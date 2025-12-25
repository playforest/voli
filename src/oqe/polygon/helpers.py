from __future__ import annotations

from datetime import UTC, datetime


def ns_to_utc_iso(ns: int | None) -> str | None:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=UTC).isoformat()
