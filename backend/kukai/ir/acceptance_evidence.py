"""Immutable, content-addressed evidence for independent KIR acceptance.

An acceptance verdict is useful only when it can be replayed from the exact
predicate and two independent model reads.  The frozen contracts below bind
those facts to the compiler's ``plan_digest`` and reject a caller-supplied
verdict that disagrees with the pure acceptance engine.

Persistence is intentionally a separate authority
(:mod:`kukai.ir.acceptance_journal`): this module contains values and algebra,
not clocks or filesystems.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Any

from kukai.ir import spec
from kukai.ir.acceptance import (
    Expectation,
    Verdict,
    check_acceptance,
    expectation_categories,
    expectation_digest,
)
from kukai.ir.acceptance_live import ScopeCensusObservation
from kukai.ir.acceptance_mutation import (
    MutationExpectation,
    MutationObservation,
    MutationVerdict,
    check_mutations,
)
from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.outcome import AcceptanceState


LEGACY_ACCEPTANCE_REGISTRATION_SCHEMA_VERSION = (
    "kir-acceptance-registration/1")
ACCEPTANCE_REGISTRATION_SCHEMA_VERSION = "kir-acceptance-registration/2"
LEGACY_ACCEPTANCE_EVIDENCE_SCHEMA_VERSION = "kir-acceptance-evidence/1"
ACCEPTANCE_EVIDENCE_SCHEMA_VERSION = "kir-acceptance-evidence/2"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[0-9a-f]{32}\Z")


class AcceptanceEvidenceError(ValueError):
    """Independent acceptance evidence is malformed or self-contradictory."""


class AcceptanceReason(str, Enum):
    """Closed reason vocabulary for non-opinionated evidence states."""

    MEASURED = "measured"
    VACUOUS = "vacuous"
    PARTIAL_BLIND_SCOPE = "partial_blind_scope"
    POST_READ_UNAVAILABLE = "post_read_unavailable"
    POST_READ_INVALID = "post_read_invalid"


def new_acceptance_run_id() -> str:
    """Return an unpredictable identity shared by pre- and post-read."""

    return secrets.token_hex(16)


def _digest(payload: Any) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AcceptanceEvidenceError(
            f"acceptance evidence is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise AcceptanceEvidenceError(f"{field_name} must be SHA-256")
    return value


def _run_id(value: Any) -> str:
    if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
        raise AcceptanceEvidenceError(
            "acceptance run_id must be 32 lowercase hex chars")
    return value


@dataclass(frozen=True, slots=True)
class AcceptanceRegistration:
    """All predicates and baselines fsynced before a possible write."""

    run_id: str
    plan_digest: str
    revit_version: str
    expectation: Expectation
    mutation_expectation: MutationExpectation
    document: DocumentFingerprint
    categories: tuple[str, ...]
    before: ScopeCensusObservation | None
    mutation_before: MutationObservation | None
    ground_digest: str | None = None

    def __post_init__(self) -> None:
        _run_id(self.run_id)
        _sha256(self.plan_digest, "plan_digest")
        if self.ground_digest is not None:
            _sha256(self.ground_digest, "ground_digest")
        if self.revit_version not in spec.REVIT_VERSIONS:
            raise AcceptanceEvidenceError(
                "registration Revit version is outside the shipped matrix")
        if not isinstance(self.expectation, Expectation):
            raise AcceptanceEvidenceError(
                "registration expectation must be typed")
        if not isinstance(self.mutation_expectation, MutationExpectation):
            raise AcceptanceEvidenceError(
                "registration mutation expectation must be typed")
        if not isinstance(self.document, DocumentFingerprint):
            raise AcceptanceEvidenceError(
                "registration document must be typed")
        expected_categories = expectation_categories(self.expectation)
        if self.categories != expected_categories:
            raise AcceptanceEvidenceError(
                "registration categories disagree with expectation")
        if self.expectation.checkable != (self.before is not None):
            raise AcceptanceEvidenceError(
                "scope baseline presence disagrees with its predicate")
        if self.mutation_expectation.checkable != (
                self.mutation_before is not None):
            raise AcceptanceEvidenceError(
                "mutation baseline presence disagrees with its predicate")
        if self.before is not None:
            if not isinstance(self.before, ScopeCensusObservation):
                raise AcceptanceEvidenceError(
                    "registration scope baseline must be typed")
            self._require_scope_binding(self.before, "before")
        if self.mutation_before is not None:
            if not isinstance(self.mutation_before, MutationObservation):
                raise AcceptanceEvidenceError(
                    "registration mutation baseline must be typed")
            self._require_mutation_binding(self.mutation_before, "before")

    @property
    def expectation_digest(self) -> str:
        return expectation_digest(self.expectation)

    @property
    def mutation_expectation_digest(self) -> str:
        return self.mutation_expectation.digest

    @property
    def checkable(self) -> bool:
        return (self.expectation.checkable
                or self.mutation_expectation.checkable)

    @property
    def blind(self) -> bool:
        suppressed_scope = (
            bool(self.expectation.rows)
            and not self.expectation.lower_bounds_valid
        )
        scope_blind = self.expectation.blind_ops
        if not self.expectation.checkable:
            # delete/change_type are blind to a category census but can be
            # fully measured by an exact-id mutation claim when there is no
            # simultaneous creation delta to confound.  In a mixed create +
            # delete/type program the census delta is still ambiguous, so its
            # blind marker deliberately remains.
            covered = {
                op_id
                for claim in self.mutation_expectation.claims
                for op_id in claim.op_ids
            }
            scope_blind = tuple(
                item for item in scope_blind if item.op_id not in covered)
        return bool(
            suppressed_scope
            or scope_blind
            or self.mutation_expectation.blind_ops
        )

    def _require_scope_binding(
        self,
        observation: ScopeCensusObservation,
        phase: str,
    ) -> None:
        if observation.run_id != self.run_id:
            raise AcceptanceEvidenceError(
                f"{phase} census belongs to another acceptance run")
        if observation.phase != phase:
            raise AcceptanceEvidenceError(
                f"{phase} census carries another read phase")
        if observation.expectation_digest != self.expectation_digest:
            raise AcceptanceEvidenceError(
                f"{phase} census belongs to another expectation")
        if observation.document_digest != self.document.digest:
            raise AcceptanceEvidenceError(
                f"{phase} census belongs to another document")
        if observation.categories != self.categories:
            raise AcceptanceEvidenceError(
                f"{phase} census belongs to another category scope")

    def _require_mutation_binding(
        self,
        observation: MutationObservation,
        phase: str,
    ) -> None:
        if observation.run_id != self.run_id:
            raise AcceptanceEvidenceError(
                f"{phase} mutation read belongs to another acceptance run")
        if observation.phase != phase:
            raise AcceptanceEvidenceError(
                f"{phase} mutation read carries another phase")
        if observation.expectation_digest != self.mutation_expectation_digest:
            raise AcceptanceEvidenceError(
                f"{phase} mutation read belongs to another expectation")
        if observation.document_digest != self.document.digest:
            raise AcceptanceEvidenceError(
                f"{phase} mutation read belongs to another document")

    @property
    def registration_digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def schema_version(self) -> str:
        return (
            ACCEPTANCE_REGISTRATION_SCHEMA_VERSION
            if self.ground_digest is not None
            else LEGACY_ACCEPTANCE_REGISTRATION_SCHEMA_VERSION
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "plan_digest": self.plan_digest,
            "revit_version": self.revit_version,
            "expectation_digest": self.expectation_digest,
            "expectation": self.expectation.to_dict(),
            "mutation_expectation_digest": self.mutation_expectation_digest,
            "mutation_expectation": self.mutation_expectation.to_dict(),
            "document_digest": self.document.digest,
            "document_fingerprint": self.document.to_dict(),
            "categories": list(self.categories),
            "before": self.before.to_dict() if self.before is not None else None,
            "before_digest": (
                self.before.observation_digest
                if self.before is not None else None
            ),
            "mutation_before": (
                self.mutation_before.to_dict()
                if self.mutation_before is not None else None
            ),
            "mutation_before_digest": (
                self.mutation_before.observation_digest
                if self.mutation_before is not None else None
            ),
        }
        if self.ground_digest is not None:
            payload["ground_digest"] = self.ground_digest
        return payload


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    """A replayable independent verdict or an explicit incomplete measure."""

    registration: AcceptanceRegistration
    state: AcceptanceState
    reason: AcceptanceReason
    after: ScopeCensusObservation | None = None
    verdict: Verdict | None = None
    mutation_after: MutationObservation | None = None
    mutation_verdict: MutationVerdict | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.registration, AcceptanceRegistration):
            raise AcceptanceEvidenceError(
                "evidence registration must be typed")
        if not isinstance(self.state, AcceptanceState):
            raise AcceptanceEvidenceError("evidence state must be typed")
        if self.state not in (
            AcceptanceState.ACCEPTED,
            AcceptanceState.REJECTED,
            AcceptanceState.INCONCLUSIVE,
        ):
            raise AcceptanceEvidenceError(
                "evidence state must be a completed acceptance state")
        if not isinstance(self.reason, AcceptanceReason):
            raise AcceptanceEvidenceError("evidence reason must be typed")

        has_measurement = (self.after is not None
                           or self.mutation_after is not None)
        if not has_measurement:
            if self.verdict is not None or self.mutation_verdict is not None:
                raise AcceptanceEvidenceError(
                    "evidence without post-read cannot carry a verdict")
            if self.state is not AcceptanceState.INCONCLUSIVE:
                raise AcceptanceEvidenceError(
                    "missing post-read can only be inconclusive")
            if self.reason not in (
                AcceptanceReason.VACUOUS,
                AcceptanceReason.PARTIAL_BLIND_SCOPE,
                AcceptanceReason.POST_READ_UNAVAILABLE,
                AcceptanceReason.POST_READ_INVALID,
            ):
                raise AcceptanceEvidenceError(
                    "missing post-read needs an incomplete reason")
            return

        scope_verdict = None
        if self.registration.expectation.checkable:
            if (not isinstance(self.after, ScopeCensusObservation)
                    or self.registration.before is None):
                raise AcceptanceEvidenceError(
                    "checkable scope evidence lacks a typed read pair")
            self.registration._require_scope_binding(self.after, "after")
            scope_verdict = check_acceptance(
                self.registration.expectation,
                self.registration.before.census,
                self.after.census,
            )
            if (self.verdict is None
                    or self.verdict.to_dict() != scope_verdict.to_dict()):
                raise AcceptanceEvidenceError(
                    "stored verdict disagrees with replayed census measurement")
        elif self.after is not None or self.verdict is not None:
            raise AcceptanceEvidenceError(
                "vacuous scope carried an unregistered measurement")

        mutation_verdict = None
        if self.registration.mutation_expectation.checkable:
            if (not isinstance(self.mutation_after, MutationObservation)
                    or self.registration.mutation_before is None):
                raise AcceptanceEvidenceError(
                    "checkable mutation evidence lacks a typed read pair")
            self.registration._require_mutation_binding(
                self.mutation_after, "after")
            mutation_verdict = check_mutations(
                self.registration.mutation_expectation,
                self.registration.mutation_before,
                self.mutation_after,
            )
            if (self.mutation_verdict is None
                    or self.mutation_verdict.to_dict()
                    != mutation_verdict.to_dict()):
                raise AcceptanceEvidenceError(
                    "stored mutation verdict disagrees with replayed reads")
        elif self.mutation_after is not None or self.mutation_verdict is not None:
            raise AcceptanceEvidenceError(
                "vacuous mutation scope carried an unregistered measurement")

        mismatches = bool(
            (scope_verdict is not None and scope_verdict.mismatches)
            or (mutation_verdict is not None and mutation_verdict.mismatches)
        )
        checked = (
            (scope_verdict.checked_groups if scope_verdict is not None else 0)
            + (mutation_verdict.checked_claims
               if mutation_verdict is not None else 0)
        )
        blind = (
            self.registration.blind
            or bool(mutation_verdict is not None
                    and mutation_verdict.inconclusive_claims)
        )
        if mismatches:
            expected_state = AcceptanceState.REJECTED
            expected_reason = AcceptanceReason.MEASURED
        elif checked == 0:
            expected_state = AcceptanceState.INCONCLUSIVE
            expected_reason = (
                AcceptanceReason.PARTIAL_BLIND_SCOPE
                if blind else AcceptanceReason.VACUOUS
            )
        elif blind:
            expected_state = AcceptanceState.INCONCLUSIVE
            expected_reason = AcceptanceReason.PARTIAL_BLIND_SCOPE
        else:
            expected_state = AcceptanceState.ACCEPTED
            expected_reason = AcceptanceReason.MEASURED
        if self.state is not expected_state or self.reason is not expected_reason:
            raise AcceptanceEvidenceError(
                "evidence state/reason disagrees with measured verdict")

    @property
    def evidence_digest(self) -> str:
        return _digest(self._unsigned_dict())

    @property
    def schema_version(self) -> str:
        return (
            ACCEPTANCE_EVIDENCE_SCHEMA_VERSION
            if self.registration.ground_digest is not None
            else LEGACY_ACCEPTANCE_EVIDENCE_SCHEMA_VERSION
        )

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registration": self.registration.to_dict(),
            "registration_digest": self.registration.registration_digest,
            "state": self.state.value,
            "reason": self.reason.value,
            "after": self.after.to_dict() if self.after is not None else None,
            "after_digest": (
                self.after.observation_digest
                if self.after is not None else None
            ),
            "verdict": self.verdict.to_dict() if self.verdict is not None else None,
            "mutation_after": (
                self.mutation_after.to_dict()
                if self.mutation_after is not None else None
            ),
            "mutation_after_digest": (
                self.mutation_after.observation_digest
                if self.mutation_after is not None else None
            ),
            "mutation_verdict": (
                self.mutation_verdict.to_dict()
                if self.mutation_verdict is not None else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["evidence_digest"] = self.evidence_digest
        return payload


def assess_acceptance(
    registration: AcceptanceRegistration,
    after: ScopeCensusObservation | None,
    mutation_after: MutationObservation | None,
) -> AcceptanceEvidence:
    """Compute the only legal complete evidence from registered observations."""

    if not isinstance(registration, AcceptanceRegistration):
        raise TypeError("acceptance assessment requires a registration")
    verdict = None
    if registration.expectation.checkable:
        if not isinstance(after, ScopeCensusObservation):
            raise TypeError(
                "scope predicate requires a post-read census")
        registration._require_scope_binding(after, "after")
        if registration.before is None:
            raise AcceptanceEvidenceError(
                "scope assessment has no registered baseline")
        verdict = check_acceptance(
            registration.expectation,
            registration.before.census,
            after.census,
        )
    elif after is not None:
        raise AcceptanceEvidenceError(
            "scope post-read exists without a predicate")

    mutation_verdict = None
    if registration.mutation_expectation.checkable:
        if not isinstance(mutation_after, MutationObservation):
            raise TypeError(
                "mutation predicate requires a post-read observation")
        registration._require_mutation_binding(mutation_after, "after")
        if registration.mutation_before is None:
            raise AcceptanceEvidenceError(
                "mutation assessment has no registered baseline")
        mutation_verdict = check_mutations(
            registration.mutation_expectation,
            registration.mutation_before,
            mutation_after,
        )
    elif mutation_after is not None:
        raise AcceptanceEvidenceError(
            "mutation post-read exists without a predicate")

    mismatches = bool(
        (verdict is not None and verdict.mismatches)
        or (mutation_verdict is not None and mutation_verdict.mismatches)
    )
    checked = (
        (verdict.checked_groups if verdict is not None else 0)
        + (mutation_verdict.checked_claims
           if mutation_verdict is not None else 0)
    )
    blind = (
        registration.blind
        or bool(mutation_verdict is not None
                and mutation_verdict.inconclusive_claims)
    )
    if mismatches:
        state = AcceptanceState.REJECTED
        reason = AcceptanceReason.MEASURED
    elif checked == 0:
        state = AcceptanceState.INCONCLUSIVE
        reason = (AcceptanceReason.PARTIAL_BLIND_SCOPE
                  if blind else AcceptanceReason.VACUOUS)
    elif blind:
        state = AcceptanceState.INCONCLUSIVE
        reason = AcceptanceReason.PARTIAL_BLIND_SCOPE
    else:
        state = AcceptanceState.ACCEPTED
        reason = AcceptanceReason.MEASURED
    return AcceptanceEvidence(
        registration=registration,
        state=state,
        reason=reason,
        after=after,
        verdict=verdict,
        mutation_after=mutation_after,
        mutation_verdict=mutation_verdict,
    )


def incomplete_acceptance(
    registration: AcceptanceRegistration,
    reason: AcceptanceReason,
) -> AcceptanceEvidence:
    """Name a measurement that could not produce an independent verdict."""

    if reason not in (
        AcceptanceReason.VACUOUS,
        AcceptanceReason.PARTIAL_BLIND_SCOPE,
        AcceptanceReason.POST_READ_UNAVAILABLE,
        AcceptanceReason.POST_READ_INVALID,
    ):
        raise AcceptanceEvidenceError(
            "incomplete acceptance needs a non-measurement reason")
    return AcceptanceEvidence(
        registration=registration,
        state=AcceptanceState.INCONCLUSIVE,
        reason=reason,
    )


__all__ = [
    "ACCEPTANCE_EVIDENCE_SCHEMA_VERSION",
    "ACCEPTANCE_REGISTRATION_SCHEMA_VERSION",
    "LEGACY_ACCEPTANCE_EVIDENCE_SCHEMA_VERSION",
    "LEGACY_ACCEPTANCE_REGISTRATION_SCHEMA_VERSION",
    "AcceptanceEvidence",
    "AcceptanceEvidenceError",
    "AcceptanceReason",
    "AcceptanceRegistration",
    "assess_acceptance",
    "incomplete_acceptance",
    "new_acceptance_run_id",
]
