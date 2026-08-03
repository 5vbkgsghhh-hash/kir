"""Step 11 — server-minted signed connection identity (the tenancy isolation key).

PROBLEM. The per-tenant isolation key everywhere (session ownership, project
memory, session persistence, per-device rate limits) is the CLIENT-SUPPLIED
``device_id``. Device ids leak (logs, screenshots, shared machines), so any
client can present a victim's device_id and read the victim's sessions and
project memory — the same cross-tenant class as the WAVE0 leak.

WHY NOT "just sign the device_id": the server would sign an attacker-chosen
victim id — signing proves nothing about who chose the value. The isolation
key must be something the client CANNOT choose:

    * the server MINTS a fresh RANDOM identity (``kid_<128-bit hex>``) —
      unguessable, never derived from client input;
    * signs it with the existing server secret (``Settings.get_server_secret``,
      the same secret that signs device tokens, persisted across restarts);
    * returns the signed token to the client (WS message ``{"type":
      "identity", "token": ...}``); the client stores it and re-presents it
      as ``identity_token`` on its ``auth``/``chat`` payloads.

Because the identity is server-random a client cannot TARGET a victim's
identity, and because it is HMAC-signed a client cannot FORGE one.

FLAG — ``KUKAI_SIGNED_IDENTITY`` (read at call time, default OFF):
    "0"/unset  OFF     Legacy behavior, byte-identical: client device_id is
                       the key, no identity messages are ever sent.
    "1"        COMPAT  Adoption bridge. A valid presented token becomes the
                       isolation key. No/invalid token ⇒ legacy device_id
                       fallback (existing users keep their history; a corrupt
                       token can never lock anyone out) + a minted token is
                       offered once per connection so clients can upgrade.
                       NOTE: compat does NOT yet stop a legacy-shaped spoof
                       (attacker sending a victim device_id with no token) —
                       that hole closes in strict, after clients adopt tokens.
    "strict"   STRICT  No fallback. No/invalid token ⇒ a FRESH minted identity
                       (stable within the connection). No code path keys
                       tenancy off a client-chosen value ⇒ spoofing closed.
                       Legacy device_id-keyed history is orphaned for clients
                       that have not adopted tokens (explicit migration cost).

FAIL-OPEN. Any INTERNAL identity error (secret unavailable, unexpected
exception) degrades to today's device_id behavior with a warning — identity
machinery must never produce a user-facing failure or lock a tenant out.
(An invalid TOKEN is not an "error": compat falls back, strict mints.)

SESSION NAMESPACING. When the tenant is a signed identity, the client-claimed
``session_id`` is replaced server-side by ``uuid5(NS, identity|claimed_id)`` —
full-length, deterministic (persistence across reconnects), and derived from
the unguessable identity, so two tenants claiming the same session_id can
never collide and an attacker cannot even ADDRESS a victim's session.
Legacy/fallback tenants keep the raw client session_id (no history orphaning
under compat).

ANTI-SMUGGLING. When the flag is ON, a client-supplied device_id that merely
LOOKS like a signed identity (``kid_...``) is never accepted as an effective
key (sanitized to ""), on every entry surface (WS payloads, HTTP
``X-KUKAI-Device-Id``). Otherwise an attacker could replay a victim's identity
STRING (which is not secret — only the signature is) through the device_id
channel and satisfy owner==requester checks.

TOPOLOGY. Per-connection identity holders live in ``chat_ws._conn_identities``
(process-local), consistent with the other live-connection maps and the
documented transport/StateStore split ("only the directory / serializable
state goes through the StateStore"). The deployment is single-worker
(``uvicorn --workers 1`` in kukai-backend.service); if that ever changes, the
holder map — like the WS registry itself — needs the StateStore directory.
The DB rows (sessions.device_id, project_memory.device_id) are shared state
already and need nothing new.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Prefix marking server-minted identities (also self-describing in DB rows:
# SELECT ... WHERE device_id LIKE 'kid_%' finds all identity-keyed data).
IDENTITY_PREFIX = "kid_"
# identity = kid_ + 32 hex chars (128 bits of server randomness)
_IDENTITY_HEX_CHARS = 32
_SIG_HEX_CHARS = 64  # full HMAC-SHA256, never truncated
_MAX_TOKEN_LEN = 256  # defensive parse bound for client-supplied tokens

# Deterministic namespace for identity-scoped session ids (uuid5).
_SESSION_NS = uuid.uuid5(uuid.NAMESPACE_URL, "kukai:signed-identity:session")


# ─── flag ────────────────────────────────────────────────────────────────────

def identity_mode() -> str:
    """Parse KUKAI_SIGNED_IDENTITY at call time: "off" | "compat" | "strict"."""
    raw = os.getenv("KUKAI_SIGNED_IDENTITY", "0").strip().lower()
    if raw in ("", "0", "off", "false", "no"):
        return "off"
    if raw in ("2", "strict"):
        return "strict"
    # "1", "on", "compat", anything explicitly enabled → the safe bridge mode
    return "compat"


def signed_identity_enabled() -> bool:
    return identity_mode() != "off"


# ─── secret ──────────────────────────────────────────────────────────────────

def _default_secret() -> str:
    """The existing server secret (config.py:get_server_secret) — stable across
    restarts (env KUKAI_SERVER_SECRET or persisted data/.server_secret)."""
    from kukai.config import get_settings

    return get_settings().get_server_secret()


# ─── mint / sign / verify ────────────────────────────────────────────────────

def is_signed_identity(value: Any) -> bool:
    """True when the string is shaped like a server-minted identity."""
    return isinstance(value, str) and value.startswith(IDENTITY_PREFIX)


def _signature(identity: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), identity.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def sign_identity(identity: str, secret: Optional[str] = None) -> str:
    """Token = ``<identity>.<hmac-sha256-hex>`` — opaque to the client."""
    if secret is None:
        secret = _default_secret()
    return f"{identity}.{_signature(identity, secret)}"


def mint_identity(secret: Optional[str] = None) -> tuple[str, str]:
    """Mint a FRESH server-random identity. Returns (identity, signed_token).

    The identity is never derived from any client-supplied value — that is the
    whole point: a client cannot choose (and therefore cannot target) it.
    """
    identity = IDENTITY_PREFIX + secrets.token_hex(_IDENTITY_HEX_CHARS // 2)
    return identity, sign_identity(identity, secret)


def verify_identity_token(token: Any, secret: Optional[str] = None) -> Optional[str]:
    """Return the embedded identity when the HMAC verifies; else None.

    Never raises on garbage input (client-supplied data).
    """
    try:
        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LEN:
            return None
        identity, sep, sig = token.rpartition(".")
        if not sep or not is_signed_identity(identity) or len(sig) != _SIG_HEX_CHARS:
            return None
        if len(identity) != len(IDENTITY_PREFIX) + _IDENTITY_HEX_CHARS:
            return None
        if secret is None:
            secret = _default_secret()
        if hmac.compare_digest(_signature(identity, secret), sig):
            return identity
        return None
    except Exception:  # noqa: BLE001 — verification must never break a request
        logger.warning("signed-identity: token verification errored (treated as invalid)",
                       exc_info=True)
        return None


# ─── session-id namespacing ──────────────────────────────────────────────────

def namespaced_session_id(identity: str, raw_session_id: Any) -> str:
    """Server-derived, full-length (32 hex) session id, scoped to the identity.

    Deterministic per (identity, client-claimed id) so the same client keeps
    its conversation across turns and reconnects; empty claimed id ⇒ a fresh
    random id (legacy "new chat per message" semantics, but full-length).
    """
    base = str(raw_session_id).strip() if raw_session_id else ""
    if not base:
        return uuid.uuid4().hex
    return uuid.uuid5(_SESSION_NS, f"{identity}|{base[:128]}").hex


# ─── per-connection holder + turn resolution ─────────────────────────────────

def new_holder() -> dict[str, Any]:
    """Per-WS-connection identity state (lives in chat_ws._conn_identities)."""
    return {"identity": None, "source": "none", "minted_sent": False}


def resolve_for_turn(
    data: Any,
    holder: dict[str, Any],
    device_id: str,
    secret: Optional[str] = None,
) -> tuple[str, bool, Optional[str]]:
    """Resolve the EFFECTIVE isolation key for one inbound message.

    Returns ``(tenant_id, from_signed_identity, mint_token_to_send_or_None)``.
    NEVER raises: any internal error fails open to (device_id, False, None) —
    i.e. exactly today's behavior.

    Priority (flag ON):
      1. valid ``identity_token`` in this message  → its identity
      2. identity already verified on this connection (holder) → it
      3. strict → mint a fresh identity (stable within the connection)
         compat → legacy device_id fallback (+ one-time mint OFFER so an
                  upgraded client can store a token and migrate itself)
    """
    try:
        mode = identity_mode()
        if mode == "off":
            return device_id, False, None
        if secret is None:
            secret = _default_secret()

        token = data.get("identity_token") if isinstance(data, dict) else None
        if token:
            identity = verify_identity_token(token, secret)
            if identity is not None:
                holder["identity"] = identity
                holder["source"] = "token"
                return identity, True, None
            logger.warning(
                "signed-identity: INVALID token presented (device_id=%s) — %s",
                str(device_id)[:16],
                "minting fresh (strict)" if mode == "strict" else "legacy fallback (compat)",
            )

        if holder.get("source") == "token" and holder.get("identity"):
            return str(holder["identity"]), True, None

        if mode == "strict":
            if holder.get("source") == "minted" and holder.get("identity"):
                return str(holder["identity"]), True, None
            identity, mint_token = mint_identity(secret)
            holder["identity"] = identity
            holder["source"] = "minted"
            holder["minted_sent"] = True
            return identity, True, mint_token

        # compat: legacy device_id stays the key; offer a token once per
        # connection. Anti-smuggling: a kid_-shaped device_id is a client
        # trying to replay someone's identity STRING through the legacy
        # channel — never accept it as an effective key.
        effective = "" if is_signed_identity(device_id) else device_id
        mint_token = None
        if not holder.get("minted_sent"):
            _identity, mint_token = mint_identity(secret)
            holder["minted_sent"] = True
        return effective, False, mint_token
    except Exception:  # noqa: BLE001 — identity must never break a chat turn
        logger.warning(
            "signed-identity: resolve failed — FAIL-OPEN to client device_id",
            exc_info=True,
        )
        return device_id, False, None


# ─── HTTP seam (dependencies.py / status.py) ─────────────────────────────────

def resolve_http_device(device_id: str, identity_token: Any) -> str:
    """Effective device identity for an HTTP request (flag-gated inside).

    Flag OFF → byte-identical passthrough. Flag ON → a valid
    ``X-KUKAI-Identity-Token`` yields its signed identity; otherwise the raw
    header value is kept UNLESS it is kid_-shaped (smuggling → sanitized to
    "", which deny-by-default ownership then refuses for owned sessions).
    """
    try:
        if not signed_identity_enabled():
            return device_id
        if identity_token:
            identity = verify_identity_token(identity_token)
            if identity is not None:
                return identity
        return "" if is_signed_identity(device_id) else device_id
    except Exception:  # noqa: BLE001 — fail-open to legacy behavior
        logger.warning("signed-identity: http resolve failed — fail-open", exc_info=True)
        return device_id


def owner_access_ok(owner: Any, requester: Any) -> bool:
    """Session-owner gate for the HTTP read/clear/export endpoints.

    Legacy semantics (and the EXACT flag-OFF truth table of the historical
    inline check): allow unless both sides are non-empty and differ —
    ``not (owner and requester and owner != requester)``.

    Flag ON, for identity-owned rows only: exact match required. The requester
    value can only equal a ``kid_`` identity when it came from a VERIFIED
    token (resolve_http_device), so the legacy empty-requester bypass is
    closed for identity-keyed data without touching legacy rows.
    """
    try:
        owner_s = owner or ""
        requester_s = requester or ""
        if signed_identity_enabled() and is_signed_identity(owner_s):
            return requester_s == owner_s
        return not (owner_s and requester_s and owner_s != requester_s)
    except Exception:  # noqa: BLE001 — fail-open to legacy semantics
        return not (owner and requester and owner != requester)
