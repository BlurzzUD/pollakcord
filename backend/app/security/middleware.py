import hmac
import secrets
import time
import uuid
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..config import Settings
from ..i18n import negotiate_language, translate
from ..logging_config import get_logger, request_id_var
from .sessions import CookieNames, set_cookie

logger = get_logger("pollakcord.http")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT_PATHS: set[str] = set()


def build_csp(settings: Settings) -> str:
    parsed = urlparse(settings.public_origin)
    websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
    websocket_origin = f"{websocket_scheme}://{parsed.netloc}"
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self'",
            "media-src 'self' blob:",
            f"connect-src 'self' {websocket_origin}",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


def origin_allowed(request: Request, settings: Settings) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer")
        if not referer:
            return False
        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin.rstrip("/") in settings.allowed_origins


def _csrf_failure(request: Request, code: str) -> JSONResponse:
    language = negotiate_language(request.headers.get("accept-language"))
    return JSONResponse({"error": {"code": code, "message": translate("errors", code, language)}}, status_code=403)


def install_http_middleware(app: FastAPI, settings: Settings) -> None:
    names = CookieNames(settings)
    csp = build_csp(settings)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        request_id = uuid.uuid4().hex[:16]
        request_id_var.set(request_id)
        started = time.perf_counter()
        path = request.url.path
        if request.method not in SAFE_METHODS and path.startswith("/api/") and path not in CSRF_EXEMPT_PATHS:
            if not origin_allowed(request, settings):
                return _csrf_failure(request, "origin_not_allowed")
            cookie_value = request.cookies.get(names.csrf, "")
            header_value = request.headers.get("x-csrf-token", "")
            if not cookie_value or not hmac.compare_digest(cookie_value, header_value):
                return _csrf_failure(request, "csrf_failed")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        if "content-security-policy" not in response.headers:
            response.headers["Content-Security-Policy"] = csp
        response.headers["X-Frame-Options"] = "DENY"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request",
            extra={"method": request.method, "path": path, "status": response.status_code, "ms": round((time.perf_counter() - started) * 1000, 1)},
        )
        return response


def issue_csrf_token(response, settings: Settings, existing: str | None) -> str:
    token = existing or secrets.token_urlsafe(32)
    names = CookieNames(settings)
    set_cookie(response, settings, names.csrf, token, max_age=60 * 60 * 24 * 30, http_only=False, same_site="strict")
    return token
