import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from ..logging_config import get_logger

logger = get_logger("pollakcord.hub")
SEND_TIMEOUT_SECONDS = 3.0


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    user_id: int
    session_id: int
    topics: set[str] = field(default_factory=set)
    closed: bool = False


class Hub:
    def __init__(self) -> None:
        self._by_user: dict[int, set[Connection]] = {}
        self._topics: dict[str, set[Connection]] = {}
        self.revalidator: Callable[[int], Awaitable[None]] | None = None

    def connections_of(self, user_id: int) -> set[Connection]:
        return self._by_user.get(user_id, set())

    def connection_count(self, user_id: int) -> int:
        return len(self._by_user.get(user_id, ()))

    def is_online(self, user_id: int) -> bool:
        return bool(self._by_user.get(user_id))

    def online_among(self, user_ids: set[int]) -> set[int]:
        return {uid for uid in user_ids if self.is_online(uid)}

    def register(self, connection: Connection) -> bool:
        group = self._by_user.setdefault(connection.user_id, set())
        first = not group
        group.add(connection)
        return first

    def unregister(self, connection: Connection) -> bool:
        connection.closed = True
        for topic in list(connection.topics):
            self.unsubscribe(connection, topic)
        group = self._by_user.get(connection.user_id)
        if group is None:
            return False
        group.discard(connection)
        if not group:
            del self._by_user[connection.user_id]
            return True
        return False

    def subscribe(self, connection: Connection, topic: str) -> None:
        connection.topics.add(topic)
        self._topics.setdefault(topic, set()).add(connection)

    def unsubscribe(self, connection: Connection, topic: str) -> None:
        connection.topics.discard(topic)
        members = self._topics.get(topic)
        if members is not None:
            members.discard(connection)
            if not members:
                del self._topics[topic]

    def subscribe_user(self, user_id: int, topic: str) -> None:
        for connection in list(self.connections_of(user_id)):
            self.subscribe(connection, topic)

    def unsubscribe_user(self, user_id: int, topic: str) -> None:
        for connection in list(self.connections_of(user_id)):
            self.unsubscribe(connection, topic)

    def subscribers(self, topic: str) -> set[Connection]:
        return set(self._topics.get(topic, ()))

    def channel_subscribed_users(self, channel_ids: list[int]) -> set[int]:
        users: set[int] = set()
        for channel_id in channel_ids:
            users.update(c.user_id for c in self._topics.get(f"channel:{channel_id}", ()))
        return users

    async def _deliver(self, connection: Connection, text: str) -> None:
        if connection.closed:
            return
        try:
            await asyncio.wait_for(connection.websocket.send_text(text), timeout=SEND_TIMEOUT_SECONDS)
        except Exception:
            connection.closed = True
            try:
                await connection.websocket.close(code=1011)
            except Exception:
                return

    @staticmethod
    def encode(event: str, data: dict[str, Any]) -> str:
        return json.dumps({"t": event, "d": data}, separators=(",", ":"), ensure_ascii=False, default=str)

    async def send_to_user(self, user_id: int, event: str, data: dict[str, Any]) -> None:
        text = self.encode(event, data)
        await asyncio.gather(*(self._deliver(c, text) for c in list(self.connections_of(user_id))))

    async def publish(self, topic: str, event: str, data: dict[str, Any], exclude_user: int | None = None) -> None:
        text = self.encode(event, data)
        targets = [c for c in list(self._topics.get(topic, ())) if c.user_id != exclude_user]
        await asyncio.gather(*(self._deliver(c, text) for c in targets))

    async def evict_user_from_server(self, user_id: int, server_id: int, channel_ids: list[int]) -> None:
        self.unsubscribe_user(user_id, f"server:{server_id}")
        for channel_id in channel_ids:
            self.unsubscribe_user(user_id, f"channel:{channel_id}")

    async def revalidate_server(self, server_id: int) -> None:
        if self.revalidator is not None:
            await self.revalidator(server_id)

    async def close_user_session(self, user_id: int, session_id: int, code: int = 4401) -> None:
        for connection in list(self.connections_of(user_id)):
            if connection.session_id == session_id:
                connection.closed = True
                try:
                    await connection.websocket.close(code=code)
                except Exception:
                    continue

    async def close_user(self, user_id: int, code: int = 4401) -> None:
        for connection in list(self.connections_of(user_id)):
            connection.closed = True
            try:
                await connection.websocket.close(code=code)
            except Exception:
                continue
