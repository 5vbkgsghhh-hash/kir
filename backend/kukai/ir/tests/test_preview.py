"""Глаза компилятора: тесты ОПРОВЕРГАЮЩИЕ.

Порядок разделов повторяет порядок законов из :mod:`kukai.ir.preview`.  Самый
важный — §4: если элемент не нарисован, он обязан быть ПОСЧИТАН и НАЗВАН.
Превью, тихо опускающее часть здания, хуже отсутствия превью, поэтому здесь
проверяется не «рисуется ли стена», а «нельзя ли молча потерять».
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import preview as P  # noqa: E402
from kukai.ir.decompile.schema import (  # noqa: E402
    GeometryKind, L0Document, L0Element, LevelInfo, LocationCurveKind,
    GridInfo, ProjectInfo, RoomInfo, L0_UNITS,
)

LVL = {"by": "ref", "value": "LV"}


def _program(*ops, intent="test"):
    return {"ir_version": "1.0", "intent": intent,
            "ops": [{"op": "create_level", "id": "LV", "elev_mm": 0,
                     "name": "Этаж 1"}, *ops]}


def _doc(levels=(("L1", 0.0),), grids=(), rooms=()):
    return L0Document(
        doc_name="тест", revit_version="2023", units=L0_UNITS,
        change_stamp="stamp-1",
        levels=tuple(LevelInfo(id=f"lv{i}", name=name, elevation_mm=elev)
                     for i, (name, elev) in enumerate(levels)),
        grids=tuple(grids), rooms=tuple(rooms),
        project_info=ProjectInfo(name="проект"))


def _wall(ident, p0, p1, *, level_id="lv0", width=200.0, curve_kind=None,
          params=None):
    body = {"WALL_ATTR_WIDTH_PARAM": width} if width is not None else {}
    body.update(params or {})
    return L0Element(
        element_id=ident, category="OST_Walls", category_ru="Стены",
        type_id="t1", type_name="Стена 200",
        level_id=level_id, level_name="L1", geom_kind=GeometryKind.CURVE,
        p0_mm=(p0[0], p0[1], 0.0), p1_mm=(p1[0], p1[1], 0.0),
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None, host_id=None,
        params=body, curve_kind=curve_kind)


def _opening(ident, host, xy, *, category="OST_Doors", width=900.0,
             level_id="lv0"):
    return L0Element(
        element_id=ident, category=category,
        category_ru="Двери" if category == "OST_Doors" else "Окна",
        type_id="t2", type_name="Д-1", level_id=level_id, level_name="L1",
        geom_kind=GeometryKind.POINT, p0_mm=(xy[0], xy[1], 0.0), p1_mm=None,
        rotation_deg=0.0, bbox_min_mm=None, bbox_max_mm=None, host_id=host,
        params={"FAMILY_WIDTH_PARAM": width})


def _bbox_only(ident, category, lo, hi, *, level_id="lv0", params=None):
    return L0Element(
        element_id=ident, category=category, category_ru="", type_id="t",
        type_name="", level_id=level_id, level_name="L1",
        geom_kind=GeometryKind.BBOX_ONLY, p0_mm=None, p1_mm=None,
        rotation_deg=None, bbox_min_mm=(lo[0], lo[1], 0.0),
        bbox_max_mm=(hi[0], hi[1], 0.0), host_id=None, params=params or {})


def _render(plan):
    return P.render_svg(plan)


def _metadata(svg: str) -> dict:
    start = svg.index('<metadata id="kir-preview">') + len(
        '<metadata id="kir-preview">')
    end = svg.index("</metadata>", start)
    blob = (svg[start:end].replace("&quot;", '"').replace("&lt;", "<")
            .replace("&gt;", ">").replace("&amp;", "&"))
    return json.loads(blob)


# ---------------------------------------------------------------------------
# ЗАКОН №4 — главный: молча потерять нельзя
# ---------------------------------------------------------------------------

class CensusLawTests(unittest.TestCase):
    def test_census_refuses_to_exist_when_an_element_vanishes(self):
        """Тождество стоит в конструкторе, а не в тесте: тест можно забыть
        написать для нового пути, конструктор обойти нельзя."""
        with self.assertRaises(P.PreviewCensusError) as ctx:
            P.PreviewCensus(considered=10, drawn=7, omitted=())
        self.assertIn("молча потеряно 3", str(ctx.exception))

    def test_census_accepts_only_a_complete_account(self):
        census = P.PreviewCensus(
            considered=10, drawn=7,
            omitted=(P.OmissionGroup(P.OmitReason.NO_GEOMETRY, "OST_Doors", 3),))
        self.assertEqual(census.omitted_total, 3)
        self.assertAlmostEqual(census.coverage_pct, 70.0)

    def test_every_omitted_element_is_named_by_reason_model(self):
        """Ни один выброшенный элемент не имеет права исчезнуть из переписи."""
        elements = [
            _wall("1", (0, 0), (5000, 0)),
            # без геометрии
            L0Element(element_id="2", category="OST_Walls", category_ru="",
                      type_id="", type_name="", level_id="lv0",
                      level_name="L1", geom_kind=GeometryKind.POINT,
                      p0_mm=(0.0, 0.0, 0.0), p1_mm=None, rotation_deg=0.0,
                      bbox_min_mm=None, bbox_max_mm=None, host_id=None,
                      params={}),
            # аннотация
            _bbox_only("3", "OST_Dimensions", (0, 0), (100, 100)),
            # категории нет в таблице правил
            _bbox_only("4", "OST_Zzz_Unknown", (0, 0), (100, 100)),
            # перекрытие без бокового эскиза
            _bbox_only("5", "OST_Floors", (0, 0), (5000, 5000)),
            # этаж не определён
            _bbox_only("6", "OST_Furniture", (0, 0), (100, 100), level_id=None),
        ]
        building = P.build_model_preview(_doc(), elements)
        plan = building.plan("L1")
        self.assertEqual(plan.census.considered, 5)
        self.assertEqual(plan.census.drawn, 1)
        reasons = {group.reason for group in plan.census.omitted}
        self.assertEqual(reasons, {P.OmitReason.NO_GEOMETRY,
                                   P.OmitReason.ANNOTATION_NOT_MODEL,
                                   P.OmitReason.CATEGORY_NOT_DRAWN,
                                   P.OmitReason.ONLY_BBOX})
        # шестой элемент не потерялся — он в переписи ЗДАНИЯ
        self.assertEqual(building.census.considered, 6)
        self.assertIn(P.OmitReason.LEVEL_UNKNOWN,
                      {group.reason for group in building.census.omitted})

    def test_levels_not_rendered_are_counted_not_silent(self):
        """Прогон по одному этажу из двух НЕ имеет права выглядеть полным."""
        doc = _doc(levels=(("L1", 0.0), ("L2", 3000.0)))
        elements = [_wall("1", (0, 0), (5000, 0)),
                    _wall("2", (0, 0), (5000, 0), level_id="lv1"),
                    _wall("3", (0, 1000), (5000, 1000), level_id="lv1")]
        building = P.build_model_preview(doc, elements, levels=["L1"])
        self.assertEqual(len(building.plans), 1)
        self.assertEqual(building.census.considered, 3)
        skipped = [group for group in building.census.omitted
                   if group.reason is P.OmitReason.LEVEL_NOT_IN_RUN]
        self.assertEqual([group.count for group in skipped], [2])

    def test_program_census_accounts_for_every_op(self):
        program = _program(
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [5000, 0], "level": LVL},
            # операции без правила рисования
            {"op": "set_param", "id": "S1",
             "target": {"by": "ref", "value": "W1"}, "param": "x", "value": 1},
            {"op": "delete", "id": "X1", "target": {"by": "ref", "value": "W1"}},
        )
        building = P.build_program_preview(program)
        # 4 операции: create_level (датум), create_wall, set_param, delete
        self.assertEqual(building.census.considered, 4)
        self.assertEqual(building.census.drawn, 1)
        self.assertEqual(building.census.omitted_total, 3)
        self.assertEqual(
            {group.reason for group in building.census.omitted},
            {P.OmitReason.NOT_VISIBLE_IN_PLAN, P.OmitReason.SELECTOR_UNRESOLVED})

    def test_drawn_element_cannot_be_empty(self):
        """«Нарисован» без единой фигуры — это потеря, а не отрисовка."""
        with self.assertRaises(P.PreviewError):
            P.DrawnElement("1", "OST_Walls", P.Layer.WALL, ())


# ---------------------------------------------------------------------------
# Опровергающие случаи, названные в задании
# ---------------------------------------------------------------------------

class RefutingCaseTests(unittest.TestCase):
    def test_empty_program_does_not_pretend_to_be_a_plan(self):
        building = P.build_program_preview({"ir_version": "1.0", "intent": "",
                                            "ops": []})
        self.assertEqual(building.plans, ())
        self.assertTrue(building.census.vacuous)
        self.assertEqual(building.census.coverage_pct, 0.0)

    def test_empty_model_level_renders_an_explicit_void(self):
        building = P.build_model_preview(_doc(), [])
        plan = building.plan("L1")
        self.assertTrue(plan.census.vacuous)
        self.assertIsNone(plan.extents_mm())
        svg = _render(plan)
        self.assertIn("ПУСТО", svg)
        self.assertIn("НЕЧЕГО РИСОВАТЬ", svg)

    def test_element_without_geometry_is_omitted_and_named(self):
        element = _bbox_only("7", "OST_Furniture", (0, 0), (0, 0))
        naked = L0Element(
            element_id="8", category="OST_Furniture", category_ru="",
            type_id="", type_name="", level_id="lv0", level_name="L1",
            geom_kind=GeometryKind.BBOX_ONLY, p0_mm=None, p1_mm=None,
            rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=None, params={})
        building = P.build_model_preview(_doc(), [element, naked])
        plan = building.plan("L1")
        self.assertEqual(plan.census.drawn, 0)
        reasons = {group.reason: group.count for group in plan.census.omitted}
        self.assertEqual(reasons[P.OmitReason.DEGENERATE], 1)
        self.assertEqual(reasons[P.OmitReason.NO_GEOMETRY], 1)

    def test_zero_length_wall_is_refused_not_drawn_as_a_dot(self):
        elements = [_wall("1", (1000, 1000), (1000.4, 1000)),
                    _wall("2", (0, 0), (5000, 0))]
        plan = P.build_model_preview(_doc(), elements).plan("L1")
        self.assertEqual(plan.census.drawn, 1)
        self.assertEqual([(g.reason, g.count) for g in plan.census.omitted],
                         [(P.OmitReason.DEGENERATE, 1)])
        # и в программе тоже
        program = _program({"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                            "p1_mm": [0, 0.2], "level": LVL})
        building = P.build_program_preview(program)
        self.assertEqual(building.census.drawn, 0)
        self.assertIn(P.OmitReason.DEGENERATE,
                      {g.reason for g in building.census.omitted})

    def test_door_past_the_end_of_its_wall_is_drawn_and_flagged(self):
        """Дверь за краем стены — НАХОДКА, а не повод её спрятать.

        Она рисуется там, где вычислилась (мусор обязан быть виден), и
        одновременно попадает в аномалии.  Прятать её значило бы вернуть
        ровно ту слепоту, ради которой этот экран написан.
        """
        wall = _wall("1", (0, 0), (5000, 0))
        good = _opening("2", "1", (2500, 0))
        past = _opening("3", "1", (9000, 0))
        plan = P.build_model_preview(_doc(), [wall, good, past]).plan("L1")
        self.assertEqual(plan.census.drawn, 3)
        anomalies = {g.reason: g for g in plan.census.anomalies}
        self.assertIn(P.AnomalyReason.OPENING_OUTSIDE_HOST, anomalies)
        self.assertEqual(anomalies[P.AnomalyReason.OPENING_OUTSIDE_HOST].count, 1)
        self.assertEqual(
            anomalies[P.AnomalyReason.OPENING_OUTSIDE_HOST].examples, ("3",))
        svg = _render(plan)
        self.assertIn('data-anomaly="opening_outside_host"', svg)

    def test_opening_without_a_drawable_host_is_omitted_by_name(self):
        orphan = _opening("2", "999", (2500, 0))
        hostless = _opening("3", None, (2500, 0))
        plan = P.build_model_preview(
            _doc(), [_wall("1", (0, 0), (5000, 0)), orphan, hostless]).plan("L1")
        reasons = {g.reason: g.count for g in plan.census.omitted}
        self.assertEqual(reasons[P.OmitReason.HOST_NOT_DRAWABLE], 1)
        self.assertEqual(reasons[P.OmitReason.HOST_UNKNOWN], 1)

    def test_rotated_grid_building_keeps_its_geometry(self):
        """Здание с повёрнутыми осями: ничего не выпрямляется и не теряется."""
        angle = math.radians(37.0)
        cos_a, sin_a = math.cos(angle), math.sin(angle)

        def rot(x, y):
            return (x * cos_a - y * sin_a, x * sin_a + y * cos_a)

        corners = [(0, 0), (8000, 0), (8000, 6000), (0, 6000)]
        walls = [_wall(str(index + 1), rot(*corners[index]),
                       rot(*corners[(index + 1) % 4]))
                 for index in range(4)]
        grids = [GridInfo(id="g1", name="A", p0_mm=(*rot(-2000, 0), 0.0),
                          p1_mm=(*rot(10000, 0), 0.0))]
        plan = P.build_model_preview(_doc(grids=grids), walls).plan("L1")
        self.assertEqual(plan.census.drawn, 4)
        self.assertEqual(plan.census.omitted, ())
        min_x, min_y, max_x, max_y = plan.extents_mm()
        # повёрнутый прямоугольник ШИРЕ и ВЫШЕ своих собственных сторон
        self.assertGreater(max_x - min_x, 8000.0)
        self.assertGreater(max_y - min_y, 6000.0)
        # ни одна вершина не «выпрямлена» на оси
        xs = [point[0] for element in plan.elements
              for shape in element.shapes for point in shape.points()]
        self.assertTrue(any(abs(x) > 1.0 for x in xs))
        self.assertIn("A", _render(plan))

    def test_spline_wall_is_refused_not_straightened_into_a_chord(self):
        """Хорда вместо сплайна проходила VERIFY как exact — здесь отказ."""
        wall = _wall("1", (0, 0), (5000, 0),
                     curve_kind=LocationCurveKind.OTHER)
        plan = P.build_model_preview(_doc(), [wall]).plan("L1")
        self.assertEqual(plan.census.drawn, 0)
        self.assertEqual([(g.reason, g.count) for g in plan.census.omitted],
                         [(P.OmitReason.UNSUPPORTED_CURVE, 1)])


# ---------------------------------------------------------------------------
# ЗАКОН №5 — детерминизм
# ---------------------------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def _sample_plan(self):
        rooms = [RoomInfo(id="r1", name="Зал", level_id="lv0", level_name="L1",
                          area_m2=42.0,
                          boundary_mm=((0, 0), (8000, 0), (8000, 6000), (0, 6000)),
                          boundary_loops_mm=(((0, 0), (8000, 0), (8000, 6000),
                                              (0, 6000)),),
                          bounding_element_ids=())]
        elements = [_wall("1", (0, 0), (8000, 0)),
                    _opening("2", "1", (3000, 0)),
                    _opening("4", "1", (6000, 0), category="OST_Windows"),
                    L0Element(element_id="r1", category="OST_Rooms",
                              category_ru="", type_id="", type_name="",
                              level_id="lv0", level_name="L1",
                              geom_kind=GeometryKind.POINT,
                              p0_mm=(4000.0, 3000.0, 0.0), p1_mm=None,
                              rotation_deg=None, bbox_min_mm=None,
                              bbox_max_mm=None, host_id=None, params={})]
        grids = [GridInfo(id="g1", name="A", p0_mm=(-1000.0, 0.0, 0.0),
                          p1_mm=(9000.0, 0.0, 0.0))]
        return _doc(grids=grids, rooms=rooms), elements

    def test_same_input_same_bytes(self):
        doc, elements = self._sample_plan()
        first = _render(P.build_model_preview(doc, elements).plan("L1"))
        second = _render(P.build_model_preview(doc, list(elements)).plan("L1"))
        self.assertEqual(first, second)
        self.assertEqual(hash(first), hash(second))

    def test_element_order_does_not_change_the_bytes(self):
        doc, elements = self._sample_plan()
        forward = _render(P.build_model_preview(doc, elements).plan("L1"))
        backward = _render(
            P.build_model_preview(doc, list(reversed(elements))).plan("L1"))
        self.assertEqual(forward, backward)

    def test_digest_covers_geometry_not_only_counts(self):
        doc, elements = self._sample_plan()
        base = P.build_model_preview(doc, elements).plan("L1")
        moved = list(elements)
        moved[0] = _wall("1", (0, 0), (8000, 500))
        other = P.build_model_preview(doc, moved).plan("L1")
        self.assertEqual(base.census.drawn, other.census.drawn)
        self.assertNotEqual(base.content_digest, other.content_digest)

    def test_no_wall_clock_or_random_identity_in_the_artifact(self):
        doc, elements = self._sample_plan()
        svg = _render(P.build_model_preview(doc, elements).plan("L1"))
        self.assertNotIn("Date", svg)
        self.assertNotIn("random", svg)
        # повторная сборка ЧЕРЕЗ НОВЫЕ объекты обязана дать те же байты
        doc2, elements2 = self._sample_plan()
        self.assertEqual(svg, _render(
            P.build_model_preview(doc2, elements2).plan("L1")))


# ---------------------------------------------------------------------------
# ЗАКОН №6 — сила утверждения обязана быть ВИДНА
# ---------------------------------------------------------------------------

class AssertionStrengthTests(unittest.TestCase):
    def _pair(self):
        program = _program(
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": LVL},
            {"op": "create_wall", "id": "W2", "p0_mm": [8000, 0],
             "p1_mm": [8000, 6000], "level": LVL})
        program_plan = P.build_program_preview(program).plans[0]
        model_plan = P.build_model_preview(
            _doc(), [_wall("1", (0, 0), (8000, 0)),
                     _wall("2", (8000, 0), (8000, 6000))]).plan("L1")
        return program_plan, model_plan

    def test_source_and_assertion_are_typed_not_implied(self):
        program_plan, model_plan = self._pair()
        self.assertIs(program_plan.assertion, P.Assertion.SELF_REPORTED)
        self.assertIs(model_plan.assertion, P.Assertion.INDEPENDENT)

    def test_the_two_sheets_cannot_be_mistaken_for_one_another(self):
        program_svg, model_svg = (_render(plan) for plan in self._pair())
        self.assertIn("САМОПРОВЕРКА", program_svg)
        self.assertIn("ЗАЯВЛЕНО", program_svg)
        self.assertIn("Модель НЕ читалась", program_svg)
        self.assertNotIn("САМОПРОВЕРКА", model_svg)
        self.assertNotIn("ЗАЯВЛЕНО", model_svg)
        self.assertIn("НЕЗАВИСИМОЕ ЧТЕНИЕ", model_svg)
        # и машинно, без зрения
        self.assertEqual(_metadata(program_svg)["assertion"], "self_reported")
        self.assertEqual(_metadata(model_svg)["assertion"], "independent")

    def test_program_never_claims_a_thickness_it_cannot_know(self):
        program_plan, model_plan = self._pair()
        self.assertIn(P.ApproxReason.THICKNESS_UNKNOWN,
                      {group.reason for group in program_plan.census.approx})
        self.assertEqual(model_plan.census.approx, ())

    def test_metadata_carries_the_whole_census_for_a_blind_reader(self):
        _, model_plan = self._pair()
        meta = _metadata(_render(model_plan))
        self.assertEqual(meta["schema"], P.PREVIEW_SCHEMA)
        self.assertEqual(meta["census"]["considered"], 2)
        self.assertEqual(meta["census"]["drawn"], 2)
        self.assertEqual(meta["content_digest"], model_plan.content_digest)


# ---------------------------------------------------------------------------
# «Нарисовано» ≠ «нарисовано точно», и подозрительное названо
# ---------------------------------------------------------------------------

class ApproximationAndAnomalyTests(unittest.TestCase):
    def test_bbox_footprint_is_declared_an_approximation(self):
        column = _bbox_only("1", "OST_StructuralColumns", (0, 0), (400, 400))
        plan = P.build_model_preview(_doc(), [column]).plan("L1")
        self.assertEqual(plan.census.drawn, 1)
        self.assertEqual([(g.reason, g.count) for g in plan.census.approx],
                         [(P.ApproxReason.FOOTPRINT_FROM_BBOX, 1)])

    def test_wall_without_a_width_parameter_is_a_spine_not_a_body(self):
        plan = P.build_model_preview(
            _doc(), [_wall("1", (0, 0), (5000, 0), width=None)]).plan("L1")
        element = plan.elements[0]
        self.assertIsInstance(element.shapes[0], P.Path)
        self.assertEqual(element.shapes[0].role, "spine")
        self.assertIn(P.ApproxReason.THICKNESS_UNKNOWN, element.approx)

    def test_coincident_walls_are_flagged_but_an_arc_is_not_its_chord(self):
        walls = [_wall("1", (0, 0), (5000, 0)), _wall("2", (5000, 0), (0, 0)),
                 _wall("3", (0, 2000), (5000, 2000))]
        curve_index = {}
        plan = P.build_model_preview(_doc(), walls,
                                     curve_index=curve_index).plan("L1")
        anomalies = {g.reason: g.count for g in plan.census.anomalies}
        self.assertEqual(anomalies[P.AnomalyReason.COINCIDENT_WALLS], 2)

        # та же хорда, но РАЗНЫЕ дуги — это две разные стены, не дубли
        arc_index = {
            "1": {"curve_kind": "arc",
                  "arc": {"center_mm": [2500.0, 0.0, 0.0], "radius_mm": 2500.0,
                          "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0],
                          "start_angle_rad": math.pi,
                          "end_angle_rad": 2 * math.pi}},
            "2": {"curve_kind": "arc",
                  "arc": {"center_mm": [2500.0, 3000.0, 0.0],
                          "radius_mm": 3905.1,
                          "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0],
                          "start_angle_rad": 3.8877, "end_angle_rad": 5.5371}},
        }
        plan2 = P.build_model_preview(_doc(), walls[:2],
                                      curve_index=arc_index).plan("L1")
        self.assertEqual(plan2.census.anomalies, ())

    def test_far_outliers_are_named_and_do_not_hide_the_building(self):
        """Замер 03.08 (k2/L16): 44 улетевших телефонных аппарата уводили
        масштаб с 32 до 146 мм/px и прятали 1610 правильных элементов."""
        walls = [_wall(str(index), (index * 300, 0), (index * 300, 2000))
                 for index in range(1, 25)]
        strays = [_bbox_only(f"s{index}", "OST_TelephoneDevices",
                             (200_000 + index * 100, 0),
                             (200_100 + index * 100, 100))
                  for index in range(3)]
        plan = P.build_model_preview(_doc(), walls + strays).plan("L1")
        self.assertEqual(plan.outliers, 3)
        anomalies = {g.reason: g.count for g in plan.census.anomalies}
        self.assertEqual(anomalies[P.AnomalyReason.FAR_OUTLIER], 3)
        # улетевшее ВСЁ ЕЩЁ нарисовано — не выброшено
        self.assertEqual(plan.census.drawn, len(walls) + len(strays))
        # но кадр стоит по ядру
        self.assertLess(plan.extents_mm()[2], 100_000.0)
        self.assertIn("КАДР ПО ЯДРУ", _render(plan))

    def test_outlier_rule_stays_silent_on_two_legitimate_clouds(self):
        """Больше четверти «выбросов» = два облака, а не мусор.  Лучше не
        сказать ничего, чем объявить половину здания улетевшей."""
        left = [_wall(str(i), (i * 300, 0), (i * 300, 2000)) for i in range(1, 13)]
        right = [_wall(f"r{i}", (500_000 + i * 300, 0), (500_000 + i * 300, 2000))
                 for i in range(1, 13)]
        plan = P.build_model_preview(_doc(), left + right).plan("L1")
        self.assertEqual(plan.outliers, 0)
        self.assertEqual(plan.census.anomalies, ())

    def test_level_recovered_from_a_parameter_is_marked_not_asserted(self):
        """Лестницы держат STAIRS_BASE_LEVEL_PARAM, а level_id у них пуст —
        падение на параметр это ВТОРОЕ ЧТЕНИЕ, а не прямое знание."""
        stair = L0Element(
            element_id="1", category="OST_Stairs", category_ru="Лестницы",
            type_id="t", type_name="", level_id=None, level_name=None,
            geom_kind=GeometryKind.BBOX_ONLY, p0_mm=None, p1_mm=None,
            rotation_deg=None, bbox_min_mm=(0.0, 0.0, 0.0),
            bbox_max_mm=(3000.0, 1200.0, 0.0), host_id=None,
            params={"STAIRS_BASE_LEVEL_PARAM": "lv0"})
        plan = P.build_model_preview(_doc(), [stair]).plan("L1")
        self.assertEqual(plan.census.drawn, 1)
        self.assertIn(P.ApproxReason.LEVEL_VIA_PARAMETER,
                      {group.reason for group in plan.census.approx})

    def test_room_with_zero_area_is_drawn_and_called_unenclosed(self):
        rooms = [RoomInfo(id="r1", name="Зал", level_id="lv0", level_name="L1",
                          area_m2=0.0,
                          boundary_mm=((0, 0), (1000, 0), (1000, 1000)),
                          boundary_loops_mm=(((0, 0), (1000, 0), (1000, 1000)),),
                          bounding_element_ids=())]
        element = L0Element(
            element_id="r1", category="OST_Rooms", category_ru="", type_id="",
            type_name="", level_id="lv0", level_name="L1",
            geom_kind=GeometryKind.POINT, p0_mm=(500.0, 500.0, 0.0),
            p1_mm=None, rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=None, params={})
        plan = P.build_model_preview(_doc(rooms=rooms), [element]).plan("L1")
        self.assertEqual(plan.census.drawn, 1)
        self.assertEqual([(g.reason, g.count) for g in plan.census.anomalies],
                         [(P.AnomalyReason.ROOM_NOT_ENCLOSED, 1)])


# ---------------------------------------------------------------------------
# Один рисовальщик: обе стороны говорят одним языком форм
# ---------------------------------------------------------------------------

class SingleDrawerTests(unittest.TestCase):
    def test_arc_is_sampled_the_same_way_from_both_sources(self):
        arc = {"curve_type": "Arc", "center_mm": [2500.0, 0.0, 0.0],
               "radius_mm": 2500.0, "x_axis": [1.0, 0.0, 0.0],
               "y_axis": [0.0, 1.0, 0.0], "start_angle_rad": math.pi,
               "end_angle_rad": 2 * math.pi}
        program = _program({"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                            "p1_mm": [5000, 0], "level": LVL, "arc": arc})
        program_plan = P.build_program_preview(program).plans[0]
        model_plan = P.build_model_preview(
            _doc(), [_wall("1", (0, 0), (5000, 0), width=None)],
            curve_index={"1": {"curve_kind": "arc", "arc": arc}}).plan("L1")
        program_pts = program_plan.elements[0].shapes[0].pts
        model_pts = model_plan.elements[0].shapes[0].pts
        self.assertEqual(program_pts, model_pts)
        for plan in (program_plan, model_plan):
            self.assertIn(P.ApproxReason.ARC_SAMPLED,
                          {group.reason for group in plan.census.approx})

    def test_slab_outline_comes_from_the_sketch_never_from_the_bbox(self):
        floor = _bbox_only("1", "OST_Floors", (0, 0), (8000, 6000))
        bare = P.build_model_preview(_doc(), [floor]).plan("L1")
        self.assertEqual([(g.reason, g.count) for g in bare.census.omitted],
                         [(P.OmitReason.ONLY_BBOX, 1)])
        sketch = {"1": {"profile_available": True,
                        "exterior_loop": [[0, 0], [8000, 0], [8000, 6000],
                                          [0, 6000]],
                        "holes": [], "curve_kinds": [], "arc_midpoints": []}}
        drawn = P.build_model_preview(_doc(), [floor],
                                      sketch_index=sketch).plan("L1")
        self.assertEqual(drawn.census.drawn, 1)
        self.assertIsInstance(drawn.elements[0].shapes[0], P.Poly)

    def test_number_formatting_never_emits_minus_zero_or_exponent(self):
        self.assertEqual(P._fmt(-0.001), "0")
        self.assertEqual(P._fmt(1.5), "1.5")
        self.assertEqual(P._fmt(2.0), "2")
        self.assertEqual(P._fmt(1e-9), "0")
        with self.assertRaises(P.PreviewError):
            P._fmt(float("nan"))

    def test_text_is_escaped_so_a_room_name_cannot_break_the_sheet(self):
        rooms = [RoomInfo(id="r1", name='Зал <b>"A&B"</b>', level_id="lv0",
                          level_name="L1", area_m2=40.0,
                          boundary_mm=((0, 0), (8000, 0), (8000, 6000)),
                          boundary_loops_mm=(((0, 0), (8000, 0), (8000, 6000),
                                              (0, 6000)),),
                          bounding_element_ids=())]
        element = L0Element(
            element_id="r1", category="OST_Rooms", category_ru="", type_id="",
            type_name="", level_id="lv0", level_name="L1",
            geom_kind=GeometryKind.POINT, p0_mm=(4000.0, 3000.0, 0.0),
            p1_mm=None, rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=None, params={})
        svg = _render(P.build_model_preview(_doc(rooms=rooms),
                                            [element]).plan("L1"))
        self.assertNotIn("<b>", svg)
        self.assertIn("&lt;b&gt;", svg)

    def test_blind_spots_are_printed_on_the_sheet(self):
        """Список слепоты полезнее списка возможностей: молчание превью
        читается как «всё в порядке»."""
        svg = _render(P.build_model_preview(
            _doc(), [_wall("1", (0, 0), (5000, 0))]).plan("L1"))
        self.assertIn("ЭТОТ ЭКРАН НЕ ПОКАЖЕТ", svg)
        self.assertIn(P.BLIND_SPOTS[0], svg)
        self.assertIn("истинный север не задан", svg)


# ---------------------------------------------------------------------------
# Живой корпус: превью обязано выдерживать НАСТОЯЩИЙ разбор
# ---------------------------------------------------------------------------

SNAPSHOT = ("/opt/kukai-rebuild1/backend/backend/data/decompile/"
            "sob62_r23_v5")


@unittest.skipUnless(os.path.isdir(SNAPSHOT), "живого слепка нет на этой машине")
class LiveSnapshotTests(unittest.TestCase):
    def test_real_building_level_draws_and_accounts(self):
        building = P.preview_snapshot(SNAPSHOT, levels=["L_02ДОО_+6.100"])
        plan = building.plan("L_02ДОО_+6.100")
        self.assertGreater(plan.census.drawn, 300)
        self.assertEqual(plan.census.considered,
                         plan.census.drawn + plan.census.omitted_total)
        self.assertEqual(
            building.census.considered,
            building.census.drawn + building.census.omitted_total)
        svg = _render(plan)
        self.assertEqual(svg, _render(plan))
        meta = _metadata(svg)
        self.assertEqual(meta["census"]["drawn"], plan.census.drawn)


if __name__ == "__main__":
    unittest.main()


class CoincidentWallsAreFoundOnTheProgramPathToo(unittest.TestCase):
    """`COINCIDENT_WALLS` выставлялся РОВНО в одном месте — по разобранному
    зданию. Программа, объявившая две стены с одними и теми же концами, не
    помечалась ничем.

    Тот же перекос входа, что был у замкнутости: способность есть на одном
    источнике и отсутствует на другом. А дубль стены — дефект АВТОРСКИЙ: его
    чинит тот, кто пишет программу, и узнать о нём он обязан ДО того, как это
    станет двумя стенами в модели.
    """

    _LVL = {"by": "ref", "value": "L1"}
    _LEVEL = {"op": "create_level", "id": "L1", "elev_mm": 0.0, "name": "Этаж 1"}

    def _wall(self, oid, p0, p1):
        return {"op": "create_wall", "id": oid, "level": self._LVL,
                "height_mm": 3000.0, "p0_mm": list(p0), "p1_mm": list(p1)}

    def _flagged(self, ops):
        preview = P.build_program_preview(
            {"ir_version": "1.0", "intent": "проба", "ops": [self._LEVEL] + ops})
        return {element.element_id
                for plan in preview.plans for element in plan.elements
                if P.AnomalyReason.COINCIDENT_WALLS in element.anomalies}

    def test_two_walls_with_the_same_ends_are_both_flagged(self):
        assert self._flagged([self._wall("d1", (0, 0), (6000, 0)),
                              self._wall("d2", (0, 0), (6000, 0))]) == {"d1", "d2"}

    def test_the_same_ends_reversed_are_still_the_same_wall(self):
        """Личность стены не зависит от порядка концов — иначе автор обходил бы
        находку, поменяв местами две точки."""
        assert self._flagged([self._wall("r1", (0, 0), (6000, 0)),
                              self._wall("r2", (6000, 0), (0, 0))]) == {"r1", "r2"}

    def test_two_genuinely_different_walls_are_left_alone(self):
        """КОНТРОЛЬ. Без него прибор, помечающий ВСЁ, был бы зелен на первых
        двух проверках и не измерял бы ничего."""
        assert self._flagged([self._wall("u1", (0, 0), (6000, 0)),
                              self._wall("u2", (0, 2000), (6000, 2000))]) == set()
