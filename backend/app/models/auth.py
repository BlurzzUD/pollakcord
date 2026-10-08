from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column
from ..db.types import UTCDateTime, utcnow
from .enums import SessionScope


class AuthMethod(Base):
    __tablename__ = "auth_methods"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    method: Mapped[str] = mapped_column(String(10))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class TotpConfig(Base):
    __tablename__ = "totp_configs"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(16))
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_used_step: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = created_column()


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"

    id: Mapped[int] = id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = created_column()


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(12), default=SessionScope.FULL.value)
    created_at: Mapped[datetime] = created_column()
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ip_hint: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(200), default="")
