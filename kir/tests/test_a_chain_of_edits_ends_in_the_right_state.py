"""A create -> move -> hosted CHAIN IN ONE PROGRAM MUST END IN THE STATE
THAT WAS REQUESTED.

WHAT WAS FOUND (2026-09-07, mandate F1 «silently wrong results of chains»).
The plan attaches to the door the shape of the host wall (`__host_wall__`)
built from the AUTHORED `p0_mm/p1_mm`, and the door's point `__pt_<id>` is
computed in Python from that shape. If the same program shifted the wall
with `move_elements` BEFORE the door, the wall now stands somewhere else,
but the door's point does not: wall (0,0)-(6000,0), a shift of +1000 along
X, a door offset of 3000 -> the C# places the door at (3000, 0), i.e. 2000
mm from the wall's NEW start. The point lies on the wall, Revit accepts it,
the door's witness checks against the same constant — A GREEN RUN, A
DIFFERENT BUILDING.

WHAT IS MEASURED: NUMBERS in the emission, not the presence of a line. The
door's point is taken from `__pt_<id> = new XYZ(U(x), U(y), …)` and compared
against what the host gives at its final position as of the door.

FAIL CONTROL: replacing `geom.same_program_shift` with zero makes the first
test go red (x=3000 instead of 4000); forging the host's shape still gets
refused by `midend._assert_payload_refinement`
(test_synthetic_fields_have_one_authority). PASS CONTROL: a door BEFORE the
shift — the point does not change (test `..._before_the_move_...`).

BOUNDARY (named, not closed): the final witness of the wall's OWN creation
still expects the authored endpoints — a shift by the same program produces
a live refusal and a rollback (the `move_elements` caveat in the registry).
That is a refusal, not silence; it is not fixed here. A Z shift of the host
before the door is a named refusal, not a guess at height.

Run:
    venv/bin/python -m pytest kir/tests/test_a_chain_of_edits_ends_in_the_right_state.py -q
"""
from __future__ import annotations

import re
import unittest

from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT

LVL = {"by": "element_id", "value": 42}
SYMBOL = {"by": "element_id", "value": 7001}


def _wall(oid="MW", p0=(0, 0), p1=(6000, 0)):
    return {"op": "create_wall", "id": oid, "p0_mm": list(p0),
            "p1_mm": list(p1), "level": LVL}


def _move(oid, target, delta):
    return {"op": "move_elements", "id": oid,
            "targets": [{"by": "ref", "value": target}],
            "delta_mm": list(delta)}


def _door(oid="DR", host="MW", offset=3000):
    return {"op": "create_door", "id": oid, "host": {"by": "ref", "value": host},
            "offset_mm": offset, "symbol": SYMBOL}


def _compile(ops):
    return compile_program({"ir_version": "1.0", "intent": "цепочка", "ops": ops},
                           "2026", snapshot=GROUND_SNAPSHOT)


def _point(cs: str, oid: str) -> tuple[float, float]:
    m = re.search(rf"XYZ __pt_{oid} = new XYZ\(U\(([-0-9.]+)\), U\(([-0-9.]+)\)", cs)
    assert m, f"точка двери {oid} не найдена в эмиссии"
    return float(m.group(1)), float(m.group(2))


class ADoorAfterAMoveOfItsHost(unittest.TestCase):

    def test_the_door_lands_at_the_requested_offset_of_the_moved_wall(self):
        out = _compile([_wall(), _move("ME1", "MW", (1000, 0, 0)), _door()])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertEqual(_point(out.csharp, "DR"), (4000.0, 0.0),
                         "offset 3000 от начала СДВИНУТОЙ стены (1000,0) — это (4000,0)")

    def test_two_moves_before_the_door_accumulate(self):
        out = _compile([_wall(), _move("ME1", "MW", (1000, 0, 0)),
                        _move("ME2", "MW", (500, 250, 0)), _door()])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertEqual(_point(out.csharp, "DR"), (4500.0, 250.0))

    def test_a_door_before_the_move_keeps_its_authored_point(self):
        """PASS control: the order of the program is the order of the effects."""
        out = _compile([_wall(), _door(), _move("ME1", "MW", (1000, 0, 0))])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertEqual(_point(out.csharp, "DR"), (3000.0, 0.0))

    def test_a_move_of_another_element_does_not_shift_the_door(self):
        out = _compile([_wall(), _wall("W2", (0, 5000), (6000, 5000)),
                        _move("ME1", "W2", (1000, 0, 0)), _door()])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertEqual(_point(out.csharp, "DR"), (3000.0, 0.0))

    def test_the_witness_of_the_door_reads_the_same_moved_point(self):
        out = _compile([_wall(), _move("ME1", "MW", (1000, 0, 0)), _door()])
        self.assertTrue(out.ok)
        post = out.csharp[out.csharp.index("// post DR"):]
        self.assertIn("4000.0", post.split("\n// post", 1)[0],
                      "свидетель двери обязан сверять с точкой на сдвинутой стене")

    def test_a_vertical_move_of_the_host_before_the_door_is_a_named_refusal(self):
        """A door's height is measured from the level, not from the wall: a
        Z shift of the wall makes the door's point inexpressible — a named
        refusal, not a guess."""
        out = _compile([_wall(), _move("ME1", "MW", (0, 0, 300)), _door()])
        self.assertFalse(out.ok)
        codes = {d.code for d in out.diagnostics}
        self.assertIn("KIR-L009", codes, codes)
        d = next(d for d in out.diagnostics if d.code == "KIR-L009")
        self.assertEqual(d.op_id, "DR")

    def test_an_addressed_host_is_shifted_on_the_ground_path_too(self):
        """A second venue for the same judge: the wall's endpoints arrive
        from grids (`ground`), not literals — the shift must be accounted
        for there too."""
        wall = {"op": "create_wall", "id": "MW",
                "level": {"by": "name", "value": "Этаж 1"},
                "type": {"by": "name", "value": "ЖБ 200"}, "height_mm": 3000,
                "p0_mm": {"at_grid": ["А", "1"]},
                "p1_mm": {"at_grid": ["А", "2"]}}
        out = _compile([wall, _move("ME1", "MW", (1000, 0, 0)), _door()])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertIn("P(0, 0, 0)", out.csharp)        # grid A1 is (0,0)
        self.assertIn("P(4000, 0, 0)", out.csharp)     # grid A2 is (4000,0)
        self.assertEqual(_point(out.csharp, "DR"), (4000.0, 0.0),
                         "offset 3000 от сдвинутого начала (1000,0)")

    def test_two_moves_with_a_door_between_place_each_door_from_its_own_position(self):
        """Self-review (b): shift -> door -> shift -> door — each from the
        host's position AT ITS OWN moment."""
        out = _compile([_wall(), _move("ME1", "MW", (1000, 0, 0)), _door("D1"),
                        _move("ME2", "MW", (500, 0, 0)), _door("D2")])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertEqual(_point(out.csharp, "D1"), (4000.0, 0.0))
        self.assertEqual(_point(out.csharp, "D2"), (4500.0, 0.0))

    def test_only_move_elements_displaces_in_the_registry(self):
        """Self-review (a): there is no second displacing op in the registry
        — the sum over `move_elements` is complete BY CONSTRUCTION, not by
        hope. Should rotate/mirror/copy appear, this test will name it first."""
        from kir import spec
        from kir.registry_base import EffectKind
        movers = sorted(n for n, o in spec.OPS.items()
                        if o.effect is EffectKind.MUTATE
                        and ("delta_mm" in {p.name for p in o.params}
                             or any(k in n for k in ("move", "rotate", "mirror",
                                                     "copy", "array", "transform"))))
        self.assertEqual(movers, ["move_elements"], movers)


class AReferenceToADeletedTarget(unittest.TestCase):
    """F1: «an unknown effect does not get success». `delete X` and any
    subsequent op on X in the SAME program is a refusal on the PLAN
    (KIR-L010), not a "stale id" after a round trip through Revit."""

    def _delete(self, oid, target):
        return {"op": "delete", "id": oid, "target": target}

    def _compile(self, ops):
        return compile_program({"ir_version": "1.0", "intent": "цепочка",
                                "allow_destructive": True, "ops": ops},
                               "2026", snapshot=GROUND_SNAPSHOT)

    def _refused(self, ops, op_id, field):
        out = self._compile(ops)
        self.assertFalse(out.ok, "удалённая цель адресована — компиляция обязана отказать")
        hits = [d for d in out.diagnostics if d.code == "KIR-L010"]
        self.assertEqual([(d.op_id, d.field_name) for d in hits], [(op_id, field)],
                         [d.as_dict() for d in out.diagnostics])

    def test_move_after_delete_is_refused_on_the_plan(self):
        self._refused([_wall(), self._delete("X1", {"by": "ref", "value": "MW"}),
                       _move("ME1", "MW", (1000, 0, 0))], "ME1", "targets[0]")

    def test_change_type_after_delete_is_refused(self):
        self._refused([_wall(), self._delete("X1", {"by": "ref", "value": "MW"}),
                       {"op": "change_type", "id": "CT1",
                        "target": {"by": "ref", "value": "MW"},
                        "type": {"by": "element_id", "value": 5001}}], "CT1", "target")

    def test_a_second_delete_of_the_same_target_is_refused(self):
        self._refused([_wall(), self._delete("X1", {"by": "ref", "value": "MW"}),
                       self._delete("X2", {"by": "ref", "value": "MW"})], "X2", "target")

    def test_a_door_on_a_deleted_wall_is_refused(self):
        self._refused([_wall(), self._delete("X1", {"by": "ref", "value": "MW"}),
                       _door()], "DR", "host")

    def test_an_existing_element_deleted_by_id_is_not_moved_afterwards(self):
        self._refused([self._delete("X1", {"by": "element_id", "value": 8145901}),
                       {"op": "move_elements", "id": "ME1",
                        "targets": [{"by": "element_id", "value": 8145901}],
                        "delta_mm": [1000, 0, 0]}], "ME1", "targets[0]")

    def test_delete_after_the_last_use_stays_legal(self):
        """PASS control: the order "used -> deleted" is legal."""
        out = self._compile([_wall(), _move("ME1", "MW", (1000, 0, 0)),
                             self._delete("X1", {"by": "ref", "value": "MW"})])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_deleting_one_wall_does_not_taint_another(self):
        out = self._compile([_wall(), _wall("W2", (0, 5000), (6000, 5000)),
                             self._delete("X1", {"by": "ref", "value": "W2"}),
                             _move("ME1", "MW", (1000, 0, 0))])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])


if __name__ == "__main__":
    unittest.main()
