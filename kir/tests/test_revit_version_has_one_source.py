"""THE REVIT VERSION IS DERIVED IN ONE PLACE, AND THE SEVENTH MUST NAME
ITSELF.

On 2026-08-13 the owner opened TWO Revits at once for the first time —
2026 and 2023 on one machine. Before that day, the default "2026" happened
to match the truth on the single machine everything is checked on, so a
green live run was a fact about a sample of one, not about the code (the
resolution logic lives in `kir/revit_version.py`).

WHAT THIS FILE GUARDS. Not "how many years are in the tree" — but that the
value called the Revit version comes from ONE place, and that every new
place fails HERE, named explicitly.

═══ THE SUBJECT IS NAMED BEFORE IT IS COUNTED ═══

The raw data was read once before any filtering: 56 year literals across
16 `kir` files, excluding tests. They are NOT homogeneous, and what tells
them apart is POSITION, not appearance — a grep for "2026" would lie in
both directions:

    CONSUMPTION  `if ver < "2022"`, `TOPOSOLID_MIN_VERSION = "2024"`,
                 `E003_EXPECTED_BELOW = {...}` — emitter branching and
                 capability thresholds. They ACCEPT a version and say
                 nothing about which one we have. **Forbidding them would
                 mean forbidding the language:** the emitter must branch,
                 `Floor.Create` versus `doc.Create.NewFloor` is exactly
                 the six target versions.

    DERIVATION   `revit_version: str = "2026"`, `x or "2026"`,
                 `m.group(0) if m else "2026"`, `d.get(k, "2026")` — the
                 literal ANSWERS the question "which version," when
                 nobody said. **This is the subject, and only this.**

A third subject was found by reading and was nearly missed: **A COPY OF
THE AUTHORITY** — the sequence of six years, written out a second time.
When 2027 arrives in the registry, the copy will silently stay at six; no
rule about defaults sees it, because it answers no question — it REPEATS
an answer.

═══ THE KIND OF THESE LISTS ═══

`DERIVATIONS` and `AUTHORITY_COPIES` are **COMPLETE BY CONSTRUCTION**:
their membership is not maintained by hand, it is computed by an AST walk
and checked against what is declared. "No record" means "no such place,"
not "we don't know." Both directions of the equality are mandatory: a
record without a place is also red, otherwise the registry would outlive
its own subject.

But the completeness of such a list is the completeness of its MATCHER,
not of the authority (the house law, paid for by `_emits`, which used to
search for a label instead of a branch). That is why the matcher reads a
POSITION in the parse tree, not the text of a line, and it has a control
in both directions — `TheProbeCanSayNo`.

═══ WHAT THIS INSTRUMENT DOES NOT COVER (silence reads as coverage) ═══

1. **Only `kir`, and this is a decision, not laziness.** The compiler is
   published as a separate repository under Apache-2.0; a guard reaching
   into `kukai/api` or `kukai/llm` would break exactly the boundary this
   split was set up for. The five spots in `api/admin_kir.py` and the one
   in `llm/api_members.py` from the director's measurement are OUTSIDE
   the scope, forever, and will never fall under this ratchet.

   **Stated here — out loud, at the CORPUS's demand, because it cannot be
   left implied: a green ratchet says "no more derivations IN MY
   CATALOG," NOT "no more derivations."** The very same day, this
   overturned the signature of the review lock: a verdict is a property
   of the input, and the instrument had not named its input. Here the
   input is named — `kir` excluding tests, 150 files, and the count is
   printed in the error message.

   What guards those six spots: `kir/tests/
   test_revit_version_provenance_rides.py` (the CORPUS) — but it catches
   only one form of return and does NOT freeze the membership. The hole
   is named, not closed.
2. **An argument at a call site does not count as a derivation.**
   `compile_program(prog, revit_version="2026", ...)` in `gate_runner` is
   a deliberate choice of the test fixture, not an answer born of not
   knowing. A rule that also caught this would catch every parameterized
   run.
3. **A year arriving other than as a literal** — from a variable, from
   the environment, assembled from pieces — is invisible by construction.
   The instrument reads literals.
4. **It does not check WHAT the source returned.** The correctness of
   `revit_version.resolve` itself is the subject of its own tests.
"""
from __future__ import annotations

import ast
import pathlib
import tempfile
import unittest

# 27.08.2026: KIR is a separate package; its root is the package directory,
# not "three steps up plus two names" from the previous layout.
IR = pathlib.Path(__file__).resolve().parents[1]
BACKEND = IR.parent

#: Years that in this house denote the Revit version. The range is wider
#: than the registry ON PURPOSE: the instrument must see the literal "2027"
#: the day it is entered, not after the registry accepts it.
YEARS = {str(y) for y in range(2015, 2036)} | set(range(2015, 2036))

#: THE ONLY place where the version default is entitled to live.
SOURCE = "kir/revit_version.py"


# --------------------------------------------------------------------------
# MATCHER: A POSITION IN THE PARSE TREE, NOT THE TEXT OF THE LINE
# --------------------------------------------------------------------------

def _is_year(node) -> bool:
    return isinstance(node, ast.Constant) and node.value in YEARS


def _docstrings(tree) -> set:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            doc = ast.get_docstring(n, clean=False)
            if doc:
                out.add(doc)
    return out


def _parents(tree) -> dict[int, ast.AST]:
    out: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


def _is_compared(node, parents: dict[int, ast.AST]) -> bool:
    """A literal is COMPARED, not turned into the answer.

    CORPUS correction 13.08, and it sharpens the subject rather than
    softening the rule. `gate_runner.py:1089` reads, in full, as:

        if ver < E003_EXPECTED_BELOW.get(name, "2021")

    `"2021"` here is a guard with the value "never": a lower bound at which
    `ver < ...` is false for all six versions. The literal answers not
    "which version" but "below which should KIR-E003 be expected", and the
    answer is "below none". By FORM it is indistinguishable from
    `d.get(k, "2026")`; what decides is SEMANTICS, and its mechanical
    signature is this: climb to the parent and ask whether this is an
    operand of a comparison.

    One-line test: **does the literal become the answer — or is it compared
    against the answer.**
    """
    seen = 0
    current = node
    while seen < 4:
        parent = parents.get(id(current))
        if parent is None:
            return False
        if isinstance(parent, ast.Compare):
            return True
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.Return,
                               ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        current, seen = parent, seen + 1
    return False


def _qualname(tree, node) -> str:
    """The nearest enclosing name is a key that survives line shifts.

    A key on `file:line` would go stale from any edit higher up in the
    file, and the ratchet would go red on someone else's commits, reporting
    nothing about the actual subject.
    """
    best, best_span = "<module>", None
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            continue
        end = getattr(n, "end_lineno", n.lineno)
        if n.lineno <= node.lineno <= end:
            span = end - n.lineno
            if best_span is None or span < best_span:
                best, best_span = n.name, span
    return best


def derivations_in(path: pathlib.Path, source: str | None = None) -> list[dict]:
    """Places that GIVE AWAY a version where there was no answer."""
    src = source if source is not None else path.read_text(
        encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    docs = _docstrings(tree)
    parents = _parents(tree)
    found: list[dict] = []

    def add(node, form, binding):
        if isinstance(node.value, str) and node.value in docs:
            return
        if _is_compared(node, parents):
            return
        found.append({
            "file": path.as_posix(), "line": node.lineno,
            "qual": _qualname(tree, node), "form": form,
            "binding": binding, "value": str(node.value),
        })

    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            positional = a.posonlyargs + a.args
            pad = [None] * (len(positional) - len(a.defaults))
            pairs = list(zip(positional, pad + list(a.defaults)))
            pairs += list(zip(a.kwonlyargs, a.kw_defaults))
            for arg, default in pairs:
                if default is not None and _is_year(default):
                    add(default, "умолчание параметра", arg.arg)
        elif isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
            for value in n.values[1:]:
                if _is_year(value):
                    add(value, "запасной ответ `or`", "<выражение>")
        elif isinstance(n, ast.IfExp):
            for branch in (n.body, n.orelse):
                if _is_year(branch):
                    add(branch, "запасной ответ тернарника", "<выражение>")
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and len(n.args) == 2
                and _is_year(n.args[1])):
            add(n.args[1], "умолчание `.get`", "<словарь>")
        elif isinstance(n, ast.Assign) and _is_year(n.value):
            for target in n.targets:
                name = getattr(target, "id", None) or getattr(
                    target, "attr", None)
                if name and "version" in name.lower() and not name.isupper():
                    add(n.value, "присваивание версии", name)
        elif (isinstance(n, ast.AnnAssign) and n.value is not None
                and _is_year(n.value)):
            name = getattr(n.target, "id", None) or getattr(
                n.target, "attr", None)
            if name and "version" in name.lower() and not name.isupper():
                add(n.value, "присваивание версии", name)
    return found


def authority_copies_in(path: pathlib.Path,
                        source: str | None = None) -> list[dict]:
    """Sequences of >=3 years — a second copy of the version registry.

    The threshold is 3, not 2: a pair of years is most often a "from–to"
    boundary, not an enumeration. The cardinality at which the rule is ABLE
    to fire is named here, because at a threshold of 7 it would stay silent
    on today's six.
    """
    src = source if source is not None else path.read_text(
        encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            continue
        if not n.elts or not all(_is_year(e) for e in n.elts):
            continue
        if len(n.elts) < 3:
            continue
        out.append({"file": path.as_posix(), "line": n.lineno,
                    "qual": _qualname(tree, n), "n": len(n.elts),
                    "values": [str(e.value) for e in n.elts]})
    return out


def _files() -> list[pathlib.Path]:
    return [p for p in sorted(IR.rglob("*.py")) if "/tests/" not in p.as_posix()]


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(BACKEND).as_posix()


def sweep() -> tuple[dict[str, int], dict[str, int], list[str], int]:
    """Composition of outputs -> HOW MANY of them are in place, not just
    "there is a place".

    The key carries a COUNT on purpose, and it's not decoration. The first
    edition keyed on `файл::функция::привязка`, and `shadow._norm_version`
    — where TWO ternaries answer "2026" — collapsed into a single record.
    That means a second output inside an already-recorded function would be
    invisible BY CONSTRUCTION: add a third, and the ratchet stays silent.
    This is exactly "cardinality 1 does not pin a multi-branch site" — my
    own finding from that same day, re-committed here in the instrument,
    against itself.
    """
    derived: dict[str, int] = {}
    copies: dict[str, int] = {}
    answers: set[str] = set()
    for path in _files():
        rel = _rel(path)
        for row in derivations_in(path):
            key = "%s::%s::%s::%s" % (rel, row["qual"], row["binding"],
                                      row["form"])
            derived[key] = derived.get(key, 0) + 1
            answers.add(row["value"])
        for row in authority_copies_in(path):
            key = "%s::%s" % (rel, row["qual"])
            copies[key] = copies.get(key, 0) + 1
    return derived, copies, sorted(answers), len(_files())


# --------------------------------------------------------------------------
# THE RATCHET IS NAME-BY-NAME. A number would say "there is more"; a list
# says "there is more, NAMELY THIS", and only the second tells you what to
# do.
# --------------------------------------------------------------------------

#: Place -> (how many literals there give away a version, why that still
#: holds).
#: The count is mandatory: without it, a second output in an already-
#: recorded function is invisible.
DERIVATIONS: dict[str, tuple[int, str]] = {
    "kir/compiler.py::emit::revit_version::умолчание параметра":
        (1, "13.08: умолчание ПУБЛИЧНОЙ функции — каллер видит его в "
            "сигнатуре. Оставлено осознанно (довод КОРПУСА): функция без "
            "умолчания заставит каждого каллера выдумать своё, и выводов "
            "станет больше, а не меньше"),
    "kir/compiler.py::compile_program::revit_version::умолчание параметра":
        (1, "13.08: ГЛАВНОЕ умолчание дома — 12 голденов из 69 "
            "версиезависимы (7 меняют ИСХОД, 5 — только C#). Видимо в "
            "сигнатуре, поэтому остаётся; но если седьмое место появится, "
            "оно появится здесь"),
    "kir/compiler.py::compile_rebuild_chunk::revit_version::"
    "умолчание параметра":
        (1, "13.08: то же умолчание на пути перестройки"),
    "kir/coverage_feed.py::record_rejections::revit_version::"
    "умолчание параметра":
        (1, "13.08: телеметрия отказов пишет версию в корпус; умолчание тут "
            "красит СТАТИСТИКУ, а не здание"),
    "kir/serving.py::_record_pre_effect::revit_version::"
    "умолчание параметра":
        (1, "13.08: умолчание в квитанции до эффекта; после проводки "
            "`1c8ab589` каллер передаёт разрешённое значение, умолчание — "
            "последний рубеж"),
    "kir/shadow.py::_norm_version::<выражение>::"
    "запасной ответ тернарника":
        (1, "13.08: ЕДИНСТВЕННОЕ место дома, спрашивающее spec.REVIT_VERSIONS "
            "— при том что модуль объявлен observe-only. Единственный, кто "
            "читал авторитет, был единственным, чей ответ ничего не решал. "
            "🔴 СЧЁТ 2 -> 1 СНИЖЕН 30.08.2026 ТЕМ ЖЕ КОММИТОМ, ЧТО ПОЧИНИЛ "
            "МЕСТО (F-351), и это УМЕНЬШЕНИЕ ЧИСЛА ВЫВОДОВ, а не ослабление "
            "храповика: «2026» выдавалось ДВУМЯ тернарниками — при "
            "непопадании регулярки и при неподдерживаемом годе, — а теперь "
            "точка подстановки ОДНА, и пять разных случаев различает "
            "ПРОВЕНАНС (`revit_version_source`), а не молчание. Прежде все "
            "пять давали одно «2026», и замер с Ревита 2019 ложился в корпус "
            "как замер на 2026"),
}

#: Copies of the version registry. The authority is
#: `registry_base.REVIT_VERSIONS`.
AUTHORITY_COPIES: dict[str, tuple[int, str]] = {
    "kir/registry_base.py::<module>":
        (1, "АВТОРИТЕТ. Здесь этой шестёрке и место"),
}


class TheDerivationsAreExactlyThese(unittest.TestCase):
    def test_the_register_matches_what_the_tree_holds(self):
        derived, _copies, _answers, files = sweep()
        self.assertGreater(
            files, 50,
            "обход не нашёл файлов — прибор смотрит не туда, и пустой "
            "результат был бы зелёным по построению")
        declared = {k: n for k, (n, _why) in DERIVATIONS.items()}
        self.assertEqual(
            derived, declared,
            "состав мест, ВЫВОДЯЩИХ версию Ревита, изменился.\n"
            f"  появилось: {sorted(set(derived) - set(declared))}\n"
            f"  исчезло:   {sorted(set(declared) - set(derived))}\n"
            "  счёт разошёлся: "
            f"{ {k: (declared.get(k), v) for k, v in derived.items() if declared.get(k) != v} }\n"
            f"  (просмотрено файлов: {files})\n"
            "Новое место — это седьмой ответ на «какая версия», и он обязан "
            f"быть назван здесь ИЛИ взят из {SOURCE}. Исчезнувшее — снимите "
            "запись вместе с причиной.")

    def test_every_entry_says_why_and_when(self):
        for key, (count, reason) in sorted(DERIVATIONS.items()):
            with self.subTest(site=key):
                self.assertGreater(count, 0, f"{key}: счёт нулевой")
                self.assertTrue(reason.strip(), f"{key}: причина пуста")
                self.assertTrue(
                    any(ch.isdigit() for ch in reason),
                    f"{key}: в причине нет даты — запись без даты не долг, "
                    "а глушилка")

    def test_the_authority_is_not_copied(self):
        _derived, copies, _answers, _files = sweep()
        declared = {k: n for k, (n, _why) in AUTHORITY_COPIES.items()}
        self.assertEqual(
            copies, declared,
            "перечень версий выписан не там, где объявлено.\n"
            f"  появилось: {sorted(set(copies) - set(declared))}\n"
            f"  исчезло:   {sorted(set(declared) - set(copies))}")

    def test_there_is_exactly_one_answer_to_i_do_not_know(self):
        """ONE answer for "don't know" across the entire scope — and this
        is a NEW state.

        On the morning of 13.08 there were three: 2026, 2023
        (`sdk.compile`) and 2021 (`gate_runner`, which turned out to be a
        guard and not an output). Plus 2024 in `llm/api_members.py` —
        OUTSIDE the scope. Wiring `1c8ab589` brought it down to one.

        The number here is not for its own sake: every EXTRA answer is a
        place that will diverge from the rest on exactly the device where
        the version is not the one we have. Before 13.08 no such devices
        existed — now the owner has 2026 and 2023 open at the same time.
        """
        _derived, _copies, answers, _files = sweep()
        self.assertEqual(
            answers, ["2026"],
            "ответов на «не знаю» стало больше одного: %s. Второй ответ — "
            "это расхождение, которое проявится только на чужой версии."
            % answers)


class TheProbeCanSayNo(unittest.TestCase):
    """Control in both directions. The plant LOOKS LIKE THE SITE, not like
    a marker.

    The cardinality is named: the FAIL control plants exactly the forms
    that live in the tree (parameter default, `or`, ternary, `.get`), while
    the PASS control plants those the instrument must LET THROUGH. Without
    the second half, the rule "any year is an output" would pass both
    checks and would forbid the emitter from branching at all.
    """

    def _write(self, text: str) -> pathlib.Path:
        path = pathlib.Path(tempfile.mkdtemp()) / "planted.py"
        path.write_text(text, encoding="utf-8")
        return path

    def test_it_catches_each_shape_of_a_real_derivation(self):
        planted = self._write(
            "import re\n"
            "def resolve(ctx, revit_version: str = '2025'):\n"
            "    v = ctx.reported or '2024'\n"
            "    m = re.search(r'20\\d\\d', ctx.raw)\n"
            "    w = m.group(0) if m else '2023'\n"
            "    z = ctx.meta.get('revit_version', '2022')\n"
            "    doc_version = '2021'\n"
            "    return v, w, z, doc_version\n")
        found = derivations_in(planted)
        forms = {row["form"] for row in found}
        self.assertEqual(
            forms,
            {"умолчание параметра", "запасной ответ `or`",
             "запасной ответ тернарника", "умолчание `.get`",
             "присваивание версии"},
            "прибор не увидел одну из живых форм вывода: %s" % sorted(forms))
        self.assertEqual(len(found), 5, [r["form"] for r in found])

    def test_it_stays_silent_on_consumption_which_is_the_whole_language(self):
        planted = self._write(
            "MIN_VERSION = '2024'\n"
            "SINCE = 2022\n"
            "def emit(ver):\n"
            "    if ver < '2022':\n"
            "        return 'old'\n"
            "    elif ver >= '2024':\n"
            "        return 'new'\n"
            "    return compile_it(ver, revit_version='2026')\n")
        found = derivations_in(planted)
        self.assertEqual(
            found, [],
            "прибор объявил выводом ПОТРЕБЛЕНИЕ версии: %s. Так он запретил "
            "бы эмиттеру ветвиться по шести целевым версиям — то есть язык."
            % [(r["form"], r["line"]) for r in found])

    def test_a_literal_that_is_compared_is_not_a_derivation(self):
        """CORPUS correction: a guard with the value "never" is not an
        answer.

        Both halves are mandatory and they sit SIDE BY SIDE, because in
        form they differ by one word: in the first, `.get` is compared; in
        the second, it is assigned. Without the second half, the rule
        "`.get` with a year is never an output" would pass this test and
        would blind the instrument to a genuine dictionary default.
        """
        compared = self._write(
            "BELOW = {'a': '2024'}\n"
            "def gate(ver, name):\n"
            "    return ver < BELOW.get(name, '2021')\n")
        self.assertEqual(
            derivations_in(compared), [],
            "сторож нижней границы объявлен выводом версии")

        adopted = self._write(
            "TABLE = {'a': '2024'}\n"
            "def resolve(meta):\n"
            "    revit_version = TABLE.get(meta, '2021')\n"
            "    return revit_version\n")
        found = derivations_in(adopted)
        self.assertEqual(
            [r["form"] for r in found], ["умолчание `.get`"],
            "настоящее умолчание словаря пропущено — правило ослепло: %s"
            % found)

    def test_it_catches_a_second_copy_of_the_registry(self):
        planted = self._write(
            "SUPPORTED = ('2021', '2022', '2023', '2024', '2025', '2026')\n")
        self.assertEqual(len(authority_copies_in(planted)), 1)

    def test_a_pair_of_years_is_not_a_copy(self):
        planted = self._write("BOUNDS = ('2021', '2026')\n")
        self.assertEqual(
            authority_copies_in(planted), [],
            "пара годов — это границы «от и до», а не перечисление; правило "
            "с порогом 2 объявляло бы копией каждый диапазон")


if __name__ == "__main__":
    unittest.main()
