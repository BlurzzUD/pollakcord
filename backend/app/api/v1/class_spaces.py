from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import AppError
from ...models import Report
from ...models.enums import ReportStatus
from ...realtime.outbox import Outbox
from ...security.ratelimit import enforce
from ...services.class_spaces import ClassSpaceService
from ...services.serializers import sid
from ..deps import Auth, get_db, get_outbox, require_auth
from .messaging import REPORT_REASONS, ReadBody, ReportBody, parse_id, report_summary

router = APIRouter(prefix="/class-spaces", tags=["class-spaces"])
ANSWER_LIMIT = (30, 600)
USER_SEND_LIMIT = (20, 60)
CLASS_SEND_LIMIT = (150, 60)
REPORT_LIMIT = (15, 3600)
EVENT = "class_space.message"


class VisibilityBody(BaseModel):
    show_username: bool


class ClassSendBody(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


def required_id(value: str) -> int:
    parsed = parse_id(value)
    if parsed is None:
        raise AppError("validation_error", 422)
    return parsed


@router.get("/me")
async def my_state(request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    service: ClassSpaceService = request.app.state.class_spaces
    return await service.state(db, auth.user)


@router.put("/me/visibility")
async def answer_visibility(
    body: VisibilityBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service: ClassSpaceService = request.app.state.class_spaces
    enforce(request, "class-space-visibility", *ANSWER_LIMIT, subject=str(auth.user.id))
    await service.answer(db, auth.user, body.show_username)
    await db.commit()
    return await service.state(db, auth.user)


@router.get("/{class_id}/members")
async def members(class_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    service: ClassSpaceService = request.app.state.class_spaces
    school_class, _ = await service.require_member(db, auth.user, class_id)
    return await service.members(db, school_class, auth.user)


@router.get("/{class_id}/messages")
async def history(
    class_id: int,
    request: Request,
    before: str | None = None,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service: ClassSpaceService = request.app.state.class_spaces
    school_class, _ = await service.require_member(db, auth.user, class_id)
    rows = await service.history(db, school_class.id, before=parse_id(before), after=parse_id(after), limit=limit)
    payloads = await service.payloads(db, school_class, rows, auth.user)
    state = await service.read_state(db, auth.user, school_class.id)
    return {"messages": payloads, "has_more": len(rows) == limit, "last_read_message_id": sid(state.last_read_message_id) if state else None}


@router.post("/{class_id}/messages")
async def send(
    class_id: int,
    body: ClassSendBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict:
    user = auth.user
    service: ClassSpaceService = request.app.state.class_spaces
    school_class, member = await service.require_member(db, user, class_id)
    enforce(request, "class-space-send", *USER_SEND_LIMIT, subject=str(user.id))
    enforce(request, "class-space-send-class", *CLASS_SEND_LIMIT, subject=str(school_class.id))
    message = await service.send(db, school_class, member, user, body.content)
    recipients = await service.member_ids(db, school_class.id)
    payload = (await service.payloads(db, school_class, [message], user))[0]
    outbox.users({*recipients, user.id}, EVENT, {"class_id": sid(school_class.id), "message_id": sid(message.id)})
    await db.commit()
    await outbox.flush()
    return payload


@router.post("/{class_id}/read")
async def mark_read(
    class_id: int,
    body: ReadBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    service: ClassSpaceService = request.app.state.class_spaces
    school_class, _ = await service.require_member(db, auth.user, class_id)
    message = await service.require_message(db, school_class.id, required_id(body.message_id))
    await service.mark_read(db, auth.user, school_class.id, message.id)
    await db.commit()
    return {"status": "ok"}


@router.delete("/{class_id}/messages/{message_id}")
async def delete_message(
    class_id: int,
    message_id: int,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict[str, str]:
    service: ClassSpaceService = request.app.state.class_spaces
    school_class, _ = await service.require_member(db, auth.user, class_id)
    message = await service.require_message(db, school_class.id, message_id)
    if message.author_id != auth.user.id:
        raise AppError("forbidden", 403)
    recipients = await service.member_ids(db, school_class.id)
    await db.delete(message)
    outbox.users(set(recipients), EVENT, {"class_id": sid(school_class.id), "message_id": sid(message_id)})
    await db.commit()
    await outbox.flush()
    return {"status": "deleted"}


@router.post("/{class_id}/messages/{message_id}/report")
async def report_message(
    class_id: int,
    message_id: int,
    body: ReportBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service: ClassSpaceService = request.app.state.class_spaces
    school_class, _ = await service.require_member(db, auth.user, class_id)
    message = await service.require_message(db, school_class.id, message_id)
    enforce(request, "report", *REPORT_LIMIT, subject=str(auth.user.id))
    if body.reason not in REPORT_REASONS:
        raise AppError("report_reason_invalid", 422)
    if message.author_id == auth.user.id:
        raise AppError("cannot_report_self", 422)
    duplicate = (
        await db.execute(
            select(Report.id).where(Report.reporter_id == auth.user.id, Report.message_id == message.id, Report.status == ReportStatus.OPEN.value)
        )
    ).first()
    if duplicate:
        raise AppError("report_exists", 409)
    report = Report(
        reporter_id=auth.user.id,
        target_user_id=message.author_id,
        message_id=message.id,
        reason=body.reason,
        details=body.details.strip(),
        escalated=True,
    )
    db.add(report)
    await db.flush()
    report.snapshot_enc, report.key_id = request.app.state.messages.seal_snapshot(report.id, await service.snapshot(db, message))
    await db.commit()
    return {"report": report_summary(report)}
