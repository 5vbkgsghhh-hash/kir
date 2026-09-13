"""Saved archive -> real portable receipt lookup; native outcome explicitly seeded."""
import json
from uuid import uuid4

import pytest

from kir import revit_connector as native
from kir.connector_result import assess_connector_saved_write_response
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision
from kir.revit_transport import exchange
from kir.saved_execution import SavedExecutionRecord
from kir.standalone_publish import publish_materialized_project, publish_program
from kir.tests.test_revit_transport import helper, native_server, wire
from kir.tests.test_standalone_publish import probe, sent


@pytest.mark.parametrize("year", ["2023", "2026"])
@pytest.mark.parametrize("project_archive", [False, True])
def test_lookup_after_archive_reload_does_not_recompile_or_resend(native_server, helper, tmp_path, monkeypatch, year, project_archive):
    advertisement, root = native_server(year)
    precondition = probe(advertisement, helper)
    archive_path = tmp_path / "original.sqlite"
    options = dict(advertisement=advertisement, client_path=helper, archive_path=archive_path,
        expected_document_key=precondition.document_key, operation_id=str(uuid4()),
        bind_view=True, bind_selection=True, timeout_ms=10000)
    if project_archive:
        project = ProjectRevision("lookup-project", [ModuleDefinition("m")], [ModuleInstance("section", "m", [
            NamedOutput("level", {"op": "create_level", "elev_mm": 0})])])
        materialized = materialize_project(project, {})
        oid = materialized.planned.ops[0].op_id
        seeded = {"ok": True, oid: {"id": "700"}}
        (root / "seed-result.json").write_text(json.dumps(seeded), encoding="utf-8")
        attempt = publish_materialized_project(project, materialized, **options)
    else:
        seeded = {"ok": True, "L": {"id": "700"}}
        attempt = publish_program({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]}, **options)
    assert attempt.execution_contract_satisfied  # only the explicit seeded fixture outcome
    before = archive_path.read_bytes()
    loaded = SavedExecutionRecord.load(archive_path)

    def forbidden(*args, **kwargs):
        pytest.fail("receipt recovery must not recompile source")
    monkeypatch.setattr(native, "compile_program", forbidden)
    request = loaded.receipt_request(advertisement.credentials, request_id=str(uuid4()))
    response = exchange(advertisement, wire(request), client_path=helper, timeout_ms=10000)
    checked = assess_connector_saved_write_response(loaded, response,
        credentials=advertisement.credentials, request_id=request["request_id"])
    assert checked.result_available and checked.result == seeded
    assert checked.archive_digest == attempt.record.digest
    assert checked.receipt["source_sha256"] == loaded.binding_dict()["source_sha256"]
    assert checked.receipt["precondition"] == loaded.binding_dict()["precondition"]
    assert archive_path.read_bytes() == before
    assert sent(root) == ["context", "context", "ping", "execute", "receipt"]
