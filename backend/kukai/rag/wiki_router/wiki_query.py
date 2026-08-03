#!/usr/bin/env python3
"""Deterministic navigator and injector for production KUKAI Wiki knowledge.

The immutable release selected by ``backend/knowledge/current.json`` is the
only automatic Revit corpus on the live request path.  Navigation, recipe
ranking and API grounding are local and deterministic; this module never
calls a model, an embedding endpoint or the retired vector index.

Port scope: PATHS ONLY (WIKI_ROOT/PAGES_GLOB resolve against the prod tree
now, and the quick_classify import no longer needs a sys.path hack because
this file already lives inside the prod backend package). All parsing/
scoring/injection logic below is byte-identical to the source file — see
CLAUDE.md rule [[sonnet-edits-opus-authors-recipes]] / the wiring spec: do
not re-tune scoring here.

CLI mirrors the RAG harness interface (see /root/kukai-rag-audit/harness/run_retrieval.py):

    wiki_query.py --queries <jsonl {id,query}> --out <out.jsonl>

For each input query this NAVIGATES (no LLM — this is the conservative floor;
see note below) to a single top-1 page, and INJECTS that page's content
(capped to ~9000 chars, the RAG median), emitting one JSONL record per query.

Navigation scoring (deterministic, no LLM):
  (a) PRIMARY, high weight: overlap of query tokens against the page's
      `triggers_ru` frontmatter list (exact-phrase match scores highest,
      all-tokens-present next, partial token overlap least).
  (b) SECONDARY: query tokens vs page title + "## Обзор" section text.
  (c) BOOST: `kukai.agents.intent_rules.quick_classify(query)["action"]`
      (imported READ-ONLY from the live prod tree) — if that action prefixes
      any of the page's frontmatter `capabilities` entries ("action×object"),
      add a fixed boost.

CAVEAT (report this honestly, per the audit brief): this is a hand-tuned
keyword/heuristic navigator, not an LLM doing index navigation. A real
LLM-driven "read index.md, pick the page" navigator would very likely score
HIGHER on accuracy than this deterministic floor (better paraphrase/synonym
handling, no reliance on literal trigger-phrase overlap) — this script
exists to measure the WORST-CASE wiki-navigation latency/accuracy, not the
ceiling.

Injection sizing: if the page's full body (title + Триггеры + Обзор +
Грабли и версии + Verified recipes + See also) fits under the char budget
(~9000), inject it whole. Otherwise DROP "## Триггеры" and "## See also"
first (lowest injection value — they are navigation/cross-link sugar, not
task-relevant content) and rank the "## Verified recipes" cards by
relevance to the query (name + "Use when (RU)" token overlap with the
query), keeping the best-matching cards first and trimming the
least-relevant cards off the tail until the remainder fits the budget.

Resilience: one failing query never kills the run — failures are caught
per-query and written as {id, query, error} records.

Timing: `nav_latency_ms` wraps the SAME scope as the RAG harness's `ms`
field (quick_classify + page scoring + top-k select + injection assembly),
for an apples-to-apples speed comparison.

Lever 1 (2026-07-11, /root/kukai-rag-audit/SPEC_lever1_api_ref.md): optional,
enabled-by-default (`KUKAI_WIKI_API_REF`) "Справка API" block appended
by `build_injection` after the page content, in whatever budget remains once
recipes are placed. Addresses the audited REF_GAP failure mode (ab_codegen
REPORT.md 2026-07-10): the wiki page alone is a connected recipe with no
API-member reference the way RAG's class-slots gave it, so the model
invents members (CS1061 22.8% wiki vs 13.8% RAG). Members are NEVER
invented here either — `build_api_reference` only surfaces members from
`kukai.llm.api_members.members_for` (version-correct, reuses the same
surface rag_prompt.py already trusts) or, fail-open when no version is
available / the class is unknown to that surface, an unfiltered top-N from
`data/revit_api_db.json`'s `classes` list. A class in neither source is
skipped, never fabricated. OFF by default: every existing caller (this
module's own CLI, and capability_router.build_injection, which still calls
`build_injection(page, query, budget)` with no `revit_version`) renders
byte-identical to before this change.

W2-B (2026-07-11, /root/kukai-rag-audit/SPEC_W2B_card_rank.md): optional,
enabled-by-default (`KUKAI_WIKI_CARD_RANK`) frame-aware Verified-recipe
CARD ranking inside `build_injection`. Diagnosed in
schedules_coverage_report.md: every schedule-domain page is >9K chars (always
the TRIMMED path below), where `first_recipe` was previously decided by pure
token overlap between the query and a card's name+use_when — a single
literal-case token match (e.g. "спецификацию") can hand the win to a wholly
unrelated card ("покажи спецификацию окон" -> the electrical-panel
spare-slot recipe on `schedules-configure.md`, reproduced verbatim in that
report). W2-B adds a capability-match BONUS as the primary sort key ahead of
the token tie-break: does the card's own `capability` ("action×object",
already parsed off its header) share the caller-supplied OperationFrame's
`action` / one of its `object_kinds`. This is a bonus, never a filter — a
non-matching card is never dropped from contention, only ranked lower (same
discipline as capability_router's SOFT_W_DOMAIN/SOFT_W_OBJECT fusion, see
that module's docstring on why ROUTER_V3 replaced hard filters with score
bonuses). OFF by default, or `frame` not given/empty, or any scoring error:
falls back to exactly today's token-overlap-only ranking — every existing
caller (this module's CLI, and capability_router.build_injection, whose own
`frame` parameter defaults to None) renders byte-identical to before this
change.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PROD PORT: resolve the wiki data root from this file's location inside the
# backend tree, overridable via KUKAI_WIKI_ROOT for tests/tooling. No
# sys.path hacks needed (this file already lives inside the kukai package).
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../kukai/rag/wiki_router
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))  # backend/
if os.environ.get("KUKAI_WIKI_ROOT"):
    WIKI_ROOT = os.environ["KUKAI_WIKI_ROOT"]
else:
    from kukai.knowledge.release import current_release as _current_knowledge_release

    WIKI_ROOT = str(_current_knowledge_release().wiki_root)
PAGES_GLOB = os.path.join(WIKI_ROOT, "pages", "*", "*.md")

INJECT_BUDGET_DEFAULT = 9000
PREVIEW_CHARS_DEFAULT = 600

# ---------------------------------------------------------------------------
# Lever 1 (SPEC_lever1_api_ref.md): API-reference block constants.
# ---------------------------------------------------------------------------
API_REF_FLAG_ENV = "KUKAI_WIKI_API_REF"
API_REF_MAX_CLASSES = 5
API_REF_MAX_MEMBERS = 10
API_REF_BUDGET_CHARS_DEFAULT = 1500  # hard cap on the whole block, regardless of remaining page budget
API_REF_MIN_BUDGET = 120  # below this, skip rather than render a near-empty/truncated block
API_REF_HEADER = "## Справка API (проверь члены/классы)\n"

# ---------------------------------------------------------------------------
# REF_GAP fix (2026-07-12, /root/kukai-rag-audit/ab_codegen/REFGAP_FIX_REPORT.md):
# enum VALUES + method SIGNATURES, layered on top of Lever 1 above. OFF by
# default -> build_api_reference renders byte-identical to pre-this-change
# output (see api_ref_enums_flag_enabled() / every new block below is
# strictly additive and gated by it).
# ---------------------------------------------------------------------------
API_REF_ENUMS_FLAG_ENV = "KUKAI_WIKI_APIREF_ENUMS"
API_REF_MAX_SIGNATURE_HINTS = 3   # "Class.Method" frontmatter hints resolved per page
# Only used in place of API_REF_BUDGET_CHARS_DEFAULT when the new flag is ON
# (see build_api_reference's final budget clamp) -- OFF renders with the
# original 1500 cap, unchanged.
API_REF_BUDGET_CHARS_ENUMS = 2500
# BuiltInParameter/BuiltInCategory/ViewType are used across nearly every
# domain (any parameter/category/view-filter recipe) but, being generic,
# essentially never appear in a page's own `api_classes` (that field is
# curated per-page-domain, e.g. rebar-reinforcement.md never mentions
# BuiltInParameter even though rebar recipes read/write parameters). Checked
# ALWAYS (not gated on frontmatter membership) but only ever CONTRIBUTES a
# block through the same relevance-gated `enum_values_for` used for explicit
# candidates -- a query with no real token-overlap against either enum's
# real values renders nothing extra, exactly as if the class were never
# checked at all.
# Cheapest (smallest real value-count) first: a page whose explicit
# api_classes already ate most of API_REF_BUDGET_CHARS_ENUMS should still
# have room left for a small, on-topic ViewType before the two genuinely
# large enums get their (much more expensive, still bounded) turn.
_UNIVERSAL_ENUM_WATCHLIST = ("ViewType", "BuiltInCategory", "BuiltInParameter")


def api_ref_enums_flag_enabled() -> bool:
    """KUKAI_WIKI_APIREF_ENUMS, default ON. Read at call time (not cached),
    same discipline as api_ref_flag_enabled() / every other KUKAI_* flag in
    this codebase. Independent of KUKAI_WIKI_API_REF's own gate in
    `_append_api_reference` (both must be truthy AND `revit_version` given
    for any of this module's new blocks to render -- see build_api_reference)."""
    return os.environ.get(API_REF_ENUMS_FLAG_ENV, "1").strip().lower() in ("1", "true", "on", "yes")


_SIG_HINT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$")


def _signature_hint_pairs(api_classes: list[str]) -> list[tuple[str, str]]:
    """Extract (ClassName, MethodName) pairs from `api_classes` raw entries
    shaped "Class.Method" (already an existing frontmatter convention, e.g.
    schedules-export.md's `"ViewSchedule.Export"` -- see
    `_candidate_base_names`, which today only uses this shape to seed TWO
    class-name candidates, discarding which half was the method). Order-
    preserving, deduplicated. Deliberately narrow: exactly one "." (a
    namespace-qualified FQN like "Autodesk.Revit.DB.ExtensibleStorage.Schema"
    has 3+ dots and is never mistaken for a method hint), both halves
    identifier-shaped. Never validated here -- `method_signatures_for` is the
    arbiter; a hint naming a nonexistent class/method just resolves to
    nothing later, same fail-open contract as `_candidate_base_names`."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for c in api_classes or []:
        if not isinstance(c, str):
            continue
        for piece in _PAREN_RE.sub("", c).split("/"):
            m = _SIG_HINT_RE.match(piece.strip())
            if not m:
                continue
            pair = (m.group(1), m.group(2))
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
    return out

# ---------------------------------------------------------------------------
# Read-only import of the prod deterministic intent classifier. Never raises:
# on ANY failure (module renamed/removed, etc.) quick_action falls back to
# None everywhere and navigation runs on triggers+overview alone — this
# script must never crash the whole batch over an optional signal.
# ---------------------------------------------------------------------------
try:
    from kukai.agents.intent_rules import quick_classify as _quick_classify  # type: ignore
except Exception:
    _quick_classify = None


def quick_action_for(query: str) -> str | None:
    if _quick_classify is None:
        return None
    try:
        meta = _quick_classify(query)
        return meta.get("action")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "и", "в", "во", "на", "по", "с", "со", "для", "как", "что", "это", "то",
    "а", "но", "или", "из", "за", "к", "ко", "у", "до", "от", "при", "же",
    "ли", "бы", "не", "нет", "есть", "все", "всех", "всей", "всего", "одну",
    "эту", "эта", "этот", "эти", "него", "нее", "них", "между", "над",
    "под", "о", "об", "про", "the", "a", "an", "of", "to", "in", "on",
    "for", "and", "or",
}


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return s


def tokenize(s: str) -> set[str]:
    toks = _TOKEN_RE.findall(norm_text(s))
    return {t for t in toks if t not in _STOPWORDS and len(t) > 1}


def tokenize_list(s: str) -> list[str]:
    """Order-preserving variant of `tokenize` (stopwords/length-filtered too)."""
    toks = _TOKEN_RE.findall(norm_text(s))
    return [t for t in toks if t not in _STOPWORDS and len(t) > 1]


def contains_contiguous(haystack: list[str], needle: list[str]) -> bool:
    """True iff `needle` appears as a contiguous run inside `haystack`.

    This is WORD-token based, never character-substring based — a critical
    distinction for short trigger phrases. An earlier version of this scorer
    used raw string containment (`trig_norm in q_norm`), which let 2-letter
    professional abbreviations used as triggers (e.g. "ОВ" = HVAC, "ВА" =
    volt-ampere) match as SUBSTRINGS inside unrelated Cyrillic words (e.g.
    "ОВ" inside "уг-ОВ" [углов], "ВА" inside "указыВА-ющей") — a real bug
    caught during build that spuriously routed unrelated queries to
    duct-routing/electrical-circuits. Matching on the tokenized word list
    instead makes this class of false-positive structurally impossible.
    """
    if not needle:
        return False
    n = len(needle)
    for i in range(len(haystack) - n + 1):
        if haystack[i:i + n] == needle:
            return True
    return False


# ---------------------------------------------------------------------------
# Page model
# ---------------------------------------------------------------------------
_FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
_SECTION_RE = re.compile(r"^## (.+?)\n(.*?)(?=^## |\Z)", re.S | re.M)
_TITLE_RE = re.compile(r"^# (.+)$", re.M)
_CARD_RE = re.compile(r"^### .+?(?=^### |\Z)", re.S | re.M)
_CARD_HEAD_RE = re.compile(
    r"^### (.+?)\s+·\s+capability:\s*(\S+)\s+·\s+compiles:\s*([^\s·]+)"
    r"(?:\s+·\s+db_idx:\s*(\d+))?\s*$",
    re.M,
)
_USE_WHEN_RE = re.compile(r"^Use when \(RU\):\s*(.+)$", re.M)
_REVIT_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_COMPILES_RANGE_RE = re.compile(r"^(20\d{2})(?:-(20\d{2}))?$")


def _parse_list_field(fm_raw: str, key: str) -> list[str]:
    m = re.search(rf'^{key}:\s*(\[.*?\])\s*$', fm_raw, re.M)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except Exception:
        return []


@dataclass
class RecipeCard:
    name: str
    capability: str
    compiles: str
    db_idx: str | None
    use_when: str
    raw: str  # verbatim "### ..." block, stripped of trailing blank lines
    match_tokens: set[str] = field(default_factory=set)
    # W2-B (SPEC_W2B_card_rank.md): `capability` ("action×object") parsed
    # once at load time via `_card_action_object`, cached here so
    # `build_injection`'s ranking never re-parses it per query. None when
    # `capability` is empty/malformed (no "×") — same fail-open contract as
    # `match_tokens` on a malformed card header.
    cap_action: str | None = None
    cap_object: str | None = None
    cap_objects: frozenset[str] = field(default_factory=frozenset)


def revit_year(value: str | None) -> int | None:
    """Extract a Revit major year from bridge/config values.

    The bridge normally sends ``"2026"``, while diagnostics and tests may
    carry values such as ``"Autodesk Revit 2026"``.  Unknown values stay
    unknown instead of being guessed.
    """
    match = _REVIT_YEAR_RE.search(value or "")
    return int(match.group(1)) if match else None


def card_supports_version(card: RecipeCard, value: str | None) -> bool:
    """Whether a recipe's declared compile range includes ``value``.

    No version means that the caller has no trustworthy compatibility signal,
    so the historical unfiltered behaviour is preserved.  A known version is
    fail-closed: malformed compile metadata cannot leak code into that turn.
    Release validation rejects malformed metadata before production startup.
    """
    year = revit_year(value)
    if year is None:
        return True
    match = _COMPILES_RANGE_RE.fullmatch(card.compiles or "")
    if not match:
        return False
    first = int(match.group(1))
    last = int(match.group(2) or match.group(1))
    return first <= year <= last


@dataclass
class Page:
    slug: str
    path: str
    domain: str
    capabilities: list[str]
    recipe_names: list[str]
    api_classes: list[str]
    triggers_ru: list[str]
    title: str
    sections: dict[str, str]
    cards: list[RecipeCard]
    full_body: str  # body after frontmatter, title through See also
    # precomputed scoring state
    trigger_norms: list[tuple[list[str], set[str]]] = field(default_factory=list)
    overview_tokens: set[str] = field(default_factory=set)
    action_set: set[str] = field(default_factory=set)

    def recipe_names_lower(self) -> set[str]:
        return {n.lower() for n in self.recipe_names}


# ---------------------------------------------------------------------------
# W2-B (SPEC_W2B_card_rank.md): capability parsing, shared by load_pages()
# (cache on RecipeCard) and _card_frame_bonus() (compare against a frame).
# ---------------------------------------------------------------------------
def _card_action_objects(cap: str) -> tuple[str | None, frozenset[str]]:
    """Parse the canonical ``action×obj1,obj2`` capability shape.

    Older pages used a bare action for an empty object set.  Runtime keeps
    accepting that shape during rolling deploys, while the release gate
    requires canonical ``action×-`` in new releases.
    """
    try:
        from kukai.knowledge.schema import parse_capability

        parsed = parse_capability(cap, allow_bare_action=True)
        return parsed.action, frozenset(parsed.object_kinds)
    except Exception:
        return None, frozenset()


def _card_action_object(cap: str) -> tuple[str | None, str | None]:
    """Parse a RecipeCard.capability string ("action×object", e.g.
    "create×wall") -> (action, object). Missing/malformed capability (no
    "×" separator, or either half blank after stripping) -> None for that
    half — mirrors capability_router.build_routing_table's own
    `cap.split("×", 1)` convention for the identical string shape."""
    action, objects = _card_action_objects(cap)
    return action, (sorted(objects)[0] if objects else None)


def load_pages(root: str | os.PathLike[str] | None = None) -> dict[str, Page]:
    selected_root = os.fspath(root) if root is not None else WIKI_ROOT
    pages_glob = os.path.join(selected_root, "pages", "*", "*.md")
    pages: dict[str, Page] = {}
    from pathlib import Path
    for path in sorted(Path(selected_root).glob("pages/*/*.md")):
        fp = str(path)
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        fm_m = _FM_RE.match(content)
        fm_raw = fm_m.group(1) if fm_m else ""
        body = content[fm_m.end():] if fm_m else content
        domain_m = re.search(r"^domain:\s*(\S+)\s*$", fm_raw, re.M)
        domain = domain_m.group(1) if domain_m else os.path.basename(os.path.dirname(fp))
        capabilities = _parse_list_field(fm_raw, "capabilities")
        recipe_names = _parse_list_field(fm_raw, "recipe_names")
        api_classes = _parse_list_field(fm_raw, "api_classes")
        triggers_ru = _parse_list_field(fm_raw, "triggers_ru")
        title_m = _TITLE_RE.search(body)
        title = title_m.group(1).strip() if title_m else os.path.splitext(os.path.basename(fp))[0]
        sections: dict[str, str] = {}
        for m in _SECTION_RE.finditer(body):
            sections[m.group(1).strip()] = m.group(2)
        cards: list[RecipeCard] = []
        vr = sections.get("Verified recipes", "")
        for card_m in _CARD_RE.finditer(vr):
            raw = card_m.group(0).rstrip() + "\n"
            head_m = _CARD_HEAD_RE.search(raw)
            if not head_m:
                # Malformed/unexpected card header shape — cite verbatim,
                # still keep it navigable under a best-effort name.
                first_line = raw.splitlines()[0].lstrip("# ").strip()
                cards.append(RecipeCard(
                    name=first_line, capability="", compiles="", db_idx=None,
                    use_when="", raw=raw,
                ))
                continue
            name, capability, compiles, db_idx = head_m.groups()
            uw_m = _USE_WHEN_RE.search(raw)
            use_when = uw_m.group(1).strip() if uw_m else ""
            cards.append(RecipeCard(
                name=name.strip(), capability=capability, compiles=compiles,
                db_idx=db_idx, use_when=use_when, raw=raw,
            ))
        slug = os.path.splitext(os.path.basename(fp))[0]
        page = Page(
            slug=slug, path=fp, domain=domain, capabilities=capabilities,
            recipe_names=recipe_names, api_classes=api_classes,
            triggers_ru=triggers_ru, title=title, sections=sections,
            cards=cards, full_body=body.strip() + "\n",
        )
        # precompute
        page.trigger_norms = [(tokenize_list(t), tokenize(t)) for t in triggers_ru]
        page.overview_tokens = tokenize(title) | tokenize(sections.get("Обзор", ""))
        page.action_set = {c.split("×", 1)[0] for c in capabilities if "×" in c or c}
        for c in cards:
            c.match_tokens = tokenize(c.name) | tokenize(c.use_when)
            c.cap_action, c.cap_objects = _card_action_objects(c.capability)
            c.cap_object = sorted(c.cap_objects)[0] if c.cap_objects else None
        if slug in pages:
            raise ValueError(
                f"duplicate wiki slug {slug!r}: {pages[slug].path} and {fp}"
            )
        pages[slug] = page
    return pages


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_page(page: Page, q_tokens: set[str], q_tokens_list: list[str], action: str | None) -> tuple[float, float, float, float]:
    trig_score = 0.0
    for trig_list, trig_tokens in page.trigger_norms:
        if not trig_tokens:
            continue
        # WORD-token contiguous match (not character substring — see
        # `contains_contiguous` docstring for the bug this guards against).
        if contains_contiguous(q_tokens_list, trig_list):
            trig_score += 3.0 + 0.15 * len(trig_tokens)  # exact phrase, scaled by specificity
            continue
        overlap = trig_tokens & q_tokens
        if overlap == trig_tokens:
            trig_score += 2.0  # all trigger words present, just not contiguous
        elif overlap:
            trig_score += 0.5 * len(overlap)

    overview_overlap = len(q_tokens & page.overview_tokens)
    overview_score = 0.3 * overview_overlap

    # (c) is a BOOST, not an independent signal: it must only reinforce a page
    # that already has some primary/secondary evidence. Without this guard, a
    # zero-signal query (smalltalk, gibberish, truly off-corpus) falls back to
    # quick_classify's own weak default action (e.g. "set_param"), which is
    # carried by ~29/68 pages — the boost then becomes the SOLE driver of
    # navigation for every such query, and the alphabetically-first page among
    # those ~29 wins every single time. That produced a real bug during build
    # (39/556 queries — all smalltalk/off-topic/gibberish — deterministically
    # routed to `cable-tray-conduit`, an unrelated page, purely because "c"
    # sorts early). Gating the boost on existing evidence fixes this; the
    # residual zero-signal fallback (see `navigate`) is then a small, honestly
    # arbitrary alphabetical default — reported as such, not hidden.
    cap_boost = 4.0 if (action and action in page.action_set and (trig_score > 0 or overview_score > 0)) else 0.0

    total = trig_score + overview_score + cap_boost
    return total, trig_score, overview_score, cap_boost


def navigate(pages: dict[str, Page], query: str) -> tuple[list[tuple[str, float]], str | None]:
    action = quick_action_for(query)
    q_tokens = tokenize(query)
    q_tokens_list = tokenize_list(query)
    scored = []
    for slug, page in pages.items():
        total, trig, ov, cap = score_page(page, q_tokens, q_tokens_list, action)
        scored.append((slug, total, trig, ov, cap))
    scored.sort(key=lambda r: (-r[1], -r[2], -r[3], r[0]))
    top3 = [(s[0], s[1]) for s in scored[:3]]
    return top3, action


# ---------------------------------------------------------------------------
# Lever 1: API reference block (SPEC_lever1_api_ref.md)
# ---------------------------------------------------------------------------
def api_ref_flag_enabled() -> bool:
    """KUKAI_WIKI_API_REF, default ON. Read at call time (not cached) so a
    flag flip is picked up without a process restart, same discipline as
    every other KUKAI_* feature flag in this codebase."""
    return os.environ.get(API_REF_FLAG_ENV, "1").strip().lower() in ("1", "true", "on", "yes")


_PAREN_RE = re.compile(r"\s*\([^)]*\)")


def _candidate_base_names(raw: str) -> list[str]:
    """Best-effort bare CLASS name candidates from ONE raw `api_classes`
    frontmatter entry.

    The common case is clean ("ViewSchedule", "ViewSchedule.CreateKeySchedule")
    and the spec's "text before the first dot" rule handles it. The real
    corpus is messier though (hand-authored frontmatter, 19/435 entries as of
    2026-07-11): parenthetical notes ("FamilyInstance (FlipFacing/FlipHand)"),
    "/"-separated alternatives ("BindingMap / ParameterBindings"), and fully-
    qualified dotted paths ("Autodesk.Revit.DB.ExtensibleStorage.Schema" —
    where "text before the first dot" wrongly yields "Autodesk", not the real
    class "Schema"). This never GUESSES a member, only which bare name(s) to
    try looking up: every candidate still has to resolve in members_for/the
    corpus below to render anything, so a wrong/junk candidate (e.g.
    "LoadFamily" from "Document.LoadFamily") just fails that lookup and is
    dropped, never fabricated.

    For each "/"-separated piece: no dot -> the piece itself is one
    candidate; a dot present -> BOTH the first segment (Class.Member
    convention) and the last segment (FQN convention) are offered as
    candidates, in that order — whichever one is a real class resolves,
    lookup is the arbiter, not this parser.
    """
    raw = _PAREN_RE.sub("", raw or "").strip()
    if not raw:
        return []
    candidates: list[str] = []
    for piece in raw.split("/"):
        piece = piece.strip()
        if not piece:
            continue
        if "." in piece:
            first = piece.split(".", 1)[0].strip()
            last = piece.rsplit(".", 1)[-1].strip()
            if first:
                candidates.append(first)
            if last and last != first:
                candidates.append(last)
        else:
            candidates.append(piece)
    return candidates


def build_api_reference(
    api_classes: list[str], revit_version: str | None, budget_chars: int,
    q_tokens: set[str] | None = None,
) -> str:
    """Render a compact "Справка API" block for a page's frontmatter
    `api_classes` list (e.g. ["ViewSchedule", "ViewSchedule.CreateKeySchedule",
    "TableSectionData"]). Cap: <=API_REF_MAX_CLASSES classes,
    <=API_REF_MAX_MEMBERS members/class, whole block <=API_REF_BUDGET_CHARS_DEFAULT
    chars (and never more than `budget_chars`, the caller's remaining budget).

    Members are NEVER invented: for each candidate base class name
    (`_candidate_base_names`, deduplicated, order-preserving) this tries, in
    order:
      1. `kukai.llm.api_members.members_for("", base_name, revit_version)` —
         the SAME version-correct source rag_prompt.py's G2 member-grounding
         already trusts (namespace="" relies on that function's own
         short-name fallback match, exactly as intended for a bare wiki
         frontmatter class name with no namespace attached).
      2. REF_GAP fix (2026-07-12), only when `api_ref_enums_flag_enabled()`:
         `kukai.llm.api_members.enum_values_for` — class-member lookup above
         return nothing for an ENUM class by design (members_for's own
         docstring: "too many members -> stay repair-side"); this is the one
         case a candidate that resolves to an enum in `revit_version`'s
         surface gets a block at all, and only ever a bounded, real,
         relevance-filtered (`q_tokens`) subset of its values — never the
         whole enum. See that function's docstring for the small-enum vs
         large-enum policy.
      3. Neither source has it -> that candidate is skipped
         entirely (a frontmatter entry can offer multiple candidates -- e.g.
         a "/" list, or both ends of a dotted FQN -- only the ones that
         resolve render; junk candidates just cost a cheap failed lookup).

    Resolution stops once API_REF_MAX_CLASSES real classes have been
    rendered (not after scanning API_REF_MAX_CLASSES raw candidates) so a
    page whose first couple of frontmatter entries happen to be messy/
    unresolvable doesn't starve the later, clean ones out of their slot.

    REF_GAP fix, only when `api_ref_enums_flag_enabled()` (both ADDITIVE —
    neither changes a single byte of the class-member blocks above, and
    both no-op to nothing whenever they find nothing real, same fail-open
    contract):
      - METHOD SIGNATURES: `api_classes` entries shaped "Class.Method"
        (`_signature_hint_pairs` — an existing frontmatter convention, e.g.
        "ViewSchedule.Export") each resolve, independently of the class-
        candidate loop above, to a small, bounded, real parameter-TYPE
        signature block via `kukai.llm.api_members.method_signatures_for`
        (capped at API_REF_MAX_SIGNATURE_HINTS hints/page).
      - UNIVERSAL ENUMS: `_UNIVERSAL_ENUM_WATCHLIST` (BuiltInParameter/
        BuiltInCategory/ViewType — used everywhere, curated on almost no
        page's frontmatter) is always checked through the SAME relevance-
        gated `enum_values_for` as (3) above, so it renders nothing unless
        `q_tokens` actually picks out a real, bounded subset.

    Returns "" if nothing usable was found (empty api_classes, no candidate
    resolved in either source, or budget_chars too small to render even one
    class — see API_REF_MIN_BUDGET).
    """
    if not api_classes or not budget_chars or budget_chars < API_REF_MIN_BUDGET:
        return ""

    seen: set[str] = set()
    candidates: list[str] = []
    for c in api_classes:
        if not isinstance(c, str) or not c.strip():
            continue
        for base in _candidate_base_names(c):
            if base and base not in seen:
                seen.add(base)
                candidates.append(base)
    if not candidates:
        return ""

    enums_on = api_ref_enums_flag_enabled()

    blocks: list[str] = []
    for name in candidates:
        if len(blocks) >= API_REF_MAX_CLASSES:
            break
        members: list[str] | None = None
        if revit_version:
            try:
                from kukai.llm.api_members import members_for as _members_for
                raw = _members_for("", name, revit_version, limit=API_REF_MAX_MEMBERS)
                if raw:
                    members = [m.strip() for m in raw.split(",") if m.strip()]
            except Exception:
                logger.debug("Lever 1: members_for(%s) failed (non-fatal)", name, exc_info=True)
                members = None
        if not members and enums_on and revit_version:
            try:
                from kukai.llm.api_members import enum_values_for as _enum_values_for
                values = _enum_values_for("", name, revit_version, query_tokens=q_tokens)
            except Exception:
                logger.debug("REF_GAP: enum_values_for(%s) failed (non-fatal)", name, exc_info=True)
                values = None
            if values:
                blocks.append(f"### {name} (enum)\n" + ", ".join(values))
            continue
        if not members:
            continue  # not in either source -> skip, never fabricate
        blocks.append(f"### {name}\n" + ", ".join(members[:API_REF_MAX_MEMBERS]))

    if enums_on and revit_version:
        sig_count = 0
        for cls, method in _signature_hint_pairs(api_classes):
            if sig_count >= API_REF_MAX_SIGNATURE_HINTS:
                break
            try:
                from kukai.llm.api_members import method_signatures_for as _sig_for
                sigs = _sig_for("", cls, method, revit_version)
            except Exception:
                logger.debug("REF_GAP: method_signatures_for(%s.%s) failed (non-fatal)",
                             cls, method, exc_info=True)
                sigs = None
            if not sigs:
                continue
            blocks.append(f"### {cls}.{method}\n" + "; ".join(sigs))
            sig_count += 1

        for wname in _UNIVERSAL_ENUM_WATCHLIST:
            if wname in seen:
                continue  # already handled as an explicit frontmatter candidate above
            try:
                from kukai.llm.api_members import enum_values_for as _enum_values_for
                # require_relevance NOT set (defaults False): unlike the two
                # genuinely large watchlist entries (BuiltInParameter/
                # BuiltInCategory, which are relevance-gated regardless --
                # that path triggers purely on real value-count, see
                # enum_values_for's _SMALL_ENUM_MAX check), a SMALL watchlist
                # enum (ViewType: 25 real values, ~350 chars bounded) has no
                # RU-keyword-curated relevance source to gate on at all (only
                # builtin_parameters/builtin_categories carry name_ru/
                # keywords_ru) -- gating it the same way as the large enums
                # would make it silently never fire for RU-language queries
                # (measured: real:153 needs exactly ViewType, in RU, with no
                # literal-English-token overlap). Cheap + bounded + always
                # real -> always offered, same policy as an explicit
                # frontmatter-declared small-enum candidate above.
                values = _enum_values_for("", wname, revit_version, query_tokens=q_tokens)
            except Exception:
                logger.debug("REF_GAP: enum_values_for(%s) [watchlist] failed (non-fatal)",
                             wname, exc_info=True)
                values = None
            if values:
                blocks.append(f"### {wname} (enum)\n" + ", ".join(values))

    if not blocks:
        return ""

    # REF_GAP fix: the enum/signature additions above are appended AFTER the
    # explicit class-member blocks (never displace them) but share the same
    # overall cap -- API_REF_BUDGET_CHARS_DEFAULT (1500) was sized for
    # Lever-1's names-only scope, where API_REF_MAX_CLASSES=5 explicit
    # classes alone can already consume most of it, starving every new
    # block out on pages with a full explicit api_classes list. Widen the
    # cap (never past the caller's own `budget_chars` ceiling -- `min(...)`
    # below still applies) only when the new flag is on; OFF -> identical
    # 1500 cap, byte-identical output.
    effective_default = API_REF_BUDGET_CHARS_ENUMS if enums_on else API_REF_BUDGET_CHARS_DEFAULT
    budget = min(budget_chars, effective_default)
    kept: list[str] = []
    total = len(API_REF_HEADER)
    for b in blocks:
        add_len = len(b) + 2  # blank-line separator
        if kept and total + add_len > budget:
            break  # least-relevant (frontmatter-order tail) classes trimmed first
        kept.append(b)
        total += add_len

    if not kept:
        return ""
    return (API_REF_HEADER + "\n\n".join(kept)).rstrip() + "\n"


def _append_api_reference(
    text: str, page: Page, budget: int, revit_version: str | None,
    q_tokens: set[str] | None = None,
) -> str:
    """Flag-gated tail shared by both `build_injection` return paths: append
    a `build_api_reference` block into whatever budget remains under
    `budget` once `text` (the page content already assembled above) is
    placed. OFF (KUKAI_WIKI_API_REF unset/0) or no `revit_version` -> `text`
    returned completely unchanged (byte-identical to pre-Lever-1 output).
    Absolute fail-open: any error here returns `text` unchanged rather than
    ever breaking the page injection itself (module docstring / SPEC rule:
    "ошибка справки -> инжект без неё").

    `q_tokens` (REF_GAP fix, optional, default None): the query's tokenize()
    set, passed straight through to `build_api_reference` for its enum
    relevance-ranking. Every existing caller (this module's own CLI
    `process_query`, and `capability_router.build_injection`/the live
    adapter's own direct `build_api_reference(...)` call, none of which pass
    this) leaves it at None -> the REF_GAP additions that need it (large-
    enum relevance filtering) simply contribute nothing there, same as
    before this parameter existed; the two callers inside `build_injection`
    below (which already computes `q_tokens = tokenize(query)` for card
    ranking) are the only ones passing it.
    """
    if not revit_version or not api_ref_flag_enabled():
        return text
    try:
        remaining = budget - len(text)
        if remaining < API_REF_MIN_BUDGET:
            return text  # recipes already ate the budget -> skip, never trim a recipe for this
        api_ref = build_api_reference(page.api_classes, revit_version, remaining, q_tokens)
        if not api_ref:
            return text
        return text.rstrip("\n") + "\n\n" + api_ref
    except Exception:
        logger.debug("Lever 1: _append_api_reference failed (non-fatal)", exc_info=True)
        return text


# ---------------------------------------------------------------------------
# W2-B: frame-aware card ranking (SPEC_W2B_card_rank.md)
# ---------------------------------------------------------------------------
CARD_RANK_FLAG_ENV = "KUKAI_WIKI_CARD_RANK"


def card_rank_flag_enabled() -> bool:
    """KUKAI_WIKI_CARD_RANK, default ON. Read at call time (not cached),
    same discipline as `api_ref_flag_enabled()` / every other KUKAI_*
    feature flag in this codebase."""
    return os.environ.get(CARD_RANK_FLAG_ENV, "1").strip().lower() in ("1", "true", "on", "yes")


def _card_frame_bonus(card: RecipeCard, frame: dict) -> tuple[int, int]:
    """(cap_action_match, cap_object_match) bonus terms for ranking `card`
    against an OperationFrame dict ({action, object_kinds, ...} — same
    shape as capability_router.derive_quick_frame/derive_oracle_frame).
    Both 0 whenever the card carries no parsed capability or the frame
    carries no matching signal — a card is NEVER excluded by this, only
    nudged in rank (see module docstring: bonus, not filter)."""
    action = frame.get("action")
    obj_kinds = frame.get("object_kinds") or []
    cap_action_match = 1 if (action and card.cap_action == action) else 0
    cap_object_match = 1 if card.cap_objects.intersection(obj_kinds) else 0
    return cap_action_match, cap_object_match


def _rank_cards(
    cards: list[RecipeCard], q_tokens: set[str], frame: dict | None,
    preferred_names: list[str] | None = None,
) -> list[RecipeCard] | None:
    """Rank Verified-recipe `cards` by capability-match with `frame` as the
    PRIMARY key, token-overlap with `q_tokens` as the tie-break, original
    page-file order as the final tie-break — the SPEC_W2B_card_rank.md sort
    key `(-cap_action_match, -cap_object_match, -token_overlap, file_index)`.

    Returns None — every caller below must then fall back to today's plain
    `(-token_overlap, file_index)` ranking — when: `cards` is empty,
    `KUKAI_WIKI_CARD_RANK` is off, `frame` is not a usable non-empty dict,
    or scoring raises for ANY reason. This is the single fail-open gate for
    the whole W2-B feature (SPEC rule: frame None/error -> today's
    token-only ranking, unchanged).
    """
    if preferred_names:
        by_name = {card.name: card for card in cards}
        ordered = [by_name[name] for name in preferred_names if name in by_name]
        seen = {card.name for card in ordered}
        ordered.extend(card for card in cards if card.name not in seen)
        if ordered:
            return ordered
    if not cards or not card_rank_flag_enabled() or not isinstance(frame, dict) or not frame:
        return None
    try:
        scored = []
        for idx, c in enumerate(cards):
            cap_action_match, cap_object_match = _card_frame_bonus(c, frame)
            token_overlap = len(c.match_tokens & q_tokens)
            scored.append((-cap_action_match, -cap_object_match, -token_overlap, idx, c))
        scored.sort(key=lambda t: t[:4])
        return [t[4] for t in scored]
    except Exception:
        logger.debug("W2-B: card_rank scoring failed, falling back to token overlap", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Injection assembly
# ---------------------------------------------------------------------------
def build_injection(
    page: Page, query: str, budget: int, revit_version: str | None = None,
    frame: dict | None = None, card_order: list[str] | None = None,
) -> tuple[str, str | None, bool]:
    """Returns (injection_text, first_recipe_name, was_trimmed).

    `revit_version` is a correctness boundary, not merely API-reference
    decoration: recipe cards whose declared ``compiles`` range excludes the
    active Revit year are removed before ranking and rendering.  This applies
    to both short (formerly whole-page) and trimmed pages.  The compact API
    reference remains additive when KUKAI_WIKI_API_REF is enabled.

    `frame` (W2-B, optional, default None, SPEC_W2B_card_rank.md): an
    OperationFrame dict. When KUKAI_WIKI_CARD_RANK is truthy AND `frame` is
    a usable non-empty dict, Verified-recipe cards are ranked with a
    capability-match bonus ahead of the token-overlap tie-break (see
    `_rank_cards`) — applied to BOTH the trimmed path's kept-card
    selection/order AND the untrimmed path's reported `first_recipe` (the
    untrimmed page TEXT itself is never rewritten/reordered — only which
    card's name is reported as `first_recipe` can change, since the
    untrimmed body is assembled verbatim from `page.sections`, not
    reconstructed from `page.cards`). Every existing caller leaves `frame`
    at its default None, so with the flag off OR no frame given this
    function's output is byte-identical to the pre-W2-B behavior.
    """
    eligible_cards = [
        card for card in page.cards if card_supports_version(card, revit_version)
    ]
    version_filtered = len(eligible_cards) != len(page.cards)

    full = f"# {page.title}\n\n"
    for sec in ("Триггеры", "Обзор", "Грабли и версии", "Verified recipes", "See also"):
        if sec in page.sections:
            section_text = page.sections[sec]
            if sec == "Verified recipes" and version_filtered:
                section_text = (
                    "\n\n".join(card.raw.rstrip() for card in eligible_cards) + "\n"
                    if eligible_cards
                    else "Для активной версии Revit на этой странице нет проверенного рецепта.\n"
                )
            full += f"## {sec}\n{section_text}"
            if not full.endswith("\n\n"):
                full += "\n"

    q_tokens = tokenize(query)

    if len(full) <= budget:
        first_recipe = eligible_cards[0].name if eligible_cards else None
        ranked_cards = _rank_cards(eligible_cards, q_tokens, frame, card_order)
        if ranked_cards is not None:
            first_recipe = ranked_cards[0].name
        text, trimmed = full.rstrip() + "\n", False
        return _append_api_reference(text, page, budget, revit_version, q_tokens), first_recipe, trimmed

    # Trimmed path: title + Обзор + Грабли и версии + ranked Verified recipes.
    # Триггеры and See also are dropped first (lowest injection value).
    header = f"# {page.title}\n\n"
    header += f"## Обзор\n{page.sections.get('Обзор', '').strip()}\n\n"
    header += f"## Грабли и версии\n{page.sections.get('Грабли и версии', '').strip()}\n\n"
    header += "## Verified recipes\n\n"

    ranked_cards = _rank_cards(eligible_cards, q_tokens, frame, card_order)
    ranked = ranked_cards if ranked_cards is not None else sorted(
        eligible_cards,
        key=lambda c: (-len(c.match_tokens & q_tokens), eligible_cards.index(c)),
    )

    remaining = budget - len(header)
    kept: list[RecipeCard] = []
    for card in ranked:
        block_len = len(card.raw) + 1
        if not kept:
            # Always keep at least the single best-matching card, even if it
            # alone doesn't fit — a page injection with zero recipes is a
            # worse failure mode than one slightly over budget.
            kept.append(card)
            remaining -= block_len
            continue
        if block_len <= remaining:
            kept.append(card)
            remaining -= block_len
        # else: this card is trimmed (least-relevant-first, by construction
        # of the `ranked` order); keep scanning in case a smaller, still
        # lower-ranked card fits in the leftover budget.

    body = header + "\n\n".join(c.raw.rstrip() for c in kept) + "\n"
    first_recipe = kept[0].name if kept else None
    return _append_api_reference(body, page, budget, revit_version, q_tokens), first_recipe, True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def process_query(pages: dict[str, Page], rec: dict, budget: int, preview_chars: int) -> dict:
    qid = rec.get("id")
    query = rec.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"id": qid, "query": query, "error": "missing/empty 'query'"}
    t0 = time.perf_counter()
    try:
        top3, action = navigate(pages, query)
        top1_slug = top3[0][0] if top3 else None
        page = pages.get(top1_slug) if top1_slug else None
        if page is None:
            raise RuntimeError("navigation produced no page (empty corpus?)")
        injection, first_recipe, trimmed = build_injection(page, query, budget)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {
            "id": qid,
            "query": query,
            "quick_action": action,
            "nav_page": os.path.relpath(page.path, WIKI_ROOT),
            "nav_top3": [os.path.relpath(pages[s].path, WIKI_ROOT) for s, _ in top3 if s in pages],
            "nav_scores_top3": [round(sc, 3) for _, sc in top3],
            "nav_latency_ms": latency_ms,
            "wiki_injection_chars": len(injection),
            "wiki_injection_trimmed": trimmed,
            "first_recipe_name": first_recipe,
            "inject_preview": injection[:preview_chars],
            "error": None,
        }
    except Exception as e:  # never let one query kill the run
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {
            "id": qid, "query": query, "nav_latency_ms": latency_ms,
            "error": f"{type(e).__name__}: {e}",
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", required=True, help="input JSONL with {id, query} per line")
    ap.add_argument("--out", required=True, help="output JSONL path")
    ap.add_argument("--budget", type=int, default=INJECT_BUDGET_DEFAULT, help="injection char budget (default 9000)")
    ap.add_argument("--preview-chars", type=int, default=PREVIEW_CHARS_DEFAULT, help="inject_preview length (default 600)")
    args = ap.parse_args()

    pages = load_pages()
    if not pages:
        print(f"FATAL: no pages loaded from {PAGES_GLOB}", file=sys.stderr)
        return 1

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
            out_rec = process_query(pages, rec, args.budget, args.preview_chars)
            fout.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            fout.flush()
            if out_rec.get("error"):
                n_err += 1
            else:
                n_ok += 1

    print(f"wiki_query: {n_ok} ok, {n_err} error, -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
