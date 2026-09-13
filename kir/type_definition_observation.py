"""Revision-bound parallel wall/floor layer facts and declared-clause comparison.

Parsing requires the original prepared opt-in query and a bound read-only
Connector response. There is no JSON authority loader or native execution here.
Layer/name/width equality is not complete type/material/geometry preservation.
"""
from collections.abc import Sequence
from dataclasses import dataclass, field
import json
from types import MappingProxyType

from kir import spec
from kir.contracts import ElementIdentityProof
from kir.connector_result import assess_connector_query_response
from kir.element_query import ELEMENT_STATE_SCHEMA, TYPE_DEFINITION_STATE_SCHEMA
from kir.project import _hash, _object as _freeze, _thaw
from kir.revit_connector import (
    MAX_FRAME_BYTES, ContextPrecondition, RuntimeTarget, PreparedExecution, prepare_execution, _uuid,
)
from kir.revit_observation import (
    _ROW_FIELDS, _validate_row, _object, _integer, _finite, _require, _identity,
    ObservationRefusal,
)


MAX_TYPE_DEFINITION_ELEMENTS = 32
MAX_TYPE_DEFINITION_BYTES = MAX_FRAME_BYTES
# Frozen /1 observation profile; retained reads do not consult today's query
# registry. Fresh query authoring still uses element_query's ParamSpec gate.
_RETAINED_UID_MAX = 512
_METADATA_FIELDS = {"target", "precondition", "operation_id", "source_sha256", "rows"}
_DEFINITION_FIELDS = {"host_kind", "wall_kind", "is_vertically_compound", "is_vertically_homogeneous",
                      "name", "total_width_mm", "layers"}
_LAYER_FIELDS = {"width_mm", "function", "material_id", "material_name", "material_identity", "material_name_match_count"}
_UNAVAILABLE = {"base_observation_unavailable", "definition_getter_failed", "compound_structure_missing",
    "layers_unavailable", "layer_count_outside_profile", "invalid_width", "material_id_unavailable",
    "material_missing", "material_identity_unavailable", "material_identity_mismatch", "material_name_unavailable"}
_NOT_APPLICABLE = {"unsupported_element_kind", "unsupported_wall_kind", "non_simple_compound_structure"}
# Explicitly tied to element_query._type_definition_cs's current post-cast
# control flow. Even its catch reason follows a successful Wall/FloorType cast
# for API getter failures: the generic branch has no API calls. Keep this set
# independent of _UNAVAILABLE so a future pre-cast reason never acquires class
# authority merely by being added to the schema. Neither generic unsupported
# elements nor base-read failures establish a type role.
_KNOWN_TYPE_REASONS = {
    "unsupported_wall_kind", "non_simple_compound_structure", "definition_getter_failed",
    "compound_structure_missing", "layers_unavailable", "layer_count_outside_profile", "invalid_width",
    "material_id_unavailable", "material_missing", "material_identity_unavailable",
    "material_identity_mismatch", "material_name_unavailable",
}
_NOT_EVALUATED = ["full_type_definition", "material_properties", "graphics", "endcaps",
                  "core_shell_flags", "deck_profile", "undeclared_parameters", "geometry", "engineering"]


def _claims():
    return {"scope": "revision_bound_declared_layer_facts", "current_model_state": "not_established",
            "native_ownership": "not_established", "update_permission": "none",
            "not_evaluated": list(_NOT_EVALUATED)}


def _json_budget(value, *, frozen=False):
    """Bound structural inspection before canonical hashing; no JSON coercion."""
    stack, nodes, characters = [(value, 0)], 0, 0
    mapping_type, array_type = (MappingProxyType, tuple) if frozen else (dict, list)
    while stack:
        node, depth = stack.pop()
        nodes += 1
        _require(depth <= 64 and nodes <= 150000, "type_definition_claims_budget")
        if type(node) is mapping_type:
            _require(len(node) <= 150000, "type_definition_claims_budget")
            for key, item in node.items():
                _require(type(key) is str, "invalid_type_definition_claims")
                stack.extend(((key, depth + 1), (item, depth + 1)))
        elif type(node) is array_type:
            _require(len(node) <= 150000, "type_definition_claims_budget")
            stack.extend((item, depth + 1) for item in node)
        elif type(node) is str:
            characters += len(node)
            _require(characters <= MAX_TYPE_DEFINITION_BYTES, "type_definition_claims_budget")
        elif type(node) is int:
            _require(node.bit_length() <= 1024, "type_definition_claims_budget")
        elif type(node) is float:
            _finite(node)
        else:
            _require(node is None or type(node) is bool, "invalid_type_definition_claims")
    try:
        size = 0
        encoded = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True,
                                   separators=(",", ":")).iterencode(_thaw(value) if frozen else value)
        for chunk in encoded:
            size += len(chunk.encode("utf-8"))
            _require(size <= MAX_TYPE_DEFINITION_BYTES, "type_definition_claims_budget")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        if isinstance(error, ObservationRefusal):
            raise
        raise ObservationRefusal("invalid_type_definition_claims") from error


@dataclass(frozen=True, slots=True, init=False)
class TypeDefinitionObservation:
    target: object
    precondition: object
    operation_id: str
    source_sha256: str
    digest: str
    _rows: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use parse_type_definition_observation; JSON claims are not a bound query")

    @property
    def rows(self):
        return _thaw(self._rows)

    def validate(self) -> None:
        """Recheck this carrier's structure/integrity, not freshness or a channel.

        This does not authenticate hostile in-process Python or re-execute its
        query. Retained claims have a separate inert validator and never become
        this factory-only object.
        """
        _require(type(self) is TypeDefinitionObservation, "type_definition_observation_required")
        try:
            _require(type(self.target) is RuntimeTarget and type(self.precondition) is ContextPrecondition,
                     "invalid_type_definition_carrier")
            _json_budget(self._rows, frozen=True)
            validate_type_definition_claims(self.to_dict())
        except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as error:
            if isinstance(error, ObservationRefusal):
                raise
            raise ObservationRefusal("invalid_type_definition_carrier") from error

    def to_dict(self):
        return {"schema": "kir-type-definition-observation/1", "target": self.target.to_dict(),
            "precondition": self.precondition.to_dict(), "operation_id": self.operation_id,
            "source_sha256": self.source_sha256, "rows": self.rows, "observation_digest": self.digest,
            "claims": _claims()}


def prepare_type_definition_observation(unique_ids: Sequence[str], *, target, precondition,
                                        operation_id: str) -> PreparedExecution:
    _require(isinstance(unique_ids, Sequence) and not isinstance(unique_ids, (str, bytes)), "invalid_type_definition_scope")
    uids = tuple(unique_ids)
    _require(1 <= len(uids) <= MAX_TYPE_DEFINITION_ELEMENTS, "type_definition_scope_budget")
    _require(all(type(uid) is str and uid.strip() for uid in uids), "invalid_type_definition_scope")
    _require(len(set(uids)) == len(uids), "duplicate_type_definition_identity")
    return prepare_execution({"ops": [{"op": "query_element_state", "id": f"type_definition_{index}",
        "unique_id": uid, "include_type_definition": True} for index, uid in enumerate(uids)]},
        target=target, precondition=precondition, operation_id=operation_id)


def _validate_definition(row):
    observation = row["type_definition"]
    _object(observation, {"status", "reason", "value"})
    status, reason, value = observation["status"], observation["reason"], observation["value"]
    _require(type(status) is str and status in {"observed", "not_applicable", "unavailable"})
    if row["status"] != "observed":
        _require(status == "unavailable" and reason == "base_observation_unavailable" and value is None)
        return []
    if status != "observed":
        _require(value is None and type(reason) is str and reason in (
            _UNAVAILABLE - {"base_observation_unavailable"} if status == "unavailable" else _NOT_APPLICABLE))
        return []
    _require(reason is None and row["is_level"] is False and row["type_state"]["status"] == "none")
    _object(value, _DEFINITION_FIELDS)
    _require(type(value["host_kind"]) is str and value["host_kind"] in {"wall", "floor"})
    _require(value["wall_kind"] == ("Basic" if value["host_kind"] == "wall" else None))
    # A wall with no horizontal breaks can be vertically compound AND homogeneous.
    _require(type(value["is_vertically_compound"]) is bool and value["is_vertically_homogeneous"] is True)
    _require(value["host_kind"] == "wall" or value["is_vertically_compound"] is False)
    _require(type(value["name"]) is str and value["name"] == row["name"])
    _finite(value["total_width_mm"])
    _require(value["total_width_mm"] >= 0)
    layers = value["layers"]
    _require(type(layers) is list and 1 <= len(layers) <= spec.WALL_LAYERS_MAX)
    identities = []
    for layer in layers:
        _object(layer, _LAYER_FIELDS)
        _finite(layer["width_mm"])
        _require(layer["width_mm"] >= 0)
        _require(type(layer["function"]) is str and layer["function"] in spec.WALL_LAYER_FUNCTIONS)
        _integer(layer["material_id"], -1, (1 << 63) - 1)
        if layer["material_id"] == -1:
            _require(all(layer[key] is None for key in ("material_name", "material_identity", "material_name_match_count")))
        else:
            _require(layer["material_id"] > 0 and type(layer["material_name"]) is str)
            _integer(layer["material_name_match_count"], 0, (1 << 31) - 1)
            _object(layer["material_identity"], {"schema_version", "element_id", "unique_id", "version_guid"})
            try:
                proof = ElementIdentityProof.from_dict(layer["material_identity"])
            except ValueError as error:
                raise ObservationRefusal("invalid_material_identity") from error
            _require(proof.element_id == layer["material_id"], "material_identity_mismatch")
            identities.append(proof)
    return identities


def _validate_rows(rows):
    _require(type(rows) is dict and 1 <= len(rows) <= MAX_TYPE_DEFINITION_ELEMENTS, "type_definition_scope_budget")
    by_id, by_uid, materials = {}, {}, {}
    non_material_ids = set()
    for uid, row in rows.items():
        _require(type(uid) is str and bool(uid.strip()) and len(uid) <= _RETAINED_UID_MAX, "invalid_type_definition_identity")
        _object(row, set(_ROW_FIELDS) | {"type_definition"})
        _require(row["schema_version"] == TYPE_DEFINITION_STATE_SCHEMA)
        # Explicit /2 base-field validation, not construction of an old fresh
        # observation and not a relabelled query/receipt. The old parser rejects
        # /2 fields/schema. This is its shared field validator only.
        base = {key: value for key, value in row.items() if key != "type_definition"}
        base["schema_version"] = ELEMENT_STATE_SCHEMA
        _validate_row(base, uid)
        proofs = _validate_definition(row)
        if row["type_definition"]["status"] == "observed":
            for layer in row["type_definition"]["value"]["layers"]:
                if layer["material_id"] != -1:
                    facts = (layer["material_name"], layer["material_name_match_count"])
                    _require(materials.get(layer["material_id"], facts) == facts,
                             "conflicting_material_observation")
                    materials[layer["material_id"]] = facts
        if row["status"] == "observed":
            primary = _identity(row)
            proofs.append(primary)
            if (row["is_level"] or row["type_definition"]["status"] == "observed"
                    or row["type_definition"]["reason"] in _KNOWN_TYPE_REASONS):
                non_material_ids.add(primary.element_id)
            if row["type_state"]["status"] == "observed":
                element_type = _identity(row["type_state"])
                proofs.append(element_type)
                non_material_ids.add(element_type.element_id)
        for proof in proofs:
            _require(by_id.get(proof.element_id, proof) == proof and by_uid.get(proof.unique_id, proof) == proof,
                     "conflicting_element_identity")
            by_id[proof.element_id] = by_uid[proof.unique_id] = proof
    # Check AFTER all rows: a material may alias a type queried later. Generic
    # primary elements are not classified here; querying a Material itself is
    # lawful and its identity can also occur in a layer. Observed Level,
    # confirmed Wall/FloorType (even incomplete definition) and GetTypeId-
    # produced identities are disjoint from Material.
    _require(set(materials).isdisjoint(non_material_ids), "material_role_conflict")
    name_counts, name_ids = {}, {}
    for material_id, (name, count) in materials.items():
        _require(count >= 1, "invalid_material_name_count")
        _require(name_counts.get(name, count) == count, "conflicting_material_name_count")
        name_counts[name] = count
        name_ids.setdefault(name, set()).add(material_id)
    for name, ids in name_ids.items():
        # Ordinal/case-sensitive names match the actual factory lookup. These
        # rows establish only a LOWER bound: unqueried document materials may
        # have the same name, so count greater than the known set is legal.
        _require(name_counts[name] >= len(ids), "material_name_count_below_observed")


def validate_type_definition_claims(value: dict) -> None:
    """Validate retained profile/rows/hash only; no fresh carrier or authority.

    Coherently rehashed data is still only data. This function cannot establish
    which query executed, authenticate a source/channel, or grant any action.
    It deliberately does not invoke the compiler, native parser or transport.
    """
    try:
        _json_budget(value)
        _object(value, _METADATA_FIELDS | {"schema", "observation_digest", "claims"})
        _require(value["schema"] == "kir-type-definition-observation/1", "invalid_type_definition_claims")
        _require(value["claims"] == _claims(), "invalid_type_definition_claims")
        _object(value["target"], {"journal_id", "instance_id", "revit_version"})
        _object(value["precondition"], {"document_key", "revision", "active_view_id", "selection_digest"})
        target = RuntimeTarget(**value["target"])
        precondition = ContextPrecondition(**value["precondition"])
        _require(target.to_dict() == value["target"] and precondition.to_dict() == value["precondition"],
                 "noncanonical_type_definition_metadata")
        _require(_uuid(value["operation_id"], "operation_id") == value["operation_id"], "noncanonical_type_definition_metadata")
        for key in ("source_sha256", "observation_digest"):
            digest = value[key]
            _require(type(digest) is str and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest),
                     "invalid_type_definition_digest")
        _validate_rows(value["rows"])
        _require(_hash({key: value[key] for key in _METADATA_FIELDS}) == value["observation_digest"],
                 "type_definition_digest_mismatch")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        if isinstance(error, ObservationRefusal):
            raise
        raise ObservationRefusal("invalid_type_definition_claims") from error


def parse_type_definition_observation(artifact, response, *, credentials, request_id) -> TypeDefinitionObservation:
    _require(type(artifact) is PreparedExecution and artifact.planned.family.value == "query", "type_definition_query_required")
    operations = artifact.planned.to_ops()
    _require(1 <= len(operations) <= MAX_TYPE_DEFINITION_ELEMENTS and all(
        op["op"] == "query_element_state" and op.get("include_type_definition") is True for op in operations),
        "type_definition_query_required")
    _require(len({op["unique_id"] for op in operations}) == len(operations), "duplicate_type_definition_identity")
    assessment = assess_connector_query_response(artifact, response, credentials=credentials, request_id=request_id)
    _require(assessment.result_available and assessment.precondition == artifact.precondition, "query_result_unavailable")
    result = assessment.result
    _object(result, {op["id"] for op in operations})
    rows = {op["unique_id"]: result[op["id"]] for op in operations}
    payload = {"target": artifact.target.to_dict(), "precondition": artifact.precondition.to_dict(),
               "operation_id": artifact.operation_id, "source_sha256": artifact.source_sha256, "rows": rows}
    _json_budget(payload)
    _validate_rows(rows)  # Reject malformed/wide rows before freezing/hashing.
    observation = object.__new__(TypeDefinitionObservation)
    for key, value in {"target": artifact.target, "precondition": artifact.precondition,
        "operation_id": artifact.operation_id, "source_sha256": artifact.source_sha256,
        "digest": _hash(payload), "_rows": _freeze(rows, "type_definition_rows")}.items():
        object.__setattr__(observation, key, value)
    observation.validate()
    return observation


def compare_type_definition(observation, *, unique_id: str, factory_op) -> dict:
    """Compare validated caller-declared factory clauses, not Project provenance.

    The existing planner owns all expected scalar/function/material validation;
    no arbitrary dict is treated as already-normalized evidence. source_type is
    validated as authoring input, never promoted to observed native ownership.
    """
    from kir.compiler import plan_program
    from kir.diag import KirRefusal
    from kir.midend import PlannedOp

    _require(type(observation) is TypeDefinitionObservation, "type_definition_observation_required")
    observation.validate()
    operation = factory_op.to_dict() if type(factory_op) is PlannedOp else factory_op
    _require(type(operation) is dict and operation.get("op") == "create_wall_type", "factory_definition_required")
    try:
        expected = plan_program({"ops": [{"id": "expected_type_definition", **operation}]}).to_ops()[0]
    except (KirRefusal, TypeError, ValueError) as error:
        raise ObservationRefusal("factory_definition_invalid") from error
    kind = expected.get("host_kind", "wall")
    _require(kind in {"wall", "floor"}, "factory_definition_profile_unsupported")
    _require(type(unique_id) is str and bool(unique_id.strip()), "invalid_type_definition_identity")
    layers = expected["layers"]
    checks = {key: {"status": "not_evaluated", "reason": "definition_unavailable"}
              for key in ("host_kind", "type_name", "layer_count", "total_width")}
    for index in range(len(layers)):
        for clause in ("width_mm", "function", "material"):
            checks[f"layers[{index}].{clause}"] = {"status": "not_evaluated", "reason": "definition_unavailable"}
    tolerance = spec.OPS["create_wall_type"].tolerances["layer_mm"]
    result = {"schema": "kir-type-definition-comparison/1", "observation_digest": observation.digest,
        "unique_id": unique_id, "expected_clauses_digest": _hash({"host_kind": kind, "new_name": expected["new_name"], "layers": layers}),
        "precondition": observation.precondition.to_dict(), "checks": checks, "tolerance_mm": tolerance,
        "claims": {"current_model_state": "not_established", "project_source_binding": "not_established",
                   "source_seed_identity": "not_evaluated", "update_permission": "none",
                   "not_evaluated": list(_NOT_EVALUATED)}}
    row = observation.rows.get(unique_id)
    if row is None or row["type_definition"]["status"] != "observed":
        return result
    actual = row["type_definition"]["value"]
    def check(key, matched, reason):
        checks[key] = {"status": "matched" if matched else "mismatch", "reason": reason}
    check("host_kind", actual["host_kind"] == kind, "observed_host_kind")
    check("type_name", actual["name"] == expected["new_name"], "observed_type_name")
    check("layer_count", len(actual["layers"]) == len(layers), "observed_layer_count")
    check("total_width", abs(actual["total_width_mm"] - round(sum(layer["width_mm"] for layer in layers), 6)) <= tolerance,
          "observed_total_width")
    for index, layer in enumerate(layers):
        if index >= len(actual["layers"]):
            for clause in ("width_mm", "function", "material"):
                checks[f"layers[{index}].{clause}"]["reason"] = "observed_layer_missing"
            continue
        observed = actual["layers"][index]
        check(f"layers[{index}].width_mm", abs(observed["width_mm"] - layer["width_mm"]) <= tolerance, "observed_layer_width")
        check(f"layers[{index}].function", observed["function"] == layer["function"], "observed_layer_function")
        key, material = f"layers[{index}].material", layer.get("material")
        if material is None:
            check(key, observed["material_id"] == -1, "declared_no_material")
        elif observed["material_name"] != material:
            check(key, False, "observed_material_name_differs")
        elif observed["material_name_match_count"] != 1:
            checks[key] = {"status": "not_evaluated", "reason": "material_name_not_unique"}
        else:
            check(key, True, "observed_unique_material_name")
    return result


__all__ = ["MAX_TYPE_DEFINITION_ELEMENTS", "MAX_TYPE_DEFINITION_BYTES", "TypeDefinitionObservation",
           "prepare_type_definition_observation", "parse_type_definition_observation",
           "validate_type_definition_claims", "compare_type_definition"]
