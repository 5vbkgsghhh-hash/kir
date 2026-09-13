"""Opening-loop sites: eight copies of one loop, seven of them DARK.

WHY A SECOND REGISTRY WHEN THERE IS ALREADY A REGISTRY OF UNPINNED PLURALS.
That one asks the OP about its count: «does the corpus exercise
`create_foundation.holes` at count >= 2». A «yes» closes the op — and says
NOTHING about the rest of the copies of the same loop. **There are more
sites than ops, and a fix in one copy will not reach the others.** This is
"declared here, read there" in CLONE form, and today no instrument speaks to
divergence between clones.

KIND OF LIST: **THE MEMBERSHIP IS COMPLETE BY CONSTRUCTION, THE VERDICTS ARE
A DATED MEASUREMENT.** The set of sites is COMPUTED from the emitters'
sources (:func:`hole_loop_sites`), so a new copy of the loop cannot arrive
silently: the declaration will diverge from what is computed and the test
WILL DEMAND a decision. But "caught / dark" cannot be checked from inside the
set — the measurement requires mutating the emitters one at a time — so the
verdicts stand here with a date, and the WAY to retake them sits alongside:

    venv/bin/python tools/hole_loop_darkness.py     (~1 minute)

MEASURED 12.08.2026, REPRODUCED INDEPENDENTLY BY TWO ZONES:

    sites 8 · caught 1 · DARK 7

The only one caught is `struct_emit.py:246`, and it became so on the VERY
SAME DAY: before `struct_foundation_slab` was refrozen on TWO openings, ALL
EIGHT were dark, meaning a change that drops every opening but the first
passed the whole golden corpus green.

THE TWO KINDS OF DARKNESS ARE SEPARATED BY A REACHABILITY CHECK, AND THIS IS
NOT PEDANTRY. A mutation that did not change the output only proves that it
missed. So each site first gets a crude tag, `__hl_` -> `__ZZH_`:

    reached, but count <= 1            6 sites — a golden exists, it is degenerate
    NOT REACHED AT ALL                 1 site — `authoring.py` / `_emit_floor`

`authoring.py` / `_emit_floor` — floor openings (`_emit_floor`). The tag never
surfaced in a single golden: `holes` equals `null` in ALL THREE goldens where
`create_floor` occurs. "Dark" and "unreached" require DIFFERENT fixes: the
first needs a golden with two openings, the second needs a program where an
opening exists at all.

WHAT THIS LIST DOES NOT SAY. It is about ONE loop — the traversal of the
opening list. Right next to it, `solid_emit` has a SECOND, independent
traversal of the same list (`[f"__hl_{s}_{i}" for i in
range(len(region["holes"]))]`, line 115): the names there are assembled
afresh, and they can diverge from the number of declared loops in exactly the
same way as the two boundaries in `move_elements`. This form is NOT caught
here — `hole_loop_sites()` looks for the idiom `for hi, hole in
enumerate(...)` — and this is stated so that the absence of a record is not
read as the absence of risk.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any
import re
import unittest

IR_DIR = pathlib.Path(__file__).resolve().parent.parent

#: The site idiom: a loop over openings whose body forms the INDEXED loop
#: name `__hl_<s>_<hi>`. Both conditions are mandatory: without the second,
#: `geom.check_holes_relation` would get swept in too (the same loop idiom,
#: but that's VALIDATION, not emission), and the list would lie on the high
#: side.
_LOOP = re.compile(r"^\s*for hi, hole in enumerate\(.+\):\s*$")
_EMITS_INDEXED_LOOP = re.compile(r"__hl_\{s\}_\{hi\}")


def _enclosing_function(tree: ast.AST, lineno: int) -> str:
    """The name of the nearest enclosing function — the stable half of the address."""
    best: Any = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None) or 10 ** 9
            if node.lineno <= lineno <= end:
                if best is None or node.lineno > best.lineno:
                    best = node
    return best.name if best is not None else "<модуль>"


def hole_loop_sites_located() -> dict[tuple[str, str, int], int]:
    """Site -> LINE NUMBER of the loop in the CURRENT source (1-based).

    🔴 WHY A SEPARATE FUNCTION, NOT A SECOND TRAVERSAL AT THE CONSUMER
    (17.08.2026). A site's key deliberately does NOT carry a line number —
    that is the whole point of the 13.08 fix: the address must describe the
    site, not its neighbors above it. But `tools/hole_loop_darkness.py`
    mutates the SOURCE, and it needs precisely the line.

    The temptation was to write its own traversal inside the instrument. That
    is exactly the project's named defect: two copies of the definition of
    "what a site is," connected to nothing, where a divergence would read as
    a fact about the code. So there is ONE traversal, and it lives here, next
    to the verdicts; `hole_loop_sites()` holds its keys, and the instrument
    takes the values.

    The number is 1-based and points to the line of the LOOP ITSELF (`for hi,
    hole in ...`). The site's body is the following lines; which of them
    carries `__hl_{s}_{hi}` is NOT asserted here, and the consumer must find
    it itself, not assume it is the first one.
    """
    out: dict[tuple[str, str, int], int] = {}
    for path in sorted(IR_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        try:
            tree = ast.parse(source)
        except SyntaxError:                                    # noqa: PERF203
            continue
        seen: dict[str, int] = {}
        for i, line in enumerate(lines):
            if not _LOOP.match(line):
                continue
            body = "\n".join(lines[i + 1:i + 4])
            if not _EMITS_INDEXED_LOOP.search(body):
                continue
            fn = _enclosing_function(tree, i + 1)
            seen[fn] = seen.get(fn, 0) + 1
            out[(path.name, fn, seen[fn])] = i + 1
    return out


def hole_loop_sites() -> set[tuple[str, str, int]]:
    """(module, ENCLOSING FUNCTION, its ordinal number within it). Authority —
    THE SOURCE.

    THE KEY WAS A LINE NUMBER BEFORE 13.08, AND THAT DESCRIBED NOT THE SITE
    BUT ITS NEIGHBORS ABOVE IT. The registry turned red from ANY edit above
    it — someone else's and harmless. Measured by the SUITE zone during a
    merge: declared `1350 · 3068 · 5015`, while the line WITHOUT anyone's new
    branch already gave `1403 · 3121 · 5068`. Someone else's work shifted two
    of the three sites; the third was finished off by the refusal fix in
    `_emit_filled_region` (the very one where the `bound_diags[:1]` slice was
    removed) — `5068 → 5189`.

    **The author of a fix who never touched openings AT ALL got a red test
    about openings.** This is the same class we spent the whole day fixing:
    a key by APPEARANCE (position in the file) instead of a key by ORIGIN
    (what site this actually is).

    The ordinal number is needed because one function can carry SEVERAL
    sites: `emit_ceiling` holds two (by the CONTOUR sketch and by the
    outline), and their verdicts differ. It is counted in order of
    appearance in the source — swapping two sites WITHIN one function will
    change the keys, and that is honest: the order changed, so what the
    verdicts describe changed.

    As of 17.08.2026 these are the KEYS of `hole_loop_sites_located()`, not a
    second traversal: the definition of "what a site is" must be singular,
    otherwise the instrument and the test will diverge silently — the very
    named defect this whole file exists for.
    """
    return set(hole_loop_sites_located())


#: The declaration. The key is the site, the value is a VERDICT with a date
#: and a reason. Diverge from what is computed, and the test turns red: a new
#: copy of the loop must get either a golden or an explicit "dark, here's
#: why" line.
SITE_VERDICTS: dict[tuple[str, str, int], str] = {
    ("struct_emit.py", "_emit_foundation_slab", 1):
        "12.08.2026 ЛОВИТСЯ — struct_foundation_slab (два проёма, 4 и 5 "
        "точек). Единственная ловимая из восьми, и стала ею в тот же день",
    ("arch_emit.py", "emit_ceiling", 1):
        "12.08.2026 ТЁМНАЯ, достижима — потолок по эскизу CONTOUR; голден "
        "arch_ceiling_contour есть, но проёмов не несёт",
    ("arch_emit.py", "emit_ceiling", 2):
        "12.08.2026 ТЁМНАЯ, достижима — потолок по контуру; arch_ceiling "
        "несёт ОДИН проём, мощности 1 не хватает по построению",
    ("authoring.py", "_emit_floor", 1):
        "12.08.2026 ТЁМНАЯ И НЕ ДОСТИГАЕТСЯ ВОВСЕ — проёмы перекрытия "
        "(_emit_floor). Контроль достижимости (метка __hl_ -> __ZZH_) не "
        "проступил ни в одном голдене: holes равен null во всех трёх "
        "голденах, где create_floor встречается. Починка ДРУГАЯ, чем у "
        "остальных: нужна программа, где проём вообще есть",
    ("authoring.py", "_emit_floor_contour", 1):
        "12.08.2026 ТЁМНАЯ, достижима — проёмы по эскизу CONTOUR",
    ("authoring.py", "_emit_filled_region", 1):
        "12.08.2026 ТЁМНАЯ, достижима — проёмы с точечным форматом (pt=fmt)",
    ("site_emit.py", "_region_loops_cs", 1):
        "12.08.2026 ТЁМНАЯ, достижима — проёмы площадки/подобласти",
    # 🔴 THE NINTH SITE, ARRIVED WITH THE FAMILY-AUTHORING WAVE (21.08.2026),
    # verdict rendered on 21.08 by the INSTRUMENT (`tools/hole_loop_darkness.py`),
    # not by eye: "NOT reachable, DARK".
    #
    # And here is the subtlety that must not be swallowed. A program with an
    # opening on `author_family` DOES EXIST — `auth_family_arc_hole` in the
    # GATE corpus (`gate_runner.py`, an arc in the profile plus a rectangular
    # opening). But the reachability probe runs `test_golden.py`, i.e. the
    # GOLDEN corpus, and never sees the gate programs at all. So "NOT
    # reachable" here means "not reachable BY THE CORPUS DOING THE
    # MEASURING," not "nobody builds openings on this family."
    #
    # The fix is therefore ONE LINE IN SUBSTANCE and is deliberately not made
    # here: it needs a GOLDEN with `author_family` carrying an opening. That
    # is an edit to the golden corpus — someone else's shelf, and it must not
    # be substituted with a weakened verdict.
    ("family_author_emit.py", "_profile_cs", 1):
        "21.08.2026 ТЁМНАЯ, НЕ достигается корпусом ГОЛДЕНОВ — проёмы "
        "профиля авторского семейства. Программа с проёмом есть в корпусе "
        "ВОРОТ (auth_family_arc_hole), но зонд достижимости смотрит только "
        "голдены. Чинит голден с author_family и проёмом",
    ("solid_emit.py", "_loops_cs", 1):
        "12.08.2026 ТЁМНАЯ, достижима — проёмы профиля тела. У этой площадки "
        "рядом ВТОРОЙ независимый обход того же списка (строка 115, "
        "range(len(...))), и он этим списком НЕ ловится — см. докстринг",
}


#: RENUMBERING 13.08.2026 — NOT A REVISION OF VERDICTS. Three sites in
#: `authoring.py` moved, the loops are the same, the verdicts are the same.
#: Who shifted them is MEASURED, not assumed: on line `d8346967`, WITHOUT
#: this branch, they already stood at 1403/3121/5068, meaning the
#: declaration had diverged from the source BEFORE the merge; the third was
#: additionally shifted by the spatial-mark wave (5068 -> 5179).
#:
#: AND THE CONSEQUENCE WORTH SAYING OUT LOUD: a registry keyed by LINE NUMBER
#: turns red from ANY edit above the site — including someone else's and
#: harmless one. This is the same kind of proxy as "node count instead of
#: cost": the site's address describes not the site but its neighbors above
#: it. I did not fix this here — the registry belongs to someone else's
#: zone, and replacing the key with something stable (the enclosing
#: function's name + the loop's ordinal number within it) is a rework, not a
#: renumbering.


class TheSiteListIsDerivedNotRemembered(unittest.TestCase):

    def test_the_declaration_matches_the_source(self):
        computed = hole_loop_sites()
        declared = set(SITE_VERDICTS)
        self.assertEqual(
            computed, declared,
            "объявление разошлось с исходником.\n"
            f"  новые площадки: {sorted(computed - declared)}\n"
            f"  исчезли: {sorted(declared - computed)}\n"
            "Новая копия петли обязана получить ВЕРДИКТ: либо голден, "
            "который её ловит, либо строку «тёмная, вот причина». "
            "Переснять вердикты: venv/bin/python tools/hole_loop_darkness.py")

    def test_every_site_carries_a_dated_verdict(self):
        for site, verdict in SITE_VERDICTS.items():
            with self.subTest(site=site):
                self.assertTrue(verdict.strip(), f"{site}: вердикт пуст")
                self.assertRegex(
                    verdict, r"\d{2}\.\d{2}\.\d{4}",
                    f"{site}: у вердикта нет даты — замер без даты не "
                    f"отличить от догадки")

    def test_the_detector_is_not_vacuous(self):
        """FAIL control for the detector itself.

        A regex that diverged from the loop idiom would return an empty set,
        and the list would become vacuously green — looking exactly like
        ordinary, healthy work. The threshold is 2, not 1: a single site is
        also the "no clones" state, and the whole list exists precisely for
        clones.
        """
        self.assertGreaterEqual(
            len(hole_loop_sites()), 2,
            "детектор площадок нашёл меньше двух — идиома цикла разошлась с "
            "регуляркой, и список молча перестал что-либо утверждать")

    def test_validation_loops_are_not_counted_as_emission_sites(self):
        """FAIL control in the other direction: the list must not lie on the
        HIGH side.

        `geom.check_holes_relation` traverses openings with the SAME idiom,
        but it is VALIDATION, not emission: it does not build an indexed loop
        name. Were it to land among the sites, a "dark emission" verdict
        would be pinned on code that emits nothing.
        """
        self.assertNotIn(
            ("geom.py", 190), hole_loop_sites(),
            "цикл валидации сочтён площадкой эмиссии — условие про "
            "__hl_{s}_{hi} перестало работать")


if __name__ == "__main__":
    unittest.main()


class TheKeyDescribesTheSiteNotItsNeighbours(unittest.TestCase):
    """The key must survive a harmless edit ABOVE the site (13.08.2026).

    Before this date the key was `(module, line number)`, and the registry
    turned red from any insertion above it — someone else's, and unrelated to
    openings. Measured during a merge: declared `1350 · 3068 · 5015`, the
    line WITHOUT new branches gave `1403 · 3121 · 5068`, and the refusal fix
    in `_emit_filled_region` (removing the `bound_diags[:1]` slice) finished
    off the third to `5189`.

    **An author who never touched openings got a red test about openings.**
    """

    def _sites_of(self, source: str) -> set[tuple[str, str, int]]:
        """The same computation as `hole_loop_sites`, but over TEXT.

        A file traversal won't do here: it reads the tree, and we need to
        compare TWO states of one module, the second of which does not exist
        on disk and must not exist.
        """
        lines = source.splitlines()
        tree = ast.parse(source)
        seen: dict[str, int] = {}
        out: set[tuple[str, str, int]] = set()
        for i, line in enumerate(lines):
            if not _LOOP.match(line):
                continue
            if not _EMITS_INDEXED_LOOP.search("\n".join(lines[i + 1:i + 4])):
                continue
            fn = _enclosing_function(tree, i + 1)
            seen[fn] = seen.get(fn, 0) + 1
            out.add(("<проба>", fn, seen[fn]))
        return out

    #: The real site idiom — copied from the emitter, not invented.
    _SITE = (
        "def _emit_thing(op, ver, stamp, isolation):\n"
        "    s = 'X'\n"
        "    region = op['__region__']\n"
        "    for hi, hole in enumerate(region['holes']):\n"
        '        loops.append(f"CurveLoop __hl_{s}_{hi} = new CurveLoop();")\n'
        "    return loops\n"
    )

    def test_a_harmless_line_above_does_not_move_the_key(self):
        """THE CONTROL the key was changed for."""
        before = self._sites_of(self._SITE)
        after = self._sites_of("# безобидный комментарий чужой правки\n"
                               "import os  # и чужой импорт\n" + self._SITE)
        self.assertEqual(
            before, after,
            "вставка ДВУХ строк выше площадки сдвинула ключ — реестр снова "
            "описывает соседей сверху, а не площадку")
        self.assertEqual(
            {("<проба>", "_emit_thing", 1)}, before,
            f"проба не опознала собственную площадку: {before}")

    def test_moving_the_site_to_another_function_DOES_move_the_key(self):
        """FAIL CONTROL: the key must be CAPABLE of changing.

        Without it, the first test is green on an instrument that returns a
        constant. A site moving to a different function is a genuine change
        of subject, and the verdict about it must demand reconsideration.
        """
        renamed = self._SITE.replace("_emit_thing", "_emit_other_thing")
        self.assertNotEqual(
            self._sites_of(self._SITE), self._sites_of(renamed),
            "переезд площадки в другую функцию ключ НЕ изменил — прибор "
            "возвращает одно и то же независимо от предмета")

    def test_a_second_site_in_one_function_gets_its_own_ordinal(self):
        """Two sites in one function must be distinguishable.

        `emit_ceiling` holds exactly this case, and their verdicts differ:
        one is about the CONTOUR sketch, the other about the outline.
        """
        doubled = self._SITE.replace("    return loops\n", "")
        doubled += (
            "    for hi, hole in enumerate(region['outer_holes']):\n"
            '        loops.append(f"CurveLoop __hl_{s}_{hi} = new CurveLoop();")\n'
            "    return loops\n")
        self.assertEqual(
            {("<проба>", "_emit_thing", 1), ("<проба>", "_emit_thing", 2)},
            self._sites_of(doubled),
            "вторая площадка в той же функции не получила своего номера — "
            "две разные площадки слились бы в один вердикт")
