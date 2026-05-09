"""End-to-end tests for the umbrella ``voli serve`` HTTP app.

Covers:
  * Bearer-token auth on the protected surfaces
  * Public passthrough for /healthz and /openapi.json
  * /openapi.json content shape
  * /tools/<name> dispatch with auth
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("starlette")


def _build_app_with_stub_tool(monkeypatch, *, auth_token: str | None):
    """Return a TestClient bound to build_app() with a single stubbed tool."""

    from starlette.testclient import TestClient

    from voli.llm.types import ToolDef
    from voli.server import build_app
    from voli.server import openapi as openapi_mod
    from voli.server import rest as rest_mod

    fake = ToolDef(
        name="echo",
        description="Echo the arguments back.",
        input_schema={"type": "object", "additionalProperties": True},
        fn=lambda args: json.dumps({"echoed": args}),
    )
    monkeypatch.setattr(rest_mod, "build_default_tools", lambda include_analytics=True: [fake])
    monkeypatch.setattr(openapi_mod, "build_default_tools", lambda include_analytics=True: [fake])

    app = build_app(auth_token=auth_token, server_url="https://example.com")
    return TestClient(app)


# ---- Auth ----------------------------------------------------------------


def test_protected_route_requires_auth(monkeypatch):
    client = _build_app_with_stub_tool(monkeypatch, auth_token="secret-token")
    resp = client.post("/tools/echo", json={"foo": "bar"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer ")
    assert resp.json() == {
        "error": "Unauthorized",
        "message": "Authentication required.",
    }


def test_protected_route_rejects_wrong_token(monkeypatch):
    client = _build_app_with_stub_tool(monkeypatch, auth_token="secret-token")
    resp = client.post(
        "/tools/echo",
        json={"foo": "bar"},
        headers={"authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_protected_route_accepts_correct_token(monkeypatch):
    client = _build_app_with_stub_tool(monkeypatch, auth_token="secret-token")
    resp = client.post(
        "/tools/echo",
        json={"foo": "bar"},
        headers={"authorization": "Bearer secret-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"echoed": {"foo": "bar"}}


def test_no_auth_mode_lets_everything_through(monkeypatch):
    """auth_token=None means the deploy is in --no-auth mode."""

    client = _build_app_with_stub_tool(monkeypatch, auth_token=None)
    resp = client.post("/tools/echo", json={"foo": "bar"})
    assert resp.status_code == 200


def test_non_bearer_authorization_header_rejected(monkeypatch):
    """Basic auth or other schemes must not be accepted."""

    client = _build_app_with_stub_tool(monkeypatch, auth_token="secret-token")
    resp = client.post(
        "/tools/echo",
        json={"foo": "bar"},
        headers={"authorization": "Basic c2VjcmV0LXRva2Vu"},
    )
    assert resp.status_code == 401


# ---- Health + OpenAPI ----------------------------------------------------


def test_healthz_is_public(monkeypatch):
    client = _build_app_with_stub_tool(monkeypatch, auth_token="secret-token")
    resp = client.get("/healthz")  # no auth header
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_endpoint_returns_spec(monkeypatch):
    client = _build_app_with_stub_tool(monkeypatch, auth_token="secret-token")
    resp = client.get("/openapi.json", headers={"authorization": "Bearer secret-token"})
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["openapi"] == "3.1.0"
    assert "/tools/echo" in spec["paths"]
    # Server URL passed at build time made it into the spec.
    assert spec["servers"] == [{"url": "https://example.com"}]


# ---- MCP route still mounted --------------------------------------------


def test_mcp_route_is_mounted_under_umbrella(monkeypatch):
    """The umbrella app should still expose /mcp from the sub-app.

    A bare GET (no Accept: text/event-stream) returns 4xx from the SDK,
    not 404, which proves the route exists and the auth check passed.

    Wrapped in `with TestClient(...) as client` so Starlette's lifespan
    fires (the MCP session manager needs its task group).
    """

    from starlette.testclient import TestClient

    from voli.llm.types import ToolDef
    from voli.server import build_app
    from voli.server import openapi as openapi_mod
    from voli.server import rest as rest_mod

    fake = ToolDef(
        name="echo",
        description="x",
        input_schema={"type": "object"},
        fn=lambda args: json.dumps(args),
    )
    monkeypatch.setattr(rest_mod, "build_default_tools", lambda include_analytics=True: [fake])
    monkeypatch.setattr(openapi_mod, "build_default_tools", lambda include_analytics=True: [fake])

    app = build_app(auth_token="secret-token")
    with TestClient(app) as client:
        resp = client.get("/mcp", headers={"authorization": "Bearer secret-token"})
    # 406 from the MCP SDK when there's no Accept: text/event-stream header,
    # or 4xx of some flavour from a newer SDK version. The point: route
    # exists, auth passed.
    assert resp.status_code != 401, "auth should have passed"
    assert resp.status_code != 404, "MCP route should be mounted"
