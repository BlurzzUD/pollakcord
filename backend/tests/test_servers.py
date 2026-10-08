import sqlite3

from .conftest import channel_named, create_server, database_path, first_channel, join_server, role_named, sql_rows


def setup_server(make_user, count=2):
    names = ["tulaj", "tag_egy", "tag_ketto"][:count]
    users = [make_user(name) for name in names]
    detail = create_server(users[0])
    code = users[0].get(f"/servers/{detail['id']}/invites").json()[0]["code"]
    for user in users[1:]:
        join_server(user, code)
    return users, detail, code


def assign(owner, server_id, target, role_id):
    response = owner.patch(f"/servers/{server_id}/members/{target.uid}", {"role_ids": [role_id]})
    assert response.status_code == 200, response.text


def test_new_server_has_profile_roles_categories_channels_and_invite(make_user):
    owner = make_user("tulaj")
    detail = create_server(owner, "Informatika 10A")
    assert detail["name"] == "Informatika 10A" and detail["is_owner"] is True and detail["member_count"] == 1
    assert detail["id"].isdigit() and detail["owner_id"] == owner.uid
    assert [r["kind"] for r in detail["roles"]] == ["administrator", "moderator", "member"]
    assert next(r for r in detail["roles"] if r["is_default"])["kind"] == "member"
    assert [c["name"] for c in detail["categories"]] == ["Szöveges csatornák", "Hangcsatornák"]
    assert channel_named(detail, "általános")["type"] == "text"
    assert channel_named(detail, "Társalgó")["type"] == "voice"
    assert len(detail["invite_code"]) == 10 and detail["invite_code"].isalnum()


def test_server_defaults_are_localized_to_the_owners_language(make_user):
    owner = make_user("tulaj")
    owner.patch("/me/settings", {"language": "de"})
    detail = create_server(owner, "Deutsch AG")
    assert channel_named(detail, "allgemein")["type"] == "text"
    assert {r["name"] for r in detail["roles"]} == {"Mitglied", "Moderator", "Administrator"}


def test_server_ids_and_invite_codes_are_unique_and_unpredictable(make_user):
    owner = make_user("tulaj")
    servers = [create_server(owner, f"S{i}") for i in range(4)]
    assert len({s["id"] for s in servers}) == 4
    codes = [s["invite_code"] for s in servers]
    assert len(set(codes)) == 4
    assert all(len(c) == 10 for c in codes)
    ids = sorted(int(s["id"]) for s in servers)
    assert all(b - a > 1 for a, b in zip(ids, ids[1:]))


def test_non_members_cannot_see_or_touch_a_server(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    outsider = make_user("kivul")
    channel = first_channel(detail, "text")
    for response in (
        outsider.get(f"/servers/{detail['id']}"),
        outsider.get(f"/servers/{detail['id']}/members"),
        outsider.get(f"/channels/{channel['id']}/messages"),
        outsider.post(f"/channels/{channel['id']}/messages", {"content": "hello"}),
        outsider.patch(f"/servers/{detail['id']}", {"name": "Hacked"}),
        outsider.delete(f"/servers/{detail['id']}", {"confirm_name": detail["name"]}),
        outsider.get(f"/servers/{detail['id']}/audit-logs"),
        outsider.post(f"/servers/{detail['id']}/channels", {"name": "x", "type": "text"}),
    ):
        assert response.status_code == 404, response.text
    assert outsider.get("/servers").json() == []


def test_invite_preview_is_public_and_acceptance_joins_once(make_user, api):
    owner = make_user("tulaj")
    detail = create_server(owner)
    code = detail["invite_code"]
    preview = api.client.get(f"/api/v1/invites/{code}")
    assert preview.status_code == 200
    assert preview.json()["server"]["name"] == "Teszt szerver" and preview.json()["server"]["member_count"] == 1
    joiner = make_user("belepo")
    assert join_server(joiner, code) == {"server_id": detail["id"], "already_member": False}
    assert join_server(joiner, code)["already_member"] is True
    assert joiner.get("/servers").json()[0]["name"] == "Teszt szerver"
    assert owner.get(f"/servers/{detail['id']}").json()["member_count"] == 2


def test_invites_can_be_limited_expired_and_revoked(make_user):
    owner, a, b, c = make_user("tulaj"), make_user("a_diak"), make_user("b_diak"), make_user("c_diak")
    detail = create_server(owner)
    limited = owner.post(f"/servers/{detail['id']}/invites", {"max_uses": 1}).json()
    assert limited["max_uses"] == 1 and limited["code"] != detail["invite_code"]
    join_server(a, limited["code"])
    assert b.post(f"/invites/{limited['code']}/accept").status_code == 404
    revocable = owner.post(f"/servers/{detail['id']}/invites", {}).json()
    assert owner.delete(f"/servers/{detail['id']}/invites/{revocable['code']}").status_code == 200
    assert b.post(f"/invites/{revocable['code']}/accept").json()["error"]["code"] == "invite_invalid"
    expiring = owner.post(f"/servers/{detail['id']}/invites", {"expires_in_hours": 1}).json()
    connection = sqlite3.connect(database_path(owner.app))
    connection.execute("UPDATE invites SET expires_at='2000-01-01 00:00:00' WHERE code=?", (expiring["code"],))
    connection.commit()
    connection.close()
    assert c.post(f"/invites/{expiring['code']}/accept").status_code == 404
    assert c.post("/invites/doesnotexist/accept").status_code == 404


def test_invite_management_requires_permission(make_user):
    (owner, member), detail, code = setup_server(make_user)
    assert member.post(f"/servers/{detail['id']}/invites", {}).status_code == 200
    assert len(member.get(f"/servers/{detail['id']}/invites").json()) == 1
    assert len(owner.get(f"/servers/{detail['id']}/invites").json()) == 2
    assert member.delete(f"/servers/{detail['id']}/invites/{code}").status_code == 403
    owner.patch(f"/servers/{detail['id']}", {"moderation_settings": {"invites_enabled": False}})
    assert member.post(f"/servers/{detail['id']}/invites", {}).json()["error"]["code"] == "invites_disabled"


def test_invite_codes_cannot_be_reused_after_leaving_a_server_limited_by_use(make_user):
    owner, a = make_user("tulaj"), make_user("a_diak")
    detail = create_server(owner)
    limited = owner.post(f"/servers/{detail['id']}/invites", {"max_uses": 1}).json()
    join_server(a, limited["code"])
    a.post(f"/servers/{detail['id']}/leave")
    assert a.post(f"/invites/{limited['code']}/accept").status_code == 404


def test_leaving_and_ownership_rules(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    assert owner.post(f"/servers/{detail['id']}/leave").json()["error"]["code"] == "owner_cannot_leave"
    assert member.post(f"/servers/{detail['id']}/leave").status_code == 200
    assert member.get(f"/servers/{detail['id']}").status_code == 404
    assert owner.get(f"/servers/{detail['id']}").json()["member_count"] == 1


def test_ownership_transfer_and_deletion(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    assert member.patch(f"/servers/{detail['id']}", {"owner_id": member.uid}).status_code == 403
    assert owner.patch(f"/servers/{detail['id']}", {"owner_id": member.uid}).status_code == 200
    assert owner.get(f"/servers/{detail['id']}").json()["is_owner"] is False
    assert owner.delete(f"/servers/{detail['id']}", {"confirm_name": detail["name"]}).status_code == 403
    assert member.delete(f"/servers/{detail['id']}", {"confirm_name": "wrong"}).json()["error"]["code"] == "confirmation_mismatch"
    assert member.delete(f"/servers/{detail['id']}", {"confirm_name": detail["name"]}).status_code == 200
    assert owner.get(f"/servers/{detail['id']}").status_code == 404
    assert sql_rows(owner.app, "SELECT COUNT(*) FROM servers")[0][0] == 0
    assert sql_rows(owner.app, "SELECT COUNT(*) FROM channels")[0][0] == 0


def test_server_profile_updates_need_manage_server(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    assert member.patch(f"/servers/{detail['id']}", {"name": "Hack"}).json()["error"]["code"] == "missing_permission"
    updated = owner.patch(f"/servers/{detail['id']}", {"name": "Új név", "description": "Leírás", "moderation_settings": {"max_mentions_per_message": 3}})
    body = updated.json()
    assert body["name"] == "Új név" and body["description"] == "Leírás" and body["moderation_settings"]["max_mentions_per_message"] == 3
    assert owner.patch(f"/servers/{detail['id']}", {"moderation_settings": {"bogus": 1}}).status_code == 422
    assert owner.patch(f"/servers/{detail['id']}", {"moderation_settings": {"max_mentions_per_message": 500}}).status_code == 422


def test_roles_permissions_and_assignment(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    sid = detail["id"]
    mod_role = role_named(detail, "moderator")
    assert member.post(f"/servers/{sid}/roles", {"name": "x", "permissions": []}).status_code == 403
    assert owner.post(f"/servers/{sid}/roles", {"name": "x", "permissions": ["make_me_god"]}).status_code == 422
    created = owner.post(f"/servers/{sid}/roles", {"name": "Szervező", "color": "#112233", "permissions": ["manage_channels", "create_invite"]})
    assert created.status_code == 200 and created.json()["permission_names"] == ["create_invite", "manage_channels"]
    assign(owner, sid, member, created.json()["id"])
    assert member.get(f"/servers/{sid}").json()["my_permission_names"].count("manage_channels") == 1
    assert member.post(f"/servers/{sid}/channels", {"name": "Projekt Munka", "type": "text"}).json()["name"] == "projekt-munka"
    assign(owner, sid, member, mod_role["id"])
    assert "manage_channels" not in member.get(f"/servers/{sid}").json()["my_permission_names"]
    assert member.post(f"/servers/{sid}/channels", {"name": "nem", "type": "text"}).status_code == 403


def test_nobody_can_grant_permissions_they_do_not_have(make_user):
    (owner, helper), detail, _ = setup_server(make_user)
    sid = detail["id"]
    role = owner.post(f"/servers/{sid}/roles", {"name": "Rangkezelo", "permissions": ["manage_roles"], "position": 50}).json()
    assign(owner, sid, helper, role["id"])
    denied = helper.post(f"/servers/{sid}/roles", {"name": "Ugyes", "permissions": ["kick_members"], "position": 10})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "cannot_grant_permission"
    allowed = helper.post(f"/servers/{sid}/roles", {"name": "Csendes", "permissions": ["manage_roles"], "position": 10})
    assert allowed.status_code == 200
    above = helper.post(f"/servers/{sid}/roles", {"name": "Fenti", "permissions": ["manage_roles"], "position": 60})
    assert above.json()["error"]["code"] == "role_hierarchy"
    assert helper.patch(f"/servers/{sid}/roles/{role_named(detail, 'administrator')['id']}", {"name": "pwn"}).json()["error"]["code"] == "role_hierarchy"
    assert helper.patch(f"/servers/{sid}/members/{helper.uid}", {"role_ids": [role_named(detail, "administrator")["id"]]}).status_code == 403


def test_builtin_roles_cannot_be_deleted_but_custom_ones_can(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    sid = detail["id"]
    assert owner.delete(f"/servers/{sid}/roles/{role_named(detail, 'moderator')['id']}").json()["error"]["code"] == "role_protected"
    custom = owner.post(f"/servers/{sid}/roles", {"name": "Ideiglenes", "permissions": []}).json()
    assign(owner, sid, member, custom["id"])
    assert owner.delete(f"/servers/{sid}/roles/{custom['id']}").status_code == 200
    assert custom["id"] not in member.get(f"/servers/{sid}").json()["my_role_ids"]


def test_moderator_hierarchy_for_kick_and_ban(make_user):
    (owner, mod, member), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    assign(owner, sid, mod, role_named(detail, "moderator")["id"])
    assert mod.delete(f"/servers/{sid}/members/{owner.uid}").status_code == 403
    assert mod.put(f"/servers/{sid}/bans/{member.uid}", {"reason": "x"}).json()["error"]["code"] == "missing_permission"
    assert member.delete(f"/servers/{sid}/members/{mod.uid}").status_code == 403
    assert mod.delete(f"/servers/{sid}/members/{member.uid}").status_code == 200
    assert member.get(f"/servers/{sid}").status_code == 404
    assert any(n["type"] == "moderation" and n["payload"]["kind"] == "kick" for n in member.get("/notifications").json()["items"])


def test_ban_blocks_rejoining_and_can_be_lifted(make_user):
    (owner, member), detail, code = setup_server(make_user)
    sid = detail["id"]
    assert owner.put(f"/servers/{sid}/bans/{member.uid}", {"reason": "spam"}).status_code == 200
    assert member.get(f"/servers/{sid}").status_code == 404
    assert member.post(f"/invites/{code}/accept").json()["error"]["code"] == "banned_from_server"
    bans = owner.get(f"/servers/{sid}/bans").json()
    assert bans[0]["user"]["username"] == "tag_egy" and bans[0]["reason"] == "spam"
    assert owner.delete(f"/servers/{sid}/bans/{member.uid}").status_code == 200
    assert join_server(member, code)["already_member"] is False
    assert owner.put(f"/servers/{sid}/bans/{owner.uid}", {"reason": ""}).status_code == 404


def test_owner_cannot_be_banned_or_kicked_by_admins(make_user):
    (owner, admin), detail, _ = setup_server(make_user)
    sid = detail["id"]
    assign(owner, sid, admin, role_named(detail, "administrator")["id"])
    assert admin.delete(f"/servers/{sid}/members/{owner.uid}").status_code == 403
    assert admin.put(f"/servers/{sid}/bans/{owner.uid}", {"reason": ""}).status_code == 404


def test_member_timeout_blocks_posting(make_user):
    (owner, mod, member), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    assign(owner, sid, mod, role_named(detail, "moderator")["id"])
    channel = first_channel(detail, "text")
    assert member.post(f"/channels/{channel['id']}/messages", {"content": "szia"}).status_code == 200
    assert mod.patch(f"/servers/{sid}/members/{member.uid}", {"timeout_minutes": 10}).status_code == 200
    blocked = member.post(f"/channels/{channel['id']}/messages", {"content": "meg egy"})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "timed_out"
    assert member.get(f"/channels/{channel['id']}/messages").status_code == 200
    mod.patch(f"/servers/{sid}/members/{member.uid}", {"timeout_minutes": 0})
    assert member.post(f"/channels/{channel['id']}/messages", {"content": "ujra"}).status_code == 200


def test_nicknames(make_user):
    (owner, member, other), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    assert member.patch(f"/servers/{sid}/members/{member.uid}", {"nickname": "Becenév"}).status_code == 200
    members = {m["user"]["username"]: m for m in owner.get(f"/servers/{sid}/members").json()["members"]}
    assert members["tag_egy"]["nickname"] == "Becenév" and members["tulaj"]["is_owner"] is True
    assert other.patch(f"/servers/{sid}/members/{member.uid}", {"nickname": "Hack"}).status_code == 403
    assert owner.patch(f"/servers/{sid}/members/{member.uid}", {"nickname": "Tulaj adta"}).status_code == 200


def test_channel_overwrites_hide_channels_from_members(make_user):
    (owner, mod, member), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    assign(owner, sid, mod, role_named(detail, "moderator")["id"])
    secret = owner.post(f"/servers/{sid}/channels", {"name": "titkos", "type": "text"}).json()
    default_role = next(r for r in detail["roles"] if r["is_default"])
    mod_role = role_named(detail, "moderator")
    assert member.get(f"/servers/{sid}").json()["channels"].__len__() == 3
    owner.put(f"/channels/{secret['id']}/overwrites/role/{default_role['id']}", {"deny": ["view_channel"]})
    owner.put(f"/channels/{secret['id']}/overwrites/role/{mod_role['id']}", {"allow": ["view_channel"]})
    assert "titkos" not in [c["name"] for c in member.get(f"/servers/{sid}").json()["channels"]]
    assert "titkos" in [c["name"] for c in mod.get(f"/servers/{sid}").json()["channels"]]
    assert member.get(f"/channels/{secret['id']}/messages").status_code == 404
    assert member.post(f"/channels/{secret['id']}/messages", {"content": "x"}).status_code == 404
    assert mod.post(f"/channels/{secret['id']}/messages", {"content": "csak mod"}).status_code == 200
    assert member.get(f"/channels/{secret['id']}/overwrites").status_code == 404
    assert owner.delete(f"/channels/{secret['id']}/overwrites/role/{default_role['id']}").status_code == 200
    assert "titkos" in [c["name"] for c in member.get(f"/servers/{sid}").json()["channels"]]


def test_overwrites_can_only_touch_channel_scoped_permissions(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    channel = first_channel(detail, "text")
    default_role = next(r for r in detail["roles"] if r["is_default"])
    base = f"/channels/{channel['id']}/overwrites/role/{default_role['id']}"
    assert owner.put(base, {"allow": ["administrator"]}).json()["error"]["code"] == "invalid_permission"
    assert owner.put(base, {"allow": ["send_messages"], "deny": ["send_messages"]}).status_code == 422
    assert owner.put(f"/channels/{channel['id']}/overwrites/role/999", {"deny": ["view_channel"]}).status_code == 404
    assert owner.put(f"/channels/{channel['id']}/overwrites/member/{member.uid}", {"deny": ["send_messages"]}).status_code == 200
    assert member.post(f"/channels/{channel['id']}/messages", {"content": "x"}).status_code == 403
    assert owner.get(f"/channels/{channel['id']}/overwrites").json()[0]["deny"] == ["send_messages"]


def test_category_overwrites_apply_to_their_channels(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    sid = detail["id"]
    default_role = next(r for r in detail["roles"] if r["is_default"])
    category = detail["categories"][0]
    channel = first_channel(detail, "text")
    owner.put(f"/categories/{category['id']}/overwrites/role/{default_role['id']}", {"deny": ["send_messages"]})
    assert member.post(f"/channels/{channel['id']}/messages", {"content": "x"}).status_code == 403
    assert owner.post(f"/channels/{channel['id']}/messages", {"content": "y"}).status_code == 200
    assert owner.get(f"/categories/{category['id']}/overwrites").json()[0]["deny"] == ["send_messages"]
    assert owner.delete(f"/categories/{category['id']}/overwrites/role/{default_role['id']}").status_code == 200
    assert member.post(f"/channels/{channel['id']}/messages", {"content": "z"}).status_code == 200


def test_channel_and_category_management(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    sid = detail["id"]
    category = owner.post(f"/servers/{sid}/categories", {"name": "Projektek"}).json()
    assert member.post(f"/servers/{sid}/categories", {"name": "Hack"}).status_code == 403
    channel = owner.post(
        f"/servers/{sid}/channels",
        {"name": "Beszélgető Szoba", "type": "voice", "category_id": category["id"], "user_limit": 4},
    ).json()
    assert channel["name"] == "Beszélgető Szoba" and channel["user_limit"] == 4 and channel["category_id"] == category["id"]
    text = owner.post(f"/servers/{sid}/channels", {"name": "Téma Szoba", "type": "text", "topic": "Leírás", "slowmode_seconds": 5}).json()
    assert text["name"] == "téma-szoba" and text["topic"] == "Leírás" and text["slowmode_seconds"] == 5
    assert owner.post(f"/servers/{sid}/channels", {"name": "x", "type": "text", "category_id": "999"}).status_code == 404
    updated = owner.patch(f"/channels/{text['id']}", {"name": "Átnevezve", "topic": "Új", "clear_category": True}).json()
    assert updated["name"] == "átnevezve" and updated["topic"] == "Új"
    assert member.patch(f"/channels/{text['id']}", {"name": "hack"}).status_code == 403
    assert owner.patch(f"/categories/{category['id']}", {"name": "Átnevezett"}).json()["name"] == "Átnevezett"
    assert owner.delete(f"/channels/{channel['id']}").status_code == 200
    assert owner.delete(f"/categories/{category['id']}").status_code == 200
    names = [c["name"] for c in owner.get(f"/servers/{sid}").json()["channels"]]
    assert "Beszélgető Szoba" not in names and "átnevezve" in names
    assert owner.post(f"/servers/{sid}/channels", {"name": "\u0007", "type": "text"}).status_code == 422


def test_audit_log_records_administrative_actions_without_secrets(make_user):
    (owner, mod, member), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    assign(owner, sid, mod, role_named(detail, "moderator")["id"])
    channel = owner.post(f"/servers/{sid}/channels", {"name": "uj", "type": "text"}).json()
    owner.patch(f"/servers/{sid}", {"name": "Átnevezve"})
    owner.delete(f"/channels/{channel['id']}")
    owner.post(f"/servers/{sid}/roles", {"name": "R", "permissions": ["speak"]})
    invite = owner.post(f"/servers/{sid}/invites", {"max_uses": 5}).json()
    owner.delete(f"/servers/{sid}/invites/{invite['code']}")
    mod.delete(f"/servers/{sid}/members/{member.uid}")
    owner.put(f"/servers/{sid}/bans/{member.uid}", {"reason": "teszt"})
    entries = owner.get(f"/servers/{sid}/audit-logs").json()["entries"]
    actions = {e["action"] for e in entries}
    assert {"channel.create", "channel.delete", "server.update", "role.create", "invite.create", "invite.revoke", "member.kick", "member.ban", "member.roles"} <= actions
    kick = next(e for e in entries if e["action"] == "member.kick")
    assert kick["actor"]["username"] == "tag_ketto" or kick["actor"]["username"] == "tag_egy"
    assert kick["target_user"]["username"] == "tag_ketto"
    assert member.get(f"/servers/{sid}/audit-logs").status_code == 404
    assert mod.get(f"/servers/{sid}/audit-logs").status_code == 200
    blob = str(entries)
    assert "Kiss" not in blob and "password" not in blob.lower()


def test_audit_log_requires_the_view_permission(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    denied = member.get(f"/servers/{detail['id']}/audit-logs")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "missing_permission"


def test_inviting_friends_sends_notifications_to_friends_only(make_user):
    owner, friend, stranger = make_user("tulaj"), make_user("barat"), make_user("idegen")
    owner.post("/friends/requests", {"username": "barat"})
    friend.post(f"/friends/requests/{friend.get('/friends/requests').json()['incoming'][0]['id']}/accept")
    detail = create_server(owner)
    sent = owner.post(f"/servers/{detail['id']}/invite-friends", {"user_ids": [friend.uid, stranger.uid], "invite_code": detail["invite_code"]})
    assert sent.json() == {"sent": 1}
    note = next(n for n in friend.get("/notifications").json()["items"] if n["type"] == "server")
    assert note["payload"]["invite_code"] == detail["invite_code"] and note["payload"]["server_name"] == "Teszt szerver"
    assert stranger.get("/notifications").json()["items"] == []


def test_server_and_account_limits(make_user):
    owner = make_user("tulaj")
    for index in range(10):
        assert owner.post("/servers", {"name": f"S{index}"}).status_code == 200
    assert owner.post("/servers", {"name": "Tizenegyedik"}).json()["error"]["code"] == "server_limit_reached"
