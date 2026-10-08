from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...crypto.blind_index import fold, tokenize
from ...models import Channel, Conversation, Message, Server, ServerMember
from ...models.enums import ChannelType, ScopeKind
from ...security.ratelimit import enforce
from ...services import people, privacy
from ...services.messages import MessageScope
from ...services.permissions import Perm, load_context
from ...services.serializers import channel_dict, server_summary, sid
from ..deps import Auth, get_db, require_auth
from .users import find_users

router = APIRouter(tags=["search"])
ALL_TYPES = ("friends", "users", "servers", "channels", "messages")


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(min_length=2, max_length=64),
    types: str = Query(default=",".join(ALL_TYPES), max_length=80),
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    enforce(request, "search", 40, 60, subject=str(auth.user.id))
    wanted = {t for t in types.split(",") if t in ALL_TYPES} or set(ALL_TYPES)
    needle = fold(q.strip())
    result: dict[str, list] = {t: [] for t in ALL_TYPES}
    friend_set = await privacy.friend_ids(db, auth.user.id)
    if "friends" in wanted:
        cards = await people.load_cards(db, friend_set)
        result["friends"] = [c for c in cards.values() if needle in fold(c["display_name"]) or needle in c["username"]][:20]
    if "users" in wanted:
        result["users"] = [c for c in await find_users(db, auth.user.id, q.strip().lower(), limit=20) if int(c["id"]) not in friend_set]
    memberships = list((await db.execute(select(Server).join(ServerMember, ServerMember.server_id == Server.id).where(ServerMember.user_id == auth.user.id))).scalars())
    if "servers" in wanted:
        result["servers"] = [server_summary(s) for s in memberships if needle in fold(s.name)][:20]
    need_scopes = "channels" in wanted or "messages" in wanted
    scopes: list[MessageScope] = []
    scope_info: dict[tuple[str, int], dict] = {}
    if need_scopes:
        for server in memberships:
            context = await load_context(db, server.id, auth.user.id)
            if context is None:
                continue
            channels = (await db.execute(select(Channel).where(Channel.server_id == server.id))).scalars()
            for channel in channels:
                if not context.visible_channel(channel):
                    continue
                if "channels" in wanted and needle in fold(channel.name) and len(result["channels"]) < 20:
                    result["channels"].append({**channel_dict(channel), "server_name": server.name})
                if channel.type == ChannelType.TEXT.value and context.can_in(channel, Perm.READ_MESSAGE_HISTORY):
                    scope = MessageScope(ScopeKind.CHANNEL, channel.id, server.id)
                    scopes.append(scope)
                    scope_info[(scope.kind.value, scope.scope_id)] = {"server_id": sid(server.id), "server_name": server.name, "channel_id": sid(channel.id), "channel_name": channel.name}
    if "messages" in wanted:
        conversations = (
            await db.execute(select(Conversation).where(or_(Conversation.user_low_id == auth.user.id, Conversation.user_high_id == auth.user.id)))
        ).scalars().all()
        others = {c.user_high_id if c.user_low_id == auth.user.id else c.user_low_id for c in conversations}
        cards = await people.load_cards(db, others)
        for conversation in conversations:
            other = conversation.user_high_id if conversation.user_low_id == auth.user.id else conversation.user_low_id
            scopes.append(MessageScope(ScopeKind.DM, conversation.id))
            scope_info[("dm", conversation.id)] = {"conversation_id": sid(conversation.id), "user": cards.get(other)}
        terms = tokenize(q)
        service = request.app.state.messages
        found = await service.search(db, scopes[:600], terms, limit=20)
        grouped: dict[tuple[str, int], list[Message]] = {}
        for message in found:
            key = ("dm", message.conversation_id) if message.conversation_id is not None else ("channel", message.channel_id)
            grouped.setdefault(key, []).append(message)
        entries = []
        for (kind, scope_id), items in grouped.items():
            scope = next((s for s in scopes if s.kind.value == kind and s.scope_id == scope_id), None)
            if scope is None:
                continue
            for payload in await service.payloads(db, items, auth.user.id, scope):
                entries.append({"message": payload, "where": scope_info.get((kind, scope_id), {})})
        entries.sort(key=lambda e: int(e["message"]["id"]), reverse=True)
        result["messages"] = entries[:20]
    return result
