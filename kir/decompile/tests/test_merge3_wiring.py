"""The `merge3` wire: a guard between a delta and the document it will land on.

The `merge3` layer sat on the shelf as 420 lines and 20 tests, and all 20
checked WHAT it computes: T-MERGE, symmetry, conflict kinds, the source-id
bridge. Not one checked whether even a single live input reaches it — so
the shelf was invisible from inside the tests. This file checks exactly the
second thing, and only that.

The wire's placement was chosen not by taste but by a NAMED HOLE: the delta
rebuild says of itself, "the delta is correct only if the document already
carries the base building; the compiler cannot check this offline." This is
the one point where a live rebuild can produce a SILENTLY WRONG outcome —
building a diff on top of a document the operator had meanwhile edited, and
saying nothing about it. A fresh decompile of the same document makes the
condition measurable.

Four laws:

* **inertness** — without `current_doc_stamp` the rebuild must give the SAME
  chunks and the same report as before this wave, whatever the flag's
  position;
* **a conflict is a REFUSAL, not a warning** — two edits to the same thing
  mean the delta would erase someone's work; only someone who explicitly
  said `allow_conflicts` may survive it;
* **"verified" is written only where it was verified** — the document's
  state matched the base, and only then;
* **comparing the target with itself is forbidden** — it always yields "no
  conflicts", and that false "verified" is worse than an honest "not
  verified".
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import tempfile
import unittest
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_merge3_wiring_queue.jsonl"))

from kir import serving  # noqa: E402
from kir.decompile.merge3 import merge_enabled  # noqa: E402
from kir.decompile.merge_guard import (  # noqa: E402
    GUARD_SCHEMA,
    VERDICT_CLEAN,
    VERDICT_CONFIRMED,
    VERDICT_CONFLICTING,
    guard_refusal,
    guard_report,
)
from kir.decompile.tests.fixtures_decompile import make_element  # noqa: E402
from kir.decompile.tests.test_merkle import (  # noqa: E402
    _document,
    _fold,
    _grid_building,
    _on_level,
    _wall,
)

_LEVEL = ("100", "Этаж 1", 0.0)


def _walls_doc(name: str, *walls: tuple[int, float]):
    """A building made of exactly the named walls `(source id, length)` + three items."""

    elements = [_wall(eid, _LEVEL, (0, 0, 0), (length, 0, 0))
                for eid, length in walls]
    for index in range(3):
        row = _on_level(
            make_element("OST_Furniture", 600 + index, ordinal=0), _LEVEL)
        row.update({
            "geom_kind": "point", "p0_mm": [index * 500.0, 2000.0, 0.0],
            "p1_mm": None, "rotation_deg": 0.0,
            "bbox_min_mm": [index * 500.0, 1900.0, 0.0],
            "bbox_max_mm": [index * 500.0 + 300.0, 2100.0, 800.0]})
        elements.append(row)
    return _fold(_document([_LEVEL], elements, name=name))

_FLAG = "KUKAI_IR_MERGE3"
_REBUILD = "KUKAI_IR_REBUILD"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _ShimLLM:
    _revit_version = "2026"

    async def _repair_code(self, *a: Any, **k: Any) -> None:
        return None


async def _never_bridge(method: str, params: dict) -> dict:  # pragma: no cover
    raise AssertionError("мост не смеет вызываться в сухом прогоне")


# ───────────────────────────────────────────────────────────────────────────
# The guard itself: the three outcomes must be DISTINGUISHABLE
# ───────────────────────────────────────────────────────────────────────────


class GuardVerdicts(unittest.TestCase):
    def test_flag_is_off_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            self.assertFalse(merge_enabled())

    def test_an_untouched_document_confirms_the_precondition(self) -> None:
        base = _fold(_grid_building(floors=3))
        report = guard_report(
            base, _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=3, extra_furniture_on_floor=1)))
        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], VERDICT_CONFIRMED)
        self.assertTrue(report["identical_to_base"])
        self.assertEqual(report["conflicts_total"], 0)

    def test_a_document_that_moved_without_arguing_is_not_confirmed(
            self) -> None:
        """`diverged_clean` is not "verified". The base condition is NOT satisfied."""

        report = guard_report(
            _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=3, extra_furniture_on_floor=1)),
            _fold(_grid_building(floors=3, stretch_wall_on_floor=2)))
        self.assertEqual(report["verdict"], VERDICT_CLEAN)
        self.assertFalse(report["identical_to_base"])
        self.assertEqual(report["conflicts_total"], 0)
        self.assertGreater(report["auto_merged"], 0)

    def test_two_edits_of_the_same_thing_are_named_conflicts(self) -> None:
        report = guard_report(
            _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=2)),
            _fold(_grid_building(floors=4)))
        self.assertEqual(report["verdict"], VERDICT_CONFLICTING)
        self.assertGreater(report["conflicts_total"], 0)
        self.assertTrue(report["conflicts"],
                        "конфликты посчитаны, но ни один не назван — по "
                        "отчёту нельзя понять, ЧТО именно сотрут")
        self.assertEqual(
            sum(report["conflicts_by_kind"].values()),
            report["conflicts_total"])

    def test_the_full_count_survives_the_sample_cut(self) -> None:
        """The LIST is truncated, not the NUMBER: a truncated number would lie about the building."""

        report = guard_report(
            _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=2)),
            _fold(_grid_building(floors=4)))
        self.assertLessEqual(report["conflicts_shown"],
                             report["conflicts_total"])
        self.assertEqual(len(report["conflicts"]), report["conflicts_shown"])

    def test_one_element_with_two_bodies_reaches_the_operator(self) -> None:
        """F-292 reaches the report instead of drowning between two additions.

        The operator created element 500 in the document, while the delta
        builds ITS OWN element 500 of a different length. Before this wave
        the guard said `diverged_clean`: there was no identity bridge for an
        id absent from the ancestor, and the multiset read two unrelated
        additions. "Clean" here meant "we will silently build a second
        physical element on top of someone else's".
        """

        report = guard_report(
            _walls_doc("O"),
            _walls_doc("current", (500, 6500.0)),
            _walls_doc("target", (500, 7000.0)))
        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], VERDICT_CONFLICTING)
        self.assertEqual(report["conflicts_by_kind"].get("add_add"), 1)
        self.assertEqual(report["conflicts"][0]["source_id"], "500")
        self.assertNotEqual(report["conflicts"][0]["current"],
                            report["conflicts"][0]["target"])

    def test_two_authors_deleting_two_lookalikes_leaves_nothing(self) -> None:
        """F-295: base multiplicity 2, each side deleted THEIR OWN wall — zero remains.

        Checked on the product side, not only the layer: the verdict must
        remain `diverged_clean` (there is no dispute), but the state must be
        wall-free.
        """

        base = _walls_doc("O", (500, 6000.0), (501, 6000.0))
        report = guard_report(base, _walls_doc("current", (501, 6000.0)),
                              _walls_doc("target", (500, 6000.0)))
        self.assertEqual(report["verdict"], VERDICT_CLEAN)
        self.assertEqual(report["conflicts_total"], 0)
        # 🔴 A NUMBER, NOT A VERDICT. The guard does not hand out the merged
        # state — it does not even build one — so "zero walls" cannot be
        # asked directly here. Its one number that MOVES from this fix is
        # the edit count: two deletions, while the multiset saw one. Without
        # it the test would be green under a live defect (the `clean`
        # verdict is correct in both cases), i.e. it would check nothing.
        self.assertEqual(report["auto_merged"], 2,
                         "два автора удалили ДВЕ стены; счёт 1 означает, что "
                         "одно удаление потерялось между неразличимыми")

    def test_all_three_verdicts_are_still_reachable(self) -> None:
        """Three outcomes, not two: a fix has no right to close off any one of them.

        Named by NUMBER in one test, so that "it got stricter" could not be
        passed off as success: three different verdicts on three triples.
        """

        verdicts = {
            guard_report(_fold(_grid_building(floors=3)),
                         _fold(_grid_building(floors=3)),
                         _fold(_grid_building(
                             floors=3, extra_furniture_on_floor=1)))["verdict"],
            guard_report(_fold(_grid_building(floors=3)),
                         _fold(_grid_building(
                             floors=3, extra_furniture_on_floor=1)),
                         _fold(_grid_building(
                             floors=3, stretch_wall_on_floor=2)))["verdict"],
            guard_report(_fold(_grid_building(floors=3)),
                         _fold(_grid_building(floors=2)),
                         _fold(_grid_building(floors=4)))["verdict"],
        }
        self.assertEqual(
            verdicts,
            {VERDICT_CONFIRMED, VERDICT_CLEAN, VERDICT_CONFLICTING})

    def test_a_refusal_is_not_a_clean_merge(self) -> None:
        report = guard_report({"kind": "building"}, {}, {})
        self.assertFalse(report["ok"])
        self.assertEqual(report["schema"], GUARD_SCHEMA)
        self.assertNotIn("verdict", report,
                         "сломанный страж выдал вердикт — «посчитать не "
                         "удалось» стало неотличимо от «конфликтов нет»")
        self.assertFalse(guard_refusal(ValueError("х"))["ok"])


# ───────────────────────────────────────────────────────────────────────────
# The live input: `handle_revit_rebuild` ← `api/admin_kir.py::rebuild`
# ───────────────────────────────────────────────────────────────────────────


class ServingWiring(unittest.TestCase):
    def setUp(self) -> None:
        # 🔴 BOTH GATE CONDITIONS ARE OPENED (2026-08-28). Only the MODE
        # used to be set here, while `serving.ADMIN_DEVICE` is not a
        # constant: it is derived from `KUKAI_ADMIN_DEVICES` at call time
        # and equals `None` when the list is empty (the fallback was
        # removed 2026-08-15). The mock returned `None`, the gate refused,
        # and the refusal was blamed on the MODE, which was in fact
        # enabled.
        os.environ["KUKAI_ADMIN_DEVICES"] = "dev-набор"
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        os.environ.pop("KUKAI_IR_ATOM_ESCROW", None)
        self._dev = mock.patch.object(
            serving, "_turn_device_id", return_value="dev-набор")
        self._dev.start()
        self._tmp = TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._dev.stop()
        self._tmp.cleanup()
        for flag in (_FLAG, _REBUILD, "KUKAI_KIR_DECOMPILE",
                     "KUKAI_ADMIN_DEVICES"):
            os.environ.pop(flag, None)

    def _persist(self, stamp: str, tree) -> None:
        directory = self.root / stamp
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tree.json").write_text(
            json.dumps(tree), encoding="utf-8")

    def _out_dir(self, stamp: str) -> str:
        return str(self.root / stamp)

    def _rebuild(self, args: dict) -> dict:
        with mock.patch.object(serving, "_decompile_out_dir", self._out_dir):
            return _run(serving.handle_revit_rebuild(
                {"dry_run": True, **args}, _ShimLLM(), _never_bridge))

    def _triple(self, *, ours_floors: int = 3, theirs_extra: bool = True,
                ours_extra: bool = False) -> None:
        self._persist("base", _fold(_grid_building(floors=3)))
        self._persist("now", _fold(_grid_building(
            floors=ours_floors,
            extra_furniture_on_floor=1 if ours_extra else None)))
        self._persist("target", _fold(_grid_building(
            floors=3,
            extra_furniture_on_floor=1 if theirs_extra else None,
            stretch_wall_on_floor=None if theirs_extra else 2)))

    # -- inertness ------------------------------------------------------------
    def test_without_the_current_stamp_nothing_changes(self) -> None:
        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1"}, clear=False):
            os.environ.pop(_FLAG, None)
            off = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            on = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        self.assertTrue(off["ok"], msg=off)
        self.assertTrue(on["ok"], msg=on)
        self.assertEqual(off["chunks_total"], on["chunks_total"])
        self.assertNotIn("merge_guard", off["delta"])
        self.assertNotIn("merge_guard", on["delta"],
                         "флаг включили — и страж заговорил сам, без "
                         "current_doc_stamp: это уже не приложение, а "
                         "изменение поведения пересборки")
        self.assertNotIn("precondition_verified", off["delta"])

    # -- refusals ---------------------------------------------------------------
    def test_the_guard_with_the_flag_off_is_refused_by_name(self) -> None:
        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1"}, clear=False):
            os.environ.pop(_FLAG, None)
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "merge_guard_disabled")
        self.assertNotIn("chunks_total", result,
                         "отказ протащил за собой пересборку — просили "
                         "проверку, а построили бы вслепую")

    def test_a_current_stamp_without_a_base_is_meaningless(self) -> None:
        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild(
                {"doc_stamp": "target", "current_doc_stamp": "now"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "args")

    def test_comparing_the_target_with_itself_is_refused(self) -> None:
        """A false "verified" is worse than an honest "not verified"."""

        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "target"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "args")

    def test_a_missing_current_decompile_is_refused(self) -> None:
        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "нет-такого"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_current_decompile")

    # -- three outcomes on a live input ---------------------------------------
    def test_an_untouched_document_turns_the_precondition_into_a_measurement(
            self) -> None:
        """What all of this is for: a promise becomes a check."""

        self._triple()
        self._persist("now", _fold(_grid_building(floors=3)))
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now"})
        self.assertTrue(result["ok"], msg=result)
        delta = result["delta"]
        self.assertTrue(delta["precondition_verified"])
        self.assertEqual(delta["merge_guard"]["verdict"], VERDICT_CONFIRMED)
        self.assertIn("проверено", delta["precondition_ru"])
        self.assertIn("chunks_total", result,
                      "проверка прошла, а пересборка всё равно отказана — "
                      "страж обязан пропускать то, что подтвердил")

    def test_a_clean_divergence_builds_but_does_not_claim_verification(
            self) -> None:
        self._triple(ours_extra=True, theirs_extra=False)
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now"})
        self.assertTrue(result["ok"], msg=result)
        delta = result["delta"]
        self.assertEqual(delta["merge_guard"]["verdict"], VERDICT_CLEAN)
        self.assertFalse(delta["precondition_verified"],
                         "документ ушёл от базы, а отчёт называет условие "
                         "проверенным — это ровно то враньё, ради которого "
                         "страж и заведён")
        self.assertIn("НЕ здание", delta["precondition_ru"])

    def test_conflicts_refuse_the_rebuild_instead_of_overwriting(self) -> None:
        """The wave's refuting test: without the guard this is a silent overwrite."""

        self._persist("base", _fold(_grid_building(floors=3)))
        self._persist("now", _fold(_grid_building(floors=2)))
        self._persist("target", _fold(_grid_building(floors=4)))
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            guarded = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now"})
            blind = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        self.assertFalse(guarded["ok"])
        self.assertEqual(guarded["error"], "merge_conflicts")
        self.assertEqual(guarded["merge_guard"]["verdict"], VERDICT_CONFLICTING)
        self.assertNotIn("chunks_total", guarded)
        # And without the guard — the same rebuild goes through silently.
        # This is exactly the silently wrong outcome the wave closes off.
        self.assertTrue(blind["ok"], msg=blind)
        self.assertGreater(blind["chunks_total"], 0)
        self.assertNotIn("merge_guard", blind["delta"])

    def test_conflicts_may_be_accepted_but_never_hidden(self) -> None:
        self._persist("base", _fold(_grid_building(floors=3)))
        self._persist("now", _fold(_grid_building(floors=2)))
        self._persist("target", _fold(_grid_building(floors=4)))
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now", "allow_conflicts": True})
        self.assertTrue(result["ok"], msg=result)
        guard = result["delta"]["merge_guard"]
        self.assertGreater(guard["conflicts_total"], 0,
                           "согласие стёрло конфликты из отчёта — согласие "
                           "касается решения, а не измерения")
        self.assertFalse(result["delta"]["precondition_verified"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
