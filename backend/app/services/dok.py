from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..crypto.envelope import DecryptionError, Vault
from ..db.types import utcnow
from ..errors import AppError
from ..ids import new_id
from ..logging_config import get_logger
from ..models import DokMessage, DokThread, Notification, ReadState, SchoolClass, User, UserSettings
from ..models.enums import STAFF_ROLES, AccountStatus, DokScope, NotificationType, PlatformRole
from ..realtime.outbox import Outbox
from . import people
from .messages import clean_content
from .notifications import notify
from .serializers import iso, sid

logger = get_logger("pollakcord.dok")
PURPOSE = "dok-message"
READ_SCOPE = "dok"
SCHOOL_KEY = "school"
PREVIEW_LENGTH = 120
MAX_PAGE = 100
MAX_ID = 2**63 - 1
SETTINGS_CHUNK = 500
SENDER_ROLES = frozenset({PlatformRole.DOK_REPRESENTATIVE.value, PlatformRole.DOK_PRESIDENT.value})
READ_ALL_ROLES = STAFF_ROLES | {PlatformRole.DOK_PRESIDENT.value}


@dataclass(frozen=True)
class Target:
    scope: DokScope
    school_class_id: int | None = None

    @property
    def key(self) -> str:
        return SCHOOL_KEY if self.scope is DokScope.SCHOOL else f"class:{self.school_class_id}"


def can_send(user: User) -> bool:
    return user.platform_role in SENDER_ROLES


def authorize_target(user: User, target: Target) -> None:
    if user.platform_role == PlatformRole.DOK_PRESIDENT.value:
        return
    if user.platform_role != PlatformRole.DOK_REPRESENTATIVE.value:
        raise AppError("dok_send_forbidden", 403)
    if user.school_class_id is None:
        raise AppError("class_required", 422)
    if target.scope is DokScope.CLASS and target.school_class_id == user.school_class_id:
        return
    raise AppError("dok_target_forbidden", 403)


def is_recipient(user: User, thread: DokThread) -> bool:
    if user.school_class_id is None:
        return False
    return thread.scope == DokScope.SCHOOL.value or thread.school_class_id == user.school_class_id


def can_read(user: User, thread: DokThread) -> bool:
    return user.platform_role in READ_ALL_ROLES or is_recipient(user, thread)


def can_send_to(user: User, thread: DokThread) -> bool:
    if user.platform_role == PlatformRole.DOK_PRESIDENT.value:
        return True
    if user.platform_role == PlatformRole.DOK_REPRESENTATIVE.value:
        return thread.scope == DokScope.CLASS.value and thread.school_class_id == user.school_class_id
    return False


def class_target(school_class: SchoolClass) -> dict[str, Any]:
    return {"type": DokScope.CLASS.value, "class_id": sid(school_class.id), "code": school_class.code}


class DokService:
    def __init__(self, vault: Vault, settings: Settings) -> None:
        self._vault = vault
        self._max_length = settings.message_max_length

    @staticmethod
    def _aad(message_id: int, thread_id: int) -> bytes:
        return f"dok|{message_id}|{thread_id}".encode()

    def _open(self, message: DokMessage) -> str | None:
        try:
            return self._vault.decrypt(PURPOSE, message.body_enc, self._aad(message.id, message.thread_id), message.key_id).decode("utf-8")
        except DecryptionError:
            logger.error("dok_decrypt_failed", extra={"message_id": message.id})
            return None

    @staticmethod
    async def resolve_class(db: AsyncSession, class_id: int) -> SchoolClass:
        school_class = await db.get(SchoolClass, class_id) if 0 < class_id <= MAX_ID else None
        if school_class is None or not school_class.is_active:
            raise AppError("not_found", 404)
        return school_class

    @staticmethod
    async def require_thread(db: AsyncSession, thread_id: int, viewer: User) -> DokThread:
        thread = await db.get(DokThread, thread_id) if 0 < thread_id <= MAX_ID else None
        if thread is None or not can_read(viewer, thread):
            raise AppError("not_found", 404)
        return thread

    @staticmethod
    async def _find_thread(db: AsyncSession, target: Target) -> DokThread | None:
        return (await db.execute(select(DokThread).where(DokThread.target_key == target.key))).scalar_one_or_none()

    async def _thread_for(self, db: AsyncSession, target: Target, creator_id: int) -> DokThread:
        existing = await self._find_thread(db, target)
        if existing is not None:
            return existing
        thread = DokThread(scope=target.scope.value, school_class_id=target.school_class_id, target_key=target.key, created_by=creator_id)
        db.add(thread)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise AppError("conflict", 409) from exc
        return thread

    async def send(self, db: AsyncSession, target: Target, author: User, content: str) -> tuple[DokThread, DokMessage]:
        text = clean_content(content, self._max_length)
        thread = await self._thread_for(db, target, author.id)
        message_id = new_id()
        body_enc, key_id = self._vault.encrypt(PURPOSE, text.encode("utf-8"), self._aad(message_id, thread.id))
        message = DokMessage(id=message_id, thread_id=thread.id, author_id=author.id, author_role=author.platform_role, body_enc=body_enc, key_id=key_id)
        db.add(message)
        thread.last_message_at = utcnow()
        await db.flush()
        return thread, message

    @staticmethod
    async def recipient_ids(db: AsyncSession, thread: DokThread) -> list[int]:
        statement = select(User.id).where(User.status == AccountStatus.ACTIVE.value)
        if thread.scope == DokScope.CLASS.value:
            statement = statement.where(User.school_class_id == thread.school_class_id)
        else:
            statement = statement.where(User.school_class_id.is_not(None))
        return list((await db.execute(statement)).scalars())

    @staticmethod
    async def _prime_settings(db: AsyncSession, user_ids: list[int]) -> None:
        for start in range(0, len(user_ids), SETTINGS_CHUNK):
            await db.execute(select(UserSettings).where(UserSettings.user_id.in_(user_ids[start : start + SETTINGS_CHUNK])))

    async def announce(
        self,
        db: AsyncSession,
        outbox: Outbox,
        thread: DokThread,
        message: DokMessage,
        author: User,
        recipients: list[int],
        class_code: str | None,
    ) -> None:
        payload = {
            "thread_id": sid(thread.id),
            "dok_message_id": sid(message.id),
            "scope": thread.scope,
            "class_code": class_code,
            "author_role": message.author_role,
        }
        audience = [user_id for user_id in recipients if user_id != author.id]
        await self._prime_settings(db, audience)
        for user_id in audience:
            await notify(db, outbox, user_id, NotificationType.DOK_MESSAGE, payload)
        outbox.users({*recipients, author.id}, "dok.message", {"thread_id": sid(thread.id), "message_id": sid(message.id)})

    @staticmethod
    async def history(db: AsyncSession, thread_id: int, *, before: int | None, after: int | None, limit: int) -> list[DokMessage]:
        limit = max(1, min(limit, MAX_PAGE))
        statement = select(DokMessage).where(DokMessage.thread_id == thread_id)
        if before is not None:
            statement = statement.where(DokMessage.id < before)
        if after is not None:
            rows = (await db.execute(statement.where(DokMessage.id > after).order_by(DokMessage.id.asc()).limit(limit))).scalars().all()
            return list(rows)
        rows = (await db.execute(statement.order_by(DokMessage.id.desc()).limit(limit))).scalars().all()
        return list(reversed(rows))

    async def payloads(self, db: AsyncSession, thread: DokThread, messages: list[DokMessage], viewer: User) -> list[dict[str, Any]]:
        if not messages:
            return []
        visible = {m.author_id for m in messages if m.author_id is not None and (viewer.platform_role in STAFF_ROLES or m.author_id == viewer.id)}
        cards = await people.load_cards(db, visible)
        result = []
        for message in messages:
            result.append(
                {
                    "id": sid(message.id),
                    "thread_id": sid(message.thread_id),
                    "scope": thread.scope,
                    "author_role": message.author_role,
                    "author": cards.get(message.author_id) if message.author_id in visible else None,
                    "mine": message.author_id == viewer.id,
                    "content": self._open(message) or "",
                    "created_at": iso(message.created_at),
                }
            )
        return result

    @staticmethod
    async def read_state(db: AsyncSession, viewer: User, thread: DokThread) -> ReadState | None:
        if not is_recipient(viewer, thread):
            return None
        return await db.get(ReadState, (viewer.id, READ_SCOPE, thread.id))

    async def mark_read(self, db: AsyncSession, viewer: User, thread: DokThread, message_id: int) -> None:
        if is_recipient(viewer, thread):
            state = await db.get(ReadState, (viewer.id, READ_SCOPE, thread.id))
            if state is None:
                db.add(ReadState(user_id=viewer.id, scope_type=READ_SCOPE, scope_id=thread.id, last_read_message_id=message_id))
            elif message_id > state.last_read_message_id:
                state.last_read_message_id = message_id
                state.updated_at = utcnow()
        unread = (
            await db.execute(
                select(Notification).where(Notification.user_id == viewer.id, Notification.type == NotificationType.DOK_MESSAGE.value, Notification.read_at.is_(None))
            )
        ).scalars()
        now = utcnow()
        for row in unread:
            referenced = str(row.payload.get("dok_message_id", ""))
            if row.payload.get("thread_id") == sid(thread.id) and referenced.isdigit() and int(referenced) <= message_id:
                row.read_at = now

    @staticmethod
    async def _unread_counts(db: AsyncSession, viewer: User, threads: list[DokThread]) -> dict[int, int]:
        ids = [t.id for t in threads if is_recipient(viewer, t)]
        if not ids:
            return {}
        statement = (
            select(DokMessage.thread_id, func.count())
            .select_from(DokMessage)
            .outerjoin(
                ReadState,
                and_(ReadState.user_id == viewer.id, ReadState.scope_type == READ_SCOPE, ReadState.scope_id == DokMessage.thread_id),
            )
            .where(
                DokMessage.thread_id.in_(ids),
                DokMessage.id > func.coalesce(ReadState.last_read_message_id, 0),
                or_(DokMessage.author_id.is_(None), DokMessage.author_id != viewer.id),
            )
            .group_by(DokMessage.thread_id)
        )
        return {thread_id: count for thread_id, count in (await db.execute(statement)).all()}

    @staticmethod
    async def _latest(db: AsyncSession, thread_ids: list[int]) -> dict[int, DokMessage]:
        if not thread_ids:
            return {}
        newest = select(func.max(DokMessage.id)).where(DokMessage.thread_id.in_(thread_ids)).group_by(DokMessage.thread_id)
        rows = (await db.execute(select(DokMessage).where(DokMessage.id.in_(newest)))).scalars()
        return {m.thread_id: m for m in rows}

    @staticmethod
    async def send_options(db: AsyncSession, viewer: User) -> dict[str, Any]:
        if not can_send(viewer):
            return {"allowed": False, "targets": []}
        if viewer.platform_role == PlatformRole.DOK_PRESIDENT.value:
            classes = (await db.execute(select(SchoolClass).where(SchoolClass.is_active.is_(True)).order_by(SchoolClass.sort_order))).scalars().all()
            targets = [{"type": DokScope.SCHOOL.value}, *(class_target(c) for c in classes)]
        else:
            own = await db.get(SchoolClass, viewer.school_class_id) if viewer.school_class_id is not None else None
            targets = [class_target(own)] if own is not None and own.is_active else []
        return {"allowed": bool(targets), "targets": targets}

    @staticmethod
    async def visible_threads(db: AsyncSession, viewer: User) -> list[DokThread]:
        statement = select(DokThread).order_by(DokThread.last_message_at.desc())
        if viewer.platform_role not in READ_ALL_ROLES:
            if viewer.school_class_id is None:
                return []
            statement = statement.where(or_(DokThread.scope == DokScope.SCHOOL.value, DokThread.school_class_id == viewer.school_class_id))
        return list((await db.execute(statement)).scalars())

    async def inbox(self, db: AsyncSession, viewer: User) -> dict[str, Any]:
        threads = await self.visible_threads(db, viewer)
        class_ids = {t.school_class_id for t in threads if t.school_class_id is not None}
        classes = {c.id: c for c in (await db.execute(select(SchoolClass).where(SchoolClass.id.in_(class_ids)))).scalars()} if class_ids else {}
        unread = await self._unread_counts(db, viewer, threads)
        latest = await self._latest(db, [t.id for t in threads])
        items = []
        for thread in threads:
            school_class = classes.get(thread.school_class_id) if thread.school_class_id is not None else None
            newest = latest.get(thread.id)
            items.append(
                {
                    "id": sid(thread.id),
                    "scope": thread.scope,
                    "class": {"id": sid(school_class.id), "code": school_class.code} if school_class else None,
                    "last_message": {"preview": (self._open(newest) or "")[:PREVIEW_LENGTH], "created_at": iso(newest.created_at)} if newest else None,
                    "last_message_at": iso(thread.last_message_at),
                    "unread": unread.get(thread.id, 0),
                    "can_send": can_send_to(viewer, thread),
                }
            )
        return {"threads": items, "unread": sum(unread.values()), "send": await self.send_options(db, viewer)}

    async def attach_previews(self, db: AsyncSession, viewer: User, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        wanted: dict[str, int] = {}
        for item in items:
            raw = item["payload"].get("dok_message_id")
            if item["type"] == NotificationType.DOK_MESSAGE.value and isinstance(raw, str) and raw.isdigit() and int(raw) <= MAX_ID:
                wanted[item["id"]] = int(raw)
        if not wanted:
            return items
        messages = {m.id: m for m in (await db.execute(select(DokMessage).where(DokMessage.id.in_(set(wanted.values()))))).scalars()}
        thread_ids = {m.thread_id for m in messages.values()}
        threads = {t.id: t for t in (await db.execute(select(DokThread).where(DokThread.id.in_(thread_ids)))).scalars()} if thread_ids else {}
        enriched = []
        for item in items:
            message = messages.get(wanted.get(item["id"], 0))
            thread = threads.get(message.thread_id) if message is not None else None
            if message is None or thread is None or not can_read(viewer, thread):
                enriched.append(item)
                continue
            text = self._open(message)
            enriched.append({**item, "payload": {**item["payload"], "preview": text[:PREVIEW_LENGTH] if text else None}})
        return enriched
