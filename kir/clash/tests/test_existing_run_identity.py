"""A DECOMPILE WITH THE SAME NAME IS NOT THE SAME DOCUMENT, and the receipt is
required to say so.

THE MEASUREMENT THIS FILE GREW FROM (corpus of decompiles, 20.08.2026):

    decompiles with a passport and L0        54
    unique document NAMES                    11
    sit in a same-name group                 51  = 94 %
    same-named AND WITHOUT identity          49
    largest single-name group                18

That is, the document NAME in this corpus is almost not a key. And within one
class of evidence the choice was decided by a SINGLE `mtime`: among the 18
same-named ones the last-written directory simply won.

THE CONCRETE CASE THIS STARTED FROM. `resolve_run("Проект1")` selects
`graph_check`: **Revit 2023, 1556 elements**. The live "Проект1" of this evening
is **Revit 2026**, the document into which live construction was going all
evening. A report of collisions between today's geometry and someone else's
building is not a "bad report" but a FALSE one: it will name disputes that do not
exist, and stay silent about the ones that do.

🔴 WHAT WAS ALREADY BUILT HERE, AND THIS MATTERS MORE THAN WHAT IS NEW. Identity
was already checked before this wave: a `project_uid` mismatch DISCARDS a
decompile with a named cause («2 отброшено по РАСХОЖДЕНИЮ личности»), and a weak
match is honestly printed in the receipt as the line «🔴 ИСТОЧНИК СТОЯЩЕГО НЕ
ДОКАЗАН». The substitution was NOT silent. The hole already existed: identity is
carried by **2 passports out of 54**, and for the rest there is nothing to refute
with.

WHAT WAS ADDED. The Revit version exists on BOTH sides from the very
start — the decompile writes `passport.revit_version`, the live side
`__revit_version` from `doc.Application.VersionNumber` — and it was NEVER
cross-checked. Now it:

* enters the selection order between lineage and file clock (match > one
  side silent > mismatch), disqualifying no one: a document upgrade is
  legitimate, and losing the only candidate because of it is worse than comparing
  with a caveat;
* is printed in the receipt as a SEPARATE line, because "a past state of THE SAME
  document" and "possibly a DIFFERENT document" require different actions from the
  reader: check against the model — or not trust the report at all.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import time
import unittest

from kir.clash import existing as E
from kir.clash_bundle import render_bundle_clash


def _make_run(root: pathlib.Path, name: str, *, doc: str,
              version: str, uid: str = "", age_s: float = 0.0) -> pathlib.Path:
    run = root / name
    run.mkdir(parents=True)
    passport = {"doc_name": doc, "revit_version": version}
    if uid:
        passport["document_identity"] = {"value": uid,
                                         "source": "project_information_unique_id"}
    (run / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
    (run / "L0.jsonl").write_text(
        json.dumps({"record": "document", "document": {"doc_name": doc}}) + "\n"
        + json.dumps({"record": "element", "element": {"element_id": "1"}}) + "\n",
        encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(run, (old, old))
    return run


class VersionIsPartOfTheChoice(unittest.TestCase):

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp())

    def test_the_same_version_wins_over_a_NEWER_run_of_another_version(self) -> None:
        """THE CORE OF THE FIX. A matching version beats file recency.

        FAIL CONTROL: remove `version_rank` from the sort key — and `newer_2023`
        wins, because it was written later. Verified by removal: without
        the fix this test turns red.
        """
        _make_run(self.root, "older_2026", doc="Проект1", version="2026",
                  age_s=3600)
        _make_run(self.root, "newer_2023", doc="Проект1", version="2023")
        run, why, fresh = E.resolve_run("Проект1", root=self.root,
                                        revit_version="2026")
        self.assertEqual(run.name, "older_2026", why)
        self.assertEqual(fresh.version_drift, "")

    def test_a_known_mismatch_loses_to_a_run_that_says_nothing(self) -> None:
        """Three states, not two: a mismatch is weaker than NOT KNOWING.

        Not knowing testifies neither for nor against; a known mismatch
        testifies AGAINST. Merging them would mean losing the only thing
        that still distinguishes documents in this corpus.
        """
        _make_run(self.root, "silent", doc="Проект1", version="", age_s=3600)
        _make_run(self.root, "mismatch", doc="Проект1", version="2019")
        run, _why, _f = E.resolve_run("Проект1", root=self.root,
                                      revit_version="2026")
        self.assertEqual(run.name, "silent")

    def test_the_drift_is_NAMED_not_swallowed(self) -> None:
        _make_run(self.root, "only_one", doc="Проект1", version="2023")
        run, _why, fresh = E.resolve_run("Проект1", root=self.root,
                                         revit_version="2026")
        self.assertEqual(run.name, "only_one",
                         "единственный кандидат ОТБРАКОВАН — апгрейд законен, "
                         "терять его нельзя")
        self.assertEqual(fresh.version_drift, "2023 -> 2026")
        self.assertIn("ДРУГОМ РЕВИТЕ", fresh.why)

    def test_silence_on_either_side_is_NOT_a_drift(self) -> None:
        """NARROWNESS CONTROL: "we don't know" does not turn into an accusation.

        Without it the instrument would shout at all 54 corpus decompiles whose
        version is not recorded — and the very first reader would learn to stop
        reading it.
        """
        _make_run(self.root, "a", doc="Проект1", version="")
        _, _why, fresh = E.resolve_run("Проект1", root=self.root,
                                       revit_version="2026")
        self.assertEqual(fresh.version_drift, "")
        _make_run(self.root, "b", doc="Другой", version="2023")
        _, _why2, fresh2 = E.resolve_run("Другой", root=self.root,
                                         revit_version="")
        self.assertEqual(fresh2.version_drift, "")


class IdentityStillRefutes(unittest.TestCase):
    """REGRESSION: what worked BEFORE the fix is required to work after."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp())

    def test_a_foreign_uid_is_refused_BY_NAME(self) -> None:
        _make_run(self.root, "foreign", doc="Проект1", version="2026",
                  uid="ЧУЖОЙ-UID")
        run, why, fresh = E.resolve_run("Проект1", root=self.root,
                                        project_uid="НАШ-UID",
                                        revit_version="2026")
        self.assertIsNone(run)
        self.assertIsNone(fresh)
        self.assertIn("РАСХОЖДЕНИЮ личности", why)

    def test_a_matching_uid_beats_a_newer_nameless_run(self) -> None:
        _make_run(self.root, "pedigree", doc="Проект1", version="2026",
                  uid="НАШ-UID", age_s=7200)
        _make_run(self.root, "nameless", doc="Проект1", version="2026")
        run, _why, fresh = E.resolve_run("Проект1", root=self.root,
                                         project_uid="НАШ-UID",
                                         revit_version="2026")
        self.assertEqual(run.name, "pedigree")
        self.assertEqual(fresh.matched_by, "project_information_unique_id")


class TheReceiptSaysWhichWorstCaseItIs(unittest.TestCase):
    """Two worst cases — two DIFFERENT lines, because the actions are different."""

    def _block(self, freshness: dict) -> dict:
        return {
            "schema": "kir-bundle-clash/1", "status": "ok", "scope_id": "x",
            "judgement_schema": "kir-clash-judgement/1",
            "bodies": 1, "pairs_compared": 1, "total_findings": 0,
            "findings": [], "disputes": 0, "filtered_by_rule": 0,
            "unjudged": 0, "without_body": 0, "elements_considered": 1,
            "ops_without_body": {}, "without_body_by_category": {},
            "no_geometry_reasons": {}, "blind_by_class": {},
            "filtered_by_slack": 0, "refused_by_rule": 0, "duplicates": 0,
            "overlaps": 0, "touches": 0, "op_id_collisions": {},
            "by_kind": {}, "by_origin": {}, "by_rung": {}, "by_host_state": {},
            "rung_actions": {}, "rules": [], "hosted_edges": 0,
            "search_complete": True, "delta_scope": "all", "delta_basis": "",
            "assertion": "", "type_sections": 0, "text_budget": 4000,
            "bodies_bundle": 1, "bodies_existing": 1, "elapsed_ms": 1,
            "without_body_on_mvp_side": 0, "filtered": 0,
            "compared_against": {"present": True, "source": "graph_check",
                                 "bodies": 1, "scanned": 1, "without_bbox": 0,
                                 "region": {"margin_mm": 0},
                                 "freshness": freshness},
        }

    def test_a_drift_adds_the_ANOTHER_DOCUMENT_line(self) -> None:
        text = render_bundle_clash(self._block({
            "proven": False, "matched_by": "doc_title", "age_days": 0.3,
            "why": "совпало ИМЯ", "version_drift": "2023 -> 2026"}), {})
        self.assertIn("ИСТОЧНИК СТОЯЩЕГО НЕ ДОКАЗАН", text)
        self.assertIn("МОЖЕТ БЫТЬ ВООБЩЕ ДРУГОЙ ДОКУМЕНТ", text)
        self.assertIn("2023", text)
        self.assertIn("2026", text)

    def test_without_a_drift_that_line_is_ABSENT(self) -> None:
        """CONTROL: a line that is always printed means nothing."""
        text = render_bundle_clash(self._block({
            "proven": False, "matched_by": "doc_title", "age_days": 0.3,
            "why": "совпало ИМЯ", "version_drift": ""}), {})
        self.assertIn("ИСТОЧНИК СТОЯЩЕГО НЕ ДОКАЗАН", text)
        self.assertNotIn("ВООБЩЕ ДРУГОЙ ДОКУМЕНТ", text)


if __name__ == "__main__":
    unittest.main()
