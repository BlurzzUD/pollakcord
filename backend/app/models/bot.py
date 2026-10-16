from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column
from ..db.types import UTCDateTime


class BotApplication(Base):
    __tablename__ = "bot_applications"

    bot_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = created_column()
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BotInstall(Base):
    __tablename__ = "bot_installs"
    __table_args__ = (
        ForeignKeyConstraint(["server_id", "bot_user_id"], ["server_members.server_id", "server_members.user_id"], ondelete="CASCADE"),
    )

    server_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bot_user_id: Mapped[int] = mapped_column(ForeignKey("bot_applications.bot_user_id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    permissions: Mapped[int] = mapped_column(BigInteger)
    installed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = created_column()


class BotCommand(Base):
    __tablename__ = "bot_commands"
    __table_args__ = (UniqueConstraint("bot_user_id", "name"),)

    id: Mapped[int] = id_column()
    bot_user_id: Mapped[int] = mapped_column(ForeignKey("bot_applications.bot_user_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(100))
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    default_member_permissions: Mapped[int] = mapped_column(BigInteger, default=0)


class BotInteraction(Base):
    __tablename__ = "bot_interactions"

    id: Mapped[int] = id_column()
    bot_user_id: Mapped[int] = mapped_column(ForeignKey("bot_applications.bot_user_id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    command_id: Mapped[int | None] = mapped_column(ForeignKey("bot_commands.id", ondelete="SET NULL"), nullable=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    response_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = created_column()
