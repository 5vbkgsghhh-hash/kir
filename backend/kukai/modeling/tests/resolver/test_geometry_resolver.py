"""Tests for GeometryResolver."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo
from kukai.modeling.resolver.geometry_resolver import GeometryResolver
from kukai.modeling.schemas.resolver import GridIntersectionSpec


@pytest.fixture
def mock_client() -> MockModelQueryClient:
    return MockModelQueryClient(
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
    )


@pytest.mark.asyncio
async def test_resolves_grid_intersection(mock_client):
    r = GeometryResolver(mock_client)
    out = await r.resolve_grid_intersection(GridIntersectionSpec(
        grid_x_name="2", grid_y_name="B", level_name="Level 1",
    ))
    assert out.point.x == 6000.0
    assert out.point.y == 6000.0
    assert out.point.z == 0.0
    assert out.level_id == 1042


@pytest.mark.asyncio
async def test_resolves_at_origin(mock_client):
    r = GeometryResolver(mock_client)
    out = await r.resolve_grid_intersection(GridIntersectionSpec(
        grid_x_name="1", grid_y_name="A", level_name="Level 1",
    ))
    assert out.point.x == 0.0
    assert out.point.y == 0.0


@pytest.mark.asyncio
async def test_raises_for_missing_grid(mock_client):
    r = GeometryResolver(mock_client)
    with pytest.raises(KeyError, match="grid"):
        await r.resolve_grid_intersection(GridIntersectionSpec(
            grid_x_name="999", grid_y_name="B", level_name="Level 1",
        ))


@pytest.mark.asyncio
async def test_raises_for_missing_level(mock_client):
    r = GeometryResolver(mock_client)
    with pytest.raises(KeyError, match="level"):
        await r.resolve_grid_intersection(GridIntersectionSpec(
            grid_x_name="2", grid_y_name="B", level_name="Level 99",
        ))


@pytest.mark.asyncio
async def test_lookup_level_id(mock_client):
    r = GeometryResolver(mock_client)
    assert await r.lookup_level_id("Level 2") == 1043
    assert await r.lookup_level_id("nonexistent") is None
