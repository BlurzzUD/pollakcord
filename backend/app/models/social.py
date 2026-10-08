from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("user_low_id", "user_high_id"),
        CheckConstraint("user_low_id < user_high_id", name="ordered_pair"),
    )

    id: Mapped[int] = id_column()
    user_low_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_high_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = created_column()


class FriendRequest(Base):
    __tablename__ = "friend_requests"
    __table_args__ = (UniqueConstraint("sender_id", "recipient_id"),)

    id: Mapped[int] = id_column()
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = created_column()


class Block(Base):
    __tablename__ = "blocks"

    blocker_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    blocked_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at: Mapped[datetime] = created_column()
