"""THE RETURN PATH — "transfer to Revit" as a TYPED decision, not a button.

Before this wave the stream was one-way: frames went to the person and never
came back (`serving.py` said so in so many words). Here an edge appears going
back, and it is deliberately narrow: the panel can say exactly one thing —
"build what I see" and, possibly, "this part of it".

──────────────────────────────────────────────────────────────────────────────
LAW ONE: we look at and build ONE program, not two
──────────────────────────────────────────────────────────────────────────────
The panel does not send a program. The panel sends the SIGNATURE of what was
shown, and the body is taken from the showroom (`showroom.py`) by that
signature. The swap is not checked — it is UNSPEAKABLE: a program the server
never showed has no signature in the showroom, and the panel has no way to
name it. What is checked is something else, and it is the second line of
defense: `Shown.verify()` recomputes the signature from the stored bytes
before handing it out, i.e. tampering with the showroom itself produces a
typed refusal, not a silent swap.

WHY NOT THE SHEET'S `content_digest`. It signs the picture. Measured 04.08: a
default wall, the same wall with `height_mm=4200`, and the same one with
`type_name="Кирпич 380"` give ONE sheet digest — neither the height nor the
type is drawn on the plan. As a transfer ticket it would mean exactly what
the typed compiler was built to forbid: a building with two signatures. The
transfer signature takes the whole program.

──────────────────────────────────────────────────────────────────────────────
LAW TWO: the selected piece is closed under its dependencies
──────────────────────────────────────────────────────────────────────────────
A door with no carrier wall is not "an incomplete program" but an INVALID
one: `compiler` refuses with code KIR-L003 ("ref does not point to an
earlier op"). So the subset is grown to closure over the forward-pass graph.

THE GRAPH IS NOT INVENTED HERE. It already exists and lives in the registry:
a parameter of kind `sel`/`target_w`/`refs_w` with a value of
`{"by": "ref", ...}` is an edge, and this is exactly the rule
`compiler.py:591-638` applies when building the DAG. `refs_of()` below reads
`spec.OPS[...].params`, not a list of field names: a list of names ("host",
"level", "wall") would drift apart from the registry on the very first new
operation, and it would drift SILENTLY.

GROWING THE SET WAS CHOSEN OVER REFUSING. The reasoning, point by point:

  1. what gets added is not guessed but DERIVED: the closure is deterministic
     and unique. Refusing would mean handing the person a task the compiler
     has already solved — and then what would types even be for;
  2. growing cannot introduce anything NEVER SEEN: the closure only takes
     operations from that same shown program. Everything added was on the
     same sheet, in the same census, under the same signature. The
     highlighted set expands, not the world;
  3. the cost of a mistake is asymmetric. Refusing costs a round trip through
     the most expensive resource (a person's attention); growing costs one
     named line;
  4. and yet silence is not allowed, so growing is NOT EXECUTED IMMEDIATELY.
     The grown batch gets ITS OWN signature and is placed in the showroom,
     while the decision comes back with status `needs_confirm` and a named
     list of what was added ("wall W1 — required by door D3, field host").
     Execution is only possible on a second request carrying the NEW
     signature. In other words, "silently build the incomplete" is
     impossible by construction, and so is "silently build the extra": no
     batch executes until its own signature has arrived from the panel.

──────────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE DOES NOT DO
──────────────────────────────────────────────────────────────────────────────
It does not compile, does not ground, does not write to Revit, and does not
open transactions. It issues a PERMIT: a batch of operations and the
signature under which it is permitted. `kukai/api/chat_ws.py` executes it
through the same public door `revit_ir` that chat uses — a second door into
Revit is deliberately not set up here.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from kir.live import showroom as _showroom
from kir.live import transfer_journal
from kir import env  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = (
    "DECISION_SCHEMA",
    "REQUEST_SCHEMA",
    "Added",
    "Decision",
    "Refusal",
    "Status",
    "authorize",
    "closure",
    "enabled",
    "redeem",
    "refs_of",
)

REQUEST_SCHEMA = "kir-transfer-request/1"
DECISION_SCHEMA = "kir-transfer-decision/1"

_FLAG = "KIR_TRANSFER"

#: Parameter KINDS that MAY carry a reference. Not a list of fields — a list
#: of KINDS; the fields themselves are declared by the operation registry.
#: Matches `compiler.py:613`.
_REF_KINDS = ("sel", "target_w")
_REF_LIST_KIND = "refs_w"


def enabled() -> bool:
    """The return-path switch, separate from the display switch: breaking the
    button and breaking the screen are different decisions, and they must not
    be confused."""
    return env.get(_FLAG, "1") != "0"


class Status(str, Enum):
    #: The signature was found, the closure added nothing — safe to execute.
    READY = "ready"
    #: The closure grew the selection. What was added is named; waiting for
    #: confirmation of the NEW signature. Nothing executes without a second
    #: request.
    NEEDS_CONFIRM = "needs_confirm"
    REFUSED = "refused"


class Refusal(str, Enum):
    """A CLOSED list of reasons. A refusal must NAME the reason, not apologize."""

    #: The return path is switched off by the flag.
    DISABLED = "disabled"
    #: The signature is not in the showroom: the server never showed that
    #: (or showed it so long ago the frame was evicted). NOT "the program is
    #: bad" — "I never showed this".
    NOT_SHOWN = "not_shown"
    #: The showroom holds bytes whose signature does not match them. Internal
    #: corruption; the one case where we can name the MISMATCH by value.
    STORE_CORRUPT = "store_corrupt"
    #: Asked to transfer the selection, but nothing is selected.
    SELECTION_EMPTY = "selection_empty"
    #: Identifiers were selected that are not in what was shown. The user is
    #: looking at one frame but sent the signature of another — this must be
    #: named.
    SELECTION_UNKNOWN = "selection_unknown"
    #: A local `id` appeared in SEVERAL programs of the batch. It is unique
    #: only within a program (`KIR-L003`: a `ref` points to an earlier op OF
    #: THE SAME program), so "W1" without a batch-scoped address names two
    #: different objects. Choosing for the person is not allowed, and taking
    #: both is worse still: they selected ONE. The refusal names which
    #: programs the name appeared in, and a batch-scoped address (`p1/W1`)
    #: resolves it without a second request.
    SELECTION_AMBIGUOUS = "selection_ambiguous"
    #: There is an operation in what was shown that is not in the registry:
    #: its edges are unknown, so the closure cannot be proven. No guessing
    #: allowed here.
    UNKNOWN_OP = "unknown_op"
    #: After closure there is nothing to execute.
    NOTHING_TO_BUILD = "nothing_to_build"
    #: The signature of what the panel DREW did not match the signature of
    #: what the server SHOWED. Since the merged scene, these are two
    #: DIFFERENT computations, and a mismatch means a building the engineer
    #: never saw. No winner is chosen here: taking the server's version means
    #: building the unshown, taking the panel's means trusting something we
    #: never computed.
    SHOWN_MISMATCH = "shown_mismatch"
    #: The panel is looking at a journal TAIL, not the building. A tail
    #: cannot be sent as the building, even if the signatures match: they
    #: would match on the tail.
    PARTIAL_SCENE = "partial_scene"
    #: The server never showed this session a scene at all — nothing to sign.
    #: Deliberately separate from `SHOWN_MISMATCH`: "didn't match" and "never
    #: shown" are cured differently, and the former still needs an
    #: explanation while the latter does not.
    NOTHING_SHOWN = "nothing_shown"


_REFUSAL_RU: dict[Refusal, str] = {
    Refusal.DISABLED: "перенос выключен на этом сервере (KUKAI_KIR_TRANSFER=0)",
    Refusal.NOT_SHOWN: (
        "такой программы сервер не показывал: подписи нет в витрине. "
        "Переносится только увиденное — программу, которой не было на экране, "
        "назвать нечем"),
    Refusal.STORE_CORRUPT: (
        "витрина хранит не то, что подписывала: содержимое кадра изменилось "
        "после показа — переносить нечего, пока расхождение не объяснено"),
    Refusal.SELECTION_EMPTY: "выделение пусто: переносить нечего",
    Refusal.SELECTION_UNKNOWN: (
        "выделены элементы, которых в показанной программе нет — вероятно, "
        "карточка и выделение с разных кадров"),
    Refusal.SELECTION_AMBIGUOUS: (
        "выделен идентификатор, который в этой пачке принадлежит нескольким "
        "программам сразу: он уникален только ВНУТРИ программы. Назовите его "
        "адресом масштаба пачки (`p1/W1`) — тот же адрес, каким сцена "
        "подписывает элементы"),
    Refusal.UNKNOWN_OP: (
        "в показанной программе есть операция, отсутствующая в реестре: её "
        "зависимости неизвестны, и замыкание выделения недоказуемо"),
    Refusal.NOTHING_TO_BUILD: "после замыкания исполнять нечего",
    Refusal.SHOWN_MISMATCH: (
        "то, что нарисовала панель, и то, что показал сервер, — разные вещи. "
        "Переносить нельзя НИ ОДНУ из версий: серверная не была на экране, "
        "панельную мы не считали. Перезагрузите сцену целиком"),
    Refusal.PARTIAL_SCENE: (
        "на экране ХВОСТ журнала, а не здание: часть программ в эту сцену не "
        "попала. Отправить хвост как здание нельзя — запросите сцену целиком"),
    Refusal.NOTHING_SHOWN: (
        "сервер не показывал этой сессии ни одной сцены: подписывать нечего"),
}


@dataclass(frozen=True, slots=True)
class Added:
    """One operation ADDED by the closure, and who required it."""

    op_id: str
    op: str
    needed_by: str
    via: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.op_id, "op": self.op,
                "needed_by": self.needed_by, "via": self.via,
                "ru": (f"{self.op} «{self.op_id}» — его требует «{self.needed_by}» "
                       f"(поле {self.via})")}


@dataclass(frozen=True, slots=True)
class Decision:
    """A typed decision. One per request, fully serializable."""

    status: Status
    #: The signature the panel sent (what the person saw).
    requested_digest: str = ""
    #: The signature of what is PERMITTED to execute. At `READY` it equals
    #: the previous one — that equality is exactly "what you saw is what
    #: gets built".
    transfer_digest: str = ""
    level: str = ""
    refusal: Refusal | None = None
    refusal_ru: str = ""
    #: What exactly diverged. Filled in wherever the mismatch is KNOWN.
    diverged: tuple[str, ...] = ()
    added: tuple[Added, ...] = ()
    programs: int = 0
    ops: int = 0
    selected: int = 0
    #: A census of EXACTLY what is permitted for transfer — not of the sheet.
    census: Mapping[str, Any] = field(default_factory=dict)
    census_lines: tuple[Mapping[str, Any], ...] = ()
    #: This floor's frame has been updated since. NOT a refusal: exactly what
    #: is on the card gets transferred. But staying silent about it would let
    #: the person think they are looking at the fresh one.
    stale: bool = False
    current_digest: str = ""
    #: How many CENSUS operations will not go into execution: held-back
    #: datums are counted so the person sees the floor, but the batch carries
    #: only programs (F-199). Zero means the census and the batch are about
    #: the same thing.
    census_not_executed: int = 0
    #: How many programs in the batch do not fit the chat door's author
    #: budget. Counted HERE, before any Revit: learning this on the device
    #: costs a round trip.
    over_budget: tuple[str, ...] = ()
    #: What the compiler ITSELF says about the batch, asked offline
    #: (`plan_program`). Not a second opinion and not a copy of the rules —
    #: the same judge, just ahead of time.
    preflight: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status is not Status.REFUSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DECISION_SCHEMA,
            "status": self.status.value,
            "requested_digest": self.requested_digest,
            "transfer_digest": self.transfer_digest,
            "level": self.level,
            "refusal": self.refusal.value if self.refusal else None,
            "refusal_ru": self.refusal_ru,
            "diverged": list(self.diverged),
            "added": [a.to_dict() for a in self.added],
            "programs": self.programs,
            "ops": self.ops,
            "selected": self.selected,
            "census": dict(self.census),
            "census_lines": [dict(line) for line in self.census_lines],
            "stale": self.stale,
            "current_digest": self.current_digest,
            "census_not_executed": self.census_not_executed,
            "over_budget": list(self.over_budget),
            "preflight": list(self.preflight),
        }


def _refuse(reason: Refusal, *, requested: str = "", level: str = "",
            diverged: Sequence[str] = (), extra_ru: str = "",
            current_digest: str = "") -> Decision:
    text = _REFUSAL_RU[reason]
    if extra_ru:
        text = f"{text}; {extra_ru}"
    return Decision(status=Status.REFUSED, refusal=reason, refusal_ru=text,
                    requested_digest=requested, level=level,
                    diverged=tuple(diverged), current_digest=current_digest)


# ── forward-pass graph ───────────────────────────────────────────────────────

def refs_of(op: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """(field, id it references) — by the REGISTRY, not by a list of names.

    Returns an empty tuple for an operation with no references. Raises
    `KeyError` if the operation is not in the registry: its edges are
    unknown, and silently treating it as independent would allow an
    incomplete program.
    """
    from kir import spec as _spec

    ospec = _spec.OPS[str(op.get("op", ""))]
    out: list[tuple[str, str]] = []
    for param in ospec.params:
        value = op.get(param.name)
        if param.kind in _REF_KINDS and isinstance(value, Mapping):
            if value.get("by") == "ref" and isinstance(value.get("value"), str):
                out.append((param.name, value["value"]))
        elif param.kind == _REF_LIST_KIND and isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                if not isinstance(item, Mapping):
                    continue
                if (item.get("by") == "ref"
                        and isinstance(item.get("value"), str)):
                    out.append((f"{param.name}[{index}]", item["value"]))
                    continue
                # A second-stage selector (`{"by": "face", "of": ...}`,
                # `kir/faceref.py`): the reference sits one level deeper.
                # Skipping it here would mean closing the selection WITHOUT
                # its producing op and handing out a program with a dangling
                # ref; a closure that loses an edge is worse than none at
                # all, because it looks complete.
                inner = item.get("of")
                if (item.get("by") == "face" and isinstance(inner, Mapping)
                        and inner.get("by") == "ref"
                        and isinstance(inner.get("value"), str)):
                    out.append((f"{param.name}[{index}].of", inner["value"]))
    return tuple(out)


def closure(ops: Sequence[Mapping[str, Any]],
            selected: Sequence[str]) -> tuple[list[dict[str, Any]], list[Added]]:
    """Close the selection over the forward-pass graph WITHIN one program.

    The original program's order is preserved: `compiler` requires a ref to
    point to an EARLIER op, and reordering would make the closed subset
    invalid again.

    The closure is deliberately intra-program. There are never `ref` links
    between programs of a batch by construction — `compiler` resolves `ref`
    only within one program, while a neighboring program refers to a level
    BY NAME (`base_level="Этаж 1"`). Pulling closure across the batch would
    mean inventing an edge the language does not have.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    for op in ops:
        oid = op.get("id")
        if isinstance(oid, str) and oid:
            by_id.setdefault(oid, op)

    wanted = {oid for oid in selected if oid in by_id}
    added: dict[str, Added] = {}
    stack = list(wanted)
    while stack:
        oid = stack.pop()
        op = by_id.get(oid)
        if op is None:
            continue
        for field_name, target in refs_of(op):
            if target in wanted or target not in by_id:
                # A reference outside the program (by name / by element id)
                # never reaches here: `refs_of` only yields `by=ref`, and an
                # unresolvable `ref` is the compiler's concern, not the
                # selection's.
                continue
            wanted.add(target)
            added[target] = Added(
                op_id=target, op=str(by_id[target].get("op", "?")),
                needed_by=oid, via=field_name)
            stack.append(target)

    kept = [dict(op) for op in ops
            if isinstance(op.get("id"), str) and op["id"] in wanted]
    order = {op.get("id"): i for i, op in enumerate(ops)}
    grown = sorted(added.values(), key=lambda a: order.get(a.op_id, 0))
    return kept, grown


def _resolve_selection(
    programs: Sequence[Sequence[Mapping[str, Any]]],
    selected: set[str],
) -> tuple[dict[int, set[str]], list[str], list[str]]:
    """Selection -> `{program position: local ids}` + unresolved + ambiguous.

    🔴 A LOCAL `id` IS UNIQUE ONLY WITHIN A PROGRAM (HR-03, 04.09.2026). The
    `known` set used to be collected FLAT across the whole batch, and that
    same set went into `closure` for EVERY program. Measured: two programs,
    each with its own legitimate `W1`, selection `["W1"]` — TWO walls came
    out, status `needs_confirm`, zero refusals. The person selected one
    object, and two got built, and there was no way to name this: "growth"
    only lists what was pulled in by references, and the second `W1` was not
    pulled in — it arrived AS THE SELECTION ITSELF.

    The rule `KIR-L003` ("a ref points to an earlier op OF THE SAME program")
    makes a name collision between programs LEGITIMATE, not corruption. So
    what needs fixing is addressing, not names.

    A SECOND ADDRESS FORMAT IS NOT INTRODUCED HERE. The batch's scope is
    already named — `clash_bundle.bundle_oid` gives `p1/W1`, and that is
    exactly what `viewer.live_scene` uses to qualify the scene before
    showing it. The prefix is not assembled here as a string: it is TAKEN
    from `bundle_oid(position, "")`, so the separator stays in one place in
    the tree. A panel that sends a raw `W1` is served by the old path for
    exactly as long as the name is unambiguous.

    Returns three things, and all three are values, not exceptions:
      * `{position (from 1): set of local ids}` — what to close in which
        program;
      * unresolved selection entries (belong to no program);
      * ambiguous ones: `id -> which programs it appeared in`, as a string
        for the person.
    """
    from kir.clash_bundle import bundle_oid

    # `id -> positions`, positions starting at 1: the same numbering as
    # `bundle_oid` and `live_scene._qualify(first_position=1)`.
    где: dict[str, list[int]] = {}
    for position, program in enumerate(programs, start=1):
        for op in program:
            oid = op.get("id")
            if isinstance(oid, str) and oid:
                места = где.setdefault(oid, [])
                if position not in места:
                    места.append(position)

    префиксы = {bundle_oid(position, ""): position
                for position in range(1, len(programs) + 1)}

    по_программам: dict[int, set[str]] = {}
    unknown: list[str] = []
    ambiguous: list[str] = []
    for запись in sorted(selected):
        for префикс, position in префиксы.items():
            if запись.startswith(префикс):
                oid = запись[len(префикс):]
                if position in где.get(oid, ()):  # the address named the program
                    по_программам.setdefault(position, set()).add(oid)
                else:
                    unknown.append(запись)
                break
        else:
            места = где.get(запись, [])
            if not места:
                unknown.append(запись)
            elif len(места) > 1:
                ambiguous.append(
                    f"{запись} — в программах "
                    + ", ".join(bundle_oid(p, запись) for p in места))
            else:
                по_программам.setdefault(места[0], set()).add(запись)
    return по_программам, sorted(unknown), ambiguous


# ── authorization ────────────────────────────────────────────────────────────

def _journal_attempt(decision: Decision, *, key: tuple[str, str], door: str,
                     started: float, error: str) -> None:
    """Write the attempt to the journal. ONE funnel for both doors.

    Here, and not inside `_authorize*`: the private functions have eight
    return points, and recording at each would be eight handwritten copies of
    one rule — the named defect of this whole tree. There are exactly two
    public doors, and both must already never raise, so the funnel coincides
    with the boundary.

    The journal has no right to change the decision: it does not raise by
    construction (`transfer_journal.record` is fail-open), and its own
    refusal goes to the log, not to the answer given to the person.
    """
    transfer_journal.record(
        decision, key=key, door=door, error=error,
        elapsed_ms=int((time.monotonic() - started) * 1000))


def authorize(key: tuple[str, str], *, digest: str,
              selection: Sequence[str] | None = None) -> Decision:
    """The one and only entry point of the return path. Never raises: a refusal is a value.

    `selection is None` means transfer the frame whole. `selection == []`
    means the person pressed "transfer selected" while selecting nothing;
    this is a separate refusal, not a silent transfer of everything.
    """
    started = time.monotonic()
    error = ""
    decision: Decision
    try:
        decision = _authorize(key, digest=digest, selection=selection)
    except Exception as exc:  # noqa: BLE001 — the panel has no right to bring down the server
        logger.exception("kir transfer authorize failed")
        error = f"{type(exc).__name__}: {exc}"
        decision = _refuse(Refusal.NOT_SHOWN, requested=str(digest or ""),
                           extra_ru="внутренняя ошибка разбора запроса")
    _journal_attempt(decision, key=key, door=transfer_journal.DOOR_FRAME,
                     started=started, error=error)
    return decision


def _authorize(key: tuple[str, str], *, digest: str,
               selection: Sequence[str] | None) -> Decision:
    if not enabled():
        return _refuse(Refusal.DISABLED, requested=str(digest or ""))

    digest = str(digest or "").strip().lower()
    shown = _showroom.recall(key, digest)
    if shown is None:
        current = _showroom.levels(key)
        return _refuse(
            Refusal.NOT_SHOWN, requested=digest,
            diverged=sorted(f"{lvl}={d[:16]}" for lvl, d in current.items()),
            extra_ru=(f"сервер помнит кадров: {len(current)}"
                      if current else "витрина этой сессии пуста"))
    if not shown.verify():
        stored = _showroom.program_digest(
            shown.programs_json, shown.context_json, shown.level)
        return _refuse(
            Refusal.STORE_CORRUPT, requested=digest, level=shown.level,
            diverged=(f"подписано {digest[:16]}", f"хранится {stored[:16]}"),
            extra_ru="содержимое кадра изменилось после показа")

    programs = shown.programs()
    context = shown.context()

    # CLOSURE. An empty selection and no selection at all are DIFFERENT things.
    added: list[Added] = []
    selected_ids: set[str] = set()
    if selection is None:
        pack = programs
    else:
        selected_ids = {str(s) for s in selection if str(s)}
        if not selected_ids:
            return _refuse(Refusal.SELECTION_EMPTY, requested=digest,
                           level=shown.level)
        по_программам, unknown, ambiguous = _resolve_selection(
            programs, selected_ids)
        if unknown:
            return _refuse(
                Refusal.SELECTION_UNKNOWN, requested=digest, level=shown.level,
                diverged=tuple(unknown[:24]),
                extra_ru=f"не найдено в показанном: {len(unknown)}")
        if ambiguous:
            return _refuse(
                Refusal.SELECTION_AMBIGUOUS, requested=digest,
                level=shown.level, diverged=tuple(ambiguous[:24]),
                extra_ru=f"неоднозначных имён: {len(ambiguous)}")
        pack = []
        try:
            # THE SELECTION IS CLOSED WITHIN ITS OWN PROGRAM, NOT ACROSS ALL
            # AT ONCE. Previously `sorted(selected_ids)` went into EVERY
            # program of the batch.
            for position, program in enumerate(programs, start=1):
                мои = по_программам.get(position)
                if not мои:
                    continue
                kept, grown = closure(program, sorted(мои))
                if kept:
                    pack.append(kept)
                    added.extend(grown)
        except KeyError as exc:
            return _refuse(Refusal.UNKNOWN_OP, requested=digest,
                           level=shown.level, diverged=(str(exc.args[0]),))
        if not pack:
            return _refuse(Refusal.NOTHING_TO_BUILD, requested=digest,
                           level=shown.level)

    blobs = tuple(_showroom.canonical_program(p) for p in pack)
    transfer_digest = _showroom.program_digest(
        blobs, shown.context_json, shown.level)

    # THE GROWN BATCH IS PLACED IN THE SHOWROOM UNDER ITS OWN SIGNATURE.
    # Otherwise confirmation would have to be taken "on faith", and
    # content-addressing would stop being complete: exactly what the
    # showroom can hand out by signature is what executes.
    census, lines = _census_of(context, pack, shown.level)
    # 🔴 STALENESS WAS READ BEFORE ITS OWN RECORD (F-198, 29.08.2026). The
    # `show` call below puts the batch under a DERIVED signature and thereby
    # BECOMES `latest`; `stale` used to be computed AFTER that — i.e. it
    # compared a value to itself and gave ALWAYS FALSE. The staleness flag
    # was dead precisely on the path it was written for: a selection made
    # from a STALE frame.
    #
    # Comparing against `shown.digest` is wrong: `shown` IS the original
    # frame, and the question "is it stale" is about comparing to the
    # LATEST, not to itself.
    latest = _showroom.levels(key).get(shown.level, "")
    if transfer_digest != digest:
        _showroom.show(key, level=shown.level, programs=pack,
                       context=context, census=census, seq=shown.seq,
                       ts=shown.ts, intent=shown.intent)

    over = _over_budget(pack)
    ops_total = sum(len(p) for p in pack)
    status = Status.READY if not added else Status.NEEDS_CONFIRM
    return Decision(
        preflight=_preflight(pack),
        status=status,
        requested_digest=digest,
        transfer_digest=transfer_digest,
        level=shown.level,
        added=tuple(added),
        programs=len(pack),
        ops=ops_total,
        selected=len(selected_ids),
        census=census,
        census_lines=tuple(lines),
        # 🔴 THE CONTEXT IS COUNTED IN THE CENSUS BUT WILL NOT GO INTO
        # EXECUTION (F-199, 29.08.2026). `_census_of` takes the held-back
        # datums (`create_level`, `create_grid`), while only `programs_json`
        # goes to execution: the person saw a census where the datums were
        # counted, and got a batch without them — the floor traveled with no
        # name.
        #
        # A NUMBER, NOT SILENCE, AND NOT DELETION. Removing the context from
        # the census would take away the one place where it is visible ON
        # WHICH FLOOR the building is happening; reporting it into the
        # batch is a decision about what travels to Revit, and it requires
        # knowing "does the datum already exist in the model", which KIR
        # does not have — Revit does. So what is removed is the PROMISE, not
        # the accounting: the census stays complete and NAMES its
        # non-executable share. The fork (context into the batch / context
        # out of the census) belongs to the lead.
        census_not_executed=len(context),
        stale=bool(latest and latest not in (digest, transfer_digest)),
        current_digest=latest,
        over_budget=over,
    )


def redeem(key: tuple[str, str], digest: str) -> list[list[dict[str, Any]]] | None:
    """Hand the executor the BATCH by signature. The only way to get the body.

    The executor NEVER RECEIVES operations from the panel — under no
    circumstance: it names a signature, the showroom hands out the bytes. So
    "execute something other than what was shown" is not a checked
    condition — it is unexpressible.
    """
    shown = _showroom.recall(key, str(digest or "").strip().lower())
    if shown is None or not shown.verify():
        return None
    return shown.programs()


#: The "the check did not run" string prefix. The reader (panel, chat, test)
#: needs a way to tell a warning ABOUT THE BATCH apart from the absence of
#: the check itself, and it must be one prefix for both lists — two spellings
#: would drift apart silently.
UNAVAILABLE_PREFIX = "ПРОВЕРКА НЕ СОСТОЯЛАСЬ"


def _unavailable(what: str, module: str, exc: BaseException) -> tuple[str, ...]:
    """The check failed to come up — SAY SO, rather than return an empty list.

    🔴 WHAT THIS CLOSES (RT-26). Both offline checks of the transfer decision
    (`_over_budget`, `_preflight`) sat under `except Exception: return ()`,
    and for them an empty tuple means "asked, and no complaints". So a
    broken tree looked like a clean batch, and a `Decision` with status
    `READY` reached the person with two empty warning lists. Measured, with
    the compiler import swapped for one that raises:

        a healthy tree     over_budget 0 lines · preflight 1 line
        broken, BEFORE     over_budget ()      · preflight ()      — indistinguishable
        broken, AFTER      both carry "ПРОВЕРКА НЕ СОСТОЯЛАСЬ: …"

    The form is borrowed from a neighbor in this same file: on its own
    refusal, `_census_of` returns not an empty census but
    `{"unavailable": True, "ru": …}` — "treat it as if there is NO shown
    coverage". Same law, same file.

    A STRING, NOT AN EXCEPTION: both checks are declared as WARNINGS, not a
    judge (see `_preflight`'s docstring), and turning the absence of a
    prediction into a transfer ban would mean setting up a second authority —
    exactly what this docstring forbids.
    """
    return (f"{UNAVAILABLE_PREFIX}: {what} не спрашивали — не поднялся "
            f"{module} ({type(exc).__name__}: {exc}). Это НЕ «претензий нет»",)


def _over_budget(pack: Sequence[Sequence[Mapping[str, Any]]]) -> tuple[str, ...]:
    """Which programs will not fit the CHAT door's author budget (20).

    Computed offline deliberately. Learning "the program is too long" on a
    live device costs a round trip through the most expensive resource; here
    it costs one comparison.
    """
    try:
        from kir.compiler import MAX_OPS_PER_PROGRAM as _cap
    except Exception as exc:  # noqa: BLE001 — see `_unavailable` below
        return _unavailable("бюджет чат-двери", "kir.compiler", exc)
    return tuple(
        f"программа #{i + 1}: {len(program)} опов > {_cap}"
        for i, program in enumerate(pack) if len(program) > _cap)


def _preflight(pack: Sequence[Sequence[Mapping[str, Any]]]) -> tuple[str, ...]:
    """Ask the compiler ITSELF about the batch — offline, before the device.

    WHY NOT OUR OWN CHECKS. A second instance of the rule "where a ref may
    point", "which op must be solo", "which field is mandatory" would drift
    apart from the first within a month, and it would drift SILENTLY. What
    is called here is precisely the judge that will judge on the device —
    `plan_program`. The only difference is that the answer arrives for free
    and immediately, rather than via a round trip to the most expensive
    resource.

    THIS IS NOT A REFUSAL BUT A WARNING. The judge remains the `revit_ir`
    door: it also sees the live model, and its verdict may differ from the
    planned one in either direction. Turning a prediction into a ban would
    mean setting up a second authority — the very defect that already cost
    this project an `ok:true` over a violated postcondition.
    """
    try:
        from kir.compiler import plan_program
        from kir.spec import IR_VERSION
    except Exception as exc:  # noqa: BLE001 — see `_unavailable` below
        return _unavailable("предполётный опрос компилятора",
                            "kir.compiler / kir.spec", exc)
    out: list[str] = []
    for index, program in enumerate(pack):
        try:
            plan_program({"ir_version": IR_VERSION, "intent": "перенос",
                          "ops": [dict(op) for op in program]}, bulk=True)
        except Exception as exc:  # noqa: BLE001 — the refusal text is the answer itself
            out.append(f"программа #{index + 1}: {exc}"[:400])
    return tuple(out)


def _census_of(context: Sequence[Mapping[str, Any]],
               pack: Sequence[Sequence[Mapping[str, Any]]],
               level: str) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    """A census of EXACTLY WHAT IS TRANSFERRED, not of the sheet.

    This is not decoration for the decision. The person selected a piece; how
    much of it is even drawn, and how much is not shown and why, is the only
    way to see that what is being transferred is not what they think, BEFORE
    it ends up in Revit.
    """
    try:
        from kir.preview import build_program_preview, census_lines
        ops = [dict(op) for op in context]
        for program in pack:
            ops.extend(dict(op) for op in program)
        building = build_program_preview(ops, levels=[level] if level else None)
        try:
            plan = building.plan(level)
            census = plan.census
        except KeyError:
            census = building.census
        return census.to_dict(), list(census_lines(census))
    except Exception:  # noqa: BLE001 — without a census the decision stays honest,
        # but it must SAY there is no census, rather than slip in an empty one as fact
        logger.debug("transfer census failed", exc_info=True)
        return ({"unavailable": True,
                 "ru": "перепись посчитать не удалось — считайте, что "
                       "показанного покрытия НЕТ"}, [])


# ═══════════════════════════════════════════════════════════════════════════
# THE VIEWER BUTTON: transferring the SHOWN SCENE, not a shown frame
# ═══════════════════════════════════════════════════════════════════════════
#
# A PRODUCT BOUNDARY, NOT AN OPTIMIZATION. The "send to Revit" button is the
# only place where the virtual becomes real, and it signs WHAT THE PERSON
# SAW. While the scene arrived whole, "shown" and "transferred" coincided by
# construction. With the merge of a base and tails, these are two DIFFERENT
# computations — the server's and the panel's — and any mismatch between
# them is a building the engineer never saw, built with their consent.
#
# THREE RULES, AND NONE IS DERIVED FROM THE OTHERS:
#
#   1. the signature is computed FROM WHAT WAS DRAWN. The panel assembles it
#      from its own merged buffers — the same numbers that feed the
#      renderer — rather than echoing what the server sent. Otherwise intent
#      would be what got signed;
#   2. a mismatch is a REFUSAL, not a choice of a winner. Both versions are
#      forbidden: the server's was never on screen, the panel's we never
#      computed;
#   3. `partial` reaches the button. An engineer looking at a tail must not
#      be able to send it as the building — even if the signatures matched,
#      they would have matched on the tail.
#
# WHAT IS NOT HERE. There is no selection of a piece (`selection`) on this
# path yet: the scene is transferred whole. Closure over dependencies is
# therefore not needed — the batch already has everything it references.
# Once selection appears, `closure` will come back too, and it is already
# written above for frames.

SCENE_DECISION_SCHEMA = "kir-transfer-scene/1"


def authorize_scene(key: tuple[str, str], *, shown_digest: str,
                    partial: bool = False) -> Decision:
    """Authorize transfer of the SHOWN SCENE. Never raises."""
    started = time.monotonic()
    error = ""
    decision: Decision
    try:
        decision = _authorize_scene(key, shown_digest=shown_digest,
                                    partial=partial)
    except Exception as exc:  # noqa: BLE001 — the button has no right to drop the session
        logger.exception("kir transfer authorize_scene failed")
        error = f"{type(exc).__name__}: {exc}"
        decision = _refuse(Refusal.NOT_SHOWN, requested=shown_digest,
                           extra_ru="решение не собралось — переносить нечего")
    _journal_attempt(decision, key=key, door=transfer_journal.DOOR_SCENE,
                     started=started, error=error)
    return decision


def _authorize_scene(key: tuple[str, str], *, shown_digest: str,
                     partial: bool) -> Decision:
    from kir.live import journal as _journal

    # 🔴 THE LOCAL `_showroom` IMPORT WAS REMOVED 28.08.2026: it is already
    # imported at module level (line 75) and called from there by four
    # neighboring functions. A second import of the same name inside a
    # function SHADOWS the first — a fix to the module-level import silently
    # fails to reach here, and two functions about the same module start
    # living differently. The guard `test_authority_boundaries` catches this.

    if not enabled():
        return _refuse(Refusal.DISABLED, requested=shown_digest)

    # THE TAIL IS CHECKED FIRST. It makes everything else meaningless: a
    # tail's signature will match itself and prove nothing by it.
    if partial:
        return _refuse(Refusal.PARTIAL_SCENE, requested=shown_digest)

    current = _showroom.scene_digest(key)
    if not current:
        return _refuse(Refusal.NOTHING_SHOWN, requested=shown_digest)
    if not shown_digest or shown_digest != current:
        # THE MISMATCH IS NAMED BY BOTH SIGNATURES. A refusal that does not
        # say what failed to match what is indistinguishable from breakage.
        return _refuse(
            Refusal.SHOWN_MISMATCH, requested=shown_digest,
            current_digest=current,
            diverged=(f"панель: {shown_digest or '(пусто)'}",
                      f"сервер: {current}"))

    session = _journal.get(key)
    if session is None or not session.records:
        return _refuse(Refusal.NOTHING_TO_BUILD, requested=shown_digest)

    # 🔴 THE BATCH IS EXACTLY WHAT THE SIGNATURE VOUCHES FOR (F-284/F-196,
    # 29.08.2026). Reading the journal "as is" would mean executing programs
    # the person never saw: the signature is taken from the PICTURE, and the
    # picture lags behind the journal by everything appended after the
    # render. Measured before the fix: signature `118e6045589cf07e` did not
    # change, the batch grew from 2 programs to 3, the status stayed
    # `ready`, and a wall with the address `НЕ-ПОКАЗЫВАЛИ` traveled to Revit.
    #
    # `upto == 0` means the scene was shown OUTSIDE the journal (or the
    # showroom evicted the record); then there is nothing to cut against,
    # and the batch is taken as before. This is not a loosening: the
    # signature of such a scene must still match above, and we simply do
    # not know its revision and do not pretend to.
    upto = _showroom.scene_upto_seq(key)
    records = list(session.records)
    if upto:
        shown_records = [r for r in records if r.seq < upto]
        unshown = len(records) - len(shown_records)
        if unshown:
            # 🔴 A REFUSAL, NOT A SILENT TRUNCATION. Silently building LESS
            # than what was shown is exactly as much a lie as building more:
            # the person pressed the button on what they see on screen RIGHT
            # NOW. A refusal costs one extra round trip (the panel redraws
            # and presses again) and is more honest by a whole class — the
            # property "what I see is what gets built" holds in BOTH
            # directions. The fork is named to the lead.
            return _refuse(
                Refusal.SHOWN_MISMATCH, requested=shown_digest,
                current_digest=current,
                diverged=(f"показано программ: {len(shown_records)}",
                          f"в журнале сейчас: {len(records)}",
                          f"дописано после отрисовки: {unshown}"))
        records = shown_records

    pack = [[dict(op) for op in record.ops] for record in records]
    if not any(pack):
        return _refuse(Refusal.NOTHING_TO_BUILD, requested=shown_digest)

    context = [dict(op) for op in session.datums]
    census, lines = _census_of(context, pack, "")
    return Decision(
        status=Status.READY,
        requested_digest=shown_digest,
        # THE EQUALITY OF SIGNATURES IS EXACTLY "what you saw is what gets
        # built" — but ONLY together with the batch being cut by `upto_seq`
        # above. One signature vouches for the PICTURE; for it to vouch for
        # the PROGRAM, the picture and the program must be taken at the same
        # journal revision (F-196, F-284, 29.08.2026). Previously NOTHING
        # tied them together, and a program appended after the render
        # traveled to Revit with someone else's consent. The claim is tied to
        # a guard: `test_a_signature_vouches_for_what_executes.py`.
        transfer_digest=shown_digest,
        current_digest=current,
        programs=len(pack),
        ops=sum(len(program) for program in pack),
        census=census,
        census_lines=tuple(lines),
        over_budget=_over_budget(pack),
        preflight=_preflight(pack),
    )
