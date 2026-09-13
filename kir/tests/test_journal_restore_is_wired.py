"""THE JOURNAL RESTORE WAS BUILT, COVERED BY TESTS, AND CALLED BY NO ONE.

Measured 23.08.2026: `live.journal.restore` had ZERO callers. The building's
memory across service restarts existed on disk and did not exist at
runtime — after a restart, "the whole building" started from an empty
place, and programs from past turns lay right there, never handed to
anyone. The generic class of this defect: built, covered, not wired in.

What is guarded here is the WIRING, not the restore itself (it has its own
tests):

  * the first program of a new key calls restore;
  * the store is read ONCE per key — a session with no history gets the
    answer "restored 0", and paying for a disk read for a known zero on
    every program is not allowed;
  * restore is NOT called when the session is already alive in this
    process;
  * the `KUKAI_JOURNAL_RESTORE=0` switch reverts to the previous behavior.
"""
import os
import unittest
from unittest import mock

from kir.live import journal as J


def _prog(n=1):
    return {"ops": [{"op": "create_level", "id": f"l{n}",
                     "name": f"Э{n}", "elev_mm": 3300 * n}]}


class TheFirstProgramOfAKeyLiftsTheJournal(unittest.TestCase):
    def setUp(self):
        J._RESTORE_TRIED.clear()
        J._SESSIONS.clear()

    def test_it_is_called_once_for_a_fresh_key(self):
        with mock.patch.object(J, "restore",
                               return_value={"restored": 0}) as m:
            J.append(("dev", "doc"), _prog(1))
        self.assertEqual(m.call_count, 1, "подъём не позван на первой программе")

    def test_the_store_is_read_once_per_key_not_per_program(self):
        with mock.patch.object(J, "restore",
                               return_value={"restored": 0}) as m:
            for i in range(5):
                J.append(("dev", "doc"), _prog(i))
        self.assertEqual(m.call_count, 1,
                         "склад перечитывается на каждой программе — "
                         "это плата диском за известный ноль")

    def test_a_live_session_is_not_lifted_over(self):
        """A second key must not drag along a restore for the first one, and vice versa."""
        with mock.patch.object(J, "restore", return_value={"restored": 0}) as m:
            J.append(("dev", "a"), _prog(1))
            J.append(("dev", "b"), _prog(2))
            J.append(("dev", "a"), _prog(3))
        self.assertEqual(m.call_count, 2, "подъём на ключ, а не на программу")

    def test_the_kill_switch_restores_the_old_behaviour(self):
        with mock.patch.dict(os.environ, {"KUKAI_JOURNAL_RESTORE": "0"}):
            with mock.patch.object(J, "restore") as m:
                J.append(("dev", "doc"), _prog(1))
            self.assertEqual(m.call_count, 0)

    def test_a_raising_restore_never_breaks_the_turn(self):
        """Restore has no right to drop a turn — the program must still get written."""
        with mock.patch.object(J, "restore", side_effect=RuntimeError("склад упал")):
            rec = J.append(("dev", "doc"), _prog(1))
        self.assertIsNotNone(rec, "ход умер из-за подъёма")


if __name__ == "__main__":
    unittest.main()
