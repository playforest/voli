"""Model Context Protocol (MCP) server.

Exposes the OQE tools to any MCP client - Claude Desktop, claude.ai web
custom integrations, Continue, Zed, etc. The same `build_default_tools()`
that powers `oqe llm-ask` is reused here, so the analytics + raw layers
the LLM has access to via our CLI are exactly the same set Claude sees
when it talks to OQE through MCP.

We lazy-import the `mcp` SDK so users on the lean install don't pay for
an unused dep; calling `serve()` without it raises a clear ImportError
pointing at `poetry install -E mcp`.

Configuration for Claude Desktop (~/Library/Application Support/Claude/
claude_desktop_config.json on macOS):

    {
      "mcpServers": {
        "oqe": {
          "command": "poetry",
          "args": ["run", "oqe", "mcp-serve"],
          "cwd": "/path/to/options-query-agent",
          "env": {"POLYGON_API_KEY": "sk-..."}
        }
      }
    }

Restart Claude Desktop and the OQE tools appear in the Available Tools
panel.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .llm.tools import build_default_tools
from .llm.tools import execute as execute_tool
from .llm.types import ToolDef

SERVER_NAME = "oqe"
SERVER_DESCRIPTION = (
    "Options Query Engine - grounded options chain tools (snapshot, contracts, "
    "quotes, greeks) plus analytics (term structure, skew slope, ATM greeks) "
    "backed by Polygon."
)


def _require_sdk():
    """Lazy import so the lean install doesn't need the mcp dep."""

    try:
        from mcp import types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError as exc:
        raise ImportError(
            "MCP server requires the 'mcp' package.\nInstall with: poetry install -E mcp"
        ) from exc
    return Server, stdio_server, types


def _to_mcp_tool(tool: ToolDef, types_module) -> Any:
    """Convert one OQE ToolDef into the MCP types.Tool shape."""

    return types_module.Tool(
        name=tool.name,
        description=tool.description,
        inputSchema=tool.input_schema,
    )


def _build_server(*, include_analytics: bool = True):
    """Construct the MCP Server with our tool catalogue wired in.

    Returned as a 2-tuple `(server, tools)` so callers (mostly tests) can
    inspect the registered tools without booting the stdio transport.
    """

    Server, _stdio, types = _require_sdk()

    tools = build_default_tools(include_analytics=include_analytics)
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list:
        return [_to_mcp_tool(t, types) for t in tools]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list:
        # OQE tools are sync functions that hit Polygon (which is also
        # sync via httpx). Run them in the default executor so the MCP
        # event loop isn't blocked.
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: execute_tool(tools, name, arguments or {}),
        )
        return [types.TextContent(type="text", text=result)]

    return server, tools


async def _serve_async(*, include_analytics: bool = True) -> None:
    Server, stdio_server, _types = _require_sdk()
    server, _tools = _build_server(include_analytics=include_analytics)
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)


def serve(*, include_analytics: bool = True) -> None:
    """Block on the MCP stdio loop. Returns when the client disconnects."""

    asyncio.run(_serve_async(include_analytics=include_analytics))
