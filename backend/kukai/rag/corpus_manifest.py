"""Corpus manifest — provenance + three-tree drift measurement (IRON 5 / IRON 10).

The corpus has two derived artifacts that historically drifted invisibly:
``data/revit_api_db.json`` (the source-of-truth knowledge base) and
``data/rag_embeddings.npz`` (vectors derived FROM it). Nothing bound them, and
nothing bound either to the tree it lived in — prod served *different embedding
vectors than the repo with identical ids*, and nobody could prove it.

This module is the Mint's measurement instrument (Constitution IRON 5: "Derived
artifacts carry manifests bound to their source's hash; desynchronization is
structurally impossible"; IRON 10: "unmeasured is untrusted"). It computes
content-addressed digests of both artifacts, writes/checks a manifest, and
compares two trees' artifacts.

Design decisions:
  - The npz digest is a CONTENT digest over id-sorted vectors, NOT a file-byte
    digest. The same logical artifact zipped differently across trees must
    compare SAME; the same ids with different vector values (the live prod
    divergence) must compare DRIFT. File-byte hashing would conflate both.
  - numpy is optional-guarded exactly like ``revit_api_index`` — if numpy is
    absent, npz digests degrade to ``"absent:numpy"`` and never raise. The
    manifest gates writes, not reads; a missing/incomputable digest must not
    take down retrieval (Article 9: disclose, don't die).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Optional numpy — only needed for npz (embeddings) digesting.
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover - environment without numpy
    _HAS_NUMPY = False

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "corpus_manifest.json"
DB_FILENAME = "revit_api_db.json"
NPZ_FILENAME = "rag_embeddings.npz"
# Plan 012 version-truth artifacts: the diffed map + the six vendored surfaces
# it is generated from. File-byte sha256 (these are canonical-by-bytes JSON).
API_VERSIONS_FILENAME = "api_versions.json"
API_SURFACE_FILENAMES = tuple(
    f"api_surface/api_surface_{v}.json"
    for v in ("2021", "2022", "2023", "2024", "2025", "2026")
)

# Sentinel used when numpy is unavailable for npz digesting. Never a real hash.
NUMPY_ABSENT = "absent:numpy"


@dataclass
class ArtifactDigest:
    """Content-addressed fingerprint of a single corpus artifact."""

    sha256: Optional[str] = None          # file bytes (json artifacts)
    ids_sha256: Optional[str] = None      # npz: sha256 of '\n'.join(sorted(ids))
    vectors_sha256: Optional[str] = None  # npz: sha256 of id-sorted vector bytes
    counts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out: dict = {}
        if self.sha256 is not None:
            out["sha256"] = self.sha256
        if self.ids_sha256 is not None:
            out["ids_sha256"] = self.ids_sha256
        if self.vectors_sha256 is not None:
            out["vectors_sha256"] = self.vectors_sha256
        if self.counts:
            out["counts"] = dict(self.counts)
        return out


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_db(path: Path) -> ArtifactDigest:
    """Digest the JSON knowledge base: file-byte sha256 + structural counts.

    The JSON is canonical-by-bytes (it's the source-of-truth), so a plain
    file-byte sha256 is correct here — re-serialization with different key order
    would be a genuine change. Counts give a human-legible drift signal.
    """
    sha = _sha256_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    classes = data.get("classes", []) or []
    recipes = data.get("recipes", []) or []
    cats = data.get("builtin_categories", []) or []
    params = data.get("builtin_parameters", []) or []

    examples_total = 0
    examples_v4 = 0
    for cls in classes:
        for ex in cls.get("examples", []) or []:
            examples_total += 1
            if isinstance(ex, dict):
                examples_v4 += 1
    recipes_stamped = sum(1 for r in recipes if isinstance(r, dict) and r.get("verified_at"))

    counts = {
        "classes": len(classes),
        "recipes": len(recipes),
        "builtin_categories": len(cats),
        "builtin_parameters": len(params),
        "examples_total": examples_total,
        "examples_v4": examples_v4,
        "recipes_stamped": recipes_stamped,
    }
    return ArtifactDigest(sha256=sha, counts=counts)


def digest_api_versions(path: Path) -> ArtifactDigest:
    """Digest the version-truth map: file-byte sha256 + type/member fact counts."""
    sha = _sha256_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    types = data.get("types", {}) or {}
    members = data.get("members", {}) or {}
    counts = {
        "types": len(types),
        "members": len(members),
        "types_removed": sum(1 for f in types.values() if isinstance(f, dict) and "removed_in" in f),
        "members_removed": sum(1 for f in members.values() if isinstance(f, dict) and "removed_in" in f),
        "supported": len(data.get("supported", []) or []),
    }
    return ArtifactDigest(sha256=sha, counts=counts)


def digest_api_surface(path: Path) -> ArtifactDigest:
    """Digest one vendored api_surface file: file-byte sha256 + type count."""
    sha = _sha256_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = {"types": len(data) if isinstance(data, dict) else 0}
    except Exception:
        counts = {}
    return ArtifactDigest(sha256=sha, counts=counts)


def digest_npz(path: Path) -> ArtifactDigest:
    """Digest the embeddings npz: CONTENT digests over id-sorted vectors.

    ``ids_sha256``  = sha256 of '\\n'.join(sorted(ids))
    ``vectors_sha256`` = sha256 of the vector rows reordered into ascending
    id order — container-independent, so re-zipping or row-reordering does NOT
    change the digest, but ANY vector value change DOES.

    If numpy is absent, returns sentinels rather than raising (loader safety).
    """
    if not _HAS_NUMPY:
        return ArtifactDigest(
            ids_sha256=NUMPY_ABSENT,
            vectors_sha256=NUMPY_ABSENT,
            counts={},
        )

    data = np.load(str(path), allow_pickle=False)
    raw_ids = data["ids"]
    vectors = data["vectors"]

    ids = [str(x) for x in raw_ids]
    h_ids = _sha256_bytes("\n".join(sorted(ids)).encode("utf-8"))

    # Reorder vector rows into ascending id order so the digest is independent
    # of the on-disk row order (container-independence property).
    order = np.argsort(raw_ids)
    ordered = np.ascontiguousarray(vectors[order])
    h_vec = _sha256_bytes(ordered.tobytes())

    counts = {"count": int(vectors.shape[0]), "dim": int(vectors.shape[1])}
    return ArtifactDigest(ids_sha256=h_ids, vectors_sha256=h_vec, counts=counts)


def _git_rev(data_dir: Path) -> str:
    """Best-effort short git rev of the tree the data_dir lives in."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(data_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def build_manifest(data_dir: Path, git_rev: Optional[str] = None) -> dict:
    """Compute the manifest dict for the artifacts under ``data_dir`` (no write)."""
    data_dir = Path(data_dir)
    db_path = data_dir / DB_FILENAME
    npz_path = data_dir / NPZ_FILENAME

    artifacts: dict = {}

    db_dig = digest_db(db_path)
    artifacts[DB_FILENAME] = {
        "sha256": db_dig.sha256,
        "counts": db_dig.counts,
    }

    npz_dig = digest_npz(npz_path)
    # Read provenance from the npz `meta` key when present (plan 017 builder
    # stamps it INSIDE the artifact: a 0-d unicode array holding a JSON string).
    # Legacy npz files have no `meta` — fall back to the literals + None so the
    # manifest stays back-compatible. Guarded: a malformed/absent meta never
    # raises (IRON 5 fail-open — the manifest gates writes, not reads).
    npz_meta: dict = {}
    if _HAS_NUMPY and npz_path.exists():
        try:
            data = np.load(str(npz_path), allow_pickle=False)
            if "meta" in data:
                npz_meta = json.loads(str(data["meta"]))
        except Exception:  # pragma: no cover - defensive
            npz_meta = {}
    artifacts[NPZ_FILENAME] = {
        "ids_sha256": npz_dig.ids_sha256,
        "vectors_sha256": npz_dig.vectors_sha256,
        "count": npz_dig.counts.get("count"),
        "dim": npz_meta.get("dim", npz_dig.counts.get("dim")),
        "embedding_model": npz_meta.get("embedding_model", "text-embedding-3-large"),
        # The sha256 of revit_api_db.json the vectors were built FROM, stamped
        # by the embed builder inside the npz. None for the legacy artifact (we
        # did not build it). REQUIRED for any regeneration so npz<->db desync is
        # detectable forever (IRON 10).
        "built_from_db_sha256": npz_meta.get("built_from_db_sha256"),
    }
    if npz_meta.get("built_at"):
        artifacts[NPZ_FILENAME]["embeddings_built_at"] = npz_meta["built_at"]
    if npz_meta.get("builder_git_rev"):
        artifacts[NPZ_FILENAME]["embeddings_builder_git_rev"] = npz_meta["builder_git_rev"]

    # Plan 012 version-truth artifacts (registered only when present so trees
    # that predate the vendoring don't fail the manifest — IRON 5 fail-open).
    av_path = data_dir / API_VERSIONS_FILENAME
    if av_path.exists():
        av_dig = digest_api_versions(av_path)
        artifacts[API_VERSIONS_FILENAME] = {
            "sha256": av_dig.sha256,
            "counts": av_dig.counts,
        }
    for rel in API_SURFACE_FILENAMES:
        sp = data_dir / rel
        if sp.exists():
            sdig = digest_api_surface(sp)
            artifacts[rel] = {"sha256": sdig.sha256, "counts": sdig.counts}

    return {
        "manifest_version": MANIFEST_VERSION,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder_git_rev": git_rev if git_rev is not None else _git_rev(data_dir),
        "artifacts": artifacts,
    }


def write_manifest(data_dir: Path, git_rev: Optional[str] = None) -> dict:
    """Compute and persist the manifest to ``data_dir/corpus_manifest.json``."""
    data_dir = Path(data_dir)
    manifest = build_manifest(data_dir, git_rev=git_rev)
    out_path = data_dir / MANIFEST_FILENAME
    out_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _load_manifest(data_dir: Path) -> dict:
    path = Path(data_dir) / MANIFEST_FILENAME
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def check_manifest(data_dir: Path, *, quick: bool = False) -> tuple[bool, str]:
    """Recompute digests and compare against the stored manifest.

    Returns ``(ok, detail)``. ``quick=True`` (used by the loader) verifies the
    db sha256 + npz count + npz ids hash only — it skips hashing the 36 MB of
    vector bytes, which is the CLI's job. Never raises except FileNotFoundError
    when the manifest is absent (callers distinguish absent from mismatch).
    """
    data_dir = Path(data_dir)
    manifest = _load_manifest(data_dir)
    artifacts = manifest.get("artifacts", {})

    # --- db (always checked) ---
    db_stored = artifacts.get(DB_FILENAME, {})
    db_path = data_dir / DB_FILENAME
    if not db_path.exists():
        return False, f"{DB_FILENAME}: file missing"
    db_dig = digest_db(db_path)
    if db_dig.sha256 != db_stored.get("sha256"):
        return False, f"{DB_FILENAME}: sha256 mismatch"

    # --- npz ---
    npz_stored = artifacts.get(NPZ_FILENAME, {})
    npz_path = data_dir / NPZ_FILENAME
    if not npz_path.exists():
        # An absent npz is a disclosure-worthy mismatch, but not fatal: the
        # index already falls back to keyword search when the npz is gone.
        return False, f"{NPZ_FILENAME}: file missing"

    if not _HAS_NUMPY:
        # Cannot verify npz content without numpy; disclose, treat as ok-enough
        # so the loader does not warn on a numpy-less environment that already
        # has semantic search disabled.
        return True, "ok:numpy-absent"

    npz_dig = digest_npz(npz_path)
    if npz_dig.counts.get("count") != npz_stored.get("count"):
        return False, f"{NPZ_FILENAME}: count mismatch"
    if npz_dig.ids_sha256 != npz_stored.get("ids_sha256"):
        return False, f"{NPZ_FILENAME}: ids_sha256 mismatch"
    if not quick:
        if npz_dig.vectors_sha256 != npz_stored.get("vectors_sha256"):
            return False, f"{NPZ_FILENAME}: vectors_sha256 mismatch"

    # --- plan 012 version-truth artifacts (file-byte sha256) ---
    # Verify every recorded api_versions/api_surface artifact. Recorded-but-
    # missing is a mismatch; not-recorded is fine (older manifests / partial trees).
    for name, stored in artifacts.items():
        if name != API_VERSIONS_FILENAME and name not in API_SURFACE_FILENAMES:
            continue
        fpath = data_dir / name
        if not fpath.exists():
            return False, f"{name}: file missing"
        if _sha256_file(fpath) != stored.get("sha256"):
            return False, f"{name}: sha256 mismatch"

    # --- npz<->db binding disclosure (plan 017, IRON 10) ---
    # AFTER every integrity check passes: if the npz was built from a KNOWN db
    # sha (provenance stamped inside the artifact) and that sha no longer
    # matches the CURRENT db, the vectors are stale relative to the knowledge
    # base. This is a DISCLOSURE, not a failure — a legitimate db-only edit
    # (e.g. recipe explanations) must not break CI Gate C, but the staleness
    # must be visible forever. A null binding (legacy npz) stays plain "ok".
    bound_sha = npz_stored.get("built_from_db_sha256")
    if bound_sha and bound_sha != db_dig.sha256:
        return True, "ok:npz-stale-vs-db"

    return True, "ok"


def check_quick(data_dir: Path) -> tuple[bool, str]:
    """Convenience wrapper for the loader's startup check."""
    return check_manifest(data_dir, quick=True)


def compare_trees(data_dir_a: Path, data_dir_b: Path) -> list[tuple[str, str]]:
    """Compare two trees' artifacts by CONTENT digest.

    Returns ``[(artifact, "SAME" | "DRIFT:<which digest differs>"), ...]``.
    Recomputes digests live from both trees (does NOT trust either manifest) so
    it measures the artifacts themselves, not stale stamps.
    """
    data_dir_a = Path(data_dir_a)
    data_dir_b = Path(data_dir_b)
    rows: list[tuple[str, str]] = []

    # db: file-byte sha256 + counts
    a_db = digest_db(data_dir_a / DB_FILENAME)
    b_db = digest_db(data_dir_b / DB_FILENAME)
    if a_db.sha256 == b_db.sha256:
        rows.append((DB_FILENAME, "SAME"))
    else:
        # Distinguish content-equivalent (same counts) from real content drift.
        if a_db.counts == b_db.counts:
            rows.append((DB_FILENAME, "DRIFT:bytes(counts-equal)"))
        else:
            rows.append((DB_FILENAME, "DRIFT:counts"))

    # npz: content digests (ids + vectors independently)
    a_npz = digest_npz(data_dir_a / NPZ_FILENAME)
    b_npz = digest_npz(data_dir_b / NPZ_FILENAME)
    if a_npz.ids_sha256 == NUMPY_ABSENT or b_npz.ids_sha256 == NUMPY_ABSENT:
        rows.append((NPZ_FILENAME, "DRIFT:numpy-absent"))
    else:
        ids_same = a_npz.ids_sha256 == b_npz.ids_sha256
        vec_same = a_npz.vectors_sha256 == b_npz.vectors_sha256
        if ids_same and vec_same:
            rows.append((NPZ_FILENAME, "SAME"))
        elif ids_same and not vec_same:
            rows.append((NPZ_FILENAME, "DRIFT:vectors"))
        elif not ids_same and vec_same:
            rows.append((NPZ_FILENAME, "DRIFT:ids"))
        else:
            rows.append((NPZ_FILENAME, "DRIFT:ids+vectors"))

    # plan 012 version-truth artifacts: file-byte sha256. Report missing-on-one-
    # side explicitly (deploy excludes data/, so absence is a real signal).
    for rel in (API_VERSIONS_FILENAME, *API_SURFACE_FILENAMES):
        pa, pb = data_dir_a / rel, data_dir_b / rel
        if not pa.exists() and not pb.exists():
            continue
        if not pa.exists():
            rows.append((rel, "MISSING:repo"))
        elif not pb.exists():
            rows.append((rel, "MISSING:other"))
        elif _sha256_file(pa) == _sha256_file(pb):
            rows.append((rel, "SAME"))
        else:
            rows.append((rel, "DRIFT:bytes"))

    return rows
