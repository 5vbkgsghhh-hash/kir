"""SHAPE ALIAS BY TYPE: who to ask Revit about, and who gets a neighbor's
answer.

WHY. The shape store is already content-addressed: identical geometry lands
under one `geo_hash` and is not physically duplicated
(`geom_extract.GeometryStore`). But deduplication happens AFTER the bridge —
"the Python half deduplicates its bridge payload offline". That is, STORAGE
is saved but the FETCH is not: to get 268 distinct shapes for tower K2, today
you would still have to pull 38 175 instances across the bridge.

The idea "a shape belongs to its type" reached the store but never reached
the door. This module is that door: it splits the requested elements into
those who will be asked, and those who will get a type-neighbor's shape.

🔴 A SHAPE DOES NOT ALWAYS BELONG TO ITS TYPE, AND THIS IS MEASURED, NOT
ASSUMED.

Measured 15.08.2026 on `k2_ar_rd_v15` (35 943 instances, 266 types, a 2 mm
threshold declared before the measurement): only 28.48% of instances agree
by bounding box, and the split is STRUCTURAL, not random:

    doors             1743 of 2096    catalog family — the alias is valid
    plumbing fixtures 1422 of 1426    catalog
    beams             1361 of 1426    catalog
    casework            65 of 11 994  CUT TO THE CELL — the shape is the
                                      INSTANCE's own
    curtain panels     437 of 4 322   cut to fit
    telephones          11 of 4 479

That is why a representative is NEVER assigned on faith. It is assigned, and
the other instances of the same type are CHECKED against it by bounding box;
the ones that diverge are asked separately and land in the report under
their own name.

THE INSTRUMENT'S LIMIT, named here rather than discovered later. Bounding
box is a WEAK stand-in for shape, and it is weak in one direction:

  * different shapes with the same bounding box will NOT be told apart — a
    theoretical hole we have no cheap instrument against;
  * identical shapes rotated by a NON-RIGHT angle will be declared different.
    Sorting the dimensions removes 90° rotations and mirrors, but not an
    arbitrary angle. So the alias share computed from bounding box is a
    LOWER BOUND on the savings, not an estimate of them.

The two sides are asymmetric in cost, and the default was chosen for that
asymmetry: **when in doubt, ASK**. An extra round trip costs time; someone
else's shape handed out as your own is a silently-wrong result, and that is
forbidden by construction.
"""
from __future__ import annotations

import os
from kir import env  # noqa: E402  (dependency-free submodule — avoids an import cycle)
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


def type_shapes_enabled() -> bool:
    """The gate for the type-based shape library; OFF by default.

    WHY IT IS OFF, even though the channel is proven live (15.08: 31 fetches,
    30 types with a shape, 425 instances covered, 16 s). The pipeline states
    its cost right in the code — "Extracting full geometry for all L0
    elements would waste the Revit budget" — and the cost is real: every
    representative is a round trip to the bridge. The flag exists so that
    this cost is a DECISION, not a side effect of someone else's edit.

    HONEST STATUS AS OF 15.08: the channel was verified live by a SEPARATE
    instrument; it has never been run live THROUGH THE PIPELINE (Revit
    stopped responding at that hour). This is exactly the third flag state
    the canon requires naming: not "on", not "off", but "built and not
    yet road-tested".
    """
    return env.get("KIR_TYPE_SHAPES", "").strip().lower() in {
        "1", "true", "yes", "on",
    }

#: Bounding-box comparison tolerance, mm. Declared BEFORE the alias-share
#: measurement, and matches the bounding-box threshold that closed out the
#: "shape 1-to-1" goal (24 of 24 families). This number is ASSIGNED here, not
#: derived, and therefore travels into the report together with the share:
#: the reader must be able to see under which tolerance it was obtained.
BBOX_TOLERANCE_MM = 2.0

#: Why an instance is asked about separately. The list is CLOSED and
#: COMPLETE BY CONSTRUCTION: every input element gets exactly one label, and
#: the `assert` in `plan_geometry_asks` enforces this. A new reason must be
#: added here, or it will travel into the report unnamed.
ASK_REASONS = (
    "representative",        # this is the representative of its own type
    "type_unknown",          # type could not be read — the alias has nothing to stand on
    "bbox_unknown",          # no bounding box, nothing to compare against
    "instance_driven",       # bounding box disagrees with the representative: the instance shapes itself
    "singleton",             # type has a single instance: nobody to alias to
)


@dataclass(frozen=True)
class GeometryAskPlan:
    """Who to ask, who gets a borrowed shape, and why — per element."""

    #: The ids that go into `build_geometry_extract_cs`.
    ask: tuple[str, ...]
    #: element -> representative element whose shape it will receive.
    alias: dict[str, str]
    #: element -> reason from `ASK_REASONS` (only for those who are asked).
    reason: dict[str, str]
    #: summary for the receipt; numbers, not adjectives.
    stats: dict[str, Any] = field(default_factory=dict)

    def saved_calls(self) -> int:
        """How many bridge round trips were saved. Zero is a legal answer."""
        return len(self.alias)


def _dims(bbox_min: Any, bbox_max: Any) -> tuple[float, float, float] | None:
    """Bounding-box dimensions, sorted. Sorting is exactly what removes 90°
    rotations and mirrors; it does not remove an arbitrary angle (see the
    module header)."""
    if not (isinstance(bbox_min, (list, tuple))
            and isinstance(bbox_max, (list, tuple))
            and len(bbox_min) == 3 and len(bbox_max) == 3):
        return None
    try:
        out = sorted(float(bbox_max[i]) - float(bbox_min[i]) for i in range(3))
    except (TypeError, ValueError):
        return None
    if any(v != v or v in (float("inf"), float("-inf")) for v in out):
        return None
    return (out[0], out[1], out[2])


def _same_shape(a: tuple[float, float, float],
                b: tuple[float, float, float],
                tolerance_mm: float) -> bool:
    return all(abs(a[i] - b[i]) <= tolerance_mm for i in range(3))


def plan_geometry_asks(
    elements: Iterable[Mapping[str, Any]],
    *,
    tolerance_mm: float = BBOX_TOLERANCE_MM,
) -> GeometryAskPlan:
    """Split elements into "ask" and "take from the representative".

    `elements` are records with keys `element_id`, `type_id` (may be
    missing), `bbox_min_mm`, `bbox_max_mm`. Exactly these fields are read:
    the module never touches Revit or disk, so it can be checked entirely
    offline.

    THE REPRESENTATIVE IS CHOSEN DETERMINISTICALLY — the smallest type id.
    Not decoration: a non-deterministic choice would give one building
    different `geo_hash` values from run to run, and the diff between two
    decompiles (`kir_merkle`, a rebuild delta) would show edits where
    nothing had changed.
    """
    rows: list[tuple[str, str | None, tuple[float, float, float] | None]] = []
    for el in elements:
        eid = el.get("element_id")
        if eid is None:
            continue
        rows.append((str(eid),
                     None if el.get("type_id") in (None, "")
                     else str(el.get("type_id")),
                     _dims(el.get("bbox_min_mm"), el.get("bbox_max_mm"))))

    by_type: dict[str, list[tuple[str, tuple[float, float, float] | None]]] = {}
    ask: list[str] = []
    reason: dict[str, str] = {}
    alias: dict[str, str] = {}

    for eid, tid, dims in rows:
        if tid is None:
            ask.append(eid)
            reason[eid] = "type_unknown"
            continue
        by_type.setdefault(tid, []).append((eid, dims))

    instance_driven = 0
    aliased_types = 0
    for tid, members in sorted(by_type.items()):
        members.sort(key=_id_order)
        if len(members) == 1:
            eid = members[0][0]
            ask.append(eid)
            reason[eid] = "singleton"
            continue
        head_eid, head_dims = members[0]
        ask.append(head_eid)
        reason[head_eid] = "representative"
        if head_dims is None:
            # A representative with no bounding box has nothing to compare
            # against — so NOBODY gets aliased to it. The default is "when
            # in doubt, ask", not "trust it".
            for eid, _d in members[1:]:
                ask.append(eid)
                reason[eid] = "bbox_unknown"
            continue
        used = False
        for eid, dims in members[1:]:
            if dims is None:
                ask.append(eid)
                reason[eid] = "bbox_unknown"
            elif _same_shape(head_dims, dims, tolerance_mm):
                alias[eid] = head_eid
                used = True
            else:
                ask.append(eid)
                reason[eid] = "instance_driven"
                instance_driven += 1
        if used:
            aliased_types += 1

    total = len(rows)
    assert len(ask) + len(alias) == total, (
        "каждый элемент обязан быть либо спрошен, либо приписан к образцу")
    assert set(reason) == set(ask), "у каждого спрошенного своя причина"

    stats = {
        "elements": total,
        "types": len(by_type),
        "asked": len(ask),
        "aliased": len(alias),
        "aliased_types": aliased_types,
        "instance_driven": instance_driven,
        "tolerance_mm": tolerance_mm,
        # The share is a LOWER BOUND: bounding box declares identical shapes
        # rotated by a non-right angle to be different. The field's name
        # must carry this, or the number will be read as an estimate.
        "alias_share_lower_bound": (
            round(100.0 * len(alias) / total, 2) if total else 0.0),
    }
    return GeometryAskPlan(tuple(ask), alias, reason, stats)


def _id_order(item: tuple[str, Any]) -> tuple[int, Any]:
    """Numeric ids sort by number, the rest by string. Plain string sorting
    would put "10" before "9" and make the choice of representative depend
    on digit count."""
    eid = item[0]
    try:
        return (0, int(eid))
    except (TypeError, ValueError):
        return (1, eid)


def attach_aliased_geometry(index_rows: Sequence[Mapping[str, Any]],
                            plan: GeometryAskPlan) -> list[dict[str, Any]]:
    """Append index rows for those who received the representative's shape.

    The input is what the fetch returned (one row per ASKED element, with
    `geo_hash` and `transform`). The output is the same rows plus alias rows.

    🔴 THE REPRESENTATIVE'S `transform` IS NOT COPIED. It describes the
    REPRESENTATIVE's position in space, and handing it to a neighbor would
    mean placing a door where another door already stands. An alias carries
    the shape and does NOT carry a position: its `transform` stays empty,
    and the position comes from wherever it always came from — the L0 of the
    instance itself. The row is tagged `alias_of` so the reader can tell
    what was captured from what was attributed.
    """
    # 🔴 THE RECORD'S FIELD IS `element_id`, AND THIS WAS ASKED OF A LIVE
    # FETCH, NOT ASSUMED. The first draft read `source_element_id` — that is
    # what the field is called in the PIPELINE's index, and the name looked
    # obvious. A live run on 15.08 produced ZERO shapes with ZERO failures: a
    # silent emptiness visible only through a counter. `GeometryIndexRecord`
    # carries `element_id`.
    #
    # The old name is accepted as a fallback: the pipeline's index genuinely
    # calls it that, and silently failing to find the row is the same defect
    # in the other direction.
    def _row_id(row):
        return str(row.get("element_id")
                   if row.get("element_id") is not None
                   else row.get("source_element_id"))

    by_id = {_row_id(r): r for r in index_rows}
    out = [dict(r) for r in index_rows]
    for eid, head in plan.alias.items():
        source = by_id.get(str(head))
        if source is None:
            continue          # representative was never captured — we do not silently emit an alias
        row = dict(source)
        # We write to the SAME FIELD we read from: mixing the two names in
        # one set of rows would hand the consumer a set half of which it can
        # address, and half it cannot.
        if source.get("element_id") is not None:
            row["element_id"] = eid
        else:
            row["source_element_id"] = eid
        row["alias_of"] = str(head)
        row["transform"] = None
        out.append(row)
    return out


#: The capture tier that counts as a REAL shape. `Gb` is the same bounding
#: box, just fetched at greater cost, and lumping it together with a mesh
#: under one "shape" column would mean declaring victory over exactly what
#: the owner complained about.
MESH_TIER = "Gm"


def build_type_shape_library(
    elements: Iterable[Mapping[str, Any]],
    index_rows: Sequence[Mapping[str, Any]],
    plan: GeometryAskPlan,
) -> dict[str, Any]:
    """`{type_id: geo_hash}` plus the numbers this decision is judged by.

    The library is built ONLY from representatives: a singleton and an
    "instance-driven shape" have no shape of the TYPE by definition, and
    recording them here would mean passing off one instance's shape as
    everyone's.

    Each row's tier is distinguished: `types_with_mesh` and
    `types_with_shape` are different numbers, and the report must carry
    both.
    """
    type_of = {str(e.get("element_id")): str(e.get("type_id"))
               for e in elements if e.get("element_id") is not None
               and e.get("type_id") not in (None, "")}

    reps = {eid for eid in plan.ask
            if plan.reason.get(eid) == "representative"}

    shapes: dict[str, str] = {}
    mesh_types: set[str] = set()
    tiers: dict[str, int] = {}
    for row in index_rows:
        eid = str(row.get("element_id")
                  if row.get("element_id") is not None
                  else row.get("source_element_id"))
        if eid not in reps:
            continue
        geo_hash = row.get("geo_hash")
        type_id = type_of.get(eid)
        tier = row.get("tier")
        tier = str(getattr(tier, "value", tier) or "")
        tiers[tier] = tiers.get(tier, 0) + 1
        if not geo_hash or not type_id:
            continue
        shapes[type_id] = str(geo_hash)
        if tier == MESH_TIER:
            mesh_types.add(type_id)

    covered = sum(1 for e in elements
                  if str(e.get("type_id")) in shapes)
    covered_mesh = sum(1 for e in elements
                       if str(e.get("type_id")) in mesh_types)
    return {
        "schema": "type-shape-library/1",
        "type_shapes": shapes,
        "types_with_shape": len(shapes),
        "types_with_mesh": len(mesh_types),
        "instances_covered": covered,
        "instances_covered_by_mesh": covered_mesh,
        "tiers": tiers,
        "representatives_asked": len(reps),
        # The same name as in `plan.stats`: bounding box declares identical
        # shapes rotated by a non-right angle to be different, so this is a
        # LOWER bound.
        "alias_share_lower_bound": plan.stats.get("alias_share_lower_bound"),
    }
