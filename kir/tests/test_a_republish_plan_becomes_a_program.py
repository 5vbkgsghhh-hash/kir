"""A republish plan becomes a program that changes in place instead of rebuilding.

Live Revit 2023, 13.09.2026, two receipts of the same day: a repeat publication
either refuses entirely (`live-20260913-slice-receipt.json` — walls 4/4/4,
floors 1/1/1, instances 3915/3915/3915, `publish_2` = `stale_or_failed`) or
duplicates entirely (`live-20260913-slice-opening-receipt.json` — walls 4→8→12,
floors 1→2→3, instances 3913→3938→3968). The pair of numbers the derived program
is answerable to is therefore **0 new instances AND 0 `stale_or_failed`**.

🔴 THE OP FORM BELONGS TO SECTION N AND IS NOT YET IN THE REGISTRY
(`{"by": "unique_id"}`, `expected_identity`, `expected_current`). The shape is
pinned here now; the compile lane below is written so that it is TRUE BOTH
BEFORE AND AFTER N lands it, and prints which of the two states holds — a pin on
an absence rots the moment the work succeeds.
"""
import json

import pytest

from kir.project_republish import plan_republish
from kir.project_republish_program import (RepublishProgramError, republish_program)

LEVEL, WALL_TYPE, FLOOR = "1" * 64, "3" * 64, "8" * 64
WALLS = [str(index) * 64 for index in (4, 5, 6, 7)]


def section(*, height_mm=3000, type_width_mm=230, walls=4, shift_mm=0.0,
            type_name="секция"):
    corners = [[shift_mm, 0.0], [shift_mm + 6000.0, 0.0],
               [shift_mm + 6000.0, 6000.0], [shift_mm, 6000.0]]
    ops = [{"op": "create_level", "id": LEVEL, "elev_mm": 0, "name": "Уровень 1"},
           {"op": "create_wall_type", "id": WALL_TYPE, "host_kind": "wall",
            "new_name": type_name, "source_type": {"by": "name", "value": "Типовой"},
            "layers": [{"width_mm": type_width_mm, "function": "Structure",
                       "material": "Бетон"}]}]
    for index in range(walls):
        ops.append({"op": "create_wall", "id": WALLS[index], "p0_mm": corners[index],
                    "p1_mm": corners[(index + 1) % 4], "height_mm": height_mm,
                    "level": {"by": "ref", "value": LEVEL},
                    "type": {"by": "ref", "value": WALL_TYPE}})
    ops.append({"op": "create_floor_by_contour", "id": FLOOR,
                "level": {"by": "ref", "value": LEVEL},
                "contour": {"outer": {"shape": "poly", "points_mm": corners}}})
    return {"ir_version": "1.0", "intent": "секция", "lineage": "sec", "ops": ops}


def published(program):
    return {"program": program, "identity": {
        "schema": "kir-create-identity-assessment/1", "receipt_digest": "d" * 64,
        "outputs": [{"output_id": op["id"], "source_op": op["op"], "state": "created_here",
                     # 🔴 THE UniqueId IS THE LIVE DOCUMENT'S SHAPE, not a label:
                     # `8-4-4-4-12-суффикс` (`kir/authoring_validation.py:775`),
                     # taken from the owner's receipt
                     # `live-20260913-slice-receipt.json`. A made-up string used
                     # to pass here and be refused by the emitter — the fixture
                     # was measuring the wrong thing.
                     "element_identity": {"schema_version": "revit-element-identity/1",
                                          "unique_id": f"7ff4b512-b299-4d75-8107-62effd492f45-{42980 + index:08x}",
                                          "element_id": 274500 + index,
                                          "version_guid": "7ff4b512b2994d75810762effd492f45"}}
                    for index, op in enumerate(program["ops"])]}}


def derive(new, old=None):
    old = old if old is not None else section()
    return republish_program(plan_republish(None, new, published(old)), new)


def test_a_repeat_with_no_change_emits_no_operation_at_all():
    """THE MAIN NUMBER: nothing is created, and nothing is even asked of Revit."""
    derived = derive(section())
    assert derived.program["ops"] == []
    assert derived.counts["create"] == 0 and derived.counts["keep"] == 7
    # the kept outputs are proved by the prologue's guard, not by a read op each
    assert len(derived.expected_identities) == 7
    assert derived.destructive is False
    assert "allow_destructive" not in derived.program


def test_a_changed_parameter_becomes_set_param_by_unique_id_with_both_expectations():
    derived = derive(section(height_mm=3300))
    ops = derived.program["ops"]
    assert [op["op"] for op in ops] == ["set_param"] * 4
    for op in ops:
        assert op["target"] == {"by": "unique_id", "value": op["expected_identity"]["unique_id"]}
        assert op["param"] == "WALL_USER_HEIGHT_PARAM", "имя параметра не зависит от языка"
        assert op["value"] == {"value": 3300, "unit": "mm"}
        assert op["expected_current"] == {"value": 3000, "unit": "mm"}
        # 🔴 THE OPERATION TAKES TWO FIELDS, THE PLAN CARRIES FOUR, and that is
        # not sloppiness on either side: `kir/authoring_validation.py:1668`
        # refuses anything but `{unique_id, version_guid}`, while the plan needs
        # `element_id` to address and `schema_version` to say what it is. The
        # converter narrows; it does not drop.
        assert set(op["expected_identity"]) == {"unique_id", "version_guid"}
    assert derived.counts["create"] == 0


def test_a_rigid_shift_becomes_move_elements_with_one_delta():
    derived = derive(section(shift_mm=1000.0))
    moves = [op for op in derived.program["ops"] if op["op"] == "move_elements"]
    assert len(moves) == 4
    for op in moves:
        assert op["delta_mm"] == [1000.0, 0.0, 0.0]
        assert op["targets"] == [{"by": "unique_id", "value": op["expected_identity"]["unique_id"]}]


def test_a_replaced_type_with_users_needs_two_programs_and_says_so():
    """🔴 MEASURED AFTER SECTION N LANDED THE FORM (`fc6ef65`, 13.09.2026).

    Contract §2/П5 orders create → rebind → delete. The registry then showed the
    order cannot be ONE program: `change_type.type` takes only `element_id`
    («type в v1 — только element_id»), and a type that has not been built yet has
    no id. Emitting the six ops anyway would ship a program whose refusal is
    already known — so the converter refuses first, and names the two programs.
    This is the same shape as `create_stairs` being SOLO: a building is a BATCH.
    """
    with pytest.raises(RepublishProgramError) as caught:
        derive(section(type_width_mm=300, type_name="секция 300"))
    assert caught.value.code == "replace_of_a_type_needs_two_programs"
    assert "СЛЕДУЮЩИЙ ХОД" in str(caught.value)
    assert "element_id" in str(caught.value)


def test_a_replacement_with_no_users_is_one_program_in_the_contract_order():
    """Without dependants there is nothing to rebind, and the order holds."""
    base = section(walls=0)
    derived = republish_program(
        plan_republish(None, section(walls=0, type_width_mm=300, type_name="секция 300"),
                       published(base)),
        section(walls=0, type_width_mm=300, type_name="секция 300"))
    kinds = [op["op"] for op in derived.program["ops"]]
    assert kinds == ["create_wall_type", "delete"]
    assert derived.destructive is True and derived.program["allow_destructive"] is True


def test_control_a_replacement_that_keeps_the_old_name_is_refused_offline():
    """Live this exact shape was `stale_or_failed` + a rollback of everything."""
    with pytest.raises(RepublishProgramError) as caught:
        derive(section(type_width_mm=300))
    assert caught.value.code == "replace_would_collide_with_the_existing_name"
    assert "stale_or_failed" in str(caught.value)
    assert "СЛЕДУЮЩИЙ ХОД" in str(caught.value)


def test_a_carried_create_is_regrounded_to_known_identities():
    """A re-created floor still stands on a level this program does NOT create."""
    derived = derive(section(shift_mm=1000.0))
    floors = [op for op in derived.program["ops"] if op["op"] == "create_floor_by_contour"]
    assert floors, "сдвиг контура перекрытия должен дать пересоздание"
    # 🔴 BY element_id: a `sel` slot takes `name|element_id|default|ref` and does
    # NOT know `unique_id` — only write targets do. Measured 13.09.2026.
    assert floors[0]["level"]["by"] == "element_id", (
        "ссылка на уровень, которого нет в производной программе, обязана быть "
        "заземлена идентификатором, который слот принимает, иначе KIR-T001")
    assert isinstance(floors[0]["level"]["value"], int)


def test_a_removed_output_is_a_delete_by_unique_id_and_nothing_else():
    derived = derive(section(walls=3))
    assert [op["op"] for op in derived.program["ops"]] == ["delete"]
    op = derived.program["ops"][0]
    assert op["target"]["by"] == "unique_id"
    assert set(op["expected_identity"]) == {"unique_id", "version_guid"}
    assert op["expected_identity"]["unique_id"] == op["target"]["value"]
    assert derived.counts["create"] == 0


def test_control_a_create_over_a_known_identity_is_refused_by_the_converter_too():
    """The planner cannot emit it; the converter still refuses to execute it."""
    plan = plan_republish(None, section(), published(section())).to_dict()
    plan["rows"][0] = {**plan["rows"][0], "action": "create"}
    with pytest.raises(RepublishProgramError) as caught:
        republish_program(plan, section())
    assert caught.value.code == "create_over_known_identity"


def test_control_an_action_outside_the_closed_list_is_refused_by_name():
    plan = plan_republish(None, section(), published(section())).to_dict()
    plan["rows"][0] = {**plan["rows"][0], "action": "patch"}
    with pytest.raises(RepublishProgramError) as caught:
        republish_program(plan, section())
    assert caught.value.code == "action_outside_the_closed_list"


def test_control_a_destructive_plan_and_a_harmless_program_cannot_disagree():
    plan = plan_republish(None, section(walls=3), published(section())).to_dict()
    plan["destructive"] = False
    with pytest.raises(RepublishProgramError) as caught:
        republish_program(plan, section(walls=3))
    assert caught.value.code == "destructive_flag_disagrees_with_the_plan"


def test_control_a_parameter_without_a_builtin_route_never_becomes_set_param():
    plan = plan_republish(None, section(height_mm=3300), published(section())).to_dict()
    plan["rows"] = [{**row, "update_via": None, "parameter": None}
                    if row["action"] == "update" else row for row in plan["rows"]]
    with pytest.raises(RepublishProgramError) as caught:
        republish_program(plan, section(height_mm=3300))
    assert caught.value.code == "parameter_has_no_route"


def test_where_the_registry_stands_today_on_the_new_op_form():
    """🔴 TWO-SIDED ON PURPOSE, so it does not rot when section N lands the form.

    Either the derived program compiles (N has landed `{by: unique_id}` +
    `expected_identity` + `expected_current`), or it is refused — and then the
    refusal must be about THE FORM and nothing else. Both states are true
    statements about the tree; the test says which one holds.
    """
    from kir.compiler import compile_program
    from kir.diag import KirRefusal

    #: The two codes that ARE the form: an unknown envelope/op field, and a
    #: selector shape the slot does not know yet. Anything else would mean the
    #: derived program is wrong about something OTHER than N's pending input.
    form_codes = {"KIR-P003", "KIR-T001"}

    derived = derive(section(height_mm=3300))
    try:
        out = compile_program(derived.program, "2026")
    except KirRefusal as failure:
        codes = {diagnostic.code for diagnostic in failure.diagnostics}
        messages = [diagnostic.message_ru[:140] for diagnostic in failure.diagnostics][:2]
    else:
        if out.ok:
            # Section N has landed the form: then the whole point must hold.
            assert derived.counts["create"] == 0, "форма введена, а программа всё равно создаёт"
            return
        codes = {diagnostic.code for diagnostic in (out.diagnostics or ())}
        messages = [diagnostic.message_ru[:140] for diagnostic in (out.diagnostics or ())][:2]
    assert codes <= form_codes, (
        "пока форма не введена, отказ обязан быть ТОЛЬКО про форму входа "
        f"({sorted(form_codes)}); пришло {sorted(codes)}: {messages}")
    assert "expected_identity" in json.dumps(messages, ensure_ascii=False) or \
           "unique_id" in json.dumps(messages, ensure_ascii=False), \
        "отказ обязан НАЗЫВАТЬ поле или форму, которых ждёт раздел N"
