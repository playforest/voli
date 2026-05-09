"""Streamable-HTTP MCP transport.

Wraps voli's existing tool catalogue in the MCP SDK's
:class:`StreamableHTTPSessionManager` so the same tools that
``voli mcp-serve`` exposes over stdio are also reachable over HTTP/SSE
at ``/mcp``. This is the transport claude.ai's Custom Integrations and
other web-side MCP clients require, since they can't spawn a local
subprocess.

The session manager handles MCP's session lifecycle (initialize,
tools/list, tools/call, ping, terminate) and streaming responses;
voli's job is just to hand it the catalogue and mount the ASGI handler.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any


def _require_deps() -> tuple[Any, Any, Any]:
    """Lazy-import MCP / Starlette so the lean voli install stays slim."""

    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount
    except ImportError as exc:  # pragma: no cover - exercised only when the extra is missing
        raise ImportError(
            "voli.server.mcp_http requires the 'mcp' extra. Install with: poetry install -E mcp"
        ) from exc
    return StreamableHTTPSessionManager, Starlette, Mount


def build_mcp_http_app(*, include_analytics: bool = True):
    """Return a Starlette app exposing voli's MCP server at ``/mcp``.

    The returned app is an ordinary ASGI application, so it can be mounted
    inside a larger Starlette / FastAPI app or run directly with uvicorn.
    """

    StreamableHTTPSessionManager, Starlette, Mount = _require_deps()

    # Reuse voli's existing tool catalogue + Server construction so the
    # stdio and HTTP modes can never drift.
    from voli.mcp_server import _build_server

    server, _tools = _build_server(include_analytics=include_analytics)

    # ``stateless=False`` keeps a session per client (claude.ai expects this).
    # ``json_response=False`` sends responses as SSE streams which is what
    # the streamable-HTTP spec mandates for tool calls that may stream.
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,
        stateless=False,
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    async def mcp_handler(scope, receive, send) -> None:
        await session_manager.handle_request(scope, receive, send)

    app = Starlette(
        routes=[Mount("/mcp", app=mcp_handler)],
        lifespan=lifespan,
    )
    # Stash for tests / introspection.
    app.state.session_manager = session_manager
    app.state.mcp_server = server
    return app


def serve_mcp_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    include_analytics: bool = True,
) -> None:
    """Run the MCP-HTTP server in the foreground via uvicorn."""

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "voli.server.mcp_http requires uvicorn (installed with the 'mcp' extra)."
        ) from exc

    app = build_mcp_http_app(include_analytics=include_analytics)
    uvicorn.run(app, host=host, port=port, log_level="info")
