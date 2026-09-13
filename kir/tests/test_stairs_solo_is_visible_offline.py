"""A RULE REACHABLE ONLY ON A LIVE DEVICE IS HALF A RULE.

`create_stairs` must be the sole op of its program: its `StairsEditScope`
owns its own transactions and does not nest inside the program's overall
transaction. This is a FACT of the Revit API, not our whim, and the
prohibition is correct.

THE DEFECT MEASURED ON 04.08 is not in the prohibition, but in WHERE it
lived. In exactly one place: `authoring.emit_program`, i.e. AFTER
grounding. So the sandbox was compiling the program, `plan_program` was
accepting it SILENTLY, and the model only found out about the wall on a
live device, where a round trip costs the most of all:

    plan_program({"ops": [create_stairs, create_wall]})  ->  ACCEPTED

This rule is about the SHAPE OF THE PROGRAM, not about the document: to
check it, Revit is not needed at all. It now also sits on the plan
(`compiler.plan_program`, reading `spec.SOLO_OPS`), and the emitter's
refusal REMAINS verbatim where it was — a last line of defense, not a
duplicate.

THE SECOND HALF OF THE LAW is in `test_verdict_takes_kir_ops.py`: since a
staircase must be a separate program, judging must be done on a BATCH of
programs, otherwise a multi-story building is unfit by construction.

Run: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kir/tests/test_stairs_solo_is_visible_offline.py -q
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir import authoring, spec  # noqa: E402
from kir.compiler import compile_program  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

STAIRS = {"op": "create_stairs", "id": "S1",
          "p0_mm": [0, 0], "p1_mm": [0, 3000],
          "base_level": {"by": "name", "value": "Этаж 1"},
          "top_level": {"by": "name", "value": "Этаж 2"},
          "width_mm": 1200}
WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
        "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000}


def _prog(ops):
    return {"ir_version": "1.0", "intent": "тест", "ops": ops}


class SoloOpVisibleOffline(unittest.TestCase):

    def test_a_neighbour_is_refused_at_plan_time(self):
        """The actual fix: a refusal WITHOUT live Revit."""
        out = compile_program(_prog([STAIRS, WALL]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", [d.code for d in out.diagnostics])

    def test_it_does_not_matter_which_side_the_neighbour_is_on(self):
        """The order of ops must not matter: the rule is about the
        program's MEMBERSHIP."""
        out = compile_program(_prog([WALL, STAIRS]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", [d.code for d in out.diagnostics])

    def test_even_a_level_is_a_neighbour(self):
        """A level next to a staircase is the most natural thing a model
        would write, and it was exactly this that was silently passing the
        plan. The level belongs to the BODY's program, and the staircase
        addresses it by name."""
        level = {"op": "create_level", "id": "L1", "elev_mm": 0,
                 "name": "Этаж 1"}
        out = compile_program(_prog([level, STAIRS]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", [d.code for d in out.diagnostics])

    def test_the_refusal_says_where_to_put_the_rest(self):
        """A prohibition without a way out is a dead end. In the 03.08
        measurement a strong model agreed with the rule, wrote so in its
        own script — and glued a staircase together out of 15
        `create_floor` calls, because it did not know WHERE to put the
        rest. The refusal must name the BATCH and the way to address the
        level across its boundary."""
        out = compile_program(_prog([STAIRS, WALL]), snapshot=SNAPSHOT)
        text = " ".join(d.message_ru for d in out.diagnostics
                        if d.code == "KIR-L002")
        self.assertIn("ПАЧКА", text)
        self.assertIn("ИМЕНИ", text)

    def test_the_solo_program_itself_still_compiles(self):
        """The prohibition must be CONDITIONAL: a rule that always refuses
        is a removed capability, not a rule."""
        out = compile_program(_prog([STAIRS]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_an_ordinary_program_is_untouched(self):
        """And adjacency by itself is legitimate — the solo-op status has
        nothing to do with it here."""
        out = compile_program(_prog([WALL, dict(WALL, id="W2")]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_the_emitter_keeps_its_own_last_line_of_defence(self):
        """The duplication is DELIBERATE. `emit_program` is a public
        function: it must refuse on its own, not rely on having been
        reached through the plan."""
        grounded = [
            dict(STAIRS, base_level={"via": "element_id", "id": 1},
                 top_level={"via": "element_id", "id": 2}),
            dict(WALL, level={"via": "element_id", "id": 1}),
        ]
        with self.assertRaises(Exception) as caught:
            authoring.emit_program(grounded, "2023")
        codes = [d.code for d in getattr(caught.exception, "diagnostics", ())]
        self.assertIn("KIR-L002", codes)

    def test_the_rule_reads_the_registry_not_a_hardcoded_name(self):
        """ONE FACT — ONE PLACE. Before 04.08, "create_stairs is a
        soloist" was written three times: a hardcode in the emitter, a
        private `_SOLO_OPS` in `decompile/materialize.py`, and prose. A
        fact stated in three places diverges in two of them."""
        self.assertIn("create_stairs", spec.SOLO_OPS)
        for name in spec.SOLO_OPS:
            self.assertIn(name, spec.OPS,
                          "правило о несуществующем опе никто не применяет")
        from kir.decompile import materialize
        self.assertIs(materialize._SOLO_OPS, spec.SOLO_OPS)


if __name__ == "__main__":
    unittest.main()
