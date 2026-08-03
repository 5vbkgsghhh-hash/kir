"""The value-loop proof: the parametric generator produces multi-story residential ЖК that
PASS the correctness checker (0 BLOCKING) — habitable by construction, validated in memory."""
import pytest

from kukai.modeling.generator.building import building
from kukai.modeling.checker.engine import run
from kukai.modeling.checker.spatial_model import SpatialModel


@pytest.mark.parametrize("floors,apts", [(1, 1), (1, 4), (3, 2), (5, 4), (9, 6)])
def test_generated_building_passes_checker(floors, apts):
    model = SpatialModel.model_validate(building(floors, apts))
    rep = run(model)
    assert rep.passed, [(v.rule_id, v.refs, v.msg) for v in rep.blocking]


@pytest.mark.parametrize("floors,apts", [(1, 1), (5, 4), (9, 6)])
def test_generated_building_is_fully_clean(floors, apts):
    # A skeleton-generated building should have ZERO violations of any severity (incl. WARNING/INFO).
    rep = run(SpatialModel.model_validate(building(floors, apts)))
    assert rep.blocking == []
    assert rep.warnings == [], [v.rule_id for v in rep.warnings]
    assert rep.info == [], [v.rule_id for v in rep.info]


def test_generated_building_shape():
    b = building(5, 4)
    assert len(b["levels"]) == 5
    apt_rooms = sum(1 for r in b["rooms"] if r["apartment_id"])
    assert apt_rooms == 5 * 4 * 4                  # 5 floors × 4 apts × 4 rooms each
    assert len(b["stairs"]) == 4                   # 5 floors → 4 inter-floor stair runs
    assert sum(1 for d in b["doors"] if d["is_exterior"]) == 1  # exactly one building entrance


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        building(0, 3)
    with pytest.raises(ValueError):
        building(3, 0)
