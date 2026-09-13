"""Tests for the design-intent verdict (`kir/design_check.py`) and the
stage profile.

What is checked is not "the function returned something," but the FOUR
properties the module was written for:

1. the geometric read does what it promises: a planar partition yields a
   polygon where walls close, and HONESTLY yields none where they don't;
2. the stage profile removes exactly what is named and nothing beyond it —
   without it, any building with a stair would read as NOT_EVALUATED;
3. a named default cannot become load-bearing (the `StageProfile`
   invariant);
4. a verdict from the program does NOT PASS ITSELF OFF as a verdict from
   the decompile, and the divergence between the two paths is explained by
   the input, not by the wording.

Run: KUKAI_CHECKER_V2=1 pytest kir/tests/test_design_check.py -q
"""
from __future__ import annotations

import os
from typing import Any, Mapping

import pytest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir.design_check import (  # noqa: E402
    DESIGN_STAGE,
    DESIGN_STAGE_THRESHOLDS,
    OUT_OF_SCOPE,
    UNATTRIBUTED,
    BuildWitness,
    DesignCheckUnavailable,
    ModelSource,
    check_design,
    design_stage_profile,
    compare,
    render_comparison,
    render_verdict,
    spatial_model_from_program,
)
from kir.decompile.l1_schema import stable_l1_id  # noqa: E402
from kir.checker.spatial_model import (  # noqa: E402
    RoomFunction,
    Verdict,
)
from kir.checker.thresholds import StageProfile, Thresholds  # noqa: E402


# --------------------------------------------------------------------- builders

def _op(op_name: str, source_id: str, params: dict, *, level_name=None,
        type_name: str = "") -> dict:
    return {
        "kind": "op", "op_name": op_name, "_id": stable_l1_id("op", source_id),
        "type_name": type_name, "params": params, "source_element_id": source_id,
        "level_name": level_name, "anchor_mm": None,
    }


def _level_ref(name: str, source_id: str) -> dict:
    return {"by": "name", "value": name, "_id": source_id}


def _wall(source_id: str, p0, p1, *, level=("L1", "L-1"), height_mm=3000.0) -> dict:
    return _op("create_wall", source_id, {
        "p0_mm": list(p0), "p1_mm": list(p1),
        "level": _level_ref(*level), "height_mm": height_mm,
    })


def _rect_walls(prefix: str, x0, y0, x1, y1, *, height_mm=3000.0) -> list[dict]:
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [
        _wall(f"{prefix}{i}", corners[i], corners[(i + 1) % 4], height_mm=height_mm)
        for i in range(4)
    ]


def _two_room_program() -> list[dict]:
    """Two adjacent closed rooms, a door between them, an exterior door,
    and a window.

    The numbers are chosen so every claim in the test can be read with the
    naked eye: a room of 8x5 m (40 m²) and one of 4x5 m (20 m²), wall
    height 3000 mm.
    """
    nodes: list[dict] = [
        _op("create_level", "L-1", {"elev_mm": 0.0, "name": "L1"}),
        _op("create_level", "L-2", {"elev_mm": 3000.0, "name": "L2"}),
    ]
    # overall outline 12x5 with a partition at x=8000
    nodes += [
        _wall("w1", (0, 0), (12000, 0)),
        _wall("w2", (12000, 0), (12000, 5000)),
        _wall("w3", (12000, 5000), (0, 5000)),
        _wall("w4", (0, 5000), (0, 0)),
        _wall("w5", (8000, 0), (8000, 5000)),
    ]
    nodes += [
        _op("create_room", "r1", {"xy": [4000.0, 2500.0],
                                  "level": _level_ref("L1", "L-1"),
                                  "name": "Спальня"}),
        _op("create_room", "r2", {"xy": [10000.0, 2500.0],
                                  "level": _level_ref("L1", "L-1"),
                                  "name": "Кухня"}),
    ]
    wall5 = stable_l1_id("op", "w5")
    wall1 = stable_l1_id("op", "w1")
    nodes += [
        # an interior door in the partition
        _op("create_door", "d1", {"host": {"ref": wall5}, "offset_mm": 2500.0}),
        # an exterior door in the south wall of the "Kitchen" room
        _op("create_door", "d2", {"host": {"ref": wall1}, "offset_mm": 10000.0}),
        # a window in the south wall of the "Bedroom" room
        _op("create_window", "win1", {"host": {"ref": wall1}, "offset_mm": 4000.0,
                                      "sill_mm": 800.0}),
    ]
    return nodes


# ------------------------------------------------- 1. the geometric read

def test_planar_partition_finds_rooms_that_walls_actually_enclose():
    model, witness = spatial_model_from_program(
        _two_room_program(), building_id="t")
    assert witness.source is ModelSource.PROGRAM
    assert witness.rooms_measured == 2, witness.unmeasured_reasons
    by_name = {room.name: room for room in model.rooms}
    # 8x5 and 4x5 meters: the area is read off the partition polygon, not
    # declared
    assert by_name["Спальня"].area_m2 == pytest.approx(40.0, abs=0.05)
    assert by_name["Кухня"].area_m2 == pytest.approx(20.0, abs=0.05)
    assert by_name["Спальня"].function is RoomFunction.ЖИЛАЯ
    assert by_name["Кухня"].function is RoomFunction.КУХНЯ


def test_room_height_comes_from_the_walls_that_closed_it():
    model, _ = spatial_model_from_program(_two_room_program(), building_id="t")
    for room in model.rooms:
        assert room.height_mm == pytest.approx(3000.0)
        assert room.height_source == "wall_enclosure"


def test_unenclosed_room_goes_to_unmeasured_never_invented():
    """A room outside the walls is NEITHER a partitioner bug NOR a
    fabrication: it goes into the unmeasurable."""
    nodes = _two_room_program()
    nodes.append(_op("create_room", "r3", {"xy": [50000.0, 50000.0],
                                           "level": _level_ref("L1", "L-1"),
                                           "name": "Спальня в чистом поле"}))
    model, witness = spatial_model_from_program(nodes, building_id="t")
    assert witness.rooms_total == 3
    assert witness.rooms_measured == 2
    assert witness.unmeasured_room_ids == ["r3"]
    assert witness.unmeasured_reasons["not_enclosed_by_walls"] == 1
    lonely = next(room for room in model.rooms if room.id == "r3")
    assert lonely.boundary == []          # there is no outline
    assert lonely.height_mm is None       # and there is no height either — not a 2700 pulled out of thin air


def test_one_face_claimed_by_two_rooms_is_given_to_neither():
    """The partition did not tell two points apart — picking one would
    mean guessing."""
    nodes = [
        _op("create_level", "L-1", {"elev_mm": 0.0, "name": "L1"}),
        *_rect_walls("w", 0, 0, 10000, 5000),
        _op("create_room", "r1", {"xy": [2000.0, 2500.0],
                                  "level": _level_ref("L1", "L-1"), "name": "Спальня"}),
        _op("create_room", "r2", {"xy": [8000.0, 2500.0],
                                  "level": _level_ref("L1", "L-1"), "name": "Кухня"}),
    ]
    model, witness = spatial_model_from_program(nodes, building_id="t")
    assert witness.rooms_measured == 0
    assert witness.unmeasured_reasons["shared_face"] == 2
    assert sorted(witness.shared_face_room_ids) == ["r1", "r2"]
    assert all(room.boundary == [] for room in model.rooms)


def test_door_position_is_read_from_host_and_offset_not_guessed():
    model, _ = spatial_model_from_program(_two_room_program(), building_id="t")
    doors = {door.id: door for door in model.doors}
    # w5 runs from (8000,0) to (8000,5000); an offset of 2500 -> right in
    # the middle
    assert doors["d1"].location == pytest.approx((8000.0, 2500.0))
    # w1 runs from (0,0) to (12000,0); an offset of 10000
    assert doors["d2"].location == pytest.approx((10000.0, 0.0))
    # the opening has no width in the program — 0.0 means "not expressed,"
    # not "zero"
    assert doors["d1"].width_mm == 0.0


def test_door_adjacency_is_measured_not_declared():
    model, _ = spatial_model_from_program(_two_room_program(), building_id="t")
    inner = next(door for door in model.doors if door.id == "d1")
    assert {inner.from_room_id, inner.to_room_id} == {"r1", "r2"}
    # exteriority is NOT declared by the partitioner: derive.py derives it
    # from the shell's ring
    assert all(not door.is_exterior for door in model.doors)


# --------------------------------------------------- 2. the stage profile

def test_without_a_profile_any_building_with_a_stair_is_not_evaluated():
    """The very reason the profile exists at all (engine.RULE_SPECS_V2:HAB011)."""
    nodes = _two_room_program()
    nodes.append(_op("create_stairs", "s1", {
        "p0_mm": [1000.0, 1000.0], "p1_mm": [3000.0, 1000.0],
        "base_level": _level_ref("L1", "L-1"),
        "top_level": _level_ref("L2", "L-2"),
    }))
    model, witness = spatial_model_from_program(nodes, building_id="t", profile=None)
    plain = check_design(model, witness, thresholds=Thresholds())
    assert "HAB011" in plain.report.coverage.mandatory_not_evaluated
    assert plain.verdict is not Verdict.PASS

    staged = check_design(model, witness, thresholds=DESIGN_STAGE_THRESHOLDS)
    assert "HAB011" not in staged.report.coverage.mandatory_not_evaluated


def test_suspended_rule_does_not_run_and_says_who_suspended_it():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    verdict = check_design(model, witness)
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    for rule_id in DESIGN_STAGE.suspended:
        assert rows[rule_id].status.value == "not_evaluated"
        assert DESIGN_STAGE.name in rows[rule_id].reason
        assert DESIGN_STAGE.suspension_reason(rule_id) in rows[rule_id].reason
    # and not one finding from the removed rule leaked into the report
    fired = {v.rule_id for v in (verdict.report.blocking + verdict.report.warnings
                                 + verdict.report.info)}
    assert not (fired & set(DESIGN_STAGE.suspended))


def test_profile_changes_nothing_it_did_not_name():
    """A profile is a composition of rules, not a discount: the remaining
    rules proceed exactly as before."""
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    staged = check_design(model, witness, thresholds=DESIGN_STAGE_THRESHOLDS)
    plain = check_design(model, witness, thresholds=Thresholds())
    staged_rows = {o.rule_id: o for o in staged.report.coverage.outcomes}
    plain_rows = {o.rule_id: o for o in plain.report.coverage.outcomes}
    # 🔴 A PRECONDITION IS ALSO "NAMED," AND THIS CAME OUT ON 22.08.2026.
    # A profile names a rule THREE ways: by removal, by requiredness, and
    # by PRECONDITION (`HAB001`/`HAB010` -> `stair_landings_complete`,
    # `HAB002` -> three entrances). Only the first two were being counted
    # here.
    #
    # The difference did not show up as long as `stair_landings_complete`
    # was vacuously true at zero stairs: with the profile and without it,
    # the rule spoke the same way either way. Fixing that precondition (23
    # false BLOCKING findings on MNVNK) surfaced the difference, and the
    # test went red on `HAB001` — correctly red: the rule had DIVERGED,
    # and the "named" list stayed silent about it.
    touched = (set(DESIGN_STAGE.suspended) | set(DESIGN_STAGE.mandatory)
               | set(DESIGN_STAGE.preconditions))
    for rule_id in plain_rows:
        if rule_id in touched:
            continue
        assert staged_rows[rule_id].status is plain_rows[rule_id].status, rule_id
        assert staged_rows[rule_id].n_subjects == plain_rows[rule_id].n_subjects
    # the profile does not touch numeric tolerances at all
    assert DESIGN_STAGE_THRESHOLDS.model_dump(
        exclude={"profile"}) == Thresholds().model_dump(exclude={"profile"})


def test_profile_name_reaches_the_report_and_the_verdict_text():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    verdict = check_design(model, witness)
    assert verdict.report.coverage.profile_name == DESIGN_STAGE.name
    text = render_verdict(verdict)
    assert DESIGN_STAGE.name in text
    assert "применимо" in text and "правил из" in text


def test_named_nominal_cannot_become_load_bearing():
    """The `StageProfile` invariant: a nominal value survives only as long
    as everything that would compare against it is removed too."""
    with pytest.raises(ValueError) as excinfo:
        StageProfile(name="кривой", nominal_opening_area_m2=1.0)
    assert "HAB031" in str(excinfo.value)
    # while one declared by the rules — survives
    ok = StageProfile(name="ровный", suspended={"HAB031": "нет площади"},
                      nominal_opening_area_m2=1.0)
    assert ok.nominal_opening_area_m2 == 1.0
    assert DESIGN_STAGE.nominal_opening_area_m2 is not None
    assert "HAB031" in DESIGN_STAGE.suspended


def test_window_presence_survives_the_unmeasurable_opening_size():
    """A window with no dimensions is still a window: HAB030 answers "is
    there an opening"."""
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    assert witness.nominal_opening_area_m2 == DESIGN_STAGE.nominal_opening_area_m2
    assert witness.opening_size_measured is False
    verdict = check_design(model, witness)
    # the "Bedroom" has a window -> HAB030 stays silent about it; the
    # "Kitchen" has none -> it speaks up
    fired = {ref for v in verdict.report.blocking + verdict.report.warnings
             if v.rule_id == "HAB030" for ref in v.refs}
    assert "r1" not in fired
    assert "r2" in fired


def test_missing_window_is_the_headline_finding():
    """"An apartment with no window" is the whole point of this. Remove
    the window — the rule speaks up."""
    nodes = [node for node in _two_room_program()
             if node.get("op_name") != "create_window"]
    model, witness = spatial_model_from_program(nodes, building_id="t")
    verdict = check_design(model, witness)
    blocking = [v for v in verdict.report.blocking if v.rule_id == "HAB030"]
    assert blocking, "жилая комната без окна обязана быть BLOCKING"
    assert "r1" in {ref for v in blocking for ref in v.refs}
    assert verdict.verdict is Verdict.FAIL


def _low_storey_program() -> list[dict]:
    """The same building, but a 2400 mm floor-to-floor and 2100 mm walls —
    a genuinely low story.

    The floor step is lowered TOGETHER with the walls on purpose: an
    enclosure only counts as a ceiling once it reaches the next level, and
    2100 mm walls under a 3000 mm level are a balustrade, not a low
    ceiling (see `_height_from_enclosure`).
    """
    nodes = []
    for node in _two_room_program():
        if node.get("op_name") == "create_level" and node["params"]["name"] == "L2":
            node = _op("create_level", "L-2", {"elev_mm": 2400.0, "name": "L2"})
        elif node.get("op_name") == "create_wall":
            node = _wall(node["source_element_id"], node["params"]["p0_mm"],
                         node["params"]["p1_mm"], height_mm=2100.0)
        nodes.append(node)
    return nodes


def test_low_ceiling_is_a_finding_and_it_comes_from_the_walls():
    model, witness = spatial_model_from_program(_low_storey_program(),
                                                building_id="t")
    verdict = check_design(model, witness)
    blocking = [v for v in verdict.report.blocking if v.rule_id == "HAB022"]
    assert blocking, "2100 мм ниже жёсткого порога 2200 — обязано быть BLOCKING"
    assert all(room.height_mm == pytest.approx(2100.0) for room in model.rooms)


def test_a_balustrade_is_not_a_ceiling():
    """Measurement K2: hall «ЛК 2.1 1» is closed by 1530 mm walls while
    its own height is 3830.

    The enclosure around a stair opening is not a ceiling, and a height
    taken from it would produce an accusation born of the partitioner's
    assumption, not of the building.
    """
    nodes = [node if node.get("op_name") != "create_wall"
             else _wall(node["source_element_id"], node["params"]["p0_mm"],
                        node["params"]["p1_mm"], height_mm=1530.0)
             for node in _two_room_program()]      # the level above stays at 3000
    model, witness = spatial_model_from_program(nodes, building_id="t")
    assert all(room.height_mm is None for room in model.rooms), \
        "ограждение, не доходящее до перекрытия, не определяет высоту помещения"
    verdict = check_design(model, witness)
    assert not [v for v in verdict.report.blocking if v.rule_id == "HAB022"]
    row = {o.rule_id: o for o in verdict.report.coverage.outcomes}["HAB022"]
    assert row.status.value == "not_evaluated"


# ------------------------------------------------- 3. honesty about the source

def test_v1_path_is_refused_never_silently_downgraded(monkeypatch):
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    monkeypatch.setenv("KUKAI_CHECKER_V2", "0")
    with pytest.raises(DesignCheckUnavailable):
        check_design(model, witness)


def test_source_is_visible_in_the_artifact_not_implied():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    text = render_verdict(check_design(model, witness))
    assert "САМОПРОВЕРКА" in text
    assert "ЗАЯВЛЕННОЕ" in text
    parse_witness = BuildWitness(source=ModelSource.PARSE, building_id="t")
    assert "НЕЗАВИСИМОЕ ЧТЕНИЕ" in parse_witness.source.evidence


def test_out_of_scope_is_named_in_every_verdict():
    """A component that does not undertake to predict Revit must say so
    out loud."""
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    text = render_verdict(check_design(model, witness))
    assert len(OUT_OF_SCOPE) == 5
    for item in OUT_OF_SCOPE:
        assert item.name in text
        assert item.measured, "поведение вне области обязано нести замер"


# ----------------------------------------------------------- 4. the gate

def test_identical_models_diverge_in_nothing():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    verdict = check_design(model, witness)
    assert compare(verdict, verdict) == []
    assert "РАСХОЖДЕНИЙ НЕТ" in render_comparison(verdict, verdict, [])


def test_every_divergence_carries_a_derived_cause_or_says_it_does_not():
    """No guessing accepted: the cause is either derived from the inputs,
    or named NOT ESTABLISHED."""
    full = _two_room_program()
    stripped = [node for node in full if node.get("op_name") != "create_window"]
    a = check_design(*spatial_model_from_program(full, building_id="t"))
    b = check_design(*spatial_model_from_program(stripped, building_id="t"))
    divergences = compare(a, b)
    assert divergences, "снятое окно обязано быть видно в воротах"
    assert {d.subject for d in divergences} >= {"windows", "HAB030/blocking"}
    for item in divergences:
        assert item.cause, item
    # Here the window is REMOVED FROM THE PROGRAM by hand: neither the
    # lifter nor the partitioner ever lost it, and the honest answer is
    # "cause not established." This is exactly the property being checked:
    # the module must stay silent where it doesn't know, rather than pick
    # something plausible.
    window_row = next(d for d in divergences if d.subject == "windows")
    assert window_row.cause == UNATTRIBUTED
    # But the consequence — the RULE's divergence — must be tied to the
    # input.
    rule_row = next(d for d in divergences if d.subject == "HAB030/blocking")
    assert rule_row.cause != UNATTRIBUTED
    text = render_comparison(a, b, divergences)
    assert "причина:" in text


def test_rule_divergence_is_attributed_to_the_input_the_rule_reads():
    full = _two_room_program()
    stripped = [node for node in full if node.get("op_name") != "create_window"]
    a = check_design(*spatial_model_from_program(full, building_id="t"))
    b = check_design(*spatial_model_from_program(stripped, building_id="t"))
    row = next(d for d in compare(a, b) if d.subject == "HAB030/blocking")
    # HAB030 reads windows — and they are exactly what must appear in the
    # cause
    assert "окон" in row.cause


# ═══════════ 5. A RULE MUST NOT FIRE ON AN INPUT IT DOES NOT HAVE ═══════

def _program_with_one_unenclosed_room() -> list[Mapping[str, Any]]:
    nodes = _two_room_program()
    nodes.append(_op("create_room", "r3", {"xy": [50000.0, 50000.0],
                                           "level": _level_ref("L1", "L-1"),
                                           "name": "Спальня в чистом поле"}))
    return nodes


def test_unmeasurable_room_is_withheld_from_the_area_rule_not_accused():
    """A zero in place of the unknown is a lie. Measured on K2: 732
    accusations of "area 0"."""
    model, witness = spatial_model_from_program(
        _program_with_one_unenclosed_room(), building_id="t")
    lonely = next(room for room in model.rooms if room.id == "r3")
    assert lonely.area_m2 == 0.0        # the contract has no way to say "unknown"
    assert lonely.function is RoomFunction.ЖИЛАЯ   # and it has a threshold

    verdict = check_design(model, witness)
    accused = {ref for v in verdict.report.blocking if v.rule_id == "HAB020"
               for ref in v.refs}
    assert "r3" not in accused, "правило обвинило помещение, площади которого не знает"
    row = {o.rule_id: o for o in verdict.report.coverage.outcomes}["HAB020"]
    assert row.excluded_subjects == 1
    assert "room_polygon" in row.excluded_reason
    # and the same thing is visible in the text, not only in the
    # structure
    assert "не оценено HAB020 на 1 субъектах" in render_verdict(verdict)


def test_the_same_law_covers_width_height_daylight_and_door_sides():
    model, witness = spatial_model_from_program(
        _program_with_one_unenclosed_room(), building_id="t")
    verdict = check_design(model, witness)
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    for rule_id in ("HAB020", "HAB021", "HAB022", "HAB030", "HAB040"):
        assert rows[rule_id].excluded_subjects >= 1, rule_id
    # HAB060..063 are WITNESSES, not accusers: their job is exactly to
    # name the room whose boundary there is nothing to check. All other
    # rules stay silent about it.
    accused = {(v.rule_id, ref)
               for bucket in (verdict.report.blocking, verdict.report.warnings)
               for v in bucket for ref in v.refs
               if not v.rule_id.startswith("HAB06")}
    assert not [pair for pair in accused if pair[1] == "r3"], accused
    witnessed = {v.rule_id for v in verdict.report.warnings
                 if "r3" in v.refs and v.rule_id.startswith("HAB06")}
    assert witnessed == {"HAB060"}, "неизмеримое помещение обязано быть НАЗВАНО"


def test_apartment_oracle_rules_are_suspended_with_the_measurement_named():
    """A measurement of the oracle's accuracy is part of the cause, not a
    footnote to it.

    🔴 HAB002 LEFT THIS LIST ON 15.08.2026, and that is not a softening but
    a second measurement. On the generator's reference case, where the
    truth is known by construction, `derive_apartments` gives 20
    apartments out of 20 with the EXACT composition: "0%" is a property of
    the INPUT, not of the algorithm. HAB002 moved onto preconditions
    (`_DESIGN_PRECONDITIONS`), which separate an input the oracle can be
    trusted on from one it cannot; the grounds and both controls are in
    `test_apartment_oracle_precondition.py`. The remaining three each
    stand on THEIR OWN input, and this measurement does NOT cover them.
    """
    _, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    profile = design_stage_profile(witness)
    for rule_id in ("HAB003", "HAB004", "HAB042"):
        reason = profile.suspension_reason(rule_id)
        assert reason, rule_id
        assert "0%" in reason and "469" in reason, "причина обязана нести замер"
    assert not profile.suspension_reason("HAB002"), (
        "HAB002 больше не снимается безусловно — он обязан стоять на предусловиях")


def test_curtain_wall_facade_suspends_the_daylight_rule_with_both_numbers():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    assert "HAB030" not in design_stage_profile(witness).suspended

    witness.curtain_panels = 2602          # measurement K2
    witness.counts["windows"] = 0
    profile = design_stage_profile(witness)
    reason = profile.suspension_reason("HAB030")
    assert "2602" in reason and "витраж" in reason.lower()
    verdict = check_design(model, witness,
                           thresholds=Thresholds(profile=profile))
    assert not [v for v in verdict.report.blocking if v.rule_id == "HAB030"]
    row = {o.rule_id: o for o in verdict.report.coverage.outcomes}["HAB030"]
    assert row.status.value == "not_evaluated"
    assert "2602" in row.reason


def test_missing_ground_level_stops_hab010_instead_of_accusing_every_level():
    """Measured: the kindergarten — 4 accusations out of 4 occupied
    levels, snowdon — 8 out of 8."""
    from kir.checker.engine import PRECONDITIONS

    nodes = [node for node in _two_room_program()
             if node.get("op_name") != "create_door"
             or node["source_element_id"] != "d2"]      # removing the exterior door
    nodes.append(_op("create_stairs", "s1", {
        "p0_mm": [1000.0, 1000.0], "p1_mm": [3000.0, 1000.0],
        "base_level": _level_ref("L1", "L-1"),
        "top_level": _level_ref("L2", "L-2"), "width_mm": 1200.0}))
    model, witness = spatial_model_from_program(nodes, building_id="t")
    verdict = check_design(model, witness)
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    assert rows["HAB010"].status.value == "not_evaluated"
    assert "ground_level_known" in rows["HAB010"].reason
    assert not [v for v in verdict.report.blocking if v.rule_id == "HAB010"]
    assert "ground_level_known" in PRECONDITIONS
    # An active mandatory rule that cannot establish its precondition is unknown,
    # never satisfied. Before the regression fix this exact design returned PASS.
    assert verdict.report.coverage.mandatory_not_evaluated == ["HAB001", "HAB010"]
    assert verdict.verdict is Verdict.NOT_EVALUATED
    assert verdict.report.passed is False


def test_stair_landing_gap_stops_the_vertical_rules():
    nodes = _two_room_program()
    nodes.append(_op("create_stairs", "s1", {
        "p0_mm": [1000.0, 1000.0], "p1_mm": [3000.0, 1000.0],
        "base_level": _level_ref("L1", "L-1"),
        "top_level": _level_ref("L2", "L-2"), "width_mm": 1200.0}))
    model, witness = spatial_model_from_program(nodes, building_id="t")
    # no room is named a stairwell -> the upward edges will not be built
    assert witness.rooms_stair == 0
    verdict = check_design(model, witness)
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    for rule_id in ("HAB001", "HAB010"):
        assert rows[rule_id].status.value == "not_evaluated", rule_id
        assert "stair_landings_complete" in rows[rule_id].reason


def test_a_rule_may_be_suspended_or_filtered_but_never_both():
    with pytest.raises(ValueError) as excinfo:
        StageProfile(name="кривой", suspended={"HAB020": "нет"},
                     subject_inputs={"HAB020": "room_polygon"})
    assert "HAB020" in str(excinfo.value)


def test_the_filter_refuses_rules_that_reason_about_the_whole_graph():
    """Trimming the model for a rule about CONNECTIVITY means changing the
    question, not the coverage."""
    from kir.checker.engine import _ROOM_FILTERABLE

    assert not (_ROOM_FILTERABLE & {"HAB002", "HAB003", "HAB004", "HAB010", "HAB042"})
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    bad = Thresholds(profile=StageProfile(
        name="кривой", subject_inputs={"HAB010": "room_polygon"}))
    with pytest.raises(ValueError) as excinfo:
        check_design(model, witness, thresholds=bad)
    assert "HAB010" in str(excinfo.value)


def _tiny_l0_document():
    """The same building as `_two_room_program`, but as a DECOMPILE.

    Room boundaries are given as outlines (the way Revit returns them),
    openings as points with instance dimensions. This is a case where the
    two paths MUST converge: everything they differ on in a real building
    is expressed here by both.
    """
    from kir.decompile.schema import L0Document

    def wall(eid, p0, p1):
        return {
            "element_id": eid, "category": "OST_Walls", "category_ru": "Стены",
            "type_id": "t", "type_name": "Стена 200", "level_id": "L-1",
            "level_name": "L1", "host_id": None, "geom_kind": "curve",
            "p0_mm": [p0[0], p0[1], 0.0], "p1_mm": [p1[0], p1[1], 0.0],
            "bbox_min_mm": None, "bbox_max_mm": None, "rotation_deg": None,
            "design_option": None, "phase_created": None, "workset": None,
            "params": {"WALL_USER_HEIGHT_PARAM": 3000.0},
        }

    def hosted(eid, category, xy, host, width, height):
        return {
            "element_id": eid, "category": category, "category_ru": category,
            "type_id": "t", "type_name": f"{category} 900", "level_id": "L-1",
            "level_name": "L1", "host_id": host, "geom_kind": "point",
            "p0_mm": [xy[0], xy[1], 0.0], "p1_mm": None,
            "bbox_min_mm": None, "bbox_max_mm": None, "rotation_deg": None,
            "design_option": None, "phase_created": None, "workset": None,
            "params": {"FAMILY_WIDTH_PARAM": width, "FAMILY_HEIGHT_PARAM": height},
        }

    def room_element(eid):
        return {
            "element_id": eid, "category": "OST_Rooms", "category_ru": "Помещения",
            "type_id": "", "type_name": "", "level_id": "L-1", "level_name": "L1",
            "host_id": None, "geom_kind": "bbox_only", "p0_mm": None, "p1_mm": None,
            "bbox_min_mm": [0.0, 0.0, 0.0], "bbox_max_mm": [12000.0, 5000.0, 3000.0],
            "rotation_deg": None, "design_option": None, "phase_created": None,
            "workset": None, "params": {},
        }

    return L0Document.from_dict({
        "doc_name": "tiny", "revit_version": "2023", "units": "mm",
        "change_stamp": "tiny-v1",
        "levels": [{"id": "L-1", "name": "L1", "elevation_mm": 0.0},
                   {"id": "L-2", "name": "L2", "elevation_mm": 3000.0}],
        "grids": [], "project_info": {},
        "rooms": [
            {"id": "r1", "name": "Спальня", "level_id": "L-1", "level_name": "L1",
             "area_m2": 40.0,
             "boundary_mm": [[0, 0], [8000, 0], [8000, 5000], [0, 5000]],
             "boundary_loops_mm": [[[0, 0], [8000, 0], [8000, 5000], [0, 5000]]],
             "bounding_element_ids": ["w1", "w4", "w3", "w5"]},
            {"id": "r2", "name": "Кухня", "level_id": "L-1", "level_name": "L1",
             "area_m2": 20.0,
             "boundary_mm": [[8000, 0], [12000, 0], [12000, 5000], [8000, 5000]],
             "boundary_loops_mm": [[[8000, 0], [12000, 0], [12000, 5000],
                                    [8000, 5000]]],
             "bounding_element_ids": ["w1", "w2", "w3", "w5"]},
        ],
        "elements": [
            wall("w1", (0, 0), (12000, 0)),
            wall("w2", (12000, 0), (12000, 5000)),
            wall("w3", (12000, 5000), (0, 5000)),
            wall("w4", (0, 5000), (0, 0)),
            wall("w5", (8000, 0), (8000, 5000)),
            room_element("r1"), room_element("r2"),
            hosted("d1", "OST_Doors", (8000, 2500), "w5", 900.0, 2100.0),
            hosted("d2", "OST_Doors", (10000, 0), "w1", 1000.0, 2100.0),
            hosted("win1", "OST_Windows", (4000, 0), "w1", 1200.0, 1400.0),
        ],
        "category_status": [], "links": [],
    })


def test_gate_two_paths_agree_when_both_can_express_the_building():
    """THE GATE, the positive case: they converge — the program path is
    justified."""
    from kir.design_check import spatial_model_from_l0

    parse = check_design(*spatial_model_from_l0(_tiny_l0_document()))
    program = check_design(*spatial_model_from_program(
        _two_room_program(), building_id="tiny-v1"))
    assert parse.verdict is program.verdict
    divergences = compare(parse, program)
    subjects = {d.subject for d in divergences}
    # populations, "room geometry" inputs, and all rules match …
    assert not (subjects & {"rooms", "doors", "walls", "windows", "levels",
                            "rooms_measured", "rooms_with_height",
                            "HAB020", "HAB030", "HAB001", "HAB003"})
    # … and what remains is exactly what the two representations genuinely
    # express differently: the opening's dimensions, which the program
    # doesn't carry.
    assert subjects <= {"doors_with_width", "windows_with_size", "HAB041"}
    for item in divergences:
        assert item.cause != UNATTRIBUTED, item


def test_geometry_gate_is_per_element_and_splits_along_from_across():
    """The gate compares element NUMBERS, not just their count."""
    from kir.design_check import compare_geometry, spatial_model_from_l0

    model_a, _ = spatial_model_from_l0(_tiny_l0_document())
    model_b, _ = spatial_model_from_program(_two_room_program(),
                                            building_id="tiny-v1")
    rows = {row.subject: row for row in compare_geometry(model_a, model_b)}
    # the wall axis is read by both paths from the same numbers — there
    # should be no line about it
    assert "ось стены" not in rows
    # along the host's axis the opening is reconstructed EXACTLY
    assert "совпало 2, макс 0.00 мм" in rows["положение двери — ВДОЛЬ оси хозяина"].program
    # across it there is no discrepancy: in this rig the openings are on
    # the axis anyway
    assert "положение двери — ПОПЕРЁК оси хозяина" not in rows
    iou = rows["контур помещения (IoU)"]
    assert "IoU медиана 1.000" in iou.program


def test_parse_path_reads_the_room_boundary_revit_returned():
    from kir.design_check import spatial_model_from_l0

    model, witness = spatial_model_from_l0(_tiny_l0_document())
    assert witness.source is ModelSource.PARSE
    assert witness.rooms_measured == 2
    rooms = {room.name: room for room in model.rooms}
    assert rooms["Спальня"].area_m2 == pytest.approx(40.0)
    assert rooms["Спальня"].height_source == "room_bbox"
    # the decompile HAS the opening's dimensions — and the profile's
    # nominal value is not used at all
    assert witness.opening_size_measured is True
    assert witness.nominal_opening_area_m2 is None
    assert witness.inputs["windows_with_size"] == 1


def test_witness_counts_are_not_decoration():
    """Every number the witness reports must match the model's actual content."""
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    assert witness.counts["rooms"] == len(model.rooms)
    assert witness.counts["walls"] == len(model.walls)
    assert witness.counts["doors"] == len(model.doors)
    assert witness.inputs["rooms_measured"] == witness.rooms_measured
    assert witness.inputs["doors_with_width"] == 0
    assert witness.inputs["windows_with_size"] == 0
    assert witness.measured_ratio == pytest.approx(1.0)


# ---------------------------------- closedness WITHOUT rooms (15.08.2026)

def _walls_only(*, closed: bool) -> list[dict]:
    """Four walls and NOT A SINGLE room. `closed=False` — a 1500 mm gap."""
    nodes = [_op("create_level", "L-1", {"elev_mm": 0.0, "name": "L1"})]
    nodes += _rect_walls("w", 0, 0, 6000, 4000)[:3]
    last = (0, 4000), ((0, 0) if closed else (0, 1500))
    nodes.append(_wall("w3", *last))
    return nodes


def test_enclosure_is_measured_where_walls_are_not_where_rooms_are():
    """CLOSEDNESS IS A FACT ABOUT WALLS, AND IS COMPUTED WHEREVER THERE
    ARE WALLS.

    Before 15.08.2026 the partition was built by looping over levels THAT
    HAVE ROOMS. A program of four walls with not a single room gave
    `partition_faces == 0` regardless of whether the walls closed the
    outline or not — that is, in exactly the case where the "striped
    wall" (three walls, no rooms) broke, the witness carried not one
    number about the partition.

    Here both sides are covered: a closed box yields a face, an open one
    does not. The second case is a FAIL control: without it the test
    would be green even on an instrument that always answers "one face."
    """
    closed, _w = spatial_model_from_program(
        _walls_only(closed=True), building_id="закрытая")
    opened, _w2 = spatial_model_from_program(
        _walls_only(closed=False), building_id="открытая")
    del closed, opened

    _, w_closed = spatial_model_from_program(
        _walls_only(closed=True), building_id="закрытая")
    _, w_open = spatial_model_from_program(
        _walls_only(closed=False), building_id="открытая")

    assert w_closed.counts.get("walls") == 4
    assert w_open.counts.get("walls") == 4, "стены обязаны доехать в обоих случаях"
    assert w_closed.partition_faces == 1, "замкнутая коробка обязана дать грань"
    assert w_open.partition_faces == 0, "дыра 1500 мм не замыкает ничего"
    assert w_closed.rooms_total == 0 and w_open.rooms_total == 0


def test_walls_on_a_level_nobody_declared_are_named_upstream_not_here():
    """Walls on a level that no `create_level` ever declared.

    Zero faces here is NOT silent, and the cause is named UPSTREAM: such a
    wall never reaches the partition at all — the read discards it with
    the note `wall_level_unresolved`. This test holds exactly that — so
    that the next edit doesn't set up a SECOND name for the same fact (the
    first edition did, and this test caught it).
    """
    nodes = [_op("create_level", "L-1", {"elev_mm": 0.0, "name": "L1"})]
    nodes += [_wall("x1", (0, 0), (6000, 0), level=("L9", "L-9"))]
    _, witness = spatial_model_from_program(nodes, building_id="сирота")
    assert witness.partition_faces == 0
    assert witness.counts.get("walls", 0) == 0, "стена не доехала — и это верно"
    codes = {note.code for note in witness.notes}
    assert "wall_level_unresolved" in codes, codes
