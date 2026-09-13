"""Store/7 atomic no-start release; SQLite is real, native receipts synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from dataclasses import replace
import json
import sqlite3
import threading
from uuid import uuid4

import pytest

from kir import project_store as storage
from kir.create_publication import bind_create_receipt
from kir.project_store import (ProjectStore, CREATE_STORE_SCHEMA, CREATE_RESOLUTION_STORE_SCHEMA,
    STORE_SCHEMA, GEOMETRY_STORE_SCHEMA, REALIZATION_STORE_SCHEMA, RESOLUTION_STORE_SCHEMA, TASK_STORE_SCHEMA,
    StoreConflict, StoreCorrupt, StoreCommitUnknown, StoreNotFound, StoreReadOnly, StoreUpgradeRequired, ProjectStoreError)
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.tests.test_project_create_store import archive
from kir.tests.test_selected_project_submission import source_project


def evidence(record, state="cancelled_before_start"):
    credentials=SessionCredentials(RuntimeTarget(**record.binding_dict()["target"]),str(uuid4()),"synthetic-no-start-token")
    receipt={**record.binding_dict(),"document_key":record.binding_dict()["precondition"]["document_key"],
        "state":state,"started":False,"may_retry":True,"transaction_evidence":"not_observed",
        "semantic_evidence":"unverified","result_json":None,"result_error":None,"result_truncated":False,
        "changes":None,"error":None,"timestamp_utc":"2026-09-06T18:00:00Z"}
    if state in ("running_unknown","rolled_back"):
        receipt.update(started=True,may_retry=False)
    if state=="rolled_back":
        receipt.update(state="invocation_completed",transaction_evidence="changes_not_observed",
            result_json=json.dumps({"commit_status":"RolledBack","error":"controlled"}),
            changes={"added":[],"modified":[],"deleted":[],"transaction_names":[],"truncated":False})
    response={"protocol":"kir-revit-connector/4","target":credentials.target.to_dict(),"session_id":credentials.session_id,
        "request_id":str(uuid4()),"ok":True,"status":"receipt","context":None,"error":None,"receipt":receipt}
    return bind_create_receipt(record,json.dumps(response),credentials=credentials,request_id=response["request_id"])


def setup(tmp_path, schema=CREATE_RESOLUTION_STORE_SCHEMA):
    source=source_project()
    store=ProjectStore.create(tmp_path/"project.sqlite",source,schema=schema)
    record=archive(source,roots=("section",))
    if schema in (CREATE_STORE_SCHEMA,CREATE_RESOLUTION_STORE_SCHEMA):
        store.reserve_create_publication(record,expected_revision=source.revision_id)
    return store,source,record


def rows(store):
    with sqlite3.connect(store.path) as connection:
        names=[row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name:connection.execute('SELECT * FROM "'+name+'"').fetchall() for name in names}


def release(store,record,bound=None):
    return store.release_create_not_started(bound or evidence(record),expected_archive_digest=record.digest)


@pytest.mark.parametrize("native_state", ["cancelled_before_start","rejected_before_start","context_changed_before_start"])
def test_atomic_release_retains_input_receipt_uuid_and_original_output_scope(tmp_path,native_state):
    store,source,record=setup(tmp_path)
    before=rows(store)
    bound=evidence(record,native_state)
    result=release(store,record,bound)
    assert result.inserted and not result.may_retry and result.receipt_digest==bound.receipt_digest
    after=rows(store)
    assert after["create_inputs"]==before["create_inputs"]
    assert after["create_scope_owners"]==[] and len(after["create_receipts"])==len(after["create_resolutions"])==1
    retained=ProjectStore.open(store.path).get_create_publication(record.digest)
    assert retained.state=="released_not_started" and not retained.may_retry
    assert retained.output_ids==tuple(row["output_id"] for row in record.project_submission["outputs"])
    assert retained.record._raw==record._raw
    assert store.get_create_resolution(record.digest).receipt_digest==bound.receipt_digest
    assert not store.reserve_create_publication(record,expected_revision=source.revision_id).inserted
    assert store.head().dumps()==source.dumps()


def test_old_release_replay_never_deletes_new_publication_owners(tmp_path):
    store,source,record=setup(tmp_path)
    bound=evidence(record)
    release(store,record,bound)
    later=source.revise(expected_revision=source.revision_id,metadata={"draft":"later"})
    store.commit(later,expected_revision=source.revision_id)
    new=archive(later,roots=("section",))
    assert store.reserve_create_publication(new,expected_revision=later.revision_id).inserted
    before=rows(store)
    again=release(store,record,bound)
    assert not again.inserted and not again.may_retry and rows(store)==before
    assert store.get_create_publication(new.digest).state=="reserved"
    same_uuid=archive(later,roots=("section",),operation=record.binding_dict()["operation_id"])
    with pytest.raises(StoreConflict): store.reserve_create_publication(same_uuid,expected_revision=later.revision_id)


def test_release_does_not_require_current_authored_head(tmp_path):
    store,source,record=setup(tmp_path)
    later=source.revise(expected_revision=source.revision_id,metadata={"later":True})
    store.commit(later,expected_revision=source.revision_id)
    assert release(store,record).inserted
    assert store.head().revision_id==later.revision_id


@pytest.mark.parametrize("fault", ["running_unknown","rolled_back","forged-assessment","loaded-dict","wrong-archive"])
def test_no_release_without_exact_fresh_bound_no_start(tmp_path,fault):
    store,_,record=setup(tmp_path)
    bound=evidence(record,"running_unknown" if fault=="forged-assessment" else fault if fault in("running_unknown","rolled_back") else "cancelled_before_start")
    if fault=="forged-assessment":
        from kir.bridge_result import WriteResultAssessment
        from kir.outcome import program_not_started
        bound=copy(bound)
        object.__setattr__(bound,"assessment",replace(bound.assessment,assessment=WriteResultAssessment(program_not_started())))
    if fault=="loaded-dict": bound=bound.to_dict()
    before=rows(store)
    with pytest.raises(ProjectStoreError):
        store.release_create_not_started(bound,expected_archive_digest="f"*64 if fault=="wrong-archive" else record.digest)
    assert rows(store)==before


def test_no_resolution_without_proof_is_not_an_empty_owner_set(tmp_path):
    store,_,record=setup(tmp_path)
    assert store.get_create_resolution(record.digest) is None
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM create_scope_owners WHERE archive_digest=?",(record.digest,))
    with pytest.raises(StoreCorrupt): store.get_create_publication(record.digest)


@pytest.mark.parametrize("fault", ["missing-marker","orphan-marker","missing-receipt","changed-receipt","owners-returned","moved-marker"])
def test_broken_resolution_link_is_corruption(tmp_path,fault):
    store,source,record=setup(tmp_path)
    bound=evidence(record)
    release(store,record,bound)
    other=archive(source,roots=("unselected",))
    store.reserve_create_publication(other,expected_revision=source.revision_id)
    with sqlite3.connect(store.path) as connection:
        if fault=="missing-marker": connection.execute("DELETE FROM create_resolutions")
        elif fault=="orphan-marker": connection.execute("UPDATE create_resolutions SET archive_digest=?",("f"*64,))
        elif fault=="missing-receipt": connection.execute("DELETE FROM create_receipts")
        elif fault=="changed-receipt": connection.execute("UPDATE create_receipts SET payload='{}'")
        elif fault=="moved-marker": connection.execute("UPDATE create_resolutions SET archive_digest=?",(other.digest,))
        else:
            binding=record.binding_dict();target=binding["target"]
            connection.execute("INSERT INTO create_scope_owners VALUES (?,?,?,?,?,?)",(target["journal_id"],target["instance_id"],target["revit_version"],binding["precondition"]["document_key"],record.project_submission["outputs"][0]["output_id"],record.digest))
    for read in (lambda:store.get_create_publication(record.digest),lambda:store.get_create_resolution(record.digest),lambda:store.history()):
        with pytest.raises(StoreCorrupt): read()


def test_release_failure_before_commit_rolls_back_receipt_marker_and_owner_deletion(tmp_path,monkeypatch):
    store,_,record=setup(tmp_path)
    before=rows(store)
    def fail(connection): raise RuntimeError("before COMMIT")
    with monkeypatch.context() as patch:
        patch.setattr(storage,"_commit",fail)
        with pytest.raises(RuntimeError): release(store,record)
    assert rows(store)==before and store.get_create_resolution(record.digest) is None


def test_release_commit_ack_loss_is_inspectable_and_safe_to_repeat(tmp_path,monkeypatch):
    store,_,record=setup(tmp_path)
    bound=evidence(record)
    commit=storage._commit
    def lose_ack(connection):
        commit(connection)
        raise StoreCommitUnknown("after COMMIT")
    with monkeypatch.context() as patch:
        patch.setattr(storage,"_commit",lose_ack)
        with pytest.raises(StoreCommitUnknown): release(store,record,bound)
    reopened=ProjectStore.open(store.path,readonly=False)
    assert reopened.get_create_resolution(record.digest).receipt_digest==bound.receipt_digest
    assert not release(reopened,record,bound).inserted
    assert rows(reopened)["create_scope_owners"]==[]


def test_competing_connections_have_one_new_scope_owner_after_release(tmp_path):
    store,source,record=setup(tmp_path)
    release(store,record)
    candidates=[archive(source,roots=("section",)) for _ in range(2)]
    barrier=threading.Barrier(2)
    def reserve(candidate):
        local=ProjectStore.open(store.path,readonly=False)
        barrier.wait(timeout=10)
        try: return local.reserve_create_publication(candidate,expected_revision=source.revision_id).inserted
        except StoreConflict: return False
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(reserve,candidates))==[False,True]
    assert len(rows(store)["create_scope_owners"])==len(record.project_submission["outputs"])
    assert len(rows(store)["create_inputs"])==2


@pytest.mark.parametrize("schema", [STORE_SCHEMA,GEOMETRY_STORE_SCHEMA,REALIZATION_STORE_SCHEMA,RESOLUTION_STORE_SCHEMA,TASK_STORE_SCHEMA,CREATE_STORE_SCHEMA])
def test_upgrade_is_explicit_and_preserves_existing_rows_and_identities(tmp_path,schema):
    store,source,record=setup(tmp_path,schema)
    if schema==CREATE_STORE_SCHEMA: store.record_create_receipt(evidence(record))
    before=rows(store);old_store=store.store_id
    with pytest.raises(StoreUpgradeRequired): release(store,record)
    assert rows(store)==before and store.schema==schema
    assert store.upgrade_schema(CREATE_RESOLUTION_STORE_SCHEMA,expected_revision=source.revision_id)
    after=rows(store)
    assert all(after[name]==value for name,value in before.items() if name!="project_store")
    assert after["project_store"][0][1]==CREATE_RESOLUTION_STORE_SCHEMA
    assert (after["project_store"][0][0],*after["project_store"][0][2:])==(before["project_store"][0][0],*before["project_store"][0][2:])
    assert store.store_id==old_store and store.head().dumps()==source.dumps()
    assert after["create_resolutions"]==[]
    assert not store.upgrade_schema(CREATE_RESOLUTION_STORE_SCHEMA,expected_revision=source.revision_id)
    with pytest.raises(StoreConflict): store.upgrade_schema(CREATE_STORE_SCHEMA,expected_revision=source.revision_id)
    if schema!=CREATE_STORE_SCHEMA: store.reserve_create_publication(record,expected_revision=source.revision_id)
    assert release(store,record).inserted


def test_readonly_resolution_lookup_and_release_boundary(tmp_path):
    store,_,record=setup(tmp_path)
    release(store,record)
    reader=ProjectStore.open(store.path)
    before=store.path.read_bytes()
    assert reader.get_create_resolution(record.digest).to_dict()["state"]=="released_not_started"
    assert store.path.read_bytes()==before
    with pytest.raises(StoreReadOnly): release(reader,record)
    with pytest.raises(StoreNotFound): reader.get_create_resolution("f"*64)


@pytest.mark.parametrize("first", ["create","level"])
def test_cross_create_level_uuid_guard_remains_on_schema7_even_after_release(tmp_path,first):
    from kir.tests.test_project_realization_store import stored_case
    store,_,level_record,_,_,_=stored_case(tmp_path/"project.sqlite",schema=CREATE_RESOLUTION_STORE_SCHEMA)
    binding=level_record.binding_dict()
    created=archive(store.head(),operation=binding["operation_id"],target=RuntimeTarget(**binding["target"]),
                    document=binding["precondition"]["document_key"])
    if first=="create":
        store.reserve_create_publication(created,expected_revision=store.head().revision_id)
        release(store,created)
        with pytest.raises(StoreConflict,match="operation identity"):
            store.reserve_level_update(level_record,expected_checkpoint=None)
    else:
        store.reserve_level_update(level_record,expected_checkpoint=None)
        with pytest.raises(StoreConflict,match="operation identity"):
            store.reserve_create_publication(created,expected_revision=store.head().revision_id)


def test_schema7_keeps_existing_task_writer_and_history_audit(tmp_path):
    from kir.project_tasks import create_task,checkpoint_task,read_task
    from kir.project_merge import ProposalScope
    store,source,record=setup(tmp_path)
    task=create_task(store,task_id="t",base_revision=source.revision_id,actor="worker",objective="Retain workflow",
        scope=ProposalScope(instances=("section",)))["task"]
    checkpoint_task(store,"t",request_id="checkpoint",expected_version=task["version"],generation=0,actor="worker",notes={"saved":True})
    release(store,record)
    assert read_task(store,"t")["checkpoint"]["notes"]=={"saved":True}
    assert store.history()==(source,)


def test_upgrade_before_commit_failure_preserves_schema6_file(tmp_path,monkeypatch):
    store,source,_=setup(tmp_path,CREATE_STORE_SCHEMA)
    before=rows(store)
    def fail(connection): raise RuntimeError("migration precommit")
    with monkeypatch.context() as patch:
        patch.setattr(storage,"_commit",fail)
        with pytest.raises(RuntimeError): store.upgrade_schema(CREATE_RESOLUTION_STORE_SCHEMA,expected_revision=source.revision_id)
    assert store.schema==CREATE_STORE_SCHEMA and rows(store)==before


def test_resolution_rejects_rehashed_non_no_start_receipt(tmp_path):
    from kir.project import _canonical,_hash
    store,_,record=setup(tmp_path)
    bound=evidence(record)
    release(store,record,bound)
    data=bound.to_dict()
    native=data["native_receipt"]
    native.update(state="invocation_completed",started=True,may_retry=False,result_json='{"ok":true}',
                  transaction_evidence="changes_not_observed",changes={"added":[],"modified":[],"deleted":[],"transaction_names":[],"truncated":False})
    data["receipt_digest"]=_hash({"archive_digest":record.digest,"native_receipt":native})
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE create_receipts SET receipt_digest=?,payload=?",(data["receipt_digest"],_canonical(data)))
        connection.execute("UPDATE create_resolutions SET receipt_digest=?",(data["receipt_digest"],))
    with pytest.raises(StoreCorrupt,match="no-start evidence"):
        store.get_create_resolution(record.digest)


def test_different_valid_no_start_receipt_cannot_replace_existing_resolution(tmp_path):
    store,_,record=setup(tmp_path)
    release(store,record,evidence(record,"cancelled_before_start"))
    before=rows(store)
    with pytest.raises(StoreConflict): release(store,record,evidence(record,"context_changed_before_start"))
    assert rows(store)==before
