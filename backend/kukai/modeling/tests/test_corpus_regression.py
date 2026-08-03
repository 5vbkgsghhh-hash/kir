"""Corpus regression — replays every JSONL under corpus_samples/.

Live runs record into ../corpus/ (gitignored); to promote a recording to a
permanent regression, copy it into corpus_samples/ and rerun this test.

Two tests live here:

1. ``test_corpus_sample_replays_exactly`` — low-level: walks every record in
   the JSONL and checks the replay clients hand back identical responses.
   Catches bit-rot in the request-key construction (Fix E etc.).

2. ``test_corpus_drives_full_phase_run`` — high-level (audit T6): records a
   real Foreman.run_phase under RecordingBridgeClient + RecordingCompileClient
   + RecordingLLMClient, then re-runs the SAME phase against ReplayBridgeClient
   + ReplayCompileClient + ReplayLLMClient reading the just-written JSONL.
   Asserts the second run reproduces the first's phase outcome exactly.
   Without this, the replay infrastructure could silently regress (e.g. the
   pre-Fix-E ReplayCompileClient was dropping error messages — the
   record-level test would still pass).
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest

from kukai.modeling.bridge.mocks import (
    MockBridgeClient, MockCompileClient, MockModelQueryClient,
)
from kukai.modeling.bridge.model_query_client import GridInfo
from kukai.modeling.bridge.recording_client import (
    RecordingBridgeClient, RecordingCompileClient, RecordingLLMClient,
)
from kukai.modeling.bridge.replay_client import (
    ReplayBridgeClient, ReplayCompileClient, ReplayLLMClient,
)
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate,
)
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman.dispatcher import Foreman
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.foreman import PhasePlan, PhaseRunStatus, PlanTask
from kukai.modeling.schemas.identifiers import deterministic_task_uuid
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.resolver import (
    FamilyHint, FamilySymbolCandidate, GridIntersectionSpec, ResolverIntent,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, Tier
from kukai.modeling.state.projections.project_state import ProjectState
from kukai.modeling.subagent.structural import StructuralSubagent

_SAMPLES = Path(__file__).parent / "corpus_samples"


@pytest.mark.asyncio
@pytest.mark.parametrize("jsonl_path", sorted(_SAMPLES.glob("*.jsonl")), ids=lambda p: p.stem)
async def test_corpus_sample_replays_exactly(jsonl_path: Path):
    """Low-level: every record in the JSONL must be retrievable via its key."""
    compile_client = ReplayCompileClient(log_path=jsonl_path)
    bridge_client = ReplayBridgeClient(log_path=jsonl_path)
    for rec in (json.loads(l) for l in jsonl_path.read_text("utf-8").splitlines() if l.strip()):
        if rec["kind"] == "compile":
            r = await compile_client.compile(rec["request"]["code"])
            assert r.success == rec["response"]["success"]
            assert r.assembly_id == rec["response"].get("assembly_id")
        elif rec["kind"] == "execute_code":
            req = rec["request"]
            response = await bridge_client.execute_code(
                session_id=req["session_id"], csharp_code=req["code"],
                expected_count=req["expected_count"],
            )
            assert response == rec["response"]


# ---------------------------------------------------------------------------
# Audit T6 — high-level corpus regression: replay drives a full phase run.
# ---------------------------------------------------------------------------

def _checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _proposal(task_id: str) -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code=(
            "// RAG:#snip_a\nusing(Transaction t = new Transaction(doc,\"Place column\"))"
            "{t.Start();t.Commit();}\n__result__ = new int[] { 42 };"
        ),
        explanation="ok",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column",
        revit_version="2026",
        failure_mode_checks=_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_a", api_called="Document.Create.NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )


def _plan_task(plan_task_id: str, grid_x: str = "A") -> PlanTask:
    return PlanTask(
        plan_task_id=plan_task_id,
        intent=ResolverIntent(
            element_type="structural_column",
            family_hint=FamilyHint(category="OST_StructuralColumns"),
            grid_intersection=GridIntersectionSpec(grid_x_name=grid_x, grid_y_name="1", level_name="L1"),
            revit_version="2026",
        ),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        skill_path="modeling/structure/columns/concrete-columns.md",
    )


class _FakeSkills:
    def load(self, _p: str) -> str:
        return "# Skill"


def _build_foreman(*, llm, compile_client, bridge_client) -> Foreman:
    query = MockModelQueryClient(grids=[
        GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
        GridInfo(grid_id=2, name="B", axis="horizontal", position_mm=6000.0),
        GridInfo(grid_id=3, name="1", axis="vertical", position_mm=0.0),
    ])
    query._families = [FamilySymbolCandidate(
        family_symbol_id=10, name="C-300", family_name="ЖБ Колонна",
        category="OST_StructuralColumns",
    )]
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(bridge_client, session_id="dev"),
        count_gate=CountValidationGate(),
    )
    return Foreman(
        project_id="proj_replay_t6",
        resolver=Resolver(query),
        subagent=StructuralSubagent(llm),
        execution_queue=queue,
        skill_loader=_FakeSkills(),
        rag_snippets=[("snip_a", "t", "body")],
        project_state_provider=lambda: ProjectState(),
    )


@pytest.mark.asyncio
async def test_corpus_drives_full_phase_run(tmp_path):
    """Audit T6: replay must drive a real Foreman.run_phase, not just match
    raw records back-to-back.

    Stage 1 — RECORD: run a 2-task phase under MockLLM/MockCompile/MockBridge
    wrapped in the corresponding Recording* clients. Capture the resulting
    PhaseRunResult + the on-disk JSONL paths.

    Stage 2 — REPLAY: rebuild a NEW Foreman whose clients are Replay* against
    those JSONLs (no fresh mocks underneath). Drive the IDENTICAL phase plan.
    The new outcome must reproduce the recorded one exactly.

    This catches regressions where the recording or replay layers silently
    drop information (e.g. the pre-Fix-E ReplayCompileClient dropped error
    strings, which the record-level test couldn't observe). Also forces the
    LLM replay path to round-trip a full CodeProposal correctly.
    """
    # --- Stage 1: record ---
    rec_llm = MockLLMClient()
    tid1 = deterministic_task_uuid("proj_replay_t6", Phase.STRUCTURE.value, 1)
    tid2 = deterministic_task_uuid("proj_replay_t6", Phase.STRUCTURE.value, 2)
    rec_llm.queue_proposal(_proposal(tid1))
    rec_llm.queue_proposal(_proposal(tid2))

    rec_compile_mock = MockCompileClient()
    rec_bridge_mock = MockBridgeClient()

    rec_llm_recording = RecordingLLMClient(
        upstream=rec_llm, project_id="proj_replay_t6", corpus_dir=tmp_path)
    rec_compile_recording = RecordingCompileClient(
        upstream=rec_compile_mock, project_id="proj_replay_t6", corpus_dir=tmp_path)
    rec_bridge_recording = RecordingBridgeClient(
        upstream=rec_bridge_mock, project_id="proj_replay_t6", corpus_dir=tmp_path)

    foreman1 = _build_foreman(
        llm=rec_llm_recording,
        compile_client=rec_compile_recording,
        bridge_client=rec_bridge_recording,
    )
    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[
        _plan_task("pt_0001"), _plan_task("pt_0002", grid_x="B")])
    recorded_result = await foreman1.run_phase(plan)

    # The Recording* clients each wrote their own JSONL (one client = one log file).
    llm_log = rec_llm_recording.log_path
    compile_log = rec_compile_recording.log_path
    bridge_log = rec_bridge_recording.log_path
    assert llm_log.exists() and compile_log.exists() and bridge_log.exists()
    # Sanity: the recording produced > 0 lines on each log.
    assert llm_log.stat().st_size > 0
    assert compile_log.stat().st_size > 0
    assert bridge_log.stat().st_size > 0

    # --- Stage 2: replay through full Foreman pipeline ---
    foreman2 = _build_foreman(
        llm=ReplayLLMClient(log_path=llm_log),
        compile_client=ReplayCompileClient(log_path=compile_log),
        bridge_client=ReplayBridgeClient(log_path=bridge_log),
    )
    replayed_result = await foreman2.run_phase(plan)

    # The phase outcome reproduces exactly.
    assert replayed_result.status == recorded_result.status, (
        f"replay status diverged: recorded={recorded_result.status}, "
        f"replayed={replayed_result.status}"
    )
    assert recorded_result.status == PhaseRunStatus.COMPLETED
    assert (replayed_result.succeeded_plan_task_ids
            == recorded_result.succeeded_plan_task_ids)
    assert (replayed_result.failed_plan_task_ids
            == recorded_result.failed_plan_task_ids)
