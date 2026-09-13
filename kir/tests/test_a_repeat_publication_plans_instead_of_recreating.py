"""A repeat publication plans actions; a duplicate is not expressible.

Measured on a live Revit 2023 on 13.09.2026, two receipts of the SAME day:

* `/root/kir-live-20260909/live-20260913-slice-receipt.json` — the program
  carries `create_wall_type` and `create_level`; `publish_2`/`publish_3` answer
  `stale_or_failed` and `atomic` rolls the whole publication back. Six counters
  stand still (walls 4/4/4, floors 1/1/1, instances 3915/3915/3915).
* `/root/kir-live-20260909/live-20260913-slice-opening-receipt.json` — the same
  shape without those two ops. Nothing refuses, and each repeat adds +4 walls,
  +1 floor, +25 instances: walls 4→8→12, floors 1→2→3, instances 3913→3938→3968.

So a repeat publication had no middle: refuse everything or duplicate
everything. `kir.project_republish` is the middle, and the law of this file is
that the duplicate is UNSPEAKABLE — `action="create"` over a known identity is
refused when the plan is built, not caught afterwards.
"""
import pytest

from kir.project_republish import (ACTIONS, REASONS, RepublishError, plan_republish)

LEVEL, WALL_TYPE, FLOOR = "1" * 64, "3" * 64, "8" * 64
WALLS = [str(index) * 64 for index in (4, 5, 6, 7)]


def section(*, height_mm=3000, type_width_mm=230, walls=4, opening=(2000.0, 4000.0),
            shift_mm=0.0):
    corners = [[shift_mm, 0.0], [shift_mm + 6000.0, 0.0],
               [shift_mm + 6000.0, 6000.0], [shift_mm, 6000.0]]
    low, high = opening
    ops = [
        {"op": "create_level", "id": LEVEL, "elev_mm": 0, "name": "Уровень 1"},
        {"op": "create_wall_type", "id": WALL_TYPE, "host_kind": "wall",
         "new_name": "секция", "source_type": {"by": "name", "value": "Типовой"},
         "layers": [{"width_mm": type_width_mm, "function": "Structure",
                       "material": "Бетон"}]},
    ]
    for index in range(walls):
        ops.append({"op": "create_wall", "id": WALLS[index], "p0_mm": corners[index],
                    "p1_mm": corners[(index + 1) % 4], "height_mm": height_mm,
                    "level": {"by": "ref", "value": LEVEL},
                    "type": {"by": "ref", "value": WALL_TYPE}})
    ops.append({"op": "create_floor_by_contour", "id": FLOOR, "level": {"by": "ref", "value": LEVEL},
                "contour": {"shape": "poly", "points_mm": corners,
                            "holes": [{"shape": "poly", "points_mm": [
                                [low, low], [high, low], [high, high], [low, high]]}]}})
    return {"ir_version": "1.0", "intent": "секция", "lineage": "sec", "ops": ops}


def published(program):
    """The shape `assess_create_identities` produces (`create_publication.py:363`)."""
    return {"program": program, "identity": {
        "schema": "kir-create-identity-assessment/1", "receipt_digest": "d" * 64,
        "outputs": [{"output_id": op["id"], "source_op": op["op"], "state": "created_here",
                     "element_identity": {"unique_id": f"uid-{index}", "element_id": 270000 + index}}
                    for index, op in enumerate(program["ops"])]}}


def plan(new, old=None):
    old = old if old is not None else section()
    return plan_republish(None, new, published(old))


def test_a_repeat_with_no_change_creates_nothing():
    result = plan(section())
    assert result.counts() == {"keep": 7, "update": 0, "replace": 0, "delete": 0, "create": 0}
    assert all(not row["changes"] for row in result.rows)


def test_a_changed_parameter_is_an_in_place_update_with_the_field_named():
    result = plan(section(height_mm=3300))
    assert result.counts()["create"] == 0
    updates = [row for row in result.rows if row["action"] == "update"]
    assert len(updates) == 4
    assert all(row["changes"]["height_mm"] == [3000, 3300] for row in updates)
    assert all(row["reason"] == "parameter_changed" for row in updates)
    assert all(row["uid_before"] for row in updates)


def test_a_type_whose_composition_changed_is_an_honest_replace_not_a_repeat():
    """Live this was `stale_or_failed` and a rollback of everything (ОТК-9)."""
    result = plan(section(type_width_mm=300))
    assert result.counts()["create"] == 0
    replaced = [row for row in result.rows if row["action"] == "replace"]
    assert [row["source_op"] for row in replaced] == ["create_wall_type"]
    assert replaced[0]["reason"] == "replace_no_update_op"
    assert replaced[0]["uid_before"], "замена без прежней личности прячет смену UID"


def test_a_changed_sketch_is_named_not_passed_off_as_an_update():
    result = plan(section(opening=(1500.0, 4500.0)))
    replaced = [row for row in result.rows if row["action"] == "replace"]
    assert [row["reason"] for row in replaced] == ["replace_sketch_unsupported"]
    assert result.counts()["create"] == 0


def test_a_rigid_shift_is_a_move_but_a_stretched_wall_is_not():
    """`move_elements` carries ONE delta; a wall that changed length is not a move."""
    moved = plan(section(shift_mm=1000.0))
    assert {row["reason"] for row in moved.rows if row["action"] == "update"} == {"geometry_moved"}

    stretched = section()
    stretched["ops"][2] = {**stretched["ops"][2], "p1_mm": [9000.0, 0.0]}
    result = plan(stretched)
    rows = [row for row in result.rows if row["output_id"] == WALLS[0]]
    assert rows[0]["action"] == "replace" and rows[0]["reason"] == "replace_no_update_op"


def test_a_removed_output_is_a_delete_by_uid_and_a_new_one_has_no_identity():
    fewer = plan(section(walls=3))
    assert fewer.counts()["delete"] == 1 and fewer.counts()["create"] == 0
    assert all(row["uid_before"] for row in fewer.rows if row["action"] == "delete")

    extra = section()
    extra["ops"].append({"op": "create_wall", "id": "9" * 64, "p0_mm": [0.0, 0.0],
                         "p1_mm": [0.0, 6000.0], "height_mm": 3000,
                         "level": {"by": "ref", "value": LEVEL},
                         "type": {"by": "ref", "value": WALL_TYPE}})
    more = plan(extra)
    created = [row for row in more.rows if row["action"] == "create"]
    assert len(created) == 1 and created[0]["uid_before"] is None


def test_the_first_publication_is_all_create_and_says_which_ledger_it_read():
    result = plan_republish(None, section(), None)
    assert result.counts()["create"] == 7 and result.ledger_source == "none"
    assert all(row["uid_before"] is None for row in result.rows)


def test_a_duplicate_is_unspeakable_across_every_edit():
    """THE LAW. Not one create stands over a known element, in any of six edits."""
    base = section()
    for name, edited in (("нет правок", section()),
                         ("параметр", section(height_mm=3300)),
                         ("тип", section(type_width_mm=300)),
                         ("эскиз", section(opening=(1500.0, 4500.0))),
                         ("сдвиг", section(shift_mm=1000.0)),
                         ("меньше стен", section(walls=3))):
        result = plan(edited, base)
        assert result.creates_over_known_identity() == (), name
        assert sum(result.counts().values()) == len(result.rows), name


def test_the_plan_is_deterministic_and_grants_nothing():
    first, second = plan(section(height_mm=3300)), plan(section(height_mm=3300))
    assert first.digest == second.digest
    claims = first.to_dict()["claims"]
    assert claims["dispatch_permission"] == "none"
    assert claims["native_execution"] == "not_run"


def test_control_a_changed_op_kind_is_not_a_repeat_publication():
    other = section()
    other["ops"][2] = {**other["ops"][2], "op": "create_floor"}
    with pytest.raises(RepublishError) as caught:
        plan(other)
    assert caught.value.code == "output_op_kind_changed"


def test_control_an_identity_without_the_values_it_was_published_with_is_refused():
    """A plan cannot NAME a change it cannot see: it refuses instead of guessing."""
    base = section()
    ledger = published(base)["identity"]
    with pytest.raises(RepublishError) as caught:
        plan_republish(None, section(height_mm=3300), ledger)
    assert caught.value.code == "previous_payload_unavailable"


def test_the_closed_lists_stay_closed():
    assert ACTIONS == ("keep", "update", "replace", "delete", "create")
    assert set(REASONS) == {
        "unchanged", "parameter_changed", "geometry_moved", "type_changed",
        "replace_no_update_op", "replace_sketch_unsupported",
        "removed_from_program", "new_in_program", "no_previous_publication"}


# ── the store branch: `previous` may be an archive digest ──────────────────
#
# 🔴 THE FAKE STORE THAT STOOD HERE WAS REMOVED 13.09.2026, and with it a test
# that asserted a REFUSAL which no longer exists. Section N measured on a real
# SQLite that no product writer ever puts an `identity_assessment` blob into a
# stored receipt row — those rows are closed to five fields by
# `create_publication.validate_create_receipt_claims`. So the old reader refused
# on every real store and passed only here, against a mock that answered
# whatever this file wanted. `previous_from_store` now falls through to
# `kir.republish_archive.previous_from_stored_publication`, which DERIVES the
# identities from what the store does hold, and the route is measured on a real
# store in `test_a_republication_receipt_closes_the_loop.py` and in N's own pin.
#
# What stays here is only what needs no store at all: the argument checks.


def test_a_store_without_the_reader_is_refused_before_anything_is_read():
    with pytest.raises(RepublishError) as caught:
        plan_republish(object(), section(), "a" * 64)
    assert caught.value.code == "previous_publication_unreadable"


def test_a_digest_that_is_not_a_digest_is_refused_before_the_store_is_touched():
    class _Explodes:
        def get_create_publication(self, digest):  # pragma: no cover — must not run
            raise AssertionError("store was touched despite a malformed digest")

    with pytest.raises(RepublishError) as caught:
        plan_republish(_Explodes(), section(), "короткий")
    assert caught.value.code == "previous_publication_unreadable"


# ── the six review points of section N, accepted by the lead 13.09.2026 ────
def _identity(program):
    """The capture's own triple, as the live receipt returns it."""
    return {"program": program, "identity": {
        "schema": "kir-create-identity-assessment/1", "receipt_digest": "d" * 64,
        "outputs": [{"output_id": op["id"], "source_op": op["op"], "state": "created_here",
                     "element_identity": {"schema_version": "revit-element-identity/1",
                                          "unique_id": f"7ff4b512-…-{index:05d}",
                                          "element_id": 274500 + index,
                                          "version_guid": "7ff4b512b2994d75810762effd492f45"}}
                    for index, op in enumerate(program["ops"])]}}


def _plan(new, old=None):
    old = old if old is not None else section()
    return plan_republish(None, new, _identity(old))


def test_p1_a_row_carries_the_whole_identity_not_only_the_unique_id():
    """П1. `set_param`/`move_elements`/`change_type`/`delete` address by ElementId."""
    rows = [row for row in _plan(section(height_mm=3300)).rows if row["action"] == "update"]
    assert rows, "изменение параметра не дало ни одной строки update"
    for row in rows:
        identity = row["identity_before"]
        assert set(identity) == {"schema_version", "element_id", "unique_id", "version_guid"}
        assert identity["schema_version"] == "revit-element-identity/1"
        assert isinstance(identity["element_id"], int)
        # the mirror stays, but it is a mirror
        assert row["uid_before"] == identity["unique_id"]


def test_p2_a_known_field_is_addressed_by_builtin_parameter_not_by_a_display_name():
    """П2. The owner's Revit is Russian; a display name would be refused there."""
    rows = [row for row in _plan(section(height_mm=3300)).rows if row["action"] == "update"]
    assert {row["update_via"] for row in rows} == {"builtin_parameter"}
    assert {row["parameter"] for row in rows} == {"WALL_USER_HEIGHT_PARAM"}


def test_p2_control_a_field_outside_the_table_becomes_a_replace_not_a_promise():
    """The table is closed: no route, no `update`."""
    other = section()
    other["ops"][2] = {**other["ops"][2], "structural": True}
    row = [item for item in _plan(other).rows if item["output_id"] == WALLS[0]][0]
    assert row["action"] == "replace" and row["reason"] == "replace_no_update_op"
    assert row["update_via"] is None


def test_p4_allow_destructive_is_a_program_flag_raised_only_when_something_goes():
    """П4. `{"op": "delete"}` without it is KIR-D001."""
    assert _plan(section()).to_dict()["destructive"] is False
    assert _plan(section(height_mm=3300)).to_dict()["destructive"] is False
    assert _plan(section(walls=3)).to_dict()["destructive"] is True
    assert _plan(section(type_width_mm=300)).to_dict()["destructive"] is True


def test_p5_a_replaced_type_names_its_dependants_and_its_cascade_before_the_effect():
    """П5. Live, one deletion took 10/13/12/38 ids with it."""
    row = [item for item in _plan(section(type_width_mm=300)).rows
           if item["action"] == "replace"][0]
    assert row["source_op"] == "create_wall_type"
    # the four walls that stand on this type are named as the rebinding order
    assert sorted(row["depends_on"]) == sorted(WALLS)
    assert row["cascade"]["named"] is True
    assert row["cascade"]["outputs"] == sorted(WALLS)
    assert row["identity_replacement"] == {
        "old": row["identity_before"]["unique_id"], "new": None,
        "reason": "replace_no_update_op"}


def test_p6_the_version_guid_is_carried_and_is_not_read_as_a_version():
    """П6. On an unsaved document it is the DOCUMENT's episode, one for all."""
    rows = _plan(section(height_mm=3300)).rows
    guids = {row["identity_before"]["version_guid"] for row in rows
             if row["identity_before"]}
    assert guids == {"7ff4b512b2994d75810762effd492f45"}, "квитанция даёт один guid на всех"
    # and the plan never uses it to claim "did not change either"
    assert all(row["identity_state_before"] == "created_here" for row in rows
               if row["identity_before"])


def test_a_cascade_that_could_not_be_named_is_refused_not_executed():
    """`named: false` is itself a reason not to execute the row."""
    from kir.project_republish import _row, RepublishError as Failure, RepublishPlan, _guard

    row = _row(WALLS[0], "create_wall", "removed_from_program",
               {"schema_version": "revit-element-identity/1", "element_id": 1,
                "unique_id": "u", "version_guid": "g"}, "created_here", {}, "test",
               cascade={"named": False, "ids": []})
    with pytest.raises(Failure) as caught:
        _guard(RepublishPlan((row,), "p", None, None, "create_imports"))
    assert caught.value.code == "cascade_not_named"
