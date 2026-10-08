from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SchoolClass

DEFAULT_CLASSES = [(grade, section) for grade in (9, 10, 11, 12, 13, 14) for section in ("A", "B")]


async def ensure_school_classes(db: AsyncSession) -> None:
    existing = set((await db.execute(select(SchoolClass.code))).scalars())
    for index, (grade, section) in enumerate(DEFAULT_CLASSES):
        code = f"{grade}{section}"
        if code not in existing:
            db.add(SchoolClass(code=code, grade=grade, section=section, sort_order=index))
    await db.commit()
