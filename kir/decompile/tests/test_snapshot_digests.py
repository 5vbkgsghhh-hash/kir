"""A COMPRESSED SNAPSHOT MUST HAVE A WITNESS OF ITS CONTENT, NOT ONLY OF THE
CONTAINER.

WHY THIS FILE, BY THE 20.08.2026 MEASUREMENT. The janitor
(`tools/snapshot_janitor.py`) compresses into a temp file, reads it back,
and checks it against the original byte for byte, and only then deletes the
raw one. The check is sound — but it is about the COMPRESSOR and lives for
exactly one instant: after `unlink()` the single remaining copy has no
witness of what it used to be.

A FAIL control on a copy of the `graph_check` decompile showed the
boundary precisely:

    the container is corrupted   -> BadGzipFile "Unknown compression method" LOUDLY
    the content is swapped       -> THE INSTRUMENT'S ANSWER DID NOT CHANGE AT ALL
                                     (wall thickness 200 -> 999; shells 1504,
                                     refusals 52, the census digest the same)

The second one is the hole. And checking a SUMMARY is useless BY
CONSTRUCTION: a swap that does not enter the summary will never move it —
and which one will is unknown in advance.

🔴 THE COST OF THIS HOLE TODAY IS ZERO, AND THAT IS EXACTLY WHY NOW IS THE
TIME. The janitor is not wired in: compressed decompiles 0 of 75. Once it
is wired in, this becomes the corpus all our measurements stand on.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import tempfile
import unittest

from kir.decompile import snapshot_io as SIO


class ДайджестПереживаетСжатие(unittest.TestCase):

    def _snapshot(self, tmp: str, payload: bytes = b'{"a": 1}\n{"b": 2}\n'):
        """The snapshot is assembled the SAME WAY the janitor will compress it.

        The digest is taken from the RAW bytes before compression — exactly
        the spot where the janitor has already read them
        (`original = raw.read_bytes()`), so as not to introduce a second
        read and a second way to get it wrong.
        """
        run = pathlib.Path(tmp)
        raw = run / "L0.jsonl"
        raw.write_bytes(payload)
        SIO.record_digest(run, "L0.jsonl", payload)
        with gzip.open(SIO.gz_path(raw), "wb") as handle:
            handle.write(payload)
        raw.unlink()
        return run

    def test_a_faithful_compression_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._snapshot(tmp)
            self.assertEqual(SIO.verify_digests(run), {})

    def test_TAMPERED_CONTENT_IS_CAUGHT(self):
        """🔴 THE FILE'S MAIN TEST: a swap inside an intact container.

        This is exactly the case that slipped past the instrument in
        silence: the gzip is valid, it reads, it returns data — just the
        wrong data.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run = self._snapshot(tmp)
            with gzip.open(SIO.gz_path(run / "L0.jsonl"), "wb") as handle:
                handle.write(b'{"a": 999}\n{"b": 2}\n')
            bad = SIO.verify_digests(run)
        self.assertIn("L0.jsonl", bad)
        self.assertIn("содержимое разошлось", bad["L0.jsonl"])

    def test_a_missing_file_is_named_not_silently_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._snapshot(tmp)
            SIO.gz_path(run / "L0.jsonl").unlink()
            bad = SIO.verify_digests(run)
        self.assertIn("L0.jsonl", bad)
        self.assertIn("нет ни сырым, ни сжатым", bad["L0.jsonl"])

    def test_a_broken_container_is_named_too(self):
        """The container is already caught by gzip — but the REFUSAL must
        become a ROW, not an exception thrown outward: the check runs over
        many files, and the first broken one must not cut off the rest."""
        with tempfile.TemporaryDirectory() as tmp:
            run = self._snapshot(tmp)
            SIO.gz_path(run / "L0.jsonl").write_bytes(b"\x1f\x8b" + b"\x00" * 64)
            bad = SIO.verify_digests(run)
        self.assertIn("L0.jsonl", bad)
        self.assertIn("не читается", bad["L0.jsonl"])


class ОтсутствиеМанифестаЭтоТРЕТИЙ_ИСХОД(unittest.TestCase):
    """"There is nothing to check against" and "checked, everything matched"
    are different facts.

    Returning an empty dict here would mean reporting no findings where the
    instrument was never present at all — our own named form of it (a zero
    for a quantity that was not counted here).
    """

    def test_no_manifest_is_not_an_empty_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp)
            (run / "L0.jsonl").write_bytes(b"x")
            out = SIO.verify_digests(run)
        self.assertNotEqual(out, {})
        self.assertIn("манифеста нет", out[""])

    def test_a_foreign_schema_refuses_instead_of_verifying(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp)
            (run / SIO.DIGEST_MANIFEST).write_text(
                json.dumps({"schema_version": "kir-snapshot-digests/999",
                            "files": {}}), encoding="utf-8")
            out = SIO.verify_digests(run)
        self.assertIn("чужая схема", out[""])


class МанифестНеТеряетСОСЕДА(unittest.TestCase):
    """The files of one decompile are compressed SEQUENTIALLY.

    A full manifest overwrite on every file would erase the previous one —
    and this can only be noticed on the SECOND one, so the experiment runs
    on two.
    """

    def test_two_files_both_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp)
            SIO.record_digest(run, "L0.jsonl", b"aaa")
            SIO.record_digest(run, "curve.index.json", b"bbb")
            rows = json.loads((run / SIO.DIGEST_MANIFEST).read_text(
                encoding="utf-8"))["files"]
        self.assertEqual(sorted(rows), ["L0.jsonl", "curve.index.json"])
        self.assertNotEqual(rows["L0.jsonl"]["sha256"],
                            rows["curve.index.json"]["sha256"])


if __name__ == "__main__":
    unittest.main()
