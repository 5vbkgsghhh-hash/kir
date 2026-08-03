"""A hosted op whose host stayed an atom is a SKIP, not a crash.

``leaves_to_program`` promises in its own docstring that "every op-leaf either
materializes or is a typed skip — never silently dropped (I2)", and a comment
above the host map says a hosted ref "can be validated before chunking".  No
such validation existed: a ``{"ref": …}`` pointing at a leaf that never became
an op raised ``MaterializeError`` out of the middle of chunk assembly, killing
the whole run.

It stayed hidden because a hosted element usually failed for the same reason
its host did.  It surfaced on SOB6.2_UPO_L_DOO_AR_R23 the moment doors with a
negative sill started lifting: 5 of that building's walls are atoms (no curve
in frozen L0), and their doors are now perfectly good ops pointing at nothing.

One unbuildable wall must cost its own doors, not the other 1 069 elements.
"""
import unittest

from kukai.ir.decompile.l1_schema import stable_l1_id
from kukai.ir.decompile.materialize import leaves_to_program


def _wall(source_id):
    return {
        "kind": "op", "op_name": "create_wall",
        "_id": stable_l1_id("op", source_id), "type_name": "W200",
        "params": {"p0_mm": [0.0, 0.0], "p1_mm": [6000.0, 0.0],
                   "level": {"by": "element_id", "_id": "10"},
                   "height_mm": 3000.0},
        "source_element_id": source_id, "level_name": "L1",
        "anchor_mm": [0.0, 0.0, 0.0],
    }


def _atom_wall(source_id):
    return {
        "kind": "atom", "_id": stable_l1_id("atom", source_id),
        "category": "OST_Walls", "category_ru": "Стены", "type_name": "W200",
        "bbox_min_mm": [0.0, 0.0, 0.0], "bbox_max_mm": [100.0, 100.0, 3000.0],
        "source_element_id": source_id, "level_name": "L1",
        "anchor_mm": [50.0, 50.0, 0.0],
        "reason": {"code": "missing_geometry",
                   "detail": "OST_Walls requires curve geometry"},
    }


def _door(source_id, host_source_id, *, sill=-100.0):
    return {
        "kind": "op", "op_name": "create_door",
        "_id": stable_l1_id("op", source_id), "type_name": "D1",
        "params": {"host": {"ref": stable_l1_id("op", host_source_id)},
                   "offset_mm": 3000.0, "sill_mm": sill},
        "source_element_id": source_id, "level_name": "L1",
        "anchor_mm": [3000.0, 0.0, -100.0],
    }


class OrphanHostIsSkipped(unittest.TestCase):
    def test_door_on_an_atom_wall_is_skipped_not_raised(self):
        leaves = [_atom_wall("100"), _door("200", "100")]
        result = leaves_to_program(leaves, chunk_target=250)
        skipped = {r.source_id: r.reason for r in result.skipped}
        self.assertIn("200", skipped)
        self.assertIn("host", skipped["200"])
        self.assertEqual(result.programs, [])

    def test_the_rest_of_the_building_still_materializes(self):
        # The whole point: one orphan must not cost the healthy elements.
        leaves = [_wall("100"), _door("200", "100"),
                  _atom_wall("300"), _door("400", "300")]
        result = leaves_to_program(leaves, chunk_target=250)
        ops = [op for program in result.programs for op in program["ops"]]
        names = sorted(op["op"] for op in ops)
        self.assertEqual(names, ["create_door", "create_wall"])
        skipped = {r.source_id for r in result.skipped}
        self.assertIn("400", skipped)
        self.assertNotIn("200", skipped)

    def test_a_chain_of_orphans_resolves_to_a_fixed_point(self):
        # If a hosted op is dropped, anything hosted on IT is orphaned too;
        # one pass would leave a dangling ref behind and crash as before.
        leaves = [_atom_wall("100"), _door("200", "100"), _door("300", "200")]
        result = leaves_to_program(leaves, chunk_target=250)
        skipped = {r.source_id for r in result.skipped}
        self.assertEqual(skipped, {"100", "200", "300"})
        self.assertEqual(result.programs, [])


if __name__ == "__main__":
    unittest.main()
