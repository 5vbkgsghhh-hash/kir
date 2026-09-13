"""A shape the language ACCEPTS must reach the body — or the refusal carries a name.

🔴 WHAT WAS MEASURED 07.09.2026 BEFORE THE FIX. `kir.geometry_authoring`
parsed the profile with its OWN reader: it understood `poly` and `rect`,
and understood NEITHER a rotated rectangle, NOR the `l` shape, NOR
openings, NOR arcs, NOR a sketch plane that is tilted. Of the seven
shapes legal under `contour.SHAPE_FORMS` and under the registry
(`ops_solid`), the body calculator built exactly ONE:

    rect                OK
    rect + rotation_deg REFUSED unsupported_profile
    poly + arcs         REFUSED unsupported_profile
    poly + splines      REFUSED unsupported_profile
    l                   REFUSED unsupported_profile
    {outer, holes}      REFUSED unsupported_profile
    plane (tilted)      REFUSED unsupported_op

This is "a dictionary instead of a mechanism": the registry stated the
shape, the body calculator did not know it, and the two could silently
diverge further from there. The fix removes the SECOND reader: the shape
is now read by `contour.validate_region` — the same sole carrier of the
law that the compiler itself reads it by.

🔴 WHAT THIS IS CHECKED BY, RATHER THAN "IT DID NOT CRASH". The
instrument here is the REGISTRY'S POSTCONDITION, verbatim: «solid volume
== profile area * extrusion height, both closed-form at compile time».
The area is computed by `contour.region_measures` (Green's theorem,
exact for arcs too), the volume by OCCT on the built body. The match
between these two numbers on an arc, a rotation, an opening, and a
tilted plane IS the claim.

WHAT THIS DOES NOT SAY: not a single word about Revit. Equality between
OCCT's volume and Revit's is NOT CLAIMED — the limit is named in
`docs/GEOMETRY_OCCT_LIMITS_RU.md`.
"""
from __future__ import annotations

import math

import pytest

pytest.importorskip("OCP.BRepPrimAPI", reason="optional real OCCT backend")

from kir import contour
from kir.geometry_authoring import DEFAULT_TOLERANCE_MM, GeometryRefusal, build_body
from kir.occt_geometry import _kernel, _measure


TILT = {"origin_mm": [0, 0, 0], "normal": [0, 0.7071067811865476, 0.7071067811865476],
        "x_dir": [1, 0, 0]}
#: A vertical plane — a wall's face. This is the MOST expensive case:
#: leave the extrusion direction at +Z, and the volume would become
#: A·h·|N·Z| = EXACTLY ZERO.
WALL_FACE = {"origin_mm": [0, 0, 3000], "normal": [0, 1, 0], "x_dir": [1, 0, 0]}

RECT = {"shape": "rect", "origin": [0, 0], "size_mm": [4000, 3000]}
ROTATED = {"shape": "rect", "origin": [0, 0], "size_mm": [4000, 3000], "rotation_deg": 30}
ARCED = {"shape": "poly", "points_mm": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
         "arcs": [{"edge": 1, "bulge": 0.4}]}
ELL = {"shape": "l", "origin": [0, 0], "size_mm": [4000, 3000], "cut_mm": [1000, 1000]}
HOLED = {"outer": RECT, "holes": [{"shape": "rect", "origin": [1000, 1000], "size_mm": [1000, 1000]}]}


def extrusion(profile, *, height=1000.0, **extra):
    return {"op": "create_solid_extrusion", "id": "x", "profile": profile,
            "height_mm": height, "category": "generic", "name": "Тело", **extra}


def facts(operation):
    return _measure(build_body(operation), _kernel())


def declared_area(profile):
    """The area the LANGUAGE already knows how to name a closed shape."""
    wrapped = profile if "outer" in profile else {"outer": profile}
    region = contour.validate_region(wrapped, [], "probe", "profile", [])
    assert region is not None
    return contour.region_measures(region)["area_mm2"]


@pytest.mark.parametrize("name,profile", [
    ("rect", RECT), ("rect+rotation_deg", ROTATED), ("poly+arcs", ARCED),
    ("l", ELL), ("outer+holes", HOLED),
])
def test_every_shape_contour_accepts_reaches_a_solid_of_the_declared_volume(name, profile):
    """THE REGISTRY'S POSTCONDITION on the built body: V == area × height."""
    measured = facts(extrusion(profile))
    assert measured["solid_count"] == 1
    assert measured["volume_mm3"] == pytest.approx(declared_area(profile) * 1000.0, rel=1e-9)


def test_a_rotated_rect_is_actually_rotated_and_not_merely_accepted():
    """CONTROL: an UNrotated rectangle could give the same volume too."""
    straight, turned = facts(extrusion(RECT)), facts(extrusion(ROTATED))
    assert straight["volume_mm3"] == pytest.approx(turned["volume_mm3"], rel=1e-9)
    # The footprint of a 4000×3000 box rotated 30° is computed in closed form.
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    corners = [(0., 0.), (4000. * c, 4000. * s), (4000. * c - 3000. * s, 4000. * s + 3000. * c),
               (-3000. * s, 3000. * c)]
    assert turned["bbox_min_mm"][:2] == pytest.approx([min(p[k] for p in corners) for k in (0, 1)], abs=1e-6)
    assert turned["bbox_max_mm"][:2] == pytest.approx([max(p[k] for p in corners) for k in (0, 1)], abs=1e-6)
    assert straight["bbox_max_mm"][:2] != pytest.approx(turned["bbox_max_mm"][:2], abs=1.0)


def test_an_arc_is_a_circle_arc_and_not_a_chord_of_eight():
    """ARC CONTROL: an 8-chord CONTOUR sampling would have given a DIFFERENT number.

    `contour._sample_arc` is a deterministic sample taken FOR STATIC
    LAWS, and its area is SMALLER than the arc's area. If the body were
    built from the sample (the simplest way to "support arcs"), the
    volume would match the chorded figure, not the closed shape. What is
    checked is that a discrepancy exists and that the body stands on the
    side of the CLOSED SHAPE.
    """
    region = contour.validate_region({"outer": ARCED}, [], "probe", "profile", [])
    sampled = contour._shoelace(contour.edges_to_sample_poly(region["outer"]))
    exact = contour.region_measures(region)["area_mm2"]
    assert sampled < exact and (exact - sampled) / exact > 1e-4
    assert facts(extrusion(ARCED))["volume_mm3"] == pytest.approx(exact * 1000.0, rel=1e-9)


def test_a_hole_removes_material_and_adds_faces():
    """An opening is a subtraction, not a drawing: both the volume and the face count know this."""
    plain, holed = facts(extrusion(RECT)), facts(extrusion(HOLED))
    assert holed["volume_mm3"] == pytest.approx(plain["volume_mm3"] - 1000. * 1000. * 1000., rel=1e-9)
    assert holed["face_count"] == plain["face_count"] + 4


def test_a_sketch_plane_extrudes_along_its_normal_not_along_z():
    """🔴 THE SILENT ZERO THAT IS NOT THERE: on a wall's face, +Z would have given EXACTLY 0 mm³."""
    on_wall = facts(extrusion(RECT, height=200.0, plane=WALL_FACE))
    assert on_wall["volume_mm3"] == pytest.approx(4000. * 3000. * 200., rel=1e-9)
    # The extrusion runs along +Y (the normal), not along Z: the thickness along Y is exactly 200.
    extents = [b - a for a, b in zip(on_wall["bbox_min_mm"], on_wall["bbox_max_mm"])]
    assert extents == pytest.approx([4000., 200., 3000.], abs=1e-6)
    # A tilted plane: the volume is the same, but the box is no longer anyone's bounding box.
    tilted = facts(extrusion(RECT, height=200.0, plane=TILT))
    assert tilted["volume_mm3"] == pytest.approx(4000. * 3000. * 200., rel=1e-9)


def test_thinness_is_a_property_of_the_sketch_not_of_the_world_box():
    """A REFUSAL CONTROL that a world-space box would NOT have caught.

    A 4000×3000 slab 0.005 mm thick at 45° gives an axis-aligned box with
    all three edges in meters: the old `thin_body` check, by the
    RESULT's bounding box, would have said "fine". Thinness is asked
    about in the sketch's own plane.
    """
    with pytest.raises(GeometryRefusal) as caught:
        build_body(extrusion(RECT, height=DEFAULT_TOLERANCE_MM / 2, plane=TILT))
    assert caught.value.code == "thin_body"
    # A sketch that is thin IN PLAN never reaches this check at all:
    # CONTOUR rejects a side shorter than `SHAPE_SIDE_MIN_MM` earlier and
    # under its OWN name. The guard here is not "my code said thin_body",
    # but "no path gives silence".
    thin_sketch = {"shape": "rect", "origin": [0, 0], "size_mm": [4000, DEFAULT_TOLERANCE_MM / 2]}
    with pytest.raises(GeometryRefusal) as narrow:
        build_body(extrusion(thin_sketch, plane=TILT))
    assert narrow.value.code in ("thin_body", "unsupported_profile"), str(narrow.value)


@pytest.mark.parametrize("name,operation,code", [
    ("spline", extrusion({"shape": "poly", "points_mm": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
                          "splines": [{"edge": 1, "via_mm": [[4400, 1500]]}]}), "unsupported_profile"),
    ("grid anchor", extrusion({"shape": "rect", "origin": {"at_grid": ["A", "1"]},
                               "size_mm": [4000, 3000]}), "unsupported_profile"),
    ("plane + base_z_mm", extrusion(RECT, plane=TILT, base_z_mm=100.0), "unsupported_op"),
    ("plane without x_dir", extrusion(RECT, plane={"origin_mm": [0, 0, 0], "normal": [0, 0, 1]}),
     "unsupported_op"),
    ("open ring", extrusion({"shape": "poly", "points_mm": [[0, 0], [4000, 0]]}), "unsupported_profile"),
])
def test_what_the_language_does_not_accept_is_refused_by_name(name, operation, code):
    """The unsupported becomes neither empty geometry nor an exact zero."""
    with pytest.raises(GeometryRefusal) as caught:
        build_body(operation)
    assert caught.value.code == code, str(caught.value)
    assert str(caught.value).strip() and caught.value.code in str(caught.value)


def test_the_blend_refuses_a_hole_it_cannot_subtract():
    """`ThruSections` builds a SHELL from rings; it would silently lose an opening.

    🔴 THE REFUSAL CARRIES A NUMBER (08.09.2026). "The opening is not
    built" does not tell the author what the silence costs, and it costs
    EXACTLY the opening's volume: 1000×1000 mm over a 3000 mm run =
    3,000,000,000 mm³ of excess material. The number is computed by
    `contour.region_measures` (the same Green's-theorem integral the
    witness uses), not retyped here: an edit to the opening's shape
    moves it too.
    """
    operation = {"op": "create_solid_blend", "id": "x", "profile": HOLED,
                 "profile_top": {"shape": "rect", "origin": [500, 500], "size_mm": [3000, 2000]},
                 "height_mm": 3000, "category": "generic", "name": "Тело"}
    with pytest.raises(GeometryRefusal) as caught:
        build_body(operation)
    assert caught.value.code == "unsupported_profile" and "проём" in str(caught.value)
    region = contour.validate_region(HOLED, [], "probe", "profile", [])
    lost = sum(contour.region_measures(region)["hole_areas_mm2"]) * 3000.0
    assert f"{lost:.6g}" in str(caught.value), str(caught.value)
    # The next move is named by the same name the emission uses for it.
    assert "create_solid_boolean" in str(caught.value)


# ── TWO READERS OF ONE SHAPE DO NOT DIVERGE (08.09.2026) ──────────────────────
#
# 🔴 WHAT WAS MEASURED. Wave 9 carried the task of BUILDING a spline in the
# body's profile and CUTTING an opening after `ThruSections`.
# Reconnaissance by the compiler showed that the language ACCEPTS NEITHER
# shape for any of the three `BODY_OPS`:
#
#     create_solid_extrusion + splines   ok=False  KIR-E010 (ground.py)
#     create_solid_blend + holes         ok=False  KIR-T004 (solid_emit.py)
#     the same boolean without a spline/opening    ok=True
#
# Had the body calculator built even one of these — the project would
# have had a BODY for a program that does not compile: the same disease
# of "two readers of one shape" this file was cured of on 07.09, just in
# reverse. So both stay a refusal, and the refusal TAKES THE LAW FROM THE
# SOLE CARRIER — `contour.SPLINE_WITNESSED_OPS` and the
# `CreateBlendGeometry` signature — not from its own reasoning. The pin
# below holds the EQUIVALENCE of the two readers, and holds it FROM THE
# SUBJECT: it asks the real compiler, not a literal.


def _compiles(build):
    from kir import dsl
    from kir.compiler import compile_program

    dsl.reset(intent="проверка равносильности двух читателей формы")
    build(dsl)
    return compile_program(dsl.build())


SPLINE_POLY = {"shape": "poly", "points_mm": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
               "splines": [{"edge": 1, "via_mm": [[4400, 1500]]}]}


@pytest.mark.parametrize("name,author,operation", [
    ("сплайн в выдавливании",
     lambda dsl: dsl.create_solid_extrusion(profile={"outer": SPLINE_POLY}, height_mm=1000,
                                            category="mass", name="Т", id="x"),
     extrusion(SPLINE_POLY)),
    ("проём в бленде",
     lambda dsl: dsl.create_solid_blend(profile=HOLED,
                                        profile_top={"outer": {"shape": "rect", "origin": [500, 500],
                                                               "size_mm": [3000, 2000]}},
                                        height_mm=3000, category="mass", name="Т", id="x"),
     {"op": "create_solid_blend", "id": "x", "profile": HOLED,
      "profile_top": {"shape": "rect", "origin": [500, 500], "size_mm": [3000, 2000]},
      "height_mm": 3000, "category": "generic", "name": "Тело"}),
])
def test_the_body_computer_refuses_exactly_what_the_language_refuses(name, author, operation):
    """The compiler refused -> there is no body. The compiler accepted -> there is a body."""
    outcome = _compiles(author)
    assert not outcome.ok, f"{name}: язык принял — тогда и тело обязано строиться"
    with pytest.raises(GeometryRefusal) as caught:
        build_body(operation)
    assert caught.value.code == "unsupported_profile", str(caught.value)


def test_a_form_the_language_does_accept_still_reaches_a_body():
    """🔴 EQUIVALENCE CONTROL: without it the pin above would have passed with "always refuse".

    A check that requires only refusals is green for a calculator that
    builds NOTHING AT ALL. Here we take a shape the compiler ACCEPTS, and
    a body for it must exist.
    """
    outcome = _compiles(lambda dsl: dsl.create_solid_extrusion(
        profile={"outer": ARCED}, height_mm=1000, category="mass", name="Т", id="x"))
    assert outcome.ok, [d.message_ru for d in (outcome.diagnostics or [])]
    assert facts(extrusion(ARCED))["solid_count"] == 1


def test_the_spline_refusal_reads_the_registry_of_witnessed_ops_and_not_its_own_rule():
    """The spline refusal names the LIST that grounding judges it against.

    🔴 A PIN FROM THE SUBJECT, NOT FROM THE TEXT. There used to be its own
    argument here ("a Catmull-Rom sample is not `HermiteSpline.Create`")
    — correct, but SECONDARY: should a solid op ever gain a spline
    witness, the calculator would keep refusing for a reason already
    overturned, and the two would silently diverge. What is checked below
    is that the calculator's answer CHANGES together with the list.
    """
    from kir.geometry_authoring import BODY_OPS

    # Not a single body op expresses a spline today — that is a fact of
    # the LIST, and it is read here, not retyped.
    assert not set(BODY_OPS) & contour.SPLINE_WITNESSED_OPS
    with pytest.raises(GeometryRefusal) as caught:
        build_body(extrusion(SPLINE_POLY))
    assert "SPLINE_WITNESSED_OPS" in str(caught.value)
    assert "KIR-E010" in str(caught.value)


def test_the_spline_refusal_changes_its_reason_when_the_registry_changes(monkeypatch):
    """CONTROL OF THE SAME LIST: add the op to the list — the reason for the refusal changes.

    The refusal stays (this calculator does not build a curve), but it
    stops lying about the language. This is exactly the difference
    between "I read the law" and "I repeat it."
    """
    monkeypatch.setattr(contour, "SPLINE_WITNESSED_OPS",
                        frozenset(set(contour.SPLINE_WITNESSED_OPS) | {"create_solid_extrusion"}))
    with pytest.raises(GeometryRefusal) as caught:
        build_body(extrusion(SPLINE_POLY))
    assert caught.value.code == "unsupported_profile"
    assert "ВЫРАЖАЕТ" in str(caught.value) and "KIR-E010" not in str(caught.value)


# ── THE REFUSAL NAMES THE AUTHOR'S OP, NOT THE MODULE'S NAME ────────────────
#
# 🔴 FOUND BY SELF-REVIEW ON 07.09.2026, AFTER THE FIX WAS ALREADY GREEN.
# `contour.validate_region` and `plane.validate_plane` put `op_id` into
# EVERY one of their diagnostics, and the body calculator was passing in
# the string `"geometry_authoring"` — the name of the MODULE. The refusal
# was honest about the field («profile.outer.origin: точка — [x,y] мм…»)
# and lied about the addressee: the author has ten operations in their
# program, and WHICH of them refused, they could not tell from the
# refusal. The instrument below holds both carriers: `op_id` inside the
# diagnostic, and the op's name in the refusal's text.

BAD_PROFILE = {"shape": "rect", "origin": {"at_grid": ["A", "1"]}, "size_mm": [4000, 3000]}


def test_a_refusal_names_the_authors_op_and_not_the_module():
    """Two ops with THE SAME invalid shape refuse with DIFFERENT messages."""
    first = extrusion(BAD_PROFILE)
    second = extrusion(BAD_PROFILE)
    first["id"], second["id"] = "atrium-void", "podium-plinth"
    messages = []
    for operation in (first, second):
        with pytest.raises(GeometryRefusal) as caught:
            build_body(operation)
        assert caught.value.code == "unsupported_profile"
        messages.append(str(caught.value))
    assert "atrium-void" in messages[0] and "podium-plinth" in messages[1]
    assert messages[0] != messages[1]
    # The MODULE's name no longer pretends to be the addressee.
    assert not any("geometry_authoring" in message for message in messages)


def test_the_op_id_reaches_the_contour_diagnostic_itself(monkeypatch):
    """CONTROL: `op_id` travels into CONTOUR's own diagnostic, not only into the text.

    Swap the op's name in `_region` back to a constant — this pin goes
    red first, before the refusal's text even diverges.
    """
    from kir import contour as contour_module

    seen: list = []
    original = contour_module.validate_region

    def spy(region, grids_pool, oid, field, diags):
        seen.append((oid, field))
        return original(region, grids_pool, oid, field, diags)

    monkeypatch.setattr(contour_module, "validate_region", spy)
    build_body({**extrusion(RECT), "id": "tower-c-shell"})
    assert seen == [("tower-c-shell", "profile")]


def test_a_plane_refusal_names_the_authors_op_too():
    """The plane reads `kir.plane`, and its diagnostic is addressed the same way."""
    operation = extrusion(RECT, plane={"origin_mm": [0, 0, 0], "normal": [0, 0, 1]})
    operation["id"] = "wall-opening"
    with pytest.raises(GeometryRefusal) as caught:
        build_body(operation)
    assert caught.value.code == "unsupported_op"
    assert "wall-opening" in str(caught.value)
    assert "geometry_authoring" not in str(caught.value)


def test_an_op_without_an_id_is_named_and_not_silently_blank():
    """An op without an `id` gets a NAMED location, not an empty string in the refusal."""
    with pytest.raises(GeometryRefusal) as caught:
        build_body({"op": "create_solid_extrusion", "profile": BAD_PROFILE,
                    "height_mm": 1000.0, "category": "generic", "name": "Тело"})
    assert "<оп без id>" in str(caught.value)
