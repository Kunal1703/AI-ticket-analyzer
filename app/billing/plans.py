"""
Plan registry: the monthly analysis limit for each subscription plan.

The registry is **configurable**, not hard-coded product pricing. The limits
below are deliberate *placeholders* for M2.5a (metering + enforcement plumbing);
real plan definitions/pricing are set later (M2.5b, Stripe) and can be overridden
at deploy time via ``Settings.plan_monthly_analysis_limits`` (env
``PLAN_MONTHLY_ANALYSIS_LIMITS`` as a JSON object).

A limit of ``None`` means unlimited.
"""

from dataclasses import dataclass

# The plan slug used as a fallback for unknown/unset plans. It is the most
# conservative known plan, so an unrecognized plan is never treated as unlimited.
DEFAULT_PLAN = "free"

# Placeholder limits — NOT final product pricing. Override via
# Settings.plan_monthly_analysis_limits. See module docstring.
_PLACEHOLDER_LIMITS: dict[str, int | None] = {
    "free": 100,
    "pro": 10_000,
    "enterprise": None,  # unlimited
}


@dataclass(frozen=True)
class Plan:
    """A subscription plan and its monthly analysis entitlement.

    Attributes:
        name: Plan slug (matches ``Organization.plan``).
        monthly_analysis_limit: Max metered analyses per calendar month, or
            ``None`` for unlimited.
    """

    name: str
    monthly_analysis_limit: int | None


def build_plans(overrides: dict[str, int | None] | None = None) -> dict[str, Plan]:
    """Build the plan registry from the placeholder defaults plus optional overrides.

    Overrides are merged over the defaults (per-plan), so deployments can retune
    limits — or add plans — without code changes.
    """
    limits = {**_PLACEHOLDER_LIMITS, **(overrides or {})}
    return {name: Plan(name=name, monthly_analysis_limit=limit) for name, limit in limits.items()}


def get_plan(plans: dict[str, Plan], name: str | None) -> Plan:
    """Return the plan for ``name``, falling back to the default plan.

    Never returns ``None``: an unknown plan resolves to the conservative default
    (``DEFAULT_PLAN``), and if that is somehow absent, to an unlimited plan so a
    misconfiguration fails open rather than blocking all requests.
    """
    if name is not None and name in plans:
        return plans[name]
    if DEFAULT_PLAN in plans:
        return plans[DEFAULT_PLAN]
    return Plan(name=DEFAULT_PLAN, monthly_analysis_limit=None)
