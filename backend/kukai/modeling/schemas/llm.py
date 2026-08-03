"""LLM-output schemas: CodeProposal, FailureCategory checklist, InlineRagCitation.

Per spec Section 5.4 (Subagents) + Section 11 + Section 18.3 (role-play audit
reversals). The CodeProposal replaces v1's freeform self_concerns with a
structured FailureCategory checklist — every audit-cataloged failure mode
must be either explicitly checked OR marked not-applicable, with notes.
This is the "negative attestation" pattern: zero violations is valid, but
the categories considered must be enumerable.
"""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, model_validator

from kukai.modeling.schemas.tasks import ExpectedElementsSpec


class FailureCategory(str, Enum):
    """Known failure modes from spec Section 18.2 and 7.1 audit catalog.

    Subagent must declare per-category whether they considered it and
    whether it applies to their code. Empty/missing categories rejected.
    """
    UNIT_MISMATCH = "unit_mismatch"
    PARAMETER_NAME_DRIFT = "parameter_name_drift"
    FAMILY_NOT_ACTIVATED = "family_not_activated"
    TRANSACTION_NESTING = "transaction_nesting"
    MISSING_NULL_GUARD = "missing_null_guard"
    STALE_ELEMENT_ID = "stale_element_id"
    WRONG_NAMESPACE = "wrong_namespace"
    DUPLICATE_MARK = "duplicate_mark"
    WRONG_HOST_CATEGORY = "wrong_host_category"
    WRONG_LEVEL_BINDING = "wrong_level_binding"
    GEOMETRY_OUT_OF_RANGE = "geometry_out_of_range"
    INVALID_OVERLOAD_SELECTION = "invalid_overload_selection"
    MISSING_REGENERATE = "missing_regenerate"
    CYRILLIC_NAME_MATCH = "cyrillic_name_match"
    VERSION_API_MISMATCH = "version_api_mismatch"
    SILENT_NO_OP = "silent_no_op"
    IDEMPOTENCY_VIOLATION = "idempotency_violation"
    SCOPE_CREEP = "scope_creep"
    CROSS_DISCIPLINE_CONTAMINATION = "cross_discipline_contamination"
    VIEW_DEPENDENT_FILTER_FAILURE = "view_dependent_filter_failure"
    PARALLEL_SAFETY_VIOLATION = "parallel_safety_violation"


class FailureCheckResult(BaseModel):
    """Per-category attestation. `checked=True` is the floor; applicability
    tells us if the failure mode is even relevant to this specific task."""
    model_config = ConfigDict(frozen=True)

    checked: bool
    applicable: bool
    note: str | None = None


class InlineRagCitation(BaseModel):
    """Companion to `// RAG:#snippet_id` inline comments in csharp_code.

    The list of these in CodeProposal must include every snippet_id referenced
    inline; orchestrator validates with kukai.modeling.subagent.citations.
    """
    model_config = ConfigDict(frozen=True)

    snippet_id: str = Field(..., min_length=1)
    api_called: str = Field(..., min_length=1, description="which Revit API the citation grounded")


class DryRunSummary(BaseModel):
    """Pre-execution summary of what the code WILL do.

    Reviewer (Foreman in later plans) compares this against task brief without
    waiting for actual execution — catches "wrong family selected silently"
    class of failures.
    """
    model_config = ConfigDict(frozen=True)

    selected_symbol_id: int
    proposed_xyz_mm: tuple[float, float, float]
    params_to_set: dict[str, str] = Field(default_factory=dict)


class DeclaredOutputs(BaseModel):
    """Subagent's pre-codegen typed contract (Phase 4 Task 1, VeriMAP).

    Distinct from TaskBrief.expected_elements (the Foreman ask): this is
    what the Subagent commits to producing. Foreman compares to actuals
    after execute; mismatch triggers single-task replan.

    To express "no declaration" (skip VF), pass None for the whole field
    on CodeProposal — NOT a sentinel instance. The previous .empty() /
    .is_empty sentinel pattern conflated "not declared" with "intentional
    empty result" (Fix G).
    """
    model_config = ConfigDict(frozen=True)

    expected_element_count: int = Field(..., ge=0)
    expected_category: str = Field(..., min_length=1)
    expected_parameter_values: dict[str, str] = Field(default_factory=dict)
    expected_level_name: str | None = None
    expected_family_name: str | None = None


class LLMPromptInputs(BaseModel):
    """Bundle passed into LLMClient.generate_code_proposal().

    The actual prompt text is assembled in subagent.persona — this is the
    structured input that drives it.
    """
    model_config = ConfigDict(frozen=True)

    persona_prompt: str
    skill_content: str
    task_brief_json: str
    rag_snippets: list[tuple[str, str, str]] = Field(
        default_factory=list,
        description="list of (snippet_id, title, body)",
    )
    failure_catalog_summary: str


class CodeProposal(BaseModel):
    """Subagent output. Validated by orchestrator before execution.

    Per spec Section 11 with audit reversals R1, R3 applied:
    - No freeform self_concerns; structured failure_mode_checks required
    - rag_citations must mirror inline `// RAG:#id` markers
    - dry_run reports proposed coords/symbol/params before execution
    """
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(..., min_length=1)
    csharp_code: str = Field(..., min_length=1)
    explanation: str = Field(..., min_length=1)

    expected_elements: ExpectedElementsSpec
    requires_assemblies: list[str] = Field(..., min_length=1)
    transaction_name: str = Field(..., min_length=1)
    revit_version: str

    failure_mode_checks: dict[FailureCategory, FailureCheckResult] = Field(...)
    additional_concern: str | None = None

    rag_citations: list[InlineRagCitation] = Field(..., min_length=1)
    dry_run: DryRunSummary

    declared_outputs: "DeclaredOutputs | None" = Field(
        default=None,
        description="VeriMAP-style typed contract: what this code WILL produce. "
                    "Optional — None means 'not declared, skip VF evaluation'. "
                    "When provided, Foreman compares to actuals after execute; "
                    "mismatch triggers single-task replan."
    )

    questions_to_foreman: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coverage(self) -> "CodeProposal":
        missing = set(FailureCategory) - set(self.failure_mode_checks)
        if missing:
            raise ValueError(
                f"failure_mode_checks must cover all FailureCategory values; "
                f"missing: {sorted(c.value for c in missing)}"
            )
        return self
