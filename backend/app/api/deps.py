from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..errors import AppError
from ..i18n import negotiate_language
from ..models import AuthSession, User
from ..models.enums import AccountStatus, PlatformRole, SessionScope
from ..realtime.outbox import Outbox
from ..security.deps_ip import client_ip, mask_ip
from ..security.sessions import CookieNames, load_session


@dataclass
class Auth:
    user: User
    session: AuthSession


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_outbox(request: Request) -> Outbox:
    return Outbox(request.app.state.hub)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_language(request: Request) -> str:
    return negotiate_language(request.headers.get("accept-language"))


def session_cookie_name(request: Request) -> str:
    return request.app.state.cookies.session


async def optional_auth(request: Request, db: AsyncSession = Depends(get_db)) -> Auth | None:
    token = request.cookies.get(session_cookie_name(request))
    if not token:
        return None
    loaded = await load_session(db, token, request.app.state.settings)
    if loaded is None:
        return None
    record, user = loaded
    return Auth(user=user, session=record)


async def any_session(auth: Auth | None = Depends(optional_auth)) -> Auth:
    if auth is None:
        raise AppError("unauthenticated", 401)
    if auth.user.status == AccountStatus.SUSPENDED.value:
        raise AppError("account_suspended", 403)
    return auth


async def require_auth(auth: Auth = Depends(any_session)) -> Auth:
    if auth.session.scope != SessionScope.FULL.value:
        raise AppError("account_setup_required", 403)
    if auth.user.status != AccountStatus.ACTIVE.value:
        raise AppError("account_setup_required", 403)
    return auth


async def require_setup(auth: Auth = Depends(any_session)) -> Auth:
    if auth.session.scope != SessionScope.SETUP.value:
        raise AppError("setup_session_required", 403)
    return auth


async def require_moderator(auth: Auth = Depends(require_auth)) -> Auth:
    if auth.user.platform_role not in (PlatformRole.SCHOOL_MODERATOR.value, PlatformRole.SCHOOL_ADMIN.value):
        raise AppError("not_found", 404)
    return auth


def request_fingerprint(request: Request) -> tuple[str, str]:
    return mask_ip(client_ip(request)), request.headers.get("user-agent", "")[:200]


def cookie_names(request: Request) -> CookieNames:
    return request.app.state.cookies
