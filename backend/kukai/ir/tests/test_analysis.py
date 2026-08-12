"""Волна нагрузок и пути эвакуации: то, что нельзя сломать молча.

Каждый класс здесь стоит против КОНКРЕТНОГО тихо-неверного исхода, а не
против «вдруг сломается»:

* `LoadsExistOnlyWhereTheApiHasThem` — ось версий. Свободная нагрузка есть на
  2021-2023 и убрана Autodesk из API в 2024; если однажды кто-то «починит»
  отказ, передав `InvalidElementId`, тест обязан упасть, потому что поведение
  этого аргумента не измерено ни разу.
* `WitnessReadsTheResult` — свидетель читает СВОЙСТВО ПОСТРОЕННОГО ЭЛЕМЕНТА.
  Проверка «сеттер отработал» — повторяющийся дефект этого пакета, и он
  проходит любой обычный тест.
* `OrientationIsPinned` — без пришпиленной системы отсчёта три числа вектора
  силы не значат ничего определённого, и подмену системы свидетель силы не
  заметил бы вовсе.
* `LoadCaseIsMandatory` — нагрузка в случае по умолчанию снаружи неотличима
  от выполненной работы.
* `BoundaryConditionsAreDeliberatelyAbsent` — решение, а не забывчивость;
  ровно тот же замок, что у `create_wire` в волне ЭОМ.
* `ForceToleranceIsDerived` — число допуска обязано СЛЕДОВАТЬ из объявленной
  границы, а не быть набранным.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_analysis_queue.jsonl"))

from kukai.ir import spec                                      # noqa: E402
from kukai.ir.analysis_emit import (                           # noqa: E402
    ANALYSIS_ZERO_LOAD, _FREE_LOAD_LAST_VER, _plane_normal,
)
from kukai.ir.compiler import compile_program                  # noqa: E402
from kukai.ir.diag import PARSE_MISSING_FIELD                 # noqa: E402
from kukai.ir.reverse_contract import REVERSE_CONTRACTS, ReverseMode  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT            # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
CASE_NAME = {"by": "name", "value": "ДЛ1 Собственный вес"}
CASE_ID = {"by": "element_id", "value": 1500}

POINT_LOAD = {"op": "create_point_load", "id": "PL1", "xyz": [1000, 2000, 3000],
              "fz_n": -10000.0, "mx_nm": 250.0, "load_case": CASE_NAME}
LINE_LOAD = {"op": "create_line_load", "id": "LL1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "fz_n_per_m": -5000.0,
             "load_case": CASE_ID}
AREA_LOAD = {"op": "create_area_load", "id": "AL1",
             "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "elev_mm": 3000, "fz_n_per_m2": -3000.0, "load_case": CASE_ID}
PATH = {"op": "create_path_of_travel", "id": "PT1",
        "in_view": {"by": "element_id", "value": 900},
        "p0_mm": [0, 0], "p1_mm": [12000, 5000]}

LOAD_OPS = (POINT_LOAD, LINE_LOAD, AREA_LOAD)


def _compile(op: dict, ver: str = "2023", **extra):
    program = {"ir_version": "1.0", "ops": [op]}
    program.update(extra)
    return compile_program(program, revit_version=ver, snapshot=GROUND_SNAPSHOT)


def _codes(out) -> set:
    return {d.code for d in out.diagnostics}


class LoadsExistOnlyWhereTheApiHasThem(unittest.TestCase):
    """Замер, а не соглашение: перегрузки без носителя дают CS1503/CS1501 на
    2024-2026 против эталонных сборок, поэтому там отказ — ПРАВИЛЬНЫЙ ответ."""

    def test_free_loads_emit_up_to_2023_and_refuse_after(self) -> None:
        for op in LOAD_OPS:
            for ver in VERSIONS:
                with self.subTest(op=op["op"], ver=ver):
                    out = _compile(op, ver)
                    if ver <= _FREE_LOAD_LAST_VER:
                        self.assertTrue(out.ok, _codes(out))
                    else:
                        self.assertFalse(out.ok)
                        self.assertEqual(_codes(out), {"KIR-E003"})

    def test_the_refusal_names_the_measurement_and_the_reason(self) -> None:
        """Отказ без причины отправляет ремонт не туда. Здесь причина обязана
        назвать И версию, И то, почему InvalidElementId не годится."""
        out = _compile(POINT_LOAD, "2026")
        text = " ".join(d.message_ru for d in out.diagnostics)
        for probe in ("2026", "2024", "hostElemId", "InvalidElementId",
                      "аналитического"):
            self.assertIn(probe, text, probe)

    def test_path_of_travel_is_the_one_op_alive_on_all_six(self) -> None:
        for ver in VERSIONS:
            with self.subTest(ver=ver):
                self.assertTrue(_compile(PATH, ver).ok)


class WitnessReadsTheResult(unittest.TestCase):
    """Постусловие, подтверждающее, что вызов состоялся, проходит любой тест и
    не доказывает ничего. Здесь проверяется, что в блоке post стоит ЧТЕНИЕ
    свойства построенного элемента."""

    #: (оп, программа, строки, которые обязаны стоять в блоке post).
    EXPECTED = (
        ("create_point_load", POINT_LOAD, (
            "__el_PL1.Point", "__el_PL1.ForceVector", "__el_PL1.MomentVector",
            "__el_PL1.OrientTo", "__el_PL1.LoadCaseId", "__el_PL1.GetTypeId()")),
        ("create_line_load", LINE_LOAD, (
            "__el_LL1.StartPoint", "__el_LL1.EndPoint",
            "__el_LL1.ForceVector1", "__el_LL1.IsUniform",
            "__el_LL1.OrientTo", "__el_LL1.LoadCaseId")),
        ("create_area_load", AREA_LOAD, (
            "__el_AL1.GetLoops()", "__el_AL1.ForceVector1",
            "__el_AL1.OrientTo", "__el_AL1.LoadCaseId")),
        ("create_path_of_travel", PATH, (
            "__el_PT1.PathStart", "__el_PT1.PathEnd",
            "__el_PT1.GetCurves()", "__el_PT1.OwnerViewId")),
    )

    def _post_block(self, op: dict) -> str:
        out = _compile(op, "2023")
        self.assertTrue(out.ok, _codes(out))
        marker = f"// post {op['id']}"
        start = out.csharp.index(marker)
        end = out.csharp.index("// witness", start)
        return out.csharp[start:end]

    def test_every_obligation_reads_a_property_of_the_built_element(self) -> None:
        for name, op, probes in self.EXPECTED:
            block = self._post_block(op)
            for probe in probes:
                with self.subTest(op=name, probe=probe):
                    self.assertIn(probe, block)

    def test_geometry_is_compared_against_revits_own_tolerance(self) -> None:
        """Ни одного набранного числа: сравнение идёт с
        `doc.Application.VertexTolerance` — приём `create_dimension`."""
        for _name, op, _probes in self.EXPECTED:
            with self.subTest(op=op["op"]):
                self.assertIn("doc.Application.VertexTolerance",
                              self._post_block(op))

    def test_the_route_length_is_an_inequality_not_an_equality(self) -> None:
        """Форму маршрута считает Revit. Утверждать можно только то, что от
        его расчёта не зависит: маршрут непуст и не короче прямой."""
        block = self._post_block(PATH)
        self.assertIn("__cvs_PT1.Count < 1", block)
        # Прямая между (0,0) и (12000,5000) — ровно 13000 мм, и это ЕДИНСТВЕННОЕ
        # число, которое утверждение о маршруте вправе назвать: оно посчитано
        # из заказанных точек, а не из вывода Revit.
        self.assertIn("__len_PT1 < U(13000.0)", block)
        self.assertNotIn("__len_PT1 ==", block)

    def test_path_z_is_excluded_by_construction_not_by_prose(self) -> None:
        """API отбрасывает Z заданных точек («set to the view's level
        elevation»). Факт вписан в РОД параметра, а не в комментарий."""
        kinds = {p.name: p.kind for p in spec.OPS["create_path_of_travel"].params}
        self.assertEqual(kinds["p0_mm"], "pt_xy")
        self.assertEqual(kinds["p1_mm"], "pt_xy")


class OrientationIsPinned(unittest.TestCase):
    """`ForceVector` документирован как «oriented according to OrientTo
    setting». Без пришпиленной системы отсчёта свидетель силы читал бы ту же
    тройку чисел в другой системе и ничего бы не заметил."""

    def test_orient_is_set_before_the_vector_is_written(self) -> None:
        for op, prop in ((POINT_LOAD, "ForceVector"),
                         (LINE_LOAD, "ForceVector1"),
                         (AREA_LOAD, "ForceVector1")):
            with self.subTest(op=op["op"]):
                out = _compile(op, "2023")
                cs = out.csharp
                orient = cs.index(f"__el_{op['id']}.OrientTo = ")
                write = cs.index(f"__el_{op['id']}.{prop} = ")
                self.assertLess(orient, write,
                                "система отсчёта обязана быть пришпилена ДО "
                                "записи вектора, иначе проверка ловила бы "
                                "собственный пересчёт Revit")

    def test_an_unpermitted_orientation_is_a_typed_runtime_refusal(self) -> None:
        out = _compile(POINT_LOAD, "2023")
        self.assertIn("IsOrientToPermitted", out.csharp)


class LoadCaseIsMandatory(unittest.TestCase):
    """Нагрузка, попавшая в случай по умолчанию, стоит и выглядит правильно, а
    в сочетаниях участвует не там. Снаружи это неотличимо от успеха."""

    def test_every_load_declares_load_case_required(self) -> None:
        for name in ("create_point_load", "create_line_load", "create_area_load"):
            grounded = dict((p, r) for p, _pool, r in spec.OPS[name].grounded)
            with self.subTest(op=name):
                self.assertTrue(grounded["load_case"])

    def test_a_missing_load_case_is_a_typed_refusal(self) -> None:
        for op in LOAD_OPS:
            bare = {k: v for k, v in op.items() if k != "load_case"}
            with self.subTest(op=op["op"]):
                out = _compile(bare, "2023")
                self.assertFalse(out.ok)
                # Required selectors are a parse/schema invariant: an absent
                # field is rejected before grounding gets a selector to read.
                self.assertEqual(_codes(out), {PARSE_MISSING_FIELD})
                self.assertEqual(
                    {d.field_name for d in out.diagnostics}, {"load_case"})

    def test_an_ambiguous_case_name_refuses_with_candidates(self) -> None:
        """Два случая с одним именем — норма расчётного проекта. Отказ обязан
        нести кандидатов, иначе следующий ход автору взять неоткуда."""
        snap = dict(GROUND_SNAPSHOT)
        snap["load_cases"] = [{"id": 1500, "name": "Снег"},
                              {"id": 1501, "name": "Снег"}]
        prog = {"ir_version": "1.0",
                "ops": [dict(POINT_LOAD, load_case={"by": "name", "value": "Снег"})]}
        out = compile_program(prog, revit_version="2023", snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", _codes(out))
        self.assertTrue(any(d.candidates for d in out.diagnostics))


class ZeroLoadIsRefusedBeforeTheTransaction(unittest.TestCase):
    """Autodesk документирует `ArgumentsInconsistentException` на нулевую
    нагрузку. Рантайм-исключение внутри транзакции читается как НАШ дефект;
    это ошибка автора, и назвать её надо ей самой."""

    def test_all_zero_components_refuse_typed(self) -> None:
        bare = {"op": "create_point_load", "id": "Z", "xyz": [0, 0, 0],
                "load_case": CASE_ID}
        out = _compile(bare, "2023")
        self.assertFalse(out.ok)
        self.assertEqual(_codes(out), {ANALYSIS_ZERO_LOAD})

    def test_one_nonzero_component_is_enough(self) -> None:
        ok = {"op": "create_point_load", "id": "Z", "xyz": [0, 0, 0],
              "mz_nm": 10.0, "load_case": CASE_ID}
        self.assertTrue(_compile(ok, "2023").ok)


class WorkPlaneIsAuthoredNotInherited(unittest.TestCase):
    """`null` вместо плоскости отдал бы отметку нагрузки АКТИВНОМУ ВИДУ, то
    есть входу, которого в программе нет и который на машине пользователя нам
    неизвестен."""

    def test_the_emitter_builds_its_own_sketch_plane(self) -> None:
        for op in (POINT_LOAD, LINE_LOAD):
            with self.subTest(op=op["op"]):
                cs = _compile(op, "2023").csharp
                self.assertIn("SketchPlane.Create(doc, "
                              "Plane.CreateByNormalAndOrigin", cs)

    def test_a_sloped_line_load_gets_a_vertical_plane_through_its_segment(self) -> None:
        """Горизонтальная плоскость наклонный отрезок не содержит, и Revit
        отверг бы вызов внутри транзакции. Нормаль считается в питоне."""
        self.assertEqual(_plane_normal((0, 0, 0), (1000, 0, 0)), (0.0, 0.0, 1.0))
        nx, ny, nz = _plane_normal((0, 0, 0), (1000, 0, 500))
        self.assertEqual((round(nx, 9), round(ny, 9), nz), (0.0, -1.0, 0.0))
        # строго вертикальный отрезок: cross(d, Z) вырождается — выбор назван
        self.assertEqual(_plane_normal((0, 0, 0), (0, 0, 3000)), (1.0, 0.0, 0.0))

    def test_a_vertical_plane_actually_reaches_the_emission(self) -> None:
        sloped = dict(LINE_LOAD, id="LS", p1_mm=[6000, 2000, 4200])
        cs = _compile(sloped, "2023").csharp
        self.assertNotIn("Plane.CreateByNormalAndOrigin(XYZ.BasisZ", cs)
        self.assertIn("Plane.CreateByNormalAndOrigin(new XYZ(", cs)


class PathOfTravelRefusesWhatItCannotAddress(unittest.TestCase):
    def test_in_view_by_ref_is_refused_typed(self) -> None:
        """Ни один оп KIR не создаёт View, поэтому `as View` по ссылке — это
        гарантированный CS0039, а не случайность модели (замер 28.07)."""
        out = _compile(dict(PATH, in_view={"by": "ref", "value": "W1"}), "2023")
        self.assertFalse(out.ok)

    def test_a_non_plan_view_is_guarded_at_runtime(self) -> None:
        cs = _compile(PATH, "2023").csharp
        self.assertIn("ViewType.FloorPlan", cs)
        self.assertIn("IsTemplate", cs)

    def test_a_non_success_status_refuses_before_postconditions(self) -> None:
        """`ResultAffectedByCrop` вернул бы ЭЛЕМЕНТ с маршрутом по
        подрезанному виду — постусловие длины он бы прошёл."""
        cs = _compile(PATH, "2023").csharp
        status = cs.index("PathOfTravelCalculationStatus.Success")
        post = cs.index("// post PT1")
        self.assertLess(status, post)


class BoundaryConditionsAreDeliberatelyAbsent(unittest.TestCase):
    """РЕШЕНИЕ, А НЕ ЗАБЫВЧИВОСТЬ — тот же замок, что у `create_wire`.

    Три фабрики `New*BoundaryConditions` существуют на всех шести версиях и
    компилируются; операции всё равно нет. У точечной единственная перегрузка
    берёт `Reference` на КОНЕЦ АНАЛИТИЧЕСКОЙ ЛИНИИ — замороженный диалект
    ссылок KIR умеет называть элементы, и такое назвать нечем вообще. У
    линейной и площадной носитель адресуем, но весь смысл опоры — шесть
    степеней свободы, а прочитать их обратно НЕЧЕМ: у `BoundaryConditions`
    нет ни одного свойства о них, а `BOUNDARY_*_RESTRAINT_*` хранят целое,
    чьё соответствие `TranslationRotationValue` Autodesk не документирует.

    Снимает отказ ОДИН живой замер, а не переформулировка. Тест стоит здесь,
    чтобы следующая сессия не отгрузила вакуумную версию молча.
    """

    def test_no_boundary_condition_op_exists(self) -> None:
        offenders = [n for n in spec.OPS if "boundary" in n]
        self.assertEqual(offenders, [])

    def test_the_reason_is_written_down_where_the_next_wave_will_look(self) -> None:
        from kukai.ir import ops_analysis
        doc = ops_analysis.__doc__ or ""
        for probe in ("NewPointBoundaryConditions", "NewLineBoundaryConditions",
                      "TranslationRotationValue", "BOUNDARY_RESTRAINT_",
                      "ЧТО СНИМЕТ ОТКАЗ"):
            self.assertIn(probe, doc, probe)


class ForceToleranceIsDerived(unittest.TestCase):
    """Допуск, набранный рассуждением, — дефектный класс этого пакета
    (`create_door.sill_mm min_val=0`). Здесь число обязано СЛЕДОВАТЬ из
    объявленной границы диапазона и двоичной плавающей арифметики."""

    def test_the_number_follows_from_the_declared_bound(self) -> None:
        for name, key in (("create_point_load", "force_n"),
                          ("create_point_load", "moment_nm"),
                          ("create_line_load", "force_n_per_m"),
                          ("create_area_load", "force_n_per_m2")):
            op_spec = spec.OPS[name]
            bound = max(p.max_val for p in op_spec.params if p.kind == "num")
            # Относительная ошибка пути `x -> x*k -> (x*k)/k` в double не
            # превышает 3*2^-53 с учётом представления самого x.
            worst = bound * 3 * 2.0 ** -53
            with self.subTest(op=name, key=key):
                value = op_spec.tolerances[key]
                self.assertGreater(value, worst, "допуск ниже шума арифметики")
                self.assertLess(value, worst * 1000,
                                "допуск на три порядка выше вывода — это уже "
                                "назначенное число, а не выведенное")

    def test_geometry_registers_no_number_at_all(self) -> None:
        """У геометрии допуска в реестре нет и быть не должно: сравнение идёт
        с собственным допуском Revit, прочитанным во время проверки."""
        for name in ("create_point_load", "create_line_load",
                     "create_area_load", "create_path_of_travel"):
            with self.subTest(op=name):
                keys = set(spec.OPS[name].tolerances)
                self.assertFalse({k for k in keys if k.endswith("_mm")})


class ReverseIsNamedNotAssumed(unittest.TestCase):
    """«Стадия отказала на элементе» и «стадия о нём не говорила» — разные
    факты, и умолчание уже стоило этому пакету одного неверного диагноза."""

    def test_all_four_declare_a_capture_gap_with_a_named_limitation(self) -> None:
        for name in ("create_point_load", "create_line_load",
                     "create_area_load", "create_path_of_travel"):
            contract = REVERSE_CONTRACTS[name]
            with self.subTest(op=name):
                self.assertIs(contract.mode, ReverseMode.CAPTURE_GAP)
                self.assertTrue(contract.limitation.strip())
                self.assertTrue(contract.reason.strip())


class PoolsAreAskableBeforeTheAttempt(unittest.TestCase):
    """В расчётном проекте случаев загружения десятки; селектор по имени
    вслепую — это отказ ходом позже."""

    def test_every_new_pool_is_in_the_query_types_enum(self) -> None:
        choices = set(next(p for p in spec.OPS["query_types"].params
                           if p.name == "pool").choices)
        for pool in ("load_cases", "point_load_types", "line_load_types",
                     "area_load_types"):
            with self.subTest(pool=pool):
                self.assertIn(pool, choices)

    def test_the_snapshot_collects_exactly_those_pools(self) -> None:
        from kukai.ir.open_model import GROUND_SNAPSHOT_CS, required_grounding_pools
        for pool in ("load_cases", "point_load_types", "line_load_types",
                     "area_load_types"):
            with self.subTest(pool=pool):
                self.assertIn(f'__AddPool("{pool}"', GROUND_SNAPSHOT_CS)
                self.assertIn(pool, required_grounding_pools())

    def test_load_natures_is_absent_on_purpose(self) -> None:
        """Пул без селектора был бы первым исключением из правила «пул
        существует ради заземления»; операции создания случая в этой волне
        нет, значит нет и пула природ."""
        from kukai.ir.open_model import required_grounding_pools
        self.assertNotIn("load_natures", required_grounding_pools())


if __name__ == "__main__":
    unittest.main()
