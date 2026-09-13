"""A curtain wall mullion is a child of the carrier's TYPE, or a manual
grid edit.

MEASUREMENT BEFORE THIS WAVE (28.07, index schema /3):

* ``sob62_fas_r23_v11``: 197 curtain wall carriers, **964 mullions**, every
  single one an ``unsupported_forward_signature`` atom. This is the
  facade's largest remainder;
* ``sob62_fas_r23_v12``: the same rows, 1372 mullions;
* ``демо-v3``: 26291 mullions.

A mullion does NOT NEED its own operation: the one the carrier's type
places will be born on its own during reassembly. But "is born on its own"
is a claim about the TYPE, and it must be proven by the type, or else
coverage grows by subtracting from the denominator something reassembly
will not actually build. Hence exactly two witnesses here, both readable
from Revit:

* ``Mullion.Lock`` — "is the Mullion line locked" (RevitAPI.xml across all
  six versions); Revit itself knows the reverse transition:
  ``CurtainWallFailures.RequestOrphanMullionDeletion`` — "some mullions
  became non-type driven";
* the mullion's type among the carrier type's twelve ``AUTO_MULLION_*``
  slots.

Schema /3 read NEITHER of them — so all 964 remain atoms even after this
wave, pending fresh extraction by schema /4. The test below holds exactly
that: the pre-state HONESTLY remains a refusal, and is not retroactively
turned into coverage.

THE ROWS ARE TAKEN LIVE. Carrier ``8145922`` and its mullions
``8145925/26/27`` of type «50х250 мм_Смещение -80мм» — from
``data/decompile/sob62_fas_r23_v11/curtain.index.json``; the /4 witnesses
for them are appended here and marked as appended (live extraction by
schema /4 has not happened yet).
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kir.decompile.curtain_extract import (
    CURTAIN_INDEX_SCHEMA_VERSION,
    CURTAIN_INDEX_SCHEMA_VERSION_PANEL_STATE,
    AutoMullionState,
    AutoMullionTypes,
    CurtainWallRecord,
    MullionDirection,
    MullionRecord,
    MullionState,
)
from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)


HOST_ID = "8145922"
MULLION_ID = "8145925"
#: A mullion type the carrier places on its own — and one it does not.
TYPE_DRIVEN_TYPE_ID = "606060"
FOREIGN_TYPE_ID = "707070"
MULLION_TYPE_NAME = "50х250 мм_Смещение -80мм"


def _mullion_row_v3(mullion_id: str = MULLION_ID) -> dict[str, Any]:
    """A live row of schema /3 — exactly as it sits in v11."""

    return {
        "mullion_id": mullion_id,
        "type_name": MULLION_TYPE_NAME,
        "curve_state": "curved_unsupported",
        "p0_mm": None,
        "p1_mm": None,
    }


def _mullion_row(
    mullion_id: str = MULLION_ID,
    *,
    type_id: str | None = TYPE_DRIVEN_TYPE_ID,
    locked: bool | None = True,
    direction: str = "vertical",
) -> dict[str, Any]:
    row = _mullion_row_v3(mullion_id)
    row.update(type_id=type_id, locked=locked, direction=direction)
    return row


def _slots(**values: str) -> dict[str, Any]:
    return {
        "slots": dict(values),
        "state": (AutoMullionState.OK.value if values
                  else AutoMullionState.NONE.value),
    }


def _index(
    mullions: list[dict[str, Any]],
    *,
    auto_mullion_types: dict[str, Any] | None = None,
    host_kind: str = "wall",
    schema_version: str = CURTAIN_INDEX_SCHEMA_VERSION,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "curtain_available": True,
        "host_kind": host_kind,
        "default_panel_type_id": "7469627",
        "default_panel_type_name": "НР_ВТ_Стеклопакет_30мм",
        "default_panel_state": "ok",
        "default_panel_source": "AUTO_PANEL_WALL",
        "u_grid_lines": [],
        "v_grid_lines": [],
        "panels": [],
        "mullions": mullions,
    }
    if auto_mullion_types is not None:
        row["auto_mullion_types"] = auto_mullion_types
    return {
        "schema_version": schema_version,
        "curtain_index": {HOST_ID: row},
        "failures": [],
    }


def _document(mullion_ids: tuple[str, ...] = (MULLION_ID,)) -> L0Document:
    wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
    wall["element_id"] = HOST_ID
    wall["type_name"] = "Витраж НР_ВТ"
    elements = [wall]
    for ordinal, mullion_id in enumerate(mullion_ids, start=1):
        mullion = make_element(
            "OST_CurtainWallMullions", int(mullion_id), ordinal=ordinal)
        mullion["element_id"] = mullion_id
        mullion["host_id"] = HOST_ID
        mullion["type_name"] = MULLION_TYPE_NAME
        mullion["geom_kind"] = "curve"
        mullion["p0_mm"] = [0.0, 0.0, 0.0]
        mullion["p1_mm"] = [0.0, 0.0, 3000.0]
        elements.append(mullion)
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-mullion-v1"
    row["elements"] = elements
    row["category_status"] = []
    return L0Document.from_dict(row)


def _atom(result, source_id: str = MULLION_ID) -> dict[str, Any]:
    nodes = {node["source_element_id"]: node for node in result.nodes}
    return nodes[source_id]


class MullionVerdict(unittest.TestCase):
    """The verdict is computed from the records, without any lift at
    all."""

    @staticmethod
    def _record(
        mullion: MullionRecord,
        auto: AutoMullionTypes,
        host_kind_row: str = "wall",
    ) -> CurtainWallRecord:
        return CurtainWallRecord.from_dict(HOST_ID, {
            "curtain_available": True,
            "host_kind": host_kind_row,
            "default_panel_type_id": None,
            "default_panel_type_name": None,
            "default_panel_state": "not_captured",
            "default_panel_source": None,
            "auto_mullion_types": auto.to_dict(),
            "u_grid_lines": [],
            "v_grid_lines": [],
            "panels": [],
            "mullions": [mullion.to_dict()],
        })

    def test_locked_and_typed_is_type_driven(self) -> None:
        record = self._record(
            MullionRecord.from_wire(_mullion_row(), "m"),
            AutoMullionTypes.from_wire(
                _slots(interior_vert=TYPE_DRIVEN_TYPE_ID), "a"))
        self.assertEqual(
            record.mullion_state(record.mullions[0]),
            MullionState.TYPE_DRIVEN)

    def test_unlocked_is_manual_even_when_the_type_matches(self) -> None:
        """An unlocked mullion is NOT driven by the type — Revit says so
        itself."""

        record = self._record(
            MullionRecord.from_wire(_mullion_row(locked=False), "m"),
            AutoMullionTypes.from_wire(
                _slots(interior_vert=TYPE_DRIVEN_TYPE_ID), "a"))
        self.assertEqual(
            record.mullion_state(record.mullions[0]), MullionState.MANUAL)

    def test_foreign_type_is_manual_even_when_locked(self) -> None:
        record = self._record(
            MullionRecord.from_wire(
                _mullion_row(type_id=FOREIGN_TYPE_ID), "m"),
            AutoMullionTypes.from_wire(
                _slots(interior_vert=TYPE_DRIVEN_TYPE_ID), "a"))
        self.assertEqual(
            record.mullion_state(record.mullions[0]), MullionState.MANUAL)

    def test_direction_narrows_the_candidate_slots_on_a_wall(self) -> None:
        """A vertical mullion is checked against the VERTICAL slots."""

        record = self._record(
            MullionRecord.from_wire(_mullion_row(direction="vertical"), "m"),
            AutoMullionTypes.from_wire(
                _slots(interior_horiz=TYPE_DRIVEN_TYPE_ID), "a"))
        self.assertEqual(
            record.mullion_state(record.mullions[0]), MullionState.MANUAL)

    def test_grid_family_is_not_narrowed_by_direction(self) -> None:
        """In a curtain wall system the axes are called GRID1/GRID2 —
        there is no "vertical" among them."""

        record = self._record(
            MullionRecord.from_wire(_mullion_row(direction="horizontal"), "m"),
            AutoMullionTypes.from_wire(
                _slots(interior_grid1=TYPE_DRIVEN_TYPE_ID), "a"),
            host_kind_row="curtain_system")
        self.assertEqual(
            record.mullion_state(record.mullions[0]),
            MullionState.TYPE_DRIVEN)

    def test_missing_witness_is_unreadable_not_a_guess(self) -> None:
        for row, auto in (
            (_mullion_row(locked=None),
             _slots(interior_vert=TYPE_DRIVEN_TYPE_ID)),
            (_mullion_row(type_id=None),
             _slots(interior_vert=TYPE_DRIVEN_TYPE_ID)),
            (_mullion_row(),
             {"slots": {}, "state": AutoMullionState.UNREADABLE.value}),
        ):
            with self.subTest(row=row, auto=auto["state"]):
                record = self._record(
                    MullionRecord.from_wire(row, "m"),
                    AutoMullionTypes.from_wire(auto, "a"))
                self.assertEqual(
                    record.mullion_state(record.mullions[0]),
                    MullionState.UNREADABLE)

    def test_host_type_that_places_nothing_makes_every_mullion_manual(
            self) -> None:
        """``none`` is a read fact: the type does not place mullions at
        all."""

        record = self._record(
            MullionRecord.from_wire(_mullion_row(), "m"),
            AutoMullionTypes.from_wire(_slots(), "a"))
        self.assertEqual(
            record.mullion_state(record.mullions[0]), MullionState.MANUAL)


class MullionLift(unittest.TestCase):
    def test_v3_row_stays_an_atom_and_says_why(self) -> None:
        """PRE-STATE: 964 mullions in v11 are atoms, and remain atoms."""

        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                [_mullion_row_v3()],
                schema_version=CURTAIN_INDEX_SCHEMA_VERSION_PANEL_STATE))
        atom = _atom(result)
        self.assertEqual(atom["kind"], "atom")
        self.assertEqual(
            atom["reason"]["code"], AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("свежее извлечение", atom["reason"]["detail"])

    def test_type_driven_mullion_becomes_generator_child(self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                [_mullion_row()],
                auto_mullion_types=_slots(
                    interior_vert=TYPE_DRIVEN_TYPE_ID)))
        atom = _atom(result)
        self.assertEqual(atom["kind"], "atom")
        self.assertEqual(
            atom["reason"]["code"], AtomReason.GENERATOR_CHILD.value)
        self.assertIn("порождается типом носителя", atom["reason"]["detail"])

    def test_hand_edited_grid_stays_an_atom(self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                [_mullion_row(locked=False)],
                auto_mullion_types=_slots(
                    interior_vert=TYPE_DRIVEN_TYPE_ID)))
        atom = _atom(result)
        self.assertEqual(atom["kind"], "atom")
        self.assertEqual(
            atom["reason"]["code"], AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("правлена вручную", atom["reason"]["detail"])

    def test_a_mullion_never_becomes_a_placement_op(self) -> None:
        """No outcome may place a mullion as a family instance.

        The v6 measurement named the cost of the opposite: 956
        ``place_family`` calls on mullions — 42% of all facade
        operations, and each would place a second mullion on top of the
        one the curtain wall generates itself.
        """

        for auto in (None, _slots(interior_vert=TYPE_DRIVEN_TYPE_ID),
                     _slots()):
            with self.subTest(auto=auto):
                result = lift_document_detailed(
                    _document(("8145925", "8145926", "8145927")),
                    curtain_index=_index(
                        [_mullion_row("8145925"), _mullion_row("8145926"),
                         _mullion_row("8145927")],
                        auto_mullion_types=auto))
                ops = [node for node in result.nodes
                       if node["kind"] == "op"
                       and node["source_element_id"] != HOST_ID]
                self.assertEqual(ops, [])
                # A multiset: three mullions — exactly three nodes, with
                # no self-duplicates and no losses.
                sources = [node["source_element_id"] for node in result.nodes]
                self.assertEqual(len(sources), len(set(sources)))
                self.assertEqual(len(sources), 4)


if __name__ == "__main__":
    unittest.main()
