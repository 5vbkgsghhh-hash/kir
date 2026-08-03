"""Declaration-consistency rules (checker v2): HAB060–HAB063.

These rules read the DerivationReport (derive.py) — the geometric witness — and flag
every place where the DECLARED model disagrees with what geometry supports. They are
the anti-self-certification layer: the fix-loop and the LLM can write any scalar they
like, but a scalar that geometry does not back is now a BLOCKING lie, not a pass.

HAB060  declared scalar vs derived geometry (area lies, window claims)   BLOCKING
HAB061  door adjacency vs geometry (phantom doors / fake exits)          BLOCKING
        (unverifiable adjacency / orphan doors / above-grade exits)      WARNING
HAB062  unclassified habitable-sized room — habitability not applied     WARNING
HAB063  floor-plate dead void (rooms-union vs closed footprint)          WARNING

Signature: check_habNNN(model, dmodel, drep, thr) -> list[Violation] — model is the
DECLARED input, dmodel the derived model, drep the DerivationReport. Run only on the
v2 engine path."""
from __future__ import annotations

from kukai.modeling.checker.derive import DerivationReport, DoorStatus
from kukai.modeling.checker.spatial_model import (
    Severity,
    SpatialModel,
    Violation,
)
from kukai.modeling.checker.thresholds import Thresholds


def check_hab060(model: SpatialModel, dmodel: SpatialModel,
                 drep: DerivationReport, thr: Thresholds) -> list[Violation]:
    """HAB060 — declaration consistency: every declared scalar must match geometry."""
    violations: list[Violation] = []
    names = {r.id: r.name for r in model.rooms}
    for rid, rd in sorted(drep.rooms.items()):
        if rd.area_mismatch and rd.derived_area_m2 is not None:
            violations.append(Violation(
                rule_id="HAB060",
                severity=Severity.BLOCKING,
                refs=[rid],
                msg=(f"Room '{names.get(rid, rid)}' declares area "
                     f"{rd.declared_area_m2:g} m² but its boundary polygon measures "
                     f"{rd.derived_area_m2:g} m² — the declaration is not backed by "
                     f"geometry."),
                fix_hint="Fix the boundary polygon (the geometry is the truth); the "
                         "declared area_m2 is recomputed from it.",
            ))
        if rd.window_claim_unbacked:
            violations.append(Violation(
                rule_id="HAB060",
                severity=Severity.BLOCKING,
                refs=[rid],
                msg=(f"Room '{names.get(rid, rid)}' declares has_window=true but NO "
                     f"window is geometrically verified for it (host wall/location must "
                     f"lie on the room's envelope-exterior boundary)."),
                fix_hint="Add a real window hosted in a wall on an exterior boundary "
                         "segment of this room — setting the scalar is not a window.",
            ))
        if rd.derived_area_m2 is None:
            violations.append(Violation(
                rule_id="HAB060",
                severity=Severity.WARNING,
                refs=[rid],
                msg=(f"Room '{names.get(rid, rid)}' has no measurable boundary polygon "
                     f"— its declared dimensions cannot be verified."),
                fix_hint="Give the room a valid closed boundary loop (>= 3 points, "
                         "non-zero area).",
            ))
    return violations


def check_hab061(model: SpatialModel, dmodel: SpatialModel,
                 drep: DerivationReport, thr: Thresholds) -> list[Violation]:
    """HAB061 — door adjacency must be geometrically real (no phantom connectivity)."""
    violations: list[Violation] = []
    for did, dd in sorted(drep.doors.items()):
        if dd.status is DoorStatus.CONTRADICTED:
            violations.append(Violation(
                rule_id="HAB061",
                severity=Severity.BLOCKING,
                refs=[did],
                msg=f"Phantom door {did!r}: {dd.note}. Its declared connectivity was "
                    f"removed from the graph.",
                fix_hint="Place the door on the shared boundary segment of the two "
                         "rooms it connects (or on the envelope for an entrance).",
            ))
        elif dd.status is DoorStatus.ORPHAN:
            violations.append(Violation(
                rule_id="HAB061",
                severity=Severity.WARNING,
                refs=[did],
                msg=f"Orphan door {did!r}: touches no room and claims no room.",
                fix_hint="Remove the door or host it between two rooms / on the envelope.",
            ))
        elif dd.status is DoorStatus.UNKNOWN and dd.declared_exterior:
            violations.append(Violation(
                rule_id="HAB061",
                severity=Severity.WARNING,
                refs=[did],
                msg=(f"Door {did!r} is declared EXTERIOR but geometry does not support "
                     f"it ({dd.note}) — it is NOT counted as a building exit."),
                fix_hint="A street exit must sit on the building envelope; check the "
                         "door's room phase / the unplaced room on its far side.",
            ))
    for did in sorted(drep.above_grade_exterior_door_ids):
        violations.append(Violation(
            rule_id="HAB061",
            severity=Severity.INFO,
            refs=[did],
            msg=(f"Exterior door {did!r} sits above the grade band — treated as a "
                 f"balcony/terrace door, not ground egress."),
            fix_hint="",
        ))
    return violations


def check_hab062(model: SpatialModel, dmodel: SpatialModel,
                 drep: DerivationReport, thr: Thresholds) -> list[Violation]:
    """HAB062 — an unclassified (ПРОЧЕЕ) room of habitable size is UNVERIFIABLE, not
    exempt: the dimension/light rules silently skip it, so say so out loud."""
    violations: list[Violation] = []
    by_id = {r.id: r for r in dmodel.rooms}
    for rid in drep.unclassified_room_ids:
        room = by_id.get(rid)
        if room is None:
            continue
        rd = drep.rooms.get(rid)
        area = rd.derived_area_m2 if (rd and rd.derived_area_m2 is not None) else room.area_m2
        if area is None or area < thr.unclassified_min_area_m2:
            continue
        violations.append(Violation(
            rule_id="HAB062",
            severity=Severity.WARNING,
            refs=[rid],
            msg=(f"Room '{room.name}' ({area:g} m²) has an UNCLASSIFIED function — the "
                 f"habitability rules (area/width/height/daylight) were NOT applied to it."),
            fix_hint="Name the room recognizably (спальня/кухня/санузел/…) or stamp an "
                     "explicit function; unknown ≠ exempt.",
        ))
    return violations


def check_hab063(model: SpatialModel, dmodel: SpatialModel,
                 drep: DerivationReport, thr: Thresholds) -> list[Violation]:
    """HAB063 — floor-plate dead void: rooms must substantially cover the closed level
    footprint (the DeepSeek 26%-void case). WARNING instrument (courtyards dip legitimately)."""
    violations: list[Violation] = []
    for lid, coverage in sorted(drep.floorplate_coverage.items()):
        if coverage < thr.min_floorplate_coverage:
            violations.append(Violation(
                rule_id="HAB063",
                severity=Severity.WARNING,
                refs=[lid],
                msg=(f"Level {lid}: rooms cover only {coverage * 100:.0f}% of the closed "
                     f"floor plate (< {thr.min_floorplate_coverage:.0%}) — large dead "
                     f"void / unusable in-between space."),
                fix_hint="Fill the plate with rooms or shrink the envelope; every m² "
                         "inside the envelope should belong to a room.",
            ))
    return violations


#: Ordered v2 consistency registry (engine runs these before the geometric ruleset).
CONSISTENCY_REGISTRY = [
    ("HAB060", check_hab060),
    ("HAB061", check_hab061),
    ("HAB062", check_hab062),
    ("HAB063", check_hab063),
]
