"""Bridge timeout ceiling — the hot execute path must fail FAST, not hang 75 min.

Regression for the 2026-07-08 "бесконечное ожидание": an execute whose Revit bridge
never answered sat on BRIDGE_REQUEST_TIMEOUT=4500s (75 min). execute is now hard-capped.
"""
from __future__ import annotations

import kukai.api.chat_ws as cw


def test_execute_is_hard_capped():
    assert cw._effective_bridge_timeout("execute", {}) == cw._EXECUTE_BRIDGE_TIMEOUT_S
    # even a huge propagated timeout_ms cannot lift the execute cap (min wins)
    assert cw._effective_bridge_timeout("execute", {"timeout_ms": 9_000_000}) == cw._EXECUTE_BRIDGE_TIMEOUT_S


def test_execute_shorter_timeout_ms_still_honored():
    # a SHORTER explicit budget for execute is respected (5s+10 buffer = 15s < 200)
    assert cw._effective_bridge_timeout("execute", {"timeout_ms": 5000}) == 15.0


def test_non_execute_keeps_legacy_ceiling():
    assert cw._effective_bridge_timeout("export", {}) == cw.BRIDGE_REQUEST_TIMEOUT
    # explicit timeout_ms honored for non-execute methods (30s+10 buffer)
    assert cw._effective_bridge_timeout("export", {"timeout_ms": 30000}) == 40.0


def test_default_cap_is_sane():
    # operator-set 200s default — never the 75-min legacy value
    assert cw._EXECUTE_BRIDGE_TIMEOUT_S <= 600
