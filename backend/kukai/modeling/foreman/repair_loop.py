"""Reflexion verbal-repair loop (max 3 attempts).

Sources: Shinn et al., "Reflexion: language agents with verbal reinforcement
learning" (arXiv 2303.11366); "Static analysis feedback loop" (arXiv 2508.14419,
plateau after 3 iter). For each attempt: invariant gate → compile gate → judge
gate. On any failure: hash signature; if already seen → give up; else compute
verbal reflection via the LLM and feed it back via RepairContext.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from kukai.modeling.execution.invariants import InvariantViolation, check_proposal_invariants
from kukai.modeling.judge.code_judge import JudgeSeverity, JudgeVerdict
from kukai.modeling.schemas.execution import CompileResult
from kukai.modeling.schemas.llm import CodeProposal
from kukai.modeling.schemas.tasks import TaskBrief
from kukai.modeling.subagent.structural import StructuralSubagent


@runtime_checkable
class CompileClientProto(Protocol):
    async def compile(self, code: str, revit_version: str = ...) -> CompileResult: ...


@runtime_checkable
class JudgeProto(Protocol):
    async def judge(self, proposal: CodeProposal, brief: TaskBrief) -> JudgeVerdict: ...


@runtime_checkable
class ReflectLLMProto(Protocol):
    async def complete(self, prompt: str) -> str: ...


# Back-compat aliases (Wave 5 R1 lifted leading underscores when these
# Protocols became part of the public Foreman sub-config schema).
_CompileClientProto = CompileClientProto
_JudgeProto = JudgeProto
_ReflectLLMProto = ReflectLLMProto


@dataclass(frozen=True)
class RepairContext:
    """Snapshot of one failed attempt, fed into the next generate_code() call."""
    attempt_number: int
    previous_proposal: CodeProposal
    failure_kind: str                      # "invariant" | "compile" | "judge"
    failure_signature: str
    diagnostics: list[str]
    verbal_reflection: str


@dataclass(frozen=True)
class RepairOutcome:
    """Final result of one repair_loop() call (exported for callers that prefer this over the tuple form)."""
    final_proposal: CodeProposal | None
    history: list[RepairContext] = field(default_factory=list)
    gave_up_reason: str | None = None


def _h(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8")); h.update(b"\x1f")
    return h.hexdigest()[:32]


def _hash_invariants(violations: list[InvariantViolation]) -> str:
    # Audit N11: include severity per violation. Two failures that share rule_id/message
    # but differ in severity are different repair surfaces — don't collapse them.
    return _h("invariant", *sorted(
        f"{v.rule_id}|{getattr(v, 'severity', '?')}|{v.message}"
        for v in violations
    ))


def _hash_compile_errors(result: CompileResult, attempt: int | None = None) -> str:
    # Audit N11: hash ALL errors (code|line|message), not just the first message.
    # Two compile failures with same first-error but different secondary errors
    # ARE distinct repair surfaces — the loop must give them another shot.
    #
    # Wave 6A B silent-failure: when result.errors == [] (compile-service
    # returned success=False with no diagnostic detail — e.g. internal 500,
    # malformed response), the hash inputs are constant and two consecutive
    # empty-errors attempts would collide → Reflexion's "seen-twice = give
    # up" trigger fires at attempt 2 instead of letting all 3 attempts run.
    # When `attempt` is supplied AND errors is empty, mix it into the hash
    # so each attempt produces a distinct signature. Caller in repair_loop()
    # passes the current loop index; standalone callers (e.g. the unit test
    # asserting "same diagnostics → same hash") may omit it.
    parts = ["compile", f"success={result.success}"]
    if not result.errors and attempt is not None:
        parts.append(f"empty_errors_attempt={attempt}")
    for e in result.errors:
        parts.append(f"{e.code}|{e.line}|{e.message}")
    return _h(*parts)


def _hash_judge_verdict(verdict: JudgeVerdict) -> str:
    # Audit N11: include severity. Same score/errors_detected with different
    # severity tier (e.g. MEDIUM vs HIGH) is a different repair signal.
    return _h(
        "judge",
        str(verdict.score),
        str(verdict.severity),
        *sorted(str(e) for e in verdict.errors_detected),
    )


_REFLECT_INVARIANT_PROMPT = (
    "Your last attempt failed these structural invariants:\n{diagnostics}\n\n"
    "In one paragraph, describe what you did wrong AND what you will change next. Be specific."
)
_REFLECT_COMPILE_PROMPT = (
    "Your last attempt failed Roslyn compilation:\n{diagnostics}\n\n"
    "In one paragraph, describe what you did wrong AND what you will change next. Be specific."
)
_REFLECT_JUDGE_PROMPT = (
    "An LLM code-judge flagged your last attempt (score={score}/5):\n"
    "Errors detected:\n{errors}\nSuggestions:\n{suggestions}\n\n"
    "In one paragraph, describe what you did wrong AND what you will change next."
)


async def _reflect_invariants(llm, violations):
    diag = "\n".join(f"- [{v.rule_id}] {v.message}" for v in violations)
    return await llm.complete(_REFLECT_INVARIANT_PROMPT.format(diagnostics=diag))


async def _reflect_compile(llm, result):
    return await llm.complete(_REFLECT_COMPILE_PROMPT.format(diagnostics=result.error or "(no error)"))


async def _reflect_judge(llm, verdict):
    errs = "\n".join(f"- {e}" for e in verdict.errors_detected) or "- (none)"
    sugg = "\n".join(f"- {s}" for s in verdict.suggestions) or "- (none)"
    return await llm.complete(_REFLECT_JUDGE_PROMPT.format(
        score=verdict.score, errors=errs, suggestions=sugg))


async def repair_loop(
    *,
    subagent: StructuralSubagent,
    judge: JudgeProto,
    compile_client: CompileClientProto,
    brief: TaskBrief,
    skill: str,
    rag: list[tuple[str, str, str]],
    reflect_llm: ReflectLLMProto,
    max_attempts: int = 3,
) -> tuple[CodeProposal | None, list[RepairContext]]:
    """Returns (final_proposal_or_None, history_of_attempts).

    History contains one entry per FAILED attempt; on full success history==[].
    """
    history: list[RepairContext] = []
    repair_context: RepairContext | None = None
    seen: set[str] = set()

    for attempt in range(1, max_attempts + 1):
        proposal = await subagent.generate_code(
            task_brief=brief, skill_content=skill, rag_snippets=rag,
            repair_context=repair_context,
        )

        # Stage 1 — invariants
        violations = check_proposal_invariants(proposal)
        if violations:
            sig = _hash_invariants(violations)
            if sig in seen:
                return None, history
            seen.add(sig)
            reflection = await _reflect_invariants(reflect_llm, violations)
            repair_context = RepairContext(
                attempt_number=attempt, previous_proposal=proposal,
                failure_kind="invariant", failure_signature=sig,
                diagnostics=[v.message for v in violations],
                verbal_reflection=reflection,
            )
            history.append(repair_context); continue

        # Stage 2 — compile (Fix D: forward brief.revit_version so multi-version
        # tasks compile against the correct Revit reference set, not the 2026
        # default. Silent version mismatch caused subtle CS errors that the
        # repair loop couldn't reflect on.)
        compile_result = await compile_client.compile(
            proposal.csharp_code, revit_version=brief.revit_version,
        )
        if not compile_result.success:
            # Wave 6A B silent-failure: pass `attempt` so empty-errors results
            # produce distinct hashes per attempt and don't false-trigger
            # "seen-twice = give up" when compile-service returns success=False
            # with no diagnostic detail.
            sig = _hash_compile_errors(compile_result, attempt=attempt)
            if sig in seen:
                return None, history
            seen.add(sig)
            reflection = await _reflect_compile(reflect_llm, compile_result)
            repair_context = RepairContext(
                attempt_number=attempt, previous_proposal=proposal,
                failure_kind="compile", failure_signature=sig,
                diagnostics=[compile_result.error or ""],
                verbal_reflection=reflection,
            )
            history.append(repair_context); continue

        # Stage 3 — judge
        verdict = await judge.judge(proposal, brief)
        if verdict.severity == JudgeSeverity.CRITICAL or verdict.score < 4:
            sig = _hash_judge_verdict(verdict)
            if sig in seen:
                return None, history
            seen.add(sig)
            reflection = await _reflect_judge(reflect_llm, verdict)
            repair_context = RepairContext(
                attempt_number=attempt, previous_proposal=proposal,
                failure_kind="judge", failure_signature=sig,
                diagnostics=list(str(e) for e in verdict.errors_detected) + list(verdict.suggestions),
                verbal_reflection=reflection,
            )
            history.append(repair_context); continue

        # All gates green
        return proposal, history

    return None, history
