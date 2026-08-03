"""The generate→check→fix loop closes: a deliberately broken building converges back to
passing under the deterministic fixers (the scaffold an LLM adaptation layer plugs into)."""
from kukai.modeling.generator.building import building
from kukai.modeling.generator.fix_loop import run_loop
from kukai.modeling.checker.engine import run
from kukai.modeling.checker.spatial_model import SpatialModel


def _break(b: dict) -> dict:
    # remove a bedroom's window (HAB030 BLOCKING) and lower another's ceiling (HAB022 WARNING)
    for r in b["rooms"]:
        if r["id"] == "apt_1_0_bed":
            r["has_window"] = False
            r["window_area_m2"] = 0.0
        if r["id"] == "apt_2_1_bed":
            r["height_mm"] = 2100.0
    b["windows"] = [w for w in b["windows"] if w["room_id"] != "apt_1_0_bed"]
    return b


def test_broken_building_is_actually_broken():
    rep = run(SpatialModel.model_validate(_break(building(3, 2))))
    assert not rep.passed
    assert any(v.rule_id == "HAB030" for v in rep.blocking)


def test_fix_loop_converges_to_passing():
    res = run_loop(_break(building(3, 2)), max_iters=6)
    assert res.passed, res.history
    # converged in a couple of iterations, and the repaired model really passes
    assert res.iterations <= 6
    assert run(SpatialModel.model_validate(res.model)).passed


def test_fix_loop_noop_on_already_clean_building():
    res = run_loop(building(4, 3), max_iters=4)
    assert res.passed
    assert res.iterations == 0          # clean on first check → no repair needed


def test_fix_loop_gives_up_honestly_when_unfixable():
    # break connectivity (no registered fixer for HAB001) → loop must stop, not spin
    b = building(2, 2)
    b["doors"] = [d for d in b["doors"] if d["to_room_id"] != "apt_0_0_wc"
                  and d["from_room_id"] != "apt_0_0_wc"]
    res = run_loop(b, max_iters=5)
    assert res.passed is False
    assert res.iterations < 5            # gave up as soon as nothing was repairable
