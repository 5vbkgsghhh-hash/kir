"""Real stored source/compiler/query parser; synthetic native exchange only."""
from copy import deepcopy
import json

import pytest

from kir import standalone_publish, revit_observation, revit_transport
from kir.project_store import ProjectStore, CREATE_RESOLUTION_STORE_SCHEMA
from kir.revit_discovery import load_discovery
from kir.stored_type_readback import readback_stored_create_types, StoredTypeReadbackError
from kir.tests.test_create_type_discrepancy import scenario
from kir.tests.test_revit_observation import identity, row, unavailable
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_project_publication_cli import call, arguments
from kir.tests.test_connector_cli import write_advertisement


def setup(tmp_path, monkeypatch, *, walls=2, fault=None, later_head=False):
    case = scenario(tmp_path, walls=walls, both_floors=True)
    store = ProjectStore.create(tmp_path / "project.sqlite", case["project"], schema=CREATE_RESOLUTION_STORE_SCHEMA)
    store.reserve_create_publication(case["record"], expected_revision=case["project"].revision_id)
    if later_head:
        later = case["project"].revise(expected_revision=case["project"].revision_id, metadata={"later": True})
        store.commit(later, expected_revision=case["project"].revision_id)
    creds = case["credentials"]
    ad = load_discovery(json.dumps({"protocol": "kir-revit-connector/4", "target": creds.target.to_dict(),
        "session_id": creds.session_id, "token": creds.token, "pipe_name": "synthetic-not-opened", "process_id": 1,
        "expires_utc": "2099-01-01T00:00:00.0000000Z"}).encode())
    values = {}
    for output in case["record"].project_submission["outputs"]:
        key = output["output_key"]
        native = case["result"][output["output_id"]]
        uid = native["element_identity"]["unique_id"]
        value = row(uid, is_level=output["source_op"] == "create_level")
        value.update(identity(int(native["id"]), uid))
        if output["source_op"] in ("create_wall", "create_floor", "create_floor_by_contour"):
            floor = output["source_op"] != "create_wall"
            value["type_state"] = {"status": "observed", **identity(801 if floor else 800,
                "uid-floor-type" if floor else "uid-wall-type")}
        elif output["source_op"] == "create_level":
            value["type_state"] = {"status": "observed", **identity(600000, "native-level-type")}
        else:
            value["type_state"] = {"status": "none", **unavailable()}
        values[uid] = value
    if fault == "type_mismatch":
        values["uid-wall-0"]["type_state"] = {"status": "observed", **identity(100, "seed-type-100")}
    if fault == "partial":
        native = case["result"][case["ids"]["wall-0"]]
        case["response"]["receipt"]["changes"]["added"].remove(int(native["id"]))
        case["result"][case["ids"]["wall-0"]] = {"refused": "controlled partial refusal"}
    if fault == "unqualified":
        for native in case["result"].values():
            if type(native) is dict:
                native.update(element_identity=None, element_identity_status="unavailable", element_identity_reason="identity_unreadable")
    events, queries = [], []
    actual_prepare = revit_observation.prepare_element_observation
    def prepare(*args, **kwargs):
        prepared = actual_prepare(*args, **kwargs)
        queries.append(prepared)
        return prepared
    monkeypatch.setattr(revit_observation, "prepare_element_observation", prepare)
    def exchange(advertisement, wire, **kwargs):
        request = json.loads(wire)
        events.append(request)
        if request["kind"] == "receipt":
            answer = deepcopy(case["response"])
            answer["receipt"]["result_json"] = json.dumps(case["result"])
            if fault == "receipt_missing":
                answer.update(ok=False, status="not_found", error="not found", receipt=None)
        elif request["kind"] == "context":
            answer = deepcopy(case["response"])
            answer.update(status="context", receipt=None, context={"has_document": True, "document_key": "native-doc",
                "document_title": "Not identity", "revit_version": creds.target.revit_version, "revision": 9,
                "active_view_id": 42, "selection_digest": "d" * 64, "selection_count": 2,
                "is_family_document": False, "is_read_only": False, "is_modifiable": False, "complete": True})
        else:
            assert request["kind"] == "execute" and queries
            prepared = queries[-1]
            assert prepared.planned.family.value == "query"
            assert prepared.source == request["source"] and prepared.source_sha256 == request["source_sha256"]
            assert all(op.op_name == "query_element_state" for op in prepared.planned.ops)
            assert "new Transaction(" not in prepared.source
            if fault == "query_lost":
                raise revit_transport.ConnectorTransportError("controlled_read_lost", "response", delivery="unknown")
            payload = {op["id"]: values[op["unique_id"]] for op in prepared.planned.to_ops()}
            answer = response_for(prepared, creds, payload,
                changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
            if fault == "second_drift" and len(queries) == 2:
                answer["receipt"]["precondition"]["revision"] = 10
        answer.update(request_id=request["request_id"], session_id=creds.session_id, target=creds.target.to_dict())
        return json.dumps(answer).encode()
    monkeypatch.setattr(standalone_publish, "exchange", exchange)
    monkeypatch.setattr(revit_transport, "exchange", exchange)
    monkeypatch.setattr(standalone_publish, "prepare_execution", lambda *_a, **_kw: pytest.fail("readback recompiled CREATE"))
    options = dict(advertisement=ad, client_path="/not-opened", expected_target=creds.target,
        expected_document_key="native-doc", bind_view=True, bind_selection=True)
    return case, store, options, events, queries


@pytest.mark.parametrize("walls", [2, 130])
def test_stored_source_receipt_then_pinned_queries_then_type_report(tmp_path, monkeypatch, walls):
    case, store, options, events, queries = setup(tmp_path, monkeypatch, walls=walls)
    result = readback_stored_create_types(store, case["record"].digest, **options)
    data = result.to_dict()
    assert data["type_discrepancy"]["consumer_count"] == walls + 2
    assert data["type_discrepancy"]["counts"]["matched"] == walls + 2
    assert [event["kind"] for event in events] == ["receipt", "context"] + ["execute"] * len(queries)
    assert len(queries) == (walls + 5 + 127) // 128
    assert all(query.precondition == queries[0].precondition for query in queries)
    assert data["claims"]["current_model_state"] == "not_established"
    assert data["type_discrepancy"]["claims"]["type_definition"] == "not_evaluated"
    observed = data["type_discrepancy"]["observation"]
    assert "operation_id" not in observed and "source_sha256" not in observed
    assert len(observed["query_inputs"]) == len(queries)
    assert store.head().revision_id == case["project"].revision_id
    assert store.get_create_publication(case["record"].digest).state == "reserved"
    assert len(store.get_create_receipts(case["record"].digest).to_dict()["receipts"]) == 1


@pytest.mark.parametrize("fault", ["receipt_missing", "unqualified", "query_lost", "second_drift"])
def test_unavailable_evidence_does_not_manufacture_type_acceptance(tmp_path, monkeypatch, fault):
    case, store, options, events, queries = setup(tmp_path, monkeypatch, walls=130 if fault == "second_drift" else 2, fault=fault)
    result = readback_stored_create_types(store, case["record"].digest, **options)
    assert result.discrepancy is None and result.observation is None
    assert result.diagnostic_code != "type_links_compared_at_observed_revision"
    if fault in ("receipt_missing", "unqualified"):
        assert [event["kind"] for event in events] == ["receipt"] and not queries
    else:
        assert result.identities is not None and result.publication.retained_receipt_digest
        assert sum(event["kind"] == "context" for event in events) == 1
    assert store.get_create_publication(case["record"].digest).state == "reserved"


@pytest.mark.parametrize("fault,expected", [("partial", "unavailable"), ("type_mismatch", "mismatch")])
def test_partial_and_wrong_type_keep_full_archived_denominator(tmp_path, monkeypatch, fault, expected):
    case, store, options, _, _ = setup(tmp_path, monkeypatch, fault=fault)
    result = readback_stored_create_types(store, case["record"].digest, **options)
    report = result.discrepancy.to_dict()
    assert report["consumer_count"] == 4 and report["counts"][expected] == 1
    assert report["counts"]["matched"] == 3
    if fault == "partial":
        assert "uid-wall-0" not in result.requested_unique_ids


def test_archived_comparison_does_not_claim_to_validate_newer_authored_head(tmp_path, monkeypatch):
    case, store, options, _, _ = setup(tmp_path, monkeypatch, later_head=True)
    data = readback_stored_create_types(store, case["record"].digest, **options).to_dict()
    assert data["source_project"]["revision_id"] == case["project"].revision_id
    assert not data["head_seen_matches_source"]
    assert data["authored_head_seen_before_lookup"] == store.head().revision_id
    assert data["claims"]["authoring_basis"] == "archived_publication_not_current_head"


def test_wrong_document_refuses_before_transport(tmp_path, monkeypatch):
    case, store, options, events, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(StoredTypeReadbackError, match="publication_observation_target_mismatch"):
        readback_stored_create_types(store, case["record"].digest, **{**options, "expected_document_key": "other"})
    assert not events


def test_cli_exposes_mismatch_as_observed_report_not_mutation_success(tmp_path, monkeypatch):
    from kir import __main__ as cli
    case, store, options, _, _ = setup(tmp_path, monkeypatch, fault="type_mismatch")
    directory = tmp_path / "discovery"
    write_advertisement(directory, options["advertisement"])
    args = arguments("create-readback-types", store, options["advertisement"], "/not-opened", directory)
    code, data, _ = call(args + ["--archive", case["record"].digest, "--document-key", "native-doc",
                                "--bind-view", "yes", "--bind-selection", "yes"])
    assert code == cli.ANSWERED and data["status"] == "readback"
    assert not data["intent_verified"] and not data["may_retry"]
    assert data["readback"]["type_discrepancy"]["counts"]["mismatch"] == 1
