import hashlib
import secrets
from datetime import timedelta

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db.types import utcnow
from ..models import AuthSession, User
from ..models.enums import SessionScope

LAST_SEEN_REFRESH = timedelta(minutes=5)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CookieNames:
    def __init__(self, settings: Settings) -> None:
        prefix = "__Host-" if settings.cookie_secure else ""
        self.session = f"{prefix}pc_session"
        self.csrf = f"{prefix}pc_csrf"
        self.kreta = f"{prefix}pc_kreta"


def set_cookie(
    response: Response,
    settings: Settings,
    name: str,
    value: str,
    *,
    max_age: int,
    http_only: bool = True,
    same_site: str = "lax",
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=settings.cookie_secure,
        httponly=http_only,
        samesite=same_site,
    )


def clear_cookie(response: Response, settings: Settings, name: str) -> None:
    response.delete_cookie(name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")


async def create_session(
    db: AsyncSession, user_id: int, scope: SessionScope, settings: Settings, ip_hint: str, user_agent: str
) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    if scope is SessionScope.SETUP:
        lifetime = timedelta(minutes=settings.setup_session_ttl_minutes)
    else:
        lifetime = timedelta(hours=settings.session_ttl_hours)
    record = AuthSession(
        user_id=user_id,
        token_hash=hash_token(token),
        scope=scope.value,
        expires_at=utcnow() + lifetime,
        ip_hint=ip_hint[:64],
        user_agent=user_agent[:200],
    )
    db.add(record)
    await db.flush()
    return token, record.id


async def load_session(db: AsyncSession, token: str, settings: Settings) -> tuple[AuthSession, User] | None:
    statement = (
        select(AuthSession, User).join(User, User.id == AuthSession.user_id).where(AuthSession.token_hash == hash_token(token))
    )
    row = (await db.execute(statement)).first()
    if row is None:
        return None
    record, user = row
    now = utcnow()
    if record.revoked_at is not None or record.expires_at <= now:
        return None
    if record.scope == SessionScope.FULL.value and record.last_seen_at + timedelta(hours=settings.session_idle_hours) < now:
        return None
    if now - record.last_seen_at > LAST_SEEN_REFRESH:
        record.last_seen_at = now
        await db.commit()
    return record, user


async def revoke_session(db: AsyncSession, session_id: int) -> None:
    await db.execute(update(AuthSession).where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))


async def revoke_user_sessions(db: AsyncSession, user_id: int, keep_session_id: int | None = None) -> None:
    statement = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if keep_session_id is not None:
        statement = statement.where(AuthSession.id != keep_session_id)
    await db.execute(statement.values(revoked_at=utcnow()))
