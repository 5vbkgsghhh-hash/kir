"""Additive STEP-0 honesty contracts for DECOMPILE results.

The legacy VERIFY scale (``exact | approximate | failed``) remains intact and
continues to describe its deliberately bounded offline geometry check.  This
module adds a stricter, orthogonal fidelity scale, build-stage evidence, and a
scoped equivalence claim.  None of these types upgrades old evidence: current
L0 1.0 ops are at most ``approximate`` until dependency fingerprints and
native-state round-trip facts exist.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Sequence, TypeAlias

from kukai.ir.decompile.l1_schema import (
    AtomReason,
    FidelityReason,
    FidelityVerdict,
)


LegacyVerifyStatus: TypeAlias = Literal[
    "exact", "approximate", "failed", "unknown"
]
FORBIDDEN_EQUIVALENCE_PROMISE = "environment_identical"


class HonestyContractError(ValueError):
    """A caller attempted to create an unscoped or unsupported claim."""


@dataclass(frozen=True, slots=True)
class SourceReason:
    """The original typed LIFT refusal attached to an atom leaf."""

    code: AtomReason
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, AtomReason):
            raise HonestyContractError("source reason code must be AtomReason")
        if not isinstance(self.detail, str) or not self.detail:
            raise HonestyContractError("source reason detail must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class FidelityAssessment:
    """Strict fidelity verdict for one preserved L1 source leaf.

    ``legacy_verify_status`` is retained explicitly so a failed legacy verdict
    can never be softened by the new five-value scale.  ``native_exact`` is
    legal only with resolved dependencies and explicit semantic round-trip
    evidence; STEP-0's current-L0 mapper never emits it.
    """

    node_id: str
    source_element_id: str
    verdict: FidelityVerdict
    reasons: tuple[FidelityReason, ...]
    detail: str
    dependency_resolved: bool
    legacy_verify_status: LegacyVerifyStatus
    source_reason: SourceReason | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("node_id", self.node_id),
            ("source_element_id", self.source_element_id),
            ("detail", self.detail),
        ):
            if not isinstance(value, str) or not value:
                raise HonestyContractError(
                    f"fidelity {field_name} must be a non-empty string")
        if not isinstance(self.verdict, FidelityVerdict):
            raise HonestyContractError("fidelity verdict must be typed")
        if (not isinstance(self.reasons, tuple) or not self.reasons
                or not all(isinstance(reason, FidelityReason)
                           for reason in self.reasons)):
            raise HonestyContractError(
                "fidelity reasons must be a non-empty typed tuple")
        if len(self.reasons) != len(set(self.reasons)):
            raise HonestyContractError("fidelity reasons must not repeat")
        if not isinstance(self.dependency_resolved, bool):
            raise HonestyContractError(
                "fidelity dependency_resolved must be boolean")
        if self.legacy_verify_status not in {
                "exact", "approximate", "failed", "unknown"}:
            raise HonestyContractError("legacy VERIFY status is invalid")
        if self.source_reason is not None and not isinstance(
                self.source_reason, SourceReason):
            raise HonestyContractError("source_reason must be typed or null")

        if self.verdict is FidelityVerdict.NATIVE_EXACT:
            if not self.dependency_resolved:
                raise HonestyContractError(
                    "native_exact requires resolved dependencies")
            if FidelityReason.NATIVE_SEMANTICS_VERIFIED not in self.reasons:
                raise HonestyContractError(
                    "native_exact requires native semantic evidence")
        if (self.verdict is FidelityVerdict.FORM_EXACT
                and FidelityReason.FORM_WITNESS_VERIFIED not in self.reasons):
            raise HonestyContractError(
                "form_exact requires a verified form witness")
        if (self.verdict is FidelityVerdict.GENERATED_ACCOUNTED
                and FidelityReason.GENERATOR_CHILD not in self.reasons):
            raise HonestyContractError(
                "generated_accounted requires generator_child provenance")

    def to_dict(self) -> dict[str, Any]:
        """Return finite JSON without weakening the legacy verdict."""

        return {
            "node_id": self.node_id,
            "source_element_id": self.source_element_id,
            "verdict": self.verdict.value,
            "reasons": [reason.value for reason in self.reasons],
            "detail": self.detail,
            "dependency_resolved": self.dependency_resolved,
            "legacy_verify_status": self.legacy_verify_status,
            "source_reason": (
                self.source_reason.to_dict() if self.source_reason else None),
        }


def _percentage(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator * 100.0


@dataclass(frozen=True, slots=True)
class FidelitySummary:
    """Flat additive metrics that sit beside legacy VERIFY metrics."""

    fidelity_total: int
    native_exact: int
    form_exact: int
    fidelity_approximate: int
    opaque: int
    generated_accounted: int
    native_exact_pct: float
    form_exact_pct: float
    fidelity_approximate_pct: float
    opaque_pct: float
    generated_accounted_pct: float
    dependency_resolved: int
    dependency_unresolved: int
    dependency_resolved_pct: float

    def __post_init__(self) -> None:
        integer_fields = (
            self.fidelity_total,
            self.native_exact,
            self.form_exact,
            self.fidelity_approximate,
            self.opaque,
            self.generated_accounted,
            self.dependency_resolved,
            self.dependency_unresolved,
        )
        if any(isinstance(value, bool) or not isinstance(value, int)
               or value < 0 for value in integer_fields):
            raise HonestyContractError(
                "fidelity summary counts must be non-negative integers")
        if sum((
            self.native_exact,
            self.form_exact,
            self.fidelity_approximate,
            self.opaque,
            self.generated_accounted,
        )) != self.fidelity_total:
            raise HonestyContractError(
                "fidelity verdict counts must sum to fidelity_total")
        if (self.dependency_resolved + self.dependency_unresolved
                != self.fidelity_total):
            raise HonestyContractError(
                "dependency counts must sum to fidelity_total")
        percentages = (
            self.native_exact_pct,
            self.form_exact_pct,
            self.fidelity_approximate_pct,
            self.opaque_pct,
            self.generated_accounted_pct,
            self.dependency_resolved_pct,
        )
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(float(value))
               or not 0.0 <= float(value) <= 100.0
               for value in percentages):
            raise HonestyContractError(
                "fidelity percentages must be finite values in 0..100")

    @classmethod
    def from_assessments(
        cls,
        assessments: Sequence[FidelityAssessment],
    ) -> "FidelitySummary":
        total = len(assessments)
        counts = {
            verdict: sum(item.verdict is verdict for item in assessments)
            for verdict in FidelityVerdict
        }
        dependency_resolved = sum(
            item.dependency_resolved for item in assessments)
        return cls(
            fidelity_total=total,
            native_exact=counts[FidelityVerdict.NATIVE_EXACT],
            form_exact=counts[FidelityVerdict.FORM_EXACT],
            fidelity_approximate=counts[FidelityVerdict.APPROXIMATE],
            opaque=counts[FidelityVerdict.OPAQUE],
            generated_accounted=counts[
                FidelityVerdict.GENERATED_ACCOUNTED],
            native_exact_pct=_percentage(
                counts[FidelityVerdict.NATIVE_EXACT], total),
            form_exact_pct=_percentage(
                counts[FidelityVerdict.FORM_EXACT], total),
            fidelity_approximate_pct=_percentage(
                counts[FidelityVerdict.APPROXIMATE], total),
            opaque_pct=_percentage(counts[FidelityVerdict.OPAQUE], total),
            generated_accounted_pct=_percentage(
                counts[FidelityVerdict.GENERATED_ACCOUNTED], total),
            dependency_resolved=dependency_resolved,
            dependency_unresolved=total - dependency_resolved,
            dependency_resolved_pct=_percentage(
                dependency_resolved, total),
        )

    def to_dict(self) -> dict[str, int | float]:
        return {
            "fidelity_total": self.fidelity_total,
            "native_exact": self.native_exact,
            "form_exact": self.form_exact,
            "fidelity_approximate": self.fidelity_approximate,
            "opaque": self.opaque,
            "generated_accounted": self.generated_accounted,
            "native_exact_pct": self.native_exact_pct,
            "form_exact_pct": self.form_exact_pct,
            "fidelity_approximate_pct": self.fidelity_approximate_pct,
            "opaque_pct": self.opaque_pct,
            "generated_accounted_pct": self.generated_accounted_pct,
            "dependency_resolved": self.dependency_resolved,
            "dependency_unresolved": self.dependency_unresolved,
            "dependency_resolved_pct": self.dependency_resolved_pct,
        }


class BuildStageState(str, Enum):
    """Evidence state for one reconstruction gate."""

    NOT_ATTEMPTED = "not_attempted"
    PASSED = "passed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BuildStageEvidence:
    state: BuildStageState
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, BuildStageState):
            raise HonestyContractError("build stage state must be typed")
        if not isinstance(self.detail, str) or not self.detail:
            raise HonestyContractError("build stage detail must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class BuildStatuses:
    """Four non-conflated reconstruction statuses from STEP-0."""

    compilable: BuildStageEvidence
    groundable: BuildStageEvidence
    executed: BuildStageEvidence
    roundtrip_verified: BuildStageEvidence

    def __post_init__(self) -> None:
        if not all(isinstance(value, BuildStageEvidence) for value in (
            self.compilable,
            self.groundable,
            self.executed,
            self.roundtrip_verified,
        )):
            raise HonestyContractError("all build statuses must be typed")
        if (self.executed.state is BuildStageState.PASSED
                and (
                    self.compilable.state is not BuildStageState.PASSED
                    or self.groundable.state is not BuildStageState.PASSED
                )):
            raise HonestyContractError(
                "executed=passed requires compilable and groundable evidence")
        if (self.roundtrip_verified.state is BuildStageState.PASSED
                and self.executed.state is not BuildStageState.PASSED):
            raise HonestyContractError(
                "roundtrip_verified=passed requires executed=passed evidence")

    @classmethod
    def initial(cls, *, unresolved_dependencies: int) -> "BuildStatuses":
        if (isinstance(unresolved_dependencies, bool)
                or not isinstance(unresolved_dependencies, int)
                or unresolved_dependencies < 0):
            raise HonestyContractError(
                "unresolved dependency count must be non-negative")
        not_compiled = BuildStageEvidence(
            BuildStageState.NOT_ATTEMPTED,
            "forward compilation has not been attempted by offline decompile",
        )
        groundable = (
            BuildStageEvidence(
                BuildStageState.BLOCKED,
                f"{unresolved_dependencies} dependency record(s) unresolved",
            )
            if unresolved_dependencies
            else BuildStageEvidence(
                BuildStageState.NOT_ATTEMPTED,
                "dependency manifest has no unresolved record, but target "
                "grounding has not been attempted",
            )
        )
        return cls(
            compilable=not_compiled,
            groundable=groundable,
            executed=BuildStageEvidence(
                BuildStageState.NOT_ATTEMPTED,
                "no live Revit execution has been attempted",
            ),
            roundtrip_verified=BuildStageEvidence(
                BuildStageState.NOT_ATTEMPTED,
                "no live rebuild and re-extract comparison has been attempted",
            ),
        )

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            "compilable": self.compilable.to_dict(),
            "groundable": self.groundable.to_dict(),
            "executed": self.executed.to_dict(),
            "roundtrip_verified": self.roundtrip_verified.to_dict(),
        }


class EquivalenceScope(str, Enum):
    """Supported, explicitly scoped equivalence claims.

    ``environment_identical`` is intentionally absent: Revit ids, history,
    worksharing ownership, and other runtime environment state cannot be
    recreated by this pipeline and must never be promised.
    """

    NATIVE_SEMANTIC = "native_semantic"
    FORM = "form"
    DOCUMENT = "document"


class EquivalenceState(str, Enum):
    NOT_VERIFIED = "not_verified"
    VERIFIED = "verified"
    FAILED = "failed"


def coerce_equivalence_scope(value: EquivalenceScope | str) -> EquivalenceScope:
    if value == FORBIDDEN_EQUIVALENCE_PROMISE:
        raise HonestyContractError(
            "environment_identical is outside the reconstructable contract")
    try:
        return value if isinstance(value, EquivalenceScope) else EquivalenceScope(value)
    except (TypeError, ValueError) as exc:
        raise HonestyContractError(f"unsupported equivalence scope: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class EquivalenceClaim:
    scope: EquivalenceScope
    state: EquivalenceState
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, EquivalenceScope):
            raise HonestyContractError("equivalence scope must be typed")
        if not isinstance(self.state, EquivalenceState):
            raise HonestyContractError("equivalence state must be typed")
        if not isinstance(self.detail, str) or not self.detail:
            raise HonestyContractError("equivalence detail must be non-empty")

    @classmethod
    def unverified(
        cls,
        scope: EquivalenceScope | str,
    ) -> "EquivalenceClaim":
        normalized = coerce_equivalence_scope(scope)
        return cls(
            scope=normalized,
            state=EquivalenceState.NOT_VERIFIED,
            detail=(
                f"{normalized.value} equivalence has not been live-roundtrip "
                "verified"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "scope": self.scope.value,
            "state": self.state.value,
            "detail": self.detail,
        }


_UNSCOPED_CLAIM = re.compile(
    r"(?:\b1\s*:\s*1\b|\bone[- ]to[- ]one\b|\b(?:full|complete)\b|"
    r"\bпол(?:ный|ная|ное|ностью)\b)",
    re.IGNORECASE,
)


def require_scope_for_equivalence_text(
    text: str,
    scope: EquivalenceScope | str | None,
) -> None:
    """Reject generated completeness wording when no scope accompanies it.

    This guard is intended for report/injection renderers, not user-authored
    project names or free text.  The forbidden environment-identity promise is
    rejected even when a nominal scope is supplied.
    """

    if not isinstance(text, str):
        raise HonestyContractError("equivalence claim text must be a string")
    if FORBIDDEN_EQUIVALENCE_PROMISE in text:
        raise HonestyContractError(
            "environment_identical must never be emitted as a promise")
    if _UNSCOPED_CLAIM.search(text) and scope is None:
        raise HonestyContractError(
            "equivalence wording requires an explicit supported scope")
    if scope is not None:
        coerce_equivalence_scope(scope)


__all__ = [
    "BuildStageEvidence",
    "BuildStageState",
    "BuildStatuses",
    "EquivalenceClaim",
    "EquivalenceScope",
    "EquivalenceState",
    "FidelityAssessment",
    "FidelitySummary",
    "FORBIDDEN_EQUIVALENCE_PROMISE",
    "HonestyContractError",
    "LegacyVerifyStatus",
    "SourceReason",
    "coerce_equivalence_scope",
    "require_scope_for_equivalence_text",
]
