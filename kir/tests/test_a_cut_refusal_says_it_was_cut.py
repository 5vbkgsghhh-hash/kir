"""A CUT REFUSAL MUST SAY IT WAS CUT. AND CUT BY RELEVANCE.

WHAT THIS WAS BOUGHT BY, 2026-08-26, a live run an hour after the fix.

Commit `2350024d` taught a curtain-wall refusal to name the grid and list
the OCCUPIED coordinates with their distance to the requested point — "a
distance of 0 mm on one of those listed is the cause". Gates 6/6 green, the
golden updated, the emission test green. The service was restarted, a live
attempt at an occupied coordinate, and here is what ARRIVED at the reader,
in full, length EXACTLY 300 characters::

    AddGridLine returned null — the line was not created. Requested:
    direction u, point (5500, -60000, 2000) mm. this grid is HORIZONTAL:
    the line runs along the host at a constant HEIGHT, and what needs to
    move is the HEIGHT — the point's third coordinate; there are already 4
    lines on this grid: 2140320 (height 1000 mm, distance to the requested
    point 1000 mm), 2

Cut off in the middle of the second id. Neither the line with the 0 mm
distance nor the next move — i.e. EVERYTHING the fix was made for. The fix
nonetheless looked done.

THERE WERE TWO DEFECTS, IN DIFFERENT FILES, AND ONE HID THE OTHER.

* `serving.py` cut the `detail` of every runtime refusal at 300 characters
  SILENTLY: the reader could not tell a cut-off phrase from a whole one.
  The idiom of honest truncation lived in THIS SAME FILE, on
  `witness_note` — a runtime refusal simply was not given it.
* `authoring.py` printed ALL of a grid's lines in a row, in arrival order.
  On a straight wall there were 4; on a real facade, twenty, and raising
  the ceiling would have traded a silent cut for a loud expense (this same
  day a refusal carrying 18 KB for no reason was being fixed — `6d09726b`).

WHY THE LIST'S ORDER IS LOAD-BEARING. The cause of the refusal is the line
with a 0 mm distance. In arrival order (by ElementId) it sits wherever it
lands and drops out of what is shown AT RANDOM. Sorted by distance, it
comes first and survives any truncation. This is the same idiom as
`_nearest`/`_shown_of` in `ground.py`: cut by RELEVANCE, not by order, and
NAME the remainder.

🔴 WHY THE TEST READS BEHAVIOUR AND THE EMITTED TEXT, NOT THE SOURCE BY
LINE NUMBER. In this tree a source-reading test has already lied: a patch
shifted the line numbers, and it parsed a DIFFERENT function.
"""
from __future__ import annotations

import pytest

from kir import authoring
from kir import ground as ground_mod
from kir import serving
from kir.compiler import _parse_and_check
from kir.tests.fixtures import GROUND_SNAPSHOT

VER = "2024"
OID = "ZQW"          # rare on purpose: see the argument in the curtain-wall neighbour
MARK = "…[+"         # truncation marker, shared by both ceilings


# ─────────────────────────────────────────────────────────────────────────
# THE KNIFE. It must speak about itself.
# ─────────────────────────────────────────────────────────────────────────

def _runtime(message: str) -> dict:
    """Exactly the input that arrives from the bridge for an emitter refusal."""
    return serving._translate_runtime({
        "error": "stale_or_failed",
        "layer": {"message": message, "op_id": OID},
    })


def test_длинный_отказ_НАЗЫВАЕТ_свой_остаток():
    """MAIN. On the old code there is no tail at all — the phrase tears off silently."""
        # 2000 characters — twice our worst authored refusal
    длинный = "щ" * 2000
    detail = _runtime(длинный)["detail"]
    assert MARK in detail, (
        "обрезка молчит о себе — вернулся дефект 26.08: читатель не может "
        "отличить оборванную фразу от полной")
    assert detail.endswith("знаков]")


def test_остаток_назван_ВЕРНО_а_не_приблизительно():
    """The number in the tail must agree with what was actually cut off.

    A tail that lies with its number is worse than a missing one: it looks like a measurement.
    """
    длинный = "щ" * 2000
    detail = _runtime(длинный)["detail"]
    оставлено, _, хвост = detail.partition(MARK)
    отрезано = int(хвост.split(" ")[0])
    assert len(оставлено) + отрезано == 2000


def test_потолок_соблюдён_ВМЕСТЕ_с_хвостом():
    """The tail is counted INSIDE the ceiling, not on top of it.

    Otherwise truncation would breach the very limit it exists for.
    """
    detail = _runtime("щ" * 5000)["detail"]
    assert len(detail) <= serving._RUNTIME_DETAIL_CAP


def test_КОНТРОЛЬ_PASS_короткий_отказ_без_всякого_хвоста():
    """Without this the check would be green by construction — crediting a tail to everyone."""
    коротко = "AddGridLine вернул null — линия не создана"
    detail = _runtime(коротко)["detail"]
    assert detail == коротко
    assert MARK not in detail


def test_потолок_ВЫШЕ_худшего_авторского_отказа_витража():
    """The ceiling's number must be derived, not a round one.

    Arithmetic of the worst case (a vertical grid, it is wider than a
    horizontal one): the fixed part 552 + 6 lines of 77 + 5 separators = 1024.
    """
    assert serving._RUNTIME_DETAIL_CAP >= 552 + 6 * 77 + 5 * 2


def test_ДВА_ПОТОЛКА_но_ОДИН_нож():
    """The ceilings are about DIFFERENT things, the algorithm is one. A copy would be a named defect."""
    assert serving._RUNTIME_DETAIL_CAP != serving._NOTE_CAP
    короткое = "оси: геометрия+"
    assert serving._cut_and_say(короткое, 300) == короткое
    assert MARK in serving._cut_and_say("щ" * 500, 300)


def test_строка_осей_свидетеля_режется_ТЕМ_ЖЕ_ножом():
    """PASS control for carrying the idiom over: `witness_note` did not lose truncation."""
    note = serving.witness_note({
        "geometry_ok": True, "semantic_ok": True, "topology_ok": True,
        "named_absences": {("оп%03d" % i): [("к" * 40, "x")]
                           for i in range(40)},
    })
    assert len(note) <= serving._NOTE_CAP


# ─────────────────────────────────────────────────────────────────────────
# THE LIST. It must be bounded and name the remainder.
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cs() -> str:
    ops = [
        {"op": "create_curtain_grid_line", "id": OID,
         "host": {"by": "element_id", "value": 8145901},
         "direction": "u", "position_mm": [2000.0, 0.0, 1500.0]},
    ]
    grounded = ground_mod.ground(
        _parse_and_check({"ir_version": "1.0", "ops": ops}), GROUND_SNAPSHOT)
    return authoring.emit_program(grounded, VER)


def test_перечень_СОРТИРУЕТСЯ_по_расстоянию(cs: str):
    """Without sorting, the cause (0 mm) would drop out of what is shown at random."""
    assert "Array.Sort(__goK, __goT)" in cs


def test_перечень_ОГРАНИЧЕН(cs: str):
    """The old code had a bare String.Join over all the lines."""
    assert "__goT.Length < 6 ? __goT.Length : 6" in cs
    assert "String.Join(\", \", __goB)" not in cs, (
        "перечень снова печатает ВСЕ линии — вернулся неограниченный расход")


def test_остаток_перечня_НАЗВАН(cs: str):
    assert "ПОКАЗАНЫ " in cs and " БЛИЖАЙШИХ ИЗ " in cs


def test_число_показанного_БЕРЁТСЯ_ИЗ_ПОКАЗАННОГО_СПИСКА(cs: str):
    """The `_shown_of` idiom: the quantity is read, not declared.

    In this same tree, the caption "SHOWN 12 OF 48" once sat over FIVE lines
    (`f132cb8e`) for exactly this reason — the number was declared separately.
    """
    assert "__goP2.Count.ToString(" in cs


def test_непрочитанное_расстояние_НЕ_ПЕЧАТАЕТСЯ_ЧИСЛОМ(cs: str):
    """`-1 mm` is a value that cannot occur, and it would sort FIRST,
    displacing the real cause."""
    assert "расстояние до запрошенной точки НЕ ПРОЧИТАНО" in cs
    assert "__goD < 0.0 ? Double.MaxValue : __goD" in cs


def test_ВЫРОЖДЕННЫЙ_ВХОД_ноль_линий_на_оси(cs: str):
    """An empty grid is NOT an occupied coordinate, and the text must say exactly that."""
    assert "линий этой оси в сетке НЕТ ни одной" in cs


def test_ВЫРОЖДЕННЫЙ_ВХОД_линии_есть_но_ни_одна_не_читается(cs: str):
    """Otherwise it would print "линий этой оси уже 0: " — directly against what was seen."""
    assert "но НИ ОДНА не перечитывается" in cs
