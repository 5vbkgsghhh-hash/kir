"""THE LEDGER PROVES A FIELD BY ITS VALUE, NOT BY A MATCHED SUBSTRING.

🔴 WHY THIS WAS SET UP (07.09.2026, mandate F5 part 3). The previous
counting law stated: a field made it across if its NAME is present in the
node OR its value occurs in the node's TEXT. Neither arm proves what it
claims to:

* the name is present, the value is different — `type_name="Slab"` in L0
  against `"other"` in the node was counted as having made it across;
* the value `0` (or `1`, or `"1"`) occurs in the text of almost any node —
  an unrelated zero counted the field as having made it across for
  everything indiscriminately.

🔴 FOUR STATES INSTEAD OF TWO. "Made it across / did not" fails to
distinguish four different facts, and each is fixed differently:

    represented   the value is carried by a NAMED IR bearer (an operation
                  parameter, a node's type slot, a registry reference) and
                  matches in value, units, and coordinate system;
    approximate   the same fact is recoverable, but not byte-for-byte: a
                  namesake counterpart, a projected point (z dropped), a
                  rounded number;
    source_data   the value remains as SOURCE DATA (an opaque L0 block
                  addressed by `element_id`). Storing opaque data is NOT
                  proof of reconstruction in BIM — this is the mandate's
                  wording verbatim, and here it serves as an instrument,
                  not a slogan;
    unknown       there is no bearer at all, or the bearer carries a
                  DIFFERENT value.

🔴 UNITS ARE PART OF THE VALUE. `p0_mm=[3048]` and `p0_ft=[10.0]` are the
same place; `p0_mm=[3048]` and `p0_ft=[3048.0]` are different places, and
the second must be counted as NOT having made it across, even though the
number matches byte-for-byte. The previous law did not distinguish them at
all.
"""
from __future__ import annotations

import dataclasses
import unittest

from kir.decompile.field_ledger import STATES, field_ledger


@dataclasses.dataclass(frozen=True)
class Element:
    element_id: str
    category: str
    category_ru: str
    type_id: str
    type_name: str
    level_id: str | None = None
    level_name: str | None = None
    p0_mm: tuple | None = None
    rotation_deg: float | None = None
    host_id: str | None = None
    unique_id: str | None = None
    params: dict | None = None


@dataclasses.dataclass(frozen=True)
class Document:
    elements: tuple


def _state(ledger, element_id: str, field: str) -> str:
    row = next(r for r in ledger.rows if r.element_id == element_id)
    if field in row.kept:
        return "represented"
    item = next((x for x in row.lost if x.field == field), None)
    return "не считалось" if item is None else item.state


class ASubstringIsNotAProof(unittest.TestCase):
    """(a) Name matches, value is different."""

    def setUp(self) -> None:
        self.element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                               type_id="t1", type_name="Плита 225", level_name="Этаж 1")
        self.node = {"kind": "op", "op_name": "create_wall", "_id": "n1",
                     "source_element_id": "1", "type_name": "СОВСЕМ ДРУГОЙ ТИП",
                     "level_name": "Этаж 1", "params": {}}

    def test_a_name_whose_value_disagrees_is_not_represented(self) -> None:
        ledger = field_ledger(Document(elements=(self.element,)), [self.node])
        self.assertEqual(_state(ledger, "1", "type_name"), "unknown")
        self.assertNotIn("type_name", next(iter(ledger.rows)).kept)

    def test_the_same_name_with_the_same_value_is_represented(self) -> None:
        """Control: the instrument must distinguish a mismatch from the
        absence of a bearer."""
        node = dict(self.node, type_name="Плита 225")
        ledger = field_ledger(Document(elements=(self.element,)), [node])
        self.assertEqual(_state(ledger, "1", "type_name"), "represented")


class AForeignZeroProvesNothing(unittest.TestCase):
    """(b) A zero from an unrelated field was counted as having made it
    across."""

    def setUp(self) -> None:
        self.element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                               type_id="t1", type_name="Стена", rotation_deg=0.0,
                               level_name="Этаж 1")
        # `0.0` lives in the node in an UNRELATED field: the wall's start
        # point.
        self.node = {"kind": "op", "op_name": "create_wall", "_id": "n1",
                     "source_element_id": "1", "type_name": "Стена",
                     "level_name": "Этаж 1",
                     "params": {"p0_mm": [0.0, 0.0], "p1_mm": [12000.0, 0.0]}}

    def test_a_zero_from_another_field_does_not_keep_rotation(self) -> None:
        ledger = field_ledger(Document(elements=(self.element,)), [self.node])
        self.assertIn(_state(ledger, "1", "rotation_deg"), ("unknown", "approximate"))
        self.assertNotIn("rotation_deg", next(iter(ledger.rows)).kept)

    def test_its_own_carrier_does_keep_it(self) -> None:
        node = dict(self.node)
        node["params"] = dict(node["params"], rotation_deg=0.0)
        ledger = field_ledger(Document(elements=(self.element,)), [node])
        self.assertEqual(_state(ledger, "1", "rotation_deg"), "represented")


class OpaqueStorageIsNotReconstruction(unittest.TestCase):
    """(c) The field is stored opaque — the state is "source data," not
    "in IR"."""

    def test_the_raw_revit_parameter_blob_is_source_data(self) -> None:
        element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                          type_id="t1", type_name="Стена", level_name="Этаж 1",
                          params={"WALL_ATTR_WIDTH_PARAM": 200})
        node = {"kind": "op", "op_name": "create_wall", "_id": "n1",
                "source_element_id": "1", "type_name": "Стена",
                "level_name": "Этаж 1", "params": {"height_mm": 4500.0}}
        ledger = field_ledger(Document(elements=(element,)), [node])
        self.assertEqual(_state(ledger, "1", "params"), "source_data")
        self.assertNotIn("params", next(iter(ledger.rows)).kept)
        self.assertEqual(ledger.totals["by_state"]["source_data"], 1)

    def test_a_value_echoed_only_inside_an_opaque_region_is_source_data(self) -> None:
        """The value sits in the node, but in an area WITHOUT operational
        meaning."""
        element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                          type_id="t1", type_name="Стена", level_name="Этаж 1",
                          unique_id="u-abc-1")
        node = {"kind": "atom", "_id": "a1", "source_element_id": "1",
                "category": "OST_Walls", "category_ru": "Стены",
                "type_name": "Стена", "level_name": "Этаж 1",
                "reason": {"code": "no_lifter", "detail": "u-abc-1"}}
        ledger = field_ledger(Document(elements=(element,)), [node])
        self.assertEqual(_state(ledger, "1", "unique_id"), "source_data")


class UnitsArePartOfTheValue(unittest.TestCase):
    """(d) mm in the source, feet in IR: a correct conversion — yes, an
    incorrect one — no."""

    element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                      type_id="t1", type_name="Стена", level_name="Этаж 1",
                      p0_mm=(3048.0, 0.0))

    def _node(self, p0):
        return {"kind": "op", "op_name": "create_wall", "_id": "n1",
                "source_element_id": "1", "type_name": "Стена",
                "level_name": "Этаж 1", "params": {"p0_ft": p0}}

    def test_a_correct_conversion_is_represented(self) -> None:
        ledger = field_ledger(Document(elements=(self.element,)), [self._node([10.0, 0.0])])
        self.assertEqual(_state(ledger, "1", "p0_mm"), "represented")

    def test_the_same_number_in_another_unit_is_not_kept(self) -> None:
        """A number matching byte-for-byte in a DIFFERENT unit is a
        different place."""
        ledger = field_ledger(Document(elements=(self.element,)),
                              [self._node([3048.0, 0.0])])
        self.assertEqual(_state(ledger, "1", "p0_mm"), "unknown")
        self.assertNotIn("p0_mm", next(iter(ledger.rows)).kept)


class AProjectionIsApproximateNotExact(unittest.TestCase):
    """A dropped z is neither "made it across" nor "lost": it is a third
    state."""

    def test_a_dropped_component_is_approximate(self) -> None:
        element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                          type_id="t1", type_name="Стена", level_name="Этаж 1",
                          p0_mm=(12000.0, 2000.0, 3500.0))
        node = {"kind": "op", "op_name": "create_wall", "_id": "n1",
                "source_element_id": "1", "type_name": "Стена", "level_name": "Этаж 1",
                "params": {"p0_mm": [12000.0, 2000.0]}}
        ledger = field_ledger(Document(elements=(element,)), [node])
        self.assertEqual(_state(ledger, "1", "p0_mm"), "approximate")


class AReferenceIsProvedByWhatItResolvesTo(unittest.TestCase):
    """A registry reference `{by,value,_id}` and `{ref}` are bearers, not
    text."""

    def test_a_level_reference_carries_the_level_id(self) -> None:
        element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                          type_id="t1", type_name="Стена", level_id="274334",
                          level_name="Этаж 1")
        node = {"kind": "op", "op_name": "create_wall", "_id": "n1",
                "source_element_id": "1", "type_name": "Стена", "level_name": "Этаж 1",
                "params": {"level": {"by": "name", "value": "Этаж 1", "_id": "274334"}}}
        ledger = field_ledger(Document(elements=(element,)), [node])
        self.assertEqual(_state(ledger, "1", "level_id"), "represented")

    def test_a_reference_to_another_level_is_not_a_proof(self) -> None:
        element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                          type_id="t1", type_name="Стена", level_id="274334",
                          level_name="Этаж 1")
        node = {"kind": "op", "op_name": "create_wall", "_id": "n1",
                "source_element_id": "1", "type_name": "Стена", "level_name": "Этаж 1",
                "params": {"level": {"by": "name", "value": "Этаж 2", "_id": "999"}}}
        ledger = field_ledger(Document(elements=(element,)), [node])
        self.assertIn(_state(ledger, "1", "level_id"), ("approximate", "unknown"))

    def test_a_host_ref_is_resolved_to_the_hosted_element(self) -> None:
        """`host_id` is translated into a NODE REFERENCE — this is
        representation, not loss."""
        wall = Element(element_id="10", category="OST_Walls", category_ru="Стены",
                       type_id="t1", type_name="Стена", level_name="Этаж 1")
        door = Element(element_id="11", category="OST_Doors", category_ru="Двери",
                       type_id="t2", type_name="Дверь", level_name="Этаж 1",
                       host_id="10")
        nodes = [{"kind": "op", "op_name": "create_wall", "_id": "nw",
                  "source_element_id": "10", "type_name": "Стена",
                  "level_name": "Этаж 1", "params": {}},
                 {"kind": "op", "op_name": "create_door", "_id": "nd",
                  "source_element_id": "11", "type_name": "Дверь",
                  "level_name": "Этаж 1", "params": {"host": {"ref": "nw"}}}]
        ledger = field_ledger(Document(elements=(wall, door)), nodes)
        self.assertEqual(_state(ledger, "11", "host_id"), "represented")

    def test_a_host_ref_pointing_elsewhere_is_not_a_proof(self) -> None:
        wall = Element(element_id="10", category="OST_Walls", category_ru="Стены",
                       type_id="t1", type_name="Стена", level_name="Этаж 1")
        door = Element(element_id="11", category="OST_Doors", category_ru="Двери",
                       type_id="t2", type_name="Дверь", level_name="Этаж 1",
                       host_id="99")
        nodes = [{"kind": "op", "op_name": "create_wall", "_id": "nw",
                  "source_element_id": "10", "type_name": "Стена",
                  "level_name": "Этаж 1", "params": {}},
                 {"kind": "op", "op_name": "create_door", "_id": "nd",
                  "source_element_id": "11", "type_name": "Дверь",
                  "level_name": "Этаж 1", "params": {"host": {"ref": "nw"}}}]
        ledger = field_ledger(Document(elements=(wall, door)), nodes)
        self.assertEqual(_state(ledger, "11", "host_id"), "unknown")


class TheFourStatesAreCountedAndSum(unittest.TestCase):
    """The sum of the states must agree with the number of non-empty
    fields."""

    def test_the_states_sum_to_the_nonempty_fields(self) -> None:
        element = Element(element_id="1", category="OST_Walls", category_ru="Стены",
                          type_id="t1", type_name="Стена", level_id="L1",
                          level_name="Этаж 1", unique_id="u1", params={"A": 1})
        node = {"kind": "op", "op_name": "create_wall", "_id": "n1",
                "source_element_id": "1", "type_name": "Стена",
                "level_name": "Этаж 1", "params": {}}
        ledger = field_ledger(Document(elements=(element,)), [node])
        totals = ledger.totals
        self.assertEqual(sorted(totals["by_state"]), sorted(STATES))
        self.assertEqual(sum(totals["by_state"].values()), totals["nonempty"])
        self.assertEqual(totals["by_state"]["represented"], len(ledger.rows[0].kept))
        self.assertEqual(totals["nonempty"] - totals["by_state"]["represented"],
                         totals["lost"])


if __name__ == "__main__":                                     # pragma: no cover
    unittest.main()


class ThePlacementPointHasAnIrSlotOfItsOwn(unittest.TestCase):
    """🔴 THE PLACEMENT POINT LIVES IN `anchor_mm`, AND THAT IS A BEARER
    (measured 07.09.2026).

    `create_door` names the HOST and the OFFSET ALONG THE WALL, while the
    point is held by the node slot `anchor_mm` — right next to
    `level_name` and `type_name`, which the ledger already counts as
    bearers. The previous law looked for a bearer ONLY by name match and
    declared `p0_mm` lost for 126 doors and 756 `bench_A` columns, even
    though the point sits in the node byte-for-byte.

    The control here is INSIDE the instrument: for a wall, `anchor_mm` is
    the MIDPOINT of the segment, and it is not counted for `p0_mm`. A slot
    that counted anything at all would be a concession, not a bearer.
    """

    def _door(self, anchor):
        element = Element(element_id="286533", category="OST_Doors",
                          category_ru="Двери", type_id="29797",
                          type_name="0864 x 2134 мм", p0_mm=(24000.0, 5000.0, 0.0))
        node = {"kind": "op", "op_name": "create_door", "_id": "n1",
                "type_name": "0864 x 2134 мм", "source_element_id": "286533",
                "params": {"offset_mm": 3000.0}, "anchor_mm": anchor}
        return field_ledger(Document(elements=(element,)), [node])

    def test_the_anchor_slot_carries_the_placement_point(self) -> None:
        ledger = self._door([24000.0, 5000.0, 0.0])
        self.assertEqual(_state(ledger, "286533", "p0_mm"), "represented")

    def test_an_anchor_holding_another_point_is_not_a_proof(self) -> None:
        # FAIL control: the same slot, a DIFFERENT value. If the
        # instrument is green here too, it proves the key's presence, not
        # the point.
        ledger = self._door([1.0, 2.0, 3.0])
        self.assertNotEqual(_state(ledger, "286533", "p0_mm"), "represented")

    def test_a_wall_midpoint_anchor_does_not_prove_the_start_point(self) -> None:
        element = Element(element_id="286529", category="OST_Walls",
                          category_ru="Стены", type_id="1740",
                          type_name="Типовой - 200мм", p0_mm=(12000.0, 2000.0, 0.0))
        node = {"kind": "op", "op_name": "create_wall", "_id": "n1",
                "type_name": "Типовой - 200мм", "source_element_id": "286529",
                "params": {"p1_mm": [24000.0, 2000.0]},
                "anchor_mm": [18000.0, 2000.0, 0.0]}
        ledger = field_ledger(Document(elements=(element,)), [node])
        self.assertNotEqual(_state(ledger, "286529", "p0_mm"), "represented")


class AHostIsProvedByTheEntityAddressed(unittest.TestCase):
    """🔴 A REFERENCE ADDRESSES AN ENTITY, NOT A KEY (measured 07.09.2026).

    Beam `bench_A` 296802 has `host_id = 296349`, and the node addresses
    exactly this entity — via the reference `params.level._id`. The beam's
    host IS its level. The prior revision looked for a host only under the
    key `host` and declared it lost for 777 of 1207 beams: the verdict was
    describing our search, not the building.

    A FAIL control INSIDE the instrument: a reference to a DIFFERENT host
    entity does not prove anything, no matter how many named references
    sit in the node.
    """

    def _beam(self, level_id):
        element = Element(element_id="296802", category="OST_StructuralFraming",
                          category_ru="Каркас несущий", type_id="169118",
                          type_name="I 20H1", host_id="296349")
        node = {"kind": "op", "op_name": "create_beam", "_id": "n1",
                "type_name": "I 20H1", "source_element_id": "296802",
                "params": {"level": {"by": "name", "value": "HB-Ур.2",
                                     "_id": level_id},
                           "symbol": {"by": "name", "value": "I 20H1",
                                      "_id": "169118"}}}
        return field_ledger(Document(elements=(element,)), [node])

    def test_a_level_reference_to_the_host_element_proves_the_host(self) -> None:
        ledger = self._beam("296349")
        self.assertEqual(_state(ledger, "296802", "host_id"), "represented")

    def test_the_carrier_names_where_the_host_was_found(self) -> None:
        # A verdict without an address has nothing to be re-checked
        # against: the address must be named.
        ledger = self._beam("296349")
        row = next(r for r in ledger.rows if r.element_id == "296802")
        self.assertNotIn("host_id", [item.field for item in row.lost])
        self.assertIn("host_id", row.kept)

    def test_a_reference_to_another_element_is_not_a_host_proof(self) -> None:
        # FAIL control: the reference exists, addressing something
        # DIFFERENT.
        ledger = self._beam("999999")
        self.assertNotEqual(_state(ledger, "296802", "host_id"), "represented")


class TheSameWordCanNameAnotherSubject(unittest.TestCase):
    """🔴 A MATCHING NAME IS NOT A BEARER IF THE SUBJECT IS DIFFERENT
    (measured 07.09.2026).

    `create_column.category` is the enum `structural|architectural`, while
    `L0.category` is the Revit category `OST_StructuralColumns`. The
    previous count attributed such losses to "the op has the word, the
    lifter failed to deliver it" — that is, to the LIFTER'S DEBT: 756 of
    1708 such losses for `bench_A` were this one case. There is no debt —
    there is a language boundary, and it must be named as such.

    A control INSIDE the instrument: the accusation is lifted, but proof
    is NOT added — the field's state remains lost.
    """

    def _column(self):
        element = Element(element_id="289025", category="OST_StructuralColumns",
                          category_ru="Несущие колонны", type_id="48056",
                          type_name="305x305x97UC")
        node = {"kind": "op", "op_name": "create_column", "_id": "n1",
                "type_name": "305x305x97UC", "source_element_id": "289025",
                "params": {"category": "structural"}}
        return field_ledger(Document(elements=(element,)), [node])

    def test_the_colliding_word_is_not_a_debt_of_the_lifter(self) -> None:
        ledger = self._column()
        row = next(r for r in ledger.rows if r.element_id == "289025")
        item = next(x for x in row.lost if x.field == "category")
        self.assertFalse(item.in_op_contract)
        self.assertEqual(ledger.totals["lost_though_the_op_contract_has_the_word"], 0)

    def test_removing_the_accusation_does_not_add_a_proof(self) -> None:
        self.assertNotEqual(_state(self._column(), "289025", "category"),
                            "represented")


class ARemovedLossIsNotAProvenReconstruction(unittest.TestCase):
    """🔴 A CAVEAT AGAINST ITS OWN NUMBER (07.09.2026).

    `anchor_mm` is a standard L1-schema slot, and its value matches
    byte-for-byte: by the counting law the field is represented. But
    `fold` calls it DERIVED and drops it from the canonical form — the
    door's rebuild places it by `host` and `offset_mm`, not by this point.
    "Loss lifted" and "reconstruction proven" are different facts, and the
    number must keep them apart, or a rising percentage would read as a
    promise nobody made.
    """

    def test_the_derived_slot_is_counted_separately(self) -> None:
        element = Element(element_id="1", category="OST_Doors",
                          category_ru="Двери", type_id="7", type_name="Д-1",
                          p0_mm=(1.0, 2.0, 3.0))
        node = {"kind": "op", "op_name": "create_door", "_id": "n1",
                "type_name": "Д-1", "source_element_id": "1",
                "params": {"offset_mm": 5.0}, "anchor_mm": [1.0, 2.0, 3.0]}
        ledger = field_ledger(Document(elements=(element,)), [node])
        self.assertEqual(_state(ledger, "1", "p0_mm"), "represented")
        self.assertEqual(ledger.totals["represented_via_derived_slot"], 1)

    def test_an_authored_parameter_is_not_counted_as_derived(self) -> None:
        # Control: a point that arrived as an OPERATION PARAMETER does not
        # fall under the caveat — otherwise the counter would accuse
        # everything indiscriminately and mean nothing.
        element = Element(element_id="2", category="OST_StructuralFraming",
                          category_ru="Каркас", type_id="7", type_name="Б-1",
                          p0_mm=(1.0, 2.0, 3.0))
        node = {"kind": "op", "op_name": "create_beam", "_id": "n1",
                "type_name": "Б-1", "source_element_id": "2",
                "params": {"p0_mm": [1.0, 2.0, 3.0]},
                "anchor_mm": [1.0, 2.0, 3.0]}
        ledger = field_ledger(Document(elements=(element,)), [node])
        self.assertEqual(_state(ledger, "2", "p0_mm"), "represented")
        self.assertEqual(ledger.totals["represented_via_derived_slot"], 0)
