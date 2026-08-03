"""YAML loader for golden scenarios. Pure function, no Foreman dependencies."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

from pydantic import BaseModel, ConfigDict, Field

from kukai.modeling.schemas.foreman import PhasePlan, PlanTask
from kukai.modeling.schemas.resolver import (
    FamilyHint, GridIntersectionSpec, ResolverIntent,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, Tier


# Audit N14 — closed-set pydantic schemas validate scenario YAML structure at load
# time. Typos in keys ("expecteds:" instead of "expected:") become construction
# errors rather than silent "default value used" mistakes downstream.
class _ScenarioSchema(BaseModel):
    """Top-level scenario shape — every key the loader recognises."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str = ""
    project_id: str = "proj_golden"
    phase_plan: dict[str, Any]
    scripted_llm_responses: list[dict[str, Any]] = Field(default_factory=list)
    scripted_bridge_responses: list[dict[str, Any]] = Field(default_factory=list)
    scripted_compile_responses: list[dict[str, Any]] = Field(default_factory=list)
    model_query_seed: dict[str, Any] = Field(default_factory=dict)
    # Audit T5 — when set, the test wraps MockBridgeClient with a MockRevitSession
    # built from this seed. The session then parses real C# placement calls and
    # tracks placed-element state, exercising the regex parser end-to-end.
    # Shape: {grids: [...], levels: [...], families: [...]} (same keys as
    # MockRevitSession constructor; reuses model_query_seed shape).
    mock_revit_session_seed: dict[str, Any] | None = None
    user_intervention: dict[str, Any] | None = None
    requires_repair_loop_wiring: bool = False
    expected: dict[str, Any]


class _ExpectedSchema(BaseModel):
    """Expected-block keys — anything unknown is a typo. Keys derived from
    the 10 canonical scenario YAMLs as of 2026-05-19."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_status: str
    succeeded_count: int = 0
    failed_count: int = 0
    notes_substring: str | None = None
    assert_idempotency: bool = False
    # Audit T5 — session-backed scenarios use these to assert the parser
    # actually placed elements and that they map to distinct XYZ locations.
    placed_element_count: int | None = None
    placed_distinct_locations: int | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    project_id: str
    phase_plan: PhasePlan
    scripted_llm_responses: list[dict[str, Any]]
    scripted_bridge_responses: list[dict[str, Any]]
    scripted_compile_responses: list[dict[str, Any]]
    model_query_seed: dict[str, Any]
    mock_revit_session_seed: dict[str, Any] | None
    user_intervention: dict[str, Any] | None
    requires_repair_loop_wiring: bool
    expected: dict[str, Any]


def _required(d: dict[str, Any], key: str) -> Any:
    if key not in d:
        raise KeyError(f"scenario missing required key: {key!r}")
    return d[key]


def _build_plan(raw: dict[str, Any]) -> PhasePlan:
    phase = Phase(_required(raw, "phase"))
    tasks: list[PlanTask] = []
    for t in _required(raw, "tasks"):
        ir = _required(t, "intent")
        intent = ResolverIntent(
            element_type=_required(ir, "element_type"),
            family_hint=FamilyHint(category=_required(ir["family_hint"], "category"),
                                   name_contains=ir["family_hint"].get("name_contains", [])),
            grid_intersection=GridIntersectionSpec(
                grid_x_name=_required(ir["grid_intersection"], "grid_x_name"),
                grid_y_name=_required(ir["grid_intersection"], "grid_y_name"),
                level_name=_required(ir["grid_intersection"], "level_name"),
            ),
            revit_version=_required(ir, "revit_version"),
        )
        er = t["expected_elements"]
        expected = ExpectedElementsSpec(
            category=_required(er, "category"),
            count=int(_required(er, "count")),
            naming_pattern=er.get("naming_pattern"),
            level_name=er.get("level_name"),
            required_parameters=er.get("required_parameters", []),
        )
        tasks.append(PlanTask(
            plan_task_id=_required(t, "plan_task_id"),
            intent=intent,
            expected_elements=expected,
            tier=Tier(_required(t, "tier")),
            skill_path=_required(t, "skill_path"),
        ))
    return PhasePlan(phase=phase, tasks=tasks)


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"scenario root must be a mapping: {path}")
    # Audit N14 — validate raw YAML against closed-set schemas. Typos in
    # keys ("scripted_llm_response" missing 's', "expecteds:") raise here
    # rather than silently using defaults downstream.
    parsed = _ScenarioSchema.model_validate(raw)
    # Also validate the expected block.
    _ExpectedSchema.model_validate(parsed.expected)
    return Scenario(
        name=parsed.name,
        description=parsed.description,
        project_id=parsed.project_id,
        phase_plan=_build_plan(parsed.phase_plan),
        scripted_llm_responses=list(parsed.scripted_llm_responses),
        scripted_bridge_responses=list(parsed.scripted_bridge_responses),
        scripted_compile_responses=list(parsed.scripted_compile_responses),
        model_query_seed=dict(parsed.model_query_seed),
        mock_revit_session_seed=(
            dict(parsed.mock_revit_session_seed)
            if parsed.mock_revit_session_seed is not None else None
        ),
        user_intervention=parsed.user_intervention,
        requires_repair_loop_wiring=parsed.requires_repair_loop_wiring,
        expected=dict(parsed.expected),
    )
