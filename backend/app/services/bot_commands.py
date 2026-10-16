import asyncio
import re
from datetime import timedelta
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.types import utcnow
from ..errors import AppError
from ..models import BotApplication, BotCommand, BotInstall, BotInteraction, Channel, Profile, ServerMember, User
from ..models.enums import ScopeKind
from ..realtime.outbox import Outbox
from ..security.bots import BotAuth, INTERACTION_TIMEOUT_SECONDS, MAX_COMMANDS_PER_BOT, bot_rate
from .bots import BOT_INSTALL_PERMISSIONS, prune_interactions
from .messages import MessageScope
from .permissions import Perm, load_channel_context, load_context, names_to_bits
from .serializers import sid, user_card


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommandOption(StrictBody):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    description: str = Field(min_length=1, max_length=100)
    type: Literal["string", "int", "bool", "channel", "user"]
    required: bool = False


class CommandDefinition(StrictBody):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    description: str = Field(min_length=1, max_length=100)
    options: list[CommandOption] = Field(default_factory=list, max_length=10)
    default_member_permissions: list[str] = Field(default_factory=list, max_length=20)


class RegisterBody(StrictBody):
    commands: list[CommandDefinition] = Field(max_length=MAX_COMMANDS_PER_BOT)


class InvokeBody(StrictBody):
    command_id: str = Field(pattern=r"^[0-9]{1,19}$")
    options: dict[str, Any] = Field(default_factory=dict, max_length=10)


class BotMessageBody(StrictBody):
    content: str = Field(min_length=1, max_length=8000)


def command_payload(command: BotCommand, card: dict | None = None) -> dict:
    return {"id": sid(command.id), "bot_id": sid(command.bot_user_id), "name": command.name, "description": command.description, "options": command.options, "default_member_permissions": command.default_member_permissions, **({"bot": card} if card else {})}


async def register_commands(db: AsyncSession, bot_id: int, body: RegisterBody) -> list[dict]:
    if len({command.name for command in body.commands}) != len(body.commands):
        raise AppError("bot_commands_invalid", 422)
    await db.execute(select(BotApplication.bot_user_id).where(BotApplication.bot_user_id == bot_id).with_for_update())
    existing = {row.name: row for row in (await db.execute(select(BotCommand).where(BotCommand.bot_user_id == bot_id))).scalars()}
    wanted = {definition.name for definition in body.commands}
    for name, command in existing.items():
        if name not in wanted:
            await db.delete(command)
    rows = []
    for definition in body.commands:
        if len({option.name for option in definition.options}) != len(definition.options) or not definition.description.strip() or any(not o.description.strip() for o in definition.options):
            raise AppError("bot_commands_invalid", 422)
        required = names_to_bits(definition.default_member_permissions)
        if required & ~(BOT_INSTALL_PERMISSIONS | int(Perm.ADMINISTRATOR)):
            raise AppError("bot_commands_invalid", 422)
        command = existing.get(definition.name)
        if command is None:
            command = BotCommand(bot_user_id=bot_id, name=definition.name)
            db.add(command)
        command.description = definition.description.strip()
        command.options = [option.model_dump() for option in definition.options]
        command.default_member_permissions = required
        rows.append(command)
    await db.flush()
    return [command_payload(row) for row in rows]


async def available_commands(db: AsyncSession, channel_id: int, user_id: int) -> list[dict]:
    channel, human = await load_channel_context(db, channel_id, user_id)
    if channel.type != "text":
        return []
    human.require_in(channel, Perm.SEND_MESSAGES)
    rows = (await db.execute(select(BotCommand, BotApplication, User, Profile).join(BotApplication, BotApplication.bot_user_id == BotCommand.bot_user_id).join(User, User.id == BotCommand.bot_user_id).outerjoin(Profile, Profile.user_id == User.id).join(BotInstall, (BotInstall.bot_user_id == BotCommand.bot_user_id) & (BotInstall.server_id == channel.server_id)).where(BotApplication.deleted_at.is_(None), User.status == "active").order_by(BotCommand.name, BotCommand.id))).all()
    result = []
    contexts = {}
    for command, application, bot, profile in rows:
        owner = await db.get(User, application.owner_id)
        if owner is None or owner.is_bot or owner.status != "active":
            continue
        if bot.id not in contexts:
            contexts[bot.id] = await load_context(db, channel.server_id, bot.id)
        context = contexts[bot.id]
        if context is None or not context.can_in(channel, Perm.VIEW_CHANNEL) or not context.can_in(channel, Perm.SEND_MESSAGES):
            continue
        required = command.default_member_permissions
        if human.channel_permissions(channel) & required != required:
            continue
        result.append(command_payload(command, user_card(bot, profile)))
    return result


async def validate_options(db: AsyncSession, command: BotCommand, options: dict, channel: Channel, human_id: int, bot_id: int) -> dict:
    definitions = {option["name"]: option for option in command.options}
    if set(options) - set(definitions):
        raise AppError("bot_options_invalid", 422)
    for name, definition in definitions.items():
        if name not in options:
            if definition["required"]:
                raise AppError("bot_options_invalid", 422)
            continue
        value = options[name]
        kind = definition["type"]
        valid = (kind == "string" and isinstance(value, str) and len(value) <= 1000) or (kind == "int" and type(value) is int and -(2**53) < value < 2**53) or (kind == "bool" and type(value) is bool)
        if kind in ("channel", "user"):
            valid = isinstance(value, str) and bool(re.fullmatch(r"[0-9]{1,19}", value)) and 0 < int(value) < 2**63
            if valid and kind == "channel":
                target = await db.get(Channel, int(value))
                human = await load_context(db, channel.server_id, human_id)
                bot = await load_context(db, channel.server_id, bot_id)
                valid = bool(target and target.server_id == channel.server_id and target.type == "text" and human and bot and human.visible_channel(target) and bot.visible_channel(target))
            elif valid:
                valid = await db.get(ServerMember, (channel.server_id, int(value))) is not None
        if not valid:
            raise AppError("bot_options_invalid", 422)
    return options


async def invoke(db: AsyncSession, request: Request, channel_id: int, human_id: int, body: InvokeBody) -> dict:
    commands = await available_commands(db, channel_id, human_id)
    selected = next((command for command in commands if command["id"] == body.command_id), None)
    if selected is None:
        raise AppError("not_found", 404)
    command = await db.get(BotCommand, int(body.command_id))
    channel = await db.get(Channel, channel_id)
    options = await validate_options(db, command, body.options, channel, human_id, command.bot_user_id)
    manager = request.app.state.bot_gateway
    if not manager.online(command.bot_user_id):
        raise AppError("bot_offline", 409)
    await prune_interactions(db)
    interaction = BotInteraction(bot_user_id=command.bot_user_id, command_id=command.id, user_id=human_id, channel_id=channel_id, expires_at=utcnow() + timedelta(seconds=INTERACTION_TIMEOUT_SECONDS))
    db.add(interaction)
    await db.flush()
    interaction_id = interaction.id
    future = asyncio.get_running_loop().create_future()
    manager.pending[interaction_id] = future
    manager.pending_bots[interaction_id] = command.bot_user_id
    try:
        await db.commit()
        event = {"id": sid(interaction_id), "command_id": sid(command.id), "name": command.name, "options": options, "channel_id": sid(channel_id), "server_id": sid(channel.server_id), "user": {"id": sid(human_id)}, "expires_at": interaction.expires_at.isoformat()}
        if not await manager.interaction(command.bot_user_id, channel_id, event):
            await db.execute(update(BotInteraction).where(BotInteraction.id == interaction_id, BotInteraction.status == "pending").values(status="expired"))
            await db.commit()
            raise AppError("bot_offline", 409)
        remaining = max(0, (interaction.expires_at - utcnow()).total_seconds())
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
        except asyncio.TimeoutError:
            await db.execute(update(BotInteraction).where(BotInteraction.id == interaction_id, BotInteraction.status == "pending").values(status="expired"))
            await db.commit()
            if future.done():
                return future.result()
            interaction = (await db.execute(select(BotInteraction).where(BotInteraction.id == interaction_id).execution_options(populate_existing=True))).scalar_one_or_none()
            if interaction is not None and interaction.status == "responded" and interaction.response_message_id:
                from ..models import Message

                message = await db.get(Message, interaction.response_message_id)
                scope = MessageScope(ScopeKind.CHANNEL, channel_id, channel.server_id)
                return (await request.app.state.messages.payloads(db, [message], human_id, scope))[0]
            raise AppError("bot_interaction_timeout", 504)
    except AppError:
        await db.execute(update(BotInteraction).where(BotInteraction.id == interaction_id, BotInteraction.status == "pending").values(status="expired"))
        await db.commit()
        raise
    finally:
        manager.pending.pop(interaction_id, None)
        manager.pending_bots.pop(interaction_id, None)
        if not future.done():
            future.cancel()


async def send_bot_message(db: AsyncSession, request: Request, auth: BotAuth, channel_id: int, content: str, outbox: Outbox) -> dict:
    from ..api.v1.channels import enforce_slowmode, mention_targets, text_scope

    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    if await db.get(BotInstall, (channel.server_id, auth.user.id)) is None:
        raise AppError("not_found", 404)
    scope = text_scope(channel)
    context.require_in(channel, Perm.SEND_MESSAGES)
    if context.member.timeout_until is not None and context.member.timeout_until > utcnow():
        raise AppError("timed_out", 403)
    if channel.slowmode_seconds and not context.can_in(channel, Perm.MANAGE_MESSAGES):
        await enforce_slowmode(db, channel, auth.user.id)
    targets = await mention_targets(db, context, channel, content, auth.user.id)
    service = request.app.state.messages
    message, _ = await service.send(db, scope, auth.user.id, content, reply_to_id=None, mentions=targets)
    payload = (await service.payloads(db, [message], auth.user.id, scope))[0]
    outbox.topic(f"channel:{channel_id}", "message.create", payload)
    outbox.topic(f"server:{channel.server_id}", "channel.activity", {"server_id": sid(channel.server_id), "channel_id": sid(channel_id), "message_id": sid(message.id), "author_id": sid(auth.user.id)})
    return payload


async def respond(db: AsyncSession, request: Request, auth: BotAuth, interaction_id: int, content: str, outbox: Outbox) -> dict:
    bot_rate(request, auth, "send", 8, 10, 16)
    interaction = await db.get(BotInteraction, interaction_id)
    if interaction is None or interaction.bot_user_id != auth.user.id:
        raise AppError("not_found", 404)
    if interaction.user_id is None:
        raise AppError("bot_interaction_expired", 409)
    allowed = await available_commands(db, interaction.channel_id, interaction.user_id)
    if not any(command["id"] == sid(interaction.command_id) for command in allowed):
        raise AppError("not_found", 404)
    changed = await db.execute(update(BotInteraction).where(BotInteraction.id == interaction_id, BotInteraction.bot_user_id == auth.user.id, BotInteraction.status == "pending", BotInteraction.expires_at > utcnow()).values(status="responded"))
    if changed.rowcount != 1:
        raise AppError("bot_interaction_expired", 409)
    payload = await send_bot_message(db, request, auth, interaction.channel_id, content, outbox)
    if utcnow() >= interaction.expires_at:
        raise AppError("bot_interaction_expired", 409)
    await db.execute(update(BotInteraction).where(BotInteraction.id == interaction_id).values(response_message_id=int(payload["id"])))
    await db.commit()
    request.app.state.bot_gateway.complete(interaction_id, payload)
    await outbox.flush()
    return payload
