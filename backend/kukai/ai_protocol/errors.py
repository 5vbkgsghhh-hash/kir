"""Typed refusals for the isolated AP-01 model wire boundary."""
from __future__ import annotations


class AiProtocolError(ValueError):
    """Base class for an offline protocol contract or admission refusal."""

    code = "AI_PROTOCOL_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ProtocolContractError(AiProtocolError):
    """A programmatic AP-01 value violates its closed immutable contract."""

    code = "PROTOCOL_CONTRACT_INVALID"


class WireDecodeError(AiProtocolError):
    """Wire bytes are not strict canonical-input JSON."""

    code = "WIRE_INVALID_JSON"


class WireShapeError(AiProtocolError):
    """Decoded JSON does not match the exact AP-01 request shape."""

    code = "WIRE_SHAPE_INVALID"


__all__ = [
    "AiProtocolError",
    "ProtocolContractError",
    "WireDecodeError",
    "WireShapeError",
]
