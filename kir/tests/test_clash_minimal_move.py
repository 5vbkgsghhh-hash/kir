"""THE MODEL GETS THE MINIMAL MOVE, NOT THE DETECTOR'S RAW VECTOR.

WHAT WAS MEASURED BEFORE THE FIX (17.08.2026). `clash/resolve.py` provably
computes the SMALLEST clearance and knows about THIRD bodies, but its only
consumer outside the package was `viewer/advice.py` — i.e. the HUMAN panel.
The model, which drives the program itself, was getting the detector's raw
displacement. The difference was measured on 600 real findings from
`sob62_r23_v5` (`resolve.py:32-38`): median **5.892x**, p90 56.667x, maximum
**112 066.5x**.

THE COST WAS MEASURED BEFORE THE FIX, AND IT DISPROVED THE FIRST EDIT. The
threshold of "count three findings" turned out to be a hope, not a ceiling:
`propose` on the three deepest overlaps gave

    sob62_r23_v5      1 326 bodies  ->     5.9 ms for three
    snowdon_plumb_v3  6 381 bodies -> 1 329.9 ms for three

Cost grows not with the number of findings but with NEIGHBORHOOD DENSITY. The
only possible ceiling is TIME, and it is supplied by the caller.

Run:
    venv/bin/python -m pytest kir/tests/test_clash_minimal_move.py -q
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from kir.clash import hulls as H
from kir import clash_judgement as J
from kir.tests.test_clash_judgement import DUCT, PIPE, finding


def _record(side: dict, *, x0: float, x1: float, y: float) -> H.HullRecord:
    """The hull is exactly the shape the prod builds (`hull_from_wall_axis`)."""
    prism = H.hull_from_wall_axis((x0, y, 0.0), (x1, y, 0.0),
                                  width_mm=200.0, z0=0.0, z1=200.0)
    return H.HullRecord(
        source_id=side["source_element_id"], category=side["category"],
        label=side["label"], mvp_side="mep", hull=prism,
        grade="conservative", hull_source="axis_section",
        section_radius_mm=100.0, extra={})


def _pair() -> tuple[dict, dict]:
    hulls = {
        PIPE["source_element_id"]: _record(PIPE, x0=0, x1=3000, y=0),
        DUCT["source_element_id"]: _record(DUCT, x0=1000, x1=4000, y=50),
    }
    return finding(PIPE, DUCT, depth=80.0), hulls


class TheMoveIsMinimal(unittest.TestCase):

    def test_default_changes_nothing(self):
        """Default = the PREVIOUS behavior. The unknown must not improve silently."""
        f, hulls = _pair()
        before = J.judge([f], hulls=hulls)
        self.assertEqual(before.proposals, {},
                         "пустой словарь = второй проход НЕ запускали; это не "
                         "то же самое, что «посчитали ноль»")
        self.assertTrue(all(j.move_source == "detector" for j in before.judged))

    def test_on_look_the_move_is_NOT_named_and_the_reason_is(self):
        """🔴 THE MAIN TEST OF THIS FILE, AND IT WAS PAID FOR BY A LIVE DEFECT ON 17.08.2026.

        The first edition of `_upgrade_moves` filtered only by `rule_id` and
        never asked the rung. At `rung=look, proven=False` it replaced the
        honest "go get the missing evidence" with "move the pipe by −Y
        150 mm — the move is clear" — exactly the destructive instruction
        that the rung's definition FORBIDS. The code had already shipped to prod.
        """
        f, hulls = _pair()
        base = J.judge([f], hulls=hulls)
        gated = J.judge([f], hulls=hulls, propose_budget_ms=500.0)
        self.assertEqual(gated.judged[0].rung, "look", "фикстура не та")
        self.assertEqual(gated.judged[0].next_move_ru,
                         base.judged[0].next_move_ru,
                         "на `look` ход обязан остаться БАЙТ В БАЙТ прежним")
        self.assertEqual(gated.judged[0].move_source, "detector")
        self.assertEqual(gated.proposals.get("skipped_rung", 0), 1,
                         "«ступень не позволяет» обязано быть НАЗВАНО, а не "
                         "выглядеть как «нечего считать»")

    def test_the_permitted_rung_is_asked_of_the_ladder_not_remembered(self):
        """Permission is asked of the AUTHORITY — the `RUNGS` table.

        The prohibition lives in the action text of the `look` rung; if
        someone removes it from there, the decision must be made EXPLICITLY,
        not inherited silently.
        """
        self.assertNotIn("look", J._RUNGS_ALLOWING_A_NAMED_MOVE)
        self.assertLessEqual(J._RUNGS_ALLOWING_A_NAMED_MOVE,
                             {key for key, _, _ in J.RUNGS})
        look_action = dict((k, a) for k, _, a in J.RUNGS)["look"]
        self.assertIn("ЗАПРЕЩЕНО", look_action,
                      "ступень перестала запрещать разрушающее указание — "
                      "это решение о продукте, прими его явно")

    def test_the_upgrade_still_works_where_it_is_legal(self):
        """The gate did not kill the capability: on an allowed rung, the move is computed.

        🔴 THE LINE IS BUILT DIRECTLY, AND THIS IS A NAMED BOUNDARY. `fix`
        CANNOT be obtained from a real finding via a fixture: `_rung`
        requires `proven is True`, which in turn requires a sealed chain of
        detector certificates whose forgery the module deliberately rejects.
        That is why only the UNIT (`_upgrade_moves`) is tested here, not the
        whole path; the path to `fix` is entirely unreachable in prod today
        (canon: prod never releases `verdict=confirmed`).
        """
        f, hulls = _pair()
        row = J.judge([f], hulls=hulls).judged[0]
        import dataclasses
        allowed = dataclasses.replace(row, rung="fix")
        out, counts = J._upgrade_moves([allowed], {row.finding_id: f}, hulls,
                                       budget_ms=500.0)
        self.assertEqual(counts["computed"], 1, counts)
        self.assertEqual(out[0].move_source, "minimal_exit")
        self.assertNotEqual(out[0].next_move_ru, row.next_move_ru)

    def test_an_exhausted_budget_is_counted_never_silent(self):
        f, hulls = _pair()
        row = J.judge([f], hulls=hulls).judged[0]
        import dataclasses
        allowed = dataclasses.replace(row, rung="fix")
        _out, counts = J._upgrade_moves([allowed], {row.finding_id: f}, hulls,
                                        budget_ms=1e-9)
        self.assertEqual(counts["skipped_budget"], 1, counts)

    def test_a_missing_hull_is_a_named_refusal_not_a_blank_move(self):
        f, hulls = _pair()
        row = J.judge([f], hulls=hulls).judged[0]
        import dataclasses
        allowed = dataclasses.replace(row, rung="fix")
        hulls.pop(DUCT["source_element_id"])
        out, counts = J._upgrade_moves([allowed], {row.finding_id: f}, hulls,
                                       budget_ms=500.0)
        self.assertEqual(counts["refused"], 1, counts)
        self.assertEqual(out[0].next_move_ru, row.next_move_ru)

    def test_the_vector_rule_list_is_complete_by_construction(self):
        """`_VECTOR_MOVE_RULES` is derived from the SINGLE branch of `_next_move`
        that emits a vector — not enumerated from memory.

        What is asked is the DEFINITION, not a naming convention: if a second
        such branch appears, this test will turn red, and the decision will
        have to be made.
        """
        src = pathlib.Path(J.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "_next_move":
                continue
            for branch in ast.walk(node):
                if not isinstance(branch, ast.If):
                    continue
                body = ast.dump(branch)
                if "'vector'" not in body and '"vector"' not in body:
                    continue
                for cmp_node in ast.walk(branch.test):
                    if isinstance(cmp_node, ast.Tuple):
                        found |= {e.value for e in cmp_node.elts
                                  if isinstance(e, ast.Constant)
                                  and isinstance(e.value, str)}
        self.assertTrue(found, "ветка с вектором не найдена — разбор промахнулся")
        self.assertEqual(found, set(J._VECTOR_MOVE_RULES), found)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
