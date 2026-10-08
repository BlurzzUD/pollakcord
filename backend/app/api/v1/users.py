from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ...errors import AppError
from ...models import FriendRequest, Profile, SchoolClass, Server, ServerMember, User
from ...models.enums import AccountStatus
from ...security.ratelimit import enforce
from ...services import people, privacy
from ...services.privacy import Relation, get_settings_row
from ...services.serializers import media_url, sid, user_card, user_profile
from ..deps import Auth, get_db, require_auth

router = APIRouter(prefix="/users", tags=["users"])


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def shared_servers(db: AsyncSession, viewer_id: int, target_id: int) -> list[dict]:
    mine = aliased(ServerMember)
    theirs = aliased(ServerMember)
    rows = (
        await db.execute(
            select(Server)
            .join(mine, mine.server_id == Server.id)
            .join(theirs, theirs.server_id == Server.id)
            .where(mine.user_id == viewer_id, theirs.user_id == target_id)
            .order_by(Server.name)
            .limit(20)
        )
    ).scalars()
    return [{"id": sid(s.id), "name": s.name, "icon_url": media_url("server_icon", s.icon_key)} for s in rows]


async def pending_direction(db: AsyncSession, viewer_id: int, target_id: int) -> str | None:
    outgoing = (await db.execute(select(FriendRequest.id).where(FriendRequest.sender_id == viewer_id, FriendRequest.recipient_id == target_id))).first()
    if outgoing:
        return "outgoing"
    incoming = (await db.execute(select(FriendRequest.id).where(FriendRequest.sender_id == target_id, FriendRequest.recipient_id == viewer_id))).first()
    return "incoming" if incoming else None


@router.get("/search")
async def search_users(
    request: Request, q: str = Query(min_length=2, max_length=40), auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    enforce(request, "user-search", 40, 60, subject=str(auth.user.id))
    return await find_users(db, auth.user.id, q.strip().lower(), limit=20)


async def find_users(db: AsyncSession, viewer_id: int, needle: str, limit: int) -> list[dict]:
    pattern = escape_like(needle)
    statement = (
        select(User, Profile)
        .outerjoin(Profile, Profile.user_id == User.id)
        .where(
            User.status == AccountStatus.ACTIVE.value,
            User.id != viewer_id,
            or_(User.username_lower.like(pattern + "%", escape="\\"), User.display_name.ilike("%" + pattern + "%", escape="\\")),
        )
        .limit(60)
    )
    rows = (await db.execute(statement)).all()
    if not rows:
        return []
    ids = {user.id for user, _ in rows}
    friends = await privacy.friend_ids(db, viewer_id)
    shared = await privacy.shared_server_user_ids(db, viewer_id)
    blocked = await privacy.blocked_ids(db, viewer_id)
    settings_map = await people.load_settings_map(db, ids)
    results = []
    for user, profile in rows:
        row = settings_map.get(user.id)
        relation = Relation(user.id in friends, False, user.id in blocked, user.id in shared)
        if row is None or user.id in blocked or not privacy.can_view_profile(relation, row):
            continue
        card = user_card(user, profile)
        card["is_friend"] = user.id in friends
        results.append(card)
        if len(results) >= limit:
            break
    return results


@router.get("/{user_id}")
async def get_user(user_id: int, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "user-profile", 120, 60, subject=str(auth.user.id))
    target = await db.get(User, user_id)
    if target is None or target.status != AccountStatus.ACTIVE.value:
        raise AppError("not_found", 404)
    relation = await privacy.relation(db, auth.user.id, target.id)
    target_settings = await get_settings_row(db, target.id)
    if not privacy.can_view_profile(relation, target_settings):
        raise AppError("not_found", 404)
    profile = await db.get(Profile, target.id)
    class_code = None
    if target.school_class_id is not None and privacy.class_visible_to(relation, target_settings):
        school_class = await db.get(SchoolClass, target.school_class_id)
        class_code = school_class.code if school_class else None
    presence = None
    if privacy.presence_visible_to(relation, target_settings):
        presence = "online" if request.app.state.hub.is_online(target.id) else "offline"
    last_seen = target.last_seen_at if privacy.activity_visible_to(relation, target_settings) else None
    own = target.id == auth.user.id
    mutual = None if own else len((await privacy.friend_ids(db, auth.user.id)) & (await privacy.friend_ids(db, target.id)))
    relation_payload = None
    if not own:
        relation_payload = {
            "friends": relation.friends,
            "blocked": relation.blocked_by_viewer,
            "shares_server": relation.shares_server,
            "pending": await pending_direction(db, auth.user.id, target.id),
        }
    payload = user_profile(target, profile, class_code=class_code, presence=presence, last_seen=last_seen, mutual_friends=mutual, relation=relation_payload)
    payload["shared_servers"] = [] if own else await shared_servers(db, auth.user.id, target.id)
    return payload
