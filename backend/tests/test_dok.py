import sqlite3
import sys

import pytest

from app import cli
from app.config import get_settings

from .conftest import database_dump, database_path, sql_rows
from .test_messages import promote
from .test_social import befriend
from .test_websocket import ready, settle, types, wait_for

pytestmark = pytest.mark.timeout(60)


def class_id(user, code):
    return next(c["id"] for c in user.get("/me/classes").json() if c["code"] == code)


def join_class(user, code, visibility="hidden"):
    response = user.put("/me/class", {"class_id": class_id(user, code), "visibility": visibility})
    assert response.status_code == 200, response.text


def class_member(make_user, username, code):
    user = make_user(username)
    join_class(user, code)
    return user


def staff(make_user, username, role):
    user = make_user(username)
    promote(user.app, username, role)
    return user


def send(user, content, **target):
    return user.post("/dok/messages", {"content": content, "target": target})


def to_class(user, code, content="Szia osztály!"):
    return send(user, content, type="class", class_id=class_id(user, code))


def to_school(user, content="Szia iskola!"):
    return send(user, content, type="school")


def build_school(make_user):
    rep = class_member(make_user, "rep_eva", "9A")
    mate = class_member(make_user, "mate_anna", "9A")
    outsider = class_member(make_user, "out_bence", "10B")
    president = make_user("pres_dora")
    promote(rep.app, "rep_eva", "dok_representative")
    promote(rep.app, "pres_dora", "dok_president")
    return rep, mate, outsider, president


def codes(user):
    return [t["class"]["code"] if t["class"] else "school" for t in user.get("/dok/inbox").json()["threads"]]


def collect_until(ws, event_type, attempts=30):
    seen = []
    for _ in range(attempts):
        event = ws.receive_json()
        seen.append(event)
        if event["t"] == event_type:
            return seen
    raise AssertionError(f"event {event_type} never arrived")


def run_cli(monkeypatch, app, *arguments):
    monkeypatch.setenv("POLLAKCORD_DATABASE_URL", app.state.settings.database_url)
    monkeypatch.setattr(sys, "argv", ["pollakcord", *arguments])
    get_settings.cache_clear()
    try:
        return cli.main()
    finally:
        get_settings.cache_clear()


def test_representative_can_only_target_own_class(make_user):
    rep, mate, outsider, president = build_school(make_user)
    assert rep.get("/me").json()["platform_role"] == "dok_representative"
    sent = to_class(rep, "9A", "Holnap DÖK-gyűlés lesz.")
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["content"] == "Holnap DÖK-gyűlés lesz." and body["scope"] == "class" and body["mine"] is True
    assert body["author_role"] == "dok_representative" and body["created_at"]
    other = to_class(rep, "10B")
    assert other.status_code == 403 and other.json()["error"]["code"] == "dok_target_forbidden"
    school = to_school(rep)
    assert school.status_code == 403 and school.json()["error"]["code"] == "dok_target_forbidden"
    assert sql_rows(rep.app, "SELECT COUNT(*) FROM dok_threads")[0][0] == 1
    assert codes(mate) == ["9A"] and codes(outsider) == []
    assert rep.get("/dok/inbox").json()["send"] == {"allowed": True, "targets": [{"type": "class", "class_id": class_id(rep, "9A"), "code": "9A"}]}


def test_president_can_target_any_class_and_the_whole_school(make_user):
    rep, mate, outsider, president = build_school(make_user)
    join_class(president, "9A")
    loner = make_user("loner_ede")
    own = to_class(president, "9A", "Saját osztálynak")
    assert own.status_code == 200 and own.json()["author_role"] == "dok_president"
    foreign = to_class(president, "10B", "Másik osztálynak")
    assert foreign.status_code == 200 and foreign.json()["scope"] == "class"
    assert codes(outsider) == ["10B"] and codes(mate) == ["9A"]
    school = to_school(president, "Az egész iskolának")
    assert school.status_code == 200 and school.json()["scope"] == "school"
    for user in (rep, mate, outsider):
        assert "school" in codes(user)
    assert codes(loner) == []
    options = president.get("/dok/inbox").json()["send"]
    assert options["allowed"] is True and options["targets"][0] == {"type": "school"} and len(options["targets"]) == 13
    assert sorted(codes(president)) == ["10B", "9A", "school"]
    missing = send(president, "x", type="class", class_id="123")
    assert missing.status_code == 404


def test_inactive_classes_cannot_be_targeted(make_user):
    rep, mate, outsider, president = build_school(make_user)
    retired = class_id(president, "10B")
    connection = sqlite3.connect(database_path(rep.app))
    connection.execute("UPDATE school_classes SET is_active=0 WHERE code='10B'")
    connection.commit()
    connection.close()
    assert send(president, "x", type="class", class_id=retired).status_code == 404
    assert not any(t.get("code") == "10B" for t in president.get("/dok/inbox").json()["send"]["targets"])


def test_recipients_never_receive_the_real_author(make_user):
    rep, mate, outsider, president = build_school(make_user)
    sent = to_class(rep, "9A", "Titkos feladó").json()
    thread = sent["thread_id"]
    secrets_to_hide = (rep.username, "Rep_Eva", rep.uid)
    history = mate.get(f"/dok/threads/{thread}/messages")
    message = history.json()["messages"][0]
    assert message["author"] is None and message["mine"] is False and message["author_role"] == "dok_representative"
    for response in (history, mate.get("/dok/inbox"), mate.get("/notifications")):
        for secret in secrets_to_hide:
            assert secret not in response.text
    president_view = president.get(f"/dok/threads/{thread}/messages").json()["messages"][0]
    assert president_view["author"] is None
    own = rep.get(f"/dok/threads/{thread}/messages").json()["messages"][0]
    assert own["mine"] is True and own["author"]["username"] == "rep_eva"
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    for viewer in (moderator, admin):
        revealed = viewer.get(f"/dok/threads/{thread}/messages").json()["messages"][0]
        assert revealed["author"]["username"] == "rep_eva" and revealed["mine"] is False


def test_dok_roles_do_not_show_up_as_staff(make_user):
    rep, mate, outsider, president = build_school(make_user)
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    befriend(rep, mate)
    befriend(moderator, mate)
    cards = {card["username"]: card for card in mate.get("/friends").json()}
    assert cards["rep_eva"]["staff"] is False and cards["mod_ilona"]["staff"] is True
    assert rep.get("/me").json()["staff"] is False and moderator.get("/me").json()["staff"] is True


def test_dok_roles_have_no_moderation_access(make_user):
    rep, mate, outsider, president = build_school(make_user)
    for user in (rep, president):
        assert user.get("/moderation/reports").status_code == 404
        assert user.get("/moderation/audit").status_code == 404


def test_dok_notification_is_created_and_can_be_marked_read(make_user):
    rep, mate, outsider, president = build_school(make_user)
    classmate = class_member(make_user, "mate_gabor", "9A")
    sent = to_class(rep, "9A", "A szuloi ertekezlet csutortokon lesz.").json()
    for user in (mate, classmate):
        listing = user.get("/notifications").json()
        items = [n for n in listing["items"] if n["type"] == "dok_message"]
        assert len(items) == 1 and listing["unread"] == 1 and items[0]["read"] is False
        assert items[0]["payload"] == {
            "thread_id": sent["thread_id"],
            "dok_message_id": sent["id"],
            "scope": "class",
            "class_code": "9A",
            "author_role": "dok_representative",
            "preview": "A szuloi ertekezlet csutortokon lesz.",
        }
    assert rep.get("/notifications").json()["items"] == []
    assert outsider.get("/notifications").json()["items"] == []
    stored = sql_rows(rep.app, "SELECT payload FROM notifications WHERE type='dok_message'")
    assert len(stored) == 2 and all("szuloi" not in row[0] and "preview" not in row[0] for row in stored)
    first = mate.get("/notifications").json()["items"][0]["id"]
    assert mate.post("/notifications/read", {"ids": [first]}).status_code == 200
    after = mate.get("/notifications").json()
    assert after["unread"] == 0 and after["items"][0]["read"] is True
    assert classmate.get("/notifications").json()["unread"] == 1
    assert classmate.get("/dok/inbox").json()["unread"] == 1
    thread = sent["thread_id"]
    assert classmate.post(f"/dok/threads/{thread}/read", {"message_id": sent["id"]}).json() == {"status": "ok"}
    assert classmate.get("/notifications").json()["unread"] == 0
    assert classmate.get("/dok/inbox").json()["unread"] == 0
    assert classmate.get(f"/dok/threads/{thread}/messages").json()["last_read_message_id"] == sent["id"]
    assert outsider.post(f"/dok/threads/{thread}/read", {"message_id": sent["id"]}).status_code == 404


def test_previews_disappear_once_the_viewer_can_no_longer_read_the_thread(make_user):
    rep, mate, outsider, president = build_school(make_user)
    to_class(rep, "9A", "csak a 9A-nak")
    assert mate.get("/notifications").json()["items"][0]["payload"]["preview"] == "csak a 9A-nak"
    join_class(mate, "10B")
    payload = mate.get("/notifications").json()["items"][0]["payload"]
    assert "preview" not in payload and "csak a 9A-nak" not in str(payload)


def test_dok_notifications_can_be_muted_without_hiding_messages(make_user):
    rep, mate, outsider, president = build_school(make_user)
    assert mate.get("/me").json()["settings"]["notification_prefs"]["dok"] is True
    connection = sqlite3.connect(database_path(rep.app))
    connection.execute("UPDATE user_settings SET notification_prefs='{\"sounds\": true}'")
    connection.commit()
    connection.close()
    assert mate.get("/me").json()["settings"]["notification_prefs"]["dok"] is True
    assert mate.patch("/me/settings", {"notification_prefs": {"dok": False}}).status_code == 200
    to_class(rep, "9A", "néma értesítés")
    assert mate.get("/notifications").json()["unread"] == 0
    inbox = mate.get("/dok/inbox").json()
    assert inbox["unread"] == 1 and inbox["threads"][0]["last_message"]["preview"] == "néma értesítés"


def test_unauthorized_send_is_rejected(make_user, api):
    rep, mate, outsider, president = build_school(make_user)
    denied = to_class(mate, "9A")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "dok_send_forbidden"
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    for user in (moderator, admin, outsider):
        assert to_school(user).json()["error"]["code"] == "dok_send_forbidden"
    assert sql_rows(rep.app, "SELECT COUNT(*) FROM dok_messages")[0][0] == 0
    assert sql_rows(rep.app, "SELECT COUNT(*) FROM dok_threads")[0][0] == 0
    assert api.post("/dok/messages", {"content": "x", "target": {"type": "school"}}).status_code == 401
    assert api.get("/dok/inbox").status_code == 401
    assert mate.get("/dok/inbox").json()["send"] == {"allowed": False, "targets": []}
    assert rep.post("/dok/messages", {"content": "x", "target": {"type": "galaxy"}}).status_code == 422
    assert rep.post("/dok/messages", {"content": "x", "target": {"type": "class", "class_id": "abc"}}).status_code == 422
    assert rep.post("/dok/messages", {"content": "x"}).status_code == 422


def test_representative_without_a_class_cannot_send(make_user):
    loner = staff(make_user, "loner_ede", "dok_representative")
    assert loner.get("/dok/inbox").json()["send"] == {"allowed": False, "targets": []}
    assert to_school(loner).json()["error"]["code"] == "class_required"
    assert send(loner, "x", type="class", class_id="1000").json()["error"]["code"] == "class_required"


def test_representative_cannot_change_class_while_holding_the_role(make_user):
    rep, mate, outsider, president = build_school(make_user)
    moved = rep.put("/me/class", {"class_id": class_id(rep, "10B"), "visibility": "hidden"})
    assert moved.status_code == 403 and moved.json()["error"]["code"] == "dok_class_locked"
    cleared = rep.put("/me/class", {"class_id": None, "visibility": "hidden"})
    assert cleared.status_code == 403 and cleared.json()["error"]["code"] == "dok_class_locked"
    assert rep.put("/me/class", {"class_id": class_id(rep, "9A"), "visibility": "friends"}).status_code == 200
    assert to_class(rep, "10B").status_code == 403
    assert president.put("/me/class", {"class_id": class_id(president, "10B"), "visibility": "hidden"}).status_code == 200
    promote(rep.app, "rep_eva", "user")
    assert rep.put("/me/class", {"class_id": class_id(rep, "10B"), "visibility": "hidden"}).status_code == 200


def test_threads_are_only_readable_by_recipients_and_oversight_roles(make_user):
    rep, mate, outsider, president = build_school(make_user)
    thread = to_class(rep, "9A", "csak 9A").json()["thread_id"]
    base = f"/dok/threads/{thread}/messages"
    assert outsider.get(base).status_code == 404
    assert outsider.get(base).json()["error"]["code"] == "not_found"
    assert outsider.post(f"/dok/threads/{thread}/read", {"message_id": "1"}).status_code == 404
    assert outsider.get("/dok/threads/1/messages").status_code == 404
    assert outsider.get("/dok/threads/999999999999999999999/messages").status_code == 404
    assert mate.post(f"/dok/threads/{thread}/read", {"message_id": "99999999999999999999"}).status_code == 404
    assert mate.post(f"/dok/threads/{thread}/read", {"message_id": "abc"}).status_code == 422
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    for viewer in (mate, president, moderator, admin):
        assert viewer.get(base).status_code == 200
    assert moderator.get("/dok/inbox").json()["unread"] == 0


def test_inbox_lists_threads_with_unread_counts_and_send_rights(make_user):
    rep, mate, outsider, president = build_school(make_user)
    to_class(rep, "9A", "osztály")
    to_school(president, "iskola " + "x" * 200)
    to_class(president, "10B", "tízbé")
    inbox = rep.get("/dok/inbox").json()
    threads = {("school" if t["scope"] == "school" else t["class"]["code"]): t for t in inbox["threads"]}
    assert sorted(threads) == ["9A", "school"]
    assert threads["9A"]["unread"] == 0 and threads["9A"]["can_send"] is True
    assert threads["school"]["unread"] == 1 and threads["school"]["can_send"] is False
    assert inbox["unread"] == 1
    assert len(threads["school"]["last_message"]["preview"]) == 120
    everything = president.get("/dok/inbox").json()
    assert sorted(t["scope"] for t in everything["threads"]) == ["class", "class", "school"]
    assert all(t["can_send"] is True and t["unread"] == 0 for t in everything["threads"])
    assert [t["last_message"]["preview"] for t in everything["threads"]][0] == "tízbé"


def test_history_paginates_like_direct_messages(make_user):
    rep, mate, outsider, president = build_school(make_user)
    ids = [to_class(rep, "9A", f"üzenet {n}").json()["id"] for n in range(5)]
    thread = mate.get("/dok/inbox").json()["threads"][0]["id"]
    base = f"/dok/threads/{thread}/messages"
    page = mate.get(base, params={"limit": 2}).json()
    assert [m["id"] for m in page["messages"]] == ids[3:] and page["has_more"] is True and page["last_read_message_id"] is None
    older = mate.get(base, params={"limit": 2, "before": ids[3]}).json()
    assert [m["id"] for m in older["messages"]] == ids[1:3]
    newer = mate.get(base, params={"after": ids[2]}).json()
    assert [m["id"] for m in newer["messages"]] == ids[3:]
    assert mate.get(base, params={"limit": 0}).status_code == 422
    assert mate.get(base, params={"before": "abc"}).status_code == 422


def test_message_validation(make_user):
    rep, mate, outsider, president = build_school(make_user)
    assert to_class(rep, "9A", "   ").json()["error"]["code"] == "message_empty"
    assert to_class(rep, "9A", "x" * 4001).json()["error"]["code"] == "message_too_long"
    assert to_class(rep, "9A", "x" * 9000).status_code == 422
    assert sql_rows(rep.app, "SELECT COUNT(*) FROM dok_threads")[0][0] == 0
    assert to_class(rep, "9A", "a\x00b").json()["content"] == "ab"


def test_sends_are_rate_limited_per_user_and_per_target(make_user, monkeypatch):
    rep, mate, outsider, president = build_school(make_user)
    second = class_member(make_user, "rep_gabor", "9A")
    promote(rep.app, "rep_gabor", "dok_representative")
    rep.app.state.limiter.enabled = True
    monkeypatch.setattr("app.api.v1.dok.USER_SEND_LIMIT", (3, 60))
    monkeypatch.setattr("app.api.v1.dok.TARGET_SEND_LIMIT", (4, 60))
    for _ in range(6):
        assert to_class(mate, "9A").status_code == 403
    for _ in range(3):
        assert to_class(rep, "9A").status_code == 200
    limited = to_class(rep, "9A")
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited" and "retry-after" in limited.headers
    assert to_class(second, "9A").status_code == 200
    assert to_class(second, "9A").status_code == 429
    assert to_class(president, "10B").status_code == 200


def test_every_send_is_audited_with_the_real_author(make_user):
    rep, mate, outsider, president = build_school(make_user)
    admin = staff(make_user, "admin_vera", "school_admin")
    sent = to_class(rep, "9A", "naplózott üzenet").json()
    to_school(president, "iskolai üzenet")
    entries = [e for e in admin.get("/moderation/audit").json()["entries"] if e["action"] == "dok.message_send"]
    by_actor = {e["actor"]["username"]: e for e in entries}
    assert sorted(by_actor) == ["pres_dora", "rep_eva"]
    class_entry = by_actor["rep_eva"]
    assert class_entry["target_type"] == "dok_message" and class_entry["target_id"] == sent["id"]
    assert class_entry["details"] == {
        "thread_id": sent["thread_id"],
        "scope": "class",
        "class_id": class_id(rep, "9A"),
        "author_role": "dok_representative",
        "recipients": 1,
    }
    school_entry = by_actor["pres_dora"]
    assert school_entry["details"]["scope"] == "school" and school_entry["details"]["class_id"] is None and school_entry["details"]["recipients"] == 3
    assert "naplózott" not in str(entries) and "iskolai" not in str(entries)
    assert sql_rows(rep.app, "SELECT COUNT(*) FROM audit_logs WHERE action='dok.message_send' AND server_id IS NULL")[0][0] == 2


def test_dok_bodies_are_encrypted_and_bound_to_their_row(make_user):
    rep, mate, outsider, president = build_school(make_user)
    to_class(rep, "9A", "elso titkos szoveg")
    to_class(rep, "9A", "masodik titkos szoveg")
    rows = sql_rows(rep.app, "SELECT id, body_enc FROM dok_messages ORDER BY id")
    assert len(rows) == 2 and all(b"titkos" not in bytes(blob) for _, blob in rows)
    assert "titkos szoveg" not in database_dump(rep.app)
    thread = mate.get("/dok/inbox").json()["threads"][0]["id"]
    assert [m["content"] for m in mate.get(f"/dok/threads/{thread}/messages").json()["messages"]] == ["elso titkos szoveg", "masodik titkos szoveg"]
    connection = sqlite3.connect(database_path(rep.app))
    connection.execute("UPDATE dok_messages SET body_enc=? WHERE id=?", (rows[1][1], rows[0][0]))
    connection.execute("UPDATE dok_messages SET body_enc=? WHERE id=?", (rows[0][1], rows[1][0]))
    connection.commit()
    connection.close()
    swapped = mate.get(f"/dok/threads/{thread}/messages").json()["messages"]
    assert [m["content"] for m in swapped] == ["", ""]
    assert mate.get("/dok/inbox").json()["threads"][0]["last_message"]["preview"] == ""


def test_admin_can_suspend_dok_roles_but_not_staff(make_user):
    rep, mate, outsider, president = build_school(make_user)
    admin = staff(make_user, "admin_vera", "school_admin")
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    reason = "visszaélés a DÖK-csatornával"
    suspended = admin.post(f"/moderation/users/{rep.uid}/status", {"status": "suspended", "reason": reason})
    assert suspended.status_code == 200 and suspended.json() == {"status": "suspended"}
    assert rep.get("/dok/inbox").status_code in (401, 403)
    assert admin.post(f"/moderation/users/{moderator.uid}/status", {"status": "suspended", "reason": reason}).status_code == 404


def test_suspended_accounts_do_not_receive_dok_messages(make_user):
    rep, mate, outsider, president = build_school(make_user)
    classmate = class_member(make_user, "mate_gabor", "9A")
    admin = staff(make_user, "admin_vera", "school_admin")
    admin.post(f"/moderation/users/{classmate.uid}/status", {"status": "suspended", "reason": "teszt felfüggesztés"})
    to_class(rep, "9A", "felfüggesztettnek nem")
    assert sql_rows(rep.app, "SELECT COUNT(*) FROM notifications WHERE user_id=? AND type='dok_message'", (int(classmate.uid),))[0][0] == 0
    assert mate.get("/notifications").json()["unread"] == 1


def test_dok_message_event_reaches_recipients_without_content_or_author(make_user):
    rep, mate, outsider, president = build_school(make_user)
    with rep.websocket() as wr, mate.websocket() as wm, outsider.websocket() as wo:
        for socket in (wr, wm, wo):
            ready(socket)
        sent = to_class(rep, "9A", "élő üzenet").json()
        seen = collect_until(wm, "dok.message")
        event = seen[-1]
        assert event["d"] == {"thread_id": sent["thread_id"], "message_id": sent["id"]}
        notifications = [e for e in seen if e["t"] == "notification.create"]
        assert len(notifications) == 1 and notifications[0]["d"]["type"] == "dok_message"
        assert "preview" not in notifications[0]["d"]["payload"]
        for secret in (rep.username, "Rep_Eva", rep.uid, "élő üzenet"):
            assert secret not in str(seen)
        assert wait_for(wr, "dok.message")["d"] == event["d"]
        assert "dok.message" not in types(settle(wo))
        assert "notification.create" not in types(settle(wr))


def test_grant_role_accepts_dok_roles_and_requires_a_class_for_representatives(make_user, monkeypatch, capsys):
    loner = make_user("loner_ede")
    member = class_member(make_user, "mate_anna", "9A")
    app = loner.app
    assert run_cli(monkeypatch, app, "grant-role", "loner_ede", "dok_representative") == 1
    assert "user has no class" in capsys.readouterr().err
    assert sql_rows(app, "SELECT platform_role FROM users WHERE username_lower='loner_ede'")[0][0] == "user"
    assert run_cli(monkeypatch, app, "grant-role", "mate_anna", "dok_representative") == 0
    assert sql_rows(app, "SELECT platform_role FROM users WHERE username_lower='mate_anna'")[0][0] == "dok_representative"
    assert run_cli(monkeypatch, app, "grant-role", "loner_ede", "dok_president") == 0
    assert sql_rows(app, "SELECT platform_role FROM users WHERE username_lower='loner_ede'")[0][0] == "dok_president"
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, app, "grant-role", "loner_ede", "dok_emperor")
    assert member.get("/dok/inbox").json()["send"]["allowed"] is True
