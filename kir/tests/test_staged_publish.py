"""Stored A -> B -> C through real factories; only native transport is synthetic.

These tests do not execute Revit or establish geometry/engineering acceptance.
Preparation spies delegate to the real compiler; native answers are explicit
fixture data passed through the real Connector and observation codecs.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import sqlite3
import sys
from uuid import uuid4

import pytest

from kir import staged_publish as publishing, standalone_publish, revit_connector
from kir.connector_result import assess_connector_context_response
from kir.create_publication import bind_create_receipt, CreatePublicationError
from kir.element_query import TYPE_DEFINITION_STATE_SCHEMA
from kir.geometry_materialization import materialize_selection
from kir.project import ModuleInstance, ProjectRevision, output_id
from kir.project_execution_partition import partition_project_execution
from kir.project_selection import select_project_instances
from kir.project_store import ProjectStore, STAGED_CREATE_STORE_SCHEMA, StoreConflict
from kir.revit_connector import (ConnectorPreparationError, RuntimeTarget, SessionCredentials,
                                 MAX_SOURCE_CHARS)
from kir.revit_transport import ConnectorTransportError
from kir.staged_create_projection import bind_staged_create_projection
from kir.staged_submission import STAGED_SUBMISSION_SCHEMA
from kir.standalone_publish import PublicationRefusal
from kir.tests.test_project_execution_partition import shared_project
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_revit_observation import row as observation_row, identity, unavailable
from kir.tests.test_revit_transport import ready_response
from kir.tests.test_stored_level_update import advertisement
from kir.type_definition_observation import (prepare_type_definition_observation,
                                             parse_type_definition_observation)
from kir.viewer.tests.test_live_scene_mesh import _VAULT


def source_project(*, walls_in_b=1):
    source = shared_project()
    body = dict(source.instances[-1].outputs[0].operation)
    instances = [*source.instances[:-1], ModuleInstance("B", "m", {
        f"body-{index}": {**body, "p0_mm": [index % 100 * 6000, 5000 + index // 100 * 6000],
                         "p1_mm": [index % 100 * 6000 + 5000, 5000 + index // 100 * 6000]}
        for index in range(walls_in_b)}),
        ModuleInstance("C", "m", {"body": {**body, "p0_mm": [0, 10000], "p1_mm": [5000, 10000]}}),
        ModuleInstance("preserved-concept", "m", {"body": {"op": "create_directshape",
            "category": "mass", "name": "Preserved concept", "mesh": _VAULT}},
            metadata={"role": "preserved_conceptual_source", "native_execution": "not_run"})]
    return ProjectRevision(source.project_id, source.modules, instances)


def materialize(source, instance):
    return materialize_selection(source, select_project_instances(source, instance_keys=(instance,)), {})


class Native:
    """Synthetic Connector boundary, not a fake compiler or store."""
    def __init__(self, monkeypatch, store, year):
        self.store = store
        self.credentials = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), year),
                                              str(uuid4()), "synthetic-not-sent-to-revit")
        self.ad = advertisement(self.credentials)
        self.revision, self.document = 8, "native-doc"
        self.prepared, self.receipts, self.values = {}, {}, {}
        self.requests, self.written_ops = [], []
        self.loss_operation = None
        self.unknown_receipt = False
        self.on_ping = None
        for owner, name in ((standalone_publish, "prepare_execution"), (publishing, "prepare_staged_create")):
            actual = getattr(owner, name)
            def remember(*args, _actual=actual, **kwargs):
                prepared = _actual(*args, **kwargs)
                self.prepared[prepared.operation_id] = prepared
                return prepared
            monkeypatch.setattr(owner, name, remember)
        # The one send lives in standalone_publish._reserve_and_send for every input variant.
        monkeypatch.setattr(standalone_publish, "exchange", self.exchange)

    @property
    def writes(self):
        return [request for request in self.requests if request["kind"] == "execute"
                and self.prepared[request["operation_id"]].planned.family.value == "write"]

    def envelope(self, request, *, receipt=None, context=None, status="receipt"):
        return {"protocol": "kir-revit-connector/4", "request_id": request["request_id"],
            "target": self.credentials.target.to_dict(), "session_id": self.credentials.session_id,
            "ok": True, "status": status, "error": None, "context": context, "receipt": receipt}

    def observed(self, op, number, uid):
        is_level = op["op"] == "create_level"
        row = observation_row(uid, is_level=is_level)
        row.update(identity(number, uid), schema_version=TYPE_DEFINITION_STATE_SCHEMA)
        row["name"] = op.get("new_name", op.get("name", "Synthetic created element"))
        if is_level:
            elevation = op["elev_mm"]
            row["level"].update(project_elevation_mm=elevation, reported_elevation_mm=elevation)
            row["level"]["elevation_parameter"]["value_internal_feet"] = elevation / 304.8
        else:
            row["type_state"] = {"status": "none", **unavailable()}
        if op["op"] == "create_wall_type":
            row["type_definition"] = {"status": "observed", "reason": None, "value": {
                "host_kind": op.get("host_kind", "wall"), "wall_kind": "Basic",
                "is_vertically_compound": False, "is_vertically_homogeneous": True,
                "name": op["new_name"], "total_width_mm": 200,
                "layers": [{"width_mm": 200, "function": "Structure", "material_id": -1,
                    "material_name": None, "material_identity": None, "material_name_match_count": None}]}}
        else:
            row["type_definition"] = {"status": "not_applicable",
                "reason": "unsupported_element_kind", "value": None}
        return row

    def exchange(self, advertisement, wire, **_kwargs):
        request = json.loads(wire)
        assert advertisement.credentials == self.credentials
        self.requests.append(request)
        kind = request["kind"]
        if kind == "ping":
            if self.on_ping:
                callback, self.on_ping = self.on_ping, None
                callback()
            return json.dumps(ready_response(request)).encode()
        if kind == "context":
            answer = self.envelope(request, status="context", context={"has_document": True,
                "document_key": self.document, "document_title": "Not an identity",
                "revit_version": self.credentials.target.revit_version, "revision": self.revision,
                "active_view_id": 42, "selection_digest": hashlib.sha256(b"").hexdigest(), "selection_count": 0,
                "is_family_document": False, "is_read_only": False, "is_modifiable": False, "complete": True})
        elif kind == "receipt":
            if self.unknown_receipt:
                answer = self.envelope(request, status="not_found")
                answer.update(ok=False, error="synthetic unavailable")
            else:
                answer = self.envelope(request, receipt=deepcopy(self.receipts[request["operation_id"]]))
        else:
            assert kind == "execute"
            prepared = self.prepared[request["operation_id"]]
            assert request["source"] == prepared.source
            assert request["source_sha256"] == prepared.source_sha256
            assert request["precondition"] == prepared.precondition.to_dict()
            ops = prepared.planned.to_ops()
            added = []
            if prepared.planned.family.value == "write":
                # Reopen the actual database before any synthetic native effect.
                retained = ProjectStore.open(self.store.path).find_create_publication(
                    journal_id=self.credentials.target.journal_id, operation_id=prepared.operation_id)
                assert retained.record.to_dict()["source"] == request["source"]
                assert tuple(op["id"] for op in ops) == retained.output_ids
                payload = {"ok": True}
                stale = (request["precondition"]["revision"] != self.revision
                         or request["precondition"]["document_key"] != self.document)
                if not stale:
                    for op in ops:
                        assert op["op"].startswith("create_")
                        uid = "uid-" + op["id"]
                        assert uid not in self.values, "duplicate native CREATE"
                        number = 700 + len(self.values)
                        payload[op["id"]] = {"id": str(number), **identity(number, uid)}
                        if op["op"] == "create_wall_type": payload[op["id"]]["duplicated"] = True
                        self.values[uid] = self.observed(op, number, uid)
                        self.written_ops.append(deepcopy(op))
                        added.append(number)
                    self.revision += 1
            else:
                assert all(op["op"] == "query_element_state" and op["include_type_definition"] is True for op in ops)
                assert "new Transaction(" not in prepared.source
                stale = False
                payload = {op["id"]: deepcopy(self.values[op["unique_id"]]) for op in ops}
            receipt = response_for(prepared, self.credentials, payload, changes={"added": added,
                "modified": [], "deleted": [], "transaction_names": ["Synthetic"] if added else [],
                "truncated": False})["receipt"]
            if stale:
                receipt.update(state="context_changed_before_start", started=False, may_retry=True,
                    transaction_evidence="not_observed", changes=None, result_json=None,
                    result_error=None, result_truncated=False, error="synthetic context changed")
            self.receipts[prepared.operation_id] = receipt
            if request["operation_id"] == self.loss_operation:
                self.loss_operation = None
                raise ConnectorTransportError("synthetic_lost_reply", "response", delivery="unknown")
            answer = self.envelope(request, receipt=receipt)
        return json.dumps(answer, allow_nan=False).encode()

    def read_imports(self, uids):
        request_id = str(uuid4())
        request = self.credentials.context_request(request_id=request_id)
        response = self.exchange(self.ad, standalone_publish._wire(request))
        context = assess_connector_context_response(response, credentials=self.credentials, request_id=request_id)
        condition = context.require_precondition(bind_view=True, bind_selection=True)
        query = prepare_type_definition_observation(uids, target=self.credentials.target,
            precondition=condition, operation_id=str(uuid4()))
        self.prepared[query.operation_id] = query
        request_id = str(uuid4())
        response = self.exchange(self.ad, standalone_publish._wire(query.execute_request(
            self.credentials, request_id=request_id)))
        return parse_type_definition_observation(query, response, credentials=self.credentials, request_id=request_id)


def bootstrap(tmp_path, monkeypatch, *, year="2026", walls_in_b=1):
    source = source_project(walls_in_b=walls_in_b)
    store = ProjectStore.create(tmp_path / "project.sqlite", source, schema=STAGED_CREATE_STORE_SCHEMA)
    native = Native(monkeypatch, store, year)
    first = standalone_publish.publish_stored_project(store, materialize(source, "A"),
        expected_revision=source.revision_id, advertisement=native.ad, client_path=sys.executable,
        expected_document_key="native-doc", operation_id=str(uuid4()), bind_view=True, bind_selection=True)
    assert first.execution_contract_satisfied and first.retained_receipt_digest
    return source, store, native, first


def projection(source, native, original, instance="B", *, evidence=None, observation=None):
    evidence = evidence if evidence is not None else bind_create_receipt(original.record,
        original.result.raw_response, credentials=native.credentials, request_id=original.request_id)
    imports = [output_id(source.project_id, "shared", key) for key in ("level", "type")]
    observed = observation if observation is not None else native.read_imports(["uid-" + oid for oid in imports])
    partition = partition_project_execution(source, materialize(source, instance), import_output_ids=imports)
    return bind_staged_create_projection(partition,
        import_sources={oid: (source, original.record, evidence) for oid in imports}, observation=observed)


def publish(store, source, native, stage, **kwargs):
    options = {"expected_revision": source.revision_id, "advertisement": native.ad,
        "client_path": sys.executable, "expected_document_key": "native-doc", "operation_id": str(uuid4())}
    options.update(kwargs)
    return publishing.publish_staged_project(store, stage, **options)


def recover(store, native, operation_id):
    retained = store.find_create_publication(journal_id=native.credentials.target.journal_id,
                                             operation_id=operation_id)
    return standalone_publish.recover_stored_create(store, retained.archive_digest,
        advertisement=native.ad, client_path=sys.executable)


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_A_then_B_then_C_keeps_shared_identity_and_unpublished_concept(tmp_path, monkeypatch, year):
    source, store, native, first = bootstrap(tmp_path, monkeypatch, year=year)
    original = source.dumps()
    attempts = [first]
    for name in ("B", "C"):
        stage = projection(source, native, first, name)
        before = len(native.requests)
        attempt = publish(store, source, native, stage)
        attempts.append(attempt)
        assert [r["kind"] for r in native.requests[before:]] == ["ping", "execute"]
        assert attempt.prepared.precondition is stage.precondition
        assert attempt.prepared.expected_identities == stage.expected_identities
        assert all(proof.unique_id in attempt.prepared.source for proof in stage.expected_identities)
        assert attempt.record.project_submission["schema"] == STAGED_SUBMISSION_SCHEMA
        assert attempt.execution_contract_satisfied and attempt.retained_receipt_digest
        assert not attempt.intent_verified
        assert len(attempt.record.project_submission["outputs"]) == 1
        assert all(op["op"] == "create_wall" for op in attempt.prepared.planned.to_ops())
        assert len(attempt.prepared.source.encode("utf-16-le")) // 2 <= MAX_SOURCE_CHARS
    assert len(native.writes) == 3
    assert [op["op"] for op in native.written_ops].count("create_level") == 1
    assert [op["op"] for op in native.written_ops].count("create_wall_type") == 1
    assert len(native.values) == len(native.written_ops) == 5
    assert "uid-" + output_id(source.project_id, "preserved-concept", "body") not in native.values
    assert store.head().dumps() == original
    reopened = ProjectStore.open(store.path, readonly=False)
    for attempt in attempts:
        assert reopened.get_create_publication(attempt.record.digest).record._raw == attempt.record._raw
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM create_imports").fetchone()[0] == 4


def test_lost_reply_reopen_and_receipt_lookup_never_resend_B(tmp_path, monkeypatch):
    source, store, native, first = bootstrap(tmp_path, monkeypatch)
    stage = projection(source, native, first)
    operation_id = native.loss_operation = str(uuid4())
    with pytest.raises(ConnectorTransportError):
        publish(store, source, native, stage, operation_id=operation_id)
    assert len(native.writes) == 2
    reopened = ProjectStore.open(store.path, readonly=False)
    retained = reopened.find_create_publication(journal_id=native.credentials.target.journal_id,
                                                 operation_id=operation_id)
    assert reopened.get_create_receipts(retained.archive_digest).to_dict()["receipts"] == []
    native.unknown_receipt = True
    unknown = recover(reopened, native, operation_id)
    assert not unknown.execution_contract_satisfied and unknown.retained_receipt_digest is None
    with pytest.raises(PublicationRefusal, match="create_already_reserved"):
        publish(reopened, source, native, stage, operation_id=operation_id)
    with pytest.raises(StoreConflict):
        publish(reopened, source, native, stage)
    native.unknown_receipt = False
    with monkeypatch.context() as scoped:
        scoped.setattr(publishing, "prepare_staged_create", lambda *_a, **_kw: pytest.fail("recovery prepared a write"))
        recovered = recover(reopened, native, operation_id)
    assert recovered.execution_contract_satisfied and recovered.prepared is None
    assert recovered.retained_receipt_digest and len(native.writes) == 2
    # C is independently based on A's qualified shared imports, not on B's wall.
    later = publish(reopened, source, native, projection(source, native, first, "C"))
    assert later.execution_contract_satisfied and len(native.writes) == 3


@pytest.mark.parametrize("committed", [False, True])
def test_late_receipt_storage_failure_does_not_undo_or_repeat_native_create(tmp_path, monkeypatch, committed):
    source, store, native, first = bootstrap(tmp_path, monkeypatch)
    stage = projection(source, native, first)
    operation_id = str(uuid4())
    actual = ProjectStore.record_create_receipt
    def fail(self, evidence):
        if committed: actual(self, evidence)
        raise RuntimeError("synthetic receipt acknowledgement lost")
    with monkeypatch.context() as scoped:
        scoped.setattr(ProjectStore, "record_create_receipt", fail)
        with pytest.raises(RuntimeError, match="acknowledgement"):
            publish(store, source, native, stage, operation_id=operation_id)
    assert len(native.writes) == 2
    restored = recover(ProjectStore.open(store.path, readonly=False), native, operation_id)
    assert restored.execution_contract_satisfied and restored.retained_receipt_digest
    assert len(native.writes) == 2


def test_reservation_acknowledgement_loss_keeps_input_without_sending(tmp_path, monkeypatch):
    source, store, native, first = bootstrap(tmp_path, monkeypatch)
    stage = projection(source, native, first)
    operation_id = str(uuid4())
    actual = ProjectStore.reserve_create_publication
    def fail(self, *args, **kwargs):
        actual(self, *args, **kwargs)
        raise RuntimeError("synthetic reservation acknowledgement lost")
    with monkeypatch.context() as scoped:
        scoped.setattr(ProjectStore, "reserve_create_publication", fail)
        with pytest.raises(RuntimeError, match="acknowledgement"):
            publish(store, source, native, stage, operation_id=operation_id)
    assert len(native.writes) == 1
    with pytest.raises(PublicationRefusal, match="create_already_reserved"):
        publish(store, source, native, stage, operation_id=operation_id)
    assert len(native.writes) == 1


@pytest.mark.parametrize("fault", ["head", "document", "runtime", "readonly", "timeout"])
def test_explicit_input_refusals_happen_before_transport(tmp_path, monkeypatch, fault):
    source, store, native, first = bootstrap(tmp_path, monkeypatch)
    stage = projection(source, native, first)
    options = {}
    if fault == "head":
        changed = source.revise(expected_revision=source.revision_id, metadata={"newer": True})
        store.commit(changed, expected_revision=source.revision_id)
    elif fault == "document": options["expected_document_key"] = "foreign-document"
    elif fault == "runtime":
        target = replace(native.credentials.target, instance_id=str(uuid4()))
        options["advertisement"] = advertisement(replace(native.credentials, target=target))
    elif fault == "readonly": store = ProjectStore.open(store.path)
    else: options["timeout_ms"] = True
    before = len(native.requests)
    with pytest.raises(PublicationRefusal): publish(store, source, native, stage, **options)
    assert len(native.requests) == before and len(native.writes) == 1


def test_author_head_race_is_refused_by_atomic_reservation(tmp_path, monkeypatch):
    source, store, native, first = bootstrap(tmp_path, monkeypatch)
    stage = projection(source, native, first)
    def race():
        changed = source.revise(expected_revision=source.revision_id, metadata={"parallel": True})
        ProjectStore.open(store.path, readonly=False).commit(changed, expected_revision=source.revision_id)
    native.on_ping = race
    with pytest.raises(StoreConflict): publish(store, source, native, stage)
    assert len(native.writes) == 1


@pytest.mark.parametrize("fault", ["revision", "document"])
def test_native_context_change_is_not_hidden_by_recapturing_C0(tmp_path, monkeypatch, fault):
    source, store, native, first = bootstrap(tmp_path, monkeypatch)
    stage = projection(source, native, first)
    if fault == "revision": native.revision += 1
    else: native.document = "different-open-document"
    before = len(native.requests)
    attempt = publish(store, source, native, stage)
    assert not attempt.execution_contract_satisfied
    assert attempt.result.outcome.execution.value == "not_started"
    assert [r["kind"] for r in native.requests[before:]] == ["ping", "execute"]
    assert len(native.written_ops) == 3
    assert attempt.prepared.precondition is stage.precondition


def test_wrong_import_receipt_is_not_a_next_stage_permission(tmp_path, monkeypatch):
    source, store, native, first = bootstrap(tmp_path, monkeypatch)
    second = publish(store, source, native, projection(source, native, first))
    foreign = bind_create_receipt(second.record, second.result.raw_response,
        credentials=native.credentials, request_id=second.request_id)
    before = len(native.writes)
    with pytest.raises(CreatePublicationError) as refused:
        projection(source, native, first, "C", evidence=foreign)
    assert refused.value.code == "invalid_create_receipt"
    assert len(native.writes) == before


def test_missing_retained_import_receipt_blocks_publication_before_effect(tmp_path, monkeypatch):
    source, store, native, first = bootstrap(tmp_path, monkeypatch)
    stage = projection(source, native, first)
    # A genuine typed proof alone cannot replace the prior receipt's SQL owner.
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM create_receipts WHERE archive_digest=?", (first.record.digest,))
    with pytest.raises(StoreConflict): publish(store, source, native, stage)
    assert len(native.writes) == 1


def test_actual_oversize_source_refuses_before_probe_reservation_and_effect(tmp_path, monkeypatch):
    source, store, native, first = bootstrap(tmp_path, monkeypatch, walls_in_b=1200)
    stage = projection(source, native, first)
    assert len(stage.runtime_program["ops"]) == 1200
    before = len(native.requests)
    real_wrap = revit_connector.wrap_connector_source
    measured = []
    def measure(source):
        wrapped = real_wrap(source)
        # prepare_execution appends this exact association prefix immediately
        # after its real wrapper and before the real UTF-16 budget comparison.
        final = revit_connector.EXECUTION_ASSOCIATION_PREFIX + stage.association_digest + "\n" + wrapped
        measured.append({"source_utf16_units": len(final.encode("utf-16-le")) // 2,
                         "source_utf8_bytes": len(final.encode("utf-8"))})
        return wrapped
    monkeypatch.setattr(revit_connector, "wrap_connector_source", measure)
    with pytest.raises(ConnectorPreparationError) as refused:
        publish(store, source, native, stage)
    assert refused.value.code == "source_budget_exceeded"
    assert len(native.requests) == before and len(native.writes) == 1
    assert len(measured) == 1 and measured[0]["source_utf16_units"] > MAX_SOURCE_CHARS
    evidence = {**measured[0], "operations": 1200, "connector_max_source_units": MAX_SOURCE_CHARS,
                "refusal": refused.value.code, "stage_write_requests": len(native.writes) - 1}
    (tmp_path / "source-budget.json").write_text(json.dumps(evidence), encoding="utf-8")
    print(json.dumps(evidence))
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM create_inputs").fetchone()[0] == 1
