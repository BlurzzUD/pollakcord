from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column
from ..db.types import UTCDateTime
from .enums import ReportStatus


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_low_id", "user_high_id"),
        CheckConstraint("user_low_id < user_high_id", name="ordered_pair"),
    )

    id: Mapped[int] = id_column()
    user_low_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_high_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = created_column()
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class DataKey(Base):
    __tablename__ = "data_keys"
    __table_args__ = (Index("ix_data_keys_scope", "scope_type", "scope_id", "active"),)

    id: Mapped[int] = id_column()
    scope_type: Mapped[str] = mapped_column(String(8))
    scope_id: Mapped[int] = mapped_column(BigInteger)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    kek_id: Mapped[str] = mapped_column(String(16))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_column()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "(channel_id IS NOT NULL AND conversation_id IS NULL) OR (channel_id IS NULL AND conversation_id IS NOT NULL)",
            name="single_scope",
        ),
        Index("ix_messages_channel_id_id", "channel_id", "id"),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
    )

    id: Mapped[int] = id_column()
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reply_to_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = created_column()
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    pinned_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    pinned_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class MessageContent(Base):
    __tablename__ = "message_contents"

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    data_key_id: Mapped[int] = mapped_column(ForeignKey("data_keys.id", ondelete="RESTRICT"), index=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    algorithm: Mapped[str] = mapped_column(String(16), default="aes-256-gcm")


class Reaction(Base):
    __tablename__ = "message_reactions"

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    emoji: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = created_column()


class ReadState(Base):
    __tablename__ = "read_states"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(8), primary_key=True)
    scope_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_read_message_id: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = created_column()


class Mention(Base):
    __tablename__ = "message_mentions"

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)


class SearchToken(Base):
    __tablename__ = "message_search_tokens"

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(16), primary_key=True, index=True)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = id_column()
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"), nullable=True, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(String(32))
    details: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default=ReportStatus.OPEN.value, index=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    snapshot_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = created_column()
    handled_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
