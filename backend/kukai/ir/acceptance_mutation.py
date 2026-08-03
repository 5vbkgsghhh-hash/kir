"""Typed, replayable independent rereads for existing-element mutations.

The category x level census proves creation deltas, but it cannot see an
in-place parameter edit, translation, type change, or deletion.  This module
derives a second predicate from the same immutable :class:`PlannedProgram` and
observes exact, pre-existing ElementIds before and after execution.

No execution receipt is trusted as a verdict or even as a target locator.
Reference-addressed mutations and type/family creation remain explicitly
blind until KIR can bind their newly-created identity independently.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from kukai.ir import spec
from kukai.ir.acceptance import BlindOp
from kukai.ir.contracts import DocumentFingerprint, ElementIdentityProof
from kukai.ir.document_guard import bind_read_to_document
from kukai.ir.emit_utils import cs_element_id_literal, cs_string_literal
from kukai.ir.midend import PlannedProgram


MUTATION_OBSERVATION_SCHEMA_VERSION = "kir-mutation-observation/1"
_PHASES = frozenset({"before", "after"})
_ROW_FIELDS = frozenset({
    "claim_key",
    "target_id",
    "exists",
    "unique_id",
    "version_guid",
    "desired_type_exists",
    "desired_type_unique_id",
    "desired_type_version_guid",
    "type_id",
    "location_kind",
    "point_mm",
    "curve0_mm",
    "curve1_mm",
    "parameter_matches",
    "parameter_read_only",
    "parameter_storage",
    "parameter_string",
    "parameter_integer",
    "parameter_double",
})


class MutationAcceptanceError(ValueError):
    """A mutation predicate or live observation violates its closed schema."""


class MutationKind(str, Enum):
    SET_PARAMETER = "set_parameter"
    MOVE = "move"
    CHANGE_TYPE = "change_type"
    DELETE = "delete"


class MutationMismatchCode(str, Enum):
    PRECONDITION = "mutation_precondition"
    TARGET_MISSING = "mutation_target_missing"
    TARGET_REPLACED = "mutation_target_replaced"
    DEPENDENCY_CHANGED = "mutation_dependency_changed"
    PARAMETER_MISMATCH = "parameter_mismatch"
    LOCATION_MISMATCH = "location_mismatch"
    TYPE_MISMATCH = "type_mismatch"
    DELETE_FAILED = "delete_failed"


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise MutationAcceptanceError(
            f"mutation value is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _phase(value: Any) -> str:
    if value not in _PHASES:
        raise MutationAcceptanceError(
            f"mutation phase must be one of {sorted(_PHASES)}")
    return str(value)


def _finite_number(value: Any, field_name: str) -> int | float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise MutationAcceptanceError(f"{field_name} must be finite")
    return value


def _exact_element_id(selector: Any) -> int | None:
    if (not isinstance(selector, Mapping)
            or selector.get("by") != "element_id"):
        return None
    value = selector.get("value")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


@dataclass(frozen=True, slots=True)
class MutationClaim:
    """One final-state predicate over one exact pre-existing ElementId."""

    key: str
    kind: MutationKind
    target_id: int
    op_ids: tuple[str, ...]
    parameter_name: str | None = None
    value_kind: str | None = None
    expected_string: str | None = None
    expected_number: int | float | None = None
    tolerance: float | None = None
    delta_mm: tuple[float, float, float] | None = None
    type_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise MutationAcceptanceError("mutation claim key must be non-empty")
        if not isinstance(self.kind, MutationKind):
            raise MutationAcceptanceError("mutation claim kind must be typed")
        if (isinstance(self.target_id, bool)
                or not isinstance(self.target_id, int)
                or self.target_id < 1):
            raise MutationAcceptanceError("mutation target_id must be positive")
        if (not self.op_ids or tuple(sorted(set(self.op_ids))) != self.op_ids
                or any(not isinstance(item, str) or not item
                       for item in self.op_ids)):
            raise MutationAcceptanceError(
                "mutation op_ids must be non-empty, unique, and sorted")

        if self.kind is MutationKind.SET_PARAMETER:
            if not isinstance(self.parameter_name, str) or not self.parameter_name:
                raise MutationAcceptanceError(
                    "parameter claim requires a non-empty name")
            if self.value_kind not in {"str", "mm", "int", "double"}:
                raise MutationAcceptanceError(
                    "parameter claim has an unknown value kind")
            if self.value_kind == "str":
                if not isinstance(self.expected_string, str):
                    raise MutationAcceptanceError(
                        "string parameter claim needs expected_string")
                if any(value is not None for value in (
                        self.expected_number, self.tolerance,
                        self.delta_mm, self.type_id)):
                    raise MutationAcceptanceError(
                        "string parameter claim carries foreign fields")
            else:
                _finite_number(self.expected_number, "expected_number")
                if (self.tolerance is None
                        or not math.isfinite(self.tolerance)
                        or self.tolerance < 0):
                    raise MutationAcceptanceError(
                        "numeric parameter claim needs a non-negative tolerance")
                if any(value is not None for value in (
                        self.expected_string, self.delta_mm, self.type_id)):
                    raise MutationAcceptanceError(
                        "numeric parameter claim carries foreign fields")
            return

        if self.kind is MutationKind.MOVE:
            if (not isinstance(self.delta_mm, tuple)
                    or len(self.delta_mm) != 3
                    or any(not math.isfinite(value)
                           for value in self.delta_mm)):
                raise MutationAcceptanceError(
                    "move claim needs a finite three-axis delta")
            if self.tolerance is None or self.tolerance <= 0:
                raise MutationAcceptanceError(
                    "move claim needs a positive tolerance")
        elif self.kind is MutationKind.CHANGE_TYPE:
            if (isinstance(self.type_id, bool)
                    or not isinstance(self.type_id, int)
                    or self.type_id < 1):
                raise MutationAcceptanceError(
                    "change-type claim needs a positive type_id")
        elif self.kind is MutationKind.DELETE:
            pass

        foreign = (
            self.parameter_name,
            self.value_kind,
            self.expected_string,
            self.expected_number,
        )
        if any(value is not None for value in foreign):
            raise MutationAcceptanceError(
                "non-parameter mutation claim carries parameter fields")
        if self.kind is not MutationKind.MOVE and self.delta_mm is not None:
            raise MutationAcceptanceError("non-move claim carries delta_mm")
        if self.kind is not MutationKind.MOVE and self.tolerance is not None:
            raise MutationAcceptanceError("non-move claim carries tolerance")
        if self.kind is not MutationKind.CHANGE_TYPE and self.type_id is not None:
            raise MutationAcceptanceError("non-type claim carries type_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind.value,
            "target_id": self.target_id,
            "op_ids": list(self.op_ids),
            "parameter_name": self.parameter_name,
            "value_kind": self.value_kind,
            "expected_string": self.expected_string,
            "expected_number": self.expected_number,
            "tolerance": self.tolerance,
            "delta_mm": list(self.delta_mm) if self.delta_mm is not None else None,
            "type_id": self.type_id,
        }


@dataclass(frozen=True, slots=True)
class MutationExpectation:
    claims: tuple[MutationClaim, ...]
    blind_ops: tuple[BlindOp, ...]

    def __post_init__(self) -> None:
        if (not isinstance(self.claims, tuple)
                or any(not isinstance(item, MutationClaim)
                       for item in self.claims)):
            raise MutationAcceptanceError(
                "mutation claims must be typed immutable values")
        keys = tuple(claim.key for claim in self.claims)
        if keys != tuple(sorted(set(keys))):
            raise MutationAcceptanceError(
                "mutation claims must have unique canonical keys")
        if (not isinstance(self.blind_ops, tuple)
                or any(not isinstance(item, BlindOp)
                       for item in self.blind_ops)):
            raise MutationAcceptanceError("mutation blind ops must be typed")

    @property
    def checkable(self) -> bool:
        return bool(self.claims)

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [claim.to_dict() for claim in self.claims],
            "blind_ops": [item.to_dict() for item in self.blind_ops],
        }


_UNMEASURED_WRITES: Mapping[str, str] = {
    "create_type": (
        "создаёт ElementType, исключённый из instance-census; независимый "
        "локатор нового типа пока не выводится без доверия к receipt"),
    "load_family": (
        "загружает внешний Family/FamilySymbol; независимый локатор результата "
        "пока не выводится без доверия к receipt"),
}

# Closed seam with acceptance.py: these are exactly the operations whose
# correctness cannot be established by an instance category census alone.
MUTATION_ACCEPTANCE_OPS = frozenset({
    "set_param", "move_elements", "change_type", "delete",
    *_UNMEASURED_WRITES,
})


def _blind(op_id: str, op_name: str, reason: str) -> BlindOp:
    return BlindOp(op_id=op_id, op_name=op_name, reason=reason)


def derive_mutation_expectation(planned: PlannedProgram) -> MutationExpectation:
    """Derive exact-id final-state claims from the immutable typed plan."""

    if not isinstance(planned, PlannedProgram):
        raise TypeError("mutation acceptance requires PlannedProgram")

    params: dict[tuple[int, str], dict[str, Any]] = {}
    moves: dict[int, dict[str, Any]] = {}
    types: dict[int, dict[str, Any]] = {}
    deletes: dict[int, dict[str, Any]] = {}
    blind: list[BlindOp] = []

    def clear_deleted(target_id: int) -> None:
        deletes.pop(target_id, None)

    for op in planned.to_ops():
        name = op["op"]
        op_id = op["id"]
        if name in _UNMEASURED_WRITES:
            blind.append(_blind(op_id, name, _UNMEASURED_WRITES[name]))
            continue

        if name == "set_param":
            target_id = _exact_element_id(op.get("target"))
            if target_id is None:
                blind.append(_blind(
                    op_id, name,
                    "target адресован ref; новый ElementId нельзя независимо "
                    "вывести до исполнения"))
                continue
            value = op["value"]
            kind = value["type"]
            row = {
                "target_id": target_id,
                "parameter_name": op["param"],
                "value_kind": "double" if kind == "raw" else kind,
                "expected_string": value["v"] if kind == "str" else None,
                "expected_number": value["v"] if kind != "str" else None,
                "tolerance": ({"mm": 0.5, "int": 0.0}.get(kind, 1e-6)
                              if kind != "str" else None),
                "op_ids": {op_id},
            }
            old = params.get((target_id, op["param"]))
            if old is not None:
                row["op_ids"].update(old["op_ids"])
            params[(target_id, op["param"])] = row
            clear_deleted(target_id)
            continue

        if name == "move_elements":
            dx, dy, dz = (float(value) for value in op["delta_mm"])
            seen: set[int] = set()
            has_ref = False
            for selector in op["targets"]:
                target_id = _exact_element_id(selector)
                if target_id is None:
                    has_ref = True
                    continue
                # Duplicates within one MoveElements collection do not mean
                # repeated translation; the API receives one target set.
                if target_id in seen:
                    continue
                seen.add(target_id)
                row = moves.setdefault(target_id, {
                    "delta": [0.0, 0.0, 0.0], "op_ids": set(),
                })
                row["delta"][0] += dx
                row["delta"][1] += dy
                row["delta"][2] += dz
                row["op_ids"].add(op_id)
                clear_deleted(target_id)
            if has_ref:
                blind.append(_blind(
                    op_id, name,
                    "часть targets адресована ref; их исходную идентичность "
                    "нельзя независимо предзарегистрировать"))
            continue

        if name == "change_type":
            target_id = _exact_element_id(op.get("target"))
            type_id = _exact_element_id(op.get("type"))
            if target_id is None or type_id is None:
                blind.append(_blind(
                    op_id, name,
                    "target/type не являются двумя exact element_id; редкую "
                    "замену элемента нельзя связать без receipt"))
                continue
            row = {"type_id": type_id, "op_ids": {op_id}}
            old = types.get(target_id)
            if old is not None:
                row["op_ids"].update(old["op_ids"])
            types[target_id] = row
            clear_deleted(target_id)
            continue

        if name == "delete":
            target_id = _exact_element_id(op.get("target"))
            if target_id is None:
                blind.append(_blind(
                    op_id, name,
                    "target адресован ref; отсутствие неизвестного заранее id "
                    "нельзя независимо проверить"))
                continue
            params = {key: row for key, row in params.items()
                      if key[0] != target_id}
            moves.pop(target_id, None)
            types.pop(target_id, None)
            old = deletes.get(target_id)
            op_ids = {op_id}
            if old is not None:
                op_ids.update(old["op_ids"])
            deletes[target_id] = {"op_ids": op_ids}

    claims: list[MutationClaim] = []
    for (target_id, parameter_name), row in params.items():
        param_hash = hashlib.sha256(parameter_name.encode("utf-8")).hexdigest()[:16]
        claims.append(MutationClaim(
            key=f"param:{target_id}:{param_hash}",
            kind=MutationKind.SET_PARAMETER,
            target_id=target_id,
            op_ids=tuple(sorted(row["op_ids"])),
            parameter_name=parameter_name,
            value_kind=row["value_kind"],
            expected_string=row["expected_string"],
            expected_number=row["expected_number"],
            tolerance=row["tolerance"],
        ))
    for target_id, row in moves.items():
        claims.append(MutationClaim(
            key=f"move:{target_id}",
            kind=MutationKind.MOVE,
            target_id=target_id,
            op_ids=tuple(sorted(row["op_ids"])),
            delta_mm=tuple(row["delta"]),
            tolerance=float(spec.OPS["move_elements"].tolerances["location_mm"]),
        ))
    for target_id, row in types.items():
        claims.append(MutationClaim(
            key=f"type:{target_id}",
            kind=MutationKind.CHANGE_TYPE,
            target_id=target_id,
            op_ids=tuple(sorted(row["op_ids"])),
            type_id=row["type_id"],
        ))
    for target_id, row in deletes.items():
        claims.append(MutationClaim(
            key=f"delete:{target_id}",
            kind=MutationKind.DELETE,
            target_id=target_id,
            op_ids=tuple(sorted(row["op_ids"])),
        ))
    claims.sort(key=lambda item: item.key)
    return MutationExpectation(tuple(claims), tuple(blind))


@dataclass(frozen=True, slots=True)
class MutationObservationRow:
    claim_key: str
    target_id: str
    exists: bool
    unique_id: str | None
    version_guid: str | None
    desired_type_exists: bool | None
    desired_type_unique_id: str | None
    desired_type_version_guid: str | None
    type_id: str | None
    location_kind: str
    point_mm: tuple[float, float, float] | None
    curve0_mm: tuple[float, float, float] | None
    curve1_mm: tuple[float, float, float] | None
    parameter_matches: int | None
    parameter_read_only: bool | None
    parameter_storage: str | None
    parameter_string: str | None
    parameter_integer: int | None
    parameter_double: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.claim_key, str) or not self.claim_key:
            raise MutationAcceptanceError(
                "mutation observation claim_key must be non-empty")
        if (not isinstance(self.target_id, str)
                or not self.target_id.isascii()
                or not self.target_id.isdigit()
                or str(int(self.target_id)) != self.target_id
                or not 1 <= int(self.target_id) <= 0x7FFFFFFFFFFFFFFF):
            raise MutationAcceptanceError(
                "mutation observation target_id must be canonical positive int64")
        if not isinstance(self.exists, bool):
            raise MutationAcceptanceError(
                "mutation observation exists must be bool")
        if (self.desired_type_exists is not None
                and not isinstance(self.desired_type_exists, bool)):
            raise MutationAcceptanceError(
                "mutation desired_type_exists must be bool or null")
        for field_name in (
            "unique_id", "version_guid", "desired_type_unique_id",
            "desired_type_version_guid", "type_id", "parameter_storage",
            "parameter_string",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise MutationAcceptanceError(
                    f"mutation observation {field_name} must be string or null")
        for field_name in ("version_guid", "desired_type_version_guid"):
            value = getattr(self, field_name)
            if (value is not None
                    and re.fullmatch(r"[0-9a-f]{32}", value) is None):
                raise MutationAcceptanceError(
                    f"mutation observation {field_name} is malformed")
        if self.location_kind not in {
            "missing", "not_requested", "point", "curve", "unsupported",
        }:
            raise MutationAcceptanceError(
                "mutation observation location_kind is unknown")
        for field_name in ("point_mm", "curve0_mm", "curve1_mm"):
            value = getattr(self, field_name)
            if (value is not None
                    and (not isinstance(value, tuple)
                         or len(value) != 3
                         or any(isinstance(item, bool)
                                or not isinstance(item, (int, float))
                                or not math.isfinite(item)
                                for item in value))):
                raise MutationAcceptanceError(
                    f"mutation observation {field_name} must be finite xyz")
        if (self.parameter_matches is not None
                and (isinstance(self.parameter_matches, bool)
                     or not isinstance(self.parameter_matches, int)
                     or self.parameter_matches < 0)):
            raise MutationAcceptanceError(
                "mutation parameter_matches must be non-negative int or null")
        if (self.parameter_read_only is not None
                and not isinstance(self.parameter_read_only, bool)):
            raise MutationAcceptanceError(
                "mutation parameter_read_only must be bool or null")
        if (self.parameter_integer is not None
                and (isinstance(self.parameter_integer, bool)
                     or not isinstance(self.parameter_integer, int))):
            raise MutationAcceptanceError(
                "mutation parameter_integer must be int or null")
        if (self.parameter_double is not None
                and (isinstance(self.parameter_double, bool)
                     or not isinstance(self.parameter_double, (int, float))
                     or not math.isfinite(self.parameter_double))):
            raise MutationAcceptanceError(
                "mutation parameter_double must be finite or null")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_key": self.claim_key,
            "target_id": self.target_id,
            "exists": self.exists,
            "unique_id": self.unique_id,
            "version_guid": self.version_guid,
            "desired_type_exists": self.desired_type_exists,
            "desired_type_unique_id": self.desired_type_unique_id,
            "desired_type_version_guid": self.desired_type_version_guid,
            "type_id": self.type_id,
            "location_kind": self.location_kind,
            "point_mm": list(self.point_mm) if self.point_mm is not None else None,
            "curve0_mm": list(self.curve0_mm) if self.curve0_mm is not None else None,
            "curve1_mm": list(self.curve1_mm) if self.curve1_mm is not None else None,
            "parameter_matches": self.parameter_matches,
            "parameter_read_only": self.parameter_read_only,
            "parameter_storage": self.parameter_storage,
            "parameter_string": self.parameter_string,
            "parameter_integer": self.parameter_integer,
            "parameter_double": self.parameter_double,
        }


@dataclass(frozen=True, slots=True)
class MutationObservation:
    run_id: str
    phase: str
    expectation_digest: str
    document_digest: str
    rows: tuple[MutationObservationRow, ...]

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{32}", self.run_id) is None:
            raise MutationAcceptanceError("mutation run_id is malformed")
        _phase(self.phase)
        if re.fullmatch(r"[0-9a-f]{64}", self.expectation_digest) is None:
            raise MutationAcceptanceError(
                "mutation expectation_digest is malformed")
        if re.fullmatch(r"[0-9a-f]{64}", self.document_digest) is None:
            raise MutationAcceptanceError(
                "mutation document_digest is malformed")
        if (not isinstance(self.rows, tuple)
                or any(not isinstance(row, MutationObservationRow)
                       for row in self.rows)):
            raise MutationAcceptanceError(
                "mutation observation rows must be typed immutable rows")
        keys = tuple(row.claim_key for row in self.rows)
        if keys != tuple(sorted(set(keys))):
            raise MutationAcceptanceError(
                "mutation observation rows are not canonical")

    @property
    def observation_digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MUTATION_OBSERVATION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "phase": self.phase,
            "expectation_digest": self.expectation_digest,
            "document_digest": self.document_digest,
            "rows": [row.to_dict() for row in self.rows],
        }


def mutation_probe_fragment(
    expectation: MutationExpectation,
    document: DocumentFingerprint,
    *,
    run_id: str,
    phase: str,
    revit_version: str,
    result_var: str = "__kirMutationObservation",
) -> str:
    """Emit a read-only fragment that assigns one mutation observation map."""

    if not isinstance(expectation, MutationExpectation):
        raise TypeError("mutation probe requires MutationExpectation")
    if not isinstance(document, DocumentFingerprint):
        raise TypeError("mutation probe requires DocumentFingerprint")
    if not expectation.checkable:
        raise MutationAcceptanceError("mutation probe has no claims")
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        raise MutationAcceptanceError("mutation run_id is malformed")
    accepted_phase = _phase(phase)
    if re.fullmatch(r"__[A-Za-z0-9_]+", result_var) is None:
        raise MutationAcceptanceError("mutation result variable is unsafe")

    descriptors = []
    for claim in expectation.claims:
        desired_type = (
            cs_element_id_literal(claim.type_id, revit_version)
            if claim.kind is MutationKind.CHANGE_TYPE else "null"
        )
        descriptors.append(
            "new Dictionary<string, object> { "
            f"{{\"key\", {cs_string_literal(claim.key)}}}, "
            f"{{\"kind\", {cs_string_literal(claim.kind.value)}}}, "
            f"{{\"target_id\", {cs_element_id_literal(claim.target_id, revit_version)}}}, "
            f"{{\"parameter_name\", {cs_string_literal(claim.parameter_name or '')}}}, "
            f"{{\"desired_type_id\", {desired_type}}} "
            "}")
    descriptor_cs = ",\n    ".join(descriptors)
    code = f"""
var __kirMutationSpecs = new List<Dictionary<string, object>> {{
    {descriptor_cs}
}};
var __kirMutationRows = new List<object>();
foreach (var __kirMutationSpec in __kirMutationSpecs)
{{
    string __kirMutationKey = (string)__kirMutationSpec["key"];
    string __kirMutationKind = (string)__kirMutationSpec["kind"];
    ElementId __kirMutationId = (ElementId)__kirMutationSpec["target_id"];
    ElementId __kirMutationDesiredTypeId =
        __kirMutationSpec["desired_type_id"] as ElementId;
    string __kirMutationParam = (string)__kirMutationSpec["parameter_name"];
    Element __kirMutationElement = doc.GetElement(__kirMutationId);
    bool __kirMutationExists = __kirMutationElement != null;
    string __kirMutationUnique = null;
    string __kirMutationVersion = null;
    object __kirMutationDesiredTypeExists = null;
    string __kirMutationDesiredTypeUnique = null;
    string __kirMutationDesiredTypeVersion = null;
    string __kirMutationType = null;
    string __kirMutationLocationKind = __kirMutationExists
        ? "not_requested" : "missing";
    object __kirMutationPoint = null;
    object __kirMutationCurve0 = null;
    object __kirMutationCurve1 = null;
    object __kirMutationParamMatches = null;
    object __kirMutationParamReadOnly = null;
    object __kirMutationParamStorage = null;
    object __kirMutationParamString = null;
    object __kirMutationParamInteger = null;
    object __kirMutationParamDouble = null;
    if (__kirMutationKind == "change_type")
    {{
        Element __kirMutationDesiredType =
            doc.GetElement(__kirMutationDesiredTypeId);
        bool __kirMutationDesiredExists =
            __kirMutationDesiredType != null;
        __kirMutationDesiredTypeExists = __kirMutationDesiredExists;
        if (__kirMutationDesiredExists)
        {{
            try {{ __kirMutationDesiredTypeUnique =
                __kirMutationDesiredType.UniqueId ?? ""; }}
            catch {{ __kirMutationDesiredTypeUnique = ""; }}
            try {{ __kirMutationDesiredTypeVersion =
                __kirMutationDesiredType.VersionGuid.ToString("N")
                    .ToLowerInvariant(); }}
            catch {{ __kirMutationDesiredTypeVersion = ""; }}
        }}
    }}
    if (__kirMutationExists)
    {{
        try {{ __kirMutationUnique = __kirMutationElement.UniqueId ?? ""; }}
        catch {{ __kirMutationUnique = ""; }}
        try {{ __kirMutationVersion =
            __kirMutationElement.VersionGuid.ToString("N").ToLowerInvariant(); }}
        catch {{ __kirMutationVersion = ""; }}
        if (__kirMutationKind == "move")
        {{
            var __kirMutationLp = __kirMutationElement.Location as LocationPoint;
            var __kirMutationLc = __kirMutationElement.Location as LocationCurve;
            if (__kirMutationLp != null)
            {{
                XYZ __kirMutationP = __kirMutationLp.Point;
                __kirMutationLocationKind = "point";
                __kirMutationPoint = new List<object> {{
                    Math.Round(__kirMutationP.X * 304.8, 6),
                    Math.Round(__kirMutationP.Y * 304.8, 6),
                    Math.Round(__kirMutationP.Z * 304.8, 6)
                }};
            }}
            else if (__kirMutationLc != null)
            {{
                XYZ __kirMutationA = __kirMutationLc.Curve.GetEndPoint(0);
                XYZ __kirMutationB = __kirMutationLc.Curve.GetEndPoint(1);
                __kirMutationLocationKind = "curve";
                __kirMutationCurve0 = new List<object> {{
                    Math.Round(__kirMutationA.X * 304.8, 6),
                    Math.Round(__kirMutationA.Y * 304.8, 6),
                    Math.Round(__kirMutationA.Z * 304.8, 6)
                }};
                __kirMutationCurve1 = new List<object> {{
                    Math.Round(__kirMutationB.X * 304.8, 6),
                    Math.Round(__kirMutationB.Y * 304.8, 6),
                    Math.Round(__kirMutationB.Z * 304.8, 6)
                }};
            }}
            else __kirMutationLocationKind = "unsupported";
        }}
        else if (__kirMutationKind == "change_type")
        {{
            ElementId __kirMutationTypeId = __kirMutationElement.GetTypeId();
            __kirMutationType = __kirMutationTypeId == null
                ? "" : __kirMutationTypeId.ToString();
        }}
        else if (__kirMutationKind == "set_parameter")
        {{
            var __kirMutationMatches =
                __kirMutationElement.GetParameters(__kirMutationParam);
            int __kirMutationMatchCount =
                __kirMutationMatches == null ? 0 : __kirMutationMatches.Count;
            __kirMutationParamMatches = __kirMutationMatchCount;
            if (__kirMutationMatchCount == 1)
            {{
                Parameter __kirMutationParameter = __kirMutationMatches[0];
                __kirMutationParamReadOnly = __kirMutationParameter.IsReadOnly;
                __kirMutationParamStorage =
                    __kirMutationParameter.StorageType.ToString();
                if (__kirMutationParameter.StorageType == StorageType.String)
                    __kirMutationParamString =
                        __kirMutationParameter.AsString() ?? "";
                else if (__kirMutationParameter.StorageType == StorageType.Integer)
                    __kirMutationParamInteger = __kirMutationParameter.AsInteger();
                else if (__kirMutationParameter.StorageType == StorageType.Double)
                {{
                    double __kirMutationDouble = __kirMutationParameter.AsDouble();
                    if (!Double.IsNaN(__kirMutationDouble)
                        && !Double.IsInfinity(__kirMutationDouble))
                        __kirMutationParamDouble = __kirMutationDouble;
                }}
            }}
        }}
    }}
    __kirMutationRows.Add(new Dictionary<string, object> {{
        {{"claim_key", __kirMutationKey}},
        {{"target_id", __kirMutationId.ToString()}},
        {{"exists", __kirMutationExists}},
        {{"unique_id", __kirMutationUnique}},
        {{"version_guid", __kirMutationVersion}},
        {{"desired_type_exists", __kirMutationDesiredTypeExists}},
        {{"desired_type_unique_id", __kirMutationDesiredTypeUnique}},
        {{"desired_type_version_guid", __kirMutationDesiredTypeVersion}},
        {{"type_id", __kirMutationType}},
        {{"location_kind", __kirMutationLocationKind}},
        {{"point_mm", __kirMutationPoint}},
        {{"curve0_mm", __kirMutationCurve0}},
        {{"curve1_mm", __kirMutationCurve1}},
        {{"parameter_matches", __kirMutationParamMatches}},
        {{"parameter_read_only", __kirMutationParamReadOnly}},
        {{"parameter_storage", __kirMutationParamStorage}},
        {{"parameter_string", __kirMutationParamString}},
        {{"parameter_integer", __kirMutationParamInteger}},
        {{"parameter_double", __kirMutationParamDouble}}
    }});
}}
var {result_var} = new Dictionary<string, object> {{
    {{"schema_version", "{MUTATION_OBSERVATION_SCHEMA_VERSION}"}},
    {{"run_id", "{run_id}"}},
    {{"phase", "{accepted_phase}"}},
    {{"expectation_digest", "{expectation.digest}"}},
    {{"document_digest", "{document.digest}"}},
    {{"rows", __kirMutationRows}}
}};
""".strip()
    return code


def build_mutation_probe_cs(
    expectation: MutationExpectation,
    document: DocumentFingerprint,
    *,
    run_id: str,
    phase: str,
    revit_version: str,
) -> str:
    fragment = mutation_probe_fragment(
        expectation,
        document,
        run_id=run_id,
        phase=phase,
        revit_version=revit_version,
    )
    return bind_read_to_document(
        fragment + "\nreturn __kirMutationObservation;", document)


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MutationAcceptanceError(f"{field_name} must be string or null")
    return value


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise MutationAcceptanceError(f"{field_name} must be bool or null")
    return value


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MutationAcceptanceError(f"{field_name} must be int or null")
    return value


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    return float(_finite_number(value, field_name))


def _point(value: Any, field_name: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) != 3):
        raise MutationAcceptanceError(f"{field_name} must be xyz list or null")
    return tuple(float(_finite_number(item, field_name)) for item in value)


def parse_mutation_observation(
    payload: Any,
    expectation: MutationExpectation,
    document: DocumentFingerprint,
    *,
    run_id: str,
    phase: str,
) -> MutationObservation:
    """Strictly parse an exact-scope mutation observation from the bridge."""

    if not isinstance(payload, Mapping):
        raise MutationAcceptanceError("mutation observation must be an object")
    fields = {
        "schema_version", "run_id", "phase", "expectation_digest",
        "document_digest", "rows",
    }
    if set(payload) != fields:
        raise MutationAcceptanceError("mutation observation fields differ")
    accepted_phase = _phase(phase)
    expected_header = {
        "schema_version": MUTATION_OBSERVATION_SCHEMA_VERSION,
        "run_id": run_id,
        "phase": accepted_phase,
        "expectation_digest": expectation.digest,
        "document_digest": document.digest,
    }
    for field_name, expected in expected_header.items():
        if payload.get(field_name) != expected:
            raise MutationAcceptanceError(
                f"mutation observation {field_name} binding differs")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) != len(expectation.claims):
        raise MutationAcceptanceError(
            "mutation observation row count differs from registered claims")

    rows: list[MutationObservationRow] = []
    for index, (raw, claim) in enumerate(zip(raw_rows, expectation.claims)):
        if not isinstance(raw, Mapping) or set(raw) != _ROW_FIELDS:
            raise MutationAcceptanceError(
                f"mutation row[{index}] fields differ")
        if raw.get("claim_key") != claim.key:
            raise MutationAcceptanceError(
                f"mutation row[{index}] claim order differs")
        if raw.get("target_id") != str(claim.target_id):
            raise MutationAcceptanceError(
                f"mutation row[{index}] target identity differs")
        exists = raw.get("exists")
        if not isinstance(exists, bool):
            raise MutationAcceptanceError(
                f"mutation row[{index}].exists must be bool")
        location_kind = raw.get("location_kind")
        if location_kind not in {
            "missing", "not_requested", "point", "curve", "unsupported",
        }:
            raise MutationAcceptanceError(
                f"mutation row[{index}] location kind is unknown")
        row = MutationObservationRow(
            claim_key=claim.key,
            target_id=str(claim.target_id),
            exists=exists,
            unique_id=_optional_string(raw.get("unique_id"), "unique_id"),
            version_guid=_optional_string(
                raw.get("version_guid"), "version_guid"),
            desired_type_exists=_optional_bool(
                raw.get("desired_type_exists"), "desired_type_exists"),
            desired_type_unique_id=_optional_string(
                raw.get("desired_type_unique_id"),
                "desired_type_unique_id"),
            desired_type_version_guid=_optional_string(
                raw.get("desired_type_version_guid"),
                "desired_type_version_guid"),
            type_id=_optional_string(raw.get("type_id"), "type_id"),
            location_kind=location_kind,
            point_mm=_point(raw.get("point_mm"), "point_mm"),
            curve0_mm=_point(raw.get("curve0_mm"), "curve0_mm"),
            curve1_mm=_point(raw.get("curve1_mm"), "curve1_mm"),
            parameter_matches=_optional_int(
                raw.get("parameter_matches"), "parameter_matches"),
            parameter_read_only=_optional_bool(
                raw.get("parameter_read_only"), "parameter_read_only"),
            parameter_storage=_optional_string(
                raw.get("parameter_storage"), "parameter_storage"),
            parameter_string=_optional_string(
                raw.get("parameter_string"), "parameter_string"),
            parameter_integer=_optional_int(
                raw.get("parameter_integer"), "parameter_integer"),
            parameter_double=_optional_float(
                raw.get("parameter_double"), "parameter_double"),
        )
        _validate_row_shape(row, claim, index)
        rows.append(row)
    return MutationObservation(
        run_id=run_id,
        phase=accepted_phase,
        expectation_digest=expectation.digest,
        document_digest=document.digest,
        rows=tuple(rows),
    )


def _validate_row_shape(
    row: MutationObservationRow,
    claim: MutationClaim,
    index: int,
) -> None:
    desired_type_values = (
        row.desired_type_exists,
        row.desired_type_unique_id,
        row.desired_type_version_guid,
    )
    if claim.kind is MutationKind.CHANGE_TYPE:
        if row.desired_type_exists is None:
            raise MutationAcceptanceError(
                f"mutation row[{index}] desired type presence is absent")
        if row.desired_type_exists:
            if (not row.desired_type_unique_id
                    or row.desired_type_version_guid is None):
                raise MutationAcceptanceError(
                    f"mutation row[{index}] desired type identity is absent")
        elif any(value is not None for value in desired_type_values[1:]):
            raise MutationAcceptanceError(
                f"mutation row[{index}] missing desired type carries identity")
    elif any(value is not None for value in desired_type_values):
        raise MutationAcceptanceError(
            f"mutation row[{index}] non-type claim carries desired type state")

    parameter_values = (
        row.parameter_matches,
        row.parameter_read_only,
        row.parameter_storage,
        row.parameter_string,
        row.parameter_integer,
        row.parameter_double,
    )
    if not row.exists:
        if (row.unique_id is not None or row.version_guid is not None
                or row.type_id is not None
                or row.location_kind != "missing"
                or any(value is not None for value in (
                    row.point_mm, row.curve0_mm, row.curve1_mm,
                    *parameter_values))):
            raise MutationAcceptanceError(
                f"mutation row[{index}] missing target carries state")
        return
    if row.unique_id is None or not row.unique_id:
        raise MutationAcceptanceError(
            f"mutation row[{index}] existing target lacks UniqueId")
    if (row.version_guid is None
            or re.fullmatch(r"[0-9a-f]{32}", row.version_guid) is None):
        raise MutationAcceptanceError(
            f"mutation row[{index}] existing target lacks VersionGuid")

    if claim.kind is MutationKind.MOVE:
        if row.type_id is not None or any(value is not None
                                          for value in parameter_values):
            raise MutationAcceptanceError(
                f"mutation row[{index}] move carries foreign state")
        if row.location_kind == "point":
            if (row.point_mm is None or row.curve0_mm is not None
                    or row.curve1_mm is not None):
                raise MutationAcceptanceError(
                    f"mutation row[{index}] point shape differs")
        elif row.location_kind == "curve":
            if (row.point_mm is not None or row.curve0_mm is None
                    or row.curve1_mm is None):
                raise MutationAcceptanceError(
                    f"mutation row[{index}] curve shape differs")
        elif row.location_kind != "unsupported":
            raise MutationAcceptanceError(
                f"mutation row[{index}] move location was not observed")
        return

    if (row.location_kind != "not_requested" or row.point_mm is not None
            or row.curve0_mm is not None or row.curve1_mm is not None):
        raise MutationAcceptanceError(
            f"mutation row[{index}] non-move carries location state")
    if claim.kind is MutationKind.CHANGE_TYPE:
        if row.type_id is None or not row.type_id:
            raise MutationAcceptanceError(
                f"mutation row[{index}] type state is absent")
        if any(value is not None for value in parameter_values):
            raise MutationAcceptanceError(
                f"mutation row[{index}] type carries parameter state")
    elif claim.kind is MutationKind.SET_PARAMETER:
        if row.type_id is not None or row.parameter_matches is None:
            raise MutationAcceptanceError(
                f"mutation row[{index}] parameter state is absent")
        if row.parameter_matches < 0:
            raise MutationAcceptanceError(
                f"mutation row[{index}] parameter count is negative")
        if row.parameter_matches != 1:
            if any(value is not None for value in parameter_values[1:]):
                raise MutationAcceptanceError(
                    f"mutation row[{index}] ambiguous parameter carries value")
        elif row.parameter_read_only is None or row.parameter_storage is None:
            raise MutationAcceptanceError(
                f"mutation row[{index}] parameter metadata is absent")
        elif row.parameter_storage == "String":
            if (row.parameter_string is None
                    or any(value is not None for value in (
                        row.parameter_integer, row.parameter_double))):
                raise MutationAcceptanceError(
                    f"mutation row[{index}] string parameter shape differs")
        elif row.parameter_storage == "Integer":
            if (row.parameter_integer is None
                    or any(value is not None for value in (
                        row.parameter_string, row.parameter_double))):
                raise MutationAcceptanceError(
                    f"mutation row[{index}] integer parameter shape differs")
        elif row.parameter_storage == "Double":
            if (row.parameter_double is None
                    or any(value is not None for value in (
                        row.parameter_string, row.parameter_integer))):
                raise MutationAcceptanceError(
                    f"mutation row[{index}] double parameter shape differs")
        elif any(value is not None for value in parameter_values[3:]):
            raise MutationAcceptanceError(
                f"mutation row[{index}] unsupported storage carries a value")
    elif claim.kind is MutationKind.DELETE:
        if row.type_id is not None or any(value is not None
                                          for value in parameter_values):
            raise MutationAcceptanceError(
                f"mutation row[{index}] delete carries foreign state")


@dataclass(frozen=True, slots=True)
class MutationMismatch:
    code: MutationMismatchCode
    claim_key: str
    op_ids: tuple[str, ...]
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, MutationMismatchCode):
            raise MutationAcceptanceError("mutation mismatch code must be typed")
        if not isinstance(self.claim_key, str) or not self.claim_key:
            raise MutationAcceptanceError(
                "mutation mismatch claim_key must be non-empty")
        if (not isinstance(self.op_ids, tuple) or not self.op_ids
                or self.op_ids != tuple(sorted(set(self.op_ids)))):
            raise MutationAcceptanceError(
                "mutation mismatch op_ids must be canonical")
        if not isinstance(self.detail, str) or not self.detail:
            raise MutationAcceptanceError(
                "mutation mismatch detail must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "claim_key": self.claim_key,
            "op_ids": list(self.op_ids),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MutationVerdict:
    accepted: bool
    mismatches: tuple[MutationMismatch, ...]
    checked_claims: int
    inconclusive_claims: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise MutationAcceptanceError("mutation verdict accepted must be bool")
        if (not isinstance(self.mismatches, tuple)
                or any(not isinstance(item, MutationMismatch)
                       for item in self.mismatches)):
            raise MutationAcceptanceError(
                "mutation verdict mismatches must be typed immutable values")
        if (isinstance(self.checked_claims, bool)
                or not isinstance(self.checked_claims, int)
                or self.checked_claims < 0):
            raise MutationAcceptanceError(
                "mutation verdict checked_claims must be non-negative")
        if (not isinstance(self.inconclusive_claims, tuple)
                or any(not isinstance(item, str) or not item
                       for item in self.inconclusive_claims)
                or self.inconclusive_claims
                != tuple(sorted(set(self.inconclusive_claims)))):
            raise MutationAcceptanceError(
                "mutation verdict inconclusive claims must be canonical")
        expected_accepted = (
            not self.mismatches
            and not self.inconclusive_claims
            and self.checked_claims > 0
        )
        if self.accepted != expected_accepted:
            raise MutationAcceptanceError(
                "mutation verdict accepted flag disagrees with evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "mismatches": [item.to_dict() for item in self.mismatches],
            "checked_claims": self.checked_claims,
            "inconclusive_claims": list(self.inconclusive_claims),
        }


def mutation_precondition_errors(
    expectation: MutationExpectation,
    before: MutationObservation,
) -> tuple[str, ...]:
    """Return reasons an exact mutation cannot safely start."""

    _require_binding(expectation, before, phase="before")
    errors = []
    for claim, row in zip(expectation.claims, before.rows):
        if not row.exists:
            errors.append(f"{claim.key}: target does not exist before write")
            continue
        if claim.kind is MutationKind.SET_PARAMETER:
            if row.parameter_matches != 1:
                errors.append(
                    f"{claim.key}: parameter match count is "
                    f"{row.parameter_matches}")
            elif row.parameter_read_only:
                errors.append(f"{claim.key}: parameter is read-only")
            else:
                wanted_storage = {
                    "str": "String", "int": "Integer",
                    "mm": "Double", "double": "Double",
                }[claim.value_kind or ""]
                if row.parameter_storage != wanted_storage:
                    errors.append(
                        f"{claim.key}: parameter storage is "
                        f"{row.parameter_storage}, expected {wanted_storage}")
        elif (claim.kind is MutationKind.CHANGE_TYPE
              and not row.desired_type_exists):
            errors.append(
                f"{claim.key}: desired type does not exist before write")
    return tuple(errors)


def mutation_identity_proofs(
    expectation: MutationExpectation,
    before: MutationObservation,
) -> tuple[ElementIdentityProof, ...]:
    """Turn the independent baseline into transaction-entry identity guards."""

    _require_binding(expectation, before, phase="before")
    by_id: dict[int, ElementIdentityProof] = {}

    def add(proof: ElementIdentityProof) -> None:
        previous = by_id.get(proof.element_id)
        if previous is not None and previous != proof:
            raise MutationAcceptanceError(
                f"ElementId {proof.element_id} has contradictory identities")
        by_id[proof.element_id] = proof

    for claim, row in zip(expectation.claims, before.rows):
        if not row.exists or row.unique_id is None or row.version_guid is None:
            raise MutationAcceptanceError(
                f"{claim.key}: exact identity is absent before write")
        add(ElementIdentityProof(
            element_id=claim.target_id,
            unique_id=row.unique_id,
            version_guid=row.version_guid,
        ))
        if claim.kind is MutationKind.CHANGE_TYPE:
            if (not row.desired_type_exists
                    or row.desired_type_unique_id is None
                    or row.desired_type_version_guid is None):
                raise MutationAcceptanceError(
                    f"{claim.key}: desired type identity is absent before write")
            add(ElementIdentityProof(
                element_id=claim.type_id,
                unique_id=row.desired_type_unique_id,
                version_guid=row.desired_type_version_guid,
            ))
    return tuple(by_id[key] for key in sorted(by_id))


def _require_binding(
    expectation: MutationExpectation,
    observation: MutationObservation,
    *,
    phase: str,
) -> None:
    if not isinstance(expectation, MutationExpectation):
        raise TypeError("mutation verdict requires typed expectation")
    if not isinstance(observation, MutationObservation):
        raise TypeError("mutation verdict requires typed observation")
    if observation.phase != phase:
        raise MutationAcceptanceError(
            f"mutation {phase} observation has phase {observation.phase}")
    if observation.expectation_digest != expectation.digest:
        raise MutationAcceptanceError(
            "mutation observation belongs to another expectation")
    if tuple(row.claim_key for row in observation.rows) != tuple(
            claim.key for claim in expectation.claims):
        raise MutationAcceptanceError(
            "mutation observation claim scope differs")


def _shifted(
    before: tuple[float, float, float],
    after: tuple[float, float, float],
    delta: tuple[float, float, float],
    tolerance: float,
) -> bool:
    return all(abs(after[index] - before[index] - delta[index]) <= tolerance
               for index in range(3))


def check_mutations(
    expectation: MutationExpectation,
    before: MutationObservation,
    after: MutationObservation,
) -> MutationVerdict:
    """Replay the mutation verdict from two bound read-only observations."""

    _require_binding(expectation, before, phase="before")
    _require_binding(expectation, after, phase="after")
    if before.run_id != after.run_id or before.document_digest != after.document_digest:
        raise MutationAcceptanceError(
            "mutation observations belong to different runs/documents")

    mismatches: list[MutationMismatch] = []
    inconclusive: list[str] = []
    checked = 0
    for claim, first, last in zip(expectation.claims, before.rows, after.rows):
        def mismatch(code: MutationMismatchCode, detail: str) -> None:
            mismatches.append(MutationMismatch(
                code=code,
                claim_key=claim.key,
                op_ids=claim.op_ids,
                detail=detail,
            ))

        if not first.exists:
            checked += 1
            mismatch(MutationMismatchCode.PRECONDITION,
                     "target did not exist in the registered baseline")
            continue
        if claim.kind is MutationKind.CHANGE_TYPE:
            if (not first.desired_type_exists
                    or first.desired_type_unique_id is None
                    or first.desired_type_version_guid is None):
                checked += 1
                mismatch(MutationMismatchCode.PRECONDITION,
                         "desired type had no identity in the baseline")
                continue
            if (not last.desired_type_exists
                    or last.desired_type_unique_id
                    != first.desired_type_unique_id
                    or last.desired_type_version_guid
                    != first.desired_type_version_guid):
                checked += 1
                mismatch(MutationMismatchCode.DEPENDENCY_CHANGED,
                         "desired type identity changed during execution")
                continue
        if claim.kind is MutationKind.DELETE:
            checked += 1
            if last.exists:
                mismatch(MutationMismatchCode.DELETE_FAILED,
                         "target still exists after committed delete")
            continue
        if not last.exists:
            if claim.kind is MutationKind.CHANGE_TYPE:
                inconclusive.append(claim.key)
            else:
                checked += 1
                mismatch(MutationMismatchCode.TARGET_MISSING,
                         "target disappeared during an in-place mutation")
            continue
        if first.unique_id != last.unique_id:
            if claim.kind is MutationKind.CHANGE_TYPE:
                # Revit may legally replace a wall with a curtain panel.  A
                # receipt-only locator would not be independent, so name the
                # edge as inconclusive rather than rejecting a valid commit.
                inconclusive.append(claim.key)
            else:
                checked += 1
                mismatch(MutationMismatchCode.TARGET_REPLACED,
                         "ElementId now resolves to a different UniqueId")
            continue

        checked += 1
        if claim.kind is MutationKind.SET_PARAMETER:
            if last.parameter_matches != 1:
                mismatch(MutationMismatchCode.PARAMETER_MISMATCH,
                         "parameter is absent or ambiguous after commit")
                continue
            if claim.value_kind == "str":
                ok = (last.parameter_storage == "String"
                      and last.parameter_string == claim.expected_string)
            elif claim.value_kind == "int":
                ok = (last.parameter_storage == "Integer"
                      and last.parameter_integer == claim.expected_number)
            else:
                actual = last.parameter_double
                expected = float(claim.expected_number)  # validated above
                if claim.value_kind == "mm" and actual is not None:
                    actual *= 304.8
                ok = (last.parameter_storage == "Double"
                      and actual is not None
                      and abs(actual - expected) <= float(claim.tolerance))
            if not ok:
                mismatch(MutationMismatchCode.PARAMETER_MISMATCH,
                         "parameter did not hold the preregistered value")
        elif claim.kind is MutationKind.MOVE:
            if (first.location_kind == "unsupported"
                    or last.location_kind == "unsupported"):
                checked -= 1
                inconclusive.append(claim.key)
                continue
            if first.location_kind != last.location_kind:
                mismatch(MutationMismatchCode.LOCATION_MISMATCH,
                         "location representation changed during move")
                continue
            delta = claim.delta_mm or (0.0, 0.0, 0.0)
            tolerance = float(claim.tolerance)
            if first.location_kind == "point":
                ok = _shifted(first.point_mm, last.point_mm, delta, tolerance)
            else:
                ok = (
                    _shifted(first.curve0_mm, last.curve0_mm, delta, tolerance)
                    and _shifted(first.curve1_mm, last.curve1_mm,
                                 delta, tolerance)
                )
            if not ok:
                mismatch(MutationMismatchCode.LOCATION_MISMATCH,
                         "location did not shift by the preregistered delta")
        elif claim.kind is MutationKind.CHANGE_TYPE:
            if last.type_id != str(claim.type_id):
                mismatch(MutationMismatchCode.TYPE_MISMATCH,
                         "element type differs from the preregistered type")

    return MutationVerdict(
        accepted=not mismatches and not inconclusive and checked > 0,
        mismatches=tuple(mismatches),
        checked_claims=checked,
        inconclusive_claims=tuple(inconclusive),
    )


__all__ = [
    "MUTATION_OBSERVATION_SCHEMA_VERSION",
    "MUTATION_ACCEPTANCE_OPS",
    "MutationAcceptanceError",
    "MutationClaim",
    "MutationExpectation",
    "MutationKind",
    "MutationMismatch",
    "MutationMismatchCode",
    "MutationObservation",
    "MutationObservationRow",
    "MutationVerdict",
    "build_mutation_probe_cs",
    "check_mutations",
    "derive_mutation_expectation",
    "mutation_precondition_errors",
    "mutation_identity_proofs",
    "mutation_probe_fragment",
    "parse_mutation_observation",
]
