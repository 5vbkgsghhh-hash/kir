"""Reflexion verbal-repair loop unit tests.

Six scenarios:
  1. success on first attempt — no repair, history empty
  2. invariant violation on 1st, recovers on 2nd
  3. compile failure on 2nd, recovers on 3rd
  4. identical signature on consecutive attempts → give up
  5. exhausts max_attempts=3 → returns None, history has 3 entries
  6. judge-triggered repair (compile passes, judge score < 4) recovers
"""
from __future__ import annotations
from typing import Any
import pytest

from kukai.modeling.foreman.repair_loop import RepairContext, repair_loop
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.schemas.execution import CompileResult
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, ParameterRef, Phase, TaskBrief, Tier,
)
from kukai.modeling.subagent.structural import StructuralSubagent


def _checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _brief(task_id: str = "tid_xxxx") -> TaskBrief:
    return TaskBrief(
        task_id=task_id, phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=0.0, y=0.0, z=0.0),
        family_symbol_id=10,
        parameter_map={"Mark": ParameterRef(name="Mark", scope="instance")},
        level_id=1, revit_version="2026",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, estimated_cost_usd=0.0,
    )


def _good_proposal(task_id: str = "tid_xxxx") -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code="// RAG:#snip_a\nusing(Transaction t = new Transaction(doc,\"Place column\")){t.Start();t.Commit();}\n__result__ = new int[] { 9000 };",
        explanation="ok",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"], transaction_name="Place column", revit_version="2026",
        failure_mode_checks=_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_a", api_called="NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )


def _bad_invariant_proposal(task_id: str = "tid_xxxx") -> CodeProposal:
    """No transaction block — triggers invariant violation in Phase 1's checker."""
    return CodeProposal(
        task_id=task_id, csharp_code="// RAG:#snip_a\n__result__ = new int[] { 9000 };",
        explanation="ok",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"], transaction_name="Place column", revit_version="2026",
        failure_mode_checks=_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_a", api_called="NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )


class _ReflectLLM:
    def __init__(self, reflections: list[str] | None = None):
        self._reflections = list(reflections or [])
        self._idx = 0

    async def complete(self, prompt: str) -> str:
        if self._idx >= len(self._reflections):
            return "I will fix the previous issue."
        out = self._reflections[self._idx]; self._idx += 1; return out


class _ScriptedCompile:
    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = responses
        self._idx = 0
        self.calls: list[tuple[str, str]] = []   # (code, revit_version)

    async def compile(self, code: str, revit_version: str = "2026") -> CompileResult:
        self.calls.append((code, revit_version))
        d = self._responses[self._idx] if self._idx < len(self._responses) else {"success": True, "assembly_id": "default"}
        self._idx += 1
        # Fix E: typed errors list, not legacy `error` kwarg (which pydantic v2
        # silently drops because CompileResult.error is a @property).
        from kukai.modeling.schemas.execution import CompileError
        errors = (
            [CompileError(code="SCRIPT", message=d["error"], line=0, column=0)]
            if d.get("error") else []
        )
        return CompileResult(
            success=bool(d.get("success", True)),
            code=code if d.get("success", True) else None,
            assembly_id=d.get("assembly_id"),
            errors=errors,
        )


class _ScriptedJudge:
    def __init__(self, scores: list[int]):
        self._scores = scores; self._idx = 0

    async def judge(self, proposal, brief):
        from kukai.modeling.judge.code_judge import JudgeSeverity, JudgeVerdict
        from kukai.modeling.schemas.llm import FailureCategory
        score = self._scores[self._idx] if self._idx < len(self._scores) else 5
        self._idx += 1
        sev = JudgeSeverity.NONE if score >= 4 else JudgeSeverity.CRITICAL
        return JudgeVerdict(
            score=score,
            errors_detected=[] if score >= 4 else [FailureCategory.SILENT_NO_OP],
            severity=sev,
            suggestions=[] if score >= 4 else ["use Transaction.Start()"],
            judge_explanation="code looks correct, all checks pass" if score >= 4 else "missing transaction wrapper around element creation",
        )


@pytest.mark.asyncio
async def test_success_on_first_attempt_no_repair():
    mock = MockLLMClient(); mock.queue_proposal(_good_proposal())
    subagent = StructuralSubagent(mock)
    proposal, history = await repair_loop(
        subagent=subagent, judge=_ScriptedJudge([5]),
        compile_client=_ScriptedCompile([{"success": True, "assembly_id": "a1"}]),
        brief=_brief(), skill="# Skill", rag=[("snip_a", "t", "b")],
        reflect_llm=_ReflectLLM(), max_attempts=3,
    )
    assert proposal is not None
    assert history == []


async def _run(proposals, *, compile_responses=None, judge_scores=(5,),
               reflections=("r",), max_attempts=3):
    mock = MockLLMClient()
    for p in proposals:
        mock.queue_proposal(p)
    return await repair_loop(
        subagent=StructuralSubagent(mock),
        judge=_ScriptedJudge(list(judge_scores)),
        compile_client=_ScriptedCompile(list(compile_responses or [])),
        brief=_brief(), skill="# S", rag=[("snip_a", "t", "b")],
        reflect_llm=_ReflectLLM(list(reflections)),
        max_attempts=max_attempts,
    )


@pytest.mark.asyncio
async def test_recover_on_second_attempt_after_invariant_fail():
    proposal, history = await _run(
        [_bad_invariant_proposal(), _good_proposal()],
        compile_responses=[{"success": True, "assembly_id": "a1"}],
        reflections=["I forgot the transaction block."],
    )
    assert proposal is not None and len(history) == 1
    assert history[0].failure_kind == "invariant"
    assert history[0].attempt_number == 1


@pytest.mark.asyncio
async def test_recover_on_third_attempt_invariant_then_compile():
    # attempt 1 invariant fail → attempt 2 compile fail → attempt 3 all green
    proposal, history = await _run(
        [_bad_invariant_proposal(), _good_proposal(), _good_proposal()],
        compile_responses=[
            {"success": False, "error": "CS0103: foo not defined"},
            {"success": True, "assembly_id": "a_ok"},
        ],
        reflections=["r1", "r2"],
    )
    assert proposal is not None and len(history) == 2
    assert history[0].failure_kind == "invariant"
    assert history[1].failure_kind == "compile"


@pytest.mark.asyncio
async def test_give_up_on_identical_signature():
    """Same invariant failure twice in a row → give up immediately."""
    proposal, history = await _run(
        [_bad_invariant_proposal(), _bad_invariant_proposal()],
        reflections=["thought I fixed it"],
    )
    assert proposal is None and len(history) == 1
    assert history[0].failure_kind == "invariant"


@pytest.mark.asyncio
async def test_give_up_at_max_attempts():
    """Three distinct invariant failures → exhaust max_attempts=3 and give up.

    Monkey-patch the invariant checker so each call produces a UNIQUE
    InvariantViolation message — that way `seen_signatures` doesn't short-circuit.
    """
    from kukai.modeling.execution import invariants as inv_mod
    counter = {"n": 0}
    original = inv_mod.check_proposal_invariants

    def _stub(prop):
        counter["n"] += 1
        return [inv_mod.InvariantViolation(
            rule_id="missing_transaction", message=f"version {counter['n']}", severity="error")]

    # Also patch the symbol imported into repair_loop module
    from kukai.modeling.foreman import repair_loop as rl_mod
    rl_original = rl_mod.check_proposal_invariants

    inv_mod.check_proposal_invariants = _stub  # type: ignore[assignment]
    rl_mod.check_proposal_invariants = _stub  # type: ignore[assignment]
    try:
        proposal, history = await _run(
            [_bad_invariant_proposal()] * 3,
            reflections=["r1", "r2", "r3"],
        )
    finally:
        inv_mod.check_proposal_invariants = original  # type: ignore[assignment]
        rl_mod.check_proposal_invariants = rl_original  # type: ignore[assignment]
    assert proposal is None and len(history) == 3


@pytest.mark.asyncio
async def test_repair_loop_forwards_revit_version():
    """Fix D: repair_loop must forward brief.revit_version to compile_client.compile
    so multi-version Revit tasks (2021-2024) don't silently compile against 2026
    references. Earlier the call site dropped the kwarg → defaulted to "2026".
    """
    brief_2024 = _brief().model_copy(update={"revit_version": "2024"})
    mock = MockLLMClient()
    # Proposal must declare the same revit_version as the brief (subagent
    # cross-checks). We only care about what the compile client receives.
    mock.queue_proposal(_good_proposal().model_copy(update={"revit_version": "2024"}))
    capturing = _ScriptedCompile([{"success": True, "assembly_id": "a1"}])
    proposal, history = await repair_loop(
        subagent=StructuralSubagent(mock), judge=_ScriptedJudge([5]),
        compile_client=capturing,
        brief=brief_2024, skill="# Skill", rag=[("snip_a", "t", "b")],
        reflect_llm=_ReflectLLM(), max_attempts=3,
    )
    assert proposal is not None and history == []
    # Exactly one compile call was made, and it carried revit_version="2024".
    assert len(capturing.calls) == 1
    _code, captured_version = capturing.calls[0]
    assert captured_version == "2024", (
        f"repair_loop did not forward revit_version; got {captured_version!r}"
    )


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_empty_errors_do_not_collide_across_attempts():
    """Wave 6A B silent-failure — if compile_service keeps returning
    success=False with errors=[] (e.g. internal 500, malformed response),
    the per-attempt hash signatures must differ so Reflexion's
    'seen-twice = give up' trigger does NOT fire prematurely. The loop
    should exhaust all 3 attempts instead of bailing at attempt 2.
    """
    # Three failed compile responses with NO error details — old behaviour
    # hashed them identically → give up at attempt 2.
    compile_responses = [
        {"success": False},  # no "error" key → errors=[] in _ScriptedCompile
        {"success": False},
        {"success": False},
    ]
    capturing = _ScriptedCompile(compile_responses)
    mock = MockLLMClient()
    mock.queue_proposal(_good_proposal())
    mock.queue_proposal(_good_proposal())
    mock.queue_proposal(_good_proposal())
    proposal, history = await repair_loop(
        subagent=StructuralSubagent(mock),
        judge=_ScriptedJudge([5, 5, 5]),
        compile_client=capturing,
        brief=_brief(), skill="# S", rag=[("snip_a", "t", "b")],
        reflect_llm=_ReflectLLM(["r1", "r2", "r3"]),
        max_attempts=3,
    )
    # All three attempts ran (compile_client was called 3 times) instead of
    # the loop bailing at attempt 2 due to a false hash collision.
    assert len(capturing.calls) == 3, (
        f"empty-errors hash collision: loop only ran {len(capturing.calls)} attempts"
    )
    assert proposal is None
    assert len(history) == 3
    assert all(h.failure_kind == "compile" for h in history)


@pytest.mark.tier0
def test_hash_compile_errors_empty_errors_distinct_per_attempt():
    """Wave 6A B silent-failure — direct unit test on _hash_compile_errors:
    when called with empty errors AND distinct attempt indices, hashes must
    differ. When called WITHOUT attempt (back-compat callers), empty-errors
    results still collapse to the same hash (deterministic by-content)."""
    from kukai.modeling.foreman.repair_loop import _hash_compile_errors
    from kukai.modeling.schemas.execution import CompileResult

    r = CompileResult(success=False, errors=[])
    # No attempt context → same hash (old behaviour preserved for callers
    # that don't have an attempt index).
    assert _hash_compile_errors(r) == _hash_compile_errors(r)
    # With attempt indices → distinct hashes per attempt.
    h1 = _hash_compile_errors(r, attempt=1)
    h2 = _hash_compile_errors(r, attempt=2)
    h3 = _hash_compile_errors(r, attempt=3)
    assert h1 != h2 != h3 != h1, "empty-errors hashes must differ per attempt"


@pytest.mark.tier0
def test_hash_compile_errors_distinguishes_secondary_errors():
    """Audit N11: same first-error message but different SECOND errors must
    produce distinct hashes. Old impl hashed only result.error (first msg)
    and collapsed them, causing 'identical signature → give up' false-positives
    when the second-pass diagnostic mix actually changed."""
    from kukai.modeling.foreman.repair_loop import _hash_compile_errors
    from kukai.modeling.schemas.execution import CompileError, CompileResult

    r_a = CompileResult(success=False, errors=[
        CompileError(code="CS1002", message="; expected", line=10, column=1),
        CompileError(code="CS0103", message="name 'doc' missing", line=12, column=5),
    ])
    r_b = CompileResult(success=False, errors=[
        CompileError(code="CS1002", message="; expected", line=10, column=1),
        CompileError(code="CS0246", message="type 'Foo' not found", line=20, column=5),
    ])
    # Same first-error string; different secondary errors → must hash differently.
    assert r_a.error == r_b.error == "; expected"
    assert _hash_compile_errors(r_a) != _hash_compile_errors(r_b)
    # And identical results hash identically (sanity).
    assert _hash_compile_errors(r_a) == _hash_compile_errors(r_a.model_copy(deep=True))


class _CapturingLLM:
    """Test LLM client that records LLMPromptInputs across calls AND replays
    scripted CodeProposals. Used to assert the Reflexion reflection text actually
    reaches attempt 2's persona prompt (audit T2)."""

    def __init__(self, proposals: list[CodeProposal]):
        self._proposals = list(proposals)
        self._idx = 0
        self.captured_prompts: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.total_tokens_in = 0
        self.total_tokens_out = 0

    async def generate_code_proposal(self, inputs):
        self.captured_prompts.append(inputs.persona_prompt)
        self.calls.append({"persona_len": len(inputs.persona_prompt)})
        if self._idx >= len(self._proposals):
            raise RuntimeError(f"_CapturingLLM exhausted after {self._idx} calls")
        p = self._proposals[self._idx]
        self._idx += 1
        return p


@pytest.mark.asyncio
async def test_reflection_text_reaches_llm_prompt_on_attempt_2():
    """Audit T2: when attempt 1 fails, the verbal reflection string from
    `reflect_llm` must be embedded into attempt 2's persona_prompt via the
    REPAIR_PROMPT_TEMPLATE. Earlier the wiring existed but no test asserted
    the text actually flowed through to the LLM input.
    """
    canned_reflection = "I forgot the using(Transaction) wrapper — adding it now"
    llm = _CapturingLLM([_bad_invariant_proposal(), _good_proposal()])
    proposal, history = await repair_loop(
        subagent=StructuralSubagent(llm),
        judge=_ScriptedJudge([5]),
        compile_client=_ScriptedCompile([{"success": True, "assembly_id": "a1"}]),
        brief=_brief(), skill="# S", rag=[("snip_a", "t", "b")],
        reflect_llm=_ReflectLLM([canned_reflection]),
        max_attempts=3,
    )
    # Recovery happened on attempt 2, so 2 prompts were captured.
    assert proposal is not None and len(history) == 1
    assert len(llm.captured_prompts) == 2, (
        f"expected 2 LLM calls, got {len(llm.captured_prompts)}"
    )
    # Attempt 1 prompt has NO repair block.
    assert "Previous attempt feedback" not in llm.captured_prompts[0], (
        "attempt 1 should not contain a repair block"
    )
    # Attempt 2 prompt has the repair block referencing the failed attempt #1
    # AND the verbatim reflection text from reflect_llm.
    attempt_2_prompt = llm.captured_prompts[1]
    assert "Previous attempt feedback (attempt #1)" in attempt_2_prompt, (
        "attempt 2 prompt missing repair-block header referencing the failed attempt"
    )
    assert "Your previous attempt failed: invariant" in attempt_2_prompt, (
        "repair block missing failure_kind tag"
    )
    assert canned_reflection in attempt_2_prompt, (
        f"verbal reflection {canned_reflection!r} did not reach attempt-2 prompt"
    )


@pytest.mark.asyncio
async def test_judge_triggered_repair_recovers():
    """Compile passes both times; judge rejects first (score=2), accepts second (score=5)."""
    _tx_prefix = "// RAG:#snip_a\nusing(Transaction t = new Transaction(doc,\"Place column\")){t.Start();t.Commit();}\n"
    p1 = _good_proposal().model_copy(update={"csharp_code": _tx_prefix + "// weak v1\n__result__ = new int[] { 9000 };"})
    p2 = _good_proposal().model_copy(update={"csharp_code": _tx_prefix + "// strong v2\n__result__ = new int[] { 9000 };"})
    proposal, history = await _run(
        [p1, p2],
        compile_responses=[
            {"success": True, "assembly_id": "a1"},
            {"success": True, "assembly_id": "a2"},
        ],
        judge_scores=(2, 5),
        reflections=["improve identifier choice"],
    )
    assert proposal is not None and len(history) == 1
    assert history[0].failure_kind == "judge"
