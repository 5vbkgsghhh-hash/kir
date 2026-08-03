"""Pick (Tier, ModelChoice) for a given PlanTask.

Per spec Section 7.1 + Phase 4 Task 2 (cascade routing). Tier classification
is unchanged from MVP1 (still a stub that mirrors plan_task.tier); the second
return value is the routing decision between Flash and Pro 3.1 from
`kukai.modeling.llm.router.assess_complexity / select_model`.

Back-compat note: this function changed its return type from `Tier` to
`tuple[Tier, ModelChoice]` in Phase 4 Task 2. Callers that ignored the model
choice should destructure: `tier, _ = select_tier(plan_task)`.
"""
from __future__ import annotations

from kukai.modeling.llm.router import (
    ModelChoice, assess_complexity, select_model,
)
from kukai.modeling.schemas.foreman import PlanTask
from kukai.modeling.schemas.tasks import Tier


def select_tier(plan_task: PlanTask) -> tuple[Tier, ModelChoice]:
    """Return (Tier, ModelChoice) for this task.

    Currently a stub for Tier — always returns the tier already in
    `plan_task.tier`. The model choice IS active: TIER_3 / repair / etc.
    route to Gemini Pro 3.1 per the router scoring.
    """
    score = assess_complexity(plan_task)
    return plan_task.tier, select_model(score)
