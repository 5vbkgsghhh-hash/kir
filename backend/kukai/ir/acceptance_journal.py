"""Durable write-ahead journal for regular KIR independent acceptance.

Before a regular KIR write can reach Revit, its immutable-in-process acceptance
registration is written, flushed, fsynced, and its directory entry is fsynced.
The terminal execution outcome and (when available) independent evidence are
then appended through the same checksum chain.  A crash can therefore leave an
explicit prepared-but-unfinished run, never an effect with no registered
predicate.

This is correctness evidence, not best-effort telemetry.  Callers must refuse
the write when the journal is unavailable.  A5 keeps its stronger dedicated
state machine and does not use this adapter.  The file is private-mode,
append-once through this API, durable and tamper-evident; a filesystem owner
can still rewrite a whole checksum chain, so external/WORM anchoring remains a
separate deployment property rather than a fabricated cryptographic claim.
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
)
from kukai.ir.install_paths import install_data_path
from kukai.ir.outcome import ProgramOutcome


ACCEPTANCE_JOURNAL_SCHEMA_VERSION = "kir-acceptance-journal/1"
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
    final_payload: dict[str, Any] | None = None


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
        filename = path.name
        if not filename.endswith(".jsonl"):
            raise AcceptanceJournalError("acceptance journal filename is invalid")
        run_id = filename[:-6]
        if _RUN_ID_RE.fullmatch(run_id) is None:
            raise AcceptanceJournalError("acceptance journal run id is invalid")
        previous = _ZERO_CHECKSUM
        registration_digest: str | None = None
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
                registration = _mapping(
                    body.get("registration"), "prepared registration")
                registration_digest = _sha256(
                    body.get("registration_digest"),
                    "prepared registration_digest",
                )
                if _digest(registration) != registration_digest:
                    raise AcceptanceJournalError(
                        "prepared registration digest disagrees with payload")
            else:
                if event != "finalized" or finalized:
                    raise AcceptanceJournalError(
                        "acceptance journal permits exactly one terminal row")
                if body.get("registration_digest") != registration_digest:
                    raise AcceptanceJournalError(
                        "terminal row belongs to another registration")
                final_payload = _mapping(
                    body.get("terminal"), "terminal payload")
                cls._verify_terminal(final_payload, registration_digest)
                finalized = True
            previous = str(checksum)
        assert registration_digest is not None
        return AcceptanceJournalReplay(
            run_id=run_id,
            registration_digest=registration_digest,
            sequence=len(rows) - 1,
            checksum=previous,
            finalized=finalized,
            final_payload=final_payload,
        )

    @staticmethod
    def _verify_terminal(
        terminal: Mapping[str, Any],
        registration_digest: str,
    ) -> None:
        outcome = _mapping(terminal.get("outcome"), "terminal outcome")
        if outcome.get("schema_version") != "kir-program-outcome/1":
            raise AcceptanceJournalError(
                "terminal outcome schema is unsupported")
        evidence = terminal.get("evidence")
        evidence_digest = terminal.get("evidence_digest")
        if evidence is None:
            if evidence_digest is not None:
                raise AcceptanceJournalError(
                    "terminal evidence digest exists without evidence")
            return
        evidence_row = _mapping(evidence, "terminal evidence")
        if evidence_row.get("schema_version") != (
                ACCEPTANCE_EVIDENCE_SCHEMA_VERSION):
            raise AcceptanceJournalError(
                "terminal evidence schema is unsupported")
        if evidence_row.get("registration_digest") != registration_digest:
            raise AcceptanceJournalError(
                "terminal evidence belongs to another registration")
        declared = _sha256(evidence_digest, "terminal evidence_digest")
        if evidence_row.get("evidence_digest") != declared:
            raise AcceptanceJournalError(
                "terminal evidence digest fields disagree")
        unsigned = {key: value for key, value in evidence_row.items()
                    if key != "evidence_digest"}
        if _digest(unsigned) != declared:
            raise AcceptanceJournalError(
                "terminal evidence digest disagrees with payload")

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
        if evidence is not None:
            if not isinstance(evidence, AcceptanceEvidence):
                raise TypeError("journal evidence must be typed")
            if (evidence.registration.registration_digest
                    != self.state.registration_digest):
                raise AcceptanceJournalError(
                    "terminal evidence belongs to another registration")
        if detail is not None and not isinstance(detail, Mapping):
            raise TypeError("journal terminal detail must be an object")
        terminal: dict[str, Any] = {
            "outcome": outcome.to_dict(),
            "evidence": evidence.to_dict() if evidence is not None else None,
            "evidence_digest": (
                evidence.evidence_digest if evidence is not None else None),
        }
        if detail:
            terminal["detail"] = dict(detail)
        self._append_terminal(terminal)

    def _append_terminal(self, terminal: Mapping[str, Any]) -> None:
        with self._write_guard:
            if self._poisoned:
                raise AcceptanceJournalError(
                    "acceptance journal is poisoned after a failed write")
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
                final_payload=dict(terminal),
            )


__all__ = [
    "ACCEPTANCE_EVIDENCE_DIR_ENV",
    "ACCEPTANCE_JOURNAL_SCHEMA_VERSION",
    "AcceptanceJournal",
    "AcceptanceJournalError",
    "AcceptanceJournalReplay",
    "configured_evidence_root",
]
