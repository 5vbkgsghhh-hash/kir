"""THE SNAPSHOT WITNESS IS GREEN WHEN THERE IS NOTHING TO WITNESS —
F-343 · F-019 · F-344 · E-14.

All four are one pair of functions (`record_digest` / `verify_digests`)
and ONE defect: **the digest manifest answers for ITS OWN ROWS, and is
read as an answer about the SNAPSHOT.** The difference between
"everything was checked" and "what was recorded was checked" was
expressed nowhere, so any loss of rows was silently turning into a green
verdict.

    F-343  a 1-row manifest for a 2-file directory -> `{}`
    F-019  a broken manifest was rewritten with ONE new row, the
           previous evidence disappeared with no mark; the next check
           printed "0 discrepancies"
    F-344  legal JSON of a foreign shape (`[]`, `"a string"`) FAILED the
           verifier with `AttributeError` — the guarding `except` ended
           one line above
    E-14   `snapshot.digests.json.tmp` — a FIXED temp-file name

F-343 and F-019 are the input and the output of the same thing: F-019
CREATES an incomplete manifest, F-343 declares it clean. Fixing them
separately is pointless.

🔴 THE COMMENT IN THE CODE SAID THE OPPOSITE OF WHAT THE CODE DID. Above
the `rows = {}` branch stood "not a reason to silently discard the old
ones" — and the discarding was precisely silent. The prose was broader
than the behavior; the body was what should have been believed.

EXECUTED BEFORE THE FIX: an incomplete manifest -> `{}` · after
corrupting 2 rows -> 1, no mark, the check `{}` · `[]` and `"a string"`
-> `AttributeError`.

Run:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_the_digest_witness_says_what_it_did_not_check.py -q
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kir.decompile.snapshot_io import (
    DIGEST_MANIFEST,
    DIGEST_SCHEMA,
    record_digest,
    verify_digests,
)


class _Snapshot(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, name: str, data: bytes) -> bytes:
        (self.dir / name).write_bytes(data)
        return data

    def _manifest(self) -> dict:
        return json.loads(
            (self.dir / DIGEST_MANIFEST).read_text(encoding="utf-8"))


class AnIncompleteManifestIsNotACleanVerdict(_Snapshot):
    """F-343: "everything was checked" and "what was recorded was checked" are different facts."""

    def test_without_a_list_the_verdict_is_byte_for_byte_the_old_one(self):
        """The default changes NOT A SINGLE existing call."""
        record_digest(self.dir, "L0.jsonl", self._file("L0.jsonl", b'{"a":1}'))
        self._file("passport.json", b"{}")
        self.assertEqual(verify_digests(self.dir), {})

    def test_a_file_outside_the_manifest_is_named_when_asked(self):
        record_digest(self.dir, "L0.jsonl", self._file("L0.jsonl", b'{"a":1}'))
        self._file("passport.json", b"{}")
        bad = verify_digests(self.dir,
                             expected=("L0.jsonl", "passport.json"))
        self.assertIn("passport.json", bad)
        self.assertIn("сверять", bad["passport.json"])
        self.assertNotIn("L0.jsonl", bad)

    def test_an_expected_file_that_does_not_exist_is_not_an_accusation(self):
        """The name is neither in the manifest nor on disk — there is nothing to blame."""
        record_digest(self.dir, "L0.jsonl", self._file("L0.jsonl", b"x"))
        self.assertEqual(
            verify_digests(self.dir, expected=("L0.jsonl", "tree.json")), {})

    def test_a_fully_witnessed_snapshot_stays_clean(self):
        """🔴 THE SECOND OUTCOME: otherwise the fix is indistinguishable from "always complain"."""
        record_digest(self.dir, "L0.jsonl", self._file("L0.jsonl", b"a"))
        record_digest(self.dir, "tree.json", self._file("tree.json", b"b"))
        self.assertEqual(
            verify_digests(self.dir, expected=("L0.jsonl", "tree.json")), {})


class LostRowsLeaveAMark(_Snapshot):
    """F-019: a loss of evidence must be VISIBLE, not inferred by the reader."""

    def _corrupt_after_two_rows(self) -> None:
        record_digest(self.dir, "L0.jsonl", self._file("L0.jsonl", b"one"))
        record_digest(self.dir, "tree.json", self._file("tree.json", b"two"))
        self.assertEqual(sorted(self._manifest()["files"]),
                         ["L0.jsonl", "tree.json"])
        (self.dir / DIGEST_MANIFEST).write_text("{не json", encoding="utf-8")
        record_digest(self.dir, "tree.json", b"two")

    def test_the_new_manifest_carries_the_loss(self):
        self._corrupt_after_two_rows()
        self.assertIn("prior_rows_lost", self._manifest())

    def test_the_verifier_reads_the_mark_instead_of_reporting_clean(self):
        self._corrupt_after_two_rows()
        bad = verify_digests(self.dir)
        self.assertIn(DIGEST_MANIFEST, bad,
                      "сверка снова печатает «расхождений 0» о слепке, у "
                      "которого свидетеля больше нет")

    def test_the_broken_manifest_is_kept_as_evidence(self):
        self._corrupt_after_two_rows()
        self.assertTrue((self.dir / (DIGEST_MANIFEST + ".broken")).is_file())

    def test_an_intact_manifest_carries_no_mark(self):
        """🔴 THE SECOND OUTCOME: the mark does not appear on its own."""
        record_digest(self.dir, "L0.jsonl", self._file("L0.jsonl", b"one"))
        record_digest(self.dir, "tree.json", self._file("tree.json", b"two"))
        self.assertNotIn("prior_rows_lost", self._manifest())
        self.assertEqual(verify_digests(self.dir), {})
        self.assertFalse((self.dir / (DIGEST_MANIFEST + ".broken")).exists())


class AForeignShapeIsAVerdictNotACrash(_Snapshot):
    """F-344: a corrupted manifest is a NAMED outcome, not a crash for the caller."""

    def test_a_legal_json_of_the_wrong_shape_is_refused_by_name(self):
        self._file("a", b"x")
        for shape, kind in (("[]", "list"), ('"строка"', "str"),
                            ("7", "int"), ("null", "NoneType")):
            with self.subTest(форма=shape):
                (self.dir / DIGEST_MANIFEST).write_text(shape,
                                                        encoding="utf-8")
                bad = verify_digests(self.dir)
                self.assertEqual(bad, {"": "манифест не словарь, а %s" % kind})

    def test_a_malformed_row_blames_the_manifest_not_the_file(self):
        self._file("a", b"x")
        (self.dir / DIGEST_MANIFEST).write_text(
            json.dumps({"schema_version": DIGEST_SCHEMA, "files": {"a": []}}),
            encoding="utf-8")
        bad = verify_digests(self.dir)
        self.assertEqual(bad, {"a": "строка манифеста не словарь, а list"})


class TheTemporaryNameIsUnique(_Snapshot):
    """E-14: one name for every writer in the directory — the same class as F-070."""

    def test_the_temporary_file_is_not_the_fixed_name(self):
        import tempfile as _t
        seen: list[str] = []
        real = _t.NamedTemporaryFile

        def _spy(*args, **kwargs):
            handle = real(*args, **kwargs)
            seen.append(Path(handle.name).name)
            return handle

        _t.NamedTemporaryFile = _spy
        try:
            record_digest(self.dir, "L0.jsonl", self._file("L0.jsonl", b"z"))
        finally:
            _t.NamedTemporaryFile = real
        self.assertTrue(seen, "запись пошла не через NamedTemporaryFile")
        self.assertNotEqual(seen[0], DIGEST_MANIFEST + ".tmp",
                            "имя временного файла снова фиксировано")
        self.assertTrue(seen[0].startswith(DIGEST_MANIFEST + "."))

    def test_nothing_temporary_survives_the_write(self):
        record_digest(self.dir, "L0.jsonl", self._file("L0.jsonl", b"z"))
        self.assertEqual(
            [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
