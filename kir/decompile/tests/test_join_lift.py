"""JOINS ARE LIFTED INTO THE PROGRAM — `lift.lift_joins`.

MOTIVATION. The capture has been reading all three kinds of joins live since
18.08.2026, disk holds five `join.index.json` files, the `join_elements` op
exists in the registry — while `lift.py` had ZERO lines about joins. The
building was arriving back in pieces not because the connection was lost,
but because nobody was lifting it.

THREE THINGS THIS FILE GUARDS, AND ALL THREE ARE ABOUT DISTINCTION:

1. **the three kinds do not merge.** `joined_to` is symmetric and gets
   lifted; `join_allowed_at_end` and `elements_at_end_join` are about the END
   of a specific wall, there is no op for them, and `join_elements` cannot
   stand in for them: the live measurement of 18.08 found a pair of walls
   where an end join EXISTS, yet `AreElementsJoined` is False.
2. **"was not read" ≠ "free end".** The `EndState` census reaches the
   consumer IN FULL, zero-valued keys included.
3. **a refusal names the REASON OF THE ARM verbatim.** Otherwise the next
   person will go fix joins where what needs fixing is the wall lift: on
   MNVNK, 8 061 of 8 090 pairs ran into `OST_Walls / missing_geometry`.

Run:
    venv/bin/python -m pytest kir/decompile/tests/test_join_lift.py -q
"""
from __future__ import annotations

import unittest

from kir.decompile.join_extract import (
    EndJoin,
    JoinExtraction,
    JoinFailure,
    JoinPayloadError,
    JoinRecord,
)
from kir.decompile.l1_schema import stable_l1_id
from kir.decompile.lift import (
    JOIN_RELATIONS_WITHOUT_AN_OP,
    JoinLiftReason,
    lift_joins,
)


def _op_node(source_id: str, op_name: str = "create_wall") -> dict:
    return {
        "kind": "op",
        "op_name": op_name,
        "_id": stable_l1_id("op", source_id),
        "type_name": "Стена",
        "params": {},
        "source_element_id": source_id,
        "level_name": "Уровень 1",
        "anchor_mm": None,
    }


def _atom_node(source_id: str, code: str = "missing_geometry") -> dict:
    return {
        "kind": "atom",
        "_id": stable_l1_id("atom", source_id),
        "category": "OST_Walls",
        "category_ru": "Стены",
        "type_name": "Стена",
        "bbox_min_mm": None,
        "bbox_max_mm": None,
        "source_element_id": source_id,
        "level_name": "Уровень 1",
        "anchor_mm": None,
        "reason": {"code": code, "detail": "L0 не несёт кривой"},
    }


class ThePairIsLiftedOnce(unittest.TestCase):

    def test_a_symmetric_pair_becomes_exactly_one_op(self):
        """Revit declares the relation from BOTH sides; there must be ONE
        op."""
        index = JoinExtraction(joins=(
            JoinRecord("100", joined_to=("200",)),
            JoinRecord("200", joined_to=("100",)),
        ))
        out = lift_joins(index, [_op_node("100"), _op_node("200")])
        self.assertEqual(len(out.ops), 1, "симметричная пара удвоилась")
        self.assertEqual(out.pairs_read, 1)
        self.assertEqual(out.refusals, ())

    def test_the_op_references_nodes_not_element_ids(self):
        """The reference is in the L1 dialect, the same one used by nodes'
        params.

        A dialect of its own here would start a SECOND carrier of the
        selector schema, and `materialize._translate_reference` translates
        them.
        """
        index = JoinExtraction(joins=(JoinRecord("100", joined_to=("200",)),))
        out = lift_joins(index, [_op_node("100"), _op_node("200")])
        op = out.ops[0]
        self.assertEqual(op["op_name"], "join_elements")
        self.assertEqual(op["params"]["first"], {"ref": stable_l1_id("op", "100")})
        self.assertEqual(op["params"]["second"], {"ref": stable_l1_id("op", "200")})
        self.assertEqual(op["sources"], ("100", "200"))

    def test_the_op_carries_no_invented_id(self):
        """Op identity is handed out by the materializer, and there is no
        second carrier."""
        index = JoinExtraction(joins=(JoinRecord("100", joined_to=("200",)),))
        out = lift_joins(index, [_op_node("100"), _op_node("200")])
        self.assertNotIn("id", out.ops[0])
        self.assertNotIn("_id", out.ops[0])

    def test_the_order_is_deterministic(self):
        """Revit's response order is not declared; the decompile must be
        reproducible."""
        index = JoinExtraction(joins=(
            JoinRecord("300", joined_to=("100", "200")),
            JoinRecord("100", joined_to=("300",)),
            JoinRecord("200", joined_to=("300",)),
        ))
        nodes = [_op_node(x) for x in ("100", "200", "300")]
        first = lift_joins(index, nodes).ops
        second = lift_joins(index, list(reversed(nodes))).ops
        self.assertEqual([o["sources"] for o in first],
                         [o["sources"] for o in second])
        self.assertEqual([o["sources"] for o in first],
                         [("100", "300"), ("200", "300")])


class ARefusalNamesItsCause(unittest.TestCase):

    def test_an_arm_that_stayed_an_atom_refuses_and_quotes_the_atom(self):
        """MNVNK: 8 061 of 8 090 pairs are a wall without geometry, not a
        join."""
        index = JoinExtraction(joins=(JoinRecord("100", joined_to=("200",)),))
        out = lift_joins(index, [_op_node("100"), _atom_node("200")])
        self.assertEqual(out.ops, ())
        self.assertEqual(len(out.refusals), 1)
        refusal = out.refusals[0]
        self.assertIs(refusal.reason, JoinLiftReason.TARGET_STAYED_ATOM)
        self.assertIn("missing_geometry", refusal.detail,
                      "без причины САМОГО атома следующий пойдёт чинить "
                      "соединение вместо подъёма стены")
        self.assertIn("OST_Walls", refusal.detail)

    def test_an_address_outside_the_snapshot_refuses(self):
        """The index PRESERVES the address, yet there is nothing to
        reference it with.

        🔴 ON THE CORPUS THIS REASON NEVER FIRED, NOT ONCE (0 of 12 034 pairs
        across four decompiles on 22.08.2026), so its non-emptiness is proven
        HERE, with fabricated material. A reason that can never fire is a
        green light that means nothing.
        """
        index = JoinExtraction(joins=(
            JoinRecord("100", joined_to=("999",)),))
        out = lift_joins(index, [_op_node("100")])
        self.assertEqual(out.ops, ())
        self.assertIs(out.refusals[0].reason,
                      JoinLiftReason.TARGET_OUTSIDE_SNAPSHOT)
        self.assertIn("999", out.refusals[0].detail)

    def test_every_pair_is_either_an_op_or_a_named_refusal(self):
        """A pair has no right to vanish silently."""
        index = JoinExtraction(joins=(
            JoinRecord("100", joined_to=("200", "300", "999")),
            JoinRecord("200", joined_to=("100",)),
        ))
        out = lift_joins(index, [_op_node("100"), _op_node("200"),
                                 _atom_node("300")])
        self.assertEqual(out.pairs_read, 3)
        self.assertEqual(len(out.ops) + len(out.refusals), out.pairs_read)


class TheThreeRelationsStayApart(unittest.TestCase):

    def test_an_end_join_never_becomes_a_join_elements_op(self):
        """18.08: an end join exists, AreElementsJoined is False, JoinGeometry
        refuses. Substituting one for the other would return a building
        joined in the wrong place."""
        index = JoinExtraction(joins=(
            JoinRecord("100",
                       joined_to=(),
                       join_allowed_at_end=(True, True),
                       elements_at_end_join=(
                           EndJoin(read=True, elements=("200",)),
                           EndJoin(read=True))),
        ))
        out = lift_joins(index, [_op_node("100"), _op_node("200")])
        self.assertEqual(out.ops, (), "стык концом поднялся как слияние тел")
        self.assertEqual(out.refusals, (),
                         "род без опа — не отказ лифтера: это граница ЯЗЫКА")
        self.assertEqual(out.end_joins_read, 1)
        self.assertEqual(out.walls_with_end_permission, 1)

    def test_a_permission_is_never_read_as_a_fact(self):
        """Measurement of 800 walls: 38 of 81 mixed outcomes. It cannot be
        derived."""
        index = JoinExtraction(joins=(
            JoinRecord("100", joined_to=(),
                       join_allowed_at_end=(True, True)),))
        out = lift_joins(index, [_op_node("100")])
        self.assertEqual(out.ops, ())
        self.assertEqual(out.pairs_read, 0)

    def test_the_relations_without_an_op_are_enumerated_with_a_reason(self):
        """An empty cell reads as "such a thing does not happen"; here it
        means something else."""
        names = {row[0] for row in JOIN_RELATIONS_WITHOUT_AN_OP}
        self.assertEqual(
            names, {"join_allowed_at_end", "elements_at_end_join",
                    "порядок реза"})
        for name, member, why in JOIN_RELATIONS_WITHOUT_AN_OP:
            with self.subTest(relation=name):
                self.assertTrue(member.strip())
                self.assertGreater(len(why), 60, "названо без причины")

    def test_cut_order_is_a_named_absence_not_an_invention(self):
        """`SwitchJoinOrder` is not read — and it must not be invented."""
        row = next(r for r in JOIN_RELATIONS_WITHOUT_AN_OP
                   if r[0] == "порядок реза")
        self.assertIn("SwitchJoinOrder", row[1])
        self.assertIn("НЕ ЧИТАЕТСЯ", row[2])


class NotReadIsNotAFreeEnd(unittest.TestCase):

    def test_the_end_census_reaches_the_caller_whole(self):
        """A zero-valued key is printed: "did not occur" ≠ "cannot occur"."""
        index = JoinExtraction(joins=(
            JoinRecord("100", joined_to=(),
                       join_allowed_at_end=(True, False),
                       elements_at_end_join=(EndJoin(read=True),
                                             EndJoin(read=True))),))
        out = lift_joins(index, [_op_node("100")])
        self.assertEqual(out.end_states,
                         {"not_read": 0, "joined": 0, "free_end": 1,
                          "join_forbidden": 1, "empty_undecided": 0})

    def test_an_unread_end_is_counted_apart_from_a_free_one(self):
        index = JoinExtraction(joins=(
            JoinRecord("100", joined_to=(),
                       join_allowed_at_end=(True, True),
                       elements_at_end_join=(
                           EndJoin(read=False, why="LocationCurve отсутствует"),
                           EndJoin(read=True))),))
        out = lift_joins(index, [_op_node("100")])
        self.assertEqual(out.end_states["not_read"], 1)
        self.assertEqual(out.end_states["free_end"], 1)

    def test_a_receipt_is_not_an_absence_of_joins(self):
        """"We did not look" arrives separately from "not joined"."""
        index = JoinExtraction(
            joins=(JoinRecord("100", joined_to=()),),
            failures=(JoinFailure("300", "элемент исчез", "stale_element"),))
        out = lift_joins(index, [_op_node("100")])
        self.assertEqual(out.elements_not_read, ("300",))
        self.assertEqual(out.pairs_read, 0)


class TheIndexIsParsedByItsOwnReader(unittest.TestCase):

    def test_an_envelope_a_bare_map_and_a_parsed_index_agree(self):
        index = JoinExtraction(joins=(JoinRecord("100", joined_to=("200",)),
                                      JoinRecord("200", joined_to=("100",))))
        nodes = [_op_node("100"), _op_node("200")]
        by_object = lift_joins(index, nodes)
        by_envelope = lift_joins(index.to_dict(), nodes)
        by_bare = lift_joins(index.join_index, nodes)
        self.assertEqual(by_object.ops, by_envelope.ops)
        self.assertEqual(by_object.ops, by_bare.ops)

    def test_a_broken_index_refuses_LOUDLY(self):
        """🔴 THE DIVERGENCE FROM ITS NEIGHBORS IS DELIBERATE.

        For dimensions and tags, a corrupted index quietly becomes `{}`,
        because there a PRIOR refusal needs protecting. For joins there is no
        prior answer at all, and "the index failed to parse" -> "there are no
        joins" would reproduce the owner's complaint for whose sake the whole
        of `join_extract` was written.
        """
        with self.assertRaises(JoinPayloadError):
            lift_joins({"schema_version": "чужая/1", "join_index": {}}, [])
        with self.assertRaises(JoinPayloadError):
            lift_joins({"100": {"element_id": "999", "joined_to": []}}, [])
        with self.assertRaises(JoinPayloadError):
            lift_joins(42, [])

    def test_no_index_is_an_empty_lift_not_a_crash(self):
        out = lift_joins(None, [_op_node("100")])
        self.assertEqual(out.ops, ())
        self.assertEqual(out.pairs_read, 0)
        self.assertEqual(out.end_states["not_read"], 0)


class TheReverseContractIsAnExecutableBoundary(unittest.TestCase):

    def test_the_lift_asks_the_manifest_before_emitting(self):
        """A composite op has no right to appear without being declared in
        the manifest.

        The same law by which `_op_node` asks `assert_lift_emission`: a
        lifter branch cannot be added without explicitly extending the
        reverse contract.
        """
        from kir import reverse_contract as RC

        contract = RC.assert_composed_emission("join_elements")
        self.assertIs(contract.mode, RC.ReverseMode.COMPOSED)
        self.assertIn("lift_joins", contract.entrypoints)

        saved = RC._CONTRACTS["join_elements"]
        RC._CONTRACTS["join_elements"] = RC.ReverseContract(
            "join_elements", RC.ReverseMode.STATE_TRANSITION,
            RC.ReverseGuarantee.NONE, "подделка")
        RC.REVERSE_CONTRACTS = RC.MappingProxyType(RC._CONTRACTS)
        try:
            with self.assertRaises(RC.ReverseContractError):
                lift_joins(
                    JoinExtraction(joins=(JoinRecord("100", ("200",)),)),
                    [_op_node("100"), _op_node("200")])
        finally:
            RC._CONTRACTS["join_elements"] = saved
            RC.REVERSE_CONTRACTS = RC.MappingProxyType(RC._CONTRACTS)


if __name__ == "__main__":
    unittest.main()
