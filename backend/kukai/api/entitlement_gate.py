"""Hot-path glue for the licensing/entitlement layer (api layer).

Thin, fail-open helpers the WS/HTTP turn calls. EVERY function is a no-op when
KUKAI_LICENSING is off (prod default), so the request path stays byte-identical.
The heavy logic lives in kukai.licensing.* ; this module only bridges it to the
turn (resolve the tenant's account/tier, gate a feature) with turn-safety
guarantees (never raise, never break a turn).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from kukai.licensing.entitlements import require_entitlement
from kukai.licensing.mode import licensing_enabled, licensing_enforced, licensing_mode

GRANDFATHER_TIER = "legacy"

logger = logging.getLogger(__name__)


async def resolve_turn_account(
    state: Any, tenant_id: str, device_id: str, auth_info: dict
) -> None:
    """Populate auth_info['tier'] and auth_info['account_id'] for this turn.

    No-op when licensing is off or there is no account_manager. Fail-open: any error
    leaves the existing defaults (tier is read as .get('tier','free') downstream).

    A device with no license yet (every pre-monetization install) is handled by MODE:
      * shadow  — PURE OBSERVE, zero writes to prod: the device is treated as its
                  grandfather outcome ('legacy') so the audit accurately predicts what
                  enforce will do, WITHOUT provisioning. Real provisioning is the
                  explicit backfill script, run before any enforce flip.
      * enforce — grandfather now (idempotent WRITE) so the user is never gated.
    This keeps shadow read-only w.r.t. account data — the 50 installs are untouched.
    """
    if not licensing_enabled():
        return
    am = getattr(state, "account_manager", None)
    if am is None:
        return
    try:
        # device_id is the raw client key that activate_license stores in `devices`;
        # tenant_id is the effective isolation key (== device_id when signed-identity
        # is off). Resolve on device_id, falling back to tenant_id.
        key = device_id or tenant_id
        tier = await am.get_tier_for_device(key)        # read-only
        account = await am.get_account_by_device(key)   # read-only
        provisioned = False
        if tier is None:
            if licensing_enforced():
                prov = await am.auto_provision_grandfathered(key)  # WRITE (enforce only)
                if prov:
                    tier = prov.get("tier")
                    account = prov.get("account") or account
                    provisioned = True
            else:
                tier = GRANDFATHER_TIER  # shadow: observe-as-grandfathered, no write
        if tier:
            auth_info["tier"] = tier
        if account:
            auth_info["account_id"] = account.get("id", "")
        # Shadow observability: one concise line per turn so the soak is visible
        # (device truncated for privacy). "observe" = read-only; "provisioned" = enforce write.
        logger.info(
            "licensing[%s] tenant=%s tier=%s account=%s (%s)",
            licensing_mode(), str(key)[:12], tier or "free",
            account["id"][:8] if account else "-",
            "provisioned" if provisioned else "observe",
        )
    except Exception:  # noqa: BLE001 — resolution must never break a turn
        logger.debug("resolve_turn_account failed (fail-open)", exc_info=True)


async def gate_feature(
    state: Any, feature: str, auth_info: dict, tenant_id: str
) -> Optional[str]:
    """Entitlement gate for a feature entry point.

    Returns None to ALLOW (shadow always allows; enforce allows the entitled), or a
    user-facing upsell/deny message to BLOCK (enforce + not entitled). No-op (None)
    when licensing is off. Fail-open: any error allows.

    The shadow-mode would-deny is recorded by require_entitlement's audit log, so the
    gate can be measured on real traffic before it ever blocks a user.
    """
    if not licensing_enabled():
        return None
    try:
        db = getattr(getattr(state, "db", None), "raw_connection", None)
        if db is None:
            return None
        tier = auth_info.get("tier", "free")
        account_id = auth_info.get("account_id", "")
        decision = await require_entitlement(
            db, feature, tier=tier, account_id=account_id, tenant_id=tenant_id
        )
        if decision.allow:
            return None
        return ("Эта возможность доступна на платном тарифе. "
                "Оформите доступ, чтобы продолжить 🙏")
    except Exception:  # noqa: BLE001 — the gate must never break a turn
        logger.debug("gate_feature failed (fail-open allow)", exc_info=True)
        return None
