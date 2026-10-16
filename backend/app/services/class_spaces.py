from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..crypto.envelope import DecryptionError, Vault
from ..db.types import utcnow
from ..errors import AppError
from ..ids import new_id
from ..logging_config import get_logger
from ..models import ClassSpaceMember, ClassSpaceMessage, Profile, ReadState, SchoolClass, User
from ..models.enums import AccountStatus
from .messages import clean_content
from .serializers import iso, sid, user_card
from .link_embeds import EmbedService
from .message_media import open_media, seal_media

logger = get_logger("pollakcord.class_space")
PURPOSE = "class-space-message"
ALIAS_PURPOSE = "class-space-alias"
READ_SCOPE = "cspace"
ALIAS_LENGTH = 6
MAX_PAGE = 100
MAX_ID = 2**63 - 1
SNAPSHOT_BEFORE = 5
SNAPSHOT_AFTER = 2


async def active_class(db: AsyncSession, user: User) -> SchoolClass | None:
    if user.is_bot or user.school_class_id is None:
        return None
    school_class = await db.get(SchoolClass, user.school_class_id)
    return school_class if school_class is not None and school_class.is_active else None


def class_summary(school_class: SchoolClass) -> dict[str, Any]:
    return {"id": sid(school_class.id), "code": school_class.code}


class ClassSpaceService:
    def __init__(self, vault: Vault, settings: Settings, embeds: EmbedService | None = None) -> None:
        self._vault = vault
        self._max_length = settings.message_max_length
        self._embeds = embeds or EmbedService(settings)

    @staticmethod
    def _aad(message_id: int, school_class_id: int) -> bytes:
        return f"cspace|{message_id}|{school_class_id}".encode()

    def _open(self, message: ClassSpaceMessage) -> str | None:
        try:
            return self._vault.decrypt(PURPOSE, message.body_enc, self._aad(message.id, message.school_class_id), message.key_id).decode("utf-8")
        except DecryptionError:
            logger.error("class_space_decrypt_failed", extra={"message_id": message.id})
            return None

    def alias(self, school_class_id: int, user_id: int) -> str:
        return self._vault.mac_hex(ALIAS_PURPOSE, f"{school_class_id}|{user_id}".encode())[:ALIAS_LENGTH]

    @staticmethod
    def _valid_members(school_class_id: int):
        return (
            select(ClassSpaceMember, User, Profile)
            .join(User, User.id == ClassSpaceMember.user_id)
            .outerjoin(Profile, Profile.user_id == User.id)
            .where(
                ClassSpaceMember.school_class_id == school_class_id,
                User.school_class_id == school_class_id,
                User.status == AccountStatus.ACTIVE.value,
            )
        )

    @staticmethod
    async def member_ids(db: AsyncSession, school_class_id: int) -> list[int]:
        statement = (
            select(ClassSpaceMember.user_id)
            .join(User, User.id == ClassSpaceMember.user_id)
            .where(
                ClassSpaceMember.school_class_id == school_class_id,
                User.school_class_id == school_class_id,
                User.status == AccountStatus.ACTIVE.value,
            )
        )
        return list((await db.execute(statement)).scalars())

    @staticmethod
    async def member_count(db: AsyncSession, school_class_id: int) -> int:
        statement = (
            select(func.count())
            .select_from(ClassSpaceMember)
            .join(User, User.id == ClassSpaceMember.user_id)
            .where(
                ClassSpaceMember.school_class_id == school_class_id,
                User.school_class_id == school_class_id,
                User.status == AccountStatus.ACTIVE.value,
            )
        )
        return (await db.execute(statement)).scalar_one()

    @staticmethod
    async def require_member(db: AsyncSession, viewer: User, class_id: int) -> tuple[SchoolClass, ClassSpaceMember]:
        school_class = await db.get(SchoolClass, class_id) if 0 < class_id <= MAX_ID else None
        row = await db.get(ClassSpaceMember, viewer.id)
        if (
            school_class is None
            or not school_class.is_active
            or viewer.school_class_id != school_class.id
            or row is None
            or row.school_class_id != school_class.id
        ):
            raise AppError("not_found", 404)
        return school_class, row

    @staticmethod
    async def unread_count(db: AsyncSession, viewer: User, school_class_id: int) -> int:
        state = await db.get(ReadState, (viewer.id, READ_SCOPE, school_class_id))
        floor = state.last_read_message_id if state else 0
        statement = (
            select(func.count())
            .select_from(ClassSpaceMessage)
            .where(
                ClassSpaceMessage.school_class_id == school_class_id,
                ClassSpaceMessage.id > floor,
                or_(ClassSpaceMessage.author_id.is_(None), ClassSpaceMessage.author_id != viewer.id),
            )
        )
        return (await db.execute(statement)).scalar_one()

    async def state(self, db: AsyncSession, user: User) -> dict[str, Any]:
        school_class = await active_class(db, user)
        row = await db.get(ClassSpaceMember, user.id)
        if school_class is None or row is None or row.school_class_id != school_class.id:
            return {
                "class": class_summary(school_class) if school_class else None,
                "member": False,
                "prompt_required": school_class is not None,
                "show_username": None,
                "alias": None,
                "members": None,
                "unread": 0,
            }
        total = await self.member_count(db, school_class.id)
        return {
            "class": class_summary(school_class),
            "member": True,
            "prompt_required": False,
            "show_username": row.show_username,
            "alias": self.alias(school_class.id, user.id),
            "members": total,
            "unread": await self.unread_count(db, user, school_class.id),
        }

    async def answer(self, db: AsyncSession, user: User, show_username: bool) -> ClassSpaceMember:
        school_class = await active_class(db, user)
        if school_class is None:
            raise AppError("class_required", 422)
        row = await db.get(ClassSpaceMember, user.id)
        fresh = row is None or row.school_class_id != school_class.id
        if row is None:
            row = ClassSpaceMember(user_id=user.id, school_class_id=school_class.id, show_username=show_username)
            db.add(row)
        else:
            if fresh:
                row.school_class_id = school_class.id
                row.answered_at = utcnow()
            row.show_username = show_username
        try:
            await db.flush()
        except IntegrityError as exc:
            raise AppError("conflict", 409) from exc
        if fresh:
            newest = (await db.execute(select(func.max(ClassSpaceMessage.id)).where(ClassSpaceMessage.school_class_id == school_class.id))).scalar_one()
            if newest is not None:
                await self.mark_read(db, user, school_class.id, newest)
        return row

    @staticmethod
    async def leave_stale(db: AsyncSession, user: User) -> bool:
        row = await db.get(ClassSpaceMember, user.id)
        if row is None or row.school_class_id == user.school_class_id:
            return False
        await db.delete(row)
        return True

    async def members(self, db: AsyncSession, school_class: SchoolClass, viewer: User) -> dict[str, Any]:
        rows = (await db.execute(self._valid_members(school_class.id))).all()
        entries = []
        hidden = 0
        for member, user, profile in rows:
            if member.user_id == viewer.id:
                entries.append({"user": user_card(user, profile), "mine": True, "show_username": member.show_username})
            elif member.show_username:
                entries.append({"user": user_card(user, profile), "mine": False, "show_username": True})
            else:
                hidden += 1
        entries.sort(key=lambda entry: (not entry["mine"], entry["user"]["display_name"].casefold()))
        return {"class": class_summary(school_class), "members": entries, "hidden_count": hidden, "total": len(rows)}

    @staticmethod
    async def _flags(db: AsyncSession, school_class_id: int, user_ids: set[int]) -> dict[int, bool]:
        if not user_ids:
            return {}
        statement = (
            select(ClassSpaceMember.user_id, ClassSpaceMember.show_username)
            .join(User, User.id == ClassSpaceMember.user_id)
            .where(
                ClassSpaceMember.user_id.in_(user_ids),
                ClassSpaceMember.school_class_id == school_class_id,
                User.school_class_id == school_class_id,
            )
        )
        return {user_id: flag for user_id, flag in (await db.execute(statement)).all()}

    async def send(self, db: AsyncSession, school_class: SchoolClass, member: ClassSpaceMember, author: User, content: str) -> ClassSpaceMessage:
        text = clean_content(content, self._max_length)
        embeds = await self._embeds.build(text)
        message_id = new_id()
        body_enc, key_id = self._vault.encrypt(PURPOSE, text.encode("utf-8"), self._aad(message_id, school_class.id))
        message = ClassSpaceMessage(
            id=message_id,
            school_class_id=school_class.id,
            author_id=author.id,
            author_visible=member.show_username,
            body_enc=body_enc,
            key_id=key_id,
        )
        db.add(message)
        message.media_enc, message.media_key_id = seal_media(self._vault, f"class-space|{school_class.id}", message_id, embeds)
        await db.flush()
        return message

    @staticmethod
    async def history(db: AsyncSession, school_class_id: int, *, before: int | None, after: int | None, limit: int) -> list[ClassSpaceMessage]:
        limit = max(1, min(limit, MAX_PAGE))
        statement = select(ClassSpaceMessage).where(ClassSpaceMessage.school_class_id == school_class_id)
        if before is not None:
            statement = statement.where(ClassSpaceMessage.id < before)
        if after is not None:
            rows = (await db.execute(statement.where(ClassSpaceMessage.id > after).order_by(ClassSpaceMessage.id.asc()).limit(limit))).scalars().all()
            return list(rows)
        rows = (await db.execute(statement.order_by(ClassSpaceMessage.id.desc()).limit(limit))).scalars().all()
        return list(reversed(rows))

    async def payloads(self, db: AsyncSession, school_class: SchoolClass, messages: list[ClassSpaceMessage], viewer: User) -> list[dict[str, Any]]:
        if not messages:
            return []
        author_ids = {m.author_id for m in messages if m.author_id is not None}
        flags = await self._flags(db, school_class.id, author_ids)
        candidates = {user_id for user_id in author_ids if user_id == viewer.id or flags.get(user_id) is True}
        cards: dict[int, dict[str, Any]] = {}
        if candidates:
            rows = (await db.execute(select(User, Profile).outerjoin(Profile, Profile.user_id == User.id).where(User.id.in_(candidates)))).all()
            cards = {user.id: user_card(user, profile) for user, profile in rows}
        result = []
        for message in messages:
            author_id = message.author_id
            mine = author_id is not None and author_id == viewer.id
            visible = author_id is not None and (mine or (message.author_visible and flags.get(author_id) is True))
            anonymous_alias = author_id is not None and not mine and not message.author_visible
            result.append(
                {
                    "id": sid(message.id),
                    "class_id": sid(message.school_class_id),
                    "author": cards.get(author_id) if visible and author_id is not None else None,
                    "alias": self.alias(school_class.id, author_id) if anonymous_alias and author_id is not None else None,
                    "mine": mine,
                    "content": self._open(message) or "",
                    "embeds": open_media(self._vault, f"class-space|{school_class.id}", message.id, message.media_enc, message.media_key_id)["embeds"],
                    "created_at": iso(message.created_at),
                }
            )
        return result

    @staticmethod
    async def require_message(db: AsyncSession, school_class_id: int, message_id: int) -> ClassSpaceMessage:
        message = await db.get(ClassSpaceMessage, message_id) if 0 < message_id <= MAX_ID else None
        if message is None or message.school_class_id != school_class_id:
            raise AppError("not_found", 404)
        return message

    @staticmethod
    async def read_state(db: AsyncSession, viewer: User, school_class_id: int) -> ReadState | None:
        return await db.get(ReadState, (viewer.id, READ_SCOPE, school_class_id))

    @staticmethod
    async def mark_read(db: AsyncSession, viewer: User, school_class_id: int, message_id: int) -> None:
        state = await db.get(ReadState, (viewer.id, READ_SCOPE, school_class_id))
        if state is None:
            db.add(ReadState(user_id=viewer.id, scope_type=READ_SCOPE, scope_id=school_class_id, last_read_message_id=message_id))
        elif message_id > state.last_read_message_id:
            state.last_read_message_id = message_id
            state.updated_at = utcnow()

    async def snapshot(self, db: AsyncSession, target: ClassSpaceMessage) -> list[dict[str, Any]]:
        scope = ClassSpaceMessage.school_class_id == target.school_class_id
        earlier = (await db.execute(select(ClassSpaceMessage).where(scope, ClassSpaceMessage.id < target.id).order_by(ClassSpaceMessage.id.desc()).limit(SNAPSHOT_BEFORE))).scalars()
        later = (await db.execute(select(ClassSpaceMessage).where(scope, ClassSpaceMessage.id > target.id).order_by(ClassSpaceMessage.id.asc()).limit(SNAPSHOT_AFTER))).scalars()
        ordered = [*reversed(list(earlier)), target, *later]
        return [
            {
                "id": sid(m.id),
                "author_id": sid(m.author_id),
                "created_at": iso(m.created_at),
                "content": self._open(m),
                "deleted": False,
                "reported": m.id == target.id,
            }
            for m in ordered
        ]
