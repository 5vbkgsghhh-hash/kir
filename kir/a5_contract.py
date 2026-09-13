"""Pure request-scope and source-evidence contract for live A5 runs.

The functions here select the exact typed L1 denominator and bind it to the
snapshot, open-model profile, optional geometry escrow, compiler versions, and
request digest.  No bridge calls or writes are permitted in this module.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Sequence

from kir.a5_live import _A5_SWEEP_SCHEMA_VERSION
from kir.a5_recovery import (
    A5Journal,
    A5JournalError,
    request_digest as _a5_request_digest,
)
from kir.contracts import (
    CoverageProof,
    DocumentFingerprint,
    RevisionProof,
    SnapshotManifest,
)
from kir.open_model import OpenModelProfile


def _iter_host_refs(value: Any):
    """Yield every ``{"ref": <L1 _id>}`` target nested in a params value."""
    if isinstance(value, dict):
        ref = value.get("ref")
        if isinstance(ref, str):
            yield ref
        for item in value.values():
            yield from _iter_host_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_host_refs(item)


def _scope_leaves(leaves: list, *, limit_ops: Any = None,
                  only_kinds: Any = None, level_scope: Any = None) -> list:
    """A5 scope: level / kinds / cap + host closure, leaf order preserved.

    * ``level_scope`` — all ops of one ``level_name`` (datums stay context).
      ``only_kinds`` is independent of ``limit_ops`` (harness fix
      2026-07-21 — used to be silently ignored without a limit).
    * Host closure (live bug #14 + cross-level #17, 2026-07-21): host ops
      (doors/windows) reference a wall via ``{"ref": <L1 _id>}``.  The
      closure resolves hosts against the FULL leaf set (ALL levels) and
      pulls the host into scope EVEN IF it is on another level — a tall
      parking wall on Level −3 hosts doors on −2/−1 (otherwise materialize
      fails fail-closed).  The closure also works for a plain
      ``level_scope`` (previously an early return skipped it — level 20 got
      lucky, since it has its own hosts).  Hosts are NOT counted toward
      ``limit_ops`` (the cap measures target ops).
    * Atoms always remain in the output as the denominator (architecture
      review 2026-07-25 §3.6): they used to be cut here, and the downstream
      ``_atom_count`` always saw zero — what the compiler did not understand
      silently vanished from the assessment.  The level filter does apply to
      them (an atom outside scope is not ours), ``limit_ops``/``only_kinds``
      do not hide them here.  If the default-off Tier-G is enabled, a
      separate ``_atom_escrow_source_ids_for_scope`` gives the exact write
      allow-list; absence from it remains a typed skip.
    """
    from kir.decompile.materialize import _DATUM_OPS

    only = set(only_kinds) if isinstance(only_kinds, list) else None
    cap = limit_ops if isinstance(limit_ops, int) and limit_ops > 0 else None
    lvl = level_scope if isinstance(level_scope, str) and level_scope else None
    # No scoping requested → whole-model: datums + ops + atoms (denominator).
    if only is None and cap is None and lvl is None:
        return [leaf for leaf in leaves
                if leaf.get("kind") in ("op", "atom")]

    # Selection pass over the FULL leaf set: in-scope target ops + datums.
    keep: set[int] = set()
    taken = 0
    for idx, leaf in enumerate(leaves):
        if leaf.get("kind") == "atom":
            # An unraised leaf: into the denominator, if it is in this scope.
            if lvl is None or leaf.get("level_name") == lvl:
                keep.add(idx)
            continue
        if leaf.get("kind") != "op":
            continue
        opn = leaf.get("op_name")
        if opn in _DATUM_OPS:
            keep.add(idx)  # datums: pinned context, kept (any level)
            continue
        if lvl is not None and leaf.get("level_name") != lvl:
            continue  # out-of-level (may still be pulled as a host below)
        if only is not None and opn not in only:
            continue  # out-of-scope kind
        if cap is not None and taken >= cap:
            continue
        taken += 1
        keep.add(idx)

    # Host-closure against the FULL set — pulls cross-level hosts too.
    by_l1_id = {leaf.get("_id"): idx for idx, leaf in enumerate(leaves)
                if leaf.get("kind") == "op"}
    frontier = list(keep)
    while frontier:
        added: list[int] = []
        for idx in frontier:
            for ref in _iter_host_refs(leaves[idx].get("params") or {}):
                hidx = by_l1_id.get(ref)
                if hidx is not None and hidx not in keep:
                    keep.add(hidx)
                    added.append(hidx)
        frontier = added
    return [leaf for idx, leaf in enumerate(leaves) if idx in keep]


def _atom_escrow_source_ids_for_scope(
    leaves: Sequence[Mapping[str, Any]],
    *,
    whole_model: bool,
    limit_ops: Any,
    level_scope: Any,
) -> tuple[str, ...]:
    """Return the exact stable atom write allow-list for one A5 scope.

    Atom leaves stay in ``leaves`` as the coverage denominator regardless of
    this selection.  Whole-model and level scopes are explicit geometric
    boundaries.  A generic limited run reuses ``limit_ops`` as a hard atom
    candidate cap.  ``only_kinds`` alone cannot select atoms honestly because
    an atom has no semantic ``op_name`` and is therefore refused by the caller.
    """

    if not isinstance(whole_model, bool):
        raise A5JournalError("A5 whole_model identity must be boolean")
    cap = None
    if not whole_model and isinstance(limit_ops, int) \
            and not isinstance(limit_ops, bool) and limit_ops > 0:
        cap = limit_ops
    if not whole_model and cap is None \
            and not (isinstance(level_scope, str) and level_scope):
        raise A5JournalError(
            "atom escrow requires whole_model, level_scope, or limit_ops")

    source_ids: list[str] = []
    for leaf in leaves:
        if leaf.get("kind") != "atom":
            continue
        source_id = leaf.get("source_element_id")
        if not isinstance(source_id, str) or not source_id:
            raise A5JournalError(
                "scoped atom has no stable source_element_id")
        source_ids.append(source_id)
    if len(set(source_ids)) != len(source_ids):
        raise A5JournalError("scoped atoms have duplicate source identities")
    source_ids.sort(key=lambda value: (
        int(value) if value.isdigit() else 0, value))
    if cap is not None:
        source_ids = source_ids[:cap]
    return tuple(source_ids)


def _a5_scope_digest(leaves: Sequence[Mapping[str, Any]]) -> str:
    """Content identity of the exact scoped L1 input consumed by A5."""

    import hashlib as _hashlib

    if any(not isinstance(leaf, Mapping) for leaf in leaves):
        raise A5JournalError("A5 scope contains a non-object leaf")
    try:
        raw = json.dumps(
            [dict(leaf) for leaf in leaves],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise A5JournalError(
            f"A5 scope is not canonical JSON: {exc}") from exc
    return _hashlib.sha256(raw).hexdigest()



def _load_a5_snapshot_manifest(
    out_dir: str,
    *,
    doc_stamp: str,
    document_fingerprint: DocumentFingerprint,
) -> SnapshotManifest:
    """Load exact revision+coverage evidence for a live A5 transition."""

    import pathlib as _pathlib
    from kir.decompile.extract import EXTRACT_CATEGORIES, L0JSONLReader
    from kir.decompile.schema import CategoryState
    from kir.decompile.snapshot_io import open_snapshot

    root = _pathlib.Path(out_dir)
    revision_path = root / "revision.proof.json"
    with revision_path.open("r", encoding="utf-8") as source:
        revision = RevisionProof.from_dict(json.load(source))
    if revision.change_stamp != doc_stamp:
        raise A5JournalError("revision proof belongs to another doc_stamp")

    reader = L0JSONLReader(root / "L0.jsonl")
    statuses = tuple(reader.iter_category_status())  # validates full stream
    footer: Optional[dict[str, Any]] = None
    # THE LAW AT THE FILE LEVEL. The guard trusted category receipts and did
    # NOT recount the stream, meaning it answered "what were we told about
    # the file," not "what is in the file." A recount costs one pass
    # (measured: 49 MB in ~1.1 s) and closes a whole class of defect: any
    # counter mismatch — an appended generation of lines, a lost line — turns
    # into a typed refusal BEFORE the lift, not a silent number in a report.
    #
    # 🔴 READ THROUGH THE SEAM, NOT DIRECTLY (30.08.2026, found while closing
    # E-26). WITHIN THIS SAME function the file is read TWICE: one line up,
    # through `L0JSONLReader`, which goes through the seam and so understands
    # the compressed form, and here — previously past the seam. On a cooled
    # decompile, the first half PASSED while the second raised
    # `FileNotFoundError`, and this was not an A5 refusal but a CRASH: the
    # exception type is not in the `A5JournalError` dictionary, so it escaped
    # unwrapped and a live turn got a stack trace instead of a named cause.
    #
    # Not an edge case but nearly half the corpus: measured 30.08.2026 — 37
    # of 81 decompiles have a stream that is ONLY compressed.
    actual_elements = 0
    with open_snapshot(root / "L0.jsonl", "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            kind = row.get("record")
            if kind == "element":
                actual_elements += 1
            elif kind == "footer":
                footer = row
    if footer is None:
        raise A5JournalError("L0 stream has no committed footer")
    declared = int(footer.get("element_count", -1))
    if declared != actual_elements:
        raise A5JournalError(
            "L0 footer element_count disagrees with the stream: "
            f"footer={declared}, element records={actual_elements}")
    by_status = sum(int(status.extracted_count) for status in statuses)
    if by_status != actual_elements:
        raise A5JournalError(
            "L0 category receipts disagree with the stream: "
            f"receipts={by_status}, element records={actual_elements}")
    complete = tuple(
        status.category for status in statuses
        if status.state is CategoryState.COMPLETE)
    partial = tuple(
        status.category for status in statuses
        if status.state is CategoryState.PARTIAL)
    coverage = CoverageProof(
        stream_complete=footer.get("stream_complete") is True,
        required_categories=tuple(EXTRACT_CATEGORIES),
        complete_categories=complete,
        partial_categories=partial,
        element_count=int(footer.get("element_count", -1)),
        link_count=int(footer.get("link_count", -1)),
    )
    manifest = SnapshotManifest(
        doc_stamp=doc_stamp,
        document_fingerprint=document_fingerprint,
        revision_proof=revision,
        coverage=coverage,
        l0_path="L0.jsonl",
    )
    if not manifest.authoritative:
        raise A5JournalError("A5 snapshot manifest is not authoritative")
    return manifest


def _load_a5_open_model_profile(
    out_dir: str,
    *,
    doc_stamp: str,
    document_fingerprint: DocumentFingerprint,
    revision_proof: RevisionProof,
) -> OpenModelProfile:
    """Load the exact source catalog required by ``same_document`` rebuild."""

    import pathlib as _pathlib

    path = _pathlib.Path(out_dir) / "open_model.profile.json"
    if not path.is_file():
        raise A5JournalError(
            "A5 source snapshot has no open model profile; re-decompile")
    with path.open("r", encoding="utf-8") as source:
        profile = OpenModelProfile.from_dict(json.load(source))
    if not profile.authoritative:
        raise A5JournalError("A5 open model profile is non-authoritative")
    if profile.document_fingerprint != document_fingerprint:
        raise A5JournalError(
            "A5 open model profile belongs to another document")
    if profile.revision_proof != revision_proof:
        raise A5JournalError(
            "A5 open model profile belongs to another revision")
    if profile.revision_proof.change_stamp != doc_stamp:
        raise A5JournalError(
            "A5 open model profile belongs to another doc_stamp")
    return profile


def _a5_request_hash(
    *,
    doc_stamp: str,
    revision: RevisionProof,
    keep_delta: bool,
    whole_model: bool,
    limit_ops: Any,
    only_kinds: Any,
    level_scope: Any,
    revit_version: str,
    scope_digest: str,
    delta_mm: Any = None,
    atom_escrow: bool = False,
    geometry_bundle_digest: str | None = None,
    atom_escrow_source_ids: Sequence[str] | None = None,
) -> str:
    from kir.idempotence_contract import (
        DELTA_MM, REBUILD_PLAN_VERSION,
    )
    from kir import spec as _spec
    from kir.decompile.fold import FIDELITY_CANON_VERSION

    if not isinstance(scope_digest, str) or re.fullmatch(
            r"[0-9a-f]{64}", scope_digest) is None:
        raise A5JournalError("A5 request lacks exact scoped L1 identity")
    if not isinstance(atom_escrow, bool):
        raise A5JournalError("A5 atom_escrow identity must be boolean")
    digest_ok = (
        isinstance(geometry_bundle_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", geometry_bundle_digest) is not None
    )
    if atom_escrow and not digest_ok:
        raise A5JournalError(
            "A5 atom escrow request lacks geometry bundle identity")
    if not atom_escrow and geometry_bundle_digest is not None:
        raise A5JournalError(
            "A5 geometry bundle identity requires atom escrow")
    selected_ids: tuple[str, ...] | None = None
    if atom_escrow:
        if (not isinstance(atom_escrow_source_ids, Sequence)
                or isinstance(atom_escrow_source_ids,
                              (str, bytes, bytearray))):
            raise A5JournalError(
                "A5 atom escrow request lacks an exact source-id scope")
        selected_ids = tuple(atom_escrow_source_ids)
        if any(not isinstance(value, str) or not value
               for value in selected_ids):
            raise A5JournalError(
                "A5 atom escrow source ids must be non-empty strings")
        stable = tuple(sorted(selected_ids, key=lambda value: (
            int(value) if value.isdigit() else 0, value)))
        if stable != selected_ids or len(set(selected_ids)) != len(selected_ids):
            raise A5JournalError(
                "A5 atom escrow source ids must be sorted and unique")
    elif atom_escrow_source_ids is not None:
        raise A5JournalError(
            "A5 atom escrow source ids require atom escrow")

    return _a5_request_digest({
        "schema_version": "a5-request/4",
        "journal_version": A5Journal.VERSION,
        "sweep_schema_version": _A5_SWEEP_SCHEMA_VERSION,
        "rebuild_plan_version": REBUILD_PLAN_VERSION,
        "ir_version": _spec.IR_VERSION,
        "canon_version": FIDELITY_CANON_VERSION,
        "revit_version": revit_version,
        "scope_digest": scope_digest,
        "atom_escrow": atom_escrow,
        "geometry_bundle_digest": geometry_bundle_digest,
        "atom_escrow_source_ids": (
            list(selected_ids) if selected_ids is not None else None),
        "delta_mm": list(DELTA_MM if delta_mm is None else delta_mm),
        "doc_stamp": doc_stamp,
        "revision_fingerprint": revision.fingerprint,
        "keep_delta": keep_delta,
        "whole_model": whole_model,
        "limit_ops": None if whole_model else limit_ops,
        "only_kinds": None if whole_model else only_kinds,
        "level_scope": None if whole_model else level_scope,
    })
