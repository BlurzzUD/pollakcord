from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .i18n import negotiate_language, translate
from .logging_config import get_logger

logger = get_logger("pollakcord.errors")


class AppError(Exception):
    def __init__(
        self,
        code: str,
        status: int = 400,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.params = params or {}
        self.headers = headers or {}


def not_found(code: str = "not_found") -> AppError:
    return AppError(code, 404)


def forbidden(code: str = "forbidden") -> AppError:
    return AppError(code, 403)


def _body(request: Request, code: str, params: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    language = negotiate_language(request.headers.get("accept-language"))
    payload: dict[str, Any] = {"code": code, "message": translate("errors", code, language, **params)}
    if params:
        payload["params"] = params
    if extra:
        payload.update(extra)
    return {"error": payload}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(request, exc.code, exc.params), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in err.get("loc", ())[1:]), "code": str(err.get("type", "invalid"))}
            for err in exc.errors()
        ]
        return JSONResponse(_body(request, "validation_error", {}, {"fields": fields}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthenticated", 403: "forbidden"}.get(exc.status_code, "request_failed")
        return JSONResponse(_body(request, code, {}), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", extra={"error_type": type(exc).__name__, "path": request.url.path})
        return JSONResponse(_body(request, "internal_error", {}), status_code=500)
