import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

Handler = Callable[..., Awaitable[None]]


class BotHTTPError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"PollákCord returned {status}: {code}")


class Forbidden(BotHTTPError):
    pass


class NotFound(BotHTTPError):
    pass


class UnsupportedFeature(NotImplementedError):
    pass


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
    def __init__(self, origin: str, token: str | None = None) -> None:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("Supply a PollákCord origin without a path or credentials")
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1", "testserver"):
            raise ValueError("Use HTTPS outside local development")
        if token is not None and (not token or any(character.isspace() for character in token)):
            raise ValueError("Supply a bot token")
        self.origin = origin.rstrip("/")
        self._headers = {"Authorization": f"Bot {token}"} if token else {}
        self._http = httpx.AsyncClient(base_url=self.origin + "/api/v1/bots/api/", headers=self._headers, timeout=10, follow_redirects=False, trust_env=False)
        self._gateway_url = urlunsplit(("wss" if parsed.scheme == "https" else "ws", parsed.netloc, "/api/v1/bots/gateway", "", ""))
        self._message_handler: Handler | None = None
        self._slash_handlers: dict[str, Handler] = {}
        self._definitions: list[dict] = []
        self._tasks: set[asyncio.Task] = set()
        self._socket = None
        self.user: dict | None = None
        self._closing = asyncio.Event()
        self.latency = float("nan")
        self._ping_sent = 0.0
        self._last_pong = 0.0
        self._disconnect_handler = None

    def set_token(self, token: str) -> None:
        if not token or any(character.isspace() for character in token):
            raise ValueError("Supply a bot token")
        self._headers = {"Authorization": f"Bot {token}"}
        self._http.headers["Authorization"] = self._headers["Authorization"]

    async def __aenter__(self) -> "Bot":
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()

    async def _request(self, method: str, path: str, body: dict | None = None, *, params: dict | None = None):
        if not self._headers:
            raise RuntimeError("Call start(token) or login(token) before using the API")
        response = await self._http.request(method, path, json=body, params=params)
        if not response.is_success:
            try:
                code = str(response.json().get("error", {}).get("code", "request_failed"))
            except ValueError:
                code = "request_failed"
            error_class = {403: Forbidden, 404: NotFound}.get(response.status_code, BotHTTPError)
            raise error_class(response.status_code, code)
        return response.json() if response.content else None

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

    async def send_message(self, channel_id: str, content: str, *, reply_to_id: str | None = None) -> dict:
        body = {"content": content}
        if reply_to_id is not None:
            body["reply_to_id"] = self._id(reply_to_id)
        return await self._request("POST", f"channels/{self._id(channel_id)}/messages", body)

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
        elif kind == "pong":
            self._last_pong = time.monotonic()
            self.latency = self._last_pong - self._ping_sent if self._ping_sent else float("nan")
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
                error = completed.exception()
                if error is not None:
                    logging.getLogger("pollakcord").error("Bot handler failed: %s", type(error).__name__)
        task.add_done_callback(finished)

    async def _heartbeat(self, socket) -> None:
        while True:
            await asyncio.sleep(20)
            if time.monotonic() - self._last_pong > 45:
                await socket.close(code=1011)
                return
            self._ping_sent = time.monotonic()
            await socket.send(json.dumps({"op": "ping"}))

    async def _connect_once(self) -> None:
        async with connect(self._gateway_url, additional_headers=self._headers, max_size=262144, open_timeout=10, proxy=None) as socket:
            self._socket = socket
            self._last_pong = time.monotonic()
            heartbeat = asyncio.create_task(self._heartbeat(socket))
            try:
                async for raw in socket:
                    event = json.loads(raw)
                    if event.get("t") in ("ready", "pong"):
                        await self._handle(event)
                    else:
                        self._dispatch(event)
            finally:
                self._socket = None
                heartbeat.cancel()
                with suppress(asyncio.CancelledError, ConnectionClosed):
                    await heartbeat
                if self._disconnect_handler is not None:
                    await self._disconnect_handler()

    async def start(self, token: str | None = None, *, reconnect: bool = True) -> None:
        if token is not None:
            self.set_token(token)
        if not self._headers:
            raise ValueError("Supply a bot token")
        if self._closing.is_set():
            raise RuntimeError("This bot has been closed; create a new client")
        try:
            if self._definitions:
                await self.register_commands(self._definitions)
            attempt = 0
            while not self._closing.is_set():
                began = time.monotonic()
                try:
                    await self._connect_once()
                except ConnectionClosed as error:
                    code = error.rcvd.code if error.rcvd is not None else None
                    if code in (4401, 4403, 4400, 4429) or not reconnect:
                        raise BotHTTPError(401 if code == 4401 else 403, "gateway_closed") from None
                except InvalidStatus as error:
                    if error.response.status_code in (401, 403, 404) or not reconnect:
                        raise BotHTTPError(error.response.status_code, "gateway_rejected") from None
                except (OSError, TimeoutError):
                    if not reconnect:
                        raise BotHTTPError(0, "gateway_unavailable") from None
                if not reconnect or self._closing.is_set():
                    break
                attempt = 0 if time.monotonic() - began > 60 else attempt + 1
                delay = min(60, 2 ** min(attempt, 6)) + random.random()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._closing.wait(), timeout=delay)
        finally:
            await self.close()

    async def run(self) -> None:
        await self.start(reconnect=False)

    async def close(self) -> None:
        self._closing.set()
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
