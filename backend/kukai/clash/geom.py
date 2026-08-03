"""Оболочки и точная арифметика пар. Ни одного Revit-вызова, ни одной сети.

Три оболочки MVP и один закон: оболочка обязана СОДЕРЖАТЬ элемент. Тогда
пропуск пары оболочек означает пропуск клеша невозможным на уровне геометрии, а
всё огрубление идёт только вверх — в ложные срабатывания, которые видно и
которые помечены грейдом.

Что здесь точно, а что нет (это не украшение — на этом стоит вердикт):

* `Prism` — выпуклый многогранник: выпуклый полигон подошвы × [z0, z1].
* `Capsule` — полилиния × радиус (объединение сегментов; узлы покрыты).
* `Aabb` — бокс; частный случай призмы с прямоугольной подошвой.

Знаковое расстояние `signed_distance` считается ТОЧНО для каждой пары оболочек
(не для настоящих тел — см. `narrow.verdict_of`). «Точно» здесь проверяемо:
призма — декартово произведение выпуклого полигона на отрезок, поэтому
расстояние между двумя призмами раскладывается по независимым множителям, а
расстояние отрезка до призмы берётся как минимум по ГРАНЯМ — замыкание всех
случаев «грань/ребро/вершина» без единого приближения.

Клэмп-по-z из v1 отозван (ревью №12): у наклонного отрезка минимумы по XY и по
Z достигаются в разных точках, и их независимое сравнение объявляет клеш там,
где общей точки нет.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

Pt2 = tuple[float, float]
Pt3 = tuple[float, float, float]

#: Всё тоньше этого — ноль. Модели приезжают из Revit в футах и переводятся в
#: мм, поэтому «ровно ноль» в данных не встречается: у фасада SOB6.2 отметка
#: 1800 мм лежит как 1799.9999999998602.
EPS_MM = 1e-6

#: Ревью №8: КВАДРАТ длины нельзя сравнивать с порогом длины. Сегмент 0.0005 мм
#: имеет квадрат 2.5e-7 < EPS_MM и объявлялся точкой — знак расстояния при этом
#: менялся (замер: sd=+0.0001099 вместо -0.0003). Порог квадрата — квадрат
#: порога, и это не украшение, а единственное, что делает сравнение
#: размерностно осмысленным.
EPS_MM2 = EPS_MM * EPS_MM

#: Вырожденность пары направлений — величина ОТНОСИТЕЛЬНАЯ: `a*e - b*b` имеет
#: размерность мм⁴, поэтому сравнивать её с миллиметрами нельзя ни при каком
#: масштабе сцены.
EPS_REL = 1e-12


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _norm_zero(x: float) -> float:
    """-0.0 -> 0.0. Иначе два одинаковых прогона дают разный JSON."""
    return 0.0 if x == 0 else float(x)


# ────────────────────────────────────────────────────────────────── оболочки

@dataclass(frozen=True)
class Aabb:
    """Осеориентированный бокс. Самая грубая оболочка и единственная, которую
    можно построить из одного bbox — то есть из того, что есть про КАЖДЫЙ
    элемент декомпайла."""
    lo: Pt3
    hi: Pt3

    def bounds(self) -> tuple[Pt3, Pt3]:
        return self.lo, self.hi

    def as_prism(self) -> "Prism":
        (x0, y0, z0), (x1, y1, z1) = self.lo, self.hi
        return Prism(footprint=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
                     z0=z0, z1=z1)


@dataclass(frozen=True)
class Prism:
    """Выпуклый полигон подошвы (CCW или CW — нормализуется) × [z0, z1]."""
    footprint: tuple[Pt2, ...]
    z0: float
    z1: float

    def bounds(self) -> tuple[Pt3, Pt3]:
        xs = [p[0] for p in self.footprint]
        ys = [p[1] for p in self.footprint]
        return ((min(xs), min(ys), self.z0), (max(xs), max(ys), self.z1))


@dataclass(frozen=True)
class Capsule:
    """Полилиния × радиус. Один сегмент — частый случай; полилиния нужна дугам,
    разложенным на хорды, и наклонным трассам."""
    path: tuple[Pt3, ...]
    radius: float

    def bounds(self) -> tuple[Pt3, Pt3]:
        r = self.radius
        xs = [p[0] for p in self.path]
        ys = [p[1] for p in self.path]
        zs = [p[2] for p in self.path]
        return ((min(xs) - r, min(ys) - r, min(zs) - r),
                (max(xs) + r, max(ys) + r, max(zs) + r))

    def segments(self) -> list[tuple[Pt3, Pt3]]:
        if len(self.path) == 1:
            return [(self.path[0], self.path[0])]
        return list(zip(self.path, self.path[1:]))


Hull = Aabb | Prism | Capsule


def hull_bounds(h: Hull) -> tuple[Pt3, Pt3]:
    return h.bounds()


# ──────────────────────────────────────────────────────── элементарная работа

def _sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    return tuple(x - y for x, y in zip(a, b))


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _len(a: Sequence[float]) -> float:
    return math.sqrt(_dot(a, a))


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _point_seg_closest(pt: Pt3, q0: Pt3, q1: Pt3) -> tuple[float, Pt3]:
    """Параметр и точка проекции `pt` на отрезок q. Вырожденный отрезок — q0."""
    d = _sub(q1, q0)
    e = _dot(d, d)
    if e <= EPS_MM2:
        return 0.0, tuple(float(c) for c in q0)
    t = _clamp01(_dot(_sub(pt, q0), d) / e)
    return t, tuple(q0[i] + d[i] * t for i in range(3))


def seg_seg_closest_points(p0: Pt3, p1: Pt3, q0: Pt3, q1: Pt3
                           ) -> tuple[float, float, Pt3, Pt3, float]:
    """Ближайшая пара точек двух 3D-отрезков: `(s, t, cp, cq, distance)`.

    Ревью №5: расстояние без ТОЧЕК бесполезно для ремонта — направление
    разведения строилось по серединам сегментов и пару не разводило. Поэтому
    ближайшие точки теперь первичны, а расстояние — их следствие.

    Минимум расстояния между двумя отрезками достигается либо во внутренней
    точке обоих (классический clamped-параметр Эрикссона), либо на конце хотя
    бы одного из них. Оба множества перебираются целиком, поэтому параллельные,
    коллинеарные и вырожденные пары не являются особыми случаями: для них
    внутренняя формула вырождается, а победителем становится концевой кандидат.
    """
    d1, d2 = _sub(p1, p0), _sub(q1, q0)
    r = _sub(p0, q0)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    cands: list[tuple[float, float]] = []
    if a > EPS_MM2 and e > EPS_MM2:
        b, c = _dot(d1, d2), _dot(d1, r)
        denom = a * e - b * b
        # Относительный критерий (ревью №8): мм⁴ против мм⁴, а не против мм.
        if denom > EPS_REL * a * e:
            s = _clamp01((b * f - c * e) / denom)
            cands.append((s, _clamp01((b * s + f) / e)))
    # Концевые кандидаты — они же закрывают параллельный и вырожденный случаи.
    for s in (0.0, 1.0):
        pt = tuple(p0[i] + d1[i] * s for i in range(3))
        t, _ = _point_seg_closest(pt, q0, q1)
        cands.append((s, t))
    for t in (0.0, 1.0):
        pt = tuple(q0[i] + d2[i] * t for i in range(3))
        s, _ = _point_seg_closest(pt, p0, p1)
        cands.append((s, t))
    best: tuple[float, float, Pt3, Pt3, float] | None = None
    for s, t in cands:
        cp = tuple(p0[i] + d1[i] * s for i in range(3))
        cq = tuple(q0[i] + d2[i] * t for i in range(3))
        dist = _len(_sub(cp, cq))
        if best is None or dist < best[4] - 1e-15:
            best = (s, t, cp, cq, dist)
    assert best is not None
    return best


def seg_seg_distance(p0: Pt3, p1: Pt3, q0: Pt3, q1: Pt3) -> float:
    """Точное расстояние между двумя 3D-отрезками, включая вырожденные."""
    return seg_seg_closest_points(p0, p1, q0, q1)[4]


def _convex_hull_2d(pts: Iterable[Pt2]) -> tuple[Pt2, ...]:
    """Выпуклая оболочка подошвы (Эндрю). Вогнутый контур перекрытия обязан
    стать ВЫПУКЛЫМ — иначе SAT неприменим, а огрубление наружу законно."""
    ps = sorted(set((float(x), float(y)) for x, y in pts))
    if len(ps) <= 2:
        return tuple(ps)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Pt2] = []
    for p in ps:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Pt2] = []
    for p in reversed(ps):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return tuple(lower[:-1] + upper[:-1])


def convex_footprint(pts: Iterable[Pt2]) -> tuple[Pt2, ...]:
    return _convex_hull_2d(pts)


# ─────────────────────────────────────────────────── 2D: выпуклые полигоны

def _poly_axes(poly: Sequence[Pt2]) -> list[Pt2]:
    axes = []
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L > EPS_MM:
            axes.append((-ey / L, ex / L))
    return axes


def _project(poly: Sequence[Pt2], axis: Pt2) -> tuple[float, float]:
    vals = [p[0] * axis[0] + p[1] * axis[1] for p in poly]
    return min(vals), max(vals)


def poly_poly_gap(a: Sequence[Pt2], b: Sequence[Pt2]) -> float:
    """Зазор двух ВЫПУКЛЫХ полигонов: >0 — расстояние по разделяющей оси,
    <=0 — глубина проникания (минимальный перенос).

    Для непересекающихся полигонов это НИЖНЯЯ ОЦЕНКА евклидова расстояния (по
    лучшей разделяющей оси), для пересекающихся — точная глубина по лучшей оси.
    Нижняя оценка расстояния означает завышение клеша, то есть огрубление в
    безопасную сторону: лишние находки видно, пропущенных нет.

    Ревью №7. Оператор проверил лично: перестановочной нестабильности НЕТ —
    все циклические повороты одного квадрата дают один ответ. Осталась вторая
    половина: 1.0 против истинных √5 в контрпримере. Здесь снят ранний выход по
    первой же разделяющей оси (он делал результат зависящим от ПОРЯДКА осей,
    а не только от геометрии) — берётся максимум по всем осям, то есть самая
    тугая из доступных SAT-оценок. Точным расстоянием это не становится, и
    отчёт называет величину нижней оценкой (`SEPARATION_SEMANTICS`), а не
    расстоянием.
    """
    if not a or not b:
        return math.inf
    if len(a) == 1 and len(b) == 1:
        return math.hypot(a[0][0] - b[0][0], a[0][1] - b[0][1])
    best = -math.inf
    for axis in (_poly_axes(a) + _poly_axes(b)) or [(1.0, 0.0), (0.0, 1.0)]:
        amin, amax = _project(a, axis)
        bmin, bmax = _project(b, axis)
        gap = max(bmin - amax, amin - bmax)
        if gap > best:
            best = gap
    return best


def _interval_gap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(b0 - a1, a0 - b1)


# ───────────────────────────────────────────── отрезок × выпуклый многогранник

def _prism_faces(p: Prism) -> list[tuple[Pt3, ...]]:
    """Грани призмы: подошва, крышка и по четырёхугольнику на ребро подошвы."""
    fp = p.footprint
    if len(fp) < 3:
        # Вырожденная подошва (отрезок/точка): граней нет, работаем рёбрами.
        return []
    bottom = tuple((x, y, p.z0) for x, y in fp)
    top = tuple((x, y, p.z1) for x, y in reversed(fp))
    faces = [bottom, top]
    n = len(fp)
    for i in range(n):
        (x0, y0), (x1, y1) = fp[i], fp[(i + 1) % n]
        faces.append(((x0, y0, p.z0), (x1, y1, p.z0),
                      (x1, y1, p.z1), (x0, y0, p.z1)))
    return faces


def _point_in_prism(pt: Pt3, p: Prism) -> bool:
    if not (p.z0 - EPS_MM <= pt[2] <= p.z1 + EPS_MM):
        return False
    fp = p.footprint
    if len(fp) < 3:
        return False
    n = len(fp)
    sign = 0
    for i in range(n):
        ax, ay = fp[i]
        bx, by = fp[(i + 1) % n]
        cr = (bx - ax) * (pt[1] - ay) - (by - ay) * (pt[0] - ax)
        if abs(cr) <= EPS_MM:
            continue
        s = 1 if cr > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def _seg_polygon_distance(s0: Pt3, s1: Pt3, poly: Sequence[Pt3]) -> float:
    """Расстояние отрезка до ВЫПУКЛОГО многоугольника в 3D — точное.

    Ближайшая пара точек лежит либо на ребре многоугольника (тогда её найдёт
    отрезок-отрезок), либо внутри его плоскости (тогда её найдёт проекция конца
    отрезка). Оба случая перебираются целиком, поэтому приближения нет.
    """
    best = math.inf
    n = len(poly)
    for i in range(n):
        best = min(best, seg_seg_distance(s0, s1, poly[i], poly[(i + 1) % n]))
    # Проекции концов отрезка на плоскость грани.
    if n >= 3:
        e1 = _sub(poly[1], poly[0])
        e2 = _sub(poly[2], poly[0])
        nx = (e1[1] * e2[2] - e1[2] * e2[1],
              e1[2] * e2[0] - e1[0] * e2[2],
              e1[0] * e2[1] - e1[1] * e2[0])
        nl = _len(nx)
        if nl > EPS_MM:
            unit = tuple(c / nl for c in nx)
            for p in (s0, s1):
                d = _dot(_sub(p, poly[0]), unit)
                proj = tuple(p[i] - d * unit[i] for i in range(3))
                if _point_in_polygon_3d(proj, poly, unit):
                    best = min(best, abs(d))
    return best


def _point_in_polygon_3d(pt: Pt3, poly: Sequence[Pt3], normal: Pt3) -> bool:
    n = len(poly)
    sign = 0
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        e = _sub(b, a)
        w = _sub(pt, a)
        cr = (e[1] * w[2] - e[2] * w[1],
              e[2] * w[0] - e[0] * w[2],
              e[0] * w[1] - e[1] * w[0])
        d = _dot(cr, normal)
        if abs(d) <= EPS_MM:
            continue
        s = 1 if d > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def _halfspaces(p: Prism) -> list[tuple[Pt3, float]]:
    """Призма как пересечение полупространств n·x + d <= 0 с ЕДИНИЧНЫМИ n."""
    out: list[tuple[Pt3, float]] = [((0.0, 0.0, -1.0), p.z0), ((0.0, 0.0, 1.0), -p.z1)]
    fp = p.footprint
    n = len(fp)
    if n < 3:
        return out
    # Ориентация: знак площади задаёт, куда смотрит «наружу».
    area2 = sum(fp[i][0] * fp[(i + 1) % n][1] - fp[(i + 1) % n][0] * fp[i][1]
                for i in range(n))
    ccw = area2 > 0
    for i in range(n):
        (ax, ay), (bx, by) = fp[i], fp[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L <= EPS_MM:
            continue
        nx, ny = (ey / L, -ex / L) if ccw else (-ey / L, ex / L)
        out.append(((nx, ny, 0.0), -(nx * ax + ny * ay)))
    return out


def seg_prism_signed_distance(s0: Pt3, s1: Pt3, p: Prism) -> float:
    """Знаковое расстояние 3D-ОТРЕЗКА до призмы. Внутри — отрицательное.

    Это и есть отозванный клэмп-по-z, сделанный честно: один параметр отрезка,
    единый критерий. Проникание считается точно — глубина есть максимум по
    отрезку от вогнутой кусочно-линейной функции `min_i(-h_i)`, а её максимум
    достигается либо на конце отрезка, либо там, где две линейные части
    пересекаются; обе группы точек перебираются целиком.
    """
    hs = _halfspaces(p)
    if not hs:
        return math.inf

    def h_vals(t: float) -> list[float]:
        pt = tuple(s0[i] + (s1[i] - s0[i]) * t for i in range(3))
        return [_dot(n, pt) + d for n, d in hs]

    cands = {0.0, 1.0}
    # Точки, где меняется активная грань: пересечения пар линейных функций.
    a_lin = [(_dot(n, _sub(s1, s0)), _dot(n, s0) + d) for n, d in hs]
    for i in range(len(a_lin)):
        for j in range(i + 1, len(a_lin)):
            (ka, ba), (kb, bb) = a_lin[i], a_lin[j]
            dk = ka - kb
            if abs(dk) > EPS_MM:
                t = (bb - ba) / dk
                if 0.0 < t < 1.0:
                    cands.add(t)
    # m(t) = max_i h_i — ВЫПУКЛАЯ кусочно-линейная функция параметра, поэтому
    # её минимум (самая глубокая точка отрезка) достигается на конце или на
    # изломе, и оба множества уже в `cands`.
    best_inside = math.inf
    for t in cands:
        m = max(h_vals(t))
        if m < best_inside:
            best_inside = m
    if best_inside < 0:
        return best_inside          # отрицательное: глубина погружения
    # Снаружи — точное расстояние минимумом по граням.
    faces = _prism_faces(p)
    if not faces:
        return math.inf
    return min(_seg_polygon_distance(s0, s1, f) for f in faces)


# ────────────────────────────────────────────────────── пары оболочек

def signed_distance(a: Hull, b: Hull) -> float:
    """Знаковое расстояние между ДВУМЯ ОБОЛОЧКАМИ (не телами).

    Отрицательное — проникание. Функция симметрична по построению: пары
    приводятся к каноническому порядку типов.
    """
    ka, kb = type(a).__name__, type(b).__name__
    if (ka, kb) == ("Capsule", "Capsule"):
        best = math.inf
        for p0, p1 in a.segments():
            for q0, q1 in b.segments():
                best = min(best, seg_seg_distance(p0, p1, q0, q1))
        return best - (a.radius + b.radius)
    if ka == "Capsule":
        pr = b.as_prism() if kb == "Aabb" else b
        best = min(seg_prism_signed_distance(p0, p1, pr) for p0, p1 in a.segments())
        return best - a.radius
    if kb == "Capsule":
        return signed_distance(b, a)
    pa = a.as_prism() if ka == "Aabb" else a
    pb = b.as_prism() if kb == "Aabb" else b
    gxy = poly_poly_gap(pa.footprint, pb.footprint)
    gz = _interval_gap(pa.z0, pa.z1, pb.z0, pb.z1)
    if gxy > 0 or gz > 0:
        # Призма — декартово произведение подошвы на интервал, поэтому
        # квадраты расстояний складываются: это точно, а не приближение.
        return math.hypot(max(0.0, gxy), max(0.0, gz))
    return max(gxy, gz)


#: Допуск постусловия разведения: перенос обязан выводить пару в `sd >= -SEP_EPS`.
SEP_EPS_MM = 1e-6


def translate(h: Hull, v: Sequence[float]) -> Hull:
    """Перенос оболочки на вектор. Нужен и постусловию, и ремонту."""
    def sh(p):
        return tuple(p[i] + v[i] for i in range(3))

    if isinstance(h, Capsule):
        return Capsule(tuple(sh(p) for p in h.path), h.radius)
    if isinstance(h, Aabb):
        return Aabb(sh(h.lo), sh(h.hi))
    fp = tuple((x + v[0], y + v[1]) for x, y in h.footprint)
    return Prism(fp, h.z0 + v[2], h.z1 + v[2])


def separates(a: Hull, b: Hull, v: Sequence[float]) -> bool:
    """Проверка обещания: после переноса пара действительно разведена."""
    return signed_distance(translate(a, v), b) >= -SEP_EPS_MM


def certified_separating_translation(a: Hull, b: Hull
                                     ) -> tuple[float, float, float] | None:
    """Перенос A при НЕПОДВИЖНОМ B, ДОКАЗАННО выводящий пару из проникания.

    Имя буквальное (ревью №6). Это НЕ минимальный перенос и не MTV: минимума
    без GJK/EPA у нас нет, а обещать минимальность, считая её по граням, —
    ровно та ложь, которую ревью и поймало (диагональная капсула получала
    вектор длиной 101 там, где хватало ~8.07). Обещается ровно одно: после
    этого переноса `signed_distance >= -SEP_EPS_MM`, и это ПРОВЕРЯЕТСЯ здесь
    же, а не декларируется.

    Порядок: типовой кандидат → проверка → сертифицированный запасной вариант
    по габаритам (он разводит всегда) → проверка → `None` с названной причиной
    (`mtv_unavailable_reason`). Молчаливого `None` не бывает.
    """
    sd = signed_distance(a, b)
    if sd >= 0:
        return None
    for v in _separation_candidates(a, b, sd):
        if v is not None and separates(a, b, v):
            return tuple(_norm_zero(c) for c in v)
    v = _aabb_separation(a, b)
    if v is not None and separates(a, b, v):
        return tuple(_norm_zero(c) for c in v)
    return None


def mtv_unavailable_reason(a: Hull, b: Hull) -> str | None:
    """Почему разведения нет. `None` — оно есть (или пара не проникает)."""
    if signed_distance(a, b) >= 0:
        return None
    if certified_separating_translation(a, b) is not None:
        return None
    if not all(math.isfinite(c) for h in (a, b) for p in hull_bounds(h) for c in p):
        return "non_finite_hull"
    return "no_certified_direction"


def _separation_candidates(a: Hull, b: Hull, sd: float) -> list[Sequence[float] | None]:
    ka, kb = type(a).__name__, type(b).__name__
    if ka in ("Prism", "Aabb") and kb in ("Prism", "Aabb"):
        pa = a.as_prism() if ka == "Aabb" else a
        pb = b.as_prism() if kb == "Aabb" else b
        out: list[Sequence[float] | None] = []
        up, down = pb.z1 - pa.z0, pa.z1 - pb.z0
        out.append((0.0, 0.0, up if up <= down else -down))
        axis, depth = _best_axis(pa.footprint, pb.footprint)
        if axis is not None:
            out.append((axis[0] * depth, axis[1] * depth, 0.0))
        return out
    if ka == "Capsule" and kb in ("Prism", "Aabb"):
        return [_capsule_prism_push(a, b.as_prism() if kb == "Aabb" else b)]
    if kb == "Capsule" and ka in ("Prism", "Aabb"):
        v = _capsule_prism_push(b, a.as_prism() if ka == "Aabb" else a)
        return [None if v is None else tuple(-c for c in v)]
    return [_capsule_capsule_push(a, b)]


def _capsule_capsule_push(a: Capsule, b: Capsule) -> Sequence[float] | None:
    """Разведение двух капсул по БЛИЖАЙШИМ ТОЧКАМ (ревью №5).

    Было: направление между СЕРЕДИНАМИ ближайших сегментов, длина — недостача
    расстояния. На контрпримере (0,0,0)→(10,0,0) против (9,1,-5)→(9,1,5) это
    оставляло sd=-0.7575, то есть пару в проникании. Правильная ось — от
    ближайшей точки B к ближайшей точке A; длина — сколько не хватает до суммы
    радиусов вдоль этой оси.
    """
    best = None
    for p0, p1 in a.segments():
        for q0, q1 in b.segments():
            s, t, cp, cq, dist = seg_seg_closest_points(p0, p1, q0, q1)
            if best is None or dist < best[0]:
                best = (dist, cp, cq, (p0, p1))
    if best is None:
        return None
    dist, cp, cq, (p0, p1) = best
    need = (a.radius + b.radius) - dist
    if need <= 0:
        return None
    v = _sub(cp, cq)
    L = _len(v)
    if L > EPS_MM:
        return tuple(c / L * need for c in v)
    # Оси совпали/пересеклись: направление между точками не определено. Берём
    # ДЕТЕРМИНИРОВАННУЮ нормаль к оси A и разводим на полную сумму радиусов.
    n = _any_perpendicular(_sub(p1, p0))
    full = a.radius + b.radius
    return tuple(c * full for c in n)


def _any_perpendicular(d: Sequence[float]) -> Pt3:
    """Детерминированная единичная нормаль к направлению (и к любому нулевому
    направлению — тогда просто ось X). Детерминизм здесь — часть контракта:
    один вход обязан давать один отчёт."""
    if _len(d) <= EPS_MM:
        return (1.0, 0.0, 0.0)
    ux, uy, uz = (c / _len(d) for c in d)
    ref = (0.0, 0.0, 1.0) if abs(uz) < 0.9 else (1.0, 0.0, 0.0)
    cx = uy * ref[2] - uz * ref[1]
    cy = uz * ref[0] - ux * ref[2]
    cz = ux * ref[1] - uy * ref[0]
    L = _len((cx, cy, cz))
    if L <= EPS_MM:
        return (1.0, 0.0, 0.0)
    return (cx / L, cy / L, cz / L)


def _aabb_separation(a: Hull, b: Hull) -> Sequence[float] | None:
    """Сертифицированный запасной вариант: вывести габарит A за габарит B по
    самой дешёвой из шести сторон. Работает всегда, потому что оболочка лежит
    внутри своего габарита; длина не минимальна и на минимальность не
    претендует."""
    alo, ahi = hull_bounds(a)
    blo, bhi = hull_bounds(b)
    if not all(math.isfinite(c) for c in (*alo, *ahi, *blo, *bhi)):
        return None
    best: tuple[float, tuple[float, float, float]] | None = None
    for k in range(3):
        for d in (bhi[k] - alo[k] + SEP_EPS_MM, -(ahi[k] - blo[k] + SEP_EPS_MM)):
            v = [0.0, 0.0, 0.0]
            v[k] = d
            if best is None or abs(d) < best[0]:
                best = (abs(d), (v[0], v[1], v[2]))
    return None if best is None else best[1]


def _best_axis(a: Sequence[Pt2], b: Sequence[Pt2]) -> tuple[Pt2 | None, float]:
    best_axis, best_gap = None, -math.inf
    for axis in _poly_axes(a) + _poly_axes(b):
        amin, amax = _project(a, axis)
        bmin, bmax = _project(b, axis)
        gap = max(bmin - amax, amin - bmax)
        if gap > best_gap or (gap == best_gap and best_axis is not None
                              and axis < best_axis):
            best_axis, best_gap = axis, gap
    if best_axis is None:
        return None, 0.0
    amin, amax = _project(a, best_axis)
    bmin, bmax = _project(b, best_axis)
    out = bmax - amin
    back = amax - bmin
    return (best_axis, out) if out <= back else (
        (-best_axis[0], -best_axis[1]), back)


def _capsule_prism_push(cap: Capsule, pr: Prism) -> tuple[float, float, float] | None:
    """Разведение капсулы и призмы по граням призмы, а не численным градиентом.

    Градиент здесь вырождается ровно в самом частом случае: труба, ПРОШИВАЮЩАЯ
    стену насквозь, при сдвиге на микрон остаётся на той же глубине, и
    производная знакового расстояния равна нулю по всем трём осям. Правильный
    ответ — наименьший перенос вдоль нормали одной из граней, при котором ВЕСЬ
    отрезок оказывается снаружи: он конечен, вычисляется точно и гарантированно
    разводит пару.
    """
    hs = _halfspaces(pr)
    if not hs:
        return None
    best: tuple[float, Pt3] | None = None
    for n, d in hs:
        # h_i(p) <= 0 внутри; чтобы вывести капсулу за грань i, нужно поднять
        # h_i всех точек отрезка до +radius.
        worst = min(_dot(n, p) + d for p in cap.path)
        need = cap.radius - worst
        if need <= 0:
            return None                      # уже снаружи
        if best is None or need < best[0] - 1e-12 or (
                abs(need - best[0]) <= 1e-12 and n < best[1]):
            best = (need, n)
    if best is None:
        return None
    need, n = best
    return (_norm_zero(n[0] * need), _norm_zero(n[1] * need), _norm_zero(n[2] * need))


def _translate(h: Hull, axis: int, d: float) -> Hull:
    def shift3(p):
        q = list(p)
        q[axis] += d
        return tuple(q)

    if isinstance(h, Capsule):
        return Capsule(tuple(shift3(p) for p in h.path), h.radius)
    if isinstance(h, Aabb):
        return Aabb(shift3(h.lo), shift3(h.hi))
    if axis == 2:
        return Prism(h.footprint, h.z0 + d, h.z1 + d)
    fp = tuple(((x + d, y) if axis == 0 else (x, y + d)) for x, y in h.footprint)
    return Prism(fp, h.z0, h.z1)


def contains_point(h: Hull, pt: Pt3) -> bool:
    """Содержит ли оболочка точку — основа property-теста «оболочка содержит
    элемент»."""
    if isinstance(h, Capsule):
        return min(seg_seg_distance(p0, p1, pt, pt)
                   for p0, p1 in h.segments()) <= h.radius + 1e-6
    p = h.as_prism() if isinstance(h, Aabb) else h
    return _point_in_prism(pt, p)
