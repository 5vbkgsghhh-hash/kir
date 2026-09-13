"""A PROMISED NAME IS OBLIGATED TO LIVE IN THE SCRIPT'S NAMESPACE.

An audit finding, `F-293` (2026-08-29). `kir/curveops.py`, in its very first
lines, declares itself as the AUTHOR's python constructors and points to the
prod sandbox as precedent. Neither `offset` nor `thicken` had been placed
into that namespace for five weeks; there is no workaround — `import kir` is
forbidden to the script.

🔴 THE DEFECT IS NOT THE TWO MISSING LINES, IT IS THAT REACHABILITY WAS
GUARDED BY THREE INSTRUMENTS AND NOT ONE OF THEM FIRED:

  `test_course.NAMES`            a hand-written closed tuple — goes red on
                                 an EXTRA name in the sandbox, not a MISSING one
  `test_expressiveness_census`   a hand-written dict of promises: it does not
                                 even have `sweep`, which has LIVED in the
                                 sandbox since 08.19
  `test_sandbox_names_are_declared`  the name is not in the sandbox ⇒ there is nothing to ask

And the module's own host tests (20 passed) COULD NOT have noticed this:
they import `kir.curveops` directly, meaning they checked arithmetic the
author has no door to. The same way `sdk.py` lay excellent and unreachable.

SO THE LIST OF PROMISES IS NO LONGER HAND-ASSEMBLED. Names are taken FROM
THE CENSUS ITSELF: the `via` string of a CONSTRUCTOR row is read as a python
expression, and a name is anything followed by an opening parenthesis. A
hand-written list of promises can neither fall behind nor get ahead — it is
simply NOT CONNECTED to the census, and `sweep` proved it.

🔴 AN UNFIT CONTROL THAT SUGGESTS ITSELF HERE: "the name appears in the
rendered doc." It is GREEN-BUT-UNFIT BY CONSTRUCTION, and this is a
measurement, not a worry: the word `offset` was ALWAYS in the doc — inside
someone else's sentence, "A changing value is COMPUTED (sine, contour
offset, interpolation)," i.e. inside an example of what an author computes
BY HAND. A guard that matches names by substring cannot tell a function
name from a word in prose — exactly the `F-341` defect in another instrument.
"""
from __future__ import annotations

import re
import unittest


class ПереписьОбещаетТолькоДостижимое(unittest.TestCase):

    @staticmethod
    def _promised() -> dict[str, str]:
        from kir.course import expressiveness as ex
        out: dict[str, str] = {}
        for kind, row in ex.CENSUS.items():
            if row.verdict != ex.CONSTRUCTOR:
                continue
            for name in re.findall(r"\b([a-z_][a-z0-9_]*)\s*\(", row.via):
                out[name] = kind
        return out

    def test_every_promised_constructor_is_reachable_by_the_author(self) -> None:
        from kir.course.language import __all__ as reachable
        promised = self._promised()
        # DENOMINATOR CONTROL: an empty parse would make the test green by
        # construction, and 'zero unreachable' would mean 'nothing was looked at.'
        self.assertGreaterEqual(
            len(promised), 4,
            f"из переписи вынуто всего {len(promised)} имён конструкторов "
            f"({sorted(promised)}) — почти наверняка сломан разбор `via`, а не "
            f"обеднела перепись")
        missing = sorted(n for n in promised if n not in set(reachable))
        self.assertEqual(
            missing, [],
            f"перепись обещает конструкторы, которых нет в пространстве "
            f"скрипта: {missing}. Проверь `course.SANDBOX_NAMES` и `dsl.__all__`")

    def test_the_curveops_pair_is_among_the_promised(self) -> None:
        """THE SUBJECT OF THE FINDING, BY NAME. Without this line the guard would
        stay green even on the day both doors from the census vanish again."""
        promised = self._promised()
        for name in ("offset", "thicken", "sweep"):
            with self.subTest(name=name):
                self.assertIn(name, promised)

    def test_the_selector_forms_promised_outside_via_are_reachable_too(self) -> None:
        """Four selector forms are promised NOT in `via`, but in the `sel` row's
        note; they stay hand-written until `via` names them. This line
        exists so that a fix to the guard ADDS work rather than removing it:
        the old hand-written `promised` used to check them."""
        from kir.course.language import __all__ as reachable
        surface = set(reachable)
        for name in ("by_name", "by_element_id", "by_ref", "family_type"):
            with self.subTest(name=name):
                self.assertIn(name, surface,
                              f"{name} обещан переписью и недостижим")

    def test_a_name_in_the_prose_is_not_a_reachable_name(self) -> None:
        """🔴 PROOF, BY EXECUTION, THAT CHECKING AGAINST THE DOC IS UNFIT.

        `offset` appears in the rendered doc both as a NAME and as a word in
        someone else's sentence about a manual computation. A guard that
        asks "is the substring present" cannot tell one from the other —
        meaning reachability is obligated to be asked of the NAMESPACE, not
        of the text.
        """
        from kir.skill import build_skill_text
        from kir.tool_doc import build_tool_description
        doc = build_tool_description() + build_skill_text()
        self.assertIn("offset контура", doc,
                      "фраза про РУЧНОЙ расчёт — та самая, из-за которой "
                      "сверка по доке была зелена, пока имя было недостижимо")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
