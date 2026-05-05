# Guardrails

Two writer-side enforcement rules turn the v1 contract into runtime
guarantees. Violations raise rather than emit a misleading answer.

## Rule 1 — No invented numbers

Every numeric token in `summary` must match a value in `numbers_used`
within `1e-4` tolerance. ISO dates and option symbols are stripped first
(those aren't numeric *claims* the writer is asserting).

### Implementation

```python
_NUMBER_RE       = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_ISO_DATE_RE     = re.compile(r"\d{4}-\d{2}-\d{2}")
_OPTION_SYMBOL_RE = re.compile(r"O:[A-Z]+\d+[CP]\d+")
_TOLERANCE       = 1e-4

def _allowed_numbers_in(text, allowed):
    scrubbed = _OPTION_SYMBOL_RE.sub("", _ISO_DATE_RE.sub("", text))
    return [tok for tok in _NUMBER_RE.findall(scrubbed)
            if not any(_close(float(tok), a) for a in allowed)]
```

If the resulting list is non-empty, the writer raises:

```python
class GuardrailViolation(RuntimeError): ...

raise GuardrailViolation(
    f"Writer produced unsupported numeric tokens {bad} not present in "
    f"numbers_used {allowed}; refusing to emit."
)
```

### Why

The agent's job is to summarise data the analytics layer produced. If a
number appears in the summary that isn't in `numbers_used`, either:

- the renderer rounded to a different value than the analytics did
  (legit; tolerance absorbs it), or
- the renderer pulled a number from somewhere it shouldn't (a bug — the
  guardrail catches it before users see it).

In tests, the guardrail's silence is the proof of grounding: every
end-to-end test that produces an `AnswerResponse` is implicitly an
assertion that no numeric leaked through.

## Rule 2 — Facts section mandatory

Every supported response carries:

```python
{
    "ticker": str,
    "spot":   {"value": float, "ts": str, "source": str},
    # ... category-specific fields ...
    "flags":  list[str],
}
```

The chain renderer adds `contracts_count`, `expiries_used`,
`right_filter`. Term structure adds `atm_strike`, `front_iv`, `next_iv`,
`front_expiry`, `next_expiry`, `right_used`. Skew adds `skew_slope`,
`atm_strike`, `front_expiry`. Greeks adds `atm_contract`.

Eval cases assert these via `must_have_facts_keys` so a renderer
regression that drops a required field becomes a per-case failure with
exactly that field name in the message.

## Refusal + missing-ticker shape

For not-supported prompts:

```python
{
    "supported": False,
    "category": "not_supported",
    "summary": "Not supported in scope: this question falls under '...'.",
    "table": {"type": "none", "rows": []},
    "facts": {"reason": "<reason>", "ticker": "<ticker or null>"},
    "suggested_rewrites": ["<up to 3>"],
}
```

For missing-ticker:

```python
{
    "supported": False,
    "category": "<inferred category>",  # so we know what was attempted
    "summary": "I need a ticker to answer this. ...",
    "table": {"type": "none", "rows": []},
    "facts": {"missing": "ticker"},
}
```

## Limitations propagation

Non-fatal warnings (e.g. `STALE_DATA`, `PARTIAL_DATA`) flow from
`ToolMeta.warnings` through the writer into `AnswerResponse.limitations`,
which renders as the `[ LIMITATIONS ]` block. Users decide whether to
trust the data; we just disclose what we know.

## Testing the guardrails

```bash
poetry run python -m pytest tests/test_agent_writer.py -v
```

Specifically:

- `test_finalize_passes_when_summary_only_uses_recorded_numbers`
- `test_finalize_rejects_invented_number`
- `test_iso_dates_are_not_treated_as_numeric_claims`
- `test_option_symbols_are_not_treated_as_numeric_claims`

All five pass. The rejection test asserts that the writer raises rather
than returning a violating `AnswerResponse`.

## See also

- [Orchestrator flow](orchestrator.md) — where the writer fits.
- [v1 contract doc](https://github.com/playforest/options-query-agent/blob/main/docs/v1_contract.md) — the formal guarantees.
