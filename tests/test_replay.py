"""Replay tests.

`voli ask --trace` writes a `<trace_id>.response.json` companion alongside
the JSONL trace. `voli replay <trace_id>` reads it back and re-renders.

We override `VOLI_TRACE_DIR` per test via tmp_path so traces don't leak
between runs.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from voli.agent import answer_question
from voli.cli import main
from voli.eval.synth_market import make_registry
from voli.replay import (
    companion_path,
    dump_response,
    load_replay,
    replay_to_response,
)


@pytest.fixture()
def trace_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VOLI_TRACE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def registry():
    return make_registry()


# ---- dump_response / replay_to_response --------------------------------------


def test_dump_then_load_round_trips(trace_dir: Path, registry) -> None:
    resp = answer_question(
        "ATM IV this week vs next week",
        ticker_default="NVDA",
        registry=registry,
    )
    path = dump_response(
        "tc_001",
        resp,
        prompt="ATM IV this week vs next week",
        ticker_default="NVDA",
    )
    assert path == companion_path("tc_001")
    assert path.exists()

    payload = load_replay("tc_001")
    assert payload["trace_id"] == "tc_001"
    assert payload["prompt"] == "ATM IV this week vs next week"
    assert payload["response"]["category"] == resp.category


def test_replay_to_response_rebuilds_typed_object(trace_dir: Path, registry) -> None:
    resp = answer_question(
        "ATM IV this week vs next week",
        ticker_default="SPY",
        registry=registry,
    )
    dump_response("tc_002", resp, prompt="ATM IV this week vs next week", ticker_default="SPY")

    rebuilt = replay_to_response("tc_002")
    assert rebuilt.supported == resp.supported
    assert rebuilt.category == resp.category
    assert rebuilt.summary == resp.summary
    assert rebuilt.facts["ticker"] == "SPY"


def test_replay_resolves_id_or_full_path(trace_dir: Path, registry) -> None:
    resp = answer_question(
        "ATM IV this week vs next week",
        ticker_default="NVDA",
        registry=registry,
    )
    dump_response("tc_003", resp, prompt="x", ticker_default="NVDA")

    # By id:
    by_id = replay_to_response("tc_003")
    # By full path:
    by_path = replay_to_response(str(companion_path("tc_003")))

    assert by_id.summary == by_path.summary


def test_replay_missing_target_raises(trace_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        replay_to_response("does_not_exist")


# ---- CLI: ask --trace writes companion --------------------------------------


def test_ask_trace_writes_replay_companion(trace_dir: Path, registry) -> None:
    out = io.StringIO()
    rc = main(
        [
            "ask",
            "--no-color",
            "--trace",
            "--ticker",
            "NVDA",
            "ATM IV this week vs next week",
        ],
        registry=registry,
        out=out,
    )
    assert rc == 0
    text = out.getvalue()

    # Companion path should be mentioned in the output.
    assert "replay companion:" in text

    # The trace dir should now contain exactly one .response.json file.
    matches = list(trace_dir.glob("*.response.json"))
    assert len(matches) == 1
    payload = json.loads(matches[0].read_text())
    assert payload["prompt"] == "ATM IV this week vs next week"
    assert payload["ticker_default"] == "NVDA"


# ---- CLI: voli replay --------------------------------------------------------


def test_voli_replay_renders_companion(trace_dir: Path, registry) -> None:
    # First produce a companion by tracing an answer.
    out = io.StringIO()
    main(
        ["ask", "--no-color", "--trace", "--ticker", "NVDA", "ATM IV this week vs next week"],
        registry=registry,
        out=out,
    )
    matches = list(trace_dir.glob("*.response.json"))
    trace_id = matches[0].name.replace(".response.json", "")

    # Now replay it (via id, no registry needed).
    out2 = io.StringIO()
    rc = main(["replay", "--no-color", trace_id], out=out2)
    assert rc == 0
    replayed = out2.getvalue()
    # The replay should contain the same Facts as the original.
    assert "[ FACTS ]" in replayed
    assert "NVDA" in replayed


def test_voli_replay_supports_theme_override(trace_dir: Path, registry) -> None:
    out = io.StringIO()
    main(
        ["ask", "--no-color", "--trace", "--ticker", "NVDA", "ATM IV this week vs next week"],
        registry=registry,
        out=out,
    )
    trace_id = next(trace_dir.glob("*.response.json")).name.replace(".response.json", "")

    # Replay with --json - confirms the renderer pivot works.
    out2 = io.StringIO()
    rc = main(["replay", "--json", trace_id], out=out2)
    assert rc == 0
    payload = json.loads(out2.getvalue())
    assert payload["category"] == "term_structure"


def test_voli_replay_missing_target_returns_4(trace_dir: Path) -> None:
    out = io.StringIO()
    rc = main(["replay", "--no-color", "does_not_exist"], out=out)
    assert rc == 4
    assert "No replay companion" in out.getvalue()
