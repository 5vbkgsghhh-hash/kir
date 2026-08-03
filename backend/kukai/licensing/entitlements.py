"""Feature-entitlement gate (licensing prep).

A single seam, ``require_entitlement(...)``, called at feature entry points.
Behaviour by KUKAI_LICENSING mode (licensing.mode):

  off      Not normally called (callers guard on licensing_enabled()); if called,
           returns allow with enforced=False.
  shadow   Compute the policy decision, LOG it and record it to entitlement_audit
           (would-allow / would-deny), but ALWAYS return allow — never gate a user.
  enforce  Return the policy decision; a restricted feature the tier/account lacks
           is denied (allow=False).

Fail-open: any internal error returns allow (the gate must never break a turn).
The audit write is best-effort (its failure never affects the decision).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from kukai.licensing import features as feat
from kukai.licensing.mode import MODE_ENFORCE, MODE_OFF, MODE_SHADOW, licensing_mode

logger = logging.getLogger(__name__)


@dataclass
class EntitlementDecision:
    allow: bool          # the EFFECTIVE decision the caller MUST honor
    feature: str
    tier: str
    account_id: str
    mode: str
    enforced: bool       # True only when this decision actually gates (enforce + restricted)
    policy_allow: bool   # what policy says, independent of mode (for shadow observability)
    reason: str = ""


async def _account_override(db: Any, account_id: str, feature: str) -> Optional[bool]:
    """Per-account grant/deny override from the entitlements table.

    Returns True/False for an explicit grant/deny row, or None when there is no
    override row. Deliberately does NOT swallow DB errors: if the lookup itself
    fails, it raises so require_entitlement fails OPEN (allow) rather than silently
    degrading a possibly-entitled account to tier policy (which could wrongly deny).
    When there is no account_id, tier policy is complete without the DB, so we
    short-circuit to None (no DB touched).
    """
    if not account_id:
        return None
    cursor = await db.execute(
        "SELECT granted FROM entitlements WHERE account_id = ? AND feature = ? LIMIT 1",
        (account_id, feature),
    )
    row = await cursor.fetchone()
    return None if row is None else bool(row[0])


def _policy_allow(tier: str, feature: str, override: Optional[bool]) -> bool:
    """Tier default, with a per-account override layered on top (restricted only)."""
    if not feat.is_restricted(feature):
        return True
    if override is not None:
        return override
    return feat.tier_has_feature(tier, feature)


async def require_entitlement(
    db: Any,
    feature: str,
    *,
    tier: str = "free",
    account_id: str = "",
    tenant_id: str = "",
) -> EntitlementDecision:
    """Resolve whether `tenant` (tier/account) may use `feature`, honoring the mode."""
    mode = licensing_mode()
    try:
        if mode == MODE_OFF:
            return EntitlementDecision(True, feature, tier, account_id, mode, False, True, "licensing off")

        override = await _account_override(db, account_id, feature)
        policy_allow = _policy_allow(tier, feature, override)
        restricted = feat.is_restricted(feature)
        enforced = (mode == MODE_ENFORCE) and restricted
        # shadow (and any unrestricted feature) never blocks; enforce blocks on policy.
        allow = policy_allow or not enforced
        reason = ("account override" if override is not None
                  else ("tier policy" if restricted else "ungated"))

        decision = EntitlementDecision(allow, feature, tier, account_id, mode,
                                       enforced, policy_allow, reason)
        await _audit(db, decision, tenant_id)
        if not policy_allow:
            logger.info(
                "entitlement %s: feature=%s tier=%s account=%s -> %s (mode=%s, %s)",
                "DENY" if enforced else "would-deny",
                feature, tier, account_id or "(none)",
                "blocked" if not allow else "allowed(shadow)", mode, reason,
            )
        return decision
    except Exception:  # noqa: BLE001 — the gate must never break a turn
        logger.warning("require_entitlement failed — fail-open allow (feature=%s)",
                       feature, exc_info=True)
        return EntitlementDecision(True, feature, tier, account_id, mode, False, True, "error fail-open")


async def _audit(db: Any, d: EntitlementDecision, tenant_id: str) -> None:
    """Best-effort shadow log of the POLICY decision (allow/deny) + mode."""
    try:
        await db.execute(
            """INSERT INTO entitlement_audit
               (tenant_id, account_id, feature, tier, decision, enforced, mode, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tenant_id, d.account_id, d.feature, d.tier,
             "allow" if d.policy_allow else "deny",
             1 if d.enforced else 0, d.mode, d.reason,
             datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — audit failure never affects the decision
        logger.debug("entitlement_audit write skipped", exc_info=True)
