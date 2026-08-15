"""DECOMPILE A3: materialize L1 leaves into compiler-ready KIR programs.

The decompile pipeline lifts a Revit model into flat L1 op/atom leaves
(``lift.py``) and folds them into an L3 tree (``fold.py``).  This module closes
the loop for REBUILD: it turns those op-leaves back into RAW compiler-input
programs (``{"ir_version": "1.0", "ops": [...]}``) and immediately proves each
one through the public typed mid-end (``compiler.plan_program`` ->
DAG/host-attach -> ``ground`` -> ``authoring.emit_program``).  The materializer
still introduces **no new trust surface** — it never emits ``__grounded__``
dicts or C#; it only translates the frozen L1 reference DIALECT into the
compiler's selector dialect, chunks the ops, and retains the exact immutable
plan that the rebuild compiler must later lower.

Reference-dialect translation (``mode="same_document"``):

* named / family reference ``{"by": ..., "_id": ID, ...}`` (a level, a catalog
  type, a family symbol) -> ``{"by": "element_id", "value": int(ID)}``.  The
  same document is being rebuilt, so the source ElementId pins the existing
  datum/type directly — no name resolution, no snapshot needed.
* an L1 ``{"ref": <target _id>}`` becomes an intra-program ``by=ref`` when
  the target is materialized.  With ``include_datums=False``, a ref to a
  deliberately pinned level/grid instead becomes ``by=element_id`` for that
  existing source datum.  It is therefore resolved explicitly rather than
  being mistaken for an orphan dependency and silently dropping its consumer.

Datums (Д3): with ``include_datums=False`` (default) ``create_level`` /
``create_grid`` op-leaves are NOT materialized — the levels/grids they name are
already in the model and every other op pins them by their existing ElementId.
They are counted in ``stats.datums_skipped``.  ``include_datums=True`` DOES
materialize them (for a future ``fresh_document`` rebuild); A3 only needs the
flag and its test.

Chunking laws (Д5):

* (a) ref-atomicity — a ``ref`` may never cross a chunk boundary, so the
  indivisible unit is a CONNECTED COMPONENT of the whole ref graph: a wall, its
  hosted doors/windows AND everything else pointing at them (``create_tag``
  targets a door, ``create_dimension`` targets several elements at once) live
  in ONE chunk. Grouping by the ``host`` param alone left 39 of 133 chunks
  refused on a real 59-storey tower (measured 02.08.2026).
* (b) rooms in the tail — ``create_room`` needs its bounding walls ALREADY in
  the model, so every room op is deferred to trailing chunks after all walls of
  the whole run.
* (c) chunk size ~ ``chunk_target``, expanded only to keep a host-group whole.
* (d) inside a chunk ops are toposorted by ``ref`` dependency, with a stable
  ``source_element_id`` tie-break (I4 determinism).

``create_stairs`` is a solo program (KIR-L002: StairsEditScope owns its own
transactions) — each stairs op-leaf becomes its own single-op program.

Atom leaves remain conservative semantic fallbacks.  In the default
``same_document`` mode they become ``SkipRecord`` values.  The explicit
``mode="escrow"`` consumes a validated Tier-G ``GeometryExtraction`` and may
materialize an atom as ``create_directshape``: geometry only, never the source
BIM category when that would impersonate a wall/floor/etc.  Every such result
is labelled ``pending_runtime_witness``; this layer never claims FORM_EXACT.

Inert / additive / offline: nothing imports this in a hot path; frozen L0 and
the compiler front are untouched; universal (no LOT31 hardcoding, I1); every
sort is explicit (I4).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Sequence

from kukai.ir import spec
from kukai.ir.compiler import MAX_BULK_OPS, plan_program
from kukai.ir.diag import KirRefusal
from kukai.ir.midend import PlannedProgram
from kukai.ir.decompile.component import _translate_leaf
from kukai.ir.decompile.geom_extract import (
    ExtractedGeometryTier,
    GeometryExtraction,
    GeometryExtractionError,
    GeometryFailureReason,
    GeometryIndexRecord,
    geometry_hash,
)
from kukai.ir.decompile.geometry_acceptance import (
    FormExpectation,
    mesh_bbox_mm,
    mesh_surface_digest,
)
from kukai.ir.decompile.l1_schema import AtomReason, L1Node
from kukai.ir.decompile.recompile import GeometrySchemaError, GmMesh
from kukai.ir.mesh import validate_mesh
from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES

Vec3 = tuple[float, float, float]

# Datum ops are pinned to existing elements in same_document rebuild (Д3).
_DATUM_OPS = frozenset({"create_level", "create_grid"})
# Ops that must be the sole op of their program (KIR-L002). Read from the
# registry, not restated: the same fact used to live here, in the emitter and in
# the prose, and a fact spelled three times drifts in two of them.
_SOLO_OPS = spec.SOLO_OPS
# create_room needs its enclosure already in the model -> trailing chunks (Д5b).
_TAIL_OPS = frozenset({"create_room"})

MATERIALIZATION_ACCOUNTING_SCHEMA = "materialization-accounting/2"

_DISPOSITION_EMITTED = "emitted_semantic_op"
_DISPOSITION_ESCROW = "atom_escrow"
_DISPOSITION_DATUM_PIN = "datum_policy_pin"
_DISPOSITION_RESIDUAL = "typed_residual"
_ACCOUNTING_DISPOSITIONS = frozenset({
    _DISPOSITION_EMITTED,
    _DISPOSITION_ESCROW,
    _DISPOSITION_DATUM_PIN,
    _DISPOSITION_RESIDUAL,
})
_ATOM_REASON_CODES = frozenset(reason.value for reason in AtomReason)
_ATOM_SKIP_REASONS = frozenset({
    *("atom:" + reason for reason in _ATOM_REASON_CODES),
    "atom_escrow:not_selected",
    "atom_escrow:missing_geometry_evidence",
    "atom_escrow:tier_a_no_geometry",
    "atom_escrow:category_identity_mismatch",
    "atom_escrow:geometry_refused",
    "atom_escrow:mesh_refused",
    *("atom_escrow:geometry_failure:" + reason.value
      for reason in GeometryFailureReason),
    "atom_escrow:geometry_failure:unavailable",
})


def _canonical_json(value: Any, *, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MaterializeError(f"{label} is not canonical JSON: {exc}") from exc


def _sha256_json(value: Any, *, label: str) -> str:
    return hashlib.sha256(
        _canonical_json(value, label=label).encode("utf-8")
    ).hexdigest()


def _canonical_input_leaves(leaves: Sequence[Mapping[str, Any]]) -> list[Any]:
    """Canonical set-order for the exact input leaves committed by a receipt."""

    return sorted(
        leaves,
        key=lambda leaf: (leaf["source_element_id"], leaf["_id"]),
    )


def _validate_input_leaves(leaves: Sequence[Any]) -> None:
    """Validate the identity/kind seam needed for total accounting.

    Full L1 validation deliberately remains the LIFT boundary's job.  This
    boundary validates every field it uses for accounting before indexing it,
    so malformed kinds, unknown atom reasons and duplicate identities cannot
    turn into an overwritten dict entry or an untyped residual.
    """

    source_ids: list[str] = []
    leaf_ids: list[str] = []
    for index, leaf in enumerate(leaves):
        if not isinstance(leaf, Mapping):
            raise MaterializeError(f"leaves[{index}] must be an L1 mapping")
        source_id = leaf.get("source_element_id")
        leaf_id = leaf.get("_id")
        kind = leaf.get("kind")
        if not isinstance(source_id, str) or not source_id:
            raise MaterializeError(
                f"leaves[{index}].source_element_id must be non-empty")
        if not isinstance(leaf_id, str) or not leaf_id:
            raise MaterializeError(f"leaves[{index}]._id must be non-empty")
        if kind not in {"op", "atom"}:
            raise MaterializeError(
                f"leaves[{index}].kind must be 'op' or 'atom'")
        if kind == "op":
            if (not isinstance(leaf.get("op_name"), str)
                    or not leaf["op_name"]):
                raise MaterializeError(
                    f"leaves[{index}].op_name must be non-empty")
            if not isinstance(leaf.get("params"), dict):
                raise MaterializeError(
                    f"leaves[{index}].params must be an object")
        else:
            if (not isinstance(leaf.get("category"), str)
                    or not leaf["category"]):
                raise MaterializeError(
                    f"leaves[{index}].category must be non-empty")
            reason = leaf.get("reason")
            reason_code = (
                reason.get("code") if isinstance(reason, Mapping) else None)
            if reason_code not in _ATOM_REASON_CODES:
                raise MaterializeError(
                    "atom residual reason is outside the closed AtomReason "
                    f"set: {reason_code!r}")
        source_ids.append(source_id)
        leaf_ids.append(leaf_id)
    if len(source_ids) != len(set(source_ids)):
        raise MaterializeError("duplicate source_element_id in materialization input")
    if len(leaf_ids) != len(set(leaf_ids)):
        raise MaterializeError("duplicate L1 _id in materialization input")


class MaterializeError(ValueError):
    """The materializer cannot safely translate the supplied L1 input."""


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


@dataclass(frozen=True, slots=True)
class MaterializationRecord:
    """Exactly one authoritative disposition for one unique input leaf."""

    source_id: str
    leaf_id: str
    leaf_kind: str
    category: str
    disposition: str
    reason: str | None = None
    op_id: str | None = None
    program_index: int | None = None
    element_id: int | None = None
    evidence_state: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("leaf_id", self.leaf_id),
            ("category", self.category),
        ):
            if not isinstance(value, str) or not value:
                raise TypeError(f"accounting {field_name} must be non-empty")
        if self.leaf_kind not in {"op", "atom"}:
            raise ValueError("accounting leaf_kind must be 'op' or 'atom'")
        if self.disposition not in _ACCOUNTING_DISPOSITIONS:
            raise ValueError("unknown materialization disposition")
        if self.reason is not None and (
                not isinstance(self.reason, str) or not self.reason):
            raise TypeError("accounting reason must be non-empty or null")
        if self.op_id is not None and (
                not isinstance(self.op_id, str) or not self.op_id):
            raise TypeError("accounting op_id must be non-empty or null")
        if self.program_index is not None and (
                isinstance(self.program_index, bool)
                or not isinstance(self.program_index, int)
                or self.program_index < 0):
            raise TypeError("accounting program_index must be non-negative")
        if self.element_id is not None and (
                isinstance(self.element_id, bool)
                or not isinstance(self.element_id, int)):
            raise TypeError("accounting element_id must be an int or null")

        if self.disposition == _DISPOSITION_EMITTED:
            if (self.leaf_kind != "op" or self.op_id is None
                    or self.program_index is None or self.reason is not None
                    or self.element_id is not None
                    or self.evidence_state is not None):
                raise ValueError("invalid emitted semantic accounting row")
        elif self.disposition == _DISPOSITION_ESCROW:
            if (self.leaf_kind != "atom" or self.op_id is None
                    or self.program_index is None or self.reason is not None
                    or self.element_id is not None
                    or self.evidence_state != "pending_runtime_witness"):
                raise ValueError("invalid atom escrow accounting row")
        elif self.disposition == _DISPOSITION_DATUM_PIN:
            if (self.leaf_kind != "op" or self.op_id is not None
                    or self.program_index is not None
                    or self.reason != "datum_pinned_existing"
                    or self.element_id is None
                    or self.evidence_state != "same_document_unproven"):
                raise ValueError("invalid datum-policy accounting row")
        else:
            if (self.op_id is not None or self.program_index is not None
                    or self.element_id is not None
                    or self.evidence_state is not None
                    or self.reason is None):
                raise ValueError("invalid typed-residual accounting row")
            if self.leaf_kind == "atom" \
                    and self.reason not in _ATOM_SKIP_REASONS:
                raise ValueError("unknown atom residual accounting reason")
            if self.leaf_kind == "op" and not self.reason.startswith(
                    "host_unmaterialized:"):
                raise ValueError("unknown semantic residual accounting reason")
            if self.leaf_kind == "op" and not self.reason.split(":", 1)[1]:
                raise ValueError("semantic residual must name its missing ref")

    def as_dict(self) -> dict[str, Any]:
        # Deliberately exact: null fields stay present, so a producer cannot
        # reinterpret an omitted binding as one that was proved elsewhere.
        return {
            "source_id": self.source_id,
            "leaf_id": self.leaf_id,
            "leaf_kind": self.leaf_kind,
            "category": self.category,
            "disposition": self.disposition,
            "reason": self.reason,
            "op_id": self.op_id,
            "program_index": self.program_index,
            "element_id": self.element_id,
            "evidence_state": self.evidence_state,
        }


@dataclass(frozen=True, slots=True)
class MaterializationAccounting:
    """Versioned, digest-bound total-accounting receipt for a result."""

    input_digest: str
    programs_digest: str
    records: tuple[MaterializationRecord, ...]
    programs_count: int
    emitted_ops_count: int
    schema_version: str = field(
        default=MATERIALIZATION_ACCOUNTING_SCHEMA, init=False)

    def __post_init__(self) -> None:
        if not _is_sha256(self.input_digest):
            raise ValueError("accounting input_digest must be SHA-256")
        if not _is_sha256(self.programs_digest):
            raise ValueError("accounting programs_digest must be SHA-256")
        if (isinstance(self.programs_count, bool)
                or not isinstance(self.programs_count, int)
                or self.programs_count < 0):
            raise TypeError("accounting programs_count must be non-negative")
        if (isinstance(self.emitted_ops_count, bool)
                or not isinstance(self.emitted_ops_count, int)
                or self.emitted_ops_count < 0):
            raise TypeError("accounting emitted_ops_count must be non-negative")
        if (not isinstance(self.records, tuple)
                or any(not isinstance(record, MaterializationRecord)
                       for record in self.records)):
            raise TypeError("accounting records must be an immutable typed tuple")
        source_ids = [record.source_id for record in self.records]
        leaf_ids = [record.leaf_id for record in self.records]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("accounting repeats a source identity")
        if len(leaf_ids) != len(set(leaf_ids)):
            raise ValueError("accounting repeats an L1 identity")
        expected_order = sorted(
            self.records, key=lambda record: (record.source_id, record.leaf_id))
        if list(self.records) != expected_order:
            raise ValueError("accounting records must use canonical source order")
        emitted = sum(
            record.disposition in {_DISPOSITION_EMITTED, _DISPOSITION_ESCROW}
            for record in self.records)
        if self.emitted_ops_count != emitted:
            raise ValueError("accounting emitted count disagrees with records")

    @property
    def counts(self) -> dict[str, int]:
        return {
            "input_leaves": len(self.records),
            "emitted_semantic_ops": sum(
                row.disposition == _DISPOSITION_EMITTED
                for row in self.records),
            "atom_escrows": sum(
                row.disposition == _DISPOSITION_ESCROW
                for row in self.records),
            "datum_policy_pins": sum(
                row.disposition == _DISPOSITION_DATUM_PIN
                for row in self.records),
            "typed_residuals": sum(
                row.disposition == _DISPOSITION_RESIDUAL
                for row in self.records),
            "programs": self.programs_count,
            "emitted_ops": self.emitted_ops_count,
        }

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "input_digest": self.input_digest,
            "programs_digest": self.programs_digest,
            "counts": self.counts,
            "records": [record.as_dict() for record in self.records],
        }

    @property
    def receipt_digest(self) -> str:
        return _sha256_json(
            self._unsigned_dict(), label="materialization accounting")

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._unsigned_dict(),
            "receipt_digest": self.receipt_digest,
        }


@dataclass(frozen=True, slots=True)
class SkipRecord:
    """One L1 leaf that was not materialized, with a machine-readable reason."""

    source_id: str
    category: str
    reason: str


@dataclass(frozen=True, slots=True)
class EscrowRecord:
    """Pre-registered form expectation for one geometry-only atom."""

    source_category: str
    expectation: FormExpectation
    acceptance_state: str = "pending_runtime_witness"

    def __post_init__(self) -> None:
        if not isinstance(self.source_category, str) or not self.source_category:
            raise TypeError("EscrowRecord.source_category must be non-empty")
        if not isinstance(self.expectation, FormExpectation):
            raise TypeError("EscrowRecord.expectation must be typed")
        if self.acceptance_state != "pending_runtime_witness":
            raise ValueError(
                "atom escrow cannot claim acceptance before runtime witness")

    @property
    def source_id(self) -> str:
        return self.expectation.source_id

    @property
    def directshape_category(self) -> str:
        return self.expectation.directshape_category

    @property
    def geometry_hash(self) -> str:
        return self.expectation.source_geometry_hash

    @property
    def materialized_geometry_hash(self) -> str:
        return self.expectation.materialized_geometry_hash

    @property
    def geometry_tier(self) -> str:
        return self.expectation.geometry_tier

    @property
    def op_id(self) -> str:
        return self.expectation.op_id

    @property
    def program_index(self) -> int:
        return self.expectation.program_index

    @property
    def plan_digest(self) -> str:
        return self.expectation.plan_digest

    @property
    def form_digest(self) -> str:
        return self.expectation.surface_digest

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.expectation.to_dict(),
            "source_category": self.source_category,
            # Compatibility name retained beside the explicit source name.
            "geometry_hash": self.geometry_hash,
            "form_digest": self.form_digest,
            "expectation_digest": self.expectation.expectation_digest,
            "acceptance_state": self.acceptance_state,
        }


@dataclass(frozen=True, slots=True)
class _EscrowCandidate:
    """Mesh candidate awaiting an accepted typed-plan identity."""

    source_id: str
    source_category: str
    directshape_category: str
    source_geometry_hash: str
    geometry_tier: str
    op_id: str
    mesh: GmMesh

    def bind(self, *, program_index: int, plan_digest: str) -> EscrowRecord:
        return EscrowRecord(
            source_category=self.source_category,
            expectation=FormExpectation.from_mesh(
                source_id=self.source_id,
                op_id=self.op_id,
                program_index=program_index,
                plan_digest=plan_digest,
                source_geometry_hash=self.source_geometry_hash,
                directshape_category=self.directshape_category,
                geometry_tier=self.geometry_tier,
                mesh=self.mesh,
            ),
        )


def _build_materialization_accounting(
    leaves: Sequence[L1Node],
    programs: Sequence[dict[str, Any]],
    skipped: Sequence[SkipRecord],
    escrowed: Sequence[EscrowRecord],
    *,
    include_datums: bool,
) -> MaterializationAccounting:
    """Prove that leaves, wire programs and evidence form one total partition."""

    op_locations: dict[str, tuple[int, Mapping[str, Any]]] = {}
    emitted_total = 0
    for program_index, program in enumerate(programs):
        ops = program.get("ops")
        if not isinstance(ops, list):
            raise MaterializeError(
                f"programs[{program_index}].ops must be a list")
        for op in ops:
            if not isinstance(op, Mapping):
                raise MaterializeError("materialized op must be an object")
            op_id = op.get("id")
            if not isinstance(op_id, str) or not op_id:
                raise MaterializeError("materialized op must have an id")
            if op_id in op_locations:
                raise MaterializeError(
                    f"duplicate emitted op id in accounting: {op_id}")
            op_locations[op_id] = (program_index, op)
            emitted_total += 1

    skip_by_source: dict[str, SkipRecord] = {}
    for record in skipped:
        if not isinstance(record, SkipRecord):
            raise MaterializeError("untyped skip cannot enter accounting")
        if record.source_id in skip_by_source:
            raise MaterializeError(
                "one source leaf cannot have duplicate skip accounting")
        skip_by_source[record.source_id] = record
    escrow_by_source: dict[str, EscrowRecord] = {}
    for record in escrowed:
        if not isinstance(record, EscrowRecord):
            raise MaterializeError("untyped escrow cannot enter accounting")
        if record.source_id in escrow_by_source:
            raise MaterializeError("one atom cannot have duplicate escrow evidence")
        escrow_by_source[record.source_id] = record

    records: list[MaterializationRecord] = []
    consumed_op_ids: set[str] = set()
    consumed_skips: set[str] = set()
    consumed_escrows: set[str] = set()
    for leaf in leaves:
        source_id = leaf["source_element_id"]
        leaf_id = leaf["_id"]
        leaf_kind = leaf["kind"]
        category = (
            leaf["op_name"] if leaf_kind == "op" else leaf["category"])
        op_id = _op_id(source_id)
        location = op_locations.get(op_id)
        skip = skip_by_source.get(source_id)
        escrow = escrow_by_source.get(source_id)

        if leaf_kind == "op" and leaf["op_name"] in _DATUM_OPS \
                and not include_datums:
            if location is not None or escrow is not None or skip is None \
                    or skip.category != category \
                    or skip.reason != "datum_pinned_existing":
                raise MaterializeError(
                    f"datum source {source_id} is not accounted exactly once")
            try:
                element_id = int(source_id)
            except (TypeError, ValueError) as exc:
                raise MaterializeError(
                    "datum pin is not a source ElementId") from exc
            consumed_skips.add(source_id)
            records.append(MaterializationRecord(
                source_id=source_id,
                leaf_id=leaf_id,
                leaf_kind="op",
                category=category,
                disposition=_DISPOSITION_DATUM_PIN,
                reason="datum_pinned_existing",
                element_id=element_id,
                evidence_state="same_document_unproven",
            ))
            continue

        if leaf_kind == "op" and skip is not None:
            if (location is not None or escrow is not None
                    or skip.category != category
                    or not skip.reason.startswith("host_unmaterialized:")
                    or not skip.reason.split(":", 1)[1]):
                raise MaterializeError(
                    f"semantic source {source_id} has invalid residual accounting")
            consumed_skips.add(source_id)
            records.append(MaterializationRecord(
                source_id=source_id,
                leaf_id=leaf_id,
                leaf_kind="op",
                category=category,
                disposition=_DISPOSITION_RESIDUAL,
                reason=skip.reason,
            ))
            continue

        if leaf_kind == "op":
            if location is None or skip is not None or escrow is not None:
                raise MaterializeError(
                    f"semantic source {source_id} is missing or multiply accounted")
            program_index, op = location
            if op.get("op") != category:
                raise MaterializeError(
                    f"semantic source {source_id} emitted the wrong op")
            consumed_op_ids.add(op_id)
            records.append(MaterializationRecord(
                source_id=source_id,
                leaf_id=leaf_id,
                leaf_kind="op",
                category=category,
                disposition=_DISPOSITION_EMITTED,
                op_id=op_id,
                program_index=program_index,
            ))
            continue

        if escrow is not None:
            if location is None or skip is not None:
                raise MaterializeError(
                    f"atom source {source_id} has incomplete escrow accounting")
            program_index, op = location
            if (op.get("op") != "create_directshape"
                    or escrow.op_id != op_id
                    or escrow.program_index != program_index
                    or escrow.source_category != category
                    or escrow.acceptance_state != "pending_runtime_witness"):
                raise MaterializeError(
                    f"atom source {source_id} escrow evidence disagrees with wire")
            consumed_op_ids.add(op_id)
            consumed_escrows.add(source_id)
            records.append(MaterializationRecord(
                source_id=source_id,
                leaf_id=leaf_id,
                leaf_kind="atom",
                category=category,
                disposition=_DISPOSITION_ESCROW,
                op_id=op_id,
                program_index=program_index,
                evidence_state="pending_runtime_witness",
            ))
            continue

        if (location is not None or skip is None
                or skip.category != category
                or skip.reason not in _ATOM_SKIP_REASONS):
            raise MaterializeError(
                f"atom source {source_id} has unknown or incomplete residual accounting")
        consumed_skips.add(source_id)
        records.append(MaterializationRecord(
            source_id=source_id,
            leaf_id=leaf_id,
            leaf_kind="atom",
            category=category,
            disposition=_DISPOSITION_RESIDUAL,
            reason=skip.reason,
        ))

    if consumed_op_ids != set(op_locations):
        raise MaterializeError("emitted wire contains an op with no source leaf")
    if consumed_skips != set(skip_by_source):
        raise MaterializeError("skip evidence contains an unbound source")
    if consumed_escrows != set(escrow_by_source):
        raise MaterializeError("escrow evidence contains an unbound source")

    records.sort(key=lambda record: (record.source_id, record.leaf_id))
    return MaterializationAccounting(
        input_digest=_sha256_json(
            _canonical_input_leaves(leaves),
            label="materialization input leaves",
        ),
        programs_digest=_sha256_json(
            programs, label="materialized raw programs"),
        records=tuple(records),
        programs_count=len(programs),
        emitted_ops_count=emitted_total,
    )


@dataclass(frozen=True, slots=True)
class MaterializeStats:
    """Counters for a materialization run (all deterministic)."""

    op_leaves: int = 0
    materialized_ops: int = 0
    programs: int = 0
    atoms_skipped: int = 0
    atoms_escrowed: int = 0
    datums_skipped: int = 0
    semantic_ops_skipped: int = 0
    solo_programs: int = 0
    tail_ops: int = 0
    #: Группы, вынесенные в отдельную программу по требованию вызывающего
    #: (радиус поражения). В отличие от solo_programs это не «оп, который
    #: обязан быть один», а хост-группа целиком: хозяин со своими
    #: пристроенными опами, иначе Д5a (host-atomicity) была бы нарушена
    #: изоляцией.
    isolated_groups: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "op_leaves": self.op_leaves,
            "materialized_ops": self.materialized_ops,
            "programs": self.programs,
            "atoms_skipped": self.atoms_skipped,
            "atoms_escrowed": self.atoms_escrowed,
            "datums_skipped": self.datums_skipped,
            "semantic_ops_skipped": self.semantic_ops_skipped,
            "solo_programs": self.solo_programs,
            "tail_ops": self.tail_ops,
            "isolated_groups": self.isolated_groups,
        }


@dataclass(frozen=True, slots=True)
class ProgramPlanCheck:
    """Typed planning evidence for one materialized rebuild chunk."""

    program_index: int
    accepted: bool
    source_digest: str
    plan_digest: str | None = None
    diagnostic_codes: tuple[str, ...] = ()
    error_type: str | None = None

    def __post_init__(self) -> None:
        if (isinstance(self.program_index, bool)
                or not isinstance(self.program_index, int)
                or self.program_index < 0):
            raise ValueError("program_index must be a non-negative int")
        if not isinstance(self.accepted, bool):
            raise TypeError("accepted must be bool")
        if not isinstance(self.diagnostic_codes, tuple) or any(
                not isinstance(code, str) or not code
                for code in self.diagnostic_codes):
            raise TypeError("diagnostic_codes must be immutable strings")
        source_is_sha256 = (
            isinstance(self.source_digest, str)
            and len(self.source_digest) == 64
            and all(char in "0123456789abcdef"
                    for char in self.source_digest)
        )
        if not source_is_sha256:
            raise ValueError("plan check needs a source SHA-256 digest")
        digest_is_sha256 = (
            isinstance(self.plan_digest, str)
            and len(self.plan_digest) == 64
            and all(char in "0123456789abcdef" for char in self.plan_digest)
        )
        if self.accepted:
            if not digest_is_sha256:
                raise ValueError("accepted plan check needs a SHA-256 digest")
            if self.diagnostic_codes or self.error_type is not None:
                raise ValueError("accepted plan check cannot carry an error")
        else:
            if self.plan_digest is not None:
                raise ValueError("refused plan check cannot carry a digest")
            if not self.diagnostic_codes:
                raise ValueError("refused plan check needs a diagnostic code")
        if self.error_type is not None and (
                not isinstance(self.error_type, str) or not self.error_type):
            raise TypeError("error_type must be a non-empty string")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "program_index": self.program_index,
            "accepted": self.accepted,
            "source_digest": self.source_digest,
            "diagnostic_codes": list(self.diagnostic_codes),
        }
        if self.plan_digest is not None:
            payload["plan_digest"] = self.plan_digest
        if self.error_type is not None:
            payload["error_type"] = self.error_type
        return payload


@dataclass(frozen=True, slots=True, init=False)
class MaterializeResult:
    """Raw programs, their immutable plans, skips and run statistics.

    ``programs`` remains the stable external shape.  ``plans`` is positionally
    aligned with it; a ``None`` means planning refused and the matching
    ``plan_checks`` row names the typed diagnostic.  This preserves the
    reverse pipeline's fail-soft reporting while making compiler readiness a
    machine-checkable fact instead of a comment.
    """

    _programs_json: tuple[str, ...] = field(
        default_factory=tuple, repr=False)
    _skipped: tuple[SkipRecord, ...] = field(
        default_factory=tuple, repr=False)
    _escrowed: tuple[EscrowRecord, ...] = field(
        default_factory=tuple, repr=False)
    stats: MaterializeStats = field(default_factory=MaterializeStats)
    accounting: MaterializationAccounting | None = field(
        default=None, repr=False)
    plans: tuple[PlannedProgram | None, ...] = field(
        default_factory=tuple, repr=False, compare=False)
    plan_checks: tuple[ProgramPlanCheck, ...] = field(default_factory=tuple)

    def __init__(
        self,
        programs: Sequence[Mapping[str, Any]] = (),
        skipped: Sequence[SkipRecord] = (),
        escrowed: Sequence[EscrowRecord] = (),
        stats: MaterializeStats | None = None,
        accounting: MaterializationAccounting | None = None,
        plans: Sequence[PlannedProgram | None] = (),
        plan_checks: Sequence[ProgramPlanCheck] = (),
    ) -> None:
        if (isinstance(programs, (str, bytes, bytearray))
                or not isinstance(programs, Sequence)):
            raise TypeError("programs must be a sequence of mappings")
        encoded_programs: list[str] = []
        for index, program in enumerate(programs):
            if not isinstance(program, Mapping):
                raise TypeError(f"programs[{index}] must be a mapping")
            try:
                encoded = json.dumps(
                    program,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"programs[{index}] is not canonical JSON: {exc}") from exc
            if not isinstance(json.loads(encoded), dict):
                raise TypeError(f"programs[{index}] must encode an object")
            encoded_programs.append(encoded)

        object.__setattr__(self, "_programs_json", tuple(encoded_programs))
        object.__setattr__(self, "_skipped", tuple(skipped))
        object.__setattr__(self, "_escrowed", tuple(escrowed))
        object.__setattr__(
            self, "stats", stats if stats is not None else MaterializeStats())
        object.__setattr__(self, "accounting", accounting)
        object.__setattr__(self, "plans", tuple(plans))
        object.__setattr__(self, "plan_checks", tuple(plan_checks))
        self.__post_init__()

    @property
    def programs(self) -> list[dict[str, Any]]:
        """Detached legacy view; mutating it cannot rewrite accepted plans."""

        return [json.loads(encoded) for encoded in self._programs_json]

    @property
    def skipped(self) -> list[SkipRecord]:
        """Detached list view over immutable skip records."""

        return list(self._skipped)

    @property
    def escrowed(self) -> list[EscrowRecord]:
        """Detached list view over immutable escrow records."""

        return list(self._escrowed)

    def __post_init__(self) -> None:
        if any(not isinstance(record, SkipRecord) for record in self._skipped):
            raise TypeError("skipped must contain SkipRecord values")
        if any(not isinstance(record, EscrowRecord)
               for record in self._escrowed):
            raise TypeError("escrowed must contain EscrowRecord values")
        if not isinstance(self.stats, MaterializeStats):
            raise TypeError("stats must be MaterializeStats")
        if not isinstance(self.accounting, MaterializationAccounting):
            raise ValueError("typed materialization accounting is required")
        programs = self.programs
        if self.accounting.programs_digest != _sha256_json(
                programs, label="materialized raw programs"):
            raise ValueError("accounting digest disagrees with raw programs")
        if self.accounting.programs_count != len(programs):
            raise ValueError("accounting program count disagrees with wire")
        wire_ops: dict[str, tuple[int, Mapping[str, Any]]] = {}
        for program_index, program in enumerate(programs):
            ops = program.get("ops")
            if not isinstance(ops, list):
                raise ValueError("materialized program ops must be a list")
            for op in ops:
                if not isinstance(op, Mapping):
                    raise ValueError("materialized wire op must be an object")
                op_id = op.get("id")
                if not isinstance(op_id, str) or not op_id:
                    raise ValueError("materialized wire op needs an id")
                if op_id in wire_ops:
                    raise ValueError("materialized wire repeats an op id")
                wire_ops[op_id] = (program_index, op)
        if self.accounting.emitted_ops_count != len(wire_ops):
            raise ValueError("accounting emitted count disagrees with wire")
        accounted_op_ids: set[str] = set()
        for record in self.accounting.records:
            if record.disposition not in {
                    _DISPOSITION_EMITTED, _DISPOSITION_ESCROW}:
                continue
            assert record.op_id is not None
            location = wire_ops.get(record.op_id)
            if (location is None
                    or location[0] != record.program_index
                    or record.op_id in accounted_op_ids):
                raise ValueError("accounting op binding disagrees with wire")
            expected_op = (
                record.category
                if record.disposition == _DISPOSITION_EMITTED
                else "create_directshape")
            if location[1].get("op") != expected_op:
                raise ValueError("accounting op category disagrees with wire")
            accounted_op_ids.add(record.op_id)
        if accounted_op_ids != set(wire_ops):
            raise ValueError("wire op has no accounting record")

        expected_skips = sorted(
            (record.source_id, record.category, record.reason)
            for record in self.accounting.records
            if record.disposition in {
                _DISPOSITION_DATUM_PIN, _DISPOSITION_RESIDUAL})
        actual_skips = sorted(
            (record.source_id, record.category, record.reason)
            for record in self._skipped)
        if expected_skips != actual_skips:
            raise ValueError("accounting skips disagree with skip evidence")
        expected_escrows = sorted(
            record.source_id for record in self.accounting.records
            if record.disposition == _DISPOSITION_ESCROW)
        actual_escrows = sorted(record.source_id for record in self._escrowed)
        if expected_escrows != actual_escrows:
            raise ValueError("accounting escrow rows disagree with evidence")

        expected_stats = {
            "op_leaves": sum(
                record.leaf_kind == "op"
                for record in self.accounting.records),
            "materialized_ops": len(wire_ops),
            "programs": len(programs),
            "atoms_skipped": sum(
                record.leaf_kind == "atom"
                and record.disposition == _DISPOSITION_RESIDUAL
                for record in self.accounting.records),
            "atoms_escrowed": len(expected_escrows),
            "datums_skipped": sum(
                record.disposition == _DISPOSITION_DATUM_PIN
                for record in self.accounting.records),
            "semantic_ops_skipped": sum(
                record.leaf_kind == "op"
                and record.disposition == _DISPOSITION_RESIDUAL
                for record in self.accounting.records),
        }
        actual_stats = self.stats.as_dict()
        for key, expected in expected_stats.items():
            if actual_stats[key] != expected:
                raise ValueError(
                    f"materialization stats.{key} disagrees with accounting")
        if self.stats.atoms_escrowed != len(self._escrowed):
            raise ValueError("atoms_escrowed must match escrow evidence")
        escrow_sources = [record.source_id for record in self._escrowed]
        if len(escrow_sources) != len(set(escrow_sources)):
            raise ValueError("one source atom cannot be escrowed twice")
        if len(self.plans) != len(self._programs_json):
            raise ValueError("plans must align with materialized programs")
        if len(self.plan_checks) != len(self._programs_json):
            raise ValueError("plan_checks must align with materialized programs")
        if any(plan is not None and not isinstance(plan, PlannedProgram)
               for plan in self.plans):
            raise TypeError("plans must contain PlannedProgram or None")
        if any(not isinstance(check, ProgramPlanCheck)
               for check in self.plan_checks):
            raise TypeError("plan_checks must be typed")
        for index, (plan, check) in enumerate(zip(
                self.plans, self.plan_checks)):
            if check.program_index != index:
                raise ValueError("plan check indices must be contiguous")
            source_digest = hashlib.sha256(
                self._programs_json[index].encode("utf-8")).hexdigest()
            if check.source_digest != source_digest:
                raise ValueError("plan check source digest disagrees with program")
            if check.accepted is not (plan is not None):
                raise ValueError("plan and plan check acceptance disagree")
            if plan is not None and check.plan_digest != plan.plan_digest:
                raise ValueError("plan check digest disagrees with plan")
        for record in self._escrowed:
            index = record.program_index
            if index >= len(programs):
                raise ValueError("escrow expectation points outside programs")
            plan = self.plans[index]
            if plan is None or plan.plan_digest != record.plan_digest:
                raise ValueError(
                    "escrow expectation is not bound to its accepted plan")
            ops = programs[index].get("ops") or ()
            if (len(ops) != 1 or not isinstance(ops[0], dict)
                    or ops[0].get("id") != record.op_id
                    or ops[0].get("op") != "create_directshape"):
                raise ValueError(
                    "escrow expectation disagrees with its isolated program")
            op = ops[0]
            try:
                mesh = GmMesh.from_dict({
                    "tier": "Gm",
                    **op["mesh"],
                }, "escrow program mesh")
            except (KeyError, GeometrySchemaError) as exc:
                raise ValueError(
                    "escrow program does not carry its validated mesh") from exc
            expectation = record.expectation
            if (op.get("category") != expectation.directshape_category
                    or geometry_hash(mesh)
                    != expectation.materialized_geometry_hash
                    or mesh_surface_digest(mesh) != expectation.surface_digest
                    or len(mesh.triangles) != expectation.triangle_count
                    or mesh_bbox_mm(mesh) != expectation.bbox_mm):
                raise ValueError(
                    "escrow expectation disagrees with its exact mesh")

    @property
    def compiler_ready(self) -> bool:
        return all(plan is not None for plan in self.plans)


def _plan_materialized_programs(
    programs: Sequence[dict],
) -> tuple[
    tuple[PlannedProgram | None, ...],
    tuple[ProgramPlanCheck, ...],
]:
    """Plan every raw chunk once without hiding a rejected sibling chunk."""
    plans: list[PlannedProgram | None] = []
    checks: list[ProgramPlanCheck] = []
    for index, program in enumerate(programs):
        source_json = json.dumps(
            program,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        source_digest = hashlib.sha256(
            source_json.encode("utf-8")).hexdigest()
        try:
            planned = plan_program(program, bulk=True)
        except KirRefusal as refusal:
            plans.append(None)
            checks.append(ProgramPlanCheck(
                program_index=index,
                accepted=False,
                source_digest=source_digest,
                diagnostic_codes=tuple(
                    diagnostic.code for diagnostic in refusal.diagnostics),
            ))
        except Exception as exc:  # noqa: BLE001 - evidence, not a batch abort
            # Match compile_program's typed internal-error envelope.  A planner
            # defect must make compiler_ready false but must not erase the raw
            # chunk or the other chunks' evidence.
            plans.append(None)
            checks.append(ProgramPlanCheck(
                program_index=index,
                accepted=False,
                source_digest=source_digest,
                diagnostic_codes=("KIR-P000",),
                error_type=type(exc).__name__,
            ))
        else:
            plans.append(planned)
            checks.append(ProgramPlanCheck(
                program_index=index,
                accepted=True,
                source_digest=source_digest,
                plan_digest=planned.plan_digest,
            ))
    return tuple(plans), tuple(checks)


# ---------------------------------------------------------------------------
# Deterministic op-id derivation
# ---------------------------------------------------------------------------


def _op_id(source_element_id: str) -> str:
    """The deterministic compiler op id for a materialized leaf.

    ``"e" + source_element_id`` — same-document rebuild pins hosts/levels by the
    existing element, so the id is stable across identical inputs (I4) and the
    door/window host ``ref`` resolves to exactly this id for its host wall.
    """

    return "e" + source_element_id


# ---------------------------------------------------------------------------
# Reference-dialect translation (same_document)
# ---------------------------------------------------------------------------


def _translate_reference(
    value: Any,
    host_op_id_by_l1_id: Mapping[str, str],
    pinned_element_id_by_l1_id: Mapping[str, int] | None = None,
) -> Any:
    """Recursively rewrite frozen L1 reference dialects to compiler selectors.

    * ``{"by": "name"|"family_type", ..., "_id": ID}`` -> ``{"by": "element_id",
      "value": int(ID)}`` (same-document: pin the existing datum/type/symbol).
    * ``{"ref": <materialized L1 _id>}`` -> ``by=ref``.
    * ``{"ref": <pinned datum L1 _id>}`` -> ``by=element_id``.

    Everything else (scalars, coordinate lists) passes through unchanged.  Fails
    closed: an unresolvable host ref or a non-integer ``_id`` raises
    ``MaterializeError`` (never a silently-wrong selector, I2).
    """

    pinned = pinned_element_id_by_l1_id or {}
    if isinstance(value, list):
        return [
            _translate_reference(item, host_op_id_by_l1_id, pinned)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    if "by" in value:
        raw_id = value.get("_id")
        try:
            element_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise MaterializeError(
                f"L1 reference _id {raw_id!r} is not an integer ElementId"
            ) from exc
        return {"by": "element_id", "value": element_id}
    if "ref" in value:
        l1_id = value["ref"]
        op_id = host_op_id_by_l1_id.get(l1_id)
        if op_id is not None:
            return {"by": "ref", "value": op_id}
        pinned_id = pinned.get(l1_id)
        if pinned_id is not None:
            return {"by": "element_id", "value": pinned_id}
        raise MaterializeError(
            f"reference {l1_id!r} has neither a materialized op nor an "
            "explicit pinned element")
    return {
        key: _translate_reference(item, host_op_id_by_l1_id, pinned)
        for key, item in value.items()
    }


def _iter_refs(value: Any) -> Iterator[str]:
    """Every ``{"ref": <l1_id>}`` target inside a params tree.

    Mirrors ``_translate_reference``'s traversal exactly — same early exits on
    ``by`` and ``ref`` — so what this finds is precisely what that would try to
    translate.  Two walks that disagree would be worse than none.
    """

    if isinstance(value, list):
        for item in value:
            yield from _iter_refs(item)
        return
    if not isinstance(value, dict):
        return
    if "by" in value:
        return
    if "ref" in value:
        target = value["ref"]
        if isinstance(target, str):
            yield target
        return
    for item in value.values():
        yield from _iter_refs(item)


def _offset_leaf(leaf: L1Node, offset_mm: Vec3 | None) -> L1Node:
    """Optionally translate a leaf's coordinate fields by ``offset_mm``.

    Reuses ``component._translate_leaf`` (the canonicalization authority for the
    coordinate-field set) so the materializer never writes its own coordinate
    walk (per the SPEC's explicit instruction).  ``offset_mm=None`` is the
    identity and returns the leaf unchanged.
    """

    if offset_mm is None:
        return leaf
    return _translate_leaf(leaf, offset_mm)  # type: ignore[return-value]


def _reconcile_arc_endpoints(leaf: dict[str, Any]) -> dict[str, Any]:
    """Пересчитать концы дуговой стены ИЗ дуги после переноса.

    ЗАМЕР 28.07 (живая пересборка ЭОМ на +100 м): компилятор отказал
    `KIR-T002: концы дуги не совпадают с p0_mm/p1_mm (> 1.0 мм)`.

    Причина — независимое округление ДВУХ записей одной кривой. Перенос
    прогоняет координаты через `_round_mm` (канонизация на сетку 1 мм), и это
    касается p0/p1 и центра, но НЕ радиуса и НЕ углов: они не координатные
    поля. На радиусе ~30 м снос центра на полмиллиметра уводит конец дуги на
    1.08 мм — за допуск в 1.0.

    Дословно на стене e1292628 модели ЭОМ:
        L0            197161.9542617473
        после сдвига  297162.0     ← округлено
        дуга даёт     297161.5     ← полная точность

    Правильное лечение — не ослабить допуск, а убрать второй источник
    правды: у дуговой стены концы ВЫВОДЯТСЯ из дуги, а не хранятся рядом с
    ней. Тогда согласованность держится построением и не зависит ни от шага
    канонизации, ни от радиуса.

    Что СОХРАНЯЕТСЯ намеренно:
      * ориентация (какой конец p0, а какой p1) — берётся ближайший к уже
        записанному p0, потому что Revit хранит направление стены и менять
        его нельзя;
      * z — у p0/p1 это отметка базового уровня, а у дуги её собственная
        высота захвата; компилятор сверяет ТОЛЬКО план (x/y), и подменять z
        значило бы чинить не то.

    ПОЧЕМУ ЗДЕСЬ, А НЕ В ПЕРЕНОСЕ. Сначала я поставил это в `_translate_leaf`
    — и упал тест `test_arc_center_translates_and_both_canons_localize_it`:
    канонический хеш обязан быть ИНВАРИАНТЕН К ПЕРЕНОСУ, иначе элемент теряет
    тождество при перемещении, а на этом держатся дедупликация и меркл.
    Правка меняла координаты только у перенесённой копии и потому ломала
    инвариант. Согласование концов — свойство ОПЕРАЦИИ, которую проверяет
    компилятор, а не листа, который хранит тождество; здесь оно безвредно.
    """
    params = leaf.get("params")
    if not isinstance(params, dict):
        return leaf
    arc = params.get("arc")
    p0, p1 = params.get("p0_mm"), params.get("p1_mm")
    if (not isinstance(arc, dict) or not isinstance(p0, list)
            or not isinstance(p1, list) or len(p0) < 2 or len(p1) < 2):
        return leaf
    try:
        from kukai.ir.authoring import _arc_endpoints_mm
        from kukai.ir.decompile import recompile
        a0, a1 = _arc_endpoints_mm(recompile.curve_from_dict(arc, "arc").to_dict())
    except Exception:  # noqa: BLE001 — сверка не смеет ронять перенос
        return leaf

    def _d2(u, v) -> float:
        return (float(u[0]) - float(v[0])) ** 2 + (float(u[1]) - float(v[1])) ** 2

    if _d2(a0, p0) + _d2(a1, p1) > _d2(a1, p0) + _d2(a0, p1):
        a0, a1 = a1, a0
    out_params = dict(params)
    out_params["p0_mm"] = [float(a0[0]), float(a0[1])] + list(p0[2:])
    out_params["p1_mm"] = [float(a1[0]), float(a1[1])] + list(p1[2:])
    return {**leaf, "params": out_params}


def _leaf_to_op(
    leaf: L1Node,
    host_op_id_by_l1_id: Mapping[str, str],
    offset_mm: Vec3 | None,
    pinned_element_id_by_l1_id: Mapping[str, int] | None = None,
) -> dict:
    """Translate one op-leaf into a raw compiler op dict.

    The compiler op dict is ``{"op": <op_name>, "id": <op_id>, **params}`` where
    every ``params`` reference has been rewritten to the selector dialect.  The
    leaf's own coordinate fields are the ONLY thing ``offset_mm`` touches (the
    reference selectors carry no coordinates).
    """

    placed = _reconcile_arc_endpoints(_offset_leaf(leaf, offset_mm))
    params = _translate_reference(
        placed["params"], host_op_id_by_l1_id,
        pinned_element_id_by_l1_id)
    op: dict[str, Any] = {"op": placed["op_name"], "id": _op_id(
        placed["source_element_id"])}
    op.update(params)
    return op


_DIRECTSHAPE_TOKEN_BY_OST = {
    built_in_category: token
    for token, built_in_category in DIRECTSHAPE_CATEGORIES.items()
}


def _atom_escrow_op(
    leaf: L1Node,
    geometry: GeometryExtraction,
    record: GeometryIndexRecord,
    offset_mm: Vec3 | None,
) -> tuple[dict[str, Any] | None, _EscrowCandidate | None, SkipRecord | None]:
    """Turn one Tier-G atom into an honestly labelled DirectShape candidate."""

    source_id = leaf["source_element_id"]
    source_category = leaf["category"]
    if source_category not in {"DirectShape", "ImportInstance"} \
            and record.category != source_category:
        return None, None, SkipRecord(
            source_id=source_id,
            category=source_category,
            reason="atom_escrow:category_identity_mismatch",
        )
    try:
        mesh = geometry.world_fallback_mesh_for_record(record)
    except GeometryExtractionError:
        return None, None, SkipRecord(
            source_id=source_id,
            category=source_category,
            reason="atom_escrow:geometry_refused",
        )

    # Preserve an already-neutral source category when the forward operation
    # can name it honestly.  A wall/floor/etc is always escrowed as a generic
    # model: retaining OST_Walls on a mesh would impersonate BIM semantics.
    category = _DIRECTSHAPE_TOKEN_BY_OST.get(
        record.category, "generic_model")
    name = f"KIR escrow {source_category} {source_id}"[:64]
    synthetic: Any = {
        "kind": "op",
        "op_name": "create_directshape",
        "_id": leaf["_id"],
        "type_name": leaf.get("type_name", ""),
        "params": {
            "mesh": {
                "vertices_mm": [list(vertex) for vertex in mesh.vertices_mm],
                "triangles": [list(triangle) for triangle in mesh.triangles],
            },
            "category": category,
            "name": name,
        },
        "source_element_id": source_id,
        "level_name": leaf.get("level_name"),
        "anchor_mm": leaf.get("anchor_mm"),
    }
    op = _leaf_to_op(synthetic, {}, offset_mm)
    diagnostics: list[Any] = []
    validated_mesh = validate_mesh(op.get("mesh"), op["id"], "mesh", diagnostics)
    if validated_mesh is None:
        return None, None, SkipRecord(
            source_id=source_id,
            category=source_category,
            reason="atom_escrow:mesh_refused",
        )
    op["mesh"] = validated_mesh
    assert record.geo_hash is not None
    materialized_mesh = GmMesh(
        vertices_mm=tuple(
            tuple(vertex) for vertex in validated_mesh["vertices_mm"]),
        triangles=tuple(
            tuple(triangle) for triangle in validated_mesh["triangles"]),
    )
    candidate = _EscrowCandidate(
        source_id=source_id,
        source_category=source_category,
        directshape_category=category,
        source_geometry_hash=record.geo_hash,
        geometry_tier=record.tier.value,
        op_id=op["id"],
        mesh=materialized_mesh,
    )
    return op, candidate, None


# ---------------------------------------------------------------------------
# Chunking (Д5)
# ---------------------------------------------------------------------------


def _host_l1_ref(leaf: L1Node) -> str | None:
    """Return the host L1 ``_id`` a hosted op references, or None."""

    host = leaf["params"].get("host") if leaf["kind"] == "op" else None
    if isinstance(host, dict) and "ref" in host:
        return host["ref"]
    return None


@dataclass(frozen=True, slots=True)
class _HostGroup:
    """A host op plus its hosted children — the indivisible chunk unit (Д5a)."""

    anchor_source_id: str
    leaves: tuple[L1Node, ...]


def _build_host_groups(op_leaves: Sequence[L1Node]) -> list[_HostGroup]:
    """Cluster non-tail ops into ref-atomic groups (Д5a).

    The indivisible unit is a CONNECTED COMPONENT of the whole ``ref`` graph,
    not a host subtree.  ``_translate_reference`` resolves every ``ref`` against
    the run-wide op-id map, so a ``ref`` whose target landed in a different
    program cannot be satisfied: the compiler refuses that chunk with
    ``KIR-L003`` («ref не указывает на более ранний оп»).  Grouping must
    therefore cover exactly what ``_translate_reference`` will translate, which
    is what ``_iter_refs`` walks.

    Measured 2026-08-02 on a 59-storey tower (`k2_ar_rd_v8`): grouping by the
    ``host`` param alone left 39 of 133 chunks refused.  The dominant case was
    ``create_tag.target`` → ``create_door``: a tag is not HOSTED by the door, so
    it became its own root and was packed into an unrelated chunk — five tags
    per door, refs crossing the boundary every time.  Snowdon never showed it
    because the whole model fits inside one chunk.

    Grouping is undirected on purpose: ORDER inside a chunk is law (d)'s job
    (``_toposort_chunk``), and only membership belongs here.  A ref to a
    deliberately omitted same-document datum has already been proved external
    and is translated to ``by=element_id``; it therefore creates no graph
    edge.  Any other absent target is removed as a typed orphan before this
    function — never silently rehosted or allowed to disappear (I2).

    A component larger than ``chunk_target`` becomes its own oversized chunk
    (``_pack_groups``); past ``MAX_BULK_OPS`` the compiler refuses it by size.
    That is a loud, typed limit, unlike the silent boundary-crossing ref it
    replaces.
    """

    by_l1_id = {leaf["_id"]: leaf for leaf in op_leaves}
    if len(by_l1_id) != len(op_leaves):
        raise MaterializeError("duplicate L1 ids in host graph")

    adjacency: dict[str, set[str]] = {leaf_id: set() for leaf_id in by_l1_id}
    for leaf in op_leaves:
        leaf_id = leaf["_id"]
        for target in _iter_refs(leaf["params"]):
            if target in by_l1_id and target != leaf_id:
                adjacency[leaf_id].add(target)
                adjacency[target].add(leaf_id)

    visited: set[str] = set()
    groups: list[_HostGroup] = []
    # Deterministic component discovery: seed order and member order both keyed
    # by source_element_id, so identical input always yields identical chunks.
    for seed in sorted(op_leaves, key=lambda node: node["source_element_id"]):
        seed_id = seed["_id"]
        if seed_id in visited:
            continue
        component: list[L1Node] = []
        stack = [seed_id]
        visited.add(seed_id)
        while stack:
            current = stack.pop()
            component.append(by_l1_id[current])
            for neighbour in sorted(adjacency[current]):
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append(neighbour)
        component.sort(key=lambda node: node["source_element_id"])
        groups.append(_HostGroup(
            anchor_source_id=component[0]["source_element_id"],
            leaves=tuple(component)))

    if len(visited) != len(op_leaves):
        missing = sorted(set(by_l1_id) - visited)
        raise MaterializeError(
            "ref graph left leaves unassigned; refusing unmaterialized leaves: "
            + ", ".join(missing[:8]))
    return groups


def _pack_groups(
    groups: Sequence[_HostGroup], chunk_target: int,
) -> list[list[L1Node]]:
    """Greedily pack host-groups into chunks near ``chunk_target`` (Д5c).

    A group is never split (host-atomicity, Д5a): a group larger than
    ``chunk_target`` still becomes its own chunk.  Packing is deterministic
    (groups arrive pre-sorted by anchor source id).
    """

    effective_target = min(chunk_target, MAX_BULK_OPS)
    chunks: list[list[L1Node]] = []
    current: list[L1Node] = []
    for group in groups:
        if len(group.leaves) > MAX_BULK_OPS:
            raise MaterializeError(
                "host-atomic group exceeds compiler bulk limit: "
                f"{len(group.leaves)} > {MAX_BULK_OPS} "
                f"(host source {group.anchor_source_id})")
        if current and len(current) + len(group.leaves) > effective_target:
            chunks.append(current)
            current = []
        current.extend(group.leaves)
    if current:
        chunks.append(current)
    return chunks


def _toposort_chunk(chunk: Sequence[L1Node]) -> list[L1Node]:
    """Order a chunk so every referenced op precedes the ops that ref it (Д5d).

    Kahn over ALL intra-chunk ``ref`` edges, not just ``host``.  The compiler
    requires a ref to name an EARLIER op (``KIR-L003``), and an op may depend on
    several targets at once (``create_dimension.refs_w``), so a one-parent tree
    walk cannot express the constraint.  Measured 2026-08-02 on `k2_ar_rd_v8`:
    with membership fixed but ordering still host-only, ``create_tag`` landed at
    index 219 and its ``create_door`` target at 227 in the SAME chunk — grouped
    correctly and still refused.

    Determinism (I4): ties are broken by ``source_element_id`` exactly as
    before, so identical chunks keep producing byte-identical order.

    Membership (Д5a) guarantees every materialized ref target is in this
    chunk.  Same-document datum pins are external ``element_id`` selectors and
    intentionally create no ordering edge.  A leaf left unordered therefore
    means a genuine cycle, not a boundary crossing.
    """

    by_l1_id = {leaf["_id"]: leaf for leaf in chunk}
    order_of = {leaf["_id"]: index for index, leaf in enumerate(chunk)}

    pending: dict[str, set[str]] = {}
    dependents: dict[str, list[str]] = {}
    for leaf in chunk:
        leaf_id = leaf["_id"]
        targets = {
            ref for ref in _iter_refs(leaf["params"])
            if ref in by_l1_id and ref != leaf_id
        }
        pending[leaf_id] = targets
        for target in targets:
            dependents.setdefault(target, []).append(leaf_id)

    def key(leaf_id: str) -> tuple[str, int]:
        return (by_l1_id[leaf_id]["source_element_id"], order_of[leaf_id])

    ready = sorted(
        (leaf_id for leaf_id, targets in pending.items() if not targets),
        key=key, reverse=True)
    ordered: list[L1Node] = []
    while ready:
        leaf_id = ready.pop()
        ordered.append(by_l1_id[leaf_id])
        freed: list[str] = []
        for dependent in dependents.get(leaf_id, ()):
            waiting = pending[dependent]
            waiting.discard(leaf_id)
            if not waiting:
                freed.append(dependent)
        if freed:
            ready.extend(freed)
            ready.sort(key=key, reverse=True)
    if len(ordered) != len(chunk):
        raise MaterializeError(
            "chunk toposort did not cover every leaf (cyclic host ref)")
    return ordered


# ---------------------------------------------------------------------------
# Program assembly
# ---------------------------------------------------------------------------


def _program(ops: Sequence[dict]) -> dict:
    return {"ir_version": spec.IR_VERSION, "ops": list(ops)}


def _materialize_chunk(
    chunk: Sequence[L1Node],
    host_op_id_by_l1_id: Mapping[str, str],
    offset_mm: Vec3 | None,
    pinned_element_id_by_l1_id: Mapping[str, int] | None = None,
) -> dict:
    ordered = _toposort_chunk(chunk)
    return _program([
        _leaf_to_op(
            leaf, host_op_id_by_l1_id, offset_mm,
            pinned_element_id_by_l1_id)
        for leaf in ordered
    ])


def leaves_to_program(
    leaves: Iterable[L1Node],
    *,
    mode: str = "same_document",
    geometry: GeometryExtraction | None = None,
    escrow_source_ids: Iterable[str] | None = None,
    include_datums: bool = False,
    chunk_target: int = 250,
    offset_mm: Vec3 | None = None,
    solo_source_ids: Iterable[str] | None = None,
) -> MaterializeResult:
    """Translate L1 leaves into raw compiler-input programs.

    Parameters
    ----------
    leaves:
        Any iterable of frozen L1 nodes (e.g. ``fold.iter_l1_leaves(tree)``).
    mode:
        ``"same_document"`` pins references and skips atoms.  ``"escrow"``
        uses the same reference policy for semantic ops and additionally turns
        atoms with accepted Tier-G geometry into honestly labelled
        ``create_directshape`` candidates.  ``"fresh_document"`` remains a
        future B4 hook and is refused here.
    geometry:
        Required in ``"escrow"`` mode and forbidden otherwise.  The bundle is
        already typed and source-bound by live DECOMPILE; this boundary never
        accepts an unvalidated dictionary as geometry evidence.
    escrow_source_ids:
        Optional exact allow-list of atom ``source_element_id`` values eligible
        for escrow materialization.  It is valid only in ``"escrow"`` mode.
        Atoms outside the list remain visible as typed skips, so a bounded A5
        scope cannot silently turn into a whole-model geometry write.
    include_datums:
        When False (Д3 default) ``create_level`` / ``create_grid`` leaves are
        skipped (pinned to existing elements) and counted in
        ``stats.datums_skipped``.  When True they are materialized (future
        fresh-document rebuild).
    chunk_target:
        Approximate ops per non-solo/non-tail program; expanded only to keep a
        host-group whole (Д5c).
    offset_mm:
        Optional ``(dx, dy, dz)`` translation applied to every materialized op's
        coordinate fields (via ``component._translate_leaf``).
    solo_source_ids:
        Source element ids whose HOST GROUP must get a program of its own —
        РАДИУС ПОРАЖЕНИЯ, а не оптимизация.

        Повод замерен 28.07 на живой пересборке фасада SOB6.2: чанк из 250
        опов откатился целиком с отказом Revit «Не удалось сформировать тип
        "ATR_Панель витража с решеткой : Интегрированная Вентиляционная
        решетка" [элементы: 11401364, 11402544]» — авто-панель, которую
        порождает ТИП витражного носителя. Одна такая стена, поставленная
        пробой в одиночку, строится; несколько в одной транзакции — нет.
        А по документации сборок (``SubTransaction.Commit``) изменения
        подтверждаются только с родительской транзакцией, и отказ,
        отложенный до её Commit, стирает ВЕСЬ чанк — per-op изоляция такое
        не удерживает по построению.

        Изолируется именно ГРУППА, а не отдельный оп: у хозяина могут быть
        пристроенные опы (ячейки витража), и вынести хозяина без них значило
        бы разорвать host-atomicity (Д5a).

        Кого изолировать, решает ВЫЗЫВАЮЩИЙ — здесь нет ни одного признака
        витража: материализатор не знает боковых индексов и не должен.

    Returns a :class:`MaterializeResult`.  Every source leaf is represented by
    a semantic op, an escrow op plus :class:`EscrowRecord`, or a typed
    :class:`SkipRecord` — never silently dropped (I2).
    """

    if mode not in {"same_document", "escrow"}:
        raise MaterializeError(
            f"mode {mode!r} is not implemented "
            "(expected 'same_document' or 'escrow')")
    if mode == "escrow" and not isinstance(geometry, GeometryExtraction):
        raise MaterializeError(
            "mode 'escrow' requires a validated GeometryExtraction")
    if mode == "same_document" and geometry is not None:
        raise MaterializeError(
            "geometry evidence requires explicit mode 'escrow'")
    if mode == "same_document" and escrow_source_ids is not None:
        raise MaterializeError(
            "escrow_source_ids requires explicit mode 'escrow'")
    if not isinstance(chunk_target, int) or chunk_target < 1:
        raise MaterializeError("chunk_target must be a positive integer")

    leaf_list = list(leaves)
    _validate_input_leaves(leaf_list)
    selected_escrow_ids: frozenset[str] | None = None
    if escrow_source_ids is not None:
        if isinstance(escrow_source_ids, (str, bytes, bytearray)):
            raise MaterializeError(
                "escrow_source_ids must be an iterable of source ids")
        raw_selected = tuple(escrow_source_ids)
        if any(not isinstance(value, str) or not value
               for value in raw_selected):
            raise MaterializeError(
                "escrow_source_ids must contain non-empty strings")
        if len(set(raw_selected)) != len(raw_selected):
            raise MaterializeError("escrow_source_ids contains duplicates")
        selected_escrow_ids = frozenset(raw_selected)
        atom_source_ids = {
            leaf["source_element_id"] for leaf in leaf_list
            if leaf["kind"] == "atom"
        }
        unknown = sorted(selected_escrow_ids - atom_source_ids)
        if unknown:
            raise MaterializeError(
                "escrow_source_ids are not atom leaves: " + ", ".join(unknown))
    op_leaves = [leaf for leaf in leaf_list if leaf["kind"] == "op"]
    input_op_leaves = len(op_leaves)

    # Same-document datum policy does not mean that the datum disappears.
    # It stays an explicit external dependency pinned by the ElementId from
    # which its L1 leaf was lifted.  Consumers such as create_dimension may
    # therefore reference it without forcing a duplicate level/grid create.
    pinned_element_id_by_l1_id: dict[str, int] = {}
    if not include_datums:
        for leaf in op_leaves:
            if leaf["op_name"] not in _DATUM_OPS:
                continue
            raw_id = leaf["source_element_id"]
            try:
                element_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise MaterializeError(
                    "pinned datum source_element_id is not an integer "
                    f"ElementId: {raw_id!r}") from exc
            pinned_element_id_by_l1_id[leaf["_id"]] = element_id

    # Host op-id map spans EVERY materialized op-leaf (across all chunks) so a
    # hosted ref can be validated before chunking; the chunker then guarantees
    # the host and hosted land together (Д5a).
    host_op_id_by_l1_id: dict[str, str] = {}
    for leaf in op_leaves:
        if leaf["op_name"] in _DATUM_OPS and not include_datums:
            continue
        host_op_id_by_l1_id[leaf["_id"]] = _op_id(leaf["source_element_id"])

    # A hosted op can reference a host that never became an op — its wall was
    # an atom.  That reference is unresolvable, and dropping ANY op drags in
    # whatever was hosted on it, so this iterates to a fixed point rather than
    # making one pass and leaving the next dangling ref to crash.
    #
    # Until this existed the dangling ref raised out of the middle of chunk
    # assembly and killed the whole run: on SOB6.2 five unbuildable walls stood
    # to cost the other 1 069 elements.  Contract (I2, this function's own
    # docstring): every op-leaf materializes or becomes a TYPED skip.
    orphan_host: dict[str, str] = {}
    while True:
        newly_orphaned = False
        for leaf in op_leaves:
            l1_id = leaf["_id"]
            if l1_id in orphan_host or l1_id not in host_op_id_by_l1_id:
                continue
            missing = next(
                (ref for ref in _iter_refs(leaf["params"])
                 if ref not in host_op_id_by_l1_id
                 and ref not in pinned_element_id_by_l1_id), None)
            if missing is None:
                continue
            orphan_host[l1_id] = missing
            del host_op_id_by_l1_id[l1_id]
            newly_orphaned = True
        if not newly_orphaned:
            break
    op_leaves = [leaf for leaf in op_leaves if leaf["_id"] not in orphan_host]

    skipped: list[SkipRecord] = []
    escrow_ops: list[tuple[str, dict[str, Any], _EscrowCandidate]] = []
    atoms_skipped = 0
    datums_skipped = 0
    geometry_records = (
        {record.element_id: record for record in geometry.index}
        if geometry is not None else {})
    geometry_failures = (
        {failure.element_id: failure for failure in geometry.failures}
        if geometry is not None else {})
    for leaf in leaf_list:
        if leaf["kind"] == "op" and leaf["_id"] in orphan_host:
            skipped.append(SkipRecord(
                source_id=leaf["source_element_id"],
                category=leaf["op_name"],
                reason="host_unmaterialized:" + orphan_host[leaf["_id"]]))
            continue
        if leaf["kind"] == "atom":
            source_id = leaf["source_element_id"]
            reason_code = leaf["reason"]["code"]
            if mode == "escrow" and reason_code != "generator_child":
                if (selected_escrow_ids is not None
                        and source_id not in selected_escrow_ids):
                    skipped.append(SkipRecord(
                        source_id=source_id,
                        category=leaf["category"],
                        reason="atom_escrow:not_selected",
                    ))
                    atoms_skipped += 1
                    continue
                record = geometry_records.get(source_id)
                failure = geometry_failures.get(source_id)
                if record is None:
                    if failure is not None:
                        failure_reason = (
                            failure.reason.value
                            if failure.reason is not None
                            else "unavailable")
                        reason = (
                            "atom_escrow:geometry_failure:" + failure_reason)
                    else:
                        reason = "atom_escrow:missing_geometry_evidence"
                    skipped.append(SkipRecord(
                        source_id=source_id,
                        category=leaf["category"],
                        reason=reason,
                    ))
                    atoms_skipped += 1
                    continue
                if record.tier is ExtractedGeometryTier.A:
                    skipped.append(SkipRecord(
                        source_id=source_id,
                        category=leaf["category"],
                        reason="atom_escrow:tier_a_no_geometry",
                    ))
                    atoms_skipped += 1
                    continue
                assert geometry is not None
                op, candidate, refusal = _atom_escrow_op(
                    leaf, geometry, record, offset_mm)
                if refusal is not None:
                    skipped.append(refusal)
                    atoms_skipped += 1
                    continue
                assert op is not None and candidate is not None
                escrow_ops.append((source_id, op, candidate))
                continue
            skipped.append(SkipRecord(
                source_id=source_id,
                category=leaf["category"],
                reason="atom:" + reason_code))
            atoms_skipped += 1
        elif leaf["op_name"] in _DATUM_OPS and not include_datums:
            skipped.append(SkipRecord(
                source_id=leaf["source_element_id"],
                category=leaf["op_name"],
                reason="datum_pinned_existing"))
            datums_skipped += 1

    # Partition the materializable ops into solo / tail / body streams.
    solo_leaves: list[L1Node] = []
    tail_leaves: list[L1Node] = []
    body_leaves: list[L1Node] = []
    for leaf in op_leaves:
        op_name = leaf["op_name"]
        if op_name in _DATUM_OPS and not include_datums:
            continue
        if op_name in _SOLO_OPS or spec.is_version_fragile(
                op_name, leaf.get("params")):
            # ДВА РОДА СОЛО, И ОНИ НЕ СЛИТЫ. `_SOLO_OPS` — имена, причина своя
            # (области правки лестницы). `is_version_fragile` — пары (оп, ПОЛЕ),
            # причина другая: отсутствующая перегрузка API на старой версии.
            #
            # ЗАЧЕМ ВТОРОЙ. Отказ эмиссии роняет ПРОГРАММУ, а не оп, и размер
            # куска назначен нами: замерено 13.08 на `k2_ar_rd_v7` — ТРИ опа,
            # невыразимых на Revit 2021, унесли 2 742 совместимых, 1 : 914.
            # Ключить по ИМЕНИ было нельзя: соло уехали бы все 252 перекрытия
            # вместо 44 с проёмами, и мы разменяли бы потерю на огрызки.
            solo_leaves.append(leaf)
        elif op_name in _TAIL_OPS:
            tail_leaves.append(leaf)
        else:
            body_leaves.append(leaf)

    programs: list[dict] = []

    # Body: host-atomic groups packed into ~chunk_target programs (Д5a/c/d).
    isolate = frozenset(solo_source_ids or ())
    groups = _build_host_groups(body_leaves)
    isolated = [group for group in groups if group.anchor_source_id in isolate]
    packed = [group for group in groups
              if group.anchor_source_id not in isolate]
    for chunk in _pack_groups(packed, chunk_target):
        programs.append(_materialize_chunk(
            chunk, host_op_id_by_l1_id, offset_mm,
            pinned_element_id_by_l1_id))

    # Изолированные группы — каждая своей программой, ПЕРЕД хвостом: помещения
    # хвоста обязаны ставиться после ВСЕХ стен прогона (Д5b), а изолированная
    # группа стены содержит.
    for group in sorted(isolated, key=lambda item: item.anchor_source_id):
        programs.append(_materialize_chunk(
            list(group.leaves), host_op_id_by_l1_id, offset_mm,
            pinned_element_id_by_l1_id))

    # Tail: rooms after all walls of the whole run (Д5b).  Rooms carry no host
    # ref, so they pack purely by size with a stable source-id order.
    tail_sorted = sorted(
        tail_leaves, key=lambda node: node["source_element_id"])
    tail_chunk_size = min(chunk_target, MAX_BULK_OPS)
    for start in range(0, len(tail_sorted), tail_chunk_size):
        chunk = tail_sorted[start:start + tail_chunk_size]
        programs.append(_program([
            _leaf_to_op(
                leaf, host_op_id_by_l1_id, offset_mm,
                pinned_element_id_by_l1_id)
            for leaf in chunk
        ]))

    # Solo: one single-op program per stairs leaf (KIR-L002).
    solo_sorted = sorted(
        solo_leaves, key=lambda node: node["source_element_id"])
    for leaf in solo_sorted:
        programs.append(_program([
            _leaf_to_op(
                leaf, host_op_id_by_l1_id, offset_mm,
                pinned_element_id_by_l1_id)]))

    # Escrow geometry is last and one source atom per program.  It has no BIM
    # dependency edges, while isolation keeps one malformed/heavy mesh from
    # invalidating unrelated semantic chunks or sibling atom evidence.
    escrow_programs: list[tuple[int, _EscrowCandidate]] = []
    for _source_id, op, candidate in sorted(
            escrow_ops, key=lambda item: item[0]):
        program_index = len(programs)
        programs.append(_program([op]))
        escrow_programs.append((program_index, candidate))

    materialized_ops = sum(len(program["ops"]) for program in programs)
    stats = MaterializeStats(
        op_leaves=input_op_leaves,
        materialized_ops=materialized_ops,
        programs=len(programs),
        atoms_skipped=atoms_skipped,
        atoms_escrowed=len(escrow_programs),
        datums_skipped=datums_skipped,
        semantic_ops_skipped=len(orphan_host),
        solo_programs=len(solo_sorted),
        tail_ops=len(tail_sorted),
        isolated_groups=len(isolated),
    )
    plans, plan_checks = _plan_materialized_programs(programs)
    escrowed: list[EscrowRecord] = []
    for program_index, candidate in escrow_programs:
        plan = plans[program_index]
        if plan is None:
            check = plan_checks[program_index]
            raise MaterializeError(
                "atom escrow program was refused by typed KIR plan: "
                + ",".join(check.diagnostic_codes))
        escrowed.append(candidate.bind(
            program_index=program_index,
            plan_digest=plan.plan_digest,
        ))
    accounting = _build_materialization_accounting(
        leaf_list,
        programs,
        skipped,
        escrowed,
        include_datums=include_datums,
    )
    return MaterializeResult(
        programs=programs,
        skipped=skipped,
        escrowed=escrowed,
        stats=stats,
        accounting=accounting,
        plans=plans,
        plan_checks=plan_checks,
    )


# ---------------------------------------------------------------------------
# Group bridge (KUKAI_IR_NATIVE_GROUP) — optional
# ---------------------------------------------------------------------------


#: Отказы моста групп за последний вызов `component_to_group_program`.
#:
#: РОД СПИСКА: **закрытый, но не полный** — состав держится дисциплиной, и
#: новая причина обязана быть добавлена рукой. Полным по построению он быть не
#: может: отказ приходит из чужих слоёв (материализатор, заземление, мост), и
#: перечислить их исходы заранее нельзя.
#:
#: ЗАЧЕМ ВООБЩЕ. До 13.08 каждый отказ был `return None`: вызывающий уходил на
#: N поштучных элементов и не знал, ПОЧЕМУ группа не собралась — «группы нет»
#: и «группа отказана по названной причине» печатались одинаково. Это тот же
#: класс, что молчаливая отсечка списка и гашение инверсии покрытия, третий
#: случай за смену.
_GROUP_REFUSALS: list[dict[str, str]] = []


def _note_group_refusal(place_op: Any, reason: str, detail: str) -> None:
    """Записать ПРИЧИНУ отказа моста, не меняя его поведения.

    Поведение остаётся прежним и должно остаться: откат на поштучный путь —
    правильный ответ, геометрия не теряется. Меняется только то, что теперь
    можно спросить, почему группы не случилось.
    """
    _GROUP_REFUSALS.append({
        "def_hash": getattr(place_op, "def_hash", "?"),
        "reason": reason,
        "detail": detail[:300],
    })


def last_group_refusals() -> tuple[dict[str, str], ...]:
    """Отказы моста с последнего `reset_group_refusals()`."""
    return tuple(_GROUP_REFUSALS)


def reset_group_refusals() -> None:
    _GROUP_REFUSALS.clear()


def component_to_group_program(place_op: Any) -> dict | None:
    """Assemble a ``create_group`` program from a component-library place-op.

    The native-group bridge (``native_group.py``) proved the placement math but
    left ONE hole: turning a ComponentDefinition's leaves into PRE-GROUNDED
    member authoring op-dicts (``create_group`` requires grounded members —
    element_id selectors, absolute coords — see ``ops_authoring.create_group``).
    This function fills that hole using the same materializer: instantiate the
    definition at occurrence 0's absolute origin, materialize those leaves into
    raw ops, then GROUND them (snapshot-free — the selectors are pure
    element_id/ref, so ``ground`` pins them without a model census) so the
    member ops carry the ``__grounded__`` dicts ``_emit_group`` consumes.

    FAIL-CLOSED / opt-in: returns None (caller keeps the N-element fallback)
    unless ``native_group_enabled()`` and the bridge produces a lossless
    ``NativeGroupOp``; any translation/ground refusal also returns None — never a
    lossy or wrong group.  Gated behind ``KUKAI_IR_NATIVE_GROUP`` (default OFF).
    """

    from kukai.ir.decompile.native_group import (
        assert_group_matches_place_op,
        group_op_from_place_op,
        native_group_enabled,
        native_group_op_to_ir,
    )
    from kukai.ir.decompile.component import instantiate

    if not native_group_enabled():
        return None  # флаг выключен — это не отказ, а покой
    group_op = group_op_from_place_op(place_op)
    if group_op is None:
        _note_group_refusal(place_op, 'placement_math',
                            'мост не смог выразить размещения')
        return None

    # Occurrence 0's members at their absolute canonical origin.
    member_leaves = instantiate(
        group_op.definition, group_op.base_origin_mm,
        instance_index=0, regenerate_ids=False)
    member_result = leaves_to_program(member_leaves, chunk_target=10**9)
    # A group definition is one indivisible unit: every member must materialize
    # into a single program (no host refs cross members here — the definition is
    # self-contained), else the shape is not faithfully groupable.
    if (member_result.skipped or len(member_result.programs) != 1
            or not member_result.compiler_ready):
        _note_group_refusal(
            place_op, 'members_not_one_program',
            f'пропущено {len(member_result.skipped)}, программ '
            f'{len(member_result.programs)}, готова '
            f'{member_result.compiler_ready}')
        return None
    raw_members = member_result.programs[0]["ops"]
    if not raw_members:
        _note_group_refusal(place_op, 'no_members', 'членов не осталось')
        return None

    # Members must be PRE-GROUNDED for _emit_group; element_id/ref selectors
    # ground without a snapshot (ground._needs_pool is False for them).
    try:
        from kukai.ir import ground as ground_mod
        member_plan = member_result.plans[0]
        if member_plan is None:  # narrowed by compiler_ready; defensive seam
            return None
        normed = member_plan.to_ops()
        grounded_members = ground_mod.ground(normed, None)
    except Exception as exc:  # noqa: BLE001 — откат на поштучный путь
        _note_group_refusal(place_op, "grounding_refused", str(exc))
        return None

    # C-RT НА САМОМ МОСТУ (13.08.2026). Проверка написана в `native_group.py`
    # целиком — сверяет мультимножество абсолютных опов развёртки группы с тем,
    # что даёт поштучный путь, В ОБЕ СТОРОНЫ, и отдельно требует доказанной
    # исходной точности, — и до сегодня её не звал НИКТО, кроме тестов.
    # Мост собирал IR, ни разу не спросив, совпадает ли развёртка.
    #
    # Место выбрано перед сборкой IR нарочно: отказ обязан случиться ДО того,
    # как появится оп, который кто-то может отправить.
    try:
        assert_group_matches_place_op(group_op, place_op)
    except Exception as exc:  # noqa: BLE001 — расхождение = откат на поштучные
        _note_group_refusal(place_op, "expansion_mismatch", str(exc))
        return None

    op_id = "grp_" + group_op.def_hash[:12]
    ir = native_group_op_to_ir(
        group_op, grounded_members, op_id=op_id, name=group_op.label or None)
    from kukai.ir.reverse_contract import assert_composed_emission
    assert_composed_emission(ir.get("op"))
    return _program([ir])


__all__ = [
    "EscrowRecord",
    "MATERIALIZATION_ACCOUNTING_SCHEMA",
    "MaterializeError",
    "MaterializationAccounting",
    "MaterializationRecord",
    "MaterializeResult",
    "MaterializeStats",
    "ProgramPlanCheck",
    "SkipRecord",
    "component_to_group_program",
    "last_group_refusals",
    "reset_group_refusals",
    "leaves_to_program",
]
