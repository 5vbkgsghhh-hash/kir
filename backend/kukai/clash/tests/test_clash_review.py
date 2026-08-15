"""Контрпримеры ревью кодекса (18 находок) — по одному на находку.

Дисциплина волны: КАЖДАЯ находка сначала воспроизводится тестом, который падает
на текущем коде, и только потом чинится. Тест, который не удалось сделать
красным, — не находка, а гипотеза; такие помечены здесь явно и названы в отчёте.

Нумерация тестов = нумерация находок ревью. Файл отдельный от `test_clash.py`
намеренно: те 57 тестов были зелёными при всех воспроизведённых ниже дефектах
(находка №18), и смешивать доказательство их недостаточности с ними самими —
значит терять улику.

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

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
#: Реальный декомпайл на диске прод-бокса. Тесты НЕ зависят от его наличия —
#: фикстура ниже извлечена из него и лежит в репозитории (находка №18: gate из
#: чистого checkout, без skipif).
LIVE_RUN = (pathlib.Path(__file__).resolve().parents[3]
            / "backend" / "data" / "decompile" / "sob62_fas_r23_v11")


def floor_9981227() -> tuple[dict, dict]:
    fx = json.loads((FIXTURES / "floor_9981227_v11.json").read_text(encoding="utf-8"))
    return fx["element"], fx["profile"]


# ── №1 P0: профиль с дугой строит оболочку, не содержащую элемент ───────────

def test_01_arc_profile_hull_must_contain_the_arc_bulge():
    """Живой контрпример: пол 9981227, ребро №5 внешнего контура — ДУГА.

    `hull_from_profile` овыпукляет только вершины и заменяет дугу хордой.
    Замер до правки: середина дуги (-287.168, 26565.404) лежит на 752.832 мм
    СНАРУЖИ «conservative» оболочки. Это прямое нарушение закона
    консервативности — оболочка обязана СОДЕРЖАТЬ элемент.
    """
    el, prof = floor_9981227()
    rec, ref = H.build_hull(el, profile=prof)
    assert rec is not None, ref
    zc = (el["bbox_min_mm"][2] + el["bbox_max_mm"][2]) / 2.0
    for loop_i, kinds in enumerate(prof["curve_kinds"]):
        for edge_i, kind in enumerate(kinds):
            if kind != "arc":
                continue
            mid = prof["arc_midpoints"][loop_i][edge_i]
            if mid is None:
                continue
            pt = (float(mid[0]), float(mid[1]), zc)
            assert G.contains_point(rec.hull, pt), (
                f"середина дуги {loop_i}/{edge_i} вне оболочки "
                f"({rec.hull_source}/{rec.grade})")


def test_01b_arc_profile_is_bounded_outward_not_dropped():
    """ВОЛНА DECOMPOSE отменяет откат в bbox — но только вместе с ДОКАЗАТЕЛЬСТВОМ.

    Прежняя правка D1 отправляла дуговой контур в габаритный бокс, и причина
    была названа честно: «доказанной наружной аппроксимации дуги у нас нет».
    Теперь она есть, и это не формулировка, а конструкция: дуга не больше
    полуокружности целиком лежит в прямоугольнике «хорда × стрелка наружу»
    (`hulls._arc_outward_rect`), а стрелка берётся из `arc_midpoints` разбора,
    а не из константы.

    Тест поэтому проверяет не «какой источник победил», а ТО ЖЕ САМОЕ, что и
    №1, — закон консервативности, — и вдобавок требует, чтобы величина
    огрубления была ОПУБЛИКОВАНА. Оболочка, ставшая тоньше молча, ничем не
    лучше оболочки, ставшей тоньше неправомерно.
    """
    el, prof = floor_9981227()
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "profile" and rec.grade == "conservative"
    slack = rec.extra.get("arc_outward_slack_mm")
    assert slack is not None and slack > 0.0, (
        "раздутие наружу обязано быть названо числом: без него «наружная "
        "аппроксимация» — обещание, а не замер")
    # Ровно та величина, которой ревью №1 измерило нарушение: середина дуги
    # лежала на 752.832 мм снаружи хордовой оболочки. Стрелка обязана её
    # накрыть — иначе прямоугольник не содержит дугу.
    assert slack >= 752.832


def test_01f_the_bbox_clip_may_never_cut_the_declared_contour():
    """Обрезка накладок обязана резать НАКЛАДКИ, а не объявленную область.

    Живой контрпример (`snowdon_plumb_v5`, пол 1424071, замер 10.08.2026):
    контур доходит до x = 974.73, габарит элемента — только до x = −1854.20.
    Обрезка по габариту ЭЛЕМЕНТА срезала 21.13 % объявленной области, и проба
    вложенности увидела 95 точек контура вне оболочки. Это пропуск клеша, а не
    неточность, поэтому границей служит габарит САМОЙ области.

    Здесь то же самое в мелком масштабе: квадрат с одной дугой и заведомо
    ВРУЩИМ габаритом элемента, обрезающим половину контура.
    """
    prof = {"profile_available": True,
            "exterior_loop": [[0, 0], [100, 0], [100, 100], [0, 100]],
            "curve_kinds": [["arc", "line", "line", "line"]],
            "arc_midpoints": [[[50, -20], None, None, None]], "holes": []}
    el = {"element_id": "c", "category": "OST_Floors",
          # габарит ВРЁТ: он вдвое уже контура
          "bbox_min_mm": [0, -20, 0], "bbox_max_mm": [50, 100, 10]}
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "profile"
    for x, y in ((0, 0), (100, 0), (100, 100), (0, 100), (50, -20), (99, 99)):
        assert G.contains_point(rec.hull, (float(x), float(y), 5.0)), (
            f"объявленная точка ({x},{y}) вырезана обрезкой")
    zc = (el["bbox_min_mm"][2] + el["bbox_max_mm"][2]) / 2.0
    for loop in [prof["exterior_loop"]] + list(prof.get("holes") or []):
        for p in loop:
            assert G.contains_point(rec.hull, (float(p[0]), float(p[1]), zc)), (
                "объявленная вершина контура вне оболочки")


def test_01d_a_curve_we_cannot_bound_still_falls_back():
    """Замок не открыт настежь: неограничиваемая кривая по-прежнему в bbox.

    Дуга получила наружную оболочку ПОТОМУ, что для неё есть доказательство.
    У сплайна его нет, и он обязан вести себя ровно как дуга до этой волны.
    """
    el = {"element_id": "s", "category": "OST_Floors",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [10, 10, 1]}
    prof = {"profile_available": True,
            "exterior_loop": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "curve_kinds": [["line", "hermite_spline", "line", "line"]],
            "arc_midpoints": [[None, None, None, None]], "holes": []}
    assert H.profile_refusal(prof) == "profile_curve_hermite_spline"
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "bbox" and rec.grade == "coarse"


def test_01e_half_circle_arc_is_refused_not_guessed():
    """Формула наружного прямоугольника верна только до полуокружности.

    За этой границей проекция дуги вылезает за торцы хорды, и прямоугольник её
    больше не содержит. Здесь обязан быть ОТКАЗ, а не формула вне области
    применимости — та же болезнь, что чинил `arc_chord_polyline` для span > π.
    """
    # Полуокружность радиуса 5: хорда 10, стрелка 5 = L/2.
    prof = {"profile_available": True,
            "exterior_loop": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "curve_kinds": [["arc", "line", "line", "line"]],
            "arc_midpoints": [[[5, -5], None, None, None]], "holes": []}
    assert H.profile_refusal(prof) is None, "дуга сама по себе больше не отказ"
    reg = H.profile_loops(prof)
    assert reg.reason == "profile_arc_over_half_circle"
    assert reg.loops == () and reg.arc_patches == ()
    el = {"element_id": "h", "category": "OST_Floors",
          "bbox_min_mm": [0, -5, 0], "bbox_max_mm": [10, 10, 1]}
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "bbox", "неограничиваемая дуга обязана уронить контур"
    assert "profile_arc_over_half_circle" in (rec.extra.get("downgraded_from") or [])


def test_01c_invalid_profile_vertex_is_not_silently_dropped():
    """Строки 188–190: невалидная вершина молча выбрасывалась, уменьшая
    оболочку. Молчаливое уменьшение — тот же класс лжи, что и дуга."""
    el = {"element_id": "x", "category": "OST_Floors",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [10, 10, 1]}
    prof = {"profile_available": True,
            "exterior_loop": [[0, 0], [10, 0], [10, 10], [float("nan"), 3]],
            "curve_kinds": [["line", "line", "line", "line"]],
            "arc_midpoints": [[None, None, None, None]], "holes": []}
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "bbox", "невалидная вершина не уронила профиль в bbox"


@pytest.mark.skipif(not LIVE_RUN.exists(), reason="живой декомпайл только на прод-боксе")
def test_01d_fixture_matches_the_live_artifact():
    """Фикстура не смеет разойтись с артефактом, из которого извлечена."""
    el_fx, prof_fx = floor_9981227()
    sk = json.loads((LIVE_RUN / "sketch.index.json").read_text(encoding="utf-8"))
    assert sk["profile_index"]["9981227"] == prof_fx
    for line in (LIVE_RUN / "L0.jsonl").open(encoding="utf-8"):
        if '"9981227"' in line:
            r = json.loads(line)
            if r.get("record") == "element" and str(r["element"]["element_id"]) == "9981227":
                assert r["element"] == el_fx
                return
    pytest.fail("элемент 9981227 исчез из живого L0")


# ── №2/№3 P0: билдеры стены и эксцентричных осей — ОЖИДАНИЯ, не правка ──────

def test_02_wall_never_reaches_the_axis_capsule_branch():
    """Находка №2: капсула радиуса width/2 вокруг НИЖНЕЙ оси не покрывает
    высоту стены — при подключении ground эта ветка стала бы неконсервативной.

    Волна билдера не строит (директива), поэтому дыра закрыта ЗАПРЕТОМ: стене
    источник `axis_section` не разрешён таблицей, и даже если сечение придёт,
    оболочкой останется габарит. Здесь проверяется именно запрет, а не то, что
    сечения сегодня нет: посылка «спасает отсутствие данных» — не защита.
    """
    assert "axis_section" not in H.KIND_TABLE["OST_Walls"].sources
    el = {"element_id": "w", "category": "OST_Walls",
          "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
          "section_radius_mm": 100.0,          # сечение ЕСТЬ — и всё равно bbox
          "bbox_min_mm": [-100, -100, 0], "bbox_max_mm": [5100, 100, 3000]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "bbox"
    assert G.contains_point(rec.hull, (2500.0, 0.0, 2900.0)), "верх стены вне оболочки"


@pytest.mark.xfail(strict=True,
                   reason="blocked-on-ground-sections: wall-builder (полоса вокруг "
                          "оси с учётом location-line offset × [z0,z1]) — отдельная "
                          "волна. Сегодня стена честна, но груба: габарит вместо "
                          "тела. Тест обязан покраснеть в тот день, когда билдер "
                          "появится, и его надо будет снять с xfail.")
def test_02b_wall_hull_is_still_only_a_bounding_box():
    """Ожидание на будущее: у стены появится оболочка ТОЧНЕЕ габарита."""
    el = {"element_id": "w", "category": "OST_Walls",
          "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0], "section_radius_mm": 100.0,
          "bbox_min_mm": [-100, -100, 0], "bbox_max_mm": [5100, 100, 3000]}
    rec, _ = H.build_hull(el)
    assert rec.grade != "coarse", "оболочка стены всё ещё габаритный бокс"


def test_03_flex_curves_never_reach_the_chord_branch():
    """Находка №3: `spline_unsupported` превращался в хорду p0→p1 без стрелки —
    прямой путь к ложному пропуску на гибкой трассе. Закрыто тем же запретом:
    гибким трассам ось не разрешена, пока не захвачена настоящая кривая."""
    for cat in ("OST_FlexPipeCurves", "OST_FlexDuctCurves"):
        assert "axis_section" not in H.KIND_TABLE[cat].sources, cat
    el = {"element_id": "f", "category": "OST_FlexPipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0], "section_radius_mm": 50.0,
          "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [1050, 400, 50]}
    curve = {"curve_kind": "spline_unsupported", "p0_mm": [0, 0, 0],
             "p1_mm": [1000, 0, 0]}
    rec, _ = H.build_hull(el, curve=curve)
    assert rec.hull_source == "bbox"
    # Реальный прогиб гибкой трубы к середине пролёта: 350 мм вбок — габарит
    # его содержит, хорда бы не содержала.
    assert G.contains_point(rec.hull, (500.0, 350.0, 0.0)), "прогиб вне оболочки"


@pytest.mark.xfail(strict=True,
                   reason="blocked-on-ground-sections: category-specific dispatch "
                          "(доказанная дуга / spline / эксцентриситет балки) — "
                          "отдельная волна.")
def test_03b_eccentric_and_curved_classes_still_have_no_own_builder():
    """Ожидание на будущее: у балки и гибкой трассы появятся свои билдеры."""
    assert "axis_section" in H.KIND_TABLE["OST_StructuralFraming"].sources


# ── №4 P0: грейд `exact` выдаётся оболочкам, которые точными не являются ────

def test_04_capsule_is_never_exact():
    """Прямая капсула имеет СФЕРИЧЕСКИЕ торцы, труба — плоские; дуговая
    капсула раздута стрелкой. Ни то ни другое не `exact`, а `exact` — это
    `confirmed` в вердикте, то есть ложное обвинение."""
    el = {"element_id": "p", "category": "OST_PipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
          "section_radius_mm": 50.0, "section_round": True,
          "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [1050, 50, 50]}
    rec, _ = H.build_hull(el)
    assert rec.grade == "conservative", "капсула объявлена точной оболочкой"


def test_04b_zero_length_axis_is_a_typed_refusal_not_a_sphere():
    """Нулевая длина оси делала СФЕРУ радиуса сечения — тело, которого в
    модели нет."""
    el = {"element_id": "p0", "category": "OST_PipeCurves",
          "p0_mm": [10, 10, 10], "p1_mm": [10, 10, 10],
          "section_radius_mm": 50.0,
          "bbox_min_mm": [-40, -40, -40], "bbox_max_mm": [60, 60, 60]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "bbox", "нулевая ось построила капсулу-сферу"


def test_04c_invalid_arc_does_not_become_a_point_at_origin():
    """Невалидная дуга возвращала `[p0, p1]`, а при отсутствии p0/p1 —
    `(0,0,0)`: оболочка в начале координат, за километры от элемента."""
    el = {"element_id": "a", "category": "OST_PipeCurves",
          "section_radius_mm": 50.0,
          "bbox_min_mm": [9000, 9000, 0], "bbox_max_mm": [9100, 9100, 100]}
    curve = {"curve_kind": "arc", "arc": {"radius_mm": None}}
    rec, ref = H.build_hull(el, curve=curve)
    assert rec is not None
    assert rec.hull_source == "bbox", "битая дуга построила капсулу"
    lo, hi = rec.hull.bounds()
    assert lo[0] >= 8000, "оболочка уехала в начало координат"


# ── №5 P0: MTV капсула×капсула по серединам сегментов не разводит пару ──────

def test_05_capsule_capsule_mtv_actually_separates():
    """Контрпример ревью дословно: A(0,0,0)→(10,0,0) r=1, B(9,1,-5)→(9,1,5) r=1.

    Было: sd=-1, mtv=(-0.9701,-0.2425,0), после переноса sd=-0.7575 — пара
    осталась в проникании, то есть «минимальный вектор разведения» не разводит.
    """
    a = G.Capsule(((0, 0, 0), (10, 0, 0)), 1.0)
    b = G.Capsule(((9, 1, -5), (9, 1, 5)), 1.0)
    v = G.certified_separating_translation(a, b)
    assert v is not None
    moved = G.Capsule(tuple(tuple(p[i] + v[i] for i in range(3)) for p in a.path), a.radius)
    assert G.signed_distance(moved, b) >= -1e-6, (
        f"перенос {v} оставил проникание {G.signed_distance(moved, b)}")


@pytest.mark.parametrize("case", [
    ("identical", ((0, 0, 0), (10, 0, 0)), ((0, 0, 0), (10, 0, 0))),
    ("collinear", ((0, 0, 0), (10, 0, 0)), ((5, 0, 0), (15, 0, 0))),
    ("crossing_same_centre", ((-5, 0, 0), (5, 0, 0)), ((0, -5, 0), (0, 5, 0))),
    ("degenerate_points", ((1, 1, 1), (1, 1, 1)), ((1, 1, 1), (1, 1, 1))),
])
def test_05b_degenerate_axes_get_a_vector_or_a_named_reason(case):
    """При совпадающих/коллинеарных/пересекающихся осях направление было
    `None` молча. Молчание неотличимо от «не проникают»: нужен либо
    детерминированный вектор, либо НАЗВАННАЯ причина его отсутствия."""
    _, pa, pb = case
    a, b = G.Capsule(pa, 1.0), G.Capsule(pb, 1.0)
    assert G.signed_distance(a, b) < 0
    v = G.certified_separating_translation(a, b)
    if v is None:
        assert G.mtv_unavailable_reason(a, b), "None без названной причины"
    else:
        moved = G.Capsule(tuple(tuple(p[i] + v[i] for i in range(3)) for p in a.path),
                          a.radius)
        assert G.signed_distance(moved, b) >= -1e-6


def test_05c_separating_translation_postcondition_property():
    """Свойство: `перенос != None ⇒ после него sd >= -eps`.

    Без `skip` намеренно (находка №18): пропущенный тест в приёмочной цели
    неотличим от отсутствующего. Непроникающие пары не выбрасываются, а
    считаются, и тест требует, чтобы проникающих было достаточно много —
    иначе «свойство выполнено» означало бы «проверять было нечего».
    """
    rnd = random.Random(20260728)
    checked = 0
    for _ in range(400):
        def rp():
            return tuple(rnd.uniform(-6, 6) for _ in range(3))

        a = G.Capsule((rp(), rp()), rnd.uniform(0.2, 2.0))
        b = G.Capsule((rp(), rp()), rnd.uniform(0.2, 2.0))
        if G.signed_distance(a, b) >= 0:
            continue
        checked += 1
        v = G.certified_separating_translation(a, b)
        if v is None:
            assert G.mtv_unavailable_reason(a, b), "None без названной причины"
            continue
        moved = G.Capsule(tuple(tuple(p[i] + v[i] for i in range(3))
                                for p in a.path), a.radius)
        assert G.signed_distance(moved, b) >= -1e-6, (a, b, v)
    assert checked >= 50, f"проникающих пар всего {checked} — свойство не нагружено"


# ── №6 P0: «MTV» капсула×призма не минимален и не является penetration ──────

def test_06_capsule_prism_translation_is_certified_not_minimal():
    """Контрпример: диагональная капсула (-100,-100,-100)→(100,100,100) r=1 и
    куб [0,10]³. Face-based ответ имел длину 101 при достаточных ~8.07.

    D1 не строит GJK/EPA — поэтому поле ПЕРЕИМЕНОВАНО: оно обещает разведение,
    а не минимальность. Здесь проверяется ровно обещание.
    """
    cap = G.Capsule(((-100, -100, -100), (100, 100, 100)), 1.0)
    box = G.Aabb((0, 0, 0), (10, 10, 10))
    v = G.certified_separating_translation(cap, box)
    assert v is not None
    moved = G.Capsule(tuple(tuple(p[i] + v[i] for i in range(3)) for p in cap.path),
                      cap.radius)
    assert G.signed_distance(moved, box) >= -1e-6


def test_06b_penetration_field_is_named_hull_overlap_depth():
    """`physical_penetration_mm` обещало глубину проникания ТЕЛ, а несло
    `-sd` ОБОЛОЧЕК (находка №6 + №14). Имя обязано говорить правду."""
    a = H.HullRecord("1", "OST_PipeCurves", "pipe", "mep",
                     G.Aabb((0, 0, 0), (10, 10, 10)), "coarse", "bbox")
    b = H.HullRecord("2", "OST_Walls", "wall", "struct",
                     G.Aabb((5, 5, 5), (20, 20, 20)), "coarse", "bbox")
    f = D.evaluate(a, b)
    assert f is not None
    d = f.as_dict()
    assert "hull_overlap_depth_mm" in d
    assert "physical_penetration_mm" not in d
    assert "certified_separating_translation_mm" in d
    assert "mtv_mm" not in d


# ── №7 P1: расстояние призма×призма — нижняя оценка (операторская проверка) ─

def test_07_prism_gap_is_a_lower_bound_and_says_so():
    """Оператор проверил лично: перестановочная нестабильность НЕ
    воспроизвелась (все циклические повороты дают 1.0). Остаётся вторая
    половина находки — 1.0 против истинного √5: это НИЖНЯЯ оценка, и при
    clearance>0 она даёт лишние находки, а не пропуски.

    Чинится не формулой, а честным именем поля в отчёте.
    """
    a = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    b = ((2.0, 2.0), (3.0, 2.0), (3.0, 3.0), (2.0, 3.0))
    gap = G.poly_poly_gap(a, b)
    true = math.hypot(1.0, 1.0)
    assert gap <= true + 1e-9, "оценка ВЫШЕ истинной — это был бы пропуск"
    rotations = {round(G.poly_poly_gap(a[i:] + a[:i], b), 9) for i in range(4)}
    assert len(rotations) == 1, f"перестановочная нестабильность: {rotations}"


def test_07b_separation_distance_is_published_as_a_lower_bound():
    """Отчёт обязан назвать эту величину нижней оценкой, а не расстоянием."""
    assert "lower_bound" in D.SEPARATION_SEMANTICS


# ── №8 P2: EPS размерно неверен — знак ломается на коротких сегментах ───────

def test_08_short_segment_keeps_its_sign():
    """Контрпример ревью: сегмент длиной 0.0005 мм, точка на 0.0001 мм внутри
    радиуса. Квадрат длины (2.5e-7) сравнивался с EPS_MM=1e-6 и сегмент
    объявлялся точкой."""
    p0, p1 = (0.0, 0.0, 0.0), (0.0005, 0.0, 0.0)
    d = G.seg_seg_distance(p0, p1, (0.00025, 0.0001, 0.0), (0.00025, 0.0001, 0.0))
    assert d == pytest.approx(0.0001, abs=1e-9), d


@pytest.mark.parametrize("scale", [1e-6, 1e-3, 1.0, 1e3, 1e6])
def test_08b_sign_is_scale_invariant(scale):
    """Одна сцена, промасштабированная на 12 порядков: знак обязан выжить."""
    a = G.Capsule(((0.0, 0.0, 0.0), (10.0 * scale, 0.0, 0.0)), 1.0 * scale)
    b = G.Capsule(((5.0 * scale, 2.5 * scale, 0.0),
                   (5.0 * scale, 9.0 * scale, 0.0)), 1.0 * scale)
    sd = G.signed_distance(a, b)
    assert sd > 0, sd
    assert sd / scale == pytest.approx(0.5, rel=1e-6)


# ── №9 P0: положительный clearance теряется в широкой фазе ─────────────────

def test_09_positive_clearance_survives_the_grid():
    """Контрпример ревью дословно: cell=10, боксы x=[8,9] и [10.1,11],
    clearance=2. Полный перебор даёт пару, сетка давала []."""
    recs = [
        H.HullRecord("a", "OST_PipeCurves", "pipe", "mep",
                     G.Aabb((8.0, 0.0, 0.0), (9.0, 1.0, 1.0)), "coarse", "bbox"),
        H.HullRecord("b", "OST_Walls", "wall", "struct",
                     G.Aabb((10.1, 0.0, 0.0), (11.0, 1.0, 1.0)), "coarse", "bbox"),
    ]
    grid = D.build_grid(recs, 10.0, slack=2.0)
    got = D.candidate_pairs(recs, grid, slack=2.0)
    assert got == D.brute_pairs(recs, slack=2.0) == [(0, 1)]


def test_09c_a_grid_built_without_slack_refuses_a_slack_query():
    """Молчаливый ложный пропуск заменён громким отказом: сетка помнит, на
    какой зазор её раскладывали."""
    recs = [H.HullRecord("a", "OST_PipeCurves", "pipe", "mep",
                         G.Aabb((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), "coarse", "bbox")]
    with pytest.raises(ValueError):
        D.candidate_pairs(recs, D.build_grid(recs, 10.0), slack=5.0)


@pytest.mark.parametrize("seed", range(30))
def test_09b_broad_phase_is_a_superset_for_random_positive_slack(seed):
    """Свойство широкой фазы при slack>0, включая slack > размера ячейки."""
    rnd = random.Random(seed)
    recs = []
    for i in range(14):
        lo = tuple(rnd.uniform(-50, 50) for _ in range(3))
        hi = tuple(lo[k] + rnd.uniform(0.5, 12.0) for k in range(3))
        side = "mep" if i % 2 else "struct"
        recs.append(H.HullRecord(f"e{i}", "OST_PipeCurves" if side == "mep" else "OST_Walls",
                                 "pipe" if side == "mep" else "wall", side,
                                 G.Aabb(lo, hi), "coarse", "bbox"))
    cell = rnd.choice([3.0, 10.0, 40.0])
    slack = rnd.choice([0.5, 5.0, 25.0, 90.0])       # 90 > любой cell
    grid = D.build_grid(recs, cell, slack=slack)
    got = set(D.candidate_pairs(recs, grid, slack=slack))
    want = set(D.brute_pairs(recs, slack=slack))
    assert want <= got, f"пропущено {sorted(want - got)} при cell={cell} slack={slack}"


# ── №10 P0: баланс не доказывает закрытость модели ─────────────────────────

def _l0(tmp: pathlib.Path, *, footer: bool = True, census: int = 3,
        stream_complete: bool = True) -> pathlib.Path:
    """Синтетический L0 в ЗАМЕРЕННОЙ форме живого артефакта (SOB6.2 v10):
    census — список {key,count} внутри document, статус — во вложенном
    `status`, футер — element_count/category_count/stream_complete. Выдумывать
    форму входа значит проверять не тот формат, который приезжает."""
    d = tmp / "run"
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"record": "header", "schema_version": "1.0",
             "document": {"census": [{"key": "OST_Walls", "count": census,
                                      "name": "Стены"}],
                          "doc_name": "t", "change_stamp": "t"}}]
    for i in range(3):
        rows.append({"record": "element", "element": {
            "element_id": str(100 + i), "category": "OST_Walls",
            "bbox_min_mm": [i, 0, 0], "bbox_max_mm": [i + 1, 1, 1]}})
    rows.append({"record": "category_status",
                 "status": {"category": "OST_Walls", "expected_count": census,
                            "extracted_count": 3, "state": "complete",
                            "error": None}})
    if footer:
        rows.append({"record": "footer", "element_count": 3, "category_count": 1,
                     "link_count": 0, "stream_complete": stream_complete})
    (d / "L0.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return d


def test_10_truncated_l0_is_a_loud_refusal(tmp_path):
    """Файл, обрезанный на КОРРЕКТНОЙ json-строке до footer, давал внутренне
    сходящуюся перепись — то есть «всё в порядке» на половине здания."""
    d = _l0(tmp_path, footer=False)
    with pytest.raises(S.SnapshotIntegrityError):
        S.build_from_decompile(d)


def test_10b_header_census_gap_is_published_not_hidden(tmp_path):
    """На живом фасаде header census = 30 489, а element-строк 3 153. Разница
    не обязана быть eligible — но обязана быть НАЗВАНА, иначе знаменатель
    покрытия не доказан."""
    d = _l0(tmp_path, census=9)
    snap = S.build_from_decompile(d)
    assert snap.census.outside_extraction_scope == 6
    assert snap.origin["stream_complete"] is True


def test_10c_missing_category_status_is_a_refusal(tmp_path):
    """Мутант: удалить category_status — прогон обязан упасть громко."""
    d = _l0(tmp_path)
    p = d / "L0.jsonl"
    kept = [l for l in p.read_text(encoding="utf-8").splitlines()
            if '"category_status"' not in l]
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(S.SnapshotIntegrityError):
        S.build_from_decompile(d)


def test_10d_dropped_element_row_is_a_refusal(tmp_path):
    """Мутант: удалить одну element-строку — extracted_count перестаёт
    сходиться с фактом."""
    d = _l0(tmp_path)
    p = d / "L0.jsonl"
    kept = [l for l in p.read_text(encoding="utf-8").splitlines()
            if '"101"' not in l]
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(S.SnapshotIntegrityError):
        S.build_from_decompile(d)


# ── №11 P1: инвариант переписи не является воротами ────────────────────────

def test_11_detect_refuses_an_unbalanced_snapshot():
    """`detect()` продолжал работу на несошедшемся снапшоте."""
    snap = S.build_from_elements([], origin={"run_dir": "t"})
    snap.census.eligible["OST_Walls"] += 5          # искусственный перекос
    with pytest.raises(S.SnapshotIntegrityError):
        D.detect(snap)


def test_11b_duplicate_source_ids_are_refused():
    els = [{"element_id": "same", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]} for _ in range(2)]
    snap = S.build_from_elements(els, origin={"run_dir": "t"})
    with pytest.raises(S.SnapshotIntegrityError):
        snap.validate()


def test_11c_non_finite_hull_is_refused():
    els = [{"element_id": "n", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}]
    snap = S.build_from_elements(els, origin={"run_dir": "t"})
    snap.records[0].hull = G.Aabb((0.0, 0.0, 0.0), (float("inf"), 1.0, 1.0))
    with pytest.raises(S.SnapshotIntegrityError):
        snap.validate()


def test_11d_narrow_phase_refusal_is_counted_not_swallowed():
    """Нечисловая узкая фаза возвращала None молча — теперь это счётчик."""
    a = H.HullRecord("1", "OST_PipeCurves", "pipe", "mep",
                     G.Capsule((((0.0, 0.0, 0.0),)), 1.0), "coarse", "bbox")
    b = H.HullRecord("2", "OST_Walls", "wall", "struct",
                     G.Prism((), 0.0, 1.0), "coarse", "bbox")
    f, reason = D.evaluate_with_reason(a, b, clearance_mm=0.0)
    assert f is None and reason == "narrow_unsupported"


# ── №12 P1: «закрытая матрица» самосогласована, но не содержательна ────────

def test_12_category_manifest_is_frozen_and_counted():
    """Тест сравнивал `coverage_matrix()` с той же таблицей — одинаковая
    ошибка обеих сторон была зелёной. Теперь ожидание заморожено отдельно."""
    man = json.loads((FIXTURES / "category_manifest.json").read_text(encoding="utf-8"))
    assert len(H.KIND_TABLE) == man["row_count"]
    got = {row["category"]: row for row in H.coverage_matrix()}
    assert sorted(got) == sorted(man["rows"])
    for cat, exp in man["rows"].items():
        assert got[cat]["eligible"] == exp["eligible"]
        assert got[cat]["mvp_side"] == exp["mvp_side"]
        assert got[cat]["hull_sources"] == exp["hull_sources"], cat


def test_12b_manifest_rejects_a_new_category():
    """Мутант: добавить категорию — манифест обязан упасть."""
    man = json.loads((FIXTURES / "category_manifest.json").read_text(encoding="utf-8"))
    assert "OST_Parking" not in man["rows"], "манифест не заморожен"


def test_12c_furniture_may_not_claim_a_profile_source():
    """Каждая eligible-категория заявляла ВСЕ три источника. Мебель контура
    подошвы не имеет — заявлять его значит обещать точность, которой нет."""
    row = {r["category"]: r for r in H.coverage_matrix()}["OST_Furniture"]
    assert "profile" not in row["hull_sources"]


# ── №13 P0: область поиска и область оракула не идентифицируются ───────────

def test_13_scope_id_is_in_the_canon():
    snap = S.build_from_elements([], origin={"run_dir": "t"})
    rep = D.detect(snap, pair_filter=D.mvp_pair_filter)
    assert rep["search"]["scope_id"] == "mvp_v2"
    rep2 = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    assert rep2["search"]["scope_id"] == "all_physical_diagnostic"


def test_13b_markdown_does_not_claim_mvp_after_all_pairs():
    snap = S.build_from_elements([], origin={"run_dir": "t"})
    md = D.to_markdown(D.detect(snap, pair_filter=D.any_physical_pair_filter))
    assert "MVP" not in md or "all_physical_diagnostic" in md


def test_13c_unknown_pair_filter_is_refused():
    """Произвольный callable-фильтр делал область поиска неопределимой."""
    snap = S.build_from_elements([], origin={"run_dir": "t"})
    with pytest.raises(ValueError):
        D.detect(snap, pair_filter=lambda a, b: True)


# ── №14 P0: tol_grade прячет доказанные касания и мешает контакт с прониканием

def test_14_contact_is_reported_as_a_relation_not_swallowed():
    """При sd=0 находки не было даже у exact-пары: два тела, лежащие вплотную,
    объявлялись «ничем». Отношение и доказательность — разные оси."""
    a = H.HullRecord("1", "OST_PipeCurves", "pipe", "mep",
                     G.Aabb((0, 0, 0), (10, 10, 10)), "conservative", "axis_section")
    b = H.HullRecord("2", "OST_Walls", "wall", "struct",
                     G.Aabb((10, 0, 0), (20, 10, 10)), "conservative", "axis_section")
    f = D.evaluate(a, b)
    assert f is not None, "касание проглочено"
    assert f.as_dict()["hull_relation"] == "contact"
    assert f.verdict == "possible"


def test_14b_shallow_coarse_overlap_is_emitted_as_possible():
    """Пара coarse с sd=-1…-25 подавлялась порогом 25 мм, который никогда не
    был доказанной погрешностью AABB. Теперь 25 мм — только ранжирование."""
    a = H.HullRecord("1", "OST_PipeCurves", "pipe", "mep",
                     G.Aabb((0, 0, 0), (10, 10, 10)), "coarse", "bbox")
    b = H.HullRecord("2", "OST_Walls", "wall", "struct",
                     G.Aabb((9, 0, 0), (20, 10, 10)), "coarse", "bbox")
    f = D.evaluate(a, b)
    assert f is not None, "мелкое перекрытие габаритов проглочено"
    assert f.as_dict()["hull_relation"] == "overlap"
    assert f.verdict == "possible"


def test_14c_relation_axis_is_complete_and_verdict_has_no_touch():
    assert set(D.HULL_RELATIONS) == {"overlap", "contact", "separated"}
    assert "touch" not in D.VERDICTS


def test_14d_the_schema_is_versioned_and_every_past_version_still_reads():
    """ЗАКОН — ЧИТАЕМОСТЬ ИСТОРИИ, А НЕ НОМЕР (правка 11.08.2026).

    Здесь стояло `assert D.REPORT_SCHEMA == "clash-report/2"`, и тест стал
    ОКАМЕНЕЛОСТЬЮ: схема уехала на `/3` вместе с законченной лестницей
    миграции, а утверждение осталось от прежнего поведения. Проверять НОМЕР
    значит требовать, чтобы формат не развивался, — то есть ронять набор на
    каждом честном шаге вперёд и приучать чинить его переписыванием числа.

    Ревью №14 требовало другого: добавив факт, канон нельзя сохранить
    байт-в-байт — его надо ВЕРСИОНИРОВАТЬ И УМЕТЬ ЧИТАТЬ ИСТОРИЮ. Это и
    проверяется: версия объявлена, каждая прошлая версия принимается
    миграцией, а чужая — отвергается громко.
    """
    assert D.REPORT_SCHEMA.startswith("clash-report/")
    for past in ("clash-report/1", "clash-report/2"):
        migrated = D.migrate_report({"schema_version": past, "findings": []})
        assert migrated["schema_version"] == D.REPORT_SCHEMA, past
    with pytest.raises(ValueError):
        D.migrate_report({"schema_version": "clash-report/0"})


def test_14e_v1_golden_still_parses_under_the_migration():
    """Канон нельзя сохранить байт-в-байт, добавив факт — но старый отчёт
    обязан остаться читаемым, иначе история измерений умирает.

    Сверяемся с `D.REPORT_SCHEMA`, а не с литералом: литерал здесь был той же
    окаменелостью, что и в тесте выше, и ронял этот — настоящий — закон за
    компанию с номером.
    """
    v1 = json.loads((FIXTURES / "golden_report_v1.json").read_text(encoding="utf-8"))
    migrated = D.migrate_report(v1)
    assert migrated["schema_version"] == D.REPORT_SCHEMA
    for f in migrated["findings"]:
        assert f["hull_relation"] in D.HULL_RELATIONS
        assert "hull_overlap_depth_mm" in f


# ── №15/№16 P1: снапшот и его происхождение ───────────────────────────────

def test_16_provenance_covers_every_side_input(tmp_path):
    """Хешировался только L0, усечёнными 16 hex. Изменение профиля меняло
    находки при неизменном отпечатке."""
    d = _l0(tmp_path)
    (d / "sketch.index.json").write_text('{"profile_index":{}}', encoding="utf-8")
    (d / "curve.index.json").write_text('{"curve_index":{}}', encoding="utf-8")
    first = S.build_from_decompile(d).origin["snapshot_sha256"]
    (d / "sketch.index.json").write_text('{"profile_index":{} }', encoding="utf-8")
    second = S.build_from_decompile(d).origin["snapshot_sha256"]
    assert first != second, "байт в боковом индексе не изменил отпечаток"
    assert len(first) == 64, "усечённый хеш"


def test_15_join_manifest_names_what_was_not_lifted(tmp_path):
    """§6 требует множества U (не поднятых) — снапшот обязан его считать,
    даже если L1 ещё не подключён."""
    d = _l0(tmp_path, census=9)
    snap = S.build_from_decompile(d)
    j = snap.join_manifest()
    assert j["eligible"] == j["scored"] + j["not_scored"]
    assert j["outside_extraction_scope"] == 6
    assert j["l1_join"] == "absent"          # честно: L1 пока не подключён


# ── №17 P1: голден сам себя создаёт ───────────────────────────────────────

def test_17_missing_golden_is_an_error_not_a_blessing():
    """Тест, который при отсутствии эталона ЗАПИСЫВАЕТ его и проходит, не
    может упасть никогда."""
    src = (pathlib.Path(__file__).resolve().parent / "test_clash.py").read_text("utf-8")
    body = src.split("def test_the_canonical_golden_does_not_move")[-1][:1200]
    assert "write_text" not in body, "голден всё ещё самоблагословляется"


def test_17b_golden_covers_every_pair_type():
    g = json.loads((FIXTURES / "golden_report_v2.json").read_text(encoding="utf-8"))
    kinds = {f["hull_relation"] for f in g["findings"]}
    grades = {f["hull_grade"] for f in g["findings"]}
    assert {"overlap", "contact"} <= kinds, kinds
    assert {"coarse", "conservative"} <= grades, grades


# ── ВОЛНА DECOMPOSE: минимальность хода на НЕВЫПУКЛОМ теле ─────────────────

def test_19_minimal_exit_takes_the_opening_not_the_whole_slab():
    """Плита с ПРОЁМОМ: труба выходит в проём, а не за край плиты.

    Опровергающий замер до правки (`w1_exit_probe.py`, 11.08.2026): 400
    пересекающихся пар «плита с проёмом против бруска», у 92 из них (23.0 %)
    бисекция выдавала ход длиннее наименьшего, в худшем случае в 6.79 раза.
    Причина названа в `resolve.minimal_exit`: у объединения кусков множество
    пересечения распадается на отрезки с промежутками, и вилка бисекции
    накрывала промежуток целиком.
    """
    from kukai.clash import decompose as D
    from kukai.clash import resolve as R
    plate = [[0, 0], [100, 0], [100, 60], [0, 60]]
    hole = [[30, 10], [50, 10], [50, 50], [30, 50]]
    dec = D.decompose(plate, [hole])
    assert dec.ok, dec.reason
    slab = G.PrismSet(dec.cells, 0.0, 10.0)
    box = G.Prism(((20.0, 20.0), (26.0, 20.0), (26.0, 26.0), (20.0, 26.0)), 2.0, 8.0)
    assert G.signed_distance(slab, box) < 0, "фикстура обязана пересекаться"
    t = R.minimal_exit(box, slab, (1.0, 0.0, 0.0))
    assert t is not None
    # Брусок [20,26] чист ровно тогда, когда ЛЕВЫЙ его край зайдёт за кромку
    # проёма x=30, то есть при t=10; правый край окажется на 36 < 50, всё ещё
    # внутри проёма. Плита кончается на x=100, и выход за неё стоил бы t=80 —
    # именно его и находила бисекция, накрывая проём вилкой целиком.
    assert abs(t - 10.0) < 1e-6, f"ход {t} вместо выхода в проём (10.0)"
    assert G.separates(box, slab, (t, 0.0, 0.0)), "обещанный ход не разводит"
    # Эталон без единого допущения: плотный скан по t.
    scan = next(k * 0.01 for k in range(0, 20001)
                if G.separates(box, slab, (k * 0.01, 0.0, 0.0)))
    assert abs(t - scan) < 0.02, f"точный путь {t} против скана {scan}"


def test_19b_the_exit_is_verified_not_asserted():
    """Каждый кандидат проверяется ПЕРЕНОСОМ, а не берётся на слово.

    Ровно на пол-шага раньше найденного выхода пара обязана ещё пересекаться —
    иначе `t` не наименьший, а просто какой-то.
    """
    from kukai.clash import decompose as D
    from kukai.clash import resolve as R
    plate = [[0, 0], [100, 0], [100, 60], [0, 60]]
    hole = [[30, 10], [50, 10], [50, 50], [30, 50]]
    slab = G.PrismSet(D.decompose(plate, [hole]).cells, 0.0, 10.0)
    box = G.Prism(((20.0, 20.0), (26.0, 20.0), (26.0, 26.0), (20.0, 26.0)), 2.0, 8.0)
    t = R.minimal_exit(box, slab, (1.0, 0.0, 0.0))
    assert G.separates(box, slab, (t, 0.0, 0.0))
    assert not G.separates(box, slab, (t - 0.01, 0.0, 0.0)), (
        "пара разведена ещё до объявленного хода — значит он не наименьший")


# ── ВОЛНА 2: слияние выпуклых соседок ──────────────────────────────────────

def test_20_merge_only_when_the_union_stays_convex():
    """Слияние законно РОВНО при выпуклом объединении, и это проверяется.

    Опровергающий замер до правки (`w3_merge_probe.py`, 11.08.2026, весь
    корпус): из 16 052 пар соседних ячеек 6 265 (39.0 %) имели выпуклое
    объединение — каждая третья граница проведена зря.

    Здесь важно не то, что склейка происходит, а то, что она НЕ происходит,
    когда объединение вогнуто: невыпуклый кусок среди выпуклых молча вернул бы
    ответ своей выпуклой оболочки и сломал бы и точное расстояние, и замкнутую
    форму наименьшего выхода.
    """
    from kukai.clash import decompose as D
    # Ступенька: объединение двух соседних трапеций ВОГНУТО.
    step = [[0, 0], [10, 0], [10, 4], [20, 4], [20, 10], [0, 10]]
    dec = D.decompose(step)
    assert dec.ok, dec.reason
    for c in dec.cells:
        assert len(c) < 3 or D.loop_is_convex(c), f"невыпуклая ячейка {c}"
    total = sum(D.polygon_area(c) for c in dec.cells if len(c) >= 3)
    assert abs(total - D.polygon_area([(float(x), float(y)) for x, y in step])) \
        <= 1e-9 * total, "слияние изменило площадь области"


def test_20b_merge_preserves_the_region_exactly():
    """Склейка меняет ЗАПИСЬ области, а не саму область.

    Проверяется на контуре с отверстием: площадь до последнего разряда и
    принадлежность точек — и внутри материала, и в проёме.
    """
    from kukai.clash import decompose as D
    plate = [[0, 0], [100, 0], [100, 60], [0, 60]]
    hole = [[30, 10], [50, 10], [50, 50], [30, 50]]
    dec = D.decompose(plate, [hole])
    assert dec.ok, dec.reason
    area = sum(D.polygon_area(c) for c in dec.cells if len(c) >= 3)
    assert abs(area - (100 * 60 - 20 * 40)) < 1e-9
    hull = G.PrismSet(dec.cells, 0.0, 5.0)
    assert G.contains_point(hull, (10.0, 30.0, 2.0)), "материал вне оболочки"
    assert not G.contains_point(hull, (40.0, 30.0, 2.0)), "проём внутри оболочки"
    for c in dec.cells:
        assert len(c) < 3 or D.loop_is_convex(c)


def test_20c_a_degenerate_sliver_is_repaired_not_swallowed():
    """Вырожденная ячейка чинится выпуклой оболочкой ТОЛЬКО без роста площади.

    Замер: все 20 невыпуклых ячеек корпуса выпускает заметание, ни одной —
    слияние, и все двадцать вырождены (различие координат в восемнадцатом
    разряде). Чинить их выпуклой оболочкой законно, потому что у вырожденного
    набора она вырождена и сама; подменять же настоящую область её оболочкой
    молча — нельзя, и на этот случай стоит отказ по имени.
    """
    from kukai.clash import decompose as D
    assert "decomposition_cell_not_convex" in D.REASONS
