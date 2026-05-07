#!/usr/bin/env python3
"""Top-level LLM-as-judge eval shell. Usage:

    poetry run python eval/run_llm_eval.py
    poetry run python eval/run_llm_eval.py --limit 5         # dry-run
    poetry run python eval/run_llm_eval.py --json
    poetry run python eval/run_llm_eval.py --theme matrix
    poetry run python eval/run_llm_eval.py \
        --sut-provider openai --sut-model gpt-4.1-mini \
        --judge-provider anthropic --judge-model claude-opus-4-7

This is a *live* eval: it calls Polygon (for both reference data and the
SUT's tool calls) AND calls two LLM providers (the SUT and the judge).
Cost ballpark: $1-2 for a full 30-case run with the default models.
Use --limit N for dry runs.

Returns 0 if every case passes, 1 otherwise.
"""

from __future__ import annotations

import sys

from voli.eval.llm_runner import main

if __name__ == "__main__":
    sys.exit(main())
