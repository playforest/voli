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
- [*] `src/voli/cache.py`
- [*] `src/voli/run_trace.py` (stores tool calls + outputs summary)
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
- [*] `src/analytics/iv_metrics.py` (lives at `src/voli/analytics/iv_metrics.py`)
- [*] `src/analytics/skew.py` (lives at `src/voli/analytics/skew.py`)
- [*] `src/analytics/greeks.py` (lives at `src/voli/analytics/greeks.py`)
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
- [*] `src/agent/state.py` (lives at `src/voli/agent/state.py`)
- [*] `src/agent/planner.py` (lives at `src/voli/agent/planner.py`)
- [*] `src/agent/executor.py` (lives at `src/voli/agent/executor.py`)
- [*] `src/agent/writer.py` (lives at `src/voli/agent/writer.py`)
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
- [*] `src/cli.py` (lives at `src/voli/cli.py` + `src/voli/cli_render.py`)
- [*] `docs/usage.md`

**Done when**
- [*] You can run it end-to-end locally and understand any failure quickly.
  (`poetry run voli ask "<prompt>"` works for any v1 category; refusal path returns exit 3; Bloomberg-style ANSI theme with auto NO_COLOR detection; --json and --trace supported.)

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
- [*] `eval/prompts.jsonl` (20 cases across all 4 supported categories + refusal + missing-ticker)
- [*] `eval/run_eval.py` (themed report; non-zero exit on any failure)
- [*] `tests/test_end_to_end.py` (parametrised pytest backed by the same dataset)

**Done when**
- [*] You can refactor the agent and know if you broke behavior.
  Verified by sabotaging the writer (dropping `atm_strike` from facts): the
  harness reported 4 failed cases with per-check detail. Reverted, 20/20 pass.

---

## Part 9 — Hardening & packaging
**Goal:** Make it shippable.

- Add config system (`.env`, `config.yaml`)
- Logging (structured)
- Add docker/devcontainer (optional)
- Basic documentation + troubleshooting
- License + repo hygiene

**Deliverables**
- [*] `README.md` (polished landing page with quickstart, sample output, project structure)
- [*] `config.example.yaml` (every supported key, documented inline)
- [*] `docker/` (Dockerfile + docker-compose.yml + .devcontainer/devcontainer.json)
- [*] Bonus: `src/voli/config.py` (YAML loader with env-precedence), `src/voli/logging.py` (themed/JSON structured logging)
- [*] Bonus: 27-page MkDocs Material doc site (`docs/`, `mkdocs.yml`)

**Done when**
- [*] A new machine can run it with minimal setup friction.
  Docker compose, devcontainer, polished README, env-driven config, and a
  full doc site (`poetry run mkdocs serve` -> http://127.0.0.1:8000).

---

## Part 10 — Optional upgrades
Pick one or two:
- [ ] Simple web UI (FastAPI + minimal frontend)
- [*] Plotting (IV term structure chart, skew chart, greeks bars, chain scatter; `voli ask --plot PATH`, optional `matplotlib` extra)
- [*] Multi-ticker batching (`voli ask-many --tickers ...`, comparison table per category)
- [*] "Skeptic" sub-agent to sanity-check spreads, stale quotes, missing data (`--skeptic` flag, `[ SKEPTIC ]` block)
- [*] Replay mode using stored traces (`voli ask --trace` writes `<id>.response.json`; `voli replay <id>` re-renders without a Polygon round-trip)




evals:
- are there more 'live' tests i can run after i've added my token where the test is something like: i make a       
  direct call to polygon api to get some option related data, then i ask an llm (using my tool) to fetch similar   
  data, and tehn have an llm grade to see if the llm result matches with direct api result? and repeat this test   
  for like 30 other cases. does this type of test have a name? is it eval?                                         
                                                                                                                   
⏺ Yes — this is eval, and specifically LLM-as-judge eval (also called "model-graded eval" or "rubric-based eval"). 
  It's the standard pattern for grading agentic / open-ended LLM outputs where strict string equality doesn't work.
                                                                                                                   
  What you're describing, broken down
                                                                                                                   
  There are three roles in the loop:                              

  1. Reference / ground truth — fetched independently. In your case, calling Polygon directly with no LLM in the   
  loop. Sometimes called the "oracle".
  2. System under test (SUT) — your LLM agent answering the question via Voli tools.                                
  3. Judge — a separate LLM call that compares the SUT's answer to the reference and emits a pass/fail + reasoning.
                                                                                                                   
  The aggregate metric is "pass rate" across N cases, often broken down by category. Industry-standard frameworks  
  for this include Inspect (UK AISI), Promptfoo, Braintrust, LangSmith Evals, OpenAI Evals, and DeepEval.          
                                                                                                                   
  How it'd fit Voli                                                

  You already have eval/run_eval.py that scores the rule-based agent against the synthetic registry with           
  exact-match metrics. What you're asking for is a different axis on the same eval surface:
                                                                                                                   
  ┌──────────────────────┬──────────────────────────┬──────────────────────────────────────────────────┐           
  │                      │ Rule-based agent (today) │                 LLM agent (new)                  │
  ├──────────────────────┼──────────────────────────┼──────────────────────────────────────────────────┤           
  │ Data source          │ Synthetic, deterministic │ Live Polygon                                     │
  ├──────────────────────┼──────────────────────────┼──────────────────────────────────────────────────┤           
  │ Grading              │ Exact metric match       │ LLM-as-judge rubric                              │           
  ├──────────────────────┼──────────────────────────┼──────────────────────────────────────────────────┤           
  │ Cost per run         │ ~0                       │ ~$0.50-$2.00 / 30 cases                          │           
  ├──────────────────────┼──────────────────────────┼──────────────────────────────────────────────────┤           
  │ Variance across runs │ None                     │ Some (LLM nondeterminism)                        │
  ├──────────────────────┼──────────────────────────┼──────────────────────────────────────────────────┤           
  │ What it catches      │ Code regressions         │ Behaviour drift, prompt regressions, model swaps │
  └──────────────────────┴──────────────────────────┴──────────────────────────────────────────────────┘           
                                                                  
  So both eval styles complement each other — you keep the deterministic harness as the regression gate (every PR),
   and you'd run the LLM eval less often (when changing the system prompt, tool descriptions, or model).
                                                                                                                   
  Concrete design for Voli                                         

  A new eval/llm_run_eval.py that, for each row in eval/llm_prompts.jsonl:                                         
  
  1. Fetches reference data via direct Polygon calls (we'd reuse voli.tools.polygon_tools.* directly — no LLM).     
  2. Runs the SUT via voli.llm.llm_ask against live Polygon.       
  3. Asks the judge (a stronger model — defaulting to Claude Opus 4.7 or GPT-5) to grade with a rubric like:       
  ▎ Given the reference data and the SUT's answer, did the answer correctly state every numeric value within       
  reasonable rounding? Did it identify the right ATM strike / expiry / direction? Reply PASS or FAIL and one       
  sentence of reasoning.                                                                                           
  4. Aggregates pass rate, breaks down by category, surfaces failed cases with the judge's reasoning.              
                                                                                                                   
  eval/llm_prompts.jsonl shape:                                                                                    
                                                                                                                   
  {                                                                                                                
    "id": "lc_001",                                               
    "prompt": "What's NVDA's ATM IV for this Friday vs next?",
    "category": "term_structure",                                                                                  
    "reference_tool": "compute_atm_iv_term_structure",
    "reference_args": {"ticker": "NVDA"},                                                                          
    "rubric_hint": "Front IV, next IV, and ATM strike should match the reference within 0.5 vol points / $1."
  }                                                                                                                
                                                                  
  Effort estimate                                                                                                  
                                                                  
  - ~150 LOC for the runner + judge prompt + rubric                                                                
  - Reuses existing voli.llm.provider.make_provider for the judge call
  - Reuses existing themed report renderer                                                                         
  - Could ship in one commit                                      
                                                                                                                   
  My recommendation                                               
                                                                                                                   
  Start with 15-20 prompts across the 4 categories (chain, term structure, skew, greeks). Use Anthropic's Claude   
  Sonnet 4.6 for the SUT (cheap, fast) and Claude Opus 4.7 for the judge (better at rubric grading). Run it
  manually before merging behavioural changes; don't put it in CI (cost + variance would bake noise into the gate).
                                                                  
  Want me to build it? It's roughly the same scope as Stage A was. If yes, two quick choices:                      
  
  1. Provider for the judge: Claude Opus 4.7 (recommended), GPT-5, or whatever you prefer?                         
  2. Initial prompt count: 15, 20, or 30?  