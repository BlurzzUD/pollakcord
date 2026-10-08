from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import AppError
from ...models import Notification
from ...services import notifications as service
from ..deps import Auth, get_db, require_auth

router = APIRouter(prefix="/notifications", tags=["notifications"])


class ReadBody(BaseModel):
    ids: list[str] | None = None


@router.get("")
async def list_notifications(limit: int = Query(default=40, ge=1, le=100), auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Notification).where(Notification.user_id == auth.user.id).order_by(Notification.created_at.desc()).limit(limit))).scalars().all()
    unread = (await db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == auth.user.id, Notification.read_at.is_(None)))).scalar_one()
    return {"items": [service.notification_dict(r) for r in rows], "unread": unread}


@router.post("/read")
async def mark_read(body: ReadBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    ids = None
    if body.ids is not None:
        if any(not i.isdigit() for i in body.ids) or len(body.ids) > 200:
            raise AppError("validation_error", 422)
        ids = [int(i) for i in body.ids]
    await service.mark_read(db, auth.user.id, ids)
    await db.commit()
    return {"status": "ok"}


@router.delete("/{notification_id}")
async def delete_notification(notification_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    row = await db.get(Notification, notification_id)
    if row is None or row.user_id != auth.user.id:
        raise AppError("not_found", 404)
    await db.delete(row)
    await db.commit()
    return {"status": "deleted"}
