"""Trimming a run for a fitting insertion is legitimate, not a violation.

A LIVE MEASUREMENT on 30.07 using the Snowdon Towers Sample Plumbing sample.
The system ops promised "each LocationCurve == its node pair ±5mm
(geometry)" and on a connected system could NEVER fulfil this: Revit places
a fitting at the node and trims the neighboring runs to its face. A
differentiating experiment settled the question:

    1 run  (there is nowhere for a joint to come from) -> ok, one_system=true
    2 runs -> BOTH ends of the joint are violated
    3 runs -> all three are violated

Topology (BFS over the connector graph) passed in ALL cases — the system
assembled as connected, only the geometric check broke. That is, the
postcondition was wrong by construction, and this is exactly the reason
three network operations built NOTHING at all in their entire history.

The new invariant distinguishes two kinds of ends:

* a FREE end (a degree-1 node) — coincides with the node ±5 mm, as before;
* a JOINED end — is allowed to withdraw INTO the run, but must stay on the
  same line and not go past the midpoint. Trimming is allowed; drifting off
  the axis, overshooting outward, and "ate more than half" are not.

What is checked here is THE PART that lives in Python (the tolerance
bounds) and that the emission distinguishes them. The projection arithmetic
itself lives in C# in a single instance and is covered by goldens — a
second copy of the predicate must not be created, or it will diverge, the
way the census and its copy in the instrument have already diverged.
"""
from __future__ import annotations

import unittest

from kir.authoring import _segment_trim_bounds_mm
from kir import spec

# The end tolerance lives IN THE REGISTRY (03.08): the trim floor is the
# same number, and the test takes it from there too, not typed as a second
# instance.
TOL_MM = spec.OPS["create_pipe_system"].tolerances["endpoint_mm"]


class TrimBoundsTests(unittest.TestCase):

    def test_a_free_end_keeps_the_exact_tolerance(self) -> None:
        """An end that joins nothing has nothing to trim."""
        trim_a, trim_b = _segment_trim_bounds_mm(
            (0.0, 0.0, 0.0), (6000.0, 0.0, 0.0), degree_a=1, degree_b=1, tol_mm=TOL_MM)
        self.assertEqual((trim_a, trim_b), (5.0, 5.0))

    def test_a_junction_end_may_be_trimmed_up_to_half(self) -> None:
        """The fitting eats into the start of the run — but not more than half."""
        trim_a, trim_b = _segment_trim_bounds_mm(
            (0.0, 0.0, 0.0), (6000.0, 0.0, 0.0), degree_a=2, degree_b=1, tol_mm=TOL_MM)
        self.assertEqual(trim_a, 3000.0)
        self.assertEqual(trim_b, 5.0)

    def test_both_ends_may_be_junctions(self) -> None:
        """A middle run of a branch is trimmed from both sides."""
        trim_a, trim_b = _segment_trim_bounds_mm(
            (0.0, 0.0, 0.0), (0.0, 4000.0, 0.0), degree_a=3, degree_b=2, tol_mm=TOL_MM)
        self.assertEqual((trim_a, trim_b), (2000.0, 2000.0))

    def test_a_short_segment_never_gets_a_looser_bound_than_the_tolerance(self) -> None:
        """On a short run, half is less than the tolerance — the LARGER
        value is taken.

        Otherwise a joined end would get a stricter tolerance than a free
        one, and a connected system made of short runs would become
        impassable for a different reason.
        """
        trim_a, _ = _segment_trim_bounds_mm(
            (0.0, 0.0, 0.0), (6.0, 0.0, 0.0), degree_a=2, degree_b=1, tol_mm=TOL_MM)
        self.assertEqual(trim_a, 5.0)

    def test_a_degenerate_segment_is_refused_not_tolerated(self) -> None:
        """Zero length is not "everything matched", it is the absence of a run."""
        with self.assertRaises(ValueError):
            _segment_trim_bounds_mm(
                (10.0, 10.0, 10.0), (10.0, 10.0, 10.0), degree_a=1, degree_b=1, tol_mm=TOL_MM)


class EmissionDistinguishesEndsTests(unittest.TestCase):
    """The emission must DISTINGUISH the kinds of ends, not just relax
    everything across the board."""

    def _emit(self, program: dict) -> str:
        from kir.compiler import compile_program
        from kir.tests.fixtures import GROUND_SNAPSHOT
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, getattr(out, "diagnostics", None))
        return out.csharp

    def _program(self, nodes: list[dict], segments: list[dict]) -> dict:
        return {"ir_version": "1.0", "ops": [{
            "op": "create_pipe_system", "id": "S1",
            "nodes": nodes, "segments": segments,
            "level": {"by": "element_id", "value": 42}}]}

    def test_a_single_segment_stays_strict_on_both_ends(self) -> None:
        code = self._emit(self._program(
            [{"id": "a", "xyz_mm": [0, 0, 3000]},
             {"id": "b", "xyz_mm": [6000, 0, 3000]}],
            [{"from": "a", "to": "b"}]))
        # Both ends are free -> only tolerances of 5 appear in the comparison.
        self.assertIn("segment 0 endpoints (geometry)", code)
        block = code.split("segment 0 endpoints")[0][-700:]
        self.assertIn("__t0 > (5.0)", block)
        self.assertIn("__t1 > (5.0)", block)

    def test_a_junction_relaxes_only_the_shared_end(self) -> None:
        code = self._emit(self._program(
            [{"id": "a", "xyz_mm": [0, 0, 3000]},
             {"id": "b", "xyz_mm": [6000, 0, 3000]},
             {"id": "c", "xyz_mm": [6000, 6000, 3000]}],
            [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]))
        # Node b is shared by two runs: for run 0 the END is relaxed (t1),
        # for run 1 — the START (t0), while the free ends remain strict.
        first = code.split("segment 0 endpoints")[0][-700:]
        second = code.split("segment 1 endpoints")[0][-700:]
        self.assertIn("__t0 > (5.0)", first)
        self.assertIn("__t1 > (3000.0)", first)
        self.assertIn("__t0 > (3000.0)", second)
        self.assertIn("__t1 > (5.0)", second)


if __name__ == "__main__":
    unittest.main()
