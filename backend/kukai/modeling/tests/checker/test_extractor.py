"""Pure tests for the extractor's normalization seam (no live model): the C# payload becomes a
valid SpatialModel and room functions are assigned from RU names via classify.py."""
from kukai.modeling.checker.extractor import normalize
from kukai.modeling.checker.spatial_model import SpatialModel, RoomFunction as RF


_RAW = {
    "building_id": "Коорд файл X ",
    "levels": [{"id": "L0", "name": "Этаж 1", "elevation_mm": 0.0, "index": 0}],
    "rooms": [
        {"id": "r1", "name": "Спальня 1", "level_id": "L0", "area_m2": 14.0,
         "height_mm": 2700.0, "boundary": [[0, 0], [3000, 0], [3000, 4000], [0, 4000]]},
        {"id": "r2", "name": "Санузел", "level_id": "L0", "area_m2": 4.0,
         "height_mm": 2700.0, "boundary": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]]},
        {"id": "r3", "name": "Кухня-гостиная", "level_id": "L0", "area_m2": 18.0,
         "height_mm": 2700.0, "boundary": [[0, 0], [4000, 0], [4000, 4500], [0, 4500]]},
    ],
    "doors": [{"id": "d1", "level_id": "L0", "location": [1000, 0], "width_mm": 900.0,
               "from_room_id": "r1", "to_room_id": "r3", "is_exterior": False}],
    "windows": [{"id": "w1", "level_id": "L0", "host_wall_id": None, "room_id": "r1",
                 "width_mm": 1500.0, "area_m2": 2.5}],
    "stairs": [],
    "walls": [],
}


def test_normalize_parses_as_spatial_model():
    model = SpatialModel.model_validate(normalize(_RAW))
    assert model.building_id == "Коорд файл X"   # trimmed
    assert len(model.rooms) == 3


def test_normalize_classifies_functions_from_ru_names():
    by = {r.id: r for r in SpatialModel.model_validate(normalize(_RAW)).rooms}
    assert by["r1"].function is RF.ЖИЛАЯ        # Спальня
    assert by["r2"].function is RF.САНУЗЕЛ      # Санузел
    assert by["r3"].function is RF.КУХНЯ        # Кухня-гостиная


def test_normalize_backfills_windows():
    by = {r.id: r for r in SpatialModel.model_validate(normalize(_RAW)).rooms}
    assert by["r1"].has_window is True and by["r1"].window_area_m2 == 2.5
    assert by["r2"].has_window is False


def test_normalize_handles_empty_extraction():
    # a structural shell (Музе: levels + walls, 0 rooms) must still normalize + parse.
    raw = {"building_id": "shell", "levels": [{"id": "L0", "name": "L", "elevation_mm": 0.0, "index": 0}],
           "rooms": [], "doors": [], "windows": [], "stairs": [],
           "walls": [{"id": "w", "level_id": "L0", "curve": [[0, 0], [5000, 0]],
                      "height_mm": 3000.0, "is_structural": True}]}
    model = SpatialModel.model_validate(normalize(raw))
    assert model.rooms == [] and len(model.walls) == 1
