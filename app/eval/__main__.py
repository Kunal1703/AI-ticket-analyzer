"""
CLI entry point for the eval harness (M5.1): ``python -m app.eval``.

Builds the configured provider (needs a real provider key / endpoint), runs the
golden set, prints a report, and exits non-zero when accuracy is below the
thresholds — so it can gate prompt/model changes in CI. Thresholds come from
``EVAL_MIN_CATEGORY_ACCURACY`` / ``EVAL_MIN_PRIORITY_ACCURACY`` (defaults 0.80 /
0.60; priority is inherently fuzzier than category).
"""

import asyncio
import os
import sys

from app.ai.factory import build_provider
from app.config import get_settings
from app.eval.golden import GOLDEN_CASES
from app.eval.harness import meets_threshold, run_eval, summarize


async def _run() -> int:
    settings = get_settings()
    provider = build_provider(settings)
    try:
        report = await run_eval(provider, GOLDEN_CASES)
    finally:
        await provider.aclose()

    print(summarize(report))
    min_category = float(os.environ.get("EVAL_MIN_CATEGORY_ACCURACY", "0.80"))
    min_priority = float(os.environ.get("EVAL_MIN_PRIORITY_ACCURACY", "0.60"))
    passed = meets_threshold(
        report,
        min_category_accuracy=min_category,
        min_priority_accuracy=min_priority,
    )
    print(
        f"{'PASS' if passed else 'FAIL'} "
        f"(thresholds: category>={min_category:.0%}, priority>={min_priority:.0%})"
    )
    return 0 if passed else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
