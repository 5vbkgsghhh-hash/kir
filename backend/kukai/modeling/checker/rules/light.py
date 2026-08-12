"""Daylight rules for habitable rooms (design §6, HAB030–HAB031).

HAB030 — every habitable room (жилая) and kitchen (кухня) must have an exterior window.
         жилая without a window is BLOCKING (uninhabitable); кухня is WARNING.
HAB031 — daylight ratio window_area_m2 / area_m2 >= thr.min_daylight_ratio (INFO).

Pure functions over SpatialModel + graph + Thresholds (no I/O, no mutation). They read
Room.has_window / Room.window_area_m2 / Room.area_m2 and thr only — no magic numbers.
"""
from __future__ import annotations

import networkx as nx

from kukai.modeling.checker.spatial_model import (
    RoomFunction,
    Severity,
    SpatialModel,
    Violation,
)
from kukai.modeling.checker.thresholds import Thresholds

# Rooms that require natural light. жилая is hard-required (BLOCKING); кухня is softer.
_DAYLIT_SEVERITY: dict[RoomFunction, Severity] = {
    RoomFunction.ЖИЛАЯ: Severity.BLOCKING,
    RoomFunction.КУХНЯ: Severity.WARNING,
}


def check_hab030(
    model: SpatialModel, graph: nx.Graph, thr: Thresholds
) -> list[Violation]:
    """HAB030 — habitable rooms (and kitchens) must have an exterior window."""
    violations: list[Violation] = []
    for room in model.rooms:
        severity = _DAYLIT_SEVERITY.get(room.function)
        if severity is None:
            continue  # only жилая / кухня are subject to HAB030
        if room.has_window and room.window_area_m2 > 0.0:
            continue
        violations.append(
            Violation(
                rule_id="HAB030",
                severity=severity,
                refs=[room.id],
                msg=(
                    f"Помещение '{room.name}' ({room.function.value}) не имеет "
                    f"наружного окна — жить/готовить без естественного света нельзя."
                ),
                fix_hint=(
                    "Добавьте окно в наружную стену помещения "
                    f"'{room.name}' (room_id={room.id})."
                ),
            )
        )
    return violations


def check_hab031(
    model: SpatialModel, graph: nx.Graph, thr: Thresholds
) -> list[Violation]:
    """HAB031 — daylight ratio window_area_m2 / area_m2 must be >= thr.min_daylight_ratio.

    INFO-only. Skips rooms with no window (that case is HAB030) and rooms with zero
    floor area (avoids division by zero — a zero-area room is a different defect)."""
    violations: list[Violation] = []
    for room in model.rooms:
        if room.function not in _DAYLIT_SEVERITY:
            continue
        if not room.has_window or room.window_area_m2 <= 0.0:
            continue  # windowless → HAB030, not HAB031
        if room.area_m2 <= 0.0:
            continue
        ratio = room.window_area_m2 / room.area_m2
        if ratio >= thr.min_daylight_ratio:
            continue
        violations.append(
            Violation(
                rule_id="HAB031",
                severity=Severity.INFO,
                refs=[room.id],
                msg=(
                    f"Помещение '{room.name}' ({room.function.value}): "
                    f"остекление {room.window_area_m2:.2f} m² / пол {room.area_m2:.2f} m² "
                    f"= {ratio:.3f} ниже нормы {thr.min_daylight_ratio:.3f} (1:8)."
                ),
                fix_hint=(
                    "Увеличьте площадь остекления до "
                    f">= {room.area_m2 * thr.min_daylight_ratio:.2f} m² "
                    f"в помещении '{room.name}' (room_id={room.id})."
                ),
            )
        )
    return violations
