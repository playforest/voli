# Requirements — v1 question taxonomy

## Scope: what this agent answers (v1)
This agent answers **descriptive/analytic** questions about listed equity/ETF options using Polygon data:
- Options chain slices (by expiry/right/strike/moneyness/ATM)
- Implied volatility (ATM IV, term structure comparisons)
- Skew (IV vs strike or delta buckets)
- Basic Greeks (delta/gamma/theta/vega) for contracts or slices

It does **not** provide trade instructions, recommendations, or personalized advice.

---

## Inputs the user may provide (v1)
- Ticker (required unless already set via CLI/UI context)
- Expiry selection: exact date (`2026-01-16`) or relative (`front week`, `next week`, `nearest monthly`)
- Contract selection:
  - ATM (spot-nearest strike)
  - Strike(s): exact or range
  - Right: call/put/both
  - Moneyness window: e.g., +/- 10% around spot
  - Delta bucket (optional if greeks/IV allows it): e.g., 25d
- As-of timestamp (optional): best-effort replay for time-indexed fields (quotes/trades); snapshots may be “latest only”.
  - Accepted: ISO-8601 with offset (`2025-12-20T10:30:00-05:00`) or `YYYY-MM-DD HH:MM ET`.
  - If timezone is omitted, assume ET (America/New_York) and disclose.

If a required constraint is missing, the agent will choose a deterministic default and disclose it.

### Missing ticker behavior (v1)
- If the user does **not** provide a ticker and there is **no** existing session/UI context ticker: the agent asks a single follow-up: “Which ticker?”
- If a ticker exists in session/UI context: use it and disclose “ticker inferred from context” in **Facts**.

### As-of timestamp & timezone behavior (v1)
- **Default**: use the latest available snapshot/quote at request time.
- If the user provides an **as-of** timestamp:
  - For **bid/ask** on a specific contract: prefer historical quotes endpoints when available (time-range queries).  
  - For **chain-wide snapshots / IV / greeks**: if historical snapshots are not available, return latest snapshot fields **with their actual timestamps** and disclose that as-of replay isn’t supported for those fields.
- Facts must include: the user-supplied as-of, the resolved timezone/UTC, and the actual timestamps of returned fields.

---

## Supported question categories (v1)

### A) Chain lookup
**Intent:** “Show me contracts/quotes for X slice of the chain.”

Supported examples:
1. "Show NVDA options expiring this Friday, strikes within ±5% of spot."
2. "List NVDA calls for 2026-01-16 between 120 and 150."
3. "What’s the ATM strike for QQQ next week and what are the bid/ask?"
4. "Show me the 10 closest strikes to ATM for SPY front expiry."
5. “List SPY puts for the next monthly expiry, 0.9–1.1 moneyness.”
6. “What’s the ATM call and put for QQQ next week? Include bid/ask.”
7. “Give me the 10 closest strikes to ATM for AAPL front expiry.”
8. “Show TSLA calls for 2026-01-16 between 200 and 260.”
9. “List IWM options for the nearest expiry only, both rights, ±3 strikes around ATM.”
10. “Show NVDA chain for next week, calls only, top 20 by volume.”
11. “What contracts exist for MSFT on 2026-03-20 at strike 400?”

Expected output:
- Table: contracts in slice (symbol, expiry, strike, right, bid, ask, mid, last, volume/oi if available, timestamp)

---

### B) IV / term structure
**Intent:** “Compare IV across expiries (front vs back), usually at comparable moneyness (ATM).”

Supported examples:
1. "NVDA ATM IV this week vs next week."
2. "Compare ATM IV for SPY front week, next week, and next month."
3. "Show IV term structure (ATM) for the next 6 expiries for QQQ."
4. “What’s the difference in ATM IV between nearest weekly and nearest monthly for AAPL?”
5. “Plot (or tabulate) ATM IV by expiry for TSLA out 90 days.”
6. “ATM IV for IWM: next 3 expiries, include ATM strike used.”
7. “Which expiry has the highest ATM IV for NVDA in the next month?”
8. “Front-month vs back-month ATM IV for SPY (nearest monthly vs next monthly).”

Expected output:
- Table: expiry vs ATM strike vs ATM IV (and delta/vega optional)
- Clear definition of ATM selection & as-of timestamp

---

### C) Skew
**Intent:** “How does IV vary across strikes/deltas (puts vs calls, 25d risk reversal, slope).”

Supported examples:
1. "Show NVDA IV skew for next Friday, ±10 strikes around ATM."
2. "Compute 25d put IV vs 25d call IV for SPY next month."
3. "What’s the steepest part of the skew for QQQ front expiry?"
4. “Compute risk reversal (25d put IV − 25d call IV) for QQQ nearest monthly.”
5. “What’s the skew slope across strikes for TSLA next week?”
6. “Show put vs call IV at same delta buckets for AAPL next monthly.”
7. “Identify steepest skew points (highest IV jump) around ATM for NVDA front expiry.”
8. “Tabulate IV by strike for SPY next Friday, puts and calls.”
9. “Compare skew for NVDA this week vs next week (same strike window).”

Expected output:
- Table: strike (or delta bucket) vs IV for puts/calls
- Optional derived metrics: 25d risk reversal, slope across strikes (with definition)

---

### D) Greeks
**Intent:** “Return greeks for a contract or slice; aggregate/summarize where sensible.”

Supported examples:
1. "What are the greeks of the NVDA 2026-01-16 130C?"
2. "Show delta/gamma/theta/vega for the 5 strikes around ATM for SPY this Friday."
3. "Compare ATM vega front week vs next week for QQQ."
4. “Which contract has the highest gamma near ATM for TSLA front expiry?”
5. “Delta for the 25d put and 25d call for AAPL next monthly.”
6. “Theta per day for ATM straddle SPY front week (just return component legs + totals if available).”

Expected output:
- Table: contract(s) with greeks + IV + as-of timestamp
- If aggregation used, define it (e.g., mean across slice)

---

## Defaults (must be deterministic)
### Expiry resolution rules (v1)
All relative expiry phrases resolve using **America/New_York (ET)** time.

- **Explicit date** (`YYYY-MM-DD`): use it if that expiry exists for the ticker; otherwise return the nearest available expiries and ask the user to choose (no guessing).
- **Front expiry / front week**: the earliest listed expiry with expiry **date > as-of date**, or **date == as-of date** only if as-of time is **before 16:00 ET**.
- **Next expiry / next week**: the next listed expiry after front expiry.
- **This Friday**: the first listed expiry that falls on a Friday on/after as-of (subject to the 16:00 ET rule above).
- **Next N expiries**: take the next N listed expiries strictly after as-of, sorted ascending.
- **Nearest monthly**: the earliest expiry that is the **third Friday** of its month.
- **Next monthly**: the monthly expiry after nearest monthly.
- **Out X days** (e.g., “out 90 days”): include expiries with expiry_date <= (as-of date + X days).

Facts must list:
- resolved ET as-of timestamp
- expiry dates selected and the phrase that produced them (e.g., “front week” -> 2025-12-26)

- **Spot price (“spot”)**:
  - Preferred: underlying price included in the Options Chain/Contract Snapshot response used for the answer.
  - Fallback: Stocks Single Ticker Snapshot last trade price.
  - Fallback: Stocks Last Trade (`/v2/last/trade/{stocksTicker}`).
  - Fallback: Stocks Last Quote (NBBO) mid (`/v2/last/nbbo/{stocksTicker}`).
  - Facts must include the spot price, its timestamp, and which endpoint provided it.

- **ATM strike**: nearest strike to spot; ties -> lower strike (or document tie-break rule)
- **Mid price**: (bid + ask)/2 when both exist; otherwise last; otherwise null
- **Strike window**: if user says “around ATM” with no size, default to ±5 strikes

- **Delta bucket selection (when requested)**:
  - Universe: contracts matching the chosen expiry + right (call/put), excluding rows with missing `greeks.delta`.
  - Target: calls use +0.25 for 25Δ, puts use −0.25 for 25Δ (general: calls +X, puts −X).
  - Pick: contract with delta closest to target.
  - Tie-breakers (deterministic): higher open interest, then strike closest to ATM, then lower strike.
- If no contracts in the universe have `greeks.delta`, return **Not supported for delta buckets** for that request and suggest a strike-based skew alternative.

---

## V1 outputs (minimum)
### Table schemas (v1)

**A) Chain slice table**
Required columns:
- options_symbol, expiry, strike, right
- bid, ask, mid
- last (if available), volume (if available), open_interest (if available)
- quote_timestamp (or snapshot_timestamp)

Optional columns:
- implied_volatility (if available)
- delta, gamma, theta, vega (if available)

**B) Term structure table (ATM)**
Required columns:
- expiry
- atm_strike_used
- atm_iv

Optional columns:
- atm_options_symbol_call, atm_options_symbol_put
- atm_delta_call, atm_delta_put
- atm_vega_call, atm_vega_put
- source_timestamp_per_row (if expiries come from different snapshots)

**C) Skew table**
Required columns (strike-based skew):
- expiry, right, strike
- implied_volatility
- delta (if available)
- quote/snapshot timestamp

Optional derived metrics:
- risk_reversal_25d = iv_put_25d − iv_call_25d (only when delta buckets resolvable)
- skew_slope definition (must state window + method)

**D) Greeks table**
Required columns:
- options_symbol, expiry, strike, right
- implied_volatility (if available)
- delta, gamma, theta, vega (null allowed if missing)
- quote/snapshot timestamp

Every supported answer must include:

1) **Answer summary** (1–6 lines)
2) **One primary table** relevant to the request (chain slice / term structure / skew / greeks)
3) **Facts section** containing:
   - Spot price + timestamp + source
   - Expiry dates actually used
   - Any filters/defaults chosen
   - For every numeric claim: the raw fields used (bid/ask/mid/iv/greeks) + timestamps

Optional (nice-to-have, not required for v1):
- Simple plots (term structure line, skew curve)

---

## Out of scope (v1)
- Trade execution, order placement, “what should I buy/sell”
- Portfolio/account questions, P&L, sizing, risk management
- News/earnings/event-driven forecasting or “why did IV move”
- Strategy recommendations (“best spread”, “should I hedge”, “expected move trade”)
- Backtesting or performance claims without an explicit dataset/harness
- Complex exotics, non-listed derivatives

---

## Edge-case policy (v1)
- If Polygon lacks greeks/IV for a requested contract, agent returns:
  - the closest available fields + a clear “missing data” note
  - and does NOT invent computed greeks unless computation is explicitly implemented and shown.

### Quick decision rubric
- If the prompt reduces to: “return chain/IV/skew/greeks tables for defined slice(s)” -> Supported
- If it asks: “what should I do / what will happen / why did it happen / manage my money” -> Not supported

### Refusal / redirect style (v1)
When the user asks something **Not supported (v1)**, respond with:

1) **Label**: “Not supported (v1)”
2) **Reason** (one line, cite the rule category: execution/advice/news/portfolio/strategy)
3) **Offer 1–3 supported rewrites** of their question (same ticker/timeframe if provided)
4) If they asked for trading advice: add a short disclaimer (“I can provide data, not recommendations.”)

Example rewrite patterns:
- “Should I buy/sell X?” -> “Show X option chain for [expiry] around ATM; include bid/ask/mid, IV, and greeks.”
- “Why did IV move?” -> “Compare ATM IV front vs next expiry and show skew for both expiries.”
- “What’s the best spread?” -> “Show call/put IV skew and term structure so I can evaluate spreads myself.”


