"""GROUPS ARE LIFTED INTO THE PROGRAM — `lift.lift_groups`.

MOTIVATION. The unit of design intent in a real building is named by the
DESIGNER THEMSELVES, and group names are direct speech about the intent:
`АР_Квартира_Ст_Секция 1_Тип1_3-7,9-11 этаж_кв 3_` ×12,
`Отделка лестниц_типовой этаж` ×15. The `create_group` op exists in the
registry and is proven live by a full chain, the side index has been taken
(177 definitions, 575 occurrences) and is already read by the fold as a
BOUNDARY — while `lift.py` had ZERO lines about groups, and `create_group` was
called ZERO times across 51 574 lifted operations.

FOUR THINGS THIS FILE GUARDS:

1. **the member ceiling is checked AGAINST THE VALIDATOR BEHAVIORALLY, not by
   a literal.** `_GROUP_MEMBER_CEILING` is a second carrier of the number that
   `authoring_validation` ENFORCES; checking a literal against a literal would
   mean starting a third one and calling it a check.
2. **the offset is DERIVED, not made up.** `Group` has no rotation at all in
   the Revit API; when members give different vectors, the op does not
   appear — "let's take the first one" would be an address-by-guess.
3. **every kind of refusal is NON-EMPTY.** A reason that cannot be triggered
   is decoration, not a discriminator.
4. **`None` and an empty `GroupLift` are DIFFERENT.** The first means "the
   index was not supplied", the second means "it was supplied, there are no
   groups".

Run:
    venv/bin/python -m pytest kir/decompile/tests/test_group_lift.py -q
"""
from __future__ import annotations

import unittest

from kir.decompile.l1_schema import stable_l1_id
from kir.decompile.lift import (
    GroupLift,
    GroupLiftReason,
    _GROUP_MEMBER_CEILING,
    _group_member_eligible,
    lift_groups,
)
from kir.decompile.schema import GeometryKind, L0Document, L0Element


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
        "reason": {"code": code, "detail": "нет кривой"},
        "source_element_id": source_id,
        "level_name": "Уровень 1",
        "anchor_mm": None,
        "bbox_min_mm": None,
        "bbox_max_mm": None,
    }


def _element(element_id: str, point) -> L0Element:
    return L0Element.from_dict({
        "element_id": element_id,
        "category": "OST_Walls",
        "category_ru": "Стены",
        "type_id": "7",
        "type_name": "Стена",
        "level_id": "1",
        "level_name": "Уровень 1",
        # A member WITHOUT a point is `bbox_only`: for a fixture and for a
        # floor-by-outline, `LocationPoint` is empty, and there is nothing
        # from which to derive an offset. The `none` kind is absent from the
        # enumeration, and making it up here would mean introducing a state
        # that L0 does not know.
        "geom_kind": "point" if point is not None else "bbox_only",
        "p0_mm": list(point) if point is not None else None,
        "p1_mm": None,
        "rotation_deg": None,
        "bbox_min_mm": None,
        "bbox_max_mm": None,
        "host_id": None,
        "params": {},
    })


def _document(elements) -> L0Document:
    return L0Document.from_dict({
        "doc_name": "d", "revit_version": "2024", "units": "mm",
        "change_stamp": "s", "levels": [], "grids": [], "rooms": [],
        "project_info": {},
        "elements": [e.to_dict() for e in elements],
    })


def _instance(member_ids) -> dict:
    """One occurrence in RAW form — the index will derive the definitions
    ITSELF.

    🔴 A HANDWRITTEN DEFINITION IS NOT ACCEPTED HERE, and rightly so: the
    strict parser checks the supplied `definitions`/`composition_mismatches`
    against its own tally over occurrences and rejects any discrepancy —
    "definitions are derivations, never a second authority". A test that
    wrote them by hand would introduce exactly the second carrier that the
    check stands against.
    """
    return {
        "group_type_id": "g1", "group_type_name": "Г",
        "member_ids": list(member_ids), "group_id_parent": None,
        "attached_detail_type_count": 0, "transform_available": False,
        "origin_mm": None, "rotation_deg": None,
        "level_binding_available": False,
        "reference_level_id": None, "origin_level_offset_mm": None,
    }


def _index(instances: dict) -> dict:
    """A bare occurrence index — the `parse_group_index` path without an
    envelope."""
    return dict(instances)


class ПотолокЧленовСверяетсяСВалидатором(unittest.TestCase):
    """🔴 THE SECOND CARRIER OF THE NUMBER IS CHECKED BY THE FIRST ONE'S
    BEHAVIOR."""

    def _complains(self, member_count: int) -> bool:
        from kir import authoring_validation as av
        op = {
            "op": "create_group", "id": "G",
            "members": [
                {"op": "create_level", "id": f"m{i}", "name": f"L{i}",
                 "elevation_mm": float(i)}
                for i in range(member_count)
            ],
            "placements": [],
        }
        diags: list = []
        av.validate(op, "create_group", 0, "G", diags)
        return any(getattr(d, "field_name", None) == "members" for d in diags)

    def test_ceiling_matches_what_the_validator_enforces(self):
        at = self._complains(_GROUP_MEMBER_CEILING)
        over = self._complains(_GROUP_MEMBER_CEILING + 1)

        self.assertFalse(
            at,
            f"валидатор отверг {_GROUP_MEMBER_CEILING} членов — потолок "
            "лифтера ЗАВЫШЕН и он начнёт отказывать тому, что язык принимает")
        self.assertTrue(
            over,
            f"валидатор принял {_GROUP_MEMBER_CEILING + 1} членов — потолок "
            "лифтера ЗАНИЖЕН и он отказывает без причины")


class ГодностьЧленаБерётсяИзРеестра(unittest.TestCase):

    def test_room_separator_is_ineligible_because_it_makes_many(self):
        """🔴 A LIVE MEASUREMENT, NOT AN INVENTION: K6 439 members in 31
        definitions."""
        self.assertTrue(_group_member_eligible("create_wall"))
        self.assertFalse(
            _group_member_eligible("create_room_separator"),
            "одна операция порождает НЕСКОЛЬКО элементов — слоту "
            "определения соответствовать не может")
        self.assertFalse(_group_member_eligible("create_group"))
        self.assertFalse(_group_member_eligible("create_stairs"),  # solo
                         "solo-оп не может ехать внутри группы")


class ИндексаНеПодавали(unittest.TestCase):

    def test_none_is_not_an_empty_lift(self):
        got = lift_groups(None, (), _document(()))
        self.assertEqual(got, GroupLift())
        self.assertEqual(got.definitions_read, 0)


class СдвигВыводитсяИзЧленов(unittest.TestCase):

    def _case(self, other_points, member_points=((0.0, 0.0, 0.0),
                                                 (1000.0, 0.0, 0.0))):
        members = [f"m{i}" for i in range(len(member_points))]
        others = [f"o{i}" for i in range(len(other_points))]
        elements = [_element(m, p) for m, p in zip(members, member_points)]
        elements += [_element(o, p) for o, p in zip(others, other_points)]
        nodes = [_op_node(m) for m in members]
        index = _index({"100": _instance(members), "200": _instance(others)})
        return lift_groups(index, nodes, _document(elements))

    def test_clean_translation_becomes_one_placement(self):
        got = self._case(((0.0, 0.0, 3300.0), (1000.0, 0.0, 3300.0)))
        self.assertEqual(len(got.ops), 1, got.refusals)
        op = got.ops[0]
        self.assertEqual(op["op_name"], "create_group")
        self.assertEqual(op["params"]["placements"], [[0.0, 0.0, 3300.0]])
        self.assertEqual(len(op["params"]["members"]), 2)
        self.assertEqual(op["params"]["name"], "Г")
        # 2 members × 2 occurrences = 4 individually; as a group 2 members +
        # 1 op = 3
        self.assertEqual(got.ops_not_written_individually, 1)
        self.assertEqual(got.instances_covered, 2)

    def test_disagreeing_members_refuse_instead_of_guessing(self):
        got = self._case(((0.0, 0.0, 3300.0), (1000.0, 0.0, 9999.0)))
        self.assertEqual(got.ops, ())
        self.assertEqual(got.refusals[0].reason,
                         GroupLiftReason.PLACEMENT_AMBIGUOUS)

    def test_members_without_a_point_are_a_named_limit(self):
        got = self._case(((0.0, 0.0, 3300.0), (1000.0, 0.0, 3300.0)),
                         member_points=(None, None))
        self.assertEqual(got.ops, ())
        self.assertEqual(got.refusals[0].reason,
                         GroupLiftReason.PLACEMENT_NOT_DERIVABLE)


class КаждыйРодОтказаНепуст(unittest.TestCase):
    """A reason that cannot be triggered is decoration, not a discriminator."""

    def _lift(self, members, nodes, elements, extra_instances=()):
        inst = {"100": _instance(members)}
        for ordinal, extra in enumerate(extra_instances):
            inst[str(200 + ordinal)] = _instance(extra)
        return lift_groups(_index(inst), nodes, _document(elements))

    def test_member_outside_snapshot(self):
        got = self._lift(["m0"], [], [])
        self.assertEqual(got.refusals[0].reason,
                         GroupLiftReason.MEMBER_OUTSIDE_SNAPSHOT)

    def test_member_stayed_atom(self):
        got = self._lift(["m0"], [_atom_node("m0")], [_element("m0", (0, 0, 0))])
        self.assertEqual(got.refusals[0].reason,
                         GroupLiftReason.MEMBER_STAYED_ATOM)
        self.assertIn("missing_geometry", got.refusals[0].detail)

    def test_member_op_ineligible(self):
        got = self._lift(["m0"], [_op_node("m0", "create_room_separator")],
                         [_element("m0", (0, 0, 0))])
        self.assertEqual(got.refusals[0].reason,
                         GroupLiftReason.MEMBER_OP_INELIGIBLE)

    def test_member_count_over_ceiling(self):
        n = _GROUP_MEMBER_CEILING + 1
        members = [f"m{i}" for i in range(n)]
        got = self._lift(members, [_op_node(m) for m in members],
                         [_element(m, (0, 0, 0)) for m in members])
        self.assertEqual(got.refusals[0].reason,
                         GroupLiftReason.MEMBER_COUNT_OVER_CEILING)

    def test_definition_has_no_members(self):
        got = self._lift([], [], [])
        self.assertEqual(got.refusals[0].reason,
                         GroupLiftReason.DEFINITION_HAS_NO_MEMBERS)

    def test_composition_mismatch(self):
        """The occurrence's cardinality is GENUINELY different — the index
        derives it itself."""
        got = self._lift(
            ["m0", "m1"],
            [_op_node("m0"), _op_node("m1")],
            [_element("m0", (0.0, 0.0, 0.0)), _element("m1", (1.0, 0.0, 0.0))],
            extra_instances=(["m0"],))
        self.assertEqual(got.composition_mismatches, 1)
        self.assertEqual(got.refusals[0].reason,
                         GroupLiftReason.COMPOSITION_MISMATCH)

    def test_every_reason_is_reachable(self):
        """Summary: not a single kind was left unreachable."""
        covered = {
            GroupLiftReason.MEMBER_OUTSIDE_SNAPSHOT,
            GroupLiftReason.MEMBER_STAYED_ATOM,
            GroupLiftReason.MEMBER_OP_INELIGIBLE,
            GroupLiftReason.MEMBER_COUNT_OVER_CEILING,
            GroupLiftReason.DEFINITION_HAS_NO_MEMBERS,
            GroupLiftReason.PLACEMENT_NOT_DERIVABLE,
            GroupLiftReason.PLACEMENT_AMBIGUOUS,
            GroupLiftReason.COMPOSITION_MISMATCH,
        }
        self.assertEqual(covered, set(GroupLiftReason))


class Перепись(unittest.TestCase):

    def test_lifted_plus_refused_equals_read(self):
        members = ["m0", "m1"]
        got = lift_groups(
            _index({"100": _instance(members)}),
            [_op_node(m) for m in members],
            _document([_element(m, (0.0, 0.0, 0.0)) for m in members]))
        self.assertEqual(len(got.ops) + len(got.refusals),
                         got.definitions_read)


if __name__ == "__main__":
    unittest.main()
