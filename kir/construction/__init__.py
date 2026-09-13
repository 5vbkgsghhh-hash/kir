"""A checkable construction site over the KIR building graph.

🔴 **A QUARANTINED EXPERIMENT, NOT A LOAD-BEARING CALCULATION CORE. READ THIS
BEFORE THE NAMES BELOW.** The owner's word, 2026-09-02. Measured the same day:
there is no crane body here as an object (counter-arrows — zero occurrences),
and ``_conflicts`` checks only the load's path, so ``feasible`` from here is
NOT a conclusion about the lift. The full breakdown with numbers is in the
docstring of :mod:`kir.construction.site`, first screen.

The module is INERT: nothing in the tracked code calls it except
``examples/construction_site.py``. The whole direction is in
``docs/laws/CONSTRUCTION_EXECUTION_SPEC.md``.

The first slice deliberately does not write temporary equipment into Revit. It
models resources and motion separately from the finished building: tower
cranes, material hoists, reach zones, and conservative trajectory checks.

The second slice — :mod:`kir.construction.schedule` — is a bounded site as a
DETERMINISTIC state model. It does not yield a conclusion about construction
safety, does not model real workers, and contains no cameras; the boundary is
written out in the module's docstring.

The seam between the slices was stitched on 2026-09-07: a delivery's duration
CAN be counted as a trajectory from :mod:`~kir.construction.site` (the
number's origin is named in every event by the ``duration_source`` field), a
zone is a convex polygon in mm, an intruder is a body with a time window, and
there can be several cranes and zones. None of these properties turns itself
on: until the kinematics, the polygon, and the rigging are declared, the model
stays as before and says ``declared``.
"""

from .site import (
    CONSTRUCTION_SCHEMA,
    CapacityBand,
    ConstructionError,
    CoverageAssessment,
    CoverageReport,
    CoverageState,
    CoverageTarget,
    CranePositionEvaluation,
    Feasibility,
    GeometryAuthority,
    HoistStop,
    HoistTripPlan,
    HoistTripRequest,
    LiftPlan,
    LiftRequest,
    MaterialHoist,
    MotionKeyframe,
    MotionSegment,
    Obstacle,
    ObstacleAuthority,
    ObstacleConflict,
    TowerCrane,
    analyze_crane_coverage,
    plan_hoist_trip,
    plan_tower_crane_lift,
    rank_crane_positions,
)

from .schedule import (
    REFUSAL_CODES,
    SCHEDULE_SCHEMA,
    STATE_SCHEMA,
    CraneEnvelope,
    Crew,
    Intrusion,
    Panel,
    PanelTiming,
    ScheduleEvent,
    ScheduleRefused,
    ScheduleResult,
    SitePlan,
    SiteSimulation,
    SiteState,
    Task,
    Unavailability,
    WorkZone,
    assign_crane,
    build_tasks,
    check_reach,
    deliver_duration,
    derived_windows,
    simulate_site,
    zone_of,
)

__all__ = (
    "CONSTRUCTION_SCHEMA",
    "CapacityBand",
    "ConstructionError",
    "CoverageAssessment",
    "CoverageReport",
    "CoverageState",
    "CoverageTarget",
    "CraneEnvelope",
    "CranePositionEvaluation",
    "Crew",
    "Feasibility",
    "GeometryAuthority",
    "HoistStop",
    "HoistTripPlan",
    "HoistTripRequest",
    "Intrusion",
    "LiftPlan",
    "LiftRequest",
    "MaterialHoist",
    "MotionKeyframe",
    "MotionSegment",
    "Obstacle",
    "ObstacleAuthority",
    "ObstacleConflict",
    "Panel",
    "PanelTiming",
    "REFUSAL_CODES",
    "SCHEDULE_SCHEMA",
    "STATE_SCHEMA",
    "ScheduleEvent",
    "ScheduleRefused",
    "ScheduleResult",
    "SitePlan",
    "SiteSimulation",
    "SiteState",
    "Task",
    "TowerCrane",
    "Unavailability",
    "WorkZone",
    "analyze_crane_coverage",
    "assign_crane",
    "build_tasks",
    "check_reach",
    "deliver_duration",
    "derived_windows",
    "plan_hoist_trip",
    "plan_tower_crane_lift",
    "rank_crane_positions",
    "simulate_site",
    "zone_of",
)
