from __future__ import annotations

import pytest

from oqe.tool_schemas import GetOptionQuotesInput
from oqe.tools import polygon_tools as pt


def test_get_option_quotes_cache_hit_second_call(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cache_path = tmp_path / "cache.sqlite"
    monkeypatch.setenv("OQE_CACHE_PATH", str(cache_path))
    pt._get_cache.cache_clear()

    calls: list[tuple[str, str]] = []

    class FakePolygonClient:
        def get_option_contract_snapshot(self, underlying: str, sym: str) -> dict:
            calls.append((underlying, sym))
            ts_ns = 1700000000000000000  # nanoseconds
            return {
                "results": {
                    "details": {"ticker": sym},
                    "last_quote": {
                        "bid": 1.0,
                        "ask": 1.1,
                        "sip_timestamp": ts_ns,
                        "participant_timestamp": ts_ns,
                    },
                    "last_trade": {
                        "price": 1.05,
                        "sip_timestamp": ts_ns,
                    },
                    "last_updated": ts_ns,
                }
            }

        def close(self) -> None:
            return None

    monkeypatch.setattr(pt, "PolygonClient", FakePolygonClient)

    # include a duplicate symbol to prove we don't double-call vendor
    s1 = "O:NVDA251219C00100000"
    s2 = "O:NVDA251219P00100000"
    inp = GetOptionQuotesInput(option_symbols=[s1, s2, s1], asof=None)

    out1 = pt.get_option_quotes(inp)
    print(f"[call1] primary_source={out1.meta.primary_source} vendor_calls={len(calls)}")
    assert out1.meta.primary_source == "polygon"
    assert len(calls) == 2  # deduped vendor calls
    assert len(out1.quotes) == 3  # output preserves input multiplicity/order

    out2 = pt.get_option_quotes(inp)
    print(f"[call2] primary_source={out2.meta.primary_source} vendor_calls={len(calls)}")
    assert out2.meta.primary_source == "cache"
    assert len(calls) == 2  # no new vendor calls
    assert len(out2.quotes) == 3

    pt._get_cache().close()
    pt._get_cache.cache_clear()
