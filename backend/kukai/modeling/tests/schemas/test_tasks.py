"""Tests for task-related schemas."""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.tasks import (
    Tier,
    Phase,
    ExpectedElementsSpec,
    ParameterRef,
    TaskBrief,
)


class TestExpectedElementsSpec:
    def test_creates_with_required_fields(self):
        spec = ExpectedElementsSpec(
            category="OST_StructuralColumns",
            count=12,
            naming_pattern=r"^C-\d[A-Z]-L\d$",
            level_name="Level 1",
        )
        assert spec.count == 12
        assert spec.category == "OST_StructuralColumns"

    def test_rejects_negative_count(self):
        with pytest.raises(ValidationError):
            ExpectedElementsSpec(category="OST_Walls", count=-1)


class TestTaskBrief:
    def test_creates_with_resolved_fields(self):
        brief = TaskBrief(
            task_id="abc123def456",
            phase=Phase.STRUCTURE,
            skill_path="structure/columns/concrete-columns",
            element_type="structural_column",
            placement_point=XYZ(x=6000.0, y=6000.0, z=0.0),
            family_symbol_id=8821,
            parameter_map={"width": ParameterRef(name="b", scope="instance")},
            level_id=1042,
            top_level_id=1043,
            revit_version="2026",
            expected_elements=ExpectedElementsSpec(
                category="OST_StructuralColumns",
                count=1,
            ),
            tier=Tier.TIER_2,
            estimated_cost_usd=0.0005,
        )
        assert brief.task_id == "abc123def456"
        assert brief.placement_point.x == 6000.0

    def test_rejects_unresolved_brief(self):
        # placement_point is required — Resolver must have run first
        with pytest.raises(ValidationError):
            TaskBrief(  # type: ignore
                task_id="abc",
                phase=Phase.STRUCTURE,
                skill_path="x",
                element_type="x",
            )
