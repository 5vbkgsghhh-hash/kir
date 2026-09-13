"""ONE JOURNAL HAS ONE DOOR FOR WRITING. WHOEVER WRITES AROUND IT WRITES A LIST, NOT A JOURNAL.

Audit findings `F-181` and `F-159` (class P5-B), `kir/live/journal.restore`.
Both are about ONE spot: lifting from disk put a `ProgramRecord` straight
into `journal.records`, bypassing `SessionJournal.append`.

`records.append` builds a LIST; a journal is a list PLUS bookkeeping:
`ops_held`, `last_ts`, `datums`/`_datum_keys`, eviction. The lift built none
of that. Measurement BEFORE the fix:

    LIVE   : records 2 | ops_held 2 | datums 1
    LIFTED : records 2 | ops_held 0 | datums 0

🔴 THE CONSEQUENCE FOR THE VIEWER MATTERS MORE THAN THE BOOKKEEPING ITSELF
(`F-159`). `base_digest` is computed from the session's datums; a lifted one
has ZERO of them, and the base signature diverges:

    base_digest of the LIFTED e0da6658…   vs. LIVE 1b8cac0d…

The next delta is counted from a base the client does not have — "showed a
building with no floors." This is the same family as "showed one thing,
executed another," just from a third angle.

🔴 A THIRD DEFECT, FOUND WHILE FIXING AND NOT NAMED IN THE PACKAGES.
`restore(key, path="/…")` with a STRING used to fail: `journal_store.read_events`
calls `target.exists()`, a string cannot do that, `AttributeError` was caught
by the generic handler, and `store_unreadable` came out the other side —
meaning the refusal BLAMED THE STORE for the reader having passed a
different type. Measurement: the same file with `Path` lifted fine (2
records), with `str` — "the journal cannot be read."

THE COST OF THE FIX, NAMED: the journal door calls `_evict()`, so lifting a
history longer than the cap now TRIMS IT FROM THE HEAD — which is how caps
are meant to work, but the lift used to raise EVERYTHING before. The loss is
counted and goes into the summary (`programs_evicted`), instead of vanishing
silently.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

from kir.live import journal as J
from kir.viewer import live_scene as L

_LEVEL = {"op": "create_level", "id": "lv", "name": "L1", "elev_mm": 0.0}
_WALL = {"op": "create_wall", "id": "w0", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "height_mm": 3000, "level": {"by": "name", "value": "L1"}}


class ПоднятоеРавноПрожитому(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = os.path.join(self._dir.name, "j.jsonl")
        self._saved = os.environ.get("KIR_JOURNAL_STORE_PATH")
        os.environ["KIR_JOURNAL_STORE_PATH"] = self.path
        self.addCleanup(self._restore_env)
        self.key = J.key_for("устр-подъём", "док-подъём")
        J.reset(self.key)
        self.addCleanup(J.reset, self.key)
        J.append(self.key, {"ops": [_LEVEL]})
        J.append(self.key, {"ops": [_WALL]})
        live = J.get(self.key)
        self.lived = (len(live.records), live.ops_held, len(live.datums),
                      live.next_seq, [r.seq for r in live.records])
        self.lived_base = L.base_digest(list(live.datums), None, 0)

    def _restore_env(self) -> None:
        if self._saved is None:
            os.environ.pop("KIR_JOURNAL_STORE_PATH", None)
        else:
            os.environ["KIR_JOURNAL_STORE_PATH"] = self._saved

    def _lift(self, **kw):
        J.reset(self.key)
        info = J.restore(self.key, **kw)
        return info, J.get(self.key)

    def test_the_accounting_survives_the_lift(self) -> None:
        """🔴 THE SUBJECT OF F-181. A lifted session used to differ from a lived
        one in EVERYTHING except the number of records."""
        _info, up = self._lift()
        self.assertEqual(
            (len(up.records), up.ops_held, len(up.datums), up.next_seq,
             [r.seq for r in up.records]),
            self.lived)

    def test_the_delta_base_of_a_lifted_session_matches_the_lived_one(self) -> None:
        """🔴 THE SUBJECT OF F-159, and it matters more than the bookkeeping: the
        client was getting a delta from a base it did not have."""
        _info, up = self._lift()
        self.assertEqual(L.base_digest(list(up.datums), None, 0),
                         self.lived_base)

    def test_the_lift_keeps_the_sequence_numbers_from_disk(self) -> None:
        """The journal door does NOT TOUCH `seq` — it accepts a record as given.
        If it ever starts touching it, a lift will renumber the history
        silently, and delta addresses will drift apart."""
        _info, up = self._lift()
        self.assertEqual([r.seq for r in up.records], [0, 1])

    def test_a_string_path_is_a_legal_input(self) -> None:
        """🔴 THE THIRD DEFECT: the refusal blamed the STORE for the reader having
        passed a different type. Both kinds of path are obligated to give
        the same answer."""
        by_str, _ = self._lift(path=self.path)
        by_path, _ = self._lift(path=pathlib.Path(self.path))
        self.assertEqual(by_str.get("restored"), 2)
        self.assertIsNone(by_str.get("refused"))
        self.assertEqual(by_str.get("restored"), by_path.get("restored"))

    def test_a_missing_file_still_refuses_by_name(self) -> None:
        """🔴 THE GREEN OUTCOME OF A REFUSAL. Type coercion has no right to swallow
        a REAL missing file."""
        info, _ = self._lift(path=os.path.join(self._dir.name, "нет.jsonl"))
        self.assertEqual(info.get("restored"), 0)
        self.assertTrue(info.get("refused"))

    def test_the_lift_names_what_it_evicted(self) -> None:
        """THE COST OF THE FIX IS COUNTED. The door calls `_evict()`; the lift used
        to raise everything before, so the behavior changed — and staying
        silent about it would mean introducing a loss with no number."""
        info, _ = self._lift()
        self.assertIn("programs_evicted", info)
        self.assertEqual(info["programs_evicted"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
