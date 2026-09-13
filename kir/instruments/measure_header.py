"""MEASUREMENT HEADER — an instrument must NAME EXACTLY WHAT IT READ.

🔴 WHAT THIS MODULE COST, 2026-08-18. In a single day there were **ten**
retractions of one's own conclusions. Four of them were of one kind, and the
kind is this: **the instrument was working correctly and honestly answered A
DIFFERENT QUESTION**, and the reader took the answer for the one they had asked.

```
room params instead of doc.rooms              -> "names not extracted"   (false: 2442 of 2442 present)
live_op_rates tail instead of the right table  -> "1 op of 71 proven"     (true: 10)
head -20 on an 84-line file                    -> "no cancellation mark"  (there was one, at line 56)
RAW model instead of the DERIVED one           -> "0 exterior doors"      (true: 257)
```

AND EXACTLY ONCE THIS SAVED THE DAY. `tools/live_op_rates.py` prints above its
second table "RAW, PROGRAM-LEVEL — NOT AN OPERATION FREQUENCY." Only because of
that was the table swap caught. One instrument out of sixty-five turned out to
be talkative — and one time out of four the mistake did not make it into the
report to the owner.

WHY NOT DOCUMENTATION. The `L0JSONLReader.metadata()` trap is written into the
root `CLAUDE.md` VERBATIM, in the "CALL-SHAPE TRAPS" list, with its own
example — and on 08-18 THREE people fell into it in one day, including someone
who had read that list at the start of the session. A document is read once at
the start, and the mistake is made four hours later, thinking about something
else. **Which means the carrier's name must be printed AT THE MOMENT OF
MEASUREMENT, next to the number, not sit in a file that was read that morning.**

WHAT THE HEADER MUST CARRY, and each field was paid for by a separate blunder:

* `source`  — WHAT was read. Without it the number is not reproducible (form
              26: a number without a tree and without a call is not a number);
* `read/of` — HOW MANY were read out of how many. An unstated truncation
              understates silently;
* `window`  — WHICH WINDOW. A journal outlives a run; a match inside it is a
              fact about the JOURNAL, not about what is happening now (form 28);
* `blind`   — WHAT THIS INSTRUMENT DOES NOT SEE. The most expensive field: "the
              instrument refused" and "I did not check" are different facts,
              and the second reads as "it's clean there";
* `refusal` — REFUSAL FIRST AND LOUD. "Did not look" and "empty" must look
              different (§18.2, the law of the receipt).

The pattern is not invented out of thin air: `live_op_rates` already prints
this way (corpus, time, a gap warning), and so does `created_audit` (registry,
refusal, window, "whether the element is alive is not said here"). This module
does not replace them; it makes their shape COMMON and checkable by a test.

    from kir.instruments.measure_header import measure_header
    print(measure_header(
        source=path, read=len(rows), of=total,
        window=(first_ts, last_ts),
        blind=("does not see elements of linked files",),
        refusal=why))
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

#: A separator rule. The header must be VISIBLE to the eye in the output
#: stream, or it gets scrolled past just like the canon does.
_RULE = "─" * 78


def measure_header(
    *,
    source: Any,
    read: int | None = None,
    of: int | None = None,
    window: Sequence[Any] | None = None,
    blind: Iterable[str] = (),
    refusal: str = "",
    note: str = "",
) -> str:
    """The header text. RETURNS it rather than printing it, so it can be pinned in.

    `read`/`of`: read out of how many. If `of` is greater than `read`, the
    difference is named out loud: a truncation the instrument stayed silent
    about is an understatement indistinguishable from the fact itself.

    `blind` — the closed list of THIS instrument's blind spots. An empty list
    is allowed and means "the author did not name any", not "there are none";
    it is written that way so the emptiness does not read as a guarantee.
    """
    lines = [_RULE]
    lines.append(f"ПРОЧИТАНО: {source}")

    if refusal:
        # THE REFUSAL RANKS ABOVE THE NUMBERS. The table beneath it describes
        # what could be read, not what there is.
        lines.append(f"🔴 ОТКАЗ ЧТЕНИЯ: {refusal}")

    if read is not None:
        if of is not None and of != read:
            lines.append(
                f"записей:   {read} из {of}"
                f"   🔴 НЕ ПРОЧИТАНО {of - read} — числа ниже считаны по "
                f"прочитанному, а не по всему")
        else:
            lines.append(f"записей:   {read}"
                         + ("" if of is None else f" из {of}"))

    if window:
        first, last = (list(window) + [None, None])[:2]
        lines.append(f"окно:      {first} … {last}")

    blind_list = [b for b in blind if b]
    if blind_list:
        lines.append("ЧЕГО ЭТОТ ПРИБОР НЕ ВИДИТ:")
        lines.extend(f"   · {b}" for b in blind_list)
    else:
        lines.append("ЧЕГО НЕ ВИДИТ: автор не назвал — это НЕ значит «видит всё»")

    if note:
        lines.append(note)
    lines.append(_RULE)
    return "\n".join(lines)


__all__ = ["measure_header"]
