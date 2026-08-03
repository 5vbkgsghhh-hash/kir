"""The project skeleton every discipline derives from, instead of re-inventing.

The deepest defect measured on 2026-07-28 was not a missing op or a lazy model.
It was that three programs building one tower each chose their own numbers: the
envelope was a Reuleaux triangle tapering to 0.5 and twisting 220°, the frame was
concentric circles with no taper at all, the partitions a square grid with
neither. Every element was valid, every witness green, and the result read as
three buildings sharing an origin. Diligence cannot fix that — nothing in the
language said the disciplines had to agree.

So they are given one source of truth. A `Parti` is declared ONCE, validated
once, and thereafter every discipline asks it for geometry rather than choosing:
`plate_at(k)` is THE plate of storey k, `frame_at(k)` is THE column ring, and
the transform handed to `stack` is the same object that produced both. Structure
that derives from the envelope cannot drift from it.

It also closes the degeneracy that cost us an evening. Coherence measured as
"does the frame taper like the envelope" is satisfied perfectly by a prism —
both taper by 1.0 — and that is exactly what the model built when asked. Against
a parti the question changes to "does the model match the skeleton it declared",
and a prism fails it, because the skeleton says 0.5.

Nothing here touches Revit or the compiler: pure geometry, so every derivation
and every check runs offline, at every stage, for free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

Point = tuple[float, float]

MAX_STOREYS = 400          # far above the macro cap: a parti may describe more
                           # than one program can build, and that is the point
MIN_STOREY_MM = 2200.0
MAX_STOREY_MM = 20000.0


class PartiError(ValueError):
    """A skeleton that cannot be built from. Message is for the model."""


def _pts(raw: Any, field_name: str) -> list[Point]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        raise PartiError(f"{field_name}: нужен контур минимум из 3 точек [x, y] в мм")
    out: list[Point] = []
    for p in raw:
        if (not isinstance(p, (list, tuple)) or len(p) < 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           and math.isfinite(v) for v in p[:2])):
            raise PartiError(f"{field_name}: точка должна быть [x, y] в мм, получено {p!r}")
        out.append((float(p[0]), float(p[1])))
    return out


def _num(v: Any, field_name: str, lo: float, hi: float) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        raise PartiError(f"{field_name}: число в мм")
    if not (lo <= v <= hi):
        raise PartiError(f"{field_name}: должно быть в пределах {lo:g}..{hi:g}, получено {v:g}")
    return float(v)


@dataclass(frozen=True)
class Form:
    """How the plan changes with height — the SAME parameters `stack.transform`
    takes, so the envelope the macro builds and the geometry every other
    discipline derives come from one formula."""
    scale_xy_top: tuple[float, float] = (1.0, 1.0)
    twist_deg_total: float = 0.0
    offset_mm_top: tuple[float, float] = (0.0, 0.0)
    pivot_mm: tuple[float, float] = (0.0, 0.0)

    @property
    def is_trivial(self) -> bool:
        """A prism. Named explicitly because "the frame tapers exactly like the
        envelope" is TRUE for a prism, and that is how a coherence check gets
        satisfied by building nothing interesting."""
        return (abs(self.scale_xy_top[0] - 1.0) < 1e-6
                and abs(self.scale_xy_top[1] - 1.0) < 1e-6
                and abs(self.twist_deg_total) < 1e-6
                and abs(self.offset_mm_top[0]) < 1e-6
                and abs(self.offset_mm_top[1]) < 1e-6)

    def as_transform(self) -> dict:
        return {"scale_xy_top": list(self.scale_xy_top),
                "twist_deg_total": self.twist_deg_total,
                "offset_mm_top": list(self.offset_mm_top),
                "pivot_mm": list(self.pivot_mm)}

    def at(self, t: float) -> tuple[float, float, float, float, float]:
        """(sx, sy, angle_rad, dx, dy) at storey fraction t ∈ [0, 1]."""
        return (1.0 + (self.scale_xy_top[0] - 1.0) * t,
                1.0 + (self.scale_xy_top[1] - 1.0) * t,
                math.radians(self.twist_deg_total * t),
                self.offset_mm_top[0] * t,
                self.offset_mm_top[1] * t)

    def apply(self, pt: Point, t: float) -> Point:
        sx, sy, ang, dx, dy = self.at(t)
        px, py = self.pivot_mm
        x, y = (pt[0] - px) * sx, (pt[1] - py) * sy
        c, s = math.cos(ang), math.sin(ang)
        return (px + x * c - y * s + dx, py + x * s + y * c + dy)


@dataclass(frozen=True)
class Parti:
    """The one thing every program reads and no program re-decides."""
    storeys: int
    storey_height_mm: float
    plate_base: list[Point]                 # storey-1 outline, absolute mm
    form: Form = field(default_factory=Form)
    base_elev_mm: float = 0.0
    bay_mm: tuple[float, float] = (6000.0, 6000.0)
    core_half_mm: float = 0.0               # 0 = no core declared
    level_prefix: str = "Уровень"

    # ---- derived geometry: ask, never invent ----------------------------

    def t(self, k: int) -> float:
        """Storey fraction, k counted from 1."""
        if self.storeys <= 1:
            return 0.0
        return (min(max(k, 1), self.storeys) - 1) / (self.storeys - 1)

    def elev(self, k: int) -> float:
        return self.base_elev_mm + (k - 1) * self.storey_height_mm

    def plate_at(self, k: int) -> list[Point]:
        tt = self.t(k)
        return [self.form.apply(p, tt) for p in self.plate_base]

    def centre_at(self, k: int) -> Point:
        pts = self.plate_at(k)
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    def radius_at(self, k: int) -> float:
        cx, cy = self.centre_at(k)
        return max(math.hypot(p[0] - cx, p[1] - cy) for p in self.plate_at(k))

    def frame_at(self, k: int, *, inset_mm: float = 1500.0) -> list[Point]:
        """Column positions of storey k: the bay grid clipped to the plate, so
        the frame is INSIDE the envelope by construction rather than by luck."""
        poly = self.plate_at(k)
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        dx, dy = self.bay_mm
        out: list[Point] = []
        n = 0
        x = math.floor(min(xs) / dx) * dx
        while x <= max(xs) and n < 4000:
            y = math.floor(min(ys) / dy) * dy
            while y <= max(ys) and n < 4000:
                n += 1
                if _inside((x, y), poly, margin=inset_mm):
                    out.append((x, y))
                y += dy
            x += dx
        return out

    def levels(self) -> list[dict]:
        return [{"op": "create_level", "id": f"L{k}",
                 "elev_mm": self.elev(k), "name": f"{self.level_prefix} {k}"}
                for k in range(1, self.storeys + 1)]

    def as_dict(self) -> dict:
        return {"storeys": self.storeys,
                "storey_height_mm": self.storey_height_mm,
                "base_elev_mm": self.base_elev_mm,
                "plate_base": [list(p) for p in self.plate_base],
                "form": self.form.as_transform(),
                "bay_mm": list(self.bay_mm),
                "core_half_mm": self.core_half_mm,
                "level_prefix": self.level_prefix}


def _inside(pt: Point, poly: list[Point], *, margin: float = 0.0) -> bool:
    x, y = pt
    hit = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xc = (x1 - x0) * (y - y0) / (y1 - y0) + x0
            if x < xc:
                hit = not hit
    if not hit or margin <= 0:
        return hit
    return _dist_to_edges(pt, poly) >= margin


def _dist_to_edges(pt: Point, poly: list[Point]) -> float:
    best = float("inf")
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        vx, vy = b[0] - a[0], b[1] - a[1]
        L2 = vx * vx + vy * vy
        if L2 == 0:
            d = math.hypot(pt[0] - a[0], pt[1] - a[1])
        else:
            u = max(0.0, min(1.0, ((pt[0] - a[0]) * vx + (pt[1] - a[1]) * vy) / L2))
            d = math.hypot(pt[0] - (a[0] + u * vx), pt[1] - (a[1] + u * vy))
        best = min(best, d)
    return best


def parse(raw: Any) -> Parti:
    """Validate a declared skeleton. Refusals name the field, like the compiler's,
    because this is the first thing the model writes and the first place it can
    be wrong."""
    if not isinstance(raw, dict):
        raise PartiError("скелет проекта — объект с полями storeys, "
                         "storey_height_mm, plate_base, form")
    n = raw.get("storeys")
    if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= MAX_STOREYS):
        raise PartiError(f"storeys: целое 1..{MAX_STOREYS}, получено {n!r}")
    h = _num(raw.get("storey_height_mm", 3300), "storey_height_mm",
             MIN_STOREY_MM, MAX_STOREY_MM)
    plate = _pts(raw.get("plate_base"), "plate_base")
    f = raw.get("form") or {}
    if not isinstance(f, dict):
        raise PartiError("form: объект {scale_xy_top, twist_deg_total, offset_mm_top, pivot_mm}")
    sc = f.get("scale_xy_top", [1.0, 1.0])
    if (not isinstance(sc, (list, tuple)) or len(sc) != 2
            or not all(isinstance(v, (int, float)) and 0.05 <= v <= 20 for v in sc)):
        raise PartiError("form.scale_xy_top: [sx, sy], каждый 0.05..20")
    off = f.get("offset_mm_top", [0.0, 0.0])
    if (not isinstance(off, (list, tuple)) or len(off) != 2
            or not all(isinstance(v, (int, float)) and abs(v) <= 1e6 for v in off)):
        raise PartiError("form.offset_mm_top: [dx, dy] в мм")
    piv = f.get("pivot_mm")
    if piv is None:
        piv = [sum(p[0] for p in plate) / len(plate),
               sum(p[1] for p in plate) / len(plate)]
    if (not isinstance(piv, (list, tuple)) or len(piv) != 2
            or not all(isinstance(v, (int, float)) and abs(v) <= 1e7 for v in piv)):
        raise PartiError("form.pivot_mm: [x, y] в мм — центр сужения и поворота")
    tw = f.get("twist_deg_total", 0.0)
    if not isinstance(tw, (int, float)) or isinstance(tw, bool) or abs(tw) > 3600:
        raise PartiError("form.twist_deg_total: число -3600..3600")
    bay = raw.get("bay_mm", [6000.0, 6000.0])
    if (not isinstance(bay, (list, tuple)) or len(bay) != 2
            or not all(isinstance(v, (int, float)) and 1500 <= v <= 30000 for v in bay)):
        raise PartiError("bay_mm: [dx, dy] шаг конструктивной сетки, 1500..30000 мм")
    core = raw.get("core_half_mm", 0.0)
    if not isinstance(core, (int, float)) or isinstance(core, bool) or not (0 <= core <= 1e5):
        raise PartiError("core_half_mm: половина стороны ядра в мм (0 — ядро не задано)")
    prefix = raw.get("level_prefix", "Уровень")
    if not isinstance(prefix, str) or not (1 <= len(prefix) <= 32):
        raise PartiError("level_prefix: строка 1..32 символов")
    return Parti(storeys=n, storey_height_mm=h, plate_base=plate,
                 form=Form(tuple(float(v) for v in sc), float(tw),
                           tuple(float(v) for v in off), tuple(float(v) for v in piv)),
                 base_elev_mm=float(raw.get("base_elev_mm", 0.0)),
                 bay_mm=(float(bay[0]), float(bay[1])),
                 core_half_mm=float(core), level_prefix=prefix)


def brief_gaps(p: Parti, brief: dict) -> list[str]:
    """Does the SKELETON answer the brief? Checked before a single element is
    built, because a parti that already contradicts the request cannot be
    rescued downstream — and because "the frame tapers like the envelope" is
    true of a prism, so somebody has to insist the shape was actually asked for.
    """
    out: list[str] = []
    want_h = brief.get("height_mm")
    if want_h:
        have = p.storeys * p.storey_height_mm
        if abs(have - want_h) > 0.25 * want_h:
            out.append(f"высота по скелету {have/1000:.0f} м против "
                       f"{want_h/1000:.0f} м в задании")
    want_n = brief.get("storeys")
    if want_n and abs(p.storeys - want_n) > max(2, 0.2 * want_n):
        out.append(f"этажей по скелету {p.storeys} против {want_n} в задании")
    if brief.get("shaped") and p.form.is_trivial:
        out.append("задание требует форму (сужение/закрутку/наклон), а скелет "
                   "описывает призму: form оставлен по умолчанию")
    if brief.get("core") and not p.core_half_mm:
        out.append("задание требует ядро жёсткости, в скелете core_half_mm = 0")
    return out


def from_stack(op: dict) -> Parti | None:
    """Read the skeleton out of the `stack` the model already wrote.

    Deliberately no new tool and no new field. A `stack` op ALREADY states
    every number a parti needs — storey count, storey height, base elevation,
    the plate outline and the form — so making it the source of truth costs the
    model nothing to learn and cannot drift from what was built: it IS what was
    built. Everything authored afterwards is then checked against it, which is
    how the frame stops being a second building.

    Returns None when the op carries no usable plate; a skeleton guessed from
    half the numbers would be worse than none.
    """
    if not isinstance(op, dict) or op.get("op") != "stack":
        return None
    plate = None
    for f in op.get("floor") or []:
        if not isinstance(f, dict):
            continue
        c = f.get("contour")
        outer = c.get("outer") if isinstance(c, dict) else None
        if isinstance(outer, dict) and outer.get("shape") == "poly":
            plate = outer.get("points_mm")
            break
    if plate is None:
        return None
    try:
        return parse({"storeys": op.get("levels"),
                      "storey_height_mm": op.get("h_mm", 3300),
                      "base_elev_mm": op.get("base_elev_mm", 0.0),
                      "plate_base": plate,
                      "form": op.get("transform") or {},
                      "level_prefix": op.get("name_prefix", "Level")})
    except PartiError:
        return None


def from_programs(programs) -> Parti | None:
    """The skeleton of the first shaped stack in the turn, if there is one."""
    for prog in programs or []:
        ops = prog.get("ops") if isinstance(prog, dict) else prog
        for o in ops if isinstance(ops, list) else []:
            got = from_stack(o) if isinstance(o, dict) else None
            if got is not None:
                return got
    return None
