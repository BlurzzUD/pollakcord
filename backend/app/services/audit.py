from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog
from ..models.enums import AuditAction

FORBIDDEN_DETAIL_KEYS = ("password", "secret", "token", "content", "code", "real_name", "full_name", "key")


def clean_details(details: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if any(marker in key.lower() for marker in FORBIDDEN_DETAIL_KEYS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[key] = value[:200] if isinstance(value, str) else value
        elif isinstance(value, (list, tuple)):
            cleaned[key] = [v for v in value if isinstance(v, (str, int, float, bool))][:50]
    return cleaned


def record(
    db: AsyncSession,
    action: AuditAction,
    *,
    actor_id: int | None,
    server_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        action=action.value,
        actor_id=actor_id,
        server_id=server_id,
        target_type=target_type,
        target_id=target_id,
        details=clean_details(details),
    )
    db.add(entry)
    return entry
