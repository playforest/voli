"""Command-line interface for the Options Query Engine.

Usage:
    oqe ask "NVDA ATM IV this week vs next week" [--ticker NVDA]
        [--asof 2026-05-05T15:00:00Z] [--json] [--trace] [--no-color]

The CLI is a thin shell around `oqe.agent.answer_question`. The orchestration
itself is unaware of presentation; this module owns argument parsing, trace
bookkeeping, and dispatch to the Bloomberg-style renderer in `cli_render`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from dotenv import load_dotenv

from .agent import answer_question
from .agent.executor import ToolRegistry
from .cli_render import make_theme, render_json, render_response
from .run_trace import end_trace, get_trace, start_trace

# Load .env at CLI import time so POLYGON_API_KEY (and other Polygon settings)
# are available before the default registry instantiates the HTTP client.
# Library users who import oqe.* directly are unaffected - dotenv only fires
# when this CLI module is imported.
load_dotenv()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oqe",
        description=(
            "Options Query Engine - ask grounded questions about an options "
            "chain (chain slice, IV term structure, skew, greeks)."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

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
        help="Emit JSON instead of the Bloomberg-style text view.",
    )
    ask.add_argument(
        "--trace",
        action="store_true",
        help="Open a JSONL run-trace under $OQE_TRACE_DIR for this question.",
    )
    ask.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour. Honoured automatically when stdout is not a TTY.",
    )
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

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover - argparse exits before this line


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
            color = False if args.no_color else None  # None = auto-detect
            text = render_response(
                resp,
                color=color,
                asof=args.asof,
                trace_id=trace_id,
            )
        print(text, file=out)
        return 0 if resp.supported else 3
    finally:
        if args.trace and get_trace() is not None:
            end_trace()


def _render_error(args: argparse.Namespace, exc: Exception, *, out) -> int:
    """Render an exception in the Bloomberg style and exit non-zero.

    Keeps stack traces out of the user's face by default - the exception type
    and message are shown in the standard layout. Exit code 4 distinguishes
    upstream failures from refusals (3) and argparse errors (2).
    """

    theme = make_theme(False if args.no_color else None)
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
