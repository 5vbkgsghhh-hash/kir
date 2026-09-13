"""THE LIVE PLAN — a reader of the program journal that draws and sends.

The operator wants to SEE the building come together while the model is
designing it. The value is not in the beauty: a person watching the assembly
believes more than any report. Hence a frame must arrive DURING the work, not
after it.

The module is a READER, and only that. It does not compile, does not ground,
does not write to Revit, and decides nothing about the turn. It can be
switched off, broken, or removed entirely, and the build will not notice —
this is verified by destructive gates, not promised
(`kir/tests/test_live_plan_stream.py`).

FOUR INVARIANTS AND WHERE THEY LIVE IN THE CODE
------------------------------------------------

1. ONE-WAYNESS. There is no path from here into the compiler. The only edge
   into `kir` is the lazy import of `preview` in `_render_frame`, and
   `preview.py` at module scope imports nothing from `kir`. Verified by
   walking imports (`ast`), not by reading with the eye.

2. A VALVE WITHOUT WAITING. `publish()` is a SYNCHRONOUS function with not a
   single point of waiting. Not "we try not to block" but "there is nothing
   to block with": there is no `await` in the body, so the caller cannot be
   delayed by drawing even in theory. A "task per event" (`create_task` per
   frame) was rejected: it means an unbounded number of tasks and holding
   references to programs, i.e. a leak disguised as asynchrony. Instead there
   is ONE bounded worker with a queue.

3. BOUNDEDNESS. A queue with a cap; once it overflows, a frame is DROPPED and
   counted. The rate is limited (WebView2 already bit us with throttling that
   froze the JS ping). If the panel is not attached, drawing does not even
   start: `publish` returns right after the journal write.

   WHY DROPPING A FRAME IS SAFE. What travels in the queue is not a frame but
   an ALARM CLOCK: the program itself is already in the journal, and the
   worker catches up by cursor. A lost alarm clock costs one picture, not one
   program. And the latest state is not lost either: queue full ⇒ worker busy
   ⇒ upon reaching the end of its cycle it re-checks the cursor against the
   head of the journal.

4. HONESTY OF THE SOURCE. `preview` stamps the sheet `Assertion.SELF_REPORTED`,
   the frame carries `stage="planned"`, the summary is called "DECLARED".
   Three labels, none derived from another. Otherwise, a month from now
   someone will say "but I saw it, everything looked fine", and we would get
   acceptance by eyeballing.

WHAT THE STREAM CAN STILL GET IN THE WAY OF — named in the wave report and
here too: drawing runs in Python, i.e. it holds the GIL. It is offloaded to a
thread (`asyncio.to_thread`), so the event loop does not freeze for the whole
render, but contention for the GIL remains, and on a heavy floor it takes a
percentage of time away from the turn. This is a cost, not a defect; its size
has been measured by a long run.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Awaitable, Callable, Mapping, Optional

from kir.live import journal as _journal
from kir.live import showroom as _showroom

logger = logging.getLogger(__name__)

__all__ = (
    "FRAME_SCHEMA",
    "attach",
    "attached",
    "bind_transport",
    "detach",
    "drain",
    "enabled",
    "publish",
    "remember_sections",
    "reset",
    "stats",
)

FRAME_SCHEMA = "kir-plan-frame/1"

_FLAG = "KIR_LIVE_PLAN"


def enabled() -> bool:
    """Switch for the whole stream. Off = behavior from before this wave."""
    # 🔴 THE IMPORT IS LOCAL, AND THAT IS NOT STYLE (28.08.2026). This module
    # is declared CLEAN: the guard `test_live_plan_stream::OneWayTests` keeps
    # its edges into the package empty, so the journal cannot be dragged into
    # the compiler. A module-level `from kir import env`, put in place during
    # the env-name migration, broke that cleanliness — an edge appeared, and
    # the guard rightly turned red.
    from kir import env

    return env.get(_FLAG, "1") != "0"


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    from kir import env          # local — see the argument at `enabled()` above
    try:
        value = int(env.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _queue_max() -> int:
    return _int_env("KIR_LIVE_PLAN_QUEUE", 8, low=1, high=1024)


def _interval_s() -> float:
    """Minimum spacing between sends. Not decoration: WebView2 throttles
    background-window timers, and a frame rate above ~2/s froze the JS ping."""
    return _int_env(
        "KIR_LIVE_PLAN_INTERVAL_MS", 400, low=0, high=60_000) / 1000.0


def _levels_per_frame() -> int:
    """How many floors are drawn per pass. A program touching twenty floors
    has no right to turn one frame into twenty renders."""
    return _int_env("KIR_LIVE_PLAN_LEVELS", 3, low=1, high=64)


def _index_batch() -> int:
    """How many programs are indexed per worker pass. Catching up over four
    hundred programs must break down into bounded chunks."""
    return _int_env("KIR_LIVE_PLAN_INDEX_BATCH", 64, low=1, high=4096)


def _slice_ops_cap() -> int:
    """The cap on operations handed to ONE render. Measured: 2,800 ops of one
    floor = 543 ms per frame."""
    return _int_env("KIR_LIVE_PLAN_SLICE_OPS", 1_500, low=50, high=100_000)


def _send_timeout_s() -> float:
    return _int_env(
        "KIR_LIVE_PLAN_SEND_MS", 5_000, low=100, high=120_000) / 1000.0


# ── outbound channel ────────────────────────────────────────────────────────
# The module only knows "how to send a dict"; the web layer sets the actual
# channel (`bind_transport`). Exactly the same boundary as `llm/turn_progress.py`:
# neither `kir.live` nor `kir` drags FastAPI along.
#
# WHY THE CHANNEL IS ADDRESSED BY DEVICE, NOT BY TURN. `turn_progress` is
# bound by a ContextVar inside `run_turn`, so it is silent outside a turn —
# and a long offline run goes on for an hour without a single chat reply, and
# frames must still get through then. The `ws_registry._device_websockets`
# registry lives independently of turns and is already used by background
# tasks (VOR progress) — we take it.
_Transport = Callable[[str, dict], Awaitable[Any]]
_transport: Optional[_Transport] = None

_STATE_LOCK = threading.Lock()
#: device_id -> how many panels of this device are attached (a person opens
#: KUKI in two Revit windows — both panels wait for frames).
_attached: dict[str, int] = {}

_COUNTERS = {
    "published": 0,          # how many times publish was called
    "journaled": 0,          # how many programs landed in the journal
    "queued": 0,             # how many alarm clocks were queued
    "dropped_frames": 0,     # how many alarm clocks were dropped (queue full)
    "skipped_no_panel": 0,   # no panel — no drawing at all
    "skipped_disabled": 0,
    "renders": 0,
    "render_errors": 0,
    "index_errors": 0,
    "frames_sent": 0,
    "send_errors": 0,
    "worker_errors": 0,
    "showroom_errors": 0,    # frame drawn, but signing the program failed
    "card_errors": 0,        # sheet drawn, but the human card could not be built
    "render_ms_total": 0.0,
}


def bind_transport(transport: Optional[_Transport]) -> None:
    """Set the delivery channel. Called once by the web layer."""
    global _transport
    _transport = transport


def attach(device_id: str) -> None:
    """This device's panel attached."""
    if not device_id:
        return
    with _STATE_LOCK:
        _attached[device_id] = _attached.get(device_id, 0) + 1


def detach(device_id: str) -> None:
    """The panel detached. Zero panels — drawing for the device stops."""
    if not device_id:
        return
    with _STATE_LOCK:
        left = _attached.get(device_id, 0) - 1
        if left > 0:
            _attached[device_id] = left
        else:
            _attached.pop(device_id, None)


def attached(device_id: str) -> bool:
    with _STATE_LOCK:
        return bool(device_id) and _attached.get(device_id, 0) > 0


# ── worker ───────────────────────────────────────────────────────────────────
# Exactly one per event loop. Bound to the loop, not to the process: in tests
# there is one loop per test, and a queue created in someone else's loop
# quietly stops waking up.

_worker_lock = threading.Lock()
_worker_task: Optional[asyncio.Task] = None
_worker_loop: Optional[asyncio.AbstractEventLoop] = None
_queue: Optional[asyncio.Queue] = None
_idle: Optional[asyncio.Event] = None


def _ensure_worker() -> Optional[asyncio.Queue]:
    """Bring the worker up in the CURRENT loop. No loop — no stream, and that
    is not an error: the journal is already written, and there is no one and
    nothing to draw for."""
    global _worker_task, _worker_loop, _queue, _idle
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    with _worker_lock:
        if (_worker_loop is not loop or _queue is None
                or _worker_task is None or _worker_task.done()):
            _worker_loop = loop
            _queue = asyncio.Queue(maxsize=_queue_max())
            _idle = asyncio.Event()
            _idle.set()
            _worker_task = loop.create_task(_worker(_queue, _idle))
        return _queue


async def _worker(queue: asyncio.Queue, idle: asyncio.Event) -> None:
    """THE ONE AND ONLY worker. A separate task means its troubles stay its own.

    The whole body sits under `except`: an exception in the renderer has no
    right to bring down the worker, let alone reach the write path (it
    couldn't reach it anyway — that's a different task). The `render_errors`
    counter makes the breakage VISIBLE as a number; surviving it silently
    would be the same deception, just a polite one.
    """
    while True:
        try:
            key = await queue.get()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _COUNTERS["worker_errors"] += 1
            continue
        idle.clear()
        try:
            pending = {key}
            # Collapsing: while the worker was drawing, ten alarm clocks for
            # one session could have arrived. We draw ONCE, from the current
            # state of the journal — a lagging frame is of no use to anyone.
            while True:
                try:
                    pending.add(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            for session_key in pending:
                try:
                    await _serve(session_key)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    _COUNTERS["worker_errors"] += 1
                    logger.debug("live plan worker cycle failed", exc_info=True)
            # Rate limiting. Sits AFTER the send, so the first frame goes out
            # without delay, while the stream is no more frequent than the
            # interval.
            interval = _interval_s()
            if interval > 0:
                await asyncio.sleep(interval)
        finally:
            if queue.empty():
                idle.set()


async def _serve(session_key: tuple[str, str]) -> None:
    """Catch up with the journal by cursor, draw the changed floors, send.

    One pass is BOUNDED on both axes: how many programs we index and how many
    ops we hand to the render. Catching up over a hundred programs has no
    right to turn into one unbroken second of counting — not because it's
    slow, but because that counting runs in Python and holds the GIL, i.e. it
    takes time away from the turn itself.
    """
    entry = _journal.get(session_key)
    if entry is None:
        return
    device_id = session_key[0]
    if not attached(device_id):
        return
    pending = entry.pending()
    if not pending:
        return

    # INDEXING. Which floors each new program touched — we ask `preview`,
    # not our own copy of the rule: "which floor does this op belong to" is
    # already decided in `preview._op_level_key`, and a second instance of
    # that decision would drift apart from the first within a month.
    #
    # ONLY `create_level` datums go into the indexing, not all of them: the
    # floor's name is given by `create_level`, grids do not affect the label.
    # Without the datums, key `$L1` in one program and "Level 0.000" in
    # another would split one floor into two.
    naming = [op for op in entry.datums if op.get("op") == "create_level"]
    batch = _index_batch()
    behind = len(pending) > batch
    pending = pending[:batch]
    # ONE trip to the thread for the whole batch, not one trip per program.
    # Measured before the fix: 400 programs = 400 switches and 1.4 s per run,
    # of which the indexing itself is a small part.
    try:
        indexed = await asyncio.to_thread(_index_batch_ops, naming, pending)
    except Exception:  # noqa: BLE001
        _COUNTERS["index_errors"] += 1
        logger.debug("live plan index failed", exc_info=True)
        indexed = [(record, ()) for record in pending]

    touched: list[str] = []
    for record, labels in indexed:
        for label, considered in labels:
            entry.level_index.setdefault(label, [])
            if record.seq not in entry.level_index[label]:
                entry.level_index[label].append(record.seq)
            entry.level_tally[label] = (
                entry.level_tally.get(label, 0) + considered)
            if label not in touched:
                touched.append(label)
        # The summary is incremental: O(new program's ops), not O(building).
        for op in record.ops:
            name = str(op.get("op", "?"))
            entry.op_tally[name] = entry.op_tally.get(name, 0) + 1
        entry.indexed_upto = record.seq + 1

    limit = _levels_per_frame()
    drawn = touched[-limit:] if len(touched) > limit else touched
    not_drawn = len(touched) - len(drawn)

    for label in drawn:
        ops, dropped_programs, pack = _slice_for(entry, label)
        if not ops:
            continue
        started = time.perf_counter()
        try:
            frame = await asyncio.to_thread(
                _render_frame, ops, label, pack[-1] if pack else None)
        except Exception:  # noqa: BLE001 — the renderer fails ON ITS OWN
            _COUNTERS["render_errors"] += 1
            logger.debug("live plan render failed", exc_info=True)
            continue
        finally:
            _COUNTERS["render_ms_total"] += (
                time.perf_counter() - started) * 1000.0
        _COUNTERS["renders"] += 1
        frame["slice_ops"] = len(ops)
        # A TRUNCATED SLICE MUST BE NAMED. A sheet missing the floor's first
        # twenty programs and a sheet that never had them look identical —
        # and that is exactly the class of silence `preview`'s census was
        # written to forbid.
        frame["slice_truncated_programs"] = dropped_programs
        if dropped_programs:
            frame["slice_truncated_ru"] = (
                f"на листе НЕ ПОКАЗАНЫ самые ранние программы этажа: "
                f"{dropped_programs} — срез ограничен")
        # 🔴 THE SLICE CAP IS NOT A CAP, AND THIS MUST BE SAID OUT LOUD
        # (F-203). `_slice_for` deliberately leaves the FIRST (freshest)
        # record whole, even when it alone outweighs the cap, and datums are
        # added AFTER the accounting. Both overshoots are legitimate by
        # design — but the declared "hard limit on rendering" stops being a
        # limit, and the reader has no way to learn this: they see
        # `slice_ops`, but nothing to compare it against.
        #
        # MEASURED ACROSS THE CORPUS (65 decompiles with `lift_cache`,
        # production `_slice_ops_cap()` = 1500): LONGER THAN THE CAP in 33 of
        # 65, median 1524, maximum 51,676 ops (`demo-v3`). The median is
        # ABOVE the cap — i.e. the overshoot hits the majority, not the edge.
        #
        # THE CAP IS NOT RAISED. Raising it would mean accepting second-long
        # frames under the GIL, which it was set up to forbid; lowering it
        # would mean dropping the fresh program whole. The FACT of the
        # overshoot is named, exactly as truncation is named a line above.
        frame.update(cap_notice(len(ops), _slice_ops_cap()))
        # The sheet card — in a THREAD, just like the renderer: it builds a
        # preview of the fresh program, and doing this under the event loop
        # would mean bringing back the very turn delay drawing was offloaded
        # to forbid. A card miss does NOT cancel the frame (fail-open): the
        # picture is useful without it, whereas a frame without a picture is
        # useless.
        try:
            card = await asyncio.to_thread(_sheet_card, ops, pack)
        except Exception:  # noqa: BLE001
            card = {}
            _COUNTERS["card_errors"] += 1
            logger.debug("live plan card failed", exc_info=True)
        frame.update({
            "type": "kir_plan",
            "schema": FRAME_SCHEMA,
            "stage": "planned",
            "seq": entry.indexed_upto,
            # THE SHEET IN FRONT OF THE PERSON — FIRST; THE SESSION JOURNAL — ALONGSIDE, WHOLE.
            "summary": card.get("sheet_summary") or entry.summary(),
            "journal_summary": entry.summary(),
            "journal": entry.stats(),
            "levels_not_drawn": not_drawn,
            "dropped_frames": _COUNTERS["dropped_frames"],
        })
        if card.get("program"):
            # THE FIELD'S NAME NAMES ITS SCOPE. Right next to it sits
            # `summary` — the SHEET, and a field called `summary_ru` would
            # read as its line, when it is actually the line of ONE program.
            # A value named wider than its scope is exactly the class of bug
            # being untangled today.
            frame["program"] = card["program"]
            frame["program_summary_ru"] = card["program"].get("summary_ru", "")
        # THE SHOWROOM. The frame reaches the person not only as a picture but
        # also with a SIGNATURE of its program; the body stays here. This is
        # exactly the law "what you saw is what gets built": the panel names
        # the signature, and the showroom is what hands the operations to the
        # executor — there is no way to name a program that was never shown.
        #
        # The unit is a BATCH (`pack`), not a merged list: program boundaries
        # are not visible on the sheet, but the compiler judges precisely the
        # program (budget, solo ops, transaction).
        #
        # A showroom miss does NOT cancel the frame: the picture is useful
        # without the button. Hence `transferable` is a separate field, not a
        # silent "well, it'll get transferred somehow".
        try:
            shown = _showroom.show(
                session_key, level=frame.get("level", label),
                programs=pack, context=list(entry.datums),
                census=frame.get("census") or {}, seq=entry.indexed_upto,
                ts=time.time())
        except Exception:  # noqa: BLE001 — the showroom has no right to drop the frame
            shown = None
            _COUNTERS["showroom_errors"] += 1
        if shown is not None:
            frame["program_digest"] = shown.digest
            frame["program_ops"] = shown.op_count
            frame["program_count"] = len(shown.programs_json)
            frame["transferable"] = True
        else:
            frame["transferable"] = False
            frame["transfer_blocked_ru"] = (
                "перенос недоступен для этого кадра: программу не удалось "
                "подписать (см. showroom_errors)")
        await _send(device_id, frame)

    if behind:
        # The batch ran out, the journal did not. We set an alarm clock for
        # ourselves, so the cursor catches up with the head over several
        # BOUNDED passes rather than one unbroken one. Queue full — no
        # matter: the worker will come back here anyway.
        queue = _queue
        if queue is not None:
            try:
                queue.put_nowait(session_key)
            except asyncio.QueueFull:
                _COUNTERS["dropped_frames"] += 1


def _index_batch_ops(naming: list[Mapping[str, Any]], records: list
                     ) -> list[tuple[Any, tuple[tuple[str, int], ...]]]:
    """Tag a batch of programs by floor — ONE trip into the worker thread."""
    out = []
    for record in records:
        try:
            out.append((record, _levels_of(naming + list(record.ops))))
        except Exception:  # noqa: BLE001 — one bad program does not drop the batch
            _COUNTERS["index_errors"] += 1
            out.append((record, ()))
    return out


def cap_notice(n_ops: int, cap: int) -> dict[str, Any]:
    """Frame fields about the slice cap. Factored into a function DELIBERATELY (F-203).

    While the naming lived as lines inside the `async` render, there was
    nothing to guard it with: a check could reach `_slice_for`, but not what
    the frame actually TELLS the reader. An instrument that cannot reach its
    own subject is green by construction.

    `slice_ops_cap` travels ALWAYS: without it there is nothing to compare
    `slice_ops` against. The overshoot fields appear only on an overshoot:
    announcing it where there isn't one would mean scaring the reader.
    """
    out: dict[str, Any] = {"slice_ops_cap": cap}
    if n_ops > cap:
        out["slice_cap_exceeded"] = n_ops - cap
        out["slice_cap_exceeded_ru"] = (
            f"срез БОЛЬШЕ объявленного потолка на {n_ops - cap} "
            f"операций ({n_ops} против {cap}): свежайшая программа "
            f"этажа не режется, а датумы добавляются сверх учёта")
    return out


def _slice_for(entry: Any, label: str) -> tuple[list, int, list]:
    """A SLICE BY FLOOR, not the whole building.
    -> (ops, how many programs did NOT fit, a BATCH of programs).

    The third value carried is the batch — the same programs, but NOT merged.
    Merging is what the renderer needs (one sheet); the batch is for the
    showroom and transfer: the compiler judges a program as a whole (budget,
    solo ops, one transaction), and it would rightly reject a merged list of
    ten programs as one giant one.

    A naive union of all the session's programs gives quadratic work: every
    new frame would redraw everything accumulated so far (measured K2 — 9.3 s
    for three floors). Only programs that TOUCHED this floor go in here, plus
    the datums; a program on a neighboring floor does not enter the frame's
    work at all.

    The granularity is a PROGRAM, not an operation: a program touching two
    floors goes into both slices in full, and the extra operations honestly
    go into the census as `LEVEL_NOT_IN_RUN`. Cutting by operation would mean
    setting up a SECOND instance of the rule "which floor does this op belong
    to" — the first one lives in `preview._op_level_key`, and two sources of
    truth about the same thing cost more than a bit of extra work on a rare
    two-floor program.

    WHY THERE IS ALSO A CAP ON TOP. Rendering is linear in the size of the
    slice, and the slice grows for the whole session: measured 03.08 — 543 ms
    per frame at 2,800 ops on one floor, i.e. at the journal's ceiling a
    frame would cost seconds. This is counted in Python, under the GIL, and
    although the work is offloaded to a thread, a long frame still takes
    cycles away from the turn. The cap hits the EARLIEST programs (fresher
    matters more) and NAMES how many were dropped.
    """
    cap = _slice_ops_cap()
    seqs = entry.level_index.get(label, ())
    records = entry.by_seqs(seqs)
    kept: list = []
    total = 0
    for record in reversed(records):
        if total + record.op_count > cap and kept:
            break
        kept.append(record)
        total += record.op_count
    kept.reverse()
    ops = list(entry.datums)
    pack: list[list] = []
    for record in kept:
        ops.extend(record.ops)
        pack.append(list(record.ops))
    return ops, len(records) - len(kept), pack


def _levels_of(ops: list[Mapping[str, Any]]) -> tuple[tuple[str, int], ...]:
    """(floor label, how many ops were attributed to it) — entirely from `preview`.

    A SEAM NEEDED IN `preview.py` (the fix is handled separately by the
    lead). Here a FULL `BuildingPreview` is built just for two fields — the
    floor labels and `census.considered`; the shapes of all elements are
    computed along the way and then thrown away right there. A cheap public
    `preview.program_level_index(ops) -> tuple[tuple[str, int], ...]` is
    needed, one that walks the ops, sorts them by
    `_op_level_key`/`_selector_key`, and does NOT build a `DrawnElement`. The
    cost of this seam is measured in the wave report; the ownership rule must
    not be reimplemented here — that would be a second source of truth.
    """
    from kir.preview import build_program_preview
    building = build_program_preview(ops)
    return tuple((plan.level_name, plan.census.considered)
                 for plan in building.plans)


def _render_frame(ops: list[Mapping[str, Any]], label: str,
                  fresh: list[Mapping[str, Any]] | None = None) -> dict:
    """One plan sheet. The heavy part, hence run in a thread.

    `fresh` — the operations of the program the person JUST asked for; their
    drawn addresses become the sheet's FOCUS. It is passed as operations rather
    than as ready ids so that the second preview is built in THIS thread, next
    to the first one: computing it on the event loop would bring back exactly
    the turn delay drawing was offloaded to forbid.
    Everything else on the sheet dims to context (`opacity` 0.16) instead of
    disappearing: the sheet is a slice of the whole floor, so a fresh cube
    stands among ninety unrelated elements and is indistinguishable from them.
    `None` — no focus at all, the sheet is drawn as before, byte for byte.

    🔴 AN EMPTY SET IS NOT A FOCUS. `focus=[]` would dim EVERY element to
    context, i.e. hand the person a grey sheet on which nothing is the subject
    of their request. The caller passes `None` in that case, and the difference
    is deliberate: "nothing to highlight" and "highlight nothing" are different
    facts.
    """
    from kir import preview as _P
    from kir.preview import build_program_preview, census_lines, render_svg
    # THE FOCUS IS COMPUTED BEFORE THE SHEET AND FAILS OPEN: a miss costs the
    # highlight, never the frame.
    focus: tuple[str, ...] | None = None
    if fresh:
        try:
            focus = _focus_ids(fresh) or None
        except Exception:  # noqa: BLE001 — the highlight has no right to cost the frame
            logger.debug("live plan focus ids failed", exc_info=True)
    building = build_program_preview(ops, levels=[label])
    try:
        plan = building.plan(label)
    except KeyError:
        raise ValueError(f"этаж {label!r} не собрался в лист") from None
    # 🔴 ФОКУС, КОТОРЫЙ НА ЛИСТЕ НИЧЕГО НЕ НАХОДИТ, — НЕ ФОКУС, А СЕРЫЙ ЛИСТ.
    # Список адресов ШИРЕ нарисованного нарочно (`program_element_ids`), и это
    # дёшево ровно до одного случая: свежая программа целиком ушла в перепись
    # (ни одного правила рисования, уровень не разрешился, тело без привязки).
    # Тогда ни один её адрес на листе не встречается, и `render_svg` честно
    # гасит ВСЁ до 0.16 — человек получает серый лист вместо ответа и читает
    # это как «ничего не построилось». «Нечего подсветить» и «подсветить
    # ничего» — разные факты; второй здесь запрещён.
    на_листе = [element.element_id for element in plan.elements]
    на_листе += [datum.element_id for datum in plan.datums]
    if focus is not None:
        if not (set(на_листе) & set(focus)):
            focus = None
    # 🔴 ОСНОВНОЕ ЗДАНИЕ И НОВОЕ — ДВА СПИСКА, А НЕ ОДНА ПРОЗРАЧНОСТЬ
    # (13.09.2026, слово владельца: «всё остальное здание становится
    # полупрозрачным, а когда мы тыкаем во вьюере одобрить — оно грамотно
    # мержится в основное здание»). В SVG различие УЖЕ есть
    # (`data-context="1" opacity="0.16"` против ничего), но картинку нельзя
    # ПОСЧИТАТЬ и нельзя перечислить словами. Окну нужны оба множества
    # именами: подсвеченное — чтобы назвать его человеческими словами в
    # правой колонке, погашенное — чтобы сказать, СКОЛЬКО контекста за ним
    # стоит, вместо молчания, которое читается как «тут больше ничего нет».
    свежие = list(focus or ())
    набор = set(свежие)
    основание = [oid for oid in на_листе if oid not in набор]
    return {
        "level": plan.level_name,
        # HONESTY OF THE SOURCE travels with the frame rather than being
        # implied: `assertion` comes from `preview.PreviewSource.PROGRAM`, it
        # is not set here.
        "assertion": plan.assertion.value,
        # 🔴 WORD ORDER IS THE FIX HERE (08.09.2026). This line used to read,
        # verbatim, "DECLARED by the program — the model was not read", and
        # that is exactly what the owner read as a badge over the picture
        # after asking to "make a cube". The line is CORRECT and answers a
        # question he did not ask: it is about the strength of the
        # instrument's assertion, not about what he should do. The
        # instrument's words are not removed — they moved into
        # `assertion_instrument_ru` and into `details`; the first line now
        # carries what a person can actually act on.
        "assertion_ru": (_P.HUMAN_ASSERTION_RU
                         if plan.assertion.value == "self_reported"
                         else "модель Revit прочитана независимо"),
        "assertion_instrument_ru": (
            _P.INSTRUMENT_ASSERTION_RU
            if plan.assertion.value == "self_reported"
            else "независимое чтение модели"),
        "source": plan.source.value,
        "content_digest": plan.content_digest,
        # THE SHEET IS FOR THE HUMAN (`audience="human"` by default): a
        # drawing and one line. The census, blind spots, coverage, and
        # signature have not gone anywhere — they are in this same file's
        # `<metadata>`, in `census_lines` alongside, and in `program.details`.
        # The audience changed, not the content.
        # 🔴 БЕЗ МЕБЕЛИ ЛИСТА (13.09.2026). Кадр едет В ОКНО МОДЕЛИРОВАНИЯ, а
        # не на печать: масштабная линейка там врёт (окно само масштабирует),
        # а «ПН (+Y) · истинный север не задан» — утверждение о том, чего мы
        # не читали, посреди стройки. Слово владельца о том же окне: «там куча
        # непонятной инфы, не относящейся к моделированию». Всё это цело в
        # `<metadata>` того же файла.
        "svg": render_svg(plan, focus=focus, chrome=False),
        # THE FOCUS TRAVELS BY NAME TOO, not only as opacity inside the file:
        # the panel must be able to SAY how much of the sheet is the subject
        # of the request, and a picture cannot be counted.
        "focus": list(focus or ()),
        # ТЕ ЖЕ ДВА МНОЖЕСТВА ПОД СВОИМИ ИМЕНАМИ. `focus` — слово о ПРИБОРЕ
        # (что подсветить); `fresh`/`ground` — слова о ЗДАНИИ (что новое, что
        # уже стоит). Поле `focus` оставлено дословно: его читает выкаченная
        # панель, и снять его значило бы погасить подсветку у всех, кто ещё
        # не обновился.
        "fresh": свежие,
        "ground": основание,
        # ИМЕНА, А НЕ АДРЕСА. В правой колонке окна человек читает «стена
        # длиной 6000 мм», а не `p1/w0`; фразу пишет единственный её автор
        # (`preview._describe_op_ru` через публичный шов), потому что два
        # места, называющие стену по-разному, — это наш класс дефекта.
        # Промах ИМЁН не отменяет кадр: картинка без подписи полезна,
        # подпись без картинки — нет.
        "fresh_ru": _fresh_names(fresh),
        # 🔴 ЧЕСТНОСТЬ ОБ ИСТОЧНИКЕ ФОНА. Погашенное на листе — это НЕ
        # существующая модель Revit: это срез ЖУРНАЛА СЕССИИ, то есть то,
        # что KIR построил на этом уровне сам. Элементы, которые были в
        # документе до сессии, сюда не попадают вовсе, и молчание об этом
        # прочиталось бы как «на этаже больше ничего нет». Цена чтения
        # документа названа в разборе W: `ground_snapshot` — каталог без
        # геометрии, `query_list` — поля без геометрии
        # (`registry_base.LIST_FIELDS`), геометрию даёт только
        # `query_inspect` по ОДНОМУ элементу за оп.
        "ground_source_ru": (
            "тусклым показан срез журнала этой сессии на этом уровне; "
            "элементы документа, существовавшие до сессии, на листе не "
            "показаны"),
        # A DARK SHEET WITHOUT A SECOND RENDER: the window substitutes the
        # colors itself. The frame is drawn under the GIL, and a second pass
        # would cost exactly as much as the first, for the same file.
        "theme_palette_dark": dict(_P.DARK_PALETTE),
        "census": plan.census.to_dict(),
        # THE CENSUS TRAVELS ALONGSIDE THE PICTURE, NOT ONLY INSIDE IT. The
        # sheet's footer prints as many lines as fit (and names the
        # remainder), while the sheet in the panel is squeezed to card width
        # — there is nothing to read an 11.5 px footer with there. The panel
        # needs the lines as text, whole and in Russian: a pretty picture
        # without the census is a pretty lie.
        "census_lines": list(census_lines(plan.census)),
        "meta": plan.to_dict(),
    }


def _fresh_names(program_ops: Any) -> list[dict[str, str]]:
    """Человеческие имена свежих элементов — для правой колонки окна.

    ОТКАЗ ЭТОГО ШАГА НЕ СТОИТ КАДРА (fail-open, как и у фокуса): без имён
    окно покажет лист и кнопки, без листа — не покажет ничего.
    """
    if not program_ops:
        return []
    try:
        from kir import preview as _P
        return [{"id": oid, "ru": ru}
                for oid, ru in _P.program_element_names(program_ops)]
    except Exception:  # noqa: BLE001 — подпись не имеет права стоить кадра
        logger.debug("live plan fresh names failed", exc_info=True)
        return []


def _focus_ids(program_ops: list[Mapping[str, Any]]) -> tuple[str, ...]:
    """The drawn ids of ONE program — asked of `preview`, not derived here.

    🔴 THE ID RULE HAS EXACTLY ONE AUTHOR, AND IT IS NOT THIS FILE. In
    `build_program_preview` a drawn element's id is `str(op["id"]) or the op's
    name`, after `_members_out_of_groups`. Re-deriving that here would be a
    second source of truth about what an element is called, and the sheet would
    stop glowing SILENTLY the first time the rule moved: `render_svg` compares
    ids, and an id that matches nothing dims the whole sheet instead of raising.

    🔴 AND IT IS THE CHEAP WALK, NOT A SECOND PREVIEW (measured 13.09.2026).
    The first draft asked `build_program_preview` for the fresh program and
    read the ids off its plans. Correct, and too expensive: the live-plan
    budget test measured **5.820 ms per program against a 4 ms budget** — the
    highlight would have been paid for with the very turn delay drawing was
    offloaded to forbid. `preview.program_element_ids` walks the operations
    once and builds no shapes.
    """
    from kir import preview as _P

    return _P.program_element_ids(program_ops)


def _sheet_card(ops: list[Mapping[str, Any]],
                pack: list[list[Mapping[str, Any]]]) -> dict:
    """THE SUMMARY OF THIS SHEET, not of the whole session. The heavy part runs in a thread.

    🔴 BOUGHT BY A LIVE TURN OF THE OWNER'S ON 08.09.2026. He asked for a cube
    and got, in the window, "declared by floor: #2607 — 6 · …" — MORE THAN A
    HUNDRED document levels full of numbers, "programs in journal: 195", and
    a census of 94 out of 98. Not one of these numbers was about his program:
    `summary` was taken from `journal.SessionJournal.summary()`, i.e. from
    THE WHOLE SESSION, while the census came from the floor's slice across
    all programs. The owner's word: "what is this garbage it's dumping on me
    in the chat... I asked it to build a cube — it can't."

    The session summary is not removed or trimmed — it travels in the same
    frame under the name `journal_summary`, and `journal` (the counters)
    travels exactly as it did. Exactly one thing changed: the FIRST thing a
    person sees is the sheet in front of them, not a journal they never
    opened.

    What is counted here is exactly what is shown: `ops` is precisely the
    operations that went to the renderer (datums plus the slice's programs),
    so "declared by floor" can no longer name a floor that is not on the
    sheet.
    """
    from kir import preview as _P
    # 🔴 THE COUNT RUNS OVER PROGRAMS, WHILE FLOOR NAMES RUN OVER EVERYTHING
    # THAT WENT TO THE RENDERER, AND THIS IS NOT NITPICKING. `_slice_for`
    # places `entry.datums` BEFORE the slice's programs, and that same
    # `create_level` also sits in the journal record — i.e. it appears in
    # `ops` TWICE. The first draft counted `by_op` over `ops` and printed
    # "level — 2" where the level was declared once (pin
    # `test_summary_counts_levels_and_ops`, 2 != 1). The duplicate does not
    # hurt the floor's name (a dict of names), but it does hurt the count.
    from_programs = [op for program in pack for op in program]
    by_op: dict[str, int] = {}
    for op in from_programs:
        name = str(op.get("op") or "")
        if name:
            by_op[name] = by_op.get(name, 0) + 1
    out: dict[str, Any] = {
        "sheet_summary": {
            "schema": FRAME_SCHEMA,
            "stage": "planned",
            "assertion": "self_reported",
            "title_ru": ("ЗАЯВЛЕНО программами ЭТОГО ЛИСТА "
                         "(не «построено» и не вся сессия)"),
            "levels": [{"level": name, "declared": count}
                       for name, count in _P.program_level_index(ops)],
            "by_op": dict(sorted(by_op.items())),
            "programs": len(pack),
            "total": len(from_programs),
        },
    }
    # THE FRESHEST PROGRAM IS THE ONE THE PERSON JUST ASKED FOR.
    # Its card (`preview.program_card`) is the only place in the frame where
    # the numbers are counted for EXACTLY one program; everything else on the
    # sheet is honestly wider, because it was drawn wider too.
    if pack:
        свежая = list(pack[-1])
        # 🔴 SLICE DATUMS TRAVEL AS CONTEXT, NOT AS A DENOMINATOR
        # (08.09.2026, "NOT done" item #3 of wave 9). `pack[-1]` holds only
        # the program's own operations, and if `create_level` arrived as a
        # SEPARATE program (and in a live session it does arrive exactly that
        # way — the live document's datums are supplied by
        # `built_verdict.datum_ops`, where the level's id is its ElementId),
        # the card's title read "at level "#2607"". `ops` is exactly what
        # went to the renderer: datums plus the slice's programs. Neither the
        # census, nor `ops`, nor the built count change because of this — the
        # context only gives a NAME and nothing else
        # (`preview._level_vocabulary`).
        out["program"] = _P.program_card({"ops": свежая}, ops=len(свежая),
                                         context=ops)
    return out


async def _send(device_id: str, payload: dict) -> None:
    transport = _transport
    if transport is None:
        return
    try:
        await asyncio.wait_for(
            transport(device_id, payload), timeout=_send_timeout_s())
        _COUNTERS["frames_sent"] += 1
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — a dropped socket is not our problem
        _COUNTERS["send_errors"] += 1
        logger.debug("live plan frame send failed", exc_info=True)


# ── valve ────────────────────────────────────────────────────────────────────

def remember_sections(*, device_id: Optional[str], doc_key: str = "",
                      sections: Any = None) -> None:
    """Hand the document's type geometry to the journal. Synchronous, never raises.

    A separate entry point, not a `publish` argument: the snapshot arrives
    LATER than the program (`serving`: publish, then ground), and waiting for
    it would mean delaying the write of the building's source code for the
    sake of a picture.
    """
    try:
        if not enabled():
            return
        _journal.remember_sections(
            _journal.key_for(device_id, doc_key), sections)
    except Exception:  # noqa: BLE001 — the stream has no right to cost a turn
        logger.debug("live plan sections failed", exc_info=True)


def publish(*, device_id: Optional[str], doc_key: str = "",
            program: Any = None, plan_digest: str = "",
            author_digest: str = "", source: str = "") -> Optional[int]:
    """THE ONE AND ONLY entry point of the stream. Synchronous, no waits, never raises.

    The order in the body is not style but a contract:
      1) the program lands in the JOURNAL (the primary artifact, never dropped);
      2) and only then is it decided whether to wake the renderer.
    The reverse order would mean that on queue overflow, what gets lost is
    not a picture but the building's source code.

    RETURNS the journal record's `seq`, or `None` ("not written": the stream
    is off, the program is empty, a refusal). The number is needed for
    exactly one thing: the caller learns the outcome LATER than the call and
    must be able to tell the journal how it ended (`journal.advance`).
    Without the number the stage would stay `planned` forever — and that is
    precisely what made the building's verdict a judge of the DECLARED.
    A number, not the record itself: the record is immutable and there is
    nothing for the caller to do with it, while a reference to it would
    outlive eviction and lie about the live store.
    """
    try:
        if not enabled():
            _COUNTERS["skipped_disabled"] += 1
            return
        _COUNTERS["published"] += 1
        key = _journal.key_for(device_id, doc_key)
        record = _journal.append(
            key, program, plan_digest=plan_digest,
            author_digest=author_digest, source=source)
        if record is None:
            return
        _COUNTERS["journaled"] += 1
        seq = record.seq
        # ── PUSH TO THE VIEWER. `seq` grows here and only here, so this is
        #    the only place we can wake it without setting up a second source
        #    of the cursor: the number belongs to the journal, and here it is
        #    merely passed along. The call is synchronous, bounded, and
        #    fail-open — the same three properties as `publish` itself;
        #    otherwise it could cost the turn.
        #    SITS BEFORE the `attached` check: the chat panel and the viewer
        #    page are DIFFERENT subscribers, and the absence of the first is
        #    no reason not to wake the second.
        try:
            from kir.viewer import push as _push
            _push.notify(device_id, doc_key, record.seq)
        except Exception:  # noqa: BLE001 — the viewer has no right to cost a turn
            pass
        if not attached(key[0]):
            # The panel is not attached — drawing does not start AT ALL.
            #
            # 🔴 THIS BRANCH MUST SPEAK, AND IT WAS BOUGHT LIVE ON 02.09.2026.
            # The owner said "nothing built in KIR and nothing shows".
            # The program, meanwhile, WAS SITTING in the journal (two
            # records, `Проект1`), the device matched character for
            # character, and the stream on those exact same programs
            # produces two frames with `transferable: true` — verified by
            # replaying the owner's actual records. In other words, EVERY
            # link was working, and the empty window was explained by
            # exactly one of two branches: "no panel" or "the frame went out
            # but was never drawn".
            #
            # THERE WAS NOTHING TO TELL THEM APART WITH FROM OUTSIDE THE
            # PROCESS: the counter lives in memory, `stats()` has no route
            # out, the showroom does not write to disk, and both branches
            # were equally silent. The diagnosis cost a measurement where
            # one line would have sufficed.
            #
            # INFO level, not DEBUG, DELIBERATELY: this is the only answer to
            # the question "why is the window empty", and a refusal hidden in
            # DEBUG is the named form of this whole tree's problem (on that
            # same day it cost the service four unreadable modules).
            _COUNTERS["skipped_no_panel"] += 1
            logger.info(
                "живой план: панель НЕ подключена, кадр не рисуется — "
                "устройство %s, документ %r, программа записана под seq=%s",
                key[0], key[1], seq)
            return seq
        queue = _ensure_worker()
        if queue is None:
            # There is no event loop — there is physically nowhere to draw.
            # This branch was silent too and also explains an empty window,
            # hence it is named.
            logger.info(
                "живой план: цикла событий нет, кадр не рисуется — "
                "устройство %s, документ %r, программа записана под seq=%s",
                key[0], key[1], seq)
            return seq
        try:
            queue.put_nowait(key)
            _COUNTERS["queued"] += 1
        except asyncio.QueueFull:
            # Accumulating is not allowed: an uncapped queue is a leak
            # deferred in time. A dropped alarm clock costs one picture (see
            # the module header).
            _COUNTERS["dropped_frames"] += 1
        return seq
    except Exception:  # noqa: BLE001 — ABSOLUTE fail-open
        logger.debug("live plan publish failed (fail-open)", exc_info=True)
    return None


# ── instruments ──────────────────────────────────────────────────────────────

async def drain(timeout: float = 10.0) -> bool:
    """Wait until the worker clears the queue. For measurements/tests only."""
    if _idle is None:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (_queue is None or _queue.empty()) and _idle.is_set():
            return True
        await asyncio.sleep(0.01)
    return False


def stats() -> dict[str, Any]:
    out = dict(_COUNTERS)
    out["attached_devices"] = len(_attached)
    out["queue_depth"] = _queue.qsize() if _queue is not None else 0
    out["queue_max"] = _queue_max()
    out["transport_bound"] = _transport is not None
    out["journal"] = _journal.stats()
    out["showroom"] = _showroom.stats()
    return out


def reset() -> None:
    """Reset the counters, the channel, the attachments, and the worker. For measurements/tests only."""
    global _worker_task, _worker_loop, _queue, _idle, _transport
    with _worker_lock:
        if _worker_task is not None and not _worker_task.done():
            _worker_task.cancel()
        _worker_task = None
        _worker_loop = None
        _queue = None
        _idle = None
    with _STATE_LOCK:
        _attached.clear()
    _transport = None
    for name in _COUNTERS:
        _COUNTERS[name] = 0.0 if name.endswith("_total") else 0
    _journal.reset()
    _showroom.reset()
