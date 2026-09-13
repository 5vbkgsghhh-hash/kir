"""Archive/2 retains caller associations without granting loaded write authority."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

from kir import saved_execution as archive
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, _canonical, _hash
from kir.project_submission import bind_project_submission, validate_submission_claims
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution


ROOT = Path(__file__).resolve().parents[2]
TARGET = RuntimeTarget("07aaadf6-b76a-47f6-ab26-7a0c5a2d6550", "d0bd6240-cd09-4ccf-a121-4b135b7a94b7", "2026")
CONDITION = ContextPrecondition("original-doc", 17, 0, "")
OPERATION = "9348c3f7-473f-44b1-b173-906a5b64dd5f"


def values(project=None):
    if project is None:
        project = ProjectRevision("project-archive", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
            NamedOutput("stack", {"op": "stack", "levels": 2, "floor": [
                {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]})])])
    materialized = materialize_project(project, {})
    prepared = prepare_execution(materialized.planned, target=TARGET, precondition=CONDITION, operation_id=OPERATION)
    return project, materialized, prepared, bind_project_submission(project, materialized, prepared)


@pytest.fixture
def saved(tmp_path):
    project, materialized, prepared, submission = values()
    path = tmp_path / "project-execution.sqlite"
    record = archive.SavedExecutionRecord.create_project_new(path, prepared, submission)
    return path, project, materialized, prepared, submission, record


def resign(data):
    submission = data["project_submission"]
    submission["submission_digest"] = _hash({key: value for key, value in submission.items() if key != "submission_digest"})
    data["record_digest"] = archive._hash({key: value for key, value in data.items() if key != "record_digest"})
    return archive._canonical(data)


def rewrite(path, mutate):
    with sqlite3.connect(path) as db:
        data = json.loads(db.execute("SELECT payload FROM saved_execution").fetchone()[0])
        mutate(data)
        db.execute("UPDATE saved_execution SET payload=?", (resign(data),))


def test_one_record_contains_both_exact_association_and_execution_without_payload_duplication(saved):
    path, project, materialized, prepared, submission, record = saved
    data = record.to_dict()
    assert data["schema"] == archive.PROJECT_ARCHIVE_SCHEMA
    assert record.project_submission == submission.to_dict()
    assert record.binding_dict() == prepared.binding_dict()
    assert data["source"] == prepared.source
    assert data["plan_evidence"] == prepared.planned.to_evidence_dict()
    assert data["claims"]["project_binding"] == "retained_caller_association_not_native_attestation"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM saved_execution").fetchone() == (1,)
        assert db.execute("SELECT name FROM sqlite_schema").fetchall() == [("saved_execution",)]
    record.require_matches(prepared, submission=submission)
    assert len(data["project_submission"]["outputs"][0]["compiled_ops"]) == 4
    detached = record.project_submission
    detached["outputs"].clear()
    assert record.project_submission == submission.to_dict()
    assert not any(hasattr(record, key) for key in ("execute_request", "to_prepared", "prepared"))


def test_old_archive_one_bytes_and_default_matching_are_unchanged(tmp_path):
    _, _, prepared, submission = values()
    record = archive.SavedExecutionRecord.create_new(tmp_path / "old.sqlite", prepared)
    # Independent old /1 payload construction: no null submission field.
    data = {"schema": "kir-saved-execution/1", "protocol": "kir-revit-connector/4", "binding": prepared.binding_dict(),
        "source": prepared.source, "source_encoding": "utf-8", "source_byte_length": len(prepared.source.encode("utf-8")),
        "source_utf16_units": len(prepared.source.encode("utf-16-le")) // 2,
        "plan_evidence": prepared.planned.to_evidence_dict(), "planned_units": list(prepared.planned.units),
        "grounded_evidence": prepared.grounded.to_evidence_dict(),
        "claims": {"scope": "original_execution_input_archive", "compiler_evidence": "retained_claims_not_replayed",
            "native_execution": "not_established", "dispatch_state": "not_recorded", "retry_permission": "none",
            "credentials": "not_part_of_archive", "project_binding": "not_claimed"}}
    data["record_digest"] = archive._hash(data)
    assert record.to_dict() == data and record._raw == archive._canonical(data).encode()
    assert record.project_submission is None
    record.require_matches(prepared)
    before = (tmp_path / "old.sqlite").read_bytes()
    loaded = archive.SavedExecutionRecord.load(tmp_path / "old.sqlite")
    loaded.require_matches(prepared)
    with pytest.raises(archive.SavedExecutionError, match="submission_not_archived"):
        loaded.require_matches(prepared, submission=submission)
    with pytest.raises(archive.SavedExecutionError, match="archive_exists"):
        archive.SavedExecutionRecord.create_project_new(tmp_path / "old.sqlite", prepared, submission)
    assert (tmp_path / "old.sqlite").read_bytes() == before


@pytest.mark.parametrize("supplied", [None, {}, "serialized"])
def test_two_requires_fresh_submission_not_just_native_input_or_loaded_claims(saved, tmp_path, supplied):
    _, _, _, prepared, submission, record = saved
    argument = submission.to_dict() if supplied == "serialized" else supplied
    with pytest.raises(archive.SavedExecutionError, match="fresh_submission_required"):
        record.require_matches(prepared, submission=argument)
    path = tmp_path / "not-created.sqlite"
    with pytest.raises(archive.SavedExecutionError, match="fresh_submission_required"):
        archive.SavedExecutionRecord.create_project_new(path, prepared, argument)
    assert not path.exists()


def test_metadata_only_revisions_share_native_input_but_not_archive_association(saved, tmp_path):
    _, project, _, prepared, submission, record = saved
    next_project = project.revise(expected_revision=project.revision_id, metadata={"review": "another chosen revision"})
    _, _, next_prepared, next_submission = values(next_project)
    assert prepared.source == next_prepared.source and prepared.binding_dict() == next_prepared.binding_dict()
    with pytest.raises(archive.SavedExecutionError, match="saved_execution_mismatch"):
        record.require_matches(next_prepared, submission=next_submission)
    other = archive.SavedExecutionRecord.create_project_new(tmp_path / "different-caller-association.sqlite", next_prepared, next_submission)
    assert record.digest != other.digest and record.binding_dict() == other.binding_dict()
    assert record.project_submission["claims"]["native_execution"] == "not_established"
    # This is deliberately NOT global per-operation association CAS.
    assert other.project_submission["project"]["revision_id"] == next_project.revision_id


def test_same_source_replanned_macro_cannot_reuse_original_submission(saved, tmp_path):
    _, _, _, prepared, submission, record = saved
    replanned = prepare_execution({"ir_version": prepared.planned.ir_version, "intent": prepared.planned.intent,
        "ops": prepared.planned.to_ops()}, target=TARGET, precondition=CONDITION, operation_id=OPERATION)
    assert replanned.source == prepared.source and replanned.planned.plan_digest != prepared.planned.plan_digest
    with pytest.raises(archive.SavedExecutionError): record.require_matches(replanned, submission=submission)
    path = tmp_path / "never-created.sqlite"
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.create_project_new(path, replanned, submission)
    assert not path.exists()


@pytest.mark.parametrize("case", ["schema", "extra", "project_key", "project_schema", "instance_duplicate", "instance_missing", "instance_digest",
    "module_owner", "output_key", "output_id", "source_index", "source_op", "outputs_missing", "outputs_duplicate",
    "compiled_missing", "compiled_reverse", "compiled_id", "payload_digest", "result", "nested_count", "nested_digest",
    "execution", "precondition_scalar", "plan_digest", "units_digest", "ground_digest", "claims", "native_side_origin"])
def test_rehashed_cross_reference_corruption_is_rejected_without_writes(saved, case):
    path, _, _, _, _, _ = saved
    def mutate(data):
        value = data["project_submission"]
        output = value["outputs"][0]
        compiled = output["compiled_ops"][0]
        if case == "schema": value["schema"] = "kir-submitted-project-binding/999"
        elif case == "extra": value["source"] = "not part of this compact contract"
        elif case == "project_key": value["project"]["project_id"] = "foreign"
        elif case == "project_schema": value["project"]["schema"] = "kir-authoring-project/999"
        elif case == "instance_duplicate": value["instances"] *= 2
        elif case == "instance_missing": value["instances"].clear()
        elif case == "instance_digest": value["instances"][0]["instance_snapshot_digest"] = None
        elif case == "module_owner": value["instances"][0]["module_key"] = "foreign"
        elif case == "output_key": output["output_key"] = "foreign"
        elif case == "output_id": output["output_id"] = "0" * 64
        elif case == "source_index": output["source_index"] = False
        elif case == "source_op": output["source_op"] = "grid_array"
        elif case == "outputs_missing": value["outputs"].clear()
        elif case == "outputs_duplicate": value["outputs"] *= 2
        elif case == "compiled_missing": output["compiled_ops"].clear()
        elif case == "compiled_reverse": output["compiled_ops"].reverse()
        elif case == "compiled_id": compiled["op_id"] = "another"
        elif case == "payload_digest": compiled["payload_digest"] = "0" * 64
        elif case == "result": compiled["result"]["identity_cardinality"] = "many"
        elif case == "nested_count": compiled["nested_contract_count"] = False
        elif case == "nested_digest": compiled["nested_contracts_digest"] = "0" * 64
        elif case == "execution": value["execution"]["target"]["instance_id"] = str(uuid4())
        elif case == "precondition_scalar": value["execution"]["precondition"]["revision"] = 17.0
        elif case == "plan_digest": value["plan_digest"] = "0" * 64
        elif case == "units_digest": value["planned_units_digest"] = "0" * 64
        elif case == "ground_digest": value["grounded_evidence_digest"] = None
        elif case == "claims": value["claims"]["project_persistence"] = "verified"
        elif case == "native_side_origin":
            data["plan_evidence"]["ops"][0]["provenance"]["source_id"] = "foreign"
            data["plan_evidence"]["plan_digest"] = archive._hash({key: item for key, item in data["plan_evidence"].items() if key != "plan_digest"})
            value["plan_digest"] = data["plan_evidence"]["plan_digest"]
            data["grounded_evidence"]["plan_digest"] = value["plan_digest"]
            data["grounded_evidence"]["ground_digest"] = archive._hash({key: item for key, item in data["grounded_evidence"].items() if key != "ground_digest"})
            value["grounded_evidence_digest"] = data["grounded_evidence"]["ground_digest"]
    rewrite(path, mutate)
    before = path.read_bytes()
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("case", ["unknown", "missing_submission", "one_with_submission", "null_submission"])
def test_logical_schema_versions_never_implicitly_adopt_or_drop_submission(saved, case):
    path, _, _, _, _, _ = saved
    with sqlite3.connect(path) as db:
        data = json.loads(db.execute("SELECT payload FROM saved_execution").fetchone()[0])
        if case == "unknown": data["schema"] = "kir-saved-execution/999"
        elif case == "missing_submission": data.pop("project_submission")
        elif case == "one_with_submission": data["schema"] = "kir-saved-execution/1"
        else: data["project_submission"] = None
        data["record_digest"] = archive._hash({key: value for key, value in data.items() if key != "record_digest"})
        db.execute("UPDATE saved_execution SET payload=?", (archive._canonical(data),))
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)


def test_external_snapshot_hashes_are_retained_claims_not_invented_validation(saved):
    path, _, _, prepared, submission, _ = saved
    rewrite(path, lambda data: data["project_submission"]["instances"][0].update(instance_snapshot_digest="0" * 64))
    retained = archive.SavedExecutionRecord.load(path)
    # No full Project snapshot is in this record, so this digest has no local
    # payload to rederive. The original fresh association still refuses it.
    assert retained.project_submission["claims"]["project_persistence"] == "not_established"
    with pytest.raises(archive.SavedExecutionError, match="saved_execution_mismatch"):
        retained.require_matches(prepared, submission=submission)


def test_real_body_project_two_records_cross_check_plan_mesh_and_keep_only_references(tmp_path):
    from kir.tests.test_geometry_materialization import capture, project_for
    bundle = capture()
    project = project_for(bundle)
    m = materialize_project(project, {bundle.digest: bundle})
    prepared = prepare_execution(m.planned, target=TARGET, precondition=CONDITION, operation_id=OPERATION)
    submission = bind_project_submission(project, m, prepared)
    path = tmp_path / "body.sqlite"
    record = archive.SavedExecutionRecord.create_project_new(path, prepared, submission)
    body = record.project_submission["outputs"][0]["body"]
    assert body["descriptor"] == project.instances[0].outputs[0].geometry.to_dict()
    assert "mesh" not in body and "source" not in record.project_submission
    rewrite(path, lambda data: data["project_submission"]["outputs"][0]["body"].update(mesh_digest="0" * 64))
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)


def test_fresh_process_load_recovery_is_inert_and_has_no_fresh_factory_authority(saved):
    path, _, _, _, submission, record = saved
    before = path.read_bytes(), path.stat().st_mtime_ns
    code = r'''
import importlib.abc,json,sys
from uuid import uuid4
class NoOCP(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='OCP' or fullname.startswith('OCP.'):raise AssertionError('native import')
sys.meta_path.insert(0,NoOCP())
from kir import compiler,project_submission
def forbidden(*args,**kwargs):raise AssertionError('fresh code ran on load')
compiler.plan_program=compiler.compile_program=project_submission.bind_project_submission=forbidden
project_submission.SubmittedProjectBinding.__init__=forbidden
from kir.saved_execution import SavedExecutionRecord
from kir.revit_connector import RuntimeTarget,SessionCredentials
saved=SavedExecutionRecord.load(sys.argv[1])
assert type(saved.project_submission) is dict and not hasattr(saved,'execute_request')
auth=SessionCredentials(RuntimeTarget(str(uuid4()),str(uuid4()),'2023'),str(uuid4()),'fresh-private-session-B')
recovery=saved.recovery_request(auth,request_id=str(uuid4()))
assert recovery['kind']=='recover_receipt' and recovery['recovery_target']==saved.binding_dict()['target']
assert 'source' not in recovery and 'fresh-private-session-B' not in repr(saved)
print(json.dumps({'digest':saved.digest,'submission':saved.project_submission['submission_digest']}))
'''
    child = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=25,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == {"digest": record.digest, "submission": submission.digest}
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_real_process_crash_keeps_execution_and_project_as_one_record(tmp_path, phase):
    path = tmp_path / "crashed.sqlite"
    code = r'''
import os,sys
from kir.tests.test_saved_project_execution import values
from kir import saved_execution as module
_,_,prepared,submission=values()
connect=module.sqlite3.connect
class Crash:
 def __init__(self,inner):self.inner=inner
 def __getattr__(self,name):return getattr(self.inner,name)
 def execute(self,sql,*args):
  if sql=='COMMIT' and sys.argv[2]=='before_commit':os._exit(73)
  result=self.inner.execute(sql,*args)
  if sql=='COMMIT' and sys.argv[2]=='after_commit':os._exit(74)
  return result
module.sqlite3.connect=lambda *args,**kw:Crash(connect(*args,**kw))
module.SavedExecutionRecord.create_project_new(sys.argv[1],prepared,submission)
'''
    child = subprocess.run([sys.executable, "-c", code, str(path), phase], capture_output=True, text=True, timeout=25,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode in (73, 74), child.stderr
    files = {item.name: item.read_bytes() for item in path.parent.iterdir()}
    if phase == "before_commit":
        with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)
    else:
        _, _, prepared, submission = values()
        record = archive.SavedExecutionRecord.load(path)
        record.require_matches(prepared, submission=submission)
        assert record.project_submission["execution"] == record.binding_dict()
    assert {item.name: item.read_bytes() for item in path.parent.iterdir()} == files


def test_two_archive_flush_error_never_returns_success_and_retains_full_record(tmp_path, monkeypatch):
    _, _, prepared, submission = values()
    path = tmp_path / "uncertain.sqlite"
    def fail(_path): raise OSError("controlled directory/file flush error")
    monkeypatch.setattr(archive, "_flush_created", fail)
    with pytest.raises(archive.SavedExecutionError, match="archive_durability_unconfirmed"):
        archive.SavedExecutionRecord.create_project_new(path, prepared, submission)
    loaded = archive.SavedExecutionRecord.load(path)
    assert loaded.project_submission == submission.to_dict()
    loaded.require_matches(prepared, submission=submission)


def test_two_real_project_writers_commit_one_whole_caller_association(tmp_path):
    path = tmp_path / "race.sqlite"
    code = r'''
import json,sys
from kir.tests.test_saved_project_execution import values
from kir.saved_execution import SavedExecutionRecord,SavedExecutionError
project,_,_,_=values()
project=project.revise(expected_revision=project.revision_id,metadata={'selected_by':sys.argv[2]})
_,_,prepared,submission=values(project)
try:
 saved=SavedExecutionRecord.create_project_new(sys.argv[1],prepared,submission)
 print(json.dumps({'status':'created','revision':project.revision_id,'digest':saved.digest}))
except SavedExecutionError as error:
 print(json.dumps({'status':error.code}))
'''
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    children = [subprocess.Popen([sys.executable, "-c", code, str(path), name], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) for name in ("A", "B")]
    results = [process.communicate(timeout=25) for process in children]
    assert all(process.returncode == 0 for process in children), results
    reports = [json.loads(out) for out, _ in results]
    winner = [row for row in reports if row["status"] == "created"]
    loser = [row for row in reports if row["status"] != "created"]
    assert len(winner) == len(loser) == 1
    assert loser[0]["status"] in ("archive_exists", "archive_recovery_required")
    saved = archive.SavedExecutionRecord.load(path)
    assert saved.digest == winner[0]["digest"]
    assert saved.project_submission["project"]["revision_id"] == winner[0]["revision"]


def test_inert_owner_validator_cannot_return_fresh_authority(saved, monkeypatch):
    _, _, _, prepared, submission, _ = saved
    import kir.project_submission as owner
    def forbidden(*args, **kwargs): raise AssertionError("structural validation made fresh authority")
    monkeypatch.setattr(owner.SubmittedProjectBinding, "__init__", forbidden)
    monkeypatch.setattr(owner, "bind_project_submission", forbidden)
    assert validate_submission_claims(submission.to_dict(), execution=prepared.binding_dict(),
        plan_evidence=prepared.planned.to_evidence_dict(), planned_units=list(prepared.planned.units),
        grounded_evidence=prepared.grounded.to_evidence_dict()) is None
