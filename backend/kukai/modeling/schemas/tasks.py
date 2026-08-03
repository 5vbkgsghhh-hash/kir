"""Task-related schemas.

Per spec Section 11. TaskBrief is the fully-resolved message Foreman sends
to a Subagent: placement_point, family_symbol_id, parameter_map are all
pre-computed by Resolver — Subagent does not lookup, only places.
"""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

from kukai.modeling.schemas.identifiers import XYZ


class Phase(str, Enum):
    SETUP = "setup"
    STRUCTURE = "structure"
    ARCHITECTURE = "architecture"
    FACADE = "facade"
    ENRICHMENT = "enrichment"
    COMPLETE = "complete"


class Tier(str, Enum):
    """Per spec Section 7.1."""
    TIER_1 = "templated"             # no LLM, ~70-80% of elements
    TIER_2 = "subagent_per_element"  # LLM per element, ~20%
    TIER_3 = "subagent_multi_step"   # LLM multi-step, ~5% (parametric)


class ParameterRef(BaseModel):
    """A reference to a Revit parameter for code generation."""
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Parameter name as exposed in Revit")
    scope: str = Field(..., description="instance|type|shared|built_in")
    built_in: str | None = Field(None, description="BuiltInParameter enum name if applicable")


class ExpectedElementsSpec(BaseModel):
    """Contract: what the Subagent declares its code will produce.

    Used by gates L5 (count) and L5.5 (per-element property verification).
    """
    model_config = ConfigDict(frozen=True)

    category: str = Field(..., description="BuiltInCategory name, e.g. OST_StructuralColumns")
    count: int = Field(..., ge=0)
    naming_pattern: str | None = Field(None, description="regex each element name must match")
    level_name: str | None = None
    required_parameters: list[str] = Field(default_factory=list)


class TaskBrief(BaseModel):
    """Fully-resolved task dispatched from Foreman to a Subagent.

    Per spec Section 11: Resolver has already converted intent into IDs
    and coordinates. Subagent receives ready-to-use data.
    """
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(..., min_length=8, description="deterministic UUID per spec 3.5")
    phase: Phase
    skill_path: str = Field(..., description="relative path under skills/modeling/")
    element_type: str

    # Resolver-provided (mandatory for Tier 1/2; Tier 3 may have richer geometry)
    placement_point: XYZ
    family_symbol_id: int
    parameter_map: dict[str, ParameterRef] = Field(default_factory=dict)
    level_id: int
    top_level_id: int | None = None
    revit_version: str = Field(..., description="e.g. '2026'")

    expected_elements: ExpectedElementsSpec
    constraints: list[str] = Field(default_factory=list)
    tier: Tier
    is_repair: bool = False
    repair_for_task_id: str | None = None
    estimated_cost_usd: float = Field(..., ge=0.0)
