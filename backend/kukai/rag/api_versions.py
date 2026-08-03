"""Runtime accessor for ``data/api_versions.json`` — version-truth lookups
(plan 012, IRON 4 via IRON 5).

The JSON is the sparse diff of the per-version API surfaces (built by
``scripts/build_api_versions.py``): for each type and member that is NOT present
in every supported Revit version, it records ``{introduced, removed_in}``.

This module is the read path. It is lazy + cached and STRICTLY FAIL-OPEN: if the
artifact is missing or malformed, every helper degrades to "I know nothing"
(None / {}), and exactly ONE warning is logged — the version filter then becomes
a no-op, so retrieval behaves identically to a version-blind world. Article 9:
disclose, don't die. Positive facts only ever ADD a filter action; the absence
of a fact never removes an entry.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Mirrors the convention in kukai/llm/api_members.py:19 — parents[2] is the
# backend root, so the data dir resolves the same for both consumers.
_PATH = Path(__file__).resolve().parents[2] / "data" / "api_versions.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    """Load + cache the version-truth map. Missing/broken file → {} + 1 WARNING."""
    try:
        if not _PATH.exists():
            logger.warning(
                "api_versions.json not found at %s — version filter is a no-op "
                "(retrieval behaves version-blind)", _PATH,
            )
            return {}
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("api_versions.json is not an object — ignoring")
            return {}
        return data
    except Exception:
        logger.warning("Failed to load api_versions.json — version filter no-op", exc_info=True)
        return {}


def _types() -> dict:
    t = _load().get("types")
    return t if isinstance(t, dict) else {}


def _members() -> dict:
    m = _load().get("members")
    return m if isinstance(m, dict) else {}


def supported_versions() -> list[str]:
    """The ordered list of Revit versions the diff covers (floor first)."""
    sup = _load().get("supported")
    return list(sup) if isinstance(sup, list) else []


def type_removed_in(full_name: str) -> Optional[str]:
    """First Revit version (as ``"YYYY"``) in which ``full_name`` is ABSENT after
    having existed earlier; ``None`` if the type still exists / is unknown."""
    return (_types().get(full_name) or {}).get("removed_in")


def type_introduced(full_name: str) -> Optional[str]:
    """First Revit version in which ``full_name`` exists, if that is later than
    the support floor; ``None`` if it existed at the floor / is unknown."""
    return (_types().get(full_name) or {}).get("introduced")


@lru_cache(maxsize=1)
def _member_index() -> dict[str, dict[str, dict]]:
    """Per-type member-fact index, built ONCE: ``{type_full: {member: fact}}``.

    One pass over ``_members()``: each key splits at its LAST dot into
    ``(type_full, member)`` — exactly the pairs the historical O(M) prefix scan
    yielded, because a dotted member tail never survived that scan's leaf guard,
    and an undotted key can never match a ``type + "."`` prefix. Per-type
    insertion order preserves the file order of the member keys, so
    ``member_facts`` ordering is byte-identical to the scan it replaces.

    Same lru_cache discipline as ``_load`` (and derived from it, so it inherits
    the fail-open contract: no artifact → empty index). Nothing in production
    clears these caches; anything that ever clears ``_load`` must clear this too.
    """
    index: dict[str, dict[str, dict]] = {}
    for full, fact in _members().items():
        type_full, dot, member = full.rpartition(".")
        if not dot:
            continue  # undotted key: unreachable by any prefix scan — skip
        index.setdefault(type_full, {})[member] = fact
    return index


def member_facts(type_full_name: str) -> dict[str, dict]:
    """Member-level facts for one type: ``{member_name: {introduced?, removed_in?}}``.

    Keys are bare member names (no type prefix) so callers can match against the
    members they render. Only members whose applicability DIFFERS across versions
    appear; a member present in every living version of the type is absent here.

    O(1) lookup against the per-type index (hot render path: called per class
    entry per turn from rag_prompt). Returns a fresh shallow copy each call —
    same contract as the historical scan, and it keeps caller-side mutation
    from poisoning the cached index.
    """
    facts = _member_index().get(type_full_name)
    return dict(facts) if facts else {}
