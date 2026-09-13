"""A NUMBER CARRIED OUT OF THE GENERATED BLOCK INTO PROSE ROTS WITHOUT A
WITNESS.

    cd /opt/kir && PYTHONPATH=/opt/kir python3.12 -m pytest -q \\
        kir/tests/test_canon_numbers_live_under_the_ratchet.py

🔴 WHAT THIS FILE COST, 24.08.2026. In the KIR canon a line stood for
fifteen days: "**90861** lines across **119** non-test `.py` files, plus
**183** test files" — WITH ITS OWN MEASUREMENT COMMAND RIGHT NEXT TO IT.
Running it cost three seconds. Live, with the same command: **181126**
lines, **188** non-test, **456** test — twice, 1.6 times, and 2.5 times
over.

No one ran it, and the reason is not carelessness. The line sat ABOVE the
`СОСТОЯНИЕ КОМПИЛЯТОРА: НАЧАЛО` marker, and the ratchet
`kir/tests/test_kir_canon_state_is_current.py` checks ONLY WHAT IS BETWEEN
THE MARKERS. It could NEVER catch this copy — and that is why it diverged
twice as badly as the very block sitting ten lines below it and carrying the
same value.

═══════════════════════════════════════════════════════════════════════════
WHAT THIS GUARD DOES NOT CHECK — NAMED FIRST, BECAUSE THIS IS ITS MAIN
PROPERTY
═══════════════════════════════════════════════════════════════════════════

It is **CLOSED, BUT NOT COMPLETE**. It guards ONE named carrier, not a
class.

A general guard — "every number in the canon outside the block must carry a
provenance anchor" — was designed and REJECTED BY THE 24.08 MEASUREMENT, not
postponed:

    wide     "a bare 3+-digit number outside the block"          749 hits
             dates, line numbers, sizes of unrelated things — pure noise
    narrow   "a value with a home in the block, copied into prose"   37
             and examples: «82 содержат формы» (about FAMILIES), "82
             failures without the flag" — DIFFERENT values that happened to
             match in DIGITS

🔴 A NUMBER IN PROSE HAS NO SELF-NAMED SUBJECT. To tell "82 ops" apart from
"82 families," one has to read the sentence; a regex matches the FORM, not
the SUBJECT. This is canon form 7 in its pure state, and an instrument that
produces 98% noise will be switched off — meaning it is worse than absent.

🔴 WHY ONLY ABOVE THE MARKER, AND NOT EVERYWHERE OUTSIDE THE BLOCK — CHECKED
BEFORE THE MOVE (27.08.2026), AND THE EXTENSION REJECTED BY MEASUREMENT.
Below the block, at `kir/CLAUDE.md:3843`, stands the command
`find kir -name 'test_*.py' | wc -l` — and this is NOT a second carrier: the
neighboring paragraph itself explains that it answers a DIFFERENT question
("the block counts ALL files under `tests/` directories, while the command
here counts only `test_*.py`. Two numbers, two different questions, both
named"). Had the scope been extended to everything outside the marker, the
guard would have turned red on prose that does exactly what it demands. An
empty cell here means "no one guards this carrier," not "the canon has no
other carriers."

ONE MORE BLINDNESS, NAMED: the guard does not see PARAPHRASE. Whoever writes
the same value in different words, without the command, drives straight
through. Protection against copying, not against retelling.
"""
from __future__ import annotations

import os
import unittest

import kir as _kir

#: The canon is INSIDE THE PACKAGE. The path is asked from the package, not
#: computed by stepping upward.
CANON = os.path.join(os.path.dirname(os.path.abspath(_kir.__file__)),
                     "CLAUDE.md")

BEGIN = "<!-- СОСТОЯНИЕ КОМПИЛЯТОРА: НАЧАЛО"
END = "<!-- СОСТОЯНИЕ КОМПИЛЯТОРА: КОНЕЦ -->"

#: The measurement command BELONGING to the block: it is what counts the
#: size of `kir/`, and the block prints the result itself. Its presence
#: ABOVE the marker means a second carrier of the same value — the very one
#: that diverged twofold.
#:
#: The spelling was updated by the 27.08 split: the `kukai/ir` area was
#: removed, the package is called `kir`. The old spelling is kept alongside
#: NOT out of courtesy — the canon is edited by people who remember the
#: former layout, and a copy in the old form would be exactly the same
#: defect.
_BLOCK_OWNED_PROBES = (
    "find kir -name '*.py' -not -path '*/tests/*'",
    "find kukai/ir -name '*.py' -not -path '*/tests/*'",
)


class TheCanonKeepsItsNumbersUnderTheRatchet(unittest.TestCase):

    def _canon(self) -> str:
        with open(CANON, encoding="utf-8") as fh:
            return fh.read()

    def test_the_markers_exist_and_are_in_order(self):
        """Without a pair of markers, the ratchet guards NOTHING, and
        silently."""
        text = self._canon()
        self.assertIn(BEGIN, text, "маркер НАЧАЛО пропал — храповик блока ослеп")
        self.assertIn(END, text, "маркер КОНЕЦ пропал — храповик блока ослеп")
        self.assertLess(
            text.index(BEGIN), text.index(END),
            "маркеры переставлены: блок пуст, и храповик зелен по построению")

    def test_the_blocks_own_probe_does_not_stand_above_the_marker(self):
        """A block's measurement command above the marker = a second
        carrier without a witness."""
        text = self._canon()
        above = text.split(BEGIN, 1)[0]
        for probe in _BLOCK_OWNED_PROBES:
            #: 🔴 NOT `assertNotIn`: it prints the ENTIRE haystack together
            #: with the needle — kilobytes of prose the reader will skim
            #: past. A refusal must be shorter than its subject, or it
            #: becomes noise itself.
            if probe in above:
                line = above[:above.index(probe)].count("\n") + 1
                self.fail(
                    "\n🔴 РАЗМЕР `kir/` СНОВА ВЫНЕСЕН В ПРОЗУ ВЫШЕ МАРКЕРА.\n"
                    "   адрес: kir/CLAUDE.md:%d\n"
                    "   команда: %s\n"
                    "   Эта величина принадлежит порождаемому блоку и живёт ТОЛЬКО там.\n"
                    "   Копия выше маркера храповиком не проверяется НИКОГДА:\n"
                    "   09.08 -> 24.08 такая копия разошлась ВДВОЕ (90861 против 181126).\n"
                    "   Следующий ход: убери число, оставь довод, укажи на блок."
                    % (line, probe))

    def test_the_guard_can_actually_fire(self):
        """FAIL CONTROL. A guard whose needle occurs in no haystack is green
        by construction — and indistinguishable from a disabled one.

        What is checked is the search MECHANISM ITSELF, on faked text: the
        real canon must not be touched, and a guard without a proven ability
        to turn red is not a guard (form 8).
        """
        probe = _BLOCK_OWNED_PROBES[0]
        forged = "проза\n%s\nещё проза\n%s\nблок\n%s\n" % (probe, BEGIN, END)
        above = forged.split(BEGIN, 1)[0]
        self.assertIn(probe, above,
                      "подделка не воспроизвела дефект — контроль вырожден")
        line = above[:above.index(probe)].count("\n") + 1
        self.assertEqual(line, 2, "адрес считается неверно: %d" % line)

    def test_the_probe_spellings_are_distinct(self):
        """CONTROL FOR LIST DEGENERACY: two identical spellings would search
        for the same thing, and the second line would create a false sense
        of coverage."""
        self.assertEqual(len(set(_BLOCK_OWNED_PROBES)), len(_BLOCK_OWNED_PROBES))


if __name__ == "__main__":
    unittest.main()
