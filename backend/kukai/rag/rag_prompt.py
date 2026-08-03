"""RAG prompt enricher — injects query-specific Revit API context into prompts.

Before each LLM call, this module:
1. Analyzes the user's message for Revit-related keywords
2. Searches the RAG index for relevant API entries
3. Formats the results into a compact prompt section (max ~2000 tokens)
4. Returns the enriched context for injection into the system prompt
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from kukai.rag.revit_api_index import (
    RevitApiIndex,
    ApiEntry,
    _filter_stop_words,
    _tokenize,
)

# ONE version-truth implementation, shared with the retrieval pipeline
# (design 2026-07-04 §2.2): the predicate/filter live in kukai.rag.retrieval
# (import-cheap, stdlib-only at module level); this module keeps only the
# render-side concerns (_sanitize_version, member-level truth, gotchas).
from kukai.rag.retrieval import (
    filter_entries as _filter_entries,
    parse_revit_year as _parse_revit_year,
    version_filter_enabled as _version_filter_enabled_impl,
)

logger = logging.getLogger(__name__)


def _trim_code(code: str, max_chars: int) -> str:
    """Cut C# at a statement boundary, never mid-statement; mark the cut.

    Plan 013 (operator thesis): the weak model copies whatever it is shown,
    so a snippet sliced mid-statement (``var x = el.Get``) teaches broken code.
    This trims to the last ``;`` or ``}`` inside the budget (only if past the
    half-way mark, so we never collapse to a near-empty fragment) and appends a
    visible truncation marker so the model knows the rest is intentionally cut.
    """
    if not code or len(code) <= max_chars:
        return code
    # Audit #4 (2026-06-14): a write recipe sliced mid-Transaction teaches the weak
    # model a half-write with no Commit/return. Never amputate a write block — show
    # the whole recipe up to a hard ceiling rather than cut between `new Transaction`
    # and its Commit(). Our authored recipes are ≤40 lines, so this shows them whole.
    _HARD_CEILING = max(max_chars, 6000)
    if "Transaction" in code and len(code) <= _HARD_CEILING:
        return code
    cut = code[:max_chars]
    b = max(cut.rfind(";"), cut.rfind("}"))
    if b > max_chars // 2:
        cut = cut[: b + 1]
    return cut + "\n// … (обрезано: фрагмент длиннее лимита)"


def _code_fingerprint(code: str) -> str:
    """Whitespace-robust fingerprint of an example's code, used to dedup
    identical code shown twice in one injection (S4 audit: judge 3 / real:120
    — the same underlying snippet reached the prompt via two different
    retrieved entries and was rendered twice)."""
    normalized = re.sub(r"\s+", " ", code).strip()
    return hashlib.sha1(normalized.encode("utf-8", "ignore")).hexdigest()

# Approximate tokens-per-character ratio for mixed Russian/English text.
# GPT-style tokenizers: ~1 token per 4 chars for English, ~1 per 2 for Russian.
# We use a conservative estimate.
_CHARS_PER_TOKEN = 3
_MAX_RAG_TOKENS = 15000
_MAX_RAG_CHARS = _MAX_RAG_TOKENS * _CHARS_PER_TOKEN


class RagPromptEnricher:
    """Enriches the system prompt with query-specific Revit API context."""

    def __init__(self, index: Optional[RevitApiIndex] = None):
        self._index = index or RevitApiIndex()

    def ensure_loaded(self) -> None:
        """Make sure the index is loaded. Safe to call multiple times."""
        if not self._index.loaded:
            self._index.load()

    @staticmethod
    def _version_filter_enabled() -> bool:
        """Plan-012 version filter flag (KUKAI_RAG_VERSION_FILTER, default ON).

        Delegates to the single shared implementation in
        ``kukai.rag.retrieval`` (read at call time, fail-open True) — the same
        flag gates the in-retrieval filter stage and the render-side legs here.
        """
        return _version_filter_enabled_impl()

    def enrich(
        self,
        user_message: str,
        top_k: int = 10,
        active_extension: Optional[str] = None,
        pre_retrieved_entries: Optional[list] = None,
        family_mode: bool = False,
        revit_version: Optional[str] = None,
    ) -> str:
        """Search the RAG index and return a formatted prompt section.

        Uses a recipe backfill strategy: if the main search returns fewer
        than 2 recipes, a targeted keyword search on recipes only is
        performed. A relevance threshold prevents injecting irrelevant
        recipes (e.g., "Create wall" when user asked about wall area).

        Args:
            user_message: The user's latest message
            top_k: Maximum number of API entries to retrieve
            active_extension: If set, include extension entries and apply boost.
            pre_retrieved_entries: If set (Phase 7.5 — multi-agent reranker),
                use these entries instead of running ``_index.search``. Skips
                recipe backfill (caller already ordered the list). Use this
                to inject reranker output without round-tripping RAG.

        Returns:
            A formatted string for injection into the system prompt,
            or empty string if no relevant entries found.
        """
        self.ensure_loaded()

        if not user_message or not user_message.strip():
            return ""

        # plan-009 instrumentation: per-leg health (no-op unless begin_turn() active).
        from kukai.rag.retrieval_health import (
            current as _rh_current,
            report_leg as _report_leg,
            set_final as _set_final,
        )

        if pre_retrieved_entries is not None:
            # Reranker already chose the order — skip search + recipe backfill.
            _ents = list(pre_retrieved_entries)
            _set_final(_ents[:10])
            # Fix A (design 2026-07-04 §2.2): the version filter now runs
            # INSIDE retrieve() (kukai/rag/retrieval.py), so the reranked path
            # is filtered BY CONSTRUCTION — the retrieve() call that produced
            # these entries already emitted the truthful ``version_filter``
            # leg (``ran``/``skipped_flag``). Only when NO filter leg exists
            # this turn (an exotic caller handing in entries that never went
            # through retrieve(), or the KUKAI_RAG_VERSION_FILTER=0 legacy
            # world) does the honest BYPASS disclosure remain (plan-009).
            _h = _rh_current()
            if not any(
                leg.name == "version_filter" for leg in (_h.legs if _h else [])
            ):
                _report_leg(
                    "version_filter", "skipped_flag", 0, 0.0,
                    "bypassed_on_reranked_path",
                )
            self._audit_rag(user_message, _ents, "reranker")
            return self._sanitize_version(
                self._format_results(_ents, revit_version, user_message), revit_version,
            )

        # family_mode is accepted for caller compatibility (prompts.py passes it);
        # family-scoped retrieval is a future refinement. Today it is a no-op so
        # the family-editor path gets normal RAG rather than throwing.
        _ = family_mode

        results = self._index.search(
            user_message,
            top_k=top_k,
            active_extension=active_extension,
            revit_version=revit_version,
        )
        if not results:
            return ""

        # Version-aware filter — demoted, not deleted (design §2.2 step 3).
        # The entry-level filter now runs INSIDE retrieve() (see
        # kukai.rag.retrieval), so with KUKAI_RAG_VERSION_FILTER ON the search
        # results above are already version-clean and this second application
        # is an idempotent no-op kept as defence-in-depth (report=False — the
        # retrieval stage already emitted the ``version_filter`` health leg).
        # With the flag OFF this is the ACTING legacy filter (since-based
        # introduced-after only) and reports the leg exactly as before.
        _version_filter_on = self._version_filter_enabled()
        results = _filter_entries(
            results, revit_version,
            version_filter_on=_version_filter_on,
            report=not _version_filter_on,
        )
        if not results:
            return ""

        # Recipe backfill: guarantee code examples in the prompt.
        # The main search often returns 0 recipes because 2571 API classes
        # outnumber 103 recipes 25:1. This targeted search fixes that.
        recipe_results = [r for r in results if r.entry_type == "recipe"]
        _recipe_added = 0
        if len(recipe_results) < 2:
            try:
                recipe_candidates = self._index.keyword_search(
                    user_message,
                    top_k=5,
                    active_extension=active_extension,
                    entry_type_filter="recipe",
                )
                # keyword_search does NOT pass through retrieve(), so backfill
                # candidates must go through the SAME version predicate — a
                # version-excluded recipe the filtered main search dropped
                # must not be resurrected here (one predicate, every door).
                recipe_candidates = _filter_entries(
                    recipe_candidates, revit_version,
                    version_filter_on=_version_filter_on,
                    report=False,
                )
                if recipe_candidates:
                    # Relevance threshold: only include recipes that scored
                    # meaningfully. This prevents "wall area" → "Create wall".
                    # We check if the recipe search found something non-trivial
                    # by requiring at least 2 keyword tokens to match.
                    seen_keys = {
                        f"{r.entry_type}:{r.namespace}.{r.name}" for r in results
                    }
                    added = 0
                    for candidate in recipe_candidates:
                        key = f"{candidate.entry_type}:{candidate.namespace}.{candidate.name}"
                        if key not in seen_keys and added < 2:
                            # Prepend recipes so they appear first in formatted output
                            results.insert(0, candidate)
                            seen_keys.add(key)
                            added += 1
                    if added > 0:
                        logger.debug("Recipe backfill: added %d recipes", added)
                    _recipe_added = added
            except Exception:
                logger.debug("Recipe backfill search failed (non-fatal)")

        _report_leg(
            "recipe_backfill", "ran" if _recipe_added else "empty", _recipe_added,
        )
        _set_final(results[:10])
        self._audit_rag(user_message, results, "search")
        return self._sanitize_version(
            self._format_results(results, revit_version, user_message), revit_version,
        )

    def _sanitize_version(self, text: str, revit_version) -> str:
        """Make injected RAG/recipe code version-safe for the project's Revit.

        Audit F5: 15.4% of the verified-recipe corpus uses ElementId.Value, which
        compiles on Revit 2024+ but throws CS1061 on ≤2023. Those snippets are
        shown to the LLM as examples → it copies the broken pattern. Here we
        rewrite ElementId.Value → .IntegerValue for ≤2023 BEFORE injection.
        PRECISE: only `.Value` after an ElementId-yielding token; never kv.Value.

        Plan 012 (IRON 4/5) adds the REVERSE direction: `.IntegerValue` was
        REMOVED in 2026, so for projects at/after the removal year rewrite
        `<id>.IntegerValue` → `.Value`. The removal year is read from
        api_versions.json (NOT a hardcoded 2026 — IRON 5: no hand-written version
        truth); if the fact is absent the reverse rewrite never fires. Both
        directions are gated by KUKAI_RAG_VERSION_FILTER for the reverse leg.
        """
        try:
            yr = int(str(revit_version)[:4]) if revit_version else 0
        except (ValueError, TypeError):
            yr = 0
        if text and yr and yr < 2024:
            text = re.sub(r'\b(\w*[Ii]d(?:\(\))?)\.Value\b', r'\1.IntegerValue', text)
        # Forward direction: IntegerValue removed in 2026 → use .Value. Data-driven.
        if text and yr and self._version_filter_enabled():
            try:
                from kukai.rag.api_versions import member_facts
                rem = member_facts("Autodesk.Revit.DB.ElementId").get(
                    "IntegerValue", {}).get("removed_in")
                rem_yr = _parse_revit_year(rem) if rem else None
                if rem_yr is not None and yr >= rem_yr:
                    # Allow an optional null-conditional `?` before the dot
                    # (e.g. `GetTypeId()?.IntegerValue`) — keep it in the rewrite.
                    text = re.sub(
                        r'\b(\w*[Ii]d(?:\(\))?)(\??)\.IntegerValue\b',
                        r'\1\2.Value', text,
                    )
            except Exception:
                logger.debug("forward _sanitize_version failed (non-fatal)", exc_info=True)
        return text

    def _audit_rag(self, query: str, entries: list, source: str) -> None:
        """Emit a RAG retrieval trace for audit sessions only (no-op otherwise)."""
        try:
            from kukai import audit_trace as _at
            sid = _at.current_session()
            if not _at.is_audit_session(sid):
                return
            hits = []
            for e in entries[:10]:
                name = f"{getattr(e, 'namespace', '')}.{getattr(e, 'name', '?')}".strip(".")
                hits.append([name, getattr(e, "entry_type", "")])
            _at.trace(sid, "rag", {
                "query": str(query)[:200], "n": len(entries),
                "source": source, "hits": hits,
            })
        except Exception:
            pass

    def _format_results(
        self, entries: list[ApiEntry], revit_version=None, user_message: str = "",
    ) -> str:
        """Format RAG results: gotchas + code examples + API reference list.

        Structure:
        0. Known gotchas (path-A N4) — preventive hints based on which APIs are
           in the retrieved set. Stops Gemini from repeating the failures
           tracked in production logs (FEC.LINQ, ElementId version drift,
           BuiltInCategory prefix, FEC ctor).
        1. Code examples from top 3 classes (HOW to write code)
        2. API reference for all found classes (WHAT is available)

        ``user_message`` (S4 audit, B1) is the ORIGINAL user turn, threaded
        through from ``enrich()`` purely so the code-example choice can be
        intent-aware (see ``_render_rich_example`` / ``_pick_rich_example``).
        Optional and defaults to "" so every existing caller that formats a
        pre-built entry list without a query (tests, benchmark paths A/B/D)
        keeps rendering the byte-identical legacy pick.
        """
        if not entries:
            return ""

        # B1: query tokens for intent-aware rich-example selection. Same
        # tokenizer/stop-word filter as retrieval, so RU/EN stemming is
        # consistent with how the corpus itself was indexed. Empty when no
        # user_message is given ⇒ _pick_rich_example always falls back to
        # rich[0] (byte-identical legacy behavior).
        _query_tokens: frozenset[str] = (
            frozenset(_filter_stop_words(_tokenize(user_message)))
            if user_message else frozenset()
        )

        # G2 generation-side flag (real version-correct class members → prevent CS1061)
        _rag_members_on = False
        try:
            from kukai.config import get_settings as _gs_rm
            _rag_members_on = _gs_rm().rag_members
        except Exception:
            _rag_members_on = False
        # Plan 012 member-version-truth gate (KUKAI_RAG_VERSION_FILTER).
        _version_filter_on = self._version_filter_enabled()

        parts: list[str] = []
        total_chars = 0

        # Section 0: Gotcha hints — driven by what's in the retrieved entries.
        # Cheap (~500 chars worst case) but addresses the dominant failure modes
        # from live_test.log. Static text by design — these patterns are stable.
        gotchas = self._build_gotchas(entries[:8], revit_version)
        if gotchas:
            parts.append(gotchas)
            parts.append("")
            total_chars += len(gotchas)

        # Section 1: Code examples from top 3 classes only (highest RAG score)
        # B2 (S4 audit): recipes are hand-authored, already-verified acts —
        # stable-sort them before raw class fragments so a recipe never loses
        # its code slot to an SDK signature snippet (relative order within
        # each group is preserved; Python's sort() is stable).
        example_entries = [
            e for e in entries[:5]
            if e.entry_type in ("class", "recipe") and e.examples
        ]
        example_entries.sort(key=lambda e: 0 if e.entry_type == "recipe" else 1)
        example_entries = example_entries[:3]

        if example_entries:
            parts.append("## Code patterns (write your code following these):")
            parts.append("")
            # Dedup (S4 audit): never render the same example code twice in
            # one injection — two retrieved entries can point at the same
            # underlying snippet (judge 3 / real:120 saw this in prod).
            _seen_code: set[str] = set()
            for entry in example_entries:
                block: Optional[str] = None
                raw_code: Optional[str] = None

                # Schema-v4 (IRON 5): if the entry carries an explained example
                # (rich_examples with КОГДА/ПОЧЕМУ), render the explained form.
                # This is STRICTLY additive — entries without rich examples take
                # the legacy branches below, which stay byte-identical.
                # B1: the pick among several rich examples is intent-aware
                # (see _render_rich_example / _pick_rich_example); recipes
                # keep rendering their own single example as before.
                rich = self._render_rich_example(entry, _query_tokens)
                if rich is not None:
                    block, raw_code = rich
                elif entry.entry_type == "recipe":
                    # Statement-boundary trim (plan 013) — never cut mid-statement.
                    raw_code = entry.examples[0]
                    block = f"```csharp\n{_trim_code(raw_code, 4000)}\n```"
                else:
                    # Pick best example: prefer ones with 'return' or complete patterns
                    useful = [ex for ex in entry.examples if len(ex) >= 40]
                    best = sorted(useful, key=lambda ex: (
                        2 if 'return ' in ex else 0) + (
                        1 if ex.rstrip().endswith((';', '}')) else 0) + (
                        -1 if ex.startswith('public ') and '(' in ex and ex.count('\n') == 0 else 0
                    ), reverse=True)[:1]
                    if best:
                        raw_code = best[0]
                        block = f"```csharp\n// {entry.name}\n{_trim_code(raw_code, 800)}\n```"

                if block is None or raw_code is None:
                    continue
                fp = _code_fingerprint(raw_code)
                if fp in _seen_code:
                    continue
                _seen_code.add(fp)
                parts.append(block)
                total_chars += len(block)
            parts.append("")

        # Section 2: API reference — all entries, compact
        parts.append("## API reference (verify your code uses correct classes):")
        parts.append("")
        for entry in entries:
            if total_chars > _MAX_RAG_CHARS:
                break
            if entry.entry_type == "class":
                methods_str = ', '.join(entry.methods[:6]) if entry.methods else ''
                # G2 generation-side: prefer REAL version-correct members from the
                # api_surface (prevents CS1061 — model sees actual members, not a
                # 6-item guess). Flag-gated; enums fall through (members_for→None).
                if _rag_members_on and revit_version:
                    try:
                        from kukai.llm.api_members import members_for
                        _real = members_for(entry.namespace, entry.name, revit_version)
                        if _real:
                            methods_str = _real
                    except Exception:
                        pass
                # Plan 012 (IRON 4/5): member-level version truth. STRIP from the
                # advertised members any that are removed by / not yet in the
                # project version, and emit at most 2 warning lines telling the
                # model what to use instead. Flag-gated + fail-open. Warning
                # lines deliberately avoid the dotted `.IntegerValue` form (the
                # model copies dotted tokens it sees verbatim).
                _ver_warnings: list[str] = []
                if methods_str and _version_filter_on and revit_version:
                    methods_str, _ver_warnings = self._apply_member_version_truth(
                        entry.namespace, entry.name, methods_str, revit_version,
                    )
                desc = entry.description[:120].replace('\n', ' ')
                line = f"### {entry.name}\n{desc}"
                if methods_str:
                    line += f"\nMethods: {methods_str}"
                for _w in _ver_warnings[:2]:
                    line += f"\n{_w}"
                # For enum-typed classes, surface the FULL list of enum
                # members (value name + short description). The DB already
                # has these as ground-truth — without them in the prompt,
                # the LLM invents labels (F-NEW-027 root cause).
                # 561 enums × ~5 members each adds ~50KB potential overhead,
                # but only the retrieved top-10 entries are rendered, so
                # the real cost per query is ~500 chars × ~3 enums = ~1.5KB.
                if entry.is_enum and entry.enum_values:
                    line += "\nValues (use these names verbatim — do NOT invent labels):"
                    for v in entry.enum_values[:12]:
                        line += f"\n  - {v}"
                parts.append(line)
                parts.append("")
                total_chars += len(line)
            elif entry.entry_type in ("category", "parameter"):
                # For enum-backed parameters (e.g. WALL_STRUCTURAL_USAGE_PARAM
                # stores a StructuralWallUsage value as int), render the full
                # description AND the enum-class hint stored in methods.
                # Without this, the LLM treats the integer as opaque and
                # hand-maps invented Russian labels (F-NEW-027 root cause).
                if entry.entry_type == "parameter" and entry.methods:
                    line = f"- {entry.name} — {entry.description}"
                    for m in entry.methods:
                        line += f"\n    {m}"
                else:
                    line = f"- {entry.name} — {entry.description[:80]}"
                parts.append(line)
                total_chars += len(line)

        result = "\n".join(parts)
        entry_names = [e.name for e in entries[:10]]
        logger.info(
            "RAG enrichment: %d examples + %d refs (~%d chars): %s",
            len(example_entries), len(entries), len(result), entry_names,
        )
        return result

    def _apply_member_version_truth(
        self, namespace: str, name: str, methods_str: str, revit_version,
    ) -> tuple[str, list[str]]:
        """Strip version-wrong members from an advertised member list + build
        warning lines (plan 012 Step 5.2, IRON 4/5).

        For the connected version year Y, drop any member whose diffed
        ``removed_in`` <= Y or ``introduced`` > Y — a deleted / not-yet-existing
        member must not be advertised at all. The corpus stores members in mixed
        forms ("Name", "Name(args)", "Name - desc"); we match on the member NAME
        TOKEN (the leading identifier before ` - `, `(`, or whitespace).

        Returns ``(filtered_methods_str, warning_lines)``. Warning lines use the
        bare member name (never the dotted ``.IntegerValue`` form) so the model
        does not copy a deleted dotted token. Fail-open: any error → inputs
        returned unchanged.
        """
        try:
            year = _parse_revit_year(revit_version)
            if year is None:
                return methods_str, []
            from kukai.rag.api_versions import member_facts
            facts = member_facts(f"{namespace}.{name}")
            if not facts:
                return methods_str, []

            def _token(part: str) -> str:
                p = part.strip()
                for sep in (" - ", "("):
                    idx = p.find(sep)
                    if idx != -1:
                        p = p[:idx]
                return p.strip()

            kept: list[str] = []
            warnings: list[str] = []
            for part in methods_str.split(", "):
                if not part.strip():
                    continue
                tok = _token(part)
                fact = facts.get(tok)
                if fact:
                    rem = fact.get("removed_in")
                    intro = fact.get("introduced")
                    if rem and (_parse_revit_year(rem) or 9999) <= year:
                        warnings.append(
                            f"⚠ {tok} удалён ({rem}) — не используй, см. актуальные члены"
                        )
                        continue
                    if intro and (_parse_revit_year(intro) or 0) > year:
                        warnings.append(
                            f"⚠ {tok} появился только в {intro} — недоступен в {year}"
                        )
                        continue
                kept.append(part)
            return ", ".join(kept), warnings[:2]
        except Exception:
            logger.debug("member version-truth failed (non-fatal)", exc_info=True)
            return methods_str, []

    def _pick_rich_example(
        self, rich: list[dict], query_tokens: frozenset[str],
    ) -> dict:
        """B1 (S4 audit): pick the rich example whose ``when``/``why`` text
        overlaps most with the user's query, instead of always taking
        ``rich[0]``.

        Evidence (agent_reports.md / inject_verdicts): one class's
        ``rich_examples[0]`` («создать стиль линий», FilteredElementCollector)
        was rendered as the FIRST code block on 16% of ALL real queries,
        completely regardless of what was actually asked — because the old
        code always took index 0.

        Scoring is RU/EN token overlap between the example's ``when`` + ``why``
        text and the query, using the SAME tokenizer/stemmer/stop-word filter
        as retrieval (``kukai.rag.revit_api_index._tokenize`` /
        ``_filter_stop_words``) so this is consistent with how the corpus
        itself is indexed and searched.

        Highest overlap wins. A tie for the max score, or zero overlap for
        every example, falls back to ``rich[0]`` — byte-identical to the
        legacy pick when there is no signal to act on.
        """
        if not query_tokens or len(rich) <= 1:
            return rich[0]
        scores: list[int] = []
        for ex in rich:
            if not isinstance(ex, dict):
                scores.append(-1)  # never wins; keeps indices aligned with rich
                continue
            text = " ".join(
                t for t in (ex.get("when"), ex.get("why")) if isinstance(t, str)
            )
            ex_tokens = set(_tokenize(text)) if text else set()
            scores.append(len(ex_tokens & query_tokens))
        best = max(scores)
        if best <= 0:
            return rich[0]
        winners = [i for i, s in enumerate(scores) if s == best]
        return rich[winners[0]] if len(winners) == 1 else rich[0]

    def _render_rich_example(
        self, entry: ApiEntry, query_tokens: frozenset[str] = frozenset(),
    ) -> Optional[tuple[str, str]]:
        """Render a schema-v4 explained example, or None if there isn't one.

        Returns ``(block_text, raw_code)`` ONLY when the entry has a rich
        example carrying explanation context (``when`` and/or ``why``);
        ``raw_code`` lets the caller dedup identical code across entries.
        Returns None otherwise so the caller falls back to the byte-identical
        legacy string-render path — this is the string-example regression
        guarantee: entries without rich content render exactly as before.

        Char budgets mirror the legacy branches (code ≤ 800, recipes a touch
        more) so the explained form is not materially heavier than today.

        Recipes (B1) always render their OWN single example — ``rich[0]`` —
        exactly as before; recipes are hand-authored/verified single acts,
        not a bag of alternative snippets to choose among.

        Classes (B1+B2): among the entry's rich examples, first drop
        "headerless stubs" — an example with no ``when`` AND under 60 chars
        of code (a bare signature, no explanation) — so one never occupies
        the class's one code slot; then pick the best-scoring survivor via
        ``_pick_rich_example``. If nothing survives, defer to the legacy
        ``entry.examples`` path (same as "no rich examples at all").
        """
        rich = getattr(entry, "rich_examples", None)
        if not rich:
            return None

        if entry.entry_type == "recipe":
            ex = rich[0]
        else:
            viable = [
                e for e in rich
                if isinstance(e, dict)
                and isinstance(e.get("code"), str) and e["code"].strip()
                and (e.get("when") or len(e["code"]) >= 60)
            ]
            if not viable:
                return None
            ex = self._pick_rich_example(viable, query_tokens)

        if not isinstance(ex, dict):
            return None
        code = ex.get("code")
        if not isinstance(code, str) or not code.strip():
            return None
        when = ex.get("when")
        why = ex.get("why")
        # No explanation context ⇒ nothing to add over the legacy render; defer.
        if not when and not why:
            return None

        # Audit #4: 80% of recipes exceeded the old 1000-char budget → the trim
        # amputated the write Transaction (~292) and all returns (~62). 4000 fits
        # the full recipe (≤40 lines) so the model sees the whole write + return.
        budget = 4000 if entry.entry_type == "recipe" else 800
        lines: list[str] = ["```csharp"]
        if when:
            lines.append(f"// КОГДА: {when}")
        # Keep the class-name comment the legacy class path emits, for parity.
        if entry.entry_type != "recipe" and entry.name:
            lines.append(f"// {entry.name}")
        # Statement-boundary trim (plan 013) — never cut C# mid-statement.
        lines.append(_trim_code(code, budget))
        lines.append("```")
        if why:
            lines.append(f"// ПОЧЕМУ/ГРАБЛИ: {why}")
        return "\n".join(lines), code

    def _build_gotchas(self, entries: list[ApiEntry], revit_version=None) -> str:
        """Return a 'Known gotchas' section based on which APIs were retrieved.

        Each hint corresponds to a failure mode confirmed in live_test.log
        (14394 CS-error events). Hints are emitted only when relevant —
        if FilteredElementCollector isn't in the retrieved set, no FEC hint.

        ``revit_version`` (plan 012) makes the ElementId hint version-aware:
        once IntegerValue is removed (year from api_versions.json), the hint must
        NOT advertise the dotted ``.IntegerValue`` form for that version.
        """
        if not entries:
            return ""

        haystack = " ".join(
            (e.name + " " + " ".join(e.examples[:1] if e.examples else [])).lower()
            for e in entries
        )

        hints: list[str] = []

        if "filteredelementcollector" in haystack:
            hints.append(
                "- **FilteredElementCollector + LINQ**: FEC реализует non-generic "
                "`IEnumerable`, поэтому `.Cast<T>()`, `.Where`, `.Any`, `.First`, "
                "`.ToList`, `.Select` НЕ работают напрямую. Перед LINQ-методом всегда "
                "вызывай `.OfType<Element>()` или `.WhereElementIsNotElementType().Cast<T>()`. "
                "`new FilteredElementCollector(doc)` — `doc` обязателен."
            )

        if "elementid" in haystack:
            hints.append(self._elementid_gotcha(revit_version))

        if "ofcategory" in haystack or "builtincategory" in haystack:
            hints.append(
                "- **BuiltInCategory префикс**: `OfCategory(BuiltInCategory.OST_Walls)`, "
                "не `OfCategory(OST_Walls)`. Без префикса — CS0103."
            )

        if "transaction" in haystack or any(
            kw in haystack for kw in (".set(", ".delete(", ".create(")
        ):
            hints.append(
                "- **Transaction**: любая модификация модели должна быть внутри "
                "`using (var t = new Transaction(doc, \"name\")) { t.Start(); ... t.Commit(); }`. "
                "Не используй `Console.WriteLine` — в Revit нет stdout."
            )

        if "failuremessage" in haystack or "getwarnings" in haystack:
            # F-NEW-028 root-cause: LLM groups warnings by per-element
            # GetDescriptionText() which fragments counts and hides the
            # dominant warning type. The correct stable group key is
            # GetFailureDefinitionId().Guid. Also: many Warning-severity
            # items are known false positives (geometry drift, line
            # discrepancies) — don't pressure the user to fix every one.
            hints.append(
                "- **Группировка предупреждений (warnings)**: всегда группируй по "
                "`w.GetFailureDefinitionId().Guid.ToString()` (статичный ID типа ошибки), "
                "а НЕ по `w.GetDescriptionText()` (там per-element детали, которые "
                "фрагментируют счётчики и прячут доминирующий тип). Всегда включай "
                "`w.GetSeverity().ToString()` в результат. Большая часть Warning-уровня — "
                "известный «шум» Revit (отклонения линий, наложения), не пуш юзера "
                "чинить их все подряд."
            )

        # Enum-label hint fires whenever any retrieved entry is an enum.
        # Reinforces the formatter's enum_values render with a behavioral rule
        # (the values themselves come from the formatter; this is the «do not
        # invent» constraint).
        if any(getattr(e, "is_enum", False) for e in entries):
            hints.append(
                "- **Имена enum'ов**: используй имена ровно как они указаны в "
                "API reference выше (`Values:` секция). НИКОГДА не выдумывай "
                "русские/английские лейблы. Возвращай в данных пару "
                "`(value = (int)x, name = x.ToString())` — это даёт правильные "
                "лейблы автоматически."
            )

        if not hints:
            return ""

        return "## Известные грабли (избегай эти ошибки):\n\n" + "\n\n".join(hints)

    def _elementid_gotcha(self, revit_version=None) -> str:
        """Version-aware ElementId.Value/IntegerValue hint (plan 012 Step 5.4).

        - project >= IntegerValue's removal year (from api_versions.json):
          only `.Value` — and DELIBERATELY no dotted `.IntegerValue` token (the
          e2e verify greps the dotted form as the "model would copy this" signal);
        - project <= 2023: the legacy `.IntegerValue`-only text;
        - otherwise (2024/2025): the dual text (both still valid).
        Fail-open to the dual text if the removal fact is unavailable.
        """
        legacy_dual = (
            "- **ElementId.Value vs IntegerValue**: в Revit 2024+ свойство называется "
            "`.Value` (тип `long`). В Revit 2021-2023 — `.IntegerValue` (тип `int`). "
            "Используй то, что подходит к версии проекта."
        )
        yr = _parse_revit_year(revit_version)
        if yr is None or not self._version_filter_enabled():
            return legacy_dual

        rem_yr = None
        try:
            from kukai.rag.api_versions import member_facts
            rem = member_facts("Autodesk.Revit.DB.ElementId").get(
                "IntegerValue", {}).get("removed_in")
            rem_yr = _parse_revit_year(rem) if rem else None
        except Exception:
            logger.debug("elementid gotcha fact lookup failed (non-fatal)", exc_info=True)

        if rem_yr is not None and yr >= rem_yr:
            # No dotted .IntegerValue form here — it is removed in this version.
            return (
                f"- **ElementId — только `.Value`**: в Revit {rem_yr}+ свойство IntegerValue "
                "УДАЛЕНО; используй `.Value` (тип `long`). Старое имя писать без точки нельзя."
            )
        if yr <= 2023:
            return (
                "- **ElementId.IntegerValue**: в Revit 2021-2023 id-свойство называется "
                "`.IntegerValue` (тип `int`). Не используй `.Value` — её ещё нет (CS1061)."
            )
        return legacy_dual
