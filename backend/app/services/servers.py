import secrets
import string
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.types import utcnow
from ..errors import AppError
from ..i18n import translate
from ..models import Ban, Category, Channel, Invite, MemberRole, Role, Server, ServerMember, User
from ..models.enums import ChannelType
from .permissions import ADMINISTRATOR_DEFAULT, MEMBER_DEFAULT, MODERATOR_DEFAULT

INVITE_ALPHABET = string.ascii_letters + string.digits
INVITE_LENGTH = 10
MAX_OWNED_SERVERS = 10
MAX_JOINED_SERVERS = 50
MAX_MEMBERS = 2000
MAX_ROLES = 50
MAX_CHANNELS = 200
MAX_CATEGORIES = 50
MAX_TIMEOUT_MINUTES = 28 * 24 * 60
BUILTIN_ROLE_POSITIONS = {"member": 0, "moderator": 100, "administrator": 200}
CUSTOM_ROLE_DEFAULT_POSITION = 50


def generate_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))


async def new_invite(db: AsyncSession, server_id: int, creator_id: int | None, max_uses: int | None, expires_in_hours: int | None) -> Invite:
    for _ in range(5):
        code = generate_invite_code()
        taken = (await db.execute(select(Invite.id).where(Invite.code == code))).first()
        if not taken:
            invite = Invite(
                code=code,
                server_id=server_id,
                creator_id=creator_id,
                max_uses=max_uses,
                expires_at=utcnow() + timedelta(hours=expires_in_hours) if expires_in_hours else None,
            )
            db.add(invite)
            await db.flush()
            return invite
    raise AppError("internal_error", 500)


async def membership_counts(db: AsyncSession, user_id: int) -> tuple[int, int]:
    joined = (await db.execute(select(func.count()).select_from(ServerMember).where(ServerMember.user_id == user_id))).scalar_one()
    owned = (await db.execute(select(func.count()).select_from(Server).where(Server.owner_id == user_id))).scalar_one()
    return joined, owned


async def create_server(db: AsyncSession, owner: User, name: str, description: str, language: str) -> tuple[Server, Invite]:
    joined, owned = await membership_counts(db, owner.id)
    if owned >= MAX_OWNED_SERVERS or joined >= MAX_JOINED_SERVERS:
        raise AppError("server_limit_reached", 409)
    server = Server(name=name, description=description, owner_id=owner.id)
    db.add(server)
    await db.flush()
    t = lambda key: translate("server", key, language)
    db.add(Role(server_id=server.id, name=t("role_member"), position=0, permissions=MEMBER_DEFAULT, is_default=True, kind="member"))
    db.add(Role(server_id=server.id, name=t("role_moderator"), position=100, permissions=MODERATOR_DEFAULT, kind="moderator", color="#2f8f6b"))
    db.add(Role(server_id=server.id, name=t("role_administrator"), position=200, permissions=ADMINISTRATOR_DEFAULT, kind="administrator", color="#c2410c"))
    db.add(ServerMember(server_id=server.id, user_id=owner.id))
    text_category = Category(server_id=server.id, name=t("category_text"), position=0)
    voice_category = Category(server_id=server.id, name=t("category_voice"), position=1)
    db.add_all([text_category, voice_category])
    await db.flush()
    db.add(Channel(server_id=server.id, category_id=text_category.id, type=ChannelType.TEXT.value, name=t("channel_general"), position=0, topic=t("channel_general_topic")))
    db.add(Channel(server_id=server.id, category_id=voice_category.id, type=ChannelType.VOICE.value, name=t("channel_lounge"), position=0, user_limit=8))
    invite = await new_invite(db, server.id, owner.id, None, None)
    return server, invite


async def server_channel_ids(db: AsyncSession, server_id: int) -> list[int]:
    return list((await db.execute(select(Channel.id).where(Channel.server_id == server_id))).scalars())


async def member_count(db: AsyncSession, server_id: int) -> int:
    return (await db.execute(select(func.count()).select_from(ServerMember).where(ServerMember.server_id == server_id))).scalar_one()


async def add_member(db: AsyncSession, server_id: int, user_id: int) -> None:
    if await member_count(db, server_id) >= MAX_MEMBERS:
        raise AppError("server_full", 409)
    joined, _ = await membership_counts(db, user_id)
    if joined >= MAX_JOINED_SERVERS:
        raise AppError("server_limit_reached", 409)
    db.add(ServerMember(server_id=server_id, user_id=user_id))


async def remove_member(db: AsyncSession, server_id: int, user_id: int) -> None:
    await db.execute(delete(MemberRole).where(MemberRole.server_id == server_id, MemberRole.user_id == user_id))
    await db.execute(delete(ServerMember).where(ServerMember.server_id == server_id, ServerMember.user_id == user_id))


async def consume_invite(db: AsyncSession, invite: Invite) -> bool:
    now = utcnow()
    result = await db.execute(
        update(Invite)
        .where(
            Invite.id == invite.id,
            Invite.revoked_at.is_(None),
            (Invite.max_uses.is_(None)) | (Invite.uses < Invite.max_uses),
            (Invite.expires_at.is_(None)) | (Invite.expires_at > now),
        )
        .values(uses=Invite.uses + 1)
    )
    return result.rowcount == 1


async def is_banned(db: AsyncSession, server_id: int, user_id: int) -> bool:
    return await db.get(Ban, (server_id, user_id)) is not None


def normalize_label(raw: str, *, lowercase: bool, limit: int = 60) -> str:
    import re
    import unicodedata

    text = re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw)).strip()
    if lowercase:
        text = text.lower().replace(" ", "-")
    if not 1 <= len(text) <= limit or any(unicodedata.category(ch).startswith("C") for ch in text):
        raise AppError("name_invalid", 422, params={"max": limit})
    return text
