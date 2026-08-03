"""make_good() must parse as a valid SpatialModel and be internally consistent (design §7)."""
from kukai.modeling.checker.fixtures.builders import make_good
from kukai.modeling.checker.spatial_model import SpatialModel, RoomFunction as RF


def test_make_good_returns_dict():
    assert isinstance(make_good(), dict)


def test_make_good_parses_as_spatial_model():
    model = SpatialModel.model_validate(make_good())
    assert model.building_id
    assert len(model.levels) >= 1
    assert len(model.rooms) >= 4   # прихожая + кухня-гостиная + спальня + санузел (+ public)


def test_make_good_has_the_apartment_rooms():
    model = SpatialModel.model_validate(make_good())
    funcs = {r.function for r in model.rooms}
    assert RF.ПРИХОЖАЯ in funcs
    assert RF.ЖИЛАЯ in funcs       # спальня
    assert RF.КУХНЯ in funcs
    assert RF.САНУЗЕЛ in funcs


def test_make_good_has_public_circulation_and_egress():
    model = SpatialModel.model_validate(make_good())
    funcs = {r.function for r in model.rooms}
    assert RF.КОРИДОР in funcs and RF.ЛЕСТНИЦА in funcs
    assert any(d.is_exterior for d in model.doors)   # a building entrance exists
    assert len(model.stairs) >= 1                    # at least one stair run


def test_make_good_is_deterministic_and_isolated():
    a, b = make_good(), make_good()
    assert a == b                  # same content
    a["rooms"][0]["name"] = "MUTATED"
    assert make_good()["rooms"][0]["name"] != "MUTATED"   # no shared mutable state


def test_make_good_area_matches_boundary_polygon():
    # Data-coherence invariant (review fix): declared area_m2 must equal the boundary polygon
    # area (within tolerance) so a generator can't satisfy area rules with a faked area_m2.
    def _poly_area_m2(b):
        n = len(b)
        s = sum(b[i][0] * b[(i + 1) % n][1] - b[(i + 1) % n][0] * b[i][1] for i in range(n))
        return abs(s) / 2.0 / 1_000_000.0
    model = SpatialModel.model_validate(make_good())
    for r in model.rooms:
        assert r.boundary, f"{r.id} has no boundary"
        poly = _poly_area_m2([(p[0], p[1]) for p in r.boundary])
        assert abs(poly - r.area_m2) <= 0.05, f"{r.id}: declared {r.area_m2} vs polygon {poly:.2f}"
