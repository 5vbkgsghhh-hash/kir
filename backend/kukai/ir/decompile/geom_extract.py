"""Full-geometry EXTRACT boundary for frozen Wave-G geometry.

This module is deliberately separate from :mod:`geometry_store`, which owns
only the frozen Wave-A location/bounding-box fragment.  Geometry returned by
the Revit read-side emitter is parsed through the strict ``GbSolid`` and
``GmMesh`` ``from_dict`` methods in :mod:`recompile` before it can enter the
content-addressed store.

The persisted shape is glTF-like:

* ``GeometryStore`` owns each immutable geometry definition once;
* ``GeometryIndexRecord`` associates one source element with a ``geo_hash``
  and a separate affine transform;
* ``GeometryExtraction.nodes`` groups equal definitions/category pairs into
  frozen ``GeometryNode`` values that can be passed directly to
  ``recompile(...)``.

No function in this module calls Revit.  The C# emitter is a read-only Execute
body; the Python half validates and deduplicates its bridge payload offline.
"""
from __future__ import annotations

import hashlib
import json
from kukai.ir.emit_utils import cs_string_literal
import math
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from .recompile import (
    GbSolid,
    GeometryDefinition,
    GeometryNode,
    GeometrySchemaError,
    GeometryTier,
    GmMesh,
    Matrix4,
    validate_transform,
)
from .schema import EXTRACT_BATCH, GEOM_CANON_MM, GEOM_DETAIL
from .side_contract import source_binding_cs


GEOMETRY_EXTRACT_SCHEMA_VERSION = "kir-decompile-geometry/1"
GEOMETRY_ARTIFACT_PROOF_VERSION = "kir-geometry-artifact-proof/1"
GEOMETRY_ATOM_CONTRACT_VERSION = "kir-geometry-atom-contract/1"
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")


class GeometryExtractionError(ValueError):
    """Base class for a fail-closed full-geometry extraction refusal."""


class GeometryPayloadError(GeometryExtractionError):
    """A bridge payload does not satisfy the geometry extraction protocol."""


class GeometryStoreError(GeometryExtractionError):
    """A content-addressed geometry-store invariant was violated."""


def geometry_atom_contract_digest(
    leaves: Sequence[Mapping[str, Any]],
) -> tuple[str, int]:
    """Digest the exact non-generated atom leaves eligible for Tier G.

    The geometry bundle stores source ids and shapes, but not the L1 leaf that
    made each source an atom.  This digest binds the persisted bundle proof to
    that exact semantic fallback contract, so a valid bundle copied from a
    different decompile cannot be accepted merely because ids/categories happen
    to overlap.
    """

    atoms: list[dict[str, Any]] = []
    source_ids: list[str] = []
    for leaf in leaves:
        if not isinstance(leaf, Mapping) or leaf.get("kind") != "atom":
            continue
        reason = leaf.get("reason")
        if isinstance(reason, Mapping) and reason.get("code") == "generator_child":
            continue
        source_id = leaf.get("source_element_id")
        if not isinstance(source_id, str) or not source_id:
            raise GeometryPayloadError(
                "geometry atom contract has no source_element_id")
        source_ids.append(source_id)
        atoms.append(dict(leaf))
    if len(set(source_ids)) != len(source_ids):
        raise GeometryPayloadError(
            "geometry atom contract repeats source_element_id")
    atoms.sort(key=lambda leaf: (
        int(leaf["source_element_id"])
        if leaf["source_element_id"].isdigit() else 0,
        leaf["source_element_id"],
    ))
    try:
        raw = json.dumps({
            "schema_version": GEOMETRY_ATOM_CONTRACT_VERSION,
            "atoms": atoms,
        }, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GeometryPayloadError(
            f"geometry atom contract is not canonical JSON: {exc}") from exc
    return hashlib.sha256(raw).hexdigest(), len(atoms)


@dataclass(frozen=True, slots=True)
class GeometryArtifactProof:
    """Content/revision identity for one persisted Tier-G source bundle."""

    change_stamp: str
    revision_fingerprint: str
    geometry_bundle_sha256: str
    atom_contract_digest: str
    atom_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.change_stamp, str) or not self.change_stamp:
            raise GeometryPayloadError(
                "geometry artifact proof change_stamp must be non-empty")
        if (not isinstance(self.revision_fingerprint, str)
                or not self.revision_fingerprint):
            raise GeometryPayloadError(
                "geometry artifact proof revision must be non-empty")
        for field_name, value in (
            ("geometry_bundle_sha256", self.geometry_bundle_sha256),
            ("atom_contract_digest", self.atom_contract_digest),
        ):
            if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
                raise GeometryPayloadError(
                    f"geometry artifact proof {field_name} must be SHA-256")
        if (isinstance(self.atom_count, bool)
                or not isinstance(self.atom_count, int)
                or self.atom_count < 0):
            raise GeometryPayloadError(
                "geometry artifact proof atom_count must be non-negative")

    @classmethod
    def bind(
        cls,
        *,
        change_stamp: str,
        revision_fingerprint: str,
        geometry_bundle: bytes,
        leaves: Sequence[Mapping[str, Any]],
    ) -> "GeometryArtifactProof":
        if not isinstance(geometry_bundle, bytes):
            raise GeometryPayloadError(
                "geometry artifact proof requires exact bundle bytes")
        contract_digest, atom_count = geometry_atom_contract_digest(leaves)
        return cls(
            change_stamp=change_stamp,
            revision_fingerprint=revision_fingerprint,
            geometry_bundle_sha256=hashlib.sha256(geometry_bundle).hexdigest(),
            atom_contract_digest=contract_digest,
            atom_count=atom_count,
        )

    @classmethod
    def from_dict(cls, value: Any) -> "GeometryArtifactProof":
        row = _exact_fields(value, {
            "schema_version",
            "change_stamp",
            "revision_fingerprint",
            "geometry_bundle_sha256",
            "atom_contract_digest",
            "atom_count",
        }, "geometry artifact proof")
        if row["schema_version"] != GEOMETRY_ARTIFACT_PROOF_VERSION:
            raise GeometryPayloadError(
                "geometry artifact proof schema_version mismatch")
        return cls(
            change_stamp=_require_string(
                row["change_stamp"], "geometry proof.change_stamp"),
            revision_fingerprint=_require_string(
                row["revision_fingerprint"],
                "geometry proof.revision_fingerprint"),
            geometry_bundle_sha256=_require_string(
                row["geometry_bundle_sha256"],
                "geometry proof.geometry_bundle_sha256"),
            atom_contract_digest=_require_string(
                row["atom_contract_digest"],
                "geometry proof.atom_contract_digest"),
            atom_count=row["atom_count"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GEOMETRY_ARTIFACT_PROOF_VERSION,
            "change_stamp": self.change_stamp,
            "revision_fingerprint": self.revision_fingerprint,
            "geometry_bundle_sha256": self.geometry_bundle_sha256,
            "atom_contract_digest": self.atom_contract_digest,
            "atom_count": self.atom_count,
        }

    def verify(
        self,
        *,
        change_stamp: str,
        revision_fingerprint: str,
        geometry_bundle: bytes,
        leaves: Sequence[Mapping[str, Any]],
    ) -> None:
        expected = GeometryArtifactProof.bind(
            change_stamp=change_stamp,
            revision_fingerprint=revision_fingerprint,
            geometry_bundle=geometry_bundle,
            leaves=leaves,
        )
        if self != expected:
            raise GeometryPayloadError(
                "geometry artifact proof does not match bundle/revision/atoms")


class ExtractedGeometryTier(str, Enum):
    """The side-index fidelity ladder (Tier S is owned by LIFT)."""

    GB = "Gb"
    GM = "Gm"
    A = "A"


class GeometryDetailLevel(str, Enum):
    """Closed Revit geometry-detail levels accepted by the Gx emitter."""

    FINE = "fine"
    MEDIUM = "medium"
    COARSE = "coarse"


class GeometryFailureReason(str, Enum):
    """Typed fail-safe reasons emitted in addition to legacy error strings."""

    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"
    CALL_BUDGET_EXHAUSTED = "call_budget_exhausted"


@dataclass(frozen=True, slots=True)
class GeometryIndexRecord:
    """One frozen-L0 side-index row.

    ``to_dict`` intentionally emits exactly the §0.6.8 side contract.  Source
    element/category identity stays in the containing index rather than being
    smuggled into Wave G's frozen geometry definition.
    """

    element_id: str
    category: str
    tier: ExtractedGeometryTier
    geo_hash: str | None
    transform: Matrix4 | None
    detail_level: GeometryDetailLevel | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.element_id, str) or not self.element_id:
            raise GeometryPayloadError(
                "GeometryIndexRecord.element_id must be non-empty")
        if not isinstance(self.category, str):
            raise GeometryPayloadError(
                "GeometryIndexRecord.category must be a string")
        if not isinstance(self.tier, ExtractedGeometryTier):
            raise GeometryPayloadError(
                "GeometryIndexRecord.tier must be an ExtractedGeometryTier")
        if self.detail_level is not None and not isinstance(
                self.detail_level, GeometryDetailLevel):
            raise GeometryPayloadError(
                "GeometryIndexRecord.detail_level must be a "
                "GeometryDetailLevel")
        if self.tier is ExtractedGeometryTier.A:
            if self.geo_hash is not None or self.transform is not None:
                raise GeometryPayloadError(
                    "Tier A cannot carry geo_hash or transform")
        else:
            if not isinstance(self.geo_hash, str) \
                    or _HASH_RE.fullmatch(self.geo_hash) is None:
                raise GeometryPayloadError(
                    "Tier G geometry requires a SHA-256 geo_hash")
            if self.transform is None:
                raise GeometryPayloadError(
                    "Tier G geometry requires a transform")
            validate_transform(
                self.transform, "GeometryIndexRecord.transform")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "geo_hash": self.geo_hash,
            "transform": (
                list(self.transform) if self.transform is not None else None),
        }


@dataclass(frozen=True, slots=True)
class GeometryDegradation:
    """An exact Gb attempt that honestly landed on its Gm floor."""

    element_id: str
    part_index: int | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "part_index": self.part_index,
            "from_tier": "Gb",
            "to_tier": "Gm",
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GeometryFailure:
    """One element was not misreported as Tier A after an extraction error."""

    element_id: str
    category: str
    errors: tuple[str, ...]
    reason: GeometryFailureReason | None = None
    elapsed_ms: int | None = None
    detail_level: GeometryDetailLevel | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.element_id, str) or not self.element_id:
            raise GeometryPayloadError(
                "GeometryFailure.element_id must be non-empty")
        if not isinstance(self.category, str):
            raise GeometryPayloadError(
                "GeometryFailure.category must be a string")
        if not self.errors or not all(
                isinstance(error, str) and error for error in self.errors):
            raise GeometryPayloadError(
                "GeometryFailure.errors must contain non-empty strings")
        if self.reason is None:
            if self.elapsed_ms is not None:
                raise GeometryPayloadError(
                    "GeometryFailure.elapsed_ms requires a typed reason")
        else:
            if not isinstance(self.reason, GeometryFailureReason):
                raise GeometryPayloadError(
                    "GeometryFailure.reason must be a GeometryFailureReason")
            _require_nonnegative_int(
                self.elapsed_ms, "GeometryFailure.elapsed_ms")
            if self.reason.value not in self.errors:
                raise GeometryPayloadError(
                    "GeometryFailure.reason must match an error string")
        if self.detail_level is not None and not isinstance(
                self.detail_level, GeometryDetailLevel):
            raise GeometryPayloadError(
                "GeometryFailure.detail_level must be a GeometryDetailLevel")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "element_id": self.element_id,
            "category": self.category,
            "errors": list(self.errors),
        }
        if self.reason is not None:
            result["reason"] = self.reason.value
            result["elapsed_ms"] = self.elapsed_ms
        if self.detail_level is not None:
            result["detail_level"] = self.detail_level.value
        return result


@dataclass(frozen=True, slots=True)
class GeometryDetailRecord:
    """One explicit non-default detail declaration from a bridge row."""

    element_id: str
    detail_level: GeometryDetailLevel

    def __post_init__(self) -> None:
        if not isinstance(self.element_id, str) or not self.element_id:
            raise GeometryPayloadError(
                "GeometryDetailRecord.element_id must be non-empty")
        if not isinstance(self.detail_level, GeometryDetailLevel):
            raise GeometryPayloadError(
                "GeometryDetailRecord.detail_level must be a "
                "GeometryDetailLevel")

    def to_dict(self) -> dict[str, str]:
        return {
            "element_id": self.element_id,
            "detail_level": self.detail_level.value,
        }


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GeometryPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise GeometryPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _exact_fields(
    value: Any,
    fields: set[str],
    field_name: str,
) -> dict[str, Any]:
    row = _require_mapping(value, field_name)
    missing = sorted(fields - set(row))
    extra = sorted(set(row) - fields)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise GeometryPayloadError(
            f"{field_name} fields: {'; '.join(details)}")
    return row


def _additive_fields(
    value: Any,
    required: set[str],
    optional: set[str],
    field_name: str,
) -> dict[str, Any]:
    """Require the legacy row while admitting only named additive fields."""

    row = _require_mapping(value, field_name)
    missing = sorted(required - set(row))
    extra = sorted(set(row) - required - optional)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise GeometryPayloadError(
            f"{field_name} fields: {'; '.join(details)}")
    return row


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise GeometryPayloadError(f"{field_name} must be an array")
    return value


def _require_string(value: Any, field_name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        qualifier = "a string" if empty else "a non-empty string"
        raise GeometryPayloadError(f"{field_name} must be {qualifier}")
    return value


def _require_nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GeometryPayloadError(
            f"{field_name} must be a non-negative integer")
    return value


def _validated_geometry(
    value: GeometryDefinition | Mapping[str, Any],
    field_name: str = "geometry",
) -> GeometryDefinition:
    if isinstance(value, (GbSolid, GmMesh)):
        row = value.to_dict()
    else:
        row = _require_mapping(value, field_name)
    tier = row.get("tier")
    if tier == GeometryTier.GB.value:
        return GbSolid.from_dict(row, field_name)
    if tier == GeometryTier.GM.value:
        return GmMesh.from_dict(row, field_name)
    raise GeometryPayloadError(
        f"{field_name}.tier is unsupported: {tier!r}")


def _round_mm(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeometryStoreError("millimetre geometry value must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise GeometryStoreError("millimetre geometry value must be finite")
    scaled = number / GEOM_CANON_MM
    units = (
        math.floor(scaled + 0.5)
        if scaled >= 0.0 else math.ceil(scaled - 0.5))
    rounded = units * GEOM_CANON_MM
    return 0.0 if rounded == 0.0 else rounded


def canonical_mm(value: float) -> float:
    """Public authority for the frozen Tier-G millimetre grid.

    Independent form acceptance must quantize a post-commit re-read exactly as
    the content-addressed geometry store did.  Keeping that rule here avoids a
    second almost-identical rounding implementation at the acceptance layer.
    """

    return _round_mm(value)


def _canonical_value(value: Any, *, millimetres: bool = False) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _canonical_value(
                item,
                millimetres=key.endswith("_mm"),
            )
            for key, item in sorted(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [
            _canonical_value(item, millimetres=millimetres)
            for item in value
        ]
    if millimetres and isinstance(value, (int, float)) \
            and not isinstance(value, bool):
        return _round_mm(float(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GeometryStoreError("geometry contains a non-finite number")
        return 0.0 if value == 0.0 else value
    return value


def canonical_geometry_bytes(
    geometry: GeometryDefinition | Mapping[str, Any],
) -> bytes:
    """Return deterministic geometry-only bytes at ``GEOM_CANON_MM``.

    Category, source element id, and instance transforms are intentionally not
    accepted here, so translated/rotated symbol instances share a definition.
    """

    validated = _validated_geometry(geometry)
    canonical = _canonical_value(validated.to_dict())
    try:
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise GeometryStoreError(
            f"geometry is not canonical JSON data: {exc}") from exc
    return encoded.encode("utf-8")


def geometry_hash(
    geometry: GeometryDefinition | Mapping[str, Any],
) -> str:
    """Hash one validated definition, excluding placement and category."""

    return hashlib.sha256(canonical_geometry_bytes(geometry)).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredGeometry:
    geo_hash: str
    geometry: GeometryDefinition

    def to_dict(self) -> dict[str, Any]:
        return {
            "geo_hash": self.geo_hash,
            "geometry": self.geometry.to_dict(),
        }


class GeometryStore:
    """In-memory content-addressed Tier-G store with collision defense."""

    def __init__(self) -> None:
        self._definitions: dict[str, StoredGeometry] = {}
        self._canonical: dict[str, bytes] = {}

    def add(
        self,
        geometry: GeometryDefinition | Mapping[str, Any],
    ) -> str:
        validated = _validated_geometry(geometry)
        canonical = canonical_geometry_bytes(validated)
        geo_hash = hashlib.sha256(canonical).hexdigest()
        existing = self._canonical.get(geo_hash)
        if existing is not None and existing != canonical:
            raise GeometryStoreError(
                f"SHA-256 collision for geometry {geo_hash}")
        if existing is None:
            self._canonical[geo_hash] = canonical
            self._definitions[geo_hash] = StoredGeometry(
                geo_hash, validated)
        return geo_hash

    def get(self, geo_hash: str) -> GeometryDefinition:
        try:
            return self._definitions[geo_hash].geometry
        except KeyError as exc:
            raise GeometryStoreError(
                f"unknown geometry hash: {geo_hash!r}") from exc

    def __contains__(self, geo_hash: object) -> bool:
        return geo_hash in self._definitions

    def __len__(self) -> int:
        return len(self._definitions)

    def __iter__(self) -> Iterator[StoredGeometry]:
        for geo_hash in sorted(self._definitions):
            yield self._definitions[geo_hash]

    def to_dict(self) -> dict[str, Any]:
        return {
            stored.geo_hash: stored.geometry.to_dict()
            for stored in self
        }


@dataclass(frozen=True, slots=True)
class _GeometryPart:
    geometry: GeometryDefinition
    transform: Matrix4


def _matrix_multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    values = []
    for row in range(4):
        for column in range(4):
            values.append(sum(
                left[row * 4 + pivot] * right[pivot * 4 + column]
                for pivot in range(4)))
    return validate_transform(tuple(values), "matrix product")


def _inverse_transform(value: Matrix4) -> Matrix4:
    matrix = validate_transform(value)
    a, b, c = matrix[0], matrix[1], matrix[2]
    d, e, f = matrix[4], matrix[5], matrix[6]
    g, h, i = matrix[8], matrix[9], matrix[10]
    determinant = (
        a * (e * i - f * h)
        - b * (d * i - f * g)
        + c * (d * h - e * g)
    )
    inverse_basis = (
        (e * i - f * h) / determinant,
        (c * h - b * i) / determinant,
        (b * f - c * e) / determinant,
        (f * g - d * i) / determinant,
        (a * i - c * g) / determinant,
        (c * d - a * f) / determinant,
        (d * h - e * g) / determinant,
        (b * g - a * h) / determinant,
        (a * e - b * d) / determinant,
    )
    tx, ty, tz = matrix[3], matrix[7], matrix[11]
    itx = -(
        inverse_basis[0] * tx
        + inverse_basis[1] * ty
        + inverse_basis[2] * tz)
    ity = -(
        inverse_basis[3] * tx
        + inverse_basis[4] * ty
        + inverse_basis[5] * tz)
    itz = -(
        inverse_basis[6] * tx
        + inverse_basis[7] * ty
        + inverse_basis[8] * tz)
    return validate_transform((
        inverse_basis[0], inverse_basis[1], inverse_basis[2], itx,
        inverse_basis[3], inverse_basis[4], inverse_basis[5], ity,
        inverse_basis[6], inverse_basis[7], inverse_basis[8], itz,
        0.0, 0.0, 0.0, 1.0,
    ), "inverse transform")


def _transform_point(
    transform: Matrix4,
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    x, y, z = point
    return (
        transform[0] * x + transform[1] * y
        + transform[2] * z + transform[3],
        transform[4] * x + transform[5] * y
        + transform[6] * z + transform[7],
        transform[8] * x + transform[9] * y
        + transform[10] * z + transform[11],
    )


def _fallback_mesh(geometry: GeometryDefinition) -> GmMesh:
    return (
        geometry.fallback_mesh
        if isinstance(geometry, GbSolid) else geometry)


def _combine_parts(parts: Sequence[_GeometryPart]) -> tuple[GmMesh, Matrix4]:
    """Bake relative part transforms into one exact frozen Gm definition.

    ``GbSolid`` represents one closed solid.  An element with multiple Revit
    geometry objects therefore cannot be packed into that frozen type without
    inventing a multi-solid schema.  Its mandatory tessellations are combined
    under the first occurrence transform instead.
    """

    if len(parts) < 2:
        raise GeometryPayloadError("combining geometry requires two parts")
    base = parts[0].transform
    inverse_base = _inverse_transform(base)
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for part in parts:
        relative = _matrix_multiply(inverse_base, part.transform)
        mesh = _fallback_mesh(part.geometry)
        offset = len(vertices)
        vertices.extend(
            _transform_point(relative, vertex)
            for vertex in mesh.vertices_mm)
        triangles.extend(tuple(offset + index for index in triangle)
                         for triangle in mesh.triangles)
    return GmMesh(tuple(vertices), tuple(triangles)), base


def _transform_from_json(value: Any, field_name: str) -> Matrix4:
    values = _require_list(value, field_name)
    if len(values) != 16:
        raise GeometryPayloadError(
            f"{field_name} must contain exactly 16 numbers")
    parsed = []
    for index, item in enumerate(values):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise GeometryPayloadError(
                f"{field_name}[{index}] must be a finite number")
        parsed.append(float(item))
    try:
        return validate_transform(tuple(parsed), field_name)
    except GeometrySchemaError as exc:
        raise GeometryPayloadError(str(exc)) from exc


def _parse_part(
    value: Any,
    *,
    field_name: str,
    element_id: str,
    part_index: int,
) -> tuple[_GeometryPart, GeometryDegradation | None]:
    row = _exact_fields(
        value, {"geometry", "transform", "gb_error"}, field_name)
    geometry_row = _require_mapping(
        row["geometry"], f"{field_name}.geometry")
    transform = _transform_from_json(
        row["transform"], f"{field_name}.transform")
    raw_gb_error = row["gb_error"]
    if raw_gb_error is not None:
        raw_gb_error = _require_string(
            raw_gb_error, f"{field_name}.gb_error")[:300]
    tier = geometry_row.get("tier")
    if tier == GeometryTier.GM.value:
        try:
            geometry = GmMesh.from_dict(
                geometry_row, f"{field_name}.geometry")
        except GeometrySchemaError as exc:
            raise GeometryPayloadError(str(exc)) from exc
        degradation = (
            GeometryDegradation(element_id, part_index, raw_gb_error)
            if raw_gb_error is not None else None)
        return _GeometryPart(geometry, transform), degradation
    if tier != GeometryTier.GB.value:
        raise GeometryPayloadError(
            f"{field_name}.geometry.tier is unsupported: {tier!r}")
    if raw_gb_error is not None:
        raise GeometryPayloadError(
            f"{field_name}.gb_error is incompatible with a Gb geometry row")
    try:
        solid = GbSolid.from_dict(
            geometry_row, f"{field_name}.geometry")
        return _GeometryPart(solid, transform), None
    except GeometrySchemaError as gb_error:
        fallback = geometry_row.get("fallback_mesh")
        try:
            mesh = GmMesh.from_dict(
                fallback, f"{field_name}.geometry.fallback_mesh")
        except GeometrySchemaError as gm_error:
            raise GeometryPayloadError(
                f"{field_name} invalid Gb candidate ({gb_error}) and "
                f"invalid Gm fallback ({gm_error})") from gm_error
        degradation = GeometryDegradation(
            element_id=element_id,
            part_index=part_index,
            reason=f"frozen Gb validation refused candidate: {gb_error}",
        )
        return _GeometryPart(mesh, transform), degradation


def _unwrap_payload(value: Any) -> Any:
    current = value
    for _ in range(2):
        if not isinstance(current, Mapping) or "ok" not in current:
            break
        if current.get("ok") is not True:
            detail = current.get("error") or current.get("message") \
                or "bridge refused geometry extraction"
            raise GeometryPayloadError(str(detail)[:300])
        if "result" not in current:
            break
        current = current["result"]
    return current


def _node_id(category: str, geo_hash: str) -> str:
    digest = hashlib.sha256(
        (category + "\0" + geo_hash).encode("utf-8")).hexdigest()
    return "gx-" + digest


def _nodes_for_index(
    store: GeometryStore,
    index: Sequence[GeometryIndexRecord],
) -> tuple[GeometryNode, ...]:
    """Compose the canonical node grouping for validated index rows."""

    occurrences: dict[tuple[str, str], list[Matrix4]] = {}
    for record in index:
        if record.tier is ExtractedGeometryTier.A:
            continue
        assert record.geo_hash is not None
        assert record.transform is not None
        occurrences.setdefault(
            (record.geo_hash, record.category), []).append(record.transform)

    nodes: list[GeometryNode] = []
    for (geo_hash, category), transforms in sorted(occurrences.items()):
        try:
            nodes.append(GeometryNode(
                node_id=_node_id(category, geo_hash),
                category=category,
                geometry=store.get(geo_hash),
                transforms=tuple(sorted(transforms)),
            ))
        except (GeometrySchemaError, GeometryStoreError) as exc:
            raise GeometryPayloadError(
                f"cannot compose frozen GeometryNode for {geo_hash}: {exc}"
            ) from exc
    return tuple(nodes)


_PSEUDO_L0_CATEGORIES = frozenset({"DirectShape", "ImportInstance"})


def _resolve_index_categories(
    rows: Sequence[
        tuple[str, ExtractedGeometryTier, str | None, Matrix4 | None,
              GeometryDetailLevel | None]
    ],
    nodes: Sequence[GeometryNode],
    categories_by_id: Mapping[str, str] | None,
) -> tuple[GeometryIndexRecord, ...]:
    """Recover the deliberately non-persisted category for every index row.

    The frozen geometry-index row contains only ``tier/hash/transform``.
    Category identity is carried by ``nodes``.  Most L0 categories can be
    matched directly; class-only L0 pseudo categories (``DirectShape`` and
    ``ImportInstance``) are resolved only when exactly one node category can
    account for the same definition occurrence.  Ambiguity is a refusal, not
    a guessed category.
    """

    available: dict[tuple[str, Matrix4], Counter[str]] = {}
    for node in nodes:
        geo_hash = geometry_hash(node.geometry)
        for transform in node.transforms:
            available.setdefault(
                (geo_hash, transform), Counter())[node.category] += 1

    result: list[GeometryIndexRecord] = []
    for element_id, tier, geo_hash, transform, detail_level in rows:
        preferred = (
            categories_by_id.get(element_id)
            if categories_by_id is not None else None)
        if preferred is not None and not isinstance(preferred, str):
            raise GeometryPayloadError(
                f"category for element {element_id!r} must be a string")
        if tier is ExtractedGeometryTier.A:
            result.append(GeometryIndexRecord(
                element_id=element_id,
                category=preferred or "",
                tier=tier,
                geo_hash=None,
                transform=None,
                detail_level=detail_level,
            ))
            continue

        assert geo_hash is not None
        assert transform is not None
        bucket = available.get((geo_hash, transform), Counter())
        candidates = sorted(
            category for category, count in bucket.items() if count > 0)
        if preferred in candidates:
            category = preferred
        elif (preferred is None or preferred in _PSEUDO_L0_CATEGORIES) \
                and len(candidates) == 1:
            category = candidates[0]
        elif preferred is None:
            raise GeometryPayloadError(
                "geometry index category is ambiguous for element "
                f"{element_id!r}: {candidates!r}")
        else:
            raise GeometryPayloadError(
                "geometry node category disagrees with L0 for element "
                f"{element_id!r}: l0={preferred!r}, nodes={candidates!r}")
        bucket[category] -= 1
        result.append(GeometryIndexRecord(
            element_id=element_id,
            category=category,
            tier=tier,
            geo_hash=geo_hash,
            transform=transform,
            detail_level=detail_level,
        ))

    leftovers = sum(
        count for bucket in available.values() for count in bucket.values())
    if leftovers:
        raise GeometryPayloadError(
            f"geometry nodes contain {leftovers} unindexed occurrence(s)")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class GeometryExtraction:
    """Validated EXTRACT result; iterable directly by ``recompile``."""

    store: GeometryStore
    index: tuple[GeometryIndexRecord, ...]
    nodes: tuple[GeometryNode, ...]
    degradations: tuple[GeometryDegradation, ...] = ()
    failures: tuple[GeometryFailure, ...] = ()
    detail_levels: tuple[GeometryDetailRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.store, GeometryStore):
            raise GeometryPayloadError(
                "GeometryExtraction.store must be a GeometryStore")
        fields = (
            (self.index, GeometryIndexRecord, "index"),
            (self.nodes, GeometryNode, "nodes"),
            (self.degradations, GeometryDegradation, "degradations"),
            (self.failures, GeometryFailure, "failures"),
            (self.detail_levels, GeometryDetailRecord, "detail_levels"),
        )
        for values, expected_type, name in fields:
            if not isinstance(values, tuple) or any(
                    not isinstance(value, expected_type) for value in values):
                raise GeometryPayloadError(
                    f"GeometryExtraction.{name} has invalid values")

        indexed_ids = [record.element_id for record in self.index]
        failed_ids = [failure.element_id for failure in self.failures]
        if len(set(indexed_ids)) != len(indexed_ids):
            raise GeometryPayloadError(
                "GeometryExtraction.index repeats element_id")
        if len(set(failed_ids)) != len(failed_ids):
            raise GeometryPayloadError(
                "GeometryExtraction.failures repeats element_id")
        overlap = set(indexed_ids) & set(failed_ids)
        if overlap:
            raise GeometryPayloadError(
                "geometry elements cannot be both indexed and failed: "
                + ", ".join(sorted(overlap)[:5]))

        node_ids: set[str] = set()
        actual: Counter[tuple[str, str, Matrix4]] = Counter()
        for node in self.nodes:
            if node.node_id in node_ids:
                raise GeometryPayloadError(
                    f"geometry nodes repeat node_id {node.node_id!r}")
            node_ids.add(node.node_id)
            node_hash = geometry_hash(node.geometry)
            if node_hash not in self.store:
                raise GeometryPayloadError(
                    f"geometry node {node.node_id!r} is absent from store")
            if self.store.get(node_hash).to_dict() != node.geometry.to_dict():
                raise GeometryPayloadError(
                    f"geometry node {node.node_id!r} disagrees with store")
            if node.node_id != _node_id(node.category, node_hash):
                raise GeometryPayloadError(
                    f"geometry node {node.node_id!r} has non-canonical id")
            actual.update(
                (node_hash, node.category, transform)
                for transform in node.transforms)

        expected: Counter[tuple[str, str, Matrix4]] = Counter()
        for record in self.index:
            if record.tier is ExtractedGeometryTier.A:
                continue
            assert record.geo_hash is not None
            assert record.transform is not None
            if record.geo_hash not in self.store:
                raise GeometryPayloadError(
                    f"geometry index references unknown hash "
                    f"{record.geo_hash!r}")
            definition = self.store.get(record.geo_hash)
            if definition.tier.value != record.tier.value:
                raise GeometryPayloadError(
                    f"geometry tier disagrees with store for "
                    f"{record.element_id!r}")
            expected[(
                record.geo_hash, record.category, record.transform)] += 1
        if actual != expected:
            raise GeometryPayloadError(
                "geometry nodes do not cover the Tier-G index exactly")

        details = {item.element_id: item.detail_level
                   for item in self.detail_levels}
        if len(details) != len(self.detail_levels):
            raise GeometryPayloadError(
                "GeometryExtraction.detail_levels repeats element_id")
        accounted = {
            record.element_id: record.detail_level for record in self.index}
        accounted.update({
            failure.element_id: failure.detail_level
            for failure in self.failures})
        for element_id, detail_level in details.items():
            if accounted.get(element_id) is not detail_level:
                raise GeometryPayloadError(
                    "geometry detail level disagrees with its element row: "
                    f"{element_id!r}")

    def __iter__(self) -> Iterator[GeometryNode]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    @property
    def records(self) -> tuple[GeometryIndexRecord, ...]:
        """Common side-stage accounting alias used by the live pipeline."""

        return self.index

    @property
    def geometry_index(self) -> dict[str, dict[str, Any]]:
        return {record.element_id: record.to_dict() for record in self.index}

    def entry_for(self, element_id: str) -> GeometryIndexRecord:
        for record in self.index:
            if record.element_id == element_id:
                return record
        raise GeometryPayloadError(
            f"element is absent from geometry index: {element_id!r}")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "geometry_store": self.store.to_dict(),
            "geometry_index": self.geometry_index,
            "nodes": [node.to_dict() for node in self.nodes],
            "degradations": [item.to_dict() for item in self.degradations],
            "failures": [item.to_dict() for item in self.failures],
        }
        # Omit the additive section on the frozen Fine/default path so every
        # existing persisted fixture remains byte-for-byte unchanged.
        if self.detail_levels:
            result["detail_levels"] = [
                item.to_dict() for item in self.detail_levels]
        return result

    @classmethod
    def from_dict(
        cls,
        value: Any,
        *,
        categories_by_id: Mapping[str, str] | None = None,
    ) -> "GeometryExtraction":
        """Rehydrate and fully validate the frozen persisted bundle."""

        root = _additive_fields(value, {
            "geometry_store", "geometry_index", "nodes", "degradations",
            "failures",
        }, {"detail_levels"}, "geometry bundle")

        raw_store = _require_mapping(
            root["geometry_store"], "geometry bundle.geometry_store")
        store = GeometryStore()
        for geo_hash in sorted(raw_store):
            if _HASH_RE.fullmatch(geo_hash) is None:
                raise GeometryPayloadError(
                    f"invalid geometry store hash: {geo_hash!r}")
            definition = _validated_geometry(
                raw_store[geo_hash],
                f"geometry bundle.geometry_store[{geo_hash!r}]",
            )
            if store.add(definition) != geo_hash:
                raise GeometryPayloadError(
                    f"geometry store hash mismatch for {geo_hash!r}")

        raw_nodes = _require_list(root["nodes"], "geometry bundle.nodes")
        nodes: list[GeometryNode] = []
        for index, raw_node in enumerate(raw_nodes):
            try:
                nodes.append(GeometryNode.from_dict(
                    raw_node, f"geometry bundle.nodes[{index}]"))
            except GeometrySchemaError as exc:
                raise GeometryPayloadError(str(exc)) from exc

        detail_levels: list[GeometryDetailRecord] = []
        raw_details = root.get("detail_levels", [])
        for index, raw_detail in enumerate(_require_list(
                raw_details, "geometry bundle.detail_levels")):
            field_name = f"geometry bundle.detail_levels[{index}]"
            row = _exact_fields(
                raw_detail, {"element_id", "detail_level"}, field_name)
            try:
                detail_level = GeometryDetailLevel(row["detail_level"])
            except (TypeError, ValueError) as exc:
                raise GeometryPayloadError(
                    f"{field_name}.detail_level is unsupported") from exc
            detail_levels.append(GeometryDetailRecord(
                element_id=_require_string(
                    row["element_id"], f"{field_name}.element_id"),
                detail_level=detail_level,
            ))
        detail_by_id = {
            item.element_id: item.detail_level for item in detail_levels}
        if len(detail_by_id) != len(detail_levels):
            raise GeometryPayloadError(
                "geometry bundle.detail_levels repeats element_id")

        raw_index = _require_mapping(
            root["geometry_index"], "geometry bundle.geometry_index")
        provisional: list[
            tuple[str, ExtractedGeometryTier, str | None, Matrix4 | None,
                  GeometryDetailLevel | None]
        ] = []
        for element_id in sorted(raw_index):
            _require_string(element_id, "geometry index element_id")
            field_name = f"geometry bundle.geometry_index[{element_id!r}]"
            row = _exact_fields(
                raw_index[element_id], {"tier", "geo_hash", "transform"},
                field_name)
            try:
                tier = ExtractedGeometryTier(row["tier"])
            except (TypeError, ValueError) as exc:
                raise GeometryPayloadError(
                    f"{field_name}.tier is unsupported") from exc
            if tier is ExtractedGeometryTier.A:
                if row["geo_hash"] is not None or row["transform"] is not None:
                    raise GeometryPayloadError(
                        f"{field_name}: Tier A cannot carry geometry")
                geo_hash = None
                transform = None
            else:
                geo_hash = _require_string(
                    row["geo_hash"], f"{field_name}.geo_hash")
                if _HASH_RE.fullmatch(geo_hash) is None:
                    raise GeometryPayloadError(
                        f"{field_name}.geo_hash must be SHA-256")
                transform = _transform_from_json(
                    row["transform"], f"{field_name}.transform")
            provisional.append((
                element_id, tier, geo_hash, transform,
                detail_by_id.get(element_id),
            ))

        failures: list[GeometryFailure] = []
        raw_failures = _require_list(
            root["failures"], "geometry bundle.failures")
        for index, raw_failure in enumerate(raw_failures):
            field_name = f"geometry bundle.failures[{index}]"
            row = _additive_fields(raw_failure, {
                "element_id", "category", "errors",
            }, {"reason", "elapsed_ms", "detail_level"}, field_name)
            element_id = _require_string(
                row["element_id"], f"{field_name}.element_id")
            raw_errors = _require_list(row["errors"], f"{field_name}.errors")
            errors = tuple(
                _require_string(error, f"{field_name}.errors")
                for error in raw_errors)
            reason = None
            elapsed_ms = None
            if "reason" in row:
                try:
                    reason = GeometryFailureReason(row["reason"])
                except (TypeError, ValueError) as exc:
                    raise GeometryPayloadError(
                        f"{field_name}.reason is unsupported") from exc
                elapsed_ms = _require_nonnegative_int(
                    row.get("elapsed_ms"), f"{field_name}.elapsed_ms")
            elif "elapsed_ms" in row:
                raise GeometryPayloadError(
                    f"{field_name}.elapsed_ms requires reason")
            inline_detail = None
            if "detail_level" in row:
                try:
                    inline_detail = GeometryDetailLevel(row["detail_level"])
                except (TypeError, ValueError) as exc:
                    raise GeometryPayloadError(
                        f"{field_name}.detail_level is unsupported") from exc
            persisted_detail = detail_by_id.get(element_id)
            if inline_detail is not None and persisted_detail not in (
                    None, inline_detail):
                raise GeometryPayloadError(
                    f"{field_name}.detail_level disagrees with detail_levels")
            failures.append(GeometryFailure(
                element_id=element_id,
                category=_require_string(
                    row["category"], f"{field_name}.category", empty=True),
                errors=errors,
                reason=reason,
                elapsed_ms=elapsed_ms,
                detail_level=inline_detail or persisted_detail,
            ))

        degradations: list[GeometryDegradation] = []
        raw_degradations = _require_list(
            root["degradations"], "geometry bundle.degradations")
        for index, raw_degradation in enumerate(raw_degradations):
            field_name = f"geometry bundle.degradations[{index}]"
            row = _exact_fields(raw_degradation, {
                "element_id", "part_index", "from_tier", "to_tier",
                "reason",
            }, field_name)
            if row["from_tier"] != "Gb" or row["to_tier"] != "Gm":
                raise GeometryPayloadError(
                    f"{field_name} must describe Gb -> Gm")
            part_index = row["part_index"]
            if part_index is not None:
                part_index = _require_nonnegative_int(
                    part_index, f"{field_name}.part_index")
            degradations.append(GeometryDegradation(
                element_id=_require_string(
                    row["element_id"], f"{field_name}.element_id"),
                part_index=part_index,
                reason=_require_string(
                    row["reason"], f"{field_name}.reason"),
            ))

        index = _resolve_index_categories(
            provisional, nodes, categories_by_id)
        return cls(
            store=store,
            index=index,
            nodes=tuple(nodes),
            degradations=tuple(degradations),
            failures=tuple(failures),
            detail_levels=tuple(detail_levels),
        )

    @classmethod
    def from_json(
        cls,
        value: str,
        *,
        categories_by_id: Mapping[str, str] | None = None,
    ) -> "GeometryExtraction":
        try:
            payload = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise GeometryPayloadError(
                f"geometry bundle is not valid JSON: {exc}") from exc
        return cls.from_dict(payload, categories_by_id=categories_by_id)

    def world_fallback_mesh(self, element_id: str) -> GmMesh:
        """Return one element's validated Gm floor in world millimetres."""

        return self.world_fallback_mesh_for_record(self.entry_for(element_id))

    def world_fallback_mesh_for_record(
        self,
        record: GeometryIndexRecord,
    ) -> GmMesh:
        """World-space Gm floor for an already indexed record.

        Batch consumers build their own element-id map once and use this form;
        repeatedly scanning a 50k-row index would turn atom escrow quadratic.
        """

        if not isinstance(record, GeometryIndexRecord):
            raise GeometryPayloadError(
                "world fallback requires a GeometryIndexRecord")
        if record.tier is ExtractedGeometryTier.A:
            raise GeometryPayloadError(
                f"element {record.element_id!r} has no Tier-G geometry")
        assert record.geo_hash is not None
        assert record.transform is not None
        mesh = _fallback_mesh(self.store.get(record.geo_hash))
        vertices = tuple(
            _transform_point(record.transform, vertex)
            for vertex in mesh.vertices_mm)
        # A mirrored affine basis reverses orientation.  Keep the world mesh's
        # triangle winding aligned with the source instead of emitting an
        # inside-out DirectShape candidate.
        matrix = record.transform
        determinant = (
            matrix[0] * (matrix[5] * matrix[10] - matrix[6] * matrix[9])
            - matrix[1] * (matrix[4] * matrix[10] - matrix[6] * matrix[8])
            + matrix[2] * (matrix[4] * matrix[9] - matrix[5] * matrix[8])
        )
        triangles = (
            tuple((a, c, b) for a, b, c in mesh.triangles)
            if determinant < 0.0 else mesh.triangles)
        try:
            return GmMesh(vertices, triangles)
        except GeometrySchemaError as exc:
            raise GeometryPayloadError(
                f"world transform invalidated geometry for "
                f"{record.element_id!r}: {exc}") from exc


def merge_geometry_extractions(
    parts: Sequence[GeometryExtraction],
) -> GeometryExtraction:
    """Merge paginated geometry results under one canonical store."""

    store = GeometryStore()
    index: list[GeometryIndexRecord] = []
    degradations: list[GeometryDegradation] = []
    failures: list[GeometryFailure] = []
    detail_levels: list[GeometryDetailRecord] = []
    for part in parts:
        if not isinstance(part, GeometryExtraction):
            raise GeometryPayloadError(
                "geometry merge parts must be GeometryExtraction values")
        for stored in part.store:
            if store.add(stored.geometry) != stored.geo_hash:
                raise GeometryStoreError(
                    f"geometry store hash mismatch for {stored.geo_hash!r}")
        index.extend(part.index)
        degradations.extend(part.degradations)
        failures.extend(part.failures)
        detail_levels.extend(part.detail_levels)
    return GeometryExtraction(
        store=store,
        index=tuple(index),
        nodes=_nodes_for_index(store, index),
        degradations=tuple(degradations),
        failures=tuple(failures),
        detail_levels=tuple(detail_levels),
    )


def extract_geometry(
    payload: Any,
    *,
    store: GeometryStore | None = None,
) -> GeometryExtraction:
    """Validate, deduplicate, and compose one emitted Revit payload.

    Dirty/unsupported element geometry is represented in ``failures`` and is
    never relabelled Tier A.  A malformed wire payload is a typed refusal.
    """

    root = _exact_fields(
        _unwrap_payload(payload),
        {"schema_version", "elements"},
        "geometry extraction",
    )
    if root["schema_version"] != GEOMETRY_EXTRACT_SCHEMA_VERSION:
        raise GeometryPayloadError(
            "geometry extraction schema_version mismatch")
    elements = _require_list(root["elements"], "geometry extraction.elements")
    target_store = store if store is not None else GeometryStore()
    index: list[GeometryIndexRecord] = []
    degradations: list[GeometryDegradation] = []
    failures: list[GeometryFailure] = []
    detail_levels: list[GeometryDetailRecord] = []
    occurrences: dict[tuple[str, str], list[Matrix4]] = {}
    seen_ids: set[str] = set()

    for element_index, raw_element in enumerate(elements):
        field_name = f"geometry extraction.elements[{element_index}]"
        row = _additive_fields(raw_element, {
            "element_id", "category", "status", "parts", "errors",
        }, {"reason", "elapsed_ms", "detail_level"}, field_name)
        element_id = _require_string(
            row["element_id"], f"{field_name}.element_id")
        if element_id in seen_ids:
            raise GeometryPayloadError(
                f"duplicate geometry element_id: {element_id!r}")
        seen_ids.add(element_id)
        category = _require_string(
            row["category"], f"{field_name}.category", empty=True)
        status = _require_string(row["status"], f"{field_name}.status")
        raw_parts = _require_list(row["parts"], f"{field_name}.parts")
        raw_errors = _require_list(row["errors"], f"{field_name}.errors")
        if not all(isinstance(error, str) and error for error in raw_errors):
            raise GeometryPayloadError(
                f"{field_name}.errors must contain non-empty strings")
        errors = tuple(str(error)[:300] for error in raw_errors)
        detail_level = None
        if "detail_level" in row:
            try:
                detail_level = GeometryDetailLevel(row["detail_level"])
            except (TypeError, ValueError) as exc:
                raise GeometryPayloadError(
                    f"{field_name}.detail_level is unsupported") from exc
            detail_levels.append(GeometryDetailRecord(
                element_id=element_id,
                detail_level=detail_level,
            ))
        reason = None
        elapsed_ms = None
        if "reason" in row:
            try:
                reason = GeometryFailureReason(row["reason"])
            except (TypeError, ValueError) as exc:
                raise GeometryPayloadError(
                    f"{field_name}.reason is unsupported") from exc
            if "elapsed_ms" not in row:
                raise GeometryPayloadError(
                    f"{field_name}.reason requires elapsed_ms")
            elapsed_ms = _require_nonnegative_int(
                row["elapsed_ms"], f"{field_name}.elapsed_ms")
        elif "elapsed_ms" in row:
            raise GeometryPayloadError(
                f"{field_name}.elapsed_ms requires a typed reason")

        if status == "empty":
            if raw_parts or errors or reason is not None:
                raise GeometryPayloadError(
                    f"{field_name} empty status cannot carry parts/errors")
            index.append(GeometryIndexRecord(
                element_id, category, ExtractedGeometryTier.A, None, None,
                detail_level=detail_level))
            continue
        if status not in ("ok", "partial", "failed"):
            raise GeometryPayloadError(
                f"{field_name}.status is unsupported: {status!r}")
        if status == "ok" and (not raw_parts or errors):
            raise GeometryPayloadError(
                f"{field_name} ok status requires parts and no errors")
        if status == "failed" and (raw_parts or not errors):
            raise GeometryPayloadError(
                f"{field_name} failed status requires errors and no parts")
        if reason is not None and (
                status != "failed" or reason.value not in errors):
            raise GeometryPayloadError(
                f"{field_name} typed reason requires matching failed error")
        if status in ("partial", "failed"):
            failures.append(GeometryFailure(
                element_id, category,
                errors or ("partial geometry extraction",),
                reason=reason,
                elapsed_ms=elapsed_ms,
                detail_level=detail_level,
            ))
            continue

        parts: list[_GeometryPart] = []
        for part_index, raw_part in enumerate(raw_parts):
            part, degradation = _parse_part(
                raw_part,
                field_name=f"{field_name}.parts[{part_index}]",
                element_id=element_id,
                part_index=part_index,
            )
            parts.append(part)
            if degradation is not None:
                degradations.append(degradation)

        if len(parts) == 1:
            geometry = parts[0].geometry
            transform = parts[0].transform
        else:
            geometry, transform = _combine_parts(parts)
            degradations.append(GeometryDegradation(
                element_id=element_id,
                part_index=None,
                reason=(
                    "frozen GbSolid represents one solid; combined multiple "
                    "geometry parts through their exact Gm fallbacks"),
            ))
        geo_hash = target_store.add(geometry)
        tier = ExtractedGeometryTier(geometry.tier.value)
        index.append(GeometryIndexRecord(
            element_id, category, tier, geo_hash, transform,
            detail_level=detail_level))
        occurrences.setdefault((geo_hash, category), []).append(transform)

    nodes = []
    for (geo_hash, category), transforms in sorted(occurrences.items()):
        geometry = target_store.get(geo_hash)
        node_row = {
            "node_id": _node_id(category, geo_hash),
            "category": category,
            "geometry": geometry.to_dict(),
            "transforms": [list(value) for value in sorted(transforms)],
        }
        try:
            nodes.append(GeometryNode.from_dict(node_row))
        except GeometrySchemaError as exc:
            raise GeometryPayloadError(
                f"cannot compose frozen GeometryNode for {geo_hash}: {exc}"
            ) from exc

    return GeometryExtraction(
        store=target_store,
        index=tuple(index),
        nodes=tuple(nodes),
        degradations=tuple(degradations),
        failures=tuple(failures),
        detail_levels=tuple(detail_levels),
    )


# ── Deterministic Revit C# emission ─────────────────────────────────────────


GEOMETRY_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE Wave Gx — read-only full geometry extraction helpers.
// Coordinates and radii cross the wire in millimetres. Vectors and native
// surface/curve parameters remain unitless/native. No Transaction is opened.
Func<double, double> __gxMM = (__feet) =>
    UnitUtils.ConvertFromInternalUnits(__feet, UnitTypeId.Millimeters);
Func<XYZ, object> __gxPoint = (__point) => (object)new double[] {
    __gxMM(__point.X), __gxMM(__point.Y), __gxMM(__point.Z)
};
Func<XYZ, object> __gxVector = (__vector) => (object)new double[] {
    __vector.X, __vector.Y, __vector.Z
};
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
Func<object, string> __gxClassName = (__gxcnObj) =>
{
    if (__gxcnObj == null) return "";
    string __gxcn = __gxcnObj.ToString();
    if (__gxcn == null) return "";
    int __gxcnCut = __gxcn.IndexOf((char)10);
    if (__gxcnCut >= 0) __gxcn = __gxcn.Substring(0, __gxcnCut);
    __gxcnCut = __gxcn.IndexOf(':');
    if (__gxcnCut >= 0) __gxcn = __gxcn.Substring(0, __gxcnCut);
    __gxcn = __gxcn.Trim();
    __gxcnCut = __gxcn.LastIndexOf('.');
    return __gxcnCut >= 0 && __gxcnCut + 1 < __gxcn.Length
        ? __gxcn.Substring(__gxcnCut + 1) : __gxcn;
};
Func<Exception, string> __gxError = (__error) =>
{
    string __message = __gxClassName(__error) + ": " + (__error.Message ?? "");
    return __message.Length <= 300 ? __message : __message.Substring(0, 300);
};
Func<XYZ, XYZ, XYZ, XYZ, Dictionary<string, object>> __gxFrame =
    (__origin, __x, __y, __z) => new Dictionary<string, object> {
        {"origin_mm", __gxPoint(__origin)},
        {"basis_x", __gxVector(__x)},
        {"basis_y", __gxVector(__y)},
        {"basis_z", __gxVector(__z)}
    };
Func<Transform, object> __gxTransform = (__transform) =>
{
    XYZ __x = __transform.BasisX;
    XYZ __y = __transform.BasisY;
    XYZ __z = __transform.BasisZ;
    XYZ __o = __transform.Origin;
    return (object)new double[] {
        __x.X, __y.X, __z.X, __gxMM(__o.X),
        __x.Y, __y.Y, __z.Y, __gxMM(__o.Y),
        __x.Z, __y.Z, __z.Z, __gxMM(__o.Z),
        0.0, 0.0, 0.0, 1.0
    };
};
Func<IList<double>, int, int, bool> __gxClampedKnots =
    (__knots, __degree, __controlCount) =>
{
    if (__knots == null || __degree < 1 || __controlCount <= __degree ||
        __knots.Count != __degree + __controlCount + 1)
        return false;
    if (__knots[0] == __knots[__knots.Count - 1]) return false;
    for (int __i = 0; __i + 1 < __knots.Count; __i++)
        if (__knots[__i] > __knots[__i + 1]) return false;
    for (int __i = 0; __i <= __degree; __i++)
    {
        if (__knots[__i] != __knots[0]) return false;
        if (__knots[__knots.Count - 1 - __i] !=
            __knots[__knots.Count - 1]) return false;
    }
    return true;
};

Action<Mesh, List<object>, List<object>> __gxAppendMesh =
    (__mesh, __vertices, __triangles) =>
{
    if (__mesh == null || __mesh.NumTriangles <= 0 ||
        __mesh.Vertices == null || __mesh.Vertices.Count < 3)
        throw new InvalidOperationException("mesh contains no triangles");
    int __offset = __vertices.Count;
    foreach (XYZ __vertex in __mesh.Vertices)
        __vertices.Add(__gxPoint(__vertex));
    for (int __triangleIndex = 0;
         __triangleIndex < __mesh.NumTriangles; __triangleIndex++)
    {
        MeshTriangle __triangle = __mesh.get_Triangle(__triangleIndex);
        int __a = (int)__triangle.get_Index(0);
        int __b = (int)__triangle.get_Index(1);
        int __c = (int)__triangle.get_Index(2);
        if (__a == __b || __b == __c || __a == __c ||
            __a < 0 || __b < 0 || __c < 0 ||
            __a >= __mesh.Vertices.Count ||
            __b >= __mesh.Vertices.Count ||
            __c >= __mesh.Vertices.Count)
            continue;
        XYZ __pa = __mesh.Vertices[__a];
        XYZ __pb = __mesh.Vertices[__b];
        XYZ __pc = __mesh.Vertices[__c];
        double __area2 = (__pb - __pa).CrossProduct(__pc - __pa).GetLength();
        if (__area2 <= 1.0e-12) continue;
        __triangles.Add((object)new int[] {
            __offset + __a, __offset + __b, __offset + __c
        });
    }
};
Func<List<object>, List<object>, Dictionary<string, object>> __gxMeshRow =
    (__vertices, __triangles) =>
{
    if (__vertices.Count < 3 || __triangles.Count == 0)
        throw new InvalidOperationException("mesh has no non-degenerate triangles");
    return new Dictionary<string, object> {
        {"tier", "Gm"},
        {"vertices_mm", __vertices},
        {"triangles", __triangles}
    };
};
Func<Mesh, Dictionary<string, object>> __gxMesh = (__mesh) =>
{
    var __vertices = new List<object>();
    var __triangles = new List<object>();
    __gxAppendMesh(__mesh, __vertices, __triangles);
    return __gxMeshRow(__vertices, __triangles);
};
Func<Solid, Dictionary<string, object>> __gxSolidMesh = (__solid) =>
{
    var __vertices = new List<object>();
    var __triangles = new List<object>();
    foreach (Face __face in __solid.Faces)
    {
        Mesh __faceMesh = __face.Triangulate(1.0);
        __gxAppendMesh(__faceMesh, __vertices, __triangles);
    }
    return __gxMeshRow(__vertices, __triangles);
};

Func<Curve, Dictionary<string, object>> __gxCurve = null;
__gxCurve = (__curve) =>
{
    if (__curve == null)
        throw new InvalidOperationException("edge/profile curve is null");
    Line __line = __curve as Line;
    if (__line != null)
    {
        if (!__line.IsBound)
            throw new InvalidOperationException("unbounded line edge");
        return new Dictionary<string, object> {
            {"curve_type", "Line"},
            {"start_mm", __gxPoint(__line.GetEndPoint(0))},
            {"end_mm", __gxPoint(__line.GetEndPoint(1))}
        };
    }
    Arc __arc = __curve as Arc;
    if (__arc != null)
    {
        if (!__arc.IsBound && !__arc.IsCyclic)
            throw new InvalidOperationException("unbounded non-cyclic arc edge");
        double __start = __arc.IsBound ? __arc.GetEndParameter(0) : 0.0;
        double __end = __arc.IsBound
            ? __arc.GetEndParameter(1) : 2.0 * Math.PI;
        double __span = __end - __start;
        if (__span <= 0.0 || __span > 2.0 * Math.PI + 1.0e-8)
            throw new InvalidOperationException("arc parameter span is unsupported");
        return new Dictionary<string, object> {
            {"curve_type", "Arc"},
            {"center_mm", __gxPoint(__arc.Center)},
            {"radius_mm", __gxMM(__arc.Radius)},
            {"x_axis", __gxVector(__arc.XDirection)},
            {"y_axis", __gxVector(__arc.YDirection)},
            {"start_angle_rad", __start},
            {"end_angle_rad", __end}
        };
    }
    Ellipse __ellipse = __curve as Ellipse;
    if (__ellipse != null)
    {
        if ((!__ellipse.IsBound && !__ellipse.IsCyclic) ||
            __ellipse.RadiusX < __ellipse.RadiusY)
            throw new InvalidOperationException("ellipse edge is unsupported");
        double __start = __ellipse.IsBound
            ? __ellipse.GetEndParameter(0) : 0.0;
        double __end = __ellipse.IsBound
            ? __ellipse.GetEndParameter(1) : 2.0 * Math.PI;
        double __span = __end - __start;
        if (__span <= 0.0 || __span > 2.0 * Math.PI + 1.0e-8)
            throw new InvalidOperationException("ellipse parameter span is unsupported");
        return new Dictionary<string, object> {
            {"curve_type", "Ellipse"},
            {"center_mm", __gxPoint(__ellipse.Center)},
            {"radius_x_mm", __gxMM(__ellipse.RadiusX)},
            {"radius_y_mm", __gxMM(__ellipse.RadiusY)},
            {"x_axis", __gxVector(__ellipse.XDirection)},
            {"y_axis", __gxVector(__ellipse.YDirection)},
            {"start_angle_rad", __start},
            {"end_angle_rad", __end}
        };
    }
    NurbSpline __nurbs = __curve as NurbSpline;
    if (__nurbs == null)
    {
        HermiteSpline __hermite = __curve as HermiteSpline;
        if (__hermite != null && !__hermite.IsPeriodic)
            __nurbs = NurbSpline.Create(__hermite);
    }
    if (__nurbs != null)
    {
        if (__nurbs.IsCyclic)
            throw new InvalidOperationException("periodic NURBS edge");
        var __knots = new List<double>();
        foreach (double __knot in __nurbs.Knots) __knots.Add(__knot);
        var __controlPoints = new List<object>();
        foreach (XYZ __point in __nurbs.CtrlPoints)
            __controlPoints.Add(__gxPoint(__point));
        if (!__gxClampedKnots(
                __knots, __nurbs.Degree, __controlPoints.Count))
            throw new InvalidOperationException("NURBS edge is not clamped");
        object __weights = null;
        if (__nurbs.isRational)
        {
            var __weightValues = new List<double>();
            foreach (double __weight in __nurbs.Weights)
            {
                if (__weight <= 0.0)
                    throw new InvalidOperationException("non-positive NURBS weight");
                __weightValues.Add(__weight);
            }
            if (__weightValues.Count != __controlPoints.Count)
                throw new InvalidOperationException("NURBS weight count mismatch");
            __weights = __weightValues;
        }
        return new Dictionary<string, object> {
            {"curve_type", "NURBS"},
            {"degree", __nurbs.Degree},
            {"knots", __knots},
            {"control_points_mm", __controlPoints},
            {"weights", __weights}
        };
    }
    throw new InvalidOperationException(
        "unsupported curve: " + __gxClassName(__curve));
};

Func<Surface, Dictionary<string, object>> __gxNurbsSurface = (__surface) =>
{
    NurbsSurfaceData __data = null;
    try
    {
        __data = Autodesk.Revit.DB.ExportUtils.GetNurbsSurfaceDataForSurface(
            __surface);
        if (__data == null || !__data.IsValid())
            throw new InvalidOperationException("NURBS export returned invalid data");
        IList<double> __knotsU = __data.GetKnotsU();
        IList<double> __knotsV = __data.GetKnotsV();
        IList<XYZ> __points = __data.GetControlPoints();
        int __countU = __knotsU.Count - __data.DegreeU - 1;
        int __countV = __knotsV.Count - __data.DegreeV - 1;
        if (!__gxClampedKnots(__knotsU, __data.DegreeU, __countU) ||
            !__gxClampedKnots(__knotsV, __data.DegreeV, __countV) ||
            __points.Count != __countU * __countV)
            throw new InvalidOperationException(
                "NURBS surface is periodic, unclamped, or incomplete");
        var __pointsOut = new List<object>();
        foreach (XYZ __point in __points) __pointsOut.Add(__gxPoint(__point));
        object __weights = null;
        if (__data.IsRational)
        {
            IList<double> __weightValues = __data.GetWeights();
            if (__weightValues.Count != __points.Count ||
                __weightValues.Any(__weight => __weight <= 0.0))
                throw new InvalidOperationException("invalid NURBS surface weights");
            __weights = __weightValues.ToList();
        }
        return new Dictionary<string, object> {
            {"surface_type", "NURBS"},
            {"degree_u", __data.DegreeU},
            {"degree_v", __data.DegreeV},
            {"control_count_u", __countU},
            {"control_count_v", __countV},
            {"knots_u", __knotsU.ToList()},
            {"knots_v", __knotsV.ToList()},
            {"control_points_mm", __pointsOut},
            {"weights", __weights},
            {"reverse_orientation", __data.ReverseOrientation}
        };
    }
    finally
    {
        if (__data != null) __data.Dispose();
    }
};

Func<Face, Dictionary<string, object>> __gxSurface = (__face) =>
{
    Surface __surface = __face.GetSurface();
    if (__surface == null)
        throw new InvalidOperationException("face surface is null");
    try
    {
        Plane __plane = __surface as Plane;
        if (__plane != null)
            return new Dictionary<string, object> {
                {"surface_type", "Planar"},
                {"frame", __gxFrame(
                    __plane.Origin, __plane.XVec, __plane.YVec, __plane.Normal)}
            };
        CylindricalSurface __cylinder = __surface as CylindricalSurface;
        if (__cylinder != null)
            return new Dictionary<string, object> {
                {"surface_type", "Cylindrical"},
                {"frame", __gxFrame(
                    __cylinder.Origin, __cylinder.XDir,
                    __cylinder.YDir, __cylinder.Axis)},
                {"radius_mm", __gxMM(__cylinder.Radius)}
            };
        ConicalSurface __cone = __surface as ConicalSurface;
        if (__cone != null)
            return new Dictionary<string, object> {
                {"surface_type", "Conical"},
                {"frame", __gxFrame(
                    __cone.Origin, __cone.XDir, __cone.YDir, __cone.Axis)},
                {"half_angle_rad", __cone.HalfAngle}
            };
        RevolvedSurface __revolved = __surface as RevolvedSurface;
        if (__revolved != null)
            return new Dictionary<string, object> {
                {"surface_type", "Revolved"},
                {"frame", __gxFrame(
                    __revolved.Origin, __revolved.XDir,
                    __revolved.YDir, __revolved.Axis)},
                {"profile", __gxCurve(__revolved.GetProfileCurve())}
            };
        RuledSurface __ruled = __surface as RuledSurface;
        if (__ruled != null && !__ruled.HasFirstProfilePoint())
        {
            object __profileB = null;
            object __pointB = null;
            if (__ruled.HasSecondProfilePoint())
                __pointB = __gxPoint(__ruled.GetSecondProfilePoint());
            else
                __profileB = __gxCurve(__ruled.GetSecondProfileCurve());
            return new Dictionary<string, object> {
                {"surface_type", "Ruled"},
                {"profile_a", __gxCurve(__ruled.GetFirstProfileCurve())},
                {"profile_b", __profileB},
                {"point_b_mm", __pointB}
            };
        }
        // Revit exposes exact NURBS export data for Hermite faces and for
        // ruled faces whose point/curve order cannot fit the frozen shape.
        if (__face is HermiteFace || __ruled != null)
            return __gxNurbsSurface(__surface);
        throw new InvalidOperationException(
            "unsupported surface: " + __gxClassName(__surface));
    }
    finally
    {
        __surface.Dispose();
    }
};

Func<Solid, Dictionary<string, object>, Dictionary<string, object>>
    __gxSolid = (__solid, __fallback) =>
{
    var __solidEdges = new List<Edge>();
    foreach (Edge __edge in __solid.Edges) __solidEdges.Add(__edge);
    if (__solidEdges.Count == 0)
        throw new InvalidOperationException("solid has no shared edges");
    var __edgesOut = new List<object>();
    for (int __edgeIndex = 0;
         __edgeIndex < __solidEdges.Count; __edgeIndex++)
    {
        __edgesOut.Add(new Dictionary<string, object> {
            {"edge_id", "e" + __edgeIndex.ToString()},
            {"curve", __gxCurve(__solidEdges[__edgeIndex].AsCurve())}
        });
    }
    int[] __coedgeCounts = new int[__solidEdges.Count];
    bool[] __firstOrientation = new bool[__solidEdges.Count];
    var __facesOut = new List<object>();
    foreach (Face __face in __solid.Faces)
    {
        var __loopsOut = new List<object>();
        foreach (EdgeArray __loop in __face.EdgeLoops)
        {
            var __coedgesOut = new List<object>();
            foreach (Edge __edge in __loop)
            {
                int __found = -1;
                for (int __edgeIndex = 0;
                     __edgeIndex < __solidEdges.Count; __edgeIndex++)
                {
                    if (Object.ReferenceEquals(
                            __solidEdges[__edgeIndex], __edge) ||
                        __solidEdges[__edgeIndex].Equals(__edge))
                    {
                        __found = __edgeIndex;
                        break;
                    }
                }
                if (__found < 0)
                    throw new InvalidOperationException(
                        "face loop edge is absent from solid edge table");
                bool __reversed = __edge.IsFlippedOnFace(__face);
                if (__coedgeCounts[__found] == 0)
                    __firstOrientation[__found] = __reversed;
                else if (__coedgeCounts[__found] == 1 &&
                         __firstOrientation[__found] == __reversed)
                    throw new InvalidOperationException(
                        "shared edge coedges have equal orientation");
                __coedgeCounts[__found]++;
                if (__coedgeCounts[__found] > 2)
                    throw new InvalidOperationException("non-manifold shared edge");
                __coedgesOut.Add(new Dictionary<string, object> {
                    {"edge_id", "e" + __found.ToString()},
                    {"reversed", __reversed}
                });
            }
            if (__coedgesOut.Count == 0)
                throw new InvalidOperationException("empty face edge loop");
            __loopsOut.Add(new Dictionary<string, object> {
                {"coedges", __coedgesOut}
            });
        }
        BoundingBoxUV __bounds = __face.GetBoundingBox();
        if (__bounds == null || __bounds.Min == null || __bounds.Max == null ||
            __bounds.Min.U >= __bounds.Max.U ||
            __bounds.Min.V >= __bounds.Max.V)
            throw new InvalidOperationException("invalid face UV bounds");
        __facesOut.Add(new Dictionary<string, object> {
            {"surface", __gxSurface(__face)},
            {"reversed", !__face.OrientationMatchesSurfaceOrientation},
            {"loops", __loopsOut},
            {"uv_bounds", new double[] {
                __bounds.Min.U, __bounds.Min.V,
                __bounds.Max.U, __bounds.Max.V
            }}
        });
    }
    for (int __edgeIndex = 0;
         __edgeIndex < __coedgeCounts.Length; __edgeIndex++)
        if (__coedgeCounts[__edgeIndex] != 2)
            throw new InvalidOperationException(
                "shared edge does not have exactly two coedges");
    return new Dictionary<string, object> {
        {"tier", "Gb"},
        {"edges", __edgesOut},
        {"faces", __facesOut},
        {"fallback_mesh", __fallback},
        {"brep_candidate_valid", true}
    };
};

Action<GeometryElement, Transform, int, List<object>, List<object>, Func<bool>>
    __gxWalk = null;
__gxWalk = (__geometry, __placement, __depth, __parts, __errors,
            __budgetExceeded) =>
{
    if (__geometry == null) return;
    if (__budgetExceeded()) return;
    if (__depth > 32)
    {
        __errors.Add("geometry instance nesting exceeds 32");
        return;
    }
    foreach (GeometryObject __object in __geometry)
    {
        if (__budgetExceeded()) return;
        Solid __solid = __object as Solid;
        if (__solid != null)
        {
            if (__solid.Faces != null && __solid.Faces.Size > 0)
            {
                try
                {
                    // Cooperative checkpoint before/after Revit's face
                    // tessellation. Triangulate itself cannot be preempted.
                    if (__budgetExceeded()) return;
                    Dictionary<string, object> __fallback =
                        __gxSolidMesh(__solid);
                    if (__budgetExceeded()) return;
                    Dictionary<string, object> __definition = null;
                    string __gbError = null;
                    try
                    {
                        // Exact solid topology traversal is another bounded
                        // stage; one API call/loop body may still overrun.
                        if (__budgetExceeded()) return;
                        __definition = __gxSolid(__solid, __fallback);
                        if (__budgetExceeded()) return;
                    }
                    catch (Exception __gbException)
                    {
                        __definition = __fallback;
                        __gbError = __gxError(__gbException);
                    }
                    __parts.Add(new Dictionary<string, object> {
                        {"geometry", __definition},
                        {"transform", __gxTransform(__placement)},
                        {"gb_error", __gbError}
                    });
                }
                catch (Exception __solidException)
                {
                    __errors.Add("Solid: " + __gxError(__solidException));
                }
            }
            continue;
        }
        GeometryInstance __instance = __object as GeometryInstance;
        if (__instance != null)
        {
            try
            {
                if (__budgetExceeded()) return;
                GeometryElement __symbolGeometry =
                    __instance.GetSymbolGeometry();
                if (__budgetExceeded()) return;
                if (__symbolGeometry == null)
                    throw new InvalidOperationException(
                        "symbol geometry is null");
                Transform __nestedPlacement =
                    __placement.Multiply(__instance.Transform);
                __gxWalk(__symbolGeometry, __nestedPlacement,
                         __depth + 1, __parts, __errors,
                         __budgetExceeded);
            }
            catch (Exception __instanceException)
            {
                __errors.Add(
                    "GeometryInstance: " + __gxError(__instanceException));
            }
            continue;
        }
        Mesh __mesh = __object as Mesh;
        if (__mesh != null)
        {
            try
            {
                if (__budgetExceeded()) return;
                __parts.Add(new Dictionary<string, object> {
                    {"geometry", __gxMesh(__mesh)},
                    {"transform", __gxTransform(__placement)},
                    {"gb_error", null}
                });
                if (__budgetExceeded()) return;
            }
            catch (Exception __meshException)
            {
                __errors.Add("Mesh: " + __gxError(__meshException));
            }
        }
    }
};
""".strip()


_GEOMETRY_EXTRACT_BODY_CS = r"""
var __gxRequestedIds = new string[] { __GX_ELEMENT_IDS__ };
var __gxRequestedSet = new HashSet<string>(__gxRequestedIds);
long __gxElementBudgetMs = __GX_ELEMENT_BUDGET_MS__L;
long __gxCallBudgetMs = __GX_CALL_BUDGET_MS__L;
ViewDetailLevel __gxDetailLevel = ViewDetailLevel.__GX_DETAIL_ENUM__;
long __gxCallWatchT0 = DateTime.UtcNow.Ticks;
var __gxFound = new Dictionary<string, Element>();
foreach (Element __element in new FilteredElementCollector(__src)
         .WhereElementIsNotElementType())
{
    if (((DateTime.UtcNow.Ticks - __gxCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __gxCallBudgetMs) break;
    string __id = __element.Id.ToString();
    if (__gxRequestedSet.Contains(__id) && !__gxFound.ContainsKey(__id))
    {
        __gxFound[__id] = __element;
        if (__gxFound.Count == __gxRequestedSet.Count) break;
    }
}
var __gxElementRows = new List<object>();
foreach (string __requestedId in __gxRequestedIds)
{
    var __row = new Dictionary<string, object>();
    var __parts = new List<object>();
    var __errors = new List<object>();
    __row["element_id"] = __requestedId;
    __row["category"] = "";
    __row["parts"] = __parts;
    __row["errors"] = __errors;
    if (__gxDetailLevel != ViewDetailLevel.Fine)
        __row["detail_level"] = "__GX_DETAIL_NAME__";
    string __gxBudgetReason = null;
    long __gxBudgetElapsed = 0L;
    long __gxElementWatchT0 = 0L;
    if (((DateTime.UtcNow.Ticks - __gxCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __gxCallBudgetMs)
    {
        __gxBudgetReason = "call_budget_exhausted";
        __gxBudgetElapsed = ((DateTime.UtcNow.Ticks - __gxCallWatchT0) / TimeSpan.TicksPerMillisecond);
    }
    else
    {
        __gxElementWatchT0 = DateTime.UtcNow.Ticks;
        Func<bool> __gxBudgetExceeded = () =>
            ((DateTime.UtcNow.Ticks - __gxElementWatchT0) / TimeSpan.TicksPerMillisecond) >= __gxElementBudgetMs ||
            ((DateTime.UtcNow.Ticks - __gxCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __gxCallBudgetMs;
        Element __element = null;
        if (!__gxFound.TryGetValue(__requestedId, out __element) ||
            __element == null)
        {
            __errors.Add("element not found");
        }
        else
        {
            try
            {
                Category __category = __element.Category;
                int __categoryValue;
                string __categoryName = null;
                if (__category != null &&
                    Int32.TryParse(
                        __category.Id.ToString(), out __categoryValue))
                    __categoryName = Enum.GetName(
                        typeof(BuiltInCategory), __categoryValue);
                if (String.IsNullOrWhiteSpace(__categoryName) ||
                    !__categoryName.StartsWith(
                        "OST_", StringComparison.Ordinal))
                    __errors.Add(
                        "element category has no frozen OST_* identity");
                else
                {
                    __row["category"] = __categoryName;
                    var __options = new Options {
                        ComputeReferences = false,
                        DetailLevel = ViewDetailLevel.__GX_DETAIL_ENUM__,
                        IncludeNonVisibleObjects = false
                    };
                    GeometryElement __geometry = null;
                    // Cooperative checkpoints bound only the tail around
                    // get_Geometry; the Revit call itself is not preemptible.
                    if (!__gxBudgetExceeded())
                        __geometry = __element.get_Geometry(__options);
                    if (!__gxBudgetExceeded())
                        __gxWalk(__geometry, Transform.Identity, 0,
                                 __parts, __errors,
                                 __gxBudgetExceeded);
                }
            }
            catch (Exception __elementException)
            {
                __errors.Add(
                    "Element: " + __gxError(__elementException));
            }
        }
        // Prefer the element reason for the active over-budget element; the
        // next and every remaining row will carry call_budget_exhausted when
        // the call deadline was crossed at the same time.
        if (((DateTime.UtcNow.Ticks - __gxElementWatchT0) / TimeSpan.TicksPerMillisecond) >= __gxElementBudgetMs)
        {
            __gxBudgetReason = "time_budget_exceeded";
            __gxBudgetElapsed = ((DateTime.UtcNow.Ticks - __gxElementWatchT0) / TimeSpan.TicksPerMillisecond);
        }
        else if (((DateTime.UtcNow.Ticks - __gxCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __gxCallBudgetMs)
        {
            __gxBudgetReason = "call_budget_exhausted";
            __gxBudgetElapsed = ((DateTime.UtcNow.Ticks - __gxCallWatchT0) / TimeSpan.TicksPerMillisecond);
        }
    }
    if (__gxBudgetReason != null)
    {
        // Never mislabel a timed-out partial traversal as usable geometry.
        __parts.Clear();
        __errors.Clear();
        __errors.Add(__gxBudgetReason);
        __row["reason"] = __gxBudgetReason;
        __row["elapsed_ms"] = __gxBudgetElapsed;
        __row["status"] = "failed";
    }
    else if (__errors.Count > 0)
        __row["status"] = __parts.Count > 0 ? "partial" : "failed";
    else
        __row["status"] = __parts.Count > 0 ? "ok" : "empty";
    __gxElementRows.Add(__row);
}
return new Dictionary<string, object> {
    {"schema_version", "kir-decompile-geometry/1"},
    {"elements", __gxElementRows}
};
""".strip()


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


def build_geometry_extract_cs(
    element_ids: Sequence[str | int],
    *,
    element_budget_ms: int = 2_000,
    call_budget_ms: int = 20_000,
    detail: str = GEOM_DETAIL.lower(),
    link_title: str | None = None,
) -> str:
    """Emit one deterministic, read-only Revit Execute body.

    Numeric ids are resolved by their version-safe ``ElementId.ToString()``
    representation, avoiding the 2021/2024 ``int``/``long`` constructor fork.
    The body is intentionally bounded to the frozen extraction batch size.

    The two time budgets are cooperative fail-safes, not hard preemption.
    Revit API calls such as ``get_Geometry``, solid traversal, and face
    tessellation cannot be interrupted safely; elapsed time is checked before
    and after those stages and between elements.  A single blocking API call
    may therefore exceed its budget, but its partial geometry is discarded,
    the overrun is reported, and subsequent inputs remain accounted for.

    ``detail="fine"`` preserves the legacy wire shape: ``detail_level`` is
    emitted only for explicit ``medium`` or ``coarse`` extraction.

    ``link_title`` — читать не ХОЗЯИНА, а его СВЯЗЬ с таким ``Document.Title``.
    Источник один на ВСЁ тело: у документов разные пространства
    идентификаторов, поэтому id связи, спрошенный у хозяина, либо не находится
    (квитанция на ровном месте), либо находит ЧУЖОЙ элемент с тем же числом —
    и тогда стадия записывает чужую строку как свою, молча. Замер 30.07 на
    связанной электрике Snowdon дал оба исхода разом.
    """

    if isinstance(element_ids, (str, bytes)):
        raise ValueError("element_ids must be a sequence, not a string")
    normalized = []
    for index, value in enumerate(element_ids):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError(
                f"element_ids[{index}] must be a numeric string or integer")
        item = str(value)
        if re.fullmatch(r"-?[0-9]+", item) is None:
            raise ValueError(
                f"element_ids[{index}] must be a numeric Revit id")
        normalized.append(item)
    if not normalized:
        raise ValueError("at least one element id is required")
    if len(normalized) > EXTRACT_BATCH:
        raise ValueError(
            f"geometry extraction is capped at {EXTRACT_BATCH} elements")
    if len(set(normalized)) != len(normalized):
        raise ValueError("element_ids must be unique")

    for field_name, value in (
        ("element_budget_ms", element_budget_ms),
        ("call_budget_ms", call_budget_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
        if value > 9_223_372_036_854_775_807:
            raise ValueError(f"{field_name} exceeds the C# Int64 range")

    detail_names = {
        "fine": "Fine",
        "medium": "Medium",
        "coarse": "Coarse",
    }
    if not isinstance(detail, str) or detail not in detail_names:
        raise ValueError("detail must be 'fine', 'medium', or 'coarse'")

    body = _GEOMETRY_EXTRACT_BODY_CS.replace(
        "__GX_ELEMENT_IDS__",
        ", ".join(_csharp_string(value) for value in normalized),
        1,
    )
    body = body.replace(
        "__GX_ELEMENT_BUDGET_MS__", str(element_budget_ms))
    body = body.replace("__GX_CALL_BUDGET_MS__", str(call_budget_ms))
    body = body.replace("__GX_DETAIL_ENUM__", detail_names[detail])
    body = body.replace("__GX_DETAIL_NAME__", detail)
    if "__GX_" in body:
        raise GeometryExtractionError(
            "internal geometry emitter placeholder was not resolved")
    return (source_binding_cs(link_title) + "\n"
            + GEOMETRY_EXTRACT_HELPER_CS + "\n" + body)
