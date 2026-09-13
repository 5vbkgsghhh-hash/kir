"""A SPLIT-LINE REFUSAL MUST NAME THE AXIS AND WHAT OCCUPIES IT.

WHAT THIS COST, 26.08.2026, on live Revit 2026 against curtain wall
2140306 (0,-60000)->(8000,-60000), level «01 Этаж» elevation 0, height
4000.

The curtain wall was the MOST EXPENSIVE operation in the language: the
26.08 marathon — 17 batched attempts over 630 s and 15 single calls over
529 s, the task NOT CLOSED, four lines still never landed. The contract
kept writing «ПРИЧИНА НЕИЗВЕСТНА».

The cause is known. Nine live attempts, and one model explains all nine::

    u (2000,-60000,2000)  SUCCESS  panels 3->4
    u (4000,-60000,2000)  null          <- same z=2000
    u (6000,-60000,2000)  null          <- same z=2000
    v (4000,-60000,2000)  SUCCESS  4->6
    u (2100,-60000,2000)  null          <- same z=2000
    u (4000,-60000,3000)  SUCCESS  6->8   <- z NEW
    u (5000,-60000,2000)  null          <- same z=2000
    u (5000,-60000,1000)  SUCCESS  8->10  <- z NEW
    u (1000,-60000,3500)  SUCCESS 10->12  <- z NEW

`direction="u"` gives a line at a CONSTANT Z, `direction="v"` at a constant
position along the host. The marathon's model was moving X while holding Z
fixed, and every time it was asking for THE SAME horizontal line; Revit
answered with a bare `null`.

THREE PREDICTIONS, made BEFORE the run, all three landed::

    u (7000,-60000,1000)  predicted NULL (z=1000 occupied)  -> null    ✓
    v (4000,-60000,3900)  predicted NULL (x=4000 occupied)  -> null    ✓
    v (7000,-60000,100)   predicted SUCCESS (x=7000 free)   -> SUCCESS ✓

THE LAW THIS VIOLATED, verbatim from `ground.py`: "a refusal that names an
unworkable move is worth more than a refusal that names none." The old
refusal named NONE: «AddGridLine вернул null — линия не создана».

🔴 WHY THE TEST READS THE EMITTED C#, NOT THE SOURCE BY LINE NUMBER.
In this tree the source-reading test already lied once: an edit shifted
the line numbers, and it parsed a DIFFERENT function. Here the subject is
the emitted text itself — exactly what will go to Revit — and a shift in
the Python line numbers does not touch it.

🔴 WHAT THIS TEST DOES NOT PROVE. That the listed coordinates are
CORRECT: only live Revit knows that. It proves that the refusal ASKS THE
MODEL for them and puts them into the text — that is, that the "the
refusal stays silent about the cause" hole is closed.
"""
from __future__ import annotations

import pytest

from kir import authoring
from kir import ground as ground_mod
from kir.compiler import _parse_and_check
from kir.tests.fixtures import GROUND_SNAPSHOT

VER = "2024"
#: The op identifier is DELIBERATELY rare: the slice runs on it, and "GL"
#: would give false hits in other lines. This same caution was paid for
#: below — the first edition of the test searched for the word "boundary"
#: ACROSS THE WHOLE program and was green by construction: the word sat in
#: an unrelated guard's comment.
OID = "ZQX"


def _emit(direction: str = "u") -> str:
    """A program of ONE op: the host is given by id, no need to build a
    wall.

    That way the emission is not mixed with someone else's, and there is
    no need to slice it. The first edition of this test searched for words
    ACROSS THE WHOLE program and was green by construction: "boundary" sat
    in an unrelated guard's comment. The second sliced by lines containing
    `OID` — and tore a multi-line lambda in half.
    """
    ops = [
        {"op": "create_curtain_grid_line", "id": OID,
         "host": {"by": "element_id", "value": 8145901},
         "direction": direction, "position_mm": [2000.0, 0.0, 1500.0]},
    ]
    grounded = ground_mod.ground(
        _parse_and_check({"ir_version": "1.0", "ops": ops}), GROUND_SNAPSHOT)
    return authoring.emit_program(grounded, VER)


@pytest.fixture(scope="module")
def u() -> str:
    return _emit("u")


@pytest.fixture(scope="module")
def v() -> str:
    return _emit("v")


def test_в_программе_НЕТ_чужих_опов(u: str):
    """A guard for the test itself: the only op is ours.

    Should a second one appear alongside it, any check below could turn
    green from its text, not from ours.
    """
    assert u.count("__Refuse(\"%s\"" % OID) >= 3
    assert "_WG" not in u and "create_wall" not in u


def test_отказ_null_больше_не_голый(u: str):
    """The old text was THE ENTIRE cause the author ever received."""
    голый = '__Refuse("%s", "AddGridLine вернул null — линия не создана")' % OID
    assert голый not in u, (
        "отказ по-прежнему не называет ни оси, ни занятого — вернулся дефект, "
        "стоивший марафону 630 с")


def test_ветка_null_спрашивает_линии_этой_оси_у_МОДЕЛИ(u: str):
    """What is occupied must be read from the document, not derived from
    the program.

    Between programs, Revit is the one that changes state; a list computed
    on the Python side would diverge from the model — the named defect of
    this tree.
    """
    assert "GetUGridLineIds" in u and "GetVGridLineIds" in u
    assert "__KirGridOcc(" in u, "перечислителя занятых координат в эмиссии нет"


def test_отказ_называет_ОСЬ_и_что_двигать(u: str, v: str):
    """The author must be told WHICH coordinate to change, not left to guess."""
    for cs in (u, v):
        assert "ГОРИЗОНТАЛЬНА" in cs and "ВЕРТИКАЛЬНА" in cs, "ось не названа"
        assert "ВЫСОТУ" in cs and "ВДОЛЬ носителя" in cs, (
            "не сказано, какую координату двигать")


def test_ось_ЧИТАЕТСЯ_у_модели_а_не_утверждается(u: str):
    """That `u` means horizontal was paid for by ONE run on ONE wall.

    That is not enough for a law covering every host and version, so the
    direction is taken from the `FullCurve` of an existing line. A claim in
    the text unsupported by a read would hand back a guess dressed up as a
    fact.
    """
    assert "FullCurve" in u and "Normalize()" in u
    assert "Math.Abs(__goV.Z)" in u
    # and the coordinate label is picked by the SAME branch: for a
    # vertical line the midpoint height is the same for all of them and
    # distinguishes nothing
    assert "высота " in u and "в плане (" in u


def test_пустое_сообщение_ревита_называет_КРАЙ(u: str):
    """z=0 (exactly the bottom edge) gives an ArgumentException with an
    empty message.

    Measured live on 26.08 on wall 0..4000, point (2000,-60000,0).
    """
    assert "(пустое сообщение Revit)" in u, "ветка пустого сообщения исчезла"
    assert "РОВНО НА ГРАНИЦЕ носителя" in u and "ВНУТРЬ носителя" in u, (
        "пустое сообщение Revit по-прежнему ничего не советует")


def test_пустой_перечень_НЕ_выдаётся_за_причину(u: str):
    """A grid with no lines is a degenerate input, and it must say so
    about itself.

    "There are no lines" and "the line is occupied" are different facts;
    merged into one text, they would send the author to move a point where
    there is nothing to move.
    """
    assert "НЕТ ни одной" in u and "НЕ в занятой координате" in u


def test_КОНТРОЛЬ_PASS_свидетель_и_штамп_на_месте(u: str):
    """Fixing the refusal must not have weakened what was already correct."""
    assert "IsUGridLine" in u
    assert "mullions_on_line" in u
    assert "__gMem" + OID in u and "__gDist" + OID in u


def test_КОНТРОЛЬ_PASS_перечень_зовётся_ТОЛЬКО_в_отказе(u: str):
    """A trip into the model for a listing on the success path is one
    nobody will ever read."""
    assert u.count("__KirGridOcc(__gg_%s" % OID) == 2, (
        "перечислитель зовётся не ровно в двух ветках отказа")


def test_КОНТРОЛЬ_PASS_помощник_объявлен_ОДИН_РАЗ_на_программу():
    """A per-op copy cost +3480 B of C# for every line — measured during
    this fix.

    A façade of twenty lines grew heavier by 70 KB (+26%). The helper
    doesn't depend on the op in any way — it takes the grid, the axis, and
    the point as arguments — so a per-op copy would be a cost with no
    purpose. Here it is pinned down with a number, not an intention: no
    matter how many lines there are, there is one declaration.
    """
    ops = [
        {"op": "create_curtain_grid_line", "id": "%s%d" % (OID, i),
         "host": {"by": "element_id", "value": 8145901},
         "direction": "u", "position_mm": [2000.0, 0.0, 500.0 * i]}
        for i in range(1, 6)
    ]
    grounded = ground_mod.ground(
        _parse_and_check({"ir_version": "1.0", "ops": ops}), GROUND_SNAPSHOT)
    cs = authoring.emit_program(grounded, VER)
    assert cs.count("Func<CurtainGrid, bool, XYZ, string> __KirGridOcc") == 1
    assert cs.count("__KirGridOcc(__gg_") == 10, "две ветки отказа на каждый из пяти опов"
