"""Contour floor by the reverse path: the arc and the circle stop being
an atom.

FACT BEFORE THIS WAVE: the op ``create_floor_by_contour`` is written,
passes the gate on six versions — and is NEVER mentioned in
``kir/decompile``. Any floor whose profile carries an arc or consists of
two segments (a circle) remained an ``unsupported_geometry`` atom and was
sent to escrow.

MEASUREMENT OF 28.07 across two decompiles (by instrument, not by
estimate):

    demo-v3    235 profiles: 80 as polygons (create_floor), 155 as atoms —
               of which 126 are "2 points, two arcs" loops (circles)
    facade v11 50 profiles: 34 as polygons, 1 atom with arcs

The data for the contour already lay in the sketches' side index: for the
arc, the start, MIDPOINT, and end are captured (``arc_midpoints_mm``), and
the ``poly`` shape of the contour op accepts exactly a ``bulge`` per edge.
The recalculation is exact: the formula is the inverse of
``contour.bulge_midpoint``, verified on 3051 arcs across both buildings,
worst residual 2.4e-8 mm.

The profile rows below are copied VERBATIM from
``демо-v3/sketch.index.json``.
"""
from __future__ import annotations

import copy
import json
import math
import pathlib
import unittest
from typing import Any

from kir.contour import bulge_midpoint
from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)

#: Floor 22845777 «Подшивка бронза_10»: three points, the last edge is an
#: arc.
LIVE_ARC_FLOOR = "22845777"
LIVE_ARC_PROFILE: dict[str, Any] = {
    "profile_available": True,
    "exterior_loop": [
        [13012.509125587052, 58949.99999999602],
        [21286.985853653074, 58949.999999996],
        [14544.715866819928, 55088.17174163566],
    ],
    "curve_kinds": [["line", "line", "arc"]],
    "arc_midpoints": [[None, None, [13562.58193948993, 56933.37427175852]]],
    "holes": [],
}
LIVE_ARC_OFFSET = -700.0

#: Floor 19326960: a CIRCLE — a loop of two arcs, inexpressible as a
#: polygon.
LIVE_CIRCLE_FLOOR = "19326960"
LIVE_CIRCLE_PROFILE: dict[str, Any] = {
    "profile_available": True,
    "exterior_loop": [
        [24225.512737285004, 33500.03657079406],
        [59574.487262722156, 33500.03657079395],
    ],
    "curve_kinds": [["arc", "arc"]],
    "arc_midpoints": [[
        [41900.00000000352, 16750.036570793418],
        [41900.00000000365, 52150.036570793425],
    ]],
    "holes": [],
}

_ARTIFACT = (
    pathlib.Path(__file__).resolve().parents[4]
    / "backend" / "data" / "decompile" / "демо-v3" / "sketch.index.json")


def _document(element_id: str, *, offset: float | None = None) -> L0Document:
    floor = make_element("OST_Floors", 4001, ordinal=0)
    floor["element_id"] = element_id
    floor["type_id"] = "22845888"
    floor["type_name"] = "Подшивка бронза_10"
    floor["params"] = dict(floor.get("params") or {})
    if offset is not None:
        floor["params"]["FLOOR_HEIGHTABOVELEVEL_PARAM"] = offset
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "contour-v1"
    row["elements"] = [floor]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lift(element_id: str, profile: dict[str, Any],
          *, offset: float | None = None):
    result = lift_document_detailed(
        _document(element_id, offset=offset),
        {element_id: copy.deepcopy(profile)})
    return {node["source_element_id"]: node for node in result.nodes}[
        element_id]


class AnArcProfileBecomesAContourOp(unittest.TestCase):
    def test_the_arc_floor_lifts_instead_of_atomising(self) -> None:
        node = _lift(LIVE_ARC_FLOOR, LIVE_ARC_PROFILE, offset=LIVE_ARC_OFFSET)
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_floor_by_contour")

    def test_the_bulge_reproduces_the_captured_midpoint(self) -> None:
        """The arc is recorded EXACTLY: running the reverse path through
        their own function returns the same midpoint the extractor
        captured."""

        node = _lift(LIVE_ARC_FLOOR, LIVE_ARC_PROFILE, offset=LIVE_ARC_OFFSET)
        outer = node["params"]["contour"]["outer"]
        self.assertEqual(outer["shape"], "poly")
        self.assertEqual(len(outer["points_mm"]), 3)
        arcs = outer["arcs"]
        self.assertEqual(len(arcs), 1)
        edge = arcs[0]["edge"]
        points = outer["points_mm"]
        start = points[edge]
        end = points[(edge + 1) % len(points)]
        back = bulge_midpoint(start, end, arcs[0]["bulge"])
        expected = LIVE_ARC_PROFILE["arc_midpoints"][0][2]
        self.assertLess(math.dist(back, expected), 1e-6)

    def test_the_height_offset_travels_with_the_contour(self) -> None:
        """The offset from the level is the same degree of freedom as in
        create_floor.

        In «демо-v3» 107 of 155 contour floors have a non-zero offset;
        without it, reassembly would place them on the level plane.
        """

        node = _lift(LIVE_ARC_FLOOR, LIVE_ARC_PROFILE, offset=LIVE_ARC_OFFSET)
        self.assertEqual(node["params"]["height_offset_mm"], LIVE_ARC_OFFSET)

    def test_a_polygon_profile_still_lifts_as_create_floor(self) -> None:
        """The old path stays byte for byte: the contour takes only what
        is inexpressible."""

        square = {
            "profile_available": True,
            "exterior_loop": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
            "curve_kinds": [["line", "line", "line", "line"]],
            "arc_midpoints": [[None, None, None, None]],
            "holes": [],
        }
        node = _lift("4001", square)
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_floor")


class ACircleIsSplitIntoExpressibleArcs(unittest.TestCase):
    """A loop of two segments is not "too few vertices," it is a
    circle."""

    def test_the_circle_lifts(self) -> None:
        node = _lift(LIVE_CIRCLE_FLOOR, LIVE_CIRCLE_PROFILE)
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_floor_by_contour")

    def test_each_arc_is_halved_at_its_own_captured_midpoint(self) -> None:
        """Cutting IN HALF is not an approximation: the same curve, two
        arcs.

        The ``poly`` shape requires at least three points, a circle has
        two. The half is taken from the ALREADY CAPTURED arc midpoint, so
        not a single new number is invented.
        """

        node = _lift(LIVE_CIRCLE_FLOOR, LIVE_CIRCLE_PROFILE)
        outer = node["params"]["contour"]["outer"]
        self.assertEqual(len(outer["points_mm"]), 4)
        self.assertEqual(len(outer["arcs"]), 4)
        captured = LIVE_CIRCLE_PROFILE["arc_midpoints"][0]
        for point in captured:
            with self.subTest(point=point):
                self.assertTrue(
                    any(math.dist(point, p) < 1e-6
                        for p in outer["points_mm"]),
                    "середина дуги обязана стать точкой формы")

    def test_each_half_stays_on_its_own_arc_circle(self) -> None:
        """The halves lie on the SAME circle as the original arc.

        Measurement showed that these two arcs have different radii
        (16750 and 18650 mm from the common chord), meaning the figure is
        not a circle but a lens. So the check runs PER ARC: the center is
        recovered from the circumscribed circle through the captured
        start-midpoint-end, and all three reference points of the halves
        must lie on it.
        """

        def circumcentre(a, b, c):
            ax, ay = a; bx, by = b; cx, cy = c
            d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
            ux = ((ax ** 2 + ay ** 2) * (by - cy)
                  + (bx ** 2 + by ** 2) * (cy - ay)
                  + (cx ** 2 + cy ** 2) * (ay - by)) / d
            uy = ((ax ** 2 + ay ** 2) * (cx - bx)
                  + (bx ** 2 + by ** 2) * (ax - cx)
                  + (cx ** 2 + cy ** 2) * (bx - ax)) / d
            return (ux, uy)

        node = _lift(LIVE_CIRCLE_FLOOR, LIVE_CIRCLE_PROFILE)
        outer = node["params"]["contour"]["outer"]
        points = outer["points_mm"]
        source = LIVE_CIRCLE_PROFILE["exterior_loop"]
        captured = LIVE_CIRCLE_PROFILE["arc_midpoints"][0]
        for index, mid in enumerate(captured):
            start = source[index]
            end = source[(index + 1) % len(source)]
            centre = circumcentre(start, mid, end)
            radius = math.dist(centre, start)
            halves = [arc for arc in outer["arcs"]
                      if math.dist(points[arc["edge"]], start) < 1e-6
                      or math.dist(points[arc["edge"]], mid) < 1e-6]
            self.assertEqual(len(halves), 2, "дуга обязана стать двумя")
            for arc in halves:
                probe = bulge_midpoint(
                    points[arc["edge"]],
                    points[(arc["edge"] + 1) % len(points)], arc["bulge"])
                with self.subTest(arc=index, probe=probe):
                    self.assertLess(
                        abs(math.dist(centre, probe) - radius), 0.01,
                        "половина сошла с окружности исходной дуги")


class WhatContourStillCannotSayStaysATypedAtom(unittest.TestCase):
    def test_a_loop_beyond_sixty_four_points_is_refused_by_name(self) -> None:
        """A live case, 19326972: an opening loop of 92 points. This is a
        boundary OF THE OP, and it is named, not sidestepped by a silent
        simplification."""

        profile = {
            "profile_available": True,
            "exterior_loop": [[0, 0], [10000, 0], [10000, 8000], [0, 8000]],
            "curve_kinds": [["line"] * 4],
            "arc_midpoints": [[None] * 4],
            "holes": [[[100 + index, 100] for index in range(92)]],
        }
        profile["curve_kinds"].append(["line"] * 92)
        profile["arc_midpoints"].append([None] * 92)
        profile["curve_kinds"][1][0] = "arc"
        profile["arc_midpoints"][1][0] = [100.5, 120.0]
        node = _lift("4001", profile)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.UNSUPPORTED_GEOMETRY.value)
        # The subject of the check is "the refusal NAMES the boundary,"
        # not "the boundary equals 64." The number is taken from the
        # authority: on 02.09.2026 the ring was raised 64 -> 256, and this
        # line turned red even though the parsing was correct.
        from kir.geom import MAX_RING_POINTS, MIN_RING_POINTS
        self.assertIn(f"{MIN_RING_POINTS}..{MAX_RING_POINTS}",
                      node["reason"]["detail"])

    def test_an_arc_without_a_captured_midpoint_stays_an_atom(self) -> None:
        """An arc without a midpoint is an arc we do not know; a chord in
        its place would be a silent straightening.

        Strict index parsing does not accept a row with such an arc at
        all, and the element honestly remains an atom of "no reliable
        profile" — neither a contour nor a polygon built from invented
        points.
        """

        profile = copy.deepcopy(LIVE_ARC_PROFILE)
        profile["arc_midpoints"][0][2] = None
        node = _lift(LIVE_ARC_FLOOR, profile)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.MISSING_GEOMETRY.value)


class OneSourceYieldsExactlyOneNode(unittest.TestCase):
    """A multiset: the op does NOT get born next to an atom of the same
    element."""

    def test_no_source_id_is_lifted_twice(self) -> None:
        document = _document(LIVE_ARC_FLOOR, offset=LIVE_ARC_OFFSET)
        result = lift_document_detailed(
            document, {LIVE_ARC_FLOOR: copy.deepcopy(LIVE_ARC_PROFILE)})
        sources = [node["source_element_id"] for node in result.nodes]
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(len(result.nodes), len(document.elements))

    def test_a_lifted_contour_leaves_no_diagnostic(self) -> None:
        document = _document(LIVE_ARC_FLOOR, offset=LIVE_ARC_OFFSET)
        result = lift_document_detailed(
            document, {LIVE_ARC_FLOOR: copy.deepcopy(LIVE_ARC_PROFILE)})
        self.assertEqual(
            [d.source_element_id for d in result.diagnostics], [])


class SubMillimeterOffsetIsNotSilentlyDropped(unittest.TestCase):
    """Кодекс №8, лифт-половина (2026-07-29, tasks/b8f3v4r97.output сессии
    eeccfb91) — `_lift_floor`/`_lift_floor_by_contour` gated
    height_offset_mm on ``abs(value) >= 1.0``, so a genuine 0.4/0.6/0.999мм
    read from FLOOR_HEIGHTABOVELEVEL_PARAM never reached params at all —
    the key was absent, not zero. Canon /3 (60c61dfa) already makes absent
    canonicalize as 0.0, but that only papers over values that ALREADY
    round to 0 on the canon grid (CANON_MM=1мм) — 0.6мм and 0.999мм round
    to 1.0мм, a genuinely different canon value lift was throwing away.

    New law: discard ONLY when canon's own grid would flatten the value to
    zero anyway (lossless either way); keep anything that rounds to a
    nonzero canon value."""

    _SQUARE = {
        "profile_available": True,
        "exterior_loop": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
        "curve_kinds": [["line", "line", "line", "line"]],
        "arc_midpoints": [[None, None, None, None]],
        "holes": [],
    }

    def test_contour_floor_keeps_a_genuine_0_6mm_offset(self) -> None:
        node = _lift(LIVE_ARC_FLOOR, LIVE_ARC_PROFILE, offset=0.6)
        self.assertEqual(node["op_name"], "create_floor_by_contour")
        self.assertEqual(node["params"].get("height_offset_mm"), 0.6)

    def test_plain_floor_keeps_a_genuine_0_6mm_offset(self) -> None:
        node = _lift("4001", self._SQUARE, offset=0.6)
        self.assertEqual(node["op_name"], "create_floor")
        self.assertEqual(node["params"].get("height_offset_mm"), 0.6)

    def test_contour_floor_keeps_a_genuine_minus_0_999mm_offset(self) -> None:
        node = _lift(LIVE_ARC_FLOOR, LIVE_ARC_PROFILE, offset=-0.999)
        self.assertEqual(node["params"].get("height_offset_mm"), -0.999)

    def test_values_the_canon_grid_itself_flattens_to_zero_stay_absent(
            self) -> None:
        """0.4мм rounds to 0 on the 1мм canon grid — an absent key and an
        explicit 0.4 are canon-identical, so lift staying silent here costs
        nothing; pinned so the choice is a decision, not an accident."""
        node = _lift(LIVE_ARC_FLOOR, LIVE_ARC_PROFILE, offset=0.4)
        self.assertNotIn("height_offset_mm", node["params"])
        node2 = _lift("4001", self._SQUARE, offset=-0.4)
        self.assertNotIn("height_offset_mm", node2["params"])

    def test_roundtrip_minus_0999_to_0999_matches_canon_grid_oracle(self) -> None:
        """Codex range −0.999…0.999, both branches of the floor: presence
        of height_offset_mm in params matches EXACTLY round(v/CANON_MM) !=
        0 — the same oracle test_fold.py's canon-side test already
        pins."""
        from kir.decompile.schema import CANON_MM
        for v in (-0.999, -0.6, -0.4, 0.4, 0.6, 0.999):
            expect_present = round(v / CANON_MM) != 0
            for label, node in (
                ("contour", _lift(LIVE_ARC_FLOOR, LIVE_ARC_PROFILE, offset=v)),
                ("plain", _lift("4001", self._SQUARE, offset=v)),
            ):
                with self.subTest(offset=v, branch=label):
                    if expect_present:
                        self.assertEqual(
                            node["params"].get("height_offset_mm"), v)
                    else:
                        self.assertNotIn("height_offset_mm", node["params"])

    def test_zero_offset_still_absent_byte_parity(self) -> None:
        """offset=0.0 by itself carries no new DOF — the historical
        byte-identical emission for a ZERO offset is untouched."""
        node = _lift(LIVE_ARC_FLOOR, LIVE_ARC_PROFILE, offset=0.0)
        self.assertNotIn("height_offset_mm", node["params"])


class TheLiveRowsDoNotDrift(unittest.TestCase):
    def test_embedded_profiles_match_the_artifact_when_present(self) -> None:
        # 🔴 THE GUARD AND THE READER MUST LOOK AT THE SAME FILE (fix
        # 22.08.2026). `демо-v3` was compressed by the cleanup job: the
        # guard sees `.json.gz` and says "it's there," the bare
        # `read_text` looks for `.json` and says "no file." The third
        # carrier of this class, found by one partial suite run.
        from kir.decompile.snapshot_io import (open_snapshot,
                                                    snapshot_file_exists)
        if not snapshot_file_exists(_ARTIFACT):
            self.skipTest(f"нет артефакта {_ARTIFACT}")
        with open_snapshot(_ARTIFACT, "rt", encoding="utf-8") as handle:
            index = json.load(handle)
        rows = index["profile_index"]
        for element_id, embedded in (
            (LIVE_ARC_FLOOR, LIVE_ARC_PROFILE),
            (LIVE_CIRCLE_FLOOR, LIVE_CIRCLE_PROFILE),
        ):
            with self.subTest(element=element_id):
                actual = rows[element_id]
                for key in ("exterior_loop", "curve_kinds", "arc_midpoints"):
                    self.assertEqual(actual[key], embedded[key])


if __name__ == "__main__":
    unittest.main()
