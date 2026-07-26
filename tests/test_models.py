"""
Unit tests for Pydantic models.

Validates request/response schemas, enum values, and edge cases.
"""

import pytest
from app.models import (
    HealthResponse,
    TicketAnalysis,
    TicketCategory,
    TicketPriority,
    TicketRequest,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# TicketRequest tests
# ---------------------------------------------------------------------------


class TestTicketRequest:
    """Tests for the TicketRequest model."""

    def test_valid_ticket(self) -> None:
        """A non-empty ticket string should be accepted."""
        req = TicketRequest(ticket="My account is locked.")
        assert req.ticket == "My account is locked."

    def test_empty_ticket_rejected(self) -> None:
        """An empty string must fail validation (min_length=1)."""
        with pytest.raises(ValidationError) as exc_info:
            TicketRequest(ticket="")
        assert "ticket" in str(exc_info.value)

    def test_missing_ticket_rejected(self) -> None:
        """Omitting the ticket field must fail validation."""
        with pytest.raises(ValidationError):
            TicketRequest()  # type: ignore[call-arg]

    def test_long_ticket_rejected(self) -> None:
        """Tickets exceeding max_length should be rejected."""
        with pytest.raises(ValidationError):
            TicketRequest(ticket="x" * 5001)

    def test_max_length_ticket_accepted(self) -> None:
        """A ticket at exactly max_length should be accepted."""
        req = TicketRequest(ticket="x" * 5000)
        assert len(req.ticket) == 5000

    def test_whitespace_only_ticket_accepted(self) -> None:
        """Whitespace-only ticket passes model validation (API strips later)."""
        req = TicketRequest(ticket="   ")
        assert req.ticket == "   "


# ---------------------------------------------------------------------------
# TicketCategory tests
# ---------------------------------------------------------------------------


class TestTicketCategory:
    """Tests for the TicketCategory enum."""

    def test_all_categories_exist(self) -> None:
        """All required categories must be present."""
        expected = {
            "Billing",
            "Technical Issue",
            "Account Access",
            "Bug Report",
            "Feature Request",
            "Subscription",
            "Refund",
            "General Inquiry",
        }
        actual = {c.value for c in TicketCategory}
        assert actual == expected

    def test_category_count(self) -> None:
        """There should be exactly 8 categories."""
        assert len(TicketCategory) == 8


# ---------------------------------------------------------------------------
# TicketPriority tests
# ---------------------------------------------------------------------------


class TestTicketPriority:
    """Tests for the TicketPriority enum."""

    def test_all_priorities_exist(self) -> None:
        """All required priority levels must be present."""
        expected = {"Low", "Medium", "High", "Critical"}
        actual = {p.value for p in TicketPriority}
        assert actual == expected

    def test_priority_count(self) -> None:
        """There should be exactly 4 priority levels."""
        assert len(TicketPriority) == 4


# ---------------------------------------------------------------------------
# TicketAnalysis tests
# ---------------------------------------------------------------------------


class TestTicketAnalysis:
    """Tests for the TicketAnalysis response model."""

    @pytest.fixture
    def valid_analysis_data(self) -> dict:
        """Fixture for a valid analysis payload."""
        return {
            "summary": "Customer cannot log in.",
            "category": "Account Access",
            "priority": "High",
            "next_actions": ["Reset password", "Verify identity"],
        }

    def test_valid_analysis(self, valid_analysis_data: dict) -> None:
        """A well-formed payload should produce a valid model."""
        analysis = TicketAnalysis(**valid_analysis_data)
        assert analysis.summary == "Customer cannot log in."
        assert analysis.category == TicketCategory.ACCOUNT_ACCESS
        assert analysis.priority == TicketPriority.HIGH
        assert len(analysis.next_actions) == 2

    def test_invalid_category_rejected(self, valid_analysis_data: dict) -> None:
        """An unsupported category value must fail validation."""
        valid_analysis_data["category"] = "Unknown"
        with pytest.raises(ValidationError):
            TicketAnalysis(**valid_analysis_data)

    def test_invalid_priority_rejected(self, valid_analysis_data: dict) -> None:
        """An unsupported priority value must fail validation."""
        valid_analysis_data["priority"] = "Urgent"
        with pytest.raises(ValidationError):
            TicketAnalysis(**valid_analysis_data)

    def test_empty_next_actions_rejected(self, valid_analysis_data: dict) -> None:
        """At least one next action is required."""
        valid_analysis_data["next_actions"] = []
        with pytest.raises(ValidationError):
            TicketAnalysis(**valid_analysis_data)

    def test_serialization_roundtrip(self, valid_analysis_data: dict) -> None:
        """Model should survive JSON serialization and deserialization."""
        analysis = TicketAnalysis(**valid_analysis_data)
        json_str = analysis.model_dump_json()
        restored = TicketAnalysis.model_validate_json(json_str)
        assert restored == analysis


# ---------------------------------------------------------------------------
# HealthResponse tests
# ---------------------------------------------------------------------------


class TestHealthResponse:
    """Tests for the HealthResponse model."""

    def test_defaults(self) -> None:
        """Status should default to 'healthy'."""
        resp = HealthResponse(version="1.0.0")
        assert resp.status == "healthy"
        assert resp.version == "1.0.0"
