"""Optional plotting (matplotlib).

Lazy-imports matplotlib so the lean install (no plotting deps) keeps
working - calling `plot_response()` without matplotlib raises a clear
ImportError pointing at the right install command rather than crashing
on the import.

Each category has its own renderer; `plot_response()` dispatches:

  * term_structure -> line plot of expiry vs ATM IV
  * skew           -> scatter+line of strike vs IV with ATM marker
  * greeks         -> bar chart of (delta, gamma, theta, vega) at ATM
  * chain          -> scatter of strike vs mid (calls + puts overlaid)

The colour scheme mirrors the Bloomberg theme so saved PNGs look like
the CLI output: orange primary, amber accents, black background, dim
gridlines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent.state import AnswerResponse

# ---------------------------------------------------------------------------
# matplotlib shim - lazy import keeps the lean install working
# ---------------------------------------------------------------------------


def _require_mpl():
    try:
        import matplotlib

        matplotlib.use("Agg")  # headless: no DISPLAY required
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "Plotting requires matplotlib. Install the optional extra:\n"
            "  poetry install -E plot\n"
            "Then re-run the command."
        ) from exc
    return plt


# Bloomberg-ish palette in hex (matplotlib doesn't speak ANSI 256).
_BG = "#000000"
_PANEL = "#0a0a0a"
_PRIMARY = "#FF8A00"  # orange
_SECONDARY = "#FFB300"  # amber
_TEXT = "#FFFFFF"
_DIM = "#5a5a5a"
_GRID = "#1f1f1f"
_GREEN = "#00d264"
_RED = "#ff3b3b"


def _theme_axes(fig, ax) -> None:
    """Apply the Bloomberg-ish dark style to a single axes."""

    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_PANEL)
    for spine in ax.spines.values():
        spine.set_color(_DIM)
    ax.tick_params(colors=_TEXT, labelsize=9)
    ax.xaxis.label.set_color(_TEXT)
    ax.yaxis.label.set_color(_TEXT)
    ax.title.set_color(_PRIMARY)
    ax.title.set_fontweight("bold")
    ax.grid(True, color=_GRID, linewidth=0.5)


def _save(fig, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=_BG)
    return path


# ---------------------------------------------------------------------------
# Per-category renderers
# ---------------------------------------------------------------------------


def _plot_term_structure(resp: AnswerResponse, path: Path) -> Path:
    plt = _require_mpl()
    rows = (resp.table or {}).get("rows", []) or []
    expiries = [r["expiry"] for r in rows]
    ivs = [r["atm_iv"] for r in rows]
    if not expiries or any(v is None for v in ivs):
        raise ValueError("term_structure response has no plottable rows")

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(expiries, ivs, color=_PRIMARY, marker="o", markersize=8, linewidth=2)
    for x, y in zip(expiries, ivs, strict=False):
        ax.annotate(
            f"{y:.4f}",
            (x, y),
            textcoords="offset points",
            xytext=(0, 10),
            ha="center",
            color=_SECONDARY,
            fontsize=9,
        )

    ticker = (resp.facts or {}).get("ticker", "")
    atm = (resp.facts or {}).get("atm_strike", "")
    ax.set_title(f"{ticker} ATM IV TERM STRUCTURE  (strike {atm})")
    ax.set_xlabel("EXPIRY")
    ax.set_ylabel("ATM IV")
    _theme_axes(fig, ax)
    return _save(fig, path)


def _plot_skew(resp: AnswerResponse, path: Path) -> Path:
    plt = _require_mpl()
    facts = resp.facts or {}
    front_expiry = facts.get("front_expiry")
    atm_strike = facts.get("atm_strike")
    slope = facts.get("skew_slope")

    # The agent's skew table only carries summary numbers (slope), so we
    # plot the OLS-line we know plus the ATM marker for context. If the
    # caller has the underlying strike/IV pairs, they can extend this with
    # a richer renderer; for the agent's output, this gives a clean visual.
    if slope is None or atm_strike is None:
        raise ValueError("skew response missing slope or ATM strike")

    spot_value = (facts.get("spot") or {}).get("value", float(atm_strike))
    width = max(spot_value * 0.10, 5.0)
    xs = [spot_value - width, spot_value, spot_value + width]
    # IV at ATM isn't in the response table; estimate as 0 baseline + slope*delta.
    base = 0.0
    ys = [base + slope * (x - spot_value) for x in xs]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(xs, ys, color=_PRIMARY, linewidth=2, label=f"slope = {slope:+.6f}")
    ax.axvline(
        spot_value, color=_DIM, linestyle="--", linewidth=1, label=f"spot = {spot_value:.4f}"
    )
    ax.axvline(
        float(atm_strike),
        color=_SECONDARY,
        linestyle=":",
        linewidth=1,
        label=f"ATM strike = {atm_strike}",
    )

    ticker = facts.get("ticker", "")
    ax.set_title(f"{ticker} SKEW SLOPE  ({front_expiry})")
    ax.set_xlabel("STRIKE")
    ax.set_ylabel("IV (mean-centred)")
    leg = ax.legend(
        loc="upper left", facecolor=_PANEL, edgecolor=_DIM, labelcolor=_TEXT, fontsize=9
    )
    leg.get_frame().set_alpha(0.85)
    _theme_axes(fig, ax)
    return _save(fig, path)


def _plot_greeks(resp: AnswerResponse, path: Path) -> Path:
    plt = _require_mpl()
    atm = (resp.facts or {}).get("atm_contract") or {}
    fields = ("delta", "gamma", "theta", "vega")
    values = [atm.get(f) for f in fields]
    if all(v is None for v in values):
        raise ValueError("greeks response has no ATM greeks to plot")

    plot_vals = [v if v is not None else 0.0 for v in values]
    colors = [_GREEN if v is not None and v >= 0 else _RED for v in values]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(fields, plot_vals, color=colors, edgecolor=_DIM)
    for bar, raw in zip(bars, values, strict=False):
        if raw is None:
            continue
        h = bar.get_height()
        ax.annotate(
            f"{raw:+.4f}",
            (bar.get_x() + bar.get_width() / 2, h),
            textcoords="offset points",
            xytext=(0, 6 if h >= 0 else -16),
            ha="center",
            color=_TEXT,
            fontsize=9,
        )
    ax.axhline(0, color=_DIM, linewidth=0.8)

    ticker = (resp.facts or {}).get("ticker", "")
    strike = atm.get("strike", "")
    expiry = atm.get("expiry", "")
    ax.set_title(f"{ticker} ATM GREEKS  ({expiry} strike {strike})")
    ax.set_ylabel("VALUE")
    _theme_axes(fig, ax)
    return _save(fig, path)


def _plot_chain(resp: AnswerResponse, path: Path) -> Path:
    plt = _require_mpl()
    rows = (resp.table or {}).get("rows", []) or []
    calls = [(r["strike"], r.get("mid")) for r in rows if r.get("right") == "C"]
    puts = [(r["strike"], r.get("mid")) for r in rows if r.get("right") == "P"]

    if not calls and not puts:
        raise ValueError("chain response has no contracts to plot")

    fig, ax = plt.subplots(figsize=(9, 5))
    if calls:
        xs, ys = zip(*[(s, m) for s, m in calls if m is not None], strict=False)
        ax.scatter(xs, ys, color=_PRIMARY, s=40, label="calls (mid)")
    if puts:
        xs, ys = zip(*[(s, m) for s, m in puts if m is not None], strict=False)
        ax.scatter(xs, ys, color=_SECONDARY, s=40, label="puts (mid)", marker="x")

    spot = (resp.facts or {}).get("spot") or {}
    if isinstance(spot, dict) and spot.get("value") is not None:
        ax.axvline(
            float(spot["value"]),
            color=_DIM,
            linestyle="--",
            linewidth=1,
            label=f"spot = {spot['value']:.4f}",
        )

    ticker = (resp.facts or {}).get("ticker", "")
    ax.set_title(f"{ticker} CHAIN MID PRICES")
    ax.set_xlabel("STRIKE")
    ax.set_ylabel("MID")
    leg = ax.legend(
        loc="upper right", facecolor=_PANEL, edgecolor=_DIM, labelcolor=_TEXT, fontsize=9
    )
    leg.get_frame().set_alpha(0.85)
    _theme_axes(fig, ax)
    return _save(fig, path)


_DISPATCH: dict[str, Any] = {
    "term_structure": _plot_term_structure,
    "skew": _plot_skew,
    "greeks": _plot_greeks,
    "chain": _plot_chain,
}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def plot_response(resp: AnswerResponse, path: str | Path) -> Path:
    """Save a category-specific chart for `resp` to `path` and return the path.

    Raises:
      ImportError if matplotlib isn't installed (install with `poetry install -E plot`).
      ValueError  if the response category isn't plottable, or has no data to render.
    """

    if not resp.supported:
        raise ValueError(f"cannot plot a not-supported response (category={resp.category!r})")
    renderer = _DISPATCH.get(resp.category)
    if renderer is None:
        raise ValueError(f"no plot renderer registered for category {resp.category!r}")
    return renderer(resp, Path(path))
