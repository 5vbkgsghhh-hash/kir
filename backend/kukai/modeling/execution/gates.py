"""Per-task gates L3, L4, L5 of the Quality Defense Layer.

L3 = Roslyn compile gate (deterministic)
L4 = Revit execute gate (via bridge, deterministic catch on exception)
L5 = Element count validation (deterministic; expected vs actual)

Each gate is async and returns (GateOutcome, raw_payload). The queue
orchestrates them in order and rolls outcomes into ExecutionResult.
"""
from __future__ import annotations
import re as _re
import time
from typing import Any

from kukai.modeling.execution.invariants import check_proposal_invariants
from kukai.modeling.schemas.execution import (
    CompileError,
    CompileResult,
    ExecutionTask,
    GateOutcome,
)
from kukai.modeling.schemas.llm import CodeProposal


class CompileGate:
    """L3 — Property invariants then Roslyn compile via HttpCompileClient (or mock).

    The invariants pre-check short-circuits Roslyn for obviously-broken
    proposals (saves a network round-trip and produces a stable rule_id for logs).
    """

    def __init__(self, compile_client):
        self._client = compile_client

    async def run(
        self,
        task: ExecutionTask,
        proposal: CodeProposal | None = None,
    ) -> tuple[GateOutcome, CompileResult]:
        start = time.monotonic()

        # 0. Property invariants — only when caller supplied the originating proposal.
        if proposal is not None:
            violations = check_proposal_invariants(proposal)
            blocking = [v for v in violations if v.severity == "BLOCKING"]
            if blocking:
                first = blocking[0]
                err = f"invariant_violation: {first.rule_id}: {first.message}"
                duration_ms = int((time.monotonic() - start) * 1000)
                outcome = GateOutcome(
                    name="L3_compile",
                    passed=False,
                    duration_ms=duration_ms,
                    error=err,
                )
                return outcome, CompileResult(
                    success=False,
                    errors=[CompileError(code="INVARIANT", message=err, line=0, column=0)],
                )

        # L3 — Roslyn
        # Wave 6A B#2: any exception from the compile client (httpx 5xx,
        # socket timeout, etc.) used to propagate out of the gate and abort
        # the entire phase. Now we wrap it and return a failure outcome so
        # the queue / dispatcher can mark the task failed and continue.
        try:
            result = await self._client.compile(task.csharp_code, revit_version=task.revit_version)
        except Exception as e:  # not BaseException — preserve KeyboardInterrupt/SystemExit
            duration_ms = int((time.monotonic() - start) * 1000)
            err = f"{type(e).__name__}: {str(e)[:200]}"
            outcome = GateOutcome(
                name="L3_compile",
                passed=False,
                duration_ms=duration_ms,
                error=err,
            )
            return outcome, CompileResult(
                success=False,
                errors=[CompileError(code="GATE_EXCEPTION", message=err, line=0, column=0)],
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        outcome = GateOutcome(
            name="L3_compile",
            passed=result.success,
            duration_ms=duration_ms,
            error=result.error,
        )
        return outcome, result


class ExecuteGate:
    """L4 — Execute compiled code via bridge."""

    def __init__(self, bridge_client, session_id: str):
        self._client = bridge_client
        self._session_id = session_id

    async def run(self, task: ExecutionTask) -> tuple[GateOutcome, dict[str, Any]]:
        start = time.monotonic()
        # Wave 6A B#2: any exception from the bridge client (websocket drop,
        # Revit hang, transport error) used to propagate out of the gate and
        # abort the entire phase. Now we wrap it and return a failure outcome
        # plus a synthetic payload that downstream gates can safely consume.
        try:
            payload = await self._client.execute_code(
                session_id=self._session_id,
                csharp_code=task.csharp_code,
                expected_count=task.expected_elements.count,
            )
        except Exception as e:  # not BaseException — preserve KeyboardInterrupt/SystemExit
            duration_ms = int((time.monotonic() - start) * 1000)
            err = f"{type(e).__name__}: {str(e)[:200]}"
            outcome = GateOutcome(
                name="L4_execute",
                passed=False,
                duration_ms=duration_ms,
                error=err,
            )
            return outcome, {
                "success": False,
                "element_ids": [],
                "duration_ms": 0,
                "error": err,
            }
        duration_ms = int((time.monotonic() - start) * 1000)
        outcome = GateOutcome(
            name="L4_execute",
            passed=bool(payload.get("success", False)),
            duration_ms=duration_ms,
            error=payload.get("error"),
        )
        return outcome, payload


class CountValidationGate:
    """L5 — Compare actual element_ids count to expected_elements.count."""

    def run(self, task: ExecutionTask, element_ids: list[int]) -> GateOutcome:
        expected = task.expected_elements.count
        actual = len(element_ids)
        passed = actual == expected
        error = None if passed else (
            f"count mismatch: expected {expected}, got {actual}"
        )
        return GateOutcome(
            name="L5_count",
            passed=passed,
            duration_ms=0,
            error=error,
        )


class PropertyValidationGate:
    """L5.5 — verify each created element's properties match the brief.

    Catches:
      - silent_no_op (element exists but Mark/Level wrong)
      - cross_discipline_contamination (right category but wrong properties)
      - count-matches-but-properties-don't class of failures

    For each element_id we call query_element_properties(eid) and validate:
      1. If brief.expected_elements.naming_pattern set -> 'Mark' must match.
      2. If brief.expected_elements.level_name set -> 'Level' must equal it.
      3. Every name in brief.expected_elements.required_parameters MUST be a
         key in the returned dict AND have a non-empty value.
    """

    def __init__(self, query_client):
        self._query = query_client

    async def run(self, task: ExecutionTask, element_ids: list[int]) -> GateOutcome:
        start = time.monotonic()
        naming = task.expected_elements.naming_pattern
        level_name = task.expected_elements.level_name
        required = task.expected_elements.required_parameters
        naming_re = _re.compile(naming) if naming else None

        for eid in element_ids:
            props = await self._query.query_element_properties(eid)
            if naming_re is not None:
                mark = props.get("Mark", "")
                if not naming_re.match(mark):
                    return GateOutcome(
                        name="L5.5_property", passed=False,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        error=f"element {eid}: Mark={mark!r} does not match {naming!r}",
                    )
            if level_name is not None:
                actual = props.get("Level", "")
                if actual != level_name:
                    return GateOutcome(
                        name="L5.5_property", passed=False,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        error=f"element {eid}: Level={actual!r} expected {level_name!r}",
                    )
            for pname in required:
                if not props.get(pname):
                    return GateOutcome(
                        name="L5.5_property", passed=False,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        error=f"element {eid}: required parameter {pname!r} missing or empty",
                    )

        return GateOutcome(
            name="L5.5_property", passed=True,
            duration_ms=int((time.monotonic() - start) * 1000),
            error=None,
        )
