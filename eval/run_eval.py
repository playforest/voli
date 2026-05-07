#!/usr/bin/env python3
"""Top-level eval shell. Usage:

    poetry run python eval/run_eval.py
    poetry run python eval/run_eval.py --json
    poetry run python eval/run_eval.py --theme matrix
    poetry run python eval/run_eval.py --dataset eval/prompts.jsonl

Returns 0 if every case passes, 1 otherwise.
"""

from __future__ import annotations

import sys

from voli.eval.runner import main

if __name__ == "__main__":
    sys.exit(main())
