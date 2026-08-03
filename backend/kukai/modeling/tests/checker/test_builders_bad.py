"""Guard suite for the bad mutators (design §7): each breaks a RULE, not the schema.

Every bad_* must (a) still validate as a SpatialModel, (b) differ from make_good() only in the one
thing it targets, and (c) be deepcopy-isolated (two calls equal but not identical). Rule-firing is
asserted in each rule's own test file; here we prove the fixtures stay structurally valid and
isolated so a rule test cannot be fooled by a schema break or by cross-test mutation."""
import copy

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
from kukai.modeling.checker.spatial_model import SpatialModel


def _parses(d: dict) -> SpatialModel:
    """A bad fixture must STILL be a valid SpatialModel (only a rule is violated)."""
    return SpatialModel.model_validate(d)


def _room(d: dict, room_id: str) -> dict:
    return next(r for r in d["rooms"] if r["id"] == room_id)


def test_room_no_door_still_parses_and_isolates_wc():
    good = make_good()
    bad = bad_room_no_door()
    model = _parses(bad)
    assert isinstance(model, SpatialModel)
    # the санузел 'wc' loses EVERY door touching it (it is the isolated room) — its only door
    # in GOOD is d_kit_wc, so exactly one door is removed; nothing else changes.
    assert len(bad["doors"]) == len(good["doors"]) - 1
    assert {r["id"] for r in bad["rooms"]} == {r["id"] for r in good["rooms"]}
    assert "wc" not in {d["from_room_id"] for d in bad["doors"]}
    assert "wc" not in {d["to_room_id"] for d in bad["doors"]}


def test_apartment_into_apartment_still_parses_and_adds_nested_A2():
    good = make_good()
    bad = bad_apartment_into_apartment()
    _parses(bad)
    # a second apartment A2 (hall2 + bed2) is reachable ONLY through A1's прихожая — its only
    # entrance door connects A1.hall ↔ A2.hall2, so A2 nests inside A1 (HAB002 branch (a)).
    apt_ids = {r.get("apartment_id") for r in bad["rooms"]}
    assert "A2" in apt_ids
    assert "A2" not in {r.get("apartment_id") for r in good["rooms"]}
    assert {"hall2", "bed2"} <= {r["id"] for r in bad["rooms"]}
    # the bridging door connects an A1 room to an A2 room (different non-null apartment ids).
    bridge = next(dr for dr in bad["doors"] if dr["id"] == "d_hall_hall2")
    assert {bridge["from_room_id"], bridge["to_room_id"]} == {"hall", "hall2"}


def test_no_egress_stair_still_parses_and_removes_all_stairs():
    bad = bad_no_egress_stair()
    model = _parses(bad)
    assert model.stairs == []
    # rooms/doors otherwise untouched: only the stair run(s) and the stair-room wiring are gone.
    assert {r["id"] for r in bad["rooms"]} == {r["id"] for r in make_good()["rooms"]}


def test_floating_floor_still_parses_and_adds_unreachable_level():
    good = make_good()
    bad = bad_floating_floor()
    model = _parses(bad)
    # a new occupied level L1 exists with at least one room, but NO stair reaches it.
    assert len(model.levels) == len(good["levels"]) + 1
    upper_levels = {lvl["id"] for lvl in bad["levels"]} - {lvl["id"] for lvl in good["levels"]}
    assert upper_levels  # a brand-new level id
    upper_id = next(iter(upper_levels))
    assert any(r["level_id"] == upper_id for r in bad["rooms"])
    assert all(
        upper_id not in (s["base_level_id"], s["top_level_id"]) for s in bad["stairs"]
    )


def test_steep_stair_still_parses_and_only_changes_stair_geometry():
    good = make_good()
    bad = bad_steep_stair()
    model = _parses(bad)
    assert len(model.stairs) == len(good["stairs"])      # same number of runs
    s_good, s_bad = good["stairs"][0], bad["stairs"][0]
    # only run width / riser_count / tread_depth / z-span changed; rooms+doors untouched.
    assert s_bad["run_width_mm"] < s_good["run_width_mm"]
    assert s_bad["tread_depth_mm"] < s_good["tread_depth_mm"]
    assert (s_bad["top_z"] - s_bad["base_z"]) / s_bad["riser_count"] > 180.0
    assert {r["id"] for r in bad["rooms"]} == {r["id"] for r in good["rooms"]}
    assert {d["id"] for d in bad["doors"]} == {d["id"] for d in good["doors"]}


def test_discontinuous_core_still_parses_and_adds_a_jogged_second_run():
    good = make_good()
    bad = bad_discontinuous_core()
    model = _parses(bad)
    # a second served level + a second stair run whose footprint is shifted off the first.
    assert len(model.levels) == len(good["levels"]) + 1
    assert len(model.stairs) == len(good["stairs"]) + 1
    base_fp = bad["stairs"][0]["footprint"]
    upper_fp = bad["stairs"][1]["footprint"]
    assert base_fp != upper_fp
    # both runs keep SANE geometry so HAB011 stays silent (only HAB012 should fire).
    for s in bad["stairs"]:
        assert s["run_width_mm"] >= 1000.0
        assert s["tread_depth_mm"] >= 250.0
        assert (s["top_z"] - s["base_z"]) / s["riser_count"] <= 180.0


def test_tiny_bedroom_still_parses_and_only_shrinks_bedroom_area():
    good = make_good()
    bad = bad_tiny_bedroom()
    _parses(bad)
    assert _room(bad, "bed")["area_m2"] == 4.0          # below 8 m² жилая minimum
    assert _room(bad, "bed")["area_m2"] < _room(good, "bed")["area_m2"]
    # every OTHER room keeps its good area (exactly one thing changed).
    for r_good in good["rooms"]:
        if r_good["id"] != "bed":
            assert _room(bad, r_good["id"])["area_m2"] == r_good["area_m2"]


def test_narrow_corridor_still_parses_and_only_narrows_corridor():
    good = make_good()
    bad = bad_narrow_corridor()
    _parses(bad)
    cor = _room(bad, "cor")
    # boundary collapses the corridor to ~700 mm wide (< 900 mm коридор minimum).
    xs = [pt[0] for pt in cor["boundary"]]
    assert (max(xs) - min(xs)) <= 700.0
    # area was reduced consistently with the narrower footprint; other rooms unchanged.
    assert cor["area_m2"] < _room(good, "cor")["area_m2"]


def test_low_ceiling_still_parses_and_only_lowers_one_height():
    good = make_good()
    bad = bad_low_ceiling()
    _parses(bad)
    assert _room(bad, "bed")["height_mm"] == 2200.0     # below 2500 mm minimum
    assert _room(bad, "bed")["height_mm"] < _room(good, "bed")["height_mm"]
    for r_good in good["rooms"]:
        if r_good["id"] != "bed":
            assert _room(bad, r_good["id"])["height_mm"] == r_good["height_mm"]


def test_bedroom_no_window_still_parses_and_strips_only_the_bedroom_window():
    good = make_good()
    bad = bad_bedroom_no_window()
    _parses(bad)
    bed = _room(bad, "bed")
    assert bed["has_window"] is False
    assert bed["window_area_m2"] == 0.0
    # the windows[] entry is removed too (model stays self-consistent).
    assert "w_bed" not in {w["id"] for w in bad["windows"]}
    assert "w_bed" in {w["id"] for w in good["windows"]}
    # other rooms keep their windows.
    assert _room(bad, "kit")["has_window"] is True


def test_low_daylight_still_parses_and_only_shrinks_bedroom_glazing():
    good = make_good()
    bad = bad_low_daylight()
    _parses(bad)
    bed = _room(bad, "bed")
    # the спальня KEEPS a window (so HAB030 stays silent) but its glazing ratio drops below
    # 1:8 → 1.0 / 14.0 = 0.071 < 0.125 (HAB031, INFO).
    assert bed["has_window"] is True
    assert bed["window_area_m2"] == 1.0
    assert bed["window_area_m2"] / bed["area_m2"] < 0.125
    # the windows[] entry shrinks consistently (model stays self-consistent).
    w_bed = next(w for w in bad["windows"] if w["id"] == "w_bed")
    assert w_bed["area_m2"] == 1.0
    # GOOD bedroom glazing was healthy (>1:8); only this one ratio changed.
    assert _room(good, "bed")["window_area_m2"] / _room(good, "bed")["area_m2"] >= 0.125


def test_overlapping_rooms_still_parses_and_overlaps_two_footprints():
    good = make_good()
    bad = bad_overlapping_rooms()
    _parses(bad)
    # the спальня boundary is moved to overlap the кухня-гостиная by > 0.05 m².
    assert _room(bad, "bed")["boundary"] != _room(good, "bed")["boundary"]
    # same set of rooms — only a boundary moved (no room added/removed).
    assert {r["id"] for r in bad["rooms"]} == {r["id"] for r in good["rooms"]}


def test_door_in_wall_still_parses_and_adds_a_door_into_blank_wall():
    good = make_good()
    bad = bad_door_in_wall()
    _parses(bad)
    # exactly one door added that swings into a wall: no rooms, not exterior.
    assert len(bad["doors"]) == len(good["doors"]) + 1
    new_ids = {dr["id"] for dr in bad["doors"]} - {dr["id"] for dr in good["doors"]}
    assert len(new_ids) == 1
    new_door = next(dr for dr in bad["doors"] if dr["id"] in new_ids)
    assert new_door["from_room_id"] is None
    assert new_door["to_room_id"] is None
    assert new_door["is_exterior"] is False
    # rooms untouched.
    assert {r["id"] for r in bad["rooms"]} == {r["id"] for r in good["rooms"]}


def test_open_envelope_still_parses_and_removes_all_walls():
    good = make_good()
    bad = bad_open_envelope()
    model = _parses(bad)
    # every wall is removed → the apartment envelope is fully open (HAB042).
    assert model.walls == []
    assert good["walls"]  # GOOD had walls to begin with
    # rooms/doors/windows untouched: only the walls[] list emptied.
    assert {r["id"] for r in bad["rooms"]} == {r["id"] for r in good["rooms"]}
    assert {dr["id"] for dr in bad["doors"]} == {dr["id"] for dr in good["doors"]}


def test_floating_column_still_parses_and_adds_a_midair_structural_wall():
    good = make_good()
    bad = bad_floating_column()
    model = _parses(bad)
    # exactly one structural wall added that does NOT reach the ground level.
    assert len(model.walls) == len(good["walls"]) + 1
    new_ids = {w["id"] for w in bad["walls"]} - {w["id"] for w in good["walls"]}
    assert len(new_ids) == 1
    new_wall = next(w for w in bad["walls"] if w["id"] in new_ids)
    assert new_wall["is_structural"] is True
    assert new_wall["level_id"] != "L0"   # hosted on an upper level with nothing beneath


def test_all_fifteen_bad_mutators_are_distinct_valid_models():
    # sanity sweep: every mutator yields a parseable model that DIFFERS from make_good().
    good = make_good()
    mutators = [
        bad_room_no_door, bad_apartment_into_apartment,
        bad_no_egress_stair, bad_floating_floor,
        bad_steep_stair, bad_discontinuous_core,
        bad_tiny_bedroom, bad_narrow_corridor, bad_low_ceiling,
        bad_bedroom_no_window, bad_low_daylight,
        bad_overlapping_rooms, bad_door_in_wall, bad_open_envelope,
        bad_floating_column,
    ]
    assert len(mutators) == 15
    for m in mutators:
        d = m()
        _parses(d)              # still a valid SpatialModel
        assert d != good        # exactly one thing broke vs the baseline


def test_every_bad_mutator_is_deepcopy_isolated():
    # pytest-randomly safety: two successive calls must be EQUAL but NOT the same object, and
    # mutating one returned dict must never poison make_good() or a later call.
    good = make_good()
    mutators = [
        bad_room_no_door, bad_apartment_into_apartment,
        bad_no_egress_stair, bad_floating_floor,
        bad_steep_stair, bad_discontinuous_core,
        bad_tiny_bedroom, bad_narrow_corridor, bad_low_ceiling,
        bad_bedroom_no_window, bad_low_daylight,
        bad_overlapping_rooms, bad_door_in_wall, bad_open_envelope,
        bad_floating_column,
    ]
    assert len(mutators) == 15
    for m in mutators:
        a = m()
        b = m()
        assert a == b                 # deterministic
        assert a is not b             # distinct objects (deepcopy isolation)
        assert a["rooms"] is not b["rooms"]   # nested containers are copies too
        a["rooms"][0]["name"] = "POISON"
        assert m()["rooms"][0]["name"] != "POISON"   # no shared mutable state
        assert make_good()["rooms"][0]["name"] != "POISON"
