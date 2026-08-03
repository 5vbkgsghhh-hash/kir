"""Cascade routing: Flash vs Pro 3.1 by PlanTask complexity (arxiv 2405.15842).

Deterministic additive score (0-100, capped):
  TIER_3: +60 'tier_3_parametric' | is_repair: +30 'repair_attempt'
  >3 dims: +20 'many_dimensions' | count>5: +20 'multi_element_count'
  grid+<=1dim: +10 'simple_placement_baseline'
Threshold 50 -> PRO else FLASH. Pure function.
"""
from __future__ import annotations
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from kukai.modeling.schemas.foreman import PlanTask
from kukai.modeling.schemas.tasks import Tier


class ModelChoice(str, Enum):
    """Which Gemini model the cascade chose for this task."""
    FLASH = "gemini-flash-3"
    PRO = "gemini-pro-3.1"


class ComplexityScore(BaseModel):
    """Verbose-breakdown output of `assess_complexity`."""
    model_config = ConfigDict(frozen=True)

    score: int = Field(..., ge=0, le=100)
    factors: list[str] = Field(default_factory=list)


def assess_complexity(plan_task: PlanTask) -> ComplexityScore:
    """Deterministic complexity score 0-100 + factor list.

    Pure function. No I/O. Same input => same output.
    """
    score = 0
    factors: list[str] = []

    if plan_task.tier == Tier.TIER_3:
        score += 60
        factors.append("tier_3_parametric")

    if plan_task.is_repair:
        score += 30
        factors.append("repair_attempt")

    dims = plan_task.intent.family_hint.dimensions_mm
    if len(dims) > 3:
        score += 20
        factors.append("many_dimensions")

    if plan_task.expected_elements.count > 5:
        score += 20
        factors.append("multi_element_count")

    if plan_task.intent.grid_intersection is not None and len(dims) <= 1:
        score += 10
        factors.append("simple_placement_baseline")

    return ComplexityScore(score=min(100, score), factors=factors)


def select_model(complexity: ComplexityScore, threshold: int = 50) -> ModelChoice:
    """Map a ComplexityScore to a ModelChoice.

    Threshold default 50 mirrors the cascade-routing paper's mid-point sweep.
    """
    return ModelChoice.PRO if complexity.score >= threshold else ModelChoice.FLASH
