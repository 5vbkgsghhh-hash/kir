"""RELATE — addressing from grid axes: locks on the grammar, three
defects, and resolution.

Run standalone (the full suite is 5 GB RSS):

    venv/bin/python3.12 -m pytest kir/tests/test_relate.py -q

STRUCTURE. The first three classes are REFUTING tests for three latent
defects of the shipped mechanism ``contour.resolve_anchor`` (spec §1.3).
They are written BEFORE the fix and are red on the unfixed tree — that is
their job. Next come the grammar, resolution, and the places where an
address is resolved.

THE BOUNDARY OF THIS INSTRUMENT, IN WORDS. Everything provable by a pure
function is proved here: the form of an address (from text) and its
resolution (from a snapshot fixture). NOTHING is proved about the live
model: that an axis has not moved between the snapshot and the write, that
an element landed on the point — those are witnesses, live Revit, and a
separate ``grid_anchor`` wave. A test that "checked" this on a fixture
would be self-certification.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_relate_queue.jsonl"))

from kir import contour, macros, relate               # noqa: E402
from kir.compiler import compile_program              # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT        # noqa: E402


# ── grid-axis fixtures ──────────────────────────────────────────────────────

#: A rotated building. Measured 08-03: at `sklnk_eom` ALL 57 axes run at
#: 156.1° and 66.1° — not one matches a world axis. The same angle is used
#: here.
_ROT_DEG = 66.1
_UX, _UY = math.cos(math.radians(_ROT_DEG)), math.sin(math.radians(_ROT_DEG))
_NX, _NY = -_UY, _UX          # left-hand normal to the direction of axes 25/26

_L = 30_000.0


def _rotated_pool() -> list:
    """Three axes of a rotated building: "25" and "26" are parallel (3000
    mm apart), "A" is perpendicular to both and passes through the
    origin."""
    return [
        {"id": 101, "name": "25",
         "p0_mm": [0.0, 0.0], "p1_mm": [_UX * _L, _UY * _L]},
        {"id": 102, "name": "26",
         "p0_mm": [_NX * 3000.0, _NY * 3000.0],
         "p1_mm": [_UX * _L + _NX * 3000.0, _UY * _L + _NY * 3000.0]},
        {"id": 103, "name": "А",
         "p0_mm": [0.0, 0.0], "p1_mm": [_NX * _L, _NY * _L]},
    ]


def _perp_from_grid25(point) -> float:
    """The signed distance from a point to the line "25" — computed HERE,
    without a single function from `relate`: checking the resolver with
    its own arithmetic would mean checking it against itself."""
    return -_UY * point[0] + _UX * point[1]


def _orthogonal_pool() -> list:
    """The SHIPPED-FIXTURE grid, not a private one: "1"/"2" are vertical
    (x=0/4000), "A"/"B" are horizontal (y=0/4500).

    A second set of axes next to `fixtures.GROUND_SNAPSHOT` would drift
    from it at the very first edit — exactly what the fixtures' docstring
    warns against.
    """
    return [dict(row) for row in GROUND_SNAPSHOT["grids"]]


def _resolve(address, pool, *, dims=2, field="xy", truncated=False):
    diags: list = []
    receipt: list = []
    point = relate.resolve_address(address, pool, "op1", field, diags,
                                   dims=dims, truncated=truncated,
                                   receipt=receipt)
    return point, diags, receipt


def _codes(diags) -> list:
    return [d.code for d in diags]


# ── D1: WORLD FRAME OF THE OFFSET ───────────────────────────────────────────

class D1WorldFrameOffset(unittest.TestCase):
    """Spec §1.3, D1. The shipped form offsets the point in WORLD
    coordinates."""

    def test_shipped_world_offset_is_not_perpendicular(self):
        """THE NUMBER that proves the defect: on the rotated grid,
        `offset_mm: [200, 0]` gives 182.9 mm from the axis and ON THE
        WRONG SIDE."""
        diags: list = []
        point = contour.resolve_anchor(
            {"at_grid": ["25", "А"], "offset_mm": [200, 0]},
            _rotated_pool(), "op1", "origin", diags)
        self.assertEqual(diags, [])
        self.assertIsNotNone(point)
        got = _perp_from_grid25(point)
        self.assertAlmostEqual(got, -182.9, places=1)
        # "toward 26" is PLUS along the normal; the world offset went negative.
        self.assertLess(got, 0.0)

    def test_offset_from_a_rotated_grid_is_expressible(self):
        """THE FIX: the offset is named at the LINE and measured
        perpendicular to the axis itself, the direction is read from the
        model."""
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "25", "offset_mm": 200, "toward": "26"},
                         "А"]},
            _rotated_pool())
        self.assertEqual(diags, [])
        self.assertAlmostEqual(_perp_from_grid25(point), 200.0, places=6)

    def test_offset_direction_follows_the_named_neighbour(self):
        """The side is named by a NEIGHBOR, not by a sign: flip the
        neighbor and the point moves to the other side, with no sign
        convention needed for it."""
        pool = _rotated_pool()
        # "27" is the mirror neighbor: the same line, but on the other side.
        pool.append({"id": 104, "name": "27",
                     "p0_mm": [-_NX * 3000.0, -_NY * 3000.0],
                     "p1_mm": [_UX * _L - _NX * 3000.0,
                               _UY * _L - _NY * 3000.0]})
        toward26, d1, _ = _resolve(
            {"at_grid": [{"grid": "25", "offset_mm": 200, "toward": "26"},
                         "А"]}, pool)
        toward27, d2, _ = _resolve(
            {"at_grid": [{"grid": "25", "offset_mm": 200, "toward": "27"},
                         "А"]}, pool)
        self.assertEqual((d1, d2), ([], []))
        self.assertAlmostEqual(_perp_from_grid25(toward26), 200.0, places=6)
        self.assertAlmostEqual(_perp_from_grid25(toward27), -200.0, places=6)

    def test_world_offset_is_closed_in_the_new_slots(self):
        """D1 is not inherited: in the new slots the world pair [dx,dy] IS
        REJECTED, and the rejection names the replacement."""
        point, diags, _r = _resolve(
            {"at_grid": ["А", "1"], "offset_mm": [200, 0]}, _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-T001"])
        self.assertIn("toward", diags[0].message_ru)

    def test_world_offset_still_works_for_region(self):
        """…and yet the `region` goldens do not move: the legacy door is
        open BY NAME and to exactly one consumer."""
        diags: list = []
        point = contour.resolve_anchor(
            {"at_grid": ["А", "1"], "offset_mm": [200, 300]},
            _orthogonal_pool(), "op1", "origin", diags)
        self.assertEqual(diags, [])
        self.assertEqual(point, [200.0, 300.0])


# ── D2: SILENT CHOICE ON A NAME COLLISION ───────────────────────────────────

class D2DuplicateNames(unittest.TestCase):
    """Spec §1.3, D2. `{name: g for g in pool}` keeps the LAST row."""

    @staticmethod
    def _pool_with_two_b():
        return [
            {"id": 11, "name": "Б", "p0_mm": [1000, -5000], "p1_mm": [1000, 25000]},
            {"id": 12, "name": "Б", "p0_mm": [5000, -5000], "p1_mm": [5000, 25000]},
            {"id": 13, "name": "1", "p0_mm": [-5000, 0], "p1_mm": [30000, 0]},
        ]

    def test_shipped_code_silently_took_the_last_row(self):
        """Proof BEFORE: two "B"s, zero diagnostics, the point taken from
        the LAST one."""
        by_name = {str(g.get("name", "")).strip(): g
                   for g in self._pool_with_two_b()}          # line 86 as was
        self.assertEqual(by_name["Б"]["id"], 12)

    def test_duplicate_names_now_refuse_with_both_ids(self):
        point, diags, _r = _resolve({"at_grid": ["Б", "1"]},
                                    self._pool_with_two_b())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G109"])
        self.assertEqual([c["id"] for c in diags[0].candidates], [11, 12])
        # the repair is named and it is OUTSIDE the grammar — the language
        # does not accept element_id
        self.assertIn("литералом", diags[0].message_ru)

    def test_contour_inherits_the_fix(self):
        """The same pool through the shipped CONTOUR entry point — the
        same failure, not a silent choice."""
        diags: list = []
        point = contour.resolve_anchor({"at_grid": ["Б", "1"]},
                                       self._pool_with_two_b(),
                                       "op1", "origin", diags)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G109"])


# ── D3: CONDITIONING ─────────────────────────────────────────────────────────

class D3Conditioning(unittest.TestCase):
    """Spec §1.3, D3. `|den| < 1e-9` is an angle on the order of 1e-15
    rad."""

    @staticmethod
    def _near_parallel(angle_deg: float):
        rad = math.radians(angle_deg)
        return [
            {"id": 21, "name": "A", "p0_mm": [0, 0], "p1_mm": [30000, 0]},
            {"id": 22, "name": "B", "p0_mm": [0, 500],
             "p1_mm": [30000 * math.cos(rad), 500 + 30000 * math.sin(rad)]},
        ]

    @staticmethod
    def _shipped_line_intersection(p0, p1, q0, q1):
        """Verbatim `contour._line_intersection` as it was before 08-04 —
        the sole threshold `|den| < 1e-9`. Held HERE, because the proof of
        a defect must survive its own fix."""
        d1 = (p1[0] - p0[0], p1[1] - p0[1])
        d2 = (q1[0] - q0[0], q1[1] - q0[1])
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-9:
            return None
        t = ((q0[0] - p0[0]) * d2[1] - (q0[1] - p0[1]) * d2[0]) / den
        return (p0[0] + t * d1[0], p0[1] + t * d1[1])

    def test_shipped_line_intersection_accepted_a_tenth_of_a_degree(self):
        """Proof BEFORE: at 0.1°, the old function returns a point, and
        that point is 286 meters from the origin — i.e. noise."""
        pt = self._shipped_line_intersection(
            [0, 0], [30000, 0], [0, 500],
            [30000 * math.cos(math.radians(0.1)),
             500 + 30000 * math.sin(math.radians(0.1))])
        self.assertIsNotNone(pt)
        self.assertGreater(abs(pt[0]), 250_000)

    def test_contour_inherits_the_conditioning_fix(self):
        diags: list = []
        point = contour.resolve_anchor({"at_grid": ["A", "B"]},
                                       self._near_parallel(0.1),
                                       "op1", "origin", diags)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G110"])

    def test_near_parallel_pair_now_refuses(self):
        point, diags, _r = _resolve({"at_grid": ["A", "B"]},
                                    self._near_parallel(0.1))
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G110"])
        self.assertIn("0.100", diags[0].message_ru)

    def test_threshold_is_exactly_one_degree(self):
        """The threshold is DERIVED (§4.4), so it is checked from both
        sides."""
        below, d_below, _ = _resolve({"at_grid": ["A", "B"]},
                                     self._near_parallel(0.99))
        above, d_above, _ = _resolve({"at_grid": ["A", "B"]},
                                     self._near_parallel(1.01))
        self.assertIsNone(below)
        self.assertEqual(_codes(d_below), ["KIR-G110"])
        self.assertIsNotNone(above)
        self.assertEqual(d_above, [])

    def test_parallel_pair_refuses_with_the_same_code(self):
        point, diags, _r = _resolve({"at_grid": ["A", "B"]},
                                    self._near_parallel(0.0))
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G110"])


# ── GRAMMAR: closed, three nodes ────────────────────────────────────────────

class Grammar(unittest.TestCase):

    def test_four_reference_forms_accepted(self):
        pool = _orthogonal_pool()
        for line in ("А", {"grid": "А"},
                     {"grid": "А", "offset_mm": 250, "toward": "Б"},
                     {"grid": " А "}):
            with self.subTest(line=line):
                point, diags, _r = _resolve({"at_grid": [line, "1"]}, pool)
                self.assertEqual(diags, [])
                self.assertIsNotNone(point)

    def test_short_form_is_byte_identical_to_contour(self):
        """The key is deliberately the same: one grammar for two places."""
        pool = _orthogonal_pool()
        new, diags, _r = _resolve({"at_grid": ["А", "1"]}, pool)
        old_diags: list = []
        old = contour.resolve_anchor({"at_grid": ["А", "1"]}, pool,
                                     "op1", "origin", old_diags)
        self.assertEqual((diags, old_diags), ([], []))
        self.assertEqual(new, old)

    def test_composition_is_unexpressible(self):
        """Neither "midpoint between," nor "parallel to," nor "plus" — the
        registry of forms is CLOSED, and the failure prints the registry
        itself."""
        pool = _orthogonal_pool()
        for line in ({"between": ["А", "Б"]},
                     {"grid": "А", "plus": "Б"},
                     {"parallel_to": "А", "offset_mm": 100},
                     {"grid": "А", "offset_mm": 100, "toward": "Б", "extra": 1}):
            with self.subTest(line=line):
                point, diags, _r = _resolve({"at_grid": [line, "1"]}, pool)
                self.assertIsNone(point)
                self.assertEqual(_codes(diags), ["KIR-T001"])

    def test_offset_and_toward_are_a_pair(self):
        pool = _orthogonal_pool()
        _p, d1, _ = _resolve({"at_grid": [{"grid": "А", "offset_mm": 100}, "1"]},
                             pool)
        _p, d2, _ = _resolve({"at_grid": [{"grid": "А", "toward": "Б"}, "1"]},
                             pool)
        self.assertEqual(_codes(d1), ["KIR-T001"])
        self.assertIn("toward", d1[0].message_ru)
        self.assertEqual(_codes(d2), ["KIR-T001"])
        self.assertIn("offset_mm", d2[0].message_ru)

    def test_zero_offset_is_refused_as_a_second_spelling(self):
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 0, "toward": "Б"}, "1"]},
            _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-T002"])

    def test_offset_bound_is_the_move_elements_bound(self):
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 100_001, "toward": "Б"},
                         "1"]}, _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-T002"])

    def test_at_grid_needs_exactly_two_lines(self):
        for value in (["А"], ["А", "1", "2"], [], "А"):
            with self.subTest(value=value):
                point, diags, _r = _resolve({"at_grid": value},
                                            _orthogonal_pool())
                self.assertIsNone(point)
                self.assertEqual(_codes(diags), ["KIR-T001"])

    def test_name_bounds(self):
        for name in ("", "   ", "x" * 65, 3, None):
            with self.subTest(name=name):
                point, diags, _r = _resolve({"at_grid": [name, "1"]},
                                            _orthogonal_pool())
                self.assertIsNone(point)
                self.assertEqual(_codes(diags), ["KIR-T001"])

    def test_toward_cannot_be_its_own_grid(self):
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 100, "toward": " А "},
                         "1"]}, _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-T001"])

    def test_z_is_required_in_xyz_and_forbidden_in_xy(self):
        pool = _orthogonal_pool()
        _p, d_missing, _ = _resolve({"at_grid": ["А", "1"]}, pool, dims=3)
        _p, d_extra, _ = _resolve({"at_grid": ["А", "1"], "z_mm": 3000}, pool,
                                  dims=2)
        self.assertEqual(_codes(d_missing), ["KIR-T001"])
        self.assertIn("z_mm", d_missing[0].message_ru)
        self.assertEqual(_codes(d_extra), ["KIR-T001"])
        point, diags, _r = _resolve({"at_grid": ["А", "1"], "z_mm": 3000},
                                    pool, dims=3)
        self.assertEqual(diags, [])
        self.assertEqual(point, [0.0, 0.0, 3000.0])


# ── RESOLUTION FROM THE SNAPSHOT ────────────────────────────────────────────

class Resolution(unittest.TestCase):

    def test_missing_name_names_the_next_move(self):
        point, diags, _r = _resolve({"at_grid": ["В", "1"]}, _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G108"])
        self.assertIn("query_list", diags[0].message_ru)
        self.assertTrue(diags[0].candidates)

    def test_truncated_pool_says_so(self):
        _p, diags, _ = _resolve({"at_grid": ["В", "1"]}, _orthogonal_pool(),
                                truncated=True)
        self.assertEqual(_codes(diags), ["KIR-G108"])
        self.assertIn("обрезан", diags[0].message_ru)

    def test_empty_pool_is_a_different_repair(self):
        point, diags, _r = _resolve({"at_grid": ["А", "1"]}, [])
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G104"])
        self.assertIn("create_grid", diags[0].message_ru)

    def test_grid_without_straight_geometry(self):
        pool = _orthogonal_pool() + [{"id": 9, "name": "R", "is_curved": True}]
        point, diags, _r = _resolve({"at_grid": ["R", "1"]}, pool)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G111"])
        self.assertIn("дуговая", diags[0].message_ru)

    def test_toward_must_be_parallel(self):
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 200, "toward": "1"}, "1"]},
            _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G112"])
        self.assertEqual(diags[0].candidates, ["Б"])

    def test_toward_perpendicular_but_drawn_entirely_on_one_side(self):
        """THE NASTIEST case, and it was found by a perturbing oracle: an
        intersecting axis DRAWN entirely on one side. The "endpoints on
        opposite sides" check misses it, and only the parallelism
        threshold catches it — without it, "toward" would be computed from
        a line that actually intersects its own axis beyond the edge of
        the drawing."""
        pool = _orthogonal_pool() + [
            {"id": 5, "name": "К", "p0_mm": [1000, 2000], "p1_mm": [1000, 9000]}]
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 200, "toward": "К"}, "1"]},
            pool)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G112"])
        self.assertIn("не параллельна", diags[0].message_ru)

    def test_toward_with_no_parallel_neighbour_at_all(self):
        pool = [
            {"id": 1, "name": "А", "p0_mm": [0, -5000], "p1_mm": [0, 25000]},
            {"id": 3, "name": "1", "p0_mm": [-5000, 0], "p1_mm": [30000, 0]},
        ]
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 200, "toward": "1"}, "1"]},
            pool)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G112"])
        self.assertEqual(diags[0].candidates, [])
        self.assertIn("нет ни одной параллельной соседки",
                      diags[0].message_ru)
        self.assertIn("литералом [x, y]", diags[0].message_ru)

    def test_all_refusals_arrive_in_one_round(self):
        """SPEC 12.7: three invalid names -> three failures in one move."""
        program = {
            "ir_version": "1.0", "ops": [
                {"op": "create_column", "id": f"c{i}",
                 "level": {"by": "name", "value": "Этаж 1"},
                 "symbol": {"by": "name", "value": "К 300x300"},
                 "xy": {"at_grid": [name, "1"]}}
                for i, name in enumerate(("Ж", "З", "И"))]}
        out = compile_program(program, "2026", snapshot=_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics],
                         ["KIR-G108"] * 3)

    def test_receipt_names_every_line(self):
        _p, diags, receipt = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 250, "toward": "Б"}, "1"]},
            _orthogonal_pool())
        self.assertEqual(diags, [])
        self.assertEqual(len(receipt), 1)
        text = relate.describe_receipt_ru(receipt)[0]
        self.assertIn("«А» (id 902)", text)
        self.assertIn("250 мм в сторону «Б»", text)
        self.assertIn("[0, 250]", text)


# ── WHERE THE ADDRESS IS RESOLVED ───────────────────────────────────────────

_SNAPSHOT = GROUND_SNAPSHOT


class WhereAddressesAreAllowed(unittest.TestCase):

    def _compile(self, ops, snapshot=None):
        return compile_program({"ir_version": "1.0", "ops": ops}, "2026",
                               snapshot=_SNAPSHOT if snapshot is None
                               else snapshot)

    def test_wall_from_grid_to_grid(self):
        """"a wall from axis 1 to axis 2 along axis A" — TWO addresses,
        there is no new grammar for this form (spec §2.4/R2)."""
        out = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": {"at_grid": ["А", "1"]},
            "p1_mm": {"at_grid": ["А", "2"]}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 0, 0)", out.csharp)
        self.assertIn("P(4000, 0, 0)", out.csharp)

    def test_column_on_an_intersection(self):
        out = self._compile([{
            "op": "create_column", "id": "c1",
            "level": {"by": "name", "value": "Этаж 1"},
            "symbol": {"by": "name", "value": "К 300x300"},
            "xy": {"at_grid": ["Б", "2"]}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(4000, 4500, 0)", out.csharp)

    def test_column_with_an_offset_from_a_grid(self):
        """The main form (R3): ON THE AXIS with an offset, the side named
        by a neighbor."""
        out = self._compile([{
            "op": "create_column", "id": "c2",
            "level": {"by": "name", "value": "Этаж 1"},
            "symbol": {"by": "name", "value": "К 300x300"},
            "xy": {"at_grid": [{"grid": "А", "offset_mm": 200,
                                "toward": "Б"}, "1"]}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 200, 0)", out.csharp)

    def test_beam_needs_z_and_gets_it(self):
        out = self._compile([{
            "op": "create_beam", "id": "b1",
            "level": {"by": "name", "value": "Этаж 1"},
            "symbol": {"by": "name", "value": "Балка 200x400"},
            "p0_mm": {"at_grid": ["А", "1"], "z_mm": 3000},
            "p1_mm": {"at_grid": ["А", "2"], "z_mm": 3000}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

    def test_addressed_and_literal_programs_emit_the_same_csharp(self):
        """Spec V3: the same program, written with addresses and with
        literals, must produce BYTE-IDENTICAL C#."""
        literal = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": [0, 0], "p1_mm": [4000, 0]}])
        addressed = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": {"at_grid": ["А", "1"]},
            "p1_mm": {"at_grid": ["А", "2"]}}])
        self.assertTrue(literal.ok and addressed.ok,
                        [d.as_dict() for d in
                         (literal.diagnostics + addressed.diagnostics)])
        # THE DIFFERENCE IS EXACTLY ONE AND IT IS NAMED: the program stamp
        # is a digest of the AUTHOR'S text, and the texts are honestly
        # different (that is the whole point of an address). Everything
        # else — create, post, witness — must match byte for byte.
        stamp = re.compile(r"kir:[0-9a-f]+:")
        self.assertNotEqual(literal.csharp, addressed.csharp)
        self.assertEqual(stamp.sub("kir:<stamp>:", literal.csharp),
                         stamp.sub("kir:<stamp>:", addressed.csharp))

    def test_delta_mm_is_not_addressable(self):
        """An offset is not a position; an address there is meaningless."""
        out = self._compile([{
            "op": "move_elements", "id": "m1",
            "targets": [{"by": "element_id", "value": 777},
                        {"by": "element_id", "value": 778}],
            "delta_mm": {"at_grid": ["А", "1"], "z_mm": 0}}])
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics], ["KIR-T001"])

    def test_face_normal_direction_is_not_addressable(self):
        """The intersection of axes is a point, but face_normal sets a
        direction."""
        self.assertNotIn(
            "face_normal", relate.addressable_params("create_face_wall"))
        out = self._compile([{
            "op": "create_face_wall", "id": "fw1",
            "host": {"by": "element_id", "value": 900001},
            "type": {"by": "name", "value": "Кирпич 250"},
            "face_normal": {
                "at_grid": ["А", "1"], "z_mm": 3000},
            "location_line": "core_exterior"}])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_no_snapshot_is_the_ground_code(self):
        out = compile_program({"ir_version": "1.0", "ops": [{
            "op": "create_column", "id": "c1",
            "level": {"by": "element_id", "value": 42},
            "symbol": {"by": "element_id", "value": 500},
            "xy": {"at_grid": ["А", "1"]}}]}, "2026", snapshot=None)
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics], ["KIR-G103"])

    def test_registry_is_the_only_judge_of_where(self):
        """The list of places is NOT maintained by hand: it is derived
        from the parameter's kind."""
        from kir import spec
        derived = {(n, p.name) for n, o in spec.OPS.items() for p in o.params
                   if p.kind in ("pt_xy", "pt_xyz")}
        allowed = {(n, p) for n in spec.OPS
                   for p in relate.addressable_params(n)}
        self.assertEqual(derived - allowed, relate.ADDRESS_EXCLUDED)

    def test_arc_and_address_do_not_mix(self):
        out = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": {"at_grid": ["А", "1"]},
            "p1_mm": {"at_grid": ["А", "2"]},
            "arc": {"curve_type": "Arc", "center_mm": [3000, 0, 0],
                    "radius_mm": 3000, "x_axis": [1, 0, 0], "y_axis": [0, 1, 0],
                    "start_angle_rad": 0.0, "end_angle_rad": 3.14159}}])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_zero_length_is_still_caught_after_resolution(self):
        """The law "length ~0" moved past the snapshot boundary together
        with the address, and was not lost."""
        out = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": {"at_grid": ["А", "1"]},
            "p1_mm": {"at_grid": ["А", "1"]}}])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_half_resolved_pair_keeps_its_typed_refusal(self):
        """A REFUTING TEST for a defect found on 2026-08-09 on top of
        `2bfbec0a`, and NOT related to an address from an element: when
        ONE end is addressed correctly and the other points to a
        nonexistent axis, the second law-checking site received an
        address object where it expected a list, and the whole program
        answered "KIR-P000 internal compiler error: KeyError". The honest
        KIR-G108 "the axis is not in the model" was ALREADY sitting in the
        diagnostics by that point and simply never reached the author —
        that is, a failure with a named next move was replaced by the
        message "fix the compiler."""
        out = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "p0_mm": {"at_grid": ["НЕТ ТАКОЙ", "А"]},
            "p1_mm": {"at_grid": ["2", "А"]}}])
        self.assertFalse(out.ok)
        codes = [d.code for d in out.diagnostics]
        self.assertIn(relate.GRID_NOT_FOUND, codes)
        self.assertNotIn("KIR-P000", codes)

    def test_hosted_offset_law_survives_an_addressed_host(self):
        """A door beyond the edge of an addressed wall must fail the same
        way as beyond the edge of a literal one — otherwise the
        instrument covers only part of the range."""
        ops = [
            {"op": "create_wall", "id": "w1",
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"},
             "height_mm": 3000,
             "p0_mm": {"at_grid": ["А", "1"]},
             "p1_mm": {"at_grid": ["А", "2"]}},
            {"op": "create_door", "id": "d1",
             "host": {"by": "ref", "value": "w1"},
             "symbol": {"by": "name", "value": "Дверь 900x2100"},
             "offset_mm": 9000},
        ]
        out = self._compile(ops)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])


# ── MACROS: an address is not carried by a geometric transform ─────────────

class MacrosAndAddresses(unittest.TestCase):

    def test_stack_transform_refuses_an_address(self):
        """`stack.transform` rotates and narrows the plan. An address
        cannot be rotated: an axis does not move because of it. Passing
        this silently would mean putting every floor at the same point."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "stack", "id": "s", "levels": 3, "h_mm": 3000,
            "transform": {"twist_deg_total": 5.0},
            "floor": [{"op": "create_column", "id": "c",
                       "symbol": {"by": "name", "value": "К 300x300"},
                       "xy": {"at_grid": ["А", "1"]}}]}]}
        out = compile_program(program, "2026", snapshot=_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("stack.transform", out.diagnostics[0].message_ru)

    def test_stack_without_transform_keeps_the_address(self):
        program = {"ir_version": "1.0", "ops": [{
            "op": "stack", "id": "s", "levels": 2, "h_mm": 3000,
            "floor": [{"op": "create_column", "id": "c",
                       "symbol": {"by": "name", "value": "К 300x300"},
                       "xy": {"at_grid": ["А", "1"]}}]}]}
        out = compile_program(program, "2026", snapshot=_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])


# ── ADDRESS FROM AN ELEMENT ─────────────────────────────────────────────────
#
# THE BOUNDARY OF THIS INSTRUMENT, IN WORDS. Exactly one thing is proved
# here: that the number the compiler DERIVED from the address matches,
# byte for byte, the number the author would have computed by hand — and
# that every case where it cannot honestly be derived ends in a TYPED
# refusal with a named next move. NOTHING is proved about the live model:
# whether a column landed at its elevation is checked by the op's witness,
# not this file.

_L2_ELEV = 3300   # the elevation of "Floor 2" in the fixture


def _columns(top: bool = True) -> list:
    """Two columns at grid intersections, with the top tied to the second
    floor."""
    out = []
    for oid, grid in (("C1", "1"), ("C2", "2")):
        op = {"op": "create_column", "id": oid,
              "xy": {"at_grid": [grid, "А"]},
              "level": {"by": "name", "value": "Этаж 1"},
              "symbol": {"by": "name", "value": "К 300x300"}}
        if top:
            op["top_level"] = {"by": "name", "value": "Этаж 2"}
        out.append(op)
    return out


def _beam_on_columns() -> dict:
    return {"op": "create_beam", "id": "B1",
            "p0_mm": {"at_element": {"by": "ref", "value": "C1"},
                      "point": "center", "z": "top"},
            "p1_mm": {"at_element": {"by": "ref", "value": "C2"},
                      "point": "center", "z": "top"},
            "level": {"by": "name", "value": "Этаж 2"},
            "symbol": {"by": "name", "value": "Балка 200x400"}}


class ElementAddressResolves(unittest.TestCase):
    """What an address from an element GIVES — and that it is exactly the
    same numbers."""

    def _compile(self, ops, snapshot=None, version="2026"):
        return compile_program({"ir_version": "1.0", "ops": ops}, version,
                               snapshot=_SNAPSHOT if snapshot is None
                               else snapshot)

    def test_beam_on_top_of_columns(self):
        """THE MAIN CASE: a beam across the top of two columns. Not a
        single number about the beam's position is in the program — the
        compiler derived all three."""
        out = self._compile(_columns() + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(
            "Line.CreateBound(P(0, 0, 3300), P(4000, 0, 3300))", out.csharp)

    def test_addressed_and_hand_computed_emit_the_same_csharp(self):
        """Spec V3 for the second family: a program where the model
        computed the coordinates BY HAND, and a program where the compiler
        derived them, must produce BYTE-IDENTICAL C# — otherwise the
        address changes not the number's provenance, but the number
        itself."""
        by_hand = dict(_beam_on_columns(),
                       p0_mm=[0, 0, _L2_ELEV], p1_mm=[4000, 0, _L2_ELEV])
        literal = self._compile(_columns() + [by_hand])
        addressed = self._compile(_columns() + [_beam_on_columns()])
        self.assertTrue(literal.ok and addressed.ok,
                        [d.as_dict() for d in
                         (literal.diagnostics + addressed.diagnostics)])
        # The difference is exactly one and it is named: the program stamp
        # is a digest of the AUTHOR'S text, and the texts are honestly
        # different (that is the whole point of an address).
        stamp = re.compile(r"kir:[0-9a-f]+:")
        self.assertNotEqual(literal.csharp, addressed.csharp)
        self.assertEqual(stamp.sub("kir:<stamp>:", literal.csharp),
                         stamp.sub("kir:<stamp>:", addressed.csharp))

    def test_no_trigonometry_reaches_the_emitted_csharp(self):
        """Not a single trigonometric function and not a single read of a
        level's elevation for the sake of the address: everything is
        computed at compile time."""
        out = self._compile(_columns() + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        for token in ("Math.Sin", "Math.Cos", "Math.Atan", "Math.Sqrt"):
            self.assertNotIn(token, out.csharp)

    def test_the_chain_grid_then_element(self):
        """The column is addressed FROM THE AXES, the beam FROM THE
        COLUMN. The chain is held together by grounding order, not by a
        separate check."""
        out = self._compile(_columns() + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        rules = {row["rule"] for row in out.grounding_report}
        self.assertEqual(rules, {"at_grid", "at_element"})

    def test_per_op_address_keeps_the_runtime_dependency_gate(self):
        """GROUND replaces the address with a number, but the dependency
        does not disappear: if the column is rejected within its own
        SubTransaction, the beam must not be built separately from
        already-computed coordinates of a nonexistent support."""
        out = compile_program(
            {"ir_version": "1.0", "ops": _columns() + [_beam_on_columns()]},
            "2026", snapshot=_SNAPSHOT, isolation="per_op")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(
            'if (!__ok_C1) throw __OpRefuse("B1", '
            '"опорный оп «C1» отказан — оп пропущен");', out.csharp)
        self.assertIn(
            'if (!__ok_C2) throw __OpRefuse("B1", '
            '"опорный оп «C2» отказан — оп пропущен");', out.csharp)

    def test_the_receipt_names_the_summands(self):
        """The receipt must show the ARITHMETIC that the compiler took
        upon itself: the level's elevation and the offset, separately. A
        derivation that cannot be shown to anyone is indistinguishable
        from a `.FirstOrDefault()` in a costume."""
        from kir.ground import describe_choices_ru
        out = self._compile(_columns() + [_beam_on_columns()])
        text = describe_choices_ru(out.grounding_report)
        self.assertIn("«C1» (create_column) → center", text)
        self.assertIn("отметка top = 3300 + 0 мм", text)
        self.assertIn("[0, 0, 3300]", text)

    def test_the_receipt_formats_a_negative_offset_as_subtraction(self):
        from kir.ground import describe_choices_ru
        ops = _columns()
        for op in ops:
            op["top_offset_mm"] = -400
        out = self._compile(ops + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        text = describe_choices_ru(out.grounding_report)
        self.assertIn("отметка top = 3300 − 400 мм", text)
        self.assertNotIn("+ -400", text)

    def test_top_offset_rides_the_elevation(self):
        ops = _columns()
        for op in ops:
            op["top_offset_mm"] = -200
        out = self._compile(ops + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 0, 3100)", out.csharp)

    def test_base_reads_the_level_and_its_offset(self):
        ops = _columns()
        for op in ops:
            op["base_offset_mm"] = 150
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center", "z": "base"}
        beam["p1_mm"] = {"at_element": {"by": "ref", "value": "C2"},
                         "point": "center", "z": "base"}
        out = self._compile(ops + [beam])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("Line.CreateBound(P(0, 0, 150), P(4000, 0, 150))",
                      out.csharp)

    def test_slanted_column_top_uses_top_xy_and_is_byte_equivalent(self):
        """In the current registry, a column has `top_xy`. Taking the
        bottom `xy` when z=top is a silent plan-view miss, even though the
        beam's elevation and witness are correct."""
        column = {
            "op": "create_column", "id": "C1", "xy": [0, 0],
            "top_xy": [1000, 500],
            "level": {"by": "name", "value": "Этаж 1"},
            "top_level": {"by": "name", "value": "Этаж 2"},
            "symbol": {"by": "name", "value": "К 300x300"}}
        beam = {
            "op": "create_beam", "id": "B1",
            "p0_mm": {"at_element": {"by": "ref", "value": "C1"},
                      "point": "center", "z": "top"},
            "p1_mm": [4000, 500, _L2_ELEV],
            "level": {"by": "name", "value": "Этаж 2"},
            "symbol": {"by": "name", "value": "Балка 200x400"}}
        addressed = self._compile([column, beam])
        literal = self._compile([
            column, dict(beam, p0_mm=[1000, 500, _L2_ELEV])])
        self.assertTrue(addressed.ok and literal.ok,
                        [d.as_dict() for d in
                         (addressed.diagnostics + literal.diagnostics)])
        self.assertIn(
            "Line.CreateBound(P(1000, 500, 3300), P(4000, 500, 3300))",
            addressed.csharp)
        stamp = re.compile(r"kir:[0-9a-f]+:")
        self.assertEqual(stamp.sub("kir:<stamp>:", addressed.csharp),
                         stamp.sub("kir:<stamp>:", literal.csharp))

    def test_wall_end_feeds_the_next_wall(self):
        """A flat parameter: a wall junction without rewriting the
        coordinate."""
        out = self._compile([
            {"op": "create_wall", "id": "W1",
             "p0_mm": {"at_grid": ["А", "1"]},
             "p1_mm": {"at_grid": ["А", "2"]},
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_wall", "id": "W2",
             "p0_mm": {"at_element": {"by": "ref", "value": "W1"},
                       "point": "end"},
             "p1_mm": [4000, 4500],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(
            "Line.CreateBound(P(4000, 0, 0), P(4000, 4500, 0))", out.csharp)

    def test_center_of_a_wall(self):
        out = self._compile([
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [4000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_column", "id": "C9",
             "xy": {"at_element": {"by": "ref", "value": "W1"},
                    "point": "center"},
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "К 300x300"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(2000, 0, 0)", out.csharp)

    def test_axis_elevation_of_a_beam(self):
        """For a volumetric axis, the station elevation lives in the
        program itself."""
        out = self._compile([
            {"op": "create_beam", "id": "B0",
             "p0_mm": [0, 0, 3000], "p1_mm": [4000, 0, 3500],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}},
            {"op": "create_beam", "id": "B1",
             "p0_mm": {"at_element": {"by": "ref", "value": "B0"},
                       "point": "end", "z": "axis"},
             "p1_mm": [8000, 0, 3500],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(4000, 0, 3500)", out.csharp)

    def test_z_mm_is_the_third_way_to_name_an_elevation(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center", "z_mm": 5000}
        beam["p1_mm"] = {"at_element": {"by": "ref", "value": "C2"},
                         "point": "center", "z_mm": 5000}
        out = self._compile(_columns() + [beam])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("Line.CreateBound(P(0, 0, 5000), P(4000, 0, 5000))",
                      out.csharp)

    def test_level_built_by_this_same_program(self):
        """The elevation of a level created by THIS SAME program is taken
        from the program itself — the snapshot knows nothing about such a
        level and cannot know."""
        out = self._compile([
            {"op": "create_level", "id": "L9", "elev_mm": 7200,
             "name": "Этаж 9"},
            {"op": "create_column", "id": "C1", "xy": [0, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "top_level": {"by": "ref", "value": "L9"},
             "symbol": {"by": "name", "value": "К 300x300"}},
            {"op": "create_beam", "id": "B1",
             "p0_mm": {"at_element": {"by": "ref", "value": "C1"},
                       "point": "center", "z": "top"},
             "p1_mm": [4000, 0, 7200],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 0, 7200)", out.csharp)


class ElementAddressRefusesLoudly(unittest.TestCase):
    """Every case where a number cannot honestly be derived is a TYPED
    refusal with a NAMED next move. A silent zero here would be more
    expensive than a refusal: the witness checks the element against that
    same zero and would let it through."""

    def _compile(self, ops, snapshot=None):
        return compile_program({"ir_version": "1.0", "ops": ops}, "2026",
                               snapshot=_SNAPSHOT if snapshot is None
                               else snapshot)

    def _codes(self, out) -> list:
        return [d.code for d in out.diagnostics]

    def test_existing_model_element_is_refused_with_the_measured_reason(self):
        """MEASURED, NOT A MATTER OF TASTE: the ground snapshot has not a
        single row of geometry for an existing element, so `element_id` is
        rejected."""
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "element_id", "value": 12345},
                         "point": "center", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", self._codes(out))
        message = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("levels, load_cases, grids", message)

    def test_forward_reference_refuses_offline(self):
        """A forward reference is a pure function of the text, and the
        refusal must arrive WITHOUT a snapshot: this is exactly the DAG
        walk for whose sake the edge was pulled out of the value's depth."""
        out = compile_program(
            {"ir_version": "1.0", "ops": [_beam_on_columns()] + _columns()},
            "2026", snapshot=None)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", self._codes(out))

    def test_a_room_is_refused_by_name_with_its_reason(self):
        """An empty table row would send the author guessing — so every
        rejected kind has a REASON, and it is in the refusal."""
        out = self._compile([
            {"op": "create_room", "id": "R1", "xy": [1000, 1000],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_column", "id": "C1",
             "xy": {"at_element": {"by": "ref", "value": "R1"},
                    "point": "center"},
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "К 300x300"}}])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_NOT_ADDRESSABLE, self._codes(out))
        self.assertIn("ТОЧКА ПОСЕВА",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_top_without_top_level_refuses_and_names_the_move(self):
        """Without a top tie, the height arrives from a DEFAULT the author
        never stated — exactly the defect that used to roll back correct
        facade walls."""
        out = self._compile(_columns(top=False) + [_beam_on_columns()])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(out))
        self.assertIn("допишите top_level",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_a_point_element_has_no_start(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "start", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(out))

    def test_slanted_column_refuses_an_ambiguous_plan_station(self):
        """Without z=base|top, a sloped axis has two honestly plan-view
        points; `center` grants no right to silently pick the lower one."""
        source = {
            "op": "create_column", "id": "C1", "xy": [0, 0],
            "top_xy": [1000, 500],
            "level": {"by": "name", "value": "Этаж 1"},
            "top_level": {"by": "name", "value": "Этаж 2"},
            "symbol": {"by": "name", "value": "К 300x300"}}
        follower = {
            "op": "create_column", "id": "C2",
            "xy": {"at_element": {"by": "ref", "value": "C1"},
                   "point": "center"},
            "level": {"by": "name", "value": "Этаж 1"},
            "symbol": {"by": "name", "value": "К 300x300"}}
        out = self._compile([source, follower])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(out))
        self.assertIn("наклонная (`top_xy` задан)",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_a_grid_has_no_elevation(self):
        out = self._compile([
            {"op": "create_grid", "id": "G1", "p0_mm": [0, 0],
             "p1_mm": [0, 9000], "name": "Ф"},
            {"op": "create_beam", "id": "B1",
             "p0_mm": {"at_element": {"by": "ref", "value": "G1"},
                       "point": "start", "z": "base"},
             "p1_mm": [4000, 0, 3000],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}}])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(out))

    def test_a_grid_built_here_can_still_feed_a_plan_point(self):
        """The flip side of the same thing: an axis created by THIS SAME
        program cannot be addressed by `at_grid` (the snapshot was taken
        earlier) — but `at_element` can, because it reads the program."""
        out = self._compile([
            {"op": "create_grid", "id": "G1", "p0_mm": [0, 0],
             "p1_mm": [0, 9000], "name": "Ф"},
            {"op": "create_column", "id": "C1",
             "xy": {"at_element": {"by": "ref", "value": "G1"},
                    "point": "start"},
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "К 300x300"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 0, 0)", out.csharp)

    def test_arc_wall_has_no_center(self):
        """The midpoint of the CHORD lies outside an arc wall — silently
        returning it would mean missing by more, the sharper the curve."""
        arc = {"curve_type": "Arc", "center_mm": [2000, 0, 0],
               "radius_mm": 2000, "x_axis": [1, 0, 0], "y_axis": [0, 1, 0],
               "start_angle_rad": 0.0, "end_angle_rad": 3.14159}
        base = {"op": "create_wall", "id": "W1",
                "p0_mm": [4000, 0], "p1_mm": [0, 0], "arc": arc,
                "level": {"by": "name", "value": "Этаж 1"},
                "type": {"by": "name", "value": "ЖБ 200"}}
        follower = {"op": "create_column", "id": "C1",
                    "level": {"by": "name", "value": "Этаж 1"},
                    "symbol": {"by": "name", "value": "К 300x300"}}
        refused = self._compile([base, dict(
            follower, xy={"at_element": {"by": "ref", "value": "W1"},
                          "point": "center"})])
        self.assertFalse(refused.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(refused))
        # And the endpoints of an arc wall are honest:
        # `materialize._reconcile_arc_endpoints` derives p0/p1 FROM THE
        # ARC ITSELF.
        allowed = self._compile([base, dict(
            follower, xy={"at_element": {"by": "ref", "value": "W1"},
                          "point": "end"})])
        self.assertTrue(allowed.ok, [d.as_dict() for d in allowed.diagnostics])

    def test_capture_gap_is_named_not_zeroed(self):
        """A level row WITHOUT elevation_mm is a CAPTURE gap, not a zero.
        A substituted zero would place the beam at the model's zero
        elevation and would pass the witness, which checks against that
        same zero."""
        snapshot = dict(_SNAPSHOT)
        snapshot["levels"] = [{"id": row["id"], "name": row["name"]}
                              for row in _SNAPSHOT["levels"]]
        out = self._compile(_columns() + [_beam_on_columns()],
                            snapshot=snapshot)
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_CAPTURE_GAP, self._codes(out))
        self.assertIn("пробел ЗАХВАТА",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_zero_length_law_reaches_the_element_address(self):
        """A beam "from C1 to C1" is zero length, and the law must carry
        through past the snapshot boundary together with the address (an
        instrument covering only part of the range is more dangerous than
        none at all)."""
        beam = dict(_beam_on_columns())
        beam["p1_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", self._codes(out))

    def test_z_and_z_mm_together_are_two_answers_to_one_question(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center", "z": "top", "z_mm": 1000}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("Отметка названа ДВАЖДЫ",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_a_flat_parameter_refuses_an_elevation(self):
        out = self._compile([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [4000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_wall", "id": "W2",
             "p0_mm": {"at_element": {"by": "ref", "value": "W1"},
                       "point": "end", "z": "base"},
             "p1_mm": [4000, 4500],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}}])
        self.assertFalse(out.ok)
        self.assertIn("отметка здесь лишняя",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_a_volumetric_parameter_demands_an_elevation(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("допишите z",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_unknown_key_prints_the_closed_grammar(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "part": "center", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        message = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("Грамматика ЗАКРЫТА", message)
        self.assertIn('"point": "start|end|center"', message)

    def test_unknown_point_name_prints_the_closed_vocabulary(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "middle", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("['start', 'end', 'center']",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_inside_a_stack_the_reference_resolves_PER_STOREY(self):
        """🔴 A FOSSIL REWRITTEN ON 2026-08-15 — THE SUBJECT CHANGED, NOT
        THE THRESHOLD.

        The test used to claim: "`stack` renames ops per floor and does
        NOT rewrite references — it is checked that this is LOUD," and
        expected `KIR-L003`. The typical-floor wave (`0efcb2b0`) taught
        the expansion to REWRITE references, and the claim stopped being
        true about the code: the program below is now legal.

        Canon form 9 in pure form — nobody mutates prose, so the test
        survived the behavior change and only went red on a full run. It
        could not be deleted: it has a SURVIVING subject, and it is
        checked here — a reference inside a set must resolve PER FLOOR,
        not to the first floor.

        What is checked is REFERENCE RESOLUTION, not that the program
        compiled: "it compiled" does not distinguish the correct floor
        from the first one.
        """
        floor = [
            {"op": "create_column", "id": "c", "xy": [0, 0],
             "symbol": {"by": "name", "value": "К 300x300"}},
            {"op": "create_beam", "id": "b",
             "p0_mm": {"at_element": {"by": "ref", "value": "c"},
                       "point": "center", "z_mm": 3000},
             "p1_mm": [4000, 0, 3000],
             "symbol": {"by": "name", "value": "Балка 200x400"}},
        ]
        ops = macros._expand_stack(
            {"op": "stack", "id": "s", "levels": 2, "h_mm": 3000,
             "floor": floor})

        beams = [o for o in ops if o["op"] == "create_beam"]
        self.assertEqual(len(beams), 2, "экспансия не дала по балке на этаж — "
                                        "контроль вырожден, сравнивать нечего")
        for beam in beams:
            with self.subTest(beam=beam["id"]):
                ref = beam["p0_mm"]["at_element"]["value"]
                storey = beam["id"].rsplit("_", 1)[0]      # 's_L2_b' -> 's_L2'
                self.assertEqual(
                    ref, f"{storey}_c",
                    "балка адресует колонну ЧУЖОГО этажа — ровно тот молчаливо "
                    "неверный исход, ради запрета которого ссылки переписываются")

    def test_a_reference_OUT_of_the_stack_is_still_refused_loudly(self):
        """The second half, without which the first is worth nothing.

        Only a reference to a MEMBER of the set can be rewritten. A
        reference pointing outward cannot be rewritten by construction,
        and it must remain a LOUD refusal — otherwise a hosted op on every
        floor would hang onto the very same foreign element, and that
        would be a silent falsehood.
        """
        with self.assertRaises(Exception) as caught:
            macros._expand_stack(
                {"op": "stack", "id": "s", "levels": 2, "h_mm": 3000,
                 "floor": [{"op": "create_door", "id": "d",
                            "host": {"by": "ref", "value": "outsider"},
                            "offset_mm": 1000}]})
        text = str(caught.exception)
        self.assertIn("KIR-M001", text)
        self.assertIn("outsider", text,
                      "отказ обязан НАЗВАТЬ хозяина, которого не нашёл")


    def test_a_contour_corner_says_why_the_element_address_is_not_taken(self):
        """A slot, not a syntax error: the form is correct, but the
        contour is lowered into edges BEFORE the program grounds. A
        generic "unknown point form" would send the author to fix
        something that is not broken."""
        out = self._compile([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [4000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_floor_by_contour", "id": "F1",
             "level": {"by": "name", "value": "Этаж 1"},
             "contour": {"outer": {
                 "shape": "rect",
                 "origin": {"at_element": {"by": "ref", "value": "W1"},
                            "point": "start"},
                 "size_mm": [4000, 3000]}}}])
        self.assertFalse(out.ok)
        self.assertIn("контур опускается в рёбра",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_the_grid_resolver_stays_total(self):
        """`resolve_address` accepts an address from grid axes; an address
        from an element handed to it must be a TYPED refusal, not a
        KeyError — otherwise the refusal is again replaced by "internal
        compiler error."""
        diags: list = []
        point = relate.resolve_address(
            {"at_element": {"by": "ref", "value": "C1"}, "point": "center"},
            _orthogonal_pool(), "op1", "xy", diags, dims=2)
        self.assertIsNone(point)
        self.assertEqual([d.code for d in diags], ["KIR-T001"])

    def test_the_element_resolver_stays_total(self):
        """The symmetric seam: a grid address handed to the element
        resolver must fail in a typed way, not crash inside `at_element`."""
        diags: list = []
        point = relate.resolve_element_address(
            {"at_grid": ["А", "1"]}, {}, [], "op1", "xy", diags, dims=2)
        self.assertIsNone(point)
        self.assertEqual([d.code for d in diags], ["KIR-T001"])


class ElementAddressRegistriesAreClosed(unittest.TestCase):
    """Locks on the registries themselves. A registry that stops matching
    the code turns a closed grammar into a list of good intentions."""

    def test_every_rejected_op_carries_a_reason(self):
        for name, why in relate.ELEMENT_REJECTED.items():
            self.assertTrue(isinstance(why, str) and len(why) > 40,
                            f"{name}: причина отказа пуста или формальна")

    def test_allowed_and_rejected_do_not_overlap(self):
        self.assertFalse(
            set(relate.ELEMENT_GEOMETRY) & set(relate.ELEMENT_REJECTED))

    def test_every_addressable_source_is_decided_one_way_or_the_other(self):
        """An op that has a point parameter MUST be either addressable or
        named among the rejected. A silent third bucket is exactly that
        "empty table row" that leaves the author guessing."""
        from kir import spec
        undecided = sorted(
            name for name in spec.OPS
            if relate.addressable_params(name)
            and name not in relate.ELEMENT_GEOMETRY
            and name not in relate.ELEMENT_REJECTED)
        self.assertEqual(undecided, [])

    def test_non_geometric_point_fields_are_rejected_by_name(self):
        """Three new point-like kinds — trace/axis/direction — are not
        body coordinates. They must stay in the explicit rejection
        bucket, otherwise the next registry wave will again offer them up
        as addressable geometry."""
        cases = {
            "create_extrusion_roof": "СЛЕД РАБОЧЕЙ ПЛОСКОСТИ",
            "create_solid_revolve": "ОСЬ ВРАЩЕНИЯ",
            "create_face_wall": "НАПРАВЛЕНИЕ",
        }
        for name, evidence in cases.items():
            self.assertIn(name, relate.ELEMENT_REJECTED)
            self.assertIn(evidence, relate.ELEMENT_REJECTED[name])

            diags: list = []
            point = relate.resolve_element_address(
                {"at_element": {"by": "ref", "value": "X"},
                 "point": "center"},
                {"X": {"op": name}}, [], "follow", "xy", diags, dims=2)
            self.assertIsNone(point)
            self.assertEqual([d.code for d in diags],
                             [relate.ELEMENT_NOT_ADDRESSABLE])
            self.assertIn(evidence, diags[0].message_ru)

    def test_the_grammar_has_no_binary_node(self):
        """There is no composition here either: a node has EXACTLY ONE
        selector, so "midpoint between A and B" is unexpressible by
        construction, not by prohibition."""
        for keys in relate.ELEMENT_ADDRESS_FORMS:
            self.assertEqual(
                sum(1 for k in keys if k == "at_element"), 1)
            self.assertFalse({"at_grid", "between", "plus"} & set(keys))


if __name__ == "__main__":
    unittest.main()
