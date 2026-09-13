"""Translation deviation: ONE source against MANY derived bodies.

🔴 WHY THIS WAS SET UP, AND THIS IS A MEASUREMENT, NOT A DESIGN INTENT. The
detailing record (`kir/project_refinement.py`) names the untranslated
remainder IN WORDS: for `tower-a` this is exactly two lines —
`concept_twist_removed` and `concept_top_taper_removed` — and
`refinement_view` itself prints about them `roles_and_losses:
authored_assertions` and `loss_inventory: not_proven_exhaustive`. The
measurement of 07.09.2026 (`refine-loop/RECON-deviation.md`) showed what
these two words cost: the twist — **8.97 %** of the concept's volume
(symmetric difference of 1.0068e+11 mm³), the top taper — **20.37 %**
(2.3025e+11 mm³). The word "loss" does not distinguish 0.1 % from 20 %, and
the reader cannot tell them apart either.

🔴 WHAT IS A NUMBER HERE, AND WHAT IS ONLY A BOUND. The volume of the
remainder and the excess is a NUMBER: a check against a closed-form formula
(circle against a regular N-gon) gave a relative discrepancy of
8.1e-16 … 5.6e-14 across eight pairs. The maximum SURFACE deviation is NOT a
number, and that too is a measurement, not caution:

* `BRepExtrema_DistShapeShape` between the shells returned **0.0 in all
  eight** cases (it measures the MINIMUM, and the shells touch along shared
  faces);
* `BRepExtrema_ShapeProximity.Proximity()` returned **0.0** in the same
  cases, and on the loft — 1500.0 against a declared 2000, not moving at
  any of the five `SetNbSamples` values (0 · 10 · 100 · 1000 · 5000);
* sampling by TRIANGULATION NODES is biased by construction: the mesher
  places nodes where curvature demands it, not where the bodies diverge —
  it gave 0.0000 where the oracle gives 190.3012;
* a uniform grid INSIDE the remainder zone converges FROM BELOW and
  NON-MONOTONICALLY: steps of 200/50/20 mm gave 145.81 / 184.78 / 187.95
  against an oracle of 190.3012, while on another zone a step of 200 gave
  the exact 21.3878, whereas a step of 50 gave 17.72.

That is why `max_deviation` is printed ONLY together with the method, the
step, and the `converges_from_below=True` mark, and no consumer has the
right to read it as "the deviation equals". The upper bound is the zone's
bounding box, printed alongside it.

🔴 WHY THE WITNESS IS MANDATORY. `BRepAlgoAPI_Common` can return an empty
result with `IsDone() == True` (all three towers in the example), while
`Cut` in the same case returns the WHOLE argument — and "coverage 0 %,
remainder = whole body" looks like an honest number. Volume additivity
does not catch the defect (2.2e-16 … 1.1e-10). Only an independent point
counter catches it, and it is called from ONE place — `clash.exact`.

🔴 WHAT THIS MODULE DOES NOT DO. It does not read storage, does not edit
the project, does not guess BIM meaning, does not introduce its own
primitives, and does not extend the kernel: only OCP calls through one
door. It TAKES the thickness and height of bodies FROM OPS AND TYPES, and
where these are absent, it refuses BY NAME rather than substituting a
constant.
"""
from __future__ import annotations

import hashlib
import json
import re

import math
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from kir.clash.exact import (DEFAULT_POLICY, IDENTITY_FRAME, ExactRefusal,
                             TolerancePolicy, _kernel as _exact_kernel, _placed,
                             _validated_frame, _volume, has_curved_faces,
                             witness_common)

#: Report schema. Changes together with the set of fields.
DEVIATION_SCHEMA = "kir-refinement-deviation/1"

#: The only basis that the module issues.
DEVIATION_BASIS = "occt_cut_fuse_v1"

#: Closed list of refusals. "Other" here would mean the reason is not named.
REFUSALS = (
    "kernel_unavailable",           # OCP is unavailable
    "boolean_not_done",             # IsDone() == False
    "boolean_contradicts_witness",  # the boolean returned empty/everything, yet the points are shared
    "source_has_no_body",           # the source has no body (today — the whole concept)
    "derived_has_no_body",          # the derived output has no body (level, room, type)
    "degenerate_body",              # volume is not positive
    "null_shape",                   # empty shape
    "mirrored_frame",               # det = −1
    "invalid_frame",                # not 4×4 / not rigid
    "max_deviation_not_bounded",    # point ceiling exhausted before convergence
    "deviation_budget_exhausted",   # work ceiling per run
    "plan_contour_unusable",        # the floor contour is not readable by shapely
)

#: Refusal → dispatcher code. A dictionary, not a prefix: each one carries
#: its own repair promise, and `kir.diag` must know every issued code by
#: name.
REFUSAL_CODES: dict[str, str] = {
    "kernel_unavailable": "KIR-R004",
    "boolean_not_done": "KIR-R005",
    "boolean_contradicts_witness": "KIR-R006",
    "source_has_no_body": "KIR-R007",
    "derived_has_no_body": "KIR-R008",
    "degenerate_body": "KIR-R009",
    "null_shape": "KIR-R010",
    "mirrored_frame": "KIR-R011",
    "invalid_frame": "KIR-R012",
    "max_deviation_not_bounded": "KIR-R013",
    "deviation_budget_exhausted": "KIR-R014",
    "plan_contour_unusable": "KIR-R015",
}

#: The direction the floor grows from its level. This is ABSENT from the
#: op in any form: `create_floor_by_contour` carries the contour and a
#: reference to the level, the type carries the thickness, and nobody
#: carries the SIDE. The value is declared here and printed in the report
#: (`declared`), so the reader sees that this is a CHOICE, not a
#: measurement.
FLOOR_GROWS = "down"

#: Ceiling on grid points for the maximum-deviation estimate, per run.
MAX_DEVIATION_POINTS = 40_000

#: Below this fraction of the source volume, a remainder zone is not
#: addressed by name: a boolean operation can produce arithmetic dust, and
#: printing it as a "remainder" would drown out the real zones. The dust
#: does not disappear — it is carried off as the `residue_dust_mm3` number
#: and a counter, not as separate lines.
DUST_RELATIVE = 1e-9


class DeviationRefusal(ValueError):
    """Named measurement refusal; carries a code from `REFUSALS`."""

    def __init__(self, code: str, message: str, address: str | None = None):
        if code not in REFUSALS:
            raise AssertionError(f"{code}: отказ вне закрытого списка REFUSALS")
        self.code = code
        self.address = address
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ResidueBody:
    """One zone of untranslated remainder: a number WITH AN ADDRESS, not a flag."""

    zone_id: str
    address: str
    volume_mm3: float
    centroid_mm: tuple[float, float, float]
    bbox_mm: tuple[float, float, float, float, float, float]
    nearest_derived: str | None = None
    gap_to_nearest_mm: float | None = None

    @property
    def bbox_span_mm(self) -> tuple[float, float, float]:
        """The zone's bounding box. An UPPER bound on the deviation — unlike the grid."""
        x0, y0, z0, x1, y1, z1 = self.bbox_mm
        return (x1 - x0, y1 - y0, z1 - z0)

    def to_dict(self) -> dict[str, Any]:
        return {"zone_id": self.zone_id, "address": self.address,
                "volume_mm3": self.volume_mm3,
                "centroid_mm": list(self.centroid_mm),
                "bbox_mm": list(self.bbox_mm),
                "bbox_span_mm": list(self.bbox_span_mm),
                "nearest_derived": self.nearest_derived,
                "gap_to_nearest_mm": self.gap_to_nearest_mm}


@dataclass(frozen=True)
class MaxDeviation:
    """Estimate of the maximum deviation. A LOWER bound, and the field says so."""

    value_mm: float | None
    method: str
    step_mm: float | None
    converges_from_below: bool
    points_inside: int
    points_tried: int
    at_mm: tuple[float, float, float] | None = None
    upper_bound_mm: float | None = None
    refusal: str | None = None

    def __post_init__(self) -> None:
        if self.method != "grid":
            raise AssertionError("метод оценки называется 'grid' и никак иначе")
        if not self.converges_from_below:
            raise AssertionError(
                "оценка сеткой сходится СНИЗУ: замер 200/50/20 мм дал "
                "145.81/184.78/187.95 при оракуле 190.3012 — поле не выключается")
        if self.refusal is not None and self.refusal not in REFUSALS:
            raise AssertionError("refusal вне закрытого списка REFUSALS")

    def to_dict(self) -> dict[str, Any]:
        return {"value_mm": self.value_mm, "method": self.method,
                "step_mm": self.step_mm,
                "converges_from_below": self.converges_from_below,
                "points_inside": self.points_inside, "points_tried": self.points_tried,
                "at_mm": None if self.at_mm is None else list(self.at_mm),
                "upper_bound_mm": self.upper_bound_mm, "refusal": self.refusal}


@dataclass(frozen=True)
class DeviationReport:
    """Outcome of the measurement. A refusal is an outcome just like a number."""

    source_address: str
    source_volume_mm3: float | None
    derived_volume_mm3: float | None
    residue: tuple[ResidueBody, ...]
    residue_volume_mm3: float | None
    residue_dust_mm3: float
    residue_dust_zones: int
    excess_mm3: float | None
    coverage: float | None
    max_deviation: MaxDeviation
    plan_area_delta_mm2: dict[str, float] | None
    refusals: tuple[dict[str, Any], ...]
    tolerance_policy_digest: str
    cost_ms: float
    declared: dict[str, Any] = field(default_factory=dict)
    schema_version: str = DEVIATION_SCHEMA
    basis: str = DEVIATION_BASIS

    def __post_init__(self) -> None:
        for row in self.refusals:
            if row.get("code") not in REFUSALS:
                raise AssertionError(f"{row.get('code')}: отказ вне REFUSALS")
            if row.get("diag") != REFUSAL_CODES[row["code"]]:
                raise AssertionError(f"{row.get('code')}: код распорядителя не тот")
        if self.coverage is not None and not (-1e-9 <= self.coverage <= 1.0 + 1e-9):
            raise AssertionError(f"покрытие вне [0, 1]: {self.coverage}")

    @property
    def ok(self) -> bool:
        """The number was obtained. Named omissions of derivatives do not cancel this."""
        return self.coverage is not None

    def refusal_codes(self) -> tuple[str, ...]:
        return tuple(sorted({row["code"] for row in self.refusals}))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "basis": self.basis,
                "source_address": self.source_address,
                "source_volume_mm3": self.source_volume_mm3,
                "derived_volume_mm3": self.derived_volume_mm3,
                "residue": [item.to_dict() for item in self.residue],
                "residue_volume_mm3": self.residue_volume_mm3,
                "residue_dust_mm3": self.residue_dust_mm3,
                "residue_dust_zones": self.residue_dust_zones,
                "excess_mm3": self.excess_mm3, "coverage": self.coverage,
                "max_deviation": self.max_deviation.to_dict(),
                "plan_area_delta_mm2": self.plan_area_delta_mm2,
                "refusals": [dict(row) for row in self.refusals],
                "tolerance_policy_digest": self.tolerance_policy_digest,
                "cost_ms": self.cost_ms, "declared": dict(self.declared)}


# ───────────────────────────────────────────────────────────────── kernel

def _kernel():
    """This module's set: the `clash.exact` kernel plus CONSTRUCTION classes.

    🔴 "ONE DOOR PER MODULE" — WHAT WAS WRITTEN HERE BEFORE, AND IT WAS A
    MISTAKE (fix of 07.09.2026). One line below stood its own `from OCP...`,
    that is, a THIRD exit from the kernel to a foreign package bypassing the
    version pin; the closed list
    (`test_kir_boundary_to_the_product_is_a_closed_list`) named it
    `refine/deviation.py -> OCP (soft)` alongside two neighbors. There is
    one door for the WHOLE TREE — `kir.occt_geometry._kernel` — and this
    set only PULLS construction names from it: pair analysis lives with
    the neighbor, body assembly lives here.

    The refusal HAS NOT CHANGED HERE, and that is stated by a number, not
    by hope: `_exact_kernel()` is called FIRST both before and after the
    fix, so without a profile the neighbor's `ExactRefusal("kernel_unavailable")`
    still arrives here — caught by lines 722 and 742 of this same file.
    `DeviationRefusal("kernel_unavailable")` remains reserved for a refusal
    of the door itself, if it is called before the neighbor.
    """
    from kir.occt_geometry import GeometryRefusal, _kernel as _occt_kernel

    k = _exact_kernel()
    try:
        occt = _occt_kernel()
    except GeometryRefusal as exc:                             # pragma: no cover
        raise DeviationRefusal("kernel_unavailable",
                               "установите kir-building[geometry]") from exc
    from types import SimpleNamespace
    extra = {
        "BRepAlgoAPI_Cut": occt.BRepAlgoAPI.BRepAlgoAPI_Cut,
        "BRepAlgoAPI_Fuse": occt.BRepAlgoAPI.BRepAlgoAPI_Fuse,
        "BRepBuilderAPI_MakeFace": occt.BRepBuilderAPI.BRepBuilderAPI_MakeFace,
        "BRepBuilderAPI_MakePolygon": occt.BRepBuilderAPI.BRepBuilderAPI_MakePolygon,
        "BRepBuilderAPI_MakeVertex": occt.BRepBuilderAPI.BRepBuilderAPI_MakeVertex,
        "BRepPrimAPI_MakePrism": occt.BRepPrimAPI.BRepPrimAPI_MakePrism,
        "TopTools_ListOfShape": occt.TopTools.TopTools_ListOfShape,
        "gp_Vec": occt.gp.gp_Vec,
    }
    return SimpleNamespace(**{**k.__dict__, **extra})


def _boolean(kind: str, arguments, tools, k, *, fuzzy: float):
    op = {"cut": k.BRepAlgoAPI_Cut, "fuse": k.BRepAlgoAPI_Fuse,
          "common": k.BRepAlgoAPI_Common}[kind]()
    left, right = k.TopTools_ListOfShape(), k.TopTools_ListOfShape()
    for shape in (arguments if isinstance(arguments, (list, tuple)) else [arguments]):
        left.Append(shape)
    for shape in (tools if isinstance(tools, (list, tuple)) else [tools]):
        right.Append(shape)
    op.SetArguments(left)
    op.SetTools(right)
    op.SetNonDestructive(True)
    if fuzzy:
        op.SetFuzzyValue(float(fuzzy))
    op.Build()
    if not op.IsDone():
        raise DeviationRefusal("boolean_not_done", f"{kind}: OCCT не завершил построение")
    return op.Shape()


def _solids(shape, k) -> list:
    out = []
    explorer = k.TopExp_Explorer(shape, k.TopAbs_SOLID)
    while explorer.More():
        out.append(explorer.Current())
        explorer.Next()
    return out


def _bbox(shape, k):
    box = k.Bnd_Box()
    solids = _solids(shape, k)
    for solid in (solids or [shape]):
        k.BRepBndLib.AddOptimal_s(solid, box, False, False)
    if box.IsVoid():
        return None
    return tuple(round(float(v), 6) for v in box.Get())


def _centroid(shape, k) -> tuple[float, float, float]:
    props = k.GProp_GProps()
    k.BRepGProp.VolumeProperties_s(shape, props)
    point = props.CentreOfMass()
    return (round(point.X(), 6), round(point.Y(), 6), round(point.Z(), 6))


def _distance(a, b, k) -> float | None:
    try:
        probe = k.BRepExtrema_DistShapeShape(a, b)
        if not probe.IsDone():
            return None
        return float(probe.Value())
    except Exception:                                          # noqa: BLE001
        return None


# ────────────────────────────────────── witness on top of the boolean operation

def _witness_says_they_meet(a, b, k, *, policy: TolerancePolicy) -> tuple[int, int]:
    """`(shared points, queried)`. Called ONLY for a curved face."""
    if not (has_curved_faces(a, k) or has_curved_faces(b, k)):
        return 0, 0
    return witness_common(a, b, k, grid_n=policy.witness_grid_n)


def _check_cut_against_witness(source, tool, cut_volume, source_volume, k, *,
                               policy: TolerancePolicy, what: str) -> None:
    """`Cut` returned the WHOLE argument — meaning the bodies do not touch. Is that so?

    The same ailment as an empty `Common`, only from the other side: the
    measurement gave `Cut(loft12, prism)` = 1.1224245963947e+12 against
    `V(loft)` = 1.1224245963881e+12, i.e. "nothing was subtracted" — while
    the intersection is 99 % of the volume.
    """
    if source_volume <= 0.0:
        return
    if (source_volume - cut_volume) / source_volume > policy.containment_relative:
        return
    both, tried = _witness_says_they_meet(source, tool, k, policy=policy)
    if both > 0:
        raise DeviationRefusal(
            "boolean_contradicts_witness",
            f"{what}: вычлось {source_volume - cut_volume:.6g} мм³ из "
            f"{source_volume:.6g}, а свидетель нашёл {both} общих точек из {tried} "
            f"(сетка {policy.witness_grid_n}³)")


# ─────────────────────────────────────────────── maximum deviation

def _grid_max_deviation(zones, opposite_shell, k, *, step_mm: float,
                        point_budget: int) -> MaxDeviation:
    """Maximum distance from a point INSIDE the zone to the opposite shell.

    The instrument declares its own method, its own step, and its own
    direction of convergence. None of the three can be derived from the
    answer, and staying silent about them would be a falsehood.
    """
    worst, where, inside, tried = 0.0, None, 0, 0
    upper = 0.0
    for zone in zones:
        box = k.Bnd_Box()
        k.BRepBndLib.AddOptimal_s(zone, box, False, False)
        if box.IsVoid():
            continue
        x0, y0, z0, x1, y1, z1 = box.Get()
        upper = max(upper, math.dist((x0, y0, z0), (x1, y1, z1)))
        classifier = k.BRepClass3d_SolidClassifier(zone)
        nx = max(1, int((x1 - x0) / step_mm))
        ny = max(1, int((y1 - y0) / step_mm))
        nz = max(1, int((z1 - z0) / step_mm))
        for i in range(nx):
            for j in range(ny):
                for m in range(nz):
                    if tried >= point_budget:
                        return MaxDeviation(
                            value_mm=round(worst, 6) if inside else None,
                            method="grid", step_mm=step_mm, converges_from_below=True,
                            points_inside=inside, points_tried=tried,
                            at_mm=where, upper_bound_mm=round(upper, 6),
                            refusal="max_deviation_not_bounded")
                    point = k.gp_Pnt(x0 + (i + .5) * (x1 - x0) / nx,
                                     y0 + (j + .5) * (y1 - y0) / ny,
                                     z0 + (m + .5) * (z1 - z0) / nz)
                    tried += 1
                    classifier.Perform(point, 1e-7)
                    if classifier.State() == k.TopAbs_OUT:
                        continue
                    inside += 1
                    vertex = k.BRepBuilderAPI_MakeVertex(point).Vertex()
                    probe = k.BRepExtrema_DistShapeShape(vertex, opposite_shell)
                    probe.Perform()
                    if probe.IsDone() and probe.Value() > worst:
                        worst = float(probe.Value())
                        where = (round(point.X(), 3), round(point.Y(), 3),
                                 round(point.Z(), 3))
    return MaxDeviation(value_mm=round(worst, 6) if inside else None, method="grid",
                        step_mm=step_mm, converges_from_below=True,
                        points_inside=inside, points_tried=tried, at_mm=where,
                        upper_bound_mm=round(upper, 6) if upper else None,
                        refusal=None if inside else "max_deviation_not_bounded")


# ──────────────────────────────────────────── bodies from ops and types

def _layer_thickness(operation: Mapping[str, Any]) -> float | None:
    """Type thickness = sum of DECLARED layers. Not a single constant."""
    layers = operation.get("layers")
    if not isinstance(layers, (list, tuple)) or not layers:
        return None
    total = 0.0
    for layer in layers:
        if not isinstance(layer, Mapping):
            return None
        width = layer.get("width_mm")
        if not isinstance(width, (int, float)) or isinstance(width, bool):
            return None
        total += float(width)
    return total if total > 0.0 else None


def _ref(value: Any) -> str | None:
    if isinstance(value, Mapping) and value.get("by") == "ref":
        target = value.get("value")
        return target if isinstance(target, str) else None
    return None


def _polygon_prism(points, z0: float, z1: float, k):
    polygon = k.BRepBuilderAPI_MakePolygon()
    for point in points:
        polygon.Add(k.gp_Pnt(float(point[0]), float(point[1]), float(z0)))
    polygon.Close()
    if not polygon.IsDone():
        return None
    face = k.BRepBuilderAPI_MakeFace(polygon.Wire())
    if not face.IsDone():
        return None
    prism = k.BRepPrimAPI_MakePrism(face.Face(), k.gp_Vec(0.0, 0.0, float(z1 - z0)))
    return prism.Shape() if prism.IsDone() else None


def bodies_from_ops(ops: Sequence[Mapping[str, Any]], *,
                    floor_grows: str = FLOOR_GROWS,
                    kernel=None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Section ops -> `({op_id: body}, [named omissions])`.

    🔴 THICKNESS AND HEIGHT ARE TAKEN FROM OPS AND TYPES, NOT FROM THIN AIR.
    A wall carries `height_mm` and a `type: {by: ref}` reference; the
    thickness is carried by `create_wall_type` as the sum of layers (in the
    example tree, 15 + 200 + 15 = 230 for the wall and 200 + 50 + 10 = 260
    for the floor — exactly the numbers found in the type names
    `KIR_Section_Wall_230` and `KIR_Section_Floor_260`). The level gives
    the `elev_mm` elevation. Whatever is absent from both the op and the
    type does NOT APPEAR here: the level, the room, and the type itself
    have no body, and each is named by the `derived_has_no_body` refusal
    rather than silently skipped — otherwise coverage would be computed
    against an arbitrary denominator.
    """
    k = kernel or _kernel()
    if floor_grows not in ("down", "up"):
        raise ValueError("floor_grows: 'down' или 'up'")
    thickness: dict[str, float] = {}
    elevation: dict[str, float] = {}
    for operation in ops:
        name = operation.get("op")
        identifier = operation.get("id")
        if not isinstance(identifier, str):
            continue
        if name in ("create_wall_type", "create_floor_type"):
            value = _layer_thickness(operation)
            if value is not None:
                thickness[identifier] = value
        elif name == "create_level":
            value = operation.get("elev_mm")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                elevation[identifier] = float(value)

    bodies: dict[str, Any] = {}
    missing: list[dict[str, Any]] = []

    def skip(identifier: str, why: str) -> None:
        missing.append({"code": "derived_has_no_body",
                        "diag": REFUSAL_CODES["derived_has_no_body"],
                        "address": identifier, "detail": why})

    for operation in ops:
        name = operation.get("op")
        identifier = operation.get("id")
        if not isinstance(identifier, str):
            continue
        if name not in ("create_wall", "create_floor_by_contour"):
            skip(identifier, f"{name}: операция не несёт тела")
            continue
        type_id = _ref(operation.get("type"))
        width = thickness.get(type_id) if type_id else None
        if width is None:
            skip(identifier, f"{name}: толщина не выводится из типа "
                             f"{type_id or 'не назван'} (нет слоёв с width_mm)")
            continue
        level_id = _ref(operation.get("level"))
        base = elevation.get(level_id) if level_id else None
        if base is None:
            skip(identifier, f"{name}: отметка не выводится из уровня "
                             f"{level_id or 'не назван'}")
            continue
        if name == "create_wall":
            height = operation.get("height_mm")
            p0, p1 = operation.get("p0_mm"), operation.get("p1_mm")
            if (not isinstance(height, (int, float)) or isinstance(height, bool)
                    or not isinstance(p0, (list, tuple)) or not isinstance(p1, (list, tuple))):
                skip(identifier, "create_wall: нет высоты или оси")
                continue
            dx, dy = float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])
            length = math.hypot(dx, dy)
            if length <= 0.0:
                skip(identifier, "create_wall: нулевая длина оси")
                continue
            nx, ny = -dy / length * width / 2.0, dx / length * width / 2.0
            quad = [(float(p0[0]) + nx, float(p0[1]) + ny),
                    (float(p1[0]) + nx, float(p1[1]) + ny),
                    (float(p1[0]) - nx, float(p1[1]) - ny),
                    (float(p0[0]) - nx, float(p0[1]) - ny)]
            body = _polygon_prism(quad, base, base + float(height), k)
            if body is None:
                skip(identifier, "create_wall: тело не построилось")
                continue
            bodies[identifier] = body
            continue
        contour = operation.get("contour")
        if not isinstance(contour, Mapping):
            skip(identifier, "create_floor_by_contour: нет контура")
            continue
        outer = (contour.get("outer") or {}).get("points_mm")
        if not isinstance(outer, (list, tuple)) or len(outer) < 3:
            skip(identifier, "create_floor_by_contour: внешний контур не читается")
            continue
        top = base if floor_grows == "down" else base + width
        bottom = base - width if floor_grows == "down" else base
        slab = _polygon_prism(outer, bottom, top, k)
        if slab is None:
            skip(identifier, "create_floor_by_contour: тело не построилось")
            continue
        for hole in (contour.get("holes") or ()):
            points = (hole or {}).get("points_mm")
            if not isinstance(points, (list, tuple)) or len(points) < 3:
                continue
            cutter = _polygon_prism(points, bottom - 10.0, top + 10.0, k)
            if cutter is None:
                continue
            slab = _boolean("cut", slab, cutter, k, fuzzy=DEFAULT_POLICY.fuzzy_mm)
        bodies[identifier] = slab
    return bodies, missing


# ──────────────────────────────────────────────── plan area by floor

#: The rule for the area of a self-intersecting contour is ONE, and pinned.
#: `buffer(0)` resolves self-intersection by parity and returns the body's
#: area. `make_valid` is DELIBERATELY FORBIDDEN: on the same scene it
#: returns a `GeometryCollection` with an area of 126 000 000 mm² where the
#: body actually occupies 106 500 000, because it adds degenerate pieces
#: together with the polygons. Two rules would give two different "honest"
#: numbers — that is worse than none.
SELF_INTERSECTION_RULE = "buffer(0)"

_AT_MM = re.compile(r"\[\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
                    r"\s+(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*\]")


def _intersection_at(polygon) -> list[float] | None:
    """The location shapely complains about: `Self-intersection[7500 9000]` -> a point."""
    try:
        from shapely.validation import explain_validity
    except Exception:                                          # pragma: no cover
        return None
    match = _AT_MM.search(str(explain_validity(polygon)))
    return [float(match.group(1)), float(match.group(2))] if match else None


def _explain(polygon) -> str:
    try:
        from shapely.validation import explain_validity
        return str(explain_validity(polygon))
    except Exception:                                          # pragma: no cover
        return "самопересечение (место не названо: explain_validity недоступен)"


def plan_areas(ops: Sequence[Mapping[str, Any]]
               ) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Plan area BY LEVEL for one side of the comparison + named
    disturbances.

    🔴 SELF-INTERSECTION WAS EATING THE WHOLE MEASURE. The previous edition,
    on an invalid polygon, raised the `plan_contour_unusable` refusal and
    skipped the floor; the "atrium to the wall" fix makes ALL three floors
    invalid at once (the hole touches the outer ring), and the report
    returned `measure: None` — that is, an absent measure where the body is
    perfectly well defined. The address named in that case was the wrong
    one: the LEVEL, rather than the location of the intersection.

    Now a disturbance and a refusal are DIFFERENT things. A disturbance
    (`note: self_intersecting`) carries the area, the rule by which it was
    obtained, and the COORDINATE of the intersection. A refusal
    (`code: plan_contour_unusable`) remains reserved for cases where there
    is nothing left to read: a contour shorter than three points, or where
    `buffer(0)` leaves no area at all.
    """
    try:
        from shapely.geometry import Polygon
    except ImportError as exc:                                 # pragma: no cover
        raise DeviationRefusal("plan_contour_unusable", "shapely недоступен") from exc

    out: dict[str, float] = {}
    bad: list[dict[str, Any]] = []
    for operation in ops:
        if operation.get("op") != "create_floor_by_contour":
            continue
        identifier = operation.get("id")
        level = _ref(operation.get("level")) or f"unbound:{identifier}"
        contour = operation.get("contour") or {}
        outer = (contour.get("outer") or {}).get("points_mm")
        if not isinstance(outer, (list, tuple)) or len(outer) < 3:
            bad.append({"code": "plan_contour_unusable",
                        "diag": REFUSAL_CODES["plan_contour_unusable"],
                        "address": level, "detail": "внешний контур не читается"})
            continue
        holes = []
        for hole in (contour.get("holes") or ()):
            points = (hole or {}).get("points_mm")
            if isinstance(points, (list, tuple)) and len(points) >= 3:
                holes.append([(float(p[0]), float(p[1])) for p in points])
        polygon = Polygon([(float(p[0]), float(p[1])) for p in outer], holes)
        if polygon.is_valid:
            out[level] = out.get(level, 0.0) + float(polygon.area)
            continue
        resolved = polygon.buffer(0)
        area = float(getattr(resolved, "area", 0.0) or 0.0)
        if area <= 0.0:
            bad.append({"code": "plan_contour_unusable",
                        "diag": REFUSAL_CODES["plan_contour_unusable"],
                        "address": level,
                        "detail": f"контур не читается и {SELF_INTERSECTION_RULE} "
                                  "не оставил площади"})
            continue
        bad.append({"note": "self_intersecting", "address": level, "op_id": identifier,
                    "rule": SELF_INTERSECTION_RULE, "area_mm2": area,
                    "at_mm": _intersection_at(polygon), "detail": _explain(polygon)})
        out[level] = out.get(level, 0.0) + area
    return out, bad


#: Volume memo: assembling bodies costs ~0.9 s per section, and one report
#: asks for it twice (baseline and post-fix state), and does so on EVERY
#: call. Measurement of 07.09.2026: the refinement regression grew from
#: 29 to 95 s. The key is a digest of the OPS THEMSELVES, so the memo
#: cannot hand out someone else's number: different ops — different key.
#: The capacity is deliberately small: this is a speedup inside one run,
#: not a store.
_VOLUME_MEMO: dict[str, tuple[float | None, tuple[str, ...]]] = {}
_VOLUME_MEMO_MAX = 64


def _ops_digest(ops) -> str:
    return hashlib.sha256(json.dumps(list(ops), sort_keys=True, default=str,
                                     ensure_ascii=False).encode()).hexdigest()


def section_volume_mm3(ops: Sequence[Mapping[str, Any]]
                       ) -> tuple[float | None, list[str]]:
    """Volume of the section's bodies. No kernel — a NAMED limit, not zero."""
    key = _ops_digest(ops)
    remembered = _VOLUME_MEMO.get(key)
    if remembered is not None:
        return remembered[0], list(remembered[1])
    volume, limits = _section_volume_mm3(ops)
    if len(_VOLUME_MEMO) >= _VOLUME_MEMO_MAX:
        _VOLUME_MEMO.clear()
    _VOLUME_MEMO[key] = (volume, tuple(limits))
    return volume, limits


def _section_volume_mm3(ops):
    limits: list[str] = []
    try:
        bodies, missing = bodies_from_ops(ops)
    except Exception as exc:                                   # noqa: BLE001
        code = getattr(exc, "code", type(exc).__name__)
        return None, [f"volume not measured: {code}: {str(exc)[:120]}"]
    try:
        k = _kernel()
        total = 0.0
        for shape in bodies.values():
            props = k.GProp_GProps()
            k.BRepGProp.VolumeProperties_s(shape, props)
            total += float(props.Mass())
    except Exception as exc:                                   # noqa: BLE001
        return None, [f"volume not measured: {type(exc).__name__}: {str(exc)[:120]}"]
    if missing:
        limits.append(f"volume: {len(missing)} operations carry no body")
    return total, limits


def plan_area_delta(ops_before: Sequence[Mapping[str, Any]],
                    ops_after: Sequence[Mapping[str, Any]]
                    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Change in plan area BY FLOOR, `shapely`. The key is the level
    reference.

    🔴 WHY THE KEY IS THE LEVEL, NOT THE FLOOR'S `op_id`. In this tree, an
    operation's identifier is a DIGEST OF ITS PAYLOAD: editing the contour
    changes it, and a "before/after" comparison keyed on it would be
    comparing a floor against nothing. The level's payload is untouched by
    the atrium edit, so its id is stable and serves as the address.
    """
    try:
        from shapely.geometry import Polygon
    except ImportError as exc:                                 # pragma: no cover
        raise DeviationRefusal("plan_contour_unusable",
                               "shapely недоступен") from exc

    before, bad_before = plan_areas(ops_before)
    after, bad_after = plan_areas(ops_after)
    problems = list(bad_before) + list(bad_after)
    delta: dict[str, float] = {}
    for level in sorted(set(before) | set(after)):
        if level not in before or level not in after:
            problems.append({"code": "plan_contour_unusable",
                             "diag": REFUSAL_CODES["plan_contour_unusable"],
                             "address": level,
                             "detail": "этаж есть только на одной стороне сверки"})
            continue
        delta[level] = after[level] - before[level]
    return delta, problems


# ─────────────────────────────────────────────────────── main entry point

def measure_refinement(source_shape, derived_shapes, *, frames=None,
                       tolerance: float | None = None,
                       policy: TolerancePolicy | None = None,
                       source_address: str = "source",
                       max_deviation_step_mm: float | None = None,
                       max_deviation_points: int = MAX_DEVIATION_POINTS,
                       plan_before: Sequence[Mapping[str, Any]] | None = None,
                       plan_after: Sequence[Mapping[str, Any]] | None = None,
                       floor_grows: str = FLOOR_GROWS,
                       budget_ms: float | None = None) -> DeviationReport:
    """How much the set of derived bodies covers the source shell.

    `derived_shapes` is a mapping `{address: body}` (the address is an
    `output_id` or a part name) or a sequence of pairs. A `None` body is
    not a silent omission but a named `derived_has_no_body` refusal with
    that very address: today ALL of the section's levels, rooms, and types
    are left without a body, and the coverage denominator must show that.

    `tolerance` is a compatible name for `policy.fuzzy_mm`; supplying it
    together with `policy` is forbidden for exactly the same reason as in
    `clash.exact`: otherwise it is unknown which of the two numbers made it
    into the digest.
    """
    started = time.perf_counter()
    if policy is not None and tolerance is not None:
        raise ValueError("задайте либо tolerance, либо policy, но не оба")
    if policy is None:
        policy = (DEFAULT_POLICY if tolerance is None
                  else TolerancePolicy(fuzzy_mm=float(tolerance)))
    digest = policy.digest
    refusals: list[dict[str, Any]] = []
    declared = {"floor_grows": floor_grows,
                "floor_grows_source": "объявлено модулем: стороны нет ни у опа, ни у типа",
                "witness_grid_n": policy.witness_grid_n,
                "max_deviation_points": int(max_deviation_points),
                "dust_relative": DUST_RELATIVE}

    def add(code: str, address: str | None, detail: str) -> None:
        refusals.append({"code": code, "diag": REFUSAL_CODES[code],
                         "address": address, "detail": detail})

    def done(**kwargs) -> DeviationReport:
        base = {"source_address": source_address, "source_volume_mm3": None,
                "derived_volume_mm3": None, "residue": (), "residue_volume_mm3": None,
                "residue_dust_mm3": 0.0, "residue_dust_zones": 0, "excess_mm3": None,
                "coverage": None, "plan_area_delta_mm2": plan_delta,
                "max_deviation": MaxDeviation(value_mm=None, method="grid", step_mm=None,
                                              converges_from_below=True, points_inside=0,
                                              points_tried=0),
                "refusals": tuple(refusals), "tolerance_policy_digest": digest,
                "cost_ms": round((time.perf_counter() - started) * 1000, 3),
                "declared": declared}
        base.update(kwargs)
        base["cost_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return DeviationReport(**base)

    plan_delta: dict[str, float] | None = None
    if plan_before is not None and plan_after is not None:
        try:
            plan_delta, plan_problems = plan_area_delta(plan_before, plan_after)
            refusals.extend(plan_problems)
        except DeviationRefusal as exc:
            add(exc.code, exc.address, str(exc))

    try:
        k = _kernel()
    except DeviationRefusal as exc:                            # pragma: no cover
        add(exc.code, None, str(exc))
        return done()

    items = (list(derived_shapes.items()) if isinstance(derived_shapes, Mapping)
             else [tuple(pair) for pair in derived_shapes])
    if source_shape is None:
        add("source_has_no_body", source_address,
            "у источника нет сохранённого тела (сегодня так у каждого `create_solid_blend`)")
        for address, shape in items:
            if shape is None:
                add("derived_has_no_body", address, "нет тела")
        return done()

    all_frames = dict(frames or {})
    try:
        if not isinstance(source_shape, k.TopoDS_Shape) or source_shape.IsNull():
            raise DeviationRefusal("null_shape", "источник: ожидалась непустая TopoDS_Shape",
                                   source_address)
        source = _placed(source_shape,
                         _validated_frame(all_frames.get(source_address), "frame_source"), k)
        source_volume = _volume(source, k)
        if source_volume <= policy.min_body_volume_mm3:
            raise DeviationRefusal("degenerate_body",
                                   f"источник: объём {source_volume:.6g}", source_address)
    except ExactRefusal as exc:
        add(exc.code if exc.code in REFUSALS else "invalid_frame", source_address, str(exc))
        return done()
    except DeviationRefusal as exc:
        add(exc.code, exc.address, str(exc))
        return done()

    placed: dict[str, Any] = {}
    for address, shape in items:
        if shape is None:
            add("derived_has_no_body", address, "нет тела")
            continue
        try:
            if not isinstance(shape, k.TopoDS_Shape) or shape.IsNull():
                raise DeviationRefusal("null_shape", "ожидалась непустая TopoDS_Shape", address)
            body = _placed(shape, _validated_frame(all_frames.get(address), f"frame[{address}]"), k)
            volume = _volume(body, k)
            if volume <= policy.min_body_volume_mm3:
                raise DeviationRefusal("degenerate_body", f"объём {volume:.6g}", address)
            placed[address] = body
        except ExactRefusal as exc:
            add(exc.code if exc.code in REFUSALS else "invalid_frame", address, str(exc))
        except DeviationRefusal as exc:
            add(exc.code, exc.address, str(exc))

    if not placed:
        add("derived_has_no_body", None,
            f"ни одно из {len(items)} производных не дало тела: покрытие не считается")
        return done(source_volume_mm3=source_volume)

    if budget_ms is not None and (time.perf_counter() - started) * 1000 >= float(budget_ms):
        add("deviation_budget_exhausted", None, "бюджет исчерпан на подготовке тел")
        return done(source_volume_mm3=source_volume)

    order = sorted(placed)
    try:
        union = (placed[order[0]] if len(order) == 1
                 else _boolean("fuse", placed[order[0]], [placed[a] for a in order[1:]], k,
                               fuzzy=policy.fuzzy_mm))
        derived_volume = _volume(union, k)
        residue_shape = _boolean("cut", source, union, k, fuzzy=policy.fuzzy_mm)
        residue_volume = _volume(residue_shape, k)
        _check_cut_against_witness(source, union, residue_volume, source_volume, k,
                                   policy=policy, what="источник − ∪производных")
        excess_shape = _boolean("cut", union, source, k, fuzzy=policy.fuzzy_mm)
        excess_volume = _volume(excess_shape, k)
        _check_cut_against_witness(union, source, excess_volume, derived_volume, k,
                                   policy=policy, what="∪производных − источник")
    except DeviationRefusal as exc:
        add(exc.code, exc.address, str(exc))
        return done(source_volume_mm3=source_volume)
    except Exception as exc:                                   # noqa: BLE001
        add("boolean_not_done", None, f"{type(exc).__name__}: {exc}")
        return done(source_volume_mm3=source_volume)

    zones, dust_volume, dust_zones = [], 0.0, 0
    floor = source_volume * DUST_RELATIVE
    for index, solid in enumerate(sorted(_solids(residue_shape, k),
                                         key=lambda s: -_volume(s, k))):
        volume = _volume(solid, k)
        if volume <= floor:
            dust_volume += volume
            dust_zones += 1
            continue
        nearest, gap = None, None
        for address in order:
            distance = _distance(solid, placed[address], k)
            if distance is not None and (gap is None or distance < gap):
                nearest, gap = address, distance
        zones.append((solid, ResidueBody(
            zone_id=f"residue-{index:04d}", address=source_address,
            volume_mm3=round(volume, 6), centroid_mm=_centroid(solid, k),
            bbox_mm=_bbox(solid, k) or (0., 0., 0., 0., 0., 0.),
            nearest_derived=nearest,
            gap_to_nearest_mm=None if gap is None else round(gap, 6))))

    step = max_deviation_step_mm
    if step is None and zones:
        span = min(min(row.bbox_span_mm) for _, row in zones)
        step = max(1.0, round(span / 10.0, 3))
    if zones:
        shell = _faces_compound(union, k)
        deviation = _grid_max_deviation([solid for solid, _ in zones], shell, k,
                                        step_mm=float(step), point_budget=int(max_deviation_points))
        if deviation.refusal is not None:
            add(deviation.refusal, None,
                f"сетка шагом {step} мм: опрошено {deviation.points_tried} точек")
    else:
        deviation = MaxDeviation(value_mm=0.0, method="grid", step_mm=step,
                                 converges_from_below=True, points_inside=0, points_tried=0)

    # 🔴 A SMOOTHED LOFT IS JUDGED BY BOUNDS, AND THIS IS PRINTED, NOT
    # IMPLIED. A body with a curved face has no closed-form volume: the
    # measurement of the podium `bulge_mm=2000` gave 3.8716e+12 mm³ against
    # two-sided bounds of 3.7601e+12 … 3.9881e+12 — and a one-sided check
    # "loft ⊇ prism" would be WRONG: the loft dips inside the prism by
    # 4.297e+08 mm³. That is why the consumer must see that the obtained
    # number has to be checked against bounds, not a formula; staying
    # silent about this would read as "the number has been verified".
    curved = [name for name, body in (("source:" + source_address, source),
                                      *((address, placed[address]) for address in order))
              if has_curved_faces(body, k)]
    declared["curved_sides"] = curved
    declared["volume_check"] = "bounds_only" if curved else "closed_form_possible"

    return done(source_volume_mm3=source_volume, derived_volume_mm3=derived_volume,
                residue=tuple(row for _, row in zones),
                residue_volume_mm3=round(residue_volume, 6),
                residue_dust_mm3=round(dust_volume, 6), residue_dust_zones=dust_zones,
                excess_mm3=round(excess_volume, 6),
                coverage=(source_volume - residue_volume) / source_volume,
                max_deviation=deviation)


def _faces_compound(shape, k):
    compound = k.TopoDS_Compound()
    builder = k.TopoDS_Builder()
    builder.MakeCompound(compound)
    explorer = k.TopExp_Explorer(shape, k.TopAbs_FACE)
    while explorer.More():
        builder.Add(compound, explorer.Current())
        explorer.Next()
    return compound


__all__ = ["DEVIATION_SCHEMA", "DEVIATION_BASIS", "REFUSALS", "REFUSAL_CODES",
           "FLOOR_GROWS", "MAX_DEVIATION_POINTS", "DeviationRefusal", "ResidueBody",
           "MaxDeviation", "DeviationReport", "measure_refinement",
           "bodies_from_ops", "plan_area_delta"]
