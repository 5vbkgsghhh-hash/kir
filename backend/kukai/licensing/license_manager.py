"""License manager — server-side license validation, device tokens, usage tracking.

Tier limits (sliding window):
  - free:       20 requests per rolling 24-hour window, 1 device
  - pro:        50 requests per rolling 5-hour window, 1 device
  - team:       unlimited requests, 10 devices
  - enterprise: unlimited requests, unlimited devices

Device token format:
  KUKAI-DT-{license_key_hash}-{device_id}-{timestamp}-{signature}

Signature: HMAC-SHA256 with server secret key.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# NOTE: The storage layer is now PostgreSQL via asyncpg. The Database class
# provides an aiosqlite-compatible adapter (.execute / .commit / .rollback /
# .executescript) via Database.raw_connection, so this manager keeps its
# original code shape — only the connection type annotation changed to Any.
# The underlying SQL is automatically translated (? placeholders, INSERT OR
# IGNORE, datetime('now', ...), etc.) by the adapter at execution time.

logger = logging.getLogger(__name__)

# Tier configuration — 3 tiers
TIER_LIMITS: dict[str, dict[str, Any]] = {
    "free":  {"daily_limit": 30,  "max_devices": 1, "window_hours": 168, "window_limit": 30},   # 30/week
    "pro":   {"daily_limit": 100, "max_devices": 3, "window_hours": 24,  "window_limit": 100},   # 100/day
    "ultra": {"daily_limit": 300, "max_devices": 10,"window_hours": 24,  "window_limit": 300},   # 300/day
    # legacy = grandfathered existing installs (auto-provisioned, never sold):
    # unlimited by construction — 0 window_limit/max_devices means "no cap" per
    # check_rate_limit_window and activate_license, so switching licensing on can
    # never throttle or lock out a user who was here before monetization.
    "legacy":{"daily_limit": 0,   "max_devices": 0, "window_hours": 24,  "window_limit": 0},     # unlimited
}

VALID_TIERS = set(TIER_LIMITS.keys())

LICENSE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    max_devices INTEGER NOT NULL DEFAULT 1,
    daily_limit INTEGER NOT NULL DEFAULT 0,  -- DISABLED: free trial period — 0 = unlimited
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    license_key TEXT NOT NULL,
    device_id TEXT NOT NULL,
    hwid TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    last_seen TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (license_key) REFERENCES licenses(key)
);

CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_token TEXT NOT NULL,
    license_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_license_device
    ON devices(license_key, device_id);
CREATE INDEX IF NOT EXISTS idx_devices_license_key ON devices(license_key);
CREATE INDEX IF NOT EXISTS idx_licenses_key ON licenses(key);
CREATE INDEX IF NOT EXISTS idx_devices_hwid ON devices(hwid);
CREATE INDEX IF NOT EXISTS idx_request_log_token_time
    ON request_log(device_token, created_at);
"""


class LicenseError(Exception):
    """Base exception for license errors."""
    pass


class LicenseNotFoundError(LicenseError):
    """License key not found."""
    pass


class LicenseExpiredError(LicenseError):
    """License has expired."""
    pass


class LicenseInactiveError(LicenseError):
    """License is deactivated."""
    pass


class DeviceLimitError(LicenseError):
    """Maximum number of devices reached."""
    pass


class InvalidTokenError(LicenseError):
    """Device token is invalid or tampered."""
    pass


class HwidConflictError(LicenseError):
    """HWID is already registered on another free-tier license."""
    pass


class DailyLimitError(LicenseError):
    """Daily request limit exceeded."""
    pass


class LicenseInfo:
    """License details returned by validation."""

    def __init__(
        self,
        key: str,
        tier: str,
        max_devices: int,
        daily_limit: int,
        expires_at: str,
        active: bool,
        device_count: int = 0,
        name: str = "",
    ):
        self.key = key
        self.tier = tier
        self.max_devices = max_devices
        self.daily_limit = daily_limit
        self.expires_at = expires_at
        self.active = active
        self.device_count = device_count
        self.name = name
        self.refreshed_token: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "tier": self.tier,
            "max_devices": self.max_devices,
            "daily_limit": self.daily_limit,
            "expires_at": self.expires_at,
            "active": self.active,
            "device_count": self.device_count,
            "name": self.name,
        }


class LicenseManager:
    """Server-side license manager. Backed by the Database.raw_connection
    adapter, which today runs against PostgreSQL. The adapter exposes an
    aiosqlite-compatible API (execute/commit/rollback/executescript), so the
    SQL kept here in SQLite dialect is translated transparently.
    """

    def __init__(self, db: Any, server_secret: str):
        # `db` is whatever Database.raw_connection returns: today an asyncpg
        # adapter (`_LegacyConnection`), historically an aiosqlite.Connection.
        self._db = db
        self._server_secret = server_secret
        if not server_secret:
            raise ValueError("server_secret must not be empty")

    async def initialize(self) -> None:
        """Create licensing tables if they don't exist."""
        await self._db.executescript(LICENSE_SCHEMA_SQL)
        await self._db.commit()
        # Migrations for existing databases
        try:
            await self._db.execute("SELECT name FROM licenses LIMIT 1")
        except Exception:
            await self._db.execute("ALTER TABLE licenses ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            await self._db.commit()
            logger.info("Migrated licenses: added name column")
        try:
            await self._db.execute("SELECT license_key FROM request_log LIMIT 1")
        except Exception:
            await self._db.execute("ALTER TABLE request_log ADD COLUMN license_key TEXT NOT NULL DEFAULT ''")
            await self._db.commit()
            # Backfill: match existing request_log entries to licenses via devices
            try:
                await self._db.execute("""
                    UPDATE request_log SET license_key = (
                        SELECT d.license_key FROM devices d
                        WHERE request_log.device_token LIKE '%' || d.device_id || '%'
                        LIMIT 1
                    ) WHERE license_key = ''
                """)
                await self._db.commit()
                logger.info("Backfilled license_key in existing request_log entries")
            except Exception as e:
                logger.debug("Backfill skipped: %s", e)
            logger.info("Migrated request_log: added license_key column")
        logger.info("License tables initialized")

    @staticmethod
    def apply_config_limits(free_window_limit: int = 30, pro_window_limit: int = 100, ultra_window_limit: int = 300) -> None:
        """Override TIER_LIMITS from config values (call once at startup)."""
        TIER_LIMITS["free"]["window_limit"] = free_window_limit
        TIER_LIMITS["pro"]["window_limit"] = pro_window_limit
        TIER_LIMITS["ultra"]["window_limit"] = ultra_window_limit
        logger.info("Tier limits updated: free=%d/week, pro=%d/day, ultra=%d/day", free_window_limit, pro_window_limit, ultra_window_limit)

    # --- License key generation ---

    @staticmethod
    def generate_license_key() -> str:
        """Generate a new license key in format KUKAI-XXXX-XXXX-XXXX-XXXX."""
        chars = string.ascii_uppercase + string.digits
        groups = []
        for _ in range(4):
            group = "".join(secrets.choice(chars) for _ in range(4))
            groups.append(group)
        return "KUKAI-" + "-".join(groups)

    @staticmethod
    def validate_key_format(key: str) -> bool:
        """Check if key matches KUKAI-XXXX-XXXX-XXXX-XXXX format."""
        if not key.startswith("KUKAI-"):
            return False
        parts = key.split("-")
        if len(parts) != 5:
            return False
        # First part is "KUKAI"
        for part in parts[1:]:
            if len(part) != 4:
                return False
            if not all(c in string.ascii_uppercase + string.digits for c in part):
                return False
        return True

    # --- License CRUD ---

    async def register_license(
        self,
        key: str,
        tier: str,
        max_devices: int | None = None,
        daily_limit: int | None = None,
        expires_at: str | None = None,
        days: int = 365,
        name: str = "",
    ) -> dict[str, Any]:
        """Create a new license record. Admin-only operation."""
        if tier not in VALID_TIERS:
            raise ValueError(f"Invalid tier: {tier}. Must be one of: {VALID_TIERS}")

        if not self.validate_key_format(key):
            raise ValueError(f"Invalid key format: {key}")

        tier_config = TIER_LIMITS[tier]
        if max_devices is None:
            max_devices = tier_config["max_devices"]
        if daily_limit is None:
            daily_limit = tier_config["daily_limit"]

        now = datetime.now(timezone.utc)
        if expires_at is None:
            expires_at = (now + timedelta(days=days)).isoformat()

        license_id = str(uuid.uuid4())
        await self._db.execute(
            """INSERT INTO licenses (id, key, tier, max_devices, daily_limit, created_at, expires_at, active, name)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (license_id, key, tier, max_devices, daily_limit, now.isoformat(), expires_at, name),
        )
        await self._db.commit()

        logger.info("Registered license: key=%s name=%s tier=%s", key, name or "(unnamed)", tier)

        return {
            "id": license_id,
            "key": key,
            "tier": tier,
            "max_devices": max_devices,
            "daily_limit": daily_limit,
            "expires_at": expires_at,
            "name": name,
        }

    async def get_license_info(self, key: str) -> LicenseInfo:
        """Get full license info including device count."""
        cursor = await self._db.execute(
            "SELECT * FROM licenses WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if not row:
            raise LicenseNotFoundError(f"License not found: {key}")

        # Count active devices
        cursor2 = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM devices WHERE license_key = ? AND active = 1",
            (key,),
        )
        dev_row = await cursor2.fetchone()
        device_count = dev_row[0] if dev_row else 0

        return LicenseInfo(
            key=row[1],       # key
            tier=row[2],      # tier
            max_devices=row[3],   # max_devices
            daily_limit=row[4],   # daily_limit
            expires_at=row[6],    # expires_at
            active=bool(row[7]),  # active
            device_count=device_count,
            name=row[8] if len(row) > 8 else "",  # name
        )

    async def list_licenses(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all licenses with device counts and recent usage."""
        cursor = await self._db.execute(
            """SELECT l.*,
                      (SELECT COUNT(*) FROM devices d WHERE d.license_key = l.key AND d.active = 1) as device_count
               FROM licenses l
               ORDER BY l.created_at DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row[0],
                "key": row[1],
                "tier": row[2],
                "max_devices": row[3],
                "daily_limit": row[4],
                "created_at": row[5],
                "expires_at": row[6],
                "active": bool(row[7]),
                "name": row[8] if len(row) > 8 else "",
                "device_count": row[9] if len(row) > 9 else 0,
            })
        return result

    async def get_license_usage(self, days: int = 7) -> list[dict[str, Any]]:
        """Get usage stats per license for the last N days.

        Returns list of {key, name, tier, total_requests, today_requests, devices}.
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=days)).isoformat()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        cursor = await self._db.execute(
            """SELECT
                l.key, l.name, l.tier, l.active, l.expires_at,
                (SELECT COUNT(*) FROM devices d WHERE d.license_key = l.key AND d.active = 1) as device_count,
                COALESCE((SELECT COUNT(*) FROM request_log r WHERE r.license_key = l.key AND r.created_at >= ?), 0) as total_requests,
                COALESCE((SELECT COUNT(*) FROM request_log r WHERE r.license_key = l.key AND r.created_at >= ?), 0) as today_requests
            FROM licenses l
            ORDER BY total_requests DESC, l.created_at DESC""",
            (cutoff, today_start),
        )
        rows = await cursor.fetchall()
        return [
            {
                "key": row[0],
                "name": row[1] or "",
                "tier": row[2],
                "active": bool(row[3]),
                "expires_at": row[4],
                "devices": row[5],
                "total_requests": row[6],
                "today_requests": row[7],
            }
            for row in rows
        ]

    async def update_license_name(self, key: str, name: str) -> bool:
        """Update the display name of a license."""
        cursor = await self._db.execute(
            "UPDATE licenses SET name = ? WHERE key = ?",
            (name, key),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    # --- Device activation ---

    def _make_token_signature(self, key_hash: str, device_id: str, timestamp: str) -> str:
        """Create HMAC-SHA256 signature for device token."""
        payload = f"{key_hash}:{device_id}:{timestamp}"
        sig = hmac.new(
            self._server_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]
        return sig

    def _create_device_token(self, license_key: str, device_id: str) -> str:
        """Generate a signed device token."""
        key_hash = hashlib.sha256(license_key.encode("utf-8")).hexdigest()[:12]
        timestamp = str(int(time.time()))
        signature = self._make_token_signature(key_hash, device_id, timestamp)
        return f"KUKAI-DT-{key_hash}-{device_id}-{timestamp}-{signature}"

    def _verify_device_token(self, token: str) -> tuple[str, str, str]:
        """Verify token signature. Returns (key_hash, device_id, timestamp).

        Raises InvalidTokenError if the token is malformed or tampered.
        """
        if not token.startswith("KUKAI-DT-"):
            raise InvalidTokenError("Invalid token format")

        # Strip prefix
        rest = token[len("KUKAI-DT-"):]
        parts = rest.split("-")
        # key_hash (12 chars), device_id (variable), timestamp, signature
        # The device_id could contain hyphens, so we need at least 4 parts
        if len(parts) < 4:
            raise InvalidTokenError("Invalid token format: too few parts")

        # Last part is signature (32 hex chars)
        signature = parts[-1]
        # Second to last is timestamp
        timestamp = parts[-2]
        # First part is key_hash (12 hex chars)
        key_hash = parts[0]
        # Everything in between is the device_id
        device_id = "-".join(parts[1:-2])

        if not key_hash or not device_id or not timestamp or not signature:
            raise InvalidTokenError("Invalid token format: empty parts")

        # Verify signature
        expected_sig = self._make_token_signature(key_hash, device_id, timestamp)
        if not hmac.compare_digest(signature, expected_sig):
            raise InvalidTokenError("Invalid token: signature mismatch")

        # Check token age — tokens expire after 30 days
        try:
            token_time = int(timestamp)
            age_seconds = int(time.time()) - token_time
            max_age_seconds = 30 * 24 * 60 * 60  # 30 days
            if age_seconds < 0:
                raise InvalidTokenError("Invalid token: timestamp is in the future")
            if age_seconds > max_age_seconds:
                raise InvalidTokenError("Device token expired. Please re-activate.")
        except ValueError:
            raise InvalidTokenError("Invalid token: bad timestamp")

        return key_hash, device_id, timestamp

    async def _try_refresh_expired_token(self, expired_token: str) -> Optional[LicenseInfo]:
        """Try to auto-refresh an expired token without requiring user to re-enter license key.

        Only refreshes if:
        - Token signature is valid (just expired, not tampered)
        - Device is still registered and active
        - License is still active and not expired

        Returns dict with license info + new token, or None if refresh not possible.
        """
        try:
            # Parse token without age check
            if not expired_token.startswith("KUKAI-DT-"):
                return None
            rest = expired_token[len("KUKAI-DT-"):]
            parts = rest.split("-")
            if len(parts) < 4:
                return None
            signature = parts[-1]
            timestamp = parts[-2]
            key_hash = parts[0]
            device_id = "-".join(parts[1:-2])

            # Verify signature is valid (token wasn't tampered, just expired)
            expected_sig = self._make_token_signature(key_hash, device_id, timestamp)
            if not hmac.compare_digest(signature, expected_sig):
                return None

            # Find device and license in DB
            cursor = await self._db.execute(
                "SELECT d.*, l.key, l.tier, l.daily_limit, l.expires_at, l.active as license_active "
                "FROM devices d JOIN licenses l ON d.license_key = l.key "
                "WHERE d.device_id = ? AND d.active = 1",
                (device_id,),
            )
            rows = await cursor.fetchall()
            if not rows:
                return None

            # Match correct license by key_hash
            row = None
            for candidate in rows:
                candidate_key = candidate[8] if len(candidate) > 8 else ""
                if isinstance(candidate_key, str):
                    h = hashlib.sha256(candidate_key.encode()).hexdigest()[:12]
                    if h == key_hash:
                        row = candidate
                        break
            if not row:
                return None

            # Check license is still active and not expired
            license_active = row[-1] if len(row) > 12 else 1
            if not license_active:
                return None

            expires_at = row[-2] if len(row) > 11 else ""
            if expires_at:
                from datetime import datetime, timezone
                try:
                    exp = datetime.fromisoformat(expires_at)
                    if exp < datetime.now(timezone.utc):
                        return None  # License expired
                except (ValueError, TypeError):
                    pass

            # All checks passed — generate new token
            license_key = row[8] if len(row) > 8 else ""
            new_token = self._create_device_token(license_key, device_id)

            # Update last_seen
            now_str = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE devices SET last_seen = ? WHERE device_id = ? AND license_key = ?",
                (now_str, device_id, license_key),
            )
            await self._db.commit()

            tier = row[9] if len(row) > 9 else "free"
            daily_limit = row[10] if len(row) > 10 else 0  # DISABLED: free trial period — 0 = unlimited

            logger.info("Token auto-refreshed for device %s (tier=%s)", device_id[:8], tier)

            info = LicenseInfo(
                key=row[8] if len(row) > 8 else "",
                tier=tier,
                max_devices=0,
                daily_limit=daily_limit,
                expires_at=expires_at,
                active=True,
            )
            info.refreshed_token = new_token  # Attach new token for client
            return info
        except Exception as e:
            logger.debug("Token refresh failed: %s", e)
            return None

    async def activate_license(
        self,
        key: str,
        device_id: str,
        hwid: str = "",
        device_name: str = "",
    ) -> dict[str, Any]:
        """Activate a license for a device. Returns device token.

        Checks:
        1. License exists and is active
        2. License is not expired
        3. Device limit not exceeded (or device already registered)
        """
        # Look up license
        cursor = await self._db.execute(
            "SELECT * FROM licenses WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if not row:
            raise LicenseNotFoundError(f"License not found: {key}")

        license_tier = row[2]
        max_devices = row[3]
        daily_limit = row[4]
        expires_at = row[6]
        active = bool(row[7])

        if not active:
            raise LicenseInactiveError("License is deactivated")

        # Check expiration
        exp_dt = datetime.fromisoformat(expires_at)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt < datetime.now(timezone.utc):
            raise LicenseExpiredError("License has expired")

        # Check if this device is already registered
        cursor2 = await self._db.execute(
            "SELECT * FROM devices WHERE license_key = ? AND device_id = ?",
            (key, device_id),
        )
        existing_device = await cursor2.fetchone()

        if existing_device:
            # Re-activate if deactivated, update last_seen
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE devices SET active = 1, last_seen = ?, hwid = ? WHERE license_key = ? AND device_id = ?",
                (now, hwid or existing_device[3], key, device_id),
            )
            await self._db.commit()
        else:
            # HWID cross-license check for free-tier licenses.
            # Prevents a single machine from creating multiple free accounts
            # to bypass the daily request limit.
            # Paid tiers (pro/team/enterprise) are exempt — a company might
            # legitimately have multiple licenses on one workstation.
            if hwid and license_tier == "free":
                existing_hwid_devices = await self.get_devices_by_hwid(hwid)
                for dev_record in existing_hwid_devices:
                    if (
                        dev_record["license_key"] != key
                        and dev_record["license_tier"] == "free"
                    ):
                        raise HwidConflictError(
                            "This machine is already registered with another account. "
                            "Use your existing license key."
                        )

            # Check device count (0 means unlimited)
            if max_devices > 0:
                cursor3 = await self._db.execute(
                    "SELECT COUNT(*) FROM devices WHERE license_key = ? AND active = 1",
                    (key,),
                )
                count_row = await cursor3.fetchone()
                current_count = count_row[0] if count_row else 0
                if current_count >= max_devices:
                    raise DeviceLimitError(
                        f"Maximum devices ({max_devices}) reached for this license. "
                        f"Deactivate an existing device first."
                    )

            # Register new device
            now = datetime.now(timezone.utc).isoformat()
            dev_id_record = str(uuid.uuid4())
            await self._db.execute(
                """INSERT INTO devices (id, license_key, device_id, hwid, name, last_seen, created_at, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (dev_id_record, key, device_id, hwid, device_name, now, now),
            )
            await self._db.commit()

        # Generate token
        token = self._create_device_token(key, device_id)

        logger.info("License activated: key=%s device=%s tier=%s", key, device_id, license_tier)

        return {
            "device_token": token,
            "tier": license_tier,
            "daily_limit": daily_limit,
            "expires_at": expires_at,
        }

    async def validate_device(self, device_token: str) -> LicenseInfo:
        """Validate a device token and return the associated license info.

        Checks:
        1. Token signature is valid
        2. Device is registered and active
        3. License is active and not expired
        """
        try:
            key_hash, device_id, _timestamp = self._verify_device_token(device_token)
        except InvalidTokenError as e:
            if "expired" in str(e).lower():
                # Token expired — try to auto-refresh
                refreshed = await self._try_refresh_expired_token(device_token)
                if refreshed:
                    return refreshed  # Returns new token info + refreshed_token
                raise  # Re-raise if refresh failed
            raise

        # Find the device by device_id, matching the correct license via key_hash
        cursor = await self._db.execute(
            "SELECT d.*, l.key, l.tier, l.max_devices, l.daily_limit, l.expires_at, l.active as license_active "
            "FROM devices d JOIN licenses l ON d.license_key = l.key "
            "WHERE d.device_id = ? AND d.active = 1",
            (device_id,),
        )
        rows = await cursor.fetchall()

        if not rows:
            raise InvalidTokenError("Device not found or deactivated")

        # Match the correct license by key_hash (handles same device_id on different licenses)
        row = None
        for candidate in rows:
            candidate_key = candidate[8]  # l.key
            expected_hash = hashlib.sha256(candidate_key.encode("utf-8")).hexdigest()[:12]
            if hmac.compare_digest(key_hash, expected_hash):
                row = candidate
                break

        if not row:
            raise InvalidTokenError("Token key hash mismatch")

        license_key = row[8]   # l.key

        tier = row[9]         # l.tier
        max_devices = row[10]  # l.max_devices
        daily_limit = row[11]  # l.daily_limit
        expires_at = row[12]   # l.expires_at
        license_active = bool(row[13])  # l.active

        if not license_active:
            raise LicenseInactiveError("License is deactivated")

        # Check expiration
        exp_dt = datetime.fromisoformat(expires_at)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt < datetime.now(timezone.utc):
            raise LicenseExpiredError("License has expired")

        # Update last_seen
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ? AND license_key = ?",
            (now, device_id, license_key),
        )
        await self._db.commit()

        return LicenseInfo(
            key=license_key,
            tier=tier,
            max_devices=max_devices,
            daily_limit=daily_limit,
            expires_at=expires_at,
            active=license_active,
        )

    async def verify_device_hwid(self, device_token: str, client_hwid: str) -> bool:
        """Verify that the connecting device's HWID matches the one stored at activation.

        Args:
            device_token: The device token to verify.
            client_hwid: The HWID reported by the connecting client.

        Returns:
            True if HWID matches or if no HWID was stored (backward compat).
            False if HWID mismatch.
        """
        if not client_hwid:
            # No HWID provided — skip check (backward compat for older clients)
            return True

        key_hash, device_id, _timestamp = self._verify_device_token(device_token)

        # Find the device record, matching correct license via key_hash
        cursor = await self._db.execute(
            "SELECT d.hwid, d.license_key FROM devices d "
            "JOIN licenses l ON d.license_key = l.key "
            "WHERE d.device_id = ? AND d.active = 1",
            (device_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return False

        # Match correct license by key_hash (handles same device_id on different licenses)
        stored_hwid = None
        license_key = None
        for candidate in rows:
            expected_hash = hashlib.sha256(candidate[1].encode("utf-8")).hexdigest()[:12]
            if hmac.compare_digest(key_hash, expected_hash):
                stored_hwid = candidate[0]
                license_key = candidate[1]
                break

        if license_key is None:
            return False

        # If no HWID was stored at activation, allow (backward compat)
        if not stored_hwid:
            # Update stored HWID for future checks
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE devices SET hwid = ?, last_seen = ? WHERE device_id = ? AND license_key = ?",
                (client_hwid, now, device_id, license_key),
            )
            await self._db.commit()
            return True

        # Compare HWIDs
        if not hmac.compare_digest(stored_hwid, client_hwid):
            logger.warning(
                "HWID mismatch for device_id=%s: stored=%s client=%s",
                device_id, stored_hwid[:8] + "...", client_hwid[:8] + "...",
            )
            return False

        # Update last_seen
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ? AND license_key = ?",
            (now, device_id, license_key),
        )
        await self._db.commit()
        return True

    # --- Rate limiting (sliding window) ---

    async def check_rate_limit_window(self, device_token: str) -> dict[str, Any]:
        """Check rate limit using a sliding window.

        Returns dict: {"allowed": True, "remaining": int, "reset_minutes": int}
        Raises DailyLimitError if limit exceeded.

        Windows by tier:
          - free:       20 requests per rolling 7 days
          - pro:        50 requests per rolling 5 hours
          - team/ent:   unlimited
        """
        license_info = await self.validate_device(device_token)
        tier = license_info.tier

        tier_config = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        window_hours = tier_config.get("window_hours", 0)
        max_requests = tier_config.get("window_limit", 0)

        # 0 = unlimited (team/enterprise)
        if max_requests == 0 or window_hours == 0:
            return {"allowed": True, "remaining": -1, "reset_minutes": 0, "tier": tier, "license_key": license_info.key}

        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=window_hours)).isoformat()

        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM request_log WHERE device_token = ? AND created_at >= ?",
            (device_token, cutoff),
        )
        row = await cursor.fetchone()
        count = row[0] if row else 0

        if count >= max_requests:
            # Find the oldest request in the window to calculate reset time
            oldest_cursor = await self._db.execute(
                "SELECT created_at FROM request_log WHERE device_token = ? AND created_at >= ? ORDER BY created_at ASC LIMIT 1",
                (device_token, cutoff),
            )
            oldest_row = await oldest_cursor.fetchone()
            if oldest_row:
                oldest_dt = datetime.fromisoformat(oldest_row[0])
                if oldest_dt.tzinfo is None:
                    oldest_dt = oldest_dt.replace(tzinfo=timezone.utc)
                reset_time = oldest_dt + timedelta(hours=window_hours) - now
                reset_minutes = max(1, int(reset_time.total_seconds() / 60))
            else:
                reset_minutes = 1

            if window_hours >= 24:
                window_desc = f"{window_hours // 24} дн."
            else:
                window_desc = f"{window_hours} ч."

            raise DailyLimitError(
                f"Лимит исчерпан ({max_requests} запросов за {window_desc}). "
                f"Восстановление через {reset_minutes} мин. "
                f"Осталось: 0/{max_requests}."
            )

        remaining = max_requests - count - 1  # -1 because this request will be logged
        return {"allowed": True, "remaining": remaining, "reset_minutes": 0, "tier": tier, "license_key": license_info.key}

    async def log_request(self, device_token: str, license_key: str = "") -> None:
        """Log a request timestamp for sliding window rate limiting."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO request_log (device_token, license_key, created_at) VALUES (?, ?, ?)",
            (device_token, license_key, now),
        )
        await self._db.commit()

    async def cleanup_request_log(self) -> int:
        """Delete request_log entries older than 7 days to prevent table bloat.

        Returns number of deleted rows.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM request_log WHERE created_at < ?",
            (cutoff,),
        )
        await self._db.commit()
        return cursor.rowcount

    # --- Device management ---

    async def deactivate_device(self, device_token: str) -> bool:
        """Deactivate a device by its token (scoped to the token's license)."""
        key_hash, device_id, _timestamp = self._verify_device_token(device_token)

        # Find the license_key from key_hash to scope deactivation correctly
        cursor = await self._db.execute(
            "SELECT key FROM licenses WHERE active = 1"
        )
        license_key = None
        for row in await cursor.fetchall():
            if hmac.compare_digest(
                hashlib.sha256(row[0].encode()).hexdigest()[:12], key_hash
            ):
                license_key = row[0]
                break

        if not license_key:
            return False

        result = await self._db.execute(
            "UPDATE devices SET active = 0 WHERE license_key = ? AND device_id = ? AND active = 1",
            (license_key, device_id),
        )
        await self._db.commit()

        if result.rowcount > 0:
            logger.info("Device deactivated: device_id=%s", device_id)
            return True
        return False

    async def deactivate_device_by_id(self, license_key: str, device_id: str) -> bool:
        """Deactivate a specific device under a license. Admin operation."""
        result = await self._db.execute(
            "UPDATE devices SET active = 0 WHERE license_key = ? AND device_id = ?",
            (license_key, device_id),
        )
        await self._db.commit()

        if result.rowcount > 0:
            logger.info("Device deactivated by admin: key=%s device=%s", license_key, device_id)
            return True
        return False

    async def get_license_devices(self, key: str) -> list[dict[str, Any]]:
        """Get all devices for a license key."""
        cursor = await self._db.execute(
            "SELECT * FROM devices WHERE license_key = ? ORDER BY created_at DESC",
            (key,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "license_key": row[1],
                "device_id": row[2],
                "hwid": row[3],
                "name": row[4],
                "last_seen": row[5],
                "created_at": row[6],
                "active": bool(row[7]),
            }
            for row in rows
        ]

    async def get_devices_by_hwid(self, hwid: str) -> list[dict[str, Any]]:
        """Get all active device records across ALL licenses that share this HWID.

        Used for cross-license HWID conflict detection.

        Args:
            hwid: Hardware ID to search for

        Returns:
            List of device record dicts (with license_key, device_id, etc.)
        """
        if not hwid:
            return []
        cursor = await self._db.execute(
            """SELECT d.*, l.tier
               FROM devices d
               JOIN licenses l ON d.license_key = l.key
               WHERE d.hwid = ? AND d.active = 1
               ORDER BY d.created_at DESC""",
            (hwid,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "license_key": row[1],
                "device_id": row[2],
                "hwid": row[3],
                "name": row[4],
                "last_seen": row[5],
                "created_at": row[6],
                "active": bool(row[7]),
                "license_tier": row[8],
            }
            for row in rows
        ]

    async def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent audit log entries (from the main audit_log table)."""
        cursor = await self._db.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "session_id": row[1],
                "device_id": row[2],
                "action": row[3],
                "details": row[4],
                "result": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]
