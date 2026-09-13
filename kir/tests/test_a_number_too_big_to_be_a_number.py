"""A NUMBER THAT WILL NOT REACH REVIT IS REFUSED, NOT LEFT TO CRASH THE COMPILER.

THREE PLACES, ONE CLASS, AND THE CLASS IS CALLED OVERFLOW (measured
04.09.2026). KIR's numeric boundary is double. JSON does not know this:
`10**400` is a legitimate integer, and `json.loads` accepts `Infinity` and
`NaN` by default (verified below). Wherever a guard asked only
`isinstance(x, (int, float))`, these values got through and broke LATER —
either with a crash, or, worse, silently.

    FC-03  `faceref.validate_face_sel`, `predicate.normal`
           `[10**400, 0, 0]` -> `OverflowError` OUT, bypassing diagnostics
           control: `[1, 0, 0]` was accepted
    FC-04  `ops_boolean.validate_parts`, `center_mm`
           `[10**400, 0, 0]` -> `OverflowError`; `[16_000_001, 0, 0]` WAS
           ACCEPTED — outside the model's working scope (~16 km), there was
           no limit at all; control: `[0, 0, 0]` was accepted
    FC-05  `plane.validate_plane`, `normal`/`x_dir`
           `[1e308, 1e308, 0]` -> ACCEPTED, `normal` became
           `[0.0, 0.0, 0.0]`, the diagnostics list was EMPTY; control:
           `[0, 0, 1]` was accepted correctly

🔴 THE WORST OF THE THREE IS THE THIRD, AND PRECISELY BECAUSE IT DID NOT
CRASH. The chain broke in three places in a row, and none of them went
red: `_norm` gave `inf`, the guard `_norm(v) < MIN_VECTOR_LEN` stayed
silent (`inf` is not smaller), `_unit` divided finite components by `inf`
and returned EXACTLY zero, and the orthogonality check `|x̂·n̂| = 0` passed
trivially — a dot product with zero is zero. What went out was a "plane"
with no direction, signed off by every check. A crash is at least visible.

WHAT THIS FILE DOES NOT TOUCH, AND THIS IS DELIBERATE:

* the LENGTH of the vector at `faceref`. The file's argument ("degeneracy
  is resolved at runtime by the native `XYZ.IsZeroLength()`; assigning a
  minimum length here would mean inventing a tolerance") remains valid and
  is not checked here by anything. Finiteness is not a tolerance: it is
  the condition for the number to become a `double` at all and reach
  Revit. It cannot be asked "at execution time" — there will be no
  execution, the compiler has already crashed;
* the UPPER bound on length at `plane`. There is none, and none is added:
  the length of a direction carries no meaning. The refusal is about
  exactly one thing — the sum of squares is not representable as a
  double, meaning there is NO direction at all;
* `[1e308, 1e308, 0]` at `faceref.predicate.normal`. It IS STILL ACCEPTED,
  and this is not an oversight: the components are finite, and the length
  there is computed by Revit ITSELF (`XYZ.IsZeroLength()` /
  `Normalize()` in the emitted C#), that is, the question has reached the
  one who answers it. At `plane` it is different — WE normalize, in
  Python, and silently. The difference between the two places is exactly
  the reason a refusal appeared at one and not at the other.
"""

from __future__ import annotations

import json
import math
import unittest

from kir.faceref import validate_face_sel
from kir.ops_boolean import validate_parts
from kir.plane import validate_plane
from kir.registry_base import COORD_LIMIT_MM

#: A legitimate JSON integer that has no counterpart among doubles. Not "a
#: strange input": `json.loads("[1" + "0"*400 + "]")` produces exactly this.
TOO_BIG_INT = 10 ** 400

#: Finite components whose SUM OF SQUARES is no longer finite.
OVERFLOWING_LENGTH = [1e308, 1e308, 0.0]


def _face_sel(normal) -> dict:
    return {"by": "face", "of": {"by": "ref", "value": "W1"},
            "predicate": {"normal": normal}}


def _validate_face(normal, diags: list):
    return validate_face_sel(_face_sel(normal), oid="OP1", field="of", i=None,
                             inner_ok=lambda v: True, diags=diags)


def _box(**kw) -> list:
    part = {"shape": "box", "center_mm": [0, 0, 0],
            "size_mm": [100, 100, 100]}
    part.update(kw)
    return [part]


def _plane(**kw) -> dict:
    pl = {"origin_mm": [0, 0, 0], "normal": [0, 0, 1], "x_dir": [1, 0, 0]}
    pl.update(kw)
    return pl


class TheParserItselfAdmitsNonNumbers(unittest.TestCase):
    """The denominator: where such values even come from in the first place.

    Without this test, the three refusals below would read as protection
    against a made-up input. The input is not made up — it is produced by
    the standard JSON parse.
    """

    def test_json_accepts_a_bigger_integer_than_double_holds(self) -> None:
        value = json.loads("[1" + "0" * 400 + "]")[0]
        self.assertEqual(value, TOO_BIG_INT)
        with self.assertRaises(OverflowError):
            float(value)

    def test_json_accepts_infinity_and_nan_by_default(self) -> None:
        self.assertEqual(json.loads('[Infinity]')[0], math.inf)
        self.assertTrue(math.isnan(json.loads('[NaN]')[0]))


class FaceNormalRefusesWhatCannotBecomeADouble(unittest.TestCase):
    """FC-03: `predicate.normal` crashed the compiler instead of refusing."""

    def test_the_ordinary_normal_is_accepted(self) -> None:
        # A POSITIVE EXAMPLE — also the control: the fix did not narrow acceptance.
        diags: list = []
        out = _validate_face([1, 0, 0], diags)
        self.assertEqual(diags, [])
        self.assertEqual(out["predicate"]["normal"], [1.0, 0.0, 0.0])

    def test_an_integer_beyond_double_is_a_typed_refusal_not_a_crash(self) -> None:
        # 🔴 FAIL CONTROL: on the old code this is an `OverflowError`, not a refusal.
        diags: list = []
        self.assertIsNone(_validate_face([TOO_BIG_INT, 0, 0], diags))
        self.assertEqual([d.code for d in diags], ["KIR-T001"])

    def test_infinity_and_nan_are_refused_too(self) -> None:
        # Not decoration: `{x!r}` prints such a value in C# as `inf`/`nan`,
        # which does not compile AT ALL. A refusal here is cheaper than a
        # CS error on the box.
        for bad in (math.inf, -math.inf, math.nan):
            with self.subTest(value=bad):
                diags: list = []
                self.assertIsNone(_validate_face([bad, 0, 0], diags))
                self.assertEqual([d.code for d in diags], ["KIR-T001"])

    def test_the_length_argument_is_not_broken(self) -> None:
        # THE FILE'S ARGUMENT STANDS INTACT: there is still no lower length
        # threshold. A tiny vector and an EXACTLY zero one are both
        # accepted here and resolved by Revit at runtime — exactly as was
        # recorded.
        for vec in ([0, 0, 0], [1e-300, 0, 0]):
            with self.subTest(vec=vec):
                diags: list = []
                self.assertIsNotNone(_validate_face(vec, diags))
                self.assertEqual(diags, [])


class PrimitiveCentreObeysTheCoordinateLimit(unittest.TestCase):
    """FC-04: the primitive's center had neither finiteness nor a scene limit."""

    def test_the_ordinary_centre_is_accepted(self) -> None:
        diags: list = []
        out = validate_parts(_box(), "OP1", "parts", 0, diags)
        self.assertEqual(diags, [])
        self.assertEqual(out[0]["center_mm"], [0.0, 0.0, 0.0])

    def test_the_far_side_of_the_limit_is_still_accepted(self) -> None:
        # A CONTROL IN THE OTHER DIRECTION: the limit did not eat
        # legitimate coordinates. Exactly at the boundary — it is accepted.
        diags: list = []
        out = validate_parts(_box(center_mm=[COORD_LIMIT_MM, 0, 0]),
                             "OP1", "parts", 0, diags)
        self.assertEqual(diags, [])
        self.assertEqual(out[0]["center_mm"][0], COORD_LIMIT_MM)

    def test_one_millimetre_past_the_limit_is_a_bounds_refusal(self) -> None:
        # 🔴 FAIL CONTROL: on the old code this was ACCEPTED silently.
        diags: list = []
        self.assertIsNone(validate_parts(_box(center_mm=[16_000_001, 0, 0]),
                                         "OP1", "parts", 0, diags))
        self.assertEqual([d.code for d in diags], ["KIR-T002"])
        # The refusal must NAME the limit — otherwise the advice cannot be acted on.
        self.assertIn(f"{COORD_LIMIT_MM:.0f}", diags[0].message_ru)

    def test_an_integer_beyond_double_is_a_typed_refusal_not_a_crash(self) -> None:
        # 🔴 FAIL CONTROL: on the old code, an `OverflowError` escapes.
        diags: list = []
        self.assertIsNone(validate_parts(_box(center_mm=[TOO_BIG_INT, 0, 0]),
                                         "OP1", "parts", 0, diags))
        self.assertEqual([d.code for d in diags], ["KIR-T001"])

    def test_every_other_number_of_the_part_refuses_the_same_way(self) -> None:
        # ONE HOLE, FIVE CARRIERS. `center_mm` was named in the audit, but
        # the same unguarded `float()` stood at the size, the radius, and
        # the height too: an `OverflowError` was measured at size_mm,
        # radius_mm, and the cylinder's height_mm AS WELL. Fixing one
        # carrier out of five would have left the defect in place under a
        # different name.
        cases = {
            "size_mm": _box(size_mm=[TOO_BIG_INT, 10, 10]),
            "radius_mm": [{"shape": "sphere", "center_mm": [0, 0, 0],
                           "radius_mm": TOO_BIG_INT}],
            "height_mm": [{"shape": "cylinder", "center_mm": [0, 0, 0],
                           "radius_mm": 100, "height_mm": TOO_BIG_INT}],
        }
        for field, parts in cases.items():
            with self.subTest(field=field):
                diags: list = []
                self.assertIsNone(
                    validate_parts(parts, "OP1", "parts", 0, diags))
                self.assertTrue(diags, f"{field}: отказа нет вовсе")


class APlaneWhoseNormalOverflowsIsRefused(unittest.TestCase):
    """FC-05: a length overflow made the normal zero, and the plane got accepted."""

    def test_the_ordinary_plane_is_accepted(self) -> None:
        diags: list = []
        out = validate_plane(_plane(), "OP1", "plane", diags)
        self.assertEqual(diags, [])
        self.assertEqual(out["normal"], [0.0, 0.0, 1.0])
        self.assertEqual(out["x_dir"], [1.0, 0.0, 0.0])

    def test_a_normal_whose_length_overflows_is_refused(self) -> None:
        # 🔴 FAIL CONTROL: on the old code it was ACCEPTED with an empty
        # diagnostics list, and `normal` was returned as `[0.0, 0.0, 0.0]`.
        diags: list = []
        self.assertIsNone(
            validate_plane(_plane(normal=OVERFLOWING_LENGTH),
                           "OP1", "plane", diags))
        self.assertEqual([d.code for d in diags], ["KIR-T002"])

    def test_an_x_dir_whose_length_overflows_is_refused_too(self) -> None:
        # The same guard on BOTH directions: there is nowhere for them to drift apart.
        diags: list = []
        self.assertIsNone(
            validate_plane(_plane(x_dir=OVERFLOWING_LENGTH),
                           "OP1", "plane", diags))
        self.assertEqual([d.code for d in diags], ["KIR-T002"])

    def test_no_accepted_plane_ever_carries_a_zero_direction(self) -> None:
        # A PROPERTY, NOT A SINGLE CASE. This is exactly what was being
        # violated: an accepted plane was returning a zero-length
        # direction. The condition is checked over everything that is
        # accepted at all.
        for name, pl in (("обычная", _plane()),
                         ("наклонная", _plane(normal=[1, 0, 1],
                                              x_dir=[1, 0, -1])),
                         ("длинные числа", _plane(normal=[1e150, 0, 0],
                                                  x_dir=[0, 1e150, 0]))):
            with self.subTest(name=name):
                diags: list = []
                out = validate_plane(pl, "OP1", "plane", diags)
                self.assertIsNotNone(out, diags)
                for key in ("normal", "x_dir"):
                    length = math.sqrt(sum(c * c for c in out[key]))
                    self.assertAlmostEqual(length, 1.0, places=9,
                                           msg=f"{key} длиной {length}")

    def test_the_lower_threshold_still_stands(self) -> None:
        # A CONTROL IN THE OTHER DIRECTION: the upper guard did not replace the lower one.
        diags: list = []
        self.assertIsNone(
            validate_plane(_plane(normal=[0, 0, 0]), "OP1", "plane", diags))
        self.assertEqual([d.code for d in diags], ["KIR-T002"])

    def test_the_orthogonality_check_still_stands(self) -> None:
        # And the third guard is intact: it was passing TRIVIALLY because
        # of the zeros, not broken. On nonzero directions it still goes red.
        diags: list = []
        self.assertIsNone(
            validate_plane(_plane(normal=[0, 0, 1], x_dir=[0, 0, 1]),
                           "OP1", "plane", diags))
        self.assertEqual([d.code for d in diags], ["KIR-T004"])  # TYPE_GEOM_RELATION


if __name__ == "__main__":
    unittest.main()
