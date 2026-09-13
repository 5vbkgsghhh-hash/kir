"""A SKIPPED DECOMPILE MUST BE COUNTED, AND "NOTHING TO SAY" IS NOT "NOT IT".

Two defects in one row of `existing.resolve_run`, and both turned a fact
ABOUT THE INSTRUMENT into a fact ABOUT THE BUILDING.

1. THE `MUTE_SOURCES` DEBT. Directories skipped for lacking a passport, an
   L0, or simply not being directories at all did not land in ANY count: not
   in `seen`, not in `refuted`. The reader got "reviewed 0 — NOTHING TO
   COMPARE against" and read it as "there is no decompile", even though the
   directories DID exist. The answer did not change — a skip stayed a skip —
   but the SILENCE gained a REASON that can be asked about (in the shape of
   `install_paths` and `viewer/scene`).

2. E-34. `_doc_name_from_l0_head` declares THREE outcomes, but the condition
   read TWO: an empty string — "the decompile carries no name" — was compared
   against the header AS A NAME and answered "not it". That broke the law
   written in the module itself about the cheap filter: "it cannot skip a
   real candidate, because 'I don't know' and 'not it' are different
   outcomes." A decompile with an empty `doc_name` in its head and the RIGHT
   name in its passport was thrown out, and the resolver answered "no
   decompile in the corpus" while a live decompile sat on disk.

🔴 Next to every case stands its opposite: a genuine "not it" must still
reject, and a clean corpus must not grow a single extra word into a refusal.
Without them, a fix of "reject nothing" and a fix of "always append a note
about skips" would have passed the checks above.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kir.clash import existing as E


def _run(root: pathlib.Path, name: str, *, head_name: str | None,
         passport_name: str | None) -> pathlib.Path:
    d = root / name
    d.mkdir(parents=True)
    if head_name is not None:
        head = {"record": "header",
                "document": {"doc_name": head_name,
                             "levels": [{"id": "L1", "name": "1",
                                         "elevation_mm": 0.0}]}}
        (d / "L0.jsonl").write_text(
            json.dumps(head, ensure_ascii=False) + "\n", encoding="utf-8")
    if passport_name is not None:
        (d / "passport.json").write_text(
            json.dumps({"doc_name": passport_name}, ensure_ascii=False),
            encoding="utf-8")
    return d


class ПропускНазываетСебяЧисломИПричиной(unittest.TestCase):

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())

    def test_three_kinds_of_skip_are_counted_and_named_apart(self):
        (self.root / "мусорный.txt").write_text("не каталог", encoding="utf-8")
        _run(self.root, "нет_паспорта", head_name="Проект1",
             passport_name=None)
        _run(self.root, "нет_l0", head_name=None, passport_name="Проект1")
        run, why, _fresh = E.resolve_run("Проект1", root=self.root)
        self.assertIsNone(run)
        self.assertIn("ПРОПУЩЕНО 3", why)
        # The three causes are counted SEPARATELY: their next move differs.
        for cause in ("не каталог", "паспорта нет", "L0 нет"):
            with self.subTest(cause=cause):
                self.assertIn(cause, why)

    def test_a_clean_corpus_says_nothing_about_skips(self):
        """🔴 THE SECOND OUTCOME. Without it, a fix of "always append a note
        about skips" would have passed the check above, and the refusal would
        grow noise on every call."""
        _run(self.root, "чужой", head_name="ДРУГОЙ", passport_name="ДРУГОЙ")
        run, why, _fresh = E.resolve_run("Проект1", root=self.root)
        self.assertIsNone(run)
        self.assertIn("просмотрено 1", why)
        self.assertNotIn("ПРОПУЩЕНО", why)


class ПустаяСтрокаЭтоНеОтветНеОн(unittest.TestCase):

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())

    def test_an_empty_head_name_falls_through_to_the_passport(self):
        """E-34: the cheap filter MAY NOT lose a candidate. The head is
        silent, the passport names it — the decompile must be found."""
        want = _run(self.root, "шапка_молчит", head_name="",
                    passport_name="Проект1")
        run, why, _fresh = E.resolve_run("Проект1", root=self.root)
        self.assertEqual(run, want)
        self.assertEqual(why, "")

    def test_an_unreadable_head_still_falls_through_to_the_passport(self):
        """The third outcome, `None`, worked before too — the fix did not touch it."""
        want = self.root / "шапка_битая"
        want.mkdir(parents=True)
        (want / "L0.jsonl").write_text("НЕ JSON\n", encoding="utf-8")
        (want / "passport.json").write_text(
            json.dumps({"doc_name": "Проект1"}, ensure_ascii=False),
            encoding="utf-8")
        run, _why, _fresh = E.resolve_run("Проект1", root=self.root)
        self.assertEqual(run, want)

    def test_a_head_that_names_another_document_still_rejects(self):
        """🔴 THE SECOND OUTCOME. The cheap filter must REMAIN a filter:
        without this case, a fix of "reject nothing" would have passed both
        checks above, and the entire point of the cheap pass (0.7 s versus
        17.2 s) would be lost."""
        _run(self.root, "чужой", head_name="ДРУГОЙ", passport_name="Проект1")
        run, why, _fresh = E.resolve_run("Проект1", root=self.root)
        self.assertIsNone(run, "шапка назвала ДРУГОЙ документ — не кандидат")
        self.assertIn("просмотрено 1", why)


if __name__ == "__main__":
    unittest.main()
