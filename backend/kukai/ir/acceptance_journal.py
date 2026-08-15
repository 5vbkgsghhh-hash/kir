"""Durable write-ahead journal for regular KIR independent acceptance.

Before a regular KIR write can reach Revit, its immutable-in-process acceptance
registration is written, flushed, fsynced, and its directory entry is fsynced.
After identity-guarded re-lowering, a second fsynced row binds the exact wrapped
C# bytes and dispatch identity.  Only then may the terminal execution outcome
and independent evidence be appended through the same checksum chain.  A crash
can therefore leave an explicit prepared or artifact-bound unfinished run,
never an effect whose executable body was not registered first.

This is correctness evidence, not best-effort telemetry.  Callers must refuse
the write when the journal is unavailable.  A5 keeps its stronger dedicated
state machine and does not use this adapter.  The file is private-mode,
append-once through this API, durable and tamper-evident; a filesystem owner
can still rewrite a whole checksum chain, so external/WORM anchoring remains a
separate deployment property rather than a fabricated cryptographic claim.

ЧИТАТЬ ЭТОТ КОРПУС ЧЕРЕЗ sudo ИЛИ СКАЗАТЬ, ЧТО НЕ СМОГ — НО НИКОГДА НЕ
СООБЩАТЬ НОЛЬ. Каталог-приёмник private-mode (0700, владелец — пользователь
службы), и это ломает приборы тише, чем ожидается: `pathlib.glob` по каталогу
без права чтения возвращает ПУСТОЙ список, а не ошибку. Сессия без прав
получает «улик нет» там, где правда — «не вижу». Отсутствующий индекс и пустой
индекс — разные факты, и здесь сама среда их склеивает. Замерено 11.08.2026 на
44 настоящих журналах: без sudo перечисление даёт 0 файлов без единой ошибки.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from kukai.ir.acceptance_evidence import (
    ACCEPTANCE_EVIDENCE_SCHEMA_VERSION,
    AcceptanceEvidence,
    AcceptanceRegistration,
    ExecutionArtifactBinding,
    ExecutionArtifactBindingError,
)
from kukai.ir.install_paths import install_data_path
from kukai.ir.outcome import ProgramOutcome


ACCEPTANCE_JOURNAL_SCHEMA_VERSION = "kir-acceptance-journal/2"
LEGACY_ACCEPTANCE_JOURNAL_SCHEMA_VERSION = "kir-acceptance-journal/1"
ACCEPTANCE_EVIDENCE_DIR_ENV = "KIR_ACCEPTANCE_EVIDENCE_DIR"
_RUN_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ZERO_CHECKSUM = "0" * 64


class AcceptanceJournalError(RuntimeError):
    """Acceptance evidence could not be durably written or verified."""


def configured_evidence_root() -> pathlib.Path | None:
    """Resolve the installation-owned evidence root, or explicit disabled.

    An explicitly empty environment value disables the sink — a deployment that
    wants every regular write to refuse must be able to say so on purpose.

    Otherwise the root belongs to the installation this module was imported
    from (``install_paths``), NOT to one absolute deployment path.  The previous
    form named ``/opt/kukai-rebuild1`` literally, so the open-source cut and any
    neutral install refused every write with ``KIR-A005`` out of the box while
    only this box worked.  Deriving it keeps the production directory byte-for-
    byte identical and makes a foreign checkout own its own evidence.

    ``None`` survives for an embedded/packaged import that owns no writable
    installation: ``prepare_acceptance`` turns that into a pre-effect refusal,
    which is the correct answer — an unmeasured write is never the fallback.
    """

    if ACCEPTANCE_EVIDENCE_DIR_ENV in os.environ:
        configured = os.environ.get(ACCEPTANCE_EVIDENCE_DIR_ENV, "").strip()
        return pathlib.Path(configured) if configured else None
    return install_data_path("evidence", "kir_acceptance")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AcceptanceJournalError(
            f"journal payload is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _checksum(previous: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        previous.encode("ascii") + b"\0" + _canonical(dict(body))
    ).hexdigest()


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not all(
            isinstance(key, str) for key in value):
        raise AcceptanceJournalError(f"{field_name} must be an object")
    return dict(value)


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise AcceptanceJournalError(f"{field_name} must be SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class AcceptanceJournalReplay:
    """Verified durable state of one acceptance run."""

    run_id: str
    registration_digest: str
    sequence: int
    checksum: str
    finalized: bool
    registration_payload: dict[str, Any]
    artifact_binding: ExecutionArtifactBinding | None = None
    final_payload: dict[str, Any] | None = None
    legacy_unbound: bool = False

    @property
    def artifact_bound(self) -> bool:
        return self.artifact_binding is not None


class AcceptanceJournal:
    """One checksum-chained, fsynced regular-write evidence file."""

    def __init__(
        self,
        path: pathlib.Path,
        state: AcceptanceJournalReplay,
    ) -> None:
        self.path = path
        self.state = state
        self._write_guard = threading.Lock()
        self._poisoned = False

    @classmethod
    def create(
        cls,
        root: str | os.PathLike[str],
        registration: AcceptanceRegistration,
    ) -> "AcceptanceJournal":
        if not isinstance(registration, AcceptanceRegistration):
            raise TypeError("acceptance journal requires a registration")
        journal_root = pathlib.Path(root)
        try:
            journal_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise AcceptanceJournalError(
                f"cannot create acceptance evidence directory: {exc}") from exc
        path = journal_root / f"{registration.run_id}.jsonl"
        if path.exists():
            raise AcceptanceJournalError(
                "acceptance run id already has a journal")
        registration_payload = registration.to_dict()
        registration_digest = registration.registration_digest
        body = {
            "schema_version": ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
            "seq": 0,
            "event": "prepared",
            "run_id": registration.run_id,
            "time_ns": time.time_ns(),
            "prev_checksum": _ZERO_CHECKSUM,
            "registration_digest": registration_digest,
            "registration": registration_payload,
        }
        checksum = _checksum(_ZERO_CHECKSUM, body)
        line = _canonical({**body, "checksum": checksum}) + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as sink:
                sink.write(line)
                sink.flush()
                os.fsync(sink.fileno())
            cls._fsync_directory(journal_root)
        except OSError as exc:
            raise AcceptanceJournalError(
                f"cannot persist acceptance registration: {exc}") from exc
        return cls(path, AcceptanceJournalReplay(
            run_id=registration.run_id,
            registration_digest=registration_digest,
            sequence=0,
            checksum=checksum,
            finalized=False,
            registration_payload=registration_payload,
        ))

    @staticmethod
    def _fsync_directory(path: pathlib.Path) -> None:
        if not hasattr(os, "O_DIRECTORY"):
            return
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _require_unchanged_registration_payload(self) -> None:
        """Reject in-memory mutation of the fsynced registration snapshot.

        ``AcceptanceJournalReplay`` is frozen, but its JSON-shaped payload is a
        nested mutable object.  Without this check a caller could alter a top
        level plan/context field after ``prepared`` and make the live instance
        accept a foreign binding.  Reopening the file would detect it later,
        which is too late once Revit has seen the write.
        """

        if _digest(self.state.registration_payload) != (
                self.state.registration_digest):
            self._poisoned = True
            raise AcceptanceJournalError(
                "in-memory acceptance registration differs from durable payload")

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
    ) -> "AcceptanceJournal":
        journal_path = pathlib.Path(path)
        try:
            raw = journal_path.read_bytes()
        except OSError as exc:
            raise AcceptanceJournalError(
                f"cannot read acceptance journal: {exc}") from exc
        if not raw or not raw.endswith((b"\n", b"\r")):
            raise AcceptanceJournalError(
                "acceptance journal is empty or has a torn tail")
        rows: list[dict[str, Any]] = []
        for index, line in enumerate(raw.splitlines()):
            try:
                decoded = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AcceptanceJournalError(
                    f"invalid journal JSON at row {index}: {exc}") from exc
            rows.append(_mapping(decoded, f"journal row {index}"))
        state = cls._replay(journal_path, rows)
        return cls(journal_path, state)

    @classmethod
    def _replay(
        cls,
        path: pathlib.Path,
        rows: list[dict[str, Any]],
    ) -> AcceptanceJournalReplay:
        if (rows and rows[0].get("schema_version")
                == LEGACY_ACCEPTANCE_JOURNAL_SCHEMA_VERSION):
            return cls._replay_legacy_v1(path, rows)
        filename = path.name
        if not filename.endswith(".jsonl"):
            raise AcceptanceJournalError("acceptance journal filename is invalid")
        run_id = filename[:-6]
        if _RUN_ID_RE.fullmatch(run_id) is None:
            raise AcceptanceJournalError("acceptance journal run id is invalid")
        previous = _ZERO_CHECKSUM
        registration_digest: str | None = None
        registration_payload: dict[str, Any] | None = None
        artifact_binding: ExecutionArtifactBinding | None = None
        finalized = False
        final_payload: dict[str, Any] | None = None
        for index, row in enumerate(rows):
            checksum = row.get("checksum")
            _sha256(checksum, f"journal row {index}.checksum")
            body = {key: value for key, value in row.items()
                    if key != "checksum"}
            if body.get("schema_version") != ACCEPTANCE_JOURNAL_SCHEMA_VERSION:
                raise AcceptanceJournalError(
                    "unsupported acceptance journal schema")
            if body.get("seq") != index:
                raise AcceptanceJournalError(
                    "acceptance journal sequence is not contiguous")
            if body.get("run_id") != run_id:
                raise AcceptanceJournalError(
                    "acceptance journal row belongs to another run")
            if body.get("prev_checksum") != previous:
                raise AcceptanceJournalError(
                    "acceptance journal checksum chain is broken")
            if _checksum(previous, body) != checksum:
                raise AcceptanceJournalError(
                    "acceptance journal row was modified")
            event = body.get("event")
            if index == 0:
                if event != "prepared":
                    raise AcceptanceJournalError(
                        "acceptance journal must begin with prepared")
                registration_payload = _mapping(
                    body.get("registration"), "prepared registration")
                registration_digest = _sha256(
                    body.get("registration_digest"),
                    "prepared registration_digest",
                )
                if _digest(registration_payload) != registration_digest:
                    raise AcceptanceJournalError(
                        "prepared registration digest disagrees with payload")
            else:
                if event == "artifact_bound":
                    if finalized:
                        raise AcceptanceJournalError(
                            "artifact binding cannot follow terminal evidence")
                    if artifact_binding is not None:
                        raise AcceptanceJournalError(
                            "acceptance journal permits one artifact binding")
                    if body.get("registration_digest") != registration_digest:
                        raise AcceptanceJournalError(
                            "artifact binding belongs to another registration")
                    binding_payload = _mapping(
                        body.get("binding"), "execution artifact binding")
                    declared_digest = _sha256(
                        body.get("binding_digest"),
                        "execution artifact binding_digest",
                    )
                    try:
                        artifact_binding = ExecutionArtifactBinding.from_dict(
                            binding_payload)
                    except ExecutionArtifactBindingError as exc:
                        raise AcceptanceJournalError(str(exc)) from exc
                    if artifact_binding.binding_digest != declared_digest:
                        raise AcceptanceJournalError(
                            "execution artifact binding digest fields disagree")
                    assert registration_payload is not None
                    cls._verify_binding_registration(
                        artifact_binding, registration_payload)
                elif event != "finalized" or finalized:
                    raise AcceptanceJournalError(
                        "acceptance journal event order is invalid")
                else:
                    if body.get("registration_digest") != registration_digest:
                        raise AcceptanceJournalError(
                            "terminal row belongs to another registration")
                    final_payload = _mapping(
                        body.get("terminal"), "terminal payload")
                    cls._verify_terminal(
                        final_payload,
                        registration_digest,
                        artifact_binding,
                    )
                    finalized = True
            previous = str(checksum)
        assert registration_digest is not None
        assert registration_payload is not None
        return AcceptanceJournalReplay(
            run_id=run_id,
            registration_digest=registration_digest,
            sequence=len(rows) - 1,
            checksum=previous,
            finalized=finalized,
            registration_payload=registration_payload,
            artifact_binding=artifact_binding,
            final_payload=final_payload,
        )

    @classmethod
    def _replay_legacy_v1(
        cls,
        path: pathlib.Path,
        rows: list[dict[str, Any]],
    ) -> AcceptanceJournalReplay:
        """Verify old evidence for archive reads, never as write authority.

        V1 had no execution-artifact row.  It remains useful as historical
        evidence, but exposing it as a V2 prepared state would silently grant
        a new ``bind`` transition to a run created under weaker rules.  The
        explicit ``legacy_unbound`` state therefore refuses every mutation of
        the journal while retaining checksum/tamper verification.
        """

        filename = path.name
        if not filename.endswith(".jsonl"):
            raise AcceptanceJournalError("acceptance journal filename is invalid")
        run_id = filename[:-6]
        if _RUN_ID_RE.fullmatch(run_id) is None:
            raise AcceptanceJournalError("acceptance journal run id is invalid")
        previous = _ZERO_CHECKSUM
        registration_digest: str | None = None
        registration_payload: dict[str, Any] | None = None
        finalized = False
        final_payload: dict[str, Any] | None = None
        for index, row in enumerate(rows):
            checksum = row.get("checksum")
            _sha256(checksum, f"legacy journal row {index}.checksum")
            body = {key: value for key, value in row.items()
                    if key != "checksum"}
            if body.get("schema_version") != (
                    LEGACY_ACCEPTANCE_JOURNAL_SCHEMA_VERSION):
                raise AcceptanceJournalError(
                    "acceptance journal schemas cannot be mixed")
            if body.get("seq") != index:
                raise AcceptanceJournalError(
                    "legacy acceptance journal sequence is not contiguous")
            if body.get("run_id") != run_id:
                raise AcceptanceJournalError(
                    "legacy acceptance journal row belongs to another run")
            if body.get("prev_checksum") != previous:
                raise AcceptanceJournalError(
                    "legacy acceptance journal checksum chain is broken")
            if _checksum(previous, body) != checksum:
                raise AcceptanceJournalError(
                    "legacy acceptance journal row was modified")
            if index == 0:
                if body.get("event") != "prepared":
                    raise AcceptanceJournalError(
                        "legacy acceptance journal must begin with prepared")
                registration_payload = _mapping(
                    body.get("registration"), "legacy prepared registration")
                registration_digest = _sha256(
                    body.get("registration_digest"),
                    "legacy prepared registration_digest",
                )
                if _digest(registration_payload) != registration_digest:
                    raise AcceptanceJournalError(
                        "legacy registration digest disagrees with payload")
            else:
                if (body.get("event") != "finalized" or finalized
                        or index != 1):
                    raise AcceptanceJournalError(
                        "legacy journal permits one terminal row")
                if body.get("registration_digest") != registration_digest:
                    raise AcceptanceJournalError(
                        "legacy terminal belongs to another registration")
                final_payload = _mapping(
                    body.get("terminal"), "legacy terminal payload")
                cls._verify_legacy_terminal(
                    final_payload, str(registration_digest))
                finalized = True
            previous = str(checksum)
        assert registration_digest is not None
        assert registration_payload is not None
        return AcceptanceJournalReplay(
            run_id=run_id,
            registration_digest=registration_digest,
            sequence=len(rows) - 1,
            checksum=previous,
            finalized=finalized,
            registration_payload=registration_payload,
            artifact_binding=None,
            final_payload=final_payload,
            legacy_unbound=True,
        )

    @staticmethod
    def _verify_legacy_terminal(
        terminal: Mapping[str, Any],
        registration_digest: str,
    ) -> None:
        outcome = _mapping(terminal.get("outcome"), "legacy terminal outcome")
        if outcome.get("schema_version") != "kir-program-outcome/1":
            raise AcceptanceJournalError(
                "legacy terminal outcome schema is unsupported")
        evidence = terminal.get("evidence")
        evidence_digest = terminal.get("evidence_digest")
        if evidence is None:
            if evidence_digest is not None:
                raise AcceptanceJournalError(
                    "legacy evidence digest exists without evidence")
            return
        evidence_row = _mapping(evidence, "legacy terminal evidence")
        if evidence_row.get("schema_version") != "kir-acceptance-evidence/1":
            raise AcceptanceJournalError(
                "legacy terminal evidence schema is unsupported")
        if evidence_row.get("registration_digest") != registration_digest:
            raise AcceptanceJournalError(
                "legacy evidence belongs to another registration")
        declared = _sha256(evidence_digest, "legacy terminal evidence_digest")
        if evidence_row.get("evidence_digest") != declared:
            raise AcceptanceJournalError(
                "legacy evidence digest fields disagree")
        unsigned = {key: value for key, value in evidence_row.items()
                    if key != "evidence_digest"}
        if _digest(unsigned) != declared:
            raise AcceptanceJournalError(
                "legacy evidence digest disagrees with payload")

    @staticmethod
    def _verify_binding_registration(
        binding: ExecutionArtifactBinding,
        registration: Mapping[str, Any],
    ) -> None:
        expected = {
            "run_id": registration.get("run_id"),
            "revit_version": registration.get("revit_version"),
            "plan_digest": registration.get("plan_digest"),
            "ground_digest": registration.get("ground_digest"),
            "ground_context_digest": registration.get(
                "ground_context_digest"),
        }
        actual = {
            "run_id": binding.run_id,
            "revit_version": binding.revit_version,
            "plan_digest": binding.plan_digest,
            "ground_digest": binding.ground_digest,
            "ground_context_digest": binding.ground_context_digest,
        }
        if actual != expected:
            raise AcceptanceJournalError(
                "execution artifact binding belongs to another registration")

    @staticmethod
    def _verify_terminal(
        terminal: Mapping[str, Any],
        registration_digest: str,
        artifact_binding: ExecutionArtifactBinding | None,
    ) -> None:
        outcome = _mapping(terminal.get("outcome"), "terminal outcome")
        if outcome.get("schema_version") != "kir-program-outcome/1":
            raise AcceptanceJournalError(
                "terminal outcome schema is unsupported")
        binding_digest = terminal.get("execution_artifact_binding_digest")
        if artifact_binding is None:
            raise AcceptanceJournalError(
                "terminal evidence is missing its artifact binding")
        if binding_digest != artifact_binding.binding_digest:
            raise AcceptanceJournalError(
                "terminal artifact binding digest disagrees with journal")
        evidence = terminal.get("evidence")
        evidence_digest = terminal.get("evidence_digest")
        if evidence is None:
            if evidence_digest is not None:
                raise AcceptanceJournalError(
                    "terminal evidence digest exists without evidence")
            if outcome.get("acceptance") != "not_run":
                raise AcceptanceJournalError(
                    "terminal acceptance verdict exists without evidence")
            return
        evidence_row = _mapping(evidence, "terminal evidence")
        if evidence_row.get("schema_version") != (
                ACCEPTANCE_EVIDENCE_SCHEMA_VERSION):
            raise AcceptanceJournalError(
                "terminal evidence schema is unsupported")
        if evidence_row.get("registration_digest") != registration_digest:
            raise AcceptanceJournalError(
                "terminal evidence belongs to another registration")
        if evidence_row.get("execution_artifact_binding_digest") != (
                artifact_binding.binding_digest):
            raise AcceptanceJournalError(
                "terminal evidence belongs to another execution artifact")
        declared = _sha256(evidence_digest, "terminal evidence_digest")
        if evidence_row.get("evidence_digest") != declared:
            raise AcceptanceJournalError(
                "terminal evidence digest fields disagree")
        unsigned = {key: value for key, value in evidence_row.items()
                    if key != "evidence_digest"}
        if _digest(unsigned) != declared:
            raise AcceptanceJournalError(
                "terminal evidence digest disagrees with payload")

        # Execution, internal witness and independent measurement are separate
        # axes, but their fold is deterministic.  Persisting contradictory
        # rows would make the same journal prove both accepted and rejected.
        if outcome.get("execution") != "committed":
            raise AcceptanceJournalError(
                "independent acceptance evidence requires a committed outcome")
        evidence_state = evidence_row.get("state")
        witness_state = outcome.get("witness")
        if evidence_state == "rejected":
            expected_acceptance = "rejected"
        elif (evidence_state == "accepted"
              and witness_state == "satisfied"):
            expected_acceptance = "accepted"
        elif evidence_state in {"accepted", "inconclusive"}:
            expected_acceptance = "inconclusive"
        else:
            raise AcceptanceJournalError(
                "terminal evidence state is unsupported")
        if outcome.get("acceptance") != expected_acceptance:
            raise AcceptanceJournalError(
                "terminal outcome contradicts independent acceptance evidence")

    def finalize(
        self,
        outcome: ProgramOutcome,
        *,
        evidence: AcceptanceEvidence | None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """Fsync the one terminal row; confirmed evidence is immutable."""

        if not isinstance(outcome, ProgramOutcome):
            raise TypeError("journal terminal outcome must be typed")
        if self.state.legacy_unbound:
            raise AcceptanceJournalError(
                "legacy unbound journal is archive-only")
        binding = self.state.artifact_binding
        if binding is None:
            raise AcceptanceJournalError(
                "terminal evidence is missing its artifact binding")
        if evidence is not None:
            if not isinstance(evidence, AcceptanceEvidence):
                raise TypeError("journal evidence must be typed")
            if (evidence.registration.registration_digest
                    != self.state.registration_digest):
                raise AcceptanceJournalError(
                    "terminal evidence belongs to another registration")
            if (evidence.execution_artifact_binding_digest
                    != binding.binding_digest):
                raise AcceptanceJournalError(
                    "terminal evidence belongs to another execution artifact")
        if detail is not None and not isinstance(detail, Mapping):
            raise TypeError("journal terminal detail must be an object")
        terminal: dict[str, Any] = {
            "outcome": outcome.to_dict(),
            "evidence": evidence.to_dict() if evidence is not None else None,
            "evidence_digest": (
                evidence.evidence_digest if evidence is not None else None),
            "execution_artifact_binding_digest": binding.binding_digest,
        }
        if detail:
            terminal["detail"] = dict(detail)
        self._verify_terminal(
            terminal,
            self.state.registration_digest,
            binding,
        )
        self._append_terminal(terminal)

    def bind_execution_artifact(
        self,
        binding: ExecutionArtifactBinding,
    ) -> None:
        """Fsync the exact dispatch artifact between prepare and execution."""

        if not isinstance(binding, ExecutionArtifactBinding):
            raise TypeError("journal artifact binding must be typed")
        if self.state.legacy_unbound:
            raise AcceptanceJournalError(
                "legacy unbound journal is archive-only")
        with self._write_guard:
            if self._poisoned:
                raise AcceptanceJournalError(
                    "acceptance journal is poisoned after a failed write")
            self._require_unchanged_registration_payload()
            self._verify_binding_registration(
                binding, self.state.registration_payload)
            if self.state.finalized:
                raise AcceptanceJournalError(
                    "artifact binding cannot follow terminal evidence")
            if self.state.artifact_binding is not None:
                raise AcceptanceJournalError(
                    "acceptance journal permits one artifact binding")
            body = {
                "schema_version": ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
                "seq": self.state.sequence + 1,
                "event": "artifact_bound",
                "run_id": self.state.run_id,
                "time_ns": time.time_ns(),
                "prev_checksum": self.state.checksum,
                "registration_digest": self.state.registration_digest,
                "binding_digest": binding.binding_digest,
                "binding": binding.to_dict(),
            }
            checksum = _checksum(self.state.checksum, body)
            line = _canonical({**body, "checksum": checksum}) + b"\n"
            flags = os.O_WRONLY | os.O_APPEND
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(self.path, flags)
                with os.fdopen(descriptor, "ab") as sink:
                    sink.write(line)
                    sink.flush()
                    os.fsync(sink.fileno())
            except OSError as exc:
                self._poisoned = True
                raise AcceptanceJournalError(
                    f"cannot persist execution artifact binding: {exc}") from exc
            self.state = AcceptanceJournalReplay(
                run_id=self.state.run_id,
                registration_digest=self.state.registration_digest,
                sequence=self.state.sequence + 1,
                checksum=checksum,
                finalized=False,
                registration_payload=self.state.registration_payload,
                artifact_binding=binding,
            )

    def _append_terminal(self, terminal: Mapping[str, Any]) -> None:
        with self._write_guard:
            if self._poisoned:
                raise AcceptanceJournalError(
                    "acceptance journal is poisoned after a failed write")
            self._require_unchanged_registration_payload()
            if self.state.finalized:
                raise AcceptanceJournalError(
                    "acceptance journal is already finalized")
            body = {
                "schema_version": ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
                "seq": self.state.sequence + 1,
                "event": "finalized",
                "run_id": self.state.run_id,
                "time_ns": time.time_ns(),
                "prev_checksum": self.state.checksum,
                "registration_digest": self.state.registration_digest,
                "terminal": dict(terminal),
            }
            checksum = _checksum(self.state.checksum, body)
            line = _canonical({**body, "checksum": checksum}) + b"\n"
            flags = os.O_WRONLY | os.O_APPEND
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(self.path, flags)
                with os.fdopen(descriptor, "ab") as sink:
                    sink.write(line)
                    sink.flush()
                    os.fsync(sink.fileno())
            except OSError as exc:
                self._poisoned = True
                raise AcceptanceJournalError(
                    f"cannot persist terminal acceptance evidence: {exc}") from exc
            self.state = AcceptanceJournalReplay(
                run_id=self.state.run_id,
                registration_digest=self.state.registration_digest,
                sequence=self.state.sequence + 1,
                checksum=checksum,
                finalized=True,
                registration_payload=self.state.registration_payload,
                artifact_binding=self.state.artifact_binding,
                final_payload=dict(terminal),
            )


__all__ = [
    "ACCEPTANCE_EVIDENCE_DIR_ENV",
    "ACCEPTANCE_JOURNAL_SCHEMA_VERSION",
    "LEGACY_ACCEPTANCE_JOURNAL_SCHEMA_VERSION",
    "AcceptanceJournal",
    "AcceptanceJournalError",
    "AcceptanceJournalReplay",
    "configured_evidence_root",
]
