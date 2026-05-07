"""Renderer tests: themed text and JSON output paths.

We build small AnswerResponse objects directly and assert structure rather
than parsing ANSI escape sequences for exact colours.
"""

from __future__ import annotations

import json

from voli.agent.state import AnswerResponse
from voli.cli_render import ESC, render_json, render_response


def _resp(**overrides) -> AnswerResponse:
    base = dict(
        supported=True,
        category="term_structure",
        summary="NVDA ATM IV: front 0.42 vs next 0.45.",
        table={
            "type": "term_structure",
            "rows": [
                {"expiry": "2026-05-09", "atm_strike": 100.0, "atm_iv": 0.42},
                {"expiry": "2026-05-16", "atm_strike": 100.0, "atm_iv": 0.45},
            ],
        },
        facts={
            "ticker": "NVDA",
            "spot": {"value": 102.5, "ts": "2026-05-05T12:00:00Z", "source": "polygon"},
            "atm_strike": 100.0,
            "front_iv": 0.42,
            "next_iv": 0.45,
            "flags": [],
        },
        numbers_used=[0.42, 0.45, 100.0, 102.5],
        limitations=[],
        suggested_rewrites=[],
    )
    base.update(overrides)
    return AnswerResponse(**base)


def test_color_mode_emits_ansi_escape_sequences() -> None:
    text = render_response(_resp(), color=True)
    assert ESC in text
    assert "[ SUMMARY ]" in text  # section title in plain form is still there
    assert "NVDA" in text


def test_no_color_mode_is_pure_ascii() -> None:
    text = render_response(_resp(), color=False)
    assert ESC not in text
    assert "[ SUMMARY ]" in text
    assert "[ TERM STRUCTURE ]" in text
    assert "[ FACTS ]" in text
    assert "TICKER" in text


def test_status_bar_includes_category_and_ok_marker() -> None:
    text = render_response(_resp(), color=False)
    assert "Voli" in text
    assert "CATEGORY: TERM_STRUCTURE" in text
    assert "OK" in text


def test_status_bar_marks_refused_for_not_supported() -> None:
    refused = _resp(
        supported=False,
        category="not_supported",
        summary="Not supported in scope: 'execution'.",
        table={"type": "none", "rows": []},
        facts={"reason": "execution", "ticker": "NVDA"},
        numbers_used=[],
        suggested_rewrites=["Show ATM call and put for NVDA next week with bid/ask/mid."],
    )
    text = render_response(refused, color=False)
    assert "REFUSED" in text
    assert "[ TRY INSTEAD ]" in text
    assert "Show ATM call and put" in text


def test_chain_table_renders_all_columns() -> None:
    chain = _resp(
        category="chain",
        table={
            "type": "chain_slice",
            "rows": [
                {
                    "option_symbol": "O:NVDA260516C00100000",
                    "expiry": "2026-05-16",
                    "right": "C",
                    "strike": 100.0,
                    "bid": 1.0,
                    "ask": 2.0,
                    "mid": 1.5,
                    "last": 1.5,
                    "ts": "x",
                },
            ],
        },
    )
    text = render_response(chain, color=False)
    assert "OPTION_SYMBOL" in text
    assert "STRIKE" in text
    assert "BID" in text
    assert "O:NVDA260516C00100000" in text


def test_facts_dict_value_is_inlined_as_key_value_pairs() -> None:
    text = render_response(_resp(), color=False)
    # Spot is a dict {value, ts, source}; the renderer flattens it inline.
    assert "value=102.5" in text
    assert "source=polygon" in text


def test_limitations_section_appears_when_warnings_present() -> None:
    text = render_response(_resp(limitations=["STALE_DATA"]), color=False)
    assert "[ LIMITATIONS ]" in text
    assert "STALE_DATA" in text


def test_trace_id_in_footer_when_provided() -> None:
    text = render_response(_resp(), color=False, trace_id="20260505_abcd")
    assert "trace_id: 20260505_abcd" in text


def test_asof_in_status_bar_when_provided() -> None:
    text = render_response(_resp(), color=False, asof="2026-05-05T15:00:00Z")
    assert "AS-OF: 2026-05-05T15:00:00Z" in text


def test_json_mode_is_valid_round_trippable_json() -> None:
    text = render_json(_resp(), asof="2026-05-05T15:00:00Z", trace_id="t1")
    payload = json.loads(text)
    assert payload["category"] == "term_structure"
    assert payload["supported"] is True
    assert payload["asof"] == "2026-05-05T15:00:00Z"
    assert payload["trace_id"] == "t1"
    assert payload["numbers_used"] == [0.42, 0.45, 100.0, 102.5]


def test_no_color_when_no_color_env_var_set(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    # color=None means "auto detect" - with NO_COLOR set this should be False.
    text = render_response(_resp(), color=None)
    assert ESC not in text
