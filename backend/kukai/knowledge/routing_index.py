"""Load and score the generated recipe-level Wiki routing index."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .release import current_release
from .text import normalized_tokens, normalizer_metadata

logger = logging.getLogger(__name__)
ROUTING_INDEX_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class CardEvidence:
    name: str
    action: str
    object_kinds: frozenset[str]
    token_weights: dict[str, float]


@dataclass(frozen=True)
class PageEvidence:
    slug: str
    domain: str
    actions: frozenset[str]
    objects_by_action: dict[str, frozenset[str]]
    token_weights: dict[str, float]
    trigger_token_sets: tuple[frozenset[str], ...]
    cards: tuple[CardEvidence, ...]


class RoutingEvidenceIndex:
    """Immutable in-memory index; no embeddings, network or large API DB."""

    def __init__(self, pages: dict[str, PageEvidence], source: Path):
        self.pages = pages
        self.source = source

    def query_tokens(self, query: str) -> set[str]:
        return normalized_tokens(query)

    @staticmethod
    def _lexical_score(weights: dict[str, float], tokens: set[str]) -> float:
        return sum(weights.get(token, 0.0) for token in tokens)

    @staticmethod
    def _trigger_phrase_score(
        trigger_token_sets: tuple[frozenset[str], ...],
        query_tokens: set[str],
        *,
        base_bonus: float,
        extra_token_bonus: float,
    ) -> float:
        """Reward a complete curated trigger, beyond bag-of-token overlap."""
        best = 0.0
        for trigger in trigger_token_sets:
            if not trigger or not trigger.issubset(query_tokens):
                continue
            if len(trigger) == 1:
                # A single noun already contributes through IDF lexical
                # scoring; it is too weak to deserve an extra phrase bonus.
                continue
            best = max(
                best,
                base_bonus + extra_token_bonus * min(max(len(trigger) - 1, 0), 4),
            )
        return best

    def score_page(
        self,
        slug: str,
        query_tokens: set[str],
        *,
        action: str | None,
        object_kinds: set[str],
        domain: str | None,
        action_bonus: float = 10.0,
        domain_bonus: float = 5.0,
        object_bonus: float = 2.0,
        action_miss_penalty: float = 2.0,
        trigger_phrase_bonus: float = 8.0,
        trigger_extra_token_bonus: float = 2.0,
    ) -> tuple[float, dict[str, float | bool]]:
        page = self.pages[slug]
        lexical = self._lexical_score(page.token_weights, query_tokens)
        trigger_phrase = self._trigger_phrase_score(
            page.trigger_token_sets,
            query_tokens,
            base_bonus=trigger_phrase_bonus,
            extra_token_bonus=trigger_extra_token_bonus,
        )
        action_hit = bool(action and action in page.actions)
        domain_hit = bool(domain and domain == page.domain)
        object_hit = bool(
            action
            and object_kinds
            and object_kinds.intersection(page.objects_by_action.get(action, frozenset()))
        )
        score = lexical + trigger_phrase
        if action_hit:
            score += action_bonus
        elif action:
            score -= action_miss_penalty
        if domain_hit:
            score += domain_bonus
        if object_hit:
            score += object_bonus
        return score, {
            "lexical": round(lexical, 4),
            "trigger_phrase": round(trigger_phrase, 4),
            "action_hit": action_hit,
            "domain_hit": domain_hit,
            "object_hit": object_hit,
        }

    def rank_cards(
        self,
        slug: str,
        query_tokens: set[str],
        *,
        action: str | None,
        object_kinds: set[str],
    ) -> list[str]:
        page = self.pages.get(slug)
        if not page:
            return []
        scored: list[tuple[float, int, str]] = []
        for index, card in enumerate(page.cards):
            score = self._lexical_score(card.token_weights, query_tokens)
            if action and card.action == action:
                score += 4.0
            if object_kinds.intersection(card.object_kinds):
                score += 1.0
            scored.append((score, -index, card.name))
        scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
        return [name for _, _, name in scored]


def _parse_index(path: Path) -> RoutingEvidenceIndex:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != ROUTING_INDEX_SCHEMA_VERSION:
        raise ValueError(f"unsupported routing index schema: {raw.get('schema_version')!r}")
    generated_normalizer = raw.get("normalizer")
    current_normalizer = normalizer_metadata()
    if generated_normalizer != current_normalizer:
        raise ValueError(
            "routing normalizer drift: "
            f"generated={generated_normalizer!r} runtime={current_normalizer!r}"
        )
    raw_pages = raw.get("pages")
    if not isinstance(raw_pages, dict) or not raw_pages:
        raise ValueError("routing index contains no pages")
    pages: dict[str, PageEvidence] = {}
    for slug, value in raw_pages.items():
        if not isinstance(slug, str) or not isinstance(value, dict):
            raise ValueError("invalid routing page entry")
        cards: list[CardEvidence] = []
        for card in value.get("cards") or []:
            cards.append(CardEvidence(
                name=str(card["name"]),
                action=str(card.get("action") or ""),
                object_kinds=frozenset(str(x) for x in card.get("object_kinds") or []),
                token_weights={str(k): float(v) for k, v in (card.get("token_weights") or {}).items()},
            ))
        pages[slug] = PageEvidence(
            slug=slug,
            domain=str(value.get("domain") or ""),
            actions=frozenset(str(x) for x in value.get("actions") or []),
            objects_by_action={
                str(action): frozenset(str(x) for x in objects)
                for action, objects in (value.get("objects_by_action") or {}).items()
            },
            token_weights={str(k): float(v) for k, v in (value.get("token_weights") or {}).items()},
            trigger_token_sets=tuple(
                frozenset(str(token) for token in token_set)
                for token_set in value.get("trigger_token_sets") or []
            ),
            cards=tuple(cards),
        )
    return RoutingEvidenceIndex(pages, path)


@lru_cache(maxsize=4)
def load_routing_index(path: str | Path | None = None) -> RoutingEvidenceIndex:
    selected = Path(path) if path is not None else current_release().routing_index_path
    return _parse_index(selected)


def reset_routing_index_cache() -> None:
    load_routing_index.cache_clear()
