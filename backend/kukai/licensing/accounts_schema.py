"""Additive schema for the accounts + entitlement layer (licensing prep).

Self-contained graft in the style of api/install_telemetry.py and the existing
LICENSE_SCHEMA_SQL: SQLite-dialect DDL executed through the Database.raw_connection
adapter (auto-translated to PostgreSQL), CREATE TABLE IF NOT EXISTS + named
indexes, idempotent and self-healing at startup. No edit to storage/database.py.

Tables:
  accounts           — the monetization/identity unit ("who pays"). Wraps the
                       existing `licenses` (a license gains an account_id FK).
  entitlements       — per-account feature grants/denies (overrides tier default).
  entitlement_audit  — shadow-mode decision log (would-allow / would-deny), so the
                       gate can be validated on real traffic before enforcing.

Also adds `licenses.account_id` (idempotent ALTER) linking a license to its owner
account, and an index on it. `devices` is unchanged (device<->license already links).

Call ensure_accounts_schema() AFTER LicenseManager.initialize() (which creates the
`licenses` table this links to). It is defensive if licenses is absent.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Tables + their own indexes only. The licenses.account_id column + its index are
# added separately in ensure_accounts_schema (the column must exist before the
# index can reference it, and `licenses` is owned by LicenseManager).
ACCOUNTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    owner_email TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'admin',
    organization_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entitlements (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    feature TEXT NOT NULL,
    granted INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS entitlement_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT '',
    account_id TEXT NOT NULL DEFAULT '',
    feature TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    enforced INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_accounts_org ON accounts(organization_id);
CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(owner_email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entitlements_account_feature
    ON entitlements(account_id, feature);
CREATE INDEX IF NOT EXISTS idx_entitlement_audit_created
    ON entitlement_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_entitlement_audit_feature
    ON entitlement_audit(feature, decision);
"""

async def ensure_accounts_schema(db: Any) -> None:
    """Create the accounts/entitlement tables + licenses.account_id if absent.

    `db` is the Database.raw_connection adapter (aiosqlite-compatible), the same
    handle LicenseManager uses. Idempotent (CREATE TABLE IF NOT EXISTS) and cheap;
    called once at startup. We deliberately do NOT cache by id(db) (the
    install_telemetry pattern): a freed connection's id() can be reused by a new
    one, which would skip the DDL and leave tables missing — matching
    LicenseManager.initialize, we just re-run the idempotent DDL.
    """
    await db.executescript(ACCOUNTS_SCHEMA_SQL)
    await db.commit()
    # Link licenses -> account. Probe the column, add it only if missing (mirrors
    # LicenseManager.initialize style). Defensive if `licenses` doesn't exist yet.
    try:
        try:
            await db.execute("SELECT account_id FROM licenses LIMIT 1")
        except Exception:
            await db.execute(
                "ALTER TABLE licenses ADD COLUMN account_id TEXT NOT NULL DEFAULT ''"
            )
            await db.commit()
            logger.info("Migrated licenses: added account_id column")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_licenses_account ON licenses(account_id)"
        )
        await db.commit()
    except Exception as e:  # noqa: BLE001 — licenses link is best-effort
        logger.warning("accounts_schema: licenses.account_id link skipped (%s)", e)
    logger.info("Accounts/entitlement tables initialized")
