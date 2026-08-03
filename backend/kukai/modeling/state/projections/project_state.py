"""ProjectState projection — current phase, status, counts."""
from __future__ import annotations
from pydantic import BaseModel, Field

from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.schemas.tasks import Phase


class ProjectState(BaseModel):
    """Current project status. Lightweight; for Foreman & dashboard."""
    last_event_sequence: int = -1
    current_phase: Phase = Phase.SETUP
    elements_placed: int = 0
    elements_failed: int = 0
    cost_consumed_usd: float = 0.0
    user_intervention_required: bool = False
    user_intervention_reason: str | None = None


class ProjectStateReducer:
    """Maps events to ProjectState mutations."""

    def apply(self, state: ProjectState, event: EventBase) -> ProjectState:
        match event.event_type:
            case EventType.PHASE_STARTED:
                phase_str = event.payload.get("phase", "setup")
                return state.model_copy(update={
                    "current_phase": Phase(phase_str),
                    "last_event_sequence": event.sequence,
                })
            case EventType.ELEMENT_CREATED:
                return state.model_copy(update={
                    "elements_placed": state.elements_placed + 1,
                    "last_event_sequence": event.sequence,
                })
            case EventType.ELEMENT_FAILED:
                return state.model_copy(update={
                    "elements_failed": state.elements_failed + 1,
                    "last_event_sequence": event.sequence,
                })
            case EventType.USER_INTERVENTION_REQUESTED:
                return state.model_copy(update={
                    "user_intervention_required": True,
                    "user_intervention_reason": event.payload.get("reason"),
                    "last_event_sequence": event.sequence,
                })
            case EventType.USER_INTERVENTION_RESOLVED:
                return state.model_copy(update={
                    "user_intervention_required": False,
                    "user_intervention_reason": None,
                    "last_event_sequence": event.sequence,
                })
            case _:
                # No projection change for other event types
                return state.model_copy(update={
                    "last_event_sequence": event.sequence,
                })
