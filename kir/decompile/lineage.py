"""Derived chain materialization -> plan -> runtime, with no new truth.

The module saves nothing and assigns no identifiers.  It only joins
already-existing typed facts:

* :class:`MaterializationAccounting` — source ElementId, L1 id, KIR op, and
  program index;
* :class:`PlannedProgram` — the exact ``plan_digest``;
* ``kir-created-ledger/1`` rows — which ElementIds Revit returned for a
  specific plan and operation.

A missing witness stays ``None``.  In particular, ``op_id`` is never turned
into an ElementId, a source ElementId is never passed off as the id of the
rebuilt element, and a runtime row with no matching ``plan_digest`` is not
joined.

``BuildingGraph`` is deliberately not wired in here: ``MaterializationAccounting``
does not yet carry document/run identity or a graph-artifact digest. ElementId
is local to a document, so matching an id row without a shared anchor could
glue two different buildings together. The needed link must appear at the
source, not as a guess made by this view.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from kir.created_ledger import SCHEMA_VERSION as CREATED_LEDGER_SCHEMA
from kir.decompile.materialize import MaterializeResult
from kir.registry_base import EffectKind, IdentityCardinality

__all__ = [
    "DerivedLineage",
    "DerivedLineageRow",
    "LineageError",
    "derive_lineage",
]


class LineageError(ValueError):
    """The submitted witnesses cannot be joined without a guess."""


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


@dataclass(frozen=True, slots=True)
class DerivedLineageRow:
    """One immutable, non-authoritative projection of already-proven facts."""

    source_element_id: str
    l1_id: str
    leaf_kind: str
    materialization_disposition: str
    residual_reason: str | None
    kir_op_id: str | None
    kir_op_name: str | None
    program_index: int | None
    plan_digest: str | None
    runtime_record_present: bool
    runtime_document_key: str | None
    runtime_device_id: str | None
    runtime_element_ids: tuple[str, ...] | None

    def __post_init__(self) -> None:
        for name, value in (
            ("source_element_id", self.source_element_id),
            ("l1_id", self.l1_id),
            ("leaf_kind", self.leaf_kind),
            ("materialization_disposition", self.materialization_disposition),
        ):
            if not isinstance(value, str) or not value:
                raise TypeError(f"lineage {name} must be non-empty")
        if self.residual_reason is not None and (
                not isinstance(self.residual_reason, str)
                or not self.residual_reason):
            raise TypeError("lineage residual_reason must be non-empty or null")
        if self.kir_op_id is None:
            if (self.kir_op_name is not None
                    or self.program_index is not None
                    or self.plan_digest is not None):
                raise ValueError("an absent KIR op cannot carry plan identity")
        else:
            if not isinstance(self.kir_op_id, str) or not self.kir_op_id:
                raise TypeError("lineage kir_op_id must be non-empty or null")
            if not isinstance(self.kir_op_name, str) or not self.kir_op_name:
                raise TypeError("a KIR op needs its operation name")
            if (isinstance(self.program_index, bool)
                    or not isinstance(self.program_index, int)
                    or self.program_index < 0):
                raise TypeError("a KIR op needs a non-negative program index")
        if self.plan_digest is not None and not _is_sha256(self.plan_digest):
            raise ValueError("lineage plan_digest must be SHA-256 or null")
        if not isinstance(self.runtime_record_present, bool):
            raise TypeError("runtime_record_present must be bool")
        if self.runtime_record_present and self.plan_digest is None:
            raise ValueError(
                "a runtime record cannot bind without a planned digest")
        if not self.runtime_record_present and (
                self.runtime_document_key is not None
                or self.runtime_device_id is not None
                or self.runtime_element_ids is not None):
            raise ValueError("runtime facts require a matching runtime record")
        for name, value in (
            ("runtime_document_key", self.runtime_document_key),
            ("runtime_device_id", self.runtime_device_id),
        ):
            if value is not None and (
                    not isinstance(value, str) or not value):
                raise TypeError(f"{name} must be non-empty or null")
        if self.runtime_element_ids is not None:
            if self.kir_op_id is None:
                raise ValueError("runtime ids require a KIR op")
            if (not isinstance(self.runtime_element_ids, tuple)
                    or any(not isinstance(value, str) or not value
                           for value in self.runtime_element_ids)):
                raise TypeError(
                    "runtime_element_ids must be immutable non-empty strings")

    def as_dict(self) -> dict[str, Any]:
        """JSON with explicit nulls: an omission cannot pass itself off as evidence."""

        return {
            "source_element_id": self.source_element_id,
            "l1_id": self.l1_id,
            "leaf_kind": self.leaf_kind,
            "materialization_disposition": self.materialization_disposition,
            "residual_reason": self.residual_reason,
            "kir_op_id": self.kir_op_id,
            "kir_op_name": self.kir_op_name,
            "program_index": self.program_index,
            "plan_digest": self.plan_digest,
            "runtime_record_present": self.runtime_record_present,
            "runtime_document_key": self.runtime_document_key,
            "runtime_device_id": self.runtime_device_id,
            "runtime_element_ids": (
                list(self.runtime_element_ids)
                if self.runtime_element_ids is not None else None),
        }


@dataclass(frozen=True, slots=True)
class DerivedLineage:
    """A transient projection; the parent receipt remains the authority."""

    materialization_receipt_digest: str
    runtime_records_bound: int
    rows: tuple[DerivedLineageRow, ...]

    def __post_init__(self) -> None:
        if not _is_sha256(self.materialization_receipt_digest):
            raise ValueError("lineage needs its materialization receipt digest")
        if (isinstance(self.runtime_records_bound, bool)
                or not isinstance(self.runtime_records_bound, int)
                or self.runtime_records_bound < 0):
            raise TypeError("runtime_records_bound must be non-negative")
        if (not isinstance(self.rows, tuple)
                or any(not isinstance(row, DerivedLineageRow)
                       for row in self.rows)):
            raise TypeError("lineage rows must be an immutable typed tuple")
        source_ids = [row.source_element_id for row in self.rows]
        l1_ids = [row.l1_id for row in self.rows]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("lineage repeats a source ElementId")
        if len(l1_ids) != len(set(l1_ids)):
            raise ValueError("lineage repeats an L1 id")
        bound_plans = {
            row.plan_digest for row in self.rows if row.runtime_record_present
        }
        if len(bound_plans) != self.runtime_records_bound:
            raise ValueError(
                "runtime_records_bound disagrees with lineage rows")

    def as_dict(self) -> dict[str, Any]:
        return {
            "derived": True,
            "materialization_receipt_digest": (
                self.materialization_receipt_digest),
            "runtime_records_bound": self.runtime_records_bound,
            "rows": [row.as_dict() for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class _RuntimeRow:
    plan_digest: str
    document_key: str | None
    device_id: str | None
    created: Mapping[str, tuple[str, ...]]


def _runtime_index(
    rows: Iterable[Mapping[str, Any]],
    *,
    plans_by_digest: Mapping[str, Mapping[str, Any]],
) -> dict[str, _RuntimeRow]:
    """Check explicit registry rows, without picking a "similar" run."""

    indexed: dict[str, _RuntimeRow] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"runtime_rows[{index}] must be a mapping")
        if row.get("schema_version") != CREATED_LEDGER_SCHEMA:
            raise LineageError(
                f"runtime_rows[{index}] is not {CREATED_LEDGER_SCHEMA}")
        if row.get("op_kinds_known") is not True:
            raise LineageError(
                f"runtime_rows[{index}] predates exact operation-kind binding")
        digest = row.get("plan_digest")
        if not _is_sha256(digest):
            raise LineageError(
                f"runtime_rows[{index}] cannot bind without plan_digest")
        if digest not in plans_by_digest:
            raise LineageError(
                f"runtime_rows[{index}] names a plan outside materialization")
        if digest in indexed:
            raise LineageError(
                "multiple runtime rows name one plan; choosing one would "
                "guess which execution produced the target model")
        created = row.get("created")
        if not isinstance(created, Mapping):
            raise LineageError(
                f"runtime_rows[{index}].created must be an object")
        plan_ops = plans_by_digest[digest]
        frozen_created: dict[str, tuple[str, ...]] = {}
        for raw_op_id, raw_ids in created.items():
            if not isinstance(raw_op_id, str) or not raw_op_id:
                raise LineageError(
                    "runtime created map needs a non-empty string op id")
            op_id = raw_op_id
            planned_op = plan_ops.get(op_id)
            if planned_op is None:
                raise LineageError(
                    f"runtime created map names op outside plan: {op_id}")
            if planned_op.effect is not EffectKind.CREATE:
                raise LineageError(
                    f"runtime created map attributes a new element to "
                    f"non-create op {op_id}")
            if (not isinstance(raw_ids, Sequence)
                    or isinstance(raw_ids, (str, bytes, bytearray))):
                raise LineageError(
                    f"runtime created ids for {op_id} must be a sequence")
            ids: list[str] = []
            for raw_id in raw_ids:
                if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
                    raise LineageError(
                        f"runtime element id for {op_id} must be string or int")
                element_id = str(raw_id)
                try:
                    canonical = str(int(element_id))
                except ValueError as exc:
                    raise LineageError(
                        f"runtime element id for {op_id} is not numeric") from exc
                if int(element_id) <= 0 or canonical != element_id:
                    raise LineageError(
                        f"runtime element id for {op_id} is not a positive "
                        "canonical Revit ElementId")
                ids.append(element_id)
            if len(ids) != len(set(ids)):
                raise LineageError(
                    f"runtime ids for {op_id} repeat one Revit ElementId")
            cardinality = planned_op.result.identity_cardinality
            if (cardinality is IdentityCardinality.ONE and len(ids) != 1):
                raise LineageError(
                    f"runtime ids for {op_id} disagree with ONE cardinality")
            if (cardinality is IdentityCardinality.MANY and not ids):
                raise LineageError(
                    f"runtime ids for {op_id} disagree with MANY cardinality")
            frozen_created[op_id] = tuple(ids)
        created_count = row.get("created_count")
        if (isinstance(created_count, bool)
                or not isinstance(created_count, int)
                or created_count != sum(len(ids)
                                        for ids in frozen_created.values())):
            raise LineageError(
                f"runtime_rows[{index}].created_count disagrees with created")
        doc_key = row.get("doc_key")
        device_id = row.get("device_id")
        for name, value in (("doc_key", doc_key), ("device_id", device_id)):
            if not isinstance(value, str) or not value:
                raise LineageError(
                    f"runtime_rows[{index}].{name} must bind the target model")
        indexed[digest] = _RuntimeRow(
            plan_digest=digest,
            document_key=doc_key,
            device_id=device_id,
            created=frozen_created,
        )
    return indexed


def _wire_op_id(op) -> str | None:
    """One read per wire op: the pinned join touches every operation exactly once."""
    if not isinstance(op, Mapping):
        return None
    op_id = op.get("id")
    return op_id if isinstance(op_id, str) else None


def _index_unique(items: Iterable, key) -> tuple[dict[str, Any], set[str]]:
    """Index by id and RETAIN ambiguity: an id seen twice is reported, never
    resolved by order. `key` returns None for an item that carries no id."""
    by_id: dict[str, Any] = {}
    repeated: set[str] = set()
    for item in items:
        item_id = key(item)
        if item_id is None:
            continue
        if item_id in by_id:
            repeated.add(item_id)
        else:
            by_id[item_id] = item
    return by_id, repeated


def derive_lineage(
    materialized: MaterializeResult,
    *,
    runtime_rows: Iterable[Mapping[str, Any]] = (),
) -> DerivedLineage:
    """Join exact receipts into a derived read-only projection.

    The caller must pre-select the ``runtime_rows`` rows. More than one row
    per plan is a refusal: one plan can be executed in several documents, and
    silently taking the newest one would mean attributing a real Revit
    ElementId to the wrong building.
    """

    if not isinstance(materialized, MaterializeResult):
        raise TypeError("materialized must be MaterializeResult")

    plans_by_digest: dict[str, dict[str, Any]] = {}
    repeated_plan_ops: dict[str, set[str]] = {}
    for plan in materialized.plans:
        if plan is None:
            continue
        if plan.plan_digest in plans_by_digest:
            raise LineageError(
                "materialization contains duplicate plan digests")
        plans_by_digest[plan.plan_digest], repeated_plan_ops[plan.plan_digest] = _index_unique(
            plan.ops, lambda op: op.op_id)
    runtime_by_digest = _runtime_index(
        runtime_rows, plans_by_digest=plans_by_digest)

    programs = materialized.programs
    wire_ops_by_program: dict[int, tuple[dict[str, Mapping[str, Any]], set[str]]] = {}

    def wire_ops(program_index: int) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
        """Index the referenced program once; retain ambiguity instead of picking a winner."""
        indexed = wire_ops_by_program.get(program_index)
        if indexed is None:
            indexed = wire_ops_by_program[program_index] = _index_unique(
                programs[program_index]["ops"], _wire_op_id)
        return indexed

    derived: list[DerivedLineageRow] = []
    for record in materialized.accounting.records:
        op_name: str | None = None
        plan_digest: str | None = None
        runtime: _RuntimeRow | None = None
        if record.op_id is not None:
            assert record.program_index is not None
            by_id, repeated = wire_ops(record.program_index)
            match = by_id.get(record.op_id)
            if match is None or record.op_id in repeated:
                raise LineageError(
                    f"materialization op {record.op_id} is not unique in wire")
            raw_name = match.get("op")
            if not isinstance(raw_name, str) or not raw_name:
                raise LineageError(
                    f"materialization op {record.op_id} has no operation name")
            op_name = raw_name
            plan = materialized.plans[record.program_index]
            if plan is not None:
                planned = plans_by_digest[plan.plan_digest].get(record.op_id)
                if (planned is None
                        or record.op_id in repeated_plan_ops[plan.plan_digest]
                        or planned.op_name != op_name):
                    raise LineageError(
                        f"plan does not preserve materialization op "
                        f"{record.op_id}")
                plan_digest = plan.plan_digest
                runtime = runtime_by_digest.get(plan_digest)

        runtime_ids = (
            runtime.created.get(record.op_id)
            if runtime is not None and record.op_id is not None else None)
        derived.append(DerivedLineageRow(
            source_element_id=record.source_id,
            l1_id=record.leaf_id,
            leaf_kind=record.leaf_kind,
            materialization_disposition=record.disposition,
            residual_reason=record.reason,
            kir_op_id=record.op_id,
            kir_op_name=op_name,
            program_index=record.program_index,
            plan_digest=plan_digest,
            runtime_record_present=runtime is not None,
            runtime_document_key=(
                runtime.document_key if runtime is not None else None),
            runtime_device_id=(
                runtime.device_id if runtime is not None else None),
            runtime_element_ids=runtime_ids,
        ))

    return DerivedLineage(
        materialization_receipt_digest=(
            materialized.accounting.receipt_digest),
        runtime_records_bound=len(runtime_by_digest),
        rows=tuple(derived),
    )
