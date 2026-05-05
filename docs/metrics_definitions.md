# Part 5 — Metrics definitions (v1)

This document defines the **exact**, deterministic rules used by `oqe.analytics`.

## Conventions

- **Right**: normalized to `call` or `put`.
  - Accepted inputs: `call`/`put`, `C`/`P`, `c`/`p`.
- **Expiry**: treated as a `date` (`YYYY-MM-DD`). If a timestamp is provided, we use its `.date()`.
- **Flags**: computations return `None` values when data is missing/invalid, and include one or more string flags.
  - The orchestrator can surface this as `PARTIAL_DATA`.

## Mid price

**Function:** `mid_price(bid, ask, last=None)`

Rule order:
1. If `bid` and `ask` are present, non-negative, and `ask >= bid`:
   - `mid = (bid + ask) / 2`
   - flags: none on the happy path
2. Else if `last` is present, non-negative:
   - `mid = last` (flags: `MID_NOT_FROM_BIDASK`, `MID_FROM_LAST`)
3. Else if `bid` is present and non-negative:
   - `mid = bid` (flags: `MID_NOT_FROM_BIDASK`, `MID_FROM_BID_ONLY`)
4. Else if `ask` is present and non-negative:
   - `mid = ask` (flags: `MID_NOT_FROM_BIDASK`, `MID_FROM_ASK_ONLY`)
5. Else:
   - `mid = None` (flags: `MID_MISSING` plus the relevant `MISSING_BID` / `MISSING_ASK` / `MISSING_LAST`)

### Diagnostic flags propagated into the result

Earlier checks add diagnostic flags that are preserved into whichever branch ultimately returns:

- `NEGATIVE_BID` — bid was provided but negative.
- `NEGATIVE_ASK` — ask was provided but negative.
- `INVALID_BID_ASK` — both sides present but the pair was unusable (negative or `ask < bid`).
- `NEGATIVE_LAST` — last was provided but negative (and therefore not used).

Example: `mid_price(bid=5, ask=3, last=4)` returns `value=4.0` with flags `("INVALID_BID_ASK", "MID_NOT_FROM_BIDASK", "MID_FROM_LAST")` — the orchestrator can see *why* we fell back, not just that we did.

## Relative spread

**Function:** `relative_spread(bid, ask)`

- `mid = (bid + ask) / 2`
- `relative_spread = (ask - bid) / mid`

Returns `None` if:
- `bid` or `ask` missing
- negative quotes
- `ask < bid`
- `mid == 0`

## Spread-too-wide filter

**Function:** `is_spread_too_wide(bid, ask, max_relative_spread=0.20)`

- Computes `relative_spread`.
- Returns `True` if `relative_spread > max_relative_spread`.
- Returns `None` with flags if spread cannot be computed.

## ATM strike selection

**Function:** `select_atm_strike(spot, strikes, *, tie_break="lower")`

- Choose the strike `K` minimizing `abs(K - spot)`.
- **Deterministic tie-break** (configurable):
  - `tie_break="lower"` (default) — choose the lower strike when two are equidistant.
  - `tie_break="higher"` — choose the higher strike.
  - any other value returns `None` with flag `INVALID_TIE_BREAK`.
- Returns `None` with flag `NO_STRIKES` if `strikes` is empty, or `MISSING_SPOT` if spot is `None`.

The `tie_break` parameter is plumbed through `atm_iv_term_structure`, `atm_greeks_for_expiry`, and `compute_v1_metrics_bundle`.

## Term structure comparison

**Function:** `atm_iv_term_structure(spot, contracts, greeks_by_symbol, right='call')`

Goal: compare **ATM IV** for the **front** expiry vs the **next** expiry using the **same strike**.

> **v1 moneyness rule.** Term structure compares the two expiries at the **same strike**, not at strictly the same moneyness (e.g., same `K/S` or same delta). This is a deterministic approximation that holds well when the two expiries are close in time and spot has not drifted materially. A future v2 may compare at constant moneyness or constant delta.

Algorithm:
1. Filter to contracts matching `right`.
2. Identify the two earliest expiries: `front`, `next`.
3. Build the strike grid for `front` and choose `atm_strike` using `select_atm_strike(spot, strikes_front)`.
4. For each of `front` and `next`:
   - select the contract with `strike == atm_strike` (deterministic ordering by option symbol)
   - look up `iv` from `greeks_by_symbol[option_symbol].iv`

Missing or absent `iv` yields `None` and flags like `MISSING_GREEKS`, `MISSING_IV`, `CONTRACT_NOT_FOUND`.

## Skew curve

**Function:** `strike_iv_pairs(contracts, greeks_by_symbol, expiry, right)`

- For the given `expiry` and `right`, return sorted `(strike, iv)` pairs.
- Contracts with missing greeks or missing `iv` are **skipped** and flagged.
- Duplicate strikes are deduplicated deterministically (first seen by strike+symbol ordering), flagged `DUPLICATE_STRIKE`.

## Skew slope

**Function:** `skew_slope_ols(pairs)`

- Computes OLS slope for `iv ~ strike`:
  - `slope = cov(strike, iv) / var(strike)`
- Returns `None` if fewer than 2 points or if all strikes are identical.

## Delta skew

**Function:** `delta_skew(contracts, greeks_by_symbol, expiry, target_delta=0.25, ...)`

The classic options-market skew read: **the put IV at a target delta minus the call IV at the same target delta**, for a single expiry.

- Convention: a **positive** value means puts trade richer than calls (typical equity skew).
- Default `target_delta = 0.25` reproduces the standard "25-delta risk reversal" measure.

Algorithm:
1. Take `target = abs(target_delta)`.
2. For the given expiry:
   - find the **put** whose `delta` is closest to `-target`,
   - find the **call** whose `delta` is closest to `+target`.
3. Return `put_iv - call_iv`.

Tie-break (deterministic): smallest delta-distance wins; on equal distance, lower strike, then lower option symbol.

Skipped/flagged when:
- `MISSING_DELTA`, `MISSING_IV`, `MISSING_GREEKS`, `MISSING_OPTION_SYMBOL` — drop the candidate and flag.
- `MISSING_PUT_LEG` / `MISSING_CALL_LEG` — no usable contract was found for that side; result is `None`.

Spread filtering (`quotes_by_symbol` + `max_relative_spread` + `exclude_if_spread_unknown`) applies symmetrically to both legs.

## Optional spread filtering (recommended)

Some markets/strikes are effectively unusable because quotes are extremely wide or missing a side. In v1 we keep computations deterministic by optionally filtering out those strikes/points using a **relative spread** rule.

### Relative spread

When both bid and ask are present and valid:

- `mid = (bid + ask) / 2`
- `relative_spread = (ask - bid) / mid`

A quote is considered **too wide** when:

- `relative_spread > max_relative_spread` (default threshold used in examples/tests is `0.20`)

### Where spread filtering can be applied

These analytics functions accept optional quote spread filtering:

- `strike_iv_pairs(..., quotes_by_symbol, max_relative_spread, exclude_if_spread_unknown)`
- `skew_slope(..., quotes_by_symbol, max_relative_spread, exclude_if_spread_unknown)`
- `delta_skew(..., quotes_by_symbol, max_relative_spread, exclude_if_spread_unknown)`
- `atm_iv_term_structure(..., quotes_by_symbol, max_relative_spread, exclude_if_spread_unknown)`
- `compute_v1_metrics_bundle(..., quotes_by_symbol, max_relative_spread, exclude_if_spread_unknown)`

### Deterministic behavior

If `quotes_by_symbol` and `max_relative_spread` are provided:

- **Wide spread:** the contract/point is excluded and a `FILTERED_WIDE_SPREAD` flag is added.
- **Spread unknown:** if bid/ask is missing (so spread cannot be computed), behavior depends on:
  - `exclude_if_spread_unknown=True` (default): exclude and add `SPREAD_UNKNOWN` plus the underlying quote flags (e.g., `MISSING_BID`, `MISSING_ASK`).
  - `exclude_if_spread_unknown=False`: keep the point and still surface `SPREAD_UNKNOWN` flags.

If spread filtering is not enabled (no quotes map or no threshold), all contracts are considered eligible and the computations fall back to the usual missing-data rules.

### Important notes

- Spread filtering is **purely a data-quality filter**. It never fabricates IVs or prices.
- When filtering removes too many points, you may see `INSUFFICIENT_POINTS` for skew slope.
- Term structure still returns the front/next expiries and chosen ATM strike whenever possible; missing points become `None` with flags.