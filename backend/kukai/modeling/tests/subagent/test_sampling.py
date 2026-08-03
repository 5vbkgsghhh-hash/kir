"""Tests for SampledStructuralSubagent (Phase 3 Task 3.3)."""
from __future__ import annotations
from unittest.mock import AsyncMock

import pytest

from kukai.modeling.schemas.execution import CompileResult
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation)
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, ParameterRef, Phase, TaskBrief, Tier)
from kukai.modeling.subagent.sampling import SampledStructuralSubagent


def _full_failure_checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _brief(task_id: str = "t1task01") -> TaskBrief:
    return TaskBrief(
        task_id=task_id, phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=0, y=0, z=0), family_symbol_id=10,
        parameter_map={"width": ParameterRef(name="b", scope="instance")},
        level_id=20, revit_version="2026",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, estimated_cost_usd=0.05)


def _proposal(task_id: str = "t1task01", code_suffix: str = "") -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code=f'// RAG:#snip_a\nvar x = 1;{code_suffix}', explanation="ok",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"], transaction_name="Place column",
        revit_version="2026", failure_mode_checks=_full_failure_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_a", api_called="X")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)))


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_n_equals_one_calls_underlying_once():
    underlying = AsyncMock()
    underlying.generate_code.return_value = _proposal()
    judge = AsyncMock()
    sampled = SampledStructuralSubagent(
        underlying=underlying, invariants_check_fn=lambda _: [],
        roslyn_check_fn=None, judge=judge, n=1)
    out = await sampled.generate_code(
        task_brief=_brief(), skill_content="",
        rag_snippets=[("snip_a", "t", "b")])
    assert out.task_id == "t1task01"
    assert underlying.generate_code.await_count == 1
    judge.judge.assert_not_called()


class _Verdict:
    def __init__(self, score: float): self.score = score


async def _run(*, n, candidates, invariants_fn, roslyn=None, scores=None):
    """Build a SampledStructuralSubagent, run generate_code, return chosen + spies."""
    underlying = AsyncMock()
    underlying.generate_code.side_effect = candidates
    judge = AsyncMock()
    if scores is not None:
        judge.judge.side_effect = [_Verdict(score=s) for s in scores]
    sampled = SampledStructuralSubagent(
        underlying=underlying, invariants_check_fn=invariants_fn,
        roslyn_check_fn=roslyn, judge=judge, n=n)
    chosen = await sampled.generate_code(
        task_brief=_brief(), skill_content="",
        rag_snippets=[("snip_a", "t", "b")])
    return chosen, underlying, judge


def _props(*suffixes): return [_proposal(code_suffix=s) for s in suffixes]


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_n_equals_three_calls_underlying_three_times():
    chosen, underlying, _ = await _run(
        n=3, candidates=_props("// a", "// b", "// c"),
        invariants_fn=lambda _: [], scores=[0.5, 0.9, 0.7])
    assert underlying.generate_code.await_count == 3
    assert chosen.csharp_code.endswith("// b")  # highest score


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_invariants_screen_drops_violators():
    inv = lambda p: ["v"] if p.csharp_code.endswith("// bad") else []
    chosen, _, judge = await _run(
        n=3, candidates=_props("// bad", "// good", "// bad"),
        invariants_fn=inv, scores=[1.0])
    assert chosen.csharp_code.endswith("// good")
    assert judge.judge.await_count == 1


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_roslyn_screen_drops_failures():
    async def roslyn(p, version):
        ok = p.csharp_code.endswith("// b")
        return CompileResult(success=ok, code=p.csharp_code,
            assembly_id="asm" if ok else None, error=None if ok else "syntax")
    chosen, _, judge = await _run(
        n=3, candidates=_props("// a", "// b", "// c"),
        invariants_fn=lambda _: [], roslyn=roslyn, scores=[0.6])
    assert chosen.csharp_code.endswith("// b")
    assert judge.judge.await_count == 1


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_all_screens_fail_returns_first_candidate():
    chosen, _, judge = await _run(
        n=2, candidates=_props("// a", "// b"),
        invariants_fn=lambda _: ["violation"])
    assert chosen.csharp_code.endswith("// a")
    judge.judge.assert_not_called()


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_all_roslyn_fail_returns_first_candidate():
    async def roslyn(p, version):
        return CompileResult(success=False, code=p.csharp_code, error="syntax")
    chosen, _, judge = await _run(
        n=2, candidates=_props("// a", "// b"),
        invariants_fn=lambda _: [], roslyn=roslyn)
    assert chosen.csharp_code.endswith("// a")
    judge.judge.assert_not_called()


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_one_candidate_failure_does_not_cancel_others():
    """Wave 6A B#5 — if one of N candidate generations raises, the other
    candidates must still flow through screening + ranking. Mirrors Wave 3 N2
    on GeometryGate.gather. Before this fix, asyncio.gather would cancel the
    peers as soon as one task raised, leaving the dispatch with no proposal.
    """
    underlying = AsyncMock()
    # 3 candidates: middle one raises, others succeed
    p_a = _proposal(code_suffix="// a")
    p_c = _proposal(code_suffix="// c")
    underlying.generate_code.side_effect = [
        p_a,
        RuntimeError("LLM provider 503"),
        p_c,
    ]
    judge = AsyncMock()
    judge.judge.side_effect = [_Verdict(score=0.7), _Verdict(score=0.9)]
    sampled = SampledStructuralSubagent(
        underlying=underlying, invariants_check_fn=lambda _: [],
        roslyn_check_fn=None, judge=judge, n=3,
    )
    chosen = await sampled.generate_code(
        task_brief=_brief(), skill_content="",
        rag_snippets=[("snip_a", "t", "b")],
    )
    # Two survivors reached the judge; highest score (// c, score=0.9) wins.
    assert chosen.csharp_code.endswith("// c")
    assert judge.judge.await_count == 2


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_one_roslyn_failure_does_not_cancel_peers():
    """Wave 6A B#5 — roslyn-check exception on one candidate must drop that
    candidate (treated as screen failure) without canceling the peer checks.
    """
    underlying = AsyncMock()
    underlying.generate_code.side_effect = _props("// a", "// b", "// c")
    judge = AsyncMock()
    judge.judge.return_value = _Verdict(score=0.8)

    async def _roslyn(p, version):
        if p.csharp_code.endswith("// b"):
            raise RuntimeError("compile-service down")
        return CompileResult(success=True, code=p.csharp_code, assembly_id="asm")

    sampled = SampledStructuralSubagent(
        underlying=underlying, invariants_check_fn=lambda _: [],
        roslyn_check_fn=_roslyn, judge=judge, n=3,
    )
    chosen = await sampled.generate_code(
        task_brief=_brief(), skill_content="",
        rag_snippets=[("snip_a", "t", "b")],
    )
    # 2 survivors (// a, // c) reached the judge; the raising candidate dropped.
    assert chosen.csharp_code.endswith(("// a", "// c"))
    assert judge.judge.await_count == 2


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_sampling_one_judge_failure_does_not_cancel_ranking():
    """Wave 6A B#5 — judge exception on one candidate must drop that
    candidate from the ranking; remaining survivors are ranked normally.
    """
    underlying = AsyncMock()
    underlying.generate_code.side_effect = _props("// a", "// b", "// c")
    judge = AsyncMock()
    judge.judge.side_effect = [
        _Verdict(score=0.5),
        RuntimeError("judge timeout"),
        _Verdict(score=0.9),
    ]
    sampled = SampledStructuralSubagent(
        underlying=underlying, invariants_check_fn=lambda _: [],
        roslyn_check_fn=None, judge=judge, n=3,
    )
    chosen = await sampled.generate_code(
        task_brief=_brief(), skill_content="",
        rag_snippets=[("snip_a", "t", "b")],
    )
    # // b excluded (judge raised); // c wins (highest score 0.9).
    assert chosen.csharp_code.endswith("// c")


@pytest.mark.tier0
@pytest.mark.parametrize("value,expected", [
    # Happy path
    ("3", 3), ("1", 1), (None, 1),
    # Audit T4 — ValueError branch (non-integer): falls back to 1
    ("abc", 1),     # not numeric at all
    ("3.0", 1),     # float string: int("3.0") raises ValueError
    # Audit T4 — non-positive int branch (max(1, n) floors to 1)
    ("0", 1),
    ("-1", 1),
])
def test_resolve_default_n(monkeypatch, value, expected):
    from kukai.modeling.subagent.sampling import _resolve_default_n
    if value is None:
        monkeypatch.delenv("KUKAI_SAMPLING_N", raising=False)
    else:
        monkeypatch.setenv("KUKAI_SAMPLING_N", value)
    assert _resolve_default_n() == expected


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_foreman_wraps_subagent_when_sampling_n_gt_one():
    """Smoke test: Foreman init with sampling_n=3 wraps the subagent."""
    from kukai.modeling.execution.gates import (
        CompileGate, CountValidationGate, ExecuteGate)
    from kukai.modeling.execution.queue import ExecutionQueue
    from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient
    from kukai.modeling.foreman.dispatcher import Foreman
    from kukai.modeling.state.projections.project_state import ProjectState

    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="mock_session"),
        count_gate=CountValidationGate(),
    )

    class _Stub:
        async def resolve(self, intent): raise NotImplementedError
        async def generate_code(self, **kw): raise NotImplementedError
        def load(self, p): return ""
        async def judge(self, p, b): return type("V", (), {"score": 1.0})()
        async def compile(self, code, revit_version="2026"): raise NotImplementedError
        async def complete(self, prompt): raise NotImplementedError

    s = _Stub()
    from kukai.modeling.foreman.config import ForemanRepair, ForemanSampling
    f = Foreman(
        project_id="p1", resolver=s, subagent=s, execution_queue=queue,
        skill_loader=s, rag_snippets=[],
        project_state_provider=lambda: ProjectState.initial(project_id="p1"),
        sampling=ForemanSampling(n=3),
        repair=ForemanRepair(judge=s, compile_client_for_repair=s, reflect_llm=s),
    )
    assert isinstance(f._subagent, SampledStructuralSubagent)
    assert f._subagent._n == 3
