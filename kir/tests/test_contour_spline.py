"""THE THIRD KIND OF EDGE — SPLINE: freedom of form WITHOUT a family
document door.

WHY THIS FILE, BY THE 20.08.2026 MEASUREMENTS.

A contour had TWO kinds of edge — a line and an arc. The language did not
express freeform curves in plan at all, even though the REVERSE move
decompiles splines in full (`decompile/name.py:78` knows six kinds,
`geom_extract.py` reads degree/knots/weights, `recompile.py` reassembles
via `NurbSpline.CreateCurve`). We could read what we could not say.

🔴 AND HERE IS THE NUMBER THAT NEARLY CANCELED THIS WORK — IT IS HERE SO
THE NEXT PERSON DOES NOT MISTAKE IT FOR A REFUTATION. A corpus census (67
decompiles):

    location curves       230,598   line 91.99% · arc 1.58% · no curve 6.43%
    curves in sketches    148,894   line 96.13% · arc 3.87%
    splines                     0   in both

The extractor is NOT blind here, though: it has a named kind,
`spline_unsupported`, for `HermiteSpline`/`NurbSpline`, and it would have
recorded it at either end. It recorded it not once. That is, there is NO
DEBT — there is nothing to fix in existing buildings. But the corpus is
made of standard Russian projects, where freeform curves are absent BY
CONSTRUCTION, and the zero speaks about the corpus, not about the task.
Hence the acceptance rule for this kind: **it cannot be accepted by a
count of closed atoms, only by building what cannot be said today.**

WHY INTERPOLATION, NOT A CONTROL POLYGON. `NurbSpline.CreateCurve` takes
control points, and the curve does NOT pass through them; `HermiteSpline
.Create` takes points the curve does pass through. For an environment
whose primary user is an LLM, the constitution settles this: "draw a
curve through these points" is something the model can verify for itself,
while a control polygon also requires holding Revit's smoothing rule in
one's head. Both factories score 6/6 on `data/api_surface`; the compile
probe for the whole chain is 5/5 (`Floor.Create` has existed since 2022),
and the CS0117 and CS0200 controls both discriminate.

WHERE A SPLINE BREAKS HONESTY, THERE IS A REFUSAL, NOT AN APPROXIMATION.
Area, moment, and length for a curve whose shape between points is chosen
by Revit itself have no closed form; the "start-middle-end" witness
degenerates on it into a chord, and the chord is the same for a straight
line and for any curve between the same endpoints. Both cases are named
refusals with a named experiment that will open them up. This is the same
law that holds the five refused body factories in `ops_solid`.
"""
from __future__ import annotations

import json
import unittest

from kir import contour as C
from kir.schema_gen import program_schema

_SQUARE = [[0, 0], [30000, 0], [30000, 20000], [0, 20000]]
_VIA = [[10000, 3000], [20000, -3000]]


def _shape(**extra) -> dict:
    return {"shape": "poly", "points_mm": _SQUARE, **extra}


def _validate(shape, diags=None):
    return C._validate_shape(shape, [], "F1", "c.outer",
                             diags if diags is not None else [])


class TheKindTravelsOnTheEdge(unittest.TestCase):
    """The edge remains a TRIPLE; the kind carries the TYPE of the third
    element."""

    def test_the_edge_is_still_a_triple(self) -> None:
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        self.assertIsNotNone(edges)
        for e in edges:
            self.assertEqual(len(e), 3, "распаковка `for p0, p1, b in edges` цела")

    def test_the_type_carries_the_kind(self) -> None:
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        self.assertTrue(C.is_spline(edges[0][2]))
        self.assertFalse(C.is_spline(edges[1][2]))
        self.assertIsInstance(edges[1][2], float)

    def test_a_spline_edge_is_not_straight(self) -> None:
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        self.assertFalse(C.edges_are_straight(edges))

    def test_arc_and_spline_are_different_questions(self) -> None:
        """One question for two kinds would be one code for two different
        troubles.

        For an arc the measure is computed exactly, for a spline it is not
        computed at all — so `region_has_arc` (which decides the fate of
        the AREA witness) must answer about the arc, and only the arc.
        """
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        region = {"outer": edges}
        self.assertTrue(C.region_has_spline(region))
        self.assertFalse(C.region_has_arc(region))

    def test_the_spline_value_is_hashable_and_comparable(self) -> None:
        """Fold canonicalization and the program digest compare edges
        directly."""
        a = C.Spline([[1, 2], [3, 4]])
        b = C.Spline([[1, 2], [3, 4]])
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, C.Spline([[1, 2], [3, 5]]))


class TheEmissionSaysTheCurve(unittest.TestCase):

    def test_the_loop_emits_an_interpolating_spline(self) -> None:
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        cs = C.emit_loop_cs(edges, "__cl")
        self.assertIn("HermiteSpline.Create(", cs)
        self.assertNotIn("NurbSpline", cs,
                         "контрольный многоугольник — не наш род входа")
        self.assertEqual(cs.count("Line.CreateBound("), 3)

    def test_the_declared_points_ride_in_order_between_the_ends(self) -> None:
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        cs = C.emit_loop_cs(edges, "__cl")
        head = cs.split("HermiteSpline.Create(", 1)[1].split("}", 1)[0]
        order = [head.index(f"{v:.1f}") for v in (0.0, 10000.0, 20000.0, 30000.0)]
        self.assertEqual(order, sorted(order),
                         "точки обязаны ехать в объявленном порядке")

    def test_all_three_containers_agree_on_the_curve(self) -> None:
        """CurveLoop / CurveArray / List<Curve> differ by CONTAINER and
        nothing else.

        The edge's body is the same for all of them (`_edge_curve_cs`);
        were it to diverge, the bounding-box witness would agree with any
        copy, meaning a mistake would be invisible.
        """
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        for cs in (C.emit_loop_cs(edges, "__v"),
                   C.emit_curvearray_cs(edges, "__v"),
                   C.emit_curve_list_cs(edges, "__v")):
            self.assertEqual(cs.count("HermiteSpline.Create("), 1, cs[:200])


class WhereTheMeasureBreaksItRefuses(unittest.TestCase):
    """A silently wrong number is worse than a missing one."""

    def test_measures_refuse_by_name(self) -> None:
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        with self.assertRaises(C.SplineMeasureUnavailable):
            C.edge_measures(*edges[0])

    def test_the_triple_witness_refuses_by_a_DIFFERENT_name(self) -> None:
        """The measure and the witness are different questions with
        different remedies."""
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]))
        with self.assertRaises(C.SplineWitnessShape):
            C.edge_witness_triples(edges)
        self.assertFalse(
            issubclass(C.SplineWitnessShape, C.SplineMeasureUnavailable))
        self.assertFalse(
            issubclass(C.SplineMeasureUnavailable, C.SplineWitnessShape))

    def test_the_spline_has_its_own_witness_and_it_names_the_edge(self) -> None:
        # Edge 2 runs [30000,20000] -> [0,20000]; the points are taken
        # NEAR it, otherwise the curve runs through the whole ring and
        # gets legitimately caught by self-intersection — meaning the test
        # would be measuring something other than what it names.
        edges = _validate(_shape(splines=[{"edge": 2,
                                           "via_mm": [[20000, 23000], [10000, 17000]]}]))
        self.assertIsNotNone(edges, "контур обязан быть законным")
        self.assertEqual(C.spline_witness_points(edges),
                         [(2, [[20000.0, 23000.0], [10000.0, 17000.0]])])

    def test_a_ring_without_splines_still_measures(self) -> None:
        """CONTROL: the refusal must be NARROW, not "the measures
        broke"."""
        edges = _validate(_shape(arcs=[{"edge": 0, "bulge": 0.3}]))
        self.assertEqual(len(C.edge_witness_triples(edges)), 4)
        self.assertTrue(C.loop_measures(edges)[0] > 0)


class TheRefusalsAreOneCodePerBeef(unittest.TestCase):

    def _refusal(self, **extra) -> str:
        diags: list = []
        edges = _validate(_shape(**extra), diags)
        self.assertIsNone(edges, "ожидался отказ")
        self.assertTrue(diags, "отказ обязан нести причину")
        return diags[0].message_ru

    def test_one_edge_one_kind_arc_then_spline(self) -> None:
        msg = self._refusal(arcs=[{"edge": 0, "bulge": 0.3}],
                            splines=[{"edge": 0, "via_mm": _VIA}])
        self.assertIn("один род", msg)

    def test_one_edge_one_kind_two_splines(self) -> None:
        msg = self._refusal(splines=[{"edge": 0, "via_mm": _VIA},
                                     {"edge": 0, "via_mm": [[100, 100]]}])
        self.assertIn("один род", msg)

    def test_too_few_and_too_many_say_OPPOSITE_things(self) -> None:
        """Merged texts would advise the opposite: add a point, or
        split."""
        few = self._refusal(splines=[{"edge": 0, "via_mm": []}])
        many = self._refusal(splines=[{"edge": 0,
                                       "via_mm": [[i * 100 + 100, 50]
                                                  for i in range(C.SPLINE_VIA_MAX + 1)]}])
        self.assertIn("хотя бы одна", few)
        self.assertIn("НЕСКОЛЬКИМИ рёбрами", many)
        self.assertNotEqual(few, many)

    def test_a_zero_span_is_caught_statically(self) -> None:
        msg = self._refusal(splines=[{"edge": 0, "via_mm": [[0.2, 0.0]]}])
        self.assertIn("нулевой пролёт", msg)

    def test_an_unknown_field_is_refused(self) -> None:
        self._refusal(splines=[{"edge": 0, "via_mm": _VIA, "degree": 3}])

    def test_an_edge_out_of_range_is_refused(self) -> None:
        self._refusal(splines=[{"edge": 9, "via_mm": _VIA}])

    def test_a_point_that_is_not_a_pair_is_refused(self) -> None:
        msg = self._refusal(splines=[{"edge": 0, "via_mm": [[1000, 2000, 3000]]}])
        self.assertIn("[x, y]", msg)

    def test_self_intersection_sees_the_spline(self) -> None:
        """The self-intersection law must sample the spline, not treat it
        as a chord."""
        msg = self._refusal(splines=[{"edge": 0,
                                      "via_mm": [[10000, 60000], [20000, -60000]]}])
        self.assertIn("самопересечение", msg)
        self.assertIn("сплайн", msg, "текст обязан назвать род, который его поймал")


class TheModelIsTOLD(unittest.TestCase):
    """A capability the model does not know about is not built
    (constitution)."""

    def test_the_slot_reaches_the_schema_the_model_receives(self) -> None:
        s = json.dumps(program_schema(), ensure_ascii=False)
        self.assertIn("splines", s)
        self.assertIn("via_mm", s)

    def test_every_shape_field_the_validator_knows_is_declared(self) -> None:
        """A RATCHET. The schema has `additionalProperties: false`, so a
        field known to the validator but unknown to the schema hands the
        model a refusal on a LEGITIMATE program. The reverse case was paid
        for on 16.08.2026 — three programs out of three were legitimate by
        the schema and rejected by the compiler. Both sides of the same
        discrepancy, and one check catches them both.
        """
        s = json.dumps(program_schema(), ensure_ascii=False)
        missing = {kind: sorted(f for f in C.shape_fields(kind)
                                if f != "shape" and f'"{f}"' not in s)
                   for kind in C.SHAPE_FORMS}
        self.assertEqual({k: v for k, v in missing.items() if v}, {})

    def test_the_bounds_are_the_registry_s_and_not_a_literal(self) -> None:
        """Two numbers that are supposed to match drift apart silently."""
        s = program_schema()
        found = []

        def walk(o):
            if isinstance(o, dict):
                if o.get("properties", {}).get("via_mm"):
                    found.append(o["properties"]["via_mm"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(s)
        self.assertTrue(found, "via_mm не найден в схеме")
        for v in found:
            self.assertEqual(v["minItems"], C.SPLINE_VIA_MIN)
            self.assertEqual(v["maxItems"], C.SPLINE_VIA_MAX)


class NothingWithoutASplineMoved(unittest.TestCase):
    """A CONTROL WITHOUT WHICH EVERYTHING ABOVE IS WORTHLESS.

    The kind was added so that the bytes of a program WITHOUT a spline do
    not shift by a single character — otherwise the parity ratchet would
    turn red with a second consecutive shift, and the next person would
    read that red as background noise.
    """

    def test_a_plain_ring_emits_exactly_as_before(self) -> None:
        edges = _validate(_shape())
        cs = C.emit_loop_cs(edges, "__cl")
        self.assertEqual(cs.count("Line.CreateBound("), 4)
        self.assertNotIn("Spline", cs)

    def test_an_arc_ring_emits_exactly_as_before(self) -> None:
        edges = _validate(_shape(arcs=[{"edge": 0, "bulge": 0.5}]))
        cs = C.emit_loop_cs(edges, "__cl")
        self.assertEqual(cs.count("Arc.Create("), 1)
        self.assertNotIn("Spline", cs)


# 🔴 CODE E009 -> E010 (21.08.2026). It was not "renamed for convenience":
# `KIR-E009` was carried by TWO names with incompatible fixes —
# `EMIT_CONTOUR_SPLINE` (diag.py) and `BEAM_SYSTEM_BAD_DIRECTION_EDGE`
# (struct_emit.py), because the code space was being issued independently
# from two files. The newcomer from the 20.08 wave moved out; the senior
# code stayed.
class TheOpRefusesUntilItCanWitness(unittest.TestCase):
    """The language can SAY a curve BEFORE the ops can PROVE it.

    This is not a half-measure, but the only honest order. The spline's
    bounding box is UNDERSTATED (Revit chooses the shape between the
    points, we know only our own sampling), the "start-middle-end" triple
    degenerates into a chord. Skipping this would have meant building the
    curve and signing off on a bounding box nobody ever checked — a
    silently wrong outcome, forbidden by the cardinal invariant.
    """

    #: An op that does NOT know how to PROVE a spline. Taken from the
    #: registry itself, not written in by name: the list of capable ops
    #: grows, and a test that named the op as a literal would one day
    #: start measuring the wrong thing — form 25 (a ratchet that names a
    #: path).
    @staticmethod
    def _unwitnessed_contour_op() -> tuple[str, str]:
        """(the op's name, the name of ITS contour slot) — both from the
        registry.

        The slot is called differently across ops: `contour` for a slab,
        `profile` for a beam system, `outline` for others. Writing the
        name in as a literal would mean measuring the wrong op (form 25),
        and this already happened: the first edition fed `contour` to an
        op whose slot is `profile`, and got KIR-P003 instead of KIR-E009 —
        meaning it was checking the decompile, not the guard.
        """
        from kir import contour as C, spec
        for name, ospec in sorted(spec.OPS.items()):
            if name in C.SPLINE_WITNESSED_OPS:
                continue
            for p in ospec.params:
                if p.kind == "region":
                    return name, p.name
        raise AssertionError("контурного опа без свидетеля сплайна не нашлось")

    @staticmethod
    def _ground(extra, op_name=None, slot="contour"):
        from kir import ground as ground_mod, spec
        from kir.diag import KirRefusal
        from kir.tests.emit_parity_fixtures.generate_fixtures import (
            GROUND_SNAPSHOT, _parse_and_check)
        op_name = op_name or "create_floor_by_contour"
        body = {"op": op_name, "id": "F1",
                slot: {"outer": {"shape": "poly",
                                 "points_mm": _SQUARE, **extra}}}
        # 🔴 REQUIRED SLOTS ARE FILLED FROM THE REGISTRY'S SAMPLE TABLE,
        # NOT WITH ZERO (21.08.2026). Here stood `else 0` for everything
        # except the selector, and it worked exactly as long as the op
        # under test was one whose required fields were all numbers.
        #
        # On 21.08 `author_family` entered the registry — and landed
        # FIRST alphabetically among ops of kind `region`, meaning it
        # became exactly the "op with no spline witness" that this test
        # picks by inference. It has three required STRING slots; a zero
        # in them produces KIR-T001 already at decompile time, and the
        # move never reaches the spline guard at all. The test was
        # turning red while checking the decompile instead of the guard —
        # exactly the form 25 its own author had already moved away from
        # once before ("the first edition fed `contour` to an op whose
        # slot is `profile`").
        #
        # `_sample` is the ONE carrier of samples for the whole tree, with
        # its own guard against "a new parameter kind with no sample" and
        # a cutoff at the parameter's own bounds. A table of its own here
        # would be a second carrier, and it would drift apart from the
        # first at the very next new kind.
        from kir.tests.test_sdk import _sample
        for p in spec.OPS[op_name].params:
            if p.required and p.name not in body:
                body[p.name] = ({"by": "element_id", "value": 42}
                                if p.kind == "sel" else _sample(p))
        prog = {"ir_version": "1.0", "intent": "контур", "ops": [body]}
        try:
            ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
            return None
        except KirRefusal as exc:
            return exc

    def test_an_op_without_the_witness_refuses_before_any_effect(self) -> None:
        op, slot = self._unwitnessed_contour_op()
        exc = self._ground({"splines": [{"edge": 0, "via_mm": _VIA}]}, op, slot)
        self.assertIsNotNone(exc, "сплайн обязан отказать, пока свидетеля нет")
        self.assertIn("KIR-E010", str(exc))

    def test_the_refusal_names_the_next_move(self) -> None:
        """Every refusal names the reason AND the next move (the LLM
        profile)."""
        op, slot = self._unwitnessed_contour_op()
        text = str(self._ground({"splines": [{"edge": 0, "via_mm": _VIA}]}, op, slot))
        self.assertIn("Следующий ход", text)
        self.assertIn("arcs", text)

    def test_the_op_WITH_a_witness_now_passes(self) -> None:
        """THE OTHER SIDE, WITHOUT WHICH THE FIRST MEANS NOTHING.

        A guard that refuses EVERYONE is indistinguishable from "the kind
        is not built". The check must show that the list of capable ops
        WORKS, not merely that the incapable ones are refused.
        """
        self.assertIn("create_floor_by_contour", C.SPLINE_WITNESSED_OPS)
        self.assertIsNone(
            self._ground({"splines": [{"edge": 0, "via_mm": _VIA}]},
                         "create_floor_by_contour"))

    def test_the_refusal_is_NARROW(self) -> None:
        """CONTROL: a broad refusal would be a blunt guard, not a strict
        one."""
        self.assertIsNone(self._ground({}))
        self.assertIsNone(self._ground({"arcs": [{"edge": 0, "bulge": 0.3}]}))

    def test_the_code_is_its_own_and_not_the_holes_one(self) -> None:
        """E008 is about EMISSION («the op does not express the hole»),
        E009 is about the WITNESS.

        The fixes are opposites: the hole is removed from the contour, the
        curve is taught to be checked. The consumer branches on the code —
        one code for two outcomes is exactly the named defect of this
        tree.
        """
        from kir import diag
        self.assertNotEqual(diag.EMIT_CONTOUR_SPLINE, diag.EMIT_CONTOUR_HOLES)

    def test_the_witnessed_list_is_closed_and_says_what_empty_means(self) -> None:
        """Empty means "does not prove", not "there is no such thing as a
        spline"."""
        import inspect
        self.assertIsInstance(C.SPLINE_WITNESSED_OPS, frozenset)
        src = inspect.getsource(C)
        head = src.split("SPLINE_WITNESSED_OPS:", 1)[0]
        comment = head[head.rindex("#: OPS WHOSE WITNESS CAN PROVE A SPLINE."):]
        self.assertIn("does NOT PROVE a spline", comment,
                      "род списка обязан быть объявлен В ЕГО СОБСТВЕННОМ "
                      "комментарии: отсутствие записи значит РАЗНОЕ у двух "
                      "родов списков, и читатель решает по нему")


_ЗА_ОХВАТОМ = 1_000_000_000.0


def _via_негодных(k: int, start: int = 0):
    """`k` points, each knowingly beyond the coverage limit (~16 km)."""
    return [[_ЗА_ОХВАТОМ, _ЗА_ОХВАТОМ + start + i] for i in range(k)]


class ВСЕНЕГОДНЫЕТОЧКИКРИВОЙНАЗЫВАЮТСЯ(unittest.TestCase):
    """The refusal names ALL bad curve points, not just the first.

    WHAT THIS CLASS COST (26.08.2026). A twin of the defect fixed for the
    RING by commit `030895dd`; that commit named it unclosed, verbatim:
    «тот же обрыв стоит у точек СПЛАЙНА — `return None` сразу после
    диагностики».

    Here the break was WIDER than for the ring: it carried away not only
    the rest of THIS curve's points, but ALL SUBSEQUENT splines as well —
    the decompile never reached them. Measured on HEAD before the fix,
    `create_filled_region`, a 4×2.5 m square:

        1 spline × 4 bad points   ->  4 submitted, 1 named
        3 splines × 5 bad = 15    ->  15 submitted, 1 named

    The cost comes in circles: the author fixes one point, gets a refusal
    on the next one, and each time thinks it is the last. The same law
    `create_wall`'s refusal already obeys verbatim: «закрой недостающие
    ОДНИМ ходом, а не по одному за ход».

    THE INSTRUMENT HERE IS DIRECT (`_validate_shape`), not via
    `compile_program`, and this is NOT a convenience: for
    `create_filled_region` a spline is rejected earlier, by `KIR-E010`
    («свидетель этого опа доказывает только прямые и дуги»), and there is
    no way to run a valid curve through it at all. The subject of this
    class is COMPLETENESS OF ENUMERATION in contour decompiling, not the
    op's policy.
    """

    def _diags(self, splines):
        diags: list = []
        _validate(_shape(splines=splines), diags)
        точки = [d for d in diags if "via_mm[" in str(d.field_name)]
        остаток = [d for d in diags if str(d.field_name) == "c.outer.splines"]
        return diags, точки, остаток

    def test_ОДНА_кривая_называет_все_свои_негодные_точки(self) -> None:
        """🔴 RED before the fix: only one of four was being named."""
        _, точки, остаток = self._diags([{"edge": 0, "via_mm": _via_негодных(4)}])
        self.assertEqual(len(точки), 4, [str(d.field_name) for d in точки])
        self.assertEqual(остаток, [], "четыре меньше предела — приписки быть не должно")

    def test_СЛЕДУЮЩИЕ_кривые_тоже_разбираются(self) -> None:
        """🔴 Here the break was wider than the ring's: WHOLE splines were
        being left unmentioned.

        Three curves with two bad points each: if the decompile breaks off
        on the first curve, only 1 of 6 will be named, and the author will
        never learn about edges 1 and 2 at all — and having fixed edge 0,
        will get a refusal on edge 1 on the very next move.
        """
        _, точки, _ = self._diags(
            [{"edge": e, "via_mm": _via_негодных(2, start=e * 10)} for e in (0, 1, 2)])
        рёбра = {str(d.field_name).split("splines[")[1][0] for d in точки}
        self.assertEqual(len(точки), 6, [str(d.field_name) for d in точки])
        self.assertEqual(рёбра, {"0", "1", "2"})

    def test_перечень_ОГРАНИЧЕН_а_остаток_назван_ПОЛНЫМ_числом(self) -> None:
        """The cap is the other half of the same fix, not caution.

        There can be up to `n` curves of `SPLINE_VIA_MAX` points each, and
        a single-unit error can make ALL of them bad at once. Removing the
        cap would trade a silent loss for a refusal running to dozens of
        diagnostics — the very expense this tree fixed twice on the same
        day.
        """
        _, точки, остаток = self._diags(
            [{"edge": e, "via_mm": _via_негодных(5, start=e * 10)} for e in (0, 1, 2)])
        self.assertEqual(len(точки), C._BAD_POINTS_SHOWN)
        self.assertEqual(len(остаток), 1, "остаток обязан быть НАЗВАН")
        self.assertEqual(остаток[0].got, 15,
                         "число остатка обязано быть ПОЛНЫМ: считаются и те "
                         "негодные, что после предела не названы поимённо")
        self.assertIn("названы первые", str(остаток[0].message_ru))

    def test_КОНТРОЛЬ_одна_негодная_точка_даёт_ровно_один_отказ(self) -> None:
        """The upper bound: "name them all" must not slide into excess
        refusals."""
        _, точки, остаток = self._diags([{"edge": 0, "via_mm": _via_негодных(1)}])
        self.assertEqual(len(точки), 1)
        self.assertEqual(остаток, [], "приписки «и ещё 0» быть не должно")

    def test_КОНТРОЛЬ_PASS_годная_кривая_не_даёт_НИ_ОДНОЙ_диагностики(self) -> None:
        """A degenerate input. Without it, the prohibition would be green
        by construction."""
        diags: list = []
        edges = _validate(_shape(splines=[{"edge": 0, "via_mm": _VIA}]), diags)
        self.assertEqual(diags, [], [str(d.message_ru)[:70] for d in diags])
        self.assertIsNotNone(edges)

    def test_смесь_родов_негодности_считается_ОДНИМ_счётом(self) -> None:
        """«Не тот род» and «за охватом» are two texts but one subject.

        Different counters would give two separate footnotes about what
        remains, and the author would not be able to add them into one
        number: "how much do I have left to fix".
        """
        _, точки, _ = self._diags([{"edge": 0, "via_mm": [
            ["x", "y"], [_ЗА_ОХВАТОМ, _ЗА_ОХВАТОМ], [1500, 900], [_ЗА_ОХВАТОМ, 3]]}])
        self.assertEqual(len(точки), 3, [str(d.field_name) for d in точки])


if __name__ == "__main__":
    unittest.main()
