"""Offline contracts for the versioned compiler target-profile manifest."""
from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from importlib import resources

import pytest

import kukai.compiler_contract as compiler_contract
from kukai.compiler_contract import (
    CompilerContractError,
    FROZEN_YEARS,
    HistoricalManifestUnavailableError,
    MANIFEST_ARCHIVE_RESOURCE,
    MANIFEST_PACKAGE,
    MANIFEST_RESOURCE,
    OFFICIAL_YEARS,
    ReleasePolicy,
    TargetFramework,
    archived_target_profile_manifest_digests,
    load_archived_target_profile_manifest,
    load_target_profile_manifest,
    missing_archived_target_profile_manifest_digests,
    parse_target_profile_manifest,
)


EXPECTED_MANIFEST_DIGEST = (
    "4fe7a0b9b39a96eaf2f81a111533866a649306cd5f9c1678f1d480c8e6ef838f"
)
EXPECTED_PROFILE_DIGESTS = {
    "2021": "d412860b588b22300d7a9e7c246fe49fb30e5c4a3b409abe128aba58d98146f9",
    "2022": "d779b7deecdcff859fefc612ea84d338b5ef1e5599449651ddb31bc8fda7c68a",
    "2023": "d0cd6d594bb97dfa3b2f4f7c65e3b2eaeb55c5614a9b96843080f6c78704e2d5",
    "2024": "4522f2fb7b8f3b6a72f51eb6eaa9ae27d886960e1ffd92771b371fab620ecbdf",
    "2025": "27e0df4f1a012629f66d5327e5dc7318adc59f2627e9a228662add7134f2caec",
    "2026": "e52891173b5efd458b00db73a59dea0fdfcac01a7289c76f080d4286a436ba3c",
}


def _raw_manifest() -> dict:
    payload = resources.files(MANIFEST_PACKAGE).joinpath(
        MANIFEST_RESOURCE).read_text(encoding="utf-8")
    return json.loads(payload)


def test_manifest_is_a_packaged_resource_with_pinned_digests() -> None:
    manifest = load_target_profile_manifest()
    assert resources.files(MANIFEST_PACKAGE).joinpath(
        MANIFEST_RESOURCE).is_file()
    assert manifest.manifest_digest == EXPECTED_MANIFEST_DIGEST
    assert {
        profile.revit_year: profile.profile_digest
        for profile in manifest.profiles
    } == EXPECTED_PROFILE_DIGESTS


def test_current_manifest_is_retained_in_the_packaged_historical_archive() -> None:
    current = load_target_profile_manifest()
    archived = load_archived_target_profile_manifest(current.manifest_digest)

    assert resources.files(MANIFEST_PACKAGE).joinpath(
        MANIFEST_ARCHIVE_RESOURCE).is_file()
    assert archived_target_profile_manifest_digests() == (
        EXPECTED_MANIFEST_DIGEST,
    )
    assert archived == current
    assert missing_archived_target_profile_manifest_digests(
        [current.manifest_digest]) == ()
    assert missing_archived_target_profile_manifest_digests(
        [current.manifest_digest, "f" * 64]) == ("f" * 64,)


def test_historical_archive_unknown_and_tampered_snapshot_fail_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        HistoricalManifestUnavailableError,
        match="HISTORICAL_MANIFEST_UNAVAILABLE",
    ):
        load_archived_target_profile_manifest("f" * 64)

    original_reader = compiler_contract._read_packaged_json

    def read_tampered_snapshot(resource_name: str):
        raw = original_reader(resource_name)
        if resource_name.endswith(".v1.json") and ".archive." in resource_name:
            raw = copy.deepcopy(raw)
            raw["compiler_policy"]["roslyn_package_version"] = "4.9.3"
        return raw

    monkeypatch.setattr(
        compiler_contract,
        "_read_packaged_json",
        read_tampered_snapshot,
    )
    with pytest.raises(
        HistoricalManifestUnavailableError,
        match="HISTORICAL_MANIFEST_UNAVAILABLE",
    ):
        load_archived_target_profile_manifest(EXPECTED_MANIFEST_DIGEST)
    with pytest.raises(
        HistoricalManifestUnavailableError,
        match="HISTORICAL_MANIFEST_UNAVAILABLE",
    ):
        missing_archived_target_profile_manifest_digests(
            [EXPECTED_MANIFEST_DIGEST])

    def read_corrupt_snapshot(resource_name: str):
        if resource_name.endswith(".v1.json") and ".archive." in resource_name:
            return {"schema_version": "target-profile-manifest/999"}
        return original_reader(resource_name)

    monkeypatch.setattr(
        compiler_contract,
        "_read_packaged_json",
        read_corrupt_snapshot,
    )
    with pytest.raises(
        HistoricalManifestUnavailableError,
        match="HISTORICAL_MANIFEST_UNAVAILABLE",
    ):
        load_archived_target_profile_manifest(EXPECTED_MANIFEST_DIGEST)


def test_release_policy_and_framework_split_are_exact() -> None:
    manifest = load_target_profile_manifest()
    assert manifest.compiler_policy.roslyn_package_version == "4.9.2"
    assert manifest.compiler_policy.language_version == "10.0"
    assert manifest.compiler_policy.allow_unsafe is False
    assert {
        profile.revit_year for profile in manifest.official_profiles
    } == OFFICIAL_YEARS
    assert {
        profile.revit_year for profile in manifest.frozen_profiles
    } == FROZEN_YEARS
    assert all(
        profile.release_policy is ReleasePolicy.FROZEN
        for profile in manifest.frozen_profiles
    )
    for profile in manifest.profiles:
        expected_tfm = (
            TargetFramework.NET8 if int(profile.revit_year) >= 2025
            else TargetFramework.NET48
        )
        assert profile.target_framework is expected_tfm
        assert (
            profile.revit_api_package_version
            == f"{profile.revit_year}.0.0"
        )
        assert (
            profile.revit_api_reference_path
            == f"lib/{profile.target_framework.value}"
        )
        assert manifest.profile_for_year(profile.revit_year) is profile


def test_loaded_contract_is_deeply_immutable() -> None:
    manifest = load_target_profile_manifest()
    profile = manifest.profile_for_year("2025")
    with pytest.raises(FrozenInstanceError):
        profile.profile_id = "unsafe"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        manifest.profiles = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        manifest.reference_policy.system_prefixes[0] = "unsafe"  # type: ignore[index]


def test_unknown_schema_and_unknown_fields_are_rejected() -> None:
    unknown_schema = _raw_manifest()
    unknown_schema["schema_version"] = "target-profile-manifest/999"
    with pytest.raises(CompilerContractError, match="unsupported"):
        parse_target_profile_manifest(unknown_schema)

    unknown_field = _raw_manifest()
    unknown_field["profiles"][0]["fallback_year"] = "2026"
    with pytest.raises(CompilerContractError, match="fields mismatch"):
        parse_target_profile_manifest(unknown_field)


def test_duplicate_profile_identity_is_rejected() -> None:
    raw = _raw_manifest()
    raw["profiles"][1] = copy.deepcopy(raw["profiles"][0])
    with pytest.raises(CompilerContractError, match="profile_id values"):
        parse_target_profile_manifest(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("release_policy", "frozen", "release policy"),
        ("target_framework", "net8.0", "must target net48"),
        ("revit_api_package_version", "2026.0.0", "must match"),
        ("revit_api_reference_path", "lib/net8.0", "does not match"),
    ],
)
def test_profile_drift_is_rejected(field: str, value: str,
                                   message: str) -> None:
    raw = _raw_manifest()
    raw["profiles"][2][field] = value
    with pytest.raises(CompilerContractError, match=message):
        parse_target_profile_manifest(raw)
