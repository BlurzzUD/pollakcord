from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import AppError
from ...models import DokMessage
from ...models.enums import AuditAction, DokScope
from ...realtime.outbox import Outbox
from ...security.ratelimit import enforce
from ...services import audit
from ...services.dok import MAX_ID, DokService, Target, authorize_target, can_send
from ...services.serializers import sid
from ..deps import Auth, get_db, get_outbox, require_auth
from .messaging import parse_id

router = APIRouter(prefix="/dok", tags=["dok"])
USER_SEND_LIMIT = (10, 60)
TARGET_SEND_LIMIT = (30, 60)


class ClassTargetBody(BaseModel):
    type: Literal["class"]
    class_id: str = Field(max_length=24)


class SchoolTargetBody(BaseModel):
    type: Literal["school"]


class DokSendBody(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    target: Annotated[ClassTargetBody | SchoolTargetBody, Field(discriminator="type")]


class DokReadBody(BaseModel):
    message_id: str = Field(max_length=24)


def parse_target(body: ClassTargetBody | SchoolTargetBody) -> Target:
    if isinstance(body, SchoolTargetBody):
        return Target(DokScope.SCHOOL)
    return Target(DokScope.CLASS, parse_id(body.class_id))


@router.get("/inbox")
async def inbox(request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    service: DokService = request.app.state.dok
    return await service.inbox(db, auth.user)


@router.post("/messages")
async def send(
    body: DokSendBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict:
    user = auth.user
    service: DokService = request.app.state.dok
    if not can_send(user):
        raise AppError("dok_send_forbidden", 403)
    target = parse_target(body.target)
    authorize_target(user, target)
    school_class = await service.resolve_class(db, target.school_class_id) if target.scope is DokScope.CLASS else None
    enforce(request, "dok-send", *USER_SEND_LIMIT, subject=str(user.id))
    enforce(request, "dok-send-target", *TARGET_SEND_LIMIT, subject=target.key)
    thread, message = await service.send(db, target, user, body.content)
    recipients = await service.recipient_ids(db, thread)
    await service.announce(db, outbox, thread, message, user, recipients, school_class.code if school_class else None)
    audit.record(
        db,
        AuditAction.DOK_MESSAGE_SEND,
        actor_id=user.id,
        target_type="dok_message",
        target_id=message.id,
        details={
            "thread_id": sid(thread.id),
            "scope": thread.scope,
            "class_id": sid(thread.school_class_id),
            "author_role": message.author_role,
            "recipients": sum(1 for user_id in recipients if user_id != user.id),
        },
    )
    payload = (await service.payloads(db, thread, [message], user))[0]
    await db.commit()
    await outbox.flush()
    return payload


@router.get("/threads/{thread_id}/messages")
async def history(
    thread_id: int,
    request: Request,
    before: str | None = None,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service: DokService = request.app.state.dok
    thread = await service.require_thread(db, thread_id, auth.user)
    rows = await service.history(db, thread.id, before=parse_id(before), after=parse_id(after), limit=limit)
    payloads = await service.payloads(db, thread, rows, auth.user)
    state = await service.read_state(db, auth.user, thread)
    return {"messages": payloads, "has_more": len(rows) == limit, "last_read_message_id": sid(state.last_read_message_id) if state else None}


@router.post("/threads/{thread_id}/read")
async def mark_read(
    thread_id: int,
    body: DokReadBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    service: DokService = request.app.state.dok
    thread = await service.require_thread(db, thread_id, auth.user)
    message_id = parse_id(body.message_id)
    message = await db.get(DokMessage, message_id) if message_id <= MAX_ID else None
    if message is None or message.thread_id != thread.id:
        raise AppError("not_found", 404)
    await service.mark_read(db, auth.user, thread, message.id)
    await db.commit()
    return {"status": "ok"}
