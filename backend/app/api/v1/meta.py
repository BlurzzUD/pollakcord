from fastapi import APIRouter, Request

from ...services.messages import ALLOWED_REACTIONS
from ...services.permissions import PERMISSION_NAMES
from .messaging import REPORT_REASONS

router = APIRouter(tags=["meta"])


@router.get("/meta")
async def meta(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "app_name": settings.app_name,
        "reactions": list(ALLOWED_REACTIONS),
        "permissions": list(PERMISSION_NAMES),
        "report_reasons": list(REPORT_REASONS),
        "limits": {"message_max_length": settings.message_max_length, "voice_max_participants": settings.voice_max_participants},
        "languages": ["hu", "en", "de"],
    }
