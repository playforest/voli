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
from .agent.batch import answer_many
from .agent.executor import ToolRegistry
from .agent.state import AnswerResponse
from .cli_render import (
    THEMES,
    cycle_next_theme,
    list_themes,
    make_theme,
    render_batch,
    render_batch_json,
    render_json,
    render_response,
    resolve_theme_name,
)
from .config import load_config
from .logging import setup_logging
from .replay import dump_response, replay_to_response
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
    ask.add_argument(
        "--skeptic",
        action="store_true",
        help="Run the skeptic sub-agent and append a [ SKEPTIC ] block.",
    )
    ask.add_argument(
        "--plot",
        default=None,
        metavar="PATH",
        help="Save a category-specific PNG chart to PATH (requires `pip install matplotlib` "
        "or `poetry install -E plot`).",
    )
    _add_theme_flags(ask)

    # ---- ask-many ---------------------------------------------------------
    ask_many = sub.add_parser(
        "ask-many",
        help="Run the same prompt against multiple tickers and compare results.",
    )
    ask_many.add_argument("prompt", help="Generic prompt without a ticker.")
    ask_many.add_argument(
        "--tickers",
        required=True,
        help="Comma-separated list, e.g. NVDA,SPY,QQQ",
    )
    ask_many.add_argument("--asof", default=None)
    ask_many.add_argument("--json", action="store_true")
    ask_many.add_argument("--trace", action="store_true")
    ask_many.add_argument("--skeptic", action="store_true")
    _add_theme_flags(ask_many)

    # ---- llm-ask ---------------------------------------------------------
    llm = sub.add_parser(
        "llm-ask",
        help="Ask an LLM (Claude or GPT) using OQE tools as its data backend.",
    )
    llm.add_argument("prompt", help="The question to ask, in quotes.")
    llm.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "openai"],
        help="LLM provider. Default: $OQE_LLM_PROVIDER, or anthropic/openai "
        "based on which API key is set.",
    )
    llm.add_argument(
        "--model",
        default=None,
        help="Model name (overrides $OQE_LLM_MODEL and the provider default).",
    )
    llm.add_argument(
        "--json", action="store_true", help="Emit a JSON object with the final answer + tool log."
    )
    llm.add_argument(
        "--max-iterations",
        type=int,
        default=6,
        help="Cap on planner/tool/answer cycles. Default 6.",
    )
    llm.add_argument(
        "--skeptic",
        action="store_true",
        help="Run the skeptic over the LLM's tool results and append a [ SKEPTIC ] block.",
    )
    llm.add_argument(
        "--trace",
        action="store_true",
        help="Open a JSONL run-trace and write a <trace_id>.llm.json "
        "companion so 'oqe replay' can re-render the answer offline.",
    )
    _add_theme_flags(llm)

    # ---- mcp-serve --------------------------------------------------------
    mcp_serve = sub.add_parser(
        "mcp-serve",
        help="Run the OQE Model Context Protocol server over stdio.",
    )
    mcp_serve.add_argument(
        "--raw-only",
        action="store_true",
        help="Expose only the four raw Polygon tools (skip the analytics layer).",
    )

    # ---- replay -----------------------------------------------------------
    replay = sub.add_parser(
        "replay",
        help="Re-render a previously stored answer (companion JSON from --trace).",
    )
    replay.add_argument(
        "target",
        help="Trace ID (e.g. 20260505T130904Z_a1b2c3d4) or a path to a "
        "<trace_id>.response.json file.",
    )
    replay.add_argument("--json", action="store_true")
    _add_theme_flags(replay)

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
    if args.command == "ask-many":
        return _cmd_ask_many(args, registry=registry, out=out)
    if args.command == "llm-ask":
        return _cmd_llm_ask(args, out=out)
    if args.command == "mcp-serve":
        return _cmd_mcp_serve(args, out=out)
    if args.command == "replay":
        return _cmd_replay(args, out=out)
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
                skeptic=getattr(args, "skeptic", False),
            )
        except Exception as exc:
            return _render_error(args, exc, out=out)

        theme_name = _selected_theme(args)
        if args.json:
            text = render_json(resp, asof=args.asof, trace_id=trace_id)
        else:
            text = render_response(
                resp,
                color=_color_flag(args),
                theme=theme_name,
                asof=args.asof,
                trace_id=trace_id,
            )
        print(text, file=out)

        # Optional side effects: chart + replay companion.
        if getattr(args, "plot", None):
            try:
                _save_plot(resp, args.plot, out=out, theme_name=theme_name, color=_color_flag(args))
            except Exception as exc:
                # Plot failures shouldn't poison the answer's exit code; show
                # a themed warning and continue.
                _print_warning(args, f"plot failed: {type(exc).__name__}: {exc}", out=out)

        if args.trace and trace_id is not None:
            try:
                path = dump_response(
                    trace_id,
                    resp,
                    prompt=args.prompt,
                    asof=args.asof,
                    theme=theme_name,
                    ticker_default=args.ticker,
                    skeptic=getattr(args, "skeptic", False),
                )
                t = make_theme(_color_flag(args), theme=theme_name)
                print(t.dim(f"replay companion: {path}"), file=out)
            except Exception as exc:
                _print_warning(args, f"replay companion failed: {exc}", out=out)

        return 0 if resp.supported else 3
    finally:
        if args.trace and get_trace() is not None:
            end_trace()


def _save_plot(
    resp: AnswerResponse, path: str, *, out, theme_name: str, color: bool | None
) -> None:
    """Render a chart for `resp` and confirm in the themed style."""

    from .plot import plot_response  # lazy import - matplotlib is optional

    saved = plot_response(resp, path)
    t = make_theme(color, theme=theme_name)
    print(t.dim(f"plot: {saved}"), file=out)


def _print_warning(args: argparse.Namespace, message: str, *, out) -> None:
    t = make_theme(_color_flag(args), theme=_selected_theme(args))
    print(t.warn(f"warn: {message}"), file=out)


# ---- ask-many ---------------------------------------------------------------


def _cmd_ask_many(args: argparse.Namespace, *, registry: ToolRegistry | None, out) -> int:
    tickers = [t.strip().upper() for t in (args.tickers or "").split(",") if t.strip()]
    if not tickers:
        print("No tickers supplied. Use --tickers NVDA,SPY,QQQ", file=out)
        return 2

    trace_id = None
    if args.trace:
        trace_id = start_trace().trace_id
    try:
        try:
            batch = answer_many(
                args.prompt,
                tickers,
                registry=registry,
                skeptic=getattr(args, "skeptic", False),
            )
        except Exception as exc:
            return _render_error(args, exc, out=out)

        if args.json:
            text = render_batch_json(batch, asof=args.asof, trace_id=trace_id)
        else:
            text = render_batch(
                batch,
                color=_color_flag(args),
                theme=_selected_theme(args),
                asof=args.asof,
                trace_id=trace_id,
            )
        print(text, file=out)
        # Exit 0 if every row succeeded, else 3.
        any_failed = any(r.error or (r.response and not r.response.supported) for r in batch.rows)
        return 0 if not any_failed else 3
    finally:
        if args.trace and get_trace() is not None:
            end_trace()


# ---- llm-ask ---------------------------------------------------------------


def _cmd_llm_ask(args: argparse.Namespace, *, out) -> int:
    """Run the LLM-driven agent loop and stream events to the terminal.

    Designed to feel like the rest of the CLI: themed status bar, themed
    [ THINKING ] / [ TOOL CALL ] / [ ANSWER ] sections, exit code 0 on a
    finished answer, 4 on any provider/SDK error.
    """

    import json as _json

    from .llm import (
        AgentConfig,
        StepComplete,
        TextDelta,
        ToolCallStart,
        ToolResult,
        build_default_tools,
        llm_ask,
    )
    from .llm.provider import make_provider

    theme_name = _selected_theme(args)
    color = _color_flag(args)
    t = make_theme(color, theme=theme_name)

    try:
        provider = make_provider(args.provider, model=args.model)
    except (ImportError, ValueError) as exc:
        return _render_error(args, exc, out=out)

    cfg = AgentConfig(max_iterations=args.max_iterations)
    tools = build_default_tools()

    # Optional: open a JSONL trace. Polygon tools auto-log to it; we'll
    # also write an LLM companion at the end.
    trace_id = None
    if getattr(args, "trace", False):
        trace_id = start_trace().trace_id

    # Status bar.
    bits = [
        "OQE LLM",
        f"PROVIDER: {provider.name}",
        f"MODEL: {provider.model}",
    ]
    if t.color and t.name != "bloomberg":
        bits.append(f"THEME: {t.name}")
    print(t.dim("=" * 80), file=out)
    print(t.status_bar(" | ".join(bits)), file=out)
    print(t.dim("=" * 80), file=out)
    print(t.header("[ PROMPT ]"), file=out)
    print(args.prompt, file=out)

    answer_buf: list[str] = []
    tool_calls: list[ToolCallStart] = []
    tool_results: list[ToolResult] = []
    in_answer = False
    stop_reason = "end_turn"

    try:
        for event in llm_ask(args.prompt, provider=provider, tools=tools, config=cfg):
            if isinstance(event, ToolCallStart):
                if in_answer:
                    print("", file=out)  # close answer paragraph cleanly
                    in_answer = False
                pretty_args = _json.dumps(event.arguments, separators=(", ", "="))
                print(
                    f"\n{t.label('[ TOOL CALL ]')} {t.value(event.name)}({t.dim(pretty_args)})",
                    file=out,
                    flush=True,
                )
                tool_calls.append(event)
            elif isinstance(event, ToolResult):
                preview = event.content
                if len(preview) > 200:
                    preview = preview[:197] + "..."
                marker = "[ TOOL ERR  ]" if event.is_error else "[ TOOL OK   ]"
                print(
                    f"{t.label(marker)} {t.dim(preview)}",
                    file=out,
                    flush=True,
                )
                tool_results.append(event)
            elif isinstance(event, TextDelta):
                if not in_answer:
                    print(f"\n{t.header('[ ANSWER ]')}", file=out, flush=True)
                    in_answer = True
                print(t.value(event.text), end="", file=out, flush=True)
                answer_buf.append(event.text)
            elif isinstance(event, StepComplete):
                stop_reason = event.stop_reason
    except Exception as exc:  # pragma: no cover - hard to provoke without live API
        return _render_error(args, exc, out=out)

    # Trailing newline so the next shell prompt isn't glued to the answer.
    if in_answer:
        print("", file=out)

    # Optional skeptic pass over the LLM's tool results.
    skeptic_lines: list[str] | None = None
    if getattr(args, "skeptic", False):
        from .llm.skeptic import review_llm_run

        concerns = review_llm_run(tool_results)
        skeptic_lines = [c.render() for c in concerns]
        if skeptic_lines:
            print("", file=out)
            print(t.header("[ SKEPTIC ]"), file=out)
            for line in skeptic_lines:
                head = line.split()[0] if line else ""
                if head in ("CRITICAL", "WARN"):
                    print(t.warn(line), file=out)
                else:
                    print(t.dim(line), file=out)

    print(t.dim("-" * 80), file=out)
    print(
        t.dim(
            f"stop_reason: {stop_reason}  |  tool_calls: {len(tool_calls)}  "
            f"|  tool_results: {len(tool_results)}"
        ),
        file=out,
    )

    # Optional replay companion + trace bookkeeping.
    if trace_id is not None:
        from .llm.replay import dump_llm_run

        try:
            path = dump_llm_run(
                trace_id,
                prompt=args.prompt,
                provider=provider.name,
                model=provider.model,
                answer="".join(answer_buf),
                stop_reason=stop_reason,
                tool_calls=tool_calls,
                tool_results=tool_results,
                skeptic=skeptic_lines,
            )
            print(t.dim(f"replay companion: {path}"), file=out)
        except Exception as exc:
            _print_warning(args, f"replay companion failed: {exc}", out=out)
        finally:
            if get_trace() is not None:
                end_trace()

    print(t.dim("=" * 80), file=out)

    if args.json:
        # Emit a structured JSON tail for scripting after the themed block.
        payload = {
            "provider": provider.name,
            "model": provider.model,
            "prompt": args.prompt,
            "answer": "".join(answer_buf),
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in tool_calls
            ],
            "tool_results": [
                {"id": r.id, "name": r.name, "content": r.content, "is_error": r.is_error}
                for r in tool_results
            ],
            "stop_reason": stop_reason,
            "skeptic": skeptic_lines,
            "trace_id": trace_id,
        }
        print(_json.dumps(payload, indent=2, default=str), file=out)

    return 0


# ---- mcp-serve --------------------------------------------------------------


def _cmd_mcp_serve(args: argparse.Namespace, *, out) -> int:
    """Run the OQE MCP server over stdio.

    The server logs to stderr; stdout is reserved for the MCP wire protocol
    (Claude Desktop talks JSON-RPC over the child process's stdin/stdout).
    `--raw-only` drops the analytics tools - useful when you want Claude
    to chain the primitives itself.
    """

    try:
        from .mcp_server import serve
    except ImportError as exc:
        return _render_error(args, exc, out=out)

    try:
        serve(include_analytics=not args.raw_only)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # pragma: no cover - hard to provoke without a client
        return _render_error(args, exc, out=out)
    return 0


# ---- replay -----------------------------------------------------------------


def _cmd_replay(args: argparse.Namespace, *, out) -> int:
    """Read a stored answer companion and re-render it.

    Replay only re-renders the saved companion - it does not re-run tool
    dispatch. This makes replays free + offline + deterministic, and lets
    the user pivot the visualisation (theme, json) without re-fetching
    Polygon data.

    Auto-detects two companion shapes:
      * <id>.response.json  - rule-based AnswerResponse (oqe.replay.dump_response)
      * <id>.llm.json       - LLM run record (oqe.llm.replay.dump_llm_run)
    """

    # Try LLM companion first - it's the newer shape and the resolver
    # falls through cleanly when the file doesn't exist.
    from .llm.replay import load_llm_run

    try:
        record = load_llm_run(args.target)
    except FileNotFoundError:
        record = None

    if record is not None:
        return _replay_llm_run(args, record, out=out)

    # Fall back to the rule-based replay path.
    try:
        resp = replay_to_response(args.target)
    except FileNotFoundError as exc:
        _print_warning(args, str(exc), out=out)
        return 4

    if args.json:
        text = render_json(resp)
    else:
        text = render_response(
            resp,
            color=_color_flag(args),
            theme=_selected_theme(args),
            trace_id=args.target if not args.target.endswith(".json") else None,
        )
    print(text, file=out)
    return 0 if resp.supported else 3


def _replay_llm_run(args: argparse.Namespace, record, *, out) -> int:
    """Render a stored LLMRunRecord via the same themed blocks `_cmd_llm_ask`
    uses live, so a replay is visually indistinguishable from the original
    run minus the streaming.
    """

    import json as _json

    if args.json:
        from dataclasses import asdict

        print(_json.dumps(asdict(record), indent=2, default=str, sort_keys=True), file=out)
        return 0

    theme_name = _selected_theme(args)
    color = _color_flag(args)
    t = make_theme(color, theme=theme_name)

    bits = [
        "OQE LLM | REPLAY",
        f"PROVIDER: {record.provider}",
        f"MODEL: {record.model}",
    ]
    if t.color and t.name != "bloomberg":
        bits.append(f"THEME: {t.name}")
    print(t.dim("=" * 80), file=out)
    print(t.status_bar(" | ".join(bits)), file=out)
    print(t.dim("=" * 80), file=out)
    print(t.header("[ PROMPT ]"), file=out)
    print(record.prompt, file=out)

    for call, result in zip(record.tool_calls, record.tool_results, strict=False):
        pretty_args = _json.dumps(call["arguments"], separators=(", ", "="))
        print(
            f"\n{t.label('[ TOOL CALL ]')} {t.value(call['name'])}({t.dim(pretty_args)})",
            file=out,
        )
        preview = result["content"]
        if len(preview) > 200:
            preview = preview[:197] + "..."
        marker = "[ TOOL ERR  ]" if result.get("is_error") else "[ TOOL OK   ]"
        print(f"{t.label(marker)} {t.dim(preview)}", file=out)

    if record.answer:
        print(f"\n{t.header('[ ANSWER ]')}", file=out)
        print(t.value(record.answer), file=out)

    if record.skeptic:
        print("", file=out)
        print(t.header("[ SKEPTIC ]"), file=out)
        for line in record.skeptic:
            head = line.split()[0] if line else ""
            if head in ("CRITICAL", "WARN"):
                print(t.warn(line), file=out)
            else:
                print(t.dim(line), file=out)

    print(t.dim("-" * 80), file=out)
    print(
        t.dim(
            f"stop_reason: {record.stop_reason}  |  "
            f"tool_calls: {len(record.tool_calls)}  |  "
            f"tool_results: {len(record.tool_results)}  |  "
            f"trace_id: {record.trace_id}"
        ),
        file=out,
    )
    print(t.dim("=" * 80), file=out)
    return 0


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
