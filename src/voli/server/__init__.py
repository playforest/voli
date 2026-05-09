"""HTTP server for hosting voli's tools to remote clients.

The umbrella ``voli serve`` command exposes three things on one process:

  * ``/mcp`` for Streamable-HTTP MCP. Claude.ai's Custom Integrations and
    other MCP-aware web clients speak this.
  * ``/openapi.json`` + ``/tools/<name>`` for a REST + OpenAPI 3.1
    surface. ChatGPT Custom GPT Actions and any OpenAPI consumer can
    point here.
  * ``/healthz`` for plain liveness checks (no auth required).

Both protected surfaces sit behind a single bearer-token auth middleware
and dispatch to ``voli.llm.tools.build_default_tools()``, so the tool
catalogue is identical across providers.

This package is intentionally small. Phase A is the code; the
Dockerfile, the DigitalOcean walkthrough, and the actual provider
wiring live under ``docs/deploy/``.
"""

from __future__ import annotations

import os
from typing import Any

__all__ = [
    "build_app",
    "serve",
    # Lower-level helpers (re-exported for tests / advanced users).
    "build_mcp_http_app",
    "serve_mcp_http",
]


# ---------------------------------------------------------------------------
# Umbrella app
# ---------------------------------------------------------------------------


def build_app(
    *,
    auth_token: str | None = None,
    server_url: str | None = None,
    include_analytics: bool = True,
) -> Any:
    """Build the unified Starlette app that hosts both surfaces.

    ``auth_token`` is required in production. Pass ``None`` only when
    running locally for development; the CLI flag is ``--no-auth``.
    ``server_url`` is the public URL where this app is reachable; it's
    embedded in the OpenAPI spec so ChatGPT can call back to the right
    host. Leave ``None`` for tests where the spec doesn't need to round
    trip through ChatGPT.
    """

    try:
        import contextlib
        import json as _json

        from starlette.applications import Starlette
        from starlette.responses import JSONResponse, Response
        from starlette.routing import Mount, Route
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "voli.server requires the 'mcp' extra. Install with: poetry install -E mcp"
        ) from exc

    from .auth import BearerAuthMiddleware
    from .mcp_http import build_mcp_http_app
    from .openapi import build_openapi_spec
    from .rest import build_rest_routes

    # Pre-render the OpenAPI spec once. Tools won't change at runtime;
    # rebuilding on every request would be wasteful.
    spec = build_openapi_spec(server_url=server_url, include_analytics=include_analytics)
    spec_bytes = _json.dumps(spec, indent=2).encode("utf-8")

    async def openapi_endpoint(_request) -> Response:
        return Response(content=spec_bytes, media_type="application/json")

    async def healthz(_request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # The MCP HTTP app has its own lifespan (the SDK's session manager
    # needs to start a task group). We mount it as a sub-application so
    # its lifespan plumbing fires when the parent Starlette app starts.
    mcp_app = build_mcp_http_app(include_analytics=include_analytics)

    # Route order matters: more specific routes first, the catch-all
    # Mount("/") last, otherwise the MCP sub-app swallows /tools/* and
    # /openapi.json before they get a chance to match.
    routes: list = [
        Route("/healthz", endpoint=healthz, methods=["GET"]),
        Route("/openapi.json", endpoint=openapi_endpoint, methods=["GET"]),
    ]
    routes.extend(build_rest_routes(include_analytics=include_analytics))
    routes.append(Mount("/", app=mcp_app))  # catch-all for /mcp from the sub-app

    # Lifespan: delegate to the MCP app's lifespan so its session manager
    # task group is created at startup and torn down at shutdown.
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with mcp_app.router.lifespan_context(_app):
            yield

    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(BearerAuthMiddleware, token=auth_token)
    return app


def serve(
    *,
    host: str = "0.0.0.0",
    port: int = 8080,
    auth_token: str | None = None,
    server_url: str | None = None,
    include_analytics: bool = True,
    log_level: str = "info",
) -> None:
    """Run the umbrella app via uvicorn in the foreground.

    The CLI wires this up so ``voli serve`` Just Works; library users can
    also call it directly.
    """

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "voli.server.serve requires uvicorn (installed via the 'mcp' extra)."
        ) from exc

    if auth_token is None:
        # Try the env var as the canonical source. The CLI also surfaces
        # this so the user gets a clear "set VOLI_AUTH_TOKEN" message.
        auth_token = os.environ.get("VOLI_AUTH_TOKEN")

    app = build_app(
        auth_token=auth_token,
        server_url=server_url,
        include_analytics=include_analytics,
    )
    uvicorn.run(app, host=host, port=port, log_level=log_level)


# ---------------------------------------------------------------------------
# Lower-level helpers (kept around for tests / single-surface deploys).
# ---------------------------------------------------------------------------


def build_mcp_http_app(*, include_analytics: bool = True):
    """Return only the MCP-HTTP surface (no OpenAPI / REST / auth)."""

    from .mcp_http import build_mcp_http_app as _build

    return _build(include_analytics=include_analytics)


def serve_mcp_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    include_analytics: bool = True,
) -> None:
    from .mcp_http import serve_mcp_http as _serve

    _serve(host=host, port=port, include_analytics=include_analytics)
