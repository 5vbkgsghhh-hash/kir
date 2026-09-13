"""Why the comparison side does not see curtain-wall cells — a
measurement, not a hypothesis.

Reassembly #6 (artifacts `sob62_fas_r23_v11`): `set_curtain_panel` expected
54, actual 0, even though RECONCILED passed and all 1236 created elements
are stamped — meaning the cells are standing live.

The working hypothesis was "the law of the occupant": the cell is occupied
by a wall, `GetPanelIds` does not show the occupant, and it goes into
`create_wall`. In that case there would be about fifty extra walls. The
report shows nine, and ten missing — and that does not add up.

These tests are refutational. They read ONLY saved artifacts (no Revit, no
network) and fix the actual picture:

* 44 of 54 cells change type IN PLACE — no new element is born, its id
  does not land in `created_ids`, and the re-extraction universe is exactly
  `created_ids`. This effect is invisible by construction, no matter how
  much the lift is fixed;
* 10 of 54 (type `_Пустая_`) DO give birth to an element, land in the
  re-extraction — and still yield not a single `set_curtain_panel` sheet.
  This is a genuine hole in the lift, and it must not be hidden;
* walls whose type matches the type being assigned to the cell number
  exactly ONE — "the law of the occupant" explains 1 case out of 54, not 44.

    venv/bin/pytest kir/decompile/tests/test_curtain_blindness.py -q
"""
from __future__ import annotations

import collections
import json
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[4]
V11 = BACKEND / "backend" / "data" / "decompile" / "sob62_fas_r23_v11"
DEBUG = V11 / "idempotence_debug.json"

pytestmark = pytest.mark.skipif(
    not DEBUG.exists(), reason="нет артефактов пересборки №6 (v11)")


@pytest.fixture(scope="module")
def debug() -> dict:
    return json.loads(DEBUG.read_text(encoding="utf-8"))


def _leaves(debug: dict, side: str) -> list[dict]:
    return [x["leaf"] for x in debug[side]]


def _scp(debug: dict) -> list[dict]:
    return [l for l in _leaves(debug, "expected")
            if l.get("op_name") == "set_curtain_panel"]


# ── pre-state: the comparison is blind ────────────────────────────────────

def test_the_comparison_side_produces_no_curtain_cell_leaves_at_all(debug):
    """Pre-state of the wave, fixed verbatim: 54 was expected, 0 came out."""
    expected = collections.Counter(
        l.get("op_name") for l in _leaves(debug, "expected"))
    relifted = collections.Counter(
        l.get("op_name") for l in _leaves(debug, "relifted"))
    assert expected["set_curtain_panel"] == 54
    assert relifted["set_curtain_panel"] == 0


def test_the_occupant_wall_hypothesis_does_not_survive_the_numbers(debug):
    """If the cells had gone into walls, there would be about fifty extra
    walls.

    There are nine, and none of them are about curtain wall: walls whose
    type matches the type being assigned to the cell number exactly one.
    """
    rows = debug["reextracted_rows"]
    walls = [r for r in rows if r["category"] == "OST_Walls"]
    panel_types = {l["params"]["panel_type"]["value"] for l in _scp(debug)}
    occupants = [r for r in walls if r.get("type_name") in panel_types]
    assert len(occupants) <= 1, "закон занявшего объяснил бы куда больше"

    relifted_walls = sum(1 for l in _leaves(debug, "relifted")
                         if l.get("op_name") == "create_wall")
    expected_walls = sum(1 for l in _leaves(debug, "expected")
                         if l.get("op_name") == "create_wall")
    # Walls did NOT increase — there is even one less. Forty-four cells did
    # not turn into walls in any form.
    assert relifted_walls <= expected_walls


# ── the real cause, split into two ────────────────────────────────────────

def test_forty_four_cells_change_type_in_place_and_create_nothing(debug):
    """Main cause: `set_curtain_panel` is a family-MODIFY op.

    It changes the type of an existing cell; Revit preserves the id; the id
    does not land in `created_ids`; re-extraction asks precisely about
    `created_ids`. The effect is invisible BY CONSTRUCTION of the comparison
    universe, not by a weakness of the lift.
    """
    from kir import spec
    assert spec.OPS["set_curtain_panel"].family == "modify"

    by_type = collections.Counter(
        l["params"]["panel_type"]["value"] for l in _scp(debug))
    in_place = by_type["ПН_ВТ_Стеклопакет_ теплый_30 мм"]
    creating = by_type["_Пустая_ Не учитывать_200мм"]
    assert in_place == 44 and creating == 10

    panels = [r for r in debug["reextracted_rows"]
              if r["category"] == "OST_CurtainWallPanels"]
    # In the re-extraction there are exactly the ten that gave birth to an
    # element, and none of the forty-four that changed type in place.
    assert len(panels) == creating
    assert {r.get("type_name") for r in panels} == {"_Пустая_ Не учитывать_200мм"}


def test_the_ten_cells_that_did_create_elements_are_still_dropped(debug):
    """The second cause, and it IS a real hole in the lift, not a property
    of the universe.

    SUSPECT (cannot fix blindly, waiting for the artifact of reassembly
    #7): `_lift_curtain_panel` reaches a sheet only when
    `panel.address_state is CellAddressState.OK`, and the cell's address is
    read via `GetRefGridLines`, which lives ONLY on Panel. In the copy the
    cell is occupied by a wall (`type_name` of these ten sheets is "Стена"),
    so it may have no address at all. There is nothing to check this
    post-mortem today with: the copy's curtain-wall index did not make it
    into the artifacts. Starting this wave it is dumped into
    `idempotence_debug.json` -> `curtain_index`, and after the next live
    reassembly the suspect will become provable or fall away.

    The ten cells ARE present in the re-extraction as `OST_CurtainWallPanels`,
    but no sheets came out of them: 1236 rows gave 1226 sheets, and the
    missing ten are exactly them. This cannot be hidden under a carve-out:
    15 live flip-guard misses were already hidden that way under adjusted%.
    """
    rows = debug["reextracted_rows"]
    panels = [r for r in rows if r["category"] == "OST_CurtainWallPanels"]
    assert len(rows) - len(_leaves(debug, "relifted")) == len(panels) == 10


def test_the_missing_reason_is_uniform_and_says_nothing_useful_today(debug):
    """Today all 54 fall into one nameless bucket "sheet not found" — from
    it, it is impossible to tell what is invisible by construction from a
    real hole."""
    report = json.loads(
        (pathlib.Path(__file__).resolve().parents[4] / "backend" / "data"
         / "decompile" / "sob62_fas_r23_v11" / "idempotence.json")
        .read_text(encoding="utf-8")) if (V11 / "idempotence.json").exists() else None
    if report is None:
        pytest.skip("нет idempotence.json")
    disc = report.get("discrepancies") or []
    scp = [d for d in disc if d.get("op_name") == "set_curtain_panel"]
    assert len(scp) == 54
    assert {d["reason"] for d in scp} == {
        "re-lifted leaf not found for this translated original"}
    assert all(d["expected_discrepancy_class"] is False for d in scp)


# ── universe rule: 44 carried out, 10 remain visible ──────────────────────

def test_the_structural_rule_carves_out_exactly_the_unobservable_44(debug):
    """The count is taken from STRUCTURE, not from a list of names: a
    `modify` family op whose assigned type did not appear on any
    re-extracted element left no effect in created-ids and cannot be checked."""
    from kir import idempotence as K

    expected = _leaves(debug, "expected")
    outside = K.modify_outside_universe(expected, debug["reextracted_rows"])
    assert len(outside) == 44
    assert {expected[i]["op_name"] for i in outside} == {"set_curtain_panel"}


def test_missing_shrinks_to_ten_and_those_ten_stay_visible(debug):
    """Exactly the boundary the rule was written for: 44 leave the
    denominator, 10 remain as a DEFICIT. A carve-out by op name would have
    carried away all 54 — the way `place_family` carried away 15 live
    flip-guard misses."""
    from kir import idempotence as K

    expected = _leaves(debug, "expected")
    relifted = _leaves(debug, "relifted")
    outside = K.modify_outside_universe(expected, debug["reextracted_rows"])
    _m, _e, _a, per_kind, disc = K._compare(expected, relifted, outside)

    row = next(k.to_dict() for k in per_kind
               if k.op_name == "set_curtain_panel")
    assert row["outside_universe"] == 44
    assert row["expected"] == 10 and row["missing"] == 10
    assert sum(1 for d in disc if d["op_name"] == "set_curtain_panel") == 10


def test_nothing_was_added_to_the_adjusted_carve_out(debug):
    """Nothing is entered into adjusted%: taking something out of the
    universe is not a concession to quality, but an honest boundary of
    checkability."""
    from kir import idempotence as K

    assert "set_curtain_panel" not in K.EXPECTED_DISCREPANCY_OPS
    expected = _leaves(debug, "expected")
    outside = K.modify_outside_universe(expected, debug["reextracted_rows"])
    _m, _e, _a, per_kind, _d = K._compare(
        expected, _leaves(debug, "relifted"), outside)
    row = next(k.to_dict() for k in per_kind if k.op_name == "set_curtain_panel")
    assert row["excluded_expected"] == 0
    assert row["expected_discrepancy_class"] is False


def test_a_modify_effect_that_did_create_an_element_is_never_carved_out(debug):
    """The flip side of the rule: as soon as an effect gives birth to an
    element, it must be checked. Otherwise the counter becomes a garbage
    bin for all of modify."""
    from kir import idempotence as K

    expected = _leaves(debug, "expected")
    rows = debug["reextracted_rows"]
    # Add an element carrying the type that those very 44 cells assign.
    faked = rows + [{"category": "OST_CurtainWallPanels",
                     "type_name": "ПН_ВТ_Стеклопакет_ теплый_30 мм"}]
    assert K.modify_outside_universe(expected, faked) == []


def test_the_report_publishes_the_carve_out_as_a_number(debug):
    """The carve-out must be visible as a number and a list of ops, not
    silently shrink the denominator."""
    from kir import idempotence as K

    rep = K.IdempotenceReport(
        doc_stamp="t", delta_mm=(0, 0, 0), multiset_match=False,
        expected_hash="a", actual_hash="b", total_expected=10,
        total_matched=0, raw_exact_pct=0.0, adjusted_exact_pct=0.0,
        per_kind=(), discrepancies=(), datums_skipped=0, created_ids=(),
        cleanup_ok=True, cleanup_detail="", non_datum_total=100,
        comparable_coverage_pct=10.0,
        modify_outside_universe=44,
        modify_outside_universe_by_op=({"op_name": "set_curtain_panel",
                                        "count": 44},))
    d = rep.to_dict()
    assert d["modify_outside_universe"] == 44
    assert d["modify_outside_universe_by_op"] == [
        {"op_name": "set_curtain_panel", "count": 44}]
    assert "modify-эффектов вне вселенной created-ids" in \
        d["comparable_coverage_summary"]
    assert "set_curtain_panel×44" in d["comparable_coverage_summary"]
