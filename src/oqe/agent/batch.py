"""Multi-ticker batch.

`answer_many(prompt, tickers)` runs the same prompt against each ticker
sequentially (each call uses the existing `answer_question` pipeline) and
returns a list of `BatchRow`. The CLI's `ask-many` subcommand wraps this
and renders a single comparison table.

Why sequential rather than threaded? Three reasons:

  * Polygon rate-limits hard on free tiers; sequential keeps us under the
    limit without bookkeeping.
  * The on-disk SQLite cache de-dupes repeat work across tickers without
    needing locks.
  * Determinism: parametrized eval cases see the same row order every run.

If/when we add a high-tier Polygon key path, we can introduce an opt-in
threaded variant - all the per-ticker work is already isolated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from . import answer_question
from .executor import ToolRegistry
from .state import AnswerResponse


@dataclass(frozen=True)
class BatchRow:
    """One ticker's result. `error` is set when answer_question raised, in
    which case `response` is None.
    """

    ticker: str
    response: AnswerResponse | None
    error: str | None = None


@dataclass(frozen=True)
class BatchResult:
    prompt: str
    rows: tuple[BatchRow, ...]

    @property
    def categories(self) -> set[str]:
        return {r.response.category for r in self.rows if r.response is not None}

    @property
    def primary_category(self) -> str | None:
        """Pick the category most rows share - the comparison table renders
        per-category columns, so a homogeneous batch is the common case.
        """

        cats = [r.response.category for r in self.rows if r.response is not None]
        if not cats:
            return None
        # Most-common; tie-break by first-occurrence order for determinism.
        counts: dict[str, int] = {}
        for c in cats:
            counts[c] = counts.get(c, 0) + 1
        return max(counts, key=lambda k: (counts[k], -cats.index(k)))


def answer_many(
    prompt: str,
    tickers: Sequence[str],
    *,
    registry: ToolRegistry | None = None,
    skeptic: bool = False,
) -> BatchResult:
    """Run `answer_question` against each ticker and collect the results."""

    rows: list[BatchRow] = []
    for t in tickers:
        try:
            resp = answer_question(
                prompt,
                ticker_default=t,
                registry=registry,
                skeptic=skeptic,
            )
            rows.append(BatchRow(ticker=t, response=resp))
        except Exception as exc:  # noqa: BLE001 - surface as a row, not a crash
            rows.append(BatchRow(ticker=t, response=None, error=f"{type(exc).__name__}: {exc}"))
    return BatchResult(prompt=prompt, rows=tuple(rows))


# --- per-category row extractors -------------------------------------------
#
# Each extractor pulls the comparable fields out of a per-ticker response.
# The renderer in cli_render reads these via `comparison_rows()`.


def _row_term_structure(resp: AnswerResponse) -> dict[str, Any]:
    facts = resp.facts or {}
    front = facts.get("front_iv")
    nxt = facts.get("next_iv")
    diff = None
    if front is not None and nxt is not None:
        diff = round(float(nxt) - float(front), 4)
    return {
        "ticker": facts.get("ticker"),
        "atm_strike": facts.get("atm_strike"),
        "front_iv": front,
        "next_iv": nxt,
        "diff": diff,
    }


def _row_skew(resp: AnswerResponse) -> dict[str, Any]:
    facts = resp.facts or {}
    return {
        "ticker": facts.get("ticker"),
        "front_expiry": facts.get("front_expiry"),
        "atm_strike": facts.get("atm_strike"),
        "skew_slope": facts.get("skew_slope"),
    }


def _row_greeks(resp: AnswerResponse) -> dict[str, Any]:
    facts = resp.facts or {}
    atm = facts.get("atm_contract") or {}
    return {
        "ticker": facts.get("ticker"),
        "strike": atm.get("strike"),
        "iv": atm.get("iv"),
        "delta": atm.get("delta"),
        "gamma": atm.get("gamma"),
        "theta": atm.get("theta"),
        "vega": atm.get("vega"),
    }


def _row_chain(resp: AnswerResponse) -> dict[str, Any]:
    facts = resp.facts or {}
    spot = facts.get("spot")
    spot_value = spot.get("value") if isinstance(spot, dict) else None
    return {
        "ticker": facts.get("ticker"),
        "spot": spot_value,
        "contracts_count": facts.get("contracts_count"),
        "expiries_used": ", ".join(facts.get("expiries_used") or []),
    }


_EXTRACTORS = {
    "term_structure": _row_term_structure,
    "skew": _row_skew,
    "greeks": _row_greeks,
    "chain": _row_chain,
}


def comparison_rows(batch: BatchResult) -> list[dict[str, Any]]:
    """Build the row list for the `comparison` table type.

    Rows from refused / errored tickers come back with `status` set so the
    renderer can show a placeholder rather than dropping the row.
    """

    cat = batch.primary_category or "term_structure"
    extractor = _EXTRACTORS.get(cat, _row_term_structure)

    out: list[dict[str, Any]] = []
    for row in batch.rows:
        if row.error is not None:
            out.append({"ticker": row.ticker, "status": "ERROR", "detail": row.error})
            continue
        if row.response is None or not row.response.supported:
            reason = (row.response.facts or {}).get("reason") if row.response else "no_response"
            out.append({"ticker": row.ticker, "status": "REFUSED", "detail": reason})
            continue
        rec = extractor(row.response)
        rec["status"] = "OK"
        out.append(rec)
    return out
