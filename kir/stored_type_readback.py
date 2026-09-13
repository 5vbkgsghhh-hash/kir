"""Stored CREATE -> original receipt -> revision-bound native type-link report.

Only the existing publication/observation owners perform I/O. No CREATE resend,
schema upgrade, authoring edit, scope release or independent BIM acceptance.
The comparison is against the archived authoring revision, not a newer head.
"""
from dataclasses import dataclass, field

from kir.create_publication import (CreateIdentityAssessment, CreatePublicationError,
                                    IdentityReplacementLedger, assess_create_identities,
                                    assess_identity_replacement, bind_create_receipt)
from kir.create_type_discrepancy import (CreateTypeDiscrepancyError, CreateTypeDiscrepancyReport,
                                       assess_create_type_discrepancies)
from kir.project_store import ProjectStore, _CREATE_SCHEMAS
from kir.revit_connector import ConnectorPreparationError, RuntimeTarget
from kir.revit_discovery import DiscoveryAdvertisement
from kir.revit_observation import ObservationRefusal
from kir.revit_transport import ConnectorTransportError
from kir.standalone_publish import PublicationAttempt, recover_stored_create


class StoredTypeReadbackError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class StoredTypeReadback:
    publication: PublicationAttempt = field(repr=False)
    authored_head_seen: str
    diagnostic_code: str
    identities: CreateIdentityAssessment | None = field(default=None, repr=False)
    requested_unique_ids: tuple[str, ...] = ()
    observation: object = field(default=None, repr=False)
    discrepancy: CreateTypeDiscrepancyReport | None = field(default=None, repr=False)
    replacements: IdentityReplacementLedger | None = field(default=None, repr=False)

    def to_dict(self):
        submission = self.publication.record.project_submission
        return {
            "schema": "kir-stored-type-readback/1", "archive_digest": self.publication.record.digest,
            "source_project": submission["project"], "authored_head_seen_before_lookup": self.authored_head_seen,
            "head_seen_matches_source": self.authored_head_seen == submission["project"]["revision_id"],
            "diagnostic_code": self.diagnostic_code,
            "retained_receipt_digest": self.publication.retained_receipt_digest,
            "execution_outcome": self.publication.result.outcome.to_dict(),
            "identity_assessment": None if self.identities is None else self.identities.to_dict(),
            "observation_scope": {"policy": "all_qualified_selected_native_outputs_and_claimed_replacements/1",
                                  "requested_unique_ids": list(self.requested_unique_ids)},
            "identity_replacement": None if self.replacements is None else self.replacements.to_dict(),
            "type_discrepancy": None if self.discrepancy is None else self.discrepancy.to_dict(),
            "claims": {"authoring_basis": "archived_publication_not_current_head",
                "current_model_state": "not_established", "current_authored_head": "not_established",
                "identity_replacement": "confirmed_ledger_only_never_inferred_from_the_observation",
                "bim_acceptance": "not_established", "type_definition": "not_evaluated",
                "layers": "not_evaluated", "geometry": "not_evaluated",
                "dispatch_permission": "none", "update_permission": "none", "retry_permission": "none"},
        }


def readback_stored_create_types(store, archive_digest, *, advertisement, client_path,
        expected_target, expected_document_key, bind_view, bind_selection, timeout_ms=30000,
        replacement_claims=()):
    """Lookup this publication and read its UID scope without model mutation.

    The original receipt is retained in SQLite. Authoring head, output owners
    and store schema are not changed; native read queries may be journaled.

    The observation runtime must be the original one. Reassociation to another
    reopened model/runtime requires a separate proof and is not inferred from
    numeric IDs, document titles or receipt recovery in another process.
    Missing/unqualified identities remain in the identity assessment. A failed
    observation produces no invented empty snapshot or all-matched report.

    🔴 A DECLARED REPLACEMENT IS READ FROM ONE SNAPSHOT, NOT TWO. `replacement_
    claims` is the caller's claim (`{old_unique_id, new_unique_id, reason}`),
    and both of its sides fall within ONE observation scope: confirmation is
    exactly the fact that, in this snapshot, the old uid answers `not_found`
    and the new one answers `observed`. Two snapshots on different revisions
    cannot serve as confirmation: someone else's turn could have passed
    between them, and «disappeared» would stop meaning «replaced».
    An unconfirmed claim returns `replacement_unconfirmed` BY NAME, not the
    silent `consumer_observation_missing`.
    """
    from kir.revit_observation import observe_element_scope

    if (type(store) is not ProjectStore or store.readonly or store.schema not in _CREATE_SCHEMAS
            or type(advertisement) is not DiscoveryAdvertisement or type(expected_target) is not RuntimeTarget
            or advertisement.credentials.target != expected_target):
        raise StoredTypeReadbackError("explicit_stored_type_readback_inputs_required")
    if (type(bind_view) is not bool or type(bind_selection) is not bool
            or type(timeout_ms) is not int or not 1000 <= timeout_ms <= 300000):
        raise StoredTypeReadbackError("explicit_type_readback_policy_required")
    if type(replacement_claims) not in (tuple, list):
        raise StoredTypeReadbackError("explicit_replacement_claims_required")
    claims = tuple(replacement_claims)
    retained = store.get_create_publication(archive_digest)
    binding = retained.record.binding_dict()
    if (binding["target"] != expected_target.to_dict()
            or binding["precondition"]["document_key"] != expected_document_key):
        raise StoredTypeReadbackError("publication_observation_target_mismatch")
    source = store.get(retained.source_revision)
    head_seen = store.head().revision_id
    attempt = recover_stored_create(store, archive_digest, advertisement=advertisement,
                                   client_path=client_path, timeout_ms=timeout_ms)
    if not attempt.result.binding_matches or attempt.result.receipt is None:
        return StoredTypeReadback(attempt, head_seen, "original_receipt_unavailable")
    try:
        bound = bind_create_receipt(attempt.record, attempt.result.raw_response,
            credentials=advertisement.credentials, request_id=attempt.request_id)
        identities = assess_create_identities(source, attempt.record, bound)
    except CreatePublicationError as error:
        return StoredTypeReadback(attempt, head_seen, error.code)
    qualified = identities.to_dict()["outputs"]
    uids = tuple(dict.fromkeys(row["element_identity"]["unique_id"] for row in qualified
        if row["state"] in ("created_here", "reused_existing")))
    if not uids:
        return StoredTypeReadback(attempt, head_seen, "no_qualified_native_identities", identities)
    # Both sides of every claim ride within ONE scope: confirmation of the
    # replacement is a property of ONE snapshot, and there is nothing to
    # assemble it from two.
    for claim in claims:
        if type(claim) is not dict or "new_unique_id" not in claim:
            raise StoredTypeReadbackError("explicit_replacement_claims_required")
    uids = tuple(dict.fromkeys(uids + tuple(claim["new_unique_id"] for claim in claims
                                            if type(claim.get("new_unique_id")) is str)))
    try:
        observation = observe_element_scope(uids, advertisement=advertisement, client_path=client_path,
            expected_target=expected_target, expected_document_key=expected_document_key,
            bind_view=bind_view, bind_selection=bind_selection, timeout_ms=timeout_ms)
    except (ObservationRefusal, ConnectorPreparationError, ConnectorTransportError) as error:
        return StoredTypeReadback(attempt, head_seen, error.code, identities, uids)
    replacements = None
    if claims:
        try:
            replacements = assess_identity_replacement(source, attempt.record, bound, observation, claims=claims)
        except CreatePublicationError as error:
            return StoredTypeReadback(attempt, head_seen, error.code, identities, uids, observation)
    try:
        report = assess_create_type_discrepancies(source, attempt.record, bound, observation,
                                                  replacements=replacements)
    except CreateTypeDiscrepancyError as error:
        return StoredTypeReadback(attempt, head_seen, error.code, identities, uids, observation,
                                  None, replacements)
    return StoredTypeReadback(attempt, head_seen, "type_links_compared_at_observed_revision",
                              identities, uids, observation, report, replacements)


__all__ = ["StoredTypeReadback", "StoredTypeReadbackError", "readback_stored_create_types"]
