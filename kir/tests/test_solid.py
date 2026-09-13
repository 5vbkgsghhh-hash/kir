"""wave/solid — the parametric solid: closed-form measures, emission, vacuity.

WHAT THIS SUITE PROVES, AND WHAT IT DOES NOT.

Proves offline:
  * closed-form contour measures AGREE WITH AN INDEPENDENT INSTRUMENT (a dense
    polygonal sampling) — that is, the reference the witness checks against
    is computed correctly;
  * the witness READS GEOMETRY, not a constant: touch the profile or the height —
    the reference in the emitted C# must move;
  * the witness CAN FAIL: the substitution we actually care about (a vanished opening,
    the wrong height, a revolution that did not close) is, in magnitude, provably larger than the tolerance —
    and this is PROVEN, not simulated, because the runtime vacuity ban
    guarantees `tolerance < the smallest declared part`;
  * prohibitions: a contour crossing the axis, an impostor category, an absence that is itself absent.

Does NOT prove, and cannot prove offline: that Revit will build exactly this solid
and that `Solid.Volume` will match the reference to within the derived tolerance.
This is the first live run; the receipt carries the raw expectation/measurement pair
precisely so that it can MEASURE the remainder, rather than merely estimate it.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_solid_queue.jsonl"))

from kir import contour as C                                  # noqa: E402
from kir import spec                                          # noqa: E402
from kir.authoring import _EMITTERS                           # noqa: E402
from kir.compiler import compile_program                      # noqa: E402
from kir.emit_model import post_to_string                     # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT                # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")


def _prog(*ops, intent="тело"):
    return {"ir_version": "1.0", "intent": intent, "ops": list(ops)}


def _extrusion(**over):
    op = {"op": "create_solid_extrusion", "id": "SX",
          "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                "size_mm": [4000, 3000]}},
          "height_mm": 2500, "category": "generic_model", "name": "призма"}
    op.update(over)
    return op


def _revolve(**over):
    op = {"op": "create_solid_revolve", "id": "SR",
          "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                "size_mm": [800, 2400]}},
          "axis_xy_mm": [0, 0], "sweep_deg": 360,
          "category": "generic_model", "name": "кольцо"}
    op.update(over)
    return op


def _emit(op, ver="2023"):
    """(decl, create, post-as-C#, readback) of a single op after grounding."""
    grounded = _ground(op)
    decl, create, checks, readback = _EMITTERS[op["op"]](
        grounded, ver, "kir:test")
    return decl, create, post_to_string(op["id"], checks), readback


def _ground(op):
    from kir import ground as ground_mod
    from kir.compiler import _parse_and_check
    return ground_mod.ground(_parse_and_check(_prog(op)), GROUND_SNAPSHOT)[0]


def _num_after(text: str, pattern: str) -> float:
    m = re.search(pattern, text)
    assert m is not None, f"в эмиссии нет {pattern!r}:\n{text}"
    return float(m.group(1))


# ── 1. CLOSED-FORM MEASURES AGAINST AN INDEPENDENT INSTRUMENT ──────────────────────────


def _expects_bbox(cs: str, axis: str, lo: float, hi: float) -> bool:
    """Whether the witness prints the expectation per axis — independent of the SHAPE of the check.

    🔴 INTRODUCED ON 21.08 AFTER THREE REDS THAT HAD STOOD SINCE 19.08. The tests below
    pinned down the LETTERS of the generated C#: `Math.Abs(MM(...Min.X) - 0.0)`.
    The `_bbox_check` rewrite on 19.08 changed the shape to a two-sided inequality
    with a DIFFERENT tolerance outward and inward — the check became stricter, and the tests
    went red and stayed red, because they were asking about the text, not
    the meaning.

    Here it is the meaning that is asked: the witness must NAME the boundary per axis.
    The expectation string ("expected X 0.0..1800.0") is printed by the
    witness itself into the refusal message, so what is checked is exactly what
    the author will actually read.
    """
    return f"{axis} {lo}..{hi}" in cs


class ClosedFormsAgreeWithSampling(unittest.TestCase):
    """The witness's reference is computed as an integral over the boundary. It is checked against a
    DIFFERENT instrument — a dense polygonal sampling — because checking a formula against
    itself means checking a variable against itself.

    The 1e-6 threshold was not picked by eye: the sampling's own error at N chords is
    O(1/N²), which at N=4000 is 6e-8, and the observed discrepancy must be of that
    order. The threshold is more than an order of magnitude above what is observed, and orders of
    magnitude below any meaningful formula error.
    """

    SHAPES = {
        "rect": {"shape": "rect", "origin": [1000, 2000],
                 "size_mm": [3000, 4000]},
        "rect_rotated": {"shape": "rect", "origin": [1000, 2000],
                         "size_mm": [3000, 4000], "rotation_deg": 37},
        "l_shape": {"shape": "l", "origin": [500, 500], "size_mm": [4000, 5000],
                    "cut_mm": [1500, 2000], "corner": "ne"},
        "triangle": {"shape": "poly",
                     "points_mm": [[1000, 0], [5000, 0], [3000, 4000]]},
        "arc_out": {"shape": "poly",
                    "points_mm": [[1000, 0], [5000, 0], [5000, 3000],
                                  [1000, 3000]],
                    "arcs": [{"edge": 2, "bulge": 0.6}]},
        "arc_in": {"shape": "poly",
                   "points_mm": [[1000, 0], [5000, 0], [5000, 3000],
                                 [1000, 3000]],
                   "arcs": [{"edge": 2, "bulge": -0.6}]},
        "two_arcs": {"shape": "poly",
                     "points_mm": [[1200, 100], [6000, 0], [6000, 3000],
                                   [1000, 3400]],
                     "arcs": [{"edge": 0, "bulge": -0.35},
                              {"edge": 2, "bulge": 0.9}]},
        # A CLOCKWISE traversal: CONTOUR accepts both orientations, and measures must
        # normalize by the sign of their own area, not by faith in the winding order.
        "clockwise": {"shape": "poly",
                      "points_mm": [[1000, 0], [3000, 4000], [5000, 0]]},
    }
    N_CHORDS = 4000

    def _dense(self, edges):
        poly = []
        for p0, p1, bulge in edges:
            if abs(bulge) < 1e-9:
                poly.append(list(p0))
                continue
            (cx, cy), r, a0, sweep = C._arc_geometry(p0, p1, bulge)
            for k in range(self.N_CHORDS):
                a = a0 + sweep * k / self.N_CHORDS
                poly.append([cx + r * math.cos(a), cy + r * math.sin(a)])
        area = moment = length = x_ds = 0.0
        n = len(poly)
        for k in range(n):
            ax, ay = poly[k]
            bx, by = poly[(k + 1) % n]
            area += 0.5 * (ax * by - ay * bx)
            moment += (by - ay) * (ax * ax + ax * bx + bx * bx) / 6.0
            d = math.hypot(bx - ax, by - ay)
            length += d
            x_ds += d * (ax + bx) / 2.0
        return area, moment, length, x_ds

    def test_area_moment_length_and_pappus_integral_match_dense_sampling(self):
        worst = 0.0
        for name, shape in sorted(self.SHAPES.items()):
            diags = []
            edges = C._validate_shape(shape, [], "T", "profile", diags)
            self.assertIsNotNone(edges, f"{name}: {diags}")
            closed = C.loop_measures(edges)
            sampled = self._dense(edges)
            for label, a, b in zip(("area", "moment", "length", "x_ds"),
                                   closed, sampled):
                with self.subTest(shape=name, measure=label):
                    rel = abs(a - b) / max(1e-9, abs(b))
                    worst = max(worst, rel)
                    self.assertLess(rel, 1e-6)
        # The number is RECORDED, not merely checked: the next wave should be able to see
        # by which instrument, and to what agreement, the reference was obtained.
        self.assertLess(worst, 1e-6, f"худшее относительное расхождение {worst:.2e}")

    def test_analytic_values_are_exact_on_shapes_with_known_answers(self):
        """Where the answer is known from a textbook formula, it matches exactly."""
        rect = C._validate_shape(self.SHAPES["rect"], [], "T", "p", [])
        area, moment, length, _ = C.loop_measures(rect)
        self.assertAlmostEqual(area, 3000.0 * 4000.0, places=6)
        self.assertAlmostEqual(length, 2 * (3000.0 + 4000.0), places=6)
        # The centroid of a rectangle spanning 1000..4000 on x is exactly 2500.
        self.assertAlmostEqual(moment / area, 2500.0, places=6)

    def test_holes_are_subtracted_exactly(self):
        region = C.validate_region(
            {"outer": {"shape": "rect", "origin": [0, 0],
                       "size_mm": [4000, 3000]},
             "holes": [{"shape": "rect", "origin": [1000, 1000],
                        "size_mm": [1000, 1000]}]},
            [], "T", "profile", [])
        m = C.region_measures(region)
        self.assertAlmostEqual(m["area_mm2"], 4000 * 3000 - 1000 * 1000,
                               places=6)
        # The perimeter is the FULL length of the boundary: an opening also contributes a lateral surface.
        self.assertAlmostEqual(m["perimeter_mm"], 14000.0 + 4000.0, places=6)
        self.assertAlmostEqual(m["min_area_mm2"], 1000.0 * 1000.0, places=6)


# ── 2. THE WITNESS READS GEOMETRY, NOT A CONSTANT ───────────────────────────

_EXPECTED_VOLUME = r"__vmm_\w+ - ([\d.e+-]+)\)"
_EXPECTED_CAP = r"__rcap_\w+ - ([\d.e+-]+)\)"
_VOL_TOL_FACTOR = r"__tvol_\w+ = ([\d.e+-]+) \* __dt_"
_CAP_TOL_FACTOR = r"__tcap_\w+ = ([\d.e+-]+) \* __dt_"
_VOL_VACUITY = r"if \(__tvol_\w+ >= ([\d.e+-]+)\)"
_CAP_VACUITY = r"if \(__tcap_\w+ >= ([\d.e+-]+)\)"


class TheWitnessReadsTheGeometry(unittest.TestCase):
    """A perturbation oracle: touch the input — the reference in the C# MUST move.

    This is the same technique `test_tolerance_provenance` uses to catch a decorative
    `tol_key`. A witness that compares against a number that does not depend on the geometry
    would pass any ordinary test and prove nothing at all.
    """

    def test_extrusion_volume_is_area_times_height(self):
        _d, _c, post, _r = _emit(_extrusion())
        self.assertAlmostEqual(_num_after(post, _EXPECTED_VOLUME),
                               4000.0 * 3000.0 * 2500.0, places=3)

    def test_changing_the_height_moves_the_expected_volume(self):
        _d, _c, a, _r = _emit(_extrusion())
        _d, _c, b, _r = _emit(_extrusion(height_mm=2501))
        self.assertNotEqual(_num_after(a, _EXPECTED_VOLUME),
                            _num_after(b, _EXPECTED_VOLUME))

    def test_adding_a_hole_moves_both_expected_volume_and_cap_area(self):
        holed = _extrusion(profile={
            "outer": {"shape": "rect", "origin": [0, 0], "size_mm": [4000, 3000]},
            "holes": [{"shape": "rect", "origin": [1000, 1000],
                       "size_mm": [1000, 1000]}]})
        _d, _c, plain, _r = _emit(_extrusion())
        _d, _c, with_hole, _r = _emit(holed)
        self.assertAlmostEqual(
            _num_after(with_hole, _EXPECTED_VOLUME),
            (4000.0 * 3000.0 - 1000.0 * 1000.0) * 2500.0, places=3)
        self.assertLess(_num_after(with_hole, _EXPECTED_VOLUME),
                        _num_after(plain, _EXPECTED_VOLUME))
        self.assertLess(_num_after(with_hole, _EXPECTED_CAP),
                        _num_after(plain, _EXPECTED_CAP))

    def test_an_arc_moves_the_expected_volume_off_the_polygon_answer(self):
        """An arc must be treated as an arc, not as a chord: otherwise the closed-form measure
        would be decorative, and the witness would be checking a polygon instead."""
        straight = _extrusion(profile={"outer": {
            "shape": "poly",
            "points_mm": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}})
        curved = _extrusion(profile={"outer": {
            "shape": "poly",
            "points_mm": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
            "arcs": [{"edge": 1, "bulge": 0.5}]}})
        _d, _c, sp, _r = _emit(straight)
        _d, _c, cp, _r = _emit(curved)
        self.assertGreater(_num_after(cp, _EXPECTED_VOLUME),
                           _num_after(sp, _EXPECTED_VOLUME) * 1.05)

    def test_revolve_volume_is_sweep_times_first_moment(self):
        """A ring of radii 1000..1800, height 2400, a full revolution.

        An independent check with the textbook formula: V = π(R²−r²)h.
        """
        _d, _c, post, _r = _emit(_revolve())
        got = _num_after(post, _EXPECTED_VOLUME)
        want = math.pi * (1800.0 ** 2 - 1000.0 ** 2) * 2400.0
        self.assertAlmostEqual(got / want, 1.0, places=9)

    def test_half_turn_is_half_the_volume(self):
        _d, _c, full, _r = _emit(_revolve())
        _d, _c, half, _r = _emit(_revolve(sweep_deg=180))
        self.assertAlmostEqual(_num_after(half, _EXPECTED_VOLUME) * 2.0,
                               _num_after(full, _EXPECTED_VOLUME), places=3)

    def test_moving_the_axis_further_out_grows_the_volume(self):
        """The same profile farther from the axis sweeps a larger volume — the witness
        must see this, otherwise it would be checking an area, not a solid."""
        near = _emit(_revolve())[2]
        far = _emit(_revolve(profile={
            "outer": {"shape": "rect", "origin": [5000, 0],
                      "size_mm": [800, 2400]}}))[2]
        self.assertGreater(_num_after(far, _EXPECTED_VOLUME),
                           _num_after(near, _EXPECTED_VOLUME) * 3.0)

    def test_full_turn_expects_no_caps_and_a_sector_expects_two(self):
        full = _emit(_revolve())[2]
        sector = _emit(_revolve(sweep_deg=90))[2]
        self.assertEqual(_num_after(full, _EXPECTED_CAP), 0.0)
        self.assertAlmostEqual(_num_after(sector, _EXPECTED_CAP),
                               2.0 * 800.0 * 2400.0, places=3)


# ── 3. A MUTATION PROOF: THE WITNESS CAN FAIL ──────────────

class TheWitnessCanFail(unittest.TestCase):
    """A check that cannot fail is worse than no check at all.

    A PROOF, NOT A SIMULATION. The tolerance is computed at runtime from
    `VertexTolerance`, which does not exist offline, so plugging in a
    plausible δ here would mean inventing a number. Instead, what is used is
    something the emission GUARANTEES on its own: right next to the witness stands a runtime refusal,
    `if (tolerance >= the smallest declared part)`. So on every run that
    survives to reach the witness, the tolerance is STRICTLY LESS than that value — and any
    substitution of that size is guaranteed to be caught, whatever δ turns out to be.
    """

    def _numbers(self, op):
        _d, create, post, _r = _emit(op)
        return {
            "expected_volume": _num_after(post, _EXPECTED_VOLUME),
            "expected_cap": _num_after(post, _EXPECTED_CAP),
            "vol_tol_factor": _num_after(create, _VOL_TOL_FACTOR),
            "cap_tol_factor": _num_after(create, _CAP_TOL_FACTOR),
            "vol_vacuity": _num_after(create, _VOL_VACUITY),
            "cap_vacuity": _num_after(create, _CAP_VACUITY),
        }

    def test_the_vacuity_refusal_is_emitted_for_both_witnesses(self):
        for op in (_extrusion(), _revolve()):
            with self.subTest(op=op["op"]):
                _d, create, _p, _r = _emit(op)
                self.assertIn("__tvol_", create)
                self.assertRegex(create, _VOL_VACUITY)
                self.assertRegex(create, _CAP_VACUITY)
                self.assertIn("проверка не смогла бы провалиться", create)

    def test_an_ignored_hole_exceeds_every_admissible_tolerance(self):
        """The quietest of the plausible failures: Revit ignored the inner
        loop and filled in the opening. The volume is then larger by the volume of the opening, and this
        volume is exactly the vacuity threshold, below which the tolerance never falls."""
        op = _extrusion(profile={
            "outer": {"shape": "rect", "origin": [0, 0], "size_mm": [4000, 3000]},
            "holes": [{"shape": "rect", "origin": [1000, 1000],
                       "size_mm": [1000, 1000]}]})
        n = self._numbers(op)
        hole_volume = 1000.0 * 1000.0 * 2500.0
        # The vacuity threshold is the volume of the smallest declared part, and it equals
        # the volume of the opening (the opening is smaller than the rest of the profile).
        self.assertAlmostEqual(n["vol_vacuity"], hole_volume, places=3)
        # On every run that survives to reach the witness, tolerance < this threshold,
        # so a discrepancy the size of the opening is STRICTLY larger than the tolerance.
        self.assertGreaterEqual(hole_volume, n["vol_vacuity"])
        # And the same holds for the end caps: a filled-in opening adds 2·the opening's area.
        self.assertAlmostEqual(n["cap_vacuity"], 2.0 * 1000.0 * 1000.0,
                               places=3)

    def test_a_one_percent_error_is_caught_for_every_admissible_delta(self):
        """The height missed by one percent — is that caught ALWAYS?

        A profile with no openings is weakly protected by the vacuity ban (the smallest
        declared part there is the solid itself), so here a SECOND, independent boundary is
        at work, and it too is derived, not assigned.

        The witness fires when |Δ| > surface·δ, so an error Δ is caught
        when δ < Δ/surface. On the other hand δ is bounded FROM ABOVE by our own
        laws: `contour._EDGE_TOL` = 1 mm — the minimum edge length that
        CONTOUR will ever let out, while `VertexTolerance`, by
        definition, is the distance at which two points COINCIDE. Were it
        no less than a millimeter, a legal CONTOUR edge would be, to Revit,
        degenerate, and the profile would not build at all. So on any
        document where our profiles ACTUALLY BUILD, δ < 1 mm + the emission quantum.

        The test compares two quantities: the threshold on δ at which a one-percent
        error is still caught must be NOTICEABLY above this boundary.
        """
        max_delta = C._EDGE_TOL + C.EMIT_COORD_QUANTUM_MM
        for op in (_extrusion(), _revolve()):
            with self.subTest(op=op["op"]):
                n = self._numbers(op)
                caught_while_delta_below = (
                    0.01 * n["expected_volume"] / n["vol_tol_factor"])
                self.assertGreater(
                    caught_while_delta_below, max_delta,
                    f"допуск съедает процент объёма уже при δ="
                    f"{caught_while_delta_below:.3f} мм, а δ может доходить "
                    f"до {max_delta} мм — свидетель слеп к процентной ошибке")

    def test_a_sector_built_instead_of_a_full_turn_is_caught_by_the_caps(self):
        """The most likely failure of a full revolution: Revit assembled a wedge.
        The expected end-cap area is then 0, while the measured one is 2·A."""
        n = self._numbers(_revolve())
        self.assertEqual(n["expected_cap"], 0.0)
        wedge_caps = 2.0 * 800.0 * 2400.0
        self.assertAlmostEqual(n["cap_vacuity"], wedge_caps, places=3)
        self.assertGreaterEqual(wedge_caps, n["cap_vacuity"])

    def test_deleting_a_witness_makes_the_certificate_refuse(self):
        """A direct mutation of the emission: cut out the verdict — the certificate must fail.

        This is the strong form (the same one as law L6 in test_tolerance_provenance):
        an audit by wording would not have noticed such an edit.
        """
        from kir import translation_cert as cert
        from kir.emit_model import WitnessCheck

        for raw in (_extrusion(), _revolve()):
            grounded = _ground(raw)
            name = raw["op"]
            real = _EMITTERS[name]
            for ver in ("2021", "2026"):
                self.assertTrue(cert.certify_op(grounded, ver).proven,
                                f"{name}/{ver} не заверяется даже целым")
                _d, _c, checks, _r = real(grounded, ver, "kir:test")
                for victim in checks:
                    key = victim.obligation_key

                    def excised(o, v, stamp, isolation="atomic",
                                _r=real, _k=key):
                        d, c, post, rb = _r(o, v, stamp, isolation)
                        kept = [x for x in post if x.obligation_key != _k]
                        if not kept:
                            kept = [WitnessCheck(
                                obligation_key="__excised__", reader_cs="",
                                verdict_cs='    if (false) __post.Add("");\n',
                                message="excised", style="guard")]
                        return d, c, kept, rb

                    with self.subTest(op=name, ver=ver, witness=key):
                        _EMITTERS[name] = excised
                        try:
                            still = cert.certify_op(grounded, ver).proven
                        finally:
                            _EMITTERS[name] = real
                        self.assertFalse(
                            still,
                            f"вырезан свидетель {key}, а сертификат всё ещё "
                            f"proven — обязательство декоративно")


# ── 4. PROHIBITIONS, REFUSALS, AND ABSENCE ─────────────────────────────────────────

class RefusalsAndAbsence(unittest.TestCase):

    def test_a_profile_crossing_the_axis_is_refused_by_name(self):
        out = compile_program(
            _prog(_revolve(profile={
                "outer": {"shape": "rect", "origin": [-500, 0],
                          "size_mm": [800, 2400]}})),
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(any("за ось" in (d.message_ru or "")
                            for d in out.diagnostics), out.diagnostics)

    def test_impersonation_categories_name_the_honest_op(self):
        from kir.ops_shape import IMPERSONATION_ROUTES

        for barred, honest in sorted(IMPERSONATION_ROUTES.items()):
            for op in (_extrusion(category=barred), _revolve(category=barred)):
                with self.subTest(category=barred, op=op["op"]):
                    out = compile_program(_prog(op), revit_version="2023",
                                          snapshot=GROUND_SNAPSHOT)
                    self.assertFalse(out.ok)
                    self.assertTrue(
                        any(honest in (d.message_ru or "")
                            for d in out.diagnostics),
                        f"отказ не назвал {honest}: "
                        f"{[d.message_ru for d in out.diagnostics]}")

    def test_the_registry_bars_the_same_categories_as_the_mesh(self):
        """ONE table, not a copy: removing a prohibition in one file and missing it
        in a second is exactly the class of defect this table is imported to prevent."""
        from kir.ops_shape import DIRECTSHAPE_CATEGORIES

        for name in ("create_solid_extrusion", "create_solid_revolve"):
            with self.subTest(op=name):
                choices = {p.name: p.choices
                           for p in spec.OPS[name].params}["category"]
                self.assertEqual(set(choices), set(DIRECTSHAPE_CATEGORIES))

    def test_absent_base_z_emits_no_transform_at_all(self):
        """Absence stays absence: without `base_z_mm` there is not a single
        contour transform in the emission, not a transform by zero."""
        _d, without, _p, _r = _emit(_extrusion())
        _d, with_z, _p, _r = _emit(_extrusion(base_z_mm=3300))
        self.assertNotIn("CreateViaTransform", without)
        self.assertIn("CreateViaTransform", with_z)
        self.assertIn("U(3300.0)", with_z)

    def test_base_z_moves_the_expected_bbox_in_z_only(self):
        _d, _c, flat, _r = _emit(_extrusion())
        _d, _c, lifted, _r = _emit(_extrusion(base_z_mm=3300))
        self.assertTrue(_expects_bbox(flat, "Z", 0.0, 2500.0), flat[-400:])
        self.assertTrue(_expects_bbox(lifted, "Z", 3300.0, 5800.0),
                        lifted[-400:])
        # a shift ONLY along Z: the plan boundaries must coincide
        self.assertTrue(_expects_bbox(flat, "X", 0.0, 4000.0), flat[-400:])
        self.assertTrue(_expects_bbox(lifted, "X", 0.0, 4000.0), lifted[-400:])

    def test_a_grid_anchored_profile_resolves_and_demands_a_snapshot(self):
        """A LEFTOVER FIX FOUND BY THIS WAVE. `ground._needs_pool` was holding a
        hard-coded parameter NAME (`contour`) where the neighboring line had already
        moved to a KIND. The solid's profile is called `profile`, and before the fix
        binding it to axes had not required a snapshot: the `grids` pool arrived empty,
        and the refusal named "axes not found" instead of "no snapshot" — a repair aimed at
        the wrong spot. Both ends are checked here: with axes it builds; without a snapshot,
        the refusal is ABOUT THE SNAPSHOT."""
        op = _extrusion(profile={"outer": {
            "shape": "poly",
            "points_mm": [{"at_grid": ["1", "А"]}, {"at_grid": ["2", "А"]},
                          {"at_grid": ["2", "Б"]}, {"at_grid": ["1", "Б"]}]}})
        out = compile_program(_prog(op), revit_version="2023",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, out.diagnostics)
        # Grids 1/2 (x=0/4000) and A/B (y=0/4500) give a rectangle 4000×4500,
        # i.e. an area of 18,000,000 mm² and a volume of 45,000,000,000 mm³ —
        # numbers that could ONLY have appeared if the grid pool was actually
        # read.
        self.assertIn("__rb[\"profile_area_mm2\"] = 18000000.0;", out.csharp)
        self.assertIn("__vmm_SX - 45000000000.0", out.csharp)

        blind = compile_program(_prog(op), revit_version="2023")
        self.assertFalse(blind.ok)
        self.assertTrue(any("снапшот" in (d.message_ru or "")
                            for d in blind.diagnostics), blind.diagnostics)

    def test_neither_op_grounds_anything_and_neither_carries_a_registry_tolerance(self):
        """Both facts are substantive, not vacuous: DirectShape has no type
        (nothing to prime), and the tolerance here is a function of the op's
        geometry and Revit's own number, not a registry constant."""
        for name in ("create_solid_extrusion", "create_solid_revolve"):
            with self.subTest(op=name):
                self.assertEqual(spec.OPS[name].grounded, ())
                self.assertEqual(spec.OPS[name].tolerances, {})
                self.assertEqual(spec.OPS[name].capability,
                                 (("create", "geometry"),))

    def test_the_receipt_carries_the_raw_pair_the_live_run_must_measure(self):
        for op in (_extrusion(), _revolve()):
            with self.subTest(op=op["op"]):
                _d, _c, _p, readback = _emit(op)
                for field in ("volume_mm3_expected", "volume_mm3_measured",
                              "volume_tolerance_mm3", "cap_area_mm2_expected",
                              "cap_area_mm2_measured", "vertex_tolerance_mm",
                              "bim_semantics", "has_type",
                              "schedulable_as_building_element"):
                    self.assertIn(field, readback)

    def test_the_sector_bbox_is_the_swept_annulus_not_the_profile(self):
        """The ring's bounding box is a 2R square, not the profile's strip:
        the body sweeps the plane entirely. A witness that took the
        profile's bounding box would be certifying geometry that does not
        exist."""
        _d, _c, post, _r = _emit(_revolve())
        self.assertTrue(_expects_bbox(post, "X", -1800.0, 1800.0), post[-400:])
        self.assertTrue(_expects_bbox(post, "Y", -1800.0, 1800.0), post[-400:])

    def test_a_quarter_turn_bbox_keeps_the_inner_radius(self):
        """A quarter turn: along x from the inner radius to the outer, and
        the same along y. The cardinal directions do not fall inside the
        sector."""
        _d, _c, post, _r = _emit(_revolve(sweep_deg=90))
        self.assertTrue(_expects_bbox(post, "X", 0.0, 1800.0), post[-400:])
        self.assertTrue(_expects_bbox(post, "Y", 0.0, 1800.0), post[-400:])


# ── 5. SIX VERSIONS ─────────────────────────────────────────────────────────

class SixVersionsEmitTheSameSurface(unittest.TestCase):
    """There is NO version axis for these ops — the whole of
    GeometryCreationUtilities is byte-identical across 2021-2026 (measured by
    compilation, table in the ops_solid.py header). This is PINNED DOWN here:
    a divergence in emission between versions would mean someone introduced a
    branch and did not say so."""

    def test_emission_is_identical_across_all_six(self):
        for op in (_extrusion(), _revolve(), _extrusion(base_z_mm=1000)):
            emissions = {ver: _emit(op, ver) for ver in VERSIONS}
            first = emissions["2021"]
            for ver in VERSIONS[1:]:
                with self.subTest(op=op["op"], ver=ver):
                    self.assertEqual(emissions[ver], first)

    def test_the_program_compiles_on_every_version(self):
        """This checks only that the COMPILER does not refuse; that the C#
        builds under Roslyn on all six versions is the gate's job, not this
        suite's."""
        for op in (_extrusion(), _revolve()):
            for ver in VERSIONS:
                with self.subTest(op=op["op"], ver=ver):
                    out = compile_program(_prog(op), revit_version=ver,
                                          snapshot=GROUND_SNAPSHOT)
                    self.assertTrue(out.ok, out.diagnostics)


if __name__ == "__main__":
    unittest.main()
