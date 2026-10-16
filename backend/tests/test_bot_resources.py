import sqlite3

import pytest
from alembic import command

from .conftest import create_server, database_dump, database_path, first_channel, join_server, role_named, sql_rows
from .test_bots import bot_api, gateway, installed, settle, sql_write
from .test_migrations import alembic_config
from .test_servers import assign

pytestmark = pytest.mark.timeout(30)
DEFAULT = ["view_channel", "read_message_history", "send_messages"]


def subscribe(socket, *events):
    socket.send_json({"op": "subscribe", "events": list(events)})
    assert socket.receive_json()["t"] == "subscribed"


def test_member_events_welcome_username_once_and_privacy(make_user):
    owner, server, bot, channel = installed(make_user)
    human = make_user("new_person")
    code = owner.post(f"/servers/{server['id']}/invites", {}).json()["code"]
    with gateway(owner, bot["token"]) as socket:
        socket.receive_json()
        subscribe(socket, "member.joined", "member.left", "member.updated")
        join_server(human, code)
        event = socket.receive_json()
        assert event["t"] == "member.joined"
        assert event["d"]["member"]["user"]["username"] == "new_person"
        assert set(event["d"]["member"]["user"]) == {"id", "username", "display_name", "avatar_url", "staff", "is_bot"}
        assert "school_class" not in str(event) and "identity" not in str(event)
        welcome = bot_api(owner, bot["token"], "POST", f"/channels/{channel}/messages", {"content": f"Welcome, {event['d']['member']['user']['username']}!"})
        assert welcome.status_code == 200
        assert socket.receive_json()["t"] == "message.create"
        join_server(human, code)
        assert settle(socket) == []
        assert human.post(f"/servers/{server['id']}/leave").status_code == 200
        left = socket.receive_json()
        assert left["t"] == "member.left" and left["d"]["member"]["user"]["id"] == human.uid
    cards = bot_api(owner, bot["token"], "GET", f"/servers/{server['id']}/members").json()["members"]
    assert all(row["user"]["id"] != human.uid for row in cards)


def test_member_events_require_current_install_view_and_opt_in(make_user):
    owner, server, bot, channel = installed(make_user)
    first, second = make_user("anna_k"), make_user("bence_k")
    code = owner.post(f"/servers/{server['id']}/invites", {}).json()["code"]
    with gateway(owner, bot["token"]) as socket:
        socket.receive_json()
        join_server(first, code)
        assert settle(socket) == []
        subscribe(socket, "member.joined", "reaction.update")
        for text in [row for row in server["channels"] if row["type"] == "text"]:
            owner.put(f"/channels/{text['id']}/overwrites/member/{bot['bot_id']}", {"deny": ["view_channel"]})
        join_server(second, code)
        assert settle(socket) == []
        assert bot_api(owner, bot["token"], "GET", f"/servers/{server['id']}/members").status_code == 404
        assert owner.delete(f"/servers/{server['id']}/bots/{bot['bot_id']}").status_code == 200
        assert bot_api(owner, bot["token"], "GET", f"/servers/{server['id']}/members/{first.uid}").status_code == 404


def test_fetch_scopes_private_channels_and_safe_profile_payloads(make_user):
    owner, server, bot, channel = installed(make_user)
    other_server = create_server(owner, "Other")
    outsider = make_user("outsider")
    sent = owner.post(f"/channels/{channel}/messages", {"content": "Allowed history"}).json()
    token = bot["token"]
    assert bot_api(owner, token, "GET", f"/channels/{channel}/messages/{sent['id']}").json()["content"] == "Allowed history"
    assert bot_api(owner, token, "GET", f"/channels/{channel}/messages").json()["messages"][-1]["id"] == sent["id"]
    detail = bot_api(owner, token, "GET", f"/servers/{server['id']}").json()
    assert "moderation_settings" not in detail and "voice_states" not in detail
    assert all(row["type"] == "text" for row in detail["channels"])
    profile = bot_api(owner, token, "GET", f"/servers/{server['id']}/members/{owner.uid}").json()
    assert "presence" not in profile and "class_code" not in str(profile) and "real_name" not in str(profile)
    for path in (f"/servers/{other_server['id']}", f"/servers/{server['id']}/members/{outsider.uid}", f"/channels/{first_channel(other_server, 'text')['id']}/messages", f"/channels/{first_channel(server, 'voice')['id']}"):
        assert bot_api(owner, token, "GET", path).status_code == 404
    owner.put(f"/channels/{channel}/overwrites/member/{bot['bot_id']}", {"deny": ["read_message_history"]})
    assert bot_api(owner, token, "GET", f"/channels/{channel}/messages/{sent['id']}").status_code == 403
    owner.put(f"/channels/{channel}/overwrites/member/{bot['bot_id']}", {"deny": ["view_channel"]})
    assert bot_api(owner, token, "GET", f"/channels/{channel}").status_code == 404
    assert all(row["id"] != channel for row in bot_api(owner, token, "GET", f"/servers/{server['id']}").json()["channels"])


def test_edits_are_own_only_encrypted_reindexed_and_committed(make_user):
    owner, server, bot, channel = installed(make_user)
    token = bot["token"]
    human = owner.post(f"/channels/{channel}/messages", {"content": "Human text"}).json()
    own = bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "beforeword"}).json()
    with gateway(owner, token) as socket:
        socket.receive_json()
        subscribe(socket, "message.update")
        edited = bot_api(owner, token, "PATCH", f"/channels/{channel}/messages/{own['id']}", {"content": "afterword"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["edited_at"] and edited.json()["author"]["is_bot"]
        event = socket.receive_json()
        assert event["t"] == "message.update" and event["d"]["content"] == "afterword"
        assert owner.get(f"/channels/{channel}/messages").json()["messages"][-1]["content"] == "afterword"
    dump = database_dump(owner.app)
    assert "beforeword" not in dump and "afterword" not in dump
    assert sql_rows(owner.app, "SELECT count(*) FROM message_search_tokens WHERE message_id = ?", (own["id"],)) == [(1,)]
    assert bot_api(owner, token, "PATCH", f"/channels/{channel}/messages/{human['id']}", {"content": "No"}).status_code == 404
    assert bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "Reply", "reply_to_id": own["id"]}).json()["reply_to"]["id"] == own["id"]
    assert bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "No", "reply_to_id": str(2**63)}).status_code == 422
    bot_api(owner, token, "DELETE", f"/channels/{channel}/messages/{own['id']}")
    assert bot_api(owner, token, "PATCH", f"/channels/{channel}/messages/{own['id']}", {"content": "No"}).status_code == 404


def test_reactions_pins_and_checked_grants(make_user):
    owner, server, bot, channel = installed(make_user, [*DEFAULT, "add_reactions", "manage_messages"])
    token = bot["token"]
    own = bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "React"}).json()
    path = f"/channels/{channel}/messages/{own['id']}/reactions"
    with gateway(owner, token) as socket:
        socket.receive_json()
        subscribe(socket, "reaction.update", "message.pin")
        assert bot_api(owner, token, "PUT", path, {"emoji": "🎉"}).status_code == 200
        assert socket.receive_json()["d"]["present"] is True
        assert bot_api(owner, token, "DELETE", path, {"emoji": "🎉"}).status_code == 200
        assert socket.receive_json()["d"]["present"] is False
        assert bot_api(owner, token, "PUT", f"/channels/{channel}/pins/{own['id']}").status_code == 200
        assert socket.receive_json()["d"]["pinned"] is True
        assert bot_api(owner, token, "GET", f"/channels/{channel}/pins").json()[0]["id"] == own["id"]
        assert bot_api(owner, token, "DELETE", f"/channels/{channel}/pins/{own['id']}").status_code == 200
        assert socket.receive_json()["d"]["pinned"] is False
    assert bot_api(owner, token, "PUT", path, {"emoji": "unsupported"}).status_code == 422
    owner.put(f"/channels/{channel}/overwrites/member/{bot['bot_id']}", {"deny": ["add_reactions", "manage_messages"]})
    assert bot_api(owner, token, "PUT", path, {"emoji": "🎉"}).status_code == 403
    assert bot_api(owner, token, "PUT", f"/channels/{channel}/pins/{own['id']}").status_code == 403


def test_moderation_permissions_hierarchy_and_no_self_elevation(make_user):
    owner, server, bot, channel = installed(make_user, [*DEFAULT, "kick_members", "ban_members", "manage_members", "manage_roles"])
    member, higher = make_user("anna_k"), make_user("bence_k")
    code = owner.post(f"/servers/{server['id']}/invites", {}).json()["code"]
    join_server(member, code)
    join_server(higher, code)
    assign(owner, server["id"], higher, role_named(server, "moderator")["id"])
    token = bot["token"]
    prefix = f"/servers/{server['id']}"
    assert bot_api(owner, token, "DELETE", f"{prefix}/members/{owner.uid}").status_code == 403
    assert bot_api(owner, token, "DELETE", f"{prefix}/members/{higher.uid}").status_code == 403
    assert bot_api(owner, token, "PATCH", f"{prefix}/members/{bot['bot_id']}", {"role_ids": [role_named(server, "administrator")["id"]]}).status_code == 403
    assert bot_api(owner, token, "POST", f"{prefix}/roles", {"name": "Escalation", "permissions": ["administrator"]}).status_code == 403
    role = bot_api(owner, token, "POST", f"{prefix}/roles", {"name": "Welcomed", "permissions": ["send_messages"]})
    assert role.status_code == 200, role.text
    role_id = role.json()["id"]
    assert bot_api(owner, token, "PUT", f"{prefix}/members/{member.uid}/roles/{role_id}").status_code == 200
    assert bot_api(owner, token, "GET", f"{prefix}/members/{member.uid}").json()["role_ids"] == [role_id]
    assert bot_api(owner, token, "DELETE", f"{prefix}/members/{member.uid}/roles/{role_id}").status_code == 200
    assert bot_api(owner, token, "PATCH", f"{prefix}/members/{member.uid}", {"timeout_minutes": 5}).status_code == 200
    assert member.post(f"/channels/{channel}/messages", {"content": "Blocked"}).status_code == 403
    assert bot_api(owner, token, "PATCH", f"{prefix}/members/{member.uid}", {"timeout_minutes": 0}).status_code == 200
    assert bot_api(owner, token, "PUT", f"{prefix}/bans/{member.uid}", {"reason": "Test"}).status_code == 200
    assert join_banned(member, code) == 403
    assert bot_api(owner, token, "DELETE", f"{prefix}/bans/{member.uid}").status_code == 200
    assert bot_api(owner, token, "DELETE", f"{prefix}/bans/{bot['bot_id']}").status_code == 403
    assert bot_api(owner, token, "PATCH", f"{prefix}/roles/{role_named(server, 'member')['id']}", {"name": "No"}).status_code == 409
    assert "member.ban" in str(sql_rows(owner.app, "SELECT action FROM audit_logs"))


def join_banned(member, code):
    return member.post(f"/invites/{code}/accept").status_code


def test_channels_invites_and_management_grants(make_user):
    owner, server, bot, channel = installed(make_user, [*DEFAULT, "manage_channels", "create_invite"])
    token = bot["token"]
    assert bot_api(owner, token, "POST", f"/servers/{server['id']}/channels", {"name": "Voice", "type": "voice"}).status_code == 422
    created = bot_api(owner, token, "POST", f"/servers/{server['id']}/channels", {"name": "Bot room", "topic": "Welcome"})
    assert created.status_code == 200, created.text
    created_id = created.json()["id"]
    assert bot_api(owner, token, "PATCH", f"/channels/{created_id}", {"name": "Renamed"}).status_code == 200
    assert bot_api(owner, token, "DELETE", f"/channels/{created_id}").status_code == 200
    invite = bot_api(owner, token, "POST", f"/servers/{server['id']}/invites", {"max_uses": 1}).json()
    assert bot_api(owner, token, "DELETE", f"/servers/{server['id']}/invites/{invite['code']}").status_code == 200
    assert bot_api(owner, token, "POST", f"/servers/{server['id']}/roles", {"name": "No"}).status_code == 403
    for path in ("/dok", "/class-spaces", "/forms/1/results", "/moderation/users/1/identity", "/friends", "/me/bots", "/users/1"):
        assert bot_api(owner, token, "GET", path).status_code == 404


def test_moderated_deletion_checks_hierarchy_and_default_is_still_own_only(make_user):
    owner, server, bot, channel = installed(make_user, [*DEFAULT, "manage_messages"])
    member = make_user("anna_k")
    join_server(member, owner.post(f"/servers/{server['id']}/invites", {}).json()["code"])
    own = owner.post(f"/channels/{channel}/messages", {"content": "Owner"}).json()
    other = member.post(f"/channels/{channel}/messages", {"content": "Member"}).json()
    token = bot["token"]
    assert bot_api(owner, token, "DELETE", f"/channels/{channel}/messages/{own['id']}").status_code == 403
    assert bot_api(owner, token, "DELETE", f"/channels/{channel}/messages/{other['id']}").status_code == 200


def test_edit_migration_preserves_populated_messages_and_only_drops_own_column(tmp_path):
    path = tmp_path / "edits.db"
    config = alembic_config(f"sqlite+aiosqlite:///{path}")
    command.upgrade(config, "0006")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO messages (id, channel_id, conversation_id, created_at, media_enc, media_key_id) VALUES (1, 2, NULL, '2026-01-01', X'0102', 'test')")
        columns = [row[1] for row in db.execute("PRAGMA table_info(messages)")]
    command.upgrade(config, "0007")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id, media_enc, edited_at FROM messages").fetchall() == [(1, b"\x01\x02", None)]
    command.downgrade(config, "0006")
    with sqlite3.connect(path) as db:
        assert [row[1] for row in db.execute("PRAGMA table_info(messages)")] == columns
        assert db.execute("SELECT id, media_enc FROM messages").fetchall() == [(1, b"\x01\x02")]


def test_server_metadata_and_id_only_audit_are_scoped_and_permissioned(make_user):
    owner, server, bot, channel = installed(make_user, [*DEFAULT, "manage_server", "view_audit_log"])
    token = bot["token"]
    prefix = f"/servers/{server['id']}"
    assert bot_api(owner, token, "PATCH", prefix, {"name": "Renamed by bot"}).status_code == 200
    assert owner.get(prefix).json()["name"] == "Renamed by bot"
    assert bot_api(owner, token, "PATCH", prefix, {"owner_id": bot["bot_id"]}).status_code == 422
    rows = bot_api(owner, token, "GET", f"{prefix}/audit-logs").json()["entries"]
    assert any(row["action"] == "server.update" and row["actor_id"] == bot["bot_id"] for row in rows)
    assert all(set(row) == {"id", "action", "actor_id", "target_type", "target_id", "created_at"} for row in rows)
    other = create_server(owner, "Elsewhere")
    assert bot_api(owner, token, "GET", f"/servers/{other['id']}/audit-logs").status_code == 404
    assert bot_api(owner, token, "GET", f"{prefix}/bans").status_code == 403


def test_extended_channel_cache_refresh_contains_no_private_channels(make_user):
    owner, server, bot, channel = installed(make_user)
    role_id = sql_rows(owner.app, "SELECT role_id FROM bot_installs")[0][0]
    with gateway(owner, bot["token"]) as socket:
        socket.receive_json()
        subscribe(socket, "structure.changed", "role.changed")
        assert owner.patch(f"/servers/{server['id']}/roles/{role_id}", {"permissions": ["send_messages"]}).status_code == 200
        event = socket.receive_json()
        assert event["t"] == "role.changed" and event["d"]["channels"] == []
        assert owner.patch(f"/servers/{server['id']}/roles/{role_id}", {"permissions": DEFAULT}).status_code == 200
        socket.receive_json()
        assert owner.put(f"/channels/{channel}/overwrites/member/{bot['bot_id']}", {"deny": ["view_channel"]}).status_code == 200
        event = socket.receive_json()
        assert event["t"] == "structure.changed"
        assert all(row["id"] != channel for row in event["d"]["channels"])
