"""KIR macro layer — compact programs expand to flat IR before validation
(SPEC 12.3: bounded expressiveness — no loops in the language, only named,
capped, deterministic macro patterns; v0 stack discipline preserved).

stack — a typical floor times N storeys:
    {"op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
     "base_elev_mm": 0, "name_prefix": "Level",
     "floor": [ ...create_wall / create_pipe ops, WITHOUT level... ]}
  Expands to N create_level ops (ids L1..LN) + per-storey clones of the floor
  ops (ids "L{k}_<oid>"), their `level` rewritten to {"by":"ref","value":"L{k}"}.
  Grids inside `floor` are refused — grids are not per-storey objects.

grid_array — a rectangular grid net:
    {"op": "grid_array", "id": "net", "nx": 5, "ny": 4,
     "dx_mm": 6000, "dy_mm": 6000, "origin_mm": [0,0],
     "prefix_x": "", "prefix_y": "А", "margin_mm": 1000}
  Expands to nx vertical + ny horizontal create_grid ops with deterministic
  names (X: "1".."nx" with prefix_x; Y: prefix_y+index).

series — one template repeated N times, with NAMED NUMERIC PARAMETERS read off a
PIECEWISE-LINEAR track indexed by the repetition number:
    {"op": "series", "id": "leg", "count": 20,
     "track": {"hw": [[0, 62500], [5, 30000], [10, 24000], [20, 5000]],
               "z":  [[0,     0], [5, 57000], [10, 115000], [20, 276000]]},
     "items": [{"op": "create_beam", "id": "sw",
                "p0_mm": ["-$hw",      "-$hw",      "$z"],
                "p1_mm": ["-$hw@next", "-$hw@next", "$z@next"],
                "level": {"by": "ref", "value": "L0"}}]}
  Expands to count x len(items) ops with ids "{id}_{k}_{item-id}"; every "$name"
  in a VALUE slot is replaced by the track value at index k, "$name@next" by the
  value at k+1 (so N repetitions can chain N segments over N+1 stations).

Expansion is pure and deterministic: same input -> same flat ops (goldens and
the idempotency stamp depend on this).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from kir import relate
from kir.diag import Diagnostic, KirRefusal
from kir.emit_utils import is_finite_number

MACRO_ERROR = "KIR-M001"

MAX_STACK_LEVELS = 40          # v0 cap
MAX_GRID_AXIS = 50

#: GRID STEP for `grid_array`, mm. The numbers stood as LITERALS inside the
#: expander, and the schema the MODEL reads knew nothing of them (F-117,
#: 29.08.2026): the schema allowed `dx_mm=1`, the expander answered
#: `KIR-M001`. The name was introduced so the schema would read IT, instead
#: of repeating the figures as a third carrier.
GRID_SPACING_MIN_MM = 100.0
GRID_SPACING_MAX_MM = 100_000.0

#: The closed sets of fields for EACH macro are ONE source for
#: `_closed_fields(...)` (below, in place) AND for any instrument outside
#: that needs to know "is this even an addressable field of the program?"
#: (measured 25.08.2026, `tools/mission/refusal_actionability.py`:
#: `stack.levels` did not resolve in the op registry — and could not, the
#: macro is not an op; the macro's fields were previously never named as a
#: LIST anywhere, only as a literal inside a single call). Duplicating these
#: three sets by hand in a second place would mean introducing a pair that
#: can drift apart, as other hand-written lists in this tree already have.
STACK_FIELDS = frozenset({"op", "id", "levels", "h_mm", "base_elev_mm",
                          "name_prefix", "floor", "transform"})
GRID_ARRAY_FIELDS = frozenset({"op", "id", "nx", "ny", "dx_mm", "dy_mm",
                               "origin_mm", "margin_mm", "prefix_x", "prefix_y"})
SERIES_FIELDS = frozenset({"op", "id", "count", "track", "items"})
#: The sum of the three is the addressable names of the ENTIRE macro
#: layer, the same role as `registry_base.ENVELOPE_FIELDS` has for an op's
#: envelope.
ALL_MACRO_FIELDS: frozenset[str] = STACK_FIELDS | GRID_ARRAY_FIELDS | SERIES_FIELDS
MAX_EXPANDED_OPS = 20000       # anti-blowup, checked by compiler after expansion
#: Raised 18.08.2026 following the author's budget (100 -> 10 000). It
#: guards against BLOATING via a macro, not against large programs: the
#: twofold margin over the author's budget is left intentionally, so the
#: refusal comes from the author's declared boundary, not from here.

#: Expansion of ONE series. The number is deliberately SEPARATE from
#: MAX_EXPANDED_OPS and smaller than it: 300 is the budget of the ENTIRE
#: program after expansion, and if one macro could take all of it, a
#: program building a tower would have no room left for the level, the
#: grid, and the types it must start from. 200 = 2/3 of the budget, so one
#: series always leaves 100 ops for the rest of the program. Measured
#: 28.07 (Eiffel tower, KIR shoulder): 118 beams by enumeration — fits in
#: one series with a 40% margin. The C# shoulder in the same run placed 343
#: beams in one program, and THAT DOES NOT FIT IN ONE series — deliberately:
#: 343 elements in one Revit transaction is a live figure that no one has
#: measured, and the bridge cuts execute at 200 s. Raising the ceiling
#: without a live measurement would mean guessing; if you need 343, that is
#: two series, and the refusal says so directly, instead of silently
#: stretching.
MAX_SERIES_OPS = 200
MAX_SERIES_COUNT = 200         # repeats; with items of one op it matches ↑

#: Named parameters in a track: enough for the full state of a station
#: (x, y, z + width, height, rotation, offset, radius).
MAX_TRACK_PARAMS = 8

#: Nodes in one track. 32 nodes = 31 breaks in the silhouette; the Eiffel
#: Tower has 3, a typical setback skyscraper has 2..5. The limit here is not
#: about memory but about meaning: a track with as many nodes as repeats is
#: the same enumeration in a different suit, and it saves not a single
#: round.
MAX_TRACK_NODES = 32

MACRO_OPS = ("stack", "grid_array", "series")

#: What a typical floor may contain. Originally walls and pipes only, which
#: made the macro unusable for the thing it is named after: a storey is a slab,
#: columns, beams, partitions, doors, windows and rooms, and `stack` refused
#: every one of them. Measured 2026-07-27 — a 60-storey tower spent its first
#: four rounds writing 69 `create_level` ops by hand because the one macro that
#: exists for exactly that could not carry the floor with them.
#:
#: The rule for membership is mechanical, not taste: the op must take `level`
#: (so the per-storey rewrite means something) and must not be a whole-network
#: op whose nodes carry their own elevations.
#:
#: 🔴 A BAN ON HOSTED OPS USED TO STAND HERE, AND IT WAS LIFTED 15.08.2026.
#: The earlier argument — «hosted op would point at storey 1 forever» —
#: described not a property of the door, but a GAP IN EXPANSION: it renamed
#: ids and did not rewrite `by:ref`. The gap is closed (`_rename_member_refs`
#: below), and the door and window now travel under the second membership
#: rule — `_STACKABLE_HOSTED`.
_STACKABLE = (
    "create_wall", "create_pipe", "create_column", "create_beam",
    "create_floor", "create_floor_by_contour", "create_room",
    "create_foundation", "create_duct", "create_cable_tray", "create_roof",
    # wave/mep-electrical: the trunking and both blanks take `level` and are
    # not network ops whose nodes carry their own elevations — that is, they
    # pass the same MECHANICAL membership rule as the pipe and the tray.
    # Flexible runs ARE NOT INCLUDED HERE: they do not have a pair of ends,
    # but a `path`, and the Z-transfer rule (`_Z_SHIFTED` below) addresses
    # exactly p0_mm/p1_mm; shifting a polyline per storey needs a different
    # transfer, which no one has measured.
    "create_conduit", "create_pipe_placeholder", "create_duct_placeholder",
)

#: SECOND MEMBERSHIP RULE: HOSTED OPS. The kind of list is **CLOSED, BUT
#: NOT COMPLETE**: only ops for which expansion has been MEASURED are
#: entered here, and the absence of a name means "not measured," not "won't
#: work."
#:
#: WHY A SECOND RULE, RATHER THAN AN EXTENSION OF THE FIRST. The first
#: requires that the op take `level` — the door and the window HAVE NO SUCH
#: FIELD AT ALL (`ops_authoring`), and this is not an omission of the
#: registry: **for a hosted element, the level is a property OF THE HOST.**
#: A door stands on whichever storey its wall stands on. So a per-storey
#: rewrite, which for a wall means "rewrite `level`," means for a door
#: "rewrite the REFERENCE TO THE HOST," and requiring `level` from it would
#: mean giving the door a second, independent source of storey — exactly the
#: kind of defect this whole package is written against.
#:
#: WHAT A TENANT MUST SATISFY (checked by a test, not by eye):
#:   1. CREATE effect — mutating ops (`set_param`, `delete`, `change_type`,
#:      `set_curtain_panel`) address SOMEONE ELSE'S element and have no
#:      storey of their own;
#:   2. a mandatory host selector that accepts `ref`;
#:   3. NO `level` of its own;
#:   4. and decisively: after expansion the host RESOLVES to a member of
#:      THE SAME storey — this is a measurement, not a property of the
#:      registry, and it is held by `test_stacked_storey`.
#:
#: WHY ONLY TWO NAMES ARE HERE. `create_opening`, `create_curtain_grid_line`,
#: `create_slab_edge`, `create_wall_sweep`, `create_area_reinforcement`,
#: `create_wall_foundation`, `create_face_wall`, `create_site_subregion` also
#: mechanically satisfy conditions 1-3. None of them is entered, and each has
#: its OWN reason, not a shared one:
#:   * `create_wall_foundation` — the foundation belongs to the BASE, not to
#:     each storey; per-storey replication would build N foundations;
#:   * `create_face_wall` — the host is a FACE OF THE FORM, not a member of
#:     the storey; the reference would leave the set and run into the
#:     refusal of condition 4;
#:   * `create_site_subregion` — the host is the terrain, and a site has no
#:     storeys;
#:   * `create_opening`, `create_curtain_grid_line`, `create_slab_edge`,
#:     `create_wall_sweep`, `create_area_reinforcement` — mechanically pass
#:     and are NOT MEASURED: not one live run of per-storey expansion exists
#:     for them, and entering them by symmetry would mean declaring proven
#:     what has not been tested. Enter them one at a time, each with its own
#:     measurement.
_STACKABLE_HOSTED: dict[str, str] = {
    "create_door": (
        "хозяин — стена этажа (`host`, target_w, принимает ref); уровень берёт "
        "у хозяина; живьём 38 построек, 0 обвинений"),
    "create_window": (
        "то же устройство, что у двери, и тот же хозяин-стена; живьём "
        "33 постройки, 0 обвинений"),
}


def _takes_level(op_name: str) -> bool:
    """Whether an op takes its own `level` — ASKED OF THE REGISTRY.

    Not a list: a second enumeration of names, obliged to match the
    registry, would drift from it on the very first new op. The registry is
    the authority; here there is only the question.
    """
    from kir import spec
    op_spec = spec.OPS.get(op_name)
    return bool(op_spec) and any(p.name == "level" for p in op_spec.params)


def _rename_member_refs(node: Any, renames: dict) -> Any:
    """Rewrite `{"by":"ref","value":X}` -> `renames[X]` for members of the set.

    🔴 THIS IS THE HALF THAT EXPANSION WAS MISSING. The expander renames
    member ids at every step (`{mid}_L{k}_{base}`), but left references
    between members untouched — that is, a second-storey door kept pointing
    at a wall that no longer existed after renaming, or at the first step's
    wall. Because of this, hosted ops were BANNED, and the ban read as a
    fact about the door, though it was a fact about expansion.

    A reference TO A FOREIGN NAME is left untouched deliberately: a member
    of the storey is entitled to reference a level or element outside the
    set, and substituting such a reference would mean deciding for the
    author. The dangerous case — a hosted op whose host is OUTSIDE the set —
    is caught by a separate refusal in the expander, not by silent
    substitution.

    NAMED DEBT: the same rewrite is performed by a private closure,
    `authoring._rename_refs`, inside the group emitter. Two copies of one
    rule are a named defect of this tree; they cannot be merged into one
    place from this wave (the emitter belongs to another), and so the debt
    is recorded here, not passed over in silence.
    """
    if isinstance(node, dict):
        out = {}
        for key, val in node.items():
            if (key == "value" and node.get("by") == "ref"
                    and str(val) in renames):
                out[key] = renames[str(val)]
            else:
                out[key] = _rename_member_refs(val, renames)
        return out
    if isinstance(node, list):
        return [_rename_member_refs(x, renames) for x in node]
    return node


def _host_ref_outside(op: dict, renames: dict) -> str | None:
    """The host's name, if a hosted op references OUTSIDE the set.

    Returns `None` when everything is in order: the host is either a member
    of the set (the reference has been rewritten), or is addressed other
    than by reference (element_id/name — a real element of the document,
    and it is legitimately the same one for every step).
    """
    host = op.get("host") or op.get("wall")
    if isinstance(host, dict) and host.get("by") == "ref":
        value = str(host.get("value"))
        if value not in renames:
            return value
    return None

#: Ops whose points carry an explicit Z: the macro keeps them storey-local and
#: makes them absolute on expansion. Ops that locate by `level` + 2D need no
#: shift — the rewritten level ref already places them.
_Z_SHIFTED = {
    "create_pipe": ("p0_mm", "p1_mm"),
    "create_beam": ("p0_mm", "p1_mm"),
    "create_duct": ("p0_mm", "p1_mm"),
    "create_cable_tray": ("p0_mm", "p1_mm"),
    "create_conduit": ("p0_mm", "p1_mm"),
    "create_pipe_placeholder": ("p0_mm", "p1_mm"),
    "create_duct_placeholder": ("p0_mm", "p1_mm"),
}


def _err(msg: str, op_id: str = None, **kw) -> KirRefusal:
    return KirRefusal([Diagnostic(code=MACRO_ERROR, op_id=op_id,
                                  message_ru=msg, **kw)])


def _num(x) -> bool:
    return is_finite_number(x)


def _macro_id(m: dict, default: str) -> str:
    if "id" not in m:
        return default
    value = m.get("id")
    if not isinstance(value, str) or not (1 <= len(value) <= 64):
        raise _err("id макроса — строка длиной 1..64", default, got=value)
    return value


def _derived_id(macro: str, parent: str, role: str, ordinal: int,
                member: str | None = None) -> str:
    """Retain every legal legacy child ID; bound only previously invalid ones.

    The structured identity excludes geometry and source-envelope position:
    editing parameters or appending/reordering other macros cannot rename an
    existing child. Hash collisions remain subject to the compiler's ordinary
    duplicate-ID gate; never uniquify by encounter order.
    """
    if macro == "stack" and role in ("level", "member"):
        legacy = f"{parent}_L{ordinal}" + (f"_{member}" if role == "member" else "")
    elif macro == "grid_array" and role in ("x", "y"):
        legacy = f"{parent}_{role.upper()}{ordinal}"
    elif macro == "series" and role == "member":
        legacy = f"{parent}_{ordinal}_{member}"
    else:
        raise ValueError("unsupported internal macro child role")
    if len(legacy) <= 64:
        return legacy
    identity = ["kir-macro-derived-id/1", macro, parent, role, ordinal, member]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _closed_fields(m: dict, allowed: set[str], mid: str) -> None:
    extra = set(m) - allowed
    if extra:
        raise _err(f"неизвестное поле макроса '{sorted(extra)[0]}'", mid,
                   field_name=sorted(extra)[0], got=m.get(sorted(extra)[0]))


#: Point-bearing fields a per-storey transform may move. Only the XY plane is
#: touched — Z belongs to the storey, and the level rewrite already owns it.
#:
#: 🔴 KEPT FOR OPS OUTSIDE THE REGISTRY, AND AS A SAFETY NET (F-139,
#: 29.08.2026). The list of four names USED TO BE the sole carrier of "what
#: to transfer," and it did not include `create_floor.outline`: a storey
#: came out with walls on a 500 contour and a slab on a 1000 contour, WITH
#: NOT A SINGLE REFUSAL — the compiler checks the shape of each op
#: separately, and "consistency of walls with the slab" is not a law
#: anywhere. The fields are now ASKED OF THE REGISTRY (`_geometry_plan`), by
#: the same argument that `_takes_level` already lives by here.
_XY_FIELDS = ("p0_mm", "p1_mm", "xy", "top_xy")

#: 🔴 THE DECISION FOR EACH PARAMETER KIND IS CLOSED AND COMPLETE PER
#: `spec.PARAM_KINDS`.
#:
#: Adding `"outline"` to `_XY_FIELDS` would be the WRONG shape, and this is
#: the main point: a list of names forever chases the registry, the next
#: carrier of geometry will be forgotten the same way, and the miss will
#: again turn out invisible. But deriving "does this kind carry plan
#: geometry" from the registry is ALSO IMPOSSIBLE — it is a semantic
#: property.
#:
#: So here there is not a list of NAMES but a decision per KIND, and its
#: completeness is guarded by a number:
#: `test_a_storey_transform_moves_every_carrier_of_plan_geometry` requires
#: that EVERY kind from `spec.PARAM_KINDS` stand in this table. A new kind
#: in the registry reddens the set and forces someone to COME AND DECIDE —
#: the same device that closes the sandbox's list of names
#: (`test_course.NAMES`).
#:
#: `REFUSAL` where the kind CARRIES GEOMETRY and there is nothing to
#: transfer it with: inventing a transform for a mesh, a surface, or
#: boolean primitives without a witness would mean silently building the
#: wrong building — exactly the defect this patch is against. A named
#: refusal is strictly better.
_KIND_POINT = "точка"          # [x, y] or [x, y, z]
_KIND_RING = "кольцо"          # a list of points
_KIND_RINGS = "кольца"         # a list of lists of points
_KIND_REGION = "область"       # {outer, holes} — its own branch below
_KIND_DIR = "направление"      # rotates, does not shift and does not narrow
_KIND_SPECIAL = "особый"       # handled by a separate branch of this same function
_KIND_FLAT = "не геометрия"    # carries no coordinates at all
_KIND_REFUSE = "отказ"         # carries geometry, nothing to transfer it with

_TRANSFORM_BY_KIND: dict[str, str] = {
    # ── is transferred ──────────────────────────────────────────────────────
    "pt_xy": _KIND_POINT, "pt_xyz": _KIND_POINT,
    "pts": _KIND_RING, "pts_xyz": _KIND_RING,
    "path": _KIND_RING, "path3": _KIND_RING,
    "pts_list": _KIND_RINGS,
    "region": _KIND_REGION,
    "dir_xyz": _KIND_DIR,
    # ── handled by its own branch ───────────────────────────────────────────
    "arc": _KIND_SPECIAL,
    # ── carries geometry, NOTHING to transfer it with: named refusal ───────
    "mesh": _KIND_REFUSE, "surface": _KIND_REFUSE, "solid_parts": _KIND_REFUSE,
    "spiral": _KIND_REFUSE, "plane": _KIND_REFUSE, "placements": _KIND_REFUSE,
    "graph_nodes": _KIND_REFUSE, "graph_segments": _KIND_REFUSE,
    "slopes": _KIND_REFUSE,
    # ── carries no coordinates ──────────────────────────────────────────────
    "bool": _KIND_FLAT, "deg": _KIND_FLAT, "enum": _KIND_FLAT,
    "fields": _KIND_FLAT, "filters": _KIND_FLAT, "int": _KIND_FLAT,
    # Список имён из закрытого словаря: ни координат, ни ссылок — макросу
    # преобразовывать нечего, как и у `fields` рядом.
    "enum_list": _KIND_FLAT,
    # `identity` — ЧИТАННАЯ ЛИЧНОСТЬ, а не координата. Перенос этажа обязан
    # оставить её КАК ЕСТЬ: она называет элемент, который автор прочитал, и
    # сдвинутая копия этажа адресует ДРУГИЕ элементы. Подставлять сюда перенос
    # значило бы перенести и утверждение «я это читал» — то есть соврать о том,
    # чего автор не видел.
    "identity": _KIND_FLAT,
    "kind_enum": _KIND_FLAT, "member_ops": _KIND_FLAT, "mm": _KIND_FLAT,
    "num": _KIND_FLAT, "refs_w": _KIND_FLAT, "sel": _KIND_FLAT,
    "sel_list": _KIND_FLAT, "str": _KIND_FLAT, "str_long": _KIND_FLAT,
    "target": _KIND_FLAT, "target_w": _KIND_FLAT, "value": _KIND_FLAT,
    "wall_layers": _KIND_FLAT,
    # `pt_view2d` — coordinates of the SHEET, not of the model
    # (KIR_DOC_SPEC): narrowing the plan does not touch them, and moving
    # them would mean shifting the layout.
    "pt_view2d": _KIND_FLAT,
}


def _kind_of(op_name: str, field: str) -> str:
    """The parameter kind per the registry — for the refusal TEXT, so it names the subject."""
    from kir import spec

    op_spec = spec.OPS.get(op_name)
    for p in (op_spec.params if op_spec else ()):
        if p.name == field:
            return p.kind
    return "?"


def _geometry_plan(op_name: str) -> tuple[tuple[str, str], ...]:
    """`((field name, how to transfer), ...)` — FROM THE REGISTRY, not from a list of names."""
    # The import is lazy: `spec` pulls in half the tree, and `macros` is
    # also called from places where the registry is not yet needed. The same
    # device as `_status_of` uses with `json`.
    from kir import spec

    op_spec = spec.OPS.get(op_name)
    if op_spec is None:
        return ()
    return tuple((p.name, _TRANSFORM_BY_KIND.get(p.kind, _KIND_REFUSE))
                 for p in op_spec.params)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _xform_point(pt, pivot, sx, sy, ang, dx, dy):
    """Scale about the pivot, then rotate about it, then translate. A 3-component
    point keeps its Z: the storey owns elevation, the transform owns the plan."""
    x, y = float(pt[0]), float(pt[1])
    px, py = pivot
    x, y = (x - px) * sx, (y - py) * sy
    c, s = math.cos(ang), math.sin(ang)
    x, y = x * c - y * s, x * s + y * c
    out = [px + x + dx, py + y + dy]
    return out + [pt[2]] if len(pt) == 3 else out


def _validate_transform(t: Any, mid: str) -> dict:
    """The per-storey transform, checked into a plain dict of end-state values.

    Bounded expressiveness (SPEC 12.3) says no loops in the language — but a
    macro that can only repeat a storey BYTE-IDENTICALLY cannot describe any
    building whose plan changes with height, which is every interesting tower:
    a taper, a twist, a setback. `stack` was that macro, so the only way to get
    scale was `create_group`, which also repeats identically. Measured
    2026-07-27: the model could produce a 179-element tower with a silhouette,
    or 12 000 identical columns, and nothing in the language let it have both.
    Interpolation is still not a loop: the k-th storey is a pure function of k.
    """
    if t is None:
        return {}
    if not isinstance(t, dict):
        raise _err("stack.transform — объект", mid, got=t)
    allowed = {"scale_xy_top", "twist_deg_total", "offset_mm_top", "pivot_mm"}
    extra = set(t) - allowed
    if extra:
        raise _err(f"stack.transform: неизвестное поле '{sorted(extra)[0]}' "
                   f"(допустимы {sorted(allowed)})", mid, got=sorted(extra)[0])
    out: dict = {}
    scale = t.get("scale_xy_top", [1.0, 1.0])
    if (not isinstance(scale, list) or len(scale) != 2
            or not all(_num(v) and 0.05 <= v <= 20 for v in scale)):
        raise _err("stack.transform.scale_xy_top — [sx, sy], каждый 0.05..20 "
                   "(во сколько раз план верхнего этажа отличается от нижнего)",
                   mid, got=scale)
    out["scale"] = [float(scale[0]), float(scale[1])]
    twist = t.get("twist_deg_total", 0)
    if not _num(twist) or not (-3600 <= twist <= 3600):
        raise _err("stack.transform.twist_deg_total — число -3600..3600 "
                   "(суммарный поворот от низа к верху)", mid, got=twist)
    out["twist"] = float(twist)
    off = t.get("offset_mm_top", [0, 0])
    if (not isinstance(off, list) or len(off) != 2
            or not all(_num(v) and abs(v) <= 1_000_000 for v in off)):
        raise _err("stack.transform.offset_mm_top — [dx, dy] в мм, |v| <= 1e6",
                   mid, got=off)
    out["offset"] = [float(off[0]), float(off[1])]
    piv = t.get("pivot_mm", [0, 0])
    if (not isinstance(piv, list) or len(piv) != 2
            or not all(_num(v) and abs(v) <= 1_000_000 for v in piv)):
        raise _err("stack.transform.pivot_mm — [x, y] в мм, центр сужения и "
                   "поворота", mid, got=piv)
    out["pivot"] = [float(piv[0]), float(piv[1])]
    return out


def _apply_transform(op: dict, tr: dict, t: float, mid: str) -> None:
    """Move op's plan geometry to storey fraction `t` (0 at the base, 1 at the
    top). Mutates in place — the caller already deep-copied."""
    if not tr:
        return
    sx = _lerp(1.0, tr["scale"][0], t)
    sy = _lerp(1.0, tr["scale"][1], t)
    ang = math.radians(_lerp(0.0, tr["twist"], t))
    dx = _lerp(0.0, tr["offset"][0], t)
    dy = _lerp(0.0, tr["offset"][1], t)
    piv = tr["pivot"]
    c, s = math.cos(ang), math.sin(ang)

    def move(pt):
        return _xform_point(pt, piv, sx, sy, ang, dx, dy)

    def _is_point(v) -> bool:
        return (isinstance(v, list) and 2 <= len(v) <= 3
                and all(_num(x) for x in v))

    def _move_ring(ring, field):
        out = []
        for point in ring:
            if relate.is_address(point):
                raise _err(
                    f"stack.transform: адрес от осей в поле `{field}` не "
                    f"переносится сужением и поворотом — оси на верхнем этаже "
                    f"те же самые, и фигура получилась бы неотличимой от "
                    f"нижней. Задай эти точки литералами [x, y]",
                    mid, field_name=field, got=point)
            out.append(move(point) if _is_point(point) else point)
        return out

    def _move_region_shape(shape: Any, field: str) -> None:
        """Transfer the whole shape, without leaving nested geometry behind.

        Historically `stack.transform` knew only `contour.outer.points_mm`:
        the outer ring moved, while the holes and the spline's interpolation
        points stayed in the previous coordinate system. The boundary of the
        representation stays the same (`poly`), but every carrier of
        geometry inside it is now traversed.

        A circular arc survives only a similarity transform. Under
        different scales along the axes its image is an ellipse, which no
        form of contour arc expresses. Keeping the previous bulge/radius
        would mean silently building a different curve, so here there is a
        refusal, not an approximation.
        """
        if not isinstance(shape, dict):
            return                     # the compiler itself will name the wrong shape
        if shape.get("shape") != "poly":
            raise _err(
                f"stack.transform + {field}: контур должен быть shape='poly' "
                "— rect и l не переносят сужение и поворот без потери "
                "смысла; перечисли углы точками",
                mid, field_name=field, got=shape.get("shape"))

        pts = shape.get("points_mm")
        if isinstance(pts, list):
            shape["points_mm"] = _move_ring(pts, f"{field}.points_mm")

        arcs = shape.get("arcs")
        if isinstance(arcs, list) and arcs:
            if abs(sx - sy) > 1e-9:
                raise _err(
                    f"stack.transform + {field}.arcs: НЕРАВНОМЕРНОЕ сужение "
                    "превращает круговую дугу в эллипс, а contour arc/bulge "
                    "эллипс не выражает. Сделай scale_xy_top равным по осям "
                    "либо замени дугу сплайном/ломаной",
                    mid, field_name=f"{field}.arcs", got=[sx, sy])
            # `bulge` and `dir` are dimensionless. Under similarity only the radius changes.
            for arc in arcs:
                if isinstance(arc, dict) and _num(arc.get("radius_mm")):
                    arc["radius_mm"] = float(arc["radius_mm"]) * sx

        splines = shape.get("splines")
        if isinstance(splines, list):
            for si, spline in enumerate(splines):
                if not isinstance(spline, dict):
                    continue
                via = spline.get("via_mm")
                if isinstance(via, list):
                    spline["via_mm"] = _move_ring(
                        via, f"{field}.splines[{si}].via_mm")

    def _move_region(region: Any, field: str) -> None:
        """Transfer one region value: the outer ring and every hole together."""
        if not isinstance(region, dict):
            return                     # the compiler itself will name the wrong region
        outer = region.get("outer")
        if isinstance(outer, dict):
            _move_region_shape(outer, f"{field}.outer")
        holes = region.get("holes")
        if isinstance(holes, list):
            for hi, hole in enumerate(holes):
                if isinstance(hole, dict):
                    _move_region_shape(hole, f"{field}.holes[{hi}]")

    # 🔴 GEOMETRY FIELDS ARE TAKEN FROM THE REGISTRY (F-139). Before
    # 29.08.2026 they were known to a hand-written `_XY_FIELDS` of four
    # names, and `create_floor.outline` was not among them: `stack` with
    # `scale_xy_top` narrowed the WALLS and did not touch the SLAB — the top
    # storey came out with walls on a 500 contour and a slab on a 1000
    # contour, and not one law caught it. A second carrier of the same
    # miss: contour holes — `outer` was transferred, `holes` was not
    # mentioned at all.
    op_name = op["op"] if isinstance(op.get("op"), str) else ""
    plan = _geometry_plan(op_name)
    for field, how in plan:
        value = op.get(field)
        if value is None or how in (_KIND_FLAT, _KIND_SPECIAL):
            continue
        if how == _KIND_REGION:
            _move_region(value, field)
            continue
        if how == _KIND_REFUSE:
            raise _err(
                f"stack.transform не умеет переносить поле `{field}` (род "
                f"`{_kind_of(op['op'], field)}`): оно НЕСЁТ геометрию, а "
                f"сузить и повернуть её нечем. Молча оставить её на месте "
                f"значило бы построить этаж, у которого одна часть переехала, "
                f"а другая нет, — и снаружи это неотличимо от верного. "
                f"Следующий ход: убери `transform` либо вынеси этот оп из "
                f"типового этажа",
                mid, field_name=field, got=field)
        if how == _KIND_POINT and _is_point(value):
            op[field] = move(value)
        elif how == _KIND_POINT and relate.is_address(value):
            raise _err(
                "stack.transform: адрес от осей не переносится сужением и "
                "поворотом — ось от преобразования не переезжает, а точка "
                "обязана остаться НА НЕЙ. Молча пропустить адрес значило бы "
                "поставить все этажи в одну и ту же точку сетки. Либо убери "
                "transform, либо задай эту точку литералом [x, y]",
                mid, field_name=field, got=value)
        elif how == _KIND_RING and isinstance(value, list):
            op[field] = _move_ring(value, field)
        elif how == _KIND_RINGS and isinstance(value, list):
            op[field] = [_move_ring(r, field) if isinstance(r, list) else r
                         for r in value]
        elif how == _KIND_DIR and _is_point(value):
            # The direction is ROTATED and not shifted: the same law as
            # for the arc's axes twenty lines below.
            op[field] = [value[0] * c - value[1] * s,
                         value[0] * s + value[1] * c] + list(value[2:])

    # A SAFETY NET FOR OPS OUTSIDE THE REGISTRY, AND ONLY FOR THEM. The
    # registry knows kinds only for its own ops; an op that is not in it
    # would pass by the branch above.
    # 🔴 `if not plan` is mandatory: without it a point would be
    # transferred TWICE — caught by a run (the wall narrowed 4x instead of
    # 2x).
    for key in (_XY_FIELDS if not plan else ()):
        v = op.get(key)
        if isinstance(v, list) and 2 <= len(v) <= 3 and all(_num(x) for x in v):
            op[key] = move(v)
        elif relate.is_address(v):
            raise _err(
                "stack.transform: адрес от осей не переносится сужением и "
                "поворотом — ось от преобразования не переезжает, а точка "
                "обязана остаться НА НЕЙ. Молча пропустить адрес значило бы "
                "поставить все этажи в одну и ту же точку сетки. Либо убери "
                "transform, либо задай эту точку литералом [x, y]",
                mid, field_name=key, got=v)

    # A curved wall is how a facade reads smooth inside the op budget — six arcs
    # per storey beat twenty-four chords. The arc must ride the transform with
    # its endpoints or the compiler's endpoint cross-check refuses the storey.
    arc = op.get("arc")
    if isinstance(arc, dict) and arc.get("curve_type") == "Arc":
        if abs(sx - sy) > 1e-9:
            raise _err(
                "stack.transform: дуговая стена не переносит НЕРАВНОМЕРНОЕ "
                "сужение — дуга стала бы эллипсом, а Revit Arc его не "
                "выражает. Сделай scale_xy_top равным по осям, либо замени "
                "дугу отрезками (у ломаной такого ограничения нет)",
                mid, field_name="arc", got=[sx, sy])
        centre = arc.get("center_mm")
        if isinstance(centre, list) and len(centre) == 3 \
                and all(_num(x) for x in centre):
            arc["center_mm"] = move(centre)
        if _num(arc.get("radius_mm")):
            arc["radius_mm"] = float(arc["radius_mm"]) * sx
        # Axes are DIRECTIONS: they rotate, and they neither scale nor shift.
        for key in ("x_axis", "y_axis"):
            v = arc.get(key)
            if isinstance(v, list) and len(v) == 3 and all(_num(x) for x in v):
                arc[key] = [v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]]
def _expand_stack(m: dict) -> list[dict]:
    mid = _macro_id(m, "stack")
    _closed_fields(m, STACK_FIELDS, mid)
    n = m.get("levels")
    if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= MAX_STACK_LEVELS):
        # field_name/expected (25.08.2026, mission instrument measurement):
        # previously the pretext was text WITHOUT an address and WITHOUT a
        # form — "stack.levels is an integer 1..40" did not resolve into any
        # slot (the macro is not an op, there is no ParamSpec), and "40" in
        # the text was not read by the instrument as the boundary of a
        # value. Now field_name is a real, named slot of the macro schema
        # (STACK_FIELDS), and expected names BOTH the number AND THE NAME of
        # the ceiling constant — a number by itself rots faster than a name
        # (see MAX_STACK_LEVELS).
        raise _err(f"stack.levels={n} превышает потолок MAX_STACK_LEVELS="
                   f"{MAX_STACK_LEVELS} (целое 1..{MAX_STACK_LEVELS})", mid,
                   field_name="levels",
                   expected=f"1..{MAX_STACK_LEVELS} (константа MAX_STACK_LEVELS)",
                   got=n)
    h = m.get("h_mm", 3000)
    if not _num(h) or not (1000 <= h <= 10000):
        raise _err("stack.h_mm — число 1000..10000 мм", mid, got=h)
    e0 = m.get("base_elev_mm", 0)
    if not _num(e0):
        raise _err("stack.base_elev_mm — число (мм)", mid, got=e0)
    prefix = m.get("name_prefix", "Level")
    if not isinstance(prefix, str) or len(prefix) > 32:
        raise _err("stack.name_prefix — строка <=32", mid, got=prefix)
    floor = m.get("floor")
    if not isinstance(floor, list) or not floor:
        raise _err("stack.floor — непустой список опов", mid)
    expanded_count = n * (1 + len(floor))
    if expanded_count > MAX_EXPANDED_OPS:
        raise _err(f"stack развернётся в {expanded_count} опов — предел "
                   f"{MAX_EXPANDED_OPS}", mid, got=expanded_count)
    for f in floor:
        if not isinstance(f, dict):
            raise _err("stack.floor: op должен быть объектом", mid)
        if f.get("op") not in _STACKABLE and f.get("op") not in _STACKABLE_HOSTED:
            raise _err(f"stack.floor: '{f.get('op')}' не тиражируется по этажам "
                       f"(допустимы {list(_STACKABLE)}; хостящиеся — "
                       f"{sorted(_STACKABLE_HOSTED)})", mid, got=f.get("op"))
        if "level" in f:
            # `_err(msg, op_id=None, **kw)`: `mid` already occupies
            # `op_id` positionally, and a second `op_id=None` broke the call
            # with a TypeError. The refusal existed, but was UNREACHABLE: an
            # author who set level inside stack got «KIR-P000 внутренняя
            # ошибка компилятора: TypeError» instead of the rule they had
            # violated. Found 04.08.2026 by the very first targeted
            # stack test.
            raise _err("stack.floor: у опов внутри stack не задаётся level — "
                       "его назначает экспансия", mid, field_name="level")
        if "id" in f and (not isinstance(f.get("id"), str)
                           or not (1 <= len(f["id"]) <= 64)):
            raise _err("stack.floor[].id — строка длиной 1..64", mid,
                       got=f.get("id"))
    tr = _validate_transform(m.get("transform"), mid)
    out: list[dict] = []
    for k in range(1, n + 1):
        out.append({"op": "create_level", "id": _derived_id("stack", mid, "level", k),
                    "elev_mm": e0 + (k - 1) * h, "name": f"{prefix} {k}"})
    for k in range(1, n + 1):
        frac = (k - 1) / (n - 1) if n > 1 else 0.0
        # THE RENAME MAP FOR THIS STOREY, BUILT BEFORE THE LOOP BODY: a
        # member's reference to a neighbor must land on the neighbor OF THE
        # SAME storey, including when the neighbor is declared LOWER in the
        # list. Building the map on the fly would mean rewriting references
        # only backward, and forward — silently leaving them on the first
        # storey, exactly the defect the map is introduced to prevent.
        renames = {(f.get("id") or f["op"]): _derived_id("stack", mid, "member", k, f.get("id") or f["op"])
                   for f in floor}
        for f in floor:
            c = copy.deepcopy(f)
            base = c.get("id") or c["op"]
            c["id"] = renames[base]
            _apply_transform(c, tr, frac, mid)
            # per-storey Z shift for ops whose points carry an explicit Z:
            # points stay storey-local in the macro, absolute after expansion
            for key in _Z_SHIFTED.get(c["op"], ()):
                if isinstance(c.get(key), list) and len(c[key]) == 3 \
                        and all(_num(v) for v in c[key]):
                    c[key] = [c[key][0], c[key][1],
                              c[key][2] + e0 + (k - 1) * h]
                elif relate.is_address(c.get(key)) and _num(c[key].get("z_mm")):
                    # The address CARRIES its own elevation explicitly
                    # (`z_mm` is mandatory in pt_xyz — the grid has no Z),
                    # and it must be transferred across storeys in exactly
                    # the same way as a literal. XY is not touched here: the
                    # grid is the same on every storey, and that is exactly
                    # what is expected of the address.
                    c[key] = dict(c[key])
                    c[key]["z_mm"] = float(c[key]["z_mm"]) + e0 + (k - 1) * h
            # A HOST OUTSIDE THE SET IS A REFUSAL, NOT A QUIET REFERENCE
            # TO THE FIRST STOREY. Checked BEFORE the rewrite: after it,
            # "inside" and "outside" can no longer be told apart, and the
            # distinction is what decides everything here.
            stray = _host_ref_outside(c, renames)
            if stray is not None:
                raise _err(
                    f"stack.floor: '{c['op']}' ссылается на хозяина "
                    f"'{stray}', которого нет среди членов этажа. Хостящийся "
                    f"оп тиражируется поэтажно ТОЛЬКО вместе со своим "
                    f"хозяином: иначе на каждом этаже он повис бы на одном и "
                    f"том же элементе первого. СЛЕДУЮЩИЙ ХОД: внеси хозяина в "
                    f"floor — либо адресуй его element_id, если это настоящий "
                    f"элемент документа, один для всех этажей",
                    mid, field_name="host", got=stray)
            # Rewrite only the template's local references before inserting
            # the synthetic level. A legal member may itself be named s_L1
            # (or the bounded level hash); it must not capture that level ref.
            c = _rename_member_refs(c, renames)
            # Hosted doors/windows inherit their host's level; do not invent
            # a second independent level slot for them.
            if _takes_level(c["op"]):
                c["level"] = {"by": "ref", "value": _derived_id("stack", mid, "level", k)}
            out.append(c)
    return out


def _expand_grid_array(m: dict) -> list[dict]:
    mid = _macro_id(m, "grid_array")
    _closed_fields(m, GRID_ARRAY_FIELDS, mid)
    nx, ny = m.get("nx", 0), m.get("ny", 0)
    for label, v in (("nx", nx), ("ny", ny)):
        if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= MAX_GRID_AXIS):
            raise _err(f"grid_array.{label} — целое 0..{MAX_GRID_AXIS}", mid, got=v)
    if nx + ny == 0:
        raise _err("grid_array: nx+ny должно быть > 0", mid)
    dx, dy = m.get("dx_mm", 6000), m.get("dy_mm", 6000)
    for label, v in (("dx_mm", dx), ("dy_mm", dy)):
        if not _num(v) or not (GRID_SPACING_MIN_MM <= v <= GRID_SPACING_MAX_MM):
            # The refusal text is assembled from THE SAME constants:
            # otherwise the number in the message would become a third
            # carrier and drift apart later (F-117).
            raise _err(f"grid_array.{label} — число "
                       f"{GRID_SPACING_MIN_MM:.0f}..{GRID_SPACING_MAX_MM:.0f} мм",
                       mid, got=v)
    origin = m.get("origin_mm", [0, 0])
    if not (isinstance(origin, list) and len(origin) == 2 and all(_num(v) for v in origin)):
        raise _err("grid_array.origin_mm — [x,y] мм", mid, got=origin)
    margin = m.get("margin_mm", 1000)
    if not _num(margin) or not (0 <= margin <= 10000):
        raise _err("grid_array.margin_mm — число 0..10000 мм", mid, got=margin)
    px, py = m.get("prefix_x", ""), m.get("prefix_y", "А")
    for label, v in (("prefix_x", px), ("prefix_y", py)):
        if not isinstance(v, str) or len(v) > 8:
            raise _err(f"grid_array.{label} — строка <=8", mid, got=v)
    ox, oy = origin
    y_span = (ny - 1) * dy if ny > 1 else 0
    x_span = (nx - 1) * dx if nx > 1 else 0
    out = []
    for i in range(nx):    # vertical grids, varying X
        x = ox + i * dx
        out.append({"op": "create_grid", "id": _derived_id("grid_array", mid, "x", i + 1),
                    "p0_mm": [x, oy - margin], "p1_mm": [x, oy + y_span + margin],
                    "name": f"{px}{i + 1}"})
    for j in range(ny):    # horizontal grids, varying Y
        y = oy + j * dy
        out.append({"op": "create_grid", "id": _derived_id("grid_array", mid, "y", j + 1),
                    "p0_mm": [ox - margin, y], "p1_mm": [ox + x_span + margin, y],
                    "name": f"{py}{j + 1}"})
    return out


#: What can be replicated in a series. The membership rule is mechanical,
#: like _STACKABLE's, but the boundary runs through a different place:
#: series does NOT create levels and does NOT rewrite `level` — so the
#: requirement "the op accepts level" is not needed here, and create_grid,
#: which is refused in stack as a non-per-storey object, legitimately
#: belongs here (a variable grid step is exactly what the macro is for).
#: 🔴 THE RESTRICTION ON HOSTED OPS WAS LIFTED 15.08.2026, BY MEASUREMENT,
#: NOT BY SYMMETRY WITH stack. The earlier text said: «a hosted op would
#: forever point at bay 0» — and that was true right up until expansion
#: learned to rewrite references (`_rename_member_refs`). Measured after
#: the fix, a row of three bays "wall + door": `bay_0_d -> bay_0_w`,
#: `bay_1_d -> bay_1_w`, `bay_2_d -> bay_2_w`, **zero mismatches of bay 0**.
#: Exactly the same two names are admitted as in stack, and precisely
#: because the measurement covered them.
_SERIES_ABLE = _STACKABLE + ("create_grid",) + tuple(_STACKABLE_HOSTED)

#: Grammar of a track-parameter reference. CLOSED, four forms, no composition:
#:     $name   -$name   $name@next   -$name@next
#: The minus sign is the only concession, and it is not arithmetic: for a
#: symmetric building the mirror side is THE SAME NUMBER, read from the
#: other side of the axis, and without the sign the model would have to
#: keep a second, twin track, where a typo makes the tower imperceptibly
#: skewed. There is no composition and there will be none: «-$a + $b» does
#: not parse, there are no precedences, there is no evaluator — the
#: resolver is a table substitution over four forms. The moment a binary
#: operator appears here, 12.3 breaks.
_REF_RE = re.compile(r"^(-?)\$([A-Za-z_][A-Za-z0-9_]{0,31})(@next)?$")


def _parse_ref(s: str):
    """-> (name, negate, use_next) or None, if the string is not a reference."""
    m = _REF_RE.match(s)
    return (m.group(2), m.group(1) == "-", m.group(3) is not None) if m else None


def _scan_refs(node: Any, found: dict, mid: str) -> None:
    """Collect {name: needs_@next} from the template.

    A string that opens with '$' or '-$' and does NOT parse is a typo, not a
    literal: refused here. Otherwise '$hwd' would ride as text into a
    numeric field, and the model would get a compiler refusal about the
    value's type — truthful, but not about the mistake it actually made."""
    if isinstance(node, dict):
        for v in node.values():
            _scan_refs(v, found, mid)
    elif isinstance(node, list):
        for v in node:
            _scan_refs(v, found, mid)
    elif isinstance(node, str) and (node.startswith("$") or node.startswith("-$")):
        ref = _parse_ref(node)
        if ref is None:
            raise _err(f"series.items: '{node}' похоже на ссылку на параметр "
                       f"трека, но не разбирается. Допустимы ровно четыре формы: "
                       f"$имя, -$имя, $имя@next, -$имя@next", mid, got=node)
        name, _neg, nxt = ref
        found[name] = found.get(name, False) or nxt


def _substitute(node: Any, at_k: dict, at_next: dict) -> Any:
    """Return a copy of the template where every reference is replaced by a
    number. References are already validated in _scan_refs, names in
    _expand_series."""
    if isinstance(node, dict):
        return {k: _substitute(v, at_k, at_next) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, at_k, at_next) for v in node]
    if isinstance(node, str) and (node.startswith("$") or node.startswith("-$")):
        name, neg, nxt = _parse_ref(node)
        v = (at_next if nxt else at_k)[name]
        return -v if neg else v
    return node


def _tidy(v: float):
    """Round to 6 digits + fall back to int, if the value is whole.

    Rounding: interpolation gives 46052.63157894737, and the flat IR is
    read by eyes and diffed against goldens. 1e-6 mm is a nanometer, below
    any tolerance in the system, and round is deterministic (same input →
    same bit).

    Falling back to int is not cosmetic: without it every whole coordinate
    rides into the program as "8000.0", and on a 160-beam tower that is
    ~1.9 KB of pure ".0". The expanded IR is what a human reads and what
    the byte budget bumps against."""
    r = round(v, 6)
    return int(r) if r == int(r) else r


def _track_at(nodes: list, x: float) -> float:
    """Value of the piecewise-linear track at point x. Coverage is already
    checked, so x is always inside [first node, last node] — the branches
    at the ends stand as a belt over the braces and are normally
    unreachable."""
    if x <= nodes[0][0]:
        return _tidy(nodes[0][1])
    for (x0, v0), (x1, v1) in zip(nodes, nodes[1:]):
        if x <= x1:
            return _tidy(v0 + (v1 - v0) * (x - x0) / (x1 - x0))
    return _tidy(nodes[-1][1])


def _validate_track(m: dict, mid: str) -> dict:
    """track -> {name: [(index, value), ...]}, nodes strictly increasing."""
    track = m.get("track")
    if not isinstance(track, dict) or not track:
        raise _err("series.track — непустой объект {имя: [[индекс, значение], "
                   "...]}", mid, got=track)
    if len(track) > MAX_TRACK_PARAMS:
        raise _err(f"series.track: параметров {len(track)} — предел "
                   f"{MAX_TRACK_PARAMS}", mid, got=len(track))
    parsed: dict[str, list] = {}
    for name, nodes in track.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", name):
            raise _err(f"series.track: имя параметра '{name}' — латиница/цифры/"
                       f"подчёркивание, 1..32, не с цифры", mid, got=name)
        if not isinstance(nodes, list) or len(nodes) < 2:
            raise _err(f"series.track['{name}'] — минимум ДВА узла: одному узлу "
                       f"нечего интерполировать, это константа, и её место "
                       f"прямо в шаблоне числом", mid, field_name=name, got=nodes)
        if len(nodes) > MAX_TRACK_NODES:
            raise _err(f"series.track['{name}']: узлов {len(nodes)} — предел "
                       f"{MAX_TRACK_NODES}", mid, field_name=name, got=len(nodes))
        out = []
        for node in nodes:
            if not (isinstance(node, list) and len(node) == 2):
                raise _err(f"series.track['{name}']: узел — пара [индекс, "
                           f"значение]", mid, field_name=name, got=node)
            idx, val = node
            if not _num(idx) or not (0 <= idx <= 100000):
                raise _err(f"series.track['{name}']: индекс узла — конечное "
                           f"число 0..100000", mid, field_name=name, got=idx)
            if not _num(val) or abs(val) > 1e9:
                raise _err(f"series.track['{name}']: значение узла — КОНЕЧНОЕ "
                           f"число, |v| <= 1e9", mid, field_name=name, got=val)
            if out and float(idx) <= out[-1][0]:
                raise _err(f"series.track['{name}']: индексы узлов строго по "
                           f"возрастанию (узел {idx} после {out[-1][0]}); равные "
                           f"или убывающие индексы делают значение в точке "
                           f"неоднозначным", mid, field_name=name, got=idx)
            out.append((float(idx), float(val)))
        parsed[name] = out
    return parsed


def _expand_series(m: dict) -> list[dict]:
    """Repeat N times with interpolation of named parameters by index.

    WHY. stack repeats a storey, grid_array lays out a grid — both repeat
    THE SAME THING (stack.transform can do a linear taper, but only one for
    the whole tower, from bottom to top). Measured 28.07 on the Eiffel
    Tower: the silhouette is piecewise-linear, three breaks, and the best
    possible SINGLE linear taper misses by 20.62 m (69%) at the elevation
    of the first platform. Expressing this in KIR was possible only by
    enumeration: 118 beams with literal coordinates, 7 rounds, ~4 minutes
    of typing coordinates — while 85% of a turn's time is spent on the
    model's deliberation. The C# shoulder expressed the same silhouette
    with a three-line function. series closes exactly this gap: one round
    carries more meaning across, not more bytes.

    TRACK SHAPE. {name: [[index, value], ...]} — nodes of "index → value",
    with LINEAR interpolation between nodes. Why exactly this shape, and
    not a spline or a formula: a piecewise-linear track is the simplest
    thing that covers all three live cases with one mechanism (taper =
    decreasing half-width, slope = rising elevation, variable step =
    uneven coordinate), while remaining DATA. A spline would require a
    solver, a formula an evaluator; either would drag into the language
    what 12.3 keeps outside.

    WHAT IS OUTSIDE THE RANGE OF NODES. Nothing: the track MUST cover every
    index at which it will be read, or else refusal. Extrapolation is
    forbidden (past the nodes the line runs into nonsense faster the
    further it goes), clamping to the outermost node is also a refusal,
    not a behavior: a track with nodes up to 10 at count=40 would give 30
    identical repeats, and the model would not notice. There is no silent
    correction here, by the same rule that there is none anywhere in the
    compiler.

    HOW MANY PARAMETERS. Up to MAX_TRACK_PARAMS (8) names, up to
    MAX_TRACK_NODES (32) nodes in each. A declared but never-used
    parameter is a refusal: it is either a typo on the other side, or dead
    code in a program that no one will later edit.

    EXPANSION LIMIT. MAX_SERIES_OPS (200) = count x len(items), a number
    separate from the program-wide MAX_EXPANDED_OPS (300) — justified at
    the constant.

    THE REVERSE PATH IS ONE-WAY, and this must be said directly. Decompiling
    someone else's model will not see the macro and cannot see it: Revit
    has no "macros," it has 160 separate beams, and after expansion the IR
    also has 160. No decompile will return a series from them — it will
    return an enumeration, byte-for-byte the very thing the macro was
    meant to replace. So series lives ONLY on the "model → building model"
    path, the roundtrip does not close over it, and it cannot be used to
    measure decompile coverage. Recognizing regularity during
    decompilation (seeing a track in 160 beams) is separate future work,
    honestly NOT done here: it is a search for structure in geometry, not
    the inversion of a function, and it has its own cost of error.
    """
    mid = _macro_id(m, "series")
    _closed_fields(m, SERIES_FIELDS, mid)

    n = m.get("count")
    if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= MAX_SERIES_COUNT):
        raise _err(f"series.count — целое 1..{MAX_SERIES_COUNT}", mid, got=n)

    items = m.get("items")
    if not isinstance(items, list) or not items:
        raise _err("series.items — непустой список опов", mid)

    expanded_count = n * len(items)
    if expanded_count > MAX_SERIES_OPS:
        raise _err(f"series развернётся в {expanded_count} опов ({n} x "
                   f"{len(items)}) — предел {MAX_SERIES_OPS}. Разбей на "
                   f"несколько series", mid, got=expanded_count)

    seen_base: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            raise _err("series.items: op должен быть объектом", mid, got=it)
        op_name = it.get("op")
        if op_name in MACRO_OPS:
            raise _err(f"series.items: макрос '{op_name}' внутри макроса не "
                       f"разворачивается — вложенность превратила бы экспансию в "
                       f"рекурсию, которой в языке нет (SPEC 12.3)", mid,
                       got=op_name)
        if op_name not in _SERIES_ABLE:
            raise _err(f"series.items: '{op_name}' не тиражируется "
                       f"(допустимы {list(_SERIES_ABLE)})", mid, got=op_name)
        base = it.get("id", op_name)
        if not isinstance(base, str) or not (1 <= len(base) <= 64):
            raise _err("series.items[].id — строка длиной 1..64", mid, got=base)
        if base in seen_base:
            raise _err(f"series.items: повторяющийся id '{base}' — после "
                       f"экспансии два опа на одном шаге получили бы один id",
                       mid, got=base)
        seen_base.add(base)

    # The template body = everything except op/id: substitution must not
    # be able to assemble an op's name or id from a number, and expansion
    # assigns the id anyway.
    bodies = [{k: v for k, v in it.items() if k not in ("op", "id")}
              for it in items]

    used: dict[str, bool] = {}
    _scan_refs(bodies, used, mid)

    parsed = _validate_track(m, mid)

    unknown = sorted(set(used) - set(parsed))
    if unknown:
        raise _err(f"series.items: ссылка на параметр '{unknown[0]}', которого "
                   f"нет в series.track (объявлены: {sorted(parsed)})", mid,
                   field_name=unknown[0], got=unknown[0])
    unused = sorted(set(parsed) - set(used))
    if unused:
        raise _err(f"series.track: параметр '{unused[0]}' объявлен, но ни разу "
                   f"не использован в items — либо опечатка в ссылке, либо "
                   f"мёртвый трек", mid, field_name=unused[0], got=unused[0])

    for name, needs_next in used.items():
        top = n if needs_next else n - 1
        lo, hi = parsed[name][0][0], parsed[name][-1][0]
        if lo > 0 or hi < top:
            raise _err(
                f"series.track['{name}'] покрывает индексы {lo:g}..{hi:g}, а "
                f"читается на 0..{top} (count={n}"
                f"{', используется @next' if needs_next else ''}). Трек обязан "
                f"покрывать каждый индекс: экстраполяция запрещена, а зажим к "
                f"крайнему узлу дал бы одинаковые повторы молча",
                mid, field_name=name, expected=f"0..{top}", got=f"{lo:g}..{hi:g}")

    out: list[dict] = []
    for k in range(n):
        at_k = {name: _track_at(nodes, k) for name, nodes in parsed.items()}
        at_next = {name: _track_at(parsed[name], k + 1)
                   for name, needs_next in used.items() if needs_next}
        # THE SAME CLASS AS stack's, AND CURED THE SAME WAY. `series`
        # also renames member ids at every step (`{mid}_{k}_{base}`) and
        # also failed to rewrite references between them. There is no live
        # defect here today — among `_SERIES_ABLE` there is no one to
        # reference a neighbor — but the gap is the same, and leaving it
        # closed in one expander out of two would mean fixing the CASE
        # instead of the CLASS: the very first hosted tenant would arrive
        # here with the same bug, already declared fixed.
        renames = {it.get("id", it["op"]): _derived_id("series", mid, "member", k, it.get("id", it["op"]))
                   for it in items}
        for it, body in zip(items, bodies):
            base = it.get("id", it["op"])
            c = {"op": it["op"], "id": renames[base]}
            c.update(_substitute(body, at_k, at_next))
            stray = _host_ref_outside(c, renames)
            if stray is not None:
                raise _err(
                    f"series.items: '{c['op']}' ссылается на хозяина "
                    f"'{stray}', которого нет среди членов шага. Хостящийся оп "
                    f"тиражируется ТОЛЬКО вместе со своим хозяином: иначе на "
                    f"каждом шаге он повис бы на элементе нулевого. "
                    f"СЛЕДУЮЩИЙ ХОД: внеси хозяина в items — либо адресуй его "
                    f"element_id, если это настоящий элемент документа",
                    mid, field_name="host", got=stray)
            c = _rename_member_refs(c, renames)
            out.append(c)
    return out


_EXPANDERS = {"stack": _expand_stack, "grid_array": _expand_grid_array,
              "series": _expand_series}


@dataclass(frozen=True, slots=True)
class ExpansionOrigin:
    """Source-envelope location of one flat op after macro expansion."""

    source_index: int
    source_op: str | None
    source_id: str | None
    macro_name: str | None = None


def _origin(source_index: int, op: Any, *, macro_name: str | None = None
            ) -> ExpansionOrigin:
    source_op = op.get("op") if isinstance(op, dict) else None
    source_id = op.get("id") if isinstance(op, dict) else None
    if macro_name is not None and source_id is None:
        # Macro expanders use the macro name as their documented default id.
        source_id = macro_name
    return ExpansionOrigin(
        source_index=source_index,
        source_op=source_op if isinstance(source_op, str) else None,
        source_id=source_id if isinstance(source_id, str) else None,
        macro_name=macro_name,
    )


def expand_with_origins(
    ops: Any,
) -> tuple[Any, tuple[ExpansionOrigin, ...]]:
    """Flatten macros and retain a 1:1 source trace for every flat op.

    Non-list input still passes through unchanged so the compiler owns its
    typed shape diagnostic, matching :func:`expand`'s historical contract.
    """
    if not isinstance(ops, list):
        return ops, ()
    has_macros = any(
        isinstance(o, dict) and o.get("op") in MACRO_OPS for o in ops
    )
    if not has_macros:
        return ops, tuple(_origin(i, op) for i, op in enumerate(ops))
    out: list[dict] = []
    origins: list[ExpansionOrigin] = []
    for source_index, o in enumerate(ops):
        if isinstance(o, dict) and o.get("op") in MACRO_OPS:
            macro_name = o["op"]
            try:
                expanded = _EXPANDERS[macro_name](o)
            except KirRefusal as refusal:
                # op_index (25.08.2026, mission instrument measurement):
                # every `_expand_*` knows only ITS OWN dict `m` — the
                # macro's position in the program is visible EXACTLY HERE,
                # in this loop, and nowhere else. Previously a macro's
                # refusal came out with `op_index=None`, even though the
                # number was known from the method's first line — it was
                # simply never carried through. Setting it HERE, in one
                # place for all three macros, rather than in each
                # `_expand_*` — that very same shared carrier, rather than
                # four point fixes.
                for d in refusal.diagnostics:
                    if d.op_index is None:
                        d.op_index = source_index
                raise
            out.extend(expanded)
            origins.extend(
                _origin(source_index, o, macro_name=macro_name)
                for _ in expanded
            )
        else:
            out.append(o)
            origins.append(_origin(source_index, o))
    if len(out) > MAX_EXPANDED_OPS:
        raise _err(f"экспансия макросов превысила бюджет {MAX_EXPANDED_OPS} опов "
                   f"(получилось {len(out)})")
    return out, tuple(origins)


def expand(ops: Any) -> Any:
    """Flatten macros (deterministic), preserving the legacy public API."""
    return expand_with_origins(ops)[0]
