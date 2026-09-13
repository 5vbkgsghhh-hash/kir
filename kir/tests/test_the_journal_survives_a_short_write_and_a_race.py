"""THE DURABLE JOURNAL: A TRUNCATED LINE AND A FIRST-LOAD RACE.

Two defects, one subject — a building's memory across turns and restarts.
Both are closed by the principle that "done halfway" stops looking like
"done."

RT-25. `journal_store.append_line` called `os.write(fd, ...)` ONCE and did
not check the returned byte count against anything. A short write is a
legitimate outcome of `write(2)`, not an error (`-1` would be an error),
and it left a truncated fragment on disk while returning success to the
caller.

RT-27. `journal._RESTORE_TRIED` is an ordinary set, and the mark was set
BEFORE reading the store. A second thread within that window saw "already
tried," did not wait, and started an EMPTY session; the first thread
finished reading, got the honest refusal `live_session_present` — and the
building that had just been loaded was silently discarded, with no way to
repeat the load.

🔴 WHY THERE IS A FAIL CONTROL FOR EACH ONE HERE. Both assertions are
negative ("nothing was lost"), and a negative assertion is easy to pass
with an instrument that does not work at all. That is why next to each one
stands a measurement in THE OTHER DIRECTION: the instrument must SHOW a
loss when there is one.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
import time
import unittest

from kir.live import journal as J
from kir.live import journal_store as JS


# ═══════════════════════════════════════════════════════════════════════════
# RT-25. Short write
# ═══════════════════════════════════════════════════════════════════════════

class _ShortWrite:
    """A stand-in for `os.write` that takes only half. `once=True` — only the FIRST time.

    Both forms are legal under `write(2)`, and they produce DIFFERENT correct
    outcomes, so both are checked: a one-off short write must still get
    appended in full, while a complete inability to take any bytes must be
    named as a refusal.
    """

    def __init__(self, *, once: bool) -> None:
        self.once = once
        self.calls = 0
        self.real = os.write

    def __enter__(self):
        os.write = self          # type: ignore[assignment]
        return self

    def __exit__(self, *exc):
        os.write = self.real     # type: ignore[assignment]
        return False

    def __call__(self, fd, data):
        self.calls += 1
        if self.once and self.calls > 1:
            return self.real(fd, data)
        return self.real(fd, data[: len(data) // 2])


class AShortWriteIsNotAWrittenLine(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="rt25-"))
        self.path = self.tmp / "programs.jsonl"

    def test_a_write_cut_in_half_still_lands_as_a_whole_line(self):
        """POSITIVE. A one-off short write gets APPENDED IN FULL.

        `O_APPEND` places the remainder at the same end of the file, and the
        reader gets the whole line, not a named remnant.
        """
        row = {"schema": JS.SCHEMA, "event": JS.EVENT_PROGRAM,
               "ts": "2026-09-04T00:00:00+00:00", "device_id": "d",
               "doc_key": "k", "seq": 0, "текст": "стена" * 20}
        with _ShortWrite(once=True) as short:
            JS.append_line(self.path, row)
        self.assertGreaterEqual(short.calls, 2, "короткой записи не случилось")
        body = self.path.read_bytes()
        self.assertTrue(body.endswith(b"\n"), body[-40:])
        self.assertEqual(json.loads(body.decode("utf-8")), row)

    def test_a_line_that_cannot_be_finished_is_a_refusal_not_a_success(self):
        """FAIL CONTROL. A descriptor that takes no bytes must REFUSE.

        Before the fix, this same run raised nothing and left `_write`
        reporting `True` for a line that is not on disk.
        """
        with _ShortWrite(once=False):
            with self.assertRaises(OSError) as caught:
                JS.append_line(self.path, {"a": "б" * 40, "n": 1})
        self.assertIn("байт", str(caught.exception))
        self.assertIn("98", str(caught.exception).replace("  ", " "))

    def test_the_store_reports_false_when_the_line_did_not_land(self):
        """`_write` is fail-open, and it must return False, not True.

        This is exactly the cost of the defect: "line written" and "line
        truncated" arrived at the caller as ONE AND THE SAME value.
        """
        os.environ[JS.PATH_ENV] = str(self.path)
        try:
            with _ShortWrite(once=False):
                self.assertIs(JS._write({"schema": JS.SCHEMA, "a": "б" * 40}),
                              False)
            # CONTROL IN THE OTHER DIRECTION: without the substitution, the same line lands.
            self.assertIs(JS._write({"schema": JS.SCHEMA, "a": "б" * 40}), True)
        finally:
            os.environ.pop(JS.PATH_ENV, None)


# ═══════════════════════════════════════════════════════════════════════════
# RT-27. First-load race
# ═══════════════════════════════════════════════════════════════════════════

_KEY = ("rt27-device", "rt27-doc")
_DISK_PROGRAMS = 5


class _SlowRestore:
    """A restore from a store that READS SLOWLY — that is exactly the window.

    The slow restore here is not invented for the test's sake: a measurement
    on this machine gives a median of 18.0 ms at 1,000 store rows and
    218.4 ms at 10,000. The window exists for a real file; the 300 ms only
    make it observable without depending on the scheduler.
    """

    def __init__(self, delay: float = 0.30) -> None:
        self.delay = delay
        self.calls = 0
        self.real = J.restore

    def __enter__(self):
        J.restore = self          # type: ignore[assignment]
        return self

    def __exit__(self, *exc):
        J.restore = self.real     # type: ignore[assignment]
        return False

    def __call__(self, key, *, path=None):
        self.calls += 1
        time.sleep(self.delay)
        with J._LOCK:
            live = J._SESSIONS.get(key)
            if live is not None and live.records:
                return {"restored": 0, "refused": "live_session_present",
                        "live_records": len(live.records)}
            journal = J.SessionJournal(key=key)
            for seq in range(_DISK_PROGRAMS):
                journal.append(J.ProgramRecord(
                    seq=seq, ts=time.time(), stage="committed",
                    restored_from_disk=True,
                    ops=({"op": "create_level", "elev_mm": seq * 3000},)))
                journal.next_seq = max(journal.next_seq, seq + 1)
            J._SESSIONS[key] = journal
            return {"restored": _DISK_PROGRAMS}


def _two_writers(gap: float) -> None:
    """Two threads write to ONE key; the second enters after `gap` seconds."""
    def worker():
        J.append(_KEY, {"ops": [{"op": "create_wall", "id": "w",
                                 "p0_mm": [0, 0], "p1_mm": [6000, 0]}]})
    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    time.sleep(gap)
    second.start()
    first.join()
    second.join()


class TheFirstLoadIsNotARace(unittest.TestCase):

    def setUp(self):
        J.reset()
        J._RESTORE_TRIED.clear()
        # `getattr` IS DELIBERATE: on a frozen copy taken BEFORE the fix,
        # this dictionary does not exist, and a failure in `setUp` would
        # have painted all four instruments with a NAME instead of a
        # NUMBER. What must go red is BEHAVIOR.
        getattr(J, "_RESTORE_LOCKS", {}).clear()

    tearDown = setUp

    def test_a_second_writer_waits_instead_of_starting_the_building_over(self):
        """POSITIVE. Both programs land ON TOP OF the restored building.

        Measurement before the fix, on this same run: 2 records, `next_seq`
        2, 0 restored from disk — five history programs vanished silently
        and forever (the flag in `_RESTORE_TRIED` was already set).
        """
        with _SlowRestore() as slow:
            _two_writers(gap=0.05)
        entry = J.get(_KEY)
        self.assertIsNotNone(entry)
        self.assertEqual(slow.calls, 1, "склад читан больше одного раза")
        self.assertEqual(len(entry.records), _DISK_PROGRAMS + 2)
        self.assertEqual(entry.next_seq, _DISK_PROGRAMS + 2)
        self.assertEqual(
            sum(1 for r in entry.records if r.restored_from_disk),
            _DISK_PROGRAMS, "поднятое со склада потеряно")

    def test_the_sequential_control_gives_the_same_numbers(self):
        """CONTROL. Sequential gives the same numbers as parallel.

        The claim "there is no race" is only checkable against a
        MEASUREMENT WITHOUT A RACE: otherwise 7 and 7 could turn out to be
        a property of the instrument itself.
        """
        with _SlowRestore() as slow:
            _two_writers(gap=0.60)          # the second enters AFTER the restore
        entry = J.get(_KEY)
        self.assertEqual(slow.calls, 1)
        self.assertEqual(len(entry.records), _DISK_PROGRAMS + 2)
        self.assertEqual(entry.next_seq, _DISK_PROGRAMS + 2)

    def test_the_probe_can_still_see_a_loss_when_there_is_one(self):
        """FAIL CONTROL. The instrument must SHOW the loss when there is one.

        The flag is set by hand BEFORE the first program — exactly the
        state that the defect used to produce on its own. The restore does
        not happen, the building starts from an empty place, and the
        instrument sees it.
        """
        J._RESTORE_TRIED.add(_KEY)
        with _SlowRestore() as slow:
            _two_writers(gap=0.05)
        entry = J.get(_KEY)
        self.assertEqual(slow.calls, 0)
        self.assertEqual(len(entry.records), 2)
        self.assertEqual(
            sum(1 for r in entry.records if r.restored_from_disk), 0)

    def test_the_lock_is_a_thread_lock_because_the_race_is_in_one_process(self):
        """THE LOCK IS NAMED AFTER ITS SUBJECT, NOT OUT OF HABIT.

        The neighbor in the tree (`decompile/journal_store.py`) guards a
        FILE and so takes `flock`. Here what is guarded is
        `_RESTORE_TRIED` and `_SESSIONS` — both module globals — while
        `restore()` only READS the store. The claim is checked by
        execution, not by reading a comment: a restore on a live store
        creates and changes not a single file.
        """
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="rt27-ro-"))
        store = tmp / "s.jsonl"
        JS.append_line(store, {"schema": JS.SCHEMA, "event": JS.EVENT_PROGRAM,
                               "ts": "2026-09-04T00:00:00+00:00",
                               "device_id": _KEY[0], "doc_key": _KEY[1],
                               "seq": 0, "stage": "planned",
                               "ops": [{"op": "create_level", "elev_mm": 0}]})
        before = {p.name: p.stat().st_size for p in tmp.iterdir()}
        J.restore(_KEY, path=store)
        after = {p.name: p.stat().st_size for p in tmp.iterdir()}
        self.assertEqual(before, after, "подъём ПИСАЛ на диск — тогда замок "
                                       "обязан быть межпроцессным")
        # And only now — that the mechanism taken is EXACTLY this one.
        self.assertIsInstance(J._restore_lock(_KEY), type(threading.Lock()))

    def test_the_key_lock_is_dropped_after_the_load(self):
        """There is no second unboundedly growing dictionary next to `_RESTORE_TRIED`."""
        with _SlowRestore(delay=0.0):
            J.append(_KEY, {"ops": [{"op": "create_level", "elev_mm": 0}]})
        self.assertIn(_KEY, J._RESTORE_TRIED)
        self.assertEqual(getattr(J, "_RESTORE_LOCKS", {}), {})


if __name__ == "__main__":
    unittest.main()
