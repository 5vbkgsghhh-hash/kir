"""Event schemas for the event-sourced state log.

Per spec Section 9.1. Every state transition emits an Event written
append-only to history.jsonl. Projections derive from these events.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    """All event types in the modeling engine. Stable identifiers."""

    # Lifecycle
    PROJECT_CREATED = "project.created"
    BRIEF_INGESTED = "brief.ingested"
    BRIEF_LINTED = "brief.linted"

    # Phases
    PHASE_STARTED = "phase.started"
    PHASE_PLAN_GENERATED = "phase.plan_generated"
    PHASE_COMPLETED = "phase.completed"

    # Per-task lineage
    TASK_DISPATCHED = "task.dispatched"
    RESOLVER_INVOKED = "resolver.invoked"
    CODE_PROPOSED = "code.proposed"
    CODE_REVIEW_RESULT = "code.review_result"
    COMPILE_RESULT = "compile.result"
    EXECUTION_RESULT = "execution.result"
    ELEMENT_CREATED = "element.created"
    ELEMENT_FAILED = "element.failed"

    # QC
    GATE_EVALUATED = "gate.evaluated"
    QC_FINDING = "qc.finding"
    REPAIR_PLAN_GENERATED = "repair.plan_generated"
    REGRESSION_CHECK = "regression.check"

    # System
    CASCADE_DETECTED = "cascade.detected"
    FOREMAN_CALIBRATION_DRIFT = "foreman.calibration_drift"
    USER_INTERVENTION_REQUESTED = "user.intervention_requested"
    USER_INTERVENTION_RESOLVED = "user.intervention_resolved"
    SYSTEM_PAUSE = "system.pause"
    SYSTEM_RESUME = "system.resume"
    COST_BREACH = "cost.breach"


class EventBase(BaseModel):
    """Envelope for every event in the log.

    payload schema depends on event_type — validated by reducers, not here,
    to keep the log flexibly extensible.
    """
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., description="uuid4 unique to this event")
    timestamp: datetime = Field(..., description="UTC timestamp of event")
    sequence: int = Field(..., ge=0, description="monotonic per project")
    correlation_id: str = Field(..., description="lineage: task/phase identifier")
    causation_id: str | None = Field(None, description="parent event_id that triggered this")
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
