"""Response consistency and D1 interpretation; no fake transport success test."""
from copy import deepcopy
from dataclasses import replace
import json
from uuid import uuid4

import pytest

from kir import connector_result as evidence
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution


@pytest.fixture
def case():
    target = RuntimeTarget(str(uuid4()), str(uuid4()), "2023")
    auth = SessionCredentials(target, str(uuid4()), "never-returned-auth-token")
    request_id = str(uuid4())
    artifact = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
        target=target, precondition=ContextPrecondition("native-document-A", 8, 11, "a" * 64),
        operation_id=str(uuid4()))
    receipt = {**artifact.binding_dict(), "document_key": artifact.precondition.document_key,
        "state": "invocation_completed", "started": True, "may_retry": False,
        "transaction_evidence": "changes_observed", "semantic_evidence": "unverified",
        "result_json": json.dumps({"ok": True, "L": {"id": "700"}}),
        "result_truncated": False, "result_error": None, "error": None,
        "changes": {"added": [700], "modified": [], "deleted": [],
                    "transaction_names": ["KIR"], "truncated": False},
        "timestamp_utc": "2026-09-05T12:00:00.0000000Z"}
    response = {"protocol": "kir-revit-connector/4", "request_id": request_id,
                "target": target.to_dict(), "session_id": auth.session_id,
                "ok": True, "status": "receipt", "error": None, "context": None, "receipt": receipt}

    def assess(payload=None, *, wire=None, credentials=auth, recovery=False):
        return evidence.assess_connector_write_response(artifact,
            json.dumps(response if payload is None else payload) if wire is None else wire,
            credentials=credentials, request_id=request_id, recovery=recovery)
    return artifact, auth, response, assess


def assert_unknown(result):
    assert not result.ok
    assert result.outcome.execution.value == "unconfirmed"
    assert result.outcome.retry_safety.value == "verify_first"
    assert result.outcome.acceptance.value == "not_run"


def test_full_bound_result_uses_typed_kir_witness_without_claiming_intent(case):
    _, auth, response, assess = case
    verdict = assess()
    assert verdict.ok and verdict.binding_matches
    assert verdict.outcome.execution.value == "committed"
    assert verdict.outcome.witness.value == "satisfied"
    assert verdict.outcome.acceptance.value == "not_run"
    assert verdict.outcome.retry_safety.value == "forbidden"
    assert verdict.receipt == response["receipt"]
    assert json.loads(verdict.raw_response) == response
    assert auth.token not in repr(verdict)
    detached = verdict.receipt
    detached["target"]["journal_id"] = str(uuid4())
    detached["precondition"]["revision"] = -1
    assert verdict.receipt == response["receipt"]


@pytest.mark.parametrize("field,value", [("protocol", "kir-revit-connector/3"),
    ("request_id", str(uuid4())), ("session_id", str(uuid4())), ("target", None),
    ("ok", 1), ("status", None), ("context", {"has_document": True})])
def test_wrong_or_malformed_route_never_accepts_a_complete_inner_result(case, field, value):
    _, _, response, assess = case
    response[field] = value
    assert_unknown(assess())


@pytest.mark.parametrize("field,value", [("journal_id", str(uuid4())),
    ("instance_id", str(uuid4())), ("revit_version", "2026")])
@pytest.mark.parametrize("where", ["route", "receipt"])
def test_each_runtime_axis_is_checked_on_both_route_and_original_receipt(case, field, value, where):
    _, _, response, assess = case
    destination = response if where == "route" else response["receipt"]
    destination["target"][field] = value
    verdict = assess()
    assert_unknown(verdict)
    assert not verdict.binding_matches


@pytest.mark.parametrize("field,value", [("operation_id", str(uuid4())), ("source_sha256", "f" * 64),
    ("document_key", "native-document-B"), ("precondition", None)])
def test_receipt_execution_input_must_match_the_prepared_artifact(case, field, value):
    _, _, response, assess = case
    response["receipt"][field] = value
    assert_unknown(assess())


@pytest.mark.parametrize("field,value", [("document_key", "B"), ("revision", 9),
    ("revision", 8.0), ("revision", True), ("active_view_id", None), ("active_view_id", 0),
    ("selection_digest", None), ("selection_digest", "")])
def test_every_supplied_precondition_retains_exact_type_and_null_meaning(case, field, value):
    _, _, response, assess = case
    response["receipt"]["precondition"][field] = value
    assert_unknown(assess())


def test_historical_recovery_checks_new_route_but_original_execution_target(case):
    artifact, auth, response, assess = case
    new_target = RuntimeTarget(str(uuid4()), str(uuid4()), "2026")
    current = SessionCredentials(new_target, str(uuid4()), "new-credential")
    response["target"] = new_target.to_dict()
    response["session_id"] = current.session_id
    assert assess(credentials=current, recovery=True).ok
    response["receipt"]["target"] = new_target.to_dict()
    assert_unknown(assess(credentials=current, recovery=True))
    response["receipt"]["target"] = artifact.target.to_dict()
    response["target"] = auth.target.to_dict()
    assert_unknown(assess(credentials=current, recovery=True))


@pytest.mark.parametrize("status", ["not_found", "not_found_unconfirmed", "running_unknown",
    "compile_rejected", "recovery_busy", "journal_unavailable", "legacy_unbound", "unauthorized"])
def test_absence_or_failure_is_never_permission_to_replay(case, status):
    _, _, response, assess = case
    response.update(ok=False, status=status, error="named refusal", receipt=None)
    assert_unknown(assess())


@pytest.mark.parametrize("field,value", [("state", "failed_after_observed_change"),
    ("state", "failed_after_start_unknown"), ("state", "running_unknown"), ("state", "future_success"),
    ("state", []), ("started", 1), ("started", False), ("may_retry", True),
    ("result_truncated", True), ("result_error", "serialization failed"), ("error", "failure"),
    ("semantic_evidence", "verified"), ("timestamp_utc", ""), ("transaction_evidence", "not_observed")])
def test_native_flags_cannot_be_overruled_by_positive_inner_kir_result(case, field, value):
    _, _, response, assess = case
    response["receipt"][field] = value
    assert_unknown(assess())


@pytest.mark.parametrize("where,field", [("response", "error"), ("response", "receipt"),
    ("receipt", "result_truncated"), ("receipt", "precondition"), ("receipt", "target")])
def test_missing_required_fields_are_not_filled_with_positive_defaults(case, where, field):
    _, _, response, assess = case
    del (response if where == "response" else response["receipt"])[field]
    assert_unknown(assess())


@pytest.mark.parametrize("where", ["response", "receipt", "changes"])
def test_unknown_control_fields_are_not_silently_unwrapped_away(case, where):
    _, _, response, assess = case
    destination = response if where == "response" else response["receipt"]
    if where == "changes":
        destination = destination["changes"]
    destination["err"] = {"code": "execution_unknown"}
    assert_unknown(assess())


@pytest.mark.parametrize("inner", ["null", "{}", "[]", '"unconfirmed"'])
def test_invocation_return_alone_does_not_establish_commit(case, inner):
    _, _, response, assess = case
    response["receipt"]["result_json"] = inner
    assert_unknown(assess())


def test_post_commit_missing_identity_remains_committed_incomplete_not_retryable(case):
    _, _, response, assess = case
    response["receipt"]["result_json"] = '{"ok":true}'
    verdict = assess()
    assert not verdict.ok
    assert verdict.outcome.execution.value == "committed"
    assert verdict.outcome.witness.value == "incomplete"
    assert verdict.outcome.retry_safety.value == "forbidden"


def test_inner_witness_failure_is_retained_with_the_full_bound_receipt(case):
    _, _, response, assess = case
    response["receipt"]["result_json"] = json.dumps({"ok": True, "L": {"id": "700"},
                                                   "postcondition_violations": ["wrong elevation"]})
    verdict = assess()
    assert not verdict.ok and verdict.outcome.committed
    assert verdict.outcome.witness.value == "violated"
    assert verdict.assessment.violations == ("wrong elevation",)
    assert verdict.receipt == response["receipt"]


def test_truncated_change_manifest_is_not_promoted_to_full_preservation_evidence(case):
    _, _, response, assess = case
    response["receipt"]["changes"]["truncated"] = True
    verdict = assess()
    assert verdict.ok  # Only the bound KIR execution result contract.
    assert verdict.receipt["changes"]["truncated"] is True
    assert verdict.outcome.acceptance.value == "not_run"


@pytest.mark.parametrize("state", ["rejected_before_start", "context_changed_before_start", "cancelled_before_start"])
def test_only_consistent_bound_before_start_receipt_establishes_no_invocation(case, state):
    _, _, response, assess = case
    response["receipt"].update(state=state, started=False, may_retry=True, changes=None,
                               transaction_evidence="not_observed", result_json=None, error="before start")
    verdict = assess()
    assert not verdict.ok
    assert verdict.outcome.execution.value == "not_started"
    assert verdict.outcome.retry_safety.value == "safe"
    response["receipt"]["started"] = True
    assert_unknown(assess())


@pytest.mark.parametrize("changed,truncated", [(False, False), (True, False), (False, True)])
def test_inner_rollback_does_not_explain_native_changes_outside_its_scope(case, changed, truncated):
    _, _, response, assess = case
    response["receipt"]["result_json"] = '{"commit_status":"RolledBack"}'
    response["receipt"]["changes"].update(added=[700] if changed else [], truncated=truncated)
    response["receipt"]["transaction_evidence"] = "changes_observed" if changed else "changes_not_observed"
    verdict = assess()
    if changed or truncated:
        assert_unknown(verdict)
        assert verdict.diagnostic_code == "rollback_scope_unconfirmed"
    else:
        assert verdict.outcome.execution.value == "rolled_back"
        assert verdict.outcome.retry_safety.value == "safe"


@pytest.mark.parametrize("wire", [b"", b"\xff", b"null", b"{", b'{"ok":true,"ok":false}',
    b'{"number":NaN}', b'{"number":1e400}', b'{"text":"\\ud800"}'])
def test_malformed_outer_evidence_never_raises_or_becomes_success(case, wire):
    verdict = case[-1](wire=wire)
    assert_unknown(verdict)
    assert verdict.raw_response == wire


@pytest.mark.parametrize("inner", ['{"ok":false,"ok":true,"L":{"id":"700"}}',
    '{"ok":true,"L":{"id":"700"},"n":Infinity}', '{"ok":true,"L":{"id":"700"},"n":1e400}',
    '{"ok":true,"L":{"id":"700"},"s":"\\ud800"}', '{"ok":true', "[" * 70 + "0" + "]" * 70])
def test_inner_json_parser_is_strict_and_preserves_the_failed_native_receipt(case, inner):
    _, _, response, assess = case
    response["receipt"]["result_json"] = inner
    verdict = assess()
    assert_unknown(verdict)
    assert verdict.receipt == response["receipt"]
    assert verdict.binding_matches


def test_wire_budgets_apply_to_actual_bytes_without_retaining_oversized_outer(case, monkeypatch):
    _, _, response, assess = case
    wire = json.dumps(response).encode()
    monkeypatch.setattr(evidence, "MAX_FRAME_BYTES", len(wire) - 1)
    verdict = assess(wire=wire)
    assert_unknown(verdict)
    assert verdict.raw_response == b""
    monkeypatch.setattr(evidence, "MAX_FRAME_BYTES", len(wire))
    assert assess(wire=wire).ok
    monkeypatch.setattr(evidence, "MAX_RESULT_BYTES", 2)
    verdict = assess(wire=wire)
    assert_unknown(verdict)
    assert verdict.receipt == response["receipt"]


def test_a_foreign_document_change_is_a_named_terminal_refusal_not_a_blank_unknown(case):
    """The loudest thing the engine can say must reach the reader BY NAME.

    Before this fix, `foreign_document_changed` was not recognized at all:
    it was not counted as terminal, and in the decompile it received the
    generic code `native_state_unconfirmed`. The refusal stayed safe and
    nameless — that is, indistinguishable from "the bridge stayed silent".
    """
    _, _, response, assess = case
    receipt = response["receipt"]
    receipt.update(state="foreign_document_changed", started=True, may_retry=False,
                   result_json=None, result_truncated=False, result_error=None,
                   error="a document other than the bound document was changed during this operation")
    verdict = assess()
    assert_unknown(verdict)
    assert verdict.diagnostic_code == "foreign_document_changed"
    assert evidence.native_receipt_terminal_state(receipt) == "foreign_document_changed"

    # A retry is forbidden forever: the declared `may_retry` does not open
    # it back up.
    receipt["may_retry"] = True
    assert evidence.native_receipt_terminal_state(receipt) is None
    assert_unknown(assess())
    receipt["may_retry"] = False

    # A partial result must not arrive together with this refusal.
    receipt["result_json"] = json.dumps({"ok": True})
    assert evidence.native_receipt_terminal_state(receipt) is None
    receipt["result_json"] = None

    # An empty manifest for a linked document is a legitimate state: it
    # describes ITS OWN document, and a foreign edit could never have
    # appeared in it.
    receipt.update(changes={"added": [], "modified": [], "deleted": [],
                            "transaction_names": [], "truncated": False},
                   transaction_evidence="changes_not_observed")
    assert evidence.native_receipt_terminal_state(receipt) == "foreign_document_changed"
    assert assess().diagnostic_code == "foreign_document_changed"

    # A regression control: under the old state name the refusal becomes
    # nameless again, and the test turns red together with the fix.
    receipt["state"] = "invocation_completed_but_foreign"
    assert evidence.native_receipt_terminal_state(receipt) is None
    assert assess().diagnostic_code == "native_state_unconfirmed"
