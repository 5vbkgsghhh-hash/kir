"""A family's host reference does not depend on the ORDER of L0 rows.

🔴 WHAT THIS FILE IS PAID FOR BY, THE MEASUREMENT OF 25.08.2026.

The law is stated twice in prose in this same module: "their reference is
resolved against nodes already lifted… otherwise their refusal would depend
on the order of elements in L0", and "Doors/windows are resolved in a second
pass, so their host reference is independent of L0 input order".

The deferred-pass mechanism covers `_DEFERRED_CATEGORIES` — doors, windows,
curtain wall panels, tags, dimensions. Families whose host is declared by the
`family_placement_index.host_id` RECORD (equipment, fixtures, generic
models) are not entered into it and are lifted on the FIRST pass, in
`document.elements` order.

Run: one document, one side index, a different order of two elements —

    wall BEFORE the equipment   ->  place_family with a host reference
    equipment BEFORE the wall   ->  an ATOM missing_reference,
                                    "the hosted family's host was not lifted"

One model, two answers. And the refusal SPEAKS ABOUT OUR OWN TRAVERSAL, yet
reads as a fact about the building ("there is no host") — exactly the class
of lie for whose sake the MNVNK window was rewritten on 22.08.

Worse: `MISSING_REFERENCE` is not included in `_SHAPE_REFUSALS`, i.e. the
refusal is TERMINAL, there is no second chance. And the order of L0 rows is
set by the Revit collector's traversal and is not promised to be stable
between extractions — meaning one building can be lifted differently from
run to run, taking the canonical hashes and the idempotence comparison down
with it.

WHAT IS GUARDED HERE. Not "a host is always found" — a host may genuinely be
absent. What is guarded is that the ANSWER IS THE SAME regardless of row
order.
"""

from __future__ import annotations

import copy
import unittest

from kir.decompile.lift import lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)

_СТЕНА = 9101
_ОБОРУД = 9102


def _стена() -> dict:
    строка = make_element("OST_Walls", _СТЕНА, ordinal=0)
    строка["params"] = {"WALL_USER_HEIGHT_PARAM": 3000.0,
                        "WALL_BASE_OFFSET": 0.0}
    return строка


def _оборудование() -> dict:
    строка = make_element("OST_MechanicalEquipment", _ОБОРУД, ordinal=1)
    строка["geom_kind"] = "bbox_only"
    return строка


def _индекс() -> dict:
    """The index row — through the record object ITSELF, not composed by
    hand.

    🔴 The first revision listed six fields and failed on strict parsing:
    `_exact_fields` requires EXACTLY twenty-five. Composing the shape that
    prod produces is the same class of error as reading the corpus with one's
    own parser instead of the live reader.
    """
    from kir.decompile.family_placement_extract import (
        FamilyPlacementRecord,
        FamilyPlacementType,
    )
    запись = FamilyPlacementRecord(
        element_id=str(_ОБОРУД),
        # symbol_id must match the element's `type_id`, otherwise the lift
        # will refuse for a DIFFERENT reason and the rig will measure the
        # wrong thing.
        symbol_id=make_element("OST_MechanicalEquipment", _ОБОРУД,
                               ordinal=1)["type_id"],
        # And `type_name` is taken from the element for the same reason.
        type_name=make_element("OST_MechanicalEquipment", _ОБОРУД,
                               ordinal=1)["type_name"],
        family_name="Оборудование",
        placement_type=FamilyPlacementType.ONE_LEVEL_BASED_HOSTED,
        in_place=False,
        mirrored=False,
        hand_flipped=False,
        facing_flipped=False,
        super_component_id=None,
        group_id=None,
        host_id=str(_СТЕНА),
        host_class="Wall",
        hand_orientation=(1.0, 0.0, 0.0),
        facing_orientation=(0.0, 1.0, 0.0),
        point_mm=(1000.0, 0.0, 0.0),
        rotation_deg=0.0,
        placement_available=True,
        location_absence=None,
        curve_state=None,
        curve_p0_mm=None,
        curve_p1_mm=None,
        transform_origin_mm=None,
        transform_basis_x=None,
        transform_basis_y=None,
        transform_basis_z=None,
    )
    return {str(_ОБОРУД): запись.to_dict()}


def _документ(элементы) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "host-order-probe"
    row["elements"] = copy.deepcopy(элементы)
    row["category_status"] = []
    return L0Document.from_dict(row)


class ПорядокСтрокНеРешаетСудьбуХозяина(unittest.TestCase):

    @staticmethod
    def _поднять(элементы):
        return lift_document_detailed(
            _документ(элементы), family_placement_index=_индекс())

    @staticmethod
    def _род(итог, source_id: str) -> str:
        for узел in итог.nodes:
            if узел and узел.get("source_element_id") == source_id:
                return узел.get("op_name") or узел.get("reason") or "?"
        return "—нет узла—"

    def test_ответ_один_при_обоих_порядках(self):
        сначала_стена = self._поднять([_стена(), _оборудование()])
        сначала_обор = self._поднять([_оборудование(), _стена()])
        а = self._род(сначала_стена, str(_ОБОРУД))
        б = self._род(сначала_обор, str(_ОБОРУД))
        self.assertEqual(
            а, б,
            f"один документ, два ответа: при стене впереди — {а!r}, "
            f"при оборудовании впереди — {б!r}. Отказ говорит о НАШЕМ обходе, "
            f"а читается как факт о здании.")

    def test_КОНТРОЛЬ_стена_поднимается_в_обоих_порядках(self):
        """The rig must be valid: if the wall does not lift at all, the
        match of the answers above would be a match of two refusals."""
        for элементы in ([_стена(), _оборудование()],
                         [_оборудование(), _стена()]):
            with self.subTest(порядок=элементы[0]["category"]):
                self.assertEqual(
                    self._род(self._поднять(элементы), str(_СТЕНА)),
                    "create_wall")

    def test_КОНТРОЛЬ_отсутствующий_хозяин_по_прежнему_отказ(self):
        """What is guarded is the SAMENESS of the answer, not that a host
        always exists."""
        итог = lift_document_detailed(
            _документ([_оборудование()]), family_placement_index=_индекс())
        self.assertNotEqual(self._род(итог, str(_ОБОРУД)), "place_family")


if __name__ == "__main__":
    unittest.main()
