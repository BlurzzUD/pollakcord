from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from .api.v1.router import api_router
from .config import Settings, get_settings
from .crypto.envelope import Vault
from .crypto.keyring import load_keyring
from .db.base import Base
from .db.session import build_engine, build_session_factory
from .errors import AppError, install_error_handlers
from .integrations.kreta.adapter import KretaAuthPort, KretaScriptAdapter
from .integrations.kreta.flows import KretaFlowStore
from .logging_config import configure_logging, get_logger
from .realtime.hub import Hub
from .realtime.voice import VoiceManager
from .security.middleware import install_http_middleware
from .security.passwords import PasswordService
from .security.ratelimit import RateLimiter
from .security.sessions import CookieNames
from .seed import ensure_school_classes
from .services.dok import DokService
from .services.messages import MessageService
from .services.uploads import media_path
from .spa import mount_frontend

logger = get_logger("pollakcord.app")


def create_app(settings: Settings | None = None, kreta_adapter: KretaAuthPort | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(settings)
        if settings.auto_create_schema:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        factory = build_session_factory(engine)
        async with factory() as db:
            await ensure_school_classes(db)
        vault = Vault(load_keyring(settings))
        adapter = kreta_adapter
        if adapter is None:
            real = KretaScriptAdapter.from_settings(settings)
            digest = real.verify_script()
            logger.info("kreta_script_verified", extra={"sha256": digest[:16]})
            adapter = real
        flows = KretaFlowStore(
            adapter,
            vault,
            namespace=settings.kreta_identity_namespace,
            two_factor_ttl=settings.kreta_flow_ttl_seconds,
            max_concurrent=settings.kreta_max_concurrent,
        )
        flows.start_sweeper()
        hub = Hub()
        app.state.engine = engine
        app.state.session_factory = factory
        app.state.vault = vault
        app.state.passwords = PasswordService(settings)
        app.state.limiter = RateLimiter(settings.rate_limit_enabled)
        app.state.hub = hub
        app.state.voice = VoiceManager(settings.voice_max_participants)
        app.state.messages = MessageService(vault, settings)
        app.state.dok = DokService(vault, settings)
        app.state.kreta_flows = flows
        from .realtime.ws import install_revalidator

        install_revalidator(app)
        logger.info("startup_complete", extra={"environment": settings.environment})
        yield
        from .realtime.ws import shutdown_realtime

        await shutdown_realtime(app)
        await flows.shutdown()
        await engine.dispose()

    docs = None if settings.is_production else "/api/docs"
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan, docs_url=docs, redoc_url=None, openapi_url=None if docs is None else "/api/openapi.json")
    app.state.settings = settings
    app.state.cookies = CookieNames(settings)
    install_error_handlers(app)
    install_http_middleware(app, settings)
    app.include_router(api_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        async with app.state.session_factory() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/media/{kind}/{key}", include_in_schema=False)
    async def media(kind: str, key: str) -> FileResponse:
        path = media_path(settings, kind, key)
        return FileResponse(
            path,
            media_type="image/webp",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline",
            },
        )

    mount_frontend(app, settings)
    return app


def build_default_app() -> FastAPI:
    return create_app()
