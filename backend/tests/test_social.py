from .conftest import create_server, join_server, sql_rows


def befriend(requester, accepter):
    assert requester.post("/friends/requests", {"username": accepter.username}).status_code == 200
    incoming = accepter.get("/friends/requests").json()["incoming"]
    request_id = next(r["id"] for r in incoming if r["user"]["id"] == requester.uid)
    assert accepter.post(f"/friends/requests/{request_id}/accept").status_code == 200


def set_privacy(user, **values):
    response = user.patch("/me/settings", values)
    assert response.status_code == 200, response.text
    return response.json()


def test_friend_request_lifecycle(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    assert eva.post("/friends/requests", {"username": "anna_t"}).json() == {"status": "sent"}
    pending = anna.get("/friends/requests").json()
    assert [r["user"]["username"] for r in pending["incoming"]] == ["eva_k"]
    assert [r["user"]["username"] for r in eva.get("/friends/requests").json()["outgoing"]] == ["anna_t"]
    notifications = anna.get("/notifications").json()
    assert notifications["unread"] == 1 and notifications["items"][0]["type"] == "friend_request"
    assert anna.post(f"/friends/requests/{pending['incoming'][0]['id']}/accept").json() == {"status": "accepted"}
    assert [f["username"] for f in eva.get("/friends").json()] == ["anna_t"]
    assert [f["username"] for f in anna.get("/friends").json()] == ["eva_k"]
    assert any(n["type"] == "friend_accepted" for n in eva.get("/notifications").json()["items"])
    assert anna.get("/friends/requests").json()["incoming"] == []


def test_declining_and_cancelling_requests(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    eva.post("/friends/requests", {"username": "anna_t"})
    request_id = anna.get("/friends/requests").json()["incoming"][0]["id"]
    assert anna.post(f"/friends/requests/{request_id}/decline").status_code == 200
    assert anna.get("/friends").json() == []
    eva.post("/friends/requests", {"username": "anna_t"})
    outgoing_id = eva.get("/friends/requests").json()["outgoing"][0]["id"]
    assert anna.delete(f"/friends/requests/{outgoing_id}").status_code == 404
    assert eva.delete(f"/friends/requests/{outgoing_id}").status_code == 200
    assert anna.get("/friends/requests").json()["incoming"] == []


def test_only_the_recipient_can_accept(make_user):
    eva, anna, bence = make_user("eva_k"), make_user("anna_t"), make_user("bence_s")
    eva.post("/friends/requests", {"username": "anna_t"})
    request_id = anna.get("/friends/requests").json()["incoming"][0]["id"]
    assert bence.post(f"/friends/requests/{request_id}/accept").status_code == 404
    assert eva.post(f"/friends/requests/{request_id}/accept").status_code == 404


def test_mutual_requests_become_a_friendship(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    eva.post("/friends/requests", {"username": "anna_t"})
    assert anna.post("/friends/requests", {"username": "eva_k"}).json() == {"status": "accepted"}
    assert len(eva.get("/friends").json()) == 1


def test_removing_a_friend(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    befriend(eva, anna)
    assert eva.delete(f"/friends/{anna.uid}").status_code == 200
    assert eva.get("/friends").json() == [] and anna.get("/friends").json() == []
    assert eva.delete(f"/friends/{anna.uid}").status_code == 404


def test_friend_requests_do_not_reveal_whether_a_username_exists(make_user):
    eva = make_user("eva_k")
    assert eva.post("/friends/requests", {"username": "nincs_ilyen"}).json() == {"status": "sent"}
    assert eva.post("/friends/requests", {"username": "eva_k"}).status_code == 422


def test_friend_request_policy_is_enforced_silently(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    set_privacy(anna, friend_requests="nobody")
    assert eva.post("/friends/requests", {"username": "anna_t"}).json() == {"status": "sent"}
    assert anna.get("/friends/requests").json()["incoming"] == []
    set_privacy(anna, friend_requests="shared_servers")
    eva.post("/friends/requests", {"username": "anna_t"})
    assert anna.get("/friends/requests").json()["incoming"] == []
    detail = create_server(eva)
    invite = eva.get(f"/servers/{detail['id']}/invites").json()[0]["code"]
    join_server(anna, invite)
    eva.post("/friends/requests", {"username": "anna_t"})
    assert len(anna.get("/friends/requests").json()["incoming"]) == 1


def test_blocking_removes_friendship_and_prevents_contact(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    befriend(eva, anna)
    assert anna.put(f"/blocks/{eva.uid}").status_code == 200
    assert eva.get("/friends").json() == [] and anna.get("/friends").json() == []
    assert [u["username"] for u in anna.get("/blocks").json()] == ["eva_k"]
    eva.post("/friends/requests", {"username": "anna_t"})
    assert anna.get("/friends/requests").json()["incoming"] == []
    assert eva.get(f"/users/{anna.uid}").status_code == 404
    assert anna.get(f"/users/{eva.uid}").status_code == 404
    assert eva.post("/dms", {"user_id": anna.uid}).status_code == 403
    assert anna.delete(f"/blocks/{eva.uid}").status_code == 200
    assert anna.get("/blocks").json() == []


def test_cannot_block_yourself(make_user):
    eva = make_user("eva_k")
    assert eva.put(f"/blocks/{eva.uid}").status_code == 422


def test_profiles_are_private_by_default_and_open_up_with_shared_context(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    assert eva.get(f"/users/{anna.uid}").status_code == 404
    assert eva.get("/users/search", params={"q": "anna"}).json() == []
    detail = create_server(eva)
    join_server(anna, eva.get(f"/servers/{detail['id']}/invites").json()[0]["code"])
    profile = eva.get(f"/users/{anna.uid}").json()
    assert profile["username"] == "anna_t" and profile["relation"]["shares_server"] is True
    assert [s["name"] for s in profile["shared_servers"]] == ["Teszt szerver"]
    assert [u["username"] for u in eva.get("/users/search", params={"q": "anna"}).json()] == ["anna_t"]


def test_everyone_visibility_makes_profiles_and_search_public(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    set_privacy(anna, profile_visibility="everyone")
    assert eva.get(f"/users/{anna.uid}").status_code == 200
    assert [u["username"] for u in eva.get("/users/search", params={"q": "ann"}).json()] == ["anna_t"]
    set_privacy(anna, profile_visibility="friends")
    assert eva.get(f"/users/{anna.uid}").status_code == 404
    befriend(eva, anna)
    assert eva.get(f"/users/{anna.uid}").status_code == 200


def test_unknown_and_hidden_profiles_are_indistinguishable(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    hidden = eva.get(f"/users/{anna.uid}")
    unknown = eva.get("/users/123456789")
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json()


def test_real_names_are_not_searchable(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    set_privacy(anna, profile_visibility="everyone")
    for needle in ("Kiss", "Tóth", "Toth"):
        assert eva.get("/users/search", params={"q": needle}).json() == []


def test_class_is_hidden_unless_the_user_opts_in(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    set_privacy(anna, profile_visibility="everyone")
    classes = anna.get("/me/classes").json()
    assert [c["code"] for c in classes][:3] == ["9A", "9B", "10A"] and len(classes) == 12
    ten_a = next(c["id"] for c in classes if c["code"] == "10A")
    anna.put("/me/class", {"class_id": ten_a, "visibility": "hidden"})
    assert eva.get(f"/users/{anna.uid}").json()["class_code"] is None
    anna.put("/me/class", {"class_id": ten_a, "visibility": "friends"})
    assert eva.get(f"/users/{anna.uid}").json()["class_code"] is None
    befriend(eva, anna)
    assert eva.get(f"/users/{anna.uid}").json()["class_code"] == "10A"
    anna.put("/me/class", {"class_id": ten_a, "visibility": "everyone"})
    assert anna.get("/me").json()["class_code"] == "10A"


def test_class_choice_validation(make_user):
    eva = make_user("eva_k")
    assert eva.put("/me/class", {"visibility": "everyone"}).status_code == 422
    assert eva.put("/me/class", {"class_id": "999", "visibility": "everyone"}).status_code == 404
    assert eva.patch("/me/settings", {"class_visibility": "everyone"}).status_code == 422
    answered = eva.put("/me/class", {"visibility": "hidden"})
    assert answered.json()["settings"]["class_prompt_answered"] is True


def test_friend_suggestions_only_include_opted_in_classmates(make_user):
    eva, anna, bence = make_user("eva_k"), make_user("anna_t"), make_user("bence_s")
    classes = {c["code"]: c["id"] for c in eva.get("/me/classes").json()}
    assert eva.get("/friends/suggestions").json() == []
    eva.put("/me/class", {"class_id": classes["10A"], "visibility": "friends"})
    anna.put("/me/class", {"class_id": classes["10A"], "visibility": "shared_servers"})
    bence.put("/me/class", {"class_id": classes["10A"], "visibility": "hidden"})
    names = [s["username"] for s in eva.get("/friends/suggestions").json()]
    assert names == ["anna_t"]
    suggestion = eva.get("/friends/suggestions").json()[0]
    assert suggestion["class_code"] == "10A" and "mutual_friends" in suggestion
    assert [s["username"] for s in anna.get("/friends/suggestions").json()] == ["eva_k"]
    assert bence.get("/friends/suggestions").json() == []


def test_suggestions_exclude_other_classes_friends_blocked_and_pending(make_user):
    eva, anna, bence = make_user("eva_k"), make_user("anna_t"), make_user("bence_s")
    classes = {c["code"]: c["id"] for c in eva.get("/me/classes").json()}
    eva.put("/me/class", {"class_id": classes["11A"], "visibility": "everyone"})
    anna.put("/me/class", {"class_id": classes["11B"], "visibility": "everyone"})
    bence.put("/me/class", {"class_id": classes["11A"], "visibility": "everyone"})
    assert [s["username"] for s in eva.get("/friends/suggestions").json()] == ["bence_s"]
    eva.post("/friends/requests", {"username": "bence_s"})
    assert eva.get("/friends/suggestions").json() == []
    bence.post(f"/friends/requests/{bence.get('/friends/requests').json()['incoming'][0]['id']}/decline")
    assert [s["username"] for s in eva.get("/friends/suggestions").json()] == ["bence_s"]
    eva.put(f"/blocks/{bence.uid}")
    assert eva.get("/friends/suggestions").json() == []


def test_suggestions_respect_the_no_friend_requests_policy(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    classes = {c["code"]: c["id"] for c in eva.get("/me/classes").json()}
    for user in (eva, anna):
        user.put("/me/class", {"class_id": classes["9A"], "visibility": "everyone"})
    set_privacy(anna, friend_requests="nobody")
    assert eva.get("/friends/suggestions").json() == []


def test_presence_visibility_follows_privacy_settings(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    befriend(eva, anna)
    assert eva.get("/friends").json()[0]["presence"] == "offline"
    set_privacy(anna, online_status="nobody")
    assert eva.get("/friends").json()[0]["presence"] is None
    profile = eva.get(f"/users/{anna.uid}").json()
    assert profile["presence"] is None and profile["last_seen_at"] is None


def test_profile_updates_and_validation(make_user):
    eva = make_user("eva_k")
    updated = eva.patch("/me", {"display_name": "  Éva  K ", "bio": "Szia!\nÉn vagyok.", "accent_color": "#AA3366"})
    assert updated.status_code == 200
    body = updated.json()
    assert body["display_name"] == "Éva K" and body["bio"] == "Szia!\nÉn vagyok." and body["accent_color"] == "#aa3366"
    assert eva.patch("/me", {"bio": "x" * 301}).status_code == 422
    assert eva.patch("/me", {"accent_color": "red"}).status_code == 422
    assert eva.patch("/me", {"display_name": "bad\u0007name"}).status_code == 422
    assert eva.patch("/me", {"clear_accent": True}).json()["accent_color"] is None


def test_user_id_differs_from_username_and_is_not_sequential(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    assert eva.uid != "eva_k" and eva.uid.isdigit() and int(anna.uid) > int(eva.uid)
    ids = [int(r[0]) for r in sql_rows(eva.app, "SELECT id FROM users ORDER BY id")]
    assert all(b - a > 1 for a, b in zip(ids, ids[1:]))


def test_notification_preferences_suppress_notifications(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    anna.patch("/me/settings", {"notification_prefs": {"friend_requests": False}})
    eva.post("/friends/requests", {"username": "anna_t"})
    assert anna.get("/notifications").json()["unread"] == 0
    assert len(anna.get("/friends/requests").json()["incoming"]) == 1
    assert anna.patch("/me/settings", {"notification_prefs": {"bogus": True}}).status_code == 422


def test_notifications_can_be_read_and_deleted(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    eva.post("/friends/requests", {"username": "anna_t"})
    items = anna.get("/notifications").json()["items"]
    assert anna.post("/notifications/read", {"ids": [items[0]["id"]]}).status_code == 200
    assert anna.get("/notifications").json()["unread"] == 0
    assert eva.delete(f"/notifications/{items[0]['id']}").status_code == 404
    assert anna.delete(f"/notifications/{items[0]['id']}").status_code == 200
    assert anna.get("/notifications").json()["items"] == []
