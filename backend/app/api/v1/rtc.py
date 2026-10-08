import base64
import hashlib
import hmac
import time

from fastapi import APIRouter, Depends, Request

from ..deps import Auth, require_auth

router = APIRouter(prefix="/rtc", tags=["rtc"])


@router.get("/config")
async def rtc_config(request: Request, auth: Auth = Depends(require_auth)) -> dict:
    settings = request.app.state.settings
    servers: list[dict] = []
    if settings.stun_list:
        servers.append({"urls": settings.stun_list})
    if settings.turn_list and settings.turn_secret is not None:
        expiry = int(time.time()) + settings.turn_ttl_seconds
        username = f"{expiry}:{auth.user.id}"
        digest = hmac.new(settings.turn_secret.get_secret_value().encode("utf-8"), username.encode("utf-8"), hashlib.sha1).digest()
        servers.append({"urls": settings.turn_list, "username": username, "credential": base64.b64encode(digest).decode("ascii")})
    return {"ice_servers": servers, "max_participants": settings.voice_max_participants}
