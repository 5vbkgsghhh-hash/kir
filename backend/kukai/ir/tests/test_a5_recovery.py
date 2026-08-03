from __future__ import annotations

import asyncio
import json

import pytest

from kukai.ir.a5_recovery import (
    A5Journal,
    A5JournalError,
    A5Lease,
    A5LeaseError,
    A5Phase,
    A5TransitionError,
    request_digest,
    stamp_scope,
)
from kukai.ir.contracts import (
    CleanupReceipt,
    CommitReceipt,
    CoverageProof,
    DocumentFingerprint,
    IdempotenceMetrics,
    RevisionProof,
    RunId,
    SnapshotManifest,
)


RUN_ID = RunId("0123456789abcdef")
FINGERPRINT = DocumentFingerprint("Model A5 Copy", "", "uid-a5")


def _prepared() -> dict:
    _scope, prefix = stamp_scope("docA", RUN_ID)
    return {
        "doc_stamp_sha256": (
            "d1f11d6786f10c18cf161379e7c5b806ef9df64901f54afc72f89c5a68b3b36c"
        ),
        "request_digest": request_digest({"doc_stamp": "docA"}),
        "stamp_prefix": prefix,
        "document_fingerprint": FINGERPRINT.to_dict(),
    }


def _snapshot() -> dict:
    coverage = CoverageProof(
        stream_complete=True,
        required_categories=("OST_Walls",),
        complete_categories=("OST_Walls",),
        partial_categories=(),
        element_count=1,
    )
    manifest = SnapshotManifest(
        doc_stamp="docA",
        document_fingerprint=FINGERPRINT,
        revision_proof=RevisionProof("docA", "rev-1"),
        coverage=coverage,
    )
    return {"snapshot_manifest": manifest.to_dict()}


def _rebuild() -> dict:
    receipt = CommitReceipt(
        run_id=RUN_ID,
        operation="rebuild",
        element_ids=("7001",),
        bridge_error=False,
        commit_confirmed=True,
        commit_status="Committed",
    )
    return {
        "commit_receipts": [receipt.to_dict()],
        "created_ids": ["7001"],
        "document_revision": "revision-with-a5-elements",
    }


def _observed() -> dict:
    return {
        "stamp_prefix": _prepared()["stamp_prefix"],
        "element_count": 1,
        "element_ids": ["7001"],
        "witnesses_complete": True,
        "document_revision": "revision-with-a5-elements",
    }


def _compared() -> dict:
    metrics = IdempotenceMetrics(
        comparison_performed=True,
        multiset_match=True,
        total_expected=1,
        total_actual=1,
        total_matched=1,
        total_extra=0,
        raw_precision_pct=100.0,
        raw_recall_pct=100.0,
        adjusted_precision_pct=100.0,
        adjusted_recall_pct=100.0,
        atoms_excluded=0,
        non_datum_total=1,
        comparable_coverage_pct=100.0,
        canon_version="fidelity-canon/1",
    )
    return {
        "metrics": metrics.to_dict(),
        "report": metrics.to_dict(),
        "document_revision": "revision-with-a5-elements",
    }


def _completed() -> dict:
    receipt = CleanupReceipt(
        run_id=RUN_ID,
        stamp_prefix=_prepared()["stamp_prefix"],
        found_count=1,
        deleted_count=1,
        remaining_count=0,
        found_ids=("7001",),
        deleted_ids=("7001",),
        remaining_ids=(),
        commit_status="Committed",
        reconciled=True,
        witnesses_complete=True,
    )
    return {
        "retained": False,
        "cleanup_receipt": receipt.to_dict(),
        "document_revision": "rev-1",
    }


def _cleanup_receipt() -> CleanupReceipt:
    return CleanupReceipt.from_dict(_completed()["cleanup_receipt"])


def _journal(tmp_path) -> A5Journal:
    return A5Journal.create(
        tmp_path, run_id=RUN_ID, prepared_proof=_prepared())


def test_full_state_machine_replays_checksum_chain(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    journal.start_effect("rebuild:0", {"kind": "rebuild", "chunk": 0})
    journal.finish_effect("rebuild:0", _rebuild()["commit_receipts"][0])
    journal.transition(A5Phase.REBUILT, _rebuild())
    journal.transition(A5Phase.RECONCILED, _observed())
    journal.transition(A5Phase.COMPARED, _compared())
    journal.transition(A5Phase.CLEANUP_PREVIEWED, _observed())
    journal.transition(A5Phase.COMPLETED, _completed())

    replayed = A5Journal.open(journal.path)
    assert replayed.state.phase is A5Phase.COMPLETED
    assert not replayed.state.pending_effects
    assert replayed.state.effect_receipts["rebuild:0"]["operation"] == "rebuild"
    assert [json.loads(line)["seq"] for line in journal.path.read_text(
        encoding="utf-8").splitlines()] == list(range(9))


def test_transition_is_idempotent_but_confirmed_proof_is_immutable(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    before = journal.path.stat().st_size
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    assert journal.path.stat().st_size == before
    changed = _snapshot()
    changed["snapshot_manifest"]["l0_path"] = "other.jsonl"
    with pytest.raises(A5TransitionError, match="cannot be rewritten"):
        journal.transition(A5Phase.SNAPSHOT_VERIFIED, changed)


def test_phase_skip_is_refused(tmp_path):
    journal = _journal(tmp_path)
    with pytest.raises(A5TransitionError, match="Prepared -> Rebuilt"):
        journal.transition(A5Phase.REBUILT, _rebuild())


def test_invalid_proof_is_rejected_before_it_reaches_disk(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    before = journal.path.stat().st_size
    invalid = _rebuild()
    invalid["created_ids"] = ["other"]
    with pytest.raises(A5JournalError, match="disagree"):
        journal.transition(A5Phase.REBUILT, invalid)
    assert journal.path.stat().st_size == before
    assert A5Journal.open(journal.path).state.phase is A5Phase.SNAPSHOT_VERIFIED


def test_all_refused_rebuilt_must_keep_the_snapshot_revision(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    receipt = CommitReceipt(
        run_id=RUN_ID,
        operation="rebuild",
        element_ids=(),
        bridge_error=True,
        commit_confirmed=False,
        commit_status="RolledBack",
        program_id="a" * 64,
        document_revision="rev-foreign",
    )
    journal.start_effect("rebuild:0", {
        "kind": "rebuild", "program_id": "a" * 64})
    journal.finish_effect("rebuild:0", receipt.to_dict())

    with pytest.raises(A5JournalError, match="differs from snapshot"):
        journal.transition(A5Phase.REBUILT, {
            "commit_receipts": [receipt.to_dict()],
            "program_ids": ["a" * 64],
            "created_ids": [],
            "document_revision": "rev-foreign",
        })

    assert journal.state.phase is A5Phase.SNAPSHOT_VERIFIED


def test_checksum_tampering_is_fail_closed(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    rows = journal.path.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[1])
    row["proof"]["snapshot_manifest"]["doc_stamp"] = "forged"
    rows[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    journal.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(A5JournalError, match="checksum mismatch"):
        A5Journal.open(journal.path)


def test_torn_final_record_is_ignored(tmp_path):
    journal = _journal(tmp_path)
    with journal.path.open("ab") as sink:
        sink.write(b'{"version":"a5-state-journal/1","seq":1')
    replayed = A5Journal.open(journal.path)
    assert replayed.state.phase is A5Phase.PREPARED
    assert replayed.state.sequence == 0
    with pytest.raises(A5JournalError, match="torn tail"):
        replayed.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    assert replayed.repair_torn_tail()
    replayed.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    assert A5Journal.open(journal.path).state.phase is A5Phase.SNAPSHOT_VERIFIED


def test_pending_effect_survives_restart(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    journal.start_effect("rebuild:0", {"kind": "rebuild", "chunk": 0})
    replayed = A5Journal.open(journal.path)
    assert replayed.state.phase is A5Phase.SNAPSHOT_VERIFIED
    assert replayed.state.pending_effects == {
        "rebuild:0": {"kind": "rebuild", "chunk": 0}}
    assert replayed.state.effect_definitions == {
        "rebuild:0": {"kind": "rebuild", "chunk": 0}}


def test_finished_effect_keeps_its_write_ahead_definition(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    effect = {"kind": "rebuild", "program_id": "a" * 64}
    receipt = CommitReceipt(
        run_id=RUN_ID,
        operation="rebuild",
        element_ids=("7001",),
        bridge_error=False,
        commit_confirmed=True,
        commit_status="Committed",
        program_id="a" * 64,
        document_revision="revision-after-chunk",
    )
    journal.start_effect("rebuild:0", effect)
    journal.finish_effect("rebuild:0", receipt.to_dict())

    replayed = A5Journal.open(journal.path)
    assert not replayed.state.pending_effects
    assert replayed.state.effect_definitions["rebuild:0"] == effect
    assert replayed.state.effect_receipts["rebuild:0"] == receipt.to_dict()


def test_rebuild_epoch_is_durable_after_unknown_effect_cleanup(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    journal.start_rebuild_epoch(_cleanup_receipt())
    assert journal.state.rebuild_epoch == 1
    assert A5Journal.open(journal.path).state.rebuild_epoch == 1


def test_cleaned_failed_run_is_abandoned_not_forged_completed(tmp_path):
    journal = _journal(tmp_path)
    journal.transition(A5Phase.SNAPSHOT_VERIFIED, _snapshot())
    journal.abandon(_cleanup_receipt(), reason="comparison failed")
    replayed = A5Journal.open(journal.path)
    assert replayed.state.abandoned
    assert replayed.state.phase is A5Phase.SNAPSHOT_VERIFIED
    assert A5Journal.find_resumable(
        tmp_path,
        document_digest=FINGERPRINT.digest,
        request_hash=_prepared()["request_digest"],
    ) is None


def test_find_resumable_matches_document_and_request(tmp_path):
    journal = _journal(tmp_path)
    found = A5Journal.find_resumable(
        tmp_path,
        document_digest=FINGERPRINT.digest,
        request_hash=_prepared()["request_digest"],
    )
    assert found is not None
    assert found.path == journal.path
    assert A5Journal.find_resumable(
        tmp_path,
        document_digest=DocumentFingerprint("other", "", "uid").digest,
        request_hash=_prepared()["request_digest"],
    ) is None


def test_legacy_ledger_is_readable_but_never_resumable(tmp_path):
    run_dir = tmp_path / "a5_runs"
    run_dir.mkdir()
    path = run_dir / f"{RUN_ID.value}.jsonl"
    rows = [
        {
            "version": "a5-run-ledger/1", "event": "run_started",
            "run_id": RUN_ID.value, "time_ns": 1,
            "stamp_prefix": _prepared()["stamp_prefix"],
            "document_fingerprint": FINGERPRINT.digest,
        },
        {
            "version": "a5-run-ledger/1", "event": "rebuild_commit_receipt",
            "run_id": RUN_ID.value, "time_ns": 2,
            "created_ids": ["7001"], "created_ids_count": 1,
            "bridge_error": False,
        },
    ]
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    journal = A5Journal.open(path)
    assert journal.state.legacy
    assert A5Journal.find_resumable(
        tmp_path,
        document_digest=FINGERPRINT.digest,
        request_hash=_prepared()["request_digest"],
    ) is None


class _LeaseStore:
    def __init__(self) -> None:
        self.owner: str | None = None
        self.renew_ok = True
        self.released = False

    async def acquire_a5_document_lease(
        self, fingerprint_digest, owner_token, run_id, ttl_seconds,
    ) -> bool:
        if self.owner is not None:
            return False
        self.owner = owner_token
        return True

    async def renew_a5_document_lease(
        self, fingerprint_digest, owner_token, ttl_seconds,
    ) -> bool:
        return self.owner == owner_token and self.renew_ok

    async def release_a5_document_lease(
        self, fingerprint_digest, owner_token,
    ) -> bool:
        if self.owner != owner_token:
            return False
        self.owner = None
        self.released = True
        return True


def test_durable_lease_is_exclusive_and_released():
    async def scenario():
        store = _LeaseStore()
        lease = await A5Lease.acquire(
            store, fingerprint_digest=FINGERPRINT.digest, run_id=RUN_ID,
            ttl_seconds=3)
        with pytest.raises(A5LeaseError, match="already has"):
            await A5Lease.acquire(
                store, fingerprint_digest=FINGERPRINT.digest, run_id=RUN_ID,
                ttl_seconds=3)
        await lease.ensure_held()
        assert await lease.release()
        assert store.released

    asyncio.run(scenario())


def test_lost_heartbeat_blocks_the_next_effect():
    async def scenario():
        store = _LeaseStore()
        lease = await A5Lease.acquire(
            store, fingerprint_digest=FINGERPRINT.digest, run_id=RUN_ID,
            ttl_seconds=3)
        store.renew_ok = False
        await asyncio.sleep(1.05)
        with pytest.raises(A5LeaseError, match="lease lost"):
            await lease.ensure_held()
        await lease.release()

    asyncio.run(scenario())
