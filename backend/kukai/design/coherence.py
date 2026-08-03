"""Does the building hold together? The witness that only sees TWO elements.

Every other check in KIR looks at one op: the compiler validates it, the
postconditions confirm it landed, the composition score counts its category.
None of them can see that a column stands outside the slab it carries. So a
model optimises what is checked and produces several buildings sharing an
origin — measured 2026-07-28 on a 10 134-element tower: 404 columns off their
slab, 1 359 walls resting on nothing, 531 beams reaching no column, an envelope
tapering to 0.81 against a frame tapering to 0.51.

Pure and offline: it reads the committed programs, so it can run inside a turn
before the model is allowed to call itself finished.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, NamedTuple

#: A slab is allowed to be this much smaller than the element standing on it
#: before the element counts as hanging off the edge. 300 mm is half a typical
#: column, i.e. the point at which it visibly overhangs.
EDGE_TOL_MM = 300.0

#: A beam end this far from any column axis is not supported by it.
BEAM_REACH_MM = 1500.0


class Elem(NamedTuple):
    op: str
    level: str
    pts: list[tuple[float, float]]      # plan geometry, mm
    z: float


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _xy(v: Any) -> tuple[float, float] | None:
    if isinstance(v, (list, tuple)) and len(v) >= 2 and all(_num(x) for x in v[:2]):
        return (float(v[0]), float(v[1]))
    return None


def _contour_pts(o: dict) -> list[tuple[float, float]]:
    raw = o.get("contour")
    if raw is None:
        # create_floor/create_roof carry their footprint as `outline` — a
        # flat >=3 [x,y] ring (ParamSpec("outline", "pts")), not the `region`
        # dict create_floor_by_contour uses. Without this fallback every
        # create_floor slab was invisible here: measured 2026-07-28, a
        # 12x9 m floor + its own edge wall read as {'плит': 0,
        # 'стен_вне_плиты': 1}.
        raw = o.get("outline")
    if isinstance(raw, dict):
        raw = raw.get("outer", raw)
    if isinstance(raw, dict):
        if raw.get("shape") == "poly":
            raw = raw.get("points_mm")
        elif raw.get("shape") in ("rect", "l"):
            o0, s = raw.get("origin"), raw.get("size_mm")
            if isinstance(o0, list) and isinstance(s, list) and len(s) == 2:
                x, y = float(o0[0]), float(o0[1])
                w, h = float(s[0]), float(s[1])
                raw = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            else:
                raw = None
        else:
            raw = None
    if not isinstance(raw, list):
        return []
    return [p for p in (_xy(x) for x in raw) if p]


def _level_key(o: dict) -> str:
    lv = o.get("level")
    return str(lv.get("value")) if isinstance(lv, dict) else "?"


def flatten(programs: Iterable[Any]) -> list[Elem]:
    """Committed programs -> flat elements with plan geometry, groups expanded.

    A group's copies are the members shifted by each placement — which is the
    whole reason a group cannot follow a taper, and therefore the reason this
    check exists.
    """
    out: list[Elem] = []
    #: Elevation by level id/name, learned from the create_level ops the macro
    #: emits. Without it every stack-authored slab sits at z=0 and no column
    #: ever finds the plate it stands on.
    elev: dict[str, float] = {}

    def take(o: dict, dx: float, dy: float, dz: float, suffix: str) -> None:
        op = o.get("op") or ""
        lvl = _level_key(o) + suffix
        base = elev.get(_level_key(o), 0.0)
        dz = dz + base
        shift = lambda p: (p[0] + dx, p[1] + dy)
        if op in ("create_column", "create_foundation", "create_room"):
            p = _xy(o.get("xy"))
            if p:
                out.append(Elem(op, lvl, [shift(p)], dz))
        elif op in ("create_wall", "create_beam"):
            a, b = _xy(o.get("p0_mm")), _xy(o.get("p1_mm"))
            if a and b:
                out.append(Elem(op, lvl, [shift(a), shift(b)], dz))
        elif op in ("create_floor_by_contour", "create_floor", "create_roof"):
            pts = _contour_pts(o)
            if len(pts) >= 3:
                out.append(Elem(op, lvl, [shift(p) for p in pts], dz))

    from kukai.ir import macros

    for prog in programs:
        ops = prog.get("ops") if isinstance(prog, dict) else prog
        # `stack` is where the envelope lives; without expanding it the check
        # sees zero slabs and reports every column as unsupported — a false
        # alarm that reads exactly like the real defect.
        try:
            ops = macros.expand(ops) if isinstance(ops, list) else ops
        except Exception:  # noqa: BLE001 — a program the compiler would refuse
            pass
        for o in ops if isinstance(ops, list) else []:
            if not isinstance(o, dict):
                continue
            if o.get("op") == "create_level" and _num(o.get("elev_mm")):
                for key in filter(None, (o.get("id"), o.get("name"))):
                    elev[str(key)] = float(o["elev_mm"])
                continue
            if o.get("op") == "create_group":
                deltas = [(0.0, 0.0, 0.0)]
                for p in o.get("placements") or []:
                    if isinstance(p, list) and len(p) >= 3 and all(_num(v) for v in p[:3]):
                        deltas.append((float(p[0]), float(p[1]), float(p[2])))
                for k, (dx, dy, dz) in enumerate(deltas):
                    for m in o.get("members") or []:
                        if isinstance(m, dict):
                            take(m, dx, dy, dz, f"@{k}")
            else:
                take(o, 0.0, 0.0, 0.0, "")
    return out


def _inside(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y = pt
    hit = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xc = (x1 - x0) * (y - y0) / (y1 - y0) + x0
            if x < xc:
                hit = not hit
    return hit


def _radius(pts: list[tuple[float, float]]) -> float:
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return max(math.hypot(p[0] - cx, p[1] - cy) for p in pts)


def _dist_to_poly(pt: tuple[float, float], poly: list[tuple[float, float]]) -> float:
    """Distance from `pt` to the nearest edge of `poly` — point-to-polygon,
    not point-to-bbox, so a wall on a chamfered or curved slab edge is judged
    against the edge it actually runs along."""
    n = len(poly)
    return min(_seg_dist(pt, poly[i], poly[(i + 1) % n]) for i in range(n))


def check(elems: list[Elem]) -> dict[str, Any]:
    slabs = [e for e in elems if e.op in ("create_floor_by_contour",
                                          "create_floor", "create_roof")]
    cols = [e for e in elems if e.op == "create_column"]
    beams = [e for e in elems if e.op == "create_beam"]
    walls = [e for e in elems if e.op == "create_wall"]

    def slab_at(z: float) -> list[Elem]:
        if not slabs:
            return []
        best = min(abs(s.z - z) for s in slabs)
        return [s for s in slabs if abs(s.z - z) <= best + 1.0]

    def on_slab(pts: list[tuple[float, float]], s: Elem) -> bool:
        # Inside, or within EDGE_TOL_MM of the boundary — a wall running
        # along the edge of its own slab (every exterior wall of every real
        # building) must not read as standing off it.
        return all(_inside(p, s.pts) or _dist_to_poly(p, s.pts) <= EDGE_TOL_MM
                   for p in pts)

    def off_slab(group: list[Elem]) -> int:
        bad = 0
        for e in group:
            near = slab_at(e.z)
            if not near:
                bad += 1
                continue
            if not any(on_slab(e.pts, s) for s in near):
                bad += 1
        return bad

    col_off = off_slab(cols)
    wall_off = off_slab(walls)

    # A beam end that reaches no column is a floating line.
    col_pts = [e.pts[0] for e in cols]
    loose = 0
    for b in beams:
        for end in b.pts:
            if not any(math.hypot(end[0] - c[0], end[1] - c[1]) <= BEAM_REACH_MM
                       for c in col_pts):
                loose += 1
                break

    # Does the structure follow the envelope? Compare the plan radius of the
    # slab against the plan radius of the columns, at the bottom and at the top.
    follow = None
    if slabs and cols:
        zs = sorted({round(s.z) for s in slabs})
        lo, hi = zs[0], zs[-1]
        def r_at(z, group):
            g = [e for e in group if abs(e.z - z) < 1.0]
            pts = [p for e in g for p in e.pts]
            return _radius(pts) if len(pts) >= 2 else None
        rs_lo, rs_hi = r_at(lo, slabs), r_at(hi, slabs)
        rc_lo, rc_hi = r_at(lo, cols), r_at(hi, cols)
        if all(v for v in (rs_lo, rs_hi, rc_lo, rc_hi)):
            follow = {"оболочка_низ_верх": [round(rs_lo), round(rs_hi)],
                      "конструктив_низ_верх": [round(rc_lo), round(rc_hi)],
                      "сужение_оболочки": round(rs_hi / rs_lo, 2),
                      "сужение_конструктива": round(rc_hi / rc_lo, 2)}
    return {"колонн": len(cols), "стен": len(walls), "балок": len(beams),
            "плит": len(slabs),
            "колонн_вне_плиты": col_off, "стен_вне_плиты": wall_off,
            "балок_без_опоры": loose, "следование_форме": follow}


#: Minimum sensible room side. Below this a "room" is a slot between two walls
#: that nobody can occupy — the plan reads as a drawing and not as a building.
MIN_ROOM_SIDE_MM = 1800.0

#: A partition passing closer than this to a column axis runs through it.
COLUMN_CLEAR_MM = 250.0


def check_plan(elems: list[Elem]) -> dict[str, Any]:
    """The floor plan as a plan, not as a list of elements.

    Everything else here compares pairs of elements. A plan fails differently:
    each wall is fine, each room is fine, and the floor is still unusable
    because a room has no way in, a partition runs through a column, or a
    "room" is a 700 mm slot. That is the "beautiful from far away, engineering
    nonsense up close" the operator named on 2026-07-28, and no per-element or
    per-pair check can see it.

    Everything is measured on the BUSIEST storey — the one with the most rooms —
    because a typical floor repeated forty times has forty copies of the same
    defect and reporting it forty times teaches nothing.
    """
    rooms = [e for e in elems if e.op == "create_room"]
    if not rooms:
        return {}
    by_z: dict[float, list[Elem]] = {}
    for e in elems:
        by_z.setdefault(round(e.z), []).append(e)
    z = max(by_z, key=lambda k: sum(1 for e in by_z[k] if e.op == "create_room"))
    floor = by_z[z]
    f_rooms = [e for e in floor if e.op == "create_room"]
    f_walls = [e for e in floor if e.op == "create_wall" and len(e.pts) == 2]
    f_cols = [e for e in floor if e.op == "create_column"]

    # A room with no wall within reach is not enclosed by anything.
    unenclosed = 0
    for r in f_rooms:
        p = r.pts[0]
        if not any(_seg_dist(p, w.pts[0], w.pts[1]) <= 12000.0 for w in f_walls):
            unenclosed += 1

    # A partition crossing a column axis.
    through = 0
    for w in f_walls:
        if any(_seg_dist(c.pts[0], w.pts[0], w.pts[1]) < COLUMN_CLEAR_MM
               for c in f_cols):
            through += 1

    # Slot-shaped cells: the gap between a wall and its nearest parallel
    # neighbour, taken as the plan's smallest habitable dimension.
    slivers = 0
    for i, w in enumerate(f_walls):
        d = _seg_len(w.pts[0], w.pts[1])
        if d and d < MIN_ROOM_SIDE_MM:
            slivers += 1

    return {"этаж_z": z, "помещений_на_этаже": len(f_rooms),
            "стен_на_этаже": len(f_walls),
            "помещений_без_ограждения": unenclosed,
            "перегородок_сквозь_колонну": through,
            "стен_короче_нормы": slivers,
            "дверей_на_этаже": sum(1 for e in floor if e.op == "create_door")}


def _seg_len(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _seg_dist(p: tuple[float, float], a: tuple[float, float],
              b: tuple[float, float]) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    L2 = vx * vx + vy * vy
    if L2 == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    u = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2))
    return math.hypot(p[0] - (a[0] + u * vx), p[1] - (a[1] + u * vy))


def check_against_parti(elems: list[Elem], p: Any) -> dict[str, Any]:
    """Does what was built agree with the skeleton it declared?

    This is the check that cannot be satisfied by building nothing. Comparing
    the frame's taper to the envelope's is true of a prism — both taper by 1.0,
    which is exactly what the model delivered when that was the target. The
    parti states the taper the brief asked for, so a prism now disagrees with
    its own declaration, and the disagreement is a number.
    """
    slabs = [e for e in elems if e.op in ("create_floor_by_contour",
                                          "create_floor", "create_roof")]
    cols = [e for e in elems if e.op == "create_column"]
    if not slabs and not cols:
        return {}
    h = p.storey_height_mm
    def storey_of(z: float) -> int:
        return max(1, min(p.storeys, int(round((z - p.base_elev_mm) / h)) + 1))

    slab_off = 0
    for s in slabs:
        k = storey_of(s.z)
        want = p.radius_at(k)
        cx = sum(q[0] for q in s.pts) / len(s.pts)
        cy = sum(q[1] for q in s.pts) / len(s.pts)
        have = max(math.hypot(q[0] - cx, q[1] - cy) for q in s.pts)
        if want and abs(have - want) > 0.2 * want:
            slab_off += 1

    col_off_grid = 0
    for c in cols:
        k = storey_of(c.z)
        nodes = p.frame_at(k)
        if nodes and min(math.hypot(c.pts[0][0] - n[0], c.pts[0][1] - n[1])
                         for n in nodes) > max(p.bay_mm) / 2:
            col_off_grid += 1

    built_top = max((storey_of(s.z) for s in slabs), default=1)
    return {"этажей_по_скелету": p.storeys, "этажей_построено": built_top,
            "плит_не_по_скелету": slab_off, "плит_всего": len(slabs),
            "колонн_вне_сетки": col_off_grid, "колонн_всего": len(cols),
            "скелет_призма": p.form.is_trivial}


def gaps(rep: dict) -> list[str]:
    """The report as sentences the model can act on."""
    out: list[str] = []
    if rep["колонн"] and rep["колонн_вне_плиты"]:
        out.append(f"{rep['колонн_вне_плиты']} колонн из {rep['колонн']} стоят "
                   f"вне перекрытия своего этажа — они ничего не несут")
    if rep["стен"] and rep["стен_вне_плиты"]:
        out.append(f"{rep['стен_вне_плиты']} стен из {rep['стен']} стоят вне "
                   f"перекрытия — стена должна опираться на плиту")
    if rep["балок"] and rep["балок_без_опоры"]:
        out.append(f"{rep['балок_без_опоры']} балок из {rep['балок']} не "
                   f"доходят ни до одной колонны — это линии, а не каркас")
    f = rep.get("следование_форме")
    if f and abs(f["сужение_конструктива"] - f["сужение_оболочки"]) > 0.15:
        out.append(f"конструктив не следует форме: оболочка сужается в "
                   f"{f['сужение_оболочки']} раза, а колонны в "
                   f"{f['сужение_конструктива']} — это два разных здания")

    # ── against the declared skeleton ────────────────────────────────────
    if rep.get("плит_не_по_скелету"):
        out.append(f"{rep['плит_не_по_скелету']} плит из {rep['плит_всего']} не "
                   f"совпадают с контуром, который задаёт скелет проекта на "
                   f"своём этаже — форма построена не та, что объявлена")
    if rep.get("колонн_вне_сетки"):
        out.append(f"{rep['колонн_вне_сетки']} колонн из {rep['колонн_всего']} "
                   f"стоят не по конструктивной сетке скелета — балки и "
                   f"перегородки на них не лягут")
    built, want = rep.get("этажей_построено"), rep.get("этажей_по_скелету")
    if built and want and built < want * 0.9:
        out.append(f"построено {built} этажей из {want} по скелету — здание не "
                   f"доведено до объявленной высоты")

    # ── the floor plan as a plan ─────────────────────────────────────────
    if rep.get("помещений_без_ограждения"):
        out.append(f"{rep['помещений_без_ограждения']} помещений на этаже ничем "
                   f"не ограждены — это точки, а не комнаты")
    if rep.get("перегородок_сквозь_колонну"):
        out.append(f"{rep['перегородок_сквозь_колонну']} перегородок проходят "
                   f"сквозь колонну — план не согласован с каркасом")
    if rep.get("стен_короче_нормы"):
        out.append(f"{rep['стен_короче_нормы']} стен короче {MIN_ROOM_SIDE_MM:.0f} мм — "
                   f"такие ячейки нежилые")
    rooms_here = rep.get("помещений_на_этаже") or 0
    if rooms_here >= 4 and not rep.get("дверей_на_этаже"):
        out.append(f"на этаже {rooms_here} помещений и ни одной двери — войти "
                   f"некуда")
    return out


def full_check(elems: list[Elem], parti: Any = None) -> dict[str, Any]:
    """Every scope at once: element pairs, the plan, and the skeleton.

    Self-scoping on purpose — a report only carries what the model has actually
    built, so a turn that has laid slabs and no partitions is never told its
    rooms are unenclosed. A stage gate that nags about the next stage teaches
    the model to ignore it.
    """
    rep = check(elems)
    rep.update(check_plan(elems))
    if parti is not None:
        rep.update(check_against_parti(elems, parti))
    return rep
