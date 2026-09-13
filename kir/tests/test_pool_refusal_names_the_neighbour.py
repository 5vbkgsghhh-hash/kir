"""THE REFUSAL FOR `query_types.pool` NAMES A NEIGHBOR, NOT THIRTY-FIVE NAMES.

THE MEASUREMENT THAT BOUGHT THIS (overnight bench 16.08.2026, prod corpus
`data/telemetry/kir_rejections.jsonl`, 1959 lines, 295 in overnight
windows):

* `KIR-T003 query_types.pool` — **24 refusals, 11 repeats within a single
  turn**, the fourth most expensive class;
* the text printed ALL 35 pool names — **691 characters** — and not a word
  about the next turn; on the prod copy it is exactly the same, so this is
  not a regression but a hole;
* and most importantly — **the director's hypothesis that "the refusal that
  ENUMERATES teaches" was REFUTED by the same measurement**: enumerating
  refusals repeat in 51.4% of turns versus 29.5% for those naming only the
  kind. A long closed list does not teach: the model knows WHAT it needs
  and cannot match its intent to the dictionary.

Hence the ladder, word for word the same as `_kind_hint` uses for kinds:
first the NEIGHBOR, and only on a complete miss — the whole list (then the
choice is not between a list and a pointer, but between a list and
SILENCE).

This also closes the mirror: `_kind_hint` could say «это ПУЛ ТИПОВ, а не
вид», but the reverse branch did not exist — someone asking `pool='walls'`
got the whole sheet. The pair must exist in both directions.

FAIL CONTROL was taken on an untouched prod copy of
`/opt/kukai-rebuild1/backend` (16.08.2026), without mutating the shared
tree: there, `pool='walls'` gives the 691-character list, «Ближайшие» and
«СЛЕДУЮЩИЙ ХОД» are absent — meaning every test in this file, except for
the legitimate pool, goes red there.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.compiler import plan_program
from kir.diag import KirRefusal

POOLS = sorted(spec.OPS["query_types"].params[0].choices)


def _refusal(pool) -> str:
    op = {"op": "query_types", "id": "q1"}
    if pool is not None:
        op["pool"] = pool
    try:
        plan_program({"ir_version": "1.0", "ops": [op]})
    except KirRefusal as exc:
        return " ".join(
            str(getattr(item, "message_ru", "") or item)
            for item in exc.diagnostics)
    return ""


class PoolRefusalNamesTheNeighbour(unittest.TestCase):

    def test_a_kind_asked_as_a_pool_is_told_the_pool_is_named_otherwise(self):
        # Exactly what the overnight subject wrote.
        text = _refusal("walls")
        self.assertIn("вид элемента", text)
        self.assertIn("wall_types", text)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", text)
        # Neighbors instead of the whole sheet: the refusal's length must be
        # noticeably shorter than the full list, otherwise the ladder did
        # not work.
        self.assertLess(len(text), len(", ".join(POOLS)))

    def test_a_near_miss_gets_its_neighbour(self):
        text = _refusal("level")
        self.assertIn("levels", text)
        self.assertIn("Ближайшие", text)
        self.assertLess(len(text), len(", ".join(POOLS)))

    def test_a_total_miss_still_gets_the_whole_closed_list_and_a_move(self):
        # On a complete miss, silence is worse than the whole sheet: the
        # model cannot know whether the name it needs is hiding behind the
        # ellipsis.
        text = _refusal("xyzzy")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", text)
        for name in POOLS:
            self.assertIn(name, text)

    def test_absent_field_says_so_rather_than_calling_it_unknown(self):
        text = _refusal(None)
        self.assertIn("не написано", text)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", text)

    def test_a_legal_pool_is_never_refused(self):
        # Control in the other direction: the ladder has no right to refuse
        # a legitimate name — otherwise "got better" would have been bought
        # with a regression.
        for name in POOLS:
            self.assertEqual("", _refusal(name), name)


if __name__ == "__main__":
    unittest.main()
