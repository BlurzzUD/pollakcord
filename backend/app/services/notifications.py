from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.types import utcnow
from ..models import Notification, UserSettings
from ..models.enums import NotificationType
from ..realtime.outbox import Outbox
from .serializers import iso, sid

PREFERENCE_KEY = {
    NotificationType.FRIEND_REQUEST: "friend_requests",
    NotificationType.FRIEND_ACCEPTED: "friend_requests",
    NotificationType.DM: "direct_messages",
    NotificationType.MENTION: "mentions",
    NotificationType.SERVER: "server",
    NotificationType.CALL_INCOMING: "calls",
    NotificationType.CALL_MISSED: "calls",
    NotificationType.MODERATION: "moderation",
}


def notification_dict(row: Notification) -> dict[str, Any]:
    return {"id": sid(row.id), "type": row.type, "payload": row.payload, "read": row.read_at is not None, "created_at": iso(row.created_at)}


async def notify(
    db: AsyncSession,
    outbox: Outbox,
    user_id: int,
    kind: NotificationType,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
) -> None:
    prefs_row = await db.get(UserSettings, user_id)
    prefs = prefs_row.notification_prefs if prefs_row else {}
    if prefs.get(PREFERENCE_KEY[kind], True) is False:
        return
    existing = None
    if dedupe_key:
        existing = (
            await db.execute(
                select(Notification).where(Notification.user_id == user_id, Notification.dedupe_key == dedupe_key, Notification.read_at.is_(None))
            )
        ).scalar_one_or_none()
    if existing is not None:
        existing.payload = payload
        existing.created_at = utcnow()
        row = existing
    else:
        row = Notification(user_id=user_id, type=kind.value, payload=payload, dedupe_key=dedupe_key)
        db.add(row)
        await db.flush()
    outbox.user(user_id, "notification.create", notification_dict(row))


async def mark_read(db: AsyncSession, user_id: int, ids: list[int] | None) -> None:
    statement = update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    if ids is not None:
        statement = statement.where(Notification.id.in_(ids))
    await db.execute(statement.values(read_at=utcnow()))
