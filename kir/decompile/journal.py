"""Append-only building journal — event-sourcing over the IR (wave 9).

An append-only log of edits (a base snapshot plus a sequence of wave-6
``DeltaProgram`` events) from which **replay, undo/redo, audit, and incremental
rebuild** all follow as consequences.  One structure — the log — gives four
capabilities; that is the "substrate" of event sourcing.

* An event is a delta; the state at any revision is the DETERMINISTIC fold of
  the log (replay).  Undo is just reading the previous revision's state; audit
  is reading an event's delta; incremental rebuild between revisions IS the
  event's delta.
* Each event carries a chain hash ``H(prev_hash || canon(payload))`` (git/
  blockchain style), so the log is tamper-evident: altering or dropping an
  event breaks every later hash and ``verify()`` fails closed.
* Append returns a NEW journal (immutable), so branching history is trivial and
  undo never mutates the log — the history stays a complete audit trail.

Discipline (forks in EVENT_SOURCING_SPEC.md):

* **State is the canon_op multiset** (wave 6's ``BuildingState``) — id
  independent, so rename/renumber does not break the history.
* **commit checks applicability to head** — a delta whose removals are not in
  the head state is a typed ``JournalRevisionError`` (you cannot graft a
  foreign delta), exactly as ``apply_delta`` fails closed.
* **Inert, additive, opt-in.**  Nothing is touched; ``journal_enabled()`` is
  default OFF.  Frozen L0 untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
from kir import env  # noqa: E402  (dependency-free submodule — avoids an import cycle)
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from kir.decompile.fold import TreeNode
from kir.decompile.rebuild import (
    BuildingState,
    DeltaApplyError,
    DeltaOp,
    DeltaProgram,
    apply_delta,
    delta_between,
)

JOURNAL_VERSION = "journal/1"


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class JournalError(ValueError):
    """Base for every typed journal failure."""


class JournalIntegrityError(JournalError):
    """The hash chain does not verify (a tampered / dropped / reordered log)."""


class JournalDecisionError(JournalError):
    """A decision was violated or is itself illegal. The refusal is TYPED and NAMES it."""


class JournalRevisionError(JournalError):
    """A revision is out of range, or a commit is not applicable to head."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def journal_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return env.get("KIR_DECOMPILE_JOURNAL", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Canonical (de)serialization of the value types
# ---------------------------------------------------------------------------


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"))


def _state_to_dict(state: BuildingState) -> dict[str, Any]:
    return {"multiset": [[op, count] for op, count in state.multiset]}


def _state_from_dict(payload: Mapping[str, Any]) -> BuildingState:
    try:
        pairs = tuple(
            (str(op), int(count)) for op, count in payload["multiset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalIntegrityError(f"malformed state: {exc}") from exc
    return BuildingState(multiset=tuple(sorted(pairs)))


def _op_to_dict(op: DeltaOp) -> dict[str, Any]:
    return {
        "kind": op.kind, "reason": op.reason,
        "path": list(op.path) if op.path is not None else None,
        "hash": op.hash,
        "remove_ops": list(op.remove_ops),
        "add_ops": list(op.add_ops),
        "remove_source_ids": list(op.remove_source_ids),
        "add_source_ids": list(op.add_source_ids),
    }


def _op_from_dict(payload: Mapping[str, Any]) -> DeltaOp:
    try:
        return DeltaOp(
            kind=str(payload["kind"]), reason=str(payload["reason"]),
            path=tuple(payload["path"]) if payload["path"] is not None else None,
            hash=payload["hash"],
            remove_ops=tuple(payload["remove_ops"]),
            add_ops=tuple(payload["add_ops"]),
            remove_source_ids=tuple(payload["remove_source_ids"]),
            add_source_ids=tuple(payload["add_source_ids"]),
        )
    except (KeyError, TypeError) as exc:
        raise JournalIntegrityError(f"malformed delta op: {exc}") from exc


def _delta_to_dict(delta: DeltaProgram) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ops": [_op_to_dict(op) for op in delta.ops],
        "reused_count": delta.reused_count,
    }
    # Omit absent bindings so journal/1 payloads written before the fidelity
    # transition guard retain their exact canonical JSON and hash chain.
    if delta.base_fidelity_hash is not None:
        payload["base_fidelity_hash"] = delta.base_fidelity_hash
    if delta.target_fidelity_hash is not None:
        payload["target_fidelity_hash"] = delta.target_fidelity_hash
    return payload


def _optional_fidelity_hash(
    payload: Mapping[str, Any], key: str,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 40 \
            or any(ch not in "0123456789abcdef" for ch in value):
        raise JournalIntegrityError(
            f"malformed delta: {key} must be a lowercase SHA-1 hex digest")
    return value


def _delta_from_dict(payload: Mapping[str, Any]) -> DeltaProgram:
    try:
        ops = tuple(_op_from_dict(o) for o in payload["ops"])
        reused = int(payload["reused_count"])
        base_fidelity_hash = _optional_fidelity_hash(
            payload, "base_fidelity_hash")
        target_fidelity_hash = _optional_fidelity_hash(
            payload, "target_fidelity_hash")
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalIntegrityError(f"malformed delta: {exc}") from exc
    return DeltaProgram(
        ops=ops,
        reused_count=reused,
        base_fidelity_hash=base_fidelity_hash,
        target_fidelity_hash=target_fidelity_hash,
    )


def _delta_summary(delta: DeltaProgram) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    for op in delta.ops:
        counts[f"{op.kind}:{op.reason}"] += 1
    return tuple(f"{key}×{value}" for key, value in sorted(counts.items()))


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BaseSnapshot:
    state: BuildingState


@dataclass(frozen=True, slots=True)
class DeltaEvent:
    delta: DeltaProgram
    summary: tuple[str, ...]


#: What a decision ASSERTS about a canonical operation. The list is CLOSED:
#: the constraint language here is deliberately tiny, because it must be
#: checkable AGAINST STATE, and state knows how to do exactly one thing —
#: count canonical operations. A rule that state cannot check would be a
#: promise.
DECISION_MODES = ("keep", "absent", "hole")


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    """A SECTION DECISION — a journal event, NOT a program field.

    🔴 WHY HERE, AND NOT IN THE PROGRAM (measured 02.09.2026, `E-104`). The
    owner's requirement: "a multi-agent environment builds in KIR" — meaning
    the structural (KR) agent has no right to demolish a decision made by the
    architectural (AR) agent. The first form considered (`{"by": "hole", ...}`
    in a selector, or an envelope key) was CANCELLED by reconnaissance BEFORE
    construction: `BuildingState` is declared, by its own docstring, as a
    "multiset of canonical ops", `leaves_to_program` sets ZERO envelope keys —
    meaning a program-level decision gets demolished BY CONSTRUCTION by its
    neighbor, no matter what form it was recorded in.

    A durable carrier must live where reassembly READS from, not where it
    REASSEMBLES to. In this tree there is exactly one such place — THIS
    JOURNAL: it is not derived from the model, so reassembly does not erase
    it.

    FIELDS
      `discipline`    who decided (`spec.DISCIPLINES`, a list closed by the
                      registry — not made-up "AR/KR/MEP")
      `mode`          `keep` — this operation must REMAIN (at least `count`)
                      `absent` — must NOT APPEAR
                      `hole` — must APPEAR, and until then the hole is OPEN
      `canon`         `canon_op` — the very canonical string the decision is
                      about. Not a sample and not a query: the decision states
                      what the author SAW
      `count`         how many instances (for `keep`); for `absent`/`hole` — 1
      `addressed_to`  whose hole (for `hole`), otherwise `None`
      `note`          the decider's words; carried into the refusal verbatim

    🔴 THE LIMIT IS NAMED: a decision can only speak about a canonical
    operation that CAN BE COUNTED in state. "A wall no thinner than 200" has
    nothing in state to check it against, and promising that here would set
    up a rule with no instrument behind it.
    """

    discipline: str
    mode: str
    canon: str
    count: int
    addressed_to: str | None
    note: str


@dataclass(frozen=True, slots=True)
class Event:
    index: int
    kind: str            # "base" | "delta" | "decision"
    prev_hash: str
    event_hash: str
    base: BaseSnapshot | None
    delta: DeltaEvent | None
    decision: "DecisionEvent | None" = None


def _decision_to_dict(decision: DecisionEvent) -> dict[str, Any]:
    """Key order does not matter (`_canonical_json` sorts them), but the set
    of keys does: it enters the hash chain, and adding a field breaks old
    signatures."""
    return {"discipline": decision.discipline, "mode": decision.mode,
            "canon": decision.canon, "count": decision.count,
            "addressed_to": decision.addressed_to, "note": decision.note}


def _decision_from_dict(payload: Mapping[str, Any]) -> DecisionEvent:
    return DecisionEvent(
        discipline=str(payload["discipline"]), mode=str(payload["mode"]),
        canon=str(payload["canon"]), count=int(payload["count"]),
        addressed_to=(None if payload.get("addressed_to") is None
                      else str(payload["addressed_to"])),
        note=str(payload.get("note") or ""))


def _event_payload(
    kind: str, base: BaseSnapshot | None, delta: DeltaEvent | None,
    decision: DecisionEvent | None = None,
) -> dict[str, Any]:
    if kind == "base":
        assert base is not None
        return {"kind": "base", "state": _state_to_dict(base.state)}
    if kind == "decision":
        assert decision is not None
        return {"kind": "decision", "decision": _decision_to_dict(decision)}
    assert delta is not None
    return {"kind": "delta", "delta": _delta_to_dict(delta.delta)}


def _chain_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    material = prev_hash + "\x00" + _canonical_json(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------


class BuildingJournal:
    """An immutable, append-only, tamper-evident log of building edits."""

    def __init__(self, events: tuple[Event, ...]) -> None:
        self._events = events

    @property
    def events(self) -> tuple[Event, ...]:
        return self._events

    @property
    def head_revision(self) -> int:
        return len(self._events) - 1

    def __len__(self) -> int:
        return len(self._events)

    # -- construction -------------------------------------------------------
    @classmethod
    def new(cls, base_state: BuildingState | None = None) -> "BuildingJournal":
        state = base_state if base_state is not None else BuildingState(())
        base = BaseSnapshot(state=state)
        payload = _event_payload("base", base, None)
        event = Event(
            index=0, kind="base", prev_hash="",
            event_hash=_chain_hash("", payload), base=base, delta=None)
        return cls((event,))

    def append_delta(self, delta: DeltaProgram) -> "BuildingJournal":
        """Return a NEW journal with ``delta`` committed at head+1.

        The delta must be applicable to the current head state (its removals
        present), else ``JournalRevisionError`` — you cannot graft a foreign
        delta.
        """

        head = self.head_state()
        try:
            apply_delta(head, delta)
        except DeltaApplyError as exc:
            raise JournalRevisionError(
                f"delta not applicable to head revision: {exc}") from exc
        # 🔴 THIS IS EXACTLY WHERE A NEIGHBOR'S DECISION IS PROTECTED. The
        # owner's requirement of 02.09 ("the KR agent has no right to
        # demolish a decision made by the AR agent") is enforced exactly at
        # the point where someone else's work enters history: a delta after
        # which a standing decision would be violated is NOT ACCEPTED, and
        # the refusal NAMES the decision — whose it is, what it requires, and
        # what is observed.
        #
        # INERT BY CONSTRUCTION: a journal with no decisions does no extra
        # checking at all and behaves exactly as before. The option is
        # switched on by someone having RECORDED a decision, not by a flag.
        решения = self.decisions_at()
        if решения:
            после = BuildingJournal(self._events + (Event(
                index=len(self._events), kind="delta", prev_hash="", 
                event_hash="", base=None,
                delta=DeltaEvent(delta=delta, summary=())),))
            нарушено = после.violations()
            if нарушено:
                строки = "; ".join(
                    f"ревизия {v['revision']} раздела {v['discipline']} "
                    f"({v['mode']}: требуется {v['required']}, стало "
                    f"{v['observed']})"
                    + (f" — {v['note']}" if v["note"] else "")
                    for v in нарушено)
                raise JournalDecisionError(
                    f"дельта сносит решение другого раздела: {строки}")
        delta_event = DeltaEvent(delta=delta, summary=_delta_summary(delta))
        payload = _event_payload("delta", None, delta_event)
        prev_hash = self._events[-1].event_hash
        event = Event(
            index=len(self._events), kind="delta", prev_hash=prev_hash,
            event_hash=_chain_hash(prev_hash, payload),
            base=None, delta=delta_event)
        return BuildingJournal(self._events + (event,))

    # -- section decisions ---------------------------------------------------
    def append_decision(self, decision: DecisionEvent) -> "BuildingJournal":
        """Record a DECISION. State does not move, history is not rewritten.

        The refusal is typed and NAMES why the input is no good: a discipline
        outside the registry's closed list, an unknown mode, a `keep` about
        something not present in state (a decision about something that does
        not exist is a promise, not a decision).
        """
        from kir import spec                                # noqa: PLC0415

        if decision.discipline not in spec.DISCIPLINES:
            raise JournalDecisionError(
                f"раздел {decision.discipline!r} вне закрытого списка реестра "
                f"{sorted(spec.DISCIPLINES)}")
        if decision.mode not in DECISION_MODES:
            raise JournalDecisionError(
                f"режим {decision.mode!r} вне закрытого списка {DECISION_MODES}")
        if decision.addressed_to is not None \
                and decision.addressed_to not in spec.DISCIPLINES:
            raise JournalDecisionError(
                f"дырка адресована разделу {decision.addressed_to!r} вне "
                f"закрытого списка реестра")
        if decision.mode == "hole" and decision.addressed_to is None:
            raise JournalDecisionError(
                "дырка без адресата: некому её увидеть списком")
        if decision.count < 1:
            raise JournalDecisionError(
                f"счёт {decision.count} меньше единицы: решение ни о чём")
        if decision.mode == "keep":
            есть = self.head_state().as_counter().get(decision.canon, 0)
            if есть < decision.count:
                raise JournalDecisionError(
                    f"решение `keep` о том, чего в состоянии НЕТ: требуется "
                    f"{decision.count}, наблюдается {есть}. Решение о "
                    f"несуществующем — обещание, а не решение")
        payload = _event_payload("decision", None, None, decision)
        prev_hash = self._events[-1].event_hash
        event = Event(
            index=len(self._events), kind="decision", prev_hash=prev_hash,
            event_hash=_chain_hash(prev_hash, payload),
            base=None, delta=None, decision=decision)
        return BuildingJournal(self._events + (event,))

    def decisions_at(self, revision: int | None = None
                     ) -> tuple[tuple[int, DecisionEvent], ...]:
        """Decisions in effect at a revision (the head, by default)."""
        предел = self.head_revision if revision is None else revision
        self._require_revision(предел)
        return tuple(
            (e.index, e.decision) for e in self._events[: предел + 1]
            if e.kind == "decision" and e.decision is not None)

    def violations(self, revision: int | None = None) -> tuple[dict[str, Any], ...]:
        """Decisions VIOLATED by the state at this revision.

        Checked against the multiset — exactly what state knows how to
        count. A `hole` does NOT count as a violation: an unfilled hole is
        open work, not a violation; that is what `open_holes` is for.
        """
        предел = self.head_revision if revision is None else revision
        счёт = self.state_at(предел).as_counter()
        плохо: list[dict[str, Any]] = []
        for индекс, d in self.decisions_at(предел):
            есть = счёт.get(d.canon, 0)
            if d.mode == "keep" and есть < d.count:
                плохо.append({"revision": индекс, "mode": "keep",
                              "discipline": d.discipline, "required": d.count,
                              "observed": есть, "canon": d.canon,
                              "note": d.note})
            elif d.mode == "absent" and есть > 0:
                плохо.append({"revision": индекс, "mode": "absent",
                              "discipline": d.discipline, "required": 0,
                              "observed": есть, "canon": d.canon,
                              "note": d.note})
        return tuple(плохо)

    def open_holes(self, discipline: str | None = None,
                   revision: int | None = None
                   ) -> tuple[tuple[int, DecisionEvent], ...]:
        """Holes addressed to a discipline and not yet filled.

        A hole is closed if and only if its canonical operation has appeared
        in state. No "we consider it closed because someone built something":
        closure is an observed fact, not an intention.
        """
        предел = self.head_revision if revision is None else revision
        счёт = self.state_at(предел).as_counter()
        return tuple(
            (i, d) for i, d in self.decisions_at(предел)
            if d.mode == "hole"
            and (discipline is None or d.addressed_to == discipline)
            and счёт.get(d.canon, 0) < d.count)

    # -- replay / navigation ------------------------------------------------
    def _require_revision(self, revision: int) -> None:
        if not isinstance(revision, int) or revision < 0 \
                or revision > self.head_revision:
            raise JournalRevisionError(
                f"revision {revision} out of range [0, {self.head_revision}]")

    def state_at(self, revision: int) -> BuildingState:
        """Deterministic replay: the state after events [0, revision]."""

        self._require_revision(revision)
        base_event = self._events[0]
        assert base_event.base is not None
        state = base_event.base.state
        for event in self._events[1: revision + 1]:
            # 🔴 A DECISION DOES NOT MOVE STATE, AND THIS IS LOAD-BEARING. The
            # journal's discipline is "state is a multiset of `canon_op`"; a
            # decision that made it into state would make replay depend on
            # intent, and reassembly non-repeatable. A decision lives
            # ALONGSIDE history, not inside its fold.
            if event.kind == "decision":
                continue
            assert event.delta is not None
            state = apply_delta(state, event.delta.delta)
        return state

    def head_state(self) -> BuildingState:
        return self.state_at(self.head_revision)

    def undo(self) -> tuple[BuildingState, int]:
        """Return (state, revision) one step back from head (history intact)."""

        if self.head_revision == 0:
            raise JournalRevisionError("nothing to undo (at base revision)")
        target = self.head_revision - 1
        return self.state_at(target), target

    def changes_at(self, revision: int) -> DeltaEvent:
        """The delta that produced ``revision`` (audit)."""

        self._require_revision(revision)
        if revision == 0:
            raise JournalRevisionError("revision 0 is the base, not a delta")
        event = self._events[revision]
        assert event.delta is not None
        return event.delta

    def audit(self) -> tuple[tuple[int, DeltaEvent], ...]:
        return tuple(
            (event.index, event.delta)
            for event in self._events
            if event.kind == "delta" and event.delta is not None)

    # -- integrity ----------------------------------------------------------
    def verify(self) -> None:
        """Recompute the hash chain; raise on any tamper."""

        if not self._events:
            raise JournalIntegrityError("empty journal")
        if self._events[0].kind != "base" or self._events[0].prev_hash != "":
            raise JournalIntegrityError("first event must be a base with no prev")
        prev = ""
        for expected_index, event in enumerate(self._events):
            if event.index != expected_index:
                raise JournalIntegrityError(
                    f"event index {event.index} != position {expected_index}")
            if event.prev_hash != prev:
                raise JournalIntegrityError(
                    f"event {event.index} prev_hash breaks the chain")
            payload = _event_payload(
                event.kind, event.base, event.delta, event.decision)
            recomputed = _chain_hash(prev, payload)
            if recomputed != event.event_hash:
                raise JournalIntegrityError(
                    f"event {event.index} hash does not match its payload")
            prev = event.event_hash

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": JOURNAL_VERSION,
            "events": [
                {
                    "index": event.index, "kind": event.kind,
                    "prev_hash": event.prev_hash,
                    "event_hash": event.event_hash,
                    "payload": _event_payload(
                        event.kind, event.base, event.delta, event.decision),
                }
                for event in self._events
            ],
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BuildingJournal":
        if not isinstance(payload, Mapping) or "events" not in payload:
            raise JournalIntegrityError("journal payload must carry events")
        events: list[Event] = []
        for row in payload["events"]:
            kind = row.get("kind")
            body = row.get("payload", {})
            base: BaseSnapshot | None = None
            delta_event: DeltaEvent | None = None
            decision: DecisionEvent | None = None
            if kind == "base":
                base = BaseSnapshot(state=_state_from_dict(body["state"]))
            elif kind == "delta":
                delta = _delta_from_dict(body["delta"])
                delta_event = DeltaEvent(
                    delta=delta, summary=_delta_summary(delta))
            elif kind == "decision":
                decision = _decision_from_dict(body["decision"])
            else:
                raise JournalIntegrityError(f"unknown event kind {kind!r}")
            events.append(Event(
                index=int(row["index"]), kind=str(kind),
                prev_hash=str(row["prev_hash"]),
                event_hash=str(row["event_hash"]),
                base=base, delta=delta_event, decision=decision))
        journal = cls(tuple(events))
        journal.verify()   # a loaded journal must be intact (fail-closed)
        return journal

    # -- equality -----------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BuildingJournal):
            return NotImplemented
        return self._events == other._events

    def __hash__(self) -> int:  # pragma: no cover
        return hash(tuple(e.event_hash for e in self._events))


# ---------------------------------------------------------------------------
# Convenience API
# ---------------------------------------------------------------------------


def new_journal(base: TreeNode | BuildingState | None = None) -> BuildingJournal:
    """Create a journal from a base tree, base state, or empty."""

    if base is None:
        return BuildingJournal.new()
    if isinstance(base, BuildingState):
        return BuildingJournal.new(base)
    return BuildingJournal.new(BuildingState.of_tree(base))


def commit_delta(
    journal: BuildingJournal, delta: DeltaProgram,
) -> BuildingJournal:
    """Append a delta (must be applicable to head)."""

    return journal.append_delta(delta)


def commit_trees(
    journal: BuildingJournal, prev_tree: TreeNode, new_tree: TreeNode,
) -> BuildingJournal:
    """Commit the edit prev_tree -> new_tree.

    ``prev_tree`` must reproduce the current head state, else the commit is not
    from the journal's head and is refused (fail-closed).
    """

    if BuildingState.of_tree(prev_tree) != journal.head_state():
        raise JournalRevisionError(
            "prev_tree does not match the journal head state")
    return journal.append_delta(delta_between(prev_tree, new_tree))


def replay(journal: BuildingJournal, revision: int) -> BuildingState:
    return journal.state_at(revision)


def undo(journal: BuildingJournal) -> tuple[BuildingState, int]:
    return journal.undo()


def audit(journal: BuildingJournal) -> tuple[tuple[int, DeltaEvent], ...]:
    return journal.audit()


__all__ = [
    "BaseSnapshot",
    "BuildingJournal",
    "DECISION_MODES",
    "DecisionEvent",
    "DeltaEvent",
    "Event",
    "JOURNAL_VERSION",
    "JournalDecisionError",
    "JournalError",
    "JournalIntegrityError",
    "JournalRevisionError",
    "audit",
    "commit_delta",
    "commit_trees",
    "journal_enabled",
    "new_journal",
    "replay",
    "undo",
]
