"""Tests for the REST tool dispatcher.

Drives the dispatcher with a TestClient; the underlying voli tools are
exercised with stub data so no network is involved.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("starlette")


def _build_test_app(routes):
    from starlette.applications import Starlette

    return Starlette(routes=routes)


def test_known_tool_dispatches(monkeypatch):
    """A known tool is callable via POST /tools/<name>."""

    from starlette.testclient import TestClient

    # Stub the tool catalogue to avoid touching Polygon. The handler
    # we register just echoes its arguments.
    from voli.llm.types import ToolDef
    from voli.server import rest

    def _echo(args: dict) -> str:
        return json.dumps({"echoed": args})

    fake_tool = ToolDef(
        name="echo",
        description="Echo the arguments back.",
        input_schema={"type": "object", "additionalProperties": True},
        fn=_echo,
    )
    monkeypatch.setattr(rest, "build_default_tools", lambda include_analytics=True: [fake_tool])

    routes = rest.build_rest_routes()
    app = _build_test_app(routes)
    client = TestClient(app)

    resp = client.post("/tools/echo", json={"foo": "bar"})
    assert resp.status_code == 200
    assert resp.json() == {"echoed": {"foo": "bar"}}


def test_empty_body_allowed_for_no_arg_tool(monkeypatch):
    from starlette.testclient import TestClient

    from voli.llm.types import ToolDef
    from voli.server import rest

    fake = ToolDef(
        name="ping",
        description="No args; returns ok.",
        input_schema={"type": "object", "properties": {}},
        fn=lambda _args: json.dumps({"ok": True}),
    )
    monkeypatch.setattr(rest, "build_default_tools", lambda include_analytics=True: [fake])

    client = TestClient(_build_test_app(rest.build_rest_routes()))
    resp = client.post("/tools/ping")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_malformed_json_returns_400(monkeypatch):
    from starlette.testclient import TestClient

    from voli.llm.types import ToolDef
    from voli.server import rest

    fake = ToolDef(
        name="echo",
        description="x",
        input_schema={"type": "object"},
        fn=lambda args: json.dumps(args),
    )
    monkeypatch.setattr(rest, "build_default_tools", lambda include_analytics=True: [fake])

    client = TestClient(_build_test_app(rest.build_rest_routes()))
    resp = client.post(
        "/tools/echo",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "BadRequest"


def test_non_object_body_returns_400(monkeypatch):
    """A bare JSON array shouldn't be accepted; tools take object arguments."""

    from starlette.testclient import TestClient

    from voli.llm.types import ToolDef
    from voli.server import rest

    fake = ToolDef(
        name="echo",
        description="x",
        input_schema={"type": "object"},
        fn=lambda args: json.dumps(args),
    )
    monkeypatch.setattr(rest, "build_default_tools", lambda include_analytics=True: [fake])

    client = TestClient(_build_test_app(rest.build_rest_routes()))
    resp = client.post("/tools/echo", json=[1, 2, 3])
    assert resp.status_code == 400


def test_tool_error_surfaces_as_500(monkeypatch):
    """voli's execute() catches exceptions and returns an {error, message}
    JSON payload. The REST surface should turn that into a 5xx so callers
    can distinguish failures from successful tool output."""

    from starlette.testclient import TestClient

    from voli.llm.types import ToolDef
    from voli.server import rest

    def _raises(_args):
        raise RuntimeError("boom")

    fake = ToolDef(
        name="bomb",
        description="x",
        input_schema={"type": "object"},
        fn=_raises,
    )
    monkeypatch.setattr(rest, "build_default_tools", lambda include_analytics=True: [fake])

    client = TestClient(_build_test_app(rest.build_rest_routes()))
    resp = client.post("/tools/bomb", json={})
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "RuntimeError"
    assert "boom" in body["message"]


def test_unknown_tool_route_returns_404():
    """No route is registered for an unknown tool name, so Starlette
    handles it as a 404 by default."""

    from starlette.testclient import TestClient

    from voli.server import rest

    # Use the real catalogue so we can be sure /tools/nonexistent isn't
    # accidentally registered.
    routes = rest.build_rest_routes()
    client = TestClient(_build_test_app(routes))
    resp = client.post("/tools/this_tool_does_not_exist", json={})
    assert resp.status_code == 404


def test_real_catalogue_registers_all_tools():
    """Sanity: build_rest_routes covers every tool in build_default_tools."""

    from voli.llm.tools import build_default_tools
    from voli.server.rest import build_rest_routes

    expected = {f"/tools/{t.name}" for t in build_default_tools()}
    routes = build_rest_routes()
    actual = {r.path for r in routes}
    assert actual == expected
