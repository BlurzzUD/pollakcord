from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Profile, User, UserSettings
from ..realtime.hub import Hub
from . import privacy
from .privacy import Relation
from .serializers import user_card


async def load_cards(db: AsyncSession, user_ids: set[int] | list[int]) -> dict[int, dict[str, Any]]:
    ids = set(user_ids)
    if not ids:
        return {}
    rows = (await db.execute(select(User, Profile).outerjoin(Profile, Profile.user_id == User.id).where(User.id.in_(ids)))).all()
    return {user.id: user_card(user, profile) for user, profile in rows}


async def load_settings_map(db: AsyncSession, user_ids: set[int] | list[int]) -> dict[int, UserSettings]:
    ids = set(user_ids)
    if not ids:
        return {}
    return {row.user_id: row for row in (await db.execute(select(UserSettings).where(UserSettings.user_id.in_(ids)))).scalars()}


async def presence_map(db: AsyncSession, hub: Hub, viewer_id: int, target_ids: set[int]) -> dict[int, str | None]:
    if not target_ids:
        return {}
    friends = await privacy.friend_ids(db, viewer_id)
    shared = await privacy.shared_server_user_ids(db, viewer_id)
    blocked = await privacy.blocked_ids(db, viewer_id)
    settings_map = await load_settings_map(db, target_ids)
    result: dict[int, str | None] = {}
    for target_id in target_ids:
        if target_id == viewer_id:
            result[target_id] = "online" if hub.is_online(target_id) else "offline"
            continue
        row = settings_map.get(target_id)
        relation = Relation(target_id in friends, target_id in blocked, False, target_id in shared)
        if row is None or not privacy.presence_visible_to(relation, row):
            result[target_id] = None
        else:
            result[target_id] = "online" if hub.is_online(target_id) else "offline"
    return result


async def presence_audience(db: AsyncSession, user_id: int, mode: str) -> set[int]:
    if mode == "nobody":
        return set()
    audience = await privacy.friend_ids(db, user_id)
    if mode == "shared_servers":
        audience |= await privacy.shared_server_user_ids(db, user_id)
    audience -= await privacy.blocked_ids(db, user_id)
    return audience
