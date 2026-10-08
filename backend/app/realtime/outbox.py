from typing import Any

from .hub import Hub


class Outbox:
    def __init__(self, hub: Hub) -> None:
        self._hub = hub
        self._items: list[tuple[str, tuple[Any, ...]]] = []

    def user(self, user_id: int, event: str, data: dict[str, Any]) -> None:
        self._items.append(("user", (user_id, event, data)))

    def users(self, user_ids: list[int] | set[int], event: str, data: dict[str, Any]) -> None:
        for user_id in user_ids:
            self.user(user_id, event, data)

    def topic(self, topic: str, event: str, data: dict[str, Any], exclude_user: int | None = None) -> None:
        self._items.append(("topic", (topic, event, data, exclude_user)))

    def subscribe(self, user_id: int, topic: str) -> None:
        self._items.append(("subscribe", (user_id, topic)))

    def unsubscribe(self, user_id: int, topic: str) -> None:
        self._items.append(("unsubscribe", (user_id, topic)))

    def evict_server(self, user_id: int, server_id: int, channel_ids: list[int]) -> None:
        self._items.append(("evict_server", (user_id, server_id, channel_ids)))

    def revalidate_server(self, server_id: int) -> None:
        self._items.append(("revalidate", (server_id,)))

    async def flush(self) -> None:
        items, self._items = self._items, []
        for kind, args in items:
            if kind == "user":
                await self._hub.send_to_user(*args)
            elif kind == "topic":
                await self._hub.publish(*args)
            elif kind == "subscribe":
                self._hub.subscribe_user(*args)
            elif kind == "unsubscribe":
                self._hub.unsubscribe_user(*args)
            elif kind == "evict_server":
                user_id, server_id, channel_ids = args
                await self._hub.evict_user_from_server(user_id, server_id, channel_ids)
            elif kind == "revalidate":
                await self._hub.revalidate_server(*args)
