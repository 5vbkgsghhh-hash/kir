"""Two simultaneous writers: no piece of work may vanish silently.

Two defects of one kind — "a file lies on disk, but there is no lock in the
code" — and both were reproduced by EXECUTION, not read by eye.

**RV-11, the building's journal.** `record_revision` is READ-COUNT-
REPLACE. The swap (`os.replace`) is indivisible, the whole triple is not.
Measurement before the fix:

    CONTROL sequential : r1.rev=1  r2.rev=2  events in journal = 3
    EXPERIMENT parallel : A={ok, rev=1}  B={ok, rev=1}  events = 2

Both got SUCCESS and ONE revision; one piece of work vanished. This is the
worst outcome possible: the journal exists so that the building has a
history, and a history with a hole looks exactly like an honest one. What is
pinned here is not "the lock holds" (a lock can be rewritten), but the
CONSEQUENCE: there are exactly as many successes as the chain grew by, and
two revisions do not carry one number.

**RH-12, the pipeline's `status.json`.** The temporary file was named
`<имя>.tmp` — ONE name for all writers into the directory, while
`status.json` is written simultaneously by both the run's progress and a
cancellation. Measurement before the fix, 2×1000 writes: **423**
`FileNotFoundError: status.json.tmp -> status.json` exceptions — one's
`os.replace` took the other's temporary file. After — 0.

🔴 WHY THE WINDOW IS WIDENED ON PURPOSE (`threading.Barrier`). A race caught
"by luck" is an instrument whose negative answer means nothing: such a test
passing green is indistinguishable from a failed coin toss. The barrier
makes the collision MANDATORY on the old code. On the fixed code the first
writer arrives at the barrier WHILE HOLDING THE LOCK, the second never
reaches the barrier at all, the barrier breaks on timeout — and that by
itself is evidence that the lock kept them apart.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
import unittest
from typing import Any
from unittest import mock

from kir.decompile import journal_store as store
from kir.decompile import pipeline as pipe
from kir.decompile.journal_store import (
    journal_of,
    load_log,
    log_path,
    record_revision,
)
from kir.decompile.tests.test_merkle import _fold, _grid_building

#: How long the barrier waits for the second one. On the old code the
#: second one arrives immediately and the timeout is not spent; on the new
#: code this is exactly the price the test pays for the proof (the second
#: one is locked out, the barrier must break on its own).
_WIDEN_S = 0.5

_DOC = "дом"


class TwoWritersOfOneJournal(unittest.TestCase):
    """RV-11: the building's journal under two simultaneous `record_revision` calls."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)

    # ── helpers ──────────────────────────────────────────────────────────
    def _record(self, stamp: str, tree: Any) -> dict[str, Any]:
        directory = self.root / stamp
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tree.json").write_text(
            json.dumps(tree), encoding="utf-8")
        return record_revision(
            self.root, doc_name=_DOC, doc_stamp=stamp,
            out_dir=str(directory), tree=tree, revit_version="2026")

    def _events(self) -> int:
        log = load_log(log_path(self.root, _DOC))
        return len(journal_of(log)) if log is not None else 0

    @staticmethod
    def _tree(**kwargs: Any) -> Any:
        return _fold(_grid_building(floors=3, **kwargs))

    # ── laws ─────────────────────────────────────────────────────────────
    def test_two_concurrent_appends_never_both_claim_one_revision(
            self) -> None:
        """There are exactly as many successes as the chain grew by.

        The very outcome that no longer exists: "both ok, one revision,
        one event." A refusal to one is LAWFUL (the asker sees it), a
        silent loss is not.
        """

        self.assertTrue(self._record("v0", self._tree())["ok"])
        before = self._events()
        self.assertEqual(before, 1)

        trees = {
            "A": self._tree(extra_furniture_on_floor=1),
            "B": self._tree(extra_furniture_on_floor=1,
                            stretch_wall_on_floor=2),
        }
        barrier = threading.Barrier(2, timeout=_WIDEN_S)
        real_write = store._atomic_write_json

        def gated(path: Any, payload: Any) -> None:
            # Collide the two EXACTLY in the window between reading the head
            # and replacing the file. A broken barrier is not a test
            # failure but a signal: the second one never got here because
            # it is waiting on the lock.
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return real_write(path, payload)

        out: dict[str, dict[str, Any]] = {}

        def go(key: str) -> None:
            try:
                out[key] = self._record(f"v-{key}", trees[key])
            except BaseException as exc:  # noqa: BLE001 — a crash is evidence too
                out[key] = {"ok": False, "raised": repr(exc)}

        with mock.patch.object(store, "_atomic_write_json", gated):
            threads = [threading.Thread(target=go, args=(k,), name=k)
                       for k in ("A", "B")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60.0)
                self.assertFalse(thread.is_alive(), "пишущий завис")

        self.assertEqual(set(out), {"A", "B"})
        grew = self._events() - before
        appended = [r for r in out.values()
                    if r.get("ok") and r.get("appended")]

        self.assertEqual(
            len(appended), grew,
            f"успехов {len(appended)}, а цепочка выросла на {grew}: "
            f"работа, за которую отчитались успехом, в журнал не попала. "
            f"квитанции: {out}")
        numbers = [r["revision"] for r in appended]
        self.assertEqual(
            sorted(set(numbers)), sorted(numbers),
            f"две ревизии носят один номер {numbers} — второй писатель встал "
            f"на голову, прочитанную до первого. квитанции: {out}")
        for key, report in out.items():
            if report.get("ok") and report.get("appended"):
                continue
            self.assertFalse(
                report.get("ok"),
                f"{key}: не дописал, но отчитался успехом — {report}")
            self.assertIn(
                "error", report,
                f"{key}: отказ обязан называть себя — {report}")

        # And the other side: both writes are PRESENT in the journal
        # itself, not only in the receipts.
        stamps = [row["doc_stamp"]
                  for row in (load_log(log_path(self.root, _DOC)) or
                              {"revisions": []})["revisions"]]
        for report in appended:
            self.assertIn(report["doc_stamp"], stamps)

    def test_a_busy_log_refuses_by_name_instead_of_writing(self) -> None:
        """The second outcome permitted by the law: an HONEST refusal.

        The lock is held by the other one; waiting forever would amount to
        looking like work. The refusal must be named (`log_busy`) and must
        not write anything.
        """

        self.assertTrue(self._record("v0", self._tree())["ok"])
        path = log_path(self.root, _DOC)
        taken = threading.Event()
        release = threading.Event()

        def holder() -> None:
            with store._log_lock(path):
                taken.set()
                release.wait(30.0)

        thread = threading.Thread(target=holder, name="holder")
        thread.start()
        try:
            self.assertTrue(taken.wait(20.0), "держатель не взял замок")
            with mock.patch.object(store, "LOCK_TIMEOUT_S", 0.2):
                report = self._record("v1", self._tree(
                    extra_furniture_on_floor=1))
        finally:
            release.set()
            thread.join(30.0)

        self.assertFalse(report["ok"], f"занятый журнал сказал «ок»: {report}")
        self.assertFalse(report["appended"])
        self.assertEqual(report.get("reason"), "log_busy",
                         f"отказ не назвал причину: {report}")
        self.assertEqual(
            self._events(), 1,
            "отказ по занятости дописал ревизию — отказ, который всё-таки "
            "пишет, хуже отсутствующего")

    def test_the_lock_names_the_mechanism_that_holds_it(self) -> None:
        """"No lock" and "lock taken" must look different.

        Not cosmetics: a platform without an inter-process lock must
        REFUSE, not write silently, and this must be readable from the
        receipt, not from the code.
        """

        self.assertIn(store.LOCK_MECHANISM, ("flock", "msvcrt", "none"))
        self.assertNotEqual(
            store.LOCK_MECHANISM, "none",
            "на этой платформе межпроцессного замка нет — журнал здания "
            "здесь писать нельзя")
        self.assertTrue(str(store.lock_path(
            log_path(self.root, _DOC))).endswith(".json.lock"))


class TwoWritersOfOneStatus(unittest.TestCase):
    """RH-12: `pipeline._atomic_write_json` under two writers."""

    #: This many writes each of the two performs. At 1000 the old code
    #: produced 423 exceptions; a smaller number would have made the
    #: test's negative answer unverifiable.
    ROUNDS = 1000

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.path = self.dir / "status.json"

    def test_two_writers_never_steal_each_others_temporary_file(self) -> None:
        errors: list[str] = []
        guard = threading.Lock()

        def writer(tag: str) -> None:
            for index in range(self.ROUNDS):
                try:
                    pipe._atomic_write_json(
                        self.path, {"who": tag, "i": index})
                except Exception as exc:  # noqa: BLE001 — we are counting THEM
                    with guard:
                        errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=writer, args=(t,), name=t)
                   for t in ("A", "B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(600.0)
            self.assertFalse(thread.is_alive(), "пишущий завис")

        self.assertEqual(
            errors, [],
            f"{len(errors)} записей из {2 * self.ROUNDS} провалились: "
            f"временный файл общий на всех. первое: {errors[:1]}")
        # The file is intact and readable: "no errors" without this would
        # mean only "nobody complained."
        self.assertIsInstance(
            json.loads(self.path.read_text(encoding="utf-8")), dict)
        self.assertEqual(
            sorted(p.name for p in self.dir.iterdir()), ["status.json"],
            "рядом со статусом остался мусор")

    def test_a_failed_write_leaves_no_temporary_file_behind(self) -> None:
        """The price of a unique name: the writer itself must clean up after itself.

        With the previous FIXED name, an unfinished file was overwritten
        by the next write; with a unique one nothing overwrites it, and
        without cleanup the run directory would accumulate a file per
        refusal.
        """

        with mock.patch("os.replace", side_effect=OSError("нет места")):
            with self.assertRaises(OSError):
                pipe._atomic_write_json(self.path, {"stage": "init"})

        self.assertEqual(
            [p.name for p in self.dir.iterdir()], [],
            "провалившаяся запись оставила временный файл")

    def test_each_writer_gets_its_own_temporary_name(self) -> None:
        names = {pipe._tmp_path_for(self.path).name for _ in range(16)}
        self.assertEqual(len(names), 16)
        self.assertNotIn(self.path.name + ".tmp", names)
        for name in names:
            self.assertTrue(name.startswith("status.json."))
            self.assertTrue(name.endswith(".tmp"))
            self.assertIn(str(os.getpid()), name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
