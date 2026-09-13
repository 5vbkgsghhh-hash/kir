"""STATE RATCHET: the block in `kir/CLAUDE.md` must match the code.

    cd /opt/kir && PYTHONPATH=/opt/kir python3.12 -m pytest -q \\
        kir/tests/test_kir_canon_state_is_current.py

🔴 THIS TEST IS THE ONLY THING THAT TELLS STATE APART FROM ORDINARY PROSE.

The KIR canon gets read before the code, because it's more convenient.
Measured 15.08.2026: it was stale in SIX places, and ALL SIX in the direction
of UNDERSTATING capability:

    canon                                   code
    ─────────────────────────────────────────────────────────
    «90 861 lines in 119 files»             137 027 in 153
    «41 ops with live witness»              64 of 69
    «27 writers never reached Revit»        5
    «corpus ends 04.08»                     runs through 15.08
    walk «911 modules / 368»                1154 / 425
    device id «in two places»               27 hits in 24 files

An understated number reads as «this doesn't exist» — and produces the
mistake «already built»: FOUR times in one session, THREE times the finished
thing was BETTER than what was planned.

The reason is always the same: **nobody mutates prose.** No run turns red
because a description lies. The generated block under the ratchet — mutates,
and so it can only lie until the next suite run.

IF THIS TEST IS RED — the state is stale, not broken. There is one fix:

    cd /opt/kir && PYTHONPATH=/opt/kir python3.12 tools/kir_canon_state.py --write

then read the diff: it shows WHAT changed in the compiler since last time.
Red here is not an obstacle — it is a message.

🔴 WHY THE RATCHET IS RED ON THE FIRST RUN IN THIS REPOSITORY (27.08.2026).
The block in the canon was captured on the `prod-live` tree BEFORE the split
and describes the `kukai/ir` area — 188 non-test files. Today's `kir/` has
absorbed `checker`, `clash`, `viewer`, `live`, `course` and weighs 270. The
discrepancy is REAL, and the ratchet is obliged to shout about it; silencing
it by regenerating is the OWNER's decision (mandate item 17: the diff is read
before `--write`, otherwise regenerating destroys edits made outside the
source).

🔴 THE INTERPRETER IS PART OF THE ANSWER (form 26). The instrument REFUSES
under whoever does not walk the whole tree, instead of writing in an
understated state and letting the ratchet lock it in.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

#: 🔴 TWO STEPS UP FROM THE PACKAGE, NOT THREE FROM THE TEST. The root is
#: counted from where the package actually lives: the layout changes, this
#: does not. It was exactly on «steps up» that the sandbox burned after the
#: split (`f518b05`).
import kir as _kir  # noqa: E402

PKG = os.path.dirname(os.path.abspath(_kir.__file__))
REPO = os.path.dirname(PKG)
TOOLS = os.path.join(REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

# 🔴 THE INSTRUMENT MOVED INTO THE PACKAGE 28.08.2026: `tools/` is NOT part
# of the installable package, and the import by short name was AN ESCAPE
# BEYOND THE BOUNDARY (the guard
# `test_kir_boundary_to_the_product_is_a_closed_list` counted such by name).
# Untangling, not a registry entry: the escape was REMOVED. The command in
# `tools/` stayed a thin door and works letter for letter.
from kir.instruments import canon_state as kir_canon_state  # noqa: E402


def _sample_matching(pattern) -> str:
    """The string the INSTRUMENT considers to be the admin device id.

    Taken from the regex itself, not written as a literal: two places
    obliged to match are our named defect, and a mismatch here would make
    the control green by construction (form 8).
    """
    import re as _re
    src = getattr(pattern, "pattern", str(pattern))
    # 1) The instrument looked for a LITERAL — the sample is obtained by
    #    stripping the boundary anchors.
    literal = _re.sub(r"\\[bBAZ]", "", src)
    if literal and pattern.search(literal):
        return literal
    # 2) The instrument looks for a PATTERN (since 27.08 — a 32-char hex
    #    outside digest context). It has no literal and must not have one:
    #    the literal WAS the very leak the guard was built by hand to close.
    #    So a candidate is CONSTRUCTED, but the regex itself stays the
    #    arbiter — only what it accepts is admitted. The property «taken
    #    from the instrument, not written next to it» is preserved: a
    #    mismatch still yields a refusal, not a green.
    for candidate in ("0123456789abcdef" * 2, "a" * 32, "0" * 32):
        if pattern.search(candidate):
            return candidate
    raise AssertionError(
        "не удалось вывести образец из DEVICE_RE=%r — контроль без образца "
        "был бы зелёным по построению" % src)


#: SCALE ROWS — the ones that move from ANY edit to the tree and say nothing
#: about the compiler's capability. The list is CLOSED and self-checking.
#:
#: 🔴 WHY THE SPLIT, AND THIS IS A MEASUREMENT, NOT TASTE. On 20.08 the
#: ratchet was red ALL DAY, and the diff turned out to be: «size 148 → 156k,
#: files 162 → 167, modules 1246 → 1306. NOT ONE STRUCTURAL ROW BUDGED». The
#: whole day's red was noise. On 22.08 the same red turned out to be
#: DIFFERENT: the registry had moved (74 → 78 ops), solo ops (3 → 4),
#: parameter kinds (35 → 38). Telling one case from the other is the
#: INSTRUMENT's job, because the decision differs.
#:
#: THE SCALE ROW'S NAME CHANGED AT THE SPLIT: it used to be «размер
#: `kukai/ir/`», it became «размер `kir/`» (kept in Russian: it is the exact
#: literal the code below compares against). A desync with the instrument
#: here is a REFUSAL with a named key, not a silent recolouring (see
#: `_row_report`).
_SCALE_ROWS = frozenset({
    "размер `kir/`",
    "модулей проиндексировано / достижимо от точек входа",
})


def _rows(block: str | None) -> dict[str, str]:
    """Rows of the block's table as «what» → «how much». Unparsed stays silent."""
    out: dict[str, str] = {}
    for line in (block or "").splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] not in ("что",):
            out[cells[0]] = cells[1]
    return out


def _row_report(current: str | None, fresh: str) -> str:
    """WHAT EXACTLY diverged, tagged CAPABILITY / SCALE.

    An unknown row is deliberately treated as CAPABILITY: erring toward
    loudness is cheaper than silently filing a new row as noise.
    """
    now, was = _rows(fresh), _rows(current)
    missing = sorted(_SCALE_ROWS - set(now))
    if missing:
        return ("не могу разобрать блок по рядам: ключей %r в нём нет. "
                "Ряд переименовали, а этот список — второй носитель его "
                "имени; почини ЗДЕСЬ, иначе разметка врёт молча." % missing)
    lines: list[str] = []
    capability_moved = False
    for key in sorted(set(now) | set(was)):
        a, b = was.get(key), now.get(key)
        if a == b:
            continue
        mark = "МАСШТАБ    " if key in _SCALE_ROWS else "СПОСОБНОСТЬ"
        if key not in _SCALE_ROWS:
            capability_moved = True
        lines.append("  [%s] %s\n      было: %s\n      стало: %s"
                     % (mark, key, a if a is not None else "(ряда не было)",
                        b if b is not None else "(ряд исчез)"))
    if not lines:
        return "  (в таблице расхождений нет — разошлось что-то вне её)"
    verdict = ("\n  ВЕРДИКТ: уехала СПОСОБНОСТЬ — продукт изменился, канон о "
               "нём молчит."
               if capability_moved else
               "\n  ВЕРДИКТ: уехал только МАСШТАБ — это рост дерева, а не "
               "изменение продукта.")
    return "\n".join(lines) + "\n" + verdict


class TheStateInTheCanonMatchesTheCode(unittest.TestCase):

    def test_the_block_exists_at_all(self):
        """The block being absent and the block matching are different facts,
        and the first must be visible as a refusal, not as a silent «no
        discrepancies»."""
        assert kir_canon_state.current_block() is not None, (
            "в kir/CLAUDE.md нет порождаемого блока состояния; впиши:\n"
            "    PYTHONPATH=/opt/kir python3.12 tools/kir_canon_state.py --write")

    def test_the_block_equals_what_the_code_says_now(self):
        # NUMBERS are compared, not the provenance line: the branch name
        # differs between two sessions on the same content, and the ratchet
        # used to turn red in turn over a discrepancy that isn't in the
        # numbers.
        current = kir_canon_state.comparable(kir_canon_state.current_block())
        fresh = kir_canon_state.comparable(kir_canon_state.build())
        assert current == fresh, (
            "СОСТОЯНИЕ УСТАРЕЛО — компилятор изменился, блок нет.\n"
            "%s\n"
            "Дерево, на котором это замерено СЕЙЧАС: %s @ %s\n"
            "Почини и прочитай диф, он показывает ЧТО изменилось:\n"
            "    PYTHONPATH=/opt/kir python3.12 tools/kir_canon_state.py --write"
            % (_row_report(current, fresh),
               kir_canon_state._tree_id(), kir_canon_state.head_short()))

    def test_the_block_measures_the_CODE_and_not_the_machine(self):
        """🔴 THE RATCHET WAS RED FROM A MACHINE DIFFERENCE AND READ AS «THE
        CODE MOVED AHEAD».

        Measured 18.08.2026: the walk took in `data/`, WHERE THE SERVICE
        WRITES, and the number grew without a single code edit. The ratchet
        could not be green in prod and in the dev tree at the same time, BY
        CONSTRUCTION.

        The check is not «is `data` in the list» — that could be satisfied
        without a fix: we write an actual runtime file and require the
        number to NOT BUDGE. `build/` is added here too: `pip install` puts
        a full copy of the package into `/opt/kir/build/lib/kir/`, and the
        walk would count everything TWICE — same class, new body.
        """
        import tempfile

        sample = _sample_matching(kir_canon_state.DEVICE_RE)
        with tempfile.TemporaryDirectory() as tmp:
            pkg = os.path.join(tmp, "kir")
            os.mkdir(pkg)
            # SOURCE — must be counted.
            with open(os.path.join(pkg, "probe.py"), "w", encoding="utf-8") as fh:
                fh.write('DEVICE = "%s"\n' % sample)
            # RUNTIME — must NOT be counted. In real shape: that directory,
            # that extension, and inside it exactly what the instrument
            # looks for. `obj/` and `bin/` are written by the .NET build
            # (`connector/revit/tests/*/obj/Release/…`): on 07.09.2026 on the
            # dev machine they yielded «scanned 72», on a clean clone — 0,
            # and the canon captured on one turned red on the other.
            for runtime in ("data", "build", "obj", "bin", "test-results"):
                os.mkdir(os.path.join(tmp, runtime))
                with open(os.path.join(tmp, runtime, "written_by_runtime.json"),
                          "w", encoding="utf-8") as fh:
                    fh.write('{"device_id": "%s"}' % sample)

            saved_repo, saved_pkg = kir_canon_state.REPO, kir_canon_state.PKG
            try:
                kir_canon_state.REPO = tmp
                kir_canon_state.PKG = pkg
                row = kir_canon_state._oss_boundary()[0]
            finally:
                kir_canon_state.REPO, kir_canon_state.PKG = saved_repo, saved_pkg

        # 🔴 NUMBERS ARE QUERIED, NOT WORDING. The first edit of this test
        # matched the substring «**1 вхождений в 1 файлах**» and turned red
        # on 27.08 over an edit that broke nothing: the row's wording had
        # changed, the count stayed correct (1 source, 0 runtime). A guard
        # pinned to APPEARANCE lies about the subject — form 25 of this
        # tree, caught by its own guard.
        counts = [int(n) for n in re.findall(r"\*\*(\d+)\D+(\d+) файлах\*\*",
                                             row)[0]] if re.search(
            r"\*\*\d+\D+\d+ файлах\*\*", row) else []
        self.assertEqual(
            counts, [1, 1],
            "прибор посчитал файл, который ПИШЕТ РАНТАЙМ: значит он снова "
            "мерит МАШИНУ, а не код, и покраснеет на разнице деревьев, "
            "читаясь как «код изменился». Строка: %r" % row)

    def test_the_provenance_line_is_present_and_names_a_tree(self):
        """The provenance line was taken out from under the comparison —
        meaning its disappearance stopped being red. This test hands it back
        a guard: the line must EXIST and must name the tree, or else «a
        number without a tree» (form 26) will slide silently right through
        the door we opened."""
        block = kir_canon_state.current_block() or ""
        lines = [ln for ln in block.splitlines()
                 if ln.startswith(kir_canon_state._PROVENANCE_MARK)]
        assert len(lines) == 1, (
            "строка провенанса пропала или размножилась: она не сравнивается "
            "храповиком, поэтому сторожить её обязан этот тест")
        assert "дерево" in lines[0] and "**" in lines[0], (
            "провенанс перестал называть дерево: %r" % lines[0])

    def test_the_block_does_not_chase_its_own_commit(self):
        """🔴 A RATCHET THAT CANNOT BE SILENCED IS NOT AN INSTRUMENT (form 1).

        The block lives in a file that is itself committed. As long as it
        carried `rev-parse --short HEAD`, every commit made it stale:
        measured 15.08 — `bc6781f3` was recorded, HEAD after the commit was
        `3deec0f7`. It was never once green in committed form.

        The control is about the SUBJECT, not about equality: what is pinned
        here is the PROPERTY ITSELF — the block carries no value that
        changes with the commit."""
        block = kir_canon_state.build()
        head = kir_canon_state.head_short()
        if head == "?":
            # 🔴 A FROZEN COPY IS NOT A REPOSITORY (03.09.2026). The wave
            # measures a `git archive` copy, it has no `.git`, and
            # `head_short()` honestly returns "?". The refusal was a TRUTH
            # ABOUT THE INSTRUMENT, not about the block, and stood in every
            # run of the wave. Whoever froze it knows the revision and is
            # the one to name it; giving up is warranted only if NOBODY
            # answered.
            head = os.environ.get("KIR_FROZEN_SHA", "?")
        assert head and head != "?", (
            "не смог прочитать HEAD и не получил KIR_FROZEN_SHA от "
            "заморозившего — контроль вырожден")
        assert head not in block, (
            "блок несёт короткий хеш HEAD (%s) — значит краснеет на КАЖДОМ "
            "коммите и погасить его нельзя" % head)
        assert kir_canon_state._tree_id() in block, (
            "ветка из блока пропала — провенанс потерян совсем, а требовалось "
            "убрать только гоняющуюся часть")


class TheRedSaysWhetherItMatters(unittest.TestCase):
    """🔴 A RED THAT CANNOT TELL NOISE FROM THE SUBJECT STOPS BEING READ.

    The row-by-row breakdown is done by `_row_report`, and it must BE ABLE
    TO TELL THEM APART — otherwise it's a decoration on the message, not an
    instrument."""

    @classmethod
    def setUpClass(cls):
        cls.fresh = kir_canon_state.comparable(kir_canon_state.build())

    def _mutate_row(self, block: str, key: str) -> str:
        rows = _rows(block)
        assert key in rows, "ряда %r в блоке нет — контроль вырожден" % key
        old = "| %s | %s |" % (key, rows[key])
        assert old in block, "строка ряда собрана не так, как лежит: %r" % old
        return block.replace(old, "| %s | %s |" % (key, rows[key] + " ЗОНД"), 1)

    def test_a_capability_row_is_named_as_capability(self):
        fresh = self.fresh
        key = next(k for k in sorted(_rows(fresh)) if k not in _SCALE_ROWS)
        report = _row_report(self._mutate_row(fresh, key), fresh)
        self.assertIn("[СПОСОБНОСТЬ] %s" % key, report, report)
        self.assertIn("уехала СПОСОБНОСТЬ", report, report)

    def test_a_scale_row_alone_is_named_as_noise(self):
        """CONTROL IN THE OPPOSITE DIRECTION: a marking that calls everything
        capability distinguishes exactly as much as one that calls nothing
        at all."""
        fresh = self.fresh
        key = sorted(_SCALE_ROWS)[0]
        report = _row_report(self._mutate_row(fresh, key), fresh)
        self.assertIn("[МАСШТАБ", report, report)
        self.assertIn("уехал только МАСШТАБ", report, report)
        self.assertNotIn("уехала СПОСОБНОСТЬ", report, report)

    def test_a_renamed_scale_row_refuses_instead_of_relabelling(self):
        """`_SCALE_ROWS` is the SECOND CARRIER of the row's name, the first
        lives in `kir_canon_state`. Rename the row there, and here it will
        silently slide into «capability», making the verdict falsely alarm
        forever. So a desync is a REFUSAL with a named key, not a
        recolouring.

        🔴 THIS CONTROL FIRED FOR REAL AT THE SPLIT: the scale row was
        renamed from `kukai/ir/` to `kir/`, and without it the list would
        have silently declared the tree's growth a change in capability."""
        fresh = self.fresh
        key = sorted(_SCALE_ROWS)[0]
        renamed = fresh.replace("| %s |" % key, "| %s (переименован) |" % key, 1)
        assert renamed != fresh, "подмена оказалась пустой — контроль вырожден"
        report = _row_report(fresh, renamed)
        self.assertIn("не могу разобрать блок по рядам", report, report)
        self.assertIn(key, report, report)

    def test_the_marking_is_not_green_by_construction(self):
        """DEGENERACY CONTROL: both markings must be REACHABLE on the real
        block."""
        keys = set(_rows(self.fresh))
        assert _SCALE_ROWS & keys == _SCALE_ROWS, (
            "не все ряды масштаба есть в блоке: %r" % sorted(_SCALE_ROWS - keys))
        assert keys - _SCALE_ROWS, "в блоке нет ни одного ряда способности"


class TheRatchetCanActuallyFail(unittest.TestCase):
    """FAIL CONTROL. A comparison that is always green guards nothing — and a
    ratchet unable to turn red is WORSE than none at all: it manufactures
    confidence and gives no protection."""

    def test_a_single_changed_character_is_caught(self):
        """🔴 THIS CONTROL WENT BLIND ON 15.08.2026, AND THIS IS A
        MEASUREMENT, NOT A HYPOTHESIS.

        It used to do `fresh.replace("69", "70", 1)` — meaning it guarded
        not the block but the PRESENCE OF THE SUBSTRING «69» IN IT. That day
        the registry became 70 ops, «69» disappeared from the block, the
        replace became a no-op, and the control started failing.

        Form 7 of the canon: wording is not authority. The mutation is taken
        from the block ITSELF, so it cannot be defeated by rewording the
        content.
        """
        fresh = kir_canon_state.build()
        digit = next((c for c in fresh if c.isdigit()), None)
        assert digit is not None, (
            "в блоке состояния нет НИ ОДНОЙ цифры — а он существует ровно "
            "затем, чтобы нести числа; это отказ о блоке, а не о тесте")
        mutated = fresh.replace(digit, "9" if digit != "9" else "8", 1)
        assert mutated != fresh, "замена оказалась пустой — контроль вырожден"
        assert kir_canon_state.current_block() != mutated

    def test_a_missing_block_is_caught_too(self):
        assert kir_canon_state.current_block("/nonexistent/CLAUDE.md") is None


class TheStateRefusesRatherThanLies(unittest.TestCase):

    def test_the_budget_is_a_refusal_not_a_cut(self):
        """A truncated state looks complete, and decisions get made on it as
        if it were complete. So exceeding the ceiling is a REFUSAL."""
        original = kir_canon_state.CHAR_BUDGET
        try:
            kir_canon_state.CHAR_BUDGET = 10
            with self.assertRaises(kir_canon_state.CanonStateError) as caught:
                kir_canon_state.build()
            assert "не помещается" in str(caught.exception)
        finally:
            kir_canon_state.CHAR_BUDGET = original

    def test_the_budget_admits_the_real_state(self):
        """CONTROL: the refusal above must be about SIZE, not about the
        state failing to build at all."""
        assert len(kir_canon_state.build()) < kir_canon_state.CHAR_BUDGET


class ДостижимостьОтказываетВместоНуля(unittest.TestCase):
    """🔴 THE MAIN FIX OF THE MOVE, AND IT WAS BOUGHT BY THE 27.08.2026 RUN.

    `kir/instruments/capability_graph.py` looks for the roots
    `("kukai","tools","scripts")` INSIDE `kir/`, where none of them exist —
    and yet it returns

        modules 123 · live 0 · disqualified() == ''

    That is fail-open in pure form (form 34): a refusal wearing the costume
    of a measurement. Porting it «as is» would have written «reachable 0%»
    into the language's canon, and the ratchet would have locked it in as
    the benchmark.

    The three controls below are a pair — «knows how to refuse» / «knows how
    NOT to refuse» — plus the old disqualification control, made reachable.
    An instrument that ALWAYS refuses guards exactly as much as one that
    never does.
    """

    def _cells(self) -> list[str]:
        return kir_canon_state._reachability()

    def test_a_walk_that_looks_elsewhere_refuses_instead_of_printing_zero(self):
        """TODAY'S STATE: the walk has not been ported, the cell must REFUSE."""
        from kir.instruments import capability_graph as cg
        roots = getattr(cg, "_SOURCE_ROOTS", ())
        base = str(getattr(cg, "BACKEND", ""))
        present = [r for r in roots if os.path.isdir(os.path.join(base, r))]
        if present:
            self.skipTest(
                "обход уже переведён на раскладку пакета (нашлись корни %r) — "
                "этот контроль описывает состояние ДО перевода" % present)
        for cell in self._cells():
            self.assertIn(kir_canon_state.REACH_UNAVAILABLE, cell, cell)
            self.assertNotIn("**0 / 0**", cell,
                             "молчаливый ноль вместо названного отказа: %r" % cell)

    def test_a_qualified_walk_prints_a_number_not_a_refusal(self):
        """CONTROL IN THE OPPOSITE DIRECTION. A cell that refuses on ANY walk
        does not tell a ported instrument apart from an unported one."""
        from kir.instruments import capability_graph as cg

        real_graph, real_roots, real_base = cg.Graph, cg._SOURCE_ROOTS, cg.BACKEND

        class _Module:
            is_test = False
            gate_flags = {"probe_enabled"}

        class _Qualified:
            def __init__(self, *_a, **_kw):
                self.modules = {"kir.probe": _Module()}

            def disqualified(self) -> str:
                return ""

            def live(self):
                return {"kir.probe"}

        cg.Graph = _Qualified                       # type: ignore[assignment]
        cg._SOURCE_ROOTS = ("kir",)                 # type: ignore[assignment]
        cg.BACKEND = kir_canon_state.REPO           # type: ignore[assignment]
        try:
            cells = self._cells()
        finally:
            cg.Graph, cg._SOURCE_ROOTS, cg.BACKEND = (
                real_graph, real_roots, real_base)

        self.assertIn("**1 / 1** (100%)", cells[0], cells[0])
        self.assertIn("**1**", cells[1], cells[1])
        for cell in cells:
            self.assertNotIn(kir_canon_state.REACH_UNAVAILABLE, cell, cell)

    def test_a_disqualified_walk_raises_instead_of_understating(self):
        """A walk that didn't parse the whole tree UNDERSTATES reachability:
        the module isn't in the graph, and it's indistinguishable from dead.
        The instrument must REFUSE, not write an understated number — or the
        ratchet will lock the lie in as the benchmark.

        The precondition is swapped out too: without it the refusal would be
        unreachable and the control would be testing the new guard instead
        of the old one."""
        from kir.instruments import capability_graph as cg

        real_graph, real_roots, real_base = cg.Graph, cg._SOURCE_ROOTS, cg.BACKEND

        class _Crippled:
            def __init__(self, *_a, **_kw):
                self.modules = {}

            def disqualified(self) -> str:
                return "контроль: дерево разобрано не целиком"

        cg.Graph = _Crippled                        # type: ignore[assignment]
        cg._SOURCE_ROOTS = ("kir",)                 # type: ignore[assignment]
        cg.BACKEND = kir_canon_state.REPO           # type: ignore[assignment]
        try:
            with self.assertRaises(kir_canon_state.CanonStateError) as caught:
                kir_canon_state._reachability()
            assert "не целиком" in str(caught.exception)
        finally:
            cg.Graph, cg._SOURCE_ROOTS, cg.BACKEND = (
                real_graph, real_roots, real_base)


from kir.tests.host_entry_points import (  # noqa: E402
    HOST_ENTRY_POINTS, host_declares_entry_points)


class ДоляДостижимостиОтличаетПустоОтМёртвого(unittest.TestCase):
    """🔴 CAUGHT BY A STRANGER'S GATE ON 29.08.2026.

    On a bare package install the report used to print «Modules indexed:
    838, reachable from entry points: 0 (0%)» — a plausible, catastrophic
    statement ABOUT THE LANGUAGE where it is actually a fact ABOUT THE HOST:
    all entry points live in the product tree, and a walk over the KIR
    package alone will NEVER find them.

    🔴 EDIT 01.09.2026: entry points no longer LIVE IN THE PACKAGE. The
    owner names them through the port `ports.ENTRY_POINTS` — a package
    shipped to PyPI has no business printing the reader a map of somebody
    else's deployment. Hence the third state and the third control below:
    «not declared» is ALSO EMPTY, and it must sound the same as «declared
    but not found».

    The answer is deliberately kept separate from `disqualified()`, and this
    was bought by a run: the first edit of the fix filed this kind under
    disqualification, and `canon_state._reachability` REFUSES to produce a
    state on it — the language's canon stopped building in its own tree, 5
    tests red and 4 errors. «The walk is incomplete» and «there's nothing to
    measure» must go through different doors.

    A pair of controls: knows how to speak, and knows how to stay silent.
    """

    def _graph_with(self, names):
        from kir.instruments import capability_graph as G

        class _Fake(G.Graph):
            def __init__(self) -> None:
                self.interpreter = G.INTERPRETER
                self.modules = {n: object() for n in names}
                self.unparsable = []

        return _Fake()

    def test_no_entry_point_found_names_the_cause(self) -> None:
        """DECLARED, BUT NOT ONE WAS FOUND — the refusal names WHAT."""
        graph = self._graph_with(["kir.spec", "kir.compiler"])
        with host_declares_entry_points():
            why = graph.reachability_unmeasurable()
            disq = graph.disqualified()
        self.assertTrue(why, "ноль достижимости без точек входа обязан "
                             "назвать причину, а не печататься числом")
        for name in HOST_ENTRY_POINTS:
            self.assertIn(name, why, "отказ обязан назвать, ЧЕГО не нашлось")
        self.assertEqual(disq, "",
                         "обход ПОЛОН: дисквалифицировать отчёт нечем, "
                         "иначе канон языка перестанет строиться")

    def test_one_found_entry_point_is_enough_to_stay_silent(self) -> None:
        """AT LEAST ONE WAS FOUND — there is something to count from, the
        instrument stays silent."""
        first = sorted(HOST_ENTRY_POINTS)[0]
        graph = self._graph_with([first, "kir.spec"])
        with host_declares_entry_points():
            why = graph.reachability_unmeasurable()
        self.assertEqual(why, "",
                         "нашлась хоть одна точка входа — считать есть от чего")

    def test_no_entry_point_DECLARED_also_names_the_cause(self) -> None:
        """🔴 THE THIRD STATE, AND IT IS EXACTLY THE ONE A STRANGER SEES.

        The port isn't supplied — entry points aren't declared AT ALL. The
        instrument's earlier edit returned an empty string here and printed
        the reachability share of an EMPTY set: «0 (0%)», i.e. a zero
        indistinguishable from a dead tree. On a bare package install this
        is the normal case, not an edge one, so the guard is filed
        separately from its two neighbours.
        """
        from kir import ports
        graph = self._graph_with(["kir.spec", "kir.compiler"])
        self.assertNotIn(ports.ENTRY_POINTS, ports.supplied(),
                         "контроль требует НЕпоставленного порта; поставщик "
                         "протёк из соседнего теста")
        why = graph.reachability_unmeasurable()
        self.assertIn(ports.ENTRY_POINTS, why,
                      "отказ обязан назвать ПОРТ: читателю нужно знать, чем "
                      "это чинится, а не только что не сосчиталось")
        self.assertEqual(graph.disqualified(), "",
                         "обход ПОЛОН и здесь: «предмета нет» и «прибор "
                         "сломан» обязаны ходить разными дверьми")


class ОбъявленияФлаговБезФайлаНеПустота(unittest.TestCase):
    """🔴 What disappears isn't a report line, but a whole KIND of finding.

    `parse_env_file` returns `{}` for a missing file, and the answer must
    not be dropped: the inventory has to assemble even without `.env`. But
    flag names come from THREE sources — `.env`, `.env.example`, and the
    flag being read in code. A flag that IS READ will be found even without
    the files; the one that gets lost is exactly the one that is DECLARED
    and READ BY NOBODY — the very case the instrument was written for.

    A stranger ALWAYS lacks `.env` (gate measurement 29.08.2026), so this
    isn't an edge case but the ordinary state.
    """

    def test_absent_declaration_files_are_named(self) -> None:
        import pathlib, tempfile
        from kir.instruments.capability_graph import missing_env_files
        with tempfile.TemporaryDirectory() as tmp:
            absent = missing_env_files(pathlib.Path(tmp))
            self.assertEqual(sorted(absent), [".env", ".env.example"],
                             "оба файла объявлений обязаны быть названы "
                             "поимённо, а не одним «файлов нет»")

    def test_a_present_file_is_not_reported_missing(self) -> None:
        """Positive control: an instrument that always complains guards
        nothing."""
        import pathlib, tempfile
        from kir.instruments.capability_graph import missing_env_files
        with tempfile.TemporaryDirectory() as tmp:
            here = pathlib.Path(tmp)
            (here / ".env").write_text("KUKAI_X=1\n", encoding="utf-8")
            self.assertEqual(missing_env_files(here), (".env.example",),
                             "найденный файл в список отсутствующих попадать "
                             "не должен")


if __name__ == "__main__":
    unittest.main()
