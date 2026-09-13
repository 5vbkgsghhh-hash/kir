"""THE REVISION FEED: WHAT IT MUST SAY, AND WHAT IT MUST NOT SAY.

The adapter computes nothing: the journal is written by
`decompile/journal.py`, the diff is computed by
`decompile/merkle_report.diff_report`, the tree is read by
`viewer/pull_request._tree`. What is checked here is exactly what belongs
to the adapter — REFUSALS, ORDER and BOUNDARIES.

🔴 THE FILE'S MAIN CLAIM IS ABOUT THE CAUSE OF A REFUSAL, AND IT WAS PAID
FOR LIVE ON 28.08.2026. The first edition of `_light` swallowed any read
error, and on the live corpus (journals sit as `-rw-------` owned by the
service user), an instrument run by a different user printed: "files
exist, but none carries the `revisions` field." The files did carry the
field. The refusal named the WRONG cause and would have sent someone to
fix the journal format instead of the access rights — the "instrument is
right, but about a different subject" form, this time inside the
refusal's own text.

Run: PYTHONPATH=/opt/kir python3.12 -m pytest -q kir/viewer/tests/test_history.py
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

from kir.viewer import history as H

ЖУРНАЛ = {
    "schema": "kir-building-log/1",
    "journal_version": "journal/1",
    "doc_name": "Проект1",
    "key": "Проект1-a27186b9df3e99c6",
    "revisions": [
        {"revision": 0, "doc_stamp": "s0", "out_dir": "backend/data/decompile/раньше",
         "revit_version": "2023", "leaves": 1556,
         "recorded_at": "2026-08-19T10:27:27+00:00", "event_hash": "aa"},
        {"revision": 1, "doc_stamp": "s1", "out_dir": "backend/data/decompile/позже",
         "revit_version": "2023", "leaves": 1558,
         "recorded_at": "2026-08-19T10:48:06+00:00", "event_hash": "bb"},
    ],
    # The event carries STATE; the adapter must not read it at all.
    "journal": {"version": "journal/1", "events": [{"index": 0, "payload": {"x": "…"}}]},
}


class _СоСкладом(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.journals = self.root / H.JOURNAL_DIR
        self.journals.mkdir()
        H._LIGHT.clear()
        self.addCleanup(H._LIGHT.clear)

    def _write(self, name: str, payload) -> pathlib.Path:
        path = self.journals / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path


class ЛентаЧитается(_СоСкладом):

    def test_revisions_come_newest_first(self) -> None:
        """The freshest revision comes first: a person opens the feed for
        the latest one."""
        self._write("проект1.json", ЖУРНАЛ)
        цепочки = [c for c in H.chains(self.root) if c["count"]]
        self.assertEqual(len(цепочки), 1)
        ревизии = цепочки[0]["revisions"]
        self.assertEqual([r["revision"] for r in ревизии], [1, 0])

    def test_the_path_becomes_a_run_name(self) -> None:
        """THE PATH DOES NOT REACH THE SCREEN. `out_dir` is recorded as
        relative and is resolved against the service's working directory;
        showing it to a person would mean showing the layout of someone
        else's machine."""
        self._write("проект1.json", ЖУРНАЛ)
        имена = [r["run"] for r in H.chains(self.root)[0]["revisions"]]
        self.assertEqual(имена, ["позже", "раньше"])

    def test_the_chain_is_found_by_a_run(self) -> None:
        self._write("проект1.json", ЖУРНАЛ)
        self.assertEqual(
            (H.chain_for_run(self.root, "раньше") or {}).get("doc_name"), "Проект1")

    def test_a_run_outside_history_is_none_not_a_refusal(self) -> None:
        """`None` means exactly itself: the decompile predates the journal
        being turned on. A refusal here would accuse a perfectly sound
        decompile."""
        self._write("проект1.json", ЖУРНАЛ)
        self.assertIsNone(H.chain_for_run(self.root, "чужой"))


class ОтказНазываетПричину(_СоСкладом):

    def test_no_journal_dir_is_named(self) -> None:
        пусто = pathlib.Path(self.tmp.name) / "нет-такого"
        with self.assertRaises(H.HistoryUnavailable) as поймано:
            H.chains(пусто)
        self.assertIn("не существует", str(поймано.exception))

    def test_an_unreadable_file_is_not_blamed_on_its_format(self) -> None:
        """🔴 THAT VERY ONE. Rights and format are different causes and different people."""
        путь = self._write("закрытый.json", ЖУРНАЛ)
        os.chmod(путь, 0o000)
        self.addCleanup(os.chmod, путь, 0o644)
        if os.access(путь, os.R_OK):        # under root, permissions don't get in the way
            self.skipTest("процесс читает файл вопреки правам — под root "
                          "утверждение невыразимо")
        with self.assertRaises(H.HistoryUnavailable) as поймано:
            H.chains(self.root)
        текст = str(поймано.exception)
        self.assertIn("закрытый.json", текст)
        self.assertNotIn("не журнал здания", текст,
                         "отказ обвинил ФОРМАТ там, где дело в правах")

    def test_a_foreign_json_is_named_as_such(self) -> None:
        self._write("чужой.json", {"что-то": "другое"})
        with self.assertRaises(H.HistoryUnavailable) as поймано:
            H.chains(self.root)
        self.assertIn("не журнал здания", str(поймано.exception))

    def test_an_unreadable_file_does_not_vanish_from_a_good_answer(self) -> None:
        """A feed that silently lost a building reads as "it never existed"."""
        self._write("проект1.json", ЖУРНАЛ)
        путь = self._write("закрытый.json", ЖУРНАЛ)
        os.chmod(путь, 0o000)
        self.addCleanup(os.chmod, путь, 0o644)
        if os.access(путь, os.R_OK):
            self.skipTest("процесс читает файл вопреки правам")
        строки = H.chains(self.root)
        непрочитанные = [c for c in строки if c.get("unreadable")]
        self.assertTrue(непрочитанные, "непрочитанный журнал исчез из ответа")
        self.assertIn("закрытый.json", непрочитанные[0]["unreadable"])


class СобытияНеЧитаются(_СоСкладом):
    """The event carries STATE (a multiset of canonical ops) — on the live
    corpus that is 0.3-10.9 MB per file. The light part must stay light."""

    def test_the_event_payload_is_not_carried_to_the_screen(self) -> None:
        self._write("проект1.json", ЖУРНАЛ)
        цепочка = H.chains(self.root)[0]
        self.assertNotIn("journal", цепочка)
        for row in цепочка["revisions"]:
            self.assertEqual(
                set(row) - {"revision", "doc_stamp", "run", "revit_version",
                            "leaves", "recorded_at", "event_hash"}, set())

    def test_the_cache_notices_an_appended_file(self) -> None:
        """The journal is APPENDED TO. The cache key carries mtime AND
        size: at one-second granularity, two writes within the same second
        differ only by size."""
        путь = self._write("проект1.json", ЖУРНАЛ)
        self.assertEqual(H.chains(self.root)[0]["count"], 2)
        ещё = json.loads(json.dumps(ЖУРНАЛ))
        ещё["revisions"].append(
            {"revision": 2, "doc_stamp": "s2",
             "out_dir": "backend/data/decompile/третий", "revit_version": "2023",
             "leaves": 1600, "recorded_at": "2026-08-19T11:00:00+00:00",
             "event_hash": "cc"})
        путь.write_text(json.dumps(ещё, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(H.chains(self.root)[0]["count"], 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
