"""THE PARSE READS WHAT LAY INSIDE IT AND WAS DISCARDED BY US — and names the kind of each quantity.

Three defects paid for by a real building on 22.08.2026 (MNVNK, 33,944
elements, 1,102 rooms, 24 stairs) and closed here:

  L1  `_stairs_from_l0` required `STAIRS_TOP_LEVEL_PARAM`; the building
      returned empty for it on 24 of 24, and ALL 24 stairs were discarded.
      The base, the number of risers, and the riser height came through
      24 of 24 — the top is DERIVABLE. The cost of the discard: with not
      a single stair, the precondition `stair_landings_complete` is true
      VACUOUSLY, and HAB010 accused 23 of 24 levels of not descending to
      the ground.
  L2  room function: `ROOM_NAME` = «Помещение» on 1102 of 1102, 0%
      classification, and this silences seven rules because of it.
      Furnishings (a toilet, a kitchen front, a bed) name the function —
      and that is an INFERENCE, with its own kind and its own counter.
  L3  the decision "measured dimension or nominal" was made PER-ITEM but
      recorded AS A BUILDING-WIDE ONE: 588 windows were measured, 2364
      received a made-up 1.0 m², and the witness printed
      `opening_size_measured: true` and NOT A SINGLE note.

Each test holds a PAIR of inputs exactly where the difference is
load-bearing: the same reading with a declared quantity and without one.
What is checked is not "the function returned something", but that the
parse DISTINGUISHES what was read from what was inferred — without the
pair this is invisible.

Run: KUKAI_CHECKER_V2=1 pytest \
    kir/tests/test_the_parse_reads_what_it_had_dropped.py -q
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir.design_check import (  # noqa: E402
    STAIR_TOP_SNAP_TOL_MM,
    DESIGN_STAGE,
    spatial_model_from_l0,
)
from kir.checker.spatial_model import RoomFunction  # noqa: E402


# --------------------------------------------------------------------- builders

def _level(eid: str, name: str, z: float) -> dict:
    return {"id": eid, "name": name, "elevation_mm": z}


def _element(eid: str, category: str, **over) -> dict:
    row = {
        "element_id": eid, "category": category, "category_ru": category,
        "type_id": "t", "type_name": "", "level_id": "L-1", "level_name": "L1",
        "host_id": None, "geom_kind": "point", "p0_mm": None, "p1_mm": None,
        "bbox_min_mm": None, "bbox_max_mm": None, "rotation_deg": None,
        "design_option": None, "phase_created": None, "workset": None, "params": {},
    }
    row.update(over)
    return row


def _document(*, elements: list[dict], rooms: list[dict] | None = None,
              levels: list[dict] | None = None):
    from kir.decompile.schema import L0Document

    return L0Document.from_dict({
        "doc_name": "стенд", "revit_version": "2023", "units": "mm",
        "change_stamp": "стенд-v1",
        "levels": levels or [_level("L-1", "L1", 0.0), _level("L-2", "L2", 3000.0)],
        "grids": [], "project_info": {},
        "rooms": rooms or [],
        "elements": elements,
        "category_status": [], "links": [],
    })


def _stair(eid: str, params: dict) -> dict:
    return _element(eid, "OST_Stairs", type_name="Лестница", level_id=None,
                    level_name=None, geom_kind="bbox_only", params=params)


def _room(eid: str, boundary, *, name="Помещение") -> dict:
    return {"id": eid, "name": name, "level_id": "L-1", "level_name": "L1",
            "area_m2": 6.0, "boundary_mm": boundary,
            "boundary_loops_mm": [boundary], "bounding_element_ids": []}


def _room_element(eid: str) -> dict:
    return _element(eid, "OST_Rooms", type_name="", geom_kind="bbox_only",
                    params={"ROOM_UPPER_OFFSET": 3000})


def _fixture(eid: str, category: str, type_name: str, xy) -> dict:
    return _element(eid, category, type_name=type_name, geom_kind="point",
                    p0_mm=[xy[0], xy[1], 0.0])


def _window(eid: str, xy, *, size: tuple[float, float] | None) -> dict:
    params = ({"FAMILY_WIDTH_PARAM": size[0], "FAMILY_HEIGHT_PARAM": size[1]}
              if size else {})
    return _element(eid, "OST_Windows", type_name="ОК", p0_mm=[xy[0], xy[1], 0.0],
                    params=params)


# --------------------------------------------------------------------- L1: stairs

_RISERS = {"STAIRS_BASE_LEVEL_PARAM": "L-1", "STAIRS_ACTUAL_NUM_RISERS": 20,
           "STAIRS_ACTUAL_RISER_HEIGHT": 150, "STAIRS_ACTUAL_TREAD_DEPTH": 300}


def test_a_stair_without_a_declared_top_is_no_longer_thrown_away():
    """The top is DERIVED, and the derived value names itself as derived.

    The pair: the same stair with a declared top gives
    `stairs_top_level_param`, without the declaration — `riser_run`. Were
    there no difference, the field would exist but the distinction would
    not.
    """
    declared = _document(elements=[_stair(
        "s", {**_RISERS, "STAIRS_TOP_LEVEL_PARAM": "L-2"})])
    derived = _document(elements=[_stair("s", _RISERS)])

    model_d, witness_d = spatial_model_from_l0(declared)
    model_i, witness_i = spatial_model_from_l0(derived)

    assert [s.top_level_source for s in model_d.stairs] == ["stairs_top_level_param"]
    assert [s.top_level_source for s in model_i.stairs] == ["riser_run"]
    for model in (model_d, model_i):
        assert [s.top_level_id for s in model.stairs] == ["L-2"]
    # and not one is discarded — that is the whole value of the fix
    assert "stairs" not in witness_d.dropped
    assert "stairs" not in witness_i.dropped
    assert witness_i.counts["stairs"] == 1


def test_the_stale_docstring_was_hiding_two_parameters_out_of_three():
    """The riser count and the tread ARRIVE; one run width is missing.

    The previous code put `None` into all three with the argument "in L0
    1.0 they don't exist." The argument has gone stale: exactly one of
    the three quantities is missing, and it has ITS OWN reason — the
    width lives on the run (`StairsRun.ActualRunWidth`), and it is
    EXACTLY THAT ONE that is not lifted: the run itself is read by the
    side stage `sketch_extract` through `Stairs.GetStairsRuns()`, and the
    path was lifted on 48 of 48 (measured 22.08.2026). The claim "the
    lift does not read runs" was broader than the truth and had four
    carriers in the tree.
    """
    model, _ = spatial_model_from_l0(_document(elements=[_stair("s", _RISERS)]))
    stair = model.stairs[0]
    assert stair.riser_count == 20
    assert stair.tread_depth_mm == 300.0
    assert stair.run_width_mm is None


def test_a_run_that_ends_off_level_says_so_instead_of_snapping_silently():
    """A top that does not match a level is a fact about the building, and
    it is named as a separate kind.

    On MNVNK there is one such case out of 24 (a finishing stair to the
    roof, +600 mm above the nearest level). Silently substituting the
    level's elevation would mean printing a rise that does not exist: 115
    mm instead of the declared 150.
    """
    off = {**_RISERS, "STAIRS_ACTUAL_NUM_RISERS": 24}          # 24 × 150 = 3600 mm
    model, witness = spatial_model_from_l0(_document(elements=[_stair("s", off)]))
    stair = model.stairs[0]
    assert stair.top_level_source == "riser_run_offlevel"
    assert stair.top_z == pytest.approx(3600.0)                 # a DERIVED elevation
    assert stair.top_z - 3000.0 > STAIR_TOP_SNAP_TOL_MM
    assert any(note.code == "stair_top_off_level" for note in witness.notes)


def test_a_stair_with_nothing_to_derive_from_is_still_refused_by_name():
    """Emptiness stays emptiness: without risers the top is not derived, and this is stated."""
    model, witness = spatial_model_from_l0(_document(elements=[
        _stair("s", {"STAIRS_BASE_LEVEL_PARAM": "L-1"})]))
    assert model.stairs == []
    assert witness.dropped["stairs"]["верх не объявлен и не выводится"] == 1


# --------------------------------------------------------------------- L2: function

_SQUARE = [[0, 0], [4000, 0], [4000, 4000], [0, 4000]]
_OTHER = [[5000, 0], [9000, 0], [9000, 4000], [5000, 4000]]


def test_the_furniture_names_the_room_and_the_name_says_it_was_inferred():
    """A toilet names the bathroom — the kind of the quantity is `fixtures`, not "read".

    The pair: the same room, named by the author "Санузел", gets `room_name`.
    """
    inferred = _document(
        rooms=[_room("r", _SQUARE)],
        elements=[_room_element("r"),
                  _fixture("f", "OST_PlumbingFixtures", "Унитаз с инсталляцией",
                           (2000, 2000))])
    authored = _document(
        rooms=[_room("r", _SQUARE, name="Санузел 1")],
        elements=[_room_element("r")])

    model_i, witness = spatial_model_from_l0(inferred)
    model_a, _ = spatial_model_from_l0(authored)

    assert model_i.rooms[0].function is RoomFunction.САНУЗЕЛ
    assert model_i.rooms[0].function_source == "fixtures"
    assert model_a.rooms[0].function is RoomFunction.САНУЗЕЛ
    assert model_a.rooms[0].function_source == "room_name"
    assert witness.rooms_function_inferred == 1
    assert witness.rooms_function_conflict == 0


def test_conflicting_fixtures_are_counted_and_never_resolved_by_order():
    """Two signals at once — the room stays OTHER, but the count is printed.

    The precision of an inference must be a quantity, not a tone: on
    MNVNK there is a conflict at 5 rooms out of 286 assertions. Taking
    the first key would mean turning uncertainty into an answer, and the
    dictionary's order would become load-bearing.
    """
    document = _document(
        rooms=[_room("r", _SQUARE)],
        elements=[_room_element("r"),
                  _fixture("f1", "OST_PlumbingFixtures", "Унитаз с инсталляцией",
                           (1000, 1000)),
                  _fixture("f2", "OST_Furniture", "Кухонный фронт_Прямой",
                           (3000, 3000))])
    model, witness = spatial_model_from_l0(document)
    assert model.rooms[0].function is RoomFunction.ПРОЧЕЕ
    assert model.rooms[0].function_source is None
    assert witness.rooms_function_conflict == 1
    assert witness.rooms_function_inferred == 0
    note = next(n for n in witness.notes if n.code == "room_function_from_fixtures")
    assert "конфликт признаков у 1" in note.detail


def test_a_fixture_outside_the_room_does_not_name_it():
    """Membership is decided by CONTAINMENT within the contour, without tolerance.

    A toilet in the neighboring room does not make this one a bathroom;
    a tolerance here would produce certainty, not coverage.
    """
    document = _document(
        rooms=[_room("r", _SQUARE), _room("r2", _OTHER)],
        elements=[_room_element("r"), _room_element("r2"),
                  _fixture("f", "OST_PlumbingFixtures", "Унитаз с инсталляцией",
                           (7000, 2000))])
    model, witness = spatial_model_from_l0(document)
    functions = {room.id: room.function for room in model.rooms}
    assert functions["r"] is RoomFunction.ПРОЧЕЕ
    assert functions["r2"] is RoomFunction.САНУЗЕЛ
    assert witness.rooms_function_inferred == 1


def test_an_authored_name_is_never_overridden_by_furniture():
    """The author's word outranks the inferred one — even when the furnishings disagree.

    The room is named «Балкон» (deliberately non-habitable), and there is
    a bed inside it. The inference has no right to rename it: the author
    wrote the name, we only interpreted the furnishings.
    """
    document = _document(
        rooms=[_room("r", _SQUARE, name="Балкон 3")],
        elements=[_room_element("r"),
                  _fixture("f", "OST_Furniture", "1800 x 2100мм - Двухспальная",
                           (2000, 2000))])
    model, witness = spatial_model_from_l0(document)
    assert model.rooms[0].function is RoomFunction.ПРОЧЕЕ
    assert model.rooms[0].function_source == "room_name"
    assert witness.rooms_function_inferred == 0


# --------------------------------------------------------------------- L3: openings

def test_a_measured_window_next_to_an_unmeasured_one_does_not_certify_the_building():
    """The decision is made per-item — so the receipt must be per-item too.

    THE LIVE LIE THIS TEST WAS WRITTEN FOR: `measured_any` ("at least one
    window has a measured dimension") was printed as a claim about the
    WHOLE building. On MNVNK — 588 measured against 2364 substituted,
    `opening_size_measured: true` and not a single note.
    """
    document = _document(
        rooms=[_room("r", _SQUARE)],
        elements=[_room_element("r"),
                  _window("w1", (2000, 0), size=(1200.0, 1400.0)),
                  _window("w2", (3000, 0), size=None)])
    model, witness = spatial_model_from_l0(document, profile=DESIGN_STAGE)

    assert witness.openings_measured == 1
    assert witness.openings_nominal == 1
    assert witness.opening_size_measured is False
    assert witness.nominal_opening_area_m2 == DESIGN_STAGE.nominal_opening_area_m2
    note = next(n for n in witness.notes if n.code == "opening_size_unmeasured")
    assert note.count == 1
    areas = {w.id: w.area_m2 for w in model.windows}
    assert areas["w1"] == pytest.approx(1.68)
    assert areas["w2"] == pytest.approx(DESIGN_STAGE.nominal_opening_area_m2)


def test_a_building_whose_windows_are_all_measured_still_reads_as_measured():
    """Control in the other direction: the fix has no right to lower an honest input."""
    document = _document(
        rooms=[_room("r", _SQUARE)],
        elements=[_room_element("r"),
                  _window("w1", (2000, 0), size=(1200.0, 1400.0))])
    _, witness = spatial_model_from_l0(document, profile=DESIGN_STAGE)
    assert witness.opening_size_measured is True
    assert witness.openings_nominal == 0
    assert witness.nominal_opening_area_m2 is None
    assert not [n for n in witness.notes if n.code == "opening_size_unmeasured"]


# --------------------------------------------------------------------- L4: phase

def test_an_unplaced_room_is_not_the_same_gap_as_an_unenclosed_one():
    """608 versus 21 reads as ONE THING TODAY, and it is two different fixes.

    The split had been sitting inside the parse the whole time: a placed
    room has a location point, an unplaced one has none at all. Before
    this fix, both kinds of emptiness were counted as one code
    `ring_degenerate` — 629 identical lines about the building, where what
    needs fixing is actually different.
    """
    placed = _room("placed", [])
    unplaced = _room("unplaced", [])
    document = _document(
        rooms=[placed, unplaced, _room("ok", _SQUARE)],
        elements=[_element("placed", "OST_Rooms", geom_kind="point",
                           p0_mm=[100.0, 100.0, 0.0],
                           params={"ROOM_UPPER_OFFSET": 3000}),
                  _element("unplaced", "OST_Rooms", geom_kind="bbox_only",
                           params={"ROOM_UPPER_OFFSET": 3000}),
                  _room_element("ok")])
    _, witness = spatial_model_from_l0(document)
    assert witness.unmeasured_reasons["room_placed_but_not_enclosed"] == 1
    assert witness.unmeasured_reasons["room_not_placed"] == 1
    assert witness.unmeasured_reasons["ring_degenerate"] == 0
    assert witness.rooms_measured == 1


def test_the_room_phase_is_not_readable_and_the_gap_is_named_not_guessed():
    """There is NO room phase in L0 — and that is a fact about the lift, not about the building.

    Measured on MNVNK: `phase_created` is empty for 1102 rooms out of
    1102, while the same C# helper (`decompile/extract.py`,
    `__PutGroupingState`) fills it for 21 categories — for walls, AGK
    10305 · PD 215 · Intermediate 126. So the question WAS asked and the
    building answered with emptiness: a room's phase does not live in
    `Element.CreatedPhaseId`. The test holds the boundary: as long as
    there is no phase, no inference about it may be made, and «не
    замкнуто» must speak honestly about itself.
    """
    document = _document(
        rooms=[_room("r", _SQUARE)],
        elements=[_room_element("r")])
    model, _ = spatial_model_from_l0(document)
    assert model.rooms
    room_rows = [e for e in document.elements if e.category == "OST_Rooms"]
    assert room_rows and all(e.phase_created is None for e in room_rows)
    from kir.design_check import _UNMEASURED_RU
    assert "ДРУГОЙ ФАЗЕ" in _UNMEASURED_RU["room_placed_but_not_enclosed"]
