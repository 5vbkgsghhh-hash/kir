"""THE CANDIDATE LIST MUST NAME ITS REMAINDER — THE CHOICE IS MADE FROM IT.

THE OCCASION IS THE MEASUREMENT OF 12.08.2026 ACROSS 69 CORPUS PROFILES. A
grounding refusal carries FIVE candidates and suggests "specify via
element_id from candidates." Meanwhile the pool is often much larger than
five:

    more than five         524 observations out of 1203  (43.6%)
    family_symbols         69 profiles out of 69, maximum 741
    levels                 69 out of 69, maximum 122
    wall_types             59 out of 69, maximum 185
    door_symbols           53 out of 69, maximum 113

Before this test, the model could not distinguish "five out of five" from
"five out of seven hundred and forty-one" — and it chose a type from a
truncated set, believing it complete.

THIS IS THE THIRD CURRENCY OF ONE AND THE SAME DEFECT IN ONE DAY. The
contract printout was cut by length and lost TOLERANCES; the `TOP_N = 8`
census kept the NUMBERS and lost the category NAMES; here both were lost at
once. What the three share: **a cut by a magnitude unrelated to the
question** (text length, category size, ElementId order), while what is
diagnostically interesting is almost always the ANOMALOUS member, and being
anomalous most often means being SMALL. And all three reductions are
arithmetically honest — a reviewer checking "was anything lost" answers "no"
and is right. **What is lost is not the magnitude but the FITNESS.**

THERE ARE TWO CURES, AND THE SECOND APPLIES HERE. Cutting by RELEVANCE is
already what `_nearest()` does in this same file (`difflib`), but there a
name EXISTS to measure closeness by. On the `by=default` branch there is no
name by construction, so the second cure remains: NAME THE REMAINDER AND
GIVE A WAY TO READ IT. The number says how much you do not see; the next
turn says what to do.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_candidates.jsonl"))

from kir import ground  # noqa: E402


def _pool(n: int, name: str = "тип") -> list[dict]:
    return [{"id": 1000 + i, "name": f"{name} {i}"} for i in range(n)]


class TheCandidateListSaysHowMuchIsHidden(unittest.TestCase):

    def test_control_a_pool_that_fits_pays_nothing(self):
        """PASS CONTROL. The note must appear ONLY when there is something
        that does not fit: the refusal is paid for in tokens on every turn,
        and a note saying "showing 5 of 5" would be noise in every refusal."""
        мал = _pool(5)
        self.assertEqual(
            ground._shown_of(мал, "wall_types", ground._candidate_rows(мал)), "")
        self.assertEqual(ground._shown_of([], "wall_types", []), "")

    def test_a_pool_that_does_not_fit_names_the_total(self):
        pool = _pool(185)
        text = ground._shown_of(pool, "wall_types",
                                ground._candidate_rows(pool))
        self.assertIn("185", text)
        # The shown count is taken from the CONSTANT, not hardcoded as a
        # literal: the literal "5" survived a threshold raise to twelve and
        # became a lie on the neighboring branch (see `_shown_of`,
        # 26.08.2026).
        self.assertIn(str(ground._CANDIDATES_SHOWN), text)

    def test_it_names_the_next_move_and_not_only_the_number(self):
        """A refusal that names a magnitude without a next turn shifts the
        work onto the reader — the same defect as code without a route."""
        pool = _pool(741)
        text = ground._shown_of(pool, "family_symbols",
                                ground._candidate_rows(pool))
        self.assertIn("query_types", text)
        self.assertIn("family_symbols", text)

    def test_the_shown_count_matches_what_is_actually_shown(self):
        """Two magnitudes about one fact must agree: the note says "showing
        N," the list returns exactly N rows. If they diverged, they would
        produce exactly the defect the note was set up for.

        🔴 ONLY ONE OF THREE TRIMMERS WAS CHECKED (26.08.2026). This guard
        took only `_candidate_rows` — the one and only one that did NOT
        diverge from its note. `_nearest` (the "name not found" branch,
        KIR-G101) trimmed by its own `n=5` and returned FIVE rows under the
        caption "SHOWN 12 OF 48"; this test's green told nothing about it.
        The same kind of thing as a guard covering half of its own class.

        Now ALL trimmers whose rows go into `candidates=` are checked.
        """
        pool = _pool(200)
        обрезатели = {
            "_candidate_rows": ground._candidate_rows(pool),
            "_nearest": ground._nearest("тип 7", pool),
            "_disqualified_rows": ground._disqualified_rows(
                pool, {"param": "Диаметр", "value": 100}),
        }
        for имя, rows in обрезатели.items():
            with self.subTest(обрезатель=имя):
                self.assertEqual(
                    len(rows), ground._CANDIDATES_SHOWN,
                    f"{имя}: свой потолок показа — второй носитель одного "
                    "числа, и он уже расходился")
                self.assertIn(
                    f"ПОКАЗАНЫ {len(rows)} ИЗ 200",
                    ground._shown_of(pool, "wall_types", rows),
                    f"{имя}: подпись не совпала с длиной выданного списка")

    def test_every_row_carries_an_id_because_the_next_move_needs_it(self):
        """The advice "specify via element_id from candidates" is
        unfulfillable if the row has no id."""
        for row in ground._candidate_rows(_pool(9)):
            self.assertIsInstance(row["id"], int)
            self.assertTrue(row["name"])


class TheAmbiguousRefusalsCarryIt(unittest.TestCase):
    """The note must reach THE MESSAGE, not stay inside the function.

    This is checked through the public grounding path: a test that reads
    only `_shown_of` would prove that the line is assembled, and nothing
    about whether it reaches the one who chooses.
    """

    def _diags(self, pool_size: int) -> list:
        diags: list = []
        ground._resolve_one(
            {"by": "default"}, "wall_types", _pool(pool_size),
            0, "W1", "type", "create_beam", diags)
        return diags

    def test_a_big_pool_refusal_states_the_remainder(self):
        diags = self._diags(185)
        self.assertTrue(diags, "отказа нет — заземление что-то разрешило само")
        message = str(diags[0].message_ru)
        self.assertIn("185", message)
        self.assertIn("query_types", message)

    def test_control_a_small_pool_refusal_stays_silent_about_it(self):
        """FAIL CONTROL for the note: on a small pool it must NOT be there,
        otherwise the test above would pass even with an unconditional
        insertion."""
        diags = self._diags(3)
        self.assertTrue(diags)
        self.assertNotIn("ПОКАЗАНЫ", str(diags[0].message_ru))

    def test_the_count_is_in_the_message_even_for_small_pools(self):
        """The `by=default` branch did not name the NUMBER of options at
        all — it said "several." This is the worst case: truncation without
        a magnitude and without a name."""
        diags = self._diags(3)
        self.assertIn("3 вариант", str(diags[0].message_ru))


if __name__ == "__main__":
    unittest.main()


class CandidateNamesWhyItIsUnusable(unittest.TestCase):
    """A candidate must carry the trait that makes it UNFIT.

    🔴 LIVE MEASUREMENT OF 24.08.2026, «Проект2», the revit_ir prod path:
    `create_adaptive_component` got `KIR-G102` with 323 candidates from
    `family_symbols`, and all the ones shown were curtain-wall mullions. The
    adaptive op needs `FamilyPlacementType.Adaptive`; the refusal showed the
    name and the family, and carried NO trait at all by which the candidate
    was unfit.

    The model reads five rows and chooses from them — and there was nothing
    to choose, and it had no way to find that out before the run. Capturing
    the trait was fixed in the same pass (`open_model.GROUND_SNAPSHOT_CS`,
    key `placement_type`); here is the second half: the trait must REACH the
    reader's eyes.
    """

    def test_placement_type_reaches_the_candidate_row(self):
        pool = [{"id": 11, "name": "Импост 50х150", "category": "OST_CurtainWallMullions",
                 "family_name": "Импост", "type_name": "50х150",
                 "placement_type": "OneLevelBased"}]
        rows = ground._candidate_rows(pool)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0].get("placement_type"), "OneLevelBased",
            "кандидат не несёт типа размещения: читатель видит имя, но не "
            "видит, ПОЧЕМУ этот кандидат ему не подойдёт",
        )

    def test_control_a_row_without_the_key_stays_silent_not_invented(self):
        # The reverse-direction control: where the trait is ABSENT, it must
        # not be invented.
        # "Did not read it" and "read it, and here is what's there" are
        # different facts.
        rows = ground._candidate_rows([{"id": 12, "name": "Стена 200"}])
        self.assertNotIn(
            "placement_type", rows[0],
            "признак выдуман там, где захват его не дал",
        )
