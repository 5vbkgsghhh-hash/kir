"""L6 GeometryGate — coord deviation, AABB collision, host, level binding.

Runs after L5/L5.5, before queue returns. Reads geometry via
ModelQueryClient.query_element_geometry. Pure post-execute check — no side
effects. Phase 5 swaps MockModelQueryClient for the real bridge client.

Cross-task collision detection: NOT performed by this gate. L6 compares only
elements within a single task's execute response (current task's element_ids
vs each other).

Cross-task collision IS handled by the pre-execute geometry verifier
(`backend/kukai/modeling/foreman/verifiers/geometry.py`), which reads
`MockRevitSession.list_placed_elements()` (or the equivalent real query)
before each dispatch and compares the proposed placement to all previously
placed elements.

Phase 5+ scale concern: when element counts grow beyond ~50/phase, post-execute
cross-task validation may become useful (e.g., to catch elements that the
pre-execute verifier couldn't predict because the prior task's actual coords
differed from declared). Audit A Finding #4 (2026-05-20) flagged this asymmetry;
deferred until Phase 5+ scale work demands it.
"""
from __future__ import annotations
import asyncio
import math
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kukai.modeling.bridge.model_query_client import (
    ElementGeometry, ModelQueryClient,
)
from kukai.modeling.schemas.execution import ExecutionTask, GateOutcome
from kukai.modeling.schemas.tasks import TaskBrief


ViolationKind = Literal[
    "coord_deviation", "collision", "host_missing",
    "level_binding_missing", "geometry_query_failed",
]


class GeometryViolation(BaseModel):
    model_config = ConfigDict(frozen=True)
    element_id: int
    kind: ViolationKind
    detail: str = Field(..., min_length=1)


_HOST_REQUIRED_CATEGORIES: tuple[str, ...] = ("OST_Doors", "OST_Windows")


class GeometryGate:
    def __init__(
        self, *,
        query_client: ModelQueryClient,
        coord_deviation_tolerance_mm: float = 1.0,
        require_host_for: tuple[str, ...] = _HOST_REQUIRED_CATEGORIES,
    ):
        self._query = query_client
        self._tol = float(coord_deviation_tolerance_mm)
        self._host_required = tuple(require_host_for)

    async def run(
        self, *,
        task: ExecutionTask, element_ids: list[int], brief: TaskBrief,
    ) -> tuple[GateOutcome, list[GeometryViolation]]:
        start = time.monotonic()
        violations: list[GeometryViolation] = []
        # Audit N2 — per-element triage. return_exceptions=True so one bad
        # element does not lose all the others' validation results.
        raw_results = await asyncio.gather(*[
            self._query.query_element_geometry(eid) for eid in element_ids
        ], return_exceptions=True)
        geoms: list[ElementGeometry] = []
        for eid, res in zip(element_ids, raw_results):
            if isinstance(res, BaseException):
                violations.append(GeometryViolation(
                    element_id=eid,
                    kind="geometry_query_failed",
                    detail=f"{type(res).__name__}: {res}",
                ))
            else:
                geoms.append(res)

        expected = (
            brief.placement_point.x,
            brief.placement_point.y,
            brief.placement_point.z,
        )
        category = brief.expected_elements.category
        host_required = category in self._host_required

        for geom in geoms:
            dist = _euclidean(geom.centroid_mm, expected)
            if dist > self._tol:
                violations.append(GeometryViolation(
                    element_id=geom.element_id, kind="coord_deviation",
                    detail=(f"centroid {geom.centroid_mm} differs from {expected} "
                            f"by {dist:.2f}mm (tol {self._tol:.2f}mm)"),
                ))
            if host_required and geom.host_element_id is None:
                violations.append(GeometryViolation(
                    element_id=geom.element_id, kind="host_missing",
                    detail=f"category {category} requires host_element_id; got None",
                ))
            if geom.level_id is None:
                violations.append(GeometryViolation(
                    element_id=geom.element_id, kind="level_binding_missing",
                    detail="level_id is None",
                ))

        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                if _aabb_overlap(geoms[i], geoms[j]):
                    violations.append(GeometryViolation(
                        element_id=geoms[j].element_id, kind="collision",
                        detail=(f"bbox of {geoms[i].element_id} overlaps "
                                f"with {geoms[j].element_id}"),
                    ))

        duration_ms = int((time.monotonic() - start) * 1000)
        passed = not violations
        outcome = GateOutcome(
            name="L6_geometry", passed=passed, duration_ms=duration_ms,
            error=None if passed else f"{len(violations)} geometry violation(s)",
        )
        return outcome, violations


def _euclidean(a, b) -> float:
    return math.sqrt(sum((ax - bx) ** 2 for ax, bx in zip(a, b)))


def _aabb_overlap(a: ElementGeometry, b: ElementGeometry) -> bool:
    for axis in range(3):
        if a.bounding_box_max_mm[axis] <= b.bounding_box_min_mm[axis]:
            return False
        if b.bounding_box_max_mm[axis] <= a.bounding_box_min_mm[axis]:
            return False
    return True
