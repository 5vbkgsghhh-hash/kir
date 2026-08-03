"""VerificationFunction is the per-PlanTask typed assertion bundle.

Per Phase 4 Task 1 (VeriMAP pattern): each PlanTask may carry a VF; Foreman
evaluates it post-execute against actual placed elements + declared_outputs.
"""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.foreman import VerificationFunction


def test_verification_function_minimal():
    vf = VerificationFunction(
        description="Column at A-1, 400x400",
        must_hold_outputs=["expected_element_count", "expected_category"],
    )
    assert vf.description == "Column at A-1, 400x400"
    assert vf.python_assertions == []
    assert vf.must_hold_outputs == ["expected_element_count", "expected_category"]


def test_verification_function_with_assertions():
    vf = VerificationFunction(
        description="Wall on L1 with Width=200",
        python_assertions=[
            "declared.expected_element_count == actual_count",
            "'Width' in declared.expected_parameter_values",
        ],
        must_hold_outputs=["expected_element_count"],
    )
    assert len(vf.python_assertions) == 2


def test_verification_function_empty_description_rejected():
    with pytest.raises(ValidationError):
        VerificationFunction(description="", must_hold_outputs=["expected_element_count"])


def test_verification_function_frozen():
    vf = VerificationFunction(
        description="x",
        must_hold_outputs=["expected_element_count"],
    )
    with pytest.raises(ValidationError):
        vf.description = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Wave 5 R2 — AST whitelist for python_assertions
# ---------------------------------------------------------------------------


@pytest.mark.tier0
def test_assertion_with_call_rejected():
    """Wave 5 R2 — calls of any kind are disallowed at construction.
    __import__, subclass-introspection, dunder access via attribute walk —
    all rejected before Foreman has a chance to evaluate them."""
    with pytest.raises(ValidationError):
        VerificationFunction(description="hostile",
                             python_assertions=["__import__('os')"],
                             must_hold_outputs=["expected_element_count"])
    with pytest.raises(ValidationError):
        # The classic Python sandbox escape: (()).__class__.__bases__[0].__subclasses__()
        # Disallowed because it ultimately contains a Call node.
        VerificationFunction(description="hostile2",
                             python_assertions=["().__class__.__bases__[0].__subclasses__()"],
                             must_hold_outputs=["expected_element_count"])


@pytest.mark.tier0
def test_assertion_with_attribute_subscript_allowed():
    """Wave 5 R2 — attribute access on `declared.*` and subscript on
    `actual_parameters[...]` are common, legitimate VF patterns."""
    vf = VerificationFunction(
        description="combined attr+subscript",
        python_assertions=[
            "actual_parameters['Mark'] == declared.expected_category",
        ],
        must_hold_outputs=["expected_element_count"],
    )
    assert len(vf.python_assertions) == 1


@pytest.mark.tier0
def test_simple_comparison_allowed():
    """Wave 5 R2 — bread-and-butter VF expressions must keep working."""
    vf = VerificationFunction(
        description="simple",
        python_assertions=[
            "actual_count == declared.expected_element_count",
            "actual_count > 5",
            "'Width' in actual_parameters",
            "actual_count == 1 and 'Width' in actual_parameters",
        ],
        must_hold_outputs=["expected_element_count"],
    )
    assert len(vf.python_assertions) == 4


@pytest.mark.tier0
def test_assertion_empty_string_rejected():
    """Wave 5 R2 — silent assertions mask planner bugs."""
    with pytest.raises(ValidationError):
        VerificationFunction(description="silent",
                             python_assertions=["   "],
                             must_hold_outputs=["expected_element_count"])


@pytest.mark.tier0
def test_assertion_invalid_syntax_rejected():
    """Wave 5 R2 — non-parseable strings rejected with a clear error."""
    with pytest.raises(ValidationError):
        VerificationFunction(description="syntax",
                             python_assertions=["1 +"],
                             must_hold_outputs=["expected_element_count"])


def test_plan_task_accepts_verification_function():
    from kukai.modeling.schemas.foreman import PlanTask
    from kukai.modeling.schemas.resolver import (
        FamilyHint, GridIntersectionSpec, ResolverIntent,
    )
    from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Tier

    intent = ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(category="OST_StructuralColumns"),
        grid_intersection=GridIntersectionSpec(grid_x_name="A", grid_y_name="1", level_name="L1"),
        revit_version="2026",
    )
    vf = VerificationFunction(description="A-1",
                              must_hold_outputs=["expected_element_count"])
    base = dict(
        intent=intent,
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, skill_path="modeling/structure/columns",
    )
    pt = PlanTask(plan_task_id="p1", verification_function=vf, **base)
    pt2 = PlanTask(plan_task_id="p2", **base)
    assert pt.verification_function is vf and pt2.verification_function is None
