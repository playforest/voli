# LLM-as-judge eval

A second eval surface that complements the deterministic regression
harness. Where `eval/run_eval.py` runs the rule-based agent against a
synthetic registry with exact-match metrics, **`eval/run_llm_eval.py`**
runs the LLM agent against **live Polygon** and grades each answer with
a separate **judge LLM**.

## Why both?

|                        | Rule-based eval (`run_eval.py`) | LLM-as-judge eval (`run_llm_eval.py`) |
| ---------------------- | --- | --- |
| Data source            | Synthetic, deterministic | Live Polygon |
| Grading                | Exact metric match | Rubric-based, judge LLM verdict |
| Cost per run           | ~0 | ~$1-2 / 30 cases |
| Variance across runs   | None | Some (LLM nondeterminism) |
| What it catches        | Code regressions | Behaviour drift, prompt regressions, model swaps |
| When to run            | Every PR (CI gate) | Before merging behavioural changes (manual) |

Both share the same goal — *prevent silent quality drops* — but at
different layers. The rule-based eval gates code changes; the LLM eval
gates **behaviour** changes (system prompt, tool descriptions, swapping
provider/model).

## How a case runs

For each row in `eval/llm_prompts.jsonl`:

``` mermaid
flowchart LR
    P[user prompt] --> A[reference fetch<br/>direct analytics call]
    P --> B[SUT<br/>voli.llm.llm_ask]
    A --> J[judge LLM<br/>Claude Opus 4.7]
    B --> J
    J --> V{VERDICT<br/>PASS / FAIL}
```

1. **Reference** — call `compute_atm_iv_term_structure` /
   `compute_skew_slope` / `get_atm_greeks` directly (no LLM in the
   loop). Returns the ground-truth JSON.
2. **System Under Test (SUT)** — run `voli.llm.llm_ask(prompt)` with
   the default Claude Sonnet 4.6 (or whatever you set) driving the
   seven Voli tools. Capture the answer text.
3. **Judge** — give a stronger model (default Claude Opus 4.7) the
   prompt + reference + SUT answer + per-row tolerance hint, ask for
   `VERDICT: PASS` or `VERDICT: FAIL` with a one-sentence reason.

The aggregate metric is pass-rate across all 30 cases, broken down by
category.

## Run it

### Prereqs

```bash
poetry install -E llm        # SUT + judge providers
# .env contains POLYGON_API_KEY + ANTHROPIC_API_KEY (and/or OPENAI_API_KEY)
```

### Full run (~$1-2)

```bash
poetry run python eval/run_llm_eval.py
```

### Dry run (5 cases, ~$0.20)

```bash
poetry run python eval/run_llm_eval.py --limit 5
```

### Pick providers / models

```bash
# OpenAI as the SUT, Claude Opus as the judge (the default)
poetry run python eval/run_llm_eval.py \
    --sut-provider openai --sut-model gpt-4.1-mini

# Same provider for both, smaller judge for cheaper iterations
poetry run python eval/run_llm_eval.py \
    --judge-model claude-sonnet-4-6
```

### JSON output for tooling / dashboards

```bash
poetry run python eval/run_llm_eval.py --json > /tmp/llm_eval.json
```

Per-case payloads include `verdict`, `reasoning`, `tool_calls`,
`elapsed_seconds`, the SUT's full answer, and the reference JSON.

## Sample output

```text
================================================================================
 VOLI LLM EVAL | 30 cases | 27 pass | 2 fail | 1 error
================================================================================
[ RESULTS ]
PASS  ts_001    term_structure    4.2s  What's NVDA's ATM IV for this Friday vs ...
PASS  ts_002    term_structure    3.8s  Compare ATM IV for SPY front week vs ne...
FAIL  ts_005    term_structure    3.1s  TSLA front-week vs next-week ATM IV?
        -> SUT reported 0.62 next-week IV but reference is 0.55 (delta > 1 vol pt)
PASS  sk_001    skew              4.0s  What's NVDA's skew slope for the front ...
ERROR sk_009    skew              0.4s  Polygon HTTP 429: rate limit exceeded
... (24 more) ...

[ BY CATEGORY ]
greeks                10/10
skew                  9/10
term_structure        8/10
================================================================================
```

## Cost ballpark

For a 30-case run with the defaults (SUT = Sonnet 4.6, judge = Opus 4.7):

| Component | Estimate |
| --- | --- |
| SUT input  | ~150-300k tokens (prompts + tool results) |
| SUT output | ~30-60k tokens (answers) |
| Judge input  | ~30-60k tokens (prompt + reference + SUT answer) |
| Judge output | ~1.5-3k tokens (verdicts + reasoning) |
| **Total**     | **~$1-2 per full run** |

The `--limit N` flag is your friend for dry-runs while iterating on the
system prompt.

## Adding cases

Append a JSON line to `eval/llm_prompts.jsonl`:

```json
{
  "id": "ts_011",
  "category": "term_structure",
  "prompt": "What's IWM's ATM IV term structure?",
  "reference_tool": "compute_atm_iv_term_structure",
  "reference_args": {"ticker": "IWM"},
  "rubric_hint": "Front + next IV within 0.5 vol points; ATM strike within $1."
}
```

Categories: `term_structure`, `skew`, `greeks`. The reference_tool must
be one of `compute_atm_iv_term_structure` / `compute_skew_slope` /
`get_atm_greeks` — the runner refuses unknown tools (test enforced).

## Why these aren't in the deterministic eval

The eval in `eval/prompts.jsonl` gates **code regressions**: same
prompt, same synthetic data, same exact metric. That's a hard pass/fail
that runs in <1 second offline.

This new dataset gates **behaviour regressions** that the deterministic
eval can't catch:

- Did the LLM hallucinate a number not present in the reference?
- Did it phrase the answer in a way that misrepresents the data?
- Did a model swap (e.g. Sonnet 4.6 → 5.0) silently degrade quality?

Both layers running clean is much stronger evidence than either alone.

## See also

- [Eval harness (rule-based)](harness.md) — the deterministic counterpart
- [LLM-driven agent](../examples/llm-ask.md) — the SUT being graded
- [Dataset format](dataset-format.md) — the rule-based eval's JSONL shape (different schema)
