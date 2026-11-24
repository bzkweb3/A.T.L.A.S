"""Loopback-only HTTP boundary, origin validation and double-submit CSRF guard."""

import hmac
import ipaddress
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from backend.app.core.auth import CSRF_COOKIE, CSRF_HEADER

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _valid_host(host_header: str) -> bool:
    try:
        parsed = urlsplit("//" + host_header)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
        return hostname in _LOCAL_HOSTS and (port is None or 1 <= port <= 65535) and parsed.path == ""
    except ValueError:
        return False


class LocalSecurityMiddleware:
    """Reject non-loopback clients and protect browser state-changing requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        raw_headers = [(key.lower(), value) for key, value in scope.get("headers", [])]
        if sum(key == b"host" for key, _ in raw_headers) != 1:
            return await JSONResponse({"detail": "Host recusado."}, status_code=403)(scope, receive, send)
        if sum(key == b"origin" for key, _ in raw_headers) > 1:
            return await JSONResponse({"detail": "Origem recusada."}, status_code=403)(scope, receive, send)
        headers = {key: value for key, value in raw_headers}
        host = headers.get(b"host", b"").decode("latin-1")
        client = scope.get("client")
        try:
            loopback = bool(client and ipaddress.ip_address(client[0]).is_loopback)
        except ValueError:
            loopback = False
        forwarded = {b"forwarded", b"x-forwarded-host", b"x-forwarded-for", b"x-forwarded-proto"}
        if not loopback or not _valid_host(host) or forwarded.intersection(headers):
            return await JSONResponse({"detail": "Acesso local recusado."}, status_code=403)(scope, receive, send)

        origin = headers.get(b"origin")
        if origin:
            try:
                parsed = urlsplit(origin.decode("latin-1"))
                origin_host = parsed.netloc.lower()
                scheme = parsed.scheme.lower()
                if scheme != scope.get("scheme", "http").lower() or origin_host != host.lower() or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                    raise ValueError
            except ValueError:
                return await JSONResponse({"detail": "Origem recusada."}, status_code=403)(scope, receive, send)

        if scope["type"] == "http" and scope.get("method", "GET").upper() not in _SAFE_METHODS:
            cookies = {}
            for item in headers.get(b"cookie", b"").decode("latin-1").split(";"):
                if "=" in item:
                    key, value = item.strip().split("=", 1)
                    cookies[key] = value
            token = headers.get(CSRF_HEADER.encode(), b"").decode("latin-1")
            expected = cookies.get(CSRF_COOKIE, "")
            if not origin or not token or not expected or not hmac.compare_digest(token, expected):
                return await JSONResponse({"detail": "Verificação CSRF recusada."}, status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)
