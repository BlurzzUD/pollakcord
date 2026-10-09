from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.types import utcnow
from ...errors import AppError
from ...models import AuditLog, Message, Report, SchoolClass, User, UserIdentity
from ...models.enums import STAFF_ROLES, AccountStatus, AuditAction, PlatformRole, ReportStatus, ScopeKind
from ...security.ratelimit import enforce
from ...security.sessions import revoke_user_sessions
from ...services import audit, people
from ...services.messages import MessageScope
from ...services.accounts import identity_aad
from ...services.serializers import iso, sid
from ..deps import Auth, get_db, require_moderator
from .messaging import report_summary, scope_of_message

router = APIRouter(prefix="/moderation", tags=["moderation"])
MIN_REASON = 10


class ReasonBody(BaseModel):
    reason: str = Field(min_length=MIN_REASON, max_length=300)
    report_id: str | None = Field(default=None, max_length=24)


class ResolveBody(BaseModel):
    resolution: Literal["dismissed", "resolved"]
    note: str = Field(default="", max_length=500)


class StatusBody(BaseModel):
    status: Literal["active", "suspended"]
    reason: str = Field(min_length=MIN_REASON, max_length=300)


class MessageLookupBody(BaseModel):
    message_id: str = Field(max_length=24)
    reason: str = Field(min_length=MIN_REASON, max_length=300)


def require_admin(auth: Auth) -> None:
    if auth.user.platform_role != PlatformRole.SCHOOL_ADMIN.value:
        raise AppError("forbidden", 403)


@router.get("/reports")
async def list_reports(
    status: Literal["open", "resolved", "dismissed"] = "open",
    limit: int = Query(default=50, ge=1, le=100),
    auth: Auth = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    statement = select(Report).where(Report.status == status).order_by(Report.id.desc()).limit(limit)
    if auth.user.platform_role != PlatformRole.SCHOOL_ADMIN.value:
        statement = statement.where(Report.escalated.is_(True))
    rows = (await db.execute(statement)).scalars().all()
    cards = await people.load_cards(db, {r.target_user_id for r in rows if r.target_user_id} | {r.reporter_id for r in rows if r.reporter_id})
    return [{**report_summary(r), "target": cards.get(r.target_user_id), "reporter": cards.get(r.reporter_id)} for r in rows]


@router.get("/reports/{report_id}")
async def get_report(report_id: int, request: Request, auth: Auth = Depends(require_moderator), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "mod-report-view", 120, 3600, subject=str(auth.user.id))
    report = await db.get(Report, report_id)
    if report is None or (not report.escalated and auth.user.platform_role != PlatformRole.SCHOOL_ADMIN.value):
        raise AppError("not_found", 404)
    cards = await people.load_cards(db, {x for x in (report.target_user_id, report.reporter_id) if x})
    audit.record(db, AuditAction.PLATFORM_REPORT_VIEW, actor_id=auth.user.id, target_type="report", target_id=report.id, details={"server_id": report.server_id})
    await db.commit()
    context = request.app.state.messages.open_snapshot(report.id, report.snapshot_enc, report.key_id) if report.snapshot_enc else []
    authors = await people.load_cards(db, {int(item["author_id"]) for item in context if item.get("author_id")})
    for item in context:
        item["author"] = authors.get(int(item["author_id"])) if item.get("author_id") else None
    return {**report_summary(report), "target": cards.get(report.target_user_id), "reporter": cards.get(report.reporter_id), "context": context}


@router.post("/reports/{report_id}/resolve")
async def resolve_report(report_id: int, body: ResolveBody, auth: Auth = Depends(require_moderator), db: AsyncSession = Depends(get_db)) -> dict:
    report = await db.get(Report, report_id)
    if report is None or (not report.escalated and auth.user.platform_role != PlatformRole.SCHOOL_ADMIN.value):
        raise AppError("not_found", 404)
    report.status = ReportStatus.DISMISSED.value if body.resolution == "dismissed" else ReportStatus.RESOLVED.value
    report.resolution = body.resolution
    report.note = body.note.strip()
    report.handled_by = auth.user.id
    report.handled_at = utcnow()
    audit.record(db, AuditAction.REPORT_RESOLVE, actor_id=auth.user.id, target_type="report", target_id=report.id, details={"resolution": body.resolution})
    await db.commit()
    return report_summary(report)


@router.get("/users/lookup")
async def lookup_user(q: str = Query(min_length=2, max_length=64), auth: Auth = Depends(require_moderator), db: AsyncSession = Depends(get_db)) -> list[dict]:
    needle = q.strip().lower().lstrip("@")
    conditions = [User.username_lower == needle]
    if needle.isdigit():
        conditions.append(User.id == int(needle))
    rows = (await db.execute(select(User).where(or_(*conditions)).limit(5))).scalars().all()
    cards = await people.load_cards(db, {u.id for u in rows})
    return [{**cards[u.id], "status": u.status, "platform_role": u.platform_role} for u in rows]


@router.post("/users/{user_id}/identity")
async def reveal_identity(user_id: int, body: ReasonBody, request: Request, auth: Auth = Depends(require_moderator), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "mod-identity", 30, 3600, subject=str(auth.user.id))
    user = await db.get(User, user_id)
    identity = await db.get(UserIdentity, user_id)
    if user is None or identity is None:
        raise AppError("not_found", 404)
    full_name = request.app.state.vault.decrypt("identity", identity.real_name_enc, identity_aad(user_id), identity.key_id).decode("utf-8")
    audit.record(
        db,
        AuditAction.PLATFORM_IDENTITY_REVEAL,
        actor_id=auth.user.id,
        target_type="user",
        target_id=user_id,
        details={"reason": body.reason.strip(), "report_id": body.report_id},
    )
    await db.commit()
    school_class = await db.get(SchoolClass, user.school_class_id) if user.school_class_id else None
    return {
        "user_id": sid(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "full_name": full_name,
        "declared_class": school_class.code if school_class else None,
        "status": user.status,
    }


@router.post("/users/{user_id}/status")
async def set_user_status(user_id: int, body: StatusBody, request: Request, auth: Auth = Depends(require_moderator), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    require_admin(auth)
    user = await db.get(User, user_id)
    if user is None or user.id == auth.user.id or user.platform_role in STAFF_ROLES:
        raise AppError("not_found", 404)
    if user.status == AccountStatus.PENDING_SECURITY.value:
        raise AppError("conflict", 409)
    user.status = AccountStatus.SUSPENDED.value if body.status == "suspended" else AccountStatus.ACTIVE.value
    if body.status == "suspended":
        await revoke_user_sessions(db, user.id)
    audit.record(db, AuditAction.PLATFORM_USER_STATUS, actor_id=auth.user.id, target_type="user", target_id=user_id, details={"status": body.status, "reason": body.reason.strip()})
    await db.commit()
    if body.status == "suspended":
        await request.app.state.hub.close_user(user.id)
    return {"status": user.status}


@router.post("/messages/lookup")
async def lookup_message(body: MessageLookupBody, request: Request, auth: Auth = Depends(require_moderator), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "mod-message", 60, 3600, subject=str(auth.user.id))
    if not body.message_id.isdigit():
        raise AppError("validation_error", 422)
    message = await db.get(Message, int(body.message_id))
    if message is None:
        raise AppError("not_found", 404)
    scope = scope_of_message(message)
    if scope.kind is ScopeKind.CHANNEL:
        from ...models import Channel

        channel = await db.get(Channel, message.channel_id)
        scope = MessageScope(ScopeKind.CHANNEL, message.channel_id, channel.server_id if channel else None)
    context = await request.app.state.messages.snapshot_context(db, message, scope)
    authors = await people.load_cards(db, {int(item["author_id"]) for item in context if item.get("author_id")})
    for item in context:
        item["author"] = authors.get(int(item["author_id"])) if item.get("author_id") else None
    audit.record(db, AuditAction.PLATFORM_MESSAGE_VIEW, actor_id=auth.user.id, target_type="message", target_id=message.id, details={"reason": body.reason.strip()})
    await db.commit()
    return {"scope": scope.kind.value, "context": context}


@router.get("/audit")
async def platform_audit(before: str | None = None, limit: int = Query(default=50, ge=1, le=100), auth: Auth = Depends(require_moderator), db: AsyncSession = Depends(get_db)) -> dict:
    require_admin(auth)
    statement = select(AuditLog).where(AuditLog.server_id.is_(None)).order_by(AuditLog.id.desc()).limit(limit)
    if before and before.isdigit():
        statement = statement.where(AuditLog.id < int(before))
    rows = (await db.execute(statement)).scalars().all()
    cards = await people.load_cards(db, {r.actor_id for r in rows if r.actor_id} | {r.target_id for r in rows if r.target_type == "user" and r.target_id})
    return {
        "entries": [
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
        ],
        "has_more": len(rows) == limit,
    }
