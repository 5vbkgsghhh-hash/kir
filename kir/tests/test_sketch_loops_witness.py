"""THE WITNESS READS THE SHAPE, NOT ITS BOUNDING BOX.

WHY THIS FILE EXISTS, IN ARITHMETIC. `bbox_extents_witness` pins down FOUR numbers
(xmin, xmax, ymin, ymax). An L-shaped contour of six vertices has
TWELVE coordinates, meaning eight are free — and all this time `create_floor` was signing
the `(geometry)` axis on evidence like that. A slab with a shifted inner
corner, a lost notch, or a filled-in hole passed green.

This is our cardinal invariant, violated in the witness itself: the canon requires
that a witness sign the AXIS IT ACTUALLY READS, and a bounding box is a projection of the shape, so
a consumer of `geometry_ok=True` could not tell "the shape was checked" from "its bounding
box was checked". `unwitnessed_axes` stayed silent through all of this BY CONSTRUCTION: an obligation
of kind `geometry` formally existed.

🔴 THE DECISIVE EXPERIMENT OF THIS FILE — `test_moved_inner_vertex_...`: it shifts ONE
interior vertex so that the bounding box does not change by so much as a unit, and demands that
the old witness stay blind while the new one sees it. Before this wave, such an experiment was
impossible: there was nothing to distinguish with.
"""
from __future__ import annotations

import math
import re
import unittest

from kir.compiler import compile_program
from kir.authoring import (canon_unit, loops_payload_expected,
                                 _expected_roof_rise_mm)
from kir.emit_model import tolerance
from kir.tests.fixtures import GROUND_SNAPSHOT

#: An L-contour: six vertices, an interior corner at [3000, 4000].
L_OUTLINE = [[0, 0], [6000, 0], [6000, 4000], [3000, 4000], [3000, 8000], [0, 8000]]
#: The same contour with ONE interior vertex shifted. The bounding box does not change:
#: 0 and 6000 on X are held by other vertices, and so are 0 and 8000 on Y.
L_MOVED = [[0, 0], [6000, 0], [6000, 4000], [4000, 5000], [3000, 8000], [0, 8000]]

_BBOX_RX = (r"Math\.Abs\(MM\(__bb\.Min\.X\) - ([\-0-9\.]+)",
            r"Math\.Abs\(MM\(__bb\.Max\.X\) - ([\-0-9\.]+)",
            r"Math\.Abs\(MM\(__bb\.Min\.Y\) - ([\-0-9\.]+)",
            r"Math\.Abs\(MM\(__bb\.Max\.Y\) - ([\-0-9\.]+)")
_SKETCH_RX = r'__slf_F1 != "([^"]*)"'


def _csharp(outline, holes=None, ver="2023"):
    op = {"op": "create_floor", "id": "F1",
          "level": {"by": "name", "value": "Этаж 1"}, "outline": outline}
    if holes:
        op["holes"] = holes
    out = compile_program({"ir_version": "1.0", "ops": [op]},
                          revit_version=ver, snapshot=GROUND_SNAPSHOT)
    assert out.ok, [d.message_ru for d in (out.diagnostics or [])][:1]
    return out.csharp


def _bbox(cs):
    return tuple(re.search(rx, cs).group(1) for rx in _BBOX_RX)


def _sketch(cs):
    found = re.search(_SKETCH_RX, cs)
    return found.group(1) if found else None


class SketchLoopsWitness(unittest.TestCase):

    def test_moved_inner_vertex_is_INVISIBLE_to_bbox_and_VISIBLE_to_the_shape(self):
        """The decisive experiment: one vertex, the bounding box unmoved.

        Both assertions must stand TOGETHER. The first is proof that
        the old witness is blind BY CONSTRUCTION, not by bad luck; the second is that
        the new one sees exactly this substitution. On its own, neither
        means anything: blindness without sight is a complaint, sight without blindness is decoration.
        """
        a, b = _csharp(L_OUTLINE), _csharp(L_MOVED)
        self.assertEqual(_bbox(a), _bbox(b),
                         "габарит обязан быть НЕПОДВИЖЕН — иначе опыт не про то")
        self.assertNotEqual(_sketch(a), _sketch(b),
                            "форма обязана различать сдвинутую вершину")
        self.assertIn("3000,4000", _sketch(a))
        self.assertIn("4000,5000", _sketch(b))

    def test_a_lost_hole_changes_the_loop_count(self):
        """A filled-in hole is caught by the NUMBER OF LOOPS, not by vertices.

        The bounding box does not see it at all: the hole lies INSIDE the contour and
        does not affect the extremes with a single coordinate.
        """
        hole = [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]]
        plain, holed = _csharp(L_OUTLINE), _csharp(L_OUTLINE, holes=hole)
        self.assertEqual(_bbox(plain), _bbox(holed),
                         "габарит к отверстию слеп — на этом и стоит находка")
        self.assertNotEqual(_sketch(plain), _sketch(holed))
        self.assertEqual(_sketch(plain).count(";"), 0, "одно кольцо")
        self.assertEqual(_sketch(holed).count(";"), 1, "два кольца")

    def test_the_comparison_survives_ring_rotation_and_reversal(self):
        """Rotating a loop and changing its winding belong to REVIT, not to the author.

        The canon writes this about `__ReadLoops`: positional lists "land on the
        wrong edge". So the comparison must be stable, and a multiset
        is exactly that BY CONSTRUCTION — this test does not check the implementation, it FORBIDS
        replacing the multiset with a positional list in the future.
        """
        rotated = L_OUTLINE[2:] + L_OUTLINE[:2]
        reversed_ring = list(reversed(L_OUTLINE))
        base = _sketch(_csharp(L_OUTLINE))
        self.assertEqual(base, _sketch(_csharp(rotated)))
        self.assertEqual(base, _sketch(_csharp(reversed_ring)))

    def test_python_and_csharp_round_by_the_SAME_law(self):
        """Two halves of one quantity — and there is no third copy.

        The law: rounding half AWAY FROM zero (floor(s+0.5) / ceil(s-0.5)). Banker's
        rounding would send EXACTLY HALF of the boundary vertices into the neighboring cell,
        and the witness would go red on CORRECT geometry. The table is deliberately made of
        exact halves and negatives — precisely where `round()` diverges.
        """
        def csharp_law(mm, grid):                      # verbatim __KirCanonUnit
            s = mm / grid
            return math.floor(s + 0.5) if s >= 0.0 else math.ceil(s - 0.5)

        for mm in (0.0, 0.5, 1.5, 2.5, -0.5, -1.5, -2.5, 3000.4, 3000.5,
                   -3000.5, 12345.6789):
            for grid in (1.0, 0.5, 5.0):
                with self.subTest(mm=mm, grid=grid):
                    self.assertEqual(canon_unit(mm, grid), csharp_law(mm, grid))
        # And a control on the control itself: a naive round() MUST diverge, otherwise
        # the table is built so that it distinguishes nothing.
        self.assertNotEqual(canon_unit(2.5, 1.0), round(2.5))

    def test_python_and_csharp_ORDER_by_the_same_law(self):
        """THE SECOND HALF OF THE SAME LAW — ORDER, not just rounding.

        🔴 A LIVE MEASUREMENT ON 24.08.2026. Python sorted the FINISHED STRINGS, while C#
        sorts the pairs with `__slv.Sort(__KirCanonCmp)` — NUMERICALLY. They agreed
        exactly until the first vertex of a different MAGNITUDE: "12000" is lexicographically
        LESS than "8000", numerically it is GREATER. The very first floor to reach
        Revit (0..6000 × 8000..12000) rolled back the whole program with
        "sketch loops mismatch" on GEOMETRY that matched down to the micron.

        The earlier test pinned down the equality of ROUNDINGS and never
        asked about order — that is, half the law stood without a guard. Here stands
        the second half: the table deliberately mixes magnitudes and signs.
        """
        def csharp_cmp(a, b):                      # verbatim __KirCanonCmp
            for x, y in zip(a, b):
                if x < y:
                    return -1
                if x > y:
                    return 1
            return (len(a) > len(b)) - (len(a) < len(b))

        rings = [
            [(0, 8000), (6000, 8000), (6000, 12000), (0, 12000)],   # magnitude
            [(0, 9000), (0, 10000), (500, 0)],                      # 9 versus 10
            [(-500, 0), (0, -1500), (0, 0)],                        # signs
            [(120000, 7), (9, 7), (9, 70000)],                      # six versus one
        ]
        for ring in rings:
            with self.subTest(ring=ring):
                got = loops_payload_expected([ring], 1.0)
                pairs = [tuple(int(n) for n in v.split(","))
                         for v in got.split("|")]
                for left, right in zip(pairs, pairs[1:]):
                    self.assertLessEqual(
                        csharp_cmp(left, right), 0,
                        f"порядок питона расходится с __KirCanonCmp: {got}")
        # A CONTROL ON THE CONTROL: lexicographic order must differ from
        # numeric order on at least one loop, otherwise the table distinguishes nothing.
        ring = rings[0]
        lex = "|".join(sorted("%d,%d" % (x, y) for x, y in ring))
        self.assertNotEqual(lex, loops_payload_expected([ring], 1.0))

    def test_the_helper_declaration_travels_with_the_witness(self):
        """CS0103 on the user's machine — an outcome forbidden here.

        The canonicalizer's declaration is inserted into the preamble CONDITIONALLY, and before
        19.08 the condition checked for only one of three names (`__KirCanonPayload`). The shape witness
        calls `__KirCanonUnit`, so without extending the condition a program with a slab
        would have gone out WITHOUT the declaration — and broken not on our end.
        """
        cs = _csharp(L_OUTLINE)
        self.assertIn("__KirCanonUnit(", cs, "свидетель зовёт помощник")
        self.assertIn("Func<double, double, long> __KirCanonUnit", cs,
                      "…а объявление обязано ехать вместе с ним")
        self.assertLess(cs.index("Func<double, double, long> __KirCanonUnit"),
                        cs.index("__KirCanonUnit(MM("),
                        "объявление обязано стоять ДО первого вызова")

    def test_read_failure_and_shape_mismatch_are_DIFFERENT_outcomes(self):
        """One code for two outcomes is our named defect, and it is not present here.

        "The sketch could not be read" is fixed on OUR end (reading), "the shape diverged" is fixed on the
        PROGRAM's end (geometry). Merging them into one message would mean asking
        the reader to interpret a code that carries no distinction.
        """
        cs = _csharp(L_OUTLINE)
        self.assertIn("эскиз построенного элемента не прочитан", cs)
        self.assertIn("sketch loops mismatch", cs)

class WitnessTransfersToTheContourOps(unittest.TestCase):
    """PORTABILITY IS THE MAIN CHECK ON THE SECOND OP.

    A witness that works on a single op is a witness of THAT OP. The shape witness must
    carry over to every op whose shape is read via the same `Sketch.Profile`;
    if it did not carry over, that had to be found out on the second one, not the eighth.
    """

    def _shape(self, op):
        out = compile_program({"ir_version": "1.0", "ops": [op]},
                              revit_version="2023", snapshot=GROUND_SNAPSHOT)
        assert out.ok, [d.message_ru for d in (out.diagnostics or [])][:1]
        found = re.search(r'__slf_\w+ != "([^"]*)"', out.csharp)
        return found.group(1) if found else None

    def _ceiling(self, outline):
        return {"op": "create_ceiling", "id": "C1",
                "level": {"by": "name", "value": "Этаж 1"}, "outline": outline}

    def test_ceiling_sees_a_moved_inner_vertex(self):
        a, b = self._shape(self._ceiling(L_OUTLINE)), self._shape(self._ceiling(L_MOVED))
        self.assertIsNotNone(a, "у потолка обязан быть свидетель формы")
        self.assertNotEqual(a, b)

    def test_contour_floor_carries_the_hole_as_a_second_ring(self):
        """A hole in a contour slab is a SECOND loop, not a correction to the bounding box.

        It was exactly this reference case (`auth_contour_l`) that the expressiveness wave read
        line by line and recorded: "the live witness there is only the bounding box, with a tolerance of
        50 mm, unable by construction to see either the notch or the hole".
        """
        op = {"op": "create_floor_by_contour", "id": "F1",
              "level": {"by": "name", "value": "Этаж 1"},
              "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                    "size_mm": [10000, 6000]},
                          "holes": [{"shape": "rect", "origin": [2000, 2000],
                                     "size_mm": [2000, 2000]}]}}
        shape = self._shape(op)
        self.assertIsNotNone(shape)
        self.assertEqual(shape.count(";"), 1, "внешнее кольцо плюс отверстие")

    def test_an_arc_does_not_false_red_the_witness(self):
        """🔴 THE MEASUREMENT THAT REMOVED THE MAIN OBJECTION TO PORTABILITY.

        A comment in the ceiling emitter warns: "checking an arced ceiling BY
        VERTICES would mean blaming a correctly built element for exactly the
        sagitta of the arc". True — for comparison against a SAMPLED
        arc (`edges_to_sample_poly` breaks it into 8 chords). The shape witness compares
        the start of each EDGE, and Revit stores an arc as A SINGLE curve: a measurement
        on 19.08.2026 across 67 corpus decompiles — 10,463 loops, 259 with arcs,
        331 curves of kind `arc` as separate records interleaved with `line`, not
        a single tessellation run.

        This is pinned down here by the NUMBER OF VERTICES: an arced loop has exactly as many
        as it has edges, not eight per arc. Should this diverge, the witness would start
        going red on correct geometry, and the test must be the first to fail.
        """
        op = {"op": "create_floor_by_contour", "id": "F1",
              "level": {"by": "name", "value": "Этаж 1"},
              "contour": {"outer": {"shape": "poly",
                                    "points_mm": [[0, 0], [8000, 0],
                                                  [8000, 5000], [0, 5000]],
                                    "arcs": [{"edge": 1, "bulge": 0.4}]},
                          "holes": []}}
        shape = self._shape(op)
        self.assertIsNotNone(shape)
        self.assertEqual(len(shape.split("|")), 4,
                         "четыре ребра — четыре вершины, дуга НЕ развёрнута "
                         "в восемь хорд: %s" % shape)


class DecisiveControlPerOp(unittest.TestCase):
    """A DECISIVE EXPERIMENT FOR EVERY OP, NOT ONE PER CLASS.

    The requirement is not relaxed for the sake of throughput: an obligation without an experiment that can
    fail is decoration. The shape of the experiment is the same one every time, and that is not laziness but
    proof of PORTABILITY: same bounding box, different shape, the witness
    tells them apart.
    """

    def _shape(self, op, ver="2026"):
        out = compile_program({"ir_version": "1.0", "ops": [op]},
                              revit_version=ver, snapshot=GROUND_SNAPSHOT)
        assert out.ok, [d.message_ru for d in (out.diagnostics or [])][:1]
        found = re.search(r'__slf_\w+ != "([^"]*)"', out.csharp)
        bbox = tuple(re.search(rx, out.csharp).group(1) for rx in _BBOX_RX)
        return (found.group(1) if found else None), bbox

    def test_roof_sees_a_moved_inner_vertex(self):
        def roof(outline):
            return {"op": "create_roof", "id": "R1",
                    "level": {"by": "name", "value": "Этаж 1"},
                    "outline": outline}
        a, abb = self._shape(roof(L_OUTLINE))
        b, bbb = self._shape(roof(L_MOVED))
        self.assertEqual(abb, bbb, "габарит обязан быть неподвижен")
        self.assertNotEqual(a, b, "форма подошвы кровли обязана различать")

    def test_foundation_slab_sees_a_moved_inner_vertex(self):
        def slab(outline):
            return {"op": "create_foundation", "id": "F1", "variety": "slab",
                    "level": {"by": "name", "value": "Этаж 1"},
                    "outline": outline}
        a, abb = self._shape(slab(L_OUTLINE))
        b, bbb = self._shape(slab(L_MOVED))
        self.assertEqual(abb, bbb)
        self.assertNotEqual(a, b)

    def test_the_isolated_foundation_has_NO_sketch_witness(self):
        """The conditionality of the branch is not decoration: an isolated footing has NO
        sketch, and demanding one would mean declaring unprovable something this
        branch never has. This has already cost us KIR-R001 on a sloped column.
        """
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "create_foundation", "id": "F1", "variety": "isolated",
                 "level": {"by": "name", "value": "Этаж 1"},
                 "xy": [1000, 1000]}]},
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.message_ru for d in (out.diagnostics or [])][:1])
        self.assertNotIn("__slf_F1", out.csharp,
                         "у изолированной ветки свидетеля формы быть не должно")


class PathIsNotARing(unittest.TestCase):
    """A PATH HAS NO CLOSURE, AND A LOOP WITNESS WOULD HERE BLAME SOMETHING CORRECT.

    For a loop, ONE vertex per edge is taken: the traversal returns to the start.
    For an open polyline this would lose the END of the path — a shift of the last vertex
    would pass silently. That is why both ends of every curve are taken here, and interior
    vertices are counted twice.
    """

    #: 🔴 RAILING NO LONGER HAS A BOUNDING-BOX WITNESS, AND THAT IS CORRECT.
    #:
    #: Before 26.08 `_railing` pulled four numbers out of the generated C#,
    #: `bbox_extents_witness`, and failed with `AttributeError: NoneType.group` —
    #: three tests in this class had been red for two days over ONE reason, and not
    #: one of them was about the bounding box.
    #:
    #: The witness was removed DELIBERATELY on 25.08.2026 by a live measurement (Проект1, Revit
    #: 2026, q14), and the argument is recorded verbatim in `arch_emit.py`: the path is a LINE
    #: of zero thickness, while the built Railing is a SOLID with posts and a
    #: handrail, whose bounding box is wider than the path BY REVIT'S OWN DESIGN. Measured: path
    #: y=[921000, 921000], solid y=[920975, 921050]; the witness was blaming
    #: CORRECT geometry, with a live-run success rate of 13.0% (3 built / 20
    #: blamed / 140 collateral rollbacks).
    #:
    #: So nothing here is "fixed back": the test stops demanding
    #: the removed thing, and the "bounding box unmoved" control is now computed FROM THE PATH — from
    #: the input, not from the output of the thing under test. This is the same law already
    #: recorded in `test_python_and_csharp_ORDER_the_PATH_by_the_same_law`
    #: as the line "A DEGENERACY CONTROL ASKS THE INPUT, NOT THE OUTPUT".
    @staticmethod
    def _bbox_of(path):
        xs = [p[0] for p in path]
        ys = [p[1] for p in path]
        return (min(xs), max(xs), min(ys), max(ys))

    def _railing(self, path):
        op = {"op": "create_railing", "id": "R1", "variety": "path",
              "path": path, "level": {"by": "name", "value": "Этаж 1"}}
        out = compile_program({"ir_version": "1.0", "ops": [op]},
                              revit_version="2026", snapshot=GROUND_SNAPSHOT)
        assert out.ok, [d.message_ru for d in (out.diagnostics or [])][:1]
        found = re.search(r'__slf_\w+ != "([^"]*)"', out.csharp)
        return (found.group(1) if found else None), out.csharp

    def test_the_railing_does_NOT_carry_a_bbox_witness(self):
        """WHAT WAS REMOVED MUST STAY REMOVED, and the reason is named above.

        Without this guard, the bounding-box witness would come back "for company" with
        a neighboring op, and the live success rate would drop back to 13%: a solid versus
        a line are quantities of different kinds, and a tolerance does not fix that.
        """
        _, cs = self._railing([[0, 0], [4000, 0], [4000, 2500]])
        for rx in _BBOX_RX:
            self.assertIsNone(
                re.search(rx, cs),
                "у ограждения снова габаритный свидетель — он обвиняет "
                "верную геометрию, см. довод 25.08 в arch_emit.py")

    def test_the_LAST_vertex_is_watched(self):
        """Exactly the case a loop witness would miss.

        The END of the path is shifted, and shifted so that the bounding box does not change:
        the last segment is rotated inward, within the enclosing rectangle.
        """
        pa = [[0, 0], [4000, 0], [4000, 2500]]
        pb = [[0, 0], [4000, 2500], [4000, 0]]
        self.assertEqual(self._bbox_of(pa), self._bbox_of(pb),
                         "габарит обязан быть неподвижен")
        a, _ = self._railing(pa)
        b, _ = self._railing(pb)
        self.assertNotEqual(a, b, "конец пути обязан быть под присмотром")

    def test_an_interior_vertex_appears_twice(self):
        """Not redundancy: an interior vertex belongs to TWO edges.

        🔴 ON 04.09.2026 THE ENDPOINTS MOVED FROM A SHARED BAG TO THEIR OWN EDGE, and
        the earlier draft of this experiment pinned down the shape of the bag
        (len(shape.split("|")) == 4) — that is, THE DEFECT ITSELF: a multiset of all
        endpoints is indifferent to a permutation of the interior vertices, and the path A-B-C-D was not
        distinguished from A-C-B-D (FC-19, closed in
        `test_a_witness_proves_the_thing_it_names`). The assertion stayed the
        same in meaning — three points, two edges, four endpoints, the middle vertex counted
        twice — but it is now computed PER EDGE.
        """
        shape, _ = self._railing([[0, 0], [4000, 0], [4000, 2500]])
        self.assertEqual(shape.count("4000,0"), 2, shape)
        rings = shape.split(";")
        self.assertEqual(len(rings), 2, shape)
        self.assertEqual([len(r.split("|")) for r in rings], [2, 2], shape)

    def test_python_and_csharp_ORDER_the_PATH_by_the_same_law(self):
        """THE SAME FIX THAT WAS APPLIED TO THE LOOP NEVER REACHED THE PATH — A SECOND CARRIER.

        🔴 ON 24.08.2026 the vertex order for a LOOP was aligned with `__KirCanonCmp`
        (`loops_payload_expected`, a patch in `authoring.py`), and a guard was placed alongside it,
        `test_python_and_csharp_ORDER_by_the_same_law`. Both surfaces of
        `loops_verdict_cs` — the profile and the sketch — started calling the helper. The THIRD one,
        `path_points_witness`, went on computing the expectation itself:
        `sorted()` over FINISHED STRINGS versus `__slv.Sort(__KirCanonCmp)`
        over `long` in that same generated C#.

        THE COST, REPRODUCED: the path `[[0,0],[8000,0],[12000,0]]` compiles with
        `ok=True` and zero diagnostics, the expectation goes into the C# as
        `0,0|12000,0|8000,0|8000,0`, while that same C# will actually build
        `0,0|8000,0|8000,0|12000,0` — "12000" is lexicographically LESS than "8000",
        numerically it is GREATER. `__post.Count > 0` then rolls back the ENTIRE program
        on CORRECT geometry, telling the author "sketch loops mismatch".

        Why the loop guard did not catch this, and why the earlier path tests caught it even less:
        all of their vertices have the SAME magnitude (`0`, `4000`, `2500`), so the two
        laws agree there. It is caught only by a pair of different magnitude.

        Corpus: `railing_path_index` carries 1058 paths, 2093 curves.
        """
        def csharp_cmp(a, b):                      # verbatim __KirCanonCmp
            for x, y in zip(a, b):
                if x < y:
                    return -1
                if x > y:
                    return 1
            return (len(a) > len(b)) - (len(a) < len(b))

        paths = [
            [[0, 0], [8000, 0], [12000, 0]],       # 4 digits versus 5
            [[0, 900], [0, 12000]],                # a straight two-point one
            [[0, 0], [90, 0], [100, 0]],           # 2 digits versus 3
        ]
        g = tolerance("create_railing", "path_mm")
        gv = float(getattr(g, "value", g))
        for path in paths:
            with self.subTest(path=path):
                # Both ends of every edge — the same way the witness
                # does it, and EACH IN ITS OWN EDGE (04.09.2026). The degeneracy
                # control below is still computed from the INPUT and
                # still holds: for an edge made of two points of different
                # magnitude, the lexicographic order and the numeric one diverge
                # exactly as they diverged in the bag.
                canon_edges = [
                    [(canon_unit(a[0], gv), canon_unit(a[1], gv)),
                     (canon_unit(b[0], gv), canon_unit(b[1], gv))]
                    for a, b in zip(path, path[1:])]
                pts = [pt for edge in canon_edges for pt in edge]

                # 🔴 A DEGENERACY CONTROL ASKS THE INPUT, NOT THE OUTPUT.
                # The first draft checked the lexicographic order against the very
                # `shape` that was itself under test — that is, it closed the
                # control through the subject under test: on broken code it cried
                # "input is degenerate", when what was degenerate was the LAW. Here both orders
                # are computed from the PATH, and the control is independent of the fix.
                # (The first table carried [[0,0],[700,0],[70000,0]] — there both
                # laws give the same order, and the subtest could not have ended any other way.)
                lex = "|".join(sorted("%d,%d" % p for p in pts))
                num = "|".join("%d,%d" % p for p in sorted(pts))
                self.assertNotEqual(
                    lex, num,
                    "вход вырожден: у этого пути лексикографический порядок "
                    "совпадает с численным, различать нечего")

                shape, _ = self._railing(path)
                # THE LAW IS DERIVED FROM ONE CARRIER, not written a second time.
                edges = [[(a[0], a[1]), (b[0], b[1])]
                         for a, b in zip(path, path[1:])]
                self.assertEqual(
                    shape, loops_payload_expected(edges, g),
                    "подпись пути обязана считаться ТЕМ ЖЕ помощником, "
                    "что и подпись кольца")
                # And independent of the helper — the order must be the one
                # the generated C# will actually execute: NUMERICALLY within an edge
                # (__slv.Sort(__KirCanonCmp)), by STRING between edges
                # (__slr.Sort(StringComparer.Ordinal)).
                rings = shape.split(";")
                self.assertEqual(rings, sorted(rings), shape)
                for ring in rings:
                    pairs = [tuple(int(n) for n in v.split(","))
                             for v in ring.split("|")]
                    for left, right in zip(pairs, pairs[1:]):
                        self.assertLessEqual(
                            csharp_cmp(left, right), 0,
                            "порядок питона расходится с __KirCanonCmp: "
                            + shape)


class NamedAbsenceIsNotAWeakWitness(unittest.TestCase):
    """A NAMED ABSENCE IS MORE HONEST THAN A WEAK WITNESS.

    A weak one signs the axis; a named absence says "nobody looked
    here", and `unwitnessed_axes` picks it up. The `GetBoundary()` pair
    is declared exactly this way, and the record must carry a REASON and what would CLOSE it.
    """

    def test_the_GetBoundary_pair_declares_its_absence_with_a_reason(self):
        from kir.translation_cert import _NON_WITNESSABLE_CLAUSES
        for op in ("create_building_pad", "create_site_subregion"):
            with self.subTest(op=op):
                self.assertIn(op, _NON_WITNESSABLE_CLAUSES)
                clause, why = _NON_WITNESSABLE_CLAUSES[op][0]
                self.assertIn("boundary vertex multiset", clause)
                # The reason must name WHAT was checked and WHAT instead — otherwise
                # this is a `claim`, not a measured boundary.
                self.assertIn("UNMEASURED", why.upper())
                self.assertTrue("corpus" in why or "live probe" in why, why)


class RegistryDeclaration(unittest.TestCase):

    def test_the_obligation_is_declared_in_the_registry_post(self):
        """A witness without an obligation in the registry is an unsecured promise.

        `translation_cert` holds a bijection between `OpSpec.post` and obligations, and without
        a line in `post` the certificate could not discharge it.
        """
        from kir import spec
        post = spec.OPS["create_floor"].post
        self.assertIn("sketch loop count", post)
        self.assertIn("vertex multiset", post)
        self.assertIn("sketch_mm", spec.OPS["create_floor"].tolerances)


if __name__ == "__main__":
    unittest.main()


class RoofRiseIsTheLowerEnvelope(unittest.TestCase):
    """THE RISE OF A GABLE ROOF IS PREDICTED BY THE ENVELOPE, NOT BY THE FARTHEST VERTEX.

    🔴 A LIVE REVIT MEASUREMENT ON 24.08.2026. The prediction computed the rise as
    "distance from the edge to the FARTHEST vertex × tan", but opposing slopes meet
    IN THE MIDDLE. On a 1335×1080 mm roof with three edges at 16.699°:

        Revit built            182.9 mm
        the witness demanded   307.8 mm      ← RED on a correct roof

    Three gable roofs out of six rolled back the entire K3 transfer (74 operations).
    A roof is the LOWER ENVELOPE of planes rotated about their edges —
    the maximum over the contour's points of the minimum over the slopes.

    This class replaces the golden-fixture refreeze pin from 24.08: 12 keys of
    `golden:roof_gable_slopes` shifted PRECISELY because of this.
    """

    def test_two_facing_slopes_meet_in_the_middle(self):
        """A rectangle, two OPPOSITE edges at 45°: the ridge sits at half the
        width, not the whole of it. The old formula gave exactly twice as much."""
        outline = [(0, 0), (4000, 0), (4000, 2000), (0, 2000)]
        rise = _expected_roof_rise_mm(outline, [45.0, None, 45.0, None])
        self.assertAlmostEqual(rise, 1000.0 * 0.95, delta=20.0)

    def test_a_single_slope_still_runs_the_whole_width(self):
        """A CONTROL FOR THE HALVING: a lone slope has nothing to meet, and the rise
        must stay full. Otherwise "divided by two" would have passed everywhere."""
        outline = [(0, 0), (4000, 0), (4000, 2000), (0, 2000)]
        rise = _expected_roof_rise_mm(outline, [45.0, None, None, None])
        self.assertAlmostEqual(rise, 2000.0 * 0.95, delta=20.0)

    def test_the_live_measurements_pass_and_the_bound_stays_below_them(self):
        """Three K3 roofs, measured live on 24.08: the threshold must be BELOW
        what was actually built, otherwise the witness will go red again on a correct roof."""
        cases = (
            # (loop, slopes, measured rise in mm)
            # The loop and the slopes are VERBATIM from the K3 transfer program (the traversal
            # order is load-bearing: slopes are tied to edges by index).
            ([(14020.0, 33538.7), (14020.0, 34618.7),
              (15355.0, 34618.7), (15355.0, 33538.7)],
             [None, 16.699244, 16.699244, 16.699244], 182.9),
        )
        for outline, slopes, measured in cases:
            with self.subTest(measured=measured):
                self.assertLess(_expected_roof_rise_mm(outline, slopes), measured)

    def test_a_roof_built_at_the_WRONG_pitch_is_still_caught(self):
        """STRICTNESS IS NOT SURRENDERED. The earlier draft caught a roof built at
        38° instead of the requested 45°, and the new one must catch it too — otherwise
        fixing the false red would have bought a false green."""
        outline = [(0, 0), (4000, 0), (4000, 2000), (0, 2000)]
        bound = _expected_roof_rise_mm(outline, [45.0, None, 45.0, None])
        built_wrong = 1000.0 * math.tan(math.radians(38.0)) / math.tan(math.radians(45.0))
        self.assertLess(built_wrong, bound)

    def test_the_verdict_prints_what_it_measured(self):
        """The rule of this house: when postconditions are violated the transaction
        rolls back, and NO ONE sees the numbers. The slope case had none of this — the reason
        for 24.08 had to be worked out by side arithmetic."""
        prog = {"ir_version": "1.0", "ops": [{
            "op": "create_roof", "id": "R1",
            "outline": [[0, 0], [4000, 0], [4000, 2000], [0, 2000]],
            "level": {"by": "element_id", "value": 42},
            "slopes": [45.0, None, 45.0, None]}]}
        out = compile_program(prog, revit_version="2024",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, out.diagnostics)
        self.assertIn("уклон крыши не тот", out.csharp)
        self.assertIn("мм против ожидаемых не менее", out.csharp)
