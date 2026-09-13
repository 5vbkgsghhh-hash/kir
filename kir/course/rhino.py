"""FREEFORM VOCABULARY: build like in Rhino, get BIM.

    from kir.course.rhino import RHINO_NAMES     # шов в песочницу
    loft([(низ, 0), (верх, 30000)], name="оболочка")
    for f in faces(оболочка):
        if f["facing"] == "up": ...

WHY THIS FILE EXISTS, AND THIS IS A MEASUREMENT, NOT TASTE
------------------------------------------------------------
The owner's word, 01.09.2026: "An LLM does far better in three.js than in
Revit; I want a tool that, like Rhino and three.js, can be used to build
beautiful objects, except they will be BIM-oriented."

Why Revit produces shacks — this is measured, not assumed. Of the
registry's 82 operations, **47 require a catalog from a snapshot** (a type
by NAME the author does not know), **32 require a level**, **12 — a
host**; the language reference costs **43 030 tokens** against **519** for
raw C#; in the live corpus **121 turns** went into RECONNAISSANCE instead
of building. Every such slot is the question "and what do you call this
one", and to each one the author responds with caution: it builds what is
certain to pass. Caution is exactly what a shack is.

In three.js there is not one such question: there it's `extrude`, `loft`,
`boolean`, `transform` — and that's all. This module gives exactly that
surface **on top of the already existing registry**, without starting a
single new operation or a single new kind of value.

WHAT IS DELIBERATELY NOT HERE
------------------------------
* **There is no layout solver, and there will not be one.** The owner's
  word: "an infinite number of BIM models exists, and I do not want some
  solver producing a limited number of layouts." The author chooses the
  form; here there is only COMPUTATION (intersection, section, faces) and
  TRANSLATION into registry operations.
* **Not a single new operation, not a single new kind of value.**
  Everything the functions below return is `poly`, `region`, `mesh`,
  `plane`, and boolean parts — kinds the language already knows and
  already checks. Pattern 42 ("a kind living in a Python object's type
  does not cross the serialization boundary") is closed by this
  construction: there is nothing to cross the boundary except native
  values.
* **No approximations passed off as geometry.** Where the mesh lacks
  data (sections with differing point counts, a section that splits into
  two pieces), what stands here is a NAMED refusal or `None` with a
  reason, not a plausible fabrication. This is a direct consequence of
  pattern 44 of this tree: a plausible number is more dangerous than a
  zero.

THE BOUNDARY YOU NEED TO KNOW BEFORE READING THE CODE
-------------------------------------------------------
`loft` builds **piecewise**, not smoothly. A smooth loft exists in the
Revit API (`GeometryCreationUtilities.CreateLoftGeometry`), and it
compiles 6/6 — but it has NO honest witness of volume, while
`create_solid_blend` has one. As long as there is no witness, a chain of
blends is the only form about which one can say "what was asked for was
built", and that is why it was chosen. This is named in the function's own
output, not hidden in a docstring.

PURITY
------
Only `math` from the standard library and the language's own internal
modules. Neither numpy nor shapely: the sandbox does not have them by
default (`KIR_AUTHOR_GEOMETRY_LIBS`), and nondeterminism breaks
`author_digest`. The same law as in `recipes.py`.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kir import contour as _contour
from kir import dsl as _dsl
from kir.diag import (Diagnostic, KirRefusal, TYPE_BAD_TYPE, TYPE_BOUNDS,
                      TYPE_GEOM_RELATION)
from kir.emit_utils import is_finite_number
from kir.geom import MAX_RING_POINTS, MIN_RING_POINTS
from kir.registry_base import COORD_LIMIT_MM
from kir import promote as _promote_mod

# ─────────────────────────────────────────────────────────────── tolerances

#: Face merging: two triangular faces are considered ONE flat face when
#: their normals and offsets coincide after quantization. The value was
#: not picked arbitrarily: this language's meshes are born from
#: `mesh.extrude`/`mesh.sweep` and our own constructions, meaning
#: coordinates arrive exact down to double's rounding error at magnitudes
#: on the order of COORD_LIMIT_MM. 1e-9 for a unit normal and 1e-6 mm for
#: an offset are three orders of magnitude coarser than that error and
#: three orders of magnitude finer than the smallest legitimate quantity
#: in the language (a profile side from 100 mm, a body from 1 mm).
_NORMAL_Q = 1e-9
_OFFSET_Q = 1e-6

#: A point is considered to lie IN the section plane when the deviation is
#: below this. The same argument as above: not "small to the eye", but
#: "three orders of magnitude finer than the smallest legitimate quantity
#: in the language".
_PLANE_EPS = 1e-6

#: The cosine between normals at which faces are considered OPPOSING
#: (n·n' = -1).
_OPPOSITE_COS = -1.0 + 1e-9

#: The fraction by which the areas of opposing faces may differ and the
#: pair still be considered "the same face from the other side". A
#: DECISION, not a measurement, and named as such: for a true prism the
#: areas are exactly equal, and the tolerance here exists for the sake of
#: rounding error, not for tolerance toward non-prismatic bodies.
_AREA_MATCH = 1e-6


def _refuse(code: str, field: str, message: str, got: Any = None) -> None:
    """A refusal in the tree's grammar: code, field, reason, and the
    MEASURED value.

    `got` is always filled in when it exists: pattern 43 of this tree — "a
    message saying 'X does not equal the expected Y' must print X".
    """
    raise KirRefusal([Diagnostic(code=code, op_id=None, field_name=field,
                                 message_ru=message, got=got)])


# ────────────────────────────────────────────────── coercing inputs

def _num(value: Any, field: str, what: str) -> float:
    if not is_finite_number(value):
        _refuse(TYPE_BAD_TYPE, field,
                f"{field}: {what} — это число в миллиметрах, "
                f"а пришло {type(value).__name__}", got=repr(value)[:60])
    v = float(value)
    if abs(v) > COORD_LIMIT_MM:
        _refuse(TYPE_BOUNDS, field,
                f"{field}: {what} = {v} мм выходит за рабочий предел "
                f"{COORD_LIMIT_MM} мм", got=v)
    return v


def _ring_points(value: Any, field: str) -> list[tuple[float, float]]:
    """The author's ring -> a list of points. Forms: `poly`, `region`, a
    bare list."""
    raw = value
    if isinstance(value, dict):
        if "outer" in value:            # region
            raw = value["outer"]
        if isinstance(raw, dict):
            if raw.get("shape") != "poly":
                _refuse(TYPE_BAD_TYPE, field,
                        f"{field}: кольцом здесь работает форма `poly` (список "
                        f"точек) либо `region`; форма "
                        f"{raw.get('shape')!r} несёт свои размеры, и считать "
                        f"её точки значило бы их выдумать",
                        got=raw.get("shape"))
            raw = raw.get("points_mm")
    if not isinstance(raw, (list, tuple)) or not raw:
        _refuse(TYPE_BAD_TYPE, field,
                f"{field}: ожидалось кольцо точек, пришло "
                f"{type(value).__name__}", got=repr(value)[:60])
    pts: list[tuple[float, float]] = []
    for i, p in enumerate(raw):
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            _refuse(TYPE_BAD_TYPE, field,
                    f"{field}[{i}]: точка — это [x, y] в миллиметрах",
                    got=repr(p)[:60])
        pts.append((_num(p[0], f"{field}[{i}].x", "координата"),
                    _num(p[1], f"{field}[{i}].y", "координата")))
    if len(pts) < MIN_RING_POINTS:
        _refuse(TYPE_GEOM_RELATION, field,
                f"{field}: в кольце {len(pts)} точки, а замкнутая фигура "
                f"начинается с {MIN_RING_POINTS}", got=len(pts))
    if len(pts) > MAX_RING_POINTS:
        _refuse(TYPE_BOUNDS, field,
                f"{field}: точек {len(pts)} при пределе кольца "
                f"{MAX_RING_POINTS}", got=len(pts))
    return pts


def _as_region(value: Any, field: str) -> dict:
    """Anything ring-shaped -> the language's `region`, WITHOUT losing
    holes."""
    if isinstance(value, dict) and "outer" in value:
        return value
    return _contour.region(_ring_points(value, field))


def _mesh_of(shape: Any, field: str) -> dict:
    """A mesh from a value: the mesh itself, or a carrier with a `mesh`
    key.

    The second is what `loft` returns: operation handles AND a mesh you
    can query faces on. The carrier NEVER rides into an operation slot:
    what goes into the slot is `shape["mesh"]`, and this is visible in the
    script itself.
    """
    m = shape
    if isinstance(shape, dict) and "mesh" in shape and "vertices_mm" not in shape:
        m = shape["mesh"]
    if m is None:
        reason = ""
        if isinstance(shape, dict):
            reason = str(shape.get("mesh_absent_reason") or "")
        _refuse(TYPE_BAD_TYPE, field,
                f"{field}: у этой формы меша НЕТ, и причина названа: "
                f"{reason or 'не построен'}. Спрашивать её грани или сечение "
                f"нечем — это не пустой ответ, а отсутствие предмета",
                got=reason or None)
    if (not isinstance(m, dict) or "vertices_mm" not in m
            or "triangles" not in m):
        _refuse(TYPE_BAD_TYPE, field,
                f"{field}: ожидался меш (`vertices_mm` + `triangles`) либо "
                f"форма, его несущая; пришло {type(shape).__name__}",
                got=sorted(m)[:6] if isinstance(m, dict) else repr(shape)[:60])
    return m


# ────────────────────────────────────────────────────── pure geometry

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _signed_area(pts) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _point_in_ring(p, ring) -> bool:
    x, y = p[0], p[1]
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xx = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xx > x:
                inside = not inside
    return inside


def _key(p, q: float = 1e-6):
    return (round(p[0] / q), round(p[1] / q), round(p[2] / q))


# ──────────────────────────────────────────────────────────── FACES

def _plane_value(normal, origin) -> dict:
    """The face's plane in the language's NATIVE `plane` kind.

    This is not decoration: `create_solid_extrusion` and
    `create_solid_blend` accept `plane` directly, meaning a face found here
    is placed by the author into an operation without a single manual
    recomputation. The `x_dir` axis is chosen deterministically — from
    world X, or from world Y when the normal runs along it — otherwise the
    same mesh would produce different programs from run to run.
    """
    n = normal
    ref = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    x = _cross(ref, n)
    ln = _norm(x)
    if ln == 0.0:                                   # unreachable when |n| = 1
        x = (1.0, 0.0, 0.0)
        ln = 1.0
    x = (x[0] / ln, x[1] / ln, x[2] / ln)
    return {"origin_mm": [round(v, 6) for v in origin],
            "normal": [round(v, 9) for v in n],
            "x_dir": [round(v, 9) for v in x]}


def _facing(n) -> str:
    if n[2] > 0.999:
        return "up"
    if n[2] < -0.999:
        return "down"
    if abs(n[1]) >= abs(n[0]):
        return "north" if n[1] > 0 else "south"
    return "east" if n[0] > 0 else "west"


def faces(shape: Any, facing: Optional[str] = None) -> list[dict]:
    """BODY FACES: normal, center, area, ring, plane, thickness.

    This is the load-bearing contract of the entire "freeform" branch: on
    it rests the future ADVANCEMENT of shape into BIM (a vertical strip ->
    a wall, a horizontal area -> a floor slab, a sloped one -> a roof) and
    face addressing in `create_face_wall`. That is why every face carries
    EVERYTHING these decisions are made from, and not a single field is
    made up.

        for f in faces(оболочка, facing="south"):
            create_solid_extrusion(profile=..., plane=f["plane"], ...)

    FIELDS OF EACH FACE:
      `normal`        the unit outward normal (from triangle winding)
      `centroid_mm`   the area centroid, not the average of the vertices
      `area_mm2`      the sum of the areas of the face's triangles
      `ring_mm`       the boundary ring in 3D, by walking the face's edges
      `poly`          the same ring as the `poly` kind — ONLY for
                      horizontal faces, where it lies flat onto the plan
                      without projection
      `plane`         the language's `plane` kind: placed into an
                      operation as is
      `facing`        up · down · north · south · east · west
      `thickness_mm`  the distance to the OPPOSING face of the same area,
                      if there is exactly one; otherwise `None`
      `thickness_reason` why there is no thickness — in words, not silence

    🔴 `thickness_mm` = None DOES NOT MEAN "zero". It means "there is not
    exactly one opposing face of the same area": for a pyramid, a beveled
    body, a complex shell. Pattern 44 of this tree was bought exactly on
    this: an uncomputed quantity is printed as a word, not as a plausible
    number.
    """
    m = _mesh_of(shape, "shape")
    verts = m["vertices_mm"]
    tris = m["triangles"]
    groups: dict[tuple, dict] = {}
    for t in tris:
        a, b, c = (verts[t[0]], verts[t[1]], verts[t[2]])
        n = _cross(_sub(b, a), _sub(c, a))
        ln = _norm(n)
        if ln <= 0.0:                       # degenerate triangle
            continue
        area = ln / 2.0
        n = (n[0] / ln, n[1] / ln, n[2] / ln)
        off = _dot(n, a)
        gk = (round(n[0] / _NORMAL_Q), round(n[1] / _NORMAL_Q),
              round(n[2] / _NORMAL_Q), round(off / _OFFSET_Q))
        g = groups.setdefault(gk, {"normal": n, "offset": off, "area": 0.0,
                                   "cx": 0.0, "cy": 0.0, "cz": 0.0,
                                   "edges": {}, "tris": 0})
        g["area"] += area
        g["cx"] += area * (a[0] + b[0] + c[0]) / 3.0
        g["cy"] += area * (a[1] + b[1] + c[1]) / 3.0
        g["cz"] += area * (a[2] + b[2] + c[2]) / 3.0
        g["tris"] += 1
        for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            back = (e[1], e[0])
            if back in g["edges"]:
                del g["edges"][back]        # an interior edge of the face
            else:
                g["edges"][e] = True

    out: list[dict] = []
    for g in groups.values():
        ring_idx = _chain_edges(list(g["edges"]))
        ring = ([[round(v, 6) for v in verts[i]] for i in ring_idx]
                if ring_idx else [])
        n = g["normal"]
        centroid = (g["cx"] / g["area"], g["cy"] / g["area"],
                    g["cz"] / g["area"])
        face = {"normal": [round(v, 9) for v in n],
                "centroid_mm": [round(v, 6) for v in centroid],
                "area_mm2": round(g["area"], 6),
                "ring_mm": ring,
                "plane": _plane_value(n, centroid),
                "facing": _facing(n),
                "triangles": g["tris"],
                "offset_mm": g["offset"],
                "thickness_mm": None,
                "thickness_reason": None}
        if not ring:
            face["ring_reason"] = ("граничные рёбра не сомкнулись в одно "
                                   "кольцо — у грани дыра или разрыв")
        elif face["facing"] in ("up", "down"):
            face["poly"] = {"shape": "poly",
                            "points_mm": [[p[0], p[1]] for p in ring]}
        out.append(face)

    _fill_thickness(out)
    for f in out:
        f.pop("offset_mm", None)
    out.sort(key=lambda f: (-f["area_mm2"], f["centroid_mm"]))
    if facing is not None:
        known = {"up", "down", "north", "south", "east", "west", "side"}
        if facing not in known:
            _refuse(TYPE_BAD_TYPE, "facing",
                    f"facing: {facing!r} — не сторона. Стороны закрытым "
                    f"списком: {sorted(known)}", got=facing)
        if facing == "side":
            return [f for f in out if f["facing"] not in ("up", "down")]
        return [f for f in out if f["facing"] == facing]
    return out


def _fill_thickness(fs: list[dict]) -> None:
    """Thickness = the distance to the opposing face of the same area, if
    there is exactly ONE.

    It is precisely this quantity that decides "is this a strip or not"
    for the future advancement into a wall, so ambiguity here must be
    named, not averaged away.
    """
    for i, f in enumerate(fs):
        n = f["normal"]
        cand = []
        for j, g in enumerate(fs):
            if i == j:
                continue
            if _dot(n, g["normal"]) > _OPPOSITE_COS:
                continue
            if abs(g["area_mm2"] - f["area_mm2"]) > _AREA_MATCH * max(
                    1.0, f["area_mm2"]):
                continue
            cand.append(g)
        if len(cand) == 1:
            f["thickness_mm"] = round(abs(f["offset_mm"] + cand[0]["offset_mm"]), 6)
        elif not cand:
            f["thickness_reason"] = ("встречной грани такой же площади нет — "
                                     "тело не призматично по этой оси")
        else:
            f["thickness_reason"] = (
                f"встречных граней такой же площади {len(cand)}, а не одна — "
                f"какая из них «та же с другой стороны», из геометрии не "
                f"следует")


def _chain_edges(edges) -> Optional[list[int]]:
    """Directed boundary edges -> a single ring. Did not close — `None`."""
    if not edges:
        return None
    nxt: dict[int, list[int]] = {}
    for a, b in edges:
        nxt.setdefault(a, []).append(b)
    start = edges[0][0]
    ring = [start]
    cur = start
    for _ in range(len(edges)):
        outs = nxt.get(cur)
        if not outs:
            return None
        nxt[cur] = outs[1:]
        cur = outs[0]
        if cur == start:
            return ring if len(ring) >= MIN_RING_POINTS else None
        ring.append(cur)
    return None


# ──────────────────────────────────────────────────────────── SECTION

def section(shape: Any, z_mm: Any) -> dict:
    """A HORIZONTAL SECTION OF A BODY -> the language's `region`.

        план_этажа = section(оболочка, 3300)
        create_floor_by_contour(profile=план_этажа, ...)

    Answers the question that comes up first for an author who has just
    built a shell: "so what does it look like at the floor elevation".
    Computed as the intersection of triangles with the plane — that is, it
    READS what has already been built, and adds nothing of its own.

    🔴 TWO NAMED REFUSALS, AND BOTH ARE A BOUNDARY OF THE LANGUAGE, NOT OF
    THE INSTRUMENT:
      * the section did not intersect the body — a refusal, not an empty
        area: an empty area is indistinguishable from "computed it, and
        there's nothing there";
      * the section split into TWO disconnected pieces — a refusal. The
        `region` kind has exactly one outer ring, and merging two pieces
        into one would mean lying about the shape. This is exactly the
        limit that gets lifted by separate work (multiple outer rings),
        not by a prop here.
    """
    m = _mesh_of(shape, "shape")
    z = _num(z_mm, "z_mm", "отметка сечения")
    verts = m["vertices_mm"]
    segs: list[tuple[tuple, tuple]] = []
    in_plane = 0
    for t in m["triangles"]:
        vs = [verts[i] for i in t]
        ds = [v[2] - z for v in vs]
        if all(abs(d) < _PLANE_EPS for d in ds):
            in_plane += 1
            continue
        if all(d > _PLANE_EPS for d in ds) or all(d < -_PLANE_EPS for d in ds):
            continue
        hits = []
        for i in range(3):
            a, b = vs[i], vs[(i + 1) % 3]
            da, db = ds[i], ds[(i + 1) % 3]
            if abs(da) < _PLANE_EPS:
                hits.append((a[0], a[1], z))
            if (da > _PLANE_EPS and db < -_PLANE_EPS) or (
                    da < -_PLANE_EPS and db > _PLANE_EPS):
                k = da / (da - db)
                hits.append((a[0] + k * (b[0] - a[0]),
                             a[1] + k * (b[1] - a[1]), z))
        uniq = []
        for h in hits:
            if all(_key(h) != _key(u) for u in uniq):
                uniq.append(h)
        if len(uniq) == 2:
            segs.append((uniq[0], uniq[1]))
    if not segs:
        _refuse(TYPE_GEOM_RELATION, "z_mm",
                f"сечение на отметке {z} мм не пересекло тело"
                + (f" (в плоскости лежат {in_plane} треугольников — это ГРАНЬ, "
                   f"а не сечение: спроси faces())" if in_plane else "")
                + ". Пустая область здесь была бы неотличима от «посчитали и "
                  "там ничего нет»", got=z)
    rings = _rings_from_segments(segs)
    if rings is None:
        _refuse(TYPE_GEOM_RELATION, "z_mm",
                f"на отметке {z} мм отрезки сечения не сомкнулись в кольца — "
                f"меш не замкнут по этой плоскости", got=z)
    rings = [_drop_collinear(r) for r in rings]
    rings.sort(key=lambda r: abs(_signed_area(r)), reverse=True)
    outer, rest = rings[0], rings[1:]
    holes = []
    for r in rest:
        if _point_in_ring(r[0], outer):
            holes.append(r)
        else:
            _refuse(TYPE_GEOM_RELATION, "z_mm",
                    f"сечение на отметке {z} мм распалось на {len(rings)} "
                    f"НЕСВЯЗНЫХ куска. У рода `region` ровно одно внешнее "
                    f"кольцо; собрать их в одно значило бы соврать про форму. "
                    f"Режь по кускам либо строй их порознь", got=len(rings))
    return _contour.region([[p[0], p[1]] for p in outer],
                           [[[p[0], p[1]] for p in h] for h in holes] or None)


def _drop_collinear(ring: list) -> list:
    """Remove vertices that lie EXACTLY on the segment between their
    neighbors.

    Not a simplification of shape, but the removal of a triangulation
    artifact: the mesh cuts the face into triangles, and points that say
    nothing about the figure end up in the section ring, while still being
    paid for against the ring limit (`MAX_RING_POINTS`). The threshold is
    the area of the triangle formed by three neighboring points: it equals
    zero exactly when the point is redundant, and turns into a tolerance
    only through rounding error.
    """
    if len(ring) <= MIN_RING_POINTS:
        return ring
    out = []
    n = len(ring)
    for i in range(n):
        a, b, c = ring[(i - 1) % n], ring[i], ring[(i + 1) % n]
        cross = ((b[0] - a[0]) * (c[1] - a[1])
                 - (b[1] - a[1]) * (c[0] - a[0]))
        if abs(cross) > _PLANE_EPS:
            out.append(b)
    return out if len(out) >= MIN_RING_POINTS else ring


def _rings_from_segments(segs) -> Optional[list[list]]:
    """Undirected segments -> closed rings. Did not close — `None`."""
    adj: dict[tuple, list] = {}
    for a, b in segs:
        if _key(a) == _key(b):
            continue
        adj.setdefault(_key(a), []).append((_key(b), a, b))
        adj.setdefault(_key(b), []).append((_key(a), b, a))
    rings = []
    seen_edges: set = set()
    for start_key in list(adj):
        for _kb, pa, _pb in adj.get(start_key, []):
            eid = frozenset((start_key, _kb))
            if eid in seen_edges:
                continue
            ring = [pa]
            cur, prev = _kb, start_key
            seen_edges.add(eid)
            ok = False
            for _ in range(len(segs) + 2):
                if cur == start_key:
                    ok = True
                    break
                nxts = [x for x in adj.get(cur, [])
                        if x[0] != prev and frozenset((cur, x[0])) not in seen_edges]
                if not nxts:
                    break
                nk, npa, _npb = nxts[0]
                seen_edges.add(frozenset((cur, nk)))
                ring.append(npa)
                prev, cur = cur, nk
            if not ok or len(ring) < MIN_RING_POINTS:
                return None
            rings.append(ring)
    return rings or None


# ────────────────────────────────────────────────────────────── LOFT

def loft(sections: Any, *, category: str = "mass", name: str = "loft",
         base_id: Optional[str] = None) -> dict:
    """A CHAIN OF SECTIONS -> A BODY. Returns operations AND a mesh for
    querying.

        оболочка = loft([(низ, 0), (середина, 15000), (верх, 30000)],
                        name="башня")
        for f in faces(оболочка, facing="south"): ...
        план = section(оболочка, 15000)

    🔴 THE LOFT HERE IS PIECEWISE, NOT SMOOTH, AND THIS IS NAMED IN THE
    OUTPUT. Revit does have a smooth loft (`CreateLoftGeometry`, compiles
    on all six versions), but it has NO honest witness of volume: there is
    nothing to check what was built against what was ordered.
    `create_solid_blend` has a witness, so the body is assembled as a
    chain of blends between neighboring sections. Between sections the
    surface is STRAIGHT; want curvature — give it more sections.

    WHAT IS RETURNED (a `dict`, not a new kind of value):
      `ops`      operation handles, in bottom-to-top order
      `mesh`     a mesh for `faces()`/`section()` — or `None` with a reason
      `sections` how many sections were accepted
      `note`     the verbatim boundary of the shape, so it reaches the
                 author

    🔴 THERE IS NO MESH WHEN NEIGHBORING SECTIONS HAVE A DIFFERENT NUMBER OF
    POINTS — OR WHEN THEY HAVE DIFFERENT OPENINGS. In both cases the vertex
    correspondence is chosen by Revit, and any triangulation of ours would
    be a story about a body we did not build. `mesh_absent_reason` says
    this in words; the operations are still built and the body comes out
    real.

    🔴 THE MESH CARRIES THE PROFILE'S OPENINGS, and the cap is cut by EAR
    CLIPPING, not by a fan. Before 04.09.2026 the cap was assembled as a
    fan from vertex 0, and this produced two lies at once: a concave
    profile gets covered OUTSIDE itself (measured on the "П" shape:
    52,000,000 against an honest 40,000,000), and an opening got filled in
    solid (a 10×10 m square with a 4×4 m opening: 100,000,000 against
    84,000,000). Both quantities are what the author looks at when
    deciding what to build.
    """
    if not isinstance(sections, (list, tuple)) or len(sections) < 2:
        _refuse(TYPE_BAD_TYPE, "sections",
                "sections: лофт начинается с ДВУХ сечений — "
                f"пришло {len(sections) if isinstance(sections, (list, tuple)) else type(sections).__name__}",
                got=len(sections) if isinstance(sections, (list, tuple)) else None)
    prepared: list[tuple[dict, float, list]] = []
    for i, s in enumerate(sections):
        if isinstance(s, dict) and "profile" in s:
            prof, z = s["profile"], s.get("z_mm", 0.0)
        elif isinstance(s, (list, tuple)) and len(s) == 2:
            prof, z = s[0], s[1]
        else:
            _refuse(TYPE_BAD_TYPE, f"sections[{i}]",
                    f"sections[{i}]: сечение — это пара (профиль, отметка) "
                    f"либо {{'profile': …, 'z_mm': …}}", got=repr(s)[:60])
        reg = _as_region(prof, f"sections[{i}].profile")
        prepared.append((reg, _num(z, f"sections[{i}].z_mm", "отметка сечения"),
                         _ring_points(reg, f"sections[{i}].profile")))
    for i in range(1, len(prepared)):
        if prepared[i][1] <= prepared[i - 1][1]:
            _refuse(TYPE_GEOM_RELATION, f"sections[{i}].z_mm",
                    f"отметки сечений обязаны расти: sections[{i}] на "
                    f"{prepared[i][1]} мм не выше sections[{i-1}] на "
                    f"{prepared[i-1][1]} мм", got=prepared[i][1])

    ops = []
    for i in range(len(prepared) - 1):
        lo, hi = prepared[i], prepared[i + 1]
        kw = {"profile": lo[0], "profile_top": hi[0],
              "base_z_mm": lo[1], "height_mm": hi[1] - lo[1],
              "category": category,
              "name": f"{name}/{i + 1}" if len(prepared) > 2 else name}
        if base_id:
            kw["id"] = f"{base_id}_{i + 1}"
        ops.append(_dsl.create_solid_blend(**kw))

    mesh, reason = _loft_mesh(prepared)
    return {"ops": ops, "mesh": mesh, "mesh_absent_reason": reason,
            "sections": len(prepared),
            "note": ("тело собрано цепочкой блендов: между соседними сечениями "
                     "поверхность ПРЯМАЯ, а не гладкая — кривизна набирается "
                     "числом сечений")}


# ────────────────────────────────────── CAP: EAR CLIPPING WITH BRIDGES
#
# 🔴 WHAT IS CLOSED HERE, TWO DEFECTS OF ONE CAP.
#
# RT-02 — A FAN FROM VERTEX 0 COVERS AREA OUTSIDE THE POLYGON. The cap was
# assembled as `tris.append([bottom[0], bottom[i], bottom[i + 1]])`, and a
# fan is only correct for a CONVEX ring. Measured with a control:
#
#     CONTROL convex square      : fan 36,000,000 = exact area  (×1.000)
#     concave "П"                : area 40,000,000, fan 52,000,000 (×1.300)
#
# RT-01 — OPENINGS WERE BEING FILLED IN. The author's op carries `holes`
# (`_as_region` preserves them "WITHOUT losing holes"), while `_loft_mesh`
# did not know the word `hole` at all: `_ring_points` returns ONLY the
# outer ring. Measured, a 10×10 m square with a 4×4 m opening: cap
# 100,000,000 mm² against an honest 84,000,000 (×1.190). The preview
# showed a solid slab where the model has a hole — and `section()` on such
# a mesh also returned an area WITHOUT the opening.
#
# THE COST IS MEASURED, NOT ASSUMED, AND MEASURED FOR THE WHOLE OF `loft`,
# NOT FOR THE CLIPPING ALONE: the caller pays, and pays TWICE (bottom and
# top). The clipping runs on a linked list, and reflex vertices are kept
# in a separate set.
#
#     a square of 4 points                    0.3 ms
#     a circle of 256 points, no openings     3.9 ms
#     a circle of 256 + 8 openings of 32     31.4 ms
#     WORST CASE AT THE LANGUAGE'S LIMITS
#       (`MAX_RING_POINTS` 256 × `MAX_HOLES` 8):
#       a circle of 256 + 8 openings of 256  748.5 ms
#
# The cap's area matched the exact value TO THE NINTH DIGIT across every
# measurement. The worst case is a limit of the language, not a working
# quantity: a building's profile runs to single-digit points, and there
# the cost is under a third of a millisecond.


def _ear_clip(poly: list) -> Optional[list[list[int]]]:
    """A CCW ring without self-intersections -> triangles (indices into
    `poly`).

    `None` — the clipping did not converge (the ring is degenerate or
    self-intersecting). Silently returning part of the triangles would be
    a cap with a hole nobody mentioned; the same law applies here as with
    `mesh_absent_reason`.
    """
    n = len(poly)
    if n < 3:
        return None
    nxt = [(i + 1) % n for i in range(n)]
    prv = [(i - 1) % n for i in range(n)]
    alive = [True] * n

    def reflex(i: int) -> bool:
        a, b, c = poly[prv[i]], poly[i], poly[nxt[i]]
        return ((b[0] - a[0]) * (c[1] - a[1])
                - (b[1] - a[1]) * (c[0] - a[0])) <= 0

    concave = {i for i in range(n) if reflex(i)}
    tris: list[list[int]] = []
    left, cur, guard = n, 0, 0
    limit = 4 * n + 64
    while left > 3:
        guard += 1
        if guard > limit:
            return None
        i0, i1, i2 = prv[cur], cur, nxt[cur]
        p0, p1, p2 = poly[i0], poly[i1], poly[i2]
        if ((p1[0] - p0[0]) * (p2[1] - p0[1])
                - (p1[1] - p0[1]) * (p2[0] - p0[0])) > 0:
            lox = min(p0[0], p1[0], p2[0]); hix = max(p0[0], p1[0], p2[0])
            loy = min(p0[1], p1[1], p2[1]); hiy = max(p0[1], p1[1], p2[1])
            clean = True
            for j in concave:
                if not alive[j] or j in (i0, i1, i2):
                    continue
                q = poly[j]
                if q[0] < lox or q[0] > hix or q[1] < loy or q[1] > hiy:
                    continue
                # THE BRIDGE VERTEX LIES IN THE RING TWICE, and by
                # coordinates it coincides with the ear's corner.
                # Considering it "a stranger inside" would mean forbidding
                # clipping along the bridge — that is, refusing every cap
                # with an opening.
                if q == p0 or q == p1 or q == p2:
                    continue
                if _in_triangle(q, p0, p1, p2):
                    clean = False
                    break
            if clean:
                tris.append([i0, i1, i2])
                alive[i1] = False
                concave.discard(i1)
                nxt[i0], prv[i2] = i2, i0
                left -= 1
                guard = 0
                for j in (i0, i2):
                    if reflex(j):
                        concave.add(j)
                    else:
                        concave.discard(j)
                cur = i0
                continue
        cur = nxt[cur]
    tris.append([prv[cur], cur, nxt[cur]])
    return tris


def _in_triangle(p, a, b, c) -> bool:
    """A point inside a CCW triangle (the boundary counts as inside)."""
    if ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) < 0:
        return False
    if ((c[0] - b[0]) * (p[1] - b[1]) - (c[1] - b[1]) * (p[0] - b[0])) < 0:
        return False
    return ((a[0] - c[0]) * (p[1] - c[1])
            - (a[1] - c[1]) * (p[0] - c[0])) >= 0


def _bridge_hole(ring: list, hole: list) -> Optional[list]:
    """Cut an opening into the ring with a BRIDGE. Pairs of `(point,
    vertex index)`.

    The method is the canonical one (Eberly): a ray in +x is cast from the
    RIGHTMOST vertex of the opening, the nearest intersection with the ring
    is taken, and the bridge becomes the right end of the edge found — or
    the reflex vertex inside the triangle "opening vertex — hit point —
    edge end" that is closest by angle. A method of our own here would be
    a fourth carrier of the same geometry.
    """
    m = max(range(len(hole)), key=lambda i: (hole[i][0][0], hole[i][0][1]))
    mx, my = hole[m][0][0], hole[m][0][1]
    best_t, best_edge = None, None
    n = len(ring)
    for i in range(n):
        (ax, ay), (bx, by) = ring[i][0], ring[(i + 1) % n][0]
        if (ay > my) == (by > my):
            continue
        t = ax + (my - ay) * (bx - ax) / (by - ay)
        if t < mx:
            continue
        if best_t is None or t < best_t:
            best_t, best_edge = t, i
    if best_edge is None:
        return None
    hit = (best_t, my)
    (ax, _ay), (bx, _by) = ring[best_edge][0], ring[(best_edge + 1) % n][0]
    p_idx = best_edge if ax > bx else (best_edge + 1) % n
    peak = ring[p_idx][0]
    pick = p_idx
    if abs(peak[0] - hit[0]) > 1e-9 or abs(peak[1] - hit[1]) > 1e-9:
        best_key = None
        for i in range(n):
            if i == p_idx:
                continue
            r = ring[i][0]
            prev, nxt = ring[(i - 1) % n][0], ring[(i + 1) % n][0]
            if ((r[0] - prev[0]) * (nxt[1] - prev[1])
                    - (r[1] - prev[1]) * (nxt[0] - prev[0])) > 0:
                continue                       # convex — does not obstruct the bridge
            if not _in_triangle(r, (mx, my), hit, peak):
                continue
            dx, dy = r[0] - mx, r[1] - my
            d = math.hypot(dx, dy)
            key = (-1.0, 0.0) if d == 0 else (-dx / d, d)
            if best_key is None or key < best_key:
                best_key, pick = key, i
    return ring[:pick + 1] + hole[m:] + hole[:m + 1] + ring[pick:]


def _cap_indices(outer: list, holes: list) -> Optional[list[list[int]]]:
    """The cap of ONE section -> triples of LOCAL indices, CCW winding.

    Local numbering: `0..len(outer)-1` is the outer ring, then the
    openings one after another in the order `_loft_mesh` places them into
    the vertices. Rings are normalized BY THE SIGN OF THEIR OWN AREA (outer
    CCW, openings CW) — the same law by which `contour.region_measures`
    computes: the point order declared by the author can be anything, and
    the sign of the area is the one fact about winding that we have.
    """
    ring = [(p, i) for i, p in enumerate(outer)]
    if _signed_area(outer) < 0:
        ring = ring[::-1]
    base = len(outer)
    holed = []
    for hole in holes:
        piece = [(p, base + i) for i, p in enumerate(hole)]
        if _signed_area(hole) > 0:
            piece = piece[::-1]
        base += len(hole)
        holed.append(piece)
    # Right to left: the bridge is built with a ray in +x, and an opening
    # cut earlier must not block the next one's path out to the outer
    # ring.
    holed.sort(key=lambda piece: -max(pt[0][0] for pt in piece))
    for piece in holed:
        ring = _bridge_hole(ring, piece)
        if ring is None:
            return None
    tris = _ear_clip([pt for pt, _ in ring])
    if tris is None:
        return None
    return [[ring[a][1], ring[b][1], ring[c][1]] for a, b, c in tris]


def _hole_rings(reg: Any, field: str) -> list[list[tuple[float, float]]]:
    """An area's openings -> lists of points. Not an area, or no
    openings -> `[]`."""
    if not isinstance(reg, dict):
        return []
    holes = reg.get("holes")
    if not holes:
        return []
    if not isinstance(holes, (list, tuple)):
        _refuse(TYPE_BAD_TYPE, f"{field}.holes",
                f"{field}.holes: список колец, пришло {type(holes).__name__}",
                got=repr(holes)[:60])
    return [_ring_points(h, f"{field}.holes[{i}]")
            for i, h in enumerate(holes)]


def _loft_mesh(prepared) -> tuple[Optional[dict], Optional[str]]:
    counts = {len(p[2]) for p in prepared}
    if len(counts) != 1:
        return None, (f"у сечений разное число точек {sorted(counts)}: "
                      f"соответствие вершин выбирает Ревит, и наша "
                      f"триангуляция описывала бы тело, которого мы не строили")
    n = counts.pop()
    holes_of = [_hole_rings(reg, f"sections[{i}].profile")
                for i, (reg, _z, _pts) in enumerate(prepared)]
    shapes = {tuple(len(h) for h in hs) for hs in holes_of}
    if len(shapes) != 1:
        # THE SAME ARGUMENT AS WITH A DIFFERING NUMBER OF POINTS ON THE
        # OUTSIDE, AND IT IS NO WEAKER HERE: the correspondence of an
        # opening's vertices between sections is chosen by Revit, and we
        # would be making it up. Silently closing the opening is exactly
        # the lie that openings were put into this mesh in order to lift.
        return None, (f"у сечений разные проёмы {sorted(shapes)}: "
                      f"соответствие вершин проёма выбирает Ревит, и наша "
                      f"триангуляция описывала бы тело, которого мы не строили")
    sizes = shapes.pop()
    stride = n + sum(sizes)
    verts: list[list[float]] = []
    for (reg, z, pts), hs in zip(prepared, holes_of):
        for x, y in pts:
            verts.append([x, y, z])
        for hole in hs:
            for x, y in hole:
                verts.append([x, y, z])
    tris: list[list[int]] = []
    levels = len(prepared)
    for lvl in range(levels - 1):
        a0, b0 = lvl * stride, (lvl + 1) * stride
        for i in range(n):
            j = (i + 1) % n
            tris.append([a0 + i, a0 + j, b0 + j])
            tris.append([a0 + i, b0 + j, b0 + i])
    # THE OPENING'S WALLS, AND THEIR WINDING IS OPPOSITE TO THE OUTER ONE.
    # Without them the mesh would be unclosed along the shaft: `section()`
    # assembles rings from segments, and an opening without walls would
    # not yield a single segment — meaning it would vanish all over again.
    offset = n
    for hi, size in enumerate(sizes):
        # THE WINDING IS DECIDED FROM THE BOTTOM SECTION, ONE FOR THE WHOLE
        # SHAFT. The vertices sit in the mesh in the AUTHOR'S order
        # (otherwise the walls would twist between levels), and the normal
        # must face INTO the opening — that is, wind opposite to the outer
        # ring. An author who gave the opening the same area sign as the
        # outer ring gets the flip applied here.
        flip = ((_signed_area(holes_of[0][hi]) >= 0)
                == (_signed_area(prepared[0][2]) >= 0))
        for lvl in range(levels - 1):
            a0, b0 = lvl * stride + offset, (lvl + 1) * stride + offset
            for i in range(size):
                j = (i + 1) % size
                if flip:
                    tris.append([a0 + j, a0 + i, b0 + i])
                    tris.append([a0 + j, b0 + i, b0 + j])
                else:
                    tris.append([a0 + i, a0 + j, b0 + j])
                    tris.append([a0 + i, b0 + j, b0 + i])
        offset += size
    for level, block in ((0, 0), (levels - 1, (levels - 1) * stride)):
        cap = _cap_indices(prepared[level][2], holes_of[level])
        if cap is None:
            return None, (
                f"крышку сечения #{level + 1} не удалось разрезать на "
                f"треугольники: кольцо вырождено либо само себя пересекает. "
                f"Меш с частичной крышкой описывал бы тело, которого нет")
        # BOTTOM FACES DOWN, TOP FACES UP — the same behavior as the
        # earlier fan (it flipped ONE of the caps by the sign of the
        # area), except now the order is set by the clipping's winding,
        # not by the sign of the author's ring.
        for a, b, c in cap:
            if level == 0:
                tris.append([block + c, block + b, block + a])
            else:
                tris.append([block + a, block + b, block + c])
    return {"vertices_mm": verts, "triangles": tris}, None


def _shape_from_op(op: Any) -> Optional[dict]:
    """AN OPERATION -> A SHAPE WITH A MESH. The reverse pass of `loft`, on
    the same carrier.

    🔴 THE LEADING UNDERSCORE IN THE NAME IS DELIBERATE, AND THIS IS A
    MODULE RULE, NOT TASTE. A public name HERE would be a promise TO THE
    AUTHOR: the `test_rhino_vocabulary` guard requires the module's surface
    to match the sandbox seam (`RHINO_NAMES`). The author has no reason to
    read an operation back — this is a door for US
    (`promote.unpromoted`, the self-check, the receipt). The first edition
    was public, and the guard went red on the very next full run.

    Needed by whoever reads an ALREADY-WRITTEN program and must say
    something honest about its bodies: the intent self-check, the
    envelope, the decompile. The shape `loft` returned lives in the
    author's variable and never reaches them — the operation is what
    reaches them.

    The mesh is assembled by the SAME `_loft_mesh` that `loft` used to
    assemble it: two different walks would diverge, and diverge silently —
    nobody checks triangles by eye. Verified by a run on 02.09.2026: the
    reassembled mesh matched the live one down to the last digit.

    THE ONE LAW OF THE BOUNDARY: **reading what was written is always
    allowed; reassembling is allowed only where the reassembly has been
    checked against whoever built it.** That is why `create_directshape`
    is taken as is (the mesh sits in the operation), while
    `create_solid_blend` is reassembled by the same `_loft_mesh`. For
    `create_solid_extrusion` the reassembly is deliberately NOT done: it
    has a `plane` slot, a tilted plane changes the whole body, and there is
    nothing to check the result against — this operation's shape
    dictionary generates none. A plausible mesh is worse than a missing
    one.

    `None` is not an empty answer but the ABSENCE OF A SUBJECT, and calling
    it "no geometry" would be a lie in the direction of "we've read
    everything". Whoever calls this must name `None` in words.
    """
    if not isinstance(op, dict):
        return None
    род = op.get("op")
    if род == "create_directshape":
        # NOTHING IS REASSEMBLED HERE: the mesh sits in the operation
        # itself, the author wrote it. Reading what was written is always
        # allowed; REASSEMBLING is allowed only where the reassembly has
        # been checked against whoever built it (below,
        # `create_solid_blend`).
        m = op.get("mesh")
        if not isinstance(m, dict) or set(m) != {"vertices_mm", "triangles"}:
            return None
        return {"ops": [], "mesh": m, "mesh_absent_reason": None,
                "sections": None, "from_op": op.get("id")}
    if род != "create_solid_blend":
        return None
    prof, prof_top = op.get("profile"), op.get("profile_top")
    if prof is None or prof_top is None:
        return None
    try:
        z0 = float(op.get("base_z_mm") or 0.0)
        z1 = z0 + float(op["height_mm"])
        prepared = [(prof, z0, _ring_points(prof, "profile")),
                    (prof_top, z1, _ring_points(prof_top, "profile_top"))]
    except (KirRefusal, KeyError, TypeError, ValueError):
        # A ring-parsing failure is a fact about the RECORDED operation,
        # not a defect of ours: the program could have arrived over the
        # wire. `None` rides upward, and the caller will name it in words.
        return None
    mesh, reason = _loft_mesh(prepared)
    if mesh is None:
        return None
    # `ops` is empty ON PURPOSE: a shape reassembled from an operation does
    # not own any handles. Otherwise retraction (`promote._retract`) would
    # think there is something for it to remove.
    return {"ops": [], "mesh": mesh, "mesh_absent_reason": reason,
            "sections": 2, "from_op": op.get("id")}


# ─────────────────────────────────────────────── bodies in a single operation

def blend(bottom: Any, top: Any, height_mm: Any, *, base_z_mm: Any = 0.0,
          category: str = "mass", name: str = "blend", **kw) -> Any:
    """A transition from one section to another, in a single operation."""
    return _dsl.create_solid_blend(
        profile=_as_region(bottom, "bottom"), profile_top=_as_region(top, "top"),
        height_mm=height_mm, base_z_mm=base_z_mm, category=category, name=name,
        **kw)


def revolve(profile: Any, axis_xy_mm: Any, *, sweep_deg: Any = 360.0,
            base_z_mm: Any = 0.0, category: str = "mass",
            name: str = "revolve", **kw) -> Any:
    """A body of revolution of a profile around a vertical axis."""
    return _dsl.create_solid_revolve(
        profile=_as_region(profile, "profile"), axis_xy_mm=axis_xy_mm,
        sweep_deg=sweep_deg, base_z_mm=base_z_mm, category=category, name=name,
        **kw)


# ──────────────────────────────────────────── boolean operands (parts)

def box(center_mm: Any, size_mm: Any) -> dict:
    """A box — a boolean operand (`create_solid_boolean.parts`)."""
    return {"shape": "box", "center_mm": list(center_mm),
            "size_mm": list(size_mm)}


def sphere(center_mm: Any, radius_mm: Any) -> dict:
    """A sphere — a boolean operand."""
    return {"shape": "sphere", "center_mm": list(center_mm),
            "radius_mm": radius_mm}


def cylinder(center_mm: Any, radius_mm: Any, height_mm: Any) -> dict:
    """A cylinder — a boolean operand."""
    return {"shape": "cylinder", "center_mm": list(center_mm),
            "radius_mm": radius_mm, "height_mm": height_mm}


def prism(profile: Any, height_mm: Any, *, base_z_mm: Any = None,
          plane: Any = None) -> dict:
    """A prism over an ARBITRARY contour — a boolean operand.

    This is exactly the kind used to say a niche of an irregular outline:
    what is subtracted is not a set of boxes but the shape the author
    drew.
    """
    part: dict = {"shape": "prism", "profile": _as_region(profile, "profile"),
                  "height_mm": height_mm}
    if base_z_mm is not None:
        part["base_z_mm"] = base_z_mm
    if plane is not None:
        part["plane"] = plane
    return part


# ─────────────────────────────────────────────────────── transforms

def _map_points(value: Any, fn, field: str) -> Any:
    """A transform that PRESERVES the kind of value: what came in is what
    leaves."""
    if isinstance(value, (list, tuple)) and value and isinstance(
            value[0], (dict, list, tuple)) and not is_finite_number(
                value[0][0] if isinstance(value[0], (list, tuple)) else None):
        return [_map_points(v, fn, field) for v in value]
    if isinstance(value, dict):
        if "vertices_mm" in value:
            return {**value,
                    "vertices_mm": [list(fn(v)) for v in value["vertices_mm"]]}
        if "outer" in value:
            out = {**value, "outer": _map_points(value["outer"], fn, field)}
            if value.get("holes"):
                out["holes"] = [_map_points(h, fn, field)
                                for h in value["holes"]]
            return out
        if value.get("shape") == "poly":
            return {**value,
                    "points_mm": [list(fn(list(p) + [0.0])[:2])
                                  for p in value["points_mm"]]}
        if "mesh" in value:
            # 🔴 A CARRIER WITH LIVE HANDLES DOES NOT MOVE (RT-03). What
            # traveled here was only the mesh, while `ops` were carried
            # over INTO THE CARRIER AS IS — THE SAME OBJECTS. Measured:
            # `move(loft(...), 100000, 0, 0)` gives a mesh with
            # x∈[100000, 106000], while the op IN THE PROGRAM stays at
            # x∈[0, 6000]. The preview moved, the building did not.
            #
            # WHY NOT "MOVE THE OPS TOO". Because there is nothing to move:
            # `loft` calls `_dsl.create_solid_blend`, and the op ALREADY
            # SITS IN THE CURRENT PROGRAM, and the handle is its ADDRESS,
            # not a copy (`dsl.Handle`). Rewriting coordinates by address
            # would mean `move` silently edits an already-written program,
            # and `array(body, 5)` would move ONE AND THE SAME op five
            # times. The order in the language runs the other way: first
            # you move the PROFILE (`poly`/`region` — these do get moved
            # here), then you build the body from it.
            #
            # WHY NOT SILENTLY RETURN `ops: []`. Because then
            # `array(body, 5)` would hand back five pictures without a
            # single operation, and the author would believe they had
            # built five towers. A refusal that names the true shape is
            # the same law by which `_shape_from_op` returns `ops: []` and
            # says so in words.
            if value.get("ops"):
                _refuse(TYPE_BAD_TYPE, field,
                        f"{field}: у этой формы {len(value['ops'])} живых "
                        f"ручек — операции УЖЕ лежат в программе, и сдвинулась "
                        f"бы только картинка. Двигай ПРОФИЛЬ до постройки: "
                        f"`loft([(move(профиль, dx, dy), 0), …])`, а не тело "
                        f"после неё",
                        got=len(value["ops"]))
            return {**value, "mesh": _map_points(value["mesh"], fn, field)
                    if value["mesh"] else None}
        _refuse(TYPE_BAD_TYPE, field,
                f"{field}: двигается `poly`, `region`, меш или их список; "
                f"форма {value.get('shape')!r} несёт свои размеры и origin",
                got=value.get("shape"))
    if isinstance(value, (list, tuple)):
        return [list(fn(list(p) + [0.0]))[:len(p)] for p in value]
    _refuse(TYPE_BAD_TYPE, field,
            f"{field}: нечего двигать — пришло {type(value).__name__}",
            got=repr(value)[:60])


def move(shape: Any, dx_mm: Any = 0.0, dy_mm: Any = 0.0,
         dz_mm: Any = 0.0) -> Any:
    """A shift of the shape. The kind of value is preserved: a contour
    stays a contour."""
    dx = _num(dx_mm, "dx_mm", "сдвиг")
    dy = _num(dy_mm, "dy_mm", "сдвиг")
    dz = _num(dz_mm, "dz_mm", "сдвиг")
    return _map_points(shape, lambda p: (p[0] + dx, p[1] + dy, p[2] + dz),
                       "shape")


def rotate(shape: Any, deg: Any, *, about_mm: Any = (0.0, 0.0)) -> Any:
    """A rotation AROUND THE VERTICAL AXIS by an angle in degrees.

    🔴 The axis is vertical only, and this is named, not left unsaid: a
    tilted rotation is expressed through the sketch plane (`plane` on
    extrusion and blend), and a second way of saying the same thing is a
    named defect of our own.
    """
    a = math.radians(_num(deg, "deg", "угол поворота"))
    cx = _num(about_mm[0], "about_mm.x", "центр поворота")
    cy = _num(about_mm[1], "about_mm.y", "центр поворота")
    ca, sa = math.cos(a), math.sin(a)

    def fn(p):
        x, y = p[0] - cx, p[1] - cy
        return (cx + x * ca - y * sa, cy + x * sa + y * ca, p[2])
    return _map_points(shape, fn, "shape")


def mirror(shape: Any, axis: str = "x", *, at_mm: Any = 0.0) -> Any:
    """A reflection relative to a vertical plane, `x` or `y`."""
    if axis not in ("x", "y"):
        _refuse(TYPE_BAD_TYPE, "axis",
                f"axis: отражение относительно 'x' либо 'y'; пришло {axis!r}",
                got=axis)
    at = _num(at_mm, "at_mm", "положение плоскости")
    if axis == "x":
        return _map_points(shape, lambda p: (2 * at - p[0], p[1], p[2]),
                           "shape")
    return _map_points(shape, lambda p: (p[0], 2 * at - p[1], p[2]), "shape")


def scale(shape: Any, k: Any, *, about_mm: Any = (0.0, 0.0)) -> Any:
    """Scaling in plan relative to a point. Does not touch heights."""
    kk = _num(k, "k", "масштаб")
    if kk <= 0:
        _refuse(TYPE_BOUNDS, "k",
                f"k: масштаб строго положителен, пришло {kk}", got=kk)
    cx = _num(about_mm[0], "about_mm.x", "центр масштаба")
    cy = _num(about_mm[1], "about_mm.y", "центр масштаба")
    return _map_points(shape,
                       lambda p: (cx + (p[0] - cx) * kk,
                                  cy + (p[1] - cy) * kk, p[2]), "shape")


def array(shape: Any, count: Any, *, step_mm: Any = None,
          angle_deg: Any = None, about_mm: Any = (0.0, 0.0)) -> list:
    """A row of copies: LINEAR by step or POLAR by angle.

    Returns a list of shapes of the SAME kind, with the original first.
    Not a single element is created: this is a computation, not an
    operation — the author decides where to place them.
    """
    if not isinstance(count, int) or count < 1:
        _refuse(TYPE_BAD_TYPE, "count",
                f"count: число копий — целое от 1; пришло {count!r}",
                got=count)
    if (step_mm is None) == (angle_deg is None):
        _refuse(TYPE_BAD_TYPE, "step_mm",
                "ряд бывает ЛИБО линейным (`step_mm`), ЛИБО полярным "
                "(`angle_deg`); задано ни одного или оба сразу",
                got={"step_mm": step_mm, "angle_deg": angle_deg})
    out = [shape]
    for i in range(1, count):
        if step_mm is not None:
            s = list(step_mm) + [0.0, 0.0]
            out.append(move(shape, s[0] * i, s[1] * i, s[2] * i))
        else:
            out.append(rotate(shape, _num(angle_deg, "angle_deg", "угол") * i,
                              about_mm=about_mm))
    return out


# ──────────────────────────────────────────── addressing a type by PROPERTY

def by_property(param: str, value: Any, *, tol_mm: Any = None) -> dict:
    """A TYPE BY PROPERTY, RATHER THAN BY A NAME FROM SOMEONE ELSE'S
    CATALOG.

        create_wall(type=by_default(**by_property("Width", 380)), ...)

    The measured reason for existing: 47 operations out of 82 require a
    pool from a snapshot, i.e. a type NAME the author does not know and
    cannot know. The thickness, they always know. This is sugar over
    `dsl.disambiguate` — there is no mechanism of its own here, and a
    second one must not be started.

    🔴 `tol_mm` IS INEXPRESSIBLE TODAY, AND THIS IS A REFUSAL, NOT A
    ROUNDING. Grounding narrows the pool by EXACT equality
    (`ground._parameter_equals`). A tolerance would require editing
    grounding — someone else's file and someone else's decision. Pretending
    the tolerance is accounted for would mean handing the author a
    plausible, wrong type.
    """
    if not isinstance(param, str) or not param.strip():
        _refuse(TYPE_BAD_TYPE, "param",
                f"param: имя параметра типа строкой; пришло {param!r}",
                got=repr(param)[:60])
    if tol_mm is not None:
        _refuse(TYPE_BAD_TYPE, "tol_mm",
                "tol_mm: заземление сужает пул ТОЧНЫМ равенством параметра — "
                "допуска в нём нет. Округли само значение до того, что стоит в "
                "каталоге, либо назови тип именем",
                got=tol_mm)
    return {"disambiguate_by": _dsl.disambiguate(param, value)}


#: 🔴 THE SEAM INTO THE SANDBOX. Exactly what is placed into the script's
#: namespace, and not one line more. The list is HERE, while the wiring is
#: in `course/__init__.py`: a name that sits in the module and is not
#: named in the seam is dark by construction (the same law
#: `SANDBOX_NAMES` lives by).
def promote(shape: Any, **kw: Any) -> dict:
    """A SHAPE -> A NATIVE BIM OPERATION. The parsing and the law live in
    `kir.promote`.

    🔴 A LATE IMPORT IS IMPOSSIBLE HERE, AND THIS WAS BOUGHT BY A RUN
    (02.09.2026). The first edition called `from kir.promote import
    promote` inside the body — and the sandbox refused the author with
    `KIR-B004: импорт 'kir.promote' запрещён`, even though the import was
    made NOT by the author but by the language: the allow-list catches an
    import by the calling frame. The refusal was correct about the rule
    and wrong about who was at fault.
    So both ends take the MODULE at import time, and look up the NAME at
    call time: this way the cycle `rhino -> promote -> rhino` resolves
    regardless of load order, and no author frame ever executes an import.

    The body of the law lives separately, because it is not about the
    author's vocabulary but about Revit: which operations exist and which
    quantity belongs to the TYPE rather than to the shape. The sandbox seam
    lives here, in a single dictionary `RHINO_NAMES`: a second list of the
    same names would diverge from the first.
    """
    return _promote_mod.promote(shape, **kw)


RHINO_NAMES: dict[str, Any] = {
    "loft": loft,
    "blend": blend,
    "revolve": revolve,
    "box": box,
    "sphere": sphere,
    "cylinder": cylinder,
    "prism": prism,
    "move": move,
    "rotate": rotate,
    "mirror": mirror,
    "scale": scale,
    "array": array,
    "section": section,
    "faces": faces,
    "by_property": by_property,
    "promote": promote,
}

__all__ = sorted(RHINO_NAMES) + ["RHINO_NAMES"]
