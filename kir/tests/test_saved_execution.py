"""Portable single-record source archive, not replay permission or loaded code."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from uuid import uuid4

import pytest

from kir import saved_execution as archive
from kir.revit_connector import (RuntimeTarget, ContextPrecondition, SessionCredentials, prepare_execution)


ROOT = Path(__file__).resolve().parents[2]
TARGET = RuntimeTarget("11c09015-32c5-4fd3-8a83-eac1d50d8b4d", "73d57ec5-12b5-4d8e-85d8-fdd06ce7c9c9", "2026")
OPERATION = "be8501eb-028d-492a-842c-5917cf9fe8a2"
PROGRAM = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "Ground 😀"}]}


def prepared(program=None, *, target=TARGET, precondition=None, operation_id=OPERATION):
    return prepare_execution(program or deepcopy(PROGRAM), target=target,
        precondition=precondition or ContextPrecondition(" opaque-open-document ", 7, 0, ""), operation_id=operation_id)


@pytest.fixture
def saved(tmp_path):
    fresh = prepared()
    path = tmp_path / "saved ?#Ю.sqlite"
    record = archive.SavedExecutionRecord.create_new(path, fresh)
    return path, fresh, record


def rewrite(path, change, *, canonical=True):
    with sqlite3.connect(path) as db:
        data = json.loads(db.execute("SELECT payload FROM saved_execution").fetchone()[0])
        change(data)
        data["record_digest"] = archive._hash({k: v for k, v in data.items() if k != "record_digest"})
        payload = archive._canonical(data) if canonical else json.dumps(data, indent=2, ensure_ascii=False)
        db.execute("UPDATE saved_execution SET payload=?", (payload,))


def test_exact_record_preserves_full_source_plan_ground_units_without_credentials(saved):
    path, fresh, record = saved
    value = record.to_dict()
    assert value["source"] == fresh.source
    assert value["binding"] == fresh.binding_dict()
    assert value["plan_evidence"] == fresh.planned.to_evidence_dict()
    assert value["planned_units"] == list(fresh.planned.units)
    assert value["grounded_evidence"] == fresh.grounded.to_evidence_dict()
    assert value["source_byte_length"] == len(fresh.source.encode("utf-8"))
    assert value["source_utf16_units"] == len(fresh.source.encode("utf-16-le")) // 2
    assert "token" not in value and "session_id" not in value and "project_id" not in value
    assert fresh.source not in repr(record)
    record.require_matches(fresh)
    assert archive.SavedExecutionRecord.load(path).to_dict() == value
    assert not any(hasattr(record, name) for name in ("execute_request", "to_prepared", "planned", "grounded"))
    with pytest.raises(TypeError): archive.SavedExecutionRecord()
    value["binding"]["target"]["journal_id"] = str(uuid4())
    assert record.binding_dict() == fresh.binding_dict()
    if os.name == "posix": assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_lookup_and_recovery_preserve_original_binding_after_session_rotation(saved):
    _, fresh, record = saved
    credentials = SessionCredentials(TARGET, str(uuid4()), "transient-token-not-in-archive")
    original = record.to_dict()
    lookup = record.receipt_request(credentials, request_id=str(uuid4()))
    assert lookup["kind"] == "receipt" and lookup["operation_id"] == fresh.operation_id
    assert "source" not in lookup and "source_sha256" not in lookup and "precondition" not in lookup
    other = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2023"), str(uuid4()), "fresh-B-credential")
    with pytest.raises(archive.SavedExecutionError, match="target_mismatch"):
        record.receipt_request(other, request_id=str(uuid4()))
    recovery = record.recovery_request(other, request_id=str(uuid4()))
    assert recovery["kind"] == "recover_receipt" and recovery["target"] == other.target.to_dict()
    assert recovery["recovery_target"] == fresh.target.to_dict()
    assert recovery["operation_id"] == fresh.operation_id and "source" not in recovery
    assert record.to_dict() == original and credentials.token not in repr(record)
    assert credentials.token not in archive._canonical(record.to_dict())


@pytest.mark.parametrize("axis", ["journal", "instance", "year", "operation", "document", "revision", "view", "selection", "source"])
def test_every_original_binding_axis_must_match_fresh_artifact(saved, axis):
    _, fresh, record = saved
    kwargs = {}
    if axis in ("journal", "instance", "year"):
        kwargs["target"] = replace(TARGET, **{{"journal": "journal_id", "instance": "instance_id", "year": "revit_version"}[axis]:
            "2023" if axis == "year" else str(uuid4())})
    elif axis == "operation": kwargs["operation_id"] = str(uuid4())
    elif axis == "source": kwargs["program"] = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 100}]}
    else:
        fields = {"document": ("document_key", "another"), "revision": ("revision", 8),
                  "view": ("active_view_id", None), "selection": ("selection_digest", None)}
        key, value = fields[axis]
        kwargs["precondition"] = replace(fresh.precondition, **{key: value})
    with pytest.raises(archive.SavedExecutionError, match="saved_execution_mismatch"):
        record.require_matches(prepared(**kwargs))


def test_equal_full_source_is_not_equal_original_macro_plan(tmp_path):
    program = {"ops": [{"op": "stack", "id": "s", "levels": 1, "floor": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]}]}
    original = prepared(program)
    replayed = prepared({"ir_version": original.planned.ir_version, "intent": original.planned.intent,
                         "ops": original.planned.to_ops()})
    assert original.source == replayed.source and original.binding_dict() == replayed.binding_dict()
    assert original.planned.plan_digest != replayed.planned.plan_digest
    saved = archive.SavedExecutionRecord.create_new(tmp_path / "macro.sqlite", original)
    with pytest.raises(archive.SavedExecutionError, match="saved_execution_mismatch"):
        saved.require_matches(replayed)
    assert saved.receipt_request(SessionCredentials(TARGET, str(uuid4()), "new-session"), request_id=str(uuid4()))["kind"] == "receipt"


def test_units_are_compared_even_when_plan_digest_and_source_ignore_them(saved):
    _, original, record = saved
    plan = replace(original.planned, units=({"id": "different-unit-claim", "kind": "wall"},))
    changed = prepared(plan)
    assert original.source == changed.source and original.planned.plan_digest == changed.planned.plan_digest
    with pytest.raises(archive.SavedExecutionError, match="saved_execution_mismatch"):
        record.require_matches(changed)


@pytest.mark.parametrize("case", ["source", "source_length", "source_utf16", "schema", "protocol", "planhash", "groundhash", "groundparent", "units",
    "credential", "session", "float_revision", "zero_revision_bool", "noncanonical_guid", "plan_boolean", "extra_table", "extra_row", "blob", "noncanonical_json"])
def test_malformed_or_rehashed_database_cannot_load_as_original_record(saved, case):
    path, _, _ = saved
    if case == "extra_table":
        with sqlite3.connect(path) as db: db.execute("CREATE TABLE unexpected(x)")
    elif case == "extra_row":
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute("INSERT INTO saved_execution SELECT 2,payload FROM saved_execution")
    elif case == "blob":
        with sqlite3.connect(path) as db: db.execute("UPDATE saved_execution SET payload=CAST(payload AS BLOB)")
    else:
        def change(data):
            if case == "source": data["source"] += "\n// changed"
            elif case == "source_length": data["source_byte_length"] += 1
            elif case == "source_utf16": data["source_utf16_units"] += 1
            elif case == "schema": data["schema"] = "kir-saved-execution/999"
            elif case == "protocol": data["protocol"] = "kir-revit-connector/3"
            elif case == "planhash": data["plan_evidence"]["intent"] = "another plan"
            elif case == "groundhash": data["grounded_evidence"]["resolutions"] = [{}]
            elif case == "groundparent": data["grounded_evidence"]["plan_digest"] = "0" * 64
            elif case == "units": data["planned_units"] = {}
            elif case == "credential": data["token"] = "must-not-be-an-archive-field"
            elif case == "session": data["binding"]["session_id"] = str(uuid4())
            elif case == "float_revision": data["binding"]["precondition"]["revision"] = 7.0
            elif case == "zero_revision_bool": data["binding"]["precondition"]["revision"] = False
            elif case == "noncanonical_guid": data["binding"]["target"]["instance_id"] = data["binding"]["target"]["instance_id"].upper()
            elif case == "plan_boolean":
                data["plan_evidence"]["source_op_count"] = True
                data["plan_evidence"]["plan_digest"] = archive._hash({k:v for k,v in data["plan_evidence"].items() if k != "plan_digest"})
        rewrite(path, change, canonical=case != "noncanonical_json")
    before = path.read_bytes()
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)
    assert path.read_bytes() == before


def test_consistently_rehashed_claims_do_not_match_fresh_source(saved):
    path, fresh, record = saved
    def change(data):
        data["source"] += "\n// coherent but foreign captured bytes"
        data["source_byte_length"] = len(data["source"].encode())
        data["source_utf16_units"] = len(data["source"].encode("utf-16-le")) // 2
        data["binding"]["source_sha256"] = hashlib.sha256(data["source"].encode()).hexdigest()
    rewrite(path, change)
    loaded = archive.SavedExecutionRecord.load(path)
    assert loaded.to_dict()["claims"]["compiler_evidence"] == "retained_claims_not_replayed"
    with pytest.raises(archive.SavedExecutionError, match="saved_execution_mismatch"): loaded.require_matches(fresh)
    assert loaded.digest != record.digest and not hasattr(loaded, "execute_request")


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '{"x":"\\ud800"}', '['*66+'0'+']'*66])
def test_strict_json_refuses_duplicates_nonfinite_surrogates_depth(saved, raw):
    path, _, _ = saved
    with sqlite3.connect(path) as db: db.execute("UPDATE saved_execution SET payload=?", (raw,))
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)


@pytest.mark.parametrize("kind", ["empty", "garbage", "existing", "directory", "symlink", "dangling_symlink"])
def test_existing_paths_are_never_overwritten_or_adopted(tmp_path, kind):
    path, fresh = tmp_path / "existing.sqlite", prepared()
    if kind == "empty": path.touch()
    elif kind == "garbage": path.write_bytes(b"not SQLite")
    elif kind == "existing": archive.SavedExecutionRecord.create_new(path, fresh)
    elif kind == "directory": path.mkdir()
    else:
        target = tmp_path / "target.sqlite"
        if kind == "symlink": archive.SavedExecutionRecord.create_new(target, fresh)
        path.symlink_to(target)
    before = path.read_bytes() if path.is_file() else None
    with pytest.raises(archive.SavedExecutionError, match="archive_exists"):
        archive.SavedExecutionRecord.create_new(path, fresh)
    if before is not None: assert path.read_bytes() == before
    if kind.endswith("symlink"):
        with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_recovery_sidecars_cannot_be_removed_or_ignored(saved, suffix):
    path, fresh, _ = saved
    sidecar = Path(str(path) + suffix)
    sidecar.write_bytes(b"preserve-for-inspection")
    before = path.read_bytes()
    for action in (lambda: archive.SavedExecutionRecord.load(path), lambda: archive.SavedExecutionRecord.create_new(path, fresh)):
        with pytest.raises(archive.SavedExecutionError, match="archive_recovery_required"): action()
    assert path.read_bytes() == before and sidecar.read_bytes() == b"preserve-for-inspection"


def test_bounds_checked_before_creating_or_loading_big_payload(saved, tmp_path, monkeypatch):
    path, fresh, _ = saved
    monkeypatch.setattr(archive, "MAX_RECORD_BYTES", 100)
    new = tmp_path / "never-created.sqlite"
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.create_new(new, fresh)
    assert not new.exists()
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)


def test_postcommit_flush_failure_is_unconfirmed_not_success_or_repair(tmp_path, monkeypatch):
    path, fresh = tmp_path / "unconfirmed.sqlite", prepared()
    def fail(_path): raise OSError("controlled flush failure")
    monkeypatch.setattr(archive, "_flush_created", fail)
    with pytest.raises(archive.SavedExecutionError, match="archive_durability_unconfirmed"):
        archive.SavedExecutionRecord.create_new(path, fresh)
    assert path.exists()
    archive.SavedExecutionRecord.load(path).require_matches(fresh)
    with pytest.raises(archive.SavedExecutionError, match="archive_exists"):
        archive.SavedExecutionRecord.create_new(path, fresh)


def test_query_grounded_null_is_retained_without_fabricated_ground_evidence(tmp_path):
    fresh = prepared({"ops": [{"op": "query_list", "kind": "wall"}]})
    assert fresh.grounded is None
    record = archive.SavedExecutionRecord.create_new(tmp_path / "query.sqlite", fresh)
    assert record.to_dict()["grounded_evidence"] is None
    record.require_matches(fresh)


@pytest.mark.parametrize("phase", ["insert", "commit_ack"])
def test_sqlite_failure_boundary_is_named_and_retains_failed_path(tmp_path, monkeypatch, phase):
    path = tmp_path / "failed.sqlite"
    real_connect = archive.sqlite3.connect
    class FaultConnection:
        def __init__(self, inner): self.inner = inner
        def __getattr__(self, name): return getattr(self.inner, name)
        def execute(self, sql, *args):
            if phase == "insert" and sql.startswith("INSERT"):
                raise sqlite3.OperationalError("controlled disk error")
            result = self.inner.execute(sql, *args)
            if phase == "commit_ack" and sql == "COMMIT":
                raise sqlite3.OperationalError("commit ack lost after actual commit")
            return result
    monkeypatch.setattr(archive.sqlite3, "connect", lambda *a, **kw: FaultConnection(real_connect(*a, **kw)))
    expected = "archive_storage_failed" if phase == "insert" else "archive_durability_unconfirmed"
    with pytest.raises(archive.SavedExecutionError, match=expected):
        archive.SavedExecutionRecord.create_new(path, prepared())
    assert path.exists()
    if phase == "commit_ack": archive.SavedExecutionRecord.load(path).require_matches(prepared())
    else:
        with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)


def test_loading_does_not_issue_writable_pragmas_or_update_statements(saved, monkeypatch):
    path, _, _ = saved
    statements = []
    connect = archive._connect
    def recording(path, *, readonly):
        assert readonly is True
        connection = connect(path, readonly=readonly)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(archive, "_connect", recording)
    archive.SavedExecutionRecord.load(path)
    assert statements and all(s.startswith(("PRAGMA", "SELECT", "BEGIN")) for s in statements)
    assert not any("journal_mode=" in s or "synchronous=" in s for s in statements)


def test_extra_file_flush_uses_write_capable_nontruncating_handle(tmp_path, monkeypatch):
    path = tmp_path / "flush-access.sqlite"
    actual = archive.os.open
    calls = []
    def recording(name, flags, *args, **kwargs):
        calls.append((Path(name), flags))
        return actual(name, flags, *args, **kwargs)
    monkeypatch.setattr(archive.os, "open", recording)
    archive.SavedExecutionRecord.create_new(path, prepared())
    flush_flags = [flags for name, flags in calls if name == path and not flags & os.O_CREAT]
    assert flush_flags == [os.O_RDWR]
    assert not flush_flags[0] & os.O_TRUNC


CHILD = r'''
import json, os, sys
from pathlib import Path
from kir.saved_execution import SavedExecutionRecord
from kir.revit_connector import RuntimeTarget,ContextPrecondition,prepare_execution
target=RuntimeTarget("11c09015-32c5-4fd3-8a83-eac1d50d8b4d","73d57ec5-12b5-4d8e-85d8-fdd06ce7c9c9","2026")
fresh=prepare_execution({'ops':[{'op':'create_level','id':'L','elev_mm':0,'name':'Ground 😀'}]},target=target,
    precondition=ContextPrecondition(' opaque-open-document ',7,0,''),operation_id='be8501eb-028d-492a-842c-5917cf9fe8a2')
'''


def child(code, *args):
    return subprocess.run([sys.executable, "-c", code, *map(str,args)], capture_output=True, text=True, timeout=25,
        env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE="1"))


def test_fresh_process_load_lookup_do_not_recompile_import_native_or_write(saved):
    path, _, record = saved
    before = path.read_bytes(), path.stat().st_mtime_ns
    ran = child(r'''
import importlib.abc,json,sys
from uuid import uuid4
class NoOCP(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='OCP' or fullname.startswith('OCP.'):raise AssertionError('native import')
sys.meta_path.insert(0,NoOCP())
from kir import compiler
def forbidden(*a,**kw):raise AssertionError('recompilation')
compiler.plan_program=compiler.compile_program=forbidden
from kir.saved_execution import SavedExecutionRecord
from kir.revit_connector import RuntimeTarget,SessionCredentials
r=SavedExecutionRecord.load(sys.argv[1]);binding=r.binding_dict()
auth=SessionCredentials(RuntimeTarget(**binding['target']),str(uuid4()),'fresh-private-token')
q=r.receipt_request(auth,request_id=str(uuid4()))
assert q['kind']=='receipt' and 'source' not in q
assert 'fresh-private-token' not in repr(r) and not hasattr(r,'execute_request')
print(r.digest)
''', path)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == record.digest and (path.read_bytes(),path.stat().st_mtime_ns) == before
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_two_real_writers_have_one_exclusive_winner(tmp_path):
    path = tmp_path/'race.sqlite'
    code = CHILD + "\ntry:\n r=SavedExecutionRecord.create_new(sys.argv[1],fresh);print('created')\nexcept Exception as e:\n print(getattr(e,'code',type(e).__name__))\n"
    env = dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE="1")
    workers = [subprocess.Popen([sys.executable,'-c',code,str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env) for _ in range(2)]
    results = [worker.communicate(timeout=25) for worker in workers]
    assert all(worker.returncode==0 for worker in workers),results
    assert sorted(out.strip() for out,err in results) in (['archive_exists','created'],['archive_recovery_required','created'])
    archive.SavedExecutionRecord.load(path).require_matches(prepared())


@pytest.mark.parametrize('point', ['before_insert','after_insert','after_commit'])
def test_real_process_interruption_never_repairs_failed_new_file(tmp_path, point):
    path=tmp_path/'crashed.sqlite'
    code=CHILD+r'''
from kir import saved_execution as module
real=module.sqlite3.connect
class CrashConnection:
 def __init__(self,connection):self.connection=connection
 def __getattr__(self,name):return getattr(self.connection,name)
 def execute(self,sql,*args):
  if sys.argv[2]=='before_insert' and sql.startswith('INSERT'):os._exit(71)
  result=self.connection.execute(sql,*args)
  if (sys.argv[2]=='after_insert' and sql.startswith('INSERT')) or (sys.argv[2]=='after_commit' and sql=='COMMIT'):os._exit(72)
  return result
module.sqlite3.connect=lambda *a,**kw:CrashConnection(real(*a,**kw))
SavedExecutionRecord.create_new(sys.argv[1],fresh)
'''
    ran=child(code,path,point)
    assert ran.returncode in (71,72),ran.stderr
    original={p.name:p.read_bytes() for p in path.parent.iterdir()}
    if point=='after_commit': archive.SavedExecutionRecord.load(path).require_matches(prepared())
    else:
        with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.load(path)
    with pytest.raises(archive.SavedExecutionError): archive.SavedExecutionRecord.create_new(path,prepared())
    assert {p.name:p.read_bytes() for p in path.parent.iterdir()} == original
