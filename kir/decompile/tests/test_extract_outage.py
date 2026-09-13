# -*- coding: utf-8 -*-
"""Tasks #26/#27: extraction survives the window going away for minutes.

The operator's network drops, the bridge socket dies with 1006 in the
middle of a multi-page extraction, the window comes back with a NEW
ws_id after seconds to minutes (measured 07-29 on 13A-RD-AR-K2, working
drawings, 18,492 elements: three runs died on a floating page, each had
to be restarted completely from scratch).

Already done before this wave: pages of 400 (KUKAI_IR_EXTRACT_BATCH),
re-resolving the window on every call, retry pauses (5, 20) — tolerates
~25 s.

Here there are two real fixes:

* #26 — when the page's retries are exhausted, the loop WAITS for the
  window to return and repeats the page; the budget is shared across the
  run, and once the ceiling is exhausted → the category becomes partial
  with a reason;
* #27 — a resume with partial categories RE-EXTRACTS them, rather than
  handing over the snapshot as-is (today this blocks the
  `snapshot_non_authoritative` run, leaving the operator with a full run
  under a new stamp).

All tests are refutational: each is red without its own fix.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from kir.decompile import extract as E
from kir.decompile.extract import (
    BridgeCallError, L0JSONLReader, extract_document)
from kir.decompile.schema import EXTRACT_BATCH, CategoryState
from kir.decompile.tests.fixtures_decompile import (
    FakeExtractBridge, project1_elements)


def _walls(count: int) -> dict[str, list[dict[str, Any]]]:
    """Walls only — a single category, so the drop hits a known spot."""
    rows = project1_elements()
    walls = [row for row in rows.get("OST_Walls", [])]
    if not walls:
        raise AssertionError("фикстура без стен")
    out = []
    for index in range(count):
        row = dict(walls[0])
        row["element_id"] = str(1000 + index)
        out.append(row)
    return {"OST_Walls": out}


def _checkpoint(output: Path) -> dict[str, Any]:
    path = output.with_suffix(output.suffix + ".checkpoint.json")
    return json.loads(path.read_text(encoding="utf-8"))


# Pauses in the tests are milliseconds: what is checked is the LOGIC of
# waiting, not the clock. RETRY pauses are patched together with WAIT
# pauses: the production (5, 20) s values would give 25 seconds per turn
# of waiting and would turn the suite into a half-hour one.
FAST = mock.patch.multiple(
    E, EXTRACT_WINDOW_WAIT_S=0.30, EXTRACT_WINDOW_POLL_S=0.01,
    EXTRACT_RETRY_BACKOFF_S=(0.001,))
NO_WAIT = mock.patch.multiple(
    E, EXTRACT_WINDOW_WAIT_S=0.0, EXTRACT_WINDOW_POLL_S=0.01,
    EXTRACT_RETRY_BACKOFF_S=(0.001,))


class WaitingForTheWindow(unittest.IsolatedAsyncioTestCase):
    """#26: a drop on page N → waiting → the window returns → complete."""

    async def test_a_returning_window_completes_the_category(self) -> None:
        rows = _walls(3)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outage.jsonl"
            # The window goes away on the first page of walls and returns
            # after several failed attempts — exactly the behavior of a
            # live drop.
            bridge = FakeExtractBridge(
                elements=rows, outage_for="OST_Walls",
                outage_after_pages=0, outage_calls=6)
            with FAST:
                result = await extract_document(
                    bridge, change_stamp="outage-heals", output_path=output)

            self.assertGreater(bridge.outage_raised, 0, "обрыва не было")
            self.assertEqual(result.partial_categories, (),
                             "категория обязана закрыться полной")
            self.assertIn("OST_Walls", result.completed_categories)
            self.assertEqual(result.element_count, 3)
            L0JSONLReader(output).validate()

    async def test_pre_state_without_waiting_the_category_is_buried(self) -> None:
        """PRE-STATE #26: without waiting, the same drop buries the category.

        The wait budget is zeroed out — leaving exactly yesterday's
        behavior: the retry budget (~25 s) burns up, and a run that
        would have survived the drop hands back partial. The very same
        bridge in the test above closes the category as complete.
        """
        rows = _walls(3)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "no-wait.jsonl"
            bridge = FakeExtractBridge(
                elements=rows, outage_for="OST_Walls",
                outage_after_pages=0, outage_calls=6)
            with NO_WAIT:
                result = await extract_document(
                    bridge, change_stamp="outage-no-wait", output_path=output)

            self.assertIn("OST_Walls", result.partial_categories)
            self.assertEqual(result.element_count, 0)

    async def test_an_outage_longer_than_the_cap_is_a_partial(self) -> None:
        """The ceiling is exhausted → partial WITH A REASON, no silent success."""
        rows = _walls(3)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "gone.jsonl"
            bridge = FakeExtractBridge(
                elements=rows, outage_for="OST_Walls",
                outage_after_pages=0, outage_calls=10_000)
            with FAST:
                result = await extract_document(
                    bridge, change_stamp="outage-forever", output_path=output)

            self.assertIn("OST_Walls", result.partial_categories)
            status = _checkpoint(output)["category_states"]["OST_Walls"]
            self.assertEqual(status, CategoryState.PARTIAL.value)
            # The reason must NAME the waiting, otherwise a reader of the
            # report will decide the bridge failed instantly.
            reason = next(
                row["status"]["error"]
                for row in (json.loads(line)
                            for line in output.read_text().splitlines())
                if row.get("record") == "category_status"
                and row["status"]["category"] == "OST_Walls")
            self.assertIn("окно не вернулось", reason)
            # The stream is still closed by the law: one footer, last.
            L0JSONLReader(output).validate()

    async def test_the_budget_is_shared_by_the_whole_run(self) -> None:
        """The budget is SHARED: a dead window costs the ceiling once, not per category.

        A per-page ceiling would multiply by the number of categories —
        a window closed forever would cost hours of illusory work
        instead of minutes.
        """
        budget = E._WindowWaitBudget(total_s=0.05)
        with mock.patch.object(E, "EXTRACT_WINDOW_POLL_S", 0.01):
            spent = 0
            while await budget.pause():
                spent += 1
            self.assertGreater(spent, 0)
            self.assertEqual(budget.remaining, 0.0)
            # An exhausted budget does not replenish itself.
            self.assertFalse(await budget.pause())

    async def test_revision_drift_is_never_waited_out(self) -> None:
        """A document change during the drop is a typed failure of the RUN.

        Waiting it out would mean choosing a different revision and
        passing off a mixed snapshot as successful.
        """
        from kir.decompile.pipeline import DocumentRevisionError

        calls = {"n": 0}

        async def drifting(code: str, *, timeout_ms: int) -> Any:
            calls["n"] += 1
            raise DocumentRevisionError("document changed during one bridge read")

        with FAST:
            with self.assertRaises(DocumentRevisionError):
                await E._execute_awaiting_window(
                    drifting, "code", timeout_ms=1000, retries=2,
                    budget=E._WindowWaitBudget(), what="проба")
        self.assertEqual(calls["n"], 1, "ревизию не ретраят и не пережидают")

    async def test_exhausted_wait_still_raises_bridge_call_error(self) -> None:
        """On the outside — still BridgeCallError: no new outcomes have been introduced."""
        async def dead(code: str, *, timeout_ms: int) -> Any:
            raise RuntimeError("bridge window is not connected (matches: 0)")

        with NO_WAIT:
            with self.assertRaises(BridgeCallError) as caught:
                await E._execute_awaiting_window(
                    dead, "code", timeout_ms=1000, retries=0,
                    budget=E._WindowWaitBudget(), what="страница OST_Walls")
        self.assertIn("окно не вернулось", str(caught.exception))


#: The envelope the server ACTUALLY returns when our own template fails
#: to compile. The shape is taken from
#: ``RevitExecutionPipeline.run_declarative`` (the
#: ``state = "compile_failed"`` branch) and ``envelope.attach_err``: a
#: bare ``error: True`` flag, human text in ``message``, a machine code
#: in ``err.code``. There is not a single ``ok`` in it — this is not a
#: bridge response, matters never reached the bridge.
COMPILE_FAILED_ENVELOPE = {
    "error": True,
    "message": (
        "Внутренняя ошибка: серверный шаблон decompile_read не "
        "скомпилировался — сообщи оператору. CS1503: Argument 1: cannot "
        "convert from 'long' to 'Autodesk.Revit.DB.BuiltInParameter' "
        "(line 103)"
    ),
    "err": {
        "code": "compile.cs_error",
        "retryable": True,
        "transient": False,
        "cs_codes": ["CS1503"],
    },
}


class OurOwnTemplateIsNotTheWindowsSilence(unittest.IsolatedAsyncioTestCase):
    """"The bridge is silent" and "we failed to compile what we were
    about to send" are different things.

    A LIVE CASE, 07-30. Decompiling a 59-story tower on R2023 printed,
    for an hour and a half, "window is not responding on side stage
    annotation batch 1/14 — waiting for return," while the service log
    kept cycling through ``TEMPLATE COMPILE FAILED ... CS1503 ...
    bridge_roundtrips=0``. The window was alive: it was OUR template that
    failed to compile. The waiting layer went looking for the cause in
    Revit — exactly where it was not.

    A compilation failure cannot be waited out, by construction: the
    same text will not start compiling because we waited. It must be an
    IMMEDIATE typed failure, like ``DocumentRevisionError``, not a
    transport failure inside the retry budget.

    All tests are refutational: each is red without its own fix.
    """

    def test_the_detail_survives_instead_of_a_bare_true(self) -> None:
        """The reason must carry a CS code and a message, not the string ``True``.

        The envelope unwrapper took ``current["error"]``, and what sits
        there is a BOOLEAN FLAG. What went out was
        ``ExtractionProtocolError: True`` — the one thing that cannot be
        googled, grepped, or understood.
        """
        with self.assertRaises(E.TemplateCompileError) as caught:
            E._unwrap_bridge_payload(dict(COMPILE_FAILED_ENVELOPE))
        detail = str(caught.exception)
        self.assertNotEqual(detail, "True")
        self.assertIn("CS1503", detail)
        self.assertIn("не скомпилировался", detail)

    async def test_a_template_compile_failure_is_not_a_transport_failure(
        self,
    ) -> None:
        """No retries, no waiting: one call and a typed failure."""
        calls = {"n": 0}

        async def refuses(code: str, *, timeout_ms: int) -> Any:
            calls["n"] += 1
            return dict(COMPILE_FAILED_ENVELOPE)

        # The budget is set EXPLICITLY: this directory's conftest zeroes
        # out the production 300 s, and the default budget could not
        # have proven that it was not spent.
        budget = E._WindowWaitBudget(total_s=0.05)
        with FAST:
            with self.assertRaises(E.TemplateCompileError):
                await E._execute_awaiting_window(
                    refuses, "code", timeout_ms=1000, retries=2,
                    budget=budget, what="боковая стадия annotation пачка 1/14")
        self.assertEqual(calls["n"], 1,
                         "нескомпилировавшийся шаблон не ретраят")
        self.assertEqual(budget.waits, 0, "и не пережидают")
        self.assertEqual(budget.remaining, 0.05,
                         "запас ожидания окна на это не тратится")

    async def test_a_silent_window_is_still_waited_out(self) -> None:
        """The separation runs in BOTH directions: real silence is still waited out."""
        async def dead(code: str, *, timeout_ms: int) -> Any:
            raise RuntimeError("bridge window is not connected (matches: 0)")

        budget = E._WindowWaitBudget(total_s=0.05)
        with FAST:
            with self.assertRaises(BridgeCallError):
                await E._execute_awaiting_window(
                    dead, "code", timeout_ms=1000, retries=0,
                    budget=budget, what="страница OST_Walls")
        self.assertGreater(budget.waits, 0, "молчание окна обязано ждаться")

    def test_a_runtime_refusal_is_still_a_protocol_error(self) -> None:
        """A Revit RUNTIME failure is not a compilation failure; the class does not blur."""
        envelope = {
            "error": True,
            "message": "Revit отказал: InvalidOperationException",
            "err": {"code": "runtime.revit_exception",
                    "retryable": False, "transient": False},
        }
        with self.assertRaises(E.ExtractionProtocolError) as caught:
            E._unwrap_bridge_payload(envelope)
        self.assertNotIsInstance(caught.exception, E.TemplateCompileError)
        self.assertIn("InvalidOperationException", str(caught.exception))

    async def test_the_run_names_it_a_compile_failure_not_an_extract_failure(
        self,
    ) -> None:
        """A run must call the defect by its own name in a typed failure."""
        from kir.decompile import pipeline as P

        async def refuses(code: str, *, timeout_ms: int = 0) -> Any:
            return dict(COMPILE_FAILED_ENVELOPE)

        with tempfile.TemporaryDirectory() as directory:
            with FAST:
                result = await P.run_decompile(
                    refuses, out_dir=directory, change_stamp="compile-fail")
        self.assertFalse(result.ok)
        self.assertEqual((result.error or {}).get("code"),
                         "template_compile_failed")
        self.assertIn("CS1503", json.dumps(result.to_dict(), ensure_ascii=False))


class ResumeFinishesPartials(unittest.IsolatedAsyncioTestCase):
    """#27: a resume re-extracts partials, rather than handing over the snapshot as-is."""

    async def _partial_run(self, directory: str) -> Path:
        output = Path(directory) / "partial.jsonl"
        bridge = FakeExtractBridge(
            elements=_walls(3), outage_for="OST_Walls",
            outage_after_pages=0, outage_calls=10_000)
        with FAST:
            result = await extract_document(
                bridge, change_stamp="resume-partial", output_path=output)
        self.assertIn("OST_Walls", result.partial_categories)
        self.assertTrue(_checkpoint(output)["footer_written"])
        return output

    async def test_resume_re_extracts_and_yields_an_authoritative_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = await self._partial_run(directory)
            before = json.loads(
                [line for line in output.read_text().splitlines()
                 if json.loads(line).get("record") == "footer"][0])
            self.assertEqual(before["element_count"], 0)

            # The window came back — the resume must RE-EXTRACT, not return as-is.
            healthy = FakeExtractBridge(elements=_walls(3))
            with FAST:
                result = await extract_document(
                    healthy, change_stamp="resume-partial",
                    output_path=output)

            self.assertTrue(result.resumed)
            self.assertEqual(result.partial_categories, ())
            self.assertIn("OST_Walls", result.completed_categories)
            self.assertEqual(result.element_count, 3)
            self.assertGreater(healthy.page_attempts["OST_Walls"], 0,
                               "резюм обязан был сходить за страницами")

    async def test_the_stream_keeps_exactly_one_footer_with_the_true_count(self):
        """`stream_complete` remains the law: one footer, last, honest.

        A second, "priority" footer would fix the counter and leave
        duplicate elements behind, while also introducing a second law
        alongside the first.
        """
        with tempfile.TemporaryDirectory() as directory:
            output = await self._partial_run(directory)
            with FAST:
                await extract_document(
                    FakeExtractBridge(elements=_walls(3)),
                    change_stamp="resume-partial", output_path=output)

            records = [json.loads(line)
                       for line in output.read_text().splitlines()]
            footers = [row for row in records if row.get("record") == "footer"]
            self.assertEqual(len(footers), 1)
            self.assertIs(records[-1], footers[0])
            self.assertTrue(footers[0]["stream_complete"])
            self.assertEqual(footers[0]["element_count"], 3)
            # Not a single duplicate: the category's elements sit exactly once.
            ids = [row["element"]["element_id"] for row in records
                   if row.get("record") == "element"]
            self.assertEqual(len(ids), len(set(ids)))
            L0JSONLReader(output).validate()

    async def test_a_complete_resume_does_no_work(self) -> None:
        """A resume of a complete snapshot must remain instantaneous."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "done.jsonl"
            with FAST:
                await extract_document(
                    FakeExtractBridge(elements=_walls(2)),
                    change_stamp="resume-done", output_path=output)
            idle = FakeExtractBridge(elements=_walls(2))
            with FAST:
                result = await extract_document(
                    idle, change_stamp="resume-done", output_path=output)
            self.assertTrue(result.resumed)
            self.assertEqual(result.partial_categories, ())
            self.assertEqual(idle.page_attempts["OST_Walls"], 0,
                             "полный снимок не смеет извлекаться заново")

    async def test_a_stream_disagreeing_with_the_checkpoint_is_refused(self):
        """The stream and the checkpoint disagree about completeness — a typed failure.

        Both sides describe ONE run; if they diverge, it is unknown
        which boundary is the real one, and "take the more complete one"
        would be a guess.
        """
        with tempfile.TemporaryDirectory() as directory:
            output = await self._partial_run(directory)
            path = output.with_suffix(output.suffix + ".checkpoint.json")
            state = json.loads(path.read_text(encoding="utf-8"))
            state["category_states"]["OST_Walls"] = CategoryState.PARTIAL.value
            # The stream says partial, the checkpoint says complete for a
            # different category where the stream never closed it at all.
            other = next(c for c in E.EXTRACT_CATEGORIES if c != "OST_Walls")
            state["category_states"][other] = CategoryState.PARTIAL.value
            path.write_text(json.dumps(state), encoding="utf-8")

            with FAST:
                with self.assertRaises(E.ExtractionProtocolError) as caught:
                    await extract_document(
                        FakeExtractBridge(elements=_walls(3)),
                        change_stamp="resume-partial", output_path=output)
            self.assertIn("stream says", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class ResumeNeverAppendsAGeneration(unittest.IsolatedAsyncioTestCase):
    """A rollforward after a PROCESS death does not append a second generation of rows.

    The suspicion arose on K2 (v5): the element counter grew 16,475 →
    32,379 → 52,605 → 55,293, and this looked like three generations
    appended on top of each other. Examining the artifact showed the
    opposite — 55,293 rows, 55,293 UNIQUE ids, one `category_status`
    entry per each of the 54 categories, the checkpoint and the file
    match byte for byte. The numbers were snapshots of ONE ongoing extraction.

    The test pins this down as a law, not as luck: a process drop in the
    middle of a category, a resume — and the file must not have a single
    duplicate.
    """

    async def _kill_and_resume(self, *, crash_after_pages: int) -> Path:
        from kir.decompile.tests.fixtures_decompile import (
            SyntheticBridgeCrash)
        rows = _walls(EXTRACT_BATCH * 2 + 5)
        directory = tempfile.mkdtemp()
        output = Path(directory) / "generations.jsonl"
        dying = FakeExtractBridge(
            elements=rows, crash_batch_for="OST_Walls",
            crash_after_pages=crash_after_pages)
        with FAST:
            with self.assertRaises(SyntheticBridgeCrash):
                await extract_document(
                    dying, change_stamp="generations", output_path=output)
        # The file is LONGER than the recorded boundary — there is an
        # uncommitted tail.
        self.assertGreater(
            output.stat().st_size, _checkpoint(output)["committed_offset"])
        with FAST:
            await extract_document(
                FakeExtractBridge(elements=rows),
                change_stamp="generations", output_path=output)
        return output

    async def test_no_duplicate_rows_after_resume(self) -> None:
        output = await self._kill_and_resume(crash_after_pages=1)
        records = [json.loads(line)
                   for line in output.read_text().splitlines()]
        ids = [row["element"]["element_id"] for row in records
               if row.get("record") == "element"]
        statuses = [row["status"]["category"] for row in records
                    if row.get("record") == "category_status"]
        self.assertEqual(len(ids), len(set(ids)), "дубли строк элементов")
        self.assertEqual(len(statuses), len(set(statuses)),
                         "категория закрыта дважды")
        self.assertEqual(
            len([r for r in records if r.get("record") == "header"]), 1)
        self.assertEqual(
            len([r for r in records if r.get("record") == "footer"]), 1)
        L0JSONLReader(output).validate()

    async def test_the_footer_counts_the_rows_that_are_actually_there(self):
        """The file-level law: the footer, the receipts, and the ROWS must reconcile."""
        output = await self._kill_and_resume(crash_after_pages=1)
        records = [json.loads(line)
                   for line in output.read_text().splitlines()]
        actual = sum(1 for r in records if r.get("record") == "element")
        footer = next(r for r in records if r.get("record") == "footer")
        by_status = sum(r["status"]["extracted_count"] for r in records
                        if r.get("record") == "category_status")
        self.assertEqual(footer["element_count"], actual)
        self.assertEqual(by_status, actual)
