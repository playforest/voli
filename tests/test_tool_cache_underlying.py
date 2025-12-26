# tests/test_tool_cache_underlying.py
from __future__ import annotations

import pytest

from oqe.tool_schemas import GetUnderlyingSnapshotInput
from oqe.tools import polygon_tools as pt


def test_get_underlying_snapshot_cache_hit_second_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cache_path = tmp_path / "cache.sqlite"
    monkeypatch.setenv("OQE_CACHE_PATH", str(cache_path))
    pt._get_cache.cache_clear()

    calls: list[tuple[str, object]] = []

    class FakePolygonClient:
        def list_option_chain_snapshot(self, ticker: str, query) -> tuple[dict, list[dict]]:
            calls.append((ticker, query))
            row = {
                "underlying_asset": {
                    "price": 123.45,
                    "last_updated": 1700000000000000000,
                    "timeframe": "REAL-TIME",
                }
            }
            return {}, [row]

        def close(self) -> None:
            return None

    monkeypatch.setattr(pt, "PolygonClient", FakePolygonClient)

    inp = GetUnderlyingSnapshotInput(ticker="NVDA", asof=None)

    out1 = pt.get_underlying_snapshot(inp)
    print(f"[call1] primary_source={out1.meta.primary_source} spot={out1.snapshot.spot}")
    assert len(calls) == 1
    assert out1.meta.primary_source == "polygon"

    out2 = pt.get_underlying_snapshot(inp)
    print(f"[call2] primary_source={out2.meta.primary_source} spot={out2.snapshot.spot}")
    assert len(calls) == 1
    assert out2.meta.primary_source == "cache"

    pt._get_cache().close()
    pt._get_cache.cache_clear()
