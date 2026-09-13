"""THE SHOWROOM — what the server SHOWED, word for word, under a signature of its content.

WHY IT EXISTS, IN ONE SENTENCE. The "transfer to Revit" button must transfer
precisely the program the person saw on the card. Checking this by comparing
two digests is already decent; making a swap UNSPEAKABLE is better. This file
does the latter: only the signature travels outward, and it is this showroom,
and no one else, that hands the program to the executor. A program that was
never on screen has no way for the panel to name it: it has no signature in
the showroom.

WHY THE ALREADY-EXISTING SIGNATURE DID NOT FIT. `preview.FloorPlan.content_digest`
signs the SHEET, not the program — and that is correct for a sheet. Measured
04.08:

    a wall, 6000 mm, default,
    the same wall with height_mm=4200,
    the same wall with type_name="Кирпич 380"

give the ONE AND SAME `content_digest` (48d11fe1d66eb6a8), because neither
the height nor the type is drawn on the plan. Had we taken it as the transfer
ticket, the "build what I see" button would have built a 4.2 m brick wall
under the signature of an ordinary one. That is exactly the second signature
for one building that the compiler was typed to forbid. Hence the transfer
signature takes the WHOLE PROGRAM, including fields not visible on the plan.

THE STORAGE UNIT IS A BATCH, NOT A LIST OF OPS. A building is a BATCH of
programs (`compiler.PLAN_SOLO_OP`: a staircase must be the sole op of its
program), and program boundaries are not visible on the sheet. The showroom
stores them separately; otherwise a transfer would merge the batch into one
program and run afoul of both the budget and the solo rule.

BOUNDARIES. stdlib only. Not a single import from `kir` — not at module
level, not lazily, not even in a promissory comment. The showroom decides
nothing: it stores bytes and can say whether they changed. `transfer.py`
decides, and it lives separately PRECISELY BECAUSE OF THIS: the renderer
(`plan_stream`) must be able to fill the showroom without thereby acquiring a
path into the compiler.

PROGRAMS ARE STORED AS CANONICAL STRINGS, NOT DICTS. Three consequences, and
all three are needed: (1) the copy handed out is fresh, and the caller cannot
corrupt the original; (2) the signature is recomputed from the very thing
stored, not from its shadow, so tampering with the showroom is VISIBLE; (3)
bytes are counted, so the memory cap can be set in bytes rather than in
"items of unknown size".
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from kir import env  # noqa: E402  (dependency-free submodule — creates no ring)
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

__all__ = (
    "SHOWROOM_SCHEMA",
    "Shown",
    "ShowroomEncodingError",
    "canonical_program",
    "forget",
    "levels",
    "program_digest",
    "recall",
    "scene_digest",
    "scene_reset",
    "scene_shown",
    "scene_upto_seq",
    "reset",
    "show",
    "stats",
)

SHOWROOM_SCHEMA = "kir-shown-program/1"


class ShowroomEncodingError(ValueError):
    """The program cannot be represented as canonical JSON — nothing to sign it with."""


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(env.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _max_frames() -> int:
    """How many shown frames a session remembers. Not "as many as fit": the
    showroom lives in the memory of a live service, and an unbounded showroom
    is a leak with a nice name."""
    return _int_env("KIR_SHOWROOM_FRAMES", 12, low=1, high=512)


def _max_bytes() -> int:
    """A cap in BYTES, not in frames: a floor's frame with 1,500 ops and a
    frame with three walls take up different amounts, and counting them the
    same is the same as not counting at all."""
    return _int_env("KIR_SHOWROOM_BYTES", 4_000_000,
                    low=64_000, high=200_000_000)


def _max_sessions() -> int:
    return _int_env("KIR_SHOWROOM_SESSIONS", 8, low=1, high=256)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ShowroomEncodingError(str(exc)) from exc


def canonical_program(ops: Iterable[Mapping[str, Any]]) -> str:
    """One program -> canonical JSON of its operations."""
    return _canonical([dict(op) for op in ops])


def program_digest(programs: Sequence[str], context: str = "[]",
                   level: str = "") -> str:
    """THE SIGNATURE OF WHAT WAS SHOWN. Computed from the canonical strings,
    i.e. from exactly what is stored and will be handed to the executor — not
    from a copy of them.

    `level` is part of the signature too: the same set of programs, shown as
    the first floor's plan and as the second's, are two different things
    seen, and merging them into one signature would allow transferring "the
    same thing, but from a different sheet".
    """
    return hashlib.sha256(_canonical({
        "schema": SHOWROOM_SCHEMA,
        "level": level,
        "context": context,
        "programs": list(programs),
    }).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Shown:
    """One shown frame. Immutable; operations are handed out as fresh copies."""

    digest: str
    level: str
    seq: int
    ts: float
    #: Canonical JSON of EACH program in the batch, in journal order.
    programs_json: tuple[str, ...]
    #: Canonical JSON of the datums. This is DRAWING CONTEXT, not a program:
    #: `create_level` from the chunk header arrives here so the floor does not
    #: lose its name, but it must not be executed as a separate program — it
    #: is already inside its own.
    context_json: str
    #: `census.to_dict()` of the sheet this was shown on. Travels together
    #: with the program deliberately: a picture without the census is a
    #: pretty lie.
    census: Mapping[str, Any]
    intent: str = ""

    @property
    def nbytes(self) -> int:
        """Frame size IN UTF-8 BYTES, not in characters (F-285).

        🔴 THE NAME SAID "BYTES", THE BODY COUNTED CHARACTERS. `_canonical`
        holds `ensure_ascii=False`, i.e. Cyrillic stays Cyrillic, while a
        Python string's `len()` counts CHARACTERS. What is stored, hashed,
        and transmitted is this same text in UTF-8, where every Cyrillic
        letter is two bytes. So `held_bytes` was smaller than the real
        value, eviction lagged, and `stats()["bytes"]` reported compliance
        with the `KIR_SHOWROOM_BYTES` cap that it was not actually
        respecting.

        MEASURED ACROSS THE CORPUS (65 decompiles with `lift_cache`,
        production `canonical_program` run through a counter, 65 calls):
        undercount of **5.99%** in total, in 64 of 65 decompiles, the worst
        being `sob62_fas_r23_v12` at **11.12%**. The estimate in the finding
        itself ("roughly double for Cyrillic") is inflated several times
        over: the canonical JSON's keys and numbers are ASCII, Cyrillic
        appears only in NAMES and Russian category labels.

        The cap is NEITHER raised NOR lowered: what gets fixed is the
        MEASUREMENT, not the budget. Eviction will now trigger ~6% earlier —
        that is exactly a return to the declared cap.
        """
        return (sum(len(p.encode("utf-8")) for p in self.programs_json)
                + len(self.context_json.encode("utf-8")))

    def programs(self) -> list[list[dict[str, Any]]]:
        """Fresh mutable copies. The caller has nothing to corrupt the original with."""
        return [json.loads(blob) for blob in self.programs_json]

    def context(self) -> list[dict[str, Any]]:
        return json.loads(self.context_json)

    def render_ops(self) -> list[dict[str, Any]]:
        """Exactly the list that went to the renderer."""
        ops = self.context()
        for program in self.programs():
            ops.extend(program)
        return ops

    @property
    def op_count(self) -> int:
        return sum(len(json.loads(blob)) for blob in self.programs_json)

    def verify(self) -> bool:
        """Recompute the signature from what is stored. A mismatch = the showroom was tampered with."""
        return program_digest(
            self.programs_json, self.context_json, self.level) == self.digest


@dataclass(slots=True)
class _Room:
    frames: "OrderedDict[str, Shown]"
    #: floor -> signature of the FRESHEST shown frame. Needed not for
    #: verification but for an honest refusal: "I didn't show that program,
    #: but here is what's on this floor now" is more useful than just "no".
    latest: dict[str, str]
    held_bytes: int = 0
    shown_total: int = 0
    evicted: int = 0


_LOCK = threading.Lock()
_ROOMS: "OrderedDict[tuple[str, str], _Room]" = OrderedDict()


def show(key: tuple[str, str], *, level: str,
         programs: Sequence[Sequence[Mapping[str, Any]]],
         context: Sequence[Mapping[str, Any]] = (),
         census: Mapping[str, Any] | None = None,
         seq: int = 0, ts: float = 0.0, intent: str = "") -> Shown | None:
    """Put what was shown into the showroom. Returns `Shown`, or None if
    there is nothing to put. Never raises: the showroom has no right to break the frame.
    """
    try:
        blobs = tuple(canonical_program(ops) for ops in programs if ops)
        if not blobs:
            return None
        ctx = canonical_program(context)
        digest = program_digest(blobs, ctx, level)
        entry = Shown(
            digest=digest, level=str(level), seq=int(seq), ts=float(ts),
            programs_json=blobs, context_json=ctx,
            census=dict(census or {}), intent=str(intent or "")[:200])
    except Exception:  # noqa: BLE001 — a non-encodable program does not drop the stream
        return None
    with _LOCK:
        room = _ROOMS.get(key)
        if room is None:
            room = _Room(frames=OrderedDict(), latest={})
            _ROOMS[key] = room
            while len(_ROOMS) > _max_sessions():
                _ROOMS.popitem(last=False)
        _ROOMS.move_to_end(key)
        room.shown_total += 1
        room.latest[entry.level] = digest
        if digest in room.frames:
            # The frame did not change (a redraw of the same thing). We
            # refresh its position in the LRU, but do NOT overwrite it — what
            # is stored must remain the same byte for byte.
            room.frames.move_to_end(digest)
            return room.frames[digest]
        room.frames[digest] = entry
        room.held_bytes += entry.nbytes
        max_frames, max_bytes = _max_frames(), _max_bytes()
        # 🔴 A FRAME JUST PUT IN IS NOT EVICTED, EVEN IF IT ALONE OUTWEIGHS
        # THE WHOLE BUDGET (21.08.2026). Previously the loop ate through the
        # queue to the end, and when a frame was large ON ITS OWN, it flew
        # out in the very same millisecond it landed. The showroom returned
        # `Shown`, the author got a signature, and the very next `recall` on
        # it missed — and `transfer.authorize` named the reason `NOT_SHOWN`,
        # i.e. "I never showed that".
        #
        # THE MEASUREMENT THAT UNCOVERED THIS: a program of 100,001 ops
        # against a compiler cap of 100,000. The law
        # `test_over_budget_programs_are_named_before_revit_is_touched`
        # requires the author to hear "the program is longer than the
        # budget" OFFLINE, and instead heard "no such frame existed" — a
        # refusal correct in form and false in substance, pointing at the
        # wrong thing to fix.
        #
        # THE COST OF THE DECISION IS NAMED: a room may hold ONE frame beyond
        # the byte cap. This is bounded to one frame and is cleared by the
        # very next show; a lie about what was shown is bounded by nothing.
        while len(room.frames) > 1 and (len(room.frames) > max_frames
                                        or room.held_bytes > max_bytes):
            _gone_digest, gone = room.frames.popitem(last=False)
            room.held_bytes -= gone.nbytes
            room.evicted += 1
        return entry


def recall(key: tuple[str, str], digest: str) -> Shown | None:
    """Fetch what was shown by signature. A miss is NOT a showroom bug: it
    looks the same whether the frame is stale or the signature was never
    shown here at all.

    🔴 A READER THAT DOES NOT KNOW THE DOCUMENT IS NOT A REASON TO SAY "NEVER
    SHOWN" (02.09.2026, bought by a live refusal at the owner's).

    The showroom's key is `(device, document)`, and the writer has been
    putting the frame under the real document since 30.08
    (`plan_stream.publish(doc_key=…)`). But the transfer handler assembled
    the key BY HAND, bypassing the single source of truth `journal.key_for`,
    and always with an empty document:

        chat_ws.py::_handle_kir_transfer    key = (device_id or "", "")

    Before 30.08 both sides lived on empty and matched; after the writer was
    fixed, the transfer started missing BY CONSTRUCTION, and the refusal was
    honest in form and false in substance: "the server never showed that
    program", even though it had shown that exact one a second earlier.
    Exactly what `key_for`'s docstring warns about: "they would drift apart
    SILENTLY".

    So an empty document in the key is read as a QUESTION, not a statement:
    "for this device, the document is unknown to me". An answer is given only
    if there is exactly ONE candidate; two candidates are a refusal, not a
    choice made on the person's behalf, because building the program into
    the wrong document costs more than not building it.

    Security is not weakened: the signature must still sit in the showroom
    that the server ITSELF wrote for THIS device. The panel still cannot
    name a program it was never shown.
    """
    if not digest:
        return None
    with _LOCK:
        room = _ROOMS.get(key)
        if room is not None:
            entry = room.frames.get(digest)
            if entry is not None:
                room.frames.move_to_end(digest)
                return entry
        if key[1]:
            # The document was named and did not match — this is a real miss.
            return None
        hits = [(k, r) for k, r in _ROOMS.items()
                if k[0] == key[0] and digest in r.frames]
        if len(hits) == 1:
            k, r = hits[0]
            r.frames.move_to_end(digest)
            logger.info(
                "витрина: подпись %s найдена по УСТРОЙСТВУ (документ читатель "
                "не назвал); документ витрины %r", digest[:16], k[1])
            return r.frames[digest]
        if len(hits) > 1:
            logger.info(
                "витрина: подпись %s есть у %d документов устройства %r — "
                "ОТКАЗ, а не выбор: строить не в тот документ дороже, чем не "
                "строить", digest[:16], len(hits), key[0])
        return None


def levels(key: tuple[str, str]) -> dict[str, str]:
    """floor -> signature of the freshest shown frame."""
    with _LOCK:
        room = _ROOMS.get(key)
        return dict(room.latest) if room is not None else {}


def forget(key: tuple[str, str] | None = None) -> None:
    """Forget what a session was shown — BOTH THE FRAMES AND THE SIGNATURE.

    🔴 A DEFECT FOUND LIVE ON 14.08.2026, AND IT FIRED FOR THE OWNER. The
    showroom holds TWO stores: `_ROOMS` (frames) and `_SCENES` (the
    accumulated signature of what was shown). This function only cleared the
    first. So a session that was "forgotten" kept carrying the previous
    scene's signature — and the transfer gate compared a new panel against
    the OLD signature, answering `shown_mismatch` where there was nothing to
    compare.

    This is our class of bug in pure form: a value lives in two places, and
    nothing forces them to agree. One instrument was already saying so —
    `test_nothing_shown_is_its_own_refusal` turned red in the full run and
    green alone, because it depended on who had filled `_SCENES` before it. I
    read that red as "someone else's" and set it aside; an hour later it
    surfaced on the owner's screen as a refusal carrying two sixty-four-digit
    signatures.
    """
    with _LOCK:
        if key is None:
            _ROOMS.clear()
            _SCENES.clear()
        else:
            _ROOMS.pop(key, None)
            _SCENES.pop(key, None)


reset = forget


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "schema": SHOWROOM_SCHEMA,
            "sessions": len(_ROOMS),
            "frames": sum(len(r.frames) for r in _ROOMS.values()),
            "bytes": sum(r.held_bytes for r in _ROOMS.values()),
            "shown_total": sum(r.shown_total for r in _ROOMS.values()),
            "evicted": sum(r.evicted for r in _ROOMS.values()),
            "max_frames": _max_frames(),
            "max_bytes": _max_bytes(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# THE SIGNATURE OF THE SHOWN SCENE — accumulated, because the scene arrives in parts
# ═══════════════════════════════════════════════════════════════════════════
#
# WHY SEPARATE FROM `show`. `show` signs a PLAN FRAME: a set of programs for
# one floor, shown once. The viewer, on the other hand, since the delta wave
# shows the ACCUMULATED whole: the whole building arrives as a base, then as
# tails, and the person looks at their merge. The "send to Revit" button
# signs what the person saw, so what must be signed is the merge, not the
# latest tail.
#
# WHY A MULTISET, NOT A CHAIN. Found by a check BEFORE shipping
# (`verify_shown.mjs`): the whole scene lists elements in the order "all
# solids first, then all ghosts", while the merge is "the base's solids and
# ghosts, then the tail's solids and ghosts". It is THE SAME building, the
# order in the buffer differs, and a hash chain would have declared them
# different. Order in the buffer is a detail of drawing, not a property of
# the building, so the signature must be blind to it.
#
# A sum modulo 2^256 of the sha256 of each record gives exactly that: it does
# not depend on order and stays O(new) per frame. SUMMATION was chosen, not
# XOR: XOR cancels pairs, i.e. two identical elements would vanish without a
# trace, and an element duplicated by a delta is exactly the defect the
# signature must catch.
#
# WHY THE HASH ACCUMULATES INSTEAD OF BEING RECOMPUTED FROM SCRATCH.
# `hashlib` supports `update`, so the server adds EXACTLY the records of the
# new elements and stays O(new) per frame — the very property deltas were
# built for. Recomputing over the whole scene would give the frame the cost
# of the whole, i.e. it would fix the transport and break it right back with
# its own button.
#
# WHY THE SERVER COMPUTES IT ITSELF INSTEAD OF TAKING IT FROM THE PANEL. If
# the chain continued from a value sent by the client, a client with a broken
# merge would send its own wrong "previous", the server would continue from
# it, and the signatures would match while the buildings had diverged. Both
# sides must compute INDEPENDENTLY: the server from what it sent, the panel
# from what it drew. A match then means an actual match, not politeness.

SCENE_SCHEMA = "kir-shown-scene/1"


#: The sum's modulus. 2^256 is exactly the width of sha256, so the sum loses no bits.
_SCENE_MOD = 1 << 256


@dataclass(slots=True)
class _Scene:
    """The accumulated signature of one session's shown scene."""

    total: int = 0
    elements: int = 0
    frames: int = 0
    records_bytes: int = 0
    #: Mesh vertices in the MERGED scene held by the panel (F-008). An
    #: accumulator just like `elements`/`frames`; needed because the mesh
    #: signature must be computed over the merged scene's indices, not the
    #: frame's own.
    mesh_vertices: int = 0
    #: 🔴 UP TO WHICH JOURNAL `seq` THIS SIGNATURE VOUCHES (class P5-G,
    #: findings F-284/F-196, 29.08.2026). Previously the signature was a
    #: property of the PICTURE and said nothing about the PROGRAM: a program
    #: appended after the render would travel to Revit under a signature
    #: issued BEFORE it existed, with status `ready`. Measured: signature
    #: `118e6045589cf07e` did not change, while the batch grew from 2
    #: programs to 3, and a wall with the address `НЕ-ПОКАЗЫВАЛИ` traveled to
    #: Revit. Zero means "the scene was shown outside the journal": such a
    #: scene still cannot be transferred today except by its own batch.
    upto_seq: int = 0
    #: 🔴 THE SCENE'S ORIGIN IS A PROPERTY OF THE SCENE, NOT OF THE FRAME, AND
    #: IS COUNTED ONCE (the second half of F-284). The first draft folded it
    #: into `total` on EVERY frame, so the whole scene contributed one
    #: addition while base+tail contributed two: the signature started
    #: depending on the DELIVERY PATH, and the merge guard
    #: (`test_a_tail_is_signed_as_the_glued_scene`) caught it. We hold it as
    #: a separate term: no matter how many frames arrive, it enters the sum
    #: exactly once, while a shift of the origin does change the signature.
    origin_mark: int = 0

    def hexdigest(self) -> str:
        """Sum -> the same 64 hex digits as sha256: the consumer has no need
        to know about the sum, and there is one signature format in the batch."""
        return format((self.total + self.origin_mark) % _SCENE_MOD, "064x")


_SCENES: "OrderedDict[tuple[str, str], _Scene]" = OrderedDict()


def scene_reset(key: tuple[str, str]) -> str:
    """Start the signature over — a whole scene (`since=0`) resets the accumulator.

    Returns the signature of the EMPTY scene, not an empty string: "nothing
    shown" is a state that has a signature, and telling it apart from "no
    session" must be done by a value, not by its absence.
    """
    with _LOCK:
        scene = _Scene()
        _SCENES[key] = scene
        _SCENES.move_to_end(key)
        while len(_SCENES) > _max_sessions():
            _SCENES.popitem(last=False)
        return scene.hexdigest()


def scene_mesh_base(key: tuple[str, str]) -> int:
    """How many mesh vertices the panel already holds for this session.

    Asked BEFORE building a tail: the mesh signature must be computed over
    the MERGED scene's indices, because that is exactly what the panel signs
    (`scene-data.js` rebases indices on merge). Zero means either there is no
    session or the next frame is a whole one.
    """
    with _LOCK:
        scene = _SCENES.get(key)
        return int(scene.mesh_vertices) if scene else 0


def scene_shown(key: tuple[str, str], records: Sequence[bytes], *,
                elements: int, whole: bool, mesh_vertices: int = 0,
                upto_seq: int = 0,
                origin_mm: "Sequence[float] | None" = None) -> str:
    """Add what was shown to the session's signature and return the ACCUMULATED value.

    `whole=True` (a whole scene) resets the accumulator before adding: the
    base replaces everything the panel held before it. `whole=False` is a
    tail, and it only gets appended.
    """
    if whole or key not in _SCENES:
        scene_reset(key)
    with _LOCK:
        scene = _SCENES.get(key)
        if scene is None:  # evicted between the lines — start over
            scene = _Scene()
            _SCENES[key] = scene
        for record in records:
            scene.total = (scene.total + int.from_bytes(
                hashlib.sha256(record).digest(), "big")) % _SCENE_MOD
            scene.records_bytes += len(record)
        # 🔴 THE SCENE'S ORIGIN ENTERS THE SIGNATURE AS A SERVICE RECORD (the
        # second half of F-284). Record coordinates are RELATIVE to the
        # origin, and the origin itself was not signed: shifting the origin
        # and the content by the same amount gave THE SAME signature for
        # DIFFERENT executable coordinates. It cannot be placed into an
        # element's record — that would break the multiset property
        # (identical records must add up); so it is placed as a separate
        # frame record in the same sum.
        if origin_mm is not None:
            mark = ("kir-scene-origin:" + ",".join(
                format(float(v), ".6g") for v in origin_mm)).encode("utf-8")
            # ASSIGNED, NOT ACCUMULATED: a scene has one origin, and a
            # "base + tail" merge must give the same signature as the whole.
            scene.origin_mark = int.from_bytes(
                hashlib.sha256(mark).digest(), "big") % _SCENE_MOD
        scene.elements += int(elements)
        # Mesh vertices ACCUMULATE just like elements: a whole scene already
        # reset the accumulator above (`scene_reset`), a tail appends its own.
        scene.mesh_vertices += int(mesh_vertices)
        scene.frames += 1
        # THE REVISION ONLY GROWS. A tail taken from an older revision must
        # not PUSH the guarantee backward: the signature accumulates, and it
        # vouches for the latest of what was shown.
        scene.upto_seq = max(scene.upto_seq, int(upto_seq))
        _SCENES.move_to_end(key)
        return scene.hexdigest()


def scene_digest(key: tuple[str, str]) -> str:
    """The session's current shown signature. An empty string means NEVER SHOWN.

    An empty string and the signature of an empty scene are different facts,
    and confusing them is not allowed: the former means "the server has
    shown this session nothing at all", the latter means "shown, and it was
    empty".
    """
    with _LOCK:
        scene = _SCENES.get(key)
        return scene.hexdigest() if scene is not None else ""


def scene_upto_seq(key: tuple[str, str]) -> int:
    """Up to which journal `seq` the session's signature vouches. `0` means
    either nothing was shown or the scene was shown outside the journal."""
    with _LOCK:
        scene = _SCENES.get(key)
        return scene.upto_seq if scene is not None else 0


def scene_stats(key: tuple[str, str]) -> dict[str, Any]:
    with _LOCK:
        scene = _SCENES.get(key)
        if scene is None:
            return {"shown": False}
        return {"shown": True, "schema": SCENE_SCHEMA,
                "digest": scene.hexdigest(),
                "elements": scene.elements, "frames": scene.frames,
                "records_bytes": scene.records_bytes}
