"""Parametrized auto-discovery for golden_scenarios/*.yaml."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import pytest
import yaml

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient, MockModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo
from kukai.modeling.execution.gates import CompileGate, CountValidationGate, ExecuteGate
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman import Foreman
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.foreman import PhaseRunStatus
from kukai.modeling.schemas.identifiers import deterministic_task_uuid
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.resolver import FamilySymbolCandidate
from kukai.modeling.schemas.tasks import ExpectedElementsSpec
from kukai.modeling.state.projections.project_state import ProjectState
from kukai.modeling.subagent.structural import StructuralSubagent
from kukai.modeling.tests.golden_scenarios._loader import Scenario, load_scenario

_HERE = Path(__file__).parent / "golden_scenarios"


def _full_default_checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _build_proposal(raw: dict[str, Any], project_id: str, phase_value: str, plan_task) -> CodeProposal:
    task_id = (deterministic_task_uuid(project_id, phase_value, int(raw["seq"]))
               if raw["task_id_generator"] == "deterministic" else raw["task_id"])
    er = raw.get("expected_elements") or {"category": plan_task.expected_elements.category,
                                           "count": plan_task.expected_elements.count}
    checks_raw = raw.get("failure_mode_checks", "full_default")
    checks = _full_default_checks() if checks_raw == "full_default" else {
        FailureCategory(k): FailureCheckResult(**v) for k, v in checks_raw.items()
    }
    cite = raw["rag_citation"]; dry = raw["dry_run"]
    return CodeProposal(
        task_id=task_id, csharp_code=raw["csharp_code"], explanation=raw.get("explanation", "ok"),
        expected_elements=ExpectedElementsSpec(category=er["category"], count=er["count"]),
        requires_assemblies=raw.get("requires_assemblies", ["RevitAPI"]),
        transaction_name=raw["transaction_name"], revit_version=raw["revit_version"],
        failure_mode_checks=checks,
        rag_citations=[InlineRagCitation(snippet_id=cite["snippet_id"], api_called=cite["api_called"])],
        dry_run=DryRunSummary(selected_symbol_id=int(dry["selected_symbol_id"]),
                              proposed_xyz_mm=tuple(dry["proposed_xyz_mm"])),
        questions_to_foreman=raw.get("questions_to_foreman", []),
    )


class _FakeSkills:
    def load(self, _p: str) -> str:
        return "# Skill"


class _InterventionState:
    def __init__(self, trigger_before_seq: int | None, reason: str | None):
        self._trigger = trigger_before_seq
        self._reason = reason or ""
        self._calls = 0

    def __call__(self) -> ProjectState:
        self._calls += 1
        if self._trigger is not None and self._calls >= self._trigger:
            return ProjectState(user_intervention_required=True, user_intervention_reason=self._reason)
        return ProjectState()


def _build_foreman(scenario: Scenario, llm, compile_client, bridge_client) -> Foreman:
    seed = scenario.model_query_seed or {}
    families = [FamilySymbolCandidate(**f) for f in seed.get("families", [])]
    levels = [LevelInfo(**lv) for lv in seed.get("levels", [])] or None
    grids = [GridInfo(**g) for g in seed.get("grids", [])] or None
    query = MockModelQueryClient(families=families, levels=levels, grids=grids)
    intervention = scenario.user_intervention
    state_provider = _InterventionState(
        trigger_before_seq=intervention["required_before_seq"] if intervention else None,
        reason=intervention["reason"] if intervention else None,
    )
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(bridge_client, session_id="dev"),
        count_gate=CountValidationGate(),
    )
    if scenario.requires_repair_loop_wiring:
        from kukai.modeling.foreman.config import ForemanRepair
        from kukai.modeling.judge.code_judge import JudgeSeverity, JudgeVerdict

        class _AlwaysOKJudge:
            async def judge(self, proposal, brief):
                return JudgeVerdict(score=5, errors_detected=[], severity=JudgeSeverity.NONE, suggestions=[], judge_explanation="code looks correct, all checks pass")

        class _ReflectAdapter:
            async def complete(self, prompt: str) -> str:
                return "I will fix the previous compile error."

        return Foreman(
            project_id=scenario.project_id, resolver=Resolver(query),
            subagent=StructuralSubagent(llm), execution_queue=queue,
            skill_loader=_FakeSkills(), rag_snippets=[("snip_a", "t", "b")],
            project_state_provider=state_provider,
            repair=ForemanRepair(
                judge=_AlwaysOKJudge(),
                compile_client_for_repair=compile_client,
                reflect_llm=_ReflectAdapter(),
            ),
        )
    return Foreman(
        project_id=scenario.project_id, resolver=Resolver(query),
        subagent=StructuralSubagent(llm), execution_queue=queue,
        skill_loader=_FakeSkills(), rag_snippets=[("snip_a", "t", "b")],
        project_state_provider=state_provider,
    )


def _build_session_from_seed(seed: dict[str, Any]):
    """Audit T5 — construct MockRevitSession from a YAML seed dict.

    Reuses the same shape as model_query_seed for consistency (grids/levels/families).
    """
    from kukai.modeling.bridge.mock_revit_session import MockRevitSession
    grids = [GridInfo(**g) for g in seed.get("grids", [])] or None
    levels = [LevelInfo(**lv) for lv in seed.get("levels", [])] or None
    families = [FamilySymbolCandidate(**f) for f in seed.get("families", [])] or None
    return MockRevitSession(grids=grids, levels=levels, families=families)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_path", sorted(_HERE.glob("*.yaml")), ids=lambda p: p.stem)
async def test_golden_scenario(scenario_path: Path):
    scenario = load_scenario(scenario_path)
    llm = MockLLMClient()
    compile_client = MockCompileClient(responses=scenario.scripted_compile_responses)
    # Audit T5 — when scenario declares a mock_revit_session_seed, wire the
    # MockBridgeClient through a MockRevitSession so the C# regex parser
    # actually runs against the scripted code. Otherwise use scripted responses.
    if scenario.mock_revit_session_seed is not None:
        revit_session = _build_session_from_seed(scenario.mock_revit_session_seed)
        bridge_client = MockBridgeClient(revit_session=revit_session)
    else:
        revit_session = None
        bridge_client = MockBridgeClient(responses=scenario.scripted_bridge_responses)
    for raw_resp in scenario.scripted_llm_responses:
        seq = int(raw_resp.get("seq", 1))
        plan_task = scenario.phase_plan.tasks[seq - 1]
        llm.queue_proposal(_build_proposal(raw_resp, scenario.project_id,
                                           scenario.phase_plan.phase.value, plan_task))
    foreman = _build_foreman(scenario, llm, compile_client, bridge_client)
    result = await foreman.run_phase(scenario.phase_plan)
    exp = scenario.expected
    assert result.status == PhaseRunStatus(exp["phase_status"])
    assert len(result.succeeded_plan_task_ids) == exp["succeeded_count"]
    assert len(result.failed_plan_task_ids) == exp["failed_count"]
    if exp.get("notes_substring"):
        assert any(exp["notes_substring"] in n for n in result.notes), \
            f"expected {exp['notes_substring']!r} in notes: {result.notes!r}"
    # Audit T5 — session-backed assertions: parser actually placed N distinct elements.
    if revit_session is not None:
        placed = revit_session.list_placed_elements()
        if exp.get("placed_element_count") is not None:
            assert len(placed) == exp["placed_element_count"], (
                f"expected {exp['placed_element_count']} placed elements, "
                f"session has {len(placed)}: "
                f"{[(p.element_id, p.location_mm) for p in placed]}"
            )
        if exp.get("placed_distinct_locations") is not None:
            distinct = {p.location_mm for p in placed}
            assert len(distinct) == exp["placed_distinct_locations"], (
                f"expected {exp['placed_distinct_locations']} distinct XYZ locations, "
                f"got {len(distinct)} from {sorted(distinct)}"
            )
    if exp.get("assert_idempotency"):
        llm2 = MockLLMClient()
        for raw_resp in scenario.scripted_llm_responses:
            seq = int(raw_resp.get("seq", 1))
            plan_task = scenario.phase_plan.tasks[seq - 1]
            llm2.queue_proposal(_build_proposal(raw_resp, scenario.project_id,
                                                 scenario.phase_plan.phase.value, plan_task))
        c2 = MockCompileClient(responses=scenario.scripted_compile_responses)
        b2 = MockBridgeClient(responses=scenario.scripted_bridge_responses)
        result2 = await _build_foreman(scenario, llm2, c2, b2).run_phase(scenario.phase_plan)
        assert result.succeeded_plan_task_ids == result2.succeeded_plan_task_ids
