"""Step 9 — resilient per-provider chain for OpenRouter routing (flag-gated).

Why this exists
---------------
On 2026-07-03 prod hard-failed with "ИИ-сервис недоступен". The static
OpenRouter provider pin (``client._OR_PROVIDER``) rotted: Novita started
returning 404 "No endpoints found for deepseek/deepseek-v4-flash" and
AtlasCloud 400 "invalid request params". The pin has no memory — every request
kept slamming the same dead providers — and the legacy fallback chain
collapsed onto the SAME rotted pin (its "emergency" layer re-hits it), so the
whole service converged on one dead point. Providers on OpenRouter rotate;
this WILL recur.

What this module does
---------------------
Gives every pinned provider its own health breaker, keyed by ERROR CLASS:

* DETERMINISTIC — 404 "no endpoints" / 400 "invalid params": the provider
  cannot serve this model right now; retrying in seconds is pointless.
  Long cooldown (minutes).
* TRANSIENT — timeout / 429 / 5xx: worth retrying soon. Short cooldown.
* ACCOUNT — 401/402/403/quota: likely account-level. Longest cooldown.
* UNKNOWN — unclassifiable: treated like TRANSIENT.

``live_order()`` returns the configured candidate order MINUS providers in
DOWN cooldown. A DOWN provider whose cooldown expired is offered back at its
ORIGINAL position for exactly ONE probe per claim window (half-open), so a
recovered provider self-heals into the rotation without a stampede. If a probe
fails, its cooldown escalates.

Hardening (2026-07-04, F1+F2)
-----------------------------
F1 — request-fault vs provider-fault. A malformed REQUEST (e.g. an
orphaned-tool-call session) 400s on EVERY provider; naively recording those as
provider failures poisons the whole chain for ALL tenants on one bad request.
``begin_request()`` returns a :class:`RequestScope` that STAGES
request-suspect failures (400/422 with no provider-specific marker) instead of
applying them, then resolves by corroboration:

* the request later succeeds on another provider → the request was fine, the
  staged failures WERE provider faults → committed (2026-07-03 AtlasCloud
  protection preserved);
* the rotation ends with the same suspect failure on ≥2 DIFFERENT providers →
  the request itself is at fault → all staged failures are forgiven;
* a single uncorroborated suspect failure → committed (legacy behavior).

Provider-specific failures (404 no-endpoints, timeouts, 5xx, auth) are applied
immediately, exactly as before. 404 "no endpoints" stays DETERMINISTIC.

F2 — per-provider SLOW signal. ``record_success`` accepts the response
duration; a rolling window (mirror of ``CircuitBreaker._maybe_open_slow``:
window full ⇒ average > threshold) marks a provider SLOW for a TTL, and
``live_order()`` moves SLOW providers to the END of the order instead of
dropping them. Demotion-not-removal makes this strictly safe: availability is
unchanged (all-slow ⇒ original order), a slow provider still serves when
everything faster is down, and the TTL guarantees stale slowness decays.

Consulted ONLY when ``KUKAI_PROVIDER_CHAIN=1`` — see
``LLMClient._call_llm_with_fallback_inner`` /
``LLMClient._call_llm_with_provider_chain`` in ``kukai/llm/client.py``.
The legacy (flag-OFF) request path never constructs this class.

Design notes
------------
* ``allow_fallbacks`` is NEVER set to True by callers of this module — the
  chain only shrinks/rotates the pinned ``order`` (Baidu-garbage lesson,
  2026-06-04).
* All timing goes through an injectable ``clock`` (default
  ``time.monotonic``) so cooldown logic is unit-testable without sleeps.
* Single-process/asyncio use: methods contain no awaits, so no locking is
  needed (same concurrency model as kukai.llm.circuit_breaker).
* ``classify_provider_error`` is deliberately paranoid: litellm exception
  shapes vary (status_code attr, .message, plain strings) and the classifier
  must NEVER raise — worst case it returns UNKNOWN.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)


class ErrorClass(str, Enum):
    DETERMINISTIC = "deterministic"  # 404 no-endpoints / 400 invalid params
    TRANSIENT = "transient"          # timeout / 429 / 5xx
    ACCOUNT = "account"              # auth / payment / quota
    UNKNOWN = "unknown"              # unclassifiable — treated as transient


# Exception CLASS-NAME fragments → class. Checked when no usable status code is
# present (litellm exception names carry signal: RateLimitError, NotFoundError,
# AuthenticationError, ServiceUnavailableError, Timeout, ...).
_TYPE_NAME_RULES: tuple[tuple[tuple[str, ...], ErrorClass], ...] = (
    (("timeout",), ErrorClass.TRANSIENT),
    (("ratelimit",), ErrorClass.TRANSIENT),
    (("serviceunavailable", "internalserver", "apiconnection"), ErrorClass.TRANSIENT),
    (("notfound",), ErrorClass.DETERMINISTIC),
    (("badrequest", "invalidrequest", "unprocessable"), ErrorClass.DETERMINISTIC),
    (("authentication", "permissiondenied", "budgetexceeded"), ErrorClass.ACCOUNT),
)

# Message fragments → class (lowercase substring match). Deterministic
# model/endpoint defects first (the 2026-07-03 shapes), then account, then
# transient, then generic invalid-request.
_MESSAGE_RULES: tuple[tuple[tuple[str, ...], ErrorClass], ...] = (
    (
        ("no endpoints", "model not found", "not found for provider", "no allowed providers"),
        ErrorClass.DETERMINISTIC,
    ),
    (
        ("quota", "credit", "unauthorized", "forbidden", "api key", "payment required"),
        ErrorClass.ACCOUNT,
    ),
    (
        (
            "timeout", "timed out", "rate limit", "too many requests", "overloaded",
            "service unavailable", "bad gateway", "internal server error", "connection error",
        ),
        ErrorClass.TRANSIENT,
    ),
)


def _extract_status_code(error: object) -> Optional[int]:
    """Best-effort HTTP status extraction from litellm/OpenRouter exceptions."""
    for attr in ("status_code", "code"):
        try:
            value = getattr(error, attr, None)
        except Exception:
            continue
        if isinstance(value, bool):  # bool is int — never a status
            continue
        if isinstance(value, int) and 100 <= value <= 599:
            return value
        if isinstance(value, str) and value.isdigit():
            as_int = int(value)
            if 100 <= as_int <= 599:
                return as_int
    return None


def classify_provider_error(error: object) -> ErrorClass:
    """Classify a provider failure. Defensive: NEVER raises.

    Signal priority: timeout type → HTTP status → exception class name →
    message substrings → UNKNOWN.
    """
    try:
        # 1) Timeouts by type (asyncio.wait_for, litellm Timeout, httpx timeouts)
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return ErrorClass.TRANSIENT

        # 2) Explicit HTTP status
        status = _extract_status_code(error)
        if status is not None:
            if status == 404:
                return ErrorClass.DETERMINISTIC
            if status in (401, 402, 403):
                return ErrorClass.ACCOUNT
            if status in (408, 429) or 500 <= status <= 599:
                return ErrorClass.TRANSIENT
            if status in (400, 422):
                return ErrorClass.DETERMINISTIC

        # 3) Exception class name (litellm names are descriptive)
        if isinstance(error, BaseException):
            type_name = type(error).__name__.lower()
            for fragments, error_class in _TYPE_NAME_RULES:
                if any(f in type_name for f in fragments):
                    return error_class

        # 4) Message content (str() and .message can both lie or raise — guard)
        text = ""
        try:
            text = str(error)
        except Exception:
            text = ""
        try:
            message = getattr(error, "message", "")
            if isinstance(message, str):
                text = f"{message} {text}"
        except Exception:
            pass
        low = text.lower()
        if low:
            for fragments, error_class in _MESSAGE_RULES:
                if any(f in low for f in fragments):
                    return error_class
            if "invalid" in low and ("param" in low or "request" in low):
                return ErrorClass.DETERMINISTIC

        return ErrorClass.UNKNOWN
    except Exception:  # pragma: no cover — belt and braces
        return ErrorClass.UNKNOWN


# Error-message markers that pin a failure on the PROVIDER (not the request):
# these describe the provider's ability to serve the model at all. Their
# presence means a 400/404 is never "the request's fault".
_PROVIDER_SPECIFIC_MARKERS: tuple[str, ...] = (
    "no endpoints",
    "model not found",
    "not found for provider",
    "no allowed providers",
)


def is_request_suspect(error: object) -> bool:
    """True when a failure is PLAUSIBLY the request's fault (F1 guard input).

    A malformed request (e.g. a pre-Step6 orphaned-tool-call session) surfaces
    as 400/422 "invalid params" from EVERY provider it is sent to — the error
    shape carries no provider-specific marker, so ONE occurrence must not
    condemn a provider by itself. This predicate only flags the failure as
    *suspect*; attribution is decided by :class:`RequestScope` corroboration
    (same suspect error across ≥2 providers in one request ⇒ request-fault).

    404 / "no endpoints" / "model not found" style errors ARE
    provider-specific and are never request-suspect. Defensive: never raises.
    """
    try:
        status = _extract_status_code(error)
        if status == 404:
            return False

        text = ""
        try:
            text = str(error)
        except Exception:
            text = ""
        try:
            message = getattr(error, "message", "")
            if isinstance(message, str):
                text = f"{message} {text}"
        except Exception:
            pass
        low = text.lower()
        if any(m in low for m in _PROVIDER_SPECIFIC_MARKERS):
            return False

        if status in (400, 422):
            return True
        if status is None:
            if isinstance(error, BaseException):
                type_name = type(error).__name__.lower()
                if any(f in type_name for f in ("badrequest", "invalidrequest", "unprocessable")):
                    return True
            if low and "invalid" in low and ("param" in low or "request" in low):
                return True
        return False
    except Exception:  # pragma: no cover — belt and braces
        return False


@dataclass
class _ProviderHealth:
    """Mutable per-provider breaker record (internal)."""

    name: str
    state: str = "up"  # "up" | "down"
    last_error_class: Optional[ErrorClass] = None
    last_error: str = ""
    consecutive_failures: int = 0
    cooldown_until: float = 0.0        # clock() timestamp; 0 = none
    current_cooldown_s: float = 0.0    # last applied cooldown (escalation base)
    probe_claim_until: float = 0.0     # half-open probe claimed until this time
    # F2 — SLOW signal: rolling window of recent SUCCESS durations (maxlen is
    # rebound to the chain's slow_window_size in ProviderChain.__init__) and
    # the demotion TTL. slow_until > now ⇒ demoted to the END of live_order.
    success_durations: deque = field(default_factory=deque)
    slow_until: float = 0.0
    # F1 — observability: how many times this provider's request-suspect
    # failures were forgiven (attributed to the request, not the provider).
    forgiven_request_faults: int = 0


class ProviderChain:
    """Per-provider health breakers over an ordered OpenRouter candidate set.

    Public API:
      live_order()      -> list[str]  candidates minus DOWN, SLOW demoted last
                                      (claims half-open probes)
      full_order()      -> list[str]  the full configured candidate order
      begin_request()   -> RequestScope  per-request failure attribution (F1)
      record_success(p, duration_s=None) -> None  provider served; back UP;
                                      duration feeds the SLOW window (F2)
      record_failure(p, err) -> ErrorClass  classify + apply cooldown
      health()          -> dict[str, dict]  cheap read-only snapshot
    """

    def __init__(
        self,
        candidates: Sequence[str],
        *,
        transient_cooldown_s: float = 20.0,
        deterministic_cooldown_s: float = 300.0,
        account_cooldown_s: float = 900.0,
        unknown_cooldown_s: Optional[float] = None,
        cooldown_escalation: float = 2.0,
        max_cooldown_s: float = 1800.0,
        probe_claim_s: float = 120.0,
        # F1 — same-request-across-providers ⇒ don't poison (kill-switch:
        # KUKAI_CHAIN_REQUEST_FAULT_GUARD=0 via transport._get_provider_chain).
        request_fault_guard: bool = True,
        # F2 — slow-but-succeeding providers get demoted (never removed).
        # Threshold mirrors CircuitBreaker._maybe_open_slow (window average of
        # SUCCESS durations), but the default is tuned for this path's reality
        # (prod median ~38s): only pathological providers (~200s answers)
        # should trip it. Kill-switch: KUKAI_CHAIN_SLOW_DEMOTE=0.
        slow_demote: bool = True,
        slow_threshold_s: float = 60.0,
        slow_window_size: int = 3,
        slow_demote_s: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        # Preserve order, drop empties and duplicates.
        seen: set[str] = set()
        self._candidates: list[str] = []
        for raw in candidates or []:
            name = str(raw or "").strip()
            if name and name not in seen:
                self._candidates.append(name)
                seen.add(name)
        self._cooldowns: dict[ErrorClass, float] = {
            ErrorClass.DETERMINISTIC: deterministic_cooldown_s,
            ErrorClass.TRANSIENT: transient_cooldown_s,
            ErrorClass.ACCOUNT: account_cooldown_s,
            ErrorClass.UNKNOWN: (
                unknown_cooldown_s if unknown_cooldown_s is not None else transient_cooldown_s
            ),
        }
        self._escalation = cooldown_escalation
        self._max_cooldown_s = max_cooldown_s
        self._probe_claim_s = probe_claim_s
        self._request_fault_guard = bool(request_fault_guard)
        self._slow_demote = bool(slow_demote)
        self._slow_threshold_s = float(slow_threshold_s)
        self._slow_window_size = max(1, int(slow_window_size))
        self._slow_demote_s = float(slow_demote_s)
        self._clock = clock
        self._health: dict[str, _ProviderHealth] = {}
        for name in self._candidates:
            h = _ProviderHealth(name)
            # Rebind the duration window to the configured size (dataclass
            # default_factory cannot see chain config).
            h.success_durations = deque(maxlen=self._slow_window_size)
            self._health[name] = h

    # ── routing ──────────────────────────────────────────────────────────────

    def full_order(self) -> list[str]:
        """The full configured candidate order (desperation set)."""
        return list(self._candidates)

    def live_order(self) -> list[str]:
        """Candidate order minus providers in DOWN cooldown, SLOW demoted last.

        A DOWN provider whose cooldown has expired is offered back at its
        ORIGINAL position for exactly one probe per claim window (half-open);
        the claim is recorded here, so this method is a CONSUMING snapshot —
        concurrent callers within the claim window will not double-probe.

        F2: a provider marked SLOW (rolling success-duration average over the
        threshold, TTL not yet expired) is moved to the END of the order —
        demoted, NEVER removed. Availability is therefore unchanged: if every
        provider is slow the original order is preserved, and a slow provider
        still serves when everything ahead of it is down or failing.
        """
        now = self._clock()
        order: list[str] = []
        demoted: list[str] = []
        for name in self._candidates:
            h = self._health[name]
            bucket = demoted if h.slow_until > now else order
            if h.state == "up":
                bucket.append(name)
                continue
            if now >= h.cooldown_until and now >= h.probe_claim_until:
                h.probe_claim_until = now + self._probe_claim_s
                logger.info(
                    "ProviderChain: provider %s half-open — allowing one re-probe "
                    "(down for %s)", name,
                    h.last_error_class.value if h.last_error_class else "?",
                )
                bucket.append(name)
        return order + demoted

    # ── outcome recording ────────────────────────────────────────────────────

    def begin_request(self) -> "RequestScope":
        """F1 — open a per-request attribution scope.

        The transport rotation loop records outcomes through the returned
        scope instead of directly on the chain, so request-suspect failures
        (400/422 with no provider-specific marker) can be attributed by
        corroboration instead of poisoning every provider a bricked request
        touches. The scope is request-local: staging never mutates chain
        state, so concurrent requests cannot cross-contaminate.
        """
        return RequestScope(self, guard_enabled=self._request_fault_guard)

    def record_success(self, provider: str, duration_s: Optional[float] = None) -> None:
        """Provider served a request — restore it to full rotation.

        F2: when ``duration_s`` is given it feeds the provider's rolling
        SLOW window (see ``_maybe_mark_slow``). ``duration_s`` is optional so
        every pre-existing caller/test keeps its exact behavior.
        """
        h = self._health.get(provider)
        if h is None:
            return
        if h.state == "down":
            logger.info("ProviderChain: provider %s recovered (probe success) — back UP", provider)
        h.state = "up"
        h.consecutive_failures = 0
        h.cooldown_until = 0.0
        h.current_cooldown_s = 0.0
        h.probe_claim_until = 0.0
        h.last_error_class = None
        h.last_error = ""
        if duration_s is not None and self._slow_demote:
            try:
                h.success_durations.append(float(duration_s))
            except (TypeError, ValueError):
                return
            self._maybe_mark_slow(h)

    def _maybe_mark_slow(self, h: _ProviderHealth) -> None:
        """F2 — mirror of ``CircuitBreaker._maybe_open_slow`` per provider.

        Runs where success durations accumulate (record_success), exactly like
        the Step 9 CB fix: with a FULL window of recent successes averaging
        over the threshold, the provider is marked SLOW for ``slow_demote_s``
        (demoted to the end of live_order — never removed). A full window
        averaging under the threshold clears the mark immediately, so a
        recovered provider does not serve out a stale demotion. The TTL is
        refreshed only HERE (on new success evidence), never in live_order —
        a demoted provider that stops receiving traffic decays back to its
        original position when the TTL expires and is re-probed by real
        traffic before it can be re-marked.
        """
        if len(h.success_durations) < self._slow_window_size:
            return
        avg = sum(h.success_durations) / len(h.success_durations)
        now = self._clock()
        if avg > self._slow_threshold_s:
            was_slow = h.slow_until > now
            h.slow_until = now + self._slow_demote_s
            if not was_slow:
                logger.warning(
                    "ProviderChain: provider %s SLOW (avg %.1fs > %.1fs over last %d "
                    "successes) — de-prioritized for %.0fs (demoted, still live)",
                    h.name, avg, self._slow_threshold_s,
                    len(h.success_durations), self._slow_demote_s,
                )
        elif h.slow_until > now:
            h.slow_until = 0.0
            logger.info(
                "ProviderChain: provider %s fast again (avg %.1fs) — restored to "
                "original priority", h.name, avg,
            )

    def _forgive_request_fault(self, staged: Sequence[tuple[str, object]]) -> None:
        """F1 — the same suspect failure hit multiple providers in ONE request:
        attribute it to the REQUEST and leave every provider's health intact.
        Loud on purpose: this is the bricked-session signature ops must see."""
        names: list[str] = []
        for provider, _err in staged:
            h = self._health.get(provider)
            if h is not None:
                h.forgiven_request_faults += 1
            names.append(provider)
        sample = ""
        try:
            sample = str(staged[0][1])[:150]
        except Exception:
            sample = "<unprintable>"
        logger.warning(
            "ProviderChain: one request failed 400/422-style on %d providers (%s) "
            "— attributing to the REQUEST, providers NOT cooled: %s",
            len(names), ",".join(names), sample,
        )

    def record_failure(self, provider: str, error: object) -> ErrorClass:
        """Classify the failure and put the provider into DOWN cooldown.

        A failure while already DOWN (= a failed half-open probe) escalates the
        cooldown (×escalation, capped). Never raises; returns the error class
        so the caller can log/decide.
        """
        error_class = classify_provider_error(error)
        h = self._health.get(provider)
        if h is None:
            return error_class
        now = self._clock()
        base = self._cooldowns.get(error_class, self._cooldowns[ErrorClass.UNKNOWN])
        h.consecutive_failures += 1
        if h.state == "down":
            # Failed probe → escalate from whichever is larger: prior cooldown
            # or this error class's base.
            h.current_cooldown_s = min(
                max(h.current_cooldown_s, base) * self._escalation,
                self._max_cooldown_s,
            )
        else:
            h.state = "down"
            h.current_cooldown_s = base
        h.cooldown_until = now + h.current_cooldown_s
        h.probe_claim_until = 0.0
        h.last_error_class = error_class
        try:
            h.last_error = str(error)[:200]
        except Exception:
            h.last_error = f"<unprintable {type(error).__name__}>"
        logger.warning(
            "ProviderChain: provider %s DOWN (%s, cooldown=%.0fs, fails=%d): %s",
            provider, error_class.value, h.current_cooldown_s,
            h.consecutive_failures, h.last_error[:100],
        )
        return error_class

    # ── observability ────────────────────────────────────────────────────────

    def health(self) -> dict[str, dict[str, Any]]:
        """Cheap read-only snapshot for /health-style surfaces and logs."""
        now = self._clock()
        snapshot: dict[str, dict[str, Any]] = {}
        for name in self._candidates:
            h = self._health[name]
            durations = h.success_durations
            snapshot[name] = {
                "state": h.state,
                "last_error_class": h.last_error_class.value if h.last_error_class else None,
                "last_error": h.last_error,
                "consecutive_failures": h.consecutive_failures,
                "cooldown_s": h.current_cooldown_s,
                "cooldown_remaining_s": max(0.0, h.cooldown_until - now),
                # F2 — slow-signal observability
                "slow": h.slow_until > now,
                "slow_remaining_s": max(0.0, h.slow_until - now),
                "avg_success_s": (sum(durations) / len(durations)) if durations else None,
                # F1 — request-fault forgiveness counter
                "forgiven_request_faults": h.forgiven_request_faults,
            }
        return snapshot


class RequestScope:
    """F1 — per-request failure attribution over a :class:`ProviderChain`.

    Separates provider-fault from request-fault evidence within ONE request's
    provider rotation. Provider-specific failures (404 no-endpoints, timeouts,
    5xx, auth — anything not :func:`is_request_suspect`) pass straight through
    to ``chain.record_failure`` exactly as before. Request-suspect failures
    (400/422 invalid-params with no provider-specific marker) are STAGED and
    resolved by corroboration:

    * ``record_success`` — the request succeeded on some provider, so the
      request was well-formed and every staged failure WAS a provider fault:
      all staged failures are committed. (This is what keeps the 2026-07-03
      AtlasCloud protection: one provider 400s, another serves → cooldown.)
    * ``close`` with staged failures on ≥2 DIFFERENT providers — the same
      request 400/422'd across providers and succeeded nowhere: that is the
      REQUEST's signature (e.g. an orphaned-tool-call session), so nobody is
      cooled and the event is counted per provider (forgiven_request_faults).
    * ``close`` with exactly ONE staged failure — no corroboration either
      way: committed (identical to pre-F1 behavior, so a genuinely broken
      lone provider still cools down).

    The scope is request-local and stages in a plain list — it never mutates
    chain state before resolution, so nothing needs rolling back and
    concurrent requests (the rotation loop awaits between attempts) cannot
    cross-contaminate. ``close()`` is idempotent; with ``guard_enabled=False``
    every call passes through unchanged (legacy behavior, kill-switch).
    """

    def __init__(self, chain: ProviderChain, *, guard_enabled: bool = True):
        self._chain = chain
        self._guard = bool(guard_enabled)
        self._staged: list[tuple[str, object]] = []
        self._closed = False

    def record_success(self, provider: str, duration_s: Optional[float] = None) -> None:
        """Provider served the request — commit staged suspects (they were
        provider faults: the request itself just proved servable), then
        restore the serving provider."""
        self._commit_staged()
        self._chain.record_success(provider, duration_s)

    def record_failure(self, provider: str, error: object) -> ErrorClass:
        """Record (or stage) one provider failure. Never raises; always
        returns the error class so the caller can log/decide."""
        try:
            if self._guard and is_request_suspect(error):
                logger.info(
                    "ProviderChain: request-suspect failure on %s staged "
                    "(attribution deferred to end of rotation)", provider,
                )
                self._staged.append((provider, error))
                return classify_provider_error(error)
        except Exception:  # pragma: no cover — belt and braces
            pass
        return self._chain.record_failure(provider, error)

    def close(self) -> None:
        """Resolve staged failures at end of rotation (no success happened).
        Idempotent — safe to call from a ``finally``."""
        if self._closed:
            return
        self._closed = True
        if not self._staged:
            return
        distinct = {provider for provider, _err in self._staged}
        if len(distinct) >= 2:
            staged, self._staged = self._staged, []
            self._chain._forgive_request_fault(staged)
        else:
            self._commit_staged()

    def _commit_staged(self) -> None:
        staged, self._staged = self._staged, []
        for provider, err in staged:
            self._chain.record_failure(provider, err)
