"""A SMOOTH SURFACE — VALUE KIND, LAWS, EMISSION, AND WITNESS.

WHY THIS FILE. Before 20.08.2026, a free-form shape was expressed by
exactly one kind — a mesh, i.e. FACETS. A smooth shell of double
curvature — the very thing Rhino and Grasshopper use to make a complex
facade — the language could not express at all, no matter how many
triangles you laid down.

MEASURED BY COMPILATION, six versions, controls that distinguish (CS0117
on an invented member, CS1501 on a foreign arity, CS0200 on a write to a
read-only):

    full assembly BRepBuilder -> Solid -> DirectShape                6/6
    4×4 degree-3 emission, non-rational                              6/6
    8×6 degree-3 emission                                            6/6
    4×4 RATIONAL emission (with weights)                             6/6
    2×2 degree-1×1 emission (ruled)                                  6/6

🔴 WHAT THIS FILE DOES NOT PROVE, AND THIS IS A BOUNDARY, NOT A CAVEAT. It
proves that the CHANNEL exists and that it cannot silently close. Whether
Revit will accept the control points WITHOUT RECOMPUTING them cannot be
checked offline in any way; the witness is built so that unknown behavior
shows up as NOISE, not silence (the same direction of refusal chosen for
the mesh's face-count witness). The u-major order of points is a NAMED
ASSUMPTION, and the first live run will answer it red or green.
"""
from __future__ import annotations

import contextlib
import re
import unittest

from kir import spec
from kir import surface as S
from kir.ops_surface import OPS as SURFACE_OPS


@contextlib.contextmanager
def _registered():
    """The op is not yet in `spec.py`; the permanent registration happens
    as a patch into the registry.

    🔴 THE REGISTRATION IS REVERSIBLE, AND THIS WAS PAID FOR IN THIS VERY
    SESSION. The first edition put the op into `spec.OPS` via
    `setdefault` and DID NOT REMOVE it — meaning it was dirtying SHARED
    MUTABLE STATE for the whole process. On its own, the file was green;
    alongside its neighbors, `test_shape_census` went red with FOUR
    checks, because the shape capability census was finding an op in the
    registry with no emitter and no schema slot. The red, meanwhile, was
    pointing at SOMEONE ELSE'S file — exactly the shape that gets
    someone else's red read as your own for half a day.

    A test that needs someone else's state must GIVE IT BACK.
    """
    added = [op.name for op in SURFACE_OPS if op.name not in spec.OPS]
    for op in SURFACE_OPS:
        spec.OPS.setdefault(op.name, op)
    try:
        yield
    finally:
        for name in added:
            spec.OPS.pop(name, None)


def _grid(nu: int = 4, nv: int = 4) -> list:
    return [[iu * 1000.0, iv * 1000.0, ((iu * iv) % 3) * 300.0]
            for iu in range(nu) for iv in range(nv)]


def _value(**over) -> dict:
    base = {"degree_u": 3, "degree_v": 3, "count_u": 4, "count_v": 4,
            "knots_u": S.uniform_clamped_knots(3, 4),
            "knots_v": S.uniform_clamped_knots(3, 4),
            "control_points_mm": _grid()}
    base.update(over)
    return base


def _validate(value: dict):
    diags: list = []
    return S.validate_surface(value, "S1", "surface", diags), diags


class TheValueIsAcceptedWhole(unittest.TestCase):

    def test_a_healthy_surface_passes(self) -> None:
        out, diags = _validate(_value())
        self.assertIsNotNone(out, [d.message_ru for d in diags])
        self.assertEqual(out["degree_u"], 3)
        self.assertEqual(len(out["control_points_mm"]), 16)
        self.assertIsNone(out["weights"], "отсутствие весов = НЕрациональная")

    def test_weights_are_optional_and_absence_is_not_ones(self) -> None:
        """The absence of weights is a FACT (non-rational), not "let's
        substitute ones".

        Substituting would be a silent edit of the input: a rational
        surface with unit weights and a non-rational one are different
        objects for the reverse pass (`IsRational` is read separately),
        and gluing them together would introduce a divergence between
        the forward and reverse passes out of thin air.
        """
        out, _ = _validate(_value(weights=[1.0] * 16))
        self.assertEqual(out["weights"], [1.0] * 16)
        out2, _ = _validate(_value())
        self.assertIsNone(out2["weights"])

    def test_the_helper_builds_a_clamped_vector_and_refuses_short_grids(self) -> None:
        self.assertEqual(S.uniform_clamped_knots(3, 4),
                         [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        self.assertEqual(S.uniform_clamped_knots(1, 2), [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(len(S.uniform_clamped_knots(3, 6)), 6 + 3 + 1)
        with self.assertRaises(ValueError):
            S.uniform_clamped_knots(3, 3)

    def test_there_is_no_default_knot_vector(self) -> None:
        """There is DELIBERATELY no default for the knots — knots are
        part of the surface's DEFINITION.

        Substituting them silently would mean building a different
        surface from the one that was sent: the same class as "0 instead
        of a missing value", which in this house has already cost
        96.77% of the groups.
        """
        v = _value()
        del v["knots_u"]
        out, diags = _validate(v)
        self.assertIsNone(out)
        self.assertIn("не хватает", diags[0].message_ru)


class EveryDegeneracyHasItsOwnName(unittest.TestCase):
    """One code for two troubles is a named defect of this tree."""

    def _refusal(self, **over):
        out, diags = _validate(_value(**over))
        self.assertIsNone(out, "ожидался отказ")
        self.assertTrue(diags, "отказ обязан нести причину")
        return diags[0]

    def test_degree_bounds(self) -> None:
        self.assertIn("1..7", self._refusal(degree_u=0).message_ru)
        self.assertIn("1..7", self._refusal(degree_u=8).message_ru)

    def test_too_few_control_points_for_the_degree(self) -> None:
        d = self._refusal(count_u=3, control_points_mm=_grid(3, 4),
                          knots_u=[0, 0, 0, 0, 1, 1, 1])
        self.assertIn("базис NURBS", d.message_ru)

    def test_the_grid_must_be_rectangular(self) -> None:
        d = self._refusal(control_points_mm=_grid()[:-1])
        self.assertIn("count_u × count_v", d.message_ru)

    def test_knot_count_is_an_identity_not_a_convention(self) -> None:
        d = self._refusal(knots_u=[0, 0, 0, 0, 1, 1, 1])
        self.assertEqual(d.code, S.SURFACE_KNOTS)
        self.assertIn("count + degree + 1", d.message_ru)

    def test_knots_must_not_decrease(self) -> None:
        d = self._refusal(knots_u=[0, 0, 0, 0.5, 0.2, 1, 1, 1])
        self.assertEqual(d.code, S.SURFACE_KNOTS)
        self.assertIn("не неубывают", d.message_ru)

    def test_knots_must_be_clamped_like_the_reverse_pass_demands(self) -> None:
        """The law is taken verbatim from the reverse pass — the two
        ends of the wire are one and the same.

        🔴 THE TWO ENDS ARE CHECKED SEPARATELY, AND THIS WAS PAID FOR BY
        A CONTROL ON ITSELF (20.08.2026). The first edition fed in
        `[0,0,0,0.1,0.9,1,1,1]` — an input that violates BOTH ends at
        once — and the "remove the start check" FAIL control left the
        test GREEN: the tail end was catching it. An experiment with
        only one outcome proves nothing, whichever way it comes out
        (form 8). Now each end has an input that violates ONLY that end.
        """
        head_only = self._refusal(knots_u=[0, 0, 0, 0.1, 1, 1, 1, 1])
        self.assertEqual(head_only.code, S.SURFACE_KNOTS)
        self.assertIn("первые", head_only.message_ru)
        tail_only = self._refusal(knots_u=[0, 0, 0, 0, 0.9, 1, 1, 1])
        self.assertEqual(tail_only.code, S.SURFACE_KNOTS)
        self.assertIn("последние", tail_only.message_ru)

    def test_three_knot_diseases_say_three_different_things(self) -> None:
        """A CONTROL on the previous three: the texts must be DIFFERENT.

        The remedies are opposite — add more knots, sort them, weld the
        ends — and a shared text would be giving the reader the wrong
        advice.
        """
        msgs = {self._refusal(knots_u=[0, 0, 0, 0, 1, 1, 1]).message_ru,
                self._refusal(knots_u=[0, 0, 0, 0.5, 0.2, 1, 1, 1]).message_ru,
                self._refusal(knots_u=[0, 0, 0, 0.1, 0.9, 1, 1, 1]).message_ru}
        self.assertEqual(len(msgs), 3)

    def test_weights_must_be_strictly_positive(self) -> None:
        d = self._refusal(weights=[1.0] * 15 + [0.0])
        self.assertIn("СТРОГО положительным", d.message_ru)

    def test_weight_count_must_match(self) -> None:
        self._refusal(weights=[1.0] * 15)

    def test_a_surface_collapsed_to_a_curve_is_not_a_surface(self) -> None:
        d = self._refusal(control_points_mm=[[i * 1000.0, 0.0, 0.0]
                                             for i in range(16)])
        self.assertEqual(d.code, S.SURFACE_DEGENERATE)

    def test_coincident_corners_would_give_a_zero_edge(self) -> None:
        d = self._refusal(control_points_mm=[[0.0, 0.0, 0.0]] * 4 + _grid()[4:])
        self.assertEqual(d.code, S.SURFACE_CORNER)
        self.assertIn("изопараметрическими", d.message_ru)

    def test_an_unknown_field_is_refused(self) -> None:
        v = _value()
        v["degree_w"] = 3
        out, diags = _validate(v)
        self.assertIsNone(out)
        self.assertIn("лишнее", diags[0].message_ru)

    def test_a_coordinate_outside_revit_space_is_refused(self) -> None:
        d = self._refusal(control_points_mm=[[1e9, 0, 0]] + _grid()[1:])
        self.assertIn("рабочего пространства", d.message_ru)

    def test_the_coordinate_limit_has_ONE_source(self) -> None:
        """A mesh and a surface live in the same Revit and run up
        against the same boundary."""
        from kir import mesh
        self.assertIs(S.COORD_MAX_MM, mesh._COORD_MAX_MM)


class TheEmissionSaysTheSurface(unittest.TestCase):

    def setUp(self) -> None:
        self._ctx = _registered()
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from kir.surface_emit import emit_surface
        self._emit = emit_surface
        out, diags = _validate(_value())
        self.assertIsNotNone(out, [d.message_ru for d in diags])
        self.op = {"id": "S1", "surface": out,
                   "category": "generic_model", "name": "оболочка"}

    def _cs(self, op=None) -> str:
        decl, create, checks, readback = self._emit(op or self.op, "2023", "st")
        return decl + create + "".join(
            c.reader_cs + c.verdict_cs for c in checks) + readback

    def test_the_surface_itself_is_a_nurbs(self) -> None:
        cs = self._cs()
        self.assertIn("BRepBuilderSurfaceGeometry.CreateNURBSSurface(3, 3,", cs)

    def test_boundary_edges_are_EXACT_isoparametric_curves(self) -> None:
        """🔴 LOAD-BEARING. The chord between the corners coincides with
        the boundary only for a flat or ruled surface; on a curved one
        BRepBuilder would get a loop lying outside the face and would
        discard it — silently, unless RemovedSomeFaces is asked about.
        """
        cs = self._cs()
        self.assertEqual(cs.count("NurbSpline.CreateCurve("), 4,
                         "четыре границы — четыре ТОЧНЫЕ кривые")
        head = cs.split("BRepBuilder __bb_", 1)[0]
        self.assertNotIn("Line.CreateBound(", head,
                         "граница хордой — приближение там, где есть тождество")

    def test_the_shell_is_OPEN_and_that_is_stated(self) -> None:
        """A single face does not form a closed body; declaring it a
        Solid would be a lie."""
        self.assertIn("BRepType.OpenShell", self._cs())

    def test_revit_is_asked_whether_it_threw_a_face_away(self) -> None:
        """A shell missing a single face is, from the outside,
        indistinguishable from success."""
        cs = self._cs()
        self.assertIn("RemovedSomeFaces()", cs)
        self.assertIn("IsResultAvailable()", cs)
        self.assertIn("выбросил грань", cs)

    def test_both_shell_failures_refuse_BEFORE_the_element_is_made(self) -> None:
        cs = self._cs()
        pos_refuse = cs.index("выбросил грань")
        pos_create = cs.index("DirectShape.CreateElement")
        self.assertLess(pos_refuse, pos_create,
                        "отказ обязан стоять ДО эффекта")

    def test_the_honest_label_is_written_and_never_overwrites(self) -> None:
        cs = self._cs()
        self.assertIn("без BIM-смысла", cs)
        self.assertIn("string.IsNullOrEmpty", cs,
                      "чужое непустое значение не трогаем никогда")

    def test_the_receipt_says_what_the_result_is_NOT(self) -> None:
        cs = self._cs()
        for field in ('"bim_semantics"', '"has_type"',
                      '"schedulable_as_building_element"', '"human_editable"'):
            self.assertIn(field, cs)

    def test_a_rational_surface_carries_its_weights_into_every_curve(self) -> None:
        out, _ = _validate(_value(weights=[1.0] * 15 + [2.0]))
        op = dict(self.op, surface=out)
        cs = self._cs(op)
        self.assertEqual(cs.count("NurbSpline.CreateCurve("), 4)
        self.assertIn('"rational"', cs)


class TheWitnessReadsTheRESULT(unittest.TestCase):

    def setUp(self) -> None:
        self._ctx = _registered()
        self._ctx.__enter__()
        self.addCleanup(lambda: self._ctx.__exit__(None, None, None))
        from kir.surface_emit import emit_surface
        out, _ = _validate(_value())
        _decl, _create, self.checks, _rb = emit_surface(
            {"id": "S1", "surface": out, "category": "generic_model",
             "name": "оболочка"}, "2023", "st")
        # 🔴 `decl` IS PART OF THE SUBJECT, AND THIS WAS PAID FOR ON
        # 20.08. The previous edition was only concatenating
        # `reader_cs + verdict_cs`, and so it could not see the
        # declarations. When four of the witness's values moved into
        # `decl` — a fix for the canonical scope contract, the CS0103
        # class — this test went red on a CORRECT fix: it was measuring
        # not the program, but a piece of it.
        self.cs = _decl + "".join(c.reader_cs + c.verdict_cs
                                  for c in self.checks)

    def test_it_reads_back_with_the_SAME_instrument_as_the_reverse_pass(self) -> None:
        """The round trip closes only if both ends read the same
        thing."""
        self.assertIn("ExportUtils.GetNurbsSurfaceDataForSurface", self.cs)
        self.assertIn("GetControlPoints()", self.cs)

    def test_four_obligations_not_one(self) -> None:
        """'A different degree', 'different points', and 'a different
        surface' are three different repairs, and since 20.08 they have
        been split apart into three obligations.

        The fourth became `surface_samples` — a GEOMETRIC equality, the
        only assertion here that does not mention the parameterization.
        """
        keys = [c.obligation_key for c in self.checks]
        self.assertEqual(keys, ["faces", "nurbs_shape", "surface_samples",
                                "control_points"])

    def test_a_re_representation_is_NOT_a_violation(self) -> None:
        """🔴 THE MAIN FIX OF 20.08, AND ITS CONTROL.

        Live: a 4×4-degree-3×3 saddle was read back as a 1×1 with four
        points — a hypar is ruled, and the kernel collapsed the
        representation down to its exact minimum. The previous witness
        was judging by representation and was flagging correct work as
        wrong.

        What is checked here is that judging by degree and by point
        count in the emitted C# is GONE. This test must go red if
        anyone ever brings a degree equality back into the
        postconditions.
        """
        self.assertNotIn("read-back NURBS degree", self.cs)
        self.assertNotIn("read-back control point count", self.cs)
        # But the fact itself must remain, otherwise we cannot tell a
        # collapse apart from corruption.
        from kir.surface_emit import emit_surface
        _d, _c, _ch, rb = emit_surface(
            {"id": "S1", "surface": _validate(_value())[0],
             "category": "generic_model", "name": "оболочка"}, "2023", "st")
        self.assertIn("representation_changed", rb)
        self.assertIn("read_back_degree_u", rb)

    def test_the_geometric_law_projects_authored_samples_on_the_built_face(self) -> None:
        """The law reads the RESULT and does not mention the
        parameterization."""
        self.assertIn(".Project(__sp_S1[", self.cs)
        self.assertIn("__sp_S1 = null", self.cs)
        self.assertIn("не спроецировался", self.cs)

    def test_the_sample_grid_has_the_size_the_value_module_dictates(self) -> None:
        """The sample count is not a literal in the emitter, but a
        consequence of the number of spans."""
        from kir.surface import sample_surface
        from kir.surface_emit import emit_surface
        out, _ = _validate(_value())
        _d, create, _ch, _rb = emit_surface(
            {"id": "S1", "surface": out, "category": "generic_model",
             "name": "оболочка"}, "2023", "st")
        want = len(sample_surface(out))
        got = create.split("__sp_S1 = new XYZ[] {")[1].split("};")[0].count("P(")
        self.assertEqual(got, want)
        self.assertGreater(want, 4, "четырёх углов мало: между ними и уезжает форма")

    def test_no_sentinel_leaves_the_receipt_as_a_NUMBER(self) -> None:
        """🔴 PAID FOR LIVE ON 20.08: `worst_control_point_mm: -304.8`.

        A -1.0 sentinel in internal feet rode straight through `MM()`
        and printed out as a discrepancy of a third of a meter. What is
        dangerous is not the error but its PLAUSIBILITY: -304.8 reads as
        a measurement, and no one will argue with it.

        What is checked here is structural: every `MM(__x)` in the
        receipt sits inside a ternary with a sentinel check. The test
        will survive the addition of new quantities — it looks at the
        shape, not at a list of names.
        """
        from kir.surface_emit import emit_surface
        _d, _c, _ch, rb = emit_surface(
            {"id": "S1", "surface": _validate(_value())[0],
             "category": "generic_model", "name": "оболочка"}, "2023", "st")
        for line in rb.splitlines():
            if "MM(__" in line and "__rb[" in line:
                self.assertIn("< 0", line,
                              f"величина уезжает в квитанцию без охраны "
                              f"часового:\n  {line.strip()}")
        for name in ("read_back_degree_u", "read_back_control_points",
                     "worst_control_point_mm", "worst_sample_mm",
                     "representation_changed"):
            hit = [l for l in rb.splitlines() if f'"{name}"' in l]
            self.assertTrue(hit, f"поле {name} пропало из квитанции")
            self.assertIn("(object)null", hit[0],
                          f"{name} не умеет сказать «не измеряли»")

    def test_the_receipt_says_WHY_a_grid_was_not_compared(self) -> None:
        """null without a reason is half an answer. The second half is
        in words."""
        from kir.surface_emit import emit_surface
        _d, _c, _ch, rb = emit_surface(
            {"id": "S1", "surface": _validate(_value())[0],
             "category": "generic_model", "name": "оболочка"}, "2023", "st")
        self.assertIn("control_point_comparison_ru", rb)
        self.assertIn("Revit сменил представление", rb)
        self.assertIn("доказана ВЫБОРКОЙ", rb)
        self.assertIn("sample_comparison_ru", rb)
        self.assertIn("НЕ «расхождения нет»", rb)

    def test_the_tolerance_is_applied_in_internal_units(self) -> None:
        """The points have already gone out in feet for the build; a
        second array in mm would double the emission on a grid of
        thousands of points."""
        self.assertIn("U(0.01)", self.cs)
        self.assertNotIn("MM(__bp_", self.cs)

    def test_a_silent_zero_is_impossible(self) -> None:
        """'Not checked' and 'checked with no discrepancy' are DIFFERENT
        facts.

        `__bw` starts at -1: if the reverse read did not happen, the
        witness says "not checked", rather than "zero discrepancy".
        """
        self.assertIn("__bw_S1 = -1.0", self.cs)
        self.assertIn("не сверялись", self.cs)

    def test_every_verdict_names_the_geometry_axis(self) -> None:
        """The witness signs the grid it actually read."""
        for c in self.checks:
            self.assertIn("(geometry)", c.verdict_cs)


class TheOuterLoopIsCounterClockwise(unittest.TestCase):
    """🔴 THE AUTODESK REQUIREMENT, PAID FOR BY A LIVE REFUSAL ON 20.08.2026.

    `AddCoEdge`, verbatim (RevitAPI.xml, param `bCoEdgeIsReversed`, all six
    versions): "the loop orientations so defined must follow the convention that
    outer loops are oriented COUNTER-CLOCKWISE and inner loops are oriented
    clockwise". The first revision walked the outer contour CLOCKWISE, and
    live this produced our own typed refusal "BRepBuilder gave no result" —
    honest, but nameless: it named the effect and stayed silent about the
    cause.

    THE CHECK COMPUTES A PROPERTY RATHER THAN COMPARING THE WRITTEN FORM. A
    pin on the co-edge text would have been a ratchet naming a path (form
    25): if someone permuted the edges equivalently, the test would go red
    on a correct fix, while a change in naming convention would leave it
    silent on an incorrect one. Here the WALK in the uv-plane is
    reconstructed from the emission and the signed area is computed.
    """

    #: Corner points of each boundary curve in the NORMALIZED uv-frame
    #: (u along rows, v along columns). Taken from `surface.row_u`/`col_v`:
    #: `__eu*` is the row at a fixed u, `__ev*` is the column at a fixed v.
    _EDGE_UV = {
        "__eu0": ((0.0, 0.0), (0.0, 1.0)),
        "__ev1": ((0.0, 1.0), (1.0, 1.0)),
        "__eu1": ((1.0, 0.0), (1.0, 1.0)),
        "__ev0": ((0.0, 0.0), (1.0, 0.0)),
    }

    def _emitted(self) -> str:
        from kir.surface_emit import emit_surface
        with _registered():
            out, _ = _validate(_value())
            return emit_surface({"id": "S1", "surface": out,
                                 "category": "generic_model",
                                 "name": "оболочка"}, "2023", "st")[1]

    def _loop_uv(self) -> list:
        """The contour walk in uv follows the EMITTED code, not memory."""
        cs = self._emitted()
        # which edge is hidden behind each identifier
        alias = {}
        for m in re.finditer(
                r"BRepBuilderGeometryId (__[a-d]_S1) = __bb_S1\.AddEdge\("
                r"BRepBuilderEdgeGeometry\.Create\((__e[uv][01])_S1\)\)", cs):
            alias[m.group(1)] = m.group(2)
        self.assertEqual(len(alias), 4, f"ожидались четыре ребра, найдено {alias}")
        path = []
        for m in re.finditer(
                r"__bb_S1\.AddCoEdge\(__lp_S1, (__[a-d]_S1), (true|false)\)", cs):
            edge = alias[m.group(1)]
            a, b = self._EDGE_UV[edge]
            if m.group(2) == "true":
                a, b = b, a
            path.append((a, b))
        self.assertEqual(len(path), 4, "ожидались четыре co-edge")
        return path

    def test_the_loop_actually_closes(self) -> None:
        """Without this, the signed area would be computed over a broken polyline."""
        path = self._loop_uv()
        for i in range(4):
            self.assertEqual(path[i][1], path[(i + 1) % 4][0],
                             f"co-edge {i} не стыкуется со следующим: {path}")

    def test_the_outer_loop_is_counter_clockwise(self) -> None:
        path = self._loop_uv()
        pts = [a for a, _b in path]
        area2 = sum(pts[i][0] * pts[(i + 1) % 4][1]
                    - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4))
        self.assertGreater(
            area2, 0.0,
            "внешний контур обходится ПО ЧАСОВОЙ (удвоенная площадь "
            f"{area2}); Autodesk требует против часовой, и живьём это даёт "
            "«BRepBuilder не дал результата»")


class TheFinishOutcomeIsReadNotDiscarded(unittest.TestCase):
    """`Finish()` RETURNS `BRepBuilderOutcome` — Revit's direct answer.

    The first revision called it as a procedure and derived the outcome from
    `IsResultAvailable()`, that is, it asked the EFFECT while holding the
    CAUSE in hand. The refusal then could not name what Revit had actually
    said.
    """

    def _parts(self):
        from kir.surface_emit import emit_surface
        with _registered():
            out, _ = _validate(_value())
            return emit_surface({"id": "S1", "surface": out,
                                 "category": "generic_model",
                                 "name": "оболочка"}, "2023", "st")

    def test_the_outcome_is_captured(self) -> None:
        _decl, create, _checks, _rb = self._parts()
        self.assertIn("BRepBuilderOutcome", create,
                      "исход Finish() выброшен — отказ назовёт следствие "
                      "вместо причины")

    def test_the_outcome_reaches_the_refusal(self) -> None:
        _decl, create, _checks, _rb = self._parts()
        tail = create.split("IsResultAvailable", 1)[1]
        self.assertIn("__outcome_S1", tail,
                      "отказ не несёт исход, который уже прочитан рядом")

    def test_the_outcome_reaches_the_receipt(self) -> None:
        """A produced fact must have a READER."""
        _decl, _create, _checks, rb = self._parts()
        self.assertIn("finish_outcome", rb)

    def test_the_variable_lives_in_decl(self) -> None:
        """The receipt reads it — hence the declaration is outside `create` (class CS0103)."""
        decl, _create, _checks, _rb = self._parts()
        self.assertIn("__outcome_S1", decl)


if __name__ == "__main__":
    unittest.main()
