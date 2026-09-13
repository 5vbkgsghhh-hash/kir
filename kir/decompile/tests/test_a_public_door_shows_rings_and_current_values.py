# -*- coding: utf-8 -*-
"""The public door shows the opening RINGS and the CURRENT values of the
editable fields.

🔴 WHY THESE TWO FIELDS WERE ADDED (08.09.2026, a request from the door's
reader, via the lead). `read_element` answered about an element in
detail, but did not answer at all two questions without which the reader
cannot show the element to a human:

* "what openings does it have and where are they" — `supported` carries
  the L0 ROW's fields, while the rings sit in the L1 node, and the reader
  would have had to find them itself;
* "what currently sits in the editable fields" — `supported` answers
  about something else: the door's `offset_mm` is not in it at all, it is
  in `op_params`.

The reader would assemble both answers itself — that is, it would set up
a SECOND law about the same thing. A second law about the node's shape
would lie immediately: the shape DIFFERS across buildings.

    building            where the rings live         rings in the slice
    ──────────────────  ──────────────────────────  ─────────────
    bench_A             params.holes                      1
    k4_geom_wave2       params.holes                      6
    len_ar_me_r24_v1    params.holes                      3
    k2v33_join2         params.contour.holes              3

So `openings` is computed as `capture_edit._holes_of` + `_points_of` — the
very same ones by which `_edit_opening` reads and edits a ring — and
`editable_now` is computed as `capture_edit._before_values` — the very
same one by which an edit takes its `before` and by which `apply_patch`
checks "is that really what's there." One law per question.

🔴 WHAT THIS FILE DOES NOT PROVE. It is not about scale: the slices are
dozens of neighbors. It proves that both fields read FOUR different
buildings and TWO different node shapes under one law, and that the
reading depends on the subject (it moves after an edit).
"""
from __future__ import annotations

import copy
import json
import pathlib
import shutil

import pytest

from kir.decompile import capture_api as API
from kir.decompile import capture_edit as CE

SLICES = pathlib.Path(__file__).resolve().parent / "capture_slices"

#: Buildings with an opening in a slab, and the NUMBER OF RINGS on their
#: seed slab. The numbers are taken from a measurement in a neighboring
#: file (`test_one_rule_holds_on_four_different_buildings`), i.e. a
#: PROPERTY OF THE BUILDING, not a reading from the code under test: a pin
#: computed by the same code would stay green under any bug in it.
RING_BUILDINGS = {"bench_A": 1, "k4_geom_wave2": 6,
                  "len_ar_me_r24_v1": 3, "k2v33_join2": 3}
#: Buildings with an opening in a wall.
WALL_BUILDINGS = ("mnvnk_k1_layers_walls", "k4_geom_wave2_walls")


def _meta(name: str) -> dict:
    return json.loads((SLICES / name / "SLICE.json").read_text(encoding="utf-8"))


@pytest.fixture(params=sorted(RING_BUILDINGS))
def ring_building(request, tmp_path):
    name = request.param
    work = tmp_path / name
    shutil.copytree(SLICES / name, work)
    return {"name": name, "path": work, "seeds": _meta(name)["семена"],
            "rings": RING_BUILDINGS[name]}


@pytest.fixture(params=WALL_BUILDINGS)
def wall_building(request, tmp_path):
    name = request.param
    work = tmp_path / name
    shutil.copytree(SLICES / name, work)
    return {"name": name, "path": work, "seeds": _meta(name)["семена"]}


def _moved(ring: list, dx: float) -> list:
    return [[point[0] + dx, point[1]] for point in ring]


# ── openings ──────────────────────────────────────────────────────────────
def test_the_door_shows_every_ring_of_a_slab_on_four_buildings(ring_building):
    """The rings are visible, and there are EXACTLY AS MANY as the
    building has — across two node shapes."""
    capture = CE.open_capture(ring_building["path"])
    host = ring_building["seeds"]["opening_host"]
    read = API.read_element(capture, host)

    assert len(read.openings) == ring_building["rings"], (
        f"{ring_building['name']}: дверь показала {len(read.openings)} колец, "
        f"а у плиты {ring_building['rings']}")
    for index, ring in enumerate(read.openings):
        assert ring.index == index, "номера колец обязаны идти по порядку"
        assert ring.why is None, ring.why
        assert isinstance(ring.contour_mm, list) and len(ring.contour_mm) >= 3
        for point in ring.contour_mm:
            assert isinstance(point, list) and len(point) == 2
            assert all(isinstance(value, (int, float)) for value in point)
    # And the same thing is visible through `to_dict` — the reader takes
    # JSON, not an object.
    payload = read.to_dict()
    assert len(payload["openings"]) == ring_building["rings"]
    assert payload["openings"][0]["contour_mm"] == read.openings[0].contour_mm


def test_the_shown_ring_is_the_one_the_patch_binds_to(ring_building):
    """The ring in `openings` is the SAME one the edit calls its
    `before`.

    Two answers to one question, from two doors, must agree; diverging,
    they would show the reader one thing while editing another.
    """
    capture = CE.open_capture(ring_building["path"])
    host = ring_building["seeds"]["opening_host"]
    read = API.read_element(capture, host)
    proposal = API.propose_patch(
        capture, host, {"opening_index": 0,
                        "opening_contour_mm": _moved(read.openings[0].contour_mm, 1.0)},
        source_binding=API.source_binding(capture))
    assert proposal.admissible, proposal.refusal
    assert proposal.before["opening_contour_mm"] == read.openings[0].contour_mm


def test_the_shown_rings_follow_the_edit(ring_building):
    """🔴 THE READING DEPENDS ON THE SUBJECT. An instrument whose number
    does not move after an edit measures nothing: ring 0 gets edited —
    exactly it moves.
    """
    capture = CE.open_capture(ring_building["path"])
    host = ring_building["seeds"]["opening_host"]
    before = API.read_element(capture, host).openings
    target = _moved(before[0].contour_mm, 25.0)

    assert CE.edit_element(capture, host, {"opening_index": 0,
                                           "opening_contour_mm": target}
                           ).refusal is None
    after = API.read_element(capture, host).openings
    assert len(after) == len(before)
    assert after[0].contour_mm == target, "правленое кольцо не поехало в ответе"
    assert after[0].contour_mm != before[0].contour_mm
    for index in range(1, len(before)):
        assert after[index].contour_mm == before[index].contour_mm, (
            f"кольцо {index} сдвинулось, хотя правили нулевое")


@pytest.mark.parametrize("what", ("door", "wall_opening"))
def test_an_element_without_rings_says_why_instead_of_going_silent(
        ring_building, wall_building, what):
    """🔴 THERE IS NO SUCH THING AS AN EMPTY LIST. "No openings" is three
    different facts, and a reader that does not distinguish them goes off
    to fix the wrong thing.
    """
    if what == "door":
        capture = CE.open_capture(ring_building["path"])
        key = ring_building["seeds"]["door"]
        expect = "профиль перекрытия или потолка"
    else:
        capture = CE.open_capture(wall_building["path"])
        key = wall_building["seeds"]["wall_openings"][0]
        expect = "профиль перекрытия или потолка"
    read = API.read_element(capture, key)
    assert len(read.openings) == 1, read.openings
    ring = read.openings[0]
    assert ring.index is None and ring.contour_mm is None
    assert ring.why and expect in ring.why, ring.why


def test_an_atom_slab_names_its_atom_reason_not_an_empty_list(ring_building):
    """An ATOM slab answers with the atom's reason, not with emptiness.

    A genuine ring-category atom is sought in the slice; if there is none,
    there is nothing to check — and this is an EXPLICIT skip, not a
    silently green test.
    """
    capture = CE.open_capture(ring_building["path"])
    atom = next((key for key, element in capture.elements.items()
                 if element.category in ("OST_Floors", "OST_Ceilings")
                 and (capture.by_source.get(key) or {}).get("kind") == "atom"), None)
    if atom is None:
        pytest.skip(f"{ring_building['name']}: плиты-атома в срезе нет")
    read = API.read_element(capture, atom)
    assert len(read.openings) == 1
    assert read.openings[0].contour_mm is None
    assert "поднят атомом" in read.openings[0].why, read.openings[0].why


# ── editable_now ──────────────────────────────────────────────────────────
def test_the_door_shows_current_values_of_exactly_the_editable_fields(ring_building):
    """`editable_now` answers about the SAME fields that `editable_fields`
    names."""
    capture = CE.open_capture(ring_building["path"])
    door = ring_building["seeds"]["door"]
    read = API.read_element(capture, door)

    assert set(read.editable_fields) == set(CE._DOOR_FIELDS)
    assert set(read.editable_now) <= set(read.editable_fields), (
        "дверь показала текущее значение поля, которого не объявляла правимым")
    # `offset_mm` is exactly what is ABSENT from `supported`: it lives in
    # the node.
    assert "offset_mm" in read.editable_now
    assert "offset_mm" not in read.supported
    assert read.editable_now["offset_mm"] == read.op_params.get("offset_mm")
    assert read.to_dict()["editable_now"] == read.editable_now


def test_current_values_move_with_the_edit(ring_building):
    """The reading moves after an edit — otherwise it is not a reading but
    a copy."""
    capture = CE.open_capture(ring_building["path"])
    door = ring_building["seeds"]["door"]
    before = API.read_element(capture, door).editable_now
    assert CE.edit_element(capture, door, {"offset_mm": 1234.0}).refusal is None
    after = API.read_element(capture, door).editable_now
    assert after["offset_mm"] == 1234.0
    assert after["offset_mm"] != before["offset_mm"]
    # Neighboring editable fields are left untouched.
    assert after["symbol"] == before["symbol"]


def test_current_values_agree_with_what_a_patch_expects(ring_building):
    """`editable_now` and a patch's `before` are ONE law, hence one
    value."""
    capture = CE.open_capture(ring_building["path"])
    door = ring_building["seeds"]["door"]
    read = API.read_element(capture, door)
    proposal = API.propose_patch(capture, door, {"offset_mm": 999.0},
                                 source_binding=API.source_binding(capture))
    assert proposal.before["offset_mm"] == read.editable_now["offset_mm"]


def test_the_slab_shows_the_ring_the_contract_would_touch(ring_building):
    """For a slab, `editable_now` shows the ring that a patch WITHOUT a
    number will touch.

    Zero is not the door's invention but the contract's own default
    (`_edit_opening`: `change.get("opening_index", 0)`).
    """
    capture = CE.open_capture(ring_building["path"])
    host = ring_building["seeds"]["opening_host"]
    read = API.read_element(capture, host)
    assert read.editable_now.get("opening_index") == 0
    assert read.editable_now.get("opening_contour_mm") == read.openings[0].contour_mm


def test_a_wall_opening_shows_its_two_corners_by_the_same_law(wall_building):
    """For a wall opening, `editable_now` names ITS OWN fields, not
    someone else's."""
    capture = CE.open_capture(wall_building["path"])
    key = wall_building["seeds"]["wall_openings"][0]
    read = API.read_element(capture, key)
    assert set(read.editable_fields) == set(CE._WALL_OPENING_FIELDS)
    assert set(read.editable_now) == set(CE._WALL_OPENING_FIELDS)
    # In these slices the opening came up as an atom — meaning there are
    # NO values, and the door says `None` rather than inventing them from
    # the bounding box.
    assert read.node_kind == "atom"
    assert all(value is None for value in read.editable_now.values()), read.editable_now


def test_a_supported_wall_opening_shows_the_corners_that_are_there(tmp_path):
    """And where the opening DID come up, the door shows both corners, and
    they move."""
    directory = tmp_path / "demo"
    API.write_demo_capture(directory, wall_opening=True)
    capture = CE.open_capture(directory)
    key = API.DEMO_WALL_OPENING
    read = API.read_element(capture, key)
    assert read.editable_now == {"opening_p0_mm": [6000.0, 0.0, 900.0],
                                 "opening_p1_mm": [7000.0, 0.0, 2100.0]}
    assert CE.edit_element(capture, key, {"opening_p0_mm": [6000.0, 0.0, 800.0],
                                          "opening_p1_mm": [7500.0, 0.0, 2200.0]}
                           ).refusal is None
    assert API.read_element(capture, key).editable_now == {
        "opening_p0_mm": [6000.0, 0.0, 800.0],
        "opening_p1_mm": [7500.0, 0.0, 2200.0]}


def test_an_uneditable_category_shows_nothing_and_claims_nothing(ring_building):
    """For a category the contract does not edit, both fields are EMPTY —
    honestly so."""
    capture = CE.open_capture(ring_building["path"])
    foreign = next((key for key, element in capture.elements.items()
                    if element.category not in API._EDITABLE), None)
    assert foreign is not None, "в срезе нет ни одной неправимой категории"
    read = API.read_element(capture, foreign)
    assert read.editable_fields == ()
    assert read.editable_now == {}


# ── the previous doors have not shifted ─────────────────────────────────
def test_the_older_answer_did_not_move(ring_building):
    """An extension is not a replacement: the previous response keys are
    still there, with the same meaning."""
    capture = CE.open_capture(ring_building["path"])
    payload = API.read_element(capture, ring_building["seeds"]["door"]).to_dict()
    for name in ("schema", "element_id", "unique_id", "category", "type_name",
                 "level_name", "node_kind", "op_name", "supported", "op_params",
                 "host", "depends_on", "referenced_by", "fields",
                 "editable_fields", "field_states_from"):
        assert name in payload, f"прежний ключ ответа {name} исчез"
    assert payload["schema"] == API.API_SCHEMA
    assert payload["field_states_from"] == "kir.decompile.field_ledger"
    # The new keys sit alongside, not in place of the old ones.
    assert set(payload) - {"openings", "editable_now"} == {
        "schema", "element_id", "unique_id", "category", "type_name",
        "level_name", "node_kind", "op_name", "supported", "op_params",
        "host", "depends_on", "referenced_by", "fields", "editable_fields",
        "field_states_from"}


def test_reading_an_element_writes_nothing(ring_building):
    """Reading writes NOTHING — not to the in-memory capture, not to
    disk."""
    capture = CE.open_capture(ring_building["path"])
    host = ring_building["seeds"]["opening_host"]
    snapshot = {item.name: item.read_bytes()
                for item in sorted(ring_building["path"].iterdir()) if item.is_file()}
    nodes = copy.deepcopy(capture.nodes)
    read = API.read_element(capture, host)
    # The ring in the response is a COPY: editing the response has no
    # obligation to move the building.
    if read.openings[0].contour_mm:
        read.openings[0].contour_mm.append([0.0, 0.0])
    assert capture.nodes == nodes, "чтение изменило узлы"
    assert capture.edits == []
    assert {item.name: item.read_bytes()
            for item in sorted(ring_building["path"].iterdir())
            if item.is_file()} == snapshot
