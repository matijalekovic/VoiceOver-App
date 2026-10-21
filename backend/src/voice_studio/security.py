"""Protects the local API from other local software and from web pages in the user's browser.

- The server binds to 127.0.0.1 only (see __main__).
- Every request needs the per-launch token the desktop shell generated. Media GET requests may
  carry it as ?token= because <audio> elements cannot set headers.
- The Host header must be a loopback name, which defeats DNS-rebinding attacks.
- Requests that carry an Origin must come from the app's own webview (or the Vite dev server).
"""

from __future__ import annotations

import hmac
import json
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


class LocalAccessMiddleware:
    def __init__(self, app: ASGIApp, token: str, allowed_origins: tuple[str, ...]):
        self.app = app
        self.token = token.encode()
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        if _hostname(headers.get("host", "")) not in _LOOPBACK_HOSTS:
            await _reject(
                send, 403, "forbidden_host", "Requests must address the loopback interface."
            )
            return
        origin = headers.get("origin")
        if origin and origin not in self.allowed_origins:
            await _reject(
                send, 403, "forbidden_origin", "This origin may not use the Voice Studio API."
            )
            return
        if scope["method"] == "OPTIONS":  # CORS preflight carries no credentials
            await self.app(scope, receive, send)
            return
        supplied = headers.get("x-studio-token", "")
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:]
        if not supplied and scope["method"] == "GET":
            supplied = parse_qs(scope.get("query_string", b"").decode()).get("token", [""])[0]
        if not hmac.compare_digest(supplied.encode(), self.token):
            await _reject(send, 401, "unauthorized", "Missing or invalid API token.")
            return
        await self.app(scope, receive, send)


def _hostname(host_header: str) -> str:
    if host_header.startswith("["):  # IPv6 literal, e.g. [::1]:8765
        return host_header.split("]")[0] + "]"
    return host_header.rsplit(":", 1)[0]


async def _reject(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
