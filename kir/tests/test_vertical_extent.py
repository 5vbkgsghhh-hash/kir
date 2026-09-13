"""COLUMN VERTICALITY: the reference was checked, the GEOMETRY was not.

THE DEFECT THIS FILE GREW OUT OF (live benchmark 2026-08-18, Revit 2023).
Sonnet ran a shift on KIR and built a terraced office tower. All the planar
geometry came out clean — a 7x5 grid at 6000 exactly, 35 XY positions
exactly, setbacks along the axes exactly. All three major failures turned
out to be VERTICAL, and the most telling one:

    420 columns landed at 2500 mm instead of 3600-4500. Not one refusal.
    The witness signed off, the acceptance accepted, THREE audits saw
    nothing.

The cause is not in the model but in how the obligations are built.
`create_column` had eight of them, and three touched verticality:

    top_constraint  FAMILY_TOP_LEVEL_PARAM points at the intended level
    top_offset      the offset equals what was sent    — CONDITIONAL on top_offset_mm
    base_offset     the bottom offset equals what was sent

The first reads where the parameter POINTS. None of them reads whether the
BODY ACTUALLY REACHES where the reference points. And the top-tie
obligation is CONDITIONAL: the author omitted `top_level` — it simply never
ran, and the height silently came from the symbol's default. This is a LIVE
INSTANCE OF A SILENTLY-WRONG OUTCOME, forbidden by the mission forever.

WHY THE GUARD IS ONE-SIDED, AND THIS IS A MEASUREMENT, NOT CAUTION.
`__post.Count > 0` leads to `__t.RollBack()`. So equality on a quantity
nobody here has ever measured live would roll back CORRECT buildings —
exactly the mistake `create_beam` already paid for ("a requirement of
equality was rolling back CORRECTLY built ones," measured 07.27). The
observed defect gives a dimension SHORTER than derived, by 1100 mm; a
family whose geometry legitimately overhangs the tie gives LONGER.
So only a shortfall is checked.

WHAT THIS GUARD DOES NOT CATCH — named, not forgotten:

  * a column WITHOUT `top_level`. The dimension is not derived from the
    program at all, and the obligation stays conditional. This case is not
    spoken to by the witness but by the declaration
    `ParamSpec.omission_transfers` on `create_column.top_level` (08.19) —
    the `kir/kir_plan.py` rehearsal prints it LOUDLY, apart from the noise
    of optional decorations;
  * an OVERSHOOT of the dimension. One-sided by construction, see above;
  * a SLANTED column. Its top is set by the axis, and it is already
    checked by its own witness ("column axis not by levels");
  * the 300 mm tolerance value: it is CHOSEN, not measured. What was
    measured is the miss (1100 mm). To be refined by the first live run on
    a real family.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_vextent_queue.jsonl"))

from kir import authoring                                  # noqa: E402
from kir import spec                                       # noqa: E402
from kir import translation_cert as tc                     # noqa: E402
import dataclasses                                             # noqa: E402

from kir.emit_model import BarePost                        # noqa: E402

_L3 = {"__grounded__": {"id": 42, "name": "Этаж 3", "via": "element_id"}}
_L4 = {"__grounded__": {"id": 43, "name": "Этаж 4", "via": "element_id"}}
_SYM = {"__grounded__": {"id": 901, "name": "К400", "via": "element_id"}}


def _column(**over):
    op = {"op": "create_column", "id": "C1", "xy": [0, 0],
          "category": "structural", "level": _L3, "symbol": _SYM,
          "top_level": _L4}
    op.update(over)
    return op


def _emit(op, ver="2026"):
    decl, create, post, readback = authoring._EMITTERS["create_column"](
        op, ver, "kir:test")
    checks = list(post.checks) if isinstance(post, BarePost) else list(post)
    return decl, create, checks, readback


def _mutate(key, verdict_cs=None):
    """Cut out (verdict_cs=None) or replace the verdict of witness ``key``."""
    original = authoring._EMITTERS["create_column"]

    def broken(op, ver, stamp, isolation="atomic", _o=original):
        decl, create, post, readback = _o(op, ver, stamp, isolation)
        bare = isinstance(post, BarePost)
        checks = list(post.checks) if bare else list(post)
        out = []
        for check in checks:
            if check.obligation_key != key:
                out.append(check)
            elif verdict_cs is not None:
                out.append(dataclasses.replace(check, verdict_cs=verdict_cs))
        return decl, create, (post.__class__(tuple(out)) if bare else out), readback

    authoring._EMITTERS["create_column"] = broken
    return original


class TheObligationExists(unittest.TestCase):
    def test_registry_declares_the_vertical_extent_obligation(self) -> None:
        keys = [o.key for o in tc._ensure_table()["create_column"].obligations]
        self.assertIn("vertical_extent", keys)

    def test_it_is_geometry_not_topology(self) -> None:
        # The whole point: three neighboring obligations already read a
        # REFERENCE (topology). One more topological check would add
        # nothing.
        ob = next(o for o in tc._ensure_table()["create_column"].obligations
                  if o.key == "vertical_extent")
        self.assertEqual(ob.kind, tc.KIND_GEOMETRY)

    def test_it_is_gated_on_top_level_and_skipped_for_a_slanted_column(self) -> None:
        ob = next(o for o in tc._ensure_table()["create_column"].obligations
                  if o.key == "vertical_extent")
        self.assertTrue(ob.conditional)
        self.assertEqual(ob.param, "top_level")
        self.assertEqual(ob.unless_param, "top_xy")

    def test_the_tolerance_lives_in_the_registry(self) -> None:
        self.assertEqual(
            spec.OPS["create_column"].tolerances["vertical_span_mm"], 300.0)

    def test_the_omission_is_declared_on_the_param_not_left_to_prose(self) -> None:
        # The second carrier: the witness stays silent when top_level is
        # omitted, so the omission must be spoken to by the field's
        # DECLARATION, not a comment.
        ps = next(p for p in spec.OPS["create_column"].params
                  if p.name == "top_level")
        self.assertTrue(ps.omission_transfers)
        self.assertEqual(ps.authority, "AUTHORED")


class TheEmittedGuard(unittest.TestCase):
    def test_the_expected_extent_is_derived_from_the_two_levels(self) -> None:
        decl, create, _checks, _rb = _emit(_column())
        self.assertIn("double __vexLo_C1", decl)
        self.assertIn("double __vexHi_C1", decl)
        self.assertIn("__vexLo_C1 = MM(__lv_C1.Elevation)", create)
        self.assertIn("__vexHi_C1 = MM(__ctl_C1.Elevation)", create)

    def test_offsets_move_the_derived_extent(self) -> None:
        _d, create, _c, _rb = _emit(_column(base_offset_mm=300,
                                            top_offset_mm=-200))
        self.assertIn("__vexLo_C1 = MM(__lv_C1.Elevation) + 300", create)
        self.assertIn("__vexHi_C1 = MM(__ctl_C1.Elevation) + -200", create)

    def test_the_guard_is_one_sided(self) -> None:
        # If `Math.Abs` ever lands here, the guard becomes two-sided and
        # starts rolling back buildings on a family that overhangs the tie.
        _d, _c, checks, _rb = _emit(_column())
        v = next(c for c in checks if c.obligation_key == "vertical_extent")
        self.assertIn("__vexGot_C1 < __vexWant_C1 - 300.0", v.verdict_cs)
        self.assertNotIn("Math.Abs", v.verdict_cs)

    def test_a_slanted_column_gets_no_extent_guard(self) -> None:
        _d, _c, checks, _rb = _emit(_column(top_xy=[1000, 500]))
        self.assertNotIn("vertical_extent",
                         [c.obligation_key for c in checks])

    def test_without_top_level_nothing_is_derived(self) -> None:
        op = _column()
        del op["top_level"]
        decl, _c, checks, _rb = _emit(op)
        self.assertNotIn("__vexLo_C1", decl)
        self.assertNotIn("vertical_extent",
                         [c.obligation_key for c in checks])


class TheReceiptCarriesTheNumber(unittest.TestCase):
    def test_it_returns_both_the_expected_and_the_realised_elevation(self) -> None:
        # Exactly what the 420 columns lacked: the author had NOTHING to
        # check against.
        _d, _c, _checks, readback = _emit(_column())
        self.assertIn("vertical_extent_expected_mm", readback)
        self.assertIn("vertical_extent_mm", readback)
        self.assertIn("__vexLo_C1", readback)

    def test_the_receipt_cannot_roll_anything_back(self) -> None:
        # The receipt goes out AFTER the commit. So it can safely name a
        # quantity for which equality would be dangerous.
        _d, _c, _checks, readback = _emit(_column())
        self.assertNotIn("__post", readback)

    def test_a_column_without_a_top_constraint_reports_no_extent(self) -> None:
        op = _column()
        del op["top_level"]
        _d, _c, _checks, readback = _emit(op)
        self.assertNotIn("vertical_extent_mm", readback)


class MutationMustBeRefused(unittest.TestCase):
    """A witness that cannot be made to fail is not a witness."""

    def test_baseline_is_proven(self) -> None:
        # The foundation of the whole mutation. Without it, the tests below
        # would pass for the wrong reason.
        self.assertTrue(tc.certify_op(_column(), "2026").proven)

    def test_cutting_the_extent_witness_breaks_the_certificate(self) -> None:
        original = _mutate("vertical_extent")
        try:
            cert = tc.certify_op(_column(), "2026")
        finally:
            authoring._EMITTERS["create_column"] = original
        self.assertFalse(cert.proven, "вырезанный сторож оставил сертификат доказанным")
        gaps = "\n".join(cert.gaps).lower()
        self.assertIn("built solid spans at least base..top elevation", gaps)
        self.assertIn("vertical_extent", gaps)

    def test_a_vacuous_extent_witness_breaks_the_certificate(self) -> None:
        # A form from test_witness_vacuity: the line exists, it cannot fail.
        # The tolerance INSIDE the seedling is kept deliberately — otherwise
        # the tolerance-provenance guard (the test below) fires first, and
        # the vacuum would stay unchecked.
        original = _mutate(
            "vertical_extent",
            '    if (false) {\n'
            '        if (__vexGot_C1 < __vexWant_C1 - 300.0)\n'
            '            __post.Add("never");\n'
            '    }\n')
        try:
            cert = tc.certify_op(_column(), "2026")
        finally:
            authoring._EMITTERS["create_column"] = original
        self.assertFalse(cert.proven, "вакуумный сторож оставил сертификат доказанным")
        self.assertTrue(cert.vacuous, "находки вакуума нет")
        self.assertEqual({f.obligation_key for f in cert.vacuous},
                         {"vertical_extent"})

    def test_dropping_the_tolerance_is_refused_by_a_second_guard(self) -> None:
        # A SECOND, independent guard, found while writing this file:
        # `emit_model` requires that the DECLARED tolerance actually be
        # present in the C#. A seedling with no number gets an exception,
        # not a soft refusal — that is, the tolerance's provenance is held by
        # construction, not by agreement.
        from kir.emit_model import EmitModelError
        original = _mutate("vertical_extent",
                           '    if (false) __post.Add("never");\n')
        try:
            with self.assertRaises(EmitModelError):
                tc.certify_op(_column(), "2026")
        finally:
            authoring._EMITTERS["create_column"] = original

    def test_cutting_the_widened_top_offset_witness_breaks_it_too(self) -> None:
        # On 08.19 the obligation was extended from "when sent" to "always
        # when top_level is present": the emitter WRITES zero and had never
        # re-read it before.
        original = _mutate("top_offset")
        try:
            cert = tc.certify_op(_column(), "2026")
        finally:
            authoring._EMITTERS["create_column"] = original
        self.assertFalse(cert.proven)

    def test_after_the_mutation_is_undone_it_is_proven_again(self) -> None:
        self.assertTrue(tc.certify_op(_column(), "2026").proven)

    def test_the_old_shape_without_top_level_is_still_proven(self) -> None:
        # Compatibility: programs that omitted top_level remain provable as
        # before. The new obligation is conditional — it does not break
        # them, and `omission_transfers` speaks about them through a
        # rehearsal, not a refusal.
        op = _column()
        del op["top_level"]
        self.assertTrue(tc.certify_op(op, "2026").proven)


_WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "height_mm": 3000.0, "level": _L3,
         "type": {"__grounded__": {"id": 901, "name": "T", "via": "element_id"}},
         "top_level": _L4}


def _wall(**over):
    op = dict(_WALL)
    op.update(over)
    return op


def _mutate_wall(key, verdict_cs=None):
    original = authoring._EMITTERS["create_wall"]

    def broken(op, ver, stamp, isolation="atomic", _o=original):
        decl, create, post, readback = _o(op, ver, stamp, isolation)
        bare = isinstance(post, BarePost)
        checks = list(post.checks) if bare else list(post)
        out = []
        for check in checks:
            if check.obligation_key != key:
                out.append(check)
            elif verdict_cs is not None:
                out.append(dataclasses.replace(check, verdict_cs=verdict_cs))
        return decl, create, (post.__class__(tuple(out)) if bare else out), readback

    authoring._EMITTERS["create_wall"] = broken
    return original


class TheWallGetsTheSameTreatment(unittest.TestCase):
    """The wall — the second op of task E3.1, the same illness and the same fix."""

    def test_the_obligation_exists_and_is_geometry(self) -> None:
        ob = next(o for o in tc._ensure_table()["create_wall"].obligations
                  if o.key == "vertical_extent")
        self.assertEqual(ob.kind, tc.KIND_GEOMETRY)
        self.assertTrue(ob.conditional)
        self.assertEqual(ob.param, "top_level")

    def test_the_derived_extent_uses_both_levels(self) -> None:
        decl, create, _c, _rb = authoring._EMITTERS["create_wall"](
            _wall(), "2026", "kir:test")[0:2] + (None, None)
        self.assertIn("double __wexLo_W1", decl)
        self.assertIn("__wexLo_W1 = MM(__lv_W1.Elevation)", create)
        self.assertIn("__wexHi_W1 = MM(__tl_W1.Elevation)", create)

    def test_baseline_is_proven(self) -> None:
        self.assertTrue(tc.certify_op(_wall(), "2026").proven)

    def test_cutting_the_witness_breaks_the_certificate(self) -> None:
        original = _mutate_wall("vertical_extent")
        try:
            cert = tc.certify_op(_wall(), "2026")
        finally:
            authoring._EMITTERS["create_wall"] = original
        self.assertFalse(cert.proven)
        self.assertIn("built wall spans at least base..top elevation",
                      "\n".join(cert.gaps).lower())

    def test_a_vacuous_witness_breaks_the_certificate(self) -> None:
        original = _mutate_wall(
            "vertical_extent",
            '    if (false) {\n'
            '        if (__wexGot_W1 < __wexWant_W1 - 300.0)\n'
            '            __post.Add("never");\n'
            '    }\n')
        try:
            cert = tc.certify_op(_wall(), "2026")
        finally:
            authoring._EMITTERS["create_wall"] = original
        self.assertFalse(cert.proven)
        self.assertTrue(cert.vacuous)

    def test_a_wall_without_top_level_is_untouched(self) -> None:
        # Compatibility: without the tie, the source of truth stays
        # WALL_USER_HEIGHT_PARAM — measured 07.29, must not be touched.
        op = _wall()
        del op["top_level"]
        decl, _c, post, _rb = authoring._EMITTERS["create_wall"](
            op, "2026", "kir:test")
        checks = list(post.checks) if isinstance(post, BarePost) else list(post)
        self.assertNotIn("__wexLo_W1", decl)
        self.assertIn("height", [c.obligation_key for c in checks])
        self.assertNotIn("vertical_extent", [c.obligation_key for c in checks])
        self.assertTrue(tc.certify_op(op, "2026").proven)

    def test_the_guard_is_one_sided_here_too(self) -> None:
        _d, _c, post, _rb = authoring._EMITTERS["create_wall"](
            _wall(), "2026", "kir:test")
        checks = list(post.checks) if isinstance(post, BarePost) else list(post)
        v = next(c for c in checks if c.obligation_key == "vertical_extent")
        self.assertIn("__wexGot_W1 < __wexWant_W1 - 300.0", v.verdict_cs)
        self.assertNotIn("Math.Abs", v.verdict_cs)


if __name__ == "__main__":
    unittest.main()
