"""Shared dependencies for API endpoints.

Auth modes:
  - Local (auth_enabled=False): No auth required. All endpoints open.
  - Remote (auth_enabled=True): Device token required on all endpoints
    except GET / (HTML) and /kukai_config.js.

Device token is obtained via POST /license/activate and passed as:
  - HTTP: Authorization: Bearer {device_token}
  - WebSocket: ?device_token={device_token} query param
"""

from __future__ import annotations

import hmac
import logging
from typing import Any, Optional

from fastapi import Header, HTTPException, Query

from kukai.config import get_settings

logger = logging.getLogger(__name__)


async def _validate_token(
    device_token: str,
    api_key: str,
    device_id: str,
) -> dict[str, Any]:
    """Shared token validation logic for both HTTP and WebSocket auth.

    Handles:
      - KUKAI-DT- prefix detection in api_key field
      - Legacy API key fallback
      - License manager device validation

    Returns auth info dict on success, raises HTTPException on failure.
    """
    settings = get_settings()

    # S8 fix: HTML sends device token via api_key param.
    # If api_key looks like a device token, treat it as one.
    if not device_token and api_key and api_key.startswith("KUKAI-DT-"):
        device_token = api_key

    if not device_token:
        # Fall back to legacy API key check
        if settings.api_key and api_key and hmac.compare_digest(api_key, settings.api_key):
            return {
                "api_key": api_key,
                "device_id": device_id,
                "device_token": "",
                "tier": "pro",
                "daily_limit": 0,
                "authenticated": True,
            }
        raise HTTPException(
            status_code=401,
            detail="Требуется авторизация. Активируйте лицензию в настройках чата.",
        )

    # Validate device token via license manager
    from kukai.main import get_app_state

    state = get_app_state()
    if not state.license_manager:
        raise HTTPException(
            status_code=503,
            detail="Система лицензирования не инициализирована",
        )

    from kukai.licensing.license_manager import (
        InvalidTokenError,
        LicenseError,
        LicenseExpiredError,
        LicenseInactiveError,
    )

    try:
        license_info = await state.license_manager.validate_device(device_token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Недействительный токен устройства")
    except LicenseExpiredError:
        raise HTTPException(status_code=401, detail="Срок лицензии истёк")
    except LicenseInactiveError:
        raise HTTPException(status_code=401, detail="Лицензия деактивирована")
    except LicenseError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # Daily limit is NOT checked here — it would consume quota on read endpoints
    # (GET /status, GET /hints, etc.). Daily limit is enforced only in chat endpoints
    # (chat_ws.py and chat_http.py) where actual LLM usage occurs.

    return {
        "api_key": "",
        "device_id": device_id,
        "device_token": device_token,
        "tier": license_info.tier,
        "daily_limit": license_info.daily_limit,
        "authenticated": True,
    }


async def verify_device_token(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    x_kukai_device_id: Optional[str] = Header(None, alias="X-KUKAI-Device-Id"),
    x_kukai_identity_token: Optional[str] = Header(
        None, alias="X-KUKAI-Identity-Token"
    ),
) -> dict[str, Any]:
    """Verify device token or API key depending on auth mode.

    In auth_enabled mode:
      - Validates Authorization: Bearer {device_token}
      - Checks license validity and daily limits
      - Returns license info dict

    In local mode:
      - Falls back to old api_key check (or no auth at all)
      - Returns basic device info dict

    Step 11 (KUKAI_SIGNED_IDENTITY, flag-gated): a valid X-KUKAI-Identity-Token
    header resolves to its server-minted signed identity, which replaces the
    client-supplied device id as the effective tenancy key for HTTP endpoints
    (session ownership / export / clear). Flag OFF ⇒ passthrough, byte-identical.
    A raw device id shaped like a signed identity ("kid_…") is never trusted —
    that would let a client smuggle a victim's identity STRING past ownership.
    """
    settings = get_settings()

    from kukai.security.identity import resolve_http_device
    effective_device_id = resolve_http_device(
        x_kukai_device_id or "", x_kukai_identity_token
    )

    if not settings.auth_enabled:
        # Local mode — no auth required (backwards compatible)
        return {
            "api_key": x_api_key or "",
            "device_id": effective_device_id,
            "device_token": "",
            "tier": "free",
            "daily_limit": settings.free_daily_limit,
            "authenticated": False,
        }

    # Remote mode — device token required
    device_token = _extract_bearer_token(authorization)

    return await _validate_token(
        device_token=device_token,
        api_key=x_api_key or "",
        device_id=effective_device_id,
    )


def _extract_bearer_token(authorization: Optional[str]) -> str:
    """Extract token from 'Bearer {token}' header value."""
    if not authorization:
        return ""
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


async def verify_ws_device_token(
    device_token: str = Query(""),
    api_key: str = Query(""),
    device_id: str = Query(""),
) -> dict[str, Any]:
    """Verify WebSocket query params. Returns device info.

    In auth_enabled mode: device_token query param is required.
    In local mode: optional api_key check (backwards compatible).
    """
    settings = get_settings()

    if not settings.auth_enabled:
        # Local mode — backwards compatible
        return {
            "api_key": api_key,
            "device_id": device_id,
            "device_token": "",
            "tier": "free",
            "daily_limit": settings.free_daily_limit,
            "authenticated": False,
        }

    return await _validate_token(
        device_token=device_token,
        api_key=api_key,
        device_id=device_id,
    )


# Backwards-compatible alias — used in existing imports
verify_api_key = verify_device_token
verify_ws_params = verify_ws_device_token
