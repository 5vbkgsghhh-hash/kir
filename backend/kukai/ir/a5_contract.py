"""Pure request-scope and source-evidence contract for live A5 runs.

The functions here select the exact typed L1 denominator and bind it to the
snapshot, open-model profile, optional geometry escrow, compiler versions, and
request digest.  No bridge calls or writes are permitted in this module.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Sequence

from kukai.ir.a5_live import _A5_SWEEP_SCHEMA_VERSION
from kukai.ir.a5_recovery import (
    A5Journal,
    A5JournalError,
    request_digest as _a5_request_digest,
)
from kukai.ir.contracts import (
    CoverageProof,
    DocumentFingerprint,
    RevisionProof,
    SnapshotManifest,
)
from kukai.ir.open_model import OpenModelProfile


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
    """A5-скоуп: этаж / роды / кап + host-замыкание, порядок листьев сохранён.

    * ``level_scope`` — все опы одного ``level_name`` (датумы остаются
      контекстом).  ``only_kinds`` независим от ``limit_ops`` (harness-fix
      2026-07-21 — раньше молча игнорировался без лимита).
    * Host-замыкание (живой баг #14 + межэтажный #17, 2026-07-21): хостовые
      опы (двери/окна) ссылаются ``{"ref": <L1 _id>}`` на стену.  Замыкание
      резолвит хосты по ПОЛНОМУ набору листьев (ВСЕ уровни) и втягивает хост
      в скоуп, ДАЖЕ если он на другом этаже — высокая паркинговая стена на
      Этаже −3 хостит двери на −2/−1 (иначе materialize падает
      fail-closed).  Замыкание работает и для чистого ``level_scope`` (раньше
      ранний return его пропускал — этаж 20 везло, у него хосты свои).
      Хосты НЕ считаются в ``limit_ops`` (кап меряет целевые опы).
    * Атомы всегда остаются в выдаче как знаменатель (арх-разбор 2026-07-25
      §3.6): раньше они срезались здесь, и ``_atom_count`` ниже по течению
      всегда видел ноль — непонятое компилятором молча исчезало из оценки.
      Фильтр уровня к ним применяется (атом вне скоупа не наш),
      ``limit_ops``/``only_kinds`` здесь их не скрывают.  Если default-off
      Tier-G включён, отдельный ``_atom_escrow_source_ids_for_scope`` выдаёт
      точный write allow-list; отсутствие в нём остаётся typed skip.
    """
    from kukai.ir.decompile.materialize import _DATUM_OPS

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
            # Неподнятый лист: в знаменатель, если он в этом скоупе.
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
    from kukai.ir.decompile.extract import EXTRACT_CATEGORIES, L0JSONLReader
    from kukai.ir.decompile.schema import CategoryState

    root = _pathlib.Path(out_dir)
    revision_path = root / "revision.proof.json"
    with revision_path.open("r", encoding="utf-8") as source:
        revision = RevisionProof.from_dict(json.load(source))
    if revision.change_stamp != doc_stamp:
        raise A5JournalError("revision proof belongs to another doc_stamp")

    reader = L0JSONLReader(root / "L0.jsonl")
    statuses = tuple(reader.iter_category_status())  # validates full stream
    footer: Optional[dict[str, Any]] = None
    # ЗАКОН УРОВНЯ ФАЙЛА. Страж верил квитанциям категорий и НЕ пересчитывал
    # поток, то есть отвечал на вопрос «что нам про файл сказали», а не «что
    # в файле лежит». Пересчёт стоит один проход (замер: 49 МБ за ~1.1 с) и
    # закрывает целый класс: любое расхождение счётчиков — хоть дописанное
    # поколение строк, хоть потерянная строка — становится типизированным
    # отказом ДО лифта, а не тихой цифрой в отчёте.
    actual_elements = 0
    with (root / "L0.jsonl").open("r", encoding="utf-8") as source:
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
    from kukai.ir.idempotence_contract import (
        DELTA_MM, REBUILD_PLAN_VERSION,
    )
    from kukai.ir import spec as _spec
    from kukai.ir.decompile.fold import FIDELITY_CANON_VERSION

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
