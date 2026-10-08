from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    url = settings.database_url
    if url.startswith("sqlite"):
        engine = create_async_engine(url, future=True)

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine
    return create_async_engine(url, future=True, pool_size=settings.database_pool_size, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
