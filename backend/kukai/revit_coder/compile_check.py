"""Helper to call Roslyn compile-service (port 52412) and parse result.

Compile-service is a separate process started independently from KUKI backend.
This helper provides an async wrapper for use from the revit_coder module.

Configurable via:
- KUKAI_COMPILE_SERVICE_URL (default http://127.0.0.1:52412)
- KUKAI_COMPILE_TIMEOUT_SEC (default 30)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


def _service_url() -> str:
    return os.getenv("KUKAI_COMPILE_SERVICE_URL", "http://127.0.0.1:52412")


def _timeout_sec() -> float:
    return float(os.getenv("KUKAI_COMPILE_TIMEOUT_SEC", "30"))


@dataclass
class CompileResult:
    """Result of Roslyn compile-check call."""
    ok: bool
    stderr: str
    latency_ms: int


async def compile_check(code: str) -> CompileResult:
    """Validate C# code body via local Roslyn compile-service.

    Never raises — returns CompileResult with ok=False on any failure.
    """
    started = time.monotonic()
    url = f"{_service_url().rstrip('/')}/compile"

    try:
        async with httpx.AsyncClient(timeout=_timeout_sec()) as client:
            r = await client.post(url, json={"code": code})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        latency = int((time.monotonic() - started) * 1000)
        return CompileResult(
            ok=False,
            stderr=f"Compile service returned {e.response.status_code}",
            latency_ms=latency,
        )
    except httpx.HTTPError as e:
        latency = int((time.monotonic() - started) * 1000)
        return CompileResult(
            ok=False,
            stderr=f"Compile service unreachable: {e}",
            latency_ms=latency,
        )

    latency = int((time.monotonic() - started) * 1000)
    if data.get("ok"):
        return CompileResult(ok=True, stderr="", latency_ms=latency)

    errors = data.get("errors", [])
    if errors:
        stderr = "\n".join(
            f"{e.get('code', '')}: {e.get('message', '')} (line {e.get('line', '?')})"
            for e in errors
        )
    else:
        stderr = "Unknown compile error"

    return CompileResult(ok=False, stderr=stderr, latency_ms=latency)
