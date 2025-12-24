# v1 Contract — what the agent guarantees

## Guarantee 1 — Grounded numbers
- The agent will **not** invent prices/IV/greeks.
- Any numeric result is either:
  - directly returned by tools (Polygon), or
  - computed from returned fields (e.g., mid = (bid+ask)/2) with the exact formula shown.

## Guarantee 2 — Deterministic defaults
If the user under-specifies the request, the agent will:
- choose deterministic defaults (documented in `docs/requirements.md`)
- disclose them in the **Facts** section

## Guarantee 3 — Traceable “Facts”
Every answer includes a **Facts** section listing:
- as-of timestamp used (or “now”)
- spot price snapshot timestamp
- expiries used
- filters and selection rules (ATM method, strike window, delta bucket logic)
- the raw fields used for each computed metric

## Guarantee 4 — Supported vs Not supported decision
For any prompt, the agent can label it:
- **Supported (v1)** if it maps to one of: chain lookup, IV/term structur**Not supported (v1)** if it requests execution, advice, news causality, portfolio/account, or strategies

## Response shape (v1)
1. Summary
2. Primary Table (one of: Chain Slice / Term Structure / Skew / Greeks)
3. Facts
4. Limitations (only if needed)

## Explicit non-goals
- Personalized financial advice
- Trading instructions
- Predictions about future IV/price movement

## Guarantee 5 — Not supported response shape
When a prompt is **Not supported (v1)**, the agent will return:
1. A clear **Not supported (v1)** label
2. A one-line reason (execution/advice/news/portfolio/strategy)
3. 1–3 rewritten, **Supported (v1)** alternatives the user can ask instead
