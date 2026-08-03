"""LLM-as-Judge output schema.

Per CodeJudge (arXiv:2410.02184) — structured rubric verdict on a CodeProposal.
The judge runs OFFLINE after compile/execute gates in Phase 2; in Phase 1 it
exists as a standalone module so we can collect baseline judgments.
"""
from __future__ import annotations
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kukai.modeling.schemas.llm import FailureCategory


class JudgeSeverity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class JudgeVerdict(BaseModel):
    """Structured output from CodeJudge.

    `score`: 1-5 where 5=ship it, 1=catastrophic.
    `errors_detected`: subset of FailureCategory the judge flagged.
    `severity`: rolled-up worst-case.
    `suggestions`: concrete change suggestions (only meaningful when score<5).
    `judge_explanation`: natural-language rationale (audit trail).
    """
    model_config = ConfigDict(frozen=True)

    score: int = Field(..., ge=1, le=5)
    errors_detected: list[FailureCategory] = Field(default_factory=list)
    severity: JudgeSeverity
    suggestions: list[str] = Field(default_factory=list)
    judge_explanation: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _coherence(self) -> "JudgeVerdict":
        """Audit N13: cross-field invariants that catch nonsensical verdicts.

        - score < 4 (judge thinks code has issues) but errors_detected empty:
          self-contradiction. Judge must name at least one category.
        - score == 5 (ship-it) but severity HIGH/CRITICAL: self-contradiction.
        """
        if self.score < 4 and not self.errors_detected:
            raise ValueError(
                f"score={self.score} < 4 requires at least one errors_detected entry"
            )
        if self.score == 5 and self.severity in (JudgeSeverity.HIGH, JudgeSeverity.CRITICAL):
            raise ValueError(
                f"score=5 (ship-it) is incompatible with severity={self.severity.value!r}"
            )
        return self
