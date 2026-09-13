"""A GATE THAT HAS NOTHING TO CHECK MUST SAY SO (F-315 · F-323 · E-9).

Both locks are declared with the words "zero violations ACROSS THE WHOLE
SAMPLE", while the decision was made ONLY from the numerator. The
denominator was computed and even printed — but did not enter the verdict,
and the instrument became THE GREENER THE FEWER CLUES IT HAD.

🔴 THIS IS A "GREEN, WORTHLESS CONTROL": the check "does it turn red on the
reverted fix" does NOT catch it — on a real sample it turns red for a
DIFFERENT reason. So the cases here are picked TO MATCH THE DEFECT'S SUBJECT
(each emptiness separately, none of them follows from the other two), and
next to each stands a case where the lock must OPEN — otherwise nothing
would tell a fix of "always closed" apart from a correct one.

The shapes hold to the precedent of `75220fb`
(`snapshot_janitor._verify_all`): the reason is printed FIRST, before the
numbers, and the return codes distinguish "the measurement DID HAPPEN and
found corruption" (1) from "there WAS NO measurement" (2). All three gates
in the tree must answer emptiness the same way: an operator learns the
behaviour of one and carries it over to the others.
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from kir.clash.tools import bundle_containment_gate as BG
from kir.clash.tools import wall_prism_gate as WG


HEADER = {"record": "header",
          "document": {"levels": [{"id": "L1", "elevation_mm": 0.0}]}}


def _write(directory: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "L0.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    return directory


# ── THE WALL-PRISM LOCK (F-323) ─────────────────────────────────────────────

WALL = {"element_id": 2, "category": "OST_Walls", "level_id": "L1",
        "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1000, 200, 3000],
        "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0], "params": {}}

FULL = {"WALL_ATTR_WIDTH_PARAM": 200.0, "WALL_USER_HEIGHT_PARAM": 3000.0}


class ЗамокПризмыНеОткрываетсяНаПустоте(unittest.TestCase):

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        patcher = mock.patch.object(WG, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, name: str, elements: list[dict]) -> dict:
        _write(self.root / name,
               [HEADER] + [{"record": "element", "element": e}
                           for e in elements])
        return WG.analyse(name)

    def test_no_walls_at_all_does_not_open_the_gate(self):
        row = self._run("A", [{"element_id": 1, "category": "OST_Floors"}])
        self.assertEqual(row["non_containing_diagnosis"]["count"], 0)
        self.assertFalse(row["gate_open"])
        self.assertIn("ни одной стены с габаритом", row["empty_evidence"])

    def test_walls_that_cannot_be_predicted_do_not_open_the_gate(self):
        """A second emptiness, and it does NOT follow from the first: the
        wall EXISTS, the bounding box EXISTS, and there is nothing to
        predict it with."""
        row = self._run("B", [dict(WALL)])
        self.assertEqual(row["target_population"]
                         ["ground_truth_walls_with_bbox"], 1)
        self.assertEqual(row["judged"], 0)
        self.assertEqual(row["non_containing_diagnosis"]["count"], 0)
        self.assertFalse(row["gate_open"])
        self.assertIn("не предсказуема", row["empty_evidence"])

    def test_a_real_breach_closes_the_gate_for_its_own_reason(self):
        """The lock was closed BEFORE the fix too, and must remain closed —
        but for a VIOLATION, not for emptiness: reasons are not substituted
        for each other."""
        row = self._run("C", [dict(WALL, element_id=3,
                                   bbox_min_mm=[-5000, -5000, 0],
                                   bbox_max_mm=[6000, 5000, 3000],
                                   params=dict(FULL))])
        self.assertEqual(row["non_containing_diagnosis"]["count"], 1)
        self.assertIsNone(row["empty_evidence"])
        self.assertFalse(row["gate_open"])

    def test_a_contained_prediction_still_opens_the_gate(self):
        """🔴 THE SECOND OUTCOME. Without it, a fix of "always closed" is
        indistinguishable from a correct one: it would pass all three cases
        above."""
        row = self._run("D", [dict(WALL, element_id=4,
                                   bbox_min_mm=[10, -50, 10],
                                   bbox_max_mm=[990, 50, 2990],
                                   params=dict(FULL))])
        self.assertEqual(row["judged"], 1)
        self.assertEqual(row["non_containing_diagnosis"]["count"], 0)
        self.assertIsNone(row["empty_evidence"])
        self.assertTrue(row["gate_open"])

    def test_a_legal_zero_width_is_judged_and_not_skipped(self):
        """A width of 0 is a prediction of zero thickness, not "nothing to
        predict with". Falling through to a skip, it was dragging the
        sample toward emptiness."""
        row = self._run("E", [dict(WALL, element_id=5,
                                   bbox_min_mm=[0, -100, 0],
                                   bbox_max_mm=[1000, 100, 3000],
                                   params={"WALL_ATTR_WIDTH_PARAM": 0.0,
                                           "WALL_USER_HEIGHT_PARAM": 3000.0})])
        self.assertEqual(row["formula_variants"][WG.BEST]["skipped_no_data"], 0)
        self.assertEqual(row["judged"], 1)
        self.assertIsNone(row["empty_evidence"])

    def test_the_three_outcomes_have_three_return_codes(self):
        """Before, `main` returned 0 ALWAYS: the lock could not be put into
        a pipeline at all. The codes are taken from `snapshot_janitor`
        (`75220fb`)."""
        self._run("RC_empty", [{"element_id": 1, "category": "OST_Floors"}])
        self._run("RC_breach", [dict(WALL, element_id=3,
                                     bbox_min_mm=[-5000, -5000, 0],
                                     bbox_max_mm=[6000, 5000, 3000],
                                     params=dict(FULL))])
        self._run("RC_open", [dict(WALL, element_id=4,
                                   bbox_min_mm=[10, -50, 10],
                                   bbox_max_mm=[990, 50, 2990],
                                   params=dict(FULL))])
        art = mock.patch.object(WG, "ART", self.root / "art")
        art.start()
        self.addCleanup(art.stop)
        for run, want in (("RC_empty", 2), ("RC_breach", 1), ("RC_open", 0)):
            with self.subTest(run=run):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = WG.main([run])
                self.assertEqual(code, want)
                if want == 2:
                    # The reason must stand as the FIRST line of the run's block.
                    body = buf.getvalue().split("### RC_empty\n", 1)[1]
                    self.assertTrue(
                        body.lstrip().startswith("🔴 ЗАМЕР НЕ СОСТОЯЛСЯ:"),
                        "причина не первой строкой: %r" % body[:200])


# ── THE CONTAINMENT LOCK (F-315) and the level id (E-9) ─────────────────────

def _hull(lo, hi):
    return types.SimpleNamespace(bounds=lambda: (lo, hi))


def _records(*specs):
    return types.SimpleNamespace(records=[
        types.SimpleNamespace(source_id=sid, category="OST_Walls",
                              hull_source="prism", hull=_hull(lo, hi))
        for sid, lo, hi in specs])


class ЗамокСодержанияНеПропускаетПриНулеУлик(unittest.TestCase):

    #: 🔴 THE LEVEL ID IS DELIBERATELY NON-NUMERIC (E-9): the language accepts
    #: any non-empty string, and in a federated model the address has the
    #: form `<model>::<id>`. Before the fix, `int(lid)` dropped the gate with
    #: a ValueError BEFORE the verdict — the instrument did not say "did not
    #: check", it never got as far as a word at all.
    ELEMENT = {"element_id": 101, "category": "OST_Walls", "type_id": "W-EXT",
               "type_name": "T", "level_id": "L1",
               "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1000, 200, 3000],
               "params": {"WALL_ATTR_WIDTH_PARAM": 200.0,
                          "WALL_CROSS_SECTION": 1.0}}

    def setUp(self):
        self.run = _write(pathlib.Path(tempfile.mkdtemp()) / "synthetic",
                          [HEADER, {"record": "element",
                                    "element": dict(self.ELEMENT)}])

    @contextlib.contextmanager
    def _wired(self, programs, snap):
        empty = types.SimpleNamespace(elements=[], profiles={}, no_geometry={})
        with mock.patch.object(BG, "_resolve", lambda run: self.run), \
             mock.patch.object(BG, "materialise", lambda d: programs), \
             mock.patch("kir.clash_bundle.bundle_elements",
                        lambda *a, **k: empty), \
             mock.patch("kir.clash.snapshot.build_from_elements",
                        lambda *a, **k: snap):
            yield

    def _gate(self, programs, snap):
        with self._wired(programs, snap):
            return BG.gate(str(self.run))

    def test_a_non_numeric_level_id_no_longer_drops_the_gate(self):
        """E-9. The measurement must HAPPEN on a legitimate non-numeric id."""
        snapshot, _ = BG.derive_sections({"L1": 0.0, "1-lnk-a": 3000.0},
                                         [dict(self.ELEMENT)])
        self.assertEqual([r["id"] for r in snapshot["levels"]],
                         ["1-lnk-a", "L1"])
        self.assertEqual([r["id"] for r in snapshot["wall_types"]], ["W-EXT"])

    def test_a_numeric_level_id_survives_the_change(self):
        """🔴 THE SECOND OUTCOME OF E-9: a numeric id must still work as
        before, and the consumer must see THE SAME key. Without this case,
        a fix of "throw out levels entirely" would have passed the previous
        check."""
        from kir.clash_bundle import SnapshotSections
        snapshot, _ = BG.derive_sections({"1": 0.0}, [])
        self.assertEqual(snapshot["levels"],
                         [{"id": "1", "name": "1", "elevation_mm": 0.0}])
        index = SnapshotSections.from_snapshot(snapshot)
        self.assertEqual(dict(index.levels),
                         {"element_id:1": 0.0, "name:1": 0.0})

    def test_no_programs_at_all_does_not_pass(self):
        row = self._gate([], _records())
        self.assertEqual(row["violations"], {})
        self.assertEqual(row["gate"], "FAIL")
        self.assertIn("ни одной программы", row["empty_evidence"])

    def test_programs_without_bodies_do_not_pass(self):
        row = self._gate([{"ops": []}], _records())
        self.assertEqual(row["gate"], "FAIL")
        self.assertIn("НОЛЬ тел", row["empty_evidence"])

    def test_bodies_that_never_join_the_source_do_not_pass(self):
        """A third emptiness: the bodies EXIST, but none of them matched by
        `source_id`. None of the three follows from the other two, which is
        why they are checked separately."""
        row = self._gate([{"ops": []}],
                         _records(("prog/xNOTANID", [0, 0, 0], [1, 1, 1]),
                                  ("prog/xNOTANID", [0, 0, 0], [1, 1, 1])))
        self.assertEqual(row["bodies"], 2)
        self.assertEqual(row["checked_total"], 0)
        self.assertEqual(row["unjoined"], 2)
        self.assertEqual(row["gate"], "FAIL")
        self.assertIn("НИ ОДНО не сошлось", row["empty_evidence"])

    def test_a_real_breach_fails_for_its_own_reason(self):
        row = self._gate([{"ops": []}],
                         _records(("prog/e101", [0, 0, 0], [500, 200, 3000])))
        self.assertEqual(row["checked_total"], 1)
        self.assertEqual(row["violations"], {"OST_Walls/prism": 1})
        self.assertIsNone(row["empty_evidence"])
        self.assertEqual(row["gate"], "FAIL")

    def test_a_containing_hull_still_passes(self):
        """🔴 THE SECOND OUTCOME. The lock has not been turned into "always FAIL"."""
        row = self._gate(
            [{"ops": []}],
            _records(("prog/e101", [-1, -1, -1], [1001, 201, 3001])))
        self.assertEqual(row["checked_total"], 1)
        self.assertEqual(row["violations"], {})
        self.assertIsNone(row["empty_evidence"])
        self.assertEqual(row["gate"], "PASS")

    def test_the_three_outcomes_have_three_return_codes(self):
        cases = (([], _records(), 2),
                 ([{"ops": []}],
                  _records(("prog/e101", [0, 0, 0], [500, 200, 3000])), 1),
                 ([{"ops": []}],
                  _records(("prog/e101", [-1, -1, -1], [1001, 201, 3001])), 0))
        for programs, snap, want in cases:
            with self.subTest(want=want):
                buf = io.StringIO()
                with self._wired(programs, snap), \
                        contextlib.redirect_stdout(buf):
                    code = BG.main([str(self.run)])
                self.assertEqual(code, want)
                if want == 2:
                    lines = [x.strip() for x in buf.getvalue().splitlines()]
                    self.assertTrue(
                        lines[1].startswith("🔴 СВЕРКА НЕ СОСТОЯЛАСЬ:"),
                        "причина не первой строкой: %r" % lines[:3])


if __name__ == "__main__":
    unittest.main()
