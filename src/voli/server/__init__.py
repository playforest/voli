"""HTTP server for hosting voli's tools to remote clients.

Two surfaces are exposed by the umbrella ``voli serve`` command:

  * ``/mcp`` — Streamable-HTTP MCP transport, what claude.ai's Custom
    Integrations and other MCP-aware clients speak.
  * ``/openapi.json`` + ``/tools/<name>`` — a thin REST + OpenAPI 3.1
    surface for ChatGPT Custom GPT Actions and other OpenAPI consumers.

Both routes share a single bearer-token auth middleware and dispatch to
the same ``voli.llm.tools.build_default_tools()`` registry, so the tool
catalogue is identical across providers.

This package is intentionally small. Phase A of the deploy work is just
the code; the Dockerfile, the digitalocean walkthrough, and the actual
provider wiring live under ``docs/deploy/``.
"""

from __future__ import annotations

__all__ = ["build_mcp_http_app", "serve_mcp_http"]


def build_mcp_http_app(*, include_analytics: bool = True):
    """Lazy import to keep ``voli`` core install light when MCP isn't used."""

    from .mcp_http import build_mcp_http_app as _build

    return _build(include_analytics=include_analytics)


def serve_mcp_http(
    *, host: str = "127.0.0.1", port: int = 8080, include_analytics: bool = True
) -> None:
    from .mcp_http import serve_mcp_http as _serve

    _serve(host=host, port=port, include_analytics=include_analytics)
