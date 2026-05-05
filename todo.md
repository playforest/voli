# Options Chain Q&A Agent — todo.md

This roadmap will guide us through creating an **Options Chain Q&A agent**. Each numbered **Part** gets its own ChatGPT Project chat so we can work interactively—one bite-sized step at a time.

## Project goal
Build an agent that can answer natural-language questions about an underlying’s options (chain, IV, term structure, skew, basic Greeks), **grounded in Polygon data**, with transparent calculations and repeatable results.

Also: make the repo and docs **friendly for learning agents/LLMs**—briefly explain what an *orchestrator* is (the control layer that routes requests, calls tools, and assembles results) and its typical parts (planner → executor → writer, state, tool schemas, traces/guardrails) as we implement them.

## Core principles
- **No hallucinated numbers**: every numeric claim must come from tool outputs or derived computations shown in a “Facts” section.
- **Deterministic execution**: the same question + same timestamp window should yield the same answer (within market data changes).
- **Traceable**: store tool calls, parameters, and key returned fields.
- **Safe**: educational/analytic framing; no trade instructions or personalized financial advice.

## Suggested stack (feel free to swap)
- Language: Python
- Agent/orchestration: LangGraph *or* a small custom orchestrator (planner → executor → writer)
- Data: Polygon REST (options chain/quotes/greeks as available), local cache (SQLite or DuckDB)
- CLI first; optional web UI later

---

## Part 1 — Requirements & question taxonomy
**Goal:** Decide exactly what questions we support in v1.

- Collect 20–30 example prompts (including your NVDA “ATM IV this week vs next week” style).
- Classify them into categories:
  - Chain lookup (by expiry/strike/ATM)
  - IV/term structure (front vs back)
  - Skew (put vs call, delta buckets)
  - Greeks (delta/gamma/theta/vega) per contract or slice
- Define v1 outputs (what tables/plots we must show).
- Write a short “Out of scope” list (e.g., execution, account/portfolio, news).

### 1.5 Repo and dev environment
- Create repo + basic structure (`/api`, `/agent`, `/ui`, `/infra`)
- Add formatting/linting (ruff/black, eslint if JS)
- Add pre-commit hooks
- Add Docker/devcontainer (optional)
- Add `.env.example`


**Deliverables**
- [*] `docs/requirements.md` (supported question types + examples)
- [*] `docs/v1_contract.md` (what the agent guarantees to return)
- [*] `prompt_corpus_v1.jsonl` (extract examples into prompt corpus file for later test)

**Done when**
- You can point at a prompt and say “supported” or “not supported” without debate.

---

## Part 2 — Data model & tool schemas
**Goal:** Create the exact tool interfaces the agent will call.

- Define normalized internal objects:
  - `UnderlyingSnapshot(spot, ts, source)`
  - `OptionContract(symbol, expiry, strike, right, multiplier, ...)`
  - `OptionQuote(bid, ask, last, mid, ts)`
  - `OptionGreeks(delta, gamma, theta, vega, iv, ts)`
- Decide minimum inputs for each tool and required fields in outputs.
- Draft JSON schemas (strict).

**Tools (v1)**
- [*] `get_underlying_snapshot(ticker, asof=None)`
- [*] `list_option_contracts(ticker, expiry=None, right=None, strike_min=None, strike_max=None, limit=...)`
- [*] `get_option_quotes(option_symbols, asof=None)`
- [*] `get_option_greeks(option_symbols, asof=None)` (or compute if Polygon doesn’t supply)
- [*] `get_option_oi(option_symbols)` (optional)

**Deliverables**
- [*] `schemas/tools.json`
- [*] `docs/tool_contracts.md`

**Done when**
- A tool executor can be written from the schemas without guessing.

---

## Part 3 — Polygon integration layer (thin, testable)
**Goal:** Build a clean client that talks to Polygon and returns typed objects.

- Implement `polygon_client.py` with:
  - Authentication handling
  - Rate limit/backoff strategy
  - Error taxonomy (network vs 4xx vs 5xx vs “no data”)
- Implement each v1 tool as a function calling the client.
- Add unit tests that mock Polygon responses.

**Deliverables**
- [*] `src/polygon_client.py`
- [*] `src/tools/polygon_tools.py`
- [*] `tests/test_polygon_tools.py`

**Done when**
- Tools run in isolation and return consistent, validated objects.

---

## Part 4 — Caching & “as-of” semantics
**Goal:** Make results repeatable and fast.

- Choose cache store (SQLite/DuckDB).
- Decide cache keys (ticker, expiry, tool name, asof window).
- Implement:
  - Time-based cache expiry (quotes short TTL; contracts longer)
  - Optional “asof” parameter to replay a past snapshot (best-effort)
- Add a “trace id” per question run.

**Deliverables**
- [*] `src/oqe/cache.py`
- [*] `src/oqe/run_trace.py` (stores tool calls + outputs summary)
- [*] `docs/reproducibility.md`
- [*] `docs/notebooks/part4_replay_and_trace_walkthrough.ipynb`

**Done when**
- You can rerun the same prompt and see the same trace + same computed metrics (when using cached/asof).

---

## Part 5 — Computation library (IV, ATM selection, skew metrics)
**Goal:** Centralize all finance math so the agent doesn’t “wing it”.

- Implement:
  - ATM selection (spot-based, nearest strike, configurable)
  - Mid price calculation (bid/ask)
  - Term structure comparison (front week vs next week, same moneyness)
  - Skew metrics (e.g., 25d put vs 25d call IV, or slope across strikes)
- Decide how to handle missing bid/ask or wide spreads (filters).

**Deliverables**
- [*] `src/analytics/iv_metrics.py` (lives at `src/oqe/analytics/iv_metrics.py`)
- [*] `src/analytics/skew.py` (lives at `src/oqe/analytics/skew.py`)
- [*] `src/analytics/greeks.py` (lives at `src/oqe/analytics/greeks.py`)
- [*] `docs/metrics_definitions.md`

**Done when**
- Given a chain snapshot, you can compute and print all metrics without the LLM.

---

## Part 6 — Orchestration: planner → executor → writer
**Goal:** The agent reliably decides which tools to call and in what order.

- Build a simple state machine:
  1) Parse intent + constraints (ticker, expiries, ATM/delta bucket, etc.)
  2) Create a tool plan (JSON)
  3) Execute tools (with retries/caching)
  4) Compute metrics
  5) Generate final answer grounded in “Facts”
- Enforce guardrails:
  - Disallow the writer from inventing fields not present in facts
  - Require a “Numbers used” section

**Deliverables**
- [*] `src/agent/state.py` (lives at `src/oqe/agent/state.py`)
- [*] `src/agent/planner.py` (lives at `src/oqe/agent/planner.py`)
- [*] `src/agent/executor.py` (lives at `src/oqe/agent/executor.py`)
- [*] `src/agent/writer.py` (lives at `src/oqe/agent/writer.py`)
- [*] `docs/agent_flow.md`

**Done when**
- [*] The agent answers 10+ sample prompts with correct tool usage and no made-up numbers.
  (See `tests/test_agent_end_to_end.py` — 12 prompts run through planner→executor→writer with a stubbed ToolRegistry; the writer's no-invented-numbers guardrail enforces the second clause.)

---

## Part 7 — UX: CLI with structured output
**Goal:** Make it pleasant to use and easy to debug.

- Build `cli.py`:
  - `ask "prompt here" --ticker NVDA`
  - `--asof`, `--json`, `--trace`
- Output format (v1):
  - Short narrative
  - 1–2 tables (ATM IV, term structure, steepest skew points)
  - Facts section (raw values + timestamps)

**Deliverables**
- [ ] `src/cli.py`
- [ ] `docs/usage.md`

**Done when**
- You can run it end-to-end locally and understand any failure quickly.

---

## Part 8 — Evaluation harness (golden tests)
**Goal:** Measure whether the agent is improving.

- Create a dataset:
  - prompts + expected tool plan + sanity checks (e.g., “should mention expiry dates”, “should show ATM strike”)
- Add regression tests:
  - Compare computed metrics within tolerances
  - Ensure “Facts” contains required fields
- Track failures by category.

**Deliverables**
- [ ] `eval/prompts.jsonl`
- [ ] `eval/run_eval.py`
- [ ] `tests/test_end_to_end.py`

**Done when**
- You can refactor the agent and know if you broke behavior.

---

## Part 9 — Hardening & packaging
**Goal:** Make it shippable.

- Add config system (`.env`, `config.yaml`)
- Logging (structured)
- Add docker/devcontainer (optional)
- Basic documentation + troubleshooting
- License + repo hygiene

**Deliverables**
- [ ] `README.md`
- [ ] `config.example.yaml`
- [ ] `docker/` (optional)

**Done when**
- A new machine can run it with minimal setup friction.

---

## Part 10 — Optional upgrades
Pick one or two:
- Simple web UI (FastAPI + minimal frontend)
- Plotting (IV term structure chart, skew chart)
- Multi-ticker batching
- “Skeptic” sub-agent to sanity-check spreads, stale quotes, missing data
- Replay mode using stored traces
