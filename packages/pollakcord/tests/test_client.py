import asyncio
import io
import json
import sys
import tokenize
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pollakcord import Bot, BotHTTPError, Interaction


def test_auth_paths_payloads_and_handler_dispatch():
    async def scenario():
        seen = []
        async def transport(request):
            assert request.headers["Authorization"] == "Bot test-secret"
            assert "cookie" not in request.headers
            seen.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
            return httpx.Response(200, json={"id": "4"})
        bot = Bot("https://school.example", "test-secret")
        await bot._http.aclose()
        bot._http = httpx.AsyncClient(base_url=bot.origin + "/api/v1/bots/api/", headers=bot._headers, transport=httpx.MockTransport(transport))
        await bot.current()
        await bot.servers()
        await bot.channels("1")
        await bot.send_message("2", "Hello")
        await bot.delete_message("2", "4")
        await bot.register_commands([])
        messages = []
        @bot.on_message
        async def message(payload):
            messages.append(payload)
        @bot.slash("ping", "Ping")
        async def ping(interaction: Interaction):
            assert interaction.user_id == "8"
            await interaction.respond("Pong!")
        await bot._handle({"t": "ready", "d": {"user": {"id": "7", "is_bot": True}}})
        await bot._handle({"t": "message.create", "d": {"author": {"is_bot": True}, "content": "ignored"}})
        await bot._handle({"t": "message.create", "d": {"author": {"is_bot": False}, "content": "human"}})
        await bot._handle({"t": "interaction.create", "d": {"id": "3", "name": "ping", "options": {}, "channel_id": "2", "server_id": "1", "user": {"id": "8"}}})
        assert messages == [{"author": {"is_bot": False}, "content": "human"}]
        assert bot.user["is_bot"]
        assert seen == [
            ("GET", "/api/v1/bots/api/me", None), ("GET", "/api/v1/bots/api/servers", None),
            ("GET", "/api/v1/bots/api/servers/1/channels", None), ("POST", "/api/v1/bots/api/channels/2/messages", {"content": "Hello"}),
            ("DELETE", "/api/v1/bots/api/channels/2/messages/4", None), ("PUT", "/api/v1/bots/api/commands", {"commands": []}),
            ("POST", "/api/v1/bots/api/interactions/3/response", {"content": "Pong!"}),
        ]
        await bot.close()
    asyncio.run(scenario())


def test_gateway_url_authorization_heartbeat_and_cleanup(monkeypatch):
    import pollakcord.client as module

    class Socket:
        def __init__(self):
            self.frames = iter([json.dumps({"t": "ready", "d": {"user": {"id": "1", "is_bot": True}}})])
            self.closed = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return next(self.frames)
            except StopIteration:
                raise StopAsyncIteration
        async def close(self):
            self.closed = True
    socket = Socket()
    class Connection:
        async def __aenter__(self):
            return socket
        async def __aexit__(self, *_args):
            await socket.close()
    def connect(url, **kwargs):
        assert url == "wss://school.example/api/v1/bots/gateway"
        assert kwargs["additional_headers"] == {"Authorization": "Bot test-secret"}
        assert kwargs["proxy"] is None
        return Connection()
    monkeypatch.setattr(module, "connect", connect)
    async def scenario():
        bot = Bot("https://school.example", "test-secret")
        await bot.run()
        assert socket.closed and bot._http.is_closed and bot.user["is_bot"]
    asyncio.run(scenario())


def test_safe_errors_and_rejects_insecure_origins_and_path_ids():
    for origin in ("http://school.example", "https://school.example/api", "https://user:secret@school.example", "https://school.example?token=secret"):
        with pytest.raises(ValueError):
            Bot(origin, "test-secret")
    with pytest.raises(ValueError):
        Bot._id("1/../../me")
    async def scenario():
        bot = Bot("https://school.example", "test-secret")
        await bot._http.aclose()
        bot._http = httpx.AsyncClient(base_url=bot.origin + "/api/v1/bots/api/", transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"error": {"code": "bot_token_invalid"}})))
        with pytest.raises(BotHTTPError) as error:
            await bot.current()
        assert error.value.status == 401 and error.value.code == "bot_token_invalid" and "test-secret" not in str(error.value)
        await bot.close()
    asyncio.run(scenario())


def test_package_contains_no_python_comments_or_docstrings():
    import ast

    for path in Path(__file__).resolve().parents[1].rglob("*.py"):
        source = path.read_text()
        assert not [token for token in tokenize.generate_tokens(io.StringIO(source).readline) if token.type == tokenize.COMMENT]
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                assert ast.get_docstring(node) is None


def test_gateway_reconnects_with_backoff_and_close_stops_retrying(monkeypatch):
    import pollakcord.client as module

    async def scenario():
        bot = Bot("https://school.example", "test-secret")
        attempts = []
        async def connect_once():
            attempts.append(len(attempts))
            if len(attempts) == 1:
                raise OSError("Temporary disconnect")
            bot._closing.set()
        monkeypatch.setattr(bot, "_connect_once", connect_once)
        monkeypatch.setattr(module.random, "random", lambda: 0)
        await asyncio.wait_for(bot.start(reconnect=True), timeout=4)
        assert len(attempts) == 2 and bot._http.is_closed
    asyncio.run(scenario())


def test_revoked_gateway_is_terminal_and_does_not_reconnect(monkeypatch):
    from websockets.exceptions import ConnectionClosedError
    from websockets.frames import Close

    async def scenario():
        bot = Bot("https://school.example", "test-secret")
        attempts = []
        async def connect_once():
            attempts.append(1)
            raise ConnectionClosedError(Close(4401, ""), Close(4401, ""), True)
        monkeypatch.setattr(bot, "_connect_once", connect_once)
        with pytest.raises(BotHTTPError) as error:
            await bot.start()
        assert error.value.status == 401 and len(attempts) == 1 and bot._http.is_closed
        assert "test-secret" not in str(error.value)
    asyncio.run(scenario())
