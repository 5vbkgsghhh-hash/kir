"""Account layer on top of the existing licenses/devices (licensing prep).

An `account` is the monetization/identity unit ("who pays"). It WRAPS the existing
LicenseManager rather than duplicating it: a license gains an ``account_id``, and a
device resolves to its account via ``devices -> licenses -> accounts``. AccountManager
owns account CRUD and the auto-grandfather path; the actual license/device/HMAC-token
machinery is reused from LicenseManager (register_license / activate_license).

Runtime-dormant unless KUKAI_LICENSING != off (see licensing.mode).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from kukai.licensing.accounts_schema import ensure_accounts_schema

logger = logging.getLogger(__name__)

# Far-future expiry for grandfathered licenses (~100y) — effectively no expiry,
# while reusing the existing expiry-carrying `licenses` schema unchanged.
_GRANDFATHER_DAYS = 365 * 100
_GRANDFATHER_TIER = "legacy"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_account(row: Any) -> Optional[dict[str, Any]]:
    if not row:
        return None
    # accounts columns: id, owner_email, status, source, organization_id, name,
    # created_at, updated_at
    return {
        "id": row[0],
        "owner_email": row[1],
        "status": row[2],
        "source": row[3],
        "organization_id": row[4],
        "name": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


class AccountManager:
    """CRUD for accounts + the auto-grandfather provisioning path.

    ``db`` is the Database.raw_connection adapter (aiosqlite-compatible), the same
    handle LicenseManager uses. ``license_manager`` is reused for grandfather
    provisioning (may be None in unit tests that don't exercise that path).
    """

    def __init__(self, db: Any, license_manager: Any = None):
        self._db = db
        self._lm = license_manager

    async def initialize(self) -> None:
        await ensure_accounts_schema(self._db)

    # --- CRUD ---------------------------------------------------------------

    async def create_account(
        self,
        owner_email: str = "",
        source: str = "admin",
        name: str = "",
        organization_id: str = "",
    ) -> dict[str, Any]:
        account_id = str(uuid.uuid4())
        now = _now()
        await self._db.execute(
            """INSERT INTO accounts
               (id, owner_email, status, source, organization_id, name, created_at, updated_at)
               VALUES (?, ?, 'active', ?, ?, ?, ?, ?)""",
            (account_id, owner_email, source, organization_id, name, now, now),
        )
        await self._db.commit()
        logger.info("Account created: id=%s source=%s email=%s",
                    account_id, source, owner_email or "(none)")
        account = await self.get_account(account_id)
        assert account is not None
        return account

    async def get_account(self, account_id: str) -> Optional[dict[str, Any]]:
        cursor = await self._db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        return _row_to_account(await cursor.fetchone())

    async def get_account_by_device(self, device_id: str) -> Optional[dict[str, Any]]:
        """Resolve device -> license -> account (the tenant's owner), or None."""
        if not device_id:
            return None
        cursor = await self._db.execute(
            """SELECT a.* FROM devices d
               JOIN licenses l ON d.license_key = l.key
               JOIN accounts a ON l.account_id = a.id
               WHERE d.device_id = ? AND d.active = 1
               LIMIT 1""",
            (device_id,),
        )
        return _row_to_account(await cursor.fetchone())

    async def get_tier_for_device(self, device_id: str) -> Optional[str]:
        """The license tier backing a device (independent of account link), or None."""
        if not device_id:
            return None
        cursor = await self._db.execute(
            """SELECT l.tier FROM devices d JOIN licenses l ON d.license_key = l.key
               WHERE d.device_id = ? AND d.active = 1 LIMIT 1""",
            (device_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def link_license(self, license_key: str, account_id: str) -> None:
        await self._db.execute(
            "UPDATE licenses SET account_id = ? WHERE key = ?", (account_id, license_key)
        )
        await self._db.commit()

    async def set_status(self, account_id: str, status: str) -> bool:
        cursor = await self._db.execute(
            "UPDATE accounts SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), account_id),
        )
        await self._db.commit()
        return getattr(cursor, "rowcount", 0) > 0

    async def list_accounts(self, limit: int = 100) -> list[dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT * FROM accounts ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [a for a in (_row_to_account(r) for r in rows) if a is not None]

    # --- Grandfather --------------------------------------------------------

    async def _license_key_for_device(self, device_id: str) -> Optional[str]:
        cursor = await self._db.execute(
            "SELECT license_key FROM devices WHERE device_id = ? AND active = 1 LIMIT 1",
            (device_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def auto_provision_grandfathered(
        self, device_id: str, hwid: str = ""
    ) -> Optional[dict[str, Any]]:
        """Idempotently ensure a pre-monetization device has a legacy account.

        Returns {account, license_key, device_token, tier, grandfathered} or None
        if it cannot provision (no device_id / no LicenseManager). NEVER raises into
        the caller — grandfathering must not break a live turn.

        Cases:
          1. device already resolves to an account -> return it (grandfathered=False).
          2. device has a license but no account   -> create account, link it.
          3. device unknown (the common pre-monetization case) -> create account +
             an unlimited `legacy` license + register the device (reusing
             LicenseManager), returning a signed device token.
        """
        if not device_id or self._lm is None:
            return None
        try:
            existing = await self.get_account_by_device(device_id)
            if existing is not None:
                tier = await self.get_tier_for_device(device_id)
                return {"account": existing, "license_key": None, "device_token": None,
                        "tier": tier, "grandfathered": False}

            # Case 2: device already licensed but the license has no account.
            existing_key = await self._license_key_for_device(device_id)
            if existing_key:
                account = await self.create_account(source="grandfathered",
                                                    name=f"grandfathered:{device_id[:16]}")
                await self.link_license(existing_key, account["id"])
                tier = await self.get_tier_for_device(device_id)
                return {"account": account, "license_key": existing_key,
                        "device_token": None, "tier": tier, "grandfathered": True}

            # Case 3: fresh grandfather — account + legacy license + device.
            account = await self.create_account(source="grandfathered",
                                                name=f"grandfathered:{device_id[:16]}")
            key = self._lm.generate_license_key()
            await self._lm.register_license(
                key, tier=_GRANDFATHER_TIER, days=_GRANDFATHER_DAYS,
                name=f"grandfathered:{device_id[:16]}",
            )
            await self.link_license(key, account["id"])
            activation = await self._lm.activate_license(
                key, device_id, hwid=hwid, device_name="grandfathered"
            )
            logger.info("Grandfathered device=%s -> account=%s (legacy license)",
                        device_id[:16], account["id"])
            return {"account": account, "license_key": key,
                    "device_token": activation.get("device_token"),
                    "tier": _GRANDFATHER_TIER, "grandfathered": True}
        except Exception:  # noqa: BLE001 — grandfathering must never break a turn
            logger.warning("auto_provision_grandfathered failed for device=%s",
                           str(device_id)[:16], exc_info=True)
            return None
