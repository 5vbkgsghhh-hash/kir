"""Projection base — generic reducer pattern over EventLog.

Per spec Section 9.2. A projection is a derived view of state computed
by folding a reducer over the event log. Always rebuildable from log.
"""
from __future__ import annotations
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from kukai.modeling.schemas.events import EventBase
from kukai.modeling.state.event_log import EventLog


T = TypeVar("T", bound=BaseModel)


class Reducer(Protocol[T]):
    """A reducer applies one event to current state, returning new state."""

    def apply(self, state: T, event: EventBase) -> T: ...


class Projection(Generic[T]):
    """Generic projection wrapper. Folds a Reducer over EventLog."""

    def __init__(self, state_type: type[T], reducer: Reducer[T]):
        self._state_type = state_type
        self._reducer = reducer

    def rebuild(self, log: EventLog, from_state: T | None = None) -> T:
        """Compute projection state from the event log.

        If from_state provided, resumes from that point (incremental).
        Otherwise starts fresh from default-constructed state.
        """
        if from_state is None:
            state = self._state_type()
            from_sequence = 0
        else:
            state = from_state
            from_sequence = getattr(from_state, "last_event_sequence", -1) + 1

        for event in log.iter(from_sequence=from_sequence):
            state = self._reducer.apply(state, event)

        return state
