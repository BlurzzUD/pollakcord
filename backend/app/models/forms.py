from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, created_column, id_column
from ..db.types import UTCDateTime
from .enums import FormStatus


class Form(Base):
    __tablename__ = "forms"

    id: Mapped[int] = id_column()
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    creator_role: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1000), default="")
    target_scope: Mapped[str] = mapped_column(String(8))
    school_class_id: Mapped[int | None] = mapped_column(ForeignKey("school_classes.id", ondelete="RESTRICT"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(8), default=FormStatus.OPEN.value)
    created_at: Mapped[datetime] = created_column()
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class FormQuestion(Base):
    __tablename__ = "form_questions"
    __table_args__ = (Index("ix_form_questions_form_id_position", "form_id", "position"),)

    id: Mapped[int] = id_column()
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(200))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class FormResponse(Base):
    __tablename__ = "form_responses"
    __table_args__ = (
        UniqueConstraint("form_id", "user_id"),
        Index("ix_form_responses_form_id_id", "form_id", "id"),
    )

    id: Mapped[int] = id_column()
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    submitted_at: Mapped[datetime] = created_column()


class FormAnswer(Base):
    __tablename__ = "form_answers"

    response_id: Mapped[int] = mapped_column(ForeignKey("form_responses.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("form_questions.id", ondelete="CASCADE"), primary_key=True, index=True)
    value_enc: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(16))
