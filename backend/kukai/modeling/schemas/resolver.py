"""Resolver schemas — bridges Foreman intent to Subagent task data.

Per spec Section 5.3. ResolverIntent is Foreman's high-level request;
ResolverOutput is the deterministically-resolved data passed to Subagent.
"""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

from kukai.modeling.schemas.identifiers import XYZ


class FamilyResolutionStatus(str, Enum):
    """Verdict from FamilyResolver."""
    RESOLVED = "resolved"           # exactly one symbol matched
    AMBIGUOUS = "ambiguous"          # multiple candidates; Foreman picks
    NOT_FOUND = "not_found"          # no candidate; escalate to user


class ParameterScope(str, Enum):
    """Where a Revit parameter is defined."""
    INSTANCE = "instance"
    TYPE = "type"
    SHARED = "shared"
    BUILT_IN = "built_in"


class FamilyHint(BaseModel):
    """High-level family description from BuildingBrief or Foreman."""
    model_config = ConfigDict(frozen=True)

    category: str = Field(..., description="BuiltInCategory name, e.g. OST_StructuralColumns")
    shape: str | None = Field(None, description="e.g. rectangular, circular, I-beam")
    dimensions_mm: dict[str, float] = Field(default_factory=dict, description="width/height/depth/diameter")
    material_hint: str | None = Field(None, description="e.g. concrete, steel, brick")
    name_contains: list[str] = Field(default_factory=list, description="optional substring filters")


class FamilySymbolCandidate(BaseModel):
    """Inventory record for a single FamilySymbol available in the Revit project."""
    model_config = ConfigDict(frozen=True)

    family_symbol_id: int
    name: str
    family_name: str
    category: str
    dimensions_mm: dict[str, float] = Field(default_factory=dict)


class GridIntersectionSpec(BaseModel):
    """Foreman specifies placement by axis names; GeometryResolver computes XYZ."""
    model_config = ConfigDict(frozen=True)

    grid_x_name: str
    grid_y_name: str
    level_name: str


class ResolverIntent(BaseModel):
    """Foreman's element placement intent. Resolver converts to ResolverOutput."""
    model_config = ConfigDict(frozen=True)

    element_type: str = Field(..., description="e.g. structural_column, wall, door")
    family_hint: FamilyHint
    grid_intersection: GridIntersectionSpec | None = None
    explicit_point: XYZ | None = Field(None, description="if set, overrides grid_intersection")
    top_level_name: str | None = None
    revit_version: str


class ResolverOutput(BaseModel):
    """Fully-resolved data: family ID, parameter map, coordinates.

    Subagent receives this and only writes placement code — no lookups.
    """
    model_config = ConfigDict(frozen=True)

    family_resolution: FamilyResolutionStatus
    family_symbol_id: int | None
    candidate_symbols: list[FamilySymbolCandidate] = Field(default_factory=list, description="present if AMBIGUOUS or NOT_FOUND with neighbors")

    parameter_map: dict[str, tuple[str, ParameterScope]] = Field(default_factory=dict, description="e.g. width -> (b, INSTANCE)")

    placement_point: XYZ
    level_id: int
    top_level_id: int | None = None

    revit_version: str
    notes: list[str] = Field(default_factory=list, description="diagnostic info for Foreman")
