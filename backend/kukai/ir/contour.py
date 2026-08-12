"""KIR CONTOUR — the sketch-geometry sublanguage (v2 invention, 2026-07-17).

THE PINNED DECISIONS (Sonnet waves tile new sketch-ops on these; changing any
of them is a Fable-level language change, not a patch):

1. CANONICAL LOWERED FORM: every profile shape lowers to a closed edge list
   [(p0_mm, p1_mm, bulge), ...] — p1 of edge k == p0 of edge k+1, ring closed
   implicitly. `bulge` is the DXF convention: tan(sweep/4), 0 = straight
   line, sign = CCW positive. ALL trigonometry happens at COMPILE time in
   python — emitted C# only ever sees three literal points per arc
   (Arc.Create(start, end, pointOnArc), version-safe 2014+).
2. CLOSED BY CONSTRUCTION beats closed-by-check: rect/l/ring shapes cannot
   express an open or self-intersecting region at all; only `poly` needs the
   full static law (normalize closure, short edges, self-intersection with
   arcs sampled at 8 chords — deterministic documented approximation).
3. ANCHORS: any point is a literal [x,y] OR an ADDRESS resolved at ground
   time from the grids pool (id/name/p0_mm/p1_mm); a missing / duplicate /
   geometry-less / near-parallel grid is a typed refusal with candidates.
   No other anchor kinds in v2.0 of CONTOUR.
   ОБНОВЛЕНО 04.08.2026: грамматика адреса переехала целиком в `relate.py`
   (RELATE), и CONTOUR стал её потребителем — `resolve_anchor` больше не
   владеет ни разбором, ни отказами. Легаси-форма `offset_mm: [dx,dy]`
   (МИРОВАЯ рамка) сохранена ровно здесь и ровно ради голденов `region`;
   новая форма отступа — узловая, `{"grid": "Б", "offset_mm": 200,
   "toward": "В"}`, и она работает и в `region` тоже.
4. A REGION = {"outer": <shape>, "holes": [<shape>...]} — holes obey the
   same shape laws recursively, must lie strictly inside the outer (arc
   sample points included), pairwise disjoint. Same law set as v1.1 geom.py,
   lifted to arcs.
5. TOLERANCES (single source): _EDGE_TOL=1mm, |bulge|<=1.5, radius form
   requires radius >= chord/2 * 1.0005, area >= 1e4 mm².

Shapes v2.0:
  {"shape":"rect", "origin": <anchor>, "size_mm":[w,h], "rotation_deg"?:a}
  {"shape":"l",    "origin": <anchor>, "size_mm":[W,H], "cut_mm":[cw,ch],
                   "corner"?: "ne"|"nw"|"se"|"sw" (default "ne")}
  {"shape":"poly", "points_mm":[<anchor>...>=3],
                   "arcs"?: [{"edge":i, "bulge":b} | {"edge":i, "radius_mm":r,
                              "dir"?: "ccw"|"cw"}]}
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kukai.ir import relate
from kukai.ir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS, TYPE_GEOM_RELATION
from kukai.ir.emit_utils import is_finite_number
from kukai.ir.geom import (
    MAX_HOLES,
    MAX_RING_POINTS,
    MIN_RING_AREA_MM2,
    MIN_RING_POINTS,
    _dist,
    _seg_intersect,
    check_holes_relation,
)

_EDGE_TOL = 1.0

#: Верхняя граница языка для DXF bulge. Публичное имя читает и обратный ход:
#: приватная копия здесь позволяла лифтеру принять дугу, которую forward затем
#: отвергал бы. Значение сохранено; его происхождение пока назначенное, а не
#: измеренное ограничение Revit.
MAX_ARC_BULGE = 1.5
ARC_SAMPLES = 8

#: ГРАНИЦА ЯЗЫКА между прямым ребром и дугой, безразмерная (bulge =
#: 2·стрелка/хорда). Ниже неё дуга НЕ ВЫРАЖАЕТСЯ: прямой ход отвергает
#: авторский bulge (`_validate_shape`), обратный не записывает дугу
#: (`lift._bulge_from_midpoint`). Один вопрос — один ответ; до 10.08.2026
#: число стояло голым литералом по обе стороны хода, и разъехавшись они дали
#: бы лифтеру право сочинить программу, которую компилятор тут же отвергнет.
#: НАЗНАЧЕНО, не замерено. Замер рядом есть, но он про другое и это важно не
#: спутать: 28.07 сверка 3051 дуги двух разборов дала худшую невязку
#: обратного хода 2.4e-8 мм (`lift._ARC_BULGE_TOL_MM`) — то есть точность
#: пересчёта, а не порог, с которого дуга считается дугой.
MIN_ARC_BULGE = 1e-6

#: ЗАЩИТНАЯ СЕТКА ЭМИССИИ, не граница языка. Отвечает на вопрос «рисовать
#: `Line.CreateBound` или `Arc.Create`» и стоит на три порядка ниже
#: `MIN_ARC_BULGE` НАМЕРЕННО: полоса (1e-9, 1e-6) недостижима с обеих сторон
#: — прямой ход её отвергает, обратный туда не пишет, — поэтому сетка ловит
#: только вычисленный изнутри bulge (макро-преобразование, тело вращения).
#: Ставить её на уровень границы языка значило бы делить на почти-ноль в
#: `_arc_geometry`. Семь копий этого числа в трёх модулях (contour,
#: opening_emit, struct_emit) решали, ПРЯМУЮ или ДУГУ построит Revit; с
#: 10.08.2026 копия одна.
STRAIGHT_BULGE_EPS = 1e-9

#: Сколько знаков после запятой печатают `emit_loop_cs`/`emit_curvearray_cs`.
#: Число стояло литералом `round(..., 2)` в шести местах и было НЕНАХОДИМО:
#: волна тел выводит из него собственную погрешность границы, а вывод из
#: числа, у которого нет имени, разъезжается с оригиналом на первой правке
#: (ровно 103 «голых литерала в сравнении» насчитал bounds_audit 31.07).
_EMIT_DECIMALS = 2

#: КВАНТ ЭМИССИИ КООРДИНАТЫ, мм. Полное следствие `_EMIT_DECIMALS`: точка,
#: напечатанная с двумя знаками, отстоит от идеальной не дальше половины
#: кванта по каждой оси. Волна тел складывает его с `VertexTolerance` Revit,
#: получая ПОЛНУЮ погрешность границы построенного тела.
EMIT_COORD_QUANTUM_MM = 10.0 ** (-_EMIT_DECIMALS)

#: `KIR-G105` (`GRID_ANCHOR_UNRESOLVED`) ВЫВЕДЕН ИЗ УПОТРЕБЛЕНИЯ 04.08.2026.
#:
#: Он покрывал три разных случая — «имени нет», «геометрии нет», «пересечения
#: нет» — то есть три РАЗНЫХ РЕМОНТА одним кодом, и потому не мог назвать
#: следующий ход ни в одном из них. Расщеплён на `relate.GRID_NOT_FOUND`
#: (G108), `GRID_NO_GEOMETRY` (G111) и `GRID_NO_INTERSECTION` (G110).
#: Имя не переиспользуется: код, который значил три вещи, не должен получить
#: четвёртую.


# ── anchors ──────────────────────────────────────────────────────────────────

def anchor_is_literal(a) -> bool:
    return (isinstance(a, list) and len(a) == 2
            and all(is_finite_number(c) for c in a))


def anchor_is_grid(a) -> bool:
    return relate.is_address(a)


def resolve_anchor(a, grids_pool: list, oid, field: str, diags: list) -> Optional[list]:
    """Literal passes through; `at_grid` resolves through :mod:`relate`.

    ОДНА ГРАММАТИКА, ОДИН РЕЗОЛВЕР. До 04.08 адресация от осей жила ЗДЕСЬ и
    несла три латентных дефекта (мировая рамка отступа, тихий выбор при
    совпадении имён, непроверенная обусловленность). Обобщать её на все
    точечные параметры, не починив, значило бы размножить дефект фундамента
    на двадцать два новых параметра — поэтому починка живёт в одном месте, а
    CONTOUR стал её потребителем, а не вторым владельцем.

    ``allow_world_offset=True`` — ИМЕНОВАННАЯ легаси-дверь ровно для `region`:
    форма ``{"at_grid": [...], "offset_mm": [dx, dy]}`` шиппится с 17.07 и
    стоит в голденах. В новых слотах она закрыта (см. `relate`).
    """
    if anchor_is_literal(a):
        return [float(a[0]), float(a[1])]
    # ВТОРОЕ СЕМЕЙСТВО УЗЛОВ ЗДЕСЬ НЕ ПРИНИМАЕТСЯ, И ПРИЧИНА НАЗВАНА (09.08).
    # Адрес от элемента читает не снапшот, а уже заземлённые опы программы, а
    # регион опускается в рёбра из `validate_region`, которому программу не
    # передают. Сказать «неизвестная форма точки» значило бы послать автора
    # чинить синтаксис вместо того, чтобы объяснить границу: сегодня форма
    # верная, а слот — нет.
    if relate.is_element_address(a):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=a,
            message_ru=(
                f"{field}: адрес от элемента ({{at_element: ...}}) в углу "
                f"контура не принимается — контур опускается в рёбра ДО того, "
                f"как программа заземлена, и числа адресуемого опа здесь ещё "
                f"неизвестны. Годятся [x,y] мм и адрес от осей "
                f"{{at_grid:[имя,имя]}}")))
        return None
    if not isinstance(a, dict) or "at_grid" not in a:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=a,
            message_ru=f"{field}: точка — [x,y] мм или {{at_grid:[имя,имя], offset_mm?}}"))
        return None
    return relate.resolve_address(a, grids_pool, oid, field, diags, dims=2,
                                  allow_world_offset=True)


# ── arc math (ALL at compile time) ───────────────────────────────────────────

def bulge_midpoint(p0, p1, bulge: float) -> list:
    """Point on the arc at mid-sweep — the third point Arc.Create needs."""
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    # DXF bulge is positive for a CCW sweep from p0 to p1.  The midpoint
    # therefore lies on the RIGHT side of the directed chord; the circle
    # centre lies on the left for a positive minor arc.
    ch = math.hypot(dx, dy)
    if ch < 1e-9:
        return [mx, my]
    nx, ny = -dy / ch, dx / ch
    s = bulge * ch / 2.0
    return [mx - nx * s, my - ny * s]


def radius_to_bulge(p0, p1, radius: float, ccw: bool, oid, field: str,
                    diags: list) -> Optional[float]:
    ch = _dist(p0, p1)
    if radius < ch / 2.0 * 1.0005:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid, field_name=field,
            expected=f">={ch / 2.0:.1f}", got=radius,
            message_ru=f"{field}: радиус меньше половины хорды ({ch:.0f}мм) — дуга невозможна"))
        return None
    half = math.asin(min(1.0, ch / (2.0 * radius)))    # minor arc only in v2.0
    b = math.tan(half / 2.0)
    return b if ccw else -b


def _arc_geometry(p0, p1, bulge: float) -> tuple:
    """(centre, radius, start_angle, signed_sweep) for a DXF-bulge arc."""
    sweep = 4.0 * math.atan(bulge)
    ch = _dist(p0, p1)
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    nx, ny = -dy / ch, dx / ch
    centre_offset = ch * (1.0 - bulge * bulge) / (4.0 * bulge)
    cx, cy = mx + nx * centre_offset, my + ny * centre_offset
    radius = ch * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
    start = math.atan2(p0[1] - cy, p0[0] - cx)
    return (cx, cy), radius, start, sweep


def _sample_arc(p0, p1, bulge: float) -> list:
    """8-chord deterministic approximation for intersection/containment laws."""
    if abs(bulge) < STRAIGHT_BULGE_EPS:
        return [list(p0), list(p1)]
    (cx, cy), r, a0, sweep = _arc_geometry(p0, p1, bulge)
    pts = []
    for k in range(ARC_SAMPLES + 1):
        a = a0 + sweep * k / ARC_SAMPLES
        pts.append([cx + r * math.cos(a), cy + r * math.sin(a)])
    pts[0], pts[-1] = list(p0), list(p1)   # exact endpoints
    return pts


def edges_to_sample_poly(edges: list) -> list:
    """Flatten (with arc sampling) to a plain polygon for the v1.1 geom laws."""
    poly = []
    for p0, p1, b in edges:
        seg = _sample_arc(p0, p1, b)
        poly.extend(seg[:-1])
    return poly


def edges_bbox(edges: list) -> tuple:
    """Exact axis-aligned bounds, including every arc cardinal extremum."""
    points = []
    tau = 2.0 * math.pi
    for p0, p1, bulge in edges:
        points.extend((p0, p1))
        if abs(bulge) < STRAIGHT_BULGE_EPS:
            continue
        (cx, cy), radius, start, sweep = _arc_geometry(p0, p1, bulge)
        for angle in (0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0):
            travelled = ((angle - start) % tau if sweep > 0
                         else (start - angle) % tau)
            if travelled <= abs(sweep) + 1e-12:
                points.append([cx + radius * math.cos(angle),
                               cy + radius * math.sin(angle)])
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


# ── shapes → canonical edges ─────────────────────────────────────────────────

def _rect_edges(origin, w, h, rot_deg: float) -> list:
    ca, sa = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    def T(x, y):
        return [origin[0] + x * ca - y * sa, origin[1] + x * sa + y * ca]
    c = [T(0, 0), T(w, 0), T(w, h), T(0, h)]
    return [(c[k], c[(k + 1) % 4], 0.0) for k in range(4)]


_L_CORNERS = ("ne", "nw", "se", "sw")


def _l_edges(origin, W, H, cw, ch_, corner: str) -> list:
    ox, oy = origin
    if corner == "ne":
        pts = [[0, 0], [W, 0], [W, H - ch_], [W - cw, H - ch_], [W - cw, H], [0, H]]
    elif corner == "nw":
        pts = [[0, 0], [W, 0], [W, H], [cw, H], [cw, H - ch_], [0, H - ch_]]
    elif corner == "se":
        pts = [[0, 0], [W - cw, 0], [W - cw, ch_], [W, ch_], [W, H], [0, H]]
    else:  # sw
        pts = [[0, ch_], [cw, ch_], [cw, 0], [W, 0], [W, H], [0, H]]
    pts = [[ox + p[0], oy + p[1]] for p in pts]
    return [(pts[k], pts[(k + 1) % 6], 0.0) for k in range(6)]


def _shoelace(poly) -> float:
    n = len(poly)
    return abs(sum(poly[k][0] * poly[(k + 1) % n][1]
                   - poly[(k + 1) % n][0] * poly[k][1] for k in range(n))) / 2.0


def _validate_shape(shape: Any, grids_pool, oid, field: str, diags: list) -> Optional[list]:
    """One shape -> canonical closed edge list, all static laws enforced."""
    if not isinstance(shape, dict) or shape.get("shape") not in ("rect", "l", "poly"):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=shape,
            message_ru=f"{field}: форма — rect | l | poly"))
        return None
    kind = shape["shape"]
    if kind in ("rect", "l"):
        origin = resolve_anchor(shape.get("origin"), grids_pool, oid,
                                f"{field}.origin", diags)
        if origin is None:
            return None
        size = shape.get("size_mm")
        if not anchor_is_literal(size) or size[0] < 100 or size[1] < 100 \
                or size[0] > 500_000 or size[1] > 500_000:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.size_mm", got=size,
                message_ru=f"{field}: size_mm — [w,h] в 100..500000"))
            return None
        if kind == "rect":
            rot = shape.get("rotation_deg", 0)
            if not is_finite_number(rot) or not (-360 <= rot <= 360):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.rotation_deg",
                    got=rot, message_ru=f"{field}: rotation_deg — число -360..360"))
                return None
            extra = set(shape) - {"shape", "origin", "size_mm", "rotation_deg"}
        else:
            cut = shape.get("cut_mm")
            corner = shape.get("corner", "ne")
            if not anchor_is_literal(cut) or not (100 <= cut[0] <= size[0] - 100) \
                    or not (100 <= cut[1] <= size[1] - 100):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.cut_mm", got=cut,
                    message_ru=f"{field}: cut_mm — [cw,ch], каждый в 100..(size-100) "
                               f"(вырез не съедает профиль — Г-форма by construction)"))
                return None
            if corner not in _L_CORNERS:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.corner",
                    got=corner, candidates=list(_L_CORNERS),
                    message_ru=f"{field}: corner — ne|nw|se|sw"))
                return None
            extra = set(shape) - {"shape", "origin", "size_mm", "cut_mm", "corner"}
        if extra:
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid, field_name=field,
                got=sorted(extra), message_ru=f"{field}: неизвестные поля формы"))
            return None
        if kind == "rect":
            return _rect_edges(origin, float(size[0]), float(size[1]),
                               float(shape.get("rotation_deg", 0)))
        return _l_edges(origin, float(size[0]), float(size[1]),
                        float(shape["cut_mm"][0]), float(shape["cut_mm"][1]),
                        shape.get("corner", "ne"))
    # poly
    extra = set(shape) - {"shape", "points_mm", "arcs"}
    if extra:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=sorted(extra),
            message_ru=f"{field}: неизвестные поля формы"))
        return None
    raw_pts = shape.get("points_mm")
    # Тот же закон профиля, что у прямого `pts` и у лифтера (объявлен в geom).
    # КОНТУР написал его своей копией 17.07 («v2 invention») — третий ответ на
    # один вопрос; с 10.08 ответ один.
    if not isinstance(raw_pts, list) or not (
            MIN_RING_POINTS <= len(raw_pts) <= MAX_RING_POINTS):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.points_mm",
            got=raw_pts,
            message_ru=(f"{field}: points_mm — {MIN_RING_POINTS}.."
                        f"{MAX_RING_POINTS} точек")))
        return None
    pts = []
    for pi, a in enumerate(raw_pts):
        r = resolve_anchor(a, grids_pool, oid, f"{field}.points_mm[{pi}]", diags)
        if r is None:
            return None
        pts.append(r)
    # Кольцо ПЛЮС повторённая первая точка — то же правило, что в
    # geom.ring_normalize, и оно обязано быть тем же числом.
    if len(pts) >= MIN_RING_POINTS + 1 and _dist(pts[0], pts[-1]) < _EDGE_TOL:
        pts = pts[:-1]                       # closure normalization (v1.1 law)
    n = len(pts)
    if n < MIN_RING_POINTS:
        diags.append(Diagnostic(code=TYPE_BOUNDS, op_id=oid, field_name=field,
                                message_ru=f"{field}: после нормализации <3 точек"))
        return None
    bulges = [0.0] * n
    arcs = shape.get("arcs", [])
    if not isinstance(arcs, list) or len(arcs) > n:
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.arcs",
                                message_ru=f"{field}: arcs — список по рёбрам"))
        return None
    seen_arc_edges = set()
    for ai, arc in enumerate(arcs):
        if not isinstance(arc, dict) or isinstance(arc.get("edge"), bool) \
                or not isinstance(arc.get("edge"), int) \
                or not (0 <= arc["edge"] < n):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.arcs[{ai}]",
                got=arc, message_ru=f"{field}: arc — {{edge: 0..{n - 1}, bulge|radius_mm}}"))
            return None
        e = arc["edge"]
        if e in seen_arc_edges:
            diags.append(Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=oid,
                field_name=f"{field}.arcs[{ai}].edge", got=e,
                message_ru=f"{field}: ребро {e} описано дугой более одного раза"))
            return None
        seen_arc_edges.add(e)
        has_bulge, has_radius = "bulge" in arc, "radius_mm" in arc
        allowed = ({"edge", "bulge"} if has_bulge and not has_radius else
                   {"edge", "radius_mm", "dir"} if has_radius and not has_bulge else set())
        if not allowed or set(arc) - allowed:
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.arcs[{ai}]",
                got=arc, message_ru=(f"{field}: arc требует ровно одно из bulge/radius_mm; "
                                     "dir допустим только с radius_mm")))
            return None
        if has_bulge:
            b = arc["bulge"]
            if (not is_finite_number(b) or not (abs(b) <= MAX_ARC_BULGE)
                    or abs(b) < MIN_ARC_BULGE):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.arcs[{ai}].bulge",
                    got=b, expected=f"0<|b|<={MAX_ARC_BULGE}",
                    message_ru=f"{field}: bulge вне диапазона"))
                return None
            bulges[e] = float(b)
        else:
            r = arc["radius_mm"]
            direction = arc.get("dir", "ccw")
            if (not is_finite_number(r) or r <= 0
                    or direction not in ("ccw", "cw")):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_id=oid,
                    field_name=f"{field}.arcs[{ai}].radius_mm", got=r,
                    message_ru=f"{field}: radius_mm — конечное положительное число; dir=ccw|cw"))
                return None
            b = radius_to_bulge(pts[e], pts[(e + 1) % n], float(r),
                                direction == "ccw",
                                oid, f"{field}.arcs[{ai}]", diags)
            if b is None:
                return None
            bulges[e] = b
    edges = [(pts[k], pts[(k + 1) % n], bulges[k]) for k in range(n)]
    # static laws on the sampled polygon (v1.1 geom, lifted to arcs)
    for k in range(n):
        if _dist(pts[k], pts[(k + 1) % n]) < _EDGE_TOL:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=field,
                message_ru=f"{field}: нулевое ребро {k} (ShortCurveTolerance статически)"))
            return None
    sampled = edges_to_sample_poly(edges)
    if _shoelace(sampled) < MIN_RING_AREA_MM2:
        diags.append(Diagnostic(code=TYPE_BOUNDS, op_id=oid, field_name=field,
                                message_ru=f"{field}: вырожденный контур (<0.01 м²)"))
        return None
    m = len(sampled)
    for a in range(m):
        for b in range(a + 2, m):
            if a == 0 and b == m - 1:
                continue
            if _seg_intersect(sampled[a], sampled[(a + 1) % m],
                              sampled[b], sampled[(b + 1) % m]):
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
                    message_ru=f"{field}: самопересечение контура (с учётом дуг)"))
                return None
    return edges


def validate_region(region: Any, grids_pool, oid, field: str, diags: list) -> Optional[dict]:
    """{"outer": shape, "holes": [shape...]} -> {"outer": edges, "holes": [edges]}."""
    if not isinstance(region, dict) or "outer" not in region \
            or set(region) - {"outer", "holes"}:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=region,
            message_ru=f"{field}: регион — {{outer: форма, holes?: [формы]}}"))
        return None
    outer = _validate_shape(region["outer"], grids_pool, oid, f"{field}.outer", diags)
    if outer is None:
        return None
    holes_raw = region.get("holes", [])
    if not isinstance(holes_raw, list) or len(holes_raw) > MAX_HOLES:
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid,
                                field_name=f"{field}.holes",
                                message_ru=f"{field}: holes — до {MAX_HOLES} форм"))
        return None
    holes = []
    for hi, h in enumerate(holes_raw):
        he = _validate_shape(h, grids_pool, oid, f"{field}.holes[{hi}]", diags)
        if he is None:
            return None
        holes.append(he)
    # Containment/disjointness on sampled polygons (v1.1 law, arc-aware).
    # Reuse the shared inclusive edge law so plus-shaped overlaps, collinear
    # contact, and a hole edge crossing a concave outline cannot pass merely
    # because none of their vertices lies inside the other polygon.
    outer_poly = edges_to_sample_poly(outer)
    hole_polys = [edges_to_sample_poly(h) for h in holes]
    if not check_holes_relation(outer_poly, hole_polys, oid, diags,
                                field_prefix=f"{field}.holes"):
        return None
    return {"outer": outer, "holes": holes}


# ── МЕРЫ КАНОНИЧЕСКОГО КОНТУРА (замкнутые формы, всё на компиляции) ──────────
#
# ЗАЧЕМ ЗДЕСЬ, А НЕ У ВОЛНЫ ТЕЛ. Дуговая арифметика в пакете живёт ровно в
# одном месте — `_arc_geometry` выше, — и `edges_bbox` уже показывает форму:
# мера канонического рёберного списка есть свойство CONTOUR, а не того, кто
# его потребляет. Второй дом для той же тригонометрии означал бы два ответа на
# один вопрос ровно в тот день, когда один из них поправят.
#
# Каждая мера — ИНТЕГРАЛ ПО ГРАНИЦЕ (Грин), а не сумма по выборке: выборка
# внесла бы в свидетеля собственную ошибку, которую пришлось бы закладывать в
# допуск, а закладывать в допуск свою же неаккуратность — это и есть тот
# «прибор на часть диапазона», который здесь уже стоил дефекта.
#
# СВЕРКА (замер 09.08, tests/test_solid.py::ClosedFormsAgreeWithSampling): все
# четыре меры на восьми формах (включая обход по часовой и две дуги разного
# знака) сверены с полигональной выборкой в 4000 хорд на дугу. Худшее
# относительное расхождение 3.15e-8 при СОБСТВЕННОЙ ошибке выборки
# O(1/N²) = 6.25e-8 — то есть замкнутая форма точнее прибора, которым её
# проверяли, и наблюдаемое расхождение целиком объясняется прибором.


def edge_measures(p0, p1, bulge: float) -> tuple:
    """Меры ОДНОГО канонического ребра: (площадь, момент, длина, ∫x·ds).

    * ``area``   — вклад ребра в ``(1/2)∮(x dy − y dx)``, ЗНАКОВЫЙ (обход);
    * ``moment`` — вклад в ``∮ (x²/2) dy = ∬ x dA``, знаковый так же;
    * ``length`` — длина ребра (для дуги r·|sweep|), всегда >= 0;
    * ``x_ds``   — ``∫ x ds`` вдоль ребра; для профиля тела вращения это
      ровно вторая теорема Паппа (боковая поверхность = θ·∫x ds).
    """
    if abs(bulge) < STRAIGHT_BULGE_EPS:
        ax, ay = p0
        bx, by = p1
        length = math.hypot(bx - ax, by - ay)
        return (0.5 * (ax * by - ay * bx),
                # ∫(x²/2)dy по отрезку: x линеен по t, dy постоянна ⇒
                # (By−Ay)/2 · ∫₀¹(Ax + t·dx)² dt = (By−Ay)(Ax²+AxBx+Bx²)/6.
                (by - ay) * (ax * ax + ax * bx + bx * bx) / 6.0,
                length,
                length * (ax + bx) / 2.0)
    (cx, cy), r, a0, sweep = _arc_geometry(p0, p1, bulge)
    a1 = a0 + sweep
    s0, s1, c0, c1 = math.sin(a0), math.sin(a1), math.cos(a0), math.cos(a1)
    # x = cx + r·cos a, y = cy + r·sin a ⇒ x dy − y dx = (cx·r·cos a +
    # cy·r·sin a + r²) da.
    area = 0.5 * (r * cx * (s1 - s0) - r * cy * (c1 - c0) + r * r * sweep)
    # ∫(x²/2)dy = (1/2)∫(cx + r cos a)²·r cos a da, расписано по трём
    # первообразным: ∫cos = sin, ∫cos² = a/2 + sin2a/4, ∫cos³ = sin − sin³/3.
    i_cos = s1 - s0
    i_cos2 = (a1 / 2.0 + math.sin(2.0 * a1) / 4.0) - (a0 / 2.0 + math.sin(2.0 * a0) / 4.0)
    i_cos3 = (s1 - s1 ** 3 / 3.0) - (s0 - s0 ** 3 / 3.0)
    moment = 0.5 * (r * cx * cx * i_cos + 2.0 * cx * r * r * i_cos2 + r ** 3 * i_cos3)
    # ds = r·|da| — по ДЛИНЕ дуги, поэтому пределы упорядочиваются: знак
    # обхода не должен делать длину отрицательной.
    alo, ahi = (a0, a1) if a1 >= a0 else (a1, a0)
    x_ds = r * (cx * (ahi - alo) + r * (math.sin(ahi) - math.sin(alo)))
    return area, moment, r * abs(sweep), x_ds


def loop_measures(edges: list) -> tuple:
    """Суммы :func:`edge_measures` по замкнутому кольцу."""
    area = moment = length = x_ds = 0.0
    for p0, p1, bulge in edges:
        a, m, l, x = edge_measures(p0, p1, bulge)
        area += a
        moment += m
        length += l
        x_ds += x
    return area, moment, length, x_ds


def region_measures(region: dict) -> dict:
    """Меры региона {outer, holes} — площадь, момент, периметр, ∫x·ds.

    Кольцо нормализуется ПО ЗНАКУ СВОЕЙ ПЛОЩАДИ, а не по объявленному
    порядку точек: CONTOUR принимает обе ориентации (`poly_cw` в сверке —
    ровно такой случай), и знак площади — единственный факт об обходе,
    который у нас есть. Проёмы вычитаются; их строгая внутренность и
    попарная непересекаемость уже доказаны `check_holes_relation`, поэтому
    вычитание точное, а не приблизительное.

    ``perimeter_mm`` — ПОЛНАЯ длина границы (наружное кольцо + все проёмы):
    именно она даёт боковую поверхность призмы, а не длина одного кольца.

    ``min_area_mm2`` — площадь самого мелкого ОБЪЯВЛЕННОГО элемента профиля
    (сам профиль либо мельчайший проём). Это не украшение: свидетель, чей
    допуск не меньше этой величины, не заметил бы исчезновения этого
    элемента, и эмиссия обязана на таком отказать, а не подписать.
    """
    a_out, m_out, l_out, x_out = loop_measures(region["outer"])
    sign = 1.0 if a_out >= 0.0 else -1.0
    area = abs(a_out)
    moment = m_out * sign
    perimeter = l_out
    x_ds = x_out
    hole_areas = []
    hole_moments = []
    for hole in region.get("holes", ()):
        a_h, m_h, l_h, x_h = loop_measures(hole)
        s_h = 1.0 if a_h >= 0.0 else -1.0
        area -= abs(a_h)
        moment -= m_h * s_h
        perimeter += l_h
        x_ds += x_h
        hole_areas.append(abs(a_h))
        hole_moments.append(abs(m_h))
    return {
        "area_mm2": area,
        "moment_x_mm3": moment,
        "perimeter_mm": perimeter,
        "x_ds_mm2": x_ds,
        "hole_areas_mm2": hole_areas,
        "min_area_mm2": min([area] + hole_areas),
        # Момент самой мелкой объявленной части — та же роль, что у
        # `min_area_mm2`, но для тела вращения: там объём части есть θ·(её
        # момент), и брать вместо момента «площадь × габаритный радиус» было
        # бы оценкой СВЕРХУ, то есть завышенным порогом вакуумности, то есть
        # пропущенным свидетелем, который не может провалиться.
        "min_moment_x_mm3": min([abs(moment)] + hole_moments),
    }


def region_bbox(region: dict) -> tuple:
    """Габарит региона = габарит НАРУЖНОГО кольца (проёмы строго внутри)."""
    return edges_bbox(region["outer"])


def region_has_arc(region: dict) -> bool:
    """Есть ли в регионе хоть одна дуга (решает судьбу свидетеля площади)."""
    loops = [region["outer"], *region.get("holes", ())]
    return any(abs(b) > STRAIGHT_BULGE_EPS
               for edges in loops for _p0, _p1, b in edges)


# ── emit helper (THE template Sonnet waves clone for new sketch-ops) ─────────

def _model_pt_cs(x: float, y: float, z: str = "0") -> str:
    """Точка МОДЕЛЬНОГО пространства: плоскость XY плюс отметка.

    Знаки — `_EMIT_DECIMALS` (слияние 09.08): волна тел вывела из этой же
    константы `EMIT_COORD_QUANTUM_MM`, которым её свидетель считает
    погрешность границы, а волна детализации завела этот форматтер против
    своей базы, где имени ещё не было. Голый `2` здесь означал бы, что вывод
    одной волны опирается на число, которого в месте печати больше нет.
    """
    return f"P({round(x, _EMIT_DECIMALS)}, {round(y, _EMIT_DECIMALS)}, {z})"


def _edge_curve_cs(p0, p1, b: float, z: str = "0", pt=None) -> str:
    """ОДНО ребро канонической формы -> ОДНО выражение Revit-кривой.

    Три сборщика ниже (CurveLoop / CurveArray / List<Curve>) расходятся ровно
    контейнером и ничем больше: точки у них обязаны быть теми же самыми.
    Пока тело ребра стояло переписанным в каждом, «те же самые» держалось
    авторской дисциплиной — а два расхождения из трёх были бы невидимы
    (габаритный свидетель считает по питоновским рёбрам, то есть согласился
    бы с любой из копий). Байты обеих прежних функций сохранены: при z="0"
    строка совпадает посимвольно.

    СЛИЯНИЕ 09.08: число знаков берётся из `_EMIT_DECIMALS`, а не литералом, и
    обе руки СЛОЖЕНЫ, а не выбрана одна. Этот рефактор свёл тело ребра в одно
    место; волна тел в тот же день ДАЛА ЧИСЛУ ИМЯ и вывела из него
    `EMIT_COORD_QUANTUM_MM`, которым её свидетель считает погрешность границы
    построенного тела. Оставить здесь голый `2` значило бы, что вывод волны
    опирается на константу, которой в единственном месте печати больше нет, —
    и разъехались бы они МОЛЧА, потому что C# компилируется одинаково.

    ``pt`` (09.08.2026) — ФОРМАТТЕР ТОЧКИ, ``(x, y) -> C#-выражение``. Заведён
    не для симметрии: у заливки контур лежит не в плоскости XY модели, а в
    ПЛОСКОСТИ ВИДА, и Revit отвергает петлю, не параллельную собственной
    эскизной плоскости вида (RevitAPI.xml, ``FilledRegion.Create``). То есть
    третьего сборщика с другим ``z`` тут мало — меняется вся система координат,
    а не отметка. При этом ДУГОВАЯ АРИФМЕТИКА остаётся компиляционной ровно как
    была (канон CONTOUR, пункт 1): наружу по-прежнему уходят три точки на дугу,
    просто выражены они через базис вида. Умолчание — прежняя модельная форма,
    поэтому все существующие вызовы байт-в-байт те же.
    """
    fmt = pt if pt is not None else (lambda x, y: _model_pt_cs(x, y, z))
    if abs(b) < STRAIGHT_BULGE_EPS:
        return (f"Line.CreateBound("
                f"{fmt(p0[0], p0[1])}, "
                f"{fmt(p1[0], p1[1])})")
    m = bulge_midpoint(p0, p1, b)
    return (f"Arc.Create("
            f"{fmt(p0[0], p0[1])}, "
            f"{fmt(p1[0], p1[1])}, "
            f"{fmt(m[0], m[1])})")


def emit_loop_cs(edges: list, var: str, indent: str = "", pt=None) -> str:
    """CurveLoop assembly from canonical edges: Line for bulge==0,
    Arc.Create(start, end, mid-on-arc) otherwise — all points precomputed.

    ``pt`` — тот же форматтер точки, что у :func:`_edge_curve_cs`; без него
    петля собирается в плоскости XY модели, как и раньше."""
    out = [f"{indent}CurveLoop {var} = new CurveLoop();"]
    for p0, p1, b in edges:
        out.append(f"{indent}{var}.Append({_edge_curve_cs(p0, p1, b, pt=pt)});")
    return "\n".join(out)


def edge_witness_triples(edges: list) -> list:
    """Каждое ребро как ``(p0, mid, p1)`` — форма, которую свидетель СРАВНИВАЕТ.

    Почему тройка, а не пара концов: концы одни и те же у прямой и у любой дуги
    между ними, то есть свидетель по концам не отличил бы построенную дугу от
    построенной хорды — и стрелка дуги осталась бы недоказанной. Середина
    считается ТЕМ ЖЕ :func:`bulge_midpoint`, которым дуга и эмитируется (при
    ``bulge == 0`` он вырождается ровно в середину хорды), а с обратной стороны
    ей отвечает ``Curve.Evaluate(0.5, true)`` — параметрическая середина и
    прямой, и дуги окружности. Обе стороны сравнения обязаны считаться по
    одному закону; здесь закон — «концы плюс середина».
    """
    return [(list(p0), bulge_midpoint(p0, p1, b), list(p1))
            for p0, p1, b in edges]


def emit_curvearray_cs(edges: list, var: str, indent: str = "",
                       z: str = "0") -> str:
    """2021 legacy path (CurveArray for NewFloor) — same canon, same points.

    ``z`` — C#-ВЫРАЖЕНИЕ отметки плоскости эскиза В МИЛЛИМЕТРАХ, а не число.
    Понадобилось второму потребителю CurveArray — проёму
    (``NewOpening(Element, CurveArray, bool)``), чей профиль обязан лежать НА
    ПЛОСКОСТИ НОСИТЕЛЯ: отметку даёт сам носитель, прочитанный живьём, а ноль
    был бы тихой неправдой (перекрытие 17-го этажа стоит не там, и профиль
    просто не пересёк бы его).

    ЕДИНИЦЫ НАЗВАНЫ ЗДЕСЬ НАРОЧНО, И ЭТО СЛЕД СЛИЯНИЯ 09.08.2026. Две ветки
    пришли к этому помощнику с РАЗНЫМИ конвенциями: каркас клал
    ``MM(__lv.Elevation)`` (миллиметры, дальше через ``P()``), а проём —
    ``(__hbb.Min.Z + __hbb.Max.Z) / 2.0`` (внутренние футы, в обход ``U()``).
    Каждая была верна у себя и обе стали бы неверны здесь: ``P`` прогнал бы
    футы через ``U()`` вторым разом и посадил бы профиль на высоту порядка
    отметки, умноженной на 304.8. Дефект был бы НЕВИДИМ офлайн — C#
    компилируется одинаково, — и вылез бы только на живой модели, на этаже
    выше нулевого. Поэтому конвенция здесь ОДНА и она миллиметровая, как во
    всём языке; приводит к ней вызывающий (``MM(...)`` на стороне проёма).

    ``z="0"`` — прежний путь БАЙТ В БАЙТ: ветка 2021 у
    ``create_floor_by_contour``, единственного потребителя до этого дня.
    """
    out = [f"{indent}CurveArray {var} = new CurveArray();"]
    for p0, p1, b in edges:
        out.append(f"{indent}{var}.Append({_edge_curve_cs(p0, p1, b, z)});")
    return "\n".join(out)


def emit_curve_list_cs(edges: list, var: str, z: str = "0",
                       indent: str = "") -> str:
    """``IList<Curve>`` из тех же канонических рёбер — третий контейнер.

    Заведён не для симметрии: ``BeamSystem.Create`` принимает профиль ИМЕННО
    как ``IList<Curve>`` (замер компиляцией 09.08 на всех шести версиях;
    ``CurveLoop`` туда не приводится — CS0266 6/6, ``IList<Curve> x =
    bs.Profile`` тоже), поэтому обойтись двумя прежними сборщиками нельзя.

    ``z`` — C#-ВЫРАЖЕНИЕ, а не число, и это тоже не украшение: у балочной
    системы профиль обязан лежать в плоскости своего уровня, а отметка уровня
    известна только в рантайме (``MM(__lv.Elevation)``). Та же подпись, что у
    ``authoring._loop_pts(pts, name, z="0")``, и то же умолчание — прежние
    вызовы остаются байт-в-байт.
    """
    out = [f"{indent}IList<Curve> {var} = new List<Curve>();"]
    for p0, p1, b in edges:
        out.append(f"{indent}{var}.Add({_edge_curve_cs(p0, p1, b, z)});")
    return "\n".join(out)


def edges_vertex_bbox(edges: list) -> tuple:
    """Габарит ТОЛЬКО по вершинам — сознательно слабее :func:`edges_bbox`.

    Нужен там, где свидетель читает профиль ОБРАТНО ИЗ REVIT покривлённо:
    ``BeamSystem.Profile`` отдаёт кривые, у которых в C# без тесселяции
    доступны ровно концы (``GetEndPoint(0/1)``), то есть вершины. Сверять
    прочитанные вершины с :func:`edges_bbox`, который добавляет кардинальные
    экстремумы дуг, значило бы обвинять правильно построенную систему ровно
    на стрелку дуги — тот самый ложный отказ, каким `create_beam` разворачивал
    верные балки по опорному уровню. Обе стороны сравнения обязаны считаться
    по одному закону; здесь закон — вершины.
    """
    xs = [p[0] for edge in edges for p in (edge[0], edge[1])]
    ys = [p[1] for edge in edges for p in (edge[0], edge[1])]
    return min(xs), min(ys), max(xs), max(ys)
