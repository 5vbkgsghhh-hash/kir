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
   CLOSURE (the whole decompile package plus ``kir.spec``) — so a code
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

from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import (
    GroupLift,
    GroupLiftReason,
    GroupRefusal,
    JoinLift,
    JoinLiftReason,
    JoinRefusal,
    LiftDiagnostic,
    LiftResult,
    lift_document_detailed,
)
from kir.decompile.schema import L0Document

logger = logging.getLogger(__name__)

# Bump when the stored value shape or key derivation changes.  (Independent of
# the lift.py byte-hash, which is folded into the key automatically.)
#: 🔴 BUMPED TO /2 TOGETHER WITH THE `joins` FIELD (22.08.2026). A version
#: /1 record carries no joins, and reading it as valid would say "no
#: joins" on a document where they exist — that is, OUR blindness
#: disguised as a fact about the building.
#:
#: 🔴 AND TO /3 TOGETHER WITH THE `groups` FIELD (23.08.2026), by the
#: exact same argument: a /2 record carries no groups, and reading it as
#: valid would say "there are no design units in the building" on a
#: document that has 177 of them.
LIFT_CACHE_WRAPPER_VERSION = "lift-cache/3"

_DECOMPILE_PACKAGE_DIR = Path(__file__).resolve().parent
# lift.py's output also depends on kir.spec (op registry) — the one
# import it takes from outside the decompile package.
#
# 🔴 IT USED TO BE `_DECOMPILE_PACKAGE_DIR.parent / "spec.py"` — CORRECT
# TODAY and fragile tomorrow: the answer depends on what level within the
# package THIS file happens to sit at, not on the registry's location. The
# same count-steps-upward already cost twice — the sandbox (`f518b05`) and
# `install_paths`. The anchor is taken from the location of THE PACKAGE
# ITSELF: the module can move into a subpackage and the answer won't
# change.
import kir as _kir_pkg  # noqa: E402  — package anchor; `kir` is already loaded above

_EXTRA_SOURCE_PATHS = (
    Path(_kir_pkg.__file__).resolve().parent / "spec.py",
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


#: Directories inside the package that are NOT included in the closure.
#: Tests change every day and don't affect the lift result; including them
#: would make us miss the cache on every test edit, that is, silently
#: switch the cache off.
_CLOSURE_SKIP_PARTS = frozenset({"tests", "__pycache__"})


def _lift_closure_sources() -> list[tuple[str, Path]]:
    """(path-relative-to-package, file) for everything the lift depends on.

    🔴 IT USED TO BE `decompile/*.py` PLUS `spec.py`, AND THE COMMENT NEXT
    TO IT ASSERTED THAT THIS WAS «the one import it takes from outside the
    decompile package». The assertion is false, and this is measured by
    walking `lift.py`'s imports (29.08.2026): outside the decompile
    package it takes EIGHT modules —

        kir.geom            ring limits, `ring_normalize`, `check_holes_relation`
        kir.contour         `MIN_ARC_BULGE`/`MAX_ARC_BULGE`, `bulge_midpoint`
        kir.ops_authoring   `WALL_LOCATION_LINE_NAMES`
        kir.ops_shape       `DIRECTSHAPE_CATEGORIES`
        kir.mesh            `validate_mesh`
        kir.reverse_contract  `assert_composed_emission`
        kir.record_ratchet  journals
        kir.spec            ← the only one that was in the key

    The cost of the miss is NOT theoretical. On 21.08 the
    `MIN_RING_AREA_MM2` threshold in `geom.py` was lowered from 10 000 to
    100 mm², and this brought back 20 family shapes that had until then
    been atomized as a "degenerate contour." On a warm `lift_cache`, this
    edit DID NOT CHANGE THE KEY — the decompile would have returned the
    previous L1, where the shapes are still atoms, with no refusal and no
    log entry. Our blindness disguised as a fact about the building,
    exactly what R-3 declares impossible.

    WHAT WAS TAKEN INSTEAD, AND WHY EXACTLY THIS. Not a list of names: an
    enumeration goes stale on the very first new import, and it goes stale
    SILENTLY — the same way the previous one did. What is taken is THE
    WHOLE PACKAGE (except tests), and this is not wastefulness but the
    direction the docstring below has already chosen: re-inviting a
    recompute is allowed, handing back someone else's answer is not.
    """
    root = Path(_kir_pkg.__file__).resolve().parent
    out: dict[str, Path] = {}
    for path in root.rglob("*.py"):
        if _CLOSURE_SKIP_PARTS & set(path.parts):
            continue
        if path.name.startswith("test_"):
            continue
        out[str(path.relative_to(root))] = path
    # Explicit paths remain in the closure even after the walk: their
    # existence is guarded by `test_no_path_is_counted_in_steps_up`, and
    # silently switching off the subject of someone else's guard is not
    # allowed.
    for extra in _EXTRA_SOURCE_PATHS:
        if extra.exists():
            out[str(extra.name)] = extra
    return sorted(out.items())


def _lift_source_hash() -> str:
    """Honest code-version key: byte hash of the lift CODE CLOSURE.

    ``lift_document_detailed``'s output depends not only on ``lift.py`` but on
    its in-package dependencies (l1_schema classification tables, schema
    readers, side-index parsers) and on eight modules OUTSIDE the decompile
    package — see :func:`_lift_closure_sources`, which enumerates them and the
    measured price of having missed them.  Hashing only ``lift.py`` would let
    an edit to a dependency serve a stale entry — the lying-cache failure Р-3
    forbids.  Hashing the whole package closure over-invalidates (any edit is
    a miss), which is the conservative direction: it can cost a recompute,
    never a wrong answer.  A byte hash is truthful even for uncommitted edits.
    """

    try:
        hasher = hashlib.sha256()
        sources = _lift_closure_sources()
        if not sources:
            # The closure is empty — there was nothing to read. Zero here
            # is indistinguishable from an honest "the code hasn't
            # changed," and that is exactly the lie R-3 forbids; so the
            # key is GUARANTEED not to match any record.
            return "unreadable:пакет не прочитан ни одним файлом"
        for path in sources:
            # PATH RELATIVE TO THE PACKAGE, NOT `path.name`: a file name
            # doesn't distinguish `decompile/schema.py` from
            # `checker/schema.py`, and swapping their contents wouldn't
            # change the key.
            hasher.update(str(path[0]).encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(path[1].read_bytes())
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
    join_index: Any = None,
    group_index: Any = None,
) -> str:
    """Return the content-address for one detailed-lift request.

    ``wall_curve_index`` must be part of the key: it CHANGES the lift
    result (an arc wall is lifted as an arc, not a chord), so a record
    computed without it is a different result for the same document.
    Without this field the cache would return the previously saved CHORD
    lift for a request carrying the index, and the index's wiring would
    look applied while silently not working.
    """

    key_material = {
        "wrapper": LIFT_CACHE_WRAPPER_VERSION,
        "code": _lift_source_hash(),
        "change_stamp": document.change_stamp,
        "document": _document_hash(document),
        "profile_index": _index_hash(profile_index),
        "family_placement_index": _index_hash(family_placement_index),
        "wall_curve_index": _index_hash(wall_curve_index),
        # For the same reason as the curve index: the curtain-wall index
        # CHANGES the result (a cell becomes an op instead of an atom). A
        # record computed without it is a different answer for the same
        # document.
        "curtain_index": _index_hash(curtain_index),
        # And for the same reason — the annotation index: with it a text
        # note becomes an op, without it it stays an atom. A record
        # computed without the index is a DIFFERENT answer for the same
        # document, and handing it out for a request carrying the index
        # would show the wiring as applied while it silently isn't
        # working.
        "annotation_index": _index_hash(annotation_index),
        # And the TAG index: with it a tag becomes an op referencing the
        # tagged node, without it it stays an atom. A record computed
        # without the index is a DIFFERENT answer for the same document;
        # handing it out for a request WITH the index would show the
        # wiring as applied while it silently isn't working. The code's
        # byte-hash covers a change in CODE, not a change in INPUT, and
        # it's the input that changes here.
        "tag_index": _index_hash(tag_index),
        # And the DIMENSION index: with it a dimension becomes an op with
        # references to the measured nodes, without it it stays a
        # source_contract_gap atom. A record computed without the index is
        # a DIFFERENT answer for the same document.
        "dimension_index": _index_hash(dimension_index),
        # And the system-membership index: with it a pipe gets a
        # system_type, without it there is none — a different answer for
        # the same document.
        "mep_system_index": _index_hash(mep_system_index),
        # 🔴 AND THE JOIN INDEX. With it the answer carries `joins` (on
        # MNVNK 1 992 `join_elements` operations), without it `joins is
        # None`. A record computed without the index is a DIFFERENT
        # answer for the same document, and handing it out as the answer
        # with the index would mean returning "there are no joins."
        "join_index": _index_hash(join_index),
        # 🔴 AND THE GROUP INDEX, by the same argument: with it the answer
        # carries `groups` (on K6 28 `create_group` operations, 944
        # operations not itemized), without it `groups is None`. Handing
        # out a record computed without the index as the answer with the
        # index would mean returning "there are no groups."
        "group_index": _index_hash(group_index),
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
    """🔴 THIS FUNCTION IS ASSEMBLED FIELD BY FIELD, AND THAT IS ITS
    DANGEROUS PROPERTY.

    A `LiftResult` field it doesn't know about, it drops SILENTLY: the
    cached decompile comes back without it, and there isn't a single sign
    of the loss. It was exactly on this seam that the join lifter stalled
    on 22.08.2026 — it had been written and couldn't get through. Keeping
    fields and keys in correspondence is held by
    `test_lift_cache_carries_every_field`, not by the editor's memory.
    """
    return {
        # 🔴 THE RECORD MUST SAY IT IS OURS (F-260). The wrapper's version
        # is already part of the KEY, but the key is the FILE NAME: a
        # truncated record (disk ran out), a foreign file, or an empty
        # `{}` object placed under the same name are indistinguishable
        # from our own record. A marker INSIDE answers a question the name
        # cannot ask.
        "wrapper": LIFT_CACHE_WRAPPER_VERSION,
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
        # `None` and an empty `JoinLift` are DIFFERENT: the former means
        # "the index wasn't supplied," the latter "supplied, no joins."
        # The key always exists, the value doesn't.
        "joins": None if result.joins is None else {
            "ops": [dict(op) for op in result.joins.ops],
            "refusals": [
                {"first": r.first, "second": r.second,
                 "reason": r.reason.value, "detail": r.detail}
                for r in result.joins.refusals
            ],
            "pairs_read": result.joins.pairs_read,
            "end_joins_read": result.joins.end_joins_read,
            "walls_with_end_permission": result.joins.walls_with_end_permission,
            "end_states": dict(result.joins.end_states),
            "elements_not_read": list(result.joins.elements_not_read),
        },
        # The same "None versus empty" discipline as for joins.
        "groups": None if result.groups is None else {
            "ops": [dict(op) for op in result.groups.ops],
            "refusals": [
                {"group_type_id": r.group_type_id,
                 "group_type_name": r.group_type_name,
                 "reason": r.reason.value, "detail": r.detail}
                for r in result.groups.refusals
            ],
            "definitions_read": result.groups.definitions_read,
            "instances_read": result.groups.instances_read,
            "instances_covered": result.groups.instances_covered,
            "member_ops": result.groups.member_ops,
            "ops_not_written_individually":
                result.groups.ops_not_written_individually,
            "composition_mismatches": result.groups.composition_mismatches,
        },
    }


#: Keys the serializer ALWAYS writes. `joins` and `groups` can carry
#: `None` AS A VALUE — but the key exists, and that is recorded by the
#: serializer itself. So a missing key is a sign of a FOREIGN record, not
#: an empty building.
_REQUIRED_ENTRY_KEYS = ("nodes", "diagnostics", "joins", "groups")


def deserialize_lift_result(payload: Mapping[str, Any]) -> LiftResult:
    """Restore a `LiftResult` from a cache record — OR REFUSE BY NAME.

    🔴 `.get(..., default)` ON EVERY FIELD TURNED `{}` INTO A LEGITIMATE
    ANSWER (F-260): zero nodes, zero diagnostics, `joins=None`,
    `groups=None` — that is, "the building is empty AND joins weren't
    asked for AND groups weren't asked for," the most plausible-looking
    shape of a total reading failure. This ran on the live path before the
    fix (`pipeline` calls the wrapper with `enabled=True`
    unconditionally): a fresh decompile gave 1 node, the substituted `{}`
    gave 0 nodes, and this was called a HIT.

    The default here was not a wrong choice of value but an answer to a
    question that was NEVER ASKED: `nodes=()` is a legitimate result (a
    document with no elements), and it must not be forbidden; what must be
    forbidden is DERIVING it from the absence of a key.

    The refusal is `ValueError`, not a class of its own: the wrapper's
    recovery branch already catches it, so this half of the fix works even
    on its own.
    """

    if not isinstance(payload, Mapping):
        raise ValueError(
            f"lift cache entry is {type(payload).__name__}, not a mapping")
    stamp = payload.get("wrapper")
    if stamp != LIFT_CACHE_WRAPPER_VERSION:
        raise ValueError(
            f"lift cache entry wrapper is {stamp!r}, "
            f"not {LIFT_CACHE_WRAPPER_VERSION!r}")
    missing = [key for key in _REQUIRED_ENTRY_KEYS if key not in payload]
    if missing:
        raise ValueError(
            "lift cache entry is missing " + ", ".join(missing))
    for key in ("nodes", "diagnostics"):
        if not isinstance(payload[key], list):
            raise ValueError(
                f"lift cache entry {key} is "
                f"{type(payload[key]).__name__}, not a list")
    # 🔴 THESE TWO LINES WERE FOUND BY EXECUTION, NOT BY READING THE
    # PACKAGE. The package named TWO kinds of refusal (`ValueError` and an
    # uncaught `TypeError`), and checking found a THIRD: `joins`/`groups`
    # arriving as a list or a number reach `.get(...)` and raise
    # `AttributeError` — the same corruption, only under a name neither
    # the old branch nor the fixed one caught. Here it is NAMED, not
    # caught by guesswork: a foreign shape must become a refusal with the
    # field's name, not a random attribute failure.
    for key in ("joins", "groups"):
        if payload[key] is not None and not isinstance(payload[key], Mapping):
            raise ValueError(
                f"lift cache entry {key} is "
                f"{type(payload[key]).__name__}, not a mapping or null")
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
    raw_joins = payload.get("joins")
    joins = None if raw_joins is None else JoinLift(
        ops=tuple(dict(op) for op in raw_joins.get("ops", ())),
        refusals=tuple(
            JoinRefusal(first=row["first"], second=row["second"],
                        reason=JoinLiftReason(row["reason"]),
                        detail=row["detail"])
            for row in raw_joins.get("refusals", ())),
        pairs_read=int(raw_joins.get("pairs_read", 0)),
        end_joins_read=int(raw_joins.get("end_joins_read", 0)),
        walls_with_end_permission=int(
            raw_joins.get("walls_with_end_permission", 0)),
        end_states=dict(raw_joins.get("end_states", {})),
        elements_not_read=tuple(raw_joins.get("elements_not_read", ())),
    )
    raw_groups = payload.get("groups")
    groups = None if raw_groups is None else GroupLift(
        ops=tuple(dict(op) for op in raw_groups.get("ops", ())),
        refusals=tuple(
            GroupRefusal(
                group_type_id=row["group_type_id"],
                group_type_name=row["group_type_name"],
                reason=GroupLiftReason(row["reason"]),
                detail=row["detail"])
            for row in raw_groups.get("refusals", ())),
        definitions_read=int(raw_groups.get("definitions_read", 0)),
        instances_read=int(raw_groups.get("instances_read", 0)),
        instances_covered=int(raw_groups.get("instances_covered", 0)),
        member_ops=int(raw_groups.get("member_ops", 0)),
        ops_not_written_individually=int(
            raw_groups.get("ops_not_written_individually", 0)),
        composition_mismatches=int(
            raw_groups.get("composition_mismatches", 0)),
    )
    return LiftResult(nodes=nodes, diagnostics=diagnostics, joins=joins,
                      groups=groups)


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
        # 🔴 THE FILE EXISTS, BUT THERE'S NOTHING TO READ IT WITH — THIS IS
        # A REFUSAL, NOT A MISS. A miss ("no record") and a refusal ("a
        # record exists and is unfit") are different facts, and before
        # this line they both arrived as the single value `None`. Found by
        # our own ratchet: a file substituted as a LIST produced a
        # recompute with the correct answer and NOT A SINGLE REASON in the
        # journal.
        logger.debug("lift cache read failed for %s: %s", key, exc)
        _note_unusable(cache_dir, key, exc)
        return None
    if not isinstance(payload, dict):
        logger.debug("lift cache entry for %s is %s, not an object",
                     key, type(payload).__name__)
        _note_unusable(cache_dir, key, ValueError(
            f"lift cache entry is {type(payload).__name__}, not an object"))
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


#: The journal of UNFIT records — next to the records themselves, the same
#: directory. Its name is separate: it must not be confused with a cache
#: record, the suffix is different.
_UNUSABLE_LEDGER = "unusable.jsonl"


def _note_unusable(directory: Path, key: str, exc: BaseException) -> None:
    """Record WHY a cache entry is unfit. NEVER RAISES.

    The wrapper must be able to recompute through any disk trouble; a
    guard capable of crashing the run would cost more than the defect it
    guards against.
    """

    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / _UNUSABLE_LEDGER).open(
                "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"key": key, "reason": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False) + "\n")
    except OSError:
        pass


def lift_cache_refusals(
    cache_dir: str | os.PathLike[str],
) -> tuple[str, ...]:
    """Records the cache REFUSED to read — by their reasons.

    An empty tuple means "there were no refusals," not "there's no one to
    ask": no directory is also empty, and that is LEGITIMATE (the cache
    might not have been needed). A run whose decompile took the full lift
    time on a "hit" asks here and gets the NAME OF THE REASON instead of a
    guess.
    """

    path = Path(cache_dir) / _UNUSABLE_LEDGER
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            # Even here, silence isn't allowed: a broken line in the
            # refusal journal is itself a refusal, and counting it is
            # cheaper than losing it.
            out.append("unparsable ledger line")
            continue
        if isinstance(row, Mapping):
            out.append(str(row.get("reason") or ""))
    return tuple(out)


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
    join_index: Any = None,
    group_index: Any = None,
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

    ``wall_curve_index`` is carried through to the lift on equal footing
    with the other side indexes: without it an arc wall degrades to a
    chord, and the original side sees LESS context than the A5-relift
    (``kir.idempotence`` does pass the index) — that is, the comparison
    runs against a degraded representation.
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
            join_index=join_index,
            group_index=group_index,
        )

    directory = Path(cache_dir) if cache_dir is not None else None
    key = lift_cache_key(
        document, profile_index, family_placement_index,
        wall_curve_index=wall_curve_index,
        curtain_index=curtain_index,
        annotation_index=annotation_index,
        tag_index=tag_index,
        dimension_index=dimension_index,
        mep_system_index=mep_system_index,
        join_index=join_index,
        group_index=group_index)

    if directory is not None:
        payload = _read_entry(directory, key)
        if payload is not None:
            try:
                return deserialize_lift_result(payload)
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                # Corrupt/foreign entry: recompute rather than serve garbage.
                #
                # 🔴 `TypeError` DIDN'T REACH HERE (F-250), and so a
                # legitimate JSON `{"nodes": null, "diagnostics": []}`
                # crashed the WHOLE decompile instead of a cache miss. The
                # cache has no right to be the cause of a run's refusal:
                # the R-3 law allows it to cost a RECOMPUTE and forbids
                # giving a wrong answer — there's not a word in it about
                # "crashing." `AttributeError` is a third kind, found by
                # execution after the fix: a foreign shape inside `joins`
                # crashed the read past both named names. It is named
                # EXPLICITLY in the prologue, and here it stands as a
                # belt: the law "the cache doesn't crash the run" must not
                # depend on the prologue being complete.
                logger.debug("lift cache entry unusable for %s: %s", key, exc)
                # The wrapper's answer doesn't change (it was a recompute —
                # it stays a recompute), but the silence now has a REASON
                # that can be asked about: `logger.debug` goes nowhere,
                # and a run whose "hit" took the full lift time still had
                # no way to find out why.
                _note_unusable(directory, key, exc)

    result = lift_document_detailed(
        document, profile_index, family_placement_index,
        wall_curve_index=wall_curve_index,
        curtain_index=curtain_index,
        annotation_index=annotation_index,
        tag_index=tag_index,
        dimension_index=dimension_index,
        mep_system_index=mep_system_index,
        join_index=join_index,
        group_index=group_index,
    )

    if directory is not None:
        _write_entry(directory, key, serialize_lift_result(result))

    return result


__all__ = [
    "LIFT_CACHE_WRAPPER_VERSION",
    "cached_lift_document_detailed",
    "deserialize_lift_result",
    "lift_cache_key",
    "lift_cache_refusals",
    "serialize_lift_result",
]
