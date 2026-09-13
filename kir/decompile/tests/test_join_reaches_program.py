"""A JOIN MUST REACH THE PROGRAM — OR NAME WHY IT DID NOT.

🔴 THE OCCASION WAS FOUND BY THE OWNER'S EYE, NOT AN INSTRUMENT (23.08.2026).
The MNVNK K3 building, transferred into a foreign document, looked like "a
Frankenstein whose walls bulge outward": 6 015 walls built and NOT A SINGLE
join. In Revit, joined walls trim each other, unjoined ones stand at their
full axial length.

No instrument had seen this: the `create_wall` witness does not ask about
joins, neither does `verify.json`. `lift_joins` was lifting 1 758
operations, while `leaves_to_program` had no `joins` parameter at all —
lifted, and never arrived.

What is guarded here are THREE LAWS, not three numbers: a join travels in
ONE program with both arms (D5a), AFTER both of them (D5d), or drops out as
a TYPED remainder. The live building's numbers are in `_join_leaves`'s
docstring; they are deliberately absent here: a test that checks a number
goes red on every new decompile.
"""
from __future__ import annotations

import unittest

from kir.decompile.materialize import (
    MaterializeResult, leaves_to_program,
)


def _wall(source_id: str) -> dict:
    return {
        "kind": "op", "_id": "L" + source_id, "source_element_id": source_id,
        "op_name": "create_wall",
        "params": {
            "p0_mm": [0.0, 0.0], "p1_mm": [1000.0, 0.0],
            "height_mm": 3000.0,
            "level": {"by": "name", "value": "L1", "_id": "42"},
        },
    }


def _stairs(source_id: str) -> dict:
    """A solo op: it must travel alone (KIR-L002), i.e. OUTSIDE the main
    program."""
    return {
        "kind": "op", "_id": "L" + source_id, "source_element_id": source_id,
        "op_name": "create_stairs",
        "params": {
            "base_level": {"by": "name", "value": "L1", "_id": "42"},
            "top_level": {"by": "name", "value": "L2", "_id": "43"},
            "runs": [{"kind": "straight", "start_mm": [0.0, 0.0],
                      "end_mm": [3000.0, 0.0], "width_mm": 1200.0}],
        },
    }


class _Joins:
    """The minimal carrier of the `JoinLift` shape that the materializer
    reads."""

    def __init__(self, pairs):
        self.ops = tuple(
            {
                "op_name": "join_elements",
                "params": {"first": {"ref": "L" + a},
                           "second": {"ref": "L" + b}},
                "sources": (a, b),
            }
            for a, b in pairs
        )


def _join_ops(result: MaterializeResult) -> list[tuple[int, dict]]:
    return [(index, op)
            for index, program in enumerate(result.programs)
            for op in program["ops"] if op["op"] == "join_elements"]


class JoinReachesProgram(unittest.TestCase):

    def test_join_travels_with_both_arms_in_one_program(self):
        """D5a: both arms and the join — in ONE program."""
        leaves = [_wall("100"), _wall("200")]
        result = leaves_to_program(
            leaves, joins=_Joins([("100", "200")]), chunk_target=250)
        joins = _join_ops(result)
        self.assertEqual(len(joins), 1, "соединение не доехало до программы")
        program_index, join = joins[0]
        ids = {op["id"] for op in result.programs[program_index]["ops"]}
        for side in ("first", "second"):
            selector = join[side]
            self.assertEqual(selector["by"], "ref")
            self.assertIn(
                selector["value"], ids,
                "плечо оказалось за границей программы: ссылка `ref` её не "
                "переживёт, компилятор откажет чанку (KIR-L003)")

    def test_join_stands_after_both_arms(self):
        """D5d: a reference must name an EARLIER op."""
        leaves = [_wall("100"), _wall("200")]
        result = leaves_to_program(
            leaves, joins=_Joins([("100", "200")]), chunk_target=250)
        program_index, join = _join_ops(result)[0]
        order = {op["id"]: index for index, op
                 in enumerate(result.programs[program_index]["ops"])}
        for side in ("first", "second"):
            self.assertLess(
                order[join[side]["value"]], order[join["id"]],
                "плечо стоит ПОСЛЕ соединения")

    def test_arm_that_stayed_an_atom_drops_the_join_typed(self):
        """An atom-arm takes the join down with it as a REMAINDER, not as a
        dangling reference."""
        atom = {
            "kind": "atom", "_id": "L200", "source_element_id": "200",
            "category": "OST_Walls",
            "reason": {"code": "missing_geometry", "detail": "нет кривой"},
        }
        result = leaves_to_program(
            leaves := [_wall("100"), atom], joins=_Joins([("100", "200")]))
        self.assertEqual(_join_ops(result), [],
                         "соединение уехало с висячей ссылкой")
        self.assertEqual(result.stats.joins_materialized, 0)
        self.assertEqual(result.stats.joins_dropped, 1)
        self.assertTrue(
            any(skip.category == "join_elements" and skip.reason
                for skip in result.skipped),
            "снятое соединение обязано быть ВИДНО типизированным остатком")
        del leaves

    def test_arm_outside_the_body_stream_drops_the_join_typed(self):
        """🔴 A SOLO arm: it materializes, but in its own program.

        Measurement of 23.08 on K3: exactly 3 of 1 758 joins run into this,
        and all three into one `create_floor` arm, recognized as
        version-fragile. Pulling it back in is not an option (a solo damps
        the blast radius), and neither is letting the join through with a
        dangling reference.
        """
        result = leaves_to_program(
            [_wall("100"), _stairs("200")], joins=_Joins([("100", "200")]))
        self.assertEqual(_join_ops(result), [])
        self.assertEqual(result.stats.joins_dropped, 1)
        self.assertTrue(
            any(skip.reason.startswith("join_arm_isolated:")
                for skip in result.skipped),
            "причина обязана отличаться от «не материализовался хозяин»: "
            "плечо материализовалось, оно просто в другой программе")

    def test_without_joins_the_run_is_byte_identical(self):
        """Without `joins=`, the number and shape of the programs are the
        same, VERBATIM."""
        leaves = [_wall("100"), _wall("200")]
        self.assertEqual(
            leaves_to_program(leaves).programs,
            leaves_to_program(leaves, joins=None).programs)


if __name__ == "__main__":
    unittest.main()
