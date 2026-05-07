# Plotting

`voli ask --plot PATH` renders a category-specific PNG chart alongside the
themed text answer. Charts use the Bloomberg-ish palette (orange primary,
amber accents, dark background, dim gridlines) so they look like the CLI
output.

## Install the optional extra

Plotting needs `matplotlib`, which is not part of the lean install. Pull it
in via the `plot` extra:

```bash
poetry install -E plot
```

If you skip this, `--plot` raises a clear ImportError pointing at the same
command — the rest of the CLI is unaffected.

## Examples

=== "Term structure"

    ```bash
    poetry run voli ask --plot /tmp/term.png "NVDA ATM IV this week vs next week"
    ```

    Saves a line chart of expiry → ATM IV with each point labelled. Output
    confirms the file path:

    ```text
    ... themed answer ...
    plot: /tmp/term.png
    ```

=== "Skew"

    ```bash
    poetry run voli ask --plot /tmp/skew.png "Show NVDA IV skew next Friday"
    ```

    Plots the OLS-fit slope through the ATM strike, with spot + ATM markers
    labelled.

=== "Greeks"

    ```bash
    poetry run voli ask --plot /tmp/greeks.png "Show ATM greeks for NVDA"
    ```

    Bar chart of delta / gamma / theta / vega — green bars for non-negative
    values, red for negative.

=== "Chain"

    ```bash
    poetry run voli ask --plot /tmp/chain.png "Show NVDA options for 2026-05-16"
    ```

    Scatter of strike → mid for calls + puts, with spot marked as a vertical
    dashed line.

## Programmatic

```python
from voli.agent import answer_question
from voli.plot import plot_response

resp = answer_question("NVDA ATM IV this week vs next week")
saved = plot_response(resp, "ts.png")
print(f"chart: {saved}")
```

`plot_response` raises:

- `ImportError` when matplotlib isn't installed (with the install command in
  the message).
- `ValueError` when the response is a refusal or has no plottable data.

## Theme

PNG charts always use the Bloomberg palette regardless of the CLI `--theme`
flag — the reasoning is that a saved chart is meant to be shareable, and a
themed terminal palette doesn't translate well to a static image. If you
want a different palette in PNGs, fork `voli.plot` and tweak the colour
constants at the top of the module.

## Failure handling

If matplotlib is missing or the response can't be plotted, the CLI:

1. Renders the themed answer block as usual.
2. Prints a `warn:` line with the reason.
3. Returns the answer's exit code (the plot failure does **not** turn an
   `OK` answer into a failure).

This means scripts that combine `--plot` with `--json` keep their
machine-readable contract — the warning is printed, the chart isn't
created, the JSON is still valid.

## See also

- [Replay mode](replay.md) — re-render a saved answer in any theme/format.
- [Recipes](recipes.md) — plot in a loop for a watchlist.
