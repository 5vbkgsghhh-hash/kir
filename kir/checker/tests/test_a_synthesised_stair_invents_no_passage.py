"""A SYNTHESISED STAIR HAS NO RIGHT TO INVENT A PASSAGE (F-320, F-335).

🔴 ONE CLASS, TWO PLACES. `_synthesize_stairs` joins aligned stair
landings. Before 30.08.2026 it did this in TWO wrong ways at once, and both
produce a MADE-UP WAY OUT OF THE BUILDING:

    F-320  neighbours were taken BY LIST ORDER, not by the building. Landings on L0 and L2 with
           no landing on L1 produced `synth_L0_L2` — a stair through an UNSERVED
           floor; two landings on the SAME level produced `synth_L1_L1` with
           `base_z == top_z`, a stair from a level into itself.
    F-335  the link's name carried no core. Two DIFFERENT cores on the same pair of floors
           got ONE id; `nx.Graph.add_node` on an existing node updates its
           attributes, and one node ended up connected to ALL FOUR
           landings — a path from core A to core B that does not exist in the building.

Both mistakes are ONE-DIRECTIONAL: the building looks SAFER than it is, and
HAB010 falls silent. For egress rules this is the worst kind of error — the same argument
that made the height band on `graph.ground_level_ids` unconditional.

🔴 THE FIX CHANGES BEHAVIOUR UNDER BOTH LEVERS, and this is the SECOND NAMED
EXCEPTION to the "v1 bit-for-bit" promise, recorded in `checker/flags.py` in the same
commit. The law of `flags.py` itself demands exactly this: an exception without a record
turns the promise into a silent lie.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import networkx as nx

from kir.checker import engine
from kir.checker.extractor import normalize
from kir.checker.graph import build_graph
from kir.checker.spatial_model import SpatialModel
from kir.checker.thresholds import Thresholds
from kir.checker.rules import connectivity


def _кв(x, y, s=3000):
    return [[x, y], [x + s, y], [x + s, y + s], [x, y + s]]


def _уровни(n):
    return [{"id": f"L{i}", "name": f"L{i}", "elevation_mm": 3000.0 * i,
             "index": i} for i in range(n)]


def _площадка(rid, lvl, x=0):
    return {"id": rid, "name": "Лестница", "level_id": lvl, "area_m2": 9.0,
            "height_mm": 3000.0, "boundary": _кв(x, 0)}


def _сырое(rooms, n=3):
    return {"building_id": "b", "levels": _уровни(n), "rooms": rooms,
            "doors": [], "windows": [], "stairs": [], "walls": []}


def _синтез(rooms, n=3, *, v2="1"):
    with mock.patch.dict(os.environ, {"KIR_CHECKER_V2": v2}):
        return normalize(_сырое(rooms, n))["stairs"]


class СинтезНеВыдумываетПрохода(unittest.TestCase):

    def test_пропущенный_этаж_не_становится_лестницей(self):
        """F-320, case A: landings on L0 and L2, NO landing on L1."""
        for рычаг in ("0", "1"):
            with self.subTest(v2=рычаг):
                s = _синтез([_площадка("s0", "L0"),
                             {"id": "r1", "name": "Спальня", "level_id": "L1",
                              "area_m2": 9.0, "height_mm": 3000.0,
                              "boundary": _кв(0, 0)},
                             _площадка("s2", "L2")], v2=рычаг)
                self.assertEqual(
                    [x["id"] for x in s], [],
                    "связь через НЕОБСЛУЖЕННЫЙ этаж: лестницы на L1 нет, а "
                    "граф считает, что L0 и L2 соединены")

    def test_уровень_не_соединяется_сам_с_собой(self):
        """F-320, case B: two aligned landings on the SAME level."""
        for рычаг in ("0", "1"):
            with self.subTest(v2=рычаг):
                s = _синтез([_площадка("a", "L1"), _площадка("b", "L1")], v2=рычаг)
                self.assertEqual([x["id"] for x in s], [],
                                 "лестница из уровня в себя (base_z == top_z)")

    def test_два_ядра_не_сливаются_в_один_узел(self):
        """F-335: cores A and B on the same pair of floors — TWO nodes, not one."""
        rooms = [_площадка("A1", "L1", 0), _площадка("A2", "L2", 0),
                 _площадка("B1", "L1", 20000), _площадка("B2", "L2", 20000)]
        n = _синтез(rooms)
        self.assertEqual(len(n), 2, "ядра слиты: связь одна вместо двух")
        self.assertEqual(len({x["id"] for x in n}), 2,
                         "два ядра получили ОДИН id — граф сольёт их в узел")
        with mock.patch.dict(os.environ, {"KIR_CHECKER_V2": "1"}):
            готовое = normalize(_сырое(rooms))
        m = SpatialModel.model_validate({**готовое, "stairs": n})
        g = build_graph(m)
        узлы = {u: sorted(v for v in g.neighbors(u))
                for u in g.nodes if str(u).startswith("stair:")}
        self.assertEqual(len(узлы), 2, узлы)
        for соседи in узлы.values():
            self.assertEqual(len(соседи), 2,
                             f"узел соединён с чужим ядром: {узлы}")

    def test_ТРИ_ПОДРЯД_этажа_по_прежнему_связываются(self):
        """🔴 THE SECOND HALF, AND WITHOUT IT THE FIX IS INDISTINGUISHABLE FROM "DO NOT
        SYNTHESISE AT ALL". Packet F-320 says outright that this control is NOT in the tree.

        Three consecutive occupied levels with a landing on each must produce EXACTLY two
        links, and HAB010 must stay silent.
        """
        rooms = [_площадка(f"s{i}", f"L{i}") for i in range(3)]
        for рычаг in ("0", "1"):
            with self.subTest(v2=рычаг):
                s = _синтез(rooms, v2=рычаг)
                self.assertEqual(len(s), 2, [x["id"] for x in s])
                пары = {(x["base_level_id"], x["top_level_id"]) for x in s}
                self.assertEqual(пары, {("L0", "L1"), ("L1", "L2")})

    def test_дубль_id_отвергается_пред_эффектно(self):
        """F-335, second part: a model the graph cannot represent must not
        reach the verdict. Without this refusal the naming could be reverted
        to the old one, and the merge would come back silently."""
        rooms = [_площадка("A1", "L1"), _площадка("A2", "L2")]
        двойник = [
            {"id": "s", "base_level_id": "L1", "top_level_id": "L2",
             "base_z": 3000.0, "top_z": 6000.0, "run_width_mm": None,
             "riser_count": None, "tread_depth_mm": None,
             "footprint": _кв(0, 0), "kind": "inferred"},
            {"id": "s", "base_level_id": "L1", "top_level_id": "L2",
             "base_z": 3000.0, "top_z": 6000.0, "run_width_mm": None,
             "riser_count": None, "tread_depth_mm": None,
             "footprint": _кв(20000, 0), "kind": "inferred"}]
        with mock.patch.dict(os.environ, {"KIR_CHECKER_V2": "1"}):
            готовое = normalize(_сырое(rooms))
        with self.assertRaises(Exception) as ctx:
            SpatialModel.model_validate({**готовое, "stairs": двойник})
        self.assertIn("уже занят", str(ctx.exception))

    def test_эталон_не_сдвинулся(self):
        """A MEASUREMENT, NOT AN ARGUMENT: of 17 fixtures, synthesis participates in ONE, and there
        both links are PRESERVED — only their names change."""
        from kir.checker.fixtures import builders
        for рычаг in ("0", "1"):
            with self.subTest(v2=рычаг):
                with mock.patch.dict(os.environ, {"KIR_CHECKER_V2": рычаг}):
                    d = normalize(builders.bad_floors_hidden_by_balcony_doors())
                синт = [s["id"] for s in d["stairs"]
                        if str(s["id"]).startswith("synth_")]
                self.assertEqual(len(синт), 2, синт)
                self.assertTrue(all("_" in i.removeprefix("synth_") for i in синт))


if __name__ == "__main__":
    unittest.main()
