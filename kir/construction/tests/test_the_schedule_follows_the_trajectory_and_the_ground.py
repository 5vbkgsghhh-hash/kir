"""Acceptance of the "geometry ↔ schedule" seam (mandate F9).

Every test here is an instrument with a NUMBER. Exactly four claims are
checked:

1. feed duration CAN BE A CONSEQUENCE of the trajectory, not only an input,
   and the number's origin is named in every event (``duration_source``);
2. the zone is a POLYGON, the foreign object is a BODY, and geometry
   decides the intersection;
3. two cranes with different reach zones give PARALLEL feeds, while a
   single work zone still holds ONE panel at a time;
4. determinism and ``pause``/``resume`` survive everything listed above.

The baseline plan from the neighboring file (9720 / 11700 / 10600 s)
deliberately stays on ``declared``: the trajectory-based path is SWITCHED ON
by declared kinematics, not silently swapped in for the previous numbers.
"""

from __future__ import annotations

import json

import pytest

from kir.clash import geom as G
from kir.construction.schedule import (
    ConstructionError,
    CraneEnvelope,
    Crew,
    Intrusion,
    Panel,
    ScheduleRefused,
    SiteSimulation,
    SitePlan,
    SiteState,
    WorkZone,
    simulate_site,
)
from kir.construction.site import (
    CapacityBand,
    Obstacle,
    ObstacleAuthority,
    TowerCrane,
)

# ----------------------------------------------------------------- baselines

#: A crane with DECLARED kinematics: speeds and the load chart.
TOWER = TowerCrane(
    id="TC-1", base_mm=(0.0, 0.0, 0.0), max_hook_height_mm=30_000.0,
    min_radius_mm=2_000.0,
    load_chart=(CapacityBand(10_000.0, 8_000.0),
                CapacityBand(20_000.0, 4_000.0)),
    hoist_speed_mm_s=500.0, trolley_speed_mm_s=800.0, slew_speed_deg_s=0.5)

KINEMATIC = CraneEnvelope.from_tower_crane(TOWER)
DECLARED = CraneEnvelope(id="TC-1", base_mm=(0.0, 0.0, 0.0),
                         min_radius_mm=2_000.0, max_radius_mm=20_000.0,
                         max_hook_z_mm=30_000.0)
CREW = Crew(id="CREW-A", size=4)

#: The zone polygon in mm: a rectangle covering P1…P3 with their envelope.
ZONE_POLYGON = ((4_000.0, 2_000.0), (10_500.0, 2_000.0),
                (10_500.0, 6_000.0), (4_000.0, 6_000.0))
ZONE_1 = WorkZone(id="ZONE-1", footprint_mm=ZONE_POLYGON,
                  z0_mm=0.0, z1_mm=8_000.0)

#: A body on the load path at a low routing level: cleared ONLY by lifting.
BLOCK = ((5_000.0, -9_000.0), (9_000.0, -9_000.0),
         (9_000.0, -5_000.0), (5_000.0, -5_000.0))
#: A body right at the sling point: not cleared by lifting at any level.
PILLAR = ((-1_500.0, -13_500.0), (1_500.0, -13_500.0),
          (1_500.0, -10_500.0), (-1_500.0, -10_500.0))

DECLARED_TOTAL_S = 9_720.0
TRAJECTORY_TOTAL_S = 7_534.663811
#: Feed of P1 along the trajectory: lift 2500 mm, slew 120.11°, boom-in reach.
P1_TRAJECTORY_S = 250.233124


def panels(count: int = 6, *, promise: bool = True, **changes):
    out = []
    for index in range(1, count + 1):
        values = {
            "id": f"P{index}",
            "set_mm": (6_000.0 + 900.0 * index, 4_000.0, 3_000.0),
            "height_mm": 2_800.0,
            "deliver_s": 600.0,
            "install_s": 900.0,
            "release_s": 120.0,
            "plan_half_extent_mm": 1_500.0,
        }
        if promise:
            values.update({"pickup_mm": (0.0, -12_000.0, 500.0),
                           "gross_load_kg": 3_000.0,
                           "load_radius_mm": 1_500.0})
        values.update(changes)
        values["id"] = f"P{index}"
        out.append(Panel(**values))
    return tuple(out)


def plan(**changes) -> SitePlan:
    values = {"id": "SITE-6", "panels": panels(), "crane": KINEMATIC,
              "crew": CREW, "zone": WorkZone(id="ZONE-1")}
    values.update(changes)
    return SitePlan(**values)


def deliveries(result) -> list[float]:
    return [round(item.deliver_end_s - item.deliver_start_s, 6)
            for item in result.panels]


def obstacle(footprint, z1, authority, name="OB-1") -> Obstacle:
    return Obstacle(id=name, hull=G.Prism(footprint, 0.0, z1),
                    authority=authority, label="temporary")


# ------------------------------------ 1. duration as a CONSEQUENCE of the path


def test_delivery_time_is_computed_from_the_trajectory_not_taken_from_input():
    """The feed number comes from ``site.py``, and it DIFFERS between panels."""
    walked = simulate_site(plan())
    declared = simulate_site(plan(crane=DECLARED))

    assert declared.total_time_s == DECLARED_TOTAL_S
    assert deliveries(declared) == [600.0] * 6
    assert all(item.deliver_source == "declared" for item in declared.panels)

    assert walked.total_time_s == TRAJECTORY_TOTAL_S
    assert all(item.deliver_source == "trajectory" for item in walked.panels)
    assert deliveries(walked) == [250.233124, 243.34206, 237.413754,
                                  232.23973, 227.663788, 223.771355]
    # Six DIFFERENT numbers: the duration follows the panel's geometry
    # instead of turning out to be one constant renamed "trajectory".
    assert len(set(deliveries(walked))) == 6
    assert dict(walked.resource_busy_s)["TC-1"] == 1_414.663811
    # The input did not change: the same panels declare the same 600 s.
    assert all(item.deliver_s == 600.0 for item in plan().panels)


def test_the_origin_of_every_duration_is_named_in_its_event():
    """``duration_source`` is a field of the event, not report prose."""
    events = simulate_site(plan()).events
    by_kind: dict[str, set[str]] = {}
    for event in events:
        by_kind.setdefault(event.task_id.split(":")[0], set()).add(
            event.duration_source)

    assert by_kind["deliver"] == {"trajectory"}
    assert by_kind["install"] == {"declared"}
    assert by_kind["release"] == {"declared"}
    assert {event.duration_source for event in events} == {
        "declared", "trajectory"}
    payload = json.loads(simulate_site(plan()).to_json())
    assert all("duration_source" in item for item in payload["events"])
    assert {item["deliver_source"] for item in payload["panels"]} == {
        "trajectory"}


def test_a_partial_promise_is_named_and_the_two_origins_live_side_by_side():
    """A panel without a promised sling point stays on the input number.

    AND SAYS SO: the reduction is named in ``reductions``, not hidden.
    """
    mixed = (panels(1)[0],
             Panel(id="P2", set_mm=(7_800.0, 4_000.0, 3_000.0),
                   height_mm=2_800.0, deliver_s=600.0, install_s=900.0,
                   release_s=120.0, plan_half_extent_mm=1_500.0),
             panels(3)[2])
    second = CraneEnvelope(id="TC-2", base_mm=(20_000.0, 0.0, 0.0),
                           min_radius_mm=2_000.0, max_radius_mm=12_000.0,
                           max_hook_z_mm=30_000.0)
    result = simulate_site(plan(panels=mixed, zone=ZONE_1,
                                extra_cranes=(second,),
                                extra_zones=(WorkZone(id="ZONE-2"),)))

    assert [item.deliver_source for item in result.panels] == [
        "trajectory", "declared", "trajectory"]
    assert deliveries(result) == [250.233124, 600.0, 237.413754]
    assert result.reductions == ("crane_kinematics_not_promised:TC-2",
                                 "panel_lift_not_promised:P2",
                                 "zone_footprint_not_promised:ZONE-2")


def test_an_obstacle_raises_the_travel_level_and_lengthens_every_delivery():
    """An obstacle changes the SCHEDULE, not just the output text."""
    clear = simulate_site(plan())
    blocked = simulate_site(plan(lift_obstacles=(
        obstacle(BLOCK, 6_000.0, ObstacleAuthority.EXACT_ZONE),)))

    assert blocked.total_time_s == 7_654.938258
    assert round(blocked.total_time_s - clear.total_time_s, 6) == 120.274447
    assert deliveries(blocked) == [270.278814, 263.387749, 257.459444,
                                   252.285419, 247.709477, 243.817355]
    # All six feeds grew longer by the same increment: the routing level
    # rose once, and the lift-and-lower paid for it twice.
    grew = [round(after - before, 3) for before, after
            in zip(deliveries(clear), deliveries(blocked))]
    assert grew == [20.046] * 6
    assert blocked.installation_order == clear.installation_order


@pytest.mark.parametrize("authority,reason", [
    (ObstacleAuthority.EXACT_ZONE, "lift_path_blocked"),
    (ObstacleAuthority.OUTER_ENVELOPE, "lift_feasibility_unknown"),
])
def test_a_path_that_cannot_be_timed_refuses_by_name(authority, reason):
    """Neither time nor silence: an impassable and UNKNOWN path is a refusal."""
    with pytest.raises(ScheduleRefused) as excinfo:
        simulate_site(plan(lift_obstacles=(
            obstacle(PILLAR, 28_000.0, authority, name="OB-MAST"),)))

    assert excinfo.value.reason == reason
    assert "P1" in excinfo.value.detail


@pytest.mark.parametrize("changes,reason,mark", [
    ({"gross_load_kg": 5_000.0}, "panel_over_capacity",
     "gross_load_exceeds_chart_at_worst_radius"),
    ({"pickup_mm": (0.0, -25_000.0, 500.0)}, "panel_out_of_reach",
     "pickup_outside_radial_reach"),
])
def test_a_lift_the_crane_cannot_make_refuses_by_name(changes, reason, mark):
    """The SLING point and mass are checked even though the set point is
    within the envelope."""
    # Control: the same panel without a promised sling point passes on the
    # input number.
    assert simulate_site(plan(panels=panels(promise=False))).total_time_s \
        == DECLARED_TOTAL_S

    with pytest.raises(ScheduleRefused) as excinfo:
        simulate_site(plan(panels=panels(**changes)))

    assert excinfo.value.reason == reason
    assert mark in excinfo.value.detail


# ---------------------------------- 2. the zone is a polygon, the foreign object is a body


def test_the_panel_must_lie_inside_the_zone_polygon():
    inside = simulate_site(plan(panels=panels(3), zone=ZONE_1))
    assert inside.total_time_s == 3_790.988938

    with pytest.raises(ScheduleRefused) as excinfo:
        simulate_site(plan(zone=ZONE_1))
    assert excinfo.value.reason == "panel_outside_zone"
    assert "P4" in excinfo.value.detail and "ZONE-1" in excinfo.value.detail

    # Control: without a polygon the zone stays a capacity-1 identifier, and
    # the same six panels pass. So it is the GEOMETRY that turns red, not
    # something else.
    assert simulate_site(plan()).total_time_s == TRAJECTORY_TOTAL_S


def test_the_containment_predicate_uses_the_extent_not_the_set_point():
    """The set point is in the zone but the envelope is not: a refusal must
    occur."""
    edge = Panel(id="P1", set_mm=(10_400.0, 4_000.0, 3_000.0),
                 height_mm=2_800.0, deliver_s=600.0, install_s=900.0,
                 release_s=120.0, plan_half_extent_mm=1_500.0)
    point = Panel(id="P1", set_mm=(10_400.0, 4_000.0, 3_000.0),
                  height_mm=2_800.0, deliver_s=600.0, install_s=900.0,
                  release_s=120.0, plan_half_extent_mm=None)

    with pytest.raises(ScheduleRefused) as excinfo:
        simulate_site(plan(crane=DECLARED, panels=(edge,), zone=ZONE_1))
    assert excinfo.value.reason == "panel_outside_zone"

    reduced = simulate_site(plan(crane=DECLARED, panels=(point,), zone=ZONE_1))
    assert reduced.total_time_s == 1_620.0
    assert reduced.reductions == ("panel_extent_not_promised:P1",)


def test_kinematics_that_disagree_with_the_envelope_are_refused():
    """Two truths about one crane are a source of silent divergence.

    The envelope would say one thing, the trajectory would be computed
    another way, and they would drift apart silently: reach is checked
    against the ring, time against the chart. That is why the declared
    kinematics must MATCH the declared envelope.
    """
    # Control: a consistent pair builds and works.
    assert CraneEnvelope.from_tower_crane(TOWER).kinematics is TOWER
    assert simulate_site(plan()).total_time_s == TRAJECTORY_TOTAL_S

    with pytest.raises(ConstructionError) as excinfo:
        CraneEnvelope(id="TC-1", base_mm=(0.0, 0.0, 0.0),
                      min_radius_mm=2_000.0, max_radius_mm=18_000.0,
                      max_hook_z_mm=30_000.0, kinematics=TOWER)
    assert "disagrees" in str(excinfo.value)

    with pytest.raises(ConstructionError):
        CraneEnvelope(id="TC-9", base_mm=(0.0, 0.0, 0.0),
                      min_radius_mm=2_000.0, max_radius_mm=20_000.0,
                      max_hook_z_mm=30_000.0, kinematics=TOWER)


def test_a_concave_zone_polygon_is_refused_before_it_can_lie():
    """The containment predicate holds only for a convex contour — and
    requires one."""
    with pytest.raises(ConstructionError) as excinfo:
        WorkZone(id="ZONE-X", z0_mm=0.0, z1_mm=1_000.0, footprint_mm=(
            (0.0, 0.0), (10_000.0, 0.0), (10_000.0, 10_000.0),
            (5_000.0, 5_000.0), (0.0, 10_000.0)))

    assert "convex" in str(excinfo.value)


def test_an_outsider_body_moves_the_schedule_by_geometry():
    """The foreign object is named a BODY; which zone it occupies is decided
    by intersection."""
    body = Intrusion(
        id="IN-1", z0_mm=0.0, z1_mm=2_000.0, start_s=200.0, end_s=900.0,
        cause="outsider_body_in_zone",
        footprint_mm=((9_000.0, 3_000.0), (12_000.0, 3_000.0),
                      (12_000.0, 5_000.0), (9_000.0, 5_000.0)))
    base = simulate_site(plan(panels=panels(3), zone=ZONE_1))
    hit = simulate_site(plan(panels=panels(3), zone=ZONE_1, intrusions=(body,)))

    assert hit.total_time_s == base.total_time_s + 900.0 == 4_690.988938
    causes = {event.task_id: event.cause for event in hit.events
              if event.kind == "task_started"}
    assert causes["deliver:P1"] == "unavailable:ZONE-1:outsider_body_in_zone"
    assert hit.panels[0].deliver_start_s == 900.0
    assert hit.reductions == ()
    # The body itself intersects the zone — that is a checkable NUMBER, not an opinion.
    assert G.signed_distance(body.prism, ZONE_1.prism) <= 0.0


def test_an_outsider_body_that_touches_no_zone_moves_nothing_and_says_so():
    """Control for the previous case: the same window, the body off to the
    side — no shift."""
    far = Intrusion(
        id="IN-2", z0_mm=0.0, z1_mm=2_000.0, start_s=200.0, end_s=900.0,
        cause="outsider_body_in_zone",
        footprint_mm=((90_000.0, 3_000.0), (92_000.0, 3_000.0),
                      (92_000.0, 5_000.0), (90_000.0, 5_000.0)))
    base = simulate_site(plan(panels=panels(3), zone=ZONE_1))
    missed = simulate_site(plan(panels=panels(3), zone=ZONE_1,
                                intrusions=(far,)))

    assert missed.total_time_s == base.total_time_s == 3_790.988938
    assert missed.reductions == ("intrusion_touches_no_zone:IN-2",)
    assert G.signed_distance(far.prism, ZONE_1.prism) > 0.0


# ------------------------------------------ 3. two cranes and two zones


def two_zone_plan(**changes) -> SitePlan:
    first = CraneEnvelope(id="TC-1", base_mm=(0.0, 0.0, 0.0),
                          min_radius_mm=2_000.0, max_radius_mm=12_000.0,
                          max_hook_z_mm=30_000.0)
    second = CraneEnvelope(id="TC-2", base_mm=(20_000.0, 0.0, 0.0),
                           min_radius_mm=2_000.0, max_radius_mm=12_000.0,
                           max_hook_z_mm=30_000.0)
    zone_two = WorkZone(id="ZONE-2", z0_mm=0.0, z1_mm=8_000.0, footprint_mm=(
        (11_000.0, 2_000.0), (16_500.0, 2_000.0),
        (16_500.0, 6_000.0), (11_000.0, 6_000.0)))

    def panel(index: int, x: float, zone: str | None) -> Panel:
        return Panel(id=f"P{index}", set_mm=(x, 4_000.0, 3_000.0),
                     height_mm=2_800.0, deliver_s=600.0, install_s=900.0,
                     release_s=120.0, plan_half_extent_mm=1_500.0,
                     zone_id=zone)

    zoned = changes.pop("zoned", True)
    near = [panel(index, 6_000.0 + 900.0 * index, "ZONE-1" if zoned else None)
            for index in (1, 2, 3)]
    far = [panel(index, 13_000.0 + 900.0 * (index - 4),
                 "ZONE-2" if zoned else None) for index in (4, 5, 6)]
    values = {"id": "SITE-2C", "panels": tuple(near + far), "crane": first,
              "crew": CREW, "extra_cranes": (second,),
              "zone": ZONE_1 if zoned else WorkZone(id="ZONE-1"),
              "extra_zones": (zone_two,) if zoned else ()}
    values.update(changes)
    return SitePlan(**values)


def test_two_cranes_with_two_zones_deliver_in_parallel():
    result = simulate_site(two_zone_plan())
    spans = sorted((item.deliver_start_s, item.deliver_end_s)
                   for item in result.panels)
    overlaps = [(a, b) for (a, b), (c, _d) in zip(spans, spans[1:]) if c < b]

    assert result.total_time_s == 6_120.0
    assert overlaps == [(0.0, 600.0)]
    assert [(item.panel_id, item.crane_id, item.zone_id)
            for item in result.panels] == [
        ("P1", "TC-1", "ZONE-1"), ("P2", "TC-1", "ZONE-1"),
        ("P3", "TC-1", "ZONE-1"), ("P4", "TC-2", "ZONE-2"),
        ("P5", "TC-2", "ZONE-2"), ("P6", "TC-2", "ZONE-2")]
    assert dict(result.resource_busy_s) == {
        "CREW-A": 5_400.0, "TC-1": 1_800.0, "TC-2": 1_800.0,
        "ZONE-1": 5_220.0, "ZONE-2": 6_120.0}
    assert result.state_at(300.0)["zone_owners"] == {
        "ZONE-1": "P1", "ZONE-2": "P4"}
    assert result.state_at(300.0)["zone_owner"] == "P1"


def test_one_zone_still_holds_one_panel_even_with_two_cranes():
    """Control for parallelism: the same two cranes, one zone — a queue."""
    result = simulate_site(two_zone_plan(zoned=False))
    spans = sorted((item.deliver_start_s, item.deliver_end_s)
                   for item in result.panels)

    assert result.total_time_s == DECLARED_TOTAL_S
    assert [(a, b) for (a, b), (c, _d) in zip(spans, spans[1:]) if c < b] == []
    assert [item.crane_id for item in result.panels] == [
        "TC-1", "TC-1", "TC-1", "TC-2", "TC-2", "TC-2"]
    assert dict(result.resource_busy_s)["ZONE-1"] == DECLARED_TOTAL_S
    assert result.zones == ("ZONE-1",)


def test_the_panel_takes_the_first_crane_that_reaches_it():
    far = Panel(id="P4", set_mm=(13_000.0, 4_000.0, 3_000.0),
                height_mm=2_800.0, deliver_s=600.0, install_s=900.0,
                release_s=120.0, plan_half_extent_mm=1_500.0)
    first = CraneEnvelope(id="TC-1", base_mm=(0.0, 0.0, 0.0),
                          min_radius_mm=2_000.0, max_radius_mm=12_000.0,
                          max_hook_z_mm=30_000.0)
    second = CraneEnvelope(id="TC-2", base_mm=(20_000.0, 0.0, 0.0),
                           min_radius_mm=2_000.0, max_radius_mm=12_000.0,
                           max_hook_z_mm=30_000.0)
    zone = WorkZone(id="ZONE-1")

    with pytest.raises(ScheduleRefused) as alone:
        simulate_site(SitePlan(id="ONE", panels=(far,), crane=first,
                               crew=CREW, zone=zone))
    assert alone.value.reason == "panel_out_of_reach"

    paired = simulate_site(SitePlan(id="TWO", panels=(far,), crane=first,
                                    crew=CREW, zone=zone,
                                    extra_cranes=(second,)))
    assert paired.panels[0].crane_id == "TC-2"
    assert dict(paired.resource_busy_s) == {
        "CREW-A": 900.0, "TC-1": 0.0, "TC-2": 600.0, "ZONE-1": 1_620.0}

    unreachable = Panel(id="P9", set_mm=(40_000.0, 0.0, 3_000.0),
                        height_mm=2_800.0, deliver_s=600.0, install_s=900.0,
                        release_s=120.0, plan_half_extent_mm=1_500.0)
    with pytest.raises(ScheduleRefused) as neither:
        simulate_site(SitePlan(id="NONE", panels=(unreachable,), crane=first,
                               crew=CREW, zone=zone, extra_cranes=(second,)))
    # The detail carries the reason for EVERY crane, not just the last one polled.
    assert neither.value.reason == "panel_out_of_reach"
    assert "TC-1:" in neither.value.detail and "TC-2:" in neither.value.detail


# ------------------------------ 4. determinism, pause, and the shape of state


def test_the_trajectory_run_is_byte_identical_and_survives_every_pause():
    reference = simulate_site(plan()).to_json().encode("utf-8")
    assert simulate_site(plan()).to_json().encode("utf-8") == reference

    moments = sorted({event.time_s for event in simulate_site(plan()).events})
    assert len(moments) == 19
    for moment in moments + [0.0, TRAJECTORY_TOTAL_S]:
        state = SiteSimulation(plan()).pause(moment)
        carried = SiteState.from_dict(json.loads(state.to_json()))
        assert carried == state, moment
        resumed = SiteSimulation(plan()).resume(carried)
        assert resumed.to_json().encode("utf-8") == reference, moment


def test_two_zones_survive_pause_and_resume_byte_for_byte():
    reference = simulate_site(two_zone_plan()).to_json().encode("utf-8")
    state = SiteSimulation(two_zone_plan()).pause(1_000.0)

    assert state.zone_owner == (("ZONE-1", "P1"), ("ZONE-2", "P4"))
    carried = SiteState.from_dict(json.loads(state.to_json()))
    assert carried == state
    assert SiteSimulation(two_zone_plan()).resume(
        carried).to_json().encode("utf-8") == reference


@pytest.mark.parametrize("forgery,reason", [
    ("legacy_scalar", "state_does_not_match_plan"),
    ("unknown_zone", "state_does_not_match_plan"),
    ("foreign_owner", "state_does_not_match_plan"),
    ("owner_without_events", "state_is_inconsistent"),
])
def test_a_state_of_the_previous_shape_is_refused_by_name(forgery, reason):
    """The old snapshot shape — one field for all zones — is not
    reinterpreted."""
    honest = SiteSimulation(two_zone_plan()).pause(1_000.0).to_dict()
    data = json.loads(json.dumps(honest))
    if forgery == "legacy_scalar":
        data["zone_owner"] = "P1"
    elif forgery == "unknown_zone":
        data["zone_owner"] = dict(data["zone_owner"], **{"ZONE-9": None})
    elif forgery == "foreign_owner":
        data["zone_owner"] = dict(data["zone_owner"], **{"ZONE-2": "P99"})
    elif forgery == "owner_without_events":
        data["zone_owner"] = dict(data["zone_owner"], **{"ZONE-2": None})

    with pytest.raises(ScheduleRefused) as excinfo:
        state = SiteState.from_dict(data)
        SiteSimulation(two_zone_plan()).resume(state)

    assert excinfo.value.reason == reason


def test_the_new_output_still_carries_no_verdict_beyond_the_schedule():
    """The module's boundary did not expand along with the geometry."""
    result = simulate_site(plan(zone=ZONE_1, panels=panels(3), intrusions=(
        Intrusion(id="IN-1", z0_mm=0.0, z1_mm=2_000.0, start_s=200.0,
                  end_s=900.0, cause="outsider_body_in_zone",
                  footprint_mm=((9_000.0, 3_000.0), (12_000.0, 3_000.0),
                                (12_000.0, 5_000.0), (9_000.0, 5_000.0))),)))
    payload = "\n".join((
        result.to_json(),
        json.dumps(result.state_at(1_000.0), ensure_ascii=False),
        SiteSimulation(two_zone_plan()).pause(1_000.0).to_json(),
        json.dumps(two_zone_plan().to_dict(), ensure_ascii=False),
    )).lower()

    for forbidden in ("safety", "safe", "безопас", "разрешено к подъёму"):
        assert forbidden not in payload
