"""REST tool dispatcher (the OpenAPI surface ChatGPT GPTs call).

Each voli tool is exposed as ``POST /tools/<tool_name>``. The body is the
tool's JSON-Schema-validated input arguments (the same shape the MCP
``tools/call`` request carries); the response is the tool's JSON output
or a small error envelope.

The dispatch logic delegates to :func:`voli.llm.tools.execute`, which is
already provider-agnostic (anthropic / openai / mcp / now rest), so the
tool surface here is identical to what an LLM driving voli sees.
"""

from __future__ import annotations

import json
from typing import Any

from voli.llm.tools import build_default_tools, execute
from voli.llm.types import ToolDef


def _require_starlette():
    try:
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "voli.server.rest requires starlette (installed via the 'mcp' extra)."
        ) from exc
    return Request, JSONResponse, Route


def _make_tool_handler(tool: ToolDef, tools: list[ToolDef]):
    Request, JSONResponse, _Route = _require_starlette()

    async def handler(request: Request) -> JSONResponse:
        # Parse the JSON body. An empty body is allowed for tools whose
        # input schema has no required fields.
        try:
            body_bytes = await request.body()
            arguments: dict[str, Any] = json.loads(body_bytes) if body_bytes else {}
            if not isinstance(arguments, dict):
                raise ValueError("request body must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            return JSONResponse({"error": "BadRequest", "message": str(exc)}, status_code=400)

        # Run the tool. ``execute`` returns a JSON string (the same one the
        # MCP transport sends back). Re-parse so we can return it as a
        # proper JSON object via Starlette.
        result_json = execute(tools, tool.name, arguments)
        try:
            payload = json.loads(result_json)
        except json.JSONDecodeError:
            payload = {"error": "InvalidJSON", "message": result_json}

        # voli's execute() returns a payload like {"error": "...", "message": ...}
        # for failures; surface those as 5xx so ChatGPT / curl can see the
        # difference between a successful tool call and a failure.
        if isinstance(payload, dict) and "error" in payload:
            return JSONResponse(payload, status_code=500)
        return JSONResponse(payload)

    handler.__name__ = f"tool_{tool.name}"
    return handler


def build_rest_routes(*, include_analytics: bool = True) -> list:
    """Return a list of ``starlette.routing.Route`` for every voli tool.

    Use it like::

        from starlette.applications import Starlette
        from voli.server.rest import build_rest_routes

        app = Starlette(routes=build_rest_routes())
    """

    _Request, _JSONResponse, Route = _require_starlette()

    tools = build_default_tools(include_analytics=include_analytics)
    routes = []
    for tool in tools:
        routes.append(
            Route(
                f"/tools/{tool.name}",
                endpoint=_make_tool_handler(tool, tools),
                methods=["POST"],
                name=f"tool_{tool.name}",
            )
        )
    return routes
