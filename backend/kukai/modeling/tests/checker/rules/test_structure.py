"""HAB050 vertical structural-continuity tests (design §6/§7)."""
import copy

from kukai.modeling.checker.fixtures.builders import make_good, bad_floating_column
from kukai.modeling.checker.graph import build_graph
from kukai.modeling.checker.rules import structure
from kukai.modeling.checker.spatial_model import SpatialModel, Severity
from kukai.modeling.checker.thresholds import THRESHOLDS


def _run(d: dict):
    model = SpatialModel.model_validate(d)
    return structure.check_hab050(model, build_graph(model), THRESHOLDS)


def test_hab050_silent_on_good():
    # GOOD is single-level: all structural walls are on the ground level → supported.
    assert _run(make_good()) == []


def test_hab050_fires_on_floating_wall():
    viols = _run(bad_floating_column())
    assert len(viols) == 1
    v = viols[0]
    assert v.rule_id == "HAB050"
    assert v.severity is Severity.WARNING
    assert "wall_float" in v.refs


def test_hab050_message_names_the_floating_element():
    v = _run(bad_floating_column())[0]
    low = v.msg.lower()
    assert "wall_float" in v.msg
    assert "support" in low or "mid-air" in low


def test_hab050_silent_when_wall_is_supported_from_below():
    # Put a structural wall directly under the floating one on L0 → supported → silent.
    # wall_float (canonical fixture) is curve [[12000, 0], [15000, 0]] on L1; mirror it on L0.
    raw = bad_floating_column()
    raw["walls"].append(
        {"id": "wall_support", "level_id": "L0",
         "curve": [[12000, 0], [15000, 0]],
         "height_mm": 2700.0, "is_structural": True}
    )
    assert _run(raw) == []


def test_hab050_ignores_non_structural_floating_wall():
    # The same mid-air wall, but non-structural → not load-bearing → never flagged.
    raw = bad_floating_column()
    for w in raw["walls"]:
        if w["id"] == "wall_float":
            w["is_structural"] = False
    assert _run(raw) == []


def test_hab050_supported_within_lateral_tolerance():
    # Lower wall offset laterally by 150 mm (< struct_support_offset_mm = 200) still supports it.
    # wall_float runs along y = 0; offset the lower wall to y = 150 (collinear direction, same x-span).
    raw = bad_floating_column()
    raw["walls"].append(
        {"id": "wall_support", "level_id": "L0",
         "curve": [[12000, 150], [15000, 150]],
         "height_mm": 2700.0, "is_structural": True}
    )
    assert _run(raw) == []


def test_hab050_not_supported_when_overlap_too_short():
    # Lower wall collinear but barely overlapping (200 mm < struct_min_support_overlap_mm = 300).
    # wall_float spans x in [12000, 15000] along y = 0; this lower wall shares only x in [14800, 15000].
    raw = bad_floating_column()
    raw["walls"].append(
        {"id": "wall_short", "level_id": "L0",
         "curve": [[14800, 0], [15000, 0]],   # only 200 mm of shared run
         "height_mm": 2700.0, "is_structural": True}
    )
    viols = _run(raw)
    assert len(viols) == 1
    assert viols[0].rule_id == "HAB050"
    assert "wall_float" in viols[0].refs


def test_hab050_ground_level_walls_never_flagged():
    # Even an isolated structural wall on the ground level is supported by the ground.
    raw = copy.deepcopy(make_good())
    raw["walls"].append(
        {"id": "wall_iso", "level_id": "L0",
         "curve": [[20000, 0], [20000, 4000]],
         "height_mm": 2700.0, "is_structural": True}
    )
    assert _run(raw) == []
