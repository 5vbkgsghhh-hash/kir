"""Foreman.dispatch_task — single-task end-to-end with mocks."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient, MockModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo
from kukai.modeling.execution.gates import CompileGate, CountValidationGate, ExecuteGate
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman.dispatcher import DispatchOutcome, Foreman
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.foreman import PlanTask
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.resolver import FamilyHint, FamilySymbolCandidate, GridIntersectionSpec, ResolverIntent
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, Tier
from kukai.modeling.state.projections.project_state import ProjectState
from kukai.modeling.subagent.structural import StructuralSubagent


def _full_checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _good_proposal(task_id: str, *, with_question: bool = False) -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code=(
            "// RAG:#snip_column_basic\n"
            "using (var t = new Transaction(doc, \"Place column\")) {\n"
            "  t.Start();\n"
            "  __result__ = new int[] { 12345 };\n"
            "  t.Commit();\n"
            "}\n"
        ),
        explanation="creates one column",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column",
        revit_version="2026",
        failure_mode_checks=_full_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_column_basic", api_called="Document.Create.NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
        questions_to_foreman=(["which family?"] if with_question else []),
    )


def _plan_task(plan_task_id: str = "pt_0001") -> PlanTask:
    return PlanTask(
        plan_task_id=plan_task_id,
        intent=ResolverIntent(
            element_type="structural_column",
            family_hint=FamilyHint(category="OST_StructuralColumns"),
            grid_intersection=GridIntersectionSpec(grid_x_name="A", grid_y_name="1", level_name="L1"),
            revit_version="2026",
        ),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        skill_path="modeling/structure/columns/concrete-columns.md",
    )


class _FakeSkillLoader:
    def load(self, skill_path: str) -> str:
        return "# Skill\nConcrete columns: use RAG snippets carefully."


def _make_foreman(
    llm: MockLLMClient,
    bridge: MockBridgeClient | None = None,
    compile: MockCompileClient | None = None,
    query: MockModelQueryClient | None = None,
):
    query = query or MockModelQueryClient(
        grids=[
            GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
            GridInfo(grid_id=2, name="1", axis="vertical", position_mm=0.0),
        ],
    )
    # Gotcha 2: seed a family so Resolver returns RESOLVED
    if not query._families:
        query._families = [FamilySymbolCandidate(
            family_symbol_id=10,
            name="C-300",
            family_name="ЖБ Колонна",
            category="OST_StructuralColumns",
        )]
    bridge = bridge or MockBridgeClient()
    compile = compile or MockCompileClient()
    resolver = Resolver(query)
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile),
        execute_gate=ExecuteGate(bridge, session_id="dev"),
        count_gate=CountValidationGate(),
    )
    return Foreman(
        project_id="proj1",
        resolver=resolver,
        subagent=StructuralSubagent(llm),
        execution_queue=queue,
        skill_loader=_FakeSkillLoader(),
        rag_snippets=[("snip_column_basic", "Column basic", "doc.Create.NewFamilyInstance(...)")],
        project_state_provider=lambda: ProjectState(),
    )


@pytest.mark.asyncio
async def test_dispatch_task_happy_path():
    llm = MockLLMClient()
    plan = _plan_task()
    from kukai.modeling.schemas.identifiers import deterministic_task_uuid
    expected_task_id = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    llm.queue_proposal(_good_proposal(expected_task_id))
    foreman = _make_foreman(llm)
    outcome = await foreman.dispatch_task(plan, phase=Phase.STRUCTURE, task_seq=1)
    assert isinstance(outcome, DispatchOutcome)
    assert outcome.executed is True
    assert outcome.execution_result is not None
    assert outcome.execution_result.success is True
    assert outcome.review_verdict.passed is True
    assert len(llm.calls) == 1  # single dispatch should hit the LLM exactly once


@pytest.mark.asyncio
async def test_dispatch_task_continues_through_questions_to_foreman():
    """Wave 6C Fix A#5 — questions_to_foreman is INFO not BLOCKING.

    Dispatch continues; the question is surfaced as an operator-facing
    escalation note on outcome.notes. Previously this case rejected the
    proposal at review, which punished the persona's documented
    clarification path."""
    llm = MockLLMClient()
    plan = _plan_task()
    from kukai.modeling.schemas.identifiers import deterministic_task_uuid
    expected_task_id = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    llm.queue_proposal(_good_proposal(expected_task_id, with_question=True))
    foreman = _make_foreman(llm)
    outcome = await foreman.dispatch_task(plan, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.executed is True
    assert outcome.execution_result is not None
    assert outcome.execution_result.success is True
    # Review passed (INFO doesn't block), but the question is recorded as an issue
    assert outcome.review_verdict.passed is True
    q_issues = [i for i in outcome.review_verdict.issues
                if i.category == "questions_to_foreman"]
    assert len(q_issues) == 1
    # Escalation note for operator
    assert any("escalation:" in n and "question(s) raised" in n
               for n in outcome.notes), f"notes={outcome.notes}"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_dispatch_task_records_resolver_output():
    llm = MockLLMClient()
    plan = _plan_task()
    from kukai.modeling.schemas.identifiers import deterministic_task_uuid
    expected_task_id = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    llm.queue_proposal(_good_proposal(expected_task_id))
    foreman = _make_foreman(llm)
    outcome = await foreman.dispatch_task(plan, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.resolver_output.family_symbol_id is not None
    assert outcome.task_brief.task_id == expected_task_id
    assert len(llm.calls) == 1  # single dispatch should hit the LLM exactly once


class _ScoredJudge:
    """Judge mock that returns canned scores based on a marker substring in the
    proposal's csharp_code. Lets us assert sampling picks the highest-scored one.
    """

    def __init__(self, scores_by_marker: dict[str, int]):
        self._scores_by_marker = scores_by_marker
        self.calls: list[int] = []

    async def judge(self, proposal, brief):
        from kukai.modeling.judge.code_judge import JudgeSeverity, JudgeVerdict
        score = 1
        for marker, s in self._scores_by_marker.items():
            if marker in proposal.csharp_code:
                score = s
                break
        self.calls.append(score)
        sev = JudgeSeverity.NONE if score >= 4 else JudgeSeverity.CRITICAL
        return JudgeVerdict(
            score=score,
            errors_detected=[] if score >= 4 else [FailureCategory.SILENT_NO_OP],
            severity=sev,
            suggestions=[] if score >= 4 else ["fix it"],
            judge_explanation="ok" if score >= 4 else "needs work, missing pieces",
        )


@pytest.mark.asyncio
async def test_dispatch_task_sampling_n3_picks_highest_scored_candidate():
    """Audit T3: SampledStructuralSubagent wraps the underlying subagent.
    Foreman with sampling_n=3 + judge must call the LLM 3 times for a single
    dispatch_task, and select the candidate with the highest judge score."""
    llm = MockLLMClient()
    plan = _plan_task()
    from kukai.modeling.schemas.identifiers import deterministic_task_uuid
    expected_task_id = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)

    # Three distinct candidates. They differ only in an inline marker comment so
    # the judge can assign different scores. All pass invariants (transaction
    # wrapper + __result__).
    def _candidate(marker_tag: str) -> CodeProposal:
        prop = _good_proposal(expected_task_id)
        new_code = prop.csharp_code.replace(
            "// RAG:#snip_column_basic",
            f"// RAG:#snip_column_basic\n// CANDIDATE:{marker_tag}",
        )
        return prop.model_copy(update={"csharp_code": new_code})

    llm.queue_proposal(_candidate("low"))
    llm.queue_proposal(_candidate("medium"))
    llm.queue_proposal(_candidate("WINNER"))

    judge = _ScoredJudge({"WINNER": 5, "medium": 3, "low": 1})

    # Build Foreman directly with sampling_n=3 + judge. No repair_loop wiring
    # (compile_for_repair/reflect_llm intentionally None) so the non-repair
    # branch is exercised: dispatcher.generate_code -> SampledStructuralSubagent.
    query = MockModelQueryClient(
        grids=[
            GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
            GridInfo(grid_id=2, name="1", axis="vertical", position_mm=0.0),
        ],
    )
    query._families = [FamilySymbolCandidate(
        family_symbol_id=10, name="C-300", family_name="ЖБ Колонна",
        category="OST_StructuralColumns",
    )]
    bridge = MockBridgeClient()
    compile_client = MockCompileClient()
    resolver = Resolver(query)
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(bridge, session_id="dev"),
        count_gate=CountValidationGate(),
    )
    from kukai.modeling.foreman.config import ForemanRepair, ForemanSampling

    # Sampling > 1 now requires a full ForemanRepair (all three: judge,
    # compile_client_for_repair, reflect_llm). For this test we only care about
    # the candidate-ranking path; the repair loop is not entered because each
    # ranked candidate passes invariants. Provide minimal compile/reflect stubs.
    class _NoOpCompile:
        async def compile(self, code, revit_version="2026"):
            from kukai.modeling.schemas.execution import CompileResult
            return CompileResult(success=True, code=code, assembly_id="noop")
        async def health(self): return True

    class _NoOpReflect:
        async def complete(self, prompt): return ""

    foreman = Foreman(
        project_id="proj1", resolver=resolver,
        subagent=StructuralSubagent(llm),
        execution_queue=queue, skill_loader=_FakeSkillLoader(),
        rag_snippets=[("snip_column_basic", "Column basic", "doc.Create.NewFamilyInstance(...)")],
        project_state_provider=lambda: ProjectState(),
        repair=ForemanRepair(
            judge=judge,
            compile_client_for_repair=_NoOpCompile(),
            reflect_llm=_NoOpReflect(),
        ),
        sampling=ForemanSampling(n=3),
        # roslyn_check_fn=None so the Roslyn screen is skipped (we have only the
        # invariants screen + judge rank; that's enough to verify candidate ranking).
    )

    outcome = await foreman.dispatch_task(plan, phase=Phase.STRUCTURE, task_seq=1)

    # 3 LLM calls (one per candidate), single dispatch_task. After Wave 5 R1,
    # configuring sampling.n>1 also requires ForemanRepair, so repair_loop is
    # active — but the winning candidate (score=5) passes the judge gate
    # immediately on the first repair attempt, so the LLM is still called
    # exactly 3 times (one per sampled candidate) and not retried.
    assert len(llm.calls) == 3, (
        f"sampling_n=3 should produce 3 LLM calls, got {len(llm.calls)}"
    )
    # Judge was invoked for each of the 3 invariant-passing candidates during
    # sampling. After Wave 5 R1, repair_loop also runs a final judge.judge() on
    # the selected proposal (4th call), so accept either 3 or 4 (still proves
    # ranking works because every candidate was scored).
    assert len(judge.calls) in (3, 4), (
        f"judge should rank all 3 candidates (+ optional repair recheck), got {len(judge.calls)}"
    )
    # The selected proposal is the highest-scored one.
    assert outcome.code_proposal is not None
    assert "CANDIDATE:WINNER" in outcome.code_proposal.csharp_code, (
        f"sampling selected the wrong candidate; "
        f"chosen code excerpt: {outcome.code_proposal.csharp_code[:200]!r}"
    )
