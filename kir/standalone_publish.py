"""Explicit first publication: capture -> compile -> archive -> one delivery.

This is orchestration of existing contracts, not another compiler, journal or
receipt interpreter. No mutation retry or implicit selection of a Revit process
is allowed. Saved execution material remains available if transport later fails;
loading it does not authorize another execute request.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from kir.connector_result import (
    ConnectorResultAssessment, assess_connector_context_response,
    assess_connector_write_response,
)
from kir.revit_connector import ConnectorPreparationError, prepare_execution, _text, _uuid
from kir.revit_discovery import DiscoveryAdvertisement
from kir.revit_transport import exchange, validate_exchange_inputs

if TYPE_CHECKING:
    from kir.saved_execution import SavedExecutionRecord
    from kir.project import ProjectRevision
    from kir.geometry_materialization import GeometryMaterialization
    from kir.revit_connector import PreparedExecution
    from kir.revit_level_update import LevelElevationUpdatePlan


class PublicationRefusal(ValueError):
    """A prerequisite for this publication is absent; never permission to retry."""

    def __init__(self, code: str, stage: str):
        self.code, self.stage, self.may_retry = code, stage, False
        super().__init__(f"{code}: {stage}; publication prerequisite not satisfied")


@dataclass(frozen=True, slots=True)
class PublicationAttempt:
    record: SavedExecutionRecord = field(repr=False)
    request_id: str
    result: ConnectorResultAssessment = field(repr=False)
    prepared: PreparedExecution | None = field(default=None, repr=False)
    retained_receipt_digest: str | None = None
    resolution_receipt_digest: str | None = None

    @property
    def execution_contract_satisfied(self) -> bool:
        return self.result.ok

    @property
    def intent_verified(self) -> bool:
        # This workflow has no independent native model acceptance/readback.
        return False


def _wire(request: dict) -> bytes:
    return json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _probe_connection(advertisement, *, client_path, timeout_ms):
    """One bound ping, not a document capture or a replacement precondition."""
    from kir.connector_result import require_connector_ready_response
    request_id = str(uuid4())
    probe_timeout = min(timeout_ms, 30000)
    request = advertisement.credentials.ping_request(request_id=request_id, timeout_ms=probe_timeout)
    response = exchange(advertisement, _wire(request), client_path=client_path, timeout_ms=probe_timeout)
    try:
        require_connector_ready_response(response, credentials=advertisement.credentials, request_id=request_id)
    except ConnectorPreparationError as error:
        raise PublicationRefusal("connector_not_ready", "preflight") from error


def publish_program(program: Any, *, advertisement: DiscoveryAdvertisement,
                    client_path: str | Path, archive_path: str | Path,
                    expected_document_key: str, operation_id: str,
                    bind_view: bool, bind_selection: bool,
                    timeout_ms: int = 120000, bulk: bool = False) -> PublicationAttempt:
    """Publish only after fresh preparation and acknowledged durable archiving.

    The caller explicitly selected the advertisement, inspected/authorized the
    opaque open-document key, and assigned a stable operation ID. Do not derive
    that key from a title or silently mint a new operation ID after a failure.
    Both UI-binding choices are required. The native boundary rechecks context
    immediately before effects; this read alone cannot freeze a Revit document.

    The archive path must be NEW. No existing record is overwritten or treated
    as a dispatch ticket. Exceptions before archive acknowledgement cause no
    execute call. After acknowledgement, a transport error leaves that archive
    intact for receipt/recovery lookup and is never caught to retry a mutation.
    `timeout_ms` bounds each transport exchange, not all compilation/storage CPU
    work. A receipt and its witnesses do not establish independent BIM intent.

    Caller-provided programs may already be explicitly materialized geometry.
    This helper never loads recipes, selects assets or regenerates a project.
    """
    return _publish(program, project_input=None, advertisement=advertisement,
        client_path=client_path, archive_path=archive_path, expected_document_key=expected_document_key,
        operation_id=operation_id, bind_view=bind_view, bind_selection=bind_selection,
        timeout_ms=timeout_ms, bulk=bulk)


def publish_materialized_project(project: ProjectRevision, materialized: GeometryMaterialization, *,
                    advertisement: DiscoveryAdvertisement, client_path: str | Path,
                    archive_path: str | Path, expected_document_key: str, operation_id: str,
                    bind_view: bool, bind_selection: bool, timeout_ms: int = 120000) -> PublicationAttempt:
    """Archive the selected authored association before delivering its exact plan.

    Materialization is explicit and supplied, never regenerated here. Its plan
    and bulk policy are retained. Caller owns persistence of the Project/asset
    history: the compact execution archive references that source rather than
    duplicating it. This does not publish a native update or prove preservation
    of already realized elements. Native receipts do not attest project metadata.
    """
    from kir.project import ProjectRevision
    from kir.geometry_materialization import GeometryMaterialization

    if type(project) is not ProjectRevision or type(materialized) is not GeometryMaterialization:
        raise PublicationRefusal("explicit_materialized_project_required", "input")
    if project.dumps() != materialized.project.dumps():
        raise PublicationRefusal("materialized_project_mismatch", "input")
    return _publish(materialized.planned, project_input=(project, materialized), advertisement=advertisement,
        client_path=client_path, archive_path=archive_path, expected_document_key=expected_document_key,
        operation_id=operation_id, bind_view=bind_view, bind_selection=bind_selection,
        timeout_ms=timeout_ms, bulk=materialized.planned.bulk)


def publish_stored_project(project_store, materialized, *, expected_revision: str,
                    advertisement: DiscoveryAdvertisement, client_path: str | Path,
                    expected_document_key: str, operation_id: str,
                    bind_view: bool, bind_selection: bool, timeout_ms: int = 120000,
                    isolation: str = "atomic") -> PublicationAttempt:
    """Reserve selected/full flat CREATE input in ProjectStore, send once, retain receipt.

    The full authored source must already be saved at the expected head. No
    separate archive file, implicit migration, geometry derivation or retry is
    performed. A lost native/local acknowledgement leaves durable input owners.
    A retained receipt is not independent BIM acceptance or fresh model state.
    """
    from kir.project_store import ProjectStore, _CREATE_SCHEMAS
    from kir.geometry_materialization import GeometryMaterialization
    if type(project_store) is not ProjectStore or type(materialized) is not GeometryMaterialization:
        raise PublicationRefusal("explicit_store_and_materialization_required", "input")
    if project_store.readonly or project_store.schema not in _CREATE_SCHEMAS:
        raise PublicationRefusal("writable_create_store_required", "input")
    if (materialized.project.revision_id != expected_revision
            or project_store.head().dumps() != materialized.project.dumps()):
        raise PublicationRefusal("stored_source_mismatch", "input")
    return _publish(materialized.planned, project_input=(materialized.project, materialized),
        advertisement=advertisement, client_path=client_path, archive_path=None,
        expected_document_key=expected_document_key, operation_id=operation_id,
        bind_view=bind_view, bind_selection=bind_selection, timeout_ms=timeout_ms,
        bulk=materialized.planned.bulk, project_store=project_store, expected_revision=expected_revision,
        isolation=isolation)


def _publish(program, *, project_input, advertisement, client_path, archive_path,
             expected_document_key, operation_id, bind_view, bind_selection, timeout_ms, bulk,
             project_store=None, expected_revision=None, isolation="atomic"):
    """The closed input variants share one first-send sequence, not callbacks."""
    from kir.saved_execution import SavedExecutionRecord

    if type(advertisement) is not DiscoveryAdvertisement:
        raise PublicationRefusal("explicit_advertisement_required", "input")
    if any(type(value) is not bool for value in (bind_view, bind_selection, bulk)):
        raise PublicationRefusal("explicit_boolean_policy_required", "input")
    if type(isolation) is not str or isolation not in ("atomic", "per_op"):
        raise PublicationRefusal("invalid_isolation", "input")
    if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 300000:
        raise PublicationRefusal("invalid_timeout", "input")
    _text(expected_document_key, "expected_document_key")
    operation_id = _uuid(operation_id, "operation_id")
    credentials = advertisement.credentials
    context_id = str(uuid4())
    context_request = credentials.context_request(request_id=context_id, timeout_ms=min(timeout_ms, 30000))
    context_response = exchange(advertisement, _wire(context_request), client_path=client_path, timeout_ms=timeout_ms)
    context = assess_connector_context_response(context_response, credentials=credentials, request_id=context_id)
    try:
        precondition = context.require_precondition(bind_view=bind_view, bind_selection=bind_selection)
    except ConnectorPreparationError as error:
        raise PublicationRefusal("context_unavailable", "context") from error
    if precondition.document_key != expected_document_key:
        raise PublicationRefusal("unexpected_document", "context")

    prepared = prepare_execution(program, target=credentials.target, precondition=precondition,
                                 operation_id=operation_id, bulk=bulk, isolation=isolation)
    if prepared.planned.family.value != "write":
        raise PublicationRefusal("write_program_required", "compilation")
    request_id, request_bytes = _frame_and_probe(prepared, advertisement, client_path=client_path,
                                                 timeout_ms=timeout_ms)
    if project_input is None:
        record = SavedExecutionRecord.create_new(archive_path, prepared)
        record.require_matches(prepared)
    else:
        from kir.project_submission import bind_project_submission, bind_selected_project_submission
        selected = project_store is not None and project_input[1].selection is not None
        binder = bind_selected_project_submission if selected else bind_project_submission
        submission = binder(*project_input, prepared)
        record = (SavedExecutionRecord.capture_project(prepared, submission) if project_store is not None
                  else SavedExecutionRecord.create_project_new(archive_path, prepared, submission))
        record.require_matches(prepared, submission=submission)
    return _reserve_and_send(prepared, record, request_id, request_bytes, advertisement=advertisement,
                             client_path=client_path, timeout_ms=timeout_ms,
                             project_store=project_store, expected_revision=expected_revision)


def _frame_and_probe(prepared, advertisement, *, client_path, timeout_ms):
    """Frame, budget-check and ping BEFORE any archive or reservation exists.

    The credential-bearing external frame is checked first so that no archive
    is created for a request the transport cannot carry.
    """
    request_id = str(uuid4())
    request = prepared.execute_request(advertisement.credentials, request_id=request_id, timeout_ms=timeout_ms)
    request_bytes = _wire(request)
    validate_exchange_inputs(advertisement, request_bytes, client_path=client_path, timeout_ms=timeout_ms)
    _probe_connection(advertisement, client_path=client_path, timeout_ms=timeout_ms)
    return request_id, request_bytes


def _reserve_and_send(prepared, record, request_id, request_bytes, *, advertisement, client_path,
                      timeout_ms, project_store=None, expected_revision=None, submission=None):
    """Reserve before the one send; bind a receipt only to a matched response.

    Every input variant (file archive, stored flat CREATE, staged CREATE)
    shares this tail, so the ordering law has one carrier.
    """
    credentials = advertisement.credentials
    if project_store is not None:
        reservation = project_store.reserve_create_publication(record, expected_revision=expected_revision,
                                                               submission=submission)
        if not reservation.inserted:
            raise PublicationRefusal("create_already_reserved", "reservation")
    response = exchange(advertisement, request_bytes, client_path=client_path, timeout_ms=timeout_ms)
    result = assess_connector_write_response(prepared, response, credentials=credentials, request_id=request_id)
    receipt_digest = None
    if project_store is not None:
        from kir.create_publication import bind_create_receipt
        # No original bound receipt (e.g. timeout/not_found) leaves input pending.
        # A mismatched response must not be attached to this reservation.
        if result.binding_matches and result.receipt is not None:
            evidence = bind_create_receipt(record, response, credentials=credentials, request_id=request_id)
            receipt_digest = project_store.record_create_receipt(evidence).receipt_digest
    return PublicationAttempt(record, request_id, result, prepared, receipt_digest)


def recover_stored_create(project_store, archive_digest: str, *, advertisement: DiscoveryAdvertisement,
                          client_path: str | Path, recovery: bool = False,
                          timeout_ms: int = 30000) -> PublicationAttempt:
    """Lookup original receipt after restart, never recompile or resend CREATE.

    Recovery through another runtime is explicit. Its outer route must match
    that runtime while the receipt still binds the original archived input.
    Missing/unknown receipts leave the reservation and all owners unchanged.
    """
    return _stored_create_request(project_store, archive_digest, advertisement=advertisement,
        client_path=client_path, recovery=recovery, cancel=False, timeout_ms=timeout_ms)


def cancel_stored_create(project_store, archive_digest: str, *, advertisement: DiscoveryAdvertisement,
                         client_path: str | Path, timeout_ms: int = 30000) -> PublicationAttempt:
    """Explicit original-runtime journal cancellation, not model rollback.

    The source-free control request may prevent admission if it has not begun.
    Started/completed work is never stopped by this method. Owners remain held
    until a separate explicit no-start resolution, even after cancellation.
    """
    return _stored_create_request(project_store, archive_digest, advertisement=advertisement,
        client_path=client_path, recovery=False, cancel=True, timeout_ms=timeout_ms)


def _stored_create_request(project_store, archive_digest, *, advertisement, client_path,
                           recovery, cancel, timeout_ms):
    from kir.project_store import ProjectStore, _CREATE_SCHEMAS
    from kir.connector_result import assess_connector_saved_create_response
    from kir.create_publication import bind_create_receipt
    if (type(project_store) is not ProjectStore or project_store.readonly
            or project_store.schema not in _CREATE_SCHEMAS or type(advertisement) is not DiscoveryAdvertisement
            or type(recovery) is not bool or type(cancel) is not bool or (cancel and recovery)
            or type(timeout_ms) is not int or not 1000 <= timeout_ms <= 300000):
        raise PublicationRefusal("explicit_create_recovery_inputs_required", "input")
    record = project_store.get_create_publication(archive_digest).record
    request_id = str(uuid4())
    if cancel:
        request = record.cancel_before_start_request(advertisement.credentials, request_id=request_id,
                                                     timeout_ms=timeout_ms)
    else:
        request = (record.recovery_request(advertisement.credentials, request_id=request_id) if recovery
                   else record.receipt_request(advertisement.credentials, request_id=request_id))
    response = exchange(advertisement, _wire(request), client_path=client_path, timeout_ms=timeout_ms)
    result = assess_connector_saved_create_response(record, response, credentials=advertisement.credentials,
        request_id=request_id, recovery=recovery)
    receipt_digest = None
    if result.binding_matches and result.receipt is not None:
        evidence = bind_create_receipt(record, response, credentials=advertisement.credentials,
                                      request_id=request_id, recovery=recovery)
        receipt_digest = project_store.record_create_receipt(evidence).receipt_digest
    return PublicationAttempt(record, request_id, result, None, receipt_digest)


def resolve_stored_create_not_started(project_store, archive_digest: str, *,
        advertisement: DiscoveryAdvertisement, client_path: str | Path,
        recovery: bool = False, timeout_ms: int = 30000) -> PublicationAttempt:
    """Fresh native lookup, then explicit exact-input no-start resolution.

    No compile, CREATE resend, implicit cancellation or schema upgrade. The
    native fact is retained before qualification; only a bound coherent no-start
    may atomically release the old owners. The returned resolution is historical
    acknowledgement, not a claim that another publication has not acquired them.
    """
    from kir.project_store import ProjectStore, CREATE_RESOLUTION_STORE_SCHEMA
    from kir.create_publication import bind_create_receipt, require_create_not_started
    if (type(project_store) is not ProjectStore or project_store.readonly
            or project_store.schema != CREATE_RESOLUTION_STORE_SCHEMA):
        raise PublicationRefusal("writable_create_resolution_store_required", "input")
    attempt = recover_stored_create(project_store, archive_digest, advertisement=advertisement,
        client_path=client_path, recovery=recovery, timeout_ms=timeout_ms)
    if not attempt.result.binding_matches or attempt.result.receipt is None:
        raise PublicationRefusal("bound_create_not_started_required", "resolution")
    evidence = bind_create_receipt(attempt.record, attempt.result.raw_response,
        credentials=advertisement.credentials, request_id=attempt.request_id, recovery=recovery)
    require_create_not_started(attempt.record, evidence)
    resolution = project_store.release_create_not_started(evidence, expected_archive_digest=archive_digest)
    return replace(attempt, resolution_receipt_digest=resolution.receipt_digest)


def publish_level_update(update: LevelElevationUpdatePlan, *, advertisement: DiscoveryAdvertisement,
                         client_path: str | Path, archive_path: str | Path,
                         operation_id: str, timeout_ms: int = 120000,
                         project_store=None,
                         expected_project_revision: str | None = None) -> PublicationAttempt:
    """Archive one fresh update association, then deliver exactly once.

    Unlike first publication, this path MUST NOT capture a newer context: the
    native boundary checks the revision belonging to the plan's observation.
    An existing archive is not a replay ticket. A lost response leaves the
    original archive for read-only receipt/recovery, never an automatic retry.
    Native after-readback/acceptance remains a separate operation.

    Supplying a ProjectStore reserves a durable pending operation before send.
    It is mandatory for an iterative checkpoint-based update. Exact reservation
    redelivery is not a send ticket. Unknown or failed acceptance leaves pending
    intact; successful after qualification must be settled explicitly in store.
    An optional authored-head pin belongs to the store reservation transaction,
    not to a preflight read or a lock held during native execution.
    """
    from kir.revit_level_update import LevelElevationUpdatePlan, prepare_level_update
    from kir.saved_execution import SavedExecutionRecord
    from kir.update_submission import bind_level_update_submission

    if type(update) is not LevelElevationUpdatePlan or type(advertisement) is not DiscoveryAdvertisement:
        raise PublicationRefusal("explicit_update_and_advertisement_required", "input")
    if advertisement.credentials.target != update.target:
        raise PublicationRefusal("update_target_mismatch", "input")
    if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 300000:
        raise PublicationRefusal("invalid_timeout", "input")
    if project_store is not None:
        from kir.project_store import ProjectStore
        if type(project_store) is not ProjectStore or project_store.readonly:
            raise PublicationRefusal("writable_project_store_required", "input")
    elif expected_project_revision is not None:
        raise PublicationRefusal("head_pin_requires_project_store", "input")
    if update.baseline is not None and (project_store is None or project_store.store_id != update.baseline.store_id):
        raise PublicationRefusal("baseline_project_store_required", "input")
    prepared = prepare_level_update(update, operation_id=operation_id)
    submission = bind_level_update_submission(update, prepared)
    request_id = str(uuid4())
    request = prepared.execute_request(advertisement.credentials, request_id=request_id, timeout_ms=timeout_ms)
    request_bytes = _wire(request)
    validate_exchange_inputs(advertisement, request_bytes, client_path=client_path, timeout_ms=timeout_ms)
    _probe_connection(advertisement, client_path=client_path, timeout_ms=timeout_ms)
    record = SavedExecutionRecord.create_update_new(archive_path, prepared, submission)
    record.require_matches(prepared, level_update=submission)
    if project_store is not None:
        reservation = project_store.reserve_level_update(record,
            expected_checkpoint=update.baseline.checkpoint_digest if update.baseline is not None else None,
            expected_project_revision=expected_project_revision)
        if not reservation.inserted:
            raise PublicationRefusal("update_already_reserved", "reservation")
    response = exchange(advertisement, request_bytes, client_path=client_path, timeout_ms=timeout_ms)
    result = assess_connector_write_response(prepared, response, credentials=advertisement.credentials, request_id=request_id)
    return PublicationAttempt(record, request_id, result, prepared)


__all__ = ["PublicationRefusal", "PublicationAttempt", "publish_program", "publish_materialized_project",
           "publish_stored_project", "recover_stored_create", "cancel_stored_create",
           "resolve_stored_create_not_started", "publish_level_update"]
