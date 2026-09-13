"""Actual pre-/5 compiler fixtures remain inert, byte-identical archives.

The compressed fixture bytes were emitted by a frozen 0.8.1 source tree using
its own compiler/materialization/submission/archive factories. They were NOT
produced by deleting lineage from current evidence. Producer wheel, sdist and
source-manifest hashes travel with the fixtures; machine-local generation notes
are deliberately not needed by this test or shipped as product documentation.
"""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zlib

import pytest

from kir import compiler, revit_connector
from kir.geometry_materialization import materialize_project, materialize_selection
from kir.midend import PLAN_SCHEMA, LINEAGED_PLAN_SCHEMA
from kir.project import ProjectRevision
from kir.project_selection import select_project_instances
from kir.project_submission import (bind_project_submission, bind_selected_project_submission,
                                    validate_submission_source)
from kir.revit_connector import RuntimeTarget, ContextPrecondition, SessionCredentials, prepare_execution
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError, _canonical, _hash, _capture


FIXTURE = Path(__file__).with_name("lineage_archive_compatibility_v4.json")
NAMES = ("plain", "full_project", "selected_project")


def _fixtures():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _bytes(packed):
    assert packed["encoding"] == "zlib+base64"
    raw = zlib.decompress(base64.b64decode(packed["data"], validate=True))
    assert len(raw) == packed["raw_size"]
    assert hashlib.sha256(raw).hexdigest() == packed["sha256"]
    return raw


def _project():
    return ProjectRevision.loads(_bytes(_fixtures()["project_source"]).decode("utf-8"))


def _rehash_record(data):
    data["record_digest"] = _hash({key: value for key, value in data.items() if key != "record_digest"})
    return _canonical(data).encode("utf-8")


def _new_record(name):
    target = RuntimeTarget("11111111-1111-4111-8111-111111111111",
                           "22222222-2222-4222-8222-222222222222", "2023")
    args = dict(target=target, precondition=ContextPrecondition("synthetic-archive-document", 8),
                operation_id="33333333-3333-4333-8333-333333333333")
    if name == "plain":
        prepared = prepare_execution({"lineage": "current-explicit-owner", "ops": [
            {"op": "create_level", "id": "base", "elev_mm": 0.0, "name": "Base"}]}, **args)
        raw = _capture(prepared)
    else:
        project = _project()
        selected = name == "selected_project"
        materialized = (materialize_selection(project,
            select_project_instances(project, instance_keys=("selected",)), {})
            if selected else materialize_project(project, {}))
        prepared = prepare_execution(materialized.planned, **args)
        binder = bind_selected_project_submission if selected else bind_project_submission
        raw = _capture(prepared, submission=binder(project, materialized, prepared))
    return SavedExecutionRecord._from_bytes(raw)


def test_historical_fixture_producer_is_pinned_not_a_current_field_deletion():
    fixtures = _fixtures()
    assert fixtures["format"] == "kir-historical-lineage-test-fixtures/1"
    assert fixtures["producer"] == {
        "version": "0.8.1", "plan_schema": "kir-planned-program/4",
        "wheel_sha256": "d6d688c63437e4e42659c87a3f7a46cea39413ead11815f255ee1074197c2484",
        "sdist_sha256": "6fff8b0f9754fdb060829295cddd84cfa3033568970e3ef1a328c9e975fa4029",
        "source_manifest_sha256": "18a75ed6824ef2aefd15cd6db6426e6a1e61763dd904bfcb8a8316db1ac3dd58"}
    assert tuple(fixtures["archives"]) == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_actual_historical_v4_round_trips_sqlite_without_replanning_or_inferred_lineage(name, tmp_path, monkeypatch):
    packed = _fixtures()["archives"][name]
    raw = _bytes(packed)
    historical = json.loads(raw)
    assert historical["plan_evidence"]["schema"] == "kir-planned-program/4"
    assert "lineage" not in historical["plan_evidence"]
    def forbidden(*_args, **_kwargs):
        raise AssertionError("reading historical evidence must not invoke a compiler or fresh preparation")
    monkeypatch.setattr(compiler, "compile_program", forbidden)
    monkeypatch.setattr(compiler, "plan_program", forbidden)
    monkeypatch.setattr(revit_connector, "prepare_execution", forbidden)
    memory = SavedExecutionRecord._from_bytes(raw)
    # Use the real immutable SQLite container, not a mock load function.
    created = SavedExecutionRecord._create_record(tmp_path / "historical.sqlite", raw)
    loaded = SavedExecutionRecord.load(tmp_path / "historical.sqlite")
    for record in (memory, created, loaded):
        assert record._raw == raw and record.digest == packed["record_digest"]
        assert record.to_dict() == historical
        assert _canonical(record.to_dict()).encode("utf-8") == raw
        assert record.to_dict()["schema"] == packed["archive_schema"]
        assert "lineage" not in record.to_dict()["plan_evidence"]
        assert not any(hasattr(record, attribute) for attribute in ("planned", "execute", "execute_request"))
        binding = record.binding_dict()
        credentials = SessionCredentials(RuntimeTarget(**binding["target"]),
            "66666666-6666-4666-8666-666666666666", "synthetic-not-sent")
        request = record.receipt_request(credentials, request_id="77777777-7777-4777-8777-777777777777")
        assert request["kind"] == "receipt"
        assert request["operation_id"] == binding["operation_id"]
        assert set(request).isdisjoint({"source", "source_sha256", "planned", "plan_evidence"})
        if name != "plain":
            validate_submission_source(_project(), record.project_submission, selection_policy="retained")
            # Project identity already exists in these old records. It is NOT
            # permission to insert a missing signed native lineage retroactively.
            assert record.project_submission["project"]["project_id"] == "archive-compatibility"
            assert len(record.project_submission["outputs"]) == (1 if name == "selected_project" else 2)


@pytest.mark.parametrize("name", NAMES)
def test_current_explicit_lineage_records_use_v5_without_rewriting_v4(name):
    current = _new_record(name)
    data = current.to_dict()
    assert data["plan_evidence"]["schema"] == LINEAGED_PLAN_SCHEMA == "kir-planned-program/5"
    assert data["plan_evidence"]["lineage"] == ("current-explicit-owner" if name == "plain" else "archive-compatibility")
    assert SavedExecutionRecord._from_bytes(current._raw)._raw == current._raw
    old = _bytes(_fixtures()["archives"][name])
    assert SavedExecutionRecord._from_bytes(old).to_dict()["plan_evidence"]["schema"] == PLAN_SCHEMA == "kir-planned-program/4"


@pytest.mark.parametrize("value", [None, "", "not an owner", "x" * 65, "\u0432\u043b\u0430\u0434\u0435\u043b\u0435\u0446", True, 1, {}, []])
def test_rehashed_v5_malformed_lineage_is_not_accepted_as_a_retained_claim(value):
    data = _new_record("plain").to_dict()
    data["plan_evidence"]["lineage"] = value
    data["plan_evidence"]["plan_digest"] = _hash({k: v for k, v in data["plan_evidence"].items() if k != "plan_digest"})
    with pytest.raises(SavedExecutionError) as refused:
        SavedExecutionRecord._from_bytes(_rehash_record(data))
    assert refused.value.code == "invalid_saved_execution"


@pytest.mark.parametrize("fault", ["missing", "unknown_plan_field", "unknown_archive_field", "downgraded", "future"])
def test_v5_missing_unknown_and_wrong_schema_fields_refuse_even_with_rehashed_envelopes(fault):
    data = _new_record("plain").to_dict()
    plan = data["plan_evidence"]
    if fault == "missing": plan.pop("lineage")
    elif fault == "unknown_plan_field": plan["invented_authority"] = True
    elif fault == "unknown_archive_field": data["invented_authority"] = True
    elif fault == "downgraded": plan["schema"] = "kir-planned-program/4"
    else: plan["schema"] = "kir-planned-program/999"
    plan["plan_digest"] = _hash({key: value for key, value in plan.items() if key != "plan_digest"})
    with pytest.raises(SavedExecutionError):
        SavedExecutionRecord._from_bytes(_rehash_record(data))


@pytest.mark.parametrize("fault", ["outer_digest", "inner_digest", "signed_lineage_changed"])
def test_v5_digest_tampering_is_refused(fault):
    current = _new_record("plain")
    data = deepcopy(current.to_dict())
    if fault == "outer_digest":
        data["record_digest"] = "0" * 64
        raw = _canonical(data).encode("utf-8")
    else:
        if fault == "inner_digest": data["plan_evidence"]["plan_digest"] = "0" * 64
        else: data["plan_evidence"]["lineage"] = "another-valid-owner"
        raw = _rehash_record(data)  # outer integrity alone cannot repair the plan.
    with pytest.raises(SavedExecutionError):
        SavedExecutionRecord._from_bytes(raw)


def test_unsupported_plan_v3_is_still_rejected_not_upgraded():
    # This is an adversarial schema mutation, NOT a claimed historical /3 fixture.
    data = json.loads(_bytes(_fixtures()["archives"]["plain"]))
    plan = data["plan_evidence"]
    plan["schema"] = "kir-planned-program/3"
    plan["plan_digest"] = _hash({key: value for key, value in plan.items() if key != "plan_digest"})
    with pytest.raises(SavedExecutionError) as refused:
        SavedExecutionRecord._from_bytes(_rehash_record(data))
    assert refused.value.code == "unsupported_saved_execution"
