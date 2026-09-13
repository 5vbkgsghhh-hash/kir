"""SINGLETONS SHIP BY KIND — otherwise one refusal costs two hundred
fifty.

MEASURED 23.08.2026, building K3 into a foreign document. There is ONE
TRANSACTION PER PROGRAM: the failure of one op rolls back the entire
chunk. While singletons were packed together indiscriminately, 917 room
separators (all failing for one named reason — the created level has no
floor plan) held **11,207 of 13,100 operations, i.e. 85.5%**, hostage.

Shrinking the chunk does not fix it: at target=50 the share drops only to
53.5%, while the number of groundings grows fivefold — and a grounding's
cost is exactly the second wall of migration (3…250 s per program).

After splitting by kind: **917 of 13,100 = 7.0%** — exactly the
separators themselves, with not a single neighbor. The cost is 55
programs instead of 62.

🔴 THESE TESTS GUARD A LAW, NOT A NUMBER. They do not check 7.0% and know
nothing about the separators: they require that TWO DIFFERENT KINDS OF
SINGLETONS never land in the same chunk, and that the catalog goes first.
The numbers live in `_pack_groups`'s docstring next to the argument; what
is here is the behavior that delivers them.
"""
from __future__ import annotations

import unittest

from kir.decompile.materialize import _HostGroup, _pack_groups


def _leaf(node_id: str, op_name: str) -> dict:
    return {"_id": node_id, "source_element_id": node_id,
            "kind": "op", "op_name": op_name, "params": {}}


def _single(node_id: str, op_name: str) -> _HostGroup:
    return _HostGroup(anchor_source_id=node_id,
                      leaves=(_leaf(node_id, op_name),))


def _multi(anchor: str, kinds: tuple[str, ...]) -> _HostGroup:
    leaves = tuple(_leaf(f"{anchor}_{i}", kind)
                   for i, kind in enumerate(kinds))
    return _HostGroup(anchor_source_id=anchor, leaves=leaves)


def _kinds_of(chunk) -> set:
    return {node["op_name"] for node in chunk}


class SinglesTravelByKind(unittest.TestCase):
    def test_two_singleton_kinds_never_share_a_chunk(self):
        """The main law: a kind's failure costs only that kind."""
        groups = []
        for i in range(40):
            groups.append(_single(f"w{i:03d}", "create_wall"))
            groups.append(_single(f"s{i:03d}", "create_room_separator"))
        chunks = _pack_groups(groups, chunk_target=25)
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertEqual(
                len(_kinds_of(chunk)), 1,
                f"в куске смешались роды: {sorted(_kinds_of(chunk))}")

    def test_risky_kind_takes_no_hostages(self):
        """The blast radius equals the kind itself, and not one operation
        more."""
        groups = [_single(f"w{i:03d}", "create_wall") for i in range(100)]
        groups.append(_single("s000", "create_room_separator"))
        chunks = _pack_groups(groups, chunk_target=250)
        hostage = sum(len(c) for c in chunks
                      if "create_room_separator" in _kinds_of(c))
        self.assertEqual(hostage, 1)

    def test_multi_op_group_is_never_split(self):
        """D5a intact: a composite group is indivisible, and mixing kinds
        inside it is legitimate."""
        wall = _multi("h000", ("create_wall", "create_door", "create_tag"))
        groups = [wall] + [_single(f"w{i:03d}", "create_wall")
                           for i in range(10)]
        chunks = _pack_groups(groups, chunk_target=2)
        holding = [c for c in chunks if any(n["_id"].startswith("h000")
                                            for n in c)]
        self.assertEqual(len(holding), 1, "составная группа разъехалась")
        self.assertEqual(len(holding[0]), 3)


class CatalogGoesFirst(unittest.TestCase):
    def test_catalog_kinds_precede_the_rest(self):
        """Levels and grids must be committed before their consumers.

        A `by=ref` reference does not survive across a program boundary —
        only the name does, so the level must ALREADY exist. Live
        measurement from 23.08: the first three programs got "levels not
        found" while the catalog rode mixed in with the rest.

        🔴 A COMPOSITE GROUP IS MANDATORY HERE. The test's first revision
        used only singletons — and the mutation "catalog not first" sailed
        straight THROUGH, because the stream of composites was empty and
        there was nothing to reorder. The test was green by construction —
        exactly the shape this whole package was written against. A
        level's consumer most often sits precisely INSIDE a composite
        group (a wall with doors and tags), which is why one is in the
        fixture.
        """
        groups = [_multi("h000", ("create_wall", "create_door"))]
        groups += [_single(f"w{i:03d}", "create_wall") for i in range(5)]
        groups += [_single(f"l{i:03d}", "create_level") for i in range(3)]
        groups += [_single(f"g{i:03d}", "create_grid") for i in range(2)]
        chunks = _pack_groups(groups, chunk_target=2)
        order = [sorted(_kinds_of(c))[0] for c in chunks]
        first_consumer = min(
            i for i, c in enumerate(chunks)
            if _kinds_of(c) & {"create_wall", "create_door"})
        for catalog in ("create_grid", "create_level"):
            self.assertLess(
                order.index(catalog), first_consumer,
                f"{catalog} едет ПОСЛЕ потребителя")


class PackingIsDeterministic(unittest.TestCase):
    def test_same_input_same_chunks(self):
        groups = [_single(f"w{i:03d}", "create_wall") for i in range(7)]
        groups += [_single(f"s{i:03d}", "create_room_separator")
                   for i in range(5)]
        first = [[n["_id"] for n in c]
                 for c in _pack_groups(groups, chunk_target=3)]
        second = [[n["_id"] for n in c]
                  for c in _pack_groups(groups, chunk_target=3)]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
