"""Сверка `seg_seg_closest_points` с НЕЗАВИСИМЫМ оракулом (BHoM-формула).

Зачем. Наша ближайшая пара точек считается формулировкой Эрикссона: одна
линейная система с знаменателем `a*e - b*b`, плюс перебор концевых кандидатов.
Тест, написанный тем же человеком под ту же формулу, проверяет арифметику, но
не саму формулу: общая ошибка вывода останется зелёной.

Оракул здесь — ДРУГАЯ алгебра для той же величины, прочитанная как справочник
в клоне BHoM (`Geometry_Engine/Compute/SkewLineProximity.cs`, LGPLv3 — код не
копируется, воспроизводится математика):

    cp = v1 × v2 ;  n1 = v1 × (−cp) ;  n2 = v2 × cp
    t1 = ((p2 − p1) · n2) / (v1 · n2)
    t2 = ((p1 − p2) · n1) / (v2 · n1)

Это пересечение прямой с плоскостью, натянутой на вторую прямую и общую
нормаль, — вывод, не имеющий с методом Эрикссона общих промежуточных величин.
Дальше, как и у них: параметры КЛАМПЯТСЯ в [0,1], отдельно считаются концевые
кандидаты, и побеждает ближайший. Совпадение двух независимых выводов на одних
входах — это уже свидетельство, а не самопроверка.

Их же трактовка вырождения взята как эталон границы: при `1 − |v̂1·v̂2| <= tol`
(параллельность) косая формула не определена и обязана уступить концевым
кандидатам. У нас ту же роль играет относительный критерий `denom > EPS_REL*a*e`.

    venv/bin/pytest kukai/clash/tests/test_clash_proximity_oracle.py -q
"""
from __future__ import annotations

import math
import random

import pytest

from kukai.clash import geom as G
from kukai.clash import hulls as H

#: Порог параллельности оракула. У BHoM это `Tolerance.Angle`; здесь он назван
#: числом, потому что от него зависит, какая из двух ветвей оракула отвечает.
ORACLE_PARALLEL_TOL = 1e-9


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _skew_params(p0, p1, q0, q1):
    """Незажатые параметры косых прямых. `None` — прямые параллельны."""
    v1, v2 = G._sub(p1, p0), G._sub(q1, q0)
    l1, l2 = G._len(v1), G._len(v2)
    if l1 <= 0 or l2 <= 0:
        return None
    u1 = tuple(c / l1 for c in v1)
    u2 = tuple(c / l2 for c in v2)
    if 1.0 - abs(G._dot(u1, u2)) <= ORACLE_PARALLEL_TOL:
        return None
    cp = _cross(v1, v2)
    n1 = _cross(v1, tuple(-c for c in cp))
    n2 = _cross(v2, cp)
    d1, d2 = G._dot(v1, n2), G._dot(v2, n1)
    if d1 == 0 or d2 == 0:
        return None
    return (G._dot(G._sub(q0, p0), n2) / d1,
            G._dot(G._sub(p0, q0), n1) / d2)


def oracle_distance(p0, p1, q0, q1) -> float:
    """Расстояние отрезок-отрезок ПО ЧУЖОМУ ВЫВОДУ. Только величина: точки нам
    для сверки не нужны, а минимум расстояния определён однозначно даже там,
    где сама пара ближайших точек не единственна."""
    def pt(a, b, t):
        return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

    def point_seg(p, a, b):
        d = G._sub(b, a)
        e = G._dot(d, d)
        t = 0.0 if e <= 0 else max(0.0, min(1.0, G._dot(G._sub(p, a), d) / e))
        return G._len(G._sub(p, pt(a, b, t)))

    # Концевые кандидаты — та же пара проекций, что у BHoM (min1/min2).
    best = min(point_seg(p0, q0, q1), point_seg(p1, q0, q1),
               point_seg(q0, p0, p1), point_seg(q1, p0, p1))
    params = _skew_params(p0, p1, q0, q1)
    if params is not None:
        t1 = max(0.0, min(1.0, params[0]))
        t2 = max(0.0, min(1.0, params[1]))
        best = min(best, G._len(G._sub(pt(p0, p1, t1), pt(q0, q1, t2))))
    return best


# ── вырожденные случаи закалки против чужого вывода ────────────────────────

#: Ровно те четыре случая, которыми закрыта находка №5 закалки. Для них наш
#: интерьерный кандидат ОТКЛЮЧАЕТСЯ вырожденностью, и ответ целиком держится
#: на концевых кандидатах — то есть проверяется самая хрупкая ветвь.
DEGENERATE = [
    ("identical", ((0, 0, 0), (10, 0, 0)), ((0, 0, 0), (10, 0, 0))),
    ("collinear", ((0, 0, 0), (10, 0, 0)), ((5, 0, 0), (15, 0, 0))),
    ("crossing_same_centre", ((-5, 0, 0), (5, 0, 0)), ((0, -5, 0), (0, 5, 0))),
    ("degenerate_points", ((1, 1, 1), (1, 1, 1)), ((1, 1, 1), (1, 1, 1))),
]


@pytest.mark.parametrize("name,pa,pb", DEGENERATE)
def test_degenerate_pairs_agree_with_the_foreign_derivation(name, pa, pb):
    ours = G.seg_seg_distance(pa[0], pa[1], pb[0], pb[1])
    theirs = oracle_distance(pa[0], pa[1], pb[0], pb[1])
    assert ours == pytest.approx(theirs, abs=1e-9), (
        f"{name}: наш вывод {ours}, чужой {theirs}")


@pytest.mark.parametrize("name,pa,pb", DEGENERATE)
def test_degenerate_pairs_are_exactly_where_the_skew_formula_refuses(name, pa, pb):
    """Граница вырожденности названа, а не подразумевается: на этих четырёх
    входах косая формула НЕ отвечает (параллельны, вырождены) либо отвечает и
    совпадает. Если однажды она начнёт отвечать иначе — тест выше покраснеет."""
    params = _skew_params(pa[0], pa[1], pb[0], pb[1])
    if name in ("identical", "collinear", "degenerate_points"):
        assert params is None, "оракул обязан отказаться на параллельной паре"
    else:
        assert params is not None


# ── случайная сверка, включая почти-вырожденные ────────────────────────────

def test_random_pairs_agree_with_the_foreign_derivation():
    """400 случайных пар: два независимых вывода обязаны дать одно число."""
    rnd = random.Random(20260729)
    checked = 0
    for _ in range(400):
        def rp():
            return tuple(rnd.uniform(-50, 50) for _ in range(3))

        p0, p1, q0, q1 = rp(), rp(), rp(), rp()
        ours = G.seg_seg_distance(p0, p1, q0, q1)
        theirs = oracle_distance(p0, p1, q0, q1)
        assert ours == pytest.approx(theirs, abs=1e-6), (p0, p1, q0, q1)
        checked += 1
    assert checked == 400


@pytest.mark.parametrize("skew_deg", [0.0, 1e-7, 1e-5, 1e-3, 0.01, 0.1, 1.0])
def test_nearly_parallel_pairs_agree(skew_deg):
    """Почти параллельные — та зона, где знаменатель обоих выводов стремится к
    нулю и где расхождение вылезло бы первым. Наш относительный критерий и их
    угловой обязаны давать один ответ по обе стороны своих порогов."""
    ang = math.radians(skew_deg)
    p0, p1 = (0.0, 0.0, 0.0), (100.0, 0.0, 0.0)
    q0 = (10.0, 3.0, 0.0)
    q1 = (10.0 + 80.0 * math.cos(ang), 3.0 + 80.0 * math.sin(ang), 0.0)
    ours = G.seg_seg_distance(p0, p1, q0, q1)
    theirs = oracle_distance(p0, p1, q0, q1)
    assert ours == pytest.approx(theirs, abs=1e-6), (skew_deg, ours, theirs)


# ── дыра, найденная чек-листом BHoM: у них Circle — ОТДЕЛЬНЫЙ тип ──────────

def _sample_arc(arc: dict, n: int = 600) -> list[G.Pt3]:
    c, r = arc["center_mm"], arc["radius_mm"]
    a0, a1 = arc["start_angle_rad"], arc["end_angle_rad"]
    xa, ya = arc["x_axis"], arc["y_axis"]
    out = []
    for i in range(n + 1):
        t = a0 + (a1 - a0) * (i / n)
        out.append(tuple(c[k] + r * (math.cos(t) * xa[k] + math.sin(t) * ya[k])
                         for k in range(3)))
    return out


# ДЫРА ЗАКРЫТА 29.07. Была: формула стрелки `r*(1-cos(span/2n))` применялась
# вне области применимости, и при размахе около чётного кратного 2π дуга
# подменялась ОДНОЙ хордой — тело уходило из оболочки на 5 900 мм при r=3000.
# Правка: число хорд снизу ограничено ceil(span/π). `xfail` СНЯТ, потому что
# закон доказан, а не потому что тест стал удобным.
@pytest.mark.parametrize("span_deg", [715, 720, 1440])
def test_arc_hull_contains_the_arc_at_any_span(span_deg):
    arc = {"center_mm": [0.0, 0.0, 0.0], "radius_mm": 3000.0,
           "start_angle_rad": 0.0, "end_angle_rad": math.radians(span_deg),
           "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0]}
    p0 = (3000.0, 0.0, 0.0)
    p1 = (3000.0 * math.cos(math.radians(span_deg)),
          3000.0 * math.sin(math.radians(span_deg)), 0.0)
    pts, sag = H.arc_chord_polyline(arc, p0, p1)
    hull = G.Capsule(tuple(pts), 100.0 + sag)
    for p in _sample_arc(arc):
        assert G.contains_point(hull, p), (span_deg, p, sag)


def test_zero_length_against_real_segment_agrees():
    """Точка против отрезка — вырождение, которое в модели встречается чаще
    всего (труба нулевой длины уже ловилась ревью №4)."""
    for pt in ((5.0, 1.0, 0.0), (-5.0, 0.0, 0.0), (15.0, 0.0, 0.0)):
        ours = G.seg_seg_distance(pt, pt, (0, 0, 0), (10, 0, 0))
        theirs = oracle_distance(pt, pt, (0, 0, 0), (10, 0, 0))
        assert ours == pytest.approx(theirs, abs=1e-12), pt
