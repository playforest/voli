from __future__ import annotations

import pytest

from voli.tool_schemas import GetOptionGreeksInput
from voli.tools import polygon_tools as pt


def test_get_option_greeks_cache_hit_second_call(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cache_path = tmp_path / "cache.sqlite"
    monkeypatch.setenv("VOLI_CACHE_PATH", str(cache_path))
    pt._get_cache.cache_clear()

    calls: list[tuple[str, str]] = []

    class FakePolygonClient:
        def get_option_contract_snapshot(self, underlying: str, sym: str) -> dict:
            calls.append((underlying, sym))
            ts_ns = 1700000000000000000  # nanoseconds
            return {
                "results": {
                    "details": {"ticker": sym},
                    # include multiple timestamp locations so your normalizer finds one
                    "last_updated": ts_ns,
                    "last_quote": {
                        "bid": 1.0,
                        "ask": 1.1,
                        "sip_timestamp": ts_ns,
                        "participant_timestamp": ts_ns,
                    },
                    # greeks payload (common Polygon shape)
                    "greeks": {"delta": 0.5, "gamma": 0.1, "theta": -0.02, "vega": 0.3},
                    "implied_volatility": 0.4,
                }
            }

        def close(self) -> None:
            return None

    monkeypatch.setattr("voli.providers.polygon.PolygonClient", FakePolygonClient)

    s1 = "O:NVDA251219C00100000"
    s2 = "O:NVDA251219P00100000"

    # include duplicate symbol to prove per-request dedupe of HTTP calls
    inp1 = GetOptionGreeksInput(option_symbols=[s1, s2, s1], asof=None, mode="vendor_only")

    out1 = pt.get_option_greeks(inp1)
    print(f"[call1] primary_source={out1.meta.primary_source} vendor_calls={len(calls)}")
    assert out1.meta.primary_source == "polygon"
    assert len(calls) == 2  # deduped vendor calls
    assert len(out1.greeks) == 3  # preserves input multiplicity/order

    # reorder on second call: should be cache hit + output order matches request order
    inp2 = GetOptionGreeksInput(option_symbols=[s2, s1, s1], asof=None, mode="vendor_only")
    out2 = pt.get_option_greeks(inp2)
    print(f"[call2] primary_source={out2.meta.primary_source} vendor_calls={len(calls)}")
    assert out2.meta.primary_source == "cache"
    assert len(calls) == 2  # no new vendor calls
    assert [g.option_symbol for g in out2.greeks] == [s2, s1, s1]

    # close sqlite to avoid file-lock issues
    pt._get_cache().close()
    pt._get_cache.cache_clear()
