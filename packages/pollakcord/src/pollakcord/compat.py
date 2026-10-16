from __future__ import annotations

import asyncio
import copy
import importlib
import inspect
import json
import logging
import os
from collections import OrderedDict
from types import SimpleNamespace

from . import app_commands
from .client import Bot as Transport
from .client import NotFound, UnsupportedFeature
from .objects import Guild, Interaction, Intents, Member, Message, Reaction, TextChannel, User, snowflake


class Client:
    def __init__(self, *, origin: str | None = None, intents: Intents | None = None, max_messages: int = 1000) -> None:
        if not 0 <= max_messages <= 10000:
            raise ValueError("max_messages must be between 0 and 10000")
        self._transport = Transport(origin or os.environ.get("POLLAKCORD_ORIGIN", ""))
        self.origin = self._transport.origin
        self.intents = intents or Intents.default()
        self.tree = app_commands.CommandTree(self)
        self.user: User | None = None
        self.owner_id: int | None = None
        self._guilds: dict[int, Guild] = {}
        self._messages: OrderedDict[int, Message] = OrderedDict()
        self._max_messages = max_messages
        self._listeners: dict[str, list] = {}
        self._waiters: dict[str, list] = {}
        self._tasks: set[asyncio.Task] = set()
        self._ready = asyncio.Event()
        self._started = False
        self.extensions: dict[str, object] = {}
        self._transport._handle = self._receive
        self._transport._disconnect_handler = self._disconnected

    @property
    def latency(self) -> float:
        return self._transport.latency

    @property
    def guilds(self) -> list[Guild]:
        return list(self._guilds.values())

    @property
    def cached_messages(self) -> list[Message]:
        return list(self._messages.values())

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def is_closed(self) -> bool:
        return self._transport._closing.is_set()

    async def wait_until_ready(self) -> None:
        await self._ready.wait()

    async def _disconnected(self) -> None:
        self._ready.clear()
        self.dispatch("disconnect")

    def get_guild(self, guild_id: int) -> Guild | None:
        return self._guilds.get(snowflake(guild_id))

    def get_channel(self, channel_id: int) -> TextChannel | None:
        channel_id = snowflake(channel_id)
        return next((guild._channels[channel_id] for guild in self.guilds if channel_id in guild._channels), None)

    def get_user(self, user_id: int) -> User | None:
        user_id = snowflake(user_id)
        if self.user and self.user.id == user_id:
            return self.user
        return next((guild._members[user_id] for guild in self.guilds if user_id in guild._members), None)

    async def fetch_user(self, user_id: int) -> User:
        raise UnsupportedFeature("Global user lookup is unavailable; use guild.fetch_member(user_id)")

    async def _request(self, method: str, path: str, body: dict | None = None, *, params: dict | None = None):
        return await self._transport._request(method, path, body, params=params)

    async def fetch_guild(self, guild_id: int) -> Guild:
        guild_id = snowflake(guild_id)
        try:
            data = await self._request("GET", f"servers/{guild_id}")
        except NotFound:
            self._guilds.pop(guild_id, None)
            raise
        guild = self._guilds.get(guild_id)
        if guild is None:
            guild = Guild(self, data)
            self._guilds[guild.id] = guild
        else:
            guild._update(data)
        return guild

    async def fetch_guilds(self, *, limit: int | None = 100):
        rows = await self._transport.servers()
        for row in rows[:limit] if limit is not None else rows:
            yield await self.fetch_guild(int(row["id"]))

    async def fetch_channel(self, channel_id: int) -> TextChannel:
        data = await self._request("GET", f"channels/{snowflake(channel_id)}")
        guild = self.get_guild(int(data["server_id"])) or await self.fetch_guild(int(data["server_id"]))
        channel = TextChannel(self, data, guild=guild)
        guild._channels[channel.id] = channel
        return channel

    def event(self, callback):
        if not inspect.iscoroutinefunction(callback) or not callback.__name__.startswith("on_"):
            raise TypeError("Events must be async functions named on_event")
        setattr(self, callback.__name__, callback)
        return callback

    def listen(self, name: str | None = None):
        def decorator(callback):
            self.add_listener(callback, name)
            return callback
        return decorator

    def add_listener(self, callback, name: str | None = None) -> None:
        if not inspect.iscoroutinefunction(callback):
            raise TypeError("Listeners must be async functions")
        name = (name or callback.__name__).removeprefix("on_")
        self._listeners.setdefault(name, []).append(callback)

    def remove_listener(self, callback, name: str | None = None) -> None:
        listeners = self._listeners.get((name or callback.__name__).removeprefix("on_"), [])
        if callback in listeners:
            listeners.remove(callback)

    def _schedule(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        def finished(completed):
            self._tasks.discard(completed)
            if not completed.cancelled():
                error = completed.exception()
                if error:
                    logging.getLogger("pollakcord").error("Client task failed: %s", type(error).__name__)
        task.add_done_callback(finished)
        return task

    def dispatch(self, event: str, *args) -> None:
        self._schedule(self._emit(event, *args))

    async def _emit(self, event: str, *args) -> None:
        for future, predicate in list(self._waiters.get(event, [])):
            if future.done():
                continue
            try:
                if predicate is None or predicate(*args):
                    future.set_result(args[0] if len(args) == 1 else args)
            except Exception as error:
                future.set_exception(error)
        handler = getattr(self, "on_" + event, None)
        callbacks = ([handler] if callable(handler) else []) + list(self._listeners.get(event, []))
        for callback in callbacks:
            try:
                await callback(*args)
            except Exception as error:
                if event == "error":
                    logging.getLogger("pollakcord").error("Error handler failed: %s", type(error).__name__)
                else:
                    await self._emit("error", event, type(error).__name__)

    async def wait_for(self, event: str, *, check=None, timeout: float | None = None):
        if sum(len(items) for items in self._waiters.values()) >= 128:
            raise RuntimeError("Too many pending event waiters")
        event = event.removeprefix("on_")
        future = asyncio.get_running_loop().create_future()
        entry = (future, check)
        self._waiters.setdefault(event, []).append(entry)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._waiters[event].remove(entry)
            if not self._waiters[event]:
                self._waiters.pop(event, None)

    async def on_error(self, event: str, error_type: str) -> None:
        logging.getLogger("pollakcord").error("Event %s failed: %s", event, error_type)

    async def setup_hook(self) -> None:
        if self.tree.get_commands():
            await self.tree.sync()

    async def on_app_command_error(self, interaction, error) -> None:
        await self.on_error("app_command", type(error).__name__)

    async def login(self, token: str) -> None:
        self._transport.set_token(token)
        data = await self._transport.current()
        self.user = User(self, data["user"])
        self.owner_id = int(data["owner_id"]) if data.get("owner_id") else None
        if not self._started:
            self._started = True
            await self.setup_hook()

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        try:
            await self.login(token)
            await self._transport.start(reconnect=reconnect)
        finally:
            await self.close()

    def run(self, token: str, *, reconnect: bool = True) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(self.start(token, reconnect=reconnect))
            except KeyboardInterrupt:
                return
        else:
            raise RuntimeError("Use await client.start(token) inside an async program")

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()

    async def close(self) -> None:
        self._ready.clear()
        await self._transport.close()
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        for waiters in self._waiters.values():
            for future, _ in waiters:
                if not future.done():
                    future.cancel()
        self._guilds.clear()
        self._messages.clear()

    def _cache_message(self, message: Message) -> None:
        if self._max_messages:
            self._messages[message.id] = message
            self._messages.move_to_end(message.id)
            while len(self._messages) > self._max_messages:
                self._messages.popitem(last=False)

    async def _receive(self, event: dict) -> None:
        kind, data = event.get("t"), event.get("d", {})
        if kind == "pong":
            import time

            self._transport._last_pong = time.monotonic()
            self._transport.latency = self._transport._last_pong - self._transport._ping_sent if self._transport._ping_sent else float("nan")
            return
        if kind == "ready":
            self._ready.clear()
            self._guilds.clear()
            self._messages.clear()
            self.user = User(self, data["user"])
            events = ["message.update", "message.pin", "structure.changed", "role.changed", "server.updated"] if self.intents.guilds else ["message.update"]
            if self.intents.members:
                events += ["member.joined", "member.left", "member.updated"]
            if self.intents.reactions:
                events.append("reaction.update")
            if self._transport._socket:
                await self._transport._socket.send(json.dumps({"op": "subscribe", "events": events}))
            async for guild in self.fetch_guilds(limit=None):
                self._guilds[guild.id] = guild
            self._ready.set()
            self.dispatch("ready")
            return
        if kind.startswith("message.") and kind != "message.pin":
            if not self.intents.messages:
                return
            data = dict(data)
            if not self.intents.message_content:
                data["content"] = ""
            if kind == "message.create":
                message = Message(self, data)
                self._cache_message(message)
                await self._emit("message", message)
            elif kind == "message.delete":
                cached = self._messages.pop(int(data["id"]), None)
                await self._emit("raw_message_delete", SimpleNamespace(message_id=int(data["id"]), channel_id=int(data["channel_id"]), guild_id=int(data["server_id"]), cached_message=cached))
                if cached:
                    await self._emit("message_delete", cached)
            elif kind == "message.update":
                before = self._messages.get(int(data["id"]))
                after = Message(self, data)
                self._cache_message(after)
                await self._emit("raw_message_edit", SimpleNamespace(message_id=after.id, channel_id=after.channel.id, guild_id=int(data["server_id"]), data=data, cached_message=before))
                if before:
                    await self._emit("message_edit", before, after)
        elif kind == "interaction.create":
            interaction = Interaction(self, data)
            await asyncio.wait_for(self.tree._invoke(interaction), timeout=2.8)
        elif kind in ("member.joined", "member.left", "member.updated") and self.intents.members:
            guild = self.get_guild(int(data["server_id"]))
            if guild is None:
                return
            before = guild.get_member(int(data["user_id"]))
            member = guild._store_member(data["member"])
            if kind == "member.left":
                guild._members.pop(member.id, None)
                await self._emit("member_remove", before or member)
            elif kind == "member.joined":
                await self._emit("member_join", member)
            else:
                await self._emit("raw_member_update", member)
                if before:
                    await self._emit("member_update", before, member)
        elif kind == "reaction.update" and self.intents.reactions:
            payload = SimpleNamespace(message_id=int(data["message_id"]), channel_id=int(data["channel_id"]), guild_id=int(data["server_id"]), user_id=int(data["user_id"]), emoji=data["emoji"])
            await self._emit("raw_reaction_add" if data["present"] else "raw_reaction_remove", payload)
            message = self._messages.get(payload.message_id)
            if message:
                reaction = next((item for item in message.reactions if item.emoji == payload.emoji), None)
                if reaction is None:
                    reaction = Reaction(message, {"emoji": payload.emoji, "count": 0, "me": False})
                    message.reactions.append(reaction)
                reaction.count = max(0, reaction.count + (1 if data["present"] else -1))
                if self.user and self.user.id == payload.user_id:
                    reaction.me = data["present"]
                message.reactions = [item for item in message.reactions if item.count > 0]
                user = message.guild.get_member(payload.user_id) if message.guild else None
                user = user or User(self, {"id": str(payload.user_id)})
                await self._emit("reaction_add" if data["present"] else "reaction_remove", reaction, user)
        elif kind == "message.pin":
            cached = self._messages.get(int(data["id"]))
            if cached:
                cached.pinned = data["pinned"]
            channel = self.get_channel(int(data["channel_id"]))
            if channel:
                await self._emit("guild_channel_pins_update", channel, None)
        elif kind in ("structure.changed", "role.changed", "server.updated") and self.intents.guilds:
            guild = self.get_guild(int(data["server_id"]))
            if guild is None:
                return
            before = copy.copy(guild)
            old = dict(guild._channels if kind == "structure.changed" else guild._roles)
            guild._update(data)
            if "channels" in data:
                visible_ids = set(guild._channels)
                for message_id, message in list(self._messages.items()):
                    if message.guild and message.guild.id == guild.id and message.channel.id not in visible_ids:
                        self._messages.pop(message_id, None)
            if kind == "structure.changed":
                await self._diff_events("guild_channel", old, guild._channels)
            elif kind == "role.changed":
                await self._diff_events("guild_role", old, guild._roles)
            else:
                await self._emit("guild_update", before, guild)

    async def _diff_events(self, prefix: str, before: dict, after: dict) -> None:
        for key in before.keys() - after.keys():
            await self._emit(prefix + "_delete", before[key])
        for key in after.keys() - before.keys():
            await self._emit(prefix + "_create", after[key])
        for key in before.keys() & after.keys():
            fields = ("name", "topic", "position", "slowmode_delay") if prefix == "guild_channel" else ("name", "position", "color")
            changed = any(getattr(before[key], field, None) != getattr(after[key], field, None) for field in fields)
            if prefix == "guild_role":
                changed = changed or before[key].permissions.value != after[key].permissions.value
            if changed:
                await self._emit(prefix + "_update", before[key], after[key])

    async def load_extension(self, name: str) -> None:
        if name in self.extensions:
            raise ValueError("Extension is already loaded")
        module = importlib.import_module(name)
        setup = getattr(module, "setup", None)
        if setup is None or not inspect.iscoroutinefunction(setup):
            raise TypeError("Extensions need an async setup(bot) function")
        await setup(self)
        self.extensions[name] = module
