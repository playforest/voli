"""Theme palette tests.

Covers the 10 bundled palettes, the --theme / --cycle-theme flags, the
OQE_THEME env var, and the `oqe themes list / preview` subcommands.

These tests never call render with an `AnswerResponse` produced by the
real agent - we either build small synthetic responses or use the CLI's
own preview path, both of which avoid hitting Polygon.
"""

from __future__ import annotations

import io

import pytest

from oqe.agent.state import AnswerResponse
from oqe.cli import main
from oqe.cli_render import (
    DEFAULT_THEME,
    ESC,
    THEMES,
    cycle_next_theme,
    list_themes,
    make_theme,
    render_response,
    resolve_theme_name,
)

# ---- palette catalogue ------------------------------------------------------


def test_ten_themes_are_registered() -> None:
    """The product spec is 10 themes - regression-guard the count and the
    presence of the named themes the docs / CLI help advertise.
    """

    assert len(THEMES) == 10
    expected = {
        "bloomberg",
        "bloomberg_classic",
        "matrix",
        "amber_crt",
        "solarized_dark",
        "dracula",
        "nord",
        "cyberpunk",
        "mono",
        "paper",
    }
    assert set(THEMES) == expected


def test_default_theme_is_bloomberg() -> None:
    assert DEFAULT_THEME == "bloomberg"


def test_list_themes_returns_palettes_in_definition_order() -> None:
    names = [p.name for p in list_themes()]
    assert names[0] == "bloomberg"
    assert len(names) == 10
    assert names == list(THEMES.keys())


def test_each_palette_has_distinct_primary_colour() -> None:
    """Two themes with the same primary would feel identical at a glance."""

    primaries = {p.name: p.primary for p in list_themes()}
    assert len(set(primaries.values())) == len(primaries), primaries


# ---- name resolution --------------------------------------------------------


def test_resolve_theme_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("OQE_THEME", "matrix")
    assert resolve_theme_name(None) == "matrix"


def test_resolve_theme_explicit_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("OQE_THEME", "matrix")
    assert resolve_theme_name("dracula") == "dracula"


def test_resolve_theme_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("OQE_THEME", raising=False)
    assert resolve_theme_name(None) == DEFAULT_THEME


def test_resolve_theme_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown theme"):
        resolve_theme_name("not_a_real_theme")


# ---- rendering --------------------------------------------------------------


def _sample_resp() -> AnswerResponse:
    return AnswerResponse(
        supported=True,
        category="term_structure",
        summary="NVDA front IV 0.33 vs next IV 0.34 (diff 0.01).",
        table={"type": "term_structure", "rows": []},
        facts={"ticker": "NVDA", "front_iv": 0.33, "next_iv": 0.34},
        numbers_used=[0.33, 0.34, 0.01],
        limitations=[],
        suggested_rewrites=[],
    )


@pytest.mark.parametrize("name", list(THEMES.keys()))
def test_every_theme_renders_without_error(name: str) -> None:
    """Smoke test: each palette can produce a coloured render of the standard
    response shape. Catches typos in palette ANSI codes.
    """

    text = render_response(_sample_resp(), color=True, theme=name)
    assert ESC in text
    assert "NVDA" in text
    assert "[ SUMMARY ]" in text


def test_no_color_strips_ansi_for_every_theme() -> None:
    for name in THEMES:
        text = render_response(_sample_resp(), color=False, theme=name)
        assert ESC not in text, f"theme={name} leaked ANSI in no-colour mode"


def test_status_bar_only_advertises_non_default_themes() -> None:
    bb = render_response(_sample_resp(), color=True, theme="bloomberg")
    assert "THEME: bloomberg" not in bb  # default stays implicit

    matrix = render_response(_sample_resp(), color=True, theme="matrix")
    assert "THEME: matrix" in matrix


def test_two_themes_produce_visibly_different_output() -> None:
    """Different palettes -> different ANSI sequences in the rendered text."""

    a = render_response(_sample_resp(), color=True, theme="bloomberg")
    b = render_response(_sample_resp(), color=True, theme="matrix")
    assert a != b


# ---- cycling ----------------------------------------------------------------


def test_cycle_advances_through_all_themes(tmp_path, monkeypatch) -> None:
    cursor = tmp_path / "theme_cursor"
    monkeypatch.setenv("OQE_THEME_CURSOR", str(cursor))
    seen = [cycle_next_theme() for _ in range(len(THEMES))]
    assert seen == list(THEMES.keys()), seen
    # Cursor wraps back to the first theme on the next call.
    assert cycle_next_theme() == list(THEMES.keys())[0]


def test_cycle_persists_state_across_runs(tmp_path, monkeypatch) -> None:
    cursor = tmp_path / "theme_cursor"
    monkeypatch.setenv("OQE_THEME_CURSOR", str(cursor))

    first = cycle_next_theme()
    # Simulate a second process: file has been written, cursor reads from it.
    assert cursor.exists()
    second = cycle_next_theme()
    assert first != second


# ---- CLI integration --------------------------------------------------------


def test_themes_list_command_names_every_theme() -> None:
    out = io.StringIO()
    rc = main(["themes", "list", "--no-color"], out=out)
    text = out.getvalue()
    assert rc == 0
    for name in THEMES:
        assert name in text


def test_themes_preview_default_uses_bloomberg() -> None:
    out = io.StringIO()
    rc = main(["themes", "preview", "--no-color"], out=out)
    text = out.getvalue()
    assert rc == 0
    assert "[ SUMMARY ]" in text
    # Sample preview always shows NVDA term structure.
    assert "NVDA" in text


def test_themes_preview_specific_theme() -> None:
    out = io.StringIO()
    rc = main(["themes", "preview", "--theme", "dracula", "--no-color"], out=out)
    text = out.getvalue()
    assert rc == 0
    # In no-colour mode the theme name only appears in the status bar when
    # colour is on, so we can't easily assert that. Check the structural
    # invariants instead.
    assert "NVDA" in text
    assert "[ FACTS ]" in text


def test_themes_preview_all_renders_each_theme() -> None:
    out = io.StringIO()
    rc = main(["themes", "preview", "--all", "--no-color"], out=out)
    text = out.getvalue()
    assert rc == 0
    # Each theme's preview block contains the same Facts header; count them.
    assert text.count("[ FACTS ]") == len(THEMES)


def test_ask_with_unknown_theme_argparse_rejects() -> None:
    """argparse `choices=` should reject unknown themes before any tool runs."""

    with pytest.raises(SystemExit):
        main(["ask", "--theme", "not_a_theme", "NVDA ATM IV this week."])


def test_ask_cycle_theme_advances_cursor(tmp_path, monkeypatch) -> None:
    cursor = tmp_path / "theme_cursor"
    monkeypatch.setenv("OQE_THEME_CURSOR", str(cursor))

    # Use a stub registry - just need ask to reach _selected_theme().
    from oqe.agent.executor import ToolRegistry

    bad = ToolRegistry(
        tools={
            "get_underlying_snapshot": lambda _i: (_ for _ in ()).throw(RuntimeError("stub")),
            "list_option_contracts": lambda _i: (_ for _ in ()).throw(RuntimeError("stub")),
            "get_option_quotes": lambda _i: (_ for _ in ()).throw(RuntimeError("stub")),
            "get_option_greeks": lambda _i: (_ for _ in ()).throw(RuntimeError("stub")),
        }
    )
    out = io.StringIO()
    main(["ask", "--no-color", "--cycle-theme", "NVDA ATM IV"], registry=bad, out=out)
    main(["ask", "--no-color", "--cycle-theme", "NVDA ATM IV"], registry=bad, out=out)
    # Two cycles -> cursor advanced twice.
    assert int(cursor.read_text()) == 2


def test_make_theme_ignores_color_when_disabled() -> None:
    t = make_theme(color=False, theme="cyberpunk")
    # Even with a vivid palette, no-colour output is pure ASCII.
    assert t.value("hello") == "hello"
