"""
Tests for the eval harness (M5.1).

The harness is exercised deterministically with a fake provider (no live LLM);
a real-provider run is a guarded, opt-in integration test.
"""

import os
from collections.abc import Sequence

import pytest
from app.ai.base import AnalysisProvider, AnalysisResult, ProviderResponseError
from app.eval.golden import GOLDEN_CASES
from app.eval.harness import (
    CaseOutcome,
    EvalCase,
    EvalReport,
    meets_threshold,
    run_eval,
    summarize,
)
from app.models import TicketAnalysis, TicketCategory, TicketPriority

CASES = [
    EvalCase(
        name="a",
        ticket_text="billing high",
        expected_category=TicketCategory.BILLING,
        expected_priority=TicketPriority.HIGH,
    ),
    EvalCase(
        name="b",
        ticket_text="refund low",
        expected_category=TicketCategory.REFUND,
        expected_priority=TicketPriority.LOW,
    ),
]


class _FakeProvider(AnalysisProvider):
    """Returns a caller-controlled (category, priority) per ticket text."""

    def __init__(
        self,
        responses: dict[str, tuple[TicketCategory, TicketPriority]],
        *,
        errors: Sequence[str] = (),
        prompt_version: str | None = "v1",
    ) -> None:
        self._responses = responses
        self._errors = set(errors)
        self._prompt_version = prompt_version

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def analyze(self, ticket_text: str) -> AnalysisResult:
        if ticket_text in self._errors:
            raise ProviderResponseError("boom")
        category, priority = self._responses[ticket_text]
        analysis = TicketAnalysis(
            summary="s", category=category, priority=priority, next_actions=["x"]
        )
        return AnalysisResult(analysis=analysis, prompt_version=self._prompt_version)


class TestEvalReportMetrics:
    def test_empty_report_is_zero_not_error(self) -> None:
        report = EvalReport()
        assert report.total == 0
        assert report.category_accuracy == 0.0
        assert report.priority_accuracy == 0.0
        assert report.exact_match_accuracy == 0.0

    def test_counts_and_accuracy(self) -> None:
        outcomes = [
            CaseOutcome(CASES[0], TicketCategory.BILLING, TicketPriority.HIGH),  # both ok
            CaseOutcome(CASES[1], TicketCategory.REFUND, TicketPriority.HIGH),  # cat ok, pri wrong
        ]
        report = EvalReport(outcomes=outcomes)
        assert report.total == 2
        assert report.category_correct == 2 and report.category_accuracy == 1.0
        assert report.priority_correct == 1 and report.priority_accuracy == 0.5
        assert report.exact_correct == 1 and report.exact_match_accuracy == 0.5


class TestRunEval:
    @pytest.mark.anyio
    async def test_all_correct(self) -> None:
        provider = _FakeProvider(
            {
                "billing high": (TicketCategory.BILLING, TicketPriority.HIGH),
                "refund low": (TicketCategory.REFUND, TicketPriority.LOW),
            }
        )
        report = await run_eval(provider, CASES)
        assert report.total == 2
        assert report.category_accuracy == 1.0
        assert report.priority_accuracy == 1.0
        assert report.model == "fake-model"
        assert report.prompt_version == "v1"

    @pytest.mark.anyio
    async def test_partial_and_error(self) -> None:
        provider = _FakeProvider(
            {"billing high": (TicketCategory.GENERAL_INQUIRY, TicketPriority.HIGH)},
            errors=["refund low"],
        )
        report = await run_eval(provider, CASES)
        assert report.errors == 1
        assert report.category_correct == 0  # first wrong category, second errored
        assert report.priority_correct == 1  # first priority correct
        assert report.category_accuracy == 0.0

    @pytest.mark.anyio
    async def test_meets_threshold(self) -> None:
        provider = _FakeProvider(
            {
                "billing high": (TicketCategory.BILLING, TicketPriority.HIGH),
                "refund low": (TicketCategory.REFUND, TicketPriority.LOW),
            }
        )
        report = await run_eval(provider, CASES)
        assert meets_threshold(report, min_category_accuracy=1.0, min_priority_accuracy=1.0)
        assert not meets_threshold(
            EvalReport(), min_category_accuracy=0.5, min_priority_accuracy=0.5
        )


class TestSummarize:
    @pytest.mark.anyio
    async def test_summary_reports_metrics_and_mismatches(self) -> None:
        provider = _FakeProvider(
            {
                "billing high": (TicketCategory.BILLING, TicketPriority.HIGH),
                "refund low": (TicketCategory.GENERAL_INQUIRY, TicketPriority.LOW),
            }
        )
        report = await run_eval(provider, CASES)
        text = summarize(report)
        assert "category accuracy" in text
        assert "mismatches" in text
        assert "General Inquiry" in text  # the wrong prediction is listed


class TestGoldenSet:
    def test_golden_set_is_valid(self) -> None:
        assert len(GOLDEN_CASES) >= 3
        names = [c.name for c in GOLDEN_CASES]
        assert len(names) == len(set(names))  # unique names
        for case in GOLDEN_CASES:
            assert case.ticket_text.strip()
            assert isinstance(case.expected_category, TicketCategory)
            assert isinstance(case.expected_priority, TicketPriority)


@pytest.mark.anyio
@pytest.mark.skipif(
    not (
        os.environ.get("RUN_LIVE_EVAL") and os.environ.get("OPENAI_API_KEY", "").startswith("sk-")
    ),
    reason="live eval opt-in: set RUN_LIVE_EVAL=1 and a real OPENAI_API_KEY",
)
async def test_live_golden_eval_meets_threshold() -> None:
    """Opt-in: run the golden set through the real provider and gate on accuracy."""
    from app.ai.factory import build_provider
    from app.config import Settings

    provider = build_provider(Settings(_env_file=None))
    try:
        report = await run_eval(provider, GOLDEN_CASES)
    finally:
        await provider.aclose()
    assert meets_threshold(report, min_category_accuracy=0.8, min_priority_accuracy=0.6), summarize(
        report
    )
