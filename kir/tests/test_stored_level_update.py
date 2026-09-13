"""Real stored/compiler/receipt lifecycle; ONLY native transport is simulated.

The tiny physical selection deliberately excludes a preserved concept. These
are not live Revit results or a whole-building preservation/engineering proof.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from kir import revit_level_update, revit_observation, revit_transport, standalone_publish
from kir import stored_level_update as workflow
from kir.geometry_materialization import materialize_selection
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.project_selection import select_project_instances
from kir.project_store import (ProjectStore, CREATE_RESOLUTION_STORE_SCHEMA, STAGED_CREATE_STORE_SCHEMA,
                               StoreConflict, StoreCommitUnknown)
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.revit_discovery import load_discovery
from kir.revit_transport import ConnectorTransportError
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_revit_observation import row as observation_row, identity, unavailable
from kir.tests.test_revit_transport import ready_response
from kir.viewer.tests.test_live_scene_mesh import _VAULT


TARGET = ("section", "upper-level")
PROTECTED = (("protected", "body"),)
CONCEPT = ("section-concept", "body")


def source_project():
    level_id = output_id("stored-level", *TARGET)
    return ProjectRevision("stored-level", [ModuleDefinition("explicit", "explicit")], [
        ModuleInstance("section", "explicit", {
            "upper-level": {"op": "create_level", "elev_mm": 3000.0, "name": "Upper"},
            "wall": {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [5000, 0],
                     "height_mm": 3200, "level": {"by": "ref", "value": level_id}}}),
        ModuleInstance("protected", "explicit", {"body": {
            "op": "create_directshape", "category": "mass", "mesh": _VAULT, "name": "Protected"}}),
        ModuleInstance("section-concept", "explicit", {"body": {
            "op": "create_directshape", "category": "mass", "mesh": _VAULT, "name": "Preserved concept"}},
            metadata={"role": "preserved_conceptual_source", "native_execution": "not_run"}),
    ])


def advertisement(credentials):
    return load_discovery(json.dumps({"protocol": "kir-revit-connector/4", "target": credentials.target.to_dict(),
        "session_id": credentials.session_id, "token": credentials.token, "pipe_name": "synthetic-not-connected",
        "process_id": 1, "expires_utc": "2099-01-01T00:00:00.0000000Z"}).encode())


class NativeFixture:
    def __init__(self, monkeypatch, year, store, *, fault=None):
        self.credentials = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), year),
                                              str(uuid4()), "synthetic-credential")
        self.ad = advertisement(self.credentials)
        self.store = store
        self.fault = fault
        self.revision = 8
        self.prepared = {}
        self.receipts = {}
        self.values = {}
        self.events = []
        self.create_sends = self.setter_sends = self.query_sends = 0
        self.original_operation_id = None
        self.before_send = None
        self.saw_pending_before_setter = False
        for module, name in ((standalone_publish, "prepare_execution"),
                             (revit_observation, "prepare_element_observation"),
                             (revit_level_update, "prepare_level_update")):
            actual = getattr(module, name)
            def remember(*args, _actual=actual, **kwargs):
                prepared = _actual(*args, **kwargs)
                self.prepared[prepared.operation_id] = prepared
                return prepared
            monkeypatch.setattr(module, name, remember)
        for module in (standalone_publish, revit_transport, workflow):
            monkeypatch.setattr(module, "exchange", self.exchange)

    def _answer(self, request, *, receipt=None, context=None, status="receipt"):
        return {"protocol": "kir-revit-connector/4", "request_id": request["request_id"],
            "target": self.credentials.target.to_dict(), "session_id": self.credentials.session_id,
            "ok": True, "status": status, "error": None, "context": context, "receipt": receipt}

    def _response(self, prepared, payload, *, added=(), modified=()):
        return response_for(prepared, self.credentials, payload, changes={"added": list(added),
            "modified": list(modified), "deleted": [], "transaction_names": ["synthetic"] if added or modified else [],
            "truncated": False})["receipt"]

    def exchange(self, ad, wire, **kwargs):
        request = json.loads(wire)
        self.events.append(request)
        kind = request["kind"]
        if kind == "ping":
            if self.before_send is not None:
                callback, self.before_send = self.before_send, None
                callback()
            return json.dumps(ready_response(request)).encode()
        if kind == "context":
            answer = self._answer(request, status="context", context={"has_document": True,
                "document_key": "native-doc", "document_title": "Not identity",
                "revit_version": self.credentials.target.revit_version, "revision": self.revision,
                "active_view_id": 42, "selection_digest": hashlib.sha256(b"").hexdigest(), "selection_count": 0,
                "is_family_document": False, "is_read_only": False, "is_modifiable": False, "complete": True})
        elif kind == "receipt":
            if self.fault == "unknown_receipt":
                answer = self._answer(request, status="not_found")
                answer.update(ok=False, error="synthetic unavailable")
            else:
                answer = self._answer(request, receipt=deepcopy(self.receipts[request["operation_id"]]))
        else:
            assert kind == "execute"
            prepared = self.prepared[request["operation_id"]]
            assert request["source"] == prepared.source and request["source_sha256"] == prepared.source_sha256
            operations = prepared.planned.to_ops()
            if prepared.planned.family.value == "query":
                self.query_sends += 1
                assert all(op["op"] == "query_element_state" for op in operations)
                assert "new Transaction(" not in prepared.source
                if self.setter_sends and self.fault == "after_lost":
                    raise ConnectorTransportError("synthetic_after_lost", "response", delivery="unknown")
                values = {op["id"]: deepcopy(self.values[op["unique_id"]]) for op in operations}
                if self.setter_sends and self.fault == "after_mismatch":
                    level = next(value["level"] for value in values.values() if value["is_level"])
                    level["project_elevation_mm"] = 999.0
                answer = self._answer(request, receipt=self._response(prepared, values))
            elif all(op["op"].startswith("create_") for op in operations):
                self.create_sends += 1
                self.original_operation_id = prepared.operation_id
                payload = {"ok": True}
                for index, op in enumerate(operations):
                    number, uid = 700 + index, "uid-" + op["id"]
                    native = {"id": str(number), **identity(number, uid)}
                    if self.fault == "missing_identity" and op["op"] == "create_level":
                        native.update(unavailable())
                    payload[op["id"]] = native
                    value = observation_row(uid, is_level=op["op"] == "create_level")
                    value.update(identity(number, uid))
                    if op["op"] != "create_level":
                        value["type_state"] = {"status": "none", **unavailable()}
                    self.values[uid] = value
                receipt = self._response(prepared, payload, added=range(700, 700 + len(operations)))
                self.receipts[prepared.operation_id] = receipt
                self.revision += 1
                if self.fault == "create_reply_lost":
                    self.fault = None
                    raise ConnectorTransportError("synthetic_create_reply_lost", "response", delivery="unknown")
                answer = self._answer(request, receipt=receipt)
            else:
                assert len(operations) == 1 and operations[0]["op"] == "set_param"
                self.setter_sends += 1
                op = operations[0]
                # Native send cannot precede durable reservation: inspect a new
                # store handle, not a boolean injected into the publisher.
                status = ProjectStore.open(self.store.path).status()
                pending = [row for row in status["native"]["streams"] if row["pending"]]
                assert len(pending) == 1
                retained = ProjectStore.open(self.store.path).get_level_update_archive(pending[0]["pending"]["archive_digest"])
                assert retained.binding_dict()["operation_id"] == prepared.operation_id
                self.saw_pending_before_setter = True
                value = next(row for row in self.values.values()
                             if row["element_identity"]["element_id"] == op["target"]["value"])
                payload = {"ok": True, op["id"]: {"id": str(op["target"]["value"]), "param": op["param"], "value": "display"}}
                receipt = self._response(prepared, payload, modified=[op["target"]["value"]])
                if self.fault == "stale_document":
                    self.revision += 1
                if request["precondition"]["revision"] != self.revision:
                    receipt.update(state="context_changed_before_start", started=False, may_retry=True,
                        transaction_evidence="not_observed", changes=None, result_json=None,
                        result_error=None, result_truncated=False, error="synthetic revision race")
                else:
                    level = value["level"]
                    elevation = op["value"]["v"]
                    level.update(project_elevation_mm=elevation, reported_elevation_mm=elevation)
                    level["elevation_parameter"]["value_internal_feet"] = elevation / 304.8
                    value["element_identity"]["version_guid"] = "b" * 32
                    self.revision += 1
                self.receipts[prepared.operation_id] = receipt
                if self.fault == "setter_reply_lost":
                    self.fault = None
                    raise ConnectorTransportError("synthetic_setter_reply_lost", "response", delivery="unknown")
                answer = self._answer(request, receipt=receipt)
        return json.dumps(answer).encode()


def setup(tmp_path, monkeypatch, *, year="2026", fault=None):
    source = source_project()
    store = ProjectStore.create(tmp_path / "project.sqlite", source, schema=CREATE_RESOLUTION_STORE_SCHEMA)
    native = NativeFixture(monkeypatch, year, store, fault=fault)
    choice = select_project_instances(source, instance_keys=("section", "protected"))
    selected = materialize_selection(source, choice, {})
    creation_id = str(uuid4())
    try:
        first = standalone_publish.publish_stored_project(store, selected, expected_revision=source.revision_id,
            advertisement=native.ad, client_path=sys.executable, expected_document_key="native-doc",
            operation_id=creation_id, bind_view=True, bind_selection=True)
        create_archive = first.record.digest
        assert first.execution_contract_satisfied
    except ConnectorTransportError:
        assert fault == "create_reply_lost"
        store = ProjectStore.open(store.path, readonly=False)
        create_archive = store.find_create_publication(journal_id=native.credentials.target.journal_id,
                                                       operation_id=creation_id).archive_digest
    section = source.instances[0]
    proposed = source.replace_instance(replace(section, outputs=tuple(
        replace(output, operation={**dict(output.operation), "elev_mm": 3800.0}) if output.key == TARGET[1]
        else output for output in section.outputs)), expected_revision=source.revision_id)
    store.commit(proposed, expected_revision=source.revision_id)
    kwargs = dict(create_archive_digest=create_archive, proposed_revision_id=proposed.revision_id,
        expected_head=proposed.revision_id, target=TARGET, protected_outputs=PROTECTED,
        advertisement=native.ad, client_path=sys.executable, archive_path=tmp_path / "update.sqlite",
        operation_id=str(uuid4()), expected_target=native.credentials.target, expected_document_key="native-doc")
    return store, source, proposed, native, kwargs


def reconcile(store, result, native):
    return workflow.reconcile_stored_level_update(store, stream_id=result.stream_id,
        expected_pending_archive=result.update_archive_digest, advertisement=native.ad,
        client_path=sys.executable, expected_target=native.credentials.target, expected_document_key="native-doc")


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_selected_create_first_setter_and_settlement_use_real_store_and_codecs(tmp_path, monkeypatch, year):
    store, source, proposed, native, kwargs = setup(tmp_path, monkeypatch, year=year)
    result = workflow.publish_first_stored_level_update(store, **kwargs)
    assert result.stage == "settled", result.to_dict()
    assert result.mutation_execution == "committed" and result.scope_satisfied
    assert result.storage_acknowledgement == "recorded" and not result.may_retry
    assert native.create_sends == native.setter_sends == 1 and native.query_sends == 2
    assert native.saw_pending_before_setter
    excluded_id = output_id(source.project_id, *CONCEPT)
    created = store.get_create_publication(kwargs["create_archive_digest"])
    assert excluded_id not in created.output_ids and "uid-" + excluded_id not in native.values
    assert len(created.output_ids) == 3 and len(source.addressed_outputs()) == 4
    assert store.head().dumps() == proposed.dumps()
    assert source.instances[-1].to_dict() == store.head().instances[-1].to_dict()
    assert store.level_baseline(result.stream_id).checkpoint_digest == result.settlement_digest
    sent = native.setter_sends
    again = reconcile(ProjectStore.open(store.path, readonly=False), result, native)
    assert again.stage == "already_settled" and not again.scope_satisfied
    assert again.storage_acknowledgement == "already_recorded" and native.setter_sends == sent


@pytest.mark.parametrize("fault", ["create_reply_lost", "setter_reply_lost"])
def test_reopen_after_lost_reply_never_resends_a_model_mutation(tmp_path, monkeypatch, fault):
    store, _, _, native, kwargs = setup(tmp_path, monkeypatch, fault=fault)
    result = workflow.publish_first_stored_level_update(store, **kwargs)
    if fault == "setter_reply_lost":
        assert result.stage == "publication" and result.mutation_execution == "unconfirmed", result.to_dict()
        assert result.update_archive_digest
        assert store.level_baseline(result.stream_id).pending_archive_digest == result.update_archive_digest
        before = native.create_sends, native.setter_sends
        # A new Python-facing handle uses only retained input; no re-preparation.
        monkeypatch.setattr(revit_level_update, "prepare_level_update", lambda *_a, **_kw: pytest.fail("mutation recompiled"))
        result = reconcile(ProjectStore.open(store.path, readonly=False), result, native)
        assert (native.create_sends, native.setter_sends) == before
    assert result.stage == "settled", result.to_dict()
    assert native.create_sends == native.setter_sends == 1


@pytest.mark.parametrize("fault,stage", [("missing_identity", "create_lookup"),
    ("after_lost", "after_readback"), ("after_mismatch", "field_qualification"), ("stale_document", "mutation_receipt")])
def test_evidence_failure_never_settles_or_grants_retry(tmp_path, monkeypatch, fault, stage):
    store, _, _, native, kwargs = setup(tmp_path, monkeypatch, fault=fault)
    result = workflow.publish_first_stored_level_update(store, **kwargs)
    assert result.stage == stage, result.to_dict()
    assert not result.scope_satisfied and not result.may_retry and result.settlement_digest is None
    if fault == "missing_identity":
        assert result.diagnostic_code == "required_created_identity_unavailable" and native.setter_sends == 0
    else:
        baseline = store.level_baseline(result.stream_id)
        assert baseline.pending_archive_digest == result.update_archive_digest and baseline.checkpoint_digest is None
        assert result.mutation_execution == ("not_started" if fault == "stale_document" else "committed")


@pytest.mark.parametrize("fault", ["wrong_document", "wrong_runtime", "stale_head", "not_direct_child", "unpublished_scope"])
def test_initial_scope_refusals_make_no_extra_native_request(tmp_path, monkeypatch, fault):
    store, _, proposed, native, kwargs = setup(tmp_path, monkeypatch)
    if fault == "wrong_document": kwargs["expected_document_key"] = "different-document"
    elif fault == "wrong_runtime": kwargs["expected_target"] = RuntimeTarget(str(uuid4()), str(uuid4()), "2026")
    elif fault in ("stale_head", "not_direct_child"):
        later = proposed.revise(expected_revision=proposed.revision_id, metadata={"later": True})
        store.commit(later, expected_revision=proposed.revision_id)
        if fault == "not_direct_child": kwargs.update(expected_head=later.revision_id, proposed_revision_id=later.revision_id)
    else: kwargs["protected_outputs"] = (CONCEPT,)
    before = len(native.events)
    with pytest.raises(workflow.StoredLevelUpdateError):
        workflow.publish_first_stored_level_update(store, **kwargs)
    assert len(native.events) == before and native.setter_sends == 0


def test_authoring_race_after_plan_is_checked_in_reservation_transaction(tmp_path, monkeypatch):
    store, _, proposed, native, kwargs = setup(tmp_path, monkeypatch)
    def move_head():
        latest = proposed.revise(expected_revision=proposed.revision_id, metadata={"parallel": True})
        ProjectStore.open(store.path, readonly=False).commit(latest, expected_revision=proposed.revision_id)
    native.before_send = move_head
    result = workflow.publish_first_stored_level_update(store, **kwargs)
    assert result.stage == "publication" and result.diagnostic_code == "store_conflict", result.to_dict()
    assert native.setter_sends == 0
    assert store.status()["native"]["streams"] == []


@pytest.mark.parametrize("fault", ["before_commit", "lost_ack", "generic_after_commit"])
def test_settlement_storage_failure_preserves_committed_native_fact(tmp_path, monkeypatch, fault):
    store, _, _, native, kwargs = setup(tmp_path, monkeypatch)
    actual = ProjectStore.commit_level_settlement
    def fail(self, *args, **kw):
        if fault != "before_commit":
            actual(self, *args, **kw)
            if fault == "generic_after_commit":
                raise RuntimeError("synthetic unexpected error after commit")
            raise StoreCommitUnknown("synthetic settlement ACK loss")
        raise StoreConflict("synthetic local failure")
    with monkeypatch.context() as scoped:
        scoped.setattr(ProjectStore, "commit_level_settlement", fail)
        result = workflow.publish_first_stored_level_update(store, **kwargs)
    assert result.stage == "settlement" and result.mutation_execution == "committed" and result.scope_satisfied
    assert result.storage_acknowledgement == ("failed" if fault == "before_commit" else "unknown")
    assert not result.may_retry
    again = reconcile(ProjectStore.open(store.path, readonly=False), result, native)
    assert again.stage == ("settled" if fault == "before_commit" else "already_settled"), again.to_dict()
    assert native.setter_sends == 1


def test_reconciliation_unknown_receipt_keeps_pending_without_query_or_setter(tmp_path, monkeypatch):
    store, _, _, native, kwargs = setup(tmp_path, monkeypatch, fault="setter_reply_lost")
    original = workflow.publish_first_stored_level_update(store, **kwargs)
    native.fault = "unknown_receipt"
    before = native.setter_sends, native.query_sends
    result = reconcile(ProjectStore.open(store.path, readonly=False), original, native)
    assert result.mutation_execution == "unconfirmed" and not result.scope_satisfied
    assert (native.setter_sends, native.query_sends) == before
    assert store.level_baseline(result.stream_id).pending_archive_digest == original.update_archive_digest


def _restart_reconcile(project_path, native_path, stream_id, archive_digest):
    """Child-only fake native journal: no parent Python objects are reachable."""
    state = json.loads(Path(native_path).read_text())
    store = ProjectStore.open(project_path, readonly=False)
    with pytest.MonkeyPatch.context() as patched:
        native = NativeFixture(patched, state["credentials"]["target"]["revit_version"], store)
        native.credentials = SessionCredentials(RuntimeTarget(**state["credentials"]["target"]),
            state["credentials"]["session_id"], "synthetic-credential")
        native.ad = advertisement(native.credentials)
        native.receipts, native.values, native.revision = state["receipts"], state["values"], state["revision"]
        patched.setattr(revit_level_update, "prepare_level_update", lambda *_a, **_kw: pytest.fail("setter prepared after restart"))
        result = workflow.reconcile_stored_level_update(store, stream_id=stream_id,
            expected_pending_archive=archive_digest, advertisement=native.ad, client_path=sys.executable,
            expected_target=native.credentials.target, expected_document_key="native-doc")
        print(json.dumps({"pid": os.getpid(), "result": result.to_dict(),
            "create_sends": native.create_sends, "setter_sends": native.setter_sends, "query_sends": native.query_sends}))


def test_actual_new_python_process_reconciles_lost_setter_response(tmp_path, monkeypatch):
    store, _, _, native, kwargs = setup(tmp_path, monkeypatch, fault="setter_reply_lost")
    pending = workflow.publish_first_stored_level_update(store, **kwargs)
    assert pending.mutation_execution == "unconfirmed" and pending.update_archive_digest
    native_path = tmp_path / "synthetic-native-journal.json"
    native_path.write_text(json.dumps({"credentials": {"target": native.credentials.target.to_dict(),
        "session_id": native.credentials.session_id}, "receipts": native.receipts,
        "values": native.values, "revision": native.revision}), encoding="utf-8")
    child = subprocess.run([sys.executable, "-c",
        "import sys; from kir.tests.test_stored_level_update import _restart_reconcile; _restart_reconcile(*sys.argv[1:])",
        str(store.path), str(native_path), pending.stream_id, pending.update_archive_digest],
        capture_output=True, text=True, timeout=40, cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert child.returncode == 0, child.stderr[-3000:]
    evidence = json.loads(child.stdout)
    assert evidence["pid"] != os.getpid()
    assert evidence["result"]["stage"] == "settled", evidence
    assert evidence["create_sends"] == evidence["setter_sends"] == 0 and evidence["query_sends"] == 1
    assert ProjectStore.open(store.path).level_baseline(pending.stream_id).checkpoint_digest == evidence["result"]["settlement_digest"]
    assert native.create_sends == native.setter_sends == 1


def test_exception_class_name_is_bounded_json_without_arbitrary_formatting(tmp_path, monkeypatch):
    store, _, _, native, kwargs = setup(tmp_path, monkeypatch)
    def unsafe(_self):
        raise AssertionError("exception formatter must not be invoked")
    broken = type("Unusual" + "Ошибка" * 200, (RuntimeError,), {"__str__": unsafe})
    actual = ProjectStore.commit_level_settlement
    def lost(self, *args, **kw):
        actual(self, *args, **kw)
        raise broken("\ud800")
    monkeypatch.setattr(ProjectStore, "commit_level_settlement", lost)
    result = workflow.publish_first_stored_level_update(store, **kwargs)
    assert result.mutation_execution == "committed" and result.storage_acknowledgement == "unknown"
    assert len(result.error_type) < 130
    json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False).encode("utf-8")


def test_selected_original_source_cannot_be_replaced_by_changed_full_metadata(tmp_path, monkeypatch):
    store, source, _, native, kwargs = setup(tmp_path, monkeypatch)
    record = store.get_create_publication(kwargs["create_archive_digest"]).record
    different = source.revise(expected_revision=source.revision_id, metadata={"foreign_source": True})
    with pytest.raises(revit_level_update.LevelUpdateRefusal, match="source_project_mismatch"):
        revit_level_update.bind_original_publication(different, record, "{}", required_outputs=(TARGET, *PROTECTED),
            credentials=native.credentials, request_id=str(uuid4()))


def test_staged_submission_is_refused_before_native_lookup(tmp_path, monkeypatch):
    from kir.tests.test_staged_create_projection import case, project
    from kir.staged_create_projection import prepare_staged_create
    from kir.staged_submission import bind_staged_project_submission
    from kir.saved_execution import SavedExecutionRecord
    value = case()
    source = value["project"]
    store = ProjectStore.create(tmp_path / "staged.sqlite", source, schema=STAGED_CREATE_STORE_SCHEMA)
    store.reserve_create_publication(value["archive"], expected_revision=source.revision_id)
    store.record_create_receipt(value["bound"])
    projection = project(value)
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    submission = bind_staged_project_submission(projection, prepared)
    staged = SavedExecutionRecord.capture_project(prepared, submission)
    store.reserve_create_publication(staged, expected_revision=source.revision_id, submission=submission)
    monkeypatch.setattr(workflow, "recover_stored_create", lambda *_a, **_kw: pytest.fail("/3 performed lookup"))
    with pytest.raises(workflow.StoredLevelUpdateError, match="flat_create_submission_required"):
        workflow.publish_first_stored_level_update(store, create_archive_digest=staged.digest,
            proposed_revision_id=source.revision_id, expected_head=source.revision_id,
            target=("B", "wall"), protected_outputs=(), advertisement=advertisement(value["credentials"]),
            client_path=sys.executable, archive_path=tmp_path / "not-created.sqlite", operation_id=str(uuid4()),
            expected_target=prepared.target, expected_document_key="native-doc")
    with pytest.raises(revit_level_update.LevelUpdateRefusal, match="original_profile_unsupported"):
        revit_level_update.bind_original_publication(source, staged, "{}", required_outputs=(("B", "wall"),),
            credentials=value["credentials"], request_id=str(uuid4()))
