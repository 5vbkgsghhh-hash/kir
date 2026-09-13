"""THE `op_id → element_id` BRIDGE: a map, a refusal instead of silence, and a translation.

What is guarded here, by importance:

1. **An empty intersection is a NAMED finding, not an empty list.** Before
   15.08, `compare_geometry` on the authored program returned `[]`, because
   every one of its branches stands under `if common:`. An empty list of
   discrepancies reads as "everything matched" — a zero for a quantity
   nobody counted.
2. **The keys of what was created are DERIVED from the registry.** A
   hand-written tuple was missing four creating ops (`segment_ids`) and
   carried two names that belong to no op at all.
3. **The "creating/never-creating" pair is a PARTITION** of the registry's
   fields: with no remainder and no overlap. The "no overlap" condition
   caught an error of the author's: `change_type` is `MUTATE` and carries
   the same `id` as one of the 59 creating ops.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir import created_ledger, design_check, spec           # noqa: E402
from kir.address import (                                    # noqa: E402
    Address, AddressSpace, AddressSpaceError, IdentityMissingError,
    assert_one_space, created_identity_fields, element_addresses,
    identity_field_reasons, receipt_map)


def _walls(prefix: str) -> list[dict]:
    """A closed 5×4 m box on its own level, id following the `prefix` pattern.

    The level is created RIGHT HERE and addressed `by=ref`: without it the
    collector does not pick up the wall at all — verified, and this is
    exactly where the "the control is degenerate" line fired. The level
    carries the same prefix, because the translation MUST cover it too: the
    address is a property of ALL of the program's nodes, not only the
    interesting ones.
    """

    box = [((0, 0), (5000, 0)), ((5000, 0), (5000, 4000)),
           ((5000, 4000), (0, 4000)), ((0, 4000), (0, 0))]
    level_id = f"{prefix}0"
    ops: list[dict] = [{"op": "create_level", "id": level_id,
                        "elev_mm": 0.0, "name": "L1"}]
    ops += [{"op": "create_wall", "id": f"{prefix}{i}",
             "p0_mm": list(p0), "p1_mm": list(p1),
             "level": {"by": "ref", "value": level_id}, "height_mm": 3000.0}
            for i, (p0, p1) in enumerate(box, start=1)]
    return ops


def _model(ops: list[dict]):
    nodes = design_check._ops_to_nodes(ops)
    model, _witness = design_check.spatial_model_from_program(
        nodes, building_id="контроль")
    return model


class TheMapIsDerivedFromTheRegistry(unittest.TestCase):

    def test_all_four_identity_forms_reach_the_map(self) -> None:
        """The map MUST cover ALL forms, not only the `id` of the 59 ops."""

        ops = [{"op": "create_wall", "id": "w1"},
               {"op": "move_elements", "id": "m1"},
               {"op": "delete", "id": "d1"},
               {"op": "route_pipe_system", "id": "r1"},
               {"op": "query_count", "id": "q1"}]
        payload = {"w1": {"id": 9001}, "m1": {"moved_ids": [11, 12]},
                   "d1": {"deleted_id": 77}, "r1": {"segment_ids": [21, 22]},
                   "q1": {"n": 5}}
        got = element_addresses(ops, payload)
        self.assertEqual(sorted(got), ["d1", "m1", "r1", "w1"])
        self.assertNotIn("q1", got, "у запроса идентичности нет по контракту")
        self.assertEqual([a.value for a in got["r1"]], ["21", "22"])
        self.assertTrue(all(a.space is AddressSpace.ELEMENT_ID
                            for addrs in got.values() for a in addrs))

    def test_a_writing_op_without_identity_refuses(self) -> None:
        """FAIL CONTROL: a silent omission would give an incomplete map that looks complete."""

        ops = [{"op": "create_wall", "id": "w1"},
               {"op": "create_wall", "id": "w2"}]
        payload = {"w1": {"id": 9001}}                 # w2 without identity
        with self.assertRaises(IdentityMissingError) as caught:
            element_addresses(ops, payload)
        self.assertIn("w2", str(caught.exception))
        # and the soft mode MUST exist, but must not be the default
        self.assertEqual(sorted(element_addresses(ops, payload, strict=False)),
                         ["w1"])

    def test_the_map_is_a_list_on_every_arity(self) -> None:
        """ONE FORM FOR ALL ARITIES — a list even when there is a single element.

        🔴 THIS TEST REPLACED `test_the_flat_translation_drops_plural_
        ops_on_purpose`, AND REPLACED IT TOGETHER WITH ITS ASSERTION. That
        one pinned down, as INTENDED behavior, the fact that the flat map
        drops operations of plural arity: `op_to_element_ids(...) ==
        {"w1": "9001"}` — and `r1` with two segments simply vanished.
        Measured on 15.08 against the registry: FIVE writing ops out of 66
        were being lost this way. The function was removed, and the
        assertion about its "intentionality" was removed along with it,
        not commented out: a commented-out assertion reads, a month later,
        as temporarily lifted, whereas this was a decision.
        """

        ops = [{"op": "create_wall", "id": "w1"},
               {"op": "route_pipe_system", "id": "r1"}]
        payload = {"w1": {"id": 9001}, "r1": {"segment_ids": [21, 22]}}
        got = receipt_map(ops, payload)
        self.assertEqual(got, {"w1": ["9001"], "r1": ["21", "22"]},
                         "множественная арность обязана ДОЕХАТЬ, а не выпасть")

    def test_a_flat_translation_now_refuses_instead_of_dropping(self) -> None:
        """FAIL CONTROL FOR RECONCILIATION: swapping the form changes the
        answer exactly where it should.

        The flat map is still needed at the boundary — `design_check.
        compare_geometry` takes `translate: Mapping[str, str]`, because it
        compares walls, openings, and rooms, all of arity ONE. The
        difference from the removed function is in the OUTCOME: explicit
        unpacking `(only,)` REFUSES on plural arity, where the old one
        silently lost data.
        """

        ops = [{"op": "create_wall", "id": "w1"},
               {"op": "route_pipe_system", "id": "r1"}]
        payload = {"w1": {"id": 9001}, "r1": {"segment_ids": [21, 22]}}

        # THE HONEST PATH: where the arity is one, the unpacking goes through.
        only_walls = {"w1": payload["w1"]}
        flat = {oid: only for oid, (only,) in
                receipt_map(ops[:1], only_walls).items()}
        self.assertEqual(flat, {"w1": "9001"})

        # But on plural arity — REFUSAL, not a silent loss.
        with self.assertRaises(ValueError):
            {oid: only for oid, (only,) in receipt_map(ops, payload).items()}

    def test_there_is_exactly_one_producer_of_the_map(self) -> None:
        """AS LONG AS THERE ARE TWO ANSWERS, NOBODY KNOWS THE NUMBER OF
        DISCREPANCIES BETWEEN THEM.

        Two functions doing one job drift apart silently — this is exactly
        how, in this tree, `KIND_TABLE` already diverged from
        `REGISTRY_GAPS` (three times) and `acceptance._OP_CATEGORIES` from
        `clash_bundle.OP_CATEGORY` (three discrepancies instead of the one
        assumed). Here this is pinned down structurally: `receipt_map` MUST
        be built ON TOP OF `element_addresses`, rather than reading the
        registry in a second pass."""

        import inspect

        from kir import address as _mod

        source = inspect.getsource(_mod.receipt_map)
        self.assertIn("element_addresses(", source,
                      "второй проход по реестру = второй производитель карты")
        self.assertFalse(hasattr(_mod, "op_to_element_ids"),
                         "плоская форма вернулась — их снова две")
        self.assertNotIn("op_to_element_ids", _mod.__all__)


class TheCreatedKeysAreTheRegistrys(unittest.TestCase):

    def test_the_four_network_ops_are_no_longer_lost(self) -> None:
        """Measured 15.08: `segment_ids` carries FOUR creating ops."""

        keys = created_identity_fields()
        self.assertIn("segment_ids", keys)
        network = [n for n, o in spec.OPS.items()
                   if o.result.identity_field == "segment_ids"]
        self.assertEqual(len(network), 4, sorted(network))
        got = created_ledger.extract_created({"r1": {"segment_ids": [21, 22]}})
        self.assertEqual(got, {"r1": ["21", "22"]})

    def test_the_hand_written_names_are_gone(self) -> None:
        """`ids` and `created_ids` are declared by NOT A SINGLE op — guessed names."""

        self.assertNotIn("ids", created_identity_fields())
        self.assertNotIn("created_ids", created_identity_fields())

    def test_created_and_never_created_partition_the_registry(self) -> None:
        """PARTITION: no remainder AND no overlap. The second caught an author's error."""

        created = set(created_identity_fields())
        never = set(identity_field_reasons())
        every = {o.result.identity_field for o in spec.OPS.values()
                 if o.result.identity_field}
        self.assertEqual(created | never, every, "остаток есть — реестр не покрыт")
        self.assertFalse(created & never, "пересечение есть — это не разбиение")
        for field, reason in identity_field_reasons().items():
            self.assertTrue(reason.strip(), f"{field} исключён без причины")

    def test_the_ratchet_can_actually_fail(self) -> None:
        """A check that cannot turn red is guarding zero.

        The predecessor file's earlier test checked `"id" in ("id",…)` — a
        constant. Here the subject itself is broken: a field dropped from
        the registry MUST also disappear from the keys.
        """

        keys_before = created_identity_fields()
        self.assertIn("segment_ids", keys_before)
        victim = next(o for o in spec.OPS.values()
                      if o.result.identity_field == "segment_ids")
        import dataclasses
        from kir.registry_base import IdentityCardinality, ResultSpec
        patched = dict(spec.OPS)
        for name, op in list(patched.items()):
            if op.result.identity_field == "segment_ids":
                patched[name] = dataclasses.replace(
                    op, result=ResultSpec(IdentityCardinality.ONE, "id"))
        original = spec.OPS
        try:
            spec.OPS = patched                       # type: ignore[misc]
            created_identity_fields.cache_clear()
            self.assertNotIn("segment_ids", created_identity_fields(),
                             "ключи не следуют за реестром — вывод фиктивен")
        finally:
            spec.OPS = original                      # type: ignore[misc]
            created_identity_fields.cache_clear()
        self.assertIn("segment_ids", created_identity_fields())
        self.assertIsNotNone(victim)


class TheAddressRefusesToCrossSpaces(unittest.TestCase):

    def test_comparing_two_spaces_refuses_instead_of_returning_false(self) -> None:
        op = Address(AddressSpace.OP_ID, "w1")
        el = Address(AddressSpace.ELEMENT_ID, "9001")
        with self.assertRaises(AddressSpaceError):
            op.same_as(el)
        self.assertTrue(op.same_as(Address(AddressSpace.OP_ID, "w1")))
        self.assertFalse(op.same_as(Address(AddressSpace.OP_ID, "w2")))

    def test_containers_still_work(self) -> None:
        """`__eq__` is deliberately structural: otherwise `set`/`dict` would break on collisions."""

        pool = {Address(AddressSpace.OP_ID, "w1"),
                Address(AddressSpace.ELEMENT_ID, "w1")}
        self.assertEqual(len(pool), 2)

    def test_an_empty_set_has_no_space(self) -> None:
        with self.assertRaises(AddressSpaceError):
            assert_one_space([])
        with self.assertRaises(AddressSpaceError):
            assert_one_space([Address(AddressSpace.OP_ID, "w1"),
                              Address(AddressSpace.ELEMENT_ID, "9001")])
        self.assertIs(assert_one_space([Address(AddressSpace.OP_ID, "w1")]),
                      AddressSpace.OP_ID)


class TheComparatorSpeaksInsteadOfBeingSilent(unittest.TestCase):

    def test_without_a_translation_the_empty_intersection_is_NAMED(self) -> None:
        """The wave's main finding: there used to be an empty list here."""

        program = _model(_walls("w"))
        parse = _model(_walls("900"))
        self.assertTrue(program.walls and parse.walls, "контроль вырожден")
        out = design_check.compare_geometry(parse, program)
        self.assertEqual(len(out), 1, [d.subject for d in out])
        self.assertEqual(out[0].kind, "адрес")
        self.assertIn("ПУСТО", out[0].cause)

    def test_with_the_translation_the_comparison_actually_happens(self) -> None:
        program = _model(_walls("w"))
        parse = _model(_walls("900"))
        translate = {f"w{i}": f"900{i}" for i in range(0, 5)}
        out = design_check.compare_geometry(parse, program, translate=translate)
        self.assertFalse([d for d in out if d.kind == "адрес"],
                         "перевод дан, а пространства всё ещё не сведены")
        self.assertTrue(any(d.subject == "ось стены" for d in out) or not out,
                        "сравнение не дошло до осей стен")

    def test_moving_one_wall_changes_the_answer(self) -> None:
        """FAIL CONTROL FOR THE COMPARATOR: green without an act of
        discrimination does not count.

        Matching geometry MUST NOT produce a discrepancy along the axes; a
        geometry shifted by 250 mm MUST. If both runs answer the same way,
        the comparator is green by construction and measures nothing.
        """

        translate = {f"w{i}": f"900{i}" for i in range(0, 5)}
        parse = _model(_walls("900"))

        same = design_check.compare_geometry(
            parse, _model(_walls("w")), translate=translate)
        axis_same = [d for d in same if d.subject == "ось стены"]

        moved_ops = _walls("w")
        moved_ops[1]["p1_mm"] = [5250, 0]          # one wall is 250 mm longer
        moved = design_check.compare_geometry(
            parse, _model(moved_ops), translate=translate)
        axis_moved = [d for d in moved if d.subject == "ось стены"]

        self.assertFalse(axis_same, "совпадающая геометрия дала расхождение")
        self.assertTrue(axis_moved, "сдвиг на 250 мм НЕ изменил ответ — "
                                    "компаратор не меряет геометрию")
        self.assertIn("250", axis_moved[0].program)


if __name__ == "__main__":
    unittest.main()
