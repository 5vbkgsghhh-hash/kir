"""The prefix on HAB000 also reaches the COMPOSITE form, not just the flat one.

🔴 WHAT THIS FILE WAS BOUGHT BY: THE MEASUREMENT OF 25.08.2026.

`_hab000_names_the_real_cause` explains to the author why the judge read zero
rooms: it takes elevations ONLY from the program itself, and without
`create_level`, every element standing on that level is discarded along with
it. This is the boundary of SELF-CHECK, not a verdict on the building — and
without this caveat the author reads «model has no rooms; the building must
NOT read as valid» as a verdict.

The traversal counted operations only at the TOP level of the program.
Running the same program in two forms:

    FLAT     (20 create_room in a row)          prefix: 583 characters
    IN GROUP (the same 20 inside a group)       prefix: 🔴 EMPTY

That is, the prefix went dark exactly for the form that this very module
teaches: the unit of intent is the GROUP, 82.6% of the operations of a real
building live inside them.

THE SAME FORM HAS ALREADY BEEN CLOSED IN THE TREE THREE TIMES in these same
24 hours: `compiler._apply_defaults_with_trace`, `ground.compiler_choices`,
and `spec.group_member_yields_one` — all of them descend into `members`. This
traversal did not descend.
"""

from __future__ import annotations

import unittest

from kir.course import _hab000_names_the_real_cause as _приставка

_ВЕРДИКТ = "HAB000: model has no rooms; the building must NOT read as valid"


def _комнаты(n: int = 20) -> list[dict]:
    return [{"op": "create_room", "id": f"r{i}", "xy": [i * 1000.0, 0.0],
             "level": {"by": "name", "value": "Этаж 1"}} for i in range(n)]


class ПриставкаВидитЧленовГруппы(unittest.TestCase):

    def test_плоская_форма_объясняется(self):
        т = _приставка(_ВЕРДИКТ, {"ops": _комнаты()}, False)
        self.assertTrue(т, "приставка исчезла и у плоской формы — стенд негоден")
        self.assertIn("граница САМОПРОВЕРКИ", т)

    def test_композитная_форма_объясняется_тоже(self):
        программа = {"ops": [{
            "op": "create_group", "id": "g1", "name": "Квартира",
            "members": _комнаты(),
            "placements": [{"xy": [0.0, 0.0], "rotation_deg": 0.0}]}]}
        т = _приставка(_ВЕРДИКТ, программа, False)
        self.assertTrue(
            т, "в группе приставка гаснет: автор читает границу самопроверки "
               "как приговор зданию, и чинит то, что не сломано")
        self.assertIn("20", т, "число помещений посчитано мимо членов группы")

    def test_вложенная_группа_тоже_считается(self):
        """Groups nest; the traversal must be recursive, not one level deep —
        otherwise the same defect returns one floor deeper."""
        программа = {"ops": [{
            "op": "create_group", "id": "g1", "name": "Дом",
            "members": [{"op": "create_group", "id": "g2", "name": "Квартира",
                         "members": _комнаты(),
                         "placements": [{"xy": [0.0, 0.0]}]}],
            "placements": [{"xy": [0.0, 0.0], "rotation_deg": 0.0}]}]}
        self.assertTrue(_приставка(_ВЕРДИКТ, программа, False))

    def test_КОНТРОЛЬ_уровень_в_группе_снимает_приставку(self):
        """The prefix explains the ABSENCE of `create_level`. If a level is
        declared — even inside a group — there is nothing to explain, and the
        prefix would be noise. The descent must see BOTH kinds of operations,
        not only rooms."""
        программа = {"ops": [{
            "op": "create_group", "id": "g1", "name": "Квартира",
            "members": [{"op": "create_level", "id": "L1", "name": "Этаж 1",
                         "elev_mm": 0.0}, *_комнаты()],
            "placements": [{"xy": [0.0, 0.0], "rotation_deg": 0.0}]}]}
        self.assertEqual(_приставка(_ВЕРДИКТ, программа, False), "")

    def test_КОНТРОЛЬ_без_помещений_приставки_нет(self):
        программа = {"ops": [{"op": "create_wall", "id": "w1"}]}
        self.assertEqual(_приставка(_ВЕРДИКТ, программа, False), "")

    def test_КОНТРОЛЬ_чужой_вердикт_не_трогается(self):
        self.assertEqual(_приставка("HAB004: что-то другое",
                                    {"ops": _комнаты()}, False), "")


if __name__ == "__main__":
    unittest.main()
