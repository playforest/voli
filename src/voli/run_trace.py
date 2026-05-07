# src/voli/run_trace.py
from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_trace_id() -> str:
    # Example: 20251227T001122Z_a1b2c3d4
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rand = secrets.token_hex(4)
    return f"{ts}_{rand}"


def default_trace_dir() -> Path:
    env = os.getenv("VOLI_TRACE_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".voli" / "traces"


def trace_path(trace_id: str) -> Path:
    return default_trace_dir() / f"{trace_id}.jsonl"


@dataclass(frozen=True)
class TraceLogger:
    trace_id: str

    @property
    def path(self) -> Path:
        return trace_path(self.trace_id)

    def log(self, event: Mapping[str, Any]) -> None:
        """
        Append a single JSON object as one line (JSONL).
        """
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)

        payload = dict(event)
        payload.setdefault("trace_id", self.trace_id)
        payload.setdefault("created_at", _utc_now_iso())

        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            f.write("\n")


# Simple singleton for "current run" (v1: process-local)
_CURRENT: TraceLogger | None = None


def start_trace(trace_id: str | None = None) -> TraceLogger:
    global _CURRENT
    _CURRENT = TraceLogger(trace_id or new_trace_id())
    _CURRENT.log({"event": "trace_start"})
    return _CURRENT


def get_trace() -> TraceLogger | None:
    return _CURRENT


def end_trace() -> None:
    global _CURRENT
    if _CURRENT is not None:
        _CURRENT.log({"event": "trace_end"})
    _CURRENT = None
