"""A GREEN RESULT ABOUT A FOREIGN TREE MUST SAY THAT IT IS NOT ABOUT OURS.

🔴 WHY THIS FILE EXISTS (04.09.2026). Two package tests were loading the
HOST's instruments along a path hardcoded as a literal:

    kir/tests/test_stand_does_not_starve_the_author.py   loop_meter
    kir/tests/test_asked_vs_built_is_judged.py           author_loop_baseline

Their green was NOT evidence about `/opt/kir`: there are ZERO definitions of
`RECEIPT_CHARS`, `_receipt_for_author`, and `summarise` in the package — all
of them live in `/opt/kukai-rebuild1/backend/tools`. Remove any
implementation from `/opt/kir` — both files keep turning green. This is
exactly the violation of the KIR↔product boundary that the package guards by
number: not by import, but by PATH.

🔴 WHAT COUNTS AS A CURE, AND THIS IS NOT OUR OWN INVENTION. The canon
distinguishes two kinds of knowledge of a foreign tree
(`test_the_package_does_not_know_the_host`): the ROUTE the code WALKS must
ask the environment; the NARRATIVE stays verbatim. The census
`tools/host_path_census.py` counts the same two kinds and states outright
that a seam assertion about BOTH trees is legal if it DECLARES the host's
configuration. The form already lives in four package files
(`test_plural_operand_authority`, `test_record_ratchet`, `test_kir_transfer`,
`test_clash_in_the_receipt`): the root is taken from `KIR_HOST_ROOT`, and
without it seam assertions are SKIPPED WITH A REASON.

THE NUMBER: the 04.09 census gave 22 files "ONLY a literal, no declaration";
after the fix — 20, and "declare AND carry a literal" grew from 4 to 6.

WHAT THIS FILE DOES NOT DO: it does not fix the remaining 20 and does not
forbid them. It holds the TWO fixed ones in place and asks them about
BEHAVIOR, not appearance — by running with a host root that does not exist.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_КОРЕНЬ = Path(__file__).resolve().parents[2]

#: Seam files brought in line with the declared root on 04.09.2026. The list
#: is CLOSED AND NOT COMPLETE: an empty cell means "not fixed here yet," not
#: "clean here."
_ШОВНЫЕ = (
    "kir/tests/test_stand_does_not_starve_the_author.py",
    "kir/tests/test_asked_vs_built_is_judged.py",
)


def _прогон(файл: str, корень: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", файл, "-q",
         "-p", "no:cacheprovider", "-p", "no:randomly", "-rs"],
        cwd=_КОРЕНЬ, text=True, capture_output=True, timeout=300,
        env={**_среда(), "KIR_HOST_ROOT": str(корень)})


def _среда() -> dict[str, str]:
    import os
    среда = dict(os.environ)
    среда["PYTHONPATH"] = str(_КОРЕНЬ)
    среда.pop("KUKAI_BACKEND_ROOT", None)
    return среда


@pytest.mark.parametrize("файл", _ШОВНЫЕ)
def test_a_seam_test_skips_when_the_host_tree_is_absent(файл, tmp_path):
    """🔴 THE ASSERTION IS CHECKED BY EXECUTION, NOT BY READING THE SOURCE.

    A test that reads its neighbor's text would say "the `KIR_HOST_ROOT` line
    is in place" and stay silent about whether the neighbor actually hears
    it. We ask the OUTCOME: the root is named, there is no tree at it — the
    module must skip itself.

    THE NUMBER BEFORE (measured 04.09 on a copy of HEAD): with the same
    `KIR_HOST_ROOT` pointing at an empty directory, both files gave `4
    passed` and `10 passed` — they were not hearing the variable at all.
    """
    результат = _прогон(файл, tmp_path)
    вывод = результат.stdout + результат.stderr
    # 5 is `NO_TESTS_COLLECTED`, and here it is the DESIRED outcome: the
    # module refused to be collected, meaning no assertion about a foreign
    # tree was either green or red. 0 remains legal for the case where the
    # skip becomes per-test rather than per-module.
    assert результат.returncode in (0, 5), вывод
    assert "skipped" in вывод, (
        f"{файл}: дерева хозяина нет, а тест не пропустился — значит он берёт "
        f"его не по объявленному корню:\n{вывод}")
    assert " passed" not in вывод, (
        f"{файл}: без дерева хозяина что-то всё-таки зеленеет, и этот зелёный "
        f"будет прочитан как улика о KIR:\n{вывод}")
    assert "KIR_HOST_ROOT" in вывод, (
        f"{файл}: пропуск не называет, чем его поднять:\n{вывод}")


@pytest.mark.parametrize("файл", _ШОВНЫЕ)
def test_the_same_seam_test_runs_when_the_host_tree_is_there(файл):
    """🔴 A CONTROL IN THE OTHER DIRECTION: a skip that never lifts is a lie.

    A file that skips itself ALWAYS would pass the assertion above and check
    nothing at all. So the reverse is also asked: with a real host root, the
    assertions EXECUTE. If the host is missing on this machine too, the
    control itself is skipped — with a reason, not silently.
    """
    from kir import env

    корень = Path(env.get("KIR_HOST_ROOT", "/opt/kukai-rebuild1/backend"))
    if not (корень / "tools" / "loop_meter.py").is_file():
        pytest.skip(
            f"дерева хозяина нет и здесь ({корень}); поднять пропуск нечем. "
            f"Назвать корень: KIR_HOST_ROOT")
    результат = _прогон(файл, корень)
    вывод = результат.stdout + результат.stderr
    assert результат.returncode == 0, вывод
    assert " passed" in вывод and "skipped" not in вывод, (
        f"{файл}: корень хозяина назван и дерево на месте, а утверждения не "
        f"исполнились:\n{вывод}")


def test_the_package_carries_no_implementation_of_the_host_stand():
    """The argument "this is someone else's subject" is A NUMBER, not a
    taste, and it is re-checked right here.

    On the day the rig moves into KIR, the assertion will turn red, and
    rightly so: that is when the seam form must come off, and the tests must
    be addressed into the package.
    """
    # The names are DISTINCTIVE, not generic: `def summarise` also exists in
    # our own `decompile/family_recipe.py`, and the guard would turn red on
    # it about a foreign subject — exactly the shape this whole patch is
    # against.
    имена = ("RECEIPT_CHARS", "_receipt_for_author", "author_loop_baseline")
    # 🔴 THE DENOMINATOR IS DECLARED, AND THIS IS NOT CEREMONY (04.09.2026).
    # The assertion "our own count is zero" is, by itself, not a fact about
    # the tree: a traversal that lost its root hands back the same zero and
    # reads as a win. The day's measurement: 300 production files; the floor
    # is set with margin for deleting a dozen, but tight enough that a
    # collapsed traversal (zero-to-a-few-dozen files) turns red. The
    # instrument guarding this is `kir/instruments/walk_denominator.py`, and
    # it was red on this file until the floor was added here.
    ФАЙЛОВ_НЕ_МЕНЬШЕ = 280
    файлы = [
        p for p in sorted((_КОРЕНЬ / "kir").rglob("*.py"))
        if "__pycache__" not in p.parts
        and "tests" not in p.parts
        and not p.name.startswith("test_")]
    assert len(файлы) >= ФАЙЛОВ_НЕ_МЕНЬШЕ, (
        f"обход прочёл {len(файлы)} производственных файлов при поле "
        f"{ФАЙЛОВ_НЕ_МЕНЬШЕ} — предмет потерян, и «своих ноль» ниже было бы "
        f"фактом о потерянном корне, а не о пакете")
    свои = [
        f"{p.relative_to(_КОРЕНЬ)}: {имя}"
        for p in файлы
        for имя in имена
        if имя in p.read_text(encoding="utf-8", errors="replace")]
    assert not свои, (
        "предмет шовных тестов появился в пакете — значит они больше не "
        f"шовные и обязаны адресовать KIR: {свои}")
