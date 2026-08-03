"""Foreman orchestration schemas.

Per spec Section 5.2. The Foreman owns phase-level decisions. These types
are its inputs/outputs:

  - PlanTask: one item in a phase plan (what to build, where, how)
  - PhasePlan: an ordered list of PlanTask for a single phase
  - ReviewIssue / ReviewVerdict: deterministic per-proposal checklist outcome
  - PhaseRunResult: rolled-up phase outcome (after all tasks attempted)

PlanTask is INTENT-shaped (it carries a ResolverIntent, not a resolved TaskBrief)
so the Foreman can author a plan without touching the bridge yet. Resolution
happens at dispatch time, just before the Subagent call.
"""
from __future__ import annotations
import ast
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kukai.modeling.schemas.resolver import ResolverIntent
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, Tier


# Wave 5 R2 — AST whitelist for `VerificationFunction.python_assertions`.
#
# Each assertion string must parse to an expression composed only of these
# node types. Anything outside (Call, Lambda, dunder attribute, comprehension,
# import-via-builtins, walrus) is rejected at VF construction so a malicious
# or careless planner cannot smuggle arbitrary code into the eval namespace
# in foreman/replan.py.
#
# Patterns we MUST support (grep'd from existing fixtures + the plan's R2
# motivating example):
#   actual_count > 5
#   actual_count == 1 and 'Width' in actual_parameters
#   declared.expected_element_count == actual_count
#   'Width' in declared.expected_parameter_values
#   actual_parameters['Mark'] == declared.expected_category
#
# Closed set rather than open blacklist — adding a new construct is a
# deliberate, reviewed action.
_VF_ALLOWED_AST_NODES: frozenset[type[ast.AST]] = frozenset({
    ast.Expression, ast.Module,
    # Boolean / comparison / arithmetic structure
    ast.Compare, ast.BoolOp, ast.UnaryOp, ast.BinOp,
    # Operands
    ast.Name, ast.Constant, ast.Subscript, ast.Attribute,
    # Slicing primitives (Index/Slice — Index removed Python 3.9+, kept for safety)
    ast.Slice,
    # Contexts
    ast.Load,
    # Tuple/list literals (e.g. `x in (1, 2, 3)`)
    ast.Tuple, ast.List,
    # Comparison ops
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
    # Bool ops
    ast.And, ast.Or, ast.Not,
    # Unary ops
    ast.USub, ast.UAdd, ast.Invert,
    # Arithmetic ops (sometimes useful for tolerance comparisons)
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv, ast.Pow,
})


def _validate_vf_assertion(expr: str) -> None:
    """Parse and walk `expr`. Raise ValueError on any node outside the
    whitelist. Empty / whitespace-only string is also a ValueError —
    silent assertions would mask planner bugs."""
    if not expr or not expr.strip():
        raise ValueError("python_assertions entries must be non-empty expressions")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"python_assertion is not a valid Python expression: {expr!r} ({e.msg})")
    for node in ast.walk(tree):
        if type(node) not in _VF_ALLOWED_AST_NODES:
            raise ValueError(
                f"python_assertion contains disallowed AST node "
                f"{type(node).__name__!r} in {expr!r}. Allowed: "
                f"{sorted(t.__name__ for t in _VF_ALLOWED_AST_NODES)}"
            )


class ReviewSeverity(str, Enum):
    """Severity tiers for Foreman.review_code output."""
    BLOCKING = "blocking"     # must not execute
    WARNING = "warning"       # execute but record
    INFO = "info"             # log only


class ReviewIssue(BaseModel):
    """One finding from the deterministic CodeProposal review.

    Wave 5 R3 — `verifier_source` records which sub-verifier produced this
    issue. Optional (None) for back-compat — legacy callers that build
    ReviewIssue directly without going through correctness/geometry/safety
    helpers keep working. Set automatically by the helpers in
    foreman/verifiers/*.py. Enables telemetry + per-verifier disable in
    later phases.
    """
    model_config = ConfigDict(frozen=True)

    severity: ReviewSeverity
    category: str = Field(..., min_length=1, description="short stable identifier")
    detail: str = Field(..., min_length=1)
    verifier_source: Literal["correctness", "geometry", "safety"] | None = None


class ReviewVerdict(BaseModel):
    """Aggregate result of Foreman.review_code(proposal, brief)."""
    model_config = ConfigDict(frozen=True)

    passed: bool
    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _consistency(self) -> "ReviewVerdict":
        has_blocking = any(i.severity == ReviewSeverity.BLOCKING for i in self.issues)
        if self.passed and has_blocking:
            raise ValueError("passed=True is incompatible with a BLOCKING issue")
        if not self.passed and not self.issues:
            raise ValueError("passed=False requires at least one ReviewIssue")
        return self


# Audit N9 — closed-set of DeclaredOutputs fields that evaluate_verification_function
# knows how to compare. Anything outside this set is a typo at construction time, not
# a silent runtime '<unknown field>' violation that buries the planner's mistake.
_ALLOWED_MUST_HOLD_OUTPUTS: frozenset[str] = frozenset({
    "expected_element_count",
    "expected_category",
    "expected_level_name",
    "expected_family_name",
    "expected_parameter_values",
})


class VerificationFunction(BaseModel):
    """Per-PlanTask typed assertion bundle (Phase 4 Task 1, VeriMAP).

    Foreman attaches per task. After execute, each `must_hold_outputs` name is
    matched against `CodeProposal.declared_outputs`; `python_assertions` are
    safe-eval'd over namespace {declared, actual_count, actual_category,
    actual_parameters, actual_level_name, actual_family_name}. Mismatch =
    VF violation → targeted replan (single task, no phase abort).
    """
    model_config = ConfigDict(frozen=True)

    description: str = Field(..., min_length=1)
    python_assertions: list[str] = Field(default_factory=list)
    must_hold_outputs: list[str] = Field(..., min_length=1)

    @field_validator("must_hold_outputs")
    @classmethod
    def _check_must_hold_outputs(cls, v: list[str]) -> list[str]:
        """Audit N9 — reject typos in field names at construction time."""
        unknown = [f for f in v if f not in _ALLOWED_MUST_HOLD_OUTPUTS]
        if unknown:
            raise ValueError(
                f"unknown must_hold_outputs field(s): {unknown}. "
                f"Allowed: {sorted(_ALLOWED_MUST_HOLD_OUTPUTS)}"
            )
        return v

    @field_validator("python_assertions")
    @classmethod
    def _check_python_assertions(cls, v: list[str]) -> list[str]:
        """Wave 5 R2 — restrict assertion strings to a safe AST subset at VF
        construction time. Removes the dynamic-code-execution attack surface
        before Phase 5 starts letting LLMs author VFs."""
        for expr in v:
            _validate_vf_assertion(expr)
        return v


class PlanTask(BaseModel):
    """One unit of a phase plan, before Resolver runs.

    Distinct from execution.ExecutionTask (raw C# for the queue) and from
    tasks.TaskBrief (resolved data for the Subagent). PlanTask is what the
    Foreman writes when it plans the phase — intent only.
    """
    model_config = ConfigDict(frozen=True)

    plan_task_id: str = Field(..., min_length=1, description="unique within the phase")
    intent: ResolverIntent
    expected_elements: ExpectedElementsSpec
    tier: Tier
    skill_path: str = Field(..., min_length=1, description="under skills/modeling/")
    is_repair: bool = False
    repair_for_plan_task_id: str | None = None
    estimated_cost_usd: float = Field(0.0, ge=0.0)
    verification_function: VerificationFunction | None = Field(
        default=None,
        description="Phase 4 Task 1 (VeriMAP). Foreman attaches per plan task; "
                    "evaluated post-execute against CodeProposal.declared_outputs.",
    )


class PhasePlan(BaseModel):
    """Ordered tasks for a single phase. Tasks execute in list order."""
    model_config = ConfigDict(frozen=True)

    phase: Phase
    tasks: list[PlanTask] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "PhasePlan":
        seen: set[str] = set()
        for t in self.tasks:
            if t.plan_task_id in seen:
                raise ValueError(f"duplicate plan_task_id: {t.plan_task_id!r}")
            seen.add(t.plan_task_id)
        return self


class PhaseRunStatus(str, Enum):
    """Rolled-up phase outcome."""
    COMPLETED = "completed"           # every task succeeded
    PARTIAL = "partial"               # some succeeded, some failed
    FAILED = "failed"                 # zero succeeded
    ABORTED = "aborted"               # halted mid-phase (user_intervention etc.)


class PhaseRunResult(BaseModel):
    """Outcome of Foreman.run_phase(plan)."""
    model_config = ConfigDict(frozen=True)

    phase: Phase
    status: PhaseRunStatus
    plan_task_ids: list[str]
    succeeded_plan_task_ids: list[str]
    failed_plan_task_ids: list[str]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_consistent(self) -> "PhaseRunResult":
        total = set(self.plan_task_ids)
        ok = set(self.succeeded_plan_task_ids)
        bad = set(self.failed_plan_task_ids)
        if ok - total or bad - total:
            raise ValueError("succeeded/failed IDs must be subset of plan_task_ids")
        if ok & bad:
            raise ValueError("a plan_task_id cannot be both succeeded and failed")
        match self.status:
            case PhaseRunStatus.COMPLETED:
                if ok != total or bad:
                    raise ValueError("COMPLETED requires every plan_task_id in succeeded and no failures")
            case PhaseRunStatus.FAILED:
                if ok:
                    raise ValueError("FAILED requires zero successes")
            case PhaseRunStatus.PARTIAL:
                if not ok or not bad:
                    raise ValueError("PARTIAL requires at least one success and one failure")
            case PhaseRunStatus.ABORTED:
                pass  # aborted may have any split (we halted)
        return self
