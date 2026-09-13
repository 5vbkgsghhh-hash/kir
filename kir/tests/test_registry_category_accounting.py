"""Every writing op MUST be named by exactly one mechanism.

THE REASON IS NOT A HYPOTHESIS BUT A RE-MEASUREMENT ON 2026-08-11. The
paragraph in `spec.py` above `OP_RESULT_CATEGORIES` explained "unfilled"
ops by three mechanisms and a sum of 43 + 10 + 4 + 7 = 64. On the day of
the re-measurement, the registry held 65 writing ops, the table had 44
rows, and the resolver accounted for 6 — and, most importantly, there
turned out to be FIVE mechanisms: `create_group` was named by neither the
table, nor the resolver, nor either of the two acceptance ledgers. It is
named by a FIFTH way that the paragraph never mentioned at all: Revit
carries the group wrapper as its own bookkeeping
(`acceptance._OP_DERIVED`), and the expectation is built from the group's
MEMBERS.

The old sum balanced not because it was correct but because the addends and
the total were taken on the same day. A TEST must hold this kind of
arithmetic: the paragraph explains WHY, the test answers HOW MANY.

WHAT THIS TEST DOES NOT DO, AND WHY. It does NOT require every op to have a
row in the table. Filling in a category that the census does not observe
is an IRREVERSIBLE mistake: acceptance then waits for an increment in a
cell nobody watches, and an HONEST build gets `category_shortfall`.
Blindness is reversible: only the upper bound is lost. That is why the
test demands NAMEDNESS, not completeness.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_accounting_queue.jsonl"))

from kir import acceptance, spec  # noqa: E402

#: Variety probes: for six ops the category is decided by its OWN closed
#: enumeration, and the resolver answers only from a filled-in field.
_VARIETY_PROBES = (
    {}, {"variety": "wall_rect"}, {"variety": "host_face"},
    {"variety": "isolated"}, {"variety": "slab"},
    {"variety": "surface"}, {"variety": "toposolid"},
    {"category": "structural"}, {"category": "generic_model"},
)


def _writing_ops():
    return {name for name, op in spec.OPS.items()
            if op.family in spec.WRITE_FAMILIES}


def _resolver_answers(name):
    """Whether the resolver answers for an op that has no row in the table."""
    for probe in _VARIETY_PROBES:
        op = dict(probe)
        op["op"] = name
        try:
            if spec.op_result_categories(op):
                return True
        except Exception:
            continue
    return False


def _buckets():
    writing = _writing_ops()
    table = set(spec.OP_RESULT_CATEGORIES) & writing
    blind = set(acceptance._OPS_BLIND) & writing
    no_elements = set(acceptance._OPS_WITHOUT_ELEMENTS) & writing
    resolver = {n for n in writing - table if _resolver_answers(n)}
    derived_only = {
        n for n in writing - table - blind - no_elements - resolver
        if acceptance._OP_DERIVED.get(n)}
    return writing, table, resolver, blind, no_elements, derived_only


class EveryWritingOpIsNamed(unittest.TestCase):

    def test_no_writing_op_is_unaccounted(self):
        """An op that NO mechanism named is silent blindness: acceptance
        builds for it neither an expectation row nor a record saying there
        is nothing to look at. From the outside this is indistinguishable
        from "checked and it matched."""
        writing, table, resolver, blind, no_elements, derived = _buckets()
        unaccounted = writing - table - resolver - blind - no_elements - derived
        self.assertEqual(
            unaccounted, set(),
            "пишущие опы, которых не назвал ни один механизм: %s — добавь "
            "строку в spec.OP_RESULT_CATEGORIES ТОЛЬКО если категория "
            "ЗАМЕРЕНА, иначе назови слепым в acceptance._OPS_BLIND с "
            "причиной словами" % sorted(unaccounted))

    def test_the_table_never_contradicts_the_blind_ledger(self):
        """An op cannot both have a census cell and be declared invisible
        to the census — these are two answers to one question."""
        _w, table, _r, blind, _n, _d = _buckets()
        self.assertEqual(
            table & blind, set(),
            "оп и в таблице категорий, и в журнале слепых: %s"
            % sorted(table & blind))

    def test_the_table_holds_only_writing_ops(self):
        """A row for a reading op would promise an increment from an
        operation that creates nothing."""
        extra = set(spec.OP_RESULT_CATEGORIES) - _writing_ops()
        self.assertEqual(extra, set(),
                         "не-пишущие опы в таблице категорий: %s"
                         % sorted(extra))

    def test_the_arithmetic_in_the_spec_comment_still_holds(self):
        """THE NUMBERS FROM THE PARAGRAPH ABOVE THE TABLE. The test
        deliberately fails when an op is added: the earlier version of the
        paragraph had drifted from the tree silently, and the cost of that
        is a reader who trusts a sum that has not balanced for a month.
        Failing here means "update the paragraph in spec.py," not "fix the
        code."""
        writing, table, resolver, blind, no_elements, derived = _buckets()
        measured = {
            "writing": len(writing), "table": len(table),
            "resolver": len(resolver), "blind": len(blind),
            "no_elements": len(no_elements), "derived_only": len(derived),
        }
        self.assertEqual(
            measured,
            # 2026-08-18: 66 -> 67 writing, no_elements 4 -> 5.
            # `join_elements` is a RELATION op: it joins the geometry of two
            # already-standing elements and adds NONE to the census. It went
            # into mechanism 4 (`acceptance._OPS_WITHOUT_ELEMENTS`), not into
            # the category table: a row in the table would make acceptance
            # wait for an increment that will never come, and fail an
            # honest build.
            #
            # 2026-08-21: 67 -> 73 writing, resolver 6 -> 10, blind 11 -> 13.
            # The increment reconciles BY NAME — six ops from the 08-20 wave
            # plus `author_family`, minus `query_surface` (it reads). The
            # breakdown and the argument are in the paragraph above
            # `OP_RESULT_CATEGORIES` in spec.py; here there is only the
            # number, and it exists exactly so the paragraph cannot be left
            # stale silently.
            # 2026-08-24: 73 -> 77 writing, no_elements 5 -> 9. The whole
            # increment is in mechanism 4 and entirely named:
            # create_wall_type, transfer_family, create_floor_plan (08-23)
            # and transfer_material (08-24) — a catalog and a view, not
            # building elements.
            {"writing": 77, "table": 44, "resolver": 10, "blind": 13,
             "no_elements": 9, "derived_only": 1},
            "арифметика категорий сдвинулась — обнови абзац над "
            "OP_RESULT_CATEGORIES в spec.py и это число здесь")
        self.assertEqual(
            len(table) + len(resolver) + len(blind) + len(no_elements)
            + len(derived), len(writing))

    def test_the_two_named_gaps_stay_named_and_stay_out_of_the_table(self):
        """`create_curtain_grid_line` and `create_wall_foundation` are NOT
        a gap but a named blindness, and filling them in is forbidden: a
        filling mistake rejects an honest build, a blindness mistake loses
        the upper bound."""
        for name in ("create_curtain_grid_line", "create_wall_foundation"):
            with self.subTest(op=name):
                self.assertNotIn(name, spec.OP_RESULT_CATEGORIES)
                self.assertIn(name, acceptance._OPS_BLIND)
                self.assertTrue(acceptance._OPS_BLIND.reason(name).strip())

    def test_create_group_is_named_by_the_fifth_mechanism(self):
        """The fifth mechanism, which the earlier paragraph never named at
        all: Revit carries the group wrapper (`_OP_DERIVED`), and the
        expectation is built from the MEMBERS."""
        self.assertNotIn("create_group", spec.OP_RESULT_CATEGORIES)
        self.assertIsNone(spec.op_result_categories({"op": "create_group"}))
        self.assertNotIn("create_group", acceptance._OPS_BLIND)
        self.assertTrue(acceptance._OP_DERIVED.get("create_group"))


if __name__ == "__main__":
    unittest.main()