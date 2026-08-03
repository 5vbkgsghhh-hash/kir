"""Tests for MockCompileClient and MockBridgeClient."""
from __future__ import annotations
from typing import Any
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient


@pytest.mark.asyncio
async def test_mock_compile_default_success():
    m = MockCompileClient()
    r = await m.compile("// anything")
    assert r.success is True


@pytest.mark.asyncio
async def test_mock_compile_scripted_failure():
    m = MockCompileClient(
        responses=[{"success": False, "error": "CS1002"}]
    )
    r = await m.compile("// bad")
    assert r.success is False
    assert r.error == "CS1002"


@pytest.mark.asyncio
async def test_mock_bridge_default_success_one_element():
    m = MockBridgeClient()
    r = await m.execute_code("sess", "// any", expected_count=1)
    assert r["success"] is True
    assert len(r["element_ids"]) == 1


@pytest.mark.asyncio
async def test_mock_bridge_scripted_responses():
    m = MockBridgeClient(
        responses=[
            {"success": True, "element_ids": [9000], "duration_ms": 100},
            {"success": False, "error": "Mock failure", "element_ids": [], "duration_ms": 50},
        ]
    )
    r1 = await m.execute_code("s", "// a", 1)
    r2 = await m.execute_code("s", "// b", 1)
    assert r1["success"] is True
    assert r2["success"] is False


@pytest.mark.asyncio
async def test_mock_bridge_records_calls():
    m = MockBridgeClient()
    await m.execute_code("s", "// a", 1)
    await m.execute_code("s", "// b", 2)
    assert len(m.calls) == 2
    assert m.calls[1]["expected_count"] == 2


# ---- Wave 6C — Fix A#3: BridgeBriefForwarder Protocol ----

@pytest.mark.tier0
def test_mock_bridge_client_implements_forwarder_protocol():
    """MockBridgeClient must satisfy the BridgeBriefForwarder runtime
    Protocol check so ExecutionQueue's isinstance gate matches it."""
    from kukai.modeling.bridge.bridge_client import BridgeBriefForwarder
    client = MockBridgeClient()
    assert isinstance(client, BridgeBriefForwarder)


@pytest.mark.tier0
def test_real_websocket_client_does_not_implement_forwarder():
    """Real WebSocketBridgeClient is intentionally NOT a
    BridgeBriefForwarder — real Revit knows the current task from its own
    state; nothing to forward. ExecutionQueue's isinstance gate must
    skip forwarding here."""
    from kukai.modeling.bridge.bridge_client import (
        BridgeBriefForwarder, WebSocketBridgeClient,
    )
    client = WebSocketBridgeClient(base_url="http://localhost:52411")
    assert not isinstance(client, BridgeBriefForwarder)


@pytest.mark.tier0
def test_mock_bridge_forward_brief_delegates_to_session():
    """MockBridgeClient.forward_brief must call set_current_task on the
    wrapped MockRevitSession; clear_brief must call clear_current_task."""
    from kukai.modeling.bridge.mock_revit_session import MockRevitSession

    session = MockRevitSession()
    m = MockBridgeClient(revit_session=session)

    # Build a minimal TaskBrief
    from kukai.modeling.schemas.identifiers import XYZ
    from kukai.modeling.schemas.tasks import (
        ExpectedElementsSpec, Phase, TaskBrief, Tier,
    )
    brief = TaskBrief(
        task_id="t1task01", phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=0, y=0, z=0),
        family_symbol_id=10, parameter_map={},
        level_id=20, revit_version="2026",
        expected_elements=ExpectedElementsSpec(
            category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, estimated_cost_usd=0.05,
    )
    m.forward_brief(task_brief=brief, plan_task_id="pt_abc")
    assert session._current_task_brief is brief
    assert session._current_plan_task_id == "pt_abc"

    m.clear_brief()
    assert session._current_task_brief is None
    assert session._current_plan_task_id is None


@pytest.mark.tier0
def test_mock_bridge_forward_brief_noop_without_session():
    """When MockBridgeClient has no wrapped session (legacy scripted mode),
    forward_brief/clear_brief are silent no-ops."""
    m = MockBridgeClient()
    m.forward_brief(task_brief=None)  # must not raise
    m.clear_brief()  # must not raise


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_queue_submit_forwards_brief_to_mock_session():
    """ExecutionQueue.submit must call forward_brief on bridge clients
    that implement BridgeBriefForwarder. Verified by checking the wrapped
    session sees the brief during gate execution."""
    from kukai.modeling.bridge.mock_revit_session import MockRevitSession
    from kukai.modeling.execution.gates import (
        CompileGate, CountValidationGate, ExecuteGate,
    )
    from kukai.modeling.execution.queue import ExecutionQueue
    from kukai.modeling.schemas.execution import ExecutionTask
    from kukai.modeling.schemas.identifiers import XYZ
    from kukai.modeling.schemas.tasks import (
        ExpectedElementsSpec, Phase, TaskBrief, Tier,
    )

    session = MockRevitSession()
    captured: dict[str, Any] = {}

    # Wrap mock bridge so the compile gate's `.run` (which then triggers
    # the execute gate) can observe `session._current_task_brief`.
    bridge = MockBridgeClient(revit_session=session)

    # Patch execute_code to snapshot session state during the gated call.
    original_execute = bridge.execute_code

    async def execute_with_snapshot(*args, **kwargs):
        captured["brief_during_execute"] = session._current_task_brief
        return await original_execute(*args, **kwargs)
    bridge.execute_code = execute_with_snapshot

    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(bridge, session_id="mock"),
        count_gate=CountValidationGate(),
    )

    brief = TaskBrief(
        task_id="t1task01", phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=0, y=0, z=0),
        family_symbol_id=10, parameter_map={},
        level_id=20, revit_version="2026",
        expected_elements=ExpectedElementsSpec(
            category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, estimated_cost_usd=0.05,
    )
    task = ExecutionTask(
        task_id="t1task01",
        csharp_code="__result__ = new int[] { 1 };",
        expected_elements=brief.expected_elements,
        revit_version="2026",
        transaction_name="t",
        max_compile_attempts=1, max_execute_attempts=1,
    )
    await queue.submit(task, brief=brief)

    # The forwarded brief must be visible while the gate was running.
    assert captured["brief_during_execute"] is brief
    # After submit returns, clear_brief must have wiped the register.
    assert session._current_task_brief is None
