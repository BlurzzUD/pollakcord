import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI, WebSocket
from sqlalchemy import select

from ..db.types import utcnow
from ..errors import AppError
from ..logging_config import get_logger
from ..models import Conversation, Server, ServerMember, User
from ..models.enums import AccountStatus, AuditAction, ChannelType, NotificationType, SessionScope
from ..security.sessions import load_session
from ..services import audit, people, privacy
from ..services.notifications import notify
from ..services.permissions import Perm, load_channel_context, load_context
from ..services.serializers import sid
from .hub import Connection, Hub
from .outbox import Outbox

logger = get_logger("pollakcord.ws")
router = APIRouter()
MAX_FRAME_CHARS = 32768
IDLE_TIMEOUT_SECONDS = 75
SESSION_RECHECK_SECONDS = 60
FRAME_WINDOW_SECONDS = 10
FRAME_LIMIT = 80
MAX_CHANNEL_SUBSCRIPTIONS = 60
MAX_SIGNAL_CHARS = 16384
SIGNAL_KINDS = frozenset({"offer", "answer", "ice"})
TYPING_INTERVAL_SECONDS = 3


@dataclass
class PendingCall:
    caller_id: int
    callee_id: int
    accepted: bool
    task: asyncio.Task | None


def install_revalidator(app: FastAPI) -> None:
    app.state.calls = {}
    app.state.voice_owner = {}
    app.state.background_tasks = set()

    async def revalidate(server_id: int) -> None:
        await revalidate_channel_subscriptions(app, server_id)

    app.state.hub.revalidator = revalidate


def spawn(app: FastAPI, coroutine) -> None:
    task = asyncio.get_running_loop().create_task(coroutine)
    app.state.background_tasks.add(task)
    task.add_done_callback(app.state.background_tasks.discard)


async def shutdown_realtime(app: FastAPI) -> None:
    for pending in list(app.state.calls.values()):
        if pending.task is not None:
            pending.task.cancel()
    tasks = list(app.state.background_tasks)
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=2)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def send_to_connection(hub: Hub, connection: Connection, event: str, data: dict[str, Any]) -> None:
    await hub._deliver(connection, hub.encode(event, data))


def parse_int(value: Any) -> int:
    if isinstance(value, bool):
        raise AppError("validation_error", 422)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit() and len(value) <= 20:
        return int(value)
    raise AppError("validation_error", 422)


async def broadcast_presence(app: FastAPI, user_id: int, online: bool) -> None:
    async with app.state.session_factory() as db:
        row = await privacy.get_settings_row(db, user_id)
        audience = await people.presence_audience(db, user_id, row.online_status)
        await db.commit()
    payload = {"user_id": sid(user_id), "status": "online" if online else "offline"}
    for target in audience:
        await app.state.hub.send_to_user(target, "presence.update", payload)


async def revalidate_channel_subscriptions(app: FastAPI, server_id: int) -> None:
    hub: Hub = app.state.hub
    async with app.state.session_factory() as db:
        from ..models import Channel

        channels = {c.id: c for c in (await db.execute(select(Channel).where(Channel.server_id == server_id))).scalars()}
        subscribed = hub.channel_subscribed_users(list(channels))
        for user_id in subscribed:
            context = await load_context(db, server_id, user_id)
            for connection in list(hub.connections_of(user_id)):
                for topic in [t for t in connection.topics if t.startswith("channel:")]:
                    channel = channels.get(int(topic.split(":", 1)[1]))
                    if channel is None:
                        continue
                    if context is None or not context.can_in(channel, Perm.READ_MESSAGE_HISTORY):
                        hub.unsubscribe(connection, topic)
        voice = app.state.voice
        for channel in channels.values():
            room = voice.room(f"channel:{channel.id}")
            if room is None:
                continue
            for participant_id in list(room.participants):
                context = await load_context(db, server_id, participant_id)
                if context is None or not context.can_in(channel, Perm.CONNECT):
                    await leave_voice(app, participant_id, notify_user="permissions")


async def channel_update_event(app: FastAPI, room) -> None:
    if room.server_id is not None and room.channel_id is not None:
        await app.state.hub.publish(
            f"server:{room.server_id}",
            "voice.channel_update",
            {"server_id": sid(room.server_id), "channel_id": sid(room.channel_id), "participants": room.snapshot()},
        )


async def leave_voice(app: FastAPI, user_id: int, notify_user: str | None = None) -> None:
    hub: Hub = app.state.hub
    voice = app.state.voice
    previous = voice.room_of(user_id)
    room = voice.leave(user_id)
    app.state.voice_owner.pop(user_id, None)
    if room is None:
        return
    if notify_user:
        await hub.send_to_user(user_id, "voice.disconnected", {"reason": notify_user})
    if room.server_id is not None:
        for other in room.participants:
            await hub.send_to_user(other, "voice.participant_left", {"user_id": sid(user_id), "room": room.key})
        empty = voice.room(room.key) is None
        if empty:
            room.participants.clear()
        await channel_update_event(app, room)
        return
    conversation_id = int(room.key.split(":", 1)[1])
    pending = app.state.calls.pop(conversation_id, None)
    if pending is not None and pending.task is not None:
        pending.task.cancel()
    for other in list(room.participants):
        voice.leave(other)
        app.state.voice_owner.pop(other, None)
        await hub.send_to_user(other, "call.ended", {"conversation_id": sid(conversation_id), "reason": "hangup"})
    del previous


async def force_leave_voice(app: FastAPI, user_id: int, server_id: int) -> None:
    room = app.state.voice.room_of(user_id)
    if room is not None and room.server_id == server_id:
        await leave_voice(app, user_id, notify_user="removed")


async def close_voice_room(app: FastAPI, channel_id: int, server_id: int) -> None:
    room = app.state.voice.room(f"channel:{channel_id}")
    if room is None:
        return
    for user_id in list(room.participants):
        await leave_voice(app, user_id, notify_user="channel_deleted")


async def authenticate(websocket: WebSocket) -> tuple[Any, User, list[int]] | None:
    app = websocket.app
    settings = app.state.settings
    origin = websocket.headers.get("origin")
    if origin is None or origin.rstrip("/") not in settings.allowed_origins:
        return None
    token = websocket.cookies.get(app.state.cookies.session)
    if not token:
        return None
    async with app.state.session_factory() as db:
        loaded = await load_session(db, token, settings)
        if loaded is None:
            return None
        record, user = loaded
        if record.scope != SessionScope.FULL.value or user.status != AccountStatus.ACTIVE.value:
            return None
        server_ids = list((await db.execute(select(ServerMember.server_id).where(ServerMember.user_id == user.id))).scalars())
    return record, user, server_ids


async def session_still_valid(app: FastAPI, session_id: int, user_id: int) -> bool:
    from ..models import AuthSession

    async with app.state.session_factory() as db:
        record = await db.get(AuthSession, session_id)
        user = await db.get(User, user_id)
    return (
        record is not None
        and record.revoked_at is None
        and record.expires_at > utcnow()
        and user is not None
        and user.status == AccountStatus.ACTIVE.value
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    app = websocket.app
    hub: Hub = app.state.hub
    identity = await authenticate(websocket)
    if identity is None:
        await websocket.close(code=4401)
        return
    record, user, server_ids = identity
    if hub.connection_count(user.id) >= app.state.settings.ws_max_connections_per_user:
        await websocket.close(code=4429)
        return
    await websocket.accept()
    connection = Connection(websocket=websocket, user_id=user.id, session_id=record.id)
    first = hub.register(connection)
    for server_id in server_ids:
        hub.subscribe(connection, f"server:{server_id}")
    await send_to_connection(hub, connection, "ready", {"user_id": sid(user.id)})
    if first:
        spawn(app, broadcast_presence(app, user.id, True))
    try:
        await receive_loop(app, connection)
    except Exception as exc:
        logger.info("ws_closed", extra={"error_type": type(exc).__name__})
    finally:
        last = hub.unregister(connection)
        spawn(app, finalize_connection(app, connection, last))


async def finalize_connection(app: FastAPI, connection: Connection, last: bool) -> None:
    try:
        if app.state.voice_owner.get(connection.user_id) is connection:
            await leave_voice(app, connection.user_id)
        if last:
            async with app.state.session_factory() as db:
                row = await db.get(User, connection.user_id)
                if row is not None:
                    row.last_seen_at = utcnow()
                    await db.commit()
            await broadcast_presence(app, connection.user_id, False)
    except Exception as exc:
        logger.error("ws_cleanup_failed", extra={"error_type": type(exc).__name__})


async def receive_loop(app: FastAPI, connection: Connection) -> None:
    hub: Hub = app.state.hub
    frames: deque[float] = deque()
    last_check = time.monotonic()
    while not connection.closed:
        try:
            event = await asyncio.wait_for(connection.websocket.receive(), timeout=IDLE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await connection.websocket.close(code=4408)
            return
        if event["type"] == "websocket.disconnect":
            return
        text = event.get("text")
        if text is None:
            continue
        now = time.monotonic()
        frames.append(now)
        while frames and frames[0] < now - FRAME_WINDOW_SECONDS:
            frames.popleft()
        if len(text) > MAX_FRAME_CHARS:
            await connection.websocket.close(code=4413)
            return
        if len(frames) > FRAME_LIMIT:
            await connection.websocket.close(code=4429)
            return
        if now - last_check > SESSION_RECHECK_SECONDS:
            last_check = now
            if not await session_still_valid(app, connection.session_id, connection.user_id):
                await connection.websocket.close(code=4401)
                return
        try:
            message = json.loads(text)
            operation = message["op"]
            data = message.get("d") or {}
            if not isinstance(operation, str) or not isinstance(data, dict):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        handler = HANDLERS.get(operation)
        if handler is None:
            continue
        try:
            await handler(app, connection, data)
        except AppError as error:
            await send_to_connection(hub, connection, "error", {"op": operation, "code": error.code})
        except Exception as exc:
            logger.error("ws_handler_failed", extra={"op": operation, "error_type": type(exc).__name__})
            await send_to_connection(hub, connection, "error", {"op": operation, "code": "internal_error"})


async def op_ping(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    await send_to_connection(app.state.hub, connection, "pong", {})


async def op_subscribe(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    channel_id = parse_int(data.get("channel_id"))
    if sum(1 for t in connection.topics if t.startswith("channel:")) >= MAX_CHANNEL_SUBSCRIPTIONS:
        raise AppError("subscription_limit", 429)
    async with app.state.session_factory() as db:
        channel, context = await load_channel_context(db, channel_id, connection.user_id)
        if channel.type != ChannelType.TEXT.value:
            raise AppError("channel_type_invalid", 422)
        context.require_in(channel, Perm.READ_MESSAGE_HISTORY)
    app.state.hub.subscribe(connection, f"channel:{channel_id}")
    await send_to_connection(app.state.hub, connection, "subscribed", {"channel_id": sid(channel_id)})


async def op_unsubscribe(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    app.state.hub.unsubscribe(connection, f"channel:{parse_int(data.get('channel_id'))}")


async def op_typing(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    hub: Hub = app.state.hub
    scope, target_id = data.get("scope"), parse_int(data.get("id"))
    if app.state.limiter.check(f"typing:{connection.user_id}:{scope}:{target_id}", 1, TYPING_INTERVAL_SECONDS) is not None:
        return
    payload = {"scope": scope, "id": sid(target_id), "user_id": sid(connection.user_id)}
    async with app.state.session_factory() as db:
        if scope == "channel":
            channel, context = await load_channel_context(db, target_id, connection.user_id)
            context.require_in(channel, Perm.SEND_MESSAGES)
            await hub.publish(f"channel:{target_id}", "typing", payload, exclude_user=connection.user_id)
            return
        if scope == "dm":
            conversation = await db.get(Conversation, target_id)
            if conversation is None or connection.user_id not in (conversation.user_low_id, conversation.user_high_id):
                raise AppError("not_found", 404)
            other = conversation.user_high_id if conversation.user_low_id == connection.user_id else conversation.user_low_id
            if (await privacy.relation(db, connection.user_id, other)).blocked:
                return
            await hub.send_to_user(other, "typing", payload)
            return
    raise AppError("validation_error", 422)


async def join_room(app: FastAPI, connection: Connection, key: str, *, server_id: int | None, channel_id: int | None, limit: int) -> None:
    hub: Hub = app.state.hub
    voice = app.state.voice
    current = voice.room_of(connection.user_id)
    if current is not None and current.key == key:
        return
    if current is not None:
        await leave_voice(app, connection.user_id)
    room = voice.join(connection.user_id, key, server_id=server_id, channel_id=channel_id, limit=limit)
    app.state.voice_owner[connection.user_id] = connection
    others = [p for p in room.participants if p != connection.user_id]
    await send_to_connection(
        hub,
        connection,
        "voice.joined",
        {"room": key, "server_id": sid(server_id), "channel_id": sid(channel_id), "participants": room.snapshot(), "you": sid(connection.user_id)},
    )
    for other in others:
        await hub.send_to_user(other, "voice.participant_joined", {"user_id": sid(connection.user_id), "room": key, "participants": room.snapshot()})
    await channel_update_event(app, room)


async def op_voice_join(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    channel_id = parse_int(data.get("channel_id"))
    async with app.state.session_factory() as db:
        channel, context = await load_channel_context(db, channel_id, connection.user_id)
        if channel.type != ChannelType.VOICE.value:
            raise AppError("channel_type_invalid", 422)
        context.require_in(channel, Perm.CONNECT)
        limit = channel.user_limit
        server_id = channel.server_id
    await join_room(app, connection, f"channel:{channel_id}", server_id=server_id, channel_id=channel_id, limit=limit)


async def op_voice_leave(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    if app.state.voice_owner.get(connection.user_id) is connection or app.state.voice.room_of(connection.user_id):
        await leave_voice(app, connection.user_id)


async def op_voice_signal(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    recipient = parse_int(data.get("to"))
    kind = data.get("kind")
    payload = data.get("data")
    if kind not in SIGNAL_KINDS or not isinstance(payload, dict) or len(json.dumps(payload)) > MAX_SIGNAL_CHARS:
        raise AppError("validation_error", 422)
    if not app.state.voice.can_relay(connection.user_id, recipient):
        raise AppError("forbidden", 403)
    room = app.state.voice.room_of(connection.user_id)
    await app.state.hub.send_to_user(recipient, "voice.signal", {"from": sid(connection.user_id), "kind": kind, "data": payload, "room": room.key})


async def op_voice_state(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    muted, deafened = bool(data.get("muted", False)), bool(data.get("deafened", False))
    room = app.state.voice.update_state(connection.user_id, muted=muted or deafened, deafened=deafened)
    if room is None:
        return
    for participant in room.participants:
        await app.state.hub.send_to_user(participant, "voice.state", {"room": room.key, "participants": room.snapshot()})
    await channel_update_event(app, room)


async def op_voice_moderate(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    channel_id, target_id = parse_int(data.get("channel_id")), parse_int(data.get("user_id"))
    server_muted = data.get("server_muted")
    server_deafened = data.get("server_deafened")
    async with app.state.session_factory() as db:
        channel, actor = await load_channel_context(db, channel_id, connection.user_id)
        if channel.type != ChannelType.VOICE.value:
            raise AppError("channel_type_invalid", 422)
        if server_muted is not None:
            actor.require_in(channel, Perm.MUTE_MEMBERS)
        if server_deafened is not None:
            actor.require_in(channel, Perm.DEAFEN_MEMBERS)
        target = await load_context(db, channel.server_id, target_id)
        if target is None or (target_id != connection.user_id and not actor.outranks(target)):
            raise AppError("role_hierarchy", 403)
        audit.record(
            db,
            AuditAction.VOICE_MODERATE,
            actor_id=connection.user_id,
            server_id=channel.server_id,
            target_type="user",
            target_id=target_id,
            details={"server_muted": server_muted, "server_deafened": server_deafened, "channel": channel.name},
        )
        await db.commit()
    room = app.state.voice.moderate(
        f"channel:{channel_id}",
        target_id,
        server_muted=bool(server_muted) if server_muted is not None else None,
        server_deafened=bool(server_deafened) if server_deafened is not None else None,
    )
    if room is None:
        return
    for participant in room.participants:
        await app.state.hub.send_to_user(participant, "voice.state", {"room": room.key, "participants": room.snapshot()})
    await channel_update_event(app, room)


async def load_call_parties(app: FastAPI, connection: Connection, data: dict[str, Any]) -> tuple[int, int]:
    conversation_id = parse_int(data.get("conversation_id"))
    async with app.state.session_factory() as db:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None or connection.user_id not in (conversation.user_low_id, conversation.user_high_id):
            raise AppError("not_found", 404)
    other = conversation.user_high_id if conversation.user_low_id == connection.user_id else conversation.user_low_id
    return conversation_id, other


async def ring_timeout(app: FastAPI, conversation_id: int, caller_id: int, callee_id: int) -> None:
    await asyncio.sleep(app.state.settings.call_ring_seconds)
    pending = app.state.calls.get(conversation_id)
    if pending is None or pending.accepted:
        return
    app.state.calls.pop(conversation_id, None)
    app.state.voice.leave(caller_id)
    app.state.voice_owner.pop(caller_id, None)
    hub: Hub = app.state.hub
    outbox = Outbox(hub)
    async with app.state.session_factory() as db:
        cards = await people.load_cards(db, {caller_id})
        await notify(db, outbox, callee_id, NotificationType.CALL_MISSED, {"conversation_id": sid(conversation_id), "user": cards.get(caller_id)})
        await db.commit()
    await outbox.flush()
    await hub.send_to_user(caller_id, "call.ended", {"conversation_id": sid(conversation_id), "reason": "unanswered"})
    await hub.send_to_user(callee_id, "call.ended", {"conversation_id": sid(conversation_id), "reason": "missed"})


async def op_call_invite(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    hub: Hub = app.state.hub
    conversation_id, callee_id = await load_call_parties(app, connection, data)
    if app.state.limiter.check(f"call:{connection.user_id}", 6, 60) is not None:
        raise AppError("rate_limited", 429)
    if conversation_id in app.state.calls:
        raise AppError("call_in_progress", 409)
    async with app.state.session_factory() as db:
        callee = await db.get(User, callee_id)
        relation = await privacy.relation(db, connection.user_id, callee_id)
        callee_settings = await privacy.get_settings_row(db, callee_id)
        if callee is None or callee.status != AccountStatus.ACTIVE.value or not privacy.can_call(relation, callee_settings):
            raise AppError("call_not_allowed", 403)
        cards = await people.load_cards(db, {connection.user_id})
    if not hub.is_online(callee_id):
        raise AppError("callee_offline", 409)
    if app.state.voice.room_of(callee_id) is not None:
        raise AppError("callee_busy", 409)
    await join_room(app, connection, f"dm:{conversation_id}", server_id=None, channel_id=None, limit=2)
    task = asyncio.create_task(ring_timeout(app, conversation_id, connection.user_id, callee_id))
    app.state.calls[conversation_id] = PendingCall(connection.user_id, callee_id, False, task)
    await hub.send_to_user(
        callee_id,
        "call.incoming",
        {"conversation_id": sid(conversation_id), "from": cards.get(connection.user_id), "expires_in": app.state.settings.call_ring_seconds},
    )


async def op_call_accept(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    conversation_id, _ = await load_call_parties(app, connection, data)
    pending = app.state.calls.get(conversation_id)
    if pending is None or pending.callee_id != connection.user_id or pending.accepted:
        raise AppError("not_found", 404)
    pending.accepted = True
    if pending.task is not None:
        pending.task.cancel()
    await join_room(app, connection, f"dm:{conversation_id}", server_id=None, channel_id=None, limit=2)
    await app.state.hub.send_to_user(pending.caller_id, "call.accepted", {"conversation_id": sid(conversation_id)})


async def end_pending_call(app: FastAPI, connection: Connection, data: dict[str, Any], as_caller: bool) -> None:
    conversation_id, _ = await load_call_parties(app, connection, data)
    pending = app.state.calls.get(conversation_id)
    if pending is None or pending.accepted:
        return
    if (as_caller and pending.caller_id != connection.user_id) or (not as_caller and pending.callee_id != connection.user_id):
        raise AppError("forbidden", 403)
    app.state.calls.pop(conversation_id, None)
    if pending.task is not None:
        pending.task.cancel()
    app.state.voice.leave(pending.caller_id)
    app.state.voice_owner.pop(pending.caller_id, None)
    other = pending.callee_id if as_caller else pending.caller_id
    reason = "cancelled" if as_caller else "declined"
    await app.state.hub.send_to_user(other, "call.ended", {"conversation_id": sid(conversation_id), "reason": reason})


async def op_call_decline(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    await end_pending_call(app, connection, data, as_caller=False)


async def op_call_cancel(app: FastAPI, connection: Connection, data: dict[str, Any]) -> None:
    await end_pending_call(app, connection, data, as_caller=True)


HANDLERS = {
    "ping": op_ping,
    "subscribe": op_subscribe,
    "unsubscribe": op_unsubscribe,
    "typing": op_typing,
    "voice.join": op_voice_join,
    "voice.leave": op_voice_leave,
    "voice.signal": op_voice_signal,
    "voice.state": op_voice_state,
    "voice.moderate": op_voice_moderate,
    "call.invite": op_call_invite,
    "call.accept": op_call_accept,
    "call.decline": op_call_decline,
    "call.cancel": op_call_cancel,
}
