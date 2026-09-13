# -*- coding: utf-8 -*-
"""The window wait in tests — ZERO by default.

Task #26 taught extraction to wait for the window's return: when a page's
retries are exhausted, the loop pauses and retries until the bridge comes
back or the run's overall budget runs out (``EXTRACT_WINDOW_WAIT_S``, the
production value is 300 s). In production this is correct — a dead window
costs five minutes exactly once per run, and that is cheaper than throwing
away the extraction of the whole model.

In tests, each run is its own, and any test that DELIBERATELY exhausts the
retry budget (``timeout_probe_for`` in test_extract/test_pipeline) would end
up waiting those five minutes for nothing: the suite stopped fitting into
its allotted time (measured: the decompile suite went from ~190 s to 550 s
and was killed).

That is why the budget is zeroed here — the clock is not being checked, the
logic is.

A TEST THAT CHECKS THE WAIT ITSELF MUST RESTORE THE BUDGET EXPLICITLY:
``mock.patch.multiple(extract, EXTRACT_WINDOW_WAIT_S=..., ...)`` —
see ``test_extract_outage.py``. Zeroing here mutes the CLOCK, not the
behavior: every waiting branch is covered there, with millisecond pauses.
"""
from __future__ import annotations

import pytest

from kir.decompile import extract as _extract


@pytest.fixture(autouse=True)
def _no_wall_clock_window_wait(monkeypatch):
    monkeypatch.setattr(_extract, "EXTRACT_WINDOW_WAIT_S", 0.0)
    monkeypatch.setattr(_extract, "EXTRACT_WINDOW_POLL_S", 0.0)
    # RETRY pauses (production 5 and 20 s) are NOT touched: they have their
    # own guard, dcf86ca7 (RetryBackoffWaitsForTheBridgeToComeBack), and
    # muting someone else's test subject for the sake of our own speed is a
    # bad trade. What is muted here is exactly what this wave added.
