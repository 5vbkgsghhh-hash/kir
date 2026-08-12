"""Плоская область -> ВЫПУКЛЫЕ ячейки. Ни одной оболочки, ни одного Revit-вызова.

ЗАЧЕМ. `hulls.hull_from_profile` сводил ЛЮБУЮ подошву к ВЫПУКЛОЙ оболочке и
засыпал отверстия. Замер по корпусу (`/tmp/clashwork/w1_value.py`, 10.08.2026):
на `k2_ar_rd_v15` из 341 читаемого контура 215 (63.0 %) НЕВЫПУКЛЫ, 42 несут
отверстия, и площадь выпуклой оболочки больше объявленной области в медиане на
5.8 %, на p90 — на 57.5 %, в пределе — на 95.5 %. То есть у худшего пола
двадцать первых процентов оболочки были телом, а остальное — нашим огрублением.
Огрубление законно (закон консервативности), но каждая находка в нём —
выдумана, и отличить её от настоящей читатель не может.

ПОЧЕМУ ВЕРТИКАЛЬНАЯ ТРАПЕЦЕИДАЛЬНАЯ РАЗБИВКА, а не отсечение ушей и не
Гертель–Мельхорн:

* отверстия — не особый случай, а просто ещё рёбра в заметании; ухо-клиппинг
  их не умеет вовсе и требует предварительного «моста» к каждому отверстию;
* каждая ячейка выпукла ПО ПОСТРОЕНИЮ (трапеция с двумя вертикальными
  сторонами), а не по проверке после;
* разбивка ДЕТЕРМИНИРОВАНА: полосы идут по отсортированным координатам вершин,
  пересечения внутри полосы — по отсортированным y. Байт-в-байт одинаковый
  отчёт при повторном прогоне — требование каноничности, а не удобство.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Здесь нет ни одного «допуска склейки» и ни одного
округления координат. Полосы режутся по ТОЧНЫМ значениям x вершин (сравнение
на равенство float, а не в пределах epsilon): слить две почти совпавшие
координаты значит выбросить тонкую полосу между ними, а выброшенная полоса
УМЕНЬШАЕТ область — ровно то, что закон консервативности запрещает. Полос
поэтому бывает много; на это стоит потолок работы, и за потолком ответ —
НАЗВАННЫЙ отказ, а не тихое огрубление.

ЗАКОН МОДУЛЯ, буквально: «молча не выбрасываем — отказываем». Поэтому
разбивка сама себя ПРОВЕРЯЕТ двумя независимыми способами и, не сойдясь,
отказывается целиком:

  1. ПЛОЩАДЬ. Сумма площадей ячеек обязана совпасть с объявленной площадью
     области (внешний контур минус отверстия). Расхождение ловит и
     самопересечение контура, и неверную расстановку «внутри/снаружи», и
     потерянную полосу.
  2. ЦЕНТР ЯЧЕЙКИ. Центроид каждой ячейки обязан лежать ВНУТРИ области по
     независимому счётчику пересечений луча с ИСХОДНЫМИ контурами. Эта
     проверка не знает про полосы вообще и потому не может ошибиться вместе
     с ними.

Обе проверки дешевле самой разбивки и обе обязательны: площадь ловит недостачу,
центроид — лишнее.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

Pt2 = tuple[float, float]

#: Потолок работы заметания: (число полос) x (число рёбер). Смысл тот же, что
#: у `clash_judgement._MAX_LOOP_WORK`: дешёвое уточнение не имеет права стать
#: дорогим. ЗАМЕР (`w1_decomp.py`, 11.08.2026, весь корпус, 1 436 разложенных
#: контуров): работа p50 = 380, p90 = 3 245, МАКСИМУМ 3 660 (`k2_ar_rd_v14`,
#: элемент 11894479: 60 полос на 61 ребре). Потолок 250 000 оставляет запас в
#: 68 раз к худшему наблюдению и при этом не пускает контур в тысячу вершин
#: (работа порядка 1e6) в узкую фазу. Ни одного отказа по этому потолку на
#: корпусе нет — он стоит на вырожденный вход, а не на сегодняшние данные.
MAX_SWEEP_WORK = 250_000

#: Потолок числа ячеек. Это НЕ вкус: узкая фаза считает пару оболочек как
#: N x M пар ячеек, поэтому стоимость пары растёт вместе с этим числом.
#:
#: ЧИСЛО ПЕРЕВЫВЕДЕНО ПОСЛЕ СЛИЯНИЯ (11.08.2026). Прежние 64 стояли при
#: распределении ДО склейки соседок; склейка распределение сдвинула, и оставить
#: потолок «с запасом» значило бы назначить границу, а не вывести её.
#:
#: ЗАМЕР 1 — РАСПРЕДЕЛЕНИЕ (весь корпус, 1 564 разложенных контура, без
#: потолка): ячеек p50 = 18, p90 = 48, МАКСИМУМ 78. До слияния те же контуры
#: давали p50 = 19, p90 = 59, максимум 94.
#:
#: ЗАМЕР 2 — ЦЕНА ДОПУСКА, по РАЗЛИЧНЫМ контурам, а не по снимкам. Сверх 64
#: ячеек в корпусе оказалось 19 РАЗЛИЧНЫХ полов (все на `k2_ar_rd`; в сумме по
#: шести снимкам одного здания они дают 114 строк, и это одно здание, а не сто
#: четырнадцать полов). Те же 11 883 пары-кандидата, посчитанные дважды:
#:
#:     потолок 64  (подошва овыпуклена)  2.329 с,   196 мкс/пара, 11 056 перекрытий
#:     потолок 128 (подошва разложена)  14.607 с,  1 229 мкс/пара,  4 179 перекрытий
#:
#: То есть допуск стоит 6.27x времени узкой фазы НА ЭТИХ ПАРАХ и снимает
#: 6 877 перекрытий — 62.2 % всех, что давала выпуклая оболочка. Двенадцать
#: секунд на здание против почти семи тысяч выдуманных находок: обмен
#: очевидный, и он предъявлен, а не заявлен.
#:
#: ОТКУДА 128. Потолок поставлен так, чтобы в сегодняшнем корпусе он НЕ
#: СРАБАТЫВАЛ НИ РАЗУ (максимум 78), и одновременно оставался стопом на
#: вырожденный контур. Что именно он стопорит, тоже названо числом: стоимость
#: пары растёт по замеру почти линейно, 196 + 13.6*N мкс, поэтому на потолке
#: она составляет около 1.9 мс. Это и есть величина, при выходе за которую
#: потолок обязан пересматриваться заново — не «когда покажется много».
MAX_CELLS = 128

#: Потолок СЫРЫХ ячеек заметания — до слияния. Существует только затем, чтобы
#: вырожденный контур не съел память прежде, чем дело дойдёт до склейки; на
#: осмысленность ответа он не влияет, потому что настоящий потолок
#: (`MAX_CELLS`) применяется ПОСЛЕ неё. Замер 11.08.2026: сырых ячеек p90 = 57,
#: максимум 62 при потолке 64 — то есть до слияния корпус в 512 не упирается
#: нигде, и этот потолок сегодня не срабатывает ни разу.
RAW_CELL_CAP = 512


#: Относительная невязка площади, при которой разбивка считается несошедшейся.
#:
#: Число ВЫВЕДЕНО и ПОДТВЕРЖДЕНО, а не выбрано. Вывод: double несёт 2^-52,
#: около 2.2e-16, относительной точности; накопление по <= MAX_CELLS ячейкам и
#: <= сотне рёбер даёт порядок 1e-13 в худшем случае.
#:
#: ЗАМЕР (`w1_decomp.py`, 11.08.2026, 1 436 разложенных контуров всего
#: корпуса): невязка p50 = 1.6e-16, p90 = 5.1e-15, МАКСИМУМ 1.15e-12
#: (`sob62_fas_r23_v12`, элемент 11423944, 7 ячеек). То есть порог 1e-9 стоит
#: в 868 раз выше худшего наблюдения — запас есть, но он ТРИ ПОРЯДКА, а не
#: семь; если корпус вырастет и невязка подберётся к 1e-10, порог придётся
#: пересматривать замером, а не рассуждением.
#:
#: Порог стоит там, где ошибка арифметики уже невозможна, а ошибка геометрии
#: (самопересечение, чужое отверстие) ещё видна: на корпусе он поймал ровно
#: один контур, и это была настоящая поломка, а не шум.
AREA_REL_TOL = 1e-9

#: Имена отказов. Список закрыт: разбивка, не сумевшая доказать себя, обязана
#: назваться, иначе «оболочка выпуклая» неотличимо от «оболочка выпуклая,
#: потому что мы сдались».
REASONS = (
    "decomposition_over_cap",
    "decomposition_too_many_cells",
    "decomposition_odd_crossings",
    "decomposition_area_mismatch",
    "decomposition_cell_outside_region",
    "decomposition_slab_underflow",
    "decomposition_loop_too_short",
    "decomposition_zero_area",
    "decomposition_cell_not_convex",
)


@dataclass(frozen=True)
class Decomposition:
    """Разбивка либо названный отказ от неё. Третьего состояния нет."""
    #: Выпуклые ячейки. Пусто ровно тогда, когда `reason` не пуст.
    cells: tuple[tuple[Pt2, ...], ...] = ()
    #: Почему разбивки нет. `None` — она есть.
    reason: str | None = None
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.reason is None and bool(self.cells)


# ─────────────────────────────────────────────────────────── элементарное

def _clean(loop: Sequence[Sequence[float]]) -> list[Pt2] | None:
    """Контур -> список точек без ПОДРЯД ИДУЩИХ ПОВТОРОВ. `None` — не контур.

    Убирается только буквальный повтор координат: множество точек многоугольника
    от этого не меняется, поэтому это не выброс, а нормализация. Всё остальное
    (совпадение через одну, самопересечение) остаётся на проверках ниже.
    """
    pts: list[Pt2] = []
    for p in loop:
        if not (isinstance(p, (list, tuple)) and len(p) >= 2):
            return None
        x, y = p[0], p[1]
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))
                and math.isfinite(x) and math.isfinite(y)):
            return None
        q = (float(x), float(y))
        if pts and q == pts[-1]:
            continue
        pts.append(q)
    while len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts if len(pts) >= 3 else None


def signed_area(loop: Sequence[Pt2]) -> float:
    n = len(loop)
    return 0.5 * sum(loop[i][0] * loop[(i + 1) % n][1]
                     - loop[(i + 1) % n][0] * loop[i][1] for i in range(n))


def polygon_area(loop: Sequence[Pt2]) -> float:
    return abs(signed_area(loop))


def loop_is_convex(loop: Sequence[Pt2]) -> bool:
    """Выпуклость КАК ФАКТ О КОНТУРЕ, а не о его выпуклой оболочке.

    Нужна не ради красоты: у выпуклого контура без отверстий разбивка ничего
    не уточняет, и запись обязана остаться БАЙТ-В-БАЙТ прежней — иначе диф
    отчёта перестаёт быть читаемым, а вместе с ним и вопрос «что именно
    изменилось от волны».
    """
    n = len(loop)
    if n < 3:
        return True
    sign = 0
    for i in range(n):
        a, b, c = loop[i], loop[(i + 1) % n], loop[(i + 2) % n]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if cr == 0.0:
            continue
        s = 1 if cr > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def point_in_region(pt: Pt2, loops: Sequence[Sequence[Pt2]]) -> bool:
    """Лежит ли точка в области по правилу ЧЁТ-НЕЧЕТ на ИСХОДНЫХ контурах.

    Правило выбрано вместо ненулевой намотки намеренно: намотка зависит от
    ОРИЕНТАЦИИ контуров, а Revit не обещает, что отверстие придёт обходом в
    обратную сторону. Чёт-нечет от ориентации не зависит вовсе — а случай, где
    два правила расходятся (пересекающиеся контуры), ловит сверка площадей.

    Кода заметания здесь нет ни строчки: проверка обязана быть НЕЗАВИСИМОЙ от
    того, что проверяет.
    """
    x, y = pt
    inside = False
    for loop in loops:
        n = len(loop)
        for i in range(n):
            x0, y0 = loop[i]
            x1, y1 = loop[(i + 1) % n]
            if (y0 > y) != (y1 > y):
                xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if x < xc:
                    inside = not inside
    return inside


def interior_witness(cell: Sequence[Pt2]) -> Pt2:
    """Точка внутри ВЫПУКЛОЙ ячейки — среднее её вершин.

    ПОЧЕМУ НЕ ЦЕНТРОИД ПЛОЩАДИ. Он делится на площадь, а у тонкой ячейки
    площадь — разность почти равных чисел. Замер 10.08.2026 (пол 9981227
    фасада, ячейка шириной 2.3e-9 мм при длине 24 844 мм, площадь 2.9e-5 мм²):
    центроид площади вышел на 0.0126 мм ЗА СОБСТВЕННЫЙ диапазон x ячейки, то
    есть указал наружу тела, которое сам же описывает. Проверка на нём
    отказывала от совершенно исправной разбивки.

    Среднее вершин таких свойств не имеет по построению: это выпуклая
    комбинация с ПОЛОЖИТЕЛЬНЫМИ весами 1/n, поэтому оно лежит внутри выпуклой
    оболочки вершин при любой их конфигурации, и ни одного деления на малую
    величину в нём нет.
    """
    n = len(cell)
    return (math.fsum(p[0] for p in cell) / n, math.fsum(p[1] for p in cell) / n)


def clip_to_box(cell: Sequence[Pt2], x0: float, y0: float,
                x1: float, y1: float) -> tuple[Pt2, ...]:
    """ВЫПУКЛАЯ ячейка ∩ осеориентированный прямоугольник. Точно, без допусков.

    Отсечение Сазерленда–Ходжмена четырьмя полуплоскостями. Выпуклость входа —
    предпосылка (у вогнутого этот алгоритм врёт), и здесь она выполнена по
    построению: на вход идут ячейки заметания.

    ЗАЧЕМ ЭТО НУЖНО РОВНО ОДНОМУ ПОТРЕБИТЕЛЮ. Наружный прямоугольник дуги
    (`hulls._arc_outward_rect`) содержит дугу, но своими УГЛАМИ вылезает за
    габарит элемента: у четверти окружности радиуса R угол наружного
    прямоугольника отстоит от центра на 1.207R при габарите R. Замер
    10.08.2026 (`snowdon_plumb_v5`, пол 1424071): 21.06 % площади новой
    подошвы лежало ВНЕ габарита элемента, и это дало 10 находок, которых при
    прежнем коде не было. Габарит тело содержит — значит и пересечение с ним
    тело содержит, а лишний угол уходит.
    """
    out = list(cell)
    for inside, cut in (
            (lambda p: p[0] >= x0, lambda a, b: _cut(a, b, 0, x0)),
            (lambda p: p[0] <= x1, lambda a, b: _cut(a, b, 0, x1)),
            (lambda p: p[1] >= y0, lambda a, b: _cut(a, b, 1, y0)),
            (lambda p: p[1] <= y1, lambda a, b: _cut(a, b, 1, y1))):
        src, out = out, []
        n = len(src)
        for i in range(n):
            a, b = src[i], src[(i + 1) % n]
            ia, ib = inside(a), inside(b)
            if ia:
                out.append(a)
            if ia != ib:
                out.append(cut(a, b))
        if not out:
            return ()
    dedup: list[Pt2] = []
    for p in out:
        if not dedup or p != dedup[-1]:
            dedup.append(p)
    while len(dedup) > 1 and dedup[0] == dedup[-1]:
        dedup.pop()
    return tuple(dedup)


def _cut(a: Pt2, b: Pt2, ax: int, v: float) -> Pt2:
    d = b[ax] - a[ax]
    t = 0.0 if d == 0.0 else (v - a[ax]) / d
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _distance_to_boundary(pt: Pt2, loops: Sequence[Sequence[Pt2]]) -> float:
    best = math.inf
    for loop in loops:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            e = dx * dx + dy * dy
            t = 0.0 if e == 0.0 else max(0.0, min(
                1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / e))
            d = math.hypot(pt[0] - a[0] - dx * t, pt[1] - a[1] - dy * t)
            if d < best:
                best = d
    return best


def _convex_hull(pts: Sequence[Pt2]) -> tuple[Pt2, ...]:
    """Выпуклая оболочка набора точек (Эндрю). Своя, а не из `geom`.

    `decompose` не импортирует `geom` намеренно: разбивка обязана оставаться
    проверяемой независимо от того, что делает арифметика пар.
    """
    ps = sorted(set((float(x), float(y)) for x, y in pts))
    if len(ps) <= 2:
        return tuple(ps)

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lower: list[Pt2] = []
    for q in ps:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list[Pt2] = []
    for q in reversed(ps):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return tuple(lower[:-1] + upper[:-1])


def _vside(cell: Sequence[Pt2], right: bool) -> tuple[float, float, float] | None:
    """Вертикальная сторона ячейки: `(x, y_низ, y_верх)`. `None` — стороны нет.

    Ячейка заметания всегда ограничена слева и справа ВЕРТИКАЛЯМИ (это границы
    полосы), и после слияния это свойство сохраняется: у объединённой ячейки
    левая сторона левой соседки, правая — правой. Поэтому цепочку можно
    продолжать сколько угодно раз без особого случая.
    """
    xs = [p[0] for p in cell]
    x = max(xs) if right else min(xs)
    ys = sorted(p[1] for p in cell if p[0] == x)
    if len(ys) < 2 or ys[0] == ys[-1]:
        return None
    return (x, ys[0], ys[-1])


def _join(a: Sequence[Pt2], b: Sequence[Pt2],
          shared: tuple[float, float, float]) -> tuple[Pt2, ...] | None:
    """Объединение двух соседок, если оно ВЫПУКЛО. Иначе `None`.

    Проверок две, и обе обязательны:

    * ВЫПУКЛОСТЬ — иначе объединение нельзя отдать в SAT, ради чего вся
      разбивка и делается;
    * ПЛОЩАДЬ — сумма площадей соседок обязана совпасть с площадью
      объединения. Без этой проверки слияние молча ПОДМЕНЯЛО БЫ объединение
      его выпуклой оболочкой и добавляло бы площадь, которой в области нет.
      Огрубление наружу законом не запрещено, но оно обязано быть НАЗВАННЫМ, а
      тихое здесь — ровно то, что волна из модуля вычищала.
    """
    x1, ylo, yhi = shared
    xa = min(p[0] for p in a)
    xb = max(p[0] for p in b)
    ay = sorted(p[1] for p in a if p[0] == xa)
    by = sorted(p[1] for p in b if p[0] == xb)
    if len(ay) < 2 or len(by) < 2:
        return None
    hexa = [(xa, ay[0]), (x1, ylo), (xb, by[0]),
            (xb, by[-1]), (x1, yhi), (xa, ay[-1])]
    poly: list[Pt2] = []
    for p in hexa:
        if not poly or p != poly[-1]:
            poly.append(p)
    while len(poly) > 1 and poly[0] == poly[-1]:
        poly.pop()
    if len(poly) < 3 or not loop_is_convex(poly):
        return None
    want = polygon_area(a) + polygon_area(b)
    if want <= 0.0:
        return None
    if abs(polygon_area(poly) - want) > AREA_REL_TOL * want:
        return None
    return tuple(poly)


def merge_convex_neighbours(cells: Sequence[Sequence[Pt2]]
                            ) -> tuple[tuple[tuple[Pt2, ...], ...], int]:
    """Склеить соседние ячейки, чьё объединение выпукло. Возвращает `(ячейки, склеек)`.

    ЗАЧЕМ. Заметание продлевает ячейку вправо, только пока её ограничивают ТЕ
    ЖЕ ДВА РЕБРА. Стоит нижней границе перейти на соседнее ребро — ячейка
    закрывается, хотя объединение двух соседок сплошь и рядом выпукло и имеет
    полное право быть одной ячейкой. ЗАМЕР до правки (`w3_merge_probe.py`,
    11.08.2026, весь корпус): из 16 052 пар соседних ячеек 6 265 (39.0 %)
    имеют ВЫПУКЛОЕ объединение, то есть каждая третья граница проведена зря.

    Цена дробления двойная и обе половины измерены: 162 контура из 1 598
    упираются в `MAX_CELLS` и откатываются в выпуклую оболочку, а у остальных
    пара оболочек в узкой фазе стоит N*M сравнений подошв.

    ПОЧЕМУ СОВПАДЕНИЕ КООРДИНАТ ПРОВЕРЯЕТСЯ ТОЧНО, БЕЗ ДОПУСКА. Граница полосы
    всегда стоит на x ВЕРШИНЫ, а `y_at(ребро, x)` при x, равном концу ребра,
    возвращает координату этой вершины БИТ В БИТ (множитель обращается в 0 или
    1 точно). Ребро же меняется на границе полосы только в вершине. Значит у
    двух соседок общая сторона совпадает точно, и допуск здесь был бы не
    страховкой, а способом склеить то, что не смежно.

    Слияние ДЕТЕРМИНИРОВАНО: ячейки обходятся в порядке сортировки по
    координатам, а не в порядке появления.
    """
    cur = [tuple(c) for c in cells]
    joins = 0
    while len(cur) > 1:
        by_left: dict[tuple[float, float, float], list[int]] = {}
        for i, c in enumerate(cur):
            s = _vside(c, right=False)
            if s is not None:
                by_left.setdefault(s, []).append(i)
        order = sorted(range(len(cur)), key=lambda i: tuple(sorted(cur[i])))
        used: set[int] = set()
        out: list[tuple[Pt2, ...]] = []
        made = 0
        for i in order:
            if i in used:
                continue
            used.add(i)
            cell = cur[i]
            while True:
                r = _vside(cell, right=True)
                if r is None:
                    break
                cands = [j for j in by_left.get(r, ()) if j not in used]
                got = None
                for j in sorted(cands, key=lambda j: tuple(sorted(cur[j]))):
                    m = _join(cell, cur[j], r)
                    if m is not None:
                        got = (j, m)
                        break
                if got is None:
                    break
                used.add(got[0])
                cell = got[1]
                made += 1
            out.append(cell)
        joins += made
        cur = out
        if made == 0:
            break
    return tuple(cur), joins


# ─────────────────────────────────────────────────────────────── заметание

def decompose(exterior: Sequence[Sequence[float]],
              holes: Sequence[Sequence[Sequence[float]]] = (),
              *, max_work: int = MAX_SWEEP_WORK,
              max_cells: int = MAX_CELLS) -> Decomposition:
    """Область (внешний контур + отверстия) -> выпуклые ячейки либо отказ.

    Инвариант, который здесь ДОКАЗЫВАЕТСЯ, а не декларируется:

        объединение ячеек == объявленная область,

    с точностью до арифметики double (см. `AREA_REL_TOL`). Не «содержит» и не
    «содержится» — РАВНО. Именно поэтому подошва впервые перестаёт быть
    огрублением; почему при этом грейд НЕ становится `exact`, сказано в
    `hulls.UNREACHABLE_GRADE_REASONS` — оболочка это ещё и Z, а он по-прежнему
    берётся из объявленной отметки, а не из направления роста тела.
    """
    ext = _clean(exterior)
    if ext is None:
        return Decomposition(reason="decomposition_loop_too_short")
    loops: list[list[Pt2]] = [ext]
    for h in holes or ():
        c = _clean(h)
        if c is not None:                 # отверстие-вырожденка площади не несёт
            loops.append(c)

    area_declared = polygon_area(ext) - sum(polygon_area(h) for h in loops[1:])
    if area_declared <= 0.0:
        return Decomposition(reason="decomposition_zero_area",
                             stats={"area_declared": area_declared})

    # Рёбра. Вертикальные пропускаются НЕ как «мелкие», а как не несущие
    # площади: x-полоса режется ровно по ним, внутрь полосы они не попадают.
    edges: list[tuple[Pt2, Pt2]] = []
    for loop in loops:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            if a[0] == b[0]:
                continue
            edges.append((a, b) if a[0] < b[0] else (b, a))
    if not edges:
        return Decomposition(reason="decomposition_zero_area",
                             stats={"area_declared": area_declared})

    # Границы полос — значения x вершин. Слияние БЛИЗКИХ значений здесь было
    # бы выбросом тонкой полосы, то есть уменьшением области, и потому
    # запрещено. Слиянию подлежат ровно СОСЕДНИЕ DOUBLE — те, между которыми
    # НЕ СУЩЕСТВУЕТ представимого числа: у такой полосы нет середины, а значит
    # нет и точки, в которой можно спросить «внутри или снаружи».
    #
    # ЗАМЕР, ради которого это написано (11.08.2026, весь корпус): без слияния
    # 640 контуров из 1 633 (39.2 %) отказывались с `slab_underflow` и падали
    # обратно в выпуклую оболочку — потому что перевод футов в мм оставляет
    # вершины вида 1410.9127015655997 и 1410.9127015655999. Это ОДНА вершина
    # чертежа, разъехавшаяся в последнем разряде. После слияния отказов по
    # этой причине на корпусе НОЛЬ.
    #
    # Слияние ужимает область не более чем на (число слияний) x (шаг double) x
    # (высота) — величину, которой в мм не существует. Но обещать это мало:
    # ужатие ПРОВЕРЯЕТСЯ сверкой площадей ниже, и контур, у которого слияние
    # что-то сломало, отказывается по имени `decomposition_area_mismatch`.
    xs_all = sorted({p[0] for loop in loops for p in loop})
    xs = [xs_all[0]] if xs_all else []
    merged_x = 0
    for v in xs_all[1:]:
        if math.nextafter(xs[-1], math.inf) >= v:
            merged_x += 1
            continue
        xs.append(v)
    if len(xs) < 2:
        return Decomposition(reason="decomposition_zero_area",
                             stats={"area_declared": area_declared,
                                    "merged_x": merged_x})
    n_slabs = len(xs) - 1
    work = n_slabs * len(edges)
    if work > max_work:
        return Decomposition(reason="decomposition_over_cap",
                             stats={"work": work, "slabs": n_slabs,
                                    "edges": len(edges)})

    def y_at(e: tuple[Pt2, Pt2], x: float) -> float:
        (x0, y0), (x1, y1) = e
        return y0 + (y1 - y0) * ((x - x0) / (x1 - x0))

    #: Ячейка живёт как (x_левый, x_правый, ребро_низа, ребро_верха) и
    #: РАСТЁТ вправо, пока её ограничивают те же два ребра. Слияние точное:
    #: две соседние полосы с одной парой ограничивающих ПРЯМЫХ дают ровно ту
    #: же трапецию, что и одна широкая. Без слияния контур из 108 вершин давал
    #: бы сотню ячеек там, где хватает единиц.
    open_cells: dict[tuple[int, int], int] = {}
    raw: list[list] = []
    degenerate = 0

    for s in range(n_slabs):
        xl, xr = xs[s], xs[s + 1]
        xm = 0.5 * (xl + xr)
        if not (xl < xm < xr):
            # После слияния соседних double этого быть не может; если всё же
            # случилось — молчать нельзя, полосу не посчитать и не выбросить.
            return Decomposition(reason="decomposition_slab_underflow",
                                 stats={"x_left": xl, "x_right": xr})
        cross: list[tuple[float, int]] = []
        for ei, e in enumerate(edges):
            if e[0][0] < xm < e[1][0]:
                cross.append((y_at(e, xm), ei))
        if not cross:
            open_cells = {}
            continue
        if len(cross) % 2:
            # Нечётное число пересечений — контур пересекает сам себя либо
            # разомкнут. Расставить «внутри/снаружи» нечем.
            return Decomposition(reason="decomposition_odd_crossings",
                                 stats={"x_mid": xm, "crossings": len(cross)})
        cross.sort()
        nxt: dict[tuple[int, int], int] = {}
        for k in range(0, len(cross), 2):
            key = (cross[k][1], cross[k + 1][1])
            idx = open_cells.get(key)
            if idx is not None:
                raw[idx][1] = xr                      # продлеваем вправо
            else:
                raw.append([xl, xr, key[0], key[1]])
                idx = len(raw) - 1
                if len(raw) > RAW_CELL_CAP:
                    # Потолок СЫРЫХ ячеек — только чтобы заметание не съело
                    # память на вырожденном контуре. Настоящий потолок
                    # (`max_cells`) применяется ПОСЛЕ слияния: до него число
                    # ячеек ещё не является числом ячеек.
                    return Decomposition(
                        reason="decomposition_too_many_cells",
                        stats={"cells_raw": len(raw), "slabs": n_slabs,
                               "edges": len(edges)})
            nxt[key] = idx
        open_cells = nxt

    cells: list[tuple[Pt2, ...]] = []
    for xl, xr, lo_i, hi_i in raw:
        lo, hi = edges[lo_i], edges[hi_i]
        quad = [(xl, y_at(lo, xl)), (xr, y_at(lo, xr)),
                (xr, y_at(hi, xr)), (xl, y_at(hi, xl))]
        poly: list[Pt2] = []
        for p in quad:
            if not poly or p != poly[-1]:
                poly.append(p)
        if len(poly) > 1 and poly[0] == poly[-1]:
            poly.pop()
        # Вырожденная ячейка (отрезок/точка) площади не несёт, но и выброшена
        # быть не может: это точки области, а «молча не выбрасываем».
        if len(poly) < 3:
            degenerate += 1
        cells.append(tuple(poly))

    if not cells:
        return Decomposition(reason="decomposition_zero_area",
                             stats={"area_declared": area_declared})

    # ── проверка 1: площадь
    area_cells = sum(polygon_area(c) for c in cells if len(c) >= 3)
    residual = abs(area_cells - area_declared) / area_declared
    if residual > AREA_REL_TOL:
        return Decomposition(
            reason="decomposition_area_mismatch",
            stats={"area_declared": area_declared, "area_cells": area_cells,
                   "residual_rel": residual, "cells": len(cells)})

    # ── проверка 2: внутренняя точка каждой ячейки — внутри ИСХОДНОЙ области
    #
    # ТРИСТЕЙТ, А НЕ ДА/НЕТ. Луч чёт-нечета решает вопрос сравнением координат,
    # а у ячейки тоньше шага double сравнивать нечего: её внутренняя точка
    # отстоит от границы на считанные ULP, и предикат «внутри» перестаёт быть
    # определён — не «ложен», а именно НЕ ОПРЕДЕЛЁН. Такие ячейки считаются
    # НЕПРОВЕРЕННЫМИ и публикуются числом, ровно как `loops_overlap` публикует
    # своё `None`. Площадь их при этом уже учтена сверкой выше, поэтому
    # пропуска они не создают: спрятаться в них может лишь то, что тоньше
    # арифметики.
    #
    # Порог назван арифметикой, а не вкусом: `math.ulp(scale)` — истинный шаг
    # double в точке такого масштаба, и восьмикратный запас покрывает разброс
    # округлений в самой формуле расстояния.
    unverified = 0
    for c in cells:
        if len(c) < 3 or polygon_area(c) <= 0.0:
            unverified += 1
            continue
        w = interior_witness(c)
        if point_in_region(w, loops):
            continue
        scale = max(abs(w[0]), abs(w[1]), 1.0)
        if _distance_to_boundary(w, loops) <= 8.0 * math.ulp(scale):
            unverified += 1
            continue
        return Decomposition(
            reason="decomposition_cell_outside_region",
            stats={"cell": [list(p) for p in c], "cells": len(cells),
                   "witness": list(w)})

    # ── слияние выпуклых соседок. Объединение ячеек НЕ МЕНЯЕТСЯ как множество
    #    (это проверяет `_join` сверкой площадей), поэтому все проверки выше
    #    остаются в силе; меняется только то, сколькими выпуклыми кусками оно
    #    записано.
    raw_cells = len(cells)
    merged, joins = merge_convex_neighbours(cells)
    area_merged = sum(polygon_area(c) for c in merged if len(c) >= 3)
    if abs(area_merged - area_cells) > AREA_REL_TOL * max(area_declared, 1.0):
        # Слияние обязано сохранять площадь до последнего разряда. Не
        # сохранило — не сливаем вовсе, а не «сливаем и надеемся».
        merged, joins = tuple(tuple(c) for c in cells), 0
    # ── ИНВАРИАНТ НАБОРА, а не свойство алгоритма. Всё, что стоит ниже по
    #    конвейеру, — SAT, точное расстояние, замкнутая форма наименьшего
    #    выхода — суть теоремы о ВЫПУКЛЫХ множествах. Невыпуклый кусок,
    #    попавший в набор, не вызовет ошибки: он молча вернёт ответ выпуклой
    #    оболочки, то есть ровно тот дефект, ради устранения которого заведён
    #    `geom.PrismSet`. Поэтому выпуклость КАЖДОЙ ячейки проверяется здесь, а
    #    не выводится из того, что заметание выпускает трапеции, а слияние
    #    якобы их сохраняет.
    repaired = 0
    fixed_cells: list[tuple[Pt2, ...]] = []
    for c in merged:
        if len(c) < 3 or loop_is_convex(c):
            fixed_cells.append(tuple(c))
            continue
        # ОТКУДА ЭТО БЕРЁТСЯ. Замер 11.08.2026: все 20 таких ячеек корпуса
        # выпускает ЗАМЕТАНИЕ, ни одной — слияние. Все двадцать вырождены:
        # у примера (`k2_ar_rd_v14`, элемент 15949387) четыре вершины
        # различаются по x в восемнадцатом разряде (18800.000000019340 против
        # 18800.000000019358), три из четырёх y совпадают. Это не многоугольник,
        # это арифметическая пыль на почти вертикальном ребре.
        #
        # ЧИНИТЬ ВЫПУКЛОЙ ОБОЛОЧКОЙ ЗАКОННО РОВНО ПОКА ПЛОЩАДЬ НЕ РАСТЁТ.
        # Оболочка вырожденного набора точек вырождена и сама, поэтому площадь
        # остаётся нулевой, объединение не меняется ни на мм², а куски снова
        # выпуклы. Если же площадь выросла — кусок был невыпуклым ПО СУЩЕСТВУ,
        # и тогда отказ, а не починка: подменять область её выпуклой оболочкой
        # молча запрещено тем же законом, что и всё остальное здесь.
        hull = _convex_hull(c)
        if len(hull) >= 3 and abs(polygon_area(hull) - polygon_area(c)) >                 AREA_REL_TOL * max(area_declared, 1.0):
            return Decomposition(
                reason="decomposition_cell_not_convex",
                stats={"cell": [list(q) for q in c], "cells": len(merged),
                       "merges": joins})
        repaired += 1
        fixed_cells.append(tuple(hull) if hull else tuple(c))
    merged = tuple(fixed_cells)
    if len(merged) > max_cells:
        return Decomposition(
            reason="decomposition_too_many_cells",
            stats={"cells": len(merged), "cells_raw": raw_cells,
                   "merges": joins, "slabs": n_slabs, "edges": len(edges)})
    cells = list(merged)

    return Decomposition(
        cells=tuple(cells),
        stats={"cells": len(cells), "cells_raw": raw_cells, "merges": joins,
               "slabs": n_slabs, "edges": len(edges),
               "work": work, "degenerate_cells": degenerate,
               "cells_unverified": unverified, "merged_x": merged_x,
               "cells_repaired": repaired,
               "holes": len(loops) - 1,
               "area_declared": area_declared, "area_cells": area_cells,
               "residual_rel": residual})
