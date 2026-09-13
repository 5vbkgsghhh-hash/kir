"""Actual linked native failure/cancellation -> real SQLite CREATE ledger.

No Revit assemblies are loaded. Context API wrappers are controlled stubs; the
one-byte assembly sentinel is never invoked in the pre-start-failure branch.
The healthy-context control deliberately fails assembly loading AFTER durable
start. Initial transport envelope is synthetic, cancellation uses actual Service.
"""
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

from kir.create_publication import bind_create_receipt
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision
from kir.project_store import CREATE_STORE_SCHEMA, ProjectStore, StoreConflict
from kir.project_submission import bind_project_submission
from kir.revit_connector import RuntimeTarget, ContextPrecondition, SessionCredentials, prepare_execution
from kir.saved_execution import SavedExecutionRecord, _capture

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "connector/revit/tests/NoStartFailure.Tests/NoStartFailure.Tests.csproj"


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK absent; linked native failure path not executed")
    root = tmp_path_factory.mktemp("native-no-start")
    for name in ("empty.props", "empty.targets"):
        (root / name).write_text("<Project/>", encoding="utf-8")
    (root / "NuGet.Config").write_text(
        '<configuration><packageSources><clear /></packageSources></configuration>', encoding="utf-8")
    env = {**os.environ, "DOTNET_CLI_HOME": str(root / "cli"), "NUGET_PACKAGES": str(root / "packages"),
           "TMPDIR": str(root), "TMP": str(root), "TEMP": str(root), "DOTNET_NOLOGO": "1",
           "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
           "DOTNET_CLI_USE_MSBUILD_SERVER": "0"}
    build = subprocess.run([dotnet, "build", str(PROJECT), "-c", "Release", "--nologo",
        "--artifacts-path", str(root / "artifacts"), "--configfile", str(root / "NuGet.Config"),
        "-p:NuGetAudit=false", f"-p:DirectoryBuildPropsPath={root / 'empty.props'}",
        f"-p:DirectoryBuildTargetsPath={root / 'empty.targets'}"], cwd=ROOT, env=env,
        text=True, capture_output=True, timeout=120)
    assert build.returncode == 0, build.stdout + build.stderr
    binary = root / "artifacts/bin/NoStartFailure.Tests/release/NoStartFailure.Tests.dll"
    assert binary.is_file()
    return dotnet, binary, env


def test_unpersisted_failure_cannot_block_later_durable_no_start(runner, tmp_path):
    dotnet, binary, env = runner
    process = subprocess.Popen([dotnet, str(binary), str(tmp_path)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        ready_line = lines.get(timeout=15)
        assert ready_line, "native fixture exited before context handshake"
        ready = json.loads(ready_line)
        target = RuntimeTarget(**ready["target"])
        condition = ContextPrecondition(**ready["precondition"])
        credentials = SessionCredentials(target, ready["session_id"], "fixture-token")
        source = ProjectRevision("native-no-start-repro", [ModuleDefinition("m")],
            [ModuleInstance("i", "m", {"level": {"op": "create_level", "elev_mm": 0}})])
        materialized = materialize_project(source, {})
        prepared = prepare_execution(materialized.planned, target=target, precondition=condition,
                                     operation_id=str(uuid4()))
        record = SavedExecutionRecord._from_bytes(_capture(prepared,
            submission=bind_project_submission(source, materialized, prepared)))
        store = ProjectStore.create(tmp_path / "project.sqlite", source, schema=CREATE_STORE_SCHEMA)
        store.reserve_create_publication(record, expected_revision=source.revision_id)
        output, error = process.communicate(json.dumps({"operation_id": prepared.operation_id,
            "source_sha256": prepared.source_sha256}) + "\n", timeout=30)
        assert not error, error
        native = json.loads(output)
        assert native["empty_before_cancel"] and native["journal_healthy"]
        assert native["mutation_count"] == 0 and native["stored_phase"] == "terminal"
        assert native["original_source_sha256"] == prepared.source_sha256
        assert native["durable_failure_state"] == "failed_after_start_unknown" and native["durable_failure_has_record"]
        response = {"protocol": "kir-revit-connector/4", "target": target.to_dict(),
            "session_id": credentials.session_id, "request_id": str(uuid4()), "ok": True,
            "status": "receipt", "context": None, "error": None, "receipt": native["first_receipt"]}
        prior = bind_create_receipt(record, json.dumps(response), credentials=credentials,
                                    request_id=response["request_id"])
        first = store.record_create_receipt(prior)
        cancellation = native["cancellation"]
        cancelled = bind_create_receipt(record, json.dumps(cancellation), credentials=credentials,
                                        request_id=cancellation["request_id"])
        assert cancelled.not_started
        conflict = None
        try:
            second = store.record_create_receipt(cancelled)
        except StoreConflict as caught:
            conflict = str(caught)
        # Before the fix: actual native journal was empty/healthy, but the first
        # response looked terminal and blocked the valid cancellation in SQLite.
        assert conflict is None, {"native": native, "storage_conflict": conflict}
        assert process.returncode == 0 and native["first_receipt"]["state"] == "running_unknown", native
        assert prior.terminal_state is None and first.terminal_receipt_digest is None
        assert second.terminal_receipt_digest == cancelled.receipt_digest
        stored = store.get_create_receipts(record.digest)
        assert len(stored.to_dict()["receipts"]) == 2
        assert stored.terminal_receipt_digest == cancelled.receipt_digest
        # This wave stores evidence only. No-start release is a separate API.
        assert store.get_create_publication(record.digest).output_ids == tuple(
            item["output_id"] for item in record.project_submission["outputs"])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
