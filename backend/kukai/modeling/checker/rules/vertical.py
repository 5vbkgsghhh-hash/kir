"""Vertical-circulation rules (design §6): HAB011 stair geometry, HAB012 core continuity.

Pure functions over SpatialModel; no I/O, no mutation. Every numeric constant comes
from `thr` (Thresholds) — no magic numbers (design §11.4). Both rules are WARNING:
a stair that is too steep or a core that jogs between floors is probably wrong but does
not by itself make the building uninhabitable (design §6 severity model)."""
from __future__ import annotations

import networkx as nx
from shapely.geometry import Polygon

from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.spatial_model import SpatialModel, Severity, Violation, Stair
from kukai.modeling.checker.thresholds import Thresholds


def check_hab011(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB011 — stair geometry sane (run width / rise / going). WARNING.

    rise = (top_z - base_z) / riser_count; going = tread_depth_mm.

    v1: a stair whose riser_count or tread_depth_mm is None is SKIPPED silently.
    v2 (unknown ≠ pass): each MEASURED parameter is checked and a measured violation is
    BLOCKING (a 300 mm run is a fact, not a maybe); every UNMEASURED parameter — and
    every kind='inferred' pseudo-run — produces a per-stair 'cannot verify' WARNING
    instead of silence, and the engine's coverage counts the rule NOT_EVALUATED when no
    stair is fully measured.
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
        unmeasured: list[str] = []
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
                defects.append(
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
    """Intersection area / smaller polygon area, in [0, 1]. 0 if either is degenerate."""
    pa, pb = Polygon(a), Polygon(b)
    if not pa.is_valid or not pb.is_valid:
        return 0.0
    smaller = min(pa.area, pb.area)
    if smaller <= 0.0:
        return 0.0
    return pa.intersection(pb).area / smaller


def check_hab012(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB012 — stair-core continuous in plan between consecutive served levels. WARNING.

    For each pair of consecutive served levels (ordered by Level.index), the stair run
    based on the lower level must overlap the run based on the upper level by MORE than
    thr.stair_min_footprint_overlap_ratio of the smaller footprint. Otherwise the core
    jogs sideways between floors (design §6)."""
    violations: list[Violation] = []
    by_level = _stair_by_base_level(model)
    # Served levels = levels that base at least one stair run, ordered bottom→top.
    served = sorted(
        (lvl for lvl in model.levels if lvl.id in by_level),
        key=lambda lvl: lvl.index,
    )
    for lower, upper in zip(served, served[1:]):
        for s_low in by_level[lower.id]:
            for s_up in by_level[upper.id]:
                if not s_low.footprint or not s_up.footprint:
                    continue  # no plan footprint to compare
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
