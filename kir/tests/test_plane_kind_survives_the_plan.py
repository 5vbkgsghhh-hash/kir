"""THE SKETCH PLANE MUST SURVIVE ALL FOUR PLACES WHERE A VALUE'S KIND LIVES.

WHY THIS SUITE WAS WRITTEN BEFORE THE FIRST LIVE RUN. On 20.08.2026 this
house paid for a named class of defect with a spline: the value's kind lived
in the Python object's TYPE and did not survive
`midend._canonical_json`. The lesson is recorded in the canon verbatim —
**"a value's kind lives in FOUR places: emission and the witness remember it
on their own, CANONICALIZATION and the REVERSE PATH never remember it"**.
The gate stood at 2360/2360 green, the targeted tests too: not one of them
ever crossed the serialization boundary.

Here all four are named by name, and each carries a check CAPABLE OF
FAILING:

    1. CANONICALIZATION  `_canonical_json` -> `json.loads` -> the value is
                    the same, and the signature TELLS APART two different
                    planes;
    2. EMISSION      the frame travels as a `Transform`, the normal as the
                    extrusion direction, and a dropped plane prints THE SAME
                    BYTES AS BEFORE;
    3. THE WITNESS    end faces are located by the PLANE's normal, the
                    bounding box is computed by the rotated profile's
                    support function;
    4. THE REVERSE PATH `program_source` neither rounds nor shifts unit
                    vectors, and `family_recipe` reads the frame from Revit.

🔴 THE FOURTH PLACE HERE IS NOT A FORMALITY: without declaring the kind of
`normal` and `x_dir`, they are ordinary three-number lists, indistinguishable
from a point. `_round_mm` would round [0.7071, 0.7071, 0] to
[1.0, 1.0, 0.0], `_shift` would subtract the local frame's origin from a
DIRECTION. Both edits produce a legitimate-looking list and crash nowhere.
"""
from __future__ import annotations

import json
import math
import unittest

from kir import contour as C
from kir import plane as PL
from kir import solid_emit as SE
from kir.decompile import program_source as PS
from kir.midend import _canonical_json


def _plane(normal=(0.0, -1.0, 0.0), x_dir=(1.0, 0.0, 0.0),
           origin=(3000.0, 5000.0, 900.0)) -> dict:
    diags: list = []
    out = PL.validate_plane(
        {"origin_mm": list(origin), "normal": list(normal),
         "x_dir": list(x_dir)}, "W1", "plane", diags)
    assert out is not None and not diags, diags
    return out


def _region(w=1200.0, h=2100.0) -> dict:
    diags: list = []
    out = C.validate_region(
        {"outer": {"shape": "rect", "origin": [0, 0], "size_mm": [w, h]}},
        None, "W1", "profile", diags)
    assert out is not None and not diags, diags
    return out


def _op(plane=None, **extra) -> dict:
    op = {"id": "W1", "category": "generic_model", "name": "проём",
          "height_mm": 200.0, "__region__": _region(), "profile": {}}
    if plane is not None:
        op["plane"] = plane
    op.update(extra)
    return op


class PlaceOneTheCanonicalSignature(unittest.TestCase):
    """CANONICALIZATION. The place that never gets remembered."""

    def test_the_value_survives_the_json_round_trip_UNCHANGED(self) -> None:
        plane = _plane()
        back = json.loads(_canonical_json({"plane": plane}))["plane"]
        self.assertEqual(back, plane)
        # AND THE TYPE too: lists, not tuples. A tuple would have gone out
        # as an array and come back as a list — a plan reread from the
        # signature would stop being equal to itself as a Python object.
        # This is exactly how the spline lost its kind.
        for key in ("origin_mm", "normal", "x_dir"):
            self.assertIsInstance(plane[key], list)
            self.assertIsInstance(back[key], list)

    def test_two_DIFFERENT_planes_get_DIFFERENT_signatures(self) -> None:
        """Narrowness control: a signature that does not tell planes apart
        is green forever."""
        a = _canonical_json(_op(_plane()))
        b = _canonical_json(_op(_plane(normal=(0.0, 1.0, 0.0))))
        self.assertNotEqual(a, b)
        # And a rotation WITHIN the plane must also be distinguished: it
        # changes neither area, nor volume, nor end-face area — i.e. three
        # of the four witnesses do not see it, and the signature remains the
        # only guard."""
        c = _canonical_json(_op(_plane(x_dir=(0.0, 0.0, 1.0))))
        self.assertNotEqual(a, c)

    def test_the_emitter_sees_the_plane_AFTER_the_round_trip(self) -> None:
        """🔴 THE SERIALIZATION BOUNDARY IS CROSSED HERE, NOT BYPASSED.

        The spline check that never existed consisted of exactly this:
        validation and emission were called DIRECTLY, and the signature sits
        between them. Here the plan is run through `_canonical_json` and
        parsed back, and the emitter gets exactly what it would get in prod.
        """
        op = _op(_plane())
        region = op.pop("__region__")
        revived = json.loads(_canonical_json(op))
        revived["__region__"] = region
        _d, create, _c, _r = SE.emit_solid_extrusion(revived, "2023", "S")
        self.assertIn("__pf_tf_W1.BasisZ = new XYZ(0.0, -1.0, 0.0);", create)
        self.assertIn("CreateExtrusionGeometry(__lps_W1, "
                      "new XYZ(0.0, -1.0, 0.0), U(200.0))", create)


class PlaceTwoTheEmission(unittest.TestCase):
    """EMISSION. Plus the requirement for whose sake the kind was made
    OPTIONAL."""

    def test_an_ABSENT_plane_emits_the_SAME_BYTES_as_before_the_wave(self) -> None:
        """A dropped plane prints NOT ONE extra character.

        Not "equivalent text" but the SAME: the parity ratchet compares
        bytes, and a shared way of writing it (`DotProduct(new XYZ(0,0,1))`
        instead of `.Z`) would shift EVERY existing body.
        """
        _d, create, checks, _r = SE.emit_solid_extrusion(_op(), "2023", "S")
        self.assertIn("CreateExtrusionGeometry(__lps_W1, XYZ.BasisZ, U(200.0))",
                      create)
        self.assertNotIn("Transform __pf_tf_", create)
        cap = [c for c in checks if c.obligation_key == "cap_area"][0]
        self.assertIn("Math.Abs(__pf_W1.FaceNormal.Z) > 0.999999", cap.reader_cs)
        self.assertNotIn("DotProduct", cap.reader_cs)

    def test_the_extrusion_runs_along_the_NORMAL_not_along_Z(self) -> None:
        """🔴 WITHOUT THIS THE BODY WOULD BECOME A SLANTED PRISM, AND ON A
        VERTICAL FACE — A FLAT SHEET OF ZERO VOLUME.

        The profile is rotated into the wall's plane, and if the extrusion
        stayed along +Z, the volume would drop to A·h·|N·Z|, i.e. to zero
        when N ⊥ Z.
        """
        _d, create, _c, _r = SE.emit_solid_extrusion(_op(_plane()), "2023", "S")
        self.assertIn("new XYZ(0.0, -1.0, 0.0), U(200.0))", create)
        self.assertNotIn("XYZ.BasisZ", create)


class PlaceThreeTheWitness(unittest.TestCase):
    """THE WITNESS. Three obligations, each of which must change together
    with the frame."""

    def _checks(self, plane):
        return {c.obligation_key: c
                for c in SE.emit_solid_extrusion(_op(plane), "2023", "S")[2]}

    def test_the_cap_witness_follows_the_PLANE_normal(self) -> None:
        cap = self._checks(_plane())["cap_area"]
        self.assertIn("FaceNormal.DotProduct(new XYZ(0.0, -1.0, 0.0))",
                      cap.reader_cs)

    def test_the_bbox_is_the_profile_CARRIED_onto_the_plane(self) -> None:
        """A 1200×2100 opening on the wall face y=5000, extruded 200 inward.

        Independently: X 3000..4200 (width along +X), Z 900..3000 (height
        along +Z), Y 4800..5000 (extrusion 200 mm along the normal -Y). Not
        one of these six numbers would match the profile's planar bounding
        box.
        """
        bbox = self._checks(_plane())["bbox"]
        self.assertIn("ожидалось X 3000.0..4200.0 · Y 4800.0..5000.0 "
                      "· Z 900.0..3000.0", bbox.verdict_cs)

    def test_the_bbox_is_EXACT_for_an_ARC_on_a_tilted_plane(self) -> None:
        """🔴 EXACT, NOT SAMPLED, AND WITH NO SECOND COPY OF THE ARC LAW.

        A circle r=1000 in a plane tilted 45° around the world X axis. The
        circle's world bounding box along Y and Z equals exactly
        r·cos45 = 707.107 — a value sampling by chords does NOT give, while
        the support function gives it in closed form."""
        b = math.tan(math.radians(90.0) / 4.0)
        pts = [[1000.0, 0.0], [0.0, 1000.0], [-1000.0, 0.0], [0.0, -1000.0]]
        edges = [(pts[k], pts[(k + 1) % 4], b) for k in range(4)]
        c = 1.0 / math.sqrt(2.0)
        plane = _plane(normal=(0.0, -c, c), x_dir=(1.0, 0.0, 0.0),
                       origin=(0.0, 0.0, 0.0))
        box = SE._plane_profile_box(plane, ({"outer": edges},), (0.0,))
        self.assertAlmostEqual(box[0], -1000.0, places=6)   # X: the full radius
        self.assertAlmostEqual(box[3], 1000.0, places=6)
        self.assertAlmostEqual(box[1], -1000.0 * c, places=6)   # Y: cos 45
        self.assertAlmostEqual(box[4], 1000.0 * c, places=6)
        self.assertAlmostEqual(box[2], -1000.0 * c, places=6)   # Z: cos 45
        self.assertAlmostEqual(box[5], 1000.0 * c, places=6)

    def test_the_planar_bbox_is_UNCHANGED_by_the_generalisation(self) -> None:
        """Narrowness control: generalizing the support function did not
        shift the planar bounding box by ONE BIT — neither for a straight
        segment nor for an arc."""
        b = math.tan(math.radians(90.0) / 4.0)
        pts = [[1000.0, 0.0], [0.0, 1000.0], [-1000.0, 0.0], [0.0, -1000.0]]
        edges = [(pts[k], pts[(k + 1) % 4], b) for k in range(4)]
        x0, y0, x1, y1 = C.edges_bbox(edges)
        cand = C.extreme_candidates(edges, ((1.0, 0.0), (0.0, 1.0)))
        self.assertEqual((x0, x1), (min(p[0] for p in cand),
                                    max(p[0] for p in cand)))
        self.assertEqual((y0, y1), (min(p[1] for p in cand),
                                    max(p[1] for p in cand)))


class PlaceFourTheReversePass(unittest.TestCase):
    """THE REVERSE PATH. The place that never gets remembered — along with
    the third."""

    _PLANE = {"origin_mm": [1000.4, 2000.6, 3000.0],
              "normal": [0.7071067811865476, 0.7071067811865476, 0.0],
              "x_dir": [0.0, 0.0, 1.0]}

    def test_rounding_to_the_millimetre_does_NOT_touch_the_unit_vectors(self) -> None:
        """🔴 WITHOUT DECLARING THE KIND, THE NORMAL WOULD BE ROUNDED TO
        [1.0, 1.0, 0.0].

        A plane at 45° would end up at a different angle, and the vector's
        length would become 1.41. The number here is not hypothetical — it
        is printed by the very same `_round_mm` that sits in prod once
        `FREE_KEYS` is removed.
        """
        out = PS._round_by_kind("create_solid_extrusion", "plane", self._PLANE,
                                PS.param_kinds())
        self.assertEqual(out["normal"], self._PLANE["normal"])
        self.assertEqual(out["x_dir"], self._PLANE["x_dir"])
        # While the origin IS a real world point, and it is rounded like
        # everything else.
        self.assertEqual(out["origin_mm"], [1000.0, 2001.0, 3000.0])
        # Narrowness control: the same rounder BREAKS a bare vector.
        self.assertEqual(PS._round_mm(self._PLANE["normal"]), [1.0, 1.0, 0.0])

    def test_the_local_frame_shift_moves_the_ORIGIN_and_not_the_DIRECTIONS(self) -> None:
        """A shift into the apartment's local frame is a translation, not a
        rotation."""
        out = PS._shift(self._PLANE, 500.0, 700.0, "plane")
        self.assertEqual(out["origin_mm"], [500.4, 1300.6, 3000.0])
        self.assertEqual(out["normal"], self._PLANE["normal"])
        self.assertEqual(out["x_dir"], self._PLANE["x_dir"])

    def test_the_plane_is_PRINTED_back_as_program_source(self) -> None:
        """Reading it and not printing it is the same as never reading it."""
        ops = [{"op": "create_solid_extrusion", "id": "W1",
                "category": "generic_model", "name": "проём", "height_mm": 200,
                "profile": {"outer": {"shape": "poly",
                                      "points_mm": [[0, 0], [1200, 0],
                                                    [1200, 2100]]}},
                "plane": self._PLANE}]
        text = PS.render_source([{"ops": ops}]).parts[0].text
        self.assertIn("plane={", text)
        self.assertIn("0.7071067811865476", text)


class TheKindIsRegisteredEverywhereTheRegistryDemands(unittest.TestCase):
    """REGISTRY LOCKS. All three are independent, and each catches its own
    thing."""

    def test_the_kind_is_known_to_the_registry_the_sdk_and_the_course(self) -> None:
        from kir import spec
        from kir.course import expressiveness as EX
        from kir import sdk

        self.assertIn("plane", spec.PARAM_KINDS)
        self.assertIn("plane", EX.CENSUS)
        self.assertIn("plane", sdk.PLAIN_KINDS)
        self.assertIn("plane", PS.MM_KINDS)

    def test_the_schema_the_model_sees_matches_the_validator(self) -> None:
        """A schema allowing something OTHER than what the validator allows
        gives a refusal on a LEGITIMATE program — paid for on 16.08.2026 on
        contour shapes, three cases out of three."""
        from kir import schema_gen, spec

        schema = schema_gen._op_schema(spec.OPS["create_solid_extrusion"])
        props = schema["properties"]["plane"]
        self.assertEqual(sorted(props["required"]), sorted(PL.PLANE_FIELDS))
        self.assertFalse(props["additionalProperties"])


class TheLawsOfThePlaneRefuseInsteadOfFixing(unittest.TestCase):

    def _diags(self, value):
        diags: list = []
        out = PL.validate_plane(value, "W1", "plane", diags)
        return out, diags

    def test_a_non_perpendicular_x_dir_is_REFUSED_not_projected(self) -> None:
        """Silent orthogonalization is exactly the input edit that cost
        96.77% of the groups. The mistake is either in the normal or in the
        direction, and only the author knows which.
        """
        out, diags = self._diags({"origin_mm": [0, 0, 0], "normal": [0, 0, 1],
                                  "x_dir": [1, 0, 0.5]})
        self.assertIsNone(out)
        self.assertIn("не лежит В плоскости", diags[0].message_ru)

    def test_a_missing_x_dir_is_REFUSED_and_says_WHY_it_is_required(self) -> None:
        out, diags = self._diags({"origin_mm": [0, 0, 0], "normal": [0, 0, 1]})
        self.assertIsNone(out)
        self.assertIn("выбрал бы Revit", diags[0].message_ru)

    def test_the_vectors_come_back_UNIT(self) -> None:
        out, _ = self._diags({"origin_mm": [0, 0, 0], "normal": [0, 0, 7],
                              "x_dir": [3, 0, 0]})
        self.assertEqual(out["normal"], [0.0, 0.0, 1.0])
        self.assertEqual(out["x_dir"], [1.0, 0.0, 0.0])

    def test_plane_and_base_z_together_are_REFUSED(self) -> None:
        """Two ways to say one thing is our named class of defect. Silently
        picking one would mean the other is lost without a word."""
        from kir import authoring_validation as AV

        diags: list = []
        AV.validate({"op": "create_solid_extrusion", "id": "W1",
                     "category": "generic_model", "name": "п",
                     "height_mm": 200.0, "base_z_mm": 100.0,
                     "plane": {"origin_mm": [0, 0, 0], "normal": [0, 0, 1],
                               "x_dir": [1, 0, 0]},
                     "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                           "size_mm": [1000, 1000]}}},
                    "create_solid_extrusion", 0, "W1", diags)
        self.assertTrue(any("вместе не принимаются" in d.message_ru
                            for d in diags), [d.message_ru for d in diags])

    def test_a_horizontal_plane_at_z_is_EXACTLY_todays_base_z(self) -> None:
        """The claim "a dropped plane means exactly this" is checkable only
        when "this" is written down as a VALUE, not as prose."""
        self.assertTrue(PL.is_horizontal(PL.horizontal_at(3300.0)))
        self.assertFalse(PL.is_horizontal(_plane()))
        # An origin shifted in-plane is DIFFERENT geometry, and base_z does
        # not carry it.
        self.assertFalse(PL.is_horizontal(
            _plane(normal=(0, 0, 1), x_dir=(1, 0, 0), origin=(500, 0, 3300))))
        # A frame rotated within the plane is different too.
        self.assertFalse(PL.is_horizontal(
            _plane(normal=(0, 0, 1), x_dir=(0, 1, 0), origin=(0, 0, 3300))))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
