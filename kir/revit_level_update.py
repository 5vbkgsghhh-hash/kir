"""A bounded original-flat-create binding and one explicit authored Level edit.

No dispatch, source replay, storage mutation, recipe/kernel execution, or native
acceptance. Archived input/claims are never reconstructed as a PlannedProgram.
Only the NEW one-operation mutation is planned with current compiler contracts.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
import math

from kir import spec
from kir.connector_result import assess_connector_saved_write_response
from kir.contracts import ElementIdentityProof
from kir.emit_utils import cs_element_id_literal
from kir.midend import PlannedProgram
from kir.project import ProjectError, ProjectRevision, _canonical, _hash, _key, _object, _thaw, output_id
from kir.project_diff import diff_projects
from kir.revit_connector import ContextPrecondition, RuntimeTarget, PreparedExecution
from kir.revit_observation import ElementObservation, MAX_OBSERVATION_ELEMENTS, ObservationRefusal, _identity
from kir.saved_execution import PROJECT_ARCHIVE_SCHEMA, SavedExecutionRecord


_CAPTURE = {"create_level": "level", "create_directshape": "element", "create_solid_blend": "element"}
_SUPPLEMENTAL_CAPTURE = {"create_wall": "wall", "create_floor": "element",
                         "create_floor_by_contour": "element", "create_room": "element"}
#: The shape that can say "partial". `/1` could not, and a `/1` record therefore
#: asserts completeness by its own absence of the field — see the payload note.
ORIGINAL_BINDINGS_SCHEMA = "kir-original-publication-bindings/2"
LEGACY_ORIGINAL_BINDINGS_SCHEMA = "kir-original-publication-bindings/1"

_META = {"ok", "postcondition_violations", "revit_warnings", "revit_errors_resolved"}
_ROW_CONTROL = {"ok", "success", "error", "err", "state", "status", "commit_status", "result",
                "result_json", "result_error", "result_truncated", "truncated", "postcondition_violations"}
_ORIGINAL_CLAIMS = {"scope": "selected_original_create_captures", "native_project_attestation": "not_established",
    "global_ownership": "not_established", "engineering_acceptance": "not_established", "dispatch_permission": "none"}
_UPDATE_PLAN_CLAIMS = {"native_execution": "not_run", "engineering_acceptance": "not_established",
    "native_project_attestation": "not_established", "preservation": "not_checked_before_to_after",
    "dispatch_permission": "none", "recipe_execution": "not_run"}


class LevelUpdateRefusal(ProjectError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _require(condition, code, message):
    if not condition:
        raise LevelUpdateRefusal(code, message)


def _addresses(values, *, empty=False):
    _require(isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)),
             "invalid_output_scope", "expected explicit output address sequence")
    _require((0 if empty else 1) <= len(values) <= MAX_OBSERVATION_ELEMENTS,
             "invalid_output_scope", "output scope outside bounded observation size")
    result = []
    for item in values:
        _require(isinstance(item, (tuple, list)) and len(item) == 2,
                 "invalid_output_scope", "each address must be (instance_key, output_key)")
        try:
            pair = (_key(item[0], "instance_key"), _key(item[1], "output_key"))
        except ProjectError as error:
            raise LevelUpdateRefusal("invalid_output_scope", str(error)) from error
        _require(pair not in result, "duplicate_output_scope", "output address repeats")
        result.append(pair)
    return tuple(result)


def _source_matches(project, submission):
    _require(type(project) is ProjectRevision, "source_project_required", "expected exact source ProjectRevision")
    from kir.project_submission import (SUBMISSION_SCHEMA, SELECTED_SUBMISSION_SCHEMA,
                                        validate_submission_source)
    _require(submission["schema"] in (SUBMISSION_SCHEMA, SELECTED_SUBMISSION_SCHEMA),
             "original_profile_unsupported", "only whole or selected flat CREATE source is supported")
    if submission["schema"] == SELECTED_SUBMISSION_SCHEMA:
        try:
            validate_submission_source(project, submission, selection_policy="retained")
        except ValueError as error:
            raise LevelUpdateRefusal("source_project_mismatch", "selected source association differs") from error
        return
    _require(submission["project"] == {"project_id": project.project_id, "schema": project.schema,
                                      "revision_id": project.revision_id},
             "source_project_mismatch", "source is not the archived selected revision")
    expected_instances = [{"instance_key": item.key, "module_key": item.module_key,
        "instance_snapshot_digest": _hash(item.to_dict()), "module_definition_digest": item.module_digest}
        for item in project.instances]
    _require(_canonical(submission["instances"]) == _canonical(expected_instances),
             "source_project_mismatch", "instance/parameter/metadata/module ownership differs")
    addresses = project.addressed_outputs()
    _require(len(addresses) == len(submission["outputs"]), "source_project_mismatch", "output coverage differs")
    for index, ((instance, output, oid), row) in enumerate(zip(addresses, submission["outputs"], strict=True)):
        expected = {"source_index": index, "instance_key": instance.key, "output_key": output.key,
                    "module_key": instance.module_key, "output_id": oid, "source_op": output.operation["op"],
                    "authored_output_digest": _hash(output.to_dict())}
        _require(all(row.get(key) == value for key, value in expected.items()),
                 "source_project_mismatch", "named output/source address differs")
        _require((output.geometry is not None) == ("body" in row), "source_project_mismatch", "body source differs")
        if output.geometry is not None:
            _require(row["body"]["descriptor"] == output.geometry.to_dict(),
                     "source_project_mismatch", "body bundle/shape descriptor differs")


def _native_id(value):
    _require(type(value) is str and value.isascii() and value.isdecimal() and 1 <= len(value) <= 19,
             "original_result_profile_unsupported", "flat create rows require canonical positive decimal id")
    number = int(value)
    _require(0 < number < (1 << 63) and str(number) == value,
             "original_result_profile_unsupported", "native id is not canonical positive int64")
    return number


def _captured(row):
    _require({"element_identity", "element_identity_status", "element_identity_reason"} <= set(row),
             "original_identity_unavailable", "identity status fields are incomplete")
    try:
        proof = _identity(row)  # existing exact wire/status reader, not query ownership inference
    except ValueError as error:
        raise LevelUpdateRefusal("original_identity_unavailable", str(error)) from error
    if proof is None:
        return None
    _require(proof.unique_id.strip() and proof.element_id == _native_id(row.get("id")),
             "original_identity_mismatch", "capture and original primary result id differ")
    return proof


def _capture_is_creation(operation, row):
    """Classify extra observation without extending the legacy required scope.

    A returned type may have been reused. Its identity is still checked for
    contradictions, but is never promoted to original-created ownership here.
    """
    payload = operation["payload"]
    name = payload["op"]
    kind = _CAPTURE.get(name, _SUPPLEMENTAL_CAPTURE.get(name))
    created = True
    if name == "create_wall_type":
        host_kind = payload.get("host_kind", "wall")
        _require(type(host_kind) is str and host_kind in ("wall", "floor"),
                 "original_profile_unsupported", "only wall/floor type captures are interpreted")
        kind = host_kind + "_type"
        _require(type(row.get("duplicated")) is bool, "original_creation_unconfirmed",
                 "a captured type requires an explicit boolean duplicated result")
        created = row["duplicated"]
    _require(kind is not None and operation["result"].get("reference_kind") == kind,
             "original_profile_unsupported", "capture is not supported by this archived create contract")
    return created


@dataclass(frozen=True, slots=True, init=False)
class OriginalPublicationBindings:
    digest: str
    target: RuntimeTarget
    document_key: str
    project_id: str
    source_revision_id: str
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use bind_original_publication; serialized claims are not new native evidence")

    @property
    def rows(self):
        """Only the outputs that actually bound. A refused row is not a mapping."""
        return _thaw(self._payload)["outputs"]

    @property
    def refused_rows(self):
        """Required outputs that did NOT bind, each with its own named state.

        Carried in the retained payload since schema /2 (13.09.2026), so
        `digest` covers it: a stored submission can now prove WHAT WAS REFUSED,
        not only that the outputs it lists bound. A `/1` record has no such
        field and is read as the complete binding it claimed to be.
        """
        return _thaw(self._payload).get("refused_outputs", [])

    @property
    def completeness(self):
        """`complete` or `partial` — never silently one pretending to be the other."""
        return _thaw(self._payload).get("binding_completeness", "complete")

    def to_dict(self):
        return {**_thaw(self._payload), "binding_digest": self.digest}


def bind_original_publication(project, record, response, *, required_outputs,
                              credentials, request_id, recovery=False) -> OriginalPublicationBindings:
    """Qualify selected original captures in one narrow flat-create receipt.

    This does not attest all BIM results or unique authorship among independent
    archive paths. Source/recipe ownership remains the selected caller record.
    Required body-owned DirectShape outputs are allowed; their saved descriptor
    is matched, without rematerializing their BRep or trusting a new preview.
    Supplementary wall/floor/type observations do not extend the legacy required
    output profile. Reused types may coexist, but are not original creations.
    """
    required = _addresses(required_outputs)
    _require(type(record) is SavedExecutionRecord and record.to_dict()["schema"] == PROJECT_ARCHIVE_SCHEMA,
             "project_archive_required", "original mapping requires checked Archive/2")
    data = record.to_dict()
    submission = data["project_submission"]
    _source_matches(project, submission)
    _require(project.ir_version == data["plan_evidence"]["ir_version"] == spec.IR_VERSION,
             "original_profile_unsupported", "current flat-create profile does not reinterpret another IR version")
    assessed = assess_connector_saved_write_response(record, response, credentials=credentials,
                                                      request_id=request_id, recovery=recovery)
    _require(assessed.result_available and assessed.binding_matches, "original_receipt_unavailable",
             "original response does not match retained execution input")
    receipt, result = assessed.receipt, assessed.result
    operations = data["plan_evidence"]["ops"]
    _require(not data["planned_units"] and not data["plan_evidence"]["allow_destructive"]
             and all(op.get("effect") == "create" and op.get("nested_contracts") == []
                     and type(op.get("result")) is dict and type(op.get("provenance")) is dict
                     and op["result"].get("identity_cardinality") == "one"
                     and op["result"].get("identity_field") == "id"
                     and op["provenance"].get("macro_name") is None for op in operations),
             "original_profile_unsupported", "first original-flat-create profile excludes macros/groups/networks/units/mutations")
    by_op = {op["payload"]["id"]: op for op in operations}
    _require(set(result) - _META == set(by_op) and result.get("ok") is True,
             "original_result_profile_unsupported", "expected complete direct flat result with exact ok=true, no legacy wrapper")
    _require("postcondition_violations" not in result or result["postcondition_violations"] == [],
             "original_postconditions_unconfirmed", "original postconditions are violated or malformed")
    for name in ("revit_warnings", "revit_errors_resolved"):
        _require(name not in result or type(result[name]) is list,
                 "original_result_profile_unsupported", "native warnings/resolutions must be arrays")
    _require(not result.get("revit_errors_resolved"), "original_resolution_unreviewed", "native error resolution needs separate review")
    changes = receipt["changes"]
    _require(changes["truncated"] is False, "original_changes_incomplete", "original manifest must be complete")
    added, deleted = set(changes["added"]), set(changes["deleted"])
    primary_ids, captures, seen_ids, seen_uids = {}, {}, {}, {}
    for oid, operation in by_op.items():
        row = result[oid]
        _require(type(row) is dict and not (_ROW_CONTROL & set(row)),
                 "original_result_profile_unsupported", "per-op failure/control/wrapper is not a qualified create result")
        native_id = _native_id(row.get("id"))
        _require(native_id not in primary_ids, "original_ownership_conflict", "different create outputs returned one native id")
        primary_ids[native_id] = oid
        if "element_identity" in row or "element_identity_status" in row or "element_identity_reason" in row:
            # Missing/unavailable captures outside requested scope stay optional;
            # any affirmative capture is checked globally for contradictions.
            proof = _captured(row)
            if proof is None:
                continue
            created = _capture_is_creation(operation, row)
            _require(proof.element_id not in seen_ids and proof.unique_id not in seen_uids,
                     "original_ownership_conflict", "one original id/UID has multiple output owners")
            seen_ids[proof.element_id] = seen_uids[proof.unique_id] = oid
            if created:
                _require(proof.element_id in added and proof.element_id not in deleted,
                         "original_creation_unconfirmed", "captured element is not a surviving original added element")
            else:
                _require(proof.element_id not in added and proof.element_id not in deleted,
                         "original_creation_unconfirmed", "reused type identity contradicts the creation/deletion manifest")
            if operation["payload"]["op"] in _CAPTURE:
                captures[oid] = proof
    by_address = {(row["instance_key"], row["output_key"]): row for row in submission["outputs"]}
    rows, refused = [], []
    for address in required:
        # 🔴 E5 (audit 06.09.2026): ONE OUTPUT'S FAILURE USED TO DESTROY ALL THE
        # MAPPINGS. Every check below was a `_require` that raised, so a single
        # unsupported or uncaptured output threw away the identities of every
        # OTHER output in the same publication — elements really created in the
        # model, left with no mapping FOREVER, because a neighbour was not
        # qualified. The audit named it a P1 boundary: "частичный успех = потеря
        # идентичности".
        #
        # Each row now judges ITSELF and says so by name. A row that cannot bind
        # is recorded with its reason and does not touch its neighbours; the
        # binding carries `partial` when some bound and some did not. The only
        # whole-binding refusal left is "not one row bound" — a mapping of
        # nothing is not a partial success, it is an absence.
        #
        # WHAT THIS DOES NOT DO, ON PURPOSE. It does not widen the required
        # scope: a supplemental wall/floor/room capture is still not a legacy
        # required output, and asking for one is still refused — now per row,
        # by the same name (`output_unsupported`), instead of by exception.
        # That boundary was a decision, not an accident (see the docstring).
        row = by_address.get(address)
        if row is None:
            refused.append({"address": list(address), "state": "original_output_missing",
                            "reason": "required source output is absent"})
            continue
        compiled = row["compiled_ops"]
        if not (row["source_op"] in _CAPTURE and len(compiled) == 1
                and compiled[0]["op_id"] == row["output_id"] and compiled[0]["op"] == row["source_op"]
                and compiled[0]["result"] == {"identity_cardinality": "one", "identity_field": "id",
                                              "reference_kind": _CAPTURE[row["source_op"]]}):
            refused.append({"address": list(address), "output_id": row.get("output_id"),
                            "source_op": row.get("source_op"), "state": "original_output_unsupported",
                            "reason": "required output must be a direct one-to-one supported create"})
            continue
        oid = compiled[0]["op_id"]
        if oid not in captures:
            refused.append({"address": list(address), "output_id": row.get("output_id"),
                            "source_op": row.get("source_op"), "compiled_op_id": oid,
                            "state": "original_identity_unavailable",
                            "reason": "required output has no original captured proof"})
            continue
        rows.append({key: row[key] for key in ("instance_key", "output_key", "output_id", "source_op",
                    "authored_output_digest", "module_key")} | {"compiled_op_id": oid,
                    "element_identity": captures[oid].to_dict()})
    _require(bool(rows), "original_binding_empty",
             "not one required output bound: " + ", ".join(sorted({r["state"] for r in refused})))
    # 🔴 SCHEMA /2, NOT AN ADDITIVE /1, AND THE REASON IS THE SCHEMA'S JOB.
    # E5 (13.09.2026) made a binding able to be PARTIAL. On 13.09 the partiality
    # lived only on the object, so `digest` did not cover it: a retained
    # submission could prove which outputs bound and could NOT prove which were
    # refused — a record that silently loses the fact it was incomplete. Adding
    # the fields under the SAME version would leave two different shapes both
    # calling themselves /1, which is precisely the ambiguity a version exists
    # to remove: a reader could not tell "no refusals" from "written before the
    # field existed". So the shape that carries refusals is /2, and a /1 record
    # is read as what it actually asserted — complete, nothing refused.
    payload = {"schema": ORIGINAL_BINDINGS_SCHEMA, "profile": "original-flat-create/1",
        "project": submission["project"], "archive_digest": record.digest,
        "submission_digest": submission["submission_digest"], "receipt_digest": _hash(receipt),
        "execution": data["binding"], "outputs": rows,
        "refused_outputs": refused,
        "binding_completeness": "complete" if not refused else "partial",
        "warnings": result.get("revit_warnings", []),
        "claims": dict(_ORIGINAL_CLAIMS)}
    bound = object.__new__(OriginalPublicationBindings)
    for key, value in {"digest": _hash(payload), "target": RuntimeTarget(**data["binding"]["target"]),
        "document_key": data["binding"]["precondition"]["document_key"], "project_id": project.project_id,
        "source_revision_id": project.revision_id, "_payload": _object(payload, "original_publication")}.items():
        object.__setattr__(bound, key, value)
    return bound


@dataclass(frozen=True, slots=True, init=False)
class LevelElevationUpdatePlan:
    planned: PlannedProgram
    target: RuntimeTarget
    precondition: ContextPrecondition
    expected_identities: tuple[ElementIdentityProof, ...]
    publication: OriginalPublicationBindings | None = field(repr=False)
    baseline: object = field(repr=False)
    before_observation: ElementObservation = field(repr=False)
    _report: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use plan_level_elevation_update; a report is not a fresh plan")

    def to_dict(self):
        return _thaw(self._report)


    @property
    def original_binding(self):
        """Immutable original lineage, never relabelled as the current revision."""
        return self.publication.to_dict() if self.publication is not None else self.baseline.original


def plan_level_elevation_update(base, proposed, *, publication=None, baseline=None, observation, target,
                                protected_outputs) -> LevelElevationUpdatePlan:
    """Plan one Level edit from original publication OR a settled scoped baseline.

    A loaded baseline is historical data, not an observation or send permission.
    A fresh parsed observation is required and the store must still reserve the
    submitted operation against the checkpoint before dispatch.
    """
    _require(type(base) is ProjectRevision and type(proposed) is ProjectRevision
             and type(observation) is ElementObservation,
             "level_update_inputs_required", "expected exact snapshots and parsed observation")
    if baseline is None:
        _require(type(publication) is OriginalPublicationBindings,
                 "level_update_inputs_required", "original publication or recorded settled baseline required")
        original = publication.to_dict()
        expected_base = publication.source_revision_id
    else:
        from kir.project_realization_store import RecordedLevelBaseline
        _require(publication is None and type(baseline) is RecordedLevelBaseline,
                 "level_update_inputs_required", "choose one original publication OR recorded baseline")
        _require(baseline.checkpoint_digest is not None and baseline.accepted is not None,
                 "level_baseline_unsettled", "first update requires its original publication")
        _require(baseline.pending_archive_digest is None,
                 "level_update_pending", "reconcile the reserved operation before another update")
        original = baseline.original
        expected_base = baseline.baseline_revision
    selected, = _addresses([target])
    protected = _addresses(protected_outputs, empty=True)
    _require(selected not in protected, "protected_scope_overlap", "target cannot also be protected")
    _require(base.project_id == original["project"]["project_id"] and base.revision_id == expected_base,
             "source_project_mismatch", "base must match the selected original or settled revision")
    _require(proposed.parent_revision == base.revision_id, "level_update_not_direct_child", "proposed must be a direct child")
    rows = {(row["instance_key"], row["output_key"]): row for row in original["outputs"]}
    _require(set(rows) == {selected, *protected}, "publication_scope_mismatch", "binding scope must exactly cover target and protection")
    addresses = {(instance.key, output.key): (instance, output, oid)
                 for instance, output, oid in base.addressed_outputs()}
    after = {(instance.key, output.key): (instance, output, oid)
             for instance, output, oid in proposed.addressed_outputs()}
    _require(selected in addresses and selected in after, "level_output_missing", "selected output must exist in both snapshots")
    instance, old, oid = addresses[selected]
    _, new, _ = after[selected]
    module = next(item for item in base.modules if item.key == instance.module_key)
    _require(module.owner == "explicit" and module.recipe is None, "level_output_not_explicit", "sealed recipe outputs require explicit authoring handoff first")
    _require(old.geometry is None and new.geometry is None and old.operation["op"] == new.operation["op"] == "create_level",
             "level_output_unsupported", "target must be a direct authored Level")
    old_op, new_op = _thaw(old.operation), _thaw(new.operation)
    old_value, new_value = old_op.get("elev_mm"), new_op.get("elev_mm")
    param = next(item for item in spec.OPS["create_level"].params if item.name == "elev_mm")
    _require(all(type(value) in (int, float) and param.min_val <= value <= param.max_val
                 and math.isfinite(value) for value in (old_value, new_value)),
             "invalid_level_elevation", "level elevation must satisfy the current finite mm contract")
    _require(old_value != new_value, "level_elevation_unchanged", "no numeric elevation change")
    _require(_canonical({**new_op, "elev_mm": old_value}) == _canonical(old_op),
             "level_update_has_other_changes", "only elev_mm may change")
    replacement = replace(instance, outputs=tuple(new if output.key == old.key else output for output in instance.outputs))
    expected = base.replace_instance(replacement, expected_revision=base.revision_id)
    _require(expected.dumps() == proposed.dumps(), "level_update_has_other_changes", "another output/parameter/metadata/owner/order field changed")
    difference = diff_projects(base, proposed)
    delta = difference.to_dict()
    _require(delta["analysis"]["explicit_reference_analysis_complete"], "level_dependency_analysis_incomplete", "unknown dependencies need another planner")
    _require(not ({addresses[address][2] for address in protected} & set(difference.affected)),
             "protected_scope_affected", "explicitly affected outputs cannot be promised protected")
    _require(observation.target.to_dict() == original["execution"]["target"]
             and observation.precondition.document_key == original["execution"]["precondition"]["document_key"],
             "observation_document_mismatch", "original runtime and open-document identity must match")
    observed = observation.rows
    _require(set(observed) == {row["element_identity"]["unique_id"] for row in rows.values()},
             "observation_scope_mismatch", "all and only required original UIDs must be observed")
    if baseline is not None:
        from kir.level_update_acceptance import _fields
        settled_after = baseline.accepted["after"]
        _require(observation.target.to_dict() == settled_after["target"]
                 and observation.precondition.document_key == settled_after["precondition"]["document_key"]
                 and observation.precondition.revision >= settled_after["precondition"]["revision"],
                 "level_baseline_observation_stale", "observation must follow the accepted native checkpoint")
        _require(set(observed) == set(settled_after["rows"]),
                 "level_baseline_scope_mismatch", "checkpoint and fresh observation scopes differ")
        _require(all(_fields(observed[uid]) is not None and
                     _canonical(_fields(observed[uid])) == _canonical(_fields(settled_after["rows"][uid]))
                     for uid in observed), "level_baseline_fields_changed",
                 "observed fields changed since settlement; reconcile before another edit")
    guards = {}
    try:
        for row in rows.values():
            uid = row["element_identity"]["unique_id"]
            identity = observation.require_identity(uid)
            guards[identity.element_id] = identity
            typed = observed[uid]["type_state"]
            _require(typed["status"] in {"none", "observed"}, "observed_type_unavailable", "required type identity is incomplete")
            if typed["status"] == "observed":
                proof = ElementIdentityProof.from_dict(typed["element_identity"])
                guards[proof.element_id] = proof
        level_row = observation.require_level(rows[selected]["element_identity"]["unique_id"])
    except ObservationRefusal as error:
        raise LevelUpdateRefusal("observation_incomplete", str(error)) from error
    level, parameter = level_row["level"], level_row["level"]["elevation_parameter"]
    _require(level["elevation_base"] == 0 and parameter["storage_type"] == "Double"
             and parameter["is_read_only"] is False and parameter["name_match_count"] == 1
             and parameter["name_resolves_builtin"] is True and parameter["builtin"] == "LEVEL_ELEV",
             "level_parameter_unsupported", "requires Project basis and one writable observed builtin name")
    baseline_tol = spec.OPS["create_level"].tolerances["elevation_mm"]
    _require(abs(level["project_elevation_mm"] - old_value) <= baseline_tol
             and abs(level["reported_elevation_mm"] - old_value) <= baseline_tol
             and abs(parameter["value_internal_feet"] * 304.8 - old_value) <= baseline_tol,
             "level_baseline_mismatch", "observed project/reported/parameter values differ from base authored elevation")
    try:
        for proof in guards.values():
            cs_element_id_literal(proof.element_id, observation.target.revit_version)
    except ValueError as error:
        raise LevelUpdateRefusal("observed_id_outside_backend", str(error)) from error
    from kir.compiler import plan_program
    current = ElementIdentityProof.from_dict(level_row["element_identity"])
    planned = plan_program({"ir_version": base.ir_version, "intent": "One explicit Level elevation update",
        "ops": [{"op": "set_param", "id": "update_level_elevation", "target": {"by": "element_id", "value": current.element_id},
                 "param": parameter["name"], "value": {"value": new_value, "unit": "mm"}}]})
    _require(planned.to_ops()[0]["param"] == parameter["name"], "parameter_name_normalized", "compiler normalization would target a different observed name")
    report = {"schema": "kir-level-elevation-update-plan/1", "original_binding_digest": original["binding_digest"],
        "base_revision": base.revision_id, "proposed_revision": proposed.revision_id,
        "target_output_id": oid, "old_elev_mm": old_value, "new_elev_mm": new_value,
        "baseline_tolerance_mm": baseline_tol, "setter_tolerance_mm": spec.OPS["set_param"].tolerances["length_mm"],
        "observation": {"operation_id": observation.operation_id, "source_sha256": observation.source_sha256,
                        "target": observation.target.to_dict(), "precondition": observation.precondition.to_dict()},
        "target_identity": current.to_dict(), "protected_output_ids": [addresses[address][2] for address in protected],
        "affected_output_ids": list(difference.affected), "mutation_plan_digest": planned.plan_digest,
        "claims": dict(_UPDATE_PLAN_CLAIMS)}
    result = object.__new__(LevelElevationUpdatePlan)
    for key, value in {"planned": planned, "target": observation.target, "precondition": observation.precondition,
        "expected_identities": tuple(guards[key] for key in sorted(guards)),
        "publication": publication, "baseline": baseline, "before_observation": observation,
        "_report": _object(report, "level_update")}.items():
        object.__setattr__(result, key, value)
    return result


def prepare_level_update(update: LevelElevationUpdatePlan, *, operation_id: str) -> PreparedExecution:
    """Compile the new mutation with ALL planned guards and the observed revision.

    The caller cannot replace target, precondition or guard inputs through this
    entrypoint. No discovery, context refresh, archiving, dispatch or retry is
    performed. A saved report cannot be loaded into a fresh update plan here.
    """
    _require(type(update) is LevelElevationUpdatePlan, "level_update_plan_required", "expected a fresh typed Level update plan")
    from kir.revit_connector import prepare_execution

    return prepare_execution(update.planned, target=update.target, precondition=update.precondition,
        operation_id=operation_id, bulk=update.planned.bulk, expected_identities=update.expected_identities)


__all__ = ["ORIGINAL_BINDINGS_SCHEMA", "LEGACY_ORIGINAL_BINDINGS_SCHEMA", "LevelUpdateRefusal", "OriginalPublicationBindings", "LevelElevationUpdatePlan",
           "bind_original_publication", "plan_level_elevation_update", "prepare_level_update"]
