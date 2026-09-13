"""Actual ProjectStore/archives/restart; native execution and reads are synthetic."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir import standalone_publish as publisher
from kir.level_settlement import qualify_level_settlement
from kir.project_store import ProjectStore, REALIZATION_STORE_SCHEMA, StoreConflict
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials
from kir.revit_discovery import load_discovery
from kir.revit_level_update import plan_level_elevation_update, prepare_level_update, LevelUpdateRefusal
from kir.revit_observation import prepare_element_observation, parse_element_observation
from kir.revit_transport import ConnectorTransportError
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_revit_level_update import (initial, make_case, bind, observation, proposed,
    plan, response_for, TARGET_ADDRESS, PROTECTED)
from kir.tests.test_revit_transport import ready_response


def observe_rows(credentials, rows, revision):
    query = prepare_element_observation(sorted(rows), target=credentials.target,
        precondition=ContextPrecondition("native-doc", revision), operation_id=str(uuid4()))
    response = response_for(query, credentials,
        {op.op_id: rows[op.to_dict()["unique_id"]] for op in query.planned.ops},
        changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
    return parse_element_observation(query, json.dumps(response), credentials=credentials,
                                     request_id=response["request_id"])


def shifted_rows(rows, uid, value):
    rows = deepcopy(rows)
    level = rows[uid]["level"]
    level.update(project_elevation_mm=value, reported_elevation_mm=value)
    level["elevation_parameter"]["value_internal_feet"] = value / 304.8
    return rows


def dispatch(store, update, credentials, archive_path, *, lost_reply=False):
    advertisement = load_discovery(json.dumps({"protocol": "kir-revit-connector/4",
        "target": credentials.target.to_dict(), "session_id": credentials.session_id, "token": credentials.token,
        "pipe_name": "synthetic-not-connected", "process_id": 123,
        "expires_utc": "2099-01-01T00:00:00.0000000Z"}).encode())
    operation = str(uuid4())
    expected = prepare_level_update(update, operation_id=operation)
    responses, requests = [], []
    def exchange(advertisement, raw, **kwargs):
        request = json.loads(raw)
        if request["kind"] == "ping":
            assert not Path(archive_path).exists()
            return json.dumps(ready_response(request)).encode()
        requests.append(request)
        baseline = store.level_baseline(update.original_binding["binding_digest"])
        archive = SavedExecutionRecord.load(archive_path)
        assert baseline.pending_archive_digest == archive.digest
        assert store.get_level_update_archive(archive.digest)._raw == archive._raw
        assert request["kind"] == "execute" and request["source"] == expected.source
        assert request["precondition"] == update.precondition.to_dict()
        if lost_reply:
            raise ConnectorTransportError("synthetic_loss", "response", delivery="unknown")
        op = expected.planned.to_ops()[0]
        response = response_for(expected, credentials,
            {"ok": True, op["id"]: {"id": str(op["target"]["value"]), "param": op["param"]}},
            changes={"added": [], "modified": [op["target"]["value"]], "deleted": [],
                     "transaction_names": ["synthetic setter"], "truncated": False})
        response["request_id"] = request["request_id"]
        responses.append(response)
        return json.dumps(response).encode()
    with patch.object(publisher, "exchange", side_effect=exchange):
        attempt = publisher.publish_level_update(update, advertisement=advertisement, client_path=sys.executable,
            archive_path=archive_path, operation_id=operation, project_store=store)
    assert len(requests) == 1
    return attempt, responses[0]


def first_round(tmp_path):
    source = make_case(tmp_path)
    origin = bind(source)
    before = observation(source, origin)
    update = plan(source, origin, before)
    root = initial(explicit=False)
    store = ProjectStore.create(tmp_path / "project.sqlite", root, schema=REALIZATION_STORE_SCHEMA)
    base = source["project"]
    store.commit(base, expected_revision=root.revision_id)
    r1 = proposed(base)
    store.commit(r1, expected_revision=base.revision_id)
    attempt, response = dispatch(store, update, source["credentials"], tmp_path / "first-update.sqlite")
    # Authoring can get ahead while a native operation is pending.
    r2 = proposed(r1, value=4200.0)
    store.commit(r2, expected_revision=r1.revision_id)
    uid = update.to_dict()["target_identity"]["unique_id"]
    after = observe_rows(source["credentials"], shifted_rows(before.rows, uid, 3800), 10)
    qualified = qualify_level_settlement(attempt.record, json.dumps(response), after=after,
        credentials=source["credentials"], request_id=response["request_id"])
    result = store.commit_level_settlement(qualified, expected_checkpoint=None,
                                          expected_pending_archive=attempt.record.digest)
    assert result.inserted and store.head().revision_id == r2.revision_id
    baseline = store.level_baseline(origin.digest)
    assert baseline.baseline_revision == r1.revision_id and baseline.pending_archive_digest is None
    return source, store, origin, r1, r2, qualified


def continue_round(store_path, credentials, stream_id, archive_path):
    """Invoked in a NEW Python process, with no original publication object."""
    store = ProjectStore.open(store_path, readonly=False)
    baseline = store.level_baseline(stream_id)
    r1, r2 = store.get(baseline.baseline_revision), store.head()
    observed = observe_rows(credentials, baseline.accepted["after"]["rows"], 10)
    update = plan_level_elevation_update(r1, r2, baseline=baseline, observation=observed,
        target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    assert update.publication is None and update.baseline is baseline
    assert len(update.planned.to_ops()) == 1 and update.planned.to_ops()[0]["op"] == "set_param"
    attempt, response = dispatch(store, update, credentials, Path(archive_path))
    submitted = attempt.record.update_submission
    assert submitted["schema"] == "kir-submitted-level-update/2"
    assert submitted["baseline_ref"]["checkpoint_digest"] == baseline.checkpoint_digest
    assert submitted["original_publication"] == baseline.original
    uid = update.to_dict()["target_identity"]["unique_id"]
    after = observe_rows(credentials, shifted_rows(observed.rows, uid, 4200), 11)
    qualified = qualify_level_settlement(attempt.record, json.dumps(response), after=after,
        credentials=credentials, request_id=response["request_id"])
    store.commit_level_settlement(qualified, expected_checkpoint=baseline.checkpoint_digest,
                                 expected_pending_archive=attempt.record.digest)
    current = store.level_baseline(stream_id)
    assert current.baseline_revision == r2.revision_id and current.pending_archive_digest is None
    return {"checkpoint": current.checkpoint_digest, "revision": current.baseline_revision,
        "original_revision": current.original["project"]["revision_id"],
        "original_digest": current.original["binding_digest"], "archive": attempt.record.digest}


def test_r0_r1_r2_real_history_and_reservation_survive_python_restart(tmp_path):
    source, store, origin, r1, r2, qualified = first_round(tmp_path)
    before_history = tuple(revision.dumps() for revision in store.history())
    auth = source["credentials"]
    script = '''
import json, sys
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.tests.test_level_update_iteration import continue_round
data = json.load(sys.stdin)
auth = SessionCredentials(RuntimeTarget(**data["target"]), data["session_id"], data["token"])
print(json.dumps(continue_round(sys.argv[1], auth, sys.argv[2], sys.argv[3])))
'''
    child = subprocess.run([sys.executable, "-B", "-c", script, str(store.path), origin.digest,
        str(tmp_path / "second-update.sqlite")], input=json.dumps({"target": auth.target.to_dict(),
        "session_id": auth.session_id, "token": auth.token}), text=True, capture_output=True, timeout=60)
    assert child.returncode == 0, child.stderr
    report = json.loads(child.stdout)
    assert report["revision"] == r2.revision_id and report["original_revision"] == source["project"].revision_id
    assert report["original_digest"] == origin.digest and report["checkpoint"] != qualified.digest
    assert tuple(revision.dumps() for revision in store.history()) == before_history
    assert store.level_baseline(origin.digest).baseline_revision == r2.revision_id
    redelivery = store.commit_level_settlement(qualified, expected_checkpoint=None,
        expected_pending_archive=qualified.record.digest)
    assert not redelivery.inserted and redelivery.checkpoint_digest == report["checkpoint"]
    assert store.level_baseline(origin.digest).pending_archive_digest is None


def test_lost_second_reply_keeps_pending_and_blocks_another_plan(tmp_path):
    source, store, origin, r1, r2, _ = first_round(tmp_path)
    baseline = store.level_baseline(origin.digest)
    observed = observe_rows(source["credentials"], baseline.accepted["after"]["rows"], 10)
    update = plan_level_elevation_update(r1, r2, baseline=baseline, observation=observed,
        target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    with pytest.raises(ConnectorTransportError):
        dispatch(store, update, source["credentials"], tmp_path / "lost-second.sqlite", lost_reply=True)
    current = ProjectStore.open(store.path).level_baseline(origin.digest)
    assert current.pending_archive_digest is not None and current.checkpoint_digest == baseline.checkpoint_digest
    with pytest.raises(LevelUpdateRefusal, match="level_update_pending"):
        plan_level_elevation_update(r1, r2, baseline=current, observation=observed,
            target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    # A stale already-prepared plan cannot evade the store's pending CAS either.
    with pytest.raises(StoreConflict):
        dispatch(store, update, source["credentials"], tmp_path / "must-not-send.sqlite")
    assert store.level_baseline(origin.digest).pending_archive_digest == current.pending_archive_digest


@pytest.mark.parametrize("fault", ["old_revision", "changed_protected", "wrong_base"])
def test_checkpoint_requires_matching_fresh_observation_and_authored_base(tmp_path, fault):
    source, store, origin, r1, r2, _ = first_round(tmp_path)
    baseline = store.level_baseline(origin.digest)
    rows = baseline.accepted["after"]["rows"]
    if fault == "changed_protected":
        uid = next(row["element_identity"]["unique_id"] for row in baseline.original["outputs"]
                   if (row["instance_key"], row["output_key"]) == PROTECTED[0])
        rows[uid]["name"] = "External change"
    observed = observe_rows(source["credentials"], rows, 9 if fault == "old_revision" else 10)
    with pytest.raises(LevelUpdateRefusal):
        plan_level_elevation_update(source["project"] if fault == "wrong_base" else r1, r2,
            baseline=baseline, observation=observed, target=TARGET_ADDRESS, protected_outputs=PROTECTED)


def test_imported_baseline_claims_cannot_bypass_the_actual_stored_after_fields(tmp_path):
    source, store, origin, r1, r2, _ = first_round(tmp_path)
    baseline = store.level_baseline(origin.digest)
    accepted = baseline.accepted
    protected = next(row["element_identity"]["unique_id"] for row in baseline.original["outputs"]
                     if (row["instance_key"], row["output_key"]) == PROTECTED[0])
    accepted["after"]["rows"][protected]["name"] = "Unreconciled external change"
    # This public inert DTO is deliberately not an authority: its unchanged
    # checkpoint reference must still be checked against the real store data.
    altered = replace(baseline, _accepted_json=json.dumps(accepted))
    observed = observe_rows(source["credentials"], accepted["after"]["rows"], 10)
    update = plan_level_elevation_update(r1, r2, baseline=altered, observation=observed,
        target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    with pytest.raises(StoreConflict):
        dispatch(store, update, source["credentials"], tmp_path / "must-not-send-changed-scope.sqlite")
    assert store.level_baseline(origin.digest).pending_archive_digest is None
