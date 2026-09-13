"""A CHECK THAT ASKED A PART DOES NOT ANSWER FOR THE WHOLE (2026-09-04).

Seven defects of shape and body, found in one pass, and all seven of ONE
form. Not one instrument was broken: each honestly answered its own
question, and the question was narrower than the subject. A list — to make
the form visible, not seven cases:

    FC-13  the turn limit walked only the INTERNAL nodes — the seam of a
           closed polyline was not counted as a node, though a miter cuts
           there just the same;
    FC-14a degeneracy was measured by the BOUNDING BOX — i.e. the WORLD
           axes, while a grid degenerates along any line, diagonal included;
    FC-14b matching corners were asked only of NEIGHBOURING pairs — four out
           of six;
    FC-14c samples ran uniformly over the DOMAIN, while the shape changes at
           the boundaries of knot SPANS, and a narrow span was stepped over
           entirely;
    FC-22  the blend was handed OUTER rings only, while the witness computed
           the end-face area over the full region — with openings subtracted;
    FC-23  a body's placement and its profile were checked SEPARATELY, while
           the body lives in their sum;
    FC-20  the reference census walked the WHOLE dictionary, not knowing
           that for one kind of node (`at_element`) the selector's shape is
           CLOSED.

🔴 EVERY TEST HERE HAS A CONTROL, AND THIS IS NOT A RITUAL. A refusal that
ALWAYS fires is indistinguishable from a broken operation; a measurement
with no other side answers the question "does it work", not "does it
catch". So next to every experiment stands an input that must PASS.
"""
from __future__ import annotations

import unittest

from kir import chunking
from kir import contour as C
from kir import relate
from kir import surface as S
from kir import sweep_path as SW
from kir.diag import KirRefusal
from kir.registry_base import COORD_LIMIT_MM
from kir.solid_emit import (emit_solid_blend, emit_solid_extrusion,
                            emit_solid_revolve)


# ── FC-13 ───────────────────────────────────────────────────────────────────

_CLOSED = [[0, 0, 0], [10000, 0, 0], [9000, 3000, 0], [0, 0, 0]]


class TheSeamOfAClosedPathIsANode(unittest.TestCase):
    """On a closed polyline the seam is a node just like any other, and the turn limit sees it.

    MEASUREMENT BEFORE THE FIX, on this exact triangle: `is_closed` True,
    computed angles [108.4°, 90.0°], and the seam's 161.6° at a 120° limit
    WAS ABSENT FROM THE LIST — so `feasibility` answered `None`, "buildable".
    """

    def test_the_seam_angle_is_measured_at_all(self) -> None:
        nodes = dict(SW.turns_by_node(_CLOSED))
        self.assertIn(0, nodes, "шов — узел 0, и он обязан быть в списке")
        self.assertAlmostEqual(nodes[0], 161.6, places=1)

    def test_the_isotropic_check_refuses_the_seam_and_says_so(self) -> None:
        why = SW.feasibility(_CLOSED, 200.0)
        self.assertIsNotNone(why, "ДО ПРАВКИ здесь был None — 161.6° проезжал")
        self.assertIn("ШОВ", why)
        self.assertIn("161.6", why)

    def test_the_exact_check_refuses_the_seam_too(self) -> None:
        """Both feasibility checks carry ONE law, so both must go red."""
        region = _region([[0, 0], [200, 0], [200, 200], [0, 200]])
        why = SW.frame_feasibility(_CLOSED, region, (100.0, 100.0),
                                   (0.0, 0.0, 1.0))
        self.assertIsNotNone(why)
        self.assertIn("ШОВ", why)

    def test_CONTROL_the_same_polyline_left_OPEN_is_allowed(self) -> None:
        """CONTROL: the issue is the SEAM, not the triangle itself. Open the
        path — that same node no longer exists, and both links must pass."""
        self.assertIsNone(SW.feasibility(_CLOSED[:-1], 200.0))

    def test_CONTROL_the_internal_only_list_keeps_its_contract(self) -> None:
        """CONTROL OF THE OTHER SIDE: `turn_angles_deg` is indexed by LINKS,
        and appending the seam to it would shift all of its readers. The fix
        had to add a second entry point, not spoil the first."""
        self.assertEqual(len(SW.turn_angles_deg(_CLOSED)), len(_CLOSED) - 2)

    def test_CONTROL_a_gentle_closed_path_still_builds(self) -> None:
        """CONTROL: being closed is not by itself a refusal. A square with a
        90° seam must pass — otherwise the new law would ban a whole kind of path."""
        square = [[0, 0, 0], [6000, 0, 0], [6000, 6000, 0], [0, 6000, 0],
                  [0, 0, 0]]
        self.assertIsNone(SW.feasibility(square, 200.0))


# ── FC-14a / FC-14b ─────────────────────────────────────────────────────────

def _grid_surface(points, du=1, dv=1, cu=2, cv=2) -> dict:
    return {"degree_u": du, "degree_v": dv, "count_u": cu, "count_v": cv,
            "knots_u": S.uniform_clamped_knots(du, cu),
            "knots_v": S.uniform_clamped_knots(dv, cv),
            "control_points_mm": points}


_SOUND = _grid_surface([[0, 0, 0], [0, 1000, 0], [1000, 0, 0], [1000, 1000, 500]])


class ASurfaceIsJudgedByItsRankNotItsBoundingBox(unittest.TestCase):
    """FC-14a. A bounding box measures the WORLD axes; degeneracy can run along a diagonal.

    MEASUREMENT BEFORE THE FIX: a grid of points `t·(1000, 1000, 1000)` had
    a bounding box of 3000x3000x3000 mm — the second span three times the
    thousand-millimetre limit — and was accepted with EMPTY diags.
    """

    def _diag(self, surface):
        diags: list = []
        out = S.validate_surface(surface, "S1", "surface", diags)
        return out, diags

    def test_a_grid_collinear_along_a_diagonal_is_refused(self) -> None:
        out, diags = self._diag(_grid_surface(
            [[0, 0, 0], [1000, 1000, 1000], [2000, 2000, 2000],
             [3000, 3000, 3000]]))
        self.assertIsNone(out, "ДО ПРАВКИ это принималось, diags был ПУСТ")
        self.assertEqual(diags[0].code, S.SURFACE_DEGENERATE)
        self.assertIn("на одной прямой", diags[0].message_ru)

    def test_the_deviation_is_a_number_not_a_verdict(self) -> None:
        """Deviation from a line is measurable, and the control tells them
        apart: for a sound grid it exceeds the limit, for a collinear one
        it is arithmetic zero.

        Not `assertEqual(0.0)`: for the diagonal `t·(1000,1000,1000)`
        subtraction leaves a 7.9e-13 mm double-precision remainder. What
        must be compared is the LIMIT the decision is actually made against,
        not an ideal zero — otherwise the test would be guarding arithmetic
        instead of the law."""
        self.assertLess(S.line_deviation_mm(
            [[0, 0, 0], [1000, 1000, 1000], [2000, 2000, 2000]]), 1e-9)
        self.assertGreater(
            S.line_deviation_mm(_SOUND["control_points_mm"]), S.MIN_EXTENT_MM)

    def test_CONTROL_a_sound_grid_is_still_accepted(self) -> None:
        out, diags = self._diag(_SOUND)
        self.assertIsNotNone(out, f"здоровая сетка отвергнута: {diags}")
        self.assertEqual(diags, [])


class CoincidentCornersAreSixPairsNotFour(unittest.TestCase):
    """FC-14b. Neighbouring pairs are four out of six; nobody ever asked about the two diagonals.

    MEASUREMENT BEFORE THE FIX: a 2x2 grid with `p00 == p11` was accepted,
    diags empty. All four of its BOUNDARY edges are nonzero — the patch is
    not collapsed, it is FOLDED IN TWO and pinched at a point, and a check
    of neighbouring corners does not see that.
    """

    def _diag(self, surface):
        diags: list = []
        out = S.validate_surface(surface, "S1", "surface", diags)
        return out, diags

    def test_opposite_corners_that_coincide_are_refused(self) -> None:
        out, diags = self._diag(_grid_surface(
            [[0, 0, 0], [1000, 0, 0], [0, 1000, 0], [0, 0, 0]]))
        self.assertIsNone(out, "ДО ПРАВКИ это принималось, diags был ПУСТ")
        self.assertEqual(diags[0].code, S.SURFACE_CORNER)
        self.assertIn("ПРОТИВОПОЛОЖНЫЕ", diags[0].message_ru)

    def test_the_four_edges_of_the_folded_patch_are_all_NONZERO(self) -> None:
        """A CONTROL OF THE ACCUSATION ITSELF: if even one edge were zero,
        the old check would have caught the defect, and the finding would be a fabrication."""
        corners = S.surface_corners(
            [[0, 0, 0], [1000, 0, 0], [0, 1000, 0], [0, 0, 0]], 2, 2)
        for ci in range(4):
            a, b = corners[ci], corners[(ci + 1) % 4]
            edge = max(abs(a[k] - b[k]) for k in range(3))
            self.assertGreaterEqual(edge, S.MIN_EXTENT_MM,
                                    f"ребро {ci} оказалось нулевым")

    def test_CONTROL_a_sound_grid_keeps_its_four_distinct_corners(self) -> None:
        out, diags = self._diag(_SOUND)
        self.assertIsNotNone(out, f"здоровая сетка отвергнута: {diags}")


# ── FC-14c ──────────────────────────────────────────────────────────────────

_NARROW = {
    "degree_u": 1, "degree_v": 1, "count_u": 4, "count_v": 2,
    "knots_u": [0.0, 0.0, 0.400, 0.402, 1.0, 1.0],
    "knots_v": [0.0, 0.0, 1.0, 1.0],
    "control_points_mm": [[0, 0, 0], [0, 1000, 0],
                          [400, 0, 10000], [400, 1000, 10000],
                          [402, 0, 10000], [402, 1000, 10000],
                          [1000, 0, 0], [1000, 1000, 0]],
    "weights": None,
}


class SamplesFollowTheKnotsNotTheDomain(unittest.TestCase):
    """FC-14c. The shape changes at span boundaries, while the step ran over the domain.

    MEASUREMENT BEFORE THE FIX, on this surface: 40 samples, sample `max_z`
    9290.2 mm, while `z(u = 0.401)` = 10000.0 mm. That is, the witness
    declared the face checked without ever once looking where it is
    highest: the narrow span [0.400, 0.402] got ZERO samples.
    """

    def test_the_narrow_span_gets_its_samples(self) -> None:
        us = S.sample_parameters(0.0, 1.0, _NARROW["knots_u"])
        inside = [u for u in us if 0.400 <= u <= 0.402]
        self.assertGreaterEqual(len(inside), S.SAMPLES_PER_SPAN,
                                f"ДО ПРАВКИ здесь было НОЛЬ; сейчас {us}")

    def test_the_peak_is_actually_seen_by_the_witness(self) -> None:
        peak = S.evaluate_surface(_NARROW, 0.401, 0.5)[2]
        best = max(p[2] for p in S.sample_surface(_NARROW))
        self.assertAlmostEqual(best, peak, places=6,
                               msg="ДО ПРАВКИ: 9290.2 против 10000.0")

    def test_the_promise_in_the_docstring_is_the_law_in_the_code(self) -> None:
        """The promise is checked by a COUNT, not by reading the prose: in
        every non-empty span exactly `SAMPLES_PER_SPAN` interior points, the boundaries exactly."""
        us = S.sample_parameters(0.0, 1.0, _NARROW["knots_u"])
        breaks = S.span_breaks(0.0, 1.0, _NARROW["knots_u"])
        for b in breaks:
            self.assertIn(b, us, f"граница пролёта {b} не попала в выборку")
        for i in range(len(breaks) - 1):
            a, z = breaks[i], breaks[i + 1]
            self.assertEqual(sum(1 for u in us if a < u < z),
                             S.SAMPLES_PER_SPAN)

    def test_CONTROL_the_declared_ceiling_still_holds(self) -> None:
        """CONTROL: a per-span promise has no right to blow up emission
        size. Above the ceiling of spans, sampling is uniform, and this is DECLARED."""
        many = S.uniform_clamped_knots(3, 40)
        self.assertEqual(len(S.sample_parameters(many[3], many[40], many)),
                         S.MAX_SAMPLES_PER_DIR)

    def test_CONTROL_an_explicit_count_is_still_obeyed(self) -> None:
        self.assertEqual(len(S.sample_surface(_NARROW, nu=5, nv=4)), 20)


# ── FC-22 / FC-23 ───────────────────────────────────────────────────────────

def _region(points, holes=()) -> dict:
    diags: list = []
    outer = C._validate_shape({"shape": "poly", "points_mm": points},
                              [], "B1", "p", diags)
    assert outer is not None, diags
    rings = []
    for hole in holes:
        diags = []
        ring = C._validate_shape({"shape": "poly", "points_mm": hole},
                                 [], "B1", "p", diags)
        assert ring is not None, diags
        rings.append(ring)
    return {"outer": outer, "holes": rings}


_LOW = [[0, 0], [2000, 0], [2000, 2000], [0, 2000]]
_TOP = [[400, 400], [1600, 400], [1600, 1600], [400, 1600]]
_HOLE = [[800, 800], [1200, 800], [1200, 1200], [800, 1200]]


def _blend_op(region_lo, region_hi) -> dict:
    return {"id": "B1", "category": "generic_model", "name": "Пуфик",
            "height_mm": 3000.0, "base_z_mm": None,
            "__region_profile__": region_lo,
            "__region_profile_top__": region_hi}


class ABlendCannotSayAHoleSoItMustNotAcceptOne(unittest.TestCase):
    """FC-22. The registry accepted openings, the factory does not express them, and they were LOST.

    MEASUREMENT BEFORE THE FIX (a 2000x2000 profile with a 400x400 opening):
    `ok=True`, `__hl_` rings in the emitted C# ZERO — the body came out
    solid. Meanwhile the end-face-area witness takes `region_measures`, and
    that DOES subtract the opening: 3,840,000 mm² against 4,000,000 mm² for
    a solid face. The witness would have accused Revit of OUR OWN lost ring.
    """

    def test_a_profile_with_a_hole_is_refused_before_the_effect(self) -> None:
        with self.assertRaises(KirRefusal) as caught:
            emit_solid_blend(_blend_op(_region(_LOW, [_HOLE]), _region(_TOP)),
                             "2023", "S1")
        message = caught.exception.diagnostics[0].message_ru
        self.assertIn("проём", message)
        self.assertIn("CreateBlendGeometry", message)

    def test_the_top_profile_is_asked_too(self) -> None:
        """There are two profiles, and silence about the top one would be the same loss."""
        with self.assertRaises(KirRefusal) as caught:
            emit_solid_blend(_blend_op(_region(_LOW), _region(_TOP, [_HOLE])),
                             "2023", "S1")
        self.assertEqual(caught.exception.diagnostics[0].field_name,
                         "profile_top")

    def test_the_refusal_names_the_next_move(self) -> None:
        with self.assertRaises(KirRefusal) as caught:
            emit_solid_blend(_blend_op(_region(_LOW, [_HOLE]), _region(_TOP)),
                             "2023", "S1")
        self.assertIn("create_solid_boolean",
                      caught.exception.diagnostics[0].message_ru)

    def test_CONTROL_a_blend_without_holes_still_builds(self) -> None:
        _decl, create, _checks, _rb = emit_solid_blend(
            _blend_op(_region(_LOW), _region(_TOP)), "2023", "S1")
        self.assertIn("GeometryCreationUtilities.CreateBlendGeometry(", create)
        self.assertNotIn("__hl_", create)


_PROFILE = [[0, 0], [2000, 0], [2000, 1000], [0, 1000]]


def _revolve_op(axis) -> dict:
    return {"id": "R1", "category": "generic_model", "name": "Вал",
            "sweep_deg": 360.0, "axis_xy_mm": list(axis), "base_z_mm": None,
            "__region__": _region(_PROFILE)}


class PlacementAndProfileAreLegalApartAndIllegalTogether(unittest.TestCase):
    """FC-23. A body lives in the SUM of placement and profile, but they were checked separately.

    MEASUREMENT BEFORE THE FIX: `axis_xy_mm = [16,000,000, 0]` (exactly the
    limit, legal) with a 2000x1000 profile (legal) gave `ok=True`, diags 0,
    while the body's world bounding box reached 16,002,000 mm. The sibling
    operation — an extrusion with a plane whose origin sits at the limit —
    had the SAME hole.
    """

    def test_a_revolve_pushed_past_the_extent_by_its_axis_is_refused(self) -> None:
        with self.assertRaises(KirRefusal) as caught:
            emit_solid_revolve(_revolve_op([COORD_LIMIT_MM, 0]), "2023", "S1")
        diag = caught.exception.diagnostics[0]
        self.assertEqual(diag.field_name, "axis_xy_mm")
        self.assertGreater(abs(diag.got), COORD_LIMIT_MM)

    def test_the_sibling_extrusion_is_closed_by_the_SAME_guard(self) -> None:
        """There is one law — so there must not be two holes left standing."""
        plane = {"origin_mm": [COORD_LIMIT_MM, 0.0, 0.0],
                 "normal": [0, 0, 1], "x_dir": [1, 0, 0]}
        with self.assertRaises(KirRefusal):
            emit_solid_extrusion(
                {"id": "E1", "category": "generic_model", "name": "Плита",
                 "height_mm": 500.0, "base_z_mm": None,
                 "__region__": _region(_PROFILE), "plane": plane},
                "2023", "S1")

    def test_CONTROL_the_same_body_at_the_origin_still_builds(self) -> None:
        _decl, create, _checks, _rb = emit_solid_revolve(
            _revolve_op([0, 0]), "2023", "S1")
        self.assertIn("CreateRevolvedGeometry(", create)

    def test_CONTROL_a_body_that_merely_SITS_far_away_is_allowed(self) -> None:
        """BOUNDARY CONTROL: the refusal must catch GOING PAST the extent,
        not "far away". An axis pulled back inward by exactly the profile's
        size must pass — otherwise the new guard would eat into a legal
        working extent."""
        _decl, create, _checks, _rb = emit_solid_revolve(
            _revolve_op([COORD_LIMIT_MM - 2000.0, 0]), "2023", "S1")
        self.assertIn("CreateRevolvedGeometry(", create)


# ── FC-20 ───────────────────────────────────────────────────────────────────

_ADDRESS = {"at_element": {"by": "ref", "value": "W1"}, "point": "end"}


def _chunk(op) -> chunking.Chunk:
    return chunking.Chunk(index=1, ops=(op,), est_bytes=1,
                          op_ids=frozenset({"W2"}), needs=("W1",),
                          reason="тест")


class ARewriteMustKnowWhichNodesAreNotItsToRewrite(unittest.TestCase):
    """FC-20. Chunking made a CORRECT program illegal.

    MEASUREMENT BEFORE THE FIX: a legal address `{"at_element": {"by":
    "ref", "value": "W1"}, "point": "end"}` (the grammar accepts it, diags
    0) turned, after `bind_refs`, into `{"at_element": {"by": "element_id",
    "value": 777}, ...}` and got `KIR-T001`. The address grammar (`relate`)
    keeps the selector's shape CLOSED on purpose: an address reads the
    NUMBERS of the addressed op, not an element's id.
    """

    def test_the_address_was_legal_BEFORE_the_split(self) -> None:
        """The argument of the accusation: the program was correct, and chunking broke it."""
        diags: list = []
        self.assertTrue(relate.validate_address(
            _ADDRESS, "W2", "p0_mm", diags, dims=2), diags)
        self.assertEqual(diags, [])

    def test_the_grammar_still_refuses_element_id_there(self) -> None:
        """CONTROL OF THE OTHER SIDE: if the grammar had accepted
        element_id, there would be nothing to fix, and the finding would be a fabrication."""
        diags: list = []
        self.assertFalse(relate.validate_address(
            {"at_element": {"by": "element_id", "value": 777},
             "point": "end"}, "W2", "p0_mm", diags, dims=2))
        self.assertEqual(diags[0].code, "KIR-T001")

    def test_a_cross_chunk_ref_inside_an_address_refuses_BY_NAME(self) -> None:
        with self.assertRaises(ValueError) as caught:
            chunking.bind_refs(
                _chunk({"op": "create_wall", "id": "W2", "p0_mm": _ADDRESS}),
                {"W1": [777]})
        self.assertIn("at_element", str(caught.exception))

    def test_the_refusal_names_the_next_move(self) -> None:
        with self.assertRaises(ValueError) as caught:
            chunking.bind_refs(
                _chunk({"op": "create_wall", "id": "W2", "p0_mm": _ADDRESS}),
                {"W1": [777]})
        self.assertIn("ОДНОМ чанке", str(caught.exception))

    def test_CONTROL_an_ordinary_ref_is_still_rewritten(self) -> None:
        """CONTROL: the fix has no right to switch off the census itself —
        that is the whole reason `bind_refs` exists."""
        out = chunking.bind_refs(
            _chunk({"op": "create_wall", "id": "W2",
                    "level": {"by": "ref", "value": "W1"}}),
            {"W1": [355]})
        self.assertEqual(out[0]["level"], {"by": "element_id", "value": 355})

    def test_CONTROL_an_address_INSIDE_the_chunk_is_left_alone(self) -> None:
        """NARROWNESS CONTROL: the refusal catches crossing the BOUNDARY,
        not an address as a kind. An addressed op in the same chunk — the
        reference is not in `needs`, and the address must reach emission untouched."""
        chunk = chunking.Chunk(
            index=0,
            ops=({"op": "create_wall", "id": "W1", "p0_mm": [0, 0]},
                 {"op": "create_wall", "id": "W2", "p0_mm": dict(_ADDRESS)}),
            est_bytes=2, op_ids=frozenset({"W1", "W2"}), needs=(),
            reason="тест")
        out = chunking.bind_refs(chunk, {})
        self.assertEqual(out[1]["p0_mm"], _ADDRESS)


if __name__ == "__main__":
    unittest.main()
