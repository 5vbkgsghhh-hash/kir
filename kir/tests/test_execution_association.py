"""Explicit source commitment, not a proof that a staged import was qualified."""
import hashlib
from uuid import uuid4

import pytest

from kir import revit_connector as owner
from kir.contracts import ElementIdentityProof
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError
from kir.tests.test_revit_connector_preparation import PROGRAM, target, OPERATION, credentials
from kir.tests.test_type_creation_conformance import type_conformance_runner, VERSIONS


def prepare(**kwargs):
    return owner.prepare_execution(PROGRAM, target=target(),
        precondition=owner.ContextPrecondition("doc", 7), operation_id=OPERATION, **kwargs)


def test_omitted_and_none_preserve_existing_source_and_archive_bytes(tmp_path):
    ordinary, explicit = prepare(), prepare(association_digest=None)
    assert ordinary.source == explicit.source
    assert ordinary.source_sha256 == explicit.source_sha256 and ordinary.association_digest is None
    assert owner.source_association_digest(ordinary.source) is None
    first = SavedExecutionRecord.create_new(tmp_path / "first.json", ordinary)
    second = SavedExecutionRecord.create_new(tmp_path / "second.json", explicit)
    assert first._raw == second._raw


def test_distinct_associations_change_native_binding_without_changing_runtime_plan(tmp_path):
    plain, a, b = prepare(), prepare(association_digest="a" * 64), prepare(association_digest="b" * 64)
    assert a.planned.plan_digest == b.planned.plan_digest == plain.planned.plan_digest
    assert a.source == owner.EXECUTION_ASSOCIATION_PREFIX + "a" * 64 + "\n" + plain.source
    assert b.source == owner.EXECUTION_ASSOCIATION_PREFIX + "b" * 64 + "\n" + plain.source
    assert len({item.source_sha256 for item in (plain, a, b)}) == 3
    for item in (a, b):
        assert item.source_sha256 == hashlib.sha256(item.source.encode()).hexdigest()
        assert owner.source_association_digest(item.source) == item.association_digest
        request = item.execute_request(credentials(), request_id=str(uuid4()))
        assert request["source_sha256"] == item.source_sha256 and request["source"] == item.source
        assert "association_digest" not in request  # No independent, unsigned wire field.
    record = SavedExecutionRecord.create_new(tmp_path / "bound.json", a)
    loaded = SavedExecutionRecord.load(tmp_path / "bound.json")
    assert loaded._raw == record._raw and owner.source_association_digest(loaded.to_dict()["source"]) == "a" * 64
    loaded.require_matches(a)
    with pytest.raises(SavedExecutionError, match="saved_execution_mismatch"):
        loaded.require_matches(b)


@pytest.mark.parametrize("value", ["", "a" * 63, "A" * 64, "g" * 64, "a" * 64 + "\n", 1, True, [], b"a" * 64])
def test_invalid_association_refuses_before_compilation(monkeypatch, value):
    monkeypatch.setattr(owner, "compile_program", lambda *_a, **_kw: pytest.fail("invalid digest reached compiler"))
    with pytest.raises(owner.ConnectorPreparationError, match="invalid_association_digest"):
        prepare(association_digest=value)


def test_full_source_budget_counts_association_header(monkeypatch):
    plain = prepare()
    monkeypatch.setattr(owner, "MAX_SOURCE_CHARS", len(plain.source.encode("utf-16-le")) // 2)
    assert prepare().source == plain.source
    with pytest.raises(owner.ConnectorPreparationError, match="source_budget_exceeded"):
        prepare(association_digest="a" * 64)


@pytest.mark.parametrize("tail", ["a" * 64, "a" * 63 + "\n", "A" * 64 + "\n", "a" * 64 + " \n"])
def test_reader_refuses_malformed_reserved_header(tail):
    with pytest.raises(owner.ConnectorPreparationError, match="invalid_association_digest"):
        owner.source_association_digest(owner.EXECUTION_ASSOCIATION_PREFIX + tail)


def test_reader_does_not_search_or_normalize_an_arbitrary_body():
    header = owner.EXECUTION_ASSOCIATION_PREFIX + "a" * 64 + "\n"
    assert owner.source_association_digest(" " + header) is None
    assert owner.source_association_digest("using System;\n" + header) is None
    # A commitment is not semantic authority: even this non-C# tail can carry
    # a readable prefix. Only the actual preparer/binder may confer its contract.
    assert owner.source_association_digest(header + "not executable source") == "a" * 64


def test_identity_guards_and_isolation_are_preserved_with_commitment():
    proof = ElementIdentityProof(700, "actual-uid", "a" * 32)
    plain = prepare(expected_identities=[proof], isolation="per_op")
    bound = prepare(expected_identities=[proof], isolation="per_op", association_digest="b" * 64)
    assert bound.source.endswith(plain.source) and "new SubTransaction(doc)" in bound.source
    assert bound.expected_identities == (proof,)


@pytest.mark.parametrize("version", VERSIONS)
def test_association_header_passes_real_policy_and_api_references(version, type_conformance_runner):
    sources = [owner.prepare_execution(PROGRAM, target=target(version),
        precondition=owner.ContextPrecondition("doc", 7), operation_id=OPERATION,
        isolation=mode, association_digest="a" * 64,
        expected_identities=[ElementIdentityProof(700, "guarded-native-uid", "b" * 32)]).source
        for mode in ("atomic", "per_op")]
    sources.append(owner.EXECUTION_ASSOCIATION_PREFIX + "a" * 64 + "\n"
                   + owner.wrap_connector_source("return doc.GetType();"))
    atomic, per_op, forbidden = type_conformance_runner(version, sources)
    assert atomic["ok"] and atomic["assembly_bytes"] > 0
    assert per_op["ok"] and per_op["assembly_bytes"] > 0
    assert not forbidden["ok"] and forbidden["assembly_bytes"] == 0
    assert any("runtime type discovery is not allowed" in message for message in forbidden["diagnostics"])
