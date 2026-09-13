"""Daylight rules for habitable rooms (design §6, HAB030–HAB031).

HAB030 — every habitable room (жилая) and kitchen (кухня) must have an exterior window.
         жилая without a window is BLOCKING (uninhabitable); кухня is WARNING.
HAB031 — daylight ratio window_area_m2 / area_m2 >= thr.min_daylight_ratio (INFO).

Pure functions over SpatialModel + graph + Thresholds (no I/O, no mutation). They read
Room.has_window / Room.window_area_m2 / Room.area_m2 and thr only — no magic numbers.
"""
from __future__ import annotations

import networkx as nx

from kir.checker.function_provenance import (
    describe as describe_function,
)
from kir.checker.function_provenance import (
    is_authored as function_is_authored,
)
from kir.checker.spatial_model import (
    RoomFunction,
    Severity,
    SpatialModel,
    Violation,
)
from kir.checker.flags import checker_v2_enabled
from kir.checker.thresholds import Thresholds

# Rooms that require natural light. жилая is hard-required (BLOCKING); кухня is softer.
_DAYLIT_SEVERITY: dict[RoomFunction, Severity] = {
    RoomFunction.ЖИЛАЯ: Severity.BLOCKING,
    RoomFunction.КУХНЯ: Severity.WARNING,
}


def check_hab030(
    model: SpatialModel, graph: nx.Graph, thr: Thresholds
) -> list[Violation]:
    """HAB030 — habitable rooms (and kitchens) must have an exterior window.

    🔴 A BLOCKING VERDICT DOES NOT REST ON A FUNCTION THE AUTHOR NEVER NAMED
    (22.08.2026), the same law as at HAB020/HAB021 and at HAB022 with height. "жилая
    without a window" BLOCKS, and the word "жилая" has, since 22.08, sometimes been
    derived by us from context (a bed → жилая): the accusation then rests on our dictionary,
    not on intent. The threshold is not relaxed — the authority changes, and the reason is named.
    """
    violations: list[Violation] = []
    for room in model.rooms:
        severity = _DAYLIT_SEVERITY.get(room.function)
        if severity is None:
            continue  # only habitable / kitchen rooms are subject to HAB030
        # 🔴 UNDER v2 `has_window` IS ALREADY GEOMETRIC, AND THE AREA CLAUSE HERE
        # IS HARMFUL (F-254, 30.08.2026). `derive` sets
        # `has_window=bool(verified_window_ids)` — that is, the window is CONFIRMED
        # by geometry. Demanding `window_area_m2 > 0` on top of that means reading
        # "we did not measure the opening's size" as "there is no window" and issuing a BLOCKING
        # "cannot live without light" out of OUR OWN blindness. Under v1 the clause stays:
        # there `has_window` is a bare author declaration, and there is nothing to check it against.
        if room.has_window and (checker_v2_enabled()
                                or room.window_area_m2 > 0.0):
            continue
        # Provenance is named ALWAYS (see the argument at `dimensions.check_hab020`), and
        # severity only drops for the strict one: "kitchen without a window" is WARNING already, but
        # it was the KITCHEN FRONT that named this room a kitchen, and the finding must say so.
        named = function_is_authored(room.function_source)
        why = "" if named else f" ({describe_function(room.function_source)})"
        if severity is Severity.BLOCKING and not named:
            severity = Severity.WARNING
            why = (f" Вердикт НЕ блокирующий: "
                   f"{describe_function(room.function_source)}.")
        violations.append(
            Violation(
                rule_id="HAB030",
                severity=severity,
                refs=[room.id],
                msg=(
                    f"Помещение '{room.name}' ({room.function.value}) не имеет "
                    f"наружного окна — жить/готовить без естественного света "
                    f"нельзя.{why}"
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
        # 🔴 THE NORM IS APPLIED TO THE FUNCTION, AND SOMEONE NAMES THE FUNCTION (07.09.2026).
        # The direction of the cost here is the OPPOSITE of HAB003/HAB010: there a guess
        # EXTINGUISHED the verdict, here it ADDS one — a sofa could have named the room
        # "жилой" (habitable), and then the 1:8 ratio is measured against our dictionary, not intent.
        # The subject CANNOT be excluded: that would extinguish the finding, exactly the thing the
        # provenance mechanism was set up against. Under `function_provenance`'s law ("judging is
        # allowed, BLOCKING is not") there is nothing to downgrade here either — HAB031 is INFO
        # already. What's left is the one thing that was missing: the finding NAMES its source, just
        # as HAB030 does twenty lines above.
        why = ("" if function_is_authored(room.function_source)
               else f" Функция помещения: {describe_function(room.function_source)}.")
        violations.append(
            Violation(
                rule_id="HAB031",
                severity=Severity.INFO,
                refs=[room.id],
                msg=(
                    f"Помещение '{room.name}' ({room.function.value}): "
                    f"остекление {room.window_area_m2:.2f} m² / пол {room.area_m2:.2f} m² "
                    f"= {ratio:.3f} ниже нормы {thr.min_daylight_ratio:.3f} (1:8).{why}"
                ),
                fix_hint=(
                    "Увеличьте площадь остекления до "
                    f">= {room.area_m2 * thr.min_daylight_ratio:.2f} m² "
                    f"в помещении '{room.name}' (room_id={room.id})."
                ),
            )
        )
    return violations
