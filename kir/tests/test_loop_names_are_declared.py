"""Every ring name that emitted C# code REFERENCES must be DECLARED.

**This is "declared here, read there" in CLONE form, and the clone form is
more dangerous than usual: the code does not diverge from the
documentation — it diverges FROM ITSELF.** The opening loop lives at eight
sites across six modules (`arch_emit` ×2, `authoring` ×3, `site_emit`,
`solid_emit`, `struct_emit`), and some of them have a SECOND, independent
traversal of the same list standing next to them, collecting names AFRESH:

    solid_emit.py:108   for hi, hole in enumerate(region["holes"]):
                            parts.append(emit_loop_cs(hole, f"__hl_{s}_{hi}"))
    solid_emit.py:115   names = [f"__ol_{s}"] + [f"__hl_{s}_{i}"
                                 for i in range(len(region["holes"]))]

Should these two diverge, the emitted C# would reference an `__hl_` that
nobody declared: CS0103 at best, and at worst a reference to someone
else's loop. Exactly two `move_elements`-style boundaries, only in
geometry.

**As of today (12.08.2026) they CANNOT diverge, and this is verified by
reading, not assumed:** both functions receive the same `region` object at
both call sites (405/416 and 544/565), between the calls it is only read,
`region["holes"]` is not mutated anywhere in the module, and neither
traversal filters or does a `continue`. But safety by construction is a
property of TODAY'S code, not an invariant: a `continue` for a degenerate
opening, added to just one traversal, breaks it silently.

That is why what stands here is not prose but an instrument. It does not
parse the emitters — it reads what they PRODUCED, and therefore does not
depend on the loop idiom, the module, or how many copies there are:
**the set of declared names is compared against the set of used names, in
every golden.** A new copy of the loop, written however it is written,
falls under the check automatically.

The boundary is honest: the golden corpus is NOT all of the compiler's
programs. The instrument says "no divergence in the frozen emission," not
"divergence is impossible."
"""

import pathlib
import re
import unittest

GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden"

#: ANY declaration of a name, not only `CurveLoop`. The first version
#: required exactly `CurveLoop` — and produced two "violators" that do not
#: exist: `__hl_D1` and `__hl_Win1` are declared as `Level`, because **the
#: prefix `__hl_` carries TWO different meanings in the emitter** — a hole
#: loop (`__hl_{s}_{hi}`, `CurveLoop`) and a host level (`__hl_{s}`,
#: `Level`, `authoring.py:1876`). The instrument was matching by the SHAPE
#: OF THE NAME, that is, by convention instead of authority, and the
#: declaration type was exactly the authority it never asked.
DECLARED = re.compile(
    r"\b(?:CurveLoop|Level|ModelCurve|var)\s+(__(?:hl|ol)_[A-Za-z0-9_]+)\s*=")

#: Any mention of a ring name in the code.
MENTIONED = re.compile(r"\b(__(?:hl|ol)_[A-Za-z0-9_]+)\b")


def _split(text: str) -> tuple[set[str], set[str]]:
    declared = set(DECLARED.findall(text))
    return declared, set(MENTIONED.findall(text)) - declared


class EveryLoopNameUsedIsDeclared(unittest.TestCase):

    def test_no_golden_references_an_undeclared_loop(self):
        checked = 0
        carrying = 0
        offenders = []
        for path in sorted(GOLDEN_DIR.glob("*.golden.cs")):
            text = path.read_text(encoding="utf-8")
            declared, dangling = _split(text)
            checked += 1
            if declared:
                carrying += 1
            if dangling:
                offenders.append(f"{path.name}: {sorted(dangling)}")
        self.assertGreater(checked, 40,
                           "голденов почти нет — сломан корень, а не код")
        # The denominator RIGHT NEXT TO zero: "0 dangling out of 0 rings
        # carrying anything" and "0 out of 20" print the same and mean the
        # opposite.
        self.assertGreater(
            carrying, 5,
            f"кольца несут лишь {carrying} голденов из {checked} — прибор "
            "смотрит почти в пустоту, и его ноль ничего не стоит")
        self.assertEqual(
            offenders, [],
            "эмитированный C# ссылается на кольцо, которого не объявлял — "
            "два обхода одного списка разошлись:\n  " + "\n  ".join(offenders))

    def test_holes_are_numbered_without_a_gap(self):
        """A gap in numbering is the same discord, but visible before
        substitution.

        `__hl_F1_0, __hl_F1_2` with no `_1` means the declaring traversal
        skipped an opening while the counting one did not (or the other
        way around).
        """
        offenders = []
        for path in sorted(GOLDEN_DIR.glob("*.golden.cs")):
            declared, _ = _split(path.read_text(encoding="utf-8"))
            by_owner: dict[str, list[int]] = {}
            for name in declared:
                match = re.fullmatch(r"__hl_(.+)_(\d+)", name)
                if match:
                    by_owner.setdefault(match.group(1), []).append(
                        int(match.group(2)))
            for owner, indices in by_owner.items():
                indices.sort()
                if indices != list(range(len(indices))):
                    offenders.append(f"{path.name}: {owner} -> {indices}")
        self.assertEqual(
            offenders, [],
            "нумерация проёмов с пропуском:\n  " + "\n  ".join(offenders))

    def test_the_instrument_can_say_no(self):
        """FAIL control: plant a dangling name and require that it be
        found.

        Without it, "no violators" is indistinguishable from "the regex
        catches nothing" — and both regexes here are written to the
        emission's IDIOM, that is, by convention rather than by
        authority.
        """
        good = ("CurveLoop __ol_F1 = new CurveLoop();\n"
                "CurveLoop __hl_F1_0 = new CurveLoop();\n"
                "__loops_F1.Add(__ol_F1);\n__loops_F1.Add(__hl_F1_0);\n")
        declared, dangling = _split(good)
        self.assertEqual(declared, {"__ol_F1", "__hl_F1_0"})
        self.assertEqual(dangling, set(), "чистый образец не должен ловиться")

        bad = good + "__loops_F1.Add(__hl_F1_1);\n"
        _, dangling = _split(bad)
        self.assertEqual(
            dangling, {"__hl_F1_1"},
            "прибор обязан поймать ссылку на необъявленное кольцо")


if __name__ == "__main__":
    unittest.main()
