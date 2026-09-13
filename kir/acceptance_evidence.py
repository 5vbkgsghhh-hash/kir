"""Immutable, content-addressed evidence for independent KIR acceptance.

An acceptance verdict is useful only when it can be replayed from the exact
predicate and two independent model reads.  The frozen contracts below bind
those facts to the compiler's ``plan_digest`` and reject a caller-supplied
verdict that disagrees with the pure acceptance engine.

Persistence is intentionally a separate authority
(:mod:`kir.acceptance_journal`): this module contains values and algebra,
not clocks or filesystems.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from kir import spec
from kir.acceptance import (
    Expectation,
    Verdict,
    check_acceptance,
    expectation_categories,
    expectation_digest,
)
from kir.acceptance_live import ScopeCensusObservation
from kir.acceptance_mutation import (
    MutationExpectation,
    MutationObservation,
    MutationVerdict,
    check_mutations,
)
from kir.contracts import DocumentFingerprint
from kir.outcome import AcceptanceState


ACCEPTANCE_REGISTRATION_SCHEMA_VERSION = "kir-acceptance-registration/2"
ACCEPTANCE_EVIDENCE_SCHEMA_VERSION = "kir-acceptance-evidence/2"
EXECUTION_ARTIFACT_BINDING_SCHEMA_VERSION = "kir-execution-artifact-binding/1"
REGULAR_WRITE_EXECUTION_LANE = "kir_regular_write"
# Private in-process transport capability plus its JSON-safe public address.
# The object itself must never cross the websocket; Bridge consumes it before
# constructing the client message.  Keeping the digest beside it makes the
# operation payload identity and telemetry independently address the same
# durable journal row.
EXECUTION_ARTIFACT_CAPABILITY_KEY = "_kir_execution_artifact_binding"
EXECUTION_ARTIFACT_DIGEST_KEY = "_kir_execution_artifact_binding_digest"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_EXECUTION_LABEL_RE = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")


class AcceptanceEvidenceError(ValueError):
    """Independent acceptance evidence is malformed or self-contradictory."""


class ExecutionArtifactBindingError(AcceptanceEvidenceError):
    """The executable bytes or their dispatch identity are not the bound ones."""


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


def _execution_label(value: Any, field_name: str) -> str:
    if (not isinstance(value, str)
            or _EXECUTION_LABEL_RE.fullmatch(value) is None):
        raise ExecutionArtifactBindingError(
            f"{field_name} must be a canonical execution label")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionArtifactBinding:
    """Content address of the exact wrapped C# authorized for one dispatch.

    ``source_sha256`` and ``source_byte_length`` describe the UTF-8 bytes sent
    in the Bridge ``code`` parameter, after the execution pipeline wrapper has
    been applied.  The surrounding identity prevents a valid source digest
    from being replayed for another acceptance run, Revit dialect or transport
    lane.  This is a typed value; a bare caller-supplied digest is never write
    authority.
    """

    run_id: str
    revit_version: str
    plan_digest: str
    ground_digest: str
    ground_context_digest: str
    execution_lane: str
    tool: str
    op: str
    source_sha256: str
    source_byte_length: int

    def __post_init__(self) -> None:
        _run_id(self.run_id)
        if self.revit_version not in spec.REVIT_VERSIONS:
            raise ExecutionArtifactBindingError(
                "execution artifact Revit version is outside the shipped matrix")
        _sha256(self.plan_digest, "plan_digest")
        _sha256(self.ground_digest, "ground_digest")
        _sha256(self.ground_context_digest, "ground_context_digest")
        _execution_label(self.execution_lane, "execution_lane")
        _execution_label(self.tool, "tool")
        _execution_label(self.op, "op")
        _sha256(self.source_sha256, "source_sha256")
        if (not isinstance(self.source_byte_length, int)
                or isinstance(self.source_byte_length, bool)
                or self.source_byte_length <= 0):
            raise ExecutionArtifactBindingError(
                "source_byte_length must be a positive integer")

    @classmethod
    def from_source(
        cls,
        source: str,
        *,
        run_id: str,
        revit_version: str,
        plan_digest: str,
        ground_digest: str,
        ground_context_digest: str,
        execution_lane: str,
        tool: str,
        op: str,
    ) -> "ExecutionArtifactBinding":
        if not isinstance(source, str):
            raise ExecutionArtifactBindingError(
                "execution artifact source must be text")
        try:
            source_bytes = source.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ExecutionArtifactBindingError(
                "execution artifact source is not valid UTF-8 text") from exc
        return cls(
            run_id=run_id,
            revit_version=revit_version,
            plan_digest=plan_digest,
            ground_digest=ground_digest,
            ground_context_digest=ground_context_digest,
            execution_lane=execution_lane,
            tool=tool,
            op=op,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            source_byte_length=len(source_bytes),
        )

    @classmethod
    def from_dict(cls, value: Any) -> "ExecutionArtifactBinding":
        if not isinstance(value, Mapping) or not all(
                isinstance(key, str) for key in value):
            raise ExecutionArtifactBindingError(
                "execution artifact binding must be an object")
        expected = {
            "schema_version", "run_id", "revit_version", "plan_digest",
            "ground_digest", "ground_context_digest", "execution_lane",
            "tool", "op", "source_encoding", "source_sha256",
            "source_byte_length", "binding_digest",
        }
        if set(value) != expected:
            raise ExecutionArtifactBindingError(
                "execution artifact binding has unknown or missing fields")
        if value.get("schema_version") != (
                EXECUTION_ARTIFACT_BINDING_SCHEMA_VERSION):
            raise ExecutionArtifactBindingError(
                "execution artifact binding schema is unsupported")
        if value.get("source_encoding") != "utf-8":
            raise ExecutionArtifactBindingError(
                "execution artifact source encoding is unsupported")
        binding = cls(
            run_id=value.get("run_id"),
            revit_version=value.get("revit_version"),
            plan_digest=value.get("plan_digest"),
            ground_digest=value.get("ground_digest"),
            ground_context_digest=value.get("ground_context_digest"),
            execution_lane=value.get("execution_lane"),
            tool=value.get("tool"),
            op=value.get("op"),
            source_sha256=value.get("source_sha256"),
            source_byte_length=value.get("source_byte_length"),
        )
        if value.get("binding_digest") != binding.binding_digest:
            raise ExecutionArtifactBindingError(
                "execution artifact binding digest disagrees with payload")
        return binding

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EXECUTION_ARTIFACT_BINDING_SCHEMA_VERSION,
            "run_id": self.run_id,
            "revit_version": self.revit_version,
            "plan_digest": self.plan_digest,
            "ground_digest": self.ground_digest,
            "ground_context_digest": self.ground_context_digest,
            "execution_lane": self.execution_lane,
            "tool": self.tool,
            "op": self.op,
            "source_encoding": "utf-8",
            "source_sha256": self.source_sha256,
            "source_byte_length": self.source_byte_length,
        }

    @property
    def binding_digest(self) -> str:
        return _digest(self._unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["binding_digest"] = self.binding_digest
        return payload

    def require_exact(
        self,
        source: str,
        *,
        run_id: str,
        revit_version: str,
        plan_digest: str,
        ground_digest: str,
        ground_context_digest: str,
        execution_lane: str,
        tool: str,
        op: str,
    ) -> None:
        """Reconcile the binding against an INDEPENDENT source for all its fields.

        The full form exists for the sake of `acceptance_runtime`, where an
        independent source genuinely exists: there all five values come
        from the FSYNCED registration (`self.registration.*`), not from the
        object under check, and the comparison proves that the artifact was
        not swapped after being written to the journal. Do NOT narrow this
        signature: narrowing it would remove the one reconciliation it was
        written for.

        The transport boundary has NO independent source for these fields —
        the binding is the sole carrier of them there. It is addressed by
        :meth:`require_transport_exact`, whose signature names exactly what
        that boundary can check on its own.
        """
        candidate = type(self).from_source(
            source,
            run_id=run_id,
            revit_version=revit_version,
            plan_digest=plan_digest,
            ground_digest=ground_digest,
            ground_context_digest=ground_context_digest,
            execution_lane=execution_lane,
            tool=tool,
            op=op,
        )
        if candidate != self:
            raise ExecutionArtifactBindingError(
                "execution artifact or dispatch identity differs from binding")

    def require_transport_exact(
        self,
        source: str,
        *,
        revit_version: str,
        execution_lane: str,
        tool: str,
        op: str,
    ) -> None:
        """Reconciliation at the transport boundary: only what it knows on its own.

        INTRODUCED 11.08.2026, BECAUSE THE FULL FORM COULD NOT FAIL HERE.
        `bridge_protocol` called :meth:`require_exact`, feeding `run_id`,
        `plan_digest`, `ground_digest`, and `ground_context_digest` FROM THE
        OBJECT UNDER CHECK (`raw.run_id=raw.run_id`): five of the ten
        comparisons were identical by construction, while the signature
        promised the reader an independent reconciliation of ten fields. A
        value was declared in one place and read in another — inside a
        check written against this very class.

        What the boundary knows independently, and what is solely checked
        here: the `code` bytes themselves, the Revit version from the
        session context, and the three constants of strip, instrument, and
        operation. Tampering with the bytes after acceptance is caught by
        exactly this — while tampering with metadata is caught earlier, in
        `acceptance_runtime` against the fsynced registration.

        Should the boundary gain an independent source for, say,
        `plan_digest` — add it here deliberately, rather than restoring the
        full form because it once stood here.
        """
        self.require_exact(
            source,
            run_id=self.run_id,
            revit_version=revit_version,
            plan_digest=self.plan_digest,
            ground_digest=self.ground_digest,
            ground_context_digest=self.ground_context_digest,
            execution_lane=execution_lane,
            tool=tool,
            op=op,
        )


@dataclass(frozen=True, slots=True)
class AcceptanceRegistration:
    """All predicates and baselines fsynced before a possible write."""

    run_id: str
    plan_digest: str
    ground_digest: str
    revit_version: str
    expectation: Expectation
    mutation_expectation: MutationExpectation
    document: DocumentFingerprint
    categories: tuple[str, ...]
    before: ScopeCensusObservation | None
    mutation_before: MutationObservation | None
    ground_context_digest: str | None = None
    ground_context_execution_bound: bool = False
    ground_context_authoritative: bool = False
    ground_selector_resolution_replayed: bool = False
    ground_derived_artifacts_verified: bool = False

    def __post_init__(self) -> None:
        _run_id(self.run_id)
        _sha256(self.plan_digest, "plan_digest")
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
        if self.ground_context_digest is not None:
            _sha256(self.ground_context_digest, "ground_context_digest")
        if not isinstance(self.ground_context_execution_bound, bool):
            raise AcceptanceEvidenceError(
                "ground_context_execution_bound must be bool")
        if not isinstance(self.ground_context_authoritative, bool):
            raise AcceptanceEvidenceError(
                "ground_context_authoritative must be bool")
        if not isinstance(self.ground_selector_resolution_replayed, bool):
            raise AcceptanceEvidenceError(
                "ground_selector_resolution_replayed must be bool")
        if not isinstance(self.ground_derived_artifacts_verified, bool):
            raise AcceptanceEvidenceError(
                "ground_derived_artifacts_verified must be bool")
        if ((self.ground_context_execution_bound
             or self.ground_context_authoritative)
                and self.ground_context_digest is None):
            raise AcceptanceEvidenceError(
                "ground context authority needs a bound context digest")
        if (self.ground_context_authoritative
                and not self.ground_context_execution_bound):
            raise AcceptanceEvidenceError(
                "authoritative ground context must be execution-bound")
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
    def blind_ops(self) -> tuple:
        """NAMED blind ops — ONE entry point for every reader.

        🔴 24.08: there are THREE carriers of blindness (see `blind`), while
        diagnostics read EXACTLY ONE — `expectation.blind_ops`. The live
        `create_type` returns it empty while the full
        `mutation_expectation.blind_ops` holds both the op's name and the
        human reason. The author got "check the model" instead: an address
        pointing nowhere, for a program that is ALREADY COMMITTED.

        The property does not change `blind`'s decision — it gives the
        reader the same thing under one name, so that a fourth carrier does
        not spring up silently.
        """
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
        seen: set = set()
        named: list = []
        for item in (tuple(scope_blind)
                     + tuple(self.mutation_expectation.blind_ops)):
            key = (getattr(item, "op_id", None), getattr(item, "op_name", None))
            if key in seen:
                continue
            seen.add(key)
            named.append(item)
        return tuple(named)

    @property
    def blind(self) -> bool:
        # SUPPRESSED LOWER BOUNDS are a fourth kind of blindness that has no
        # op NAME: census cells exist, but judging by them is not allowed.
        # It remains a separate member for exactly this reason, not out of
        # forgetfulness.
        suppressed_scope = (
            bool(self.expectation.rows)
            and not self.expectation.lower_bounds_valid
        )
        return bool(suppressed_scope or self.blind_ops)

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

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": ACCEPTANCE_REGISTRATION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "plan_digest": self.plan_digest,
            "ground_digest": self.ground_digest,
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
            "ground_selector_resolution_replayed": (
                self.ground_selector_resolution_replayed),
            "ground_derived_artifacts_verified": (
                self.ground_derived_artifacts_verified),
        }
        if self.ground_context_digest is not None:
            payload["ground_context_digest"] = self.ground_context_digest
            payload["ground_context_execution_bound"] = (
                self.ground_context_execution_bound)
            payload["ground_context_authoritative"] = (
                self.ground_context_authoritative)
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
    execution_artifact_binding_digest: str | None = None

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
        if self.execution_artifact_binding_digest is not None:
            _sha256(
                self.execution_artifact_binding_digest,
                "execution_artifact_binding_digest",
            )

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
    def outside_scope_delta(self) -> int | None:
        """How much the count of elements OUTSIDE scope GREW. `None` — not measured.

        🔴 THE ONLY RECORD OF AN UNREQUESTED ELEMENT (F-155). The live
        census is built over EXPECTED categories and cuts everything else
        out THREE TIMES — in the C# itself, in the Python builder, and in
        the observation contract. `Verdict.unexpected` — the instrument
        capable of NAMING the extra — could never say anything on the live
        path: it was fed an already-filtered census, and no trace remained
        even in the total, because `__kirAcceptanceTotal++` stood AFTER
        `continue`.

        `scanned_total - total` counts the document MINUS the scope; growth
        of this difference between `before` and `after` means "the model
        gained something the program did not ask for".

        🔴 THIS IS INFORMATION, NOT A REFUSAL, AND IT IS NOT A CONCESSION.
        Revit makes more derived elements than authorial ones (366,902
        `OST_SketchLines` across 31 parses — measured in the `Verdict`
        docstring), so refusing here would fail EVERY honest build. The fix
        adds VISIBILITY, not strictness: the state of the evidence does not
        move because of it in a single case, and this is verified by a
        test, not promised.
        """
        before = self.registration.before
        after = self.after
        if (before is None or after is None
                or before.outside_scope is None
                or after.outside_scope is None):
            return None
        return after.outside_scope - before.outside_scope

    @property
    def evidence_digest(self) -> str:
        return _digest(self._unsigned_dict())

    def _unsigned_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": ACCEPTANCE_EVIDENCE_SCHEMA_VERSION,
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
            "execution_artifact_binding_digest": (
                self.execution_artifact_binding_digest),
        }
        # THE KEY APPEARS ONLY WHEN THE WITNESS HAS BEEN TAKEN BY BOTH
        # PHASES. Otherwise `evidence_digest` would shift for EVERY already
        # recorded piece of evidence, and the journal would stop being
        # re-readable — a price that need not be paid: "not measured" and
        # "zero" must be distinguished (form 34).
        outside = self.outside_scope_delta
        if outside is not None:
            payload["outside_scope_delta"] = outside
        return payload

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
    "EXECUTION_ARTIFACT_CAPABILITY_KEY",
    "EXECUTION_ARTIFACT_DIGEST_KEY",
    "EXECUTION_ARTIFACT_BINDING_SCHEMA_VERSION",
    "REGULAR_WRITE_EXECUTION_LANE",
    "AcceptanceEvidence",
    "AcceptanceEvidenceError",
    "AcceptanceReason",
    "AcceptanceRegistration",
    "ExecutionArtifactBinding",
    "ExecutionArtifactBindingError",
    "assess_acceptance",
    "incomplete_acceptance",
    "new_acceptance_run_id",
]
