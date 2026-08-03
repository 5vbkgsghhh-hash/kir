"""KUKAI_LICENSING rollout flag — off | shadow | enforce.

Mirrors security.identity.identity_mode() and the read-at-call-time / default-off
feature-flag convention (KUKAI_TURN_LEDGER, KUKAI_SIGNED_IDENTITY): the value is
read from the environment on every call (never cached), so a plain restart flips
modes and tests can monkeypatch os.environ.

  off      PROD DEFAULT. Byte-identical to today — no LicenseManager /
           AccountManager constructed, no account resolution, no entitlement or
           quota checks anywhere.
  shadow   Managers constructed; account resolution + entitlement/quota decisions
           are COMPUTED and LOGGED (would-allow / would-deny), but NEVER enforced.
           Validates the whole layer on real traffic without gating a single user.
  enforce  Real gating: unentitled features and exhausted quotas are denied.

Safety bias: any explicitly-set-but-unrecognized value resolves to `shadow`,
never `enforce` — we never silently start denying users on a typo.
"""
from __future__ import annotations

import os

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"

_OFF_VALUES = frozenset({"", "0", "off", "false", "no", "none"})
_ENFORCE_VALUES = frozenset({"2", "enforce", "strict"})
# shadow values are documented for clarity; anything non-off and non-enforce
# falls through to shadow anyway (see licensing_mode).
_SHADOW_VALUES = frozenset({"1", "shadow", "on", "observe", "dry-run", "dryrun"})


def licensing_mode() -> str:
    """Parse KUKAI_LICENSING at call time -> "off" | "shadow" | "enforce"."""
    raw = os.getenv("KUKAI_LICENSING", "").strip().lower()
    if raw in _OFF_VALUES:
        return MODE_OFF
    if raw in _ENFORCE_VALUES:
        return MODE_ENFORCE
    # shadow values + any unrecognized non-off value -> shadow (never silently enforce)
    return MODE_SHADOW


def licensing_enabled() -> bool:
    """True in shadow or enforce (managers should be constructed)."""
    return licensing_mode() != MODE_OFF


def licensing_enforced() -> bool:
    """True only in enforce (decisions actually gate traffic)."""
    return licensing_mode() == MODE_ENFORCE
