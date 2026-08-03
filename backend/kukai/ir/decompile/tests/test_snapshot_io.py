"""Gzip transparency for on-disk snapshots (2026-07-29, pre-1000-user wave).

The falsifying claim: a snapshot gzipped in place (``L0.jsonl`` ->
``L0.jsonl.gz`` + the side indexes, raw removed — exactly what
``tools/snapshot_janitor.py`` does) must lift to the BYTE-IDENTICAL canon
as the raw original. Proven on a real, small, committed fixture
(``backend/data/decompile/night_b2`` — 8 elements, every side index
present, all real capture bytes) rather than a hand-built synthetic one:
the shim has to survive real file shapes, not an idealized one.
"""
from __future__ import annotations

import copy
import dataclasses
import gzip
import pathlib
import shutil
import tempfile
import unittest

from kukai.ir.decompile.fold import FidelityCanon
from kukai.ir.decompile.lift import lift_document_detailed
from tools.relift_offline import _load_envelope, _load_side_index, load_document

_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[4]
    / "backend" / "data" / "decompile" / "night_b2")

#: The exact five side-index files + L0.jsonl the shim is scoped to
#: (relift_offline.load_document, L0JSONLReader, every side-index reader).
_SNAPSHOT_FILES = (
    "L0.jsonl", "curve.index.json", "curtain.index.json",
    "sketch.index.json", "family_placement.index.json", "group.index.json",
)

_ORIGIN = (0.0, 0.0, 0.0)


def _relift_hash(directory: pathlib.Path) -> str:
    """Same load path tools/relift_offline.relift() uses, collapsed to one
    canon multiset hash — the end-to-end proof, not just "the bytes read
    back the same", the WHOLE downstream lift/fold pipeline agrees."""
    document, elements = load_document(directory)
    document = dataclasses.replace(document, elements=elements)
    family_payload = _load_envelope(directory, "family_placement.index.json")
    result = lift_document_detailed(
        document,
        _load_side_index(directory, "sketch.index.json", "sketch_index"),
        family_payload,
        wall_curve_index=_load_side_index(
            directory, "curve.index.json", "curve_index"),
        curtain_index=_load_envelope(directory, "curtain.index.json"),
    )
    return FidelityCanon.multiset_hash(result.nodes, _ORIGIN)


def _gzip_in_place(directory: pathlib.Path) -> None:
    """Exactly what tools/snapshot_janitor.py's compress step does to one
    snapshot file: write name+'.gz', remove the raw original. Files the
    fixture doesn't have (e.g. an empty/absent side index) are skipped —
    "no such stage ran" must stay "no such stage ran" after compression."""
    for name in _SNAPSHOT_FILES:
        raw = directory / name
        if not raw.is_file():
            continue
        gz = directory.with_name(directory.name) / (name + ".gz")
        with raw.open("rb") as src, gzip.open(gz, "wb") as dst:
            shutil.copyfileobj(src, dst)
        raw.unlink()


class GzipSnapshotIsByteIdenticalToRaw(unittest.TestCase):
    def setUp(self) -> None:
        if not _FIXTURE.is_dir():
            self.skipTest(f"нет фикстуры {_FIXTURE}")
        self._tmp = tempfile.TemporaryDirectory(prefix="kir-snapshot-gz-test-")
        self.addCleanup(self._tmp.cleanup)
        self.raw_dir = pathlib.Path(self._tmp.name) / "raw"
        self.gz_dir = pathlib.Path(self._tmp.name) / "gz"
        shutil.copytree(_FIXTURE, self.raw_dir)
        shutil.copytree(_FIXTURE, self.gz_dir)
        _gzip_in_place(self.gz_dir)

    def test_gzip_directory_has_no_raw_snapshot_files_left(self) -> None:
        """Sanity on the test's own setup: the adversarial case is REAL
        absence of the raw file, not a coincidence of the fixture."""
        for name in _SNAPSHOT_FILES:
            raw = self.gz_dir / name
            gz = self.gz_dir / (name + ".gz")
            if (self.raw_dir / name).is_file():
                self.assertFalse(raw.exists(), name)
                self.assertTrue(gz.is_file(), name)

    def test_gzipped_snapshot_lifts_to_the_identical_canon_hash(self) -> None:
        """Опровергающий тест: до шима это падает с FileNotFoundError на
        первом же read (README readers know nothing about .gz); после шима
        оба каталога обязаны дать ОДИН canon-хеш."""
        raw_hash = _relift_hash(self.raw_dir)
        gz_hash = _relift_hash(self.gz_dir)
        self.assertEqual(raw_hash, gz_hash)

    def test_gzipped_side_index_that_never_ran_stays_none(self) -> None:
        """A side index the original run never produced must still read
        as "this stage didn't run" after compression — not silently
        become "ran with zero rows" and not crash."""
        raw_curtain = _load_envelope(self.raw_dir, "curtain.index.json")
        gz_curtain = _load_envelope(self.gz_dir, "curtain.index.json")
        self.assertEqual(raw_curtain, gz_curtain)


class SnapshotIoUnitTests(unittest.TestCase):
    """Direct coverage of the shim itself, independent of the lift
    pipeline: the primitives every reader now shares."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="kir-snapshot-io-unit-")
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)

    def test_open_snapshot_prefers_raw_over_gz(self) -> None:
        from kukai.ir.decompile.snapshot_io import open_snapshot

        (self.dir / "x.json").write_text("raw", encoding="utf-8")
        with gzip.open(self.dir / "x.json.gz", "wt", encoding="utf-8") as f:
            f.write("gz")
        with open_snapshot(self.dir / "x.json", "rt", encoding="utf-8") as h:
            self.assertEqual(h.read(), "raw")

    def test_open_snapshot_falls_back_to_gz(self) -> None:
        from kukai.ir.decompile.snapshot_io import open_snapshot

        with gzip.open(self.dir / "x.json.gz", "wt", encoding="utf-8") as f:
            f.write("gz-content")
        with open_snapshot(self.dir / "x.json", "rt", encoding="utf-8") as h:
            self.assertEqual(h.read(), "gz-content")

    def test_open_snapshot_raises_when_neither_exists(self) -> None:
        from kukai.ir.decompile.snapshot_io import open_snapshot

        with self.assertRaises(FileNotFoundError):
            open_snapshot(self.dir / "missing.json", "rt", encoding="utf-8")

    def test_snapshot_file_exists_true_for_gz_only(self) -> None:
        from kukai.ir.decompile.snapshot_io import snapshot_file_exists

        self.assertFalse(snapshot_file_exists(self.dir / "x.json"))
        with gzip.open(self.dir / "x.json.gz", "wb"):
            pass
        self.assertTrue(snapshot_file_exists(self.dir / "x.json"))

    def test_touch_last_access_creates_and_updates_marker(self) -> None:
        from kukai.ir.decompile.snapshot_io import (
            LAST_ACCESS_MARKER, touch_last_access)

        marker = self.dir / LAST_ACCESS_MARKER
        self.assertFalse(marker.exists())
        touch_last_access(self.dir)
        self.assertTrue(marker.exists())
        first = marker.stat().st_mtime
        marker.touch()  # simulate time passing without a real sleep
        os_stat_before = marker.stat().st_mtime
        touch_last_access(self.dir)
        self.assertGreaterEqual(marker.stat().st_mtime, os_stat_before)
        self.assertGreaterEqual(marker.stat().st_mtime, first)

    def test_open_snapshot_touches_the_marker(self) -> None:
        from kukai.ir.decompile.snapshot_io import (
            LAST_ACCESS_MARKER, open_snapshot)

        (self.dir / "x.json").write_text("raw", encoding="utf-8")
        self.assertFalse((self.dir / LAST_ACCESS_MARKER).exists())
        with open_snapshot(self.dir / "x.json", "rt", encoding="utf-8"):
            pass
        self.assertTrue((self.dir / LAST_ACCESS_MARKER).exists())

    def test_open_snapshot_touch_false_does_not_touch(self) -> None:
        from kukai.ir.decompile.snapshot_io import (
            LAST_ACCESS_MARKER, open_snapshot)

        (self.dir / "x.json").write_text("raw", encoding="utf-8")
        with open_snapshot(self.dir / "x.json", "rt", encoding="utf-8",
                           touch=False):
            pass
        self.assertFalse((self.dir / LAST_ACCESS_MARKER).exists())


if __name__ == "__main__":
    unittest.main()
