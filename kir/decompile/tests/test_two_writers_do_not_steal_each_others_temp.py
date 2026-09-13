# -*- coding: utf-8 -*-
"""Two writers do not steal each other's temp file (04.09.2026).

`_atomic_write_json` was writing to a temp file named `<target>.tmp` —
ONE name for every writer. While a single writer was at work, this
looked flawless: the write is atomic, the directory is synced, no
failures. A second writer on the same path breaks everything silently:
its ``os.replace`` grabs the first writer's temp file right out from
under it, and the first one crashes with `FileNotFoundError` on its own
``os.replace``.

THE NUMBER THIS PROBE WAS WRITTEN FOR was taken by a neighboring
session on this function's twin in ``pipeline.py``: two threads of 1000
writes each give **294-733 failures**, and after a unique name —
**zero**. The shape of the fix is taken from there (`bdc5db1`), not
reinvented.

WHY THE PROBE IS SHORT, NOT AT 1000. What is needed here is not the
same scale, but DISCRIMINATION: the probe must turn red on the old
shape and green on the new one. The second test below BRINGS BACK the
old shape by a swap and demands that failures appear — without it, the
first test's green would mean nothing.
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from kir.decompile import extract

#: Writes per thread. Fewer, and the old shape starts slipping through,
#: and the FAIL control becomes flaky.
WRITES = 200
THREADS = 2


def _hammer(path: Path):
    """Two threads write to ONE path; return the list of caught failures."""

    beaten: list[BaseException] = []
    barrier = threading.Barrier(THREADS)

    def worker(tag: int) -> None:
        barrier.wait()
        for i in range(WRITES):
            try:
                extract._atomic_write_json(path, {"tag": tag, "i": i})
            except BaseException as exc:  # noqa: BLE001 — the probe's very subject
                beaten.append(exc)

    threads = [threading.Thread(target=worker, args=(t,))
               for t in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return beaten


class ConcurrentWritersKeepTheirOwnTemporary(unittest.TestCase):

    def test_two_writers_finish_without_losing_a_temporary(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            beaten = _hammer(path)
        self.assertEqual(
            [type(e).__name__ for e in beaten], [],
            "пишущий потерял свой временный файл: имя временного обязано "
            "быть уникальным на всех пишущих")

    def test_the_old_shared_name_really_does_lose_it(self):
        """FAIL CONTROL: without it, the green test above proves nothing.

        We bring back the old name shape — one for everyone — and
        demand that failures APPEAR. If it is still zero, the probe
        does not discriminate, and the first test's green was green by
        construction.
        """

        def shared(path: Path) -> Path:
            return path.with_name(path.name + ".tmp")

        with mock.patch.object(extract, "_temp_name", shared):
            with TemporaryDirectory() as directory:
                path = Path(directory) / "checkpoint.json"
                beaten = _hammer(path)
        self.assertTrue(
            beaten,
            "прежняя форма НЕ дала ни одного отказа — значит проба не "
            "различает форму имени, и её зелёный ничего не стоит")
        # The failure must be exactly the one named in the measurement:
        # someone else's `os.replace` carried off our temp file.
        self.assertTrue(
            any(isinstance(e, FileNotFoundError) for e in beaten),
            f"ожидался FileNotFoundError, получено "
            f"{sorted({type(e).__name__ for e in beaten})}")

    def test_the_name_is_unique_per_call_and_stays_beside_its_target(self):
        first = extract._temp_name(Path("/x/y/checkpoint.json"))
        second = extract._temp_name(Path("/x/y/checkpoint.json"))
        self.assertNotEqual(first, second)
        for name in (first, second):
            with self.subTest(name=name.name):
                # Right next to the target — otherwise `os.replace`
                # would stop being atomic: a rename across a filesystem
                # boundary is not atomic and would silently turn into a
                # copy.
                self.assertEqual(name.parent, Path("/x/y"))
                self.assertTrue(name.name.endswith(".tmp"))
                self.assertTrue(name.name.startswith("checkpoint.json."))


if __name__ == "__main__":
    unittest.main()
