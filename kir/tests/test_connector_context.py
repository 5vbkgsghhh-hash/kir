"""Read response consistency; no simulated native invocation or live channel."""
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

import pytest

from kir.connector_result import assess_connector_context_response
from kir.revit_connector import (
    ConnectorPreparationError, RuntimeTarget, SessionCredentials, prepare_execution,
)


@pytest.fixture
def case():
    credentials = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"),
                                     str(uuid4()), "do-not-log-this-secret")
    request = credentials.context_request(request_id=str(uuid4()))
    snapshot = {"has_document": True, "document_key": "opaque-open-document-A", "document_title": "Башня 😀",
                "revit_version": "2026", "revision": 71, "active_view_id": (1 << 40) + 3,
                "selection_digest": hashlib.sha256(b"31,42").hexdigest(), "selection_count": 2,
                "is_family_document": False, "is_read_only": False, "is_modifiable": False, "complete": True}
    response = {"protocol": request["protocol"], "target": credentials.target.to_dict(),
                "session_id": credentials.session_id, "request_id": request["request_id"], "ok": True,
                "status": "context", "error": None, "context": snapshot, "receipt": None}

    def assess(value=None, *, raw=None):
        return assess_connector_context_response(
            json.dumps(response if value is None else value) if raw is None else raw,
            credentials=credentials, request_id=request["request_id"])
    return credentials, request, response, assess


def refuse_precondition(assessment):
    with pytest.raises(ConnectorPreparationError, match="context_unavailable"):
        assessment.require_precondition(bind_view=True, bind_selection=True)


def test_context_request_is_detached_read_only_and_explicitly_addressed(case):
    auth, request, _, _ = case
    assert set(request) == {"protocol", "target", "session_id", "request_id", "kind", "timeout_ms", "token"}
    assert request["kind"] == "context" and request["timeout_ms"] == 30000
    request["target"]["journal_id"] = str(uuid4())
    assert auth.context_request(request_id=str(uuid4()))["target"] == auth.target.to_dict()
    assert auth.token not in repr(auth)


@pytest.mark.parametrize("bind_view,bind_selection", [(False, False), (False, True), (True, False), (True, True)])
def test_exact_document_revision_and_explicit_ui_conditions_reach_compiler(case, bind_view, bind_selection):
    auth, _, response, assess = case
    result = assess()
    assert result.read_complete and result.binding_matches and result.diagnostic_code == "context_captured"
    assert result.target == auth.target and result.session_id == auth.session_id
    assert result.snapshot == response["context"]
    precondition = result.require_precondition(bind_view=bind_view, bind_selection=bind_selection)
    assert precondition.document_key == "opaque-open-document-A" and precondition.revision == 71
    assert precondition.active_view_id == (response["context"]["active_view_id"] if bind_view else None)
    assert precondition.selection_digest == (response["context"]["selection_digest"] if bind_selection else None)
    artifact = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
        target=result.target, precondition=precondition, operation_id=str(uuid4()))
    assert artifact.execute_request(auth, request_id=str(uuid4()))["precondition"] == precondition.to_dict()


def test_no_document_is_complete_read_but_not_a_precondition(case):
    _, _, response, assess = case
    response["context"] = {"has_document": False, "document_key": "", "document_title": "", "revit_version": "2026",
        "revision": 0, "active_view_id": 0, "selection_digest": "", "selection_count": 0,
        "is_family_document": False, "is_read_only": False, "is_modifiable": False, "complete": True}
    result = assess()
    assert result.read_complete and result.diagnostic_code == "no_document"
    refuse_precondition(result)


def test_incomplete_capture_is_retained_but_cannot_be_used(case):
    _, _, response, assess = case
    response["context"]["complete"] = False
    result = assess()
    assert result.binding_matches and not result.read_complete
    assert result.snapshot == response["context"]
    assert result.diagnostic_code == "context_incomplete"
    refuse_precondition(result)


@pytest.mark.parametrize("flag", ["is_family_document", "is_read_only", "is_modifiable"])
def test_document_flags_are_observations_not_write_permission(case, flag):
    _, _, response, assess = case
    response["context"][flag] = True
    result = assess()
    assert result.read_complete and result.snapshot[flag] is True
    assert result.require_precondition(bind_view=False, bind_selection=False).document_key
    assert not hasattr(result, "write_allowed")


def test_same_title_does_not_replace_the_opaque_open_document_identity(case):
    _, _, response, assess = case
    before = assess().require_precondition(bind_view=True, bind_selection=True)
    response["context"]["document_key"] = "different-open-document-with-identical-title"
    after = assess().require_precondition(bind_view=True, bind_selection=True)
    assert before != after and before.document_key != after.document_key


@pytest.mark.parametrize("field,value", [("protocol", "kir-revit-connector/3"), ("request_id", str(uuid4())),
    ("session_id", str(uuid4())), ("target", None), ("target", {"journal_id": str(uuid4())})])
def test_foreign_or_malformed_route_cannot_supply_precondition(case, field, value):
    _, _, response, assess = case
    response[field] = value
    result = assess()
    assert not result.binding_matches and not result.read_complete and result.snapshot is None
    refuse_precondition(result)


@pytest.mark.parametrize("field,value", [("journal_id", str(uuid4())), ("instance_id", str(uuid4())), ("revit_version", "2023")])
def test_every_runtime_axis_is_bound(case, field, value):
    _, _, response, assess = case
    response["target"][field] = value
    assert not assess().binding_matches
    refuse_precondition(assess())


@pytest.mark.parametrize("field,value", [("ok", 1), ("ok", False), ("status", "receipt"), ("status", None),
    ("error", "failed"), ("error", {}), ("receipt", {}), ("receipt", {"state": "invocation_completed"})])
def test_non_context_or_contradictory_envelope_is_not_a_capture(case, field, value):
    _, _, response, assess = case
    response[field] = value
    assert assess().snapshot is None
    refuse_precondition(assess())


@pytest.mark.parametrize("status", ["disabled", "context_error", "unauthorized", "context_target_mismatch"])
def test_named_native_failure_is_not_a_capture_or_a_retry_directive(case, status):
    _, _, response, assess = case
    response.update(ok=False, status=status, context=None, error="native refusal")
    result = assess()
    assert result.binding_matches and result.diagnostic_code == "context_unavailable"
    assert not result.read_complete
    refuse_precondition(result)


@pytest.mark.parametrize("field,value", [
    ("has_document", 1), ("complete", "true"), ("is_read_only", None), ("is_family_document", 0),
    ("is_modifiable", "false"), ("revision", True), ("revision", -1), ("revision", 1 << 63),
    ("revision", 1.0), ("active_view_id", 1 << 63), ("active_view_id", True),
    ("selection_count", -1), ("selection_count", 1 << 31), ("selection_count", False),
    ("selection_count", 0), ("selection_digest", None), ("selection_digest", "f" * 63),
    ("selection_digest", "F" * 64), ("document_key", ""), ("document_key", "  "),
    ("document_title", None), ("revit_version", "2023"), ("revit_version", ""),
    ("has_document", False),
])
def test_invalid_context_fields_cannot_synthesize_a_precondition(case, field, value):
    _, _, response, assess = case
    response["context"][field] = value
    result = assess()
    assert not result.read_complete and result.snapshot is None
    refuse_precondition(result)


@pytest.mark.parametrize("where", ["envelope", "context"])
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_exact_dto_field_sets_required(case, where, change):
    _, _, response, assess = case
    value = response if where == "envelope" else response["context"]
    if change == "missing":
        value.pop(next(iter(value)))
    else:
        value["future_field"] = None
    refuse_precondition(assess())


def test_no_document_contradiction_is_not_hidden_by_has_document_false(case):
    _, _, response, assess = case
    response["context"]["has_document"] = False
    assert not assess().read_complete
    refuse_precondition(assess())


def test_empty_selection_digest_and_zero_view_are_preserved(case):
    _, _, response, assess = case
    response["context"].update(selection_count=0, selection_digest=hashlib.sha256(b"").hexdigest(), active_view_id=0)
    result = assess()
    assert result.read_complete
    precondition = result.require_precondition(bind_view=True, bind_selection=True)
    assert precondition.active_view_id == 0 and precondition.selection_digest == hashlib.sha256(b"").hexdigest()


def test_nonempty_selection_cannot_claim_the_native_empty_selection_digest(case):
    _, _, response, assess = case
    response["context"].update(selection_count=2, selection_digest=hashlib.sha256(b"").hexdigest())
    result = assess()
    assert not result.read_complete and result.snapshot is None
    refuse_precondition(result)


@pytest.mark.parametrize("raw", [b"", b"null", b"{}", b"{\"a\":1,\"a\":2}", b"{\"a\":NaN}",
    b"{\"a\":1e999}", b"{\"a\":\"\xff\"}", b"\xef\xbb\xbf{}", b"{\"a\":\"\\ud800\"}",
    b"[" * 66 + b"0" + b"]" * 66])
def test_malformed_wire_never_yields_context(case, raw):
    result = case[3](raw=raw)
    assert result.snapshot is None and not result.binding_matches
    refuse_precondition(result)


def test_duplicate_key_in_otherwise_valid_context_is_not_last_wins(case):
    raw = json.dumps(case[2]).replace('"revision": 71', '"revision": 70, "revision": 71')
    result = case[3](raw=raw)
    assert not result.read_complete
    refuse_precondition(result)


def test_context_budget_does_not_retain_over_budget_raw_payload(case, monkeypatch):
    import kir.connector_result as evidence
    monkeypatch.setattr(evidence, "MAX_FRAME_BYTES", 128)
    result = case[3](raw=b" " * 129)
    assert result.diagnostic_code == "response_budget_exceeded" and result.raw_response == b""
    refuse_precondition(result)


def test_snapshot_detached_raw_retained_and_diagnostics_do_not_echo_secrets(case):
    auth, _, response, assess = case
    result = assess()
    clone = result.snapshot
    clone["revision"] = 1000
    assert result.snapshot == response["context"]
    assert json.loads(result.raw_response) == response
    response["context"]["document_title"] = auth.token
    secret_result = assess()
    assert auth.token not in repr(secret_result)
    response["context"]["revision"] = auth.token
    refused = assess()
    assert auth.token not in refused.diagnostic_code and auth.token not in repr(refused)


def test_precondition_requires_explicit_boolean_ui_choices(case):
    result = case[3]()
    with pytest.raises(TypeError):
        result.require_precondition()
    for view, selection in ((1, True), (True, None)):
        with pytest.raises(ConnectorPreparationError, match="invalid_input"):
            result.require_precondition(bind_view=view, bind_selection=selection)


def test_bad_call_arguments_do_not_become_evidence(case):
    auth, request, response, _ = case
    with pytest.raises(ConnectorPreparationError):
        assess_connector_context_response(json.dumps(response), credentials=auth, request_id="bad")
    with pytest.raises(ConnectorPreparationError):
        assess_connector_context_response(json.dumps(response), credentials=None, request_id=request["request_id"])
