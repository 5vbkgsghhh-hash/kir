"""Stored flat CREATE -> one explicit Level edit, with durable reconciliation.

This orchestration reuses the CREATE/Level stores and their evidence factories.
It never republishes CREATE, invents a new journal, migrates a store or commits
authored changes. Only publish_first_stored_level_update sends a model mutation.
Reconciliation only looks up that exact input, reads fields and records a local
settlement. A receipt, timeout or settlement failure never grants mutation retry.
"""
from dataclasses import dataclass, field, replace
import json
from uuid import uuid4

from kir.create_publication import bind_create_receipt, assess_create_identities
from kir.connector_result import assess_connector_saved_level_update_response
from kir.level_settlement import qualify_level_settlement
from kir.project import _digest, output_id
from kir.project_store import ProjectStore, StoreConflict, _CREATE_SCHEMAS
from kir.project_submission import SUBMISSION_SCHEMA, SELECTED_SUBMISSION_SCHEMA
from kir.revit_connector import RuntimeTarget, _uuid
from kir.revit_discovery import DiscoveryAdvertisement
from kir.revit_level_update import (_addresses, bind_original_publication,
                                     plan_level_elevation_update)
from kir.revit_observation import observe_elements
from kir.revit_transport import exchange
from kir.standalone_publish import _wire, recover_stored_create, publish_level_update
from kir.wire_json import exception_name


class StoredLevelUpdateError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class StoredLevelUpdateResult:
    """A scoped outcome, not a replay permit or whole-building acceptance."""
    stage: str
    diagnostic_code: str
    create_archive_digest: str | None = None
    update_archive_digest: str | None = None
    stream_id: str | None = None
    operation_id: str | None = None
    mutation_execution: str = "not_evaluated"
    scope_satisfied: bool = False
    settlement_digest: str | None = None
    storage_acknowledgement: str = "not_attempted"
    error_type: str | None = None
    record: object = field(default=None, repr=False)
    publication: object = field(default=None, repr=False)
    after: object = field(default=None, repr=False)

    @property
    def may_retry(self):
        return False

    def to_dict(self):
        return {name: getattr(self, name) for name in (
            "stage", "diagnostic_code", "create_archive_digest", "update_archive_digest",
            "stream_id", "operation_id", "mutation_execution", "scope_satisfied",
            "settlement_digest", "storage_acknowledgement", "error_type")} | {
            "may_retry": False,
            "claims": {"scope": "one_explicit_level_and_named_protected_fields",
                       "bim_acceptance": "not_established", "dependent_geometry": "not_evaluated",
                       "protected_geometry": "not_evaluated", "engineering": "not_evaluated",
                       "dispatch_permission": "none", "retry_permission": "none"}}


def _require(value, code):
    if not value:
        raise StoredLevelUpdateError(code)


def _inputs(store, advertisement, expected_target, expected_document_key, timeout_ms,
            bind_view, bind_selection):
    _require(type(store) is ProjectStore and not store.readonly and store.schema in _CREATE_SCHEMAS,
             "writable_create_and_level_store_required")
    _require(type(advertisement) is DiscoveryAdvertisement and type(expected_target) is RuntimeTarget
             and advertisement.credentials.target == expected_target, "explicit_original_runtime_required")
    _require(type(expected_document_key) is str and bool(expected_document_key.strip()),
             "explicit_document_key_required")
    _require(type(timeout_ms) is int and 1000 <= timeout_ms <= 300000, "invalid_level_update_timeout")
    _require(type(bind_view) is bool and type(bind_selection) is bool, "explicit_observation_policy_required")


def _target(record, expected_target, expected_document_key):
    binding = record.binding_dict()
    _require(binding["target"] == expected_target.to_dict()
             and binding["precondition"]["document_key"] == expected_document_key,
             "original_publication_target_mismatch")


def _failed(result, stage, error, **fields):
    # Exception text can contain paths, secrets or non-JSON data. A safe local
    # class name and an owned stage code suffice; never repr the remote error.
    code = "store_conflict" if isinstance(error, StoreConflict) else stage + "_failed"
    if isinstance(error, StoredLevelUpdateError):
        code = error.code
    return replace(result, stage=stage, diagnostic_code=code,
                   error_type=exception_name(error), **fields)


def _read(uids, advertisement, client_path, expected_target, expected_document_key,
          timeout_ms, bind_view, bind_selection):
    return observe_elements(uids, advertisement=advertisement, client_path=client_path,
        expected_target=expected_target, expected_document_key=expected_document_key,
        operation_id=str(uuid4()), bind_view=bind_view, bind_selection=bind_selection,
        timeout_ms=timeout_ms)


def _settle(store, result, response, request_id, *, expected_checkpoint, advertisement,
            client_path, expected_target, expected_document_key, timeout_ms, bind_view, bind_selection):
    # Entered only after a qualified committed receipt. A later read/SQL failure
    # must preserve that fact, not relabel the already committed setter unknown.
    record = result.record
    uids = tuple(row["element_identity"]["unique_id"]
                 for row in record.update_submission["original_publication"]["outputs"])
    try:
        after = _read(uids, advertisement, client_path, expected_target,
                      expected_document_key, timeout_ms, bind_view, bind_selection)
    except Exception as error:
        return _failed(result, "after_readback", error)
    result = replace(result, after=after)
    try:
        qualified = qualify_level_settlement(record, response, after=after,
            credentials=advertisement.credentials, request_id=request_id)
    except Exception as error:
        return _failed(result, "field_qualification", error)
    result = replace(result, scope_satisfied=True)
    try:
        saved = store.commit_level_settlement(qualified, expected_checkpoint=expected_checkpoint,
                                              expected_pending_archive=record.digest)
    except Exception as error:
        return _failed(result, "settlement", error, storage_acknowledgement=(
            "failed" if isinstance(error, StoreConflict) else "unknown"))
    return replace(result, stage="settled", diagnostic_code="level_fields_settled",
                   settlement_digest=saved.checkpoint_digest, storage_acknowledgement="recorded")


def publish_first_stored_level_update(store, *, create_archive_digest, proposed_revision_id,
        expected_head, target, protected_outputs, advertisement, client_path, archive_path,
        operation_id, expected_target, expected_document_key, timeout_ms=30000,
        bind_view=True, bind_selection=True) -> StoredLevelUpdateResult:
    """Send one newly planned setter, then read/settle its named field scope.

    The proposed elev-only revision must already be the expected authored head;
    its explicit handoff predates CREATE. Head is checked again atomically with
    native pending reservation. The original full source keeps unselected concept
    outputs. Unknown native or local outcomes retain durable input for reconcile.
    """
    _inputs(store, advertisement, expected_target, expected_document_key, timeout_ms, bind_view, bind_selection)
    for value, label in ((create_archive_digest, "create_archive_digest"),
                         (proposed_revision_id, "proposed_revision_id"), (expected_head, "expected_head")):
        _digest(value, label)
    operation_id = _uuid(operation_id, "operation_id")
    _require(proposed_revision_id == expected_head and store.head().revision_id == expected_head,
             "authored_head_changed")
    publication = store.get_create_publication(create_archive_digest)
    record = publication.record
    _require(publication.state == "reserved", "create_scope_released")
    _require(record.project_submission["schema"] in (SUBMISSION_SCHEMA, SELECTED_SUBMISSION_SCHEMA),
             "flat_create_submission_required")
    _target(record, expected_target, expected_document_key)
    selected, = _addresses([target])
    protected = _addresses(protected_outputs, empty=True)
    _require(selected not in protected, "protected_scope_overlap")
    required = (selected, *protected)
    submitted = {(row["instance_key"], row["output_key"]): row for row in record.project_submission["outputs"]}
    _require(all(address in submitted for address in required), "required_output_not_published")
    source = store.get(publication.source_revision)
    proposed = store.get(proposed_revision_id)
    _require(proposed.parent_revision == source.revision_id, "proposal_not_direct_child_of_publication")
    result = StoredLevelUpdateResult("create_lookup", "not_started",
        create_archive_digest=create_archive_digest, operation_id=operation_id)
    try:
        original = recover_stored_create(store, create_archive_digest, advertisement=advertisement,
                                         client_path=client_path, timeout_ms=timeout_ms)
        _require(original.result.binding_matches and original.result.receipt is not None,
                 "original_receipt_unavailable")
        bound = bind_create_receipt(record, original.result.raw_response,
            credentials=advertisement.credentials, request_id=original.request_id)
        identities = assess_create_identities(source, record, bound).to_dict()
        qualified = {row["output_id"]: row for row in identities["outputs"]}
        _require(all(qualified.get(output_id(source.project_id, *address), {}).get("state") == "created_here"
                     for address in required), "required_created_identity_unavailable")
        binding = bind_original_publication(source, record, original.result.raw_response,
            required_outputs=required, credentials=advertisement.credentials, request_id=original.request_id)
    except Exception as error:
        return _failed(result, "create_lookup", error)
    result = replace(result, stream_id=binding.digest)
    try:
        before = _read(tuple(row["element_identity"]["unique_id"] for row in binding.rows),
                       advertisement, client_path, expected_target, expected_document_key,
                       timeout_ms, bind_view, bind_selection)
        update = plan_level_elevation_update(source, proposed, publication=binding, observation=before,
                                             target=selected, protected_outputs=protected)
    except Exception as error:
        return _failed(result, "before_and_plan", error)
    try:
        attempt = publish_level_update(update, advertisement=advertisement, client_path=client_path,
            archive_path=archive_path, operation_id=operation_id, timeout_ms=timeout_ms,
            project_store=store, expected_project_revision=expected_head)
    except Exception as error:
        result = _failed(result, "publication", error, mutation_execution="unconfirmed")
        # Recover only a store-owned input with THIS operation ID; never adopt a
        # foreign pre-existing archive file or infer no-start from missing data.
        try:
            baseline = store.level_baseline(binding.digest)
            if baseline.pending_archive_digest is not None:
                retained = store.get_level_update_archive(baseline.pending_archive_digest)
                if retained.binding_dict()["operation_id"] == operation_id:
                    result = replace(result, record=retained, update_archive_digest=retained.digest)
        except Exception:
            pass  # Inaccessible storage does not negate possible execution.
        return result
    result = replace(result, publication=attempt, record=attempt.record,
        update_archive_digest=attempt.record.digest,
        mutation_execution=attempt.result.outcome.execution.value, stage="mutation_receipt",
        diagnostic_code=attempt.result.diagnostic_code)
    if not (attempt.result.binding_matches and attempt.result.outcome.execution.value == "committed"):
        return result
    return _settle(store, result, attempt.result.raw_response, attempt.request_id,
        expected_checkpoint=None, advertisement=advertisement, client_path=client_path,
        expected_target=expected_target, expected_document_key=expected_document_key,
        timeout_ms=timeout_ms, bind_view=bind_view, bind_selection=bind_selection)


def reconcile_stored_level_update(store, *, stream_id, expected_pending_archive,
        advertisement, client_path, expected_target, expected_document_key, timeout_ms=30000,
        bind_view=True, bind_selection=True) -> StoredLevelUpdateResult:
    """Lookup/read/settle an exact prior setter; never send that mutation again.

    Even coherent NOT_STARTED does not automatically release pending or retry:
    use the existing explicit Level no-start qualification/resolution workflow.
    An already recorded settlement is historical acknowledgement, not readback.
    """
    _inputs(store, advertisement, expected_target, expected_document_key, timeout_ms, bind_view, bind_selection)
    _digest(stream_id, "stream_id")
    _digest(expected_pending_archive, "expected_pending_archive")
    record = store.get_level_update_archive(expected_pending_archive)
    _target(record, expected_target, expected_document_key)
    original = record.update_submission["original_publication"]
    _require(original["binding_digest"] == stream_id, "level_stream_mismatch")
    baseline = store.level_baseline(stream_id)
    result = StoredLevelUpdateResult("receipt_lookup", "not_started",
        create_archive_digest=original["archive_digest"], update_archive_digest=record.digest,
        stream_id=stream_id, operation_id=record.binding_dict()["operation_id"], record=record,
        mutation_execution="unconfirmed")
    if baseline.pending_archive_digest is None and baseline.accepted is not None:
        _require(baseline.accepted["archive_digest"] == record.digest, "pending_level_update_changed")
        return replace(result, stage="already_settled", diagnostic_code="settlement_already_recorded",
            mutation_execution="committed", settlement_digest=baseline.checkpoint_digest,
            storage_acknowledgement="already_recorded")
    _require(baseline.pending_archive_digest == record.digest, "pending_level_update_changed")
    request_id = str(uuid4())
    try:
        request = record.receipt_request(advertisement.credentials, request_id=request_id)
        response = exchange(advertisement, _wire(request), client_path=client_path, timeout_ms=timeout_ms)
        assessment = assess_connector_saved_level_update_response(record, response,
            credentials=advertisement.credentials, request_id=request_id)
    except Exception as error:
        return _failed(result, "receipt_lookup", error)
    result = replace(result, mutation_execution=assessment.outcome.execution.value,
                     diagnostic_code=assessment.diagnostic_code)
    if not (assessment.binding_matches and assessment.outcome.execution.value == "committed"):
        return result
    return _settle(store, result, response, request_id, expected_checkpoint=baseline.checkpoint_digest,
        advertisement=advertisement, client_path=client_path, expected_target=expected_target,
        expected_document_key=expected_document_key, timeout_ms=timeout_ms,
        bind_view=bind_view, bind_selection=bind_selection)


__all__ = ["StoredLevelUpdateError", "StoredLevelUpdateResult",
           "publish_first_stored_level_update", "reconcile_stored_level_update"]
