"""Pure, scoped consumer/type identity comparison after a CREATE publication.

The original bound receipt and parsed observation have existing owners;
selected-channel authentication remains a caller prerequisite.
This consumer performs no transport, planning, materialization, native execution
or persistence. Frozen Python carriers prevent accidental mutation, not hostile
in-process Python. A matching type link does not prove its layer definition,
geometry, original exclusive ownership, or permission to update it.
"""
from dataclasses import dataclass, field

from kir.contracts import ElementIdentityProof
from kir.create_publication import (BoundCreateReceipt, IdentityReplacementLedger,
                                    assess_create_identities)
from kir.project import ProjectRevision, _canonical, _hash, _object, _thaw
from kir.revit_observation import ElementObservation, ElementObservationSet
from kir.saved_execution import SavedExecutionRecord


TYPE_DISCREPANCY_SCHEMA = "kir-create-type-discrepancy/1"
_CONSUMERS = {"create_wall": "wall", "create_floor": "floor", "create_floor_by_contour": "floor"}
_STATES = ("matched", "mismatch", "unavailable", "conflict")
_CLAIMS = {
    "scope": "selected_direct_authored_consumer_type_links",
    "comparison": "revision_bound_observed_type_identity_vs_qualified_output_identity",
    "current_model_state": "not_established",
    "historical_type_assignment": "not_evaluated",
    "type_definition": "not_evaluated", "layers": "not_evaluated",
    "geometry": "not_evaluated", "engineering": "not_evaluated",
    "whole_bim_acceptance": "not_established", "exclusive_type_ownership": "not_established",
    "dispatch_permission": "none", "retry_permission": "none", "update_permission": "none",
    "identity_replacement": "confirmed_ledger_only_never_inferred_from_the_observation",
}


class CreateTypeDiscrepancyError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, init=False)
class CreateTypeDiscrepancyReport:
    digest: str
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use assess_create_type_discrepancies; a serialized report is not a parsed observation")

    def to_dict(self):
        return {**_thaw(self._payload), "report_digest": self.digest}


def _address(output):
    return {key: output[key] for key in ("instance_key", "output_key", "output_id", "source_op")}


def _direct(output, operation):
    compiled = output["compiled_ops"]
    return (len(compiled) == 1 and compiled[0]["op_id"] == output["output_id"]
            and compiled[0]["op"] == output["source_op"] and operation is not None)


def _effective(replacements, unique_id):
    """The live address and a replacement record, if the replacement is CONFIRMED by the ledger."""
    if replacements is None:
        return unique_id, None
    current = replacements.effective_unique_id(unique_id)
    if current == unique_id:
        return unique_id, None
    return current, {"original_unique_id": unique_id, "effective_unique_id": current,
                     "reason": next(row["reason"] for row in replacements.replacements
                                    if row["original_identity"]["unique_id"] == unique_id)}


def assess_create_type_discrepancies(project, record, bound_receipt, observation,
                                     *, replacements=None) -> CreateTypeDiscrepancyReport:
    """Compare every selected type-consumer output; unknowns keep their address.

    Qualified expected types may be newly created or read-only reused. Seed IDs
    are deliberately never used as expected consumer types. This first profile
    handles direct wall/floor/contour-floor creation with explicit by:ref types;
    other selectors, producers and expanded outputs get named unavailability.

    Observation target/document must be the original runtime, even when receipt
    recovery was delivered through another runtime. A later revision proves
    ordering within that runtime, not absence of intervening external changes.
    ElementObservation does not retain a timestamp: none is invented here.
    Re-rendering the same observation is allowed; matched refers only to its
    captured revision and does not establish the model's current state.

    🔴 AN IDENTITY REPLACEMENT IS READ ONLY FROM THE LEDGER. `ChangeTypeId`,
    in a rare documented case, builds a NEW element instead of editing in
    place, and then the original uid is dead. Without the ledger this used to
    yield `unavailable` with the `consumer_observation_missing` diagnostic —
    that is, a replacement could not be told apart from "was not read". The
    `kir-create-identity-replacement/1` ledger is supplied by the caller; it
    must belong to THIS publication and THIS observation, or the report would
    glue together two different snapshots. There is no guessing here: an
    undeclared replacement still remains an unknown with a name.
    """
    if (type(project) is not ProjectRevision or type(record) is not SavedExecutionRecord
            or type(bound_receipt) is not BoundCreateReceipt
            or type(observation) not in (ElementObservation, ElementObservationSet)):
        raise CreateTypeDiscrepancyError("typed_discrepancy_inputs_required")
    if replacements is not None:
        if type(replacements) is not IdentityReplacementLedger:
            raise CreateTypeDiscrepancyError("typed_discrepancy_inputs_required")
        ledger = replacements.to_dict()
        if (ledger["archive_digest"] != record.digest
                or ledger["receipt_digest"] != bound_receipt.receipt_digest):
            raise CreateTypeDiscrepancyError("identity_replacement_publication_mismatch")
        if (ledger["observation"]["target"] != observation.target.to_dict()
                or ledger["observation"]["precondition"] != observation.precondition.to_dict()):
            raise CreateTypeDiscrepancyError("identity_replacement_observation_mismatch")

    # Reuse the source/archive/receipt consistency and birth/reuse owner. No
    # fresh compiler/Plan is manufactured from retained source or plan claims.
    identity_assessment = assess_create_identities(project, record, bound_receipt)
    historical = identity_assessment.to_dict()
    execution = historical["execution"]
    if (observation.target.to_dict() != execution["target"]
            or observation.precondition.document_key != execution["precondition"]["document_key"]):
        raise CreateTypeDiscrepancyError("observation_runtime_or_document_mismatch")
    if observation.precondition.revision <= execution["precondition"]["revision"]:
        raise CreateTypeDiscrepancyError("observation_not_after_publication")

    submission = record.project_submission
    submitted = {output["output_id"]: output for output in submission["outputs"]}
    authored = {oid: output for _, output, oid in project.addressed_outputs()}
    retained = {row["payload"]["id"]: row["payload"] for row in record.to_dict()["plan_evidence"]["ops"]}
    identities = {output["output_id"]: output for output in historical["outputs"]}
    observed = observation.rows  # Detached, field-validated by its existing owner.
    rows, excluded = [], []

    for output in submission["outputs"]:
        oid = output["output_id"]
        source = authored[oid]
        raw = _thaw(source.operation)
        operation = retained.get(oid)
        expanded = [retained.get(item["op_id"], {}) for item in output["compiled_ops"]]
        if not (output["source_op"] in _CONSUMERS or "type" in raw
                or any(op.get("op") in _CONSUMERS or "type" in op for op in expanded)):
            excluded.append({**_address(output), "reason": "not_a_type_consumer"})
            continue

        row = {**_address(output), "state": "unavailable", "diagnostic": None,
               "expected_type_output": None, "consumer_publication_state": identities[oid]["state"],
               "type_publication_state": None, "original_consumer_identity": None,
               "original_expected_type_identity": None, "observed_consumer_identity": None,
               "observed_expected_type_identity": None, "observed_assigned_type_identity": None,
               "consumer_identity_replacement": None, "expected_type_identity_replacement": None}
        rows.append(row)

        if output["source_op"] not in _CONSUMERS or source.geometry is not None or not _direct(output, operation):
            row["diagnostic"] = "direct_consumer_profile_unsupported"
            continue
        selector = raw.get("type")
        if (type(selector) is not dict or set(selector) != {"by", "value"}
                or selector["by"] != "ref" or type(selector["value"]) is not str):
            row["diagnostic"] = "explicit_type_output_ref_required"
            continue
        if _canonical(selector) != _canonical(operation.get("type")):
            row["diagnostic"] = "authored_and_retained_type_ref_differ"
            continue
        target_id = selector["value"]
        target = submitted.get(target_id)
        if target is None:
            row["diagnostic"] = "type_output_not_submitted"
            continue
        row["expected_type_output"] = _address(target)
        type_source, type_operation = authored[target_id], retained.get(target_id)
        if (target["source_op"] != "create_wall_type" or type_source.geometry is not None
                or not _direct(target, type_operation)
                or type_operation.get("host_kind", "wall") != _CONSUMERS[output["source_op"]]):
            row["diagnostic"] = "native_type_output_profile_unsupported"
            continue

        consumer_fact, type_fact = identities[oid], identities[target_id]
        row["type_publication_state"] = type_fact["state"]
        if "conflict" in (consumer_fact["state"], type_fact["state"]):
            row.update(state="conflict", diagnostic="publication_identity_conflict")
            continue
        if consumer_fact["state"] != "created_here":
            row["diagnostic"] = "consumer_publication_identity_unqualified"
            continue
        if type_fact["state"] not in ("created_here", "reused_existing"):
            row["diagnostic"] = "type_publication_identity_unqualified"
            continue
        consumer_identity = ElementIdentityProof.from_dict(consumer_fact["element_identity"])
        type_identity = ElementIdentityProof.from_dict(type_fact["element_identity"])
        row["original_consumer_identity"] = consumer_identity.to_dict()
        row["original_expected_type_identity"] = type_identity.to_dict()
        # The address is resolved BEFORE reading the observation: there is no
        # point reading a dead uid, and the live one is known only from the
        # confirmed ledger.
        consumer_uid, consumer_replaced = _effective(replacements, consumer_identity.unique_id)
        type_uid, type_replaced = _effective(replacements, type_identity.unique_id)
        row["consumer_identity_replacement"] = consumer_replaced
        row["expected_type_identity_replacement"] = type_replaced
        current = observed.get(consumer_uid)
        expected = observed.get(type_uid)
        if current is None or expected is None:
            row["diagnostic"] = ("consumer_observation_missing" if current is None else "expected_type_observation_missing")
            continue
        if current["status"] != "observed" or expected["status"] != "observed":
            row["diagnostic"] = ("consumer_observation_unavailable" if current["status"] != "observed"
                                 else "expected_type_observation_unavailable")
            continue
        current_identity = observation.require_identity(consumer_uid)
        expected_identity = observation.require_identity(type_uid)
        row["observed_consumer_identity"] = current_identity.to_dict()
        row["observed_expected_type_identity"] = expected_identity.to_dict()
        typed = current["type_state"]
        if current["is_level"] or expected["is_level"]:
            row.update(state="conflict", diagnostic="observed_element_kind_conflicts_with_source")
        elif expected["type_state"]["status"] != "none":
            # This supported Wall/FloorType profile expects no own type. An
            # observed own type is outside it; an unreadable one is unknown.
            # Conversely, `none` alone is NOT proof of an ElementType class:
            # source producer and qualified original binding remain required.
            row["diagnostic"] = ("expected_type_profile_unsupported"
                if expected["type_state"]["status"] == "observed"
                else "expected_type_profile_unavailable")
        elif typed["status"] == "none":
            row.update(state="mismatch", diagnostic="consumer_has_no_type")
        elif typed["status"] != "observed":
            row["diagnostic"] = "consumer_type_observation_unavailable"
        else:
            assigned = ElementIdentityProof.from_dict(typed["element_identity"])
            row["observed_assigned_type_identity"] = assigned.to_dict()
            if assigned.unique_id != expected_identity.unique_id:
                row.update(state="mismatch", diagnostic="consumer_assigned_other_type")
            elif assigned != expected_identity:
                # The normal ElementObservation parser rejects this already;
                # never treat a contradictory pair as a numeric-ID match.
                row.update(state="conflict", diagnostic="revision_bound_type_identity_conflict")
            else:
                row.update(state="matched", diagnostic="revision_bound_type_link_matches_output")

    observation_input = ({"operation_id": observation.operation_id, "source_sha256": observation.source_sha256}
                         if type(observation) is ElementObservation else
                         {"query_inputs": observation.query_inputs,
                          "query_inputs_digest": observation.query_inputs_digest,
                          "scope": "multiple_queries_at_one_precondition"})
    body = {
        "schema": TYPE_DISCREPANCY_SCHEMA, "project": submission["project"],
        "submission_digest": submission["submission_digest"], "archive_digest": record.digest,
        "historical": {"receipt_digest": bound_receipt.receipt_digest,
            "identity_assessment_digest": identity_assessment.digest, "execution": execution,
            "timestamp_utc": bound_receipt.receipt["timestamp_utc"], "outcome": historical["outcome"],
            "manifest_complete": historical["manifest_complete"], "diagnostics": historical["diagnostics"]},
        "observation": {**observation_input, "target": observation.target.to_dict(),
            "precondition": observation.precondition.to_dict(),
            "timestamp_utc": None, "timestamp_status": "not_retained_by_observation_owner"},
        "identity_replacement": None if replacements is None else {
            "ledger_digest": replacements.digest, "replacement_count": len(replacements.replacements),
            "replacements": replacements.replacements},
        "selected_output_count": len(submitted), "consumer_count": len(rows),
        "counts": {state: sum(row["state"] == state for row in rows) for state in _STATES},
        "outputs": rows, "excluded_outputs": excluded, "claims": dict(_CLAIMS),
    }
    report = object.__new__(CreateTypeDiscrepancyReport)
    object.__setattr__(report, "_payload", _object(body, "create_type_discrepancy"))
    object.__setattr__(report, "digest", _hash(body))
    return report


__all__ = ["TYPE_DISCREPANCY_SCHEMA", "CreateTypeDiscrepancyError", "CreateTypeDiscrepancyReport",
           "assess_create_type_discrepancies"]
