"""A group member's path addresses a slot belonging to a FOREIGN op — no
advice is given about it.

🔴 WHAT THIS FILE COST — MEASURED ON 25.08.2026.

On a refusal inside a group, `ground.py` rewrites the diagnostic address:
`level` -> `members[w1].level`, and `op_id` to the group's id. The
refusal's tail (`authoring_validation._slot_tail`) takes the ROOT of the
path via `_base_field`:

    _base_field('members[w1].level')        -> 'members'
    _base_field('members[?].levels[0].id')  -> 'members'

`members` is a REAL slot of `create_group`, so the guard "the field is not
in the registry — stay silent" does not fire, and the author gets advice
about a slot that has nothing to do with the defect.

WHAT REPRODUCED AND WHAT DID NOT — I NAME BOTH. For the three ordinary
kinds of authoring error (a missing slot, an unresolvable reference, the
wrong type), the tail inside a group IS correct: it is built INSIDE the
member's lift, BEFORE the address is rewritten. The 25.08 run on all three
gave "fix level … create_wall," same as outside a group. The case where
the tail is added LATER (a defect of our own snapshot, `KIR-G106`) could
not be constructed, and this is recorded as NOT KNOWN, not as refuted.

But the mechanism exists and is checked directly: `_slot_tail` on a
member's path produces advice about `members`. It is dangerous regardless
of which input calls it, and it is closed here.

WHY SILENCE, NOT CORRECT ADVICE. Giving correct advice requires knowing
the MEMBER's op, and at this seam only the group's op is known. The file
already carries this law verbatim: "DO NOT INVENT … silence is more
honest than a guessed piece of advice: invented advice is worse than
silence, it gets checked on the next turn."
"""

from __future__ import annotations

import unittest

from kir.authoring_validation import _slot_tail
from kir.diag import Diagnostic, TYPE_BAD_TYPE


def _д(field: str) -> Diagnostic:
    return Diagnostic(code=TYPE_BAD_TYPE, message_ru="проверка",
                      field_name=field, op_id="g1")


class ПутьЧленаНеПолучаетЧужогоСовета(unittest.TestCase):

    def test_путь_члена_молчит(self):
        хвост = _slot_tail("create_group", _д("members[w1].level"),
                           with_roster=True)
        self.assertEqual(
            хвост, "",
            f"хвост про ЧУЖОЙ слот: {хвост[:120]!r}. Дефект в `level` стены, "
            f"а совет про `members` группы — автор чинит исправное.")

    def test_путь_члена_без_имени_тоже_молчит(self):
        self.assertEqual(
            _slot_tail("create_group", _д("members[?].levels[0].id"),
                       with_roster=True), "")

    def test_КОНТРОЛЬ_свой_слот_группы_совет_даёт(self):
        """The instrument must be able to speak. A genuine `members`
        defect is a defect of the group, and there is something to say
        about it."""
        хвост = _slot_tail("create_group", _д("members"), with_roster=True)
        self.assertIn("members", хвост)
        self.assertNotEqual(хвост, "")

    def test_КОНТРОЛЬ_обычный_слот_обычного_опа_не_тронут(self):
        хвост = _slot_tail("create_wall", _д("level"), with_roster=True)
        self.assertIn("level", хвост)

    def test_КОНТРОЛЬ_вложенный_путь_своего_слота_по_прежнему_советует(self):
        """`contour.outer.points_mm` -> `contour` — trimming to the root
        is legitimate on its own and stays: silence is required only for
        a GROUP MEMBER'S path."""
        хвост = _slot_tail("create_floor_by_contour",
                           _д("contour.outer.points_mm"), with_roster=True)
        self.assertNotEqual(хвост, "", "обрезание корня сломано целиком")


if __name__ == "__main__":
    unittest.main()
