"""Running a decompile has no right to make the server dead for everyone else.

LIVE MEASUREMENT, 2026-07-30. During a tower extraction, ``/health`` did not
respond TWELVE times in a row, 25 seconds each — a minute earlier the same
request answered in 2 ms. The backend runs on one worker
(``uvicorn --workers 1``), and after reading, the pipeline does heavy
SYNCHRONOUS work right in the event loop: materializing 88 MB of L0, parsing
an 18 MB side index, lift, fold, verify, passport serialization. For these
minutes the server answers NOBODY: chat sockets get no answer to their ping
and drop with close_code=1006 (62 disconnects in 12 hours across ten
different devices), HTTP hangs.

The operator's complaint sounded like "every so often the server drops out".
It is not "every so often" — it is every single time someone runs a
decompile.

The tests below do not measure time (on a five-element synthetic fixture
there is nothing to measure) — they require a STRUCTURAL property: a heavy
step must NOT run on the event loop's thread. The property is checkable and
does not depend on the model's size.
"""
from __future__ import annotations

import asyncio
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kir.decompile import pipeline as pipe
from kir.decompile.tests.test_pipeline import FakePipelineBridge, _run


class LoopNotStarvedTests(unittest.TestCase):
    """Every heavy step is named explicitly: forgetting one brings the defect back."""

    #: Name in ``pipeline`` -> a human-readable step name. The list is OPEN
    #: by design: a new heavy step appears — add a line, or it will ride the
    #: event loop and nobody will notice until the sockets drop.
    HEAVY_STEPS = {
        "cached_lift_document_detailed": "лифт",
        "fold_document": "свёртка",
        "name_document": "именование",
        "verify_document": "verify",
        "build_passport": "паспорт",
        "_persist_core_artifacts": "сериализация артефактов",
        "build_dependency_manifest": "манифест зависимостей",
        "reconcile_census": "перепись",
    }

    def _threads_of(self, step: str) -> list[str]:
        seen: list[str] = []
        original = getattr(pipe, step)

        def spy(*args, **kwargs):
            seen.append(threading.current_thread().name)
            return original(*args, **kwargs)

        setattr(pipe, step, spy)
        try:
            with TemporaryDirectory() as tmp:
                result = _run(pipe.run_decompile(
                    FakePipelineBridge(), out_dir=tmp,
                    change_stamp="pipeline-mini-v1"))
                self.assertTrue(result.ok, msg=result.to_dict())
        finally:
            setattr(pipe, step, original)
        return seen

    def test_every_heavy_step_runs_off_the_event_loop_thread(self) -> None:
        main = threading.main_thread().name
        for step, human in self.HEAVY_STEPS.items():
            with self.subTest(step=step):
                threads = self._threads_of(step)
                self.assertTrue(threads, f"{human}: шаг не вызвался вовсе")
                for name in threads:
                    self.assertNotEqual(
                        name, main,
                        f"{human} исполняется в потоке цикла событий — "
                        f"на большой модели это минуты мёртвого сервера")

    def test_l0_materialize_runs_off_the_event_loop_thread(self) -> None:
        """Parsing 88 MB of JSONL is the longest of the steps, and it was the first one found."""
        seen: list[str] = []
        original = pipe.L0JSONLReader.materialize

        def spy(self_reader, *args, **kwargs):
            seen.append(threading.current_thread().name)
            return original(self_reader, *args, **kwargs)

        pipe.L0JSONLReader.materialize = spy
        try:
            with TemporaryDirectory() as tmp:
                result = _run(pipe.run_decompile(
                    FakePipelineBridge(), out_dir=tmp,
                    change_stamp="pipeline-mini-v1"))
                self.assertTrue(result.ok, msg=result.to_dict())
        finally:
            pipe.L0JSONLReader.materialize = original

        self.assertTrue(seen, "материализация не вызвалась")
        self.assertNotIn(threading.main_thread().name, seen)

    def test_the_loop_keeps_ticking_while_a_heavy_step_blocks(self) -> None:
        """The loop CAUSALLY releases the heavy step, rather than merely happening to keep up alongside it.

        The patched fold waits for a signal that can be set ONLY by a
        sentinel in the event loop after several of its own ticks. If the
        fold accidentally ran back on the loop thread, the sentinel could
        not release it and the worker's emergency timeout would fire. This
        checks the same invariant without making the OS scheduler's state
        part of the contract.
        """
        original = pipe.fold_document
        worker_started = threading.Event()
        release_worker = threading.Event()
        worker_timed_out = threading.Event()
        worker_threads: list[int] = []

        def slow(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            worker_started.set()
            if not release_worker.wait(2.0):
                worker_timed_out.set()
            return original(*args, **kwargs)

        ticks_while_worker_waited: list[int] = []

        async def scenario():
            stop = asyncio.Event()
            loop_thread = threading.get_ident()

            async def sentry():
                while not stop.is_set():
                    await asyncio.sleep(0)
                    if (worker_started.is_set()
                            and not release_worker.is_set()):
                        ticks_while_worker_waited.append(
                            threading.get_ident())
                        if len(ticks_while_worker_waited) >= 10:
                            release_worker.set()

            watch = asyncio.ensure_future(sentry())
            try:
                with TemporaryDirectory() as tmp:
                    result = await pipe.run_decompile(
                        FakePipelineBridge(), out_dir=tmp,
                        change_stamp="pipeline-mini-v1")
                    return result, loop_thread
            finally:
                stop.set()
                # Do not leave the worker to its own timeout, even if the
                # pipeline finished with an exception before the causal
                # signal.
                release_worker.set()
                await watch

        pipe.fold_document = slow
        try:
            result, loop_thread = asyncio.run(scenario())
        finally:
            pipe.fold_document = original

        self.assertTrue(result.ok, msg=result.to_dict())
        self.assertTrue(worker_threads, "свёртка не вызвалась")
        self.assertNotEqual(worker_threads[0], loop_thread)
        self.assertFalse(
            worker_timed_out.is_set(),
            "event loop не освободил блокирующую свёртку")
        self.assertEqual(len(ticks_while_worker_waited), 10)
        self.assertEqual(set(ticks_while_worker_waited), {loop_thread})

    def test_core_artifact_offload_preserves_exact_bytes_and_names(self) -> None:
        passport = {
            "doc_name": "мини-здание",
            "revit_version": "2023",
            "change_stamp": "stable-v1",
            "gestalt": "mixed",
            "stats": {
                "elements_total": 2,
                "ops_lifted": 1,
                "atoms": 1,
                "floors": 1,
                "rooms": 0,
                "apartments": 0,
            },
            "verify_summary": {"failed_count": 0, "reversible": True},
        }
        tree = {
            "kind": "building",
            "name": "Корпус А",
            "children": [{"kind": "floor", "name": "Этаж 1"}],
        }
        named_tree = {
            "kind": "building",
            "name": "Именованный корпус",
            "children": [],
        }

        def atomic_json_bytes(value):
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            passport_md = pipe._persist_core_artifacts(
                out, passport, tree, {"tree": named_tree})

            self.assertEqual(
                {path.name for path in out.iterdir()},
                {"passport.json", "passport.md", "tree.json", "named.json"},
            )
            self.assertEqual(
                (out / "passport.json").read_bytes(),
                pipe.passport_bytes(passport),
            )
            self.assertEqual(
                (out / "passport.md").read_bytes(),
                pipe._passport_markdown(passport).encode("utf-8"),
            )
            self.assertEqual(
                (out / "tree.json").read_bytes(), atomic_json_bytes(tree))
            self.assertEqual(
                (out / "named.json").read_bytes(),
                atomic_json_bytes(named_tree),
            )
            self.assertEqual(passport_md, out / "passport.md")


if __name__ == "__main__":
    unittest.main()
