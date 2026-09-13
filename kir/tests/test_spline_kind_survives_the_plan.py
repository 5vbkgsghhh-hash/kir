"""AN EDGE'S KIND MUST SURVIVE THE PLAN'S SIGNATURE, WHILE A SPLINE'S
BOUNDING BOX MUST NOT BE PINNED DOWN.

TWO FINDINGS FROM ONE LIVE RUN ON 20.08.2026, AND BOTH ARE INVISIBLE
OFFLINE. The gate stood at 2360/2360 green on both.

──────────────────────────────────────────────────────────────────────────────
1. A KIND LIVING IN THE TYPE OF A PYTHON OBJECT DOES NOT CROSS THE SERIALIZATION BOUNDARY
──────────────────────────────────────────────────────────────────────────────
`Spline` is a tuple subclass, and `is_spline` asked `isinstance(b, Spline)`.
Between grounding and payload emission runs `midend._canonical_json`: the
plan gets SIGNED, and the signature requires canonical form. JSON knows
nothing of tuple subclasses — what arrives at the emitter is an ordinary
list of the same structure. `isinstance` answers "no", the arc branch takes
`abs(list)`, and the compiler PANICS with KIR-P000.

A consequence more important than the fix itself: **the one and only op that
is allowed a spline (`create_floor_by_contour`) is brought down by exactly
this code.** That is, the kind had been declared at a place from which it is
never emitted, and NOBODY could build it, EVER — with the gate green and the
target tests green.

This is invisible offline because every previous check called validation and
emission DIRECTLY, bypassing the signature. The serialization boundary lies
between them, and a test that does not cross it could not tell working from
broken.

──────────────────────────────────────────────────────────────────────────────
2. A SPLINE'S BOUNDING BOX IS UNPROVABLE, AND THE KNOWLEDGE OF THIS LIVED IN A COMMENT
──────────────────────────────────────────────────────────────────────────────
In `_emit_floor_contour`, from the very beginning there stood "the bounding
box on a spline is understated by construction" — and `bbox_extents_witness`
was attached UNCONDITIONALLY. A live measurement (Revit 2026, a 12×8 m slab
with a wave): Revit gave 9705.3 mm along Y, our sampling expected 9426.0 — a
gap of 279 mm against a tolerance of 50.

This is not an error margin but DIFFERENT CURVES: we approximate the edge
with Catmull-Rom during compilation, Revit builds a `HermiteSpline` with its
own tangents, and the algorithm is not documented. The extrema will not
coincide at any tolerance, and a tolerance stretched to 300 mm would also
have signed off on a genuine error.

The right move is not to stretch the tolerance but to LIFT THE OBLIGATION
and name the absence. The points the curve is declared to pass through are
proven by `spline_points_witness` against `Sketch.Profile`.
"""
from __future__ import annotations

import json
import unittest

from kir import contour as C


def _spline_region() -> dict:
    return {"outer": {"shape": "poly",
                      "points_mm": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]],
                      "splines": [{"edge": 2,
                                   "via_mm": [[9600, 9400], [6600, 6600]]}]}}


def _validated():
    diags: list = []
    out = C.validate_region(_spline_region(), None, "F1", "contour", diags)
    assert out is not None and not diags, diags
    return out


class TheKindSurvivesTheSignature(unittest.TestCase):

    def test_the_kind_is_read_after_a_json_round_trip(self) -> None:
        """THE MAIN CONTROL. Revert the fix, and this test is the first to
        go red.

        The round trip through JSON is not the test's invention but exactly
        what the plan's signature does to EVERY program. What is checked is
        precisely the boundary at which the kind was being lost.
        """
        edges = json.loads(json.dumps(_validated()["outer"]))
        kinds = [C.is_spline(b) for _p0, _p1, b in edges]
        self.assertEqual(kinds, [False, False, True, False],
                         "после подписи плана род ребра прочитан неверно")

    def test_the_via_points_are_readable_from_both_forms(self) -> None:
        """One instrument for both forms: the object and its JSON shadow."""
        live = _validated()["outer"][2][2]
        shadow = json.loads(json.dumps(_validated()["outer"]))[2][2]
        self.assertEqual(C.spline_via(live), C.spline_via(shadow))
        self.assertEqual(C.spline_via(shadow),
                         ((9600.0, 9400.0), (6600.0, 6600.0)))

    def test_a_number_is_NEVER_a_spline(self) -> None:
        """A NARROWNESS CONTROL, without which the first check is worth
        nothing.

        A predicate that answers "yes" to everything passes the check
        trivially. A line and an arc must remain numbers on both sides of
        the boundary.
        """
        for b in (0.0, 0.3, -0.75, 1):
            self.assertFalse(C.is_spline(b), f"{b!r} принят за сплайн")

    def test_the_lowered_csharp_builds_a_spline_after_the_round_trip(self) -> None:
        """End of the chain: after the signature, the emitter must produce
        a HermiteSpline.

        Without the fix, what stood here was not "a different curve" but
        `TypeError: bad operand type for abs(): 'list'` — that is, a
        KIR-P000 for the program's author.
        """
        edges = json.loads(json.dumps(_validated()["outer"]))
        cs = C.emit_loop_cs(edges, "__ol")
        self.assertIn("HermiteSpline.Create", cs)
        self.assertEqual(cs.count("Line.CreateBound"), 3)


class TheSplineBboxIsNotClaimed(unittest.TestCase):

    def _obligations(self, region: dict) -> set:
        from kir.compiler import compile_program
        prog = {"ir_version": "1.0", "ops": [{
            "op": "create_floor_by_contour", "id": "F1",
            "contour": region, "level": {"by": "element_id", "value": 355}}]}
        out = compile_program(prog, revit_version="2026", snapshot={
            "levels": [{"id": 355, "name": "Уровень 1", "elevation_mm": 0.0}]})
        self.assertTrue(out.ok, [str(d.message_ru)[:200] for d in out.diagnostics])
        return set(out.csharp.splitlines())

    def test_a_plain_ring_still_claims_its_bbox(self) -> None:
        """A NARROWNESS CONTROL: the fix must not be allowed to weaken
        ordinary contours.

        It also catches the opposite mistake — lifting the bounding box off
        ALL slabs.
        """
        plain = {"outer": {"shape": "poly",
                           "points_mm": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]]}}
        cs = "\n".join(self._obligations(plain))
        self.assertIn("bbox extents mismatch", cs,
                      "у контура без сплайна габарит обязан остаться доказанным")

    def test_a_spline_ring_does_NOT_claim_its_bbox(self) -> None:
        """The bounding box has been lifted, while the curve's points are
        proven."""
        cs = "\n".join(self._obligations(_spline_region()))
        self.assertNotIn("bbox extents mismatch", cs,
                         "габарит сплайна пришпилен — он недоказуем по построению")
        self.assertIn("spline", cs.lower(),
                      "снят габарит и не добавлен свидетель точек — это молчание")

    def test_the_bbox_violation_prints_what_it_MEASURED(self) -> None:
        """A "mismatch" message must carry the measured number.

        On 20.08, three messages in a row named the expected value and
        omitted the measured one, and each one cost a separate live run:
        when postconditions are violated the transaction rolls back, and
        there will be no receipt with numbers at all.
        """
        plain = {"outer": {"shape": "poly",
                           "points_mm": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]]}}
        cs = "\n".join(self._obligations(plain))
        self.assertIn("MM(__bb.Min.X).ToString", cs,
                      "габаритное нарушение не печатает измеренный габарит")


if __name__ == "__main__":
    unittest.main()
