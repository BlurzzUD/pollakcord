from dataclasses import dataclass

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..models import Block, Friendship, ServerMember, UserSettings
from ..models.enums import (
    ActivityVisibility,
    CallPolicy,
    ClassVisibility,
    DirectMessagePolicy,
    FriendRequestPolicy,
    PresenceVisibility,
    ProfileVisibility,
)


def ordered(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


@dataclass(frozen=True)
class Relation:
    friends: bool
    blocked_by_viewer: bool
    blocked_viewer: bool
    shares_server: bool

    @property
    def blocked(self) -> bool:
        return self.blocked_by_viewer or self.blocked_viewer


SELF_RELATION = Relation(True, False, False, True)


async def relation(db: AsyncSession, viewer_id: int, target_id: int) -> Relation:
    if viewer_id == target_id:
        return SELF_RELATION
    low, high = ordered(viewer_id, target_id)
    friends = (await db.execute(select(exists().where(Friendship.user_low_id == low, Friendship.user_high_id == high)))).scalar_one()
    blocked_by_viewer = (
        await db.execute(select(exists().where(Block.blocker_id == viewer_id, Block.blocked_id == target_id)))
    ).scalar_one()
    blocked_viewer = (
        await db.execute(select(exists().where(Block.blocker_id == target_id, Block.blocked_id == viewer_id)))
    ).scalar_one()
    mine = aliased(ServerMember)
    theirs = aliased(ServerMember)
    shares = (
        await db.execute(
            select(
                exists().where(and_(mine.user_id == viewer_id, theirs.user_id == target_id, mine.server_id == theirs.server_id))
            )
        )
    ).scalar_one()
    return Relation(friends, blocked_by_viewer, blocked_viewer, shares)


async def get_settings_row(db: AsyncSession, user_id: int) -> UserSettings:
    row = await db.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        db.add(row)
        await db.flush()
    return row


def can_view_profile(rel: Relation, target: UserSettings) -> bool:
    if rel is SELF_RELATION:
        return True
    if rel.blocked:
        return False
    mode = target.profile_visibility
    if mode == ProfileVisibility.EVERYONE.value:
        return True
    if mode == ProfileVisibility.FRIENDS.value:
        return rel.friends
    return rel.friends or rel.shares_server


def class_visible_to(rel: Relation, target: UserSettings) -> bool:
    if rel is SELF_RELATION:
        return True
    if rel.blocked:
        return False
    mode = target.class_visibility
    if mode == ClassVisibility.HIDDEN.value:
        return False
    if mode == ClassVisibility.EVERYONE.value:
        return True
    if mode == ClassVisibility.FRIENDS.value:
        return rel.friends
    return rel.friends or rel.shares_server


def presence_visible_to(rel: Relation, target: UserSettings) -> bool:
    if rel is SELF_RELATION:
        return True
    if rel.blocked:
        return False
    mode = target.online_status
    if mode == PresenceVisibility.NOBODY.value:
        return False
    if mode == PresenceVisibility.FRIENDS.value:
        return rel.friends
    return rel.friends or rel.shares_server


def activity_visible_to(rel: Relation, target: UserSettings) -> bool:
    if rel is SELF_RELATION:
        return True
    if rel.blocked:
        return False
    return target.activity_visibility == ActivityVisibility.FRIENDS.value and rel.friends


def can_direct_message(rel: Relation, recipient: UserSettings) -> bool:
    if rel.blocked:
        return False
    if rel.friends:
        return True
    mode = recipient.direct_messages
    if mode == DirectMessagePolicy.EVERYONE.value:
        return True
    if mode == DirectMessagePolicy.SHARED_SERVERS.value:
        return rel.shares_server
    return False


def can_send_friend_request(rel: Relation, recipient: UserSettings, same_visible_class: bool) -> bool:
    if rel.blocked or rel.friends:
        return False
    mode = recipient.friend_requests
    if mode == FriendRequestPolicy.EVERYONE.value:
        return True
    if mode == FriendRequestPolicy.SHARED_SERVERS.value:
        return rel.shares_server or same_visible_class
    return False


def can_call(rel: Relation, callee: UserSettings) -> bool:
    if rel.blocked or not rel.friends:
        return False
    return callee.voice_calls == CallPolicy.FRIENDS.value


async def friend_ids(db: AsyncSession, user_id: int) -> set[int]:
    rows = (
        await db.execute(
            select(Friendship.user_low_id, Friendship.user_high_id).where(
                or_(Friendship.user_low_id == user_id, Friendship.user_high_id == user_id)
            )
        )
    ).all()
    return {high if low == user_id else low for low, high in rows}


async def blocked_ids(db: AsyncSession, user_id: int) -> set[int]:
    rows = (
        await db.execute(select(Block.blocker_id, Block.blocked_id).where(or_(Block.blocker_id == user_id, Block.blocked_id == user_id)))
    ).all()
    return {blocked if blocker == user_id else blocker for blocker, blocked in rows}


async def shared_server_user_ids(db: AsyncSession, user_id: int) -> set[int]:
    mine = aliased(ServerMember)
    theirs = aliased(ServerMember)
    rows = (
        await db.execute(
            select(theirs.user_id).join(mine, mine.server_id == theirs.server_id).where(mine.user_id == user_id, theirs.user_id != user_id).distinct()
        )
    ).scalars()
    return set(rows)
