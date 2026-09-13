"""Source-binding commitment tests, not a future staged lowering validator."""
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from kir import revit_connector as owner
from kir.contracts import ElementIdentityProof
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError, _capture, _canonical, _hash
from kir.tests.test_revit_connector_preparation import target, OPERATION, credentials


PROGRAM = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "Уровень 🏗"}]}


def prepared(**kwargs):
    return owner.prepare_execution(PROGRAM, target=target(),
        precondition=owner.ContextPrecondition("native-doc", 7, 42, "d" * 64), operation_id=OPERATION, **kwargs)


@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_same_runtime_projection_commits_different_logical_cores_and_keeps_guard_source(isolation):
    guard = ElementIdentityProof(800, "original-type-uid", "a" * 32)
    plain = prepared(expected_identities=(guard,), isolation=isolation)
    digests = [_hash({"logical_import": logical, "projected_id": 800}) for logical in ("T-A", "T-B")]
    imports = [prepared(association_digest=digest, expected_identities=(guard,), isolation=isolation) for digest in digests]
    assert imports[0].planned.to_evidence_dict() == imports[1].planned.to_evidence_dict() == plain.planned.to_evidence_dict()
    assert len({item.source_sha256 for item in [plain, *imports]}) == 3
    for item in imports:
        assert item.source.split("\n", 1)[1] == plain.source
        assert item.expected_identities == (guard,)
        assert item.source_sha256 == sha256(item.source.encode()).hexdigest()
        assert item.precondition is not None and item.precondition == plain.precondition
        request = item.execute_request(credentials(), request_id=str(uuid4()))
        assert request["source"] == item.source and "association_digest" not in request


def test_exact_utf16_header_budget_boundary_and_legacy_archive_bytes(monkeypatch):
    plain = prepared()
    assert _capture(plain) == _capture(prepared(association_digest=None))
    assert "association_digest" not in json.loads(_capture(plain))
    header = owner.EXECUTION_ASSOCIATION_PREFIX + "a" * 64 + "\n"
    total = len((header + plain.source).encode("utf-16-le")) // 2
    monkeypatch.setattr(owner, "MAX_SOURCE_CHARS", total)
    assert prepared(association_digest="a" * 64).source == header + plain.source
    monkeypatch.setattr(owner, "MAX_SOURCE_CHARS", total - 1)
    with pytest.raises(owner.ConnectorPreparationError, match="source_budget_exceeded"):
        prepared(association_digest="a" * 64)
    assert prepared().source == plain.source


@pytest.mark.parametrize("prefix", ["\ufeff", " ", "\n", "using System;\n"])
def test_reader_does_not_upgrade_misplaced_header_to_fresh_binding(prefix):
    source = prefix + owner.EXECUTION_ASSOCIATION_PREFIX + "a" * 64 + "\nbody"
    assert owner.source_association_digest(source) is None


@pytest.mark.parametrize("ending", ["\r\n", " \n", "\t\n", "\x00\n", "/\n"])
def test_header_token_requires_exact_ascii_digest_then_newline(ending):
    with pytest.raises(owner.ConnectorPreparationError, match="invalid_association_digest"):
        owner.source_association_digest(owner.EXECUTION_ASSOCIATION_PREFIX + "a" * 64 + ending + "body")


def test_rehashed_header_is_new_inert_claim_not_matching_original_fresh_artifact():
    original = prepared(association_digest="a" * 64)
    data = json.loads(_capture(original))
    data["source"] = data["source"].replace("sha256:" + "a" * 64, "sha256:" + "b" * 64, 1)
    data["binding"]["source_sha256"] = sha256(data["source"].encode()).hexdigest()
    data["record_digest"] = _hash({k: v for k, v in data.items() if k != "record_digest"})
    loaded = SavedExecutionRecord._from_bytes(_canonical(data).encode())
    assert owner.source_association_digest(loaded.to_dict()["source"]) == "b" * 64
    assert not hasattr(loaded, "execute_request")
    with pytest.raises(SavedExecutionError, match="saved_execution_mismatch"):
        loaded.require_matches(original)
    # Structural hashes do not authenticate the author of altered claims.
    assert owner.source_association_digest(owner.EXECUTION_ASSOCIATION_PREFIX + "b" * 64 + "\nnot C#") == "b" * 64
