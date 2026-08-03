"""Bridge-busy classification — the 'Failed to raise ExternalEvent: Pending' storm.

Revit runs C# through ONE single-threaded ExternalEvent. When it's busy with a prior
op (or stuck Pending after a cancel/timeout), the bridge returns "Failed to raise
ExternalEvent: Pending". That is NOT a code fault — misclassifying it as one sent the
model off repairing perfectly-good code and left the user with a silent "пусто"
(observed live 2026-07-08). It must classify as transport.bridge_busy and surface
honest, actionable text.
"""
from __future__ import annotations

from kukai.llm.envelope import (
    ERR_PROPS,
    ErrCode,
    classify_bridge_error,
    friendly_bridge_message,
)


def test_external_event_pending_classifies_as_bridge_busy():
    for msg in (
        "Execution error: Failed to raise ExternalEvent: Pending",
        "Failed to raise ExternalEvent: Pending",
        "Context collection failed: Failed to raise ExternalEvent: Pending",
    ):
        assert classify_bridge_error(msg) == ErrCode.TRANSPORT_BRIDGE_BUSY, msg


def test_bridge_busy_is_transient_not_code_repair():
    retryable, transient = ERR_PROPS[ErrCode.TRANSPORT_BRIDGE_BUSY]
    # transient=True ⇒ the SAME code is resent after a wait, never sent to code-repair
    assert retryable is True and transient is True


def test_friendly_message_is_actionable_not_raw_internals():
    friendly = friendly_bridge_message(
        ErrCode.TRANSPORT_BRIDGE_BUSY,
        "Execution error: Failed to raise ExternalEvent: Pending",
    )
    assert "ExternalEvent" not in friendly            # no leaked internals
    assert "Revit" in friendly and "перезапус" in friendly.lower()


def test_other_errors_are_untouched():
    cs = "error CS0246: type or namespace not found"
    assert classify_bridge_error(cs) == ErrCode.COMPILE_CS_ERROR
    assert friendly_bridge_message(ErrCode.COMPILE_CS_ERROR, cs) == cs      # unchanged
    assert classify_bridge_error("Object reference not set") == ErrCode.RUNTIME_REVIT_EXCEPTION
    assert classify_bridge_error("Bridge not connected") == ErrCode.TRANSPORT_BRIDGE_DISCONNECTED
