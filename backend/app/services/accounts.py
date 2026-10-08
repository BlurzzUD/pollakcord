import re
import unicodedata
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..crypto.envelope import Vault
from ..db.types import utcnow
from ..errors import AppError
from ..models import AuthMethod, Profile, RecoveryCode, TotpConfig, User, UserSettings
from ..models.enums import AccountStatus, AuthMethodKind, SessionScope
from ..security import totp as totp_service
from ..security import recovery
from ..security.sessions import CookieNames, create_session, revoke_user_sessions, set_cookie
from ..security.deps_ip import client_ip, mask_ip

USERNAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_.]{1,22})[a-z0-9]$")
RESERVED_USERNAMES = frozenset(
    {"admin", "administrator", "moderator", "mod", "system", "support", "staff", "pollakcord", "pollak", "ekreta", "kreta", "root", "everyone", "here", "null", "deleted"}
)
MAX_DISPLAY_NAME = 32


def normalize_username(raw: str) -> str:
    candidate = unicodedata.normalize("NFKC", raw).strip().lower()
    if not USERNAME_PATTERN.match(candidate) or ".." in candidate or "__" in candidate:
        raise AppError("username_invalid", 422)
    if candidate in RESERVED_USERNAMES:
        raise AppError("username_reserved", 422)
    return candidate


def normalize_display_name(raw: str) -> str:
    candidate = re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw)).strip()
    if not 1 <= len(candidate) <= MAX_DISPLAY_NAME:
        raise AppError("display_name_invalid", 422, params={"max": MAX_DISPLAY_NAME})
    if any(unicodedata.category(ch).startswith("C") for ch in candidate):
        raise AppError("display_name_invalid", 422, params={"max": MAX_DISPLAY_NAME})
    return candidate


async def username_taken(db: AsyncSession, username: str, ignore_user_id: int | None = None) -> bool:
    statement = select(User.id).where(User.username_lower == username)
    found = (await db.execute(statement)).scalar_one_or_none()
    return found is not None and found != ignore_user_id


def identity_aad(user_id: int) -> bytes:
    return f"identity|{user_id}".encode()


def totp_aad(user_id: int) -> bytes:
    return f"totp|{user_id}".encode()


def start_session_cookie(response: Response, settings: Settings, names: CookieNames, token: str, scope: SessionScope) -> None:
    if scope is SessionScope.SETUP:
        max_age = settings.setup_session_ttl_minutes * 60
    else:
        max_age = settings.session_ttl_hours * 3600
    set_cookie(response, settings, names.session, token, max_age=max_age)


async def issue_session(
    db: AsyncSession, request: Request, response: Response, user_id: int, scope: SessionScope
) -> int:
    settings: Settings = request.app.state.settings
    names: CookieNames = request.app.state.cookies
    token, session_id = await create_session(
        db, user_id, scope, settings, mask_ip(client_ip(request)), request.headers.get("user-agent", "")
    )
    start_session_cookie(response, settings, names, token, scope)
    return session_id


async def issue_recovery_codes(db: AsyncSession, vault: Vault, user_id: int) -> list[str]:
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    codes = recovery.generate_codes()
    for code in codes:
        db.add(RecoveryCode(user_id=user_id, code_hash=recovery.hash_code(vault, code)))
    return codes


async def finalize_security_setup(
    db: AsyncSession, request: Request, response: Response, user: User, current_session_id: int
) -> list[str]:
    vault: Vault = request.app.state.vault
    if user.status == AccountStatus.PENDING_SECURITY.value:
        user.status = AccountStatus.ACTIVE.value
    codes = await issue_recovery_codes(db, vault, user.id)
    await revoke_user_sessions(db, user.id)
    await issue_session(db, request, response, user.id, SessionScope.FULL)
    return codes


async def apply_lockout(db: AsyncSession, method: AuthMethod, settings: Settings) -> None:
    method.failed_attempts += 1
    overflow = method.failed_attempts - settings.lockout_threshold
    if overflow >= 0:
        delay = min(settings.lockout_base_seconds * (2**overflow), settings.lockout_max_seconds)
        method.locked_until = utcnow() + timedelta(seconds=delay)


async def create_account_records(
    db: AsyncSession,
    vault: Vault,
    *,
    user: User,
    identity_hash: str,
    full_name: str,
    language: str,
) -> None:
    from ..models import UserIdentity

    db.add(user)
    await db.flush()
    blob, key_id = vault.encrypt("identity", full_name.encode("utf-8"), identity_aad(user.id))
    db.add(UserIdentity(user_id=user.id, identity_hash=identity_hash, real_name_enc=blob, key_id=key_id))
    db.add(Profile(user_id=user.id))
    db.add(UserSettings(user_id=user.id, language=language))
    await db.flush()


async def clear_credentials(db: AsyncSession, user_id: int) -> None:
    await db.execute(delete(TotpConfig).where(TotpConfig.user_id == user_id))
    method = await db.get(AuthMethod, user_id)
    if method is not None:
        await db.delete(method)
    await db.flush()


def method_kind(value: str) -> AuthMethodKind:
    return AuthMethodKind(value)


async def load_self_payload(db: AsyncSession, user: User) -> dict:
    from ..models import SchoolClass
    from ..services.privacy import get_settings_row
    from ..services.serializers import self_user

    profile = await db.get(Profile, user.id)
    settings_row = await get_settings_row(db, user.id)
    class_code = None
    if user.school_class_id is not None:
        school_class = await db.get(SchoolClass, user.school_class_id)
        class_code = school_class.code if school_class else None
    return self_user(user, profile, settings_row, class_code)


def ensure_not_locked(method: AuthMethod) -> None:
    now = utcnow()
    if method.locked_until is not None and method.locked_until > now:
        seconds = int((method.locked_until - now).total_seconds()) + 1
        raise AppError("rate_limited", 429, params={"seconds": seconds}, headers={"Retry-After": str(seconds)})


async def verify_secret(request: Request, db: AsyncSession, user: User, method: AuthMethod, secret: str) -> bool:
    passwords = request.app.state.passwords
    vault: Vault = request.app.state.vault
    if method.method == AuthMethodKind.PASSWORD.value and method.password_hash:
        valid, upgraded = await passwords.verify(method.password_hash, secret)
        if valid and upgraded:
            method.password_hash = upgraded
        return valid
    if method.method == AuthMethodKind.TOTP.value:
        row = await db.get(TotpConfig, user.id)
        if row is not None and row.confirmed_at is not None:
            plain = vault.decrypt("totp", row.secret_enc, totp_aad(user.id), row.key_id).decode("ascii")
            step = totp_service.verify_code(plain, secret, row.last_used_step)
            if step is not None:
                row.last_used_step = step
                return True
            return False
    await passwords.burn(secret)
    return False
