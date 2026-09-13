"""A solo op explains ITSELF at the first refusal, not at the planner's.

🔴 BOUGHT BY A MEASUREMENT (13.09.2026, RQ7 expressibility matrix, task P05).
`create_stairs(base_level=<уровень этой же программы>)` is the program any
author writes first — «создать этажи и поставить между ними лестницу». Of the
36 level slots in the registry, 34 take a reference and exactly these two do
not, so the refusal is right. But the FIRST thing the author read was the
contract's plumbing — «ref_kinds пуст» — while the reason is a property of the
BUILDING: the op owns its own transactions, so it is the only op of its program,
and the level comes from a neighbouring one BY NAME.

The planner already says that, and says it well (`kir/compiler.py:1862`,
KIR-L002). It just speaks SECOND. This file pins that the DSL speaks first in
the SAME words — two carriers of one sentence held by a pin, because
`kir/compiler.py` belongs to another section this wave.
"""
import pytest

from kir import dsl, spec


def _stairs_refusal():
    dsl.reset()
    dsl.envelope(intent="лестница между этажами одной программы")
    base = dsl.create_level(elev_mm=0, name="Этаж 1")
    top = dsl.create_level(elev_mm=3000, name="Этаж 2")
    with pytest.raises(dsl.DslRefusal) as caught:
        dsl.create_stairs(base_level=base, top_level=top,
                          p0_mm=[0.0, 0.0], p1_mm=[3000.0, 5000.0], width_mm=1200.0)
    return str(caught.value)


def _planner_solo_message():
    """The planner's own KIR-L002 text, taken from the planner, not retyped."""
    from kir.compiler import plan_program
    from kir.diag import KirRefusal

    program = {"ir_version": "1.0", "intent": "две вещи в одной программе", "ops": [
        {"op": "create_level", "id": "lv", "elev_mm": 0, "name": "Этаж 1"},
        {"op": "create_stairs", "id": "st", "base_level": {"by": "name", "value": "Этаж 1"},
         "top_level": {"by": "name", "value": "Этаж 2"}},
    ]}
    with pytest.raises(KirRefusal) as caught:
        plan_program(program)
    solo = [d for d in caught.value.diagnostics if d.code == "KIR-L002"]
    assert solo, [d.code for d in caught.value.diagnostics]
    return solo[0].message_ru


def test_the_first_refusal_names_the_reason_not_the_contract_plumbing():
    text = _stairs_refusal()
    assert "ref_kinds" not in text, "первым автор читает причину, а не механику контракта"
    assert "владеет собственными транзакциями" in text
    assert "ЕДИНСТВЕННЫМ опом своей программы" in text
    assert "KIR-L002" in text, "тот же код, что назовёт планировщик"


def test_the_first_refusal_still_names_the_next_move_and_the_admissible_forms():
    text = _stairs_refusal()
    assert "СЛЕДУЮЩИЙ ХОД" in text
    assert 'base_level="Этаж 1"' in text, "ход должен быть исполним, а не общим советом"
    assert "'name', 'element_id', 'default'" in text or "name" in text


def test_the_dsl_and_the_planner_speak_the_same_words():
    """🔴 THE TIE. Two carriers of one sentence diverge unless something holds them."""
    first, second = _stairs_refusal(), _planner_solo_message()
    for phrase in ("своей программы", "ПАЧКА", "ИМЕНИ"):
        assert phrase in first, (phrase, "нет в отказе DSL")
        assert phrase in second, (phrase, "нет в отказе планировщика")
    assert "create_stairs" in first and "create_stairs" in second


def test_control_a_non_solo_slot_keeps_the_contract_wording():
    """The plumbing sentence is right where the reason IS the contract."""
    from kir.dsl import _no_ref_reason

    stairs = spec.OPS["create_stairs"]
    level_slot = next(p for p in stairs.params if p.name == "base_level")
    assert "ref_kinds" not in _no_ref_reason(stairs, level_slot)

    wall = spec.OPS["create_wall"]
    type_slot = next(p for p in wall.params if p.name == "type")
    assert "ref_kinds" in _no_ref_reason(wall, type_slot)


def test_control_every_solo_op_gets_the_same_treatment():
    """Five ops are solo; none of them may fall back to the plumbing sentence."""
    from kir.dsl import _no_ref_reason

    assert spec.SOLO_OPS, "список solo-опов пуст — проверять нечего"
    for name in sorted(spec.SOLO_OPS):
        ospec = spec.OPS[name]
        slot = next((p for p in ospec.params
                     if p.kind in ("sel", "target", "target_w")), None)
        if slot is None:
            continue
        text = _no_ref_reason(ospec, slot)
        assert "ref_kinds" not in text, name
        assert "ЕДИНСТВЕННЫМ опом своей программы" in text, name
