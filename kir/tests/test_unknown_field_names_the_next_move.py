"""KIR-P003 at the JSON door must name the NEXT MOVE, not just the reason.

THE MEASUREMENT THAT BOUGHT THIS FILE — a live turn of the owner's on 16.08.2026, on the flash
model `deepseek-v4-flash`. In ONE turn, two refusals landed side by side, and they behaved
OPPOSITELY:

  * `KIR-T002`, `create_roof.slopes` — «slopes без единого угла — это плоская
    крыша, просто не задавай поле». The corrected program arrived after
    FOUR SECONDS (10:45:45 -> 10:45:49);
  * `KIR-P003`, `create_door.__host_wall__` — «неизвестное поле». The turn DIED.

There is exactly one difference: the first text carries the next move, the second carries only the reason.

WHY THIS IS CHECKED, RATHER THAN LEFT TO TASTE. The owner's requirement from
16.08: KIR must work on a FLASH model ("ordinary subscribers must also be
able to use it"). So a refusal's text is not documentation for the clever, but a
RAIL for the weak, and it must be held in place by an instrument.

🔴 WHAT THIS FILE DOES NOT CHECK. It does not check that the model WILL OBEY. That is a
property of the model, measured by a ladder, not by a test suite. What is held here is exactly
what is within our power: the next move is NAMED and DERIVED FROM THE REGISTRY.
"""
from __future__ import annotations

import unittest

from kir import compiler, spec
from kir.tests.test_course import GROUND_SNAPSHOT

LVL = {"by": "name", "value": "Этаж 1"}


def _compile(op: dict):
    program = {"ir_version": spec.IR_VERSION, "intent": "контроль", "ops": [op]}
    return compiler.compile_program(
        program, revit_version="2026", snapshot=GROUND_SNAPSHOT, bulk=False)


def _p003(res) -> str:
    for d in (res.diagnostics or []):
        if d.code == "KIR-P003":
            return d.message_ru or ""
    raise AssertionError(
        "KIR-P003 не поднялся вовсе — зонд слеп, а не предмет исправен; "
        f"коды: {[d.code for d in (res.diagnostics or [])]}")


class TheRefusalNamesTheNextMove(unittest.TestCase):
    def test_it_names_the_next_move_in_words(self):
        """A FAIL CONTROL: revert message_ru to the bare «неизвестное поле 'x' у y»
        — this test will turn red, and it will turn red BEHAVIORALLY, on the text that
        the model reads, not on the mere presence of a symbol."""
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "height": 3000}))
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg,
                      "отказ назвал повод и не назвал следующий ход")

    def test_the_slots_come_from_the_registry_not_from_prose(self):
        """The list of slots must BE DERIVED, not hand-written.

        What is checked is not "there are words in the text", but a match against the registry: every
        parameter of the op must be named. A handwritten list would drift apart from the
        registry on the very first new operation, and it would drift SILENTLY — in this
        tree EVERY handwritten list has drifted, and NOT ONE generated one has.
        """
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "height": 3000}))
        missing = [p.name for p in spec.OPS["create_wall"].params
                   if p.name not in msg]
        self.assertEqual(missing, [],
                         f"слоты реестра не названы в отказе: {missing}")

    def test_a_near_miss_gets_the_near_name(self):
        """`height` -> `height_mm`. The `_mm` suffix is the most common slip."""
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "height": 3000}))
        self.assertIn("height_mm", msg)
        self.assertIn("Похоже на", msg,
                      "ближайшее имя не предложено, хотя оно вычислимо")

    def test_a_far_miss_does_not_invent_a_neighbour(self):
        """THE OPPOSITE POLE, without which the fix would collapse into "always suggest something".

        For a field that resembles nothing, a "did you mean" must NOT appear:
        a made-up neighbor is worse than silence, because it gets checked with a turn.
        """
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "зззз": 1}))
        self.assertNotIn("Похоже на", msg)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg,
                      "следующий ход обязан быть назван и без соседа")

    def test_the_call_form_has_one_generator_for_both_doors(self):
        """The scripting door and the JSON door print ONE form of the op, not two similar ones.

        A second text about the op's form would be a second opinion and would drift apart from the first
        precisely when both are read back to back. It is held in place by the identity of the string, not by
        a promise in a docstring.
        """
        from kir.dsl import _call_form
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "height": 3000}))
        self.assertIn(_call_form(spec.OPS["create_wall"]), msg,
                      "JSON-дверь печатает СВОЮ форму опа, а не общую")


class TheSyntheticFieldIsStillRefusedWhereItDoesNotBelong(unittest.TestCase):
    """Verbosity has no right to become a jammer for refusals.

    `__host_wall__` at its owner's (`create_door`) is LIFTED by parsing; on a foreign
    op it is still KIR-P003. This pole is already held by
    `test_synthetic_fields_have_one_authority.py`; what is checked here is that my
    text did not blur it.
    """

    def test_owner_op_passes_and_stranger_op_refuses(self):
        door = _compile({"op": "create_door", "id": "d1",
                         "host": {"by": "element_id", "value": 424242},
                         "offset_mm": 1500,
                         spec.SYNTHETIC_HOST_WALL: {"p0_mm": [0, 0],
                                                    "p1_mm": [1000, 0]}})
        codes = {d.code for d in (door.diagnostics or [])}
        self.assertNotIn("KIR-P003", codes,
                         "синтетика у владельца обязана сниматься молча")

        wall = _compile({"op": "create_wall", "id": "w1",
                         "p0_mm": [0, 0], "p1_mm": [4000, 0], "level": LVL,
                         spec.SYNTHETIC_HOST_WALL: {"p0_mm": [0, 0]}})
        self.assertIn("KIR-P003", {d.code for d in (wall.diagnostics or [])},
                      "синтетика у чужого опа обязана остаться отказом")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
