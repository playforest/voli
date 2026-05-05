# Themes

Twelve bundled palettes. The visual layout (status bar / sections / tables /
facts) is fixed; only the colour mix changes.

## Browse them

```bash
poetry run oqe themes list
```

Prints every theme with its description, each row rendered in the theme it
names — fastest way to pick one.

## Preview an answer

```bash
# One theme
poetry run oqe themes preview --theme dracula

# All twelve side-by-side
poetry run oqe themes preview --all
```

## The catalogue

| Name | Vibe |
| --- | --- |
| `bloomberg` (default) | Orange + amber on black, classic Bloomberg Terminal. |
| `bloomberg_classic` | Deeper, slightly desaturated Bloomberg variant. |
| `matrix` | Phosphor green on black. |
| `amber_crt` | Vintage amber-monochrome CRT. |
| `solarized_dark` | Yellow accent, base0 body, blue highlights. |
| `dracula` | Purple + pink on dark grey. |
| `nord` | Cool frost-blues, low contrast. |
| `cyberpunk` | Neon pink primary, cyan accents. |
| `mono` | Greyscale only — works on any terminal. |
| `paper` | Inverted, dark inks for light terminals. |
| `sepia` | Aged-photograph: warm browns + cream on near-black. |
| `material` | MkDocs Material dark code: pink keywords, purple modules, soft green strings on dark blue-grey. Same vibe as the docs site's code blocks. |

## Pick one for an `ask`

=== "Per invocation"

    ```bash
    poetry run oqe ask --theme matrix "NVDA ATM IV this week vs next week"
    ```

=== "Whole session"

    ```bash
    export OQE_THEME=nord
    poetry run oqe ask "Show NVDA IV skew next Friday"
    ```

=== "Persistent (config.yaml)"

    ```yaml
    default_theme: cyberpunk
    ```

## Cycling through themes

`--cycle-theme` rotates to the next theme each invocation. Useful for a quick
A/B in a real workflow.

```bash
poetry run oqe ask --cycle-theme "NVDA ATM IV this week"   # bloomberg
poetry run oqe ask --cycle-theme "NVDA ATM IV this week"   # bloomberg_classic
poetry run oqe ask --cycle-theme "NVDA ATM IV this week"   # matrix
# ... wraps after the 12th call.
```

The cursor lives at `~/.oqe/theme_cursor`. Override the path with
`OQE_THEME_CURSOR=/tmp/my_cursor` (mostly for tests).

## Disable colour

=== "Per command"

    ```bash
    poetry run oqe ask --no-color "NVDA ATM IV this week"
    ```

=== "Per shell session"

    ```bash
    export NO_COLOR=1
    ```

=== "Pipes"

    Colour auto-disables when stdout isn't a TTY:

    ```bash
    poetry run oqe ask "..." | head -20    # always plain
    poetry run oqe ask "..." > out.txt     # always plain
    ```

## What's actually colour-coded

| Element | Style |
| --- | --- |
| Status bar | bold + theme `primary` colour over `bg` background |
| `[ SECTION ]` headers | bold + `primary` |
| Facts keys / column headers | bold + `secondary` |
| Body values, table cells | plain `value` |
| Borders, dividers, separators | dim `dim` |
| Refusal label, errors, limitations | bold `warn` |
| OK marker, positive deltas | bold `good` |

## Defining a custom theme

The bundled palettes live in `src/oqe/cli_render.py`. Add a new entry to
the `THEMES` dict and you can name it on the CLI immediately:

```python
THEMES["my_theme"] = Palette(
    name="my_theme",
    description="...",
    primary=_fg(214),    # ANSI 256-color codes
    secondary=_fg(250),
    value=_fg(231),
    dim=_fg(240),
    warn=_fg(196),
    good=_fg(46),
    bg=_bg(16),
)
```

Run `poetry run oqe themes preview --theme my_theme` to verify.

## Next

- [CLI overview](overview.md) — every flag in detail
- [Troubleshooting](troubleshooting.md) — fixes for common issues
