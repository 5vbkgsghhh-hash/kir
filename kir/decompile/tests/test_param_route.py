"""THE PROBE ROUTE: cut off by SCHEMA, not by data, and fail loudly.

WHY, MEASURED 20.08.2026. A live A/B (three categories, two hands, two
runs each) showed: probing costs 45-64% of the extraction body AFTER
the type lift, and `OST_Dimensions` pays the most of all — 64% for ZERO
values. The flat list asks every element for all 43 names.

🔴 WHAT THE TABLE IS NOT. It is NOT built on "did the parameter land" —
that is a fact about the project's DATA, and cutting on it would lose
the value in the very first document where it exists. It is built on
`not_applicable == total`: the parameter is absent BOTH ON THE INSTANCE
AND ON THE TYPE — a fact about the element's SCHEMA.

The predicate is conservative BY CONSTRUCTION: one element that does
have the schema blocks cutting the name for the whole category.

THE SAFEGUARD WITHOUT WHICH THE TABLE WOULD BE A GUESS: a cut name is
still asked of every `AUDIT_EVERY`-th element, and a hit is a LOUD
refusal, not a silent correction. A table that has drifted from the
model must be FOUND.
"""
from __future__ import annotations

import re
import unittest

from kir.decompile import param_route as R
from kir.decompile.extract import (
    _parse_route_skips, build_category_batch_cs)
from kir.decompile.schema import RouteSkip


def _hashset(body: str) -> set[str]:
    """What exactly the body cuts — read from ITS OWN text, not from
    the table."""
    m = re.search(r"new HashSet<string>\(new string\[\] \{(.*?)\}\)", body)
    if not m or not m.group(1).strip():
        return set()
    return set(re.findall(r'"([A-Z0-9_]+)"', m.group(1)))


class ТаблицаОтвечаетТолькоТам_ГДЕ_ЕСТЬ_УЛИКА(unittest.TestCase):

    def test_an_unknown_category_skips_nothing(self):
        """No evidence — ask EVERYTHING. This is the only safe default
        answer: cutting on an empty sample would mean deriving
        something from an absence."""
        self.assertEqual(R.route_skip("OST_НЕТ_ТАКОЙ_КАТЕГОРИИ"), frozenset())

    def test_the_table_carries_its_provenance(self):
        """A table without provenance is a claim, not a measurement."""
        for key in ("tree", "runs", "elements", "min_sample",
                    "names_under_receipt", "share_of_probes_skipped"):
            self.assertIn(key, R.PROVENANCE)
        self.assertGreater(R.PROVENANCE["elements"], 0)
        self.assertLess(R.PROVENANCE["names_under_receipt"],
                        R.PROVENANCE["names_total"],
                        "улика покрыла все имена — провенанс пора пересчитать")

    def test_the_audit_rate_is_a_named_decision(self):
        self.assertGreater(R.AUDIT_EVERY, 1)
        self.assertLessEqual(R.AUDIT_EVERY, 1024)


class ТелоОтсекаетРОВНО_ТО_ЧТО_ТАБЛИЦА(unittest.TestCase):
    """We ask the GENERATED BODY, not the table: it is exactly these
    two that can drift apart."""

    def test_a_routed_category_carries_its_names(self):
        body = build_category_batch_cs("OST_Dimensions")
        self.assertEqual(_hashset(body), set(R.route_skip("OST_Dimensions")))
        self.assertTrue(_hashset(body), "у самой дорогой категории маршрут пуст")

    def test_a_category_without_evidence_emits_an_EMPTY_route(self):
        """A disabled route must be the previous behavior.

        An empty set and a branch that is never taken are not "almost
        like before," they are exactly like before.
        """
        body = build_category_batch_cs("OST_Roofs")
        route = R.route_skip("OST_Roofs")
        self.assertEqual(_hashset(body), set(route))

    def test_every_probe_call_is_still_emitted(self):
        """🔴 PROBES ARE NOT CUT OUT OF THE BODY, AND THIS IS
        LOAD-BEARING.

        The decision is made in the helper BY NAME, not by cutting out
        lines: the canon carries the named case `_wrap_create_per_op`,
        where substituting already-generated C# silently preserved
        someone else's semantics. On top of that, cutting them out
        would make the safeguard impossible — there would be nothing
        left to probe a sampled element with.
        """
        body = build_category_batch_cs("OST_Dimensions")
        calls = re.findall(
            r"__PutSection\w*Param\(__e, __typeEl, BuiltInParameter\.", body)
        self.assertEqual(len(calls), 43)

    def test_the_builder_actually_asks_the_route(self):
        """THE LAST LINK: assembly must call `_route_cs`."""
        from kir.decompile import extract as E
        self.assertIn("_route_cs", E.build_category_batch_cs.__code__.co_names)


class РазборСтрокМаршрута(unittest.TestCase):

    def test_absent_key_is_not_an_error(self):
        """The old bridge does not send the key, and this is not a broken protocol."""
        self.assertEqual(_parse_route_skips(None, interrogated=5), ())

    def test_a_row_must_account_for_every_element_of_the_page(self):
        with self.assertRaises(Exception) as caught:
            _parse_route_skips([{"parameter": "A", "skipped": 2, "audited": 1}],
                               interrogated=10)
        self.assertIn("маршрут не сходится", str(caught.exception))

    def test_a_repeated_parameter_refuses(self):
        rows = [{"parameter": "A", "skipped": 4, "audited": 1},
                {"parameter": "A", "skipped": 4, "audited": 1}]
        with self.assertRaises(Exception) as caught:
            _parse_route_skips(rows, interrogated=5)
        self.assertIn("repeat", str(caught.exception))


class СтраховкаГРОМКАЯ_А_НЕ_ТИХАЯ(unittest.TestCase):
    """A mismatch between the table and the model is a refusal, not an on-the-fly correction."""

    def setUp(self):
        self.category = next(iter(R.ROUTE))
        self.name = sorted(R.ROUTE[self.category])[0]

    def test_a_routed_name_that_turns_out_to_EXIST_is_loud(self):
        found = [{"parameter": self.name, "instance_hit": 3,
                  "type_hit": 0, "not_applicable": 0, "no_value": 0,
                  "wrong_storage": 0, "exception": 0}]
        bad = R.verify_against_receipts(self.category, found)
        self.assertIn(self.name, bad)
        self.assertIn("СХЕМА ЕСТЬ", bad[self.name])

    def test_a_routed_name_that_stays_absent_is_silent(self):
        """CONTROL: a safeguard that always screams distinguishes nothing."""
        clean = [{"parameter": self.name, "instance_hit": 0, "type_hit": 0,
                  "not_applicable": 5, "no_value": 0, "wrong_storage": 0,
                  "exception": 0}]
        self.assertEqual(R.verify_against_receipts(self.category, clean), {})

    def test_an_exception_during_the_audit_is_NEITHER_ok_nor_a_violation(self):
        """Third outcome: whether the table holds or not is UNKNOWN."""
        blew = [{"parameter": self.name, "instance_hit": 0, "type_hit": 0,
                 "not_applicable": 0, "no_value": 0, "wrong_storage": 0,
                 "exception": 2}]
        bad = R.verify_against_receipts(self.category, blew)
        self.assertIn("НЕИЗВЕСТНО", bad[self.name])

    def test_a_category_outside_the_table_is_never_flagged(self):
        self.assertEqual(R.verify_against_receipts("OST_НЕТ_ТАКОЙ", []), {})

    def test_the_safety_is_actually_CALLED_on_the_extraction_path(self):
        """🔴 WITHOUT THIS THE WHOLE CLASS WOULD BE GUARDING A SHELF — AND THE FIRST TWO REVISIONS
        DID NOT PASS THE FAIL CONTROL.

        The tests above call the safeguard THEMSELVES, so its absence in prod would not
        turn them red: the result would be "built but not wired in."

        Revision 1 asked for `co_names` — the mutation "replace the call with an empty
        dict" left the name in place, because the name arrives via IMPORT.
        Third time in one day, the same shape: a name in the code does not mean a call in the code.

        Here what is asked is the BYTECODE: `LOAD_*` of this name, followed in the
        nearest instructions by `CALL`. An import leaves no such trace.
        """
        import dis
        from kir.decompile import extract as E

        def called(code, target):
            found = []
            ins = list(dis.get_instructions(code))
            for index, op in enumerate(ins):
                if op.opname.startswith("LOAD_") and op.argval == target:
                    if any(nxt.opname.startswith("CALL")
                           for nxt in ins[index + 1:index + 6]):
                        found.append(op.opname)
            for const in code.co_consts:
                if hasattr(const, "co_names"):
                    found += called(const, target)
            return found

        self.assertTrue(
            called(E.extract_document.__code__, "verify_against_receipts"),
            "страховка маршрута не ВЫЗЫВАЕТСЯ (имя может стоять от импорта): "
            "отсечённое имя, которое всё-таки существует, снова пройдёт молча")
        # PROBE CONTROL: a name that is not in this function must yield empty —
        # otherwise the check "finds" anything and means nothing.
        self.assertEqual(called(E.extract_document.__code__, "route_skip"), [])


class ТриРукиЗамераСОБИРАЮТСЯ_ПРОД_ФУНКЦИЕЙ(unittest.TestCase):
    """🔴 A SHAPE BOUGHT BY A LIVE MEASUREMENT ON 20.08.2026 — AND NOT ABOUT THE ROUTE.

    The first count gave 30 % savings against the real 22, which would have been a pleasant
    untruth. What saved it was looking at arm B: it shifted between
    runs (981 -> 715 ms), even though it CONTAINS no probes and the route cannot
    touch it. What moved was not the arm but the BASELINE — today's R was compared against yesterday's A.

    Hence two requirements, the second one free:
      * all three arms are taken in ONE RUN;
      * an arm the subject CANNOT touch must stay put;
        if it moved, it cannot be counted.

    Here the assembly is pinned; the law about the run itself lives in the docstring
    `build_probe_ab_arms`, because only a run can check it.
    """

    def test_the_three_arms_differ_exactly_where_they_must(self):
        from kir.decompile.extract import build_probe_ab_arms
        arms = build_probe_ab_arms("OST_Dimensions")
        self.assertEqual(sorted(arms), ["A", "B", "R"])
        # A — the route is off: the set is empty, the branch is never taken.
        self.assertEqual(_hashset(arms["A"]), set())
        # R — exactly what is in the table.
        self.assertEqual(_hashset(arms["R"]), set(R.route_skip("OST_Dimensions")))
        # B — no probes at all.
        self.assertNotIn("__PutParams(__element, __row);", arms["B"])
        self.assertIn("__PutParams(__element, __row);", arms["A"])

    def test_B_is_ONE_canonical_control_not_two_almost_equal(self):
        """The control arm must be one.

        Build it from both A and R — that would yield two bodies, differing
        by the dead route set, and "B shifted" would become indistinguishable from
        "a different B was built".
        """
        from kir.decompile.extract import build_probe_ab_arms
        first = build_probe_ab_arms("OST_Walls")["B"]
        second = build_probe_ab_arms("OST_Walls")["B"]
        self.assertEqual(first, second)
        self.assertEqual(_hashset(first), set(),
                         "контрольная рука несёт маршрут — значит их две")

    def test_the_arms_are_built_by_the_PRODUCTION_builder(self):
        """Not by substituting text: the substitution rests on the line's shape.

        The only substitution that remains is stripping the `__PutParams` call,
        and it checks its OWN applicability: the call must be exactly one, otherwise
        the assembly refuses loudly.
        """
        from kir.decompile import extract as E
        self.assertIn("build_category_batch_cs",
                      E.build_probe_ab_arms.__code__.co_names)

    def test_PRODUCTION_never_turns_the_route_off(self):
        """🔴 THE `route=False` KEY EXISTS ONLY FOR MEASUREMENT.

        We ask for the keyword arguments of the CALL in the prod path: CPython
        stores the names of keyword arguments as a constant tuple, and `route` must
        not be among them. This shape was bought three times today — a name in the code does not mean
        a call in the code, and vice versa.
        """
        from kir.decompile import extract as E

        def keyword_tuples(code, out=None):
            out = out if out is not None else []
            for const in code.co_consts:
                if isinstance(const, tuple):
                    out.append(const)
                elif hasattr(const, "co_consts"):
                    keyword_tuples(const, out)
            return out

        for tup in keyword_tuples(E.extract_document.__code__):
            self.assertNotIn("route", tup,
                             "прод-путь выключает маршрут: ключ замера уехал "
                             "в продукт")


if __name__ == "__main__":
    unittest.main()
