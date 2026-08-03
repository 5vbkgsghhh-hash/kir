"""GeometryResolver — converts grid+level names to project coordinates.

Per spec Section 5.3. For MVP1 we handle orthogonal grids only (axis in
{horizontal, vertical}). Non-orthogonal/curved grids deferred to MVP2.
"""
from __future__ import annotations
from dataclasses import dataclass

from kukai.modeling.bridge.model_query_client import ModelQueryClient
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.resolver import GridIntersectionSpec


@dataclass(frozen=True)
class GeometryResolution:
    point: XYZ
    level_id: int


class GeometryResolver:
    def __init__(self, query_client: ModelQueryClient):
        self._client = query_client

    async def resolve_grid_intersection(
        self, spec: GridIntersectionSpec
    ) -> GeometryResolution:
        grids = await self._client.query_grids()
        levels = await self._client.query_levels()

        grid_x = next((g for g in grids if g.name == spec.grid_x_name and g.axis == "horizontal"), None)
        grid_y = next((g for g in grids if g.name == spec.grid_y_name and g.axis == "vertical"), None)
        level = next((l for l in levels if l.name == spec.level_name), None)

        if grid_x is None:
            raise KeyError(f"grid x={spec.grid_x_name!r} not found among horizontal grids")
        if grid_y is None:
            raise KeyError(f"grid y={spec.grid_y_name!r} not found among vertical grids")
        if level is None:
            raise KeyError(f"level {spec.level_name!r} not found")

        return GeometryResolution(
            point=XYZ(x=grid_x.position_mm, y=grid_y.position_mm, z=level.elevation_mm),
            level_id=level.level_id,
        )

    async def lookup_level_id(self, level_name: str) -> int | None:
        levels = await self._client.query_levels()
        for l in levels:
            if l.name == level_name:
                return l.level_id
        return None
