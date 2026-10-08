import pytest
from starlette.websockets import WebSocketDisconnect

from .conftest import ORIGIN, create_server, first_channel, join_server, role_named
from .test_messages import friends_with_dm
from .test_servers import assign, setup_server
from .test_social import befriend, set_privacy

pytestmark = pytest.mark.timeout(60)


def ready(ws):
    first = ws.receive_json()
    assert first["t"] == "ready"
    return first


def settle(ws):
    ws.send_json({"op": "ping"})
    seen = []
    while True:
        event = ws.receive_json()
        if event["t"] == "pong":
            return seen
        seen.append(event)


def wait_for(ws, event_type, attempts=30):
    for _ in range(attempts):
        event = ws.receive_json()
        if event["t"] == event_type:
            return event
    raise AssertionError(f"event {event_type} never arrived")


def types(events):
    return [e["t"] for e in events]


def subscribe(ws, channel_id):
    ws.send_json({"op": "subscribe", "d": {"channel_id": channel_id}})
    return wait_for_any(ws, ("subscribed", "error"))


def wait_for_any(ws, kinds, attempts=30):
    for _ in range(attempts):
        event = ws.receive_json()
        if event["t"] in kinds:
            return event
    raise AssertionError("none of the expected events arrived")


def test_socket_requires_a_session_and_a_trusted_origin(api, make_user):
    with pytest.raises(WebSocketDisconnect):
        with api.websocket():
            pass
    user = make_user("eva_k")
    with pytest.raises(WebSocketDisconnect):
        with user.client.websocket_connect("/api/v1/ws", headers={"Origin": "https://evil.example"}):
            pass
    user.client.cookies = user.jar
    with pytest.raises(WebSocketDisconnect):
        with user.client.websocket_connect("/api/v1/ws"):
            pass
    with user.websocket() as ws:
        assert ready(ws)["d"]["user_id"] == user.uid


def test_setup_sessions_cannot_open_sockets(api):
    api.kreta_verify("diak1", "jelszo-egy")
    api.post("/auth/kreta/confirm", {"confirmed": True})
    api.post("/auth/register", {"username": "eva_k", "display_name": "Éva"})
    with pytest.raises(WebSocketDisconnect):
        with api.websocket():
            pass


def test_channel_messages_reach_only_authorized_subscribers(make_user):
    (owner, member, bystander), detail, _ = setup_server(make_user, 3)
    outsider = make_user("kivul")
    channel = first_channel(detail, "text")
    with owner.websocket() as wo, member.websocket() as wm, bystander.websocket() as wb, outsider.websocket() as wx:
        for socket in (wo, wm, wb, wx):
            ready(socket)
        assert subscribe(wo, channel["id"])["t"] == "subscribed"
        assert subscribe(wm, channel["id"])["t"] == "subscribed"
        denied = subscribe(wx, channel["id"])
        assert denied == {"t": "error", "d": {"op": "subscribe", "code": "not_found"}}
        posted = member.post(f"/channels/{channel['id']}/messages", {"content": "Szia mindenki"}).json()
        pushed = wait_for(wo, "message.create")
        assert pushed["d"]["id"] == posted["id"] and pushed["d"]["content"] == "Szia mindenki"
        assert wait_for(wm, "message.create")["d"]["author"]["username"] == "tag_egy"
        assert "message.create" not in types(settle(wb))
        assert "message.create" not in types(settle(wx))


def test_permission_changes_drop_live_subscriptions(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    sid = detail["id"]
    channel = first_channel(detail, "text")
    default_role = next(r for r in detail["roles"] if r["is_default"])
    with member.websocket() as wm:
        ready(wm)
        assert subscribe(wm, channel["id"])["t"] == "subscribed"
        owner.post(f"/channels/{channel['id']}/messages", {"content": "latod"})
        assert wait_for(wm, "message.create")["d"]["content"] == "latod"
        owner.put(f"/channels/{channel['id']}/overwrites/role/{default_role['id']}", {"deny": ["view_channel"]})
        settle(wm)
        owner.post(f"/channels/{channel['id']}/messages", {"content": "nem latod"})
        assert "message.create" not in types(settle(wm))
        assert subscribe(wm, channel["id"])["d"]["code"] == "not_found"


def test_direct_messages_are_pushed_to_both_participants_only(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    mallory = make_user("mallory")
    with eva.websocket() as we, anna.websocket() as wa, mallory.websocket() as wm:
        for socket in (we, wa, wm):
            ready(socket)
        sent = eva.post(f"/dms/{conversation}/messages", {"content": "privát"}).json()
        assert wait_for(we, "message.create")["d"]["id"] == sent["id"]
        assert wait_for(wa, "message.create")["d"]["content"] == "privát"
        assert "message.create" not in types(settle(wm))
        assert anna.delete(f"/dms/{conversation}/messages/{sent['id']}").status_code == 403
        assert "message.delete" not in types(settle(wa))
        eva.delete(f"/dms/{conversation}/messages/{sent['id']}")
        assert wait_for(wa, "message.delete")["d"]["id"] == sent["id"]
        assert "message.delete" not in types(settle(wm))


def test_typing_indicators_are_authorized(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    outsider = make_user("kivul")
    channel = first_channel(detail, "text")
    with owner.websocket() as wo, member.websocket() as wm, outsider.websocket() as wx:
        for socket in (wo, wm, wx):
            ready(socket)
        subscribe(wo, channel["id"])
        wm.send_json({"op": "typing", "d": {"scope": "channel", "id": channel["id"]}})
        typing = wait_for(wo, "typing")
        assert typing["d"] == {"scope": "channel", "id": channel["id"], "user_id": member.uid}
        wx.send_json({"op": "typing", "d": {"scope": "channel", "id": channel["id"]}})
        assert wait_for(wx, "error")["d"]["code"] == "not_found"
        assert "typing" not in types(settle(wo))


def test_dm_typing_reaches_only_the_other_participant(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    mallory = make_user("mallory")
    with eva.websocket() as we, anna.websocket() as wa, mallory.websocket() as wm:
        for socket in (we, wa, wm):
            ready(socket)
        we.send_json({"op": "typing", "d": {"scope": "dm", "id": conversation}})
        assert wait_for(wa, "typing")["d"]["user_id"] == eva.uid
        wm.send_json({"op": "typing", "d": {"scope": "dm", "id": conversation}})
        assert wait_for(wm, "error")["d"]["code"] == "not_found"
        assert "typing" not in types(settle(we))


def test_presence_is_pushed_to_friends_who_are_allowed_to_see_it(make_user):
    eva, anna, bence = make_user("eva_k"), make_user("anna_t"), make_user("bence_s")
    befriend(eva, anna)
    befriend(eva, bence)
    set_privacy(bence, online_status="nobody")
    with eva.websocket() as we:
        ready(we)
        with anna.websocket() as wa:
            ready(wa)
            assert wait_for(we, "presence.update")["d"] == {"user_id": anna.uid, "status": "online"}
            with bence.websocket() as wb:
                ready(wb)
        assert wait_for(we, "presence.update")["d"] == {"user_id": anna.uid, "status": "offline"}
        assert all(e["d"]["user_id"] != bence.uid for e in settle(we) if e["t"] == "presence.update")
        assert eva.get("/friends").json()[0]["presence"] in ("online", "offline")


def test_friend_events_and_notifications_are_pushed_live(make_user):
    eva, anna = make_user("eva_k"), make_user("anna_t")
    with anna.websocket() as wa:
        ready(wa)
        eva.post("/friends/requests", {"username": "anna_t"})
        pushed = {event["t"]: event["d"] for event in settle(wa)}
        assert pushed["friend.request"]["user"]["username"] == "eva_k"
        assert pushed["notification.create"]["type"] == "friend_request"
        request_id = anna.get("/friends/requests").json()["incoming"][0]["id"]
        with eva.websocket() as we:
            ready(we)
            anna.post(f"/friends/requests/{request_id}/accept")
            assert wait_for(we, "friend.added")["d"]["user"]["username"] == "anna_t"


def test_voice_signaling_is_limited_to_room_participants(make_user):
    (owner, member, third), detail, _ = setup_server(make_user, 3)
    voice = first_channel(detail, "voice")
    with owner.websocket() as wo, member.websocket() as wm, third.websocket() as wt:
        for socket in (wo, wm, wt):
            ready(socket)
        wo.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
        joined = wait_for(wo, "voice.joined")["d"]
        assert joined["room"] == f"channel:{voice['id']}" and [p["user_id"] for p in joined["participants"]] == [owner.uid]
        wm.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
        assert {p["user_id"] for p in wait_for(wm, "voice.joined")["d"]["participants"]} == {owner.uid, member.uid}
        assert wait_for(wo, "voice.participant_joined")["d"]["user_id"] == member.uid
        wm.send_json({"op": "voice.signal", "d": {"to": owner.uid, "kind": "offer", "data": {"sdp": "v=0"}}})
        relayed = wait_for(wo, "voice.signal")["d"]
        assert relayed["from"] == member.uid and relayed["kind"] == "offer" and relayed["data"] == {"sdp": "v=0"}
        wt.send_json({"op": "voice.signal", "d": {"to": owner.uid, "kind": "offer", "data": {"sdp": "evil"}}})
        assert wait_for(wt, "error")["d"]["code"] == "forbidden"
        wo.send_json({"op": "voice.signal", "d": {"to": third.uid, "kind": "answer", "data": {}}})
        assert wait_for(wo, "error")["d"]["code"] == "forbidden"
        wm.send_json({"op": "voice.signal", "d": {"to": owner.uid, "kind": "exploit", "data": {}}})
        assert wait_for(wm, "error")["d"]["code"] == "validation_error"
        wm.send_json({"op": "voice.signal", "d": {"to": owner.uid, "kind": "ice", "data": {"x": "y" * 20000}}})
        assert wait_for(wm, "error")["d"]["code"] == "validation_error"
        assert "voice.signal" not in types(settle(wt))
        wm.send_json({"op": "voice.leave"})
        assert wait_for(wo, "voice.participant_left")["d"]["user_id"] == member.uid


def test_voice_room_tracking_is_visible_to_server_members(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    voice = first_channel(detail, "voice")
    with owner.websocket() as wo, member.websocket() as wm:
        ready(wo)
        ready(wm)
        wo.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
        update = wait_for(wm, "voice.channel_update")["d"]
        assert update["channel_id"] == voice["id"] and [p["user_id"] for p in update["participants"]] == [owner.uid]
        assert member.get(f"/servers/{detail['id']}").json()["voice_states"][voice["id"]][0]["user_id"] == owner.uid
        wo.send_json({"op": "voice.state", "d": {"muted": True, "deafened": False}})
        state = wait_for(wm, "voice.channel_update")["d"]
        assert state["participants"][0]["muted"] is True
        wo.send_json({"op": "voice.leave"})
        assert wait_for(wm, "voice.channel_update")["d"]["participants"] == []


def test_voice_needs_connect_permission_and_respects_limits(make_user):
    (owner, member, other), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    voice = first_channel(detail, "voice")
    owner.patch(f"/channels/{voice['id']}", {"user_limit": 1})
    with owner.websocket() as wo, member.websocket() as wm:
        ready(wo)
        ready(wm)
        wo.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
        wait_for(wo, "voice.joined")
        wm.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
        assert wait_for(wm, "error")["d"]["code"] == "voice_channel_full"
        wo.send_json({"op": "voice.leave"})
        default_role = next(r for r in detail["roles"] if r["is_default"])
        owner.put(f"/channels/{voice['id']}/overwrites/role/{default_role['id']}", {"deny": ["connect"]})
        settle(wm)
        wm.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
        assert wait_for(wm, "error")["d"]["code"] == "missing_permission"
        wm.send_json({"op": "voice.join", "d": {"channel_id": detail['channels'][0]['id']}})
        assert wait_for(wm, "error")["d"]["code"] == "channel_type_invalid"


def test_losing_connect_permission_ejects_participants_from_voice(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    voice = first_channel(detail, "voice")
    default_role = next(r for r in detail["roles"] if r["is_default"])
    with member.websocket() as wm:
        ready(wm)
        wm.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
        wait_for(wm, "voice.joined")
        owner.put(f"/channels/{voice['id']}/overwrites/role/{default_role['id']}", {"deny": ["connect"]})
        assert wait_for(wm, "voice.disconnected")["d"]["reason"] == "permissions"


def test_server_side_voice_moderation(make_user):
    (owner, mod, member), detail, _ = setup_server(make_user, 3)
    sid = detail["id"]
    assign(owner, sid, mod, role_named(detail, "moderator")["id"])
    voice = first_channel(detail, "voice")
    with mod.websocket() as wmod, member.websocket() as wm:
        ready(wmod)
        ready(wm)
        for socket in (wmod, wm):
            socket.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
            wait_for(socket, "voice.joined")
        wm.send_json({"op": "voice.moderate", "d": {"channel_id": voice["id"], "user_id": mod.uid, "server_muted": True}})
        assert wait_for(wm, "error")["d"]["code"] == "missing_permission"
        wmod.send_json({"op": "voice.moderate", "d": {"channel_id": voice["id"], "user_id": member.uid, "server_muted": True}})
        state = wait_for(wm, "voice.state")["d"]
        assert next(p for p in state["participants"] if p["user_id"] == member.uid)["server_muted"] is True
        wmod.send_json({"op": "voice.moderate", "d": {"channel_id": voice["id"], "user_id": owner.uid, "server_muted": True}})
        assert wait_for(wmod, "error")["d"]["code"] == "role_hierarchy"
    assert any(e["action"] == "voice.moderate" for e in owner.get(f"/servers/{sid}/audit-logs").json()["entries"])


def test_removed_members_lose_realtime_access_and_voice(make_user):
    (owner, member), detail, _ = setup_server(make_user)
    sid = detail["id"]
    channel, voice = first_channel(detail, "text"), first_channel(detail, "voice")
    with member.websocket() as wm, owner.websocket() as wo:
        ready(wm)
        ready(wo)
        subscribe(wm, channel["id"])
        wm.send_json({"op": "voice.join", "d": {"channel_id": voice["id"]}})
        wait_for(wm, "voice.joined")
        owner.delete(f"/servers/{sid}/members/{member.uid}")
        removed = wait_for(wm, "server.removed")["d"]
        assert removed == {"server_id": sid, "reason": "kicked"}
        assert wait_for(wm, "voice.disconnected")["d"]["reason"] == "removed"
        owner.post(f"/channels/{channel['id']}/messages", {"content": "nem kapod meg"})
        assert "message.create" not in types(settle(wm))
        assert subscribe(wm, channel["id"])["d"]["code"] == "not_found"


def test_new_members_receive_server_events_immediately(make_user):
    owner, joiner = make_user("tulaj"), make_user("belepo")
    detail = create_server(owner)
    with owner.websocket() as wo, joiner.websocket() as wj:
        ready(wo)
        ready(wj)
        join_server(joiner, detail["invite_code"])
        assert wait_for(wo, "member.joined")["d"]["user"]["username"] == "belepo"
        assert wait_for(wj, "server.joined")["d"]["server_id"] == detail["id"]
        owner.post(f"/servers/{detail['id']}/channels", {"name": "uj", "type": "text"})
        assert wait_for(wj, "structure.changed")["d"]["server_id"] == detail["id"]


def test_direct_voice_call_lifecycle(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    with eva.websocket() as we, anna.websocket() as wa:
        ready(we)
        ready(wa)
        we.send_json({"op": "call.invite", "d": {"conversation_id": conversation}})
        incoming = wait_for(wa, "call.incoming")["d"]
        assert incoming["from"]["username"] == "eva_k" and incoming["conversation_id"] == conversation
        assert wait_for(we, "voice.joined")["d"]["room"] == f"dm:{conversation}"
        wa.send_json({"op": "call.accept", "d": {"conversation_id": conversation}})
        assert wait_for(we, "call.accepted")["d"]["conversation_id"] == conversation
        assert {p["user_id"] for p in wait_for(wa, "voice.joined")["d"]["participants"]} == {eva.uid, anna.uid}
        we.send_json({"op": "voice.signal", "d": {"to": anna.uid, "kind": "offer", "data": {"sdp": "x"}}})
        assert wait_for(wa, "voice.signal")["d"]["from"] == eva.uid
        wa.send_json({"op": "voice.leave"})
        assert wait_for(we, "call.ended")["d"]["reason"] == "hangup"
        we.send_json({"op": "call.invite", "d": {"conversation_id": conversation}})
        wait_for(wa, "call.incoming")
        wa.send_json({"op": "call.decline", "d": {"conversation_id": conversation}})
        assert wait_for(we, "call.ended")["d"]["reason"] == "declined"


def test_caller_can_cancel_a_ringing_call(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    with eva.websocket() as we, anna.websocket() as wa:
        ready(we)
        ready(wa)
        we.send_json({"op": "call.invite", "d": {"conversation_id": conversation}})
        wait_for(wa, "call.incoming")
        we.send_json({"op": "call.cancel", "d": {"conversation_id": conversation}})
        assert wait_for(wa, "call.ended")["d"]["reason"] == "cancelled"
        wa.send_json({"op": "call.accept", "d": {"conversation_id": conversation}})
        assert wait_for(wa, "error")["d"]["code"] == "not_found"


def test_unanswered_calls_become_missed_call_notifications(make_user, app):
    app.state.settings.call_ring_seconds = 1
    eva, anna, conversation = friends_with_dm(make_user)
    with eva.websocket() as we, anna.websocket() as wa:
        ready(we)
        ready(wa)
        we.send_json({"op": "call.invite", "d": {"conversation_id": conversation}})
        wait_for(wa, "call.incoming")
        assert wait_for(we, "call.ended")["d"]["reason"] == "unanswered"
        assert wait_for(wa, "call.ended")["d"]["reason"] == "missed"
    assert any(n["type"] == "call_missed" for n in anna.get("/notifications").json()["items"])


def test_calls_respect_privacy_presence_and_friendship(make_user):
    eva, anna, conversation = friends_with_dm(make_user)
    with eva.websocket() as we:
        ready(we)
        we.send_json({"op": "call.invite", "d": {"conversation_id": conversation}})
        assert wait_for(we, "error")["d"]["code"] == "callee_offline"
        set_privacy(anna, voice_calls="nobody")
        with anna.websocket() as wa:
            ready(wa)
            we.send_json({"op": "call.invite", "d": {"conversation_id": conversation}})
            assert wait_for(we, "error")["d"]["code"] == "call_not_allowed"
            set_privacy(anna, voice_calls="friends")
            eva.delete(f"/friends/{anna.uid}")
            we.send_json({"op": "call.invite", "d": {"conversation_id": conversation}})
            assert wait_for(we, "error")["d"]["code"] == "call_not_allowed"


def test_logging_out_closes_the_socket(make_user):
    eva = make_user("eva_k")
    with eva.websocket() as ws:
        ready(ws)
        eva.post("/auth/logout")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_malformed_traffic_is_ignored_and_oversized_frames_close_the_socket(make_user):
    eva = make_user("eva_k")
    with eva.websocket() as ws:
        ready(ws)
        for junk in ("not json", "[]", '{"op": 5}', '{"op": "nope"}', '{"op": "ping", "d": []}', "{}"):
            ws.send_text(junk)
        assert settle(ws) == []
    with eva.websocket() as ws:
        ready(ws)
        ws.send_text("x" * 40000)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4413


def test_connection_count_per_user_is_limited(make_user, app):
    app.state.settings.ws_max_connections_per_user = 2
    eva = make_user("eva_k")
    with eva.websocket() as first, eva.websocket() as second:
        ready(first)
        ready(second)
        with pytest.raises(WebSocketDisconnect):
            with eva.websocket():
                pass


def test_suspended_accounts_are_disconnected(make_user):
    eva, admin = make_user("eva_k"), make_user("admin_u")
    from .test_messages import promote

    promote(eva.app, "admin_u", "school_admin")
    with eva.websocket() as ws:
        ready(ws)
        admin.post(f"/moderation/users/{eva.uid}/status", {"status": "suspended", "reason": "Szabályszegés miatt"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
