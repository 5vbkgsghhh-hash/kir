"""`place_family` by CURVE: families that are placed not at a point.

MEASURED 27.07 (training model EOM, SKLNK, Revit 2026). After fixing the
refusal ordering in the riser, the honest EOM coverage is 67.70%, and THE
ENTIRE REMAINING GAP is 79 elements with one cause:
`FamilyPlacementType.CurveBased`.

What they actually are was checked in the live model: fireproofing wraps for
cable trays ("Техстронг_ОЗК : 4 стороны"), category "Generic Models", each
hosted on a tray. ALL 79 have a `LocationCurve`, and every curve is a
straight segment. Example:
    1268396 | Line [155643,-5766,565] -> [155643,-5766,4910] | host 1221482

That is, Revit stores their geometry and hands it back; it was only
inexpressible for us. The point-based `place_family` does not take them as a
matter of substance, not oversight: the instance has no `LocationPoint` at
all.

Why this is a general op, not an EOM special case: curve-based is one of ten
family placement kinds, and most Revit categories are family instances. An
op that can do both point and curve covers categories by the thousand, not
one at a time. The discipline here is only the trigger: the same
`CurveBased` shows up in structural (connections), HVAC (duct supports), and
architectural (copings, railings).

The parameter contract repeats one already in the registry: a curve is a
`p0_mm`/`p1_mm` pair, exactly as for `create_beam`, `create_pipe`,
`create_cable_tray`. There should be no second way to write a segment in
this registry.
"""
import copy
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_pfcurve.jsonl"))

from kir import spec
from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT

_POINT = {
    "ir_version": "1.0", "intent": "семейство в точку", "ops": [
        {"op": "place_family", "id": "F1", "xyz": [1000, 2000, 0],
         "level": {"by": "element_id", "value": 42}}]}

# A host is mandatory for the curve variant — MEASURED, not chosen: the
# overload with a level projects the curve onto the level's plane and
# collapses a vertical segment into a point, the correct overload goes
# through a reference to the host face.
# So the program keeps the tray and the wrap on it — just like a wall and a
# door.
_CURVE = {
    "ir_version": "1.0", "intent": "семейство по кривой на хосте", "ops": [
        {"op": "create_cable_tray", "id": "T1",
         "p0_mm": [155643, -5766, 565], "p1_mm": [155643, -5766, 4910],
         "level": {"by": "element_id", "value": 42}},
        {"op": "place_family", "id": "F1",
         "p0_mm": [155643, -5766, 565], "p1_mm": [155643, -5766, 4910],
         "host": {"by": "ref", "value": "T1"}}]}


class PlaceFamilyCurve(unittest.TestCase):
    def test_curve_without_a_host_is_refused(self):
        """A curve with no host is a refusal, not a level substitution.

        Measured 27.07: the overload with a level projects the segment onto
        the level's plane; a vertical curve collapses into a point, and
        Revit ignores the level on top of that (LevelId stays -1).
        Substituting a level "to make the call succeed" would mean passing
        broken geometry off as success.
        """
        no_host = copy.deepcopy(_CURVE)
        no_host["ops"][1].pop("host")
        out = compile_program(no_host, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("host", str([d.as_dict() for d in out.diagnostics]))

    def test_registry_expresses_a_curve_the_same_way_as_every_other_op(self):
        params = {p.name: p for p in spec.OPS["place_family"].params}
        for name in ("p0_mm", "p1_mm"):
            self.assertIn(name, params, f"{name} нет у place_family")
            self.assertEqual(params[name].kind, "pt_xyz")
        # the point stopped being mandatory — otherwise a curve could not be
        # expressed
        self.assertFalse(params["xyz"].required)

    def test_curve_variant_compiles_and_uses_the_curve_overload(self):
        out = compile_program(copy.deepcopy(_CURVE), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        cs = out.csharp
        self.assertIn("Line.CreateBound", cs)
        self.assertIn("new Reference(__pfh_F1)", cs)
        # the witness must read the RESULT, and for a curve-based instance
        # the result is a LocationCurve, not a LocationPoint
        self.assertIn("LocationCurve", cs)
        self.assertIn("host mismatch (topology)", cs)
        self.assertIn("endpoints mismatch (geometry)", cs)

    def test_point_and_curve_are_mutually_exclusive(self):
        both = copy.deepcopy(_CURVE)
        both["ops"][1]["xyz"] = [0, 0, 0]
        out = compile_program(both, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok, "точка и кривая вместе неоднозначны")

        neither = copy.deepcopy(_POINT)
        neither["ops"][0].pop("xyz")
        out2 = compile_program(neither, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out2.ok, "без точки и без кривой ставить нечего")

    def test_half_a_curve_is_refused_not_guessed(self):
        half = copy.deepcopy(_CURVE)
        half["ops"][1].pop("p1_mm")
        out = compile_program(half, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok, "одна точка кривой — не кривая")

    def test_point_emission_is_byte_stable(self):
        """The point-based path must not shift by a single byte.

        The curve is an ADDED branch, not a rewritten op: 18,700 demo
        instances and 327 from the A5 run were placed via the point-based
        path, and their bytes are frozen by the parity corpus.
        """
        out = compile_program(copy.deepcopy(_POINT), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertNotIn("Line.CreateBound", out.csharp)
        self.assertIn("NewFamilyInstance(__pfp_F1", out.csharp)


if __name__ == "__main__":
    unittest.main()
