"""THE D4 TRANSITIONAL ADAPTER HAS BEEN RETIRED FROM USE — and this is
verified by a refusal.

WHY THIS FILE EXISTS. `WitnessCheck` cannot be built without `__post.Add` in
the verdict — this kills the class "verdict deleted, reader marker
survived, certificate says proven". But as long as `post_to_string` PASSED
THE STRING THROUGH untouched, the guarantee had a hole: the emitter could
return a handwritten block, and the class would be resurrected silently,
bypassing the constructor. A by-construction guarantee that has a bypass is
a guarantee by agreement.

WHAT CLEARED THE RETIREMENT, AND THIS IS A MEASUREMENT, NOT AN ARGUMENT
(27.08.2026, python3.12, tree `/opt/kir`):

    a probe on post_to_string itself, 28 files, 931 tests
        list 9452 · BarePost 164 · LINES 0

    a probe on the PRODUCER (wrapping _EMITTERS and _SOLO_PROGRAMS)
        73 of 77 writing ops are grounded by the corpus, NOT ONE returned a
        string

The branch was dead. The retirement did not shift a single byte of
emission — this is held by `test_emit_model_byte_parity` and the goldens,
and they were run alongside it.

🔴 WHY A REFUSAL, NOT JUST DELETING THE BRANCH. Without an explicit refusal
the string would have fallen through into `render_post` and been taken
apart there character by character, producing "post block carries a
non-WitnessCheck" — a truth about the CONSEQUENCE and silence about the
CAUSE. A refusal that names the wrong address is more costly than silence:
it sends the reader to fix the wrong thing (form 51).
"""
from __future__ import annotations

import unittest

from kir.emit_model import (BarePost, EmitModelError, WitnessCheck,
                            post_to_string, render_post)


def _check(key: str = "k", msg: str = "м") -> WitnessCheck:
    return WitnessCheck(
        obligation_key=key,
        reader_cs="",
        verdict_cs=f'    __post.Add("{msg}");\n',
        message=msg,
    )


class АдаптерСнятИОтказываетГромко(unittest.TestCase):
    """FAIL control: the line must REFUSE, not slip through."""

    def test_a_string_post_is_refused(self) -> None:
        with self.assertRaises(EmitModelError) as ctx:
            post_to_string("W1", "// post W1\n{\n__post.Add(\"x\");\n}")
        text = str(ctx.exception)
        # The refusal must name the CAUSE (adapter retired), not just the symptom.
        self.assertIn("W1", text)
        self.assertIn("СТРОКОЙ", text)
        self.assertIn("WitnessCheck", text)

    def test_the_refusal_names_the_guarantee_it_protects(self) -> None:
        """The message explains WHAT would have been bypassed — otherwise the
        next one will return a string and read the refusal as nitpicking
        about the type."""
        with self.assertRaises(EmitModelError) as ctx:
            post_to_string("W1", "что угодно")
        self.assertIn("вердикт", str(ctx.exception).lower())


class ЖивыеРодаПроезжаютКакПрежде(unittest.TestCase):
    """The other side of the control: the retirement must not close legitimate paths."""

    def test_a_model_post_still_renders(self) -> None:
        out = post_to_string("W1", [_check()])
        self.assertEqual(out, render_post("W1", [_check()]))
        self.assertIn("__post.Add", out)

    def test_a_bare_post_still_renders_frameless(self) -> None:
        out = post_to_string("W1", BarePost(checks=(_check(),)))
        self.assertTrue(out.startswith("// post W1\n"))
        # WITHOUT a frame: for the mesh kind, blocks carry their own brackets.
        self.assertNotIn("{\n", out.split("\n", 1)[1][:2])

    def test_a_tuple_of_checks_is_a_model_too(self) -> None:
        self.assertIn("__post.Add", post_to_string("W1", (_check(),)))


class ГарантияНеИмеетОбходногоПути(unittest.TestCase):
    """What all this is for: a witness cannot be built without a verdict, and
    the constructor cannot be bypassed with a string either."""

    def test_a_witness_without_a_verdict_is_unconstructible(self) -> None:
        with self.assertRaises(EmitModelError):
            WitnessCheck(obligation_key="k", reader_cs="",
                         verdict_cs="    // ничего не добавляем\n", message="м")

    def test_and_the_string_door_around_it_is_shut(self) -> None:
        """Both doors are closed AT THE SAME TIME — that is the whole point.
        As long as the second stays open, the first is an agreement, not a
        guarantee."""
        with self.assertRaises(EmitModelError):
            post_to_string("W1", '    // ничего не добавляем\n')


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
