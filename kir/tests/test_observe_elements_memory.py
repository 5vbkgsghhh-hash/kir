"""Read orchestration order with synthetic responses, no transport or files."""
from hashlib import sha256
import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir.revit_connector import ConnectorPreparationError, RuntimeTarget
from kir.revit_discovery import load_discovery
from kir.revit_observation import observe_elements, ObservationRefusal
from kir.revit_transport import ConnectorTransportError
from kir.tests.test_revit_observation import row


def scenario(fault=None):
    target = RuntimeTarget(str(uuid4()), str(uuid4()), "2026")
    ad = load_discovery(json.dumps({"protocol": "kir-revit-connector/4", "target": target.to_dict(),
        "session_id": str(uuid4()), "token": "synthetic-private-token", "pipe_name": "not-connected",
        "process_id": 123, "expires_utc": "2099-01-01T00:00:00.0000000Z"}).encode())
    events = []
    def exchange(advertisement, wire, **kwargs):
        request = json.loads(wire)
        events.append(request["kind"])
        response = {"protocol": request["protocol"], "target": request["target"], "session_id": request["session_id"],
            "request_id": request["request_id"], "ok": True, "error": None, "context": None, "receipt": None}
        if request["kind"] == "context":
            response.update(status="context", context={"has_document": True, "document_key": "other" if fault == "document" else "chosen-doc",
                "document_title": "not an identity", "revit_version": "2026", "revision": 10,
                "active_view_id": 11, "selection_digest": sha256(b"").hexdigest(), "selection_count": 0,
                "is_family_document": False, "is_read_only": False, "is_modifiable": False, "complete": True})
            if fault == "session": response["session_id"] = str(uuid4())
        else:
            assert events == ["context", "execute"]
            assert request["precondition"]["document_key"] == "chosen-doc" and request["precondition"]["revision"] == 10
            assert request["precondition"]["active_view_id"] is None and request["precondition"]["selection_digest"] is None
            assert "query_element_state" in request["source"] and "new Transaction(" not in request["source"]
            if fault == "lost": raise ConnectorTransportError("synthetic_lost_read", "response", delivery="unknown")
            receipt = {key: request[key] for key in ("target", "operation_id", "source_sha256", "precondition")}
            receipt.update(document_key="chosen-doc", state="invocation_completed", started=True, may_retry=False,
                transaction_evidence="changes_not_observed", semantic_evidence="unverified", error=None,
                result_json=json.dumps({"observe_0": row()}), result_truncated=False, result_error=None,
                changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False},
                timestamp_utc="2026-09-05T12:00:00Z")
            if fault == "changed_before_read":
                receipt.update(state="context_changed_before_start", started=False, may_retry=True, error="changed",
                    changes=None, transaction_evidence="not_observed", result_json=None)
            response.update(status="receipt", receipt=receipt)
        return json.dumps(response).encode()
    expected = RuntimeTarget(str(uuid4()), str(uuid4()), "2026") if fault == "target" else target
    with patch("kir.revit_transport.exchange", side_effect=exchange):
        try:
            observed = observe_elements(["level-uid"], advertisement=ad, client_path="/not-invoked", expected_target=expected,
                expected_document_key="chosen-doc", operation_id=str(uuid4()), bind_view=False, bind_selection=False)
        except (ObservationRefusal, ConnectorPreparationError, ConnectorTransportError) as error:
            return error, events
    return observed, events


def test_exact_context_precedes_one_read_and_is_retained():
    observed, events = scenario()
    assert events == ["context", "execute"] and observed.precondition.revision == 10
    assert observed.require_level("level-uid")["level"]["project_elevation_mm"] == 3000


@pytest.mark.parametrize("fault,events", [("target", []), ("document", ["context"]), ("session", ["context"]),
    ("changed_before_read", ["context", "execute"]), ("lost", ["context", "execute"])])
def test_wrong_binding_or_lost_read_never_refreshes_context_or_retries(fault, events):
    error, actual = scenario(fault)
    assert isinstance(error, Exception) and actual == events
