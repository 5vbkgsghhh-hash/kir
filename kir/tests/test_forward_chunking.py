"""FORWARD-PASS CHUNKING: the slice preserves the intent, and the weakening
is named.

MEASUREMENTS THIS FILE EXISTS FOR (20.08.2026, Revit 2026):

    20 000 ops   monolith: 20.8 s, 68 MB of C#, peak RSS 830 MB
                 chunked:    17 s, 9 chunks of <=8.2 MB, peak RSS 206 MB
   100 000 ops   monolith:  101  s, 343 MB of C#, peak RSS 3723 MB
                 chunked:    94 s, 42 chunks of <=8.3 MB, peak RSS 250 MB

So chunking fixes not only the transport (the bridge frame's 16 MB) but
also the service's MEMORY: fifteenfold, because a chunk is compiled and
released, while the monolith holds all the C# at once.

The cost estimate misses by 2.5% ON THE SAFE SIDE (an estimate of 8.0 MB
against an actual 8.2), and a margin for this is built into the frame's 0.5
fraction.
"""
from __future__ import annotations

import unittest

from kir import chunking as K

_LEVEL = {"by": "element_id", "value": 355}


def _wall(i: int, **extra) -> dict:
    r, c = divmod(i, 300)
    x, y = c * 300.0, r * 400.0
    op = {"op": "create_wall", "id": f"W{i}", "p0_mm": [x, y],
          "p1_mm": [x + 250.0, y], "level": _LEVEL, "height_mm": 3000.0}
    op.update(extra)
    return op


class TheSliceKeepsTheIntent(unittest.TestCase):

    def test_order_is_preserved_exactly(self) -> None:
        """THE MAIN LAW. A HUMAN wrote the order, and it is part of the
        intent.

        Topological sorting is legitimate for the inverse pass, where the
        order was produced by decompilation. Here, reordering would mean
        building a different program than the one that was sent — and
        building it SILENTLY.
        """
        ops = [_wall(i) for i in range(5000)]
        plan = K.plan_chunks(ops)
        flat = [o for ch in plan.chunks for o in ch.ops]
        self.assertEqual([o["id"] for o in flat], [o["id"] for o in ops])

    def test_no_op_is_lost_or_duplicated(self) -> None:
        ops = [_wall(i) for i in range(5000)]
        plan = K.plan_chunks(ops)
        flat = [o for ch in plan.chunks for o in ch.ops]
        self.assertEqual(len(flat), len(ops))
        self.assertEqual(len({o["id"] for o in flat}), len(ops))

    def test_every_chunk_fits_the_budget(self) -> None:
        plan = K.plan_chunks([_wall(i) for i in range(5000)])
        for ch in plan.chunks:
            self.assertLessEqual(ch.est_bytes, plan.budget_bytes,
                                 f"чанк {ch.index} превысил бюджет")

    def test_a_program_that_fits_stays_ONE_chunk(self) -> None:
        """A NARROWNESS CONTROL, and it matters more than the rest.

        An ordinary program must run as it always did — as one transaction,
        byte for byte. Chunking that always kicks in would weaken
        atomicity for everyone for the sake of the few it was getting in
        the way of.
        """
        plan = K.plan_chunks([_wall(i) for i in range(10)])
        self.assertEqual(len(plan.chunks), 1)
        self.assertFalse(plan.split)
        self.assertEqual(plan.atomicity, "whole_program")


class TheWeakeningIsNamed(unittest.TestCase):

    def test_a_split_program_says_atomicity_is_per_chunk(self) -> None:
        plan = K.plan_chunks([_wall(i) for i in range(5000)])
        self.assertTrue(plan.split)
        self.assertEqual(plan.atomicity, "per_chunk")

    def test_the_note_says_what_survives_a_failure(self) -> None:
        """A name with no consequence is decoration.

        The author must learn not the word "per_chunk", but the fact: the
        chunks before the one that failed are ALREADY IN THE MODEL.
        """
        note = K.plan_chunks([_wall(i) for i in range(5000)]).atomicity_note_ru
        self.assertIn("УЖЕ В МОДЕЛИ", note)

    def test_each_chunk_says_why_it_ended(self) -> None:
        plan = K.plan_chunks([_wall(i) for i in range(5000)])
        for ch in plan.chunks:
            self.assertTrue(ch.reason.strip(), f"чанк {ch.index} молчит о причине")


class RefsSurviveTheBoundary(unittest.TestCase):

    def test_a_backward_ref_is_declared_as_a_need(self) -> None:
        ops = [{"op": "create_level", "id": "L1", "elev_mm": 0, "name": "К1"}]
        ops += [_wall(i, level={"by": "ref", "value": "L1"}) for i in range(5000)]
        plan = K.plan_chunks(ops)
        self.assertGreater(len(plan.chunks), 1)
        self.assertEqual(plan.chunks[0].needs, ())
        for ch in plan.chunks[1:]:
            self.assertIn("L1", ch.needs,
                          f"чанк {ch.index} молчит о ссылке за свою границу")

    def test_an_intra_chunk_ref_is_NOT_a_need(self) -> None:
        """A NARROWNESS CONTROL: a `needs` that declares EVERYTHING is
        useless."""
        ops = [{"op": "create_level", "id": "L1", "elev_mm": 0, "name": "К1"},
               _wall(0, level={"by": "ref", "value": "L1"})]
        plan = K.plan_chunks(ops)
        self.assertEqual(len(plan.chunks), 1)
        self.assertEqual(plan.chunks[0].needs, ())

    def test_bind_refs_rewrites_only_what_crosses(self) -> None:
        ops = [{"op": "create_level", "id": "L1", "elev_mm": 0, "name": "К1"}]
        ops += [_wall(i, level={"by": "ref", "value": "L1"}) for i in range(5000)]
        plan = K.plan_chunks(ops)
        bound = K.bind_refs(plan.chunks[1], {"L1": ["12345"]})
        self.assertEqual(bound[0]["level"], {"by": "element_id", "value": 12345})
        # and an intra-chunk reference remains a reference
        first = K.bind_refs(plan.chunks[0], {})
        inner = [o for o in first if o["op"] == "create_wall"][0]
        self.assertEqual(inner["level"], {"by": "ref", "value": "L1"})

    def test_a_ref_to_a_MANY_element_op_is_refused(self) -> None:
        """Choosing on the author's behalf is not allowed — that is a
        silent `.FirstOrDefault()`."""
        ops = [{"op": "create_level", "id": "L1", "elev_mm": 0, "name": "К1"}]
        ops += [_wall(i, level={"by": "ref", "value": "L1"}) for i in range(5000)]
        plan = K.plan_chunks(ops)
        with self.assertRaises(ValueError):
            K.bind_refs(plan.chunks[1], {"L1": ["1", "2", "3"]})

    def test_a_missing_receipt_is_refused_by_name(self) -> None:
        ops = [{"op": "create_level", "id": "L1", "elev_mm": 0, "name": "К1"}]
        ops += [_wall(i, level={"by": "ref", "value": "L1"}) for i in range(5000)]
        plan = K.plan_chunks(ops)
        with self.assertRaises(KeyError):
            K.bind_refs(plan.chunks[1], {})


class TheHardCases(unittest.TestCase):

    def test_a_solo_op_gets_its_own_chunk(self) -> None:
        """KIR-L002: StairsEditScope owns its own transactions."""
        ops = [_wall(0), {"op": "create_stairs", "id": "S1",
                          "level": _LEVEL, "top_level": _LEVEL}, _wall(1)]
        plan = K.plan_chunks(ops)
        self.assertEqual(len(plan.chunks), 3)
        self.assertEqual([o["id"] for o in plan.chunks[1].ops], ["S1"])

    def test_an_op_bigger_than_the_budget_is_named_not_silently_oversized(self) -> None:
        big = {"op": "create_surface", "id": "S"}
        with self.assertRaises(K.ChunkTooBig) as caught:
            K.plan_chunks([big], frame_bytes=1000, payload_share=0.5)
        self.assertIn(K.CHUNK_OP_TOO_BIG, str(caught.exception))

    def test_an_unknown_op_costs_the_MOST_expensive_known(self) -> None:
        """The unmeasured is treated as expensive — a miss then costs one
        extra chunk, not a dropped connection."""
        self.assertEqual(K.cost_of({"op": "нет такого"}), K.UNKNOWN_OP_BYTES)
        self.assertEqual(K.UNKNOWN_OP_BYTES, max(K.MEASURED_BYTES_PER_OP.values()))

    def test_the_solo_list_is_the_registry_one(self) -> None:
        """Two tables that are required to match diverge silently."""
        from kir import spec
        self.assertEqual(set(K.SOLO_OPS), set(spec.SOLO_OPS))


if __name__ == "__main__":
    unittest.main()
