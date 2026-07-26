"""
Backward-compatible facade for ticket analysis.

Historically this module hosted the OpenAI integration directly. That logic now
lives behind the provider abstraction in :mod:`app.ai`, and the running
application builds and injects a provider via :mod:`app.dependencies`.

This module is retained as a thin, provider-agnostic entry point so existing
imports (e.g. ``from app.openai_client import analyze_ticket``) keep working.
Prefer the dependency-injected provider inside the app; this facade builds a
transient provider per call and is intended only for legacy/standalone use.
"""

from app.ai.factory import build_provider
from app.config import Settings, get_settings
from app.models import TicketAnalysis

__all__ = ["analyze_ticket"]


async def analyze_ticket(ticket_text: str, settings: Settings | None = None) -> TicketAnalysis:
    """Analyze a customer support ticket using the configured AI provider.

    Args:
        ticket_text: Raw customer support ticket content.
        settings: Optional settings override (defaults to global settings).

    Returns:
        A validated ``TicketAnalysis`` instance.
    """
    provider = build_provider(settings or get_settings())
    result = await provider.analyze(ticket_text)
    return result.analysis
