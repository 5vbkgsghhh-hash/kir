"""Fixtures for tier1/tier3 integration tests.

The `compile_service` fixture reuses an already-running compile-service on
port 52412 if present, otherwise boots one via `dotnet run -c Release` and
tears it down at session end. Tests that depend on this fixture should be
marked `tier1`.
"""
from __future__ import annotations
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[4]  # backend/
COMPILE_SERVICE_DIR = BACKEND_ROOT / "compile-service"
# Wave 7.5 follow-up: env override lets us point tier1 at a port that isn't
# 52412 (e.g. when Navisworks dev-backend has already claimed it). The auto-
# boot path still binds to 52412 by default unless this env is set.
_DEFAULT_COMPILE_URL = os.environ.get(
    "KUKAI_COMPILE_SERVICE_URL", "http://127.0.0.1:52412"
)


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _compile_service_responding(base_url: str) -> bool:
    """Port + /health JSON check — catches the case where SOMETHING is on the
    port but it isn't compile-service (Wave 7.5 hit this with Navisworks
    backend squatting on 52412)."""
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{base_url}/health")
            if r.status_code != 200:
                return False
            return r.json().get("status") == "ready"
    except (httpx.HTTPError, ValueError):
        return False


@pytest.fixture(scope="session")
def compile_service():
    """Boot compile-service if not already running; yield base URL.

    Honors `KUKAI_COMPILE_SERVICE_URL` env override; falls back to
    http://127.0.0.1:52412 (canonical). If the URL responds with the
    expected /health payload, reuse it. Otherwise try to boot on 52412.
    """
    base_url = _DEFAULT_COMPILE_URL
    if _compile_service_responding(base_url):
        yield base_url
        return
    # Auto-boot path stays on 52412 (canonical)
    COMPILE_PORT = 52412
    base_url = f"http://127.0.0.1:{COMPILE_PORT}"
    if _compile_service_responding(base_url):
        yield base_url
        return
    if shutil.which("dotnet") is None:
        pytest.skip("dotnet CLI not available")
    if not COMPILE_SERVICE_DIR.exists():
        pytest.skip(f"compile-service dir missing: {COMPILE_SERVICE_DIR}")

    proc = subprocess.Popen(
        ["dotnet", "run", "--project", str(COMPILE_SERVICE_DIR), "-c", "Release"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 60.0
    ready = False
    while time.monotonic() < deadline:
        if _port_open(COMPILE_PORT):
            try:
                with httpx.Client(timeout=2.0) as c:
                    r = c.get(f"{base_url}/health")
                    if r.status_code == 200 and r.json().get("status") == "ready":
                        ready = True
                        break
            except httpx.HTTPError:
                pass
        time.sleep(0.5)
    if not ready:
        proc.kill()
        pytest.fail("compile-service failed to come up within 60s")

    yield base_url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def vertex_env_ready() -> bool:
    """Skip marker for tests that need real Vertex creds."""
    required = (
        "KUKAI_VERTEX_AI_API_KEY",
        "KUKAI_VERTEX_AI_PROJECT",
        "KUKAI_VERTEX_AI_LOCATION",
    )
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        pytest.skip(f"Vertex env missing: {missing}")
    return True
