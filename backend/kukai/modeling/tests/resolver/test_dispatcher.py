"""Tests for Resolver dispatcher."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.resolver import (
    FamilyHint,
    FamilyResolutionStatus,
    FamilySymbolCandidate,
    GridIntersectionSpec,
    ParameterScope,
    ResolverIntent,
)


@pytest.fixture
def stocked_client() -> MockModelQueryClient:
    return MockModelQueryClient(
        families=[
            FamilySymbolCandidate(
                family_symbol_id=8821, name="400 x 400mm",
                family_name="M_Concrete-Rectangular-Column",
                category="OST_StructuralColumns",
                dimensions_mm={"width": 400, "height": 400},
            ),
        ],
        levels=[
            LevelInfo(level_id=1042, name="Level 1", elevation_mm=0.0),
            LevelInfo(level_id=1043, name="Level 2", elevation_mm=3300.0),
        ],
        grids=[
            GridInfo(grid_id=2002, name="2", axis="horizontal", position_mm=6000.0),
            GridInfo(grid_id=2004, name="B", axis="vertical", position_mm=6000.0),
        ],
        parameter_info={
            8821: {"width": ("b", "instance"), "mark": ("ALL_MODEL_MARK", "built_in")},
        },
    )


@pytest.mark.asyncio
async def test_dispatcher_resolved_column(stocked_client):
    r = Resolver(stocked_client)
    out = await r.resolve(ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(
            category="OST_StructuralColumns",
            dimensions_mm={"width": 400, "height": 400},
        ),
        grid_intersection=GridIntersectionSpec(
            grid_x_name="2", grid_y_name="B", level_name="Level 1",
        ),
        top_level_name="Level 2",
        revit_version="2026",
    ))
    assert out.family_resolution == FamilyResolutionStatus.RESOLVED
    assert out.family_symbol_id == 8821
    assert out.placement_point.x == 6000.0
    assert out.placement_point.y == 6000.0
    assert out.level_id == 1042
    assert out.top_level_id == 1043
    assert out.parameter_map["width"] == ("b", ParameterScope.INSTANCE)
    assert out.revit_version == "2026"


@pytest.mark.asyncio
async def test_dispatcher_ambiguous_family_returns_candidates(stocked_client):
    # add a second 400x400 to make it ambiguous
    duplicate = stocked_client._families[0].model_copy(
        update={"family_symbol_id": 8899, "name": "alt"}
    )
    stocked_client._families.append(duplicate)
    r = Resolver(stocked_client)
    out = await r.resolve(ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(
            category="OST_StructuralColumns",
            dimensions_mm={"width": 400, "height": 400},
        ),
        grid_intersection=GridIntersectionSpec(
            grid_x_name="2", grid_y_name="B", level_name="Level 1",
        ),
        revit_version="2026",
    ))
    assert out.family_resolution == FamilyResolutionStatus.AMBIGUOUS
    assert out.family_symbol_id is None
    assert len(out.candidate_symbols) == 2


@pytest.mark.asyncio
async def test_dispatcher_handles_explicit_point(stocked_client):
    from kukai.modeling.schemas.identifiers import XYZ
    r = Resolver(stocked_client)
    out = await r.resolve(ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(
            category="OST_StructuralColumns",
            dimensions_mm={"width": 400, "height": 400},
        ),
        explicit_point=XYZ(x=1234.0, y=5678.0, z=0.0),
        top_level_name="Level 2",
        revit_version="2026",
    ))
    assert out.placement_point.x == 1234.0
    assert out.placement_point.y == 5678.0


@pytest.mark.asyncio
async def test_dispatcher_no_top_level(stocked_client):
    """When top_level_name omitted, top_level_id is None."""
    r = Resolver(stocked_client)
    out = await r.resolve(ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(category="OST_StructuralColumns", dimensions_mm={"width": 400, "height": 400}),
        grid_intersection=GridIntersectionSpec(grid_x_name="2", grid_y_name="B", level_name="Level 1"),
        revit_version="2026",
    ))
    assert out.top_level_id is None
