import asyncio
import base64
import io
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from email.parser import BytesParser
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from ..config import Settings
from .uploads import ImageSpec, transform_image

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid", ".example")
TRANSITION_NETWORKS = tuple(ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"))
MAX_DOCUMENT_BYTES = 524_288
MAX_IMAGE_BYTES = 1_000_000
MAX_REDIRECTS = 3
TLS_CONTEXT = ssl.create_default_context()


class UnsafeURL(ValueError):
    pass


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if str(address) == "168.63.129.16":
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None or any(address in network for network in TRANSITION_NETWORKS):
            return False
    return address.is_global and not address.is_multicast and not address.is_reserved


def validate_url(value: str, settings: Settings) -> tuple[str, str, int]:
    if len(value) > 2048 or any(ord(ch) < 33 or ord(ch) == 127 for ch in value) or "\\" in value:
        raise UnsafeURL()
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except (ValueError, UnicodeError) as exc:
        raise UnsafeURL() from exc
    if parts.scheme not in ("http", "https") or not host or parts.username is not None or parts.password is not None:
        raise UnsafeURL()
    if port != (443 if parts.scheme == "https" else 80) or "%" in host or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURL()
    own_hosts = {(urlsplit(origin).hostname or "").rstrip(".").encode("idna").decode("ascii").lower() for origin in settings.allowed_origins}
    if host in own_hosts or host == "localhost":
        raise UnsafeURL()
    try:
        if not public_ip(host):
            raise UnsafeURL()
    except ValueError as exc:
        if isinstance(exc, UnsafeURL) or "." not in host or ":" in host:
            raise UnsafeURL() from exc
    if re.search(r"/(admin|auth|login|logout|settings|account)(/|$)", parts.path, re.IGNORECASE):
        raise UnsafeURL()
    normalized_host = f"[{host}]" if ":" in host else host
    return urlunsplit((parts.scheme, normalized_host, parts.path or "/", parts.query, "")), host, port


async def resolve_public(host: str, port: int) -> str:
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or not all(public_ip(address) for address in addresses):
        raise UnsafeURL()
    return addresses[0]


@dataclass(frozen=True)
class Fetched:
    url: str
    content_type: str
    data: bytes


async def _response(url: str, host: str, port: int, ip: str, limit: int) -> tuple[int, dict[str, str], bytes]:
    parts = urlsplit(url)
    reader, writer = await asyncio.open_connection(
        ip, port, ssl=TLS_CONTEXT if parts.scheme == "https" else None,
        server_hostname=host if parts.scheme == "https" else None, limit=16384,
    )
    try:
        target = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        request = (
            f"GET {target} HTTP/1.1\r\nHost: {parts.netloc}\r\nUser-Agent: PollakCord-LinkPreview/1.0\r\n"
            "Accept: text/html, image/*;q=0.8\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        header = await reader.readuntil(b"\r\n\r\n")
        if len(header) > 16384:
            raise ValueError()
        status_line, raw_headers = header.split(b"\r\n", 1)
        version, status, _ = status_line.split(b" ", 2)
        if version not in (b"HTTP/1.0", b"HTTP/1.1"):
            raise ValueError()
        parsed = BytesParser().parsebytes(raw_headers)
        if any(len(parsed.get_all(key, [])) > 1 for key in ("Content-Length", "Transfer-Encoding", "Location", "Content-Encoding")):
            raise ValueError()
        headers = {key.lower(): value.strip() for key, value in parsed.items()}
        code = int(status)
        if code in (301, 302, 303, 307, 308):
            return code, headers, b""
        if code != 200 or headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError()
        length = int(headers["content-length"]) if "content-length" in headers else None
        if length is not None and (length < 0 or length > limit):
            raise ValueError()
        body = bytearray()
        transfer = headers.get("transfer-encoding", "").lower()
        if transfer:
            if transfer != "chunked" or length is not None:
                raise ValueError()
            for _ in range(4096):
                line = await reader.readuntil(b"\r\n")
                if len(line) > 128:
                    raise ValueError()
                size = int(line.split(b";", 1)[0].strip(), 16)
                if size < 0 or len(body) + size > limit:
                    raise ValueError()
                if size == 0:
                    return code, headers, bytes(body)
                body.extend(await reader.readexactly(size))
                if await reader.readexactly(2) != b"\r\n":
                    raise ValueError()
            raise ValueError()
        while len(body) <= limit and (length is None or len(body) < length):
            chunk = await reader.read(min(65536, limit + 1 - len(body), length - len(body) if length is not None else limit + 1))
            if not chunk:
                break
            body.extend(chunk)
        if len(body) > limit or (length is not None and len(body) != length):
            raise ValueError()
        return code, headers, bytes(body)
    finally:
        writer.close()


async def safe_fetch(url: str, settings: Settings, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> Fetched:
    async with asyncio.timeout(settings.link_embed_timeout_seconds):
        for hop in range(MAX_REDIRECTS + 1):
            url, host, port = validate_url(url, settings)
            ip = await resolve_public(host, port)
            status, headers, data = await _response(url, host, port, ip, max_bytes)
            if status in (301, 302, 303, 307, 308):
                if hop == MAX_REDIRECTS or not headers.get("location"):
                    raise UnsafeURL()
                url = urljoin(url, headers["location"])
                continue
            return Fetched(url, headers.get("content-type", "").lower(), data)
    raise UnsafeURL()


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.icon: str | None = None
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key not in self.meta:
                self.meta[key] = values.get("content", "")[:2000]
        if tag == "title":
            self.in_title = True
        if tag == "link" and "icon" in values.get("rel", "").lower().split():
            self.icon = values.get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title = (self.title + data)[:300]


def compact(value: str, limit: int) -> str:
    return " ".join(value.replace("\x00", "").split())[:limit]


def preview_image(data: bytes, settings: Settings, *, icon: bool) -> str:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}.get(image.format)
    if extension is None:
        raise ValueError()
    spec = ImageSpec("attachment_max_bytes", 1, 1, 10000, (64, 64) if icon else (640, 360), False)
    output = transform_image(data, spec, extension, min(settings.max_image_pixels, 4_000_000))
    if len(output) > 100_000:
        raise ValueError()
    return "data:image/webp;base64," + base64.b64encode(output).decode("ascii")


class EmbedService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.slots = asyncio.Semaphore(4)

    async def _image(self, base: str, value: str | None, *, icon: bool = False) -> str | None:
        if not value:
            return None
        try:
            result = await safe_fetch(urljoin(base, value), self.settings, max_bytes=MAX_IMAGE_BYTES)
            if not result.content_type.startswith("image/"):
                return None
            return await asyncio.to_thread(preview_image, result.data, self.settings, icon=icon)
        except Exception:
            return None

    async def _one(self, url: str) -> dict | None:
        try:
            url, host, _ = validate_url(url, self.settings)
        except UnsafeURL:
            return None
        minimal = {"url": url, "host": host, "title": host}
        try:
            result = await safe_fetch(url, self.settings)
            if not result.content_type.startswith("text/html"):
                return minimal
            parser = MetadataParser()
            charset = re.search(r"charset=[\"']?([\w-]+)", result.content_type)
            parser.feed(result.data.decode(charset[1] if charset else "utf-8", errors="replace"))
            meta = parser.meta
            image, icon = await asyncio.gather(
                self._image(result.url, meta.get("og:image") or meta.get("twitter:image")),
                self._image(result.url, parser.icon, icon=True),
            )
            return {
                **minimal,
                "title": compact(meta.get("og:title") or parser.title or host, 200),
                "description": compact(meta.get("og:description") or meta.get("description", ""), 350),
                "site_name": compact(meta.get("og:site_name", ""), 80),
                "image": image,
                "icon": icon,
            }
        except UnsafeURL:
            return None
        except Exception:
            return minimal

    async def build(self, content: str) -> list[dict]:
        if not self.settings.link_embeds_enabled:
            return []
        urls = list(dict.fromkeys(match[0].rstrip(".,;:!?)\\]}") for match in URL_PATTERN.finditer(content)))[:2]
        if not urls:
            return []
        acquired = False
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=0.05)
            acquired = True
            async with asyncio.timeout(self.settings.link_embed_timeout_seconds):
                return [item for item in await asyncio.gather(*(self._one(url) for url in urls)) if item]
        except Exception:
            return []
        finally:
            if acquired:
                self.slots.release()
