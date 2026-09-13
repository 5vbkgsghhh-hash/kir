"""READING THE SURFACE CLOSES A CIRCULAR ROUND-TRIP — and does not set up a single sentinel.

The circle: `create_surface` puts the surface into the model, `query_surface`
reads it back IN THE SAME KEYS, meaning what is read can be edited and built
again. Before this read existed, a panel would not seat onto an existing
shell: the 48-panel panelization of 20.08.2026 computed points from ITS OWN
formula, not from what is actually in the model.

WHAT IS CHECKED HERE, AND WHY EXACTLY THIS:

* **key agreement** — the one thing that makes the circle a circle. Should
  they diverge, "read → build" stops working SILENTLY, on the very first
  field;
* **the throw is caught** — `ExportUtils.GetNurbsSurfaceDataForSurface` is
  documented across all six versions to raise `ArgumentException` ("This
  surface type is not supported") and `InvalidOperationException` ("Couldn't
  get NURBS data"). A `null` check does not save you from them: execution
  never reaches it;
* **trimming is named** — a point inside the UV bounding box can lie OUTSIDE
  the face, and `Face.Evaluate` will return it silently, on the underlying
  surface;
* **not a single sentinel number** — anything not computed travels as `null`
  with a word. Form was bought that same day by five sentinels in the
  surface's receipt, the worst of which, `-304.8`, was `-1.0` in internal
  feet via `MM()`: a plausible number is more dangerous than zero, because
  nobody argues with it.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program
from kir.surface import _FIELDS_REQUIRED as SURFACE_FIELDS
from kir.surface_query import GRID_MAX

_TARGET = {"by": "element_id", "value": 287030}


def _emit(**kw) -> str:
    op = {"op": "query_surface", "id": "Q1", "target": dict(_TARGET), **kw}
    out = compile_program({"ir_version": "1.0", "ops": [op]},
                          revit_version="2026")
    assert out.ok, [f"{d.code}: {str(d.message_ru)[:160]}" for d in out.diagnostics]
    return out.csharp


def _refusals(**kw):
    op = {"op": "query_surface", "id": "Q1", "target": dict(_TARGET), **kw}
    out = compile_program({"ir_version": "1.0", "ops": [op]},
                          revit_version="2026")
    return out.ok, [d.code for d in out.diagnostics]


class TheCircleCloses(unittest.TestCase):

    def test_every_key_create_surface_REQUIRES_is_written_back(self) -> None:
        """THE FILE'S MAIN TEST. The keys are taken from
        `surface._FIELDS_REQUIRED`, not rewritten here: a list copied into
        the test stops catching a discrepancy on the exact day it appears."""
        cs = _emit(u_count=4, v_count=4)
        for field in SURFACE_FIELDS:
            self.assertIn(f'"{field}"', cs,
                          f"прочитанная поверхность не несёт {field!r} — "
                          f"её нельзя вернуть в create_surface")

    def test_the_optional_weights_ride_only_when_rational(self) -> None:
        """The weight of a non-rational surface is one by definition, and
        writing it would mean presenting a computed value as a read one."""
        cs = _emit(u_count=2, v_count=2)
        self.assertIn("IsRational", cs)
        self.assertIn('"weights"', cs)

    def test_counts_are_DERIVED_from_the_knots_not_guessed(self) -> None:
        """count = knots - degree - 1 — a B-spline identity. Revit gives back
        the knots and the points, but not the point counts per direction,
        and they cannot be guessed from the length of the overall list: 12
        points could be 3x4, 4x3, or 2x6."""
        cs = _emit()
        # The first version of this test COULD NOT FAIL: I built the
        # condition so that it is true for any input. A test that never goes
        # red on anything is decoration, and it is worse than no test at
        # all, because it counts as coverage. Here it is the arithmetic
        # ITSELF that is pinned down.
        self.assertIn(".Count - __nd_Q1.DegreeU - 1;", cs)
        self.assertIn(".Count - __nd_Q1.DegreeV - 1;", cs)


class TheDocumentedThrowIsCaught(unittest.TestCase):

    def test_the_nurbs_read_is_wrapped_for_BOTH_documented_exceptions(self) -> None:
        cs = _emit()
        head = cs[:cs.index("GetNurbsSurfaceDataForSurface")]
        self.assertIn("try {", head[-400:],
                      "чтение NURBS не под try — а оно БРОСАЕТ на всех шести")
        self.assertIn("catch (Autodesk.Revit.Exceptions.ArgumentException)", cs)
        self.assertIn("catch (Autodesk.Revit.Exceptions.InvalidOperationException)", cs)

    def test_the_absence_of_a_nurbs_face_is_a_WORD_not_a_missing_key(self) -> None:
        """"The face is not NURBS" is a legitimate outcome, not a failure: a
        planar face has no NURBS data at all. A reader would mistake a
        missing key for breakage."""
        cs = _emit()
        self.assertIn("surface_absence_ru", cs)
        self.assertIn('"surface"] = null', cs)


class NoSentinelNumbers(unittest.TestCase):

    def test_an_unevaluated_point_is_null_with_a_reason(self) -> None:
        cs = _emit(u_count=3, v_count=3)
        self.assertIn('"point_mm"] = null', cs)
        self.assertIn("sample_absence_ru", cs)

    def test_an_unrequested_grid_is_null_with_a_reason_too(self) -> None:
        """A NARROWNESS CONTROL: "did not ask" and "could not" are different
        things, and both must be words, not the absence of a key."""
        cs = _emit()
        self.assertIn("samples_absence_ru", cs)
        self.assertNotIn("Face.Evaluate", cs,
                         "сетку не просили, а Evaluate всё равно эмитирован")

    def test_the_trim_flag_rides_with_every_sample(self) -> None:
        cs = _emit(u_count=2, v_count=2)
        self.assertIn("IsInside", cs)
        self.assertIn('"inside"', cs)

    def test_the_face_domain_is_returned_so_the_mapping_is_not_magic(self) -> None:
        """The author supplies fractions in [0,1], while Revit accepts ITS
        OWN domain. The mapping must be visible, otherwise the `uv_face`
        numbers come from nowhere."""
        self.assertIn("domain_uv", _emit(u_count=2, v_count=2))


class TheGridLaw(unittest.TestCase):

    def test_one_count_without_the_other_is_REFUSED(self) -> None:
        for kw in ({"u_count": 4}, {"v_count": 4}):
            ok, codes = _refusals(**kw)
            self.assertFalse(ok, f"{kw} принято, а сетка задаётся ПАРОЙ")

    def test_a_degenerate_or_oversized_grid_is_REFUSED(self) -> None:
        for kw in ({"u_count": 1, "v_count": 4},
                   {"u_count": 4, "v_count": GRID_MAX + 1}):
            ok, _codes = _refusals(**kw)
            self.assertFalse(ok, f"{kw} принято")

    def test_no_grid_at_all_is_LEGAL(self) -> None:
        """A NARROWNESS CONTROL: the law of the pair must not require a grid
        always — "read the definition and don't count points" is a frequent
        and legitimate case."""
        ok, codes = _refusals()
        self.assertTrue(ok, codes)


class TheNeighbourIsNotDisturbed(unittest.TestCase):

    def test_query_inspect_still_validates_its_target_the_same_way(self) -> None:
        """I extended the `target` validation branch to two ops. If it grew
        weaker for a neighbor in the process, the cost of the change exceeds
        its benefit."""
        bad = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_inspect", "id": "I1",
             "target": {"by": "name", "value": "стена"}}]},
            revit_version="2026")
        self.assertFalse(bad.ok, "поиск по имени без kind перестал отвергаться")

    def test_a_name_search_needs_a_kind_here_too(self) -> None:
        ok, _ = _refusals()
        self.assertTrue(ok)
        bad = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_surface", "id": "Q1",
             "target": {"by": "name", "value": "фасад"}}]},
            revit_version="2026")
        self.assertFalse(bad.ok, "чтение по имени без kind сканировало бы документ")


class TheSixVersionIdiom(unittest.TestCase):

    def test_the_removed_2026_member_is_never_emitted(self) -> None:
        """`ElementId.IntegerValue` was removed in Revit 2026 (CS1061). Only
        the six-version check caught this: the `by=element_id` path does not
        touch it, and five versions out of six were green."""
        for ver in ("2021", "2026"):
            out = compile_program({"ir_version": "1.0", "ops": [
                {"op": "query_surface", "id": "Q1",
                 "target": {"by": "name", "value": "фасад",
                            "kind": "generic_model"}}]}, revit_version=ver)
            self.assertTrue(out.ok)
            self.assertNotIn("IntegerValue", out.csharp)


class TheWitnessReadBackIsGuardedToo(unittest.TestCase):
    """THE SAME THROW ALSO LIVES IN THE `create_surface` WITNESS, AND THERE IT WAS OPEN.

    Found on 20.08.2026 by a query to `data/api_traps` while building the
    read: the witness checked `__nd == null`, but the call THROWS. Execution
    would simply never reach the null check. This would have triggered
    exactly when Revit collapses a face to non-NURBS — and that it does
    collapse the representation was measured live that same day (a 3x3
    saddle read back as 1x1).

    The price would not have been a red witness but `internal`: an
    unhandled Revit exception instead of a named outcome, that is, an
    "internal error" delivered to the author.
    """

    def test_create_surface_wraps_its_own_nurbs_read_back(self) -> None:
        knots = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
        pts = [[iu * 1000.0, iv * 1000.0, 0.0 if (iu + iv) % 2 else 500.0]
               for iu in range(4) for iv in range(4)]
        out = compile_program({"ir_version": "1.0", "ops": [{
            "op": "create_surface", "id": "S1",
            "surface": {"degree_u": 3, "degree_v": 3, "count_u": 4, "count_v": 4,
                        "knots_u": knots, "knots_v": knots,
                        "control_points_mm": pts},
            "category": "generic_model", "name": "контроль"}]},
            revit_version="2026")
        self.assertTrue(out.ok, [str(d.message_ru)[:200] for d in out.diagnostics])
        self.assertIn("catch (Autodesk.Revit.Exceptions.ArgumentException)",
                      out.csharp,
                      "чтение NURBS в свидетеле не защищено от документированного "
                      "броска — программа умрёт internal вместо названного исхода")


if __name__ == "__main__":
    unittest.main()
