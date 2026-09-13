# -*- coding: utf-8 -*-
"""Opening: the boundary is read, and the lift is PARTIAL — exactly as
far as there is a witness (04.09.2026).

The `create_opening` gap was declared on 09.08 with a deadline of 08.09
and closed four days before it. It is NOT closed entirely, and that is
not an unfinished job but a property of the API, which is pinned down
here by a number.

WHAT CLOSED. The capture reads `Opening.IsRectBoundary` and, based on it,
either `Opening.BoundaryRect` or `Opening.BoundaryCurves` (all three
exist on ALL six versions, zero documented traps — measured against the
trap index, not from memory). The host has been read since 09.08. So
`variety="wall_rect"` now has BOTH its inputs and lifts.

WHAT WILL NEVER CLOSE, AND WHY THIS IS A MEASUREMENT, NOT AN OPINION. The
`Autodesk.Revit.DB.Opening` type has EXACTLY SEVEN members across all six
versions:

    BoundaryCurves · BoundaryRect · Host · IsRectBoundary ·
    IsTransparentIn3D · IsTransparentInElevation · SketchId (2022+)

The cut direction is not among them. For `variety="host_face"` the `cut`
input is declared WITHOUT A DEFAULT deliberately: a vertical cut and a
perpendicular cut coincide only on a flat carrier, and on a slope they
produce DIFFERENT openings. So host_face remains an atom not because we
failed to finish reading something, but because there is nothing to read
— and no future READING wave will change that.

The shape is precedented: for a railing, `variety=path` inverts, while
the hosted variant remains an atom, "because RailingPlacementPosition has
no getter on any shipped version." The same holds here, only the witness
for the cut is absent.
"""
from __future__ import annotations

import unittest

from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import (
    _unsourceable_inputs_detail,
    lift_document_detailed,
)
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    LocationCurveKind,
    ProjectInfo,
)
from kir.reverse_contract import (
    REVERSE_CONTRACTS,
    ReverseGuarantee,
    ReverseMode,
)

#: A rectangular opening: TWO opposite corners, as BoundaryRect returns
#: them.
CORNERS = ((1000.0, 0.0, 900.0), (2000.0, 0.0, 3000.0))
#: The profile of an opening in a floor slab: a closed polyline.
PROFILE = ((0.0, 0.0, 0.0), (1000.0, 0.0, 0.0), (1000.0, 1000.0, 0.0))


def _wall(element_id="55"):
    return L0Element(
        element_id=element_id, category="OST_Walls", category_ru="",
        type_id="9", type_name="Стена 200",
        level_id="10", level_name="Этаж 1",
        geom_kind=GeometryKind.CURVE,
        p0_mm=(0.0, 0.0, 0.0), p1_mm=(6000.0, 0.0, 0.0),
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=None, params={"WALL_USER_HEIGHT_PARAM": 3000.0},
        curve_kind=LocationCurveKind.LINE)


def _host(element_id, category):
    """A carrier that does NOT itself get lifted: it is here only as a
    category."""

    return L0Element(
        element_id=element_id, category=category, category_ru="",
        type_id="9", type_name="Тип", level_id="10", level_name="Этаж 1",
        geom_kind=GeometryKind.POINT, p0_mm=(0.0, 0.0, 0.0), p1_mm=None,
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=None, params={})


def _opening(category="OST_SWallRectOpening", *, host_id="55",
             is_rect=None, boundary=None):
    return L0Element(
        element_id="70", category=category, category_ru="",
        type_id="7", type_name="Проём", level_id="10", level_name="Этаж 1",
        geom_kind=GeometryKind.POINT, p0_mm=(1500.0, 0.0, 1950.0), p1_mm=None,
        rotation_deg=None,
        bbox_min_mm=(1000.0, 0.0, 900.0), bbox_max_mm=(2000.0, 200.0, 3000.0),
        host_id=host_id, params={},
        opening_is_rect=is_rect, opening_boundary_mm=boundary)


def _lift(*elements):
    document = L0Document(
        doc_name="openings", revit_version="2023", units="mm",
        change_stamp="t", levels=(LevelInfo("10", "Этаж 1", 0.0),),
        grids=(), rooms=(), project_info=ProjectInfo(), elements=elements)
    result = lift_document_detailed(document)
    return ({node["source_element_id"]: node for node in result.nodes},
            {item.source_element_id: item for item in result.diagnostics})


class AWallOpeningNowLiftsFromItsBoundary(unittest.TestCase):
    """The very thing this wave was made for."""

    def test_both_corners_and_the_host_reference_reach_the_op(self):
        nodes, diagnostics = _lift(_wall(), _opening(
            is_rect=True, boundary=CORNERS))
        self.assertEqual(diagnostics, {})
        node = nodes["70"]
        self.assertEqual(node["op_name"], "create_opening")
        self.assertEqual(node["params"]["variety"], "wall_rect")
        self.assertEqual(node["params"]["p0_mm"], list(CORNERS[0]))
        self.assertEqual(node["params"]["p1_mm"], list(CORNERS[1]))
        # The reference to the carrier is to a NODE, not to element_id:
        # otherwise the program would depend on another document's
        # addresses.
        self.assertEqual(
            node["params"]["host"], {"ref": nodes["55"]["_id"]})

    def test_the_opening_waits_for_its_host_whatever_the_row_order(self):
        """The opening is deferred to the second pass, and row order
        decides nothing.

        Before 04.09, order would have decided this: an opening met
        before its wall would not have found the carrier's node. That is
        a refusal BY ORDER, not by the model — exactly the defect the
        second pass was set up for doors to fix.
        """

        forward = _lift(_wall(), _opening(is_rect=True, boundary=CORNERS))[0]
        backward = _lift(_opening(is_rect=True, boundary=CORNERS), _wall())[0]
        self.assertEqual(forward["70"]["op_name"], "create_opening")
        self.assertEqual(backward["70"]["op_name"], "create_opening")


class TheThreeRefusalsAreNamedApart(unittest.TestCase):
    """Three different kinds of "no," and mixing them up would mean
    pointing in the wrong direction."""

    def test_an_old_snapshot_refuses_with_the_very_same_words(self):
        """READING. A snapshot from before 04.09 does not carry the key —
        the text must stay as it was."""

        nodes, diagnostics = _lift(_wall(), _opening())
        node = nodes["70"]
        self.assertEqual(node["kind"], "atom")
        self.assertIs(
            diagnostics["70"].reason, AtomReason.SOURCE_CONTRACT_GAP,
            "причина адресует ЧТЕНИЕ: слепок старый, читать было нечего")
        self.assertEqual(
            node["reason"]["detail"],
            _unsourceable_inputs_detail("create_opening"),
            "текст обязан собираться тем же прибором из реестра, а не быть "
            "переписанным от руки: иначе история покрытия перестанет быть "
            "историей")

    def test_a_host_face_opening_refuses_because_the_cut_has_no_getter(self):
        """WITNESS. Not "we didn't finish reading," but "there is nothing
        to read."""

        nodes, diagnostics = _lift(
            _host("60", "OST_Floors"),
            _opening("OST_FloorOpening", host_id="60",
                     is_rect=False, boundary=PROFILE))
        node = nodes["70"]
        self.assertEqual(node["kind"], "atom")
        self.assertIs(
            diagnostics["70"].reason, AtomReason.MISSING_METADATA,
            "source_contract_gap послал бы следующего ЧИТАТЬ, а читать нечего")
        detail = node["reason"]["detail"]
        self.assertIn("семь", detail)
        self.assertIn("perpendicular", detail)

    def test_an_arc_boundary_refuses_instead_of_becoming_a_chord(self):
        """SHAPE. An arc passed off as a polyline is a different opening,
        not an approximation.

        The state is coded by a pair: `is_rect` is read, the boundary is
        absent. Capture does not write the key when the contour is not a
        polyline, and the lifter tells this apart from "not measured"
        precisely by the presence of the first key.
        """

        nodes, diagnostics = _lift(_wall(), _opening(is_rect=False))
        node = nodes["70"]
        self.assertEqual(node["kind"], "atom")
        self.assertIs(
            diagnostics["70"].reason, AtomReason.UNSUPPORTED_GEOMETRY)

    def test_an_opening_without_a_host_is_the_shaft_the_registry_refused(self):
        nodes, diagnostics = _lift(_opening(
            "OST_FloorOpening", host_id=None, is_rect=True, boundary=CORNERS))
        self.assertIs(
            diagnostics["70"].reason, AtomReason.MISSING_REFERENCE)
        self.assertIn("шахта", nodes["70"]["reason"]["detail"])


class TheCaptureAndTheDeclarationMovedTogether(unittest.TestCase):

    def test_the_capture_reads_all_three_members(self):
        from kir.decompile.extract import build_category_batch_cs

        cs = build_category_batch_cs("OST_FloorOpening")
        for member in ("IsRectBoundary", "BoundaryRect", "BoundaryCurves"):
            with self.subTest(member=member):
                self.assertIn(member, cs)
        # A reading refusal comes as a receipt, not as an empty `catch { }`.
        self.assertIn("opening_boundary_read_failed", cs)

    def test_the_manifest_names_every_boundary_of_the_fix(self):
        contract = REVERSE_CONTRACTS["create_opening"]
        self.assertIs(contract.mode, ReverseMode.DIRECT)
        self.assertIs(contract.guarantee, ReverseGuarantee.BOUNDED)
        for word in ("wall_rect", "host_face", "getter", "arc", "2026-09-04"):
            with self.subTest(word=word):
                self.assertIn(
                    word, contract.limitation,
                    "манифест читают ВМЕСТО кода: граница, названная только "
                    "в коде, для читателя манифеста не существует")
        # The deadline is lifted together with the gap.
        self.assertFalse(contract.due)


if __name__ == "__main__":
    unittest.main()
