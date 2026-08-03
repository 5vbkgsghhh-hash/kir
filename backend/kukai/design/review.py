"""The end-of-turn review: the checklist has to be closed before "готово" counts.

The self-check already refuses to let a writing turn end on a claim — it hands
back a screenshot and makes the model look. Looking catches shape. It does not
catch a column standing off its slab, a frame that ignores the envelope's taper,
or a building that is all columns and no doors, because those are relationships
between elements and a picture shows one composition at a time.

So the same gate also runs the checklist. It is deliberately the SAME mechanism
that took a dojo tower from 179 elements to 10 134 on 2026-07-27/28: state the
shortfall in plain sentences, hand it back, and do not accept the claim while
the list is non-empty. Nothing here judges taste — every finding is a number
about two elements that do not agree.

The programs come from the turn itself: `record()` is called by the revit_ir
handler for each program the compiler accepted, so the review sees exactly what
was built and nothing else. State is per-turn via ContextVar, so concurrent
turns on different devices never share a building.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

from kukai.design import coherence, parti

#: Programs the current turn committed. A list per turn, never global.
_programs: ContextVar[list | None] = ContextVar("kir_review_programs", default=None)

#: How many times one turn may be sent back over the checklist. The screenshot
#: self-check has its own budget; this one is separate and small, because each
#: round costs a full model call and a shortfall that survives three attempts is
#: usually a limit of the language, not of the effort.
MAX_REVIEWS = int(os.getenv("KUKAI_MODEL_REVIEW_ROUNDS", "3"))


def enabled() -> bool:
    return os.getenv("KUKAI_MODEL_REVIEW", "1") != "0"


def reset() -> None:
    _programs.set([])


def record(program: Any) -> None:
    """Called for every program the compiler accepted this turn."""
    if not enabled() or not isinstance(program, dict):
        return
    cur = _programs.get()
    if cur is None:
        cur = []
        _programs.set(cur)
    cur.append(program)


def built_anything() -> bool:
    return bool(_programs.get())


def findings() -> list[str]:
    """Plain sentences naming what does not hold together. Empty means the
    checklist is closed for everything this can see — which is not the same as
    the building being good, and the wording never claims otherwise."""
    programs = _programs.get() or []
    if not enabled() or not programs:
        return []
    try:
        # The skeleton is not asked for separately — it is READ OUT of the
        # `stack` the turn already wrote. So the building is checked against
        # its own declaration, which a prism cannot satisfy: comparing frame
        # taper to envelope taper is true of a box, comparing both to the
        # declared form is not.
        skeleton = parti.from_programs(programs)
        report = coherence.full_check(coherence.flatten(programs), skeleton)
    except Exception:  # noqa: BLE001 — a review must never break a turn
        return []
    return coherence.gaps(report)


#: What the model is told when the checklist is not closed. Imperative on
#: purpose: the earlier phrasing ("проверь, всё ли верно") was answered with
#: "да, всё верно" four turns running.
PROMPT = (
    "Работа НЕ закончена — проверка связности модели нашла нарушения:\n— "
    "{gaps}\n\n"
    "Это не замечания на будущее, а несобранное здание: элемент вне своей "
    "плиты ничего не несёт, балка без опор — это линия, а каркас с другим "
    "сужением, чем оболочка, — второе здание внутри первого.\n"
    "Исправляй инструментами прямо сейчас, по одному пункту, и не объявляй "
    "готовность, пока список не опустеет. Если пункт закрыть нечем — скажи "
    "прямо, каким средством его не выразить, и не выдавай это за готовность."
)


def message(gaps: list[str]) -> str:
    return PROMPT.format(gaps="\n— ".join(gaps))
