"""A THIN BODY IS CALLED THIN IN ANY COORDINATE SYSTEM, NOT ONLY THE WORLD ONE.

🔴 WHAT STOOD ON 08.09.2026 BEFORE THE FIX. `docs/PROJECT_GEOMETRY_RU.md` held
this as A NAMED LIMIT, verbatim: "a thin plate PRODUCED BY a boolean
operation on a sloped plane will not be named `thin_body`." The reason:
`_check_body` measured an AXIS-ALIGNED box, that is, the extent of the
body's SHADOW on the world axes, rather than the body's own extent. Sketch
thinness was caught by `_check_sketch`, but it only knows DECLARED numbers,
and here thinness is BORN of a boolean operation: not one of the declared
numbers is small.

THE MEASUREMENT THAT CLOSES THE LIMIT (08.09.2026). The program below is not
invented to force a refusal: the compiler ACCEPTS it (`ok=True`, zero
diagnostics), meaning its path to Revit is open. The intersection of two
prisms over 4000×3000 rectangles, rotated 45° in plan and shifted 2999.995 mm
across, yields a plate:

    volume                      60 000 mm³   (4000 × 3000 × 0.005)
    axis-aligned box            2828.43 × 2828.43 × 3000 mm — all three edges in meters
    extent along the BODY's own axes   0.005 mm
    modeling tolerance                  0.01 mm

`degenerate_body` did not trigger (60 000 mm³ ≫ 0.01³), `empty_boolean_result`
did not trigger (the body exists), `BRepCheck` did not trigger (the topology
is valid). What was not named was specifically the "thin" kind — and only
that.

WHAT THIS FILE ASSERTS AND WHAT IT DOES NOT. It asserts: the measure of
thinness no longer depends on how the body is rotated relative to the world
axes, and this is shown on TWO independent rotations — in plan (45° around
Z) and on a sloped sketch plane (normal (0, √½, √½)), where thinness now
comes not from a prism but from a spherical segment. It does NOT assert that
the number found is the body's minimum width: an OCCT-oriented box is not
required to be the tightest one, so "a lot" here is still not proof of
thickness (see `_own_axes_thinnest`).
"""
from __future__ import annotations

import math

import pytest

pytest.importorskip("OCP.BRepPrimAPI", reason="optional real OCCT backend")

from kir import contour
from kir.geometry_authoring import DEFAULT_TOLERANCE_MM, GeometryRefusal, build_body
from kir.occt_geometry import _kernel, _measure


#: The prisms' run and the profile side come from ONE place: the numbers
#: below are computed from them, not retyped. The 4000×3000 side is the same
#: as in the neighboring shapes file.
SIDE_U, SIDE_V, RUN = 4000.0, 3000.0, 3000.0
DIAG = math.sqrt(0.5)


def sliver_op(thickness_mm: float) -> dict:
    """Two prisms over rectangles rotated 45° in plan.

    The second is shifted across its own V axis by `SIDE_V − thickness`, so
    the INTERSECTION is a plate of exactly the declared thickness. Both
    declared shapes are large and legal (`SHAPE_SIDE_MIN_MM = 100`): thinness
    is declared NOWHERE, it is born of the boolean.
    """
    shift = SIDE_V - thickness_mm
    origin = [-DIAG * shift, DIAG * shift]
    rect = {"shape": "rect", "origin": [0, 0], "size_mm": [SIDE_U, SIDE_V], "rotation_deg": 45}
    moved = {"shape": "rect", "origin": origin, "size_mm": [SIDE_U, SIDE_V], "rotation_deg": 45}
    return {"op": "create_solid_boolean", "id": "sliver", "profile": rect,
            "height_mm": RUN, "operation": "intersect", "category": "generic",
            "name": "Пластина", "parts": [{"shape": "prism", "profile": moved,
                                           "height_mm": RUN}]}


#: The sketch's sloped plane — the same triple as in the neighboring shapes file.
TILT = {"origin_mm": [0, 0, 0], "normal": [0, DIAG, DIAG], "x_dir": [1, 0, 0]}
#: The radius of the intersecting sphere. The segment's numbers are computed from it in closed form.
CAP_RADIUS = 100000.0


def cap_op(thickness_mm: float) -> dict:
    """A spherical segment of height `thickness` ON THE TOP FACE of the
    sloped prism.

    Here the thin dimension points along the sloped plane's NORMAL — that
    is, along none of the world axes — and the body is curved: the oriented
    box is now computed not from vertices but from the axes of inertia. The
    second body kind is chosen deliberately: the same outcome on both the
    prism and the segment speaks to the MEASURE, not to a special case of
    straight edges.
    """
    # The top face's point (u, v, w) = (SIDE_U/2, SIDE_V/2, RUN) in world mm.
    top = [SIDE_U / 2,
           SIDE_V / 2 * DIAG + RUN * DIAG,
           RUN * DIAG - SIDE_V / 2 * DIAG]
    depth = CAP_RADIUS - thickness_mm          # the sphere's center is ABOVE the face along the normal
    centre = [top[0], top[1] + depth * DIAG, top[2] + depth * DIAG]
    return {"op": "create_solid_boolean", "id": "cap",
            "profile": {"shape": "rect", "origin": [0, 0], "size_mm": [SIDE_U, SIDE_V]},
            "height_mm": RUN, "plane": TILT, "operation": "intersect",
            "category": "generic", "name": "Сегмент",
            "parts": [{"shape": "sphere", "center_mm": centre, "radius_mm": CAP_RADIUS}]}


def world_thinnest(operation: dict) -> float:
    """The smallest edge of the built body's AXIS-ALIGNED box."""
    facts = _measure(build_body(operation), _kernel())
    return min(b - a for a, b in zip(facts["bbox_min_mm"], facts["bbox_max_mm"]))


def test_the_language_itself_accepts_the_program_that_hides_the_sliver():
    """🔴 THE SUBJECT IS NOT MADE UP: the compiler ACCEPTS this program.

    A refusal on a shape the language would not let through anyway would be
    worthless — the guard could never fire on a live program. Here the path
    to Revit is open: zero diagnostics, `ok=True`. So the thin plate would
    have reached the model.
    """
    from kir import dsl
    from kir.compiler import compile_program

    op = sliver_op(DEFAULT_TOLERANCE_MM / 2)
    dsl.reset(intent="пересечение двух повёрнутых призм")
    dsl.create_solid_boolean(
        profile={"outer": op["profile"]}, height_mm=op["height_mm"],
        operation=op["operation"], category="mass", name=op["name"], id="sliver",
        parts=[{"shape": "prism", "profile": {"outer": op["parts"][0]["profile"]},
                "height_mm": op["parts"][0]["height_mm"]}])
    outcome = compile_program(dsl.build())
    assert outcome.ok, [d.message_ru for d in (outcome.diagnostics or [])]


def test_a_sliver_the_world_box_cannot_see_is_refused_by_name():
    """A 0.005 mm plate at 45° in plan is `thin_body`, not silence."""
    with pytest.raises(GeometryRefusal) as caught:
        build_body(sliver_op(DEFAULT_TOLERANCE_MM / 2))
    assert caught.value.code == "thin_body"
    # The refusal carries BOTH numbers: without them the reader will not know
    # WHICH of the two boxes triggered, and will fix the wrong thing.
    assert "по мировым осям" in str(caught.value)
    assert "по собственным осям" in str(caught.value)


def test_the_world_box_really_is_blind_here_and_not_merely_unused():
    """🔴 CONTROL: the same drawing, slightly thicker, BUILDS, and the world
    box is meter-sized.

    Without this pin, "the new guard fired" is indistinguishable from "the
    old one fired." A thickness of 0.05 mm is five times the tolerance, the
    body is legal; its axis-aligned box stays 2828 × 2828 × 3000 mm, meaning
    the old check on this body would stay silent at ANY thickness above zero.
    """
    thickness = DEFAULT_TOLERANCE_MM * 5
    facts = _measure(build_body(sliver_op(thickness)), _kernel())
    assert facts["volume_mm3"] == pytest.approx(SIDE_U * RUN * thickness, rel=1e-6)
    world = min(b - a for a, b in zip(facts["bbox_min_mm"], facts["bbox_max_mm"]))
    # The plate's shadow on world X and Y is a closed form, not a measured
    # number: the long side and the thickness lie at 45°, so each axis gets
    # (SIDE_U + t)·cos45°. The RUN travel is along Z and does not enter the
    # shadow.
    assert world == pytest.approx((SIDE_U + thickness) * DIAG, rel=1e-6)
    assert world > DEFAULT_TOLERANCE_MM * 100000


def test_thinness_along_a_sketch_normal_is_named_too():
    """A sloped plane: the thin dimension lies along none of the world axes."""
    with pytest.raises(GeometryRefusal) as caught:
        build_body(cap_op(DEFAULT_TOLERANCE_MM / 2))
    assert caught.value.code == "thin_body"


def test_the_curved_case_is_invisible_to_the_world_box_as_well():
    """CONTROL for the segment: its world box is MANY TIMES larger than the
    thickness.

    The radius of a segment's cap of height h on a sphere of radius R is
    √(2Rh − h²) — a closed form, not a measured number. The box along the
    world axes is no smaller than this cap projected onto the axes, meaning
    it is unmistakably not "thin."
    """
    thickness = DEFAULT_TOLERANCE_MM * 5
    world = world_thinnest(cap_op(thickness))
    spot = math.sqrt(2 * CAP_RADIUS * thickness - thickness ** 2)
    assert world == pytest.approx(2 * spot * DIAG, rel=1e-3)
    assert world > thickness * 1000


def test_the_new_measure_never_answers_softer_than_the_old_one():
    """🔴 THE GUARD IS NOT WEAKENED: thin ALONG A WORLD AXIS stays thin.

    The oriented box is an UPPER-BOUND estimate for the true thickness, and
    replacing the old number with it would trade something exact for
    something approximate. Here the body is thin specifically along the
    world Z axis: the old check must keep answering, and it answers under
    the same name.
    """
    thin_in_z = {"op": "create_solid_boolean", "id": "slab",
                 "profile": {"shape": "rect", "origin": [0, 0], "size_mm": [SIDE_U, SIDE_V]},
                 "height_mm": RUN, "operation": "intersect", "category": "generic",
                 "name": "Слой",
                 "parts": [{"shape": "box", "center_mm": [SIDE_U / 2, SIDE_V / 2, 0.0],
                            "size_mm": [SIDE_U * 2, SIDE_V * 2, DEFAULT_TOLERANCE_MM]}]}
    with pytest.raises(GeometryRefusal) as caught:
        build_body(thin_in_z)
    assert caught.value.code == "thin_body"


def test_a_healthy_body_is_not_newly_refused_in_any_of_the_frames():
    """There is no false refusal: the same three rotations build fine at a legal thickness."""
    good = [sliver_op(DEFAULT_TOLERANCE_MM * 5), cap_op(DEFAULT_TOLERANCE_MM * 5),
            {"op": "create_solid_extrusion", "id": "plate",
             "profile": {"shape": "rect", "origin": [0, 0], "size_mm": [SIDE_U, SIDE_V]},
             "height_mm": 200.0, "plane": TILT, "category": "generic", "name": "Плита"}]
    for operation in good:
        facts = _measure(build_body(operation), _kernel())
        assert facts["solid_count"] == 1 and facts["volume_mm3"] > 0.0


def test_the_threshold_is_the_tolerance_the_bundle_carries_and_not_a_literal():
    """The thinness threshold is THE SAME tolerance that ends up in the
    body's manifest.

    A second literal placed next to it would match it only until the
    neighbor's next edit. Here the threshold moves: at half the tolerance the
    same plate is legal, at double it is refused, and both outcomes come from
    ONE number.
    """
    thickness = DEFAULT_TOLERANCE_MM
    build_body(sliver_op(thickness), modeling_tolerance_mm=thickness / 2)
    with pytest.raises(GeometryRefusal) as caught:
        build_body(sliver_op(thickness), modeling_tolerance_mm=thickness * 2)
    assert caught.value.code == "thin_body"


def test_the_law_of_the_sliver_comes_from_contour_and_not_from_this_file():
    """Both declared shapes are legal under CONTOUR: there is no thinness in
    them.

    A pin against the SUBJECT: if the profile's side dropped below
    `contour.SHAPE_SIDE_MIN_MM`, the refusal would come from CONTOUR, and the
    whole file would be proving someone else's claim.
    """
    for profile in (sliver_op(DEFAULT_TOLERANCE_MM / 2)["profile"],
                    sliver_op(DEFAULT_TOLERANCE_MM / 2)["parts"][0]["profile"]):
        region = contour.validate_region({"outer": profile}, [], "probe", "profile", [])
        assert region is not None
        x0, y0, x1, y1 = contour.region_bbox(region)
        assert min(x1 - x0, y1 - y0) > contour.SHAPE_SIDE_MIN_MM
