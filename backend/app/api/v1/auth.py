from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.types import utcnow
from ...errors import AppError
from ...i18n import negotiate_language
from ...integrations.kreta.flows import FlowIntent, FlowState, FlowView
from ...models import AuthMethod, TotpConfig, User, UserIdentity
from ...models.enums import AccountStatus, AuditAction, AuthMethodKind, SessionScope
from ...security import audit_helpers
from ...security import totp as totp_service
from ...security.middleware import issue_csrf_token
from ...security.passwords import validate_password_policy
from ...security.ratelimit import enforce
from ...security.sessions import clear_cookie, revoke_session, revoke_user_sessions, set_cookie
from ...security import recovery as recovery_service
from ...services import accounts
from ...services.accounts import (
    apply_lockout,
    ensure_not_locked,
    verify_secret,
    clear_credentials,
    create_account_records,
    finalize_security_setup,
    identity_aad,
    issue_session,
    load_self_payload,
    normalize_display_name,
    normalize_username,
    totp_aad,
    username_taken,
)
from ..deps import Auth, any_session, cookie_names, get_db, get_settings, optional_auth, require_setup

router = APIRouter(prefix="/auth", tags=["auth"])
KRETA_COOKIE_SECONDS = 900


class KretaStartBody(BaseModel):
    intent: Literal["register", "recover"] = "register"
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class TwoFactorBody(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class ConfirmBody(BaseModel):
    confirmed: bool


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class CodeBody(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class LoginMethodBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    secret: str = Field(min_length=1, max_length=256)


class RecoveryCodeBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    recovery_code: str = Field(min_length=8, max_length=64)


@router.get("/csrf")
async def csrf(request: Request, response: Response) -> dict[str, str]:
    settings = request.app.state.settings
    existing = request.cookies.get(cookie_names(request).csrf)
    return {"csrf_token": issue_csrf_token(response, settings, existing)}


@router.get("/session")
async def session_info(auth: Auth | None = Depends(optional_auth), db: AsyncSession = Depends(get_db)) -> dict:
    if auth is None:
        return {"authenticated": False}
    if auth.user.status == AccountStatus.SUSPENDED.value:
        return {"authenticated": False, "suspended": True}
    if auth.session.scope == SessionScope.SETUP.value:
        return {"authenticated": False, "setup": {"username": auth.user.username, "display_name": auth.user.display_name}}
    return {"authenticated": True, "user": await load_self_payload(db, auth.user)}


async def identity_user(db: AsyncSession, identity_hash: str) -> User | None:
    statement = select(User).join(UserIdentity, UserIdentity.user_id == User.id).where(UserIdentity.identity_hash == identity_hash)
    return (await db.execute(statement)).scalar_one_or_none()


async def describe_flow(request: Request, db: AsyncSession, token: str, view: FlowView, intent: FlowIntent) -> dict:
    if view.state is FlowState.AWAITING_TWO_FACTOR:
        return {"status": "two_factor_required"}
    flows = request.app.state.kreta_flows
    existing = await identity_user(db, flows.identity_hash_of(token))
    if intent is FlowIntent.REGISTER and existing is not None and existing.status != AccountStatus.PENDING_SECURITY.value:
        await flows.cancel(token)
        raise AppError("already_registered", 409)
    if intent is FlowIntent.RECOVER:
        if existing is None:
            await flows.cancel(token)
            raise AppError("no_account", 404)
        if existing.status == AccountStatus.SUSPENDED.value:
            await flows.cancel(token)
            raise AppError("account_suspended", 403)
    return {"status": "identified", "full_name": view.full_name, "resume": existing is not None and intent is FlowIntent.REGISTER}


@router.post("/kreta/start")
async def kreta_start(body: KretaStartBody, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "kreta-ip", 8, 600)
    flows = request.app.state.kreta_flows
    names = cookie_names(request)
    await flows.cancel(request.cookies.get(names.kreta))
    enforce(request, "kreta-user", 6, 600, subject=flows.identity_hash(body.username))
    intent = FlowIntent(body.intent)
    view = await flows.begin(intent, body.username, body.password)
    payload = await describe_flow(request, db, view.token, view, intent)
    set_cookie(response, get_settings(request), names.kreta, view.token, max_age=KRETA_COOKIE_SECONDS, same_site="strict")
    return payload


@router.post("/kreta/two-factor")
async def kreta_two_factor(body: TwoFactorBody, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "kreta-2fa", 10, 600)
    flows = request.app.state.kreta_flows
    token = request.cookies.get(cookie_names(request).kreta)
    if not token:
        raise AppError("kreta_flow_invalid", 409)
    flow_intent = flows.intent_of(token)
    view = await flows.submit_two_factor(token, body.code)
    return await describe_flow(request, db, token, view, flow_intent)


@router.post("/kreta/confirm")
async def kreta_confirm(body: ConfirmBody, request: Request, response: Response) -> dict[str, str]:
    flows = request.app.state.kreta_flows
    names = cookie_names(request)
    token = request.cookies.get(names.kreta)
    if not token:
        raise AppError("kreta_flow_invalid", 409)
    await flows.decide(token, body.confirmed)
    if not body.confirmed:
        clear_cookie(response, get_settings(request), names.kreta)
        return {"status": "cancelled"}
    return {"status": "confirmed"}


@router.post("/kreta/cancel")
async def kreta_cancel(request: Request, response: Response) -> dict[str, str]:
    names = cookie_names(request)
    await request.app.state.kreta_flows.cancel(request.cookies.get(names.kreta))
    clear_cookie(response, get_settings(request), names.kreta)
    return {"status": "cancelled"}


@router.post("/register")
async def register(body: RegisterBody, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "register", 15, 3600)
    settings = get_settings(request)
    flows = request.app.state.kreta_flows
    vault = request.app.state.vault
    names = cookie_names(request)
    token = request.cookies.get(names.kreta)
    flow = flows.peek_confirmed(token, FlowIntent.REGISTER)
    username = normalize_username(body.username)
    display_name = normalize_display_name(body.display_name)
    existing = await identity_user(db, flow.identity_hash)
    if existing is not None and existing.status != AccountStatus.PENDING_SECURITY.value:
        raise AppError("already_registered", 409)
    if await username_taken(db, username, existing.id if existing else None):
        raise AppError("username_taken", 409)
    full_name = flow.full_name or ""
    try:
        if existing is None:
            user = User(username=username, username_lower=username, display_name=display_name)
            await create_account_records(
                db, vault, user=user, identity_hash=flow.identity_hash, full_name=full_name, language=negotiate_language(request.headers.get("accept-language"))
            )
        else:
            user = existing
            user.username = username
            user.username_lower = username
            user.display_name = display_name
            identity = await db.get(UserIdentity, user.id)
            identity.real_name_enc, identity.key_id = vault.encrypt("identity", full_name.encode("utf-8"), identity_aad(user.id))
            await revoke_user_sessions(db, user.id)
        await issue_session(db, request, response, user.id, SessionScope.SETUP)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError("username_taken", 409)
    flows.finish(token)
    clear_cookie(response, settings, names.kreta)
    return {"username": user.username, "display_name": user.display_name, "next": "security"}


@router.post("/recover/kreta")
async def recover_with_kreta(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "recover", 10, 3600)
    flows = request.app.state.kreta_flows
    names = cookie_names(request)
    token = request.cookies.get(names.kreta)
    flow = flows.peek_confirmed(token, FlowIntent.RECOVER)
    user = await identity_user(db, flow.identity_hash)
    if user is None:
        raise AppError("no_account", 404)
    if user.status == AccountStatus.SUSPENDED.value:
        raise AppError("account_suspended", 403)
    await revoke_user_sessions(db, user.id)
    await issue_session(db, request, response, user.id, SessionScope.SETUP)
    audit_helpers.record_recovery(db, user.id, "kreta")
    await db.commit()
    flows.finish(token)
    clear_cookie(response, get_settings(request), names.kreta)
    return {"username": user.username, "display_name": user.display_name, "next": "security"}


@router.post("/recover/code")
async def recover_with_code(body: RecoveryCodeBody, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "recover-code-ip", 8, 3600)
    username = body.username.strip().lower()
    enforce(request, "recover-code-user", 6, 3600, subject=username)
    vault = request.app.state.vault
    user = (await db.execute(select(User).where(User.username_lower == username))).scalar_one_or_none()
    code_hash = recovery_service.hash_code(vault, body.recovery_code)
    row = await audit_helpers.consume_recovery_code(db, user.id, code_hash) if user is not None else None
    if user is None or row is None or user.status != AccountStatus.ACTIVE.value:
        raise AppError("invalid_recovery_code", 401)
    await revoke_user_sessions(db, user.id)
    await issue_session(db, request, response, user.id, SessionScope.SETUP)
    audit_helpers.record_recovery(db, user.id, "recovery_code")
    await db.commit()
    return {"username": user.username, "display_name": user.display_name, "next": "security"}


@router.post("/security/password")
async def setup_password(
    body: PasswordBody, request: Request, response: Response, auth: Auth = Depends(require_setup), db: AsyncSession = Depends(get_db)
) -> dict:
    enforce(request, "security-setup", 20, 3600, subject=str(auth.user.id))
    validate_password_policy(body.password, auth.user.username)
    hashed = await request.app.state.passwords.hash(body.password)
    await clear_credentials(db, auth.user.id)
    db.add(AuthMethod(user_id=auth.user.id, method=AuthMethodKind.PASSWORD.value, password_hash=hashed))
    codes = await finalize_security_setup(db, request, response, auth.user, auth.session.id)
    payload = await load_self_payload(db, auth.user)
    await db.commit()
    return {"user": payload, "recovery_codes": codes}


def group_secret(secret: str) -> str:
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


@router.post("/security/totp/begin")
async def totp_begin(request: Request, auth: Auth = Depends(require_setup), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "security-setup", 20, 3600, subject=str(auth.user.id))
    settings = get_settings(request)
    secret = totp_service.generate_secret()
    blob, key_id = request.app.state.vault.encrypt("totp", secret.encode("ascii"), totp_aad(auth.user.id))
    row = await db.get(TotpConfig, auth.user.id)
    if row is None:
        db.add(TotpConfig(user_id=auth.user.id, secret_enc=blob, key_id=key_id))
    else:
        row.secret_enc, row.key_id, row.confirmed_at, row.last_used_step = blob, key_id, None, 0
    await db.commit()
    uri = totp_service.provisioning_uri(secret, auth.user.username, settings.app_name)
    return {"manual_key": group_secret(secret), "otpauth_uri": uri, "qr_svg": totp_service.qr_data_uri(uri)}


@router.post("/security/totp/confirm")
async def totp_confirm(
    body: CodeBody, request: Request, response: Response, auth: Auth = Depends(require_setup), db: AsyncSession = Depends(get_db)
) -> dict:
    enforce(request, "totp-confirm", 15, 600, subject=str(auth.user.id))
    row = await db.get(TotpConfig, auth.user.id)
    if row is None or row.confirmed_at is not None:
        raise AppError("totp_not_started", 409)
    secret = request.app.state.vault.decrypt("totp", row.secret_enc, totp_aad(auth.user.id), row.key_id).decode("ascii")
    step = totp_service.verify_code(secret, body.code, 0)
    if step is None:
        raise AppError("totp_code_invalid", 422)
    row.confirmed_at = utcnow()
    row.last_used_step = step
    method = await db.get(AuthMethod, auth.user.id)
    if method is None:
        db.add(AuthMethod(user_id=auth.user.id, method=AuthMethodKind.TOTP.value))
    else:
        method.method, method.password_hash, method.failed_attempts, method.locked_until = AuthMethodKind.TOTP.value, None, 0, None
    codes = await finalize_security_setup(db, request, response, auth.user, auth.session.id)
    payload = await load_self_payload(db, auth.user)
    await db.commit()
    return {"user": payload, "recovery_codes": codes}


@router.post("/login/method")
async def login_method(body: LoginMethodBody, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    enforce(request, "login-method", 40, 600)
    username = body.username.strip().lower()[:32]
    user = (await db.execute(select(User).where(User.username_lower == username))).scalar_one_or_none()
    method = await db.get(AuthMethod, user.id) if user else None
    if method is not None:
        return {"method": method.method}
    digest = request.app.state.vault.mac("login-method", username.encode("utf-8"))
    return {"method": AuthMethodKind.TOTP.value if digest[0] % 2 else AuthMethodKind.PASSWORD.value}


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "login-ip", 30, 600)
    username = body.username.strip().lower()[:32]
    enforce(request, "login-user", 12, 600, subject=username)
    settings = get_settings(request)
    passwords = request.app.state.passwords
    user = (await db.execute(select(User).where(User.username_lower == username))).scalar_one_or_none()
    method = await db.get(AuthMethod, user.id) if user else None
    if user is None or method is None:
        await passwords.burn(body.secret)
        raise AppError("invalid_credentials", 401)
    now = utcnow()
    ensure_not_locked(method)
    valid = await verify_secret(request, db, user, method, body.secret)
    if not valid:
        await apply_lockout(db, method, settings)
        await db.commit()
        raise AppError("invalid_credentials", 401)
    method.failed_attempts = 0
    method.locked_until = None
    if user.status == AccountStatus.SUSPENDED.value:
        await db.commit()
        raise AppError("account_suspended", 403)
    if user.status != AccountStatus.ACTIVE.value:
        raise AppError("invalid_credentials", 401)
    user.last_seen_at = now
    await issue_session(db, request, response, user.id, SessionScope.FULL)
    payload = await load_self_payload(db, user)
    await db.commit()
    return {"user": payload}


@router.post("/logout")
async def logout(request: Request, response: Response, auth: Auth = Depends(any_session), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await revoke_session(db, auth.session.id)
    await db.commit()
    clear_cookie(response, get_settings(request), cookie_names(request).session)
    await request.app.state.hub.close_user_session(auth.user.id, auth.session.id)
    return {"status": "ok"}
