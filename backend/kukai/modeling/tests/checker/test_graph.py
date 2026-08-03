"""Connectivity-graph + apartment-derivation tests (design §4/§5)."""
import networkx as nx

from kukai.modeling.checker.graph import (
    OUTSIDE, PUBLIC_CIRCULATION, build_graph, derive_apartments, is_public,
    stair_node, Apartment,
    stair_nodes, occupied_levels, ground_level_ids, building_entrance_rooms,
)
from kukai.modeling.checker.spatial_model import SpatialModel, RoomFunction as RF
from kukai.modeling.checker.fixtures.builders import make_good


# --- constants / predicates ------------------------------------------------

def test_outside_sentinel_value():
    assert OUTSIDE == "OUTSIDE"


def test_public_circulation_set_is_public_and_exported():
    assert PUBLIC_CIRCULATION == frozenset({
        RF.КОРИДОР, RF.ЛЕСТНИЦА, RF.ЛИФТ_ХОЛЛ, RF.ВХОДНАЯ_ГРУППА,
    })


def test_is_public_true_for_circulation_functions():
    for f in (RF.КОРИДОР, RF.ЛЕСТНИЦА, RF.ЛИФТ_ХОЛЛ, RF.ВХОДНАЯ_ГРУППА):
        assert is_public(f) is True


def test_is_public_false_for_private_functions():
    for f in (RF.ЖИЛАЯ, RF.КУХНЯ, RF.САНУЗЕЛ, RF.ПРИХОЖАЯ, RF.ТЕХ, RF.ПРОЧЕЕ):
        assert is_public(f) is False


def test_stair_node_id_builder():
    assert stair_node("s01") == "stair:s01"


# --- build_graph -----------------------------------------------------------

def test_build_graph_has_all_rooms_outside_and_stair_nodes():
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    # every room is a node
    for r in model.rooms:
        assert g.has_node(r.id)
        assert g.nodes[r.id]["kind"] == "room"
    # the synthetic OUTSIDE node
    assert g.has_node(OUTSIDE)
    assert g.nodes[OUTSIDE]["kind"] == "outside"
    # one node per stair run
    for s in model.stairs:
        assert g.has_node(f"stair:{s.id}")
        assert g.nodes[f"stair:{s.id}"]["kind"] == "stair"
    assert g.number_of_nodes() == len(model.rooms) + 1 + len(model.stairs)


def test_build_graph_interior_door_edges():
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    for d in model.doors:
        if d.is_exterior:
            continue
        assert g.has_edge(d.from_room_id, d.to_room_id)
        assert g.edges[d.from_room_id, d.to_room_id]["kind"] == "door"
        assert g.edges[d.from_room_id, d.to_room_id]["door_id"] == d.id


def test_build_graph_exterior_door_links_room_to_outside():
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    ext = [d for d in model.doors if d.is_exterior]
    assert ext, "make_good must have at least one exterior door"
    for d in ext:
        room = d.from_room_id or d.to_room_id
        assert g.has_edge(room, OUTSIDE)
        assert g.edges[room, OUTSIDE]["kind"] == "exterior"
        assert g.edges[room, OUTSIDE]["door_id"] == d.id


def test_build_graph_every_room_reachable_from_outside_in_good():
    # The whole point: a habitable floor is connected from the building entrance (design §5).
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    reachable = nx.node_connected_component(g, OUTSIDE)
    for r in model.rooms:
        assert r.id in reachable, f"{r.id} unreachable from OUTSIDE in make_good()"


def test_build_graph_stair_vertical_edge_between_consecutive_landings():
    # Build a 2-level model so a stair has DISTINCT base/top landings to bridge.
    g2 = build_graph(SpatialModel.model_validate(_two_level_model()))
    # the stair node bridges the two landing rooms
    assert g2.has_edge("stair:s01", "land0")
    assert g2.has_edge("stair:s01", "land1")
    assert g2.edges["stair:s01", "land0"]["kind"] == "stair"
    assert g2.edges["stair:s01", "land1"]["kind"] == "stair"
    # land0 and land1 are therefore connected THROUGH the stair node
    assert nx.has_path(g2, "land0", "land1")


def _two_level_model() -> dict:
    """Two occupied levels, each with a лестница landing room, bridged by one stair run."""
    return {
        "building_id": "two_level",
        "levels": [
            {"id": "L0", "name": "Этаж 1", "elevation_mm": 0.0, "index": 0},
            {"id": "L1", "name": "Этаж 2", "elevation_mm": 3000.0, "index": 1},
        ],
        "rooms": [
            {"id": "land0", "name": "Лестничная клетка", "number": "", "level_id": "L0",
             "function": "лестница", "area_m2": 10.0, "height_mm": 2700.0,
             "boundary": [[0, 0], [3000, 0], [3000, 3000], [0, 3000]],
             "apartment_id": None, "has_window": False, "window_area_m2": 0.0},
            {"id": "land1", "name": "Лестничная клетка", "number": "", "level_id": "L1",
             "function": "лестница", "area_m2": 10.0, "height_mm": 2700.0,
             "boundary": [[0, 0], [3000, 0], [3000, 3000], [0, 3000]],
             "apartment_id": None, "has_window": False, "window_area_m2": 0.0},
        ],
        "doors": [
            {"id": "d_ext0", "level_id": "L0", "location": [1500, 0], "width_mm": 1200.0,
             "from_room_id": "land0", "to_room_id": None, "is_exterior": True},
        ],
        "windows": [],
        "stairs": [
            {"id": "s01", "base_level_id": "L0", "top_level_id": "L1", "base_z": 0.0,
             "top_z": 3000.0, "run_width_mm": 1200.0, "riser_count": 16,
             "tread_depth_mm": 280.0,
             "footprint": [[0, 0], [3000, 0], [3000, 3000], [0, 3000]]},
        ],
        "walls": [],
    }


# --- helpers ---------------------------------------------------------------

def test_stair_nodes_extracts_all_stair_kind_nodes():
    g2 = build_graph(SpatialModel.model_validate(_two_level_model()))
    assert stair_nodes(g2) == ["stair:s01"]


def test_stair_nodes_empty_when_no_stairs():
    d = _two_level_model()
    d["stairs"] = []  # drop the stair run -> no stair nodes
    model = SpatialModel.model_validate(d)
    assert stair_nodes(build_graph(model)) == []


def test_occupied_levels_returns_levels_with_rooms_sorted_by_index():
    model = SpatialModel.model_validate(_two_level_model())
    levels = occupied_levels(model)
    assert [lvl.id for lvl in levels] == ["L0", "L1"]


def test_occupied_levels_skips_empty_levels():
    d = _two_level_model()
    # add a third level with NO rooms — it must not appear
    d["levels"].append({"id": "L2", "name": "Этаж 3", "elevation_mm": 6000.0, "index": 2})
    model = SpatialModel.model_validate(d)
    assert [lvl.id for lvl in occupied_levels(model)] == ["L0", "L1"]


def test_ground_level_ids_are_levels_with_an_exterior_door():
    model = SpatialModel.model_validate(_two_level_model())
    # the single exterior door d_ext0 is on L0
    assert ground_level_ids(model) == {"L0"}


def test_building_entrance_rooms_are_from_rooms_of_exterior_doors():
    model = SpatialModel.model_validate(_two_level_model())
    assert building_entrance_rooms(model) == ["land0"]


# --- derive_apartments -----------------------------------------------------

def test_derive_apartments_finds_exactly_one_apartment_in_good():
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    apts = derive_apartments(model, g)
    assert isinstance(apts, list)
    assert len(apts) == 1


def test_derive_apartment_contains_the_private_rooms():
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    (apt,) = derive_apartments(model, g)
    # прихожая + кухня-гостиная + спальня + санузел = the four private rooms of A1
    assert apt.room_ids == {"hall", "kit", "bed", "wc"}
    # no public-circulation room leaked into the apartment
    assert "cor" not in apt.room_ids
    assert "stair" not in apt.room_ids
    assert "ent" not in apt.room_ids


def test_derive_apartment_entrance_is_the_corridor_door():
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    (apt,) = derive_apartments(model, g)
    # the прихожая↔коридор door (d_cor_hall) is the apartment's single entrance
    assert apt.entrance_door_ids == {"d_cor_hall"}


def test_derive_apartment_id_set_from_stamped_apartment_id():
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    (apt,) = derive_apartments(model, g)
    assert apt.apartment_id == "A1"


def test_derive_apartment_prihozhaya_ids_are_the_prihozhaya_rooms():
    model = SpatialModel.model_validate(make_good())
    g = build_graph(model)
    (apt,) = derive_apartments(model, g)
    # 'hall' is the прихожая room of A1 (RoomFunction.ПРИХОЖАЯ)
    assert apt.prihozhaya_ids == {"hall"}


def test_derive_apartments_two_components_two_apartments():
    # Two private clusters, each hung off the public corridor by its own entrance door.
    model = SpatialModel.model_validate(_two_apartment_model())
    g = build_graph(model)
    apts = derive_apartments(model, g)
    assert len(apts) == 2
    comps = {frozenset(a.room_ids) for a in apts}
    assert frozenset({"h1", "r1"}) in comps
    assert frozenset({"h2", "r2"}) in comps
    # both apartments carry their stamped id
    assert {a.apartment_id for a in apts} == {"AP1", "AP2"}


def _two_apartment_model() -> dict:
    """One public corridor + two independent private apartments off it."""
    return {
        "building_id": "two_apt",
        "levels": [{"id": "L0", "name": "Этаж 1", "elevation_mm": 0.0, "index": 0}],
        "rooms": [
            {"id": "cor", "name": "Коридор", "number": "", "level_id": "L0",
             "function": "коридор", "area_m2": 9.0, "height_mm": 2700.0,
             "boundary": [], "apartment_id": None,
             "has_window": False, "window_area_m2": 0.0},
            {"id": "h1", "name": "Прихожая", "number": "", "level_id": "L0",
             "function": "прихожая", "area_m2": 5.0, "height_mm": 2700.0,
             "boundary": [], "apartment_id": "AP1",
             "has_window": False, "window_area_m2": 0.0},
            {"id": "r1", "name": "Спальня", "number": "", "level_id": "L0",
             "function": "жилая", "area_m2": 14.0, "height_mm": 2700.0,
             "boundary": [], "apartment_id": "AP1",
             "has_window": True, "window_area_m2": 2.5},
            {"id": "h2", "name": "Прихожая", "number": "", "level_id": "L0",
             "function": "прихожая", "area_m2": 5.0, "height_mm": 2700.0,
             "boundary": [], "apartment_id": "AP2",
             "has_window": False, "window_area_m2": 0.0},
            {"id": "r2", "name": "Спальня", "number": "", "level_id": "L0",
             "function": "жилая", "area_m2": 14.0, "height_mm": 2700.0,
             "boundary": [], "apartment_id": "AP2",
             "has_window": True, "window_area_m2": 2.5},
        ],
        "doors": [
            {"id": "d_c_h1", "level_id": "L0", "location": [0, 0], "width_mm": 900.0,
             "from_room_id": "cor", "to_room_id": "h1", "is_exterior": False},
            {"id": "d_h1_r1", "level_id": "L0", "location": [0, 0], "width_mm": 900.0,
             "from_room_id": "h1", "to_room_id": "r1", "is_exterior": False},
            {"id": "d_c_h2", "level_id": "L0", "location": [0, 0], "width_mm": 900.0,
             "from_room_id": "cor", "to_room_id": "h2", "is_exterior": False},
            {"id": "d_h2_r2", "level_id": "L0", "location": [0, 0], "width_mm": 900.0,
             "from_room_id": "h2", "to_room_id": "r2", "is_exterior": False},
        ],
        "windows": [],
        "stairs": [],
        "walls": [],
    }
