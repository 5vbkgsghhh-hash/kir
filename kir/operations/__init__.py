"""Durable operation identity and lifecycle for Revit side effects.

This package is deliberately independent from the LLM/tool implementation.  A
chat turn may be retried, a provider stream may fail and a WebSocket may
reconnect, but an operation keeps the same identity and lifecycle.
"""

from .protocol import (
    PROTOCOL_VERSION,
    OperationIdentity,
    OperationOutcome,
    OperationPhase,
    canonical_payload_hash,
    derive_action_id,
    derive_operation_id,
    is_terminal_phase,
    transition_allowed,
)

__all__ = [
    "PROTOCOL_VERSION",
    "OperationIdentity",
    "OperationOutcome",
    "OperationPhase",
    "canonical_payload_hash",
    "derive_action_id",
    "derive_operation_id",
    "is_terminal_phase",
    "transition_allowed",
]
