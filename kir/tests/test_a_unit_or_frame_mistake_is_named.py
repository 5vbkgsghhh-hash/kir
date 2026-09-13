"""A UNITS OR COORDINATE MISTAKE IS NAMED, NOT LET THROUGH (F1/C03).

WHAT WAS FOUND (2026-09-07). The scene limit of ±16 000 000 mm (`COORD_LIMIT_MM`,
"almost always a units mistake") guarded LITERALS only: a wall at 15,95 km
compiled, and the same program then shifted it with `move_elements` by +100 m —
16,05 km, a green compile. The literal at that point would have been refused as KIR-T002.
One law, bypassed by a second route; the target's FINAL position is now
counted from the order of ops (`geom.same_program_shift`).

WHAT IS MEASURED: the compile verdict and the refusal address (op_id/field), a control-PASS
on a shift TOWARD the coordinate origin and on a shift within the limit.
CONTROL-FAIL: replace `geom.same_program_shift` with zero — the first test goes red.

BOUNDARY (named): targets by `element_id` — the position is unknown to the compiler;
axis endpoints (RELATE) on the ground path — are not checked by this law after
a shift; a "3 mm wall" and a "0.9 mm door" pass the bounds — there is no threshold
for small values in the registry, and none was invented here (legitimate small
values outnumber mistakes).

Run:
    venv/bin/python -m pytest kir/tests/test_a_unit_or_frame_mistake_is_named.py -q
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program
from kir.registry_base import COORD_LIMIT_MM
from kir.tests.fixtures import GROUND_SNAPSHOT

LVL = {"by": "element_id", "value": 42}
NEAR = COORD_LIMIT_MM - 50_000          # 15 950 000: legitimate on its own


def _wall(x0=NEAR, oid="MW"):
    return {"op": "create_wall", "id": oid, "p0_mm": [x0, 0],
            "p1_mm": [x0 + 6000, 0], "level": LVL}


def _move(oid, target, delta):
    return {"op": "move_elements", "id": oid,
            "targets": [{"by": "ref", "value": target}], "delta_mm": list(delta)}


def _compile(ops):
    return compile_program({"ir_version": "1.0", "intent": "предел сцены",
                            "ops": ops}, "2026", snapshot=GROUND_SNAPSHOT)


class AMoveBeyondTheSceneIsNamed(unittest.TestCase):

    def test_the_literal_beyond_the_limit_is_already_refused(self):
        """Control: the law for the literal exists (KIR-T002)."""
        out = _compile([_wall(COORD_LIMIT_MM + 100_000)])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", {d.code for d in out.diagnostics})

    def test_a_move_that_pushes_the_wall_beyond_the_limit_is_refused(self):
        out = _compile([_wall(), _move("ME1", "MW", (100_000, 0, 0))])
        self.assertFalse(out.ok, "15,95 км + 100 м = 16,05 км прошло молча")
        hits = [d for d in out.diagnostics if d.code == "KIR-T002"]
        self.assertEqual([(d.op_id, d.field_name) for d in hits], [("ME1", "targets[0]")],
                         [d.as_dict() for d in out.diagnostics])
        # p0 = 15 950 000 + 100 000 = 16 050 000 — p0 is the first to cross the limit.
        self.assertEqual(hits[0].got, {"target": "MW", "param": "p0_mm",
                                       "coordinate_mm": 16_050_000.0})

    def test_two_moves_accumulate_and_the_crossing_move_is_named(self):
        out = _compile([_wall(), _move("ME1", "MW", (30_000, 0, 0)),
                        _move("ME2", "MW", (30_000, 0, 0))])
        self.assertFalse(out.ok)
        hits = [(d.op_id, d.field_name) for d in out.diagnostics if d.code == "KIR-T002"]
        self.assertEqual(hits, [("ME2", "targets[0]")], hits)

    def test_a_move_toward_the_origin_stays_legal(self):
        out = _compile([_wall(), _move("ME1", "MW", (-100_000, 0, 0))])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_a_move_inside_the_limit_stays_legal(self):
        out = _compile([_wall(), _move("ME1", "MW", (40_000, 0, 0))])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_a_move_of_another_wall_does_not_taint_the_near_one(self):
        out = _compile([_wall(), _wall(0, "W2"), _move("ME1", "W2", (100_000, 0, 0))])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])


if __name__ == "__main__":
    unittest.main()
