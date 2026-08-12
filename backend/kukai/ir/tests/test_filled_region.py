"""create_filled_region — 2D-заливка по контуру, живущая НА ВИДЕ (09.08.2026).

Первая операция, где сходятся ДВА подъязыка: CONTOUR даёт форму, docspace —
пространство. Файл держит ровно те законы, которые из-за этого стыка можно
нарушить молча, и ни одного «оп существует».

ЧТО ДОКАЗЫВАЕТСЯ ЗДЕСЬ:
  * контур ложится в ПЛОСКОСТЬ ВИДА, а не в XY модели (иначе Revit отвергает
    петлю на любом разрезе — а на плане молча принял бы, и дефект был бы виден
    только на живой модели с непрямым базисом);
  * прямой и обратный ходы ТОЖДЕСТВЕННЫ, а не похожи — одна формула на оба;
  * свидетель читает РЕЗУЛЬТАТ (`GetBoundaries()`), а не эхо аргумента;
  * адрес от осей внутри контура — типизированный ОТКАЗ, а не «на планах
    совпадёт»;
  * допуск ВЫВЕДЕН из `contour._EDGE_TOL`, а не назначен.

ЧТО ЭТОТ ФАЙЛ ДОКАЗАТЬ НЕ МОЖЕТ И НЕ ПРИТВОРЯЕТСЯ: живого Revit здесь нет.
Что именно вернёт `GetBoundaries()` у построенной заливки — совпадут ли петли
числом, сохранит ли Revit дугу дугой, не переставит ли начало кольца, — это
замер живьём. Офлайн доказана ФОРМА свидетеля и то, что он смотрит наружу.

ЗАПИСАННЫЕ ОТКАЗЫ (последний класс тестов): марка высотной отметки и объёмный
текст. Оба замерены компиляцией и оба ОТКАЗАНЫ; тест существует затем, чтобы
причина не протухла молча вместе с прозой, которая её объясняет.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_fr_queue.jsonl"))

from kukai.ir import contour, docspace, spec                    # noqa: E402
from kukai.ir.compiler import compile_program                   # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
IN_VIEW = {"by": "element_id", "value": 900}          # id-pinned: пула видов нет
RECT = {"outer": {"shape": "rect", "origin": [500, 500], "size_mm": [3000, 1200]}}


def _fr(oid="F1", **kw):
    op = {"op": "create_filled_region", "id": oid, "in_view": IN_VIEW,
          "contour": RECT}
    op.update(kw)
    return op


def _prog(ops, intent="filled-region-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _emit(ops, ver="2026"):
    out = compile_program(_prog(ops), revit_version=ver, snapshot=SNAPSHOT)
    assert out.ok, [f"{d.code}: {d.message_ru}" for d in out.diagnostics]
    return out.csharp


class ItCompilesOnEveryShippedVersion(unittest.TestCase):
    """Ось версий у заливки ПЛОСКАЯ, и это замер, а не надежда:
    `FilledRegion.Create(Document, ElementId, ElementId, IList<CurveLoop>)`,
    `GetBoundaries()`, `IsValidFilledRegionTypeId` и
    `ElementTypeGroup.FilledRegionType` компилируются на 2021-2026 против
    эталонных сборок. Поэтому в эмиттере НЕТ ни одной развилки по версии — и
    этот тест обязан упасть, если она появится."""

    def test_same_emission_shape_on_all_six(self):
        for ver in VERSIONS:
            with self.subTest(ver=ver):
                cs = _emit([_fr()], ver)
                self.assertIn("FilledRegion.Create(doc, __frt_F1.Id, "
                              "__vw_F1.Id, __loops_F1)", cs)
                self.assertIn("FilledRegion.IsValidFilledRegionTypeId", cs)
                self.assertIn("__el_F1.GetBoundaries()", cs)

    def test_no_version_branch_hides_in_the_emission(self):
        """Тексты шести версий отличаются РОВНО литералом ElementId, если
        отличаются вообще. Развилка версии, добавленная без замера, поедет
        здесь."""
        bodies = {ver: _emit([_fr(type={"by": "element_id", "value": 1800})],
                             ver)
                  for ver in VERSIONS}
        stripped = {ver: cs.replace("new ElementId(1800)", "<ID>")
                        .replace("new ElementId((long)1800)", "<ID>")
                        .replace("new ElementId(900)", "<VIEW>")
                        .replace("new ElementId((long)900)", "<VIEW>")
                    for ver, cs in bodies.items()}
            # Штамп программы зависит от её дайджеста, а не от версии.
        self.assertEqual(len(set(stripped.values())), 1,
                         "эмиссия разошлась по версиям — где замер?")


class ContourLandsInViewSpaceNotModelXY(unittest.TestCase):
    """САМЫЙ ВАЖНЫЙ ЗАКОН ЭТОГО ОПА.

    `FilledRegion.Create` требует петлю в плоскости, параллельной СОБСТВЕННОЙ
    эскизной плоскости вида (RevitAPI.xml). Готовый `contour.emit_loop_cs`
    собирает петлю при z=0 в мировых XY — это верно на плане и отвергается на
    разрезе. Дефект такого рода невидим офлайн и невидим на планах, поэтому
    закон закреплён здесь структурно."""

    def test_every_loop_point_goes_through_the_view_basis(self):
        cs = _emit([_fr()])
        loop_lines = [ln for ln in cs.splitlines() if ".Append(" in ln]
        self.assertTrue(loop_lines, "петля не собрана вовсе")
        for ln in loop_lines:
            self.assertIn("__vp_F1(", ln,
                          "точка петли не прошла через базис вида")
            self.assertNotIn("P(", ln.replace("__vp_F1(", ""),
                             "точка петли построена в мировых XY — на разрезе "
                             "Revit отвергнет петлю целиком")

    def test_the_point_function_is_the_family_forward_map(self):
        """Функция точки — НЕ вторая формула, а та же самая. Иначе заливка и
        текст на одном виде оказались бы в разных местах."""
        cs = _emit([_fr()])
        one_point = docspace.emit_view2d_to_xyz_cs("__vw_F1", 500.0, 500.0)
        # Из выражения одной точки убираем её литералы — остаётся скелет,
        # который обязан слово в слово стоять в теле локальной функции.
        skeleton = one_point.replace("U(500.0)", "U(__u)", 1) \
                            .replace("U(500.0)", "U(__v)", 1)
        self.assertIn(skeleton, cs)
        self.assertIn("XYZ __vp_F1(double __u, double __v) =>", cs)

    def test_forward_and_inverse_are_one_law(self):
        """Тождественность, а не сходство: обратный ход берёт ТЕ ЖЕ Right/Up в
        ТОМ ЖЕ порядке, что прямой, и обе стороны рождены одним модулем."""
        cs = _emit([_fr()])
        fwd = docspace.emit_view2d_to_xyz_cs("__vw_F1", 0.0, 0.0)
        self.assertLess(fwd.index("RightDirection"), fwd.index("UpDirection"))
        inv = docspace.emit_xyz_to_view2d_cs(
            "__vw_F1", "__frCv_F1.GetEndPoint(0)", "__frRa_F1",
            "__frAu_F1", "__frAv_F1")
        self.assertLess(inv.index("RightDirection"), inv.index("UpDirection"))
        # Отступ ставит сборщик программы, поэтому сверяются СТРОКИ, а не
        # блок целиком: обратный ход обязан стоять в эмиссии дословно.
        emitted = {ln.strip() for ln in cs.splitlines()}
        for line in inv.strip().splitlines():
            self.assertIn(line.strip(), emitted)
        # Обратный ход читает СОЗДАННЫЙ элемент, а не аргумент вызова.
        self.assertIn("__frCv_F1.GetEndPoint(0) - __vw_F1.Origin", cs)


class TheWitnessReadsTheResult(unittest.TestCase):
    """Свидетель обязан перечитать построенную границу, а не подтвердить, что
    вызов состоялся."""

    def test_boundary_is_reread_and_matched_edge_for_edge(self):
        cs = _emit([_fr()])
        post = cs[cs.index("// post F1"):cs.index("// witness F1")]
        self.assertIn("__el_F1.GetBoundaries()", post)
        self.assertIn("__frCv_F1.GetEndPoint(0)", post)
        self.assertIn("__frCv_F1.GetEndPoint(1)", post)
        # Середина ребра — единственное, чем дуга отличается от своей хорды.
        self.assertIn("__frCv_F1.Evaluate(0.5, true)", post)
        self.assertIn("__post.Add", post)

    def test_loop_and_curve_counts_are_gated(self):
        """Дырка добавляет петлю и рёбра: числа в свидетеле обязаны ехать
        вместе с контуром, иначе они не свидетельство, а украшение."""
        with_hole = dict(RECT)
        with_hole = {"outer": RECT["outer"],
                     "holes": [{"shape": "rect", "origin": [1000, 700],
                                "size_mm": [500, 400]}]}
        plain = _emit([_fr()])
        holed = _emit([_fr(contour=with_hole)])
        self.assertIn("__frLoops_F1 != 1 || __frCurves_F1 != 4", plain)
        self.assertIn("__frLoops_F1 != 2 || __frCurves_F1 != 8", holed)
        self.assertIn("new int[4]", plain)
        self.assertIn("new int[8]", holed)

    def test_every_authored_edge_must_be_matched_exactly_once(self):
        """«Найдено хотя бы одно» ловит подмену контура наполовину. Здесь
        требуется биекция: каждое авторское ребро ровно один раз, и ни одной
        лишней кривой."""
        cs = _emit([_fr()])
        self.assertIn("if (__frHit_F1[__frJ_F1] != 1) __frExact_F1 = false;", cs)
        self.assertIn("if (!__frOne_F1) __frStray_F1 = true;", cs)

    def test_arc_midpoint_travels_into_the_witness(self):
        """Дуга и её хорда имеют ОДНИ И ТЕ ЖЕ концы. Без середины свидетель
        принял бы построенную хорду за заказанную дугу."""
        arc = {"outer": {"shape": "poly",
                         "points_mm": [[0, 0], [4000, 0], [4000, 2500],
                                       [0, 2500]],
                         "arcs": [{"edge": 1, "bulge": 0.4}]}}
        cs = _emit([_fr(contour=arc)])
        mid = contour.bulge_midpoint([4000.0, 0.0], [4000.0, 2500.0], 0.4)
        self.assertIn(f"Arc.Create(__vp_F1(4000.0, 0.0), "
                      f"__vp_F1(4000.0, 2500.0), "
                      f"__vp_F1({round(mid[0], 2)}, {round(mid[1], 2)}))", cs)
        # ТА ЖЕ середина обязана лежать в массиве, с которым сверяется
        # прочитанная кривая — иначе свидетель проверял бы другую дугу.
        self.assertIn(f"double[] __fum_F1 = new double[] {{ 2000.0, "
                      f"{round(mid[0], 2)},", cs)

    def test_type_is_reread_from_the_built_element(self):
        cs = _emit([_fr(type={"by": "name", "value": "Бетон"})])
        self.assertIn("__el_F1.GetTypeId().ToString() != __frt_F1.Id.ToString()",
                      cs)

    def test_is_masking_is_recorded_never_asserted(self):
        """«Заливка это или маска» решает ТИП, а какие типы проекта
        маскирующие — из программы не видно. Факт едет в квитанцию; отказывать
        по нему значило бы отказывать по догадке."""
        cs = _emit([_fr()])
        post = cs[cs.index("// post F1"):cs.index("// witness F1")]
        witness = cs[cs.index("// witness F1"):]
        self.assertNotIn("IsMasking", post)
        self.assertIn('__rb["is_masking"] = __el_F1.IsMasking', witness)


class SpaceConfusionIsRefusedNotTolerated(unittest.TestCase):
    """Точки контура — [u,v] ПРОСТРАНСТВА ВИДА. Ось живёт в модели: на плане
    с мировым базисом эти числа совпали бы, на разрезе означали бы другое
    место. Ровно тот класс, который docspace делает невыразимым."""

    def test_grid_anchor_inside_the_contour_is_a_typed_refusal(self):
        addressed = {"outer": {"shape": "rect",
                               "origin": {"at_grid": ["А", "1"]},
                               "size_mm": [3000, 1200]}}
        out = compile_program(_prog([_fr(contour=addressed)]),
                              revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        text = " ".join(d.message_ru or "" for d in out.diagnostics)
        self.assertIn("at_grid", text)
        self.assertIn("ПРОСТРАНСТВЕ ВИДА", text)

    def test_a_plain_contour_is_not_refused(self):
        """Отказ, которого API не требует, — такая же ложь, как молчание."""
        out = compile_program(_prog([_fr()]), revit_version="2026",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok,
                        [d.message_ru for d in out.diagnostics])

    def test_a_coordinate_outside_the_working_extent_is_refused(self):
        """У самого CONTOUR предела координат нет вовсе; предел берётся тот
        же, что у `at` марки и текста, — потому что это то же пространство."""
        huge = {"outer": {"shape": "rect",
                          "origin": [docspace._SHEET_LIMIT_MM * 2, 0],
                          "size_mm": [3000, 1200]}}
        out = compile_program(_prog([_fr(contour=huge)]),
                              revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_in_view_by_ref_is_refused_like_the_rest_of_the_family(self):
        out = compile_program(
            _prog([{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                    "p1_mm": [6000, 0],
                    "level": {"by": "name", "value": "Этаж 1"}},
                   _fr(in_view={"by": "ref", "value": "W1"})]),
            revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("in_view", " ".join(d.field_name or ""
                                          for d in out.diagnostics))


class TheToleranceIsDerivedNotInvented(unittest.TestCase):
    """1.0 мм — это СОБСТВЕННОЕ разрешение CONTOUR по точкам
    (`contour._EDGE_TOL`): ребро короче него подъязык отвергает статически как
    нулевое, то есть две точки ближе миллиметра для этого языка — ОДНА точка.
    Свидетель не вправе различать то, чего язык различить не даёт."""

    def test_boundary_tolerance_equals_the_contour_edge_tolerance(self):
        self.assertEqual(
            spec.OPS["create_filled_region"].tolerances["boundary_mm"],
            contour._EDGE_TOL)

    def test_the_number_actually_reaches_the_emission(self):
        self.assertIn("<= 1.0", _emit([_fr()]))


class GroundingFollowsTheExistingPattern(unittest.TestCase):
    def test_named_type_resolves_through_the_new_pool(self):
        cs = _emit([_fr(type={"by": "name", "value": "Грунт"})])
        self.assertIn("new ElementId(1801)", cs)

    def test_omitted_type_uses_the_document_default(self):
        """У заливки документное умолчание СУЩЕСТВУЕТ (замер: 6/6). Общее
        правило «единственный в пуле» здесь было бы хуже всего — у настоящего
        проекта типов заливки десятки."""
        cs = _emit([_fr()])
        self.assertIn("doc.GetDefaultElementTypeId("
                      "ElementTypeGroup.FilledRegionType)", cs)
        self.assertNotIn("new ElementId(1800)", cs)

    def test_the_pool_is_askable_before_the_program(self):
        self.assertIn("filled_region_types",
                      spec.OPS["query_types"].params[0].choices)

    def test_an_unknown_type_name_refuses_with_candidates(self):
        out = compile_program(
            _prog([_fr(type={"by": "name", "value": "Нет такого"})]),
            revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(any(d.candidates for d in out.diagnostics))


class RecordedRefusalsStayRecorded(unittest.TestCase):
    """ОТКАЗЫ С НАЗВАННОЙ ПРИЧИНОЙ, замеренные 09.08 против шести эталонных
    сборок. Тест — не про вкус, а про то, чтобы причина не исчезла вместе с
    прозой: без него следующая волна предложит их заново и потратит день на
    повторный замер."""

    def test_no_elevation_marker_op_exists_and_the_reason_is_written_down(self):
        self.assertNotIn("create_elevation_marker", spec.OPS)
        self.assertNotIn("create_elevation_view", spec.OPS)
        from kukai.ir import ops_annotation
        doc = ops_annotation.__doc__ or ""
        # Причина, а не факт: пустой маркер ничего не рисует, а его виды
        # требуют ReferenceKind.VIEW — изменения ЯЗЫКА, не операции.
        self.assertIn("CurrentViewCount", doc)
        self.assertIn("ReferenceKind.VIEW", doc)
        # И правильное имя сиблинга: `CreateElevationView` не существует.
        self.assertIn("CreateElevation(Document", doc)
        self.assertIn("CreateElevationView", doc)

    def test_no_model_text_op_exists_and_the_reason_is_written_down(self):
        self.assertNotIn("create_model_text", spec.OPS)
        from kukai.ir import ops_annotation
        doc = ops_annotation.__doc__ or ""
        self.assertIn("NewModelText", doc)
        self.assertIn("FamilyItemFactory", doc)
        self.assertIn("CS1061", doc)


class ExistingEmissionDidNotMove(unittest.TestCase):
    """Обратная формула переехала в docspace ИЗ марки и текста — байт в байт.
    Эталоны это уже доказывают; здесь — прямая проверка того, что помощник
    рождает ровно те строки, которые стояли в эмиттерах руками."""

    def test_the_helper_reproduces_the_hand_written_tag_bytes(self):
        self.assertEqual(
            docspace.emit_xyz_to_view2d_cs(
                "__vw_T1", "__el_T1.TagHeadPosition", "__rel_T1",
                "__ou_T1", "__ow_T1", indent=" " * 8),
            "        var __rel_T1 = __el_T1.TagHeadPosition - __vw_T1.Origin;\n"
            "        double __ou_T1 = MM(__rel_T1.DotProduct(__vw_T1.RightDirection));\n"
            "        double __ow_T1 = MM(__rel_T1.DotProduct(__vw_T1.UpDirection));\n")

    def test_the_model_space_loop_builder_is_unchanged(self):
        """У `emit_loop_cs` появился необязательный форматтер точки. Без него
        байты обязаны быть прежними — иначе поехали бы все контурные полы."""
        edges = [([0.0, 0.0], [1000.0, 0.0], 0.0),
                 ([1000.0, 0.0], [0.0, 0.0], 0.5)]
        self.assertEqual(
            contour.emit_loop_cs(edges, "__ol"),
            "CurveLoop __ol = new CurveLoop();\n"
            "__ol.Append(Line.CreateBound(P(0.0, 0.0, 0), P(1000.0, 0.0, 0)));\n"
            "__ol.Append(Arc.Create(P(1000.0, 0.0, 0), P(0.0, 0.0, 0), "
            f"P({round(contour.bulge_midpoint([1000.0, 0.0], [0.0, 0.0], 0.5)[0], 2)}, "
            f"{round(contour.bulge_midpoint([1000.0, 0.0], [0.0, 0.0], 0.5)[1], 2)}, 0)));")


if __name__ == "__main__":
    unittest.main()
