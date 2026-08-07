"""Immutable target-profile contract shared by compiler rollout stages.

The first rollout is intentionally shadow-only: this module validates and
digests the packaged manifest but does not alter compile requests, readiness,
bridge handshake, or execution.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from importlib import resources
from typing import Any


MANIFEST_PACKAGE = "kukai.compiler_contracts"
MANIFEST_RESOURCE = "target_profiles.v1.json"
MANIFEST_SCHEMA = "target-profile-manifest/1"
PROFILE_SCHEMA = "target-profile/1"
MANIFEST_ARCHIVE_RESOURCE = "target_profile_manifest_archives.v1.json"
MANIFEST_ARCHIVE_SCHEMA = "target-profile-manifest-archive/1"
HISTORICAL_MANIFEST_UNAVAILABLE = "HISTORICAL_MANIFEST_UNAVAILABLE"
_ARCHIVE_RESOURCE_RE = re.compile(
    r"target_profiles\.archive\.([0-9a-f]{64})\.v1\.json\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
OFFICIAL_YEARS = frozenset({"2023", "2024", "2025", "2026"})
FROZEN_YEARS = frozenset({"2021", "2022"})


class CompilerContractError(ValueError):
    """The packaged compiler contract is malformed or internally inconsistent."""


class HistoricalManifestUnavailableError(CompilerContractError):
    """A requested archived manifest cannot be used as historical evidence."""

    code = HISTORICAL_MANIFEST_UNAVAILABLE

    def __init__(self, manifest_digest: object, detail: str) -> None:
        self.manifest_digest = manifest_digest
        super().__init__(f"{self.code}: {detail}")


class ReleasePolicy(str, Enum):
    OFFICIAL = "official"
    FROZEN = "frozen"


class TargetFramework(str, Enum):
    NET48 = "net48"
    NET8 = "net8.0"


@dataclass(frozen=True, slots=True)
class CompilerPolicy:
    roslyn_package_version: str
    language_version: str
    optimization: str
    platform: str
    allow_unsafe: bool
    nullable: str


@dataclass(frozen=True, slots=True)
class ReferencePolicy:
    system_prefixes: tuple[str, ...]
    system_exact_names: tuple[str, ...]
    revit_assemblies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetProfile:
    profile_id: str
    revit_year: str
    release_policy: ReleasePolicy
    target_framework: TargetFramework
    revit_api_package_version: str
    revit_api_reference_path: str
    profile_digest: str


@dataclass(frozen=True, slots=True)
class TargetProfileManifest:
    schema_version: str
    compiler_policy: CompilerPolicy
    reference_policy: ReferencePolicy
    profiles: tuple[TargetProfile, ...]
    manifest_digest: str

    def profile_for_year(self, revit_year: str) -> TargetProfile:
        matches = tuple(
            profile for profile in self.profiles
            if profile.revit_year == revit_year
        )
        if len(matches) != 1:
            raise CompilerContractError(
                f"target profile for Revit {revit_year!r} is unavailable")
        return matches[0]

    @property
    def official_profiles(self) -> tuple[TargetProfile, ...]:
        return tuple(
            profile for profile in self.profiles
            if profile.release_policy is ReleasePolicy.OFFICIAL
        )

    @property
    def frozen_profiles(self) -> tuple[TargetProfile, ...]:
        return tuple(
            profile for profile in self.profiles
            if profile.release_policy is ReleasePolicy.FROZEN
        )


@dataclass(frozen=True, slots=True)
class ArchivedTargetProfileManifest:
    """One immutable package resource registered for historical receipt proof."""

    manifest_digest: str
    resource_name: str


@dataclass(frozen=True, slots=True)
class TargetProfileManifestArchive:
    """Validated index of immutable, packaged historical manifest snapshots."""

    schema_version: str
    entries: tuple[ArchivedTargetProfileManifest, ...]

    def entry_for_digest(
        self,
        manifest_digest: str,
    ) -> ArchivedTargetProfileManifest | None:
        return next(
            (
                entry for entry in self.entries
                if entry.manifest_digest == manifest_digest
            ),
            None,
        )

    @property
    def manifest_digests(self) -> tuple[str, ...]:
        return tuple(entry.manifest_digest for entry in self.entries)


def canonical_digest(value: Any) -> str:
    """SHA-256 over deterministic UTF-8 JSON."""
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompilerContractError(
            f"compiler contract is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def _object(value: Any, *, path: str,
            fields: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompilerContractError(f"{path} must be an object")
    keys = frozenset(value)
    missing = sorted(fields - keys)
    extra = sorted(keys - fields)
    if missing or extra:
        raise CompilerContractError(
            f"{path} fields mismatch: missing={missing}, extra={extra}")
    return value


def _string(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompilerContractError(f"{path} must be a non-empty string")
    return value


def _sha256(value: Any, *, path: str) -> str:
    result = _string(value, path=path)
    if _SHA256_RE.fullmatch(result) is None:
        raise CompilerContractError(f"{path} must be lowercase SHA-256")
    return result


def _string_tuple(value: Any, *, path: str) -> tuple[str, ...]:
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes, bytearray))):
        raise CompilerContractError(f"{path} must be an array of strings")
    result = tuple(
        _string(item, path=f"{path}[{index}]")
        for index, item in enumerate(value)
    )
    if not result:
        raise CompilerContractError(f"{path} must not be empty")
    if len(result) != len(set(result)):
        raise CompilerContractError(f"{path} contains duplicates")
    return result


def _parse_compiler_policy(raw: Any) -> CompilerPolicy:
    fields = frozenset({
        "roslyn_package_version",
        "language_version",
        "optimization",
        "platform",
        "allow_unsafe",
        "nullable",
    })
    obj = _object(raw, path="compiler_policy", fields=fields)
    roslyn = _string(
        obj["roslyn_package_version"],
        path="compiler_policy.roslyn_package_version",
    )
    if re.fullmatch(r"[1-9]\d*\.\d+\.\d+", roslyn) is None:
        raise CompilerContractError(
            "compiler_policy.roslyn_package_version must be SemVer-like")
    language = _string(
        obj["language_version"], path="compiler_policy.language_version")
    optimization = _string(
        obj["optimization"], path="compiler_policy.optimization")
    platform = _string(obj["platform"], path="compiler_policy.platform")
    nullable = _string(obj["nullable"], path="compiler_policy.nullable")
    allow_unsafe = obj["allow_unsafe"]
    if not isinstance(allow_unsafe, bool):
        raise CompilerContractError(
            "compiler_policy.allow_unsafe must be boolean")
    if (
        language != "10.0"
        or optimization != "release"
        or platform != "AnyCPU"
        or allow_unsafe
        or nullable != "disabled"
    ):
        raise CompilerContractError(
            "compiler policy must be C# 10, Release, AnyCPU, "
            "unsafe disabled, nullable disabled")
    return CompilerPolicy(
        roslyn_package_version=roslyn,
        language_version=language,
        optimization=optimization,
        platform=platform,
        allow_unsafe=allow_unsafe,
        nullable=nullable,
    )


def _parse_reference_policy(raw: Any) -> ReferencePolicy:
    fields = frozenset({
        "system_prefixes",
        "system_exact_names",
        "revit_assemblies",
    })
    obj = _object(raw, path="reference_policy", fields=fields)
    prefixes = _string_tuple(
        obj["system_prefixes"], path="reference_policy.system_prefixes")
    exact = _string_tuple(
        obj["system_exact_names"],
        path="reference_policy.system_exact_names",
    )
    revit = _string_tuple(
        obj["revit_assemblies"],
        path="reference_policy.revit_assemblies",
    )
    if revit != ("RevitAPI", "RevitAPIUI"):
        raise CompilerContractError(
            "reference_policy.revit_assemblies must be exactly "
            "RevitAPI and RevitAPIUI")
    overlap = set(prefixes) & set(exact)
    if overlap:
        raise CompilerContractError(
            f"system prefix/exact policies overlap: {sorted(overlap)}")
    return ReferencePolicy(prefixes, exact, revit)


def _parse_profile(
    raw: Any,
    *,
    compiler_raw: Mapping[str, Any],
    references_raw: Mapping[str, Any],
    index: int,
) -> TargetProfile:
    fields = frozenset({
        "profile_id",
        "revit_year",
        "release_policy",
        "target_framework",
        "revit_api_package_version",
        "revit_api_reference_path",
    })
    path = f"profiles[{index}]"
    obj = _object(raw, path=path, fields=fields)
    profile_id = _string(obj["profile_id"], path=f"{path}.profile_id")
    year = _string(obj["revit_year"], path=f"{path}.revit_year")
    if re.fullmatch(r"20\d{2}", year) is None:
        raise CompilerContractError(f"{path}.revit_year is invalid")
    try:
        release_policy = ReleasePolicy(
            _string(obj["release_policy"], path=f"{path}.release_policy"))
    except ValueError as exc:
        raise CompilerContractError(
            f"{path}.release_policy is unsupported") from exc
    try:
        target_framework = TargetFramework(
            _string(obj["target_framework"],
                    path=f"{path}.target_framework"))
    except ValueError as exc:
        raise CompilerContractError(
            f"{path}.target_framework is unsupported") from exc
    package_version = _string(
        obj["revit_api_package_version"],
        path=f"{path}.revit_api_package_version",
    )
    reference_path = _string(
        obj["revit_api_reference_path"],
        path=f"{path}.revit_api_reference_path",
    )

    expected_framework = (
        TargetFramework.NET8 if int(year) >= 2025
        else TargetFramework.NET48
    )
    if target_framework is not expected_framework:
        raise CompilerContractError(
            f"{path}: Revit {year} must target {expected_framework.value}")
    framework_token = (
        "net8" if target_framework is TargetFramework.NET8 else "net48")
    expected_id = f"revit-{year}-{framework_token}-cs10-r1"
    if profile_id != expected_id:
        raise CompilerContractError(
            f"{path}.profile_id must be {expected_id!r}")
    if package_version != f"{year}.0.0":
        raise CompilerContractError(
            f"{path}.revit_api_package_version must match the Revit year")
    if reference_path != f"lib/{target_framework.value}":
        raise CompilerContractError(
            f"{path}.revit_api_reference_path does not match target framework")

    profile_digest = canonical_digest({
        "schema_version": PROFILE_SCHEMA,
        "compiler_policy": compiler_raw,
        "reference_policy": references_raw,
        "profile": obj,
    })
    return TargetProfile(
        profile_id=profile_id,
        revit_year=year,
        release_policy=release_policy,
        target_framework=target_framework,
        revit_api_package_version=package_version,
        revit_api_reference_path=reference_path,
        profile_digest=profile_digest,
    )


def parse_target_profile_manifest(raw: Any) -> TargetProfileManifest:
    """Validate raw JSON data and return an immutable manifest."""
    root_fields = frozenset({
        "schema_version",
        "compiler_policy",
        "reference_policy",
        "profiles",
    })
    root = _object(raw, path="manifest", fields=root_fields)
    schema = _string(root["schema_version"], path="schema_version")
    if schema != MANIFEST_SCHEMA:
        raise CompilerContractError(
            f"unsupported compiler manifest schema {schema!r}")
    compiler_raw = _object(
        root["compiler_policy"],
        path="compiler_policy",
        fields=frozenset({
            "roslyn_package_version",
            "language_version",
            "optimization",
            "platform",
            "allow_unsafe",
            "nullable",
        }),
    )
    references_raw = _object(
        root["reference_policy"],
        path="reference_policy",
        fields=frozenset({
            "system_prefixes",
            "system_exact_names",
            "revit_assemblies",
        }),
    )
    compiler = _parse_compiler_policy(compiler_raw)
    references = _parse_reference_policy(references_raw)

    profile_rows = root["profiles"]
    if (not isinstance(profile_rows, Sequence)
            or isinstance(profile_rows, (str, bytes, bytearray))):
        raise CompilerContractError("profiles must be an array")
    profiles = tuple(
        _parse_profile(
            item,
            compiler_raw=compiler_raw,
            references_raw=references_raw,
            index=index,
        )
        for index, item in enumerate(profile_rows)
    )
    ids = tuple(profile.profile_id for profile in profiles)
    years = tuple(profile.revit_year for profile in profiles)
    if len(ids) != len(set(ids)):
        raise CompilerContractError("profile_id values must be unique")
    if len(years) != len(set(years)):
        raise CompilerContractError("Revit profile years must be unique")
    if years != tuple(sorted(years)):
        raise CompilerContractError("profiles must be ordered by Revit year")

    official = {
        profile.revit_year for profile in profiles
        if profile.release_policy is ReleasePolicy.OFFICIAL
    }
    frozen = {
        profile.revit_year for profile in profiles
        if profile.release_policy is ReleasePolicy.FROZEN
    }
    if official != OFFICIAL_YEARS or frozen != FROZEN_YEARS:
        raise CompilerContractError(
            "release policy must be official=2023..2026 and frozen=2021..2022")

    return TargetProfileManifest(
        schema_version=schema,
        compiler_policy=compiler,
        reference_policy=references,
        profiles=profiles,
        manifest_digest=canonical_digest(root),
    )


def parse_target_profile_manifest_archive(raw: Any) -> TargetProfileManifestArchive:
    """Validate the package-owned historical-manifest archive index.

    A persisted record supplies only a digest.  The resource name is pinned by
    this package index and is checked against that digest before any archived
    manifest is parsed.
    """

    root = _object(
        raw,
        path="manifest_archive",
        fields=frozenset({"schema_version", "archives"}),
    )
    schema = _string(root["schema_version"], path="manifest_archive.schema_version")
    if schema != MANIFEST_ARCHIVE_SCHEMA:
        raise CompilerContractError(
            f"unsupported compiler manifest archive schema {schema!r}")
    rows = root["archives"]
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes, bytearray))
    ):
        raise CompilerContractError("manifest_archive.archives must be an array")
    if not rows:
        raise CompilerContractError("manifest_archive.archives must not be empty")

    entries: list[ArchivedTargetProfileManifest] = []
    for index, row in enumerate(rows):
        path = f"manifest_archive.archives[{index}]"
        obj = _object(
            row,
            path=path,
            fields=frozenset({"manifest_digest", "resource"}),
        )
        manifest_digest = _sha256(
            obj["manifest_digest"], path=f"{path}.manifest_digest")
        resource_name = _string(obj["resource"], path=f"{path}.resource")
        match = _ARCHIVE_RESOURCE_RE.fullmatch(resource_name)
        if match is None or match.group(1) != manifest_digest:
            raise CompilerContractError(
                f"{path}.resource must be the digest-pinned archive resource")
        entries.append(ArchivedTargetProfileManifest(
            manifest_digest=manifest_digest,
            resource_name=resource_name,
        ))

    digests = tuple(entry.manifest_digest for entry in entries)
    if len(digests) != len(set(digests)):
        raise CompilerContractError(
            "manifest_archive manifest_digest values must be unique")
    if digests != tuple(sorted(digests)):
        raise CompilerContractError(
            "manifest_archive entries must be ordered by manifest_digest")
    return TargetProfileManifestArchive(
        schema_version=schema,
        entries=tuple(entries),
    )


def _read_packaged_json(resource_name: str) -> Any:
    try:
        payload = resources.files(MANIFEST_PACKAGE).joinpath(
            resource_name).read_text(encoding="utf-8")
        return json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompilerContractError(
            f"cannot load packaged compiler resource {resource_name!r}: {exc}") from exc


@lru_cache(maxsize=1)
def load_target_profile_manifest() -> TargetProfileManifest:
    """Load and validate the packaged target-profile manifest once."""
    return parse_target_profile_manifest(_read_packaged_json(MANIFEST_RESOURCE))


@lru_cache(maxsize=1)
def load_target_profile_manifest_archive() -> TargetProfileManifestArchive:
    """Load the package-owned historical manifest index once."""
    return parse_target_profile_manifest_archive(
        _read_packaged_json(MANIFEST_ARCHIVE_RESOURCE))


def load_archived_target_profile_manifest(
    manifest_digest: str,
) -> TargetProfileManifest:
    """Resolve one historical manifest exclusively from a packaged snapshot.

    ``manifest_digest`` is an identifier supplied by persisted evidence, never
    a request to parse caller-provided manifest bytes.  Every unavailable,
    malformed, or digest-mismatched archive fails with the dedicated typed
    historical refusal.
    """

    try:
        requested_digest = _sha256(
            manifest_digest, path="historical_manifest_digest")
    except CompilerContractError as exc:
        raise HistoricalManifestUnavailableError(
            manifest_digest,
            "requested manifest digest is invalid",
        ) from exc
    try:
        archive = load_target_profile_manifest_archive()
        entry = archive.entry_for_digest(requested_digest)
        if entry is None:
            raise HistoricalManifestUnavailableError(
                requested_digest,
                "no packaged archive entry exists",
            )
        manifest = parse_target_profile_manifest(
            _read_packaged_json(entry.resource_name))
    except HistoricalManifestUnavailableError:
        raise
    except CompilerContractError as exc:
        raise HistoricalManifestUnavailableError(
            requested_digest,
            "packaged archive could not be parsed",
        ) from exc
    if manifest.manifest_digest != requested_digest:
        raise HistoricalManifestUnavailableError(
            requested_digest,
            "packaged archive digest disagrees with its index",
        )
    return manifest


def archived_target_profile_manifest_digests() -> tuple[str, ...]:
    """Return the digest inventory available to historical receipt parsing."""
    return load_target_profile_manifest_archive().manifest_digests


def missing_archived_target_profile_manifest_digests(
    required_manifest_digests: Iterable[str],
) -> tuple[str, ...]:
    """Return retained evidence digests absent from the package archive.

    This is a pure release-retention preflight interface.  A later data-plane
    query supplies the digests referenced by retained strict evidence; this
    module never reads a store and never treats store bytes as a trust root.
    """

    if isinstance(required_manifest_digests, (str, bytes, bytearray)):
        raise TypeError("required_manifest_digests must be an iterable of digests")
    available = frozenset(archived_target_profile_manifest_digests())
    missing: set[str] = set()
    for index, digest in enumerate(required_manifest_digests):
        try:
            required = _sha256(
                digest,
                path=f"required_manifest_digests[{index}]",
            )
        except CompilerContractError as exc:
            raise HistoricalManifestUnavailableError(
                digest,
                "required retention digest is invalid",
            ) from exc
        if required not in available:
            missing.add(required)
            continue
        # Presence in the package index alone is not retention.  Preflight must
        # also reparse and digest-check the immutable resource before a release
        # may claim that retained evidence remains recoverable.
        load_archived_target_profile_manifest(required)
    return tuple(sorted(missing))


def is_current_target_profile_manifest_digest(manifest_digest: str) -> bool:
    """Whether an archived evidence digest still equals the current contract."""
    _sha256(manifest_digest, path="manifest_digest")
    return manifest_digest == load_target_profile_manifest().manifest_digest
