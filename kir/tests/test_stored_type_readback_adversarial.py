"""Independent readback orchestration: real SQLite/compiler/parser, synthetic wire.

Small monkeypatched chunk budgets exercise the actual batching path without
large fixtures. These are not Revit execution or live-currentness proofs.
"""
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from kir import standalone_publish, revit_observation, revit_transport
from kir.project_store import ProjectStore, CREATE_STORE_SCHEMA
from kir.stored_type_readback import readback_stored_create_types
from kir.tests import test_stored_type_readback as fixtures
from kir.tests.test_create_not_started_store import rows
from kir.tests.test_create_type_discrepancy_adversarial import selected_case
from kir.tests.test_project_publication_cli import call, arguments
from kir.tests.test_connector_cli import write_advertisement
from kir.tests.test_revit_observation import identity


def deny_mutations(monkeypatch):
    def forbidden(*_args, **_kwargs): pytest.fail("readback changed publication/authoring authority")
    for name in ("commit", "reserve_create_publication", "release_create_not_started", "upgrade_schema"):
        monkeypatch.setattr(ProjectStore, name, forbidden)
    monkeypatch.setattr(standalone_publish, "publish_stored_project", forbidden)


def wrap_exchange(monkeypatch, transform):
    original = revit_transport.exchange
    def exchange(advertisement, wire, **kwargs):
        raw = original(advertisement, wire, **kwargs)
        request, response = json.loads(wire), json.loads(raw)
        return json.dumps(transform(request, response)).encode()
    monkeypatch.setattr(revit_transport, "exchange", exchange)
    monkeypatch.setattr(standalone_publish, "exchange", exchange)


def test_selected_scope_queries_only_qualified_archived_outputs_not_extra_receipt_ids(tmp_path, monkeypatch):
    selected = selected_case()
    monkeypatch.setattr(fixtures, "scenario", lambda *_a, **_kw: selected)
    case, store, options, events, queries = fixtures.setup(tmp_path, monkeypatch)
    # Neither a stale/refused selected capture nor an unrequested extra native
    # result may expand the queried UID scope.
    refused = case["ids"]["wall-1"]
    case["result"][refused]["internal"] = True
    case["result"]["unrequested-native-result"] = {"id": "888888", **identity(888888, "foreign-not-in-publication")}
    case["response"]["receipt"]["changes"]["added"].append(888888)
    before = rows(store)
    deny_mutations(monkeypatch)
    report = readback_stored_create_types(store, case["record"].digest, **options)
    requested = [op["unique_id"] for query in queries for op in query.planned.to_ops()]
    qualified = tuple(row["element_identity"]["unique_id"] for row in report.identities.to_dict()["outputs"]
                      if row["state"] in ("created_here", "reused_existing"))
    assert tuple(requested) == report.requested_unique_ids == qualified
    assert "uid-wall-1" not in requested and "foreign-not-in-publication" not in requested
    assert len(case["project"].instances) == 2
    data = report.discrepancy.to_dict()
    assert data["selected_output_count"] == 7 and data["consumer_count"] == 4
    assert data["counts"] == {"matched": 3, "mismatch": 0, "unavailable": 1, "conflict": 0}
    assert all(row["instance_key"] == "section" for row in data["outputs"])
    after = rows(store)
    assert {k: v for k, v in before.items() if k != "create_receipts"} == {k: v for k, v in after.items() if k != "create_receipts"}
    assert len(after["create_receipts"]) == 1
    assert [event["kind"] for event in events] == ["receipt", "context", "execute"]


@pytest.mark.parametrize("fault", ["transport", "deleted", "transaction", "selection", "view", "uid", "shared-type-version"])
def test_second_chunk_failure_never_leaves_complete_observation_or_all_matched_report(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(revit_observation, "MAX_OBSERVATION_ELEMENTS", 4)
    case, store, options, events, queries = fixtures.setup(tmp_path, monkeypatch)
    before = rows(store)
    deny_mutations(monkeypatch)
    count = 0
    def corrupt_second(request, response):
        nonlocal count
        if request["kind"] != "execute": return response
        count += 1
        if count != 2: return response
        receipt = response["receipt"]
        if fault == "transport":
            raise revit_transport.ConnectorTransportError("independent_second_read_lost", "response", delivery="unknown")
        if fault == "deleted":
            receipt["changes"]["deleted"] = [900]
            receipt["transaction_evidence"] = "changes_observed"
        elif fault == "transaction": receipt["changes"]["transaction_names"] = ["Unexpected write transaction"]
        elif fault == "selection": receipt["precondition"]["selection_digest"] = "e" * 64
        elif fault == "view": receipt["precondition"]["active_view_id"] = 43
        else:
            result = json.loads(receipt["result_json"])
            for row in result.values():
                if fault == "uid": row["requested_unique_id"] = "not-requested"
                elif row["type_state"]["status"] == "observed":
                    row["type_state"]["element_identity"]["version_guid"] = "b" * 32
            receipt["result_json"] = json.dumps(result)
        return response
    wrap_exchange(monkeypatch, corrupt_second)
    result = readback_stored_create_types(store, case["record"].digest, **options)
    assert result.observation is None and result.discrepancy is None
    assert result.identities is not None and result.publication.retained_receipt_digest
    assert result.diagnostic_code != "type_links_compared_at_observed_revision"
    assert [e["kind"] for e in events] == ["receipt", "context", "execute", "execute"]
    assert len(queries) == 2 and queries[0].precondition is queries[1].precondition
    assert rows(store)["create_scope_owners"] == before["create_scope_owners"]
    assert rows(store)["create_inputs"] == before["create_inputs"]
    assert store.get_create_publication(case["record"].digest).state == "reserved"


def test_each_input_in_aggregate_report_is_the_actual_chunk_not_an_invented_query(tmp_path, monkeypatch):
    monkeypatch.setattr(revit_observation, "MAX_OBSERVATION_ELEMENTS", 4)
    case, store, options, events, queries = fixtures.setup(tmp_path, monkeypatch)
    result = readback_stored_create_types(store, case["record"].digest, **options)
    observed = result.discrepancy.to_dict()["observation"]
    actual = [{"operation_id": query.operation_id, "source_sha256": query.source_sha256,
               "requested_unique_ids": [op["unique_id"] for op in query.planned.to_ops()]} for query in queries]
    assert observed["query_inputs"] == actual
    encoded = json.dumps(actual, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert observed["query_inputs_digest"] == sha256(encoded).hexdigest()
    assert "operation_id" not in observed and "source_sha256" not in observed
    assert observed["precondition"] == queries[0].precondition.to_dict()
    assert observed["precondition"] == {"document_key": "native-doc", "revision": 9,
        "active_view_id": 42, "selection_digest": "d" * 64}
    assert sum(event["kind"] == "context" for event in events) == 1
    detached = result.observation.rows
    detached["uid-wall-0"]["type_state"]["status"] = "none"
    assert result.observation.rows["uid-wall-0"]["type_state"]["status"] == "observed"
    assert result.to_dict()["claims"]["current_model_state"] == "not_established"


def test_head_advanced_during_read_is_not_mislabeled_current_intent(tmp_path, monkeypatch):
    case, store, options, events, _ = fixtures.setup(tmp_path, monkeypatch)
    original = case["project"]
    newer = original.revise(expected_revision=original.revision_id, metadata={"different-intent": "new draft"})
    def advance(request, response):
        if request["kind"] == "receipt": store.commit(newer, expected_revision=original.revision_id)
        return response
    wrap_exchange(monkeypatch, advance)
    result = readback_stored_create_types(store, case["record"].digest, **options).to_dict()
    assert store.head().revision_id == newer.revision_id
    assert result["source_project"]["revision_id"] == original.revision_id
    assert result["authored_head_seen_before_lookup"] == original.revision_id
    assert result["head_seen_matches_source"]  # Explicitly historical label only.
    assert result["claims"]["current_authored_head"] == "not_established"
    assert result["claims"]["authoring_basis"] == "archived_publication_not_current_head"
    assert result["type_discrepancy"]["project"]["revision_id"] == original.revision_id
    assert [e["kind"] for e in events] == ["receipt", "context", "execute"]


def test_request_budget_refusal_retains_only_receipt_and_never_queries_or_releases(tmp_path, monkeypatch):
    case, store, options, events, queries = fixtures.setup(tmp_path, monkeypatch)
    before = rows(store)
    monkeypatch.setattr(revit_observation, "MAX_OBSERVATION_AGGREGATE_BYTES", 20)
    deny_mutations(monkeypatch)
    result = readback_stored_create_types(store, case["record"].digest, **options)
    assert result.diagnostic_code == "observation_aggregate_budget"
    assert result.discrepancy is None and result.observation is None
    assert [e["kind"] for e in events] == ["receipt"] and not queries
    assert result.publication.retained_receipt_digest
    assert rows(store)["create_scope_owners"] == before["create_scope_owners"]
    assert store.get_create_resolution(case["record"].digest) is None


@pytest.mark.parametrize("fault", ["outer-session", "original-source", "outer-unconfirmed"])
def test_unqualified_original_receipt_never_becomes_a_uid_query_grant(tmp_path, monkeypatch, fault):
    case, store, options, events, queries = fixtures.setup(tmp_path, monkeypatch)
    before = rows(store)
    def invalid_receipt(request, response):
        assert request["kind"] == "receipt"
        if fault == "outer-session": response["session_id"] = str(uuid4())
        elif fault == "original-source": response["receipt"]["source_sha256"] = "f" * 64
        else: response.update(ok=False, status="journal_unavailable", error="unconfirmed receipt")
        return response
    wrap_exchange(monkeypatch, invalid_receipt)
    deny_mutations(monkeypatch)
    result = readback_stored_create_types(store, case["record"].digest, **options)
    assert result.identities is None and result.requested_unique_ids == ()
    assert result.observation is None and result.discrepancy is None
    assert [event["kind"] for event in events] == ["receipt"] and not queries
    after = rows(store)
    assert {k: v for k, v in before.items() if k != "create_receipts"} == {k: v for k, v in after.items() if k != "create_receipts"}
    assert len(after["create_receipts"]) == (1 if fault == "outer-unconfirmed" else 0)


def test_schema6_readback_never_upgrades_and_repeat_lookups_only_deduplicate_receipt(tmp_path, monkeypatch):
    case, _, options, events, queries = fixtures.setup(tmp_path, monkeypatch)
    store = ProjectStore.create(tmp_path / "schema6.sqlite", case["project"], schema=CREATE_STORE_SCHEMA)
    store.reserve_create_publication(case["record"], expected_revision=case["project"].revision_id)
    before = rows(store)
    deny_mutations(monkeypatch)
    first = readback_stored_create_types(store, case["record"].digest, **options)
    again = readback_stored_create_types(store, case["record"].digest, **options)
    assert first.discrepancy is not None and again.discrepancy is not None
    assert first.publication.retained_receipt_digest == again.publication.retained_receipt_digest
    assert len(store.get_create_receipts(case["record"].digest).to_dict()["receipts"]) == 1
    assert store.schema == CREATE_STORE_SCHEMA and "create_resolutions" not in rows(store)
    assert before["create_scope_owners"] == rows(store)["create_scope_owners"]
    assert [event["kind"] for event in events] == ["receipt", "context", "execute"] * 2
    assert queries[0].operation_id != queries[1].operation_id


@pytest.mark.parametrize("fault,answered", [("type_mismatch", True), ("partial", True), ("query_lost", False)])
def test_cli_status_is_answered_comparison_not_whole_bim_acceptance(tmp_path, monkeypatch, fault, answered):
    from kir import __main__ as cli
    case, store, options, events, _ = fixtures.setup(tmp_path, monkeypatch, fault=fault)
    directory = tmp_path / "discovery"
    write_advertisement(directory, options["advertisement"])
    args = arguments("create-readback-types", store, options["advertisement"], "/not-opened", directory)
    code, data, errors = call(args + ["--archive", case["record"].digest, "--document-key", "native-doc",
                                    "--bind-view", "yes", "--bind-selection", "yes"])
    assert code == (cli.ANSWERED if answered else cli.REFUSED), (data, errors)
    assert data["status"] == ("readback" if answered else "unavailable")
    assert not data["intent_verified"] and not data["may_retry"]
    assert data["readback"]["claims"]["bim_acceptance"] == "not_established"
    assert "synthetic-private-token" not in json.dumps(data)
    assert not any(event["kind"] in ("cancel_before_start", "recover_receipt") for event in events)


def test_same_chunk_not_found_type_contradiction_is_not_a_complete_aggregate(monkeypatch):
    from kir.tests.test_element_observation_scope import carriers
    make, _, _ = carriers.__wrapped__()
    def missing(rows):
        rows["observe_1"].update(status="not_found", name=None, category_id=None, is_level=None,
            type_state=None, level_status="not_evaluated", element_identity=None,
            element_identity_status="unavailable", element_identity_reason="element_missing")
    # The generic individual parser keeps this row-level unavailable fact; the
    # aggregate must notice that another row affirmatively uses that same type.
    parsed = make(["consumer", "type-uid"], mutate=missing)
    assert parsed.rows["type-uid"]["status"] == "not_found"
    with pytest.raises(revit_observation.ObservationRefusal, match="conflicting_element_identity"):
        revit_observation.combine_element_observations([parsed], expected_unique_ids=["consumer", "type-uid"])
