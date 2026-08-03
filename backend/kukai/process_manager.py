"""Backend process manager — launched by the C# bridge to start/monitor the backend.

Features:
- Start the FastAPI backend as a subprocess (or in-process)
- Health monitoring via /status endpoint
- Auto-restart on crash (max 3 retries)
- Clean shutdown on SIGTERM/SIGINT/CTRL_BREAK
- Logging to file for diagnostics

Usage from bridge:
    start_backend.bat

Usage directly:
    python -m kukai.process_manager
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Defaults
# Bind on all interfaces so nginx on the Cloud.ru VPS can reach us over the
# WireGuard tunnel (peer IP 10.0.0.3). Access is restricted by Windows Firewall
# rule "KUKAI Backend (WG + localhost only)" — only 10.0.0.0/24 and 127.0.0.1
# can hit TCP 52411. Public network cannot reach it.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 52411
# Infinite retry — process manager must outlive any single crash. We used to
# exit after 3 failures, which masked disasters (Task Scheduler saw exit 0 and
# left the server dead). Large sentinel instead of changing the whole shape.
MAX_RESTART_ATTEMPTS = 10**9
HEALTH_CHECK_INTERVAL = 5  # seconds
STARTUP_TIMEOUT = 30  # seconds
HEALTH_CHECK_URL_TEMPLATE = "http://{host}:{port}/health"
# Consider backend "stable" after this many consecutive healthy checks —
# resets the backoff so a process that runs well for an hour doesn't carry
# startup-churn history forever.
STABLE_RESET_THRESHOLD = 12  # 12 * 5s = 1 minute of healthy operation
RESTART_BACKOFF_CAP_S = 60


class ProcessManager:
    """Manages the KUKI backend process lifecycle."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        max_restarts: int = MAX_RESTART_ATTEMPTS,
        log_file: Optional[str] = None,
    ):
        self._host = host
        self._port = port
        self._max_restarts = max_restarts
        self._log_file = log_file
        self._process: Optional[subprocess.Popen] = None
        self._log_handle = None
        self._restart_count = 0
        self._running = False
        # When binding 0.0.0.0 (all interfaces), health checks must connect via
        # loopback — Windows TCP stack does not treat 0.0.0.0 as a routable
        # destination. Same for IPv6 wildcard.
        health_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        self._health_url = HEALTH_CHECK_URL_TEMPLATE.format(host=health_host, port=port)

    @property
    def is_running(self) -> bool:
        """Check if the managed process is running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def restart_count(self) -> int:
        return self._restart_count

    def start(self) -> bool:
        """Start the backend process. Returns True if started successfully."""
        if self.is_running:
            logger.info("Backend already running (PID %d)", self._process.pid)
            return True

        python_exe = sys.executable
        backend_dir = Path(__file__).parent.parent  # backend/
        main_module = "kukai.main:app"

        cmd = [
            python_exe, "-m", "uvicorn",
            main_module,
            "--host", self._host,
            "--port", str(self._port),
            "--log-level", "info",
            "--no-access-log",
        ]

        log_handle = None
        if self._log_file:
            log_path = Path(self._log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "a", encoding="utf-8")

        try:
            self._process = subprocess.Popen(
                cmd,
                cwd=str(backend_dir),
                stdout=log_handle or subprocess.DEVNULL,
                stderr=log_handle or subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self._log_handle = log_handle
            logger.info("Backend started (PID %d) on %s:%d", self._process.pid, self._host, self._port)
        except Exception as e:
            logger.error("Failed to start backend: %s", e)
            if log_handle:
                log_handle.close()
            return False

        # Wait for the server to become healthy
        return self._wait_for_healthy()

    def stop(self) -> None:
        """Stop the backend process gracefully."""
        if self._process is None:
            return

        if not self.is_running:
            self._process = None
            return

        pid = self._process.pid
        logger.info("Stopping backend (PID %d)...", pid)

        try:
            # Send SIGTERM (or TerminateProcess on Windows)
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
                logger.info("Backend stopped gracefully (PID %d)", pid)
            except subprocess.TimeoutExpired:
                logger.warning("Backend did not stop gracefully, killing (PID %d)", pid)
                self._process.kill()
                self._process.wait(timeout=5)
        except Exception as e:
            logger.error("Error stopping backend: %s", e)
        finally:
            self._process = None
            if self._log_handle:
                self._log_handle.close()
                self._log_handle = None

    def check_health(self) -> bool:
        """Check if the backend is healthy via /status endpoint."""
        try:
            resp = httpx.get(self._health_url, timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    def run_forever(self) -> None:
        """Run the process manager loop — start, monitor, auto-restart.

        This is the main entry point when running as a standalone process manager.
        Blocks until shutdown signal received or max restarts exceeded.
        """
        self._running = True
        self._restart_count = 0

        # Register signal handlers for clean shutdown
        _register_shutdown(self._shutdown)

        logger.info("Process manager starting (max restarts: %d)", self._max_restarts)

        consecutive_healthy = 0
        while self._running:
            if not self.is_running:
                if self._restart_count > 0:
                    # Exponential backoff, capped so we never wait too long.
                    delay = min(RESTART_BACKOFF_CAP_S, 2 ** min(self._restart_count, 6))
                    logger.warning(
                        "Backend crashed. Restart attempt %d in %ds...",
                        self._restart_count + 1, delay,
                    )
                    time.sleep(delay)

                success = self.start()
                if not success:
                    self._restart_count += 1
                    continue

                if self._restart_count > 0:
                    logger.info("Backend restarted successfully (attempt %d)", self._restart_count + 1)
                self._restart_count = 0
                consecutive_healthy = 0

            # Monitor health
            time.sleep(HEALTH_CHECK_INTERVAL)

            if self.is_running and self.check_health():
                consecutive_healthy += 1
                if consecutive_healthy >= STABLE_RESET_THRESHOLD:
                    # Long-running stability — forget old restart history so
                    # the next isolated crash doesn't start with a huge backoff.
                    self._restart_count = 0
                continue

            if self.is_running and not self.check_health():
                # Process is running but not responding — might be stuck
                logger.warning("Backend process alive but not responding to health check")
                time.sleep(3)
                if self.is_running and not self.check_health():
                    logger.error("Backend unresponsive. Killing and restarting.")
                    self.stop()
                    self._restart_count += 1
                    consecutive_healthy = 0
                    continue

            if not self.is_running:
                exit_code = self._process.returncode if self._process else "unknown"
                logger.error("Backend process exited with code %s", exit_code)
                self._restart_count += 1
                consecutive_healthy = 0

        self.stop()
        logger.info("Process manager stopped")

    def _wait_for_healthy(self, timeout: float = STARTUP_TIMEOUT) -> bool:
        """Wait for the backend to respond to health checks."""
        start = time.time()
        while time.time() - start < timeout:
            if not self.is_running:
                logger.error("Backend process exited during startup")
                return False
            if self.check_health():
                logger.info("Backend is healthy")
                return True
            time.sleep(1)

        logger.error("Backend did not become healthy within %ds", timeout)
        return False

    def _shutdown(self) -> None:
        """Signal handler — initiate clean shutdown."""
        logger.info("Shutdown signal received")
        self._running = False


def _register_shutdown(callback: "Callable[[], None]") -> None:
    """Register shutdown handlers for various signals."""
    # SIGINT = Ctrl+C, SIGTERM = terminate
    signal.signal(signal.SIGINT, lambda s, f: callback())
    signal.signal(signal.SIGTERM, lambda s, f: callback())

    # Windows-specific: CTRL_BREAK_EVENT
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, lambda s, f: callback())
        except (AttributeError, ValueError):
            pass


def main() -> None:
    """Entry point for process manager."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    host = os.environ.get("KUKAI_HOST", DEFAULT_HOST)
    port = int(os.environ.get("KUKAI_PORT", str(DEFAULT_PORT)))
    log_file = os.environ.get("KUKAI_LOG_FILE", "")

    manager = ProcessManager(
        host=host,
        port=port,
        log_file=log_file or None,
    )
    manager.run_forever()


if __name__ == "__main__":
    main()
