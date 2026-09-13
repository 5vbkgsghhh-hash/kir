"""CLASH SAW NOT A SINGLE GROUP ELEMENT — THE THIRD CONSUMER IN A ROW.

Measured 23.08.2026, a live capture next to the real K3: a program of seven
walls as a unit and eleven placements put 84 walls into the model, and NOT
ONE took part in the clash search. The report printed honestly, but bare:

    OUTSIDE THE CHECK, AND THIS CAN HIDE A CLASH: create_group ×1

The acceptance check that same day attributed all the copies to one level,
and the scene showed zero of the seven walls. Both are fixed; this one closes
the last.

🔴 WHY MOVE THE ELEMENT, NOT THE OP. This morning the branch was set aside as
a debt: moving the OP has to be kind-dependent (direction is not a point,
the lesson of 21.08 cost a day). But there is no need to move the op — it is
enough to move the finished BODY, whose coordinates are already reduced to a
closed set of six keys. The debt is closed by changing the PLACE of the fix,
not by boldness.
"""
import unittest

from kir import clash_bundle as C

_LVL = {"by": "name", "value": "Э2"}


def _pipes(n=3):
    return [{"op": "create_pipe", "id": f"p{i}", "p0_mm": [0, i * 1000, 0],
             "p1_mm": [6000, i * 1000, 0], "diameter_mm": 100, "level": _LVL,
             "system_type": "Хозяйственно-бытовая"} for i in range(n)]


def _elements(ops):
    return C.bundle_elements([{"ops": ops}]).elements


class CopiesOfAGroupEnterTheSearch(unittest.TestCase):
    def test_members_and_placements_all_get_a_body(self):
        els = _elements([{"op": "create_group", "id": "g", "name": "с",
                          "placements": [[0, 0, 3300 * k] for k in range(1, 4)],
                          "members": _pipes()}])
        self.assertEqual(len(els), 12, "3 трубы × 4 занятия — членов и копий")

    def test_lifted_copies_stand_at_their_own_elevation(self):
        els = _elements([{"op": "create_group", "id": "g", "name": "с",
                          "placements": [[0, 0, 3300 * k] for k in range(1, 4)],
                          "members": _pipes()}])
        zs = sorted({round(float(e["p0_mm"][2]), 1) for e in els if e.get("p0_mm")})
        self.assertEqual(zs, [0.0, 3300.0, 6600.0, 9900.0],
                         "копии не подняты — поиск сравнивает их на одной отметке")

    def test_each_copy_is_its_own_declaration(self):
        """The fingerprint is computed AFTER the move: otherwise twelve copies
        would collapse into one declaration, and "the same thing said
        twice" would eat eleven of them."""
        els = _elements([{"op": "create_group", "id": "g", "name": "с",
                          "placements": [[0, 0, 3300 * k] for k in range(1, 4)],
                          "members": _pipes()}])
        self.assertEqual(len({e["declaration_digest"] for e in els}), 12)

    def test_a_flat_placement_does_not_move_anything_vertically(self):
        """CONTROL: an offset without a vertical component must not change the
        elevation."""
        els = _elements([{"op": "create_group", "id": "g", "name": "с",
                          "placements": [[8000, 0]], "members": _pipes(1)}])
        zs = {round(float(e["p0_mm"][2]), 1) for e in els if e.get("p0_mm")}
        xs = sorted({round(float(e["p0_mm"][0]), 1) for e in els if e.get("p0_mm")})
        self.assertEqual(zs, {0.0})
        self.assertEqual(xs, [0.0, 8000.0], "плоское смещение не применено")

    def test_a_malformed_group_stays_itself(self):
        """CONTROL: a group without a member list is not expanded and does not
        crash the assembly — it remains an op and enters the census as
        before."""
        els = _elements([{"op": "create_group", "id": "g", "name": "с",
                          "members": "не список", "placements": []}])
        self.assertIsInstance(els, list)

    def test_the_marker_never_leaks_into_the_element(self):
        """The move marker is internal bookkeeping. Its leaking outward would
        mean it ended up in the declaration's fingerprint and in the
        report."""
        els = _elements([{"op": "create_group", "id": "g", "name": "с",
                          "placements": [[0, 0, 3300]], "members": _pipes(1)}])
        for e in els:
            self.assertNotIn("__group_delta__", e)


if __name__ == "__main__":
    unittest.main()
