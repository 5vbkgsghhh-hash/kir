"""A TRAVERSAL THAT LOST ITS SUBJECT SAYS "CLEAN." THE RATCHET STANDS
AGAINST THAT.

🔴 THE NUMBER THIS FILE EXISTS FOR (02.09.2026). A wave of layer changes
relocated carriers, and TWO source traversals went blind on the same day:

    the satellite traversal    found 4 delegations instead of 41 and ZERO
                                refusal sites instead of six — and TURNED RED
    the emitter guard          saw 35 names out of 72 — and STAYED GREEN

The difference is exactly one thing, and it is not the traversal's
complexity: the first had a line saying "the traversal found fewer than six
sites — this is an assertion about the WALKER, not about the registry," the
second had `assert names`, which only catches emptiness. Fewer found = fewer
defects found; a green bought by blindness is worse than a red.

WHAT IS GUARDED HERE, AND WHAT ISN'T
-------------------------------------
What is guarded is the NUMBER of traversals without a denominator, and it is
allowed only to DECREASE. There is NO list of exceptions with prose here —
and that is a decision, not a gap: 02.09 bought, at its own expense, the
lesson that eleven arguments of "the name is named in the lesson" rested on
my own word, until someone started checking them. A list of reasons nobody
checks is a way to close a debt with words.

The instrument's signature is SYNTACTIC, and the limit is named right in its
own header: it sees the shape "a count against a positive threshold," not
the meaning. So the number is an UPPER BOUND on the debt: some of the files
in it declare their denominator differently (by cross-checking the registry
both ways). Lowering the bar is allowed ONLY together with a real fix, and
the ratchet's second half guards exactly that.
"""
from __future__ import annotations

import unittest

# 🔴 IMPORTED FROM THE PACKAGE, NOT FROM `tools/` VIA `sys.path` (02.09.2026).
# The first draft was patching the path in by hand — and the KIR<->product
# boundary guard counted HARD CROSSINGS at 2 instead of 1 on the same day:
# `tools/` is not part of the installable package, and this test would have
# broken on import for a stranger. The pattern was already closed here on
# 28.08 for `canon_state`, and it came back as a new instance.
from kir.instruments import walk_denominator as ПЕРЕПИСЬ

#: Traversals across the tree, TOTAL. The denominator OF THE RATCHET ITSELF:
#: a census that lost its subject would hand back "0 without a denominator"
#: and read as a win.
ОБХОДОВ_НЕ_МЕНЬШЕ = 50

#: Traversals WITHOUT a declared denominator. Measured 02.09.2026: 63
#: traversals, 54 with a denominator, **9** without. This number is allowed
#: only to DECREASE.
#:
#: 🔴 THE FIRST FOUR NUMBERS WERE NUMBERS ABOUT THE INSTRUMENT, NOT ABOUT THE
#: TREE: 32 -> 28 -> 24 in the first hour, and 14 -> 9 on the same day. The
#: instrument first knew exactly one form of denominator (`len(X) >= 3`),
#: then learned a threshold CONSTANT, then a COUNTER next to the traversal
#: (`files += 1` … `assertGreaterEqual(files, THRESHOLD)`), and on the
#: fourth pass, that the threshold is declared NEXT TO ITS OWN TRAVERSAL,
#: inside the test, not in the file's header: the census was reading only
#: `t.body` and failed to count FIVE real conversions in a row. Every
#: extension was caught by ITS OWN FIX — you declare a denominator to the
#: real guard, and the census cannot see it — and each was closed by a
#: self-check instance. A number taken by an instrument that knows one form
#: out of four is a claim about the instrument.
#:
#: 🔴 WHAT REMAINS, AND WHY IT ISN'T ZERO (analyzed 02.09.2026, all nine
#: READ). Eight of the nine are protected DIFFERENTLY — not by `== []`, but
#: by a positive assertion about the traversal's find, one that an empty
#: traversal would fail: `assertIsNotNone(names, "call disappeared")`,
#: `assertEqual(order[:2], [two names])`, `carriers ==
#: ["emit_utils.py"]`, `loops == len(declared_sources)`. The ninth —
#: `test_the_digest_witness…` — is not a traversal at all: its `iterdir`
#: and `read_text` walk a TEMPORARY directory the test created itself, and
#: they sit in DIFFERENT tests; the instrument's signature is per-module and
#: folds them into one phantom traversal. Neither case is fixed by
#: appending `assertGreaterEqual(len(x), 1)`: an instrument that can be
#: gamed by reshaping its form guards nothing. The remainder is more honest
#: than a list of exceptions with prose — it is VISIBLE in the number.
БЕЗ_ЗНАМЕНАТЕЛЯ = 9


class ОбходОбъявляетСколькоОбязанНайти(unittest.TestCase):

    def setUp(self) -> None:
        self.с, self.без = ПЕРЕПИСЬ.перепись()

    def test_прибор_нашёл_обходы_вообще(self) -> None:
        """THE DENOMINATOR FIRST. An empty census would pass the ratchet vacuously."""
        всего = len(self.с) + len(self.без)
        self.assertGreaterEqual(
            всего, ОБХОДОВ_НЕ_МЕНЬШЕ,
            f"перепись нашла {всего} обходов при поле {ОБХОДОВ_НЕ_МЕНЬШЕ} "
            "(замер 02.09.2026 — 62). Это заявление о ПРИБОРЕ, а не о дереве: "
            "проверь его прежде, чем верить числу ниже")

    def test_обходов_без_знаменателя_не_прибавилось(self) -> None:
        self.assertLessEqual(
            len(self.без), БЕЗ_ЗНАМЕНАТЕЛЯ,
            "\n🔴 ПОЯВИЛСЯ ОБХОД ПО ДЕРЕВУ БЕЗ ЗНАМЕНАТЕЛЯ.\n"
            "Обход, потерявший предмет, отвечает «ничего не нашлось» и\n"
            "читается как «всё чисто». Объяви, сколько мест он ОБЯЗАН найти:\n"
            "    self.assertGreaterEqual(len(места), N, «это о ходоке…»)\n"
            "либо `assert файлов >= ПОРОГ` внутри самого обхода.\n"
            + "\n".join(f"    {f}" for f in sorted(set(self.без))))

    def test_храповик_затянут(self) -> None:
        """Fixed it, but did not lower the bar — the ratchet stopped
        holding.

        The same second half as with the boundary guard: a one-directional
        ratchet lets the debt creep back silently.
        """
        self.assertEqual(
            len(self.без), БЕЗ_ЗНАМЕНАТЕЛЯ,
            f"\n🟢 БЕЗ ЗНАМЕНАТЕЛЯ УЖЕ {len(self.без)}, А ПЛАНКА "
            f"{БЕЗ_ЗНАМЕНАТЕЛЯ}.\nОпусти `БЕЗ_ЗНАМЕНАТЕЛЯ` тем же коммитом, "
            "что объявил знаменатель.")

    def test_сам_прибор_различает_оба_исхода(self) -> None:
        """An instrument whose parsing nobody checked is a source of a
        plausible-looking number, on par with prose. Its FAIL control is
        called FROM HERE."""
        self.assertEqual(ПЕРЕПИСЬ.самопроверка(), 0)


if __name__ == "__main__":
    unittest.main()
