"""Evaluation harness package.

Public surface:
  * `synth_market.make_registry()` - builds a deterministic offline ToolRegistry
    that mirrors Polygon response shapes.
  * `runner.run_eval()` and `runner.main()` - load a JSONL dataset of test
    cases, score each one against `answer_question`, and emit a themed report.
"""

from .runner import run_eval

__all__ = ["run_eval"]
