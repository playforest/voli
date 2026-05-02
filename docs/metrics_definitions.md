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
2. Else if `last` is present, non-negative:
   - `mid = last` (flag: `MID_FROM_LAST`)
3. Else if only `bid` is present, non-negative:
   - `mid = bid` (flag: `MID_FROM_BID_ONLY`)
4. Else if only `ask` is present, non-negative:
   - `mid = ask` (flag: `MID_FROM_ASK_ONLY`)
5. Else:
   - `mid = None` (flag: `MID_MISSING`)

Whenever we do **not** use bid/ask midpoint, we also add `MID_NOT_FROM_BIDASK`.

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

**Function:** `select_atm_strike(spot, strikes)`

- Choose the strike `K` minimizing `abs(K - spot)`.
- **Deterministic tie-break:** if two strikes are equally close, choose the **lower** strike.
- Returns `None` if `strikes` is empty.

## Term structure comparison

**Function:** `atm_iv_term_structure(spot, contracts, greeks_by_symbol, right='call')`

Goal: compare **ATM IV** for the **front** expiry vs the **next** expiry using the **same strike**.

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