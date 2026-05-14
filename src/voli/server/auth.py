"""Bearer-token authentication middleware.

Voli's HTTP server is intended to be exposed publicly (so claude.ai and
ChatGPT can reach it), which means anyone who finds the URL could call
the tools and burn through the operator's Polygon API budget. To prevent
that, every request to ``/mcp`` and ``/tools/*`` must carry an
``Authorization: Bearer <token>`` header that matches the token the
server was started with.

The token is read once from ``VOLI_AUTH_TOKEN`` at startup. If the env
var isn't set, the server refuses to start (fail closed) unless the
operator passes ``--no-auth`` for local development.

The middleware never logs the token. Mismatches return a 401 with a
generic message so attackers can't tell whether the token was wrong or
the route just happened to require auth.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterable

# Routes that bypass auth.
#
# Health checks need to be reachable from load balancers / Cloudflare /
# uptime monitors that don't carry credentials. The OpenAPI spec is a
# discovery document (it describes what endpoints exist; the endpoints
# themselves stay auth-protected), so it needs to be fetchable by clients
# that haven't authenticated yet. ChatGPT's Custom GPT Actions UI in
# particular fetches /openapi.json *before* the user has finished
# configuring auth, so requiring auth on the spec breaks that flow.
DEFAULT_PUBLIC_PATHS: tuple[str, ...] = ("/healthz", "/openapi.json", "/")


class BearerAuthMiddleware:
    """Pure-ASGI bearer-token middleware.

    Implemented as a plain ASGI app (not a Starlette ``BaseHTTPMiddleware``)
    so it composes cleanly with the streaming MCP transport, which uses
    raw ASGI receive/send and would buffer through BaseHTTPMiddleware.
    """

    def __init__(
        self,
        app,
        *,
        token: str | None,
        public_paths: Iterable[str] = DEFAULT_PUBLIC_PATHS,
    ) -> None:
        self.app = app
        self.token = token
        self.public_paths = tuple(public_paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Only HTTP requests are authenticated. Lifespan / websocket
            # scopes pass straight through.
            await self.app(scope, receive, send)
            return

        # Public paths (health checks etc.) bypass auth entirely.
        path: str = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in self.public_paths):
            await self.app(scope, receive, send)
            return

        # If auth is disabled (token is None), let everything through.
        # The CLI prints a loud warning when this is on, so it's only used
        # for local dev.
        if self.token is None:
            await self.app(scope, receive, send)
            return

        # Pull the Authorization header. ASGI lower-cases header names but
        # values are bytes, so we decode to str before comparing.
        headers: list[tuple[bytes, bytes]] = scope.get("headers") or []
        auth_value: str | None = None
        for raw_name, raw_value in headers:
            if raw_name == b"authorization":
                auth_value = raw_value.decode("latin-1").strip()
                break

        if not auth_value or not auth_value.lower().startswith("bearer "):
            await self._send_401(send, "Missing bearer token")
            return

        presented = auth_value[len("Bearer ") :].strip()
        # Constant-time compare to avoid timing oracles. Length mismatches
        # short-circuit but that's fine: token length is not a secret here
        # because both sides see it.
        if not hmac.compare_digest(presented, self.token):
            await self._send_401(send, "Invalid bearer token")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_401(send, _detail: str) -> None:
        """Send a generic 401 (don't leak which check failed)."""

        body = b'{"error":"Unauthorized","message":"Authentication required."}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b'Bearer realm="voli"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
