from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import AppError
from ...models import AuditLog, MemberRole, ServerMember, User
from ...models.enums import AuditAction
from ...realtime.outbox import Outbox
from ...security.bots import BotAuth, bot_rate, require_bot
from ...services import audit
from ...services import bot_resources as resources
from ...services.bot_commands import BotMessageBody, StrictBody
from ...services.permissions import Perm, load_context
from ...services.serializers import channel_dict, iso, sid
from ..deps import get_db, get_outbox
from . import channels as human_channels
from . import servers as human_servers
from .messaging import message_in_scope

router = APIRouter(prefix="/bots/api", tags=["bot resources"])
IdPath = Annotated[int, Path(gt=0, lt=2**63)]
IdQuery = Annotated[int | None, Query(gt=0, lt=2**63)]


class MemberBody(human_servers.MemberUpdateBody):
    model_config = ConfigDict(extra="forbid")
    role_ids: list[str] | None = Field(default=None, max_length=50)


class RoleBody(human_servers.RoleBody):
    model_config = ConfigDict(extra="forbid")


class RoleUpdateBody(human_servers.RoleUpdateBody):
    model_config = ConfigDict(extra="forbid")


class TextChannelBody(StrictBody):
    name: str = Field(min_length=1, max_length=80)
    topic: str = Field(default="", max_length=300)
    slowmode_seconds: int = Field(default=0, ge=0, le=21600)
    position: int | None = Field(default=None, ge=0, le=1000)


class TextChannelUpdateBody(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    topic: str | None = Field(default=None, max_length=300)
    slowmode_seconds: int | None = Field(default=None, ge=0, le=21600)
    position: int | None = Field(default=None, ge=0, le=1000)


class ReactionBody(StrictBody):
    emoji: str = Field(min_length=1, max_length=16)


class BanBody(StrictBody):
    reason: str = Field(default="", max_length=300)


class InviteBody(human_servers.InviteBody):
    model_config = ConfigDict(extra="forbid")


class ServerBody(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)


@router.get("/servers/{server_id}")
async def server(server_id: IdPath, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    return await resources.server_payload(db, await resources.server_context(db, server_id, auth.user.id))


@router.patch("/servers/{server_id}")
async def edit_server(server_id: IdPath, body: ServerBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage", 10, 60, 20)
    context = await resources.server_context(db, server_id, auth.user.id)
    context.require(Perm.MANAGE_SERVER)
    if body.name is not None:
        context.server.name = human_servers.server_service.normalize_label(body.name, lowercase=False)
    if body.description is not None:
        context.server.description = body.description.strip()
    audit.record(db, AuditAction.SERVER_UPDATE, actor_id=auth.user.id, server_id=server_id, target_type="server", target_id=server_id)
    await db.commit()
    outbox.topic(f"server:{server_id}", "server.updated", {"server_id": sid(server_id)})
    await outbox.flush()
    return await resources.server_payload(db, context)


@router.get("/servers/{server_id}/audit-logs")
async def audit_logs(server_id: IdPath, before: IdQuery = None, limit: int = Query(default=100, ge=1, le=100), auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    context = await resources.server_context(db, server_id, auth.user.id)
    context.require(Perm.VIEW_AUDIT_LOG)
    allowed = [action.value for action in AuditAction if action.value.startswith(("member.", "role.", "channel.", "category.", "server.", "message.", "invite.")) or action in (AuditAction.BOT_INSTALL, AuditAction.BOT_REMOVE)]
    statement = select(AuditLog).where(AuditLog.server_id == server_id, AuditLog.action.in_(allowed)).order_by(AuditLog.id.desc()).limit(limit)
    if before is not None:
        statement = statement.where(AuditLog.id < before)
    rows = list((await db.execute(statement)).scalars())
    return {"entries": [{"id": sid(row.id), "action": row.action, "actor_id": sid(row.actor_id), "target_type": row.target_type, "target_id": sid(row.target_id), "created_at": iso(row.created_at)} for row in rows], "has_more": len(rows) == limit}


@router.get("/servers/{server_id}/bans")
async def bans(server_id: IdPath, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> list:
    await resources.server_context(db, server_id, auth.user.id)
    return await human_servers.list_bans(server_id, auth, db)


@router.get("/channels/{channel_id}")
async def channel(channel_id: IdPath, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    row, context = await resources.text_context(db, channel_id, auth.user.id)
    return {**channel_dict(row), "my_permissions": context.channel_permissions(row)}


@router.get("/servers/{server_id}/members")
async def members(server_id: IdPath, after: IdQuery = None, limit: int = Query(default=100, ge=1, le=100), auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    context = await resources.server_context(db, server_id, auth.user.id)
    await resources.member_access(db, context)
    statement = select(ServerMember.user_id).where(ServerMember.server_id == server_id).order_by(ServerMember.user_id).limit(limit)
    if after is not None:
        statement = statement.where(ServerMember.user_id > after)
    user_ids = list((await db.execute(statement)).scalars())
    return {"members": [await resources.member_payload(db, server_id, user_id) for user_id in user_ids], "has_more": len(user_ids) == limit}


@router.get("/servers/{server_id}/members/{user_id}")
async def member(server_id: IdPath, user_id: IdPath, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    context = await resources.server_context(db, server_id, auth.user.id)
    await resources.member_access(db, context)
    if await db.get(ServerMember, (server_id, user_id)) is None:
        raise AppError("not_found", 404)
    return await resources.member_payload(db, server_id, user_id)


@router.get("/channels/{channel_id}/messages")
async def history(channel_id: IdPath, request: Request, before: IdQuery = None, after: IdQuery = None, limit: int = Query(default=50, ge=1, le=100), auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    channel, context = await resources.text_context(db, channel_id, auth.user.id)
    context.require_in(channel, Perm.READ_MESSAGE_HISTORY)
    scope = human_channels.text_scope(channel)
    rows = await request.app.state.messages.history(db, scope, before=before, after=after, limit=limit)
    return {"messages": await request.app.state.messages.payloads(db, rows, auth.user.id, scope), "has_more": len(rows) == limit}


@router.get("/channels/{channel_id}/members/{user_id}")
async def channel_member(channel_id: IdPath, user_id: IdPath, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    channel, _ = await resources.text_context(db, channel_id, auth.user.id)
    target = await load_context(db, channel.server_id, user_id)
    if target is None or not target.visible_channel(channel):
        raise AppError("not_found", 404)
    return {**await resources.member_payload(db, channel.server_id, user_id), "permissions": target.channel_permissions(channel)}


@router.get("/channels/{channel_id}/messages/{message_id}")
async def message(channel_id: IdPath, message_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    channel, context = await resources.text_context(db, channel_id, auth.user.id)
    context.require_in(channel, Perm.READ_MESSAGE_HISTORY)
    scope = human_channels.text_scope(channel)
    row = await message_in_scope(db, scope, message_id)
    if row.deleted_at is not None:
        raise AppError("not_found", 404)
    return (await request.app.state.messages.payloads(db, [row], auth.user.id, scope))[0]


@router.patch("/channels/{channel_id}/messages/{message_id}")
async def edit_message(channel_id: IdPath, message_id: IdPath, body: BotMessageBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "edit", 8, 10, 16)
    channel, context = await resources.text_context(db, channel_id, auth.user.id)
    context.require_in(channel, Perm.SEND_MESSAGES)
    scope = human_channels.text_scope(channel)
    row = await message_in_scope(db, scope, message_id)
    if row.author_id != auth.user.id or row.deleted_at is not None:
        raise AppError("not_found", 404)
    mentions = await human_channels.mention_targets(db, context, channel, body.content, auth.user.id)
    service = request.app.state.messages
    await service.edit_text(db, row, scope, body.content, mentions)
    payload = (await service.payloads(db, [row], auth.user.id, scope))[0]
    await db.commit()
    outbox.topic(f"channel:{channel_id}", "message.update", payload)
    await outbox.flush()
    return payload


@router.put("/channels/{channel_id}/messages/{message_id}/reactions")
async def add_reaction(channel_id: IdPath, message_id: IdPath, body: ReactionBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "reaction", 20, 60, 40)
    await resources.text_context(db, channel_id, auth.user.id)
    return await human_channels.toggle_reaction(request, db, outbox, auth, channel_id, message_id, body.emoji, True)


@router.delete("/channels/{channel_id}/messages/{message_id}/reactions")
async def remove_reaction(channel_id: IdPath, message_id: IdPath, body: ReactionBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "reaction", 20, 60, 40)
    await resources.text_context(db, channel_id, auth.user.id)
    return await human_channels.toggle_reaction(request, db, outbox, auth, channel_id, message_id, body.emoji, False)


@router.get("/channels/{channel_id}/pins")
async def pins(channel_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> list:
    await resources.text_context(db, channel_id, auth.user.id)
    return await human_channels.list_pins(channel_id, request, auth, db)


@router.put("/channels/{channel_id}/pins/{message_id}")
async def pin(channel_id: IdPath, message_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage-message", 10, 60, 20)
    await resources.text_context(db, channel_id, auth.user.id)
    return await human_channels.pin_message(channel_id, message_id, request, auth, db, outbox)


@router.delete("/channels/{channel_id}/pins/{message_id}")
async def unpin(channel_id: IdPath, message_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage-message", 10, 60, 20)
    await resources.text_context(db, channel_id, auth.user.id)
    return await human_channels.unpin_message(channel_id, message_id, auth, db, outbox)


@router.patch("/servers/{server_id}/members/{user_id}")
async def update_member(server_id: IdPath, user_id: IdPath, body: MemberBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "moderate", 10, 60, 20)
    actor, target = await resources.moderation_target(db, auth, server_id, user_id)
    if body.role_ids is not None:
        for raw in body.role_ids:
            if not raw.isascii() or not raw.isdigit() or len(raw) > 19 or int(raw) not in actor.roles:
                raise AppError("not_found", 404)
            role = actor.roles[int(raw)]
            if role.id not in target.member_role_ids and (role.kind != "custom" or role.permissions & ~actor.base):
                raise AppError("cannot_grant_permission", 403)
    return await human_servers.update_member(server_id, user_id, body, request, auth, db, outbox)


@router.delete("/servers/{server_id}/members/{user_id}")
async def kick(server_id: IdPath, user_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "moderate", 10, 60, 20)
    await resources.moderation_target(db, auth, server_id, user_id)
    return await human_servers.kick_member(server_id, user_id, request, auth, db, outbox)


@router.put("/servers/{server_id}/members/{user_id}/roles/{role_id}")
async def add_member_role(server_id: IdPath, user_id: IdPath, role_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    return await change_member_role(server_id, user_id, role_id, True, request, auth, db, outbox)


@router.delete("/servers/{server_id}/members/{user_id}/roles/{role_id}")
async def remove_member_role(server_id: IdPath, user_id: IdPath, role_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    return await change_member_role(server_id, user_id, role_id, False, request, auth, db, outbox)


async def change_member_role(server_id, user_id, role_id, present, request, auth, db, outbox):
    bot_rate(request, auth, "moderate", 10, 60, 20)
    actor, target = await resources.moderation_target(db, auth, server_id, user_id)
    actor.require(Perm.MANAGE_ROLES)
    role = actor.roles.get(role_id)
    if role is None:
        raise AppError("not_found", 404)
    if role.kind != "custom" or role.is_default:
        raise AppError("role_protected", 409)
    if not actor.outranks_role(role):
        raise AppError("role_hierarchy", 403)
    if present and role.permissions & ~actor.base:
        raise AppError("cannot_grant_permission", 403)
    if present and role_id not in target.member_role_ids:
        db.add(MemberRole(server_id=server_id, user_id=user_id, role_id=role_id))
    elif not present:
        await db.execute(delete(MemberRole).where(MemberRole.server_id == server_id, MemberRole.user_id == user_id, MemberRole.role_id == role_id))
    audit.record(db, AuditAction.MEMBER_ROLES, actor_id=auth.user.id, server_id=server_id, target_type="user", target_id=user_id, details={"role_id": role_id, "added": present})
    await db.commit()
    outbox.topic(f"server:{server_id}", "member.updated", {"server_id": sid(server_id), "user_id": sid(user_id)})
    outbox.revalidate_server(server_id)
    await outbox.flush()
    return {"status": "updated"}


@router.put("/servers/{server_id}/bans/{user_id}")
async def ban(server_id: IdPath, user_id: IdPath, body: BanBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "moderate", 10, 60, 20)
    await resources.moderation_target(db, auth, server_id, user_id)
    return await human_servers.ban_member(server_id, user_id, human_servers.BanBody(reason=body.reason), request, auth, db, outbox)


@router.delete("/servers/{server_id}/bans/{user_id}")
async def unban(server_id: IdPath, user_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    bot_rate(request, auth, "moderate", 10, 60, 20)
    context = await resources.server_context(db, server_id, auth.user.id)
    target = await db.get(User, user_id)
    if target is not None and (target.is_bot or user_id in (auth.owner.id, context.server.owner_id)):
        raise AppError("role_hierarchy", 403)
    return await human_servers.unban_member(server_id, user_id, auth, db)


@router.get("/servers/{server_id}/roles")
async def roles(server_id: IdPath, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> list:
    await resources.server_context(db, server_id, auth.user.id)
    return await human_servers.list_roles(server_id, auth, db)


@router.post("/servers/{server_id}/roles")
async def create_role(server_id: IdPath, body: RoleBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage", 10, 60, 20)
    context = await resources.server_context(db, server_id, auth.user.id)
    if body.position is None:
        body.position = max(0, context.top_position - 1)
    return await human_servers.create_role(server_id, body, auth, db, outbox)


async def custom_role(db, server_id, role_id, auth):
    context = await resources.server_context(db, server_id, auth.user.id)
    role = context.roles.get(role_id)
    if role is None:
        raise AppError("not_found", 404)
    if role.kind != "custom" or role.is_default:
        raise AppError("role_protected", 409)
    return context


@router.patch("/servers/{server_id}/roles/{role_id}")
async def update_role(server_id: IdPath, role_id: IdPath, body: RoleUpdateBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage", 10, 60, 20)
    context = await custom_role(db, server_id, role_id, auth)
    if context.roles[role_id].permissions & ~context.base:
        raise AppError("cannot_grant_permission", 403)
    return await human_servers.update_role(server_id, role_id, body, auth, db, outbox)


@router.delete("/servers/{server_id}/roles/{role_id}")
async def delete_role(server_id: IdPath, role_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage", 10, 60, 20)
    context = await custom_role(db, server_id, role_id, auth)
    if context.roles[role_id].permissions & ~context.base:
        raise AppError("cannot_grant_permission", 403)
    return await human_servers.delete_role(server_id, role_id, auth, db, outbox)


@router.post("/servers/{server_id}/channels")
async def create_channel(server_id: IdPath, body: TextChannelBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage", 10, 60, 20)
    await resources.server_context(db, server_id, auth.user.id)
    return await human_channels.create_channel(server_id, human_channels.ChannelBody(type="text", **body.model_dump()), auth, db, outbox)


@router.patch("/channels/{channel_id}")
async def update_channel(channel_id: IdPath, body: TextChannelUpdateBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage", 10, 60, 20)
    await resources.text_context(db, channel_id, auth.user.id)
    return await human_channels.update_channel(channel_id, human_channels.ChannelUpdateBody(**body.model_dump(exclude_unset=True)), auth, db, outbox)


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: IdPath, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    bot_rate(request, auth, "manage", 10, 60, 20)
    await resources.text_context(db, channel_id, auth.user.id)
    return await human_channels.delete_channel(channel_id, request, auth, db, outbox)


@router.post("/servers/{server_id}/invites")
async def create_invite(server_id: IdPath, body: InviteBody, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    bot_rate(request, auth, "invite", 5, 60, 10)
    await resources.server_context(db, server_id, auth.user.id)
    return await human_servers.create_invite(server_id, body, request, auth, db)


@router.get("/servers/{server_id}/invites")
async def invites(server_id: IdPath, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> list:
    await resources.server_context(db, server_id, auth.user.id)
    return await human_servers.list_invites(server_id, auth, db)


@router.delete("/servers/{server_id}/invites/{code}")
async def revoke_invite(server_id: IdPath, code: str, request: Request, auth: BotAuth = Depends(require_bot), db: AsyncSession = Depends(get_db)) -> dict:
    bot_rate(request, auth, "invite", 5, 60, 10)
    await resources.server_context(db, server_id, auth.user.id)
    return await human_servers.revoke_invite(server_id, code, auth, db)
