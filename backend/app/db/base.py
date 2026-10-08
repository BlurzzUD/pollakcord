from datetime import datetime

from sqlalchemy import BigInteger, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..ids import new_id
from .types import UTCDateTime, utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def id_column() -> Mapped[int]:
    return mapped_column(BigInteger, primary_key=True, autoincrement=False, default=new_id)


def created_column() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, default=utcnow, nullable=False)
