"""Archive/3 on real local files; native observations/transport remain synthetic.

No Revit/.NET build or live connection. Run with an explicitly contained pytest
basetemp. These checks cover local process restart, not machine power loss.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import stat
import subprocess
import sys
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir import saved_execution as archive
from kir import standalone_publish as publisher
from kir.revit_connector import prepare_execution
from kir.revit_discovery import load_discovery
from kir.revit_transport import ConnectorTransportError
from kir.tests.test_level_update_acceptance import memory_case
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_revit_transport import ready_response
from kir.update_submission import bind_level_update_submission


def inputs():
    case = memory_case()
    submission = bind_level_update_submission(case[1], case[2])
    return case, submission


def snapshot(directory):
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in directory.iterdir() if path.is_file()}


def test_file_archive_reopens_in_new_process_without_compilation_or_writes(tmp_path):
    case, submission = inputs()
    path = tmp_path / "level-update.sqlite"
    created = archive.SavedExecutionRecord.create_update_new(path, case[2], submission)
    before = snapshot(tmp_path)
    script = r'''
import hashlib, json, os, sys
from unittest.mock import patch
from kir.saved_execution import SavedExecutionRecord

def read_only(event, args):
    if event == "open":
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            raise AssertionError("archive load requested a Python file write")
    if event in {"os.mkdir", "os.remove", "os.rename", "subprocess.Popen"}:
        raise AssertionError("archive load requested a filesystem mutation/process")
sys.addaudithook(read_only)
with patch("kir.compiler.compile_program", side_effect=AssertionError("no compilation")), \
     patch("kir.compiler.plan_program", side_effect=AssertionError("no planning")), \
     patch("kir.revit_connector.prepare_execution", side_effect=AssertionError("no preparation")):
    record = SavedExecutionRecord.load(sys.argv[1])
assert not any(hasattr(record, name) for name in ("execute_request", "planned", "to_prepared"))
print(json.dumps({"digest": record.digest, "bytes_sha256": hashlib.sha256(record._raw).hexdigest(),
                  "submission": record.update_submission, "binding": record.binding_dict()}))
'''
    child = subprocess.run([sys.executable, "-B", "-c", script, str(path)],
                           capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(child.stdout)
    assert result == {"digest": created.digest, "bytes_sha256": hashlib.sha256(created._raw).hexdigest(),
                      "submission": submission.to_dict(), "binding": case[2].binding_dict()}
    assert snapshot(tmp_path) == before
    assert set(before) == {path.name}
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = archive.SavedExecutionRecord.load(path)
    loaded.require_matches(case[2], level_update=submission)


def test_existing_archive_is_not_overwritten_or_adopted_for_dispatch(tmp_path):
    case, submission = inputs()
    path = tmp_path / "existing.sqlite"
    archive.SavedExecutionRecord.create_update_new(path, case[2], submission)
    before = snapshot(tmp_path)
    with pytest.raises(archive.SavedExecutionError, match="archive_exists"):
        archive.SavedExecutionRecord.create_update_new(path, case[2], submission)
    assert snapshot(tmp_path) == before


def test_competing_creators_have_one_winner_without_changing_archive(tmp_path):
    case, submission = inputs()
    path = tmp_path / "competing.sqlite"
    barrier = Barrier(2)
    def create():
        barrier.wait(timeout=10)
        try:
            return archive.SavedExecutionRecord.create_update_new(path, case[2], submission)
        except archive.SavedExecutionError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    winners = [result for result in results if isinstance(result, archive.SavedExecutionRecord)]
    errors = [result for result in results if isinstance(result, archive.SavedExecutionError)]
    assert len(winners) == len(errors) == 1
    # The losing creator can see the winner's live rollback journal before O_EXCL.
    assert errors[0].code in {"archive_exists", "archive_recovery_required"}
    assert archive.SavedExecutionRecord.load(path)._raw == winners[0]._raw
    assert {item.name for item in tmp_path.iterdir()} == {path.name}


def test_inconsistent_fresh_preparation_refuses_before_creating_file(tmp_path):
    case, submission = inputs()
    update, original = case[1:3]
    unguarded = prepare_execution(update.planned, target=update.target,
        precondition=update.precondition, operation_id=original.operation_id)
    with pytest.raises(archive.SavedExecutionError):
        archive.SavedExecutionRecord.create_update_new(tmp_path / "must-not-exist.sqlite", unguarded, submission)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_existing_recovery_sidecar_is_preserved_and_never_adopted(tmp_path, suffix):
    case, submission = inputs()
    path = tmp_path / "sidecar.sqlite"
    sidecar = tmp_path / (path.name + suffix)
    sidecar.write_bytes(b"retained recovery evidence")
    before = snapshot(tmp_path)
    with pytest.raises(archive.SavedExecutionError, match="archive_recovery_required"):
        archive.SavedExecutionRecord.create_update_new(path, case[2], submission)
    assert snapshot(tmp_path) == before and not path.exists()


def advertisement_for(case):
    credentials = case[0]["credentials"]
    return load_discovery(json.dumps({"protocol": "kir-revit-connector/4",
        "target": credentials.target.to_dict(), "session_id": credentials.session_id,
        "token": credentials.token, "pipe_name": "synthetic-not-connected", "process_id": 123,
        "expires_utc": "2099-01-01T00:00:00.0000000Z"}).encode())


def test_post_commit_flush_failure_preserves_readable_archive_but_never_dispatches_mutation(tmp_path):
    case, _ = inputs()
    path = tmp_path / "flush-unconfirmed.sqlite"
    def only_probe(advertisement, raw, **kwargs):
        request = json.loads(raw)
        assert request["kind"] == "ping", "must not dispatch mutation"
        return json.dumps(ready_response(request)).encode()
    with patch.object(archive, "_flush_created", side_effect=OSError("synthetic flush failure")), \
         patch.object(publisher, "exchange", side_effect=only_probe) as transport:
        with pytest.raises(archive.SavedExecutionError, match="archive_durability_unconfirmed"):
            publisher.publish_level_update(case[1], advertisement=advertisement_for(case),
                client_path=sys.executable, archive_path=path, operation_id=case[2].operation_id)
    assert transport.call_count == 1
    loaded = archive.SavedExecutionRecord.load(path)
    assert loaded.binding_dict() == case[2].binding_dict()
    assert loaded.update_submission is not None
    with patch.object(publisher, "exchange", side_effect=only_probe):
        with pytest.raises(archive.SavedExecutionError, match="archive_exists"):
            publisher.publish_level_update(case[1], advertisement=advertisement_for(case),
                client_path=sys.executable, archive_path=path, operation_id=case[2].operation_id)


@pytest.mark.parametrize("lost_reply", [False, True])
def test_real_archive_is_reopenable_before_single_dispatch_and_after_lost_reply(tmp_path, lost_reply):
    case, _ = inputs()
    path = tmp_path / "before-dispatch.sqlite"
    requests = []
    def exchange(advertisement, raw, **kwargs):
        request = json.loads(raw)
        if request["kind"] == "ping":
            assert not path.exists()
            return json.dumps(ready_response(request)).encode()
        requests.append(request)
        assert len(requests) == 1 and request["kind"] == "execute"
        record = archive.SavedExecutionRecord.load(path)
        assert request["source"] == record.to_dict()["source"]
        assert request["precondition"] == case[1].precondition.to_dict()
        assert record.update_submission["expected_identities"] == [p.to_dict() for p in case[2].expected_identities]
        if lost_reply:
            raise ConnectorTransportError("synthetic_loss", "response", delivery="unknown")
        operation = case[2].planned.to_ops()[0]
        result = {"ok": True, operation["id"]: {"id": str(operation["target"]["value"]), "param": operation["param"]}}
        response = response_for(case[2], case[0]["credentials"], result,
            changes={"added": [], "modified": [901], "deleted": [],
                     "transaction_names": ["synthetic setter"], "truncated": False})
        response["request_id"] = request["request_id"]
        return json.dumps(response).encode()
    with patch.object(publisher, "exchange", side_effect=exchange):
        if lost_reply:
            with pytest.raises(ConnectorTransportError) as failure:
                publisher.publish_level_update(case[1], advertisement=advertisement_for(case),
                    client_path=sys.executable, archive_path=path, operation_id=case[2].operation_id)
            assert failure.value.may_retry is False
        else:
            attempt = publisher.publish_level_update(case[1], advertisement=advertisement_for(case),
                client_path=sys.executable, archive_path=path, operation_id=case[2].operation_id)
            assert attempt.execution_contract_satisfied and not attempt.intent_verified
    assert len(requests) == 1
    loaded = archive.SavedExecutionRecord.load(path)
    lookup = loaded.receipt_request(case[0]["credentials"], request_id=str(uuid4()))
    assert lookup["kind"] == "receipt" and lookup["operation_id"] == requests[0]["operation_id"]
    assert "source" not in lookup and "token" not in loaded.binding_dict()
