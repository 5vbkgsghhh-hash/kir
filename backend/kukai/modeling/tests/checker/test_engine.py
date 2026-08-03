"""Engine orchestration tests (design §2/§11).

run(model, thr=THRESHOLDS) builds the graph once, runs the full RULE_REGISTRY,
aggregates Violations, bins them by severity, and sets passed = (no BLOCKING). The GOOD
fixture passes with zero BLOCKING; each BAD fixture trips its target rule (design §7).

Every `bad_*` mutator is IMPORTED from fixtures/builders.py (single definition site,
D4) — never redefined here. build_graph lives in graph.py; the engine module only
exposes `run` + `RULE_REGISTRY` (D9)."""
import pytest

from kukai.modeling.checker import engine
from kukai.modeling.checker.engine import RULE_REGISTRY, run
from kukai.modeling.checker.spatial_model import (
    CheckReport,
    Severity,
    SpatialModel,
    Violation,
)
from kukai.modeling.checker.fixtures.builders import (
    make_good,
    bad_room_no_door,
    bad_apartment_into_apartment,
    bad_no_egress_stair,
    bad_floating_floor,
    bad_steep_stair,
    bad_discontinuous_core,
    bad_tiny_bedroom,
    bad_narrow_corridor,
    bad_low_ceiling,
    bad_bedroom_no_window,
    bad_low_daylight,
    bad_overlapping_rooms,
    bad_door_in_wall,
    bad_open_envelope,
    bad_floating_column,
)


# ---------- registry shape ----------

def test_registry_is_the_sixteen_hab_rules_in_order():
    ids = [fn.__name__ for fn in RULE_REGISTRY]
    assert ids == [
        "check_hab001", "check_hab002", "check_hab003", "check_hab004", "check_hab010",
        "check_hab011", "check_hab012",
        "check_hab020", "check_hab021", "check_hab022",
        "check_hab030", "check_hab031",
        "check_hab040", "check_hab041", "check_hab042",
        "check_hab050",
    ]


def test_registry_has_no_duplicate_rules():
    assert len(RULE_REGISTRY) == len({fn.__name__ for fn in RULE_REGISTRY})


# ---------- happy path ----------

def test_run_good_passes_with_zero_blocking():
    report = run(SpatialModel.model_validate(make_good()))
    assert isinstance(report, CheckReport)
    assert report.passed is True
    assert report.blocking == []


def test_run_is_pure_does_not_mutate_input():
    model = SpatialModel.model_validate(make_good())
    before = model.model_dump()
    run(model)
    assert model.model_dump() == before          # frozen + pure: no mutation


def test_run_returns_consistent_report():
    # passed must be exactly equivalent to "no blocking" (CheckReport invariant).
    report = run(SpatialModel.model_validate(make_good()))
    assert report.passed == (len(report.blocking) == 0)


def test_run_bins_violations_by_severity():
    # Every violation in each bucket carries that bucket's severity.
    report = run(SpatialModel.model_validate(bad_tiny_bedroom()))
    assert all(v.severity is Severity.BLOCKING for v in report.blocking)
    assert all(v.severity is Severity.WARNING for v in report.warnings)
    assert all(v.severity is Severity.INFO for v in report.info)


# ---------- the integration matrix: each BAD fixture trips its target rule ----------

# (mutator, target rule_id, target severity) — design §7 + the rule tasks (D7).
# ONE row per registry rule that has a dedicated fixture: all 16 rules covered.
#
# Two egress subtleties are nailed down here:
#   * bad_no_egress_stair runs on the single-level base — removing stairs leaves L0 a
#     ground level, so HAB010 stays SILENT and the egress-to-stair rule HAB003 fires
#     (BLOCKING).
#   * bad_floating_floor is the genuinely multi-level case where a non-ground occupied
#     level loses its floor/egress → HAB010 (BLOCKING).
#
# Severity column = the documented severity of THIS rule's violation on THIS fixture:
#   * HAB031 (low daylight) is INFO-only; the fixture trips no BLOCKING rule, so the
#     building still "passes" (passed stays True) — covered by the invariant test below.
#   * HAB011 / HAB012 / HAB021 / HAB022 / HAB041 / HAB042 / HAB050 are WARNING.
_BAD_CASES = [
    (bad_room_no_door, "HAB001", Severity.BLOCKING),
    (bad_apartment_into_apartment, "HAB002", Severity.BLOCKING),
    (bad_no_egress_stair, "HAB003", Severity.BLOCKING),
    (bad_room_no_door, "HAB004", Severity.BLOCKING),
    (bad_floating_floor, "HAB010", Severity.BLOCKING),
    (bad_steep_stair, "HAB011", Severity.WARNING),
    (bad_discontinuous_core, "HAB012", Severity.WARNING),
    (bad_tiny_bedroom, "HAB020", Severity.BLOCKING),
    (bad_narrow_corridor, "HAB021", Severity.WARNING),
    (bad_low_ceiling, "HAB022", Severity.WARNING),
    (bad_bedroom_no_window, "HAB030", Severity.BLOCKING),
    (bad_low_daylight, "HAB031", Severity.INFO),
    (bad_overlapping_rooms, "HAB040", Severity.BLOCKING),
    (bad_door_in_wall, "HAB041", Severity.WARNING),
    (bad_open_envelope, "HAB042", Severity.WARNING),
    (bad_floating_column, "HAB050", Severity.WARNING),
]

# The fixtures whose target rule is NOT blocking AND which must not incidentally trip
# any BLOCKING rule — the building still "passes" (design §6: passed ⇔ no BLOCKING).
_WARNING_OR_INFO_ONLY = [
    bad_steep_stair,         # HAB011 WARNING
    bad_discontinuous_core,  # HAB012 WARNING
    bad_narrow_corridor,     # HAB021 WARNING
    bad_low_ceiling,         # HAB022 WARNING
    bad_low_daylight,        # HAB031 INFO
    bad_door_in_wall,        # HAB041 WARNING
    bad_open_envelope,       # HAB042 WARNING
    bad_floating_column,     # HAB050 WARNING
]


def _all_violations(report: CheckReport) -> list[Violation]:
    return [*report.blocking, *report.warnings, *report.info]


@pytest.mark.parametrize(
    "mutator,rule_id,severity",
    _BAD_CASES,
    ids=[f"{m.__name__}->{rid}" for m, rid, _ in _BAD_CASES],
)
def test_each_bad_fixture_trips_its_target_rule(mutator, rule_id, severity):
    report = run(SpatialModel.model_validate(mutator()))
    fired = {v.rule_id for v in _all_violations(report)}
    assert rule_id in fired, f"{mutator.__name__} did not trip {rule_id}; fired={sorted(fired)}"
    # The fired violation carries the documented severity for this fixture.
    target = next(v for v in _all_violations(report) if v.rule_id == rule_id)
    assert target.severity is severity
    # A BLOCKING-target fixture must make the whole report fail; otherwise the report's
    # passed flag stays exactly equivalent to "no blocking" (design §6).
    if severity is Severity.BLOCKING:
        assert report.passed is False
    else:
        assert report.passed == (len(report.blocking) == 0)


@pytest.mark.parametrize(
    "mutator",
    _WARNING_OR_INFO_ONLY,
    ids=[m.__name__ for m in _WARNING_OR_INFO_ONLY],
)
def test_warning_or_info_only_fixtures_leave_building_passing(mutator):
    # A fixture whose only defect is WARNING/INFO must NOT raise a BLOCKING violation —
    # the building still passes (design §6). Guards against a rule mis-classifying its
    # severity or a WARNING/INFO fixture incidentally breaking a structural invariant.
    report = run(SpatialModel.model_validate(mutator()))
    assert report.blocking == [], (
        f"{mutator.__name__} unexpectedly produced BLOCKING violations: "
        f"{[v.rule_id for v in report.blocking]}"
    )
    assert report.passed is True


def test_empty_model_surfaces_emptiness_not_silent_pass():
    # review fix: an empty / failed extraction must surface (INFO HAB000), not just read clean.
    rep = run(SpatialModel(building_id="empty"))
    assert rep.passed is True            # no design ERROR, so technically passes…
    assert any(v.rule_id == "HAB000" for v in rep.info)   # …but the emptiness is flagged
    assert rep.blocking == []
