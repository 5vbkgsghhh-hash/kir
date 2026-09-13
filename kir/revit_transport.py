"""One explicitly selected local Connector exchange, never an execution verdict.

The trusted helper is explicitly provided. Credentials/source travel only over
stdin; no discovery guessing, fallback backend, mutation retry or fake native
receipt occurs. After a helper starts, failed delivery is always unknown.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
from pathlib import Path
import subprocess
import threading
import time

from kir.connector_result import _json, _precondition, _target
from kir.revit_connector import CONNECTOR_PROTOCOL, MAX_FRAME_BYTES, _uuid
from kir.revit_discovery import DiscoveryAdvertisement


MAX_STDERR_BYTES = 4096
_CLEANUP_SECONDS = 5.0
_CORE = {"protocol", "request_id", "target", "session_id", "token", "kind", "timeout_ms"}
_FIELDS = {
    "ping": set(), "context": set(), "receipt": {"operation_id"},
    "recover_receipt": {"operation_id", "recovery_target"},
    "execute": {"operation_id", "source", "source_sha256", "precondition"},
    "cancel_before_start": {"operation_id", "source_sha256", "precondition"},
}
_HELPER_PHASES = frozenset({"arguments", "stdin", "request_validation", "connect",
                            "server_identity", "request_write", "response_read", "stdout"})
# Safe names owned by Kir.Revit.PipeClient.Program, never free-form child text.
_HELPER_CODES = {
    "invalid_arguments": frozenset({"arguments"}),
    "unsupported_platform": frozenset({"arguments"}),
    "request_budget_exceeded": frozenset({"stdin", "request_validation"}),
    "invalid_request": frozenset({"stdin", "request_validation"}),
    "server_identity_unavailable": frozenset({"server_identity"}),
    "server_pid_mismatch": frozenset({"server_identity"}),
    "deadline_exceeded": _HELPER_PHASES,
    "exchange_failed": _HELPER_PHASES,
}


class ConnectorTransportError(RuntimeError):
    def __init__(self, code: str, phase: str, *, delivery: str):
        self.code, self.phase, self.delivery = code, phase, delivery
        self.may_retry = False
        # Never include payload, token, source, argv, paths or untrusted stderr.
        super().__init__(f"{code}: {phase}; delivery={delivery}; retry not permitted")


def _helper_diagnostic(raw: bytes) -> tuple[str, str] | None:
    """Accept only safe code/phase names, not claims about delivery or retry."""
    try:
        value, _ = _json(raw, MAX_STDERR_BYTES)
        if (not isinstance(value, dict) or set(value) != {
                "schema", "code", "phase", "request_may_have_been_sent", "retry_permitted"}
                or value["schema"] != "kir-pipe-client-diagnostic/1"
                or type(value["request_may_have_been_sent"]) is not bool
                or type(value["retry_permitted"]) is not bool or value["retry_permitted"] is not False):
            return None
        code, phase = value["code"], value["phase"]
        if type(code) is not str or type(phase) is not str or phase not in _HELPER_CODES.get(code, ()):
            return None
        return "pipe_client_" + code, phase
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return None


def _require(value: bool, code: str, phase="request_validation") -> None:
    if not value:
        raise ConnectorTransportError(code, phase, delivery="not_attempted")


def _admit(advertisement: DiscoveryAdvertisement, request: bytes) -> None:
    _require(type(advertisement) is DiscoveryAdvertisement, "invalid_advertisement")
    _require(type(request) is bytes, "invalid_request")
    try:
        payload, _ = _json(request, MAX_FRAME_BYTES)
        _require(isinstance(payload, dict), "invalid_request")
        kind = payload.get("kind")
        _require(isinstance(kind, str) and kind in _FIELDS, "invalid_request")
        _require(set(payload) == _CORE | _FIELDS[kind], "invalid_request")
        credentials = advertisement.credentials
        _require(payload["protocol"] == CONNECTOR_PROTOCOL and _target(payload["target"]) == credentials.target
                 and payload["session_id"] == credentials.session_id, "route_mismatch")
        token = payload["token"]
        _require(isinstance(token, str) and hmac.compare_digest(token.encode("utf-8"), credentials.token.encode("utf-8")), "token_mismatch")
        _require(_uuid(payload["request_id"], "request_id") == payload["request_id"], "invalid_request")
        _require(type(payload["timeout_ms"]) is int and 1000 <= payload["timeout_ms"] <= 300000, "invalid_request")
        if "operation_id" in payload:
            _uuid(payload["operation_id"], "operation_id")
        if kind == "recover_receipt":
            _target(payload["recovery_target"])
        if kind == "cancel_before_start":
            digest = payload["source_sha256"]
            _require(type(digest) is str and len(digest) == 64
                     and all(c in "0123456789abcdefABCDEF" for c in digest), "invalid_request")
            _precondition(payload["precondition"])
        if kind == "execute":
            import hashlib
            source = payload["source"]
            _require(isinstance(source, str) and bool(source.strip()), "invalid_request")
            _require(len(source.encode("utf-16-le")) // 2 <= 6 * 1024 * 1024, "source_budget_exceeded")
            _require(isinstance(payload["source_sha256"], str)
                     and hashlib.sha256(source.encode("utf-8")).hexdigest() == payload["source_sha256"].lower(), "source_hash_mismatch")
            _precondition(payload["precondition"])
        _require(advertisement.advertised_unexpired(now=datetime.now(timezone.utc)), "advertisement_expired")
    except ConnectorTransportError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
        raise ConnectorTransportError("invalid_request", "request_validation", delivery="not_attempted") from None


def validate_exchange_inputs(advertisement: DiscoveryAdvertisement, request: bytes, *,
                             client_path: str | Path, timeout_ms: int = 120000) -> Path:
    """Validate request/session and local helper path without starting a process.

    This point-in-time check is not a connection probe, binary verification,
    document lease or permission to replay. Exchange repeats it before launch;
    expiry, file replacement and connection failures can still occur afterwards.
    """
    _admit(advertisement, request)
    _require(type(timeout_ms) is int and 1000 <= timeout_ms <= 300000, "invalid_timeout", "preparation")
    try:
        path = Path(client_path)
        _require(path.is_absolute() and path.is_file(), "client_unavailable", "preparation")
    except (OSError, TypeError, ValueError):
        raise ConnectorTransportError("client_unavailable", "preparation", delivery="not_attempted") from None
    return path


def exchange(advertisement: DiscoveryAdvertisement, request: bytes, *,
             client_path: str | Path, timeout_ms: int = 120000) -> bytes:
    """Send exact bytes once; return exact response bytes, NOT a BIM result.

    The response still requires the existing context/write binding assessor.
    Even a before-connect helper failure is delivery=unknown after process start:
    its diagnostic cannot prove absence of an earlier use of that operation ID.
    OS process creation itself has no hard cancellation guarantee.
    """
    path = validate_exchange_inputs(advertisement, request, client_path=client_path, timeout_ms=timeout_ms)
    args = [str(path), "exchange", "--pipe", advertisement.pipe_name,
            "--expected-server-pid", str(advertisement.process_id), "--timeout-ms", str(timeout_ms)]
    deadline = time.monotonic() + timeout_ms / 1000
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, shell=False)
    except (OSError, ValueError):
        raise ConnectorTransportError("client_start_failed", "start", delivery="not_attempted") from None

    output, stderr = bytearray(), bytearray()
    failed = threading.Event()
    fault: list[tuple[str, str]] = []
    lock = threading.Lock()
    threads = []

    def error(code, phase):
        with lock:
            if not fault:
                fault.append((code, phase))
        failed.set()

    def drain(stream, retained, maximum, phase):
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                if len(retained) + len(chunk) > maximum:
                    error("helper_output_budget_exceeded", phase)
                    break
                retained.extend(chunk)
        except (OSError, ValueError):
            error("helper_io_failed", phase)

    def send():
        try:
            view = memoryview(request)
            offset = 0
            while offset < len(view):
                written = process.stdin.write(view[offset:offset + 65536])
                if not written:
                    raise OSError("closed stdin")
                offset += written
            process.stdin.close()
        except (OSError, ValueError):
            error("helper_io_failed", "stdin")

    result_error = None
    cleanup_ok = True
    try:
        for action in (lambda: drain(process.stdout, output, MAX_FRAME_BYTES, "stdout"),
                       lambda: drain(process.stderr, stderr, MAX_STDERR_BYTES, "stderr"), send):
            thread = threading.Thread(target=action, daemon=True)
            threads.append(thread)
            thread.start()
        while process.poll() is None and not failed.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result_error = ("helper_timeout", "exchange")
                break
            failed.wait(min(remaining, 0.02))
        if result_error is None and fault:
            result_error = fault[0]
        if result_error is None:
            for thread in threads:
                thread.join(max(0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in threads):
                result_error = ("helper_timeout", "io_completion")
            elif fault:
                result_error = fault[0]
            elif process.returncode != 0:
                result_error = ("helper_failed", "exit")
            elif stderr:
                result_error = ("helper_protocol_contradiction", "stderr")
    except Exception:
        result_error = ("helper_supervision_failed", "exchange")
    finally:
        cleanup_deadline = time.monotonic() + _CLEANUP_SECONDS
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=max(0.01, cleanup_deadline - time.monotonic()))
        except (OSError, subprocess.TimeoutExpired):
            cleanup_ok = False
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
        for thread in threads:
            if thread.ident is not None:
                thread.join(max(0, cleanup_deadline - time.monotonic()))
        cleanup_ok = cleanup_ok and all(not thread.is_alive() for thread in threads)
    if not cleanup_ok:
        raise ConnectorTransportError("helper_cleanup_unconfirmed", "cleanup", delivery="unknown")
    if result_error is not None:
        if process.returncode == 2 and result_error in {("helper_failed", "exit"), ("helper_io_failed", "stdin")}:
            result_error = _helper_diagnostic(bytes(stderr)) or result_error
        raise ConnectorTransportError(*result_error, delivery="unknown")
    raw = bytes(output)
    try:
        payload, _ = _json(raw, MAX_FRAME_BYTES)
        if not isinstance(payload, dict):
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise ConnectorTransportError("invalid_helper_response", "response_validation", delivery="unknown") from None
    return raw


__all__ = ["ConnectorTransportError", "validate_exchange_inputs", "exchange"]
