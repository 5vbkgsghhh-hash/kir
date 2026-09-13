"""Actual emitted query -> fake API execution -> typed observation parser.

Only the query fragments execute. The native receipt/binding is synthetic;
this does not establish actual Revit getter behavior, transport authentication,
DocumentChanged behavior, original creation ownership, or write permission.
"""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution
from kir.revit_observation import ObservationRefusal, parse_element_observation
from kir.tests.test_element_query_execution import CASES, OPS, query_rows


@pytest.fixture(scope="module", params=("2023", "2026"))
def query_binding(request):
    target = RuntimeTarget(str(uuid4()), str(uuid4()), request.param)
    credentials = SessionCredentials(target, str(uuid4()), "synthetic-query-credential")
    artifact = prepare_execution({"ops": OPS}, target=target,
        precondition=ContextPrecondition("synthetic-open-document", 17), operation_id=str(uuid4()))
    return request.param, artifact, credentials


def envelope(artifact, credentials, result):
    """Seed only the receipt. Result must come from the executed query fixture."""
    return {"protocol": "kir-revit-connector/4", "request_id": str(uuid4()),
        "target": credentials.target.to_dict(), "session_id": credentials.session_id,
        "ok": True, "status": "receipt", "error": None, "context": None,
        "receipt": {**artifact.binding_dict(), "document_key": artifact.precondition.document_key,
            "state": "invocation_completed", "started": True, "may_retry": False,
            "transaction_evidence": "changes_not_observed", "semantic_evidence": "unverified",
            "result_json": json.dumps(result), "result_truncated": False,
            "result_error": None, "error": None,
            "changes": {"added": [], "modified": [], "deleted": [],
                        "transaction_names": [], "truncated": False},
            "timestamp_utc": "2026-09-05T12:00:00.0000000Z"}}


def parse(artifact, credentials, response):
    return parse_element_observation(artifact, json.dumps(response), credentials=credentials,
                                     request_id=response["request_id"])


@pytest.mark.parametrize("scenario", CASES)
def test_every_executed_getter_outcome_survives_the_real_field_parser(query_rows, query_binding, scenario):
    year, artifact, credentials = query_binding
    actual = query_rows[f"{year}:{scenario}"]["result"]
    observed = parse(artifact, credentials, envelope(artifact, credentials, actual))
    assert observed.precondition is artifact.precondition
    assert observed.precondition.revision == 17
    assert observed.rows == {op["unique_id"]: actual[op["id"]] for op in OPS}
    assert set(observed.rows) == {"level-uid", "protected-uid"}
    document_unavailable = scenario in {"document_modifiable", "document_state_throw"}
    if document_unavailable:
        with pytest.raises(ObservationRefusal, match="element_identity_unavailable"):
            observed.require_identity("protected-uid")
    else:
        assert observed.require_identity("protected-uid").element_id == 800
    assert not hasattr(observed, "write_allowed")

    level = actual["read-level"]
    if level["status"] == "observed":
        identity = observed.require_identity("level-uid")
        assert identity.unique_id == "level-uid"
        assert identity.element_id == level["element_identity"]["element_id"]
    else:
        with pytest.raises(ObservationRefusal, match="element_identity_unavailable"):
            observed.require_identity("level-uid")
    if (level["status"] == "observed" and level["level_status"] == "observed"
            and level["type_state"]["status"] == "observed"):
        assert observed.require_level("level-uid") == level
    else:
        with pytest.raises(ObservationRefusal, match="level_observation_unavailable"):
            observed.require_level("level-uid")

    # Accessors return detached state, not aliases of the retained observation.
    detached = observed.rows
    if document_unavailable:
        detached["protected-uid"]["reason"] = "forged"
        assert observed.rows["protected-uid"]["reason"] != "forged"
    else:
        detached["protected-uid"]["element_identity"]["element_id"] = 999
        assert observed.require_identity("protected-uid").element_id == 800


@pytest.mark.parametrize("mutation", ("missing_scope", "requested_uid", "revision", "transaction", "truncated"))
def test_executed_positive_cannot_hide_scope_or_binding_corruption(query_rows, query_binding, mutation):
    year, artifact, credentials = query_binding
    actual = deepcopy(query_rows[f"{year}:normal"]["result"])
    if mutation == "missing_scope":
        del actual["read-protected"]
    elif mutation == "requested_uid":
        actual["read-level"]["requested_unique_id"] = "another-uid"
    response = envelope(artifact, credentials, actual)
    if mutation == "revision":
        response["receipt"]["precondition"]["revision"] += 1
    elif mutation == "transaction":
        response["receipt"]["changes"]["transaction_names"] = ["unexpected transaction"]
    elif mutation == "truncated":
        response["receipt"]["changes"]["truncated"] = True
    with pytest.raises(ObservationRefusal):
        parse(artifact, credentials, response)
