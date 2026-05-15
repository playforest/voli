"""OpenAPI 3.1 spec generation for voli's tool catalogue.

Why this exists: ChatGPT Custom GPT Actions consume OpenAPI specs to
discover what endpoints they can call. Claude.ai uses MCP for the same
purpose. The two protocols want different shapes, but the underlying
tools are the same set, so we generate an OpenAPI spec from the same
``voli.llm.tools.build_default_tools()`` registry the MCP transport
uses. One source of truth, two surfaces.

The spec emitted here describes the REST surface served by
``voli.server.rest`` (added in A3): ``POST /tools/<tool_name>`` for each
voli tool, JSON request/response, bearer-token auth.
"""

from __future__ import annotations

from typing import Any

from voli.llm.tools import build_default_tools
from voli.llm.types import ToolDef

OPENAPI_VERSION = "3.1.0"


def _first_sentence(text: str) -> str:
    """Take the first sentence of a description for OpenAPI's ``summary`` field.

    OpenAPI's summary should fit on one line; ChatGPT shows it in the GPT
    Actions UI. The full description goes in the ``description`` field.
    """

    # Strip newlines, take up to the first period followed by a space, cap
    # at ~120 chars so the GPT UI doesn't truncate awkwardly.
    flat = " ".join(text.split())
    if "." in flat:
        head, _, _ = flat.partition(". ")
        flat = head + "."
    return flat[:120]


def _operation(tool: ToolDef) -> dict[str, Any]:
    """Build the OpenAPI Operation Object for one voli tool."""

    return {
        "operationId": tool.name,
        "summary": _first_sentence(tool.description),
        "description": tool.description,
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": tool.input_schema,
                }
            },
        },
        "responses": {
            "200": {
                "description": (
                    "Tool output as a JSON object. Shape varies per tool; "
                    "see voli.tool_schemas for the typed envelopes returned by "
                    "the underlying voli implementations."
                ),
                "content": {
                    "application/json": {
                        # Permissive object schema. ChatGPT's validator
                        # rejects bare {"type": "object"} as "missing
                        # properties", so we set additionalProperties: true
                        # to signal "any object" explicitly. The real
                        # shape is documented in voli.tool_schemas.
                        "schema": {"type": "object", "additionalProperties": True},
                    }
                },
            },
            "401": {"description": "Missing or invalid bearer token."},
            "404": {"description": "Unknown tool name."},
            "500": {"description": "Tool execution error."},
        },
        "security": [{"bearerAuth": []}],
        "tags": ["voli"],
    }


def build_openapi_spec(
    *,
    server_url: str | None = None,
    title: str = "Voli",
    version: str = "0.1.0",
    description: str | None = None,
    include_analytics: bool = True,
    tools: list[ToolDef] | None = None,
) -> dict[str, Any]:
    """Generate the OpenAPI 3.1 spec for the REST tool surface.

    ``server_url`` is the public base URL where ``voli serve`` is reachable
    (e.g. ``https://voli.example.com``). It must be set when the spec is
    consumed by ChatGPT Custom GPT Actions; for local testing or unit
    tests, leaving it ``None`` produces a spec without a servers list.

    Pass ``tools`` to override the catalogue (mostly useful in tests).
    """

    tool_list = (
        tools if tools is not None else build_default_tools(include_analytics=include_analytics)
    )

    paths: dict[str, Any] = {}
    for tool in tool_list:
        paths[f"/tools/{tool.name}"] = {"post": _operation(tool)}

    spec: dict[str, Any] = {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": title,
            "version": version,
            "description": description
            or (
                "REST + OpenAPI surface for voli's options-chain tools. "
                "Mirror of the MCP catalogue at /mcp; same tools, different "
                "transport."
            ),
        },
        "paths": paths,
        "components": {
            # ChatGPT's spec validator expects `schemas` to exist as an
            # object even when we have no reusable component schemas to
            # declare. Leaving it empty is fine; presence is what matters.
            "schemas": {},
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "Static bearer token. The server reads it from the "
                        "VOLI_AUTH_TOKEN environment variable; clients send "
                        "`Authorization: Bearer <token>`."
                    ),
                }
            },
        },
        # Apply auth globally so every per-tool operation is protected by
        # default. Operations can opt out by overriding `security: []`.
        "security": [{"bearerAuth": []}],
    }
    if server_url:
        spec["servers"] = [{"url": server_url.rstrip("/")}]
    return spec
