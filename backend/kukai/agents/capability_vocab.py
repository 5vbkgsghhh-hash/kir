"""Closed capability vocabulary — actions + object kinds + capability-topic
domain (capability-first RAG, Stage 2, per
/root/kukai-rag-audit/CAPABILITY_FIRST_RAG.md; domain added per
/root/kukai-rag-audit/ROUTER_REALLLM_REPORT.md's classifier output-contract
fix, /root/kukai-rag-audit/ROUTER_CONTRACT_FIX_REPORT.md).

The active Wiki release tags every recipe with a ``capability`` signature:
``action`` (one of
a closed 28-verb vocabulary), ``object_kinds`` (0+ of a closed 20-kind
vocabulary), and ``domain`` (one of a closed 16-value capability-TOPIC
vocabulary — e.g. ``architecture``/``mep``/``qc``/``views``/``sheets`` — NOT
to be confused with ``IntentClassifier``'s original 7-way Revit-DISCIPLINE
``domain`` enum, ``ARCH``/``STR``/``MEP``/``VIEW``/``PROJECT``/``FAMILY``/
``OTHER``; the two are different vocabularies for different purposes and
neither replaces the other). Stage 2 needs all three in three different
places — the LLM ``IntentClassifier``'s schema validation (agents layer), its
deterministic ``quick_classify`` fallback (agents layer), and the
capability-resolve retrieval stage / Capability→Page Router (rag/nav layer)
— so this module is the single source of truth all three import, rather than
hand-copied lists that would silently drift out of sync with each other or
with the corpus.

Read PROGRAMMATICALLY from the versioned Wiki capability catalogue (never hardcoded as the primary
source — an explicit instruction from the brief: "read them programmatically,
don't hardcode a possibly-stale list"), cached on (path, mtime, size) so a
corpus edit is picked up without a restart. The module-level frozensets below
are a FALLBACK ONLY, used exactly when the live read fails (file missing/
unreadable/malformed/empty of capability data) — snapshotted from
CAPCAT_REPORT.md's verification on 2026-07-08 so a broken data file degrades
to a known-good vocabulary instead of an empty one (which would make the
capability-resolve stage think NO action is ever "known" and silently
no-op the whole stage).

Layering note: this module is intentionally dependency-light (stdlib only —
json + Path) and lives in ``kukai.agents``, the LOWER layer.
``kukai.rag.converse_gate`` already imports FROM
``kukai.agents.intent_rules`` (established precedent: rag depends on agents,
never the reverse), so a rag module importing this file is safe; this file
must never import anything from ``kukai.rag`` — that would create the cycle
the layering exists to avoid.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback vocab (used only if the live read below fails) — snapshot of what
# CAPCAT_REPORT.md verified is actually present in data/revit_api_db.json's
# capability.action / capability.object_kinds values across all 479 recipes.
# ---------------------------------------------------------------------------

ACTION_VOCAB_FALLBACK: frozenset[str] = frozenset({
    "annotate", "change_type", "check", "color_scheme", "consult",
    "coordinate", "count", "create", "create_view", "delete", "dimension",
    "export", "find_select", "inspect", "isolate", "join", "link", "list",
    "modify_geometry", "override_graphics", "place", "purge", "quantify",
    "rename", "schedule", "set_param", "tag", "transform",
})

OBJECT_KIND_VOCAB_FALLBACK: frozenset[str] = frozenset({
    "category", "type", "family", "element", "mark", "level", "grid", "view",
    "sheet", "material", "parameter", "workset", "room_space", "link",
    "assembly", "wall_layer", "mep_system", "rebar", "global_param", "phase",
})

# ADDITIVE (ROUTER_CONTRACT_FIX_REPORT.md): the 16-way capability-TOPIC domain
# — this is what the wiki pages (nav/wiki_query.py Page.domain) and
# capability_catalog.json key routing on, and is DISTINCT from
# IntentClassifier's original 7-way Revit-discipline `domain` enum
# (ARCH/STR/MEP/VIEW/PROJECT/FAMILY/OTHER). Snapshot verified against both
# ``data/revit_api_db.json``'s 479 ``capability.domain`` values AND the 68
# live wiki pages' frontmatter ``domain:`` values on 2026-07-09 — the two
# corpora agree exactly on this 16-value set.
DOMAIN_VOCAB_FALLBACK: frozenset[str] = frozenset({
    "annotation", "architecture", "coordination", "data", "electrical",
    "families", "general", "geometry", "graphics", "mep", "qc", "schedules",
    "sheets", "structure", "views", "worksharing",
})

# ---------------------------------------------------------------------------
# Fail-open intent -> action map (brief §Part-2a step 1): the ONE place this
# mapping is defined. Used by:
#   * IntentClassifier.parse_response — when the LLM omits `action` (or
#     returns something outside the closed vocab), derive it from the
#     (already-validated) `intent` field instead of raising.
#   * intent_rules.quick_classify — the deterministic fallback classifier
#     emits a best-effort `action` from the SAME map (its `intent` buckets
#     are the same 11-way enum as IntentClassifier's).
# "modify" intentionally maps to the safe default `set_param` (per brief) —
# a bare "modify" carries no signal about WHICH kind of modification
# (parameter vs geometry vs transform vs type-swap), and set_param is both
# the most common modify-recipe action in the corpus and the least
# destructive guess.
# ---------------------------------------------------------------------------

_INTENT_TO_ACTION: dict[str, str] = {
    "count": "count",
    "delete": "delete",
    "schedule": "schedule",
    "tag": "tag",
    "export": "export",
    "filter": "find_select",
    "list": "list",
    "create": "create",
    "modify": "set_param",
    "diagnose": "check",
    "converse": "consult",
}

_DEFAULT_ACTION = "set_param"


def derive_action_from_intent(intent: Optional[str]) -> str:
    """Deterministic intent -> action fallback. Never raises, never empty.

    Unknown/blank/None intent -> ``_DEFAULT_ACTION`` (the same safe default
    "modify" itself maps to) rather than raising — this function backstops
    BOTH the LLM path (fail-open on a missing/invalid action) and the
    rules-only path (no LLM ever ran), so it must be total.
    """
    key = (intent or "").strip().lower()
    return _INTENT_TO_ACTION.get(key, _DEFAULT_ACTION)


# ---------------------------------------------------------------------------
# Live vocab loader — cached on (path, mtime_ns, size), same discipline as
# kukai.rag.retrieval._rank_policy_path / active_rank_policy.
# ---------------------------------------------------------------------------

_CACHE: dict = {"sig": None, "actions": None, "kinds": None, "domains": None}


def _catalog_path() -> Path:
    override = (os.getenv("KUKAI_CAPABILITY_CATALOG_FILE") or "").strip()
    if override:
        return Path(override)
    from kukai.knowledge.release import current_release

    return current_release().wiki_root / "capability_catalog.json"


def _load_live_vocab() -> tuple[Optional[frozenset], Optional[frozenset], Optional[frozenset]]:
    """Read (action_vocab, object_kind_vocab, domain_vocab) straight from the
    corpus's per-recipe ``capability`` block (``action`` + ``object_kinds`` +
    ``domain`` — the 16-way capability-topic domain, NOT the classifier's
    separate 7-way discipline `domain` enum).

    Returns ``(None, None, None)`` on ANY problem (missing file, bad JSON, no
    recipe carries a `capability` block yet) — callers fall back to the
    frozen snapshot. Never raises.
    """
    try:
        p = _catalog_path()
        st = p.stat()
        sig = (str(p), st.st_mtime_ns, st.st_size)
        if _CACHE["sig"] == sig:
            return _CACHE["actions"], _CACHE["kinds"], _CACHE["domains"]

        doc = json.loads(p.read_text(encoding="utf-8"))
        actions: set[str] = set()
        kinds: set[str] = set()
        domains: set[str] = set()
        recipes = doc.get("recipes") or {}
        if not isinstance(recipes, dict):
            raise ValueError("capability_catalog.recipes must be an object")
        for cap in recipes.values():
            if not isinstance(cap, dict):
                continue
            action = cap.get("action")
            if isinstance(action, str) and action.strip():
                actions.add(action.strip().lower())
            for kind in (cap.get("object_kinds") or []):
                if isinstance(kind, str) and kind.strip():
                    kinds.add(kind.strip().lower())
            domain = cap.get("domain")
            if isinstance(domain, str) and domain.strip():
                domains.add(domain.strip().lower())

        result = (
            frozenset(actions) if actions else None,
            frozenset(kinds) if kinds else None,
            frozenset(domains) if domains else None,
        )
        _CACHE["sig"] = sig
        _CACHE["actions"], _CACHE["kinds"], _CACHE["domains"] = result
        return result
    except Exception:
        logger.exception(
            "capability_vocab: live read of versioned capability_catalog.json failed — "
            "falling back to the frozen 2026-07-08/09 snapshot vocab",
        )
        return None, None, None


def action_vocab() -> frozenset[str]:
    """The closed action vocabulary — live from the corpus, else the fallback."""
    actions, _, _ = _load_live_vocab()
    return actions if actions else ACTION_VOCAB_FALLBACK


def object_kind_vocab() -> frozenset[str]:
    """The closed object-kind vocabulary — live from the corpus, else the fallback."""
    _, kinds, _ = _load_live_vocab()
    return kinds if kinds else OBJECT_KIND_VOCAB_FALLBACK


def capability_domain_vocab() -> frozenset[str]:
    """The closed 16-way capability-TOPIC domain vocabulary — live from the
    corpus, else the fallback. This is the vocabulary the Capability→Page
    Router indexes wiki pages on (``nav/wiki_query.py`` ``Page.domain``); it
    is DISTINCT from ``IntentClassifier``'s original 7-way Revit-discipline
    `domain` field (ARCH/STR/MEP/VIEW/PROJECT/FAMILY/OTHER), which this
    function does not touch or replace.
    """
    _, _, domains = _load_live_vocab()
    return domains if domains else DOMAIN_VOCAB_FALLBACK


def reset_cache() -> None:
    """Test hook: forget the cached (path, mtime, size) -> vocab mapping."""
    _CACHE["sig"] = None
    _CACHE["actions"] = None
    _CACHE["kinds"] = None
    _CACHE["domains"] = None
