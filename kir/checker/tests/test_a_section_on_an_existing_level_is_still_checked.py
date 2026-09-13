"""A program that builds into an EXISTING document must not be invisible.

🔴 THE CASE THIS GUARDS IS THE ONLY ONE THAT SHIPS. A section added to a document
that already exists addresses its levels by `element_id` — the author got the id
from a facts sheet, exactly as intended. Until 13.09.2026 such a level entered
the model NOWHERE: `elevations` held only ids that `create_level` produced, so
every wall and room hanging on it was dropped in silence and the verdict came
back `HAB000: model has no rooms`. The refusal was honest; the coverage was zero.

Measured then, on ONE program with ONE difference:

    create_level          -> rooms 1 · walls 4 · levels 1 · rules 7 of 20
    {by: element_id}      -> rooms 0 · walls 0 · levels 0 · rules 0 of 20

This file pins the control itself: the two programs must be judged by the SAME
number of rules. It is not a test of the numbers 1/4/7 — those may legitimately
move — it is a test that the two paths do not DIFFER.
"""
import pytest

from kir.design_check import check_ops, spatial_model_from_ops

RING = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]
EXISTING_LEVEL_ID = 355


def _program(level_selector, *, create_the_level):
    ops = []
    if create_the_level:
        ops.append({"op": "create_level", "id": "L", "elev_mm": 0, "name": "Этаж 1"})
    for index, (start, end) in enumerate(zip(RING, RING[1:] + RING[:1])):
        ops.append({"op": "create_wall", "id": f"w{index}", "p0_mm": start, "p1_mm": end,
                    "height_mm": 3000, "level": level_selector})
    ops.append({"op": "create_room", "id": "r", "xy": [3000.0, 2000.0], "name": "Жилая",
                "level": level_selector, "function": "жилая", "upper_offset_mm": 2700})
    return {"ops": ops}


CREATED = _program({"by": "ref", "value": "L"}, create_the_level=True)
EXISTING = _program({"by": "element_id", "value": EXISTING_LEVEL_ID}, create_the_level=False)


@pytest.mark.parametrize("known_levels", [None, {EXISTING_LEVEL_ID: 0.0}])
def test_an_existing_level_is_judged_by_the_same_rules_as_a_created_one(known_levels):
    created = check_ops(CREATED)
    existing = check_ops(EXISTING, known_levels=known_levels)
    assert existing.rules_applied == created.rules_applied > 0
    assert existing.verdict == created.verdict


@pytest.mark.parametrize("known_levels", [None, {EXISTING_LEVEL_ID: 0.0}])
def test_the_population_is_the_same_on_both_paths(known_levels):
    created, _ = spatial_model_from_ops(CREATED, building_id="t")
    existing, _ = spatial_model_from_ops(EXISTING, building_id="t",
                                         known_levels=known_levels)
    assert (len(existing.rooms), len(existing.walls), len(existing.levels)) == \
           (len(created.rooms), len(created.walls), len(created.levels))


def test_an_unsupplied_elevation_stays_unknown_instead_of_becoming_zero():
    """Unknown is not grade. Fabricating 0.0 would let the band call any floor
    "ground", which is the failure the band itself was built to prevent."""
    model, _ = spatial_model_from_ops(EXISTING, building_id="t")
    level, = model.levels
    assert level.external is True
    assert level.elevation_mm is None and level.elevation_source is None


def test_a_supplied_elevation_is_carried_with_its_provenance():
    model, _ = spatial_model_from_ops(EXISTING, building_id="t",
                                      known_levels={EXISTING_LEVEL_ID: 3300.0})
    level, = model.levels
    assert level.external is True
    assert level.elevation_mm == 3300.0 and level.elevation_source == "facts"


def test_a_level_the_program_creates_is_not_marked_external():
    model, _ = spatial_model_from_ops(CREATED, building_id="t")
    level, = model.levels
    assert level.external is False and level.elevation_source == "program"
    assert level.elevation_mm == 0.0
