"""Draw a KIR program. No Revit, no 3D engine — the ops already ARE the geometry.

KIR carries millimetres in the open: a beam is two points, a column is a point
plus a level span, a wall is two points plus a height. So a program can be
projected straight to line art, which turns out to matter more than it sounds:

* The compiler answers "is this well-formed", never "is this the right shape".
  A tower of 94 accepted beams can still be junk, and on 2026-07-27 one was.
* Revit's own screenshot needs a live document, a warmed view and ~15s. This
  needs neither, so it can run after every program instead of once at the end.
* The model that wrote the numbers can LOOK at them. That closes the operator's
  loop — build, look, notice it's wrong, keep working — offline and for free.

Views are orthographic and unlabelled by design. The point is silhouette:
proportion, symmetry, things floating in the air. A rendering that flatters the
program is worse than none, so anything undrawable is COUNTED and reported
rather than skipped quietly.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any, Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

Point = tuple[float, float, float]
Segment = tuple[Point, Point]

#: Level elevations a program declares as it goes. A column's Z comes from its
#: level, and the ground snapshot carries names without elevations, so a program
#: that never declares one is drawn flat — and said to be.
DEFAULT_LEVEL_MM = 0.0


def _xyz(v: Any, z: float = 0.0) -> Point | None:
    if not isinstance(v, (list, tuple)) or not (2 <= len(v) <= 3):
        return None
    try:
        x, y = float(v[0]), float(v[1])
        zz = float(v[2]) if len(v) == 3 else z
    except (TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (x, y, zz))):
        return None
    return (x, y, zz)


def _level_z(ref: Any, levels: dict[str, float]) -> float:
    if isinstance(ref, dict):
        key = str(ref.get("value", ""))
        if key in levels:
            return levels[key]
    return DEFAULT_LEVEL_MM


def _contour_points(o: dict, z: float) -> list[Point]:
    """Corners of a floor/roof outline.

    KIR's CONTOUR sublanguage is `{outer: {shape: rect|l|poly, ...}}`, not a
    bare point list — reading only the bare form silently dropped every
    contour-authored plate, which is the whole floor of a tower. `at_grid`
    anchors resolve against the model's grids and are honestly skipped.
    """
    raw = o.get("contour") or o.get("outline") or o.get("points_mm")
    if isinstance(raw, dict):
        raw = raw.get("outer", raw)
    if isinstance(raw, dict):
        shape = raw.get("shape")
        if shape == "poly":
            raw = raw.get("points_mm")
        elif shape in ("rect", "l"):
            origin, size = raw.get("origin"), raw.get("size_mm")
            if (isinstance(origin, list) and isinstance(size, list)
                    and len(origin) >= 2 and len(size) == 2):
                x, y = float(origin[0]), float(origin[1])
                w, h = float(size[0]), float(size[1])
                raw = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            else:
                raw = None
        else:
            raw = None
    if not isinstance(raw, list):
        return []
    return [p for p in (_xyz(x, z) for x in raw) if p]


class Drawing:
    def __init__(self) -> None:
        self.segments: list[Segment] = []
        self.drawn: dict[str, int] = {}
        self.skipped: dict[str, int] = {}
        self.levels: dict[str, float] = {}

    def _ok(self, op: str, segs: Iterable[Segment]) -> None:
        segs = [s for s in segs if s]
        if not segs:
            self.skipped[op] = self.skipped.get(op, 0) + 1
            return
        self.segments.extend(segs)
        self.drawn[op] = self.drawn.get(op, 0) + 1

    def add(self, o: dict) -> None:
        op = o.get("op")
        if op == "create_level":
            try:
                elev = float(o.get("elev_mm", 0.0))
            except (TypeError, ValueError):
                elev = 0.0
            for key in filter(None, (o.get("id"), o.get("name"))):
                self.levels[str(key)] = elev
            self.drawn[op] = self.drawn.get(op, 0) + 1
            return

        z0 = _level_z(o.get("level"), self.levels)

        if op in ("create_beam", "create_grid"):
            a, b = _xyz(o.get("p0_mm"), z0), _xyz(o.get("p1_mm"), z0)
            self._ok(op, [(a, b)] if a and b else [])

        elif op == "create_column":
            base = _xyz(o.get("xy"), z0)
            if base is None:
                self._ok(op, [])
                return
            top_ref = o.get("top_level")
            ztop = _level_z(top_ref, self.levels) if top_ref is not None else None
            if ztop is None or ztop == base[2]:
                ztop = base[2] + 3000.0          # a column with no span still reads as one
            ztop += float(o.get("top_offset_mm") or 0)
            zb = base[2] + float(o.get("base_offset_mm") or 0)
            head = _xyz(o.get("top_xy"), 0) or base
            self._ok(op, [((base[0], base[1], zb), (head[0], head[1], ztop))])

        elif op == "create_wall":
            a, b = _xyz(o.get("p0_mm"), z0), _xyz(o.get("p1_mm"), z0)
            if not (a and b):
                self._ok(op, [])
                return
            h = float(o.get("height_mm") or 3000)
            at, bt = (a[0], a[1], a[2] + h), (b[0], b[1], b[2] + h)
            self._ok(op, [(a, b), (at, bt), (a, at), (b, bt)])

        elif op in ("create_floor", "create_floor_by_contour", "create_roof",
                    "create_room"):
            pts = _contour_points(o, z0)
            if len(pts) < 3:
                self._ok(op, [])
                return
            self._ok(op, [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))])

        elif op == "create_group":
            # members + placements is KIR's repetition primitive, so a drawing
            # that skips it shows a fraction of the building. Measured the hard
            # way: the first run after groups became usable rendered 4 beams out
            # of 100+, the model was shown a near-empty sheet, and its "keep
            # building" reaction looked like the look-loop working. Occurrence 0
            # IS the members; placements are deltas from it.
            members = o.get("members")
            if not isinstance(members, list):
                self._ok(op, [])
                return
            deltas: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]
            for p in o.get("placements") or []:
                d = _xyz(p, 0.0)
                if d:
                    deltas.append(d)
            before = len(self.segments)
            inner = Drawing()
            inner.levels = dict(self.levels)
            for m in members:
                if isinstance(m, dict):
                    inner.add(m)
            for dx, dy, dz in deltas:
                self.segments.extend(
                    (((a[0] + dx, a[1] + dy, a[2] + dz),
                      (b[0] + dx, b[1] + dy, b[2] + dz)))
                    for a, b in inner.segments)
            for k, v in inner.skipped.items():
                self.skipped[f"group/{k}"] = self.skipped.get(f"group/{k}", 0) + v
            if len(self.segments) > before:
                self.drawn[op] = self.drawn.get(op, 0) + 1
                self.drawn["group/члены"] = (self.drawn.get("group/члены", 0)
                                             + len(members) * len(deltas))
            else:
                self.skipped[op] = self.skipped.get(op, 0) + 1

        else:
            self.skipped[op or "?"] = self.skipped.get(op or "?", 0) + 1


def collect(programs: Iterable[Any]) -> Drawing:
    d = Drawing()
    for prog in programs:
        ops = prog.get("ops") if isinstance(prog, dict) else prog
        for o in ops if isinstance(ops, list) else []:
            if isinstance(o, dict):
                d.add(o)
    return d


def _project(seg: Segment, view: str) -> tuple[tuple[float, float], tuple[float, float]]:
    (x0, y0, z0), (x1, y1, z1) = seg
    if view == "front":                      # looking along +Y: X right, Z up
        return (x0, z0), (x1, z1)
    if view == "top":                        # plan: X right, Y up
        return (x0, y0), (x1, y1)
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    return ((x0 - y0) * c, (x0 + y0) * s + z0), ((x1 - y1) * c, (x1 + y1) * s + z1)


def render(d: Drawing, title: str = "", *, px: int = 1400,
           max_bytes: int = 90_000) -> bytes:
    views = ("front", "top", "iso")
    fig, axes = plt.subplots(1, 3, figsize=(px / 100, px / 300), dpi=100)
    for ax, view in zip(axes, views):
        for seg in d.segments:
            (ax0, ay0), (ax1, ay1) = _project(seg, view)
            ax.plot([ax0, ax1], [ay0, ay1], linewidth=0.6, color="#111111",
                    solid_capstyle="round")
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_title({"front": "фасад (XZ)", "top": "план (XY)",
                      "iso": "изометрия"}[view], fontsize=9)
        ax.tick_params(labelsize=6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    if title:
        fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    png = buf.getvalue()
    if len(png) <= max_bytes:
        return png
    # A 140KB PNG becomes ~190KB of base64 in the history, and a long authoring
    # session carries several. Past some size the route stopped answering at all
    # — 35 empty replies in 48 calls on 2026-07-27, zero in the same harness
    # without pictures. Line art survives JPEG fine; the history does not
    # survive the PNG.
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    for quality in (80, 65, 50, 35):
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True)
        if out.tell() <= max_bytes:
            return out.getvalue()
    return out.getvalue()


def report(d: Drawing) -> str:
    """What the picture does and does not show — stated, never implied."""
    drawn = sum(d.drawn.values())
    parts = [f"нарисовано {drawn} опов ({', '.join(f'{k}×{v}' for k, v in sorted(d.drawn.items()))})"]
    if d.skipped:
        parts.append("НЕ нарисовано: " +
                     ", ".join(f"{k}×{v}" for k, v in sorted(d.skipped.items())))
    if d.segments:
        xs = [p[0] for s in d.segments for p in s]
        ys = [p[1] for s in d.segments for p in s]
        zs = [p[2] for s in d.segments for p in s]
        parts.append(f"габарит X {min(xs):.0f}..{max(xs):.0f}, "
                     f"Y {min(ys):.0f}..{max(ys):.0f}, "
                     f"Z {min(zs):.0f}..{max(zs):.0f} мм")
    return "; ".join(parts)


def data_url(blob: bytes) -> str:
    mime = "image/png" if blob[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(blob).decode()
