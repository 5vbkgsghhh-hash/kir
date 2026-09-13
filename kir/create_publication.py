"""Bound CREATE receipt facts, distinct from native birth/ownership acceptance.

No transport or storage occurs here. The selected authenticated channel is a
caller prerequisite. Matching identity fields alone does not authenticate it.
Only a new bound response produces this in-process object; persisted claims
remain inert and never become dispatch or retry permission.
"""
from dataclasses import dataclass, field
import json

from kir.connector_result import (assess_connector_saved_create_response, validate_saved_receipt_binding,
                                  native_receipt_terminal_state)
from kir.project import _hash, _object, _thaw
from kir.saved_execution import SavedExecutionRecord, PROJECT_ARCHIVE_SCHEMA
from kir.project_submission import validate_submission_source
from kir.revit_observation import _identity
from kir.outcome import ExecutionState


CREATE_RECEIPT_SCHEMA = "kir-create-publication-receipt/1"
CREATE_IDENTITY_SCHEMA = "kir-create-identity-assessment/1"
_CLAIMS = {"evidence": "retained_bound_native_receipt_payload",
           "model_state": "not_fresh_observation", "native_element_mapping": "not_qualified",
           "global_ownership": "not_established", "dispatch_permission": "none", "retry_permission": "none"}


class CreatePublicationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True, init=False)
class BoundCreateReceipt:
    archive_digest: str
    receipt_digest: str
    _payload: object = field(repr=False)
    assessment: object = field(repr=False)
    _original_response: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use bind_create_receipt with a newly received bound response")

    def to_dict(self):
        return {**_thaw(self._payload), "receipt_digest": self.receipt_digest}

    @property
    def receipt(self):
        return _thaw(self._payload)["native_receipt"]

    @property
    def not_started(self):
        return self.assessment.diagnostic_code == "not_started"

    @property
    def terminal_state(self):
        return native_receipt_terminal_state(self.receipt)


def bind_create_receipt(record, response, *, credentials, request_id, recovery=False):
    """Preserve partial/unavailable result facts without inventing commit or IDs.

    Digest depends on the original receipt and archive, NOT the delivery request
    or the current recovery session. D1 assessment is a separate derived value,
    excluded from immutable receipt identity because registry contracts evolve.
    A response with no original receipt leaves reservation/recovery unresolved.
    """
    if type(record) is not SavedExecutionRecord or record.to_dict()["schema"] != PROJECT_ARCHIVE_SCHEMA:
        raise CreatePublicationError("project_archive_required", "checked Archive/2 input required")
    checked = SavedExecutionRecord._from_bytes(record._raw)
    if checked.digest != record.digest:
        raise CreatePublicationError("archive_mismatch", "record digest differs from retained input")
    assessment = assess_connector_saved_create_response(checked, response, credentials=credentials,
        request_id=request_id, recovery=recovery)
    if not assessment.binding_matches or assessment.receipt is None:
        raise CreatePublicationError("create_receipt_unbound", assessment.diagnostic_code)
    receipt = assessment.receipt
    validate_saved_receipt_binding(checked, receipt)
    payload = {"schema": CREATE_RECEIPT_SCHEMA, "archive_digest": checked.digest,
               "native_receipt": receipt, "claims": dict(_CLAIMS)}
    result = object.__new__(BoundCreateReceipt)
    object.__setattr__(result, "archive_digest", checked.digest)
    object.__setattr__(result, "receipt_digest", _hash({"archive_digest": checked.digest, "native_receipt": receipt}))
    object.__setattr__(result, "_payload", _object(payload, "create_receipt"))
    object.__setattr__(result, "assessment", assessment)
    # Private original delivery evidence, not a mutable derived assessment and
    # not part of the archive/native-receipt fact digest or serialized claims.
    object.__setattr__(result, "_original_response", assessment.raw_response)
    return result


def validate_create_receipt_claims(record, value):
    """Inert storage consistency; does not restore BoundCreateReceipt authority."""
    if type(record) is not SavedExecutionRecord or record.to_dict()["schema"] != PROJECT_ARCHIVE_SCHEMA:
        raise CreatePublicationError("project_archive_required", "checked Archive/2 input required")
    if type(value) is not dict or set(value) != {"schema", "archive_digest", "native_receipt", "claims", "receipt_digest"}:
        raise CreatePublicationError("invalid_create_receipt", "unknown or missing receipt fields")
    if (value["schema"] != CREATE_RECEIPT_SCHEMA or value["archive_digest"] != record.digest
            or value["claims"] != _CLAIMS
            or value["receipt_digest"] != _hash({"archive_digest": record.digest, "native_receipt": value["native_receipt"]})):
        raise CreatePublicationError("invalid_create_receipt", "receipt claims/digest differ")
    validate_saved_receipt_binding(record, value["native_receipt"])


@dataclass(frozen=True, slots=True, init=False)
class CreateIdentityAssessment:
    """Derived historical identity facts; not dispatch, ownership or BIM acceptance."""
    digest: str
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use assess_create_identities with a bound native receipt")

    def to_dict(self):
        return {**_thaw(self._payload), "assessment_digest": self.digest}


_CAPTURE_RESULTS = {"create_level": "level", "create_directshape": "element", "create_solid_blend": "element",
                    "create_wall": "wall", "create_floor": "element", "create_floor_by_contour": "element",
                    "create_room": "element"}
_ROW_CONTROL = frozenset({"ok", "success", "error", "err", "state", "status", "commit_status", "result",
                         "result_json", "result_error", "result_truncated", "truncated", "postcondition_violations",
                         "internal", "serialization_error", "receipt", "outcome", "started", "may_retry"})


def _primary_id(value):
    if (type(value) is str and value.isascii() and value.isdecimal() and 1 <= len(value) <= 19
            and value[0] != "0" and int(value) < (1 << 63)):
        return int(value)
    return None


def _supported_identity_output(output, retained):
    compiled = output["compiled_ops"]
    if (len(compiled) != 1 or compiled[0]["op_id"] != output["output_id"]
            or compiled[0]["op"] != output["source_op"] or retained is None):
        return False
    name = output["source_op"]
    reference = _CAPTURE_RESULTS.get(name)
    if name == "create_wall_type":
        kind = retained["payload"].get("host_kind", "wall")
        reference = {"wall": "wall_type", "floor": "floor_type"}.get(kind)
    return reference is not None and compiled[0]["result"] == {
        "identity_cardinality": "one", "identity_field": "id", "reference_kind": reference}


def _bound_create_assessment(record, bound_receipt):
    """Recheck original response and native content, not caller-edited outcome."""
    from kir.connector_result import (ConnectorResultAssessment, assess_saved_create_receipt,
                                      _json, _response_reports_receipt, MAX_FRAME_BYTES)
    if type(record) is not SavedExecutionRecord or type(bound_receipt) is not BoundCreateReceipt:
        raise CreatePublicationError("create_identity_inputs_required", "checked archive and newly bound receipt required")
    checked = SavedExecutionRecord._from_bytes(record._raw)
    if checked.digest != record.digest:
        raise CreatePublicationError("archive_mismatch", "record identity differs from retained bytes")
    validate_create_receipt_claims(checked, bound_receipt.to_dict())
    assessment = bound_receipt.assessment
    receipt = bound_receipt.receipt
    if (type(assessment) is not ConnectorResultAssessment or not assessment.binding_matches
            or assessment.archive_digest != checked.digest or assessment.receipt != receipt
            or bound_receipt.archive_digest != checked.digest):
        raise CreatePublicationError("create_assessment_mismatch", "D1 assessment and native fact identify different input/receipt")
    try:
        original, _ = _json(bound_receipt._original_response, MAX_FRAME_BYTES)
        if (original["receipt"] != receipt or original["context"] is not None
                or not _response_reports_receipt(original)):
            raise ValueError("original outer response did not confirm this receipt")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise CreatePublicationError("create_assessment_mismatch", "original response barrier does not qualify the native fact") from error
    derived = assess_saved_create_receipt(checked, receipt)
    if derived.outcome != assessment.outcome:
        raise CreatePublicationError("create_assessment_mismatch", "derived outcome differs from retained native content or outer barrier")
    return checked, receipt, derived


def require_create_not_started(record, bound_receipt):
    """Validate fresh bound no-start evidence; this function releases nothing.

    The store owns the explicit atomic resolution, not receipt presence or a
    caller's mutable derived assessment. No retry authority is returned.
    """
    _, _, derived = _bound_create_assessment(record, bound_receipt)
    if derived.outcome.execution is not ExecutionState.NOT_STARTED:
        raise CreatePublicationError("bound_create_not_started_required", "native content does not prove no-start")


def validate_create_not_started_claims(record, value):
    """Inert persisted consistency only; never restore fresh release authority."""
    from kir.connector_result import assess_saved_create_receipt
    validate_create_receipt_claims(record, value)
    assessment = assess_saved_create_receipt(record, value["native_receipt"])
    if assessment.outcome.execution is not ExecutionState.NOT_STARTED:
        raise CreatePublicationError("bound_create_not_started_required", "retained native claim is not coherent no-start")


def assess_create_identities(project, record, bound_receipt) -> CreateIdentityAssessment:
    """Qualify individual captured identities, never collapse partial CREATE to ok.

    D1 comes from the existing Connector assessment; existing result unwrapping
    and identity codecs are reused. A complete change manifest proves reported
    birth/survival only in this original committed receipt, not current state.
    Reused types are observed links, never exclusive ownership or update rights.
    Operation-end type_assignment and final type_id stay untouched in the raw
    receipt; this assessment does not reinterpret either as BIM acceptance.
    """
    checked, receipt, derived = _bound_create_assessment(record, bound_receipt)
    body = _identity_payload(project, checked, receipt, derived, bound_receipt.receipt_digest)
    report = object.__new__(CreateIdentityAssessment)
    object.__setattr__(report, "_payload", _object(body, "create_identity_assessment"))
    object.__setattr__(report, "digest", _hash(body))
    return report


def retained_create_identity_claims(project, record, receipt_claims) -> dict:
    """Recalculate inert historical identity claims from an exact saved fact.

    This does NOT restore BoundCreateReceipt, authenticate a transport response,
    create a fresh assessment object, observe today's model or authorize dispatch.
    The store must own the original input and previously admitted receipt. The
    returned detached dictionary only checks their retained cross-relations.
    """
    from kir.connector_result import assess_saved_create_receipt
    if type(record) is not SavedExecutionRecord:
        raise CreatePublicationError("project_archive_required", "checked Archive/2 required")
    checked = SavedExecutionRecord._from_bytes(record._raw)
    if checked.digest != record.digest:
        raise CreatePublicationError("archive_mismatch", "record identity differs from retained bytes")
    validate_create_receipt_claims(checked, receipt_claims)
    receipt = receipt_claims["native_receipt"]
    derived = assess_saved_create_receipt(checked, receipt)
    body = _identity_payload(project, checked, receipt, derived, receipt_claims["receipt_digest"])
    return {**body, "assessment_digest": _hash(body)}


def _identity_payload(project, checked, receipt, derived, receipt_digest):
    """One calculation for fresh qualification and inert historical checking."""
    from kir.bridge_result import saved_create_result_contract, _result_layers_for
    from kir.connector_result import _manifest
    validate_submission_source(project, checked.project_submission, selection_policy="retained")
    data = checked.to_dict()
    operations = {row["payload"]["id"]: row for row in data["plan_evidence"]["ops"]}
    diagnostics, payload = [], {}
    supported_profile = True
    try:
        expected = saved_create_result_contract(checked)
    except (ValueError, TypeError, KeyError):
        supported_profile = False
        expected = {}
        diagnostics.append({"code": "unsupported_create_profile"})
    try:
        result = json.loads(receipt["result_json"]) if receipt["result_json"] is not None else None
        layers = _result_layers_for(result, expected)
        if layers:
            payload = layers[-1]
        else:
            diagnostics.append({"code": "result_payload_unavailable"})
    except (ValueError, TypeError, RecursionError):
        diagnostics.append({"code": "result_payload_unavailable"})
    committed = derived.outcome.execution is ExecutionState.COMMITTED
    changes = receipt["changes"]
    try:
        _manifest(changes)  # Shared native manifest codec, not a second parser.
        complete = changes["truncated"] is False
        added, deleted = set(changes["added"]), set(changes["deleted"])
    except (ValueError, TypeError, KeyError):
        complete, added, deleted = False, set(), set()
        diagnostics.append({"code": "change_manifest_unavailable"})
    if not committed:
        diagnostics.append({"code": "execution_not_committed", "execution": derived.outcome.execution.value})
    if type(changes) is dict and changes.get("truncated") is True:
        diagnostics.append({"code": "change_manifest_truncated"})

    # Scan ALL rows, including unsupported/extra/refused ones. A good selected
    # row must not conceal another affirmative claim on the same native object.
    ids, uids, proofs, primary = {}, {}, {}, {}
    for oid, row in payload.items():
        if type(row) is not dict:
            continue
        number = _primary_id(row.get("id"))
        if number is not None:
            primary[oid] = number
            ids.setdefault(number, set()).add(oid)
        # Malformed affirmative captures cannot qualify, but their explicitly
        # reported IDs/UIDs can still contradict a neighbor. This only removes
        # qualification; it never manufactures an ElementIdentityProof.
        reported = row.get("element_identity")
        if row.get("element_identity_status") == "captured" and type(reported) is dict:
            reported_id, reported_uid = reported.get("element_id"), reported.get("unique_id")
            if type(reported_id) is int and 0 < reported_id < (1 << 63):
                ids.setdefault(reported_id, set()).add(oid)
            if type(reported_uid) is str and reported_uid.strip():
                uids.setdefault(reported_uid, set()).add(oid)
        try:
            proof = _identity(row)
            if proof is not None and not proof.unique_id.strip():
                proof = None
        except (ValueError, TypeError, KeyError):
            proof = None
        if proof is not None:
            proofs[oid] = proof
            ids.setdefault(proof.element_id, set()).add(oid)
            uids.setdefault(proof.unique_id, set()).add(oid)
    conflicts = set()
    for kind, owners in (("native_id", ids), ("unique_id", uids)):
        for owner_ids in owners.values():
            if len(owner_ids) > 1:
                participants = sorted(owner_ids)
                conflicts.update(participants)
                diagnostics.append({"code": "identity_conflict", "kind": kind, "op_ids": participants})
    extras = sorted(key for key in payload if key not in operations
                    and key not in {"ok", "commit_status", "error", "violations", "postcondition_violations", "revit_warnings", "revit_errors_resolved"})
    if extras:
        diagnostics.append({"code": "unexpected_result_keys", "keys": extras})
    outputs = []
    for output in checked.project_submission["outputs"]:
        oid = output["output_id"]
        row = payload.get(oid)
        proof = proofs.get(oid)
        entry = {key: output[key] for key in ("instance_key", "output_key", "output_id", "source_op")}
        entry.update(state="unavailable", element_identity=None, diagnostic=None)
        reason = None
        if oid in conflicts:
            entry["state"], reason = "conflict", "identity_conflict"
        elif not supported_profile or not _supported_identity_output(output, operations.get(oid)):
            reason = "producer_capture_unsupported"
        elif not committed:
            reason = "execution_not_committed"
        elif type(row) is not dict:
            reason = "result_row_missing" if oid not in payload else "result_row_malformed"
        elif "refused" in row or "refused_op_id" in row:
            if primary.get(oid) is not None or proof is not None or row.get("element_identity_status") == "captured":
                reason = "refused_row_reports_identity"
            elif (type(row.get("refused")) is not str or not row["refused"].strip()
                  or ("refused_op_id" in row and (type(row["refused_op_id"]) is not str or not row["refused_op_id"].strip()))):
                reason = "result_row_malformed"
            else:
                entry["state"], reason = "refused", "operation_refused"
        elif _ROW_CONTROL & row.keys():
            reason = "result_row_control_fields"
        elif proof is None:
            reason = "captured_identity_unavailable"
        elif primary.get(oid) != proof.element_id:
            reason = "primary_capture_mismatch"
        elif not complete:
            reason = "change_manifest_truncated"
        elif proof.element_id in deleted:
            reason = "identity_deleted_in_publication"
        elif output["source_op"] == "create_wall_type" and type(row.get("duplicated")) is not bool:
            reason = "type_creation_origin_unavailable"
        elif output["source_op"] == "create_wall_type" and row["duplicated"] is False:
            if proof.element_id in added:
                reason = "reused_type_reported_added"
            else:
                entry["state"] = "reused_existing"
        elif proof.element_id not in added:
            reason = "created_identity_not_added"
        else:
            entry["state"] = "created_here"
        entry["diagnostic"] = reason
        if entry["state"] in ("created_here", "reused_existing"):
            entry["element_identity"] = proof.to_dict()
        outputs.append(entry)
    body = {"schema": CREATE_IDENTITY_SCHEMA, "archive_digest": checked.digest,
        "receipt_digest": receipt_digest, "project": checked.project_submission["project"],
        "execution": data["binding"], "outcome": derived.outcome.to_dict(), "manifest_complete": complete,
        "outputs": outputs, "diagnostics": diagnostics,
        "claims": {"scope": "historical_captured_identity_assessment", "model_state": "not_fresh_observation",
            "global_ownership": "not_established", "exclusive_type_ownership": "not_established",
            "geometry": "not_evaluated", "layers": "not_evaluated", "engineering": "not_evaluated",
            "type_assignment": "not_evaluated", "dispatch_permission": "none", "retry_permission": "none"}}
    return body


# ═══════════════════════════════════════════════════════════════════════════
# NATIVE IDENTITY REPLACEMENT: AN EXPLICIT LEDGER, NOT A GUESS BY PROXIMITY
# ═══════════════════════════════════════════════════════════════════════════
#
# 🔴 WHAT WAS MEASURED (07.09.2026, probes in `.work/marathon-fable-20260907/ident/`).
# `Element.ChangeTypeId` is documented by the assemblies thus: "In rare cases, applying
# a change in type will result in a new element being created... In this
# situation the new element id is returned. Also, this element becomes
# invalid." That is, ONE authoring output's native identity can change
# WITHOUT the author's involvement. Emission already carries this fact in
# four fields (`emit_transaction_unit`: `replacement_element_id`; `authoring`:
# `new_element_created`, `returned_panel_id`, `panel_replaced`), yet they had
# **zero** consumers. The consequence is measured: a discrepancy report over
# a replacement used to give `authored_only=1 + observed_only=1` where a
# control without a replacement gives `both_agree=1` — that is, one building
# split in two as "the author lied" and "there is a stranger in the model".
#
# 🔴 WHY THE LEDGER IS AN EXPLICIT INPUT, NOT AN OUTPUT. Guessing at a
# replacement from an observation is impossible in principle: "the old uid is
# gone, but there is an undeclared new one nearby" describes a replacement
# and a deletion with an unrelated neighbour equally well. So the claim is
# supplied by the caller — by the same order, and for the same reason, as
# `ObservedRevision` for the discrepancy report. It is not taken on faith
# here either: CONFIRMATION requires ONE observation on ONE revision, in
# which the old uid answers `not_found` and the new one is `observed` with a
# captured identity. Any other outcome is a named refusal
# `replacement_unconfirmed`.
#
# 🔴 AN ADDITION, NOT A COVER-UP. The old link is not erased: it travels in
# the row in full (`original_identity`) and gets a `superseded_by`. The
# ledger only ever appends forward, a chain of replacements is resolved
# transitively, and a cycle is rejected — otherwise `effective_unique_id`
# would spin forever.
#
# WHAT IS NOT HERE. A sixth state for `assess_create_identities` is
# deliberately not introduced: `discrepancy._QUALIFIED` and
# `staged_create_projection` treat an unfamiliar state as unqualified
# SILENTLY, and a new name there would become a quiet loss of address. The
# replacement travels as a SEPARATE carrier with its own digest.

IDENTITY_REPLACEMENT_SCHEMA = "kir-create-identity-replacement/1"

#: A closed list of reasons. A reason that is not on the list is an
#: unfamiliar mechanism, not "other".
REPLACEMENT_REASONS = frozenset({"change_type_replacement"})

_REPLACEMENT_CLAIM_FIELDS = {"old_unique_id", "new_unique_id", "reason"}
_REPLACEMENT_CLAIMS = {
    "scope": "explicit_confirmed_native_identity_replacement",
    "confirmation": "one_revision_bound_observation_old_not_found_and_new_observed",
    "history": "append_only_original_link_retained_and_superseded",
    "current_model_state": "not_established", "bim_acceptance": "not_established",
    "type_definition": "not_evaluated", "geometry": "not_evaluated",
    "global_ownership": "not_established", "dispatch_permission": "none",
    "update_permission": "none", "retry_permission": "none",
}


@dataclass(frozen=True, slots=True, init=False)
class IdentityReplacementLedger:
    """Confirmed native identity replacements. An addition, not a rewrite."""

    digest: str
    _payload: object = field(repr=False)
    _pairs: tuple = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use assess_identity_replacement with a bound receipt and one observation")

    def to_dict(self):
        return {**_thaw(self._payload), "ledger_digest": self.digest}

    @property
    def replacements(self):
        return _thaw(self._payload)["replacements"]

    def superseded_by(self, unique_id):
        """Who this uid was DIRECTLY replaced by, or None. One step, not a chain."""
        return dict(self._pairs).get(unique_id)

    def to_bridge_dict(self):
        """The ledger in the discrepancy BRIDGE's shape (`discrepancy._resolve_replacements`).

        🔴 NARROW ON PURPOSE. The consumer on the graph side rejects an extra
        row key rather than making do with "whatever comes": a shape
        mismatch must surface as a refusal, not silently as a wrong bridge.
        So there are exactly three fields here, and the rest of the ledger
        (identities, confirmation revision, authoring output address) stays
        in `to_dict()` — the bridge does not need it and it would become an
        extra key for it.

        The chain is NOT collapsed: direct pairs travel as-is, and resolving
        A->B->C down to C is done by the bridge itself — otherwise the two
        sides would count the same thing by two different laws, and nothing
        would stop them from diverging.
        """
        return {"schema": IDENTITY_REPLACEMENT_SCHEMA,
                "replacements": [{"superseded_uid": row["original_identity"]["unique_id"],
                                  "superseded_by": row["superseded_by"], "reason": row["reason"]}
                                 for row in self.replacements]}

    def effective_unique_id(self, unique_id):
        """The live address: the chain walked to its end. An unfamiliar uid is its own."""
        chain = dict(self._pairs)
        seen, current = set(), unique_id
        while current in chain:
            if current in seen:  # A cycle is rejected at assembly time; this is a safeguard.
                raise CreatePublicationError("identity_replacement_cycle", "replacement chain loops")
            seen.add(current)
            current = chain[current]
        return current


def _replacement_claims(value):
    """A claim in ONE of two shapes: its own triple, or a unit receipt row.

    🔴 THE SHAPES ARE RECONCILED HERE, NOT BY RENAMING ALONG THE WAY. The
    transaction unit puts `identity_replacements` in the receipt as rows of
    `emit_transaction_unit.IDENTITY_REPLACEMENT_ROW`, and both sides take the
    schema name and field composition FROM ONE PLACE — the neighbouring
    allotment's constants are imported, not repeated as literals. A name
    rewritten along the way would be exactly the class of bug this ledger was
    built to prevent: a value named in one place, read from another, with
    nothing forcing them to match.

    A row with `identity_replaced: false` is NOT a claim: it says the type
    changed IN PLACE. Silently swallowing it would mean taking "there was no
    replacement" for "the replacement was confirmed"; the caller does the
    filtering, and a contested row is rejected here by name.
    """
    from kir.emit_transaction_unit import IDENTITY_REPLACEMENT_ROW, IDENTITY_REPLACEMENT_SCHEMA

    if type(value) not in (tuple, list) or not value:
        raise CreatePublicationError("identity_replacement_claims_invalid",
                                     "at least one explicit replacement claim required")
    claims = []
    for entry in value:
        if type(entry) is dict and set(IDENTITY_REPLACEMENT_ROW) <= set(entry):
            if entry["schema"] != IDENTITY_REPLACEMENT_SCHEMA:
                raise CreatePublicationError("identity_replacement_claims_invalid",
                                             "native replacement row carries a foreign schema")
            if entry["identity_replaced"] is not True:
                raise CreatePublicationError("identity_replacement_claims_invalid",
                                             "a native row reporting no replacement is not a claim")
            entry = {"old_unique_id": entry["old_unique_id"], "new_unique_id": entry["new_unique_id"],
                     "reason": "change_type_replacement"}
        if type(entry) is not dict or set(entry) != _REPLACEMENT_CLAIM_FIELDS:
            raise CreatePublicationError("identity_replacement_claims_invalid",
                                         "each claim needs exactly old_unique_id, new_unique_id, reason")
        old, new, reason = entry["old_unique_id"], entry["new_unique_id"], entry["reason"]
        if (type(old) is not str or not old.strip() or type(new) is not str or not new.strip()
                or old == new or reason not in REPLACEMENT_REASONS):
            raise CreatePublicationError("identity_replacement_claims_invalid",
                                         "claim identities must be distinct non-empty strings with a known reason")
        claims.append({"old_unique_id": old, "new_unique_id": new, "reason": reason})
    olds = [claim["old_unique_id"] for claim in claims]
    news = [claim["new_unique_id"] for claim in claims]
    if len(set(olds)) != len(olds) or len(set(news)) != len(news):
        raise CreatePublicationError("identity_replacement_claims_invalid",
                                     "one identity cannot be replaced twice in one ledger")
    return claims


def _observation_row(observation, unique_id):
    row = observation.rows.get(unique_id)
    return row if type(row) is dict else None


def assess_identity_replacement(project, record, bound_receipt, observation, *, claims) -> IdentityReplacementLedger:
    """Confirm claimed replacements with ONE observation; otherwise refuse by name.

    Confirmation is not "the new element looks similar", but two facts in
    ONE snapshot at ONE revision: the old uid answers `not_found`, the new
    one is `observed` with its own captured identity. The observation must
    belong to the same runtime and document as the publication, and must
    follow it by revision: a snapshot taken BEFORE the turn can say nothing
    about a replacement.

    The ledger grants neither a right to dispatch, nor BIM acceptance, nor a
    statement about the model's current state: it says exactly what this
    snapshot saw.
    """
    from kir.project import ProjectRevision
    from kir.revit_observation import ElementObservation, ElementObservationSet
    from kir.type_definition_observation import TypeDefinitionObservation

    if (type(project) is not ProjectRevision or type(record) is not SavedExecutionRecord
            or type(bound_receipt) is not BoundCreateReceipt
            or type(observation) not in (ElementObservation, ElementObservationSet, TypeDefinitionObservation)):
        raise CreatePublicationError("identity_replacement_inputs_required",
                                     "authored revision, archive, bound receipt and one observation required")
    entries = _replacement_claims(claims)
    assessment = assess_create_identities(project, record, bound_receipt)
    historical = assessment.to_dict()
    execution = historical["execution"]
    if (observation.target.to_dict() != execution["target"]
            or observation.precondition.document_key != execution["precondition"]["document_key"]):
        raise CreatePublicationError("observation_runtime_or_document_mismatch",
                                     "replacement evidence belongs to another runtime or document")
    if observation.precondition.revision <= execution["precondition"]["revision"]:
        raise CreatePublicationError("observation_not_after_publication",
                                     "an observation at or before the publication cannot confirm a replacement")

    # The address is taken from the link's common owner; a foreign uid gets no address.
    address, original = {}, {}
    for output in historical["outputs"]:
        if output["state"] in ("created_here", "reused_existing"):
            uid = output["element_identity"]["unique_id"]
            address[uid] = {key: output[key] for key in ("instance_key", "output_key", "output_id", "source_op")}
            original[uid] = output["element_identity"]

    rows, pairs = [], []
    for entry in entries:
        old, new, reason = entry["old_unique_id"], entry["new_unique_id"], entry["reason"]
        if old not in address:
            raise CreatePublicationError("replacement_old_identity_unqualified",
                                         "replaced identity is not a qualified output of this publication")
        if new in address:
            raise CreatePublicationError("identity_replacement_claims_invalid",
                                         "a replacement identity cannot already own an authored address")
        old_row = _observation_row(observation, old)
        if old_row is None:
            raise CreatePublicationError("replacement_unconfirmed",
                                         "the replaced identity was not requested in this observation")
        if old_row["status"] != "not_found":
            raise CreatePublicationError("replacement_unconfirmed",
                                         "the replaced identity is not reported gone at this revision")
        new_row = _observation_row(observation, new)
        if new_row is None:
            raise CreatePublicationError("replacement_unconfirmed",
                                         "the replacement identity was not requested in this observation")
        if new_row["status"] != "observed":
            raise CreatePublicationError("replacement_unconfirmed",
                                         "the replacement identity has no observed row at this revision")
        proof = _identity(new_row)
        if proof is None or proof.unique_id != new:
            raise CreatePublicationError("replacement_unconfirmed",
                                         "the replacement row carries no captured identity for this UID")
        # The replacement inherits the replaced one's address: the next link
        # in the chain can rely on it, and the old row stays intact.
        address[new], original[new] = address[old], proof.to_dict()
        rows.append({**address[old], "reason": reason, "original_identity": original[old],
                     "original_observed_status": old_row["status"],
                     "superseded_by": new, "replacement_identity": proof.to_dict(),
                     "confirmed_at_revision": observation.precondition.revision})
        pairs.append((old, new))

    # The confirmation scope comes in three kinds, and all three carry ONE
    # revision: a single query, a set of queries, and a type-definition
    # observation from a re-publication. The last is allowed ON PURPOSE:
    # otherwise `staged` could not confirm a replacement with the very
    # snapshot it uses to link.
    observation_input = ({"query_inputs_digest": observation.query_inputs_digest,
                          "scope": "multiple_queries_at_one_precondition"}
                         if type(observation) is ElementObservationSet else
                         {"operation_id": observation.operation_id, "source_sha256": observation.source_sha256})
    body = {"schema": IDENTITY_REPLACEMENT_SCHEMA, "archive_digest": record.digest,
            "receipt_digest": bound_receipt.receipt_digest,
            "identity_assessment_digest": assessment.digest,
            "project": record.project_submission["project"], "execution": execution,
            "observation": {**observation_input, "target": observation.target.to_dict(),
                            "precondition": observation.precondition.to_dict()},
            "replacement_count": len(rows), "replacements": rows,
            "claims": dict(_REPLACEMENT_CLAIMS)}
    ledger = object.__new__(IdentityReplacementLedger)
    object.__setattr__(ledger, "_payload", _object(body, "identity_replacement"))
    object.__setattr__(ledger, "_pairs", tuple(pairs))
    object.__setattr__(ledger, "digest", _hash(body))
    # Address resolution must TERMINATE; this is checked before the carrier is handed out.
    for old, _ in pairs:
        ledger.effective_unique_id(old)
    return ledger


def validate_identity_replacement_ledger(record, bound_receipt, value):
    """An inert sidecar check: it does NOT restore the freshness of a confirmation."""
    if type(value) is not dict or set(value) != {
            "schema", "archive_digest", "receipt_digest", "identity_assessment_digest", "project",
            "execution", "observation", "replacement_count", "replacements", "claims", "ledger_digest"}:
        raise CreatePublicationError("invalid_identity_replacement", "unknown or missing ledger fields")
    body = {key: value[key] for key in value if key != "ledger_digest"}
    if (value["schema"] != IDENTITY_REPLACEMENT_SCHEMA or value["archive_digest"] != record.digest
            or value["receipt_digest"] != bound_receipt.receipt_digest
            or value["replacement_count"] != len(value["replacements"])
            or value["claims"] != _REPLACEMENT_CLAIMS or value["ledger_digest"] != _hash(body)):
        raise CreatePublicationError("invalid_identity_replacement", "ledger claims or digest differ")
