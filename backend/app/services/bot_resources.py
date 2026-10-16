from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError
from ..models import BotInstall, Channel, MemberRole, ServerMember
from .people import load_cards
from .permissions import Perm, load_channel_context, require_context
from .serializers import channel_dict, iso, role_dict, sid


async def server_context(db: AsyncSession, server_id: int, bot_id: int):
    context = await require_context(db, server_id, bot_id)
    if await db.get(BotInstall, (server_id, bot_id)) is None:
        raise AppError("not_found", 404)
    return context


async def text_context(db: AsyncSession, channel_id: int, bot_id: int):
    channel, context = await load_channel_context(db, channel_id, bot_id)
    if channel.type != "text" or await db.get(BotInstall, (channel.server_id, bot_id)) is None:
        raise AppError("not_found", 404)
    return channel, context


async def member_payload(db: AsyncSession, server_id: int, user_id: int) -> dict | None:
    cards = await load_cards(db, {user_id})
    if user_id not in cards:
        return None
    member = await db.get(ServerMember, (server_id, user_id))
    roles = list((await db.execute(select(MemberRole.role_id).where(MemberRole.server_id == server_id, MemberRole.user_id == user_id))).scalars())
    return {"user": cards[user_id], "nickname": member.nickname if member else None, "role_ids": [sid(role_id) for role_id in roles], "joined_at": iso(member.joined_at) if member else None, "timeout_until": iso(member.timeout_until) if member else None}


async def visible_text_channels(db: AsyncSession, context) -> list[dict]:
    channels = (await db.execute(select(Channel).where(Channel.server_id == context.server.id, Channel.type == "text").order_by(Channel.position, Channel.id))).scalars()
    return [{**channel_dict(channel), "my_permissions": context.channel_permissions(channel)} for channel in channels if context.visible_channel(channel)]


async def server_payload(db: AsyncSession, context) -> dict:
    return {"id": sid(context.server.id), "name": context.server.name, "description": context.server.description, "owner_id": sid(context.server.owner_id), "my_permissions": context.base, "my_role_ids": [sid(role_id) for role_id in context.member_role_ids], "roles": [role_dict(role) for role in context.roles.values()], "channels": await visible_text_channels(db, context)}


async def member_access(db: AsyncSession, context) -> None:
    if not await visible_text_channels(db, context):
        raise AppError("not_found", 404)


async def moderation_target(db: AsyncSession, auth, server_id: int, user_id: int):
    from ..models import User
    from .permissions import load_context

    actor = await server_context(db, server_id, auth.user.id)
    target = await load_context(db, server_id, user_id)
    user = await db.get(User, user_id)
    if target is None or user is None:
        raise AppError("not_found", 404)
    if user.is_bot or user_id == auth.owner.id or not actor.outranks(target):
        raise AppError("role_hierarchy", 403)
    return actor, target
