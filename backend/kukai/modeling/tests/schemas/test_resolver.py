"""Tests for Resolver schemas."""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.resolver import (
    FamilyHint,
    FamilyResolutionStatus,
    FamilySymbolCandidate,
    GridIntersectionSpec,
    ParameterScope,
    ResolverIntent,
    ResolverOutput,
)


class TestFamilyHint:
    def test_creates(self):
        h = FamilyHint(
            category="OST_StructuralColumns",
            shape="rectangular",
            dimensions_mm={"width": 400, "height": 400},
            material_hint="concrete",
        )
        assert h.category == "OST_StructuralColumns"
        assert h.dimensions_mm["width"] == 400

    def test_minimal_only_category(self):
        h = FamilyHint(category="OST_Walls")
        assert h.shape is None
        assert h.dimensions_mm == {}


class TestGridIntersectionSpec:
    def test_creates_with_names(self):
        g = GridIntersectionSpec(grid_x_name="2", grid_y_name="B", level_name="Level 1")
        assert g.grid_x_name == "2"
        assert g.grid_y_name == "B"


class TestResolverIntent:
    def test_for_column_placement(self):
        intent = ResolverIntent(
            element_type="structural_column",
            family_hint=FamilyHint(category="OST_StructuralColumns", dimensions_mm={"width": 400, "height": 400}),
            grid_intersection=GridIntersectionSpec(grid_x_name="2", grid_y_name="B", level_name="Level 1"),
            top_level_name="Level 2",
            revit_version="2026",
        )
        assert intent.element_type == "structural_column"


class TestResolverOutput:
    def test_resolved_full(self):
        out = ResolverOutput(
            family_resolution=FamilyResolutionStatus.RESOLVED,
            family_symbol_id=8821,
            candidate_symbols=[],
            parameter_map={
                "width": ("b", ParameterScope.INSTANCE),
                "height": ("h", ParameterScope.INSTANCE),
            },
            placement_point=XYZ(x=6000.0, y=6000.0, z=0.0),
            level_id=1042,
            top_level_id=1043,
            revit_version="2026",
            notes=[],
        )
        assert out.family_resolution == FamilyResolutionStatus.RESOLVED
        assert out.placement_point.x == 6000.0

    def test_ambiguous_with_candidates(self):
        candidates = [
            FamilySymbolCandidate(family_symbol_id=1, name="A", family_name="F_A", category="OST_StructuralColumns", dimensions_mm={"width": 400}),
            FamilySymbolCandidate(family_symbol_id=2, name="B", family_name="F_B", category="OST_StructuralColumns", dimensions_mm={"width": 400}),
        ]
        out = ResolverOutput(
            family_resolution=FamilyResolutionStatus.AMBIGUOUS,
            family_symbol_id=None,
            candidate_symbols=candidates,
            parameter_map={},
            placement_point=XYZ(x=0.0, y=0.0, z=0.0),
            level_id=1042,
            top_level_id=None,
            revit_version="2026",
            notes=["multiple candidates"],
        )
        assert len(out.candidate_symbols) == 2
        assert out.family_resolution == FamilyResolutionStatus.AMBIGUOUS

    def test_not_found(self):
        out = ResolverOutput(
            family_resolution=FamilyResolutionStatus.NOT_FOUND,
            family_symbol_id=None,
            candidate_symbols=[],
            parameter_map={},
            placement_point=XYZ(x=0.0, y=0.0, z=0.0),
            level_id=1042,
            top_level_id=None,
            revit_version="2026",
            notes=["no RC column families loaded"],
        )
        assert out.family_resolution == FamilyResolutionStatus.NOT_FOUND
        assert out.family_symbol_id is None
