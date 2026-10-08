import json
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..crypto.blind_index import tokenize
from ..crypto.envelope import DecryptionError, Vault, seal, unseal
from ..db.types import utcnow
from ..errors import AppError
from ..ids import new_id
from ..logging_config import get_logger
from ..models import (
    DataKey,
    Mention,
    Message,
    MessageContent,
    Profile,
    Reaction,
    ReadState,
    SearchToken,
    ServerMember,
    User,
)
from ..models.enums import ScopeKind
from .serializers import iso, sid, user_card

logger = get_logger("pollakcord.messages")
ALLOWED_REACTIONS = ("👍", "❤️", "😂", "😮", "😢", "🎉", "🔥", "👀", "✅", "❌", "🙏", "💯")
MENTION_PATTERN = re.compile(r"<@(\d{1,20})>")
KEY_CACHE_SIZE = 512
PREVIEW_LENGTH = 120
MAX_PAGE = 100


def extract_mentions(content: str) -> set[int]:
    return {int(match) for match in MENTION_PATTERN.findall(content)}


def clean_content(content: str, limit: int) -> str:
    cleaned = content.replace("\x00", "").replace("\r\n", "\n").strip()
    if not cleaned:
        raise AppError("message_empty", 422)
    if len(cleaned) > limit:
        raise AppError("message_too_long", 422, params={"max": limit})
    return cleaned


def scope_columns(scope: ScopeKind, scope_id: int) -> dict[str, int]:
    return {"conversation_id": scope_id} if scope is ScopeKind.DM else {"channel_id": scope_id}


def scope_clause(scope: ScopeKind, scope_id: int):
    return Message.conversation_id == scope_id if scope is ScopeKind.DM else Message.channel_id == scope_id


@dataclass(frozen=True)
class MessageScope:
    kind: ScopeKind
    scope_id: int
    server_id: int | None = None


class MessageService:
    def __init__(self, vault: Vault, settings: Settings) -> None:
        self._vault = vault
        self._rotation = settings.data_key_rotation_messages
        self._max_length = settings.message_max_length
        self._cache: OrderedDict[int, bytes] = OrderedDict()

    def _remember(self, key_id: int, raw: bytes) -> None:
        self._cache[key_id] = raw
        self._cache.move_to_end(key_id)
        while len(self._cache) > KEY_CACHE_SIZE:
            self._cache.popitem(last=False)

    @staticmethod
    def _wrap_aad(scope_type: str, scope_id: int) -> bytes:
        return f"dek|{scope_type}|{scope_id}".encode()

    @staticmethod
    def _message_aad(message_id: int, scope_type: str, scope_id: int, author_id: int | None) -> bytes:
        return f"msg|{message_id}|{scope_type}|{scope_id}|{author_id}".encode()

    async def _active_key(self, db: AsyncSession, scope: MessageScope) -> tuple[int, bytes]:
        row = (
            await db.execute(
                select(DataKey)
                .where(DataKey.scope_type == scope.kind.value, DataKey.scope_id == scope.scope_id, DataKey.active.is_(True))
                .order_by(DataKey.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None and row.message_count < self._rotation:
            return row.id, await self._unwrap(row)
        if row is not None:
            row.active = False
        raw = os.urandom(32)
        wrapped, kek_id = self._vault.encrypt("dek-wrap", raw, self._wrap_aad(scope.kind.value, scope.scope_id))
        fresh = DataKey(id=new_id(), scope_type=scope.kind.value, scope_id=scope.scope_id, wrapped_key=wrapped, kek_id=kek_id)
        db.add(fresh)
        await db.flush()
        self._remember(fresh.id, raw)
        return fresh.id, raw

    async def _unwrap(self, row: DataKey) -> bytes:
        cached = self._cache.get(row.id)
        if cached is not None:
            self._cache.move_to_end(row.id)
            return cached
        raw = self._vault.decrypt("dek-wrap", row.wrapped_key, self._wrap_aad(row.scope_type, row.scope_id), row.kek_id)
        self._remember(row.id, raw)
        return raw

    async def _key_by_id(self, db: AsyncSession, key_id: int) -> bytes:
        cached = self._cache.get(key_id)
        if cached is not None:
            return cached
        row = await db.get(DataKey, key_id)
        if row is None:
            raise AppError("internal_error", 500)
        return await self._unwrap(row)

    def search_hashes(self, scope: MessageScope, tokens: list[str]) -> list[bytes]:
        return [self._vault.mac("search-index", f"{scope.kind.value}:{scope.scope_id}:{token}".encode())[:16] for token in tokens]

    async def send(
        self,
        db: AsyncSession,
        scope: MessageScope,
        author_id: int,
        content: str,
        *,
        reply_to_id: int | None,
        mentions: set[int],
    ) -> tuple[Message, str]:
        text = clean_content(content, self._max_length)
        if reply_to_id is not None:
            target = await db.get(Message, reply_to_id)
            same_scope = target is not None and (
                (scope.kind is ScopeKind.DM and target.conversation_id == scope.scope_id)
                or (scope.kind is ScopeKind.CHANNEL and target.channel_id == scope.scope_id)
            )
            if not same_scope or target.deleted_at is not None:
                raise AppError("reply_target_invalid", 422)
        key_id, raw_key = await self._active_key(db, scope)
        message = Message(id=new_id(), author_id=author_id, reply_to_id=reply_to_id, **scope_columns(scope.kind, scope.scope_id))
        db.add(message)
        await db.flush()
        sealed = seal(raw_key, text.encode("utf-8"), self._message_aad(message.id, scope.kind.value, scope.scope_id, author_id))
        db.add(MessageContent(message_id=message.id, data_key_id=key_id, ciphertext=sealed))
        await db.execute(update(DataKey).where(DataKey.id == key_id).values(message_count=DataKey.message_count + 1))
        for digest in self.search_hashes(scope, tokenize(text)):
            db.add(SearchToken(message_id=message.id, token_hash=digest))
        for user_id in mentions:
            db.add(Mention(message_id=message.id, user_id=user_id))
        await db.flush()
        return message, text

    async def decrypt(self, db: AsyncSession, message: Message, content: MessageContent) -> str:
        raw = await self._key_by_id(db, content.data_key_id)
        scope_type = ScopeKind.DM.value if message.conversation_id is not None else ScopeKind.CHANNEL.value
        scope_id = message.conversation_id if message.conversation_id is not None else message.channel_id
        plain = unseal(raw, content.ciphertext, self._message_aad(message.id, scope_type, scope_id, message.author_id))
        return plain.decode("utf-8")

    async def texts_for(self, db: AsyncSession, messages: list[Message]) -> dict[int, str]:
        ids = [m.id for m in messages if m.deleted_at is None]
        if not ids:
            return {}
        contents = {c.message_id: c for c in (await db.execute(select(MessageContent).where(MessageContent.message_id.in_(ids)))).scalars()}
        by_id = {m.id: m for m in messages}
        texts: dict[int, str] = {}
        for message_id, content in contents.items():
            try:
                texts[message_id] = await self.decrypt(db, by_id[message_id], content)
            except DecryptionError:
                logger.error("message_decrypt_failed", extra={"message_id": message_id})
        return texts

    async def history(
        self, db: AsyncSession, scope: MessageScope, *, before: int | None, after: int | None, limit: int
    ) -> list[Message]:
        limit = max(1, min(limit, MAX_PAGE))
        statement = select(Message).where(scope_clause(scope.kind, scope.scope_id))
        if before is not None:
            statement = statement.where(Message.id < before)
        if after is not None:
            rows = (await db.execute(statement.where(Message.id > after).order_by(Message.id.asc()).limit(limit))).scalars().all()
            return list(rows)
        rows = (await db.execute(statement.order_by(Message.id.desc()).limit(limit))).scalars().all()
        return list(reversed(rows))

    async def payloads(self, db: AsyncSession, messages: list[Message], viewer_id: int, scope: MessageScope) -> list[dict[str, Any]]:
        if not messages:
            return []
        texts = await self.texts_for(db, messages)
        authors = await self._authors(db, {m.author_id for m in messages if m.author_id}, scope.server_id)
        reply_ids = {m.reply_to_id for m in messages if m.reply_to_id}
        previews = await self._previews(db, reply_ids)
        reactions = await self._reactions(db, [m.id for m in messages], viewer_id)
        result = []
        for message in messages:
            deleted = message.deleted_at is not None
            result.append(
                {
                    "id": sid(message.id),
                    "scope": scope.kind.value,
                    "channel_id": sid(message.channel_id),
                    "conversation_id": sid(message.conversation_id),
                    "author": authors.get(message.author_id),
                    "content": None if deleted else texts.get(message.id, ""),
                    "deleted": deleted,
                    "created_at": iso(message.created_at),
                    "reply_to": previews.get(message.reply_to_id) if message.reply_to_id else None,
                    "pinned": message.pinned_at is not None,
                    "reactions": [] if deleted else reactions.get(message.id, []),
                }
            )
        return result

    async def _authors(self, db: AsyncSession, author_ids: set[int], server_id: int | None) -> dict[int, dict[str, Any]]:
        if not author_ids:
            return {}
        rows = (await db.execute(select(User, Profile).outerjoin(Profile, Profile.user_id == User.id).where(User.id.in_(author_ids)))).all()
        cards = {user.id: user_card(user, profile) for user, profile in rows}
        if server_id is not None:
            members = (
                await db.execute(select(ServerMember.user_id, ServerMember.nickname).where(ServerMember.server_id == server_id, ServerMember.user_id.in_(author_ids)))
            ).all()
            nicknames = {uid: nick for uid, nick in members}
            for uid, card in cards.items():
                card["nickname"] = nicknames.get(uid)
                card["is_member"] = uid in nicknames
        return cards

    async def _previews(self, db: AsyncSession, reply_ids: set[int]) -> dict[int, dict[str, Any]]:
        if not reply_ids:
            return {}
        targets = list((await db.execute(select(Message).where(Message.id.in_(reply_ids)))).scalars())
        texts = await self.texts_for(db, targets)
        previews: dict[int, dict[str, Any]] = {}
        for target in targets:
            deleted = target.deleted_at is not None
            previews[target.id] = {
                "id": sid(target.id),
                "author_id": sid(target.author_id),
                "deleted": deleted,
                "preview": None if deleted else texts.get(target.id, "")[:PREVIEW_LENGTH],
            }
        return previews

    async def _reactions(self, db: AsyncSession, message_ids: list[int], viewer_id: int) -> dict[int, list[dict[str, Any]]]:
        counts = (
            await db.execute(
                select(Reaction.message_id, Reaction.emoji, func.count())
                .where(Reaction.message_id.in_(message_ids))
                .group_by(Reaction.message_id, Reaction.emoji)
            )
        ).all()
        mine = {
            (mid, emoji)
            for mid, emoji in (
                await db.execute(select(Reaction.message_id, Reaction.emoji).where(Reaction.message_id.in_(message_ids), Reaction.user_id == viewer_id))
            ).all()
        }
        grouped: dict[int, list[dict[str, Any]]] = {}
        for mid, emoji, count in counts:
            grouped.setdefault(mid, []).append({"emoji": emoji, "count": count, "me": (mid, emoji) in mine})
        for items in grouped.values():
            items.sort(key=lambda item: ALLOWED_REACTIONS.index(item["emoji"]) if item["emoji"] in ALLOWED_REACTIONS else 99)
        return grouped

    async def delete(self, db: AsyncSession, message: Message) -> None:
        message.deleted_at = utcnow()
        message.pinned_at = None
        message.pinned_by = None
        for model in (MessageContent, SearchToken, Reaction, Mention):
            await db.execute(delete(model).where(model.message_id == message.id))

    async def set_reaction(self, db: AsyncSession, message_id: int, user_id: int, emoji: str, present: bool) -> None:
        if emoji not in ALLOWED_REACTIONS:
            raise AppError("reaction_not_allowed", 422)
        existing = await db.get(Reaction, (message_id, user_id, emoji))
        if present and existing is None:
            db.add(Reaction(message_id=message_id, user_id=user_id, emoji=emoji))
        elif not present and existing is not None:
            await db.delete(existing)

    async def mark_read(self, db: AsyncSession, user_id: int, scope: MessageScope, message_id: int) -> None:
        state = await db.get(ReadState, (user_id, scope.kind.value, scope.scope_id))
        if state is None:
            db.add(ReadState(user_id=user_id, scope_type=scope.kind.value, scope_id=scope.scope_id, last_read_message_id=message_id))
        elif message_id > state.last_read_message_id:
            state.last_read_message_id = message_id
            state.updated_at = utcnow()

    async def unread_count(self, db: AsyncSession, user_id: int, scope: MessageScope) -> int:
        state = await db.get(ReadState, (user_id, scope.kind.value, scope.scope_id))
        floor = state.last_read_message_id if state else 0
        statement = (
            select(func.count())
            .select_from(Message)
            .where(scope_clause(scope.kind, scope.scope_id), Message.id > floor, Message.deleted_at.is_(None), Message.author_id != user_id)
        )
        return (await db.execute(statement)).scalar_one()

    async def search(self, db: AsyncSession, scopes: list[MessageScope], terms: list[str], limit: int = 25) -> list[Message]:
        if not scopes or not terms:
            return []
        hash_to_scope: dict[bytes, MessageScope] = {}
        all_hashes: list[bytes] = []
        for scope in scopes:
            for digest in self.search_hashes(scope, terms):
                hash_to_scope[digest] = scope
                all_hashes.append(digest)
        statement = (
            select(SearchToken.message_id)
            .where(SearchToken.token_hash.in_(all_hashes))
            .group_by(SearchToken.message_id)
            .having(func.count() == len(terms))
            .order_by(SearchToken.message_id.desc())
            .limit(limit)
        )
        ids = list((await db.execute(statement)).scalars())
        if not ids:
            return []
        rows = (await db.execute(select(Message).where(Message.id.in_(ids), Message.deleted_at.is_(None)).order_by(Message.id.desc()))).scalars()
        return list(rows)

    def seal_snapshot(self, report_id: int, snapshot: list[dict[str, Any]]) -> tuple[bytes, str]:
        return self._vault.encrypt("report-snapshot", json.dumps(snapshot, ensure_ascii=False).encode("utf-8"), f"report|{report_id}".encode())

    def open_snapshot(self, report_id: int, blob: bytes, key_id: str) -> list[dict[str, Any]]:
        return json.loads(self._vault.decrypt("report-snapshot", blob, f"report|{report_id}".encode(), key_id).decode("utf-8"))

    async def snapshot_context(self, db: AsyncSession, target: Message, scope: MessageScope, before: int = 5, after: int = 2) -> list[dict[str, Any]]:
        earlier = (
            await db.execute(select(Message).where(scope_clause(scope.kind, scope.scope_id), Message.id < target.id).order_by(Message.id.desc()).limit(before))
        ).scalars()
        later = (
            await db.execute(select(Message).where(scope_clause(scope.kind, scope.scope_id), Message.id > target.id).order_by(Message.id.asc()).limit(after))
        ).scalars()
        ordered = [*reversed(list(earlier)), target, *later]
        texts = await self.texts_for(db, ordered)
        return [
            {
                "id": sid(m.id),
                "author_id": sid(m.author_id),
                "created_at": iso(m.created_at),
                "content": texts.get(m.id),
                "deleted": m.deleted_at is not None,
                "reported": m.id == target.id,
            }
            for m in ordered
        ]
