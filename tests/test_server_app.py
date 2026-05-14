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


def test_openapi_endpoint_is_public(monkeypatch):
    """The OpenAPI spec is a discovery document — clients fetch it before
    they have credentials configured. ChatGPT's Custom GPT Actions UI in
    particular fetches the spec at import time. So it must be reachable
    without auth, even though the routes it describes still require it."""

    client = _build_app_with_stub_tool(monkeypatch, auth_token="secret-token")

    # No auth header at all.
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["openapi"] == "3.1.0"
    assert "/tools/echo" in spec["paths"]
    # Server URL passed at build time made it into the spec.
    assert spec["servers"] == [{"url": "https://example.com"}]

    # The actual tool route still requires auth, even though the spec
    # describing it is public.
    resp = client.post("/tools/echo", json={"x": 1})
    assert resp.status_code == 401


# ---- Env-var fallbacks ---------------------------------------------------


def test_serve_falls_back_to_env_for_server_url_and_token(monkeypatch):
    """`voli.server.serve()` should read VOLI_SERVER_URL and VOLI_AUTH_TOKEN
    from env when not passed explicitly. Containerised deploys typically
    set them via the env file rather than threading them through the CLI
    or compose `command:`."""

    monkeypatch.setenv("VOLI_AUTH_TOKEN", "env-token")
    monkeypatch.setenv("VOLI_SERVER_URL", "https://from-env.example.com")

    # Capture what serve() passes to build_app + uvicorn.run instead of
    # actually booting a server.
    captured = {}

    def fake_build_app(**kwargs):
        captured["build_app"] = kwargs
        return "FAKE_APP"

    def fake_uvicorn_run(app, **kwargs):
        captured["uvicorn"] = {"app": app, **kwargs}

    monkeypatch.setattr("voli.server.build_app", fake_build_app)
    # `uvicorn` is imported inside serve(); patch the module attribute
    # via sys.modules so the import inside serve() returns our stub.
    import sys
    import types

    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = fake_uvicorn_run
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    from voli.server import serve

    serve(host="127.0.0.1", port=9999)

    assert captured["build_app"]["auth_token"] == "env-token"
    assert captured["build_app"]["server_url"] == "https://from-env.example.com"
    assert captured["uvicorn"]["host"] == "127.0.0.1"
    assert captured["uvicorn"]["port"] == 9999


def test_explicit_args_beat_env_vars(monkeypatch):
    """An explicit --server-url / explicit auth_token must win over env."""

    monkeypatch.setenv("VOLI_AUTH_TOKEN", "env-token")
    monkeypatch.setenv("VOLI_SERVER_URL", "https://from-env.example.com")

    captured = {}

    def fake_build_app(**kwargs):
        captured["build_app"] = kwargs
        return "FAKE_APP"

    monkeypatch.setattr("voli.server.build_app", fake_build_app)
    import sys
    import types

    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    from voli.server import serve

    serve(auth_token="cli-token", server_url="https://from-cli.example.com")

    assert captured["build_app"]["auth_token"] == "cli-token"
    assert captured["build_app"]["server_url"] == "https://from-cli.example.com"


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
