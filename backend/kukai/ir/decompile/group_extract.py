"""Strict offline contract for Revit model-group instances and definitions.

The raw collector supplies ordered member ids per instance.  Member ids are
document-instance identities, so they cannot establish semantic slot equality
between two instances.  This module therefore derives only what the evidence
proves: ordinal slots from one deterministic reference instance, and explicit
cardinality mismatches.  It never repairs an excluded or otherwise divergent
member set.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from kukai.ir.decompile.side_contract import (
    SideFailure,
    SideFailureReason,
    parse_wire_failures,
    sorted_failures,
    source_binding_cs,
)


GROUP_INDEX_SCHEMA_VERSION = "kir-decompile-group-index/2"
LEGACY_GROUP_INDEX_SCHEMA_VERSION = "kir-decompile-group-index/1"
GROUP_EXTRACT_SCHEMA_VERSION = "kir-decompile-group-extract/2"
_FT_TO_MM = 304.8


class GroupIndexPayloadError(ValueError):
    """A raw or persisted group-index payload violates the contract."""


Vec3 = tuple[float, float, float]


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GroupIndexPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise GroupIndexPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _exact_fields(
    value: Any,
    fields: set[str],
    field_name: str,
) -> dict[str, Any]:
    row = _mapping(value, field_name)
    missing = sorted(fields - set(row))
    extra = sorted(set(row) - fields)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise GroupIndexPayloadError(
            f"{field_name} fields: {'; '.join(details)}")
    return row


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise GroupIndexPayloadError(
            f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    return None if value is None else _string(value, field_name)


def _integer(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GroupIndexPayloadError(
            f"{field_name} must be an integer >= {minimum}")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GroupIndexPayloadError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise GroupIndexPayloadError(f"{field_name} must be a finite number")
    return 0.0 if result == 0.0 else result


def _vec3(value: Any, field_name: str) -> Vec3:
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or len(value) != 3):
        raise GroupIndexPayloadError(
            f"{field_name} must contain exactly three finite numbers")
    return (
        _number(value[0], f"{field_name}[0]"),
        _number(value[1], f"{field_name}[1]"),
        _number(value[2], f"{field_name}[2]"),
    )


def _id_array(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise GroupIndexPayloadError(f"{field_name} must be an array")
    result = tuple(
        _string(item, f"{field_name}[{index}]")
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise GroupIndexPayloadError(
            f"{field_name} contains duplicate member ids")
    return result


def _raw_element_id(row: Any, index: int) -> str:
    """id группы из СЫРОЙ строки — для квитанции о самой этой строке."""
    if isinstance(row, Mapping):
        value = row.get("element_id")
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return f"<row {index}>"


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


_RAW_BASE_FIELDS = {
    "element_id", "group_type_id", "group_type_name", "member_ids",
    "group_id_parent", "attached_detail_type_count", "status",
}
_PERSISTED_INSTANCE_FIELDS_V1 = {
    "group_type_id", "group_type_name", "member_ids", "group_id_parent",
    "attached_detail_type_count", "transform_available", "origin_mm",
    "rotation_deg",
}
_PERSISTED_INSTANCE_FIELDS = _PERSISTED_INSTANCE_FIELDS_V1 | {
    "level_binding_available", "reference_level_id",
    "origin_level_offset_mm",
}


@dataclass(frozen=True, slots=True)
class GroupInstanceRecord:
    """One normalized model-group instance."""

    element_id: str
    group_type_id: str
    group_type_name: str
    member_ids: tuple[str, ...]
    group_id_parent: str | None
    attached_detail_type_count: int
    transform_available: bool
    origin_mm: Vec3 | None
    rotation_deg: float | None
    level_binding_available: bool = False
    reference_level_id: str | None = None
    origin_level_offset_mm: float | None = None

    def __post_init__(self) -> None:
        _string(self.element_id, "GroupInstanceRecord.element_id")
        _string(self.group_type_id, "GroupInstanceRecord.group_type_id")
        _string(self.group_type_name, "GroupInstanceRecord.group_type_name")
        _id_array(list(self.member_ids), "GroupInstanceRecord.member_ids")
        parent = _optional_string(
            self.group_id_parent, "GroupInstanceRecord.group_id_parent")
        if parent == self.element_id:
            raise GroupIndexPayloadError("a group cannot be its own parent")
        _integer(
            self.attached_detail_type_count,
            "GroupInstanceRecord.attached_detail_type_count")
        if not isinstance(self.transform_available, bool):
            raise GroupIndexPayloadError(
                "GroupInstanceRecord.transform_available must be a boolean")
        if self.transform_available:
            if self.origin_mm is None or self.rotation_deg is None:
                raise GroupIndexPayloadError(
                    "available group transform requires origin_mm/rotation_deg")
            _vec3(self.origin_mm, "GroupInstanceRecord.origin_mm")
            _number(self.rotation_deg, "GroupInstanceRecord.rotation_deg")
        elif self.origin_mm is not None and self.rotation_deg is not None:
            raise GroupIndexPayloadError(
                "a complete group transform must be marked available")
        else:
            if self.origin_mm is not None:
                _vec3(self.origin_mm, "GroupInstanceRecord.origin_mm")
            if self.rotation_deg is not None:
                _number(self.rotation_deg, "GroupInstanceRecord.rotation_deg")
        if not isinstance(self.level_binding_available, bool):
            raise GroupIndexPayloadError(
                "GroupInstanceRecord.level_binding_available must be a boolean")
        if self.level_binding_available:
            if (self.reference_level_id is None
                    or self.origin_level_offset_mm is None):
                raise GroupIndexPayloadError(
                    "available group level binding requires "
                    "reference_level_id/origin_level_offset_mm")
            _string(
                self.reference_level_id,
                "GroupInstanceRecord.reference_level_id")
            _number(
                self.origin_level_offset_mm,
                "GroupInstanceRecord.origin_level_offset_mm")
        elif (self.reference_level_id is not None
              or self.origin_level_offset_mm is not None):
            raise GroupIndexPayloadError(
                "partial group level binding is not authoritative")

    @classmethod
    def from_raw(
        cls,
        value: Any,
        field_name: str = "group raw row",
    ) -> "GroupInstanceRecord":
        raw = _mapping(value, field_name)
        has_origin = "origin_ft" in raw
        has_rotation = "rotation_rad" in raw
        has_level_id = "reference_level_id" in raw
        has_level_offset = "origin_level_offset_ft" in raw
        # A transform is useful only as an inseparable origin+angle pair.
        # The observed bridge dialect omits rotation for all rows; retain that
        # as unavailable instead of inventing 0 degrees from its absence.
        fields = _RAW_BASE_FIELDS.copy()
        if has_origin:
            fields.add("origin_ft")
        if has_rotation:
            fields.add("rotation_rad")
        if has_level_id:
            fields.add("reference_level_id")
        if has_level_offset:
            fields.add("origin_level_offset_ft")
        row = _exact_fields(raw, fields, field_name)
        if row["status"] != "ok":
            raise GroupIndexPayloadError(
                f"{field_name}.status must be the literal 'ok'")
        if has_level_id != has_level_offset:
            raise GroupIndexPayloadError(
                f"{field_name} has a partial group level binding")
        origin_mm: Vec3 | None = None
        rotation_deg: float | None = None
        available = has_origin and has_rotation
        if has_origin:
            origin_ft = _vec3(row["origin_ft"], f"{field_name}.origin_ft")
            origin_mm = tuple(
                0.0 if value * _FT_TO_MM == 0.0 else value * _FT_TO_MM
                for value in origin_ft
            )
        if has_rotation:
            rotation_deg = math.degrees(_number(
                row["rotation_rad"], f"{field_name}.rotation_rad"))
            if rotation_deg == 0.0:
                rotation_deg = 0.0
        reference_level_id: str | None = None
        origin_level_offset_mm: float | None = None
        level_binding_available = False
        if has_level_id:
            raw_level_id = row["reference_level_id"]
            raw_level_offset = row["origin_level_offset_ft"]
            if (raw_level_id is None) != (raw_level_offset is None):
                raise GroupIndexPayloadError(
                    f"{field_name} has a partial group level binding")
            if raw_level_id is not None:
                reference_level_id = _string(
                    raw_level_id, f"{field_name}.reference_level_id")
                offset_ft = _number(
                    raw_level_offset,
                    f"{field_name}.origin_level_offset_ft")
                origin_level_offset_mm = (
                    0.0 if offset_ft * _FT_TO_MM == 0.0
                    else offset_ft * _FT_TO_MM
                )
                level_binding_available = True
        return cls(
            element_id=_string(row["element_id"], f"{field_name}.element_id"),
            group_type_id=_string(
                row["group_type_id"], f"{field_name}.group_type_id"),
            group_type_name=_string(
                row["group_type_name"], f"{field_name}.group_type_name"),
            member_ids=_id_array(row["member_ids"], f"{field_name}.member_ids"),
            group_id_parent=_optional_string(
                row["group_id_parent"], f"{field_name}.group_id_parent"),
            attached_detail_type_count=_integer(
                row["attached_detail_type_count"],
                f"{field_name}.attached_detail_type_count"),
            transform_available=available,
            origin_mm=origin_mm,
            rotation_deg=rotation_deg,
            level_binding_available=level_binding_available,
            reference_level_id=reference_level_id,
            origin_level_offset_mm=origin_level_offset_mm,
        )

    @classmethod
    def from_dict(
        cls,
        element_id: str,
        value: Any,
        field_name: str = "group index instance",
    ) -> "GroupInstanceRecord":
        raw = _mapping(value, field_name)
        field_set = set(raw)
        if field_set == _PERSISTED_INSTANCE_FIELDS:
            row = raw
            has_level_binding = True
        elif field_set == _PERSISTED_INSTANCE_FIELDS_V1:
            row = raw
            has_level_binding = False
        else:
            row = _exact_fields(
                raw, _PERSISTED_INSTANCE_FIELDS, field_name)
            has_level_binding = True
        available = row["transform_available"]
        if not isinstance(available, bool):
            raise GroupIndexPayloadError(
                f"{field_name}.transform_available must be a boolean")
        level_available = (
            row["level_binding_available"] if has_level_binding else False)
        if not isinstance(level_available, bool):
            raise GroupIndexPayloadError(
                f"{field_name}.level_binding_available must be a boolean")
        return cls(
            element_id=_string(element_id, f"{field_name} key"),
            group_type_id=_string(
                row["group_type_id"], f"{field_name}.group_type_id"),
            group_type_name=_string(
                row["group_type_name"], f"{field_name}.group_type_name"),
            member_ids=_id_array(row["member_ids"], f"{field_name}.member_ids"),
            group_id_parent=_optional_string(
                row["group_id_parent"], f"{field_name}.group_id_parent"),
            attached_detail_type_count=_integer(
                row["attached_detail_type_count"],
                f"{field_name}.attached_detail_type_count"),
            transform_available=available,
            origin_mm=(
                _vec3(row["origin_mm"], f"{field_name}.origin_mm")
                if row["origin_mm"] is not None else None),
            rotation_deg=(
                _number(row["rotation_deg"], f"{field_name}.rotation_deg")
                if row["rotation_deg"] is not None else None),
            level_binding_available=level_available,
            reference_level_id=(
                _optional_string(
                    row["reference_level_id"],
                    f"{field_name}.reference_level_id")
                if has_level_binding else None),
            origin_level_offset_mm=(
                _number(
                    row["origin_level_offset_mm"],
                    f"{field_name}.origin_level_offset_mm")
                if (has_level_binding
                    and row["origin_level_offset_mm"] is not None)
                else None),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_type_id": self.group_type_id,
            "group_type_name": self.group_type_name,
            "member_ids": list(self.member_ids),
            "group_id_parent": self.group_id_parent,
            "attached_detail_type_count": self.attached_detail_type_count,
            "transform_available": self.transform_available,
            "origin_mm": (
                list(self.origin_mm) if self.origin_mm is not None else None),
            "rotation_deg": self.rotation_deg,
            "level_binding_available": self.level_binding_available,
            "reference_level_id": self.reference_level_id,
            "origin_level_offset_mm": self.origin_level_offset_mm,
        }


@dataclass(frozen=True, slots=True)
class GroupSlot:
    """One ordinal slot witnessed on a definition's reference instance."""

    ordinal: int
    reference_member_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_key": f"member[{self.ordinal}]",
            "ordinal": self.ordinal,
            "reference_member_id": self.reference_member_id,
        }


@dataclass(frozen=True, slots=True)
class GroupDefinition:
    """A deterministic definition inferred without equating instance ids."""

    group_type_id: str
    group_type_name: str
    reference_instance_id: str
    instance_ids: tuple[str, ...]
    slots: tuple[GroupSlot, ...]
    comparison_basis: str = "ordered_cardinality_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_type_name": self.group_type_name,
            "reference_instance_id": self.reference_instance_id,
            "instance_ids": list(self.instance_ids),
            "slots": [slot.to_dict() for slot in self.slots],
            "comparison_basis": self.comparison_basis,
        }


@dataclass(frozen=True, slots=True)
class GroupCompositionMismatch:
    """One instance cardinality differs from its reference definition."""

    group_type_id: str
    reference_instance_id: str
    instance_id: str
    expected_member_count: int
    actual_member_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_type_id": self.group_type_id,
            "reference_instance_id": self.reference_instance_id,
            "instance_id": self.instance_id,
            "expected_member_count": self.expected_member_count,
            "actual_member_count": self.actual_member_count,
            "reason": "ordered_member_cardinality_mismatch",
        }


def _derive_definitions(
    records: Sequence[GroupInstanceRecord],
) -> tuple[tuple[GroupDefinition, ...], tuple[GroupCompositionMismatch, ...]]:
    by_type: dict[str, list[GroupInstanceRecord]] = {}
    for record in records:
        by_type.setdefault(record.group_type_id, []).append(record)
    definitions = []
    mismatches = []
    for type_id, instances in sorted(
            by_type.items(), key=lambda item: _element_id_key(item[0])):
        names = {instance.group_type_name for instance in instances}
        if len(names) != 1:
            raise GroupIndexPayloadError(
                f"group type {type_id!r} has inconsistent names")
        # The largest observed member sequence is the least-lossy canonical
        # witness when exclusions exist. Numeric/source-id order breaks ties.
        reference = min(
            instances,
            key=lambda item: (
                -len(item.member_ids), _element_id_key(item.element_id)))
        ordered_instances = tuple(sorted(
            (instance.element_id for instance in instances),
            key=_element_id_key,
        ))
        definition = GroupDefinition(
            group_type_id=type_id,
            group_type_name=reference.group_type_name,
            reference_instance_id=reference.element_id,
            instance_ids=ordered_instances,
            slots=tuple(
                GroupSlot(index, member_id)
                for index, member_id in enumerate(reference.member_ids)
            ),
        )
        definitions.append(definition)
        for instance in sorted(instances, key=lambda item: _element_id_key(
                item.element_id)):
            if len(instance.member_ids) == len(reference.member_ids):
                continue
            mismatches.append(GroupCompositionMismatch(
                group_type_id=type_id,
                reference_instance_id=reference.element_id,
                instance_id=instance.element_id,
                expected_member_count=len(reference.member_ids),
                actual_member_count=len(instance.member_ids),
            ))
    return tuple(definitions), tuple(mismatches)


@dataclass(frozen=True, slots=True)
class GroupExtraction:
    """Validated group instances plus evidence-bounded definitions.

    §18.2: ``failures`` — вторая половина ответа, а не приложение к нему.
    Стадия полномодельная (у группы нет L0-категории), поэтому сверить её
    ответ со списком запрошенных id нельзя; тем важнее, чтобы группу, которую
    обрезал бюджет или не дал прочитать API, было видно ПОИМЁННО.
    """

    records: tuple[GroupInstanceRecord, ...]
    failures: tuple[SideFailure, ...] = ()

    def __post_init__(self) -> None:
        ids = [record.element_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise GroupIndexPayloadError(
                "group index contains duplicate element_id")
        object.__setattr__(self, "records", tuple(sorted(
            self.records, key=lambda item: _element_id_key(item.element_id))))
        object.__setattr__(self, "failures", sorted_failures(self.failures))

    def __iter__(self) -> Iterator[GroupInstanceRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def instances(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.records, key=lambda item: _element_id_key(item.element_id))
        }

    @property
    def definitions(self) -> tuple[GroupDefinition, ...]:
        return _derive_definitions(self.records)[0]

    @property
    def composition_mismatches(self) \
            -> tuple[GroupCompositionMismatch, ...]:
        return _derive_definitions(self.records)[1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GROUP_INDEX_SCHEMA_VERSION,
            "group_index": {
                "instances": self.instances,
                "definitions": {
                    definition.group_type_id: definition.to_dict()
                    for definition in self.definitions
                },
                "composition_mismatches": [
                    mismatch.to_dict()
                    for mismatch in self.composition_mismatches
                ],
            },
            "failures": [failure.to_dict() for failure in self.failures],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[Any],
        *,
        wire_failures: Iterable[Any] | None = None,
    ) -> "GroupExtraction":
        """Построчный карантин: битая строка — квитанция, а не смерть прогона."""
        records: list[GroupInstanceRecord] = []
        failures: list[SideFailure] = list(
            parse_wire_failures(
                list(wire_failures) if wire_failures is not None else None,
                "group wire failures"))
        for index, row in enumerate(rows):
            try:
                records.append(GroupInstanceRecord.from_raw(
                    row, f"group raw row[{index}]"))
            except GroupIndexPayloadError as exc:
                failures.append(SideFailure(
                    _raw_element_id(row, index),
                    str(exc)[:300],
                    typed_reason=SideFailureReason.ROW_UNPARSABLE))
        return cls(tuple(records), tuple(failures))

    @classmethod
    def from_jsonl(cls, value: str) -> "GroupExtraction":
        records = []
        for line_number, line in enumerate(value.splitlines(), start=1):
            if not line.strip():
                raise GroupIndexPayloadError(
                    f"group JSONL line {line_number} is blank")
            try:
                raw = json.loads(line)
            except (TypeError, ValueError) as exc:
                raise GroupIndexPayloadError(
                    f"group JSONL line {line_number} is invalid: {exc}") from exc
            records.append(GroupInstanceRecord.from_raw(
                raw, f"group JSONL line {line_number}"))
        return cls(tuple(records))

    @classmethod
    def load_jsonl(cls, path: str | Path) -> "GroupExtraction":
        with Path(path).open("r", encoding="utf-8") as stream:
            records = []
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise GroupIndexPayloadError(
                        f"group JSONL line {line_number} is blank")
                try:
                    raw = json.loads(line)
                except (TypeError, ValueError) as exc:
                    raise GroupIndexPayloadError(
                        f"group JSONL line {line_number} is invalid: {exc}") \
                        from exc
                records.append(GroupInstanceRecord.from_raw(
                    raw, f"group JSONL line {line_number}"))
        return cls(tuple(records))

    @classmethod
    def from_dict(cls, value: Any) -> "GroupExtraction":
        # ``failures`` необязателен на чтении и обязателен на записи: разборы,
        # снятые до этой волны, ключа не несут (та же осознанная миграция, что
        # у полей рабочих наборов §18.4).
        raw_root = _mapping(value, "persisted group extraction")
        root = _exact_fields(
            raw_root,
            ({"schema_version", "group_index", "failures"}
             if "failures" in raw_root
             else {"schema_version", "group_index"}),
            "persisted group extraction")
        if root["schema_version"] not in {
                GROUP_INDEX_SCHEMA_VERSION,
                LEGACY_GROUP_INDEX_SCHEMA_VERSION,
        }:
            raise GroupIndexPayloadError("group index schema_version mismatch")
        bundle = _exact_fields(root["group_index"], {
            "instances", "definitions", "composition_mismatches",
        }, "persisted group extraction.group_index")
        raw_instances = _mapping(
            bundle["instances"],
            "persisted group extraction.group_index.instances")
        result = cls(
            tuple(
                GroupInstanceRecord.from_dict(
                    element_id, row,
                    f"persisted group extraction.instances[{element_id!r}]",
                )
                for element_id, row in sorted(
                    raw_instances.items(),
                    key=lambda item: _element_id_key(item[0]))
            ),
            parse_wire_failures(
                root.get("failures"),
                "persisted group extraction.failures"),
        )
        # Definitions are derivations, never a second authority. Strictly
        # compare their canonical persisted form to expose tampering/drift.
        canonical = result.to_dict()["group_index"]
        if bundle["definitions"] != canonical["definitions"]:
            raise GroupIndexPayloadError(
                "persisted group definitions disagree with instances")
        if (bundle["composition_mismatches"]
                != canonical["composition_mismatches"]):
            raise GroupIndexPayloadError(
                "persisted group mismatches disagree with instances")
        return result

    @classmethod
    def from_json(
        cls,
        value: str | bytes | bytearray,
    ) -> "GroupExtraction":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise GroupIndexPayloadError(
                f"group index is not valid JSON: {exc}") from exc
        return cls.from_dict(decoded)


def parse_group_index(
    value: GroupExtraction | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a strict canonical bundle; ``None`` stays absent."""

    if value is None:
        return None
    if isinstance(value, GroupExtraction):
        return value.to_dict()
    raw = _mapping(value, "group_index")
    if "schema_version" in raw or "group_index" in raw:
        return GroupExtraction.from_dict(raw).to_dict()
    bundle_fields = {"instances", "definitions", "composition_mismatches"}
    if set(raw) == bundle_fields:
        return GroupExtraction.from_dict({
            "schema_version": GROUP_INDEX_SCHEMA_VERSION,
            "group_index": raw,
        }).to_dict()
    # Direct instance index, symmetric with profile/family direct-index use.
    return GroupExtraction(tuple(
        GroupInstanceRecord.from_dict(
            element_id,
            row,
            f"group_index.instances[{element_id!r}]",
        )
        for element_id, row in sorted(
            raw.items(), key=lambda item: _element_id_key(item[0]))
    )).to_dict()


# ── Deterministic Revit C# emission ─────────────────────────────────────────
#
# This is an Execute-method body for the same ``wrap_user_code`` path used in
# serving.  It opens no Transaction and never calls get_Geometry/Tessellate.
#
# Requested-ids decision (documented per the master design A1 order — "groups:
# все"): the pipeline registers this stage with ``whole_model=True`` and an
# EMPTY L0 category set (``_STAGE_CATEGORIES["group"] = frozenset()``), because
# a Revit group is not one of the extracted L0 categories — there is no L0 id
# list to page over.  So this collector takes NO requested ids and walks every
# model group itself via ``FilteredElementCollector.OfClass(typeof(Autodesk.Revit.DB.Group))``,
# ordered by numeric id for determinism (I4).  The whole pass is bounded by a
# single cooperative call budget (I7): it never brute-forces per element.
#
# ``origin_ft`` is emitted ALONE, and ``rotation_rad`` is never emitted at all.
#
# Эта строчка раньше читалась наоборот, и стоила дороже всего остального в
# файле. Стояло так: «наблюдаемый диалект моста, в котором угла нет, — это
# ограничение МОСТА, а не контракт; LocationPoint отдаёт Rotation напрямую,
# значит честно отдавать оба». Первая половина верна как наблюдение, вывод —
# нет: угла в диалекте не было не потому, что мост не умел, а потому что
# ЭТОГО ЧТЕНИЯ У ГРУППЫ НЕ СУЩЕСТВУЕТ. Autodesk пишет это сам, дословно и
# одинаково во всех шести поддерживаемых версиях (RevitAPI.xml,
# ``P:Autodesk.Revit.DB.LocationPoint.Rotation``):
#
#   "This property is not supported for some elements supporting
#    LocationPoints, such as AssemblyInstances, GROUPS, ModelText, Room, and
#    SpotDimensions."
#   throws ``InvalidOperationException``.
#
# Цена вывода — ЗАМЕР на 13A-RD-AR-K2_v33: 2846 групп из 2941 (96.77%) не
# попали в индекс вообще, все с одной строкой «group read failed:
# InvalidOperationException». Выжили ровно 95 вложенных групп, у которых
# ``Location`` пуст, и потому запретное чтение не выполнялось ни разу.
#
# Мораль общая и стоит того, чтобы её здесь оставить: НАБЛЮДАЕМЫЙ ДИАЛЕКТ —
# ЭТО ДАННЫЕ. Отсутствие поля объясняют, а не устраняют; «мост не дочитал» и
# «API этого не отдаёт» неразличимы на глаз и различаются только чтением
# документации на конкретный член.
#
# ``reference_level_id``/``origin_level_offset_ft`` остаются неразделимой
# парой свидетельства: смещение меряется от ``Level.Elevation`` до той самой
# живой точки группы.  Точка и смещение уходят на провод в СЫРЫХ внутренних
# футах; строгий разборщик владеет пересчётом единиц.
#
# ``attached_detail_type_count`` = ``GroupType.GetAvailableAttachedDetailGroup
# TypeIds().Count`` (an ``ISet<ElementId>`` read, available since Revit 2019.1
# on ``GroupType``; confirmed against RevitAPI.xml member
# ``M:Autodesk.Revit.DB.GroupType.GetAvailableAttachedDetailGroupTypeIds``).
# It is a cheap, read-only count of the attached-detail-group TYPES available
# to the group's type; a read that throws falls back to 0 (the parser accepts
# ``>= 0``).
#
# Fail-closed contract (I2): a group whose type/name/members cannot be fully
# read is left ABSENT from the ``groups`` list rather than emitted as a wrong
# row — the strict ``from_raw`` parser only accepts ``status == "ok"`` rows.


GROUP_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE Wave A1b — read-only model-group instance helpers.
// Origin crosses the wire in RAW internal feet, rotation in RAW radians;
// the offline parser owns unit conversion. No Transaction opens.
// Имя класса БЕЗ обращения к среде выполнения за типом: та форма записи
// целиком отвергается валидатором безопасности моста версий до 06.07.2026,
// который всё ещё стоит на части флота, — тело браковалось бы на машине
// пользователя ДО компиляции, и сервер об этом не узнавал бы.
// Object.ToString() у Element/Curve/Surface и у исключений — это полное имя
// типа CLR: из Autodesk.Revit.DB его перекрывают только ElementId, UV, XYZ,
// WorksetId, ScheduleFieldId и PolymeshFacet (замер по индексу ловушек), и
// ни один из них сюда не передаётся. Исключение дописывает ": сообщение" и
// стек, поэтому срез идёт по первому переводу строки и первому двоеточию.
// Результат побайтно равен прежнему .Name.
Func<object, string> __grClassName = (__grcnObj) =>
{
    if (__grcnObj == null) return "";
    string __grcn = __grcnObj.ToString();
    if (__grcn == null) return "";
    int __grcnCut = __grcn.IndexOf((char)10);
    if (__grcnCut >= 0) __grcn = __grcn.Substring(0, __grcnCut);
    __grcnCut = __grcn.IndexOf(':');
    if (__grcnCut >= 0) __grcn = __grcn.Substring(0, __grcnCut);
    __grcn = __grcn.Trim();
    __grcnCut = __grcn.LastIndexOf('.');
    return __grcnCut >= 0 && __grcnCut + 1 < __grcn.Length
        ? __grcn.Substring(__grcnCut + 1) : __grcn;
};
Func<XYZ, bool> __grFiniteXYZ = (__point) =>
    __point != null
    && !Double.IsNaN(__point.X) && !Double.IsInfinity(__point.X)
    && !Double.IsNaN(__point.Y) && !Double.IsInfinity(__point.Y)
    && !Double.IsNaN(__point.Z) && !Double.IsInfinity(__point.Z);
Func<double, bool> __grFinite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
Func<XYZ, object> __grRawPoint = (__point) => (object)new double[] {
    __point.X, __point.Y, __point.Z
};
Func<ElementId, string> __grValidIdString = (__id) =>
    (__id == null || __id == ElementId.InvalidElementId)
        ? null : __id.ToString();
// Version-safe numeric id ordering key: ElementId.ToString() + Int64.TryParse
// (the 32-bit integer id accessor is gone in 2026). Non-numeric ids sort last.
Func<ElementId, long> __grIdOrder = (__id) =>
{
    long __value = 0L;
    if (__id != null && Int64.TryParse(__id.ToString(), out __value))
        return __value;
    return Int64.MaxValue;
};
"""


_GROUP_EXTRACT_BODY_CS = r"""
long __grCallBudgetMs = __GR_CALL_BUDGET_MS__L;
long __grCallWatchT0 = DateTime.UtcNow.Ticks;

// §18.2, закон квитанции: группа, которую съел бюджет или не дал прочитать
// API, обязана назваться. Стадия полномодельная — сверить её ответ со
// списком запрошенных id нельзя, и именно поэтому немой `break`/`continue`
// здесь опаснее, чем где-либо ещё: снаружи «групп нет» и «мы до групп не
// дошли» выглядели одинаково.
var __grFailures = new List<object>();
Action<string, string, string, object> __grFail =
    (__failedId, __reason, __typed, __elapsed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __failure["elapsed_ms"] = __elapsed;
    __grFailures.Add(__failure);
};

// Only fully-read groups are emitted (I2 fail-closed by absence from the
// INSTANCE list — never from the answer). The whole pass is bounded by one
// cooperative call budget (I7) — never per-element brute force.
// Deterministic order: numeric ElementId ascending (I4).
// "Group"/"GroupType" are fully qualified: the serving wrapper's usings pull
// in System.Text.RegularExpressions, whose Group makes the bare name CS0104
// (caught by the live 6-version gate, not guessed).
//
// Список материализуется ДО чтения: OrderBy всё равно буферизует коллектор
// целиком, так что ToList не добавляет прохода, зато даёт то, чего раньше не
// было, — знание, СКОЛЬКО групп осталось за бюджетом и как их зовут.
var __grAll = new FilteredElementCollector(__src)
    .OfClass(typeof(Autodesk.Revit.DB.Group))
    .WhereElementIsNotElementType()
    .Cast<Autodesk.Revit.DB.Group>()
    .OrderBy(__item => __grIdOrder(__item.Id))
    .ToList();

var __grGroups = new List<object>();
bool __grBudgetOut = false;
foreach (Autodesk.Revit.DB.Group __group in __grAll)
{
    string __groupId = "<unresolved group>";
    try { __groupId = __group.Id.ToString(); } catch { }
    if (__grBudgetOut
        || ((DateTime.UtcNow.Ticks - __grCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __grCallBudgetMs)
    {
        __grBudgetOut = true;
        __grFail(__groupId, "call_budget_exhausted", "call_budget_exhausted",
                 (object)((DateTime.UtcNow.Ticks - __grCallWatchT0) / TimeSpan.TicksPerMillisecond));
        continue;
    }
    // ИМЯ ЧТЕНИЯ, КОТОРОЕ СЕЙЧАС ИДЁТ. Тип исключения без имени вызова —
    // это одно ведро на всё: на 13A-RD-AR-K2_v33 в него легли 2846 групп
    // одной строкой «group read failed: InvalidOperationException», и по ней
    // нельзя было сказать ни ЧТО читали, ни ЧТО ответил Revit.
    string __grStep = "Group.Id";
    try
    {
        __grStep = "Group.GroupType";
        Autodesk.Revit.DB.GroupType __groupType = __group.GroupType;
        if (__groupType == null)
        {
            __grFail(__groupId, "group has no GroupType",
                     "element_kind_mismatch", null);
            continue;
        }
        // GroupType.Name getter is non-public; the public Element.Name getter
        // is the version-safe read of the group-type name.
        __grStep = "Element.Name on GroupType";
        string __typeName = ((Element)__groupType).Name;
        if (String.IsNullOrEmpty(__typeName))
        {
            __grFail(__groupId, "group type name is empty",
                     "element_kind_mismatch", null);
            continue;
        }

        var __memberIds = new List<object>();
        __grStep = "Group.GetMemberIds";
        var __members = __group.GetMemberIds();
        if (__members != null)
            foreach (ElementId __memberId in __members)
            {
                if (__memberId == null) continue;
                __memberIds.Add(__memberId.ToString());
            }

        // attached-detail-group TYPES available to this group's type. Cheap
        // read-only ISet<ElementId> count (Revit 2019.1+ on GroupType); a
        // throw falls back to 0, which the parser accepts (>= 0).
        // ВЫЗОВ УБРАН, И ЭТО НЕ ЛЕНЬ. `GetAvailableAttachedDetailGroupTypeIds`
        // возвращает `ISet<ElementId>`, а `ISet<>` на net48 объявлен в
        // `System.dll`, которой нет в замыкании ссылок РАЗВЁРНУТОГО плагина.
        // Живой замер 04.08: `CS0012: The type 'ISet<>' is defined in an
        // assembly that is not referenced` плюс `CS0030: Cannot convert type
        // 'method' to 'long'` — вторая ошибка следствие первой: без интерфейса
        // `.Count` вырождается в метод-группу LINQ.
        //
        // ОБОЙТИ КАСТОМ НЕЛЬЗЯ: любое использование выражения требует, чтобы
        // компилятор загрузил его тип, — приведение к `object` или
        // `IEnumerable` этого не снимает. Значит выбор был между «не читать
        // это поле» и «не читать группы вообще»; поле необязательное (парсер
        // принимает >= 0, что и было заявлено прежним комментарием), а группы
        // обязательны.
        //
        // НОВЫЙ РОД МИНЫ, и его стоит знать: она не в том, что МЫ ПИШЕМ, а в
        // том, что мы ВЫЗЫВАЕМ. Тип возврата чужого метода тянет за собой
        // несуществующую сборку, и сторож `bridge_reference_closure`, который
        // судит имена в нашем тексте, такое не видит по построению.
        //
        // ВЕРНУТЬ, когда у клиента появится `System.dll` в замыкании: снять
        // этот блок и восстановить прежние четыре строки.
        long __attachedCount = 0L;
        __grStep = "GroupType.GetAvailableAttachedDetailGroupTypeIds:skipped";

        var __row = new Dictionary<string, object>();
        __row["element_id"] = __groupId;
        __row["group_type_id"] = __groupType.Id.ToString();
        __row["group_type_name"] = __typeName;
        __row["member_ids"] = __memberIds;
        // A group nested inside another group carries a valid parent GroupId;
        // a top-level group's GroupId is InvalidElementId, emitted as null.
        __row["group_id_parent"] = __grValidIdString(__group.GroupId);
        __row["attached_detail_type_count"] = (object)__attachedCount;
        // v2: group-storey binding. Always expose both keys so "observed
        // unavailable" is distinct from a legacy v1 row that never measured
        // the binding. A non-null binding is emitted only as a complete pair.
        __row["reference_level_id"] = null;
        __row["origin_level_offset_ft"] = null;
        __row["status"] = "ok";

        // У ГРУППЫ ЧИТАЕТСЯ ТОЧКА И НЕ ЧИТАЕТСЯ УГОЛ. Это не наше решение и
        // не осторожность — так написано у Autodesk, дословно и одинаково во
        // всех шести поддерживаемых версиях (RevitAPI.xml,
        // P:Autodesk.Revit.DB.LocationPoint.Rotation):
        //
        //   "This property is not supported for some elements supporting
        //    LocationPoints, such as AssemblyInstances, GROUPS, ModelText,
        //    Room, and SpotDimensions."
        //   throws InvalidOperationException: "The rotation property is not
        //    supported for the Element related to this LocationPoint."
        //
        // Пока `__location.Rotation` стояло здесь, оно бросало у КАЖДОЙ
        // размещённой группы — то есть всегда и в любой модели — и уносило
        // весь ряд вместе с типом, именем и составом, прочитанными строкой
        // выше. ЗАМЕР 13A-RD-AR-K2_v33: 2846 групп из 2941 (96.77%) ушли в
        // квитанции, а выжили ровно 95 ВЛОЖЕННЫХ, у которых Location пуст и
        // до запретного чтения дело не доходило. Совпадение «выжил ⇔ нет
        // локации» точное, оно и указало на виновника.
        //
        // Угол группы этим API не достаётся никак (у Group нет ни Transform,
        // ни иного публичного источника поворота), поэтому ряд уходит с
        // origin_ft БЕЗ rotation_rad — ровно тот диалект, под который строгий
        // разборщик уже написан: «retain that as unavailable instead of
        // inventing 0 degrees from its absence».
        //
        // ПРАВИЛО, А НЕ ЗАПЛАТА: удостоверение группы — это тип, имя и
        // состав; всё остальное ДОБАВКА, и добавка, которая не прочиталась,
        // вправе стоить своего поля и ничего сверх него. Поэтому у каждого
        // такого чтения свой guard.
        __grStep = "Group.Location/LocationPoint.Point";
        try
        {
            LocationPoint __location = __group.Location as LocationPoint;
            if (__location != null)
            {
                XYZ __origin = __location.Point;
                if (__grFiniteXYZ(__origin))
                {
                    __row["origin_ft"] = __grRawPoint(__origin);
                    try
                    {
                        ElementId __referenceLevelId = __group.LevelId;
                        Autodesk.Revit.DB.Level __referenceLevel =
                            __src.GetElement(__referenceLevelId)
                            as Autodesk.Revit.DB.Level;
                        if (__referenceLevelId != null
                            && __referenceLevelId != ElementId.InvalidElementId
                            && __referenceLevel != null
                            && __grFinite(__referenceLevel.Elevation))
                        {
                            double __originLevelOffset =
                                __origin.Z - __referenceLevel.Elevation;
                            if (__grFinite(__originLevelOffset))
                            {
                                __row["reference_level_id"] =
                                    __referenceLevelId.ToString();
                                __row["origin_level_offset_ft"] =
                                    __originLevelOffset;
                            }
                        }
                    }
                    catch (Exception) { /* keep the explicit null/null pair */ }
                }
            }
        }
        catch (Exception __originError)
        {
            // РЯД СОХРАНЯЕТСЯ: точка — не удостоверение группы. Квитанция
            // диагностическая (стадия полномодельная, сверки заказа у неё
            // нет), и она называет то, что раньше было бы молчанием.
            __grFail(__groupId,
                     "group origin unread, row kept: "
                     + __grClassName(__originError) + ": "
                     + __originError.Message,
                     "read_failed", null);
        }
        __grGroups.Add(__row);
    }
    catch (Exception __groupError)
    {
        // fail-closed by absence from the INSTANCE list, never from the answer.
        // Имя шага + СООБЩЕНИЕ, а не только тип: тип в одиночку — это ведро,
        // в котором 2846 групп выглядели одним событием.
        __grFail(__groupId,
                 "group read failed at " + __grStep + ": "
                 + __grClassName(__groupError) + ": " + __groupError.Message,
                 "read_failed", null);
    }
}
return new Dictionary<string, object> {
    {"schema_version", "__GR_SCHEMA_VERSION__"},
    {"groups", __grGroups},
    {"failures", __grFailures}
};
"""


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


def build_group_extract_cs(
    *,
    call_budget_ms: int = 20_000,
    link_title: str | None = None,
) -> str:
    """Emit one deterministic, read-only model-group Execute body.

    Takes NO requested ids: a Revit group is not an extracted L0 category, so
    there is no id list to page over.  The collector walks every model group
    itself via ``FilteredElementCollector.OfClass(typeof(Autodesk.Revit.DB.Group))``, ordered by
    numeric ``ElementId`` for determinism (I4), under a single cooperative
    call budget (I7 — never per-element brute force).

    Origin and origin-level offset cross the wire as RAW internal feet; the
    strict :meth:`GroupInstanceRecord.from_raw` parser owns the sole
    feet→millimetre conversion.  A group's ROTATION is not emitted, because
    Autodesk documents ``LocationPoint.Rotation`` as unsupported for ``Group``
    in every supported version — see the wire-contract note above and
    ``GroupRotationIsUnsupportedByTheApiTests``.

    Fail-closed (I2) applies to IDENTITY only: a group whose type, name or
    members cannot be read is left absent from the ``groups`` list rather than
    mislabelled as a usable row.  An optional field that cannot be read costs
    that field alone — the row survives, and the receipt says which read went
    missing.  Those two rules used to be one, and the strict version threw away
    2846 of 2941 groups on one real building over a property the API was never
    going to return.

    ``link_title`` — читать не ХОЗЯИНА, а его СВЯЗЬ с таким ``Document.Title``.
    Стадия полномодельная, и это делает её случай ХУЖЕ страничных: заказа она
    не делает, поэтому сверять нечего, и группы хозяина приехали бы под видом
    групп связи — без единой квитанции, при идеальном счётчике строк.

    ЗАМЕР 30.07 (``snowdon_elec_v1``) показал НОЛЬ групп и ноль квитанций, и
    это НЕ доказательство исправности: в документе-хозяине (сантехника)
    модельных групп просто не было. Пустой ответ здесь неотличим от верного —
    ровно поэтому источник обязан быть задан, а не выведен из результата.
    """

    if (isinstance(call_budget_ms, bool)
            or not isinstance(call_budget_ms, int) or call_budget_ms <= 0):
        raise ValueError("call_budget_ms must be a positive integer")
    if call_budget_ms > 9_223_372_036_854_775_807:
        raise ValueError("call_budget_ms exceeds the C# Int64 range")

    body = (
        _GROUP_EXTRACT_BODY_CS
        .replace("__GR_CALL_BUDGET_MS__", str(call_budget_ms))
        .replace("__GR_SCHEMA_VERSION__", GROUP_EXTRACT_SCHEMA_VERSION)
    )
    if "__GR_" in body:
        raise GroupIndexPayloadError(
            "internal group emitter placeholder was not resolved")
    return (
        source_binding_cs(link_title)
        + "\n" + GROUP_EXTRACT_HELPER_CS.strip()
        + "\n" + body.strip())


__all__ = [
    "GROUP_INDEX_SCHEMA_VERSION",
    "LEGACY_GROUP_INDEX_SCHEMA_VERSION",
    "GROUP_EXTRACT_SCHEMA_VERSION",
    "GROUP_EXTRACT_HELPER_CS",
    "GroupCompositionMismatch",
    "GroupDefinition",
    "GroupExtraction",
    "GroupIndexPayloadError",
    "GroupInstanceRecord",
    "GroupSlot",
    "build_group_extract_cs",
    "parse_group_index",
]
