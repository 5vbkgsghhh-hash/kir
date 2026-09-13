"""A SKIP THAT NEVER LIFTS IS NOT A GATE, IT'S AN OFF SWITCH.

🔴 WHY THIS FILE EXISTS (04.09.2026). In
`checker/tests/test_the_host_may_name_what_our_lexicon_cannot.py` a coverage
section was gated by the condition

    if os.environ.get("KUKAI_CHECKER_V2", "0") != "1":
        pytest.skip("раздел покрытия существует только под checker v2")

and this is TWO misses in one line.

  * The value has TWO names: the new `KIR_CHECKER_V2` and the old
    `KUKAI_CHECKER_V2` (`kir/env.py`, the `RENAMED` table). Only the old one
    was being read — an operator who turned on v2 using the NEW name got a
    skip even with the lever on.
  * The lever's default became "on" on 01.09.2026
    (`flags.checker_v2_enabled` returns `env.get("KIR_CHECKER_V2", "1") ==
    "1"`), while here the default stayed `"0"`. So on an EMPTY environment —
    that is, on any run without hand-set variables — the section was skipped
    ALWAYS.

The number taken by execution: `pytest <that file> -q` gave `10 passed, 1
skipped` before the fix and `11 passed` after, under the same empty
environment.

WHAT IS GUARDED HERE, AND WHY A PROPERTY, NOT A LITERAL. A guard looking for
the string `KUKAI_CHECKER_V2` would have caught yesterday's case and missed
tomorrow's: the `RENAMED` table has 65 names today, and any of them in the
same position produces the same lie. What is asked is a PROPERTY: a decision
to SKIP made by DIRECTLY reading the old name, instead of asking the product.
"""
from __future__ import annotations

import ast
from pathlib import Path

from kir import env

_ПАКЕТ = Path(__file__).resolve().parents[1]

#: Old names — from the product's table, not from memory. The list grows
#: together with `RENAMED`, and the guard cannot fall behind it by
#: construction.
_ПРЕЖНИЕ = frozenset(env.RENAMED.values())


def _пропуски_по_прежнему_имени(текст: str) -> list[tuple[int, str]]:
    """Places where the decision to SKIP is made by directly reading the old
    name.

    The distinction is load-bearing: `os.environ.setdefault("KUKAI_CHECKER_V2",
    "1")` in a file's header is SETTING the environment, which is legal, and
    there are many such places in the tree. Only a READ standing inside a
    condition whose body skips the test is caught.
    """
    из: list[tuple[int, str]] = []
    try:
        дерево = ast.parse(текст)
    except SyntaxError:
        return из
    for узел in ast.walk(дерево):
        if not isinstance(узел, ast.If):
            continue
        пропускает = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("skip", "skipTest")
            for ветка in узел.body for n in ast.walk(ветка))
        if not пропускает:
            continue
        for n in ast.walk(узел.test):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get"
                    and isinstance(n.func.value, ast.Attribute)
                    and n.func.value.attr == "environ"
                    and n.args
                    and isinstance(n.args[0], ast.Constant)
                    and n.args[0].value in _ПРЕЖНИЕ):
                из.append((n.lineno, n.args[0].value))
    return из


def _тестовые_файлы() -> list[Path]:
    return [p for p in sorted(_ПАКЕТ.rglob("*.py"))
            if "__pycache__" not in p.parts
            and ("tests" in p.parts or p.name.startswith("test_"))]


def test_no_test_decides_to_skip_by_reading_a_legacy_name():
    """Measured on 04.09: there was ONE such place, now there are ZERO."""
    # 🔴 THE DENOMINATOR IS DECLARED (04.09.2026). "Zero offenders" is not a
    # fact about the tree until it is said HOW MANY files were read: a
    # traversal that lost its root hands back the same zero. The day's
    # measurement: 694 test files; a floor with margin for deletions, but a
    # collapsed traversal turns red. Guarded by
    # `kir/instruments/walk_denominator.py`.
    ФАЙЛОВ_НЕ_МЕНЬШЕ = 650
    файлы = _тестовые_файлы()
    assert len(файлы) >= ФАЙЛОВ_НЕ_МЕНЬШЕ, (
        f"обход прочёл {len(файлы)} тестовых файлов при поле "
        f"{ФАЙЛОВ_НЕ_МЕНЬШЕ} — предмет потерян")
    виновные = [
        f"{p.relative_to(_ПАКЕТ.parent)}:{строка} читает {имя}"
        for p in файлы
        for строка, имя in _пропуски_по_прежнему_имени(
            p.read_text(encoding="utf-8", errors="replace"))]
    assert not виновные, (
        "пропуск решается прямым чтением ПРЕЖНЕГО имени: заданное НОВОЕ имя "
        "такой тест не увидит, и умолчание у него своё, а не продуктовое — "
        "спрашивать надо `kir.env.get` или `flags.checker_v2_enabled()`:\n"
        + "\n".join(виновные))


def test_the_scanner_can_say_yes(tmp_path):
    """🔴 FAIL CONTROL: a guard that always answers "no" guards zero.

    The sample is a line taken VERBATIM, one that stood in the tree before
    04.09.2026. If the guard does not find it, the green of the test above
    means nothing.
    """
    было = (
        "import os\n"
        "import pytest\n"
        "def test_x():\n"
        '    if os.environ.get("KUKAI_CHECKER_V2", "0") != "1":\n'
        '        pytest.skip("только под checker v2")\n'
        "    assert True\n")
    найдено = _пропуски_по_прежнему_имени(было)
    assert найдено == [(4, "KUKAI_CHECKER_V2")], найдено


def test_the_scanner_does_not_cry_over_setting_the_environment():
    """🔴 A CONTROL IN THE OTHER DIRECTION: setting the environment is not a
    defect.

    `os.environ.setdefault("KUKAI_CHECKER_V2", "1")` sits in the headers of a
    good dozen files across the tree and is legal: it TURNS ON the lever, it
    does not decide a test's fate by it. A guard that cannot tell reading
    from writing apart would turn red on all of them and get switched off by
    the second day.
    """
    законное = (
        "import os\n"
        'os.environ.setdefault("KUKAI_CHECKER_V2", "1")\n'
        "import pytest\n"
        "def test_x():\n"
        '    if os.environ.get("KIR_CHECKER_V2") != "1":\n'
        '        pytest.skip("новое имя читать можно")\n'
    )
    assert _пропуски_по_прежнему_имени(законное) == []


def test_the_coverage_section_runs_on_an_empty_environment():
    """What it's all for: on an empty environment the lever is ON, so the
    section executes.

    What is asked is the product, not memory: the default lives in
    `flags.checker_v2_enabled`, and on the day the owner flips it back to
    "off," this test must say so, not survive the change silently.
    """
    import os

    from kir.checker.flags import checker_v2_enabled

    названо = [и for и in ("KIR_CHECKER_V2", "KUKAI_CHECKER_V2")
               if и in os.environ]
    if названо:
        # The run's environment set the lever explicitly — there is nothing to assert about the default.
        assert checker_v2_enabled() == (env.get("KIR_CHECKER_V2") == "1")
        return
    assert checker_v2_enabled() is True, (
        "умолчание рычага выключено; тогда раздел покрытия у хозяина и у "
        "чужого человека пропускается, и это надо объявить, а не обнаружить")
