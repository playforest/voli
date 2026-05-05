"""End-to-end CLI tests.

We invoke `oqe.cli.main` directly with a stubbed ToolRegistry so the test
never touches Polygon. Output is captured via pytest's capsys.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from oqe.agent.executor import ToolRegistry
from oqe.cli import main

# ---- minimal stub market (one ticker, two expiries, three strikes) ---------


@dataclass(frozen=True)
class _Snap:
    ticker: str
    spot: float
    ts: datetime
    source: str = "polygon"


@dataclass(frozen=True)
class _Resp:
    snapshot: _Snap | None = None
    contracts: list = field(default_factory=list)
    quotes: list = field(default_factory=list)
    greeks: list = field(default_factory=list)
    meta: Any = None


@dataclass(frozen=True)
class _Contract:
    option_symbol: str
    expiry: date
    strike: float
    right: str


@dataclass(frozen=True)
class _Quote:
    option_symbol: str
    bid: float | None
    ask: float | None
    mid: float | None
    last: float | None
    ts: datetime
    source: str = "polygon"


@dataclass(frozen=True)
class _Greeks:
    option_symbol: str
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    ts: datetime
    source: str = "polygon"


def _make_stub_registry() -> ToolRegistry:
    now = datetime.now(UTC)
    spot = 100.0
    expiries = [date(2026, 5, 9), date(2026, 5, 16)]
    strikes = [95.0, 100.0, 105.0]

    contracts: list[_Contract] = []
    quotes: dict[str, _Quote] = {}
    greeks: dict[str, _Greeks] = {}
    for exp in expiries:
        for k in strikes:
            for right in ("C", "P"):
                sym = f"O:NVDA{exp.strftime('%y%m%d')}{right}{int(k * 1000):08d}"
                contracts.append(_Contract(sym, exp, k, right))
                quotes[sym] = _Quote(sym, 1.0, 2.0, 1.5, 1.5, now)
                base_iv = 0.30 + (0.05 if exp == expiries[1] else 0.0) + 0.002 * abs(k - spot)
                greeks[sym] = _Greeks(
                    sym, base_iv, 0.5 if right == "C" else -0.5, 0.02, -0.10, 0.12, now
                )

    snap = _Snap("NVDA", spot, now)

    def _underlying(inp):
        return _Resp(snapshot=snap)

    def _list(inp):
        out = list(contracts)
        if "right" in inp:
            out = [c for c in out if c.right == inp["right"]]
        if "expiry" in inp:
            target = (
                date.fromisoformat(inp["expiry"])
                if isinstance(inp["expiry"], str)
                else inp["expiry"]
            )
            out = [c for c in out if c.expiry == target]
        return _Resp(contracts=out)

    def _quotes(inp):
        return _Resp(quotes=[quotes[s] for s in inp["option_symbols"] if s in quotes])

    def _greeks(inp):
        return _Resp(greeks=[greeks[s] for s in inp["option_symbols"] if s in greeks])

    return ToolRegistry(
        tools={
            "get_underlying_snapshot": _underlying,
            "list_option_contracts": _list,
            "get_option_quotes": _quotes,
            "get_option_greeks": _greeks,
        }
    )


# ---- tests -----------------------------------------------------------------


def test_ask_text_mode_renders_bloomberg_layout() -> None:
    out = io.StringIO()
    rc = main(
        ["ask", "--no-color", "NVDA ATM IV this week vs next week."],
        registry=_make_stub_registry(),
        out=out,
    )
    text = out.getvalue()
    assert rc == 0
    # Bloomberg-style sections present.
    assert "OQE" in text
    assert "CATEGORY: TERM_STRUCTURE" in text
    assert "[ SUMMARY ]" in text
    assert "[ TERM STRUCTURE ]" in text
    assert "[ FACTS ]" in text
    # Facts include NVDA ticker.
    assert "NVDA" in text


def test_ask_json_mode_emits_valid_json() -> None:
    out = io.StringIO()
    rc = main(
        ["ask", "--json", "NVDA ATM IV this week vs next week."],
        registry=_make_stub_registry(),
        out=out,
    )
    payload = json.loads(out.getvalue())
    assert rc == 0
    assert payload["supported"] is True
    assert payload["category"] == "term_structure"
    assert "summary" in payload
    assert "table" in payload
    assert "facts" in payload


def test_ask_refusal_returns_exit_code_3() -> None:
    out = io.StringIO()
    rc = main(
        ["ask", "--no-color", "Should I buy NVDA calls?"],
        registry=_make_stub_registry(),
        out=out,
    )
    text = out.getvalue()
    assert rc == 3
    assert "REFUSED" in text
    assert "[ TRY INSTEAD ]" in text


def test_ask_ticker_default_used_when_prompt_lacks_ticker() -> None:
    out = io.StringIO()
    rc = main(
        ["ask", "--no-color", "--ticker", "NVDA", "Show options expiring this Friday."],
        registry=_make_stub_registry(),
        out=out,
    )
    text = out.getvalue()
    assert rc == 0
    assert "TICKER: NVDA" in text


def test_ask_asof_appears_in_status_bar() -> None:
    out = io.StringIO()
    rc = main(
        [
            "ask",
            "--no-color",
            "--asof",
            "2026-05-05T15:00:00Z",
            "NVDA ATM IV this week vs next week.",
        ],
        registry=_make_stub_registry(),
        out=out,
    )
    text = out.getvalue()
    assert rc == 0
    assert "AS-OF: 2026-05-05T15:00:00Z" in text


def test_ask_renders_upstream_error_in_bloomberg_layout() -> None:
    """If a tool raises (e.g. missing API key), the CLI shows a styled error
    rather than a Python traceback, and exits 4.
    """

    def _boom(_inp):
        raise RuntimeError("Missing POLYGON_API_KEY env var.")

    bad = ToolRegistry(
        tools={
            "get_underlying_snapshot": _boom,
            "list_option_contracts": _boom,
            "get_option_quotes": _boom,
            "get_option_greeks": _boom,
        }
    )
    out = io.StringIO()
    rc = main(
        ["ask", "--no-color", "NVDA ATM IV this week vs next week."],
        registry=bad,
        out=out,
    )
    text = out.getvalue()
    assert rc == 4
    assert "OQE | ERROR: RuntimeError" in text
    assert "Missing POLYGON_API_KEY" in text


def test_ask_json_mode_includes_asof_and_trace_id_keys() -> None:
    out = io.StringIO()
    rc = main(
        ["ask", "--json", "--asof", "2026-05-05T15:00:00Z", "NVDA ATM IV this week vs next week."],
        registry=_make_stub_registry(),
        out=out,
    )
    payload = json.loads(out.getvalue())
    assert rc == 0
    assert payload["asof"] == "2026-05-05T15:00:00Z"
    assert "trace_id" in payload  # present (None when --trace not passed)
