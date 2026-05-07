"""Wrap the four Polygon-backed Voli tools as ToolDef objects.

We build the JSON schemas from the existing Pydantic input models in
`voli.tool_schemas` so the LLM sees the exact same contract the rule-based
agent uses. Each tool's `fn` calls the real Polygon-backed implementation
and returns the response as a JSON string.

Why JSON strings as the tool result rather than Python objects? Both
Anthropic + OpenAI tool-use APIs send the result back to the LLM as text
(or a content block); a JSON string is the simplest stable representation
the LLM can parse and quote in its answer.
"""

from __future__ import annotations

import json
from typing import Any

from voli.tool_schemas import (
    GetOptionGreeksInput,
    GetOptionGreeksOutput,
    GetOptionQuotesInput,
    GetOptionQuotesOutput,
    GetUnderlyingSnapshotInput,
    GetUnderlyingSnapshotOutput,
    ListOptionContractsInput,
    ListOptionContractsOutput,
)
from voli.tools.polygon_tools import (
    get_option_greeks,
    get_option_quotes,
    get_underlying_snapshot,
    list_option_contracts,
)

from .types import ToolDef


def _schema(model) -> dict[str, Any]:
    """Pydantic v2 -> JSON schema. Strip the Pydantic-internal `$defs`/`$ref`
    indirection that confuses some tool-use validators by inlining refs.
    """

    schema = model.model_json_schema()
    return _inline_refs(schema)


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs") or schema.get("definitions") or {}

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and len(node) == 1:
                ref = node["$ref"]
                # e.g. "#/$defs/Foo"
                key = ref.split("/")[-1]
                if key in defs:
                    return _walk(dict(defs[key]))
                return node
            return {k: _walk(v) for k, v in node.items() if k not in ("$defs", "definitions")}
        if isinstance(node, list):
            return [_walk(x) for x in node]
        return node

    cleaned = _walk(schema)
    return cleaned


def _dump(obj) -> str:
    """Pydantic v2 model -> JSON string for the tool result.

    `mode='json'` so datetimes serialise as ISO strings, etc.
    `exclude_none=True` keeps the LLM context lean (drops `null` fields).
    """

    return obj.model_dump_json(exclude_none=True)


# ---- tool functions --------------------------------------------------------


def _tool_get_underlying_snapshot(args: dict[str, Any]) -> str:
    out: GetUnderlyingSnapshotOutput = get_underlying_snapshot(GetUnderlyingSnapshotInput(**args))
    return _dump(out)


def _tool_list_option_contracts(args: dict[str, Any]) -> str:
    out: ListOptionContractsOutput = list_option_contracts(ListOptionContractsInput(**args))
    return _dump(out)


def _tool_get_option_quotes(args: dict[str, Any]) -> str:
    out: GetOptionQuotesOutput = get_option_quotes(GetOptionQuotesInput(**args))
    return _dump(out)


def _tool_get_option_greeks(args: dict[str, Any]) -> str:
    out: GetOptionGreeksOutput = get_option_greeks(GetOptionGreeksInput(**args))
    return _dump(out)


# ---- public builder --------------------------------------------------------


def build_default_tools(*, include_analytics: bool = True) -> list[ToolDef]:
    """Return the LLM tool surface.

    Two layers, both included by default:

      * Analytics tools (Stage B) - high-level, one-call answers for the
        canonical question shapes (term structure, skew slope, ATM greeks).
        Prefer these.
      * Raw Polygon tools (Stage A) - chain listing, quotes, greeks by
        symbol. Use when the analytics layer doesn't cover what's asked.

    Pass `include_analytics=False` to expose only the raw tools (useful
    for testing the LLM's ability to chain primitives, or for prompts that
    explicitly want a chain slice).
    """

    raw = _build_raw_polygon_tools()
    if not include_analytics:
        return raw

    # Local import keeps build_default_tools() lightweight if the analytics
    # module ever grows expensive imports.
    from .analytics_tools import build_analytics_tools

    return build_analytics_tools() + raw


def _build_raw_polygon_tools() -> list[ToolDef]:
    return [
        ToolDef(
            name="get_underlying_snapshot",
            description=(
                "Fetch the current spot price snapshot for an underlying ticker. "
                "Returns ticker, spot, ts (UTC), source. Cheap; call freely."
            ),
            input_schema=_schema(GetUnderlyingSnapshotInput),
            fn=_tool_get_underlying_snapshot,
        ),
        ToolDef(
            name="list_option_contracts",
            description=(
                "List option contracts for an underlying. Optional filters: "
                "expiry (YYYY-MM-DD), right ('C' for calls / 'P' for puts), "
                "strike_min, strike_max, limit. Returns a list of OptionContract "
                "objects with option_symbol, strike, expiry, right, multiplier. "
                "Always call this before fetching quotes/greeks so you have the "
                "option_symbol identifiers."
            ),
            input_schema=_schema(ListOptionContractsInput),
            fn=_tool_list_option_contracts,
        ),
        ToolDef(
            name="get_option_quotes",
            description=(
                "Fetch bid/ask/last/mid for one or more option_symbols (must be "
                "Polygon-style symbols like 'O:NVDA260516C00100000', obtained "
                "from list_option_contracts). Returns one OptionQuote per symbol "
                "that has data."
            ),
            input_schema=_schema(GetOptionQuotesInput),
            fn=_tool_get_option_quotes,
        ),
        ToolDef(
            name="get_option_greeks",
            description=(
                "Fetch implied vol + greeks (delta/gamma/theta/vega) for one or "
                "more option_symbols. Use this for IV-based questions (term "
                "structure, skew, ATM IV). The 'mode' field defaults to vendor "
                "greeks; only override if the user explicitly asks for "
                "Black-Scholes computation."
            ),
            input_schema=_schema(GetOptionGreeksInput),
            fn=_tool_get_option_greeks,
        ),
    ]


def execute(tools: list[ToolDef], name: str, arguments: dict[str, Any]) -> str:
    """Dispatch a tool call by name. Returns a JSON string for the LLM."""

    for t in tools:
        if t.name == name:
            try:
                result = t.fn(arguments)
                if isinstance(result, str):
                    return result
                # Allow tools to return dicts/lists for convenience.
                return json.dumps(result, default=str)
            except Exception as exc:
                return json.dumps(
                    {
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )
    return json.dumps({"error": "UnknownTool", "message": f"No such tool: {name}"})
