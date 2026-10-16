import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from app.db.types import utcnow

from .conftest import STRONG_PASSWORD, create_server, database_dump, database_path, first_channel, join_server, role_named, sql_rows
from .test_servers import assign

pytestmark = pytest.mark.timeout(30)


def bot_request(owner, token, method, path, body=None, headers=None):
    return owner.client.request(method, "/api/v1" + path, json=body, headers={"Authorization": f"Bot {token}", "Cookie": "", **(headers or {})})


def bot_api(owner, token, method, path, body=None):
    return bot_request(owner, token, method, "/bots/api" + path, body)


def create_bot(owner, username="helper_bot"):
    result = owner.post("/me/bots", {"username": username, "display_name": "Helper", "password": STRONG_PASSWORD})
    assert result.status_code == 200, result.text
    return result.json()


def installed(make_user, permissions=None):
    owner = make_user("eva_k")
    server = create_server(owner)
    bot = create_bot(owner)
    body = {"bot_id": bot["bot_id"]}
    if permissions is not None:
        body["permissions"] = permissions
    result = owner.post(f"/servers/{server['id']}/bots", body)
    assert result.status_code == 200, result.text
    return owner, server, bot, first_channel(server, "text")["id"]


def gateway(owner, token, extra=None):
    return owner.client.websocket_connect("/api/v1/bots/gateway", headers={"Authorization": f"Bot {token}", "Cookie": "", **(extra or {})})


def settle(socket):
    socket.send_json({"op": "ping"})
    seen = []
    while True:
        event = socket.receive_json()
        if event["t"] == "pong":
            return seen
        seen.append(event)


def sql_write(owner, statement, params=()):
    with sqlite3.connect(database_path(owner.app)) as connection:
        connection.execute(statement, params)


def register_ping(owner, bot, **extra):
    response = bot_api(owner, bot["token"], "PUT", "/commands", {"commands": [{"name": "ping", "description": "Ping", **extra}]})
    assert response.status_code == 200, response.text
    return response.json()[0]


def test_lifecycle_password_ownership_hashes_and_limit(make_user):
    owner, other = make_user("eva_k"), make_user("anna_k")
    assert owner.post("/me/bots", {"username": "helper_bot", "display_name": "Helper", "password": "wrong"}).status_code == 401
    bot = create_bot(owner)
    assert bot["user"]["is_bot"] and not bot["user"]["staff"]
    assert bot["token"] not in database_dump(owner.app)
    assert sql_rows(owner.app, "SELECT token_hash FROM bot_applications")[0][0] == hashlib.sha256(bot["token"].encode()).hexdigest()
    for table in ("auth_methods", "user_identities"):
        assert sql_rows(owner.app, f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (bot["bot_id"],)) == [(0,)]
    listed = owner.get("/me/bots").json()
    assert len(listed) == 1 and "token" not in listed[0] and "token_hash" not in str(listed)
    assert other.patch(f"/me/bots/{bot['bot_id']}", {"display_name": "Taken"}).status_code == 404
    assert other.post(f"/me/bots/{bot['bot_id']}/token/reveal", {"password": STRONG_PASSWORD}).status_code == 404
    assert owner.patch(f"/me/bots/{bot['bot_id']}", {"display_name": "New name", "username": "new_helper"}).json()["user"]["username"] == "new_helper"
    create_bot(owner, "helper_two")
    create_bot(owner, "helper_three")
    fourth = owner.post("/me/bots", {"username": "helper_four", "display_name": "Fourth", "password": STRONG_PASSWORD})
    assert fourth.status_code == 409 and fourth.json()["error"]["code"] == "bot_limit_reached"
    for password, confirmation, status in ((STRONG_PASSWORD, "wrong", 422), ("wrong", "new_helper", 401), (STRONG_PASSWORD, "new_helper", 200)):
        assert owner.delete(f"/me/bots/{bot['bot_id']}", {"password": password, "confirm_username": confirmation}).status_code == status
    assert bot_api(owner, bot["token"], "GET", "/me").status_code == 401
    assert len(owner.get("/me/bots").json()) == 2
    create_bot(owner, "helper_four")
    assert {"bot.create", "bot.delete"} <= {row[0] for row in sql_rows(owner.app, "SELECT action FROM audit_logs")}


def test_password_lockouts_and_totp_only_owners(make_user):
    owner = make_user("eva_k")
    bot = create_bot(owner)
    sql_write(owner, "UPDATE auth_methods SET locked_until = ? WHERE user_id = ?", ((utcnow() + timedelta(minutes=5)).isoformat(), owner.uid))
    assert owner.post(f"/me/bots/{bot['bot_id']}/token/regenerate", {"password": STRONG_PASSWORD}).status_code == 429
    totp = make_user("anna_k", method="totp")
    response = totp.post("/me/bots", {"username": "totp_helper", "display_name": "Helper", "password": "123456"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "bot_password_required"


def test_install_requires_owner_or_real_administrator_and_badge_serializers(make_user):
    owner, server, bot, channel = installed(make_user)
    member = make_user("anna_k")
    join_server(member, owner.post(f"/servers/{server['id']}/invites", {}).json()["code"])
    bot2 = create_bot(owner, "second_helper")
    path = f"/servers/{server['id']}/bots"
    assert member.post(path, {"bot_id": bot2["bot_id"]}).status_code == 403
    assert member.get(path).status_code == 403
    assert member.delete(f"{path}/{bot['bot_id']}").status_code == 403
    assign(owner, server["id"], member, role_named(server, "moderator")["id"])
    assert member.post(path, {"bot_id": bot2["bot_id"]}).status_code == 403
    assert member.delete(f"/servers/{server['id']}/members/{bot['bot_id']}").status_code == 403
    assign(owner, server["id"], member, role_named(server, "administrator")["id"])
    assert member.post(path, {"bot_id": bot2["bot_id"]}).status_code == 200
    assert member.delete(f"{path}/{bot2['bot_id']}").status_code == 200
    cards = owner.get(f"/servers/{server['id']}/members").json()["members"]
    assert next(row["user"] for row in cards if row["user"]["id"] == bot["bot_id"])["is_bot"]
    assert owner.get(f"/users/{bot['bot_id']}").json()["is_bot"]
    assert owner.patch(f"/servers/{server['id']}", {"owner_id": bot["bot_id"]}).status_code == 403
    assert owner.post(path, {"bot_id": "9999999999999999999"}).status_code == 422
    assert owner.delete(f"{path}/9999999999999999999").status_code == 422
    payload = owner.get(path).json()
    assert "administrator" not in payload["available_permissions"] and "connect" not in payload["available_permissions"]
    for permission in ("administrator", "dok_president"):
        assert owner.post(path, {"bot_id": bot2["bot_id"], "permissions": [permission]}).status_code == 422


def test_bot_auth_is_separate_from_sessions_and_school_private_surfaces(make_user):
    owner, server, bot, channel = installed(make_user)
    for path in ("/me", "/me/bots", "/dok/threads", "/class-spaces", "/forms", "/forms/1/results", "/moderation/users", "/moderation/users/1/identity", "/friends", "/users/search", "/dms", "/uploads/config", "/servers"):
        assert bot_request(owner, bot["token"], "GET", path).status_code == 403
    assert bot_request(owner, bot["token"], "POST", "/me/bots", {}).status_code == 403
    assert owner.post("/auth/login", {"username": bot["user"]["username"], "secret": STRONG_PASSWORD}).status_code == 401
    assert owner.post("/friends/requests", {"user_id": bot["bot_id"]}).status_code == 200
    assert sql_rows(owner.app, "SELECT COUNT(*) FROM friend_requests WHERE recipient_id = ?", (bot["bot_id"],)) == [(0,)]
    assert owner.post("/dms", {"user_id": bot["bot_id"]}).status_code == 404
    assert bot_api(owner, bot["token"], "GET", "/me").json()["user"]["is_bot"]
    owner.client.cookies = owner.jar
    assert owner.client.get("/api/v1/bots/api/me", headers={"Authorization": f"Bot {bot['token']}"}).status_code == 401
    assert owner.get("/bots/api/me").status_code == 401
    assert bot_request(owner, bot["token"], "POST", f"/bots/api/channels/{channel}/messages", {"content": "hello"}, {"Origin": "http://testserver"}).status_code == 403
    assert owner.client.post("/api/v1/me/bots", json={}, headers={"Authorization": "Bot bogus", "Cookie": ""}).status_code == 403
    for statement in ("UPDATE users SET platform_role = 'school_admin' WHERE id = ?", "UPDATE users SET school_class_id = 1 WHERE id = ?"):
        with pytest.raises(sqlite3.IntegrityError):
            sql_write(owner, statement, (bot["bot_id"],))


def test_checked_grants_cap_roles_overwrites_private_channels_and_slowmode(make_user):
    owner, server, bot, channel = installed(make_user, ["view_channel", "read_message_history"])
    token = bot["token"]
    assert bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "denied"}).status_code == 403
    role_id = sql_rows(owner.app, "SELECT role_id FROM bot_installs")[0][0]
    assert owner.put(f"/channels/{channel}/overwrites/member/{bot['bot_id']}", {"allow": ["send_messages", "manage_messages"]}).status_code == 200
    assert owner.patch(f"/servers/{server['id']}/roles/{role_id}", {"permissions": ["administrator"]}).status_code == 200
    assert bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "no elevation"}).status_code == 404
    assert owner.delete(f"/servers/{server['id']}/bots/{bot['bot_id']}").status_code == 200
    assert owner.post(f"/servers/{server['id']}/bots", {"bot_id": bot["bot_id"]}).status_code == 200
    default = next(role for role in server["roles"] if role["is_default"])
    assert owner.put(f"/channels/{channel}/overwrites/role/{default['id']}", {"deny": ["view_channel"]}).status_code == 200
    channels = bot_api(owner, token, "GET", f"/servers/{server['id']}/channels").json()
    assert all(c["id"] != channel for c in channels)
    assert bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "private"}).status_code == 404
    assert owner.put(f"/channels/{channel}/overwrites/member/{bot['bot_id']}", {"allow": ["view_channel", "send_messages"]}).status_code == 200
    sent = bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "Text bot"})
    assert sent.status_code == 200 and sent.json()["author"]["is_bot"]
    assert bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "x", "attachment_ids": ["1"]}).status_code == 422
    assert owner.patch(f"/channels/{channel}", {"slowmode_seconds": 30}).status_code == 200
    assert bot_api(owner, token, "POST", f"/channels/{channel}/messages", {"content": "slow"}).status_code == 429
    foreign = create_server(owner, "Other")
    assert bot_api(owner, token, "POST", f"/channels/{first_channel(foreign, 'text')['id']}/messages", {"content": "no install"}).status_code == 404
    assert bot_api(owner, token, "GET", "/servers").json() == [{"id": server["id"], "name": server["name"]}]


def test_bot_delete_is_own_only_and_respects_channel_permissions(make_user):
    owner, server, bot, channel = installed(make_user)
    own = bot_api(owner, bot["token"], "POST", f"/channels/{channel}/messages", {"content": "mine"}).json()
    human = owner.post(f"/channels/{channel}/messages", {"content": "human"}).json()
    assert bot_api(owner, bot["token"], "DELETE", f"/channels/{channel}/messages/{human['id']}").status_code == 404
    assert bot_api(owner, bot["token"], "DELETE", f"/channels/{channel}/messages/{own['id']}").status_code == 200
    assert next(m for m in owner.get(f"/channels/{channel}/messages").json()["messages"] if m["id"] == own["id"])["deleted"]


def test_gateway_live_filtering_regeneration_caps_and_owner_suspension(make_user):
    owner, server, bot, channel = installed(make_user)
    with gateway(owner, bot["token"]) as socket:
        assert socket.receive_json()["d"]["user"]["is_bot"]
        with pytest.raises(WebSocketDisconnect):
            with gateway(owner, bot["token"]):
                pass
        sent = owner.post(f"/channels/{channel}/messages", {"content": "visible"}).json()
        assert socket.receive_json()["d"]["id"] == sent["id"]
        owner.delete(f"/channels/{channel}/messages/{sent['id']}")
        assert socket.receive_json()["t"] == "message.delete"
        default = next(role for role in server["roles"] if role["is_default"])
        owner.put(f"/channels/{channel}/overwrites/role/{default['id']}", {"deny": ["view_channel"]})
        owner.post(f"/channels/{channel}/messages", {"content": "hidden"})
        assert settle(socket) == []
        rotated = owner.post(f"/me/bots/{bot['bot_id']}/token/reveal", {"password": STRONG_PASSWORD})
        assert rotated.status_code == 200 and rotated.json()["token"] != bot["token"]
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert bot_api(owner, bot["token"], "GET", "/me").status_code == 401
    token = rotated.json()["token"]
    assert bot_api(owner, token, "GET", "/me").status_code == 200
    with gateway(owner, token) as socket:
        socket.receive_json()
        sql_write(owner, "UPDATE users SET status = 'suspended' WHERE id = ?", (owner.uid,))
        socket.send_json({"op": "ping"})
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert bot_api(owner, token, "GET", "/me").status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with gateway(owner, token):
            pass


def test_commands_scope_options_offline_timeout_and_single_public_response(make_user):
    owner, server, bot, channel = installed(make_user)
    command = register_ping(owner, bot)
    assert owner.get(f"/channels/{channel}/bot-commands").json()[0]["bot"]["is_bot"]
    second_channel = first_channel(create_server(owner, "Other"), "text")["id"]
    assert owner.get(f"/channels/{second_channel}/bot-commands").json() == []
    assert owner.post(f"/channels/{second_channel}/interactions", {"command_id": command["id"]}).status_code == 404
    offline = owner.post(f"/channels/{channel}/interactions", {"command_id": command["id"]})
    assert offline.status_code == 409 and offline.json()["error"]["code"] == "bot_offline"
    with gateway(owner, bot["token"]) as socket:
        socket.receive_json()
        timeout = owner.post(f"/channels/{channel}/interactions", {"command_id": command["id"]})
        interaction = socket.receive_json()["d"]
        assert timeout.status_code == 504 and timeout.json()["error"]["code"] == "bot_interaction_timeout"
        assert bot_api(owner, bot["token"], "POST", f"/interactions/{interaction['id']}/response", {"content": "late"}).status_code == 409
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(owner.post, f"/channels/{channel}/interactions", {"command_id": command["id"]})
            interaction = socket.receive_json()["d"]
            reply = bot_api(owner, bot["token"], "POST", f"/interactions/{interaction['id']}/response", {"content": "Pong!"})
            assert reply.status_code == 200, reply.text
            result = pending.result(timeout=8)
            assert result.status_code == 200 and result.json()["content"] == "Pong!"
        assert bot_api(owner, bot["token"], "POST", f"/interactions/{interaction['id']}/response", {"content": "twice"}).status_code == 409
        assert owner.get(f"/channels/{channel}/messages").json()["messages"][-1]["author"]["is_bot"]
    assert register_ping(owner, bot)["id"] == command["id"]
    assert bot_api(owner, bot["token"], "PUT", "/commands", {"commands": [{"name": "same", "description": "x"}, {"name": "same", "description": "x"}]}).status_code == 422
    assert bot_api(owner, bot["token"], "PUT", "/commands", {"commands": [{"name": f"cmd{i}", "description": "x"} for i in range(26)]}).status_code == 422
    command = register_ping(owner, bot, options=[{"name": "count", "description": "Count", "type": "int", "required": True}])
    for options in ({}, {"count": True}, {"count": 2**54}, {"count": 1, "unknown": "x"}):
        assert owner.post(f"/channels/{channel}/interactions", {"command_id": command["id"], "options": options}).status_code == 422


def test_default_member_permissions_filter_commands(make_user):
    owner, server, bot, channel = installed(make_user)
    member = make_user("anna_k")
    join_server(member, owner.post(f"/servers/{server['id']}/invites", {}).json()["code"])
    command = register_ping(owner, bot, default_member_permissions=["manage_messages"])
    assert member.get(f"/channels/{channel}/bot-commands").json() == []
    assert member.post(f"/channels/{channel}/interactions", {"command_id": command["id"]}).status_code == 404
    assert len(owner.get(f"/channels/{channel}/bot-commands").json()) == 1


def test_bot_rest_and_command_registration_rate_limits(make_user):
    owner, server, bot, channel = installed(make_user)
    owner.app.state.limiter.enabled = True
    for _ in range(3):
        register_ping(owner, bot)
    assert bot_api(owner, bot["token"], "PUT", "/commands", {"commands": []}).status_code == 429
    for index in range(8):
        assert bot_api(owner, bot["token"], "POST", f"/channels/{channel}/messages", {"content": f"message {index}"}).status_code == 200
    assert bot_api(owner, bot["token"], "POST", f"/channels/{channel}/messages", {"content": "too much"}).status_code == 429


def test_regeneration_and_deletion_disconnect_pending_interactions_and_keep_author_badge(make_user):
    owner, server, bot, channel = installed(make_user)
    command = register_ping(owner, bot)
    own = bot_api(owner, bot["token"], "POST", f"/channels/{channel}/messages", {"content": "kept"}).json()
    assert owner.post(f"/me/bots/{bot['bot_id']}/token/regenerate", {"password": "wrong"}).status_code == 401
    assert bot_api(owner, bot["token"], "GET", "/me").status_code == 200
    with gateway(owner, bot["token"]) as socket:
        socket.receive_json()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(owner.post, f"/channels/{channel}/interactions", {"command_id": command["id"]})
            interaction = socket.receive_json()["d"]
            rotated = owner.post(f"/me/bots/{bot['bot_id']}/token/regenerate", {"password": STRONG_PASSWORD})
            assert rotated.status_code == 200
            assert pending.result(timeout=8).json()["error"]["code"] == "bot_offline"
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    token = rotated.json()["token"]
    assert bot_api(owner, token, "POST", f"/interactions/{interaction['id']}/response", {"content": "old invocation"}).status_code == 409
    with gateway(owner, token) as socket:
        socket.receive_json()
        assert owner.delete(f"/me/bots/{bot['bot_id']}", {"password": STRONG_PASSWORD, "confirm_username": "helper_bot"}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert sql_rows(owner.app, "SELECT COUNT(*) FROM bot_installs") == [(0,)]
    assert sql_rows(owner.app, "SELECT COUNT(*) FROM roles WHERE kind = 'bot'") == [(0,)]
    assert sql_rows(owner.app, "SELECT COUNT(*) FROM server_members WHERE user_id = ?", (bot["bot_id"],)) == [(0,)]
    history = owner.get(f"/channels/{channel}/messages").json()["messages"]
    assert next(message for message in history if message["id"] == own["id"])["author"]["is_bot"]
    assert {"bot.create", "bot.token_regenerate", "bot.install", "bot.remove", "bot.delete"} <= {row[0] for row in sql_rows(owner.app, "SELECT action FROM audit_logs")}
    assert bot["token"] not in str(sql_rows(owner.app, "SELECT details FROM audit_logs"))
    assert token not in database_dump(owner.app)


def test_gateway_excludes_private_topics_and_only_flushes_committed_outbox(make_user):
    from app.realtime.outbox import Outbox

    owner, server, bot, channel = installed(make_user)
    async def hidden_and_unflushed():
        outbox = Outbox(owner.app.state.hub)
        outbox.topic(f"channel:{channel}", "message.create", {"id": "1", "scope": "channel", "content": "not flushed"})
        for topic, scope in (("dm:1", "dm"), ("dok:school", "dok"), ("class-space:1", "class_space")):
            await owner.app.state.hub.publish(topic, "message.create", {"id": "2", "scope": scope, "content": "private"})
        await owner.app.state.hub.publish(f"channel:{channel}", "message.create", {"scope": "dm", "content": "wrong scope"})
    with gateway(owner, bot["token"]) as socket:
        socket.receive_json()
        owner.client.portal.call(hidden_and_unflushed)
        assert settle(socket) == []
        owner.post(f"/channels/{channel}/messages", {"content": "committed"})
        assert socket.receive_json()["d"]["content"] == "committed"
        assert owner.delete(f"/servers/{server['id']}/bots/{bot['bot_id']}").status_code == 200
        owner.post(f"/channels/{channel}/messages", {"content": "after uninstall"})
        assert settle(socket) == []
        assert bot_api(owner, bot["token"], "POST", f"/channels/{channel}/messages", {"content": "cannot send"}).status_code == 404


def test_options_hide_other_servers_channels_and_users(make_user):
    owner, server, bot, channel = installed(make_user)
    outsider = make_user("anna_k")
    other_channel = first_channel(create_server(owner, "Elsewhere"), "text")["id"]
    command = register_ping(owner, bot, options=[{"name": "target", "description": "Target", "type": "channel", "required": True}, {"name": "person", "description": "Person", "type": "user", "required": True}])
    for options in ({"target": other_channel, "person": owner.uid}, {"target": channel, "person": outsider.uid}, {"target": str(2**63), "person": owner.uid}):
        assert owner.post(f"/channels/{channel}/interactions", {"command_id": command["id"], "options": options}).status_code == 422
    owner.put(f"/channels/{channel}/overwrites/member/{bot['bot_id']}", {"deny": ["send_messages"]})
    assert owner.get(f"/channels/{channel}/bot-commands").json() == []
    assert owner.post(f"/channels/{channel}/interactions", {"command_id": command["id"], "options": {"target": channel, "person": owner.uid}}).status_code == 404


def test_bot_context_reuses_hierarchy_without_inheriting_default_powers(make_user):
    from app.services.permissions import Perm, load_context

    owner, server, bot, channel = installed(make_user)
    human = make_user("anna_k")
    join_server(human, owner.post(f"/servers/{server['id']}/invites", {}).json()["code"])
    async def check():
        async with owner.app.state.session_factory() as db:
            context = await load_context(db, int(server["id"]), int(bot["bot_id"]))
            server_owner = await load_context(db, int(server["id"]), int(owner.uid))
            regular = await load_context(db, int(server["id"]), int(human.uid))
            assert not context.outranks(server_owner) and not context.outranks(context)
            assert context.outranks(regular)
            assert not context.can(Perm.CREATE_INVITE) and not context.can(Perm.CONNECT) and not context.can(Perm.ADMINISTRATOR)
    owner.client.portal.call(check)
    assign(owner, server["id"], human, role_named(server, "moderator")["id"])
    async def check_higher():
        async with owner.app.state.session_factory() as db:
            context = await load_context(db, int(server["id"]), int(bot["bot_id"]))
            moderator = await load_context(db, int(server["id"]), int(human.uid))
            assert not context.outranks(moderator)
    owner.client.portal.call(check_higher)
