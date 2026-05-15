"""Unit tests for the OpenAPI 3.1 spec generator."""

from __future__ import annotations

from voli.server.openapi import OPENAPI_VERSION, build_openapi_spec


def test_spec_top_level_shape():
    spec = build_openapi_spec(server_url="https://example.com")
    assert spec["openapi"] == OPENAPI_VERSION
    assert spec["info"]["title"] == "Voli"
    assert spec["servers"] == [{"url": "https://example.com"}]
    assert "/tools/get_underlying_snapshot" in spec["paths"]


def test_server_url_optional():
    """For local tests we sometimes don't have a public URL yet."""

    spec = build_openapi_spec()
    assert "servers" not in spec


def test_server_url_trailing_slash_is_normalised():
    spec = build_openapi_spec(server_url="https://example.com/")
    assert spec["servers"] == [{"url": "https://example.com"}]


def test_each_tool_becomes_a_post_path():
    spec = build_openapi_spec()
    for path, ops in spec["paths"].items():
        assert path.startswith("/tools/")
        assert "post" in ops
        op = ops["post"]
        # Every op gets an operationId derived from the tool name.
        assert path.endswith("/" + op["operationId"])
        # Body is required JSON with a schema.
        assert op["requestBody"]["required"] is True
        body = op["requestBody"]["content"]["application/json"]
        assert body["schema"], "schema body must be present"


def test_global_bearer_auth_is_declared():
    spec = build_openapi_spec()
    assert spec["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "description": (
            "Static bearer token. The server reads it from the "
            "VOLI_AUTH_TOKEN environment variable; clients send "
            "`Authorization: Bearer <token>`."
        ),
    }
    assert spec["security"] == [{"bearerAuth": []}]


def test_per_op_security_is_set_to_bearer():
    """Belt-and-braces: each operation also names bearerAuth explicitly so
    a generator that ignores top-level `security` still gets it right."""

    spec = build_openapi_spec()
    for ops in spec["paths"].values():
        assert ops["post"]["security"] == [{"bearerAuth": []}]


def test_raw_only_mode_drops_analytics_paths():
    spec = build_openapi_spec(include_analytics=False)
    paths = list(spec["paths"].keys())
    # Analytics shortcut tools are exposed as /tools/compute_*.
    assert not any("/compute_" in p for p in paths), paths
    # Raw catalogue still has the four primitives.
    for raw in (
        "/tools/get_underlying_snapshot",
        "/tools/list_option_contracts",
        "/tools/get_option_quotes",
        "/tools/get_option_greeks",
    ):
        assert raw in paths


def test_tools_override_for_unit_tests():
    """Callers can pass a custom tool list (used in dependency-light tests)."""

    from voli.llm.types import ToolDef

    fake = ToolDef(
        name="dummy",
        description="Returns 42. The first sentence.",
        input_schema={"type": "object", "properties": {}},
        fn=lambda _args: '{"value": 42}',
    )
    spec = build_openapi_spec(tools=[fake])
    assert list(spec["paths"].keys()) == ["/tools/dummy"]
    op = spec["paths"]["/tools/dummy"]["post"]
    assert op["operationId"] == "dummy"
    # Summary is the first sentence of the description, not the whole thing.
    assert op["summary"] == "Returns 42."


def test_input_schema_is_preserved_verbatim():
    """Pydantic-derived JSON schemas should make it through unmodified so
    ChatGPT sees exactly the same constraints voli's stdio MCP clients see."""

    spec = build_openapi_spec()
    op = spec["paths"]["/tools/get_underlying_snapshot"]["post"]
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    # Sanity: the get_underlying_snapshot input has a required ticker field.
    assert schema["type"] == "object"
    assert "ticker" in schema["properties"]


# ---- ChatGPT validator compatibility -------------------------------------
#
# ChatGPT's Custom GPT Actions importer runs a stricter validator than the
# OpenAPI 3.1 spec strictly requires. These tests pin the three pieces of
# shape it cares about so we don't regress and force a re-import diagnostic
# session later.


def test_components_schemas_exists_for_chatgpt_validator():
    """ChatGPT rejects a spec where `components.schemas` is absent, even
    though OpenAPI 3.1 allows it. Presence (empty object) is enough."""

    spec = build_openapi_spec()
    assert "schemas" in spec["components"]
    assert spec["components"]["schemas"] == {}


def test_response_schema_has_additional_properties():
    """Every 200 response must declare additionalProperties so ChatGPT's
    validator doesn't flag the bare {"type": "object"} as 'missing
    properties'."""

    spec = build_openapi_spec()
    for path, ops in spec["paths"].items():
        schema = ops["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema.get("type") == "object", path
        assert schema.get("additionalProperties") is True, path


def test_no_tool_description_exceeds_300_chars():
    """ChatGPT's validator caps operation descriptions at 300 chars. Keep
    every tool description under that ceiling so the importer doesn't warn
    (and in some cases refuse to register the action)."""

    from voli.llm.tools import build_default_tools

    too_long = [
        (t.name, len(t.description)) for t in build_default_tools() if len(t.description) > 300
    ]
    assert not too_long, f"descriptions over 300 chars: {too_long}"
