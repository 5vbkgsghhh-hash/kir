"""Contour ceiling by the reverse path (09.08.2026).

FACT BEFORE THIS FIX. On the morning of 09.08, ``create_ceiling`` gained a
SECOND input shape — ``contour`` of kind ``region`` (ops_arch.py), i.e. the
whole CONTOUR sketch language: arcs, up to eight openings, rect/l/poly. The
forward direction grew, the reverse stayed in place: ``_lift_ceiling``
called only the polygonal path, and a ceiling with a rounded edge still
became an ``unsupported_geometry`` atom — "the op cannot handle this
shape," which stopped being true that same morning.

WHY THIS IS A LIFTER FIX, NOT A CAPTURE GAP (the three states this wave
decides between). The data for the contour is ALREADY PRESENT in the
sketches' side index: the ``OST_Ceilings`` category has stood in
``_STAGE_CATEGORIES`` for the ``sketch`` stage since 29.07, and the profile
row carries, for every loop, both the segment kind (``curve_kinds``) and
the arc midpoint (``arc_midpoints``) — exactly the three numbers from which
the floor already assembles ``bulge``. So what was missing was not a field
in capture or an op in the registry, but a branch in the lifter. Exactly
the one case out of three where writing a lifter IS allowed.

WHAT IS PROVEN HERE, AND WHAT IS NOT. It is proven that the loop CLOSES:
the node the lift produces is accepted by the compiler on 2022-2026 and
rejected with the typed KIR-E003 on 2021 (there the ceiling has NO creation
path AT ALL — measured by compilation, see ops_arch.py). It is NOT proven
that the ceiling reassembles in live Revit: capture still does not carry
ceiling slope (it is absent from L0 in any form), and this lift will
return a sloped ceiling as flat. That boundary is named in the lifter
itself and in the manifest (``create_ceiling`` is ``BOUNDED``, not
``FORM_EXACT``), and the contour does not move it one step: it is about
the PLAN, while slope is about the third coordinate.
"""
from __future__ import annotations

import copy
import math
import unittest
from typing import Any

from kir.compiler import compile_program
from kir.contour import bulge_midpoint
from kir.decompile.l1_schema import AtomReason, validate_l1_node
from kir.decompile.lift import lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)
from kir.tests.fixtures import GROUND_SNAPSHOT

#: Names FROM THE GATE SNAPSHOT: the loop is checked through to the end
#: only when grounding finds both the level and the type. Otherwise the
#: test would be proving the shape of the region, not that the program
#: compiles.
SNAPSHOT_LEVEL = "Этаж 1"
SNAPSHOT_CEILING_TYPE = "Потолок подвесной 600x600"

SQUARE = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]

#: A rounded edge: the third side of the square is an arc with a captured
#: midpoint.
ARC_MIDPOINT = [3000.0, 4600.0]


def _profile(
    outline: list[list[float]],
    *,
    curve_kinds: list[list[str]] | None = None,
    arc_midpoints: list[list[list[float] | None]] | None = None,
    holes: list[list[list[float]]] | None = None,
) -> dict[str, Any]:
    contours = [outline] + list(holes or [])
    return {
        "profile_available": True,
        "exterior_loop": copy.deepcopy(outline),
        "holes": copy.deepcopy(holes or []),
        "curve_kinds": copy.deepcopy(curve_kinds) if curve_kinds else [
            ["line"] * len(contour) for contour in contours],
        "arc_midpoints": copy.deepcopy(arc_midpoints) if arc_midpoints else [
            [None] * len(contour) for contour in contours],
    }


ARC_PROFILE = _profile(
    SQUARE,
    curve_kinds=[["line", "line", "arc", "line"]],
    arc_midpoints=[[None, None, ARC_MIDPOINT, None]])


def _document(*, offset: float | None = None,
              floor_offset: float | None = None) -> L0Document:
    ceiling = make_element("OST_Ceilings", 8801, ordinal=0)
    ceiling["element_id"] = "8801"
    ceiling["geom_kind"] = "bbox_only"
    ceiling["p0_mm"] = None
    ceiling["p1_mm"] = None
    ceiling["rotation_deg"] = None
    ceiling["type_id"] = "1200"
    ceiling["type_name"] = SNAPSHOT_CEILING_TYPE
    ceiling["params"] = dict(ceiling.get("params") or {})
    if offset is not None:
        ceiling["params"]["CEILING_HEIGHTABOVELEVEL_PARAM"] = offset
    if floor_offset is not None:
        ceiling["params"]["FLOOR_HEIGHTABOVELEVEL_PARAM"] = floor_offset
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "ceiling-contour-v1"
    row["elements"] = [ceiling]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lift(profile: dict[str, Any], **kwargs):
    result = lift_document_detailed(
        _document(**kwargs), {"8801": copy.deepcopy(profile)})
    return result.nodes[0], result.diagnostics


class AnArcCeilingStopsBeingAnAtom(unittest.TestCase):

    def test_it_lifts_as_create_ceiling_through_the_contour_input(self) -> None:
        node, diagnostics = _lift(ARC_PROFILE)
        self.assertEqual(diagnostics, ())
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_ceiling")
        self.assertIn("contour", node["params"])
        self.assertEqual(validate_l1_node(node), node)

    def test_the_flat_shape_fields_are_absent_because_both_is_a_refusal(self):
        """`outline`/`holes` next to `contour` is a typed KIR-P007.

        Emitting both would mean handing the compiler a program it is
        REQUIRED to reject, and counting it toward one's own coverage.
        """

        node, _ = _lift(ARC_PROFILE)
        self.assertNotIn("outline", node["params"])
        self.assertNotIn("holes", node["params"])

    def test_the_bulge_reproduces_the_captured_midpoint(self) -> None:
        """The arc is recorded EXACTLY: running the reverse path through
        their own function gives the same midpoint the extractor captured,
        not "approximately the same" curve."""

        node, _ = _lift(ARC_PROFILE)
        outer = node["params"]["contour"]["outer"]
        self.assertEqual(outer["shape"], "poly")
        arcs = outer["arcs"]
        self.assertEqual(len(arcs), 1)
        edge = arcs[0]["edge"]
        points = outer["points_mm"]
        back = bulge_midpoint(
            points[edge], points[(edge + 1) % len(points)], arcs[0]["bulge"])
        self.assertLess(math.dist(back, ARC_MIDPOINT), 1e-6)

    def test_the_offset_comes_from_the_ceiling_parameter_only(self) -> None:
        """The parameter name is part of the category's identity.

        The wrong name here would silently return zero, i.e. it would
        flatten the ceiling onto the level plane and call that success.
        """

        node, _ = _lift(ARC_PROFILE, offset=2700.0)
        self.assertEqual(node["params"]["height_offset_mm"], 2700.0)

        other, _ = _lift(ARC_PROFILE, floor_offset=2700.0)
        self.assertNotIn("height_offset_mm", other["params"])


class ThePolygonPathIsUnchanged(unittest.TestCase):
    """The contour takes only what is INEXPRESSIBLE otherwise. Everything
    else must not move.

    Otherwise the loop would break open on every ceiling of every already
    decompiled building, and "we broke nothing" would become unverifiable.
    """

    def test_a_polygon_ceiling_still_lifts_with_outline_and_holes(self) -> None:
        node, diagnostics = _lift(_profile(SQUARE), offset=2700.0)
        self.assertEqual(diagnostics, ())
        self.assertEqual(node["op_name"], "create_ceiling")
        self.assertEqual(node["params"]["outline"],
                         [[0.0, 0.0], [6000.0, 0.0],
                          [6000.0, 4000.0], [0.0, 4000.0]])
        self.assertEqual(node["params"]["holes"], [])
        self.assertNotIn("contour", node["params"])
        self.assertEqual(node["params"]["height_offset_mm"], 2700.0)


class WhatContourStillCannotSayStaysATypedAtom(unittest.TestCase):

    def test_an_arc_without_a_captured_midpoint_stays_an_atom(self) -> None:
        """Without the midpoint the arc is unrecoverable, and a chord is
        not an approximation.

        The reason here is `missing_geometry`, not "the contour cannot
        express it": strict parsing of the side index does not accept a
        row with an arc lacking a midpoint AT ALL, meaning the element has
        no profile. The floor answers with exactly the same code and for
        the same reason (`test_lift_floor_contour`), and this is not a
        coincidence — row parsing is shared by both categories.
        """

        node, diagnostics = _lift(_profile(
            SQUARE,
            curve_kinds=[["line", "line", "arc", "line"]],
            arc_midpoints=[[None, None, None, None]]))
        self.assertEqual(node["kind"], "atom")
        self.assertIs(diagnostics[0].reason, AtomReason.MISSING_GEOMETRY)
        self.assertIn(
            "arc segment 2 requires an exact midpoint",
            node["reason"]["detail"])

    def test_more_than_eight_openings_are_refused_by_name(self) -> None:
        holes = [[[200.0 + i * 500, 200.0], [500.0 + i * 500, 200.0],
                  [500.0 + i * 500, 500.0], [200.0 + i * 500, 500.0]]
                 for i in range(9)]
        node, diagnostics = _lift(_profile(
            SQUARE,
            curve_kinds=[["line", "line", "arc", "line"]]
                        + [["line"] * 4] * 9,
            arc_midpoints=[[None, None, ARC_MIDPOINT, None]]
                          + [[None] * 4] * 9,
            holes=holes))
        self.assertEqual(node["kind"], "atom")
        self.assertIs(diagnostics[0].reason, AtomReason.UNSUPPORTED_SIGNATURE)
        self.assertIn("до 8 проёмов", node["reason"]["detail"])


class TheCircleActuallyCloses(unittest.TestCase):
    """A lift whose node the compiler does not accept is not coverage but a
    report about coverage.

    The region is assembled BY THE LIFT and handed to the compiler
    verbatim; substituting it here with a hand-written sketch would mean
    testing one's own guess about what the lift emits.
    """

    def _program(self, revit_version: str):
        node, _ = _lift(ARC_PROFILE, offset=2700.0)
        return compile_program(
            {"ir_version": "1.0", "intent": "потолок по эскизу", "ops": [{
                "op": "create_ceiling", "id": "CE1",
                "contour": node["params"]["contour"],
                "level": {"by": "name", "value": SNAPSHOT_LEVEL},
                "type": {"by": "name", "value": SNAPSHOT_CEILING_TYPE},
                "height_offset_mm": node["params"]["height_offset_mm"],
            }]},
            revit_version=revit_version, snapshot=GROUND_SNAPSHOT, bulk=True)

    def test_the_lifted_contour_compiles_on_every_version_that_has_ceilings(
            self) -> None:
        for version in ("2022", "2023", "2024", "2025", "2026"):
            with self.subTest(revit_version=version):
                out = self._program(version)
                self.assertTrue(
                    out.ok, [d.code for d in out.diagnostics])
                self.assertIn("Ceiling.Create", out.csharp)

    def test_2021_refuses_the_whole_operation_by_name(self) -> None:
        """On 2021 the ceiling has NOT A SINGLE creation path — neither the
        new one nor the legacy one. The refusal must be typed and occur
        before the shape is even parsed."""

        out = self._program("2021")
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics], ["KIR-E003"])


if __name__ == "__main__":
    unittest.main()
