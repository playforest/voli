"""MCP server tests.

We can't drive a real Claude Desktop client from a unit test, so we
exercise the parts that don't need stdio:
  * `_build_server` returns the registered tool catalogue.
  * the @list_tools handler returns one entry per tool with valid shape.
  * the @call_tool handler dispatches to the right OQE function and
    forwards results back as MCP TextContent.
  * the lazy-import shim raises a clear ImportError when mcp is missing.

The decorator-installed handlers live on `Server._tool_handlers` (or
similar internal attribute) - we avoid touching internals by re-running
the build with a custom tool list and triggering dispatch via the
publicly-exposed methods.
"""

from __future__ import annotations

import asyncio
import json
import sys
from unittest.mock import patch

import pytest

mcp = pytest.importorskip("mcp")  # skip cleanly if -E mcp not installed.

from oqe.llm.types import ToolDef  # noqa: E402
from oqe.mcp_server import _build_server, _to_mcp_tool, serve  # noqa: E402

# ---- _build_server ---------------------------------------------------------


def test_build_server_returns_full_tool_catalogue() -> None:
    server, tools = _build_server()
    assert server is not None
    names = {t.name for t in tools}
    assert names == {
        "compute_atm_iv_term_structure",
        "compute_skew_slope",
        "get_atm_greeks",
        "get_underlying_snapshot",
        "list_option_contracts",
        "get_option_quotes",
        "get_option_greeks",
    }


def test_build_server_with_raw_only() -> None:
    _server, tools = _build_server(include_analytics=False)
    names = {t.name for t in tools}
    assert names == {
        "get_underlying_snapshot",
        "list_option_contracts",
        "get_option_quotes",
        "get_option_greeks",
    }


# ---- _to_mcp_tool ----------------------------------------------------------


def test_to_mcp_tool_preserves_schema_and_camelcases_input_schema() -> None:
    """OQE uses input_schema (snake_case); MCP wants inputSchema (camel)."""

    from mcp import types

    src = ToolDef(
        name="echo",
        description="echo input",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        fn=lambda _args: "ok",
    )
    out = _to_mcp_tool(src, types)
    assert out.name == "echo"
    assert out.description == "echo input"
    assert out.inputSchema == src.input_schema


# ---- handler dispatch ------------------------------------------------------


def _drain_call_tool(server, name: str, arguments: dict) -> list:
    """Invoke the @server.call_tool() handler the way the SDK would.

    The SDK registers handlers on `server.request_handlers`. We don't poke
    private attrs - we route through the public `request_handlers` mapping
    keyed by request type. To keep this test API-stable, we look up the
    decorated function and call it directly with the same args the SDK
    passes (name + parsed arguments dict).
    """

    # Newer SDK versions stash the call-tool callback under a typed
    # request_handlers map. Fall back to scanning attributes if the layout
    # changes - we want a clear failure if Anthropic changes the contract.
    handlers = getattr(server, "request_handlers", None)
    if handlers is None:
        raise RuntimeError("MCP Server has no request_handlers map; SDK changed?")

    # Find the call_tool handler. Its key in request_handlers is the
    # CallToolRequest type - we don't import that to avoid coupling tests
    # to internal type names; instead we filter handlers by their assigned
    # name attribute or simply pick the one whose Pydantic schema field is
    # 'tools/call'.
    from mcp.types import CallToolRequest

    handler = handlers[CallToolRequest]
    request = CallToolRequest(
        method="tools/call",
        params={"name": name, "arguments": arguments},
    )
    result = asyncio.run(handler(request))
    return result.root.content


def test_call_tool_dispatches_to_get_underlying_snapshot(monkeypatch) -> None:
    """Patch the underlying polygon function so the dispatch path runs
    without touching Polygon."""

    captured = {}

    from datetime import UTC, datetime

    from oqe.models import UnderlyingSnapshot
    from oqe.tool_schemas import GetUnderlyingSnapshotInput, GetUnderlyingSnapshotOutput

    def _fake(inp: GetUnderlyingSnapshotInput):
        captured["ticker"] = inp.ticker
        snap = UnderlyingSnapshot(
            ticker=inp.ticker,
            spot=199.84,
            ts=datetime.now(UTC),
            source="polygon",
        )
        return GetUnderlyingSnapshotOutput(
            meta={
                "tool": "get_underlying_snapshot",
                "generated_at": datetime.now(UTC),
                "primary_source": "polygon",
                "warnings": [],
            },
            snapshot=snap,
        )

    monkeypatch.setattr("oqe.llm.tools.get_underlying_snapshot", _fake)

    server, _tools = _build_server()
    content = _drain_call_tool(server, "get_underlying_snapshot", {"ticker": "NVDA"})

    assert captured == {"ticker": "NVDA"}
    assert len(content) == 1
    payload = json.loads(content[0].text)
    assert payload["snapshot"]["ticker"] == "NVDA"
    assert payload["snapshot"]["spot"] == 199.84


def test_call_tool_unknown_tool_returns_error_payload() -> None:
    server, _tools = _build_server()
    content = _drain_call_tool(server, "not_a_tool", {})
    payload = json.loads(content[0].text)
    assert payload["error"] == "UnknownTool"


# ---- list_tools handler ----------------------------------------------------


def test_list_tools_returns_one_mcp_tool_per_oqe_tool() -> None:
    server, tools = _build_server()

    from mcp.types import ListToolsRequest

    handler = server.request_handlers[ListToolsRequest]
    request = ListToolsRequest(method="tools/list")
    result = asyncio.run(handler(request))
    listed = result.root.tools
    assert {t.name for t in listed} == {t.name for t in tools}


# ---- lean install shim -----------------------------------------------------


def test_serve_raises_clear_error_when_mcp_missing(monkeypatch) -> None:
    """Hide the SDK so the lazy-import raises the install hint."""

    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "mcp.server", None)
    monkeypatch.setitem(sys.modules, "mcp.server.stdio", None)

    # _require_sdk inside mcp_server is module-local; patch it directly.
    import oqe.mcp_server as mcp_server

    with (
        patch.object(
            mcp_server,
            "_require_sdk",
            side_effect=ImportError("MCP server requires the 'mcp' package."),
        ),
        pytest.raises(ImportError, match="mcp"),
    ):
        serve()
