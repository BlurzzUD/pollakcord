from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import AppError
from ...models import Block, FriendRequest, Friendship, Profile, SchoolClass, User, UserSettings
from ...models.enums import AccountStatus, ClassVisibility, FriendRequestPolicy, NotificationType
from ...realtime.outbox import Outbox
from ...security.ratelimit import enforce
from ...services import people, privacy
from ...services.notifications import notify
from ...services.privacy import ordered
from ...services.serializers import iso, sid, user_card
from ..deps import Auth, get_db, get_outbox, require_auth

router = APIRouter(tags=["friends"])


class FriendRequestBody(BaseModel):
    username: str | None = Field(default=None, max_length=64)
    user_id: str | None = Field(default=None, max_length=24)


async def make_friends(db: AsyncSession, a: int, b: int) -> None:
    low, high = ordered(a, b)
    exists = (await db.execute(select(Friendship.id).where(Friendship.user_low_id == low, Friendship.user_high_id == high))).first()
    if not exists:
        db.add(Friendship(user_low_id=low, user_high_id=high))
    await db.execute(
        delete(FriendRequest).where(
            or_(and_(FriendRequest.sender_id == a, FriendRequest.recipient_id == b), and_(FriendRequest.sender_id == b, FriendRequest.recipient_id == a))
        )
    )


@router.get("/friends")
async def list_friends(request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    ids = await privacy.friend_ids(db, auth.user.id)
    cards = await people.load_cards(db, ids)
    presence = await people.presence_map(db, request.app.state.hub, auth.user.id, ids)
    result = [{**card, "presence": presence.get(uid)} for uid, card in cards.items()]
    result.sort(key=lambda c: (c["presence"] != "online", c["display_name"].lower()))
    return result


@router.get("/friends/requests")
async def list_requests(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        await db.execute(
            select(FriendRequest).where(or_(FriendRequest.sender_id == auth.user.id, FriendRequest.recipient_id == auth.user.id)).order_by(FriendRequest.id.desc())
        )
    ).scalars().all()
    cards = await people.load_cards(db, {r.sender_id for r in rows} | {r.recipient_id for r in rows})
    incoming, outgoing = [], []
    for row in rows:
        other = row.sender_id if row.recipient_id == auth.user.id else row.recipient_id
        entry = {"id": sid(row.id), "user": cards.get(other), "created_at": iso(row.created_at)}
        (incoming if row.recipient_id == auth.user.id else outgoing).append(entry)
    return {"incoming": incoming, "outgoing": outgoing}


async def same_visible_class(db: AsyncSession, viewer: User, target: User, target_settings: UserSettings) -> bool:
    if viewer.school_class_id is None or viewer.school_class_id != target.school_class_id:
        return False
    viewer_settings = await privacy.get_settings_row(db, viewer.id)
    return (
        viewer_settings.class_visibility != ClassVisibility.HIDDEN.value
        and target_settings.class_visibility != ClassVisibility.HIDDEN.value
    )


@router.post("/friends/requests")
async def send_request(
    body: FriendRequestBody,
    request: Request,
    auth: Auth = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    outbox: Outbox = Depends(get_outbox),
) -> dict[str, str]:
    enforce(request, "friend-request", 25, 3600, subject=str(auth.user.id))
    if body.username:
        target = (await db.execute(select(User).where(User.username_lower == body.username.strip().lower().lstrip("@")))).scalar_one_or_none()
    elif body.user_id and body.user_id.isdigit():
        target = await db.get(User, int(body.user_id))
    else:
        raise AppError("validation_error", 422)
    generic = {"status": "sent"}
    if target is not None and target.id == auth.user.id:
        raise AppError("cannot_friend_self", 422)
    if target is None or target.status != AccountStatus.ACTIVE.value:
        return generic
    relation = await privacy.relation(db, auth.user.id, target.id)
    if relation.friends:
        raise AppError("already_friends", 409)
    target_settings = await privacy.get_settings_row(db, target.id)
    classmates = await same_visible_class(db, auth.user, target, target_settings)
    reverse = (await db.execute(select(FriendRequest).where(FriendRequest.sender_id == target.id, FriendRequest.recipient_id == auth.user.id))).scalar_one_or_none()
    if reverse is not None and not relation.blocked:
        await accept_request(db, outbox, reverse)
        await db.commit()
        await outbox.flush()
        return {"status": "accepted"}
    if not privacy.can_send_friend_request(relation, target_settings, classmates):
        return generic
    existing = (await db.execute(select(FriendRequest.id).where(FriendRequest.sender_id == auth.user.id, FriendRequest.recipient_id == target.id))).first()
    if existing:
        return generic
    row = FriendRequest(sender_id=auth.user.id, recipient_id=target.id)
    db.add(row)
    await db.flush()
    cards = await people.load_cards(db, {auth.user.id})
    await notify(db, outbox, target.id, NotificationType.FRIEND_REQUEST, {"request_id": sid(row.id), "user": cards[auth.user.id]})
    outbox.user(target.id, "friend.request", {"id": sid(row.id), "user": cards[auth.user.id], "created_at": iso(row.created_at)})
    await db.commit()
    await outbox.flush()
    return generic


async def accept_request(db: AsyncSession, outbox: Outbox, row: FriendRequest) -> None:
    sender_id, recipient_id = row.sender_id, row.recipient_id
    await make_friends(db, sender_id, recipient_id)
    cards = await people.load_cards(db, {sender_id, recipient_id})
    await notify(db, outbox, sender_id, NotificationType.FRIEND_ACCEPTED, {"user": cards[recipient_id]})
    outbox.user(sender_id, "friend.added", {"user": cards[recipient_id]})
    outbox.user(recipient_id, "friend.added", {"user": cards[sender_id]})


async def own_incoming(db: AsyncSession, request_id: int, user_id: int) -> FriendRequest:
    row = await db.get(FriendRequest, request_id)
    if row is None or row.recipient_id != user_id:
        raise AppError("not_found", 404)
    return row


@router.post("/friends/requests/{request_id}/accept")
async def accept(request_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    row = await own_incoming(db, request_id, auth.user.id)
    relation = await privacy.relation(db, auth.user.id, row.sender_id)
    if relation.blocked:
        raise AppError("not_found", 404)
    await accept_request(db, outbox, row)
    await db.commit()
    await outbox.flush()
    return {"status": "accepted"}


@router.post("/friends/requests/{request_id}/decline")
async def decline(request_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    row = await own_incoming(db, request_id, auth.user.id)
    await db.delete(row)
    await db.commit()
    return {"status": "declined"}


@router.delete("/friends/requests/{request_id}")
async def cancel(request_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    row = await db.get(FriendRequest, request_id)
    if row is None or row.sender_id != auth.user.id:
        raise AppError("not_found", 404)
    await db.delete(row)
    await db.commit()
    return {"status": "cancelled"}


async def remove_friendship(db: AsyncSession, a: int, b: int) -> None:
    low, high = ordered(a, b)
    await db.execute(delete(Friendship).where(Friendship.user_low_id == low, Friendship.user_high_id == high))
    await db.execute(
        delete(FriendRequest).where(
            or_(and_(FriendRequest.sender_id == a, FriendRequest.recipient_id == b), and_(FriendRequest.sender_id == b, FriendRequest.recipient_id == a))
        )
    )


@router.delete("/friends/{user_id}")
async def remove_friend(user_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    relation = await privacy.relation(db, auth.user.id, user_id)
    if not relation.friends:
        raise AppError("not_found", 404)
    await remove_friendship(db, auth.user.id, user_id)
    await db.commit()
    outbox.user(user_id, "friend.removed", {"user_id": sid(auth.user.id)})
    outbox.user(auth.user.id, "friend.removed", {"user_id": sid(user_id)})
    await outbox.flush()
    return {"status": "removed"}


@router.get("/friends/suggestions")
async def suggestions(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    me = auth.user
    my_settings = await privacy.get_settings_row(db, me.id)
    if me.school_class_id is None or my_settings.class_visibility == ClassVisibility.HIDDEN.value:
        return []
    excluded = (await privacy.friend_ids(db, me.id)) | (await privacy.blocked_ids(db, me.id)) | {me.id}
    pending = (
        await db.execute(select(FriendRequest.sender_id, FriendRequest.recipient_id).where(or_(FriendRequest.sender_id == me.id, FriendRequest.recipient_id == me.id)))
    ).all()
    for sender, recipient in pending:
        excluded.add(sender)
        excluded.add(recipient)
    statement = (
        select(User, Profile)
        .join(UserSettings, UserSettings.user_id == User.id)
        .outerjoin(Profile, Profile.user_id == User.id)
        .where(
            User.school_class_id == me.school_class_id,
            User.status == AccountStatus.ACTIVE.value,
            User.id.notin_(excluded),
            UserSettings.class_visibility != ClassVisibility.HIDDEN.value,
            UserSettings.friend_requests != FriendRequestPolicy.NOBODY.value,
        )
        .limit(60)
    )
    rows = (await db.execute(statement)).all()
    school_class = await db.get(SchoolClass, me.school_class_id)
    my_friends = await privacy.friend_ids(db, me.id)
    results = []
    for user, profile in rows:
        mutual = len(my_friends & await privacy.friend_ids(db, user.id))
        card = user_card(user, profile)
        card.update({"mutual_friends": mutual, "class_code": school_class.code if school_class else None})
        results.append(card)
    results.sort(key=lambda c: (-c["mutual_friends"], c["display_name"].lower()))
    return results[:20]


@router.get("/blocks")
async def list_blocks(auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> list[dict]:
    ids = list((await db.execute(select(Block.blocked_id).where(Block.blocker_id == auth.user.id))).scalars())
    cards = await people.load_cards(db, ids)
    return list(cards.values())


@router.put("/blocks/{user_id}")
async def block(user_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict[str, str]:
    if user_id == auth.user.id:
        raise AppError("cannot_block_self", 422)
    target = await db.get(User, user_id)
    if target is None:
        raise AppError("not_found", 404)
    if await db.get(Block, (auth.user.id, user_id)) is None:
        db.add(Block(blocker_id=auth.user.id, blocked_id=user_id))
    await remove_friendship(db, auth.user.id, user_id)
    await db.commit()
    outbox.user(auth.user.id, "friend.removed", {"user_id": sid(user_id)})
    outbox.user(user_id, "friend.removed", {"user_id": sid(auth.user.id)})
    await outbox.flush()
    return {"status": "blocked"}


@router.delete("/blocks/{user_id}")
async def unblock(user_id: int, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    row = await db.get(Block, (auth.user.id, user_id))
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"status": "unblocked"}
