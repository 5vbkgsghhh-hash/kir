"""Content-addressed cache for the offline LIFT pass (wave: кэш-слой).

``lift_document_detailed`` deterministically maps a frozen L0 document (plus
optional Sketch / FamilyInstance side indexes) to an :class:`LiftResult`.  On a
large model (~90k elements) a full lift is measured at ~5 minutes even though
its inputs are unchanged between calls.  This module wraps the detailed lift in
an opt-in, content-addressed cache so an unchanged document is served from disk
in milliseconds.

LAW (risk register Р-3): the cache changes *how* the result is obtained, never
*what* it is.  Two guarantees make that true:

1. **The key is complete.**  It hashes the document's ``change_stamp``, a full
   content hash of ``document.to_dict()`` (every element and every metadata
   field), the hashes of both side indexes, AND the byte hash of the lift code
   CLOSURE (the whole decompile package plus ``kukai.ir.spec``) — so a code
   change to the lifter or any of its dependencies invalidates every entry.
   Any input that could change the output is in the key.
2. **The value round-trips byte-for-byte.**  A cached ``LiftResult`` serializes
   to exactly the same JSON as a fresh one (``nodes`` are JSON-ready L1
   TypedDicts; ``diagnostics`` are dataclasses whose ``AtomReason`` enum is
   restored on load).  The A/B test asserts ``json.dumps(cached) ==
   json.dumps(fresh)``.

Off by default: ``enabled=False`` calls straight through to
``lift_document_detailed`` and touches no disk.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.lift import (
    LiftDiagnostic,
    LiftResult,
    lift_document_detailed,
)
from kukai.ir.decompile.schema import L0Document

logger = logging.getLogger(__name__)

# Bump when the stored value shape or key derivation changes.  (Independent of
# the lift.py byte-hash, which is folded into the key automatically.)
LIFT_CACHE_WRAPPER_VERSION = "lift-cache/1"

_DECOMPILE_PACKAGE_DIR = Path(__file__).resolve().parent
# lift.py's output also depends on kukai.ir.spec (op registry) — the one
# import it takes from outside the decompile package.
_EXTRA_SOURCE_PATHS = (
    _DECOMPILE_PACKAGE_DIR.parent / "spec.py",
)


def _canonical_json(value: Any) -> str:
    """Deterministic JSON text: sorted keys, compact, unicode preserved.

    ``allow_nan=False`` is load-bearing and was missing until 10.08.2026.
    Seven other modules in this package define their own ``_canonical_json``
    (``midend``, ``journal``, ``geometry_acceptance``, ``passport``,
    ``merkle``, ``acceptance_live``, ``acceptance_mutation``); measured the
    same day, all eight agree BYTE FOR BYTE on every finite payload and parted
    company on exactly two — ``NaN`` and ``Infinity``.  The other seven refuse
    them; this one accepted and emitted ``{"v":NaN}``, which is not JSON:
    RFC 8259 has no such literal, so the text could not be read back by any
    strict parser, and a value every other canon of this package calls a
    refusal was silently keyed here as data.

    The hole has never been observed to open — 0 non-finite floats in 857 650
    records across 12 stored buildings — but it is NOT closed by construction,
    which is why this is a fix rather than a comment: ``L0Element.params`` is
    read by ``schema._mapping``, which checks that the KEYS are strings and
    nothing at all about the values, and those values come from Revit.

    Callers must treat the refusal as *uncacheable*, never as fatal — see
    ``_index_hash`` and ``lift_cache_key``.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lift_source_hash() -> str:
    """Honest code-version key: byte hash of the lift CODE CLOSURE.

    ``lift_document_detailed``'s output depends not only on ``lift.py`` but on
    its in-package dependencies (l1_schema classification tables, schema
    readers, side-index parsers) and on ``kukai.ir.spec``.  Hashing only
    ``lift.py`` would let an edit to a dependency serve a stale entry — the
    lying-cache failure Р-3 forbids.  Hashing the whole package closure
    over-invalidates (any decompile edit is a miss), which is the conservative
    direction: it can cost a recompute, never a wrong answer.  A byte hash is
    truthful even for uncommitted edits.
    """

    try:
        hasher = hashlib.sha256()
        sources = sorted(_DECOMPILE_PACKAGE_DIR.glob("*.py"))
        sources += [p for p in _EXTRA_SOURCE_PATHS if p.exists()]
        for path in sources:
            hasher.update(path.name.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(path.read_bytes())
            hasher.update(b"\x00")
        return hasher.hexdigest()
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("lift sources unreadable for cache versioning: %s", exc)
        # A read failure must never let a stale entry look valid; fold the
        # error text in so the key is at least distinct from any real hash.
        return "unreadable:" + repr(exc)


def _index_hash(index: Any) -> str:
    """Stable hash of an optional side index in any accepted form."""

    if index is None:
        return "none"
    # Wave dataclasses (FamilyPlacementExtraction, profile extractions) expose
    # a JSON-ready to_dict(); prefer it so the hash tracks their real content.
    to_dict = getattr(index, "to_dict", None)
    if callable(to_dict):
        try:
            return _sha256_text(_canonical_json(to_dict()))
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            logger.debug("index to_dict() not serializable: %s", exc)
    if isinstance(index, Mapping):
        try:
            return _sha256_text(_canonical_json(_json_safe(index)))
        except ValueError as exc:
            # A non-finite number somewhere in the index.  Same answer as an
            # unknown shape below: force a miss rather than key on text no
            # strict parser could read back.
            logger.debug("index is not canonical JSON: %s", exc)
            return "nonfinite:" + _sha256_text(repr(index))
    # Unknown shape: refuse to pretend we can key it — return a value that
    # forces a miss rather than a possibly-wrong hit.
    return "opaque:" + _sha256_text(repr(index))


def _json_safe(value: Any) -> Any:
    """Best-effort conversion of a mapping tree to JSON-serializable data."""

    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _document_hash(document: L0Document) -> str:
    """Content hash of the document, or a miss-forcing key if it is not JSON.

    ``L0Element.params`` is the one numeric surface the L0 schema does NOT
    validate for finiteness (``schema._mapping`` checks the keys and nothing
    else), so a Revit-supplied ``NaN`` can reach here.  Р-3 says a cache may
    cost a recompute and must never give a wrong answer, so an uncanonicalisable
    document gets a key distinct from every real hash instead of an exception
    that would kill a run which works today.
    """

    try:
        return _sha256_text(_canonical_json(document.to_dict()))
    except ValueError as exc:
        logger.debug("document is not canonical JSON: %s", exc)
        return "nonfinite:" + _sha256_text(repr(document.to_dict()))


def lift_cache_key(
    document: L0Document,
    profile_index: Any = None,
    family_placement_index: Any = None,
    wall_curve_index: Any = None,
    curtain_index: Any = None,
    annotation_index: Any = None,
    tag_index: Any = None,
    dimension_index: Any = None,
    mep_system_index: Any = None,
) -> str:
    """Return the content-address for one detailed-lift request.

    ``wall_curve_index`` обязан входить в ключ: он МЕНЯЕТ результат лифта
    (дуговая стена поднимается дугой, а не хордой), поэтому запись, посчитанная
    без него, — другой результат на тот же документ.  Без этого поля кэш вернул
    бы ранее сохранённый ХОРДОВЫЙ лифт на запрос с индексом, и проводка индекса
    выглядела бы применённой, молча не работая.
    """

    key_material = {
        "wrapper": LIFT_CACHE_WRAPPER_VERSION,
        "code": _lift_source_hash(),
        "change_stamp": document.change_stamp,
        "document": _document_hash(document),
        "profile_index": _index_hash(profile_index),
        "family_placement_index": _index_hash(family_placement_index),
        "wall_curve_index": _index_hash(wall_curve_index),
        # По той же причине, что и индекс кривых: индекс витражей МЕНЯЕТ
        # результат (ячейка становится опом вместо атома). Запись, посчитанная
        # без него, — другой ответ на тот же документ.
        "curtain_index": _index_hash(curtain_index),
        # И по той же причине — индекс оформления: с ним текстовое
        # примечание становится опом, без него остаётся атомом. Запись,
        # посчитанная без индекса, — ДРУГОЙ ответ на тот же документ, и
        # выдать её на запрос с индексом значило бы показать проводку
        # применённой, пока она молча не работает.
        "annotation_index": _index_hash(annotation_index),
        # И индекс МАРОК: с ним марка становится опом со ссылкой на
        # помеченный узел, без него остаётся атомом. Запись, посчитанная без
        # индекса, — ДРУГОЙ ответ на тот же документ; выдать её на запрос С
        # индексом значило бы показать проводку применённой, пока она молча
        # не работает. Байт-хэш кода закрывает смену КОДА, но не смену
        # ВХОДА, и именно вход здесь меняется.
        "tag_index": _index_hash(tag_index),
        # И индекс РАЗМЕРОВ: с ним размер становится опом со ссылками на
        # измеряемые узлы, без него остаётся атомом source_contract_gap.
        # Запись, посчитанная без индекса, — ДРУГОЙ ответ на тот же документ.
        "dimension_index": _index_hash(dimension_index),
        # И индекс принадлежности системе: с ним у трубы появляется
        # system_type, без него его нет — другой ответ на тот же документ.
        "mep_system_index": _index_hash(mep_system_index),
    }
    return _sha256_text(_canonical_json(key_material))


# ---------------------------------------------------------------------------
# LiftResult (de)serialization
# ---------------------------------------------------------------------------
#
# nodes:       tuple[L1Node, ...]  where L1Node is a JSON-ready TypedDict -> as-is.
# diagnostics: tuple[LiftDiagnostic, ...]  frozen dataclass with an AtomReason
#              enum field -> store the enum's .value, restore the enum on load.


def serialize_lift_result(result: LiftResult) -> dict:
    return {
        "nodes": [dict(node) for node in result.nodes],
        "diagnostics": [
            {
                "source_element_id": diag.source_element_id,
                "category": diag.category,
                "reason": diag.reason.value,
                "detail": diag.detail,
            }
            for diag in result.diagnostics
        ],
    }


def deserialize_lift_result(payload: Mapping[str, Any]) -> LiftResult:
    nodes = tuple(payload.get("nodes", []))
    diagnostics = tuple(
        LiftDiagnostic(
            source_element_id=row["source_element_id"],
            category=row["category"],
            reason=AtomReason(row["reason"]),
            detail=row["detail"],
        )
        for row in payload.get("diagnostics", [])
    )
    return LiftResult(nodes=nodes, diagnostics=diagnostics)


def _entry_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def _read_entry(cache_dir: Path, key: str) -> Optional[dict]:
    path = _entry_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.debug("lift cache read failed for %s: %s", key, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _write_entry(cache_dir: Path, key: str, payload: dict) -> None:
    path = _entry_path(cache_dir, key)
    tmp = path.with_suffix(".json.tmp")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug("lift cache write failed for %s: %s", key, exc)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def cached_lift_document_detailed(
    document: L0Document,
    profile_index: Any = None,
    family_placement_index: Any = None,
    *,
    wall_curve_index: Any = None,
    curtain_index: Any = None,
    annotation_index: Any = None,
    tag_index: Any = None,
    dimension_index: Any = None,
    mep_system_index: Any = None,
    enabled: bool = False,
    cache_dir: Optional[str | os.PathLike[str]] = None,
) -> LiftResult:
    """Detailed lift with an opt-in content-addressed cache.

    When ``enabled`` is ``False`` (the default) this is exactly
    ``lift_document_detailed(document, profile_index, family_placement_index,
    wall_curve_index)`` with no disk access.

    When ``enabled`` and ``cache_dir`` is provided, an unchanged
    (document, indexes, lift.py) tuple returns the previously computed
    :class:`LiftResult`, which is byte-for-byte identical to a fresh one.

    ``wall_curve_index`` доносится до лифта наравне с прочими side-индексами:
    без него дуговая стена деградирует до хорды, и оригинальная сторона видит
    МЕНЬШЕ контекста, чем A5-релифт (``kir_idempotence`` индекс передаёт) — то
    есть сверка идёт на деградированном представлении.
    """

    if not enabled:
        return lift_document_detailed(
            document, profile_index, family_placement_index,
            wall_curve_index=wall_curve_index,
            curtain_index=curtain_index,
            annotation_index=annotation_index,
            tag_index=tag_index,
            dimension_index=dimension_index,
            mep_system_index=mep_system_index,
        )

    directory = Path(cache_dir) if cache_dir is not None else None
    key = lift_cache_key(
        document, profile_index, family_placement_index,
        wall_curve_index=wall_curve_index,
        curtain_index=curtain_index,
        annotation_index=annotation_index,
        tag_index=tag_index,
        dimension_index=dimension_index,
        mep_system_index=mep_system_index)

    if directory is not None:
        payload = _read_entry(directory, key)
        if payload is not None:
            try:
                return deserialize_lift_result(payload)
            except (KeyError, ValueError) as exc:
                # Corrupt/foreign entry: recompute rather than serve garbage.
                logger.debug("lift cache entry unusable for %s: %s", key, exc)

    result = lift_document_detailed(
        document, profile_index, family_placement_index,
        wall_curve_index=wall_curve_index,
        curtain_index=curtain_index,
        annotation_index=annotation_index,
        tag_index=tag_index,
        dimension_index=dimension_index,
        mep_system_index=mep_system_index,
    )

    if directory is not None:
        _write_entry(directory, key, serialize_lift_result(result))

    return result


__all__ = [
    "LIFT_CACHE_WRAPPER_VERSION",
    "cached_lift_document_detailed",
    "deserialize_lift_result",
    "lift_cache_key",
    "serialize_lift_result",
]
