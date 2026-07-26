"""AI provider abstraction for AI Ticket Analyzer.

Public surface for resolving and using ticket-analysis providers without
depending on any concrete backend.
"""

from app.ai.base import (
    AnalysisProvider,
    AnalysisResult,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    TokenUsage,
)
from app.ai.factory import build_provider

__all__ = [
    "AnalysisProvider",
    "AnalysisResult",
    "TokenUsage",
    "ProviderError",
    "ProviderTimeoutError",
    "ProviderRateLimitError",
    "ProviderConnectionError",
    "ProviderResponseError",
    "build_provider",
]
