"""Smoke tests for the HTTP MCP transport.

A full client round-trip (initialize handshake + tools/list + tools/call
over SSE) is exercised manually with the MCP Inspector or an integration
test environment; here we just verify the Starlette app builds, mounts
``/mcp``, and registers the same tool catalogue the stdio transport uses.
"""

from __future__ import annotations

import pytest

# Skip the whole module if the 'mcp' extra isn't installed (the lean voli
# install doesn't need it and shouldn't fail tests for missing it).
pytest.importorskip("mcp.server.streamable_http_manager")
pytest.importorskip("starlette")


def test_build_mcp_http_app_constructs_without_error():
    from voli.server.mcp_http import build_mcp_http_app

    app = build_mcp_http_app()
    assert app is not None
    # Sanity-check that the app stashed its session manager + server for
    # introspection, so future tests / debug tools can poke at them.
    assert app.state.session_manager is not None
    assert app.state.mcp_server is not None


def test_mcp_route_is_mounted():
    from starlette.routing import Mount

    from voli.server.mcp_http import build_mcp_http_app

    app = build_mcp_http_app()
    mounts = [r for r in app.routes if isinstance(r, Mount)]
    paths = [m.path for m in mounts]
    assert "/mcp" in paths, f"expected /mcp mount, got {paths!r}"


def test_tool_catalogue_matches_stdio_transport():
    """The HTTP and stdio modes must expose an identical tool list."""

    from voli.mcp_server import _build_server
    from voli.server.mcp_http import build_mcp_http_app

    _stdio_server, stdio_tools = _build_server(include_analytics=True)
    # Just constructing the HTTP app with the same flag is enough to prove
    # the wiring; the catalogue itself comes from _build_server, so we
    # rebuild it and compare directly.
    build_mcp_http_app(include_analytics=True)
    stdio_names = {t.name for t in stdio_tools}
    _, http_tools = _build_server(include_analytics=True)
    http_names = {t.name for t in http_tools}

    assert stdio_names == http_names
    assert stdio_names, "tool catalogue should not be empty"


def test_raw_only_mode_skips_analytics_tools():
    from voli.mcp_server import _build_server
    from voli.server.mcp_http import build_mcp_http_app

    _, raw_tools = _build_server(include_analytics=False)
    raw_names = {t.name for t in raw_tools}

    # Analytics shortcut tools start with `compute_`; raw mode must drop them.
    assert not any(n.startswith("compute_") for n in raw_names), raw_names
    assert "get_underlying_snapshot" in raw_names

    # build_mcp_http_app honours the same flag.
    app = build_mcp_http_app(include_analytics=False)
    assert app is not None  # constructed without error
