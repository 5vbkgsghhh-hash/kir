"""Контрпримеры красной команды (29.07) — по одному на находку.

Дисциплина прежняя: находка сперва воспроизводится тестом, красным на текущем
коде, и только потом чинится. Нумерация тестов = нумерация находок
`docs/2026-07-29-clash-redteam.md`.

Ядро красные НЕ сломали: 105 780 живых оболочек, 0 нарушений консервативности.
Сломали продукт и приёмку — и ровно эти места здесь.

    venv/bin/pytest kukai/clash -q
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.clash import snapshot as S

LIVE = (pathlib.Path(__file__).resolve().parents[3]
        / "backend" / "data" / "decompile")


# ── R3 P0: номинальный диаметр вместо наружного — оболочка НЕ содержит трубу ─

def test_r3_nominal_diameter_never_builds_a_capsule():
    """Живая улика красных, числами ДУ100.

    `RBS_PIPE_DIAMETER_PARAM` — «Diameter», номинал (сверено по RevitAPI.xml).
    Наружный у ДУ100 — 114.3 мм. Капсула радиуса 50.0 НЕ содержит тело
    радиуса 57.15: недостача 7.15 мм на сторону, и это в паре MVP, где
    пропуск стоит дороже всего.

    Закон один и тот же с находкой №1 закалки (дуга/хорда): нет доказательства,
    что оболочка содержит тело, — откат вниз, а не вера в число. Габаритный
    бокс приходит из НАСТОЯЩЕЙ геометрии Revit и тело содержит.
    """
    el = {"element_id": "p", "category": "OST_PipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [4000, 0, 0],
          "params": {"RBS_PIPE_DIAMETER_PARAM": 100.0},
          "bbox_min_mm": [-58, -58, -58], "bbox_max_mm": [4058, 58, 58]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "bbox", "номинал построил капсулу"
    assert rec.grade == "coarse"
    assert "section_nominal_only" in (rec.extra.get("downgraded_from") or [])
    # число не потеряно — оно названо и помечено как номинал
    assert rec.section_radius_mm is None
    assert rec.extra.get("nominal_radius_mm") == pytest.approx(50.0)
    # и главное: тело настоящей трубы лежит в оболочке
    assert G.contains_point(rec.hull, (2000.0, 57.15, 0.0))


def test_r3_outer_diameter_builds_the_capsule_and_contains_the_body():
    """Наружный диаметр — единственное, что доказывает содержание."""
    el = {"element_id": "p", "category": "OST_PipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [4000, 0, 0],
          "params": {"RBS_PIPE_DIAMETER_PARAM": 100.0,
                     "RBS_PIPE_OUTER_DIAMETER": 114.3},
          "bbox_min_mm": [-58, -58, -58], "bbox_max_mm": [4058, 58, 58]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "axis_section"
    assert rec.hull.radius == pytest.approx(57.15)
    assert rec.section_source == "RBS_PIPE_OUTER_DIAMETER"
    assert rec.grade == "conservative"
    for ang in range(0, 360, 15):
        a = math.radians(ang)
        assert G.contains_point(
            rec.hull, (2000.0, 57.15 * math.cos(a), 57.15 * math.sin(a)))


def test_r3_the_missed_clash_is_actually_found_now():
    """Контрпример красных целиком: балка в 55 мм от оси трубы ДУ100.

    Было: `signed_distance = +5.0`, вердикт «ничего» — при том что тело трубы
    режет балку на 2.15 мм. Стало: наружный диаметр даёт находку, а без
    наружного оболочкой становится габарит, который тело содержит.
    """
    beam = {"element_id": "b", "category": "OST_StructuralFraming",
            "bbox_min_mm": [1000, 55, -200], "bbox_max_mm": [3000, 255, 200]}
    pipe_outer = {"element_id": "p", "category": "OST_PipeCurves",
                  "p0_mm": [0, 0, 0], "p1_mm": [4000, 0, 0],
                  "params": {"RBS_PIPE_DIAMETER_PARAM": 100.0,
                             "RBS_PIPE_OUTER_DIAMETER": 114.3},
                  "bbox_min_mm": [-58, -58, -58], "bbox_max_mm": [4058, 58, 58]}
    snap = S.build_from_elements([beam, pipe_outer], origin={"run_dir": "t"})
    rep = D.detect(snap)
    assert rep["findings"], "клеш ДУ100 против балки снова пропущен"
    assert rep["findings"][0]["hull_overlap_depth_mm"] == pytest.approx(2.15, abs=1e-3)


def test_r3_conduit_trade_size_is_nominal_too():
    """`RBS_CONDUIT_DIAMETER_PARAM` — «Diameter(Trade Size)», то есть номинал
    прямым текстом в API. Тот же закон, что у трубы."""
    el = {"element_id": "c", "category": "OST_Conduit",
          "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
          "params": {"RBS_CONDUIT_DIAMETER_PARAM": 50.0},
          "bbox_min_mm": [-40, -40, -40], "bbox_max_mm": [1040, 40, 40]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "bbox"
    el["params"]["RBS_CONDUIT_OUTER_DIAM_PARAM"] = 63.5
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "axis_section"
    assert rec.hull.radius == pytest.approx(31.75)


def test_r3_duct_diameter_is_the_modelled_size_and_is_named_so():
    """У воздуховода наружного параметра в API НЕТ ни в одной из шести версий
    (сверено компиляцией). Значит `RBS_CURVE_DIAMETER_PARAM` — единственное
    описание сечения; оно классифицировано ЯВНО, а не по умолчанию."""
    assert H.DIAMETER_KIND["RBS_CURVE_DIAMETER_PARAM"] == "modelled"
    assert H.DIAMETER_KIND["RBS_PIPE_DIAMETER_PARAM"] == "nominal"
    assert H.DIAMETER_KIND["RBS_PIPE_OUTER_DIAMETER"] == "outer"
    assert H.DIAMETER_KIND["RBS_CONDUIT_DIAMETER_PARAM"] == "nominal"


def test_r3_census_counts_the_nominal_only_elements():
    """Отчёт обязан НАЗВАТЬ, у скольких трасс наружного диаметра не нашлось:
    без этого числа «капсул мало» неотличимо от «труб мало»."""
    els = [{"element_id": "1", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
            "params": {"RBS_PIPE_DIAMETER_PARAM": 100.0},
            "bbox_min_mm": [-58, -58, -58], "bbox_max_mm": [1058, 58, 58]}]
    snap = S.build_from_elements(els, origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert sec["nominal_only_total"] == 1
    assert sec["nominal_only_by_category"] == {"OST_PipeCurves": 1}


# ── R4 P0: изоляция и футеровка — тело есть, оболочки нет ни у кого ─────────

@pytest.mark.parametrize("cat", ["OST_PipeInsulations", "OST_DuctInsulations",
                                 "OST_DuctLinings", "OST_DuctCurvesInsulation",
                                 "OST_FabricationPipeworkInsulation"])
def test_r4_insulation_is_a_body_with_a_hull(cat):
    """ДУ20 (наружный 26.9) + 50 мм изоляции: оболочка трубы покрывает 4.5 %
    площади препятствия. Изоляция — отдельный элемент со своим габаритом;
    честнее взять её тело, чем поверить в толщину."""
    assert cat in H.KIND_TABLE, f"{cat} нет в закрытой таблице"
    rule = H.KIND_TABLE[cat]
    assert rule.eligible and rule.mvp_side == "mep"
    el = {"element_id": "i", "category": cat,
          "bbox_min_mm": [0, -63.45, -63.45], "bbox_max_mm": [1000, 63.45, 63.45]}
    rec, ref = H.build_hull(el)
    assert rec is not None, ref
    assert rec.grade == "coarse"


def test_r4_insulated_pipe_pair_is_found_through_the_insulation():
    """Стена в 40 мм от оси ДУ20: тело трубы её не задевает, изоляция — да."""
    wall = {"element_id": "w", "category": "OST_Walls",
            "bbox_min_mm": [200, 40, -500], "bbox_max_mm": [800, 240, 500]}
    pipe = {"element_id": "p", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
            "params": {"RBS_PIPE_OUTER_DIAMETER": 26.9},
            "bbox_min_mm": [-14, -14, -14], "bbox_max_mm": [1014, 14, 14]}
    ins = {"element_id": "i", "category": "OST_PipeInsulations",
           "bbox_min_mm": [0, -63.45, -63.45], "bbox_max_mm": [1000, 63.45, 63.45]}
    snap = S.build_from_elements([wall, pipe], origin={"run_dir": "t"})
    assert not D.detect(snap)["findings"], "тело трубы не должно доставать стену"
    snap2 = S.build_from_elements([wall, pipe, ins], origin={"run_dir": "t"})
    ids = {f["finding_id"] for f in D.detect(snap2)["findings"]}
    assert "i~w" in ids, "препятствие из изоляции не найдено"


# ── R2 P0: фитинги — 46 % трассы без оболочки ──────────────────────────────

@pytest.mark.parametrize("cat", ["OST_PipeFitting", "OST_DuctFitting",
                                 "OST_CableTrayFitting", "OST_ConduitFitting",
                                 "OST_PipeAccessory", "OST_DuctAccessory",
                                 "OST_DuctTerminal", "OST_Sprinklers"])
def test_r2_fittings_are_in_the_table_with_the_mep_side(cat):
    """`sklnk_eom_r26_v8`: лотков 75, фитингов лотка 64 — 46.0 % трассы по
    числу элементов не имело оболочки ВООБЩЕ, и это ровно углы и ответвления,
    где трасса шире прямого участка."""
    assert cat in H.KIND_TABLE, f"{cat} уходит в kind_outside_table"
    rule = H.KIND_TABLE[cat]
    assert rule.eligible and rule.mvp_side == "mep", cat
    assert rule.sources == H.SOURCES_BBOX, "у фитинга нет доказанной оси"
    el = {"element_id": "f", "category": cat,
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [300, 300, 300]}
    rec, ref = H.build_hull(el)
    assert rec is not None and rec.grade == "coarse", ref


def test_r2_report_names_the_share_of_the_run_without_a_hull():
    """Сегодня это число из отчёта получить нельзя вовсе."""
    els = [{"element_id": "1", "category": "OST_CableTray",
            "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
            "params": {"RBS_CABLETRAY_WIDTH_PARAM": 200.0,
                       "RBS_CABLETRAY_HEIGHT_PARAM": 100.0},
            "bbox_min_mm": [-10, -110, -60], "bbox_max_mm": [1010, 110, 60]},
           {"element_id": "2", "category": "OST_CableTrayFitting",
            "bbox_min_mm": [1000, -110, -60], "bbox_max_mm": [1200, 110, 60]}]
    rep = D.detect(S.build_from_elements(els, origin={"run_dir": "t"}))
    mep = rep["census"]["mvp_side_coverage"]["mep"]
    assert mep["eligible"] == 2 and mep["hulled"] == 2


# ── R5 P0: элементы без габарита — перепись считает, поиск не видит ─────────

def test_r5_a_missing_hull_on_an_mvp_side_makes_the_report_say_it_is_incomplete():
    """783 невидимых элемента (15.66 % фасада v14), а отчёт выглядел исправным.
    Стена, которой нет в поиске, — гарантированный пропуск всего, что сквозь
    неё проходит. Отчёт обязан это СКАЗАТЬ, а не спрятать в строку переписи."""
    els = [{"element_id": "w", "category": "OST_Walls",
            "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
            "params": {"WALL_ATTR_WIDTH_PARAM": 200.0}},          # bbox нет
           {"element_id": "p", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
            "params": {"RBS_PIPE_OUTER_DIAMETER": 114.3},
            "bbox_min_mm": [-58, -58, -58], "bbox_max_mm": [1058, 58, 58]}]
    rep = D.detect(S.build_from_elements(els, origin={"run_dir": "t"}))
    comp = rep["search"]["completeness"]
    assert comp["complete"] is False
    assert comp["incomplete_axes"] == ["geometry"]
    assert comp["axes"]["geometry"]["complete"] is False
    assert comp["axes"]["extraction"]["complete"] is True
    assert comp["axes"]["federation"]["complete"] is True
    assert comp["axes"]["query_scope"]["complete"] is True
    assert comp["without_hull_on_mvp_side"] == 1
    assert comp["by_category"]["OST_Walls"] == 1
    md = D.to_markdown(rep)
    assert "ПОИСК НЕПОЛОН" in md


def test_r5_a_complete_search_says_so_too():
    """Симметрия: полнота обязана быть УТВЕРЖДЕНИЕМ, а не молчанием."""
    els = [{"element_id": "w", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]
    rep = D.detect(S.build_from_elements(els, origin={"run_dir": "t"}),
                   pair_filter=D.any_physical_pair_filter)
    comp = rep["search"]["completeness"]
    assert comp["complete"] is True
    assert comp["incomplete_axes"] == []
    assert all(axis["complete"] for axis in comp["axes"].values())


def test_r5_completeness_vector_does_not_hide_extraction_or_federation_gaps():
    """A perfect host hull census cannot certify rows that never entered L0
    or linked geometry that was discovered but never transformed/scored."""
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [10, 10, 10]}],
        origin={"run_dir": "t", "links_in_l0": 3})
    snap.census.outside_extraction_scope = 7
    # ДВЕ РАЗНЫЕ ВЕЛИЧИНЫ, И ТЕПЕРЬ ОНИ РАЗВЕДЕНЫ (правка слияния 11.08.2026).
    # Здесь стояло только `linked_elements_unscored = 3`, и полнота решалась
    # по нему — что было верно, пока поле держало ЧИСЛО СВЯЗЕЙ. Поле исправлено
    # и держит ЭЛЕМЕНТЫ, поэтому три связи и число элементов за ними заданы
    # ОТДЕЛЬНО: 3 связи, 12 000 элементов. Если бы полнота по-прежнему читала
    # сумму, здание с выгруженными связями (сумма 0) объявило бы себя полным.
    snap.census.linked_elements_unscored = 12_000
    snap.census.links_without_element_count = 1

    comp = D.detect(snap)["search"]["completeness"]
    assert comp["axes"]["geometry"]["complete"] is True
    assert comp["axes"]["extraction"]["complete"] is False
    assert comp["axes"]["extraction"]["outside_extraction_scope"] == 7
    assert comp["axes"]["federation"]["complete"] is False
    assert comp["axes"]["federation"]["links_in_l0"] == 3
    assert comp["axes"]["federation"]["linked_elements_unscored"] == 12_000
    assert comp["axes"]["federation"]["links_without_element_count"] == 1
    assert comp["incomplete_axes"] == ["extraction", "federation"]
    assert comp["complete"] is False
    with pytest.raises(S.SnapshotIntegrityError,
                       match="extraction.*federation"):
        D.detect(snap, require_complete=True)


def test_r5_query_scope_and_all_physical_geometry_are_independent_axes():
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [10, 10, 10]},
         {"element_id": "u", "category": "OST_UnknownPhysical",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [10, 10, 10]}],
        origin={"run_dir": "t"})

    comp = D.completeness_of(
        snap, scope_id="all_physical_diagnostic", candidate_pairs=1,
        narrow_evaluations=1, narrow_refusals={"narrow_unsupported": 1})
    assert comp["axes"]["geometry"]["complete"] is False
    assert comp["axes"]["geometry"]["without_hull"] == 1
    assert comp["axes"]["query_scope"]["complete"] is False
    assert comp["axes"]["query_scope"]["refused_pairs"] == 1
    assert comp["incomplete_axes"] == ["geometry", "query_scope"]
    # Compatibility is intentionally conservative: it cannot remain green
    # when either new axis is red.
    assert comp["complete"] is False


def test_r5_a_narrow_refusal_makes_the_serialized_query_axis_incomplete(
        monkeypatch):
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [100, 100, 100]},
         {"element_id": "p", "category": "OST_PipeCurves",
          "bbox_min_mm": [40, 40, 40], "bbox_max_mm": [60, 60, 60]}],
        origin={"run_dir": "t"})
    monkeypatch.setattr(
        D, "evaluate_with_reason",
        lambda *args, **kwargs: (None, "forced_narrow_refusal"))

    comp = D.detect(snap)["search"]["completeness"]
    query = comp["axes"]["query_scope"]
    assert query["evaluation_status"] == "incomplete"
    assert query["candidate_pairs"] == query["narrow_evaluations"] == 1
    assert query["narrow_refusals"] == {"forced_narrow_refusal": 1}
    assert comp["incomplete_axes"] == ["query_scope"]
    assert comp["complete"] is False
    with pytest.raises(S.SnapshotIntegrityError, match="query_scope"):
        D.detect(snap, require_complete=True)


def test_r5_require_complete_turns_the_warning_into_a_refusal():
    """Вызывающий, которому нужен полный поиск, обязан иметь способ этого
    ПОТРЕБОВАТЬ — иначе предупреждение прочитают глазами и забудут."""
    els = [{"element_id": "w", "category": "OST_Walls",
            "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0], "params": {}}]
    snap = S.build_from_elements(els, origin={"run_dir": "t"})
    with pytest.raises(S.SnapshotIntegrityError, match="неполон"):
        D.detect(snap, pair_filter=D.any_physical_pair_filter, require_complete=True)


@pytest.mark.skipif(not (LIVE / "sob62_fas_r23_v14").exists(),
                    reason="живой декомпайл только на прод-боксе")
def test_r5_live_v14_diagnosis_is_null_bbox_not_a_broken_extractor():
    """Диагноз, а не догадка: у всех 291 стены без габарита `geom_kind` =
    `curve` и ОСЬ на месте, а `bbox_min_mm` — `null`. То есть
    `get_BoundingBox(null)` вернул null (RevitAPI.xml допускает это прямо),
    экстрактор отработал верно, и чинить надо не его.

    Ни design option, ни фаза их не отличают (замерено: у всех 783 элементов
    без габарита те же значения, что у 2 622 с габаритом).
    """
    d = LIVE / "sob62_fas_r23_v14"
    no_bbox = []
    for line in (d / "L0.jsonl").open(encoding="utf-8"):
        line = line.strip()
        if not line or '"OST_Walls"' not in line:
            continue
        row = json.loads(line)
        if row.get("record") != "element":
            continue
        el = row["element"]
        if el.get("category") == "OST_Walls" and el.get("bbox_min_mm") is None:
            no_bbox.append(el)
    assert len(no_bbox) == 291
    assert all(e.get("geom_kind") == "curve" for e in no_bbox)
    assert all(e.get("p0_mm") and e.get("p1_mm") for e in no_bbox)
    assert all(e.get("design_option") is None for e in no_bbox)
    assert sum(1 for e in no_bbox
               if "WALL_ATTR_WIDTH_PARAM" in (e.get("params") or {})) == 215


# ── Дыра arc_chord_polyline: формула стрелки вне области применимости ───────

def _sample_arc_pts(arc: dict, n: int = 600):
    c, r = arc["center_mm"], arc["radius_mm"]
    a0, a1 = arc["start_angle_rad"], arc["end_angle_rad"]
    xa, ya = arc["x_axis"], arc["y_axis"]
    out = []
    for i in range(n + 1):
        t = a0 + (a1 - a0) * (i / n)
        out.append(tuple(c[k] + r * (math.cos(t) * xa[k] + math.sin(t) * ya[k])
                         for k in range(3)))
    return out


@pytest.mark.parametrize("span_deg", [30, 179, 181, 270, 359, 360, 361, 540,
                                      700, 715, 720, 721, 730, 900, 1080, 1440])
def test_arc_polyline_contains_the_arc_at_every_span(span_deg):
    """Закрытие дыры, найденной сверкой с чек-листом пар BHoM.

    `r*(1-cos(span/2n))` — стрелка суб-хорды, и формула верна только пока
    суб-дуга не больше π. При размахе около чётного кратного 2π условие
    `sag <= порог` проходило ЛОЖНО при n=1 (cos(2π)=1 даёт sag=0), дуга
    заменялась ОДНОЙ хордой, и тело уходило из оболочки на 5 900 мм при
    r=3000. Правка: число хорд снизу ограничено `ceil(span/π)`, то есть
    суб-дуга НИКОГДА не больше π, и формула применяется только там, где верна.
    """
    arc = {"center_mm": [0.0, 0.0, 0.0], "radius_mm": 3000.0,
           "start_angle_rad": 0.0, "end_angle_rad": math.radians(span_deg),
           "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0]}
    p0 = (3000.0, 0.0, 0.0)
    p1 = (3000.0 * math.cos(math.radians(span_deg)),
          3000.0 * math.sin(math.radians(span_deg)), 0.0)
    pts, sag = H.arc_chord_polyline(arc, p0, p1)
    hull = G.Capsule(tuple(pts), 100.0 + sag)
    for p in _sample_arc_pts(arc):
        assert G.contains_point(hull, p), (span_deg, p, sag)


def test_arc_polyline_sub_arc_never_exceeds_pi():
    """Закон, а не совпадение: суб-дуга обязана быть <= π по построению."""
    for span_deg in (1, 180, 360, 720, 1440, 2000):
        arc = {"center_mm": [0.0, 0.0, 0.0], "radius_mm": 1000.0,
               "start_angle_rad": 0.0, "end_angle_rad": math.radians(span_deg),
               "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0]}
        pts, _ = H.arc_chord_polyline(arc, (1000.0, 0.0, 0.0), (0.0, 1000.0, 0.0))
        n = len(pts) - 1
        assert n >= math.ceil(math.radians(span_deg) / math.pi) - 1e-9, span_deg


# ── KEY_REF: ось стены лежит на ГРАНИ у 213 из 215 кандидатов v18 ──────────

def test_wall_axis_halfwidth_covers_every_location_line():
    """Сторона смещения при location line = грань в L0 НЕ снята: знать, куда
    именно смещено тело, нельзя. Но содержать его обязаны при любом ответе —
    значит полуширина берётся такой, чтобы накрыть обе стороны."""
    assert H.wall_axis_halfwidth(200.0, 0) == pytest.approx(100.0)   # осевая
    for key_ref in (1, 2, 3, 4, 5, None, 99):
        assert H.wall_axis_halfwidth(200.0, key_ref) == pytest.approx(200.0), key_ref


def test_wall_axis_halfwidth_is_conservative_for_a_face_located_wall():
    """Тело стены, ось которой лежит на грани, целиком по одну сторону оси."""
    hw = H.wall_axis_halfwidth(200.0, 3)
    pr = H.hull_from_wall_axis((0, 0, 0), (5000, 0, 0), width_mm=2 * hw,
                               z0=0.0, z1=3000.0)
    for off in (0.0, 200.0, -200.0):        # тело может быть слева ИЛИ справа
        assert G.contains_point(pr, (2500.0, off, 1500.0)), off


# ── Дубликаты: два элемента на одном месте — диагностика, а не шум ─────────

def test_coincident_duplicates_are_their_own_finding_class():
    """Замер v19: пары 8206221/9202566 и 8214960/9192099 несут ОДНУ ось и
    один габарит — это два элемента на одном месте. Заказчику такая находка
    нужна отдельно: дубликат чинится удалением, а не раздвиганием.

    Признак структурный: совпадение оболочек с точностью до численного шума.
    Никаких имён типов — правило работает на любой модели.
    """
    a = {"element_id": "1", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]}
    b = {"element_id": "2", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]}
    rep = D.detect(S.build_from_elements([a, b], origin={"run_dir": "t"}),
                   pair_filter=D.any_physical_pair_filter)
    f = rep["findings"][0]
    assert f["pair_kind"] == "coincident_duplicate"
    assert rep["pair_kind_counts"]["coincident_duplicate"] == 1


def test_a_normal_overlap_is_not_called_a_duplicate():
    """Обратная сторона: обычное пересечение дубликатом не объявляется."""
    a = {"element_id": "1", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]}
    b = {"element_id": "2", "category": "OST_Walls",
         "bbox_min_mm": [100, 0, 0], "bbox_max_mm": [5000, 200, 3000]}
    rep = D.detect(S.build_from_elements([a, b], origin={"run_dir": "t"}),
                   pair_filter=D.any_physical_pair_filter)
    assert rep["findings"][0]["pair_kind"] == "interference"


# ── ГАБАРИТ НЕ ДОКАЗЫВАЕТ СОВПАДЕНИЯ (09.08): совет удалял живой элемент ────

def _pipe_el(eid: str, p0, p1, r=200.0, cat="OST_PipeCurves") -> dict:
    xs, ys, zs = (p0[0], p1[0]), (p0[1], p1[1]), (p0[2], p1[2])
    return {"element_id": eid, "category": cat,
            "p0_mm": list(p0), "p1_mm": list(p1),
            "section_radius_mm": r, "section_round": True,
            "bbox_min_mm": [min(xs) - r, min(ys) - r, min(zs) - r],
            "bbox_max_mm": [max(xs) + r, max(ys) + r, max(zs) + r]}


def _floor_el(eid: str, loop, z0=0.0, z1=200.0) -> tuple[dict, dict]:
    xs = [p[0] for p in loop]
    ys = [p[1] for p in loop]
    return ({"element_id": eid, "category": "OST_Floors",
             "bbox_min_mm": [min(xs), min(ys), z0],
             "bbox_max_mm": [max(xs), max(ys), z1]},
            {"profile_available": True,
             "exterior_loop": [list(p) for p in loop], "holes": []})


def test_two_diagonals_of_a_square_are_not_a_duplicate():
    """Два РАЗНЫХ элемента с одним габаритом. Воспроизведено 09.08:

        Capsule((0,0,0)→(4000,4000,0), r=200)  bounds ((-200,-200,-200),(4200,4200,200))
        Capsule((4000,0,0)→(0,4000,0), r=200)  bounds ((-200,-200,-200),(4200,4200,200))
        pair_kind: coincident_duplicate

    Габарит у диагоналей квадрата ОДИН, а тела разные, и совет обзора при
    этом читался «чинится удалением одного из них» с серьёзностью «критично».
    Выполнить его — удалить настоящую трубу.

    Ось у этих оболочек ЕСТЬ (`hull_source: axis_section`), то есть выдумывать
    ничего не надо: две капсулы с разными осями — не дубликат.
    """
    snap = S.build_from_elements(
        [_pipe_el("1", (0, 0, 0), (4000, 4000, 0)),
         _pipe_el("2", (4000, 0, 0), (0, 4000, 0))],
        origin={"run_dir": "t"})
    a, b = snap.records
    assert a.bounds() == b.bounds(), "воспроизведение: габариты обязаны совпасть"
    assert D.pair_kind_of(a, b) == "interference"
    rep = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    f = rep["findings"][0]
    assert f["pair_kind"] == "interference", f
    assert rep["pair_kind_counts"].get("coincident_duplicate", 0) == 0


def test_two_halves_of_a_square_floor_are_not_a_duplicate():
    """То же самое подошвой, а не осью: два треугольных перекрытия — половинки
    одного квадрата. Габарит общий, подошвы разные, соприкасаются по диагонали.
    Призма несёт подошву, значит доказательство есть и здесь."""
    t1 = [(0, 0), (4000, 0), (4000, 4000)]
    t2 = [(0, 0), (0, 4000), (4000, 4000)]
    e1, p1 = _floor_el("1", t1)
    e2, p2 = _floor_el("2", t2)
    snap = S.build_from_elements([e1, e2], origin={"run_dir": "t"},
                                 profiles={"1": p1, "2": p2})
    a, b = snap.records
    assert a.bounds() == b.bounds()
    assert D.pair_kind_of(a, b) == "interference"


def test_the_same_pipe_twice_is_still_a_duplicate():
    """Не регрессия в обратную сторону: одна ось, один радиус — дубликат,
    и обход оси в другую сторону тела не меняет."""
    snap = S.build_from_elements(
        [_pipe_el("1", (0, 0, 0), (5000, 0, 0), r=100.0),
         _pipe_el("2", (0, 0, 0), (5000, 0, 0), r=100.0),
         _pipe_el("3", (5000, 0, 0), (0, 0, 0), r=100.0)],
        origin={"run_dir": "t"})
    rep = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    assert rep["pair_kind_counts"]["coincident_duplicate"] == 3, rep["findings"]


def test_a_capsule_against_a_bare_box_stays_a_suspicion():
    """Тройственный ответ `hulls_coincide` не смеет схлопнуться в двоичный.

    У трубы 1 сечение прочитано — оболочка капсула; у трубы 2 сечения нет —
    оболочка габаритный бокс, ровно тот же. Это НЕ доказательство совпадения
    (`None`, а не `False`), поэтому находка остаётся дубликатом-подозрением;
    и это НЕ доказательство различия, поэтому терять её нельзя.
    """
    a = _pipe_el("1", (0, 0, 0), (5000, 0, 0), r=100.0)
    b = {"element_id": "2", "category": "OST_PipeCurves",
         "bbox_min_mm": a["bbox_min_mm"], "bbox_max_mm": a["bbox_max_mm"]}
    snap = S.build_from_elements([a, b], origin={"run_dir": "t"})
    ra, rb = snap.records
    assert (ra.hull_source, rb.hull_source) == ("axis_section", "bbox")
    assert D.hulls_coincide(ra, rb) is None
    rep = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    f = rep["findings"][0]
    assert f["pair_kind"] == "coincident_duplicate"
    assert f["hull_grade"] == "coarse"
    assert D.duplicate_claim_is_proven(f) is False


def test_a_thicker_pipe_on_the_same_axis_is_not_a_duplicate():
    """Радиус — часть тела: та же ось, другое сечение — разные трубы. Габариты
    у них разные, так что это ещё и проверка, что ворота габарита на месте."""
    snap = S.build_from_elements(
        [_pipe_el("1", (0, 0, 0), (5000, 0, 0), r=100.0),
         _pipe_el("2", (0, 0, 0), (5000, 0, 0), r=150.0)],
        origin={"run_dir": "t"})
    a, b = snap.records
    assert D.pair_kind_of(a, b) == "interference"
