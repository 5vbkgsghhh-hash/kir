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
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from kukai.ir.decompile.fold import TreeNode
from kukai.ir.decompile.rebuild import (
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


class JournalRevisionError(JournalError):
    """A revision is out of range, or a commit is not applicable to head."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def journal_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return os.getenv("KUKAI_IR_JOURNAL", "").strip().lower() in {
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


@dataclass(frozen=True, slots=True)
class Event:
    index: int
    kind: str            # "base" | "delta"
    prev_hash: str
    event_hash: str
    base: BaseSnapshot | None
    delta: DeltaEvent | None


def _event_payload(
    kind: str, base: BaseSnapshot | None, delta: DeltaEvent | None,
) -> dict[str, Any]:
    if kind == "base":
        assert base is not None
        return {"kind": "base", "state": _state_to_dict(base.state)}
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
        delta_event = DeltaEvent(delta=delta, summary=_delta_summary(delta))
        payload = _event_payload("delta", None, delta_event)
        prev_hash = self._events[-1].event_hash
        event = Event(
            index=len(self._events), kind="delta", prev_hash=prev_hash,
            event_hash=_chain_hash(prev_hash, payload),
            base=None, delta=delta_event)
        return BuildingJournal(self._events + (event,))

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
            payload = _event_payload(event.kind, event.base, event.delta)
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
                        event.kind, event.base, event.delta),
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
            if kind == "base":
                base = BaseSnapshot(state=_state_from_dict(body["state"]))
            elif kind == "delta":
                delta = _delta_from_dict(body["delta"])
                delta_event = DeltaEvent(
                    delta=delta, summary=_delta_summary(delta))
            else:
                raise JournalIntegrityError(f"unknown event kind {kind!r}")
            events.append(Event(
                index=int(row["index"]), kind=str(kind),
                prev_hash=str(row["prev_hash"]),
                event_hash=str(row["event_hash"]),
                base=base, delta=delta_event))
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
    "DeltaEvent",
    "Event",
    "JOURNAL_VERSION",
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
