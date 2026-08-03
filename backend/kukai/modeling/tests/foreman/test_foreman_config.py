"""Wave 5 R1 — Foreman sub-config validation tests.

Covers the three cross-config invariants that grew out of refactoring 9
loose optional kwargs into 4 typed pydantic sub-configs:

  1. ForemanRepair requires all three fields (judge, compile_client_for_repair,
     reflect_llm) — partial repair wiring used to be a silent runtime no-op.
  2. Foreman with sampling.n > 1 but no repair sub-config — used to silently
     fall back to Flash-only because `judge is None` short-circuited the
     SampledStructuralSubagent path.
  3. Foreman with sampling.n == 1 must work without repair (the common
     single-shot path, no Judge needed).
"""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.bridge.mocks import (
    MockBridgeClient, MockCompileClient, MockModelQueryClient,
)
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate,
)
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman.config import (
    ForemanRepair, ForemanRouting, ForemanSampling, ForemanVerifiers,
)
from kukai.modeling.foreman.dispatcher import Foreman
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.state.projections.project_state import ProjectState
from kukai.modeling.subagent.structural import StructuralSubagent


class _Stub:
    """Minimal stub that satisfies all of (Judge, CompileClient, ReflectLLM)
    via duck typing. Not exercised — only used to construct ForemanRepair."""
    async def judge(self, proposal, brief):
        from kukai.modeling.judge.code_judge import JudgeSeverity, JudgeVerdict
        return JudgeVerdict(score=5, errors_detected=[], severity=JudgeSeverity.NONE,
                            suggestions=[], judge_explanation="ok ok")
    async def compile(self, code, revit_version="2026"):
        from kukai.modeling.schemas.execution import CompileResult
        return CompileResult(success=True, code=code, assembly_id="stub")
    async def health(self): return True
    async def complete(self, prompt): return ""


def _bare_foreman_kwargs():
    llm = MockLLMClient()
    query = MockModelQueryClient()
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="mock"),
        count_gate=CountValidationGate(),
    )
    return dict(
        project_id="p1",
        resolver=Resolver(query),
        subagent=StructuralSubagent(llm),
        execution_queue=queue,
        skill_loader=type("L", (), {"load": lambda self, p: ""})(),
        rag_snippets=[],
        project_state_provider=lambda: ProjectState(),
    )


@pytest.mark.tier0
def test_foreman_repair_config_rejects_partial():
    """ForemanRepair must require all three fields (judge, compile_client_for_repair,
    reflect_llm) — partial config used to silently disable the repair loop."""
    s = _Stub()
    # Missing compile_client_for_repair AND reflect_llm.
    with pytest.raises(ValidationError):
        ForemanRepair(judge=s)
    # Missing reflect_llm.
    with pytest.raises(ValidationError):
        ForemanRepair(judge=s, compile_client_for_repair=s)
    # Missing judge.
    with pytest.raises(ValidationError):
        ForemanRepair(compile_client_for_repair=s, reflect_llm=s)
    # All three present — accepted.
    ok = ForemanRepair(judge=s, compile_client_for_repair=s, reflect_llm=s)
    assert ok.judge is s and ok.compile_client_for_repair is s and ok.reflect_llm is s


@pytest.mark.tier0
def test_foreman_sampling_without_repair_raises():
    """Foreman with sampling.n > 1 but no repair must fail at construction.
    Cross-config invariant — sub-configs only see their own fields, so this
    rule is enforced by Foreman.__init__ itself."""
    kw = _bare_foreman_kwargs()
    with pytest.raises(ValueError, match="sampling.n > 1 requires a ForemanRepair"):
        Foreman(sampling=ForemanSampling(n=3), **kw)


@pytest.mark.tier0
def test_foreman_sampling_n1_works_without_repair():
    """Sampling.n == 1 is the legacy single-shot path; no Judge required.
    Regression guard against over-eager validation."""
    kw = _bare_foreman_kwargs()
    f = Foreman(sampling=ForemanSampling(n=1), **kw)
    # When n == 1 the dispatcher uses the bare subagent (no sampler wrapper).
    from kukai.modeling.subagent.sampling import SampledStructuralSubagent
    assert not isinstance(f._subagent, SampledStructuralSubagent)


@pytest.mark.tier0
def test_foreman_sampling_n3_with_repair_wires_sampler():
    """Sampling.n > 1 + full ForemanRepair wraps the subagent in
    SampledStructuralSubagent (judge sourced from repair sub-config)."""
    s = _Stub()
    kw = _bare_foreman_kwargs()
    f = Foreman(
        sampling=ForemanSampling(n=3),
        repair=ForemanRepair(judge=s, compile_client_for_repair=s, reflect_llm=s),
        **kw,
    )
    from kukai.modeling.subagent.sampling import SampledStructuralSubagent
    assert isinstance(f._subagent, SampledStructuralSubagent)
    assert f._subagent._n == 3
