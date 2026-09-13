"""Source-free cancellation and explicit scope resolution over real portable IPC.

The service/journal and SQLite are real; CREATE responses in this helper are
seeded. These tests do not execute generated model code or load native Revit.
"""
from uuid import uuid4

import pytest

from kir import standalone_publish as publishing
from kir.create_publication import CreatePublicationError
from kir.project_store import CREATE_RESOLUTION_STORE_SCHEMA, ProjectStore
from kir.project_submission import bind_selected_project_submission
from kir.revit_connector import prepare_execution
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError
from kir.tests.test_revit_transport import native_server, helper
from kir.tests.test_stored_project_publication import setup, sent
from kir.tests.test_standalone_publish import probe
from kir.tests.test_project_publication_cli import call, arguments, status_args
from kir.tests.test_connector_cli import write_advertisement


def reserved(native_server, helper, tmp_path, *, upgrade=True):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    if upgrade:
        store.upgrade_schema(CREATE_RESOLUTION_STORE_SCHEMA, expected_revision=materialized.project.revision_id)
    condition = probe(advertisement, helper)
    prepared = prepare_execution(materialized.planned, target=advertisement.credentials.target,
        precondition=condition, operation_id=options["operation_id"])
    record = SavedExecutionRecord.capture_project(prepared,
        bind_selected_project_submission(materialized.project, materialized, prepared))
    store.reserve_create_publication(record, expected_revision=materialized.project.revision_id)
    return store, materialized, advertisement, root, options, record


def test_cancel_then_resolve_then_new_explicit_create_never_reexecutes_old_input(native_server, helper, tmp_path, monkeypatch):
    store, materialized, advertisement, root, options, record = reserved(native_server, helper, tmp_path)
    client = dict(advertisement=advertisement, client_path=helper, timeout_ms=10000)
    original_preparer = publishing.prepare_execution
    monkeypatch.setattr(publishing, "prepare_execution", lambda *_a, **_kw: pytest.fail("control recompiled"))
    cancelled = publishing.cancel_stored_create(store, record.digest, **client)
    assert cancelled.result.outcome.execution.value == "not_started"
    assert cancelled.prepared is None and cancelled.retained_receipt_digest
    assert cancelled.resolution_receipt_digest is None
    assert store.get_create_publication(record.digest).state == "reserved"
    assert store.get_create_resolution(record.digest) is None
    assert sent(root)[-1] == "cancel_before_start" and "execute" not in sent(root)
    reopened = ProjectStore.open(store.path, readonly=False)
    resolved = publishing.resolve_stored_create_not_started(reopened, record.digest, **client)
    assert resolved.resolution_receipt_digest == cancelled.retained_receipt_digest
    assert reopened.get_create_publication(record.digest).state == "released_not_started"
    assert sent(root)[-1] == "receipt" and "execute" not in sent(root)

    # A NEW explicit publication is possible, not replay of the old source/UUID.
    monkeypatch.setattr(publishing, "prepare_execution", original_preparer)
    fresh = publishing.publish_stored_project(reopened, materialized,
        **{**options, "operation_id": str(uuid4())}, isolation="per_op")
    assert fresh.execution_contract_satisfied and fresh.record.digest != record.digest
    assert sent(root).count("execute") == 1
    owners = reopened.get_create_publication(fresh.record.digest).output_ids
    again = publishing.resolve_stored_create_not_started(reopened, record.digest, **client)
    assert again.resolution_receipt_digest == resolved.resolution_receipt_digest
    assert reopened.get_create_publication(fresh.record.digest).output_ids == owners
    assert reopened.get_create_publication(fresh.record.digest).state == "reserved"
    assert sent(root).count("execute") == 1


def test_not_found_does_not_release_or_implicitly_cancel(native_server, helper, tmp_path):
    store, _, advertisement, root, _, record = reserved(native_server, helper, tmp_path)
    with pytest.raises(publishing.PublicationRefusal, match="bound_create_not_started_required"):
        publishing.resolve_stored_create_not_started(store, record.digest,
            advertisement=advertisement, client_path=helper, timeout_ms=10000)
    assert store.get_create_resolution(record.digest) is None
    assert store.get_create_publication(record.digest).state == "reserved"
    assert sent(root)[-1] == "receipt" and "cancel_before_start" not in sent(root) and "execute" not in sent(root)


def test_committed_create_cannot_be_cancelled_or_released(native_server, helper, tmp_path):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    store.upgrade_schema(CREATE_RESOLUTION_STORE_SCHEMA, expected_revision=materialized.project.revision_id)
    created = publishing.publish_stored_project(store, materialized, **options)
    client = dict(advertisement=advertisement, client_path=helper, timeout_ms=10000)
    cancellation = publishing.cancel_stored_create(store, created.record.digest, **client)
    assert cancellation.result.outcome.committed and cancellation.resolution_receipt_digest is None
    with pytest.raises(CreatePublicationError, match="bound_create_not_started_required"):
        publishing.resolve_stored_create_not_started(store, created.record.digest, **client)
    assert store.get_create_resolution(created.record.digest) is None
    assert store.get_create_publication(created.record.digest).state == "reserved"
    assert sent(root).count("execute") == 1


def test_resolution_requires_explicit_upgrade_before_transport(native_server, helper, tmp_path):
    store, _, advertisement, root, _, record = reserved(native_server, helper, tmp_path, upgrade=False)
    before = sent(root)
    with pytest.raises(publishing.PublicationRefusal, match="writable_create_resolution_store_required"):
        publishing.resolve_stored_create_not_started(store, record.digest,
            advertisement=advertisement, client_path=helper, timeout_ms=10000)
    assert sent(root) == before and store.schema.endswith("/6")


def test_cancellation_cannot_target_a_recovery_runtime(native_server, helper, tmp_path):
    store, _, _, root, _, record = reserved(native_server, helper, tmp_path)
    other, other_root = native_server("2026")
    before = sent(root), sent(other_root)
    with pytest.raises(SavedExecutionError, match="target_mismatch"):
        publishing.cancel_stored_create(store, record.digest,
            advertisement=other, client_path=helper, timeout_ms=10000)
    assert (sent(root), sent(other_root)) == before


def test_cli_explicit_upgrade_cancel_resolve_and_retained_status(native_server, helper, tmp_path):
    store, materialized, advertisement, root, options, record = reserved(native_server, helper, tmp_path, upgrade=False)
    directory = tmp_path / "discovery"
    write_advertisement(directory, advertisement)
    from kir import __main__ as cli
    code, upgraded, _ = call(["project", "create-upgrade", str(store.path), "--expected",
        materialized.project.revision_id, "--enable-no-start-resolution"])
    assert code == cli.ANSWERED and upgraded["store_schema"] == CREATE_RESOLUTION_STORE_SCHEMA
    cancel_args = arguments("create-cancel-before-start", store, advertisement, helper, directory) + ["--archive", record.digest]
    code, cancelled, _ = call(cancel_args)
    assert code == cli.ANSWERED and cancelled["no_start_confirmed"]
    assert not cancelled["execution_contract_satisfied"] and cancelled["resolution_receipt_digest"] is None
    status = call(status_args(store, advertisement, options["operation_id"]))[1]
    assert status["scope_ownership"] == "retained"
    resolve_args = arguments("create-resolve-not-started", store, advertisement, helper, directory) + ["--archive", record.digest]
    code, resolved, _ = call(resolve_args)
    assert code == cli.ANSWERED and resolved["resolution_receipt_digest"] == cancelled["retained_receipt_digest"]
    status = call(status_args(store, advertisement, options["operation_id"]))[1]
    assert status["scope_ownership"] == "released_not_started" and status["reservation_state"] == "released_not_started"
    assert status["resolution_receipt_digest"] == resolved["resolution_receipt_digest"]
    assert not status["may_retry"] and "execute" not in sent(root)
