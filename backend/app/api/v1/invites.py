from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.types import utcnow
from ...errors import AppError
from ...models import Invite, Server, ServerMember
from ...realtime.outbox import Outbox
from ...security.ratelimit import enforce
from ...services import people
from ...services import servers as server_service
from ...services.serializers import media_url, sid
from ..deps import Auth, get_db, get_outbox, require_auth

router = APIRouter(prefix="/invites", tags=["invites"])


async def usable_invite(db: AsyncSession, code: str) -> tuple[Invite, Server]:
    invite = (await db.execute(select(Invite).where(Invite.code == code[:24]))).scalar_one_or_none()
    if invite is None or invite.revoked_at is not None:
        raise AppError("invite_invalid", 404)
    if invite.expires_at is not None and invite.expires_at <= utcnow():
        raise AppError("invite_invalid", 404)
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        raise AppError("invite_invalid", 404)
    server = await db.get(Server, invite.server_id)
    if server is None:
        raise AppError("invite_invalid", 404)
    return invite, server


@router.get("/{code}")
async def preview(code: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    enforce(request, "invite-preview", 40, 60)
    _, server = await usable_invite(db, code)
    return {
        "server": {
            "id": sid(server.id),
            "name": server.name,
            "description": server.description,
            "icon_url": media_url("server_icon", server.icon_key),
            "member_count": await server_service.member_count(db, server.id),
        }
    }


@router.post("/{code}/accept")
async def accept(code: str, request: Request, auth: Auth = Depends(require_auth), db: AsyncSession = Depends(get_db), outbox: Outbox = Depends(get_outbox)) -> dict:
    enforce(request, "invite-accept", 20, 600, subject=str(auth.user.id))
    invite, server = await usable_invite(db, code)
    if await db.get(ServerMember, (server.id, auth.user.id)) is not None:
        return {"server_id": sid(server.id), "already_member": True}
    if await server_service.is_banned(db, server.id, auth.user.id):
        raise AppError("banned_from_server", 403)
    await server_service.add_member(db, server.id, auth.user.id)
    if not await server_service.consume_invite(db, invite):
        await db.rollback()
        raise AppError("invite_invalid", 404)
    await db.commit()
    cards = await people.load_cards(db, {auth.user.id})
    request.app.state.hub.subscribe_user(auth.user.id, f"server:{server.id}")
    outbox.topic(f"server:{server.id}", "member.joined", {"server_id": sid(server.id), "user": cards[auth.user.id]}, exclude_user=auth.user.id)
    outbox.user(auth.user.id, "server.joined", {"server_id": sid(server.id)})
    await outbox.flush()
    return {"server_id": sid(server.id), "already_member": False}
