"""Durable recovery primitives for the live A5 idempotence workflow.

The journal is deliberately local and append-only: every durable state change
is one fsynced JSONL record chained to the previous record by SHA-256.  A
PostgreSQL-backed lease (the store is injected) prevents two workers from
owning the same live document while that journal is replayed or advanced.

Old ``a5-run-ledger/1`` files remain inspectable.  They cannot be resumed,
because they have neither checksums nor enough transition proofs; treating
them as authoritative would turn compatibility into a safety regression.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import pathlib
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from kukai.ir.contracts import (
    CleanupReceipt,
    CommitReceipt,
    DocumentFingerprint,
    IdempotenceMetrics,
    RunId,
    SnapshotManifest,
)


class A5JournalError(RuntimeError):
    """The persisted journal is corrupt, unsupported, or ambiguous."""


class A5TransitionError(A5JournalError):
    """A caller attempted to skip or rewrite a confirmed transition."""


class A5LeaseError(RuntimeError):
    """The durable document lease is unavailable or has been lost."""


class A5Phase(str, Enum):
    PREPARED = "Prepared"
    SNAPSHOT_VERIFIED = "SnapshotVerified"
    REBUILT = "Rebuilt"
    RECONCILED = "Reconciled"
    COMPARED = "Compared"
    CLEANUP_PREVIEWED = "CleanupPreviewed"
    COMPLETED = "Completed"


PHASES: tuple[A5Phase, ...] = tuple(A5Phase)
_PHASE_INDEX = {phase: index for index, phase in enumerate(PHASES)}
_RUN_FILE_RE = re.compile(r"(?P<run_id>[0-9a-f]{16})(?:\.state)?\.jsonl\Z")


def phase_at_least(current: A5Phase, required: A5Phase) -> bool:
    return _PHASE_INDEX[current] >= _PHASE_INDEX[required]


def request_digest(value: Mapping[str, Any]) -> str:
    """Return the stable identity of one requested A5 scope."""

    raw = json.dumps(
        dict(value), ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def stamp_scope(doc_stamp: str, run_id: RunId) -> tuple[str, str]:
    """Build the compiler scope and exact Comments prefix for a run."""

    if not isinstance(doc_stamp, str) or not doc_stamp:
        raise ValueError("doc_stamp must be a non-empty string")
    doc_key = hashlib.sha256(doc_stamp.encode("utf-8")).hexdigest()[:12]
    scope = f"a5:{doc_key}:{run_id.value}"
    return scope, f"kir:{scope}:"


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _checksum(previous: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        previous.encode("ascii") + b"\0" + _canonical(body)
    ).hexdigest()


def _proof_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not all(
            isinstance(key, str) for key in value):
        raise A5JournalError(f"{name} must be an object")
    return dict(value)


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(
            value, (str, bytes, bytearray)):
        raise A5JournalError(f"{name} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise A5JournalError(f"{name} must contain non-empty strings")
        result.append(item)
    if len(set(result)) != len(result):
        raise A5JournalError(f"{name} contains duplicate ids")
    return tuple(result)


def _validate_transition_proof(
    phase: A5Phase,
    proof: Mapping[str, Any],
    *,
    run_id: RunId,
) -> None:
    """Validate the typed evidence carried by each confirmed transition."""

    if phase is A5Phase.PREPARED:
        DocumentFingerprint.from_dict(proof.get("document_fingerprint"))
        digest = proof.get("request_digest")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise A5JournalError("Prepared proof has an invalid request_digest")
        prefix = proof.get("stamp_prefix")
        if (not isinstance(prefix, str)
                or re.fullmatch(
                    rf"kir:a5:[0-9a-f]{{12}}:{run_id.value}:", prefix) is None):
            raise A5JournalError("Prepared proof is bound to another run")
        doc_hash = proof.get("doc_stamp_sha256")
        if not isinstance(doc_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", doc_hash):
            raise A5JournalError("Prepared proof has an invalid doc stamp hash")
        return
    if phase is A5Phase.SNAPSHOT_VERIFIED:
        manifest = SnapshotManifest.from_dict(proof.get("snapshot_manifest"))
        if not manifest.authoritative:
            raise A5JournalError("SnapshotVerified proof is not authoritative")
        return
    if phase is A5Phase.REBUILT:
        raw_receipts = proof.get("commit_receipts")
        if not isinstance(raw_receipts, list) or not raw_receipts:
            raise A5JournalError("Rebuilt proof requires commit receipts")
        receipts = tuple(CommitReceipt.from_dict(item) for item in raw_receipts)
        # ИЗВЕСТНЫЙ исход, а не только коммит. Отказ («Revit ответил,
        # транзакция откатена, витнесов нет») закрывает свою программу так
        # же надёжно; НЕИЗВЕСТНОСТЬ по-прежнему незаконна — её эффект не
        # финишируется вовсе и до доказательства не доходит.
        if any(receipt.run_id != run_id or receipt.operation != "rebuild"
               or not receipt.decided for receipt in receipts):
            raise A5JournalError("Rebuilt proof contains an unconfirmed receipt")
        # A fully DECIDED plan may contain only witnessed rollbacks.  That is
        # an executed 0%-coverage outcome, not an unknown effect and not a
        # successful commit.  Its unchanged document revision is carried by
        # the refusal receipts below; requiring one success here would conflate
        # execution state with acceptance state.
        created = _strings(proof.get("created_ids"), "Rebuilt.created_ids")
        flat_witnesses = [
            element_id for receipt in receipts for element_id in receipt.element_ids]
        witnessed = set(flat_witnesses)
        if len(flat_witnesses) != len(witnessed):
            raise A5JournalError("Rebuilt receipts contain duplicate element ids")
        if set(created) != witnessed:
            raise A5JournalError("Rebuilt created ids disagree with receipts")
        revision = proof.get("document_revision")
        if not isinstance(revision, str) or not revision:
            raise A5JournalError("Rebuilt proof has no document revision")
        if "program_ids" in proof:
            program_ids = _strings(
                proof.get("program_ids"), "Rebuilt.program_ids")
            receipt_program_ids = tuple(
                receipt.program_id for receipt in receipts)
            if receipt_program_ids != program_ids:
                raise A5JournalError(
                    "Rebuilt program ids disagree with receipts")
            # Отказ документ не двигает и ревизии не несёт, поэтому
            # финальную ревизию доказывает ПОСЛЕДНЯЯ КВИТАНЦИЯ, У КОТОРОЙ
            # ОНА ЕСТЬ. Требовать её от отказа значило бы требовать
            # свидетельство о записи, которой не было.
            with_revision = [
                receipt for receipt in receipts
                if receipt.document_revision is not None]
            if (not all(receipt.resumable_rebuild
                        or receipt.refused_without_commit
                        for receipt in receipts)
                    or not with_revision
                    or with_revision[-1].document_revision != revision):
                raise A5JournalError(
                    "Rebuilt resumable receipts do not prove final revision")
        return
    if phase in (A5Phase.RECONCILED, A5Phase.CLEANUP_PREVIEWED):
        prefix = proof.get("stamp_prefix")
        ids = _strings(proof.get("element_ids"), f"{phase.value}.element_ids")
        if (not isinstance(prefix, str)
                or re.fullmatch(
                    rf"kir:a5:[0-9a-f]{{12}}:{run_id.value}:", prefix) is None):
            raise A5JournalError(f"{phase.value} proof is bound to another run")
        count = proof.get("element_count")
        if isinstance(count, bool) or not isinstance(count, int) \
                or count != len(ids):
            raise A5JournalError(f"{phase.value} proof count mismatch")
        if proof.get("witnesses_complete") is not True:
            raise A5JournalError(f"{phase.value} witnesses are incomplete")
        revision = proof.get("document_revision")
        if not isinstance(revision, str) or not revision:
            raise A5JournalError(f"{phase.value} has no document revision")
        return
    if phase is A5Phase.COMPARED:
        metrics = IdempotenceMetrics.from_dict(proof.get("metrics"))
        if not metrics.comparison_performed:
            raise A5JournalError("Compared proof has no comparison")
        _proof_mapping(proof.get("report"), "Compared.report")
        revision = proof.get("document_revision")
        if not isinstance(revision, str) or not revision:
            raise A5JournalError("Compared proof has no document revision")
        return
    if phase is A5Phase.COMPLETED:
        revision = proof.get("document_revision")
        if not isinstance(revision, str) or not revision:
            raise A5JournalError("Completed proof has no document revision")
        if proof.get("retained") is True:
            _strings(proof.get("retained_ids"), "Completed.retained_ids")
            return
        receipt = CleanupReceipt.from_dict(proof.get("cleanup_receipt"))
        if receipt.run_id != run_id or not receipt.confirmed:
            raise A5JournalError("Completed cleanup receipt is unconfirmed")
        return
    raise A5JournalError(f"unsupported A5 phase {phase!r}")


@dataclass(slots=True)
class A5Replay:
    run_id: RunId
    phase: A5Phase
    proofs: dict[A5Phase, dict[str, Any]] = field(default_factory=dict)
    pending_effects: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Retain the immutable write-ahead definition after ``effect_finished``.
    # Without it a confirmed receipt cannot be rebound to the exact
    # deterministic rebuild program during process restart.
    effect_definitions: dict[str, dict[str, Any]] = field(default_factory=dict)
    effect_receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    effect_epochs: dict[str, int] = field(default_factory=dict)
    rebuild_epoch: int = 0
    abandoned: bool = False
    abandon_proof: dict[str, Any] | None = None
    sequence: int = -1
    checksum: str = ""
    legacy: bool = False

    @property
    def prepared(self) -> dict[str, Any]:
        return self.proofs[A5Phase.PREPARED]


class A5Journal:
    """A checksum-chained, fsynced A5 state journal."""

    VERSION = "a5-state-journal/1"
    LEGACY_VERSION = "a5-run-ledger/1"

    def __init__(self, path: pathlib.Path, replay: A5Replay) -> None:
        self.path = path
        self.relative_path = f"a5_runs/{path.name}"
        self.state = replay
        self._write_guard = threading.Lock()
        self._poisoned = False

    @classmethod
    def create(
        cls,
        out_dir: str | os.PathLike[str],
        *,
        run_id: RunId,
        prepared_proof: Mapping[str, Any],
    ) -> "A5Journal":
        journal_dir = pathlib.Path(out_dir) / "a5_runs"
        journal_dir.mkdir(parents=True, exist_ok=True)
        path = journal_dir / f"{run_id.value}.state.jsonl"
        if path.exists():
            raise A5JournalError(f"A5 journal already exists: {path.name}")
        replay = A5Replay(run_id=run_id, phase=A5Phase.PREPARED)
        journal = cls(path, replay)
        journal._transition_new(A5Phase.PREPARED, dict(prepared_proof))
        # fsync(file) does not by itself make a newly-created directory entry
        # durable on POSIX.  Persist the name before any Revit effect can run.
        if hasattr(os, "O_DIRECTORY"):
            try:
                directory_fd = os.open(
                    journal_dir, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError as exc:
                journal._poisoned = True
                raise A5JournalError(
                    f"cannot persist A5 journal directory: {exc}") from exc
        return journal

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "A5Journal":
        journal_path = pathlib.Path(path)
        replay = cls._replay(journal_path)
        return cls(journal_path, replay)

    @classmethod
    def find_resumable(
        cls,
        out_dir: str | os.PathLike[str],
        *,
        document_digest: str,
        request_hash: str,
    ) -> "A5Journal | None":
        journal_dir = pathlib.Path(out_dir) / "a5_runs"
        if not journal_dir.is_dir():
            return None
        matches: list[A5Journal] = []
        for path in sorted(journal_dir.glob("*.jsonl")):
            journal = cls.open(path)
            if journal.state.legacy:
                continue
            prepared = journal.state.prepared
            raw_document = prepared.get("document_fingerprint")
            fingerprint = DocumentFingerprint.from_dict(raw_document)
            if (fingerprint.digest == document_digest
                    and prepared.get("request_digest") == request_hash
                    and not journal.state.abandoned
                    and journal.state.phase is not A5Phase.COMPLETED):
                matches.append(journal)
        if len(matches) > 1:
            names = ", ".join(item.path.name for item in matches)
            raise A5JournalError(
                f"multiple resumable A5 journals for one request: {names}")
        return matches[0] if matches else None

    @classmethod
    def _replay(cls, path: pathlib.Path) -> A5Replay:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise A5JournalError(f"cannot read A5 journal {path}: {exc}") from exc
        if not raw:
            raise A5JournalError(f"empty A5 journal: {path}")
        # A process may die between write(2) and the terminating newline.  The
        # last non-terminated fragment was never a complete journal record.
        lines = raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith((b"\n", b"\r")):
            lines.pop()
        if not lines:
            raise A5JournalError(f"A5 journal has no complete records: {path}")
        rows: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise A5JournalError(
                    f"invalid A5 journal JSON at record {index}: {exc}") from exc
            rows.append(_proof_mapping(value, f"journal record {index}"))

        first_version = rows[0].get("version")
        if first_version == cls.LEGACY_VERSION:
            return cls._replay_legacy(path, rows)
        if first_version != cls.VERSION:
            raise A5JournalError(
                f"unsupported A5 journal version {first_version!r}")

        filename = _RUN_FILE_RE.fullmatch(path.name)
        if filename is None:
            raise A5JournalError(f"invalid A5 journal filename {path.name!r}")
        run_id = RunId.from_value(filename.group("run_id"))
        replay: A5Replay | None = None
        previous = ""
        for expected_seq, row in enumerate(rows):
            if row.get("version") != cls.VERSION:
                raise A5JournalError("A5 journal changes version mid-stream")
            if row.get("run_id") != run_id.value:
                raise A5JournalError("A5 journal record is bound to another run")
            if row.get("seq") != expected_seq:
                raise A5JournalError("A5 journal sequence is not contiguous")
            if row.get("prev_checksum") != previous:
                raise A5JournalError("A5 journal previous checksum mismatch")
            supplied = row.get("checksum")
            if not isinstance(supplied, str):
                raise A5JournalError("A5 journal checksum is absent")
            body = {key: value for key, value in row.items() if key != "checksum"}
            calculated = _checksum(previous, body)
            if not secrets.compare_digest(supplied, calculated):
                raise A5JournalError("A5 journal checksum mismatch")
            previous = supplied
            replay = cls._apply_record(replay, run_id, row)
            replay.sequence = expected_seq
            replay.checksum = supplied
        assert replay is not None
        return replay

    @classmethod
    def _replay_legacy(
        cls,
        path: pathlib.Path,
        rows: Sequence[Mapping[str, Any]],
    ) -> A5Replay:
        filename = _RUN_FILE_RE.fullmatch(path.name)
        raw_run = rows[0].get("run_id")
        run_id = RunId.from_value(raw_run)
        if filename is None or filename.group("run_id") != run_id.value:
            raise A5JournalError("legacy A5 ledger filename/run_id mismatch")
        if rows[0].get("event") != "run_started":
            raise A5JournalError("legacy A5 ledger does not start with run_started")
        for row in rows:
            if row.get("version") != cls.LEGACY_VERSION \
                    or row.get("run_id") != run_id.value:
                raise A5JournalError("invalid legacy A5 ledger identity")
            if row.get("event") in (
                    "rebuild_commit_receipt", "delete_commit_receipt"):
                # Compatibility means parseable, not authoritative.  PR1's
                # pessimistic defaults leave these old receipts unconfirmed.
                CommitReceipt.from_dict(row)
        prepared = {
            "legacy": True,
            "request_digest": None,
            "document_fingerprint_digest": rows[0].get(
                "document_fingerprint"),
            "stamp_prefix": rows[0].get("stamp_prefix"),
        }
        return A5Replay(
            run_id=run_id,
            phase=A5Phase.PREPARED,
            proofs={A5Phase.PREPARED: prepared},
            sequence=len(rows) - 1,
            legacy=True,
        )

    @classmethod
    def _apply_record(
        cls,
        replay: A5Replay | None,
        run_id: RunId,
        row: Mapping[str, Any],
    ) -> A5Replay:
        event = row.get("event")
        if replay is None:
            replay = A5Replay(run_id=run_id, phase=A5Phase.PREPARED)
        elif replay.abandoned:
            raise A5TransitionError("record appears after A5 journal abandonment")
        if event == "transition":
            try:
                phase = A5Phase(row.get("phase"))
            except ValueError as exc:
                raise A5JournalError("unknown A5 transition phase") from exc
            proof = _proof_mapping(row.get("proof"), f"{phase.value} proof")
            _validate_transition_proof(phase, proof, run_id=run_id)
            if replay.pending_effects:
                raise A5TransitionError(
                    "A5 phase cannot advance with pending effects")
            if not replay.proofs:
                if phase is not A5Phase.PREPARED:
                    raise A5TransitionError("first A5 phase must be Prepared")
            else:
                expected_index = _PHASE_INDEX[replay.phase] + 1
                if expected_index >= len(PHASES) or PHASES[expected_index] is not phase:
                    raise A5TransitionError(
                        f"illegal A5 transition {replay.phase.value} -> {phase.value}")
            if phase is A5Phase.SNAPSHOT_VERIFIED:
                manifest = SnapshotManifest.from_dict(
                    proof["snapshot_manifest"])
                prepared = replay.proofs[A5Phase.PREPARED]
                expected_doc_hash = hashlib.sha256(
                    manifest.doc_stamp.encode("utf-8")).hexdigest()
                _scope, expected_prefix = stamp_scope(
                    manifest.doc_stamp, run_id)
                if prepared.get("doc_stamp_sha256") != expected_doc_hash:
                    raise A5JournalError(
                        "SnapshotVerified doc_stamp disagrees with Prepared")
                if prepared.get("stamp_prefix") != expected_prefix:
                    raise A5JournalError(
                        "SnapshotVerified prefix disagrees with Prepared")
                prepared_document = DocumentFingerprint.from_dict(
                    prepared.get("document_fingerprint"))
                if prepared_document != manifest.document_fingerprint:
                    raise A5JournalError(
                        "SnapshotVerified document disagrees with Prepared")
            elif phase is A5Phase.REBUILT:
                receipts = tuple(CommitReceipt.from_dict(item) for item in (
                    proof.get("commit_receipts") or ()))
                if receipts and not any(
                        receipt.confirmed for receipt in receipts):
                    manifest = SnapshotManifest.from_dict(
                        replay.proofs[A5Phase.SNAPSHOT_VERIFIED][
                            "snapshot_manifest"])
                    if proof["document_revision"] \
                            != manifest.revision_proof.fingerprint:
                        raise A5JournalError(
                            "all-refused Rebuilt revision differs from snapshot")
            elif phase is A5Phase.RECONCILED:
                rebuilt = replay.proofs[A5Phase.REBUILT]
                rebuilt_ids = set(rebuilt["created_ids"])
                if set(proof["element_ids"]) != rebuilt_ids:
                    raise A5JournalError(
                        "Reconciled ids disagree with Rebuilt")
                if proof["document_revision"] != rebuilt["document_revision"]:
                    raise A5JournalError(
                        "Reconciled revision disagrees with Rebuilt")
            elif phase is A5Phase.COMPARED:
                metrics = IdempotenceMetrics.from_dict(proof["metrics"])
                report_metrics = IdempotenceMetrics.from_dict(proof["report"])
                if metrics != report_metrics:
                    raise A5JournalError(
                        "Compared metrics disagree with report")
                if proof["document_revision"] != replay.proofs[
                        A5Phase.REBUILT]["document_revision"]:
                    raise A5JournalError(
                        "Compared revision disagrees with Rebuilt")
            elif phase is A5Phase.CLEANUP_PREVIEWED:
                rebuilt = replay.proofs[A5Phase.REBUILT]
                rebuilt_ids = set(rebuilt["created_ids"])
                if set(proof["element_ids"]) != rebuilt_ids:
                    raise A5JournalError(
                        "CleanupPreviewed ids disagree with Rebuilt")
                if proof["document_revision"] != rebuilt["document_revision"]:
                    raise A5JournalError(
                        "CleanupPreviewed revision disagrees with Rebuilt")
            elif phase is A5Phase.COMPLETED:
                preview_ids = set(
                    replay.proofs[A5Phase.CLEANUP_PREVIEWED]["element_ids"])
                if proof.get("retained") is True:
                    completed_ids = set(proof["retained_ids"])
                else:
                    completed_ids = set(CleanupReceipt.from_dict(
                        proof["cleanup_receipt"]).found_ids)
                if completed_ids != preview_ids:
                    raise A5JournalError(
                        "Completed ids disagree with CleanupPreviewed")
                if proof.get("retained") is True:
                    expected_revision = replay.proofs[
                        A5Phase.REBUILT]["document_revision"]
                else:
                    manifest = SnapshotManifest.from_dict(
                        replay.proofs[A5Phase.SNAPSHOT_VERIFIED][
                            "snapshot_manifest"])
                    expected_revision = manifest.revision_proof.fingerprint
                if proof["document_revision"] != expected_revision:
                    raise A5JournalError(
                        "Completed revision disagrees with cleanup policy")
            replay.phase = phase
            replay.proofs[phase] = proof
        elif event == "effect_started":
            if replay.phase in (A5Phase.PREPARED, A5Phase.COMPLETED):
                raise A5TransitionError(
                    f"effects are forbidden in {replay.phase.value}")
            effect_id = row.get("effect_id")
            if not isinstance(effect_id, str) or not effect_id:
                raise A5JournalError("effect_started has no effect_id")
            if effect_id in replay.pending_effects or effect_id in replay.effect_receipts:
                raise A5JournalError(f"duplicate A5 effect id {effect_id!r}")
            effect = _proof_mapping(
                row.get("effect"), "effect_started.effect")
            replay.pending_effects[effect_id] = effect
            replay.effect_definitions[effect_id] = effect
        elif event == "effect_finished":
            effect_id = row.get("effect_id")
            if not isinstance(effect_id, str) or effect_id not in replay.pending_effects:
                raise A5JournalError("effect_finished has no matching start")
            replay.pending_effects.pop(effect_id)
            replay.effect_receipts[effect_id] = _proof_mapping(
                row.get("receipt"), "effect_finished.receipt")
            replay.effect_epochs[effect_id] = replay.rebuild_epoch
        elif event == "rebuild_epoch_started":
            epoch = row.get("epoch")
            if (isinstance(epoch, bool) or not isinstance(epoch, int)
                    or epoch != replay.rebuild_epoch + 1):
                raise A5JournalError("A5 rebuild epoch is not contiguous")
            if replay.phase is not A5Phase.SNAPSHOT_VERIFIED:
                raise A5TransitionError(
                    "a rebuild epoch can start only at SnapshotVerified")
            if replay.pending_effects:
                raise A5JournalError(
                    "a rebuild epoch cannot start with pending effects")
            receipt = CleanupReceipt.from_dict(row.get("cleanup_receipt"))
            if receipt.run_id != run_id or not receipt.confirmed:
                raise A5JournalError(
                    "rebuild epoch reset has no confirmed cleanup proof")
            replay.rebuild_epoch = epoch
        elif event == "abandoned":
            if replay.phase is A5Phase.COMPLETED or replay.abandoned:
                raise A5TransitionError("A5 journal cannot be abandoned here")
            if replay.pending_effects:
                raise A5JournalError(
                    "A5 journal cannot be abandoned with pending effects")
            proof = _proof_mapping(row.get("proof"), "abandoned.proof")
            receipt = CleanupReceipt.from_dict(proof.get("cleanup_receipt"))
            if receipt.run_id != run_id or not receipt.confirmed:
                raise A5JournalError("abandoned A5 journal lacks cleanup proof")
            replay.abandoned = True
            replay.abandon_proof = proof
        else:
            raise A5JournalError(f"unknown A5 journal event {event!r}")
        return replay

    def _append(self, event: str, **fields: Any) -> None:
        with self._write_guard:
            if self.state.legacy:
                raise A5JournalError("legacy A5 ledgers are read-only")
            if self._poisoned:
                raise A5JournalError(
                    "A5 journal had an uncertain write and is sealed")
            if not self.path.exists() and self.state.sequence == -1:
                terminated = True  # the first Prepared append creates the file
            else:
                try:
                    with self.path.open("rb") as source:
                        source.seek(-1, os.SEEK_END)
                        terminated = source.read(1) in (b"\n", b"\r")
                except (OSError, ValueError) as exc:
                    raise A5JournalError(
                        f"cannot inspect A5 journal tail: {exc}") from exc
            if not terminated:
                raise A5JournalError(
                    "A5 journal has a torn tail; repair it under the lease")
            body = {
                "version": self.VERSION,
                "seq": self.state.sequence + 1,
                "run_id": self.state.run_id.value,
                "event": event,
                "time_ns": time.time_ns(),
                "prev_checksum": self.state.checksum,
                **fields,
            }
            checksum = _checksum(self.state.checksum, body)
            row = {**body, "checksum": checksum}
            line = _canonical(row) + b"\n"
            # Validate against an isolated replay before bytes can reach disk.
            # Invalid caller evidence must not poison an otherwise valid log.
            candidate = self._apply_record(
                copy.deepcopy(self.state), self.state.run_id, row)
            candidate.sequence = int(body["seq"])
            candidate.checksum = checksum
            try:
                with self.path.open("ab") as sink:
                    sink.write(line)
                    sink.flush()
                    os.fsync(sink.fileno())
            except OSError as exc:
                self._poisoned = True
                raise A5JournalError(
                    f"cannot persist A5 journal {self.path}: {exc}") from exc
            self.state = candidate

    def repair_torn_tail(self) -> bool:
        """Drop only a non-terminated tail after durable ownership is held."""

        with self._write_guard:
            if self.state.legacy:
                return False
            try:
                raw = self.path.read_bytes()
            except OSError as exc:
                raise A5JournalError(
                    f"cannot inspect A5 journal tail: {exc}") from exc
            if raw.endswith((b"\n", b"\r")):
                return False
            durable_end = raw.rfind(b"\n") + 1
            if durable_end <= 0:
                raise A5JournalError(
                    "A5 journal has no durable record before its torn tail")
            try:
                with self.path.open("r+b") as sink:
                    sink.truncate(durable_end)
                    sink.flush()
                    os.fsync(sink.fileno())
            except OSError as exc:
                self._poisoned = True
                raise A5JournalError(
                    f"cannot repair A5 journal torn tail: {exc}") from exc
            self.state = self._replay(self.path)
            return True

    def _transition_new(self, phase: A5Phase, proof: Mapping[str, Any]) -> None:
        self._append("transition", phase=phase.value, proof=dict(proof))

    def transition(self, phase: A5Phase, proof: Mapping[str, Any]) -> None:
        """Advance exactly one phase, or idempotently confirm the same proof."""

        normalized = dict(proof)
        if phase in self.state.proofs:
            if self.state.proofs[phase] != normalized:
                raise A5TransitionError(
                    f"confirmed {phase.value} proof cannot be rewritten")
            return
        expected_index = _PHASE_INDEX[self.state.phase] + 1
        if expected_index >= len(PHASES) or PHASES[expected_index] is not phase:
            raise A5TransitionError(
                f"illegal A5 transition {self.state.phase.value} -> {phase.value}")
        self._transition_new(phase, normalized)

    def start_effect(self, effect_id: str, effect: Mapping[str, Any]) -> None:
        self._append("effect_started", effect_id=effect_id, effect=dict(effect))

    def finish_effect(self, effect_id: str, receipt: Mapping[str, Any]) -> None:
        self._append(
            "effect_finished", effect_id=effect_id, receipt=dict(receipt))

    def start_rebuild_epoch(self, cleanup_receipt: CleanupReceipt) -> None:
        """Invalidate prior rebuild receipts after unknown effects are swept."""

        if not isinstance(cleanup_receipt, CleanupReceipt) \
                or not cleanup_receipt.confirmed:
            raise A5JournalError("rebuild epoch requires confirmed cleanup")
        self._append(
            "rebuild_epoch_started",
            epoch=self.state.rebuild_epoch + 1,
            cleanup_receipt=cleanup_receipt.to_dict())

    def abandon(self, cleanup_receipt: CleanupReceipt, *, reason: str) -> None:
        """Close a failed, fully-cleaned run without forging Completed."""

        if not isinstance(reason, str) or not reason:
            raise ValueError("A5 abandon reason must be non-empty")
        self._append("abandoned", proof={
            "reason": reason,
            "cleanup_receipt": cleanup_receipt.to_dict(),
        })


class A5LeaseStore(Protocol):
    async def acquire_a5_document_lease(
        self, fingerprint_digest: str, owner_token: str, run_id: str,
        ttl_seconds: int,
    ) -> bool: ...

    async def renew_a5_document_lease(
        self, fingerprint_digest: str, owner_token: str,
        ttl_seconds: int,
    ) -> bool: ...

    async def release_a5_document_lease(
        self, fingerprint_digest: str, owner_token: str,
    ) -> bool: ...


class A5Lease:
    """Renewing ownership guard backed by the injected durable store."""

    def __init__(
        self,
        store: A5LeaseStore,
        *,
        fingerprint_digest: str,
        run_id: RunId,
        owner_token: str,
        ttl_seconds: int,
    ) -> None:
        self.store = store
        self.fingerprint_digest = fingerprint_digest
        self.run_id = run_id
        self.owner_token = owner_token
        self.ttl_seconds = ttl_seconds
        self._lost: BaseException | None = None
        self._task: asyncio.Task[None] | None = None
        self._renew_lock = asyncio.Lock()
        self._last_renewed = time.monotonic()

    @classmethod
    async def acquire(
        cls,
        store: A5LeaseStore,
        *,
        fingerprint_digest: str,
        run_id: RunId,
        ttl_seconds: int = 300,
    ) -> "A5Lease":
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) \
                or ttl_seconds < 3:
            raise ValueError("A5 lease ttl_seconds must be an integer >= 3")
        owner = secrets.token_hex(16)
        try:
            acquired = await store.acquire_a5_document_lease(
                fingerprint_digest, owner, run_id.value, ttl_seconds)
        except Exception as exc:
            raise A5LeaseError(f"durable A5 lease unavailable: {exc!r}") from exc
        if not acquired:
            raise A5LeaseError("live document already has an active A5 lease")
        lease = cls(
            store, fingerprint_digest=fingerprint_digest, run_id=run_id,
            owner_token=owner, ttl_seconds=ttl_seconds)
        lease._task = asyncio.create_task(lease._heartbeat())
        return lease

    async def _heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.ttl_seconds / 3.0)
                await self._renew(force=True)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # task records the loss; effect gates see it
            self._lost = exc

    async def _renew(self, *, force: bool) -> None:
        async with self._renew_lock:
            if self._lost is not None:
                raise A5LeaseError(
                    f"durable A5 lease lost: {self._lost!r}")
            if (not force and time.monotonic() - self._last_renewed
                    < self.ttl_seconds / 3.0):
                return
            try:
                renewed = await self.store.renew_a5_document_lease(
                    self.fingerprint_digest, self.owner_token,
                    self.ttl_seconds)
            except Exception as exc:
                self._lost = exc
                raise A5LeaseError(
                    f"durable A5 lease renewal failed: {exc!r}") from exc
            if not renewed:
                error = A5LeaseError("durable A5 lease was lost")
                self._lost = error
                raise error
            self._last_renewed = time.monotonic()

    async def ensure_held(self) -> None:
        """Prove ownership before an effect, renewing if the TTL is aging."""

        if self._lost is not None:
            raise A5LeaseError(f"durable A5 lease lost: {self._lost!r}")
        await self._renew(force=False)

    async def release(self) -> bool:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            return await self.store.release_a5_document_lease(
                self.fingerprint_digest, self.owner_token)
        except Exception as exc:
            raise A5LeaseError(f"durable A5 lease release failed: {exc!r}") from exc


__all__ = [
    "A5Journal",
    "A5JournalError",
    "A5Lease",
    "A5LeaseError",
    "A5LeaseStore",
    "A5Phase",
    "A5Replay",
    "A5TransitionError",
    "PHASES",
    "phase_at_least",
    "request_digest",
    "stamp_scope",
]
