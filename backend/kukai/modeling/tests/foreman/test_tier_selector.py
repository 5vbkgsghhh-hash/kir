"""Phase 4 Task 2 — `select_tier` now returns (Tier, ModelChoice)."""
from __future__ import annotations

from kukai.modeling.foreman.tier_selector import select_tier
from kukai.modeling.llm.router import ModelChoice
from kukai.modeling.schemas.foreman import PlanTask
from kukai.modeling.schemas.resolver import (
    FamilyHint, GridIntersectionSpec, ResolverIntent,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Tier


def _plan_task(tier: Tier = Tier.TIER_2, is_repair: bool = False) -> PlanTask:
    return PlanTask(
        plan_task_id="p1",
        intent=ResolverIntent(
            element_type="structural_column",
            family_hint=FamilyHint(category="OST_StructuralColumns"),
            grid_intersection=GridIntersectionSpec(grid_x_name="A", grid_y_name="1", level_name="L1"),
            revit_version="2026",
        ),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=tier,
        skill_path="modeling/structure/columns",
        is_repair=is_repair,
    )


def test_select_tier_returns_tier_and_model_choice():
    tier, model = select_tier(_plan_task())
    assert tier == Tier.TIER_2
    assert isinstance(model, ModelChoice)


def test_select_tier_tier3_picks_pro():
    _, model = select_tier(_plan_task(tier=Tier.TIER_3))
    assert model is ModelChoice.PRO


def test_select_tier_simple_picks_flash():
    _, model = select_tier(_plan_task())
    assert model is ModelChoice.FLASH
