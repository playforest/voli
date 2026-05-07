"""LLM-mode replay companion.

When `voli llm-ask --trace` is set we drop a JSON file alongside the
existing JSONL flight recorder so `voli replay` can re-render the LLM
answer offline (no API call, no Polygon traffic).

Companion shape (separate from `<id>.response.json` used by the rule-
based path) so the replay command can dispatch by file existence:

    ~/.voli/traces/<trace_id>.llm.json

We intentionally don't reuse `AnswerResponse.dump_response()` - LLM
answers don't fit cleanly into AnswerResponse.category, and storing the
raw event log lets us preserve the [ TOOL CALL ] / [ TOOL OK ] /
[ ANSWER ] structure on replay.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from voli.run_trace import default_trace_dir

from .types import ToolCallStart, ToolResult


@dataclass(frozen=True)
class LLMRunRecord:
    trace_id: str
    prompt: str
    provider: str
    model: str
    answer: str
    stop_reason: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    skeptic: list[str] | None = None


def companion_path(trace_id: str, *, trace_dir: Path | None = None) -> Path:
    base = trace_dir or default_trace_dir()
    return base / f"{trace_id}.llm.json"


def dump_llm_run(
    trace_id: str,
    *,
    prompt: str,
    provider: str,
    model: str,
    answer: str,
    stop_reason: str,
    tool_calls: list[ToolCallStart],
    tool_results: list[ToolResult],
    skeptic: list[str] | None = None,
    trace_dir: Path | None = None,
) -> Path:
    record = LLMRunRecord(
        trace_id=trace_id,
        prompt=prompt,
        provider=provider,
        model=model,
        answer=answer,
        stop_reason=stop_reason,
        tool_calls=[{"id": c.id, "name": c.name, "arguments": c.arguments} for c in tool_calls],
        tool_results=[
            {"id": r.id, "name": r.name, "content": r.content, "is_error": r.is_error}
            for r in tool_results
        ],
        skeptic=skeptic,
    )
    path = companion_path(trace_id, trace_dir=trace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(record), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return path


def _resolve_path(target: str, *, trace_dir: Path | None = None) -> Path:
    p = Path(target)
    if p.is_file():
        return p
    base = trace_dir or default_trace_dir()
    for candidate in (
        base / target,
        base / f"{target}.llm.json",
        Path(target),
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"No LLM replay companion found for {target!r}. Looked in {base} and as a literal path."
    )


def load_llm_run(target: str, *, trace_dir: Path | None = None) -> LLMRunRecord:
    path = _resolve_path(target, trace_dir=trace_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return LLMRunRecord(
        trace_id=raw["trace_id"],
        prompt=raw["prompt"],
        provider=raw["provider"],
        model=raw["model"],
        answer=raw["answer"],
        stop_reason=raw["stop_reason"],
        tool_calls=list(raw.get("tool_calls") or []),
        tool_results=list(raw.get("tool_results") or []),
        skeptic=raw.get("skeptic"),
    )
