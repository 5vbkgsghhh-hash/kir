"""Vertical-circulation rules (design §6): HAB011 stair geometry, HAB012 core continuity.

Pure functions over SpatialModel; no I/O, no mutation. Every numeric constant comes
from `thr` (Thresholds) — no magic numbers (design §11.4). Both rules are WARNING:
a stair that is too steep or a core that jogs between floors is probably wrong but does
not by itself make the building uninhabitable (design §6 severity model)."""
from __future__ import annotations

import networkx as nx
from shapely.geometry import Polygon

from kir.checker.flags import checker_v2_enabled
from kir.checker.spatial_model import SpatialModel, Severity, Violation, Stair
from kir.checker.stair_provenance import describe as describe_top
from kir.checker.stair_provenance import is_authored as top_is_authored
from kir.checker.thresholds import Thresholds


def check_hab011(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB011 — stair geometry sane (run width / rise / going). WARNING.

    rise = (top_z - base_z) / riser_count; going = tread_depth_mm.

    v1: a stair whose riser_count or tread_depth_mm is None is SKIPPED silently.
    v2 (unknown ≠ pass): each MEASURED parameter is checked and a measured violation is
    BLOCKING (a 300 mm run is a fact, not a maybe); every UNMEASURED parameter — and
    every kind='inferred' pseudo-run — produces a per-stair 'cannot verify' WARNING
    instead of silence, and the engine's coverage counts the rule NOT_EVALUATED when no
    stair is fully measured.

    🔴 A BLOCKING VERDICT ABOUT SLOPE DOES NOT REST ON A TOP WE COMPUTED OURSELVES
    (22.08.2026). MNVNK measurement: `STAIRS_TOP_LEVEL_PARAM` is empty for 24 stairs out of 24, and
    the top is derived as base + riser count × riser height. On such a
    top the formula `(top_z - base_z) / riser_count` returns EXACTLY the riser
    height it was used to compute the top from: every number in it is real, but
    the comparison stops being a comparison of two independent facts. The same law as
    `height_provenance` in HAB022, and the same cost of error — a strict verdict on
    a value that no one declared.

    The difference is observable: a stair with a 200 mm rise gives BLOCKING under
    `stairs_top_level_param` and WARNING under `riser_run`. This does not cancel
    the soft finding — a substituted top is not a reason to miss a steep flight, it is a reason not
    to call it proven.
    """
    v2 = checker_v2_enabled()
    violations: list[Violation] = []
    for stair in model.stairs:
        if not v2 and (stair.riser_count is None or stair.tread_depth_mm is None
                       or stair.run_width_mm is None):
            continue  # v1: rise/going underivable — skip per design §6

        if v2 and stair.kind == "inferred":
            violations.append(Violation(
                rule_id="HAB011",
                severity=Severity.WARNING,
                refs=sorted([stair.id]),
                msg=(f"Stair {stair.id!r} is an INFERRED vertical link (stacked "
                     f"лестница rooms) — no real stair element exists, its geometry "
                     f"cannot be verified."),
                fix_hint="Model a real stair element (run width/risers/treads) between "
                         "these levels.",
            ))
            continue

        defects: list[str] = []
        #: Defects RESTING ON THE DERIVED TOP ELEVATION — in a separate list,
        #: because they carry a different authority, not a different wording.
        soft_defects: list[str] = []
        unmeasured: list[str] = []
        top_authored = top_is_authored(stair.top_level_source)
        if stair.run_width_mm is None:
            unmeasured.append("run width")
        elif stair.run_width_mm < thr.stair_min_run_width_mm:
            defects.append(
                f"run width {stair.run_width_mm:.0f} mm "
                f"< {thr.stair_min_run_width_mm:.0f} mm"
            )
        if stair.riser_count is None:
            unmeasured.append("riser count (rise underivable)")
        else:
            rise_mm = (stair.top_z - stair.base_z) / stair.riser_count
            if rise_mm > thr.stair_max_rise_mm:
                (defects if top_authored else soft_defects).append(
                    f"rise {rise_mm:.0f} mm > {thr.stair_max_rise_mm:.0f} mm"
                )
        if stair.tread_depth_mm is None:
            unmeasured.append("tread depth (going underivable)")
        elif stair.tread_depth_mm < thr.stair_min_going_mm:
            defects.append(
                f"going {stair.tread_depth_mm:.0f} mm < {thr.stair_min_going_mm:.0f} mm"
            )
        if defects:
            violations.append(
                Violation(
                    rule_id="HAB011",
                    severity=Severity.BLOCKING if v2 else Severity.WARNING,
                    refs=sorted([stair.id]),
                    msg=f"Stair {stair.id!r} geometry unsafe: " + "; ".join(defects),
                    fix_hint=(
                        "Widen the run to >= "
                        f"{thr.stair_min_run_width_mm:.0f} mm, keep rise <= "
                        f"{thr.stair_max_rise_mm:.0f} mm "
                        f"(add risers / lower the level span), and tread depth >= "
                        f"{thr.stair_min_going_mm:.0f} mm."
                    ),
                )
            )
        if soft_defects:
            violations.append(
                Violation(
                    rule_id="HAB011",
                    severity=Severity.WARNING,
                    refs=sorted([stair.id]),
                    msg=(f"Stair {stair.id!r} geometry suspect: "
                         + "; ".join(soft_defects)
                         + f", но вердикт НЕ блокирующий: "
                           f"{describe_top(stair.top_level_source)}."),
                    fix_hint=(
                        f"Объявите верхний уровень лестницы {stair.id!r} "
                        f"(STAIRS_TOP_LEVEL_PARAM) — тогда подъём станет сравнением "
                        f"расстояния между уровнями с числом подступенков, и вердикт "
                        f"станет строгим; сейчас он сравнивает высоту подступенка "
                        f"саму с собой."
                    ),
                )
            )
        if v2 and unmeasured:
            violations.append(
                Violation(
                    rule_id="HAB011",
                    severity=Severity.WARNING,
                    refs=sorted([stair.id]),
                    msg=(f"Stair {stair.id!r}: {', '.join(unmeasured)} unmeasured — "
                         f"stair geometry cannot be verified (unknown ≠ pass)."),
                    fix_hint="Extract/author real stair parameters (ACTUAL run width, "
                             "riser count, tread depth).",
                )
            )
    return violations


def _stair_by_base_level(model: SpatialModel) -> dict[str, list[Stair]]:
    """Map level_id → stair runs based on that level (design §6: a run starts on its
    base level and climbs to the next served level)."""
    by_level: dict[str, list[Stair]] = {}
    for stair in model.stairs:
        by_level.setdefault(stair.base_level_id, []).append(stair)
    return by_level


def _footprint_overlap_ratio(a: list[tuple[float, float]],
                             b: list[tuple[float, float]]) -> float:
    """Intersection area / smaller polygon area, in [0, 1]. 0 if either is degenerate.

    🔴 THE PROMISE ON THE LINE ABOVE WAS NOT KEPT (29.08.2026). `Polygon(a)`
    was built BEFORE the `is_valid` check, and shapely rejects a ring shorter than
    four coordinates WITH AN EXCEPTION:

        _footprint_overlap_ratio([(0, 0)], [(0, 0), (1, 0), (0, 1)])
        -> ValueError: A linearring requires at least 4 coordinates

    The `Stair.footprint` contract does not bound the list's length, so a trace of
    one or two points is a LEGAL typed input, and it used to crash HAB012 and, with
    it, the judge's entire run. Degeneracy must produce a documented
    zero, not a crash: "no coverage" and "nothing to measure with" are different answers, but both
    are answers, and an exception is not an answer to anything.
    """
    if len(a) < 3 or len(b) < 3:
        return 0.0
    pa, pb = Polygon(a), Polygon(b)
    if not pa.is_valid or not pb.is_valid:
        return 0.0
    smaller = min(pa.area, pb.area)
    if smaller <= 0.0:
        return 0.0
    return pa.intersection(pb).area / smaller


def hab012_comparable_pairs(model: SpatialModel):
    """The pairs of flights that HAB012 ACTUALLY compares. A lazy enumeration.

    🔴 WHY A SEPARATE FUNCTION, NOT A LOOP INSIDE THE RULE (29.08.2026,
    audit finding F-362). The rule's coverage was counted over a DIFFERENT population:

        RuleSpec(check_hab012, "HAB012",
                 lambda c: sum(1 for s in c.model.stairs if s.footprint), ...)

    that is, by STAIRS, whereas the rule considers PAIRS of adjacent
    served levels. For a building with one stair, `zip(served, served[1:])`
    is empty — NOT A SINGLE pair was compared — yet the coverage printed
    `HAB012 EVALUATED(n=1), 0 violations`. "Looked and it's clean" instead of
    "there was nothing to compare": exactly what this engine's
    three-valued verdict was set up for.

    There should be no two counters in principle: two carriers of the same knowledge
    drift apart silently, and would drift the more invisibly for both looking correct.
    So there is ONE enumeration, and the rule and the coverage are two readers of it.
    """
    by_level = _stair_by_base_level(model)
    # Served levels = those on which at least one flight is based, bottom to top.
    served = sorted(
        (lvl for lvl in model.levels if lvl.id in by_level),
        key=lambda lvl: lvl.index,
    )
    for lower, upper in zip(served, served[1:]):
        for s_low in by_level[lower.id]:
            for s_up in by_level[upper.id]:
                if not s_low.footprint or not s_up.footprint:
                    continue  # nothing to compare in plan
                yield lower, upper, s_low, s_up


def check_hab012(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB012 — stair-core continuous in plan between consecutive served levels. WARNING.

    For each pair of consecutive served levels (ordered by Level.index), the stair run
    based on the lower level must overlap the run based on the upper level by MORE than
    thr.stair_min_footprint_overlap_ratio of the smaller footprint. Otherwise the core
    jogs sideways between floors (design §6).

    The pair enumeration is `hab012_comparable_pairs`, and it is also what counts coverage."""
    violations: list[Violation] = []
    for lower, upper, s_low, s_up in hab012_comparable_pairs(model):
        ratio = _footprint_overlap_ratio(s_low.footprint, s_up.footprint)
        if ratio <= thr.stair_min_footprint_overlap_ratio:
            violations.append(
                Violation(
                    rule_id="HAB012",
                    severity=Severity.WARNING,
                    refs=sorted([s_low.id, s_up.id]),
                    msg=(
                        f"Stair core discontinuous between levels "
                        f"{lower.id!r} and {upper.id!r}: runs {s_low.id!r}/"
                        f"{s_up.id!r} footprint overlap "
                        f"{ratio * 100:.0f}% <= "
                        f"{thr.stair_min_footprint_overlap_ratio * 100:.0f}%"
                    ),
                    fix_hint=(
                        "Stack the stair runs so their plan footprints align "
                        "(overlap > "
                        f"{thr.stair_min_footprint_overlap_ratio * 100:.0f}%) "
                        "between consecutive levels."
                    ),
                )
            )
    return violations
