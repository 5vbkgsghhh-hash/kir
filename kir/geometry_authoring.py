"""A KIR authoring program -> a REAL OCCT body, with no new language.

🔴 WHY THIS FILE EXISTS. Before 07.09.2026, rich geometry entered the
project through EXACTLY one path: a trusted Python example
(`examples/curved_podium.py`, `examples/podium_passage.py`) called OCP
itself, built the form by hand, and handed it to
`occt_geometry.capture_body`. Neither `kir.dsl`, nor `kir.sdk`, nor the
authoring sandbox script (`kir.recipe_language`) could obtain a body AT
ALL: their output is a flat IR, and `capture_body` accepts an already
computed `TopoDS_Shape`. Measured on 07.09: a `kir.dsl` program with
`create_solid_blend` + `create_solid_boolean`, laid into a
`ProjectStore`, gave `bodies_with_geometry = 0` — the language could SAY
a loft with a cutout, but the project could not HAVE it.

WHAT IS DONE HERE AND WHAT IS NOT. NO new ops are set up: exactly the
three that already sit in the registry (`spec.OPS`) and are already
checked by `authoring_validation` are read. The module is an EVALUATOR
of what was already said, not a second dialect: not a single field
absent from `ParamSpec` is read here, and no value is invented on the
author's behalf.

WHAT THIS DOES NOT PROVE. An OCCT body is not the body Revit will
build: Revit's blend side surface is undocumented (see the header of
`ops_solid.py`), and here it is `BRepOffsetAPI_ThruSections` with a
straight ruling. No claim of matching volumes is made or checked. This
is GEOMETRY FOR PREVIEW, ANALYSIS, AND STORAGE, not a promise of the
native result.

WHAT IS ABSENT HERE BY CONSTRUCTION: PROCESS ISOLATION. The sandbox
bounds the AUTHORING SCRIPT (5 s CPU, 256 MB), while the trusted caller
builds bodies already outside it, and no OCCT budget bounds the
kernel's own running time — they bound the RESULT. Measured on 07.09 at
the worst the registry allows (a 256-gon and `BOOLEAN_PARTS_MAX = 8`):
build time 1.4–2.6 s, peak RSS 284 MB, and exceeding the tessellation
budget arrives as a `budget_exceeded` refusal WITHOUT silent
coarsening. Whoever needs a CPU/RSS boundary sets it at the process
level, as stated in the header of `occt_geometry`.

REFUSALS ARE NAMED. Empty geometry and an exact zero are FORBIDDEN by
construction: `empty_boolean_result` (an intersection/subtraction ate
the whole body — direct memory of
`occt-common-silent-zero-on-twisted-loft-2026-09-07`),
`degenerate_body` (volume below the tolerance cube), `thin_body` (a
bounding-box dimension thinner than the tolerance along some axis),
`unsupported_profile`, `unsupported_op`. A kernel refusal arrives with
its own code from `occt_geometry` (`kernel_*`).
"""
from __future__ import annotations

from inspect import signature as _signature
import math
from typing import Any, Mapping

from kir.occt_geometry import (GeometryBundle, GeometryRefusal, IDENTITY_FRAME,
                               capture_body)
from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                         NamedOutput, ProjectRevision, RecipePin, output_id)


#: Registry ops that HAVE a closed-form OCCT build. The list is closed:
#: an unknown op gets `unsupported_op`, not silently no body.
BODY_OPS: tuple[str, ...] = ("create_solid_extrusion", "create_solid_blend",
                             "create_solid_boolean")

#: 🔴 THE NUMBER IS NOT WRITTEN HERE, BUT READ. The modeling tolerance
#: belongs to `occt_geometry.capture_body` — it is the one that puts it
#: into the body's manifest. A second `0.01` literal in this file would
#: match it exactly until the neighbor's first edit, after which the
#: `thin_body`/`degenerate_body` threshold would drift from the
#: tolerance recorded in the bundle, SILENTLY. The test holds the
#: equality with an instrument.
DEFAULT_TOLERANCE_MM: float = _signature(capture_body).parameters["modeling_tolerance_mm"].default


def _k():
    """ONE door into the kernel — `occt_geometry._kernel`, where the
    version is pinned.

    There is deliberately NO second `import OCP` here: it would be a
    second way out of the kernel to a foreign package and would bypass
    the pin check (measured 07.09.2026 — the closed list named it
    `geometry_authoring.py -> OCP (soft)`).
    """
    from kir.occt_geometry import _kernel

    kernel = _kernel()
    return (kernel, kernel.BRepAlgoAPI, kernel.BRepBuilderAPI, kernel.BRepOffsetAPI,
            kernel.BRepPrimAPI, kernel.gp)


def _oid(operation: Any) -> str:
    """The name of the AUTHOR'S OP for someone else's diagnostics. One
    place, not five literals.

    🔴 WHY (found in a self-review on 07.09.2026). `contour.validate_region`
    and `plane.validate_plane` put `op_id` into EVERY diagnostic of
    theirs, and the string `"geometry_authoring"` was being passed here —
    the MODULE's name. The refusal was honest about the field and lied
    about the addressee: the author's program has ten operations, and
    the refusal never named WHICH of them. The op's name is the only
    thing by which the author will find it.
    """
    identifier = operation.get("id") if isinstance(operation, Mapping) else None
    return identifier if isinstance(identifier, str) and identifier else "<оп без id>"


def _region(profile: Any, field: str, oid: str, op_name: str) -> dict:
    """A registry profile -> a CANONICAL CONTOUR region, or a refusal by name.

    🔴 THERE IS NO LONGER A SECOND READER OF THE SHAPE HERE (07.09.2026).
    Before this fix, the file parsed the profile ITSELF: it understood
    `poly` and `rect`, did not understand a rotated rectangle, `l`,
    openings, or arcs — and refused with `unsupported_profile` in cases
    where the LANGUAGE accepts the shape. Measured: 6 of 7 forms legal
    under `contour.SHAPE_FORMS` were never built by the evaluator. This
    is exactly "a dictionary instead of a mechanism": the registry said
    one thing, the body evaluator said another, and they would have
    drifted further apart at the very next edit to `SHAPE_FORMS`.

    Now the shape is read by the ONE AND ONLY carrier of the law —
    `contour.validate_region`, the same one the compiler reads it with
    (`ground.py`). The output is canonical: `{"outer": edges, "holes":
    [edges]}`, an edge being `(p0, p1, bulge)` in DXF convention.
    Nothing is invented: whatever CONTOUR did not accept arrives here as
    its own diagnostic, not as silence.

    THE GRID POOL IS EMPTY ON PURPOSE. Grid binding (`{"at_grid": …}`)
    is resolved at `ground`, which has the pool; the body evaluator does
    not have it and cannot have it. So an address point gets a NAMED
    refusal, not a silent zero.
    """
    from kir import contour
    from kir.diag import KirRefusal

    if not isinstance(profile, Mapping):
        raise GeometryRefusal("unsupported_profile", f"{oid}: {field}: ожидался объект формы реестра")
    # The registry takes `{outer, holes}`; author programs and the
    # tree's examples write a bare shape. The wrapper is NOT a
    # relaxation: a bare shape is a region with no openings, and no
    # second meaning is assigned to it here.
    wrapped = profile if "outer" in profile else {"outer": profile}
    diagnostics: list = []
    try:
        region = contour.validate_region(wrapped, [], oid, field, diagnostics)
    except KirRefusal as exc:
        raise GeometryRefusal("unsupported_profile", f"{oid}: {field}: {exc}") from exc
    if region is None:
        raise GeometryRefusal(
            "unsupported_profile",
            f"{oid}: " + ("; ".join(d.message_ru for d in diagnostics)
                          or f"{field}: CONTOUR отверг форму"))
    if contour.region_has_spline(region):
        # 🔴 A SPLINE IS REFUSED BY THE SAME LAW AS THE COMPILER'S
        # (08.09.2026).
        #
        # There used to be its OWN argument here — "a Catmull-Rom
        # sampling is not the curve `HermiteSpline.Create` produces" —
        # and it is true, but it is a SECOND one. The real law is single
        # and lives in `contour.SPLINE_WITNESSED_OPS`: an op whose
        # witness only proves lines and arcs does not accept a spline,
        # and the guard stands at GROUNDING (`ground.py`, KIR-E010).
        # Measured on 08.09 against the compiler: `create_solid_extrusion`
        # with a spline -> `ok=False`, KIR-E010; not one of the three
        # `BODY_OPS` is in the list. So if we built the curve here, the
        # project would get a BODY for a program the language does not
        # compile: the same disease of "two readers of one shape" this
        # file was cured of, only in reverse.
        #
        # WHY THE LIST IS READ, NOT REPEATED. Should a solid op ever
        # gain a spline witness, this refusal must fall silent ON ITS
        # OWN, not after someone remembers a second file.
        witnessed = op_name in contour.SPLINE_WITNESSED_OPS
        raise GeometryRefusal(
            "unsupported_profile",
            f"{oid}: {field}: " + (
                f"{op_name} сплайн ВЫРАЖАЕТ (contour.SPLINE_WITNESSED_OPS), а этот "
                f"вычислитель кривую не строит: понадобится интерполяция по ТЕМ ЖЕ "
                f"точкам, которые печатает `HermiteSpline.Create`"
                if witnessed else
                f"{op_name} не входит в contour.SPLINE_WITNESSED_OPS — язык этот "
                f"сплайн НЕ ПРИНИМАЕТ (страж заземления, KIR-E010: свидетель опа "
                f"доказывает только прямые и дуги). Тело для программы, которая не "
                f"компилируется, было бы вторым ответом на тот же вопрос. "
                f"СЛЕДУЮЩИЙ ХОД: выразить край дугами (arcs)"))
    return region


def _oriented(edges: list, positive: bool) -> list:
    """A ring with a winding SIGN: outer counterclockwise, an opening
    clockwise.

    The sign is taken from `contour.loop_measures` — the one and only
    carrier of a ring's signed area, EXACT for an arc too. A formula of
    its own here would be a second answer to the same question, while
    CONTOUR accepts either winding on input.
    """
    from kir.contour import loop_measures

    if (loop_measures(edges)[0] > 0.0) == positive:
        return list(edges)
    return [(p1, p0, -bulge) for p0, p1, bulge in reversed(edges)]


#: The default plane: world XY, extrusion along +Z. The same thing
#: emission prints when `plane` is absent (`solid_emit`, the `plane is
#: None` branch).
_WORLD_XY = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def _placement(operation: Mapping[str, Any]) -> tuple[tuple, float]:
    """(sketch plane, base elevation) — from `plane` OR from `base_z_mm`.

    🔴 A TILTED PLANE IS NO LONGER A REFUSAL. The registry (`ops_solid`,
    21.08.2026) states verbatim: the body remains a RIGHT prism, but its
    axis is the plane's NORMAL, not +Z; an oblique prism remains, as it
    always was, inexpressible. This is exactly what is built here: the
    profile is laid onto the plane via `kir.plane.frame` (the one and
    only carrier of the O·X·Y·N triple, where Y is derived as N×X), and
    the run goes along N. Leaving `XYZ.BasisZ` in place would drop the
    volume to A·h·|N·Z| — on a wall's vertical face, TO ZERO — and that
    is exactly the silent zero forbidden here.

    The registry declares `base_z_mm` and `plane` MUTUALLY EXCLUSIVE.
    When both are declared, it is a refusal by name: silently preferring
    one over the other would mean silently losing the author's decision.
    """
    from kir import plane as plane_mod

    oid = _oid(operation)
    declared = operation.get("plane")
    base_z = operation.get("base_z_mm")
    if declared is None:
        if base_z is not None and (type(base_z) not in (int, float) or not math.isfinite(base_z)):
            raise GeometryRefusal("invalid_input", f"{oid}: base_z_mm должен быть конечным числом")
        return _WORLD_XY, float(base_z or 0.0)
    if base_z is not None:
        raise GeometryRefusal(
            "unsupported_op",
            f"{oid}: plane и base_z_mm взаимно исключают друг друга (реестр ops_solid): "
            "у плоскости эскиза уже есть своё начало")
    diagnostics: list = []
    normalized = plane_mod.validate_plane(declared, oid, "plane", diagnostics)
    if normalized is None:
        raise GeometryRefusal(
            "unsupported_op",
            f"{oid}: " + ("; ".join(d.message_ru for d in diagnostics)
                          or "plane: плоскость отвергнута"))
    return plane_mod.frame(normalized), 0.0


def _pnt(placement, uv, offset, gp):
    origin, x, y, normal = placement
    u, v = float(uv[0]), float(uv[1])
    return gp.gp_Pnt(*(origin[k] + u * x[k] + v * y[k] + offset * normal[k] for k in range(3)))


def _wire(edges, offset, placement, tools):
    """A canonical ring -> an OCCT wire. An arc is built FROM THREE POINTS.

    The three points are the same ones emission prints
    (`contour._edge_curve_cs` -> `Arc.Create(start, end, pointOnArc)`),
    and the midpoint is taken from that same `contour.bulge_midpoint`. A
    second way to build the arc would give a second arc.
    """
    kernel, _algo, builder, _off, _prim, gp = tools
    from kir.contour import STRAIGHT_BULGE_EPS, bulge_midpoint, is_spline

    maker = builder.BRepBuilderAPI_MakeWire()
    for p0, p1, bulge in edges:
        if is_spline(bulge):
            # A spline never reaches this point: `_region` rejects it via
            # the `contour.SPLINE_WITNESSED_OPS` list. The refusal is
            # kept as a SECOND line of defense and says what is missing,
            # not "unsupported": a body curve must be the interpolation
            # through the SAME points that `HermiteSpline.Create` prints,
            # and this evaluator does not build that curve.
            raise GeometryRefusal(
                "unsupported_profile",
                "сплайн-ребро: этот вычислитель строит только прямую и дугу; "
                "кривая потребовала бы интерполяции по точкам `HermiteSpline.Create`")
        a, b = _pnt(placement, p0, offset, gp), _pnt(placement, p1, offset, gp)
        if abs(bulge) < STRAIGHT_BULGE_EPS:
            edge = builder.BRepBuilderAPI_MakeEdge(a, b)
        else:
            arc = kernel.GC.GC_MakeArcOfCircle(a, _pnt(placement, bulge_midpoint(p0, p1, bulge),
                                                       offset, gp), b)
            if not arc.IsDone():
                raise GeometryRefusal("degenerate_body",
                                      "дуга по трём точкам не построилась (точки на прямой?)")
            edge = builder.BRepBuilderAPI_MakeEdge(arc.Value())
        if not edge.IsDone():
            raise GeometryRefusal("degenerate_body", "ребро профиля не построилось")
        maker.Add(edge.Edge())
    if not maker.IsDone():
        raise GeometryRefusal("degenerate_body", "профиль не замкнулся в проволоку")
    return maker.Wire()


def _face(region, offset, placement, tools):
    """A region -> a flat face WITH OPENINGS. An opening is subtracted,
    not drawn."""
    _kernel, _algo, builder, _off, _prim, _gp = tools
    face = builder.BRepBuilderAPI_MakeFace(_wire(_oriented(region["outer"], True),
                                                 offset, placement, tools))
    for hole in region["holes"]:
        face.Add(_wire(_oriented(hole, False), offset, placement, tools))
    if not face.IsDone():
        raise GeometryRefusal("degenerate_body", "профиль не дал плоской грани")
    return face.Face()


def _prism(region, offset, height, placement, tools):
    """A RIGHT prism: the run goes along the sketch plane's NORMAL, not
    along +Z."""
    _kernel, _algo, _builder, _off, prim, gp = tools
    normal = placement[3]
    solid = prim.BRepPrimAPI_MakePrism(
        _face(region, offset, placement, tools),
        gp.gp_Vec(*(float(height) * normal[k] for k in range(3))))
    if not solid.IsDone():
        raise GeometryRefusal("kernel_capture_failed", "выдавливание профиля не завершилось")
    return solid.Shape()


def _part_shape(part: Mapping[str, Any], tools, oid: str):
    kernel, _algo, _builder, _off, prim, gp = tools
    shape = part.get("shape")
    center = part.get("center_mm")
    if shape in ("box", "sphere", "cylinder"):
        if not isinstance(center, (list, tuple)) or len(center) != 3:
            raise GeometryRefusal("unsupported_profile", f"{oid}: часть булевой требует center_mm значением")
        cx, cy, cz = (float(v) for v in center)
    if shape == "box":
        size = part.get("size_mm")
        if not isinstance(size, (list, tuple)) or len(size) != 3:
            raise GeometryRefusal("unsupported_profile", f"{oid}: box требует size_mm из трёх чисел")
        sx, sy, sz = (float(v) for v in size)
        return prim.BRepPrimAPI_MakeBox(gp.gp_Pnt(cx - sx / 2, cy - sy / 2, cz - sz / 2), sx, sy, sz).Shape()
    if shape == "sphere":
        return prim.BRepPrimAPI_MakeSphere(gp.gp_Pnt(cx, cy, cz), float(part["radius_mm"])).Shape()
    if shape == "cylinder":
        height = float(part["height_mm"])
        axis = gp.gp_Ax2(gp.gp_Pnt(cx, cy, cz - height / 2), gp.gp_Dir(0., 0., 1.))
        return prim.BRepPrimAPI_MakeCylinder(axis, float(part["radius_mm"]), height).Shape()
    if shape == "prism":
        return _prism(_region(part.get("profile"), "parts[].profile", oid,
                              "create_solid_boolean"), 0.0,
                      float(part["height_mm"]), _WORLD_XY, tools)
    raise GeometryRefusal("unsupported_profile", f"{oid}: часть булевой {shape!r} не поддержана")


def _boolean(base, parts, operation, tools, oid: str):
    kernel, algo, _builder, _off, _prim, _gp = tools
    factory = {"union": algo.BRepAlgoAPI_Fuse, "difference": algo.BRepAlgoAPI_Cut,
               "intersect": algo.BRepAlgoAPI_Common}.get(operation)
    if factory is None:
        raise GeometryRefusal("unsupported_op", f"{oid}: булева операция {operation!r} не поддержана")
    result = base
    for part in parts:
        algorithm = factory(result, _part_shape(part, tools, oid))
        algorithm.Build()
        if not algorithm.IsDone():
            raise GeometryRefusal("kernel_boolean_failed", f"OCCT не завершил {operation}")
        result = algorithm.Shape()
        # 🔴 A SILENT ZERO. `Common`/`Cut` return an EMPTY compound with
        # no error, and `IsDone()` reads True regardless (memory of
        # occt-common-silent-zero, 07.09). An empty body is not geometry
        # and does not silently become it.
        explorer = kernel.TopExp.TopExp_Explorer(result, kernel.TopAbs.TopAbs_SOLID)
        if not explorer.More():
            raise GeometryRefusal("empty_boolean_result",
                                  f"{oid}: {operation} не оставил ни одного тела; "
                                  f"пустая геометрия не принимается")
    return result


def _loft(low, top, offset, height, placement, tools):
    kernel, _algo, _builder, offsets, _prim, _gp = tools
    if low["holes"] or top["holes"]:
        # 🔴 THE SAME LAW AS EMISSION'S, AND NOW WITH A NUMBER
        # (08.09.2026). `CreateBlendGeometry(CurveLoop, CurveLoop, …)`
        # takes ONE ring per profile — its signature has no room for a
        # second ring at all — and the emitter refuses exactly on this
        # (`solid_emit`, KIR-T004, 04.09.2026). Measured on 08.09 against
        # the compiler: a blend with an opening in the base -> `ok=False`,
        # KIR-T004, and the same for the top profile. So if we built the
        # opening here, the project's body would diverge from the body
        # Revit will build from our own C#, and subtracting the opening
        # after `ThruSections` would be a THIRD answer to a question the
        # language has already answered: "assemble the blend without
        # openings and subtract the opening with a boolean difference."
        #
        # A NUMBER, NOT JUST A NAME. `ThruSections`'s silence about the
        # opening costs exactly as much material as the opening would
        # occupy as a right prism over the blend's run; the areas are
        # computed by `contour.region_measures` (Green's integral, exact
        # for an arc too), and the number is printed for BOTH profiles,
        # because with different rings the true volume of the void
        # depends on a vertex correspondence that `CreateBlendGeometry`
        # does not define.
        from kir.contour import region_measures

        lost = [sum(region_measures(side)["hole_areas_mm2"]) * float(height)
                for side in (low, top)]
        raise GeometryRefusal(
            "unsupported_profile",
            f"бленд с проёмом этим вычислителем не строится: `CreateBlendGeometry` "
            f"берёт по ОДНОМУ замкнутому кольцу на профиль, и эмиссия отказывает "
            f"тем же законом (solid_emit, KIR-T004). `ThruSections` потерял бы "
            f"проём МОЛЧА — лишнего материала {lost[0]:.6g} мм³ по нижнему профилю "
            f"и {lost[1]:.6g} мм³ по верхнему (проём прямой призмой на ход "
            f"{float(height):.6g} мм). СЛЕДУЮЩИЙ ХОД: собрать бленд без проёмов и "
            f"вычесть проём `create_solid_boolean` (difference)")
    if len(low["outer"]) != len(top["outer"]):
        raise GeometryRefusal("unsupported_profile",
                              "бленд этого вычислителя требует равного числа рёбер у обоих профилей")
    sections = offsets.BRepOffsetAPI_ThruSections(True, True, 1e-6)
    sections.AddWire(_wire(_oriented(low["outer"], True), offset, placement, tools))
    sections.AddWire(_wire(_oriented(top["outer"], True), offset + float(height), placement, tools))
    sections.Build()
    if not sections.IsDone():
        raise GeometryRefusal("kernel_loft_failed", "OCCT не построил переход между профилями")
    return sections.Shape()


def _check_sketch(regions, height, tolerance):
    """Thinness is a property of the SKETCH, not of the world-axis box
    (07.09.2026).

    🔴 WHY A SECOND CHECK, WHEN `thin_body` ALREADY EXISTS. That one
    measures the axis-aligned bounding box of the RESULT, and as long as
    the body sat only in world XY, the box WAS the body. With a tilted
    sketch plane this stopped being true: a 4000×3000 slab, 0.005 mm
    thick, laid at 45°, gives a box with all three edges in the
    meters — and "thin" would slip through SILENTLY, exactly the way
    this is forbidden here. So thinness is asked where the author NAMED
    it: the region's bounding box in the sketch plane
    (`contour.region_bbox` — exact for an arc too) and the extrusion run.

    WHAT CHANGED ON 08.09.2026 AND WHY THIS CHECK IS STILL NEEDED.
    `_check_body` is no longer blind to rotation: it also asks the
    body's own axes. But the two instruments answer DIFFERENT questions
    and do not replace each other: here — "the author declared it
    thin," there — "it CAME OUT thin." The first refuses BEFORE the
    kernel does any work and names the author's FIELD; the second only
    knows the result and cannot name a field.
    """
    from kir.contour import region_bbox

    if float(height) <= tolerance:
        raise GeometryRefusal("thin_body",
                              f"ход выдавливания {height} мм не превышает допуск {tolerance} мм")
    for field, region in regions:
        x0, y0, x1, y1 = region_bbox(region)
        thinnest = min(x1 - x0, y1 - y0)
        if thinnest <= tolerance:
            raise GeometryRefusal("thin_body",
                                  f"{field}: габарит эскиза {thinnest} мм не превышает "
                                  f"допуск {tolerance} мм")


def _own_axes_thinnest(shape, kernel) -> float:
    """The smallest bounding-box dimension of a body along ITS OWN axes.
    A measure WITHOUT world axes.

    🔴 WHY A SECOND BOX (08.09.2026). An axis-aligned bounding box is not
    the body's box but the box of its SHADOW on the world axes, and for
    a rotated body these two numbers diverge by orders of magnitude.
    `docs/PROJECT_GEOMETRY_RU.md` held this as a NAMED LIMITATION: "a
    thin plate PRODUCED by a boolean operation on a tilted plane will
    not be named `thin_body`." Measured on 08.09 on a program the
    compiler accepts (`ok=True`): the intersection of two prisms over
    4000×3000 rectangles, rotated 45°, with a 2999.995 mm offset, gives
    a plate 0.005 mm THICK and 60,000 mm³ in volume; its axis-aligned
    box is 2828.43 × 2828.43 × 3000 mm, meaning all three edges in the
    meters, and `thin_body` STAYED SILENT.

    WHAT IS COMPUTED HERE. `BRepBndLib::AddOBB` — OCCT's oriented
    bounding box: from the point set if the body consists of flat faces
    and straight edges, otherwise from the axes of inertia. Three
    arguments are set EXPLICITLY, each chosen against a named hazard:

      `theIsTriangulationUsed=False`  otherwise the answer would depend
                                      on whether SOMEONE HAD ALREADY
                                      called `rederive_preview` on this
                                      same object: the tessellation
                                      stays with the shape, and the
                                      measure would stop being a
                                      function of the body. Measured:
                                      the numbers with and without
                                      triangulation are the same on all
                                      five forms in the tree;
      `theIsOptimal=True`             a tighter box; the cost is
                                      measured — 0.3–0.4 ms per body,
                                      against 1.4–2.6 s to build it;
      `theIsShapeToleranceUsed=False` widening the box by the shape's
                                      tolerance would make a thin body
                                      THICKER, weakening exactly the
                                      guard this measure exists for.

    WHAT THIS MEASURE DOES NOT CLAIM: it is NOT the minimum-volume OBB.
    A box aligned to the axes of inertia can be wider than the
    tightest one, so the number here is an UPPER-BOUND ESTIMATE of the
    true thickness. Hence the only legitimate way to use it: "small" is
    proof of thinness, "large" is NOT proof of thickness. So below, the
    SMALLER of the two boxes is taken, not this one instead of the old
    one: this fix could not weaken the old guard on any body.
    """
    box = kernel.Bnd.Bnd_OBB()
    kernel.BRepBndLib.BRepBndLib.AddOBB_s(shape, box, False, True, False)
    if box.IsVoid():
        raise GeometryRefusal("degenerate_body",
                              "ориентированный габарит тела пуст: измерять нечего")
    return 2.0 * min(box.XHSize(), box.YHSize(), box.ZHSize())


def _check_body(shape, tolerance, tools):
    """A degenerate and thin body — A REFUSAL BY NAME, not a small number.

    THINNESS IS ASKED WITH TWO BOXES AND DECIDED BY THE SMALLER OF THEM.
    The world box remains: it is exact when the body sits on the world
    axes. The body's own (:func:`_own_axes_thinnest`) answers where the
    world one lies. Taking one instead of the other would mean either
    bringing back the 07.09 limitation, or replacing an exact number
    with an estimate; taking the smaller means NEVER saying "thick"
    where either of the two says "thin."
    """
    kernel = tools[0]
    from kir.occt_geometry import _measure

    facts = _measure(shape, kernel)          # it will refuse an invalid/non-simple one on its own
    if facts["volume_mm3"] <= tolerance ** 3:
        raise GeometryRefusal("degenerate_body",
                              f"объём {facts['volume_mm3']} mm³ не превышает куб допуска {tolerance} мм")
    world = min(b - a for a, b in zip(facts["bbox_min_mm"], facts["bbox_max_mm"]))
    own = _own_axes_thinnest(shape, kernel)
    if min(world, own) <= tolerance:
        raise GeometryRefusal(
            "thin_body",
            f"габарит {min(world, own)} мм не превышает допуск {tolerance} мм "
            f"(по мировым осям {world} мм, по собственным осям тела {own} мм)")
    return facts


def build_body(operation: Mapping[str, Any], *, modeling_tolerance_mm: float = DEFAULT_TOLERANCE_MM):
    """One registry op -> a `TopoDS_Shape`. Saves nothing and hashes
    nothing."""
    if not isinstance(operation, Mapping):
        raise GeometryRefusal("invalid_input", "операция должна быть объектом IR")
    name = operation.get("op")
    if name not in BODY_OPS:
        raise GeometryRefusal("unsupported_op",
                              f"{_oid(operation)}: {name!r} не имеет замкнутого построения OCCT; "
                              f"поддержаны {', '.join(BODY_OPS)}")
    tolerance = float(modeling_tolerance_mm)
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise GeometryRefusal("invalid_input", "modeling_tolerance_mm должен быть положительным")
    tools = _k()
    oid = _oid(operation)
    placement, base = _placement(operation)
    height = operation.get("height_mm")
    if type(height) not in (int, float) or not math.isfinite(height) or height <= 0:
        raise GeometryRefusal("invalid_input", "height_mm должен быть положительным числом")
    try:
        if name == "create_solid_extrusion":
            region = _region(operation.get("profile"), "profile", oid, name)
            _check_sketch((("profile", region),), height, tolerance)
            shape = _prism(region, base, height, placement, tools)
        elif name == "create_solid_blend":
            low = _region(operation.get("profile"), "profile", oid, name)
            top = _region(operation.get("profile_top"), "profile_top", oid, name)
            _check_sketch((("profile", low), ("profile_top", top)), height, tolerance)
            shape = _loft(low, top, base, height, placement, tools)
        else:
            parts = operation.get("parts")
            if not isinstance(parts, (list, tuple)) or not parts:
                raise GeometryRefusal("invalid_input", f"{oid}: create_solid_boolean требует непустой parts")
            region = _region(operation.get("profile"), "profile", oid, name)
            _check_sketch((("profile", region),), height, tolerance)
            shape = _boolean(_prism(region, base, height, placement, tools),
                             parts, operation.get("operation"), tools, oid)
    except GeometryRefusal:
        raise
    except Exception as exc:  # noqa: BLE001 — a kernel refusal carries a name, it does not stay silent
        raise GeometryRefusal("kernel_capture_failed", f"{type(exc).__name__}: {exc}") from exc
    _check_body(shape, tolerance, tools)
    return shape


def author_bodies(program: Mapping[str, Any], *, project_id: str, instance_key: str,
                  recipe: RecipePin, parameters: Mapping[str, Any],
                  frame=IDENTITY_FRAME, modeling_tolerance_mm: float = DEFAULT_TOLERANCE_MM,
                  output_keys: Mapping[str, str] | None = None,
                  source_lineage=()) -> dict[str, GeometryBundle]:
    """A `kir.dsl.build()` program -> `{output_key: GeometryBundle}`.

    ONLY ops from `BODY_OPS` are read; the rest of the author program's
    operations are left untouched and remain ordinary project outputs.
    `output_keys` translates `op["id"]` into the project output's name;
    by default the name equals `id`.
    """
    ops = program.get("ops") if isinstance(program, Mapping) else None
    if not isinstance(ops, (list, tuple)):
        raise GeometryRefusal("invalid_input", "ожидалась программа KIR с массивом ops")
    keys = dict(output_keys or {})
    bundles: dict[str, GeometryBundle] = {}
    for operation in ops:
        if not isinstance(operation, Mapping) or operation.get("op") not in BODY_OPS:
            continue
        identifier = operation.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise GeometryRefusal("invalid_input", "операция тела обязана нести свой id")
        output_key = keys.get(identifier, identifier)
        shape = build_body(operation, modeling_tolerance_mm=modeling_tolerance_mm)
        bundles[output_key] = capture_body(
            shape, project_id=project_id, instance_key=instance_key, output_key=output_key,
            recipe=recipe, parameters=parameters, frame=frame,
            source_lineage=tuple(source_lineage), modeling_tolerance_mm=modeling_tolerance_mm)
    return bundles


def author_project(program: Mapping[str, Any], *, project_id: str, instance_key: str = "i",
                   module_key: str = "m", recipe: RecipePin, parameters: Mapping[str, Any],
                   frame=IDENTITY_FRAME, modeling_tolerance_mm: float = DEFAULT_TOLERANCE_MM,
                   intent: str | None = None,
                   source_lineage=()) -> tuple[ProjectRevision, dict[str, GeometryBundle]]:
    """An author program -> a project revision whose outputs CARRY
    bodies, plus its assets.

    Output order is author-operation order. Ops with no build travel as
    ordinary outputs WITHOUT `geometry`: there is no silent substitution
    of a body here.
    """
    from kir.project import PROJECT_SCHEMA_V2

    bundles = author_bodies(program, project_id=project_id, instance_key=instance_key,
                            recipe=recipe, parameters=parameters, frame=frame,
                            modeling_tolerance_mm=modeling_tolerance_mm,
                            source_lineage=source_lineage)
    outputs = []
    for operation in program["ops"]:
        identifier = operation["id"]
        payload = {key: value for key, value in operation.items() if key != "id"}
        bundle = bundles.get(identifier)
        if bundle is None:
            outputs.append(NamedOutput(identifier, payload))
            continue
        # The body lives in the bundle; the project output carries a
        # REFERENCE and the ordinary display op.
        outputs.append(NamedOutput(identifier,
                                   {"op": "create_directshape", "category": operation["category"],
                                    "name": operation["name"]},
                                   BodyRepresentation(bundle.digest, bundle.body_digest)))
    revision = ProjectRevision(
        project_id, [ModuleDefinition(module_key, "sealed_evaluation", recipe)],
        [ModuleInstance(instance_key, module_key, outputs, parameters=dict(parameters))],
        intent=intent if intent is not None else program.get("intent"),
        schema=PROJECT_SCHEMA_V2)
    by_digest = {bundle.digest: bundle for bundle in bundles.values()}
    return revision, by_digest


def attach_recipe_bodies(binding, *, frame=IDENTITY_FRAME,
                         modeling_tolerance_mm: float = DEFAULT_TOLERANCE_MM,
                         source_lineage=()):
    """A sealed evaluation of an author script -> THE SAME submission,
    but WITH BODIES.

    🔴 THIS IS THE "REAL AUTHORING WORKFLOW." The model script runs
    inside a sandbox (`sandbox.execute_author_script`, a separate
    process, chroot, zero network), the receipt is bound to the project
    (`project_recipe.bind_recipe_result`), and ONLY AFTER THAT does the
    trusted caller build bodies from those same registry operations.
    Neither OCP nor `capture_body` ever reaches the sandbox: the author
    script still cannot run native code.

    The recipe pin and the parameters are taken FROM THE CANDIDATE, not
    reassembled — otherwise
    `geometry_materialization.validate_geometry_bindings` would reject
    the binding as foreign. The submission is returned with the same
    base, scope, author, and reason: bodies are ADDED to the same
    outputs, nothing is replaced.
    """
    from kir.project_merge import ChangeProposal

    proposal = getattr(binding, "proposal", None)
    if proposal is None:
        raise GeometryRefusal("recipe_projection_refused",
                              "оценка рецепта не дала заявки; тело не приделывается к отказу")
    evaluation = binding.evaluation
    instance_key, module_key = evaluation["instance_key"], evaluation["module_key"]
    candidate = proposal.candidate
    instance = next(item for item in candidate.instances if item.key == instance_key)
    definition = next(module for module in candidate.modules if module.key == module_key)
    if definition.recipe is None:
        raise GeometryRefusal("recipe_projection_refused", "модуль без пина не заявляет источника тела")
    program = evaluation["program"]
    keys = {operation["id"]: output.key
            for operation, output in zip(program["ops"], instance.outputs, strict=True)}
    bundles = author_bodies(program, project_id=candidate.project_id, instance_key=instance_key,
                            recipe=definition.recipe, parameters=instance.parameters,
                            frame=frame, modeling_tolerance_mm=modeling_tolerance_mm,
                            output_keys=keys, source_lineage=source_lineage)
    if not bundles:
        raise GeometryRefusal("no_body_operation",
                              f"в программе нет ни одного опа из {', '.join(BODY_OPS)}")
    outputs = []
    for operation, output in zip(program["ops"], instance.outputs, strict=True):
        bundle = bundles.get(output.key)
        if bundle is None:
            outputs.append(output)
            continue
        outputs.append(NamedOutput(output.key,
                                   {"op": "create_directshape", "category": operation["category"],
                                    "name": operation["name"]},
                                   BodyRepresentation(bundle.digest, bundle.body_digest)))
    from dataclasses import replace as _replace

    revised = proposal.base.revise(
        expected_revision=proposal.base.revision_id, modules=candidate.modules,
        instances=tuple(_replace(instance, outputs=tuple(outputs)) if item.key == instance_key else item
                        for item in candidate.instances))
    return (ChangeProposal(proposal.base, revised, proposal.scope, proposal.author, proposal.reason),
            {bundle.digest: bundle for bundle in bundles.values()})


def rebind_body_frame(bundle: GeometryBundle, *, world_delta_mm) -> GeometryBundle:
    """Move an AUTHORED body in world coordinates, without touching its
    shape.

    🔴 WHY A SEPARATE MOVE. `project_fix.raise_clear` raises a body by
    editing an AUTHORED PARAMETER — the `instance.parameters[output.key]`
    box — and this is correct exactly for scenes where each output has
    its own box. In an authored program
    (`author_project`/`attach_recipe_bodies`), ALL bodies of one instance
    share ONE set of parameters: the shape is set by registry operations,
    not by a box named after the output. Measured 07.09.2026 — a refusal
    reading "raise_clear needs a box parameter named 'plinth' on
    instance 'tower-c'." Worse, editing the shared parameters WOULD
    BREAK THE NEIGHBORS: `validate_geometry_bindings` checks each body's
    manifest against the owning instance's parameters, and neighboring
    bundles would keep the old ones.

    So it is the BODY ITSELF that moves — by translating its frame (the
    rigid local-mm -> project-mm transform) that all three G02 readers
    read. Shape, recipe, parameters, binding, and tolerance are NOT
    CHANGED; only the translation column changes. `body_sha256` must
    stay the same — this is CHECKED below, not merely promised: a
    changed BRep would mean the shape was swapped out under the guise of
    a move.

    WHAT THIS DOES NOT DO: it does not rerun the recipe and does not
    claim that the recipe, given new inputs, would produce this same
    body. The shift is an authored decision about PLACEMENT, and the
    recipe's next run does not know about it
    (`authored_body_needs_recipe_rebind` is the name for the case where
    placement is not enough and the source needs rebinding).
    """
    if not isinstance(bundle, GeometryBundle):
        raise GeometryRefusal("invalid_input", "ожидался инертный GeometryBundle")
    if (not isinstance(world_delta_mm, (list, tuple)) or len(world_delta_mm) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in world_delta_mm)):
        raise GeometryRefusal("invalid_input", "world_delta_mm — три конечных числа в мм проекта")
    frame = list(bundle.to_dict()["manifest"]["frame"])
    # World point = R·local + t. A world shift d changes ONLY t.
    for axis in range(3):
        frame[4 * axis + 3] = frame[4 * axis + 3] + float(world_delta_mm[axis])
    # 🔴 THE KERNEL IS NOT CALLED HERE, AND THIS IS A FIX, NOT AN
    # OPTIMIZATION (measured 07.09). The first draft moved the body like
    # this: `read_body()` -> `capture_body(frame=…)`. For a flat prism,
    # the ASCII BRep survived this round trip BYTE FOR BYTE; for a loft
    # it did NOT: parsing + `BRepBuilderAPI_Copy` + writing re-issued the
    # B-spline side surfaces differently, `body_sha256` drifted
    # (e09f9279814a -> 88464fb690b8), and a pure translation looked like
    # a different body. The refusal was honest about the symptom and
    # wrong about the cause: the BRep, the preview, and the measurements
    # are LOCAL and do not depend on the frame at all.
    return bundle.with_frame(frame)


def _unit(vector, field):
    if (not isinstance(vector, (list, tuple)) or len(vector) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)):
        raise GeometryRefusal("invalid_input", f"{field} — три конечных числа")
    values = [float(v) for v in vector]
    length = math.sqrt(sum(v * v for v in values))
    if length <= 1e-9:
        raise GeometryRefusal("invalid_input", f"{field} не имеет направления")
    return [v / length for v in values]


def rotate_body_frame(bundle: GeometryBundle, *, degrees: float,
                      axis=(0., 0., 1.), about_mm=(0., 0., 0.)) -> GeometryBundle:
    """Rotate an AUTHORED body around a world axis, without touching its
    shape.

    🔴 WHY ROTATION IS THE SAME MOVE AS TRANSLATION, NOT A KERNEL
    OPERATION. The bundle's frame is a RIGID local-mm -> project-mm
    transform, and `with_frame` was already proven (07.09.2026) to touch
    neither the BRep, nor the preview, nor the measurements: all of them
    are LOCAL. A rotation changes the frame's rotation matrix and its
    translation column — and `body_sha256` must stay the SAME. This is
    CHECKED inside `with_frame`, not merely promised: a changed BRep
    would mean the shape was swapped out under the guise of placement.

    WHY THIS IS HERE, NOT AT A READER. Measured 07.09.2026:
    `rebind_body_frame` could ONLY translate (`world_delta_mm`), and
    there was no way to rotate an authored body from any of the three
    reading paths. A rotation that reaches one reader and not another is
    exactly the discrepancy `geometry_readers.one_geometry` catches; so
    it is done ON the bundle, and readers take the frame from it.

    There is no reflection here, and there cannot be: `_frame` rejects
    det = −1 (`invalid_frame`). The legitimate way to reflect is
    :func:`mirror_body`, where the BODY ITSELF is reflected while the
    frame remains a right-handed triple.
    """
    if not isinstance(bundle, GeometryBundle):
        raise GeometryRefusal("invalid_input", "ожидался инертный GeometryBundle")
    if type(degrees) not in (int, float) or not math.isfinite(degrees):
        raise GeometryRefusal("invalid_input", "degrees — конечное число градусов")
    if (not isinstance(about_mm, (list, tuple)) or len(about_mm) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in about_mm)):
        raise GeometryRefusal("invalid_input", "about_mm — три конечных числа в мм проекта")
    ux, uy, uz = _unit(axis, "axis")
    angle = math.radians(float(degrees))
    c, s2 = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    # Rodrigues: R = I·cos + (1−cos)·uuᵀ + sin·[u]ₓ. Orthogonality and det = +1
    # are NOT asserted here — `_frame` checks them on the way out, and this is
    # the sole carrier of the law about a valid frame.
    rotation = ((t*ux*ux + c,    t*ux*uy - s2*uz, t*ux*uz + s2*uy),
                (t*ux*uy + s2*uz, t*uy*uy + c,    t*uy*uz - s2*ux),
                (t*ux*uz - s2*uy, t*uy*uz + s2*ux, t*uz*uz + c))
    old = bundle.to_dict()["manifest"]["frame"]
    pivot = [float(v) for v in about_mm]
    frame = []
    for row in range(3):
        # New = P + R·(Old − P), componentwise across the 4×4 rows.
        frame.extend(sum(rotation[row][k] * old[4*k + col] for k in range(3)) for col in range(3))
        frame.append(pivot[row] + sum(rotation[row][k] * (old[4*k + 3] - pivot[k]) for k in range(3)))
    frame.extend((0., 0., 0., 1.))
    return bundle.with_frame(frame)


def mirror_body(bundle: GeometryBundle, *, normal, through_mm=(0., 0., 0.),
                max_vertices: int = 4096, max_triangles: int = 4096) -> GeometryBundle:
    """PERMITTED reflection: the BODY is mirrored, the frame remains a right-handed triple.

    🔴 TWO KINDS OF REFLECTION, AND THEY ARE DIFFERENT. A reflection WRITTEN
    INTO THE FRAME is rejected by name (`invalid_frame`: «reflection requires
    a separate orientation contract»), and this is correct: the frame is
    declared rigidly right-handed, every reader treats it as such, and a
    left-handed frame would silently flip face normals for anyone who
    multiplies it with local geometry. The contract it demands is THIS ONE:
    the shape itself is reflected, while the placement stays right-handed.

    WHAT IS CHECKED, NOT PROMISED. The mirrored body is a DIFFERENT body, and
    `body_sha256` must change (a match would mean the reflection did not
    happen — the `mirror_did_nothing` refusal). At the same time VOLUME and
    face count must be preserved: reflection is an isometry. A negative or
    drifted volume is the `mirror_lost_volume` refusal, not a silent number.

    WHAT THIS DOES NOT DO: it does not claim that Revit will build the
    mirrored instance the same way, and it does not carry `face_identity`
    over — it is declared `bundle_local` and the new body has its own.
    """
    if not isinstance(bundle, GeometryBundle):
        raise GeometryRefusal("invalid_input", "ожидался инертный GeometryBundle")
    if (not isinstance(through_mm, (list, tuple)) or len(through_mm) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in through_mm)):
        raise GeometryRefusal("invalid_input", "through_mm — три конечных числа в мм тела")
    direction = _unit(normal, "normal")
    kernel = _k()[0]
    from kir.occt_geometry import _measure

    manifest = bundle.manifest
    before = _measure(bundle.read_body(), kernel)
    try:
        transform = kernel.gp.gp_Trsf()
        transform.SetMirror(kernel.gp.gp_Ax2(kernel.gp.gp_Pnt(*(float(v) for v in through_mm)),
                                             kernel.gp.gp_Dir(*direction)))
        builder = kernel.BRepBuilderAPI.BRepBuilderAPI_Transform(bundle.read_body(), transform, True)
        if not builder.IsDone():
            raise GeometryRefusal("kernel_mirror_failed", "OCCT не завершил отражение тела")
        shape = builder.Shape()
    except GeometryRefusal:
        raise
    except Exception as exc:  # noqa: BLE001 — the core refusal carries a name, it does not stay silent
        raise GeometryRefusal("kernel_mirror_failed", f"{type(exc).__name__}: {exc}") from exc
    after = _measure(shape, kernel)
    if after["face_count"] != before["face_count"]:
        raise GeometryRefusal("mirror_lost_volume",
                              f"число граней уехало {before['face_count']} -> {after['face_count']}")
    if abs(after["volume_mm3"] - before["volume_mm3"]) > 1e-6 * before["volume_mm3"]:
        raise GeometryRefusal("mirror_lost_volume",
                              f"объём уехал {before['volume_mm3']} -> {after['volume_mm3']}")
    preview, binding = manifest["preview"], manifest["binding"]
    mirrored = capture_body(
        shape, project_id=binding["project_id"], instance_key=binding["instance_key"],
        output_key=binding["output_key"], recipe=RecipePin.from_dict(manifest["recipe"]),
        parameters=manifest["parameters"], frame=manifest["frame"],
        source_lineage=tuple(manifest["source_lineage"]),
        modeling_tolerance_mm=manifest["modeling_tolerance_mm"],
        linear_deflection_mm=preview["linear_deflection_mm"],
        angular_deflection_rad=preview["angular_deflection_rad"],
        max_vertices=max_vertices, max_triangles=max_triangles)
    if mirrored.body_digest == bundle.body_digest:
        raise GeometryRefusal("mirror_did_nothing",
                              "отражённое тело побайтно равно исходному: отражение не состоялось")
    return mirrored


__all__ = ["BODY_OPS", "DEFAULT_TOLERANCE_MM", "build_body", "author_bodies",
           "author_project", "attach_recipe_bodies", "rebind_body_frame",
           "rotate_body_frame", "mirror_body", "GeometryRefusal"]
