"""A VIEW-SPACE POINT TRAVELS TO REVIT IN ONE SET OF UNITS — IN EVERY BRANCH.

WHY, BY A NUMBER FROM THIS SAME TREE (measured 2026-09-04). A program with
``create_tag`` and ``"at": [3000, 800]`` printed TWO different units in ONE
op, in adjacent lines of one reference
(``kir/tests/golden/auth_annotation.golden.cs``):

    360:  var __uv_TAG1 = new UV(3000.0, 800.0);                  <- MILLIMETERS
    380:  ... RightDirection.Multiply(U(3000.0)) ...              <- internal

Revit reads ``UV`` in INTERNAL units (feet), so the spatial tag was landing
off by a factor of about 304.8. The ordinary-tag branch (``IndependentTag``)
went through ``docspace.emit_view2d_to_xyz_cs`` and converted; the spatial
branch (``NewRoomTag``/``NewSpaceTag``/``NewAreaTag``) printed literals. One
law, two carriers, two verdicts.

🔴 THIS IS ABOUT UNITS, NOT ABOUT AXES, AND TELLING THEM APART IS MANDATORY.
``test_spatial_tag_is_its_own_class`` says out loud: "which axes ``UV`` uses
for ``NewRoomTag`` is not settled by compilation, not checked live." Here
the axis is NOT GUESSED AT and is not checked: the mm -> internal conversion
is unambiguous and does not depend on the choice of axis, while the axis is
still guarded by the ``head_at`` witness, which reads ``TagHeadPosition``
back through the same view basis. If the axis were decided here, this file
would be a guess; it is about the NUMBER having to arrive in the same units
in which it is read.

WHY THIS LIVED GREEN. Three references (``auth_annotation``,
``annotation_full_set``, ``annotation_explicit_types``) froze raw
millimeters at the 2026-08-13 freeze and held them byte for byte. A
reference is a CHANGE DETECTOR, not proof of correctness, and this is
recorded in ``test_golden.UNREVIEWED_GOLDENS`` itself: "if an op emits
wrongly today, freezing makes the wrong output canonical and the future FIX
then looks like the regression." That is exactly what happened. Meanwhile
``test_annotation.Golden``'s docstring promised "a view point through the
VIEW BASIS... A raw XY here will go red" — and that was true of
``TextNote`` but not of the neighboring branch of the same family: the
promise was checked in the wrong place for the hole.

``test_spatial_tag_is_its_own_class`` contained NOT ONE check of the unit
conversion (neither ``304.8`` nor the ``UV`` arguments) — hence they are
introduced here.
"""

from __future__ import annotations

import re
import unittest

from kir import docspace
from kir.compiler import compile_program

#: The same point in every program in the file — so that "3000" in one place
#: and "3000" in another are ONE number, not two literals that happen to match.
AT_MM = [3000, 800]

IN_VIEW = {"by": "element_id", "value": 900}


def _emit(revit_version: str = "2026", **tag_extra: object) -> str:
    tag: dict[str, object] = {
        "op": "create_tag", "id": "TAG1",
        "in_view": IN_VIEW,
        "target": {"by": "ref", "value": "W1"},
        "at": list(AT_MM),
    }
    tag.update(tag_extra)
    program = {"ir_version": "1.0", "ops": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "height_mm": 3000, "level": {"by": "element_id", "value": 100}},
        tag,
    ]}
    out = compile_program(program, revit_version=revit_version,
                          snapshot=None, bulk=True)
    assert out.ok, [d.as_dict() for d in (out.diagnostics or [])][:3]
    return out.csharp


def _uv_args(cs: str) -> list[str]:
    """The arguments of EVERY ``new UV(...)`` in the emitted C#."""
    return [m.group(1) for m in re.finditer(r"new UV\(([^;]*?)\)\s*;", cs)]


class TheSpatialTagConvertsMillimetresLikeItsSibling(unittest.TestCase):
    """FC-01: the spatial-tag branch printed raw millimeters."""

    def setUp(self) -> None:
        self.cs = _emit()

    def test_the_uv_of_the_spatial_tag_goes_through_the_unit_helper(self) -> None:
        # A POSITIVE EXAMPLE. `U(mm)` is the only conversion in the emitted
        # C# (`emit_core`: `UnitUtils.ConvertToInternalUnits(mm, Millimeters)`).
        args = _uv_args(self.cs)
        self.assertTrue(args, "в программе с create_tag нет ни одного new UV(")
        for a in args:
            with self.subTest(uv=a):
                self.assertIn("U(", a)

    def test_no_uv_carries_a_bare_millimetre_literal(self) -> None:
        # 🔴 THE CONTROL-FAIL LIVES HERE: this exact line goes red on the OLD
        # code — there it read `new UV(3000.0, 800.0)`.
        for a in _uv_args(self.cs):
            with self.subTest(uv=a):
                for value in AT_MM:
                    self.assertNotRegex(
                        a, rf"(?<![\w.]){value}(\.0)?\s*(,|$)",
                        f"UV получил СЫРОЙ миллиметр {value}: Revit читает UV "
                        f"во внутренних единицах, марка уедет в ~304.8 раза")

    def test_both_branches_of_one_op_state_the_same_number(self) -> None:
        # TWO BRANCHES OF ONE OP — ONE NUMBER. The ordinary tag places the
        # point through the view basis (`Multiply(U(3000.0))`), the spatial
        # one through `UV`. As long as both print `U(3000.0)`, a unit
        # mismatch cannot go UNNOTICED: it would become two different
        # strings in one file.
        u_terms = set(re.findall(r"U\((-?\d+(?:\.\d+)?)\)", self.cs))
        for value in AT_MM:
            with self.subTest(value=value):
                self.assertIn(f"{float(value)}", u_terms)

    def test_the_independent_branch_is_untouched(self) -> None:
        # The edit did NOT touch the neighboring branch: it was already correct.
        self.assertIn("RightDirection.Multiply(U(3000.0))", self.cs)

    def test_the_conversion_holds_on_every_version(self) -> None:
        # Units are not a property of the version. `tag_type` is deliberately
        # left unset here: on 2021 it would be a typed refusal, and what we
        # care about is the UV.
        for ver in ("2021", "2022", "2023", "2024", "2025", "2026"):
            with self.subTest(ver=ver):
                for a in _uv_args(_emit(ver)):
                    self.assertIn("U(", a)


class TheUnitLawHasOneCarrier(unittest.TestCase):
    """The conversion for the view point is recorded in ONE place, not as a
    literal on the spot.

    The defect was born precisely from a second carrier:
    `emit_view2d_to_xyz_cs` knew the conversion, while the `UV` branch typed
    the numbers by hand. As long as there is one function, a third branch
    cannot diverge without rewriting it.
    """

    def test_docspace_owns_the_uv_form(self) -> None:
        self.assertEqual(docspace.emit_view2d_to_uv_cs(3000, 800),
                         "new UV(U(3000), U(800))")

    def test_the_emitted_uv_is_byte_for_byte_what_docspace_says(self) -> None:
        # 🔴 WE CHECK BEHAVIOR, NOT SOURCE TEXT, AND THIS WAS PAID FOR RIGHT
        # HERE. The first edition of this test read
        # `inspect.getsource(_emit_tag)` and demanded the absence of the
        # substring `new UV({round(` — and it went red on THE FIX'S OWN
        # COMMENT, which honestly quotes the previous form. The instrument
        # caught not the defect but the account of the defect being removed:
        # the more conscientious the note, the more confidently such a
        # matcher would err. The equality below checks exactly the same
        # thing ("there is no second carrier"), but by the EMISSION'S BYTES,
        # which no comment moves.
        want = docspace.emit_view2d_to_uv_cs(float(AT_MM[0]), float(AT_MM[1]))
        self.assertIn(f"var __uv_TAG1 = {want};", _emit())

    def test_the_room_creator_already_obeyed_the_same_law(self) -> None:
        # A THIRD CARRIER OF THE SAME LAW, and it had been right ALL ALONG:
        # `doc.Create.NewRoom(level, UV)` — the same `doc.Create` and the same
        # `UV` — was printed as `new UV(U(4000), U(3000))`. That is, the
        # argument "UV is in internal units" was not derived from
        # documentation but LIFTED FROM A NEIGHBOR that had already made it
        # into the reference.
        import pathlib
        golden = (pathlib.Path(__file__).parent / "golden"
                  / "full_house_v1.golden.cs").read_text(encoding="utf-8")
        self.assertIn("doc.Create.NewRoom(__lv_R1, new UV(U(4000), U(3000)))",
                      golden)


if __name__ == "__main__":
    unittest.main()
