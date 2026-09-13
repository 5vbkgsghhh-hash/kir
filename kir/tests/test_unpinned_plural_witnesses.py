"""Plural witnesses whose plural branch is exercised by NOT A SINGLE golden.

THE KIND OF LIST: **COMPLETE BY CONSTRUCTION — BUT ONLY WITH RESPECT TO OPS, AND THIS MUST BE READ
LITERALLY.** The set of OPS is not maintained by hand — it is COMPUTED from two
authorities and checked against what is declared:

    the set of plural ops        <- `spec.OPS` (the registry), by parameter kind
    the set of checked goldens   <- `PROGRAMS` intersected with the golden catalog

**But the set of parameter KINDS is maintained by hand** (`PLURAL_KINDS`), and until
the evening of 12.08.2026 it was silently missing four kinds — the file was "complete by
the construction of ITS OWN LIST", not of the registry. The hole is closed not by memorizing the
missing names, but by COVERAGE: `PLURAL_KINDS | SCALAR_KINDS` must cover
the entire inventory of the registry's kinds, and a new kind turns
`test_every_kind_in_the_registry_is_classified` red, demanding an explicit decision.

So "no entry" here means "no such op exists", not "we don't know". The list
cannot go stale silently: add a golden — and the declaration will drift apart from
the computed value, the test will turn red and WILL DEMAND a decision. This is the same discipline as
the golden ratchet, and the opposite of the load-sensitive list
(`tests/test_load_sensitive_tests.py`), which is closed but NOT complete.

THE PROBE WAS ASKING FOR A LABEL, NOT FOR THE CONTENTS — FIXED ON THE EVENING OF 12.08.2026.
Before this fix, "pinned" meant "the string `// <op name> ` occurs somewhere in the bytes of some
checked golden". This is a label, and it lied IN BOTH DIRECTIONS:

* **falsely OPEN.** The list's only entry read «`create_foundation`:
  0 goldens at all». There were actually TWO goldens (`struct_foundation_slab`,
  `struct_foundation_isolated`), both in `PROGRAMS`, both checked. The probe did not
  see them because the emitter writes `// create_foundation(slab) F1` — with
  the subtype in parentheses. FOUR ops carry this parenthesized label
  (`create_foundation`, `create_opening`, `create_railing`,
  `create_topography`), only one of them plural so far, and the blindness would have been
  waiting for the rest silently;
* **falsely CLOSED, and that costs more.** The probe considered `create_floor` pinned:
  the string `// create_floor ` sits in the bytes. But the op occurs in THREE
  checked goldens, and in all three `holes` equals `null` — the plural
  branch had NEVER executed even once. `create_ceiling` is the same, with one
  contour across two goldens.

Now what is asked is the CONTENTS OF THE PROGRAM: what cardinality the plural
parameter has in the checked goldens. The threshold is **TWO**, and it is not arbitrary: with
ONE element, the boundary of a handwritten loop is invisible by construction, because
`xs`, `xs[:1]`, and `xs[-1:]` produce byte-for-byte the same thing. Exactly the argument by
which `move_elements` required THREE targets, not one.

WHY THE LIST EXISTS AT ALL — THE HOLE IS MEASURED, NOT ASSUMED (12.08.2026).
A plural witness walks its set through a hand-written LOOP: there is no shared
helper (14 hand-written `for`s plus 34 `foreach`s in `authoring.py`, with different
idioms — `< Count`, `+ 1 < Count`, `< {n_edges}` from Python, one loop
deliberately starting at one), and `move_elements` has TWO such loops, independent, over
one list. There is no reference against which to check the boundary by eye, and
so an error in it is indistinguishable from intent.

`move_elements` LEFT THIS LIST ON 12.08 (merge `79d694db`): it got a
checked golden, `auth_move_and_change_type`, and it pins BOTH boundaries —
`__mti_ME1` and `__mtj_ME1` — on a program with THREE targets. Three, not one,
because with a single target an off-by-one is invisible by construction: there is nothing to lose.
Verified on the merged tree, rather than taken on faith. The mutation that all of this was
for is now caught by this golden and brings down EXACTLY ONE subtest.

A mutation on a representative of the class (`move_elements`, the check loop boundary
`__mtEls.Count` -> `__mtEls.Count - 1`, meaning the LAST target of every transfer
is never checked):

    the full suite   7 failed / 6140 passed / 34 skipped / 3 xfailed / 7750
                      subtests — BYTE-FOR-BYTE the same as the baseline, before and after
    the Roslyn gate  6/6
    the probe        targets in the list 2, loop boundary `1`, ok: True, diagnostics []

`create_foundation` LEFT THIS LIST ON THE EVENING OF 12.08, and not by starting a new file:
`struct_foundation_slab` was RE-FROZEN on a program with TWO openings (4 and 5
points — deliberately different cardinalities, so a contour reordering would show up in the
bytes). Determinism was proven BEFORE freezing, using two processes with different
`PYTHONHASHSEED`: 10 272 bytes, sha256 `636133231e1c77a0…`, byte-for-byte equal.
The mutation "take only the first contour" (`holes` -> `holes[:1]` in
`struct_emit.emit_foundation`) used to survive against the old single-opening program and
brings down the new one.

The boundaries of this finding are named so it does not get cited more broadly than it should:
* **not a live defect** — today the boundary is correct, this is an UNPROTECTED SURFACE;
* the plausibility of an off-by-one is an **argument** ("the most ordinary kind of mistake"), not a
  measurement: `git log -G` on the emitted loops turned up 5 commits, all of them ADDING a loop
  along with the capability, with 0 boundary fixes — and this zero is declared
  UNINFORMATIVE prior to a run, because an unpinned boundary would not even
  have been fixed — nobody would have noticed it;
* **the cost is small**: across the three of them, 11 occurrences out of 17 158 in the live corpus
  (`create_pipe_system` 7, `create_dimension` 4,
  `create_angular_dimension` 0). It does not reach as far as the ordinals
  (56 559 walls).

WHAT THIS LIST DOES NOT SAY. An op that HAS a checked golden is pinned only IN THAT
CONFIGURATION which the golden exercises; an emitter branch not engaged by it
will slip through even with a golden present. Absence from this list is not a certificate.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from kir import spec
# THE IMPORT IS AT MODULE LEVEL, NOT INSIDE THE TEST, AND THIS IS NOT A STYLE CHOICE.
# `test_golden`, on import, does `os.environ.setdefault("KIR_REJECTIONS_PATH")`.
# Imported INSIDE the test, it would change the process environment mid-test, and
# the guard in `conftest.py` honestly catches this in teardown as a leak. At module
# level, the change happens during COLLECTION, before the environment snapshot, and dirties nobody.
from kir.tests.test_golden import PROGRAMS

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"

#: Parameter kinds whose contents the emitter walks with a HAND-WRITTEN LOOP.
#:
#: THE CRITERION WAS FIXED ON THE EVENING OF 12.08.2026, AND THIS IS A FINDING AGAINST ITSELF.
#: The former criterion read "one op -> many elements", and it DID NOT MATCH
#: the defect this list was set up for: what we are protecting is the BOUNDARY OF THE
#: HAND-WRITTEN LOOP, and it arises even where an op produces ONE element from many points
#: (`_loop_pts` runs `range(n)` with `% n`; roof slopes use `enumerate(slopes)`).
#: The list was following a weaker definition and was therefore blind by construction
#: to four kinds at once. Measured on the merged line:
#:
#:     sel_list  create_multistory_stairs.levels   cardinality 2  (pinned)
#:     pts       outline on six ops                cardinality 4  (pinned)
#:     fields    query_list.fields                 cardinality 4  (pinned)
#:     slopes    create_roof.slopes                cardinality 0  <- A HOLE
#:
#: Three of the four turned out to be closed BY ACCIDENT — nobody pinned them deliberately,
#: the corpus's programs simply carry four points each. The fourth is open.
PLURAL_KINDS = frozenset({
    "member_ops", "placements", "graph_nodes", "graph_segments",
    "pts_list", "refs_w", "filters",
    # added on 12.08 under the fixed criterion:
    "sel_list", "pts", "slopes", "fields",
    # 🔴 `enum_list` — МНОЖЕСТВЕННЫЙ ПО ФОРМЕ, И КРИТЕРИЙ ЗДЕСЬ ВЫПОЛНЕН ПО
    # ИЗМЕРЕНИЮ, А НЕ ПО ИМЕНИ (13.09.2026). Критерий файла: длина
    # эмитированного C# РАСТЁТ с мощностью значения. У `query_level_plan.include`
    # растёт: каждый включённый род следов — свой сборщик и свой цикл строк, так
    # что include=["walls"] короче include=["walls","floors","columns",
    # "openings"] на три блока. Ставится рядом с `fields` как его точный
    # родственник по форме.
    "enum_list",
    # ── 21.08.2026: TWO KINDS, AND BOTH MEASURED BY THE GROWTH OF THE TEXT ───────────────
    #
    # 🔴 THE CRITERION IS VERIFIED BY EXECUTION, NOT READ OFF BY NAME. The mark of
    # a hand-written loop is that the length of the emitted C# GROWS with the value's cardinality.
    # Measured with `compile_program` on 2026:
    #
    #   solid_parts  2 parts -> 265 lines,   3 parts -> 297 lines
    #   surface      4 points -> 14033 chars, 9 -> 14305, 16 -> 14613
    #
    # Both are LOOPING. A control in the same direction: `dir_xyz` gives 11863
    # characters for ANY direction — there is no loop, the kind is scalar.
    "solid_parts", "surface",
    # ── 24.08.2026: THE LAYER CAKE ────────────────────────────────────────────
    # This kind arrived on 23.08 with `create_wall_type` and for a whole day was not assigned to
    # either set — exactly the silence this file is built to catch.
    #
    # The criterion is verified by EXECUTION, not by name. Measured with `compile_program`
    # on 2026, the same instrument as the neighbors above:
    #
    #   wall_layers  1 layer  -> 212 lines / 10681 chars
    #                2 layers -> 213 lines / 10867
    #                3 layers -> 214 lines / 11051
    #                5 layers -> 216 lines / 11419
    #
    # One line per layer and ~184 characters per layer — LINEAR growth with cardinality, that
    # is, a hand-written loop: `__lay_*.Add(new CompoundStructureLayer(...))` for
    # every layer, plus its own entry in the three witness-expectation arrays.
    "wall_layers",
})

#: The explicit COMPLEMENT: kinds whose contents are NOT walked by a hand-written loop.
#: The list is closed, not for the sake of tidiness — together with `PLURAL_KINDS` it must cover
#: the ENTIRE inventory of the registry's kinds, and this is checked by the test below. Otherwise a new
#: parameter kind arrives UNCLASSIFIED and silently falls into neither
#: list — exactly the blindness this very file just recovered from.
SCALAR_KINDS = frozenset({
    "arc", "bool", "deg", "enum",
    # `identity` (13.09.2026) — ОДНА прочитанная личность, не список: пара
    # {unique_id, version_guid} описывает РОВНО ОДИН элемент, и у неё нет
    # мощности, которую свидетель мог бы обходить. Отсюда же отказ на этапе
    # компиляции, когда `expected_identity` ставят к `move_elements` с
    # несколькими целями: одна база не описывает много целей.
    "identity",
    "int", "kind_enum", "mesh", "mm", "num",
    "path", "path3", "pt_view2d", "pt_xy", "pt_xyz", "pts_xyz", "region",
    "sel", "spiral", "str", "str_long", "target", "target_w", "value",
    # 21.08.2026, both measured by that same growth of the text — or rather, by its ABSENCE:
    #   dir_xyz  11863 characters for any direction — a ray has no cardinality
    #   plane    three fields of fixed shape; no cardinality by construction
    # 🔴 Both were late not from a wave's oversight, but because coverage of
    # `PLURAL_KINDS | SCALAR_KINDS` is checked ONLY by this test, and it
    # stayed silent along with its three neighbors: the solo-op corpus was bringing down their
    # collection on import. `surface` stood here unclassified for TWO WHOLE DAYS.
    "dir_xyz", "plane",
})

#: The cardinality threshold. ONE element does not pin the loop boundary: `xs`, `xs[:1]`,
#: and `xs[-1:]` emit the exact same bytes.
PLURAL_FLOOR = 2

#: The declaration. It will drift from the computed value — the test will turn red and demand a decision.
#: FIVE entries on the evening of 12.08 instead of one, and this is not a regression but the LIFTING OF
#: BLINDNESS: the previous probe was looking for the label `// <op> ` in the bytes and therefore considered
#: `create_floor`/`create_ceiling` pinned merely by the op's presence.
#: Their `holes` cardinality is 0 and 1. Not a single entry here is added on
#: suspicion: each one carries a MEASURED cardinality and the golden where it is maximal.
#:
#: FOUR entries were removed on the morning of 12.08 — not "to make it go green", but because
#: each one got a CHECKED golden that exercises EXACTLY the plural branch:
#:   move_elements            3 targets, and BOTH boundaries `__mtEls_ME1.Count` sit
#:                            in the bytes — two independent loops over one
#:                            list, pinning one would have left the second unpinned
#:   create_dimension         2 refs, ReferenceArray×2 in the bytes
#:   create_angular_dimension 2 refs, the same golden (auth_annotation)
#:   create_pipe_system       3 nodes / 2 segments, Pipe.Create×2
#: The FIFTH was removed in the evening: `create_foundation` — `struct_foundation_slab`
#: was re-frozen with TWO openings (4 and 5 points).
#: Two orphan files that the dimension entries referenced were DELETED on 12.08
#: (`d9da9f90`): they had NEVER been in `PROGRAMS`, there was nothing to check against.
UNPINNED_PLURAL: dict[str, str] = {
    # 🔴 ВОСЬМАЯ ЗАПИСЬ, 13.09.2026, И ОНА ЧЕСТНО «НЕПРИШПИЛЕНА КОРПУСОМ», а не
    # «не проверена». `query_level_plan.include` — вид `enum_list`, плюральный по
    # критерию этого файла: длина эмитированного C# РАСТЁТ с мощностью значения
    # (каждый включённый род следа — свой коллектор и свой блок строк; измерено:
    # include=["walls"] короче четырёх родов на три блока).
    #
    # Почему запись здесь, а не голден: `_max_cardinality` читает только
    # `test_golden.PROGRAMS`, а это корпус ПИШУЩИХ программ — он ловит изменение
    # эмиссии здания. Читающий оп в нём не стоит ни один из семи, и ставить туда
    # первый значило бы решить за корпус, что он теперь и про чтение тоже.
    #
    # Мощность при этом ПРИШПИЛЕНА — своим эталоном, не голденом:
    # `test_the_sheet_gets_a_background.py::test_include_narrows_the_emission_which_is_what_makes_the_lever_real`
    # сверяет, что один род даёт КОРОЧЕ четырёх и что при include=["walls"] в
    # коде нет `OST_Floors`. То есть рычаг доказан числом; не доказано только то,
    # что его сторожит КОРПУС.
    #
    # Снимается в один ход: читающая программа в `test_golden.PROGRAMS` с двумя
    # опами разной мощности `include` (скажем, 1 и 4), свой эталон и своя строка
    # в `UNREVIEWED_GOLDENS`.
    "query_level_plan": ("include: рычаг доказан своим эталоном "
                         "(test_the_sheet_gets_a_background), но корпус голденов "
                         "читающих опов не держит вовсе — 0 из 7"),
    # 🔴 SEVENTH ENTRY, 2026-08-24, AND IT IS NOT "FORGOTTEN" BUT "THE PROBE
    # READS THE WRONG CORPUS." The loop over layers RUNS — the fixture
    # `catalog_wall_type` builds a type from TWO layers (Structure 120 +
    # Insulation 80) and checks it byte-for-byte on six versions in both
    # insulations. But it lives in the corpus
    # `test_emitter_scope_contract.PROGRAMS`, while `_max_cardinality` reads
    # ONLY `test_golden.PROGRAMS`, where the cardinality of `layers` is zero.
    #
    # Recorded here, not "fixed" by extending the probe, because it is more
    # honest to name the instrument's boundary than to silently move it: the
    # two corpora answer DIFFERENT questions (golden — an emission-change
    # detector, scope — a scope-of-visibility contract), and merging them in
    # one move would mean deciding for both.
    #
    # The entry can be lifted in exactly one move: a program in
    # `test_golden.PROGRAMS` with TWO operations of different layer
    # cardinality (say 3 and 1), its own reference, and its own line in
    # `UNREVIEWED_GOLDENS` — the same move by which, on 08.12, the opening
    # boundary of `struct_foundation_slab` was pinned.
    "create_wall_type":
        "layers (wall_layers): мощность 0 в `test_golden.PROGRAMS`. Цикл "
        "ЕСТЬ и замерен ростом C# (1/2/3/5 слоёв -> 10681/10867/11051/11419 "
        "символов, ~184 символа на слой), и он ГОНЯЕТСЯ фикстурой "
        "`catalog_wall_type` с двумя слоями — но в корпусе `scope:`, "
        "которого этот зонд не читает",
    # 🔴 SIXTH ENTRY, 2026-08-21, AND IT WAS FOUND NOT BY SEARCH BUT BY
    # CONSEQUENCE. The `surface` kind was classed as plural BY MEASUREMENT
    # (the length of the C# grows with the number of control points:
    # 4 -> 14033 characters, 9 -> 14305, 16 -> 14613), and in the same
    # instant it turned out there is NOTHING to run this boundary against:
    # `create_surface` does not occur in A SINGLE reference of the corpus —
    # cardinality 0, not 1 or 2.
    #
    # This is not "forgot to pin": the op's counterpart move `capture_gap`
    # is young (08.20) and no one has entered it into the corpus yet. The
    # entry stands here because SILENCE would be worse: without it, "five
    # plural ops unpinned" would read as complete, when it is six.
    #
    # The entry can be lifted in exactly one move: a program in `PROGRAMS`
    # with a grid of NOT FEWER THAN TWO control points on each axis, and its
    # own reference.
    "create_surface":
        "surface (surface): мощность 0 — оп не встречается ни в одном "
        "эталоне корпуса. Граница цикла по контрольным точкам не гоняется "
        "ничем; замер роста C# (4/9/16 точек -> 14033/14305/14613 символов) "
        "доказывает, что цикл ЕСТЬ, а пина у него нет",
    "create_floor":
        "holes (pts_list): мощность 0. Оп встречается в ТРЁХ сверяемых "
        "голденах (full_house_v1, struct_area_reinforcement_slabs, "
        "sweep_slab_edge_bottom_ref), по одному опу в каждом, и во всех "
        "трёх `holes` равен null. Прежний зонд считал оп пришпиленным по "
        "ярлыку `// create_floor `; ветка с проёмами не выполнялась НИ "
        "РАЗУ. Цикл — тот же `for hi, hole in enumerate(holes)`, что у "
        "create_foundation, но своя копия в authoring._emit_floor",
    "create_ceiling":
        "holes (pts_list): мощность 1. Оп в ДВУХ голденах — arch_ceiling "
        "(один контур) и arch_ceiling_contour (null). Вырожденный случай: "
        "границу цикла один контур не пиннит",
    "query_count":
        "where (filters): мощность 0 — ни один сверяемый голден не задаёт "
        "предикатов. ВНИМАНИЕ: род риска здесь ДРУГОЙ. `_emit_collector` "
        "не содержит рукописного цикла — это закрытая цепочка `if key in "
        "where` по трём известным ключам, и непришпинена КОМПОЗИЦИЯ "
        "предикатов, а не граница обхода. Закрывать эту запись доводом "
        "про off-by-one нельзя",
    "query_list":
        "where (filters): мощность 1 (list_walls_level1, один предикат "
        "level_name). Тот же род риска, что у query_count — композиция "
        "двух и более `.Where(...)` в цепочке не пришпинена. ВТОРОЙ его "
        "плюральный параметр `fields` мощности 4 и пришпилен — запись "
        "держится на `where`, и снять её можно только по нему",
}

#: THE SIXTH WAS LIFTED BY THE MERGE ON THE EVENING OF 08.12: `create_roof`.
#: The entry was opened by the gate line ("slopes: cardinality 0 — NOT ONE
#: program of the checked corpus sets slopes"), closed by the lead line with
#: the golden `roof_gable_slopes` (`4e26c65f`), and the two met only here.
#: Lifted not by editing the declaration under the red ratchet, but by
#: verifying that it is PRECISELY the plural branch that runs, exactly as
#: the test text requires:
#:     slopes = [30.0, None, 30.0, None]      cardinality 4 (threshold 2)
#:     tan(radians(30)) = 0.577350269         STANDS IN THE BYTES
#:     eaves -1.0 (edge at the level)         2
#: That is, both independent traversals of the one list — the handwritten
#: `for k, pitch in enumerate(slopes)` (authoring.py:3007) and the
#: generator one at 2931 — go through four elements, of which two lead into
#: one eaves branch and two into the other. A neighboring configuration
#: cannot turn red this way.


def _plural_params() -> dict[str, tuple[str, ...]]:
    """Op -> its plural parameters. The authority is the registry, not memory."""
    out: dict[str, tuple[str, ...]] = {}
    for name, op in spec.OPS.items():
        ps = tuple(p.name for p in op.params if p.kind in PLURAL_KINDS)
        if ps:
            out[name] = ps
    return out


def _compared_goldens() -> set[str]:
    """Goldens that are ACTUALLY compared: intersect the catalog with PROGRAMS.

    We ask `PROGRAMS`, not the catalog. On 08.12 a census asked the catalog
    and declared two ops pinned; four files there are orphans, added by hand
    back on 07.17 and never having been in `PROGRAMS` at all.
    """
    on_disk = {p.name[: -len(".golden.cs")] for p in GOLDEN_DIR.glob("*.golden.cs")}
    return on_disk & set(PROGRAMS)


def cardinality(value) -> int:
    """How many elements a plural parameter carries.

    A dict is counted on par with a list ON PURPOSE: the `filters` kind
    stores predicates as a dict (`{"level_name": "Floor 1"}`), and the first
    census, which measured only `isinstance(v, list)`, declared `query_list`
    zero — an artifact of its own, caught by printing RAW values rather than
    parsing the output. Absence and `None` are an honest zero too:
    `pts_list` counts `None` and `[]` as the same "no openings"
    (authoring_validation).
    """
    if isinstance(value, (list, tuple, dict)):
        return len(value)
    return 0


def _max_cardinality() -> dict[tuple[str, str], tuple[int, str | None]]:
    """(op, parameter) -> (maximum cardinality, golden where it is reached)."""
    plural = _plural_params()
    best: dict[tuple[str, str], tuple[int, str | None]] = {
        (op, p): (0, None) for op, ps in plural.items() for p in ps}
    for gname in sorted(_compared_goldens()):
        for o in PROGRAMS[gname].get("ops", []):
            nm = o.get("op")
            for pname in plural.get(nm, ()):
                n = cardinality(o.get(pname))
                if n > best[(nm, pname)][0]:
                    best[(nm, pname)] = (n, gname)
    return best


def _unpinned() -> set[str]:
    """An op is unpinned if EVEN ONE of its plural parameters falls short.

    "Even one," not "all": `create_group` has two independent plural
    parameters (`member_ops`, `placements`), the routers have nodes and
    segments, and each is traversed by ITS OWN handwritten loop. Pinning one
    says nothing about the other.
    """
    best = _max_cardinality()
    return {op for (op, _), (n, _g) in best.items() if n < PLURAL_FLOOR}


class TheListIsDerivedNotRemembered(unittest.TestCase):
    def test_the_declaration_matches_what_the_authorities_say(self):
        computed = _unpinned()
        declared = set(UNPINNED_PLURAL)
        best = _max_cardinality()
        table = "\n".join(
            f"    {op:28} {p:12} {n:>3}  {g or '—'}"
            for (op, p), (n, g) in sorted(best.items()))
        self.assertEqual(
            computed, declared,
            "объявление разошлось с вычисленным.\n"
            f"  появились непришпиленными: {sorted(computed - declared)}\n"
            f"  перестали быть непришпиленными: {sorted(declared - computed)}\n"
            "Это не повод править объявление молча: если оп ПЕРЕСТАЛ быть "
            "непришпиленным, убедись, что голден гоняет ИМЕННО плюральную "
            f"ветку, а не соседнюю конфигурацию.\n  замер:\n{table}")

    def test_every_entry_says_why(self):
        for op, reason in UNPINNED_PLURAL.items():
            with self.subTest(op=op):
                self.assertTrue(reason.strip(), f"{op}: причина пустая")

    def test_the_plural_set_still_comes_from_the_registry(self):
        # Authority control: if the kinds of parameters get renamed, the set
        # collapses to empty and the list turns vacuously green.
        self.assertGreaterEqual(
            len(_plural_params()), len(UNPINNED_PLURAL),
            "плюральных опов меньше, чем непришпиленных — реестр спрошен неверно")

    def test_every_kind_in_the_registry_is_classified(self):
        """A NEW KIND OF PARAMETER MUST NOT ARRIVE UNCLASSIFIED.

        This fixes this very file's own blindness (2026-08-12): it took the
        set of OPS from the authority, but held the set of KINDS by hand —
        and so did not see `sel_list`, `pts`, `slopes`, `fields`. "Complete
        by construction" rested on seven names written by hand, that is, it
        was complete by construction of MY LIST, not of the registry.

        Plurality cannot be derived from the registry — it does not mark it.
        But COVERAGE can be closed: every kind must lie in exactly one of the
        two lists. Then a new kind turns this test red and DEMANDS a
        decision instead of silently landing nowhere.
        """
        registry_kinds = {p.kind for op in spec.OPS.values() for p in op.params}
        classified = PLURAL_KINDS | SCALAR_KINDS
        unclassified = sorted(registry_kinds - classified)
        self.assertFalse(unclassified, (
            f"виды параметров, не отнесённые ни к PLURAL_KINDS, ни к "
            f"SCALAR_KINDS: {unclassified}. Решение обязано быть явным: "
            f"обходит ли эмиссия этот вид РУКОПИСНЫМ ЦИКЛОМ."))
        both = sorted(PLURAL_KINDS & SCALAR_KINDS)
        self.assertFalse(both, f"вид объявлен и там, и там: {both}")
        # control-FAIL: the lists must not survive a renaming of kinds.
        # A name that is not in the registry is not "for later" but a stale
        # entry.
        stale = sorted(classified - registry_kinds)
        self.assertFalse(stale, (
            f"объявленные виды, которых в реестре НЕТ: {stale} — список "
            f"пережил свой авторитет"))

    def test_the_probe_reads_cardinality_control_pass_and_control_fail(self):
        """A control of the probe ITSELF: both PASS and FAIL, on known answers.

        Without this pair, a probe that had forgotten how to count would
        declare EVERYTHING unpinned (the threshold is never reached) or
        NOTHING (cardinality read as huge), and both outcomes would look
        like the list working normally.
        """
        # control-FAIL: the degenerate and the empty must NOT reach the
        # threshold
        self.assertEqual(cardinality(None), 0)
        self.assertEqual(cardinality([]), 0)
        self.assertEqual(cardinality([[[0, 0], [1, 0], [1, 1]]]), 1)
        self.assertLess(cardinality([[[0, 0], [1, 0], [1, 1]]]), PLURAL_FLOOR)
        self.assertEqual(cardinality({"level_name": "Этаж 1"}), 1)
        # control-PASS: two or more must reach the threshold
        self.assertGreaterEqual(cardinality([{"a": 1}, {"a": 2}]), PLURAL_FLOOR)
        self.assertGreaterEqual(
            cardinality({"level_name": "Этаж 1", "structural": True}),
            PLURAL_FLOOR)

    def test_the_four_ops_closed_on_evidence_stay_closed(self):
        """Those lifted by measurement on 08.12 must stay lifted.

        A named control-PASS on live data: if a new probe starts lying
        downward, it will first "reopen" this foursome — and fail here,
        with the op's name, not a bare total.
        """
        best = _max_cardinality()
        expected = {
            ("move_elements", "targets"): 3,
            ("create_dimension", "refs"): 2,
            ("create_angular_dimension", "refs"): 2,
            ("create_pipe_system", "nodes"): 3,
            ("create_foundation", "holes"): 2,
        }
        for key, want in expected.items():
            with self.subTest(op=key[0]):
                got, gname = best[key]
                self.assertGreaterEqual(
                    got, want,
                    f"{key[0]}.{key[1]}: мощность упала до {got} "
                    f"(ждали >= {want}); максимум даёт {gname}")


if __name__ == "__main__":
    unittest.main()
