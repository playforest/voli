# tests/test_cache.py
from __future__ import annotations

import json
from pathlib import Path

from voli.cache import SQLiteCache, make_cache_key


def test_cache_key_order_insensitive_option_symbols(tmp_path: Path) -> None:
    inputs_a = {"option_symbols": ["O:NVDA251219C00100000", "O:NVDA251219P00100000"], "foo": 1}
    inputs_b = {"foo": 1, "option_symbols": ["O:NVDA251219P00100000", "O:NVDA251219C00100000"]}

    key_a, asof_a, canon_a = make_cache_key("get_option_quotes", inputs_a, asof=None)
    key_b, asof_b, canon_b = make_cache_key("get_option_quotes", inputs_b, asof=None)

    assert asof_a == asof_b == "latest"
    assert key_a == key_b
    assert json.loads(canon_a) == json.loads(canon_b)


def test_ttl_expiry_deletes_entry(tmp_path: Path) -> None:
    t = {"now": 1000.0}

    def now_fn() -> float:
        return t["now"]

    cache = SQLiteCache(tmp_path / "cache.sqlite", now_fn=now_fn)

    key, asof, canon = make_cache_key("get_underlying_snapshot", {"ticker": "NVDA"}, asof=None)
    cache.set(
        key=key,
        tool="get_underlying_snapshot",
        asof=asof,
        inputs_json=canon,
        response_json='{"ok":true}',
        ttl_seconds=10,
    )

    assert cache.get(key) is not None

    t["now"] = 1011.0  # advance past expiry
    assert cache.get(key) is None

    cache.close()
