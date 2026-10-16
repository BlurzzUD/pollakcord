import asyncio
import io
import sqlite3
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.db.types import utcnow
from app.errors import AppError
from app.services import link_embeds
from app.services.attachments import ELEVATED_ROLES, attachment_limit, check_size, cleanup_attachments
from app.services.link_embeds import EmbedService, Fetched, UnsafeURL, public_ip, safe_fetch, validate_url
from app.services.message_media import open_media, seal_media

from .conftest import ORIGIN, create_server, database_dump, database_path, first_channel, join_server, sql_rows
from .test_messages import friends_with_dm
from .test_dok import class_member, to_class
from .test_class_spaces import answer, class_id, say


def set_role(user, role):
    with sqlite3.connect(database_path(user.app)) as db:
        db.execute("UPDATE users SET platform_role=? WHERE id=?", (role, int(user.uid)))


def attachment_upload(user, channel, data=b"document", filename="dokumentum.txt", mime="text/plain"):
    return user.request("POST", f"/uploads/attachments?scope=channel&scope_id={channel}", files={"file": (filename, data, mime)})


def setup_channel(make_user):
    owner = make_user("media_owner")
    server = create_server(owner)
    return owner, server, first_channel(server, "text")["id"]


async def stream_upload(user, channel, size):
    boundary = "pollakcord-media-test"

    async def body():
        yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="large.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
        block = b"x" * 1_000_000
        remaining = size
        while remaining:
            amount = min(remaining, len(block))
            yield block[:amount]
            remaining -= amount
        yield f"\r\n--{boundary}--\r\n".encode()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=user.app), base_url=ORIGIN, cookies=user.jar) as client:
        return await client.post(
            "/api/v1/uploads/attachments", params={"scope": "channel", "scope_id": channel}, content=body(),
            headers={"Origin": ORIGIN, "X-CSRF-Token": user.csrf, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )


@pytest.mark.parametrize("role", ["user", *sorted(ELEVATED_ROLES)])
def test_actual_streamed_upload_boundaries_for_every_human_role(make_user, role):
    user, _, channel = setup_channel(make_user)
    set_role(user, role)
    limit = 20_000_000 if role == "user" else 250_000_000
    assert attachment_limit(user.app.state.settings, role) == limit
    allowed = asyncio.run(stream_upload(user, channel, limit))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["size_bytes"] == limit
    rejected = asyncio.run(stream_upload(user, channel, limit + 1))
    assert rejected.status_code == 413 and rejected.json()["error"]["params"]["max_bytes"] == limit
    assert len(sql_rows(user.app, "SELECT id FROM attachments")) == 1
    assert len(list((user.app.state.settings.upload_dir / "attachments").iterdir())) == 1


def test_size_helper_uses_configured_limits():
    settings = Settings(attachment_max_bytes=8, attachment_elevated_max_bytes=15)
    assert attachment_limit(settings, "user") == 8
    assert attachment_limit(settings, "school_admin") == 15
    check_size(8, 8)
    with pytest.raises(AppError) as caught:
        check_size(9, 8)
    assert caught.value.code == "file_too_large"


def test_attachments_are_private_scope_bound_and_claimed_only_once(make_user, new_api):
    owner, server, channel = setup_channel(make_user)
    peer, outsider = make_user("media_peer"), make_user("media_other")
    join_server(peer, server["invite_code"])
    upload = attachment_upload(owner, channel, filename="titkos-adatok.txt").json()
    url = upload["url"].removeprefix("/api/v1")
    assert new_api().get(url).status_code == 401
    assert peer.get(url).status_code == 404
    assert outsider.get(url).status_code == 404
    assert owner.get(url).status_code == 200
    assert peer.post(f"/channels/{channel}/messages", {"attachment_ids": [upload["id"]]}).json()["error"]["code"] == "attachment_invalid"
    other = owner.post(f"/servers/{server['id']}/channels", {"name": "masik", "type": "text"}).json()["id"]
    assert owner.post(f"/channels/{other}/messages", {"attachment_ids": [upload["id"]]}).status_code == 422
    sent = owner.post(f"/channels/{channel}/messages", {"attachment_ids": [upload["id"]]})
    assert sent.status_code == 200 and sent.json()["content"] == ""
    assert sent.json()["attachments"] == [upload]
    assert peer.get(url).status_code == 200 and outsider.get(url).status_code == 404
    assert owner.post(f"/channels/{channel}/messages", {"attachment_ids": [upload["id"]]}).status_code == 422
    assert owner.delete(url).status_code == 404
    assert "titkos-adatok.txt" not in database_dump(owner.app)
    assert owner.delete(f"/channels/{channel}/messages/{sent.json()['id']}").status_code == 200
    assert owner.get(url).status_code == 404 and peer.get(url).status_code == 404
    assert sql_rows(owner.app, "SELECT COUNT(*) FROM attachments")[0][0] == 0


def test_non_inline_files_are_always_downloads_even_when_mislabeled(make_user):
    owner, _, channel = setup_channel(make_user)
    for name, mime in (("evil.html", "text/html"), ("evil.svg", "image/svg+xml"), ("evil.js", "application/javascript"), ("evil.png", "image/png")):
        uploaded = attachment_upload(owner, channel, b"<script>alert(1)</script>", name, mime).json()
        response = owner.get(uploaded["url"].removeprefix("/api/v1") + "?inline=true")
        assert uploaded["kind"] == "file"
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"


def test_images_are_reencoded_and_video_is_served_with_safe_headers_and_ranges(make_user):
    owner, _, channel = setup_channel(make_user)
    output = io.BytesIO()
    Image.new("RGB", (128, 128), "red").save(output, format="PNG")
    image = attachment_upload(owner, channel, output.getvalue() + b"<script>secret</script>", "photo.png").json()
    served = owner.get(image["url"].removeprefix("/api/v1") + "?inline=true")
    assert image["kind"] == "image" and served.headers["content-type"] == "image/webp"
    assert b"<script>" not in served.content
    assert Image.open(io.BytesIO(served.content)).format == "WEBP"
    video = attachment_upload(owner, channel, b"\x00\x00\x00\x18ftypisom" + b"x" * 100, "video.mp4").json()
    partial = owner.get(video["url"].removeprefix("/api/v1") + "?inline=true", headers={"Range": "bytes=0-11"})
    assert video["kind"] == "video" and partial.status_code == 206
    assert partial.headers["content-type"] == "video/mp4"
    assert partial.headers["content-disposition"].startswith("inline;")


def test_upload_and_download_permissions_reuse_channel_rules(make_user):
    owner, server, channel = setup_channel(make_user)
    peer = make_user("media_peer")
    join_server(peer, server["invite_code"])
    assert attachment_upload(peer, channel).status_code == 200
    assert owner.put(f"/channels/{channel}/overwrites/member/{peer.uid}", {"deny": ["send_messages"]}).status_code == 200
    assert attachment_upload(peer, channel).status_code == 403
    assert owner.put(f"/channels/{channel}/overwrites/member/{peer.uid}", {"deny": ["view_channel"]}).status_code == 200
    assert attachment_upload(peer, channel).status_code == 404
    voice = first_channel(server, "voice")["id"]
    assert attachment_upload(owner, voice).status_code == 422


def test_upload_requires_full_auth_csrf_and_origin(api, make_user):
    owner, _, channel = setup_channel(make_user)
    assert attachment_upload(api, channel).status_code == 401
    assert owner.request("POST", f"/uploads/attachments?scope=channel&scope_id={channel}", headers={"X-CSRF-Token": "wrong"}, files={"file": ("x", b"x")}).status_code == 403
    assert owner.request("POST", f"/uploads/attachments?scope=channel&scope_id={channel}", headers={"Origin": "https://evil.com"}, files={"file": ("x", b"x")}).status_code == 403


def test_rate_limits_count_uploaded_bytes_and_requests(make_user):
    owner, _, channel = setup_channel(make_user)
    settings = owner.app.state.settings
    settings.attachment_hourly_bytes = 10
    owner.app.state.limiter.enabled = True
    assert attachment_upload(owner, channel, b"123456").status_code == 200
    rejected = attachment_upload(owner, channel, b"12345")
    assert rejected.status_code == 429 and int(rejected.headers["retry-after"]) > 0
    assert len(sql_rows(owner.app, "SELECT id FROM attachments")) == 1
    settings.attachment_hourly_bytes = 100_000
    owner.app.state.limiter.check(f"attachment-upload:{owner.uid}", 1, 3600)
    for _ in range(60):
        owner.app.state.limiter.check(f"attachment-upload:{owner.uid}", 100, 3600)
    assert attachment_upload(owner, channel, b"x").status_code == 429


def test_expired_pending_files_can_be_cleaned_without_deleting_message_files(make_user):
    owner, _, channel = setup_channel(make_user)
    pending = attachment_upload(owner, channel).json()
    attached = attachment_upload(owner, channel).json()
    assert owner.post(f"/channels/{channel}/messages", {"attachment_ids": [attached["id"]]}).status_code == 200
    cutoff = utcnow() - timedelta(days=2)
    with sqlite3.connect(database_path(owner.app)) as db:
        db.execute("UPDATE attachments SET created_at=?", (cutoff.isoformat(),))
    assert owner.get(pending["url"].removeprefix("/api/v1")).status_code == 404
    async def clean():
        async with owner.app.state.session_factory() as db:
            await cleanup_attachments(db, owner.app.state.settings)
    asyncio.run(clean())
    assert sql_rows(owner.app, "SELECT id FROM attachments") == [(int(attached["id"]),)]


def test_giphy_is_disabled_without_a_key_and_only_ids_are_persisted(make_user):
    owner, _, channel = setup_channel(make_user)
    assert owner.get("/uploads/config").json()["giphy_api_key"] is None
    assert owner.post(f"/channels/{channel}/messages", {"giphy_id": "SchoolGif"}).json()["error"]["code"] == "giphy_disabled"
    owner.app.state.settings.giphy_api_key = Settings(giphy_api_key="browser-key").giphy_api_key
    sent = owner.post(f"/channels/{channel}/messages", {"giphy_id": "SchoolGif"})
    assert sent.status_code == 200 and sent.json()["giphy_id"] == "SchoolGif"
    assert "SchoolGif" not in database_dump(owner.app)
    assert owner.post(f"/channels/{channel}/messages", {"giphy_id": "https://evil.com/x"}).status_code == 422


def test_dm_uploads_obey_participation_privacy_blocks_and_current_permissions(make_user):
    sender, recipient, conversation = friends_with_dm(make_user)
    outsider = make_user("other_viewer")
    path = f"/uploads/attachments?scope=dm&scope_id={conversation}"
    upload = sender.request("POST", path, files={"file": ("notes.txt", b"notes")}).json()
    url = upload["url"].removeprefix("/api/v1")
    assert outsider.request("POST", path, files={"file": ("notes.txt", b"notes")}).status_code == 404
    assert outsider.get(url).status_code == 404 and recipient.get(url).status_code == 404
    sent = sender.post(f"/dms/{conversation}/messages", {"attachment_ids": [upload["id"]]})
    assert sent.status_code == 200 and recipient.get(url).status_code == 200
    assert sender.put(f"/blocks/{recipient.uid}").status_code == 200
    assert sender.request("POST", path, files={"file": ("notes.txt", b"notes")}).status_code == 403
    assert recipient.request("POST", path, files={"file": ("notes.txt", b"notes")}).status_code == 403


def test_dok_and_class_space_embeds_preserve_anonymity_and_history_permissions(make_user, monkeypatch):
    author = class_member(make_user, "rep_link", "9A")
    peer = class_member(make_user, "peer_link", "9A")
    outsider = class_member(make_user, "other_link", "10B")
    set_role(author, "dok_representative")
    monkeypatch.setattr(link_embeds, "safe_fetch", AsyncMock(return_value=Fetched("https://example.com/page", "text/html", b"<title>Confidential preview</title>")))
    dok = to_class(author, "9A", "https://example.com/page").json()
    history = peer.get(f"/dok/threads/{dok['thread_id']}/messages").json()["messages"][0]
    assert history["embeds"][0]["title"] == "Confidential preview" and history["author"] is None
    assert outsider.get(f"/dok/threads/{dok['thread_id']}/messages").status_code == 404
    answer(author, False)
    answer(peer, False)
    sent = say(author, "https://example.com/page").json()
    history = peer.get(f"/class-spaces/{class_id(author, '9A')}/messages").json()["messages"][0]
    assert sent["embeds"] == history["embeds"] and history["author"] is None
    assert "Confidential preview" not in database_dump(author.app)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "http://localhost/", "http://metadata.google.internal/", "http://intranet/",
    "http://127.0.0.1/", "http://0.0.0.0/", "http://10.1.2.3/", "http://172.16.0.1/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data", "http://168.63.129.16/", "http://100.64.0.1/", "http://[::1]/", "http://[fc00::1]/",
    "http://[fe80::1]/", "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::a00:1]/", "http://[2002:7f00:1::]/",
    "http://user:password@example.com/", "http://example.com:8080/", "http://example.com/admin/users", "http://testserver/app/admin",
    "https://example.com/\r\nX-Test:yes", "https://example.com\\@127.0.0.1/",
])
def test_ssrf_urls_are_rejected_before_fetch(settings, url):
    with pytest.raises(UnsafeURL):
        validate_url(url, settings)


def test_mixed_dns_private_and_public_addresses_are_rejected(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("10.0.0.1", 443))]))
        with pytest.raises(UnsafeURL):
            await link_embeds.resolve_public("example.com", 443)
    asyncio.run(run())
    assert public_ip("93.184.216.34") and not public_ip("127.0.0.1")


def test_redirect_to_private_host_is_blocked(settings, monkeypatch):
    resolve = AsyncMock(return_value="93.184.216.34")
    response = AsyncMock(return_value=(302, {"location": "http://127.0.0.1/secret"}, b""))
    monkeypatch.setattr(link_embeds, "resolve_public", resolve)
    monkeypatch.setattr(link_embeds, "_response", response)
    with pytest.raises(UnsafeURL):
        asyncio.run(safe_fetch("https://example.com", settings))
    assert response.await_count == 1 and resolve.await_count == 1


def test_dns_is_pinned_while_tls_and_host_use_original_hostname(settings, monkeypatch):
    class Writer:
        def __init__(self):
            self.request = b""
        def write(self, data):
            self.request += data
        async def drain(self):
            return None
        def close(self):
            return None

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 5\r\n\r\nhello")
        reader.feed_eof()
        writer = Writer()
        connect = AsyncMock(return_value=(reader, writer))
        monkeypatch.setattr(link_embeds, "resolve_public", AsyncMock(return_value="93.184.216.34"))
        monkeypatch.setattr(asyncio, "open_connection", connect)
        result = await safe_fetch("https://example.com/page", settings)
        assert result.data == b"hello"
        assert connect.call_args.args == ("93.184.216.34", 443)
        assert connect.call_args.kwargs["server_hostname"] == "example.com"
        assert b"Host: example.com" in writer.request and b"Cookie:" not in writer.request
    asyncio.run(run())


def test_redirect_limit_and_response_limit(settings, monkeypatch):
    monkeypatch.setattr(link_embeds, "resolve_public", AsyncMock(return_value="93.184.216.34"))
    response = AsyncMock(return_value=(302, {"location": "https://example.com/loop"}, b""))
    monkeypatch.setattr(link_embeds, "_response", response)
    with pytest.raises(UnsafeURL):
        asyncio.run(safe_fetch("https://example.com/loop", settings))
    assert response.await_count == 4


@pytest.mark.parametrize("headers,body", [
    (b"Content-Length: 99\r\n", b""),
    (b"", b"x" * 17),
    (b"Transfer-Encoding: chunked\r\n", b"11\r\n" + b"x" * 17 + b"\r\n0\r\n\r\n"),
    (b"Content-Encoding: gzip\r\n", b"gzip"),
])
def test_http_response_limits_reject_oversize_and_compressed_bodies(monkeypatch, headers, body):
    class Writer:
        def write(self, data):
            return None
        async def drain(self):
            return None
        def close(self):
            return None

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n" + body)
        reader.feed_eof()
        monkeypatch.setattr(asyncio, "open_connection", AsyncMock(return_value=(reader, Writer())))
        with pytest.raises(ValueError):
            await link_embeds._response("https://example.com/", "example.com", 443, "93.184.216.34", 16)
    asyncio.run(run())


def test_total_preview_budget_and_thumbnail_ssrf_fail_closed(settings, monkeypatch):
    settings.link_embed_timeout_seconds = 0.01
    async def delayed(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(link_embeds, "safe_fetch", delayed)
    assert asyncio.run(EmbedService(settings).build("https://example.com/page")) == []
    real_fetch = safe_fetch
    async def fetch(url, *args, **kwargs):
        if url == "https://example.com/page":
            return Fetched(url, "text/html", b'<title>Safe title</title><meta property="og:image" content="http://127.0.0.1/private">')
        return await real_fetch(url, *args, **kwargs)
    monkeypatch.setattr(link_embeds, "safe_fetch", fetch)
    embed = asyncio.run(EmbedService(settings).build("https://example.com/page"))[0]
    assert embed["title"] == "Safe title" and embed["image"] is None


def test_embeds_parse_metadata_and_fail_closed_when_unavailable(settings, monkeypatch):
    fetch = AsyncMock(return_value=Fetched("https://example.com/page", "text/html", b'<title>Fallback</title><meta property="og:title" content="School &amp; news"><meta name="description" content="Description"><meta property="og:site_name" content="Example">'))
    monkeypatch.setattr(link_embeds, "safe_fetch", fetch)
    embed = asyncio.run(EmbedService(settings).build("https://example.com/page"))[0]
    assert embed["title"] == "School & news" and embed["description"] == "Description" and embed["site_name"] == "Example"
    fetch.side_effect = TimeoutError()
    fallback = asyncio.run(EmbedService(settings).build("https://example.com/page"))
    assert fallback == [{"url": "https://example.com/page", "host": "example.com", "title": "example.com"}]
    assert asyncio.run(EmbedService(settings).build("http://127.0.0.1/")) == []


def test_embed_failure_does_not_prevent_message_send_and_success_is_encrypted(make_user, monkeypatch):
    owner, _, channel = setup_channel(make_user)
    fetch = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(link_embeds, "safe_fetch", fetch)
    assert owner.post(f"/channels/{channel}/messages", {"content": "https://example.com/page"}).status_code == 200
    fetch.side_effect = None
    fetch.return_value = Fetched("https://example.com/page", "text/html", b'<title>PRIVATE_PREVIEW_TITLE</title>')
    sent = owner.post(f"/channels/{channel}/messages", {"content": "https://example.com/page"}).json()
    assert sent["embeds"][0]["title"] == "PRIVATE_PREVIEW_TITLE"
    assert "PRIVATE_PREVIEW_TITLE" not in database_dump(owner.app)
    calls = fetch.await_count
    history = owner.get(f"/channels/{channel}/messages").json()
    assert history["messages"][-1]["embeds"] == sent["embeds"]
    assert fetch.await_count == calls
    vault = owner.app.state.vault
    blob, key_id = seal_media(vault, "chat", 1, sent["embeds"])
    assert open_media(vault, "chat", 2, blob, key_id)["embeds"] == []
