"""
Golden evaluation set (M5.1).

A small, curated fixture of unambiguously-labeled tickets used to measure
analysis quality (category/priority) for a given prompt/model. Kept intentionally
small and clear; grow it (or derive cases from the ``feedback`` table's
``corrected_category``/``corrected_priority`` labels) as real signal accumulates.
"""

from app.eval.harness import EvalCase
from app.models import TicketCategory, TicketPriority

GOLDEN_CASES: list[EvalCase] = [
    EvalCase(
        name="double-charge-upgrade",
        ticket_text=(
            "I upgraded to the Pro plan yesterday and was charged twice on my "
            "card, but my account still shows the Free plan. Please fix the "
            "billing and refund the duplicate charge."
        ),
        expected_category=TicketCategory.BILLING,
        expected_priority=TicketPriority.HIGH,
    ),
    EvalCase(
        name="api-outage",
        ticket_text=(
            "Your API has been returning HTTP 500 errors for the last hour and "
            "our production checkout is completely down. This is affecting all "
            "of our customers right now."
        ),
        expected_category=TicketCategory.TECHNICAL_ISSUE,
        expected_priority=TicketPriority.CRITICAL,
    ),
    EvalCase(
        name="dark-mode-request",
        ticket_text=(
            "It would be nice if you could add a dark mode option to the "
            "dashboard at some point. Not urgent, just a suggestion."
        ),
        expected_category=TicketCategory.FEATURE_REQUEST,
        expected_priority=TicketPriority.LOW,
    ),
    EvalCase(
        name="locked-out",
        ticket_text=(
            "I'm completely locked out of my account and the password reset "
            "email never arrives no matter how many times I request it. I can't "
            "access anything."
        ),
        expected_category=TicketCategory.ACCOUNT_ACCESS,
        expected_priority=TicketPriority.HIGH,
    ),
    EvalCase(
        name="support-hours",
        ticket_text=(
            "Quick question — what are your customer support hours, and do you "
            "offer phone support in addition to email?"
        ),
        expected_category=TicketCategory.GENERAL_INQUIRY,
        expected_priority=TicketPriority.LOW,
    ),
]
