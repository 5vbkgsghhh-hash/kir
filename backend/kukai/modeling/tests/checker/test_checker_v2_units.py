"""Checker v2 unit-level guarantees: derivation, extraction honesty, landing matching,
verdict semantics, and the v1-compatibility guard (flag OFF must stay byte-identical
in behaviour)."""
import pytest

from kukai.modeling.checker.spatial_model import SpatialModel, Verdict


@pytest.fixture()
def v2(monkeypatch):
    monkeypatch.setenv("KUKAI_CHECKER_V2", "1")


@pytest.fixture()
def v1(monkeypatch):
    monkeypatch.delenv("KUKAI_CHECKER_V2", raising=False)


# ------------------------------------------------------------------- extraction honesty

_RAW_TWO_LEVEL = {
    "building_id": "raw2",
    "levels": [{"id": "L0", "name": "Э1", "elevation_mm": 0.0, "index": 0},
               {"id": "L1", "name": "Э2", "elevation_mm": 3000.0, "index": 1}],
    "rooms": [
        {"id": "ent", "name": "Входная группа", "level_id": "L0", "area_m2": 12.0,
         "height_mm": 0.0,   # ← missing/zero in Revit
         "boundary": [[0, 0], [3000, 0], [3000, 4000], [0, 4000]]},
        {"id": "st0", "name": "Лестничная клетка", "level_id": "L0", "area_m2": 10.0,
         "height_mm": 2700.0, "boundary": [[3000, 0], [5500, 0], [5500, 4000], [3000, 4000]]},
        {"id": "st1", "name": "Лестничная клетка", "level_id": "L1", "area_m2": 10.0,
         "height_mm": 2700.0, "boundary": [[3000, 0], [5500, 0], [5500, 4000], [3000, 4000]]},
    ],
    "doors": [
        {"id": "dx", "level_id": "L0", "location": [1500, 0], "width_mm": 1200.0,
         "from_room_id": "ent", "to_room_id": None, "is_exterior": True},
        {"id": "d0", "level_id": "L0", "location": [3000, 2000], "width_mm": 900.0,
         "from_room_id": "ent", "to_room_id": "st0", "is_exterior": False},
    ],
    "windows": [], "stairs": [], "walls": [],
}


def test_normalize_v2_does_not_fabricate_heights(v2):
    from kukai.modeling.checker.extractor import normalize
    d = normalize(_RAW_TWO_LEVEL)
    ent = next(r for r in d["rooms"] if r["id"] == "ent")
    assert ent["height_mm"] is None          # v1 rewrote 0.0 → 2700.0


def test_normalize_v1_keeps_legacy_default(v1):
    from kukai.modeling.checker.extractor import normalize
    d = normalize(_RAW_TWO_LEVEL)
    ent = next(r for r in d["rooms"] if r["id"] == "ent")
    assert ent["height_mm"] == 2700.0        # legacy behaviour preserved under the flag


def test_synthesized_stairs_carry_no_invented_dimensions(v2):
    from kukai.modeling.checker.extractor import normalize
    d = normalize(_RAW_TWO_LEVEL)
    assert len(d["stairs"]) == 1
    s = d["stairs"][0]
    assert s["kind"] == "inferred"
    assert s["run_width_mm"] is None and s["riser_count"] is None
    assert s["tread_depth_mm"] is None       # v1 invented 1100/17/280 pass-by-construction


def test_inferred_stairs_cannot_certify_vertical_circulation(v2):
    """A building whose only vertical link is INFERRED (no stair element — e.g. flights
    deleted, landings remain) must not read PASS: HAB011 is mandatory-when-stairs-exist
    and has zero measured subjects → NOT_EVALUATED."""
    from kukai.modeling.checker.engine import run
    from kukai.modeling.checker.extractor import normalize
    d = normalize(_RAW_TWO_LEVEL)
    rep = run(SpatialModel.model_validate(d))
    assert rep.passed is False
    assert rep.verdict is Verdict.NOT_EVALUATED
    assert rep.coverage is not None and "HAB011" in rep.coverage.mandatory_not_evaluated
    assert any(v.rule_id == "HAB011" and "INFERRED" in v.msg for v in rep.warnings)


def test_normalize_v2_never_trusts_raw_exterior_flags(v2):
    from kukai.modeling.checker.extractor import normalize
    d = normalize(_RAW_TWO_LEVEL)
    assert all(door["is_exterior"] is False for door in d["doors"])  # derive.py decides


def test_normalize_v2_stamps_apartment_from_department(v2):
    from kukai.modeling.checker.extractor import normalize
    raw = {**_RAW_TWO_LEVEL,
           "rooms": [{**_RAW_TWO_LEVEL["rooms"][0], "department": "Кв. 12"}]}
    d = normalize(raw)
    assert d["rooms"][0]["apartment_id"] == "Кв. 12"


# ------------------------------------------------------------------ derivation details

def test_derivation_reestablishes_exteriority_positively(v2):
    """The entrance (is_exterior stripped by normalize) is re-derived from envelope
    membership; the interior door stays interior."""
    from kukai.modeling.checker.derive import derive
    from kukai.modeling.checker.extractor import normalize
    from kukai.modeling.checker.thresholds import THRESHOLDS
    dmodel, drep = derive(
        SpatialModel.model_validate(normalize(_RAW_TWO_LEVEL)), THRESHOLDS)
    by_id = {d.id: d for d in dmodel.doors}
    assert by_id["dx"].is_exterior is True
    assert by_id["d0"].is_exterior is False
    assert drep.ground_level_ids == {"L0"}


def test_phantom_door_is_contradicted_and_dropped(v2):
    from kukai.modeling.checker.derive import DoorStatus, derive
    from kukai.modeling.checker.fixtures.builders import make_good
    from kukai.modeling.checker.thresholds import THRESHOLDS
    d = make_good()
    for door in d["doors"]:
        if door["id"] == "d_hall_bed":
            door["location"] = [1000, 9000]   # deep inside the kitchen, far from hall|bed
    _, drep = derive(SpatialModel.model_validate(d), THRESHOLDS)
    assert drep.doors["d_hall_bed"].status is DoorStatus.CONTRADICTED
    assert "d_hall_bed" in drep.dropped_door_ids


def test_declared_prochee_upgraded_from_name(v2):
    from kukai.modeling.checker.derive import derive
    from kukai.modeling.checker.fixtures.builders import make_good
    from kukai.modeling.checker.spatial_model import RoomFunction
    from kukai.modeling.checker.thresholds import THRESHOLDS
    d = make_good()
    for r in d["rooms"]:
        if r["id"] == "bed":
            r["name"] = "Bedroom 1"
            r["function"] = "прочее"
    dmodel, drep = derive(SpatialModel.model_validate(d), THRESHOLDS)
    bed = next(r for r in dmodel.rooms if r.id == "bed")
    assert bed.function is RoomFunction.ЖИЛАЯ
    assert drep.rooms["bed"].function_upgraded_from_name is True


def test_known_nonhabitable_names_are_not_unclassified(v2):
    from kukai.modeling.checker.derive import derive
    from kukai.modeling.checker.fixtures.builders import make_good
    from kukai.modeling.checker.thresholds import THRESHOLDS
    d = make_good()
    d["rooms"].append({
        "id": "balk", "name": "Балкон", "number": "", "level_id": "L0",
        "function": "прочее", "area_m2": 4.5, "height_mm": 2700.0,
        "boundary": [[8000, 4000], [9500, 4000], [9500, 7000], [8000, 7000]],
        "apartment_id": None, "has_window": False, "window_area_m2": 0.0})
    d["doors"].append({
        "id": "d_bed_balk", "level_id": "L0", "location": [8000, 5000],
        "width_mm": 800.0, "from_room_id": "bed", "to_room_id": "balk",
        "is_exterior": False})
    _, drep = derive(SpatialModel.model_validate(d), THRESHOLDS)
    assert "balk" not in drep.unclassified_room_ids
    assert drep.classification_coverage == 1.0


# --------------------------------------------------------- multi-core landing matching

def test_stair_attaches_to_the_core_under_its_footprint_not_list_order(v2):
    """Probe L2: v1 attached every stair to the FIRST лестница room on the level; with
    core-B landings listed first, the stair bridged the wrong core. v2 matches by
    footprint intersection."""
    from kukai.modeling.checker.graph import build_graph
    model = SpatialModel.model_validate({
        "building_id": "two_cores",
        "levels": [{"id": "L0", "name": "Э1", "elevation_mm": 0.0, "index": 0},
                   {"id": "L1", "name": "Э2", "elevation_mm": 3000.0, "index": 1}],
        "rooms": [
            # core B listed FIRST on both levels (the v1 trap)
            {"id": "stB0", "name": "Лестничная клетка", "number": "", "level_id": "L0",
             "function": "лестница", "area_m2": 9.0, "height_mm": 2700.0,
             "boundary": [[6000, 0], [9000, 0], [9000, 3000], [6000, 3000]],
             "apartment_id": None, "has_window": False, "window_area_m2": 0.0},
            {"id": "stB1", "name": "Лестничная клетка", "number": "", "level_id": "L1",
             "function": "лестница", "area_m2": 9.0, "height_mm": 2700.0,
             "boundary": [[6000, 0], [9000, 0], [9000, 3000], [6000, 3000]],
             "apartment_id": None, "has_window": False, "window_area_m2": 0.0},
            {"id": "stA0", "name": "Лестничная клетка", "number": "", "level_id": "L0",
             "function": "лестница", "area_m2": 9.0, "height_mm": 2700.0,
             "boundary": [[0, 0], [3000, 0], [3000, 3000], [0, 3000]],
             "apartment_id": None, "has_window": False, "window_area_m2": 0.0},
            {"id": "stA1", "name": "Лестничная клетка", "number": "", "level_id": "L1",
             "function": "лестница", "area_m2": 9.0, "height_mm": 2700.0,
             "boundary": [[0, 0], [3000, 0], [3000, 3000], [0, 3000]],
             "apartment_id": None, "has_window": False, "window_area_m2": 0.0},
        ],
        "doors": [], "windows": [], "walls": [],
        "stairs": [
            {"id": "sA", "base_level_id": "L0", "top_level_id": "L1", "base_z": 0.0,
             "top_z": 3000.0, "run_width_mm": 1200.0, "riser_count": 17,
             "tread_depth_mm": 280.0,
             "footprint": [[0, 0], [3000, 0], [3000, 3000], [0, 3000]]},   # core A!
        ],
    })
    g = build_graph(model)
    assert g.has_edge("stair:sA", "stA0") and g.has_edge("stair:sA", "stA1")
    assert not g.has_edge("stair:sA", "stB0") and not g.has_edge("stair:sA", "stB1")


def test_ground_band_constant_stays_in_sync(v2):
    from kukai.modeling.checker import graph
    from kukai.modeling.checker.thresholds import THRESHOLDS
    assert graph._GROUND_ELEVATION_BAND_MM == THRESHOLDS.ground_elevation_band_mm


# ------------------------------------------------------------------ v1 behaviour guard

def test_v1_flag_off_keeps_legacy_semantics(v1):
    """Belt-and-braces beyond the existing 188-test suite: with the flag OFF the v1
    theater is intentionally preserved (report has no verdict; empty model 'passes'
    with INFO HAB000) so the flip to v2 is a conscious operator act, not a silent
    behaviour change."""
    from kukai.modeling.checker.engine import run
    from kukai.modeling.checker.fixtures.builders import make_good
    rep = run(SpatialModel.model_validate(make_good()))
    assert rep.passed is True and rep.verdict is None and rep.coverage is None
    empty = run(SpatialModel(building_id="empty"))
    assert empty.passed is True
    assert any(v.rule_id == "HAB000" for v in empty.info)
