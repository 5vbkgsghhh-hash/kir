"""A DECOMPILE BACKGROUND JOB THAT DIED BEFORE THE FIRST PAGE IS NAMED IN
status.json.

🔴 MEASURED 08.09.2026 on the owner's live Revit. `handle_revit_decompile`'s
`start` answered twice with «прогон запущен — опрашивай action=status», the
background job was dying before the first page, and `status` answered
`None` twice (meaning "there is no active run"): no file, no directory, not
a line in the log. `asyncio.ensure_future` with no observer of the
exception is a falsely green receipt. Here: a dead background job leaves
`stage: failed` with the exception's name; a live background job with no
file yet leaves `stage: starting`. Controls: with no observer (remove
`add_done_callback`) the first test is red; with no "starting" branch, the
second one is.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from kir import serving
from kir.decompile.tests.test_serving_decompile import (
    _ShimLLM, _never_bridge, _run, _открыть_ворота)


class ADeadRunIsNamed(TestCase):
    def setUp(self):
        self.DEVICE = _открыть_ворота(self)
        self._dev = mock.patch.object(serving, "_turn_device_id", return_value=self.DEVICE)
        self._dev.start(); self.addCleanup(self._dev.stop)
        serving._active_run.clear(); self.addCleanup(serving._active_run.clear)
        self.tmp = tempfile.mkdtemp(prefix="dead-run-")
        self._out = mock.patch.object(serving, "_decompile_out_dir",
                                      side_effect=lambda stamp: str(Path(self.tmp) / stamp))
        self._out.start(); self.addCleanup(self._out.stop)

    def test_a_run_that_dies_before_its_first_status_is_named(self):
        async def _dying_run(executor, *, out_dir, change_stamp, **kw):
            raise RuntimeError("bridge dead before the first page")

        async def _drive():
            with mock.patch("kir.decompile.pipeline.run_decompile", _dying_run):
                first = await serving.handle_revit_decompile(
                    {"action": "start", "doc_stamp": "docDead"}, _ShimLLM(), _never_bridge)
                task = serving._active_run.get("task")
                try:
                    await asyncio.wait_for(task, timeout=10)
                except Exception:  # noqa: BLE001 — the background job's exception is exactly the subject
                    pass
                await asyncio.sleep(0)  # let the observer fire
                status = await serving.handle_revit_decompile(
                    {"action": "status", "doc_stamp": "docDead"}, _ShimLLM(), _never_bridge)
                return first, status

        first, status = _run(_drive())
        self.assertTrue(first["ok"] and first["started"], first)
        self.assertIsNotNone(status["status"], "умерший фон остался без следа — «нет активного прогона»")
        self.assertEqual(status["status"]["stage"], "failed", status)
        self.assertIn("bridge dead before the first page", status["status"]["error"])
        self.assertTrue(status["status"]["background_died"])

    def test_a_live_run_without_a_file_yet_is_starting_not_absent(self):
        started = asyncio.Event()

        async def _slow_run(executor, *, out_dir, change_stamp, **kw):
            started.set()
            await asyncio.sleep(5)

        async def _drive():
            with mock.patch("kir.decompile.pipeline.run_decompile", _slow_run):
                first = await serving.handle_revit_decompile(
                    {"action": "start", "doc_stamp": "docSlow"}, _ShimLLM(), _never_bridge)
                await asyncio.wait_for(started.wait(), timeout=10)
                status = await serving.handle_revit_decompile(
                    {"action": "status", "doc_stamp": "docSlow"}, _ShimLLM(), _never_bridge)
                task = serving._active_run.get("task")
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                await asyncio.sleep(0)
                after = await serving.handle_revit_decompile(
                    {"action": "status", "doc_stamp": "docSlow"}, _ShimLLM(), _never_bridge)
                return first, status, after

        first, status, after = _run(_drive())
        self.assertTrue(first["ok"], first)
        self.assertEqual(status["status"]["stage"], "starting", status)
        self.assertTrue(status["status"]["background_alive"])
        self.assertEqual(after["status"]["stage"], "cancelled", after)
