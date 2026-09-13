"""SEARCH BY NAME IN THE CATALOG — and why, without it, the author returns
ZERO.

MEASUREMENT OF 19.08.2026, THREE AUTHORS, ONE FORM. The catalog handed back
only whole pools, and the author wrote the search themselves:
`next((r for r in model.levels() if ...), None)`. A typo produced `None`,
the author appended `or <number>`, and a ZERO OF A MAGNITUDE NO ONE HAD
COUNTED went into the program:

  * 540 beams out of 540 at `z=0` while «Этаж 5» was written (a hand on
    KIR);
  * «Типовой - 150мм» versus «Типовой 150мм» — a type name from memory on a
    new run (a control hand on free-form C#, a live Revit refusal);
  * a table of elevations recomputed by arithmetic instead of read: «Этаж
    9» was missing from the list of names, twenty double-height columns,
    with beams in their middle, no beams on the roof (the director, during
    the marathon, one stage after building instruments against this very
    class).

🔴 WHAT THIS FILE DOES NOT PROMISE. It does not check that grounding will
resolve the name the same way the script found it — that is a claim about
TWO places, and it is held by the matching rule copied from `ground.py`
(exact, otherwise the only case-insensitive one). Only the catalog side is
checked here.
"""
from __future__ import annotations

import unittest

from kir.sandbox import ModelCatalog, execute_author_script

#: A live pair from the document where this was written: the template
#: level and the authored one stand at THE SAME elevation. Evidence
#: `KIR-A006` — 35 columns went to «Уровень 1».
CATALOGUE = {
    "levels": [
        {"id": 311, "name": "Уровень 1", "elevation_mm": 0},
        {"id": 300832, "name": "Этаж 1", "elevation_mm": 0},
        {"id": 300840, "name": "Этаж 9", "elevation_mm": 32699.999999999996},
        {"id": 300841, "name": "Кровля", "elevation_mm": 36600},
    ],
    "wall_types": [{"id": 7, "name": "Типовой 150мм"}],
}


class LookupNamesWhatItCannotDecide(unittest.TestCase):

    def test_the_indistinguishable_neighbour_is_named(self):
        """Evidence KIR-A006 in full: the magnitude is returned, the match
        is NAMED."""
        row = ModelCatalog(CATALOGUE, "d").level("Этаж 1")
        self.assertEqual(row["id"], 300832)
        self.assertEqual(row["indistinguishable_on_elevation"], ["Уровень 1"])

    def test_no_neighbour_is_an_empty_list_not_a_missing_key(self):
        """"The neighbor was checked and not found" and "it was not looked
        at" are different claims."""
        row = ModelCatalog(CATALOGUE, "d").level("Кровля")
        self.assertIn("indistinguishable_on_elevation", row)
        self.assertEqual(row["indistinguishable_on_elevation"], [])

    def test_a_typo_refuses_with_candidates_instead_of_returning_none(self):
        """The exact typo that cost the control hand a live run."""
        with self.assertRaises(KeyError) as caught:
            ModelCatalog(CATALOGUE, "d").find("wall_types", "Типовой - 150мм")
        self.assertIn("Типовой 150мм", str(caught.exception))

    def test_a_missing_level_names_the_near_misses(self):
        with self.assertRaises(KeyError) as caught:
            ModelCatalog(CATALOGUE, "d").find("levels", "Этаж 99")
        text = str(caught.exception)
        self.assertIn("Этаж 9", text)
        self.assertIn("нет имени", text)

    def test_the_matching_rule_is_the_one_ground_uses(self):
        """Exact, otherwise the ONLY case-insensitive one. It must not
        diverge."""
        cat = ModelCatalog(CATALOGUE, "d")
        self.assertEqual(cat.find("levels", "этаж 9")["id"], 300840)

    def test_a_duplicated_name_refuses_rather_than_picking(self):
        """A choice between two same-named ones would be made by someone
        other than the author."""
        twins = {"levels": [{"id": 1, "name": "Э", "elevation_mm": 0},
                            {"id": 2, "name": "Э", "elevation_mm": 3000}]}
        with self.assertRaises(KeyError) as caught:
            ModelCatalog(twins, "d").find("levels", "Э")
        self.assertIn("выбор между ними сделал бы не ты", str(caught.exception))

    def test_an_absent_pool_still_says_whose_fault(self):
        """Inherited from `_rows`: "not sent" is a fact about US, not about
        the building."""
        with self.assertRaises(KeyError) as caught:
            ModelCatalog(CATALOGUE, "d").find("door_symbols", "любое")
        self.assertIn("НЕ ПРИСЛАЛИ", str(caught.exception))


class TheMutationsThatMustBreakIt(unittest.TestCase):
    """A form from `test_witness_vacuity`: a check that cannot be made to
    fail is not a check. Each mutation cuts out exactly one property."""

    def test_dropping_the_neighbour_scan_breaks_the_assertion(self):
        class Blind(ModelCatalog):
            def level(self, name):                      # the neighbor is not searched for
                row = self.find("levels", name)
                row["indistinguishable_on_elevation"] = []
                return row
        self.assertEqual(
            Blind(CATALOGUE, "d").level("Этаж 1")["indistinguishable_on_elevation"],
            [], "мутация обязана давать пустоту")
        self.assertNotEqual(
            ModelCatalog(CATALOGUE, "d").level("Этаж 1")["indistinguishable_on_elevation"],
            [], "а НАСТОЯЩИЙ каталог обязан назвать соседа")

    def test_returning_none_instead_of_refusing_breaks_the_assertion(self):
        class Silent(ModelCatalog):
            def find(self, pool, name):                 # a silent None instead of a refusal
                rows = self._rows(pool)
                return next((dict(r) for r in rows
                             if str(r.get("name", "")) == name), None)
        self.assertIsNone(Silent(CATALOGUE, "d").find("wall_types", "Типовой - 150мм"))
        with self.assertRaises(KeyError):
            ModelCatalog(CATALOGUE, "d").find("wall_types", "Типовой - 150мм")


class ReproducibilityIsNotSpentOnThis(unittest.TestCase):
    """The sandbox runs the script TWICE and compares digests. Reading the
    live model brings in a value from outside — and must not break this."""

    SCRIPT = ('envelope(intent="читаю таблицу, а не пересчитываю")\n'
              'top = model.level("Кровля")\n'
              'create_beam(id="b", p0_mm=[0, 0, top["elevation_mm"]],\n'
              '            p1_mm=[6000, 0, top["elevation_mm"]],\n'
              '            level=by_name(top["name"]))\n')

    def test_the_same_snapshot_gives_the_same_program(self):
        one = execute_author_script(self.SCRIPT, model=CATALOGUE)
        two = execute_author_script(self.SCRIPT, model=CATALOGUE)
        self.assertTrue(one.ok, getattr(one.refusal, "message_ru", one.refusal))
        self.assertEqual(one.program_digest, two.program_digest)
        self.assertEqual(one.model_digest, two.model_digest)

    def test_the_replay_that_proves_determinism_is_on_where_it_matters(self):
        """🔴 The claim must be about the PROD POLICY, not about the
        default.

        `SandboxPolicy.replay_check` defaults to **False**, and the first
        edit of this test read the default, mistaking it for a guarantee.
        The double run is enabled by the showroom — `serving.py:1704`,
        `SandboxPolicy(replay_check=True, allowed_imports=allowed)` —
        exactly the same place where the live list of imports is
        assembled. The fork "frozen default versus live assembly" already
        cost this file a day: the tool description printed the model
        `ALLOWED_IMPORTS` instead of `allowed_imports_for_env()` and
        assured that numpy and shapely were unavailable, while they were
        open.
        """
        from kir.sandbox import SandboxPolicy
        self.assertFalse(SandboxPolicy().replay_check,
                         "умолчание изменилось — перечитай, на чём стоит вывод")
        one = execute_author_script(
            self.SCRIPT, model=CATALOGUE,
            policy=SandboxPolicy(replay_check=True))
        self.assertTrue(one.ok, getattr(one.refusal, "message_ru", one.refusal))
        self.assertTrue(one.isolation.get("replay_checked"))
        self.assertEqual(one.isolation.get("environment_replay"), "same")

    def test_a_moved_level_is_NAMED_by_the_catalogue_signature(self):
        """Drift of the building must be visible as a field, not as the
        reader's guess."""
        moved = {**CATALOGUE, "levels": [
            (r if r["name"] != "Кровля" else {**r, "elevation_mm": 40000})
            for r in CATALOGUE["levels"]]}
        one = execute_author_script(self.SCRIPT, model=CATALOGUE)
        two = execute_author_script(self.SCRIPT, model=moved)
        self.assertEqual(one.author_digest, two.author_digest)   # the text is the same
        self.assertNotEqual(one.model_digest, two.model_digest)  # the building is different
        self.assertNotEqual(one.program_digest, two.program_digest)


if __name__ == "__main__":
    unittest.main()
