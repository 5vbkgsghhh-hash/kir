"""DE-JOIN SPEAKS UP WHEN IT DID NOT TAKE — AND IT TRIES BOTH ENDS.

THE MEASUREMENT THAT PAID FOR THIS FILE (18.08.2026, the `prod-live`
tree). Until that day `authoring.py` emitted, on a rebuild, ONE line for
two ends:

    try { WallUtils.DisallowWallJoinAtEnd(el,0);
          WallUtils.DisallowWallJoinAtEnd(el,1); } catch { }

Two defects in one line, and both silent:

* **one `try` for two ends.** A throw at end 0 took end 1 down with it,
  and nobody ever tried end 1. The wall would leave for the document with
  one live auto-join, and the program looked successful;
* **an empty `catch`.** "De-join failed" became INDISTINGUISHABLE from
  "de-join succeeded" — exactly the class this whole bundle was written
  against.

Why this is not cosmetic: the witness tolerance for `create_wall` is
**5.0 mm** (`spec.OPS['create_wall'].tolerances['endpoint_mm']`), while
live Revit moves a curve via auto-join by **±100/125/150 mm** (canon,
measured 21.07). So it is exactly this call that keeps the rebuild green,
and its silence is silence about whether the endpoint geometry is even
correct.

🔴 A REFUTATION, PAID FOR RIGHT HERE. The task required "deciding whether
`create_face_wall` belongs in `_WALL_OPS`." The answer is IT DOES NOT AND
CANNOT: `FaceWall` is not a `Wall`. The live compile service was asked
against Revit 2026 references:

    WallUtils.DisallowWallJoinAtEnd(FaceWall, 0)  ->  CS1503: cannot convert
        from 'Autodesk.Revit.DB.FaceWall' to 'Autodesk.Revit.DB.Wall'
    WallUtils.DisallowWallJoinAtEnd(Wall, 0)      ->  OK  (control)

Extending the list would break emission, not fix it. The previous
`_WALL_OPS = {"create_wall"}` is not an oversight — it is the only thing
that compiles.

🔴 A SECOND CARRIER OF THE FORM WAS SEARCHED FOR AND FOUND — 8 OF THEM,
AND THEY ARE NOT CLOSED. The law from the night of 17→18.08 states: once a
form is caught, search for its second carrier IN THE SAME FILE. The search
was carried out, the number is named: in the emitted C#, `authoring.py`
has **eight** places where an EFFECT (a parameter's `.Set(...)`) is
wrapped in an empty `catch` — lines 345, 604, 770, 1642, 2257, 2981, 3058,
3789 (measured 18.08.2026, a regex over `catch {{ }}` with a two-line
window).

WHAT THIS MEASUREMENT DOES NOT SAY, AND WHY THERE IS NO GUARD HERE. The
form is not dangerous by itself: `WALL_TOP_OFFSET` and
`RBS_PIPE_DIAMETER_PARAM` sit next to their own `__post.Add` («top offset
mismatch», «diameter mismatch»), meaning their value GETS RE-READ, and a
silent `.Set` would be caught by that second reader. The real form,
therefore, is already **"an empty catch around an effect that NOBODY
re-reads,"** and de-join was exactly that.

There is nothing to check the remaining eight with: my probe measured
LINE PROXIMITY, not data flow, and building a guard on top of it would
mean setting up an instrument that is green by construction — the very
kind this house has already been burned by. The finding is recorded with
a number and a date; what closes it is data-flow analysis, not one more
regex.

Run:
    venv/bin/python -m pytest kir/tests/test_dejoin_is_not_silent.py -q
"""
from __future__ import annotations

import re
import unittest

from kir import authoring, compiler, spec
from kir.tests.test_op_budget_seam import GROUND_SNAPSHOT, _wall_ops

#: Exactly what stood here before 18.08. Kept here verbatim: the test must
#: be able to name the FORM it defends against, not only the current
#: state.
_RETIRED_SILENT_FORM = "; }} catch {{ }}"


def _chunk_cs(n: int = 2, ver: str = "2026") -> str:
    """The rebuild chunk's C# is the only path where de-join is turned on."""
    out = compiler.compile_rebuild_chunk(
        {"ir_version": "1.0", "ops": _wall_ops(n)}, ver,
        snapshot=GROUND_SNAPSHOT)
    assert out.ok, out.diagnostics
    return out.csharp


class TheDeJoinTriesBothEnds(unittest.TestCase):

    def test_each_end_owns_its_try(self):
        """The paid-for defect: a throw at end 0 took end 1 down with it."""
        cs = _chunk_cs(1)
        calls = cs.count("WallUtils.DisallowWallJoinAtEnd")
        self.assertEqual(calls, 2, "одна стена — два конца")
        # `try { ...(x, 0); }` closes BEFORE end 1 even begins.
        pairs = re.findall(
            r"try \{ WallUtils\.DisallowWallJoinAtEnd\(([^,]+), (\d)\); \}",
            cs)
        self.assertEqual([e for _, e in pairs], ["0", "1"],
                         "у каждого конца обязан быть СВОЙ try; общий try "
                         "делает второй конец непопробованным при броске "
                         "на первом")

    def test_the_refusal_is_named_not_swallowed(self):
        cs = _chunk_cs(1)
        self.assertNotIn(
            "DisallowWallJoinAtEnd(__el_w0, 1); } catch { }", cs,
            "вернулась молчаливая форма: пустой catch делает отказ "
            "неотличимым от успеха")
        self.assertEqual(cs.count("НЕ де-джойнен"), 2,
                         "оба конца обязаны уметь СКАЗАТЬ, что не сработали")
        self.assertIn(".Message);", cs,
                      "причина Revit обязана доехать словами, а не пропасть")

    def test_the_note_goes_into_the_channel_that_is_reported(self):
        """The record must travel through `__post`, not through a new
        second channel.

        `disallow_wall_joins` only occurs under `per_op`, and `per_op`
        forces `report_posts` (`authoring.py:7425`) — meaning `__post`
        reaches `__results["postcondition_violations"]` BY CONSTRUCTION,
        not by hope.
        """
        cs = _chunk_cs(1)
        self.assertIn('__post.Add("w0: конец 0 НЕ де-джойнен', cs)
        self.assertIn('__post.Add("w0: конец 1 НЕ де-джойнен', cs)
        self.assertIn('__results["postcondition_violations"] = __post;', cs,
                      "канал объявлен, но программа его не выгружает")

    def test_the_op_id_is_in_the_note(self):
        """A note with no address cannot find its own wall among 15 930 walls."""
        cs = _chunk_cs(3)
        for oid in ("w0", "w1", "w2"):
            self.assertIn(f'__post.Add("{oid}: конец 0 НЕ де-джойнен', cs)

    def test_the_chat_path_still_carries_no_de_join(self):
        """A control pointing the other way: the fix did not leak into the
        chat door.

        One program — DIFFERENT endpoint geometry on the two compilation
        paths; this is known behavior (`compiler.py:2230`), and it must
        NOT have changed because of this fix.
        """
        out = compiler.compile_program(
            {"ir_version": "1.0", "ops": _wall_ops(2)}, "2026",
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, out.diagnostics)
        self.assertNotIn("DisallowWallJoinAtEnd", out.csharp)


class TheWallOpsListIsWhatCompiles(unittest.TestCase):
    """`_WALL_OPS` is closed not by taste, but by what actually compiles."""

    def test_face_wall_is_absent_and_that_is_the_measured_answer(self):
        self.assertEqual(authoring._WALL_OPS, frozenset({"create_wall"}))
        self.assertIn("create_face_wall", spec.OPS,
                      "оп существует — значит его отсутствие здесь это "
                      "РЕШЕНИЕ, а не забывчивость")
        self.assertNotIn("create_face_wall", authoring._WALL_OPS,
                         "FaceWall не является Wall: замер 18.08 живой "
                         "компайл-службой дал CS1503 на "
                         "DisallowWallJoinAtEnd(FaceWall, 0)")

    def test_every_listed_op_actually_creates_a_wall(self):
        """A closed list: a new op lands here only deliberately.

        The rule is derived, not enumerated: everything in `_WALL_OPS`
        must emit a `Wall`, or `WallUtils` won't compile.
        """
        for name in authoring._WALL_OPS:
            self.assertIn(name, spec.OPS, f"{name} нет в реестре")
            self.assertTrue(spec.OPS[name].writes_model,
                            f"{name} не пишет в модель — де-джойнить нечего")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
