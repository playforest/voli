# src/voli/cache.py
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JsonLike = None | bool | int | float | str | Sequence["JsonLike"] | Mapping[str, "JsonLike"]

ORDER_INSENSITIVE_FIELDS = {
    "option_symbols",
    "symbols",
    "tickers",
}

# v1 TTL defaults (seconds)
TOOL_TTL_LATEST_SECONDS: dict[str, int] = {
    "get_underlying_snapshot": 30,
    "get_option_quotes": 30,
    "get_option_greeks": 30,
    "list_option_contracts": 6 * 60 * 60,
    # News changes slower than prices; 5 minutes keeps the LLM seeing fresh
    # headlines without re-hitting the vendor on every "what happened today"
    # question.
    "get_ticker_news": 5 * 60,
}

TOOL_TTL_HISTORICAL_SECONDS: dict[str, int] = {
    # When a tool truly supports historical asof (Part 4/5), cache much longer.
    "default": 24 * 60 * 60,
}


def _canonicalize(obj: Any, *, field_name: str | None = None) -> JsonLike:
    """
    Convert Python objects into a JSON-like structure with deterministic ordering.
    - Dict keys are sorted.
    - Certain lists (by field name) are sorted to make keys order-insensitive.
    """
    if obj is None or isinstance(obj, bool | int | float | str):
        return obj

    if isinstance(obj, Mapping):
        # Drop None values for stability (exclude_none semantics).
        items = ((k, v) for k, v in obj.items() if v is not None)
        return {k: _canonicalize(v, field_name=k) for k, v in sorted(items, key=lambda kv: kv[0])}

    if isinstance(obj, list | tuple):
        canon_items = [_canonicalize(v, field_name=field_name) for v in obj]
        if field_name in ORDER_INSENSITIVE_FIELDS:
            # Sort by stable JSON representation
            canon_items.sort(
                key=lambda x: json.dumps(
                    x, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
            )
        return canon_items

    # Fallback: coerce unknown types to string (keeps keying stable without crashing).
    return str(obj)


def canonical_json(tool_inputs: Mapping[str, Any]) -> str:
    canon = _canonicalize(tool_inputs)
    return json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_asof(asof: Any) -> str | None:
    """
    Normalize asof into a stable string.
    v1: accept None, int/float epoch seconds, or ISO-ish strings. Keep strings as-is (stripped).
    I'll tighten this later once i've standardised tool input models.
    """
    if asof is None:
        return None
    if isinstance(asof, int | float):
        # represent as integer milliseconds for stability
        ms = int(round(float(asof) * 1000.0))
        return f"epoch_ms:{ms}"
    s = str(asof).strip()
    return s or None


def make_cache_key(
    tool_name: str, tool_inputs: Mapping[str, Any], asof: Any
) -> tuple[str, str, str]:
    """
    Returns: (cache_key, asof_norm, canon_json)
    cache_key is sha256 of a stable 'raw' string.
    """
    asof_norm = normalize_asof(asof)
    canon = canonical_json(tool_inputs)
    raw = f"v1|tool={tool_name}|asof={asof_norm or 'latest'}|inputs={canon}"
    key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return key, (asof_norm or "latest"), canon


@dataclass(frozen=True)
class CacheRecord:
    key: str
    tool: str
    asof: str
    inputs_json: str
    response_json: str
    created_at: float
    ttl_seconds: int
    expires_at: float


class SQLiteCache:
    """
    Simple on-disk cache for tool results.
    - Deterministic keys via make_cache_key(...)
    - TTL-based freshness
    """

    def __init__(self, path: str | Path, *, now_fn: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now_fn

        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
              key TEXT PRIMARY KEY,
              tool TEXT NOT NULL,
              asof TEXT NOT NULL,
              inputs_json TEXT NOT NULL,
              response_json TEXT NOT NULL,
              created_at REAL NOT NULL,
              ttl_seconds INTEGER NOT NULL,
              expires_at REAL NOT NULL
            );
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_tool_asof ON cache_entries(tool, asof);"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at);"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, key: str) -> CacheRecord | None:
        row = self._conn.execute(
            """
            SELECT key, tool, asof, inputs_json, response_json, created_at, ttl_seconds, expires_at
            FROM cache_entries
            WHERE key = ?
            """,
            (key,),
        ).fetchone()

        if row is None:
            return None

        rec = CacheRecord(*row)
        if self._now() >= rec.expires_at:
            # Expired: delete and treat as miss.
            self._conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
            self._conn.commit()
            return None

        return rec

    def set(
        self,
        *,
        key: str,
        tool: str,
        asof: str,
        inputs_json: str,
        response_json: str,
        ttl_seconds: int,
    ) -> CacheRecord:
        created_at = float(self._now())
        expires_at = created_at + int(ttl_seconds)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO cache_entries
              (key, tool, asof, inputs_json, response_json, created_at, ttl_seconds, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                tool,
                asof,
                inputs_json,
                response_json,
                created_at,
                int(ttl_seconds),
                float(expires_at),
            ),
        )
        self._conn.commit()
        return CacheRecord(
            key,
            tool,
            asof,
            inputs_json,
            response_json,
            created_at,
            int(ttl_seconds),
            float(expires_at),
        )


def default_cache_path() -> Path:
    # v1: env override + sane local default
    env = os.getenv("VOLI_CACHE_PATH")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".voli" / "cache.sqlite"


def ttl_for(tool_name: str, *, asof_is_latest: bool) -> int:
    if asof_is_latest:
        return TOOL_TTL_LATEST_SECONDS.get(tool_name, 60)
    return TOOL_TTL_HISTORICAL_SECONDS.get(tool_name, TOOL_TTL_HISTORICAL_SECONDS["default"])
