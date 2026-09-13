"""THE TRACE OF WHAT WAS CREATED CAN BE READ, AND "DID NOT LOOK" IS DISTINGUISHABLE FROM "EMPTY".

THE MEASUREMENT THAT PAID FOR THIS FILE (17.08.2026, the `prod-live` tree).
The entire public surface of `created_ledger` was WRITE-ONLY: the registry
was written and read by no one anywhere in the tree. In the live file that
day — **31 rows, 475 entries of the `op_id → element_id` map** — of which
23 rows had zero created. This is exactly NAKAZ clause 9: "the model did not
feel what it had touched — the map is guaranteed and consumed by no one".

🔴 THE RETURN CONTRACT WAS PAID FOR BY THE VERY FIRST RUN. The reader's
first edition handed back only rows. The file sits with 600 permissions, the
reader got a `PermissionError` and returned an empty tuple — "could not look"
and "nothing was created" became indistinguishable TO THE CALLER, meaning
the module guarding against a lost trace would itself have lost the trace.
The return became the pair `(rows, refusal)` — §18.2 of this package's law,
applied to reading.

Run:
    venv/bin/python -m pytest kir/tests/test_created_ledger_reader.py -q
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kir import created_ledger as CL


def _row(ts: str, created: dict, **kw) -> dict:
    row = {"schema_version": CL.SCHEMA_VERSION, "ts": ts, "query_id": "",
           "turn_id": "", "action_id": "", "revit_version": "",
           "plan_digest": "", "family": "", "created": created,
           "created_count": sum(len(v) for v in created.values())}
    row.update(kw)
    return row


class TheTraceIsReadable(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._dir.name) / "kir_created_ids.jsonl"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _write(self, *rows: dict) -> None:
        with self.path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_a_missing_file_is_a_named_refusal_not_an_empty_answer(self):
        rows, why = CL.read_created(self.path)
        self.assertEqual(rows, ())
        self.assertTrue(why, "пустой ответ без причины неотличим от «пусто»")
        self.assertIn(str(self.path), why)

    def test_an_unreadable_file_names_the_refusal(self):
        """The case that PAID FOR the contract: the prod registry sits with 600 permissions."""
        self._write(_row("2026-08-17T10:00:00.000+00:00", {"w1": ["1"]}))
        self.path.chmod(0o000)
        try:
            rows, why = CL.read_created(self.path)
        finally:
            self.path.chmod(0o644)
        if rows:  # a run as root can read anything — then there is no such case
            self.skipTest("процесс читает файл с правами 000 (root)")
        self.assertEqual(rows, ())
        self.assertIn("не прочитать", why)

    def test_an_empty_read_says_so_with_an_empty_refusal(self):
        self._write()
        rows, why = CL.read_created(self.path)
        self.assertEqual((rows, why), ((), ""),
                         "«смотрел, там пусто» — единственный случай, где "
                         "причина обязана быть ПУСТОЙ")

    def test_the_map_is_op_id_to_element_id(self):
        self._write(_row("2026-08-17T10:00:00.000+00:00",
                         {"w1": ["277144"], "w2": ["277145", "277146"]}))
        rows, why = CL.read_created(self.path)
        self.assertEqual(why, "")
        self.assertEqual(CL.created_index(rows),
                         {"w1": "277144", "w2": "277145"})

    def test_a_broken_line_is_skipped_and_counted(self):
        with self.path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_row("2026-08-17T10:00:00.000+00:00",
                                     {"w1": ["1"]})) + "\n")
            fh.write("{это не json\n")
        rows, why = CL.read_created(self.path)
        self.assertEqual(len(rows), 1, "битая строка спрятала целую")
        self.assertIn("битых", why, "битая строка проглочена молча")

    def test_the_later_row_wins_and_the_window_filters(self):
        self._write(_row("2026-08-17T10:00:00.000+00:00", {"w1": ["111"]}),
                    _row("2026-08-17T20:00:00.000+00:00", {"w1": ["222"]}))
        rows, _ = CL.read_created(self.path)
        self.assertEqual(CL.created_index(rows), {"w1": "222"},
                         "свежий ответ полезнее старого — так и объявлено")
        late, _ = CL.read_created(self.path, since="2026-08-17T15")
        self.assertEqual(len(late), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
