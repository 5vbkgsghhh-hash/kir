"""Tests for ModelQueryClient and MockModelQueryClient."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo
from kukai.modeling.schemas.resolver import FamilySymbolCandidate


@pytest.fixture
def populated_mock() -> MockModelQueryClient:
    return MockModelQueryClient(
        families=[
            FamilySymbolCandidate(
                family_symbol_id=8821,
                name="400 x 400mm",
                family_name="M_Concrete-Rectangular-Column",
                category="OST_StructuralColumns",
                dimensions_mm={"width": 400, "height": 400},
            ),
            FamilySymbolCandidate(
                family_symbol_id=8822,
                name="500 x 500mm",
                family_name="M_Concrete-Rectangular-Column",
                category="OST_StructuralColumns",
                dimensions_mm={"width": 500, "height": 500},
            ),
        ],
        levels=[
            LevelInfo(level_id=1042, name="Level 1", elevation_mm=0.0),
            LevelInfo(level_id=1043, name="Level 2", elevation_mm=3300.0),
        ],
        grids=[
            GridInfo(grid_id=2001, name="1", axis="horizontal", position_mm=0.0),
            GridInfo(grid_id=2002, name="2", axis="horizontal", position_mm=6000.0),
            GridInfo(grid_id=2003, name="A", axis="vertical", position_mm=0.0),
            GridInfo(grid_id=2004, name="B", axis="vertical", position_mm=6000.0),
        ],
        parameter_info={
            8821: {
                "width": ("b", "instance"),
                "height": ("h", "instance"),
                "mark": ("ALL_MODEL_MARK", "built_in"),
            },
        },
    )


@pytest.mark.asyncio
async def test_query_families_by_category(populated_mock):
    fams = await populated_mock.query_families(category="OST_StructuralColumns")
    assert len(fams) == 2


@pytest.mark.asyncio
async def test_query_levels(populated_mock):
    levels = await populated_mock.query_levels()
    assert len(levels) == 2
    assert levels[0].name == "Level 1"


@pytest.mark.asyncio
async def test_query_grids(populated_mock):
    grids = await populated_mock.query_grids()
    assert len(grids) == 4
    horiz = [g for g in grids if g.axis == "horizontal"]
    assert len(horiz) == 2


@pytest.mark.asyncio
async def test_query_parameter_info(populated_mock):
    info = await populated_mock.query_parameter_info(8821)
    assert info["width"] == ("b", "instance")
    assert info["mark"] == ("ALL_MODEL_MARK", "built_in")


@pytest.mark.asyncio
async def test_query_parameter_info_unknown_symbol(populated_mock):
    info = await populated_mock.query_parameter_info(99999)
    assert info == {}
