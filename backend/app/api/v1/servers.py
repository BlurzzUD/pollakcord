import hashlib
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.types import utcnow
from ...errors import AppError
from ...models import AuditLog, Ban, Category, Channel, Invite, MemberRole, Message, ReadState, Report, Role, Server, ServerMember, User
from ...models.enums import AuditAction, NotificationType, ReportStatus
from ...realtime.outbox import Outbox
from ...security.ratelimit import enforce
from ...services import audit, people, privacy
from ...services import servers as server_service
from ...services import uploads
from ...services.notifications import notify
from ...services.permissions import (
    ALL_PERMISSIONS,
    Perm,
    ServerContext,
    bits_to_names,
    load_context,
    names_to_bits,
    require_context,
)
from ...services.serializers import category_dict, channel_dict, iso, media_url, role_dict, server_summary, sid
from ..deps import Auth, get_db, get_language, get_outbox, get_settings, require_auth
from .messaging import report_summary

router = APIRouter(prefix="/servers", tags=["servers"])
MODERATION_KEYS = {"reports_enabled": bool, "invites_enabled": bool, "max_mentions_per_message": int}


class ServerCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class ServerUpdateBody(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    moderation_settings: dict[str, Any] | None = None
    owner_id: str | None = Field(default=None, max_length=24)


class ServerDeleteBody(BaseModel):
    confirm_name: str = Field(max_length=80)


class MemberUpdateBody(BaseModel):
    nickname: str | None = Field(default=None, max_length=60)
    role_ids: list[str] | None = None
    timeout_minutes: int | None = Field(default=None, ge=0, le=server_service.MAX_TIMEOUT_MINUTES)


class RoleBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str | None = Field(default=None, max_length=7)
    permissions: list[str] = Field(default_factory=list, max_length=40)
    position: int | None = Field(default=None, ge=0, le=1000)


class RoleUpdateBody(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    color: str | None = Field(default=None, max_length=7)
    clear_color: bool = False
    permissions: list[str] | None = Field(default=None, max_length=40)
    position: int | None = Field(default=None, ge=0, le=1000)


class BanBody(BaseModel):
    reason: str = Field(default="", max_length=300)


class InviteBody(BaseModel):
    max_uses: int | None = Field(default=None, ge=1, le=1000)
    expires_in_hours: int | None = Field(default=None, ge=1, le=720)


class InviteFriendsBody(BaseModel):
    user_ids: list[str] = Field(max_length=25)
    invite_code: str = Field(max_length=24)


class ResolveBody(BaseModel):
    resolution: str = Field(pattern="^(dismissed|resolved)$")
    note: str = Field(default="", max_length=500)


def valid_color(value: str | None) -> str | None:
    import re

    if value is None:
        return None
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise AppError("settings_invalid", 422)
    return value.lower()


async def unread_by_channel(db: AsyncSession, user_id: int, channel_ids: list[int]) -> dict[str, int]:
    if not channel_ids:
        return {}
    statement = (
        select(Message.channel_id, func.count())
        .outerjoin(ReadState, (ReadState.user_id == user_id) & (ReadState.scope_type == "channel") & (ReadState.scope_id == Message.channel_id))
        .where(
            Message.channel_id.in_(channel_ids),
            Message.deleted_at.is_(None),
            Message.author_id != user_id,
            Message.id > func.coalesce(ReadState.last_read_message_id, 0),
        )
        .group_by(Message.channel_id)
    )
    return {str(cid): count for cid, count in (await db.execute(statement)).all()}


async def build_detail(request: Request, db: AsyncSession, context: ServerContext) -> dict[str, Any]:
    server = context.server
    channels = list((await db.execute(select(Channel).where(Channel.server_id == server.id).order_by(Channel.position, Channel.id))).scalars())
    visible = [c for c in channels if context.visible_channel(c)]
    categories = list((await db.execute(select(Category).where(Category.server_id == server.id).order_by(Category.position, Category.id))).scalars())
    shown_categories = categories if context.can(Perm.MANAGE_CHANNELS) else [cat for cat in categories if any(c.category_id == cat.id for c in visible)]
    voice_ids = [c.id for c in visible if c.type == "voice"]
    detail = server_summary(server, await server_service.member_count(db, server.id))
    detail.update(
        {
            "moderation_settings": server.moderation_settings,
            "is_owner": context.is_owner,
            "my_permissions": context.base,
            "my_permission_names": bits_to_names(context.base),
            "my_role_ids": [sid(r) for r in context.member_role_ids],
            "roles": [role_dict(r) for r in sorted(context.roles.values(), key=lambda r: -r.position)],
            "categories": [category_dict(c) for c in shown_categories],
            "channels": [
                {**channel_dict(c), "my_permissions": context.channel_permissions(c)} for c in visible
            ],
            "voice_states": request.app.state.voice.channel_states(voice_ids),
            "unread": await unread_by_channel(db, context.user_id, [c.id for c in visible if c.type == "text"]),
        }
    )
    return detail


@router.post("")
async def create_server(
    body: ServerCreateBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), language: str = Depends(get_language)
) -> dict:
    enforce(request, "server-create", 10, 3600, subject=str(auth.user.id))
    name = server_service.normalize_label(body.name, lowercase=False)
    from ...models import UserSettings

    settings_row = await db.get(UserSettings, auth.user.id)
    server, invite = await server_service.create_server(db, auth.user, name, body.description.strip(), settings_row.language if settings_row else language)
    await db.commit()
    request.app.state.hub.subscribe_user(auth.user.id, f"server:{server.id}")
    context = await require_context(db, server.id, auth.user.id)
    detail = await build_detail(request, db, context)
    detail["invite_code"] = invite.code
    return detail


@router.get("")
async def list_servers(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(select(Server).join(ServerMember, ServerMember.server_id == Server.id).where(ServerMember.user_id == auth.user.id).order_by(ServerMember.joined_at))
    ).scalars().all()
    return [server_summary(s) for s in rows]


@router.get("/{server_id}")
async def get_server(server_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    context = await require_context(db, server_id, auth.user.id)
    return await build_detail(request, db, context)


def validate_moderation_settings(value: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, item in value.items():
        expected = MODERATION_KEYS.get(key)
        if expected is None or isinstance(item, bool) != (expected is bool) or not isinstance(item, expected):
            raise AppError("settings_invalid", 422)
        if key == "max_mentions_per_message" and not 1 <= item <= 50:
            raise AppError("settings_invalid", 422)
        merged[key] = item
    return merged


@router.patch("/{server_id}")
async def update_server(
    server_id: int, body: ServerUpdateBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict:
    context = await require_context(db, server_id, auth.user.id)
    server = context.server
    changed: dict[str, Any] = {}
    if body.name is not None or body.description is not None or body.moderation_settings is not None:
        context.require(Perm.MANAGE_SERVER)
    if body.name is not None:
        server.name = server_service.normalize_label(body.name, lowercase=False)
        changed["name"] = server.name
    if body.description is not None:
        server.description = body.description.strip()
        changed["description_changed"] = True
    if body.moderation_settings is not None:
        server.moderation_settings = validate_moderation_settings(body.moderation_settings, server.moderation_settings)
        changed["moderation_settings"] = True
    if body.owner_id is not None:
        if not context.is_owner:
            raise AppError("forbidden", 403)
        if not body.owner_id.isdigit() or await db.get(ServerMember, (server_id, int(body.owner_id))) is None:
            raise AppError("not_found", 404)
        server.owner_id = int(body.owner_id)
        changed["owner_id"] = server.owner_id
    audit.record(db, AuditAction.SERVER_UPDATE, actor_id=auth.user.id, server_id=server_id, target_type="server", target_id=server_id, details=changed)
    await db.commit()
    outbox.topic(f"server:{server_id}", "server.updated", {"server_id": sid(server_id)})
    outbox.revalidate_server(server_id)
    await outbox.flush()
    context = await require_context(db, server_id, auth.user.id)
    return await build_detail(request, db, context)


@router.post("/{server_id}/icon")
async def upload_icon(
    server_id: int, request: Request, file: UploadFile = File(...), auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict:
    enforce(request, "upload", 20, 3600, subject=str(auth.user.id))
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.MANAGE_SERVER)
    settings = get_settings(request)
    data = await uploads.process_image_upload("server_icon", file, settings)
    previous = context.server.icon_key
    context.server.icon_key = uploads.store_image(settings, "server_icon", data)
    audit.record(db, AuditAction.SERVER_UPDATE, actor_id=auth.user.id, server_id=server_id, target_type="server", target_id=server_id, details={"icon": "changed"})
    await db.commit()
    uploads.delete_image(settings, "server_icon", previous)
    outbox.topic(f"server:{server_id}", "server.updated", {"server_id": sid(server_id)})
    await outbox.flush()
    return {"icon_url": media_url("server_icon", context.server.icon_key)}


@router.delete("/{server_id}/icon")
async def remove_icon(server_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.MANAGE_SERVER)
    previous = context.server.icon_key
    context.server.icon_key = None
    audit.record(db, AuditAction.SERVER_UPDATE, actor_id=auth.user.id, server_id=server_id, target_type="server", target_id=server_id, details={"icon": "removed"})
    await db.commit()
    uploads.delete_image(get_settings(request), "server_icon", previous)
    outbox.topic(f"server:{server_id}", "server.updated", {"server_id": sid(server_id)})
    await outbox.flush()
    return {"icon_url": None}


@router.delete("/{server_id}")
async def delete_server(
    server_id: int, body: ServerDeleteBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    context = await require_context(db, server_id, auth.user.id)
    if not context.is_owner:
        raise AppError("forbidden", 403)
    if body.confirm_name.strip() != context.server.name:
        raise AppError("confirmation_mismatch", 422)
    member_ids = list((await db.execute(select(ServerMember.user_id).where(ServerMember.server_id == server_id))).scalars())
    channel_ids = await server_service.server_channel_ids(db, server_id)
    icon = context.server.icon_key
    await db.execute(delete(Message).where(Message.channel_id.in_(channel_ids)))
    await db.execute(delete(Server).where(Server.id == server_id))
    await db.commit()
    uploads.delete_image(get_settings(request), "server_icon", icon)
    for member_id in member_ids:
        outbox.evict_server(member_id, server_id, channel_ids)
        outbox.user(member_id, "server.removed", {"server_id": sid(server_id), "reason": "deleted"})
    await outbox.flush()
    return {"status": "deleted"}


async def detach_member(request: Request, db: AsyncSession, outbox: Outbox, server_id: int, user_id: int, reason: str) -> None:
    from ...realtime.ws import force_leave_voice

    channel_ids = await server_service.server_channel_ids(db, server_id)
    await server_service.remove_member(db, server_id, user_id)
    await db.commit()
    outbox.evict_server(user_id, server_id, channel_ids)
    outbox.topic(f"server:{server_id}", "member.left", {"server_id": sid(server_id), "user_id": sid(user_id)})
    outbox.user(user_id, "server.removed", {"server_id": sid(server_id), "reason": reason})
    await outbox.flush()
    await force_leave_voice(request.app, user_id, server_id)


@router.post("/{server_id}/leave")
async def leave_server(server_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    context = await require_context(db, server_id, auth.user.id)
    if context.is_owner:
        raise AppError("owner_cannot_leave", 409)
    await detach_member(request, db, outbox, server_id, auth.user.id, "left")
    return {"status": "left"}


@router.get("/{server_id}/members")
async def list_members(
    server_id: int,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    after: str | None = None,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    context = await require_context(db, server_id, auth.user.id)
    statement = select(ServerMember).where(ServerMember.server_id == server_id).order_by(ServerMember.user_id).limit(limit)
    if after and after.isdigit():
        statement = statement.where(ServerMember.user_id > int(after))
    members = list((await db.execute(statement)).scalars())
    ids = {m.user_id for m in members}
    cards = await people.load_cards(db, ids)
    presence = await people.presence_map(db, request.app.state.hub, auth.user.id, ids)
    role_rows = (await db.execute(select(MemberRole.user_id, MemberRole.role_id).where(MemberRole.server_id == server_id, MemberRole.user_id.in_(ids)))).all()
    roles_by_user: dict[int, list[str]] = {}
    for user_id, role_id in role_rows:
        roles_by_user.setdefault(user_id, []).append(sid(role_id))
    items = [
        {
            "user": cards.get(m.user_id),
            "nickname": m.nickname,
            "role_ids": roles_by_user.get(m.user_id, []),
            "joined_at": iso(m.joined_at),
            "timeout_until": iso(m.timeout_until) if m.timeout_until and m.timeout_until > utcnow() else None,
            "presence": presence.get(m.user_id),
            "is_owner": m.user_id == context.server.owner_id,
        }
        for m in members
    ]
    return {"members": items, "has_more": len(members) == limit}


@router.patch("/{server_id}/members/{user_id}")
async def update_member(
    server_id: int, user_id: int, body: MemberUpdateBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    actor = await require_context(db, server_id, auth.user.id)
    target = actor if user_id == auth.user.id else await load_context(db, server_id, user_id)
    if target is None:
        raise AppError("not_found", 404)
    fields = body.model_fields_set
    details: dict[str, Any] = {}
    if "nickname" in fields:
        if user_id != auth.user.id:
            actor.require(Perm.MANAGE_MEMBERS)
            if not actor.outranks(target):
                raise AppError("role_hierarchy", 403)
        nickname = server_service.normalize_label(body.nickname, lowercase=False, limit=40) if body.nickname else None
        target.member.nickname = nickname
        details["nickname"] = nickname
        audit.record(db, AuditAction.MEMBER_UPDATE, actor_id=auth.user.id, server_id=server_id, target_type="user", target_id=user_id, details=details)
    if "timeout_minutes" in fields and body.timeout_minutes is not None:
        actor.require(Perm.MANAGE_MEMBERS)
        if user_id == auth.user.id or not actor.outranks(target):
            raise AppError("role_hierarchy", 403)
        target.member.timeout_until = utcnow() + timedelta(minutes=body.timeout_minutes) if body.timeout_minutes else None
        audit.record(db, AuditAction.MEMBER_TIMEOUT, actor_id=auth.user.id, server_id=server_id, target_type="user", target_id=user_id, details={"minutes": body.timeout_minutes})
        if body.timeout_minutes:
            await notify(db, outbox, user_id, NotificationType.MODERATION, {"kind": "timeout", "server_id": sid(server_id), "server_name": actor.server.name, "minutes": body.timeout_minutes})
    if "role_ids" in fields and body.role_ids is not None:
        actor.require(Perm.MANAGE_ROLES)
        editing_self = user_id == auth.user.id
        if (editing_self and not actor.is_owner) or (not editing_self and not actor.outranks(target)):
            raise AppError("role_hierarchy", 403)
        wanted = set()
        for raw in body.role_ids:
            if not raw.isdigit() or int(raw) not in actor.roles or actor.roles[int(raw)].is_default:
                raise AppError("not_found", 404)
            wanted.add(int(raw))
        changed = wanted.symmetric_difference(target.member_role_ids)
        for role_id in changed:
            if not actor.outranks_role(actor.roles[role_id]):
                raise AppError("role_hierarchy", 403)
        await db.execute(delete(MemberRole).where(MemberRole.server_id == server_id, MemberRole.user_id == user_id))
        for role_id in wanted:
            db.add(MemberRole(server_id=server_id, user_id=user_id, role_id=role_id))
        audit.record(
            db,
            AuditAction.MEMBER_ROLES,
            actor_id=auth.user.id,
            server_id=server_id,
            target_type="user",
            target_id=user_id,
            details={"added": [actor.roles[r].name for r in wanted - target.member_role_ids], "removed": [actor.roles[r].name for r in target.member_role_ids - wanted]},
        )
    await db.commit()
    outbox.topic(f"server:{server_id}", "member.updated", {"server_id": sid(server_id), "user_id": sid(user_id)})
    outbox.revalidate_server(server_id)
    await outbox.flush()
    return {"status": "updated"}


@router.delete("/{server_id}/members/{user_id}")
async def kick_member(server_id: int, user_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    actor = await require_context(db, server_id, auth.user.id)
    actor.require(Perm.KICK_MEMBERS)
    target = await load_context(db, server_id, user_id)
    if target is None or user_id == auth.user.id:
        raise AppError("not_found", 404)
    if not actor.outranks(target):
        raise AppError("role_hierarchy", 403)
    audit.record(db, AuditAction.MEMBER_KICK, actor_id=auth.user.id, server_id=server_id, target_type="user", target_id=user_id)
    await notify(db, outbox, user_id, NotificationType.MODERATION, {"kind": "kick", "server_id": sid(server_id), "server_name": actor.server.name})
    await detach_member(request, db, outbox, server_id, user_id, "kicked")
    return {"status": "kicked"}


@router.get("/{server_id}/bans")
async def list_bans(server_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.BAN_MEMBERS)
    rows = (await db.execute(select(Ban).where(Ban.server_id == server_id).order_by(Ban.created_at.desc()).limit(200))).scalars().all()
    cards = await people.load_cards(db, {b.user_id for b in rows})
    return [{"user": cards.get(b.user_id), "reason": b.reason, "created_at": iso(b.created_at)} for b in rows]


@router.put("/{server_id}/bans/{user_id}")
async def ban_member(
    server_id: int, user_id: int, body: BanBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    actor = await require_context(db, server_id, auth.user.id)
    actor.require(Perm.BAN_MEMBERS)
    if user_id == auth.user.id or user_id == actor.server.owner_id or await db.get(User, user_id) is None:
        raise AppError("not_found", 404)
    target = await load_context(db, server_id, user_id)
    if target is not None and not actor.outranks(target):
        raise AppError("role_hierarchy", 403)
    if await db.get(Ban, (server_id, user_id)) is None:
        db.add(Ban(server_id=server_id, user_id=user_id, reason=body.reason.strip(), banned_by=auth.user.id))
    audit.record(db, AuditAction.MEMBER_BAN, actor_id=auth.user.id, server_id=server_id, target_type="user", target_id=user_id, details={"reason": body.reason.strip()})
    await notify(db, outbox, user_id, NotificationType.MODERATION, {"kind": "ban", "server_id": sid(server_id), "server_name": actor.server.name})
    if target is not None:
        await detach_member(request, db, outbox, server_id, user_id, "banned")
    else:
        await db.commit()
        await outbox.flush()
    return {"status": "banned"}


@router.delete("/{server_id}/bans/{user_id}")
async def unban_member(server_id: int, user_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.BAN_MEMBERS)
    ban = await db.get(Ban, (server_id, user_id))
    if ban is None:
        raise AppError("not_found", 404)
    await db.delete(ban)
    audit.record(db, AuditAction.MEMBER_UNBAN, actor_id=auth.user.id, server_id=server_id, target_type="user", target_id=user_id)
    await db.commit()
    return {"status": "unbanned"}


def check_grantable(actor: ServerContext, bits: int) -> None:
    if not actor.is_owner and bits & ~actor.base:
        raise AppError("cannot_grant_permission", 403)


@router.get("/{server_id}/roles")
async def list_roles(server_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    context = await require_context(db, server_id, auth.user.id)
    return [role_dict(r) for r in sorted(context.roles.values(), key=lambda r: -r.position)]


@router.post("/{server_id}/roles")
async def create_role(server_id: int, body: RoleBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    actor = await require_context(db, server_id, auth.user.id)
    actor.require(Perm.MANAGE_ROLES)
    if len(actor.roles) >= server_service.MAX_ROLES:
        raise AppError("role_limit_reached", 409)
    bits = names_to_bits(body.permissions)
    check_grantable(actor, bits)
    position = body.position if body.position is not None else server_service.CUSTOM_ROLE_DEFAULT_POSITION
    if not actor.is_owner and position >= actor.top_position:
        raise AppError("role_hierarchy", 403)
    role = Role(
        server_id=server_id,
        name=server_service.normalize_label(body.name, lowercase=False, limit=40),
        color=valid_color(body.color),
        position=position,
        permissions=bits,
        kind="custom",
    )
    db.add(role)
    await db.flush()
    audit.record(db, AuditAction.ROLE_CREATE, actor_id=auth.user.id, server_id=server_id, target_type="role", target_id=role.id, details={"name": role.name, "permissions": bits_to_names(bits)})
    await db.commit()
    outbox.topic(f"server:{server_id}", "role.changed", {"server_id": sid(server_id)})
    await outbox.flush()
    return role_dict(role)


@router.patch("/{server_id}/roles/{role_id}")
async def update_role(
    server_id: int, role_id: int, body: RoleUpdateBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict:
    actor = await require_context(db, server_id, auth.user.id)
    actor.require(Perm.MANAGE_ROLES)
    role = actor.roles.get(role_id)
    if role is None:
        raise AppError("not_found", 404)
    if not actor.outranks_role(role) and not (role.is_default and actor.is_owner):
        raise AppError("role_hierarchy", 403)
    details: dict[str, Any] = {"name": role.name}
    if body.name is not None:
        role.name = server_service.normalize_label(body.name, lowercase=False, limit=40)
    if body.clear_color:
        role.color = None
    elif body.color is not None:
        role.color = valid_color(body.color)
    if body.permissions is not None:
        bits = names_to_bits(body.permissions)
        check_grantable(actor, bits)
        details["permissions"] = bits_to_names(bits)
        role.permissions = bits
    if body.position is not None and not role.is_default:
        if not actor.is_owner and body.position >= actor.top_position:
            raise AppError("role_hierarchy", 403)
        role.position = body.position
    audit.record(db, AuditAction.ROLE_UPDATE, actor_id=auth.user.id, server_id=server_id, target_type="role", target_id=role.id, details=details)
    await db.commit()
    outbox.topic(f"server:{server_id}", "role.changed", {"server_id": sid(server_id)})
    outbox.revalidate_server(server_id)
    await outbox.flush()
    return role_dict(role)


@router.delete("/{server_id}/roles/{role_id}")
async def delete_role(server_id: int, role_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    actor = await require_context(db, server_id, auth.user.id)
    actor.require(Perm.MANAGE_ROLES)
    role = actor.roles.get(role_id)
    if role is None:
        raise AppError("not_found", 404)
    if role.is_default or role.kind != "custom":
        raise AppError("role_protected", 409)
    if not actor.outranks_role(role):
        raise AppError("role_hierarchy", 403)
    audit.record(db, AuditAction.ROLE_DELETE, actor_id=auth.user.id, server_id=server_id, target_type="role", target_id=role.id, details={"name": role.name})
    await db.delete(role)
    await db.commit()
    outbox.topic(f"server:{server_id}", "role.changed", {"server_id": sid(server_id)})
    outbox.revalidate_server(server_id)
    await outbox.flush()
    return {"status": "deleted"}


def invite_dict(invite: Invite, creator: dict | None = None) -> dict:
    return {
        "code": invite.code,
        "creator": creator,
        "uses": invite.uses,
        "max_uses": invite.max_uses,
        "expires_at": iso(invite.expires_at),
        "revoked": invite.revoked_at is not None,
        "created_at": iso(invite.created_at),
    }


@router.get("/{server_id}/invites")
async def list_invites(server_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.CREATE_INVITE)
    statement = select(Invite).where(Invite.server_id == server_id, Invite.revoked_at.is_(None)).order_by(Invite.created_at.desc()).limit(100)
    if not context.can(Perm.MANAGE_SERVER):
        statement = statement.where(Invite.creator_id == auth.user.id)
    rows = (await db.execute(statement)).scalars().all()
    cards = await people.load_cards(db, {r.creator_id for r in rows if r.creator_id})
    return [invite_dict(r, cards.get(r.creator_id)) for r in rows]


@router.post("/{server_id}/invites")
async def create_invite(
    server_id: int, body: InviteBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict:
    enforce(request, "invite-create", 30, 3600, subject=str(auth.user.id))
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.CREATE_INVITE)
    if not context.server.moderation_settings.get("invites_enabled", True) and not context.can(Perm.MANAGE_SERVER):
        raise AppError("invites_disabled", 403)
    invite = await server_service.new_invite(db, server_id, auth.user.id, body.max_uses, body.expires_in_hours)
    audit.record(db, AuditAction.INVITE_CREATE, actor_id=auth.user.id, server_id=server_id, target_type="invite", target_id=invite.id, details={"max_uses": body.max_uses, "expires_in_hours": body.expires_in_hours})
    await db.commit()
    return invite_dict(invite)


@router.delete("/{server_id}/invites/{code}")
async def revoke_invite(server_id: int, code: str, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    context = await require_context(db, server_id, auth.user.id)
    invite = (await db.execute(select(Invite).where(Invite.code == code, Invite.server_id == server_id))).scalar_one_or_none()
    if invite is None:
        raise AppError("not_found", 404)
    if invite.creator_id != auth.user.id:
        context.require(Perm.MANAGE_SERVER)
    invite.revoked_at = utcnow()
    audit.record(db, AuditAction.INVITE_REVOKE, actor_id=auth.user.id, server_id=server_id, target_type="invite", target_id=invite.id)
    await db.commit()
    return {"status": "revoked"}


@router.post("/{server_id}/invite-friends")
async def invite_friends(
    server_id: int, body: InviteFriendsBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, int]:
    enforce(request, "invite-friends", 20, 3600, subject=str(auth.user.id))
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.CREATE_INVITE)
    invite = (await db.execute(select(Invite).where(Invite.code == body.invite_code, Invite.server_id == server_id, Invite.revoked_at.is_(None)))).scalar_one_or_none()
    if invite is None:
        raise AppError("invite_invalid", 404)
    friends = await privacy.friend_ids(db, auth.user.id)
    cards = await people.load_cards(db, {auth.user.id})
    sent = 0
    for raw in body.user_ids:
        if raw.isdigit() and int(raw) in friends:
            await notify(
                db,
                outbox,
                int(raw),
                NotificationType.SERVER,
                {"kind": "invite", "server_id": sid(server_id), "server_name": context.server.name, "invite_code": invite.code, "user": cards[auth.user.id]},
            )
            sent += 1
    await db.commit()
    await outbox.flush()
    return {"sent": sent}


@router.get("/{server_id}/audit-logs")
async def audit_logs(
    server_id: int, before: str | None = None, limit: int = Query(default=50, ge=1, le=100), auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.VIEW_AUDIT_LOG)
    statement = select(AuditLog).where(AuditLog.server_id == server_id).order_by(AuditLog.id.desc()).limit(limit)
    if before and before.isdigit():
        statement = statement.where(AuditLog.id < int(before))
    rows = (await db.execute(statement)).scalars().all()
    cards = await people.load_cards(db, {r.actor_id for r in rows if r.actor_id} | {r.target_id for r in rows if r.target_type == "user" and r.target_id})
    entries = [
        {
            "id": sid(r.id),
            "action": r.action,
            "actor": cards.get(r.actor_id),
            "target_type": r.target_type,
            "target_id": sid(r.target_id),
            "target_user": cards.get(r.target_id) if r.target_type == "user" else None,
            "details": r.details,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]
    return {"entries": entries, "has_more": len(rows) == limit}


@router.get("/{server_id}/reports")
async def server_reports(
    server_id: int, request: Request, status: str = Query(default="open", pattern="^(open|resolved|dismissed)$"), auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.MANAGE_MESSAGES)
    rows = (await db.execute(select(Report).where(Report.server_id == server_id, Report.status == status).order_by(Report.id.desc()).limit(100))).scalars().all()
    cards = await people.load_cards(db, {r.target_user_id for r in rows if r.target_user_id} | {r.reporter_id for r in rows if r.reporter_id})
    service = request.app.state.messages
    result = []
    for report in rows:
        entry = report_summary(report)
        entry["target"] = cards.get(report.target_user_id)
        entry["reporter"] = cards.get(report.reporter_id)
        entry["context"] = service.open_snapshot(report.id, report.snapshot_enc, report.key_id) if report.snapshot_enc else []
        result.append(entry)
    return result


@router.post("/{server_id}/reports/{report_id}/resolve")
async def resolve_server_report(
    server_id: int, report_id: int, body: ResolveBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.MANAGE_MESSAGES)
    report = await db.get(Report, report_id)
    if report is None or report.server_id != server_id:
        raise AppError("not_found", 404)
    report.status = ReportStatus.DISMISSED.value if body.resolution == "dismissed" else ReportStatus.RESOLVED.value
    report.resolution = body.resolution
    report.note = body.note.strip()
    report.handled_by = auth.user.id
    report.handled_at = utcnow()
    audit.record(db, AuditAction.REPORT_RESOLVE, actor_id=auth.user.id, server_id=server_id, target_type="report", target_id=report.id, details={"resolution": body.resolution})
    await db.commit()
    return report_summary(report)
