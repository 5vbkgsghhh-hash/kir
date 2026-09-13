"""The corpus's largest refusal reason did not name WHAT is missing.

MEASUREMENT OF 10.08.2026, `tools/coverage_matrix.py` over 67 decompiles
on disk (a machine-local corpus, 4.1 GB). The reasons map ranks them by
the number of AFFECTED DOCUMENTS, and the top line reads:

    10 documents out of 10, 77 733 elements
    "category is outside the exact Part 5 lifter table"

This is not only the corpus's most massive reason — it is the ONLY
reason that touches ALL documents. And it cannot be acted upon: it does
not say which category. Seventy-seven thousand elements of ten buildings
are folded into one opaque line, and the decision made from it is what
to build next.

Breaking it down by category is exactly that ranking. A category is a
CLASS, not an instance, so the folding of variable data in
`coverage_matrix` (the one that collapses edge indices and parent ids so
one reason does not scatter into a row per element) deliberately does
not touch it: a category name is not put in quotes and does not contain
stand-alone numbers.

The price of this silence has already been paid twice in this very file
and is recorded in `lift.py`: the same population stood in the reasons
map TWICE under different names (28 926 "outside the … lifter table" and
8 207 "absent from the family placement side index"), and, quoting that
comment, "a duplicate in it costs more than any percentage of coverage."
Here the same class is an order of magnitude larger.
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kir.decompile.lift import AtomReason, lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata,
)

#: A category knowingly outside the lifters table — the test's question
#: is not about the category but about whether the refusal NAMES it.
_UNSUPPORTED = "OST_RasterImages"


def _document(elements: list[dict[str, Any]]) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "synthetic-no-lifter-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


class NoLifterNamesTheCategory(unittest.TestCase):

    def test_the_atom_says_which_category_has_no_lifter(self):
        row = make_element(_UNSUPPORTED, 9001, ordinal=0)
        result = lift_document_detailed(_document([row]))

        node = result.nodes[0]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(len(result.diagnostics), 1)
        diag = result.diagnostics[0]
        self.assertIs(diag.reason, AtomReason.NO_LIFTER)
        # The old wording stays — three other tests and comments in
        # lift.py search for it and refer to it; what is added is the
        # MISSING part.
        self.assertIn("outside the exact Part 5 lifter table", diag.detail)
        self.assertIn(_UNSUPPORTED, diag.detail)
        self.assertEqual(node["reason"]["detail"], diag.detail)

    def test_two_unsupported_categories_are_two_causes_not_one(self):
        """The ranking must tell them apart: these are two DIFFERENT
        rows of the categories table and two different pieces of work,
        not one big one."""
        rows = [make_element(_UNSUPPORTED, 9002, ordinal=0),
                make_element("OST_MEPSpaces", 9003, ordinal=1)]
        result = lift_document_detailed(_document(rows))

        details = {d.detail for d in result.diagnostics}
        self.assertEqual(len(details), 2, details)


if __name__ == "__main__":
    unittest.main()
