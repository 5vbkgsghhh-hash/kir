"""Curtain wall grid layout — the generator's missing link.

NIGHT MEASUREMENT OF 28.07 (``kir-night/artifacts/child_closure_20260728.json``):
child closure 417/1556 = 27%, and ALL reassembled carriers have ZERO
internal U/V lines despite BYTE-IDENTICAL types. The diagnosis from that is
direct: grid layout is authored state that ``create_wall`` does not carry,
and without it not a single cell, mullion, or panel of the curtain wall
reproduces — the carrier's whole family of children.

PRE-STATE (v13, index schema /4): 70 carriers have lines — 122 of them, all
read as a straight curve with endpoints in mm — and NOT ONE operation on
them. The line is also absent from L0: the collector does not gather its
category at all (measured: 122 index lines, 0 among 3153 L0 elements). So
the node is not lifted from an element but is SYNTHESIZED from the side
index and references the carrier.

HONESTY. A line becomes an operation ONLY once it is proven that the
carrier's type does not produce it itself: the type layout (six
``SPACING_LAYOUT_*`` parameters) is read by schema /5 and compared against
zero — as a NUMBER, not by interpreting a name. If the type divides the
grid itself ⇒ no operation: a doubled line is worse than a missing one. If
the layout was not read ⇒ also no operation, and the reason is named.

THE ROWS ARE TAKEN LIVE: carrier ``8145922`` and its line ``8145929`` with
endpoints from ``data/decompile/sob62_fas_r23_v13/curtain.index.json``; the
type layout is appended here and marked as appended (live extraction by
schema /5 has not happened yet).
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kir.decompile.curtain_extract import (
    CURTAIN_INDEX_SCHEMA_VERSION,
    CURTAIN_INDEX_SCHEMA_VERSION_MULLION,
    GRID_LAYOUT_NONE,
    CurtainWallRecord,
    GridLayout,
    GridLayoutState,
    GridLineState,
)
from kir.decompile.l1_schema import AtomReason, stable_l1_id
from kir.decompile.lift import lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)


HOST_ID = "8145922"
LINE_ID = "8145929"
P0 = [6890.514473904456, 28537.503893960205, 4924.999999999713]
P1 = [8545.171981203326, 29107.24816426004, 4924.999999999713]
#: The midpoint of the live line — the point through which AddGridLine
#: places it.
MID = [round((a + b) / 2.0, 6) for a, b in zip(P0, P1)]


def _line_row(line_id: str = LINE_ID, *,
              curve_state: str = "line") -> dict[str, Any]:
    straight = curve_state == "line"
    return {
        "line_id": line_id,
        "curve_state": curve_state,
        "p0_mm": P0 if straight else None,
        "p1_mm": P1 if straight else None,
        "existing_segment_count": 1,
        "skipped_segment_count": 0,
        "locked": False,
    }


def _layout(**values: int) -> dict[str, Any]:
    return {
        "slots": dict(values),
        "state": (GridLayoutState.OK.value if values
                  else GridLayoutState.NONE.value),
    }


def _index(
    *,
    u_lines: list[dict[str, Any]] | None = None,
    v_lines: list[dict[str, Any]] | None = None,
    grid_layout: dict[str, Any] | None = None,
    schema_version: str = CURTAIN_INDEX_SCHEMA_VERSION,
    host_id: str = HOST_ID,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "curtain_available": True,
        "host_kind": "wall",
        "default_panel_type_id": "7469627",
        "default_panel_type_name": "НР_ВТ_Стеклопакет_30мм",
        "default_panel_state": "ok",
        "default_panel_source": "AUTO_PANEL_WALL",
        "auto_mullion_types": {"slots": {}, "state": "not_captured"},
        "u_grid_lines": [] if u_lines is None else u_lines,
        "v_grid_lines": [] if v_lines is None else v_lines,
        "panels": [],
        "mullions": [],
    }
    if grid_layout is not None:
        row["grid_layout"] = grid_layout
    return {
        "schema_version": schema_version,
        "curtain_index": {host_id: row},
        "failures": [],
    }


def _line_element(element_id: str, ordinal: int = 1) -> dict[str, Any]:
    """The L0 row of the grid line — as the extractor returns it after the
    fix.

    The category is taken from the LIVE MODEL CENSUS v14:
    ``OST_CurtainGridsWall``, 122 elements — exactly as many as lines in
    the curtain index of the same run. The line has neither a type nor a
    placement point, and the row honestly shows this: the node is not
    built from it, but from the side index.
    """

    return {
        "element_id": element_id,
        "category": "OST_CurtainGridsWall",
        "category_ru": "Схемы разрезки витражей",
        "type_id": "0",
        "type_name": "",
        "level_id": None,
        "level_name": None,
        # The geometry of the L0 row plays no role: the node is built from
        # the side index, not from it. The shape is taken from its curtain
        # wall neighbors in live L0 v14 (a mullion is a point with
        # coordinates).
        "geom_kind": "bbox_only",
        "p0_mm": None,
        "p1_mm": None,
        "rotation_deg": None,
        "bbox_min_mm": P0,
        "bbox_max_mm": P1,
        "host_id": HOST_ID,
        "params": {},
        "design_option": None,
        "phase_created": None,
        "workset": None,
    }


def _document(line_ids: tuple[str, ...] = (LINE_ID,)) -> L0Document:
    """The carrier and its lines — both sides in L0, as after the read
    fix."""

    wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
    wall["element_id"] = HOST_ID
    wall["type_name"] = "НР_ВТ_(250х50)_Без нарезки_Теплый"
    elements = [wall] + [
        _line_element(line_id, ordinal)
        for ordinal, line_id in enumerate(line_ids, start=1)]
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-grid-line-v1"
    row["elements"] = elements
    row["category_status"] = []
    return L0Document.from_dict(row)


def _document_without_the_line() -> L0Document:
    """The line is in the index but NOT read — the v14 pre-state."""

    wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
    wall["element_id"] = HOST_ID
    wall["type_name"] = "НР_ВТ_(250х50)_Без нарезки_Теплый"
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-grid-line-unread"
    row["elements"] = [wall]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lines(result) -> list[dict[str, Any]]:
    return [node for node in result.nodes
            if node.get("op_name") == "create_curtain_grid_line"]


class GridLineVerdict(unittest.TestCase):
    """The verdict is computed from the layout numbers, without any lift
    at all."""

    @staticmethod
    def _record(layout: GridLayout) -> CurtainWallRecord:
        return CurtainWallRecord.from_dict(HOST_ID, {
            "curtain_available": True,
            "host_kind": "wall",
            "default_panel_type_id": None,
            "default_panel_type_name": None,
            "default_panel_state": "not_captured",
            "default_panel_source": None,
            "auto_mullion_types": {"slots": {}, "state": "not_captured"},
            "grid_layout": layout.to_dict(),
            "u_grid_lines": [_line_row()],
            "v_grid_lines": [],
            "panels": [],
            "mullions": [],
        })

    def test_layout_zero_means_the_line_is_authored(self) -> None:
        record = self._record(GridLayout.from_wire(
            _layout(vert=GRID_LAYOUT_NONE, horiz=GRID_LAYOUT_NONE), "l"))
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.MANUAL)

    def test_a_dividing_type_makes_the_line_its_own(self) -> None:
        record = self._record(GridLayout.from_wire(_layout(vert=2), "l"))
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.TYPE_DRIVEN)

    def test_a_type_without_layout_parameters_divides_nothing(self) -> None:
        """``none`` is a read fact: the type has no layout parameters."""

        record = self._record(GridLayout.from_wire(_layout(), "l"))
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.MANUAL)

    def test_unreadable_layout_is_not_a_guess(self) -> None:
        record = self._record(GridLayout.from_wire(
            {"slots": {}, "state": GridLayoutState.UNREADABLE.value}, "l"))
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.UNREADABLE)

    def test_schema_before_five_says_not_captured(self) -> None:
        record = self._record(GridLayout.not_captured())
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.NOT_CAPTURED)


class GridLineLift(unittest.TestCase):
    def test_v4_row_yields_no_operation_and_says_why(self) -> None:
        """PRE-STATE: 122 lines in v13 — and not a single operation."""

        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                u_lines=[_line_row()],
                schema_version=CURTAIN_INDEX_SCHEMA_VERSION_MULLION))
        self.assertEqual(_lines(result), [])
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(len(skipped), 1)
        self.assertIn("раскладки типа не читала", skipped[0].detail)

    def test_authored_line_becomes_an_operation_on_the_host(self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE,
                                    horiz=GRID_LAYOUT_NONE)))
        lines = _lines(result)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["params"]["direction"], "u")
        self.assertEqual(line["params"]["position_mm"], MID)
        self.assertEqual(line["source_element_id"], LINE_ID)
        host = [n for n in result.nodes
                if n["source_element_id"] == HOST_ID][0]
        self.assertEqual(line["params"]["host"], {"ref": host["_id"]})

    def test_direction_comes_from_the_axis_the_index_put_it_on(self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                v_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        self.assertEqual(_lines(result)[0]["params"]["direction"], "v")

    def test_a_dividing_type_emits_nothing_and_names_the_reason(self) -> None:
        """A doubled line is worse than a missing one — the op is not
        emitted."""

        result = lift_document_detailed(
            _document(),
            curtain_index=_index(u_lines=[_line_row()],
                                 grid_layout=_layout(vert=2)))
        self.assertEqual(_lines(result), [])
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0].reason, AtomReason.GENERATOR_CHILD)
        self.assertIn("делит сетку сам", skipped[0].detail)

    def test_a_curve_that_is_not_a_line_refuses_instead_of_guessing(
            self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                u_lines=[_line_row(curve_state="curved_unsupported")],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        self.assertEqual(_lines(result), [])
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(
            skipped[0].reason, AtomReason.CURVE_KIND_UNSUPPORTED)

    def test_two_lines_make_two_operations_and_no_duplicates(self) -> None:
        """A multiset: as many operations as there are lines in the
        index."""

        result = lift_document_detailed(
            _document(("8145929", "8145930", "8145931")),
            curtain_index=_index(
                u_lines=[_line_row("8145929"), _line_row("8145930")],
                v_lines=[_line_row("8145931")],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        lines = _lines(result)
        self.assertEqual(len(lines), 3)
        sources = [node["source_element_id"] for node in result.nodes]
        self.assertEqual(len(sources), len(set(sources)))
        node_ids = [node["_id"] for node in result.nodes]
        self.assertEqual(len(node_ids), len(set(node_ids)))

    def test_a_line_that_L0_did_deliver_is_not_synthesised_twice(
            self) -> None:
        """Re-extraction may return the line as an element — the node is
        still only one.

        If synthesis did not look at L0, the same id would arrive twice,
        and reassembly would build the line twice.
        """

        document = _document()
        wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
        wall["element_id"] = HOST_ID
        wall["type_name"] = "НР_ВТ_(250х50)_Без нарезки_Теплый"
        line = make_element("OST_GenericModel", int(LINE_ID), ordinal=1)
        line["element_id"] = LINE_ID
        line["host_id"] = HOST_ID
        # Which exact category re-extraction will return the line as is
        # known only to live Revit; the test holds exactly what depends on
        # that: the id is ALREADY IN L0 — so synthesis must stay silent,
        # otherwise the line would be built twice.
        row = copy.deepcopy(project1_metadata())
        row["change_stamp"] = "curtain-grid-line-relift"
        row["elements"] = [wall, line]
        row["category_status"] = []
        document = L0Document.from_dict(row)
        result = lift_document_detailed(
            document,
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        sources = [node["source_element_id"] for node in result.nodes]
        self.assertEqual(sources.count(LINE_ID), 1)
        self.assertEqual(len(sources), len(set(sources)))

    def test_a_line_absent_from_L0_makes_no_node_and_says_why(self) -> None:
        """PRE-STATE: the live v14 run stopped right here.

        The wave's first revision synthesized the line node from the side
        index without looking at L0, and the fold rejected it under the
        census law:
        ``FoldError('L0/L1 source mismatch: missing=0, invented=122')``
        (``sob62_fas_r23_v14/run.json``; extraction went through in full —
        5096 elements, the census matched). The law is right: a node with
        no source in L0 is an invented element. Now there is no operation,
        and the reason is named.
        """

        result = lift_document_detailed(
            _document_without_the_line(),
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        self.assertEqual(_lines(result), [])
        sources = {node["source_element_id"] for node in result.nodes}
        self.assertNotIn(LINE_ID, sources)
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(len(skipped), 1)
        self.assertIn("нет среди прочитанных элементов", skipped[0].detail)

    def test_the_fold_law_itself_rejects_an_invented_source(self) -> None:
        """The very law that saved the run is under test here.

        It must not be weakened: it is the only thing that tells apart "we
        read it and lifted it" from "we invented an element the reader
        never saw."
        """

        from kir.decompile.fold import FoldError, fold_l1

        document = _document_without_the_line()
        nodes = list(lift_document_detailed(
            document,
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE))).nodes)
        host = [n for n in nodes if n["source_element_id"] == HOST_ID][0]
        invented = {
            "kind": "op",
            "op_name": "create_curtain_grid_line",
            "_id": stable_l1_id("op", LINE_ID),
            "type_name": "",
            "params": {"host": {"ref": host["_id"]}, "direction": "u",
                       "position_mm": MID},
            "source_element_id": LINE_ID,
            "level_name": host.get("level_name"),
            "anchor_mm": MID,
        }
        with self.assertRaises(FoldError) as caught:
            fold_l1(nodes + [invented], document)
        self.assertIn("invented=1", str(caught.exception))

    def test_the_position_travels_with_the_delta_copy(self) -> None:
        """PRE-STATE: live run #9 (v15) died right here.

        ``position_mm`` was not listed in the shared coordinate table
        (``fold._COORDINATE_FIELDS``), and the Δ-shift moved the WALL but
        not the point of its grid line. Measured from the run's artifacts:
        the wall in the program moved to ``p0_mm=[637652.0, 15682.0]``,
        while the line's position stayed at ``[7717.8, 28822.4, 4925.0]``
        — the ORIGINAL's coordinates. The commit rolled back with the
        Revit error "Не удалось создать импост витража. Та часть схемы
        разрезки витража, на которой он был размещён, больше не
        существует."

        The same lesson was learned on 21.07 with "xyz" in place_family:
        furniture was built at the original coordinates INSIDE the
        building. One field in the shared table fixes both consumers — the
        transfer and the canon.
        """

        from kir.decompile.materialize import leaves_to_program

        leaves = [n for n in lift_document_detailed(
            _document(), curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE))).nodes
            if n.get("kind") == "op"]
        delta = (300000.0, 0.0, 0.0)
        programs = leaves_to_program(leaves, offset_mm=delta).programs
        lines = [op for prog in programs for op in prog["ops"]
                 if op["op"] == "create_curtain_grid_line"]
        self.assertEqual(len(lines), 1)
        moved = lines[0]["position_mm"]
        self.assertAlmostEqual(moved[0], MID[0] + delta[0], delta=1.0)
        self.assertAlmostEqual(moved[1], MID[1], delta=1.0)
        self.assertAlmostEqual(moved[2], MID[2], delta=1.0)
        walls = [op for prog in programs for op in prog["ops"]
                 if op["op"] == "create_wall"]
        self.assertTrue(walls, "носитель обязан быть в программе")
        # The line and its wall must move by THE SAME AMOUNT: they must
        # not drift apart under any shift.
        plain = leaves_to_program(leaves).programs
        plain_wall = [op for prog in plain for op in prog["ops"]
                      if op["op"] == "create_wall"][0]
        self.assertAlmostEqual(
            moved[0] - MID[0],
            walls[0]["p0_mm"][0] - plain_wall["p0_mm"][0], delta=1.0)

    def test_the_canon_is_translation_invariant_for_the_line(self) -> None:
        """Otherwise the line's sheet would NEVER match the original.

        The idempotence comparison checks the canonical hashes of the
        original against the reassembled copy, and the copy sits shifted.
        A field that is not in the coordinate table is not localized by
        the canon — and the hashes diverge even when the line is built
        perfectly.
        """

        from kir.decompile.component import _translate_leaf
        from kir.decompile.fold import FidelityCanon

        nodes = list(lift_document_detailed(
            _document(), curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE))).nodes)
        delta = (300000.0, 0.0, 0.0)
        # The copy is built SHIFTED AS A WHOLE — and the line in it sits
        # at position+delta. We move the sheet by hand, not through the
        # shared table: otherwise the test would be comparing the table
        # against itself and would not catch the exact gap that brought
        # down run #9.
        moved = []
        for node in nodes:
            shifted = _translate_leaf(node, delta)
            if shifted.get("op_name") == "create_curtain_grid_line":
                params = dict(shifted["params"])
                params["position_mm"] = [
                    node["params"]["position_mm"][i] + delta[i]
                    for i in range(3)]
                shifted = {**shifted, "params": params}
            moved.append(shifted)
        origin = (0.0, 0.0, 0.0)
        here = FidelityCanon.hash_sequence(nodes, origin)
        there = FidelityCanon.hash_sequence(moved, delta)
        index_of_line = [i for i, node in enumerate(nodes)
                         if node.get("op_name") == "create_curtain_grid_line"]
        self.assertEqual(len(index_of_line), 1)
        i = index_of_line[0]
        self.assertEqual(here[i], there[i])

    def test_a_host_that_did_not_lift_refuses_instead_of_dangling(
            self) -> None:
        """A reference to a carrier that was not lifted would be a
        dangling L1 reference."""

        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE),
                host_id="404404"))
        self.assertEqual(_lines(result), [])
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(skipped[0].reason, AtomReason.MISSING_REFERENCE)


if __name__ == "__main__":
    unittest.main()
