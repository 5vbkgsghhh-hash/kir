"""Normalize clash hulls into one authoritative federation frame.

This module is deliberately upstream of candidate generation and proof
issuance.  A serialized overlap/inner certificate is never transported across
a coordinate-frame boundary: geometry is transformed first and all pair
proofs are issued again against the transformed occurrence-keyed records.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.ir.decompile.identity import OccurrenceIdentity
from kukai.ir.decompile.federation import (
    FederationAssemblyError,
    LinkAuthorityBinding,
)
from kukai.ir.decompile.schema import (
    FederationTransformEvidence,
    FederationTransformTarget,
    L0SchemaError,
)


FEDERATED_HULLS_SCHEMA = "kir-clash-federated-hulls/2"
FEDERATION_PROOF_GAP = "inner_certificate_dropped_at_frame_boundary"
FEDERATION_LEVEL_GAP = "local_level_id_dropped_at_frame_boundary"


class _FrozenJsonDict(dict):
    """JSON-compatible mapping that cannot drift after proof issuance."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("federated hull metadata is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenJsonList(list):
    """JSON-compatible sequence that cannot drift after proof issuance."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("federated hull metadata is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


def _freeze_json(value: Any) -> Any:
    """Deep-freeze already validated JSON without changing its wire shape."""

    if isinstance(value, dict):
        frozen = _FrozenJsonDict()
        dict.update(frozen, {
            key: _freeze_json(item) for key, item in value.items()
        })
        return frozen
    if isinstance(value, list):
        frozen = _FrozenJsonList()
        list.extend(frozen, (_freeze_json(item) for item in value))
        return frozen
    return value


class _FederatedHullRecord(H.HullRecord):
    """A HullRecord-compatible immutable snapshot used by proof consumers.

    Ordinary extraction records intentionally remain mutable for compatibility.
    Once a record enters ``FederatedHullSet`` its geometry and metadata are a
    content-addressed proof surface, so field replacement must be impossible.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, "extra", _freeze_json(self.extra))
        object.__setattr__(self, "_federation_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_federation_sealed", False):
            raise TypeError("federated hull record is immutable")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_federation_sealed", False):
            raise TypeError("federated hull record is immutable")
        super().__delattr__(name)


class FederationGeometryGapReason(str, Enum):
    MISSING_OCCURRENCE_IDENTITY = "missing_occurrence_identity"
    INVALID_OCCURRENCE_IDENTITY = "invalid_occurrence_identity"
    DUPLICATE_OCCURRENCE_KEY = "duplicate_occurrence_key"
    FEDERATION_ROOT_MISMATCH = "federation_root_mismatch"
    NESTED_LINK_CHAIN_NOT_EXTRACTED = "nested_link_chain_not_extracted"
    MISSING_TRANSFORM = "missing_transform"
    INVALID_TRANSFORM = "invalid_transform"
    ROOT_TRANSFORM_NOT_IDENTITY = "root_transform_not_identity"
    TRANSFORM_SUBJECT_MISMATCH = "transform_subject_mismatch"
    TRANSFORM_TARGET_MISMATCH = "transform_target_mismatch"
    UNTRANSFORMABLE_HULL = "untransformable_hull"
    INVALID_RECORD_METADATA = "invalid_record_metadata"


@dataclass(frozen=True, slots=True)
class FederationGeometryGap:
    source: str
    local_source_id: str
    category: str
    mvp_side: str | None
    type_name: str | None
    section_present: bool | None
    reason: FederationGeometryGapReason
    detail: str
    occurrence_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("gap source must be non-empty")
        if not isinstance(self.local_source_id, str) or not self.local_source_id:
            raise ValueError("gap local_source_id must be non-empty")
        if not isinstance(self.category, str) or not self.category:
            raise ValueError("gap category must be non-empty")
        if self.mvp_side not in {None, *H.MVP_PAIR}:
            raise ValueError("gap mvp_side must be a typed clash side or null")
        rule = H.KIND_TABLE.get(self.category)
        if rule is None or not rule.eligible:
            raise ValueError(
                "federated geometry gaps require a clash-eligible category")
        if self.mvp_side != rule.mvp_side:
            raise ValueError("gap mvp_side contradicts the category table")
        if self.type_name is not None and (
                not isinstance(self.type_name, str) or not self.type_name):
            raise ValueError("gap type_name must be non-empty or null")
        sections_apply = H.category_allows_sections(self.category)
        if sections_apply:
            if not isinstance(self.section_present, bool):
                raise ValueError(
                    "section-capable gap must preserve section presence")
        elif self.section_present is not None:
            raise ValueError(
                "non-section category gap cannot claim section presence")
        if not isinstance(self.reason, FederationGeometryGapReason):
            raise ValueError("gap reason must be typed")
        if not isinstance(self.detail, str) or not self.detail:
            raise ValueError("gap detail must be non-empty")

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "local_source_id": self.local_source_id,
            "category": self.category,
            "mvp_side": self.mvp_side,
            "type_name": self.type_name,
            "section_present": self.section_present,
            "occurrence_key": self.occurrence_key,
            "reason": self.reason.value,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class HullFederationSource:
    """One root or directly-linked clash snapshot and its frame evidence."""

    source: str
    records: tuple[H.HullRecord, ...]
    occurrence_by_local_id: Mapping[str, OccurrenceIdentity | None]
    source_to_root: FederationTransformEvidence | Mapping[str, Any] | None
    link_authority_binding: LinkAuthorityBinding | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("source must be a non-empty string")
        records = tuple(self.records)
        if any(not isinstance(record, H.HullRecord) for record in records):
            raise ValueError("records must contain HullRecord values")
        object.__setattr__(self, "records", records)
        local_ids = tuple(record.source_id for record in records)
        if any(not isinstance(value, str) or not value for value in local_ids):
            raise ValueError("every record must have a non-empty local source id")
        if len(local_ids) != len(set(local_ids)):
            raise ValueError("source records contain duplicate local source ids")
        if not isinstance(self.occurrence_by_local_id, Mapping):
            raise ValueError("occurrence_by_local_id must be a mapping")
        normalized: dict[str, OccurrenceIdentity | None] = {}
        for key, occurrence in self.occurrence_by_local_id.items():
            if not isinstance(key, str) or not key:
                raise ValueError("occurrence map keys must be non-empty strings")
            if occurrence is not None and not isinstance(
                    occurrence, OccurrenceIdentity):
                raise ValueError("occurrence map values must be typed or null")
            normalized[key] = occurrence
        object.__setattr__(
            self, "occurrence_by_local_id",
            MappingProxyType(dict(sorted(normalized.items()))))
        if set(normalized) != set(local_ids):
            missing = sorted(set(local_ids) - set(normalized))
            extra = sorted(set(normalized) - set(local_ids))
            raise ValueError(
                f"occurrence map does not exactly account records; "
                f"missing={missing}, extra={extra}")
        contexts = {
            (occurrence.federation_root,
             occurrence.link_instance_chain,
             occurrence.definition.document.value)
            for occurrence in normalized.values() if occurrence is not None
        }
        if len(contexts) > 1:
            raise ValueError(
                "one HullFederationSource cannot mix document/root/link chains")
        context = next(iter(contexts), None)
        if context is not None:
            root, chain, document_key = context
            if len(chain) == 1:
                binding = self.link_authority_binding
                if not isinstance(binding, LinkAuthorityBinding):
                    raise ValueError(
                        "linked hull source requires LinkAuthorityBinding")
                if (binding.child_context.federation_root != root
                        or binding.child_context.link_instance_chain != chain
                        or binding.linked_document_identity.value != document_key):
                    raise ValueError(
                        "link authority binding differs from source occurrence")
                if isinstance(self.source_to_root, FederationTransformEvidence):
                    binding.assert_transform_subject(
                        self.source_to_root.subject_context.to_dict())
            elif not chain and self.link_authority_binding is not None:
                raise ValueError(
                    "root hull source cannot carry a link authority binding")


@dataclass(frozen=True, slots=True)
class FederationCensus:
    input: int
    transformed: int
    gaps: int

    def __post_init__(self) -> None:
        for name, value in (
            ("input", self.input), ("transformed", self.transformed),
            ("gaps", self.gaps),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"census.{name} must be non-negative int")
        if self.input != self.transformed + self.gaps:
            raise ValueError("federation census does not balance")

    def as_dict(self) -> dict[str, int]:
        return {
            "input": self.input,
            "transformed": self.transformed,
            "gaps": self.gaps,
        }


@dataclass(frozen=True, slots=True)
class FederatedHullSet:
    federation_root: str
    records: tuple[H.HullRecord, ...]
    gaps: tuple[FederationGeometryGap, ...]
    census: FederationCensus
    content_digest: str
    schema_version: str = FEDERATED_HULLS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != FEDERATED_HULLS_SCHEMA:
            raise ValueError("unsupported federated hull schema")
        if not isinstance(self.federation_root, str) or not self.federation_root:
            raise ValueError("federation_root must be non-empty")
        if any(not isinstance(record, _FederatedHullRecord)
               for record in self.records):
            raise ValueError(
                "federated hull records must be immutable canonical snapshots")
        if tuple(sorted(self.records, key=lambda row: row.source_id)) != self.records:
            raise ValueError("federated records must be source-id sorted")
        source_ids = tuple(record.source_id for record in self.records)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("federated record occurrence keys must be unique")
        if not isinstance(self.census, FederationCensus):
            raise ValueError("census must be typed")
        if self.census.transformed != len(self.records):
            raise ValueError("transformed census differs from records")
        if self.census.gaps != len(self.gaps):
            raise ValueError("gap census differs from gaps")
        expected = _digest_payload(self._payload())
        if self.content_digest != expected:
            raise ValueError("federated hull content digest mismatch")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "federation_root": self.federation_root,
            "records": [_record_dict(record) for record in self.records],
            "gaps": [gap.as_dict() for gap in self.gaps],
            "census": self.census.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload(), "content_digest": self.content_digest}


def _digest_payload(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _hull_dict(hull: G.Hull) -> dict[str, Any]:
    if isinstance(hull, G.Aabb):
        return {"kind": "aabb", "lo": list(hull.lo), "hi": list(hull.hi)}
    if isinstance(hull, G.Prism):
        return {
            "kind": "prism", "footprint": [list(point) for point in hull.footprint],
            "z0": hull.z0, "z1": hull.z1,
        }
    if isinstance(hull, G.PrismSet):
        return {
            "kind": "prism_set",
            "pieces": [[list(point) for point in piece]
                       for piece in hull.pieces],
            "z0": hull.z0, "z1": hull.z1,
        }
    if isinstance(hull, G.Capsule):
        return {
            "kind": "capsule", "path": [list(point) for point in hull.path],
            "radius": hull.radius,
        }
    raise TypeError(f"unsupported hull type: {type(hull).__name__}")


def _json_value(value: Any) -> Any:
    """Reject rather than stringify non-JSON metadata into a proof digest."""

    try:
        return json.loads(json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise ValueError("HullRecord.extra must be finite JSON") from exc


def _record_dict(record: H.HullRecord) -> dict[str, Any]:
    return {
        "source_id": record.source_id,
        "category": record.category,
        "label": record.label,
        "mvp_side": record.mvp_side,
        "hull": _hull_dict(record.hull),
        "grade": record.grade,
        "hull_source": record.hull_source,
        "level_id": record.level_id,
        "type_name": record.type_name,
        "section_radius_mm": record.section_radius_mm,
        "section_round": record.section_round,
        "section_source": record.section_source,
        "extra": _json_value(record.extra),
        "inner": None,
    }


def _point(matrix: tuple[float, ...], point: G.Pt3) -> G.Pt3:
    x, y, z = point
    transformed = (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )
    if not all(G._finite(value) for value in transformed):
        raise ValueError("transformed point is non-finite")
    return tuple(G._norm_zero(value) for value in transformed)  # type: ignore[return-value]


def _aabb_of(points: Iterable[G.Pt3]) -> G.Aabb:
    vertices = tuple(points)
    if not vertices:
        raise ValueError("cannot bound an empty transformed hull")
    return G.Aabb(
        tuple(min(point[axis] for point in vertices) for axis in range(3)),
        tuple(max(point[axis] for point in vertices) for axis in range(3)),
    )


def _aabb_vertices(hull: G.Aabb) -> tuple[G.Pt3, ...]:
    return tuple(
        (x, y, z)
        for x in (hull.lo[0], hull.hi[0])
        for y in (hull.lo[1], hull.hi[1])
        for z in (hull.lo[2], hull.hi[2]))


def _z_preserving(matrix: tuple[float, ...]) -> bool:
    # These entries decide whether transformed Z is independent of footprint
    # X/Y.  A tolerance is unsafe here: an accepted 1e-9 tilt multiplied by a
    # sufficiently large footprint can move a vertex outside the claimed
    # vertical prism.  Exact zeros are available for genuine Z-only Revit
    # placements; every other case goes through the all-vertices AABB path.
    return (
        matrix[2] == 0.0
        and matrix[6] == 0.0
        and matrix[8] == 0.0
        and matrix[9] == 0.0
        and abs(matrix[10]) == 1.0)


def _capsule_radius_scale(matrix: tuple[float, ...]) -> tuple[float, bool]:
    """Safe upper bound for the image of a swept sphere.

    The transform schema admits tiny numerical deviations from an exact
    isometry.  Keeping the old radius under a near-shear can under-approximate
    the body.  Gershgorin bounds the largest eigenvalue of ``A.T @ A`` without
    a numerical eigensolver; ``max(1, sqrt(bound))`` therefore cannot shrink
    an expected Revit isometry.  ``exact`` is intentionally algebraic: if the
    float matrix is merely near-orthonormal, the result is conservative.
    """

    columns = tuple(
        (matrix[index], matrix[4 + index], matrix[8 + index])
        for index in range(3))
    gram = tuple(tuple(
        sum(columns[left][axis] * columns[right][axis]
            for axis in range(3))
        for right in range(3)) for left in range(3))
    upper = max(
        gram[index][index]
        + sum(abs(gram[index][other]) for other in range(3)
              if other != index)
        for index in range(3))
    if not G._finite(upper) or upper < 0.0:
        raise ValueError("transform linear norm is non-finite")
    exact = all(
        gram[left][right] == (1.0 if left == right else 0.0)
        for left in range(3) for right in range(3))
    return max(1.0, math.sqrt(upper)), exact


def _transform_prism(
    hull: G.Prism | G.PrismSet,
    matrix: tuple[float, ...],
) -> tuple[G.Hull, bool]:
    if _z_preserving(matrix):
        def xy(point: G.Pt2) -> G.Pt2:
            transformed = _point(matrix, (point[0], point[1], 0.0))
            return transformed[0], transformed[1]

        za = _point(matrix, (0.0, 0.0, hull.z0))[2]
        zb = _point(matrix, (0.0, 0.0, hull.z1))[2]
        z0, z1 = min(za, zb), max(za, zb)
        if isinstance(hull, G.Prism):
            return G.Prism(tuple(xy(point) for point in hull.footprint), z0, z1), True
        return G.PrismSet(
            tuple(tuple(xy(point) for point in piece) for piece in hull.pieces),
            z0, z1), True

    if isinstance(hull, G.Prism):
        points = (
            _point(matrix, (x, y, z))
            for x, y in hull.footprint for z in (hull.z0, hull.z1))
    else:
        points = (
            _point(matrix, (x, y, z))
            for piece in hull.pieces for x, y in piece
            for z in (hull.z0, hull.z1))
    return _aabb_of(points), False


def transform_hull(
    hull: G.Hull,
    evidence: FederationTransformEvidence,
) -> tuple[G.Hull, bool]:
    """Return ``(hull_in_root_frame, exact_representation_preserved)``."""

    if not isinstance(evidence, FederationTransformEvidence):
        raise ValueError("transform evidence must be typed")
    if not evidence.authoritative or evidence.matrix is None:
        raise ValueError("transform evidence is incomplete")
    matrix = evidence.matrix
    if isinstance(hull, G.Capsule):
        if (not isinstance(hull.path, (list, tuple)) or not hull.path
                or not G._finite(hull.radius) or hull.radius < 0.0
                or any(not isinstance(point, (list, tuple))
                       or len(point) != 3
                       or not all(G._finite(v) for v in point)
                       for point in hull.path)):
            raise ValueError("capsule is empty or non-finite")
        # Exact Euclidean isometries preserve swept spheres, including under
        # reflection.  Near-isometries admitted for floating Revit evidence
        # receive a proven conservative radius instead of silently shrinking.
        radius_scale, exact = _capsule_radius_scale(matrix)
        transformed_radius = G._norm_zero(hull.radius * radius_scale)
        if not G._finite(transformed_radius):
            raise ValueError("transformed capsule radius is non-finite")
        return G.Capsule(
            tuple(_point(matrix, point) for point in hull.path),
            transformed_radius), exact
    if isinstance(hull, (G.Prism, G.PrismSet)):
        pieces = ((hull.footprint,) if isinstance(hull, G.Prism)
                  else hull.pieces)
        # PrismSet deliberately admits empty/point/line pieces: they are
        # lower-dimensional conservative bodies, not malformed input.  A
        # plain Prism still denotes a polygon and therefore needs >=3 points.
        if (not isinstance(pieces, (list, tuple))
                or (isinstance(hull, G.Prism)
                    and (not isinstance(hull.footprint, (list, tuple))
                         or len(hull.footprint) < 3))
                or any(not isinstance(piece, (list, tuple)) or not piece
                       for piece in pieces)
                or any(not isinstance(point, (list, tuple))
                       or len(point) != 2
                       or not all(G._finite(v) for v in point)
                       for piece in pieces for point in piece)
                or not G._finite(hull.z0) or not G._finite(hull.z1)
                or hull.z0 > hull.z1):
            raise ValueError("prism is empty, inverted or non-finite")
        if isinstance(hull, G.PrismSet) and not pieces:
            # The image of the empty set is empty in every affine frame.
            return G.PrismSet((), 0.0, 0.0), True
        return _transform_prism(hull, matrix)
    if isinstance(hull, G.Aabb):
        if (not isinstance(hull.lo, (list, tuple))
                or not isinstance(hull.hi, (list, tuple))
                or len(hull.lo) != 3 or len(hull.hi) != 3
                or not all(G._finite(value) for value in (*hull.lo, *hull.hi))
                or any(hull.lo[axis] > hull.hi[axis] for axis in range(3))):
            raise ValueError("AABB is inverted or non-finite")
        # An arbitrary rotated AABB is an OBB.  The kernel has no OBB type, so
        # all eight corners are enclosed in a fresh root-frame AABB.  This can
        # only enlarge the represented body, never shrink it.
        return _aabb_of(_point(matrix, point)
                        for point in _aabb_vertices(hull)), False
    raise ValueError(f"unsupported hull type: {type(hull).__name__}")


def _coerce_transform(
    value: FederationTransformEvidence | Mapping[str, Any] | None,
) -> tuple[FederationTransformEvidence | None, str | None]:
    if value is None:
        return None, "source snapshot carries no transform evidence"
    if isinstance(value, FederationTransformEvidence):
        if not value.authoritative:
            return None, "source transform evidence is incomplete"
        return value, None
    if isinstance(value, Mapping):
        try:
            evidence = FederationTransformEvidence.from_dict(value)
        except (L0SchemaError, TypeError, ValueError) as exc:
            return None, f"source transform evidence is invalid: {exc}"
        if not evidence.authoritative:
            return None, "source transform evidence is incomplete"
        return evidence, None
    return None, "source transform evidence has an invalid type"


def _is_identity(matrix: tuple[float, ...]) -> bool:
    expected = (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    # Root extraction emits Transform.Identity from literals.  A tolerant
    # comparison would accept and then *apply* a non-zero translation/tilt.
    return matrix == expected


def _transform_binding_error(
    transform: FederationTransformEvidence,
    occurrence: OccurrenceIdentity,
) -> tuple[FederationGeometryGapReason, str] | None:
    """Prove the matrix belongs to this exact occurrence, not a neighbour."""

    subject = transform.subject_context
    if subject is None or not subject.replay_safe:
        return (
            FederationGeometryGapReason.TRANSFORM_SUBJECT_MISMATCH,
            "transform has no replay-safe document subject binding")
    if (subject.source_document_key
            != occurrence.definition.document.value
            or subject.link_instance_chain
            != occurrence.link_instance_chain):
        return (
            FederationGeometryGapReason.TRANSFORM_SUBJECT_MISMATCH,
            "transform subject document/link chain differs from occurrence")
    if transform.target_frame is FederationTransformTarget.FEDERATION_ROOT:
        if (subject.target_document_key != occurrence.federation_root
                or subject.target_link_instance_chain):
            return (
                FederationGeometryGapReason.TRANSFORM_TARGET_MISMATCH,
                "federation-root transform does not target this root")
        return None
    # A direct link's parent source is the federation root.  This is the only
    # parent-frame evidence that is already a source-to-root transform.
    if transform.target_frame is FederationTransformTarget.PARENT_SOURCE:
        if (len(occurrence.link_instance_chain) != 1
                or subject.target_link_instance_chain
                or subject.target_document_key != occurrence.federation_root):
            return (
                FederationGeometryGapReason.TRANSFORM_TARGET_MISMATCH,
                "parent-source transform is root-normalized only for a direct link")
        return None
    return (
        FederationGeometryGapReason.TRANSFORM_TARGET_MISMATCH,
        "unknown transform target frame")


def _gap(
    source: HullFederationSource,
    record: H.HullRecord,
    reason: FederationGeometryGapReason,
    detail: str,
    occurrence: OccurrenceIdentity | None = None,
) -> FederationGeometryGap:
    sections_apply = H.category_allows_sections(record.category)
    return FederationGeometryGap(
        source=source.source,
        local_source_id=record.source_id,
        category=record.category,
        mvp_side=record.mvp_side,
        type_name=record.type_name,
        section_present=(
            bool(G._finite(record.section_radius_mm)
                 and record.section_radius_mm > 0.0)
            if sections_apply else None),
        occurrence_key=(occurrence.key if occurrence is not None else None),
        reason=reason,
        detail=detail,
    )


def federate_hulls(
    sources: Iterable[HullFederationSource],
    *,
    federation_root: str,
) -> FederatedHullSet:
    """Transform root/direct-link records before any cross-document query.

    Every input record becomes exactly one transformed record or exactly one
    typed geometry gap.  ``OccurrenceIdentity.key`` is the sole output key;
    local ElementId survives only as audit metadata.
    """

    if not isinstance(federation_root, str) or not federation_root:
        raise ValueError("federation_root must be non-empty")
    source_rows = tuple(sources)
    if any(not isinstance(source, HullFederationSource)
           for source in source_rows):
        raise ValueError("sources must contain HullFederationSource values")
    entries = tuple(
        (source, record,
         source.occurrence_by_local_id.get(record.source_id))
        for source in source_rows for record in source.records)
    occurrence_counts: dict[str, int] = {}
    for _, _, occurrence in entries:
        if occurrence is not None:
            occurrence_counts[occurrence.key] = (
                occurrence_counts.get(occurrence.key, 0) + 1)

    transformed: list[H.HullRecord] = []
    gaps: list[FederationGeometryGap] = []
    for source, record, occurrence in entries:
        if occurrence is None:
            gaps.append(_gap(
                source, record,
                FederationGeometryGapReason.MISSING_OCCURRENCE_IDENTITY,
                "no occurrence identity for this local ElementId"))
            continue
        if occurrence.federation_root != federation_root:
            gaps.append(_gap(
                source, record,
                FederationGeometryGapReason.FEDERATION_ROOT_MISMATCH,
                "occurrence belongs to another federation root", occurrence))
            continue
        if len(occurrence.link_instance_chain) > 1:
            gaps.append(_gap(
                source, record,
                FederationGeometryGapReason.NESTED_LINK_CHAIN_NOT_EXTRACTED,
                "production extractor supports root and direct links only",
                occurrence))
            continue
        if occurrence_counts.get(occurrence.key, 0) != 1:
            gaps.append(_gap(
                source, record,
                FederationGeometryGapReason.DUPLICATE_OCCURRENCE_KEY,
                "the same authoritative occurrence was supplied more than once",
                occurrence))
            continue
        transform, transform_error = _coerce_transform(source.source_to_root)
        if transform is None:
            reason = (
                FederationGeometryGapReason.MISSING_TRANSFORM
                if source.source_to_root is None
                else FederationGeometryGapReason.INVALID_TRANSFORM)
            gaps.append(_gap(
                source, record, reason, transform_error or "invalid transform",
                occurrence))
            continue
        assert transform.matrix is not None
        if source.link_authority_binding is not None:
            try:
                source.link_authority_binding.assert_transform_subject(
                    transform.subject_context.to_dict())
            except FederationAssemblyError as exc:
                gaps.append(_gap(
                    source, record,
                    FederationGeometryGapReason.TRANSFORM_SUBJECT_MISMATCH,
                    str(exc), occurrence))
                continue
        binding_error = _transform_binding_error(transform, occurrence)
        if binding_error is not None:
            reason, detail = binding_error
            gaps.append(_gap(
                source, record, reason, detail, occurrence))
            continue
        if (not occurrence.link_instance_chain
                and not _is_identity(transform.matrix)):
            gaps.append(_gap(
                source, record,
                FederationGeometryGapReason.ROOT_TRANSFORM_NOT_IDENTITY,
                "root-document coordinates must already be the root frame",
                occurrence))
            continue
        try:
            hull, exact = transform_hull(record.hull, transform)
        except (TypeError, ValueError) as exc:
            gaps.append(_gap(
                source, record,
                FederationGeometryGapReason.UNTRANSFORMABLE_HULL,
                str(exc), occurrence))
            continue
        try:
            canonical_extra = _json_value(record.extra)
            if not isinstance(canonical_extra, dict):
                raise ValueError("HullRecord.extra must be a JSON object")
            # These fields enter the signed content surface after geometry has
            # been classified.  Validate them per record so one NaN/custom
            # object becomes one balanced gap instead of aborting the entire
            # federation while its census already says "transformed".
            _json_value({
                "category": record.category,
                "label": record.label,
                "mvp_side": record.mvp_side,
                "grade": record.grade,
                "hull_source": record.hull_source,
                "level_id": record.level_id,
                "type_name": record.type_name,
                "section_radius_mm": record.section_radius_mm,
                "section_round": record.section_round,
                "section_source": record.section_source,
            })
        except (TypeError, ValueError) as exc:
            gaps.append(_gap(
                source, record,
                FederationGeometryGapReason.INVALID_RECORD_METADATA,
                str(exc), occurrence))
            continue
        proof_gaps: list[str] = []
        if record.inner is not None:
            proof_gaps.append(FEDERATION_PROOF_GAP)
        if record.level_id is not None:
            proof_gaps.append(FEDERATION_LEVEL_GAP)
        conservative_aabb = not exact and isinstance(hull, G.Aabb)
        federation_meta = {
            "schema_version": FEDERATED_HULLS_SCHEMA,
            "federation_root": federation_root,
            "occurrence_identity": occurrence.as_dict(),
            "occurrence_key": occurrence.key,
            "local_source_id": record.source_id,
            "source": source.source,
            "transform_digest": transform.content_digest,
            "transform_convention": transform.convention,
            "representation": (
                "exact" if exact else (
                    "conservative_aabb" if conservative_aabb
                    else "conservative_hull")),
            # level_id is an ElementId in the source document.  Carrying it as
            # a root-level id lets resolve._level_band join a same-numbered
            # but unrelated root level.  Retain it only as qualified audit
            # provenance until level planes themselves are federated.
            "local_level_id": record.level_id,
            "proof_gaps": proof_gaps,
        }
        extra = dict(canonical_extra)
        extra["federation"] = federation_meta
        transformed.append(_FederatedHullRecord(
            source_id=occurrence.key,
            category=record.category,
            label=record.label,
            mvp_side=record.mvp_side,
            hull=hull,
            grade=record.grade if exact else "coarse",
            hull_source=(record.hull_source if exact
                         else ("federated_conservative_aabb"
                               if conservative_aabb
                               else "federated_conservative_hull")),
            level_id=None,
            type_name=record.type_name,
            section_radius_mm=record.section_radius_mm,
            section_round=record.section_round,
            section_source=record.section_source,
            extra=extra,
            # Certificates bind the old subject id and old-frame hull digest.
            # Reusing one would manufacture proof authority by coordinate math.
            inner=None,
        ))

    transformed.sort(key=lambda record: record.source_id)
    gaps.sort(key=lambda gap: (
        gap.source, gap.local_source_id, gap.reason.value,
        gap.occurrence_key or "", gap.detail))
    census = FederationCensus(
        input=len(entries), transformed=len(transformed), gaps=len(gaps))
    payload = {
        "schema_version": FEDERATED_HULLS_SCHEMA,
        "federation_root": federation_root,
        "records": [_record_dict(record) for record in transformed],
        "gaps": [gap.as_dict() for gap in gaps],
        "census": census.as_dict(),
    }
    return FederatedHullSet(
        federation_root=federation_root,
        records=tuple(transformed),
        gaps=tuple(gaps),
        census=census,
        content_digest=_digest_payload(payload),
    )


__all__ = [
    "FEDERATED_HULLS_SCHEMA",
    "FEDERATION_LEVEL_GAP",
    "FEDERATION_PROOF_GAP",
    "FederatedHullSet",
    "FederationCensus",
    "FederationGeometryGap",
    "FederationGeometryGapReason",
    "HullFederationSource",
    "federate_hulls",
    "transform_hull",
]
