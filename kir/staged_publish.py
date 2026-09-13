"""One explicit staged CREATE on a stored project, never a batch dispatcher.

The caller supplies a fresh typed projection: its qualified original receipts,
Level/type observation and exact C0 are not replaced by another context capture.
Existing compiler, archive and Store/8 owners validate source, imports and scope.
This module only connects those contracts to one first send.
"""
from __future__ import annotations

from pathlib import Path

from kir.project import _digest
from kir.project_store import ProjectStore, STAGED_CREATE_STORE_SCHEMA
from kir.revit_connector import _text, _uuid
from kir.revit_discovery import DiscoveryAdvertisement
from kir.saved_execution import SavedExecutionRecord
from kir.staged_create_projection import StagedCreateProjection, prepare_staged_create
from kir.staged_submission import bind_staged_project_submission
from kir.standalone_publish import (PublicationAttempt, PublicationRefusal, _frame_and_probe,
                                    _reserve_and_send)


def publish_staged_project(project_store: ProjectStore, projection: StagedCreateProjection, *,
                           expected_revision: str, advertisement: DiscoveryAdvertisement,
                           client_path: str | Path, expected_document_key: str, operation_id: str,
                           timeout_ms: int = 120000) -> PublicationAttempt:
    """Reserve a fresh staged input, send exactly once, retain a bound receipt.

    No implicit migration, context refresh, new operation UUID, retry, source
    splitting or global rollback is performed. Runtime/document/revision and
    isolation belong to the supplied projection. Actual emitted UTF-16 and the
    credential-bearing frame must fit the existing Connector/transport limits.
    Timeout bounds each exchange, not compilation or local storage work.

    Prior import archives AND qualified receipts must already be in this store.
    Reservation atomically checks their linkage, output ownership and authored
    head. A duplicate reservation is an acknowledgement, never a send permit.
    Errors after reservation leave the retained input for caller-known
    journal/operation lookup and ``standalone_publish.recover_stored_create``;
    recovery never resends CREATE. Local failure cannot undo a native commit.

    This is one explicit direct-Level/type/wall/floor stage, not an automatic
    sequencer. Bodies, giant-instance splitting and persisted identity replacement
    remain outside the underlying staged profile. Receipt success is not fresh
    model readback or independent BIM/engineering acceptance. A dependent next
    stage needs its own explicit qualified receipts and fresh observation.
    """
    if type(project_store) is not ProjectStore or type(projection) is not StagedCreateProjection:
        raise PublicationRefusal("explicit_store_and_staged_projection_required", "input")
    if project_store.readonly or project_store.schema != STAGED_CREATE_STORE_SCHEMA:
        raise PublicationRefusal("writable_staged_create_store_required", "input")
    if type(advertisement) is not DiscoveryAdvertisement:
        raise PublicationRefusal("explicit_advertisement_required", "input")
    if advertisement.credentials.target != projection.target:
        raise PublicationRefusal("staged_target_mismatch", "input")
    _text(expected_document_key, "expected_document_key")
    if expected_document_key != projection.precondition.document_key:
        raise PublicationRefusal("unexpected_document", "input")
    if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 300000:
        raise PublicationRefusal("invalid_timeout", "input")
    _digest(expected_revision, "expected_revision")
    operation_id = _uuid(operation_id, "operation_id")
    project = projection.partition.project
    # revision_id IS the digest of the body: comparing it is comparing the source.
    if (project.revision_id != expected_revision
            or project_store.head().revision_id != project.revision_id):
        raise PublicationRefusal("stored_source_mismatch", "input")

    # Revalidation and actual source budget belong to the existing preparation
    # owner. In particular, never acquire a newer C0 for this observed projection.
    prepared = prepare_staged_create(projection, operation_id=operation_id)
    submission = bind_staged_project_submission(projection, prepared)
    request_id, request_bytes = _frame_and_probe(prepared, advertisement, client_path=client_path,
                                                 timeout_ms=timeout_ms)
    record = SavedExecutionRecord.capture_project(prepared, submission)
    record.require_matches(prepared, submission=submission)
    return _reserve_and_send(prepared, record, request_id, request_bytes, advertisement=advertisement,
                             client_path=client_path, timeout_ms=timeout_ms, project_store=project_store,
                             expected_revision=expected_revision, submission=submission)


__all__ = ["publish_staged_project"]
