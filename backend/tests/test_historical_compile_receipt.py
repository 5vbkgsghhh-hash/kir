"""Archive-only historical receipt proof and M1/M2 upgrade gates."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any

import pytest

import kukai.compiler_contract as compiler_contract
import kukai.ir.compile_receipt as compile_receipt_module
from kukai.compiler_contract import (
    HistoricalManifestUnavailableError,
    load_archived_target_profile_manifest,
)
from kukai.ir.compile_receipt import (
    CompileReceipt,
    CompileReceiptError,
    HistoricalCompileReceiptEvidence,
    validate_compile_receipt_wire,
)
from kukai.operations.strict_receipt_v1 import (
    CanonicalOperationReceiptV1,
    CompileReceiptProofV1,
    DispatchAttemptV1,
    ExecutionIntentBindingV1,
    ExecutionIntentWireValidationV1,
    HistoricalCompileReceiptProofV1,
    HistoricalManifestUnavailable,
    PersistenceEnvelopeV1,
    PersistedExecutionIntentEvidenceV1,
    ReceiptClaimConflict,
    ReceiptIngress,
    StrictReceiptError,
    ValidatedReceiptClaimV1,
    bind_or_replay_persisted_receipt_claim,
    bind_or_replay_receipt_claim,
    canonical_sha256,
    validate_persisted_execution_intent_wire,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
POSITIVE_VECTOR = (
    REPOSITORY_ROOT
    / "tests"
    / "contracts"
    / "strict_receipt_v1"
    / "regular_committed_verified.json"
)
CURRENT_MANIFEST = (
    BACKEND_ROOT / "kukai" / "compiler_contracts" / "target_profiles.v1.json"
)


def _positive() -> dict[str, Any]:
    return json.loads(POSITIVE_VECTOR.read_text(encoding="utf-8"))


def _receipt_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rehash_receipt(receipt: dict[str, Any]) -> None:
    receipt["receipt_digest"] = _receipt_digest({
        key: value
        for key, value in receipt.items()
        if key != "receipt_digest"
    })


def _rehash_intent(intent: dict[str, Any]) -> None:
    intent["intent_digest"] = canonical_sha256({
        key: value
        for key, value in intent.items()
        if key != "intent_digest"
    })


def test_historical_receipt_is_distinct_evidence_and_preserves_wire_bytes() -> None:
    receipt = _positive()["intent"]["compile_receipt"]

    current = CompileReceipt.from_dict(receipt)
    historical = HistoricalCompileReceiptEvidence.from_dict(receipt)
    persisted = CompileReceiptProofV1.from_persisted_dict(receipt)

    assert historical.to_dict() == receipt
    assert historical.receipt_digest == current.receipt_digest
    assert isinstance(persisted, HistoricalCompileReceiptProofV1)
    assert persisted.to_dict() == receipt
    assert persisted.requires_current_re_admission is False
    assert not isinstance(historical, CompileReceipt)
    for forbidden_api in (
        "expected_for",
        "verified_compile_unit",
        "verified_wrapped_source",
    ):
        assert not hasattr(historical, forbidden_api)


def test_persisted_intent_is_not_current_admission_or_dispatch_capability() -> None:
    vector = _positive()
    wire = vector["intent"]
    persisted = ExecutionIntentBindingV1.from_persisted_dict(wire)
    dispatch_attempt = DispatchAttemptV1.from_dict(vector["dispatch_attempt"])

    assert isinstance(persisted, PersistedExecutionIntentEvidenceV1)
    assert not isinstance(persisted, ExecutionIntentBindingV1)
    assert persisted.to_dict() == wire
    assert persisted.requires_current_re_admission is False
    assert not hasattr(persisted, "prepare_dispatch")
    assert not hasattr(persisted, "dispatch_attempt")
    with pytest.raises(StrictReceiptError, match="CompileReceiptProofV1"):
        ExecutionIntentBindingV1(
            operation=persisted.operation,
            authority=persisted.authority,
            lineage=persisted.lineage,
            compile_receipt=persisted.compile_receipt,  # type: ignore[arg-type]
            dispatch=persisted.dispatch,
            intent_digest=persisted.intent_digest,
        )
    with pytest.raises(StrictReceiptError, match="typed intent"):
        dispatch_attempt.validate_against(persisted)  # type: ignore[arg-type]


def test_manifest_neutral_intent_validation_is_not_dispatch_authority() -> None:
    vector = _positive()
    validated = validate_persisted_execution_intent_wire(vector["intent"])
    dispatch_attempt = DispatchAttemptV1.from_dict(vector["dispatch_attempt"])

    assert isinstance(validated, ExecutionIntentWireValidationV1)
    assert validated.to_dict() == vector["intent"]
    assert not isinstance(validated, ExecutionIntentBindingV1)
    assert not isinstance(validated, PersistedExecutionIntentEvidenceV1)
    assert not hasattr(validated, "requires_current_re_admission")
    with pytest.raises(StrictReceiptError, match="typed intent"):
        dispatch_attempt.validate_against(validated)  # type: ignore[arg-type]


def test_all_intent_content_corruption_precedes_manifest_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        (
            "intent schema",
            ("schema",),
            "kir-execution-intent/999",
            "unsupported execution intent schema",
        ),
        (
            "intent field set",
            ("unexpected",),
            True,
            "fields mismatch",
        ),
        (
            "restricted JSON domain",
            ("dispatch", "timeout_ms"),
            1.5,
            "float",
        ),
        (
            "receipt root",
            ("compile_receipt", "receipt_digest"),
            "f" * 64,
            "receipt_digest",
        ),
        (
            "receipt mirror",
            ("compile_receipt_digest",),
            "f" * 64,
            "compile receipt digest",
        ),
        (
            "compile unit mirror",
            ("compile_unit", "source_bytes"),
            1,
            "compile_unit",
        ),
        (
            "target mirror",
            ("target", "manifest_digest"),
            "f" * 64,
            "intent target",
        ),
        (
            "dispatch link",
            ("dispatch", "plaintext_payload_hash"),
            "f" * 64,
            "dispatch plaintext payload hash",
        ),
        (
            "lineage link",
            ("lineage", "lower_digest"),
            "f" * 64,
            "lineage lower digest",
        ),
        (
            "authority link",
            ("authority", "regular", "plan_digest"),
            "f" * 64,
            "regular authority plan digest",
        ),
        (
            "intent root",
            ("intent_digest",),
            "f" * 64,
            "intent digest",
        ),
    )
    loader_calls: list[str] = []

    def must_not_load(name: str):
        def fail(*_args: Any, **_kwargs: Any) -> Any:
            loader_calls.append(name)
            raise AssertionError(f"{name} manifest loader was called")

        return fail

    monkeypatch.setattr(
        compile_receipt_module,
        "load_target_profile_manifest",
        must_not_load("current"),
    )
    monkeypatch.setattr(
        compile_receipt_module,
        "load_archived_target_profile_manifest",
        must_not_load("archive"),
    )

    for parser in (
        ExecutionIntentBindingV1.from_dict,
        ExecutionIntentBindingV1.from_persisted_dict,
    ):
        for name, path, replacement, expected in cases:
            wire = copy.deepcopy(_positive()["intent"])
            cursor: dict[str, Any] = wire
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = replacement
            with pytest.raises(
                StrictReceiptError,
                match=expected,
            ):
                parser(wire)

    assert loader_calls == []


def test_valid_unknown_selector_passes_neutral_gate_then_needs_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = copy.deepcopy(_positive()["intent"])
    receipt = wire["compile_receipt"]
    receipt["target"]["manifest_digest"] = "f" * 64
    _rehash_receipt(receipt)
    wire["compile_receipt_digest"] = receipt["receipt_digest"]
    wire["compile_unit"] = copy.deepcopy(receipt["compile_unit"])
    wire["target"] = copy.deepcopy(receipt["target"])
    _rehash_intent(wire)

    def must_not_load(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("manifest loader was called by neutral validation")

    with monkeypatch.context() as guarded:
        guarded.setattr(
            compile_receipt_module,
            "load_target_profile_manifest",
            must_not_load,
        )
        guarded.setattr(
            compile_receipt_module,
            "load_archived_target_profile_manifest",
            must_not_load,
        )
        receipt_validation = validate_compile_receipt_wire(receipt)
        intent_validation = validate_persisted_execution_intent_wire(wire)

    assert receipt_validation.target["manifest_digest"] == "f" * 64
    assert intent_validation.to_dict() == wire
    with pytest.raises(
        HistoricalManifestUnavailable,
        match="HISTORICAL_MANIFEST_UNAVAILABLE",
    ):
        ExecutionIntentBindingV1.from_persisted_dict(wire)


def test_recovery_binding_accepts_only_persisted_evidence_and_durable_attempt() -> None:
    vector = _positive()
    current = ExecutionIntentBindingV1.from_dict(vector["intent"])
    persisted = ExecutionIntentBindingV1.from_persisted_dict(vector["intent"])
    dispatch_attempt = DispatchAttemptV1.from_dict(vector["dispatch_attempt"])
    claim = ValidatedReceiptClaimV1.from_dict(vector["receipt_claim"])

    binding = bind_or_replay_persisted_receipt_claim(
        None,
        claim=claim,
        persisted_intent_evidence=persisted,
        durable_dispatch_attempt=dispatch_attempt,
        first_received_via=ReceiptIngress.LIVE,
        persistence=PersistenceEnvelopeV1("kukai-operation-store/1", "c" * 64),
    )
    binding.validate_against_persisted_evidence(
        persisted_intent_evidence=persisted,
        durable_dispatch_attempt=dispatch_attempt,
    )
    receipt_wire = claim.operation_receipt.to_dict()
    receipt_wire["result"]["created"] = 2
    changed_claim = replace(
        claim,
        operation_receipt=CanonicalOperationReceiptV1(receipt_wire),
        receipt_claim_digest="",
    )
    with pytest.raises(ReceiptClaimConflict, match="receipt_claim_digest"):
        bind_or_replay_persisted_receipt_claim(
            binding,
            claim=changed_claim,
            persisted_intent_evidence=persisted,
            durable_dispatch_attempt=dispatch_attempt,
            first_received_via=ReceiptIngress.DURABLE_OUTBOX,
        )

    with pytest.raises(StrictReceiptError, match="PersistedExecutionIntentEvidenceV1"):
        bind_or_replay_persisted_receipt_claim(
            None,
            claim=claim,
            persisted_intent_evidence=current,  # type: ignore[arg-type]
            durable_dispatch_attempt=dispatch_attempt,
            first_received_via=ReceiptIngress.LIVE,
            persistence=PersistenceEnvelopeV1("kukai-operation-store/1", "c" * 64),
        )
    with pytest.raises(StrictReceiptError, match="typed intent"):
        bind_or_replay_receipt_claim(
            None,
            claim=claim,
            intent=persisted,  # type: ignore[arg-type]
            dispatch_attempt=dispatch_attempt,
            first_received_via=ReceiptIngress.LIVE,
            persistence=PersistenceEnvelopeV1("kukai-operation-store/1", "c" * 64),
        )
    foreign_attempt = DispatchAttemptV1(
        intent_digest=persisted.intent_digest,
        attempt_id="00000000-0000-0000-0000-000000000001",
        req_id="recovery-foreign-attempt",
        encrypted_code_sha256="a" * 64,
        bridge_request_envelope_sha256="b" * 64,
    )
    with pytest.raises(StrictReceiptError, match="persisted intent attempt"):
        bind_or_replay_persisted_receipt_claim(
            None,
            claim=claim,
            persisted_intent_evidence=persisted,
            durable_dispatch_attempt=foreign_attempt,
            first_received_via=ReceiptIngress.LIVE,
            persistence=PersistenceEnvelopeV1("kukai-operation-store/1", "c" * 64),
        )


def test_historical_parser_refuses_rehashed_artifact_profile_manifest_and_root() -> None:
    base = _positive()["intent"]["compile_receipt"]

    artifact = copy.deepcopy(base)
    artifact["artifact"]["artifact_digest"] = "f" * 64
    _rehash_receipt(artifact)
    with pytest.raises(CompileReceiptError, match=r"artifact.*digest"):
        HistoricalCompileReceiptEvidence.from_dict(artifact)

    profile = copy.deepcopy(base)
    profile["target"]["profile_digest"] = "f" * 64
    _rehash_receipt(profile)
    with pytest.raises(CompileReceiptError, match="target profile digests disagree"):
        HistoricalCompileReceiptEvidence.from_dict(profile)

    manifest = copy.deepcopy(base)
    manifest["target"]["manifest_digest"] = "f" * 64
    _rehash_receipt(manifest)
    with pytest.raises(
        HistoricalManifestUnavailableError,
        match="HISTORICAL_MANIFEST_UNAVAILABLE",
    ):
        HistoricalCompileReceiptEvidence.from_dict(manifest)

    root = copy.deepcopy(base)
    root["receipt_digest"] = "f" * 64
    with pytest.raises(CompileReceiptError, match="receipt_digest"):
        HistoricalCompileReceiptEvidence.from_dict(root)


def test_persisted_adapter_maps_unknown_archive_to_strict_typed_refusal() -> None:
    receipt = copy.deepcopy(_positive()["intent"]["compile_receipt"])
    receipt["target"]["manifest_digest"] = "f" * 64
    _rehash_receipt(receipt)

    with pytest.raises(
        HistoricalManifestUnavailable,
        match="HISTORICAL_MANIFEST_UNAVAILABLE",
    ):
        CompileReceiptProofV1.from_persisted_dict(receipt)


def test_invalid_utf8_archive_maps_to_typed_core_and_strict_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _positive()["intent"]["compile_receipt"]
    original_files = compiler_contract.resources.files

    class InvalidUtf8ArchiveResource:
        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            raise UnicodeDecodeError(
                "utf-8",
                b"\xff",
                0,
                1,
                "invalid start byte",
            )

    class PackageResources:
        def joinpath(self, resource_name: str):
            if resource_name.endswith(".v1.json") and ".archive." in resource_name:
                return InvalidUtf8ArchiveResource()
            return original_files("kukai.compiler_contracts").joinpath(
                resource_name)

    compiler_contract.load_target_profile_manifest_archive.cache_clear()
    monkeypatch.setattr(
        compiler_contract.resources,
        "files",
        lambda _package_name: PackageResources(),
    )
    try:
        with pytest.raises(HistoricalManifestUnavailableError) as core_error:
            load_archived_target_profile_manifest(
                receipt["target"]["manifest_digest"])
        assert core_error.value.code == "HISTORICAL_MANIFEST_UNAVAILABLE"

        with pytest.raises(HistoricalManifestUnavailable) as strict_error:
            CompileReceiptProofV1.from_persisted_dict(receipt)
        assert strict_error.value.code == "HISTORICAL_MANIFEST_UNAVAILABLE"
    finally:
        # The index is cached, so never leave a test-local resource root behind.
        compiler_contract.load_target_profile_manifest_archive.cache_clear()


def test_historical_parser_never_accepts_a_caller_supplied_raw_manifest() -> None:
    receipt = copy.deepcopy(_positive()["intent"]["compile_receipt"])
    receipt["target"]["manifest"] = {"schema_version": "target-profile-manifest/1"}
    _rehash_receipt(receipt)

    with pytest.raises(CompileReceiptError, match="target fields mismatch"):
        HistoricalCompileReceiptEvidence.from_dict(receipt)


def _run_fresh_process(script: str, *arguments: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    inherited = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(BACKEND_ROOT), inherited) if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *(str(arg) for arg in arguments)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        "fresh-process contract gate failed\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    return completed


def test_m1_m2_fresh_process_upgrade_uses_only_the_packaged_archive(
    tmp_path: Path,
) -> None:
    m1_evidence = tmp_path / "m1-recovery-evidence.json"
    _run_fresh_process(
        """
        import json
        import sys
        from pathlib import Path
        from kukai.operations.strict_receipt_v1 import (
            DispatchAttemptV1,
            ExecutionIntentBindingV1,
            ValidatedReceiptClaimV1,
        )

        vector = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        current = ExecutionIntentBindingV1.from_dict(vector["intent"])
        assert current.to_dict() == vector["intent"]
        durable_attempt = DispatchAttemptV1.from_dict(vector["dispatch_attempt"])
        claim = ValidatedReceiptClaimV1.from_dict(vector["receipt_claim"])
        claim.validate_against(current, durable_attempt)
        Path(sys.argv[2]).write_text(
            json.dumps(
                {
                    "intent": current.to_dict(),
                    "dispatch_attempt": durable_attempt.to_dict(),
                    "receipt_claim": claim.to_dict(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print("M1 current intent/attempt/claim", current.intent_digest)
        """,
        POSITIVE_VECTOR,
        m1_evidence,
    )

    completed = _run_fresh_process(
        """
        import json
        import sys
        from dataclasses import replace
        from pathlib import Path
        from kukai import compiler_contract
        from kukai.ir import compile_receipt
        from kukai.operations.strict_receipt_v1 import (
            CanonicalOperationReceiptV1,
            DispatchAttemptV1,
            ExecutionIntentBindingV1,
            PersistenceEnvelopeV1,
            PersistedExecutionIntentEvidenceV1,
            ReceiptClaimConflict,
            ReceiptIngress,
            StrictReceiptError,
            ValidatedReceiptClaimV1,
            bind_or_replay_persisted_receipt_claim,
            canonical_sha256,
        )

        m2_raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        m2_raw["compiler_policy"]["roslyn_package_version"] = "4.9.3"
        m2 = compiler_contract.parse_target_profile_manifest(m2_raw)
        assert m2.manifest_digest != "4fe7a0b9b39a96eaf2f81a111533866a649306cd5f9c1678f1d480c8e6ef838f"
        compiler_contract.load_target_profile_manifest = lambda: m2
        compile_receipt.load_target_profile_manifest = lambda: m2

        m1_evidence = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        m1_wire = m1_evidence["intent"]
        durable_attempt = DispatchAttemptV1.from_dict(m1_evidence["dispatch_attempt"])
        claim = ValidatedReceiptClaimV1.from_dict(m1_evidence["receipt_claim"])
        m2_wire = json.loads(json.dumps(m1_wire))
        m2_profile = m2.profile_for_year(m2_wire["target"]["revit_year"])
        m2_receipt = m2_wire["compile_receipt"]
        m2_receipt["target"]["profile_digest"] = m2_profile.profile_digest
        m2_receipt["target"]["manifest_digest"] = m2.manifest_digest
        m2_receipt["artifact"]["target_profile_digest"] = m2_profile.profile_digest
        m2_receipt["artifact"]["artifact_digest"] = canonical_sha256({
            key: value
            for key, value in m2_receipt["artifact"].items()
            if key != "artifact_digest"
        })
        m2_receipt["receipt_digest"] = canonical_sha256({
            key: value
            for key, value in m2_receipt.items()
            if key != "receipt_digest"
        })
        m2_wire["compile_receipt_digest"] = m2_receipt["receipt_digest"]
        m2_wire["compile_unit"] = m2_receipt["compile_unit"]
        m2_wire["target"] = m2_receipt["target"]
        m2_wire["lineage"]["artifact_digest"] = m2_receipt["artifact"]["artifact_digest"]
        m2_wire["lineage"]["target_profile_digest"] = m2_profile.profile_digest
        m2_wire["intent_digest"] = canonical_sha256({
            key: value
            for key, value in m2_wire.items()
            if key != "intent_digest"
        })
        assert ExecutionIntentBindingV1.from_dict(m2_wire).to_dict() == m2_wire

        try:
            ExecutionIntentBindingV1.from_dict(m1_wire)
        except StrictReceiptError:
            pass
        else:
            raise AssertionError("M1 receipt was incorrectly admitted under current M2")

        historical = ExecutionIntentBindingV1.from_persisted_dict(m1_wire)
        assert isinstance(historical, PersistedExecutionIntentEvidenceV1)
        assert historical.to_dict() == m1_wire
        assert historical.requires_current_re_admission is True
        assert not isinstance(historical, ExecutionIntentBindingV1)
        assert not hasattr(historical, "prepare_dispatch")
        first_binding = bind_or_replay_persisted_receipt_claim(
            None,
            claim=claim,
            persisted_intent_evidence=historical,
            durable_dispatch_attempt=durable_attempt,
            first_received_via=ReceiptIngress.LIVE,
            persistence=PersistenceEnvelopeV1("kukai-operation-store/1", "c" * 64),
        )
        assert first_binding.first_received_via is ReceiptIngress.LIVE
        assert first_binding.intent_digest == historical.intent_digest
        assert first_binding.dispatch_attempt_digest == durable_attempt.dispatch_attempt_digest
        replay = bind_or_replay_persisted_receipt_claim(
            first_binding,
            claim=claim,
            persisted_intent_evidence=historical,
            durable_dispatch_attempt=durable_attempt,
            first_received_via=ReceiptIngress.DURABLE_OUTBOX,
        )
        assert replay is first_binding
        assert replay.first_received_via is ReceiptIngress.LIVE
        receipt_wire = claim.operation_receipt.to_dict()
        receipt_wire["result"]["created"] = 2
        changed_claim = replace(
            claim,
            operation_receipt=CanonicalOperationReceiptV1(receipt_wire),
            receipt_claim_digest="",
        )
        try:
            bind_or_replay_persisted_receipt_claim(
                first_binding,
                claim=changed_claim,
                persisted_intent_evidence=historical,
                durable_dispatch_attempt=durable_attempt,
                first_received_via=ReceiptIngress.DURABLE_OUTBOX,
            )
        except ReceiptClaimConflict:
            pass
        else:
            raise AssertionError("changed recovery claim was not a contradiction")
        try:
            durable_attempt.validate_against(historical)
        except StrictReceiptError:
            pass
        else:
            raise AssertionError("historical evidence became a dispatch capability")
        print("M2 current refusal; M1 recovery binding", historical.intent_digest)
        """,
        CURRENT_MANIFEST,
        m1_evidence,
    )

    assert "M2 current refusal; M1 recovery binding" in completed.stdout
