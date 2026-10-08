from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.types import utcnow
from ..models import RecoveryCode
from ..models.enums import AuditAction
from ..services import audit


def record_recovery(db: AsyncSession, user_id: int, method: str) -> None:
    audit.record(db, AuditAction.ACCOUNT_RECOVERY, actor_id=user_id, target_type="user", target_id=user_id, details={"method": method})


async def consume_recovery_code(db: AsyncSession, user_id: int, code_hash: str) -> RecoveryCode | None:
    row = (
        await db.execute(
            select(RecoveryCode).where(RecoveryCode.user_id == user_id, RecoveryCode.code_hash == code_hash, RecoveryCode.used_at.is_(None))
        )
    ).scalar_one_or_none()
    if row is not None:
        row.used_at = utcnow()
    return row
