import json
import re
import sqlite3

import pytest

from .conftest import database_dump, database_path, sql_rows
from .test_messages import promote
from .test_websocket import ready, settle, types, wait_for

pytestmark = pytest.mark.timeout(60)

EMPTY_STATE = {"class": None, "member": False, "prompt_required": False, "show_username": None, "alias": None, "members": None, "unread": 0}


def class_id(user, code):
    return next(c["id"] for c in user.get("/me/classes").json() if c["code"] == code)


def join_class(user, code, visibility="hidden"):
    response = user.put("/me/class", {"class_id": class_id(user, code), "visibility": visibility})
    assert response.status_code == 200, response.text


def answer(user, show_username):
    response = user.put("/class-spaces/me/visibility", {"show_username": show_username})
    assert response.status_code == 200, response.text
    return response.json()


def classmate(make_user, username, code, shows=None):
    user = make_user(username)
    join_class(user, code)
    if shows is not None:
        answer(user, shows)
    return user


def staff(make_user, username, role):
    user = make_user(username)
    promote(user.app, username, role)
    return user


def space(user):
    return user.get("/class-spaces/me").json()


def base_of(user, code="9A"):
    return f"/class-spaces/{class_id(user, code)}"


def say(user, content, code="9A"):
    return user.post(f"{base_of(user, code)}/messages", {"content": content})


def feed(user, code="9A", **params):
    return user.get(f"{base_of(user, code)}/messages", params=params).json()


def usernames(listing):
    return [entry["user"]["username"] for entry in listing["members"]]


def count_rows(app, table):
    return sql_rows(app, f"SELECT COUNT(*) FROM {table}")[0][0]


def test_user_without_a_class_cannot_join_a_class_space(make_user, api):
    loner = make_user("loner_ede")
    assert space(loner) == EMPTY_STATE
    refused = loner.put("/class-spaces/me/visibility", {"show_username": True})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "class_required"
    assert count_rows(loner.app, "class_space_members") == 0
    target = class_id(loner, "9A")
    assert loner.get(f"/class-spaces/{target}/messages").status_code == 404
    assert loner.get(f"/class-spaces/{target}/members").status_code == 404
    assert loner.post(f"/class-spaces/{target}/messages", {"content": "szia"}).status_code == 404
    assert api.get("/class-spaces/me").status_code == 401
    assert api.put("/class-spaces/me/visibility", {"show_username": True}).status_code == 401


def test_users_with_a_class_are_prompted_until_they_answer(make_user):
    eva = classmate(make_user, "eva_k", "9A")
    state = space(eva)
    assert state["prompt_required"] is True and state["member"] is False and state["show_username"] is None
    assert state["class"] == {"id": class_id(eva, "9A"), "code": "9A"} and state["members"] is None and state["alias"] is None
    assert eva.get(f"{base_of(eva)}/messages").status_code == 404
    assert say(eva, "Még nem vagyok tag").status_code == 404
    assert count_rows(eva.app, "class_space_members") == 0
    answered = answer(eva, False)
    assert answered["prompt_required"] is False and answered["member"] is True and answered["show_username"] is False
    assert space(eva)["prompt_required"] is False
    assert sql_rows(eva.app, "SELECT show_username, answered_at IS NOT NULL FROM class_space_members") == [(0, 1)]
    eva.login()
    assert space(eva)["prompt_required"] is False and space(eva)["member"] is True


def test_answering_yes_adds_the_member_and_shows_the_username_to_classmates(make_user):
    eva = classmate(make_user, "eva_k", "9A")
    anna = classmate(make_user, "anna_t", "9A")
    state = answer(eva, True)
    assert state["member"] is True and state["show_username"] is True and state["members"] == 1
    answer(anna, True)
    assert say(eva, "Sziasztok!").status_code == 200
    base = base_of(anna)
    listing = anna.get(f"{base}/members").json()
    assert sorted(usernames(listing)) == ["anna_t", "eva_k"] and listing["hidden_count"] == 0 and listing["total"] == 2
    assert listing["class"] == {"id": class_id(anna, "9A"), "code": "9A"}
    message = feed(anna)["messages"][0]
    assert message["author"]["username"] == "eva_k" and message["author"]["id"] == eva.uid
    assert message["alias"] is None and message["mine"] is False and message["content"] == "Sziasztok!"


def test_answering_no_adds_the_member_but_peers_never_see_the_username(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=False)
    anna = classmate(make_user, "anna_t", "9A", shows=True)
    state = space(eva)
    assert state["member"] is True and state["show_username"] is False and re.fullmatch(r"[0-9a-f]{6}", state["alias"])
    sent = say(eva, "Titkos üzenet")
    assert sent.status_code == 200
    assert sent.json()["mine"] is True and sent.json()["author"]["username"] == "eva_k" and sent.json()["alias"] is None
    seen = feed(anna)
    message = seen["messages"][0]
    assert message["author"] is None and message["mine"] is False and message["alias"] == state["alias"]
    listing = anna.get(f"{base_of(anna)}/members").json()
    assert usernames(listing) == ["anna_t"] and listing["hidden_count"] == 1 and listing["total"] == 2
    peer_view = json.dumps([seen, listing, space(anna)])
    for secret in (eva.username, eva.uid, "Eva_K"):
        assert secret not in peer_view
    assert sql_rows(eva.app, "SELECT author_id, author_visible FROM class_space_messages") == [(int(eva.uid), 0)]


def test_anonymous_labels_are_stable_per_member_and_differ_between_members(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=False)
    anna = classmate(make_user, "anna_t", "9A", shows=False)
    gabor = classmate(make_user, "gabor_m", "9A", shows=True)
    outsider = classmate(make_user, "out_bence", "10B", shows=False)
    for text in ("egy", "kettő"):
        say(eva, text)
    say(anna, "három")
    messages = feed(gabor)["messages"]
    aliases = [m["alias"] for m in messages]
    assert aliases[0] == aliases[1] and aliases[0] != aliases[2] and None not in aliases
    assert aliases[0] == space(eva)["alias"] and aliases[2] == space(anna)["alias"]
    assert space(outsider)["alias"] != space(eva)["alias"]


def test_changing_the_preference_never_exposes_earlier_anonymous_messages(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=False)
    anna = classmate(make_user, "anna_t", "9A", shows=True)
    anonymous_alias = space(eva)["alias"]
    say(eva, "Névtelenül írtam")
    assert answer(eva, True)["show_username"] is True
    say(eva, "Már látszom")
    seen = {m["content"]: m for m in feed(anna)["messages"]}
    assert seen["Névtelenül írtam"]["author"] is None and seen["Névtelenül írtam"]["alias"] == anonymous_alias
    assert seen["Már látszom"]["author"]["username"] == "eva_k" and seen["Már látszom"]["alias"] is None
    assert sorted(usernames(anna.get(f"{base_of(anna)}/members").json())) == ["anna_t", "eva_k"]
    answer(eva, False)
    hidden = {m["content"]: m for m in feed(anna)["messages"]}
    assert hidden["Már látszom"]["author"] is None and hidden["Már látszom"]["alias"] is None
    assert hidden["Névtelenül írtam"]["author"] is None and hidden["Névtelenül írtam"]["alias"] == anonymous_alias
    listing = anna.get(f"{base_of(anna)}/members").json()
    assert usernames(listing) == ["anna_t"] and listing["hidden_count"] == 1
    own = feed(eva)["messages"]
    assert [m["author"]["username"] for m in own] == ["eva_k", "eva_k"] and all(m["mine"] for m in own)


def test_changing_class_leaves_the_old_space_and_asks_again(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    anna = classmate(make_user, "anna_t", "9A", shows=True)
    old = class_id(eva, "9A")
    say(eva, "Régi osztály")
    assert anna.get(f"/class-spaces/{old}/members").json()["total"] == 2
    join_class(eva, "10B")
    state = space(eva)
    assert state["class"]["code"] == "10B" and state["member"] is False and state["prompt_required"] is True
    assert eva.get(f"/class-spaces/{old}/messages").status_code == 404
    assert eva.get(f"/class-spaces/{old}/members").status_code == 404
    assert count_rows(eva.app, "class_space_members") == 1
    peers = anna.get(f"/class-spaces/{old}/members").json()
    assert usernames(peers) == ["anna_t"] and peers["total"] == 1
    farewell = feed(anna)["messages"][0]
    assert farewell["author"] is None and farewell["alias"] is None
    assert eva.get(f"{base_of(eva, '10B')}/messages").status_code == 404
    answer(eva, False)
    assert space(eva)["member"] is True and space(eva)["class"]["code"] == "10B"
    assert feed(eva, "10B")["messages"] == []
    assert eva.get(f"/class-spaces/{old}/messages").status_code == 404
    join_class(anna, "9A", "friends")
    assert space(anna)["member"] is True and space(anna)["prompt_required"] is False
    cleared = eva.put("/me/class", {"class_id": None, "visibility": "hidden"})
    assert cleared.status_code == 200
    assert space(eva) == EMPTY_STATE
    assert sql_rows(eva.app, "SELECT user_id FROM class_space_members") == [(int(anna.uid),)]
    assert say(eva, "x", "10B").status_code == 404


def test_returning_to_a_class_needs_a_fresh_answer(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    join_class(eva, "10B")
    join_class(eva, "9A")
    state = space(eva)
    assert state["member"] is False and state["prompt_required"] is True and state["show_username"] is None
    assert answer(eva, False)["show_username"] is False


def test_a_stale_membership_row_never_grants_access(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    anna = classmate(make_user, "anna_t", "9A", shows=True)
    old = class_id(eva, "9A")
    say(eva, "Még itt vagyok")
    connection = sqlite3.connect(database_path(eva.app))
    connection.execute("UPDATE users SET school_class_id=? WHERE username_lower='eva_k'", (int(class_id(eva, "10B")),))
    connection.commit()
    connection.close()
    assert eva.get(f"/class-spaces/{old}/messages").status_code == 404
    assert say(eva, "Nem szabad", "10B").status_code == 404
    state = space(eva)
    assert state["member"] is False and state["prompt_required"] is True
    assert usernames(anna.get(f"/class-spaces/{old}/members").json()) == ["anna_t"]
    assert feed(anna)["messages"][0]["author"] is None


def test_non_members_get_a_plain_404_everywhere(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    outsider = classmate(make_user, "out_bence", "10B", shows=True)
    pending = classmate(make_user, "pend_dora", "9A")
    loner = make_user("loner_ede")
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    representative = classmate(make_user, "rep_gabor", "9A")
    promote(representative.app, "rep_gabor", "dok_representative")
    president = classmate(make_user, "pres_hanna", "9B", shows=True)
    promote(president.app, "pres_hanna", "dok_president")
    sent = say(eva, "csak 9A").json()
    base = base_of(eva)
    for viewer in (outsider, pending, loner, moderator, admin, representative, president):
        assert viewer.get(f"{base}/messages").status_code == 404
        assert viewer.get(f"{base}/members").status_code == 404
        assert viewer.post(f"{base}/messages", {"content": "x"}).status_code == 404
        assert viewer.post(f"{base}/read", {"message_id": sent["id"]}).status_code == 404
        assert viewer.delete(f"{base}/messages/{sent['id']}").status_code == 404
        assert viewer.post(f"{base}/messages/{sent['id']}/report", {"reason": "spam"}).status_code == 404
    assert outsider.get(f"{base}/messages").json()["error"]["code"] == "not_found"
    assert count_rows(eva.app, "class_space_messages") == 1
    assert count_rows(eva.app, "reports") == 0
    for viewer in (moderator, admin, representative):
        assert space(viewer)["member"] is False
    assert space(president)["member"] is True


def test_malformed_ids_are_rejected_without_leaking_anything(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    other = classmate(make_user, "out_bence", "10B", shows=True)
    base = base_of(eva)
    sent = say(eva, "kapcsolt").json()
    assert eva.get("/class-spaces/1/messages").status_code == 404
    assert eva.get("/class-spaces/0/messages").status_code == 404
    assert eva.get("/class-spaces/999999999999999999999/messages").status_code == 404
    assert eva.get("/class-spaces/abc/messages").status_code == 422
    assert eva.get(f"{base}/messages", params={"before": "abc"}).status_code == 422
    assert eva.get(f"{base}/messages", params={"limit": 0}).status_code == 422
    assert eva.post(f"{base}/read", {"message_id": "abc"}).status_code == 422
    assert eva.post(f"{base}/read", {"message_id": "99999999999999999999"}).status_code == 404
    assert eva.delete(f"{base}/messages/1").status_code == 404
    assert eva.delete(f"{base}/messages/0").status_code == 404
    assert other.post(f"{base_of(other, '10B')}/read", {"message_id": sent["id"]}).status_code == 404
    assert other.delete(f"{base_of(other, '10B')}/messages/{sent['id']}").status_code == 404
    assert other.post(f"{base_of(other, '10B')}/messages/{sent['id']}/report", {"reason": "spam"}).status_code == 404
    assert eva.put("/class-spaces/me/visibility", {"show_username": "maybe"}).status_code == 422
    assert eva.put("/class-spaces/me/visibility", {}).status_code == 422


def test_retired_classes_have_no_space(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    base = base_of(eva)
    connection = sqlite3.connect(database_path(eva.app))
    connection.execute("UPDATE school_classes SET is_active=0 WHERE code='9A'")
    connection.commit()
    connection.close()
    assert eva.get(f"{base}/messages").status_code == 404
    assert space(eva) == EMPTY_STATE
    refused = eva.put("/class-spaces/me/visibility", {"show_username": True})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "class_required"


def test_staff_cannot_read_class_spaces_but_reports_reach_them_with_real_authors(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=False)
    anna = classmate(make_user, "anna_t", "9A", shows=False)
    moderator = staff(make_user, "mod_ilona", "school_moderator")
    admin = staff(make_user, "admin_vera", "school_admin")
    base = base_of(eva)
    say(eva, "Előzmény")
    offending = say(eva, "Sértő üzenet").json()
    say(anna, "Utómunka")
    for official in (moderator, admin):
        assert official.get(f"{base}/messages").status_code == 404
    reported = anna.post(f"{base}/messages/{offending['id']}/report", {"reason": "harassment", "details": " bántó üzenet "})
    assert reported.status_code == 200, reported.text
    summary = reported.json()["report"]
    assert summary["escalated"] is True and summary["status"] == "open" and summary["details"] == "bántó üzenet"
    assert summary["server_id"] is None and summary["channel_id"] is None and summary["conversation_id"] is None
    assert summary["message_id"] == offending["id"] and summary["target_user_id"] == eva.uid and summary["reporter_id"] == anna.uid
    queue = moderator.get("/moderation/reports").json()
    assert [item["id"] for item in queue] == [summary["id"]] and queue[0]["target"]["username"] == "eva_k"
    detail = moderator.get(f"/moderation/reports/{summary['id']}").json()
    assert {item["content"]: item["author"]["username"] for item in detail["context"]} == {"Előzmény": "eva_k", "Sértő üzenet": "eva_k", "Utómunka": "anna_t"}
    assert [item["reported"] for item in detail["context"]] == [False, True, False]
    revealed = moderator.post(f"/moderation/users/{eva.uid}/identity", {"reason": "súlyos zaklatás miatt", "report_id": summary["id"]})
    assert revealed.status_code == 200 and revealed.json()["username"] == "eva_k" and revealed.json()["declared_class"] == "9A"
    actions = [entry["action"] for entry in admin.get("/moderation/audit").json()["entries"]]
    assert "platform.report_view" in actions and "platform.identity_reveal" in actions
    assert eva.get("/moderation/reports").status_code == 404 and anna.get("/moderation/reports").status_code == 404


def test_reports_are_validated_and_deduplicated(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    anna = classmate(make_user, "anna_t", "9A", shows=False)
    base = base_of(eva)
    first = say(eva, "jelentett").json()
    own = eva.post(f"{base}/messages/{first['id']}/report", {"reason": "spam"})
    assert own.status_code == 422 and own.json()["error"]["code"] == "cannot_report_self"
    invalid = anna.post(f"{base}/messages/{first['id']}/report", {"reason": "nonsense"})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "report_reason_invalid"
    assert anna.post(f"{base}/messages/{first['id']}/report", {"reason": "spam"}).status_code == 200
    duplicate = anna.post(f"{base}/messages/{first['id']}/report", {"reason": "spam"})
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "report_exists"
    assert count_rows(eva.app, "reports") == 1
    sealed = sql_rows(eva.app, "SELECT snapshot_enc FROM reports")[0][0]
    assert sealed is not None and b"jelentett" not in bytes(sealed)


def test_messages_paginate_track_unread_and_can_be_deleted_by_their_author(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    anna = classmate(make_user, "anna_t", "9A", shows=False)
    ids = [say(eva, f"üzenet {n}").json()["id"] for n in range(5)]
    base = base_of(anna)
    page = feed(anna, limit=2)
    assert [m["id"] for m in page["messages"]] == ids[3:] and page["has_more"] is True and page["last_read_message_id"] is None
    assert [m["id"] for m in feed(anna, limit=2, before=ids[3])["messages"]] == ids[1:3]
    assert [m["id"] for m in feed(anna, after=ids[2])["messages"]] == ids[3:]
    assert space(anna)["unread"] == 5 and space(eva)["unread"] == 0
    assert anna.post(f"{base}/read", {"message_id": ids[2]}).json() == {"status": "ok"}
    assert space(anna)["unread"] == 2
    anna.post(f"{base}/read", {"message_id": ids[1]})
    assert space(anna)["unread"] == 2 and feed(anna)["last_read_message_id"] == ids[2]
    anna.post(f"{base}/read", {"message_id": ids[4]})
    assert space(anna)["unread"] == 0 and feed(anna)["last_read_message_id"] == ids[4]
    late = classmate(make_user, "late_zsolt", "9A", shows=False)
    assert space(late)["unread"] == 0 and len(feed(late)["messages"]) == 5
    refused = anna.delete(f"{base}/messages/{ids[0]}")
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "forbidden"
    assert eva.delete(f"{base}/messages/{ids[0]}").json() == {"status": "deleted"}
    assert [m["id"] for m in feed(anna)["messages"]] == ids[1:]
    assert count_rows(eva.app, "class_space_messages") == 4
    assert eva.delete(f"{base}/messages/{ids[0]}").status_code == 404
    assert space(late)["unread"] == 0


def test_message_validation(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    assert say(eva, "   ").json()["error"]["code"] == "message_empty"
    assert say(eva, "x" * 4001).json()["error"]["code"] == "message_too_long"
    assert say(eva, "x" * 9000).status_code == 422
    assert eva.post(f"{base_of(eva)}/messages", {}).status_code == 422
    assert count_rows(eva.app, "class_space_messages") == 0
    assert say(eva, "a\x00b").json()["content"] == "ab"
    assert say(eva, "  <@123> https://example.org  ").json()["content"] == "<@123> https://example.org"


def test_class_space_bodies_are_encrypted_and_bound_to_their_row(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    anna = classmate(make_user, "anna_t", "9A", shows=False)
    say(eva, "elso titkos szoveg")
    say(eva, "masodik titkos szoveg")
    rows = sql_rows(eva.app, "SELECT id, body_enc FROM class_space_messages ORDER BY id")
    assert len(rows) == 2 and all(b"titkos" not in bytes(blob) for _, blob in rows)
    assert "titkos szoveg" not in database_dump(eva.app)
    assert [m["content"] for m in feed(anna)["messages"]] == ["elso titkos szoveg", "masodik titkos szoveg"]
    connection = sqlite3.connect(database_path(eva.app))
    connection.execute("UPDATE class_space_messages SET body_enc=? WHERE id=?", (rows[1][1], rows[0][0]))
    connection.execute("UPDATE class_space_messages SET body_enc=? WHERE id=?", (rows[0][1], rows[1][0]))
    connection.commit()
    connection.close()
    assert [m["content"] for m in feed(anna)["messages"]] == ["", ""]


def test_sends_are_rate_limited_per_user_and_per_class(make_user, monkeypatch):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    anna = classmate(make_user, "anna_t", "9A", shows=True)
    gabor = classmate(make_user, "gabor_m", "9A", shows=True)
    outsider = classmate(make_user, "out_bence", "10B", shows=True)
    eva.app.state.limiter.enabled = True
    monkeypatch.setattr("app.api.v1.class_spaces.USER_SEND_LIMIT", (3, 60))
    monkeypatch.setattr("app.api.v1.class_spaces.CLASS_SEND_LIMIT", (5, 60))
    for _ in range(6):
        assert say(outsider, "x", "9A").status_code == 404
    for _ in range(3):
        assert say(eva, "x").status_code == 200
    limited = say(eva, "x")
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited" and "retry-after" in limited.headers
    assert say(anna, "y").status_code == 200
    assert say(anna, "y").status_code == 200
    assert say(gabor, "z").status_code == 429
    assert say(outsider, "q", "10B").status_code == 200


def test_the_visibility_answer_is_rate_limited(make_user, monkeypatch):
    eva = classmate(make_user, "eva_k", "9A")
    eva.app.state.limiter.enabled = True
    monkeypatch.setattr("app.api.v1.class_spaces.ANSWER_LIMIT", (2, 60))
    assert eva.put("/class-spaces/me/visibility", {"show_username": True}).status_code == 200
    assert eva.put("/class-spaces/me/visibility", {"show_username": False}).status_code == 200
    assert eva.put("/class-spaces/me/visibility", {"show_username": True}).status_code == 429


def test_suspended_members_drop_out_of_the_space(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    anna = classmate(make_user, "anna_t", "9A", shows=True)
    gabor = classmate(make_user, "gabor_m", "9A", shows=False)
    admin = staff(make_user, "admin_vera", "school_admin")
    assert space(eva)["members"] == 3
    suspended = admin.post(f"/moderation/users/{anna.uid}/status", {"status": "suspended", "reason": "teszt felfüggesztés"})
    assert suspended.status_code == 200
    listing = eva.get(f"{base_of(eva)}/members").json()
    assert usernames(listing) == ["eva_k"] and listing["hidden_count"] == 1 and listing["total"] == 2
    assert space(gabor)["members"] == 2
    assert anna.get("/class-spaces/me").status_code in (401, 403)


def test_class_space_event_reaches_members_with_ids_only(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=False)
    anna = classmate(make_user, "anna_t", "9A", shows=True)
    outsider = classmate(make_user, "out_bence", "10B", shows=True)
    with eva.websocket() as we, anna.websocket() as wa, outsider.websocket() as wo:
        for socket in (we, wa, wo):
            ready(socket)
        sent = say(eva, "élő üzenet").json()
        event = wait_for(wa, "class_space.message")
        assert event["d"] == {"class_id": class_id(eva, "9A"), "message_id": sent["id"]}
        for secret in (eva.username, eva.uid, "élő üzenet"):
            assert secret not in str(event)
        assert wait_for(we, "class_space.message")["d"] == event["d"]
        assert "class_space.message" not in types(settle(wo))
        removal = eva.delete(f"{base_of(eva)}/messages/{sent['id']}")
        assert removal.status_code == 200
        assert wait_for(wa, "class_space.message")["d"] == event["d"]


def test_class_space_features_do_not_widen_other_privacy_rules(make_user):
    eva = classmate(make_user, "eva_k", "9A", shows=True)
    anna = classmate(make_user, "anna_t", "9A", shows=True)
    assert anna.get(f"/users/{eva.uid}").status_code == 404
    refused = anna.post("/dms", {"user_id": eva.uid})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "dm_not_allowed"
    listing = anna.get("/users/search", params={"q": "eva"}).json()
    assert listing == []
    assert anna.get("/friends/suggestions").json() == []
