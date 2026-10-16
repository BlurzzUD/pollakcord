import secrets
from datetime import timedelta

from fastapi import Request
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.types import utcnow
from ..errors import AppError
from ..models import AuthMethod, Ban, BotApplication, BotCommand, BotInstall, BotInteraction, Channel, MemberRole, PermissionOverwrite, Profile, Role, ServerMember, User, UserSettings
from ..models.enums import AccountStatus, AuditAction, AuthMethodKind
from ..realtime.outbox import Outbox
from ..security.bots import MAX_BOTS_PER_OWNER
from ..security.ratelimit import enforce
from ..security.sessions import hash_token
from . import accounts, audit
from .permissions import Perm, bits_to_names, names_to_bits, require_context
from .serializers import iso, sid, user_profile

DEFAULT_BOT_PERMISSIONS = ["view_channel", "read_message_history", "send_messages"]
BOT_INSTALL_PERMISSIONS = int(Perm.VIEW_CHANNEL | Perm.READ_MESSAGE_HISTORY | Perm.SEND_MESSAGES | Perm.ADD_REACTIONS | Perm.CREATE_INVITE | Perm.KICK_MEMBERS | Perm.BAN_MEMBERS | Perm.MANAGE_MESSAGES | Perm.MANAGE_CHANNELS | Perm.MANAGE_ROLES | Perm.MANAGE_MEMBERS | Perm.MANAGE_SERVER | Perm.VIEW_AUDIT_LOG)


async def password_gate(request: Request, db: AsyncSession, owner: User, password: str) -> None:
    enforce(request, "bot-step-up", 10, 600, subject=str(owner.id))
    method = (await db.execute(select(AuthMethod).where(AuthMethod.user_id == owner.id).with_for_update())).scalar_one_or_none()
    if owner.is_bot or method is None or method.method != AuthMethodKind.PASSWORD.value or not method.password_hash:
        raise AppError("bot_password_required", 403)
    accounts.ensure_not_locked(method)
    valid, upgraded = await request.app.state.passwords.verify(method.password_hash, password)
    if not valid:
        await accounts.apply_lockout(db, method, request.app.state.settings)
        await db.commit()
        raise AppError("invalid_credentials", 401)
    if upgraded:
        method.password_hash = upgraded
    method.failed_attempts = 0
    method.locked_until = None


async def owned(db: AsyncSession, owner_id: int, bot_id: int, lock: bool = False) -> BotApplication:
    statement = select(BotApplication).where(BotApplication.bot_user_id == bot_id, BotApplication.owner_id == owner_id, BotApplication.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    application = (await db.execute(statement)).scalar_one_or_none()
    if application is None:
        raise AppError("not_found", 404)
    return application


async def application_payload(db: AsyncSession, application: BotApplication) -> dict:
    user = await db.get(User, application.bot_user_id)
    profile = await db.get(Profile, application.bot_user_id)
    card = user_profile(user, profile, class_code=None, presence=None, last_seen=None, mutual_friends=None, relation=None)
    return {"user": card, "bot_id": sid(user.id), "created_at": iso(application.created_at), "install_code": sid(user.id)}


def mint_token(application: BotApplication) -> str:
    token = "pcbot_" + secrets.token_urlsafe(48)
    application.token_hash = hash_token(token)
    return token


async def create_bot(db: AsyncSession, request: Request, owner: User, username: str, display_name: str) -> tuple[BotApplication, str]:
    await db.execute(select(User.id).where(User.id == owner.id).with_for_update())
    total = (await db.execute(select(func.count()).select_from(BotApplication).where(BotApplication.owner_id == owner.id, BotApplication.deleted_at.is_(None)))).scalar_one()
    if total >= MAX_BOTS_PER_OWNER:
        raise AppError("bot_limit_reached", 409, params={"max": MAX_BOTS_PER_OWNER})
    username = accounts.normalize_username(username)
    if await accounts.username_taken(db, username):
        raise AppError("username_taken", 409)
    user = User(username=username, username_lower=username, display_name=accounts.normalize_display_name(display_name), is_bot=True, status=AccountStatus.ACTIVE.value, platform_role="user", school_class_id=None)
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id))
    db.add(UserSettings(user_id=user.id, friend_requests="nobody", direct_messages="friends", voice_calls="nobody", class_visibility="hidden", class_prompt_answered=True, online_status="nobody"))
    application = BotApplication(bot_user_id=user.id, owner_id=owner.id)
    token = mint_token(application)
    db.add(application)
    audit.record(db, AuditAction.BOT_CREATE, actor_id=owner.id, target_type="bot", target_id=user.id)
    await db.flush()
    return application, token


async def integration_context(db: AsyncSession, server_id: int, human_id: int):
    context = await require_context(db, server_id, human_id)
    if not context.is_owner and not context.can(Perm.ADMINISTRATOR):
        raise AppError("bot_install_forbidden", 403)
    return context


async def install_bot(db: AsyncSession, server_id: int, bot_id: int, human_id: int, permissions: list[str]) -> BotInstall:
    context = await integration_context(db, server_id, human_id)
    if not 0 < bot_id < 2**63:
        raise AppError("validation_error", 422)
    application = (await db.execute(select(BotApplication).where(BotApplication.bot_user_id == bot_id, BotApplication.deleted_at.is_(None)).with_for_update())).scalar_one_or_none()
    user = await db.get(User, bot_id)
    owner = await db.get(User, application.owner_id) if application else None
    if application is None or user is None or not user.is_bot or user.status != "active" or owner is None or owner.status != "active" or owner.is_bot:
        raise AppError("not_found", 404)
    if await db.get(Ban, (server_id, bot_id)) is not None:
        raise AppError("not_found", 404)
    if await db.get(ServerMember, (server_id, bot_id)) is not None:
        raise AppError("bot_already_installed", 409)
    bits = names_to_bits(permissions)
    if bits & ~BOT_INSTALL_PERMISSIONS:
        raise AppError("invalid_permission", 422, params={"permission": "bot"})
    from .servers import MAX_MEMBERS, MAX_ROLES, member_count

    if await member_count(db, server_id) >= MAX_MEMBERS or len(context.roles) >= MAX_ROLES:
        raise AppError("bot_install_limit", 409)
    role = Role(server_id=server_id, name=user.display_name, position=1, permissions=bits, kind="bot")
    db.add(role)
    db.add(ServerMember(server_id=server_id, user_id=bot_id))
    await db.flush()
    db.add(MemberRole(server_id=server_id, user_id=bot_id, role_id=role.id))
    install = BotInstall(server_id=server_id, bot_user_id=bot_id, role_id=role.id, permissions=bits, installed_by=human_id)
    db.add(install)
    audit.record(db, AuditAction.BOT_INSTALL, actor_id=human_id, server_id=server_id, target_type="bot", target_id=bot_id)
    await db.flush()
    return install


async def remove_install(db: AsyncSession, install: BotInstall, actor_id: int, outbox: Outbox) -> None:
    server_id, bot_id, role_id = install.server_id, install.bot_user_id, install.role_id
    await db.execute(update(BotInteraction).where(BotInteraction.bot_user_id == bot_id, BotInteraction.channel_id.in_(select(Channel.id).where(Channel.server_id == server_id)), BotInteraction.status == "pending").values(status="expired"))
    await db.execute(delete(PermissionOverwrite).where(PermissionOverwrite.server_id == server_id, or_(and_(PermissionOverwrite.target_type == "member", PermissionOverwrite.target_id == bot_id), and_(PermissionOverwrite.target_type == "role", PermissionOverwrite.target_id == role_id))))
    await db.execute(delete(MemberRole).where(MemberRole.server_id == server_id, MemberRole.user_id == bot_id))
    await db.delete(install)
    await db.flush()
    member = await db.get(ServerMember, (server_id, bot_id))
    if member is not None:
        await db.delete(member)
    if role_id is not None:
        role = await db.get(Role, role_id)
        if role is not None and role.kind == "bot":
            await db.delete(role)
    audit.record(db, AuditAction.BOT_REMOVE, actor_id=actor_id, server_id=server_id, target_type="bot", target_id=bot_id)
    integration_changed(outbox, server_id, bot_id, removed=True)


def integration_changed(outbox: Outbox, server_id: int, bot_id: int, removed: bool = False) -> None:
    outbox.topic(f"server:{server_id}", "member.left" if removed else "member.joined", {"server_id": sid(server_id), "user_id": sid(bot_id)})
    outbox.topic(f"server:{server_id}", "role.changed", {"server_id": sid(server_id)})
    outbox.revalidate_server(server_id)


async def delete_bot(db: AsyncSession, application: BotApplication, outbox: Outbox) -> None:
    installs = list((await db.execute(select(BotInstall).where(BotInstall.bot_user_id == application.bot_user_id))).scalars())
    for install in installs:
        await remove_install(db, install, application.owner_id, outbox)
    await db.execute(delete(BotCommand).where(BotCommand.bot_user_id == application.bot_user_id))
    await db.execute(delete(BotInteraction).where(BotInteraction.bot_user_id == application.bot_user_id))
    application.token_hash = None
    application.deleted_at = utcnow()
    user = await db.get(User, application.bot_user_id)
    user.status = AccountStatus.SUSPENDED.value
    audit.record(db, AuditAction.BOT_DELETE, actor_id=application.owner_id, target_type="bot", target_id=application.bot_user_id)


async def prune_interactions(db: AsyncSession) -> None:
    await db.execute(delete(BotInteraction).where(BotInteraction.expires_at < utcnow() - timedelta(days=1)))
