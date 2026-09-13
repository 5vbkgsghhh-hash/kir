"""WARM-UP MUST COVER OUR OWN LAZY IMPORTS.

🔴 THIS RATCHET WAS SET UP FROM A LIVE FAILURE ON 15.08, AND THIS IS
THE THIRD OCCURRENCE OF ONE DEFECT.

The sandbox forbids imports outside the whitelist
(`sandbox.ALLOWED_IMPORTS` — `math`, `itertools`, `functools`). The ban
applies to EVERYTHING executed in the child, including OUR OWN code:
the language's names are injected by functions, and a lazy
`from kukai.… import …` inside the body of such a function is caught
by the same hook as an author's import. The only legitimate way is to
warm the module up BEFORE isolation (`course.language.warm_for_source`).

What happened three times:

1. `spec()` pulled in `kir.acceptance` / `kir.decompile.extract` and
   refused with `KIR-B004` — a correct piece of help looked like the
   model's script's fault. Closed with a line in `_WARM_BY_NAME` (a
   comment right there).
2. `design_check()` / `preview()` — the same line, the same fix.
3. **`unit(reads_as=…)`** — the design-intent-unit predicate, added on
   15.08, pulls in `kir.assembly_view` for the reading registry. No
   warm-up line was set up for it, and on a LIVE run it responded:

       KIR-B004: импорт 'kir.assembly_view' запрещён
       строка 10: with unit("наружная оболочка дома", reads_as="continuous"):
       blame: author

   That is, the day's flagship capability was entirely unreachable to
   the author, and the refusal BLAMED THE AUTHOR for an import the
   author never wrote, and recommended an unrelated fix ("the language
   is already available without the import").

The wave's offline tests never saw this: there is no sandbox there,
the import goes through. The defect lives EXACTLY at the real door —
exactly the class of defect this tree requires the entry point to be
built from prod code in order to catch.

WHY A RATCHET, NOT ANOTHER LINE. The `_WARM_BY_NAME` table documents
case (1) right above itself — and case (3) happened anyway. So prose
does not hold; what must hold is a run.
"""
from __future__ import annotations

import ast
import os
import unittest

from kir import sandbox

# 🔴 THE COURSE'S ADDRESS AFTER THE SPLIT (28.08.2026). There used to
# be four `dirname` calls and `kukai/ir/course` — the layout before
# 27.08. The same count gives `/opt`, and the `ir` package has been
# renamed to `kir` and sits one step closer.
PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSE = os.path.join(PACKAGE, "course", "__init__.py")


def _lazy_kukai_imports_by_function() -> dict[str, set[str]]:
    """Top-level function name -> `kukai.*` modules imported IN THE
    BODY.

    Taken from the SOURCE by parsing, not by grep: a grep for `from
    kukai` would also catch module-level imports, which need no
    warm-up at all.
    """
    with open(COURSE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        found: set[str] = set()
        for inner in ast.walk(node):
            # 🔴 THE PACKAGE PREFIX CHANGED AT THE SPLIT (28.08.2026):
            # `kukai.ir` was renamed to `kir`, and a scan for "kukai."
            # found ZERO functions. This file's own control ("fewer
            # than three — almost certainly a miss on the file") fired
            # correctly and named the reason itself.
            if isinstance(inner, ast.ImportFrom) and (inner.module or "").startswith("kir."):
                found.add(inner.module)
            elif isinstance(inner, ast.Import):
                for alias in inner.names:
                    if alias.name.startswith("kir."):
                        found.add(alias.name)
        if found:
            out[node.name] = found
    return out


def _lazy_third_party_by_module(path: str) -> set[str]:
    """External modules imported LAZILY (inside a function body) in this
    file.

    🔴 WHY BY MODULE, NOT BY THE BODY OF THE INJECTED FUNCTION. This is
    exactly where the guard missed on 19.08.2026: `sweep()` contains not
    a single `import` — `shapely` is pulled in by its helpers
    `_polygon_from_contour` and `_triangulate`, one floor down. A scan
    of the body returned empty, no requirement arose, and the ratchet
    was GREEN with the warm-up line missing.
    A cost measurement (the file was edited, the cache dropped): without
    the line, a live run gives back
    `KIR-B006 ModuleNotFoundError: No module named 'shapely'` with
    **blame=author** — the author is blamed for OUR OWN import, exactly
    the disease the warm-up table was set up against.

    So the rule is CONSERVATIVE, on purpose: an injected name must warm
    up everything external that ITS MODULE lazily pulls in.
    Over-covering here costs milliseconds of warm-up; under-covering
    costs blaming the author.
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    roots = set(sandbox.ALLOWED_IMPORTS) | set(sandbox.GEOMETRY_IMPORTS)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            names = []
            if isinstance(inner, ast.ImportFrom) and inner.module:
                names = [inner.module]
            elif isinstance(inner, ast.Import):
                names = [a.name for a in inner.names]
            for name in names:
                if name.split(".")[0] in roots:
                    found.add(name)
    # `math`, `itertools`, `functools` are the standard library — always
    # present in the child and needing no warm-up. We count as
    # "external" whatever the sandbox OPENS with a flag, not whatever
    # is already there.
    return {m for m in found if m.split(".")[0] in set(sandbox.GEOMETRY_IMPORTS)}


class ПрогревПокрываетНашиЛенивыеИмпорты(unittest.TestCase):

    def test_every_injected_name_has_its_modules_warmed(self):
        """A module pulled in by an INJECTED function must be in the
        warm-up.

        Otherwise the capability is unreachable to the author, and the
        refusal blames the author.
        """
        from kir.course import SANDBOX_NAMES
        from kir.course.language import _WARM_BY_NAME

        # THE PARENT PACKAGE WARMS ITSELF UP, and this is not a
        # concession: importing `kir.design_check` puts `kir` into
        # `sys.modules`, and the sandbox hook is called ONLY for what
        # isn't there yet. Without this line, the guard went red on
        # "`design_check()` pulls in `kir`" — a false alarm, caught by
        # the guard itself on the very first run.
        warmed: set[str] = set()
        for modules in _WARM_BY_NAME.values():
            for module in modules:
                parts = module.split(".")
                for i in range(1, len(parts) + 1):
                    warmed.add(".".join(parts[:i]))

        lazy = _lazy_kukai_imports_by_function()
        missing: list[str] = []
        for name in sorted(SANDBOX_NAMES):
            for module in sorted(lazy.get(name, ())):
                # `kir.dsl` lives in the child by construction: it IS
                # the language, the sandbox loads it as `dsl_module`
                # before isolation.
                if module == "kir.dsl":
                    continue
                if module not in warmed:
                    missing.append("%s() тянет %s" % (name, module))
        assert not missing, (
            "впрыснутая в песочницу функция лениво импортирует модуль, "
            "которого нет в прогреве — на живом прогоне он отдаст KIR-B004 и "
            "ОБВИНИТ АВТОРА за наш импорт:\n  " + "\n  ".join(missing) +
            "\nдобавь строку в `course.language._WARM_BY_NAME`")

    def test_every_injected_name_warms_its_third_party_too(self):
        """🔴 THE SECOND AXIS OF WARM-UP: external libraries, not just
        `kukai.*`.

        Before 19.08.2026 the guard knew exactly one kind — a lazy
        import of OUR OWN module. The external kind (`shapely`,
        `numpy`) was held together by a MANUAL workaround, and a
        comment in `language.py` claimed that "the ratchet has been
        extended to this kind." That was prose wider than the code:
        `shapely` was never once mentioned in the guard, and `sweep`
        slipped past it in silence.
        """
        import inspect
        from kir.course import SANDBOX_NAMES
        from kir.course.language import _WARM_BY_NAME

        missing: list[str] = []
        for name in sorted(SANDBOX_NAMES):
            target = SANDBOX_NAMES[name]
            if not callable(target):
                continue
            try:
                source_file = inspect.getsourcefile(target)
            except TypeError:
                continue
            if not source_file or "/kir/" not in source_file:
                continue
            needed = _lazy_third_party_by_module(source_file)
            if not needed:
                continue
            warmed = set(_WARM_BY_NAME.get(name, ()))
            for module in sorted(needed - warmed):
                missing.append("%s() из %s тянет %s"
                               % (name, source_file.rsplit("/", 1)[-1], module))
        assert not missing, (
            "впрыснутое имя тянет ВНЕШНЮЮ библиотеку, которой нет в его строке "
            "прогрева. Живой прогон отдаст KIR-B006 `ModuleNotFoundError` с "
            "blame=author, то есть обвинит автора за НАШ импорт:\n  "
            + "\n  ".join(missing)
            + "\nдобавь модуль в `course.language._WARM_BY_NAME`")

    def test_the_third_party_axis_can_actually_fail(self):
        """FAIL control for the second axis: remove ONE line, expect
        ONE finding."""
        from kir.course import language
        сохранено = dict(language._WARM_BY_NAME)
        try:
            language._WARM_BY_NAME.pop("sweep", None)
            with self.assertRaises(AssertionError) as поймано:
                self.test_every_injected_name_warms_its_third_party_too()
            assert "sweep()" in str(поймано.exception), str(поймано.exception)
        finally:
            language._WARM_BY_NAME.clear()
            language._WARM_BY_NAME.update(сохранено)

    def test_a_realistic_unit_call_actually_warms_the_predicate(self):
        """Coverage alone is not enough: the table's key must MATCH the
        real call.

        The table looks for the key as a SUBSTRING in the source (form
        7 — convention instead of authority), so coverage is checked
        against the behavior on the text the author actually writes.
        """
        from kir.course.language import warm_for_source

        source = ('with unit("фасадная лента", reads_as="continuous"):\n'
                  '    create_wall(p0_mm=[0, 0], p1_mm=[1000, 0])\n')
        assert "kir.assembly_view" in warm_for_source(source), (
            "настоящий вызов `unit(reads_as=…)` не прогревает реестр "
            "прочтений — предикат откажет KIR-B004 на живом ходу")

    def test_the_ratchet_can_actually_fail(self):
        """FAIL control. A guard that cannot go red is worse than none
        at all: it creates confidence and gives no protection."""
        from kir.course import language

        original = dict(language._WARM_BY_NAME)
        try:
            language._WARM_BY_NAME.pop("reads_as", None)
            source = 'with unit("x", reads_as="continuous"):\n    pass\n'
            assert "kir.assembly_view" not in language.warm_for_source(
                source), "нечего было ломать — строка прогрева не решала"
        finally:
            language._WARM_BY_NAME.clear()
            language._WARM_BY_NAME.update(original)

    def test_the_scan_sees_something_at_all(self):
        """DENOMINATOR CONTROL. Zero lazy imports would mean the parser
        missed the file entirely, and the first test would be green by
        construction."""
        lazy = _lazy_kukai_imports_by_function()
        assert len(lazy) >= 3, (
            "разбор нашёл меньше трёх функций с ленивыми импортами — "
            "почти наверняка промах по файлу, а не чистый курс")


class ПРОВАЛПРОГРЕВАНЕОБВИНЯЕТАВТОРА(unittest.TestCase):
    """🔴 THE SECOND HALF OF THE SAME CLASS, CLOSED ON 01.09.2026.

    The class above guards that the needed module MADE IT into the
    warm-up. It does not guard the case where the warm-up line EXISTS
    but the load FAILED: the module is not on the child's path, the
    library isn't built, the environment is different. Then
    `_MetaGuard` catches the same lazy import, and before 01.09 the
    author got exactly the refusal this file's header describes as
    FIXED:

        KIR-B004: импорт 'kir.design_check' запрещён.
                  язык уже доступен без импорта: пишите create_wall(...)
        строка 56: design_check([stairs, build()])
        blame: author

    — on the line where the author wrote a CALL and not a single
    import.

    The `WARM_FAILED_MARK` label was set up on 29.08 (E-18) for exactly
    this purpose: so a warm-up failure would be heard, and it WAS heard
    — IN THE RECEIPT. But the refusal the AUTHOR reads never looked at
    the receipt. The channel existed, the reader did not; the fix is a
    reader (`sandbox._warm_failure_for`), not a third label.

    THE MEASUREMENT THAT FORCED THE FIX: the standard recipe of the
    «жильё» course under `PYTHONPATH=/opt/kir python3.12` -> KIR-B004
    with the blame on the author; the same tree under a venv where the
    package is installed -> 19 passed. That is, the refusal was ABOUT
    THE ENVIRONMENT, but printed as if ABOUT THE SCRIPT.
    """

    def test_a_failed_warm_is_named_and_not_blamed_on_the_author(self):
        """A warm-up failure must name ITSELF and lift the blame off
        the author."""
        state = {"isolation": {
            "warmed": ["kir.preview",
                       "НЕ ЗАГРУЖЕН:kir.design_check (ModuleNotFoundError)"],
            "warmed_libs": [],
        }}
        found = sandbox._warm_failure_for(state, "kir.design_check")
        assert found is not None, (
            "отказ не увидел провала прогрева, записанного прогревом же — "
            "значит автор снова получит «импорт запрещён» за свой вызов")
        assert "ModuleNotFoundError" in found, (
            f"причина провала потеряна по дороге: {found!r}")

    def test_the_third_party_field_is_asked_too(self):
        """There are TWO warm-ups, with different fields — both must
        be checked.

        A `shapely` failure and a `kir.design_check` failure are, to
        the author, one and the same event; checking only one field
        would mean fixing half the problem.
        """
        state = {"isolation": {
            "warmed": [],
            "warmed_libs": ["НЕ ЗАГРУЖЕН:shapely.ops (ImportError)"],
        }}
        assert sandbox._warm_failure_for(state, "shapely.ops") is not None, (
            "поле `warmed_libs` не спрошено — половина прогревов немая")

    def test_a_prefix_neighbour_is_not_mistaken_for_the_asked_module(self):
        """🔴 WHAT IS CHECKED IS THE NAME PREFIX, NOT SUBSTRING
        CONTAINMENT.

        `kir.design` is a prefix of `kir.design_check`. A substring
        search would declare a NEIGHBOR's failure to be the failure of
        the one being asked about, and would lift the blame right
        where it belongs.
        """
        state = {"isolation": {
            "warmed": ["НЕ ЗАГРУЖЕН:kir.design_check (ModuleNotFoundError)"],
            "warmed_libs": [],
        }}
        assert sandbox._warm_failure_for(state, "kir.design") is None, (
            "провал соседа принят за провал спрошенного модуля")

    def test_a_healthy_warm_leaves_the_verdict_to_the_import_guard(self):
        """Warm-up intact -> the refusal must stay the same, "import
        forbidden."

        Otherwise the fix would launder away a GENUINE ban: an author
        who wrote `import os` would get "the environment is at fault."
        """
        state = {"isolation": {"warmed": ["kir.design_check"],
                               "warmed_libs": ["shapely.ops"]}}
        assert sandbox._warm_failure_for(state, "kir.design_check") is None
        assert sandbox._warm_failure_for(state, "os") is None

    def test_a_receipt_without_the_field_does_not_crash(self):
        """The warm-up might not have run at all: the field is either
        a `failed (...)` string or absent. The reader must return
        `None`, not crash — otherwise it would turn a missing receipt
        into a sandbox crash."""
        assert sandbox._warm_failure_for({}, "kir.design_check") is None
        assert sandbox._warm_failure_for(
            {"isolation": {"warmed": "failed (TypeError: x)"}},
            "kir.design_check") is None

    def test_the_ratchet_can_actually_fail(self):
        """FAIL control. A label not in the list must yield `None` —
        otherwise the reader answers "failure" for anything at all,
        and all the assertions above are vacuous."""
        state = {"isolation": {"warmed": ["kir.preview"], "warmed_libs": []}}
        assert sandbox._warm_failure_for(state, "kir.design_check") is None, (
            "читатель нашёл провал там, где прогрев отчитался успехом — "
            "значит он не различает свои ответы")

    def test_the_refusal_actually_asks_the_reader(self):
        """🔴 THE WIRING. The reader must actually BE CALLED, not
        merely exist.

        Bought by a FAIL control on 01.09: removing the ENTIRE call to
        `_warm_failure_for` from the refusal-translation point left
        this file GREEN (12 passed) — the five assertions above
        checked the FUNCTION and not one of them checked that the
        refusal actually calls it. Exactly the form this file is
        written against: a capability is built and connected to
        nothing.

        🔴 THIS GUARD'S LIMIT IS NAMED, NOT LEFT UNSAID. It reads the
        SOURCE, not behavior, and here is why it cannot be otherwise:
        the sandbox child is spawned by `fork+exec`
        (`python -c "import kir.sandbox as _s; _s._child_main()"`),
        that is, by a fresh interpreter, and swapping the warm-up
        table in the parent never reaches it. Staging a real warm-up
        failure through the actual door is only possible via the
        ENVIRONMENT (the package unavailable to the child) — and such
        a test would be about the machine, not about the code.

        The parsing is done via AST and looks for the function BY
        NAME, not by line number: a source-reading test tied to line
        numbers parses the neighboring function after the very next
        edit above it in the file.
        """
        with open(sandbox.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        target = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "fail_from_exception"):
                target = node
                break
        assert target is not None, (
            "функции `fail_from_exception` в sandbox.py нет — либо её "
            "переименовали, либо разбор промахнулся мимо файла. Обнови этот "
            "сторож вместе с переименованием, а не глуши его")

        calls = [n for n in ast.walk(target)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "_warm_failure_for"]
        assert calls, (
            "точка перевода отказа не зовёт `_warm_failure_for` — значит "
            "провал прогрева снова выйдет наружу как «импорт запрещён» с "
            "виной на авторе за строку, которой автор не писал (E-17/E-18)")

        blames = [c.value.value for c in ast.walk(target)
                  if isinstance(c, ast.keyword) and c.arg == "blame"
                  and isinstance(c.value, ast.Constant)]
        assert "sandbox" in blames, (
            "ни один отказ этой точки не снимает вину с автора; провал "
            "прогрева — несостоявшаяся способность ПЕСОЧНИЦЫ, а не ошибка "
            f"скрипта. Найдено: {blames}")


if __name__ == "__main__":
    unittest.main()
