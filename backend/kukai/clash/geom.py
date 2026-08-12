"""Оболочки и точная арифметика пар. Ни одного Revit-вызова, ни одной сети.

Три оболочки MVP и один закон: оболочка обязана СОДЕРЖАТЬ элемент. Тогда
пропуск пары оболочек означает пропуск клеша невозможным на уровне геометрии, а
всё огрубление идёт только вверх — в ложные срабатывания, которые видно и
которые помечены грейдом.

Что здесь точно, а что нет (это не украшение — на этом стоит вердикт):

* `Prism` — выпуклый многогранник: выпуклый полигон подошвы × [z0, z1].
* `PrismSet` — ОБЪЕДИНЕНИЕ выпуклых призм с общим [z0, z1]. Тело невыпуклое.
* `Capsule` — полилиния × радиус (объединение сегментов; узлы покрыты).
* `Aabb` — бокс; частный случай призмы с прямоугольной подошвой.

ПОЧЕМУ `PrismSet` — ОТДЕЛЬНЫЙ ТИП, А НЕ ПРИЗМА С ВОГНУТОЙ ПОДОШВОЙ. SAT —
теорема о ВЫПУКЛЫХ множествах и только о них. `_project` берёт min/max по
вершинам, то есть проекцию ВЫПУКЛОЙ ОБОЛОЧКИ подошвы: подай ей вогнутый контур —
и она вернёт выпуклый ответ МОЛЧА, без ошибки и без флага. Вогнутость поэтому
обязана быть видна в ТИПЕ, а не спрятана в поле: `PrismSet` носит список
ВЫПУКЛЫХ кусков, и код, который типа не знает, спотыкается громко. По той же
причине `PrismSet` НЕ наследует `Prism`: наследование сделало бы
`isinstance(h, Prism)` истинным и вернуло бы ровно то молчаливое овыпукление,
ради устранения которого тип и заведён.

Знаковое расстояние `signed_distance` считается ТОЧНО для каждой пары оболочек
(не для настоящих тел — см. `narrow.verdict_of`). «Точно» здесь проверяемо:
призма — декартово произведение выпуклого полигона на отрезок, поэтому
расстояние между двумя призмами раскладывается по независимым множителям, а
расстояние отрезка до призмы берётся как минимум по ГРАНЯМ — замыкание всех
случаев «грань/ребро/вершина» без единого приближения.

Клэмп-по-z из v1 отозван (ревью №12): у наклонного отрезка минимумы по XY и по
Z достигаются в разных точках, и их независимое сравнение объявляет клеш там,
где общей точки нет.

ВОЛНА DECOMPOSE (10.08.2026), вторая половина. Зазор пары ВЫПУКЛЫХ подошв
считался по лучшей разделяющей оси SAT и был НИЖНЕЙ ОЦЕНКОЙ евклидова
расстояния (контрпример ревью №7: 1.0 против истинного √2). Оценка снизу
завышает клеш и потому безопасна — ровно пока оболочка ОДНА. У объединения
кусков она перестаёт быть безопасной по другой причине: `dist(∪Aᵢ, ∪Bⱼ) =
minᵢⱼ dist(Aᵢ, Bⱼ)` верно как теоретико-множественное равенство, но минимум по
N·M НИЖНИХ ОЦЕНОК — оценка ТЕМ ХУЖЕ, чем больше кусков, и разбивка подошвы
обменяла бы ложные перекрытия на ЛОЖНЫЕ НАРУШЕНИЯ ЗАЗОРА. Поэтому вместе с
разбивкой вводится `_convex_poly_distance` — точное расстояние пары выпуклых
многоугольников перебором «вершина–ребро», и оно применяется ко ВСЕМ парам
подошв, а не только к разбитым. Публикуемое расстояние с этой волны ТОЧНО;
нижней оценкой осталась ровно одна величина — глубина перекрытия ОБЪЕДИНЕНИЙ
(см. `signed_distance`).
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
class PrismSet:
    """ОБЪЕДИНЕНИЕ выпуклых призм с общим [z0, z1]. Подошва — вогнутая область.

    Куски приходят из `clash.decompose`, где доказано, что их объединение РАВНО
    объявленной области (сверка площадей + независимая проверка центроидов), а
    не содержит её и не содержится в ней. Здесь это уже предпосылка: каждый
    кусок обязан быть ВЫПУКЛЫМ, иначе всё, что ниже, врёт молча.

    Общий [z0, z1] — не упрощение, а форма данных: подошва выдавливается одной
    отметкой на одну высоту. Куску собственный размах по Z взять неоткуда.

    ВЫРОЖДЕННЫЕ КУСКИ (отрезок, точка) не выбрасываются: заметание выпускает их
    на защемлениях области, а выброшенный кусок УМЕНЬШАЕТ оболочку. Как
    выпуклые множества они законны, и вся арифметика ниже их держит.
    """
    pieces: tuple[tuple[Pt2, ...], ...]
    z0: float
    z1: float

    def bounds(self) -> tuple[Pt3, Pt3]:
        xs = [p[0] for fp in self.pieces for p in fp]
        ys = [p[1] for fp in self.pieces for p in fp]
        if not xs:
            # Пустое тело. Габарит ПУСТОГО множества — вывернутый бокс, и это
            # не «нет данных», а корректный ответ: пересечься с ним нельзя.
            return ((math.inf, math.inf, self.z0), (-math.inf, -math.inf, self.z1))
        return ((min(xs), min(ys), self.z0), (max(xs), max(ys), self.z1))

    def prisms(self) -> list["Prism"]:
        return [Prism(fp, self.z0, self.z1) for fp in self.pieces]


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


Hull = Aabb | Prism | PrismSet | Capsule

#: Оболочки, у которых подошва РАСКЛАДЫВАЕТСЯ на выпуклые куски. Единая точка,
#: где призма, бокс и объединение приводятся к одному виду: любой код, который
#: перебирает куски вручную, рано или поздно забудет один из трёх типов.
def footprint_pieces(h: Hull) -> tuple[tuple[Pt2, ...], ...] | None:
    """Выпуклые подошвы оболочки, либо `None` для капсулы (у неё подошвы нет)."""
    if isinstance(h, PrismSet):
        return h.pieces
    if isinstance(h, Prism):
        return (h.footprint,)
    if isinstance(h, Aabb):
        return (h.as_prism().footprint,)
    return None


def z_span(h: Hull) -> tuple[float, float] | None:
    """Размах по Z у призменного семейства. `None` — капсула."""
    if isinstance(h, PrismSet):
        return (h.z0, h.z1)
    if isinstance(h, Prism):
        return (h.z0, h.z1)
    if isinstance(h, Aabb):
        return (h.lo[2], h.hi[2])
    return None


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


def _seg_seg_distance_2d(p0: Pt2, p1: Pt2, q0: Pt2, q1: Pt2) -> float:
    """Расстояние двух отрезков на плоскости. Точно, включая вырожденные."""
    def pt_seg(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        e = dx * dx + dy * dy
        if e <= EPS_MM2:
            return math.hypot(p[0] - a[0], p[1] - a[1])
        t = _clamp01(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / e)
        return math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t)

    # Собственное пересечение — расстояние ноль, и его не даст ни одна из
    # четырёх проекций «конец на отрезок».
    d1x, d1y = p1[0] - p0[0], p1[1] - p0[1]
    d2x, d2y = q1[0] - q0[0], q1[1] - q0[1]
    den = d1x * d2y - d1y * d2x
    if den != 0.0:
        rx, ry = q0[0] - p0[0], q0[1] - p0[1]
        t = (rx * d2y - ry * d2x) / den
        u = (rx * d1y - ry * d1x) / den
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            return 0.0
    return min(pt_seg(p0, q0, q1), pt_seg(p1, q0, q1),
               pt_seg(q0, p0, p1), pt_seg(q1, p0, p1))


def _convex_poly_distance(a: Sequence[Pt2], b: Sequence[Pt2]) -> float:
    """ТОЧНОЕ евклидово расстояние двух НЕПЕРЕСЕКАЮЩИХСЯ выпуклых полигонов.

    Ближайшая пара точек двух непересекающихся выпуклых множеств всегда
    содержит хотя бы одну ВЕРШИНУ (даже когда ближайшие элементы — две
    параллельные стороны: вершина одной из них достигает того же минимума).
    Поэтому перебор «сторона × сторона» замыкает все случаи без приближения.

    Стоимость O(n·m). Здесь это не важно: подошва призмы после разбивки — от
    трёх до шести вершин, и худшая пара стоит десятки умножений.

    Вызывать ТОЛЬКО когда SAT уже сказал «разделены»: для пересекающихся
    полигонов перебор по границам вернул бы 0 и потерял бы глубину.
    """
    na, nb = len(a), len(b)
    if na == 0 or nb == 0:
        return math.inf
    if na == 1 and nb == 1:
        return math.hypot(a[0][0] - b[0][0], a[0][1] - b[0][1])
    if na == 1:
        return min(_seg_seg_distance_2d(a[0], a[0], b[j], b[(j + 1) % nb])
                   for j in range(nb))
    if nb == 1:
        return min(_seg_seg_distance_2d(a[i], a[(i + 1) % na], b[0], b[0])
                   for i in range(na))
    best = math.inf
    for i in range(na):
        ai, aj = a[i], a[(i + 1) % na]
        for j in range(nb):
            d = _seg_seg_distance_2d(ai, aj, b[j], b[(j + 1) % nb])
            if d < best:
                best = d
    return best


def _poly_sat_gap(a: Sequence[Pt2], b: Sequence[Pt2]) -> float:
    """SAT-зазор: ЗНАК точен, положительная величина — оценка СНИЗУ.

    Вынесено из `poly_poly_gap` не ради красоты, а ради отсева: у объединения
    кусков минимум ищется по N·M парам, и точное расстояние (перебор
    «вершина–ребро») незачем считать у пары, чья дешёвая оценка снизу уже хуже
    найденного минимума. Отсев ТОЧЕН: уточнение может только поднять величину,
    поэтому пара, отсеянная по оценке снизу, победить не могла.
    """
    best = -math.inf
    for axis in (_poly_axes(a) + _poly_axes(b)) or [(1.0, 0.0), (0.0, 1.0)]:
        amin, amax = _project(a, axis)
        bmin, bmax = _project(b, axis)
        gap = max(bmin - amax, amin - bmax)
        if gap > best:
            best = gap
    return best


def _xy_range(poly: Sequence[Pt2]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def poly_poly_gap(a: Sequence[Pt2], b: Sequence[Pt2]) -> float:
    """Зазор двух ВЫПУКЛЫХ полигонов: >0 — ТОЧНОЕ евклидово расстояние,
    <=0 — глубина проникания (она же длина наименьшего разводящего переноса).

    Ревью №7 закрыто ЦЕЛИКОМ. Первая половина (перестановочная нестабильность)
    не воспроизвелась у оператора; вторая — «1.0 против истинных √2» — была
    настоящей и чинилась только формулой. Здесь она и починена: SAT решает
    ВОПРОС О ЗНАКЕ (разделены или нет) — на это он и есть теорема, — а величину
    в разделённом случае даёт точный перебор `_convex_poly_distance`.

    ЗАЧЕМ ЭТО ПОНАДОБИЛОСЬ ИМЕННО СЕЙЧАС. Пока подошва была одна, нижняя
    оценка была безопасной: она завышает клеш, то есть даёт лишние находки, а
    не пропуски. У ОБЪЕДИНЕНИЯ подошв расстояние берётся минимумом по парам
    кусков, и минимум по N·M нижним оценок — оценка тем более рыхлая, чем
    мельче разбивка. Разбивка без этой правки меняла бы ложные перекрытия на
    ложные нарушения зазора, то есть переносила бы ошибку, а не убирала.

    В пересекающемся случае величина прежняя и точная: максимум по осям от
    отрицательных зазоров — это наименьшее перекрытие проекций, то есть длина
    MTV пары ВЫПУКЛЫХ полигонов.
    """
    if not a or not b:
        return math.inf
    if len(a) == 1 and len(b) == 1:
        return math.hypot(a[0][0] - b[0][0], a[0][1] - b[0][1])
    best = _poly_sat_gap(a, b)
    if best <= 0.0:
        return best
    # Разделены — SAT сказал ЧТО, точный перебор говорит НАСКОЛЬКО.
    # Точное расстояние никогда не меньше оценки снизу; сравнение оставлено
    # как страховка от вырожденных подошв, где перебор границ может дать 0.
    exact = _convex_poly_distance(a, b)
    return exact if exact >= best else best


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
        ex, ey = bx - ax, by - ay
        cr = ex * (pt[1] - ay) - ey * (pt[0] - ax)
        # Ревью №8, тот же закон на новом месте: `cr` имеет размерность мм², и
        # сравнивать его с порогом в МИЛЛИМЕТРАХ нельзя ни при каком масштабе.
        # Расстояние от точки до прямой ребра есть `cr / |ребро|`, поэтому
        # порог умножается на длину ребра — тогда сравниваются миллиметры с
        # миллиметрами.
        #
        # ЗАМЕР, который это нашёл (10.08.2026, плотная проба содержания по
        # 1 621 617 точкам корпуса): 893 точки, лежащие НА границе ячейки,
        # объявлялись снаружи оболочки. У ячейки с ребром 5 500 мм точка в
        # 1e-9 мм от ребра давала cr ≈ 5.5e-6 > EPS_MM = 1e-6 и признавалась
        # строго снаружи. До разбивки дефект был почти невидим: внутренних
        # границ у одной выпуклой подошвы нет, а после — их десятки.
        L = math.hypot(ex, ey)
        if abs(cr) <= EPS_MM * (L if L > 1.0 else 1.0):
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

def _prism_pair_sd(fa: Sequence[Pt2], fb: Sequence[Pt2],
                   za: tuple[float, float], zb: tuple[float, float]) -> float:
    """Знаковое расстояние ОДНОЙ пары выпуклых призм.

    Призма — декартово произведение подошвы на интервал ПО ТЕМ ЖЕ осям,
    поэтому квадраты расстояний складываются: `hypot` здесь точен, а не
    приближён. Композиция обязана происходить ВНУТРИ пары кусков и только
    потом уходить в минимум по парам: `hypot` от минимума по XY одной пары и
    минимума по Z ДРУГОЙ описывает точку, которой нет ни в одном теле.
    """
    gxy = poly_poly_gap(fa, fb)
    gz = _interval_gap(za[0], za[1], zb[0], zb[1])
    if gxy > 0 or gz > 0:
        return math.hypot(max(0.0, gxy), max(0.0, gz))
    return max(gxy, gz)


def signed_distance(a: Hull, b: Hull) -> float:
    """Знаковое расстояние между ДВУМЯ ОБОЛОЧКАМИ (не телами).

    Отрицательное — проникание. Функция симметрична по построению: пары
    приводятся к каноническому порядку типов.

    ЧТО ЗНАЧИТ ЧИСЛО У ОБЪЕДИНЕНИЯ (`PrismSet`) — две разные вещи по разные
    стороны нуля, и путать их нельзя:

    * ЗНАК ТОЧЕН ВСЕГДА. `∪Aᵢ ∩ ∪Bⱼ ≠ ∅` тогда и только тогда, когда
      пересекается хоть одна пара кусков, поэтому минимум по парам меняет знак
      ровно там, где меняет его настоящее тело. Ни пропуска, ни лишней находки
      разбивка не создаёт — она их УБИРАЕТ.
    * ПОЛОЖИТЕЛЬНАЯ ВЕЛИЧИНА ТОЧНА. `dist(∪Aᵢ, ∪Bⱼ) = minᵢⱼ dist(Aᵢ, Bⱼ)` —
      равенство множеств, а каждое слагаемое точно с этой волны.
    * ОТРИЦАТЕЛЬНАЯ ВЕЛИЧИНА — НИЖНЯЯ ОЦЕНКА, и это принципиально. Развести
      два ОБЪЕДИНЕНИЯ обязан ОДИН перенос, гасящий ВСЕ пересекающиеся пары
      кусков разом, поэтому |MTV(A,B)| ≥ maxᵢⱼ|MTV(Aᵢ,Bⱼ)| и, вообще говоря,
      строго больше любой из них. Публикуемая здесь глубина — самая глубокая
      пара кусков, то есть нижняя оценка требуемого хода. Выдавать её за MTV
      значило бы подписать сертификат, который не проверяли; поэтому
      `detect.Finding.separation_is_lower_bound` у таких пар истинен, а
      разводящий перенос берётся не отсюда, а из `certified_separating_
      translation`, где он ПРОВЕРЯЕТСЯ переносом.
    """
    ka, kb = type(a).__name__, type(b).__name__
    if (ka, kb) == ("Capsule", "Capsule"):
        best = math.inf
        for p0, p1 in a.segments():
            for q0, q1 in b.segments():
                best = min(best, seg_seg_distance(p0, p1, q0, q1))
        return best - (a.radius + b.radius)
    if ka == "Capsule":
        best = math.inf
        segs = a.segments()
        for pr in _as_prisms(b):
            # Отсев требует габарита, а у ВЫРОЖДЕННОЙ подошвы (пустой список
            # вершин) его нет. Тогда отсева просто нет: расстояние считается
            # как раньше и вернёт `inf` через грани, которых у такой призмы
            # тоже нет. Молчаливого исключения из перебора не происходит.
            plo, phi = (pr.bounds() if pr.footprint else (None, None))
            for p0, p1 in segs:
                # Тот же точный отсев: габаритный зазор отрезка и куска не
                # больше настоящего расстояния, поэтому пара, проигравшая по
                # нему, не могла победить по существу.
                if best < math.inf and plo is not None:
                    g = 0.0
                    for k in range(3):
                        lo_k, hi_k = min(p0[k], p1[k]), max(p0[k], p1[k])
                        gk = max(plo[k] - hi_k, lo_k - phi[k])
                        if gk > 0.0:
                            g += gk * gk
                    if g > 0.0 and math.sqrt(g) >= best:
                        continue
                d = seg_prism_signed_distance(p0, p1, pr)
                if d < best:
                    best = d
        return best - a.radius
    if kb == "Capsule":
        return signed_distance(b, a)
    fa, fb = footprint_pieces(a), footprint_pieces(b)
    za, zb = z_span(a), z_span(b)
    if fa is None or fb is None or za is None or zb is None:
        return math.inf
    gz = _interval_gap(za[0], za[1], zb[0], zb[1])
    if len(fa) == 1 and len(fb) == 1:
        return _prism_pair_sd(fa[0], fb[0], za, zb)
    # ── ОТСЕВ ПО ОЦЕНКАМ СНИЗУ. Ответ от него не зависит ни на разряд: каждая
    #    отброшенная пара кусков отброшена величиной, которая НЕ БОЛЬШЕ её
    #    настоящего расстояния, и уже проигрывает найденному минимуму.
    #    Замер 11.08.2026 (медиана 19 кусков на разложенную подошву, максимум
    #    62): без отсева пара оболочек стоила ~1.4 мс против 0.05 мс у выпуклой,
    #    то есть тридцатикратное подорожание узкой фазы — ради него волну бы и
    #    завернули. Отсев ТОЧЕН, и это проверено отдельно: 4 000 случайных пар
    #    объединений против полного перебора всех пар кусков, 0 расхождений.
    zc = max(0.0, gz)
    ra = [_xy_range(p) for p in fa]
    rb = [_xy_range(p) for p in fb]
    best = math.inf
    for i, pa in enumerate(fa):
        ax0, ay0, ax1, ay1 = ra[i]
        for j, pb in enumerate(fb):
            bx0, by0, bx1, by1 = rb[j]
            # (1) габаритный зазор кусков — оценка снизу, три вычитания
            gx = max(bx0 - ax1, ax0 - bx1)
            gy = max(by0 - ay1, ay0 - by1)
            if gx > 0.0 or gy > 0.0:
                lb = math.hypot(math.hypot(max(0.0, gx), max(0.0, gy)), zc)
                if lb >= best:
                    continue
            elif zc > 0.0 and zc >= best:
                continue
            # (2) SAT — оценка снизу потуже, но всё ещё дешёвая
            sat = _poly_sat_gap(pa, pb)
            if sat > 0.0:
                if math.hypot(sat, zc) >= best:
                    continue
                # `max` — та же страховка, что в `poly_poly_gap`: у вырожденной
                # подошвы перебор границ может дать 0 там, где SAT прав.
                d = math.hypot(max(sat, _convex_poly_distance(pa, pb)), zc)
            elif gz > 0.0:
                d = zc
            else:
                d = max(sat, gz)
            if d < best:
                best = d
    return best


def _as_prisms(h: Hull) -> list[Prism]:
    """Призменное семейство -> список ВЫПУКЛЫХ призм. Капсула -> пусто."""
    if isinstance(h, PrismSet):
        return h.prisms()
    if isinstance(h, Prism):
        return [h]
    if isinstance(h, Aabb):
        return [h.as_prism()]
    return []


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
    if isinstance(h, PrismSet):
        return PrismSet(
            tuple(tuple((x + v[0], y + v[1]) for x, y in fp) for fp in h.pieces),
            h.z0 + v[2], h.z1 + v[2])
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

    НАСКОЛЬКО ЭТОТ ХОД ДЛИННЕЕ НАИМЕНЬШЕГО — ЗАМЕРЕНО, а не оценено.
    `clash.resolve.minimal_exit` ищет наименьший перенос бисекцией по
    направлению (множество `{t : (A+t·d) ∩ B ≠ ∅}` у выпуклых тел есть
    ОТРЕЗОК, поэтому бисекция корректна). Сверка на 600 настоящих находках
    `sob62_r23_v5` (10.08.2026): здешний ход длиннее минимального в 5.892 раза
    по медиане, в 56.667 на p90 и в 112 066.5 раза в худшем случае.

    Это НЕ противоречие с абзацем выше: минимальность здесь и не обещана.
    Ссылка стоит затем, чтобы альтернативу было ВИДНО из точки, где выбирают
    вектор, — иначе её выбирают, не зная цены.
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
    """Кандидаты в разводящий перенос. КАЖДЫЙ проверяется вызывающим.

    У объединения кандидат берётся по ВСЕМУ телу, а не по куску: перенос,
    выводящий один кусок, отправляет его в соседний, и пара остаётся в
    проникании. Поэтому проекции считаются по объединению вершин обоих тел, а
    набор осей — по граням всех кусков. Для одного выпуклого куска это ровно
    прежняя формула с прежним ответом, поэтому находки, которых волна не
    касается, не сдвигаются ни на разряд.
    """
    ka, kb = type(a).__name__, type(b).__name__
    fa, fb = footprint_pieces(a), footprint_pieces(b)
    za, zb = z_span(a), z_span(b)
    if fa is not None and fb is not None and za is not None and zb is not None:
        out: list[Sequence[float] | None] = []
        up, down = zb[1] - za[0], za[1] - zb[0]
        out.append((0.0, 0.0, up if up <= down else -down))
        pts_a = [p for fp in fa for p in fp]
        pts_b = [p for fp in fb for p in fp]
        axes: list[Pt2] = []
        for fp in fa:
            axes += _poly_axes(fp)
        for fp in fb:
            axes += _poly_axes(fp)
        axis, depth = _best_axis_over(pts_a, pts_b, axes)
        if axis is not None:
            out.append((axis[0] * depth, axis[1] * depth, 0.0))
        return out
    if ka == "Capsule" and fb is not None:
        # Каждый кусок даёт свой ход; ни один не обещан работающим, поэтому
        # предлагаются ВСЕ, а решает проверка переносом.
        return [_capsule_prism_push(a, pr) for pr in _as_prisms(b)]
    if kb == "Capsule" and fa is not None:
        out2: list[Sequence[float] | None] = []
        for pr in _as_prisms(a):
            v = _capsule_prism_push(b, pr)
            out2.append(None if v is None else tuple(-c for c in v))
        return out2
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


def _best_axis_over(a: Sequence[Pt2], b: Sequence[Pt2],
                    axes: Sequence[Pt2]) -> tuple[Pt2 | None, float]:
    """Ось наименьшего перекрытия проекций и длина хода вдоль неё.

    Точки и оси разведены по разным параметрам намеренно: у объединения
    кусков проекция обязана считаться по ВСЕМ вершинам тела, а осями служат
    нормали граней КАЖДОГО куска. Слепить их в один список нельзя — «ребро»
    между вершинами разных кусков не является гранью ни одного тела.
    """
    best_axis, best_gap = None, -math.inf
    for axis in axes:
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


def _best_axis(a: Sequence[Pt2], b: Sequence[Pt2]) -> tuple[Pt2 | None, float]:
    return _best_axis_over(a, b, _poly_axes(a) + _poly_axes(b))


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

    v = [0.0, 0.0, 0.0]
    v[axis] = d
    return translate(h, v)


def contains_point(h: Hull, pt: Pt3) -> bool:
    """Содержит ли оболочка точку — основа property-теста «оболочка содержит
    элемент».

    У объединения принадлежность — дизъюнкция по кускам: точка в теле тогда и
    только тогда, когда она хоть в одном куске. Это и есть определение
    объединения, а не приближение к нему.
    """
    if isinstance(h, Capsule):
        return min(seg_seg_distance(p0, p1, pt, pt)
                   for p0, p1 in h.segments()) <= h.radius + 1e-6
    return any(_point_in_prism(pt, p) for p in _as_prisms(h))
