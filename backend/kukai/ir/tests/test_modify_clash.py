"""CLASH-починка (28.07, стратегия оператора: ранний честный релиз):
move_elements / change_type — modify-family ops opening the clash-fix
product.

Опровергающий тест ДО (не постоянный, задокументирован здесь честно): до
регистрации в реестре ``compile_program({"ops": [{"op": "move_elements",
...}]})``/``change_type`` отказывали ``PARSE_UNKNOWN_OP`` (KIR-P002) — оп не
в ``spec.OPS``.  Замерено лично перед правкой (см. отчёт волны); тест ниже
проверяет ПОСЛЕ, а этот факт — то, что было ДО.

move_elements: ElementTransformUtils.MoveElements(doc, ICollection<
ElementId>, XYZ) — сигнатура идентична на всех шести версиях (подтверждено
рефлексией над RevitAPI.dll). targets — тот же id-pinned/ref-only узор, что
host у двери/окна и refs у create_dimension: переиспользует kind "refs_w"
(28.07 SRC PIN, живое столкновение со schema_gen.py — новый kind ронял
пилот стенда `AssertionError: unknown param kind`; schema_gen.py — чужой
грязный, править нельзя), с ОТДЕЛЬНЫМИ границами по имени опа (1..500,
дубликаты разрешены — не 2..16 с запретом дублей, как у create_dimension).

change_type: Element.ChangeTypeId(ElementId) — возврат подтверждён
XML-документацией СБОРКИ (RevitAPI.xml, не вики): InvalidElementId — ОБЫЧНЫЙ
успех (тип сменился на месте), настоящий ElementId — редкий случай нового
элемента. Несовместимость — брошенное исключение, не возврат.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


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
        cs = self._cs()
        self.assertIn("тип не удержался после ChangeTypeId (re-read)", cs)

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
