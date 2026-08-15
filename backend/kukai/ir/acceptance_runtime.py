"""KIR-only orchestration of pre-write registration and independent rereads.

``serving`` owns tool dispatch and execution.  This module owns the independent
acceptance session so that the handler cannot accidentally reorder the
correctness loop:

    typed plan -> pre-read -> fsynced registration -> identity-guarded lower
    -> fsynced exact wrapped artifact -> write -> post-read -> code-computed
    verdict -> fsynced terminal evidence

Every write routed through the regular serving body enters this state machine,
including its admin bulk budget door.  A5 has a separate runner and a stronger
revision-bound journal/form-acceptance protocol.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from kukai.ir.acceptance import (
    Expectation,
    derive_expectation,
    expectation_categories,
    symbol_rows_from_snapshot,
)
from kukai.ir.acceptance_evidence import (
    ACCEPTANCE_EVIDENCE_SCHEMA_VERSION,
    AcceptanceEvidence,
    AcceptanceReason,
    AcceptanceRegistration,
    ExecutionArtifactBinding,
    ExecutionArtifactBindingError,
    assess_acceptance,
    incomplete_acceptance,
    new_acceptance_run_id,
)
from kukai.ir.acceptance_mutation import (
    MutationExpectation,
    derive_mutation_expectation,
    mutation_identity_proofs,
    mutation_precondition_errors,
)
from kukai.ir.acceptance_probe import (
    AcceptanceObservation,
    AcceptanceProbeError,
    build_acceptance_probe_cs,
    parse_acceptance_observation,
)
from kukai.ir.acceptance_journal import (
    ACCEPTANCE_EVIDENCE_DIR_ENV,
    ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
    AcceptanceJournal,
    AcceptanceJournalError,
    configured_evidence_root,
)
from kukai.ir.bridge_result import extract_error
from kukai.ir.contracts import DocumentFingerprint, ElementIdentityProof
from kukai.ir.midend import GroundedProgram
from kukai.ir.outcome import AcceptanceState, ProgramOutcome, WitnessState


AcceptanceReader = Callable[[str, str, int], Awaitable[Any]]


class AcceptanceRuntimeError(RuntimeError):
    """A pre-effect acceptance prerequisite failed, so no write may start."""

    def __init__(self, code: str, message_ru: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.message_ru = message_ru
        self.detail = detail

    def diagnostic(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message_ru": self.message_ru,
            "detail": self.detail,
        }


def _level_names_by_id(snapshot: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    rows = snapshot.get("levels")
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        identifier = row.get("id")
        name = row.get("name")
        if (identifier is None or isinstance(identifier, bool)
                or not isinstance(name, str) or not name.strip()):
            continue
        result[str(identifier)] = name.strip()
    return result


async def _read_bound_observation(
    reader: AcceptanceReader,
    *,
    plan_digest: str,
    expectation: Expectation,
    mutation_expectation: MutationExpectation,
    document: DocumentFingerprint,
    run_id: str,
    revit_version: str,
    phase: str,
    timeout_ms: int,
) -> AcceptanceObservation:
    wire_phase = "before" if phase == "acceptance_before" else "after"
    try:
        code = build_acceptance_probe_cs(
            plan_digest=plan_digest,
            scope_expectation=expectation,
            mutation_expectation=mutation_expectation,
            document=document,
            run_id=run_id,
            phase=wire_phase,
            revit_version=revit_version,
        )
    except ValueError as exc:
        raise AcceptanceRuntimeError(
            "KIR-A002" if phase == "acceptance_before" else "KIR-A004",
            ("независимую проверку до записи не удалось сформировать — "
             "транзакция не запускалась" if phase == "acceptance_before" else
             "запись закоммичена, но повторную проверку не удалось сформировать"),
            f"{phase} probe build error: {exc}",
        ) from exc
    try:
        result = await reader(code, phase, timeout_ms)
    except Exception as exc:  # bridge/transport failures are evidence states
        raise AcceptanceRuntimeError(
            "KIR-A001" if phase == "acceptance_before" else "KIR-A003",
            ("независимая перепись до записи недоступна — транзакция не "
             "запускалась" if phase == "acceptance_before" else
             "запись закоммичена, но повторное чтение модели недоступно"),
            f"{phase} reader raised {exc.__class__.__name__}",
        ) from exc
    error = extract_error(result)
    if error is not None:
        raise AcceptanceRuntimeError(
            "KIR-A001" if phase == "acceptance_before" else "KIR-A003",
            ("независимая перепись до записи недоступна — транзакция не "
             "запускалась" if phase == "acceptance_before" else
             "запись закоммичена, но повторное чтение модели недоступно"),
            f"{phase} bridge error: {error.get('error')}",
        )
    payload = (
        result.get("result", result)
        if isinstance(result, Mapping) else None
    )
    try:
        return parse_acceptance_observation(
            payload,
            plan_digest=plan_digest,
            scope_expectation=expectation,
            mutation_expectation=mutation_expectation,
            document=document,
            run_id=run_id,
            phase=wire_phase,
            revit_version=revit_version,
        )
    except AcceptanceProbeError as exc:
        raise AcceptanceRuntimeError(
            "KIR-A002" if phase == "acceptance_before" else "KIR-A004",
            ("независимая перепись до записи нарушила контракт — транзакция "
             "не запускалась" if phase == "acceptance_before" else
             "запись закоммичена, но повторное чтение не прошло контракт"),
            f"{phase} protocol error: {exc}",
        ) from exc


@dataclass(slots=True)
class AcceptanceSession:
    """One prepared regular-write acceptance run."""

    registration: AcceptanceRegistration
    journal: AcceptanceJournal

    @property
    def execution_artifact_binding(self) -> ExecutionArtifactBinding | None:
        return self.journal.state.artifact_binding

    def bind_execution_artifact(
        self,
        wrapped_source: str,
        *,
        execution_lane: str,
        tool: str,
        op: str,
    ) -> ExecutionArtifactBinding:
        """Content-address and fsync the exact wrapped C# before dispatch."""

        context_digest = self.registration.ground_context_digest
        if context_digest is None:
            raise AcceptanceRuntimeError(
                "KIR-A010",
                "исполняемый артефакт не привязан к контексту — запись не запускалась",
                "execution artifact needs a ground context digest",
            )
        try:
            binding = ExecutionArtifactBinding.from_source(
                wrapped_source,
                run_id=self.registration.run_id,
                revit_version=self.registration.revit_version,
                plan_digest=self.registration.plan_digest,
                ground_digest=self.registration.ground_digest,
                ground_context_digest=context_digest,
                execution_lane=execution_lane,
                tool=tool,
                op=op,
            )
            self.journal.bind_execution_artifact(binding)
        except (ExecutionArtifactBindingError, AcceptanceJournalError) as exc:
            raise AcceptanceRuntimeError(
                "KIR-A010",
                "исполняемый артефакт не удалось надёжно связать — "
                "запись не запускалась",
                str(exc),
            ) from exc
        return binding

    def require_execution_artifact(
        self,
        wrapped_source: str,
        *,
        execution_lane: str,
        tool: str,
        op: str,
    ) -> ExecutionArtifactBinding:
        """Recompute the complete binding immediately before dispatch."""

        binding = self.execution_artifact_binding
        context_digest = self.registration.ground_context_digest
        if binding is None or context_digest is None:
            raise AcceptanceRuntimeError(
                "KIR-A010",
                "исполняемый артефакт не зарегистрирован — запись не запускалась",
                "regular write dispatch has no durable artifact binding",
            )
        try:
            binding.require_exact(
                wrapped_source,
                run_id=self.registration.run_id,
                revit_version=self.registration.revit_version,
                plan_digest=self.registration.plan_digest,
                ground_digest=self.registration.ground_digest,
                ground_context_digest=context_digest,
                execution_lane=execution_lane,
                tool=tool,
                op=op,
            )
        except ExecutionArtifactBindingError as exc:
            raise AcceptanceRuntimeError(
                "KIR-A010",
                "исполняемый артефакт изменился после регистрации — "
                "запись не запускалась",
                str(exc),
            ) from exc
        return binding

    @property
    def execution_identity_proofs(self) -> tuple[ElementIdentityProof, ...]:
        """Exact pre-read identities that the emitted write must guard."""

        before = self.registration.mutation_before
        if before is None:
            return ()
        return mutation_identity_proofs(
            self.registration.mutation_expectation, before)

    async def assess_after(
        self,
        reader: AcceptanceReader,
        *,
        timeout_ms: int,
    ) -> AcceptanceEvidence:
        binding = self.execution_artifact_binding
        if binding is None:
            raise AcceptanceRuntimeError(
                "KIR-A004",
                "запись не имеет связанного исполняемого артефакта",
                "post-read cannot assess an unbound execution artifact",
            )
        if not self.registration.checkable:
            reason = (
                AcceptanceReason.PARTIAL_BLIND_SCOPE
                if self.registration.blind
                else AcceptanceReason.VACUOUS
            )
            return replace(
                incomplete_acceptance(self.registration, reason),
                execution_artifact_binding_digest=binding.binding_digest,
            )
        try:
            observed = await _read_bound_observation(
                reader,
                plan_digest=self.registration.plan_digest,
                expectation=self.registration.expectation,
                mutation_expectation=self.registration.mutation_expectation,
                document=self.registration.document,
                run_id=self.registration.run_id,
                revit_version=self.registration.revit_version,
                phase="acceptance_after",
                timeout_ms=timeout_ms,
            )
        except AcceptanceRuntimeError as exc:
            reason = (
                AcceptanceReason.POST_READ_INVALID
                if exc.code == "KIR-A004"
                else AcceptanceReason.POST_READ_UNAVAILABLE
            )
            return replace(
                incomplete_acceptance(self.registration, reason),
                execution_artifact_binding_digest=binding.binding_digest,
            )
        return replace(
            assess_acceptance(
                self.registration,
                observed.scope_census,
                observed.mutations,
            ),
            execution_artifact_binding_digest=binding.binding_digest,
        )

    @staticmethod
    def outcome_state(
        evidence: AcceptanceEvidence,
        witness: WitnessState,
    ) -> AcceptanceState:
        """Fold measurement and internal witness without conflating them."""

        if evidence.state is AcceptanceState.REJECTED:
            return AcceptanceState.REJECTED
        if (evidence.state is AcceptanceState.ACCEPTED
                and witness is WitnessState.SATISFIED):
            return AcceptanceState.ACCEPTED
        return AcceptanceState.INCONCLUSIVE

    def finalize(
        self,
        outcome: ProgramOutcome,
        *,
        evidence: AcceptanceEvidence | None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        self.journal.finalize(outcome, evidence=evidence, detail=detail)

    def evidence_wire(self, evidence: AcceptanceEvidence) -> dict[str, Any]:
        # The private journal is the evidence authority and retains the full
        # before/after observations.  Tool responses and the telemetry index
        # need only replay handles plus mismatch summaries; returning raw
        # UniqueIds or pre-existing parameter values would widen private model
        # state into the conversation for no correctness benefit.
        payload = {
            "schema_version": ACCEPTANCE_EVIDENCE_SCHEMA_VERSION,
            "run_id": self.registration.run_id,
            "state": evidence.state.value,
            "reason": evidence.reason.value,
            "plan_digest": self.registration.plan_digest,
            "ground_digest": self.registration.ground_digest,
            "ground_selector_resolution_replayed": (
                self.registration.ground_selector_resolution_replayed),
            "ground_derived_artifacts_verified": (
                self.registration.ground_derived_artifacts_verified),
            "registration_digest": self.registration.registration_digest,
            "expectation_digest": self.registration.expectation_digest,
            "mutation_expectation_digest": (
                self.registration.mutation_expectation_digest),
            "evidence_digest": evidence.evidence_digest,
            "execution_artifact_binding_digest": (
                evidence.execution_artifact_binding_digest),
            "verdict": (
                evidence.verdict.to_dict()
                if evidence.verdict is not None else None
            ),
            "mutation_verdict": (
                evidence.mutation_verdict.to_dict()
                if evidence.mutation_verdict is not None else None
            ),
        }
        if self.registration.ground_context_digest is not None:
            payload["ground_context_digest"] = (
                self.registration.ground_context_digest)
            payload["ground_context_execution_bound"] = (
                self.registration.ground_context_execution_bound)
            payload["ground_context_authoritative"] = (
                self.registration.ground_context_authoritative)
        payload["journal"] = {
            "schema_version": ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
            "durable": self.journal.state.finalized,
            "run_id": self.journal.state.run_id,
            "sequence": self.journal.state.sequence,
            "checksum": self.journal.state.checksum,
        }
        if self.execution_artifact_binding is not None:
            payload["execution_artifact"] = (
                self.execution_artifact_binding.to_dict())
        return payload

    def registration_wire(self) -> dict[str, Any]:
        """Small proof that the predicate was durable before execution."""

        binding = self.execution_artifact_binding
        payload = {
            "schema_version": ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
            "state": (
                "finalized" if self.journal.state.finalized
                else "artifact_bound" if binding is not None
                else "prepared"),
            "run_id": self.registration.run_id,
            "registration_digest": self.registration.registration_digest,
            "expectation_digest": self.registration.expectation_digest,
            "mutation_expectation_digest": (
                self.registration.mutation_expectation_digest),
            "plan_digest": self.registration.plan_digest,
            "ground_digest": self.registration.ground_digest,
            "ground_selector_resolution_replayed": (
                self.registration.ground_selector_resolution_replayed),
            "ground_derived_artifacts_verified": (
                self.registration.ground_derived_artifacts_verified),
            "revit_version": self.registration.revit_version,
            "journal_checksum": self.journal.state.checksum,
            "durable": True,
        }
        if binding is not None:
            payload["execution_artifact_binding_digest"] = (
                binding.binding_digest)
            payload["execution_artifact"] = binding.to_dict()
        if self.registration.ground_context_digest is not None:
            payload["ground_context_digest"] = (
                self.registration.ground_context_digest)
            payload["ground_context_execution_bound"] = (
                self.registration.ground_context_execution_bound)
            payload["ground_context_authoritative"] = (
                self.registration.ground_context_authoritative)
        return payload


async def prepare_acceptance(
    grounded: GroundedProgram,
    snapshot: Mapping[str, Any],
    document: DocumentFingerprint,
    reader: AcceptanceReader,
    *,
    revit_version: str,
    timeout_ms: int,
    evidence_root: str | Path | None = None,
) -> AcceptanceSession:
    """Pre-read and fsync a predicate bound to exact grounded execution."""

    if not isinstance(grounded, GroundedProgram):
        raise TypeError("acceptance preparation requires GroundedProgram")
    planned = grounded.planned
    if planned.family.value != "write":
        raise ValueError("independent mutation acceptance requires a write plan")
    if not isinstance(snapshot, Mapping):
        raise TypeError("acceptance preparation requires the ground snapshot")
    if not isinstance(document, DocumentFingerprint):
        raise TypeError("acceptance preparation requires document identity")
    observed_context = type(grounded.context).from_snapshot(
        snapshot,
        source="acceptance_recheck",
        trusted_source=False,
    )
    if (grounded.context.snapshot_digest
            != observed_context.snapshot_digest):
        raise AcceptanceRuntimeError(
            "KIR-A002",
            "контекст заземления не совпал со снимком приёмки — "
            "транзакция не запускалась",
            "ground context snapshot digest mismatch",
        )
    if (grounded.context.document_digest is not None
            and grounded.context.document_digest != document.digest):
        raise AcceptanceRuntimeError(
            "KIR-A002",
            "контекст заземления принадлежит другому документу — "
            "транзакция не запускалась",
            "ground context document digest mismatch",
        )
    root = Path(evidence_root) if evidence_root is not None else (
        configured_evidence_root())
    if root is None:
        raise AcceptanceRuntimeError(
            "KIR-A005",
            "хранилище доказательств KIR не настроено — транзакция не запускалась",
            f"set {ACCEPTANCE_EVIDENCE_DIR_ENV} to a private writable directory",
        )
    # Оба справочника — ДАННЫЕ О МОДЕЛИ из того же снимка, который уже
    # заземлил программу, и оба читаются ДО эффекта: предикат
    # пред-регистрируется по построению, а не оправдывается после.
    expectation = derive_expectation(
        planned,
        level_names_by_id=_level_names_by_id(snapshot),
        family_symbols=symbol_rows_from_snapshot(snapshot),
    )
    mutation_expectation = derive_mutation_expectation(planned)
    run_id = new_acceptance_run_id()
    before = None
    mutation_before = None
    if expectation.checkable or mutation_expectation.checkable:
        observed = await _read_bound_observation(
            reader,
            plan_digest=planned.plan_digest,
            expectation=expectation,
            mutation_expectation=mutation_expectation,
            document=document,
            run_id=run_id,
            revit_version=revit_version,
            phase="acceptance_before",
            timeout_ms=timeout_ms,
        )
        before = observed.scope_census
        mutation_before = observed.mutations
        if mutation_before is not None:
            precondition_errors = mutation_precondition_errors(
                mutation_expectation, mutation_before)
            if precondition_errors:
                raise AcceptanceRuntimeError(
                    "KIR-A002",
                    "независимая проверка целей до записи не прошла — "
                    "транзакция не запускалась",
                    "; ".join(precondition_errors[:8]),
                )
    registration = AcceptanceRegistration(
        run_id=run_id,
        plan_digest=planned.plan_digest,
        ground_digest=grounded.ground_digest,
        revit_version=revit_version,
        expectation=expectation,
        mutation_expectation=mutation_expectation,
        document=document,
        categories=expectation_categories(expectation),
        before=before,
        mutation_before=mutation_before,
        ground_context_digest=grounded.context.context_digest,
        ground_context_execution_bound=grounded.context.execution_bound,
        ground_context_authoritative=grounded.context.authoritative,
        ground_selector_resolution_replayed=(
            grounded.selector_resolution_replayed),
        ground_derived_artifacts_verified=(
            grounded.derived_artifacts_verified),
    )
    try:
        journal = AcceptanceJournal.create(root, registration)
    except AcceptanceJournalError as exc:
        raise AcceptanceRuntimeError(
            "KIR-A005",
            "предикат приёмки не удалось надёжно сохранить — транзакция не запускалась",
            str(exc),
        ) from exc
    return AcceptanceSession(registration=registration, journal=journal)


__all__ = [
    "AcceptanceReader",
    "AcceptanceRuntimeError",
    "AcceptanceSession",
    "prepare_acceptance",
]
