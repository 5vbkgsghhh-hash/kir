"""Independent L3 form acceptance for Tier-G atom escrow.

The materializer knows what mesh it intends to send to ``create_directshape``;
the emitter knows what it observed inside its own transaction.  Neither is an
independent judge.  This module compares a pre-registered expectation with a
fresh :class:`GeometryExtraction` of the *created* ElementId.

The form predicate is deliberately stronger than a bounding-box check.  A mesh
is reduced to a sorted multiset of triangles whose three world-space vertices
are quantized on the frozen ``GEOM_CANON_MM`` grid.  Vertex numbering,
triangle order, and winding do not affect the digest; moving a vertex or
adding/removing a face does.  The predicate therefore checks the triangular
surface KIR actually materialized without pretending to recover BIM semantics.

No Revit call lives here.  Expectations and verdicts are frozen, serializable,
and content-addressed; a caller must obtain the observation through a separate
post-commit read before :func:`check_form_acceptance` can return ``accepted``.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from kukai.ir.decompile.geom_extract import (
    ExtractedGeometryTier,
    GeometryExtraction,
    GeometryExtractionError,
    canonical_mm,
    geometry_hash,
)
from kukai.ir.decompile.recompile import GmMesh
from kukai.ir.decompile.schema import GEOM_CANON_MM
from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES


FORM_ACCEPTANCE_SCHEMA_VERSION = "kir-form-acceptance/1"
_SHA256_LENGTH = 64


class FormAcceptanceError(ValueError):
    """A form expectation or observation violates the typed contract."""


class FormAcceptanceState(str, Enum):
    """Closed verdict of the independent post-commit form read."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class FormMismatchCode(str, Enum):
    """Machine-readable reasons an escrow form was not accepted."""

    OBSERVATION_MISSING = "observation_missing"
    GEOMETRY_UNAVAILABLE = "geometry_unavailable"
    CATEGORY_MISMATCH = "category_mismatch"
    TRIANGLE_COUNT_MISMATCH = "triangle_count_mismatch"
    BBOX_MISMATCH = "bbox_mismatch"
    SURFACE_MISMATCH = "surface_mismatch"


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(char in "0123456789abcdef" for char in value)
    )


def _digest(payload: Any) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FormAcceptanceError(
            f"form evidence is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def _point_units(point: tuple[float, float, float]) -> tuple[int, int, int]:
    """One point on the same frozen half-away-from-zero grid as Tier G."""

    return tuple(
        int(round(canonical_mm(value) / GEOM_CANON_MM))
        for value in point
    )  # type: ignore[return-value]


def mesh_surface_digest(mesh: GmMesh) -> str:
    """Order- and winding-independent digest of a world-space mesh surface."""

    if not isinstance(mesh, GmMesh):
        raise FormAcceptanceError("surface digest requires a validated GmMesh")
    vertices = tuple(_point_units(vertex) for vertex in mesh.vertices_mm)
    triangles = sorted(
        tuple(sorted((vertices[a], vertices[b], vertices[c])))
        for a, b, c in mesh.triangles
    )
    return _digest({
        "schema_version": FORM_ACCEPTANCE_SCHEMA_VERSION,
        "grid_mm": GEOM_CANON_MM,
        "triangles": triangles,
    })


def mesh_bbox_mm(mesh: GmMesh) -> tuple[float, float, float, float, float, float]:
    """Canonical world-space bounding box used for diagnostic evidence."""

    if not isinstance(mesh, GmMesh):
        raise FormAcceptanceError("bbox requires a validated GmMesh")
    xs = [canonical_mm(vertex[0]) for vertex in mesh.vertices_mm]
    ys = [canonical_mm(vertex[1]) for vertex in mesh.vertices_mm]
    zs = [canonical_mm(vertex[2]) for vertex in mesh.vertices_mm]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


@dataclass(frozen=True, slots=True)
class FormExpectation:
    """Pre-registered form predicate bound to one accepted typed plan."""

    source_id: str
    op_id: str
    program_index: int
    plan_digest: str
    source_geometry_hash: str
    materialized_geometry_hash: str
    surface_digest: str
    directshape_category: str
    geometry_tier: str
    triangle_count: int
    bbox_mm: tuple[float, float, float, float, float, float]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("op_id", self.op_id),
            ("geometry_tier", self.geometry_tier),
        ):
            if not isinstance(value, str) or not value:
                raise FormAcceptanceError(
                    f"FormExpectation.{field_name} must be non-empty")
        if (isinstance(self.program_index, bool)
                or not isinstance(self.program_index, int)
                or self.program_index < 0):
            raise FormAcceptanceError(
                "FormExpectation.program_index must be non-negative")
        for field_name, value in (
            ("plan_digest", self.plan_digest),
            ("source_geometry_hash", self.source_geometry_hash),
            ("materialized_geometry_hash", self.materialized_geometry_hash),
            ("surface_digest", self.surface_digest),
        ):
            if not _is_sha256(value):
                raise FormAcceptanceError(
                    f"FormExpectation.{field_name} must be SHA-256")
        if self.directshape_category not in DIRECTSHAPE_CATEGORIES:
            raise FormAcceptanceError(
                "FormExpectation directshape category is unsupported")
        if self.geometry_tier not in {"Gb", "Gm"}:
            raise FormAcceptanceError(
                "FormExpectation geometry tier must be Gb or Gm")
        if (isinstance(self.triangle_count, bool)
                or not isinstance(self.triangle_count, int)
                or self.triangle_count < 1):
            raise FormAcceptanceError(
                "FormExpectation triangle_count must be positive")
        if (not isinstance(self.bbox_mm, tuple) or len(self.bbox_mm) != 6
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(float(value))
                       for value in self.bbox_mm)):
            raise FormAcceptanceError(
                "FormExpectation bbox_mm must contain six numbers")
        if any(self.bbox_mm[index] > self.bbox_mm[index + 3]
               for index in range(3)):
            raise FormAcceptanceError(
                "FormExpectation bbox minima exceed maxima")

    @classmethod
    def from_mesh(
        cls,
        *,
        source_id: str,
        op_id: str,
        program_index: int,
        plan_digest: str,
        source_geometry_hash: str,
        directshape_category: str,
        geometry_tier: str,
        mesh: GmMesh,
    ) -> "FormExpectation":
        return cls(
            source_id=source_id,
            op_id=op_id,
            program_index=program_index,
            plan_digest=plan_digest,
            source_geometry_hash=source_geometry_hash,
            materialized_geometry_hash=geometry_hash(mesh),
            surface_digest=mesh_surface_digest(mesh),
            directshape_category=directshape_category,
            geometry_tier=geometry_tier,
            triangle_count=len(mesh.triangles),
            bbox_mm=mesh_bbox_mm(mesh),
        )

    @property
    def expected_built_in_category(self) -> str:
        return DIRECTSHAPE_CATEGORIES[self.directshape_category]

    @property
    def expectation_digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FORM_ACCEPTANCE_SCHEMA_VERSION,
            "source_id": self.source_id,
            "op_id": self.op_id,
            "program_index": self.program_index,
            "plan_digest": self.plan_digest,
            "source_geometry_hash": self.source_geometry_hash,
            "materialized_geometry_hash": self.materialized_geometry_hash,
            "surface_digest": self.surface_digest,
            "directshape_category": self.directshape_category,
            "expected_built_in_category": self.expected_built_in_category,
            "geometry_tier": self.geometry_tier,
            "triangle_count": self.triangle_count,
            "bbox_mm": list(self.bbox_mm),
        }


@dataclass(frozen=True, slots=True)
class FormObservation:
    """Geometry facts obtained from a separate read of the created element."""

    created_element_id: str
    category: str
    geometry_hash: str
    surface_digest: str
    triangle_count: int
    bbox_mm: tuple[float, float, float, float, float, float]

    def __post_init__(self) -> None:
        if not isinstance(self.created_element_id, str) \
                or not self.created_element_id:
            raise FormAcceptanceError(
                "FormObservation.created_element_id must be non-empty")
        if not isinstance(self.category, str) or not self.category:
            raise FormAcceptanceError(
                "FormObservation.category must be non-empty")
        if not _is_sha256(self.geometry_hash) \
                or not _is_sha256(self.surface_digest):
            raise FormAcceptanceError(
                "FormObservation hashes must be SHA-256")
        if (isinstance(self.triangle_count, bool)
                or not isinstance(self.triangle_count, int)
                or self.triangle_count < 1):
            raise FormAcceptanceError(
                "FormObservation triangle_count must be positive")
        if (not isinstance(self.bbox_mm, tuple) or len(self.bbox_mm) != 6
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(float(value))
                       for value in self.bbox_mm)):
            raise FormAcceptanceError(
                "FormObservation bbox_mm must contain six values")

    @property
    def observation_digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_element_id": self.created_element_id,
            "category": self.category,
            "geometry_hash": self.geometry_hash,
            "surface_digest": self.surface_digest,
            "triangle_count": self.triangle_count,
            "bbox_mm": list(self.bbox_mm),
        }


@dataclass(frozen=True, slots=True)
class FormMismatch:
    code: FormMismatchCode
    expected: Any
    observed: Any
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, FormMismatchCode):
            raise FormAcceptanceError("form mismatch code must be typed")
        if not isinstance(self.detail, str) or not self.detail:
            raise FormAcceptanceError("form mismatch detail must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "expected": self.expected,
            "observed": self.observed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class FormAcceptanceVerdict:
    """Immutable outcome; only an exact independent surface match accepts."""

    expectation: FormExpectation
    state: FormAcceptanceState
    created_element_id: str | None
    observation: FormObservation | None
    mismatches: tuple[FormMismatch, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.expectation, FormExpectation):
            raise FormAcceptanceError("verdict expectation must be typed")
        if not isinstance(self.state, FormAcceptanceState):
            raise FormAcceptanceError("form acceptance state must be typed")
        if self.created_element_id is not None and (
                not isinstance(self.created_element_id, str)
                or not self.created_element_id):
            raise FormAcceptanceError("created_element_id must be non-empty")
        if self.observation is not None and not isinstance(
                self.observation, FormObservation):
            raise FormAcceptanceError("verdict observation must be typed")
        if any(not isinstance(row, FormMismatch) for row in self.mismatches):
            raise FormAcceptanceError("verdict mismatches must be typed")
        if self.state is FormAcceptanceState.ACCEPTED:
            if self.observation is None or self.mismatches:
                raise FormAcceptanceError(
                    "accepted form needs an observation and no mismatches")
        elif not self.mismatches:
            raise FormAcceptanceError(
                "non-accepted form needs a named mismatch")

    @property
    def accepted(self) -> bool:
        return self.state is FormAcceptanceState.ACCEPTED

    @property
    def evidence_digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FORM_ACCEPTANCE_SCHEMA_VERSION,
            "expectation_digest": self.expectation.expectation_digest,
            "state": self.state.value,
            "source_id": self.expectation.source_id,
            "op_id": self.expectation.op_id,
            "plan_digest": self.expectation.plan_digest,
            "created_element_id": self.created_element_id,
            "observation": (
                self.observation.to_dict() if self.observation else None),
            "mismatches": [row.to_dict() for row in self.mismatches],
        }


def _inconclusive(
    expectation: FormExpectation,
    created_element_id: str | None,
    code: FormMismatchCode,
    detail: str,
    *,
    observed: Any = None,
) -> FormAcceptanceVerdict:
    return FormAcceptanceVerdict(
        expectation=expectation,
        state=FormAcceptanceState.INCONCLUSIVE,
        created_element_id=created_element_id,
        observation=None,
        mismatches=(FormMismatch(code, "Tier-G geometry", observed, detail),),
    )


def check_form_acceptance(
    expectation: FormExpectation,
    extraction: GeometryExtraction | None,
    *,
    created_element_id: str | None,
) -> FormAcceptanceVerdict:
    """Compare a pre-execution predicate with an independent geometry read."""

    if not isinstance(expectation, FormExpectation):
        raise FormAcceptanceError("check requires a FormExpectation")
    if not isinstance(created_element_id, str) or not created_element_id:
        return _inconclusive(
            expectation,
            None,
            FormMismatchCode.OBSERVATION_MISSING,
            "commit receipt did not bind the escrow op to a created ElementId",
        )
    if not isinstance(extraction, GeometryExtraction):
        return _inconclusive(
            expectation,
            created_element_id,
            FormMismatchCode.OBSERVATION_MISSING,
            "no typed post-commit GeometryExtraction was supplied",
        )
    try:
        record = extraction.entry_for(created_element_id)
    except GeometryExtractionError as exc:
        failure = next(
            (row for row in extraction.failures
             if row.element_id == created_element_id),
            None,
        )
        return _inconclusive(
            expectation,
            created_element_id,
            FormMismatchCode.GEOMETRY_UNAVAILABLE,
            f"created element geometry is unavailable: {type(exc).__name__}",
            observed=(failure.to_dict() if failure is not None else None),
        )
    if record.tier is ExtractedGeometryTier.A:
        return _inconclusive(
            expectation,
            created_element_id,
            FormMismatchCode.GEOMETRY_UNAVAILABLE,
            "created element re-read returned Tier A without geometry",
            observed=record.tier.value,
        )
    try:
        mesh = extraction.world_fallback_mesh_for_record(record)
    except GeometryExtractionError as exc:
        return _inconclusive(
            expectation,
            created_element_id,
            FormMismatchCode.GEOMETRY_UNAVAILABLE,
            f"created element world mesh is invalid: {type(exc).__name__}",
        )
    assert record.geo_hash is not None
    observation = FormObservation(
        created_element_id=created_element_id,
        category=record.category,
        geometry_hash=record.geo_hash,
        surface_digest=mesh_surface_digest(mesh),
        triangle_count=len(mesh.triangles),
        bbox_mm=mesh_bbox_mm(mesh),
    )
    mismatches: list[FormMismatch] = []
    if observation.category != expectation.expected_built_in_category:
        mismatches.append(FormMismatch(
            FormMismatchCode.CATEGORY_MISMATCH,
            expectation.expected_built_in_category,
            observation.category,
            "post-commit element category differs from the compiled category",
        ))
    if observation.triangle_count != expectation.triangle_count:
        mismatches.append(FormMismatch(
            FormMismatchCode.TRIANGLE_COUNT_MISMATCH,
            expectation.triangle_count,
            observation.triangle_count,
            "post-commit mesh has a different number of triangles",
        ))
    if observation.bbox_mm != expectation.bbox_mm:
        mismatches.append(FormMismatch(
            FormMismatchCode.BBOX_MISMATCH,
            list(expectation.bbox_mm),
            list(observation.bbox_mm),
            "post-commit world-space bounding box differs on the frozen grid",
        ))
    if observation.surface_digest != expectation.surface_digest:
        mismatches.append(FormMismatch(
            FormMismatchCode.SURFACE_MISMATCH,
            expectation.surface_digest,
            observation.surface_digest,
            "post-commit triangular surface differs on the frozen grid",
        ))
    return FormAcceptanceVerdict(
        expectation=expectation,
        state=(FormAcceptanceState.REJECTED
               if mismatches else FormAcceptanceState.ACCEPTED),
        created_element_id=created_element_id,
        observation=observation,
        mismatches=tuple(mismatches),
    )


__all__ = [
    "FORM_ACCEPTANCE_SCHEMA_VERSION",
    "FormAcceptanceError",
    "FormAcceptanceState",
    "FormAcceptanceVerdict",
    "FormExpectation",
    "FormMismatch",
    "FormMismatchCode",
    "FormObservation",
    "check_form_acceptance",
    "mesh_bbox_mm",
    "mesh_surface_digest",
]
