"""Actual portable pipes/helper processes; injected PID and seeded receipts, not Revit."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
from uuid import uuid4

import pytest

from kir.connector_result import assess_connector_context_response, assess_connector_write_response
from kir.revit_connector import MAX_FRAME_BYTES, ContextPrecondition, SessionCredentials, prepare_execution
from kir.revit_discovery import load_discovery, scan_discovery
from kir.revit_transport import ConnectorTransportError, exchange

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "connector/revit/tests/PipeClient.Tests"


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def ready_response(request):
    """Synthetic Service.Ping shape; never evidence of real connectivity."""
    return {"protocol": request["protocol"], "request_id": request["request_id"], "target": request["target"],
            "session_id": request["session_id"], "ok": True, "status": "ready", "error": None,
            "context": None, "receipt": None}


def advertisement():
    return load_discovery(wire({
        "protocol": "kir-revit-connector/4",
        "target": {"journal_id": str(uuid4()), "instance_id": str(uuid4()), "revit_version": "2026"},
        "session_id": str(uuid4()), "token": "private-token-Ж😀", "pipe_name": "kir-absent-" + uuid4().hex,
        "process_id": 123,
        "expires_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z",
    }))


@pytest.fixture(scope="module")
def helper():
    configured = os.environ.get("KIR_PIPECLIENT_TEST_EXECUTABLE")
    if configured:
        # Explicit reuse for scoped runs. Caller owns build/source provenance;
        # a bad override must fail, never silently trigger a replacement build.
        executable = Path(configured)
        assert executable.is_absolute() and executable.is_file(), "configured test helper is unavailable"
        return executable
    if shutil.which("dotnet") is None:
        pytest.skip(".NET SDK absent; real helper lane not exercised")
    built = subprocess.run(["dotnet", "build", str(RUNNER / "PipeClient.Tests.csproj"),
                            "-c", "Release", "-p:NuGetAudit=false", "--nologo"],
                           capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    return RUNNER / "bin/Release/net8.0/PipeClient.Tests"


@pytest.fixture
def native_server(helper, tmp_path):
    processes = []

    def start(year="2026", mode="seeded"):
        root = tmp_path / uuid4().hex
        child = subprocess.Popen([str(helper), "--server", str(root), year, mode],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        processes.append((child, root))
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
        line = ready.get(timeout=15)
        assert line, child.stderr.read()
        declaration = json.loads(line)
        assert declaration["scope"] == "portable_pid_injection_seeded_receipts_not_invocation"
        catalog = scan_discovery(root / "discovery")
        assert len(catalog.advertisements) == 1
        record = catalog.advertisements[0]
        selected = catalog.select(target=record.credentials.target,
                                  session_id=record.credentials.session_id, now=datetime.now(timezone.utc))
        return selected, root

    yield start
    for child, root in processes:
        if root.exists():
            (root / "stop").touch()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()


@pytest.mark.parametrize("case", [
    "target", "session", "token", "protocol", "unknown", "duplicate",
    "bool_timeout", "expired", "oversize", "extra_json",
])
def test_bad_request_refuses_before_launch_without_secret_diagnostics(monkeypatch, case):
    record = advertisement()
    request = record.credentials.context_request(request_id=str(uuid4()))
    if case == "target": request["target"]["instance_id"] = str(uuid4())
    if case == "session": request["session_id"] = str(uuid4())
    if case == "token": request["token"] = "other-secret"
    if case == "protocol": request["protocol"] = "kir-revit-connector/3"
    if case == "unknown": request["extra"] = 1
    if case == "bool_timeout": request["timeout_ms"] = True
    if case == "expired": record = replace(record, _expiry_ticks=0)
    raw = wire(request)
    if case == "duplicate": raw = raw.replace(b'"kind":"context"', b'"kind":"context","kind":"context"')
    if case == "oversize": raw = b" " * (MAX_FRAME_BYTES + 1)
    if case == "extra_json": raw += b"{}"

    def forbidden(*args, **kwargs):
        raise AssertionError("prelaunch validation must not spawn")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(ConnectorTransportError) as caught:
        exchange(record, raw, client_path="/missing")
    assert caught.value.delivery == "not_attempted" and caught.value.may_retry is False
    assert record.credentials.token not in str(caught.value) and "other-secret" not in str(caught.value)


def test_discovery_context_prepare_transport_and_seeded_bound_result(native_server, helper):
    record, root = native_server()
    credentials = record.credentials
    request = credentials.context_request(request_id=str(uuid4()))
    raw_context = exchange(record, wire(request), client_path=helper, timeout_ms=10000)
    context = assess_connector_context_response(raw_context, credentials=credentials, request_id=request["request_id"])
    assert context.read_complete
    precondition = context.require_precondition(bind_view=True, bind_selection=True)
    assert precondition.document_key != context.snapshot["document_title"]
    artifact = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
                                 target=credentials.target, precondition=precondition, operation_id=str(uuid4()))
    request = artifact.execute_request(credentials, request_id=str(uuid4()))
    response = exchange(record, wire(request), client_path=helper, timeout_ms=10000)
    assessment = assess_connector_write_response(artifact, response, credentials=credentials, request_id=request["request_id"])
    assert assessment.ok and assessment.outcome.acceptance.value == "not_run"
    assert (root / "requests").read_text().splitlines() == ["context", "execute"]
    # The fixture explicitly seeded this receipt; generated Revit code did not run.


def test_two_servers_require_explicit_routes_without_cross_call(native_server, helper):
    first, root_a = native_server("2023")
    second, root_b = native_server("2026")
    for record in (second, first):
        request = record.credentials.context_request(request_id=str(uuid4()))
        response = exchange(record, wire(request), client_path=helper, timeout_ms=10000)
        result = assess_connector_context_response(response, credentials=record.credentials, request_id=request["request_id"])
        assert result.read_complete and result.target == record.credentials.target
    assert (root_a / "requests").read_text() == "context\n"
    assert (root_b / "requests").read_text() == "context\n"
    with pytest.raises(ConnectorTransportError, match="route_mismatch"):
        exchange(second, wire(first.credentials.context_request(request_id=str(uuid4()))), client_path=helper)
    assert (root_b / "requests").read_text() == "context\n"


def test_wrong_pid_prevents_server_receiving_request(native_server, helper, monkeypatch):
    record, root = native_server()
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", "wrong_pid")
    with pytest.raises(ConnectorTransportError) as caught:
        exchange(record, wire(record.credentials.context_request(request_id=str(uuid4()))),
                 client_path=helper, timeout_ms=3000)
    assert caught.value.delivery == "unknown" and caught.value.may_retry is False
    assert not (root / "requests").exists()


@pytest.mark.parametrize("case", [
    "abnormal", "oversize", "duplicate", "extra_json", "stderr_success", "stderr_flood", "hang",
])
def test_real_helper_faults_never_become_native_success_or_retry(helper, monkeypatch, tmp_path, case):
    record = advertisement()
    pid_path = tmp_path / "helper.pid"
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", case)
    monkeypatch.setenv("KIR_PIPE_TEST_PID_FILE", str(pid_path))
    with pytest.raises(ConnectorTransportError) as caught:
        exchange(record, wire(record.credentials.context_request(request_id=str(uuid4()))),
                 client_path=helper, timeout_ms=1000)
    assert caught.value.delivery == "unknown" and caught.value.may_retry is False
    assert record.credentials.token not in str(caught.value)
    assert pid_path.is_file()
    # Linux process evidence, not a Windows cleanup claim.
    assert not Path(f"/proc/{int(pid_path.read_text())}").exists()


def test_absent_pipe_is_unknown_without_retry(helper):
    record = advertisement()
    with pytest.raises(ConnectorTransportError) as caught:
        exchange(record, wire(record.credentials.context_request(request_id=str(uuid4()))),
                 client_path=helper, timeout_ms=1000)
    assert caught.value.delivery == "unknown" and caught.value.may_retry is False


def test_forged_stale_session_is_refused_by_actual_service_not_upgraded_to_context(native_server, helper):
    record, root = native_server()
    stale = replace(record, credentials=SessionCredentials(record.credentials.target, str(uuid4()), record.credentials.token))
    request = stale.credentials.context_request(request_id=str(uuid4()))
    raw = exchange(stale, wire(request), client_path=helper, timeout_ms=10000)
    assert json.loads(raw)["status"] == "session_mismatch"
    result = assess_connector_context_response(raw, credentials=stale.credentials, request_id=request["request_id"])
    assert not result.read_complete
    assert (root / "requests").read_text() == "context\n"  # Exactly one attempt.


def test_changed_source_is_refused_before_any_helper_launch(monkeypatch):
    record = advertisement()
    artifact = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
                                 target=record.credentials.target, precondition=ContextPrecondition("doc", 0), operation_id=str(uuid4()))
    request = artifact.execute_request(record.credentials, request_id=str(uuid4()))
    request["source"] += "changed-secret-source"
    def forbidden(*args, **kwargs):
        raise AssertionError("must refuse before launch")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(ConnectorTransportError, match="source_hash_mismatch") as caught:
        exchange(record, wire(request), client_path="/missing")
    assert caught.value.delivery == "not_attempted" and caught.value.may_retry is False
    assert "changed-secret-source" not in str(caught.value)


@pytest.mark.parametrize("value", ["Ж" * 1000, "😀" * 500], ids=["cyrillic", "astral"])
def test_original_1501_ops_request_reaches_pipe_byte_for_byte(native_server, helper, value):
    record, root = native_server("2023", "raw")
    program = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}] + [
        {"op": "set_param", "id": f"P{index}", "target": {"by": "ref", "value": "L"},
         "param": "Comments", "value": value} for index in range(1500)]}
    artifact = prepare_execution(program, target=record.credentials.target,
                                 precondition=ContextPrecondition("doc", 0), operation_id=str(uuid4()))
    request = wire(artifact.execute_request(record.credentials, request_id=str(uuid4())))
    # Source emission can grow while the original program remains unchanged.
    # Measure the encoded request against the protocol's real payload ceiling.
    assert MAX_FRAME_BYTES >= len(request) > 8_000_000
    response = exchange(record, request, client_path=helper, timeout_ms=30000)
    assert json.loads(response)["fixture"] == "raw_echo_not_execution"
    assert (root / "request.sha256").read_text() == hashlib.sha256(request).hexdigest()


def test_argv_contains_neither_token_nor_source(native_server, helper, monkeypatch):
    record, _ = native_server()
    artifact = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "ARGV_LEAK_SENTINEL"}]},
                                 target=record.credentials.target, precondition=ContextPrecondition("fixture-doc", 0), operation_id=str(uuid4()))
    request = artifact.execute_request(record.credentials, request_id=str(uuid4()))
    assert "ARGV_LEAK_SENTINEL" in request["source"]
    original = subprocess.Popen
    captured = []

    def inspect(args, **kwargs):
        captured.append(args)
        return original(args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", inspect)
    exchange(record, wire(request), client_path=helper, timeout_ms=10000)
    assert len(captured) == 1
    assert record.credentials.token not in " ".join(captured[0])
    assert request["request_id"] not in " ".join(captured[0])
    assert request["source"] not in " ".join(captured[0])
    assert "ARGV_LEAK_SENTINEL" not in " ".join(captured[0])


@pytest.mark.parametrize("relative", [True, False])
def test_invalid_helper_path_never_launches(monkeypatch, tmp_path, relative):
    record = advertisement()
    def forbidden(*args, **kwargs):
        raise AssertionError("missing helper must not spawn")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    path = Path("relative-helper") if relative else tmp_path / "missing-helper"
    with pytest.raises(ConnectorTransportError, match="client_unavailable") as caught:
        exchange(record, wire(record.credentials.context_request(request_id=str(uuid4()))), client_path=path)
    assert caught.value.delivery == "not_attempted" and caught.value.may_retry is False


def test_blocked_helper_stdin_on_large_request_is_killed_and_writer_joins(helper, monkeypatch, tmp_path):
    record = advertisement()
    artifact = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
                                 target=record.credentials.target, precondition=ContextPrecondition("doc", 0), operation_id=str(uuid4()))
    request = artifact.execute_request(record.credentials, request_id=str(uuid4()))
    request["source"] += "\n// " + "x" * (1024 * 1024)
    request["source_sha256"] = hashlib.sha256(request["source"].encode()).hexdigest()
    raw = wire(request)
    assert len(raw) > 1024 * 1024
    pid_path = tmp_path / "blocked.pid"
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", "hang")
    monkeypatch.setenv("KIR_PIPE_TEST_PID_FILE", str(pid_path))
    with pytest.raises(ConnectorTransportError, match="helper_timeout") as caught:
        exchange(record, raw, client_path=helper, timeout_ms=1000)
    assert caught.value.delivery == "unknown" and not caught.value.may_retry
    assert not Path(f"/proc/{int(pid_path.read_text())}").exists()


def diagnostic(code="server_pid_mismatch", phase="server_identity", **changes):
    return {"schema": "kir-pipe-client-diagnostic/1", "code": code, "phase": phase,
            "request_may_have_been_sent": False, "retry_permitted": False, **changes}


@pytest.mark.parametrize("code,phase", [("unsupported_platform", "arguments"),
    ("server_pid_mismatch", "server_identity"), ("server_identity_unavailable", "server_identity"),
    ("deadline_exceeded", "response_read"), ("exchange_failed", "connect"),
    ("invalid_arguments", "arguments"), ("invalid_request", "stdin"), ("request_budget_exceeded", "stdin")])
@pytest.mark.parametrize("sent_claim", [False, True])
def test_known_helper_diagnostic_is_namespaced_without_trusting_delivery(helper, monkeypatch, code, phase, sent_claim):
    record = advertisement()
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", "diagnostic")
    monkeypatch.setenv("KIR_PIPE_TEST_DIAGNOSTIC", json.dumps(diagnostic(code, phase, request_may_have_been_sent=sent_claim)))
    with pytest.raises(ConnectorTransportError) as caught:
        exchange(record, wire(record.credentials.context_request(request_id=str(uuid4()))), client_path=helper, timeout_ms=3000)
    assert caught.value.code == "pipe_client_" + code and caught.value.phase == phase
    assert caught.value.delivery == "unknown" and caught.value.may_retry is False


@pytest.mark.parametrize("case", ["code_secret", "phase_secret", "unknown_field", "duplicate", "retry_true",
    "retry_integer", "sent_integer", "unknown_schema", "wrong_code_phase", "double_json", "malformed", "missing_field"])
def test_untrusted_diagnostics_cannot_echo_data_or_grant_retry(helper, monkeypatch, case):
    record = advertisement()
    sentinel = "PRIVATE-SOURCE-TOKEN-PATH-SENTINEL"
    value = diagnostic()
    if case == "code_secret": value["code"] = sentinel
    if case == "phase_secret": value["phase"] = sentinel
    if case == "unknown_field": value["message"] = sentinel
    if case == "retry_true": value["retry_permitted"] = True
    if case == "retry_integer": value["retry_permitted"] = 0
    if case == "sent_integer": value["request_may_have_been_sent"] = 0
    if case == "unknown_schema": value["schema"] = sentinel
    if case == "wrong_code_phase": value["phase"] = "connect"
    if case == "missing_field": value.pop("retry_permitted")
    raw = json.dumps(value)
    if case == "duplicate": raw = raw.replace('"code": "server_pid_mismatch"', '"code": "server_pid_mismatch", "code": "' + sentinel + '"')
    if case == "double_json": raw += "{}"
    if case == "malformed": raw = sentinel
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", "diagnostic")
    monkeypatch.setenv("KIR_PIPE_TEST_DIAGNOSTIC", raw)
    with pytest.raises(ConnectorTransportError) as caught:
        exchange(record, wire(record.credentials.context_request(request_id=str(uuid4()))), client_path=helper, timeout_ms=3000)
    assert caught.value.code == "helper_failed"
    assert caught.value.delivery == "unknown" and caught.value.may_retry is False
    assert sentinel not in str(caught.value)


@pytest.mark.parametrize("mode", ["diagnostic_exit0", "diagnostic_exit7"])
def test_diagnostic_cannot_make_an_inconsistent_helper_exit_successful(helper, monkeypatch, mode):
    record = advertisement()
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", mode)
    monkeypatch.setenv("KIR_PIPE_TEST_DIAGNOSTIC", json.dumps(diagnostic()))
    with pytest.raises(ConnectorTransportError) as caught:
        exchange(record, wire(record.credentials.context_request(request_id=str(uuid4()))), client_path=helper, timeout_ms=3000)
    assert not caught.value.code.startswith("pipe_client_") and caught.value.may_retry is False


@pytest.mark.skipif(sys.platform == "win32", reason="this control invokes the actual unsupported-platform branch on non-Windows")
def test_actual_production_cli_diagnostic_survives_python_without_becoming_retry_permission(helper, monkeypatch):
    record = advertisement()
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", "production_cli")
    with pytest.raises(ConnectorTransportError) as caught:
        exchange(record, wire(record.credentials.context_request(request_id=str(uuid4()))), client_path=helper, timeout_ms=3000)
    assert caught.value.code == "pipe_client_unsupported_platform" and caught.value.phase == "arguments"
    assert caught.value.delivery == "unknown" and caught.value.may_retry is False
