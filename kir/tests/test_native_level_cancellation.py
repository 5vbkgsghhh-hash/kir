"""Actual helper/Service/journal control with Revit stubs, not model execution."""
import json
from uuid import uuid4

import pytest

from kir.connector_result import assess_connector_saved_level_update_response
from kir.level_resolution import request_cancel_pending_level_update
from kir.project_store import ProjectStore, RESOLUTION_STORE_SCHEMA
from kir.revit_level_update import prepare_level_update
from kir.revit_transport import exchange
from kir.saved_execution import SavedExecutionRecord
from kir.update_submission import bind_level_update_submission
from kir.tests.test_revit_level_update import initial, make_case, bind, observation, plan, proposed
from kir.tests.test_revit_transport import helper, native_server, wire


def pending(tmp_path, advertisement):
    # The original BIM publication/read is synthetic, but the cancellation and
    # both journals below are real production-linked implementations.
    source = make_case(tmp_path, version=advertisement.credentials.target.revit_version,
                       credentials=advertisement.credentials)
    origin = bind(source)
    update = plan(source, origin, observation(source, origin))
    prepared = prepare_level_update(update, operation_id=str(uuid4()))
    root = initial(explicit=False)
    store = ProjectStore.create(tmp_path / "project.sqlite", root, schema=RESOLUTION_STORE_SCHEMA)
    store.commit(source["project"], expected_revision=root.revision_id)
    store.commit(proposed(source["project"]), expected_revision=source["project"].revision_id)
    record = SavedExecutionRecord.create_update_new(tmp_path / "pending.sqlite", prepared,
        bind_level_update_submission(update, prepared))
    store.reserve_level_update(record, expected_checkpoint=None)
    return store, record, prepared, origin.digest


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_cancel_real_journal_then_late_execute_returns_original_tombstone(native_server, helper, tmp_path, year):
    advertisement, native_root = native_server(year)
    store, record, prepared, stream = pending(tmp_path, advertisement)
    attempt = request_cancel_pending_level_update(store, stream_id=stream, expected_pending_archive=record.digest,
        advertisement=advertisement, client_path=helper, request_id=str(uuid4()), timeout_ms=10000)
    assert attempt.resolution_recorded and attempt.result.receipt["state"] == "cancelled_before_start"
    assert store.level_baseline(stream).pending_archive_digest is None
    assert store.level_baseline(stream).checkpoint_digest is None
    journal = native_root / "journals" / advertisement.credentials.target.journal_id / "operations.jsonl"
    before = journal.read_bytes()
    assert before
    request = prepared.execute_request(advertisement.credentials, request_id=str(uuid4()), timeout_ms=10000)
    # Deliberate test of a delayed old execute, not production replay permission.
    late = json.loads(exchange(advertisement, wire(request), client_path=helper, timeout_ms=10000))
    assert late["receipt"] == attempt.result.receipt
    assert journal.read_bytes() == before
    assert (native_root / "requests").read_text().splitlines() == ["cancel_before_start", "execute"]


def test_existing_seeded_commit_is_not_relabelled_cancelled_or_cleared(native_server, helper, tmp_path):
    advertisement, native_root = native_server()
    store, record, prepared, stream = pending(tmp_path, advertisement)
    op = prepared.planned.to_ops()[0]
    (native_root / "seed-result.json").write_text(json.dumps({"ok": True,
        op["id"]: {"id": str(op["target"]["value"]), "param": op["param"]}}), encoding="utf-8")
    execution = prepared.execute_request(advertisement.credentials, request_id=str(uuid4()), timeout_ms=10000)
    original = json.loads(exchange(advertisement, wire(execution), client_path=helper, timeout_ms=10000))["receipt"]
    journal = native_root / "journals" / advertisement.credentials.target.journal_id / "operations.jsonl"
    before = journal.read_bytes()
    attempt = request_cancel_pending_level_update(store, stream_id=stream, expected_pending_archive=record.digest,
        advertisement=advertisement, client_path=helper, request_id=str(uuid4()), timeout_ms=10000)
    assert not attempt.resolution_recorded and attempt.result.receipt == original
    assert attempt.result.outcome.execution.value == "committed"
    assert store.level_baseline(stream).pending_archive_digest == record.digest
    assert journal.read_bytes() == before


def test_cancel_with_wrong_binding_cannot_replace_recorded_tombstone(native_server, helper, tmp_path):
    advertisement, native_root = native_server()
    store, record, _, stream = pending(tmp_path, advertisement)
    attempt = request_cancel_pending_level_update(store, stream_id=stream, expected_pending_archive=record.digest,
        advertisement=advertisement, client_path=helper, request_id=str(uuid4()), timeout_ms=10000)
    journal = native_root / "journals" / advertisement.credentials.target.journal_id / "operations.jsonl"
    before = journal.read_bytes()
    request = record.cancel_before_start_request(advertisement.credentials, request_id=str(uuid4()), timeout_ms=10000)
    request["source_sha256"] = "f" * 64
    response = exchange(advertisement, wire(request), client_path=helper, timeout_ms=10000)
    parsed = json.loads(response)
    assert parsed["status"] == "operation_conflict" and parsed["ok"] is False
    assessed = assess_connector_saved_level_update_response(record, response, credentials=advertisement.credentials,
                                                           request_id=request["request_id"])
    assert assessed.outcome.execution.value == "unconfirmed" and journal.read_bytes() == before
    assert store.get_level_resolution_for_archive(record.digest)["resolution_digest"] == attempt.resolution_digest
