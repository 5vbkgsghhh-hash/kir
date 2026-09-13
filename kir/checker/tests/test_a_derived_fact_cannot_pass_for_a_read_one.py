"""A DERIVED VALUE HAS NO RIGHT TO A STRICT VERDICT — and this is observable.

The same class closed on 20.08.2026 for room height (`height_provenance`,
`test_hab022_asks_where_the_height_came_from`), and it is closed here for two more
values that became derivable on the real MNVNK building on 22.08:

    STAIR TOP LEVEL         `STAIRS_TOP_LEVEL_PARAM` is empty for 24 out of 24, the top
                             is derived as base + N × riser height;
    ROOM FUNCTION            `ROOM_NAME` = "Room" for 1102 out of 1102, the kind
                             is derived from context (a toilet → bathroom).

WHAT EXACTLY IS CHECKED HERE, AND WHY IT IS NOT VISIBLE WITHOUT A PAIR. Each test holds
TWO models differing ONLY by the source name, and demands DIFFERENT strictness. Were there
no difference, the provenance fields would exist while the distinction would not, and we would be reading a
strict verdict where nothing was actually read. This is exactly how this defect lived until 20.08.

Run: KUKAI_CHECKER_V2=1 pytest \
    kir/checker/tests/test_a_derived_fact_cannot_pass_for_a_read_one.py -q
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir.checker import function_provenance, stair_provenance  # noqa: E402
from kir.checker.engine import PRECONDITIONS, RULE_SPECS_V2  # noqa: E402
from kir.checker.engine import run as run_engine  # noqa: E402
from kir.checker.rules.dimensions import check_hab020  # noqa: E402
from kir.checker.rules.light import check_hab030  # noqa: E402
from kir.checker.rules.vertical import check_hab011  # noqa: E402
from kir.checker.spatial_model import (  # noqa: E402
    Level,
    Room,
    RoomFunction,
    Severity,
    SpatialModel,
    Stair,
)
from kir.checker.thresholds import THRESHOLDS  # noqa: E402


# ------------------------------------------------------------------ kind vocabularies

def test_the_two_new_vocabularies_read_an_unknown_name_as_unknown():
    """An unfamiliar source name is `unknown`, NOT "read from the author".

    The same law as `height_provenance`: a value has several producers,
    they live in different files, and a new source will be introduced sooner than anyone
    remembers the vocabulary. Silently promoting a foreign name to an authored one is
    exactly the error that must never be allowed here, not once.
    """
    for module in (stair_provenance, function_provenance):
        assert module.AUTHORED & module.DERIVED == frozenset(), module.__name__
    assert stair_provenance.top_level_authority("новый_съём") == "unknown"
    assert function_provenance.function_authority("новый_съём") == "unknown"
    assert not stair_provenance.is_authored("riser_run")
    assert not function_provenance.is_authored("fixtures")
    assert stair_provenance.is_authored("stairs_top_level_param")
    assert function_provenance.is_authored("room_name")


def test_a_model_built_without_the_field_is_still_authored():
    """The fields' default is `declared`, and this is NOT a concession.

    A `SpatialModel` assembled by anyone WITHOUT these fields carries values that
    its author NAMED in the input. Downgrading them to "unconfirmed" would strip
    strictness from all existing inputs at once, without measuring anything. The duty
    to name itself lies with whoever DERIVES, and it does so explicitly.
    """
    room = Room(id="r", name="Спальня", level_id="L0",
                function=RoomFunction.ЖИЛАЯ, area_m2=4.0, height_mm=2700.0)
    stair = Stair(id="s", base_level_id="L0", top_level_id="L1",
                  base_z=0.0, top_z=3000.0, run_width_mm=1200.0)
    assert room.function_source == "declared"
    assert stair.top_level_source == "declared"
    assert function_provenance.is_authored(room.function_source)
    assert stair_provenance.is_authored(stair.top_level_source)


# ------------------------------------------------------------------ HAB011

def _stair_model(top_source: str) -> SpatialModel:
    """The same STEEP flight; the only difference is the top's source name."""
    return SpatialModel(
        building_id="b", levels=[Level(id="L0", name="1", elevation_mm=0.0, index=0)],
        stairs=[Stair(id="s", base_level_id="L0", top_level_id="L1",
                      base_z=0.0, top_z=3400.0, run_width_mm=1200.0,
                      riser_count=17, tread_depth_mm=300.0,
                      top_level_source=top_source)])


def test_hab011_blocks_on_a_read_top_and_only_warns_on_a_derived_one():
    """A 200 mm rise at a 180 threshold — the same defect, different authority.

    On a DERIVED top, the formula `(top_z - base_z) / riser_count` returns exactly
    the riser height the top was computed from: every number is real, yet
    the comparison stops being a comparison of two independent facts.
    """
    strict = check_hab011(_stair_model("stairs_top_level_param"), None, THRESHOLDS)
    soft = check_hab011(_stair_model("riser_run"), None, THRESHOLDS)
    assert [v.severity for v in strict] == [Severity.BLOCKING]
    assert [v.severity for v in soft] == [Severity.WARNING]
    assert "rise 200 mm" in strict[0].msg and "rise 200 mm" in soft[0].msg
    # a soft finding MUST name the reason for its softness, otherwise it is indistinguishable from
    # a rule that simply has that severity by default
    assert "ВЫВЕДЕН нами" in soft[0].msg


def test_hab011_never_softens_a_defect_that_does_not_depend_on_the_top():
    """Width and going are not computed from the top — their strictness does not move.

    The boundary of the fix: only what rests on the derived value is softened.
    Softening the neighbours too would mean, under the pretext of provenance, stripping
    strictness from facts that were read exactly as they were.
    """
    model = SpatialModel(
        building_id="b", levels=[Level(id="L0", name="1", elevation_mm=0.0, index=0)],
        stairs=[Stair(id="s", base_level_id="L0", top_level_id="L1",
                      base_z=0.0, top_z=2550.0, run_width_mm=700.0,
                      riser_count=17, tread_depth_mm=200.0,
                      top_level_source="riser_run")])
    found = check_hab011(model, None, THRESHOLDS)
    blocking = [v for v in found if v.severity is Severity.BLOCKING]
    assert len(blocking) == 1
    assert "run width 700 mm" in blocking[0].msg
    assert "going 200 mm" in blocking[0].msg
    assert "rise" not in blocking[0].msg


# ------------------------------------------------------------------ HAB020 / HAB030

def _room_model(function_source: str, *, function=RoomFunction.ЖИЛАЯ,
                area_m2=4.0) -> SpatialModel:
    return SpatialModel(
        building_id="b", levels=[Level(id="L0", name="1", elevation_mm=0.0, index=0)],
        rooms=[Room(id="r", name="Помещение", level_id="L0", function=function,
                    area_m2=area_m2, height_mm=2700.0,
                    boundary=[(0.0, 0.0), (2000.0, 0.0), (2000.0, 2000.0),
                              (0.0, 2000.0)],
                    function_source=function_source)])


@pytest.mark.parametrize("rule,call", [
    ("HAB020", lambda m: check_hab020(m, None, THRESHOLDS)),
    ("HAB030", lambda m: check_hab030(m, None, THRESHOLDS)),
])
def test_a_rule_that_judges_by_function_asks_where_the_function_came_from(rule, call):
    """«A habitable room too small» and «a habitable room with no window» both accuse TWICE if the kind is derived.

    The second accusation — "this room is habitable" — on derivation belongs to our
    own dictionary: a bed named it habitable, not the author. The threshold itself is NOT relaxed:
    the finding is still printed, only its authority changes.
    """
    strict = call(_room_model("room_name"))
    soft = call(_room_model("fixtures"))
    assert [v.severity for v in strict] == [Severity.BLOCKING], rule
    assert [v.severity for v in soft] == [Severity.WARNING], rule
    assert "ВЫВЕДЕНА нами из обстановки" in soft[0].msg


def test_a_function_with_a_soft_threshold_keeps_its_severity_and_still_says_whence():
    """A bathroom is WARNING already — its authority does not move, but the PROVENANCE is named.

    Two halves, both load-bearing. First: the fix must move exactly one axis,
    not the set of findings along with it. Second: 258 out of 281 derived cases on MNVNK are
    bathrooms, meaning that without a line about derivation, the overwhelming majority of findings about a
    derived kind would sound exactly like findings about a read one.
    """
    for source in ("room_name", "fixtures"):
        found = check_hab020(_room_model(source, function=RoomFunction.САНУЗЕЛ,
                                         area_m2=1.0), None, THRESHOLDS)
        assert [v.severity for v in found] == [Severity.WARNING], source
        said = "ВЫВЕДЕНА нами из обстановки" in found[0].msg
        assert said is (source == "fixtures"), source


# ------------------------------------------------------------------ preconditions

def test_the_rules_own_preconditions_hold_without_any_profile():
    """A rule's own precondition holds even with `profile=None` — otherwise it does not exist at all.

    THE MEASUREMENT THIS TEST WAS WRITTEN FOR (22.08.2026, MNVNK): `preconditions`
    used to live only in `StageProfile`, and the full as-built set checked NONE of them.
    The production path printed BLOCKING 0, while as-built on the same model printed 24,
    23 of which were "a level hangs with no connection to the ground" on a graph that
    has no vertical edges by construction.
    """
    declared = {spec.rule_id: spec.preconditions for spec in RULE_SPECS_V2
                if spec.preconditions}
    assert declared, "хотя бы одно правило обязано назвать своё предусловие"
    for rule_id, names in declared.items():
        for name in names:
            assert name in PRECONDITIONS, (rule_id, name)

    # A building with a stair but WITHOUT a stairwell room: there are no vertical edges
    # by construction, and "the floor hangs" here is a property of the annotation, not the building.
    model = SpatialModel(
        building_id="b",
        levels=[Level(id="L0", name="1", elevation_mm=0.0, index=0),
                Level(id="L1", name="2", elevation_mm=3000.0, index=1)],
        rooms=[Room(id="a", name="Спальня", level_id="L0",
                    function=RoomFunction.ЖИЛАЯ, area_m2=20.0, height_mm=2700.0,
                    boundary=[(0.0, 0.0), (4000.0, 0.0), (4000.0, 5000.0),
                              (0.0, 5000.0)]),
                Room(id="b", name="Спальня", level_id="L1",
                     function=RoomFunction.ЖИЛАЯ, area_m2=20.0, height_mm=2700.0,
                     boundary=[(0.0, 0.0), (4000.0, 0.0), (4000.0, 5000.0),
                               (0.0, 5000.0)])],
        stairs=[Stair(id="s", base_level_id="L0", top_level_id="L1",
                      base_z=0.0, top_z=3000.0, run_width_mm=1200.0)])
    report = run_engine(model, THRESHOLDS)          # NO PROFILE
    rows = {o.rule_id: o for o in report.coverage.outcomes}
    for rule_id in ("HAB001", "HAB010"):
        assert rows[rule_id].status.value == "not_evaluated", rule_id
        assert "stair_landings_marked" in rows[rule_id].reason, rule_id
    # The subject of the test is the precondition, not a clean rig: other rules on this
    # stub (with no doors and windows) accuse RIGHTFULLY, and there is no basis to silence them here.
    assert not [v for v in report.blocking if v.rule_id in ("HAB001", "HAB010")]


def test_a_level_without_rooms_does_not_demand_a_landing():
    """The precondition's boundary: only OCCUPIED levels are asked about.

    A flight leading to a technical level with not a single room has no duty to have
    a landing there: such a level does not participate in connectivity (`occupied_levels`), and
    demanding annotation on it would mean silencing rules on a building where there was
    something to judge. Bought with the reference fixtures `bad_floating_column` / `bad_discontinuous_core`.
    """
    from kir.checker.engine import _V2Context, _landings_marked

    model = SpatialModel(
        building_id="b",
        levels=[Level(id="L0", name="1", elevation_mm=0.0, index=0),
                Level(id="L1", name="2", elevation_mm=3000.0, index=1)],
        rooms=[Room(id="k", name="Лестничная клетка", level_id="L0",
                    function=RoomFunction.ЛЕСТНИЦА, area_m2=8.0, height_mm=2700.0)],
        stairs=[Stair(id="s", base_level_id="L0", top_level_id="L1",
                      base_z=0.0, top_z=3000.0, run_width_mm=1200.0)])
    ctx = _V2Context(model=model, drep=None, graph=None, apartments=[])
    assert _landings_marked(ctx) is True
