import asyncio

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.types import utcnow
from ...errors import AppError
from ...models import Conversation, Message, ReadState, User
from ...models.enums import AccountStatus, NotificationType, ScopeKind
from ...realtime.outbox import Outbox
from ...security.ratelimit import enforce
from ...services import people, privacy
from ...services.messages import MessageScope, extract_mentions
from ...services.notifications import notify
from ...services.privacy import ordered
from ...services.serializers import iso, sid
from ..deps import Auth, get_db, get_outbox, require_auth
from .messaging import ReactionBody, ReadBody, ReportBody, SendBody, create_report, message_in_scope, parse_id, report_summary

router = APIRouter(prefix="/dms", tags=["direct messages"])
PREVIEW = 90


class OpenBody(BaseModel):
    user_id: str = Field(max_length=24)


def other_party(conversation: Conversation, user_id: int) -> int:
    return conversation.user_high_id if conversation.user_low_id == user_id else conversation.user_low_id


async def require_conversation(db: AsyncSession, conversation_id: int, user_id: int) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or user_id not in (conversation.user_low_id, conversation.user_high_id):
        raise AppError("not_found", 404)
    return conversation


async def conversation_summary(request: Request, db: AsyncSession, conversation: Conversation, viewer_id: int, cards: dict, presence: dict) -> dict:
    service = request.app.state.messages
    other = other_party(conversation, viewer_id)
    scope = MessageScope(ScopeKind.DM, conversation.id)
    latest = (await db.execute(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id.desc()).limit(1))).scalar_one_or_none()
    preview = None
    if latest is not None and latest.deleted_at is None:
        texts = await service.texts_for(db, [latest])
        preview = {"content": texts.get(latest.id, "")[:PREVIEW], "author_id": sid(latest.author_id), "created_at": iso(latest.created_at)}
    return {
        "id": sid(conversation.id),
        "user": cards.get(other),
        "presence": presence.get(other),
        "last_message": preview,
        "last_message_at": iso(conversation.last_message_at),
        "unread": await service.unread_count(db, viewer_id, scope),
    }


@router.get("")
async def list_conversations(request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(
            select(Conversation)
            .where(or_(Conversation.user_low_id == auth.user.id, Conversation.user_high_id == auth.user.id), Conversation.last_message_at.is_not(None))
            .order_by(Conversation.last_message_at.desc())
            .limit(50)
        )
    ).scalars().all()
    others = {other_party(c, auth.user.id) for c in rows}
    cards = await people.load_cards(db, others)
    presence = await people.presence_map(db, request.app.state.hub, auth.user.id, others)
    return [await conversation_summary(request, db, c, auth.user.id, cards, presence) for c in rows]


@router.post("")
async def open_conversation(body: OpenBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    target_id = parse_id(body.user_id)
    if target_id == auth.user.id:
        raise AppError("cannot_message_self", 422)
    target = await db.get(User, target_id)
    if target is None or target.status != AccountStatus.ACTIVE.value:
        raise AppError("not_found", 404)
    low, high = ordered(auth.user.id, target.id)
    conversation = (await db.execute(select(Conversation).where(Conversation.user_low_id == low, Conversation.user_high_id == high))).scalar_one_or_none()
    if conversation is None:
        relation = await privacy.relation(db, auth.user.id, target.id)
        recipient_settings = await privacy.get_settings_row(db, target.id)
        if not privacy.can_direct_message(relation, recipient_settings):
            raise AppError("dm_not_allowed", 403)
        conversation = Conversation(user_low_id=low, user_high_id=high)
        db.add(conversation)
        await db.commit()
    cards = await people.load_cards(db, {target.id})
    presence = await people.presence_map(db, request.app.state.hub, auth.user.id, {target.id})
    return await conversation_summary(request, db, conversation, auth.user.id, cards, presence)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    conversation = await require_conversation(db, conversation_id, auth.user.id)
    other = other_party(conversation, auth.user.id)
    cards = await people.load_cards(db, {other})
    presence = await people.presence_map(db, request.app.state.hub, auth.user.id, {other})
    return await conversation_summary(request, db, conversation, auth.user.id, cards, presence)


@router.get("/{conversation_id}/messages")
async def history(
    conversation_id: int,
    request: Request,
    before: str | None = None,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_conversation(db, conversation_id, auth.user.id)
    service = request.app.state.messages
    scope = MessageScope(ScopeKind.DM, conversation_id)
    rows = await service.history(db, scope, before=parse_id(before), after=parse_id(after), limit=limit)
    payloads = await service.payloads(db, rows, auth.user.id, scope)
    state = await db.get(ReadState, (auth.user.id, scope.kind.value, scope.scope_id))
    return {"messages": payloads, "has_more": len(rows) == limit, "last_read_message_id": sid(state.last_read_message_id) if state else None}


@router.post("/{conversation_id}/messages")
async def send(
    conversation_id: int,
    body: SendBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict:
    enforce(request, "message-send", 20, 10, subject=str(auth.user.id))
    conversation = await require_conversation(db, conversation_id, auth.user.id)
    other_id = other_party(conversation, auth.user.id)
    relation = await privacy.relation(db, auth.user.id, other_id)
    recipient_settings = await privacy.get_settings_row(db, other_id)
    if not privacy.can_direct_message(relation, recipient_settings):
        raise AppError("dm_not_allowed", 403)
    service = request.app.state.messages
    scope = MessageScope(ScopeKind.DM, conversation_id)
    mentions = {other_id} & extract_mentions(body.content)
    message, _ = await service.send(db, scope, auth.user.id, body.content, reply_to_id=parse_id(body.reply_to_id), mentions=mentions)
    conversation.last_message_at = utcnow()
    await service.mark_read(db, auth.user.id, scope, message.id)
    payload = (await service.payloads(db, [message], auth.user.id, scope))[0]
    cards = await people.load_cards(db, {auth.user.id})
    await notify(
        db,
        outbox,
        other_id,
        NotificationType.DM,
        {"conversation_id": sid(conversation_id), "user": cards[auth.user.id]},
        dedupe_key=f"dm:{conversation_id}",
    )
    await db.commit()
    outbox.user(auth.user.id, "message.create", payload)
    outbox.user(other_id, "message.create", payload)
    await outbox.flush()
    return payload


@router.delete("/{conversation_id}/messages/{message_id}")
async def delete_message(
    conversation_id: int, message_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    conversation = await require_conversation(db, conversation_id, auth.user.id)
    scope = MessageScope(ScopeKind.DM, conversation_id)
    message = await message_in_scope(db, scope, message_id)
    if message.author_id != auth.user.id:
        raise AppError("forbidden", 403)
    if message.deleted_at is None:
        await request.app.state.messages.delete(db, message)
    await db.commit()
    event = {"id": sid(message_id), "conversation_id": sid(conversation_id), "scope": "dm"}
    outbox.users({conversation.user_low_id, conversation.user_high_id}, "message.delete", event)
    await outbox.flush()
    return {"status": "deleted"}


@router.put("/{conversation_id}/messages/{message_id}/reactions")
async def add_reaction(
    conversation_id: int, message_id: int, body: ReactionBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    return await toggle_reaction(request, db, outbox, auth, conversation_id, message_id, body.emoji, True)


@router.delete("/{conversation_id}/messages/{message_id}/reactions")
async def remove_reaction(
    conversation_id: int, message_id: int, emoji: str, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)
) -> dict[str, str]:
    return await toggle_reaction(request, db, outbox, auth, conversation_id, message_id, emoji, False)


async def toggle_reaction(request: Request, db: AsyncSession, outbox: Outbox, auth: Auth, conversation_id: int, message_id: int, emoji: str, present: bool) -> dict[str, str]:
    enforce(request, "reaction", 60, 60, subject=str(auth.user.id))
    conversation = await require_conversation(db, conversation_id, auth.user.id)
    message = await message_in_scope(db, MessageScope(ScopeKind.DM, conversation_id), message_id)
    if message.deleted_at is not None:
        raise AppError("not_found", 404)
    await request.app.state.messages.set_reaction(db, message_id, auth.user.id, emoji, present)
    await db.commit()
    outbox.users(
        {conversation.user_low_id, conversation.user_high_id},
        "reaction.update",
        {"message_id": sid(message_id), "conversation_id": sid(conversation_id), "emoji": emoji, "user_id": sid(auth.user.id), "present": present},
    )
    await outbox.flush()
    return {"status": "ok"}


@router.post("/{conversation_id}/read")
async def mark_read(conversation_id: int, body: ReadBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    await require_conversation(db, conversation_id, auth.user.id)
    scope = MessageScope(ScopeKind.DM, conversation_id)
    message_id = parse_id(body.message_id)
    await message_in_scope(db, scope, message_id)
    await request.app.state.messages.mark_read(db, auth.user.id, scope, message_id)
    await db.commit()
    outbox.user(auth.user.id, "read.update", {"scope": "dm", "id": sid(conversation_id), "message_id": sid(message_id)})
    conversation = await db.get(Conversation, conversation_id)
    outbox.user(other_party(conversation, auth.user.id), "read.peer", {"conversation_id": sid(conversation_id), "message_id": sid(message_id), "user_id": sid(auth.user.id)})
    await outbox.flush()
    return {"status": "ok"}


@router.post("/{conversation_id}/messages/{message_id}/report")
async def report_message(
    conversation_id: int, message_id: int, body: ReportBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict:
    enforce(request, "report", 15, 3600, subject=str(auth.user.id))
    await require_conversation(db, conversation_id, auth.user.id)
    scope = MessageScope(ScopeKind.DM, conversation_id)
    message = await message_in_scope(db, scope, message_id)
    report = await create_report(
        db, request.app.state.messages, reporter_id=auth.user.id, message=message, scope=scope, body=body, server_id=None, reports_enabled=True
    )
    await db.commit()
    return {"report": report_summary(report)}
