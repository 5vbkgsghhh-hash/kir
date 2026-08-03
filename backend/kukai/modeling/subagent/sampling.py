"""SampledStructuralSubagent — self-consistency sampling wrapper.

Phase 3 Task 3.3. S* (arxiv 2502.14382) + Adaptive Consistency (arxiv
2305.11860). N parallel candidates -> invariants screen (free) -> Roslyn
screen (medium) -> Judge rank (~$0.001/call). Fall back to first candidate
if a screen drops everything.
"""
from __future__ import annotations
import asyncio
import os
from typing import Awaitable, Callable, Protocol

from kukai.modeling.schemas.execution import CompileResult
from kukai.modeling.schemas.llm import CodeProposal
from kukai.modeling.schemas.tasks import TaskBrief


class _InvariantsFn(Protocol):
    def __call__(self, proposal: CodeProposal) -> list: ...


class _UnderlyingSubagent(Protocol):
    async def generate_code(
        self, *, task_brief: TaskBrief, skill_content: str,
        rag_snippets: list[tuple[str, str, str]], repair_context=None,
    ) -> CodeProposal: ...


class _Judge(Protocol):
    async def judge(self, proposal: CodeProposal, brief: TaskBrief): ...


RoslynCheckFn = Callable[[CodeProposal, str], Awaitable[CompileResult]]


def _resolve_default_n() -> int:
    """KUKAI_SAMPLING_N env var -> int; falls back to 1 (CI=1, prod=3)."""
    raw = os.environ.get("KUKAI_SAMPLING_N")
    if raw is None:
        return 1
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


class SampledStructuralSubagent:
    """Self-consistency: N candidates -> screens -> Judge rank.

    Cost note: N=3 means 3x LLM cost per task. Default to N=1 in tests; flip
    to N=3 only via KUKAI_SAMPLING_N=3 env var or explicit constructor kwarg
    so the cost cliff is opt-in. Pair with `ForemanBudgetGuard` to drop back
    to N=1 if a project trips the budget tripwire.
    """

    def __init__(
        self,
        underlying: _UnderlyingSubagent,
        invariants_check_fn: _InvariantsFn,
        roslyn_check_fn: RoslynCheckFn | None,
        judge: _Judge,
        n: int = 3,
        temperature: float = 0.7,
    ):
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")
        self._underlying = underlying
        self._invariants_check_fn = invariants_check_fn
        self._roslyn_check_fn = roslyn_check_fn
        self._judge = judge
        self._n = n
        self._temperature = temperature

    async def generate_code(
        self, *, task_brief: TaskBrief, skill_content: str,
        rag_snippets: list[tuple[str, str, str]], repair_context=None,
    ) -> CodeProposal:
        # Wave 6A B#5 — mirror Wave 3 N2 (GeometryGate.gather) on the three
        # sampling-stage fan-outs. With bare asyncio.gather, a single failing
        # peer cancels the rest; one flaky LLM/roslyn/judge call could nuke
        # all N candidates and leave the dispatch with nothing to ship. Now
        # each stage uses return_exceptions=True and drops only the failures.
        raw_candidates = await asyncio.gather(*[
            self._underlying.generate_code(
                task_brief=task_brief, skill_content=skill_content,
                rag_snippets=rag_snippets, repair_context=repair_context)
            for _ in range(self._n)
        ], return_exceptions=True)
        candidates: list[CodeProposal] = [
            c for c in raw_candidates if not isinstance(c, BaseException)
        ]
        # If every generator raised we have no fallback at all — re-raise the
        # first exception so the caller (repair_loop) can surface it.
        if not candidates:
            for r in raw_candidates:
                if isinstance(r, BaseException):
                    raise r
            raise RuntimeError("no candidates and no captured exception")
        if self._n == 1:
            return candidates[0]

        screened = [c for c in candidates if not self._invariants_check_fn(c)]
        if not screened:
            return candidates[0]

        if self._roslyn_check_fn is not None:
            results = await asyncio.gather(*[
                self._roslyn_check_fn(c, task_brief.revit_version) for c in screened
            ], return_exceptions=True)
            # A failed roslyn check (exception) treats that candidate as a
            # screen-failure (excluded from survivors), same as success=False.
            screened = [
                c for c, r in zip(screened, results)
                if (not isinstance(r, BaseException)) and r.success
            ]
            if not screened:
                return candidates[0]

        raw_verdicts = await asyncio.gather(*[
            self._judge.judge(c, task_brief) for c in screened
        ], return_exceptions=True)
        # Drop candidates whose judge call exploded; rank the rest by score.
        survivors = [
            (c, v) for c, v in zip(screened, raw_verdicts)
            if not isinstance(v, BaseException)
        ]
        if not survivors:
            return candidates[0]
        ranked = sorted(survivors, key=lambda pair: -pair[1].score)
        return ranked[0][0]
