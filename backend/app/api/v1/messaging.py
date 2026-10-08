from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import AppError
from ...models import Message, Report
from ...models.enums import ReportStatus, ScopeKind
from ...services.messages import MessageScope, MessageService
from ...services.serializers import iso, sid

REPORT_REASONS = ("spam", "harassment", "hate", "sexual_content", "self_harm", "violence", "impersonation", "other")
SEVERE_REASONS = frozenset({"harassment", "hate", "sexual_content", "self_harm", "violence"})
MAX_PINS = 50


class SendBody(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    reply_to_id: str | None = Field(default=None, max_length=24)


class ReportBody(BaseModel):
    reason: str = Field(max_length=32)
    details: str = Field(default="", max_length=500)
    escalate: bool = False


class ReactionBody(BaseModel):
    emoji: str = Field(min_length=1, max_length=16)


class ReadBody(BaseModel):
    message_id: str = Field(max_length=24)


def parse_id(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isdigit() or len(value) > 20:
        raise AppError("validation_error", 422)
    return int(value)


async def message_in_scope(db: AsyncSession, scope: MessageScope, message_id: int) -> Message:
    message = await db.get(Message, message_id)
    if message is None:
        raise AppError("not_found", 404)
    if scope.kind is ScopeKind.DM and message.conversation_id != scope.scope_id:
        raise AppError("not_found", 404)
    if scope.kind is ScopeKind.CHANNEL and message.channel_id != scope.scope_id:
        raise AppError("not_found", 404)
    return message


def scope_of_message(message: Message, server_id: int | None = None) -> MessageScope:
    if message.conversation_id is not None:
        return MessageScope(ScopeKind.DM, message.conversation_id)
    return MessageScope(ScopeKind.CHANNEL, message.channel_id, server_id)


async def create_report(
    db: AsyncSession,
    service: MessageService,
    *,
    reporter_id: int,
    message: Message,
    scope: MessageScope,
    body: ReportBody,
    server_id: int | None,
    reports_enabled: bool,
) -> Report:
    if body.reason not in REPORT_REASONS:
        raise AppError("report_reason_invalid", 422)
    if message.author_id == reporter_id:
        raise AppError("cannot_report_self", 422)
    if message.deleted_at is not None:
        raise AppError("not_found", 404)
    duplicate = (
        await db.execute(select(Report.id).where(Report.reporter_id == reporter_id, Report.message_id == message.id, Report.status == ReportStatus.OPEN.value))
    ).first()
    if duplicate:
        raise AppError("report_exists", 409)
    escalated = scope.kind is ScopeKind.DM or body.escalate or body.reason in SEVERE_REASONS or not reports_enabled
    report = Report(
        reporter_id=reporter_id,
        target_user_id=message.author_id,
        message_id=message.id,
        server_id=server_id,
        channel_id=message.channel_id,
        conversation_id=message.conversation_id,
        reason=body.reason,
        details=body.details.strip(),
        escalated=escalated,
    )
    db.add(report)
    await db.flush()
    snapshot = await service.snapshot_context(db, message, scope)
    report.snapshot_enc, report.key_id = service.seal_snapshot(report.id, snapshot)
    return report


def report_summary(report: Report) -> dict[str, Any]:
    return {
        "id": sid(report.id),
        "reason": report.reason,
        "details": report.details,
        "status": report.status,
        "escalated": report.escalated,
        "server_id": sid(report.server_id),
        "channel_id": sid(report.channel_id),
        "conversation_id": sid(report.conversation_id),
        "message_id": sid(report.message_id),
        "target_user_id": sid(report.target_user_id),
        "reporter_id": sid(report.reporter_id),
        "created_at": iso(report.created_at),
        "handled_at": iso(report.handled_at),
        "resolution": report.resolution,
        "note": report.note,
    }
