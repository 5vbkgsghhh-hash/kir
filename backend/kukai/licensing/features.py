"""Feature entitlement catalog for KUKAI licensing.

The *structure* of feature-gating lives here; the *policy* (which features each
tier gets, and which features are gated at all) is deliberately conservative
until the product decision is made (see the licensing plan, Feature-entitlement):

  * FEATURES      — the catalog of gate-able capability names (stable strings,
                    used as keys in entitlement rows and audit logs).
  * RESTRICTED    — the set of features that actually REQUIRE an entitlement.
                    A feature NOT in this set is always allowed (ungated), so
                    switching licensing to `enforce` gates NOTHING until a
                    feature is deliberately added here. Ships EMPTY on purpose.
  * TIER_FEATURES — for a restricted feature, which tiers include it. Tiers not
                    listed for a feature do NOT get it (unless an explicit
                    per-account grant in the `entitlements` table overrides).

This keeps Phase-0 / shadow byte-safe: with RESTRICTED empty, require_entitlement
returns allow for everything; the maps exist so the wiring + tests are real.
Do NOT rename existing string values — they are persisted in entitlement rows.
"""
from __future__ import annotations

# --- Capability catalog (stable identifiers) --------------------------------
# Candidates drawn from the mass-adoption tracks (нормоконтроль killer-app,
# section autopilots, Pulse multiplayer, create_element). Add here as features
# become gate-able.
FEATURE_NORMCONTROL = "normcontrol"          # СП/ГОСТ нормоконтроль killer-app
FEATURE_AUTOPILOT = "autopilot_sections"     # раздел-автопилоты (отверстия/спеки/…)
FEATURE_PULSE_ROOMS = "pulse_rooms"          # Project Pulse worksharing/collab
FEATURE_CREATE_ELEMENT = "create_element"    # generative create_element op

FEATURES: frozenset[str] = frozenset({
    FEATURE_NORMCONTROL,
    FEATURE_AUTOPILOT,
    FEATURE_PULSE_ROOMS,
    FEATURE_CREATE_ELEMENT,
})

# --- Policy (deliberately empty until product decides — see plan) -----------
# Features that require an entitlement at all. EMPTY => nothing is gated, even in
# enforce mode. Populate ONLY with an explicit product decision (which features
# are pro-only, etc.).
RESTRICTED: frozenset[str] = frozenset()

# For a RESTRICTED feature: the tiers that include it. Example shape below is
# inert while RESTRICTED is empty. `ultra`/`legacy` are handled by
# ALL_ACCESS_TIERS, so list `pro`/`free` here per feature when it is restricted.
TIER_FEATURES: dict[str, frozenset[str]] = {
    # FEATURE_NORMCONTROL: frozenset({"pro"}),   # + ultra/legacy via ALL_ACCESS_TIERS
}

# Tiers that always get every feature regardless of TIER_FEATURES (owners of
# unlimited / grandfathered plans). Keeps existing users unaffected when a
# feature later becomes restricted.
ALL_ACCESS_TIERS: frozenset[str] = frozenset({"ultra", "legacy"})


def is_restricted(feature: str) -> bool:
    """True when the feature requires an entitlement at all."""
    return feature in RESTRICTED


def tier_has_feature(tier: str, feature: str) -> bool:
    """Tier-default policy for a (tier, feature) pair.

    Ungated features are always True. All-access tiers get everything. Otherwise
    consult TIER_FEATURES. Per-account grants/denies are layered on top by the
    entitlement resolver (not here — this is the tier default only).
    """
    if not is_restricted(feature):
        return True
    if tier in ALL_ACCESS_TIERS:
        return True
    return tier in TIER_FEATURES.get(feature, frozenset())
