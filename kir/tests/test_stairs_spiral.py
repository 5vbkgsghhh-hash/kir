"""A SPIRAL RUN: the second form of `create_stairs`, and not a single
silent outcome.

WHAT KIND OF GAP THIS IS. Until 09.08.2026 `create_stairs` could handle
EXACTLY ONE straight run (`StairsRun.CreateStraightRun`), and this is
recorded verbatim in the coverage measurement — "18 elements:
create_stairs reproduces exactly one straight run". A spiral is
inexpressible as a polyline AT ALL: a straight run gives a DIFFERENT shape,
not an approximation — the same class as "a polyline instead of a rounded
edge" for a ceiling. `StairsRun.CreateSpiralRun` exists and is
BYTE-FOR-BYTE identical across all six shipped versions (checked against
both the reference assemblies AND live Roslyn on :52412), so the gap was
ours, not Revit's.

THREE LAWS THIS FILE HOLDS, EACH OF THEM FALSIFIABLE:

  1. EXACTLY ONE SHAPE. "Both at once" is just as ambiguous as "neither",
     and both must be a TYPED refusal (KIR-P007), not a guess: guessing on
     the author's behalf means silently building a different staircase.
  2. WHAT IS ABSENT STAYS ABSENT. A program without `spiral` is emitted
     BYTE FOR BYTE the same as before the fix — held by the ratchet
     `golden/authoring_stairs_straight.golden.cs`, captured by the
     emitter BEFORE it.
  3. THE WITNESS READS THE RESULT AND SIGNS OFF ONLY ON WHAT IT READ. The
     path of the built run is reread (`GetStairsPath`) and must contain
     an ARC. The center, radius, sweep, and direction are NOT checked,
     and a GUARD stands here for that: the relationship between the
     requested center and what `GetStairsPath` returns (offset by
     half-width, justification) is NOT MEASURED, and a tolerance invented
     for the sake of a green witness would roll back a CORRECTLY built
     staircase. The numbers go into the receipt as a measurement.

Run: venv/bin/python3.12 -m pytest kir/tests/test_stairs_spiral.py -q
"""
from __future__ import annotations

import math
import os
import random
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_spiral_queue.jsonl"))

from kir import spec  # noqa: E402
from kir.authoring_validation import (  # noqa: E402
    _SPIRAL_MAX_INCLUDED_DEG, _SPIRAL_RADIUS_MAX_MM,
)
from kir.compiler import compile_program  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

BASE = {"by": "name", "value": "Этаж 1"}
TOP = {"by": "name", "value": "Этаж 2"}

SPIRAL = {"center_mm": [3000.0, 3000.0], "radius_mm": 1500.0,
          "start_angle_deg": 0.0, "included_angle_deg": 270.0,
          "clockwise": False}


def _prog(op_extra: dict, *, intent: str = "лестница") -> dict:
    op = {"op": "create_stairs", "id": "S1",
          "base_level": BASE, "top_level": TOP}
    op.update(op_extra)
    return {"ir_version": "1.0", "intent": intent, "ops": [op]}


def _compile(op_extra: dict, ver: str = "2023"):
    return compile_program(_prog(op_extra), snapshot=SNAPSHOT,
                           revit_version=ver)


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


# ═════════════════════════════════════════════ 1. THE SPIRAL BUILDS, ON ALL SIX

class ASpiralRunIsEmittedOnEveryShippedVersion(unittest.TestCase):
    """The version axis is a question for the reference assemblies, not
    for memory; what is held here is our conclusion from them: the spiral
    has the same axis as the straight run, and there is NO version fork in
    the emission AT ALL."""

    def test_it_compiles_on_all_six(self) -> None:
        for ver in VERSIONS:
            with self.subTest(version=ver):
                out = _compile({"spiral": SPIRAL, "width_mm": 1200}, ver)
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("StairsRun.CreateSpiralRun", out.csharp)
                self.assertNotIn("CreateStraightRun", out.csharp)

    def test_the_emission_does_not_branch_on_version(self) -> None:
        """One text for six versions is a FACT, and it must be exhibited:
        if a version seam ever appears for the spiral, the test must go
        red, not stay silent."""
        texts = {ver: _compile({"spiral": SPIRAL}, ver).csharp
                 for ver in VERSIONS}
        self.assertEqual(len(set(texts.values())), 1)

    def test_the_whole_stairs_skeleton_survives(self) -> None:
        """The branch diverges ONLY in creating the run: the
        StairsEditScope, the transaction, the statuses, the refusal
        preprocessor, and canceling the scope are all shared with the
        straight run."""
        cs = _compile({"spiral": SPIRAL, "width_mm": 1200}).csharp
        for token in ("new StairsEditScope(", "__ess.Start(",
                      "var __startStatus = __t.Start()",
                      "__startStatus != TransactionStatus.Started",
                      "__fho.SetFailuresPreprocessor(new __KirStairsFailures())",
                      "var __commitStatus = __t.Commit()",
                      "__ess.Commit(new __KirStairsFailures())",
                      "__ess.Cancel()"):
            self.assertIn(token, cs)

    def test_the_solo_rule_still_covers_the_spiral_form(self) -> None:
        """The rule that `create_stairs` is a soloist (KIR-L002) is about
        the program's MEMBERSHIP, not about the run's shape. A new shape
        must not have opened a way around it."""
        wall = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                "p1_mm": [5000, 0], "level": BASE, "height_mm": 3000}
        prog = _prog({"spiral": SPIRAL})
        prog["ops"].append(wall)
        out = compile_program(prog, snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", _codes(out))


# ═════════════════════════════════════════ 2. EXACTLY ONE SHAPE (KIR-P007)

class ExactlyOneShapeOfRun(unittest.TestCase):

    def test_both_at_once_is_a_typed_refusal_naming_both(self) -> None:
        out = _compile({"p0_mm": [0, 0], "p1_mm": [5000, 0],
                        "spiral": SPIRAL})
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        text = " ".join(d.message_ru for d in out.diagnostics
                        if d.code == "KIR-P007")
        self.assertIn("p0_mm", text)
        self.assertIn("p1_mm", text)
        self.assertIn("spiral", text)

    def test_neither_is_a_typed_refusal_naming_both(self) -> None:
        out = _compile({"width_mm": 1200})
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        text = " ".join(d.message_ru for d in out.diagnostics
                        if d.code == "KIR-P007")
        self.assertIn("p0_mm", text)
        self.assertIn("spiral", text)

    def test_half_a_straight_run_is_not_a_run(self) -> None:
        """A single point of a segment does not define a curve. Before
        09.08 this was caught by the SCHEMA's requiredness; it has become
        mutual, and the rule had to move over in full, not by half."""
        for present, missing in (("p0_mm", "p1_mm"), ("p1_mm", "p0_mm")):
            with self.subTest(present=present):
                out = _compile({present: [0, 0]})
                self.assertFalse(out.ok)
                self.assertIn("KIR-P007", _codes(out))
                text = " ".join(d.message_ru for d in out.diagnostics)
                self.assertIn(missing, text)

    def test_the_rule_is_read_from_the_registry_not_from_an_op_name(self) -> None:
        """ONE FACT — ONE PLACE. The rule is addressed by parameter KINDS
        (`pt_xy` versus `spiral`) on a single operation, so the next op
        with a spiral will get its check TOGETHER WITH THE FIELD, not as a
        separate "we forgot" commit. Here this is exhibited by the
        registry, not by reading the code."""
        ospec = spec.OPS["create_stairs"]
        kinds = {p.name: p.kind for p in ospec.params}
        self.assertEqual(kinds.get("spiral"), "spiral")
        self.assertEqual(kinds.get("p0_mm"), "pt_xy")
        self.assertEqual(kinds.get("p1_mm"), "pt_xy")
        # Mutual requiredness is NOT expressible by the schema — so none
        # of the three fields is allowed to be required, otherwise the
        # second shape would become unreachable by construction.
        for name in ("p0_mm", "p1_mm", "spiral"):
            self.assertFalse(
                next(p for p in ospec.params if p.name == name).required,
                f"{name}: required убил бы взаимную обязательность")


# ═══════════════════════════════════ 3. BOUNDS: A REFUSAL, NOT A REVIT EXCEPTION

class BoundsRefuseBeforeTheDevice(unittest.TestCase):
    """Every bound here is either DOCUMENTED by the API itself, or DERIVED
    from the justification. There are no invented numbers in this class —
    see the comments at `_SPIRAL_RADIUS_MAX_MM` /
    `_SPIRAL_MAX_INCLUDED_DEG`."""

    def _refused(self, spiral: dict, extra: dict | None = None):
        out = _compile({"spiral": spiral, **(extra or {})})
        self.assertFalse(out.ok, "принято то, что Revit отвергнет")
        return out

    def test_non_positive_radius(self) -> None:
        for radius in (0.0, -1500.0):
            with self.subTest(radius=radius):
                out = self._refused(dict(SPIRAL, radius_mm=radius))
                self.assertIn("KIR-T002", _codes(out))

    def test_radius_beyond_the_api_ceiling(self) -> None:
        out = self._refused(
            dict(SPIRAL, radius_mm=_SPIRAL_RADIUS_MAX_MM + 1.0))
        self.assertIn("KIR-T002", _codes(out))
        # The ceiling is a DOCUMENTED 30000 feet, exactly.
        self.assertEqual(_SPIRAL_RADIUS_MAX_MM, 30_000 * 304.8)

    def test_the_api_ceiling_itself_is_accepted(self) -> None:
        """A bound that rejects its own value is a different bound."""
        out = _compile({"spiral": dict(SPIRAL,
                                       radius_mm=_SPIRAL_RADIUS_MAX_MM)})
        self.assertTrue(out.ok, _codes(out))

    def test_non_positive_included_angle(self) -> None:
        for angle in (0.0, -90.0):
            with self.subTest(angle=angle):
                out = self._refused(dict(SPIRAL, included_angle_deg=angle))
                self.assertIn("KIR-T002", _codes(out))

    def test_more_than_a_full_turn(self) -> None:
        out = self._refused(
            dict(SPIRAL, included_angle_deg=_SPIRAL_MAX_INCLUDED_DEG + 0.5))
        self.assertIn("KIR-T002", _codes(out))

    def test_a_full_turn_exactly_is_accepted(self) -> None:
        out = _compile({"spiral": dict(SPIRAL, included_angle_deg=360.0)})
        self.assertTrue(out.ok, _codes(out))

    def test_radius_not_greater_than_half_the_width(self) -> None:
        """A DERIVED check, not an assigned one: the run is built on the
        CENTERLINE (`StairsRunJustification.Center`), so the inner edge
        lies at `radius - width/2`. When `radius <= width/2` there is no
        inner edge at all — this is exactly what the API calls "radius is
        too small ... at the given justification"."""
        out = self._refused(dict(SPIRAL, radius_mm=600.0),
                            {"width_mm": 1200})
        self.assertIn("KIR-T002", _codes(out))
        text = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("середине", text)
        # The same radius WITHOUT a width is legitimate: the type then
        # assigns the width, and the compiler has nothing to compare it
        # against — it will not make one up.
        self.assertTrue(_compile({"spiral": dict(SPIRAL,
                                                 radius_mm=600.0)}).ok)

    def test_a_missing_or_extra_key_is_a_typed_refusal(self) -> None:
        for broken in (
                {k: v for k, v in SPIRAL.items() if k != "clockwise"},
                dict(SPIRAL, unexpected=1),
                dict(SPIRAL, center_mm=[3000.0]),
                dict(SPIRAL, center_mm=[3000.0, 3000.0, 0.0]),
                dict(SPIRAL, clockwise="да"),
                dict(SPIRAL, radius_mm="1500"),
                dict(SPIRAL, start_angle_deg=float("inf")),
        ):
            with self.subTest(broken=sorted(broken)):
                out = _compile({"spiral": broken})
                self.assertFalse(out.ok)
                self.assertTrue(
                    {"KIR-T001", "KIR-T002"} & set(_codes(out)),
                    _codes(out))

    def test_clockwise_has_no_default(self) -> None:
        """The direction of the twist is visible in the model at first
        glance. A silently chosen "counterclockwise" on the author's
        behalf is exactly the kind of quietly different result the
        compiler exists to forbid."""
        out = _compile({"spiral": {k: v for k, v in SPIRAL.items()
                                   if k != "clockwise"}})
        self.assertFalse(out.ok)


# ═══════════════════════════════════════════ 4. WHAT IS ABSENT IS ABSENT

class AbsentStaysAbsent(unittest.TestCase):

    def test_a_straight_program_carries_no_trace_of_the_spiral(self) -> None:
        cs = _compile({"p0_mm": [0, 0], "p1_mm": [5000, 0],
                       "width_mm": 1200}).csharp
        for token in ("CreateSpiralRun", "GetStairsPath", "path_center_mm",
                      "path_radius_mm", "spiralArc"):
            self.assertNotIn(token, cs)

    def test_the_straight_emission_is_the_pre_change_bytes(self) -> None:
        """A byte-level ratchet. The reference was captured by the
        EMITTER BEFORE the fix (`git stash` at 15d5b206, the same
        snapshot, the same program): as long as the file matches, "an
        absent parameter moves nothing" is a verification, not a promise.
        The same file is also checked by `test_golden`; here it is named
        EXPLICITLY so the connection to the spiral is visible in this
        file, not only in the shared corpus."""
        import pathlib

        from kir.tests.test_golden import PROGRAMS as GOLDEN

        golden = (pathlib.Path(__file__).parent / "golden"
                  / "authoring_stairs_straight.golden.cs")
        out = compile_program(GOLDEN["authoring_stairs_straight"],
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out))
        self.assertEqual(golden.read_text(encoding="utf-8"), out.csharp)


# ═════════════════════════════════ 5. THE WITNESS: WHAT IS SIGNED AND WHAT IS NOT

class TheWitnessSignsOnlyWhatItRead(unittest.TestCase):

    def test_the_path_is_re_read_and_must_carry_an_arc(self) -> None:
        cs = _compile({"spiral": SPIRAL}).csharp
        self.assertIn("__run_S1.GetStairsPath()", cs)
        self.assertIn("is Arc", cs)
        self.assertIn("S1: spiral run path has no Arc (geometry)", cs)
        # An unreadable path is also a violation, not a silent skip.
        self.assertIn("S1: spiral run path unreadable (geometry)", cs)

    def test_the_violation_rolls_the_whole_thing_back(self) -> None:
        """A witness whose violation rolls nothing back is a report, not a
        witness. The check must sit BEFORE `__post.Count > 0`, and that
        one — before the commit."""
        cs = _compile({"spiral": SPIRAL}).csharp
        i_witness = cs.index("spiral run path has no Arc")
        i_gate = cs.index("__post.Count > 0")
        i_commit = cs.index("var __commitStatus = __t.Commit()")
        self.assertLess(i_witness, i_gate)
        self.assertLess(i_gate, i_commit)
        self.assertIn("__t.RollBack(); __ess.Cancel();", cs)

    def test_it_signs_geometry_because_it_read_geometry(self) -> None:
        """The signed axis follows what was read. The run's path is the
        geometry of a curve, not a parameter that we ourselves wrote."""
        cs = _compile({"spiral": SPIRAL}).csharp
        witness = cs[cs.index("bool __spiralArc_S1"):
                     cs.index("spiral run path unreadable")]
        self.assertNotIn("get_Parameter", witness)

    def test_no_invented_tolerance_gates_the_centre_or_the_radius(self) -> None:
        """A GUARD, NOT A DECORATION.

        The relationship between the REQUESTED center/radius and what
        `GetStairsPath` returns (offset by half the run's width,
        justification, the path line's position) is NOT MEASURED.
        Comparing it against a tolerance chosen "by eye" would roll back a
        CORRECTLY built staircase — and that is worse than having no check
        at all. If such a comparison ever appears, it must arrive TOGETHER
        WITH A MEASUREMENT and rewrite this test deliberately.
        """
        cs = _compile({"spiral": SPIRAL}).csharp
        witness = cs[cs.index("bool __spiralArc_S1"):
                     cs.index("spiral run path unreadable")]
        for token in ("Math.Abs", ".Center", ".Radius", "3000", "1500"):
            self.assertNotIn(token, witness)

    def test_the_unmeasured_relation_is_recorded_instead(self) -> None:
        """'Not measured' must become MEASURABLE on the very first live
        run: the path's center and radius go into the receipt as a
        measurement, gating nothing."""
        cs = _compile({"spiral": SPIRAL}).csharp
        self.assertIn('__rb_S1["path_center_mm"]', cs)
        self.assertIn('__rb_S1["path_radius_mm"]', cs)
        # The receipt lives AFTER the edit scope, meaning it reads the
        # committed result, not an intermediate state.
        self.assertLess(cs.index("__ess.Commit(new __KirStairsFailures())"),
                        cs.index('__rb_S1["path_center_mm"]'))

    def test_the_registry_promise_names_the_gap_out_loud(self) -> None:
        post = spec.OPS["create_stairs"].post
        self.assertIn("spiral run path contains an Arc", post)
        self.assertIn("UNMEASURED", post)

    def test_the_certificate_discharges_the_new_clause(self) -> None:
        from kir import ground as ground_mod
        from kir.compiler import _parse_and_check
        from kir.translation_cert import assert_refined, certify_op

        for extra in ({"spiral": SPIRAL, "width_mm": 1200},
                      {"p0_mm": [0, 0], "p1_mm": [5000, 0]}):
            with self.subTest(shape=sorted(extra)):
                grounded = ground_mod.ground(
                    _parse_and_check(_prog(extra)), SNAPSHOT)
                for ver in VERSIONS:
                    assert_refined(certify_op(grounded[0], ver))


# ═══════════════════════════════════════ 6. PROPERTIES OVER THE SPACE OF ANGLES

_CALL_RE = re.compile(
    r"StairsRun\.CreateSpiralRun\(doc, __sid_S1,\s*"
    r"new XYZ\(U\(([-0-9.e+]+)\), U\(([-0-9.e+]+)\), __base_S1\.Elevation\),\s*"
    r"U\(([-0-9.e+]+)\), ([-0-9.e+]+), ([-0-9.e+]+), (true|false),\s*"
    r"StairsRunJustification\.Center\);")


class TheAngleAndRadiusSpaceHoldsItsProperties(unittest.TestCase):
    """Properties over a SEEDED PRNG (hypothesis is not in the prod venv —
    the same technique as in `test_pbt`). The bounds are taken from the
    same constants as the compiler's: a corpus that knows ITS OWN numbers
    diverges from the registry."""

    SEED = 20260809
    N = 120

    def _space(self):
        rng = random.Random(self.SEED)
        for _ in range(self.N):
            width = rng.choice([None, rng.uniform(600.0, 5_000.0)])
            floor_r = 1.0 if width is None else width / 2.0
            yield {
                "center_mm": [rng.uniform(-50_000.0, 50_000.0),
                              rng.uniform(-50_000.0, 50_000.0)],
                # strictly more than half the width and no higher than the
                # API ceiling
                "radius_mm": rng.uniform(floor_r + 1e-6, 40_000.0),
                "start_angle_deg": rng.uniform(-720.0, 720.0),
                "included_angle_deg": rng.uniform(1e-6,
                                                  _SPIRAL_MAX_INCLUDED_DEG),
                "clockwise": rng.random() < 0.5,
            }, width

    def test_every_legal_point_compiles_and_carries_its_own_numbers(self) -> None:
        seen = 0
        for spiral, width in self._space():
            extra = {"spiral": spiral}
            if width is not None:
                extra["width_mm"] = width
            out = _compile(extra)
            self.assertTrue(out.ok, (spiral, width, _codes(out)))
            match = _CALL_RE.search(out.csharp)
            self.assertIsNotNone(match, out.csharp[:400])
            cx, cy, radius, start, included, cw = match.groups()
            # THE NUMBER THAT REACHES C# IS THE NUMBER THAT WAS ASKED FOR.
            # Python converts degrees at compile time, so the reverse
            # conversion must match to double precision, not "roughly".
            self.assertEqual(float(cx), spiral["center_mm"][0])
            self.assertEqual(float(cy), spiral["center_mm"][1])
            self.assertEqual(float(radius), spiral["radius_mm"])
            self.assertAlmostEqual(math.degrees(float(start)),
                                   spiral["start_angle_deg"], places=9)
            self.assertAlmostEqual(math.degrees(float(included)),
                                   spiral["included_angle_deg"], places=9)
            self.assertEqual(cw, "true" if spiral["clockwise"] else "false")
            # The direction is set by a FLAG, not by the angle's sign: a
            # negative sweep cannot exist in the emission for any input.
            self.assertGreater(float(included), 0.0)
            # The brackets balance, and the program is still a single one.
            self.assertEqual(out.csharp.count("{"), out.csharp.count("}"))
            seen += 1
        self.assertEqual(seen, self.N)

    def test_just_outside_the_box_it_always_refuses_and_never_raises(self) -> None:
        rng = random.Random(self.SEED + 1)
        for _ in range(self.N):
            broken = dict(SPIRAL)
            which = rng.randrange(4)
            if which == 0:
                broken["radius_mm"] = -rng.uniform(0.0, 10_000.0)
            elif which == 1:
                broken["radius_mm"] = _SPIRAL_RADIUS_MAX_MM + rng.uniform(
                    1.0, 1e6)
            elif which == 2:
                broken["included_angle_deg"] = -rng.uniform(0.0, 720.0)
            else:
                broken["included_angle_deg"] = (
                    _SPIRAL_MAX_INCLUDED_DEG + rng.uniform(1e-6, 3_600.0))
            out = _compile({"spiral": broken})
            self.assertFalse(out.ok, broken)
            self.assertIn("KIR-T002", _codes(out))
            # A refusal is the ABSENCE of emission, not C# "just in case".
            self.assertFalse(out.csharp)


if __name__ == "__main__":
    unittest.main()
