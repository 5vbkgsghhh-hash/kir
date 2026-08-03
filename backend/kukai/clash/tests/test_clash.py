"""Детектор, который «нашёл 0 клешей», неотличим от детектора, который не искал.

Это тот же гудхарт, что похоронил evaluator-judge, и защита от него здесь не
одна проверка, а весь набор: перепись обязана сходиться, широкая фаза обязана
быть НАДМНОЖЕСТВОМ полного перебора, оболочка обязана содержать элемент, а
отчёт — быть байт-в-байт воспроизводимым. Каждый пункт критерия завершения D1
(§8.1 канона) имеет здесь свой тест.

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

BACKEND = pathlib.Path(__file__).resolve().parents[3]
FACADE = BACKEND / "backend" / "data" / "decompile" / "sob62_fas_r23_v10"


# ── (в) геометрия: то, что ревью объявило неверным ──────────────────────────

def test_a_slanted_segment_is_not_clashed_by_independent_xy_and_z():
    """Контрпример ревью №12 дословно.

    Отрезок (-2,0,-2)→(2,0,2) имеет XY-пересечение с узкой призмой около x=0,
    а нужный слой z=[0.9,1.1] проходит при x≈1: независимые минимумы по XY и по
    Z оба нулевые, хотя общей точки нет. Клэмп-по-z объявил бы клеш.
    """
    prism = G.Prism(((-0.1, -1.0), (0.1, -1.0), (0.1, 1.0), (-0.1, 1.0)), 0.9, 1.1)
    sd = G.seg_prism_signed_distance((-2, 0, -2), (2, 0, 2), prism)
    assert sd > 0, "наклонная труба объявлена пересекающей то, чего не касается"


def test_a_slanted_segment_through_a_prism_is_found():
    """Обратная сторона: тот же отрезок и призма НА его пути — клеш обязан
    быть, иначе первый тест закрывался бы детектором, который молчит всегда."""
    prism = G.Prism(((0.9, -1.0), (1.1, -1.0), (1.1, 1.0), (0.9, 1.0)), 0.9, 1.1)
    sd = G.seg_prism_signed_distance((-2, 0, -2), (2, 0, 2), prism)
    assert sd < 0


@pytest.mark.parametrize("seed", range(12))
def test_segment_prism_sign_agrees_with_dense_sampling(seed):
    """Знак — против плотной выборки точек отрезка. Численный эталон, который
    не знает нашей формулы."""
    rnd = random.Random(seed)
    prism = G.Prism(((0.0, 0.0), (3.0, 0.0), (3.0, 2.0), (0.0, 2.0)),
                    0.0, 2.0)
    s0 = tuple(rnd.uniform(-4, 6) for _ in range(3))
    s1 = tuple(rnd.uniform(-4, 6) for _ in range(3))
    sd = G.seg_prism_signed_distance(s0, s1, prism)
    inside = any(G._point_in_prism(
        tuple(s0[k] + (s1[k] - s0[k]) * (i / 4000) for k in range(3)), prism)
        for i in range(4001))
    assert (sd < 0) == inside, (sd, inside, s0, s1)


def test_prism_distance_is_the_product_metric():
    """Призма — декартово произведение подошвы на интервал, поэтому расстояние
    раскладывается: hypot(зазор по XY, зазор по Z), а не минимум из двух."""
    a = G.Prism(((0, 0), (1, 0), (1, 1), (0, 1)), 0, 1)
    b = G.Prism(((4, 0), (5, 0), (5, 1), (4, 1)), 4, 5)
    assert G.signed_distance(a, b) == pytest.approx(math.hypot(3, 3))


def test_zero_length_and_degenerate_segments_do_not_lie():
    """Труба нулевой длины — это точка, а не ошибка деления."""
    p = G.Capsule(((0, 0, 0), (0, 0, 0)), 50.0)
    q = G.Capsule(((0, 0, 80), (0, 0, 80)), 20.0)
    assert G.signed_distance(p, q) == pytest.approx(10.0)
    near = G.Capsule(((0, 0, 60), (0, 0, 60)), 20.0)
    assert G.signed_distance(p, near) < 0


def test_separating_translation_moves_a_and_leaves_b_alone():
    """Перенос всегда означает движение A при неподвижном B (ревью №13) —
    иначе знак вектора невозможно прочитать. Имя «MTV» снято ревью №6: вектор
    сертифицирован разводящим, а не минимальным."""
    a = G.Prism(((0, 0), (2, 0), (2, 2), (0, 2)), 0, 2)
    b = G.Prism(((1, 0), (3, 0), (3, 2), (1, 2)), 0, 2)
    v = G.certified_separating_translation(a, b)
    assert v is not None
    moved = G.Prism(tuple((x + v[0], y + v[1]) for x, y in a.footprint),
                    a.z0 + v[2], a.z1 + v[2])
    assert G.signed_distance(moved, b) >= -1e-6, "перенос не вывел A из проникания"


def test_no_negative_zero_survives_serialization():
    assert G._norm_zero(-0.0) == 0.0
    assert math.copysign(1.0, G._norm_zero(-0.0)) > 0


# ── (г) adversarial-корпус: оболочка обязана СОДЕРЖАТЬ элемент ──────────────

def _sample_arc(arc: dict, n: int = 400) -> list[G.Pt3]:
    c = arc["center_mm"]
    r = arc["radius_mm"]
    a0, a1 = arc["start_angle_rad"], arc["end_angle_rad"]
    xa, ya = arc["x_axis"], arc["y_axis"]
    out = []
    for i in range(n + 1):
        t = a0 + (a1 - a0) * (i / n)
        out.append(tuple(c[k] + r * (math.cos(t) * xa[k] + math.sin(t) * ya[k])
                         for k in range(3)))
    return out


@pytest.mark.parametrize("span_deg", [30, 179, 181, 270, 359])
def test_an_arc_hull_contains_the_arc_including_spans_over_pi(span_deg):
    """Дуги больше π — отдельный пункт критерия завершения. Ломаная строится
    по стрелке, и оболочка обязана накрыть исходную дугу целиком."""
    arc = {"center_mm": [0.0, 0.0, 0.0], "radius_mm": 3000.0,
           "start_angle_rad": 0.0,
           "end_angle_rad": math.radians(span_deg),
           "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0]}
    pts, sag = H.arc_chord_polyline(arc, (3000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    hull = G.Capsule(tuple(pts), 100.0 + sag)
    for p in _sample_arc(arc):
        assert G.contains_point(hull, p), (span_deg, p, sag)


def test_a_concave_floor_contour_is_widened_not_dropped():
    """Вогнутый контур обязан стать ВЫПУКЛЫМ: SAT неприменим к вогнутому, а
    расширение наружу законно по закону консервативности — и обязано накрыть
    исходные вершины."""
    concave = [[0, 0], [10000, 0], [10000, 10000], [5000, 4000], [0, 10000]]
    pr = H.hull_from_profile(concave, 0.0, 200.0)
    assert pr is not None
    for x, y in concave:
        assert G.contains_point(pr, (float(x), float(y), 100.0))


def test_a_hull_from_bbox_contains_the_whole_bbox():
    el = {"element_id": "1", "category": "OST_Walls",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1000, 200, 3000]}
    rec, ref = H.build_hull(el)
    assert ref is None and rec.grade == "coarse"
    for corner in ((0, 0, 0), (1000, 200, 3000), (500, 100, 1500)):
        assert G.contains_point(rec.hull, corner)


def test_a_giant_hull_is_compared_against_everything():
    """Гигант, задевающий больше ячеек, чем стоит раскладывать, уходит в
    отдельный список — но НЕ выпадает из сравнения (иначе ложный пропуск)."""
    giant = _rec("giant", G.Aabb((-1e6, -1e6, -1e6), (1e6, 1e6, 1e6)), side="struct")
    small = _rec("small", G.Aabb((0, 0, 0), (10, 10, 10)), side="mep")
    recs = [giant, small]
    grid = D.build_grid(recs, cell=1.0)
    assert grid.stats["oversized_hulls"] >= 1
    assert (0, 1) in D.candidate_pairs(recs, grid, pair_filter=D.mvp_pair_filter)


def _rec(sid: str, hull: G.Hull, *, side: str | None = "struct",
         grade: str = "coarse", label: str = "x") -> H.HullRecord:
    return H.HullRecord(source_id=sid, category="OST_Walls", label=label,
                        mvp_side=side, hull=hull, grade=grade,
                        hull_source="bbox")


# ── (в) property широкой фазы: кандидаты ⊇ полный перебор ───────────────────

def _random_scene(rnd: random.Random, n: int) -> list[H.HullRecord]:
    recs = []
    for i in range(n):
        kind = rnd.choice(("box", "prism", "capsule"))
        x, y, z = (rnd.uniform(-5000, 5000) for _ in range(3))
        if kind == "box":
            d = [rnd.uniform(10, 4000) for _ in range(3)]
            hull = G.Aabb((x, y, z), (x + d[0], y + d[1], z + d[2]))
        elif kind == "prism":
            k = rnd.randint(3, 6)
            pts = [(x + rnd.uniform(-2000, 2000), y + rnd.uniform(-2000, 2000))
                   for _ in range(k)]
            fp = G.convex_footprint(pts)
            if len(fp) < 3:
                continue
            hull = G.Prism(fp, z, z + rnd.uniform(10, 3000))
        else:
            hull = G.Capsule(((x, y, z),
                              (x + rnd.uniform(-4000, 4000),
                               y + rnd.uniform(-4000, 4000),
                               z + rnd.uniform(-4000, 4000))),
                             rnd.uniform(10, 400))
        recs.append(_rec(f"e{i:04d}", hull,
                         side="mep" if i % 2 else "struct"))
    return recs


@pytest.mark.parametrize("seed", range(8))
def test_broad_phase_is_a_superset_of_brute_force(seed):
    """Ключевой property-тест §8.1(в). Сетка вправе давать лишних кандидатов
    (их отсеет узкая фаза), но НЕ вправе терять пары."""
    rnd = random.Random(seed)
    recs = _random_scene(rnd, 90)
    grid = D.build_grid(recs)
    cand = set(D.candidate_pairs(recs, grid, pair_filter=D.mvp_pair_filter))
    brute = set(D.brute_pairs(recs, pair_filter=D.mvp_pair_filter))
    assert brute <= cand, sorted(brute - cand)[:5]


@pytest.mark.parametrize("cell", [1.0, 37.0, 1000.0, 1e6])
def test_broad_phase_holds_for_any_cell_size(cell):
    """Размер ячейки — параметр производительности, а не корректности."""
    rnd = random.Random(99)
    recs = _random_scene(rnd, 60)
    grid = D.build_grid(recs, cell=cell)
    cand = set(D.candidate_pairs(recs, grid, pair_filter=D.mvp_pair_filter))
    assert set(D.brute_pairs(recs, pair_filter=D.mvp_pair_filter)) <= cand


def test_broad_phase_survives_an_adversarial_scene():
    """Наклонные, гиганты, нулевые длины и эксцентричные профили — в одной
    сцене, потому что по одному они уже проходили."""
    recs = [
        _rec("slant", G.Capsule(((-9000, 0, -9000), (9000, 0, 9000)), 60.0), side="mep"),
        _rec("zero", G.Capsule(((0, 0, 0), (0, 0, 0)), 25.0), side="mep"),
        _rec("giant", G.Aabb((-1e5, -1e5, -1e5), (1e5, 1e5, 1e5))),
        _rec("thin", G.Prism(((0, 0), (12000, 0), (12000, 1), (0, 1)), 0, 3000)),
        _rec("ecc", G.Prism(((5000, 5000), (5040, 5000), (5040, 9000),
                             (5000, 9000)), -2000, 12000)),
        _rec("far", G.Aabb((1e4, 1e4, 1e4), (1e4 + 5, 1e4 + 5, 1e4 + 5)), side="mep"),
    ]
    grid = D.build_grid(recs)
    cand = set(D.candidate_pairs(recs, grid, pair_filter=D.mvp_pair_filter))
    assert set(D.brute_pairs(recs, pair_filter=D.mvp_pair_filter)) <= cand


# ── (б) перепись: ни один класс не выпадает молча ───────────────────────────

def test_the_census_balances_by_construction():
    els = [
        {"element_id": "1", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]},
        {"element_id": "2", "category": "OST_Grids"},                 # датум
        {"element_id": "3", "category": "OST_Nonsense",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]},         # вне таблицы
        {"element_id": "4", "category": "OST_Walls"},                 # без геометрии
    ]
    snap = S.build_from_elements(els, origin={})
    t = snap.census.totals()
    assert snap.census.balanced()
    assert t == {"eligible": 3, "hulled": 1, "unsupported": 1,
                 "missing_geometry": 1, "not_eligible": 1,
                 # Ревью №10: то, что вообще не дошло до потока, тоже число.
                 "outside_extraction_scope": 0, "linked_elements_unscored": 0}


def test_an_unknown_category_is_named_not_dropped():
    """Молчаливое выпадение класса запрещено законом переписи §18."""
    snap = S.build_from_elements(
        [{"element_id": "9", "category": "OST_BrandNewThing",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}], origin={})
    assert snap.census.unsupported["OST_BrandNewThing"] == 1
    assert snap.refusals[0].reason == "kind_outside_table"


def test_datums_are_not_eligible_and_do_not_pollute_the_denominator():
    """Ось и уровень не имеют тела: считать их «непокрытыми» значило бы вечно
    держать перепись несошедшейся и приучить себя её не читать."""
    snap = S.build_from_elements(
        [{"element_id": "g", "category": "OST_Grids"},
         {"element_id": "l", "category": "OST_Levels"}], origin={})
    assert snap.census.totals()["eligible"] == 0
    assert snap.census.totals()["not_eligible"] == 2


# ── (а) закрытая матрица ────────────────────────────────────────────────────

def test_the_coverage_matrix_is_closed_and_complete():
    rows = H.coverage_matrix()
    assert len(rows) == len(H.KIND_TABLE)
    for row in rows:
        assert row["category"] in H.KIND_TABLE
        if row["eligible"]:
            assert row["hull_sources"], row
        else:
            assert row["refusal"], row


def test_every_mvp_side_is_one_of_the_two_named_sides():
    for cat, rule in H.KIND_TABLE.items():
        assert rule.mvp_side in (None, *H.MVP_PAIR), cat
        if rule.mvp_side is not None:
            assert rule.eligible, f"{cat}: сторона MVP без права на оболочку"


# ── вердикты и грейды ───────────────────────────────────────────────────────

def test_a_coarse_pair_is_never_confirmed_and_never_publishes_a_translation():
    """Ревью №14: пересечение габаритных боксов не доказывает ни клеша, ни
    направления ремонта."""
    a = _rec("a", G.Aabb((0, 0, 0), (100, 100, 100)), side="mep")
    b = _rec("b", G.Aabb((50, 50, 50), (150, 150, 150)), side="struct")
    f = D.evaluate(a, b)
    assert f is not None and f.hull_grade == "coarse"
    assert f.verdict == "possible"
    assert f.certified_separating_translation_mm is None


def test_an_exact_pair_is_confirmed():
    """`exact` ставится только оболочке, совпадающей с телом. Ревью №4 сняло
    этот грейд у капсулы, поэтому здесь он задан РУКАМИ: тест сторожит правило
    вердикта, а не право капсулы называться точной."""
    a = _rec("a", G.Capsule(((0, 0, 0), (1000, 0, 0)), 50.0),
             side="mep", grade="exact", label="pipe")
    b = _rec("b", G.Prism(((400, -500), (600, -500), (600, 500), (400, 500)),
                          -500, 500), side="struct", grade="exact", label="wall")
    f = D.evaluate(a, b)
    assert f is not None and f.verdict == "confirmed"
    assert f.hull_overlap_depth_mm > 0
    assert f.certified_separating_translation_mm is not None


def test_touching_within_the_grade_tolerance_is_reported_but_not_ranked():
    """ПЕРЕПИСАН по ревью №14. Прежнее поведение — «мелкое перекрытие внутри
    допуска грейда не находка» — глушило доказанные пересечения: три FN на
    живом фасаде пришли ровно отсюда, а 25 мм никогда не были доказанной
    погрешностью AABB.

    Теперь отношение оболочек публикуется всегда, а допуск живёт отдельной
    осью РАНЖИРОВАНИЯ (`ranking_significant`), которая ничего не скрывает.
    """
    a = _rec("a", G.Aabb((0, 0, 0), (100, 100, 100)), side="mep")
    b = _rec("b", G.Aabb((100 - H.TOL_GRADE_MM["coarse"] / 2, 0, 0),
                         (200, 100, 100)), side="struct")
    f = D.evaluate(a, b)
    assert f is not None, "мелкое перекрытие проглочено — это и был ложный пропуск"
    assert f.hull_relation == "overlap"
    assert f.ranking_significant is False


def test_clearance_is_not_applied_twice():
    """Ревью №13: суммарная дилатация обязана равняться ровно `clearance`."""
    a = _rec("a", G.Aabb((0, 0, 0), (100, 100, 100)), side="mep", grade="exact")
    b = _rec("b", G.Aabb((160, 0, 0), (260, 100, 100)), side="struct", grade="exact")
    assert D.evaluate(a, b, clearance_mm=50.0) is None
    f = D.evaluate(a, b, clearance_mm=80.0)
    assert f is not None and f.clearance_deficit_mm == pytest.approx(20.0)
    assert f.hull_overlap_depth_mm == 0.0
    assert f.hull_relation == "separated"       # зазор нарушен, но тела врозь


def test_the_pair_class_is_an_unordered_key():
    """`wall~mullion` и `mullion~wall` — один класс; иначе одно число отчёта
    делится пополам по случайному признаку (кто раньше по id)."""
    a = _rec("2", G.Aabb((0, 0, 0), (100, 100, 100)), side="mep",
             label="pipe", grade="exact")
    b = _rec("1", G.Aabb((50, 50, 50), (150, 150, 150)), side="struct",
             label="wall", grade="exact")
    f1 = D.evaluate(a, b)
    f2 = D.evaluate(b, a)
    assert f1.pair_class == f2.pair_class == "pipe~wall"
    assert f1.finding_id == f2.finding_id, "id находки зависит от порядка аргументов"


# ── (д) канонический голден и детерминизм ───────────────────────────────────

def _tiny_snapshot() -> S.ClashGeometrySnapshot:
    els = [
        {"element_id": "100", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [6000, 200, 3000],
         "level_id": "L1", "type_name": "Кирпич 250"},
        {"element_id": "200", "category": "OST_PipeCurves",
         "bbox_min_mm": [2900, -500, 1400], "bbox_max_mm": [3100, 700, 1600],
         "level_id": "L1", "type_name": "Сталь 100"},
        {"element_id": "300", "category": "OST_Grids"},
    ]
    return S.build_from_elements(els, origin={"run_dir": "golden", "l0_sha": "0"})


#: Исторический эталон clash-report/1. Живёт как ВХОД миграционного теста
#: (ревью №14): схему нельзя сохранить байт-в-байт, добавив факт, но читать
#: собственную историю измерений обязаны. Актуальный эталон — v2 в fixtures/,
#: и пишет его только генератор `kukai.clash.tools.make_fixtures` (ревью №17).
GOLDEN_V1 = (BACKEND / "kukai" / "clash" / "tests" / "golden_report.json")


def test_the_report_is_byte_identical_across_runs():
    a = D.dumps(D.detect(_tiny_snapshot()))
    b = D.dumps(D.detect(_tiny_snapshot()))
    assert a == b


def test_pairs_in_scope_aggregate_equals_brute_force():
    """Контракт агрегата: pair_filter детерминирован классом записи.

    Замер приёмки 28.07: попарный счётчик на демо-башне (~50k оболочек)
    = ~1.25e9 вызовов фильтра, детектор не дожил до ответа. Агрегат по
    классам обязан давать ТО ЖЕ число, что полный перебор."""
    import random
    rng = random.Random(287)
    cats = ["OST_PipeCurves", "OST_Walls", "OST_Floors", "OST_DuctCurves",
            "OST_CableTray", "OST_StructuralColumns", "OST_Doors"]
    els = []
    for i in range(120):
        c = rng.choice(cats)
        x, y, z = (rng.uniform(0, 30000) for _ in range(3))
        els.append({"element_id": str(1000 + i), "category": c,
                    "bbox_min_mm": [x, y, z],
                    "bbox_max_mm": [x + 400, y + 400, z + 400],
                    "level_id": "L1", "type_name": "t"})
    snap = S.build_from_elements(els, origin={"run_dir": "agg", "l0_sha": "0"})
    recs = snap.records
    for pf in (D.mvp_pair_filter, D.any_physical_pair_filter):
        brute = sum(1 for i in range(len(recs))
                    for j in range(i + 1, len(recs)) if pf(recs[i], recs[j]))
        got = D.detect(snap, pair_filter=pf)["search"]["pairs_in_scope"]
        assert got == brute, (pf.__name__, got, brute)


def test_the_canon_contains_no_wall_clock():
    """Канон — функция входа. Приёмка 28.07: голден агента нёс тайминги
    (0.1 мс), прогон лида дал 0.0 — байт-в-байт ломался самим построением.
    Телеметрия живёт в подчёркнутых ключах и в канон не сериализуется."""
    rep = D.detect(_tiny_snapshot())
    assert "_timings_ms" in rep            # телеметрия не потеряна
    canon = json.loads(D.dumps(rep))
    assert not any(k.startswith("_") for k in canon)
    assert "ms" not in canon["search"]


def test_the_canonical_golden_does_not_move():
    """Голден — не украшение: без него любое изменение формулы проходит молча.

    Ревью №17: отсутствие эталона — ОШИБКА, а не повод его записать. Тест,
    который сам создаёт то, с чем сверяется, зелен при любой поломке. Запись
    живёт в отдельном генераторе `kukai.clash.tools.make_fixtures`, а сцена
    покрывает все виды пар и отношений, а не одну грубую AABB.
    """
    from kukai.clash.tools.make_fixtures import golden_scene

    golden = (BACKEND / "kukai" / "clash" / "tests" / "fixtures"
              / "golden_report_v2.json")
    assert golden.exists(), (
        "эталон отсутствует — перегенерировать руками: "
        "PYTHONPATH=. venv/bin/python -m kukai.clash.tools.make_fixtures")
    got = D.dumps(D.detect(golden_scene()))
    assert got == golden.read_text(encoding="utf-8").strip()


def test_the_serialization_refuses_nan_and_normalizes_zero():
    rep = D.detect(_tiny_snapshot())
    text = D.dumps(rep)
    assert "NaN" not in text and "-0.0" not in text
    assert json.loads(text)["schema_version"] == D.REPORT_SCHEMA


# ── (ж) привязка к происхождению ────────────────────────────────────────────

def test_the_report_carries_the_fingerprint_of_what_it_judged():
    """Отчёт без SHA источника нельзя ни воспроизвести, ни опровергнуть."""
    snap = _tiny_snapshot()
    snap.origin["revision"] = {"fingerprint": "31587:dd:96"}
    rep = D.detect(snap)
    assert rep["origin"]["l0_sha"] == "0"
    assert rep["origin"]["revision"]["fingerprint"] == "31587:dd:96"
    assert rep["census"]["balanced"] is True


# ── (е) бенч сетки и реальный фасад ─────────────────────────────────────────

@pytest.mark.skipif(not FACADE.exists(), reason="нет артефактов декомпайла")
def test_the_real_facade_balances_and_the_grid_pays_for_itself():
    snap = S.build_from_decompile(FACADE)
    assert snap.census.balanced()
    assert snap.census.totals()["hulled"] > 2000
    rep = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    s = rep["search"]
    assert s["candidate_pairs"] < s["pairs_in_scope"] / 50, s
    assert s["grid"]["max_bucket"] < 500
    # Детектор обязан ДОКАЗАТЬ, что искал: на реальном фасаде он что-то нашёл.
    assert rep["findings"], "ноль находок на 2754 оболочках — поиск не шёл"


@pytest.mark.skipif(not FACADE.exists(), reason="нет артефактов декомпайла")
def test_the_facade_has_no_mvp_pairs_and_says_so_instead_of_pretending():
    """Фасадная модель не содержит ни одной категории MEP — значит пар MVP в
    ней ноль. Это факт данных, и отчёт обязан показать его счётчиками, а не
    пустым списком находок без объяснения."""
    snap = S.build_from_decompile(FACADE)
    assert not [r for r in snap.records if r.mvp_side == "mep"]
    rep = D.detect(snap)
    assert rep["search"]["pairs_in_scope"] == 0
    assert rep["search"]["scope_id"] == "mvp_v2"
    assert rep["findings"] == []
    assert rep["census"]["totals"]["hulled"] > 2000


@pytest.mark.skipif(not FACADE.exists(), reason="нет артефактов декомпайла")
def test_the_facade_publishes_the_gap_between_the_model_and_the_stream():
    """Ревью №10, живой замер: header census = 30 489 элементов, а element-строк
    в потоке 3 153. Разница 27 336 НЕ обязана быть пригодной к поиску — но
    обязана быть напечатана числом, иначе знаменатель любого процента покрытия
    не доказан. Форма census (список {key,count} внутри document) замерена на
    этом самом артефакте, а не предположена."""
    snap = S.build_from_decompile(FACADE)
    assert snap.origin["header_census_total"] == 30489
    assert snap.origin["elements_in_l0"] == 3153
    assert snap.census.outside_extraction_scope == 27336
    assert snap.origin["links_in_l0"] == 8
    assert snap.census.linked_elements_unscored == 8
    j = snap.join_manifest()
    assert j["eligible"] == j["scored"] + j["not_scored"]
    assert j["l1_join"] == "absent"
