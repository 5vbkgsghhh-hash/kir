"""Unreachable offline AP-01 model wire contract and capability discovery."""
from .contracts import (
    CAPABILITIES_TOOL,
    DECLARED_TOOL_NAMES,
    PROTOCOL_VERSION,
    CoverageV0,
    ProtocolErrorV0,
    ReadReceiptV0,
    ToolRequestV0,
    ToolResponseV0,
)
from .errors import (
    AiProtocolError,
    ProtocolContractError,
    WireDecodeError,
    WireShapeError,
)
from .registry import (
    CAPABILITY_REGISTRY,
    PUBLISH_NOT_AVAILABLE_BEFORE_SRV1,
    CapabilityRegistryV0,
)
from .wire import (
    decode_request,
    decode_response,
    encode_response,
    handle_request,
    handle_wire_request,
)


__all__ = [
    "AiProtocolError",
    "CAPABILITIES_TOOL",
    "CAPABILITY_REGISTRY",
    "CapabilityRegistryV0",
    "CoverageV0",
    "DECLARED_TOOL_NAMES",
    "PROTOCOL_VERSION",
    "PUBLISH_NOT_AVAILABLE_BEFORE_SRV1",
    "ProtocolContractError",
    "ProtocolErrorV0",
    "ReadReceiptV0",
    "ToolRequestV0",
    "ToolResponseV0",
    "WireDecodeError",
    "WireShapeError",
    "decode_request",
    "decode_response",
    "encode_response",
    "handle_request",
    "handle_wire_request",
]
