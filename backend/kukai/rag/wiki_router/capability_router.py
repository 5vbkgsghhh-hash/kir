#!/usr/bin/env python3
"""capability_router.py — Capability→Page Router.

PROD PORT (2026-07-09) of /root/kukai-wiki/nav/capability_router.py. Dormant
module: only ever imported/exercised via kukai.rag.wiki_router.adapter,
itself only exercised when KUKAI_RAG_WIKI_ROUTER is "shadow" or "on" (see
kukai/llm/prompts.py). With the flag unset/off this module is never imported
by the live request path.

Port scope: PATHS ONLY (CAPABILITY_CATALOG_PATH resolves against the prod
data tree; the ``import wiki_query`` sys.path hack is replaced by a plain
package-relative import since this file already lives inside the
kukai.rag.wiki_router package; the quick_classify guarded-import no longer
needs its own sys.path hack for the same reason). ALL routing/scoring logic
below (soft-fusion, SOFT_W_DOMAIN/SOFT_W_OBJECT, route_type derivation,
oracle-frame derivation) is byte-identical to the source file — do not
re-tune scoring here (see wiring spec + [[sonnet-edits-opus-authors-recipes]]).

Locked architecture: /root/kukai-rag-audit/CAPABILITY_ROUTED_WIKI.md
Measurement report:   /root/kukai-rag-audit/ROUTER_AB_REPORT.md

This is Stage 2's capability-resolve mechanism (built for recipes) pointed
at wiki PAGES instead: an OperationFrame ``{action, object_kinds, domain}``
is routed to the page(s) whose frontmatter ``capabilities`` (parsed as
``action×object`` pairs) + ``domain`` contain that frame, via a
deterministic O(1) index lookup. No embedding, no BM25, no fusion, no
rerank — the semantic step already happened once, in the classifier that
produced the frame.

This file is NEW and does not modify ``nav/wiki_query.py`` (owned
concurrently by another workstream) — it *imports* that module read-only for
two pieces of existing, working scaffolding, reused rather than
reinvented:
  1. ``wiki_query.load_pages()`` — the frontmatter/body page parser. The
     routing table is an index built ON TOP of the already-parsed
     ``Page.capabilities`` / ``Page.domain``, nothing is re-parsed here.
  2. ``wiki_query.score_page()`` / ``wiki_query.navigate()`` — the
     trigger+overview keyword scorer, reused for (a) the FUZZY FALLBACK when
     the classifier frame is missing/low-confidence/unroutable, and (b)
     relevance-ranking when a routing-table bucket contains more than one
     candidate page (breaking the tie by the same signal wiki_query already
     uses, instead of an arbitrary/alphabetical pick).

Confidence gate (see CAPABILITY_ROUTED_WIKI.md "Риск и страховка"): a wrong
but confident frame -> a confidently wrong page, which is worse than RAG's
soft top-10. ``quick_classify``'s own conservative default action is
``set_param`` (see intent_rules.py: the module-level default AND the
"modify"-intent path both resolve to it via
``capability_vocab.derive_action_from_intent`` — the two cases are
structurally indistinguishable from the returned metadata alone), so an
action of ``set_param`` or ``None`` is treated as "the classifier had no
real signal" and routed through the fuzzy fallback instead of the
deterministic table, exactly as designed.

SOFT-FUSION scoring (2026-07-09, ROUTER_V3_REPORT.md; supersedes the
2026-07-09 "contract fix" batch's cascading hard-filter tiers — see
ROUTER_CONTRACT_FIX_REPORT.md §5 for the decisive measurement that motivated
this). ``action`` remains the one HARD gate on the candidate pool — a query
only reaches ``capability_gap`` when no page anywhere carries that action
(config-E in the contract-fix report showed action-only filtering is the
single strongest individual signal, 64.5%, stronger than any config that
also hard-filtered on domain and/or object_kinds). Within the action-gated
pool, ``capability_domain`` and ``object_kinds`` are pure SCORE BONUSES over
wiki_query's content/trigger relevance score — a page is never EXCLUDED for
mismatching a predicted domain or object_kind, it can only fail to earn that
bonus. This matters because the classifier's ``capability_domain`` is only
~68% accurate against the oracle ground truth (measured in
ROUTER_CONTRACT_FIX_REPORT.md §5): hard-filtering on it threw away the
correct page in the ~32% wrong case even when content ranking would have
found it; fusing it as a bonus lets a wrong domain merely fail to help
instead of actively hurting. Weights tuned on the 292-query battery (see
ROUTER_V3_REPORT.md §"weights"): ``SOFT_W_DOMAIN`` / ``SOFT_W_OBJECT``
below. ``route_type`` labels (``exact`` / ``relaxed_domain`` /
``relaxed_object`` / ``relaxed_action``) are now DESCRIPTIVE of which bonus
the winning page earned, not the name of a hard-filter tier it survived —
diagnostic value preserved, mechanism changed.

CLI mirrors wiki_query.py / the RAG harness:
    capability_router.py --queries <in.jsonl> --out <out.jsonl> \
        [--frame-mode quick|oracle] [--battery <battery.jsonl for oracle expect>]

Per-query output record:
    {id, query, frame, routed_pages, route_type, inject_chars,
     first_recipe, latency_ms, error}
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import wiki_query  # noqa: E402  -- fuzzy fallback + page model, NOT modified here

logger = logging.getLogger(__name__)

# Same wiki-data root wiki_query already resolved (env-overridable via
# KUKAI_WIKI_ROOT) — reused here instead of re-deriving it, so both modules
# always agree on where the corpus lives.
WIKI_ROOT = wiki_query.WIKI_ROOT
CAPABILITY_CATALOG_PATH = os.environ.get("KUKAI_CAPABILITY_CATALOG") or os.path.join(
    WIKI_ROOT, "capability_catalog.json",
)

INJECT_BUDGET_SINGLE = 9000
INJECT_BUDGET_COMPOSITE = 16000
MAX_ROUTED_PAGES = 2  # spec: single page, or up to 2 for composite/relaxed-multi

# ---------------------------------------------------------------------------
# quick_classify import (read-only, from the live prod tree) — same guarded
# pattern as wiki_query.py's own import, so a prod-tree hiccup degrades to
# "no frame" (-> fuzzy fallback for everything) rather than crashing the run.
# No sys.path hack needed: this file already lives inside the prod package.
# ---------------------------------------------------------------------------
try:
    from kukai.agents.intent_rules import quick_classify as _quick_classify  # type: ignore
except Exception:
    _quick_classify = None

# The low-confidence sentinel: quick_classify's hardcoded default action AND
# the action any unmatched/"modify" query resolves to (see module docstring).
LOW_CONFIDENCE_ACTIONS = {"set_param", None}

# ---------------------------------------------------------------------------
# Soft-fusion bonus weights (ROUTER_V3_REPORT.md) — chosen by a small grid
# sweep on the 292-query battery over the real-v2 classifier frames (same
# methodology as ROUTER_CONTRACT_FIX_REPORT.md §5's sweep, re-run against
# THIS file's unified scoring pass rather than the old tiered cascade).
# Flat bonuses (not scaled by overlap count) — see module docstring: a
# domain/object match either earns its bonus once or it doesn't, matching
# how the contract-fix report's own sweep table was parameterized.
#
# ENV-OVERRIDABLE (Lever-2 measurement work, LEVER2_REPORT.md):
# ``KUKAI_WIKI_W_DOMAIN`` / ``KUKAI_WIKI_W_OBJECT`` let an offline sweep or a
# future flag-gated rollout pick a different pair WITHOUT editing this file,
# read once at import time (this module is only ever imported inside a
# dormant, per-process offline/shadow path — see module docstring — so
# "read once at import" is equivalent to "read once per run", never a stale
# read against a long-lived prod process). Unset/unparseable env -> exactly
# the values above (byte-identical default behavior); a value that fails
# ``float()`` is logged and ignored (fail-open), never raises.
# ---------------------------------------------------------------------------
def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        print(f"capability_router: ignoring unparseable {name}={raw!r}, using default {default}",
              file=sys.stderr)
        return default


SOFT_W_DOMAIN = _env_float("KUKAI_WIKI_W_DOMAIN", 2.0)
SOFT_W_OBJECT = _env_float("KUKAI_WIKI_W_OBJECT", 0.0)

# Router v4: generated lemma/IDF evidence over page triggers + every recipe's
# Use-when text. The classifier frame is a strong bonus, never a hard gate.
EVIDENCE_W_ACTION = _env_float("KUKAI_WIKI_EVIDENCE_W_ACTION", 10.0)
EVIDENCE_W_DOMAIN = _env_float("KUKAI_WIKI_EVIDENCE_W_DOMAIN", 5.0)
EVIDENCE_W_OBJECT = _env_float("KUKAI_WIKI_EVIDENCE_W_OBJECT", 2.0)
EVIDENCE_ACTION_MISS = _env_float("KUKAI_WIKI_EVIDENCE_ACTION_MISS", 2.0)
EVIDENCE_W_TRIGGER_PHRASE = _env_float("KUKAI_WIKI_EVIDENCE_W_TRIGGER_PHRASE", 8.0)
EVIDENCE_W_TRIGGER_EXTRA_TOKEN = _env_float(
    "KUKAI_WIKI_EVIDENCE_W_TRIGGER_EXTRA_TOKEN", 2.0,
)


def evidence_router_enabled() -> bool:
    return os.getenv("KUKAI_WIKI_ROUTER_V4", "1").strip().lower() not in {"0", "off", "false", "no"}


# ---------------------------------------------------------------------------
# Oracle-frame token matching — SAME methodology as
# exec_scripts/navlift_eval.py's `is_hit` (the validated matcher behind the
# 60.9%/77.5% report numbers), reused here for a different purpose: instead
# of a boolean hit test, rank ALL 479 catalog recipes by shared-token overlap
# with `expect` and take the capability of the best match(es) as the "if the
# classifier were perfect" ground-truth frame.
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-zA-Zа-яёА-ЯЁ0-9]+")
_STOP = {
    "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "by",
    "with", "from", "is", "are", "at", "as", "it", "per", "via", "this",
    "that", "not", "any", "be", "no",
}


def meaningful_tokens(s: str) -> set[str]:
    toks = _TOKEN_RE.findall((s or "").lower())
    return {t for t in toks if len(t) >= 3 and t not in _STOP}


def _fold_plural(t: str) -> str:
    """Light singular/plural fold for ENGLISH tokens only (`expect` and
    recipe names are English prose) — NOT a general stemmer, just enough to
    stop "totals"!="total" / "elements"!="element" from hiding an otherwise
    exact conceptual match. Found necessary during build: without it,
    ``expect="length totals ... wall length calc"`` missed the correct
    recipe ("Calculate total length") on the "totals"/"total" mismatch
    alone and a coincidental 2-token match won instead (see
    ROUTER_AB_REPORT.md). Used ONLY for oracle-frame derivation in this
    file, never for the battery accuracy grader (which intentionally
    reuses navlift_eval.is_hit byte-for-byte to stay comparable to the
    prior WIKI_VS_RAG_REPORT.md numbers).
    """
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _norm_set(tokens: set[str]) -> set[str]:
    return {_fold_plural(t) for t in tokens}


def _load_capability_catalog() -> dict[str, dict]:
    with open(CAPABILITY_CATALOG_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    return doc["recipes"]


# ---------------------------------------------------------------------------
# IDF index over recipe-name tokens — built once per catalog (cached by
# object identity) and reused by every `derive_oracle_frame` call.
#
# Found necessary during build: an EARLIER version ranked candidates by raw
# precision (shared / name-token-count) alone, which systematically favors
# SHORT generic names over long specific ones. Concretely,
# expect="create section view" scored "Create plan view" (2/3 tokens shared,
# precision 0.67) ABOVE "Create section, elevation, 3D view, sheet +
# viewport, set view range and crop" (3/10 tokens shared incl. the one
# genuinely distinctive word "section", precision 0.30) — the long name is
# the obviously-correct match (it literally contains "section") but lost on
# a length-blind precision metric alone. Weighting each shared token by its
# INVERSE document frequency across all 479 recipe names fixes this: a rare,
# specific word like "section" (appears in a handful of names) outweighs
# common words like "create"/"view" (appear in dozens), independent of how
# long the surrounding recipe name is.
# ---------------------------------------------------------------------------
_IDF_CACHE: dict[int, tuple[dict[str, frozenset], dict[str, float]]] = {}


def _idf_index(catalog: dict[str, dict]) -> tuple[dict[str, frozenset], dict[str, float]]:
    cached = _IDF_CACHE.get(id(catalog))
    if cached is not None:
        return cached
    name_tokens: dict[str, frozenset] = {}
    df: dict[str, int] = defaultdict(int)
    for name in catalog:
        toks = frozenset(_norm_set(meaningful_tokens(name)))
        name_tokens[name] = toks
        for t in toks:
            df[t] += 1
    n_names = max(len(catalog), 1)
    import math
    idf = {t: math.log(n_names / c) + 1.0 for t, c in df.items()}  # +1 floor: even a common token contributes something
    result = (name_tokens, idf)
    _IDF_CACHE[id(catalog)] = result
    return result


def _oracle_eligible(e_tokens: set[str], n_tokens: set[str]) -> tuple[bool, set[str]]:
    """Candidate-acceptance bar for oracle matching. Starts from the SAME
    bar as the validated grader (`navlift_eval.is_hit`: >=2 shared tokens,
    OR 1 shared token of length >=6) but ADDS a precision floor on the
    single-token case (shared token must be >=50% of the candidate name's
    own tokens) — without it, a long/generic recipe name that merely
    CONTAINS one 6+ char word in common with `expect` (e.g. "levels" inside
    "Create vertical shaft opening across levels") wins purely on token
    length, which is fine for the grader's generous is-it-plausibly-a-hit
    test but too weak to justify asserting the recipe's capability as
    ground truth here — found and fixed during build via a 25-sample manual
    spot check (see ROUTER_AB_REPORT.md).
    """
    e_norm, n_norm = _norm_set(e_tokens), _norm_set(n_tokens)
    shared = e_norm & n_norm
    if len(shared) >= 2:
        return True, shared
    if len(shared) == 1:
        tok = next(iter(shared))
        precision = 1 / max(len(n_norm), 1)
        if len(tok) >= 6 and precision >= 0.5:
            return True, shared
    return False, shared


def _oracle_prefix_bonus(e_tokens: set[str], n_tokens: set[str], shared: set[str]) -> int:
    """Tie-break only (never eligibility): counts cheap stem-ish matches
    (e.g. "counting" vs "count") among the NON-shared remainder, so a
    morphological near-match nudges the ranking without a real stemmer."""
    remaining_e = e_tokens - shared
    remaining_n = n_tokens - shared
    bonus = 0
    for et in remaining_e:
        for nt in remaining_n:
            if len(et) >= 4 and len(nt) >= 4 and (et.startswith(nt) or nt.startswith(et)):
                bonus += 1
    return bonus


def derive_oracle_frame(expect: str, catalog: dict[str, dict]) -> dict | list[dict] | None:
    """Best-matching recipe(s) for `expect` (by IDF-weighted shared-token
    overlap with the recipe NAME -- see `_idf_index` docstring for why raw
    precision alone was wrong) -> their capability {action, object_kinds,
    domain} as the ground-truth OperationFrame. Returns None when no recipe
    clears the acceptance bar (`_oracle_eligible`) -- an honest "oracle
    itself has no signal for this expect string" -> fuzzy fallback, not a
    forced guess.

    Ranking key: (idf_sum, shared_count, prefix_bonus, name) descending on
    the first three. Multiple names tied at the top with the SAME (action,
    domain) signature collapse to one frame (dedup by signature, not by
    recipe name); a genuine tie across *different* signatures produces a
    composite (>1) frame list, capped at ``MAX_ROUTED_PAGES`` distinct
    signatures (stable order: name-sorted).
    """
    e_tokens = meaningful_tokens(expect)
    if not e_tokens:
        return None
    name_tokens, idf = _idf_index(catalog)
    e_norm = _norm_set(e_tokens)
    scored: list[tuple[float, int, int, str]] = []
    for name, cap in catalog.items():
        n_norm = name_tokens[name]
        ok, shared_norm = _oracle_eligible(e_tokens, n_norm)
        if not ok:
            continue
        idf_sum = sum(idf.get(t, 1.0) for t in shared_norm)
        pb = _oracle_prefix_bonus(e_norm, n_norm, shared_norm)
        scored.append((idf_sum, len(shared_norm), pb, name))
    if not scored:
        return None
    scored.sort(key=lambda r: (-r[0], -r[1], -r[2], r[3]))
    best_key = scored[0][:3]
    top = sorted(name for idf_sum, shared, pb, name in scored if (idf_sum, shared, pb) == best_key)

    seen_sigs: dict[tuple, dict] = {}
    for name in top:
        cap = catalog[name]
        domain = cap.get("domain")
        action = cap.get("action")
        obj_kinds = cap.get("object_kinds") or []
        sig = (action, domain)
        if sig not in seen_sigs:
            seen_sigs[sig] = {"action": action, "object_kinds": obj_kinds, "domain": domain}
        else:
            # widen object_kinds under the same (action, domain) signature
            existing = set(seen_sigs[sig]["object_kinds"])
            existing.update(obj_kinds)
            seen_sigs[sig]["object_kinds"] = sorted(existing)
        if len(seen_sigs) >= MAX_ROUTED_PAGES:
            break

    frames = list(seen_sigs.values())
    return frames[0] if len(frames) == 1 else frames


def derive_quick_frame(query: str) -> dict | None:
    """OperationFrame from the deterministic prod classifier (the offline
    FLOOR — Stage 2.1 reaches 18/28 actions, empty object_kinds always,
    domain always the literal placeholder "OTHER" -- quick_classify never
    sets a real domain, see intent_rules.py: no branch calls
    ``meta.update(domain=...)``). Returns None if the prod import failed.
    """
    if _quick_classify is None:
        return None
    try:
        meta = _quick_classify(query)
    except Exception:
        return None
    domain = meta.get("domain")
    if domain in (None, "", "OTHER"):
        domain = None
    return {
        "action": meta.get("action"),
        "object_kinds": [k for k in (meta.get("object_kinds") or []) if k],
        "domain": domain,
        "intent": meta.get("intent"),
        "complexity": meta.get("complexity"),
    }


# ---------------------------------------------------------------------------
# Routing table: (action, object, domain) / (action, domain) / (action) ->
# set of page slugs. Built once per process from wiki_query.load_pages()'s
# already-parsed Page.capabilities ("action×object" strings) + Page.domain.
# ---------------------------------------------------------------------------
@dataclass
class RoutingTable:
    by_full: dict = field(default_factory=dict)
    by_action_domain: dict = field(default_factory=dict)
    by_action_object: dict = field(default_factory=dict)
    by_action: dict = field(default_factory=dict)
    # NEW (soft-fusion, ROUTER_V3_REPORT.md): (action, slug) -> the set of
    # object_kinds THAT ACTION carries on THAT page (a page can carry the
    # same action with different objects across several capability tuples,
    # e.g. "transform×element" + "transform×type" on the same page) — used
    # to score the object-overlap bonus per candidate without conflating a
    # page's unrelated actions' objects into the match.
    by_action_page_objects: dict = field(default_factory=dict)
    actions_with_pages: set = field(default_factory=set)
    evidence_index: Any = None


def build_routing_table(pages: dict[str, "wiki_query.Page"]) -> RoutingTable:
    by_full: dict = defaultdict(set)
    by_action_domain: dict = defaultdict(set)
    by_action_object: dict = defaultdict(set)
    by_action: dict = defaultdict(set)
    by_action_page_objects: dict = defaultdict(set)
    for slug, page in pages.items():
        domain = page.domain
        for raw_cap in page.capabilities:
            try:
                from kukai.knowledge.schema import parse_capability

                parsed = parse_capability(raw_cap, allow_bare_action=True)
                action = parsed.action
                objects = parsed.object_kinds or ("-",)
            except Exception:
                action = raw_cap.split("×", 1)[0].strip()
                objects = ("-",)
            if not action:
                continue
            by_action_domain[(action, domain)].add(slug)
            for obj in objects:
                by_full[(action, obj, domain)].add(slug)
                if obj != "-":
                    by_action_object[(action, obj)].add(slug)
                    by_action_page_objects[(action, slug)].add(obj)
            by_action[action].add(slug)
    evidence_index = None
    if pages and evidence_router_enabled():
        try:
            from kukai.knowledge.routing_index import load_routing_index

            first_page = Path(next(iter(pages.values())).path)
            index_path = first_page.parents[2] / "routing_index.json"
            candidate = load_routing_index(index_path)
            if set(candidate.pages) != set(pages):
                raise ValueError("routing index page set differs from parsed Wiki pages")
            for slug, page in pages.items():
                indexed_names = [card.name for card in candidate.pages[slug].cards]
                if indexed_names != [card.name for card in page.cards]:
                    raise ValueError(f"routing index card drift on {slug}")
            evidence_index = candidate
        except FileNotFoundError:
            logger.info("Wiki routing_index.json absent; using v3 compatibility router")
        except Exception as exc:
            logger.warning("Wiki evidence index unavailable; using v3 compatibility router: %s", exc)
    return RoutingTable(
        by_full=dict(by_full),
        by_action_domain=dict(by_action_domain),
        by_action_object=dict(by_action_object),
        by_action=dict(by_action),
        by_action_page_objects=dict(by_action_page_objects),
        actions_with_pages=set(by_action.keys()),
        evidence_index=evidence_index,
    )


def _rank_pages(candidates: set[str], pages: dict, q_tokens: set[str], q_tokens_list: list[str]) -> list[str]:
    """Break a multi-page tie using wiki_query's own trigger+overview scorer
    (action=None -> the classifier boost term is inert, so this is a pure
    content-relevance re-rank). Retained for callers outside `route_single`
    (e.g. ad-hoc analysis scripts) — `route_single` itself now does its own
    fused scoring inline (see `_score_candidate` / `route_single` below)."""
    scored = []
    for slug in candidates:
        page = pages[slug]
        total, *_ = wiki_query.score_page(page, q_tokens, q_tokens_list, None)
        scored.append((total, slug))
    scored.sort(key=lambda r: (-r[0], r[1]))
    return [slug for _, slug in scored]


def route_single(
    action: str | None,
    object_kinds: list[str] | None,
    domain: str | None,
    table: RoutingTable,
    pages: dict,
    q_tokens: set[str],
    q_tokens_list: list[str],
    w_domain: float = SOFT_W_DOMAIN,
    w_object: float = SOFT_W_OBJECT,
    evidence_tokens: set[str] | None = None,
) -> tuple[list[str], str]:
    """Route ONE OperationFrame -> ([best page slug] or [], route_type),
    via SOFT-FUSION scoring (ROUTER_V3_REPORT.md; see module docstring for
    why this replaced the earlier cascading hard-filter tiers).

    `action` is the one HARD gate: the candidate pool is every page that
    carries `action` anywhere (`table.by_action[action]`) — no page outside
    that pool is ever considered. "capability_gap" fires only when `action`
    has NO page anywhere in the routing table (the honest no-capability
    signal) — with full 28/28-action page coverage in this corpus this
    should be rare/never for an in-vocabulary action; reported as a real
    measurement, not forced.

    Within the action-gated pool, EVERY candidate is scored on ONE fused
    scale — content/trigger relevance (wiki_query.score_page) plus a flat
    bonus if the page's domain equals the predicted `domain`, plus a flat
    bonus if the page carries `action` with at least one of the predicted
    `object_kinds` — and the top scorer wins. No candidate is ever EXCLUDED
    for mismatching `domain` or `object_kinds`; a wrong prediction on either
    just fails to earn its bonus, it never removes the right page from
    contention (that is the whole point of soft-fusion over the old
    exact/relaxed_domain/relaxed_object/relaxed_action cascade, which
    silently threw away the correct page whenever the ~68%-accurate
    `capability_domain` prediction was wrong).

    `route_type` is still one of {"exact", "relaxed_domain",
    "relaxed_object", "relaxed_action"} for backward-compatible reporting,
    but it is now DESCRIPTIVE of which bonus the WINNING page happened to
    earn (both domain+object / domain-only / object-only / neither), not the
    name of a hard-filter tier it survived.
    """
    if table.evidence_index is not None and evidence_router_enabled():
        tokens = evidence_tokens or set()
        objects = {value for value in (object_kinds or []) if value}
        scored: list[tuple[float, str, dict]] = []
        for slug in pages:
            score, facts = table.evidence_index.score_page(
                slug,
                tokens,
                action=action,
                object_kinds=objects,
                domain=domain,
                action_bonus=EVIDENCE_W_ACTION,
                domain_bonus=EVIDENCE_W_DOMAIN,
                object_bonus=EVIDENCE_W_OBJECT,
                action_miss_penalty=EVIDENCE_ACTION_MISS,
                trigger_phrase_bonus=EVIDENCE_W_TRIGGER_PHRASE,
                trigger_extra_token_bonus=EVIDENCE_W_TRIGGER_EXTRA_TOKEN,
            )
            scored.append((score, slug, facts))
        if not scored:
            return [], "capability_gap"
        scored.sort(key=lambda row: (-row[0], row[1]))
        _score, best_slug, facts = scored[0]
        if facts["action_hit"] and facts["domain_hit"] and facts["object_hit"]:
            route_type = "exact"
        elif facts["action_hit"] and facts["domain_hit"]:
            route_type = "relaxed_domain"
        elif facts["action_hit"] and facts["object_hit"]:
            route_type = "relaxed_object"
        else:
            route_type = "relaxed_action"
        return [best_slug], route_type

    if not action or action not in table.actions_with_pages:
        return [], "capability_gap"

    candidates = table.by_action.get(action, set())
    if not candidates:
        return [], "capability_gap"

    obj_kinds = {o for o in (object_kinds or []) if o}

    scored: list[tuple[float, bool, bool, str]] = []
    for slug in candidates:
        page = pages[slug]
        content, *_ = wiki_query.score_page(page, q_tokens, q_tokens_list, None)
        dom_hit = bool(domain) and page.domain == domain
        page_objs = table.by_action_page_objects.get((action, slug), set())
        obj_hit = bool(obj_kinds & page_objs)
        total = content + (w_domain if dom_hit else 0.0) + (w_object if obj_hit else 0.0)
        scored.append((total, dom_hit, obj_hit, slug))

    # Tie-break: higher fused score first; among ties, prefer a domain hit,
    # then an object hit (so a genuine attribute match wins a pure-content
    # tie), then alphabetical slug for determinism.
    scored.sort(key=lambda r: (-r[0], not r[1], not r[2], r[3]))
    _best_total, best_dom, best_obj, best_slug = scored[0]

    if best_dom and best_obj:
        route_type = "exact"
    elif best_dom:
        route_type = "relaxed_domain"
    elif best_obj:
        route_type = "relaxed_object"
    else:
        route_type = "relaxed_action"

    return [best_slug], route_type


def route(
    frame: dict | list[dict] | None,
    query: str,
    table: RoutingTable,
    pages: dict,
) -> tuple[list[str], str, bool]:
    """Route a frame (or a composite list of frames) to page slugs.

    Returns (routed_slugs, route_type, used_fuzzy). Confidence gate: any
    sub-frame with a low-confidence/missing action sends the WHOLE query to
    the fuzzy fallback (a composite query is only as trustworthy as its
    least-confident leg). Empty frame list / total routing miss also falls
    back. `route_type` values: exact | relaxed_domain | relaxed_object |
    relaxed_action | composite | fallback | capability_gap.
    """
    q_tokens = wiki_query.tokenize(query)
    q_tokens_list = wiki_query.tokenize_list(query)

    frames: list[dict] = frame if isinstance(frame, list) else ([frame] if frame else [])

    low_confidence = {None} if table.evidence_index is not None else LOW_CONFIDENCE_ACTIONS
    if not frames or any((f.get("action") in low_confidence) for f in frames):
        top3, _ = wiki_query.navigate(pages, query)
        top1 = [top3[0][0]] if top3 else []
        return top1, "fallback", True

    evidence_tokens = (
        table.evidence_index.query_tokens(query)
        if table.evidence_index is not None and evidence_router_enabled()
        else None
    )
    sub_results = [
        route_single(
            f.get("action"), f.get("object_kinds"), f.get("domain"), table,
            pages, q_tokens, q_tokens_list, evidence_tokens=evidence_tokens,
        )
        for f in frames
    ]
    if all(rt == "capability_gap" for _, rt in sub_results):
        return [], "capability_gap", False

    collected: list[str] = []
    seen: set[str] = set()
    subtypes: list[str] = []
    for slugs, rt in sub_results:
        if rt != "capability_gap":
            subtypes.append(rt)
        for s in slugs:
            if s not in seen:
                seen.add(s)
                collected.append(s)

    if not collected:
        top3, _ = wiki_query.navigate(pages, query)
        top1 = [top3[0][0]] if top3 else []
        return top1, "fallback", True

    collected = collected[:MAX_ROUTED_PAGES]
    route_type = "composite" if len(frames) > 1 else subtypes[0]
    return collected, route_type, False


# ---------------------------------------------------------------------------
# Injection assembly — delegates the actual per-page trimming (rank Verified
# recipe cards by query overlap, drop Триггеры/See also first, keep least-
# relevant cards trimmed off the tail) to wiki_query.build_injection, which
# already implements exactly that policy. This file only decides the BUDGET
# SPLIT across 1-2 routed pages.
#
# `frame` (W2-B, 2026-07-11, /root/kukai-rag-audit/SPEC_W2B_card_rank.md):
# optional, default None, threaded straight through to each per-page
# wiki_query.build_injection(..., frame=frame) call — same pass-through
# discipline this file already uses for `revit_version` was NOT applied to
# (that one is Lever 1's, owned by adapter.py's own post-step; see that
# file), this is the analogous wiring for the frame-aware card-ranking
# bonus. Not this module's own routing frame (`route()` above already
# consumed `frame` for PAGE selection) — this is the SAME frame reused a
# second time, inside the chosen page(s), to rank which CARD wins
# `first_recipe`/the trimmed kept-set. Default None -> wiki_query.
# build_injection's own fail-open (flag off or no frame -> unchanged
# ranking) keeps this byte-identical to before W2-B.
# ---------------------------------------------------------------------------
def build_injection(
    routed_slugs: list[str], pages: dict, query: str, frame: dict | list[dict] | None = None,
    routing_index: Any = None, revit_version: str | None = None,
) -> tuple[str, str | None, int]:
    if not routed_slugs:
        return "", None, 0
    budget = INJECT_BUDGET_SINGLE if len(routed_slugs) == 1 else INJECT_BUDGET_COMPOSITE // len(routed_slugs)
    parts: list[str] = []
    first_recipe: str | None = None
    evidence_tokens = routing_index.query_tokens(query) if routing_index is not None else set()
    frames = frame if isinstance(frame, list) else ([frame] if isinstance(frame, dict) else [])
    for slug in routed_slugs:
        page = pages[slug]
        selected_frame = next(
            (item for item in frames if item.get("domain") == page.domain),
            frames[0] if frames else {},
        )
        card_order = None
        if routing_index is not None:
            card_order = routing_index.rank_cards(
                slug,
                evidence_tokens,
                action=selected_frame.get("action"),
                object_kinds=set(selected_frame.get("object_kinds") or []),
            )
        text, recipe, _trimmed = wiki_query.build_injection(
            page, query, budget, revit_version=revit_version,
            frame=selected_frame, card_order=card_order,
        )
        if first_recipe is None:
            first_recipe = recipe
        parts.append(text)
    injection = "\n---\n".join(parts)
    return injection, first_recipe, len(injection)


# ---------------------------------------------------------------------------
# Per-query processing / CLI
# ---------------------------------------------------------------------------
def process_query(
    pages: dict,
    table: RoutingTable,
    rec: dict,
    frame_mode: str,
    catalog: dict | None,
) -> dict:
    qid = rec.get("id")
    query = rec.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"id": qid, "query": query, "error": "missing/empty 'query'"}
    t0 = time.perf_counter()
    try:
        if frame_mode == "oracle":
            expect = rec.get("expect")
            if not expect:
                raise ValueError("oracle frame-mode requires an 'expect' field (battery only)")
            frame = derive_oracle_frame(expect, catalog)
        else:
            frame = derive_quick_frame(query)

        routed_slugs, route_type, used_fuzzy = route(frame, query, table, pages)
        injection, first_recipe, inject_chars = build_injection(
            routed_slugs, pages, query, frame=frame, routing_index=table.evidence_index,
        )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {
            "id": qid,
            "query": query,
            "frame_mode": frame_mode,
            "frame": frame,
            "routed_pages": [os.path.relpath(pages[s].path, WIKI_ROOT) for s in routed_slugs],
            "route_type": route_type,
            "used_fuzzy": used_fuzzy,
            "inject_chars": inject_chars,
            "first_recipe": first_recipe,
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as e:  # one query never kills the run
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {"id": qid, "query": query, "latency_ms": latency_ms, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", required=True, help="input JSONL with {id, query[, expect]} per line")
    ap.add_argument("--out", required=True, help="output JSONL path")
    ap.add_argument("--frame-mode", choices=["quick", "oracle"], default="quick",
                     help="quick = kukai.agents.intent_rules.quick_classify (floor); "
                          "oracle = derive ground-truth frame from battery 'expect' (ceiling)")
    args = ap.parse_args()

    pages = wiki_query.load_pages()
    if not pages:
        print(f"FATAL: no pages loaded", file=sys.stderr)
        return 1
    table = build_routing_table(pages)
    catalog = _load_capability_catalog() if args.frame_mode == "oracle" else None

    n_ok = n_err = 0
    with open(args.queries, encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception as e:
                fout.write(json.dumps({"error": f"bad input line: {e}"}, ensure_ascii=False) + "\n")
                n_err += 1
                continue
            out_rec = process_query(pages, table, rec, args.frame_mode, catalog)
            fout.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            fout.flush()
            if out_rec.get("error"):
                n_err += 1
            else:
                n_ok += 1

    print(f"capability_router: {n_ok} ok, {n_err} error, -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
