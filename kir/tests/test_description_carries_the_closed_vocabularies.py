"""THE LANGUAGE'S DESCRIPTION CARRIES VALUES, NOT JUST OPERATION NAMES.

THE MEASUREMENT THAT PAID FOR THIS (an overnight rig, 16.08.2026). The
owner asked why the agent builds primitive buildings. The answer turned
out to be about neither the model nor the language:

* **95 files out of 221**, written by the subject over 16 attempts across
  three nights, build nothing at all — they are RECONNAISSANCE (`spec()`,
  `pools`, `query_*`). Forty-three percent of the work goes into finding
  out NAMES. At the "openings" stage — 16 scouts against 9 builds;
* in the description (27 548 characters) all **69 of 69 operations** are
  named, while the word `kind` — a required parameter of
  `query_count`/`query_list` — never appeared **even once**; of the 53
  kinds in the closed table, **one** was named by an individual word; of
  the 35 pools, **two**;
* the one and only channel to the values (`spec()`) is rationed: one
  lookup per script, the printout truncated at 4000 characters;
* the prod refusal corpus confirms it from the other side: `KIR-G001
  count.kind` is the top refusal by inability to teach, 16 repeats inside
  a SINGLE turn.

The language was presented BY NAME and never presented BY VALUE.

THE COST WAS MEASURED: 27 548 -> 30 330 characters, +2 782 (+10.1%) on a
description that travels with every turn. The trade-off is named: ten
percent of length against forty-three percent of the work going into
reconnaissance.

A FAIL CONTROL: removing the «ЗАКРЫТЫЕ СЛОВАРИ» block from
`build_tool_description` makes both of the first two tests go red; adding
a kind or a pool to the registry without touching the description makes
the same tests go red, because they check against THE REGISTRY, not
against a constant.
"""
from __future__ import annotations

import re
import unittest

from kir import spec
from kir.tool_doc import build_tool_description


def _as_word(text: str, word: str) -> bool:
    return bool(re.search(r"(?<![\w_])%s(?![\w_])" % re.escape(word), text))


class TheDescriptionCarriesTheClosedVocabularies(unittest.TestCase):

    def setUp(self):
        self.doc = build_tool_description()

    def test_every_kind_of_the_closed_table_is_named(self):
        missing = [k for k in sorted(spec.KINDS) if not _as_word(self.doc, k)]
        self.assertEqual([], missing,
                         "вид есть в реестре и не назван в описании: модель "
                         "обязана его угадать")

    def test_pools_are_pointed_at_rather_than_enumerated_and_that_is_a_decision(self):
        """Pools are NOT enumerated, and that is a decision, not an
        oversight.

        🔴 WHY NOT BOTH DICTIONARIES IN FULL. Neither fits together: the
        ratchet `test_tool_doc::test_description_stays_small_next_to_the_schema`
        holds at 30 000 characters, and together the two dictionaries come
        to 30 330. This ratchet's history is about exactly our case: on
        15.08 the ceiling was breached by accumulation, and the first move
        the director made was to RAISE it "with payback arithmetic" — and
        that was recognized as the wrong move, because the ceiling is paid
        for on EVERY call. The right move there was reallocation, and that
        is exactly what is done here.

        Why kinds were chosen and not pools: `kind` had NOTHING — no field
        name, no dictionary (measured: 0 occurrences of the word, 1 name
        out of 53), and without that you can't even ask the question. For
        a pool, the fix path is short and was already built that same
        evening: a wrong name returns the NEAREST match (`_pool_hint`),
        and the full list is given by `spec("query_types")`.

        This is exactly what the test pins: a pointer exists, an
        enumeration does not.
        """
        pools = sorted(spec.OPS["query_types"].params[0].choices)
        named = [p for p in pools if _as_word(self.doc, p)]
        self.assertLessEqual(len(named), 3,
                             "пулы снова перечислены целиком — это пробьёт "
                             "ратчет длины, см. докстроку")
        self.assertIn('spec("query_types")', self.doc,
                      "перечня нет и указателя нет — модель обязана угадать")

    def test_the_two_dictionaries_are_told_apart(self):
        """A kind and a pool are different dictionaries, and that is said
        in words.

        Measured: `pool='walls'` (a kind in place of a pool) is the fourth
        most expensive refusal in the corpus. Naming both dictionaries
        without saying how they differ would mean pushing the distinction
        back onto the model once again.
        """
        self.assertIn("НЕ равны видам", self.doc)

    def test_the_field_name_itself_appears(self):
        # Zero occurrences of the word `kind` — that is where this entire
        # finding began.
        self.assertTrue(_as_word(self.doc, "kind"))


if __name__ == "__main__":
    unittest.main()
