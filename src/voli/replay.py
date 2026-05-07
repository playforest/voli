"""Replay support: dump a final AnswerResponse alongside its run-trace,
then re-render it later.

Why a separate companion file rather than appending to the JSONL trace?
The JSONL trace is a *flight recorder* of tool calls (cache keys, vendor
warnings, asof). Replay needs the *finished answer* - one structured
JSON object - so the renderer can recreate the CLI output without
re-running tool dispatch. Storing them side by side keeps both formats
clean.

File layout:
  ~/.voli/traces/<trace_id>.jsonl          # tool-call JSONL (existing)
  ~/.voli/traces/<trace_id>.response.json  # this module writes/reads
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .agent.state import AnswerResponse
from .run_trace import default_trace_dir


def companion_path(trace_id: str, *, trace_dir: Path | None = None) -> Path:
    base = trace_dir or default_trace_dir()
    return base / f"{trace_id}.response.json"


def _serialise_response(resp: AnswerResponse) -> dict[str, Any]:
    if is_dataclass(resp):
        return asdict(resp)
    # Fallback shouldn't trigger - AnswerResponse is a dataclass - but keeps
    # the contract explicit.
    return {  # pragma: no cover
        k: getattr(resp, k)
        for k in (
            "supported",
            "category",
            "summary",
            "table",
            "facts",
            "numbers_used",
            "limitations",
            "suggested_rewrites",
            "skeptic",
        )
    }


def dump_response(
    trace_id: str,
    response: AnswerResponse,
    *,
    prompt: str,
    asof: str | None = None,
    theme: str | None = None,
    ticker_default: str | None = None,
    skeptic: bool = False,
    trace_dir: Path | None = None,
) -> Path:
    """Write the companion JSON. Returns the path written."""

    payload = {
        "trace_id": trace_id,
        "prompt": prompt,
        "ticker_default": ticker_default,
        "asof": asof,
        "theme": theme,
        "skeptic": skeptic,
        "response": _serialise_response(response),
    }
    path = companion_path(trace_id, trace_dir=trace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return path


def _resolve_path(target: str, *, trace_dir: Path | None = None) -> Path:
    """Accept either a trace_id or a full path."""

    p = Path(target)
    if p.is_file():
        return p
    # Try trace_id forms: <id> or <id>.response.json under the trace dir.
    base = trace_dir or default_trace_dir()
    for candidate in (
        base / target,
        base / f"{target}.response.json",
        Path(target),
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"No replay companion found for {target!r}. Looked in {base} and as a literal path."
    )


def load_replay(target: str, *, trace_dir: Path | None = None) -> dict[str, Any]:
    """Return the parsed companion JSON. Re-build the AnswerResponse via
    `replay_to_response()` if you need a typed object."""

    path = _resolve_path(target, trace_dir=trace_dir)
    return json.loads(path.read_text(encoding="utf-8"))


def replay_to_response(target: str, *, trace_dir: Path | None = None) -> AnswerResponse:
    payload = load_replay(target, trace_dir=trace_dir)
    r = payload.get("response") or {}
    # AnswerResponse is a frozen dataclass; constructor takes the same keys
    # asdict() produced.
    return AnswerResponse(
        supported=r["supported"],
        category=r["category"],
        summary=r["summary"],
        table=r["table"],
        facts=r["facts"],
        numbers_used=list(r.get("numbers_used") or []),
        limitations=list(r.get("limitations") or []),
        suggested_rewrites=list(r.get("suggested_rewrites") or []),
        skeptic=r.get("skeptic"),
    )
