import asyncio
import json
import mimetypes
import re
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi import Request
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from python_multipart.exceptions import FormParserError

from ..config import Settings
from ..crypto.envelope import DecryptionError, Vault
from ..db.types import utcnow
from ..errors import AppError
from ..ids import new_id
from ..models import Attachment, User
from ..models.enums import PlatformRole
from .uploads import ImageSpec, media_directory, transform_image

ELEVATED_ROLES = frozenset({
    PlatformRole.DOK_REPRESENTATIVE.value, PlatformRole.DOK_PRESIDENT.value,
    PlatformRole.SCHOOL_MODERATOR.value, PlatformRole.SCHOOL_ADMIN.value,
})
MAX_ATTACHMENTS = 10
PENDING_LIFETIME = timedelta(hours=24)
STORAGE_KEY = re.compile(r"^[0-9a-f]{32}$")
IMAGE_SPEC = ImageSpec("attachment_max_bytes", 1, 1, 16384, (2560, 2560), False)


def attachment_limit(settings: Settings, role: str) -> int:
    return settings.attachment_elevated_max_bytes if role in ELEVATED_ROLES else settings.attachment_max_bytes


def check_size(size: int, limit: int) -> None:
    if size > limit:
        raise AppError("file_too_large", 413, params={"max_bytes": limit})


def charge_upload(request: Request, user: User, amount: int) -> None:
    settings = request.app.state.settings
    limit = settings.attachment_elevated_hourly_bytes if user.platform_role in ELEVATED_ROLES else settings.attachment_hourly_bytes
    retry = request.app.state.limiter.check_weight(f"attachment-bytes:{user.id}", amount, limit, 3600)
    if retry is not None:
        seconds = int(retry) + 1
        raise AppError("rate_limited", 429, params={"seconds": seconds}, headers={"Retry-After": str(seconds)})


async def parse_upload(request: Request, user: User, limit: int):
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
        raise AppError("attachment_invalid", 422)
    async def bounded_stream():
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            check_size(received, limit + 65536)
            yield chunk

    class AttachmentParser(MultiPartParser):
        file_bytes = 0

        def on_part_data(self, data: bytes, start: int, end: int) -> None:
            if self._current_part.file is not None:
                self.file_bytes += end - start
                check_size(self.file_bytes, limit)
                charge_upload(request, user, end - start)
            super().on_part_data(data, start, end)

    parser = AttachmentParser(request.headers, bounded_stream(), max_files=1, max_fields=0, max_part_size=65536)
    try:
        form = await parser.parse()
    except BaseException as exc:
        for handle in parser._files_to_close_on_error:
            handle.close()
        if isinstance(exc, (MultiPartException, FormParserError)):
            raise AppError("attachment_invalid", 422) from exc
        raise
    file = form.get("file")
    if len(form.multi_items()) != 1 or not isinstance(file, UploadFile):
        await form.close()
        raise AppError("attachment_invalid", 422)
    return form, file


def blob_path(settings: Settings, key: str) -> Path:
    if not STORAGE_KEY.fullmatch(key):
        raise AppError("not_found", 404)
    return settings.upload_dir / "attachments" / key


def safe_filename(value: str | None) -> str:
    name = (value or "file").replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(ch for ch in name if ch.isprintable() and ord(ch) not in range(0x202A, 0x202F) and ord(ch) not in range(0x2066, 0x206A))[:240] or "file"


def image_extension(header: bytes) -> str | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    return None


def detect_type(header: bytes, filename: str) -> tuple[str, str]:
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brands = header[8:12]
        if brands in (b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V "):
            return "video/mp4", "video"
    if header.startswith(b"\x1aE\xdf\xa3") and b"webm" in header[:512]:
        return "video/webm", "video"
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return mime[:100], "file"


def _store_file(upload: UploadFile, settings: Settings, limit: int, filename: str) -> tuple[str, int, str, str]:
    key = secrets.token_hex(16)
    path = media_directory(settings, "attachments") / key
    try:
        upload.file.seek(0)
        size = 0
        header = b""
        with path.open("xb") as output:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                check_size(size, limit)
                if not header:
                    header = chunk[:512]
                output.write(chunk)
        if not size:
            raise AppError("file_empty", 422)
        extension = image_extension(header)
        if extension:
            data = transform_image(path.read_bytes(), IMAGE_SPEC, extension, settings.max_image_pixels)
            check_size(len(data), limit)
            path.write_bytes(data)
            return key, len(data), "image/webp", "image"
        mime, kind = detect_type(header, filename)
        return key, size, mime, kind
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def store_attachment(db: AsyncSession, vault: Vault, settings: Settings, user: User, scope: str, scope_id: int, upload: UploadFile) -> Attachment:
    filename = safe_filename(upload.filename)
    key, size, mime, kind = await asyncio.to_thread(_store_file, upload, settings, attachment_limit(settings, user.platform_role), filename)
    attachment_id = new_id()
    metadata, key_id = vault.encrypt("attachment", json.dumps({"filename": filename}, ensure_ascii=False).encode(), f"attachment|{attachment_id}".encode())
    row = Attachment(
        id=attachment_id, owner_id=user.id, channel_id=scope_id if scope == "channel" else None,
        conversation_id=scope_id if scope == "dm" else None, storage_key=key, size_bytes=size,
        mime_type=mime, kind=kind, metadata_enc=metadata, key_id=key_id,
    )
    try:
        db.add(row)
        await db.flush()
    except BaseException:
        blob_path(settings, key).unlink(missing_ok=True)
        raise
    return row


def attachment_payload(vault: Vault, row: Attachment) -> dict:
    try:
        metadata = json.loads(vault.decrypt("attachment", row.metadata_enc, f"attachment|{row.id}".encode(), row.key_id))
        filename = metadata["filename"]
    except (DecryptionError, ValueError, KeyError):
        filename = "file"
    return {
        "id": str(row.id), "filename": filename, "size_bytes": row.size_bytes, "mime_type": row.mime_type,
        "kind": row.kind, "url": f"/api/v1/uploads/attachments/{row.id}",
    }


async def claim_attachments(db: AsyncSession, ids: list[int], author_id: int, scope: str, scope_id: int, message_id: int) -> None:
    if len(ids) > MAX_ATTACHMENTS or len(set(ids)) != len(ids) or any(not 0 < value < 2**63 for value in ids):
        raise AppError("attachment_invalid", 422)
    if not ids:
        return
    clause = Attachment.channel_id == scope_id if scope == "channel" else Attachment.conversation_id == scope_id
    result = await db.execute(
        update(Attachment).where(
            Attachment.id.in_(ids), Attachment.owner_id == author_id, clause,
            Attachment.message_id.is_(None), Attachment.created_at > utcnow() - PENDING_LIFETIME,
        ).values(message_id=message_id)
    )
    if result.rowcount != len(ids):
        raise AppError("attachment_invalid", 422)


async def attachments_for(db: AsyncSession, vault: Vault, message_ids: list[int]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    if message_ids:
        rows = (await db.execute(select(Attachment).where(Attachment.message_id.in_(message_ids)).order_by(Attachment.id))).scalars()
        for row in rows:
            grouped.setdefault(row.message_id, []).append(attachment_payload(vault, row))
    return grouped


async def delete_message_attachments(db: AsyncSession, settings: Settings, message_id: int) -> None:
    rows = (await db.execute(select(Attachment).where(Attachment.message_id == message_id))).scalars().all()
    await db.execute(delete(Attachment).where(Attachment.message_id == message_id))
    for row in rows:
        await asyncio.to_thread(blob_path(settings, row.storage_key).unlink, missing_ok=True)


async def cleanup_attachments(db: AsyncSession, settings: Settings) -> int:
    cutoff = utcnow() - PENDING_LIFETIME
    await db.execute(delete(Attachment).where(Attachment.message_id.is_(None), Attachment.created_at < cutoff))
    await db.commit()
    keys = set((await db.execute(select(Attachment.storage_key))).scalars())
    directory = media_directory(settings, "attachments")

    def remove_orphans():
        count = 0
        for path in directory.iterdir():
            if STORAGE_KEY.fullmatch(path.name) and path.name not in keys and path.stat().st_mtime < cutoff.timestamp():
                path.unlink(missing_ok=True)
                count += 1
        return count

    return await asyncio.to_thread(remove_orphans)
