"""THE SCENE DID NOT GO INSIDE THE GROUP AND SHOWED ZERO.

Measurement 23.08.2026 on a live program next to a real K3: seven walls as
one unit plus eleven instances put 84 walls into the model, and the scene
returned FOUR elements, and all four were rooms:

    census: 5 considered, 4 drawn, 1 skipped
    skip: no_level_slot · create_group × 1

The cause is named correctly ABOUT THE OP ITSELF — `create_group` has no
level slot — and incorrectly about the subject: the decision was made on
the group, and the renderer never went inside the members, even though
each of them has a level. A reader would go off to fix levels, when what
needed fixing was the recursion.

The third consumer in a row that did not know about the group: intake was
attributing the copies to a single level (fixed), the clash checker named
the blindness a debt, the scene discarded it.
"""
import unittest

from kir import preview as P

_LVL = {"by": "name", "value": "Э2"}


def _members(n=7):
    return [{"op": "create_wall", "id": f"w{i}", "p0_mm": [0, i * 1000],
             "p1_mm": [6000, i * 1000], "height_mm": 3300, "level": _LVL}
            for i in range(n)]


def _census(ops):
    return P.build_program_preview({"ops": ops}).census


class MembersOfAGroupAreDrawn(unittest.TestCase):
    def test_a_group_is_not_an_opaque_box(self):
        c = _census([{"op": "create_level", "id": "L", "name": "Э2", "elev_mm": 3300},
                     {"op": "create_group", "id": "g", "name": "секция",
                      "placements": [[0, 0, 3300 * k] for k in range(1, 12)],
                      "members": _members()}])
        self.assertEqual(c.drawn, 7,
                         "члены группы не нарисованы — сцена показывает ноль "
                         "там, где в модели стоят стены")

    def test_grouped_and_itemised_draw_the_same_members(self):
        """Occupancy 0 — the same seven walls, however you write them."""
        поштучно = _census([{"op": "create_level", "id": "L", "name": "Э2",
                             "elev_mm": 3300}] + _members())
        группой = _census([{"op": "create_level", "id": "L", "name": "Э2",
                            "elev_mm": 3300},
                           {"op": "create_group", "id": "g", "name": "с",
                            "placements": [], "members": _members()}])
        self.assertEqual(группой.drawn, поштучно.drawn)

    def test_a_malformed_group_is_left_alone(self):
        """CONTROL: a group with no member list does not expand and does not
        crash the renderer — it stays an op and lands in the census as
        before."""
        c = _census([{"op": "create_level", "id": "L", "name": "Э2", "elev_mm": 3300},
                     {"op": "create_group", "id": "g", "name": "с",
                      "members": "не список", "placements": []}])
        self.assertEqual(c.drawn, 0)
        self.assertGreaterEqual(c.omitted_total, 1)

    def test_placements_are_NOT_invented(self):
        """🔴 THE OPPOSITE-EXTREME CONTROL, and it is load-bearing.

        The temptation is to expand the instances too, showing twelve
        levels. It cannot be done: a copy sits wherever the member sits,
        plus an offset, and which level it ends up on cannot be derived
        from the program — Revit decides the assignment. Drawing it
        "approximately" would mean showing the engineer something that is
        not in the model. The eleven instances must remain UNDRAWN.
        """
        c = _census([{"op": "create_level", "id": "L", "name": "Э2", "elev_mm": 3300},
                     {"op": "create_group", "id": "g", "name": "с",
                      "placements": [[0, 0, 3300 * k] for k in range(1, 12)],
                      "members": _members()}])
        self.assertEqual(c.drawn, 7, "нарисовано больше членов — вхождения "
                                     "подрисованы догадкой")


if __name__ == "__main__":
    unittest.main()
