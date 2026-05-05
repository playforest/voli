"""ANSI renderer for AnswerResponse with pluggable colour themes.

Design:
  * 256-color ANSI only - no third-party deps, works in every modern terminal.
  * Honours `NO_COLOR` (https://no-color.org) and the `--no-color` flag the
    CLI passes through `color=False`.
  * Pure functions: `render_response(resp)` returns a string. The CLI handles
    actual stdout writing so tests can capture the rendered text directly.

The visual layout (status bar / sections / tables / facts) is fixed; only the
*palette* changes. Ten palettes ship out of the box (see THEMES at the bottom
of this module) - users select with `oqe ask --theme NAME` or `OQE_THEME=NAME`.
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


# ---------------------------------------------------------------------------
# Palette: the colour personality of a theme. The renderer's layout is fixed;
# swapping a palette swaps the visual identity (Bloomberg orange vs Matrix
# green vs Solarized vs ...).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    name: str
    description: str

    # ANSI escape sequences (already wrapped with `_fg`/`_bg`/style codes).
    primary: str  # status bar / section headers (the "personality" colour)
    secondary: str  # facts keys / column headers
    value: str  # body values / table cells
    dim: str  # borders, dividers, separators
    warn: str  # warnings, refusal "REFUSED" marker, errors
    good: str  # positive / "OK" markers
    bg: str  # status bar background

    # Whether the status bar should be bold. Mostly aesthetic, exposed so
    # softer themes (paper, mono) can drop it.
    bold_status: bool = True


@dataclass(frozen=True)
class Theme:
    """Resolved theme - palette + on/off switch.

    `color=False` returns a no-op theme so the output is pure ASCII (ideal
    for tests, redirected output, dumb terminals).
    """

    palette: Palette
    color: bool

    @property
    def name(self) -> str:
        return self.palette.name

    def style(self, *codes: str, text: str) -> str:
        if not self.color or not text:
            return text
        return "".join(codes) + text + RESET

    def header(self, text: str) -> str:
        return self.style(BOLD, self.palette.primary, text=text)

    def label(self, text: str) -> str:
        return self.style(BOLD, self.palette.secondary, text=text)

    def value(self, text: str) -> str:
        return self.style(self.palette.value, text=text)

    def dim(self, text: str) -> str:
        return self.style(DIM, self.palette.dim, text=text)

    def warn(self, text: str) -> str:
        return self.style(BOLD, self.palette.warn, text=text)

    def good(self, text: str) -> str:
        return self.style(BOLD, self.palette.good, text=text)

    def status_bar(self, text: str) -> str:
        if not self.color:
            return text
        bold = BOLD if self.palette.bold_status else ""
        return f"{self.palette.bg}{bold}{self.palette.primary} {text} {RESET}"


# ---------------------------------------------------------------------------
# Built-in themes. All use the same layout; only the colour mix differs.
# ---------------------------------------------------------------------------


THEMES: dict[str, Palette] = {
    "bloomberg": Palette(
        name="bloomberg",
        description="Default. Bloomberg Terminal: orange on black with amber accents.",
        primary=_fg(208),
        secondary=_fg(214),
        value=_fg(231),
        dim=_fg(240),
        warn=_fg(196),
        good=_fg(46),
        bg=_bg(16),
    ),
    "bloomberg_classic": Palette(
        name="bloomberg_classic",
        description="Deeper, slightly desaturated take on the Bloomberg look.",
        primary=_fg(202),
        secondary=_fg(130),
        value=_fg(230),
        dim=_fg(238),
        warn=_fg(124),
        good=_fg(28),
        bg=_bg(16),
    ),
    "matrix": Palette(
        name="matrix",
        description="Matrix-style phosphor green on black.",
        primary=_fg(46),
        secondary=_fg(34),
        value=_fg(120),
        dim=_fg(238),
        warn=_fg(196),
        good=_fg(46),
        bg=_bg(16),
    ),
    "amber_crt": Palette(
        name="amber_crt",
        description="Vintage amber-monochrome CRT terminal.",
        primary=_fg(214),
        secondary=_fg(208),
        value=_fg(222),
        dim=_fg(94),
        warn=_fg(202),
        good=_fg(220),
        bg=_bg(16),
    ),
    "solarized_dark": Palette(
        name="solarized_dark",
        description="Solarized Dark: yellow accent, base0 body, blue highlights.",
        primary=_fg(136),
        secondary=_fg(33),
        value=_fg(244),
        dim=_fg(240),
        warn=_fg(160),
        good=_fg(64),
        bg=_bg(235),
    ),
    "dracula": Palette(
        name="dracula",
        description="Dracula: purple/pink on dark grey.",
        primary=_fg(141),
        secondary=_fg(212),
        value=_fg(231),
        dim=_fg(245),
        warn=_fg(203),
        good=_fg(84),
        bg=_bg(236),
    ),
    "nord": Palette(
        name="nord",
        description="Nord: cool frost-blues, low contrast.",
        primary=_fg(110),
        secondary=_fg(67),
        value=_fg(188),
        dim=_fg(239),
        warn=_fg(174),
        good=_fg(108),
        bg=_bg(236),
    ),
    "cyberpunk": Palette(
        name="cyberpunk",
        description="Neon pink primary, cyan accents, high contrast.",
        primary=_fg(201),
        secondary=_fg(51),
        value=_fg(231),
        dim=_fg(240),
        warn=_fg(196),
        good=_fg(82),
        bg=_bg(16),
    ),
    "mono": Palette(
        name="mono",
        description="Greyscale only - works on any terminal, easiest to read.",
        primary=_fg(255),
        secondary=_fg(250),
        value=_fg(231),
        dim=_fg(244),
        warn=_fg(255),
        good=_fg(255),
        bg=_bg(238),
        bold_status=True,
    ),
    "paper": Palette(
        name="paper",
        description="Inverted: dark inks for light terminals.",
        primary=_fg(19),
        secondary=_fg(60),
        value=_fg(16),
        dim=_fg(244),
        warn=_fg(88),
        good=_fg(22),
        bg=_bg(254),
        bold_status=False,
    ),
}

DEFAULT_THEME = "bloomberg"


def list_themes() -> list[Palette]:
    """Stable ordering for UIs that list/cycle themes."""

    return [THEMES[name] for name in THEMES]


def resolve_theme_name(name: str | None) -> str:
    """Validate `name` (or fall back to OQE_THEME or the default)."""

    if name is None:
        name = os.environ.get("OQE_THEME") or DEFAULT_THEME
    if name not in THEMES:
        raise ValueError(f"Unknown theme '{name}'. Available: {', '.join(THEMES)}.")
    return name


def _color_supported() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(os, "isatty"):
        return False
    try:
        return os.isatty(1)  # stdout
    except (OSError, ValueError):
        return False


def make_theme(color: bool | None = None, *, theme: str | None = None) -> Theme:
    """Build a Theme. `color=None` auto-detects, `theme=None` uses OQE_THEME
    or the package default.
    """

    if color is None:
        color = _color_supported()
    palette = THEMES[resolve_theme_name(theme)]
    return Theme(palette=palette, color=bool(color))


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
    """Tight monospaced table with right-aligned numeric cells."""

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
    rows = table.get("rows", []) or []
    # `columns` and `title` may be supplied inline (used by the comparison
    # table type, where the column set depends on which category the batch
    # ended up running). Otherwise fall back to the per-type defaults.
    columns = table.get("columns") or _TABLE_COLUMNS.get(ttype, ())
    title = table.get("title")
    if title is None:
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
    if theme.color and theme.name != "bloomberg":
        bits.append(f"THEME: {theme.name}")
    bits.append("OK" if resp.supported else "REFUSED")
    return theme.status_bar(" | ".join(bits))


def render_response(
    resp: AnswerResponse,
    *,
    color: bool | None = None,
    theme: str | None = None,
    asof: str | None = None,
    trace_id: str | None = None,
) -> str:
    """Render an AnswerResponse to a themed block of text."""

    t = make_theme(color, theme=theme)

    blocks: list[str] = []
    blocks.append(_hr(t))
    blocks.append(_status_line(t, resp, asof=asof))
    blocks.append(_hr(t))

    blocks.append(_section(t, "Summary"))
    blocks.extend(_wrap(resp.summary))

    if resp.supported:
        blocks.append("")
        blocks.append(_table_block(t, resp.table))
        blocks.append("")
        blocks.append(_section(t, "Facts"))
        blocks.append(_render_facts(t, resp.facts))
    else:
        blocks.append("")
        blocks.append(_section(t, "Reason"))
        blocks.append(t.warn(str(resp.facts.get("reason", "out of scope"))))
        if resp.suggested_rewrites:
            blocks.append("")
            blocks.append(_section(t, "Try Instead"))
            for r in resp.suggested_rewrites:
                blocks.append(f"{t.dim('>')} {t.value(r)}")

    if resp.limitations:
        blocks.append("")
        blocks.append(_section(t, "Limitations"))
        for w in resp.limitations:
            blocks.append(f"{t.dim('!')} {t.warn(w)}")

    if resp.skeptic:
        blocks.append("")
        blocks.append(_section(t, "Skeptic"))
        for line in resp.skeptic:
            # Severity is the first token in each pre-rendered line - colour
            # the whole row by that severity for at-a-glance scanning.
            head = line.split()[0] if line else ""
            if head == "CRITICAL" or head == "WARN":
                blocks.append(t.warn(line))
            else:
                blocks.append(t.dim(line))

    if trace_id:
        blocks.append("")
        blocks.append(_hr(t, "-"))
        blocks.append(t.dim(f"trace_id: {trace_id}"))

    blocks.append(_hr(t))
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Multi-ticker batch rendering. Same theme + section layout as a single
# answer; the table type is "comparison" with category-specific columns.
# ---------------------------------------------------------------------------


_COMPARISON_COLUMNS: dict[str, tuple[str, ...]] = {
    "term_structure": ("ticker", "atm_strike", "front_iv", "next_iv", "diff", "status"),
    "skew": ("ticker", "front_expiry", "atm_strike", "skew_slope", "status"),
    "greeks": ("ticker", "strike", "iv", "delta", "gamma", "theta", "vega", "status"),
    "chain": ("ticker", "spot", "contracts_count", "expiries_used", "status"),
}


def render_batch(
    batch: Any,  # oqe.agent.batch.BatchResult (avoid import cycle)
    *,
    color: bool | None = None,
    theme: str | None = None,
    asof: str | None = None,
    trace_id: str | None = None,
) -> str:
    """Render a multi-ticker batch as a single themed report."""

    from .agent.batch import comparison_rows  # local import to avoid a cycle

    t = make_theme(color, theme=theme)
    cat = batch.primary_category or "term_structure"
    columns = _COMPARISON_COLUMNS.get(cat, _COMPARISON_COLUMNS["term_structure"])
    rows = comparison_rows(batch)

    ok = sum(1 for r in rows if r.get("status") == "OK")
    total = len(rows)

    blocks: list[str] = []
    blocks.append(_hr(t))
    bits = [
        "OQE BATCH",
        f"CATEGORY: {cat.upper()}",
        f"TICKERS: {total}",
        f"OK: {ok}",
    ]
    if asof:
        bits.append(f"AS-OF: {asof}")
    if t.color and t.name != "bloomberg":
        bits.append(f"THEME: {t.name}")
    blocks.append(t.status_bar(" | ".join(bits)))
    blocks.append(_hr(t))

    blocks.append(_section(t, "Prompt"))
    blocks.extend(_wrap(batch.prompt))

    blocks.append("")
    blocks.append(
        _table_block(
            t,
            {
                "type": "comparison",
                "title": f"{cat.replace('_', ' ').upper()} COMPARISON",
                "columns": columns,
                "rows": rows,
            },
        )
    )

    # Aggregate skeptic concerns across responses (deduplicated).
    sk_lines: list[str] = []
    seen: set[str] = set()
    for row in batch.rows:
        if row.response is None:
            continue
        for line in row.response.skeptic or ():
            tagged = f"[{row.ticker}] {line}"
            if tagged in seen:
                continue
            seen.add(tagged)
            sk_lines.append(tagged)
    if sk_lines:
        blocks.append("")
        blocks.append(_section(t, "Skeptic"))
        for line in sk_lines:
            head = line.split("] ", 1)[-1].split()[0] if "] " in line else ""
            if head in ("CRITICAL", "WARN"):
                blocks.append(t.warn(line))
            else:
                blocks.append(t.dim(line))

    if trace_id:
        blocks.append("")
        blocks.append(_hr(t, "-"))
        blocks.append(t.dim(f"trace_id: {trace_id}"))

    blocks.append(_hr(t))
    return "\n".join(blocks)


def render_batch_json(batch: Any, *, asof: str | None = None, trace_id: str | None = None) -> str:
    """JSON mode for batches. One object per ticker so consumers can iterate."""

    from .agent.batch import comparison_rows  # local import to avoid a cycle

    rows = comparison_rows(batch)
    payload = {
        "prompt": batch.prompt,
        "category": batch.primary_category,
        "rows": rows,
        "asof": asof,
        "trace_id": trace_id,
    }
    return json.dumps(payload, sort_keys=True, indent=2, default=str)


def render_json(
    resp: AnswerResponse,
    *,
    asof: str | None = None,
    trace_id: str | None = None,
) -> str:
    """JSON mode: stable, color-free, machine-readable."""

    payload = {
        "supported": resp.supported,
        "category": resp.category,
        "summary": resp.summary,
        "table": resp.table,
        "facts": resp.facts,
        "numbers_used": resp.numbers_used,
        "limitations": resp.limitations,
        "suggested_rewrites": resp.suggested_rewrites,
        "skeptic": resp.skeptic,
        "asof": asof,
        "trace_id": trace_id,
    }
    return json.dumps(payload, sort_keys=True, indent=2, default=str)


# ---------------------------------------------------------------------------
# Theme cycling: lightweight per-user state at ~/.oqe/theme_cursor so
# successive `oqe ask --cycle-theme` invocations rotate through THEMES in
# definition order.
# ---------------------------------------------------------------------------


def _theme_cursor_path() -> str:
    override = os.environ.get("OQE_THEME_CURSOR")
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser("~/.oqe/theme_cursor")


def _read_cursor() -> int:
    try:
        with open(_theme_cursor_path(), encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (FileNotFoundError, ValueError):
        return 0


def _write_cursor(idx: int) -> None:
    path = _theme_cursor_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(idx))


def cycle_next_theme() -> str:
    """Advance the cursor and return the name of the theme to use this run."""

    names = list(THEMES.keys())
    idx = _read_cursor() % len(names)
    name = names[idx]
    _write_cursor((idx + 1) % len(names))
    return name
