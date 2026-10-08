import re
import unicodedata
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.types import utcnow
from ...errors import AppError
from ...models import AuthMethod, AuthSession, RecoveryCode, SchoolClass, Theme, User
from ...models.enums import ClassVisibility, SessionScope
from ...security.ratelimit import enforce
from ...security.sessions import revoke_session
from ...services import accounts
from ...services.accounts import ensure_not_locked, issue_session, load_self_payload, normalize_display_name, verify_secret, apply_lockout
from ...services.css_sanitizer import CssRejected, sanitize_css
from ...services.privacy import get_settings_row
from ...services.serializers import iso, sid
from ..deps import Auth, get_db, get_settings, require_auth

router = APIRouter(prefix="/me", tags=["me"])
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
GRADIENT = re.compile(r"^linear-gradient\(\s*\d{1,3}deg\s*,\s*#[0-9a-fA-F]{6}\s*,\s*#[0-9a-fA-F]{6}\s*\)$")
THEME_COLOR_KEYS = ("bg", "bg_alt", "bg_deep", "text", "text_muted", "accent", "accent_text", "danger", "mention", "border")
THEME_KEYS = THEME_COLOR_KEYS + ("background", "radius")
NOTIFICATION_KEYS = ("friend_requests", "direct_messages", "mentions", "server", "calls", "moderation", "sounds")
MAX_THEMES = 12


class ProfileBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=600)
    accent_color: str | None = Field(default=None, max_length=7)
    clear_accent: bool = False


class SettingsBody(BaseModel):
    language: Literal["hu", "en", "de"] | None = None
    theme_mode: Literal["system", "dark", "light", "custom"] | None = None
    active_theme_id: str | None = None
    clear_active_theme: bool = False
    custom_css: str | None = Field(default=None, max_length=70000)
    developer_mode: bool | None = None
    chat_appearance: dict[str, Any] | None = None
    notification_prefs: dict[str, bool] | None = None
    friend_requests: Literal["everyone", "shared_servers", "nobody"] | None = None
    direct_messages: Literal["everyone", "shared_servers", "friends"] | None = None
    class_visibility: Literal["hidden", "friends", "shared_servers", "everyone"] | None = None
    online_status: Literal["nobody", "friends", "shared_servers"] | None = None
    profile_visibility: Literal["everyone", "shared_context", "friends"] | None = None
    activity_visibility: Literal["nobody", "friends"] | None = None
    voice_calls: Literal["friends", "nobody"] | None = None


class ClassBody(BaseModel):
    class_id: str | None = None
    visibility: Literal["hidden", "friends", "shared_servers", "everyone"] = "hidden"


class ThemeBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    tokens: dict[str, str]


class ReauthBody(BaseModel):
    current_secret: str = Field(min_length=1, max_length=256)


def clean_bio(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").strip()
    if any(unicodedata.category(ch).startswith("C") and ch != "\n" for ch in text):
        raise AppError("bio_invalid", 422)
    if len(text) > 300:
        raise AppError("bio_invalid", 422)
    return text


def validate_theme_tokens(tokens: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in tokens.items():
        if key not in THEME_KEYS:
            raise AppError("theme_invalid", 422)
        if key in THEME_COLOR_KEYS and not HEX_COLOR.match(value):
            raise AppError("theme_invalid", 422)
        if key == "background" and not (HEX_COLOR.match(value) or GRADIENT.match(value)):
            raise AppError("theme_invalid", 422)
        if key == "radius" and not (value.isdigit() and 0 <= int(value) <= 24):
            raise AppError("theme_invalid", 422)
        cleaned[key] = value
    return cleaned


def validate_chat_appearance(value: dict[str, Any]) -> dict[str, Any]:
    density = value.get("density", "cozy")
    scale = value.get("font_scale", 100)
    if density not in ("compact", "cozy") or not isinstance(scale, int) or isinstance(scale, bool) or not 80 <= scale <= 140:
        raise AppError("settings_invalid", 422)
    return {"density": density, "font_scale": scale, "show_timestamps": bool(value.get("show_timestamps", True))}


@router.get("")
async def get_me(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    return await load_self_payload(db, auth.user)


@router.patch("")
async def update_profile(body: ProfileBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    from ...models import Profile

    profile = await db.get(Profile, auth.user.id)
    if body.display_name is not None:
        auth.user.display_name = normalize_display_name(body.display_name)
    if body.bio is not None:
        profile.bio = clean_bio(body.bio)
    if body.clear_accent:
        profile.accent_color = None
    elif body.accent_color is not None:
        if not HEX_COLOR.match(body.accent_color):
            raise AppError("settings_invalid", 422)
        profile.accent_color = body.accent_color.lower()
    await db.commit()
    return await load_self_payload(db, auth.user)


@router.patch("/settings")
async def update_settings(body: SettingsBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    row = await get_settings_row(db, auth.user.id)
    fields = body.model_dump(exclude_unset=True)
    for simple in ("language", "theme_mode", "developer_mode", "friend_requests", "direct_messages", "online_status", "profile_visibility", "activity_visibility", "voice_calls"):
        if simple in fields and fields[simple] is not None:
            setattr(row, simple, fields[simple])
    if fields.get("class_visibility") is not None:
        if fields["class_visibility"] != ClassVisibility.HIDDEN.value and auth.user.school_class_id is None:
            raise AppError("class_required", 422)
        row.class_visibility = fields["class_visibility"]
    if body.custom_css is not None:
        try:
            row.custom_css = sanitize_css(body.custom_css) if body.custom_css.strip() else ""
        except CssRejected as exc:
            raise AppError("css_rejected", 422, params={"reason": exc.code, "detail": exc.detail}) from exc
    if body.chat_appearance is not None:
        row.chat_appearance = validate_chat_appearance(body.chat_appearance)
    if body.notification_prefs is not None:
        if any(key not in NOTIFICATION_KEYS for key in body.notification_prefs):
            raise AppError("settings_invalid", 422)
        row.notification_prefs = {**row.notification_prefs, **body.notification_prefs}
    if body.clear_active_theme:
        row.active_theme_id = None
    elif body.active_theme_id is not None:
        theme = await db.get(Theme, int(body.active_theme_id)) if body.active_theme_id.isdigit() else None
        if theme is None or theme.user_id != auth.user.id:
            raise AppError("not_found", 404)
        row.active_theme_id = theme.id
    await db.commit()
    return await load_self_payload(db, auth.user)


@router.get("/classes")
async def list_classes(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(SchoolClass).where(SchoolClass.is_active.is_(True)).order_by(SchoolClass.sort_order))).scalars()
    return [{"id": sid(c.id), "code": c.code, "grade": c.grade, "section": c.section} for c in rows]


@router.put("/class")
async def set_class(body: ClassBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    row = await get_settings_row(db, auth.user.id)
    if body.visibility != ClassVisibility.HIDDEN.value or body.class_id is not None:
        if body.class_id is None or not body.class_id.isdigit():
            raise AppError("class_required", 422)
        school_class = await db.get(SchoolClass, int(body.class_id))
        if school_class is None or not school_class.is_active:
            raise AppError("not_found", 404)
        auth.user.school_class_id = school_class.id
    else:
        auth.user.school_class_id = None
    row.class_visibility = body.visibility
    row.class_prompt_answered = True
    await db.commit()
    return await load_self_payload(db, auth.user)


@router.get("/themes")
async def list_themes(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(Theme).where(Theme.user_id == auth.user.id).order_by(Theme.id))).scalars()
    return [{"id": sid(t.id), "name": t.name, "tokens": t.tokens} for t in rows]


@router.post("/themes")
async def create_theme(body: ThemeBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    count = (await db.execute(select(func.count()).select_from(Theme).where(Theme.user_id == auth.user.id))).scalar_one()
    if count >= MAX_THEMES:
        raise AppError("theme_limit_reached", 409)
    theme = Theme(user_id=auth.user.id, name=body.name.strip(), tokens=validate_theme_tokens(body.tokens))
    db.add(theme)
    await db.commit()
    return {"id": sid(theme.id), "name": theme.name, "tokens": theme.tokens}


@router.put("/themes/{theme_id}")
async def update_theme(theme_id: int, body: ThemeBody, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    theme = await db.get(Theme, theme_id)
    if theme is None or theme.user_id != auth.user.id:
        raise AppError("not_found", 404)
    theme.name = body.name.strip()
    theme.tokens = validate_theme_tokens(body.tokens)
    await db.commit()
    return {"id": sid(theme.id), "name": theme.name, "tokens": theme.tokens}


@router.delete("/themes/{theme_id}")
async def delete_theme(theme_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    theme = await db.get(Theme, theme_id)
    if theme is None or theme.user_id != auth.user.id:
        raise AppError("not_found", 404)
    row = await get_settings_row(db, auth.user.id)
    if row.active_theme_id == theme.id:
        row.active_theme_id = None
    await db.delete(theme)
    await db.commit()
    return {"status": "deleted"}


@router.get("/sessions")
async def list_sessions(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(
            select(AuthSession)
            .where(AuthSession.user_id == auth.user.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow(), AuthSession.scope == SessionScope.FULL.value)
            .order_by(AuthSession.last_seen_at.desc())
        )
    ).scalars()
    return [
        {
            "id": sid(s.id),
            "current": s.id == auth.session.id,
            "created_at": iso(s.created_at),
            "last_seen_at": iso(s.last_seen_at),
            "ip_hint": s.ip_hint,
            "user_agent": s.user_agent,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}")
async def revoke_other_session(
    session_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    record = await db.get(AuthSession, session_id)
    if record is None or record.user_id != auth.user.id:
        raise AppError("not_found", 404)
    await revoke_session(db, record.id)
    await db.commit()
    await request.app.state.hub.close_user_session(auth.user.id, record.id)
    return {"status": "revoked"}


async def reauthenticate(request: Request, db: AsyncSession, auth: Auth, secret: str) -> None:
    enforce(request, "reauth", 10, 600, subject=str(auth.user.id))
    method = await db.get(AuthMethod, auth.user.id)
    if method is None:
        raise AppError("invalid_credentials", 401)
    ensure_not_locked(method)
    if not await verify_secret(request, db, auth.user, method, secret):
        await apply_lockout(db, method, get_settings(request))
        await db.commit()
        raise AppError("invalid_credentials", 401)
    method.failed_attempts = 0
    method.locked_until = None


@router.post("/security/begin")
async def begin_security_change(
    body: ReauthBody, request: Request, response: Response, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict:
    await reauthenticate(request, db, auth, body.current_secret)
    from ...security import audit_helpers
    from ...security.sessions import revoke_user_sessions

    await revoke_user_sessions(db, auth.user.id)
    await issue_session(db, request, response, auth.user.id, SessionScope.SETUP)
    audit_helpers.record_recovery(db, auth.user.id, "reauth_change")
    await db.commit()
    return {"username": auth.user.username, "display_name": auth.user.display_name, "next": "security"}


@router.get("/recovery-codes")
async def recovery_status(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    remaining = (
        await db.execute(select(func.count()).select_from(RecoveryCode).where(RecoveryCode.user_id == auth.user.id, RecoveryCode.used_at.is_(None)))
    ).scalar_one()
    return {"remaining": remaining}


@router.post("/recovery-codes")
async def regenerate_recovery_codes(
    body: ReauthBody, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict[str, list[str]]:
    await reauthenticate(request, db, auth, body.current_secret)
    codes = await accounts.issue_recovery_codes(db, request.app.state.vault, auth.user.id)
    await db.commit()
    return {"recovery_codes": codes}
