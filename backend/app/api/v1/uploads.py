from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.types import utcnow
from ...errors import AppError
from ...models import Attachment, Message, Profile
from ...security.ratelimit import enforce
from ...services import uploads
from ...services.attachments import ELEVATED_ROLES, MAX_ATTACHMENTS, PENDING_LIFETIME, attachment_limit, attachment_payload, blob_path, check_size, parse_upload, store_attachment
from ...services.media_access import require_media_scope
from ...services.accounts import load_self_payload
from ..deps import Auth, get_db, get_settings, require_auth

router = APIRouter(prefix="/uploads", tags=["uploads"])
PROFILE_FIELDS = {"avatar": "avatar_key", "banner": "banner_key"}


@router.get("/config")
async def media_config(request: Request, auth: Auth = Depends(require_auth)) -> dict:
    settings = get_settings(request)
    key = settings.giphy_api_key.get_secret_value().strip() if settings.giphy_api_key else ""
    return {
        "public_origin": settings.public_origin,
        "max_attachment_bytes": attachment_limit(settings, auth.user.platform_role),
        "max_attachments": MAX_ATTACHMENTS,
        "giphy_api_key": key or None,
        "giphy_rating": "pg",
    }


@router.post("/attachments")
async def upload_attachment(
    request: Request, scope: Literal["channel", "dm"], scope_id: int = Query(gt=0, lt=2**63),
    auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db),
) -> dict:
    await require_media_scope(db, auth.user, scope, scope_id, write=True)
    settings = get_settings(request)
    limit = attachment_limit(settings, auth.user.platform_role)
    enforce(request, "attachment-upload", 30 if auth.user.platform_role in ELEVATED_ROLES else 60, 3600, subject=str(auth.user.id))
    if declared := request.headers.get("content-length"):
        try:
            check_size(int(declared), limit + 65536)
        except ValueError as exc:
            raise AppError("attachment_invalid", 422) from exc
    form, file = await parse_upload(request, auth.user, limit)
    row = None
    try:
        row = await store_attachment(db, request.app.state.vault, settings, auth.user, scope, scope_id, file)
        await db.commit()
        return attachment_payload(request.app.state.vault, row)
    except BaseException:
        if row is not None:
            blob_path(settings, row.storage_key).unlink(missing_ok=True)
        raise
    finally:
        await form.close()


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: int, request: Request, inline: bool = False,
    auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db),
) -> FileResponse:
    row = await db.get(Attachment, attachment_id) if 0 < attachment_id < 2**63 else None
    if row is None:
        raise AppError("not_found", 404)
    pending = row.message_id is None
    if pending and (row.owner_id != auth.user.id or row.created_at <= utcnow() - PENDING_LIFETIME):
        raise AppError("not_found", 404)
    if not pending:
        message = await db.get(Message, row.message_id)
        if message is None or message.deleted_at is not None:
            raise AppError("not_found", 404)
    scope = "channel" if row.channel_id is not None else "dm"
    await require_media_scope(db, auth.user, scope, row.channel_id if scope == "channel" else row.conversation_id, write=pending)
    path = blob_path(get_settings(request), row.storage_key)
    if not path.is_file():
        raise AppError("not_found", 404)
    safe_inline = inline and row.kind in ("image", "video")
    payload = attachment_payload(request.app.state.vault, row)
    return FileResponse(
        path, filename=payload["filename"], media_type=row.mime_type if safe_inline else "application/octet-stream",
        content_disposition_type="inline" if safe_inline else "attachment",
        headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/attachments/{attachment_id}")
async def discard_attachment(
    attachment_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(Attachment, attachment_id) if 0 < attachment_id < 2**63 else None
    if row is None or row.owner_id != auth.user.id or row.message_id is not None:
        raise AppError("not_found", 404)
    path = blob_path(get_settings(request), row.storage_key)
    removed = await db.execute(delete(Attachment).where(Attachment.id == row.id, Attachment.owner_id == auth.user.id, Attachment.message_id.is_(None)))
    if removed.rowcount != 1:
        raise AppError("not_found", 404)
    await db.commit()
    path.unlink(missing_ok=True)
    return {"status": "deleted"}


@router.post("/{kind}")
async def upload_profile_image(
    kind: str, request: Request, file: UploadFile = File(...), auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict:
    from ...errors import AppError

    if kind not in PROFILE_FIELDS:
        raise AppError("not_found", 404)
    enforce(request, "upload", 20, 3600, subject=str(auth.user.id))
    settings = get_settings(request)
    data = await uploads.process_image_upload(kind, file, settings)
    profile = await db.get(Profile, auth.user.id)
    previous = getattr(profile, PROFILE_FIELDS[kind])
    setattr(profile, PROFILE_FIELDS[kind], uploads.store_image(settings, kind, data))
    await db.commit()
    uploads.delete_image(settings, kind, previous)
    return await load_self_payload(db, auth.user)


@router.delete("/{kind}")
async def remove_profile_image(kind: str, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    from ...errors import AppError

    if kind not in PROFILE_FIELDS:
        raise AppError("not_found", 404)
    profile = await db.get(Profile, auth.user.id)
    previous = getattr(profile, PROFILE_FIELDS[kind])
    setattr(profile, PROFILE_FIELDS[kind], None)
    await db.commit()
    uploads.delete_image(get_settings(request), kind, previous)
    return await load_self_payload(db, auth.user)
