"""Python artifact -> actual C# framing/service/durable replay -> bound D1.

Result evidence is explicitly seeded, not produced by a Revit invocation.
"""
from copy import deepcopy
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import struct
import subprocess
from uuid import uuid4

import pytest

from kir.connector_result import assess_connector_context_response, assess_connector_write_response
from kir.revit_connector import ConnectorPreparationError, ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution
from kir.revit_discovery import load_discovery, scan_discovery


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "connector/revit/tests/ProtocolReplay.Tests"


@pytest.fixture(scope="module")
def native_replay():
    if shutil.which("dotnet") is None:
        pytest.skip(".NET SDK absent; actual protocol/service replay not exercised")
    built = subprocess.run(["dotnet", "build", str(RUNNER / "ProtocolReplay.Tests.csproj"),
        "--configuration", "Release", "--nologo", "-p:NuGetAudit=false"],
        text=True, capture_output=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr

    def replay(seed, credentials, requests, *, started_only=False, result=None, with_discovery=False,
               context_scenario=None):
        fixture = {"seed": seed, "service_target": credentials.target.to_dict(),
                   "session_id": credentials.session_id, "token": credentials.token,
                   "requests": requests, "started_only": started_only,
                   "result_json": json.dumps({"ok": True, "L": {"id": "700"}} if result is None else result)}
        if context_scenario is not None:
            fixture["context_scenario"] = context_scenario
        ran = subprocess.run(["dotnet", str(RUNNER / "bin/Release/net8.0/ProtocolReplay.Tests.dll")],
            input=json.dumps(fixture), text=True, capture_output=True, timeout=30)
        assert ran.returncode == 0, ran.stderr
        data = json.loads(ran.stdout)
        assert data["scope"] == "seeded_receipt_replay_not_invocation"
        assert len(data["frames"]) == len(requests)
        responses = []
        for encoded in data["frames"]:
            frame = base64.b64decode(encoded, validate=True)
            assert len(frame) >= 4
            length = struct.unpack_from("<I", frame)[0]
            assert 0 < length == len(frame) - 4 <= 16 * 1024 * 1024
            responses.append(frame[4:])
        if with_discovery:
            return responses, base64.b64decode(data["discovery_utf8_base64"], validate=True)
        return responses
    return replay


@pytest.fixture
def prepared():
    target = RuntimeTarget(str(uuid4()), str(uuid4()), "2023")
    auth = SessionCredentials(target, str(uuid4()), "fixture-token")
    artifact = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
        target=target, precondition=ContextPrecondition("original-native-doc", 19, 31, "f" * 64),
        operation_id=str(uuid4()))
    return artifact, auth


def test_actual_service_replays_the_original_result_without_an_active_document(prepared, native_replay):
    artifact, auth = prepared
    seed = artifact.execute_request(auth, request_id=str(uuid4()))
    requests = [artifact.execute_request(auth, request_id=str(uuid4())),
                artifact.receipt_request(auth, request_id=str(uuid4()))]
    for request, response in zip(requests, native_replay(seed, auth, requests), strict=True):
        verdict = assess_connector_write_response(artifact, response, credentials=auth, request_id=request["request_id"])
        assert verdict.ok, (verdict.diagnostic_code, response)
        assert verdict.outcome.acceptance.value == "not_run"
        assert verdict.receipt["target"] == artifact.target.to_dict()
        assert verdict.receipt["precondition"] == artifact.precondition.to_dict()


def test_actual_historical_recovery_responds_on_new_route_with_original_binding(prepared, native_replay):
    artifact, auth = prepared
    new_auth = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "new-token")
    request = artifact.recovery_request(new_auth, request_id=str(uuid4()))
    response, = native_replay(artifact.execute_request(auth, request_id=str(uuid4())), new_auth, [request])
    decoded = json.loads(response)
    assert decoded["target"] == new_auth.target.to_dict()
    assert decoded["receipt"]["target"] == auth.target.to_dict()
    verdict = assess_connector_write_response(artifact, response, credentials=new_auth,
        request_id=request["request_id"], recovery=True)
    assert verdict.ok, (verdict.diagnostic_code, decoded)


@pytest.mark.parametrize("case", ["missing", "started_only", "wrong_precondition", "wrong_session", "wrong_target"])
def test_actual_native_refusals_never_become_write_success(prepared, native_replay, case):
    artifact, auth = prepared
    seed = artifact.execute_request(auth, request_id=str(uuid4()))
    request = artifact.execute_request(auth, request_id=str(uuid4()))
    expected = {"missing": "not_found", "started_only": "running_unknown", "wrong_precondition": "operation_conflict",
                "wrong_session": "session_mismatch", "wrong_target": "target_mismatch"}[case]
    if case == "missing":
        request = artifact.receipt_request(auth, request_id=request["request_id"])
        request["operation_id"] = str(uuid4())
    elif case == "wrong_precondition":
        request["precondition"]["revision"] += 1
    elif case == "wrong_session":
        request["session_id"] = str(uuid4())
    elif case == "wrong_target":
        request["target"]["instance_id"] = str(uuid4())
    response, = native_replay(seed, auth, [request], started_only=case == "started_only")
    assert json.loads(response)["status"] == expected
    verdict = assess_connector_write_response(artifact, response, credentials=auth, request_id=request["request_id"])
    assert not verdict.ok
    assert verdict.outcome.execution.value == "unconfirmed"
    assert verdict.outcome.retry_safety.value == "verify_first"


def test_actual_serializer_does_not_make_an_incomplete_inner_result_complete(prepared, native_replay):
    artifact, auth = prepared
    request = artifact.receipt_request(auth, request_id=str(uuid4()))
    response, = native_replay(artifact.execute_request(auth, request_id=str(uuid4())), auth, [request], result={"ok": True})
    verdict = assess_connector_write_response(artifact, response, credentials=auth, request_id=request["request_id"])
    assert not verdict.ok
    assert verdict.outcome.execution.value == "committed"
    assert verdict.outcome.witness.value == "incomplete"
    assert verdict.outcome.retry_safety.value == "forbidden"


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_actual_dotnet_discovery_dto_serialization_reaches_explicit_python_selection(prepared, native_replay, tmp_path, year):
    artifact, seed_auth = prepared
    auth = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), year), str(uuid4()), "Ключ-😀-fixture")
    responses, discovery_bytes = native_replay(artifact.execute_request(seed_auth, request_id=str(uuid4())),
        auth, [], with_discovery=True)
    assert responses == []
    parsed = load_discovery(discovery_bytes)
    assert parsed.credentials == auth
    directory = tmp_path / auth.target.instance_id
    directory.mkdir()
    (directory / (auth.session_id + ".json")).write_bytes(discovery_bytes)
    catalog = scan_discovery(tmp_path)
    selected = catalog.select(target=auth.target, session_id=auth.session_id, now=datetime.now(timezone.utc))
    assert selected.credentials == auth
    assert selected.summary(now=datetime.now(timezone.utc))["authority"] == "unverified_advertisement"
    assert auth.token not in repr(selected)


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_actual_collector_service_context_bytes_reach_preparation_without_title_identity(prepared, native_replay, year):
    artifact, seed_auth = prepared
    auth = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), year), str(uuid4()), "context-fixture-token")
    request = auth.context_request(request_id=str(uuid4()))
    responses, discovery = native_replay(artifact.execute_request(seed_auth, request_id=str(uuid4())), auth,
        [request], context_scenario="document", with_discovery=True)
    selected = load_discovery(discovery)
    result = assess_connector_context_response(responses[0], credentials=selected.credentials, request_id=request["request_id"])
    assert result.read_complete, (result.diagnostic_code, responses)
    assert result.snapshot["document_title"] == "Башня 😀"
    assert result.snapshot["selection_count"] == 2
    precondition = result.require_precondition(bind_view=True, bind_selection=True)
    assert precondition.document_key != result.snapshot["document_title"]
    assert len(precondition.document_key) == 48  # Actual current tracker epoch+counter, not parser's authority.
    assert precondition.revision == 2 and precondition.active_view_id == 31
    assert precondition.selection_digest == hashlib.sha256(b"17,42").hexdigest()
    new = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
        target=result.target, precondition=precondition, operation_id=str(uuid4()))
    assert new.execute_request(auth, request_id=str(uuid4()))["precondition"] == precondition.to_dict()
    # Context and its compiled request are never sent for execution by this fixture.


def test_actual_no_document_context_cannot_become_a_precondition(prepared, native_replay):
    artifact, auth = prepared
    request = auth.context_request(request_id=str(uuid4()))
    response, = native_replay(artifact.execute_request(auth, request_id=str(uuid4())), auth,
        [request], context_scenario="none")
    result = assess_connector_context_response(response, credentials=auth, request_id=request["request_id"])
    assert result.read_complete and result.diagnostic_code == "no_document"
    with pytest.raises(ConnectorPreparationError, match="context_unavailable"):
        result.require_precondition(bind_view=True, bind_selection=True)


@pytest.mark.parametrize("scenario,flag", [("family", "is_family_document"),
    ("read_only", "is_read_only"), ("modifiable", "is_modifiable")])
def test_actual_document_flags_remain_observations(prepared, native_replay, scenario, flag):
    artifact, auth = prepared
    request = auth.context_request(request_id=str(uuid4()))
    response, = native_replay(artifact.execute_request(auth, request_id=str(uuid4())), auth,
        [request], context_scenario=scenario)
    result = assess_connector_context_response(response, credentials=auth, request_id=request["request_id"])
    assert result.read_complete and result.snapshot[flag] is True


def test_actual_context_request_with_wrong_session_is_not_a_capture(prepared, native_replay):
    artifact, auth = prepared
    request = auth.context_request(request_id=str(uuid4()))
    request["session_id"] = str(uuid4())
    response, = native_replay(artifact.execute_request(auth, request_id=str(uuid4())), auth,
        [request], context_scenario="document")
    assert json.loads(response)["status"] == "session_mismatch"
    result = assess_connector_context_response(response, credentials=auth, request_id=request["request_id"])
    assert not result.read_complete
    with pytest.raises(ConnectorPreparationError, match="context_unavailable"):
        result.require_precondition(bind_view=True, bind_selection=True)
