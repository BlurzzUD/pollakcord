from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_db
from ..errors import AppError
from ..models import BotApplication, User
from ..models.enums import AccountStatus, PlatformRole
from .ratelimit import enforce
from .sessions import hash_token

MAX_BOTS_PER_OWNER = 3
MAX_COMMANDS_PER_BOT = 25
MAX_GATEWAYS_PER_BOT = 1
MAX_GATEWAYS_PER_OWNER = 3
INTERACTION_TIMEOUT_SECONDS = 3.0


@dataclass
class BotAuth:
    application: BotApplication
    user: User
    owner: User


async def authenticate_bot(db: AsyncSession, token: str, *, lock: bool = False) -> BotAuth:
    if not 40 <= len(token) <= 128:
        raise AppError("bot_token_invalid", 401)
    statement = select(BotApplication).where(BotApplication.token_hash == hash_token(token), BotApplication.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    application = (await db.execute(statement)).scalar_one_or_none()
    if application is None:
        raise AppError("bot_token_invalid", 401)
    if lock:
        user = (await db.execute(select(User).where(User.id == application.bot_user_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        owner = (await db.execute(select(User).where(User.id == application.owner_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    else:
        user = await db.get(User, application.bot_user_id)
        owner = await db.get(User, application.owner_id)
    if user is None or not user.is_bot or user.platform_role != PlatformRole.USER.value or user.school_class_id is not None:
        raise AppError("bot_token_invalid", 401)
    if owner is None or owner.is_bot or owner.status != AccountStatus.ACTIVE.value or user.status != AccountStatus.ACTIVE.value:
        raise AppError("bot_disabled", 403)
    return BotAuth(application, user, owner)


def bot_rate(request, auth: BotAuth, name: str, limit: int, window: float, owner_limit: int | None = None) -> None:
    enforce(request, f"bot-{name}", limit, window, subject=str(auth.user.id))
    enforce(request, f"bot-owner-{name}", owner_limit or limit * 2, window, subject=str(auth.owner.id))


async def require_bot(request: Request, db: AsyncSession = Depends(get_db)) -> AsyncIterator[BotAuth]:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bot" or not token or request.cookies.get(request.app.state.cookies.session) or request.headers.get("origin"):
        raise AppError("bot_token_invalid", 401)
    enforce(request, "bot-auth-ip", 240, 60)
    initial = await authenticate_bot(db, token)
    bot_id = initial.user.id
    await db.rollback()
    async with request.app.state.bot_gateway.lock(f"bot:{bot_id}"):
        auth = await authenticate_bot(db, token, lock=True)
        bot_rate(request, auth, "rest", 120, 60, 240)
        yield auth
