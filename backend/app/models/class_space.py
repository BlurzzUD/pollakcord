from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column


class ClassSpaceMember(Base):
    __tablename__ = "class_space_members"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    school_class_id: Mapped[int] = mapped_column(ForeignKey("school_classes.id", ondelete="CASCADE"), index=True)
    show_username: Mapped[bool] = mapped_column(Boolean, default=False)
    answered_at: Mapped[datetime] = created_column()


class ClassSpaceMessage(Base):
    __tablename__ = "class_space_messages"
    __table_args__ = (Index("ix_class_space_messages_school_class_id_id", "school_class_id", "id"),)

    id: Mapped[int] = id_column()
    school_class_id: Mapped[int] = mapped_column(ForeignKey("school_classes.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    author_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    body_enc: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = created_column()
