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
3. ANCHORS: any point is a literal [x,y] OR {"at_grid": ["1","А"],
   "offset_mm": [dx,dy]} resolved at ground time from the grids pool
   (id/name/p0_mm/p1_mm); parallel or non-intersecting grid pair is a typed
   refusal with candidates. No other anchor kinds in v2.0 of CONTOUR.
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

from kukai.ir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS, TYPE_GEOM_RELATION
from kukai.ir.emit_utils import is_finite_number
from kukai.ir.geom import _dist, _seg_intersect, check_holes_relation

_EDGE_TOL = 1.0
_MAX_BULGE = 1.5
_MIN_AREA = 1e4
_ARC_SAMPLES = 8

GRID_ANCHOR_UNRESOLVED = "KIR-G105"   # at_grid pair missing/parallel


# ── anchors ──────────────────────────────────────────────────────────────────

def anchor_is_literal(a) -> bool:
    return (isinstance(a, list) and len(a) == 2
            and all(is_finite_number(c) for c in a))


def anchor_is_grid(a) -> bool:
    return (isinstance(a, dict) and isinstance(a.get("at_grid"), list)
            and len(a["at_grid"]) == 2
            and all(isinstance(g, str) and g.strip() for g in a["at_grid"]))


def _line_intersection(p0, p1, q0, q1) -> Optional[tuple]:
    """Infinite-line intersection (grids are lines, not segments)."""
    d1 = (p1[0] - p0[0], p1[1] - p0[1])
    d2 = (q1[0] - q0[0], q1[1] - q0[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return None
    t = ((q0[0] - p0[0]) * d2[1] - (q0[1] - p0[1]) * d2[0]) / den
    return (p0[0] + t * d1[0], p0[1] + t * d1[1])


def resolve_anchor(a, grids_pool: list, oid, field: str, diags: list) -> Optional[list]:
    """Literal passes through; at_grid resolves to the grid-pair intersection.
    grids_pool rows: {"id", "name", "p0_mm": [x,y], "p1_mm": [x,y]}."""
    if anchor_is_literal(a):
        return [float(a[0]), float(a[1])]
    if not anchor_is_grid(a):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=a,
            message_ru=f"{field}: точка — [x,y] мм или {{at_grid:[имя,имя], offset_mm?}}"))
        return None
    by_name = {str(g.get("name", "")).strip(): g for g in grids_pool or []}
    ga, gb = (a["at_grid"][0].strip(), a["at_grid"][1].strip())
    rows = []
    for gname in (ga, gb):
        row = by_name.get(gname)
        if row is None or not anchor_is_literal(row.get("p0_mm")) \
                or not anchor_is_literal(row.get("p1_mm")):
            diags.append(Diagnostic(
                code=GRID_ANCHOR_UNRESOLVED, op_id=oid, field_name=field,
                got=gname, candidates=sorted(by_name)[:8],
                message_ru=f"{field}: ось «{gname}» не найдена в снапшоте (или без геометрии)"))
            return None
        rows.append(row)
    pt = _line_intersection(rows[0]["p0_mm"], rows[0]["p1_mm"],
                            rows[1]["p0_mm"], rows[1]["p1_mm"])
    if pt is None:
        diags.append(Diagnostic(
            code=GRID_ANCHOR_UNRESOLVED, op_id=oid, field_name=field,
            got=a["at_grid"], message_ru=f"{field}: оси «{ga}»/«{gb}» параллельны — пересечения нет"))
        return None
    off = a.get("offset_mm", [0, 0])
    if not anchor_is_literal(off):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=off,
            message_ru=f"{field}: offset_mm — [dx,dy]"))
        return None
    return [pt[0] + float(off[0]), pt[1] + float(off[1])]


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
    if abs(bulge) < 1e-9:
        return [list(p0), list(p1)]
    (cx, cy), r, a0, sweep = _arc_geometry(p0, p1, bulge)
    pts = []
    for k in range(_ARC_SAMPLES + 1):
        a = a0 + sweep * k / _ARC_SAMPLES
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
        if abs(bulge) < 1e-9:
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
    if not isinstance(raw_pts, list) or not (3 <= len(raw_pts) <= 64):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.points_mm",
            got=raw_pts, message_ru=f"{field}: points_mm — 3..64 точек"))
        return None
    pts = []
    for pi, a in enumerate(raw_pts):
        r = resolve_anchor(a, grids_pool, oid, f"{field}.points_mm[{pi}]", diags)
        if r is None:
            return None
        pts.append(r)
    if len(pts) >= 4 and _dist(pts[0], pts[-1]) < _EDGE_TOL:
        pts = pts[:-1]                       # closure normalization (v1.1 law)
    n = len(pts)
    if n < 3:
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
            if (not is_finite_number(b) or not (abs(b) <= _MAX_BULGE)
                    or abs(b) < 1e-6):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.arcs[{ai}].bulge",
                    got=b, expected=f"0<|b|<={_MAX_BULGE}",
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
    if _shoelace(sampled) < _MIN_AREA:
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
    if not isinstance(holes_raw, list) or len(holes_raw) > 8:
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid,
                                field_name=f"{field}.holes",
                                message_ru=f"{field}: holes — до 8 форм"))
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


# ── emit helper (THE template Sonnet waves clone for new sketch-ops) ─────────

def emit_loop_cs(edges: list, var: str, indent: str = "") -> str:
    """CurveLoop assembly from canonical edges: Line for bulge==0,
    Arc.Create(start, end, mid-on-arc) otherwise — all points precomputed."""
    out = [f"{indent}CurveLoop {var} = new CurveLoop();"]
    for p0, p1, b in edges:
        if abs(b) < 1e-9:
            out.append(f"{indent}{var}.Append(Line.CreateBound("
                       f"P({round(p0[0], 2)}, {round(p0[1], 2)}, 0), "
                       f"P({round(p1[0], 2)}, {round(p1[1], 2)}, 0)));")
        else:
            m = bulge_midpoint(p0, p1, b)
            out.append(f"{indent}{var}.Append(Arc.Create("
                       f"P({round(p0[0], 2)}, {round(p0[1], 2)}, 0), "
                       f"P({round(p1[0], 2)}, {round(p1[1], 2)}, 0), "
                       f"P({round(m[0], 2)}, {round(m[1], 2)}, 0)));")
    return "\n".join(out)


def emit_curvearray_cs(edges: list, var: str, indent: str = "") -> str:
    """2021 legacy path (CurveArray for NewFloor) — same canon, same points."""
    out = [f"{indent}CurveArray {var} = new CurveArray();"]
    for p0, p1, b in edges:
        if abs(b) < 1e-9:
            out.append(f"{indent}{var}.Append(Line.CreateBound("
                       f"P({round(p0[0], 2)}, {round(p0[1], 2)}, 0), "
                       f"P({round(p1[0], 2)}, {round(p1[1], 2)}, 0)));")
        else:
            m = bulge_midpoint(p0, p1, b)
            out.append(f"{indent}{var}.Append(Arc.Create("
                       f"P({round(p0[0], 2)}, {round(p0[1], 2)}, 0), "
                       f"P({round(p1[0], 2)}, {round(p1[1], 2)}, 0), "
                       f"P({round(m[0], 2)}, {round(m[1], 2)}, 0)));")
    return "\n".join(out)
