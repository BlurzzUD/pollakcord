from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Request, UploadFile
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import AppError
from ...models import BotApplication, BotCommand, BotInstall, BotInteraction, Message, Profile, Server, User
from ...models.enums import AuditAction
from ...realtime.outbox import Outbox
from ...security.bots import BotAuth, bot_rate, require_bot
from ...security.ratelimit import enforce
from ...services import accounts, audit, bot_commands, bots, uploads
from ...services.bot_commands import BotMessageBody, BotSendBody, InvokeBody, RegisterBody, StrictBody
from ...services.permissions import Perm, bits_to_names, load_channel_context, load_context
from ...services.serializers import channel_dict, sid, user_card
from ..deps import Auth, get_db, get_outbox, require_auth

router = APIRouter(tags=["bots"])
IdPath = Annotated[int, Path(gt=0, lt=2**63)]


class PasswordBody(StrictBody):
    password: str = Field(min_length=1, max_length=128)


class CreateBody(PasswordBody):
    username: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=40)


class ProfileBody(StrictBody):
    username: str | None = Field(default=None, max_length=32)
    display_name: str | None = Field(default=None, max_length=40)


class DeleteBody(PasswordBody):
    confirm_username: str = Field(max_length=32)


class InstallBody(StrictBody):
    bot_id: str = Field(pattern=r"^[0-9]{1,19}$")
    permissions: list[str] = Field(default_factory=lambda: list(bots.DEFAULT_BOT_PERMISSIONS), max_length=20)


@router.get("/me/bots")
async def list_owned(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(BotApplication).where(BotApplication.owner_id == auth.user.id, BotApplication.deleted_at.is_(None)).order_by(BotApplication.created_at))).scalars()
    return [await bots.application_payload(db, row) for row in rows]


@router.post("/me/bots")
async def create(body: CreateBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "bot-create", 5, 3600, subject=str(auth.user.id))
    async with request.app.state.bot_gateway.lock(f"owner:{auth.user.id}"):
        await bots.password_gate(request, db, auth.user, body.password)
        try:
            application, token = await bots.create_bot(db, request, auth.user, body.username, body.display_name)
            payload = await bots.application_payload(db, application)
            await db.commit()
        except IntegrityError as error:
            await db.rollback()
            raise AppError("username_taken", 409) from error
    return {**payload, "token": token}


@router.patch("/me/bots/{bot_id}")
async def edit(bot_id: IdPath, body: ProfileBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    async with request.app.state.bot_gateway.lock(f"bot:{bot_id}"):
        enforce(request, "bot-profile", 20, 60, subject=str(auth.user.id))
        application = await bots.owned(db, auth.user.id, bot_id)
        user = await db.get(User, bot_id)
        if body.username is not None:
            username = accounts.normalize_username(body.username)
            if await accounts.username_taken(db, username, bot_id):
                raise AppError("username_taken", 409)
            user.username = user.username_lower = username
        if body.display_name is not None:
            user.display_name = accounts.normalize_display_name(body.display_name)
        try:
            await db.commit()
        except IntegrityError as error:
            await db.rollback()
            raise AppError("username_taken", 409) from error
        return await bots.application_payload(db, application)


@router.post("/me/bots/{bot_id}/token/reveal")
@router.post("/me/bots/{bot_id}/token/regenerate")
async def regenerate(bot_id: IdPath, body: PasswordBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "bot-token-owner", 6, 600, subject=str(auth.user.id))
    enforce(request, "bot-token", 3, 600, subject=str(bot_id))
    async with request.app.state.bot_gateway.lock(f"owner:{auth.user.id}"), request.app.state.bot_gateway.lock(f"bot:{bot_id}"):
        application = await bots.owned(db, auth.user.id, bot_id, lock=True)
        await bots.password_gate(request, db, auth.user, body.password)
        token = bots.mint_token(application)
        await db.execute(update(BotInteraction).where(BotInteraction.bot_user_id == bot_id, BotInteraction.status == "pending").values(status="expired"))
        audit.record(db, AuditAction.BOT_TOKEN_REGENERATE, actor_id=auth.user.id, target_type="bot", target_id=bot_id)
        await db.commit()
        await request.app.state.bot_gateway.close_bot(bot_id)
    return {"token": token, "replaced": True}


@router.delete("/me/bots/{bot_id}")
async def delete(bot_id: IdPath, body: DeleteBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    async with request.app.state.bot_gateway.lock(f"owner:{auth.user.id}"), request.app.state.bot_gateway.lock(f"bot:{bot_id}"):
        application = await bots.owned(db, auth.user.id, bot_id, lock=True)
        user = await db.get(User, bot_id)
        if body.confirm_username != user.username:
            raise AppError("confirmation_mismatch", 422)
        await bots.password_gate(request, db, auth.user, body.password)
        await bots.delete_bot(db, application, outbox)
        await db.commit()
        await request.app.state.bot_gateway.close_bot(bot_id)
        await outbox.flush()
    return {"status": "deleted"}


@router.post("/me/bots/{bot_id}/images/{kind}")
async def image(bot_id: IdPath, kind: str, request: Request, file: UploadFile = File(...), auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    async with request.app.state.bot_gateway.lock(f"bot:{bot_id}"):
        application = await bots.owned(db, auth.user.id, bot_id)
        if kind not in ("avatar", "banner"):
            raise AppError("not_found", 404)
        enforce(request, "bot-image", 20, 3600, subject=str(auth.user.id))
        settings = request.app.state.settings
        data = await uploads.process_image_upload(kind, file, settings)
        profile = await db.get(Profile, bot_id)
        field = kind + "_key"
        previous = getattr(profile, field)
        key = uploads.store_image(settings, kind, data)
        setattr(profile, field, key)
        try:
            await db.commit()
        except BaseException:
            uploads.delete_image(settings, kind, key)
            raise
        uploads.delete_image(settings, kind, previous)
        return await bots.application_payload(db, application)


@router.delete("/me/bots/{bot_id}/images/{kind}")
async def remove_image(bot_id: IdPath, kind: str, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    async with request.app.state.bot_gateway.lock(f"bot:{bot_id}"):
        application = await bots.owned(db, auth.user.id, bot_id)
        if kind not in ("avatar", "banner"):
            raise AppError("not_found", 404)
        profile = await db.get(Profile, bot_id)
        previous = getattr(profile, kind + "_key")
        setattr(profile, kind + "_key", None)
        await db.commit()
        uploads.delete_image(request.app.state.settings, kind, previous)
        return await bots.application_payload(db, application)


@router.get("/servers/{server_id}/bots")
async def integrations(server_id: IdPath, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    await bots.integration_context(db, server_id, auth.user.id)
    rows = list((await db.execute(select(BotInstall).where(BotInstall.server_id == server_id))).scalars())
    items = []
    for row in rows:
        application = await db.get(BotApplication, row.bot_user_id)
        items.append({**await bots.application_payload(db, application), "permissions": bits_to_names(row.permissions), "online": request.app.state.bot_gateway.online(row.bot_user_id)})
    return {"bots": items, "available_permissions": bits_to_names(bots.BOT_INSTALL_PERMISSIONS), "default_permissions": bots.DEFAULT_BOT_PERMISSIONS}


@router.post("/servers/{server_id}/bots")
async def install(server_id: IdPath, body: InstallBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    enforce(request, "bot-install", 10, 60, subject=str(auth.user.id))
    async with request.app.state.bot_gateway.lock(f"install:{server_id}"), request.app.state.bot_gateway.lock(f"bot:{int(body.bot_id)}"):
        await bots.install_bot(db, server_id, int(body.bot_id), auth.user.id, body.permissions)
        await db.commit()
        bots.integration_changed(outbox, server_id, int(body.bot_id))
        await outbox.flush()
    return {"status": "installed"}


@router.delete("/servers/{server_id}/bots/{bot_id}")
async def uninstall(server_id: IdPath, bot_id: IdPath, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    async with request.app.state.bot_gateway.lock(f"bot:{bot_id}"):
        await bots.integration_context(db, server_id, auth.user.id)
        install = await db.get(BotInstall, (server_id, bot_id))
        if install is None:
            raise AppError("not_found", 404)
        await bots.remove_install(db, install, auth.user.id, outbox)
        await db.commit()
        await outbox.flush()
        return {"status": "removed"}


@router.get("/channels/{channel_id}/bot-commands")
async def commands_for_channel(channel_id: IdPath, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await bot_commands.available_commands(db, channel_id, auth.user.id)


@router.post("/channels/{channel_id}/interactions")
async def invoke_command(channel_id: IdPath, body: InvokeBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "bot-invoke", 6, 10, subject=str(auth.user.id))
    return await bot_commands.invoke(db, request, channel_id, auth.user.id, body)


@router.get("/bots/api/me")
async def current(auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    return {"user": user_card(auth.user, await db.get(Profile, auth.user.id)), "bot_id": sid(auth.user.id), "owner_id": sid(auth.owner.id)}


@router.get("/bots/api/servers")
async def servers(auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(Server).join(BotInstall, BotInstall.server_id == Server.id).where(BotInstall.bot_user_id == auth.user.id))).scalars()
    result = []
    for server in rows:
        context = await load_context(db, server.id, auth.user.id)
        if context is not None:
            result.append({"id": sid(server.id), "name": server.name})
    return result


@router.get("/bots/api/servers/{server_id}/channels")
async def channels(server_id: IdPath, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> list[dict]:
    from ...models import Channel

    context = await load_context(db, server_id, auth.user.id)
    if context is None or await db.get(BotInstall, (server_id, auth.user.id)) is None:
        raise AppError("not_found", 404)
    rows = (await db.execute(select(Channel).where(Channel.server_id == server_id, Channel.type == "text").order_by(Channel.position))).scalars()
    return [{**channel_dict(channel), "my_permissions": context.channel_permissions(channel)} for channel in rows if context.visible_channel(channel)]


@router.post("/bots/api/channels/{channel_id}/messages")
async def send(channel_id: IdPath, body: BotSendBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "send", 8, 10, 16)
    async with request.app.state.bot_gateway.lock(f"send:{auth.user.id}:{channel_id}"):
        payload = await bot_commands.send_bot_message(db, request, auth, channel_id, body.content, outbox, reply_to_id=body.reply_to_id)
        await db.commit()
        await outbox.flush()
    return payload


@router.delete("/bots/api/channels/{channel_id}/messages/{message_id}")
async def delete_message(channel_id: IdPath, message_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "delete", 10, 10, 20)
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    context.require_in(channel, Perm.SEND_MESSAGES)
    message = await db.get(Message, message_id)
    if channel.type != "text" or message is None or message.channel_id != channel_id:
        raise AppError("not_found", 404)
    if message.author_id != auth.user.id:
        if not context.can_in(channel, Perm.MANAGE_MESSAGES):
            raise AppError("not_found", 404)
        from ...services.bot_resources import moderation_target
        from .channels import delete_message as remove_message

        if message.author_id is not None:
            await moderation_target(db, auth, channel.server_id, message.author_id)
        return await remove_message(channel_id, message_id, request, auth, db, outbox)
    if message.deleted_at is None:
        await request.app.state.messages.delete(db, message)
    await db.commit()
    outbox.topic(f"channel:{channel_id}", "message.delete", {"id": sid(message_id), "channel_id": sid(channel_id), "scope": "channel"})
    await outbox.flush()
    return {"status": "deleted"}


@router.get("/bots/api/commands")
async def list_commands(auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(BotCommand).where(BotCommand.bot_user_id == auth.user.id).order_by(BotCommand.name))).scalars()
    return [bot_commands.command_payload(command) for command in rows]


@router.put("/bots/api/commands")
async def register(body: RegisterBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> list[dict]:
    bot_rate(request, auth, "commands", 3, 60, 6)
    async with request.app.state.bot_gateway.lock(f"commands:{auth.user.id}"):
        payload = await bot_commands.register_commands(db, auth.user.id, body)
        await db.commit()
    return payload


@router.post("/bots/api/interactions/{interaction_id}/response")
async def response(interaction_id: IdPath, body: BotMessageBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    interaction = await db.get(BotInteraction, interaction_id)
    if interaction is None or interaction.bot_user_id != auth.user.id:
        raise AppError("not_found", 404)
    async with request.app.state.bot_gateway.lock(f"send:{auth.user.id}:{interaction.channel_id}"):
        return await bot_commands.respond(db, request, auth, interaction_id, body.content, outbox)
