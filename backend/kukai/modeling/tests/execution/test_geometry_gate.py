"""Phase 4 Task 3 — L6 GeometryGate: coord deviation, collision, host, level."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockModelQueryClient
from kukai.modeling.bridge.model_query_client import ElementGeometry
from kukai.modeling.execution.geometry_gate import (
    GeometryGate, GeometryViolation,
)
from kukai.modeling.schemas.execution import ExecutionTask
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, Phase, Tier, TaskBrief,
)


def _geom(eid, *, bbox_min=(-200.0, -200.0, 0.0), bbox_max=(200.0, 200.0, 3000.0),
          centroid=(0.0, 0.0, 1500.0), host=None, level=1):
    return ElementGeometry(
        element_id=eid, bounding_box_min_mm=bbox_min, bounding_box_max_mm=bbox_max,
        centroid_mm=centroid, host_element_id=host, level_id=level,
    )


def _brief(*, category="OST_StructuralColumns", placement=(0.0, 0.0, 0.0)) -> TaskBrief:
    return TaskBrief(
        task_id="t1task01", phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns", element_type="structural_column",
        placement_point=XYZ(x=placement[0], y=placement[1], z=placement[2]),
        family_symbol_id=10, parameter_map={}, level_id=1, revit_version="2026",
        expected_elements=ExpectedElementsSpec(category=category, count=1),
        constraints=[], tier=Tier.TIER_2, estimated_cost_usd=0.0,
    )


def _task(brief: TaskBrief) -> ExecutionTask:
    return ExecutionTask(
        task_id=brief.task_id, csharp_code="// stub",
        expected_elements=brief.expected_elements, revit_version=brief.revit_version,
        transaction_name="Place column",
        max_compile_attempts=1, max_execute_attempts=1,
    )


@pytest.mark.asyncio
async def test_geometry_gate_passes_when_in_bounds_no_collision():
    mqc = MockModelQueryClient(); mqc.seed_geometry(_geom(9001))
    gate = GeometryGate(query_client=mqc)
    # _geom() defaults centroid to (0,0,1500); brief placement must match for default 1mm tol.
    brief = _brief(placement=(0.0, 0.0, 1500.0))
    outcome, violations = await gate.run(task=_task(brief), element_ids=[9001], brief=brief)
    assert outcome.passed and outcome.name == "L6_geometry" and violations == []


@pytest.mark.asyncio
async def test_geometry_gate_fails_on_coord_deviation():
    mqc = MockModelQueryClient()
    mqc.seed_geometry(_geom(9001, centroid=(50.0, 0.0, 1500.0)))
    gate = GeometryGate(query_client=mqc, coord_deviation_tolerance_mm=1.0)
    brief = _brief(placement=(0.0, 0.0, 1500.0))
    outcome, violations = await gate.run(task=_task(brief), element_ids=[9001], brief=brief)
    assert not outcome.passed
    assert any(v.kind == "coord_deviation" for v in violations)


@pytest.mark.asyncio
async def test_geometry_gate_fails_on_collision():
    mqc = MockModelQueryClient()
    mqc.seed_geometry(_geom(9001, bbox_min=(0.0, 0.0, 0.0), bbox_max=(400.0, 400.0, 3000.0),
                            centroid=(200.0, 200.0, 1500.0)))
    mqc.seed_geometry(_geom(9002, bbox_min=(200.0, 200.0, 0.0), bbox_max=(600.0, 600.0, 3000.0),
                            centroid=(400.0, 400.0, 1500.0)))
    gate = GeometryGate(query_client=mqc, coord_deviation_tolerance_mm=10000.0)
    brief = _brief(placement=(200.0, 200.0, 1500.0))
    outcome, violations = await gate.run(task=_task(brief), element_ids=[9001, 9002], brief=brief)
    assert not outcome.passed
    assert any(v.kind == "collision" for v in violations)


@pytest.mark.asyncio
async def test_geometry_gate_fails_for_door_without_host():
    mqc = MockModelQueryClient()
    mqc.seed_geometry(_geom(9001, centroid=(450.0, 50.0, 1050.0), host=None))
    gate = GeometryGate(query_client=mqc, coord_deviation_tolerance_mm=10000.0)
    brief = _brief(category="OST_Doors", placement=(450.0, 50.0, 1050.0))
    outcome, violations = await gate.run(task=_task(brief), element_ids=[9001], brief=brief)
    assert not outcome.passed
    assert any(v.kind == "host_missing" for v in violations)


@pytest.mark.asyncio
async def test_geometry_gate_passes_for_door_with_host():
    mqc = MockModelQueryClient()
    mqc.seed_geometry(_geom(9001, centroid=(450.0, 50.0, 1050.0), host=5000))
    gate = GeometryGate(query_client=mqc, coord_deviation_tolerance_mm=10000.0)
    brief = _brief(category="OST_Doors", placement=(450.0, 50.0, 1050.0))
    outcome, violations = await gate.run(task=_task(brief), element_ids=[9001], brief=brief)
    assert outcome.passed and violations == []


@pytest.mark.asyncio
async def test_geometry_gate_fails_on_level_binding_missing():
    mqc = MockModelQueryClient(); mqc.seed_geometry(_geom(9001, level=None))
    gate = GeometryGate(query_client=mqc, coord_deviation_tolerance_mm=10000.0)
    brief = _brief()
    outcome, violations = await gate.run(task=_task(brief), element_ids=[9001], brief=brief)
    assert not outcome.passed
    assert any(v.kind == "level_binding_missing" for v in violations)


@pytest.mark.asyncio
async def test_geometry_gate_passes_multiple_non_colliding():
    mqc = MockModelQueryClient()
    mqc.seed_geometry(_geom(9001, bbox_min=(0.0, 0.0, 0.0), bbox_max=(400.0, 400.0, 3000.0),
                            centroid=(200.0, 200.0, 1500.0)))
    mqc.seed_geometry(_geom(9002, bbox_min=(1000.0, 0.0, 0.0), bbox_max=(1400.0, 400.0, 3000.0),
                            centroid=(1200.0, 200.0, 1500.0)))
    gate = GeometryGate(query_client=mqc, coord_deviation_tolerance_mm=10000.0)
    brief = _brief(placement=(200.0, 200.0, 1500.0))
    outcome, violations = await gate.run(task=_task(brief), element_ids=[9001, 9002], brief=brief)
    assert outcome.passed and violations == []


@pytest.mark.asyncio
@pytest.mark.tier0
async def test_geometry_gate_isolates_query_failures():
    """Audit N2: per-element triage — one query exception does not lose all results."""
    class _FlakeyQuery:
        async def query_element_geometry(self, eid):
            if eid == 9002:
                raise RuntimeError("Revit query timeout")
            return _geom(eid, centroid=(0.0, 0.0, 1500.0))

    gate = GeometryGate(query_client=_FlakeyQuery())
    brief = _brief(placement=(0.0, 0.0, 1500.0))
    outcome, violations = await gate.run(
        task=_task(brief), element_ids=[9001, 9002, 9003], brief=brief,
    )
    # only 9002 should report geometry_query_failed; 9001 + 9003 validated normally.
    failed = [v for v in violations if v.kind == "geometry_query_failed"]
    assert len(failed) == 1
    assert failed[0].element_id == 9002
    assert "RuntimeError" in failed[0].detail
    # No coord_deviation violations expected (placement matches geom centroid).
    assert not any(v.kind == "coord_deviation" for v in violations)


@pytest.mark.asyncio
async def test_geometry_gate_integration_with_queue():
    """Full ExecutionQueue path: L3→L4→L5→L6 with geometry-gate wiring."""
    from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient
    from kukai.modeling.execution.gates import (
        CompileGate, CountValidationGate, ExecuteGate,
    )
    from kukai.modeling.execution.queue import ExecutionQueue

    mqc = MockModelQueryClient()
    # MockBridgeClient default returns element_ids starting at 9000 + 100*N
    # → first call yields 9100. Seed geometry for that ID.
    mqc.seed_geometry(_geom(9100))
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client=MockCompileClient()),
        execute_gate=ExecuteGate(bridge_client=MockBridgeClient(), session_id="mock"),
        count_gate=CountValidationGate(),
        geometry_gate=GeometryGate(query_client=mqc, coord_deviation_tolerance_mm=10000.0),
    )
    brief = _brief(placement=(0.0, 0.0, 1500.0))
    result = await queue.submit(_task(brief), brief=brief)
    assert result.success and result.l6_geometry_passed
