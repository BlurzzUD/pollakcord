from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column
from ..db.types import UTCDateTime

DEFAULT_MODERATION_SETTINGS: dict[str, Any] = {
    "reports_enabled": True,
    "max_mentions_per_message": 10,
    "invites_enabled": True,
}


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = id_column()
    name: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(500), default="")
    icon_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    moderation_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: dict(DEFAULT_MODERATION_SETTINGS))
    created_at: Mapped[datetime] = created_column()


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = id_column()
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    permissions: Mapped[int] = mapped_column(BigInteger, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(16), default="custom")
    created_at: Mapped[datetime] = created_column()


class ServerMember(Base):
    __tablename__ = "server_members"

    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(40), nullable=True)
    joined_at: Mapped[datetime] = created_column()
    timeout_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class MemberRole(Base):
    __tablename__ = "member_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["server_id", "user_id"],
            ["server_members.server_id", "server_members.user_id"],
            ondelete="CASCADE",
        ),
    )

    server_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, index=True)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = id_column()
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer, default=0)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = id_column()
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(60))
    topic: Mapped[str] = mapped_column(String(300), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    user_limit: Mapped[int] = mapped_column(Integer, default=0)
    slowmode_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_column()


class PermissionOverwrite(Base):
    __tablename__ = "permission_overwrites"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_id", "target_type", "target_id"),
        Index("ix_overwrites_scope", "scope_type", "scope_id"),
    )

    id: Mapped[int] = id_column()
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(10))
    scope_id: Mapped[int] = mapped_column(BigInteger)
    target_type: Mapped[str] = mapped_column(String(8))
    target_id: Mapped[int] = mapped_column(BigInteger)
    allow: Mapped[int] = mapped_column(BigInteger, default=0)
    deny: Mapped[int] = mapped_column(BigInteger, default=0)


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = id_column()
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = created_column()


class Ban(Base):
    __tablename__ = "bans"

    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    banned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = created_column()
