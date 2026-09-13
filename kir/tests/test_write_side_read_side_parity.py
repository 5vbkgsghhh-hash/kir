"""THE READING SIDE MUST ANSWER TO THE WRITING SIDE, NOT THE OTHER WAY AROUND.

THE TRIGGER WAS THE MEASUREMENT OF 12.08.2026, AND IT DISPROVED ITS OWN
PREMISE. The task arrived as "the acceptance judge does not know the
categories of the seven KR ops". The judge itself was asked
(`derive_expectation` on programs already accepted by the gate at 6/6) — and
the seven split into TWO different causes, of which only one was the one
originally claimed:

  * THREE loads (point, line, area) — the judge knows the category EXACTLY:
    one row, `exact`, upper and lower bounds intact. The third pillar of the
    cardinal invariant is NOT lost for them;
  * FOUR (truss, beam system, area reinforcement, strip foundation) — the
    blindness is NAMED in `acceptance._OPS_BLIND`, with a cause, a verdict,
    and a date, and it raises `upper_bounds_valid=False`. This is a declared
    loss, not silence.

Unnamed writing ops number zero — that is what `test_registry_category_accounting`
holds. But 22 ops out of 65 get no section, and THIS is the real gap: it is
not the judge's, it is the READING side's. Writing ops produce 61 census
categories; the carriers of the section vocabulary (`KINDS[*].collector_cs`,
`extract._CATEGORY_SPECS`) name 42. The nineteen remaining are the whole
discrepancy.

THIS IS THE SAME CLASS AS `query_types.pool`, IN A DIFFERENT CURRENCY: there
KIR writes into six pools it does not read, here into 19 categories that no
reading carrier names. The two lists were each kept separately, and nothing
forced them to converge. One rule covers both: **the set the reading side
must cover is DERIVED from the writing side, and every uncovered member is a
NAMED refusal with a cause and a deadline. There is no empty third option.**

WHAT THIS TEST DOES NOT REQUIRE. It does not require COVERAGE — appending a
row to the extraction table without an extractor would be asserting a
reading that does not exist, that is, introducing exactly the defect this
journal exists to forbid. It requires being RESOLVED: covered, or named.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_parity_queue.jsonl"))

from kir import acceptance, spec  # noqa: E402


def _categories_the_compiler_can_write() -> set[str]:
    """We ask the REGISTRY, not a list. A new op lands here on its own."""
    found: set[str] = set()
    for op in spec.OPS.values():
        if op.family in spec.WRITE_FAMILIES:
            found.update(spec.op_census_categories(op))
    return found


class ReadSideAnswersToWriteSide(unittest.TestCase):

    def test_the_registry_is_reachable_before_any_zero_below(self):
        """Any zero below would be a lie if the registry were empty or had shrunk.

        A direct consequence of the rule "any zero drawn from a corpus needs
        proof of reachability": here the corpus is the registry itself.
        """
        writing = {n for n, o in spec.OPS.items()
                   if o.family in spec.WRITE_FAMILIES}
        self.assertGreater(len(writing), 50, "реестр пишущих опов подозрительно мал")
        self.assertTrue(_categories_the_compiler_can_write(),
                        "ни одной категории у пишущих опов — прибор сломан, "
                        "а не расхождение закрыто")
        self.assertTrue(spec._category_disciplines(),
                        "носители словаря разделов не отдали ни одной строки")

    def test_every_written_category_is_either_read_or_named(self):
        """There is no third option — silence.

        A category the compiler is able to write into, about which neither
        any reading carrier NOR any journal row says a word, is invisible: an
        op with it gets no section, and from outside this is indistinguishable
        from "it needs no section".
        """
        covered = set(spec._category_disciplines())
        named = set(spec.CATEGORIES_WITHOUT_DISCIPLINE)
        silent = _categories_the_compiler_can_write() - covered - named
        self.assertEqual(
            silent, set(),
            "категории, в которые компилятор ПИШЕТ, но о которых читающая "
            "сторона молчит: " + ", ".join(sorted(silent)) + ". Либо строка "
            "у носителя (только вместе с настоящим экстрактором), либо "
            "запись в spec.CATEGORIES_WITHOUT_DISCIPLINE с причиной и сроком")

    def test_the_ledger_does_not_rot(self):
        """An entry about a category that the carriers ALREADY name is a lie.

        A gap journal that never removes closed rows describes, a month
        later, not the tree but the past; and worse, it pretends the work is
        not done — meaning it will be done a second time.
        """
        covered = set(spec._category_disciplines())
        stale = covered & set(spec.CATEGORIES_WITHOUT_DISCIPLINE)
        self.assertEqual(
            stale, set(),
            "строки журнала про уже покрытые категории: " +
            ", ".join(sorted(stale)) + " — удалить")

    def test_the_ledger_speaks_only_about_categories_that_exist(self):
        """A row about a category that NO op writes is also a gap in the
        accounting: it is forever green and forever useless."""
        writable = _categories_the_compiler_can_write()
        orphan = set(spec.CATEGORIES_WITHOUT_DISCIPLINE) - writable
        self.assertEqual(
            orphan, set(),
            "журнал говорит о категориях, которых не пишет ни один оп: " +
            ", ".join(sorted(orphan)))


def _pools_the_compiler_grounds_against() -> set[str]:
    """Grounding pools come from the REGISTRY (`OpSpec.grounded`), not from a list.

    The template name (`column_symbols_{category}`) is expanded over the
    CLOSED enumeration of the very parameter that substitutes into it:
    substituting a guess instead would mean measuring one's own templater,
    not the registry.
    """
    found: set[str] = set()
    for op in spec.OPS.values():
        choices = {p.name: p.choices for p in op.params if p.choices}
        for _param, pool, _required in op.grounded:
            if "{" not in pool:
                found.add(pool)
                continue
            key = pool[pool.index("{") + 1:pool.index("}")]
            for value in choices.get(key, ()):
                found.add(pool.replace("{" + key + "}", str(value)))
    return found


class EveryGroundedPoolCanBeAsked(unittest.TestCase):
    """THE SECOND CURRENCY OF THE SAME CLASS: pools instead of categories.

    Measurement of 12.08.2026: the compiler grounds into 35 pools, while
    `query_types.pool` read 27 — EIGHT pools that KIR is able to write into
    could not be asked about. The earlier entry named SIX: it had been
    derived from the needs of thirty UNVERIFIED ops, while `create_ceiling`
    and `create_railing` had long since been verified and did not fall into
    that slice. The answer for part of the set again turned out smaller than
    the answer for the whole set.

    And the cost of the fix, the reason it kept being deferred, turned out to
    be ZERO: the snapshot already collects all eight
    (`open_model.__profile_required_pools`), the collector idiom for each is
    already written there, and the tool's description did not grow by a
    single character — 27 185 before and after, because the pool enumeration
    is never printed into the description at all.
    """

    def test_the_registry_is_reachable_before_any_zero_below(self):
        self.assertGreater(len(_pools_the_compiler_grounds_against()), 20)
        self.assertTrue(_readable_pools())

    def test_every_pool_the_compiler_writes_into_can_be_asked(self):
        """A pool an op grounds into that cannot be enumerated is a
        `KIR-G102` one turn later, and the author will not learn of it in advance."""
        unaskable = _pools_the_compiler_grounds_against() - _readable_pools()
        self.assertEqual(
            unaskable, set(),
            "компилятор пишет в пулы, которых модель не может спросить: " +
            ", ".join(sorted(unaskable)) + ". Либо строка в "
            "`query_types.pool` вместе с коллектором в "
            "`compiler._TYPE_POOL_COLLECTOR_CS`, либо ИМЕНОВАННЫЙ отказ")

    def test_an_answer_that_gets_cut_must_say_so(self):
        """THE THIRD CURRENCY OF THE SAME CLASS, AND THE MOST EXPENSIVE OF THE THREE.

        The contract printout was being cut by length and losing tolerances —
        fixed on 12.08. The `query_types` ANSWER channel is a second channel
        of the same kind, and if someone were to cut it by length, the model
        would get a list of types READ AS COMPLETE and would choose from a
        truncated set. There, prose was being cut; here it would be the SET a
        choice is made from that would be cut.

        Today there is no cutter: the emission hands back every row and
        carries `total`. The test holds exactly this — not "the answer is
        small" (a property of the building), but "there is no silent
        truncation in the answer" (a property of the code). Should a ceiling
        appear, it must arrive together with a truncation flag, exactly as
        with the snapshot's pools (`open_model.CatalogPool`: an incomplete
        pool MUST declare `truncated`).

        Sizes were measured on 69 corpus profiles: `ceiling_types` maxes out
        at 8, `railing_types` at 22, truncations zero, and the largest pool
        of all — `family_symbols` at 741 — has been readable for a long time.
        """
        from kir import compiler
        for pool in sorted(_readable_pools()):
            with self.subTest(pool=pool):
                emitted = compiler.emit(
                    [{"op": "query_types", "id": "Q1", "pool": pool}],
                    revit_version="2026")
                self.assertIn('__r["total"] = __rows.Count', emitted,
                              "ответ не называет своего размера")
                for cut in (".Take(", ".Skip(", "__limit", "maxRows"):
                    self.assertNotIn(
                        cut, emitted,
                        f"в ответе появилось отсечение ({cut}) без флага "
                        f"усечения: усечённый список неотличим от полного, а "
                        f"выбор делается ИЗ НЕГО")

    def test_every_askable_pool_has_a_collector(self):
        """A name in the enumeration with no collector is a promise that
        refuses at emission time; that is worse than the name being absent,
        because it only shows up in the program."""
        from kir import compiler
        promised = _readable_pools() - set(compiler._TYPE_POOL_COLLECTOR_CS)
        self.assertEqual(
            promised, set(),
            "перечисление обещает пулы без идиомы сбора: " +
            ", ".join(sorted(promised)))


def _readable_pools() -> set[str]:
    return set(next(p.choices for p in spec.OPS["query_types"].params
                    if p.name == "pool"))


class TheJudgeIsNotTheGapForLoads(unittest.TestCase):
    """PINNED DOWN DELIBERATELY: the task's own statement claimed the opposite.

    Without this test, "the judge does not know loads" would come back — it
    sounds plausible (loads truly have no section) and is refuted only by
    measuring the judge itself.
    """

    #: Programs already accepted by the gate at 6/6 (`tools/live_programme_d.py`).
    LOADS = {
        "create_point_load": {
            "op": "create_point_load", "id": "P13",
            "xyz": [0.0, 0.0, 0.0], "fz_n": -1000.0,
            "load_case": {"by": "name", "value": "ЛС1"}},
        "create_line_load": {
            "op": "create_line_load", "id": "P14",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [4000.0, 0.0, 0.0],
            "fz_n_per_m": -500.0, "load_case": {"by": "name", "value": "ЛС1"}},
        "create_area_load": {
            "op": "create_area_load", "id": "P15",
            "outline": [[0.0, 0.0], [4000.0, 0.0], [4000.0, 4000.0],
                        [0.0, 4000.0]],
            "elev_mm": 0.0, "fz_n_per_m2": -250.0,
            "load_case": {"by": "name", "value": "ЛС1"}},
    }

    EXPECTED = {"create_point_load": "OST_PointLoads",
                "create_line_load": "OST_LineLoads",
                "create_area_load": "OST_AreaLoads"}

    def test_control_a_known_op_yields_a_checkable_row(self):
        """A CONTROL THAT MUST PASS. Without it, the green below means nothing:
        a program that fails the plan gives an EMPTY expectation, and "no row"
        would read as "the judge is blind"."""
        e = acceptance.derive_expectation([{
            "op": "create_wall", "id": "W",
            "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0], "height_mm": 3000.0,
            "type": {"by": "name", "value": "т"},
            "level": {"by": "name", "value": "У1"}}])
        self.assertEqual(e.notes, (), "контрольная программа не прошла план")
        self.assertTrue(e.rows)
        self.assertTrue(e.checkable)

    def test_control_a_program_that_fails_the_plan_says_so(self):
        """A CONTROL THAT MUST FAIL. An empty expectation with no note would be
        the very silence this file exists to catch."""
        e = acceptance.derive_expectation([{"op": "create_wall", "id": "W"}])
        self.assertEqual(e.rows, ())
        self.assertTrue(e.notes, "план отвергнут молча — записки нет")

    def test_the_judge_knows_each_load_exactly(self):
        for name, program in self.LOADS.items():
            with self.subTest(op=name):
                e = acceptance.derive_expectation([program])
                self.assertEqual(e.notes, (), f"{name}: программа не прошла план")
                self.assertEqual(len(e.rows), 1, f"{name}: не одна строка")
                row = e.rows[0]
                self.assertEqual(row.categories, (self.EXPECTED[name],))
                self.assertEqual(row.count, 1)
                self.assertEqual(row.certainty, acceptance.Certainty.EXACT)
                self.assertTrue(e.upper_bounds_valid, f"{name}: верхние границы сняты")
                self.assertTrue(e.lower_bounds_valid, f"{name}: нижние границы сняты")
                self.assertEqual(e.blind_ops, (), f"{name}: судья объявил слепоту")

    def test_the_loads_now_have_their_discipline_and_the_judge_still_knows(self):
        """🔴 REWRITTEN 04.09.2026: THE PIN WAS PINNING AN ABSENCE.

        This used to read `assertEqual(disciplines, ())` — "loads have NO
        section, and that is the whole gap". The assertion was true right up
        to the wave that entered loads into the extraction table with
        `discipline=
        "structural"`. That is, the pin was holding onto an ABSENCE that the
        wave was precisely obligated to remove: the better the work, the
        redder the suite, and success looks like a regression.

        THIS FILE'S SUBJECT WAS NOT HURT BY THIS, and that is the whole
        point. The file holds an assertion about the JUDGE ("the judge does
        not know loads" is false), and the section was only a PREMISE that
        made the assertion non-obvious. The premise stopped being true; the
        conclusion remained, and now it is stronger: the judge knew them back
        when there was no section, and knows them now that there is one.

        So what is checked is the PRESENT truth and its LINK to the table,
        not a snapshot of the earlier state: the section is derived, it is
        derived FROM that very category, and the row in the ledger saying
        "no section" is gone — otherwise the ledger and the table would have
        silently diverged.
        """
        for name, category in self.EXPECTED.items():
            with self.subTest(op=name):
                disciplines, why = spec.op_disciplines(spec.OPS[name])
                self.assertEqual(
                    disciplines, ("structural",),
                    "нагрузки заведены в таблицу извлечения разделом КР; "
                    "пустой раздел здесь значил бы, что категория ушла из "
                    "таблицы обратно")
                # `why` used to explain WHY the section could not be derived.
                # The section is derived — there is nothing left to explain,
                # and a non-empty row here would mean the tree holds two
                # answers at once.
                self.assertEqual(
                    why, "",
                    f"раздел выведен ({disciplines}), но довод о его "
                    f"отсутствии остался: {why!r}")
                self.assertNotIn(
                    category, spec.CATEGORIES_WITHOUT_DISCIPLINE,
                    "строка ведомости про категорию с выведенным разделом — "
                    "это протухшая запись, и храповик ведомости краснеет на "
                    "ней отдельно")


if __name__ == "__main__":
    unittest.main()
