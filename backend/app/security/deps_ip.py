from fastapi import Request, WebSocket


def client_ip(connection: Request | WebSocket) -> str:
    settings = connection.app.state.settings
    peer = connection.client.host if connection.client else "unknown"
    hops = settings.trusted_proxy_hops
    if hops <= 0:
        return peer
    forwarded = connection.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if len(parts) >= hops:
        return parts[-hops]
    return peer


def mask_ip(address: str) -> str:
    if ":" in address:
        groups = address.split(":")
        return ":".join(groups[:3]) + "::"
    octets = address.split(".")
    if len(octets) == 4:
        return ".".join(octets[:3]) + ".x"
    return ""
