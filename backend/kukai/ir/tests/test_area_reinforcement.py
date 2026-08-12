"""wave/reinforcement (2026-08-10): create_area_reinforcement.

КАЖДЫЙ ТЕСТ ЗДЕСЬ — ОПРОВЕРГАЮЩИЙ, а не подтверждающий: он воспроизводит
конкретный способ соврать, который эта операция могла бы себе позволить, и
падает, если способ снова станет доступен. Список способов не выдуман — он
собран из замера API (:52412, 2021-2026, 10.08) и из уже оплаченных этим
домом дефектов:

  (a) `required=True` у угла было НЕИСПОЛНИМЫМ обещанием: ветка рода `deg` в
      authoring_validation выходила по `not in op` раньше, чем кто-либо
      спрашивал `p.required`, — программа без обязательного угла доезжала до
      эмиттера и падала KeyError'ом (KIR-P000 «внутренняя ошибка») вместо
      названного отказа. До этой волны все углы реестра были необязательными,
      поэтому дыра не наблюдалась — ровно «прибор на часть диапазона»;
  (b) ПРОПУЩЕННЫЙ КРЮК обязан значить «без крюков» (InvalidElementId —
      значение самого API), а не «единственный в пуле»: общее правило молча
      заанкерило бы арматуру, которую автор просил без анкеровки;
  (c) СВИДЕТЕЛЬ «СТЕРЖНИ ПОЛОЖЕНЫ» обязан быть УСЛОВНЫМ: Autodesk
      документирует пустой массив как ПРАВИЛЬНЫЙ ответ при выключенной
      `ReinforcementSettings.HostStructuralRebar`, поэтому безусловная
      проверка отвергала бы исправную работу (класс «приёмка ломалась на
      кириллице»);
  (d) НОСИТЕЛЬ-СТЕНА обязан отказываться ПОИМЁННО: `Create` на ней
      отработает, но плановый угол Revit спроецирует в вертикальную плоскость
      стены — молча не туда;
  (e) ПОСЛОЙНОГО API в эмиссии быть не должно вовсе: `GetNumberOfLines` /
      `GetLayerDirection` / `AreaReinforcementLayerType` не существуют на
      2021 (замер), то есть свидетель на них работал бы на пяти версиях из
      шести;
  (f) ДОПУСКА У ОПА НЕТ НИ ОДНОГО, и это обязано держаться конструкцией: в
      38 сохранённых разборах с переписью НОЛЬ элементов армирования, значит
      любое число здесь было бы выведено рассуждением.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_area_reinf_queue.jsonl"))

from kukai.ir import spec                                        # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

OP = "create_area_reinforcement"
BAR = {"by": "name", "value": "Ø12 A500C"}


def _prog(ops, intent="reinf-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _ar(oid="AR1", **kw):
    op = {"op": OP, "id": oid,
          "host": {"by": "element_id", "value": 8145901},
          "direction_deg": 0.0, "bar_type": BAR}
    op.update(kw)
    return op


def _emit(ops, ver="2026", isolation="atomic"):
    out = compile_program(_prog(ops), revit_version=ver, snapshot=SNAPSHOT,
                          bulk=True, isolation=isolation)
    return out


def _codes(out):
    return [d.code for d in out.diagnostics]


class RegistryContract(unittest.TestCase):
    """Что обязано стоять в реестре, а не в чьей-то памяти."""

    def test_the_op_declares_no_tolerance_at_all(self):
        # (f) Ноль допусков — ЗАМЕР, а не пропуск: измерять здесь нечего.
        # Первое же число, приехавшее сюда без замера, обязано уронить тест.
        self.assertEqual(spec.OPS[OP].tolerances, {})

    def test_direction_is_required_in_the_registry(self):
        p = next(p for p in spec.OPS[OP].params if p.name == "direction_deg")
        self.assertTrue(p.required)
        # Границ у периодической величины быть не должно: угол 725° законен.
        self.assertIsNone(p.min_val)
        self.assertIsNone(p.max_val)

    def test_host_accepts_an_existing_element_not_only_a_ref(self):
        # Главный сценарий раздела КР — «заармируй ЭТУ плиту»; требование ref
        # запретило бы его целиком.
        out = _emit([_ar()])
        self.assertTrue(out.ok, _codes(out))


class MissingAngleIsANamedRefusal(unittest.TestCase):
    """(a) Опровергающий тест дыры в роде `deg`."""

    def test_absent_direction_deg_is_a_typed_refusal_not_an_internal_error(self):
        op = _ar()
        del op["direction_deg"]
        out = _emit([op])
        self.assertFalse(out.ok)
        # НАЗВАННЫЙ отказ про ПОЛЕ, а не KIR-P000 «внутренняя ошибка».
        self.assertNotIn("KIR-P000", _codes(out))
        self.assertTrue(any(d.field_name == "direction_deg"
                            for d in out.diagnostics), _codes(out))

    def test_an_optional_angle_stays_optional(self):
        # Правка АДДИТИВНА: у `rotation_deg` (default=0.0) ничего не поехало.
        out = compile_program(
            _prog([{"op": "create_column", "id": "C1", "xy": [0, 0],
                    "level": {"by": "element_id", "value": 42},
                    "category": "structural"}]),
            revit_version="2026", snapshot=SNAPSHOT, bulk=True)
        self.assertTrue(out.ok, _codes(out))


class OmittedHookMeansNoHooks(unittest.TestCase):
    """(b) Пропуск крюка — значение API, а не приглашение выбрать за автора."""

    def test_pool_has_two_hooks_so_the_sole_entry_rule_would_have_refused(self):
        # Без этой строки тест ничего не доказывал бы: с пулом из одной записи
        # «без крюков» и «единственный в пуле» дали бы одинаковый видимый
        # исход, и подмена прошла бы незамеченной.
        self.assertGreaterEqual(len(SNAPSHOT["rebar_hook_types"]), 2)

    def test_omitted_hook_builds_and_emits_the_api_s_own_none_value(self):
        out = _emit([_ar()])
        self.assertTrue(out.ok, _codes(out))
        self.assertIn("__hkid_AR1 = ElementId.InvalidElementId;", out.csharp)
        for row in SNAPSHOT["rebar_hook_types"]:
            self.assertNotIn(f"__hkid_AR1 = new ElementId({row['id']})",
                             out.csharp)

    def test_a_named_hook_still_travels_to_the_call(self):
        out = _emit([_ar(hook_type={"by": "name", "value": "Крюк 90"})])
        self.assertTrue(out.ok, _codes(out))
        self.assertNotIn("__hkid_AR1 = ElementId.InvalidElementId;", out.csharp)
        self.assertIn("RebarHookType == null", out.csharp)


class TypeResolution(unittest.TestCase):
    """Опущенный тип идёт ДОКУМЕНТНОЙ веткой, а не «единственный в пуле»."""

    def test_pool_has_two_types_so_sole_entry_would_have_refused(self):
        self.assertGreaterEqual(len(SNAPSHOT["area_reinforcement_types"]), 2)

    def test_omitted_type_takes_the_document_default(self):
        out = _emit([_ar()])
        self.assertTrue(out.ok, _codes(out))
        self.assertIn(
            "doc.GetDefaultElementTypeId(ElementTypeGroup.AreaReinforcementType)",
            out.csharp)

    def test_a_named_type_replaces_the_document_default(self):
        out = _emit([_ar(type={"by": "name", "value":
                               "Армирование по области 2"})])
        self.assertTrue(out.ok, _codes(out))
        self.assertNotIn("GetDefaultElementTypeId", out.csharp)


class WitnessHonesty(unittest.TestCase):
    """(c) Свидетель читает РЕЗУЛЬТАТ и обязан уметь провалиться."""

    def setUp(self):
        self.cs = _emit([_ar()]).csharp

    def test_every_verdict_rereads_the_element_from_the_document(self):
        # Свидетель, поверивший возвращённому объекту, доказывал бы вызов, а
        # не результат.
        for marker in ("__rdh_AR1 = doc.GetElement(__el_AR1.Id)",
                       "__rdt_AR1 = doc.GetElement(__el_AR1.Id)",
                       "__rdb_AR1 = doc.GetElement(__el_AR1.Id)",
                       "__rdr_AR1 = doc.GetElement(__el_AR1.Id)"):
            self.assertIn(marker, self.cs)

    def test_bars_laid_is_conditional_on_the_document_setting(self):
        # БЕЗУСЛОВНАЯ проверка отвергала бы исправную работу в каждом
        # документе с выключенной настройкой. Условие обязано читаться ИЗ
        # ДОКУМЕНТА и стоять в том же вердикте.
        self.assertIn("ReinforcementSettings.GetReinforcementSettings(doc)",
                      self.cs)
        head, _sep, tail = self.cs.partition("GetRebarInSystemIds().Count == 0")
        self.assertTrue(_sep, "проверки на ноль стержней нет вовсе")
        guard = head[head.rfind("{ var __rdb_AR1"):]
        self.assertIn("HostStructuralRebar", guard)

    def test_the_setting_and_the_bar_count_always_ride_the_receipt(self):
        # Ноль стержней не должен быть молчаливым: автор обязан увидеть И
        # число, И причину.
        self.assertIn('__rb["host_structural_rebar"]', self.cs)
        self.assertIn('__rb["bar_count"]', self.cs)
        self.assertIn('__rb["direction"]', self.cs)

    def test_no_witness_carries_a_tolerance(self):
        from kukai.ir import struct_emit
        op = {"op": OP, "id": "AR1", "__region__": None,
              "host": {"by": "element_id", "value": 8145901},
              "direction_deg": 0.0,
              "type": {"__grounded__": {"id": None, "name": None,
                                        "via": "doc_default",
                                        "in_emit": "__doc_default__"}},
              "bar_type": {"__grounded__": {"id": 1902, "name": "Ø12 A500C",
                                            "via": "name"}}}
        _decl, _create, checks, _rb = struct_emit.emit_area_reinforcement(
            op, "2026", "stamp")
        self.assertEqual(len(checks), 4)
        for chk in checks:
            self.assertIsNone(chk.tol, chk.obligation_key)

    def test_the_layered_api_never_reaches_the_emission(self):
        # (e) Оно не существует на 2021 — свидетель на нём был бы прибором на
        # часть диапазона.
        for absent in ("GetNumberOfLines", "GetLayerDirection",
                       "AreaReinforcementLayerType"):
            self.assertNotIn(absent, self.cs)


class HostGuards(unittest.TestCase):
    """(d) Молчаливо-неверный носитель останавливается ДО вызова."""

    def setUp(self):
        self.cs = _emit([_ar()]).csharp

    def test_a_vertical_host_is_refused_by_name_before_the_call(self):
        self.assertIn("if (!(__hh_AR1 is Floor))", self.cs)
        i_guard = self.cs.index("if (!(__hh_AR1 is Floor))")
        i_call = self.cs.index("AreaReinforcement.Create(")
        self.assertLess(i_guard, i_call)

    def test_the_api_s_own_preflight_is_asked_before_the_call(self):
        self.assertIn("RebarHostData.IsValidHost(__hh_AR1)", self.cs)
        i_guard = self.cs.index("RebarHostData.IsValidHost(__hh_AR1)")
        i_call = self.cs.index("AreaReinforcement.Create(")
        self.assertLess(i_guard, i_call)

    def test_the_create_call_is_wrapped_in_a_typed_refusal(self):
        self.assertIn("AreaReinforcement.Create: ", self.cs)
        self.assertIn("catch (Exception __ex_AR1)", self.cs)


class DirectionIsCompiledNotComputedLive(unittest.TestCase):
    """Вся тригонометрия на компиляции — закон CONTOUR, здесь тоже."""

    def test_the_emitted_vector_is_two_literals(self):
        cs = _emit([_ar(direction_deg=90.0)]).csharp
        self.assertIn("XYZ __dir_AR1 = new XYZ(", cs)
        self.assertNotIn("Math.Cos", cs)
        self.assertNotIn("Math.Sin", cs)

    def test_an_angle_outside_0_360_is_a_legal_program(self):
        for ang in (-30.0, 725.0):
            out = _emit([_ar(direction_deg=ang)])
            self.assertTrue(out.ok, (ang, _codes(out)))

    def test_the_direction_is_a_unit_vector_by_construction(self):
        # «majorDirection has zero length» — документированное исключение
        # Autodesk; здесь оно недостижимо, и это обязано держаться замером,
        # а не верой.
        import re
        for ang in (0.0, 45.0, 90.0, 179.999, -720.0):
            cs = _emit([_ar(direction_deg=ang)]).csharp
            m = re.search(r"XYZ __dir_AR1 = new XYZ\(([-\d.eE+]+), "
                          r"([-\d.eE+]+), 0\.0\);", cs)
            self.assertIsNotNone(m, ang)
            x, y = float(m.group(1)), float(m.group(2))
            self.assertAlmostEqual(x * x + y * y, 1.0, places=6)


class RefWorksToo(unittest.TestCase):
    """Плита этой же программы — законный носитель наравне со стоящей."""

    def test_ref_to_a_floor_built_in_the_same_program(self):
        ops = [{"op": "create_floor", "id": "SL1",
                "outline": [[0, 0], [9000, 0], [9000, 6000], [0, 6000]],
                "level": {"by": "element_id", "value": 42},
                "structural": True},
               _ar(host={"by": "ref", "value": "SL1"})]
        out = _emit(ops)
        self.assertTrue(out.ok, _codes(out))
        self.assertIn("__hh_AR1 = __el_SL1;", out.csharp)


class AllSixVersionsEmitTheSameShape(unittest.TestCase):
    """Оси версий у этой операции НЕТ, и это замер, а не надежда."""

    def test_no_version_branch_in_the_op_body(self):
        bodies = {}
        for ver in spec.REVIT_VERSIONS:
            out = _emit([_ar()], ver=ver)
            self.assertTrue(out.ok, (ver, _codes(out)))
            cs = out.csharp
            start = cs.index("// create_area_reinforcement")
            bodies[ver] = cs[start:]
        # Единственное, чем версии вообще расходятся, — литерал ElementId,
        # и его печатает общий `_eid`; тело носителя по element_id поэтому
        # сравнивается по инварианту, а не побайтно.
        for ver, body in bodies.items():
            self.assertIn("AreaReinforcement.Create(doc, __hh_AR1, __dir_AR1",
                          body, ver)


if __name__ == "__main__":
    unittest.main()
