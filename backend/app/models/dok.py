from datetime import datetime

from sqlalchemy import ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column
from ..db.types import UTCDateTime


class DokThread(Base):
    __tablename__ = "dok_threads"

    id: Mapped[int] = id_column()
    scope: Mapped[str] = mapped_column(String(8))
    school_class_id: Mapped[int | None] = mapped_column(ForeignKey("school_classes.id", ondelete="RESTRICT"), nullable=True)
    target_key: Mapped[str] = mapped_column(String(32), unique=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = created_column()
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class DokMessage(Base):
    __tablename__ = "dok_messages"
    __table_args__ = (Index("ix_dok_messages_thread_id_id", "thread_id", "id"),)

    id: Mapped[int] = id_column()
    thread_id: Mapped[int] = mapped_column(ForeignKey("dok_threads.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    author_role: Mapped[str] = mapped_column(String(24))
    body_enc: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = created_column()
