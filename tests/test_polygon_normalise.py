from __future__ import annotations

from datetime import UTC, date

from oqe.polygon.normalise import (
    option_contract_from_snapshot_row,
    option_greeks_from_snapshot_row,
    option_quote_from_snapshot_row,
)

# To refresh SAMPLE_ROW from live Polygon (manual, NOT for CI):
# export POLYGON_API_KEY=...
# poetry run python - <<'PY'
# import json
# from oqe.polygon.client import PolygonClient, OptionChainQuery
# pc = PolygonClient()
# first, rows = pc.list_option_chain_snapshot("AAPL", OptionChainQuery(limit=1, max_pages=1))
# print(json.dumps(rows[0], indent=2)[:4000])
# pc.close()
# PY

SAMPLE_ROW = {
    "details": {
        "contract_type": "call",
        "exercise_style": "american",
        "expiration_date": "2025-12-26",
        "shares_per_contract": 100,
        "strike_price": 110,
        "ticker": "O:AAPL251226C00110000",
    },
    "underlying_asset": {
        "change_to_break_even": 0.32,
        "last_updated": 1766613596694930291,
        "price": 273.43,
        "ticker": "AAPL",
        "timeframe": "DELAYED",
    },
    "last_trade": {
        "sip_timestamp": 1766591058341623991,
        "conditions": [232],
        "price": 164.17,
        "size": 1,
        "exchange": 308,
        "timeframe": "DELAYED",
    },
    "greeks": {
        "delta": 0.9929165938342104,
        "gamma": 0.000174290885023519,
        "theta": -0.6259316952302361,
        "vega": 0.006138491199611934,
    },
    "implied_volatility": 5.873483212710058,
    "open_interest": 1,
}


def test_option_contract_from_snapshot_row():
    c = option_contract_from_snapshot_row(SAMPLE_ROW, fallback_underlying="AAPL")
    assert c.option_symbol == "O:AAPL251226C00110000"
    assert c.underlying == "AAPL"
    assert c.expiry == date(2025, 12, 26)
    assert c.strike == 110.0
    assert c.right == "C"
    assert c.multiplier == 100
    assert c.currency == "USD"
    assert c.exercise_style == "american"


def test_option_quote_from_snapshot_row_trade_only():
    q = option_quote_from_snapshot_row(SAMPLE_ROW)
    assert q.option_symbol == "O:AAPL251226C00110000"
    assert q.bid is None
    assert q.ask is None
    assert q.mid is None
    assert q.last == 164.17
    assert q.source == "polygon"
    assert q.ts.tzinfo is not None
    assert q.ts.astimezone(UTC).tzinfo == UTC


def test_option_greeks_from_snapshot_row():
    g = option_greeks_from_snapshot_row(SAMPLE_ROW)
    assert g.option_symbol == "O:AAPL251226C00110000"
    assert g.delta is not None and -1 <= g.delta <= 1
    assert g.gamma is not None and g.gamma >= 0
    assert g.vega is not None and g.vega >= 0
    assert g.iv == SAMPLE_ROW["implied_volatility"]
    assert g.source == "polygon"
    assert g.model == "vendor"
    assert g.ts.tzinfo is not None
    assert g.ts.astimezone(UTC).tzinfo == UTC


def test_option_greeks_clamps_tiny_negative_noise_to_zero():
    """Polygon occasionally returns ~-3e-10 for gamma/vega; the model has
    `ge=0` so without clamping this raises ValidationError. The normaliser
    must floor near-zero noise.
    """

    row = {
        **SAMPLE_ROW,
        "greeks": {
            "delta": 0.5,
            "gamma": -3.1526505506027033e-10,
            "theta": -0.1,
            "vega": -7.4e-11,
        },
    }
    g = option_greeks_from_snapshot_row(row)
    assert g.gamma == 0.0
    assert g.vega == 0.0


def test_option_greeks_real_negative_still_propagates():
    """A genuine negative (outside the noise window) must NOT be silently
    clamped - it would mask a real upstream bug. Pydantic's ge=0 raises.
    """

    import pytest
    from pydantic import ValidationError

    row = {**SAMPLE_ROW, "greeks": {"gamma": -0.5}}
    with pytest.raises(ValidationError):
        option_greeks_from_snapshot_row(row)


def test_option_greeks_clamps_observed_polygon_vega_noise():
    """Regression: Polygon emitted vega -8.007e-05 against live NVDA data,
    which is much larger than the gamma noise but still below 1e-3.
    """

    row = {**SAMPLE_ROW, "greeks": {"vega": -8.007028049680383e-05}}
    g = option_greeks_from_snapshot_row(row)
    assert g.vega == 0.0
