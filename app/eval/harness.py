"""
Evaluation harness for analysis quality (M5.1).

Runs a set of labeled :class:`EvalCase` through any ``AnalysisProvider`` and
scores category/priority accuracy. It is **provider-agnostic** (works with the
real LLM or a fake/recorded provider) and the scoring is pure, so the default
test suite exercises the harness deterministically with no live LLM; a live run
(``python -m app.eval``) measures a real prompt/model combination and can gate
CI via :func:`meets_threshold`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.ai.base import AnalysisProvider, ProviderError
from app.models import TicketCategory, TicketPriority


@dataclass(frozen=True)
class EvalCase:
    """A labeled example: ticket text + the expected category/priority."""

    ticket_text: str
    expected_category: TicketCategory
    expected_priority: TicketPriority
    name: str = ""


@dataclass(frozen=True)
class CaseOutcome:
    """The prediction for one case, plus correctness flags."""

    case: EvalCase
    predicted_category: TicketCategory | None
    predicted_priority: TicketPriority | None
    error: str | None = None

    @property
    def category_ok(self) -> bool:
        return self.error is None and self.predicted_category == self.case.expected_category

    @property
    def priority_ok(self) -> bool:
        return self.error is None and self.predicted_priority == self.case.expected_priority

    @property
    def exact_ok(self) -> bool:
        return self.category_ok and self.priority_ok


@dataclass(frozen=True)
class EvalReport:
    """Aggregate results of an evaluation run (pure — no I/O)."""

    outcomes: list[CaseOutcome] = field(default_factory=list)
    model: str | None = None
    prompt_version: str | None = None

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def errors(self) -> int:
        return sum(o.error is not None for o in self.outcomes)

    @property
    def category_correct(self) -> int:
        return sum(o.category_ok for o in self.outcomes)

    @property
    def priority_correct(self) -> int:
        return sum(o.priority_ok for o in self.outcomes)

    @property
    def exact_correct(self) -> int:
        return sum(o.exact_ok for o in self.outcomes)

    @property
    def category_accuracy(self) -> float:
        return self.category_correct / self.total if self.total else 0.0

    @property
    def priority_accuracy(self) -> float:
        return self.priority_correct / self.total if self.total else 0.0

    @property
    def exact_match_accuracy(self) -> float:
        return self.exact_correct / self.total if self.total else 0.0


async def run_eval(provider: AnalysisProvider, cases: Sequence[EvalCase]) -> EvalReport:
    """Analyze every case with ``provider`` and score the predictions.

    A ``Provider*`` failure on a case is recorded as an error outcome (counted as
    incorrect) rather than aborting the run, so one flaky case doesn't lose the
    whole report.
    """
    outcomes: list[CaseOutcome] = []
    prompt_version: str | None = None
    for case in cases:
        try:
            result = await provider.analyze(case.ticket_text)
        except ProviderError as exc:
            outcomes.append(CaseOutcome(case, None, None, error=str(exc)))
            continue
        prompt_version = result.prompt_version or prompt_version
        analysis = result.analysis
        outcomes.append(CaseOutcome(case, analysis.category, analysis.priority))
    return EvalReport(outcomes=outcomes, model=provider.model, prompt_version=prompt_version)


def meets_threshold(
    report: EvalReport,
    *,
    min_category_accuracy: float,
    min_priority_accuracy: float,
) -> bool:
    """Whether the report clears the given accuracy thresholds (the CI gate)."""
    return (
        report.category_accuracy >= min_category_accuracy
        and report.priority_accuracy >= min_priority_accuracy
    )


def summarize(report: EvalReport) -> str:
    """Render a human-readable eval report (used by the CLI)."""
    lines = [
        f"Eval report — model={report.model}, prompt={report.prompt_version}",
        f"  cases: {report.total}   errors: {report.errors}",
        f"  category accuracy: {report.category_accuracy:.0%} "
        f"({report.category_correct}/{report.total})",
        f"  priority accuracy: {report.priority_accuracy:.0%} "
        f"({report.priority_correct}/{report.total})",
        f"  exact-match:       {report.exact_match_accuracy:.0%} "
        f"({report.exact_correct}/{report.total})",
    ]
    mismatches = [o for o in report.outcomes if not o.exact_ok]
    if mismatches:
        lines.append("  mismatches:")
        for o in mismatches:
            label = o.case.name or o.case.ticket_text[:40]
            if o.error is not None:
                lines.append(f"    - {label}: ERROR {o.error}")
                continue
            got_cat = o.predicted_category.value if o.predicted_category else "?"
            got_pri = o.predicted_priority.value if o.predicted_priority else "?"
            lines.append(
                f"    - {label}: category {got_cat} (expected "
                f"{o.case.expected_category.value}), priority {got_pri} "
                f"(expected {o.case.expected_priority.value})"
            )
    return "\n".join(lines)
