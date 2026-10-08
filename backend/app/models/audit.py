from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column
from ..db.types import UTCDateTime


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_server_id_id", "server_id", "id"),)

    id: Mapped[int] = id_column()
    server_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    target_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_column()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    id: Mapped[int] = id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = created_column()
