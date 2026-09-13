"""A COMPRESSED SNAPSHOT IS NOT A MISSING ONE. "COULD NOT READ" AND "NO DATA" ARE DIFFERENT FACTS.

Audit finding `F-185` (2026-08-29), `kir/corpus_catalog.load_catalog`.

`l0_bytes` was taken via `os.path.getsize` of the RAW name `L0.jsonl`. The
snapshot janitor compresses them into `L0.jsonl.gz`; for a compressed run
`getsize` raises `OSError`, and `l0_bytes` became `None` — i.e. "could not
read" was recorded with the SAME value as "there is no data". `index_fits`
then became `None` too.

🔴 THIS IS NOT A RISK, IT IS A LIVE FACT, AND IT CHANGED PROD'S OUTPUT.
Measurement on the real corpus (read-only), BEFORE and AFTER the fix:

    56 cards      | l0_bytes=None:   37 -> 0
                  | index_fits=None: 37 -> 0   (became 52 true / 4 false)
    93 catalogues | .gz only:        37

The two numbers were obtained by DIFFERENT paths — via `load_catalog` and by
walking the directory directly — and matched exactly: every run with
`l0_bytes=None` is a run where L0 sits compressed and IS ALIVE.
`Entry.to_dict()` travels to the client via `kir/serving.py`, meaning 37
cards out of 56 answered the model "does the building fit under the ceiling
— unknown" about buildings this was perfectly well known for.

🔴 THE MECHANISM WAS WRITTEN FOR THIS EXACT TRAP AND WAS NOT CALLED.
`snapshot_io.snapshot_raw_size` quotes it in its own docstring. The
catalogue grew a SECOND implementation of the question "how many bytes in
the snapshot", and it fell behind. So the cure is to call the existing one,
not add a `.gz` check next to it: adding one would grow a THIRD
implementation, and the two already disagree.

THE SECOND HALF, WITHOUT WHICH THE FIX IS INCOMPLETE. After it, `None`
means exactly one thing — "the file does not exist in any form". The case
"the file exists and is unreadable" is a THIRD state, and staying silent
about it would trade one disease for another of the same kind. It travels
out as a separate field `l0_unreadable`, not by faking the number: a
negative size would be a trick every reader of the field would have to be
told about.

AN UNFIT CHECK, NAMED EXPLICITLY: `assertEqual(len(none_l0), 0)` on the
LIVE corpus. It is red or green depending on the state of someone else's
machine, and it will go red the moment the janitor touches the corpus —
someone else's colour. The checks below run on SYNTHETIC data.
"""
from __future__ import annotations

import gzip
import json
import os
import tempfile
import unittest

from kir import corpus_catalog as cc

_CARD = """# KIR Passport — Проект1

- Revit: 2023
- change_stamp: `{run}`
- gestalt: Здание: прямоугольник, 1 этаж.
- элементов: 10
"""


def _run_dir(root: str, name: str, *, l0: str | None) -> str:
    """A synthetic parse. `l0` — 'raw' | 'gz' | None."""
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, cc.CARD_NAME), "w", encoding="utf-8") as fh:
        fh.write(_CARD.format(run=name))
    payload = json.dumps({"record": "element", "element": {"element_id": "1"}}) + "\n"
    if l0 == "raw":
        with open(os.path.join(d, "L0.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(payload)
    elif l0 == "gz":
        with gzip.open(os.path.join(d, "L0.jsonl.gz"), "wt", encoding="utf-8") as fh:
            fh.write(payload)
    return d


class СжатыйСнимокНеОтсутствующий(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        _run_dir(self.root, "packed", l0="gz")
        _run_dir(self.root, "plain", l0="raw")
        _run_dir(self.root, "empty", l0=None)
        self.by_run = {e.run: e for e in cc.load_catalog(root=self.root).entries}
        self.assertEqual(set(self.by_run), {"packed", "plain", "empty"})

    def test_a_compressed_snapshot_reports_a_real_size(self) -> None:
        """🔴 SUBJECT OF THE FINDING. Before the fix `packed` gave None."""
        packed = self.by_run["packed"]
        self.assertIsNotNone(packed.l0_bytes)
        self.assertGreater(packed.l0_bytes, 0)
        self.assertFalse(packed.l0_unreadable)

    def test_the_size_is_the_uncompressed_one_not_the_size_on_disk(self) -> None:
        """🔴 THE MEANING OF THE FIELD MUST NOT CHANGE SILENTLY. `index_fits`
        compares the volume of DATA against the transport ceiling, not disk
        space. The same payload, compressed or raw, must give ONE number."""
        self.assertEqual(self.by_run["packed"].l0_bytes,
                         self.by_run["plain"].l0_bytes)
        on_disk = os.path.getsize(os.path.join(self.root, "packed",
                                               "L0.jsonl.gz"))
        self.assertNotEqual(self.by_run["packed"].l0_bytes, on_disk,
                            "число совпало с размером НА ДИСКЕ — значит взят "
                            "сжатый размер, и смысл поля поменялся молча")

    def test_a_run_without_any_l0_still_reports_none(self) -> None:
        """🔴 A GREEN OUTCOME THAT MUST SURVIVE. Without it, the check would
        be "a size always exists", and it would pass on any stub."""
        empty = self.by_run["empty"]
        self.assertIsNone(empty.l0_bytes)
        self.assertIsNone(empty.index_fits)
        self.assertFalse(empty.l0_unreadable,
                         "«файла нет» — это НЕ «нечитаем»; слить их значило бы "
                         "завести молчащее значение на месте вылеченного")

    def test_index_fits_stops_being_none_for_a_compressed_run(self) -> None:
        """WHAT PROD SEES. `Entry.to_dict()` travels to the client via
        `serving`; today 37 cards out of 56 were giving `index_fits: null`."""
        self.assertIsInstance(self.by_run["packed"].index_fits, bool)
        self.assertIsInstance(self.by_run["plain"].index_fits, bool)
        self.assertIn("l0_unreadable", self.by_run["packed"].to_dict())

    def test_a_readable_file_that_cannot_be_sized_is_a_third_state(self) -> None:
        """🔴 THE THIRD STATE IS ENFORCED, NOT MERELY DECLARED. We swap the
        sizer so the file EXISTS and fails to be measured, and require
        `None` to arrive TOGETHER WITH a named cause, not in its place."""
        real = cc.__dict__.get("_snapshot_raw_size_for_test")
        self.assertIsNone(real, "хук теста не должен жить в модуле")
        import kir.decompile.snapshot_io as sio
        keep = sio.snapshot_raw_size

        def boom(_path):
            raise OSError("носитель отвалился")

        sio.snapshot_raw_size = boom
        try:
            by_run = {e.run: e for e in cc.load_catalog(root=self.root).entries}
        finally:
            sio.snapshot_raw_size = keep
        packed = by_run["packed"]
        self.assertIsNone(packed.l0_bytes)
        self.assertTrue(packed.l0_unreadable)
        # And the one that HAS no file at all stays simply "none" — the states are not merged.
        self.assertFalse(by_run["empty"].l0_unreadable)

    def test_a_run_without_a_card_carries_the_same_two_facts(self) -> None:
        """`Missing` is a second door onto the same data, and it must carry
        the same distinction, or half the corpus will answer the old way."""
        d = os.path.join(self.root, "nocard")
        os.makedirs(d)
        with gzip.open(os.path.join(d, "L0.jsonl.gz"), "wt", encoding="utf-8") as fh:
            fh.write("{}\n")
        miss = {m.run: m for m in cc.load_catalog(root=self.root).missing}
        self.assertIn("nocard", miss)
        self.assertTrue(miss["nocard"].has_l0,
                        "сжатый L0 у разбора без карточки объявлялся "
                        "отсутствующим тем же дефектом")
        self.assertFalse(miss["nocard"].l0_unreadable)
        self.assertIn("l0_unreadable", miss["nocard"].to_dict())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
