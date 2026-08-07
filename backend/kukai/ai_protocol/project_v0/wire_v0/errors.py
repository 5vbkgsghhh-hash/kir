"""Typed failures for the isolated AP02-W offline wire boundary."""
from __future__ import annotations

from typing import Any


class ProjectWireError(ValueError):
    """Base class for deterministic AP02-W contract and codec failures."""

    code = "PROJECT_WIRE_ERROR"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code


class WireContractError(ProjectWireError):
    code = "WIRE_CONTRACT_INVALID"


class WireDecodeError(ProjectWireError):
    code = "WIRE_DECODE_INVALID"


class WireShapeError(ProjectWireError):
    code = "WIRE_SHAPE_INVALID"


class WireEncodeError(ProjectWireError):
    code = "WIRE_ENCODE_INVALID"


class AddressableRequestError(ProjectWireError):
    """A refused request whose exact request_id and declared tool are known."""

    code = "ADDRESSABLE_REQUEST_REFUSED"

    def __init__(
        self,
        message: str,
        *,
        request_id: str,
        tool: str,
        refusal_code: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, code=refusal_code)
        self.request_id = request_id
        self.tool = tool
        self.details = {} if details is None else dict(details)


__all__ = [
    "AddressableRequestError",
    "ProjectWireError",
    "WireContractError",
    "WireDecodeError",
    "WireEncodeError",
    "WireShapeError",
]
