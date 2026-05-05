"""Plotting tests.

We use matplotlib's headless `Agg` backend (the plot module sets that
itself) and write into pytest's tmp_path so each test owns its file.

The eval harness's synthetic registry produces deterministic data, so we
can rely on exact response shapes without monkey-patching anything.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from oqe.agent import answer_question
from oqe.cli import main
from oqe.eval.synth_market import make_registry

# Skip cleanly on systems without matplotlib (e.g. lean install with no -E plot).
matplotlib = pytest.importorskip("matplotlib")
plot_module = pytest.importorskip("oqe.plot")
plot_response = plot_module.plot_response


@pytest.fixture()
def registry():
    return make_registry()


# ---- per-category renderers -------------------------------------------------


def test_plot_term_structure_writes_png(registry, tmp_path: Path) -> None:
    resp = answer_question(
        "ATM IV this week vs next week",
        ticker_default="NVDA",
        registry=registry,
    )
    out = plot_response(resp, tmp_path / "ts.png")
    assert out.exists()
    assert out.stat().st_size > 0
    # PNG magic.
    with out.open("rb") as f:
        head = f.read(8)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"


def test_plot_skew_writes_png(registry, tmp_path: Path) -> None:
    resp = answer_question(
        "Show IV skew next Friday",
        ticker_default="NVDA",
        registry=registry,
    )
    out = plot_response(resp, tmp_path / "skew.png")
    assert out.exists() and out.stat().st_size > 0


def test_plot_greeks_writes_png(registry, tmp_path: Path) -> None:
    # Prompt deliberately leaves the expiry generic - an explicit ISO date
    # narrows the contract list to one expiry, and the bundle's greeks
    # computation pivots off term-structure's front_expiry which needs >=2.
    resp = answer_question("Show ATM greeks for NVDA", registry=registry)
    out = plot_response(resp, tmp_path / "greeks.png")
    assert out.exists() and out.stat().st_size > 0


def test_plot_chain_writes_png(registry, tmp_path: Path) -> None:
    resp = answer_question(
        "Show NVDA options for 2026-05-16",
        registry=registry,
    )
    out = plot_response(resp, tmp_path / "chain.png")
    assert out.exists() and out.stat().st_size > 0


# ---- error paths ------------------------------------------------------------


def test_plot_refuses_not_supported_response(registry, tmp_path: Path) -> None:
    resp = answer_question("Should I buy NVDA calls?", registry=registry)
    with pytest.raises(ValueError, match="not-supported"):
        plot_response(resp, tmp_path / "x.png")


def test_plot_raises_clear_error_when_matplotlib_missing(
    monkeypatch, registry, tmp_path: Path
) -> None:
    """Hide matplotlib from the lazy import to simulate a lean install."""

    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", None)

    # _require_mpl uses `try: import matplotlib`, which won't raise when the
    # cache has None - we need to patch the import system. The simplest path
    # is to patch `_require_mpl` itself for this test.
    with patch.object(
        plot_module, "_require_mpl", side_effect=ImportError("Plotting requires matplotlib.")
    ):
        resp = answer_question(
            "ATM IV this week vs next week",
            ticker_default="NVDA",
            registry=registry,
        )
        with pytest.raises(ImportError, match="matplotlib"):
            plot_response(resp, tmp_path / "x.png")


# ---- CLI integration --------------------------------------------------------


def test_ask_with_plot_flag_saves_file(registry, tmp_path: Path) -> None:
    out = io.StringIO()
    target = tmp_path / "out.png"
    rc = main(
        [
            "ask",
            "--no-color",
            "--plot",
            str(target),
            "ATM IV this week vs next week",
        ],
        registry=registry,
        out=out,
    )
    assert rc == 3  # missing ticker -> refused
    # When refused, the plot is skipped (and warned about) but the answer
    # block still renders.
    text = out.getvalue()
    assert "I need a ticker" in text or "ticker" in text.lower()


def test_ask_with_plot_flag_and_ticker_saves_file(registry, tmp_path: Path) -> None:
    out = io.StringIO()
    target = tmp_path / "ts.png"
    rc = main(
        [
            "ask",
            "--no-color",
            "--ticker",
            "NVDA",
            "--plot",
            str(target),
            "ATM IV this week vs next week",
        ],
        registry=registry,
        out=out,
    )
    assert rc == 0
    assert target.exists()
    text = out.getvalue()
    assert f"plot: {target}" in text
