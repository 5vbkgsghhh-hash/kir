"""THE BUILDING THAT THE COURSE SHOWS MUST BUILD. AND THE JUDGE MUST REFUSE
WITH A TYPE, NOT CRASH.

The file is a CONSEQUENCE of two product fixes on 04.09.2026 in
`kir/course`. Both close the same class: a capability that a RUN never once
reached is silently wrong, and the text next to it explains the omission
as lawful.

───────────────────────────────────────────────────────────────── 1. THE PROGRAM

`course.lessons.PLAN_DEMO_OPS` is the program the course uses to show the
plan, and the first thing a stranger reads. A measurement before the fix,
`compile_program({"ops": list(PLAN_DEMO_OPS)}, revit_version="2026",
snapshot=None)`:

    BEFORE   ok=False, 2 diagnostics
             KIR-P003  unknown field 'point_mm' on create_room
             KIR-T001  xy is a point [x,y] mm
    and then, once the slot is fixed:
             KIR-G103  create_door.symbol {"by": "default"} requires a snapshot
    AFTER    ok=True, 0 diagnostics, C# 18,507 characters on ALL six versions

The program only ever went through `preview` — the plan reads what is
declared and tolerates an extra field — and never once reached the
compiler. The course held a building that cannot be built.

🔴 AND THE TYPO BLINDED THE LESSON ITSELF, not just the compiler. With
`point_mm`, the room was dropped from the plan with reason `no_geometry`,
and the lesson's text explained this omission AS LAWFUL: "a room has no
geometry before it is built… both omissions are legitimate." With the
`xy` slot, the census became 5/4 instead of 5/3, exactly ONE legitimate
omission remained, and the room landed on the sheet as a point. The
observation had been tailored to fit the prose, because there had been no
run.

That is why what compiles here is NOT ONLY this constant: the course
programs are found by walking the package itself. A hand-written list would
fall behind on the very first new program and stay silent about it — and
this shape of defect is repeatable by construction.

──────────────────────────────────────────────────────────────────── 2. THE JUDGE

`course.design_check()` on a program the typechecker rejects came out as a
RAW STACK TRACE. Measurement of 04.09.2026, nine shapes through this door —
FIVE failed:

    create_room(xy_mm=…)          KeyError: 'xy'
    create_room(point_mm=…)       KeyError: 'xy'     (that very lesson program)
    create_room without xy        KeyError: 'xy'
    create_level without elev_mm  KeyError: 'elev_mm'
    an op that is not a dict      ValueError: dictionary update sequence…

`KeyError: 'xy'` is the worst kind of refusal this tree can produce: it
names a slot name the author never wrote, and reads as "you wrote xy
wrong." The correct name, meanwhile, sits in the registry, and the
typechecker prints it together with the op's whole contract and the next
move.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import pkgutil
from typing import Any

import pytest

import kir.course as course
from kir.compiler import compile_program
from kir.course.lessons import PLAN_DEMO_OPS
from kir.revit_version import supported


def _programs_published_by_the_course() -> list[tuple[str, tuple[dict, ...]]]:
    """All COURSE programs, found by walking the package, not a list here.

    A program is a module-level name whose value is a sequence of dicts,
    and EVERY one carries a string `op`. The rule is "every", not "first":
    a mixture is not a program, and declaring it one would mean judging the
    wrong subject.
    """
    найдено: list[tuple[str, tuple[dict, ...]]] = []
    for info in pkgutil.iter_modules(course.__path__):
        модуль = importlib.import_module(f"{course.__name__}.{info.name}")
        for имя in dir(модуль):
            if имя.startswith("__"):
                continue
            значение: Any = getattr(модуль, имя, None)
            if not isinstance(значение, (tuple, list)) or not значение:
                continue
            if all(isinstance(op, dict) and isinstance(op.get("op"), str)
                   for op in значение):
                найдено.append((f"{info.name}.{имя}", tuple(значение)))
    return найдено


def test_the_course_publishes_at_least_the_plan_program() -> None:
    """THE DENOMINATOR IS NAMED. A walk that found ZERO programs is green
    for free — and that is exactly how this instrument would break
    silently on a rename."""
    имена = [имя for имя, _ in _programs_published_by_the_course()]
    assert "lessons.PLAN_DEMO_OPS" in имена, имена


@pytest.mark.parametrize("revit_version", supported())
def test_every_program_the_course_publishes_compiles_without_a_snapshot(
        revit_version: str) -> None:
    """NO SNAPSHOT is not strictness, it is a condition: a snapshot exists
    only with a live Revit, and the course is read where there is none. A
    slot that requires a snapshot legitimately refuses with `KIR-G103`, and
    so it has no place in the shown program."""
    for имя, ops in _programs_published_by_the_course():
        out = compile_program({"ops": list(ops)},
                              revit_version=revit_version, snapshot=None)
        assert out.ok, (
            f"{имя} не компилируется на {revit_version}: "
            + "; ".join(f"{d.code} {d.message_ru}" for d in out.diagnostics))
        assert out.csharp, f"{имя}: ok=True, а C# пуст"


def test_the_plan_lesson_still_counts_its_numbers_from_a_live_run() -> None:
    """The lesson's numbers are the OUTPUT of a run over the same constant,
    not text sitting next to it.

    The instrument looks at the ONE legitimate omission: before the fix,
    two were printed, and the second was held up by a typo. The numbers are
    taken from the census, not written here: a literal here would become a
    second carrier and diverge silently.
    """
    from kir.course.lessons import _plan_block
    from kir.preview import build_program_preview

    c = build_program_preview(list(PLAN_DEMO_OPS)).census
    текст = _plan_block()

    assert c.considered == c.drawn + c.omitted_total, "перепись не замкнулась"
    assert c.omitted_total == 1, "законный пропуск ровно один — уровень"
    assert f"рассмотрено {c.considered}, нарисовано {c.drawn}" in текст
    assert f"не нарисовано {c.omitted_total}" in текст
    # THE PROSE IS CHECKED AGAINST THE NUMBER. "Both omissions are
    # legitimate" stood here while there were two omissions due to a typo;
    # a phrase surviving the fix unchanged would have lied.
    assert "Оба пропуска" not in текст, текст


# ──────────────────────────────────────────────────────────────── THE JUDGE

#: Shapes on which the judge crashed with a raw stack trace. Each is a
#: MEASUREMENT from 04.09.2026, not invented: the first three are exactly
#: what a slot-name miss turns into.
_УРОВЕНЬ = {"op": "create_level", "id": "lvl", "name": "Этаж 1", "elev_mm": 0}
_СТЕНА = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
          "height_mm": 3000, "level": {"by": "ref", "value": "lvl"}}

СЛОМАННЫЕ = {
    "xy_mm вместо xy": [_УРОВЕНЬ, _СТЕНА, {
        "op": "create_room", "id": "r1", "xy_mm": [3000, 2000],
        "level": {"by": "ref", "value": "lvl"}}],
    "point_mm вместо xy": [_УРОВЕНЬ, _СТЕНА, {
        "op": "create_room", "id": "r1", "point_mm": [3000, 2000],
        "level": {"by": "ref", "value": "lvl"}}],
    "xy не задан вовсе": [_УРОВЕНЬ, _СТЕНА, {
        "op": "create_room", "id": "r1",
        "level": {"by": "ref", "value": "lvl"}}],
    "уровень без elev_mm": [{"op": "create_level", "id": "lvl", "name": "Э"}],
    "оп не словарь": [_УРОВЕНЬ, "не словарь"],
}


def _напечатанное(ops) -> str:
    буфер = io.StringIO()
    with contextlib.redirect_stdout(буфер):
        course.design_check(ops)
    return буфер.getvalue()


@pytest.mark.parametrize("имя", sorted(СЛОМАННЫЕ))
def test_the_judge_refuses_in_words_instead_of_raising(имя: str) -> None:
    """Not a single raw exception escapes — and the refusal names the next
    move."""
    текст = _напечатанное(СЛОМАННЫЕ[имя])
    assert "ОТКАЗ" in текст or "НЕ ВЫНЕСЕН" in текст, текст
    assert "СЛЕДУЮЩИЙ ХОД" in текст, текст


@pytest.mark.parametrize("имя", ["xy_mm вместо xy", "point_mm вместо xy",
                                 "xy не задан вовсе", "уровень без elev_mm"])
def test_the_refusal_carries_the_registrys_own_code(имя: str) -> None:
    """THE CODE TRAVELS WITH THE TEXT, and the code is the REGISTRY's, not
    one invented by the door.

    An invented code is worse than none: it looks like a code. It is
    checked against the dispatcher's closed list, not against a "KIR-…"
    mask.
    """
    from kir.diag import spec_of

    текст = _напечатанное(СЛОМАННЫЕ[имя])
    коды = {слово.strip(" (,.:") for слово in текст.split()
            if слово.startswith("KIR-")}
    assert коды, текст
    for код in коды:
        assert spec_of(код) is not None, f"{код} нет у распорядителя: {текст}"
    # THE SLOT NAME FROM THE REGISTRY IS NAMED. This is exactly why the fix
    # was made: `KeyError: 'xy'` named a slot the author never wrote, and
    # did not name where to get the correct one.
    assert "create_room" in текст or "create_level" in текст, текст


def test_a_program_the_typechecker_accepts_still_gets_its_verdict() -> None:
    """A CONTROL IN THE OTHER DIRECTION. A door that now refuses EVERYONE
    would be "fixed" and useless; the verdict must still be rendered exactly
    as before."""
    здоровая = [_УРОВЕНЬ, _СТЕНА, {
        "op": "create_room", "id": "r1", "xy": [3000, 2000],
        "name": "Гостиная", "level": {"by": "ref", "value": "lvl"}}]
    текст = _напечатанное(здоровая)
    assert "ВЕРДИКТ О ЗАМЫСЛЕ" in текст, текст
    assert "НЕ ВЫНЕСЕН" not in текст, текст


def test_a_judge_that_falls_on_a_valid_program_blames_itself() -> None:
    """THE TYPECHECKER STAYS SILENT — THE JUDGE IS AT FAULT, AND THAT IS
    WHAT IS WRITTEN.

    This is exactly the class recorded in the tree's memory as "the
    instrument is right, but about a different subject": an explainer that,
    just in case, blames the author sends someone off to fix what already
    works.
    """
    текст = course._why_the_judge_stumbled(
        {"ops": [_УРОВЕНЬ, _СТЕНА]}, False, RuntimeError("выдуманный сбой"))
    assert "дефект судьи" in текст, текст
    assert "программу править не надо" in текст, текст


def test_the_refused_call_is_marked_in_the_reading_ledger() -> None:
    """DISTINGUISHABILITY IN STRUCTURE, not only in prose: a printed answer
    and a printed refusal are otherwise indistinguishable by machine, and
    the ledger is not read by an eye.

    🔴 THE LEDGER IS RESET, AND THIS IS NOT HYGIENE. It is global per run
    and capped at `MAX_READS = 64`; alone the file was green, but in a
    combined run with `test_course.py` the ceiling was used up by SOMEONE
    ELSE'S calls, the new line never made it in, and the slice came back
    empty. An instrument without a reset would be measuring the ORDER OF
    THE RUN, not a property of the door — this kind of false red is already
    named in the tree ("the red count is a property of order, not of the
    code").
    """
    course.reset_reads()
    _напечатанное(СЛОМАННЫЕ["xy_mm вместо xy"])
    строки = course.reads_ledger()
    assert строки and строки[-1]["call"] == "design_check", строки
    assert строки[-1].get("refused") is True, строки
