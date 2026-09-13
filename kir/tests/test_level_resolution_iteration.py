"""Real storage/reservation/restart with explicitly synthetic native no-start."""
import json
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir import standalone_publish as publisher
from kir.level_resolution import qualify_level_not_started
from kir.level_settlement import qualify_level_settlement
from kir.project_store import ProjectStore, RESOLUTION_STORE_SCHEMA
from kir.revit_discovery import load_discovery
from kir.revit_level_update import plan_level_elevation_update
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_level_update_iteration import first_round, dispatch, observe_rows, shifted_rows
from kir.tests.test_revit_level_update import (initial, make_case, bind, observation, proposed, plan,
    TARGET_ADDRESS, PROTECTED)
from kir.tests.test_revit_transport import ready_response


def reject_dispatch(store, update, credentials, path):
    advertisement = load_discovery(json.dumps({"protocol": "kir-revit-connector/4",
        "target": credentials.target.to_dict(), "session_id": credentials.session_id, "token": credentials.token,
        "pipe_name": "synthetic-not-connected", "process_id": 123,
        "expires_utc": "2099-01-01T00:00:00.0000000Z"}).encode())
    seen = []
    def exchange(advertisement, raw, **kwargs):
        request = json.loads(raw)
        if request["kind"] == "ping":
            assert not path.exists()
            return json.dumps(ready_response(request)).encode()
        record = SavedExecutionRecord.load(path)
        baseline = store.level_baseline(update.original_binding["binding_digest"])
        assert baseline.pending_archive_digest == record.digest
        assert request["kind"] == "execute" and request["source"] == record.to_dict()["source"]
        response = {"protocol": "kir-revit-connector/4", "request_id": request["request_id"],
            "target": credentials.target.to_dict(), "session_id": credentials.session_id,
            "ok": True, "status": "receipt", "error": None, "context": None,
            "receipt": {**record.binding_dict(), "document_key": record.binding_dict()["precondition"]["document_key"],
                "state": "cancelled_before_start", "started": False, "may_retry": True,
                "transaction_evidence": "not_observed", "semantic_evidence": "unverified",
                "result_json": None, "result_truncated": False, "result_error": None,
                "error": "synthetic admission cancellation", "changes": None,
                "timestamp_utc": "2026-09-05T12:00:00Z"}}
        seen.append(response)
        return json.dumps(response).encode()
    with patch.object(publisher, "exchange", side_effect=exchange):
        attempt = publisher.publish_level_update(update, advertisement=advertisement, client_path=sys.executable,
            archive_path=path, operation_id=str(uuid4()), project_store=store)
    assert len(seen) == 1 and not attempt.execution_contract_satisfied
    assert attempt.result.outcome.execution.value == "not_started"
    assert store.level_baseline(update.original_binding["binding_digest"]).pending_archive_digest == attempt.record.digest
    return attempt, seen[0]


def test_not_started_at_c1_then_new_explicit_attempt_after_python_restart(tmp_path):
    source, store, origin, r1, r2, accepted = first_round(tmp_path)
    before = tuple(revision.dumps() for revision in store.history())
    assert store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=r2.revision_id)
    baseline = store.level_baseline(origin.digest)
    observed = observe_rows(source["credentials"], baseline.accepted["after"]["rows"], 10)
    update = plan_level_elevation_update(r1, r2, baseline=baseline, observation=observed,
        target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    attempt, response = reject_dispatch(store, update, source["credentials"], tmp_path / "not-started.sqlite")
    resolved = qualify_level_not_started(attempt.record, json.dumps(response), credentials=source["credentials"],
        request_id=response["request_id"])
    result = store.commit_level_not_started(resolved, expected_checkpoint=accepted.digest,
                                           expected_pending_archive=attempt.record.digest)
    assert result.inserted and result.checkpoint_digest == accepted.digest and not result.may_retry
    assert store.level_baseline(origin.digest).baseline_revision == r1.revision_id
    assert store.get_level_resolution_for_archive(attempt.record.digest) == resolved.to_dict()
    assert tuple(revision.dumps() for revision in store.history()) == before
    # Session renewal is allowed; a Revit runtime/document restart is NOT being simulated.
    auth = source["credentials"]
    script = '''
import json, sys
from kir.project_store import ProjectStore
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.tests.test_level_update_iteration import continue_round
data = json.load(sys.stdin)
store = ProjectStore.open(sys.argv[1])
assert store.get_level_resolution_for_archive(data['old_archive'])['resolution_digest'] == data['resolution']
credentials = SessionCredentials(RuntimeTarget(**data['target']), data['session_id'], data['token'])
print(json.dumps(continue_round(sys.argv[1], credentials, sys.argv[2], sys.argv[3])))
'''
    child = subprocess.run([sys.executable, "-B", "-c", script, str(store.path), origin.digest,
        str(tmp_path / "new-explicit-attempt.sqlite")], input=json.dumps({"target": auth.target.to_dict(),
        "session_id": str(uuid4()), "token": "synthetic-renewed-session", "old_archive": attempt.record.digest,
        "resolution": resolved.digest}), text=True, capture_output=True, timeout=60)
    assert child.returncode == 0, child.stderr
    continued = json.loads(child.stdout)
    assert continued["revision"] == r2.revision_id and continued["archive"] != attempt.record.digest
    assert store.get_level_update_archive(continued["archive"]).binding_dict()["operation_id"] != attempt.record.binding_dict()["operation_id"]
    late = store.commit_level_not_started(resolved, expected_checkpoint=accepted.digest,
                                         expected_pending_archive=attempt.record.digest)
    assert not late.inserted and late.checkpoint_digest == continued["checkpoint"]
    assert tuple(revision.dumps() for revision in store.history()) == before


def test_initial_not_started_does_not_claim_r1_and_allows_a_fresh_original_attempt(tmp_path):
    source = make_case(tmp_path)
    origin = bind(source)
    before = observation(source, origin)
    update = plan(source, origin, before)
    root = initial(explicit=False)
    store = ProjectStore.create(tmp_path / "project.sqlite", root, schema=RESOLUTION_STORE_SCHEMA)
    store.commit(source["project"], expected_revision=root.revision_id)
    r1 = proposed(source["project"])
    store.commit(r1, expected_revision=source["project"].revision_id)
    attempt, response = reject_dispatch(store, update, source["credentials"], tmp_path / "first-refused.sqlite")
    resolved = qualify_level_not_started(attempt.record, json.dumps(response), credentials=source["credentials"],
        request_id=response["request_id"])
    store.commit_level_not_started(resolved, expected_checkpoint=None, expected_pending_archive=attempt.record.digest)
    baseline = store.level_baseline(origin.digest)
    assert baseline.checkpoint_digest is None and baseline.accepted is None and baseline.pending_archive_digest is None
    assert baseline.baseline_revision == source["project"].revision_id
    assert store.head().revision_id == r1.revision_id  # intent is not native acceptance
    # First-step retry still needs requalified original publication, not a made-up accepted checkpoint.
    fresh_before = observation(source, origin)
    fresh_update = plan(source, origin, fresh_before)
    new_attempt, reply = dispatch(store, fresh_update, source["credentials"], tmp_path / "new-original-attempt.sqlite")
    assert new_attempt.record.binding_dict()["operation_id"] != attempt.record.binding_dict()["operation_id"]
    uid = update.to_dict()["target_identity"]["unique_id"]
    after = observe_rows(source["credentials"], shifted_rows(fresh_before.rows, uid, 3800), 10)
    qualified = qualify_level_settlement(new_attempt.record, json.dumps(reply), after=after,
        credentials=source["credentials"], request_id=reply["request_id"])
    store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=new_attempt.record.digest)
    assert store.level_baseline(origin.digest).baseline_revision == r1.revision_id
    assert len(store.history()) == 3


def test_replayed_reservation_after_not_started_is_never_a_send_ticket(tmp_path):
    source, store, origin, r1, r2, accepted = first_round(tmp_path)
    store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=r2.revision_id)
    baseline = store.level_baseline(origin.digest)
    observed = observe_rows(source["credentials"], baseline.accepted["after"]["rows"], 10)
    update = plan_level_elevation_update(r1, r2, baseline=baseline, observation=observed,
        target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    attempt, response = reject_dispatch(store, update, source["credentials"], tmp_path / "old.sqlite")
    resolved = qualify_level_not_started(attempt.record, json.dumps(response), credentials=source["credentials"],
        request_id=response["request_id"])
    store.commit_level_not_started(resolved, expected_checkpoint=accepted.digest, expected_pending_archive=attempt.record.digest)
    auth = source["credentials"]
    declaration = load_discovery(json.dumps({"protocol": "kir-revit-connector/4", "target": auth.target.to_dict(),
        "session_id": auth.session_id, "token": auth.token, "pipe_name": "synthetic-not-connected", "process_id": 123,
        "expires_utc": "2099-01-01T00:00:00.0000000Z"}).encode())
    def only_probe(advertisement, raw, **kwargs):
        request = json.loads(raw)
        assert request["kind"] == "ping", "old reservation must never send a mutation"
        return json.dumps(ready_response(request)).encode()
    with patch.object(publisher, "exchange", side_effect=only_probe) as exchange:
        with pytest.raises(publisher.PublicationRefusal, match="update_already_reserved"):
            publisher.publish_level_update(update, advertisement=declaration, client_path=sys.executable,
                archive_path=tmp_path / "same-bytes-new-file.sqlite", operation_id=attempt.record.binding_dict()["operation_id"],
                project_store=store)
    assert exchange.call_count == 1  # readiness is not permission to resend
    assert store.level_baseline(origin.digest).pending_archive_digest is None
