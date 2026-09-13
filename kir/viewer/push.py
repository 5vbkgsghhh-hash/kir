"""PUSH — a nudge instead of polling. An ALARM CLOCK, not data.

MEASURED BEFORE BUILDING (11.08.2026), and it canceled half of what was
planned:

* `seq` grows in EXACTLY ONE place — `plan_stream.publish()` calls
  `journal.append()` and gets back `record.seq`. There is no second source of
  a cursor, and none needs to be built;
* the `/ws/chat` transport is already up and subscribed, but it belongs to the
  CHAT PANEL: `plan_stream.bind_transport` binds it from `chat_ws`. **The
  viewer page has no socket of its own at all** — it only polls. So there is
  nothing to nudge it through with over a channel that belongs to someone
  else, and a channel of its own is set up (`/ws/viewer`);
* the delta is already O(what's new) (2.0 ms on 300 programs) and already
  carries `base_digest` with an honest refusal. There is no reason to push
  BYTES.

════════════════════════════════════════════════════════════════════════════
THE NUDGE CARRIES A NUMBER, NOT A SCENE — THE SAME DOCTRINE AS `plan_stream`
════════════════════════════════════════════════════════════════════════════
"What travels in the queue is not a frame but an ALARM CLOCK" — the rule by
which `plan_stream` justifies its right to DROP frames. Here it is applied one
floor up: what travels over the socket is `{"type": "kir_scene", "seq": N}`,
and the client fetches the scene with its OWN ordinary delta request — from
ITS OWN cursor and with ITS OWN base signature.

Three consequences, and all three are requirements met by construction:

1. **POLLING IS NOT DROPPED.** The nudge only wakes; the fetch path did not
   change by one line. A client whose socket dropped catches up with its
   cursor and gets the same thing, just later. Push is an acceleration, not
   the only path.
2. **`base_digest` WORKS THE SAME WAY.** The nudge carries no data, so it has
   nothing with which to weaken the delta's contract: a base mismatch still
   gives a 409 and a re-request of the whole thing. No silent conflation
   appears, because the nudge has nothing to conflate.
3. **A DROP IS VISIBLE.** The client always requests from ITS OWN cursor, so a
   lost nudge cannot lose a program — it only loses freshness. And for the
   loss to be VISIBLE, not silent, the nudge carries `seq`, and the client
   checks it against what it received: a poll that found work it was not
   woken for counts as a missed nudge and IS NAMED.

════════════════════════════════════════════════════════════════════════════
BOUNDEDNESS — BY THE SAME LAW AS THE RENDERER'S
════════════════════════════════════════════════════════════════════════════
A queue with a cap; once it overflows, the nudge is DROPPED and counted.
A dropped nudge costs a delay until the next poll, not a program: the program
is already in the journal, and the client's cursor will pick it up. A task per
event (`create_task` for every publish) is rejected here for the same reason
it is rejected there: an unbounded number of tasks is a leak wearing the mask
of asynchrony.
"""

from __future__ import annotations

import asyncio
import logging
import os
from kir import env  # noqa: E402  (a submodule with no dependencies — creates no cycle)
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ("PUSH_SCHEMA", "connect", "disconnect", "enabled", "notify",
           "reset", "stats", "subscribers")

PUSH_SCHEMA = "kir-scene-push/1"

_FLAG = "KIR_SCENE_PUSH"

#: The subscription key is the same `(device_id, doc_key)` as the journal's
#: and the showroom's. There is deliberately no key of its own here: a third
#: way of naming one session would drift apart from the first two silently.
_SUBS: dict[tuple[str, str], set] = {}
_QUEUE: Optional[asyncio.Queue] = None
_TASK = None
_LOOP = None

_COUNTERS = {
    "notified": 0, "sent": 0, "dropped": 0, "send_errors": 0,
    "no_subscriber": 0, "disabled": 0,
}


def enabled() -> bool:
    """A kill switch for all of push. Off = the behavior before this wave:
    the client polls and loses nothing, it just waits longer."""
    return env.get(_FLAG, "1") != "0"


def _queue_max() -> int:
    try:
        return max(1, min(1024, int(env.get("KIR_PUSH_QUEUE", "")
                                    or 64)))
    except (TypeError, ValueError):
        return 64


def connect(key: tuple[str, str], socket: Any) -> None:
    _SUBS.setdefault(key, set()).add(socket)


def disconnect(key: tuple[str, str], socket: Any) -> None:
    bucket = _SUBS.get(key)
    if bucket is not None:
        bucket.discard(socket)
        if not bucket:
            _SUBS.pop(key, None)


def subscribers(key: tuple[str, str]) -> int:
    return len(_SUBS.get(key) or ())


def _ensure_worker() -> Optional[asyncio.Queue]:
    """ONE bounded worker, like the renderer's. Recreated if the event loop
    has changed (a service restart within the same process)."""
    global _QUEUE, _TASK, _LOOP
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    if _LOOP is not loop or _QUEUE is None or _TASK is None or _TASK.done():
        _LOOP = loop
        _QUEUE = asyncio.Queue(maxsize=_queue_max())
        _TASK = loop.create_task(_worker(_QUEUE))
    return _QUEUE


async def _worker(queue: asyncio.Queue) -> None:
    while True:
        key, seq = await queue.get()
        # COLLAPSING: if nudges for the same session are already sitting in
        # the queue, take the LAST number. The client has no reason to wake up
        # three times to fetch the same tail, and the number is only an alarm
        # clock anyway.
        while not queue.empty():
            try:
                nkey, nseq = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if nkey == key:
                seq = max(seq, nseq)
            else:
                await _fanout(nkey, nseq)
        await _fanout(key, seq)


async def _fanout(key: tuple[str, str], seq: int) -> None:
    sockets = list(_SUBS.get(key) or ())
    if not sockets:
        _COUNTERS["no_subscriber"] += 1
        return
    payload = {"type": "kir_scene", "schema": PUSH_SCHEMA, "seq": int(seq),
               "device_id": key[0], "doc_key": key[1],
               # THE NUDGE CARRIES NO SCENE, and this is stated in it: a
               # reader who decides there is data here must trip over the
               # word.
               "wake_only": True,
               "ru": ("журнал вырос до seq=%d — заберите дельту своим "
                      "курсором и своей подписью базы" % int(seq))}
    for socket in sockets:
        try:
            await socket.send_json(payload)
            _COUNTERS["sent"] += 1
        except Exception:  # noqa: BLE001 — a dropped socket is not our problem
            _COUNTERS["send_errors"] += 1
            disconnect(key, socket)


def notify(device_id: Optional[str], doc_key: str, seq: int) -> None:
    """The ONLY entry point. Synchronous, no awaits, NEVER raises.

    Called from `plan_stream.publish` right after the journal — that is, from
    the same, single place where `seq` grows. No second source of a cursor
    appears: here the number is only PASSED ALONG, and it belongs to the
    journal.
    """
    try:
        if not enabled():
            _COUNTERS["disabled"] += 1
            return
        key = (str(device_id or ""), str(doc_key or ""))
        if not _SUBS.get(key):
            _COUNTERS["no_subscriber"] += 1
            return
        queue = _ensure_worker()
        if queue is None:
            return
        _COUNTERS["notified"] += 1
        try:
            queue.put_nowait((key, int(seq)))
        except asyncio.QueueFull:
            # A dropped nudge costs a DELAY, not a program: the program is
            # already in the journal, and the client's cursor will pick it up
            # on the next poll.
            _COUNTERS["dropped"] += 1
    except Exception:  # noqa: BLE001 — an ABSOLUTE fail-open, like publish
        logger.debug("scene push failed (fail-open)", exc_info=True)


def stats() -> dict[str, Any]:
    out = dict(_COUNTERS)
    out["schema"] = PUSH_SCHEMA
    out["enabled"] = enabled()
    out["sessions"] = len(_SUBS)
    out["sockets"] = sum(len(v) for v in _SUBS.values())
    out["queue_depth"] = _QUEUE.qsize() if _QUEUE is not None else 0
    out["queue_max"] = _queue_max()
    return out


def reset() -> None:
    global _QUEUE, _TASK, _LOOP
    _SUBS.clear()
    if _TASK is not None:
        _TASK.cancel()
    _QUEUE = None
    _TASK = None
    _LOOP = None
    for name in _COUNTERS:
        _COUNTERS[name] = 0
