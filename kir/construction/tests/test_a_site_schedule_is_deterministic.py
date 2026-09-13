"""Acceptance of the bounded construction site as a STATE model.

Every test here is an instrument with a number, not a judgment. The module's
boundary (the model gives no verdict on construction safety and does not
model real workers or cameras) is recorded in the docstring of
:mod:`kir.construction.schedule`; the test
``test_the_output_carries_no_verdict_beyond_the_schedule`` guards it from the
OUTPUT side: a forbidden word must not land in a single field.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from kir.construction import schedule as schedule_module
from kir.construction.schedule import (
    REFUSAL_CODES,
    CraneEnvelope,
    Crew,
    Panel,
    ScheduleRefused,
    SiteSimulation,
    SitePlan,
    SiteState,
    Unavailability,
    WorkZone,
    simulate_site,
)

CRANE = CraneEnvelope(id="TC-1", base_mm=(0.0, 0.0, 0.0),
                      min_radius_mm=2_000.0, max_radius_mm=20_000.0,
                      max_hook_z_mm=30_000.0)
CREW = Crew(id="CREW-A", size=4)
ZONE = WorkZone(id="ZONE-1")

#: One panel cycle: feed 600 + installation 900 + release 120.
CYCLE_S = 1_620.0
PANEL_COUNT = 6


def panels(count: int = PANEL_COUNT, **changes) -> tuple[Panel, ...]:
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
        values.update(changes)
        values["id"] = f"P{index}"
        out.append(Panel(**values))
    return tuple(out)


def plan(**changes) -> SitePlan:
    values = {"id": "SITE-6", "panels": panels(), "crane": CRANE,
              "crew": CREW, "zone": ZONE}
    values.update(changes)
    return SitePlan(**values)


def starts_of(result, kind: str) -> list[tuple[str, float]]:
    return [(event.task_id, event.time_s) for event in result.events
            if event.kind == "task_started" and event.task_id.startswith(kind)]


# ------------------------------------------------------ the happy path


def test_six_panels_run_in_order_and_end_at_a_named_time():
    result = simulate_site(plan())

    assert result.installation_order == ("P1", "P2", "P3", "P4", "P5", "P6")
    assert result.total_time_s == PANEL_COUNT * CYCLE_S == 9_720.0
    # 6 panels × (2 start/finish events per task × 3 tasks + 2 markers).
    assert len(result.events) == 48
    first, second = result.panels[0], result.panels[1]
    assert (first.deliver_start_s, first.install_end_s, first.released_s) == (
        0.0, 1_500.0, 1_620.0)
    # The zone is held by ONE panel: the next feed cannot start before release.
    assert second.deliver_start_s == first.released_s == 1_620.0
    busy = dict(result.resource_busy_s)
    assert busy == {"CREW-A": 5_400.0, "TC-1": 3_600.0, "ZONE-1": 9_720.0}
    assert result.reductions == ()


def test_the_crane_holds_the_delivery_and_the_crew_holds_the_install():
    result = simulate_site(plan())
    by_task = {event.task_id: event.resources for event in result.events
               if event.kind == "task_started"}

    assert by_task["deliver:P1"] == ("TC-1", "ZONE-1")
    assert by_task["install:P1"] == ("CREW-A", "ZONE-1")
    assert by_task["release:P1"] == ("ZONE-1",)
    # No feed overlaps another: there is a single crane.
    spans = [(item.deliver_start_s, item.deliver_end_s)
             for item in result.panels]
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert start >= end


def test_animation_follows_state_and_state_is_derived_from_events():
    result = simulate_site(plan())

    assert result.state_at(0.0)["panels"]["P1"] == "in_delivery"
    assert result.state_at(1_000.0)["panels"]["P1"] == "installing"
    assert result.state_at(1_550.0)["panels"]["P1"] == "installed"
    assert result.state_at(1_700.0)["panels"]["P1"] == "released"
    assert result.state_at(1_700.0)["zone_owner"] == "P2"
    assert result.state_at(9_720.0)["installed"] == [
        "P1", "P2", "P3", "P4", "P5", "P6"]


# --------------------------------------------------------- determinism


def test_two_runs_of_the_same_input_are_byte_identical():
    first = simulate_site(plan()).to_json().encode("utf-8")
    second = simulate_site(plan()).to_json().encode("utf-8")

    assert first == second
    assert len(first) > 2_000


# ------------------------------------------------------------- refusals


def test_a_cyclic_dependency_is_refused_by_name():
    cyclic = plan(extra_dependencies=(("install:P6", "deliver:P1"),))

    with pytest.raises(ScheduleRefused) as excinfo:
        simulate_site(cyclic)

    assert excinfo.value.reason == "cyclic_dependency"
    assert "deliver:P1" in excinfo.value.detail


def test_a_crane_without_the_reach_refuses_by_name_instead_of_lifting():
    far = list(panels())
    far[3] = Panel(id="P4", set_mm=(19_500.0, 0.0, 3_000.0), height_mm=2_800.0,
                   deliver_s=600.0, install_s=900.0, release_s=120.0,
                   plan_half_extent_mm=1_500.0)

    with pytest.raises(ScheduleRefused) as excinfo:
        simulate_site(plan(panels=tuple(far)))

    assert excinfo.value.reason == "panel_out_of_reach"
    assert "P4" in excinfo.value.detail
    assert "21000.0" in excinfo.value.detail  # 19500 + 1500 of envelope


def test_the_check_uses_the_promised_extent_not_the_load_point():
    """Control for the previous case: the same point without the promised
    envelope passes, and the reduced check is named, not hidden."""
    point_only = list(panels())
    point_only[3] = Panel(id="P4", set_mm=(19_500.0, 0.0, 3_000.0),
                          height_mm=2_800.0, deliver_s=600.0, install_s=900.0,
                          release_s=120.0, plan_half_extent_mm=None)

    result = simulate_site(plan(panels=tuple(point_only)))

    assert result.total_time_s == PANEL_COUNT * CYCLE_S
    assert result.reductions == ("panel_extent_not_promised:P4",)


def test_a_hook_ceiling_below_the_panel_refuses_by_name():
    low = CraneEnvelope(id="TC-1", base_mm=(0.0, 0.0, 0.0),
                        min_radius_mm=2_000.0, max_radius_mm=20_000.0,
                        max_hook_z_mm=5_000.0)

    with pytest.raises(ScheduleRefused) as excinfo:
        simulate_site(plan(crane=low))

    assert excinfo.value.reason == "panel_out_of_reach"
    assert "hook height" in excinfo.value.detail


# ------------------------------------ delay and obstacle move the outcome


def test_a_crane_delay_moves_the_schedule_and_is_visible_in_events():
    base = simulate_site(plan())
    delayed = simulate_site(plan(unavailabilities=(
        Unavailability(resource_id="TC-1", start_s=1_620.0, end_s=3_600.0,
                       cause="crane_maintenance"),)))

    assert delayed.total_time_s == base.total_time_s + 1_980.0 == 11_700.0
    assert delayed.panels[1].deliver_start_s == 3_600.0
    causes = {event.task_id: event.cause for event in delayed.events
              if event.kind == "task_started"}
    assert causes["deliver:P2"] == "unavailable:TC-1:crane_maintenance"
    # The order did not change; the schedule did.
    assert delayed.installation_order == base.installation_order


def test_an_outsider_in_the_zone_moves_the_schedule():
    base = simulate_site(plan())
    blocked = simulate_site(plan(unavailabilities=(
        Unavailability(resource_id="ZONE-1", start_s=2_000.0, end_s=2_500.0,
                       cause="outsider_occupies_zone"),)))

    assert blocked.total_time_s == base.total_time_s + 880.0 == 10_600.0
    assert blocked.panels[1].deliver_start_s == 2_500.0
    causes = {event.task_id: event.cause for event in blocked.events
              if event.kind == "task_started"}
    assert causes["deliver:P2"] == "unavailable:ZONE-1:outsider_occupies_zone"


# --------------------------------------------------------- pause and run


def test_pause_and_resume_equal_a_continuous_run_byte_for_byte():
    continuous = simulate_site(plan()).to_json().encode("utf-8")

    live = SiteSimulation(plan())
    state = live.pause(3_000.0)
    # State is DATA: it survives serialization to JSON and back.
    carried = SiteState.from_dict(json.loads(state.to_json()))
    assert carried == state
    resumed = SiteSimulation(plan()).resume(carried).to_json().encode("utf-8")

    assert resumed == continuous


def test_resume_does_not_reinstall_panels_installed_before_the_pause():
    live = SiteSimulation(plan())
    state = live.pause(4_000.0)
    installed_before = [event.task_id for event in state.events
                        if event.kind == "panel_installed"]
    assert installed_before == ["install:P1", "install:P2"]

    result = SiteSimulation(plan()).resume(state)

    installs = [event.task_id for event in result.events
                if event.kind == "task_started"
                and event.task_id.startswith("install:")]
    assert installs == sorted(set(installs))
    assert installs.count("install:P1") == 1
    assert installs.count("install:P2") == 1
    assert result.total_time_s == PANEL_COUNT * CYCLE_S


def test_a_state_from_another_plan_is_refused_by_name():
    state = SiteSimulation(plan()).pause(3_000.0)
    other = plan(id="SITE-OTHER")

    with pytest.raises(ScheduleRefused) as excinfo:
        SiteSimulation(other).resume(state)

    assert excinfo.value.reason == "state_does_not_match_plan"


def test_the_simulation_cannot_be_rewound():
    live = SiteSimulation(plan())
    live.pause(3_000.0)

    with pytest.raises(Exception) as excinfo:
        live.pause(100.0)

    assert "rewind" in str(excinfo.value)


# ------------------------------------------------------------- boundary


def test_the_output_carries_no_verdict_beyond_the_schedule():
    """The model speaks about the schedule and nothing else.

    There is no conclusion about construction safety here; therefore a
    forbidden word has no right to appear in a single output field.
    """
    result = simulate_site(plan(unavailabilities=(
        Unavailability(resource_id="TC-1", start_s=1_620.0, end_s=3_600.0,
                       cause="crane_maintenance"),)))
    payload = "\n".join((
        result.to_json(),
        json.dumps(result.state_at(2_000.0), ensure_ascii=False),
        SiteSimulation(plan()).pause(3_000.0).to_json(),
        json.dumps(plan().to_dict(), ensure_ascii=False),
    )).lower()

    for forbidden in ("safety", "safe", "безопас", "разрешено к подъёму"):
        assert forbidden not in payload


# =====================================================================
# Self-review "as a stranger" on 07.09: seven probes. Below is what they closed.
# =====================================================================


def test_a_pause_on_an_event_boundary_loses_and_doubles_nothing():
    """A pause exactly at an event's moment, at t=0, and at t=T.

    Probe: 21 points (19 distinct event times + 0 + T). An event has no
    right to fire twice or to vanish: event numbers stay a contiguous run,
    and the outcome matches the continuous run BYTE FOR BYTE.
    """
    reference = simulate_site(plan()).to_json().encode("utf-8")
    moments = sorted({event.time_s for event in simulate_site(plan()).events})
    assert len(moments) == 19
    points = moments + [0.0, PANEL_COUNT * CYCLE_S]

    for moment in points:
        state = SiteSimulation(plan()).pause(moment)
        resumed = SiteSimulation(plan()).resume(state)
        assert resumed.to_json().encode("utf-8") == reference, moment
        seqs = [event.seq for event in resumed.events]
        assert seqs == list(range(len(seqs))), moment
        assert len(seqs) == 48, moment


def test_the_panel_order_in_the_plan_is_the_erection_order():
    """Decision: the order of the panel list is an EXPLICIT part of the
    plan, not chance.

    The same set of panels in reverse order gives a reversed installation
    queue with the same total time. Determinism here does not depend on set
    traversal order: the schedule changes only because the INPUT changed.
    """
    forward = plan()
    backward = plan(panels=tuple(reversed(panels())))

    straight = simulate_site(forward)
    reversed_run = simulate_site(backward)

    assert straight.installation_order == ("P1", "P2", "P3", "P4", "P5", "P6")
    assert reversed_run.installation_order == ("P6", "P5", "P4", "P3", "P2", "P1")
    assert reversed_run.total_time_s == straight.total_time_s
    assert reversed_run.to_json() != straight.to_json()
    # The order is visible in the input, not only in the output.
    assert [p.id for p in backward.panels] == ["P6", "P5", "P4", "P3", "P2", "P1"]


def test_the_state_does_not_depend_on_mapping_order():
    state = SiteSimulation(plan()).pause(3_000.0)
    data = state.to_dict()
    shuffled = dict(reversed(list(data.items())))

    assert SiteState.from_dict(shuffled) == SiteState.from_dict(data) == state


def test_no_task_runs_through_an_unavailability_window():
    """There is no silent third option: a task either fits whole, or waits.

    The window ``[300, 500)`` begins IN THE MIDDLE of a feed that would
    otherwise run ``[0, 600)``. The feed neither tears nor goes "through" the
    window — it starts at 500.
    """
    window = Unavailability(resource_id="TC-1", start_s=300.0, end_s=500.0,
                            cause="mid_task_maintenance")
    result = simulate_site(plan(unavailabilities=(window,)))
    starts = {event.task_id: event.time_s for event in result.events
              if event.kind == "task_started"}
    ends = {event.task_id: event.time_s for event in result.events
            if event.kind == "task_finished"}

    assert starts["deliver:P1"] == 500.0
    assert result.total_time_s == 10_220.0
    crossing = [task_id for task_id, start in starts.items()
                if task_id.startswith("deliver:")
                and start < window.end_s and ends[task_id] > window.start_s]
    assert crossing == []


FORGERIES = {
    "completed_without_its_event": ("completed", "state_is_inconsistent"),
    "negative_now": ("now_s", "state_is_inconsistent"),
    "unknown_resource": ("resource_free_s", "state_does_not_match_plan"),
    "foreign_zone_owner": ("zone_owner", "state_does_not_match_plan"),
    "events_erased": ("events", "state_is_inconsistent"),
    "negative_seq": ("next_seq", "state_is_inconsistent"),
}


@pytest.mark.parametrize("case", sorted(FORGERIES))
def test_a_forged_state_is_refused_by_name(case):
    """A forged snapshot refuses BY NAME rather than crashing with a KeyError."""
    honest = SiteSimulation(plan()).pause(3_000.0).to_dict()
    data = json.loads(json.dumps(honest))
    if case == "completed_without_its_event":
        data["completed"] = sorted(set(data["completed"]) | {"install:P5"})
    elif case == "negative_now":
        data["now_s"] = -5.0
    elif case == "unknown_resource":
        data["resource_free_s"] = data["resource_free_s"] + [["GHOST-9", 10.0]]
    elif case == "foreign_zone_owner":
        data["zone_owner"] = "P99"
    elif case == "events_erased":
        data["events"] = []
    elif case == "negative_seq":
        data["next_seq"] = -3

    with pytest.raises(ScheduleRefused) as excinfo:
        state = SiteState.from_dict(data)
        SiteSimulation(plan()).resume(state)

    assert excinfo.value.reason == FORGERIES[case][1]
    assert excinfo.value.reason in REFUSAL_CODES


def test_the_refusal_list_is_closed_in_both_directions():
    """``REFUSAL_CODES`` is checked against the source, not the author's memory."""
    source = pathlib.Path(schedule_module.__file__).read_text(encoding="utf-8")
    raised = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "ScheduleRefused"
                and node.args and isinstance(node.args[0], ast.Constant)):
            raised.add(node.args[0].value)

    assert raised == set(REFUSAL_CODES)
    assert len(REFUSAL_CODES) == len(set(REFUSAL_CODES)) == 10


def test_resource_load_is_a_consequence_of_the_input_not_a_constant():
    """Occupancy numbers must follow from the durations, not merely coincide."""
    varied = tuple(Panel(id=f"P{index}",
                         set_mm=(6_000.0 + 900.0 * index, 4_000.0, 3_000.0),
                         height_mm=2_800.0, deliver_s=100.0 * index,
                         install_s=200.0 * index, release_s=30.0 * index,
                         plan_half_extent_mm=1_500.0)
                   for index in range(1, PANEL_COUNT + 1))
    result = simulate_site(plan(panels=varied))
    busy = dict(result.resource_busy_s)
    deliver = sum(item.deliver_s for item in varied)
    install = sum(item.install_s for item in varied)
    release = sum(item.release_s for item in varied)

    assert busy["TC-1"] == deliver == 2_100.0
    assert busy["CREW-A"] == install == 4_200.0
    assert busy["ZONE-1"] == result.total_time_s == 6_930.0
    assert result.total_time_s == deliver + install + release
    # The same instrument on the baseline: 6 × 600 / 6 × 900 / 6 × 1620.
    base = dict(simulate_site(plan()).resource_busy_s)
    assert base["TC-1"] == PANEL_COUNT * 600.0
    assert base["CREW-A"] == PANEL_COUNT * 900.0
    assert base["ZONE-1"] == PANEL_COUNT * CYCLE_S


def test_the_zone_is_held_by_the_panel_not_by_the_task():
    """An instrument for zone occupancy that distinguishes ownership from
    the sum of tasks.

    Probe 07.09: on the baseline both counts give 9720 and coincide by
    chance — there is not a single gap inside the panel there. The crew's
    window ``[600, 1200)`` splits the feed from the installation: the zone
    is occupied by panel P1 for the whole 2220 s, while its tasks occupy
    only 1620 s. The "by tasks" count turns red here.
    """
    result = simulate_site(plan(unavailabilities=(
        Unavailability(resource_id="CREW-A", start_s=600.0, end_s=1_200.0,
                       cause="crew_briefing"),)))
    busy = dict(result.resource_busy_s)
    first = result.panels[0]

    assert (first.deliver_end_s, first.install_start_s) == (600.0, 1_200.0)
    assert first.released_s == 2_220.0
    assert result.total_time_s == 10_320.0
    assert busy["ZONE-1"] == 10_320.0
    # The sum of task durations is strictly less than the zone's occupancy.
    tasks_only = PANEL_COUNT * CYCLE_S
    assert tasks_only == 9_720.0 < busy["ZONE-1"]
    # The crane and the crew did not change: it was the zone that was idle, not them.
    assert busy["TC-1"] == 3_600.0 and busy["CREW-A"] == 5_400.0
    assert result.state_at(900.0)["panels"]["P1"] == "delivered"
    assert result.state_at(900.0)["zone_owner"] == "P1"
