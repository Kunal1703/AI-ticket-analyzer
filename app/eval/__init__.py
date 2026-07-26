"""Analysis-quality evaluation harness (M5.1). See ``app/eval/harness.py``."""

from app.eval.golden import GOLDEN_CASES
from app.eval.harness import (
    CaseOutcome,
    EvalCase,
    EvalReport,
    meets_threshold,
    run_eval,
    summarize,
)

__all__ = [
    "GOLDEN_CASES",
    "CaseOutcome",
    "EvalCase",
    "EvalReport",
    "meets_threshold",
    "run_eval",
    "summarize",
]
