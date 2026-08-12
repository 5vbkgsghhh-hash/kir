"""KIR static geometry law (v1.1, VISION §5а / slab-saga fixes).

Everything a runtime Revit refusal taught us on 2026-07-17 is caught at the
T stage now: the duplicate closing point (iter-1: ShortCurveTolerance) is
NORMALIZED away ("closed ring implied"), any other near-zero edge and any
self-intersection is a typed refusal, and a hole touching the outer boundary
(iter-2: "curve loops intersect") never reaches Revit. Pure python, shared
by validate() and future reference-interpreter (12.6c).
"""
from __future__ import annotations

import math

from kukai.ir.diag import Diagnostic, TYPE_BOUNDS, TYPE_GEOM_RELATION

_EDGE_TOL = 1.0          # mm: edges shorter than this are runtime kills
_TOUCH_TOL = 1.0         # mm: hole vertex closer than this to the outline = touch

# ───────────────────── ЗАКОН МНОГОУГОЛЬНОГО ПРОФИЛЯ ──────────────────────────
#
# ОДИН ВЛАДЕЛЕЦ НА ОБА ХОДА, и это не вкус. До 10.08.2026 эти четыре числа
# стояли ГОЛЫМИ ЛИТЕРАЛАМИ в трёх местах сразу, и у трёх мест РАЗНАЯ ЦЕНА
# расхождения:
#
#   * ``authoring_validation`` (прямой ход) — превышение это ТИПИЗОВАННЫЙ
#     ОТКАЗ, который пользователь видит: KIR-T001 с `expected`/`got`;
#   * ``decompile/lift`` (обратный ход) — превышение МОЛЧА превращает элемент
#     в атом. Собственный комментарий лифтера гласил «Mirror the existing
#     forward polygon laws», то есть он ЗНАЛ, что повторяет чужой закон, и
#     всё равно переписывал числа своей рукой;
#   * ``contour`` (подъязык КОНТУР) — тот же профиль, третий набор литералов.
#
# Расхождение любой пары даёт худший из возможных исходов этого компилятора:
# лифтер отдаёт атом там, где компилятор построил бы, либо строит программу,
# которую компилятор отвергнет, — и в обоих случаях диагноз назовёт следствие.
# Поэтому здесь ИМЯ, а там СЫЛКА на имя; второго ответа на вопрос «сколько
# точек держит профиль» в дереве больше нет.
#
# ПРОИСХОЖДЕНИЕ — НАЗНАЧЕНО, НЕ ЗАМЕРЕНО. Числа пришли с самим языком:
# 3..64 точки и площадь 0.01 м² — `693da3df` (16.07.2026, «v1 op-set full»),
# 8 отверстий по 32 точки — оттуда же, КОНТУР повторил их `6875d574`
# (17.07.2026, «v2 invention»), лифтер — `a0b689d9` (18.07.2026). Ни одно из
# них не выведено из предела Revit и не замерено на здании; это выбор автора
# языка про то, какой профиль стоит выражать оп-кодом, а не свойство Revit.
# Сказано прямо, потому что «граница, сочинённая рассуждением» — родовой
# дефект этого кода (`create_door.sill_mm min_val=0`, `_SHEET_LIMIT_MM`), и
# следующий, кто захочет её подвинуть, должен видеть, что двигать можно.
#
# ЧТО ПРО НИХ ИЗВЕСТНО ЗАМЕРОМ, а не рассуждением (`tools/bounds_audit.py
# --measure`, 10.08.2026, три сохранённых разбора: k2_ar_rd_v6 «13A-RD-AR-K2»,
# демо-v3, sob62_fas_r23_v17). Цифры стоят рядом с каждым именем ниже; общий
# их смысл в том, что ДВЕ из четырёх отвергают настоящие здания, а ДВЕ не
# отвергли ничего. Ни то, ни другое здесь не исправляется: волна 10.08 — про
# ИМЕНА, и подвинуть значение молча значило бы спрятать замер под рефакторинг.
MIN_RING_POINTS = 3            # меньше трёх точек — не многоугольник

#: Точек во ВНЕШНЕМ кольце профиля. ОТВЕРГАЕТ ЖИВЬЁМ: 67 колец из 652 на трёх
#: зданиях (башня 65/317, демо 2/235, фасад 0/100), худшее кольцо — 130 точек,
#: вдвое выше предела. На прямом ходу это отказ, который автор увидит; на
#: обратном — молчаливый атом, и это те самые элементы, которые перепись
#: границ 31.07 поставила на первое место рейтинга вреда.
MAX_RING_POINTS = 64

#: Отверстий (внутренних колец) в одном профиле. ЗАМЕР: 0 отвергнутых на трёх
#: зданиях. «Не сработала» — не то же самое, что «верна»: корпус из трёх
#: зданий её просто не достаёт.
MAX_HOLES = 8

#: Точек в кольце ОТВЕРСТИЯ. САМАЯ ВРЕДНАЯ ИЗ ЧЕТЫРЁХ, и это видно только
#: замером: 82 кольца из 183 отвергнуты, причём ВСЕ 82 — на одном здании,
#: где их 82 из 85 (96 %); худшее кольцо 92 точки. Здание демо-v3 из-за неё
#: почти целиком теряет отверстия в профилях. Отдельно стоит несогласие с
#: соседом: маршрут КОНТУРА меряет кольцо отверстия тем же
#: `MAX_RING_POINTS`=64, то есть на один и тот же профиль в дереве два разных
#: ответа — 32 по маршруту многоугольника и 64 по маршруту контура. Оба
#: наблюдения ЗАВЕДЕНЫ КАК НАХОДКА и НЕ ЧИНЯТСЯ здесь.
MAX_HOLE_RING_POINTS = 32

#: 0.01 м²: вырожденное кольцо, а не профиль. ЗАМЕР: 0 отвергнутых из 709
#: колец, и запас огромен — наименьшее настоящее кольцо башни 62 500 мм²,
#: вшестеро выше предела.
MIN_RING_AREA_MM2 = 10_000.0

#: ОТКРЫТАЯ ломаная (`path` у ограждения, `path3` у гибкой подводки). Нижняя
#: граница СВОЯ и обоснована в `registry_base.ParamSpec`: прямой марш — это
#: две точки и нулевая площадь, под кольцом он был бы отвергнут как
#: «вырожденный контур». Верхнее значение исторически совпадает с кольцом,
#: но это ДРУГАЯ политика: будущий замер может поднять предел профиля, не
#: расширяя автоматически railing/flex paths. Поэтому значение сохранено,
#: а не заимствовано через имя соседней границы.
MIN_PATH_POINTS = 2
MAX_PATH_POINTS = 64


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cross(o, p, q) -> float:
    return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])


def _seg_intersect(a, b, c, d) -> bool:
    """Whether two closed 2D segments intersect, including touch/overlap.

    Callers that compare edges from the same ring already skip adjacent pairs;
    inclusive semantics are required for non-adjacent vertex touches, collinear
    overlaps, and hole-boundary contact (all invalid Revit curve-loop inputs).
    """
    eps = 1e-9

    def sign(x):
        return 1 if x > eps else -1 if x < -eps else 0

    def on_segment(p, q, r):
        return (min(p[0], r[0]) - eps <= q[0] <= max(p[0], r[0]) + eps
                and min(p[1], r[1]) - eps <= q[1] <= max(p[1], r[1]) + eps)

    o1, o2 = sign(_cross(a, b, c)), sign(_cross(a, b, d))
    o3, o4 = sign(_cross(c, d, a)), sign(_cross(c, d, b))
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return ((o1 == 0 and on_segment(a, c, b))
            or (o2 == 0 and on_segment(a, d, b))
            or (o3 == 0 and on_segment(c, a, d))
            or (o4 == 0 and on_segment(c, b, d)))


def _point_in_poly(pt, poly) -> bool:
    x, y = pt[0], pt[1]
    inside = False
    n = len(poly)
    for k in range(n):
        x1, y1 = poly[k][0], poly[k][1]
        x2, y2 = poly[(k + 1) % n][0], poly[(k + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def _pt_seg_dist(pt, a, b) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    L2 = vx * vx + vy * vy
    if L2 == 0:
        return _dist(pt, a)
    t = max(0.0, min(1.0, ((pt[0] - a[0]) * vx + (pt[1] - a[1]) * vy) / L2))
    return _dist(pt, (a[0] + t * vx, a[1] + t * vy))


def ring_normalize(pts: list, oid, field: str, diags: list):
    """Cleaned open ring, or None with a typed diagnostic appended."""
    ring = [[p[0], p[1]] for p in pts]
    # Не «>= 4», а «кольцо ПЛЮС повторённая первая точка»: снять дубликат
    # можно только там, где под ним остаётся законный многоугольник.
    if len(ring) >= MIN_RING_POINTS + 1 and _dist(ring[0], ring[-1]) < _EDGE_TOL:
        ring = ring[:-1]        # explicit closure tolerated -> normalized away
    if len(ring) < MIN_RING_POINTS:
        diags.append(Diagnostic(code=TYPE_BOUNDS, op_id=oid, field_name=field,
                                message_ru=f"{field}: после нормализации замыкания меньше 3 точек"))
        return None
    n = len(ring)
    for k in range(n):
        if _dist(ring[k], ring[(k + 1) % n]) < _EDGE_TOL:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=field,
                got=[ring[k], ring[(k + 1) % n]],
                message_ru=(f"{field}: нулевое ребро (точки {k}/{(k + 1) % n} совпадают) — "
                            "в рантайме это ShortCurveTolerance, ловится статически")))
            return None
    for a in range(n):
        for b in range(a + 2, n):
            if a == 0 and b == n - 1:
                continue        # adjacent through the closing edge
            if _seg_intersect(ring[a], ring[(a + 1) % n], ring[b], ring[(b + 1) % n]):
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
                    message_ru=f"{field}: самопересечение контура (рёбра {a} и {b})"))
                return None
    return ring


def check_holes_relation(outline: list, holes: list, oid, diags: list,
                         field_prefix: str = "holes") -> bool:
    """Holes strictly inside the outline (touching an edge == runtime
    'curve loops intersect'), pairwise disjoint, edges non-crossing."""
    ok = True
    no = len(outline)
    for hi, hole in enumerate(holes):
        for pt in hole:
            if not _point_in_poly(pt, outline):
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid,
                    field_name=f"{field_prefix}[{hi}]",
                    got=pt, message_ru=f"{field_prefix}[{hi}]: точка вне внешнего контура"))
                ok = False
                break
            if any(_pt_seg_dist(pt, outline[k], outline[(k + 1) % no]) < _TOUCH_TOL
                   for k in range(no)):
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid,
                    field_name=f"{field_prefix}[{hi}]",
                    got=pt,
                    message_ru=(f"{field_prefix}[{hi}]: касание внешней границы — в рантайме "
                                "'curve loops intersect'; отступите внутрь")))
                ok = False
                break
        if not ok:
            continue
        nh = len(hole)
        for k in range(nh):
            if any(_seg_intersect(hole[k], hole[(k + 1) % nh],
                                  outline[m], outline[(m + 1) % no])
                   for m in range(no)):
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid,
                    field_name=f"{field_prefix}[{hi}]",
                    message_ru=f"{field_prefix}[{hi}]: ребро пересекает внешний контур"))
                ok = False
                break
    for hi in range(len(holes)):
        for hj in range(hi + 1, len(holes)):
            hit = (any(_point_in_poly(pt, holes[hj]) for pt in holes[hi])
                   or any(_point_in_poly(pt, holes[hi]) for pt in holes[hj])
                   or any(_seg_intersect(holes[hi][a], holes[hi][(a + 1) % len(holes[hi])],
                                         holes[hj][b], holes[hj][(b + 1) % len(holes[hj])])
                          for a in range(len(holes[hi]))
                          for b in range(len(holes[hj]))))
            if hit:
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid,
                    field_name=f"{field_prefix}[{hj}]",
                    message_ru=(f"{field_prefix}[{hi}] и {field_prefix}[{hj}] "
                                "пересекаются/вложены")))
                ok = False
    return ok


# ── ОБЛАКО ТОЧЕК ПОВЕРХНОСТИ (род `pts_xyz`, wave/site 2026-08-09) ──────────
#
# Отдельный род, а не `pts`, и не `mesh`. От `pts` его отличает третья
# координата, и она здесь НЕСУЩАЯ: у рельефа отметка земли живёт в Z каждой
# точки, а TopographySurface.Create не принимает уровня вовсе — плоский
# [x,y] обнулил бы весь рельеф в плоскость МОЛЧА. От `mesh` — тем, что
# треугольников нет: их строит Revit, и требовать их от автора значило бы
# требовать работу, которую платформа делает сама.
#
# ПРЕДЕЛЫ ЗАИМСТВОВАНЫ, А НЕ ПРИДУМАНЫ, и заимствованы у замера, а не у вкуса:
# MAX_VERTICES/_COORD_MAX_MM берутся из mesh.py, где под ними лежит таблица
# замера компайл-сервиса 29.07 (эмиссия литерального массива точек растёт
# линейно, ~33 символа на элемент, обрыва нет) и вывод из 20-мильного предела
# Revit. Эмиссия здесь ТА ЖЕ по форме — литеральный массив точек, — поэтому
# заводить своё число значило бы завести вторую границу о том же самом.

def validate_points_xyz(value, oid, field: str, diags: list, *,
                        min_points: int = 3):
    """Облако точек [x,y,z] мм -> нормализованный список, или None + отказ.

    Три закона, и ни одного тихого исправления входа (тихая правка в этом
    доме уже стоила 96.77% групп):

    1. ФОРМА И ПРЕДЕЛЫ: 3..MAX_VERTICES точек, каждая — три конечных числа в
       пределах ±_COORD_MAX_MM.
    2. ОДИН XY — ОДНА ОТМЕТКА. Две точки с совпадающим планом (ближе
       _WELD_TOL_MM) противоречивы: поверхность рельефа 2.5-мерна, и «какая
       здесь земля» у неё ровно один ответ. Принять обе значит позволить
       Revit молча выбрать одну — то есть построить не тот рельеф. Отказ
       НАЗЫВАЕТ обе точки. Закон ВЫВЕДЕН из 2.5-мерности элемента, а не
       замерен на живом Revit, и это сказано здесь прямо.
    3. НЕ ПРЯМАЯ. Все точки на одной прямой в плане дают вырожденную
       поверхность нулевой площади. Проверка точная и линейная: берём самую
       далёкую от первой точку, меряем максимальное расстояние остальных до
       этой прямой. Габаритной рамкой такое не ловится — диагональная
       цепочка точек имеет ненулевые оба размера рамки (прибор на часть
       диапазона опаснее отсутствующего).
    """
    from kukai.ir.emit_utils import is_finite_number
    from kukai.ir.mesh import MAX_VERTICES, _COORD_MAX_MM, _WELD_TOL_MM

    if not (isinstance(value, list) and min_points <= len(value) <= MAX_VERTICES):
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid, field_name=field, got=value,
            message_ru=(f"{field} — {min_points}..{MAX_VERTICES} точек "
                        f"[x,y,z] в мм")))
        return None
    pts = []
    for k, pt in enumerate(value):
        if not (isinstance(pt, list) and len(pt) == 3
                and all(is_finite_number(c) for c in pt)):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}[{k}]", got=pt,
                message_ru=(f"{field}[{k}] — точка [x,y,z] мм из трёх "
                            f"конечных чисел")))
            return None
        if any(abs(float(c)) > _COORD_MAX_MM for c in pt):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}[{k}]", got=pt,
                message_ru=(f"{field}[{k}]: координата вне ±{_COORD_MAX_MM:.0f} "
                            f"мм от начала координат")))
            return None
        pts.append([float(pt[0]), float(pt[1]), float(pt[2])])
    # Закон 2 — план-дубликаты. Решётка вместо попарного перебора: 4096 точек
    # дали бы 8 млн сравнений на каждой компиляции.
    cell = {}
    for k, pt in enumerate(pts):
        gx, gy = int(pt[0] / _WELD_TOL_MM), int(pt[1] / _WELD_TOL_MM)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                other = cell.get((gx + dx, gy + dy))
                if other is not None and _dist(pts[other], pt) < _WELD_TOL_MM:
                    diags.append(Diagnostic(
                        code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
                        got=[pts[other], pt],
                        message_ru=(
                            f"{field}: точки {other} и {k} стоят в одном "
                            f"плане ({pt[0]:.1f}, {pt[1]:.1f}) с разной "
                            f"отметкой — у рельефа в одной точке плана ровно "
                            f"одна земля, и выбирать между ними за вас "
                            f"компилятор не станет")))
                    return None
        cell[(gx, gy)] = k
    # Закон 3 — вырождение в прямую.
    far = max(range(len(pts)), key=lambda i: _dist(pts[0], pts[i]))
    base = _dist(pts[0], pts[far])
    if base < _EDGE_TOL or max(
            abs(_cross(pts[0], pts[far], p)) / base for p in pts) < _EDGE_TOL:
        diags.append(Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
            message_ru=(f"{field}: все точки лежат на одной прямой в плане — "
                        f"поверхности нулевой площади в модели не бывает")))
        return None
    return pts
