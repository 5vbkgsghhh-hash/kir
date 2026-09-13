"""THE MISSION'S MAIN METRIC WAS NOT BEING COUNTED IN PROD — THERE WAS NOTHING TO LINK ATTEMPTS WITH.

The constitution names as the main metric "how many times checkability changed the
model's decision". An event for it is counted like this: the previous turn was refused AND
the next program DIFFERS. So two things are needed — a fingerprint of the program and
attribution to a turn.

Measurement on 23.08.2026 from live logs:
    kir_author_refusals.jsonl   46 rows, turn_id and query_id — null for ALL of them
    kir_course_uptake.jsonl     49 rows, the same
    only source_digest was populated

At the same time, `record_course_uptake` and `record_author_refusal` had accepted turn_id and
query_id FROM THE VERY START, and both doors (`handle_revit_ir`,
`handle_revit_ir_bulk`) hold these values and pass them into FIVE other places.
They just weren't being passed here. The generic class of this tree: a value is DECLARED in
one place and NOT READ in another.

The cost: the metric was only ever counted on the test bench (`author_loop_baseline`) and never
on live turns.
"""
import inspect
import unittest

from kir import serving


class BothDoorsHandTheTurnDown(unittest.TestCase):
    def test_authored_input_accepts_the_turn(self):
        p = inspect.signature(serving._authored_input).parameters
        self.assertIn("turn_id", p)
        self.assertIn("query_id", p)

    def test_the_refusal_result_accepts_the_turn(self):
        p = inspect.signature(serving._script_refusal_result).parameters
        self.assertIn("turn_id", p)
        self.assertIn("query_id", p)

    def test_both_doors_actually_pass_it(self):
        """A signature without a call is half the defect. We look at the SOURCE of the door."""
        src = inspect.getsource(serving)
        i = src.index("authored = await _authored_input(")
        хвост = src[i:i + 260]
        self.assertIn("turn_id=turn_id", хвост,
                      "дверь держит ход и не передаёт его автору")
        self.assertIn("query_id=query_id", хвост)
        # both doors, not just one: the second is internal, the same prod path
        self.assertEqual(src.count("authored = await _authored_input("), 2)
        j = src.index("authored = await _authored_input(", i + 1)
        self.assertIn("turn_id=turn_id", src[j:j + 260],
                      "вторая дверь ход теряет")

    def test_the_sinks_receive_it(self):
        src = inspect.getsource(serving)
        for сток in ("record_course_uptake(", "record_author_refusal("):
            i = src.index(сток)
            self.assertIn("turn_id=turn_id", src[i:i + 400],
                          f"{сток} зовётся без хода — строки снова придут null")


if __name__ == "__main__":
    unittest.main()
