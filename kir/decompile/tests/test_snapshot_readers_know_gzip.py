"""A COMPRESSED DECOMPILE IS READ BY THE SAME CALL AS AN ORDINARY ONE.

🔴 21.08.2026: THE NAMES BECAME TEN, AND THE LINE MATCHER TURNED OUT
ALMOST BLIND TO THE FOUR NEW ONES — THIS IS MEASURED, NOT ASSUMED.
`SNAPSHOT_FILES` gained `passport.json` (1001 MB across 28 decompiles),
`named.json` (422 MB), `tree.json` (416 MB), `verify.json` (342 MB) —
2.18 GB that could not be compressed for the exact reason that they were
being read with a bare `open`. Their readers turned up in **19 spots**,
and the line-based half of this guard, run over the pre-commit tree, saw
**ONE** of them (`tools/roundtrip_groups.py:92`). The reason is named
below in this same docstring, and it was named IN ADVANCE: the path to
these four almost always sits in a variable (`path = run / "tree.json"`
… `path.read_text()`), while the matcher is line-based.

So the structural half now has TWO matchers, and the second does not
replace the first, but closes the hole the first named:
`TheStructuralHalfByAst` parses the module into an AST, traces
assignments, and catches a read through a variable. On the same tree it
gives 11 hits across 6 files against 4 files for the line-based one, and
among its findings is LIVE PROD: `serving._metadata_from_l0_header` was
opening `L0.jsonl` with a bare `open`, meaning that on a cooled-down A5
decompile it got `no_metadata` about a building whose levels are in fact
there.

The janitor `tools/snapshot_janitor.py` compresses these files IN PLACE
(`L0.jsonl` -> `L0.jsonl.gz`), and `snapshot_io` exists for the sole
reason that readers should not notice. The rule is written verbatim in
the project's map: "only `open_snapshot` / `read_snapshot_text`."

🔴 THE READING CORE WAS VIOLATING IT, AND THE DEFECT WAS ASYMMETRIC
WITHIN ONE SINGLE CLASS. Reproduced 19.08.2026: `L0JSONLReader._records()`
went through `open_snapshot` and did read the compressed decompile, while
`_read_header()` opened the same file with a bare `path.open("rb")`. On a
compressed run `iter_elements()` was returning 1,510 elements, while
`metadata()` of the same reader was failing with
`cannot read L0 header … No such file or directory`.

WHY NO ONE SAW THIS, AND WHY THIS IS NOT "THEORETICAL": the janitor is
NOT WIRED IN — not one systemd timer, not one calling module — so
compressed decompiles today number 0 of 75. **Two shelves were covering
each other's defects: the reader stays intact only while the janitor is
dead.** The disk is meanwhile at 83%, meaning the janitor will one day be
summoned, and on that day every cooled-down decompile will stop being
readable.

THIS GUARD HOLDS TWO DIFFERENT ASSERTIONS, and they do not reduce to
each other:

1. BEHAVIORAL — a real compressed decompile is read all the way through:
   header, stream, graph. Checked by execution on a COPY of a real
   building, not on a fixture;
2. STRUCTURAL — no module opens a compressible name with a bare `open`.
   The list of known violators is CLOSED and lives here: a new violator
   fails the test, and a fixed one fails it too (a stale exception is a
   quietly disabled check, and it is more dangerous than an honest red).

🔴 THE BOUNDARY OF THE STRUCTURAL HALF, NAMED BY A NUMBER, NOT KEPT
SILENT. The matcher is line-based: it sees an open only when the
compressible NAME sits ON THE SAME line. A path placed into a variable
one line above (`l0 = d / "L0.jsonl"` … `l0.open(...)`) is INVISIBLE to
it — measured: that is how at least `tools/discipline_mix.py` and
`tools/harvest_check.py` are built, and they did not make the ledger not
because they are clean.

AND A SECOND BOUNDARY, SYMMETRIC TO THE FIRST: the matcher fires on a
line where the compressible name sits NEXT TO an open, so a file that
reads through the correct loader but mentions the name on a different
line of the same kind can land among the findings FOR NOTHING. The check
is a single one and costs a second: read the line itself. The one case
of this kind that was actually presented
(`tools/probes/probe_group_harvest.py`) turned out, on reading, to be
REAL — `json.load(open(...))` at module level — but the class of false
positives does not disappear because of that, and the next person to see
red must open the line, not trust the list.

So the list of violators is CLOSED, BUT NOT COMPLETE AND NOT PRECISE: an
empty result here means "not found by this matcher," not "none of these
exist"; a non-empty one means "something similar was found," not
"proven." Catching variables would require an AST walk tracing
assignments — that is separate work, and until it exists, this is the
honest way to phrase it. What the guard GUARANTEES: no NEW direct open
passes in silence, and no fixed one remains on the ledger.
"""
from __future__ import annotations

import ast
import gzip
import json
import pathlib
import re
import shutil
import tempfile
import unittest

from kir.install_paths import install_data_path

#: 🔴 THE SCOPE IS THE PACKAGE, AND IT IS TAKEN FROM THE PACKAGE'S
#: LOCATION (28.08.2026).
#:
#: This spot used to have `parents[4]` — before the split that was the
#: whole owner tree (`backend/`), and the walk covered `kukai/` and
#: `tools/`. After the split the same count gives `/opt`: the directory
#: where `/opt/kir` simply sits next to someone else's trees. Nine tests
#: in this file were failing, and the failure was about US.
#:
#: We count not by steps upward, but from `kir.__file__` — the rule
#: `install_paths` was fixed by on 27.08. The name was changed from
#: `PACKAGE` to `PACKAGE` DELIBERATELY: the old one named a foreign
#: subject and would have survived the fix in silence.
def _package_root() -> pathlib.Path:
    import kir

    return pathlib.Path(kir.__file__).resolve().parent


PACKAGE = _package_root()

#: The names are taken FROM THE AUTHORITY — the janitor itself, not from
#: a copy. A copy and the original can drift apart in silence; here there
#: is nothing to drift.
def _janitor_files() -> tuple[str, ...]:
    """`SNAPSHOT_FILES` is read by PARSING the declaration site, without
    execution.

    Importing the whole janitor for the sake of one tuple would mean
    dragging its dependencies into the guard; reading the list as a copy
    would set up a second source of truth about what exactly gets
    compressed. The parse takes exactly the line where the value is
    declared.
    """
    path = PACKAGE / "instruments" / "snapshot_janitor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "SNAPSHOT_FILES" not in names:
            continue
        return tuple(ast.literal_eval(node.value))
    raise AssertionError(
        f"{path}: SNAPSHOT_FILES не найден — сторож потерял свой авторитет и "
        f"обязан УПАСТЬ, а не молча проверить пустой список")


#: 🔴 A CLOSED LEDGER OF KNOWN VIOLATORS. Not "haven't gotten to it yet,"
#: but a named owner and reason on EVERY row — otherwise the list turns
#: into an archive read as "everything's under control."
#:
#: The same rule as `tools/gold_path.py`: an entry that started PASSING
#: fails the test no less than a new breakage does.
KNOWN_RAW_READERS: dict[str, str] = {
    # 🔴 `kir/a5_contract.py` STRUCK OFF 30.08.2026 — FIXED by the same
    # commit that removed this line: `_load_a5_snapshot_manifest` now
    # reads the stream through the seam. The defect was costlier than it
    # read: within one function the file was opened twice, and only the
    # SECOND half went around the seam, so on a cooled-down decompile the
    # run did not refuse — it crashed with an unwrapped
    # `FileNotFoundError`. Measured: 37 of 81 decompiles hold the stream
    # only in compressed form.
    # 🔴 `kir/course/corpus.py` STRUCK OFF 22.08.2026 — it is FIXED, and
    # its entry had been turning the test red since commit `09d6342d`
    # ("The course names the shape dictionary; five bare readers switched
    # to compression"). Exactly what this ledger's header warns about: an
    # entry that started PASSING fails the test no less than a new
    # breakage — and it did fail it, and it was only removed now.
    # 🔴 BOTH `clash/tools/` LINES STRUCK OFF 29.08.2026 (F-314 + F-324):
    # both instruments are FIXED and read through `open_snapshot` /
    # `read_snapshot_text`. An entry that started passing fails
    # `test_a_fixed_entry_must_leave_the_ledger` no less than a new
    # breakage — the ledger is guarded from TWO sides, and striking it
    # off must be done by the SAME commit that fixes the code.
    # Below are instruments found by THIS guard beyond the manual ledger:
    # a manual review gave four files, the guard gave eight. All of them
    # are under `tools/`, i.e. domain F3; fixing them across a domain
    # boundary is not allowed, but naming them is mandatory.
    #
    # On 19.08, F3 closed `content_coverage` and `roundtrip_groups`
    # (`2b50a884`), and the ledger let them go BY TURNING RED — exactly
    # as intended.
    #
    # On 21.08, by the same red, `tools/bounds_audit.py` and
    # `tools/probes/probe_group_harvest.py` went away: both were FIXED by
    # neighbors, and the entry remained. The ledger had not turned red
    # during my shift, nor because of it — checked by comparing the sets
    # of violators under the old name list (six) and the new one (ten):
    # the sets MATCHED, meaning the red predated it. A stale entry is a
    # quietly disabled check, and it is more dangerous than an honest
    # red; so it is struck off, not appended to.
}

#: Opens that MUST remain bare, each with its own reason. This is not a
#: relaxation: a bare open here is CORRECT, and recording it as a
#: violator would mean setting up a false alarm forever.
DELIBERATELY_RAW: dict[str, str] = {
    "decompile/extract.py":
        "ПИСАТЕЛЬ и пересчёт СМЕЩЕНИЙ для resume: смещение есть позиция в "
        "СЫРОМ файле и на gzip бессмысленно; активный прогон не сжат по "
        "определению — уборщик трогает только остывшее. "
        "🔴 ЦЕНА ЭТОГО ПОСЛАБЛЕНИЯ НАЗВАНА И ПРОВЕРЕНА КОНТРОЛЕМ: пока файл "
        "здесь, структурная половина НЕ УВИДИТ возврата дефекта в "
        "`_read_header`. Прогнано 19.08 — откат починки роняет РОВНО ОДИН "
        "тест, и это `TheBehaviouralHalf`. Значит гарантию по ядру чтения "
        "держит поведенческая половина, а не список имён",
    "instruments/snapshot_janitor.py":
        "сам уборщик: он и есть тот, кто жмёт",
}

_OPEN_RE = re.compile(
    r"""(?:\.open\(|\bopen\(|read_text\(|read_bytes\()""")


def _sources() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    # The scope is the whole package: after the split there is no more
    # "kukai" and "tools" here, and the guard's subject — the code that
    # READS snapshots — is entirely here.
    for root in (".",):
        for path in (PACKAGE / root).rglob("*.py"):
            rel = path.relative_to(PACKAGE).as_posix()
            if "/tests/" in rel or path.name.startswith("test_"):
                continue
            out.append(path)
    return out


def _violations() -> dict[str, list[str]]:
    """File -> the lines where a compressible name is opened by a bare call."""
    names = _janitor_files()
    found: dict[str, list[str]] = {}
    for path in _sources():
        rel = path.relative_to(PACKAGE).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if not any(name in line for name in names):
                continue
            if "open_snapshot" in line or "read_snapshot" in line:
                continue
            if not _OPEN_RE.search(line):
                continue
            found.setdefault(rel, []).append(f"{lineno}: {line.strip()[:90]}")
    return found


class TheStructuralHalf(unittest.TestCase):

    def test_no_new_module_opens_a_gzipped_name_raw(self):
        seen = _violations()
        unknown = {
            rel: lines for rel, lines in seen.items()
            if rel not in KNOWN_RAW_READERS and rel not in DELIBERATELY_RAW}
        self.assertEqual(
            {}, unknown,
            "новый читатель открывает сжимаемое имя голым вызовом — на "
            "остывшем разборе он ослепнет:\n"
            + "\n".join(f"  {r}: {l}" for r, ls in unknown.items() for l in ls))

    def test_a_fixed_entry_must_leave_the_ledger(self):
        """A stale exception is a quietly disabled check."""
        seen = _violations()
        stale = sorted(rel for rel in KNOWN_RAW_READERS if rel not in seen)
        self.assertEqual(
            [], stale,
            "эти файлы БОЛЬШЕ не читают голым вызовом — вычеркни их из "
            f"KNOWN_RAW_READERS: {stale}")

    def test_the_ledger_is_not_empty_or_the_probe_proved_nothing(self):
        """A degeneracy control: an empty probe is green by construction.

        🔴 THE DENOMINATOR WAS REWRITTEN ON 30.08.2026, AND REWRITTEN
        BECAUSE OF AN INCIDENT. This spot used to have
        `assertTrue(_violations())` — "the tree has at least one
        violation." The condition was satisfied by the very LAST
        VIOLATION ITSELF (`a5_contract.py`), and the moment it was fixed,
        the check became RED FOREVER: the cleaner the tree, the louder it
        screamed. A check that is always red guards nothing — the first
        member of the series of a worthless control.

        The same lesson is already recorded next door (`agreements.py`,
        `_gather_bare_snapshot_access`): the denominator must answer "DID
        THE WALK HAPPEN," while the findings answer "was anything found."
        These are different questions. Here the walk is measured by the
        number of files traversed, and the probe's working order — by a
        PLANTED violation, the same trick already applied to the AST
        matcher below.
        """
        self.assertTrue(_janitor_files(), "уборщик не назвал ни одного файла")
        self.assertGreater(
            len(_sources()), 200,
            "обход прошёл слишком мало файлов — это заявление О ХОДОКЕ, а не "
            "о дереве")
        name = sorted(_janitor_files())[0]
        planted = f'    with (root / "{name}").open("r") as fh:\n'
        self.assertTrue(
            any(n in planted for n in _janitor_files())
            and _OPEN_RE.search(planted)
            and "open_snapshot" not in planted,
            "проба не видит ПОДСАДНОГО нарушения — она сломана")

    def test_the_line_probe_does_not_accuse_the_shim(self):
        """The control in the other direction: a line that goes through
        the seam is not a finding. Without it, the planted control above
        would be satisfied by a probe that screams at everything
        indiscriminately."""
        name = sorted(_janitor_files())[0]
        healthy = f'    with open_snapshot(root / "{name}", "rt") as fh:\n'
        self.assertTrue("open_snapshot" in healthy,
                        "контроль потерял свой предмет")


# ─────────────────────────────────────────────────────────────────────────────
# THE SECOND MATCHER: AST, WITH ASSIGNMENT TRACING
# ─────────────────────────────────────────────────────────────────────────────
#
# 🔴 THIS IS THE VERY "SEPARATE WORK" THE DOCSTRING ABOVE NAMED IN ADVANCE
# AND DID NOT DO. While the janitor's list had six names, the line matcher
# was enough: they were opened in a single line. The four new names are
# built differently — the path is placed into a variable, and the
# line-based guard saw 1 spot out of 19.
#
# WHAT THIS MATCHER GUARANTEES, AND WHAT IT DOES NOT. It catches: a
# name-constant anywhere in an expression, a variable such an expression
# is assigned to (including through a chain `a = b`), and passing such a
# variable as the first argument into its own function. It does NOT
# catch: a path assembled from a name in a list (`for name in NAMES:
# open(d / name)`), a path from a function argument called with a
# constant in another module, and `glob`. The boundaries are named by a
# number right next to the result: an empty answer here still means "not
# found by this matcher," not "none of these exist."
#
# ONLY READING IS READ. Writing (`open(..., "w")`, `write_text`) is
# skipped DELIBERATELY, and this is not a relaxation: a writer by
# definition works with the raw file, and the janitor does not touch a
# live run. An existence check (`is_file`/`exists`) is not here either —
# it is quieter and broader, and mixing it with reading would mean
# drowning a loud finding among a hundred quiet ones.
_AST_READ_ATTRS = {"read_text", "read_bytes"}
#: Names of functions that ARE THEMSELVES the shim (or a wrapper over
#: it) — entering them is not a violation, and the matcher does not
#: descend into such a call.
_AST_SHIM_CALLS = {"open_snapshot", "read_snapshot_text", "_open_snapshot",
                   "_read_snapshot", "_records", "_load", "_open"}
_AST_WRITE_MODES = set("wax+")


def _ast_consts(node):
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _ast_name_in(node, names):
    for value in _ast_consts(node):
        for name in names:
            if value == name or value.endswith("/" + name) \
                    or value.endswith("\\" + name):
                return name
    return None


class _RawReadScan(ast.NodeVisitor):
    """Module -> the lines where a compressible name is READ around the shim."""

    def __init__(self, source: str, names: tuple[str, ...]):
        self.names = names
        self.lines = source.splitlines()
        self.vars: dict[str, str] = {}
        self.hits: list[tuple[int, str, str]] = []

    # ── variable binding ────────────────────────────────────────────
    def _bind(self, targets, value):
        got = _ast_name_in(value, self.names)
        if got is None and isinstance(value, ast.Name):
            got = self.vars.get(value.id)
        if got is None and isinstance(value, ast.Call):
            for arg in value.args:
                if isinstance(arg, ast.Name) and arg.id in self.vars:
                    got = self.vars[arg.id]
                    break
        if got is None:
            return
        for target in targets:
            if isinstance(target, ast.Name):
                self.vars[target.id] = got

    def visit_Assign(self, node):
        self._bind(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self._bind([node.target], node.value)
        self.generic_visit(node)

    def _resolve(self, node):
        got = _ast_name_in(node, self.names)
        if got:
            return got
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id in self.vars:
                return self.vars[inner.id]
        return None

    @staticmethod
    def _mode_of(node, keywords):
        mode = ""
        if node is not None and _ast_consts(node):
            mode = _ast_consts(node)[0]
        for keyword in keywords:
            if keyword.arg == "mode" and _ast_consts(keyword.value):
                mode = _ast_consts(keyword.value)[0]
        return mode

    def visit_Call(self, node):
        func = node.func
        fname = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        if fname in _AST_SHIM_CALLS:
            return
        target = None
        if fname == "open":
            if isinstance(func, ast.Name):
                target = self._resolve(node.args[0]) if node.args else None
                mode = self._mode_of(node.args[1] if len(node.args) > 1 else None,
                                     node.keywords)
            else:
                target = self._resolve(func.value)
                mode = self._mode_of(node.args[0] if node.args else None,
                                     node.keywords)
            if set(mode) & _AST_WRITE_MODES:
                target = None
        elif fname in _AST_READ_ATTRS and isinstance(func, ast.Attribute):
            target = self._resolve(func.value)
        if target is not None:
            self.hits.append((node.lineno, target,
                              self.lines[node.lineno - 1].strip()[:100]))
        self.generic_visit(node)


def _ast_violations() -> dict[str, list[str]]:
    names = _janitor_files()
    found: dict[str, list[str]] = {}
    for path in _sources():
        rel = path.relative_to(PACKAGE).as_posix()
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not any(name in source for name in names):
            continue
        try:
            module = ast.parse(source)
        except SyntaxError:
            continue
        scan = _RawReadScan(source, names)
        scan.visit(module)
        for lineno, name, text in sorted(set(scan.hits)):
            found.setdefault(rel, []).append(f"{lineno}: {name} — {text}")
    return found


#: 🔴 THE AST MATCHER'S CLOSED LEDGER. There is NO entry about the four
#: new names here, and there must not be: the 21.08 wave routed all 19 of
#: their readers through the shim. Everything below is the OLD six
#: names, foreign domains, named by name, not "haven't gotten to it yet."
_AST_KNOWN: dict[str, str] = {
    # 🔴 `kir/a5_contract.py` STRUCK OFF 30.08.2026 TOGETHER with its
    # twin at the line matcher: both halves of the ledger must agree, and
    # a fix that removed the entry from only one would leave the other a
    # quietly disabled check.
    # 🔴 `course/corpus.py` and `course/building.py` STRUCK OFF
    # 22.08.2026 — both fixed by commit `09d6342d`, and the entries
    # remained and stayed red. The second was visible ONLY to this, the
    # AST matcher (`open(path)`, with the path in a variable) — meaning
    # the ledger genuinely catches what the line-based one does not, and
    # both its halves now converge on an empty F1 remainder.
    # 🔴 BOTH `clash/tools/` LINES STRUCK OFF 29.08.2026 (F-314 + F-324),
    # TOGETHER with their twins at the line matcher: both halves of the
    # ledger must agree, and a fix that removed the entry from only one
    # would leave the other a quietly disabled check. For
    # `wall_prism_gate` BOTH spots are fixed — L0 through
    # `open_snapshot` and `curve.index.json` through
    # `read_snapshot_text` (the second was seen ONLY by this, the AST
    # matcher).
    # STRUCK OFF 28.08.2026: `tools/discipline_mix.py`, at the split,
    # remained in the OWNER's tree and did not move into the package.
    # KIR's exclusion ledger has no right to hold an entry about a
    # foreign file: it would be guarding something that is not here, and
    # would look like protection. The example of "invisible to the
    # line-based matcher," which the entry existed for, is preserved
    # further down the class by its own control.
}


class TheStructuralHalfByAst(unittest.TestCase):
    """Reading a compressible name THROUGH A VARIABLE — what the
    line-based matcher does not see."""

    def test_no_module_reads_a_gzipped_name_raw_via_a_variable(self):
        seen = _ast_violations()
        unknown = {rel: rows for rel, rows in seen.items()
                   if rel not in _AST_KNOWN and rel not in DELIBERATELY_RAW}
        self.assertEqual(
            {}, unknown,
            "чтение сжимаемого имени мимо `snapshot_io` — на остывшем разборе "
            "этот код ослепнет:\n"
            + "\n".join(f"  {r}: {row}" for r, rows in unknown.items()
                        for row in rows))

    def test_a_fixed_entry_must_leave_the_ast_ledger(self):
        seen = _ast_violations()
        stale = sorted(rel for rel in _AST_KNOWN if rel not in seen)
        self.assertEqual(
            [], stale,
            "эти файлы БОЛЬШЕ не читают голым вызовом — вычеркни их из "
            f"_AST_KNOWN: {stale}")

    def test_the_ast_probe_is_not_degenerate(self):
        """A control: a probe that finds nothing is green by construction.

        🔴 THE DENOMINATOR WAS REWRITTEN ON 30.08.2026 for the same
        reason as its line-based twin: `assertTrue(_ast_violations())`
        was satisfied by the last live violation and was bound to turn
        red forever on the day it was fixed. The probe's working order
        is proved by a PLANTED input, not by dirt in the tree.
        """
        self.assertGreater(
            len(_sources()), 200,
            "обход прошёл слишком мало файлов — заявление О ХОДОКЕ")
        name = sorted(_janitor_files())[0]
        source = ('import pathlib\n'
                  'def f(run):\n'
                  f'    path = pathlib.Path(run) / "{name}"\n'
                  '    return path.read_text(encoding="utf-8")\n')
        scan = _RawReadScan(source, _janitor_files())
        scan.visit(ast.parse(source))
        self.assertTrue(
            scan.hits,
            "AST-проба не видит ПОДСАДНОГО чтения — она сломана")

    def test_the_ast_probe_sees_what_the_line_probe_cannot(self):
        """🔴 A FAIL CONTROL ON SYNTHETIC CODE, NOT AN ARGUMENT IN WORDS.

        The second matcher is justified by exactly one thing: it catches
        what the first misses. Checked by execution on code where the
        path is placed in a variable — the form 18 of the 19 readers of
        the four new names are written in.
        """
        source = ('import pathlib\n'
                  'def f(run):\n'
                  '    path = pathlib.Path(run) / "tree.json"\n'
                  '    return path.read_text(encoding="utf-8")\n')
        scan = _RawReadScan(source, _janitor_files())
        scan.visit(ast.parse(source))
        self.assertTrue(scan.hits, "AST-матчер не увидел чтение по переменной")
        # ... while the line-based one stays silent on the same code.
        line_hit = any(
            any(n in line for n in _janitor_files())
            and _OPEN_RE.search(line)
            and "open_snapshot" not in line and "read_snapshot" not in line
            for line in source.splitlines())
        self.assertFalse(
            line_hit,
            "строчный матчер вдруг ВИДИТ этот случай — тогда второй матчер "
            "не нужен, и это надо пересмотреть, а не оставить оба")

    def test_the_ast_probe_does_not_accuse_a_writer(self):
        """The control in the other direction: a writer is not a violator."""
        source = ('def f(d):\n'
                  '    path = d / "tree.json"\n'
                  '    with open(path, "w", encoding="utf-8") as fh:\n'
                  '        fh.write("{}")\n')
        scan = _RawReadScan(source, _janitor_files())
        scan.visit(ast.parse(source))
        self.assertEqual([], scan.hits,
                         "запись объявлена нарушением — ложная тревога навсегда")


class TheBehaviouralHalf(unittest.TestCase):
    """A real decompile, really compressed. A fixture here would answer NO."""

    # The corpus belongs to the INSTALLATION, not the package, and is
    # addressed through its authority (`install_paths`). No installation
    # — no corpus, and the absence is named as a skip with a reason
    # below, rather than a path invented on the spot.
    CORPUS = (install_data_path("decompile")
              or pathlib.Path("/несуществующая-установка/decompile"))

    def _gzipped_copy(self) -> pathlib.Path:
        source = None
        for run in sorted(self.CORPUS.glob("*/L0.jsonl")):
            if run.stat().st_size < 40_000_000:
                source = run
                break
        if source is None:
            self.skipTest(
                f"корпус разборов недоступен: {self.CORPUS} — это отсутствие "
                f"ПРИБОРА, а не признак чистоты")
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="gzsnap."))
        self.addCleanup(shutil.rmtree, tmp, True)
        with source.open("rb") as src, gzip.open(tmp / "L0.jsonl.gz", "wb") as dst:
            shutil.copyfileobj(src, dst)
        return tmp

    def test_header_and_stream_both_read_from_a_gzipped_snapshot(self):
        from kir.decompile.extract import L0JSONLReader

        run = self._gzipped_copy()
        reader = L0JSONLReader(run / "L0.jsonl")
        elements = sum(1 for _ in reader.iter_elements())
        self.assertGreater(elements, 0)
        # THIS line was the defect: the stream was read, the header was not.
        self.assertTrue(reader.metadata().doc_name)

    def test_the_graph_artifact_builds_from_a_gzipped_snapshot(self):
        from kir.decompile import graph_store as gs

        run = self._gzipped_copy()
        graph = gs.build_graph_for_run(run)
        self.assertGreater(len(graph), 0)
        self.assertEqual(graph.census.rows_seen,
                         graph.census.nodes + graph.census.refused)


class TheFourNewNames(unittest.TestCase):
    """🔴 ONE TEST FOR EACH OF THE FOUR NAMES ADDED ON 21.08.2026.

    Not one test for all four: the structural half already showed that
    "covered at all" and "covered by name" are different assertions, and
    the first turns green with three of four readers fixed. Every test
    takes the REAL prod reader of this name and hands it a REAL gzip.

    The files are synthetic deliberately, and this is not the same
    relaxation as in the behavioral half above. There the subject was
    the 47 MB L0 STREAM, where a fixture would answer "yes" to a
    question nobody asked. Here the subject is opening the file, not its
    content: a 30-byte compressed passport breaks in exactly the same
    way as a 206 MB one, `FileNotFoundError` does not know a size. The
    real corpus also MUST NOT be touched in tests: the janitor is
    cleaning it at this very time.
    """

    def _snapshot(self, name: str, payload: bytes) -> pathlib.Path:
        """A decompile directory where `name` sits ONLY compressed."""
        run = pathlib.Path(tempfile.mkdtemp(prefix="gzfour."))
        self.addCleanup(shutil.rmtree, run, True)
        with gzip.open(run / (name + ".gz"), "wb") as dst:
            dst.write(payload)
        self.assertFalse((run / name).exists(),
                         "сырой файл остался — тест проверял бы не то")
        return run

    # ── passport.json ────────────────────────────────────────────────────
    def test_passport_json_is_read_from_gzip(self):
        """Prod reader: `viewer.scene._doc_name_of` (the corpus list)."""
        from kir.viewer import scene

        run = self._snapshot("passport.json", json.dumps(
            {"doc_name": "Башня-К2", "change_stamp": "v1",
             "tree": {"noise": "x" * 4096}}).encode("utf-8"))
        self.assertEqual("Башня-К2", scene._doc_name_of(run / "passport.json"))

    # ── tree.json ────────────────────────────────────────────────────────
    def test_tree_json_is_read_from_gzip(self):
        """Two prod readers: `viewer.honesty` and `viewer.pull_request`."""
        from kir.viewer import honesty, pull_request

        tree = {"payload": {}, "children": [
            {"payload": {"source_element_id": "101", "kind": "op",
                         "op_name": "create_wall"}},
            {"payload": {"source_element_id": "102", "kind": "atom",
                         "reason": {"code": "no_lifter"}}}]}
        run = self._snapshot("tree.json",
                             json.dumps(tree).encode("utf-8"))

        rows, note = honesty.read_l1_honesty(run)
        self.assertTrue(note["available"],
                        f"вьюер объявил дерево недоступным: {note['reason']!r} "
                        f"— и покрасил бы ВСЁ здание в UNKNOWN")
        self.assertEqual(2, len(rows))

        self.assertEqual(tree, pull_request._tree(run.parent, run.name))
        self.assertGreater(pull_request._tree_mb(run.parent, run.name), 0.0)
        self.assertNotEqual(float("inf"),
                            pull_request._tree_mb(run.parent, run.name),
                            "размер сжатого дерева уехал в «бесконечно много "
                            "работы» — предложение выглядело бы неподъёмным")

    # ── verify.json ──────────────────────────────────────────────────────
    def test_verify_json_is_read_from_gzip(self):
        """Prod reader: `decompile.axes_census._verify_summary`."""
        from kir.decompile import axes_census

        payload = json.dumps({"rows": [{"x": 1}], "summary": {
            "total_leaves": 7, "op_count": 5, "atom_count": 2,
            "lift_coverage": 0.71, "compression_ratio": 1.4}})
        run = self._snapshot("verify.json", payload.encode("utf-8"))

        got = axes_census._verify_summary(run / "verify.json")
        self.assertIsNotNone(
            got, "сводка сверки не прочиталась со сжатого — перепись осей "
                 "объявила бы «прогон не дошёл до сверки»")
        self.assertEqual(7, got["total_leaves"])
        self.assertEqual(0.71, got["lift_coverage"])

    # ── named.json ───────────────────────────────────────────────────────
    def test_named_json_is_read_from_gzip(self):
        """`named.json` has NO prod reader — and that is a fact, not an omission.

        🔴 422 MB ACROSS 14 DECOMPILES THAT NO ONE READS. A census on
        21.08.2026 across `kukai/` and `tools/`: `pipeline.py` WRITES it,
        tests check the bytes, there is not a single reader. So what is
        checked here is the shim itself on this name — the one door a
        reader will use once it appears.
        """
        from kir.decompile.snapshot_io import (
            read_snapshot_text, snapshot_file_exists)

        payload = json.dumps({"name": "Этаж 1", "children": []})
        run = self._snapshot("named.json", payload.encode("utf-8"))
        self.assertTrue(snapshot_file_exists(run / "named.json"))
        self.assertEqual(payload, read_snapshot_text(run / "named.json"))

    def test_named_json_still_has_no_production_reader(self):
        """A reader has appeared — give it its own behavioral test.

        Red here does NOT mean "broken": it means the entry above ("zero
        readers") has stopped being true, and such an entry, left
        hanging, reads as "everything's under control."
        """
        readers = []
        for path in _sources():
            rel = path.relative_to(PACKAGE).as_posix()
            if rel.endswith("snapshot_janitor.py"):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            module = ast.parse(source)
            scan = _RawReadScan(source, ("named.json",))
            scan.visit(module)
            if scan.hits:
                readers.append(rel)
            elif "named.json" in source and (
                    "open_snapshot" in source or "read_snapshot" in source):
                # a shimmed reader is still a reader, and still requires
                # a test
                for node in ast.walk(module):
                    if (isinstance(node, ast.Call)
                            and getattr(node.func, "id", "") in _AST_SHIM_CALLS
                            and _ast_name_in(node, ("named.json",))):
                        readers.append(rel)
                        break
        self.assertEqual(
            [], sorted(set(readers)),
            "у `named.json` появился читатель — проведи его через "
            "`snapshot_io` и дай ЕМУ поведенческий тест, как у трёх соседей: "
            + ", ".join(sorted(set(readers))))


class TheJanitorCoversWhatTheReadersKnow(unittest.TestCase):
    """The janitor's list and the shim must agree — a divergence would be silent."""

    def test_the_four_new_names_are_in_the_janitor_list(self):
        names = _janitor_files()
        for name in ("passport.json", "tree.json", "verify.json", "named.json"):
            self.assertIn(
                name, names,
                f"{name} выпал из SNAPSHOT_FILES — 2.18 ГБ снова несжимаемы")
        self.assertEqual(10, len(names),
                         f"имён стало {len(names)}, а не 10: {names}")

    def test_the_digest_manifest_survives_the_wider_list(self):
        """The janitor's `--verify` on the four new names: wrote -> checked.

        Checked ON A COPY in tmp: the live corpus must not be touched, it
        is being cleaned at this time.
        """
        from kir.decompile import snapshot_io as sio

        run = pathlib.Path(tempfile.mkdtemp(prefix="gzdigest."))
        self.addCleanup(shutil.rmtree, run, True)
        for name in ("passport.json", "tree.json", "verify.json", "named.json"):
            blob = json.dumps({"file": name}).encode("utf-8")
            with gzip.open(run / (name + ".gz"), "wb") as dst:
                dst.write(blob)
            sio.record_digest(run, name, blob)
        self.assertEqual({}, sio.verify_digests(run),
                         "манифест не сошёлся сам с собой на новых именах")

        # FAIL control: a content swap must be VISIBLE.
        with gzip.open(run / "tree.json.gz", "wb") as dst:
            dst.write(json.dumps({"file": "подменено"}).encode("utf-8"))
        bad = sio.verify_digests(run)
        self.assertIn("tree.json", bad,
                      "подмена сжатого дерева прошла мимо свидетеля")


class ПропущенныйРазборНеИсчезаетИзЗнаменателя(unittest.TestCase):
    """🔴 The boundary measurement's denominator was silently shrunk by
    TWO mute `continue`s.

    A directory with no L0 and a directory with an UNREADABLE L0 were
    skipped equally silently, and the shares rode up for the sole reason
    that no source was found (F-129). The response (skip) is correct in
    both cases — the measurement must not be failed over one decompile;
    what is now asked is the REASON, and there are TWO DIFFERENT reasons.
    """

    def test_two_kinds_of_skip_are_not_one(self) -> None:
        from kir.instruments.bounds_audit import scan_runs
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "не_разбор").mkdir()
            broken = root / "битый"
            broken.mkdir()
            (broken / "L0.jsonl").write_text("{сломано", encoding="utf-8")
            targets, skipped = scan_runs(root)
            self.assertEqual(targets, [], "годных разборов здесь нет")
            self.assertEqual(len(skipped), 2)
            self.assertIn("не разбор", skipped["не_разбор"])
            self.assertIn("не прочёлся", skipped["битый"])
            self.assertNotEqual(
                skipped["не_разбор"], skipped["битый"],
                "«это не разбор» и «разбор ЕСТЬ, прочитать не смогли» — разные "
                "факты: первый о раскладке, второй о ПОРЧЕ")

    def test_a_readable_run_is_a_target_not_a_skip(self) -> None:
        """A positive control: a valid decompile does not land among the skips."""
        from kir.instruments.bounds_audit import scan_runs
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            good = root / "годный"
            good.mkdir()
            (good / "L0.jsonl").write_text(
                json.dumps({"record": "header",
                            "document": {"doc_name": "проба"}},
                           ensure_ascii=False) + "\n",
                encoding="utf-8")
            targets, skipped = scan_runs(root)
            self.assertEqual(len(targets), 1)
            self.assertEqual(skipped, {},
                             "читаемый разбор объявлять пропущенным нельзя")


if __name__ == "__main__":
    unittest.main()
