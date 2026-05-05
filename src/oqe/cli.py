"""Command-line interface for the Options Query Engine.

Usage:
    oqe ask "NVDA ATM IV this week vs next week" [--ticker NVDA]
        [--asof 2026-05-05T15:00:00Z] [--json] [--trace] [--no-color]
        [--theme NAME | --cycle-theme]

    oqe themes list
    oqe themes preview [--theme NAME | --all]

The CLI is a thin shell around `oqe.agent.answer_question`. The orchestration
itself is unaware of presentation; this module owns argument parsing, trace
bookkeeping, theme selection, and dispatch to the renderer in `cli_render`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from dotenv import load_dotenv

from .agent import answer_question
from .agent.executor import ToolRegistry
from .agent.state import AnswerResponse
from .cli_render import (
    THEMES,
    cycle_next_theme,
    list_themes,
    make_theme,
    render_json,
    render_response,
    resolve_theme_name,
)
from .config import load_config
from .logging import setup_logging
from .run_trace import end_trace, get_trace, start_trace

# Load .env at CLI import time so POLYGON_API_KEY (and other Polygon settings)
# are available before the default registry instantiates the HTTP client.
# Library users who import oqe.* directly are unaffected - dotenv only fires
# when this CLI module is imported.
load_dotenv()
# Then layer config.yaml on top (env vars already set still win).
load_config()
# Configure the `oqe` logger so any module that imports `from oqe.logging
# import get_logger` writes through a real handler.
setup_logging()


def _add_theme_flags(parser: argparse.ArgumentParser) -> None:
    """Shared --theme / --cycle-theme / --no-color block."""

    parser.add_argument(
        "--theme",
        default=None,
        choices=sorted(THEMES.keys()),
        metavar="NAME",
        help="Colour theme. Default: bloomberg (or $OQE_THEME).",
    )
    parser.add_argument(
        "--cycle-theme",
        action="store_true",
        help="Pick the next theme in rotation (state in ~/.oqe/theme_cursor).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour. Auto-applied when stdout is not a TTY.",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oqe",
        description=(
            "Options Query Engine - ask grounded questions about an options "
            "chain (chain slice, IV term structure, skew, greeks)."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ---- ask --------------------------------------------------------------
    ask = sub.add_parser("ask", help="Ask a single natural-language question.")
    ask.add_argument("prompt", help="The question to ask, in quotes.")
    ask.add_argument(
        "--ticker",
        default=None,
        help="Default ticker if the prompt doesn't include one.",
    )
    ask.add_argument(
        "--asof",
        default=None,
        help="UTC timestamp for as-of replay (best-effort, snapshot-dependent).",
    )
    ask.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the themed text view.",
    )
    ask.add_argument(
        "--trace",
        action="store_true",
        help="Open a JSONL run-trace under $OQE_TRACE_DIR for this question.",
    )
    _add_theme_flags(ask)

    # ---- themes -----------------------------------------------------------
    themes = sub.add_parser("themes", help="List or preview the colour themes.")
    themes_sub = themes.add_subparsers(dest="theme_command", required=True)

    themes_list = themes_sub.add_parser("list", help="List the bundled themes.")
    _add_theme_flags(themes_list)

    themes_preview = themes_sub.add_parser(
        "preview", help="Render a sample answer in the chosen theme(s)."
    )
    themes_preview.add_argument(
        "--all",
        action="store_true",
        help="Render the preview in every bundled theme back to back.",
    )
    _add_theme_flags(themes_preview)

    return p


def main(
    argv: Sequence[str] | None = None,
    *,
    registry: ToolRegistry | None = None,
    out=None,
) -> int:
    """Entry point. `registry` and `out` are injection points for tests."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    out = out or sys.stdout

    if args.command == "ask":
        return _cmd_ask(args, registry=registry, out=out)
    if args.command == "themes":
        return _cmd_themes(args, out=out)

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover - argparse exits before this line


# ---- ask --------------------------------------------------------------------


def _selected_theme(args: argparse.Namespace) -> str:
    """Apply --theme / --cycle-theme / OQE_THEME precedence.

    Order of preference: --cycle-theme > --theme > $OQE_THEME > 'bloomberg'.
    """

    if getattr(args, "cycle_theme", False):
        return cycle_next_theme()
    return resolve_theme_name(getattr(args, "theme", None))


def _color_flag(args: argparse.Namespace) -> bool | None:
    return False if getattr(args, "no_color", False) else None


def _cmd_ask(args: argparse.Namespace, *, registry: ToolRegistry | None, out) -> int:
    trace_id = None
    if args.trace:
        trace_id = start_trace().trace_id
    try:
        try:
            resp = answer_question(
                args.prompt,
                ticker_default=args.ticker,
                registry=registry,
            )
        except Exception as exc:
            return _render_error(args, exc, out=out)

        if args.json:
            text = render_json(resp, asof=args.asof, trace_id=trace_id)
        else:
            text = render_response(
                resp,
                color=_color_flag(args),
                theme=_selected_theme(args),
                asof=args.asof,
                trace_id=trace_id,
            )
        print(text, file=out)
        return 0 if resp.supported else 3
    finally:
        if args.trace and get_trace() is not None:
            end_trace()


# ---- themes -----------------------------------------------------------------


def _cmd_themes(args: argparse.Namespace, *, out) -> int:
    if args.theme_command == "list":
        return _themes_list(args, out=out)
    if args.theme_command == "preview":
        return _themes_preview(args, out=out)
    return 2  # pragma: no cover - argparse enforces choices


def _themes_list(args: argparse.Namespace, *, out) -> int:
    """Print each bundled theme name + description, themed in its own colours.

    Reading the list in colour is the fastest way to pick one - each row is
    rendered using the theme it names.
    """

    color = _color_flag(args)
    for palette in list_themes():
        t = make_theme(color, theme=palette.name)
        marker = t.header(f"{palette.name:<20}")
        desc = t.value(palette.description)
        sample = t.label("[ SAMPLE ]")
        print(f"{marker}  {sample}  {desc}", file=out)
    return 0


def _themes_preview(args: argparse.Namespace, *, out) -> int:
    """Render a fixed sample AnswerResponse in one theme (or all of them)."""

    sample = _sample_response()
    color = _color_flag(args)

    if args.all:
        for palette in list_themes():
            print(
                render_response(sample, color=color, theme=palette.name),
                file=out,
            )
            print("", file=out)
        return 0

    theme_name = _selected_theme(args)
    print(render_response(sample, color=color, theme=theme_name), file=out)
    return 0


def _sample_response() -> AnswerResponse:
    """Synthetic AnswerResponse used for theme previews. Same shape as live
    output so previews look identical to a real `oqe ask` run.
    """

    return AnswerResponse(
        supported=True,
        category="term_structure",
        summary=(
            "NVDA ATM IV term structure: front IV 0.3318 vs next IV 0.3457 "
            "at strike 200.0 (diff 0.0139)."
        ),
        table={
            "type": "term_structure",
            "rows": [
                {"expiry": "2026-05-09", "atm_strike": 200.0, "atm_iv": 0.3318},
                {"expiry": "2026-05-16", "atm_strike": 200.0, "atm_iv": 0.3457},
            ],
        },
        facts={
            "ticker": "NVDA",
            "spot": {
                "value": 199.84,
                "ts": _sample_ts(),
                "source": "polygon",
            },
            "right_used": "call",
            "atm_strike": 200.0,
            "front_expiry": "2026-05-09",
            "next_expiry": "2026-05-16",
            "front_iv": 0.3318,
            "next_iv": 0.3457,
            "flags": [],
        },
        numbers_used=[199.84, 200.0, 0.3318, 0.3457, 0.0139],
        limitations=["STALE_DATA"],
        suggested_rewrites=[],
    )


def _sample_ts() -> str:
    # Deterministic sample timestamp - previews don't drift between runs.
    return datetime(2026, 5, 5, 13, 14, 23, tzinfo=UTC).isoformat()


# ---- error rendering --------------------------------------------------------


def _render_error(args: argparse.Namespace, exc: Exception, *, out) -> int:
    """Render an exception in the chosen theme and exit non-zero.

    Keeps stack traces out of the user's face by default. Exit code 4
    distinguishes upstream failures from refusals (3) and argparse errors (2).
    """

    theme = make_theme(_color_flag(args), theme=_selected_theme(args))
    cls = type(exc).__name__
    msg = str(exc) or "(no detail)"
    print(theme.dim("=" * 80), file=out)
    print(theme.status_bar(f"OQE | ERROR: {cls}"), file=out)
    print(theme.dim("=" * 80), file=out)
    print(theme.header("[ MESSAGE ]"), file=out)
    print(theme.warn(msg), file=out)
    print(theme.dim("=" * 80), file=out)
    return 4


if __name__ == "__main__":  # pragma: no cover - exercised via `oqe` script
    sys.exit(main())
