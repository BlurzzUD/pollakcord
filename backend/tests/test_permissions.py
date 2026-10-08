from datetime import timedelta

import pytest

from app.db.types import utcnow
from app.errors import AppError
from app.models import Channel, PermissionOverwrite, Role, Server, ServerMember
from app.services.permissions import (
    ADMINISTRATOR_DEFAULT,
    ALL_PERMISSIONS,
    MEMBER_DEFAULT,
    MODERATOR_DEFAULT,
    Perm,
    ServerContext,
    bits_to_names,
    names_to_bits,
)

SERVER_ID, OWNER_ID = 1, 100
MEMBER_ROLE, MOD_ROLE, ADMIN_ROLE = 10, 11, 12


def roles():
    return {
        MEMBER_ROLE: Role(id=MEMBER_ROLE, server_id=SERVER_ID, name="Tag", position=0, permissions=MEMBER_DEFAULT, is_default=True),
        MOD_ROLE: Role(id=MOD_ROLE, server_id=SERVER_ID, name="Mod", position=100, permissions=MODERATOR_DEFAULT),
        ADMIN_ROLE: Role(id=ADMIN_ROLE, server_id=SERVER_ID, name="Admin", position=200, permissions=ADMINISTRATOR_DEFAULT),
    }


def context(user_id, role_ids=(), overwrites=(), timeout=None):
    server = Server(id=SERVER_ID, name="s", owner_id=OWNER_ID)
    member = ServerMember(server_id=SERVER_ID, user_id=user_id, timeout_until=timeout)
    return ServerContext(server, member, roles(), set(role_ids), list(overwrites))


def channel(channel_id=1, category_id=None, kind="text"):
    return Channel(id=channel_id, server_id=SERVER_ID, category_id=category_id, type=kind, name="c")


def overwrite(scope, scope_id, target_type, target_id, allow=0, deny=0):
    return PermissionOverwrite(server_id=SERVER_ID, scope_type=scope, scope_id=scope_id, target_type=target_type, target_id=target_id, allow=allow, deny=deny)


def test_owner_has_every_permission_and_outranks_everyone():
    owner = context(OWNER_ID)
    assert owner.base == ALL_PERMISSIONS
    assert owner.outranks(context(200, [ADMIN_ROLE]))
    assert not context(200, [ADMIN_ROLE]).outranks(owner)


def test_members_get_the_default_role_without_assignment():
    member = context(200)
    assert member.can(Perm.SEND_MESSAGES) and member.can(Perm.CONNECT)
    assert not member.can(Perm.KICK_MEMBERS) and not member.can(Perm.MANAGE_SERVER)


def test_moderators_can_moderate_but_not_manage_the_server():
    mod = context(201, [MOD_ROLE])
    assert mod.can(Perm.KICK_MEMBERS) and mod.can(Perm.MANAGE_MESSAGES) and mod.can(Perm.VIEW_AUDIT_LOG)
    assert not mod.can(Perm.BAN_MEMBERS) and not mod.can(Perm.MANAGE_ROLES) and not mod.can(Perm.MANAGE_SERVER)


def test_administrator_flag_grants_everything_and_bypasses_overwrites():
    admin = context(202, [ADMIN_ROLE], [overwrite("channel", 1, "role", MEMBER_ROLE, deny=int(Perm.VIEW_CHANNEL))])
    assert admin.base == ALL_PERMISSIONS
    assert admin.can_in(channel(), Perm.VIEW_CHANNEL)


def test_role_hierarchy():
    admin, mod, member = context(202, [ADMIN_ROLE]), context(201, [MOD_ROLE]), context(200)
    assert admin.outranks(mod) and mod.outranks(member) and admin.outranks(member)
    assert not member.outranks(mod) and not mod.outranks(admin)
    assert not mod.outranks(context(203, [MOD_ROLE]))
    assert admin.outranks_role(roles()[MOD_ROLE]) and not mod.outranks_role(roles()[MOD_ROLE])


def test_denying_view_for_everyone_hides_the_channel():
    hidden = [overwrite("channel", 1, "role", MEMBER_ROLE, deny=int(Perm.VIEW_CHANNEL))]
    assert not context(200, overwrites=hidden).visible_channel(channel())
    assert context(200, overwrites=hidden).channel_permissions(channel()) == 0
    assert context(200, overwrites=hidden).visible_channel(channel(2))


def test_role_overwrite_can_reopen_a_hidden_channel():
    rules = [
        overwrite("channel", 1, "role", MEMBER_ROLE, deny=int(Perm.VIEW_CHANNEL)),
        overwrite("channel", 1, "role", MOD_ROLE, allow=int(Perm.VIEW_CHANNEL)),
    ]
    assert context(201, [MOD_ROLE], rules).visible_channel(channel())
    assert not context(200, overwrites=rules).visible_channel(channel())


def test_member_overwrite_beats_role_overwrites():
    rules = [
        overwrite("channel", 1, "role", MEMBER_ROLE, deny=int(Perm.SEND_MESSAGES)),
        overwrite("channel", 1, "member", 200, allow=int(Perm.SEND_MESSAGES)),
    ]
    assert context(200, overwrites=rules).can_in(channel(), Perm.SEND_MESSAGES)
    assert not context(201, overwrites=rules).can_in(channel(), Perm.SEND_MESSAGES)


def test_category_overwrites_are_inherited_and_channel_overwrites_win():
    category_rules = [overwrite("category", 5, "role", MEMBER_ROLE, deny=int(Perm.SEND_MESSAGES))]
    inside = channel(1, category_id=5)
    assert not context(200, overwrites=category_rules).can_in(inside, Perm.SEND_MESSAGES)
    assert context(200, overwrites=category_rules).can_in(channel(2), Perm.SEND_MESSAGES)
    reopened = category_rules + [overwrite("channel", 1, "role", MEMBER_ROLE, allow=int(Perm.SEND_MESSAGES))]
    assert context(200, overwrites=reopened).can_in(inside, Perm.SEND_MESSAGES)


def test_timeouts_leave_read_only_access():
    muted = context(200, timeout=utcnow() + timedelta(minutes=10))
    permissions = muted.channel_permissions(channel())
    assert permissions == int(Perm.VIEW_CHANNEL | Perm.READ_MESSAGE_HISTORY)
    expired = context(200, timeout=utcnow() - timedelta(minutes=1))
    assert expired.can_in(channel(), Perm.SEND_MESSAGES)


def test_require_in_hides_unseen_channels_and_reports_missing_permissions():
    hidden = [overwrite("channel", 1, "role", MEMBER_ROLE, deny=int(Perm.VIEW_CHANNEL))]
    with pytest.raises(AppError) as hidden_error:
        context(200, overwrites=hidden).require_in(channel(), Perm.SEND_MESSAGES)
    assert hidden_error.value.status == 404
    with pytest.raises(AppError) as denied:
        context(200).require_in(channel(), Perm.MANAGE_MESSAGES)
    assert denied.value.status == 403


def test_permission_name_round_trip_and_validation():
    bits = names_to_bits(["send_messages", "KICK_MEMBERS"])
    assert set(bits_to_names(bits)) == {"send_messages", "kick_members"}
    with pytest.raises(AppError):
        names_to_bits(["make_me_god"])
