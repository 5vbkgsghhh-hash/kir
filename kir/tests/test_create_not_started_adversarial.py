"""Independent Store/7 controls: real SQLite, synthetic explicitly bound wire.

No native invocation, live channel authentication, crash durability or automatic
retry is inferred from these tests. Native Engine/journal regression is separate.
"""
from copy import copy, deepcopy
from dataclasses import replace
import json
import sqlite3
import sys
from uuid import uuid4

import pytest

from kir import project_store as storage
from kir import standalone_publish as publishing
from kir.bridge_result import WriteResultAssessment
from kir.create_publication import CreatePublicationError, bind_create_receipt
from kir.outcome import program_not_started
from kir.project_store import (
    ProjectStore, ProjectStoreError, StoreConflict, StoreCorrupt, StoreCommitUnknown,
    CREATE_STORE_SCHEMA, CREATE_RESOLUTION_STORE_SCHEMA,
)
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.revit_discovery import load_discovery
from kir.tests.test_create_not_started_store import evidence, rows, setup
from kir.tests.test_project_create_store import archive


def release(store, record, bound):
    return store.release_create_not_started(bound, expected_archive_digest=record.digest)


def route_response(record, credentials, request_id, receipt):
    return {"protocol": "kir-revit-connector/4", "target": credentials.target.to_dict(),
            "session_id": credentials.session_id, "request_id": request_id,
            "ok": True, "status": "receipt", "context": None, "error": None,
            "receipt": deepcopy(receipt)}


def advertisement(record, *, recovery=False):
    target = (RuntimeTarget(str(uuid4()), str(uuid4()), "2026") if recovery else
              RuntimeTarget(**record.binding_dict()["target"]))
    credentials = SessionCredentials(target, str(uuid4()), "synthetic-no-start-secret")
    return load_discovery(json.dumps({"protocol": "kir-revit-connector/4", "target": target.to_dict(),
        "session_id": credentials.session_id, "token": credentials.token,
        "pipe_name": "kir-synthetic-no-start-not-connected", "process_id": 123,
        "expires_utc": "2099-01-01T00:00:00.0000000Z"}).encode())


@pytest.mark.parametrize("fault", ["outer-false", "outer-status", "outer-error", "refused-result", "wrapped-result"])
def test_public_no_start_projection_cannot_repair_outer_or_raw_result(tmp_path, fault):
    store, _, record = setup(tmp_path)
    good = evidence(record)
    credentials = advertisement(record).credentials
    response = route_response(record, credentials, str(uuid4()), good.receipt)
    if fault == "outer-false": response["ok"] = False
    elif fault == "outer-status": response["status"] = "journal_unavailable"
    elif fault == "outer-error": response["error"] = "journal append was not confirmed"
    else:
        response["receipt"]["result_json"] = json.dumps(
            {"refused_op_id": record.project_submission["outputs"][0]["output_id"], "error": "refused"}
            if fault == "refused-result" else {"result": {"ok": True}})
    bound = bind_create_receipt(record, json.dumps(response), credentials=credentials,
                                request_id=response["request_id"])
    # Raw facts are retainable even when they cannot support owner release.
    assert store.record_create_receipt(bound).inserted
    forged = copy(bound)
    repaired = deepcopy(response)
    repaired.update(ok=True, status="receipt", error=None)
    object.__setattr__(forged, "assessment", replace(bound.assessment,
        diagnostic_code="not_started", assessment=WriteResultAssessment(program_not_started()),
        raw_response=json.dumps(repaired).encode()))
    assert forged.not_started  # Deliberately demonstrate the untrusted projection.
    before = rows(store)
    with pytest.raises(StoreConflict): release(store, record, forged)
    assert rows(store) == before
    assert store.get_create_resolution(record.digest) is None
    assert store.get_create_publication(record.digest).state == "reserved"


@pytest.mark.parametrize("fault", ["foreign-receipt", "foreign-input", "same-input-progress"])
def test_resolution_marker_cannot_be_repointed_to_an_existing_but_wrong_row(tmp_path, fault):
    store, source, original = setup(tmp_path)
    good = evidence(original)
    release(store, original, good)
    other = archive(source, roots=("unselected",))
    store.reserve_create_publication(other, expected_revision=source.revision_id)
    other_receipt = evidence(other)
    store.record_create_receipt(other_receipt)
    progress = evidence(original, "running_unknown")
    store.record_create_receipt(progress)
    with sqlite3.connect(store.path) as connection:
        if fault == "foreign-input":
            connection.execute("UPDATE create_resolutions SET archive_digest=?", (other.digest,))
        else:
            connection.execute("UPDATE create_resolutions SET receipt_digest=?",
                (progress.receipt_digest if fault == "same-input-progress" else other_receipt.receipt_digest,))
    for read in (lambda: store.get_create_resolution(original.digest),
                 lambda: store.get_create_publication(other.digest), store.history):
        with pytest.raises(StoreCorrupt): read()


@pytest.mark.parametrize("fault", ["partial", "foreign-namespace", "foreign-output", "orphan"])
def test_incomplete_or_relabelled_owner_scope_cannot_be_released(tmp_path, fault):
    store, _, record = setup(tmp_path)
    good = evidence(record)
    with sqlite3.connect(store.path) as connection:
        oid = connection.execute("SELECT output_id FROM create_scope_owners ORDER BY output_id").fetchone()[0]
        assert connection.execute("SELECT count(*) FROM create_scope_owners").fetchone()[0] > 1
        if fault == "partial": connection.execute("DELETE FROM create_scope_owners WHERE output_id=?", (oid,))
        elif fault == "foreign-namespace": connection.execute("UPDATE create_scope_owners SET document_key='another-document' WHERE output_id=?", (oid,))
        elif fault == "foreign-output": connection.execute("UPDATE create_scope_owners SET output_id=? WHERE output_id=?", ("f" * 64, oid))
        else: connection.execute("UPDATE create_scope_owners SET archive_digest=? WHERE output_id=?", ("f" * 64, oid))
    before = rows(store)
    with pytest.raises(StoreCorrupt): release(store, record, good)
    assert rows(store) == before


class PartialReleaseConnection:
    """Inject failure after a real statement effect, before the enclosing COMMIT."""
    def __init__(self, inner, fault):
        self.inner, self.fault, self.fired = inner, fault, False

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def execute(self, sql, *args):
        result = self.inner.execute(sql, *args)
        prefix = {"receipt": "INSERT INTO create_receipts", "marker": "INSERT INTO create_resolutions",
                  "migration-table": "CREATE TABLE create_resolutions",
                  "migration-header": "PRAGMA user_version=7"}.get(self.fault)
        if not self.fired and prefix and sql.startswith(prefix):
            self.fired = True
            raise sqlite3.OperationalError("controlled failure after insert")
        return result

    def executemany(self, sql, args):
        if not self.fired and self.fault == "partial-owners" and sql.startswith("DELETE FROM create_scope_owners"):
            self.fired = True
            arguments = list(args)
            assert len(arguments) > 1
            self.inner.execute(sql, arguments[0])
            raise sqlite3.OperationalError("controlled failure after first owner deletion")
        return self.inner.executemany(sql, args)


@pytest.mark.parametrize("fault", ["receipt", "marker", "partial-owners"])
def test_statement_effect_failure_rolls_back_all_three_resolution_effects(tmp_path, monkeypatch, fault):
    store, _, record = setup(tmp_path)
    good, before = evidence(record), rows(store)
    connect = storage._connect
    injected = []
    def wrapped(*args, **kwargs):
        connection = PartialReleaseConnection(connect(*args, **kwargs), fault)
        injected.append(connection)
        return connection
    with monkeypatch.context() as patch:
        patch.setattr(storage, "_connect", wrapped)
        with pytest.raises(ProjectStoreError): release(store, record, good)
    assert any(connection.fired for connection in injected)
    assert rows(store) == before
    assert store.get_create_resolution(record.digest) is None
    assert release(store, record, good).inserted


@pytest.mark.parametrize("fault", ["migration-table", "migration-header"])
def test_failed_explicit_migration_keeps_schema6_and_old_publication_bytes(tmp_path, monkeypatch, fault):
    store, source, record = setup(tmp_path, CREATE_STORE_SCHEMA)
    store.record_create_receipt(evidence(record))
    before = rows(store)
    connect = storage._connect
    injected = []
    def wrapped(*args, **kwargs):
        connection = PartialReleaseConnection(connect(*args, **kwargs), fault)
        injected.append(connection)
        return connection
    with monkeypatch.context() as patch:
        patch.setattr(storage, "_connect", wrapped)
        with pytest.raises(ProjectStoreError):
            store.upgrade_schema(CREATE_RESOLUTION_STORE_SCHEMA, expected_revision=source.revision_id)
    assert any(connection.fired for connection in injected)
    assert rows(store) == before
    reopened = ProjectStore.open(store.path, readonly=False)
    assert reopened.schema == CREATE_STORE_SCHEMA
    assert reopened.get_create_publication(record.digest).record._raw == record._raw
    assert reopened.upgrade_schema(CREATE_RESOLUTION_STORE_SCHEMA, expected_revision=source.revision_id)
    assert reopened.get_create_publication(record.digest).state == "reserved"
    assert reopened.get_create_resolution(record.digest) is None


def test_release_cannot_substitute_another_existing_input_or_late_terminal(tmp_path):
    store, source, original = setup(tmp_path)
    other = archive(source, roots=("unselected",))
    store.reserve_create_publication(other, expected_revision=source.revision_id)
    good = evidence(original)
    before = rows(store)
    with pytest.raises(StoreConflict): release(store, other, good)
    assert rows(store) == before
    release(store, original, good)
    before = rows(store)
    with pytest.raises(StoreConflict): release(store, original, evidence(original, "rejected_before_start"))
    assert rows(store) == before
    assert store.get_create_publication(other.digest).state == "reserved"


def test_lost_release_ack_then_new_owner_and_late_progress_cannot_demote_or_reclear(tmp_path, monkeypatch):
    store, source, original = setup(tmp_path)
    good = evidence(original)
    commit = storage._commit
    def committed_then_lost(connection):
        commit(connection)
        raise StoreCommitUnknown("controlled lost release ACK")
    with monkeypatch.context() as patch:
        patch.setattr(storage, "_commit", committed_then_lost)
        with pytest.raises(StoreCommitUnknown): release(store, original, good)
    reopened = ProjectStore.open(store.path, readonly=False)
    newer = archive(source, roots=("section",))
    assert reopened.reserve_create_publication(newer, expected_revision=source.revision_id).inserted
    before_owners = rows(reopened)["create_scope_owners"]
    late = reopened.record_create_receipt(evidence(original, "running_unknown"))
    assert late.terminal_receipt_digest == good.receipt_digest
    replay = release(reopened, original, good)
    assert not replay.inserted and not replay.may_retry
    assert rows(reopened)["create_scope_owners"] == before_owners
    assert reopened.get_create_publication(original.digest).state == "released_not_started"
    assert reopened.get_create_publication(newer.digest).state == "reserved"
    changed = source.revise(expected_revision=source.revision_id, metadata={"new-source": True})
    reopened.commit(changed, expected_revision=source.revision_id)
    reused_uuid = archive(changed, roots=("section",), operation=original.binding_dict()["operation_id"])
    with pytest.raises(StoreConflict):
        reopened.reserve_create_publication(reused_uuid, expected_revision=changed.revision_id)


def install_exchange(monkeypatch, record, advertisement, response_factory):
    requests = []
    def exchange(advertised, raw, **_options):
        assert advertised is advertisement
        request = json.loads(raw)
        requests.append(request)
        assert request["kind"] in ("receipt", "recover_receipt", "cancel_before_start")
        assert "source" not in request and "context" not in request
        return json.dumps(response_factory(request)).encode()
    monkeypatch.setattr(publishing, "exchange", exchange)
    monkeypatch.setattr(publishing, "prepare_execution", lambda *_a, **_kw: pytest.fail("control recompiled"))
    return requests


@pytest.mark.parametrize("recovery", [False, True])
def test_fresh_resolution_route_preserves_original_binding_and_old_ack_after_new_owner(tmp_path, monkeypatch, recovery):
    store, source, record = setup(tmp_path)
    ad = advertisement(record, recovery=recovery)
    native = evidence(record).receipt
    requests = install_exchange(monkeypatch, record, ad,
        lambda request: route_response(record, ad.credentials, request["request_id"], native))
    args = dict(advertisement=ad, client_path=sys.executable, recovery=recovery)
    result = publishing.resolve_stored_create_not_started(store, record.digest, **args)
    assert result.prepared is None and result.resolution_receipt_digest
    assert result.record._raw == record._raw
    other = archive(source, roots=("section",))
    store.reserve_create_publication(other, expected_revision=source.revision_id)
    owner_rows = rows(store)["create_scope_owners"]
    again = publishing.resolve_stored_create_not_started(store, record.digest, **args)
    assert again.resolution_receipt_digest == result.resolution_receipt_digest
    assert rows(store)["create_scope_owners"] == owner_rows
    assert [request["kind"] for request in requests] == ["recover_receipt" if recovery else "receipt"] * 2
    if recovery:
        assert requests[0]["recovery_target"] == record.binding_dict()["target"]
        assert requests[0]["target"] != native["target"]


@pytest.mark.parametrize("fault", ["outer-error", "foreign-native-target", "refused-result", "missing"])
def test_control_refusal_or_foreign_wire_never_releases_owners(tmp_path, monkeypatch, fault):
    store, _, record = setup(tmp_path)
    ad = advertisement(record)
    native = evidence(record).receipt
    def answer(request):
        response = route_response(record, ad.credentials, request["request_id"], native)
        if fault == "outer-error": response.update(ok=False, status="journal_unavailable", error="unknown")
        elif fault == "foreign-native-target": response["receipt"]["target"]["instance_id"] = str(uuid4())
        elif fault == "refused-result": response["receipt"]["result_json"] = '{"error":"refused"}'
        else: response.update(receipt=None, ok=False, status="not_found")
        return response
    requests = install_exchange(monkeypatch, record, ad, answer)
    before = rows(store)["create_scope_owners"]
    with pytest.raises((publishing.PublicationRefusal, CreatePublicationError)):
        publishing.resolve_stored_create_not_started(store, record.digest,
            advertisement=ad, client_path=sys.executable)
    assert len(requests) == 1
    assert rows(store)["create_scope_owners"] == before
    assert store.get_create_resolution(record.digest) is None


def test_cancel_on_schema6_never_upgrades_or_releases_and_resolution_sends_nothing(tmp_path, monkeypatch):
    store, _, record = setup(tmp_path, CREATE_STORE_SCHEMA)
    ad = advertisement(record)
    requests = install_exchange(monkeypatch, record, ad,
        lambda request: route_response(record, ad.credentials, request["request_id"], evidence(record).receipt))
    cancelled = publishing.cancel_stored_create(store, record.digest,
        advertisement=ad, client_path=sys.executable)
    assert cancelled.result.outcome.execution.value == "not_started"
    assert cancelled.resolution_receipt_digest is None and store.schema == CREATE_STORE_SCHEMA
    assert store.get_create_publication(record.digest).state == "reserved"
    with pytest.raises(publishing.PublicationRefusal, match="writable_create_resolution_store_required"):
        publishing.resolve_stored_create_not_started(store, record.digest,
            advertisement=ad, client_path=sys.executable)
    assert len(requests) == 1 and requests[0]["kind"] == "cancel_before_start"


def test_resolved_read_and_exact_redelivery_use_historical_source_not_current_registry(tmp_path, monkeypatch):
    store, source, record = setup(tmp_path)
    good = evidence(record)
    release(store, record, good)
    later = source.revise(expected_revision=source.revision_id, metadata={"later": 1})
    store.commit(later, expected_revision=source.revision_id)
    import kir.bridge_result
    import kir.compiler
    import kir.project_submission
    validator = kir.project_submission.validate_submission_source
    def historical(project, submission, *, selection_policy="current"):
        assert selection_policy == "retained"
        return validator(project, submission, selection_policy=selection_policy)
    monkeypatch.setattr(kir.project_submission, "validate_submission_source", historical)
    def forbidden(*_args, **_kwargs): pytest.fail("historical no-start queried current planner/profile")
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    monkeypatch.setattr(kir.compiler, "compile_program", forbidden)
    monkeypatch.setattr(kir.bridge_result, "saved_create_result_contract", forbidden)
    reader = ProjectStore.open(store.path)
    assert reader.get_create_publication(record.digest).record._raw == record._raw
    assert reader.get_create_resolution(record.digest).receipt_digest == good.receipt_digest
    assert not store.reserve_create_publication(record, expected_revision=source.revision_id).inserted
    assert not release(store, record, good).inserted
    assert store.head().revision_id == later.revision_id
