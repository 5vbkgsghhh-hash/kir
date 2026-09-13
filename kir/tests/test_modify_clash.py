"""CLASH fix (07.28, operator's strategy: an early honest release):
move_elements / change_type — modify-family ops opening the clash-fix
product.

A refuting test BEFORE (not a permanent one, documented here honestly):
before registration in the registry, ``compile_program({"ops": [{"op":
"move_elements", ...}]})``/``change_type`` refused with
``PARSE_UNKNOWN_OP`` (KIR-P002) — the op was not in ``spec.OPS``. Measured
personally before the fix (see the wave's report); the test below checks
the AFTER state, and this fact is what it was BEFORE.

move_elements: ElementTransformUtils.MoveElements(doc,
ICollection<ElementId>, XYZ) — the signature is identical across all six
versions (confirmed by reflection over RevitAPI.dll). targets follows the
same id-pinned/ref-only pattern as host for a door/window and refs for
create_dimension: it reuses the kind "refs_w" (28.07 SRC PIN, a live
collision with schema_gen.py — a new kind broke the test-bench pilot with
`AssertionError: unknown param kind`; schema_gen.py is foreign, dirty, and
must not be edited), with SEPARATE bounds by op name (1..500, duplicates
allowed — unlike 2..16 with duplicates forbidden for create_dimension).

change_type: Element.ChangeTypeId(ElementId) — the return value is
confirmed by the ASSEMBLY's XML documentation (RevitAPI.xml, not the
wiki): InvalidElementId is the ORDINARY success case (the type changed in
place), a genuine ElementId is the rare case of a new element.
Incompatibility is a thrown exception, not a return value.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir.compiler import compile_program  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


def _prog(ops, **env):
    p = {"ir_version": "1.0", "intent": "clash-test", "ops": ops}
    p.update(env)
    return p


HOST_ID = 8145901   # opaque — never snapshot-resolved (target_w)


def _move(oid="M1", **kw):
    op = {"op": "move_elements", "id": oid,
          "targets": [{"by": "element_id", "value": HOST_ID}],
          "delta_mm": [1000.0, 0.0, 0.0]}
    op.update(kw)
    return op


def _wall(oid="W1", **kw):
    op = {"op": "create_wall", "id": oid, "p0_mm": [0, 0], "p1_mm": [6000, 0],
          "level": {"by": "element_id", "value": 42}}
    op.update(kw)
    return op


def _pipe(oid="P1", **kw):
    op = {"op": "create_pipe", "id": oid, "p0_mm": [0, 0, 2700],
          "p1_mm": [3000, 0, 2900], "level": {"by": "element_id", "value": 42},
          "diameter_mm": 50}
    op.update(kw)
    return op


class MoveElementsValidation(unittest.TestCase):
    def test_empty_targets_refused(self):
        out = compile_program(_prog([_move(targets=[])]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_over_500_targets_refused(self):
        many = [{"by": "element_id", "value": i} for i in range(1, 502)]
        out = compile_program(_prog([_move(targets=many)]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_500_targets_accepted(self):
        many = [{"by": "element_id", "value": i} for i in range(1, 501)]
        out = compile_program(_prog([_move(targets=many)]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])

    def test_duplicate_targets_are_allowed(self):
        """Unlike create_dimension.refs (a duplicate ref is a zero-size-
        dimension hazard), a duplicate move_elements target is harmless —
        Revit's ElementId collection de-duplicates."""
        out = compile_program(_prog([_move(
            targets=[{"by": "element_id", "value": HOST_ID},
                     {"by": "element_id", "value": HOST_ID}])]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])

    def test_delta_zero_refused(self):
        out = compile_program(_prog([_move(delta_mm=[0.0, 0.0, 0.0])]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])
        self.assertIn("нулевой перенос",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_delta_component_over_100000_refused(self):
        out = compile_program(_prog([_move(delta_mm=[0.0, 0.0, 100_001.0])]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_delta_component_exactly_100000_accepted(self):
        out = compile_program(_prog([_move(delta_mm=[0.0, 0.0, 100_000.0])]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])

    def test_target_by_name_refused_same_as_any_target_w(self):
        out = compile_program(_prog([_move(
            targets=[{"by": "name", "value": "x"}])]))
        self.assertFalse(out.ok)


class TheRefusalNamesWHATIsWrongNotJustTheShape(unittest.TestCase):
    """🔴 LIVE MEASUREMENT OF 22.08.2026: TWO ATTEMPTS ON ONE QUOTE.

    The refusal printed `expected: 1..500 selectors {by:
    element_id|ref, value: ...}` and next to it `got: [{'by':
    'element_id', 'value': '294076'}]`. In FORM they match character for
    character; what decides is the TYPE of the value. The second attempt
    sent back exactly what the refusal had named, and was rejected again.

    The language's invariant promises "it WILL REFUSE and NAME the move,"
    and the receipt promises "close the gap in ONE move." The language's
    main user is an LLM, which has nothing besides the refusal's text: an
    unspoken reason costs exactly one extra round-trip of live Revit.
    """

    def _msg(self, targets) -> str:
        out = compile_program(_prog([_move(targets=targets)]))
        self.assertFalse(out.ok)
        return " ".join(d.message_ru for d in out.diagnostics)

    def test_a_numeric_STRING_id_is_told_it_must_be_an_integer(self):
        msg = self._msg([{"by": "element_id", "value": str(HOST_ID)}])
        self.assertIn("ЦЕЛОЕ", msg)
        self.assertIn("str", msg)
        self.assertIn(f"сними кавычки: {HOST_ID}", msg,
                      "следующий ход обязан быть ОДИН, а не «догадайся сам»")

    def test_the_expected_line_alone_distinguishes_the_two_kinds(self):
        """A single line of `expected` must be enough to tell what is fit."""
        out = compile_program(_prog([_move(
            targets=[{"by": "element_id", "value": str(HOST_ID)}])]))
        expected = " ".join(str(d.expected) for d in out.diagnostics)
        self.assertIn("ЦЕЛОЕ", expected)
        self.assertIn("ref", expected)

    def test_a_wrong_BY_is_named_by_its_own_reason(self):
        msg = self._msg([{"by": "name", "value": "x"}])
        self.assertIn("element_id", msg)
        self.assertIn("ref", msg)

    def test_a_missing_key_is_named_as_missing_not_as_shape(self):
        msg = self._msg([{"by": "element_id"}])
        self.assertIn("нет ключей", msg)
        self.assertIn("value", msg)

    def test_an_out_of_range_id_says_the_range_not_the_shape(self):
        msg = self._msg([{"by": "element_id", "value": 0}])
        self.assertIn("вне 1..", msg)

    def test_the_count_bound_is_named_when_the_LIST_is_wrong(self):
        msg = self._msg([])
        self.assertIn("от 1 до 500", msg)

    def test_only_the_FIRST_FOUR_bad_selectors_are_printed_and_the_rest_counted(self):
        """A refusal must stay readable: 500 reasons is not diagnostics."""
        msg = self._msg([{"by": "element_id", "value": "1"} for _ in range(9)])
        self.assertIn("ещё 5 таких же", msg)

    def test_a_GOOD_selector_still_compiles(self):
        """Control: the reason must not turn red on a fit input."""
        out = compile_program(_prog([_move()]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])


class CreateDimensionRefsUnaffected(unittest.TestCase):
    """Regression pin: reusing refs_w for move_elements must not move
    create_dimension's ORIGINAL 2..16/no-duplicates law by a single byte."""

    def test_refs_still_bounded_2_to_16(self):
        out = compile_program(_prog([
            _wall(),
            {"op": "create_dimension", "id": "D1",
             "in_view": {"by": "element_id", "value": 900},
             "refs": [{"by": "element_id", "value": 111}],
             "line_at": [3000, 500]},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_refs_still_rejects_duplicates(self):
        out = compile_program(_prog([
            _wall(),
            {"op": "create_dimension", "id": "D1",
             "in_view": {"by": "element_id", "value": 900},
             "refs": [{"by": "ref", "value": "W1"}, {"by": "ref", "value": "W1"}],
             "line_at": [3000, 500]},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])


class MoveElementsEmission(unittest.TestCase):
    def test_emits_move_elements_call_and_delta(self):
        out = compile_program(_prog([_move(delta_mm=[1000.0, 0.0, 500.0])]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("ElementTransformUtils.MoveElements(", cs)
        self.assertIn("U(1000.0)", cs)
        self.assertIn("U(0.0)", cs)
        self.assertIn("U(500.0)", cs)

    def test_pinned_guard_present(self):
        cs = compile_program(_prog([_move()])).csharp
        self.assertIn(".Pinned", cs)
        self.assertIn("закреплён (Pinned)", cs)

    def test_stale_target_guard_present(self):
        cs = compile_program(_prog([_move()])).csharp
        self.assertIn("не найден (модель изменилась после grounding)", cs)

    def test_ref_target_resolves_to_same_program_element(self):
        out = compile_program(_prog([
            _wall(), _move(targets=[{"by": "ref", "value": "W1"}])]),
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("__el_W1", out.csharp)

    def test_connector_manager_paths_present(self):
        """MEPCurve.ConnectorManager / FamilyInstance.MEPModel.
        ConnectorManager — confirmed identical on all six versions by
        reflection over RevitAPI.dll."""
        cs = compile_program(_prog([_move()])).csharp
        self.assertIn("as MEPCurve", cs)
        self.assertIn("as FamilyInstance", cs)
        self.assertIn(".ConnectorManager", cs)
        self.assertIn(".MEPModel", cs)
        self.assertIn(".IsConnected", cs)

    def test_slope_witness_present(self):
        cs = compile_program(_prog([_move()])).csharp
        self.assertIn("GetEndPoint(0)", cs)
        self.assertIn("GetEndPoint(1)", cs)
        self.assertIn("наклон изменился", cs)

    def test_location_witness_compares_against_snapshot_plus_delta(self):
        cs = compile_program(_prog([_move(delta_mm=[250.0, 0.0, 0.0])])).csharp
        self.assertIn("MM(__mtbp_M1.X) + 250.0", cs)

    def test_per_op_isolation_compiles_offline(self):
        """Same shape, per_op isolation — the scope-contract regression this
        wave hit live (pattern-matched is-vars invisible to the corpus
        scope-leak scanner; fixed by switching to `as`-casts)."""
        out = compile_program(_prog([_move()]), isolation="per_op")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("throw __OpRefuse(", out.csharp)


class ChangeTypeValidation(unittest.TestCase):
    def test_type_by_ref_refused(self):
        out = compile_program(_prog([
            {"op": "change_type", "id": "C1",
             "target": {"by": "element_id", "value": 111},
             "type": {"by": "ref", "value": "T1"}}]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])
        self.assertIn("только element_id",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_type_by_name_refused(self):
        out = compile_program(_prog([
            {"op": "change_type", "id": "C1",
             "target": {"by": "element_id", "value": 111},
             "type": {"by": "name", "value": "Стена 200"}}]))
        self.assertFalse(out.ok)

    def test_target_may_be_ref_unlike_type(self):
        out = compile_program(_prog([
            _wall(),
            {"op": "change_type", "id": "C1",
             "target": {"by": "ref", "value": "W1"},
             "type": {"by": "element_id", "value": 5001}},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("__el_W1", out.csharp)

    def test_element_id_target_and_type_accepted(self):
        out = compile_program(_prog([
            {"op": "change_type", "id": "C1",
             "target": {"by": "element_id", "value": 111},
             "type": {"by": "element_id", "value": 222}}]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])


class ChangeTypeEmission(unittest.TestCase):
    def _cs(self):
        return compile_program(_prog([
            {"op": "change_type", "id": "C1",
             "target": {"by": "element_id", "value": 111},
             "type": {"by": "element_id", "value": 222}}])).csharp

    def test_emits_change_type_id_call(self):
        cs = self._cs()
        self.assertIn(".ChangeTypeId(", cs)

    def test_invalid_element_id_is_not_treated_as_failure(self):
        """The API's OWN doc comments (RevitAPI.xml): InvalidElementId is
        the ORDINARY success path (type changed in place); a real ElementId
        means Revit replaced the element. Naive "Invalid = failure" would
        misread the common case as a refusal — must not appear."""
        cs = self._cs()
        self.assertIn("!= ElementId.InvalidElementId", cs)
        # The comparison GATES which element gets re-read; it is not itself
        # a refusal condition (no refuse_stmt keyed on InvalidElementId).
        self.assertNotIn(
            'if (__chid_C1 == ElementId.InvalidElementId) { __t.RollBack()',
            cs)

    def test_incompatible_type_is_a_typed_refusal_via_exception(self):
        cs = self._cs()
        self.assertIn("catch (Exception __ex_C1)", cs)
        self.assertIn("несовместимый тип (ChangeTypeId)", cs)

    def test_regenerate_before_witness(self):
        cs = self._cs()
        i_change = cs.index("ChangeTypeId(")
        i_regen = cs.index("doc.Regenerate();", i_change)
        i_witness = cs.index("GetTypeId()", i_regen)
        self.assertLess(i_change, i_regen)
        self.assertLess(i_regen, i_witness)

    def test_type_held_witness_present(self):
        from kir.emit_core import type_assignment_witness
        witness = type_assignment_witness("__el_C1", "__ty_C1", "C1")
        self.assertEqual(witness.stage, "operation")
        self.assertEqual(witness.obligation_key, "type_assignment")
        cs = self._cs()
        self.assertIn("__assignedType_C1 = __el_C1.GetTypeId()", cs)
        self.assertIn("!__assignedType_C1.Equals(__requestedType_C1)", cs)
        self.assertIn("ElementId.InvalidElementId", witness.verdict_cs)
        self.assertIn("__post.Add", witness.verdict_cs)
        out = compile_program(_prog([
            _wall("W1"),
            {"op": "change_type", "id": "C1", "target": {"by": "ref", "value": "W1"},
             "type": {"by": "element_id", "value": 222}},
            {"op": "change_type", "id": "C2", "target": {"by": "ref", "value": "W1"},
             "type": {"by": "element_id", "value": 333}}]))
        self.assertTrue(out.ok, out.diagnostics)
        self.assertLess(out.csharp.index("// operation C1"), out.csharp.index("// change_type C2"))
        self.assertIn("// operation C2", out.csharp)
        self.assertNotIn("// post C1", out.csharp)

    def test_per_op_isolation_compiles_offline(self):
        out = compile_program(_prog([
            {"op": "change_type", "id": "C1",
             "target": {"by": "element_id", "value": 111},
             "type": {"by": "element_id", "value": 222}}]),
            isolation="per_op")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("throw __OpRefuse(", out.csharp)


class MoveAndChangeTypeCombined(unittest.TestCase):
    """The gate's own program shape, offline: wall+pipe moved together via
    ref targets (plus one element_id target), then the wall's type changed
    by ref — the realistic clash-fix scenario."""

    def test_wall_pipe_move_then_change_type(self):
        out = compile_program(_prog([
            _wall(oid="MW"), _pipe(oid="MP", level={"by": "element_id", "value": 42}),
            {"op": "move_elements", "id": "ME1",
             "targets": [{"by": "ref", "value": "MW"},
                         {"by": "ref", "value": "MP"},
                         {"by": "element_id", "value": HOST_ID}],
             "delta_mm": [1000.0, 0.0, 500.0]},
            {"op": "change_type", "id": "CT1",
             "target": {"by": "ref", "value": "MW"},
             "type": {"by": "element_id", "value": 5001}},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("ElementTransformUtils.MoveElements(", cs)
        self.assertIn(".ChangeTypeId(", cs)


if __name__ == "__main__":
    unittest.main()


class ПереносНижеДопускаСвидетеляНЕДОКАЗУЕМ(unittest.TestCase):
    """🔴 A BLIND STRIP, NAMED BY THE WAVE OF 22.08.2026 AND CLOSED THE
    SAME DAY.

    Validation was rejecting an EXACT zero, while the `location`
    obligation checks the move against a tolerance of `location_mm = 1.0`
    mm. A strip lay between them: a move whose all three components are
    no more than a millimeter in absolute value counts as FULFILLED, even
    if Revit silently did nothing. The op would commit green while the
    obligation was satisfied — the witness was signing something it could
    not tell apart.

    This is NOT a threshold used in place of equality (for direction, a
    threshold would be a lie — see `dir_xyz`): here the quantity is in
    MILLIMETERS, and the number is taken from THE SAME OP'S TOLERANCE, not
    written in alongside it.
    """

    def _msg(self, delta) -> str:
        out = compile_program(_prog([_move(delta_mm=delta)]))
        self.assertFalse(out.ok, delta)
        return " ".join(d.message_ru for d in out.diagnostics)

    def test_sub_tolerance_move_is_refused_as_unprovable(self):
        msg = self._msg([0.5, 0.0, 0.0])
        self.assertIn("НЕДОКАЗУЕМ", msg)
        self.assertIn("1 мм", msg)

    def test_all_three_components_at_the_tolerance_are_refused(self):
        self.assertIn("НЕДОКАЗУЕМ", self._msg([1.0, 1.0, 1.0]))

    def test_exact_zero_keeps_its_OWN_words(self):
        """Zero and "below tolerance" are different troubles, and they get different words."""
        msg = self._msg([0.0, 0.0, 0.0])
        self.assertIn("нулевой перенос", msg)
        self.assertNotIn("НЕДОКАЗУЕМ", msg)

    def test_just_above_the_tolerance_compiles(self):
        """Control: the rule does not eat a legitimate small move."""
        out = compile_program(_prog([_move(delta_mm=[1.5, 0.0, 0.0])]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])

    def test_one_big_component_is_enough(self):
        """A threshold on EACH component, not on the vector's length."""
        out = compile_program(_prog([_move(delta_mm=[0.0, 0.0, 300.0])]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])

    def test_the_threshold_has_ONE_carrier(self):
        """The validation threshold must be the OP'S OWN TOLERANCE, not a copy of the number."""
        from kir.authoring_validation import _move_witness_tol
        from kir.spec import OPS
        self.assertEqual(_move_witness_tol(),
                         OPS["move_elements"].tolerances["location_mm"])
