"""Saved project -> materialized plan -> archived association -> one local delivery.

Native API objects are stubbed and result identities explicitly seeded. These
tests prove integration/association, not actual Revit creation or update.
"""
from dataclasses import replace
import json
from uuid import uuid4

import pytest

from kir import standalone_publish as publishing
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision
from kir.project_store import ProjectStore
from kir.project_submission import ProjectSubmissionError, bind_project_submission
from kir.saved_execution import SavedExecutionError, SavedExecutionRecord
from kir.revit_connector import prepare_execution
from kir.revit_transport import ConnectorTransportError
from kir.tests.test_revit_transport import helper, native_server
from kir.tests.test_standalone_publish import probe, kwargs, sent


def initial(macro=False):
    operation = ({"op": "stack", "levels": 2, "floor": [
        {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]} if macro else
        {"op": "create_level", "elev_mm": 0})
    return ProjectRevision("publication-project", [ModuleDefinition("m")],
        [ModuleInstance("section", "m", [NamedOutput("generated", operation)])])


def seed_result(root, materialized):
    # Deliberately artificial result. No parser infers these identities from C#
    # and no fixture claims that the native element actually exists.
    data = {"ok": True, **{op.op_id: {"id": str(700 + index)}
                           for index, op in enumerate(materialized.planned.ops)}}
    (root / "seed-result.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("macro", [False, True])
def test_selected_saved_revision_is_archived_before_its_prepared_bytes_leave(native_server, helper, tmp_path, monkeypatch, macro):
    store = ProjectStore.create(tmp_path / "project.sqlite", initial(macro))
    project = store.head()
    materialized = materialize_project(project, {})
    advertisement, root = native_server()
    context = probe(advertisement, helper)
    seed_result(root, materialized)
    options = kwargs(advertisement, helper, tmp_path / "execution.sqlite", context)
    actual = publishing.exchange
    def inspect_archive(advertisement, raw, **parameters):
        if json.loads(raw)["kind"] == "execute":
            record = SavedExecutionRecord.load(options["archive_path"])
            submission = record.project_submission
            assert submission["project"]["revision_id"] == project.revision_id
            assert submission["execution"]["operation_id"] == options["operation_id"]
            assert {row["op_id"] for output in submission["outputs"] for row in output["compiled_ops"]} == {
                op.op_id for op in materialized.planned.ops}
        return actual(advertisement, raw, **parameters)
    monkeypatch.setattr(publishing, "exchange", inspect_archive)
    result = publishing.publish_materialized_project(project, materialized, **options)
    assert result.execution_contract_satisfied and result.intent_verified is False
    assert result.record.project_submission["project"]["revision_id"] == store.head().revision_id
    assert sent(root).count("execute") == 1
    assert len(result.record.project_submission["outputs"][0]["compiled_ops"]) == (4 if macro else 1)
    assert result.record.project_submission["claims"]["native_element_mapping"] == "not_created"


def test_wrong_materialization_or_wrong_input_type_refuses_before_any_transport(tmp_path, monkeypatch):
    project = initial()
    materialized = materialize_project(project, {})
    different = project.revise(expected_revision=project.revision_id, metadata={"chosen": "different revision"})
    from kir.tests.test_revit_transport import advertisement
    from kir.revit_connector import ContextPrecondition
    options = kwargs(advertisement(), tmp_path / "unused", tmp_path / "never.sqlite", ContextPrecondition("unused", 0))
    def forbidden(*args, **kwargs):
        raise AssertionError("wrong project reached transport")
    monkeypatch.setattr(publishing, "exchange", forbidden)
    for value, projection in ((different, materialized), (project.to_dict(), materialized), (project, materialized.to_dict())):
        with pytest.raises(publishing.PublicationRefusal):
            publishing.publish_materialized_project(value, projection, **options)
    assert not options["archive_path"].exists()


def test_project_binding_failure_does_not_create_archive_or_send_execute(native_server, helper, tmp_path, monkeypatch):
    import kir.project_submission as associations
    project = initial()
    materialized = materialize_project(project, {})
    advertisement, root = native_server()
    options = kwargs(advertisement, helper, tmp_path / "never.sqlite", probe(advertisement, helper))
    def fail(*args, **kwargs):
        raise ProjectSubmissionError("injected_binding_failure", "controlled refusal")
    monkeypatch.setattr(associations, "bind_project_submission", fail)
    with pytest.raises(ProjectSubmissionError, match="injected_binding_failure"):
        publishing.publish_materialized_project(project, materialized, **options)
    assert not options["archive_path"].exists() and "execute" not in sent(root)


def test_archive2_flush_uncertainty_cannot_send_execute(native_server, helper, tmp_path, monkeypatch):
    import kir.saved_execution as archive
    project = initial()
    materialized = materialize_project(project, {})
    advertisement, root = native_server()
    options = kwargs(advertisement, helper, tmp_path / "uncertain.sqlite", probe(advertisement, helper))
    def fail(path):
        raise OSError("injected flush failure")
    monkeypatch.setattr(archive, "_flush_created", fail)
    with pytest.raises(SavedExecutionError, match="archive_durability_unconfirmed"):
        publishing.publish_materialized_project(project, materialized, **options)
    assert SavedExecutionRecord.load(options["archive_path"]).project_submission["project"]["revision_id"] == project.revision_id
    assert "execute" not in sent(root)


def test_metadata_only_wrong_returned_archive_is_detected_despite_equal_native_input(native_server, helper, tmp_path, monkeypatch):
    project = initial()
    materialized = materialize_project(project, {})
    different = project.revise(expected_revision=project.revision_id, metadata={"chosen": "another revision"})
    other_materialized = materialize_project(different, {})
    advertisement, root = native_server()
    options = kwargs(advertisement, helper, tmp_path / "wrong-association.sqlite", probe(advertisement, helper))
    actual = SavedExecutionRecord.create_project_new
    def wrong(cls, path, prepared, submission):
        other = prepare_execution(other_materialized.planned, target=prepared.target,
            precondition=prepared.precondition, operation_id=prepared.operation_id, bulk=other_materialized.planned.bulk)
        assert other.source == prepared.source and other.binding_dict() == prepared.binding_dict()
        wrong_submission = bind_project_submission(different, other_materialized, other)
        return actual(path, other, wrong_submission)
    monkeypatch.setattr(SavedExecutionRecord, "create_project_new", classmethod(wrong))
    with pytest.raises(SavedExecutionError, match="saved_execution_mismatch"):
        publishing.publish_materialized_project(project, materialized, **options)
    assert "execute" not in sent(root)


def test_response_loss_preserves_original_project_association_after_head_changes(native_server, helper, tmp_path, monkeypatch):
    store = ProjectStore.create(tmp_path / "project.sqlite", initial())
    project = store.head()
    materialized = materialize_project(project, {})
    advertisement, root = native_server()
    seed_result(root, materialized)
    options = kwargs(advertisement, helper, tmp_path / "lost.sqlite", probe(advertisement, helper))
    actual = publishing.exchange
    def lose(advertisement, raw, **parameters):
        response = actual(advertisement, raw, **parameters)
        if json.loads(raw)["kind"] == "execute":
            raise ConnectorTransportError("response_lost", "response", delivery="unknown")
        return response
    monkeypatch.setattr(publishing, "exchange", lose)
    with pytest.raises(ConnectorTransportError):
        publishing.publish_materialized_project(project, materialized, **options)
    changed = project.revise(expected_revision=project.revision_id, metadata={"current": "later"})
    store.commit(changed, expected_revision=project.revision_id)
    original = SavedExecutionRecord.load(options["archive_path"])
    assert original.project_submission["project"]["revision_id"] == project.revision_id != store.head().revision_id
    request = original.receipt_request(advertisement.credentials, request_id=str(uuid4()))
    response = actual(advertisement, json.dumps(request, ensure_ascii=False).encode(), client_path=helper, timeout_ms=10000)
    assert json.loads(response)["receipt"]["operation_id"] == options["operation_id"]
    assert sent(root).count("execute") == 1 and sent(root)[-1] == "receipt"
    assert not hasattr(original, "execute_request")


def test_project_publisher_retains_materialized_bulk_policy(native_server, helper, tmp_path):
    project = initial()
    materialized = materialize_project(project, {}, bulk=True)
    advertisement, root = native_server()
    seed_result(root, materialized)
    options = kwargs(advertisement, helper, tmp_path / "bulk.sqlite", probe(advertisement, helper))
    result = publishing.publish_materialized_project(project, materialized, **options)
    assert result.record.to_dict()["plan_evidence"]["bulk"] is True
    assert result.execution_contract_satisfied and sent(root).count("execute") == 1
