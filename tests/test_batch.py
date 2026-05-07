"""Multi-ticker batch tests.

Uses the synthetic registry so the runs are deterministic. Confirms:
  * answer_many returns one row per ticker, in input order
  * comparison_rows extracts the right fields per category
  * the renderer produces a 'comparison' table with status markers
  * errors / refusals come back as rows with status markers, not crashes
"""

from __future__ import annotations

import io
import json

from voli.agent.batch import answer_many, comparison_rows
from voli.agent.executor import ToolRegistry
from voli.cli import main
from voli.cli_render import render_batch, render_batch_json
from voli.eval.synth_market import make_registry


def test_answer_many_runs_one_per_ticker_in_order() -> None:
    reg = make_registry()
    batch = answer_many(
        "ATM IV this week vs next week",
        ["NVDA", "SPY", "QQQ"],
        registry=reg,
    )
    assert [r.ticker for r in batch.rows] == ["NVDA", "SPY", "QQQ"]
    assert all(r.response is not None for r in batch.rows)


def test_primary_category_is_term_structure_for_iv_prompt() -> None:
    batch = answer_many(
        "ATM IV this week vs next week",
        ["NVDA", "SPY"],
        registry=make_registry(),
    )
    assert batch.primary_category == "term_structure"


def test_comparison_rows_term_structure_fields() -> None:
    batch = answer_many(
        "ATM IV this week vs next week",
        ["NVDA", "SPY"],
        registry=make_registry(),
    )
    rows = comparison_rows(batch)
    for row in rows:
        assert row["status"] == "OK"
        assert row["ticker"] in ("NVDA", "SPY")
        assert row["atm_strike"] is not None
        assert row["front_iv"] is not None
        assert row["next_iv"] is not None
        # Synthetic surface: front=0.30, next=0.35, diff=0.05.
        assert abs(row["diff"] - 0.05) < 1e-6


def test_comparison_rows_skew_fields() -> None:
    batch = answer_many(
        "Show IV skew next Friday",
        ["NVDA", "TSLA"],
        registry=make_registry(),
    )
    assert batch.primary_category == "skew"
    rows = comparison_rows(batch)
    for row in rows:
        assert "skew_slope" in row
        assert "front_expiry" in row


def test_errored_ticker_becomes_row_not_exception() -> None:
    """If one tool call raises, the batch must still return rows for the
    other tickers and a status=ERROR row for the broken one.
    """

    good_reg = make_registry()

    def _maybe_boom(name, fn):
        def _inner(inputs):
            if inputs.get("ticker") == "BROKEN":
                raise RuntimeError("synthetic boom")
            return fn(inputs)

        return _inner

    bad_reg = ToolRegistry(tools={n: _maybe_boom(n, f) for n, f in good_reg.tools.items()})

    batch = answer_many(
        "ATM IV this week vs next week",
        ["NVDA", "BROKEN", "SPY"],
        registry=bad_reg,
    )
    assert [r.ticker for r in batch.rows] == ["NVDA", "BROKEN", "SPY"]
    statuses = {r.ticker: ("ERR" if r.error else "OK") for r in batch.rows}
    assert statuses == {"NVDA": "OK", "BROKEN": "ERR", "SPY": "OK"}


def test_render_batch_text_mode_has_comparison_table() -> None:
    batch = answer_many(
        "ATM IV this week vs next week",
        ["NVDA", "SPY", "QQQ"],
        registry=make_registry(),
    )
    text = render_batch(batch, color=False)
    assert "VOLI BATCH" in text
    assert "TERM STRUCTURE COMPARISON" in text
    assert "NVDA" in text and "SPY" in text and "QQQ" in text
    assert "TICKER" in text


def test_render_batch_json_round_trips() -> None:
    # Use a generic prompt (no ticker baked in) so each ticker_default wins
    # for its row. A prompt that mentions a specific ticker would override.
    batch = answer_many(
        "Show IV skew next Friday",
        ["NVDA", "TSLA"],
        registry=make_registry(),
    )
    payload = json.loads(render_batch_json(batch))
    assert payload["category"] == "skew"
    assert len(payload["rows"]) == 2
    assert {r["ticker"] for r in payload["rows"]} == {"NVDA", "TSLA"}


# ---- CLI integration --------------------------------------------------------


def test_ask_many_text_mode() -> None:
    out = io.StringIO()
    rc = main(
        [
            "ask-many",
            "--no-color",
            "--tickers",
            "NVDA,SPY,QQQ",
            "ATM IV this week vs next week",
        ],
        registry=make_registry(),
        out=out,
    )
    text = out.getvalue()
    assert rc == 0
    assert "TERM STRUCTURE COMPARISON" in text
    for t in ("NVDA", "SPY", "QQQ"):
        assert t in text


def test_ask_many_json_mode() -> None:
    out = io.StringIO()
    rc = main(
        [
            "ask-many",
            "--json",
            "--tickers",
            "NVDA,SPY",
            "ATM IV this week vs next week",
        ],
        registry=make_registry(),
        out=out,
    )
    payload = json.loads(out.getvalue())
    assert rc == 0
    assert payload["category"] == "term_structure"
    tickers = {r["ticker"] for r in payload["rows"]}
    assert tickers == {"NVDA", "SPY"}


def test_ask_many_returns_3_when_any_row_fails() -> None:
    """Same boom-on-BROKEN pattern as the unit test, end-to-end via CLI."""

    good_reg = make_registry()

    def _maybe_boom(name, fn):
        def _inner(inputs):
            if inputs.get("ticker") == "BROKEN":
                raise RuntimeError("synthetic boom")
            return fn(inputs)

        return _inner

    bad_reg = ToolRegistry(tools={n: _maybe_boom(n, f) for n, f in good_reg.tools.items()})

    out = io.StringIO()
    rc = main(
        ["ask-many", "--no-color", "--tickers", "NVDA,BROKEN,SPY", "ATM IV this week vs next week"],
        registry=bad_reg,
        out=out,
    )
    assert rc == 3
    text = out.getvalue()
    assert "BROKEN" in text
    assert "ERROR" in text  # row marker


def test_ask_many_with_skeptic_aggregates_concerns() -> None:
    """Force a skeptic concern by using a stub registry whose underlying
    snapshots have an old timestamp. Confirms the [ SKEPTIC ] block appears.
    """

    from datetime import UTC, datetime, timedelta

    base = make_registry()
    old_ts = datetime.now(UTC) - timedelta(hours=2)

    # Wrap the underlying tool to return a snapshot dated 2h ago.
    real_underlying = base.tools["get_underlying_snapshot"]

    def _stale_underlying(inp):
        resp = real_underlying(inp)
        # Replace the snapshot.ts with a stale one.
        from dataclasses import replace

        return replace(resp, snapshot=replace(resp.snapshot, ts=old_ts))

    stale_reg = ToolRegistry(tools={**base.tools, "get_underlying_snapshot": _stale_underlying})

    out = io.StringIO()
    rc = main(
        [
            "ask-many",
            "--no-color",
            "--skeptic",
            "--tickers",
            "NVDA,SPY",
            "ATM IV this week vs next week",
        ],
        registry=stale_reg,
        out=out,
    )
    text = out.getvalue()
    assert rc == 0
    assert "[ SKEPTIC ]" in text
    assert "STALE_SNAPSHOT" in text
