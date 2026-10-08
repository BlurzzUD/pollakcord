import asyncio
import io
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import Settings
from ..errors import AppError

ALLOWED_FORMATS = {"PNG": {"png"}, "JPEG": {"jpg", "jpeg"}, "WEBP": {"webp"}, "GIF": {"gif"}}
MEDIA_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.webp$")
MEDIA_KINDS = ("avatar", "banner", "server_icon")


@dataclass(frozen=True)
class ImageSpec:
    max_bytes_attr: str
    min_width: int
    min_height: int
    max_source_dimension: int
    output_size: tuple[int, int]
    square: bool


SPECS = {
    "avatar": ImageSpec("avatar_max_bytes", 64, 64, 6000, (512, 512), True),
    "server_icon": ImageSpec("icon_max_bytes", 64, 64, 6000, (256, 256), True),
    "banner": ImageSpec("banner_max_bytes", 300, 100, 8000, (1600, 640), False),
}


async def read_limited(upload: UploadFile, limit: int) -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise AppError("file_too_large", 413, params={"max_bytes": limit})
    if not data:
        raise AppError("file_empty", 422)
    return data


def extension_of(filename: str | None) -> str:
    if not filename or "." not in filename:
        raise AppError("file_type_not_allowed", 415)
    return filename.rsplit(".", 1)[-1].lower()


def transform_image(data: bytes, spec: ImageSpec, extension: str, max_pixels: int) -> bytes:
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as probe:
            detected = probe.format or ""
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError) as exc:
        raise AppError("file_not_an_image", 415) from exc
    if detected not in ALLOWED_FORMATS or extension not in ALLOWED_FORMATS[detected]:
        raise AppError("file_type_not_allowed", 415)
    if width * height > max_pixels or max(width, height) > spec.max_source_dimension:
        raise AppError("image_dimensions_too_large", 422)
    if width < spec.min_width or height < spec.min_height:
        raise AppError("image_dimensions_too_small", 422, params={"min_width": spec.min_width, "min_height": spec.min_height})
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.seek(0)
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            if spec.square:
                image = ImageOps.fit(image, spec.output_size, method=Image.Resampling.LANCZOS)
            else:
                image.thumbnail(spec.output_size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=86, method=4)
            return output.getvalue()
    except (OSError, Image.DecompressionBombError, ValueError) as exc:
        raise AppError("file_not_an_image", 415) from exc


async def process_image_upload(kind: str, upload: UploadFile, settings: Settings) -> bytes:
    spec = SPECS[kind]
    extension = extension_of(upload.filename)
    data = await read_limited(upload, getattr(settings, spec.max_bytes_attr))
    return await asyncio.to_thread(transform_image, data, spec, extension, settings.max_image_pixels)


def media_directory(settings: Settings, kind: str) -> Path:
    directory = settings.upload_dir / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def store_image(settings: Settings, kind: str, data: bytes) -> str:
    key = secrets.token_hex(16) + ".webp"
    (media_directory(settings, kind) / key).write_bytes(data)
    return key


def delete_image(settings: Settings, kind: str, key: str | None) -> None:
    if key and MEDIA_KEY_PATTERN.match(key):
        (settings.upload_dir / kind / key).unlink(missing_ok=True)


def media_path(settings: Settings, kind: str, key: str) -> Path:
    if kind not in MEDIA_KINDS or not MEDIA_KEY_PATTERN.match(key):
        raise AppError("not_found", 404)
    path = settings.upload_dir / kind / key
    if not path.is_file():
        raise AppError("not_found", 404)
    return path
