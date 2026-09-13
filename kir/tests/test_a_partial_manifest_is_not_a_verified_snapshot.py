"""THE MANIFEST ANSWERS ABOUT ITS OWN LINES, BUT IT IS READ AS IF ABOUT THE SNAPSHOT (F-343).

`verify_digests` goes BY THE MANIFEST'S LINES: a file that is not in the
manifest is NEVER seen by it — which is why it cannot say anything about
it. A directory with two snapshots and a manifest of one line returned
`{}`, that is, "everything matched" exactly where less than half had been
checked.

🔴 HALF OF THE FIX STOOD UNCALLED. The closed list `expected=` was set up
by that same commit and was NOT PASSED BY A SINGLE call: `_verify_all`
called `verify_digests(directory)` without it. An instrument that is
written and never wired in is `E-7`, and here it was written RIGHT NEXT TO
a defect that never asked for it.

WHAT THIS FILE GUARDS — THREE DIFFERENT SUBJECTS, AND THEY MUST NOT BE CONFUSED:

    the line is absent, the file exists    the check DID NOT HAPPEN for this name -> code 2
    the line exists, the bytes differ      the check happened and found corruption -> code 1
    a name being APPENDED TO               the line's absence is BY DESIGN         -> stay silent

The third is bought by measurement: with the full `SNAPSHOT_FILES`, the
live corpus produced 28 alerts across 19 decompiles, of which 16 were
`L0.jsonl`, and in ALL sixteen it lies RAW. Sixteen out of sixteen is not
a distribution but a construction: the guard would go red forever, and for
a reason there is nothing to fix.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from kir.decompile.snapshot_io import record_digest
import kir.instruments.snapshot_janitor as J


def _snapshot(root: Path, name: str, files: dict[str, str]) -> Path:
    """A directory the cleaner recognizes as a snapshot: `status.json` + files."""
    directory = root / name
    directory.mkdir()
    (directory / "status.json").write_text(
        json.dumps({"stage": "done", "updated_at": time.time()}),
        encoding="utf-8")
    for filename, body in files.items():
        (directory / filename).write_text(body, encoding="utf-8")
    return directory


def _verify(root: Path) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = J._verify_all(root)
    return code, out.getvalue()


class APartialManifestIsNotAVerifiedSnapshot(unittest.TestCase):

    def test_a_name_on_disk_without_a_row_is_named_and_not_swallowed(self):
        """THE EXACT incident: two snapshots, a manifest of one line."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _snapshot(root, "разбор", {"passport.json": "{}",
                                           "tree.json": "{}"})
            record_digest(d, "passport.json", b"{}")
            code, text = _verify(root)
        self.assertEqual(code, 2, text)
        self.assertIn("tree.json", text,
                      "отказ обязан назвать ИМЯ, иначе следующий пойдёт "
                      "искать его сам")
        self.assertIn("ИМЁН БЕЗ СТРОКИ:  1", text)
        self.assertIn("расхождений:      0", text,
                      "рода не смешались: байты никто не портил")

    def test_a_full_manifest_is_accepted(self):
        """The second outcome. A guard that always goes red guards nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _snapshot(root, "разбор", {"passport.json": "{}",
                                           "tree.json": "{}"})
            record_digest(d, "passport.json", b"{}")
            record_digest(d, "tree.json", b"{}")
            code, text = _verify(root)
        self.assertEqual(code, 0, text)
        self.assertIn("ИМЁН БЕЗ СТРОКИ:  0", text)

    def test_an_appended_name_without_a_row_is_not_an_alarm(self):
        """🔴 THE BOUNDARY BOUGHT BY MEASUREMENT: 16 false alarms out of 28.

        `L0.jsonl` is in `APPEND_TARGETS`: the cold path does not compress
        it, so `record_digest` is not called on it, so it has no manifest
        line BY DESIGN. A false alarm costs more than a miss — it kills
        trust in the whole instrument.
        """
        self.assertIn("L0.jsonl", J.APPEND_TARGETS)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _snapshot(root, "разбор", {"passport.json": "{}",
                                           "L0.jsonl": '{"a":1}\n'})
            record_digest(d, "passport.json", b"{}")
            code, text = _verify(root)
        self.assertEqual(code, 0, text)
        self.assertNotIn("L0.jsonl", text)

    def test_a_changed_byte_stays_a_mismatch_and_not_a_missing_row(self):
        """The kinds differ by STRUCTURE. Corruption must remain code 1."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _snapshot(root, "разбор", {"passport.json": "{}"})
            record_digest(d, "passport.json", b"{}")
            (d / "passport.json").write_text('{"подменено": 1}',
                                             encoding="utf-8")
            code, text = _verify(root)
        self.assertEqual(code, 1, text)
        self.assertIn("расхождений:      1", text)
        self.assertIn("ИМЁН БЕЗ СТРОКИ:  0", text,
                      "порча содержимого — НЕ «строки нет»: следующий ход у "
                      "них разный, и код возврата обязан их различать")

    def test_both_roda_at_once_are_both_reported(self):
        """Corruption and a miss in one decompile: code 1 takes priority, but the number is still visible."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _snapshot(root, "разбор", {"passport.json": "{}",
                                           "tree.json": "{}"})
            record_digest(d, "passport.json", b"{}")
            (d / "passport.json").write_text('{"подменено": 1}',
                                             encoding="utf-8")
            code, text = _verify(root)
        self.assertEqual(code, 1, text)
        self.assertIn("расхождений:      1", text)
        self.assertIn("ИМЁН БЕЗ СТРОКИ:  1", text,
                      "порча не имеет права ЗАСЛОНИТЬ пропуск: это два "
                      "факта, и одно число не может нести оба")

    def test_the_witnessed_list_is_the_snapshot_list_minus_the_appended(self):
        """One carrier: the list is not reassembled anywhere else."""
        self.assertEqual(
            J.WITNESSED_SNAPSHOT_FILES,
            tuple(n for n in J.SNAPSHOT_FILES if n not in J.APPEND_TARGETS))
        self.assertTrue(J.WITNESSED_SNAPSHOT_FILES,
                        "пустой закрытый список сделал бы сверку зелёной по "
                        "построению — ровно тот дефект, что чинится")
        for name in J.APPEND_TARGETS:
            with self.subTest(appended=name):
                self.assertIn(
                    name, J.SNAPSHOT_FILES,
                    "исключение на имя, которого нет в списке слепка, — "
                    "призрак: оно ничего не исключает и лжёт читателю")


if __name__ == "__main__":
    unittest.main()
