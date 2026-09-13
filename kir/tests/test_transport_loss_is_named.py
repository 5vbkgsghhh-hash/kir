"""LOSS OF CONNECTION IS NOT AN "INTERNAL ERROR". A refusal must name its cause.

THE TRIGGER WAS MEASURED LIVE (03.08.2026): the bridge tore **4571 times in 2 hours 45 minutes**
(`close_code=1006`), and the KIR handlers responded to this with a flat refusal
`"internal"`, which the `_FLAT_ERROR_TO_ERRCODE` table translates into
`internal.unhandled`. And this code carries `(retryable=False, transient=False)`
in `ERR_PROPS`.

WHAT THIS MEANS IN PRACTICE. The models are told: "this is our own internal breakage, retrying is
pointless" — at the exact moment the truth is the opposite: the connection dropped,
and a retry in a couple of seconds would work. The model drops the task, the operator sees
"KUKAI is broken", when it was the wire that broke. And the code that was NEEDED has been in the
taxonomy from the very start — `transport.bridge_disconnected`, marked
`(retryable=True, transient=True)` — but nobody ever routed the exception to it.

WHY THIS CAN ONLY BE CAUGHT THIS WAY. `classify_bridge_error` parses the bridge's PROSE and
works when the bridge HAS ANSWERED. A torn socket brings no prose: it arrives
AS AN EXCEPTION, bypasses the classifier entirely, and falls into the general `except Exception`.
So what must be checked is not the text, but the type of the exception.

THE BOUNDARY THIS TEST ALSO GUARDS: the reclassification must be
NARROW. A genuine internal error (`KeyError`, `TypeError`, `ValueError`)
named as transport would send the model to retry a program that is
broken deterministically — that is, it would swap one lie for another. The default
refusal remains `internal`.
"""
from __future__ import annotations

import asyncio

import pytest

from kir.serving import (
    _FLAT_ERROR_TO_ERRCODE, _failure_stage, _transport_stage)
from kir.envelope import ERR_PROPS, ErrCode


class _FakeConnectionClosed(Exception):
    """A stand-in for `websockets.exceptions.ConnectionClosed`.

    The real class lives in a third-party package, and tying the KIR core to
    importing it would mean getting an `ImportError` in an environment without websockets. Recognition
    goes BY THE CLASS NAME — the same technique `_transport_stage` uses in
    production, so the stand-in exercises exactly the same path as a real disconnect.
    """

    __name__ = "ConnectionClosed"


_FakeConnectionClosed.__name__ = "ConnectionClosed"


class _FakeConnectionClosedError(Exception):
    pass


_FakeConnectionClosedError.__name__ = "ConnectionClosedError"


DISCONNECTS = [
    ConnectionResetError("[Errno 104] Connection reset by peer"),
    BrokenPipeError("[Errno 32] Broken pipe"),
    ConnectionAbortedError("software caused connection abort"),
    ConnectionError("bridge socket is gone"),
    _FakeConnectionClosed("received 1006 (abnormal closure)"),
    _FakeConnectionClosedError("no close frame received or sent"),
]

TIMEOUTS = [
    asyncio.TimeoutError(),
    TimeoutError("bridge did not answer in time"),
]

GENUINELY_INTERNAL = [
    KeyError("op_id"),
    TypeError("unsupported operand"),
    ValueError("bad literal"),
    AttributeError("'NoneType' object has no attribute 'id'"),
    ZeroDivisionError("division by zero"),
]


@pytest.mark.parametrize("exc", DISCONNECTS, ids=lambda e: type(e).__name__)
def test_a_dead_socket_is_named_a_dead_socket(exc: Exception) -> None:
    """A dropped connection is recognized by the type of the exception, not by text."""
    assert _transport_stage(exc) == "bridge_disconnected", (
        f"{type(exc).__name__} — это потеря связи, а не внутренняя ошибка; "
        "модели скажут «не повторяй» там, где повтор и есть лекарство")


@pytest.mark.parametrize("exc", TIMEOUTS, ids=lambda e: type(e).__name__)
def test_a_silent_bridge_is_named_a_timeout(exc: Exception) -> None:
    assert _transport_stage(exc) == "bridge_timeout"


@pytest.mark.parametrize("exc", GENUINELY_INTERNAL, ids=lambda e: type(e).__name__)
def test_a_real_bug_stays_internal(exc: Exception) -> None:
    """The narrowness of the boundary is half the rule's value.

    Calling a `KeyError` transport means sending the model to retry a
    deterministically broken program. One lie would be replaced by another.
    """
    assert _transport_stage(exc) is None, (
        f"{type(exc).__name__} — настоящий дефект, и он обязан остаться "
        "internal: повтор его не вылечит")


def test_the_named_stages_reach_the_right_taxonomy_codes() -> None:
    """A stage name is useless if the table does not carry it through to a code."""
    assert _FLAT_ERROR_TO_ERRCODE["bridge_disconnected"] is (
        ErrCode.TRANSPORT_BRIDGE_DISCONNECTED)
    assert _FLAT_ERROR_TO_ERRCODE["bridge_timeout"] is (
        ErrCode.TRANSPORT_BRIDGE_TIMEOUT)


def test_the_whole_point_is_the_retry_flag() -> None:
    """WHAT IT IS ALL FOR: transport codes ALLOW a retry, `internal` does not.

    This test is not about names, but about the behavior the names switch on. If
    `transport.*` ever stops being retryable, the rule loses its
    meaning, and it must fail here, not on a live bridge.
    """
    for code in (ErrCode.TRANSPORT_BRIDGE_DISCONNECTED,
                 ErrCode.TRANSPORT_BRIDGE_TIMEOUT):
        retryable, transient = ERR_PROPS[code]
        assert retryable and transient, (
            f"{code.value} обязан быть retryable+transient — иначе "
            "переименование ничего не меняет для модели")
    assert ERR_PROPS[ErrCode.INTERNAL_UNHANDLED] == (False, False)


def test_a_chained_cause_is_still_seen() -> None:
    """A disconnect wrapped inside someone else's exception must be found.

    The live path requires this: `run_decompile` wraps a transport failure in its own
    RuntimeError, and without walking the `__cause__` chain, the rule would fire only
    on a bare exception — that is, almost never.
    """
    inner = ConnectionResetError("[Errno 104] Connection reset by peer")
    outer = RuntimeError("decompile stage failed")
    outer.__cause__ = inner
    assert _transport_stage(outer) == "bridge_disconnected"


def test_a_real_bug_keeps_its_exact_old_message() -> None:
    """Byte-for-byte stability of the honest path.

    The rule adds a branch, it does not rewrite behavior: a genuine internal
    error must respond with VERBATIM the same thing it responded with before the fix, otherwise
    "we broke nothing" is a promise, not a fact.
    """
    for what in ("декомпайла", "rebuild", "идемпотентности"):
        assert _failure_stage(KeyError("op"), what) == (
            "internal", f"внутренняя ошибка {what}")


def test_the_user_is_told_what_to_do_not_just_what_broke() -> None:
    """A refusal must carry an action, otherwise it is useless to the reader."""
    stage, message = _failure_stage(ConnectionResetError(104), "rebuild")
    assert stage == "bridge_disconnected"
    assert "повтори" in message
    # The main thing for trust: to say that the model did NOT suffer.
    assert "не изменялась" in message


def test_the_search_through_causes_is_bounded() -> None:
    """The chain of causes must not become an infinite loop.

    A self-referencing exception is not a fabrication: it arises from a repeated
    `raise ... from ...` inside a recovery loop. The traversal must terminate.
    """
    loop_exc = RuntimeError("boom")
    loop_exc.__cause__ = loop_exc
    assert _transport_stage(loop_exc) is None
