"""Волна D2-A: сечения из `params` L0 -> оболочка точнее габаритного бокса.

Дисциплина та же, что в закалке: каждая правка сперва воспроизведена тестом,
который на прежнем коде КРАСНЫЙ, и только потом починена. Здесь это ветка
`axis_section`: она существовала с D1, но ждала поля `section_radius_mm`,
которого в артефактах декомпайла нет ни у одного элемента — числа лежат в
`params` строки L0 под именами BuiltInParameter (коммит d154196e).

Второй предмет файла — ЗАКОН КОНСЕРВАТИВНОСТИ на сечениях. Он не декларируется,
а меряется: тело элемента выбирается плотно, и КАЖДАЯ его точка обязана лежать
в оболочке. Для прямоугольного сечения выборка идёт по ВСЕМ углам крена,
потому что поворот сечения вокруг оси в L0 не снят — именно поэтому радиусом
взята полудиагональ, а не полуширина.

ПОПРАВКА 29.07 (R3 красной команды). Первая редакция этого файла строила
капсулы по `RBS_PIPE_DIAMETER_PARAM` / `RBS_CONDUIT_DIAMETER_PARAM`. Оба —
НОМИНАЛ («Diameter», «Diameter(Trade Size)» по RevitAPI.xml), и капсула по
номиналу тела не содержит: у ДУ100 радиус 50.0 против наружного 57.15. Тесты
переведены на наружные параметры, а закон «номинал оболочку не строит» живёт
контрпримерами в `test_clash_redteam.py`.

    venv/bin/pytest kukai/clash -q
"""
from __future__ import annotations

import json
import math
import pathlib
import random

import pytest

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.clash import snapshot as S

#: Живой декомпайл прод-бокса. Тесты, которым он нужен, помечены skipif —
#: остальные обязаны быть зелёными в чистом checkout (закон №18 закалки).
LIVE_V13 = (pathlib.Path(__file__).resolve().parents[3]
            / "backend" / "data" / "decompile" / "sob62_fas_r23_v13")


def _frame(d: G.Pt3, roll: float) -> tuple[G.Pt3, G.Pt3]:
    """Пара единичных нормалей к направлению `d`, повёрнутая на `roll`."""
    u0 = G._any_perpendicular(d)
    L = G._len(d)
    w = tuple(c / L for c in d)
    v0 = (w[1] * u0[2] - w[2] * u0[1],
          w[2] * u0[0] - w[0] * u0[2],
          w[0] * u0[1] - w[1] * u0[0])
    ca, sa = math.cos(roll), math.sin(roll)
    u = tuple(u0[i] * ca + v0[i] * sa for i in range(3))
    v = tuple(-u0[i] * sa + v0[i] * ca for i in range(3))
    return u, v


# ── A1: ветка axis_section мертва, пока сечение лежит в params ──────────────

def test_sections_pipe_reads_its_diameter_from_l0_params():
    """Опровергающий тест волны: элемент ровно в той форме, в какой его пишет
    декомпайл, — число сечения в `params`, а не в поле `section_radius_mm`.

    На коде D1 ветка `axis_section` смотрела ТОЛЬКО на `el["section_radius_mm"]`,
    которого в L0 нет ни у одного элемента, поэтому труба с известным диаметром
    получала габаритный бокс: грейд coarse, допуск ранжирования 25 мм, вердикт
    не выше `possible`, а разводящий перенос вообще не публикуется.
    """
    el = {"element_id": "p1", "category": "OST_PipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [4000, 0, 0],
          "params": {"RBS_PIPE_OUTER_DIAMETER": 100.0},
          "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [4050, 50, 50],
          "type_name": "Сталь 100"}
    rec, ref = H.build_hull(el)
    assert rec is not None, ref
    assert rec.hull_source == "axis_section", "диаметр из params не прочитан"
    assert isinstance(rec.hull, G.Capsule)
    assert rec.hull.radius == pytest.approx(50.0)
    assert rec.section_round is True
    assert rec.section_radius_mm == pytest.approx(50.0)


@pytest.mark.parametrize("category,params,expected_r,is_round", [
    ("OST_PipeCurves", {"RBS_PIPE_OUTER_DIAMETER": 219.0}, 109.5, True),
    ("OST_DuctCurves", {"RBS_CURVE_DIAMETER_PARAM": 400.0}, 200.0, True),
    ("OST_DuctCurves", {"RBS_CURVE_WIDTH_PARAM": 600.0,
                        "RBS_CURVE_HEIGHT_PARAM": 300.0},
     math.hypot(600.0, 300.0) / 2, False),
    ("OST_CableTray", {"RBS_CABLETRAY_WIDTH_PARAM": 200.0,
                       "RBS_CABLETRAY_HEIGHT_PARAM": 100.0},
     math.hypot(200.0, 100.0) / 2, False),
    ("OST_Conduit", {"RBS_CONDUIT_OUTER_DIAM_PARAM": 50.0}, 25.0, True),
])
def test_sections_every_mep_class_reads_its_own_parameter(
        category, params, expected_r, is_round):
    """Правило — свойство КАТЕГОРИИ, как и `sources` (ревью №12): труба читает
    диаметр трубы, лоток — габарит лотка. «Любое число, похожее на сечение» —
    ровно тот самый самосогласованный и пустой список источников."""
    el = {"element_id": "e", "category": category,
          "p0_mm": [0, 0, 0], "p1_mm": [3000, 0, 0], "params": params,
          "bbox_min_mm": [-500, -500, -500], "bbox_max_mm": [3500, 500, 500]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "axis_section", category
    assert rec.hull.radius == pytest.approx(expected_r)
    assert rec.section_round is is_round


def test_sections_oval_duct_takes_the_larger_radius():
    """У овального воздуховода читаются ОБА сечения. Меньший радиус мог бы не
    содержать тело, поэтому берётся больший — огрубление только вверх."""
    el = {"element_id": "d", "category": "OST_DuctCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [3000, 0, 0],
          "params": {"RBS_CURVE_DIAMETER_PARAM": 100.0,
                     "RBS_CURVE_WIDTH_PARAM": 600.0,
                     "RBS_CURVE_HEIGHT_PARAM": 300.0},
          "bbox_min_mm": [-500, -500, -500], "bbox_max_mm": [3500, 500, 500]}
    rec, _ = H.build_hull(el)
    assert rec.hull.radius == pytest.approx(math.hypot(600.0, 300.0) / 2)


def test_sections_a_non_positive_number_is_a_named_refusal_not_a_hull():
    """Нулевой/отрицательный диаметр строил бы капсулу нулевого радиуса —
    то есть отрезок вместо трубы. Это уменьшение оболочки, оно запрещено."""
    for bad in (0.0, -100.0, float("nan")):
        el = {"element_id": "p", "category": "OST_PipeCurves",
              "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
              "params": {"RBS_PIPE_OUTER_DIAMETER": bad},
              "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [1050, 50, 50]}
        rec, _ = H.build_hull(el)
        assert rec.hull_source == "bbox", bad
        assert "section_absent" in (rec.extra.get("downgraded_from") or []), bad


# ── A2: закон консервативности на сечениях, замером а не декларацией ────────

def test_sections_round_capsule_contains_the_whole_cylinder():
    """Тело круглой трубы — цилиндр с ПЛОСКИМИ торцами вокруг оси. Каждая его
    точка обязана лежать в капсуле радиуса d/2."""
    rnd = random.Random(20260729)
    for _ in range(40):
        p0 = tuple(rnd.uniform(-5000, 5000) for _ in range(3))
        d = tuple(rnd.uniform(-1, 1) for _ in range(3))
        if G._len(d) < 1e-3:
            continue
        L = rnd.uniform(100, 8000)
        w = tuple(c / G._len(d) * L for c in d)
        p1 = tuple(p0[i] + w[i] for i in range(3))
        diameter = rnd.uniform(15, 800)
        el = {"element_id": "p", "category": "OST_PipeCurves",
              "p0_mm": list(p0), "p1_mm": list(p1),
              "params": {"RBS_PIPE_OUTER_DIAMETER": diameter},
              "bbox_min_mm": [-1e6, -1e6, -1e6], "bbox_max_mm": [1e6, 1e6, 1e6]}
        rec, _ = H.build_hull(el)
        assert rec.hull_source == "axis_section"
        u, v = _frame(w, 0.0)
        r = diameter / 2
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            for k in range(12):
                ang = 2 * math.pi * k / 12
                for rad in (r, r * 0.5, 0.0):
                    pt = tuple(p0[i] + w[i] * t
                               + u[i] * rad * math.cos(ang)
                               + v[i] * rad * math.sin(ang) for i in range(3))
                    assert G.contains_point(rec.hull, pt), (
                        "точка тела трубы вне оболочки")


def test_sections_rectangular_capsule_contains_the_box_at_any_roll():
    """Поворот прямоугольного сечения вокруг оси в L0 НЕ снят. Значит оболочка
    обязана содержать коробку при ЛЮБОМ угле крена — а это ровно цилиндр
    радиуса hypot(w,h)/2. Проверяется плотной выборкой тела, включая углы,
    где оценка тугая: полуширина её бы уже не удержала."""
    rnd = random.Random(31415926)
    for _ in range(40):
        p0 = tuple(rnd.uniform(-5000, 5000) for _ in range(3))
        d = tuple(rnd.uniform(-1, 1) for _ in range(3))
        if G._len(d) < 1e-3:
            continue
        L = rnd.uniform(100, 8000)
        w = tuple(c / G._len(d) * L for c in d)
        p1 = tuple(p0[i] + w[i] for i in range(3))
        bw, bh = rnd.uniform(50, 1200), rnd.uniform(50, 1200)
        el = {"element_id": "t", "category": "OST_CableTray",
              "p0_mm": list(p0), "p1_mm": list(p1),
              "params": {"RBS_CABLETRAY_WIDTH_PARAM": bw,
                         "RBS_CABLETRAY_HEIGHT_PARAM": bh},
              "bbox_min_mm": [-1e6, -1e6, -1e6], "bbox_max_mm": [1e6, 1e6, 1e6]}
        rec, _ = H.build_hull(el)
        assert rec.hull_source == "axis_section"
        for roll_i in range(8):
            u, v = _frame(w, 2 * math.pi * roll_i / 8)
            for t in (0.0, 0.5, 1.0):
                for a in (-bw / 2, 0.0, bw / 2):
                    for b in (-bh / 2, 0.0, bh / 2):
                        pt = tuple(p0[i] + w[i] * t + u[i] * a + v[i] * b
                                   for i in range(3))
                        assert G.contains_point(rec.hull, pt), (
                            f"угол коробки вне оболочки при крене {roll_i}")


def test_sections_capsule_is_not_exact_the_spherical_cap_proves_it():
    """Ревью кодекса №11 дословно: точка ЗА плоским торцом трубы, но внутри
    полусферы капсулы, лежит в оболочке и вне тела. Значит оболочка содержит
    тело СТРОГО, значит грейд `conservative`, а не `exact`.

    Это не придирка: `exact` в `evaluate_with_reason` даёт вердикт `confirmed`,
    то есть обвинение, которого оболочка не доказывает.
    """
    el = {"element_id": "p", "category": "OST_PipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
          "params": {"RBS_PIPE_OUTER_DIAMETER": 200.0},
          "bbox_min_mm": [-100, -100, -100], "bbox_max_mm": [1100, 100, 100]}
    rec, _ = H.build_hull(el)
    assert rec.grade == "conservative"
    beyond_the_flat_end = (1050.0, 0.0, 0.0)     # за торцом, внутри полусферы
    assert G.contains_point(rec.hull, beyond_the_flat_end)
    assert D.pair_grade(rec, rec) != "exact"


# ── A3: стена не поднимается — запрет, а не «данных нет» ────────────────────

def test_sections_wall_with_width_param_still_gets_a_bounding_box():
    """На v13 толщина есть у 992 стен из 1189 — то есть «данных нет» больше НЕ
    защищает. Защищает запрет: `OST_Walls` не имеет источника `axis_section`,
    и появление числа ничего не меняет (ревью №2)."""
    el = {"element_id": "w", "category": "OST_Walls",
          "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
          "bbox_min_mm": [-100, -100, 0], "bbox_max_mm": [5100, 100, 3000]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "bbox" and rec.grade == "coarse"
    assert rec.section_radius_mm is None, "стене сечение не переносится"
    assert G.contains_point(rec.hull, (2500.0, 0.0, 2900.0))


def test_sections_wall_prism_builder_contains_the_wall_body():
    """Билдер стены НАПИСАН (ревью №10 требует его для будущего захвата) и
    проверен отдельно от таблицы: полоса вокруг оси обязана содержать тело
    стены целиком, включая верх — то, чего капсула вокруг нижней оси не даёт."""
    pr = H.hull_from_wall_axis((0, 0, 0), (5000, 0, 0), width_mm=200.0,
                               z0=0.0, z1=3000.0)
    assert pr is not None
    for x in (0.0, 2500.0, 5000.0):
        for y in (-100.0, 0.0, 100.0):
            for z in (0.0, 1500.0, 3000.0):
                assert G.contains_point(pr, (x, y, z)), (x, y, z)


def test_sections_wall_prism_builder_honours_the_location_line_offset():
    """Стена стоит НЕ по оси, когда location line — грань: тело смещено на
    полтолщины. Билдер обязан принимать смещение явным числом, а не угадывать
    его из `WALL_KEY_REF_PARAM` (знак зависит от ориентации, которой в L0 нет).
    """
    pr = H.hull_from_wall_axis((0, 0, 0), (5000, 0, 0), width_mm=200.0,
                               z0=0.0, z1=3000.0, offset_mm=100.0)
    assert G.contains_point(pr, (2500.0, 200.0, 1500.0))
    assert not G.contains_point(pr, (2500.0, -100.0, 1500.0))


def test_sections_wall_prism_blockers_name_what_is_missing():
    """Три класса стен, из-за которых одна толщина неконсервативна (ревью №10):
    slanted/tapered (WALL_CROSS_SECTION), stacked/vertically compound (состав
    по высоте), sweeps. L0 не снимает ни одного — и билдер это ГОВОРИТ."""
    el = {"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0, "WALL_KEY_REF_PARAM": 0}}
    blockers = H.wall_prism_blockers(el)
    assert set(blockers) == set(H.WALL_PRISM_EVIDENCE)


@pytest.mark.xfail(strict=True,
                   reason="blocked-on-ground-sections: WALL_CROSS_SECTION, состав "
                          "CompoundStructure по высоте и список sweeps L0 не "
                          "снимает, поэтому призма по одной толщине не доказана "
                          "консервативной (ревью кодекса №10). Тест обязан "
                          "покраснеть в день захвата — и тогда снимается xfail "
                          "вместе с SOURCES_BBOX у OST_Walls.")
def test_sections_wall_prism_is_blocked_on_cross_section():
    el = {"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0}}
    assert H.wall_prism_blockers(el) == ()


# ── C: перепись сечений в снапшоте ─────────────────────────────────────────

def _mep_scene() -> list[dict]:
    return [
        {"element_id": "1", "category": "OST_PipeCurves",
         "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
         "params": {"RBS_PIPE_OUTER_DIAMETER": 100.0},
         "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [1050, 50, 50],
         "type_name": "Сталь 100"},
        {"element_id": "2", "category": "OST_PipeCurves",
         "p0_mm": [0, 500, 0], "p1_mm": [1000, 500, 0], "params": {},
         "bbox_min_mm": [-50, 450, -50], "bbox_max_mm": [1050, 550, 50],
         "type_name": "Без сечения"},
        {"element_id": "3", "category": "OST_Walls",
         "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000],
         "type_name": "Кирпич 200"},
    ]


def test_census_counts_sections_present_absent_and_hulled():
    """«Сечений нет» обязано быть неотличимо от «не спрашивали» ТОЛЬКО в одном
    случае — когда мы это доказали числом. Перепись публикует три счётчика."""
    snap = S.build_from_elements(_mep_scene(), origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert sec["totals"] == {"present": 1, "absent": 1, "hulled": 1}
    assert sec["by_category"]["OST_PipeCurves"] == {
        "present": 1, "absent": 1, "hulled": 1, "eligible": 2}
    assert "OST_Walls" not in sec["by_category"], (
        "стене сечение не разрешено — её нет и в знаменателе сечений")


def test_census_lists_the_types_that_have_no_section():
    """Счётчик «типов без сечения» (директива C): без него отсутствие сечения
    у целого типа выглядит так же, как у одного битого элемента."""
    snap = S.build_from_elements(_mep_scene(), origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert sec["types_without_section_count"] == 1
    assert sec["types_without_section"] == {"OST_PipeCurves": ["Без сечения"]}


def test_census_section_balance_is_a_gate_not_a_warning():
    """Тот же закон, что у переписи оболочек: расхождение — исключение."""
    snap = S.build_from_elements(_mep_scene(), origin={"run_dir": "t"})
    snap.validate()
    snap.census.section_absent["OST_PipeCurves"] += 5
    with pytest.raises(S.SnapshotIntegrityError):
        snap.validate()


def test_census_names_every_section_bearing_category_even_when_absent():
    """Фасад SOB6.2 не содержит НИ ОДНОГО элемента MEP. Пустой блок сечений в
    таком отчёте читается как «не спрашивали» — а это ровно то, от чего закон
    переписи защищает. Поэтому знаменатель печатается всегда, включая нули:
    «0 из 0» и «не искали» обязаны выглядеть по-разному."""
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}],
        origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert set(sec["by_category"]) == set(H.SECTION_RULES), (
        "категории, которым сечение разрешено, обязаны стоять в знаменателе "
        "даже с нулём элементов")
    assert sec["by_category"]["OST_PipeCurves"]["eligible"] == 0


def test_census_counts_the_numbers_that_the_table_refuses_to_use():
    """Главное число волны на фасаде: сечение ЕСТЬ (992 стены из 1189), а
    подъёма НЕТ — потому что запрет, а не потому что данных нет. Без этого
    счётчика «coarse=всё» неотличимо от сломанного чтения параметров."""
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]},
         {"element_id": "w2", "category": "OST_Walls", "params": {},
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}],
        origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert sec["blocked_by_table"] == {"OST_Walls": 1}
    assert sec["blocked_total"] == 1


def test_the_closed_section_list_matches_the_emission():
    """Потребитель и эмиссия обязаны знать ОДИН список параметров. Разойдясь,
    они дадут молчаливую дыру: снимаем одно, читаем другое."""
    from kukai.ir.decompile.extract import SECTION_PARAM_NAMES
    assert (tuple(sorted(H.ALL_SECTION_PARAM_NAMES + H.SECTION_ENUM_PARAM_NAMES))
            == SECTION_PARAM_NAMES), (
        "эмиссия и потребитель разошлись: снимаем одно, читаем другое")
    assert not (set(H.ALL_SECTION_PARAM_NAMES) & set(H.SECTION_ENUM_PARAM_NAMES))


def test_markdown_says_out_loud_that_no_section_was_lifted():
    """Отчёт обязан СКАЗАТЬ «сечений не поднято и вот почему», а не показать
    это нулём в таблице грейдов."""
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}],
        origin={"run_dir": "t"})
    md = D.to_markdown(D.detect(snap, pair_filter=D.any_physical_pair_filter))
    assert "## Сечения" in md
    assert "запрещён таблицей" in md


def test_a_finding_names_the_parameter_its_hull_stands_on():
    """`hull_source: axis_section` говорит «оболочка из оси и сечения», но не
    ГДЕ взято число. Для находки это существенно: диаметр трубы и полудиагональ
    лотка — разные обоснования одной и той же капсулы."""
    els = [
        {"element_id": "1", "category": "OST_PipeCurves",
         "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
         "params": {"RBS_PIPE_OUTER_DIAMETER": 200.0},
         "bbox_min_mm": [-100, -100, -100], "bbox_max_mm": [1100, 100, 100]},
        {"element_id": "2", "category": "OST_Walls",
         "bbox_min_mm": [400, -200, -200], "bbox_max_mm": [600, 200, 200]},
    ]
    rep = D.detect(S.build_from_elements(els, origin={"run_dir": "t"}))
    assert rep["findings"], "труба сквозь стену не найдена"
    sides = [rep["findings"][0]["a"], rep["findings"][0]["b"]]
    pipe = [s for s in sides if s["label"] == "pipe"][0]
    assert pipe["section_source"] == "RBS_PIPE_OUTER_DIAMETER"
    assert pipe["section_radius_mm"] == 100.0
    wall = [s for s in sides if s["label"] == "wall"][0]
    assert wall["section_source"] is None


def test_detect_publishes_the_section_census():
    """Отчёт обязан НАЗВАТЬ отсутствие сечений, а не показать его нулём в
    `by_grade`: «coarse=всё» без причины неотличимо от сломанного чтения."""
    snap = S.build_from_elements(_mep_scene(), origin={"run_dir": "t"})
    rep = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    assert rep["census"]["sections"]["totals"]["absent"] == 1


# ── E: живой v13 (артефакт прод-бокса) ─────────────────────────────────────

@pytest.mark.skipif(not LIVE_V13.exists(),
                    reason="живой декомпайл только на прод-боксе")
def test_live_v13_walls_carry_width_and_still_stay_coarse():
    """Числом: на v13 толщина снята у 992 стен из 1189 — и НИ ОДНА оболочка от
    этого не поднялась, потому что стене источник запрещён. Это и есть честный
    ноль подъёмов: данные ЕСТЬ, подъёма НЕТ, причина названа."""
    with_width = total = 0
    for line in (LIVE_V13 / "L0.jsonl").open(encoding="utf-8"):
        line = line.strip()
        if not line or '"OST_Walls"' not in line:
            continue
        row = json.loads(line)
        if row.get("record") != "element":
            continue
        el = row["element"]
        if el.get("category") != "OST_Walls":
            continue
        total += 1
        if "WALL_ATTR_WIDTH_PARAM" in (el.get("params") or {}):
            with_width += 1
        rec, _ = H.build_hull(el)
        assert rec is None or rec.hull_source == "bbox"
    assert (total, with_width) == (1189, 992)
