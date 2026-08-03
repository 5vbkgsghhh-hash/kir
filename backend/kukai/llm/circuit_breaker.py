"""Circuit breaker for LLM providers.

States:
  CLOSED  — normal operation, requests go to primary
  OPEN    — primary is down, all requests go to fallback
  HALF_OPEN — testing primary with one request

Triggers:
  CLOSED → OPEN:  N consecutive failures OR avg response > threshold
  OPEN → HALF_OPEN:  after cooldown period
  HALF_OPEN → CLOSED: probe succeeds
  HALF_OPEN → OPEN:   probe fails (longer cooldown)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from enum import Enum
from typing import NamedTuple

logger = logging.getLogger(__name__)


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RequestRecord(NamedTuple):
    timestamp: float
    duration: float
    success: bool


class CircuitBreaker:
    """Circuit breaker for unreliable LLM providers."""

    def __init__(
        self,
        failure_threshold: int = 3,
        slow_threshold_s: float = 15.0,
        window_size: int = 5,
        cooldown_s: float = 120.0,
        cooldown_escalation: float = 2.5,
        max_cooldown_s: float = 600.0,
    ):
        self._failure_threshold = failure_threshold
        self._slow_threshold_s = slow_threshold_s
        self._window_size = window_size
        self._base_cooldown_s = cooldown_s
        self._cooldown_escalation = cooldown_escalation
        self._max_cooldown_s = max_cooldown_s

        self._state = State.CLOSED
        self._records: deque[RequestRecord] = deque(maxlen=window_size)
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._current_cooldown_s = cooldown_s

    @property
    def state(self) -> State:
        if self._state == State.OPEN:
            if time.time() - self._opened_at >= self._current_cooldown_s:
                self._state = State.HALF_OPEN
                logger.info("Circuit breaker: OPEN -> HALF_OPEN (cooldown expired)")
        return self._state

    def should_use_fallback(self) -> bool:
        return self.state == State.OPEN

    def allow_probe(self) -> bool:
        return self.state == State.HALF_OPEN

    def record_success(self, duration: float) -> None:
        self._records.append(RequestRecord(time.time(), duration, True))
        self._consecutive_failures = 0
        if self._state == State.HALF_OPEN:
            self._state = State.CLOSED
            self._current_cooldown_s = self._base_cooldown_s
            logger.info("Circuit breaker: HALF_OPEN -> CLOSED (probe succeeded)")
        self._maybe_open_slow()

    def record_failure(self, duration: float) -> None:
        self._records.append(RequestRecord(time.time(), duration, False))
        self._consecutive_failures += 1
        if self._state == State.HALF_OPEN:
            self._current_cooldown_s = min(
                self._current_cooldown_s * self._cooldown_escalation,
                self._max_cooldown_s,
            )
            self._state = State.OPEN
            self._opened_at = time.time()
            logger.warning("Circuit breaker: HALF_OPEN -> OPEN (probe failed, cooldown=%.0fs)", self._current_cooldown_s)
            return
        if self._state == State.CLOSED:
            if self._consecutive_failures >= self._failure_threshold:
                self._open("consecutive failures")

    def _maybe_open_slow(self) -> None:
        """Step 9: open when recent SUCCESSFUL responses are slow on average
        (degraded-but-working). Runs in record_success so the success window can
        actually fill — the old placement in record_failure was unreachable (a
        just-appended failure left <window_size successes in the maxlen deque)."""
        if self._state != State.CLOSED:
            return
        recent = [r for r in self._records if r.success]
        if len(recent) >= self._window_size:
            avg = sum(r.duration for r in recent) / len(recent)
            if avg > self._slow_threshold_s:
                self._open(f"avg response {avg:.1f}s > {self._slow_threshold_s}s")

    def _open(self, reason: str) -> None:
        self._state = State.OPEN
        self._opened_at = time.time()
        logger.warning("Circuit breaker: CLOSED -> OPEN (%s, cooldown=%.0fs)", reason, self._current_cooldown_s)

    def reset(self) -> None:
        self._state = State.CLOSED
        self._consecutive_failures = 0
        self._current_cooldown_s = self._base_cooldown_s
        self._records.clear()
