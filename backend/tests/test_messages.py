import sqlite3

from .conftest import channel_named, create_server, database_path, first_channel, join_server, role_named, sql_rows
from .test_servers import assign, setup_server
from .test_social import befriend, set_privacy


def promote(app, username, role):
    connection = sqlite3.connect(database_path(app))
    connection.execute("UPDATE users SET platform_role=? WHERE username_lower=?", (role, username))
    connection.commit()
    connection.close()


def open_dm(sender, recipient):
    response = sender.post("/dms", {"user_id": recipient.uid})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def friends_with_dm(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    befriend(eva, anna)
    return eva, anna, open_dm(eva, anna)


def test_direct_messages_flow_with_read_state(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    sent = eva.post(f"/dms/{conversation}/messages", {"content": "Szia Anna!"})
    assert sent.status_code == 200
    message = sent.json()
    assert message["content"] == "Szia Anna!" and message["author"]["username"] == "eva_k" and message["created_at"]
    assert anna.get("/dms").json()[0]["unread"] == 1
    summaries = anna.get("/dms").json()
    assert summaries[0]["user"]["username"] == "eva_k" and summaries[0]["last_message"]["content"] == "Szia Anna!"
    assert eva.get("/dms").json()[0]["unread"] == 0
    history = anna.get(f"/dms/{conversation}/messages").json()
    assert [m["content"] for m in history["messages"]] == ["Szia Anna!"] and history["last_read_message_id"] is None
    assert anna.post(f"/dms/{conversation}/read", {"message_id": message["id"]}).status_code == 200
    assert anna.get("/dms").json()[0]["unread"] == 0
    assert anna.get(f"/dms/{conversation}/messages").json()["last_read_message_id"] == message["id"]
    assert any(n["type"] == "dm" for n in anna.get("/notifications").json()["items"])


def test_conversation_details_are_available_before_the_first_message(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    mallory = make_user("mallory")
    detail = eva.get(f"/dms/{conversation}").json()
    assert detail["id"] == conversation and detail["user"]["username"] == "anna_t" and detail["last_message"] is None
    assert eva.get("/dms").json() == []
    assert mallory.get(f"/dms/{conversation}").status_code == 404


def test_dm_conversations_are_private_to_their_participants(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    mallory = make_user("mallory")
    eva.post(f"/dms/{conversation}/messages", {"content": "titkos"})
    assert mallory.get(f"/dms/{conversation}/messages").status_code == 404
    assert mallory.post(f"/dms/{conversation}/messages", {"content": "x"}).status_code == 404
    assert mallory.post(f"/dms/{conversation}/read", {"message_id": "1"}).status_code == 404
    assert mallory.get("/dms").json() == []


def test_dm_privacy_policy_and_blocks(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    assert eva.post("/dms", {"user_id": anna.uid}).json()["error"]["code"] == "dm_not_allowed"
    set_privacy(anna, direct_messages="everyone")
    conversation = open_dm(eva, anna)
    assert eva.post(f"/dms/{conversation}/messages", {"content": "hello"}).status_code == 200
    set_privacy(anna, direct_messages="friends")
    assert eva.post(f"/dms/{conversation}/messages", {"content": "mégegyszer"}).json()["error"]["code"] == "dm_not_allowed"
    assert [m["content"] for m in eva.get(f"/dms/{conversation}/messages").json()["messages"]] == ["hello"]
    assert eva.post("/dms", {"user_id": eva.uid}).status_code == 422


def test_blocking_stops_dm_delivery_but_keeps_history(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    eva.post(f"/dms/{conversation}/messages", {"content": "regi"})
    anna.put(f"/blocks/{eva.uid}")
    assert eva.post(f"/dms/{conversation}/messages", {"content": "uj"}).status_code == 403
    assert anna.post(f"/dms/{conversation}/messages", {"content": "uj"}).status_code == 403
    assert len(anna.get(f"/dms/{conversation}/messages").json()["messages"]) == 1


def test_message_validation(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    path = f"/dms/{conversation}/messages"
    assert eva.post(path, {"content": "   "}).json()["error"]["code"] == "message_empty"
    assert eva.post(path, {"content": "x" * 4001}).json()["error"]["code"] == "message_too_long"
    assert eva.post(path, {"content": "x" * 9000}).status_code == 422
    assert eva.post(path, {"content": "ok", "reply_to_id": "abc"}).status_code == 422
    assert eva.post(path, {"content": "a\x00b"}).json()["content"] == "ab"


def test_replies_and_deletion(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    first = eva.post(f"/dms/{conversation}/messages", {"content": "Mikor van a dolgozat?"}).json()
    reply = anna.post(f"/dms/{conversation}/messages", {"content": "Pénteken.", "reply_to_id": first["id"]}).json()
    assert reply["reply_to"]["preview"] == "Mikor van a dolgozat?" and reply["reply_to"]["author_id"] == eva.uid
    assert anna.delete(f"/dms/{conversation}/messages/{first['id']}").status_code == 403
    assert eva.delete(f"/dms/{conversation}/messages/{first['id']}").status_code == 200
    history = anna.get(f"/dms/{conversation}/messages").json()["messages"]
    assert history[0]["deleted"] is True and history[0]["content"] is None
    assert history[1]["reply_to"]["deleted"] is True and history[1]["reply_to"]["preview"] is None
    assert anna.post(f"/dms/{conversation}/messages", {"content": "x", "reply_to_id": first["id"]}).json()["error"]["code"] == "reply_target_invalid"
    assert sql_rows(eva.app, "SELECT COUNT(*) FROM message_contents WHERE message_id=?", (int(first["id"]),))[0][0] == 0
    assert sql_rows(eva.app, "SELECT COUNT(*) FROM message_search_tokens WHERE message_id=?", (int(first["id"]),))[0][0] == 0


def test_cannot_reply_across_conversations(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    bence = make_user("bence_s")
    befriend(eva, bence)
    other = open_dm(eva, bence)
    foreign = eva.post(f"/dms/{other}/messages", {"content": "mas beszelgetes"}).json()
    response = eva.post(f"/dms/{conversation}/messages", {"content": "x", "reply_to_id": foreign["id"]})
    assert response.json()["error"]["code"] == "reply_target_invalid"


def test_reactions(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    message = eva.post(f"/dms/{conversation}/messages", {"content": "Szuper"}).json()
    base = f"/dms/{conversation}/messages/{message['id']}/reactions"
    assert anna.put(base, {"emoji": "👍"}).status_code == 200
    assert eva.put(base, {"emoji": "👍"}).status_code == 200
    assert anna.put(base, {"emoji": "🎉"}).status_code == 200
    reactions = {r["emoji"]: r for r in anna.get(f"/dms/{conversation}/messages").json()["messages"][0]["reactions"]}
    assert reactions["👍"]["count"] == 2 and reactions["👍"]["me"] is True and reactions["🎉"]["count"] == 1
    assert anna.put(base, {"emoji": "💩"}).json()["error"]["code"] == "reaction_not_allowed"
    assert anna.put(base, {"emoji": "<script>"}).json()["error"]["code"] == "reaction_not_allowed"
    assert anna.delete(base, params={"emoji": "👍"}).status_code == 200
    after = {r["emoji"]: r for r in eva.get(f"/dms/{conversation}/messages").json()["messages"][0]["reactions"]}
    assert after["👍"]["count"] == 1 and after["👍"]["me"] is True


def test_reporting_a_dm_snapshots_context_and_escalates(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    anna.post(f"/dms/{conversation}/messages", {"content": "Előzmény üzenet"})
    bad = eva.post(f"/dms/{conversation}/messages", {"content": "Sértő üzenet"}).json()
    report = anna.post(f"/dms/{conversation}/messages/{bad['id']}/report", {"reason": "harassment", "details": "Bántó"})
    assert report.status_code == 200
    summary = report.json()["report"]
    assert summary["escalated"] is True and summary["status"] == "open" and summary["target_user_id"] == eva.uid
    assert anna.post(f"/dms/{conversation}/messages/{bad['id']}/report", {"reason": "spam"}).status_code == 409
    own = anna.post(f"/dms/{conversation}/messages", {"content": "enyém"}).json()
    assert anna.post(f"/dms/{conversation}/messages/{own['id']}/report", {"reason": "spam"}).status_code == 422
    assert anna.post(f"/dms/{conversation}/messages/{bad['id']}/report", {"reason": "nonsense"}).status_code == 422
    snapshot = sql_rows(eva.app, "SELECT snapshot_enc FROM reports")[0][0]
    assert b"rt\xc5\x91" not in snapshot and "Sértő".encode() not in snapshot


def test_normal_users_cannot_reach_moderation_endpoints(make_user):
    eva = make_user("eva_k")
    for path in ("/moderation/reports", "/moderation/audit", "/moderation/users/lookup?q=ab"):
        assert eva.get(path).status_code == 404
    assert eva.post(f"/moderation/users/{eva.uid}/identity", {"reason": "csak kivancsisag"}).status_code == 404
    assert eva.post(f"/moderation/users/{eva.uid}/status", {"status": "suspended", "reason": "csak kivancsisag"}).status_code == 404


def test_school_moderators_review_reports_and_reveal_identity_with_an_audit_trail(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    staff = make_user("tanar_ur")
    promote(eva.app, "tanar_ur", "school_moderator")
    bad = eva.post(f"/dms/{conversation}/messages", {"content": "Sértő üzenet"}).json()
    anna.post(f"/dms/{conversation}/messages/{bad['id']}/report", {"reason": "harassment"})
    reports = staff.get("/moderation/reports").json()
    assert len(reports) == 1 and reports[0]["target"]["username"] == "eva_k"
    detail = staff.get(f"/moderation/reports/{reports[0]['id']}").json()
    assert [c["content"] for c in detail["context"]] == ["Sértő üzenet"]
    assert detail["context"][0]["reported"] is True and detail["context"][0]["author"]["username"] == "eva_k"
    assert "Kiss" not in str(detail)
    assert staff.post(f"/moderation/users/{eva.uid}/identity", {"reason": "rövid"}).status_code == 422
    revealed = staff.post(f"/moderation/users/{eva.uid}/identity", {"reason": "Jelentés kivizsgálása", "report_id": reports[0]["id"]})
    assert revealed.status_code == 200
    body = revealed.json()
    assert body["full_name"] == "Kiss Éva" and body["username"] == "eva_k" and body["user_id"] == eva.uid
    resolved = staff.post(f"/moderation/reports/{reports[0]['id']}/resolve", {"resolution": "resolved", "note": "Figyelmeztetés"})
    assert resolved.json()["status"] == "resolved" and staff.get("/moderation/reports").json() == []
    assert len(staff.get("/moderation/reports", params={"status": "resolved"}).json()) == 1
    assert staff.get("/moderation/audit").status_code == 403
    promote(eva.app, "tanar_ur", "school_admin")
    entries = staff.get("/moderation/audit").json()["entries"]
    actions = [e["action"] for e in entries]
    assert "platform.identity_reveal" in actions and "platform.report_view" in actions and "report.resolve" in actions
    reveal = next(e for e in entries if e["action"] == "platform.identity_reveal")
    assert reveal["actor"]["username"] == "tanar_ur" and reveal["target_user"]["username"] == "eva_k"
    assert reveal["details"]["reason"] == "Jelentés kivizsgálása" and "Kiss" not in str(reveal)


def test_only_school_admins_can_suspend_accounts(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    mod, admin = make_user("moderator_u"), make_user("admin_u")
    promote(eva.app, "moderator_u", "school_moderator")
    promote(eva.app, "admin_u", "school_admin")
    reason = {"status": "suspended", "reason": "Ismételt zaklatás"}
    assert mod.post(f"/moderation/users/{eva.uid}/status", reason).status_code == 403
    assert admin.post(f"/moderation/users/{eva.uid}/status", reason).json() == {"status": "suspended"}
    assert eva.get("/me").status_code == 401 or eva.get("/me").status_code == 403
    login = eva.login()
    assert login.status_code == 403 and login.json()["error"]["code"] == "account_suspended"
    assert admin.post(f"/moderation/users/{eva.uid}/status", {"status": "active", "reason": "Fellebbezés elfogadva"}).status_code == 200
    assert eva.login().status_code == 200
    assert admin.post(f"/moderation/users/{admin.uid}/status", reason).status_code == 404


def test_message_lookup_requires_a_reason_and_is_audited(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    admin = make_user("admin_u")
    promote(eva.app, "admin_u", "school_admin")
    message = eva.post(f"/dms/{conversation}/messages", {"content": "vizsgalt uzenet"}).json()
    assert admin.post("/moderation/messages/lookup", {"message_id": message["id"], "reason": "x"}).status_code == 422
    found = admin.post("/moderation/messages/lookup", {"message_id": message["id"], "reason": "Panasz kivizsgálása"}).json()
    assert found["scope"] == "dm" and found["context"][0]["content"] == "vizsgalt uzenet"
    assert any(e["action"] == "platform.message_view" for e in admin.get("/moderation/audit").json()["entries"])
    assert eva.post("/moderation/messages/lookup", {"message_id": message["id"], "reason": "Panasz kivizsgálása"}).status_code == 404


def test_channel_messages_roles_and_moderation(make_user):
    (owner, mod, member), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    assign(owner, sid, mod, role_named(detail, "moderator")["id"])
    channel = first_channel(detail, "text")
    path = f"/channels/{channel['id']}/messages"
    posted = member.post(path, {"content": "Sziasztok!"}).json()
    assert posted["channel_id"] == channel["id"] and posted["author"]["nickname"] is None and posted["author"]["is_member"] is True
    other = owner.post(path, {"content": "Üdv"}).json()
    assert member.delete(f"/channels/{channel['id']}/messages/{other['id']}").status_code == 403
    assert mod.delete(f"/channels/{channel['id']}/messages/{posted['id']}").status_code == 200
    assert any(n["payload"].get("kind") == "message_removed" for n in member.get("/notifications").json()["items"])
    entries = owner.get(f"/servers/{sid}/audit-logs").json()["entries"]
    assert any(e["action"] == "message.delete" for e in entries)
    assert "Sziasztok" not in str(entries)
    assert owner.delete(f"/channels/{channel['id']}/messages/{other['id']}").status_code == 200


def test_pins_need_manage_messages(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    channel = first_channel(detail, "text")
    message = member.post(f"/channels/{channel['id']}/messages", {"content": "Fontos"}).json()
    assert member.put(f"/channels/{channel['id']}/pins/{message['id']}").status_code == 403
    assert owner.put(f"/channels/{channel['id']}/pins/{message['id']}").status_code == 200
    pins = member.get(f"/channels/{channel['id']}/pins").json()
    assert [p["content"] for p in pins] == ["Fontos"] and pins[0]["pinned"] is True
    assert owner.delete(f"/channels/{channel['id']}/pins/{message['id']}").status_code == 200
    assert member.get(f"/channels/{channel['id']}/pins").json() == []


def test_slowmode_is_enforced_per_user_and_skipped_for_moderators(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    channel = first_channel(detail, "text")
    owner.patch(f"/channels/{channel['id']}", {"slowmode_seconds": 30})
    path = f"/channels/{channel['id']}/messages"
    assert member.post(path, {"content": "egy"}).status_code == 200
    again = member.post(path, {"content": "ketto"})
    assert again.status_code == 429 and again.json()["error"]["code"] == "slowmode_active"
    assert 0 < int(again.headers["Retry-After"]) <= 30
    assert owner.post(path, {"content": "tulaj kivétel"}).status_code == 200
    assert owner.post(path, {"content": "tulaj ujra"}).status_code == 200
    owner.patch(f"/channels/{channel['id']}", {"slowmode_seconds": 0})
    assert member.post(path, {"content": "mehet"}).status_code == 200


def test_mention_limit_is_configurable_per_server(make_user):
    (owner, member, other), detail, _ = setup_server(make_user, 3)
    channel = first_channel(detail, "text")
    owner.patch(f"/servers/{detail['id']}", {"moderation_settings": {"max_mentions_per_message": 1}})
    many = other.post(f"/channels/{channel['id']}/messages", {"content": f"<@{member.uid}> <@{owner.uid}>"})
    assert many.status_code == 422 and many.json()["error"]["code"] == "too_many_mentions"
    assert other.post(f"/channels/{channel['id']}/messages", {"content": f"<@{member.uid}>"}).status_code == 200


def test_mentions_notify_only_people_who_can_see_the_channel(make_user):
    (owner, member, other), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    private = owner.post(f"/servers/{sid}/channels", {"name": "privat", "type": "text"}).json()
    default_role = next(r for r in detail["roles"] if r["is_default"])
    owner.put(f"/channels/{private['id']}/overwrites/role/{default_role['id']}", {"deny": ["view_channel"]})
    owner.put(f"/channels/{private['id']}/overwrites/member/{member.uid}", {"allow": ["view_channel"]})
    owner.post(f"/channels/{private['id']}/messages", {"content": f"<@{member.uid}> <@{other.uid}> gyere"})
    assert any(n["type"] == "mention" and n["payload"]["channel_name"] == "privat" for n in member.get("/notifications").json()["items"])
    assert other.get("/notifications").json()["items"] == []
    mention_rows = sql_rows(owner.app, "SELECT user_id FROM message_mentions")
    assert [int(r[0]) for r in mention_rows] == [int(member.uid)]


def test_unread_counts_per_channel(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    sid = detail["id"]
    channel = first_channel(detail, "text")
    owner.post(f"/channels/{channel['id']}/messages", {"content": "egy"})
    last = owner.post(f"/channels/{channel['id']}/messages", {"content": "ketto"}).json()
    assert member.get(f"/servers/{sid}").json()["unread"] == {channel["id"]: 2}
    assert owner.get(f"/servers/{sid}").json()["unread"] == {}
    member.post(f"/channels/{channel['id']}/read", {"message_id": last["id"]})
    assert member.get(f"/servers/{sid}").json()["unread"] == {}


def test_voice_channels_do_not_accept_messages(make_user):
    owner = make_user("tulaj")
    detail = create_server(owner)
    voice = first_channel(detail, "voice")
    assert owner.post(f"/channels/{voice['id']}/messages", {"content": "x"}).json()["error"]["code"] == "channel_type_invalid"


def test_server_reports_are_visible_to_server_moderators_without_identity(make_user):
    (owner, mod, member, other), detail, _ = setup_server_four(make_user)
    sid = detail["id"]
    assign(owner, sid, mod, role_named(detail, "moderator")["id"])
    channel = first_channel(detail, "text")
    posted = other.post(f"/channels/{channel['id']}/messages", {"content": "Kéretlen reklám"}).json()
    report = member.post(f"/channels/{channel['id']}/messages/{posted['id']}/report", {"reason": "spam"})
    assert report.status_code == 200 and report.json()["report"]["escalated"] is False
    listed = mod.get(f"/servers/{sid}/reports").json()
    assert len(listed) == 1 and listed[0]["context"][-1]["content"] == "Kéretlen reklám" or listed[0]["context"][0]["content"] == "Kéretlen reklám"
    assert "Kiss" not in str(listed) and "real" not in str(listed).lower()
    assert member.get(f"/servers/{sid}/reports").status_code == 403
    assert mod.post(f"/servers/{sid}/reports/{listed[0]['id']}/resolve", {"resolution": "resolved", "note": "Törölve"}).json()["status"] == "resolved"
    owner.patch(f"/servers/{sid}", {"moderation_settings": {"reports_enabled": False}})
    second = other.post(f"/channels/{channel['id']}/messages", {"content": "Még egy"}).json()
    again = member.post(f"/channels/{channel['id']}/messages/{second['id']}/report", {"reason": "spam"})
    assert again.json()["report"]["escalated"] is True


def setup_server_four(make_user):
    users = [make_user(name) for name in ("tulaj", "moderator_a", "tag_egy", "tag_ketto")]
    detail = create_server(users[0])
    code = users[0].get(f"/servers/{detail['id']}/invites").json()[0]["code"]
    for user in users[1:]:
        join_server(user, code)
    return users, detail, code


def test_search_finds_messages_accent_insensitively_and_respects_permissions(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    sid = detail["id"]
    public = first_channel(detail, "text")
    secret = owner.post(f"/servers/{sid}/channels", {"name": "titkos", "type": "text"}).json()
    default_role = next(r for r in detail["roles"] if r["is_default"])
    owner.put(f"/channels/{secret['id']}/overwrites/role/{default_role['id']}", {"deny": ["view_channel"]})
    owner.post(f"/channels/{public['id']}/messages", {"content": "A tanár úr holnap dolgozatot ír"})
    hidden = owner.post(f"/channels/{secret['id']}/messages", {"content": "A tanár titkos terve"}).json()
    found = member.get("/search", params={"q": "tanar", "types": "messages"}).json()["messages"]
    assert [m["message"]["content"] for m in found] == ["A tanár úr holnap dolgozatot ír"]
    assert found[0]["where"]["channel_name"] == "általános" and found[0]["where"]["server_name"] == "Teszt szerver"
    both = owner.get("/search", params={"q": "TANÁR", "types": "messages"}).json()["messages"]
    assert len(both) == 2
    assert member.get("/search", params={"q": "tanar ur dolgozatot", "types": "messages"}).json()["messages"][0]["message"]["author"]["username"] == "tulaj"
    assert member.get("/search", params={"q": "titkos", "types": "messages"}).json()["messages"] == []
    owner.delete(f"/channels/{secret['id']}/messages/{hidden['id']}")
    assert owner.get("/search", params={"q": "titkos terve", "types": "messages"}).json()["messages"] == []


def test_search_never_returns_other_peoples_direct_messages(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    mallory = make_user("mallory")
    eva.post(f"/dms/{conversation}/messages", {"content": "Titkos jelszóötlet bortörés"})
    assert mallory.get("/search", params={"q": "bortörés"}).json()["messages"] == []
    assert anna.get("/search", params={"q": "bortores", "types": "messages"}).json()["messages"][0]["where"]["user"]["username"] == "eva_k"


def test_search_covers_friends_servers_and_channels(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    befriend(owner, member)
    result = owner.get("/search", params={"q": "teszt"}).json()
    assert [s["name"] for s in result["servers"]] == ["Teszt szerver"]
    assert [f["username"] for f in owner.get("/search", params={"q": "tag_egy"}).json()["friends"]] == ["tag_egy"]
    assert [c["name"] for c in owner.get("/search", params={"q": "tarsalgo", "types": "channels"}).json()["channels"]] == ["Társalgó"]
    assert owner.get("/search", params={"q": "a"}).status_code == 422
