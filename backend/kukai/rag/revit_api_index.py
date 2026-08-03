"""Revit API knowledge base — index, search, and retrieval.

Loads a comprehensive Revit API database from JSON and provides
keyword-based AND semantic (embedding) search in both Russian and
English. Used by the prompt system to inject relevant API context
before each LLM call.

Semantic search uses pre-computed OpenAI embeddings stored in
rag_embeddings.npz. If embeddings are unavailable, falls back
to keyword search transparently.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Optional numpy — only needed for semantic search
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# Stemming-like suffix stripping for Russian morphology.
# We strip common Russian endings so that "стенами", "стены", "стенки"
# all reduce to the same stem.
_RU_SUFFIXES = [
    "ами", "ями",  # instrumental plural
    "ого", "его",  # genitive masc/neut
    "ому", "ему",  # dative masc/neut
    "ой", "ей",    # genitive/instrumental fem + adjective
    "ов", "ев",    # genitive plural
    "ах", "ях",    # prepositional plural
    "ий", "ый",    # adjective endings
    "ие", "ые",    # adjective plural
    "ок", "ек",    # diminutive
    "ки", "ка",    # diminutive / plural
    "ам", "ям",    # dative plural
    "ем", "ом",    # prepositional singular
    "ию", "ую",    # accusative fem
    "ии", "ия",    # genitive/nom fem
    "ы", "и",      # plural
    "а", "я",      # feminine/genitive
    "е", "у", "о", # various cases
]


def _lemma_lexicon_enabled() -> bool:
    """KUKAI_LEMMA_LEXICON flag (IQ-moment #7), read at call time.

    Mirrors ``kukai.nlp.lemma.lemma_lexicon_enabled`` locally so the hot
    tokenizer path does not import the nlp package when the flag is OFF.
    """
    return os.getenv("KUKAI_LEMMA_LEXICON", "0") == "1"


def _bilingual_retrieval_enabled() -> bool:
    """KUKAI_BILINGUAL_RETRIEVAL flag (IQ-moment #6), read at call time.

    Mirrors ``kukai.rag.retrieval.bilingual_retrieval_enabled`` locally (same
    env read, same pattern as ``_lemma_lexicon_enabled`` above) so the loader
    and the tokenizer-mode guard do not import the retrieval module.
    """
    return os.getenv("KUKAI_BILINGUAL_RETRIEVAL", "0") == "1"


def _normalize_token(token: str) -> str:
    """Normalize a token: lowercase + strip common suffixes for rough stemming.

    Under ``KUKAI_LEMMA_LEXICON=1``: real RU morphology instead of the greedy
    suffix strip — ``стеной``/``стене``/``стенами`` all normalize to ``стена``
    (the stripper misses whole case forms: ``дверью`` keeps its ``ью``, so it
    could never match the ``дверь`` index tokens). ASCII tokens are unchanged
    in both modes. Both the index build (``_make_tokens`` at ``load()``) and
    the query side flow through THIS function, so the two stay consistent;
    a post-load flag flip is handled by ``RevitApiIndex._ensure_token_mode``.
    """
    token = token.lower().strip()
    if _lemma_lexicon_enabled():
        try:
            from kukai.nlp.lemma import lemma

            return lemma(token)
        except Exception:  # noqa: BLE001 — retrieval must never break
            pass  # fall through to the legacy stripper
    if len(token) <= 3:
        return token
    # Try stripping Russian suffixes (longest first for greedy match)
    for suffix in _RU_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)]
    return token


def _tokenize(text: str) -> list[str]:
    """Split text into normalized tokens."""
    raw = re.split(r"[\s_.,;:!?()—\-/\\]+", text.lower())
    return [_normalize_token(t) for t in raw if len(t) >= 2]


# Common English stop words that cause false matches in keyword search.
_STOP_WORDS = frozenset([
    "in", "the", "a", "an", "of", "to", "for", "is", "it", "on",
    "at", "by", "or", "and", "with", "from", "as", "be", "are",
    "was", "were", "has", "have", "had", "do", "does", "did",
    "not", "but", "if", "so", "no", "can", "will", "my", "its",
    "this", "that", "than", "how", "what", "which", "who", "each",
    "all", "every", "many", "much", "more", "less", "over", "under",
    "without", "into", "out", "up", "down", "between", "through",
    "about", "above", "below", "after", "before", "some", "any",
    "other", "such",
])


def _filter_stop_words(tokens: list[str]) -> list[str]:
    """Remove stop words from query tokens, keeping content-bearing words."""
    content = [t for t in tokens if t not in _STOP_WORDS and len(t) >= 2]
    return content if content else tokens


# ---------------------------------------------------------------------------
# BM25F keyword leg (flag: KUKAI_BM25F, default OFF) — IQ-moment #3.
#
# The legacy keyword scorer above/below is a full-corpus nested scan
# (~O(entries x query_tokens x entry_tokens) with substring checks and a set
# allocation per (entry, token) pair) whose ad-hoc weights lack IDF — which is
# exactly why it needed four promotion hacks (_promote_to_top /
# _CREATE_BOOST_MAP / transform-verb map / concept anchors) to keep rare
# canonical classes from being buried under mega-keyword entries.
#
# The BM25F path replaces the SCORING with a proper inverted index (postings)
# + field-weighted BM25F: O(query_terms x postings(term)) instead of
# O(corpus), and IDF makes rare discriminative terms count by construction.
#
# How the legacy hacks map onto this model:
#   * missing-IDF flood        -> BM25F IDF + per-field length normalization
#     (a 287-keyword class no longer matches everything at full strength);
#   * concept "name anchor"    -> the `name` field carries the highest weight
#     AND identifier subwords are indexed (ViewSchedule -> view, schedule), so
#     the canonical home of a concept ranks on its own name;
#   * essentials floor         -> a LOW b on the `keywords` field keeps the
#     keyword-rich infrastructure classes (FilteredElementCollector,
#     Transaction) discoverable instead of length-punishing them to oblivion;
#   * class/recipe/edge boosts -> preserved verbatim as type priors;
#   * _CREATE_BOOST_MAP / transform verbs / per-token coverage guarantee ->
#     the shared post-ranking stages (`_apply_ranking_stages`) run for BOTH
#     paths, so their intent is preserved exactly (they only re-order entries
#     that already matched; with IDF in place they fire far less often).
#
# Flag OFF (default) is byte-identical legacy behaviour: the BM25F index is
# not even constructed.
# ---------------------------------------------------------------------------


def _bm25f_enabled() -> bool:
    """Read the flag at call time (same pattern as KUKAI_RAG_RECIPES_ENABLED)."""
    return os.getenv("KUKAI_BM25F", "0") == "1"


def _bm25f_stages_enabled() -> bool:
    """Sub-toggle: run the shared coverage/promotion stages on the BM25F path.

    Default ON (preserve the promotion hacks' intent). ``KUKAI_BM25F_STAGES=0``
    is an ablation/measurement knob for the benchmark, not a prod setting.
    """
    return os.getenv("KUKAI_BM25F_STAGES", "1") != "0"


# Identifier subword splitter: "ViewSchedule" -> ["View", "Schedule"],
# "View3D" -> ["View", "3D"], "OST_Walls" (post underscore-split) -> ["OST",
# "Walls"], "XYZ" -> ["XYZ"], "IFCExport" -> ["IFC", "Export"].
_SUBWORD_RE = re.compile(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|\d+[A-Za-z]*|[a-z]+")

# Same separator charset as _tokenize, but WITHOUT lowercasing first, so the
# camel-case structure of identifiers survives until _SUBWORD_RE sees it.
_BM25F_SPLIT_RE = re.compile(r"[\s_.,;:!?()—\-/\\]+")


def _en_plural_strip(token: str) -> str:
    """Light English plural normalization, applied to BOTH index and query.

    Replaces the legacy scorer's bidirectional substring matching for the
    dominant real case (walls~wall, ducts~duct, categories~category). Cyrillic
    tokens pass through untouched (no ASCII suffix match).
    """
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and token[-3] in "sxz":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _bm25f_norm(raw: str) -> str:
    """Full BM25F term normalization: legacy normalize + English plural strip."""
    return _en_plural_strip(_normalize_token(raw.lower()))


def _bm25f_field_terms(text: str, split_identifiers: bool = True) -> list[str]:
    """Terms (with multiplicity) for one document field.

    Emits the whole normalized token AND — for compound identifiers — its
    subwords, so "ViewSchedule" is reachable by "schedule" without any
    substring scan. Stop words are dropped (the query side never emits them).
    """
    terms: list[str] = []
    for raw in _BM25F_SPLIT_RE.split(text or ""):
        if len(raw) < 2:
            continue
        base = _bm25f_norm(raw)
        if len(base) >= 2 and base not in _STOP_WORDS:
            terms.append(base)
        if split_identifiers:
            subs = _SUBWORD_RE.findall(raw)
            if len(subs) > 1:
                for sub in subs:
                    if len(sub) < 2:
                        continue
                    st = _bm25f_norm(sub)
                    if len(st) >= 2 and st not in _STOP_WORDS and st != base:
                        terms.append(st)
    return terms


def _bm25f_query_terms(query: str) -> list[str]:
    """Unique query terms under the same normalization as the index fields."""
    seen: set[str] = set()
    for raw in _BM25F_SPLIT_RE.split(query or ""):
        if len(raw) < 2:
            continue
        base = _bm25f_norm(raw)
        if len(base) >= 2 and base not in _STOP_WORDS:
            seen.add(base)
        subs = _SUBWORD_RE.findall(raw)
        if len(subs) > 1:
            for sub in subs:
                if len(sub) < 2:
                    continue
                st = _bm25f_norm(sub)
                if len(st) >= 2 and st not in _STOP_WORDS:
                    seen.add(st)
    return sorted(seen)  # sorted for determinism


def _name_match_bonus(entry_name_lower: str, query_lower: str) -> float:
    """Exact/substring name-match prior — same constants as the legacy scorer."""
    if entry_name_lower == query_lower:
        return 20.0
    if entry_name_lower in query_lower:
        coverage = len(entry_name_lower) / max(len(query_lower), 1)
        if coverage > 0.5:
            return 10.0
        if coverage > 0.3:
            return 5.0
        return 2.0
    if query_lower in entry_name_lower and len(query_lower) >= 3:
        return 5.0
    return 0.0


# BM25F parameters. Field order: 0=name, 1=keywords(primary), 2=description,
# 3=aux(secondary: methods + RU keywords for classes). Weights mirror the
# legacy primary(x2)/secondary(x0.5) intent with the name promoted to the top
# slot (the concept-anchor hack, re-expressed). The NEAR-ZERO b on `keywords`
# is the essentials-floor prior: keywords are a CURATED tag set (tf is always
# 1 — they come from token sets), so field length says "reachable via many
# intents", not "diluted"; length-punishing it buries the keyword-rich
# infrastructure classes (FilteredElementCollector, Transaction) that the
# essentials floor exists to keep discoverable. IDF already de-weights their
# ubiquitous terms — that is the honest anti-flood mechanism.
_BM25F_K1 = 1.2
_BM25F_W = (5.0, 2.5, 1.0, 0.5)
_BM25F_B = (0.35, 0.0, 0.75, 0.60)
_BM25F_NFIELDS = 4


class _Bm25fIndex:
    """Inverted index (postings) + BM25F scorer over ApiEntry fields.

    Built once per corpus load (lazily, on the first flagged search); scoring
    a query is O(sum over query terms of |postings(term)|) — it never touches
    entries that share no term with the query.
    """

    __slots__ = ("n_docs", "postings", "doc_norm", "name_docs", "n_terms")

    def __init__(self, entries: list["ApiEntry"]) -> None:
        n = len(entries)
        self.n_docs = n
        # term -> list[(doc, tf0, tf1, tf2, tf3)]
        term_map: dict[str, dict[int, list[int]]] = {}
        doc_len: list[tuple[int, int, int, int]] = []
        self.name_docs: dict[str, list[int]] = {}

        from collections import Counter

        for doc, entry in enumerate(entries):
            fields = (
                _bm25f_field_terms(entry.name),
                [_en_plural_strip(t) for t in entry._primary_tokens
                 if t not in _STOP_WORDS],
                _bm25f_field_terms(entry.description),
                [_en_plural_strip(t)
                 for t in (entry._tokens - entry._primary_tokens)
                 if t not in _STOP_WORDS],
            )
            doc_len.append(tuple(len(f) for f in fields))  # type: ignore[arg-type]
            for fi, terms in enumerate(fields):
                for term, tf in Counter(terms).items():
                    slot = term_map.setdefault(term, {})
                    tfs = slot.get(doc)
                    if tfs is None:
                        tfs = [0, 0, 0, 0]
                        slot[doc] = tfs
                    tfs[fi] += tf
            self.name_docs.setdefault(entry.name.lower(), []).append(doc)

        # Freeze postings (doc-sorted for determinism).
        self.postings: dict[str, list[tuple[int, int, int, int, int]]] = {
            term: [(doc, *tfs) for doc, tfs in sorted(docmap.items())]
            for term, docmap in term_map.items()
        }
        self.n_terms = len(self.postings)

        # Precompute per-doc, per-field length norms: 1 / ((1-b) + b*len/avg).
        avg = [1.0] * _BM25F_NFIELDS
        if n:
            for fi in range(_BM25F_NFIELDS):
                total = sum(dl[fi] for dl in doc_len)
                avg[fi] = max(total / n, 1.0)
        self.doc_norm: list[tuple[float, float, float, float]] = [
            tuple(
                1.0 / ((1.0 - _BM25F_B[fi]) + _BM25F_B[fi] * dl[fi] / avg[fi])
                for fi in range(_BM25F_NFIELDS)
            )  # type: ignore[misc]
            for dl in doc_len
        ]

    def score(self, terms: list[str]) -> dict[int, tuple[float, int]]:
        """BM25F accumulation over matching postings only.

        Returns ``doc -> (score, matched_terms)``. ``matched_terms`` feeds the
        coordination factor in the caller (the legacy scorer's
        ``0.5 + 0.5 * query_coverage`` multiplier, preserved): an entry
        matching BOTH concepts of "find walls" must outrank one matching only
        "wall" harder than per-term saturation alone can express.
        """
        acc: dict[int, float] = {}
        matched: dict[int, int] = {}
        n = self.n_docs
        k1 = _BM25F_K1
        w0, w1, w2, w3 = _BM25F_W
        for term in terms:
            plist = self.postings.get(term)
            if not plist:
                continue
            df = len(plist)
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            if idf <= 0.0:
                continue
            for doc, tf0, tf1, tf2, tf3 in plist:
                norm = self.doc_norm[doc]
                tft = 0.0
                if tf0:
                    tft += w0 * tf0 * norm[0]
                if tf1:
                    tft += w1 * tf1 * norm[1]
                if tf2:
                    tft += w2 * tf2 * norm[2]
                if tf3:
                    tft += w3 * tf3 * norm[3]
                if tft > 0.0:
                    acc[doc] = acc.get(doc, 0.0) + idf * tft / (k1 + tft)
                    matched[doc] = matched.get(doc, 0) + 1
        return {doc: (s, matched[doc]) for doc, s in acc.items()}


# C#/.NET identifier shaped tokens — class names, members, dotted access
# (``ElementId``, ``IntegerValue``, ``doc.Selection``, ``OST_Walls``). Used to
# mine the high-signal API symbols out of a negative-knowledge ``wrong_form`` so
# a query naming the removed/absent API hits the edge that warns against it.
_API_SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
# Tokens that are pure C# noise (keywords/primitives) — never useful as a hook.
_API_SYMBOL_NOISE = frozenset({
    "var", "new", "true", "false", "null", "void", "return", "using", "public",
    "private", "protected", "static", "int", "long", "bool", "double", "float",
    "string", "object", "if", "else", "for", "foreach", "while", "in", "is",
    "as", "this", "out", "ref", "await", "async",
})


def _is_signature_shaped(ex: str) -> bool:
    """A single-line bare method/property signature, not runnable code.

    Local mirror of ``scripts/corpus_gate._is_signature_shaped`` (the audit's junk
    heuristic) — duplicated rather than imported because ``scripts/`` is not an
    importable package from the runtime path, and the hot retrieval path must not
    depend on tooling. Kept byte-aligned with the gate so "what the audit counts
    as a bare signature" and "what retrieval demotes" are the SAME definition.
    """
    if not isinstance(ex, str):
        return False
    s = ex.strip()
    return (
        "\n" not in s
        and (s.startswith("public ") or s.startswith("protected "))
    )


def _is_signature_only_entry(entry: "ApiEntry") -> bool:
    """True if this entry's ONLY substance is bare signature(s).

    An entry is "signature-only" when it has at least one example, EVERY one of
    those examples is signature-shaped, and it carries no rich (v4) example. Such
    an entry looks populated but is not a verified, runnable pattern — it must not
    be allowed to outrank a real recipe / rich example / edge for the same query
    (the anti-overconfidence demotion). Entries with NO examples are NOT flagged
    here: they are simply un-substantive, not a signature *masquerading* as one.
    """
    try:
        if getattr(entry, "rich_examples", None):
            return False
        examples = getattr(entry, "examples", None) or []
        if not examples:
            return False
        return all(_is_signature_shaped(ex) for ex in examples)
    except Exception:
        return False


def _extract_api_symbols(text: str) -> set[str]:
    """Mine CamelCase / dotted C# identifiers from a code-ish string.

    Returns BOTH the whole dotted path (``doc.Selection``) and each segment
    (``doc``, ``Selection``) so the symbol is reachable however the query
    phrases it. Pure C# keywords/primitives are dropped. Never raises.
    """
    out: set[str] = set()
    try:
        for m in _API_SYMBOL_RE.finditer(text or ""):
            tok = m.group(0)
            segments = tok.split(".")
            # The whole dotted path is a strong hook if it has >1 segment.
            if len(segments) > 1:
                out.add(tok)
            for seg in segments:
                if len(seg) < 2:
                    continue
                if seg.lower() in _API_SYMBOL_NOISE:
                    continue
                out.add(seg)
    except Exception:
        pass
    return out


def _normalize_examples(raw: Any) -> tuple[list[str], list[dict]]:
    """Schema-v4 dual-form example normalization (IRON 5).

    An ``examples`` array element is EITHER a legacy string (grandfathered —
    passes straight through, byte-identical) OR a v4 object. For objects:
      * their ``code`` is added to the legacy string list (so every existing
        code-render path keeps working unchanged), AND
      * the whole object is kept in the rich list, normalized to the plan-013
        injection contract keys: ``{title, code, when, why, verified_on,
        caveats}`` (only ``code`` required).

    The plan-011 v4 schema names some keys in Russian (``use_when_ru``,
    ``explanation_ru``, ``pitfalls``, ``compiles_on``, ``verified_at``); those
    are mapped onto the contract keys here so both the prompt renderer and the
    downstream injection path (plan 013) see one canonical shape. The original
    keys are preserved too (we only ADD aliases), so nothing is lost.

    Malformed objects (no ``code``) are skipped with a debug log — they never
    enter either list.

    Returns ``(legacy_strings, rich_objects)``.
    """
    if not isinstance(raw, list):
        return [], []

    legacy: list[str] = []
    rich: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            legacy.append(item)
            continue
        if isinstance(item, dict):
            code = item.get("code")
            if not isinstance(code, str) or not code.strip():
                logger.debug("Skipping malformed rich example (no 'code'): %r", item)
                continue
            legacy.append(code)
            rich.append(_normalize_rich_example(item))
            continue
        logger.debug("Skipping non-str/non-dict example: %r", type(item).__name__)
    return legacy, rich


def _normalize_rich_example(item: dict) -> dict:
    """Canonicalize a v4 example object onto the plan-013 contract keys.

    Adds the contract aliases (``when``/``why``/``verified_on``/``caveats``)
    while preserving the original v4 keys. ``code`` is required and assumed
    present (caller validates). Idempotent and never raises.
    """
    out = dict(item)  # preserve all original keys

    # when ← use_when_ru
    if "when" not in out and out.get("use_when_ru"):
        out["when"] = out["use_when_ru"]

    # why ← explanation_ru (+ pitfalls appended, mirroring the renderer's
    # ПОЧЕМУ/ГРАБЛИ join, so 013 gets the full rationale in one field)
    if "why" not in out:
        why = out.get("explanation_ru") or ""
        pitfalls = out.get("pitfalls")
        if isinstance(pitfalls, list) and pitfalls:
            joined = "; ".join(str(p) for p in pitfalls)
            why = f"{why}; {joined}" if why else joined
        if why:
            out["why"] = why

    # verified_on ← compiles_on (list of year-strings)
    if "verified_on" not in out:
        compiles_on = out.get("compiles_on")
        if isinstance(compiles_on, list) and compiles_on:
            out["verified_on"] = [str(v) for v in compiles_on]

    # caveats ← pitfalls joined (string form, per the 013 contract)
    if "caveats" not in out:
        pitfalls = out.get("pitfalls")
        if isinstance(pitfalls, list) and pitfalls:
            out["caveats"] = "; ".join(str(p) for p in pitfalls)

    return out


@dataclass
class ApiEntry:
    """A single entry in the Revit API knowledge base."""
    name: str
    namespace: str
    entry_type: str  # "class", "category", "parameter", "recipe", "version", "methodology", "formula", "table", "rule", "checklist"
    description: str
    methods: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    # Schema-v4 dual-form examples (IRON 5). Each element is the WHOLE rich
    # example object (see corpus-schema-v4.md). Its `code` is ALSO mirrored into
    # `examples` above so the legacy string path is byte-identical. Field name
    # and object keys match the plan-013 injection contract: objects of shape
    # {title?, code, when?, why?, verified_on?, caveats?} (only `code` required).
    rich_examples: list[dict] = field(default_factory=list)
    keywords_ru: list[str] = field(default_factory=list)
    keywords_en: list[str] = field(default_factory=list)
    # enum-specific: the JSON db has 561 enum-type classes, each with the
    # full list of enum members as "<Name> — <description>" lines. These
    # are the GROUND TRUTH labels the LLM should use when rendering enum
    # values into user-facing text. Without this in the prompt context,
    # the LLM invents Russian/English labels (F-NEW-027). Populated for
    # `type == "enum"` JSON entries; empty otherwise.
    enum_values: list[str] = field(default_factory=list)
    is_enum: bool = False
    # Revit version this API was introduced in, e.g. "2024" ("" = unknown).
    # Used to filter out APIs that don't exist yet in the project's version.
    since: str = ""
    # Version-truth diffed from the per-version api_surface files (plan 012).
    # `introduced`: first Revit version the type exists in (back-filled from the
    # diff when `since` is empty). `removed_in`: first version the type is ABSENT
    # after having existed — an API the project's Revit no longer has. Both ""
    # when unknown / present in every version. Annotated at load() time; the
    # legacy `since` key above is left untouched.
    introduced: str = ""
    removed_in: str = ""
    # Recipe compile-applicability stamps (plan 010): list of Revit versions the
    # recipe's code compiled on, e.g. ["2021",...,"2025"]. Empty for non-recipes
    # or unstamped recipes. Used by the version filter (plan 012 Step 5.5).
    compiles_on: list[str] = field(default_factory=list)
    # Pre-computed normalized keyword tokens for fast matching
    _tokens: set[str] = field(default_factory=set, repr=False)
    # Primary tokens (from keywords and class name) — weighted higher
    _primary_tokens: set[str] = field(default_factory=set, repr=False)
    # Extension system fields
    extension_id: str = ""  # empty = Layer 0 (core API), non-empty = Layer 1 (extension)
    formula: str = ""
    regulatory_ref: str = ""
    content_ru: str = ""
    # Wave-2 batch G (intent-join, KUKAI_RAG_INTENT_JOIN): the recipe corpus's
    # own `intent` field (create/modify/delete/write/query/read/count/list/
    # schedule/analysis/coordination/composite), normalized to lowercase at
    # load time. ``None`` for non-recipe entries and for recipes missing the
    # field (~81/479 in the current db) — the ranking adjustment (kukai.rag.
    # retrieval.apply_intent_join) treats ``None`` as "no signal, don't touch".
    intent: Optional[str] = None
    # Capability-first RAG, Stage 2 (CAPABILITY_FIRST_RAG.md §3/§6 step 1-2):
    # the recipe corpus's own `capability` signature — Stage 1
    # (CAPABILITY_CATALOG.md) tagged all 479 recipes with
    # ``{action, object_kinds, produces, requires_selection, domain}``.
    # Normalized at load time (action lowercased, object_kinds lowercased) so
    # the ranking-side match in kukai.rag.retrieval.apply_capability_resolve
    # can compare case-insensitively without re-normalizing per query.
    # ``None`` for non-recipe entries and for any recipe missing the field
    # (none, as of Stage 1, but the type stays Optional for defensiveness) —
    # treated as "no capability signal, don't touch" everywhere it's read.
    capability: Optional[dict] = None

    def relevance_text(self, max_chars: int = 1500) -> str:
        """Format this entry for injection into the system prompt.

        Priority: examples > short description > methods.
        Examples are the most valuable for code generation — LLMs follow
        working code patterns more reliably than API descriptions.
        """
        parts: list[str] = []

        if self.entry_type == "class":
            parts.append(f"### {self.namespace}.{self.name}")
            # Short description (truncate to ~200 chars — save space for examples)
            desc = self.description
            if len(desc) > 200:
                desc = desc[:197] + "..."
            parts.append(desc)
            # Code examples FIRST (most valuable for code generation)
            # Show examples that demonstrate API usage patterns.
            # Even truncated examples are useful if they show the key API call.
            if self.examples:
                examples_to_show = self.examples[:3]
                if examples_to_show:
                    parts.append("Code examples:")
                    for ex in examples_to_show:
                        parts.append(f"```csharp\n{ex}\n```")
            # Methods AFTER examples (supplementary)
            if self.methods:
                parts.append(f"Methods: {', '.join(self.methods[:15])}")
        elif self.entry_type == "category":
            parts.append(f"BuiltInCategory.{self.name} — {self.description}")
        elif self.entry_type == "parameter":
            parts.append(f"BuiltInParameter.{self.name} — {self.description}")
        elif self.entry_type == "recipe":
            parts.append(f"### Recipe: {self.description}")
            if self.examples:
                parts.append(f"```csharp\n{self.examples[0]}\n```")
        elif self.entry_type == "version":
            parts.append(f"### Version info: {self.name}")
            parts.append(self.description)
        elif self.entry_type == "methodology":
            parts.append(f"### Методика: {self.name}")
            parts.append(self.description)
            if self.content_ru:
                parts.append(self.content_ru)
            if self.formula:
                parts.append(f"Формула: `{self.formula}`")
            if self.regulatory_ref:
                parts.append(f"Источник: {self.regulatory_ref}")
        elif self.entry_type == "formula":
            parts.append(f"### Формула: {self.name}")
            parts.append(self.description)
            if self.formula:
                parts.append(f"```\n{self.formula}\n```")
            if self.regulatory_ref:
                parts.append(f"Источник: {self.regulatory_ref}")
        elif self.entry_type == "rule":
            parts.append(f"### Правило: {self.name}")
            if self.content_ru:
                parts.append(self.content_ru)
            if self.regulatory_ref:
                parts.append(f"Источник: {self.regulatory_ref}")
        elif self.entry_type == "edge":
            # Negative knowledge — a verified API/version BOUNDARY ("memory's
            # edge"). The content_ru already carries the
            # "<fact> · НЕ так: <wrong> → НАДО: <correct> (<versions>)" line built
            # by _load_negative_knowledge; render it under a loud marker so the
            # model treats it as a hard "do NOT do this" fact, not an example to
            # imitate.
            parts.append(f"### ⚠ Граница API: {self.name}")
            if self.content_ru:
                parts.append(self.content_ru)
        elif self.entry_type in ("table", "checklist"):
            parts.append(f"### {self.name}")
            parts.append(self.description)
            if self.content_ru:
                parts.append(self.content_ru)

        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text


class RevitApiIndex:
    """In-memory Revit API knowledge base with keyword + semantic search."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        embeddings_path: Optional[Path] = None,
        openai_api_key: Optional[str] = None,
    ):
        self._entries: list[ApiEntry] = []
        self._loaded = False
        self._db_path = db_path or (
            Path(__file__).parent.parent.parent / "data" / "revit_api_db.json"
        )
        self._embeddings_path = embeddings_path or (
            Path(__file__).parent.parent.parent / "data" / "rag_embeddings.npz"
        )
        self._openai_api_key = openai_api_key or os.environ.get(
            "KUKAI_OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")
        )

        # Embedding data — loaded lazily
        self._vectors: Optional[Any] = None  # np.ndarray (N, 3072)
        self._vector_ids: Optional[list[str]] = None
        self._embeddings_loaded = False
        # Map from entry_id -> index in self._entries for fast lookup
        self._entry_id_map: dict[str, int] = {}
        # Extension system — profiles keyed by extension id
        self._extension_profiles: dict[str, str] = {}
        # Extension metadata for listing (id -> {name_ru, name_en, icon})
        self._extension_meta: dict[str, dict[str, str]] = {}
        # Phrasings (Doc2Query, Path B) — lazy. Constructed on first search
        # so the file is read in the request thread, not at app import time.
        self._phrasing_index: Optional[Any] = None
        # BM25F inverted index (flag KUKAI_BM25F) — lazy; None until the first
        # flagged keyword search. Guarded by a lock: keyword_search runs in
        # asyncio worker threads and two first-searches must not double-build.
        self._bm25f: Optional[_Bm25fIndex] = None
        self._bm25f_lock = threading.Lock()
        # Tokenizer mode the entry tokens were built with (KUKAI_LEMMA_LEXICON
        # at load() time): True = lemma, False = legacy stripper, None = not
        # loaded yet. Queries normalize with the CURRENT flag, so a post-load
        # flip would silently zero recall — _ensure_token_mode() rebuilds.
        self._token_mode: Optional[bool] = None
        # Bilingual-primaries mode the entries were built with (IQ #6,
        # KUKAI_BILINGUAL_RETRIEVAL at load() time). A post-load flip changes
        # WHICH tokens are primary (and therefore the BM25F field split), so
        # it triggers the same rebuild as a tokenizer flip. Kept as a separate
        # stamp (not folded into _token_mode) so the lemma guard's pinned
        # contract — tests assert `_token_mode is True/False` — is untouched.
        self._bilingual_mode: Optional[bool] = None
        self._token_mode_lock = threading.Lock()
        # Corpus manifest disclosure (IRON 5): set by _load_embeddings.
        # "unchecked" until load; "ok" | "mismatch:<detail>" | "absent" | "error"
        # afterwards. The health layer can expose this. The Mint gates WRITES,
        # not reads — a bad/missing manifest never blocks retrieval (Article 9).
        self.manifest_status: str = "unchecked"

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def has_embeddings(self) -> bool:
        """True if embeddings are loaded and ready for semantic search."""
        return self._embeddings_loaded and self._vectors is not None

    def load(self) -> None:
        """Load the Revit API database from JSON and optionally load embeddings."""
        if self._loaded:
            return

        # Stamp the tokenizer mode this load builds tokens with (IQ #7): every
        # _make_tokens call below flows through _normalize_token, which reads
        # the flag at call time. _ensure_token_mode() compares against this.
        self._token_mode = _lemma_lexicon_enabled()
        # Stamp the bilingual-primaries mode too (IQ #6): _load_classes reads
        # the flag when choosing the primary-token set.
        self._bilingual_mode = _bilingual_retrieval_enabled()

        if not self._db_path.exists():
            logger.warning("Revit API database not found at %s", self._db_path)
            self._loaded = True
            return

        try:
            data = json.loads(self._db_path.read_text(encoding="utf-8"))
            self._load_classes(data.get("classes", []))
            self._load_categories(data.get("builtin_categories", []))
            self._load_parameters(data.get("builtin_parameters", []))
            # Hand-written "recipes" (the entries in revit_api_db.json) were
            # compile-verified against Revit 2021–2026 on 2026-06 (see
            # scripts/resurrect_recipes.py); the flag stays for rollback.
            # Set KUKAI_RAG_RECIPES_ENABLED=1 to load them.
            # NOTE: the auto-collected verified_recipes.db corpus is a SEPARATE
            # system (recipes_collector.py) and is unaffected by this flag.
            if os.getenv("KUKAI_RAG_RECIPES_ENABLED", "0") == "1":
                self._load_recipes(data.get("recipes", []))
            else:
                logger.info(
                    "Revit API recipes disabled (KUKAI_RAG_RECIPES_ENABLED=0): "
                    "skipped %d hand-written recipes",
                    len(data.get("recipes", [])),
                )
            self._load_versions(data.get("version_differences", []))
            self._load_unit_conversions(data.get("unit_conversions", {}) or {})
            # Negative knowledge — verified API/version BOUNDARY truths ("the
            # edges of memory"). Loaded UNCONDITIONALLY from its OWN file
            # (data/negative_knowledge.json), independent of revit_api_db.json:
            # these are always-valid boundary facts that must be retrievable so
            # the model stops hallucinating removed/absent APIs (IRON 5/10). A
            # missing/bad file is non-fatal — the loader logs and returns.
            self._load_negative_knowledge()
            # Version-truth annotation (plan 012, IRON 4/5): stamp each class
            # entry with {introduced, removed_in} diffed from the per-version
            # api_surface files. Non-fatal — if api_versions.json is absent the
            # helpers fail open (return None) and entries keep their legacy
            # `since`-only behaviour. `since` is preserved untouched.
            try:
                from kukai.rag.api_versions import type_removed_in, type_introduced
                for e in self._entries:
                    if e.entry_type == "class":
                        full = f"{e.namespace}.{e.name}"
                        e.removed_in = type_removed_in(full) or ""
                        e.introduced = type_introduced(full) or (e.since or "")
            except Exception:
                logger.exception("api_versions annotation failed (non-fatal)")
            self._loaded = True
            logger.info(
                "Revit API index loaded: %d entries from %s",
                len(self._entries),
                self._db_path,
            )
        except Exception:
            logger.exception("Failed to load Revit API database")
            self._loaded = True  # Mark loaded so we don't retry

        # Load extension entries (non-fatal if it fails)
        self._load_extensions()

        # Try loading embeddings (non-fatal if it fails)
        self._load_embeddings()

    def _make_tokens(self, keywords_ru: list[str], keywords_en: list[str],
                     extra_text: str = "") -> set[str]:
        """Build a set of normalized tokens from keywords and extra text."""
        tokens: set[str] = set()
        for kw in keywords_ru:
            tokens.update(_tokenize(kw))
        for kw in keywords_en:
            tokens.update(_tokenize(kw))
        if extra_text:
            tokens.update(_tokenize(extra_text))
        return tokens

    @staticmethod
    def _collect_all_keywords(data: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Collect keywords from all keywords_* fields dynamically.

        Returns (all_keywords_combined, all_keywords_en) where
        all_keywords_combined is every keyword from every language,
        and all_keywords_en is specifically from keywords_en (for
        backward-compat with ApiEntry).
        """
        all_kw: list[str] = []
        kw_en: list[str] = []
        for key, val in data.items():
            if key.startswith("keywords_") and isinstance(val, list):
                all_kw.extend(val)
                if key == "keywords_en":
                    kw_en = val
        return all_kw, kw_en

    def _load_classes(self, classes: list[dict[str, Any]]) -> None:
        for cls in classes:
            all_kw, kw_en = self._collect_all_keywords(cls)
            examples, rich = _normalize_examples(cls.get("examples", []))
            entry = ApiEntry(
                name=cls["name"],
                namespace=cls.get("namespace", "Autodesk.Revit.DB"),
                entry_type="class",
                description=cls.get("description", ""),
                methods=cls.get("methods", []),
                examples=examples,
                rich_examples=rich,
                keywords_ru=cls.get("keywords_ru", []),
                keywords_en=kw_en,
                enum_values=cls.get("enum_values", []),
                is_enum=(cls.get("type") == "enum"),
                since=str(cls.get("since", "") or ""),
            )
            # Primary tokens: ENGLISH keywords + class name only.
            # Russian keywords excluded from primary — the production pipeline
            # translates queries to English before RAG search, so Russian
            # tokens in primary only add noise (e.g., "модель" in 1475 classes).
            #
            # IQ #6 (KUKAI_BILINGUAL_RETRIEVAL, default OFF): under the flag
            # the search query is the RAW RU message (translation is a
            # parallel enrichment, not a prerequisite — see
            # kukai/rag/retrieval.py), so the curated RU keywords become
            # FIRST-CLASS primaries. They flow through the SAME
            # _make_tokens/_normalize_token path as everything else — lemma-
            # normalized under KUKAI_LEMMA_LEXICON, BM25F-posted into the
            # high-weight keywords field (w=2.5, b=0) under KUKAI_BM25F,
            # where IDF is the honest control for flood terms like "модель".
            # Language-agnostic on purpose: ALL keywords_* fields promote,
            # not just _ru (model-agnostic principle — words are data).
            if _bilingual_retrieval_enabled():
                entry._primary_tokens = self._make_tokens(
                    all_kw, [], cls["name"]
                )
            else:
                entry._primary_tokens = self._make_tokens(
                    [], kw_en, cls["name"]
                )
            # All tokens: primary + method names + Russian keywords (for direct RU search fallback)
            extra = cls["name"] + " " + " ".join(cls.get("methods", []))
            entry._tokens = self._make_tokens(
                all_kw, [], extra
            )
            self._entries.append(entry)

    def _load_categories(self, categories: list[dict[str, Any]]) -> None:
        for cat in categories:
            name_ru = cat.get("name_ru", "")
            name_en = cat.get("name_en", "")
            enum_val = cat["enum"]
            # Collect all name_* and keywords_* fields dynamically
            all_kw: list[str] = [enum_val]
            for key, val in cat.items():
                if key.startswith("name_") and isinstance(val, str) and val:
                    all_kw.append(val)
                elif key.startswith("keywords_") and isinstance(val, list):
                    all_kw.extend(val)
            entry = ApiEntry(
                name=enum_val,
                namespace="Autodesk.Revit.DB",
                entry_type="category",
                description=f"{name_ru} ({name_en})",
                keywords_ru=[name_ru] if name_ru else [],
                keywords_en=[name_en, enum_val] if name_en else [enum_val],
            )
            tokens = self._make_tokens(all_kw, [], enum_val)
            entry._tokens = tokens
            entry._primary_tokens = tokens
            self._entries.append(entry)

    def _load_parameters(self, parameters: list[dict[str, Any]]) -> None:
        for param in parameters:
            name_ru = param.get("name_ru", "")
            name_en = param.get("name_en", "")
            enum_val = param["enum"]
            param_type = param.get("type", "")
            # Collect all name_* and keywords_* fields dynamically
            all_kw: list[str] = [enum_val]
            for key, val in param.items():
                if key.startswith("name_") and isinstance(val, str) and val:
                    all_kw.append(val)
                elif key.startswith("keywords_") and isinstance(val, list):
                    all_kw.extend(val)
            # If this integer parameter is actually an enum stored as int,
            # the JSON has `enum_class` pointing to the matching enum class.
            # We encode that link into the description so the formatter can
            # render the converter hint and the LLM stops hand-mapping ints
            # to invented labels (F-NEW-027 deep root cause).
            enum_class = param.get("enum_class", "")
            if enum_class:
                desc = (
                    f"{name_ru} ({name_en}) — type: {param_type}, "
                    f"backed by enum {enum_class}"
                )
            else:
                desc = f"{name_ru} ({name_en}) — type: {param_type}"
            entry = ApiEntry(
                name=enum_val,
                namespace="Autodesk.Revit.DB",
                entry_type="parameter",
                description=desc,
                keywords_ru=[name_ru] if name_ru else [],
                keywords_en=[name_en, enum_val] if name_en else [enum_val],
            )
            # Stash the enum_class link as a method-like hint so the
            # formatter's existing methods rendering carries it through.
            # This way no new field is needed on ApiEntry, and the loader
            # treats parameters and enum-backed-parameters uniformly.
            if enum_class:
                entry.methods = [
                    f"backed by enum {enum_class} — "
                    f"use Enum.GetName(typeof({enum_class}), value) to get the name"
                ]
            tokens = self._make_tokens(all_kw, [], enum_val + " " + name_en)
            entry._tokens = tokens
            entry._primary_tokens = tokens
            self._entries.append(entry)

    def _load_recipes(self, recipes: list[dict[str, Any]]) -> None:
        for recipe in recipes:
            all_kw, kw_en = self._collect_all_keywords(recipe)
            # A recipe object IS its own rich-example form: it already carries
            # code + compiles_on/verified_at (plan 010 stamps). Promote it to a
            # rich example when it is a stamped, code-bearing object so the
            # КОГДА/ПОЧЕМУ render path (and plan-013 injection) can use it.
            rich: list[dict] = []
            if isinstance(recipe.get("code"), str) and recipe.get("verified_at"):
                rich = [_normalize_rich_example(recipe)]
            # Wave-2 batch G: the recipe's own `intent` field, normalized to
            # lowercase (the db mixes case — e.g. "WRITE"/"write") so the
            # ranking-side match in kukai.rag.retrieval can compare it
            # case-insensitively without re-normalizing on every query.
            # Absent/blank/non-string -> None ("no signal").
            _raw_intent = recipe.get("intent")
            _intent = (
                _raw_intent.strip().lower()
                if isinstance(_raw_intent, str) and _raw_intent.strip()
                else None
            )
            # Capability-first RAG, Stage 2: normalize the Stage-1 `capability`
            # signature the same way `intent` is normalized above — lowercase
            # action + object_kinds, tolerant of a malformed/missing block
            # (fail-open to None, "no capability signal" downstream).
            _raw_cap = recipe.get("capability")
            _capability: Optional[dict] = None
            if isinstance(_raw_cap, dict):
                _cap_action = _raw_cap.get("action")
                _cap_kinds = _raw_cap.get("object_kinds") or []
                _capability = {
                    "action": (
                        _cap_action.strip().lower()
                        if isinstance(_cap_action, str) and _cap_action.strip()
                        else None
                    ),
                    "object_kinds": [
                        k.strip().lower()
                        for k in _cap_kinds
                        if isinstance(k, str) and k.strip()
                    ] if isinstance(_cap_kinds, list) else [],
                    "produces": _raw_cap.get("produces"),
                    "requires_selection": bool(_raw_cap.get("requires_selection", False)),
                    "domain": _raw_cap.get("domain"),
                }
            entry = ApiEntry(
                name=recipe.get("name", ""),
                namespace="",
                entry_type="recipe",
                description=recipe.get("description", recipe.get("name", "")),
                examples=[recipe["code"]] if "code" in recipe else [],
                rich_examples=rich,
                keywords_ru=recipe.get("keywords_ru", []),
                keywords_en=kw_en,
                compiles_on=[
                    str(v) for v in (recipe.get("compiles_on") or [])
                    if isinstance(v, (str, int))
                ],
                intent=_intent,
                capability=_capability,
            )
            tokens = self._make_tokens(
                all_kw, [],
                recipe.get("name", "") + " " + recipe.get("description", ""),
            )
            entry._tokens = tokens
            entry._primary_tokens = tokens
            self._entries.append(entry)

    def _load_versions(self, versions: list[dict[str, Any]]) -> None:
        for ver in versions:
            all_kw, kw_en = self._collect_all_keywords(ver)
            entry = ApiEntry(
                name=ver.get("versions", ""),
                namespace="",
                entry_type="version",
                description=f"{ver.get('framework', '')} — {ver.get('notes', '')}",
                keywords_ru=ver.get("keywords_ru", []),
                keywords_en=kw_en,
            )
            tokens = self._make_tokens(
                all_kw, [], ver.get("versions", "")
            )
            entry._tokens = tokens
            entry._primary_tokens = tokens
            self._entries.append(entry)

    def _load_unit_conversions(self, uc: dict[str, Any]) -> None:
        """Surface the unit-conversion table as ONE retrievable 'rule' entry.

        Revit stores lengths in feet internally — the most common silent-wrong
        class for a weak model is returning feet as if they were mm. The data
        lives in revit_api_db.json's unit_conversions (restored 2026-06);
        without this entry nothing reads it at runtime.
        """
        if not uc:
            return
        lines = []
        for group, vals in uc.items():
            if group == "notes" or not isinstance(vals, dict):
                continue
            pairs = ", ".join(f"{k} = {v}" for k, v in vals.items())
            lines.append(f"{group}: {pairs}")
        if uc.get("notes"):
            lines.append(str(uc["notes"]))
        lines.append(
            "Внутренние единицы Revit: длины в ФУТАХ (мм = feet * 304.8), "
            "площади в кв. футах, объёмы в куб. футах. Всегда конвертируй "
            "перед выводом пользователю."
        )
        entry = ApiEntry(
            name="Units: Revit internal units (feet)",
            namespace="",
            entry_type="rule",
            description="Конвертация единиц: внутренние единицы Revit — футы.",
            keywords_ru=["единицы", "конвертация", "перевод", "миллиметр", "мм",
                         "метр", "площадь", "объём", "фут", "футы", "длина"],
            keywords_en=["units", "convert", "conversion", "mm", "millimeter",
                         "meter", "feet", "area", "volume", "length", "internal units"],
            content_ru="\n".join(lines),
        )
        tokens = self._make_tokens(entry.keywords_ru, entry.keywords_en, entry.name)
        entry._tokens = tokens
        entry._primary_tokens = tokens
        self._entries.append(entry)

    def _negative_knowledge_path(self) -> Path:
        """Path to the negative-knowledge file (sibling of revit_api_db.json)."""
        return self._db_path.parent / "negative_knowledge.json"

    def _load_negative_knowledge(self) -> None:
        """Surface verified API/version BOUNDARY facts as retrievable 'edge' entries.

        Each entry of ``data/negative_knowledge.json`` becomes ONE ``entry_type
        == "edge"`` ``ApiEntry`` (mirroring the ``_load_unit_conversions`` "rule"
        pattern). These are ALWAYS-VALID boundary truths — what does NOT exist,
        what was removed in which Revit version, and the confident-wrong traps a
        weak model writes from memory — so they are loaded UNCONDITIONALLY (no
        feature flag): a memory that holds the right APIs but not its OWN edges
        makes confident-wrong decisions.

        Keywording: the title, every CamelCase / dotted symbol mined from the
        ``wrong_form`` (e.g. ``IntegerValue``, ``DisplayUnitType``,
        ``doc.Selection``), and the RU content terms in ``fact_ru`` all become
        searchable tokens, so a query about the removed/absent API surfaces the
        edge that warns against it.

        Content: ``"<fact_ru> · НЕ так: <wrong_form> → НАДО: <correct_form>
        (<applies_versions>)"`` — the render path (``relevance_text`` "edge"
        branch) marks it as a hard boundary, not an example to imitate.

        Never throws: a missing/malformed file logs and returns; the live
        retrieval/loader path is unaffected (Article 9 — reads never blocked).
        """
        try:
            path = self._negative_knowledge_path()
            if not path.exists():
                logger.info("Negative knowledge file not found at %s (skipped)", path)
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data.get("entries", []) if isinstance(data, dict) else []
            if not isinstance(entries, list):
                logger.warning("negative_knowledge.json 'entries' is not a list — skipped")
                return
            loaded = 0
            for nk in entries:
                if not isinstance(nk, dict):
                    continue
                try:
                    self._add_negative_knowledge_entry(nk)
                    loaded += 1
                except Exception:
                    # One bad entry must not drop the rest.
                    logger.exception("Skipping malformed negative-knowledge entry")
            logger.info("Negative knowledge loaded: %d edge entries from %s", loaded, path)
        except Exception:
            logger.exception("Failed to load negative knowledge (non-fatal)")

    def _add_negative_knowledge_entry(self, nk: dict[str, Any]) -> None:
        """Build and append ONE ``edge`` ApiEntry from a negative-knowledge dict."""
        title = str(nk.get("title", "") or "").strip()
        if not title:
            return
        fact_ru = str(nk.get("fact_ru", "") or "").strip()
        wrong_form = str(nk.get("wrong_form", "") or "").strip()
        correct_form = str(nk.get("correct_form", "") or "").strip()
        versions = str(nk.get("applies_versions", "") or "").strip()
        kind = str(nk.get("kind", "") or "").strip()

        # The injected content: fact + the НЕ так / НАДО boundary line.
        content_parts: list[str] = []
        if fact_ru:
            content_parts.append(fact_ru)
        boundary = ""
        if wrong_form:
            boundary = f"НЕ так: {wrong_form}"
            if correct_form:
                boundary += f" → НАДО: {correct_form}"
            if versions:
                boundary += f" ({versions})"
        elif correct_form:
            boundary = f"НАДО: {correct_form}"
            if versions:
                boundary += f" ({versions})"
        if boundary:
            content_parts.append(boundary)
        content_ru = "\n".join(content_parts)

        # Keyword sources: API symbols from title + wrong_form + correct_form
        # (CamelCase / dotted identifiers), and RU terms from the fact.
        symbols = _extract_api_symbols(f"{title}\n{wrong_form}\n{correct_form}")
        keywords_en = sorted(symbols)
        keywords_ru: list[str] = []
        if kind:
            keywords_ru.append(kind)
        if versions:
            keywords_ru.append(versions)

        entry = ApiEntry(
            name=title[:120],
            namespace="",
            entry_type="edge",
            description=fact_ru[:300] if fact_ru else title,
            keywords_ru=keywords_ru,
            keywords_en=keywords_en,
            content_ru=content_ru,
        )
        # Tokens drawn from the symbols, the title, AND the RU fact, so both an
        # English API-name query ("ElementId.IntegerValue") and a Russian
        # capability query ("создать легенду") can hit the right edge.
        tokens = self._make_tokens(
            keywords_ru, keywords_en, f"{title} {fact_ru}"
        )
        entry._tokens = tokens
        # Primary tokens = the API symbols + the title (the high-signal hooks).
        entry._primary_tokens = self._make_tokens([], keywords_en, title)
        self._entries.append(entry)

    def get_extension_profile(self, extension_id: str) -> str:
        """Return the profile text for an extension, or empty string."""
        return self._extension_profiles.get(extension_id, "")

    def get_extensions_list(self) -> list[dict[str, str]]:
        """Return list of available extensions with metadata."""
        return [
            {"id": ext_id, **meta}
            for ext_id, meta in self._extension_meta.items()
        ]

    def _load_extensions(self) -> None:
        """Scan data/extensions/ for ext-*.json files and load entries."""
        extensions_dir = self._db_path.parent / "extensions"
        if not extensions_dir.is_dir():
            logger.debug("No extensions directory at %s", extensions_dir)
            return

        loaded_count = 0
        for ext_file in sorted(extensions_dir.glob("ext-*.json")):
            try:
                ext_data = json.loads(ext_file.read_text(encoding="utf-8"))
                ext_id = ext_data.get("id", "")
                if not ext_id:
                    logger.warning("Extension file %s has no 'id' field, skipping", ext_file.name)
                    continue

                # Store profile
                profile = ext_data.get("profile_ru", "")
                if profile:
                    self._extension_profiles[ext_id] = profile

                # Store metadata for listing
                self._extension_meta[ext_id] = {
                    "name_ru": ext_data.get("name_ru", ext_id),
                    "name_en": ext_data.get("name_en", ext_id),
                    "icon": ext_data.get("icon", "box"),
                }

                # Load entries
                for entry_data in ext_data.get("entries", []):
                    entry_type = entry_data.get("type", "")
                    if entry_type not in ("methodology", "formula", "table", "rule", "checklist"):
                        logger.warning(
                            "Extension %s: unknown entry type '%s', skipping",
                            ext_id, entry_type,
                        )
                        continue

                    kw_ru = entry_data.get("keywords_ru", [])
                    kw_en = entry_data.get("keywords_en", [])
                    name_ru = entry_data.get("name_ru", "")

                    entry = ApiEntry(
                        name=name_ru,
                        namespace=ext_id,
                        entry_type=entry_type,
                        description=entry_data.get("description_ru", ""),
                        keywords_ru=kw_ru,
                        keywords_en=kw_en,
                        extension_id=ext_id,
                        formula=entry_data.get("formula", ""),
                        regulatory_ref=entry_data.get("regulatory_ref", ""),
                        content_ru=entry_data.get("content_ru", ""),
                    )
                    tokens = self._make_tokens(kw_ru, kw_en, name_ru)
                    entry._tokens = tokens
                    entry._primary_tokens = tokens
                    self._entries.append(entry)

                loaded_count += 1
                logger.info(
                    "Extension loaded: %s (%d entries) from %s",
                    ext_id,
                    len(ext_data.get("entries", [])),
                    ext_file.name,
                )
            except Exception:
                logger.warning("Failed to load extension file %s, skipping", ext_file.name, exc_info=True)

        if loaded_count:
            logger.info("Extensions loaded: %d files", loaded_count)

    def _load_embeddings(self) -> None:
        """Load pre-computed embeddings from .npz file."""
        if self._embeddings_loaded:
            return

        if not _HAS_NUMPY:
            logger.debug("numpy not available — semantic search disabled")
            self._embeddings_loaded = True
            return

        if not self._embeddings_path.exists():
            logger.debug("No embeddings file at %s", self._embeddings_path)
            self._embeddings_loaded = True
            return

        try:
            data = np.load(str(self._embeddings_path), allow_pickle=False)
            vectors = data["vectors"]  # shape (N, 3072)
            raw_ids = data["ids"]  # shape (N,) string array
            self._vector_ids = [str(x) for x in raw_ids]

            # Pre-normalize vectors once at load time to avoid O(N*D) per query
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-10)
            self._vectors = vectors / norms

            # Build entry_id -> entry index map
            self._build_entry_id_map()

            logger.info(
                "Embeddings loaded: %d vectors (%d-dim, pre-normalized) from %s",
                self._vectors.shape[0],
                self._vectors.shape[1],
                self._embeddings_path,
            )
        except Exception:
            logger.exception("Failed to load embeddings")
            self._vectors = None
            self._vector_ids = None

        # Corpus manifest disclosure (IRON 5): verify the artifacts match the
        # manifest they were stamped with. Quick check (db sha + npz count/ids)
        # — full vector hashing is the CLI's job, not a startup cost. Loading
        # PROCEEDS on every branch; the Mint gates writes, not reads, and a
        # missing manifest must not take down retrieval (Article 9).
        try:
            from kukai.rag.corpus_manifest import check_manifest
            ok, detail = check_manifest(self._db_path.parent, quick=True)
            # Carry the full detail through on success too: a passing check can
            # still disclose "ok:npz-stale-vs-db" (the npz was built from a
            # different db than the one now loaded) — exactly the silent vector
            # drift the manifest was built to catch (plan 017, IRON 10).
            self.manifest_status = detail if ok else f"mismatch:{detail}"
            if ok and detail.startswith("ok:npz-stale"):
                logger.warning(
                    "Corpus manifest: vectors are STALE vs the current db "
                    "(npz built_from_db_sha256 != revit_api_db.json) — semantic "
                    "results may be desynced from the knowledge base: %s",
                    detail,
                )
            elif not ok:
                logger.warning(
                    "Corpus manifest check FAILED — artifacts may be desynced: %s",
                    detail,
                )
        except FileNotFoundError:
            self.manifest_status = "absent"
            logger.warning(
                "Corpus manifest absent — corpus provenance unverified (IRON 5)."
            )
        except Exception:
            self.manifest_status = "error"
            logger.exception("Corpus manifest check errored (non-fatal)")

        self._embeddings_loaded = True

    def _build_entry_id_map(self) -> None:
        """Build a map from entry_id (used in embeddings) to entry index.

        The IDs must match the format produced by build_rag.py:
        - class:Namespace.ClassName
        - category:ENUM_VALUE
        - parameter:ENUM_VALUE
        - recipe:N:RecipeName  (N = sequential index within recipes)
        - version:N:VersionRange (N = sequential index within versions)
        """
        self._entry_id_map.clear()

        # Track sequential indices per type
        recipe_seq = 0
        version_seq = 0

        for idx, entry in enumerate(self._entries):
            if entry.entry_type == "class":
                entry_id = f"class:{entry.namespace}.{entry.name}"
                # Reconcile legacy embedding IDs: rag_embeddings.npz keys enums
                # and interfaces under "enum:"/"interface:" prefixes, but the
                # current DB loads them as `class` entries. Alias both prefixes
                # to this entry so the ~638 pre-computed enum/interface vectors
                # resolve (semantic coverage 64% -> ~84%) instead of being
                # silently dropped. Harmless for non-enum classes (no vector
                # is ever queried under those alias keys).
                _full = f"{entry.namespace}.{entry.name}"
                self._entry_id_map[f"enum:{_full}"] = idx
                self._entry_id_map[f"interface:{_full}"] = idx
            elif entry.entry_type == "category":
                entry_id = f"category:{entry.name}"
            elif entry.entry_type == "parameter":
                entry_id = f"parameter:{entry.name}"
            elif entry.entry_type == "recipe":
                entry_id = f"recipe:{recipe_seq}:{entry.name}"
                recipe_seq += 1
            elif entry.entry_type == "version":
                entry_id = f"version:{version_seq}:{entry.name}"
                version_seq += 1
            elif entry.entry_type == "rule":
                # Stable id keyed by the rule's name, NOT its position (plan
                # 017). The generic fallback below would key it by index, which
                # shifts with the recipes flag and extension count — so a
                # precomputed `rule:` vector could never reliably resolve.
                entry_id = f"rule:{entry.name}"
            elif entry.entry_type == "edge":
                # Wave-2 batch G (SKIPPED.md §S5-1): mirror the `rule` branch
                # above. Negative-knowledge/edge entries are loaded from
                # data/negative_knowledge.json AFTER recipes — a positional
                # fallback id silently desyncs (61 orphans + 10 wrong-content
                # collisions, verified) every time the recipe count or
                # extension set changes. Name-keyed like `rule` closes that
                # class of bug for good.
                entry_id = f"edge:{entry.name}"
            else:
                entry_id = f"{entry.entry_type}:{idx}"

            self._entry_id_map[entry_id] = idx

    def _get_query_embedding(self, query: str) -> Optional[Any]:
        """Get embedding vector via the shared embedding client (plan 018 §4).

        This method's NAME and SIGNATURE are deliberately preserved — it is the
        seam the benchmark's ``_keyless_semantic`` fixture monkeypatches, and
        ``semantic_search`` calls it. The cache + circuit breaker + the original
        ``httpx`` semantics now live in ``kukai.rag.embedding_client``; here we
        only map the outcome status onto the per-turn health flags so a dead
        endpoint becomes visible (a tripped breaker / a failure are DEGRADED
        turns, where a bare ``empty`` semantic leg used to hide them).
        """
        from kukai.rag.embedding_client import get_query_embedding as _embed

        outcome = _embed(query, api_key_override=self._openai_api_key)
        if outcome.status == "breaker_open":
            # The embedding endpoint is in the breaker's OPEN window — surface
            # it per-turn so retrieval.run_legs can report the semantic leg as
            # ``tripped_breaker`` (a DEGRADED status). No-op without a turn.
            try:
                from kukai.rag.retrieval_health import add_flag as _add_flag009
                _add_flag009("embedding_breaker_open")
            except Exception:
                pass
            return None
        if outcome.status == "failed":
            # plan-009: surface the silent semantic dropout per-turn (no-op
            # without a turn). The embedding client already logged the WARNING.
            try:
                from kukai.rag.retrieval_health import add_flag as _add_flag009
                _add_flag009("embedding_failed")
            except Exception:
                pass
            return None
        # "ok" / "cache_hit" -> vector; "no_key" -> None (semantic unavailable).
        return outcome.vector

    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        active_extension: Optional[str] = None,
    ) -> list[ApiEntry]:
        """Search using cosine similarity against pre-computed embeddings.

        Args:
            query: User's question or search string
            top_k: Maximum number of results to return
            active_extension: If set, filter and boost extension entries.

        Returns:
            List of ApiEntry objects sorted by semantic similarity,
            or empty list if semantic search is unavailable.
        """
        if not self.has_embeddings or not _HAS_NUMPY:
            return []

        query_vec = self._get_query_embedding(query)
        if query_vec is None:
            return []

        # Cosine similarity: dot(q, V_norm) / |q|
        # Stored vectors are pre-normalized at load time
        q_norm = np.linalg.norm(query_vec)
        if q_norm == 0:
            return []
        query_normalized = query_vec / q_norm

        # Compute similarities (vectors already normalized at load)
        similarities = self._vectors @ query_normalized  # shape (N,)

        # Get top-k indices
        # Use argpartition for efficiency on large arrays
        if len(similarities) > top_k:
            top_indices = np.argpartition(similarities, -top_k)[-top_k:]
            top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]
        else:
            top_indices = np.argsort(similarities)[::-1]

        extension_results: list[ApiEntry] = []
        regular_results: list[ApiEntry] = []
        # Relevance gate, centralized + env-tunable (was a hardcoded 0.25 here and
        # in norms_rag). Measured on text-embedding-3-large: nonsense queries top
        # out at ~0.18 cosine, real queries start at ~0.32 — 0.25 sits in the gap.
        from kukai.config import get_settings as _gs
        _thr = _gs().embedding_sim_threshold
        for vec_idx in top_indices:
            sim = float(similarities[vec_idx])
            if sim < _thr:  # Skip low-relevance results
                continue

            vec_id = self._vector_ids[vec_idx]

            # Look up the entry by ID
            entry_idx = self._entry_id_map.get(vec_id)
            if entry_idx is not None and entry_idx < len(self._entries):
                entry = self._entries[entry_idx]
                # Extension filtering (same logic as keyword_search)
                if entry.extension_id:
                    if not active_extension or entry.extension_id != active_extension:
                        continue
                    # x1.5 boost: extension entries sorted first (same as keyword_search)
                    extension_results.append(entry)
                else:
                    regular_results.append(entry)

        # Extension entries first (boost), then regular entries
        return (extension_results + regular_results)[:top_k]

    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
        active_extension: Optional[str] = None,
        entry_type_filter: Optional[str] = None,
    ) -> list[ApiEntry]:
        """Search the knowledge base by keyword matching.

        This is the original keyword-based search. Supports Russian and
        English keywords, class names, category names, parameter names,
        and operation keywords.

        Args:
            query: User's question or search string
            top_k: Maximum number of results to return
            active_extension: If set, include only Layer 0 entries and entries
                            matching this extension_id. Layer 1 entries get x1.5 boost.
            entry_type_filter: If set, only return entries of this type (e.g., "recipe").

        Returns:
            List of ApiEntry objects sorted by relevance
        """
        # Token-mode consistency guard (KUKAI_LEMMA_LEXICON, IQ #7): entry
        # tokens must have been built by the same tokenizer queries use now.
        self._ensure_token_mode()

        # BM25F leg (flag KUKAI_BM25F, default OFF). On any internal failure
        # we fall back to the legacy scorer below — retrieval must never break.
        if _bm25f_enabled():
            try:
                return self._keyword_search_bm25f(
                    query, top_k, active_extension, entry_type_filter,
                )
            except Exception:
                logger.exception(
                    "BM25F keyword leg failed — falling back to legacy scorer"
                )

        query_tokens = _filter_stop_words(_tokenize(query))
        if not query_tokens:
            return []

        # Also check for exact substrings (e.g., class names like "FilteredElementCollector")
        query_lower = query.lower()

        scored: list[tuple[float, int, ApiEntry]] = []

        for idx, entry in enumerate(self._entries):
            # Entry type filtering (e.g., only recipes)
            if entry_type_filter and entry.entry_type != entry_type_filter:
                continue

            # Extension filtering:
            # - No active extension → exclude ALL extension entries (Layer 0 only)
            # - Active extension set → include matching extension + Layer 0
            if entry.extension_id:
                if not active_extension or entry.extension_id != active_extension:
                    continue

            score = 0.0

            # Token overlap scoring — primary tokens (keywords, class name)
            # get higher weight than secondary tokens (method names).
            if entry._tokens:
                primary_matches = 0
                secondary_matches = 0
                matched_query_tokens = 0

                for qt in query_tokens:
                    qt_matched = False

                    # Check primary tokens first (keywords, class name)
                    for et in entry._primary_tokens:
                        if qt == et:
                            primary_matches += 2
                            qt_matched = True
                        elif qt in et or et in qt:
                            primary_matches += 1
                            qt_matched = True

                    # Check remaining tokens (methods) only if not matched in primary
                    if not qt_matched:
                        secondary_tokens = entry._tokens - entry._primary_tokens
                        if qt in secondary_tokens:
                            secondary_matches += 1
                            qt_matched = True

                    if qt_matched:
                        matched_query_tokens += 1

                total_raw = primary_matches * 2.0 + secondary_matches * 0.5
                if total_raw > 0:
                    query_coverage = matched_query_tokens / len(query_tokens)
                    # Cap to prevent inflation from huge token sets
                    capped = min(total_raw, len(query_tokens) * 6)
                    score += capped * (0.5 + 0.5 * query_coverage)

                    # Bonus: all query tokens matched in PRIMARY keywords
                    # This rewards entries whose keywords perfectly cover the query
                    # e.g. "move element" → ElementTransformUtils has both in keywords
                    if matched_query_tokens == len(query_tokens) and primary_matches >= len(query_tokens) * 2:
                        score += 6.0

            # Exact name match bonus.
            # Full match: query IS the name or name IS the query → strong bonus
            # Partial match: name is a substring of query → moderate bonus
            # But only if the name covers a significant portion of the query.
            entry_name_lower = entry.name.lower()
            if entry_name_lower == query_lower:
                # Perfect match
                score += 20.0
            elif entry_name_lower in query_lower:
                # Name is fully contained in query — bonus proportional to
                # how much of the query the name covers
                coverage = len(entry_name_lower) / max(len(query_lower), 1)
                if coverage > 0.5:
                    score += 10.0
                elif coverage > 0.3:
                    score += 5.0
                else:
                    score += 2.0
            elif query_lower in entry_name_lower and len(query_lower) >= 3:
                score += 5.0

            # Boost classes and recipes over categories/parameters
            # when there are matches (they're more useful for context)
            if score > 0:
                if entry.entry_type == "class":
                    score *= 1.5
                elif entry.entry_type == "recipe":
                    score *= 1.3
                elif entry.entry_type == "edge":
                    # Negative knowledge ("memory's edge") matched this query —
                    # i.e. the query names a removed/absent API or a confident-
                    # wrong trap. A matched edge must not be drowned by the flood
                    # of classes that merely share a substring of the same symbol;
                    # boost it into view (parity with the class/recipe priors).
                    # This NEVER manufactures a match — it only re-weights an edge
                    # that already scored on token overlap.
                    score *= 1.5

            # Layer 1 boost: extension entries get x1.5 when their extension is active
            if score > 0 and entry.extension_id and active_extension and entry.extension_id == active_extension:
                score *= 1.5

            if score > 0:
                scored.append((score, idx, entry))

        # Sort by score descending, then by original index for stability
        scored.sort(key=lambda x: (-x[0], x[1]))

        return self._apply_ranking_stages(query_tokens, scored, top_k)

    def _apply_ranking_stages(
        self,
        query_tokens: list[str],
        scored: list[tuple[float, int, "ApiEntry"]],
        top_k: int,
    ) -> list["ApiEntry"]:
        """Shared post-scoring ranking stages (concept coverage + promotions).

        Extracted VERBATIM from the legacy ``keyword_search`` body (2026-07-04)
        so the flag-OFF path stays behaviourally identical (golden parity test:
        ``tests/test_bm25f.py::TestLegacyParity``), and the BM25F path
        (``KUKAI_BM25F=1``) preserves the four promotion hacks' intent exactly.
        Input: the score-sorted candidate list ``(score, idx, entry)``; output:
        the final ``top_k`` entries.
        """
        # --- Multi-concept coverage ---
        # For each query token, guarantee ONE high-relevance entry surfaces, so a
        # single dominant concept (e.g. "level") — or, after the +69 authored
        # recipes landed, a flood of broad-keyword recipes — cannot fill every
        # slot and bury the canonical class/category a bare type query is about.
        #
        # Selection is two-tier (the second tier is the recipe-crowding fix):
        #
        #   * CANONICAL NAME ANCHOR (preferred). The entry for which this token is
        #     part of its NAME is the canonical home of the concept — `Wall`/
        #     `OST_Walls` for "walls", `OST_Doors` for "doors", `Level` for
        #     "level". This is purely data-driven (the token vs. the entry's own
        #     name — no hardcoded class list) and immune to the keyword pollution
        #     that lets the three mega-keyword infrastructure classes
        #     (FilteredElementCollector / BuiltInCategory / BuiltInParameter, each
        #     ~287 LLM-authored keywords) and broad recipes match every token.
        #     Among name matches we prefer higher score, then the SHORTER name
        #     (the base `OST_Doors`, not a derived `OST_DoorsGlassCut`).
        #
        #   * PRIMARY-TOKEN FALLBACK (legacy). When no class/category names the
        #     token (e.g. operation verbs like "move"), fall back to the old
        #     behaviour: the highest-scored entry with a primary-token match.
        #
        # This re-weights ONLY the per-concept guarantee slot; the main scored
        # ranking and every recipe score are untouched, so recipes still fill all
        # remaining slots by relevance — no broad recipe demotion.
        concept_best: dict[str, tuple[float, ApiEntry]] = {}
        for qt in query_tokens:
            name_anchor: tuple[tuple[float, int], float, ApiEntry] | None = None
            primary_fallback: tuple[float, ApiEntry] | None = None
            for sc, _, entry in scored[:200]:
                # Canonical name anchor — token appears in the entry's own name.
                if entry.entry_type in ("class", "category"):
                    name_tokens = _tokenize(entry.name)
                    if any(
                        qt == nt
                        or (len(qt) >= 3 and len(nt) >= 3 and (qt in nt or nt in qt))
                        for nt in name_tokens
                    ):
                        # Rank key: higher score first, then shorter (more canonical) name.
                        cand_key = (-sc, len(entry.name))
                        if name_anchor is None or cand_key < name_anchor[0]:
                            name_anchor = (cand_key, sc, entry)
                # Primary-token fallback (legacy: first/highest-scored match).
                if primary_fallback is None:
                    for et in entry._primary_tokens:
                        if qt == et or (len(qt) >= 3 and len(et) >= 3 and (qt in et or et in qt)):
                            primary_fallback = (sc, entry)
                            break
            chosen = (
                (name_anchor[1], name_anchor[2])
                if name_anchor is not None
                else primary_fallback
            )
            if chosen is not None:
                concept_best[qt] = chosen

        # Merge: concept-best entries first (by score), then overall ranking
        seen: set[str] = set()
        results: list[ApiEntry] = []

        concept_entries = sorted(concept_best.values(), key=lambda x: -x[0])
        for _, entry in concept_entries:
            key = f"{entry.entry_type}:{entry.namespace}.{entry.name}"
            if key not in seen:
                seen.add(key)
                results.append(entry)

        for _, _, entry in scored:
            if len(results) >= top_k:
                break
            key = f"{entry.entry_type}:{entry.namespace}.{entry.name}"
            if key not in seen:
                seen.add(key)
                results.append(entry)

        # --- Domain-specific boost: ensure the canonical class for an OPERATION
        # surfaces, even when it has no name-token to anchor on (so the name
        # anchor above cannot reach it). These canonical classes are reliably
        # outranked by FilteredElementCollector — and now by the +69 broad-keyword
        # authored recipes — which match almost every query via their wide
        # keyword sets. The promotion only re-orders entries that already matched
        # (or pulls in the named canonical class); it never invents relevance and
        # never demotes recipes broadly (they keep their slots below the boost).
        def _promote_to_top(class_names: list[str]) -> None:
            boost_entries: list[ApiEntry] = []
            for entry in self._entries:
                if entry.name in class_names:
                    key = f"{entry.entry_type}:{entry.namespace}.{entry.name}"
                    if key not in seen:
                        seen.add(key)
                        boost_entries.append(entry)
                    else:
                        # Already in results — remove and re-prepend
                        try:
                            results.remove(entry)
                            boost_entries.append(entry)
                        except ValueError:
                            pass  # Same key but different object
            # Prepend in reverse so first class_name ends up first
            for entry in reversed(boost_entries):
                results.insert(0, entry)

        # "create" + a specific type keyword → the corresponding view/schedule class.
        _CREATE_BOOST_MAP = {
            "schedule": ["ViewSchedule", "ScheduleDefinition"],
            "view": ["View3D", "ViewFamilyType"],
            "3d": ["View3D", "ViewFamilyType"],
            "section": ["ViewSection"],
            "plan": ["ViewPlan"],
            "elevation": ["ViewPlan"],  # elevation views
        }
        if any(qt == "create" for qt in query_tokens):
            for trigger, class_names in _CREATE_BOOST_MAP.items():
                if any(trigger in qt or qt == trigger for qt in query_tokens):
                    _promote_to_top(class_names)
                    break  # Only apply first matching trigger

        # Geometric-transform verbs → ElementTransformUtils (the API for moving /
        # rotating / mirroring / copying existing elements). "move" etc. are not
        # part of any class NAME, so the name anchor cannot surface ETU; and as a
        # bare keyword "move" is polluted across ~150 unrelated classes. A small
        # curated verb→class map (mirroring _CREATE_BOOST_MAP) is the honest,
        # robust anchor for the canonical transform utility.
        _TRANSFORM_VERBS = ("move", "translate", "rotate", "mirror")
        if any(qt in _TRANSFORM_VERBS for qt in query_tokens):
            _promote_to_top(["ElementTransformUtils"])

        return results[:top_k]

    def _ensure_token_mode(self) -> None:
        """Keep the token index consistent with ``KUKAI_LEMMA_LEXICON`` (IQ #7)
        and ``KUKAI_BILINGUAL_RETRIEVAL`` (IQ #6).

        Entry tokens — and everything derived from them: the BM25F postings
        and the Doc2Query phrasing token-sets — are built with the tokenizer
        active at ``load()`` time; the primary/secondary token SPLIT is built
        with the bilingual flag active at ``load()`` time. If either flag
        flips afterwards (tests, benchmark A/B runs), queries would run
        against an index built under the other mode: a silent recall zero (or
        silently second-class RU primaries). Detect the flip and rebuild the
        whole index from disk under the current flags. No-op in the steady
        state (prod sets flags before the first load), and a no-op for
        hand-built test indexes that never ran ``load()``
        (``_token_mode is None``).
        """
        if not self._loaded or self._token_mode is None:
            return
        if (_lemma_lexicon_enabled() == self._token_mode
                and _bilingual_retrieval_enabled() == self._bilingual_mode):
            return
        with self._token_mode_lock:
            want = _lemma_lexicon_enabled()
            want_bi = _bilingual_retrieval_enabled()
            if self._token_mode is None or (
                self._token_mode == want and self._bilingual_mode == want_bi
            ):
                return  # another thread already rebuilt
            logger.info(
                "KUKAI_LEMMA_LEXICON/KUKAI_BILINGUAL_RETRIEVAL flipped after "
                "load (lemma %s -> %s, bilingual %s -> %s): rebuilding token "
                "index under the current flags",
                self._token_mode, want, self._bilingual_mode, want_bi,
            )
            self._entries = []
            self._entry_id_map = {}
            self._extension_profiles = {}
            self._extension_meta = {}
            # Derived structures are keyed by old-mode terms — drop them; they
            # rebuild lazily with the new tokenizer.
            self._bm25f = None
            self._phrasing_index = None
            self._loaded = False
            self.load()
            # load() skips _load_embeddings (already loaded) — re-map the
            # pre-computed vectors onto the rebuilt entries list.
            if self._vectors is not None:
                self._build_entry_id_map()

    def _ensure_bm25f_index(self) -> _Bm25fIndex:
        """Lazily build (and cache) the BM25F inverted index over the corpus.

        Build is one pass over the entries (a few hundred ms for the ~8K-entry
        corpus) and happens only under ``KUKAI_BM25F=1``. Rebuilds if the entry
        count changed (e.g. extensions loaded after a partial build).
        """
        bidx = self._bm25f
        if bidx is not None and bidx.n_docs == len(self._entries):
            return bidx
        with self._bm25f_lock:
            bidx = self._bm25f
            if bidx is not None and bidx.n_docs == len(self._entries):
                return bidx
            import time as _time

            _t0 = _time.perf_counter()
            bidx = _Bm25fIndex(self._entries)
            self._bm25f = bidx
            logger.info(
                "BM25F inverted index built: %d docs, %d terms in %.0f ms",
                bidx.n_docs, bidx.n_terms, (_time.perf_counter() - _t0) * 1000.0,
            )
            return bidx

    def _keyword_search_bm25f(
        self,
        query: str,
        top_k: int,
        active_extension: Optional[str],
        entry_type_filter: Optional[str],
    ) -> list[ApiEntry]:
        """BM25F scoring path of ``keyword_search`` (flag ``KUKAI_BM25F=1``).

        Same contract and filters as the legacy scorer; only the SCORING is
        different: inverted-index BM25F (IDF x field-weighted, length-normalized
        TF) + the same type priors and name-match prior, then the shared
        ranking stages. Touches only entries that share >=1 term with the query
        — O(query_terms x postings), not O(corpus).
        """
        query_tokens = _filter_stop_words(_tokenize(query))
        if not query_tokens:
            return []
        terms = _bm25f_query_terms(query)
        if not terms:
            return []

        bidx = self._ensure_bm25f_index()
        acc = bidx.score(terms)
        query_lower = query.lower()

        # Perfect whole-query name match must stay reachable even with zero
        # term overlap (the legacy name-bonus could pull such an entry in).
        for doc in bidx.name_docs.get(query_lower, ()):
            acc.setdefault(doc, (0.0, 0))

        n_terms = len(terms)
        scored: list[tuple[float, int, ApiEntry]] = []
        for doc, (s, n_matched) in acc.items():
            entry = self._entries[doc]
            # Entry-type + extension filtering — identical to the legacy path.
            if entry_type_filter and entry.entry_type != entry_type_filter:
                continue
            if entry.extension_id:
                if not active_extension or entry.extension_id != active_extension:
                    continue

            # Coordination factor — the legacy query-coverage multiplier
            # (0.5 + 0.5 * coverage), applied to the term score only.
            s *= 0.5 + 0.5 * (n_matched / n_terms)
            s += _name_match_bonus(entry.name.lower(), query_lower)
            if s <= 0.0:
                continue

            # Type priors — preserved verbatim from the legacy scorer.
            if entry.entry_type == "class":
                s *= 1.5
            elif entry.entry_type == "recipe":
                s *= 1.3
            elif entry.entry_type == "edge":
                s *= 1.5
            if (
                entry.extension_id
                and active_extension
                and entry.extension_id == active_extension
            ):
                s *= 1.5

            scored.append((s, doc, entry))

        scored.sort(key=lambda x: (-x[0], x[1]))

        if _bm25f_stages_enabled():
            return self._apply_ranking_stages(query_tokens, scored, top_k)

        # Stages-off ablation path: plain dedupe + slice (benchmark knob).
        seen: set[str] = set()
        results: list[ApiEntry] = []
        for _, _, entry in scored:
            key = f"{entry.entry_type}:{entry.namespace}.{entry.name}"
            if key in seen:
                continue
            seen.add(key)
            results.append(entry)
            if len(results) >= top_k:
                break
        return results

    def _ensure_phrasing_index(self) -> Any:
        """Lazy-construct the Doc2Query phrasings index.

        Construction is cheap (no IO). The actual file load happens inside
        `PhrasingIndex.ensure_loaded()` on first call.
        """
        if self._phrasing_index is None:
            from kukai.rag.phrasings import PhrasingIndex, default_phrasings_path

            self._phrasing_index = PhrasingIndex(default_phrasings_path())
        return self._phrasing_index

    def search(
        self,
        query: str,
        top_k: int = 15,
        active_extension: Optional[str] = None,
        revit_version: Optional[str] = None,
        intent: Optional[str] = None,
        complexity: Optional[str] = None,
        action: Optional[str] = None,
        object_kinds: Optional[list] = None,
    ) -> list[ApiEntry]:
        """Search the knowledge base — keyword + semantic + phrasings (RRF).

        Always runs keyword search (reliable, fast). Then runs semantic search
        if embeddings + API key are available. Finally — if Doc2Query
        phrasings exist on disk and the feature flag is enabled — adds a third
        leg ranking entries by user-phrasing token overlap.

        All three legs are merged via Reciprocal Rank Fusion (RRF).

        When phrasings are disabled or unavailable, behaviour is identical to
        the previous 2-leg search (zero regression).

        Args:
            query: User's question or search string
            top_k: Maximum number of results to return
            active_extension: If set, filter and boost extension entries.
            revit_version: Project Revit version for the in-retrieval version
                filter (design 2026-07-04 §2.2). ``None`` → resolved from the
                per-turn ``TurnState`` inside ``retrieve()``; unknown → the
                filter stage is a disclosed no-op.
            intent: Wave-2 batch G — the turn's classified intent (11-way
                enum from ``kukai.agents.intent_classifier`` or the
                deterministic ``quick_classify`` fallback), used by the
                intent-join ranking adjustment (``KUKAI_RAG_INTENT_JOIN``,
                default ON) to re-scale recipe RRF scores toward the turn's
                actual intent. ``None`` (the default, and every call site
                that predates this change) is a strict no-op — byte-identical
                to today's ranking.
            complexity: G-tune (Wave-2 batch G2) — the turn's classified
                complexity (5-way ``trivial|simple|composite|hard|vague``
                enum), same two sources as ``intent``. Gates ONLY the
                composite-recipe conditional match inside the intent-join
                adjustment; ``None`` (the default) keeps composite recipes
                NEUTRAL rather than universally boosted.
            action: Capability-first RAG, Stage 2 — the turn's classified
                OperationFrame verb (closed vocab, from
                ``kukai.agents.intent_classifier`` or its ``quick_classify``
                fallback), used by the capability-resolve ranking adjustment
                (``KUKAI_RAG_CAPABILITY_RESOLVE``, default OFF) to
                structurally prefer recipes whose own ``capability.action``
                matches. ``None`` (the default, and every call site that
                predates this change) is a strict no-op.
            object_kinds: Stage 2 — the OperationFrame's object kinds (closed
                vocab list), same two sources as ``action``. Secondary boost
                inside the capability-resolve adjustment; ``None``/``[]``
                degrades safely (no object-kind boost applied).

        Returns:
            List of ApiEntry objects ranked by fused RRF score, with
            version-invalid entries dropped BEFORE the ``top_k`` slice (the
            slice refills from deeper ranks — post-filter top-k).
        """
        if not self._loaded:
            self.load()

        if not self._entries:
            return []

        if not query or not query.strip():
            return []

        # Token-mode consistency guard (KUKAI_LEMMA_LEXICON, IQ #7) — also
        # covers the phrasings leg, whose token-sets are tokenizer-derived.
        self._ensure_token_mode()

        # The retrieval pipeline (legs -> RRF -> ranking policy) lives in
        # ``kukai.rag.retrieval`` (plan 018). ``search()`` is a thin,
        # signature-preserving delegate: it remains THE production entry point
        # (the benchmark's parity spy watches this method), but the leg
        # orchestration, fusion and the ranking policy — and therefore every
        # plan-009 ``report_leg``/``add_flag`` call — now live in one typed,
        # measurable module. The ``hard`` ranking mode is byte-identical to the
        # previous inline type-priority sort (Step-2 zero-diff gate).
        from kukai.rag.retrieval import RetrievalRequest, retrieve

        ranked = retrieve(
            self,
            RetrievalRequest(
                query=query, top_k=top_k, active_extension=active_extension,
                revit_version=revit_version, intent=intent, complexity=complexity,
                action=action, object_kinds=object_kinds,
            ),
        )
        entries = [c.entry for c in ranked]

        # --- Anti-overconfidence: demote bare-signature class entries ---
        # A class whose ONLY example is a bare signature (e.g. "public void
        # Foo(...)") looks populated but is not a verified, runnable pattern. It
        # must not be returned ABOVE a real recipe / rich example / edge for the
        # same query — otherwise the model treats a signature as a worked example
        # and writes confident-wrong code. We stable-partition: substantive
        # entries keep their ranked order; signature-only entries are appended
        # after, in their ranked order. This is a NO-OP when no signature-only
        # entry is present (the common case) — zero regression. Flag-gated; on
        # any failure we fall back to the un-demoted order (never throws).
        entries = self._maybe_demote_signatures(entries)

        final = entries[:top_k]

        # --- Grounding-confidence signal (miss-detector seed, plan: edges) ---
        # Record (never gate) whether this substantive query landed on solid
        # ground or only on signatures / read-only entries / nothing. No-op
        # unless a turn is active; never throws.
        self._record_grounding(query, final)

        return final

    def _maybe_demote_signatures(self, entries: list[ApiEntry]) -> list[ApiEntry]:
        """Stable-partition signature-only entries below substantive ones.

        Flag: ``rag_demote_signatures`` — read getattr-defaulted FALSE so a
        Settings object that does not yet declare the field (e.g. an out-of-sync
        deployment) behaves identically to the legacy/OFF path, NOT accidentally
        enabling the reorder. When off — or on any error — returns ``entries``
        unchanged (byte-identical legacy order). Stable: relative order is
        preserved within each group, so two substantive entries are NEVER
        reordered relative to each other; only signature-only entries move down.
        """
        try:
            from kukai.config import get_settings as _gs
            enabled = bool(getattr(_gs(), "rag_demote_signatures", False))
        except Exception:
            enabled = False
        if not enabled:
            return entries
        try:
            substantive: list[ApiEntry] = []
            signature_only: list[ApiEntry] = []
            for e in entries:
                if _is_signature_only_entry(e):
                    signature_only.append(e)
                else:
                    substantive.append(e)
            if not signature_only:
                return entries  # nothing to demote — byte-identical order
            return substantive + signature_only
        except Exception:
            return entries

    def _record_grounding(self, query: str, final: list[ApiEntry]) -> None:
        """Emit the per-turn ``low_grounding`` signal (seed of the miss-detector).

        Delegates to ``retrieval_health.record_grounding`` — a never-throws,
        default-off no-op (no-op unless a turn is active). Records, never gates.
        """
        try:
            from kukai.rag.retrieval_health import record_grounding as _rg
            _rg(query, final, signature_pred=_is_signature_only_entry)
        except Exception:
            pass
