"""Real portable transport/native serializer; query result is explicitly seeded.

The fixture does not invoke generated C# or establish that a real Revit model
was unchanged. It checks the public context/preparation/request/response path.
"""
import json
from uuid import uuid4

import pytest

from kir.connector_result import assess_connector_query_response
from kir.revit_connector import prepare_execution
from kir.revit_transport import exchange
from kir.tests.test_revit_transport import helper, native_server, wire
from kir.tests.test_standalone_publish import probe, sent


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_actual_native_query_receipt_serialization_and_lookup_keep_original_context(native_server, helper, year):
    advertisement, root = native_server(year)
    precondition = probe(advertisement, helper)
    seeded = {"read": {"id": "700", "name": "Seeded—not read from Revit"}}
    (root / "seed-result.json").write_text(json.dumps(seeded), encoding="utf-8")
    artifact = prepare_execution({"ops": [{"op": "query_inspect", "id": "read",
        "target": {"by": "element_id", "value": 700}}]}, target=advertisement.credentials.target,
        precondition=precondition, operation_id=str(uuid4()))
    request = artifact.execute_request(advertisement.credentials, request_id=str(uuid4()))
    response = exchange(advertisement, wire(request), client_path=helper, timeout_ms=10000)
    result = assess_connector_query_response(artifact, response,
        credentials=advertisement.credentials, request_id=request["request_id"])
    assert result.result_available and result.result == seeded
    assert result.precondition is precondition
    assert result.receipt["transaction_evidence"] == "changes_not_observed"
    lookup = artifact.receipt_request(advertisement.credentials, request_id=str(uuid4()))
    recovered = exchange(advertisement, wire(lookup), client_path=helper, timeout_ms=10000)
    second = assess_connector_query_response(artifact, recovered,
        credentials=advertisement.credentials, request_id=lookup["request_id"])
    assert second.result_available and second.result == seeded
    assert second.precondition is precondition
    assert sent(root) == ["context", "execute", "receipt"]
