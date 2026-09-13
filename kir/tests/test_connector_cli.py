"""Read-only CLI over actual portable pipe/Collector/Service fixtures.

Revit API stubs and an injected PID probe are explicit: these are neither a
Windows authentication check nor native model execution. Negative response
controls mutate actual captured responses, not claims of native corruption.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest

from kir import __main__ as cli
from kir import revit_discovery, revit_transport
from kir.tests.test_revit_transport import advertisement, helper, native_server, wire, diagnostic


def call(args):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        status = cli.main(args)
    raw, errors = stdout.getvalue(), stderr.getvalue()
    result = json.loads(raw)
    assert errors == ""
    assert result["read_only"] is True and result["write_permission"] is False
    assert result["may_retry"] is False
    assert '"token"' not in raw and '"source"' not in raw and '"raw_response"' not in raw
    return status, result, raw


def arguments(record, directory, client):
    target = record.credentials.target
    return ["connector", "context", "--directory", str(directory),
            "--journal-id", target.journal_id, "--instance-id", target.instance_id,
            "--revit-version", target.revit_version, "--session-id", record.credentials.session_id,
            "--client", str(client), "--timeout-ms", "10000"]


@pytest.mark.parametrize("args", [
    ["connector", "context", "--timeout-ms", "PRIVATE-ARG-SENTINEL"],
    ["connector", "context", "--bind-view", "PRIVATE-ARG-SENTINEL"],
    ["connector", "PRIVATE-ARG-SENTINEL"],
    ["connector", "list", "--directory", "/not-read", "--token", "PRIVATE-ARG-SENTINEL"],
    ["connector", "context"],
])
def test_argument_parser_never_echoes_invalid_values_or_credentials(args):
    status, result, raw = call(args)
    assert status == cli.NOT_DONE and result["diagnostic_code"] == "invalid_connector_arguments"
    assert "PRIVATE-ARG-SENTINEL" not in raw


def test_connector_help_remains_available_without_accessing_discovery():
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        assert cli.main(["connector", "context", "--help"]) == cli.ANSWERED
    assert "--journal-id" in stdout.getvalue() and stderr.getvalue() == ""


def write_advertisement(root, record):
    credentials = record.credentials
    path = root / credentials.target.instance_id / (credentials.session_id + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wire({"protocol": "kir-revit-connector/4", "target": credentials.target.to_dict(),
        "session_id": credentials.session_id, "token": credentials.token,
        "pipe_name": record.pipe_name, "process_id": record.process_id, "expires_utc": record.expires_utc}))
    return path


def sent(root):
    path = root / "requests"
    return path.read_text().splitlines() if path.exists() else []


def test_list_is_token_free_read_only_and_expired_is_not_liveness(tmp_path, monkeypatch):
    record = advertisement()
    path = write_advertisement(tmp_path, record)
    value = json.loads(path.read_bytes())
    value["expires_utc"] = "2000-01-01T00:00:00.0000000Z"
    path.write_bytes(wire(value))
    before = path.read_bytes(), path.stat().st_mtime_ns
    def forbidden(*args, **kwargs):
        raise AssertionError("listing must not connect or start a process")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    status, result, raw = call(["connector", "list", "--directory", str(tmp_path)])
    assert status == cli.ANSWERED and result["catalog_complete"] is True
    assert result["liveness"] == "not_probed"
    assert len(result["advertisements"]) == 1
    assert result["advertisements"][0]["advertised_unexpired"] is False
    assert result["advertisements"][0]["authority"] == "unverified_advertisement"
    assert record.credentials.token not in raw
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_list_names_incomplete_catalog_without_echoing_invalid_filename_or_payload(tmp_path):
    record = advertisement()
    write_advertisement(tmp_path, record)
    sentinel = "PRIVATE-CREDENTIAL-SENTINEL"
    invalid = tmp_path / sentinel
    invalid.write_bytes(wire({"token": record.credentials.token, "source": sentinel}))
    before = invalid.read_bytes()
    status, result, raw = call(["connector", "list", "--directory", str(tmp_path)])
    assert status == cli.ANSWERED and result["catalog_complete"] is False
    assert result["issues"] and len(result["advertisements"]) == 1
    assert sentinel not in raw and record.credentials.token not in raw
    assert invalid.read_bytes() == before


@pytest.mark.parametrize("case", ["missing", "file", "symlink", "budget"])
def test_unavailable_listing_never_creates_or_claims_complete(tmp_path, monkeypatch, case):
    root = tmp_path / "chosen"
    if case == "file": root.write_bytes(b"private-source-sentinel")
    if case == "symlink": root.symlink_to(tmp_path, target_is_directory=True)
    if case == "budget":
        root.mkdir()
        (root / "entry").touch()
        monkeypatch.setattr(revit_discovery, "MAX_DISCOVERY_ENTRIES", 0)
    status, result, raw = call(["connector", "list", "--directory", str(root)])
    assert status == cli.NOT_DONE and result["catalog_complete"] is False
    assert "private-source-sentinel" not in raw
    if case == "missing": assert not root.exists()
    if case == "file": assert root.read_bytes() == b"private-source-sentinel"


def test_empty_catalog_is_not_a_claim_about_all_running_processes(tmp_path):
    status, result, _ = call(["connector", "list", "--directory", str(tmp_path)])
    assert status == cli.ANSWERED and result["advertisements"] == []
    assert result["catalog_complete"] is True and result["liveness"] == "not_probed"


@pytest.mark.parametrize("flags", [
    ["--precondition"], ["--precondition", "--bind-view", "yes"],
    ["--precondition", "--bind-selection", "no"], ["--bind-view", "yes"],
    ["--bind-selection", "no"], ["--bind-view", "no", "--bind-selection", "yes"],
])
def test_ui_binding_choices_refuse_before_any_io(tmp_path, monkeypatch, flags):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid binding choices reached filesystem/transport")
    monkeypatch.setattr(revit_discovery, "scan_discovery", forbidden)
    monkeypatch.setattr(revit_transport, "exchange", forbidden)
    status, result, _ = call(arguments(advertisement(), tmp_path / "missing", "/missing") + flags)
    assert status == cli.REFUSED and result["diagnostic_code"] == "explicit_binding_choices_required"


@pytest.mark.parametrize("field", ["--journal-id", "--instance-id", "--session-id", "--revit-version"])
def test_wrong_exact_selection_cannot_fall_back_to_first(tmp_path, monkeypatch, field):
    record = advertisement()
    write_advertisement(tmp_path, record)
    args = arguments(record, tmp_path, "/missing")
    args[args.index(field) + 1] = "2023" if field == "--revit-version" else str(uuid4())
    def forbidden(*args, **kwargs):
        raise AssertionError("wrong explicit target reached transport")
    monkeypatch.setattr(revit_transport, "exchange", forbidden)
    status, result, raw = call(args)
    assert status == cli.REFUSED and result["diagnostic_code"] == "selection_not_unique"
    assert record.credentials.token not in raw


def test_expired_selection_does_not_launch_helper(tmp_path, monkeypatch):
    record = advertisement()
    path = write_advertisement(tmp_path, record)
    value = json.loads(path.read_bytes())
    value["expires_utc"] = "2000-01-01T00:00:00.0000000Z"
    path.write_bytes(wire(value))
    def forbidden(*args, **kwargs):
        raise AssertionError("expired selection reached transport")
    monkeypatch.setattr(revit_transport, "exchange", forbidden)
    status, result, _ = call(arguments(record, tmp_path, "/missing"))
    assert status == cli.REFUSED and result["diagnostic_code"] == "advertisement_expired"


def test_invalid_input_is_named_without_argument_echo(tmp_path):
    args = arguments(advertisement(), tmp_path, "/missing")
    args[args.index("--journal-id") + 1] = "PRIVATE-CREDENTIAL-SENTINEL"
    status, result, raw = call(args)
    assert status == cli.REFUSED and result["diagnostic_code"] == "invalid_input"
    assert "PRIVATE-CREDENTIAL-SENTINEL" not in raw


def test_two_simultaneous_servers_selected_explicitly_from_same_directory(native_server, helper, tmp_path, monkeypatch):
    first, root_a = native_server("2023")
    second, root_b = native_server("2026")
    catalog = tmp_path / "combined"
    for root in (root_a, root_b):
        shutil.copytree(root / "discovery", catalog, dirs_exist_ok=True)
    (catalog / "unrelated-invalid-neighbor").write_bytes(b'{"token":"DO-NOT-PRINT"}')
    from kir import revit_connector
    def forbidden(*args, **kwargs):
        raise AssertionError("context CLI must not compile")
    monkeypatch.setattr(revit_connector, "compile_program", forbidden)
    status, result, raw = call(["connector", "list", "--directory", str(catalog)])
    assert status == cli.ANSWERED and len(result["advertisements"]) == 2
    assert not result["catalog_complete"] and "DO-NOT-PRINT" not in raw
    for record in (second, first):
        status, result, raw = call(arguments(record, catalog, helper))
        assert status == cli.ANSWERED and result["read_complete"] and result["binding_matches"]
        assert result["target"] == record.credentials.target.to_dict()
        assert result["session_id"] == record.credentials.session_id
        assert result["snapshot"]["revit_version"] == record.credentials.target.revit_version
        assert result["snapshot"]["document_key"] != result["snapshot"]["document_title"]
        assert result["precondition"] is None and not result["precondition_requested"]
        assert not result["catalog_complete"] and record.credentials.token not in raw
        assert "fixture-token" not in raw
    assert sent(root_a) == ["context"] and sent(root_b) == ["context"]


@pytest.mark.parametrize("bind_view,bind_selection", [("yes", "yes"), ("no", "yes"), ("yes", "no"), ("no", "no")])
def test_precondition_retains_explicit_null_vs_ui_binding(native_server, helper, bind_view, bind_selection):
    record, root = native_server()
    status, result, _ = call(arguments(record, root / "discovery", helper) + [
        "--precondition", "--bind-view", bind_view, "--bind-selection", bind_selection])
    assert status == cli.ANSWERED
    before, snapshot = result["precondition"], result["snapshot"]
    assert before["document_key"] == snapshot["document_key"]
    assert before["revision"] == snapshot["revision"]
    assert before["active_view_id"] == (snapshot["active_view_id"] if bind_view == "yes" else None)
    assert before["selection_digest"] == (snapshot["selection_digest"] if bind_selection == "yes" else None)
    assert sent(root) == ["context"]


@pytest.mark.parametrize("case,precondition", [
    ("no_document", False), ("no_document", True), ("incomplete", False), ("incomplete", True),
    ("foreign", True), ("malformed", True), ("duplicate", True), ("untrusted_error", False),
])
def test_actual_context_negative_controls_cannot_yield_write_authority(native_server, helper, monkeypatch, case, precondition):
    record, root = native_server()
    actual = revit_transport.exchange
    sentinel = "PRIVATE-CREDENTIAL-SOURCE-SENTINEL"
    def mutate(*args, **kwargs):
        # All variants begin with a real pipe response. The mutations are
        # test-only and do not pretend that native Collector emitted them.
        response = json.loads(actual(*args, **kwargs))
        if case == "no_document":
            response["context"].update(has_document=False, document_key="", document_title="",
                revision=0, active_view_id=0, selection_digest="", selection_count=0,
                is_family_document=False, is_read_only=False, is_modifiable=False)
        if case == "incomplete": response["context"]["complete"] = False
        if case == "foreign": response["target"]["instance_id"] = str(uuid4())
        if case == "malformed": return wire({"token": record.credentials.token, "source": sentinel})
        if case == "duplicate": return wire(response)[:-1] + b',"ok":true}'
        if case == "untrusted_error": response.update(ok=False, status=sentinel, error=record.credentials.token)
        return wire(response)
    monkeypatch.setattr(revit_transport, "exchange", mutate)
    args = arguments(record, root / "discovery", helper)
    if precondition: args += ["--precondition", "--bind-view", "yes", "--bind-selection", "yes"]
    status, result, raw = call(args)
    assert status == (cli.ANSWERED if case == "no_document" and not precondition else cli.REFUSED)
    assert result["precondition"] is None
    assert record.credentials.token not in raw and sentinel not in raw
    assert sent(root) == ["context"]


def test_missing_helper_is_not_attempted_and_never_sent(native_server, tmp_path):
    record, root = native_server()
    status, result, raw = call(arguments(record, root / "discovery", tmp_path / "private-helper-path"))
    assert status == cli.NOT_DONE and result["delivery"] == "not_attempted"
    assert result["diagnostic_code"] == "client_unavailable"
    assert sent(root) == [] and "private-helper-path" not in raw


@pytest.mark.parametrize("mode", ["wrong_pid", "hang", "abnormal"])
def test_real_helper_failure_is_named_once_and_never_retry_permission(native_server, helper, monkeypatch, mode):
    record, root = native_server()
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", mode)
    args = arguments(record, root / "discovery", helper)
    args[-1] = "1000"
    status, result, raw = call(args)
    assert status == cli.NOT_DONE and result["delivery"] == "unknown"
    assert sent(root) == [] and record.credentials.token not in raw
    # PortableHelper's wrong_pid branch deliberately emits only fixture_failure,
    # not the production structured diagnostic. Do not infer a cause from it.
    if mode == "wrong_pid": assert result["diagnostic_code"] == "helper_failed"


def test_cli_retains_a_supported_structured_helper_diagnostic_without_retry(native_server, helper, monkeypatch):
    record, root = native_server()
    monkeypatch.setenv("KIR_PIPE_TEST_HELPER_MODE", "diagnostic")
    monkeypatch.setenv("KIR_PIPE_TEST_DIAGNOSTIC", json.dumps(diagnostic()))
    status, result, raw = call(arguments(record, root / "discovery", helper))
    assert status == cli.NOT_DONE and result["delivery"] == "unknown"
    assert result["diagnostic_code"] == "pipe_client_server_pid_mismatch"
    assert result["may_retry"] is False and sent(root) == []
    assert record.credentials.token not in raw


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_real_python_module_entrypoint_calls_only_context(native_server, helper, year):
    record, root = native_server(year)
    process = subprocess.run([sys.executable, "-m", "kir", *arguments(record, root / "discovery", helper)],
        cwd=Path(__file__).resolve().parents[2], env=os.environ.copy(), capture_output=True, text=True, timeout=30)
    assert process.returncode == cli.ANSWERED, process.stderr
    result = json.loads(process.stdout)
    assert result["read_complete"] and result["snapshot"]["revit_version"] == year
    assert result["write_permission"] is False and result["precondition"] is None
    assert record.credentials.token not in process.stdout + process.stderr
    assert sent(root) == ["context"]


def test_required_selection_and_absence_of_mutating_commands():
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as missing:
        parser.parse_args(["connector", "context", "--directory", "/chosen"])
    assert missing.value.code == cli.NOT_DONE
    for action in ("install", "toggle", "execute", "publish", "cleanup"):
        with pytest.raises(SystemExit) as absent:
            parser.parse_args(["connector", action])
        assert absent.value.code == cli.NOT_DONE
