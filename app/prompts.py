"""
Prompt engineering + versioning for AI Ticket Analyzer.

Prompts are **versioned artifacts** (M5.1). Each version bundles a system prompt
(and, if needed, a user-prompt builder); a small registry + ``get_prompt``
selector mirrors the provider/plan registries elsewhere in the codebase. The
provider records which prompt version produced an analysis (persisted on
``analyses.prompt_version``), and the eval harness (``app.eval``) measures a
prompt/model combination against labeled cases so prompt/model changes can be
gated in CI.

To add a new version: write its system prompt, create a ``PromptVersion``, and
register it in ``PROMPT_VERSIONS``. Select it at deploy time via
``LLM_PROMPT_VERSION`` (unset ⇒ ``DEFAULT_PROMPT_VERSION``). **Never edit a
shipped version's text in place** — add a new version so historical analyses stay
attributable and evals stay comparable.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.models import TicketCategory, TicketPriority


def _build_user_prompt(ticket_text: str) -> str:
    """Wrap the raw ticket text in the user-role prompt (shared across versions)."""
    return (
        "Analyze the following customer support ticket and provide a "
        "structured analysis.\n\n"
        f"--- TICKET START ---\n{ticket_text}\n--- TICKET END ---"
    )


def _build_user_prompt_with_context(ticket_text: str, context: str) -> str:
    """Prepend retrieved knowledge-base context to the ticket prompt (v2/RAG)."""
    return (
        "Use the following knowledge base excerpts, when relevant, to inform the "
        "summary and next actions. If they are not relevant, rely on the ticket "
        "alone and do not invent details.\n\n"
        f"--- KNOWLEDGE BASE START ---\n{context}\n--- KNOWLEDGE BASE END ---\n\n"
        "Analyze the following customer support ticket and provide a "
        "structured analysis.\n\n"
        f"--- TICKET START ---\n{ticket_text}\n--- TICKET END ---"
    )


# ---------------------------------------------------------------------------
# Prompt versions
# ---------------------------------------------------------------------------

_V1_SYSTEM_PROMPT: str = f"""\
You are an expert customer support ticket analyst. Your role is to analyze
incoming support tickets and produce a structured analysis.

## Your Tasks
1. **Summarize** the ticket in one or two concise sentences.
2. **Categorize** the ticket into exactly one of these categories:
   {", ".join(c.value for c in TicketCategory)}
3. **Assess priority** as one of:
   {", ".join(p.value for p in TicketPriority)}
4. **Suggest next actions** — provide 2-5 concrete, actionable steps the
   support agent should take to resolve the issue.

## Priority Guidelines
- **Critical**: Service outage, security breach, data loss, or complete
  inability to use the product affecting multiple users.
- **High**: Significant functionality broken, billing/payment issues with
  financial impact, or account access completely blocked.
- **Medium**: Partial functionality issues, non-urgent billing questions,
  or minor account problems with workarounds available.
- **Low**: General inquiries, feature requests, cosmetic issues, or
  informational questions.

## Rules
- Be objective; base the analysis solely on the ticket content.
- Keep the summary factual — do not add assumptions.
- Next actions should be specific, not generic.
- If the ticket mentions multiple issues, prioritize the most urgent one
  but reference others in next actions.
"""


_V2_SYSTEM_PROMPT: str = f"""\
You are an expert customer support ticket analyst. Your role is to analyze
incoming support tickets and produce a structured analysis, grounded in the
organization's knowledge base when relevant excerpts are provided.

## Your Tasks
1. **Summarize** the ticket in one or two concise sentences.
2. **Categorize** the ticket into exactly one of these categories:
   {", ".join(c.value for c in TicketCategory)}
3. **Assess priority** as one of:
   {", ".join(p.value for p in TicketPriority)}
4. **Suggest next actions** — provide 2-5 concrete, actionable steps the
   support agent should take to resolve the issue.

## Priority Guidelines
- **Critical**: Service outage, security breach, data loss, or complete
  inability to use the product affecting multiple users.
- **High**: Significant functionality broken, billing/payment issues with
  financial impact, or account access completely blocked.
- **Medium**: Partial functionality issues, non-urgent billing questions,
  or minor account problems with workarounds available.
- **Low**: General inquiries, feature requests, cosmetic issues, or
  informational questions.

## Using the knowledge base
- When knowledge-base excerpts are provided and relevant, use them to make the
  summary and next actions specific (e.g. cite the documented procedure).
- If the excerpts are irrelevant or absent, rely solely on the ticket content.
- Never fabricate policies or steps that are not supported by the ticket or the
  provided excerpts.

## Rules
- Be objective; base the analysis on the ticket content and any relevant excerpts.
- Keep the summary factual — do not add assumptions.
- Next actions should be specific, not generic.
- If the ticket mentions multiple issues, prioritize the most urgent one
  but reference others in next actions.
"""


@dataclass(frozen=True)
class PromptVersion:
    """A named, immutable prompt configuration used to produce analyses."""

    version: str
    system_prompt: str
    user_prompt_builder: Callable[[str], str] = _build_user_prompt
    # Optional builder used when retrieved RAG context is available (M5.2). When
    # ``None`` the version ignores context (identical to the no-context prompt).
    context_prompt_builder: Callable[[str, str], str] | None = None

    def build_user_message(self, ticket_text: str, context: str | None = None) -> str:
        """Render the user message, folding in ``context`` when the version uses it."""
        if context and self.context_prompt_builder is not None:
            return self.context_prompt_builder(ticket_text, context)
        return self.user_prompt_builder(ticket_text)

    def messages(self, ticket_text: str, context: str | None = None) -> list[dict[str, str]]:
        """Build the chat messages (system + user) for a ticket."""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.build_user_message(ticket_text, context)},
        ]


PROMPT_V1 = PromptVersion(version="v1", system_prompt=_V1_SYSTEM_PROMPT)
# v2 (M5.2): context-aware for RAG. Select via LLM_PROMPT_VERSION=v2 with
# RAG_ENABLED=true so retrieved knowledge-base context grounds the analysis.
PROMPT_V2 = PromptVersion(
    version="v2",
    system_prompt=_V2_SYSTEM_PROMPT,
    context_prompt_builder=_build_user_prompt_with_context,
)

# Registry of version name -> PromptVersion. Append new versions; never mutate.
PROMPT_VERSIONS: dict[str, PromptVersion] = {
    PROMPT_V1.version: PROMPT_V1,
    PROMPT_V2.version: PROMPT_V2,
}

DEFAULT_PROMPT_VERSION = "v1"


def get_prompt(version: str | None = None) -> PromptVersion:
    """Return the requested prompt version, failing safe to the default.

    ``None`` (unset) or an unknown version resolves to ``DEFAULT_PROMPT_VERSION``
    — the same conservative fail-safe used by the plan registry (``get_plan``).
    """
    if version is None:
        return PROMPT_VERSIONS[DEFAULT_PROMPT_VERSION]
    return PROMPT_VERSIONS.get(version, PROMPT_VERSIONS[DEFAULT_PROMPT_VERSION])


def available_prompt_versions() -> list[str]:
    """Return the sorted list of registered prompt version names."""
    return sorted(PROMPT_VERSIONS)


# ---------------------------------------------------------------------------
# Back-compat exports (pre-M5.1 imports of the v1 prompt keep working).
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = PROMPT_V1.system_prompt


def build_user_prompt(ticket_text: str) -> str:
    """Deprecated alias for the v1 user-prompt builder. Prefer ``get_prompt``."""
    return _build_user_prompt(ticket_text)


# ---------------------------------------------------------------------------
# Agentic resolution actions (M5.3)
# ---------------------------------------------------------------------------

ACTION_SYSTEM_PROMPT: str = """\
You are a customer-support resolution assistant. Given a ticket (and, when
provided, its analysis and knowledge-base context), propose a short, ordered set
of concrete resolution actions a human agent could take.

Only propose actions of these types:
- set_status: change the ticket status (open/in_progress/pending/resolved/closed).
- assign: assign the ticket to a person/queue.
- add_note: record an internal note (also used to draft reply text).
- send_reply: reply to the customer (a customer-facing action).
- escalate: escalate the ticket for urgent handling.

Rules:
- Propose at most 5 actions; fewer is fine. Never invent policies or facts.
- Every action needs a short, specific rationale.
- These are only proposals — a human approves and executes them, so it is safe to
  suggest customer-facing/escalation actions when warranted.
"""


def build_action_user_prompt(
    ticket_text: str, *, analysis_summary: str | None = None, context: str | None = None
) -> str:
    """Build the user message for action suggestion (M5.3)."""
    parts: list[str] = []
    if context:
        parts.append("--- KNOWLEDGE BASE START ---\n" + context + "\n--- KNOWLEDGE BASE END ---")
    if analysis_summary:
        parts.append(f"Analysis summary: {analysis_summary}")
    parts.append(f"--- TICKET START ---\n{ticket_text}\n--- TICKET END ---")
    parts.append("Propose the resolution actions as structured output.")
    return "\n\n".join(parts)
