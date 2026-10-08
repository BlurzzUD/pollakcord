from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Profile
from ...security.ratelimit import enforce
from ...services import uploads
from ...services.accounts import load_self_payload
from ..deps import Auth, get_db, get_settings, require_auth

router = APIRouter(prefix="/uploads", tags=["uploads"])
PROFILE_FIELDS = {"avatar": "avatar_key", "banner": "banner_key"}


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
