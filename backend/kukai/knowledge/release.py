"""Immutable knowledge-release resolver and integrity verifier.

The pointer and every release file are tracked outside ``backend/data`` so
normal source deployment cannot silently leave Wiki/API truth behind.  A
release is accepted only when its pointer, manifest and exact file set agree.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

POINTER_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
_RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class KnowledgeReleaseError(RuntimeError):
    """The configured knowledge release is absent, malformed or tampered."""


def default_knowledge_root() -> Path:
    # .../backend/kukai/knowledge/release.py -> .../backend/knowledge
    return Path(__file__).resolve().parents[2] / "knowledge"


def knowledge_root() -> Path:
    raw = (os.getenv("KUKAI_KNOWLEDGE_ROOT") or "").strip()
    return Path(raw).expanduser() if raw else default_knowledge_root()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KnowledgeReleaseError(f"{label} missing: {path}") from exc
    except Exception as exc:
        raise KnowledgeReleaseError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise KnowledgeReleaseError(f"{label} must be a JSON object: {path}")
    return value


@dataclass(frozen=True)
class KnowledgeRelease:
    release_id: str
    root: Path
    manifest_path: Path
    manifest_sha256: str
    manifest: dict[str, Any]

    @property
    def wiki_root(self) -> Path:
        return self.root / "wiki"

    @property
    def api_surface_root(self) -> Path:
        return self.root / "api_surface"

    @property
    def extensions_root(self) -> Path:
        return self.root / "extensions"

    @property
    def routing_index_path(self) -> Path:
        return self.wiki_root / "routing_index.json"

    @property
    def corpus_version(self) -> str:
        return str(self.manifest.get("corpus_version") or self.release_id)

    @property
    def metrics(self) -> dict[str, Any]:
        value = self.manifest.get("metrics")
        return dict(value) if isinstance(value, dict) else {}

    def public_metadata(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "corpus_version": self.corpus_version,
            "manifest_sha256": self.manifest_sha256,
            "metrics": self.metrics,
        }


def _safe_manifest_path(release_root: Path, rel: str) -> Path:
    if not rel or rel.startswith(("/", "\\")) or "\\" in rel:
        raise KnowledgeReleaseError(f"unsafe manifest path: {rel!r}")
    parts = Path(rel).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise KnowledgeReleaseError(f"unsafe manifest path: {rel!r}")
    candidate = release_root.joinpath(*parts)
    try:
        candidate.resolve().relative_to(release_root.resolve())
    except Exception as exc:
        raise KnowledgeReleaseError(f"manifest path escapes release: {rel!r}") from exc
    return candidate


def load_release(root: Path | None = None, *, verify: bool = True) -> KnowledgeRelease:
    base = (root or knowledge_root()).resolve()
    pointer_path = base / "current.json"
    pointer = _read_json(pointer_path, "knowledge pointer")
    if pointer.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise KnowledgeReleaseError(
            f"unsupported pointer schema {pointer.get('schema_version')!r} in {pointer_path}"
        )
    release_id = str(pointer.get("release_id") or "")
    if not _RELEASE_ID_RE.fullmatch(release_id):
        raise KnowledgeReleaseError(f"invalid knowledge release_id: {release_id!r}")

    release_root = base / "releases" / release_id
    manifest_path = release_root / "manifest.json"
    manifest_hash = _sha256(manifest_path) if manifest_path.exists() else ""
    expected_manifest_hash = str(pointer.get("manifest_sha256") or "")
    if expected_manifest_hash and manifest_hash != expected_manifest_hash:
        raise KnowledgeReleaseError(
            "knowledge manifest hash mismatch: "
            f"expected {expected_manifest_hash}, got {manifest_hash or 'missing'}"
        )
    manifest = _read_json(manifest_path, "knowledge manifest")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise KnowledgeReleaseError(
            f"unsupported manifest schema {manifest.get('schema_version')!r}"
        )
    if manifest.get("release_id") != release_id:
        raise KnowledgeReleaseError(
            f"pointer release {release_id!r} != manifest release {manifest.get('release_id')!r}"
        )

    result = KnowledgeRelease(
        release_id=release_id,
        root=release_root,
        manifest_path=manifest_path,
        manifest_sha256=manifest_hash,
        manifest=manifest,
    )
    if verify:
        verify_release(result)
    return result


def verify_release(release: KnowledgeRelease) -> None:
    files = release.manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise KnowledgeReleaseError("knowledge manifest has no files map")

    declared: set[str] = set()
    for rel, meta in files.items():
        if not isinstance(rel, str) or not isinstance(meta, dict):
            raise KnowledgeReleaseError("manifest files entries must be path -> object")
        path = _safe_manifest_path(release.root, rel)
        if path.is_symlink() or not path.is_file():
            raise KnowledgeReleaseError(f"declared knowledge file missing/not regular: {rel}")
        expected_size = meta.get("bytes")
        expected_hash = meta.get("sha256")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise KnowledgeReleaseError(f"invalid byte size for {rel}")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise KnowledgeReleaseError(f"invalid sha256 for {rel}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise KnowledgeReleaseError(
                f"knowledge file size mismatch for {rel}: expected {expected_size}, got {actual_size}"
            )
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise KnowledgeReleaseError(
                f"knowledge file hash mismatch for {rel}: expected {expected_hash}, got {actual_hash}"
            )
        declared.add(rel)

    actual = {
        p.relative_to(release.root).as_posix()
        for p in release.root.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    missing_from_manifest = sorted(actual - declared)
    missing_from_disk = sorted(declared - actual)
    if missing_from_manifest or missing_from_disk:
        raise KnowledgeReleaseError(
            "knowledge release file set mismatch: "
            f"undeclared={missing_from_manifest[:8]} missing={missing_from_disk[:8]}"
        )

    required = {
        "wiki/index.md",
        "wiki/SCHEMA.md",
        "wiki/capability_catalog.json",
        "wiki/routing_index.json",
    }
    absent = sorted(required - declared)
    if absent:
        raise KnowledgeReleaseError(f"knowledge release missing required assets: {absent}")


@lru_cache(maxsize=1)
def current_release() -> KnowledgeRelease:
    """Resolve and fully verify the active release once per process."""

    return load_release(verify=True)


def reset_release_cache() -> None:
    """Test/deploy hook. Production releases are immutable after startup."""

    current_release.cache_clear()
