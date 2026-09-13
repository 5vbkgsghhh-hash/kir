"""Stored CREATE CLI: real SQLite and portable IPC, not live Revit execution."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from kir import __main__ as cli, standalone_publish as publishing
from kir.project_store import ProjectStore, STORE_SCHEMA, CREATE_STORE_SCHEMA
from kir.revit_transport import ConnectorTransportError
from kir.tests.test_revit_transport import native_server, helper
from kir.tests.test_stored_project_publication import setup, sent
from kir.tests.test_connector_cli import write_advertisement
from kir.tests.test_project_create_store import case


def call(args):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli.main(args)
    raw = stdout.getvalue()
    value = json.loads(raw)
    assert stderr.getvalue() == ""
    assert value["schema"] == "kir-project-publication-cli/1"
    assert value["may_retry"] is False and value["intent_verified"] is False
    assert value["dispatch_permission"] == "none"
    assert all(key not in raw for key in ('"token"', '"source"', '"raw_response"'))
    return code, value, raw


def arguments(action, store, advertisement, helper, directory):
    target = advertisement.credentials.target
    return ["project", action, str(store.path), "--directory", str(directory),
        "--journal-id", target.journal_id, "--instance-id", target.instance_id,
        "--revit-version", target.revit_version, "--session-id", advertisement.credentials.session_id,
        "--client", str(helper), "--timeout-ms", "10000"]


def publish_args(store, materialized, advertisement, helper, directory, options):
    return arguments("create-publish", store, advertisement, helper, directory) + [
        "--expected", materialized.project.revision_id, "--operation-id", options["operation_id"],
        "--document-key", options["expected_document_key"], "--instance", "section",
        "--bind-view", "yes", "--bind-selection", "yes", "--confirm-create"]


def status_args(store, advertisement, operation):
    return ["project", "create-status", str(store.path), "--journal-id",
            advertisement.credentials.target.journal_id, "--operation-id", operation]


@pytest.mark.parametrize("args", [
    ["project", "create-publish", "private-sentinel"],
    ["project", "create-status", "private-sentinel", "--token", "private-sentinel"],
    ["project", "create-invalid", "private-sentinel"],
    ["project", "create-receipt", "db", "--timeout-ms", "private-sentinel"],
])
def test_bad_arguments_are_not_echoed(args):
    code, value, raw = call(args)
    assert code == cli.NOT_DONE and value["diagnostic_code"] == "invalid_publication_arguments"
    assert "private-sentinel" not in raw


def test_schema_upgrade_is_explicit_and_preserves_authored_head(tmp_path):
    store, source, _ = case(tmp_path, schema=STORE_SCHEMA)
    args = ["project", "create-upgrade", str(store.path), "--expected", source.revision_id]
    code, value, _ = call(args)
    assert code == cli.ANSWERED and value["changed"] and value["store_schema"] == CREATE_STORE_SCHEMA
    assert value["native_request"] == "none" and not value["author_head_changed"]
    assert call(args)[1]["changed"] is False
    assert ProjectStore.open(store.path).head().dumps() == source.dumps()


def test_status_reads_retained_input_without_transport_or_compiler(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    import kir.compiler, kir.revit_transport
    def forbidden(*_a, **_kw):
        pytest.fail("local status attempted execution")
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    monkeypatch.setattr(kir.revit_transport, "exchange", forbidden)
    binding = record.binding_dict()
    before = store.path.read_bytes()
    code, value, _ = call(["project", "create-status", str(store.path),
        "--journal-id", binding["target"]["journal_id"], "--operation-id", binding["operation_id"]])
    assert code == cli.ANSWERED and value["archive_digest"] == record.digest
    assert value["receipt_count"] == 0 and value["terminal_receipt_digest"] is None
    assert value["native_request"] == "none" and value["observation"] == "retained_not_fresh"
    assert store.path.read_bytes() == before


def test_cli_publishes_selected_dependency_closure_then_reads_receipt(native_server, helper, tmp_path):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    directory = tmp_path / "discovery"
    write_advertisement(directory, advertisement)
    args = publish_args(store, materialized, advertisement, helper, directory, options)
    code, value, raw = call(args)
    assert code == cli.ANSWERED and value["execution_contract_satisfied"]
    assert value["native_request"] == "execute_once" and value["retained_receipt_digest"]
    assert advertisement.credentials.token not in raw
    status = call(status_args(store, advertisement, options["operation_id"]))[1]
    assert status["archive_digest"] == value["archive_digest"] and len(status["output_ids"]) == 2
    assert status["receipt_count"] == 1 and status["scope_ownership"] == "retained"
    receipt_args = arguments("create-receipt", store, advertisement, helper, directory) + ["--archive", value["archive_digest"]]
    receipt = call(receipt_args)[1]
    assert receipt["native_request"] == "lookup_only" and receipt["execution_contract_satisfied"]
    assert receipt["retained_receipt_digest"] == value["retained_receipt_digest"]
    assert sent(root).count("execute") == 1


def test_cli_lost_response_can_find_archive_and_recover_without_recompile(native_server, helper, tmp_path, monkeypatch):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    directory = tmp_path / "discovery"
    write_advertisement(directory, advertisement)
    actual = publishing.exchange
    def lose_response(advertisement, request, **kwargs):
        response = actual(advertisement, request, **kwargs)
        if json.loads(request)["kind"] == "execute":
            raise ConnectorTransportError("controlled_lost_response", "response", delivery="unknown")
        return response
    monkeypatch.setattr(publishing, "exchange", lose_response)
    code, result, _ = call(publish_args(store, materialized, advertisement, helper, directory, options))
    assert code == cli.NOT_DONE and result["delivery"] == "unknown"
    status = call(status_args(store, advertisement, options["operation_id"]))[1]
    assert status["receipt_count"] == 0
    monkeypatch.setattr(publishing, "exchange", actual)
    monkeypatch.setattr(publishing, "prepare_execution", lambda *_a, **_kw: pytest.fail("recovery compiled"))
    args = arguments("create-receipt", store, advertisement, helper, directory) + ["--archive", status["archive_digest"]]
    code, result, _ = call(args)
    assert code == cli.ANSWERED and result["retained_receipt_digest"]
    assert sent(root).count("execute") == 1 and sent(root)[-1] == "receipt"


def test_cli_publication_status_and_receipt_survive_fresh_python_processes(native_server, helper, tmp_path):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    directory = tmp_path / "discovery"
    write_advertisement(directory, advertisement)
    repository = Path(__file__).resolve().parents[2]

    def fresh(args):
        completed = subprocess.run([sys.executable, "-m", "kir", *args], cwd=repository,
            env=dict(os.environ, PYTHONPATH=str(repository), PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True, text=True, timeout=30)
        assert completed.returncode == cli.ANSWERED, completed.stdout + completed.stderr
        assert completed.stderr == "" and advertisement.credentials.token not in completed.stdout
        value = json.loads(completed.stdout)
        assert value["may_retry"] is False and value["intent_verified"] is False
        return value

    publication = fresh(publish_args(store, materialized, advertisement, helper, directory, options))
    status = fresh(status_args(store, advertisement, options["operation_id"]))
    assert status["archive_digest"] == publication["archive_digest"]
    receipt = fresh(arguments("create-receipt", store, advertisement, helper, directory)
                    + ["--archive", status["archive_digest"]])
    assert receipt["retained_receipt_digest"] == publication["retained_receipt_digest"]
    assert receipt["execution_contract_satisfied"]
    assert sent(root).count("execute") == 1 and sent(root)[-1] == "receipt"


@pytest.mark.parametrize("failure", ["confirmation", "stale", "wrong_document", "scope"])
def test_missing_or_wrong_publication_choices_never_execute(native_server, helper, tmp_path, failure):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    directory = tmp_path / "discovery"
    write_advertisement(directory, advertisement)
    args = publish_args(store, materialized, advertisement, helper, directory, options)
    if failure == "confirmation": args.remove("--confirm-create")
    elif failure == "stale": args[args.index("--expected") + 1] = "f" * 64
    elif failure == "wrong_document": args[args.index("--document-key") + 1] = "other-document"
    else: args[args.index("--instance") + 1] = "unknown-instance"
    code, result, _ = call(args)
    assert code != cli.ANSWERED and result["status"] in {"refused", "not_done"}
    assert sent(root).count("execute") == 0
