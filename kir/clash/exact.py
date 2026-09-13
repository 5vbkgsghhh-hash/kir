"""The exact narrow phase: a pair of bodies is judged by BODIES, not hulls.

🔴 WHY IT EXISTS AT ALL, AND THIS IS A MEASUREMENT, NOT A DESIGN INTENT.
Today's narrow phase (`detect.py`) judges conservative HULLS and therefore
knows exactly two verdicts: `possible` and `confirmed`. It cannot say "the
hulls intersected but the bodies did not" AT ANY threshold whatsoever: there
is no refutation in its vocabulary. Measurement 06.09.2026 on a live corpus
(1455 elements): `exact` grades — 0 of 1271, all 3506 findings `possible`.
That is, a "clash" today is always a "maybe-clash", and a repair step cannot
be built on it (review #14).

🔴 THE LAW OF DEPTH. `depth_mm` is the minimal axis-wise extent of the AABB
of the `Common` body, in world coordinates after the frame: the minimal
AXIAL shift that separates the bodies. One law for both `intersect` and
`contained` (for containment, `Common` equals the smaller body). The
bounding box is taken over `TopAbs_SOLID`, not over the whole shape: a
boolean result is a compound, and its bounding box on the acceptance scene
equaled the bounding box of the PODIUM, giving 3000.01 instead of 500.0 for
an exact volume.

🔴 WHY VOLUME, NOT GAP. Measured on a podium with an atrium: for a body
FULLY CONTAINED within another, `BRepExtrema_DistShapeShape` returns
**3000 mm**, not zero — it measures the distance to the nearest SURFACE, and
the surfaces here do not intersect at all. A check "by gap" DOES NOT SEE full
containment. So the relation is decided by the volume of
`BRepAlgoAPI_Common`, and the gap is computed only when the intersection
volume is zero.

🔴 WHY TOLERANCE DOES NOT BUY CONTACT. A sweep of `SetFuzzyValue` on a pair
standing right up against each other from outside: 0.001 · 0.01 · 0.1 · 1.0 ·
10.0 mm give ONE AND THE SAME verdict (`clear`, gap 0.000537 mm). So fuzzy is
the numerical stability of the boolean operation, NOT clearance; contact must
be decided by the gap number and an explicit threshold, exactly as
`clearance_mm` is in the hull phase.

🔴 THE COST IS NAMED UP FRONT (medians, measurement 06.09.2026): simple
prisms 7.3 ms; loft × box — 26.8 ms (`clear`) and 52.7 ms (`contained`); a
real partial intersection 316 ms; **loft × loft — 1356 ms**. The hull phase
costs 97 µs per pair. The exact phase is 70–14 000 times more expensive, so
it NEVER runs over the broad phase's stream: the input is an explicit list
of pairs with a budget, and the remainder is named by a number.

🔴 WHAT THIS MODULE DOES NOT DO. It does not read the store, does not parse
BRep bytes, does not look at `preview_mesh` under any circumstances (a stale
preview cannot substitute for the body simply because the preview never
reaches here), does not heal or simplify bodies, does not invent its own
primitives. The kernel is not extended: only OCP calls.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

#: Outcome schema. Changes together with the field set, not "whenever
#: someone feels like it".
EXACT_VERDICT_SCHEMA = "clash-exact-verdict/1"

#: The only basis this module issues. The name travels into
#: `PhysicalOverlapProof.basis` and into the HMAC stamp — no second
#: dictionary is set up.
EXACT_BASIS = "occt_common_v1"

#: Body relations. `clear` is a PROVEN absence of intersection, not "not found".
RELATIONS = ("intersect", "contained", "clear")

#: Closed list of refusals. A refusal is neither a finding nor a refutation:
#: the pair remains as the hull phase left it, and the reason travels into
#: `analysis_limits`. The list is closed on purpose: an "other" here would
#: mean the reason is not named.
REFUSALS = (
    "boolean_not_done",        # OCCT did not complete the boolean operation
    "exact_budget_exhausted",  # the run/pair budget was exhausted BEFORE the call
    "no_persisted_body",       # the side has no stored BRep
    "null_shape",              # empty shape
    "mirrored_frame",          # det = −1: a mirror requires a separate contract
    "invalid_frame",           # not 4×4, not rigid, has scale/shear
    "degenerate_body",         # volume is not positive
    "kernel_unavailable",      # OCP is missing or the wrong version
    # 🔴 SET UP 07.09.2026 BY A MEASUREMENT, NOT AS A PRECAUTION (mission 2
    # recon, `refine-loop/RECON-deviation.md` §5). `BRepAlgoAPI_Common(twisted
    # loft, prism)` returns a volume of **0.0 with `IsDone() == True`** for
    # EVERY twist ≥ 9° — exactly at the point where the loft's side surface
    # exits the prism (bounding box along y 9000.0 → 9085.0), i.e. where the
    # surfaces genuinely intersect. Both bodies pass
    # `BRepCheck_Analyzer.IsValid()`, `SetFuzzyValue` 0 · 1e-7 · 1e-3 · 0.01 ·
    # 0.1 · 1.0 changes nothing, the constructor-built shape gives the same.
    # All three towers of the example tree (`tower-a` 12°, `tower-b` −9°,
    # `tower-c` 18°) sit in the failure zone, and without this code they
    # would get `clear` — a PROVEN absence of intersection — where the
    # bodies in fact intersect over 99% of their volume.
    "boolean_contradicts_witness",
)

IDENTITY_FRAME = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


class ExactRefusal(ValueError):
    """Named refusal of the exact phase; carries a code from `REFUSALS`."""

    def __init__(self, code: str, message: str):
        if code not in REFUSALS:
            raise AssertionError(f"{code}: отказ вне закрытого списка REFUSALS")
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class TolerancePolicy:
    """All tolerance numbers in ONE place, with a digest.

    The policy is a matter of contract, not a call setting: two runs with
    different tolerances are not comparable, and
    `tolerance_policy_digest` must show this.
    """

    #: Fuzzy value of the boolean operation. Numerical stability, NOT clearance.
    fuzzy_mm: float = 0.01
    #: The threshold below which a gap is called contact. The READER
    #: decides: the verdict itself, when `Common == 0`, remains `clear` in
    #: any case.
    contact_gap_mm: float = 0.5
    #: Containment: |Common − min(V)| ≤ max(rel·min(V), abs).
    containment_relative: float = 1e-6
    containment_absolute_mm3: float = 1e-3
    #: Below this volume a body is considered degenerate.
    min_body_volume_mm3: float = 1e-6
    #: Mesh edge length of the empty-intersection witness (`witness_common`).
    #: The number goes into the digest ON PURPOSE: whether a silent zero gets
    #: caught depends on it, and two runs with different densities are not
    #: comparable. 5 was measured — it catches 4 cases out of 4 and gives no
    #: false positive on any of the 3 sound ones.
    witness_grid_n: int = 5

    def __post_init__(self) -> None:
        if (isinstance(self.witness_grid_n, bool)
                or not isinstance(self.witness_grid_n, int) or self.witness_grid_n < 2):
            raise ValueError("witness_grid_n обязан быть целым не меньше 2")
        for name in ("fuzzy_mm", "contact_gap_mm", "containment_relative",
                     "containment_absolute_mm3", "min_body_volume_mm3"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or float(value) < 0.0):
                raise ValueError(f"{name} обязан быть конечным неотрицательным числом")

    def to_dict(self) -> dict[str, float | int]:
        return {"fuzzy_mm": float(self.fuzzy_mm),
                "contact_gap_mm": float(self.contact_gap_mm),
                "containment_relative": float(self.containment_relative),
                "containment_absolute_mm3": float(self.containment_absolute_mm3),
                "min_body_volume_mm3": float(self.min_body_volume_mm3),
                "witness_grid_n": int(self.witness_grid_n)}

    @property
    def digest(self) -> str:
        payload = json.dumps({"schema": EXACT_VERDICT_SCHEMA, "basis": EXACT_BASIS,
                              **self.to_dict()}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


DEFAULT_POLICY = TolerancePolicy()


@dataclass(frozen=True)
class ExactVerdict:
    """Outcome of one exact check. A refusal is as much an outcome as a verdict."""

    relation: str | None
    overlap_volume_mm3: float | None
    depth_mm: float | None
    gap_mm: float | None
    refusal: str | None
    cost_ms: float
    tolerance_policy_digest: str
    contained_side: str | None = None
    basis: str = EXACT_BASIS
    schema_version: str = EXACT_VERDICT_SCHEMA
    detail: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.relation is not None and self.relation not in RELATIONS:
            raise AssertionError("relation вне закрытого списка RELATIONS")
        if self.refusal is not None and self.refusal not in REFUSALS:
            raise AssertionError("refusal вне закрытого списка REFUSALS")
        if (self.relation is None) == (self.refusal is None):
            raise AssertionError("исход обязан быть либо отношением, либо отказом")
        if self.relation == "clear" and self.overlap_volume_mm3:
            raise AssertionError("clear с ненулевым объёмом пересечения")
        if self.relation in ("intersect", "contained") and not self.overlap_volume_mm3:
            raise AssertionError("пересечение без объёма не выдаётся")
        # The gap exists ONLY at zero volume: at intersection it is zero by
        # definition, and an extra DistShapeShape costs 20…111 ms.
        if self.relation in ("intersect", "contained") and self.gap_mm is not None:
            raise AssertionError("зазор не считается для пересекающихся тел")
        if (self.contained_side is not None) != (self.relation == "contained"):
            raise AssertionError("contained_side существует только у вложения")

    @property
    def ok(self) -> bool:
        return self.refusal is None

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "basis": self.basis,
                "relation": self.relation,
                "overlap_volume_mm3": self.overlap_volume_mm3,
                "depth_mm": self.depth_mm, "gap_mm": self.gap_mm,
                "contained_side": self.contained_side,
                "refusal": self.refusal, "detail": self.detail,
                "cost_ms": self.cost_ms,
                "tolerance_policy_digest": self.tolerance_policy_digest}


# ───────────────────────────────────────────────────────────────── kernel

def _kernel():
    """OCP is obtained ONLY through the tree's door, and its absence is
    named, not caught silently.

    🔴 THERE USED TO BE A SECOND `from OCP...` HERE, AND IT WAS A SECOND DOOR
    (fix 07.09.2026). The closed-list measurement
    (`test_kir_boundary_to_the_product_is_a
    _closed_list`) named FOUR exits from the KERNEL to a foreign package:
    `clash/exact.py`, `clash/project_analysis.py`, `refine/deviation.py`, and
    `occt_geometry.py`. Three of them bypassed the VERSION PIN:
    `occt_geometry._kernel` checks `cadquery-ocp-novtk==OCP_VERSION` and
    `OCP.__version__`, while these checked nothing, meaning on a foreign OCCT
    build the exact phase would compute silently and by different rules. The
    door is one per TREE, not one per module.

    The refusal remains named after this module: the door's `GeometryRefusal`
    is translated into `ExactRefusal("kernel_unavailable")` — a code from the
    closed `REFUSALS` list, which travels into `analysis_limits`. Both
    `kernel_unavailable` and the door's `unsupported_backend` mean one thing
    here: "OCP is missing or the wrong version" — exactly as written next to
    the code in `REFUSALS`.
    """
    from kir.occt_geometry import GeometryRefusal, _kernel as _occt_kernel

    try:
        k = _occt_kernel()
    except GeometryRefusal as exc:                            # pragma: no cover
        raise ExactRefusal("kernel_unavailable",
                           "установите kir-building[geometry]") from exc
    from types import SimpleNamespace
    return SimpleNamespace(
        BRepAlgoAPI_Common=k.BRepAlgoAPI.BRepAlgoAPI_Common,
        BRepBuilderAPI_Transform=k.BRepBuilderAPI.BRepBuilderAPI_Transform,
        BRepExtrema_DistShapeShape=k.BRepExtrema.BRepExtrema_DistShapeShape,
        BRepClass3d_SolidClassifier=k.BRepClass3d.BRepClass3d_SolidClassifier,
        BRepGProp=k.BRepGProp.BRepGProp,
        Bnd_Box=k.Bnd.Bnd_Box,
        BRepBndLib=k.BRepBndLib.BRepBndLib,
        GProp_GProps=k.GProp.GProp_GProps,
        BRepAdaptor_Surface=k.BRepAdaptor.BRepAdaptor_Surface,
        GeomAbs_SurfaceType=k.GeomAbs.GeomAbs_SurfaceType,
        TopAbs_FACE=k.TopAbs.TopAbs_FACE,
        TopAbs_IN=k.TopAbs.TopAbs_IN,
        TopAbs_ON=k.TopAbs.TopAbs_ON,
        TopAbs_OUT=k.TopAbs.TopAbs_OUT,
        TopAbs_SOLID=k.TopAbs.TopAbs_SOLID,
        TopExp_Explorer=k.TopExp.TopExp_Explorer,
        TopoDS=k.TopoDS.TopoDS,
        TopoDS_Builder=k.TopoDS.TopoDS_Builder,
        TopoDS_Compound=k.TopoDS.TopoDS_Compound,
        TopoDS_Shape=k.TopoDS.TopoDS_Shape,
        gp_Pnt=k.gp.gp_Pnt,
        gp_Trsf=k.gp.gp_Trsf,
    )


def _volume(shape, k) -> float:
    props = k.GProp_GProps()
    k.BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass())


def _validated_frame(frame, name: str) -> tuple[float, ...]:
    """The same law as `occt_geometry._frame`: rigid, right-handed, no scale.

    Having its own instance of the law here is NOT a second dictionary: that
    module checks the frame WHEN THE BODY IS SAVED, this one WHEN IT IS
    ANALYZED, and their refusals are of a different kind (`invalid_frame` of
    the analysis is not the same as a capture refusal). The numbers are the
    same on purpose, and this is checked by a test.
    """
    if frame is None:
        return IDENTITY_FRAME
    if not isinstance(frame, (list, tuple)) or len(frame) != 16:
        raise ExactRefusal("invalid_frame", f"{name}: ожидалась матрица 4×4 по строкам")
    try:
        m = tuple(float(x) for x in frame)
    except (TypeError, ValueError) as exc:
        raise ExactRefusal("invalid_frame", f"{name}: нечисловой элемент") from exc
    if any(not math.isfinite(x) for x in m):
        raise ExactRefusal("invalid_frame", f"{name}: неконечный элемент")
    if m[12:] != (0., 0., 0., 1.):
        raise ExactRefusal("invalid_frame", f"{name}: проективные преобразования не поддержаны")
    cols = [tuple(m[4 * row + col] for row in range(3)) for col in range(3)]
    for i in range(3):
        for j in range(3):
            if abs(sum(a * b for a, b in zip(cols[i], cols[j])) - (i == j)) > 1e-9:
                raise ExactRefusal("invalid_frame", f"{name}: масштаб или сдвиг недопустимы")
    a, b, c = cols
    det = (a[0] * (b[1] * c[2] - b[2] * c[1])
           - b[0] * (a[1] * c[2] - a[2] * c[1])
           + c[0] * (a[1] * b[2] - a[2] * b[1]))
    if abs(det + 1) <= 1e-9:
        raise ExactRefusal("mirrored_frame", f"{name}: det = −1, зеркало требует отдельного договора")
    if abs(det - 1) > 1e-9:
        raise ExactRefusal("invalid_frame", f"{name}: det ≠ 1")
    return m


def _placed(shape, frame, k):
    """The frame is applied HERE: `read_body()` returns LOCAL coordinates.

    An identity frame is skipped without calling the kernel — not for speed,
    but to avoid producing a copy of the shape where there is no
    transformation.
    """
    if frame == IDENTITY_FRAME:
        return shape
    trsf = k.gp_Trsf()
    trsf.SetValues(frame[0], frame[1], frame[2], frame[3],
                   frame[4], frame[5], frame[6], frame[7],
                   frame[8], frame[9], frame[10], frame[11])
    moved = k.BRepBuilderAPI_Transform(shape, trsf, True)
    if not moved.IsDone():
        raise ExactRefusal("boolean_not_done", "перенос фигуры не завершён")
    return moved.Shape()


def _solid_spans(shape, k) -> list[float] | None:
    """Axis-wise AABB extents of the shape's BODIES, in world coordinates.

    🔴 WHY BODIES ONLY, AND THIS IS A MEASUREMENT, NOT CAUTION (acceptance,
    entry 7). `BRepAlgoAPI_Common` returns a COMPOUND, and the compound's
    bounding box is not the bounding box of the intersection: on the
    acceptance scene `passage ∩ podium` has an exact volume
    (3.8000e+10 = 4000 × 19000 × 500), while the bbox of the whole shape
    equals the bbox of the PODIUM (67000 × 19000 × 3000.01). The minimum over
    such a bounding box gave `depth_mm` **3000.01** for a penetration of
    500.0 — the instrument was right about a different subject. Traversing
    by `TopAbs_SOLID` takes the bounding box of the result's bodies
    specifically.
    """
    # 🔴 THE BOUNDING BOX TAKEN IS OPTIMAL, NOT FAST, AND THIS IS THE SECOND
    # HALF OF THE SAME MEASUREMENT. `BRepBndLib.Add_s` builds the bounding box
    # from the UNTRIMMED underlying surfaces of the faces: for the single
    # solid `passage ∩ podium` the volume is exact (3.8e+10), while its "fast"
    # bounding box equals the podium's bounding box (67000 × 19000 × 3000.01),
    # because the faces lie on the podium's surfaces. `AddOptimal_s` computes
    # from the actual trim and gives 4000 × 19000 × 500. `occt_geometry._measure`
    # measures with the same call and for the same reason.
    box = k.Bnd_Box()
    explorer = k.TopExp_Explorer(shape, k.TopAbs_SOLID)
    solids = 0
    while explorer.More():
        k.BRepBndLib.AddOptimal_s(explorer.Current(), box, False, False)
        solids += 1
        explorer.Next()
    if not solids:
        return None
    if box.IsVoid():
        return None
    x0, y0, z0, x1, y1, z1 = box.Get()
    spans = [x1 - x0, y1 - y0, z1 - z0]
    return spans if all(math.isfinite(v) and v > 0.0 for v in spans) else None


def _distance(a, b, k) -> float | None:
    try:
        probe = k.BRepExtrema_DistShapeShape(a, b)
        if not probe.IsDone():
            return None
        return float(probe.Value())
    except Exception:                                          # noqa: BLE001
        return None


def has_curved_faces(shape, k=None) -> bool:
    """Whether the shape has at least one NON-PLANAR face.

    A cheap filter: the witness costs 0.5 s per pair, and there is no reason
    to pay it for two boxes — on flat-faced bodies the measurement never once
    found a silent zero (3 sound cases out of 3). The filter goes by the type
    of the face's SURFACE, not by the op's name: the body arrives here as
    BRep bytes, and who built it is unknown.
    """
    k = k or _kernel()
    if shape is None or shape.IsNull():
        return False
    explorer = k.TopExp_Explorer(shape, k.TopAbs_FACE)
    while explorer.More():
        try:
            surface = k.BRepAdaptor_Surface(k.TopoDS.Face_s(explorer.Current()))
            if surface.GetType() != k.GeomAbs_SurfaceType.GeomAbs_Plane:
                return True
        except Exception:                                      # noqa: BLE001
            # A face the adapter cannot read is considered CURVED: the filter
            # must err toward an extra check, not a missed defect.
            #
            # 🔴 AND THAT IS EXACTLY WHY THE FILTER HAS ITS OWN CONTROL IN THE
            # OPPOSITE DIRECTION. The first revision called `k.TopoDS`, which
            # did not exist in the kernel's namespace; the `AttributeError`
            # landed here, and the filter answered "curved" for EVERY body,
            # including a box. The witness still worked, all seven cases were
            # judged correctly — and the defect was invisible from the
            # verdicts alone. Only the question "can it say NO?" catches it
            # (`test_the_selector_can_say_no`).
            return True
        explorer.Next()
    return False


def witness_common(shape_a, shape_b, k=None, *, grid_n: int = 5,
                   tolerance: float = 1e-7) -> tuple[int, int]:
    """How many points lie INSIDE BOTH bodies. The answer is independent of
    the boolean operation.

    🔴 WHY. `BRepAlgoAPI_Common` can return emptiness with `IsDone() == True`
    (see `boolean_contradicts_witness` in `REFUSALS`). Volume additivity does
    NOT CATCH this defect: measurement 07.09.2026 on the three example towers
    gave a discrepancy `|V(A∩B)+V(A−B) − V(A)|/V(A)` = 2.2e-16 · 5.9e-12 ·
    1.1e-10, i.e. `Cut` is self-consistent — it is simply wrong. Only an
    INDEPENDENT counter catches it: point classification is decided by
    traversing the hull, not by boolean algebra.

    Returns `(points in both, points polled)`. The denominator is needed
    next to the numerator: "0 of 0" and "0 of 250" print identically and
    mean different things.
    """
    k = k or _kernel()
    if shape_a is None or shape_b is None or shape_a.IsNull() or shape_b.IsNull():
        return 0, 0
    classifiers = [k.BRepClass3d_SolidClassifier(shape_a),
                   k.BRepClass3d_SolidClassifier(shape_b)]
    both = tried = 0
    for shape in (shape_a, shape_b):
        box = k.Bnd_Box()
        explorer = k.TopExp_Explorer(shape, k.TopAbs_SOLID)
        solids = 0
        while explorer.More():
            k.BRepBndLib.AddOptimal_s(explorer.Current(), box, False, False)
            solids += 1
            explorer.Next()
        if not solids or box.IsVoid():
            continue
        x0, y0, z0, x1, y1, z1 = box.Get()
        for i in range(grid_n):
            for j in range(grid_n):
                for m in range(grid_n):
                    point = k.gp_Pnt(x0 + (i + .5) * (x1 - x0) / grid_n,
                                     y0 + (j + .5) * (y1 - y0) / grid_n,
                                     z0 + (m + .5) * (z1 - z0) / grid_n)
                    tried += 1
                    inside = True
                    for classifier in classifiers:
                        classifier.Perform(point, tolerance)
                        if classifier.State() == k.TopAbs_OUT:
                            inside = False
                            break
                    both += 1 if inside else 0
    return both, tried


# ───────────────────────────────────────────────────────────── exact phase

def verify_pair(shape_a, shape_b, frame_a=None, frame_b=None, *,
                tolerance_mm: float | None = None,
                policy: TolerancePolicy | None = None,
                budget_ms: float | None = None) -> ExactVerdict:
    """Judge a pair by BODIES. Frames are applied here, to local shapes.

    `tolerance_mm` is a compatibility name for `policy.fuzzy_mm`; setting
    both at once is forbidden, because then it is unknown which of the two
    numbers went into the policy digest.
    """
    started = time.perf_counter()
    if policy is not None and tolerance_mm is not None:
        raise ValueError("задайте либо tolerance_mm, либо policy, но не оба")
    if policy is None:
        policy = (DEFAULT_POLICY if tolerance_mm is None
                  else TolerancePolicy(fuzzy_mm=float(tolerance_mm)))
    digest = policy.digest

    def refuse(code: str, detail: str) -> ExactVerdict:
        return ExactVerdict(relation=None, overlap_volume_mm3=None, depth_mm=None,
                            gap_mm=None, refusal=code, detail=detail,
                            cost_ms=round((time.perf_counter() - started) * 1000, 3),
                            tolerance_policy_digest=digest)

    if budget_ms is not None and float(budget_ms) <= 0.0:
        return refuse("exact_budget_exhausted", "бюджет исчерпан до вызова")
    try:
        k = _kernel()
    except ExactRefusal as exc:                                # pragma: no cover
        return refuse(exc.code, str(exc))

    try:
        if shape_a is None or shape_b is None:
            raise ExactRefusal("no_persisted_body", "у стороны нет сохранённого тела")
        for name, shape in (("a", shape_a), ("b", shape_b)):
            if not isinstance(shape, k.TopoDS_Shape):
                raise ExactRefusal("null_shape", f"{name}: ожидалась TopoDS_Shape")
            if shape.IsNull():
                raise ExactRefusal("null_shape", f"{name}: пустая фигура")
        fa = _validated_frame(frame_a, "frame_a")
        fb = _validated_frame(frame_b, "frame_b")
        placed_a = _placed(shape_a, fa, k)
        placed_b = _placed(shape_b, fb, k)
        va, vb = _volume(placed_a, k), _volume(placed_b, k)
        if va <= policy.min_body_volume_mm3 or vb <= policy.min_body_volume_mm3:
            raise ExactRefusal("degenerate_body", f"объёмы {va:.6g} и {vb:.6g}")
    except ExactRefusal as exc:
        return refuse(exc.code, str(exc))

    if budget_ms is not None and (time.perf_counter() - started) * 1000 >= float(budget_ms):
        return refuse("exact_budget_exhausted", "бюджет исчерпан на подготовке")

    try:
        common = k.BRepAlgoAPI_Common(placed_a, placed_b)
        common.SetFuzzyValue(policy.fuzzy_mm)
        common.Build()
        if not common.IsDone():
            return refuse("boolean_not_done", "BRepAlgoAPI_Common не завершил построение")
        overlap = _volume(common.Shape(), k)
    except ExactRefusal as exc:                                # pragma: no cover
        return refuse(exc.code, str(exc))
    except Exception as exc:                                   # noqa: BLE001
        return refuse("boolean_not_done", f"{type(exc).__name__}: {exc}")

    smaller = min(va, vb)
    tolerance = max(policy.containment_relative * smaller, policy.containment_absolute_mm3)

    if overlap <= 0.0:
        # 🔴 AN EMPTY INTERSECTION MUST BE PROVEN, NOT TAKEN ON FAITH.
        # `clear` in this dictionary means "a PROVEN absence of
        # intersection", and a silent zero from the boolean operation
        # (measurement §5 of mission-2 recon) would issue exactly this
        # promise on a pair intersecting over 99% of its volume. The witness
        # is asked ONLY here and ONLY for a curved face: on flat-faced bodies
        # the defect was not observed, and the witness itself costs 0.5–0.6 s
        # per pair — more expensive than all the rest of the check.
        if has_curved_faces(placed_a, k) or has_curved_faces(placed_b, k):
            both, tried = witness_common(placed_a, placed_b, k,
                                         grid_n=policy.witness_grid_n)
            if both > 0:
                return refuse(
                    "boolean_contradicts_witness",
                    f"Common пуст, а свидетель нашёл {both} общих точек из "
                    f"{tried} (сетка {policy.witness_grid_n}³ по габаритам обоих "
                    f"тел); объём пересечения не публикуется")
        # The gap is computed ONLY here. At intersection it is zero by
        # definition, and the call costs from 20 to 111 ms on complex bodies.
        gap = _distance(placed_a, placed_b, k)
        return ExactVerdict(relation="clear", overlap_volume_mm3=0.0, depth_mm=None,
                            gap_mm=None if gap is None else round(gap, 6), refusal=None,
                            cost_ms=round((time.perf_counter() - started) * 1000, 3),
                            tolerance_policy_digest=digest)

    # 🔴 ONE LAW OF DEPTH FOR BOTH RELATIONS (acceptance, entry 7):
    # `depth_mm` is the MINIMAL AXIS-WISE EXTENT of the AABB of the `Common`
    # body, in world coordinates after the frame. This is the minimal AXIAL
    # shift that separates the bodies, not an MTV and not a bounding-box
    # length. For containment, `Common` equals the smaller body, so the same
    # law gives its own minimal extent (a 1000³ cube → 1000.0) — no second
    # law is needed.
    spans = _solid_spans(common.Shape(), k)
    depth = None if spans is None else min(spans)

    if abs(overlap - smaller) <= tolerance:
        side = "a" if va <= vb else "b"
        return ExactVerdict(relation="contained", overlap_volume_mm3=overlap,
                            depth_mm=None if depth is None else round(depth, 6),
                            gap_mm=None, refusal=None, contained_side=side,
                            cost_ms=round((time.perf_counter() - started) * 1000, 3),
                            tolerance_policy_digest=digest)

    # A partial intersection is judged by the same law (see above): this is
    # a LOWER BOUND on penetration, not an MTV, and it is named just as
    # cautiously as `signed_distance` in the hull phase.
    return ExactVerdict(relation="intersect", overlap_volume_mm3=overlap,
                        depth_mm=None if depth is None else round(depth, 6),
                        gap_mm=None, refusal=None,
                        cost_ms=round((time.perf_counter() - started) * 1000, 3),
                        tolerance_policy_digest=digest)


def classify_point(shape, point, frame=None, *,
                   policy: TolerancePolicy | None = None) -> str:
    """`in | on | out` for a point in a body. The atrium's void is `out`."""
    policy = policy or DEFAULT_POLICY
    k = _kernel()
    if shape is None or not isinstance(shape, k.TopoDS_Shape) or shape.IsNull():
        raise ExactRefusal("null_shape", "ожидалась непустая TopoDS_Shape")
    placed = _placed(shape, _validated_frame(frame, "frame"), k)
    classifier = k.BRepClass3d_SolidClassifier(placed, k.gp_Pnt(*(float(c) for c in point)),
                                               policy.fuzzy_mm)
    state = classifier.State()
    return {k.TopAbs_IN: "in", k.TopAbs_ON: "on", k.TopAbs_OUT: "out"}.get(state, "out")


def verify_pairs(bodies: Mapping[str, tuple[Any, Any]], pairs, *,
                 policy: TolerancePolicy | None = None,
                 budget_ms: float | None = None,
                 max_pairs: int | None = None) -> tuple[dict, list[str]]:
    """The exact phase over an EXPLICIT list of pairs, with a budget and a
    named remainder.

    Returns `({(a, b): ExactVerdict}, analysis_limits)`. The remainder NEVER
    disappears silently: both the number of unchecked pairs and the reason
    travel as a line.
    """
    policy = policy or DEFAULT_POLICY
    started = time.perf_counter()
    verdicts: dict[tuple[str, str], ExactVerdict] = {}
    limits: list[str] = []
    ordered = [tuple(p) for p in pairs]
    checked = 0
    for index, (a_id, b_id) in enumerate(ordered):
        if max_pairs is not None and checked >= max_pairs:
            limits.append(f"exact_pair_limit_reached: проверено {checked}, "
                          f"не проверено {len(ordered) - index}")
            break
        spent = (time.perf_counter() - started) * 1000
        if budget_ms is not None and spent >= float(budget_ms):
            limits.append(f"exact_budget_exhausted: потрачено {spent:.1f} мс, "
                          f"не проверено {len(ordered) - index}")
            break
        left = None if budget_ms is None else float(budget_ms) - spent
        a = bodies.get(a_id)
        b = bodies.get(b_id)
        if a is None or b is None:
            missing = ", ".join(name for name, item in ((a_id, a), (b_id, b)) if item is None)
            verdicts[(a_id, b_id)] = ExactVerdict(
                relation=None, overlap_volume_mm3=None, depth_mm=None, gap_mm=None,
                refusal="no_persisted_body", detail=f"нет тела: {missing}",
                cost_ms=0.0, tolerance_policy_digest=policy.digest)
            checked += 1
            continue
        verdicts[(a_id, b_id)] = verify_pair(a[0], b[0], a[1], b[1],
                                             policy=policy, budget_ms=left)
        checked += 1
    return verdicts, limits


__all__ = ["EXACT_VERDICT_SCHEMA", "EXACT_BASIS", "RELATIONS", "REFUSALS",
           "IDENTITY_FRAME", "ExactRefusal", "TolerancePolicy", "DEFAULT_POLICY",
           "ExactVerdict", "verify_pair", "verify_pairs", "classify_point",
           "has_curved_faces", "witness_common"]
