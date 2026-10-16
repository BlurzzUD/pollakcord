import asyncio
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..errors import AppError
from ..models import BotApplication, BotInstall, Channel, Profile, User
from ..models.enums import AccountStatus
from ..security.bots import MAX_GATEWAYS_PER_BOT, MAX_GATEWAYS_PER_OWNER, authenticate_bot, bot_rate
from ..services.permissions import Perm, load_context
from ..services.serializers import sid, user_card
from .hub import Hub

router = APIRouter()
EXTRA_EVENTS = frozenset({"member.joined", "member.left", "member.updated", "reaction.update", "message.pin", "message.update", "server.updated", "structure.changed", "role.changed"})


@dataclass(eq=False)
class BotConnection:
    websocket: WebSocket
    bot_id: int
    owner_id: int
    token_hash: str
    closed: bool = False
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    events: set[str] = field(default_factory=lambda: {"message.create", "message.delete", "interaction.create"})


class BotGateway:
    def __init__(self, app) -> None:
        self.app = app
        self.connections: dict[int, set[BotConnection]] = {}
        self.pending: dict[int, asyncio.Future] = {}
        self.pending_bots: dict[int, int] = {}
        self.locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

    def lock(self, key: str) -> asyncio.Lock:
        lock = self.locks.setdefault(key, asyncio.Lock())
        self.locks.move_to_end(key)
        if len(self.locks) > 4096:
            for old_key, old_lock in list(self.locks.items()):
                if old_key != key and not old_lock.locked():
                    self.locks.pop(old_key, None)
                    break
        return lock

    def online(self, bot_id: int) -> bool:
        return any(not c.closed for c in self.connections.get(bot_id, ()))

    def register(self, connection: BotConnection) -> None:
        group = self.connections.setdefault(connection.bot_id, set())
        owner_count = sum(not c.closed for connections in self.connections.values() for c in connections if c.owner_id == connection.owner_id)
        if sum(not c.closed for c in group) >= MAX_GATEWAYS_PER_BOT or owner_count >= MAX_GATEWAYS_PER_OWNER:
            raise AppError("bot_gateway_limit", 429)
        group.add(connection)

    def unregister(self, connection: BotConnection) -> None:
        connection.closed = True
        group = self.connections.get(connection.bot_id)
        if group is not None:
            group.discard(connection)
            if not group:
                self.connections.pop(connection.bot_id, None)

    async def valid(self, db, connection: BotConnection) -> bool:
        application = await db.get(BotApplication, connection.bot_id)
        user = await db.get(User, connection.bot_id)
        owner = await db.get(User, connection.owner_id)
        return bool(application and application.deleted_at is None and application.token_hash == connection.token_hash and user and user.is_bot and user.platform_role == "user" and user.school_class_id is None and user.status == AccountStatus.ACTIVE.value and owner and not owner.is_bot and owner.status == AccountStatus.ACTIVE.value)

    async def send(self, connection: BotConnection, event: str, data: dict[str, Any]) -> bool:
        if connection.closed:
            return False
        try:
            async with connection.send_lock:
                await asyncio.wait_for(connection.websocket.send_text(Hub.encode(event, data)), timeout=1.0)
            return True
        except Exception:
            await self.close(connection)
            return False

    async def close(self, connection: BotConnection, code: int = 4401) -> None:
        self.unregister(connection)
        try:
            await connection.websocket.close(code=code)
        except Exception:
            return

    async def close_bot(self, bot_id: int) -> None:
        for interaction_id, target_id in list(self.pending_bots.items()):
            future = self.pending.get(interaction_id)
            if target_id == bot_id and future is not None and not future.done():
                future.set_exception(AppError("bot_offline", 409))
        for connection in list(self.connections.get(bot_id, ())):
            await self.close(connection)

    async def close_owner(self, owner_id: int) -> None:
        for group in list(self.connections.values()):
            for connection in list(group):
                if connection.owner_id == owner_id:
                    await self.close_bot(connection.bot_id)

    async def shutdown(self) -> None:
        for bot_id in list(self.connections):
            await self.close_bot(bot_id)
        for future in list(self.pending.values()):
            if not future.done():
                future.cancel()
        self.pending.clear()
        self.pending_bots.clear()

    async def authorized(self, db, connection: BotConnection, channel: Channel, *, send: bool = False) -> bool:
        if not await self.valid(db, connection) or channel.type != "text":
            return False
        if await db.get(BotInstall, (channel.server_id, connection.bot_id)) is None:
            return False
        context = await load_context(db, channel.server_id, connection.bot_id)
        needed = Perm.SEND_MESSAGES if send else Perm.READ_MESSAGE_HISTORY
        return bool(context and context.can_in(channel, Perm.VIEW_CHANNEL) and context.can_in(channel, needed))

    async def publish(self, topic: str, event: str, data: dict[str, Any]) -> None:
        if not self.connections or not any(event in c.events or event == "member.updated" and "structure.changed" in c.events for group in self.connections.values() for c in group):
            return
        if topic.startswith("server:") and event in EXTRA_EVENTS:
            await self.publish_server(int(topic.split(":", 1)[1]), event, data)
            return
        if event not in ("message.create", "message.delete", "message.update", "reaction.update", "message.pin") or not topic.startswith("channel:"):
            return
        if event.startswith("message.") and event != "message.pin" and data.get("scope") != "channel":
            return
        channel_id = int(topic.split(":", 1)[1])
        async with self.app.state.session_factory() as db:
            channel = await db.get(Channel, channel_id)
            if channel is None or channel.type != "text":
                return
            installed_ids = set((await db.execute(select(BotInstall.bot_user_id).where(BotInstall.server_id == channel.server_id, BotInstall.bot_user_id.in_(list(self.connections))))).scalars())
            for bot_id in installed_ids:
                for connection in list(self.connections.get(bot_id, ())):
                    if event not in connection.events:
                        continue
                    if not await self.valid(db, connection):
                        await self.close(connection)
                    elif await self.authorized(db, connection, channel):
                        payload = {key: data[key] for key in ("id", "scope", "channel_id", "author", "content", "deleted", "created_at", "edited_at", "reply_to", "message_id", "emoji", "user_id", "present", "pinned") if key in data}
                        payload["server_id"] = sid(channel.server_id)
                        await self.send(connection, event, payload)

    async def publish_server(self, server_id: int, event: str, data: dict) -> None:
        from ..services.bot_resources import member_payload, visible_text_channels

        async with self.app.state.session_factory() as db:
            bot_ids = (await db.execute(select(BotInstall.bot_user_id).where(BotInstall.server_id == server_id, BotInstall.bot_user_id.in_(list(self.connections))))).scalars()
            for bot_id in bot_ids:
                context = await load_context(db, server_id, bot_id)
                if context is None:
                    continue
                visible = await visible_text_channels(db, context)
                for connection in list(self.connections.get(bot_id, ())):
                    raw = data.get("user_id") or (data.get("user") or {}).get("id")
                    refresh_self = event == "member.updated" and str(raw) == str(bot_id) and "structure.changed" in connection.events
                    if event not in connection.events and not refresh_self:
                        continue
                    if not await self.valid(db, connection):
                        await self.close(connection)
                        continue
                    if refresh_self:
                        await self.send(connection, "structure.changed", {"server_id": sid(server_id), "channels": visible, "my_permissions": context.base, "my_role_ids": [sid(role_id) for role_id in context.member_role_ids]})
                    if event not in connection.events:
                        continue
                    if event.startswith("member."):
                        if not visible:
                            continue
                        if not raw or not str(raw).isdigit():
                            continue
                        payload = await member_payload(db, server_id, int(raw))
                        if payload is None:
                            continue
                        await self.send(connection, event, {"server_id": sid(server_id), "user_id": str(raw), "member": payload})
                    elif event == "structure.changed":
                        await self.send(connection, event, {"server_id": sid(server_id), "channels": visible})
                    elif event == "role.changed":
                        from ..services.serializers import role_dict

                        await self.send(connection, event, {"server_id": sid(server_id), "roles": [role_dict(role) for role in context.roles.values()], "channels": visible, "my_permissions": context.base, "my_role_ids": [sid(role_id) for role_id in context.member_role_ids]})
                    elif event == "server.updated":
                        await self.send(connection, event, {"server_id": sid(server_id), "name": context.server.name, "description": context.server.description, "owner_id": sid(context.server.owner_id)})

    async def interaction(self, bot_id: int, channel_id: int, data: dict) -> bool:
        async with self.app.state.session_factory() as db:
            channel = await db.get(Channel, channel_id)
            if channel is None:
                return False
            for connection in list(self.connections.get(bot_id, ())):
                if await self.authorized(db, connection, channel, send=True):
                    return await self.send(connection, "interaction.create", data)
        return False

    def complete(self, interaction_id: int, payload: dict) -> None:
        future = self.pending.get(interaction_id)
        if future is not None and not future.done():
            future.set_result(payload)


@router.websocket("/bots/gateway")
async def gateway(websocket: WebSocket) -> None:
    app = websocket.app
    manager: BotGateway = app.state.bot_gateway
    connection = None
    try:
        header = websocket.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bot" or websocket.headers.get("origin") or websocket.cookies.get(app.state.cookies.session) or websocket.query_params:
            await websocket.close(code=4401)
            return
        from ..security.ratelimit import enforce

        enforce(websocket, "bot-gateway-ip", 30, 60)
        async with app.state.session_factory() as db:
            auth = await authenticate_bot(db, token)
            bot_rate(websocket, auth, "gateway-connect", 6, 60, 12)
            connection = BotConnection(websocket, auth.user.id, auth.owner.id, auth.application.token_hash)
            manager.register(connection)
            card = user_card(auth.user, await db.get(Profile, auth.user.id))
        token = ""
        await websocket.accept()
        if not await manager.send(connection, "ready", {"user": card, "heartbeat_interval": 20, "interaction_timeout": 3}):
            return
        while not connection.closed:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=45)
            except asyncio.TimeoutError:
                await manager.close(connection, 4408)
                break
            if len(raw) > 1024:
                await manager.close(connection, 4400)
                break
            async with app.state.session_factory() as db:
                if not await manager.valid(db, connection):
                    await manager.close(connection)
                    break
            for label, subject, limit in (("frame", connection.bot_id, 10), ("owner-frame", connection.owner_id, 24)):
                if app.state.limiter.check(f"bot-{label}:{subject}", limit, 10) is not None:
                    raise AppError("rate_limited", 429)
            try:
                frame = json.loads(raw)
            except (ValueError, TypeError):
                raise AppError("validation_error", 422)
            if not isinstance(frame, dict):
                raise AppError("bot_gateway_operation", 422)
            if frame.get("op") == "ping":
                await manager.send(connection, "pong", {})
            elif frame.get("op") == "subscribe" and isinstance(frame.get("events"), list) and len(frame["events"]) <= len(EXTRA_EVENTS) and all(isinstance(event, str) and event in EXTRA_EVENTS for event in frame["events"]):
                connection.events = {"message.create", "message.delete", "interaction.create", *frame["events"]}
                await manager.send(connection, "subscribed", {"events": sorted(connection.events)})
            else:
                raise AppError("bot_gateway_operation", 422)
    except AppError as error:
        if connection is not None:
            await manager.close(connection, 4429 if error.status == 429 else 4401)
        else:
            await websocket.close(code=4429 if error.status == 429 else 4401)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if connection is not None:
            manager.unregister(connection)
