import io
import re
from pathlib import Path

from PIL import Image

from .conftest import create_server, join_server


def image_bytes(size=(200, 200), color=(220, 40, 60), fmt="PNG", exif: bytes | None = None) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color)
    options = {"exif": exif} if exif is not None else {}
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def upload(api, kind, data, filename="kep.png", content_type="image/png"):
    return api.request("POST", f"/uploads/{kind}", files={"file": (filename, data, content_type)})


def stored_path(app, url: str) -> Path:
    kind, key = url.removeprefix("/media/").split("/")
    return app.state.settings.upload_dir / kind / key


def test_avatar_upload_is_validated_reencoded_and_served_safely(make_user):
    user = make_user("eva_k")
    response = upload(user, "avatar", image_bytes((300, 200)))
    assert response.status_code == 200, response.text
    url = response.json()["avatar_url"]
    assert re.fullmatch(r"/media/avatar/[0-9a-f]{32}\.webp", url)
    stored = stored_path(user.app, url).read_bytes()
    assert stored[:4] == b"RIFF" and stored[8:12] == b"WEBP"
    with Image.open(io.BytesIO(stored)) as image:
        assert image.size == (512, 512) and image.format == "WEBP"
    served = user.client.get(url)
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in served.headers["content-security-policy"]
    assert user.get("/me").json()["avatar_url"] == url


def test_replacing_and_removing_images_deletes_old_files(make_user):
    user = make_user("eva_k")
    first = upload(user, "avatar", image_bytes()).json()["avatar_url"]
    second = upload(user, "avatar", image_bytes(color=(0, 0, 255))).json()["avatar_url"]
    assert first != second and not stored_path(user.app, first).exists() and stored_path(user.app, second).exists()
    removed = user.delete("/uploads/avatar").json()
    assert removed["avatar_url"] is None and not stored_path(user.app, second).exists()


def test_banner_is_scaled_but_keeps_its_aspect_ratio(make_user):
    user = make_user("eva_k")
    url = upload(user, "banner", image_bytes((3000, 600))).json()["banner_url"]
    with Image.open(stored_path(user.app, url)) as image:
        assert image.size == (1600, 320)


def test_metadata_is_stripped(make_user):
    user = make_user("eva_k")
    exif = Image.Exif()
    exif[0x010E] = "GPS-secret-description"
    exif[0x0132] = "2026:01:01 10:00:00"
    data = image_bytes(fmt="JPEG", exif=exif.tobytes())
    assert b"GPS-secret-description" in data
    url = upload(user, "avatar", data, "foto.jpg", "image/jpeg").json()["avatar_url"]
    stored = stored_path(user.app, url).read_bytes()
    assert b"GPS-secret-description" not in stored
    with Image.open(io.BytesIO(stored)) as image:
        assert len(image.getexif()) == 0


def test_the_client_supplied_mime_type_is_ignored(make_user):
    user = make_user("eva_k")
    assert upload(user, "avatar", image_bytes(), "kep.png", "text/plain").status_code == 200
    assert upload(user, "avatar", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "kep.png", "image/png").status_code == 415


def test_non_images_and_unsafe_formats_are_rejected(make_user):
    user = make_user("eva_k")
    svg = b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'><script>alert(1)</script></svg>"
    for name, data in (("a.svg", svg), ("a.png", svg), ("a.png", b"not an image at all"), ("a.html", b"<html></html>"), ("a.php", b"<?php ?>"), ("a", image_bytes())):
        response = upload(user, "avatar", data, name)
        assert response.status_code == 415, (name, response.text)
    assert upload(user, "avatar", b"", "a.png").status_code in (422, 415)


def test_extension_must_match_the_detected_format(make_user):
    user = make_user("eva_k")
    assert upload(user, "avatar", image_bytes(fmt="PNG"), "kep.jpg").status_code == 415
    assert upload(user, "avatar", image_bytes(fmt="JPEG"), "kep.png").status_code == 415
    assert upload(user, "avatar", image_bytes(fmt="JPEG"), "kep.JPEG").status_code == 200
    assert upload(user, "avatar", image_bytes(fmt="GIF"), "kep.gif").status_code == 200
    assert upload(user, "avatar", image_bytes(fmt="WEBP"), "kep.webp").status_code == 200


def test_polyglot_files_cannot_smuggle_payloads_through(make_user):
    user = make_user("eva_k")
    payload = b"<script>alert('xss')</script><?php system($_GET['c']); ?>"
    url = upload(user, "avatar", image_bytes(fmt="GIF") + payload, "kep.gif", "image/gif").json()["avatar_url"]
    stored = stored_path(user.app, url).read_bytes()
    assert b"<script>" not in stored and b"<?php" not in stored


def test_size_dimension_and_pixel_limits(make_user):
    user = make_user("eva_k")
    user.app.state.settings.avatar_max_bytes = 2000
    noisy = Image.effect_noise((400, 400), 80).convert("RGB")
    buffer = io.BytesIO()
    noisy.save(buffer, format="PNG")
    too_big = upload(user, "avatar", buffer.getvalue())
    assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "file_too_large"
    user.app.state.settings.avatar_max_bytes = 2 * 1024 * 1024
    assert upload(user, "avatar", image_bytes((32, 32))).json()["error"]["code"] == "image_dimensions_too_small"
    assert upload(user, "avatar", image_bytes((7000, 20))).json()["error"]["code"] == "image_dimensions_too_large"
    user.app.state.settings.max_image_pixels = 10_000
    assert upload(user, "avatar", image_bytes((200, 200))).status_code in (415, 422)


def test_unknown_upload_kinds_and_traversal_are_not_found(make_user):
    user = make_user("eva_k")
    assert upload(user, "../../etc", image_bytes()).status_code == 404
    assert upload(user, "icon", image_bytes()).status_code == 404
    for path in ("/media/avatar/..%2F..%2Fetc%2Fpasswd", "/media/avatar/%2e%2e/%2e%2e/passwd", "/media/secrets/a.webp", "/media/avatar/" + "0" * 32 + ".webp", "/media/avatar/x.png"):
        assert user.client.get(path).status_code == 404, path


def test_uploads_require_authentication(api):
    assert upload(api, "avatar", image_bytes()).status_code == 401


def test_server_icons_need_manage_server(make_user):
    owner, member = make_user("tulaj"), make_user("tag_egy")
    detail = create_server(owner)
    join_server(member, detail["invite_code"])
    sid = detail["id"]
    assert member.request("POST", f"/servers/{sid}/icon", files={"file": ("i.png", image_bytes(), "image/png")}).status_code == 403
    icon = owner.request("POST", f"/servers/{sid}/icon", files={"file": ("i.png", image_bytes(), "image/png")}).json()["icon_url"]
    with Image.open(stored_path(owner.app, icon)) as image:
        assert image.size == (256, 256)
    assert member.get(f"/servers/{sid}").json()["icon_url"] == icon
    assert member.delete(f"/servers/{sid}/icon").status_code == 403
    assert owner.delete(f"/servers/{sid}/icon").json() == {"icon_url": None}
    assert not stored_path(owner.app, icon).exists()
