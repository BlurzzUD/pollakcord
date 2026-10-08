import math
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.types import utcnow
from ...errors import AppError
from ...models import Category, Channel, Message, PermissionOverwrite, ReadState, Role, ServerMember
from ...models.enums import AuditAction, ChannelType, NotificationType, OverwriteScope, OverwriteTarget, ScopeKind
from ...realtime.outbox import Outbox
from ...security.ratelimit import enforce
from ...services import audit, people
from ...services import servers as server_service
from ...services.messages import MessageScope, extract_mentions
from ...services.notifications import notify
from ...services.permissions import CHANNEL_SCOPED, Perm, ServerContext, bits_to_names, load_channel_context, load_context, names_to_bits, require_context
from ...services.serializers import channel_dict, category_dict, sid
from ..deps import Auth, get_db, get_outbox, require_auth
from .messaging import MAX_PINS, ReactionBody, ReadBody, ReportBody, SendBody, create_report, message_in_scope, parse_id, report_summary

router = APIRouter(tags=["channels"])


class CategoryBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    position: int | None = Field(default=None, ge=0, le=1000)


class CategoryUpdateBody(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    position: int | None = Field(default=None, ge=0, le=1000)


class ChannelBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: str = Field(pattern="^(text|voice)$")
    category_id: str | None = Field(default=None, max_length=24)
    topic: str = Field(default="", max_length=300)
    user_limit: int = Field(default=0, ge=0, le=99)
    slowmode_seconds: int = Field(default=0, ge=0, le=21600)
    position: int | None = Field(default=None, ge=0, le=1000)


class ChannelUpdateBody(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    topic: str | None = Field(default=None, max_length=300)
    category_id: str | None = Field(default=None, max_length=24)
    clear_category: bool = False
    user_limit: int | None = Field(default=None, ge=0, le=99)
    slowmode_seconds: int | None = Field(default=None, ge=0, le=21600)
    position: int | None = Field(default=None, ge=0, le=1000)


class OverwriteBody(BaseModel):
    allow: list[str] = Field(default_factory=list, max_length=20)
    deny: list[str] = Field(default_factory=list, max_length=20)


def structure_changed(outbox: Outbox, server_id: int) -> None:
    outbox.topic(f"server:{server_id}", "structure.changed", {"server_id": sid(server_id)})
    outbox.revalidate_server(server_id)


async def owned_category(db: AsyncSession, server_id: int, raw: str | None) -> int | None:
    if raw is None:
        return None
    if not raw.isdigit():
        raise AppError("not_found", 404)
    category = await db.get(Category, int(raw))
    if category is None or category.server_id != server_id:
        raise AppError("not_found", 404)
    return category.id


@router.post("/servers/{server_id}/categories")
async def create_category(server_id: int, body: CategoryBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.MANAGE_CHANNELS)
    count = (await db.execute(select(func.count()).select_from(Category).where(Category.server_id == server_id))).scalar_one()
    if count >= server_service.MAX_CATEGORIES:
        raise AppError("category_limit_reached", 409)
    category = Category(server_id=server_id, name=server_service.normalize_label(body.name, lowercase=False), position=body.position if body.position is not None else count)
    db.add(category)
    await db.flush()
    audit.record(db, AuditAction.CATEGORY_CREATE, actor_id=auth.user.id, server_id=server_id, target_type="category", target_id=category.id, details={"name": category.name})
    await db.commit()
    structure_changed(outbox, server_id)
    await outbox.flush()
    return category_dict(category)


async def category_context(db: AsyncSession, category_id: int, user_id: int) -> tuple[Category, ServerContext]:
    category = await db.get(Category, category_id)
    if category is None:
        raise AppError("not_found", 404)
    return category, await require_context(db, category.server_id, user_id)


@router.patch("/categories/{category_id}")
async def update_category(category_id: int, body: CategoryUpdateBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    category, context = await category_context(db, category_id, auth.user.id)
    context.require(Perm.MANAGE_CHANNELS)
    if body.name is not None:
        category.name = server_service.normalize_label(body.name, lowercase=False)
    if body.position is not None:
        category.position = body.position
    audit.record(db, AuditAction.CATEGORY_UPDATE, actor_id=auth.user.id, server_id=category.server_id, target_type="category", target_id=category.id, details={"name": category.name})
    await db.commit()
    structure_changed(outbox, category.server_id)
    await outbox.flush()
    return category_dict(category)


@router.delete("/categories/{category_id}")
async def delete_category(category_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    category, context = await category_context(db, category_id, auth.user.id)
    context.require(Perm.MANAGE_CHANNELS)
    await db.execute(delete(PermissionOverwrite).where(PermissionOverwrite.scope_type == OverwriteScope.CATEGORY.value, PermissionOverwrite.scope_id == category.id))
    audit.record(db, AuditAction.CATEGORY_DELETE, actor_id=auth.user.id, server_id=category.server_id, target_type="category", target_id=category.id, details={"name": category.name})
    server_id = category.server_id
    await db.delete(category)
    await db.commit()
    structure_changed(outbox, server_id)
    await outbox.flush()
    return {"status": "deleted"}


@router.post("/servers/{server_id}/channels")
async def create_channel(server_id: int, body: ChannelBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    context = await require_context(db, server_id, auth.user.id)
    context.require(Perm.MANAGE_CHANNELS)
    count = (await db.execute(select(func.count()).select_from(Channel).where(Channel.server_id == server_id))).scalar_one()
    if count >= server_service.MAX_CHANNELS:
        raise AppError("channel_limit_reached", 409)
    is_text = body.type == ChannelType.TEXT.value
    channel = Channel(
        server_id=server_id,
        category_id=await owned_category(db, server_id, body.category_id),
        type=body.type,
        name=server_service.normalize_label(body.name, lowercase=is_text),
        topic=body.topic.strip() if is_text else "",
        user_limit=body.user_limit if not is_text else 0,
        slowmode_seconds=body.slowmode_seconds if is_text else 0,
        position=body.position if body.position is not None else count,
    )
    db.add(channel)
    await db.flush()
    audit.record(db, AuditAction.CHANNEL_CREATE, actor_id=auth.user.id, server_id=server_id, target_type="channel", target_id=channel.id, details={"name": channel.name, "type": channel.type})
    await db.commit()
    structure_changed(outbox, server_id)
    await outbox.flush()
    return channel_dict(channel)


async def manage_channel_context(db: AsyncSession, channel_id: int, user_id: int) -> tuple[Channel, ServerContext]:
    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise AppError("not_found", 404)
    context = await require_context(db, channel.server_id, user_id)
    if not context.visible_channel(channel):
        raise AppError("not_found", 404)
    context.require(Perm.MANAGE_CHANNELS)
    return channel, context


@router.patch("/channels/{channel_id}")
async def update_channel(channel_id: int, body: ChannelUpdateBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    channel, _ = await manage_channel_context(db, channel_id, auth.user.id)
    is_text = channel.type == ChannelType.TEXT.value
    if body.name is not None:
        channel.name = server_service.normalize_label(body.name, lowercase=is_text)
    if body.topic is not None and is_text:
        channel.topic = body.topic.strip()
    if body.clear_category:
        channel.category_id = None
    elif body.category_id is not None:
        channel.category_id = await owned_category(db, channel.server_id, body.category_id)
    if body.user_limit is not None and not is_text:
        channel.user_limit = body.user_limit
    if body.slowmode_seconds is not None and is_text:
        channel.slowmode_seconds = body.slowmode_seconds
    if body.position is not None:
        channel.position = body.position
    audit.record(db, AuditAction.CHANNEL_UPDATE, actor_id=auth.user.id, server_id=channel.server_id, target_type="channel", target_id=channel.id, details={"name": channel.name})
    await db.commit()
    structure_changed(outbox, channel.server_id)
    await outbox.flush()
    return channel_dict(channel)


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    from ...realtime.ws import close_voice_room

    channel, _ = await manage_channel_context(db, channel_id, auth.user.id)
    server_id = channel.server_id
    await db.execute(delete(PermissionOverwrite).where(PermissionOverwrite.scope_type == OverwriteScope.CHANNEL.value, PermissionOverwrite.scope_id == channel.id))
    audit.record(db, AuditAction.CHANNEL_DELETE, actor_id=auth.user.id, server_id=server_id, target_type="channel", target_id=channel.id, details={"name": channel.name, "type": channel.type})
    was_voice = channel.type == ChannelType.VOICE.value
    subscribers = request.app.state.hub.channel_subscribed_users([channel.id])
    await db.delete(channel)
    await db.commit()
    for user_id in subscribers:
        request.app.state.hub.unsubscribe_user(user_id, f"channel:{channel_id}")
    if was_voice:
        await close_voice_room(request.app, channel_id, server_id)
    structure_changed(outbox, server_id)
    await outbox.flush()
    return {"status": "deleted"}


async def put_overwrite(
    db: AsyncSession,
    outbox: Outbox,
    actor: ServerContext,
    actor_id: int,
    scope: OverwriteScope,
    scope_id: int,
    target_type: str,
    target_id: int,
    body: OverwriteBody | None,
) -> None:
    actor.require(Perm.MANAGE_CHANNELS)
    if target_type not in (OverwriteTarget.ROLE.value, OverwriteTarget.MEMBER.value):
        raise AppError("not_found", 404)
    server_id = actor.server.id
    if target_type == OverwriteTarget.ROLE.value:
        role = actor.roles.get(target_id)
        if role is None:
            raise AppError("not_found", 404)
        if not role.is_default and not actor.outranks_role(role):
            raise AppError("role_hierarchy", 403)
    elif await db.get(ServerMember, (server_id, target_id)) is None:
        raise AppError("not_found", 404)
    existing = (
        await db.execute(
            select(PermissionOverwrite).where(
                PermissionOverwrite.scope_type == scope.value,
                PermissionOverwrite.scope_id == scope_id,
                PermissionOverwrite.target_type == target_type,
                PermissionOverwrite.target_id == target_id,
            )
        )
    ).scalar_one_or_none()
    if body is None:
        if existing is not None:
            await db.delete(existing)
    else:
        allow, deny = names_to_bits(body.allow), names_to_bits(body.deny)
        if (allow | deny) & ~CHANNEL_SCOPED or allow & deny:
            raise AppError("invalid_permission", 422)
        if not actor.is_owner and allow & ~actor.base:
            raise AppError("cannot_grant_permission", 403)
        if existing is None:
            db.add(PermissionOverwrite(server_id=server_id, scope_type=scope.value, scope_id=scope_id, target_type=target_type, target_id=target_id, allow=allow, deny=deny))
        else:
            existing.allow, existing.deny = allow, deny
    audit.record(
        db,
        AuditAction.CHANNEL_PERMISSIONS,
        actor_id=actor_id,
        server_id=server_id,
        target_type=scope.value,
        target_id=scope_id,
        details={"target_type": target_type, "target_id": target_id, "cleared": body is None},
    )
    await db.commit()
    structure_changed(outbox, server_id)
    await outbox.flush()


def overwrite_dict(row: PermissionOverwrite) -> dict[str, Any]:
    return {
        "target_type": row.target_type,
        "target_id": sid(row.target_id),
        "allow": bits_to_names(row.allow),
        "deny": bits_to_names(row.deny),
    }


@router.get("/channels/{channel_id}/overwrites")
async def list_channel_overwrites(channel_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    channel, _ = await manage_channel_context(db, channel_id, auth.user.id)
    rows = (await db.execute(select(PermissionOverwrite).where(PermissionOverwrite.scope_type == OverwriteScope.CHANNEL.value, PermissionOverwrite.scope_id == channel.id))).scalars()
    return [overwrite_dict(r) for r in rows]


@router.put("/channels/{channel_id}/overwrites/{target_type}/{target_id}")
async def set_channel_overwrite(
    channel_id: int, target_type: str, target_id: int, body: OverwriteBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    channel, context = await manage_channel_context(db, channel_id, auth.user.id)
    await put_overwrite(db, outbox, context, auth.user.id, OverwriteScope.CHANNEL, channel.id, target_type, target_id, body)
    return {"status": "ok"}


@router.delete("/channels/{channel_id}/overwrites/{target_type}/{target_id}")
async def clear_channel_overwrite(
    channel_id: int, target_type: str, target_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    channel, context = await manage_channel_context(db, channel_id, auth.user.id)
    await put_overwrite(db, outbox, context, auth.user.id, OverwriteScope.CHANNEL, channel.id, target_type, target_id, None)
    return {"status": "ok"}


@router.get("/categories/{category_id}/overwrites")
async def list_category_overwrites(category_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    category, context = await category_context(db, category_id, auth.user.id)
    context.require(Perm.MANAGE_CHANNELS)
    rows = (await db.execute(select(PermissionOverwrite).where(PermissionOverwrite.scope_type == OverwriteScope.CATEGORY.value, PermissionOverwrite.scope_id == category.id))).scalars()
    return [overwrite_dict(r) for r in rows]


@router.put("/categories/{category_id}/overwrites/{target_type}/{target_id}")
async def set_category_overwrite(
    category_id: int, target_type: str, target_id: int, body: OverwriteBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    category, context = await category_context(db, category_id, auth.user.id)
    await put_overwrite(db, outbox, context, auth.user.id, OverwriteScope.CATEGORY, category.id, target_type, target_id, body)
    return {"status": "ok"}


@router.delete("/categories/{category_id}/overwrites/{target_type}/{target_id}")
async def clear_category_overwrite(
    category_id: int, target_type: str, target_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    category, context = await category_context(db, category_id, auth.user.id)
    await put_overwrite(db, outbox, context, auth.user.id, OverwriteScope.CATEGORY, category.id, target_type, target_id, None)
    return {"status": "ok"}


def text_scope(channel: Channel) -> MessageScope:
    if channel.type != ChannelType.TEXT.value:
        raise AppError("channel_type_invalid", 422)
    return MessageScope(ScopeKind.CHANNEL, channel.id, channel.server_id)


@router.get("/channels/{channel_id}/messages")
async def history(
    channel_id: int,
    request: Request,
    before: str | None = None,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    context.require_in(channel, Perm.READ_MESSAGE_HISTORY)
    service = request.app.state.messages
    rows = await service.history(db, scope, before=parse_id(before), after=parse_id(after), limit=limit)
    state = await db.get(ReadState, (auth.user.id, "channel", channel_id))
    return {"messages": await service.payloads(db, rows, auth.user.id, scope), "has_more": len(rows) == limit, "last_read_message_id": sid(state.last_read_message_id) if state else None}


async def mention_targets(db: AsyncSession, context: ServerContext, channel: Channel, content: str, author_id: int) -> set[int]:
    wanted = extract_mentions(content) - {author_id}
    limit = int(context.server.moderation_settings.get("max_mentions_per_message", 10))
    if len(wanted) > limit:
        raise AppError("too_many_mentions", 422, params={"max": limit})
    targets: set[int] = set()
    for user_id in wanted:
        other = await load_context(db, context.server.id, user_id)
        if other is not None and other.visible_channel(channel):
            targets.add(user_id)
    return targets


async def enforce_slowmode(db: AsyncSession, channel: Channel, user_id: int) -> None:
    last = (
        await db.execute(select(func.max(Message.created_at)).where(Message.channel_id == channel.id, Message.author_id == user_id))
    ).scalar_one()
    if last is None:
        return
    remaining = channel.slowmode_seconds - (utcnow() - last).total_seconds()
    if remaining > 0:
        seconds = math.ceil(remaining)
        raise AppError("slowmode_active", 429, params={"seconds": seconds}, headers={"Retry-After": str(seconds)})


@router.post("/channels/{channel_id}/messages")
async def send(
    channel_id: int, body: SendBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict:
    enforce(request, "message-send", 20, 10, subject=str(auth.user.id))
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    if context.member.timeout_until is not None and context.member.timeout_until > utcnow():
        raise AppError("timed_out", 403)
    context.require_in(channel, Perm.SEND_MESSAGES)
    if channel.slowmode_seconds and not context.can_in(channel, Perm.MANAGE_MESSAGES):
        await enforce_slowmode(db, channel, auth.user.id)
    service = request.app.state.messages
    targets = await mention_targets(db, context, channel, body.content, auth.user.id)
    message, _ = await service.send(db, scope, auth.user.id, body.content, reply_to_id=parse_id(body.reply_to_id), mentions=targets)
    await service.mark_read(db, auth.user.id, scope, message.id)
    payload = (await service.payloads(db, [message], auth.user.id, scope))[0]
    cards = await people.load_cards(db, {auth.user.id})
    for user_id in targets:
        await notify(
            db,
            outbox,
            user_id,
            NotificationType.MENTION,
            {"server_id": sid(channel.server_id), "server_name": context.server.name, "channel_id": sid(channel.id), "channel_name": channel.name, "message_id": sid(message.id), "user": cards[auth.user.id]},
        )
    await db.commit()
    outbox.topic(f"channel:{channel.id}", "message.create", payload)
    outbox.topic(f"server:{channel.server_id}", "channel.activity", {"server_id": sid(channel.server_id), "channel_id": sid(channel.id), "message_id": sid(message.id), "author_id": sid(auth.user.id)})
    await outbox.flush()
    return payload


@router.delete("/channels/{channel_id}/messages/{message_id}")
async def delete_message(
    channel_id: int, message_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    message = await message_in_scope(db, scope, message_id)
    own = message.author_id == auth.user.id
    if not own:
        context.require_in(channel, Perm.MANAGE_MESSAGES)
    if message.deleted_at is None:
        await request.app.state.messages.delete(db, message)
        if not own:
            audit.record(db, AuditAction.MESSAGE_DELETE, actor_id=auth.user.id, server_id=channel.server_id, target_type="message", target_id=message.id, details={"author_id": message.author_id, "channel": channel.name})
            if message.author_id:
                await notify(db, outbox, message.author_id, NotificationType.MODERATION, {"kind": "message_removed", "server_id": sid(channel.server_id), "server_name": context.server.name, "channel_name": channel.name})
    await db.commit()
    outbox.topic(f"channel:{channel.id}", "message.delete", {"id": sid(message_id), "channel_id": sid(channel_id), "scope": "channel"})
    await outbox.flush()
    return {"status": "deleted"}


async def toggle_reaction(request: Request, db: AsyncSession, outbox: Outbox, auth: Auth, channel_id: int, message_id: int, emoji: str, present: bool) -> dict[str, str]:
    enforce(request, "reaction", 60, 60, subject=str(auth.user.id))
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    context.require_in(channel, Perm.READ_MESSAGE_HISTORY)
    if present:
        context.require_in(channel, Perm.ADD_REACTIONS)
    message = await message_in_scope(db, scope, message_id)
    if message.deleted_at is not None:
        raise AppError("not_found", 404)
    await request.app.state.messages.set_reaction(db, message_id, auth.user.id, emoji, present)
    await db.commit()
    outbox.topic(f"channel:{channel.id}", "reaction.update", {"message_id": sid(message_id), "channel_id": sid(channel_id), "emoji": emoji, "user_id": sid(auth.user.id), "present": present})
    await outbox.flush()
    return {"status": "ok"}


@router.put("/channels/{channel_id}/messages/{message_id}/reactions")
async def add_reaction(channel_id: int, message_id: int, body: ReactionBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    return await toggle_reaction(request, db, outbox, auth, channel_id, message_id, body.emoji, True)


@router.delete("/channels/{channel_id}/messages/{message_id}/reactions")
async def remove_reaction(channel_id: int, message_id: int, emoji: str, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    return await toggle_reaction(request, db, outbox, auth, channel_id, message_id, emoji, False)


@router.post("/channels/{channel_id}/read")
async def mark_read(channel_id: int, body: ReadBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    message_id = parse_id(body.message_id)
    await message_in_scope(db, scope, message_id)
    await request.app.state.messages.mark_read(db, auth.user.id, scope, message_id)
    await db.commit()
    outbox.user(auth.user.id, "read.update", {"scope": "channel", "id": sid(channel_id), "message_id": sid(message_id)})
    await outbox.flush()
    return {"status": "ok"}


@router.get("/channels/{channel_id}/pins")
async def list_pins(channel_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    context.require_in(channel, Perm.READ_MESSAGE_HISTORY)
    rows = (await db.execute(select(Message).where(Message.channel_id == channel_id, Message.pinned_at.is_not(None), Message.deleted_at.is_(None)).order_by(Message.pinned_at.desc()))).scalars().all()
    return await request.app.state.messages.payloads(db, list(rows), auth.user.id, scope)


@router.put("/channels/{channel_id}/pins/{message_id}")
async def pin_message(channel_id: int, message_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    context.require_in(channel, Perm.MANAGE_MESSAGES)
    message = await message_in_scope(db, scope, message_id)
    if message.deleted_at is not None:
        raise AppError("not_found", 404)
    count = (await db.execute(select(func.count()).select_from(Message).where(Message.channel_id == channel_id, Message.pinned_at.is_not(None)))).scalar_one()
    if message.pinned_at is None:
        if count >= MAX_PINS:
            raise AppError("pin_limit_reached", 409)
        message.pinned_at = utcnow()
        message.pinned_by = auth.user.id
        audit.record(db, AuditAction.MESSAGE_PIN, actor_id=auth.user.id, server_id=channel.server_id, target_type="message", target_id=message.id, details={"channel": channel.name})
    await db.commit()
    outbox.topic(f"channel:{channel_id}", "message.pin", {"id": sid(message_id), "channel_id": sid(channel_id), "pinned": True})
    await outbox.flush()
    return {"status": "pinned"}


@router.delete("/channels/{channel_id}/pins/{message_id}")
async def unpin_message(channel_id: int, message_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    context.require_in(channel, Perm.MANAGE_MESSAGES)
    message = await message_in_scope(db, scope, message_id)
    if message.pinned_at is not None:
        message.pinned_at = None
        message.pinned_by = None
        audit.record(db, AuditAction.MESSAGE_UNPIN, actor_id=auth.user.id, server_id=channel.server_id, target_type="message", target_id=message.id, details={"channel": channel.name})
    await db.commit()
    outbox.topic(f"channel:{channel_id}", "message.pin", {"id": sid(message_id), "channel_id": sid(channel_id), "pinned": False})
    await outbox.flush()
    return {"status": "unpinned"}


@router.post("/channels/{channel_id}/messages/{message_id}/report")
async def report_message(channel_id: int, message_id: int, body: ReportBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "report", 15, 3600, subject=str(auth.user.id))
    channel, context = await load_channel_context(db, channel_id, auth.user.id)
    scope = text_scope(channel)
    context.require_in(channel, Perm.READ_MESSAGE_HISTORY)
    message = await message_in_scope(db, scope, message_id)
    enabled = bool(context.server.moderation_settings.get("reports_enabled", True))
    report = await create_report(
        db, request.app.state.messages, reporter_id=auth.user.id, message=message, scope=scope, body=body, server_id=channel.server_id, reports_enabled=enabled
    )
    await db.commit()
    return {"report": report_summary(report)}
