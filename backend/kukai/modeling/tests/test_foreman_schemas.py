"""Schemas for the Foreman orchestrator: PhasePlan, PlanTask, ReviewVerdict."""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.foreman import (
    PhasePlan,
    PlanTask,
    ReviewIssue,
    ReviewSeverity,
    ReviewVerdict,
    PhaseRunResult,
    PhaseRunStatus,
)
from kukai.modeling.schemas.resolver import FamilyHint, GridIntersectionSpec, ResolverIntent
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, Tier


def _intent() -> ResolverIntent:
    return ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(category="OST_StructuralColumns", shape="rectangular"),
        grid_intersection=GridIntersectionSpec(grid_x_name="A", grid_y_name="1", level_name="L1"),
        revit_version="2026",
    )


def _expected() -> ExpectedElementsSpec:
    return ExpectedElementsSpec(category="OST_StructuralColumns", count=1)


def test_plan_task_minimal_fields():
    task = PlanTask(
        plan_task_id="pt_0001",
        intent=_intent(),
        expected_elements=_expected(),
        tier=Tier.TIER_2,
        skill_path="modeling/structure/columns/concrete-columns.md",
    )
    assert task.plan_task_id == "pt_0001"
    assert task.is_repair is False
    assert task.estimated_cost_usd == 0.0


def test_plan_task_immutable():
    task = PlanTask(
        plan_task_id="pt_0001",
        intent=_intent(),
        expected_elements=_expected(),
        tier=Tier.TIER_2,
        skill_path="modeling/structure/columns/concrete-columns.md",
    )
    with pytest.raises(ValidationError):
        task.tier = Tier.TIER_1  # type: ignore[misc]


def test_phase_plan_rejects_empty_tasks():
    with pytest.raises(ValidationError):
        PhasePlan(phase=Phase.STRUCTURE, tasks=[])


def test_phase_plan_rejects_duplicate_plan_task_ids():
    task = PlanTask(
        plan_task_id="pt_0001",
        intent=_intent(),
        expected_elements=_expected(),
        tier=Tier.TIER_2,
        skill_path="modeling/structure/columns/concrete-columns.md",
    )
    with pytest.raises(ValidationError):
        PhasePlan(phase=Phase.STRUCTURE, tasks=[task, task])


def test_review_verdict_passed_with_no_issues():
    v = ReviewVerdict(passed=True, issues=[], summary="ok")
    assert v.passed is True
    assert v.issues == []


def test_review_verdict_rejects_passed_with_blocking_issue():
    blocking = ReviewIssue(
        severity=ReviewSeverity.BLOCKING,
        category="task_id_mismatch",
        detail="brief=abc proposal=def",
    )
    with pytest.raises(ValidationError):
        ReviewVerdict(passed=True, issues=[blocking], summary="should fail")


def test_review_verdict_failed_requires_at_least_one_issue():
    with pytest.raises(ValidationError):
        ReviewVerdict(passed=False, issues=[], summary="cannot fail with no issues")


def test_phase_run_result_completed_requires_all_tasks_succeeded():
    result = PhaseRunResult(
        phase=Phase.STRUCTURE,
        status=PhaseRunStatus.COMPLETED,
        plan_task_ids=["pt_0001"],
        succeeded_plan_task_ids=["pt_0001"],
        failed_plan_task_ids=[],
        notes=[],
    )
    assert result.status == PhaseRunStatus.COMPLETED


def test_phase_run_result_completed_rejects_partial_success():
    with pytest.raises(ValidationError):
        PhaseRunResult(
            phase=Phase.STRUCTURE,
            status=PhaseRunStatus.COMPLETED,
            plan_task_ids=["pt_0001", "pt_0002"],
            succeeded_plan_task_ids=["pt_0001"],
            failed_plan_task_ids=["pt_0002"],
            notes=[],
        )
