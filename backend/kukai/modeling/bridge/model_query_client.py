"""ModelQueryClient — protocol for reading current Revit model state.

For MVP1 we only use MockModelQueryClient. The real implementation
(BridgeModelQueryClient) is deferred until after Phase 0 Spike — it
will require a new bridge endpoint exposing FilteredElementCollector
query results over HTTP/WebSocket.
"""
from __future__ import annotations
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from kukai.modeling.schemas.resolver import FamilySymbolCandidate


class LevelInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    level_id: int
    name: str
    elevation_mm: float


class GridInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    grid_id: int
    name: str
    axis: str             # "horizontal" or "vertical"
    position_mm: float    # signed offset along the perpendicular axis


class ElementGeometry(BaseModel):
    """Geometry snapshot of one placed Revit element (Phase 4 Task 3).

    Coordinates in MILLIMETERS (not Revit internal feet). host_element_id
    is set for hosted families (doors/windows); None otherwise. level_id
    is the binding Level reference.
    """
    model_config = ConfigDict(frozen=True)

    element_id: int
    bounding_box_min_mm: tuple[float, float, float]
    bounding_box_max_mm: tuple[float, float, float]
    centroid_mm: tuple[float, float, float]
    host_element_id: int | None
    level_id: int | None


class ModelQueryClient(Protocol):
    """Read-only access to current Revit project model state."""

    async def query_families(
        self, category: str | None = None
    ) -> list[FamilySymbolCandidate]: ...

    async def query_levels(self) -> list[LevelInfo]: ...

    async def query_grids(self) -> list[GridInfo]: ...

    async def query_parameter_info(
        self, family_symbol_id: int
    ) -> dict[str, tuple[str, str]]: ...

    async def query_element_properties(self, element_id: int) -> dict[str, str]:
        """Return a flat name->value-string mapping of the element's parameters.

        Keys SHOULD include at minimum: 'Mark', 'Level', 'FamilySymbolId',
        and every parameter declared in TaskBrief.expected_elements.required_parameters.
        """
        ...

    async def query_element_geometry(
        self, element_id: int
    ) -> ElementGeometry: ...
