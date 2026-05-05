"""Bloomberg-style ANSI renderer for AnswerResponse.

Design:
  * 256-color ANSI only - no third-party deps, works in every modern terminal.
  * Honours `NO_COLOR` (https://no-color.org) and the `--no-color` flag the
    CLI passes through `color=False`.
  * Pure functions: `render_response(resp)` returns a string. The CLI handles
    actual stdout writing so tests can capture the rendered text directly.

Theme (close to Bloomberg Terminal defaults):
  * Section headers and the top status bar: bold orange (#FF8A00, ANSI 208).
  * Facts keys / column headers: amber (ANSI 214).
  * Borders, dividers, dim labels: gray (ANSI 240).
  * Values default to the terminal's foreground colour (typically white).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .agent.state import AnswerResponse

# 256-color ANSI codes ---------------------------------------------------------
ESC = "\x1b"
RESET = f"{ESC}[0m"
BOLD = f"{ESC}[1m"
DIM = f"{ESC}[2m"
UNDERLINE = f"{ESC}[4m"


def _fg(n: int) -> str:
    return f"{ESC}[38;5;{n}m"


def _bg(n: int) -> str:
    return f"{ESC}[48;5;{n}m"


# Bloomberg-ish palette
ORANGE = _fg(208)  # Bloomberg primary accent
AMBER = _fg(214)  # softer amber for keys
WHITE = _fg(231)  # values
GRAY = _fg(240)  # borders / dim
RED = _fg(196)  # negatives / warnings
GREEN = _fg(46)  # positives
BLACK_BG = _bg(16)


@dataclass(frozen=True)
class Theme:
    """Resolved styling tokens. `color=False` returns a no-op theme so the
    output is pure ASCII (ideal for tests, redirected output, dumb terminals).
    """

    color: bool

    def style(self, *codes: str, text: str) -> str:
        if not self.color or not text:
            return text
        return "".join(codes) + text + RESET

    def header(self, text: str) -> str:
        return self.style(BOLD, ORANGE, text=text)

    def label(self, text: str) -> str:
        return self.style(BOLD, AMBER, text=text)

    def value(self, text: str) -> str:
        return self.style(WHITE, text=text)

    def dim(self, text: str) -> str:
        return self.style(DIM, GRAY, text=text)

    def warn(self, text: str) -> str:
        return self.style(BOLD, RED, text=text)

    def good(self, text: str) -> str:
        return self.style(BOLD, GREEN, text=text)

    def status_bar(self, text: str) -> str:
        if not self.color:
            return text
        return f"{BLACK_BG}{BOLD}{ORANGE} {text} {RESET}"


def _color_supported() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(os, "isatty"):
        return False
    try:
        return os.isatty(1)  # stdout
    except (OSError, ValueError):
        return False


def make_theme(color: bool | None = None) -> Theme:
    if color is None:
        color = _color_supported()
    return Theme(color=bool(color))


# Layout helpers --------------------------------------------------------------

WIDTH = 80


def _hr(theme: Theme, ch: str = "=") -> str:
    return theme.dim(ch * WIDTH)


def _section(theme: Theme, title: str) -> str:
    return theme.header(f"[ {title.upper()} ]")


def _wrap(text: str, width: int = WIDTH) -> list[str]:
    """Word-wrap to fit terminal width (Bloomberg-style hard wrap)."""

    out: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split(" "):
            if not word:
                continue
            if len(line) + 1 + len(word) > width:
                if line:
                    out.append(line)
                line = word
            else:
                line = (line + " " + word).strip()
        out.append(line)
    return out


def _fmt_number(v: Any) -> str:
    """Bloomberg-style numeric formatting: fixed precision, sign-aware."""

    if v is None:
        return "-"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        if abs(v) >= 1000 or v == int(v):
            return f"{v:,.4f}".rstrip("0").rstrip(".")
        return f"{v:.4f}"
    return str(v)


def _fmt_value(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, int | float) and not isinstance(v, bool):
        return _fmt_number(v)
    return str(v)


def _render_table(theme: Theme, columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> str:
    """Tight monospaced table with right-aligned numeric cells.

    Column header is amber, separator is dim gray, values use the terminal's
    default foreground.
    """

    if not rows:
        return theme.dim("(no rows)")

    headers = [c.upper() for c in columns]
    cells: list[list[str]] = [[_fmt_value(r.get(c)) for c in columns] for r in rows]
    widths = [max(len(headers[i]), *(len(row[i]) for row in cells)) for i in range(len(columns))]

    def _row(items: Iterable[str], *, header: bool = False) -> str:
        parts: list[str] = []
        for i, raw in enumerate(items):
            val = raw.rjust(widths[i]) if _is_numeric_column(cells, i) else raw.ljust(widths[i])
            parts.append(theme.label(val) if header else theme.value(val))
        sep = theme.dim("  |  ")
        return sep.join(parts)

    head = _row(headers, header=True)
    sep = theme.dim("-" * (sum(widths) + 5 * (len(widths) - 1)))
    body = "\n".join(_row(row) for row in cells)
    return f"{head}\n{sep}\n{body}"


def _is_numeric_column(cells: Sequence[Sequence[str]], idx: int) -> bool:
    """A column is numeric if every non-empty cell parses as a number."""

    for row in cells:
        cell = row[idx]
        if cell in ("", "-"):
            continue
        try:
            float(cell.replace(",", ""))
        except ValueError:
            return False
    return True


def _render_facts(theme: Theme, facts: dict[str, Any]) -> str:
    """Two-column key/value rendering for the Facts block."""

    if not facts:
        return theme.dim("(no facts)")

    key_w = max(len(str(k).upper()) for k in facts)
    out: list[str] = []
    for k, v in facts.items():
        key = theme.label(str(k).upper().ljust(key_w))
        out.append(f"{key}  {_render_facts_value(theme, v)}")
    return "\n".join(out)


def _render_facts_value(theme: Theme, v: Any) -> str:
    if isinstance(v, dict):
        # Inline a small dict like spot {value, ts, source}.
        bits = []
        for k, vv in v.items():
            bits.append(f"{theme.dim(str(k))}={theme.value(_fmt_value(vv))}")
        return "  ".join(bits)
    if isinstance(v, list):
        if not v:
            return theme.dim("(none)")
        return ", ".join(theme.value(_fmt_value(x)) for x in v)
    return theme.value(_fmt_value(v))


# Per-category table column orderings ----------------------------------------


_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "chain_slice": (
        "option_symbol",
        "expiry",
        "right",
        "strike",
        "bid",
        "ask",
        "mid",
        "last",
        "ts",
    ),
    "term_structure": ("expiry", "atm_strike", "atm_iv"),
    "skew": ("front_expiry", "atm_strike", "slope"),
    "greeks": (
        "option_symbol",
        "expiry",
        "strike",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
    ),
    "none": (),
}


def _table_block(theme: Theme, table: dict[str, Any]) -> str:
    ttype = table.get("type", "none")
    columns = _TABLE_COLUMNS.get(ttype, ())
    rows = table.get("rows", []) or []
    title = ttype.replace("_", " ").upper() if ttype != "none" else "TABLE"
    return f"{_section(theme, title)}\n{_render_table(theme, columns, rows)}"


# Top-level entry point -------------------------------------------------------


def _status_line(theme: Theme, resp: AnswerResponse, *, asof: str | None) -> str:
    bits: list[str] = ["OQE"]
    ticker = resp.facts.get("ticker") if isinstance(resp.facts, dict) else None
    if ticker:
        bits.append(f"TICKER: {ticker}")
    bits.append(f"CATEGORY: {resp.category.upper()}")
    if asof:
        bits.append(f"AS-OF: {asof}")
    bits.append("OK" if resp.supported else "REFUSED")
    return theme.status_bar(" | ".join(bits))


def render_response(
    resp: AnswerResponse,
    *,
    color: bool | None = None,
    asof: str | None = None,
    trace_id: str | None = None,
) -> str:
    """Render an AnswerResponse to a Bloomberg-style block of text."""

    theme = make_theme(color)

    blocks: list[str] = []
    blocks.append(_hr(theme))
    blocks.append(_status_line(theme, resp, asof=asof))
    blocks.append(_hr(theme))

    blocks.append(_section(theme, "Summary"))
    blocks.extend(_wrap(resp.summary))

    if resp.supported:
        blocks.append("")
        blocks.append(_table_block(theme, resp.table))
        blocks.append("")
        blocks.append(_section(theme, "Facts"))
        blocks.append(_render_facts(theme, resp.facts))
    else:
        blocks.append("")
        blocks.append(_section(theme, "Reason"))
        blocks.append(theme.warn(str(resp.facts.get("reason", "out of scope"))))
        if resp.suggested_rewrites:
            blocks.append("")
            blocks.append(_section(theme, "Try Instead"))
            for r in resp.suggested_rewrites:
                blocks.append(f"{theme.dim('>')} {theme.value(r)}")

    if resp.limitations:
        blocks.append("")
        blocks.append(_section(theme, "Limitations"))
        for w in resp.limitations:
            blocks.append(f"{theme.dim('!')} {theme.warn(w)}")

    if trace_id:
        blocks.append("")
        blocks.append(_hr(theme, "-"))
        blocks.append(theme.dim(f"trace_id: {trace_id}"))

    blocks.append(_hr(theme))
    return "\n".join(blocks)


def render_json(
    resp: AnswerResponse,
    *,
    asof: str | None = None,
    trace_id: str | None = None,
) -> str:
    """JSON mode: stable, color-free, machine-readable. Still routes through
    `_fmt_value` for floats so the same precision shows up in both modes.
    """

    payload = {
        "supported": resp.supported,
        "category": resp.category,
        "summary": resp.summary,
        "table": resp.table,
        "facts": resp.facts,
        "numbers_used": resp.numbers_used,
        "limitations": resp.limitations,
        "suggested_rewrites": resp.suggested_rewrites,
        "asof": asof,
        "trace_id": trace_id,
    }
    return json.dumps(payload, sort_keys=True, indent=2, default=str)
