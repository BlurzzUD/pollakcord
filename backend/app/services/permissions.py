from dataclasses import dataclass, field
from enum import IntFlag

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.types import utcnow
from ..errors import AppError
from ..models import Channel, MemberRole, PermissionOverwrite, Role, Server, ServerMember
from ..models.enums import ChannelType, OverwriteScope, OverwriteTarget

OWNER_POSITION = 1 << 30


class Perm(IntFlag):
    VIEW_CHANNEL = 1 << 0
    SEND_MESSAGES = 1 << 1
    READ_MESSAGE_HISTORY = 1 << 2
    ADD_REACTIONS = 1 << 3
    CONNECT = 1 << 4
    SPEAK = 1 << 5
    MUTE_MEMBERS = 1 << 6
    DEAFEN_MEMBERS = 1 << 7
    CREATE_INVITE = 1 << 8
    KICK_MEMBERS = 1 << 9
    BAN_MEMBERS = 1 << 10
    MANAGE_MESSAGES = 1 << 11
    MANAGE_CHANNELS = 1 << 12
    MANAGE_ROLES = 1 << 13
    MANAGE_MEMBERS = 1 << 14
    MANAGE_SERVER = 1 << 15
    VIEW_AUDIT_LOG = 1 << 16
    ADMINISTRATOR = 1 << 17


ALL_PERMISSIONS = int(sum(Perm))
CHANNEL_SCOPED = int(
    Perm.VIEW_CHANNEL
    | Perm.SEND_MESSAGES
    | Perm.READ_MESSAGE_HISTORY
    | Perm.ADD_REACTIONS
    | Perm.CONNECT
    | Perm.SPEAK
    | Perm.MUTE_MEMBERS
    | Perm.DEAFEN_MEMBERS
    | Perm.MANAGE_MESSAGES
    | Perm.CREATE_INVITE
)
MEMBER_DEFAULT = int(
    Perm.VIEW_CHANNEL
    | Perm.SEND_MESSAGES
    | Perm.READ_MESSAGE_HISTORY
    | Perm.ADD_REACTIONS
    | Perm.CONNECT
    | Perm.SPEAK
    | Perm.CREATE_INVITE
)
MODERATOR_DEFAULT = MEMBER_DEFAULT | int(
    Perm.MANAGE_MESSAGES
    | Perm.KICK_MEMBERS
    | Perm.MUTE_MEMBERS
    | Perm.DEAFEN_MEMBERS
    | Perm.MANAGE_MEMBERS
    | Perm.VIEW_AUDIT_LOG
)
ADMINISTRATOR_DEFAULT = ALL_PERMISSIONS
TIMEOUT_ALLOWED = int(Perm.VIEW_CHANNEL | Perm.READ_MESSAGE_HISTORY)
PERMISSION_NAMES = {perm.name.lower(): int(perm) for perm in Perm}


def names_to_bits(names: list[str]) -> int:
    bits = 0
    for name in names:
        key = name.lower()
        if key not in PERMISSION_NAMES:
            raise AppError("invalid_permission", 422, params={"permission": name[:40]})
        bits |= PERMISSION_NAMES[key]
    return bits


def bits_to_names(bits: int) -> list[str]:
    return [name for name, value in PERMISSION_NAMES.items() if bits & value]


@dataclass
class ServerContext:
    server: Server
    member: ServerMember
    roles: dict[int, Role]
    member_role_ids: set[int]
    overwrites: list[PermissionOverwrite] = field(default_factory=list)

    @property
    def user_id(self) -> int:
        return self.member.user_id

    @property
    def is_owner(self) -> bool:
        return self.server.owner_id == self.member.user_id

    @property
    def default_role(self) -> Role | None:
        return next((r for r in self.roles.values() if r.is_default), None)

    @property
    def base(self) -> int:
        if self.is_owner:
            return ALL_PERMISSIONS
        bits = 0
        for role_id in self.member_role_ids:
            role = self.roles.get(role_id)
            if role is not None:
                bits |= role.permissions
        default = self.default_role
        if default is not None:
            bits |= default.permissions
        if bits & Perm.ADMINISTRATOR:
            return ALL_PERMISSIONS
        return bits

    @property
    def top_position(self) -> int:
        if self.is_owner:
            return OWNER_POSITION
        positions = [self.roles[r].position for r in self.member_role_ids if r in self.roles]
        return max(positions, default=0)

    def can(self, perm: Perm) -> bool:
        return bool(self.base & perm)

    def require(self, perm: Perm) -> None:
        if not self.can(perm):
            raise AppError("missing_permission", 403, params={"permission": perm.name.lower()})

    def outranks(self, other: "ServerContext") -> bool:
        if other.is_owner:
            return False
        return self.is_owner or self.top_position > other.top_position

    def outranks_role(self, role: Role) -> bool:
        return self.is_owner or role.position < self.top_position

    def channel_permissions(self, channel: Channel) -> int:
        base = self.base
        if base & Perm.ADMINISTRATOR or self.is_owner:
            return ALL_PERMISSIONS
        perms = base
        scopes: list[tuple[str, int]] = []
        if channel.category_id is not None:
            scopes.append((OverwriteScope.CATEGORY.value, channel.category_id))
        scopes.append((OverwriteScope.CHANNEL.value, channel.id))
        default = self.default_role
        for scope_type, scope_id in scopes:
            relevant = [o for o in self.overwrites if o.scope_type == scope_type and o.scope_id == scope_id]
            for overwrite in relevant:
                if overwrite.target_type == OverwriteTarget.ROLE.value and default and overwrite.target_id == default.id:
                    perms = (perms & ~overwrite.deny) | overwrite.allow
            role_allow = role_deny = 0
            for overwrite in relevant:
                if overwrite.target_type == OverwriteTarget.ROLE.value and overwrite.target_id in self.member_role_ids:
                    role_allow |= overwrite.allow
                    role_deny |= overwrite.deny
            perms = (perms & ~role_deny) | role_allow
            for overwrite in relevant:
                if overwrite.target_type == OverwriteTarget.MEMBER.value and overwrite.target_id == self.user_id:
                    perms = (perms & ~overwrite.deny) | overwrite.allow
        if not perms & Perm.VIEW_CHANNEL:
            return 0
        if self.member.timeout_until is not None and self.member.timeout_until > utcnow():
            perms &= TIMEOUT_ALLOWED
        return perms

    def can_in(self, channel: Channel, perm: Perm) -> bool:
        return bool(self.channel_permissions(channel) & perm)

    def require_in(self, channel: Channel, perm: Perm) -> None:
        if not self.can_in(channel, perm):
            if not self.can_in(channel, Perm.VIEW_CHANNEL):
                raise AppError("not_found", 404)
            raise AppError("missing_permission", 403, params={"permission": perm.name.lower()})

    def visible_channel(self, channel: Channel) -> bool:
        return self.can_in(channel, Perm.VIEW_CHANNEL)

    def is_text(self, channel: Channel) -> bool:
        return channel.type == ChannelType.TEXT.value


async def load_context(db: AsyncSession, server_id: int, user_id: int) -> ServerContext | None:
    server = await db.get(Server, server_id)
    member = await db.get(ServerMember, (server_id, user_id))
    if server is None or member is None:
        return None
    roles = {r.id: r for r in (await db.execute(select(Role).where(Role.server_id == server_id))).scalars()}
    member_role_ids = set(
        (await db.execute(select(MemberRole.role_id).where(MemberRole.server_id == server_id, MemberRole.user_id == user_id))).scalars()
    )
    overwrites = list((await db.execute(select(PermissionOverwrite).where(PermissionOverwrite.server_id == server_id))).scalars())
    return ServerContext(server, member, roles, member_role_ids, overwrites)


async def require_context(db: AsyncSession, server_id: int, user_id: int) -> ServerContext:
    context = await load_context(db, server_id, user_id)
    if context is None:
        raise AppError("not_found", 404)
    return context


async def load_channel_context(db: AsyncSession, channel_id: int, user_id: int) -> tuple[Channel, ServerContext]:
    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise AppError("not_found", 404)
    context = await require_context(db, channel.server_id, user_id)
    if not context.visible_channel(channel):
        raise AppError("not_found", 404)
    return channel, context
