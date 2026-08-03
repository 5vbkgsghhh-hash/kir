"""Targeted single-task replan on VF violation (Phase 4 Task 1, VeriMAP).

When dispatch_task succeeds through L5.5 but declared_outputs don't match
actuals, we regenerate JUST that PlanTask and re-execute once (no recursion).
Distinct from Phase 2's repair_loop, which handles compile/execute failures —
this handles *semantic* failures: code ran, wrong thing produced.
"""
from __future__ import annotations
from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from kukai.modeling.schemas.foreman import (
    PlanTask, ReviewIssue, ReviewSeverity, ReviewVerdict,
)
from kukai.modeling.schemas.llm import CodeProposal, DeclaredOutputs
from kukai.modeling.schemas.tasks import TaskBrief


class VFViolation(BaseModel):
    model_config = ConfigDict(frozen=True)
    plan_task_id: str
    vf_description: str
    field_name: str
    declared: str
    actual: str
    assertion_text: str | None = None


class VFEvaluation(BaseModel):
    """Result of running a VF against post-execute actuals.

    Distinguishes 'declared field violated' (mismatched values) from
    'declared field unobservable' (actual is None for a non-None declared
    field). Until `_collect_actuals` materializes real level/family/param
    observations, unobservable fields must NOT trigger false-positive
    replans — they're skipped and surfaced via `skipped` for observability.
    """
    model_config = ConfigDict(frozen=True)

    violations: list[VFViolation] = []
    skipped: list[str] = []


def evaluate_verification_function(
    *,
    plan_task: PlanTask,
    declared_outputs: DeclaredOutputs,
    actual_count: int,
    actual_category: str | None,
    actual_parameters: dict[str, str],
    actual_level_name: str | None,
    actual_family_name: str | None,
) -> VFEvaluation:
    """Run the PlanTask's VF against post-execute actuals.

    Returns VFEvaluation: empty violations = pass; skipped lists fields the
    declarer named but whose actual is currently unobservable from
    `_collect_actuals` (will be wired in Phase 5). Skipped is informational
    only — does NOT trigger replan.
    """
    vf = plan_task.verification_function
    if vf is None:
        return VFEvaluation()

    violations: list[VFViolation] = []
    skipped: list[str] = []

    def _add(field, declared_str, actual_str, assertion_text=None):
        violations.append(VFViolation(
            plan_task_id=plan_task.plan_task_id, vf_description=vf.description,
            field_name=field, declared=declared_str, actual=actual_str,
            assertion_text=assertion_text,
        ))

    for field_name in vf.must_hold_outputs:
        d = declared_outputs
        if field_name == "expected_element_count":
            if d.expected_element_count != actual_count:
                _add(field_name, str(d.expected_element_count), str(actual_count))
        elif field_name == "expected_category":
            if actual_category is None:
                # Unobservable — never happens today (brief.category passes
                # through) but kept symmetric with other fields for safety.
                skipped.append(field_name)
            elif d.expected_category != actual_category:
                _add(field_name, d.expected_category, actual_category)
        elif field_name == "expected_level_name":
            if d.expected_level_name is not None and actual_level_name is None:
                skipped.append(field_name)
            elif d.expected_level_name is not None and d.expected_level_name != actual_level_name:
                _add(field_name, d.expected_level_name, str(actual_level_name))
        elif field_name == "expected_family_name":
            if d.expected_family_name is not None and actual_family_name is None:
                skipped.append(field_name)
            elif d.expected_family_name is not None and d.expected_family_name != actual_family_name:
                _add(field_name, d.expected_family_name, str(actual_family_name))
        elif field_name == "expected_parameter_values":
            if d.expected_parameter_values and not actual_parameters:
                # All declared params unobservable — skip the whole field.
                skipped.append(field_name)
            else:
                for k, v in d.expected_parameter_values.items():
                    if k not in actual_parameters:
                        skipped.append(f"expected_parameter_values[{k!r}]")
                    elif actual_parameters.get(k) != v:
                        _add(f"expected_parameter_values[{k!r}]", v, str(actual_parameters.get(k)))
        else:
            _add(field_name, "<unknown field>", "<n/a>")

    namespace = {
        "declared": declared_outputs, "actual_count": actual_count,
        "actual_category": actual_category, "actual_parameters": actual_parameters,
        "actual_level_name": actual_level_name, "actual_family_name": actual_family_name,
    }
    # Safe restricted eval: builtins stripped, namespace limited to actuals/declared.
    # VeriMAP-style assertion runner (Phase 4 Task 1). NOT user-input — VFs come from
    # the Foreman's hand-authored plan (or future LLM-vetted planner).
    _safe_globals = {"__builtins__": {}}
    for expr in vf.python_assertions:
        try:
            ok = bool(eval(expr, _safe_globals, namespace))  # noqa: S307
        except Exception as exc:  # noqa: BLE001
            _add("<python_assertion>", expr,
                 f"<raised {type(exc).__name__}: {exc}>", assertion_text=expr)
            continue
        if not ok:
            _add("<python_assertion>", expr, "False", assertion_text=expr)

    return VFEvaluation(violations=violations, skipped=skipped)


async def replan_single_task(
    *,
    plan_task: PlanTask,
    brief: TaskBrief,
    violations: list[VFViolation],
    regenerate: Callable[[TaskBrief, list[VFViolation]], Awaitable[CodeProposal]],
) -> tuple[CodeProposal, ReviewVerdict]:
    """Single-retry regen after VF violation. Caller re-evaluates the VF."""
    proposal = await regenerate(brief, violations)
    verdict = ReviewVerdict(
        passed=True,
        issues=[ReviewIssue(
            severity=ReviewSeverity.INFO, category="vf_replan",
            detail=f"regenerated after {len(violations)} VF violation(s)")],
        summary="regenerated after VF violation",
    )
    return proposal, verdict
