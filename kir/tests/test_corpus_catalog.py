"""THE CORPUS CATALOG GUARD — and it must be able to say "no".

WHY A FIXTURE, NOT THE LIVE CORPUS — AND WHERE THE LIVE ONE IS STILL
NEEDED. The corpus is machine-local (80 catalogs, 4.1 GB, absent from
every checkout), so the main suite is built on a fixture. But a fixture
guards the FIXTURE, not the product (form 27), and that is why the
fixture's cards are assembled by PRODUCTION CODE —
`decompile.pipeline._passport_markdown`, the very same code that writes
them to disk. The parser cannot silently drift apart from the producer:
if it drifts, it turns red.

A separate class, `LiveCorpus`, walks the REAL corpus when it exists on
the box, and DECLARES A SKIP when it does not: "there is no corpus" and
"the corpus is empty" are different facts, and the second must not read
as the first.
"""
from __future__ import annotations

import os
import unittest

from kir import corpus_catalog as cc


def _card(doc_name: str, *, stamp: str, elements: int, floors: int = 1,
          rooms: int = 0, apartments: int = 0, gestalt: str = "",
          purpose: str = "не определено") -> str:
    """A card assembled by PRODUCTION CODE.

    🔴 HAND-WRITTEN MARKDOWN IS FORBIDDEN HERE. A test that hand-assembles
    its own input guards the fixture, not the product — and the more
    neatly it is written, the more loudly it claims the opposite (form
    27). That is why the input is built by `pipeline._passport_markdown`,
    and if the producer changes shape, the parser turns red here, not in
    production.
    """
    from kir.decompile.pipeline import _passport_markdown

    return _passport_markdown({
        "doc_name": doc_name,
        "revit_version": "2023",
        "change_stamp": stamp,
        "gestalt": gestalt or (
            "Здание, контур не определён, %d этажей по 3,3 м. "
            "Назначение: %s. Типовой этаж: не определён." % (floors, purpose)),
        "stats": {"elements_total": elements, "ops_lifted": elements // 2,
                  "atoms": elements // 2, "floors": floors, "rooms": rooms,
                  "apartments": apartments},
        "verify_summary": {"failed_count": 0, "reversible": True},
    })


class ParserSpeaksTheProducersLanguage(unittest.TestCase):
    """The parser parses what the producer writes — and distinguishes `?`
    from 0."""

    def test_round_trip_through_the_real_writer(self) -> None:
        card = cc.parse_card(_card("Дом А", stamp="a_v1", elements=1510,
                                   floors=26, rooms=120, apartments=10))
        self.assertEqual(card.doc_name, "Дом А")
        self.assertEqual(card.revit, "2023")
        self.assertEqual(card.change_stamp, "a_v1")
        self.assertEqual((card.elements, card.floors, card.rooms,
                          card.apartments), (1510, 26, 120, 10))
        self.assertIn("Назначение:", card.gestalt)

    def test_unknown_is_none_and_zero_is_zero(self) -> None:
        """A `?` from the producer means "nothing to ask", not zero.

        Merging the two would mean reporting "0 apartments" about a
        building where they simply were not counted. This is exactly the
        class of defect this whole project exists for.
        """
        card = cc.parse_card(_card("Дом Б", stamp="b", elements=5,
                                   apartments=0))
        self.assertEqual(card.apartments, 0)
        blind = cc.parse_card(
            "# KIR Passport — Дом В\n\n- Revit: ?\n\n## Stats\n"
            "- elements: ?\n- apartments: ?\n")
        self.assertIsNone(blind.elements)
        self.assertIsNone(blind.apartments)
        self.assertEqual(blind.revit, "")

    def test_the_searched_fields_are_exactly_the_haystack(self) -> None:
        """The declared set of fields and what is actually searched are
        one and the same.

        The `SEARCHED_FIELDS` list is declared COMPLETE BY CONSTRUCTION,
        and such a list is honest exactly to the extent its matcher is
        honest. What is checked here is the SEAM ITSELF: every declared
        field must land in the `haystack`, and nothing beyond what is
        declared may land there.
        """
        entry = cc.Entry(
            run="run_x", card=cc.parse_card(_card("ДокY", stamp="s",
                                                  elements=1)),
            labels=("ЯрлыкZ",), stage="done", l0_bytes=10)
        hay = entry.haystack()
        for token in ("run_x", "ДокY", "ЯрлыкZ"):
            self.assertIn(token, hay)
        self.assertIn(entry.card.gestalt, hay)
        self.assertEqual(set(cc.SEARCHED_FIELDS),
                         {"run", "doc_name", "gestalt", "labels"})
        # FAIL CONTROL ON THE SEAM: a value that is NOT in the set is not
        # searched for. The census and receipts carry category codes, and
        # a query by a service code must not match a building.
        self.assertNotIn("OST_SketchLines", hay)


def _corpus(tmp: str, runs: dict) -> None:
    for run, spec in runs.items():
        os.makedirs(os.path.join(tmp, run), exist_ok=True)
        if "card" in spec:
            with open(os.path.join(tmp, run, cc.CARD_NAME), "w",
                      encoding="utf-8") as handle:
                handle.write(spec["card"])
        if "l0" in spec:
            with open(os.path.join(tmp, run, "L0.jsonl"), "w",
                      encoding="utf-8") as handle:
                handle.write(spec["l0"])
        if "status" in spec:
            import json
            with open(os.path.join(tmp, run, "status.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(spec["status"], handle)


class MissingCardIsAReasonNotSilence(unittest.TestCase):
    """"There is no card" arrives WITH A REASON and distinguishes a dead
    decompile from a live one."""

    def setUp(self) -> None:
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        _corpus(self.tmp, {
            "good_v1": {"card": _card("Дом А", stamp="good_v1", elements=100),
                        "l0": "{}\n", "status": {"stage": "done"}},
            "dead_v1": {"l0": "{}\n",
                        "status": {"stage": "error",
                                   "errors": ["extract_failed: прервано"]}},
            "alive_v1": {"l0": "{}\n", "status": {"stage": "geometry"}},
        })

    def test_dead_and_alive_are_different_facts(self) -> None:
        catalog = cc.load_catalog(self.tmp)
        by_run = {m.run: m for m in catalog.missing}
        self.assertEqual(set(by_run), {"dead_v1", "alive_v1"})
        self.assertFalse(by_run["dead_v1"].alive)
        self.assertIn("extract_failed", by_run["dead_v1"].reason)
        # 🔴 A DECOMPILE THAT STOPPED AT THE `geometry` STAGE DID NOT
        # FAIL — it never got there. Merging it with a failed one would
        # mean burying a live building; on the real corpus there are TWO
        # of these (`k2_ar_rd_v9`, `len_ar_me_r24_v1`), and one of them
        # carries the tree's only «жилая башня» label.
        self.assertTrue(by_run["alive_v1"].alive)
        self.assertEqual(by_run["alive_v1"].reason, "")

    def test_absent_corpus_refuses_and_does_not_return_empty(self) -> None:
        """No corpus is a refusal, NOT an empty catalog.

        An empty catalog would read as "there are no such buildings"; a
        refusal says there was nothing to look at. A fact about the
        MACHINE, not about the buildings.
        """
        with self.assertRaises(cc.CorpusCatalogError) as caught:
            cc.load_catalog(os.path.join(self.tmp, "нет-такого"))
        self.assertIn("KUKAI_DECOMPILE_DATA", str(caught.exception))


class ThreeOutcomesAndNoneOfThemIsSilent(unittest.TestCase):
    """Three selection outcomes, and a FAIL control on each."""

    def setUp(self) -> None:
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        _corpus(self.tmp, {
            # One building, THREE versions: `done` 100 · `done` 300 ·
            # `passport` 900.
            "tower_v1": {"card": _card("Башня", stamp="tower_v1",
                                       elements=100, floors=40),
                         "status": {"stage": "done"}},
            "tower_v2": {"card": _card("Башня", stamp="tower_v2",
                                       elements=300, floors=40),
                         "status": {"stage": "done"}},
            "tower_v3": {"card": _card("Башня", stamp="tower_v3",
                                       elements=900, floors=40),
                         "status": {"stage": "passport"}},
            "shed_v1": {"card": _card("Сарай", stamp="shed_v1", elements=7,
                                      purpose="офис"),
                        "status": {"stage": "done"}},
        })
        self.catalog = cc.load_catalog(self.tmp)

    def test_found_one_presents_the_rule_and_the_losers(self) -> None:
        found = cc.search("Сарай", self.catalog)
        self.assertEqual(found.outcome, cc.FOUND_ONE)
        self.assertIsNotNone(found.building)
        self.assertEqual(found.building.chosen.run, "shed_v1")
        self.assertEqual(found.building.rule, cc.RUN_CHOICE_RULE)

    def test_completed_beats_bigger(self) -> None:
        """The selection rule within a building: `done` outranks the
        element count.

        A TARGETED FAIL CONTROL: `tower_v3` is the largest of all (900
        versus 300), and it wins exactly when it reaches `done`. A single
        edit to the stage flips the outcome — so the rule is not
        decorative.
        """
        chosen = cc.search("Башня", self.catalog).building
        self.assertEqual(chosen.chosen.run, "tower_v2")
        # The order of the losers ALSO carries the rule: the unfinished
        # `tower_v3` stands AFTER the finished `tower_v1`, even though it
        # is nine times larger.
        self.assertEqual([e.run for e in chosen.runners_up],
                         ["tower_v1", "tower_v3"])
        import json
        with open(os.path.join(self.tmp, "tower_v3", "status.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"stage": "done"}, handle)
        again = cc.search("Башня", cc.load_catalog(self.tmp)).building
        self.assertEqual(again.chosen.run, "tower_v3")

    def test_found_many_never_picks_silently(self) -> None:
        """Several matches — name them, do not pick one.

        `building` must be `None`: a silent "first of the matches" is
        just `.FirstOrDefault()` with a good reputation.
        """
        many = cc.search("Здание", self.catalog)
        self.assertEqual(many.outcome, cc.FOUND_MANY)
        self.assertIsNone(many.building)
        self.assertEqual({b.doc_name for b in many.matched},
                         {"Башня", "Сарай"})
        for name in ("Башня", "Сарай"):
            self.assertIn(name, many.refused)

    def test_not_found_names_the_vocabulary_that_would_work(self) -> None:
        """A refusal must give the NEXT MOVE, otherwise to an LLM it
        equals silence."""
        nothing = cc.search("вертолётная площадка", self.catalog)
        self.assertEqual(nothing.outcome, cc.NOT_FOUND)
        self.assertEqual(nothing.matched, ())
        self.assertIn("Башня", nothing.refused)
        self.assertIn("Сарай", nothing.refused)
        # The closed dictionary of purposes (`name._purpose`) is also
        # presented.
        self.assertIn("офис", nothing.refused)

    def test_empty_query_is_not_the_same_refusal_as_no_match(self) -> None:
        """An empty query is a fact about the QUERY; a miss is a fact
        about the CORPUS."""
        blank = cc.search("", self.catalog)
        self.assertEqual(blank.outcome, cc.NOT_FOUND)
        self.assertIn("запрос пуст", blank.refused)
        self.assertNotIn("запрос пуст",
                         cc.search("вертолёт", self.catalog).refused)

    def test_match_identifies_the_building_choice_ranges_over_all_runs(self):
        """A match identifies the BUILDING; the candidates are drawn from
        the whole catalog.

        A CONTROL PAID FOR BY A LIVE RUN: a query by ONE version's stamp
        must still present the building's other versions. The first
        edition built the selection from the matched rows, and «фасад»
        was returning `runners_up: []` while eighteen facade decompiles
        existed in the corpus — one code for two outcomes ("there are no
        others" versus "the others did not match"), our form 11.
        """
        one = cc.search("tower_v1", self.catalog)
        self.assertEqual(one.outcome, cc.FOUND_ONE)
        self.assertEqual(len(one.building.runners_up), 2)


class TheRootIsAskedNotReinvented(unittest.TestCase):
    def test_selection_carries_the_root_it_searched(self) -> None:
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        _corpus(tmp, {"a_v1": {"card": _card("Дом", stamp="a_v1",
                                             elements=3),
                               "status": {"stage": "done"}}})
        self.assertEqual(cc.search("Дом", root=tmp).root, tmp)

    def test_root_comes_from_the_shared_authority(self) -> None:
        """A third corpus address is not introduced into the tree."""
        from kir.clash.existing import decompile_root

        self.assertEqual(cc.corpus_root(), str(decompile_root()))


class LiveCorpus(unittest.TestCase):
    """A run over the REAL corpus — or a declared skip.

    "There is no corpus on this box" and "nothing was found in the
    corpus" must be distinguishable, so a skip NAMES the path, rather
    than staying silent.
    """

    def setUp(self) -> None:
        try:
            self.catalog = cc.load_catalog()
        except cc.CorpusCatalogError as exc:
            self.skipTest("живого корпуса на этой машине нет: %s" % exc)
        if not self.catalog.entries:
            self.skipTest("корпус есть, но карточек в нём нет: %s"
                          % self.catalog.root)

    def test_every_run_is_either_carded_or_explained(self) -> None:
        """Not one corpus catalog stays silent about itself.

        This is exactly the wave's law: 80 catalogs = 52 cards + 28 named
        reasons, and zero silent lines.
        """
        for missing in self.catalog.missing:
            self.assertTrue(
                missing.reason or missing.stage,
                "разбор %r не сказал о себе НИЧЕГО — ни причины, ни стадии; "
                "именно это молчание волна и закрывает" % missing.run)

    def test_the_catalog_is_cheap_and_never_opens_passport_json(self) -> None:
        """62 KB versus 961.8 MB — the trap the neighbors already paid
        for."""
        self.assertLess(self.catalog.bytes_read, 2_000_000,
                        "каталог прочитал больше 2 МБ — почти наверняка "
                        "открылся `passport.json`, и это ловушка на 17.2 с")

    def test_the_three_example_queries_of_the_wave(self) -> None:
        """A PASS CONTROL: this is what the wave was for.

        The queries are taken verbatim from the task. Every one must
        produce a NAMED outcome, and not one may return an empty list
        without a reason.
        """
        for query in ("жилая башня", "многофункциональное", "Snowdon"):
            with self.subTest(query=query):
                found = cc.search(query, self.catalog)
                self.assertIn(found.outcome,
                              (cc.FOUND_ONE, cc.FOUND_MANY, cc.NOT_FOUND))
                if found.outcome == cc.FOUND_ONE:
                    self.assertIsNotNone(found.building)
                else:
                    self.assertTrue(found.refused,
                                    "исход %s приехал БЕЗ причины — молчащий "
                                    "отказ ровно то, что чинит волна"
                                    % found.outcome)

    def test_a_query_that_cannot_match_still_names_the_way_in(self) -> None:
        nothing = cc.search("шалаш из веток", self.catalog)
        self.assertEqual(nothing.outcome, cc.NOT_FOUND)
        self.assertIn("здания корпуса:", nothing.refused)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
