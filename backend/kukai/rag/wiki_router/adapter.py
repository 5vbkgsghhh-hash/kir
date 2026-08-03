"""Production adapter for the immutable Wiki knowledge release.

The adapter routes a request to one or two curated pages and returns both the
bounded injection and provenance telemetry.  Per-turn failures degrade to an
empty Wiki injection; callers must not substitute the retired vector corpus.
The release itself is verified at startup and again on first load.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from kukai.knowledge.release import KnowledgeRelease, current_release

from . import capability_router, wiki_query

logger = logging.getLogger(__name__)

# The request orchestrator may pass the result of its existing intent
# classifier into ``inject``.  This adapter only validates that value; it never
# starts a model/network request of its own.  If no frame arrives in time, the
# generated lexical/capability index uses the deterministic quick classifier.
try:
    from kukai.agents.capability_vocab import (
        action_vocab as _action_vocab,
        capability_domain_vocab as _capability_domain_vocab,
        derive_action_from_intent as _derive_action_from_intent,
        object_kind_vocab as _object_kind_vocab,
    )
except Exception:
    _action_vocab = None  # type: ignore
    _capability_domain_vocab = None  # type: ignore
    _derive_action_from_intent = None  # type: ignore
    _object_kind_vocab = None  # type: ignore

def frame_from_classifier_value(val: dict) -> Optional[dict]:
    """Raw classifier JSON (`val`) -> OperationFrame dict, vocab-validated.

    Used by client.py's existing IntentClassifier -> Wiki frame bridge.  It
    has the same shape as ``capability_router.derive_quick_frame`` so routing
    does not care whether the request-level classifier finished in time.

    ABSOLUTE fail-open: returns None on any vocab-import gap, non-dict input,
    or validation exception — never raises. Callers MUST treat None as "no
    usable frame" (fall back to ``derive_quick_frame``).
    """
    if _action_vocab is None or not isinstance(val, dict):
        return None
    try:
        action = val.get("action")
        if not action or action not in _action_vocab():
            action = _derive_action_from_intent(val.get("intent"))

        object_kinds = [
            k for k in (val.get("object_kinds") or []) if k in _object_kind_vocab()
        ]

        cap_domain = val.get("capability_domain")
        if cap_domain not in _capability_domain_vocab():
            cap_domain = None

        return {
            "action": action,
            "object_kinds": object_kinds,
            "domain": cap_domain,
            "intent": val.get("intent"),
            "complexity": val.get("complexity"),
        }
    except Exception:
        return None

# Belt-and-braces cap above the router's tighter 9K/16K page budgets.
_MAX_INJECTION_CHARS = 45000

_SHADOW_LOG_REL = ("data", "telemetry", "wiki_router_shadow.jsonl")
_CSHARP_BLOCK_RE = re.compile(
    r"```(?:csharp|cs)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL,
)


class WikiRouter:
    """Loads the wiki page corpus + routing table once, then answers inject() calls.

    The loaded release and routing table are immutable for the process.
    """

    def __init__(self) -> None:
        self._pages: Optional[dict] = None
        self._table: Optional[capability_router.RoutingTable] = None
        self._release: Optional[KnowledgeRelease] = None
        # .../kukai/rag/wiki_router/adapter.py -> backend/
        self._backend_dir = Path(__file__).resolve().parents[3]

    def ensure_loaded(self) -> None:
        """Load pages + build the routing table once. Idempotent — safe to
        call on every request; a no-op after the first successful load."""
        if self._pages is not None:
            return
        release = current_release()
        pages = wiki_query.load_pages(release.wiki_root)
        table = capability_router.build_routing_table(pages)
        runtime_metrics = {
            "pages": len(pages),
            "recipe_cards": sum(len(page.cards) for page in pages.values()),
            "domains": len({page.domain for page in pages.values()}),
        }
        for key, actual in runtime_metrics.items():
            expected = release.metrics.get(key)
            if expected != actual:
                raise ValueError(
                    f"knowledge manifest metric drift for {key}: "
                    f"expected {expected!r}, runtime {actual!r}"
                )
        # Assign both together at the end so a mid-load exception never
        # leaves _pages set without a matching _table (ensure_loaded would
        # then wrongly treat the router as loaded on the next call).
        self._pages = pages
        self._table = table
        self._release = release

    def metadata(self) -> dict:
        """Read-only provenance and runtime counts for startup/health."""
        self.ensure_loaded()
        release = self._release
        pages = self._pages or {}
        if release is None:
            raise RuntimeError("Wiki release was not loaded")
        value = release.public_metadata()
        value["runtime"] = {
            "pages": len(pages),
            "recipe_cards": sum(len(page.cards) for page in pages.values()),
            "domains": len({page.domain for page in pages.values()}),
        }
        return value

    def inject(
        self,
        user_message: str,
        revit_version: Optional[str] = None,
        frame: Optional[dict] = None,
        skip_llm_fallback: bool = False,
    ) -> tuple[str, dict]:
        """Route `user_message` to wiki page(s) and build the injection text.

        Mirrors capability_router.process_query()'s pipeline: derive (or
        accept a caller-supplied) OperationFrame -> route() -> build_injection().

        Args:
            user_message: the user's latest message.
            revit_version: active Revit version, used for the compact API
                reference appended after the routed recipes.
            frame: an OperationFrame dict (or a composite list of them,
                see capability_router.route()) if the caller already has one
                computed by the request orchestrator. When absent, routing
                immediately uses the deterministic quick frame.
            skip_llm_fallback: retained for caller compatibility. There is no
                adapter-level LLM fallback anymore; both values are local-only.

        Returns:
            (text, telemetry). On ANY failure, ("", {"error": "..."}) — the
            caller must treat an error key / empty text as a Wiki miss.
            telemetry (success case) = {frame, routed_pages, route_type,
            inject_chars, first_recipe, latency_ms, frame_source,
            api_ref_applied}. `api_ref_applied` (Lever 1, SPEC_lever1_api_ref.md)
            is True only when KUKAI_WIKI_API_REF is on, `revit_version` was
            given, and at least one routed page's frontmatter api_classes
            resolved to a non-empty members block appended to `text`.
            frame_source is ``threaded`` when supplied by the request-level
            classifier, ``cache`` when an S3 cache hit served a prior
            ``threaded`` frame for the same normalized query, otherwise
            ``quick``/``quick_after_timeout`` (the floor path — see
            FRAME_UPLIFT_TASKS.md S2/S3; frame_lexicon.py owns both the
            floor-frame lexicon enrichment and the deepseek-frame cache).
        """
        t0 = time.perf_counter()
        try:
            if not user_message or not user_message.strip():
                return "", {"error": "empty user_message"}

            self.ensure_loaded()
            pages = self._pages
            table = self._table
            if not pages or table is None:
                return "", {"error": "wiki router loaded no pages"}

            if frame is not None:
                frame_source = "threaded"
                # S3 (FRAME_UPLIFT_TASKS.md): cache only deepseek/"threaded"
                # frames — never the floor frame (see below). Best-effort,
                # absolute fail-open: any cache-module problem just means no
                # caching this turn, never affects the frame actually used.
                try:
                    from kukai.rag.wiki_router.frame_lexicon import get_frame_cache
                    get_frame_cache().put_if_deepseek(user_message, frame, frame_source)
                except Exception:
                    logger.debug("wiki_router: frame cache put failed (non-fatal)", exc_info=True)
            else:
                cached = None
                try:
                    from kukai.rag.wiki_router.frame_lexicon import get_frame_cache
                    cached = get_frame_cache().get(user_message)
                except Exception:
                    logger.debug("wiki_router: frame cache get failed (non-fatal)", exc_info=True)
                if cached is not None:
                    frame = cached
                    frame_source = "cache"
                else:
                    frame = capability_router.derive_quick_frame(user_message)
                    frame_source = "quick_after_timeout" if skip_llm_fallback else "quick"
                    # S2 (FRAME_UPLIFT_TASKS.md): floor/quick frame always has
                    # object_kinds==[] and domain=None (see derive_quick_frame's
                    # own docstring) — that blinds ROUTER_V3's soft-fusion
                    # bonuses on every floor-path request. KUKAI_FRAME_LEXICON
                    # (off by default) monotonically enriches ONLY those empty
                    # slots from the offline RU-token lexicon; shadow mode
                    # computes+logs but still routes on the ORIGINAL frame.
                    # Absolute fail-open: apply_to_floor_frame() itself never
                    # raises, but the import is still guarded per this
                    # module's own convention (KIR-shadow style).
                    try:
                        from kukai.rag.wiki_router.frame_lexicon import apply_to_floor_frame
                        frame = apply_to_floor_frame(frame, user_message, shadow_log_fn=self.shadow_log)
                    except Exception:
                        logger.debug("wiki_router: frame lexicon enrichment failed (non-fatal)", exc_info=True)

            routed_slugs, route_type, _used_fuzzy = capability_router.route(
                frame, user_message, table, pages,
            )
            # W2-B (2026-07-11, SPEC_W2B_card_rank.md): reuse the SAME frame
            # that just picked the page(s) above to also rank the Verified-
            # recipe CARDS within each page (capability-match bonus ahead of
            # wiki_query's token-overlap tie-break) -- flag-gated
            # (KUKAI_WIKI_CARD_RANK) and fail-open all the way down in
            # wiki_query.build_injection, so passing `frame` here is inert
            # while the flag is off (byte-identical to pre-W2-B).
            text, first_recipe, inject_chars = capability_router.build_injection(
                routed_slugs, pages, user_message, frame=frame,
                routing_index=table.evidence_index,
                revit_version=revit_version,
            )

            # Lever 1 (2026-07-11, SPEC_lever1_api_ref.md): append a compact,
            # version-filtered "Справка API" for the routed page(s)' frontmatter
            # api_classes, in whatever budget remains after the base injection
            # above. Deliberately NOT done inside capability_router.build_injection
            # (owned concurrently by Lever 2 -- not modified here): this adapter
            # already has `routed_slugs`/`pages`/`revit_version` in hand right
            # here, so the append happens as an adapter-level post-step instead.
            # wiki_query.build_injection's OWN internal hook (used by this same
            # helper's single-page callers, e.g. the offline CLI/gate harness)
            # stays inert on this call path because capability_router calls it
            # with no `revit_version` -- this block is what actually wires Lever
            # 1 into the live adapter. Enabled by default (KUKAI_WIKI_API_REF
            # is an emergency kill switch) and absolute fail-open: any error
            # falls back to the base `text` computed above, never breaks the turn.
            api_ref_applied = False
            if routed_slugs and revit_version and wiki_query.api_ref_flag_enabled():
                try:
                    remaining = _MAX_INJECTION_CHARS - len(text)
                    if remaining >= wiki_query.API_REF_MIN_BUDGET:
                        per_page_budget = remaining // len(routed_slugs)
                        # REF_GAP fix (2026-07-12): the query tokens drive
                        # build_api_reference's enum relevance-ranking (large
                        # BuiltInParameter/BuiltInCategory subsets, and gating
                        # the universal watchlist). Inert when the new
                        # KUKAI_WIKI_APIREF_ENUMS sub-flag is off
                        # (build_api_reference ignores q_tokens entirely then),
                        # so passing it is byte-identical to before for the
                        # Lever-1-only (enum-flag-off) deployment.
                        q_tokens = wiki_query.tokenize(user_message)
                        api_blocks = []
                        for slug in routed_slugs:
                            pg = pages.get(slug)
                            if pg is None:
                                continue
                            block = wiki_query.build_api_reference(
                                pg.api_classes, revit_version, per_page_budget,
                                q_tokens,
                            )
                            if block:
                                api_blocks.append(block)
                        if api_blocks:
                            text = text.rstrip("\n") + "\n\n" + "\n\n".join(api_blocks)
                            inject_chars = len(text)
                            api_ref_applied = True
                except Exception:
                    logger.debug(
                        "Lever 1: wiki router API-reference append failed (non-fatal)",
                        exc_info=True,
                    )

            if len(text) > _MAX_INJECTION_CHARS:
                text = text[:_MAX_INJECTION_CHARS]
                inject_chars = len(text)

            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            telemetry = {
                "frame": frame,
                "routed_pages": routed_slugs,
                "route_type": route_type,
                "inject_chars": inject_chars,
                "first_recipe": first_recipe,
                "latency_ms": latency_ms,
                "frame_source": frame_source,
                "api_ref_applied": api_ref_applied,
                "revit_version": wiki_query.revit_year(revit_version),
                "eligible_recipe_count": sum(
                    1
                    for slug in routed_slugs
                    for card in pages[slug].cards
                    if wiki_query.card_supports_version(card, revit_version)
                ),
                "excluded_recipe_count": sum(
                    1
                    for slug in routed_slugs
                    for card in pages[slug].cards
                    if not wiki_query.card_supports_version(card, revit_version)
                ),
                "release_id": self._release.release_id if self._release else None,
                "corpus_version": self._release.corpus_version if self._release else None,
                "manifest_sha256": (
                    self._release.manifest_sha256 if self._release else None
                ),
            }
            return text, telemetry
        except Exception as e:  # absolute fail-open — router must never break a turn
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            logger.warning("Wiki router inject() failed; no legacy fallback: %s", e)
            return "", {"error": f"{type(e).__name__}: {e}", "latency_ms": latency_ms}

    def recipe_examples(
        self,
        user_message: str,
        *,
        max_examples: int = 5,
        frame: Optional[dict] = None,
        revit_version: Optional[str] = None,
    ) -> list[dict]:
        """Return compact verified recipe examples for critic/repair agents.

        This is a deterministic view over the same routed release and generated
        card ranking used by prompt injection.  It performs no model call,
        embedding request or legacy-corpus lookup.
        """
        if not user_message or max_examples <= 0:
            return []
        self.ensure_loaded()
        pages = self._pages or {}
        table = self._table
        if not pages or table is None:
            return []
        selected_frame = frame or capability_router.derive_quick_frame(user_message)
        slugs, _route_type, _used_fuzzy = capability_router.route(
            selected_frame, user_message, table, pages,
        )
        query_tokens = (
            table.evidence_index.query_tokens(user_message)
            if table.evidence_index is not None
            else wiki_query.tokenize(user_message)
        )
        result: list[dict] = []
        for slug in slugs:
            page = pages.get(slug)
            if page is None:
                continue
            preferred_names: list[str] = []
            if table.evidence_index is not None:
                preferred_names = table.evidence_index.rank_cards(
                    slug,
                    query_tokens,
                    action=selected_frame.get("action"),
                    object_kinds=set(selected_frame.get("object_kinds") or []),
                )
            compatible_cards = [
                card for card in page.cards
                if wiki_query.card_supports_version(card, revit_version)
            ]
            by_name = {card.name: card for card in compatible_cards}
            ordered = [by_name[name] for name in preferred_names if name in by_name]
            seen = {card.name for card in ordered}
            ordered.extend(
                sorted(
                    (card for card in compatible_cards if card.name not in seen),
                    key=lambda card: -len(card.match_tokens & set(query_tokens)),
                )
            )
            for card in ordered:
                code_match = _CSHARP_BLOCK_RE.search(card.raw)
                result.append({
                    "name": card.name,
                    "namespace": f"wiki:{page.domain}/{page.slug}",
                    "description": card.use_when[:500],
                    "example_code": (
                        code_match.group(1).strip()[:2000] if code_match else ""
                    ),
                    "capability": card.capability,
                    "compiles": card.compiles,
                    "release_id": self._release.release_id if self._release else None,
                })
                if len(result) >= max_examples:
                    return result
        return result

    def shadow_log(self, record: dict) -> None:
        """Best-effort append of one JSON record to
        data/telemetry/wiki_router_shadow.jsonl. Never raises — a logging
        failure must not affect the request."""
        try:
            path = self._backend_dir.joinpath(*_SHADOW_LOG_REL)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.debug("wiki_router shadow_log failed (non-fatal)", exc_info=True)


_singleton: Optional[WikiRouter] = None


def get_wiki_router() -> WikiRouter:
    """Return the process-wide immutable Wiki router."""
    global _singleton
    if _singleton is None:
        _singleton = WikiRouter()
    return _singleton
