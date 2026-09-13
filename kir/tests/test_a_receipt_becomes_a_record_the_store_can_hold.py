# -*- coding: utf-8 -*-
"""The loop closes through a REAL store: publication → receipt → план₂ = 0 операций.

Measured live on 13.09.2026: three publications of one program gave walls
4 → 8 → 12, floors 1 → 2 → 3, **+25 instances per repeat**
(`/root/kir-live-20260909/live-20260913-slice-opening-receipt.json`). The cause
was not the emitter — nothing carried the RESULT back, so every republication
started from nothing and planned everything as `create`.

`kir/tests/test_a_republication_receipt_closes_the_loop.py` already pins the
round trip in memory and against a FAKE store. This file is the other half, and
the half that decides whether the loop survives a process boundary: a real
`ProjectStore` on disk, a real reservation, a real bound native receipt, the
handle closed and REOPENED, and only then the second plan. Nothing here is
remembered from the first round in a Python variable.
"""
import json
from uuid import uuid4

import pytest

from kir.create_publication import PROJECT_ARCHIVE_SCHEMA, bind_create_receipt
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.project_republish import RepublishError, plan_republish, previous_from_store
from kir.project_republish_program import republish_program
from kir.project_republish_receipt import import_edges, republish_receipt
from kir.project_store import CREATE_STORE_SCHEMA, ProjectStore
from kir.project_submission import bind_project_submission
from kir.republish_archive import (RepublishArchiveError, check_identities,
                                   previous_from_stored_publication,
                                   program_as_published, saved_record_from_receipt)
from kir.revit_connector import ContextPrecondition, RuntimeTarget, prepare_execution
from kir.saved_execution import SavedExecutionRecord, _capture

DOCUMENT, REVISION = "native-document", 7
GUID = "7ff4b512b2994d75810762effd492f45"


PROJECT_ID = "republish-loop"


def project(height_mm=3000.0):
    """Four walls on one level — the very shape measured live on 13.09.2026."""
    corners = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 6000.0], [0.0, 6000.0]]
    level = output_id(PROJECT_ID, "datums", "level")
    walls = {f"w{index}": {"op": "create_wall", "p0_mm": corners[index],
                           "p1_mm": corners[(index + 1) % 4], "height_mm": height_mm,
                           "level": {"by": "ref", "value": level}}
             for index in range(4)}
    return ProjectRevision(PROJECT_ID, [ModuleDefinition("m")], [
        ModuleInstance("datums", "m", {"level": {"op": "create_level", "elev_mm": 0.0}}),
        ModuleInstance("section", "m", walls)])


def archive(source, *, target, operation_id):
    materialized = materialize_project(source, {})
    prepared = prepare_execution(materialized.planned, target=target,
                                 precondition=ContextPrecondition(DOCUMENT, REVISION),
                                 operation_id=operation_id)
    submission = bind_project_submission(source, materialized, prepared)
    return SavedExecutionRecord._from_bytes(_capture(prepared, submission=submission))


def native_response(record, target, *, captured=True):
    """One committed native receipt, in the shape the connector actually returns."""
    from kir.revit_connector import SessionCredentials

    binding = record.to_dict()["binding"]
    credentials = SessionCredentials(target, str(uuid4()), "private-test-token")
    outputs = record.project_submission["outputs"]
    result = {"ok": True}
    for index, row in enumerate(outputs):
        number = 700 + index
        identity = {"schema_version": "revit-element-identity/1", "element_id": number,
                    "unique_id": f"7ff4b512-b299-4d75-8107-62effd492f45-{number:08x}",
                    "version_guid": GUID}
        result[row["output_id"]] = {
            "id": str(number),
            "element_identity_status": "captured" if captured else "unavailable",
            "element_identity_reason": None if captured else "identity_unreadable",
            "element_identity": identity if captured else None}
    receipt = {**binding, "document_key": binding["precondition"]["document_key"],
               "state": "invocation_completed", "started": True, "may_retry": False,
               "transaction_evidence": "changes_observed", "semantic_evidence": "unverified",
               "result_json": json.dumps(result), "result_truncated": False,
               "result_error": None, "error": None,
               "changes": {"added": [700 + index for index in range(len(outputs))],
                           "modified": [], "deleted": [], "transaction_names": ["KIR"],
                           "truncated": False},
               "timestamp_utc": "2026-09-13T12:00:00Z"}
    response = {"protocol": "kir-revit-connector/4", "request_id": str(uuid4()),
                "target": target.to_dict(), "session_id": credentials.session_id,
                "ok": True, "status": "receipt", "error": None, "context": None,
                "receipt": receipt}
    return credentials, response


def published(tmp_path, source=None, *, captured=True):
    """One FULL publication through the product path, then the handle is dropped."""
    source = source or project()
    target = RuntimeTarget(str(uuid4()), str(uuid4()), "2023")
    store = ProjectStore.create(tmp_path / "project.sqlite", source, schema=CREATE_STORE_SCHEMA)
    record = archive(source, target=target, operation_id=str(uuid4()))
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    credentials, response = native_response(record, target, captured=captured)
    store.record_create_receipt(bind_create_receipt(
        record, json.dumps(response), credentials=credentials,
        request_id=response["request_id"]))
    return record.digest


# ───────────── the gap: what the OTHER reader asks for is never written ─────────────

def test_control_a_real_store_never_holds_the_blob_and_the_reader_stopped_asking(tmp_path):
    """🔴 MEASURED, NOT INFERRED — and then ACTED ON (13.09.2026).

    A stored CREATE receipt's fields are closed to exactly five by
    `create_publication.validate_create_receipt_claims`, and no product writer
    ever puts an `identity_assessment` blob among them. That fact is unchanged
    and is still asserted below: it is the reason this module exists.

    What changed is the consequence. `project_republish.previous_from_store`
    used to REFUSE on a real store and was green only against a fake one; it now
    falls through to `previous_from_stored_publication` — the deriver in this
    module — so both entry points answer from the SAME derivation and a caller
    cannot land on the dead one. The control therefore checks two things: the
    store still holds no blob, and the reader no longer needs it.
    """
    digest = published(tmp_path)
    store = ProjectStore.open(tmp_path / "project.sqlite")
    row, = store.get_create_receipts(digest).to_dict()["receipts"]
    assert set(row) == {"schema", "archive_digest", "native_receipt", "claims", "receipt_digest"}
    assert "identity_assessment" not in row, "продуктовый писатель этого блока не кладёт"

    through_the_old_name = previous_from_store(store, digest)
    through_the_deriver = previous_from_stored_publication(store, digest)
    assert through_the_old_name == through_the_deriver, (
        "два входа обязаны отвечать ОДНИМ выводом, иначе один из них — тупик")
    assert through_the_old_name["identity"]["schema"] == "kir-create-identity-assessment/1"


# ───────────────────── the loop, through the real store ─────────────────────

def test_the_second_plan_asks_revit_for_nothing_after_a_reopen(tmp_path):
    """THE POINT OF THE WHOLE PROGRAMME, in one number: 0 operations.

    The store is closed and reopened from disk before the second plan, so nothing
    a variable happens to still hold can make this pass.
    """
    digest = published(tmp_path)
    store = ProjectStore.open(tmp_path / "project.sqlite")
    previous = previous_from_stored_publication(store, digest)
    assert previous["identity"]["schema"] == "kir-create-identity-assessment/1"
    assert {row["state"] for row in previous["identity"]["outputs"]} == {"created_here"}

    program = previous["program"]
    plan = plan_republish(None, program, previous)
    assert plan.counts() == {"keep": 5, "update": 0, "replace": 0, "delete": 0, "create": 0}
    assert plan.creates_over_known_identity() == ()
    assert republish_program(plan, program).program["ops"] == [], "повтор без изменений просит НОЛЬ"


def test_a_changed_value_plans_in_place_over_the_stored_identities(tmp_path):
    digest = published(tmp_path)
    store = ProjectStore.open(tmp_path / "project.sqlite")
    previous = previous_from_stored_publication(store, digest)

    taller = materialize_project(project(height_mm=3300.0), {}).to_program()
    plan = plan_republish(None, taller, previous)
    assert plan.counts()["create"] == 0 and plan.counts()["update"] == 4
    ops = republish_program(plan, taller).program["ops"]
    assert [op["op"] for op in ops] == ["set_param"] * 4
    assert {op["expected_current"]["value"] for op in ops} == {3000}, (
        "сверяться надо с ОПУБЛИКОВАННЫМ значением, а не с новым")
    assert all(op["target"]["by"] == "unique_id" for op in ops)


def test_the_program_comes_out_of_the_archive_not_out_of_the_caller(tmp_path):
    """A caller-supplied program would be a second carrier of the same fact."""
    source = project()
    digest = published(tmp_path, source)
    store = ProjectStore.open(tmp_path / "project.sqlite")
    stored = program_as_published(store.get_create_publication(digest).record)
    assert stored == materialize_project(source, {}).to_program()


# ───────────────── the receipt of a republication becomes a record ─────────────────

def test_a_fake_executors_receipt_becomes_a_record_the_store_reserves(tmp_path):
    """S's offline fake executor → запись → store, through the existing `reserve`."""
    digest = published(tmp_path)
    store = ProjectStore.open(tmp_path / "project.sqlite")
    previous = previous_from_stored_publication(store, digest)

    source = project(height_mm=3300.0)
    materialized = materialize_project(source, {})
    program = materialized.to_program()
    plan = plan_republish(None, program, previous)
    derived = republish_program(plan, program)
    receipt = republish_receipt(plan, derived,
                               {op["id"]: {"ok": True} for op in derived.program["ops"]},
                               published_program=program)

    record = saved_record_from_receipt(
        receipt, project=source, materialized=materialized,
        target=RuntimeTarget(str(uuid4()), str(uuid4()), "2023"),
        precondition=ContextPrecondition(DOCUMENT, REVISION + 1),
        operation_id=str(uuid4()))
    assert record.to_dict()["schema"] == PROJECT_ARCHIVE_SCHEMA

    second = ProjectStore.create(tmp_path / "next.sqlite", source, schema=CREATE_STORE_SCHEMA)
    reservation = second.reserve_create_publication(record, expected_revision=source.revision_id)
    assert reservation.inserted and reservation.archive_digest == record.digest
    assert set(reservation.output_ids) == set(check_identities(receipt))

    edges = import_edges(receipt, archive_digest=record.digest,
                         original_archive_digest=digest,
                         original_receipt_digest="b" * 64)
    assert len(edges) == len(receipt.outputs) and all(len(edge) == 4 for edge in edges)
    assert {edge[0] for edge in edges} == {record.digest}


# ───────────────────────────── named refusals ─────────────────────────────

def test_control_a_publication_with_no_receipt_refuses_instead_of_replanning(tmp_path):
    source = project()
    target = RuntimeTarget(str(uuid4()), str(uuid4()), "2023")
    store = ProjectStore.create(tmp_path / "project.sqlite", source, schema=CREATE_STORE_SCHEMA)
    record = archive(source, target=target, operation_id=str(uuid4()))
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    with pytest.raises(RepublishArchiveError) as refused:
        previous_from_stored_publication(store, record.digest)
    assert refused.value.code == "publication_has_no_receipt"


def test_control_an_uncaptured_identity_never_becomes_a_silent_create(tmp_path):
    """🔴 THE DANGEROUS CASE. The run committed, but no identity came back. The
    plan must NOT read that as «этого элемента нет» and build it again."""
    digest = published(tmp_path, captured=False)
    store = ProjectStore.open(tmp_path / "project.sqlite")
    previous = previous_from_stored_publication(store, digest)
    assert {row["state"] for row in previous["identity"]["outputs"]} == {"unavailable"}
    with pytest.raises(RepublishError) as refused:
        plan_republish(None, previous["program"], previous)
    assert refused.value.code == "ledger_has_no_identity_for_output"
    # The refusal is the WHOLE point: silence here would have been a `create`.


def test_control_a_receipt_without_an_identity_never_becomes_a_record():
    with pytest.raises(RepublishArchiveError) as refused:
        check_identities({"schema": "kir-republish-receipt/1",
                          "outputs": [{"output_id": "w0"}]})
    assert refused.value.code == "identity_after_missing"
    assert "query_element_state" in str(refused.value), "отказ обязан называть следующий ход"
