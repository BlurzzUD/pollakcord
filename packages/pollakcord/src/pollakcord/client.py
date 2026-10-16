import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect

Handler = Callable[..., Awaitable[None]]


class BotHTTPError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"PollákCord returned {status}: {code}")


@dataclass
class Interaction:
    bot: "Bot"
    id: str
    name: str
    options: dict[str, Any]
    channel_id: str
    server_id: str
    user_id: str

    async def respond(self, content: str) -> dict:
        return await self.bot.respond(self.id, content)


class Bot:
    def __init__(self, origin: str, token: str) -> None:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("Supply a PollákCord origin without a path or credentials")
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1", "testserver"):
            raise ValueError("Use HTTPS outside local development")
        if not token or any(character.isspace() for character in token):
            raise ValueError("Supply a bot token")
        self.origin = origin.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self.origin + "/api/v1/bots/api/", headers={"Authorization": f"Bot {token}"}, timeout=10, follow_redirects=False, trust_env=False)
        self._gateway_url = urlunsplit(("wss" if parsed.scheme == "https" else "ws", parsed.netloc, "/api/v1/bots/gateway", "", ""))
        self._headers = {"Authorization": f"Bot {token}"}
        self._message_handler: Handler | None = None
        self._slash_handlers: dict[str, Handler] = {}
        self._definitions: list[dict] = []
        self._tasks: set[asyncio.Task] = set()
        self._socket = None
        self.user: dict | None = None

    async def __aenter__(self) -> "Bot":
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()

    async def _request(self, method: str, path: str, body: dict | None = None):
        response = await self._http.request(method, path, json=body)
        if not response.is_success:
            try:
                code = str(response.json().get("error", {}).get("code", "request_failed"))
            except ValueError:
                code = "request_failed"
            raise BotHTTPError(response.status_code, code)
        return response.json()

    async def current(self) -> dict:
        return await self._request("GET", "me")

    async def servers(self) -> list[dict]:
        return await self._request("GET", "servers")

    async def channels(self, server_id: str) -> list[dict]:
        return await self._request("GET", f"servers/{self._id(server_id)}/channels")

    @staticmethod
    def _id(value: str) -> str:
        value = str(value)
        if not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63:
            raise ValueError("Expected a PollákCord ID")
        return value

    async def send_message(self, channel_id: str, content: str) -> dict:
        return await self._request("POST", f"channels/{self._id(channel_id)}/messages", {"content": content})

    async def delete_message(self, channel_id: str, message_id: str) -> dict:
        return await self._request("DELETE", f"channels/{self._id(channel_id)}/messages/{self._id(message_id)}")

    async def list_commands(self) -> list[dict]:
        return await self._request("GET", "commands")

    async def register_commands(self, definitions: list[dict]) -> list[dict]:
        return await self._request("PUT", "commands", {"commands": definitions})

    async def respond(self, interaction_id: str, content: str) -> dict:
        return await self._request("POST", f"interactions/{self._id(interaction_id)}/response", {"content": content})

    def on_message(self, handler: Handler) -> Handler:
        self._message_handler = handler
        return handler

    def slash(self, name: str, description: str, *, options: list[dict] | None = None, default_member_permissions: list[str] | None = None):
        def register(handler: Handler) -> Handler:
            self._slash_handlers[name] = handler
            definition = {"name": name, "description": description, "options": options or [], "default_member_permissions": default_member_permissions or []}
            self._definitions = [item for item in self._definitions if item["name"] != name] + [definition]
            return handler
        return register

    async def _handle(self, event: dict) -> None:
        kind, data = event.get("t"), event.get("d", {})
        if kind == "ready":
            self.user = data["user"]
        elif kind == "message.create" and self._message_handler and not (data.get("author") or {}).get("is_bot", False):
            await self._message_handler(data)
        elif kind == "interaction.create":
            handler = self._slash_handlers.get(data["name"])
            if handler:
                interaction = Interaction(self, data["id"], data["name"], data.get("options", {}), data["channel_id"], data["server_id"], data["user"]["id"])
                await asyncio.wait_for(handler(interaction), timeout=2.8)

    def _dispatch(self, event: dict) -> None:
        if len(self._tasks) >= 64:
            return
        task = asyncio.create_task(self._handle(event))
        self._tasks.add(task)
        def finished(completed: asyncio.Task) -> None:
            self._tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()
        task.add_done_callback(finished)

    async def _heartbeat(self, socket) -> None:
        while True:
            await asyncio.sleep(20)
            await socket.send(json.dumps({"op": "ping"}))

    async def run(self) -> None:
        try:
            if self._definitions:
                await self.register_commands(self._definitions)
            async with connect(self._gateway_url, additional_headers=self._headers, max_size=65536, open_timeout=10, proxy=None) as socket:
                self._socket = socket
                heartbeat = asyncio.create_task(self._heartbeat(socket))
                try:
                    async for raw in socket:
                        event = json.loads(raw)
                        if event.get("t") == "ready":
                            await self._handle(event)
                        else:
                            self._dispatch(event)
                finally:
                    heartbeat.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat
        finally:
            await self.close()

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None
        current = asyncio.current_task()
        remaining = [task for task in self._tasks if task is not current]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        self._tasks.clear()
        await self._http.aclose()
