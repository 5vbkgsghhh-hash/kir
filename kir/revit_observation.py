"""Revision-bound native observations for a selected reconciliation scope.

This is not original publication ownership, a current-document lease, a mutation
plan, or a BIM acceptance verdict. Unavailable/not-found rows remain explicit.
Parsing and combination are pure. Explicit observe functions issue model-read-only
queries through the runtime, which may journal them; they do not edit authoring
state or refresh an already bound query precondition.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import json
import math
from hashlib import sha256
from types import MappingProxyType

from kir.connector_result import assess_connector_query_response
from kir.contracts import ElementIdentityProof
from kir.element_query import ELEMENT_STATE_SCHEMA
from kir.revit_connector import (
    MAX_FRAME_BYTES, ContextPrecondition, PreparedExecution, RuntimeTarget, SessionCredentials, prepare_execution, _uuid, _text,
)

# A request budget, not a limit on a building. Larger scopes require multiple
# observations tied to the same unchanged native revision, not unbounded source
# expansion. The existing compiler/frame budgets apply independently.
MAX_OBSERVATION_ELEMENTS = 128
MAX_OBSERVATION_AGGREGATE_BYTES = MAX_FRAME_BYTES
_ROW_FIELDS = frozenset({"schema_version", "requested_unique_id", "status", "reason", "name",
    "category_id", "is_level", "type_state", "level_status", "level_reason", "level",
    "element_identity", "element_identity_status", "element_identity_reason"})
_IDENTITY_FIELDS = frozenset({"schema_version", "element_id", "unique_id", "version_guid"})
_IDENTITY_UNAVAILABLE = frozenset({"element_missing", "identity_incomplete", "identity_unreadable"})


class ObservationRefusal(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(condition, code="invalid_element_observation"):
    if not condition:
        raise ObservationRefusal(code)


def _object(value, fields):
    _require(type(value) is dict and set(value) == fields)


def _integer(value, low=-(1 << 63), high=(1 << 63) - 1):
    _require(type(value) is int and low <= value <= high)


def _finite(value):
    _require(type(value) in (int, float))
    try:
        _require(math.isfinite(value))
    except OverflowError as error:
        raise ObservationRefusal("invalid_element_observation") from error


def _identity(row):
    status, reason, identity = (row["element_identity_status"], row["element_identity_reason"], row["element_identity"])
    if status == "captured":
        _require(reason is None)
        _object(identity, _IDENTITY_FIELDS)
        try:
            return ElementIdentityProof.from_dict(identity)
        except ValueError as error:
            raise ObservationRefusal("invalid_element_identity") from error
    _require(status == "unavailable" and type(reason) is str and reason in _IDENTITY_UNAVAILABLE and identity is None)
    return None


def _validate_level(level):
    _object(level, {"project_elevation_mm", "reported_elevation_mm", "elevation_base",
                    "basis_parameter_id", "elevation_parameter"})
    _finite(level["project_elevation_mm"])
    _finite(level["reported_elevation_mm"])
    _integer(level["elevation_base"], -(1 << 31), (1 << 31) - 1)
    _integer(level["basis_parameter_id"], -(1 << 31), -1)
    parameter = level["elevation_parameter"]
    _object(parameter, {"builtin", "parameter_id", "name", "storage_type", "is_read_only",
                        "value_internal_feet", "name_match_count", "name_resolves_builtin"})
    _require(parameter["builtin"] == "LEVEL_ELEV" and parameter["storage_type"] == "Double")
    _integer(parameter["parameter_id"], -(1 << 31), -1)
    _require(type(parameter["name"]) is str and bool(parameter["name"].strip()))
    _require(type(parameter["is_read_only"]) is bool and type(parameter["name_resolves_builtin"]) is bool)
    _finite(parameter["value_internal_feet"])
    _integer(parameter["name_match_count"], 0, (1 << 31) - 1)
    _require(not parameter["name_resolves_builtin"] or parameter["name_match_count"] == 1)


def _validate_row(row, requested_uid):
    _object(row, _ROW_FIELDS)
    _require(row["schema_version"] == ELEMENT_STATE_SCHEMA and row["requested_unique_id"] == requested_uid)
    identity = _identity(row)
    status = row["status"]
    _require(type(status) is str and status in {"observed", "not_found", "unavailable"})
    _require(row["name"] is None or type(row["name"]) is str)
    _require(row["is_level"] is None or type(row["is_level"]) is bool)
    if row["category_id"] is not None:
        _integer(row["category_id"])
    type_identity = None
    if row["type_state"] is not None:
        typed = row["type_state"]
        _object(typed, {"status", "element_identity", "element_identity_status", "element_identity_reason"})
        type_identity = _identity(typed)
        _require(type(typed["status"]) is str and typed["status"] in {"observed", "none", "unavailable"})
        _require((typed["status"] == "observed") == (type_identity is not None))
        if typed["status"] == "none":
            _require(typed["element_identity_reason"] == "element_missing")
    if status == "observed":
        _require(row["reason"] is None and identity is not None and identity.unique_id == requested_uid)
        _require(type(row["name"]) is str and type(row["is_level"]) is bool and row["type_state"] is not None)
        if row["is_level"] and type_identity is not None:
            _require(identity.element_id != type_identity.element_id and identity.unique_id != type_identity.unique_id,
                     "invalid_element_type_identity")
    elif status == "not_found":
        _require(identity is None and row["reason"] is None and row["element_identity_reason"] == "element_missing")
        _require(all(row[key] is None for key in ("name", "category_id", "is_level", "type_state")))
    else:
        _require(type(row["reason"]) is str and row["reason"] in {
            "lookup_failed", "identity_mismatch", "metadata_read_failed", "identity_unavailable",
            "document_modifiable", "document_state_unavailable"})
    level_status = row["level_status"]
    _require(type(level_status) is str and level_status in {"observed", "not_level", "not_evaluated", "unavailable"})
    if level_status == "observed":
        _require(status == "observed" and row["is_level"] is True and row["level_reason"] is None)
        # The native reader gets Elevation Base from the Level's type. No
        # type therefore cannot produce an observed Level payload. A failed
        # type identity getter is different: the type object can still exist.
        _require(row["type_state"] is not None and row["type_state"]["status"] != "none",
                 "level_type_state_contradiction")
        _validate_level(row["level"])
    else:
        _require(row["level"] is None)
        if level_status == "unavailable":
            _require(row["is_level"] is True and type(row["level_reason"]) is str and row["level_reason"] in {
                "level_read_failed", "level_parameters_unavailable", "level_parameter_identity_mismatch", "nonfinite_level_value"})
        else:
            _require(row["level_reason"] is None)
        if level_status == "not_level":
            _require(status == "observed" and row["is_level"] is False)
    if status == "observed":
        _require(level_status in ({"observed", "unavailable"} if row["is_level"] else {"not_level"}))
    if status == "not_found":
        _require(level_status == "not_evaluated")


@dataclass(frozen=True, slots=True, init=False)
class ElementObservation:
    """Detached field observations; original create ownership is separate."""

    target: RuntimeTarget
    precondition: ContextPrecondition
    operation_id: str
    source_sha256: str
    _rows_json: str = field(repr=False)
    # Derived lookup caches follow ElementObservationSet's existing representation.
    # Immutable JSON/proofs stay private; callers still receive detached rows.
    _indexed_rows: object = field(repr=False, compare=False)
    _identities: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use parse_element_observation; serialized claims are not a new read")

    @property
    def rows(self) -> dict:
        return json.loads(self._rows_json)

    def require_identity(self, unique_id: str) -> ElementIdentityProof:
        proof = self._identities.get(unique_id)
        _require(proof is not None, "element_identity_unavailable")
        return proof

    def require_level(self, unique_id: str) -> dict:
        value = self._indexed_rows.get(unique_id)
        _require(value is not None, "level_observation_unavailable")
        row = json.loads(value)
        _require(row["status"] == "observed" and row["level_status"] == "observed"
                 and row["type_state"]["status"] == "observed", "level_observation_unavailable")
        # Shared/unknown basis and read-only/ambiguous parameters are observations,
        # not parser errors. A mutation planner must explicitly refuse them.
        return row


def _scope_ids(unique_ids):
    _require(isinstance(unique_ids, Sequence) and not isinstance(unique_ids, (str, bytes, bytearray)), "invalid_observation_scope")
    uids = tuple(unique_ids)
    _require(1 <= len(uids) <= MAX_OBSERVATION_ELEMENTS, "observation_scope_budget")
    _require(all(type(uid) is str and uid.strip() for uid in uids), "invalid_observation_scope")
    _require(len(set(uids)) == len(uids), "duplicate_observation_identity")
    return uids


def prepare_element_observation(unique_ids: Sequence[str], *, target: RuntimeTarget,
                                precondition: ContextPrecondition, operation_id: str) -> PreparedExecution:
    uids = _scope_ids(unique_ids)
    return prepare_execution({"ops": [{"op": "query_element_state", "id": f"observe_{index}", "unique_id": uid}
                                       for index, uid in enumerate(uids)]},
        target=target, precondition=precondition, operation_id=operation_id)


def parse_element_observation(artifact: PreparedExecution, response: str | bytes, *,
                              credentials: SessionCredentials, request_id: str) -> ElementObservation:
    _require(type(artifact) is PreparedExecution and artifact.planned.family.value == "query", "element_query_required")
    ops = artifact.planned.to_ops()
    _require(1 <= len(ops) <= MAX_OBSERVATION_ELEMENTS
             and all(op["op"] == "query_element_state"
                     and op.get("include_type_definition", False) is False for op in ops),
             "element_query_required")
    _require(len({op["unique_id"] for op in ops}) == len(ops), "duplicate_observation_identity")
    assessed = assess_connector_query_response(artifact, response, credentials=credentials, request_id=request_id)
    _require(assessed.result_available and assessed.precondition == artifact.precondition, "query_result_unavailable")
    result = assessed.result
    _object(result, {op["id"] for op in ops})
    rows = {}
    by_id, by_uid = {}, {}

    def register(identity):
        proof = ElementIdentityProof.from_dict(identity)
        _require(by_id.get(proof.element_id, proof) == proof and by_uid.get(proof.unique_id, proof) == proof,
                 "conflicting_element_identity")
        by_id[proof.element_id] = by_uid[proof.unique_id] = proof

    for op in ops:
        row = result[op["id"]]
        _validate_row(row, op["unique_id"])
        rows[op["unique_id"]] = row
        if row["status"] == "observed":
            register(row["element_identity"])
            if row["type_state"]["status"] == "observed":
                register(row["type_state"]["element_identity"])
    # Each row is serialized once; the whole map is assembled from those strings
    # byte-for-byte as `json.dumps(rows)` with the same separators would produce it.
    indexed = {uid: json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
               for uid, row in rows.items()}
    observed = object.__new__(ElementObservation)
    for key, value in {"target": artifact.target, "precondition": artifact.precondition,
        "operation_id": artifact.operation_id, "source_sha256": artifact.source_sha256,
        "_rows_json": "{" + ",".join(f"{json.dumps(uid, ensure_ascii=False)}:{raw}"
                                     for uid, raw in indexed.items()) + "}",
        "_indexed_rows": MappingProxyType(indexed),
        "_identities": MappingProxyType({uid: by_uid[uid] for uid, row in rows.items()
                                         if row["status"] == "observed"})}.items():
        object.__setattr__(observed, key, value)
    return observed


def observe_elements(unique_ids, *, advertisement, client_path, expected_target: RuntimeTarget,
                     expected_document_key: str, operation_id: str, bind_view: bool,
                     bind_selection: bool, timeout_ms: int = 30000) -> ElementObservation:
    """Read a selected UID scope in one explicitly chosen runtime/document.

    Two exchanges: context, then one generated read-only query bound to THAT
    context. No discovery selection, mutation, source archive, retry or cleanup.
    A changed context between the calls is rejected by native admission, never
    accepted by replacing the query precondition. Missing rows remain explicit.
    """
    from uuid import uuid4
    from kir.connector_result import assess_connector_context_response
    from kir.revit_discovery import DiscoveryAdvertisement
    from kir.revit_transport import exchange

    uids = _scope_ids(unique_ids)
    _require(type(expected_target) is RuntimeTarget and type(advertisement) is DiscoveryAdvertisement
             and advertisement.credentials.target == expected_target, "observation_target_mismatch")
    _require(type(bind_view) is bool and type(bind_selection) is bool, "explicit_observation_binding_required")
    _require(type(timeout_ms) is int and 1000 <= timeout_ms <= 300000, "invalid_observation_timeout")
    _text(expected_document_key, "expected_document_key")
    operation_id = _uuid(operation_id, "operation_id")
    credentials = advertisement.credentials
    context_id = str(uuid4())
    context_request = credentials.context_request(request_id=context_id, timeout_ms=timeout_ms)
    wire = lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    raw_context = exchange(advertisement, wire(context_request), client_path=client_path, timeout_ms=timeout_ms)
    context = assess_connector_context_response(raw_context, credentials=credentials, request_id=context_id)
    precondition = context.require_precondition(bind_view=bind_view, bind_selection=bind_selection)
    _require(precondition.document_key == expected_document_key, "observation_document_mismatch")
    query = prepare_element_observation(uids, target=expected_target, precondition=precondition, operation_id=operation_id)
    request_id = str(uuid4())
    request = query.execute_request(credentials, request_id=request_id, timeout_ms=timeout_ms)
    response = exchange(advertisement, wire(request), client_path=client_path, timeout_ms=timeout_ms)
    return parse_element_observation(query, response, credentials=credentials, request_id=request_id)


def _wire(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _aggregate_scope(unique_ids):
    _require(isinstance(unique_ids, Sequence) and not isinstance(unique_ids, (str, bytes, bytearray)),
             "invalid_observation_scope")
    _require(0 < len(unique_ids) <= MAX_OBSERVATION_AGGREGATE_BYTES, "observation_aggregate_budget")
    size = 2
    seen = set()
    for uid in unique_ids:
        _require(type(uid) is str and bool(uid.strip()), "invalid_observation_scope")
        _require(len(uid) <= MAX_OBSERVATION_AGGREGATE_BYTES, "observation_aggregate_budget")
        size += len(_wire(uid).encode("utf-8")) + 1
        _require(size <= MAX_OBSERVATION_AGGREGATE_BYTES, "observation_aggregate_budget")
        _require(uid not in seen, "duplicate_observation_identity")
        seen.add(uid)
    return tuple(unique_ids)


def _part_bytes(part):
    _require(type(part) is ElementObservation, "element_observation_required")
    _require(type(part._rows_json) is str and len(part._rows_json) <= MAX_OBSERVATION_AGGREGATE_BYTES,
             "observation_aggregate_budget")
    size = len(part._rows_json.encode("utf-8"))
    _require(size <= MAX_OBSERVATION_AGGREGATE_BYTES, "observation_aggregate_budget")
    return size


@dataclass(frozen=True, slots=True, init=False)
class ElementObservationSet:
    """Complete requested coverage at one retained context, not a current lease.

    Parts are real parsed carriers, never imported JSON snapshots. Each query
    keeps its own input identity; this object invents no single native operation.
    Missing/unavailable element rows remain facts, not successful BIM acceptance.
    """

    target: RuntimeTarget
    precondition: ContextPrecondition
    query_inputs_digest: str
    _query_inputs_json: str = field(repr=False)
    _indexed_rows: object = field(repr=False)
    _identities: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use combine_element_observations; serialized claims are not a new read")

    @property
    def rows(self) -> dict:
        return {uid: json.loads(row) for uid, row in self._indexed_rows.items()}

    @property
    def query_inputs(self) -> list:
        return json.loads(self._query_inputs_json)

    def require_identity(self, unique_id: str) -> ElementIdentityProof:
        proof = self._identities.get(unique_id)
        _require(proof is not None, "element_identity_unavailable")
        return proof

    def require_level(self, unique_id: str) -> dict:
        value = self._indexed_rows.get(unique_id)
        _require(value is not None, "level_observation_unavailable")
        row = json.loads(value)
        _require(row["status"] == "observed" and row["level_status"] == "observed"
                 and row["type_state"]["status"] == "observed", "level_observation_unavailable")
        return row


def combine_element_observations(parts, *, expected_unique_ids) -> ElementObservationSet:
    """Join non-overlapping complete query scopes without refreshing evidence.

    The byte limit is an aggregation/request budget, not a building size limit.
    Global numeric IDs, UIDs and versions must agree, including shared types.
    """
    uids = _aggregate_scope(expected_unique_ids)
    _require(isinstance(parts, Sequence) and 0 < len(parts) <= len(uids), "invalid_observation_parts")
    # Bound all retained bytes before decoding or accumulating any part rows.
    size = 2  # query_inputs list delimiters
    for part in parts:
        size += _part_bytes(part)
        _require(size <= MAX_OBSERVATION_AGGREGATE_BYTES, "observation_aggregate_budget")
    first = parts[0]
    _require(type(first.target) is RuntimeTarget and type(first.precondition) is ContextPrecondition,
             "invalid_observation_binding")
    size += len(_wire({"target": first.target.to_dict(), "precondition": first.precondition.to_dict()}).encode())
    expected = set(uids)
    rows, identities, by_id, by_uid, query_inputs = {}, {}, {}, {}, []
    absent, operation_ids = set(), set()

    def register(proof):
        if proof is None:
            return
        _require(by_id.get(proof.element_id, proof) == proof and by_uid.get(proof.unique_id, proof) == proof,
                 "conflicting_element_identity")
        by_id[proof.element_id] = by_uid[proof.unique_id] = proof

    for part in parts:
        _require(part.target == first.target and part.precondition == first.precondition,
                 "observation_context_mismatch")
        _require(part.operation_id not in operation_ids, "duplicate_observation_query")
        operation_ids.add(part.operation_id)
        part_rows = part.rows
        _require(type(part_rows) is dict and 0 < len(part_rows) <= MAX_OBSERVATION_ELEMENTS,
                 "invalid_element_observation")
        query_input = {"operation_id": part.operation_id, "source_sha256": part.source_sha256,
                       "requested_unique_ids": list(part_rows)}
        size += len(_wire(query_input).encode()) + 1
        _require(size <= MAX_OBSERVATION_AGGREGATE_BYTES, "observation_aggregate_budget")
        query_inputs.append(query_input)
        for uid, row in part_rows.items():
            _require(uid in expected, "observation_scope_mismatch")
            _require(uid not in rows, "duplicate_observation_identity")
            _validate_row(row, uid)
            proof = _identity(row)
            if proof is not None:
                _require(proof.unique_id == uid, "conflicting_element_identity")
            register(proof)
            if row["type_state"] is not None:
                register(_identity(row["type_state"]))
            if row["status"] == "observed":
                identities[uid] = proof
            elif row["status"] == "not_found":
                absent.add(uid)
            rows[uid] = _wire(row)
    _require(set(rows) == expected, "observation_scope_mismatch")
    _require(not absent.intersection(by_uid), "conflicting_element_identity")
    inputs_json = _wire(query_inputs)
    observed = object.__new__(ElementObservationSet)
    for key, value in {"target": first.target, "precondition": first.precondition,
        "query_inputs_digest": sha256(inputs_json.encode()).hexdigest(), "_query_inputs_json": inputs_json,
        "_indexed_rows": MappingProxyType({uid: rows[uid] for uid in uids}),
        "_identities": MappingProxyType(identities)}.items():
        object.__setattr__(observed, key, value)
    return observed


def observe_element_scope(unique_ids, *, advertisement, client_path, expected_target: RuntimeTarget,
                          expected_document_key: str, bind_view: bool, bind_selection: bool,
                          timeout_ms: int = 30000) -> ElementObservationSet:
    """One context followed by sequential bounded read-only queries, no retries.

    Every chunk uses the exact original precondition. Any failure prevents an
    aggregate result; earlier reads do not become an allegedly complete scope.
    Successful completion is evidence at that revision, never future currentness.
    """
    from uuid import uuid4
    from kir.connector_result import assess_connector_context_response
    from kir.revit_discovery import DiscoveryAdvertisement
    from kir.revit_transport import exchange

    uids = _aggregate_scope(unique_ids)
    _require(type(expected_target) is RuntimeTarget and type(advertisement) is DiscoveryAdvertisement
             and advertisement.credentials.target == expected_target, "observation_target_mismatch")
    _require(type(bind_view) is bool and type(bind_selection) is bool, "explicit_observation_binding_required")
    _require(type(timeout_ms) is int and 1000 <= timeout_ms <= 300000, "invalid_observation_timeout")
    _text(expected_document_key, "expected_document_key")
    credentials = advertisement.credentials
    context_id = str(uuid4())
    raw = exchange(advertisement, _wire(credentials.context_request(request_id=context_id,
        timeout_ms=timeout_ms)).encode(), client_path=client_path, timeout_ms=timeout_ms)
    context = assess_connector_context_response(raw, credentials=credentials, request_id=context_id)
    precondition = context.require_precondition(bind_view=bind_view, bind_selection=bind_selection)
    _require(precondition.document_key == expected_document_key, "observation_document_mismatch")
    parts = []
    size = 2 + len(_wire({"target": expected_target.to_dict(), "precondition": precondition.to_dict()}).encode())
    for start in range(0, len(uids), MAX_OBSERVATION_ELEMENTS):
        query = prepare_element_observation(uids[start:start + MAX_OBSERVATION_ELEMENTS],
            target=expected_target, precondition=precondition, operation_id=str(uuid4()))
        request_id = str(uuid4())
        request = query.execute_request(credentials, request_id=request_id, timeout_ms=timeout_ms)
        response = exchange(advertisement, _wire(request).encode(), client_path=client_path, timeout_ms=timeout_ms)
        part = parse_element_observation(query, response, credentials=credentials, request_id=request_id)
        size += _part_bytes(part)
        size += len(_wire({"operation_id": part.operation_id, "source_sha256": part.source_sha256,
                           "requested_unique_ids": list(part._indexed_rows)}).encode()) + 1
        _require(size <= MAX_OBSERVATION_AGGREGATE_BYTES, "observation_aggregate_budget")
        parts.append(part)
    return combine_element_observations(parts, expected_unique_ids=uids)


__all__ = ["ObservationRefusal", "ElementObservation", "MAX_OBSERVATION_ELEMENTS",
           "prepare_element_observation", "parse_element_observation", "observe_elements",
           "ElementObservationSet", "MAX_OBSERVATION_AGGREGATE_BYTES", "combine_element_observations",
           "observe_element_scope"]
