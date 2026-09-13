"""THE PAIR OF NUMBERS of the whole programme, living in the tree, not in `.work`.

Ported 13.09.2026 from stage R8 of `.work/prod-20260913/republish/plan_acceptance.py`
(`plan-tree-06.log`: 9 stages, 9 ДА), by the lead's word — an instrument that
proves a product law belongs beside the product.

🔴 WHY TWO NUMBERS AND NOT ONE. Live Revit 2023, the same day, two receipts:
* `live-20260913-slice-receipt.json` — the repeat REFUSED (`stale_or_failed`,
  «тип с этим адресом уже существует с другим составом») and `atomic` rolled
  everything back: walls 4/4/4, floors 1/1/1, instances 3915/3915/3915.
  Zero new instances — and zero work.
* `live-20260913-slice-opening-receipt.json` — nothing refused, `ok: true`, and
  every repeat added +4 walls, +1 floor, **+25 instances**: walls 4→8→12,
  floors 1→2→3, instances 3913→3938→3968.

So "0 new instances" ALONE is not the goal: the first receipt already gives it,
by refusing. The pair that must hold together is
**новых экземпляров поверх известных 0 И риска `stale_or_failed` 0**.

The scene is the live section (ДОК-A1): a wall type, two levels, four walls and
a floor with an opening — eight named outputs. Revit is not launched.
"""
import pytest

from kir.project_republish import plan_republish
from kir.project_republish_program import RepublishProgramError, republish_program

LEVEL_1, LEVEL_2 = "1" * 64, "2" * 64
WALL_TYPE, FLOOR = "3" * 64, "8" * 64
WALLS = [str(index) * 64 for index in (4, 5, 6, 7)]
OPENING = [[2000.0, 2000.0], [4000.0, 2000.0], [4000.0, 4000.0], [2000.0, 4000.0]]


def section(*, height_mm=3000, type_width_mm=230, shift_mm=0.0, walls=4,
            type_name="KIR_секция", opening=True):
    corners = [[shift_mm, 0.0], [shift_mm + 6000.0, 0.0],
               [shift_mm + 6000.0, 6000.0], [shift_mm, 6000.0]]
    ops = [{"op": "create_level", "id": LEVEL_1, "elev_mm": 0, "name": "KIR уровень 1"},
           {"op": "create_level", "id": LEVEL_2, "elev_mm": 3300, "name": "KIR уровень 2"},
           {"op": "create_wall_type", "id": WALL_TYPE, "host_kind": "wall",
            "new_name": type_name, "source_type": {"by": "name", "value": "Типовой"},
            "layers": [{"width_mm": type_width_mm, "function": "Structure",
                       "material": "Бетон"}]}]
    for index in range(walls):
        ops.append({"op": "create_wall", "id": WALLS[index], "p0_mm": corners[index],
                    "p1_mm": corners[(index + 1) % 4], "height_mm": height_mm,
                    "level": {"by": "ref", "value": LEVEL_1},
                    "type": {"by": "ref", "value": WALL_TYPE}})
    contour = {"outer": {"shape": "poly", "points_mm": corners}}
    if opening:
        contour["holes"] = [{"shape": "poly", "points_mm": OPENING}]
    ops.append({"op": "create_floor_by_contour", "id": FLOOR, "contour": contour,
                "level": {"by": "ref", "value": LEVEL_2}})
    return {"ir_version": "1.0", "intent": "живая секция", "lineage": "section", "ops": ops}


def published(program):
    return {"program": program, "identity": {
        "schema": "kir-create-identity-assessment/1", "receipt_digest": "d" * 64,
        "outputs": [{"output_id": op["id"], "source_op": op["op"],
                     "state": "reused_existing" if op["op"] == "create_wall_type"
                              else "created_here",
                     "element_identity": {"schema_version": "revit-element-identity/1",
                                          "unique_id": f"7ff4b512-b299-4d75-8107-62effd492f45-{42980 + index:08x}",
                                          "element_id": 274500 + index,
                                          "version_guid": "7ff4b512b2994d75810762effd492f45"}}
                    for index, op in enumerate(program["ops"])]}}


#: Five edits an author actually makes, and what each must cost in NEW elements.
#: 🔴 The type edit carries `walls=0` on purpose: with users on it, a type
#: replacement is refused `replace_of_a_type_needs_two_programs`
#: (`change_type.type` takes only `element_id`, and a type not yet built has
#: none). That refusal has its own pin below; here the subject is the COUNT of
#: new elements, and it must be measured where a program exists.
EDITS = {
    "без изменений": (section(), 0),
    "параметр": (section(height_mm=3300), 0),
    "тип без носителей (новый состав И новое имя)": (
        section(walls=0, type_width_mm=300, type_name="KIR_секция_300"), 1),
    "жёсткий сдвиг": (section(shift_mm=1000.0), 1),
    "меньше стен": (section(walls=3), 0),
}


@pytest.mark.parametrize("name", sorted(EDITS))
def test_no_edit_creates_anything_over_an_element_that_already_exists(name):
    """THE LAW. A new element may appear; a SECOND COPY of a known one may not."""
    program, expected_creates = EDITS[name]
    base = section(walls=0) if "без носителей" in name else section()
    plan = plan_republish(None, program, published(base))
    derived = republish_program(plan, program)

    known = {row["output_id"] for row in plan.to_dict()["rows"] if row.get("identity_before")}
    creates = [op for op in derived.program["ops"] if op["op"].startswith("create_")]
    over_known = [op for op in creates if op["id"] in known]

    assert over_known == [], f"{name}: создание поверх известного элемента — это дубль"
    assert len(creates) == expected_creates, name
    assert plan.creates_over_known_identity() == ()


def test_a_repeat_with_no_change_asks_revit_for_nothing_at_all():
    base = section()
    derived = republish_program(plan_republish(None, section(), published(base)), section())
    assert derived.program["ops"] == []
    assert derived.destructive is False
    assert len(derived.expected_identities) == 8, "восемь выходов сцены сверяет пролог"


def test_a_type_with_users_is_refused_as_needing_two_programs():
    """`change_type.type` takes only `element_id`, and a new type has none yet."""
    base = section()
    program = section(type_width_mm=300, type_name="KIR_секция_300")
    plan = plan_republish(None, program, published(base))
    with pytest.raises(RepublishProgramError) as caught:
        republish_program(plan, program)
    assert caught.value.code == "replace_of_a_type_needs_two_programs"
    assert "СЛЕДУЮЩИЙ ХОД" in str(caught.value)


def test_control_the_shape_that_refused_live_is_refused_here_offline():
    """A type redefined WITHOUT a new name is exactly what answered
    `stale_or_failed` and rolled the whole live publication back."""
    base = section()
    program = section(type_width_mm=300)          # тот же new_name
    plan = plan_republish(None, program, published(base))
    with pytest.raises(RepublishProgramError) as caught:
        republish_program(plan, program)
    assert caught.value.code == "replace_would_collide_with_the_existing_name"
    assert "stale_or_failed" in str(caught.value)


def test_every_operation_addresses_an_existing_element_by_its_identity():
    """Nothing in a derived program may point at an output it does not build."""
    for name in sorted(EDITS):
        program, _ = EDITS[name]
        base = section(walls=0) if "без носителей" in name else section()
        plan = plan_republish(None, program, published(base))
        derived = republish_program(plan, program)
        built = {op["id"] for op in derived.program["ops"]}
        for op in derived.program["ops"]:
            for value in _selectors(op):
                if value.get("by") == "ref":
                    assert value["value"] in built, (
                        f"{name}: {op['op']} ссылается на {value['value'][:8]}…, "
                        "которого программа не строит — это KIR-L003")
                elif value.get("by") in ("unique_id", "element_id"):
                    # a write target knows `unique_id`; a `sel` slot knows
                    # `element_id` — each gets the form it accepts
                    assert value["value"], name


def _selectors(value):
    if isinstance(value, dict):
        if "by" in value:
            yield value
        for item in value.values():
            yield from _selectors(item)
    elif isinstance(value, list):
        for item in value:
            yield from _selectors(item)
