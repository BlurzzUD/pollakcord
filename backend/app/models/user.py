from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column
from ..db.types import UTCDateTime, utcnow
from .enums import (
    AccountStatus,
    ActivityVisibility,
    CallPolicy,
    ClassVisibility,
    DirectMessagePolicy,
    FriendRequestPolicy,
    PlatformRole,
    PresenceVisibility,
    ProfileVisibility,
    ThemeMode,
)

DEFAULT_CHAT_APPEARANCE: dict[str, Any] = {"density": "cozy", "font_scale": 100, "show_timestamps": True}
DEFAULT_NOTIFICATION_PREFS: dict[str, Any] = {
    "friend_requests": True,
    "direct_messages": True,
    "mentions": True,
    "server": True,
    "calls": True,
    "moderation": True,
    "sounds": True,
}


class SchoolClass(Base):
    __tablename__ = "school_classes"

    id: Mapped[int] = id_column()
    code: Mapped[str] = mapped_column(String(16), unique=True)
    grade: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(8))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = id_column()
    username: Mapped[str] = mapped_column(String(32))
    username_lower: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default=AccountStatus.PENDING_SECURITY.value, index=True)
    platform_role: Mapped[str] = mapped_column(String(24), default=PlatformRole.USER.value)
    school_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = created_column()
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class UserIdentity(Base):
    __tablename__ = "user_identities"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    identity_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    real_name_enc: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(16))
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    bio: Mapped[str] = mapped_column(String(300), default="")
    avatar_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    banner_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    language: Mapped[str] = mapped_column(String(5), default="hu")
    theme_mode: Mapped[str] = mapped_column(String(10), default=ThemeMode.SYSTEM.value)
    active_theme_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    custom_css: Mapped[str] = mapped_column(Text, default="")
    developer_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    chat_appearance: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: dict(DEFAULT_CHAT_APPEARANCE))
    notification_prefs: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: dict(DEFAULT_NOTIFICATION_PREFS))
    friend_requests: Mapped[str] = mapped_column(String(16), default=FriendRequestPolicy.EVERYONE.value)
    direct_messages: Mapped[str] = mapped_column(String(16), default=DirectMessagePolicy.SHARED_SERVERS.value)
    class_visibility: Mapped[str] = mapped_column(String(16), default=ClassVisibility.HIDDEN.value, index=True)
    online_status: Mapped[str] = mapped_column(String(16), default=PresenceVisibility.FRIENDS.value)
    profile_visibility: Mapped[str] = mapped_column(String(16), default=ProfileVisibility.SHARED_CONTEXT.value)
    activity_visibility: Mapped[str] = mapped_column(String(16), default=ActivityVisibility.FRIENDS.value)
    voice_calls: Mapped[str] = mapped_column(String(16), default=CallPolicy.FRIENDS.value)
    class_prompt_answered: Mapped[bool] = mapped_column(Boolean, default=False)


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[int] = id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    tokens: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_column()
