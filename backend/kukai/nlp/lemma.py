"""Lemma-normalized Russian morphology (flag ``KUKAI_LEMMA_LEXICON``, IQ-moment #7).

The IQ-moments audit (2026-07-04, §1.3 / meta-pattern 3) found the same
category knowledge hand-enumerated as declension tables in 3+ places
(``kukai.categories.CATEGORY_MAP``, ``session_state.CATEGORY_HINTS``,
``write.router.CATEGORY_TO_BUILTIN``) plus a 30-suffix strip list in the RAG
tokenizer — with PROVEN holes (``стене``, ``стеной``, ``окне``, ``дверью``
missing). This module is the single normalization those tables key on instead:
``lemma("стеной") == lemma("стена") == "стена"`` — whole paradigms
(6 cases x 2 numbers) collapse to one entry, so coverage completes *by
construction*.

Design contract:

* ``lemma(word)`` is **flag-independent pure morphology** (lru_cached). The
  ``KUKAI_LEMMA_LEXICON`` flag gates the *call sites* (categories /
  session_state / the RAG tokenizer), never this function — so a flipped flag
  can never serve stale cache entries.
* **pymorphy3** (pure-Python, offline DAWG dictionaries) is imported lazily on
  the first call; if it is missing or broken, ``lemma()`` degrades to the
  legacy suffix stripper below — production must never break on a dependency.
* **ASCII tokens pass through lowercased-only** — byte-identical to the legacy
  normalizer, whose suffixes are all Cyrillic (an ASCII token can never match
  them), so English behavior is unchanged by construction.
* ``ё`` folds to ``е`` on output, so «решётка»/«решетка» meet at one key
  (pymorphy3 canonicalizes normal forms TO ``ё``; user input mostly has ``е``).
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)


def lemma_lexicon_enabled() -> bool:
    """Read the ``KUKAI_LEMMA_LEXICON`` flag at call time.

    Same pattern as ``KUKAI_BM25F`` / ``KUKAI_RAG_RECIPES_ENABLED``: env-read
    per call, default OFF ⇒ byte-identical legacy behavior everywhere.
    """
    import os

    return os.getenv("KUKAI_LEMMA_LEXICON", "0") == "1"


# Matches any lowercase Cyrillic letter (lemma() lowercases before testing).
_CYRILLIC_RE = re.compile(r"[а-яё]")

# Byte-aligned mirror of ``kukai.rag.revit_api_index._RU_SUFFIXES`` — the
# legacy greedy suffix stripper, kept as the no-pymorphy3 FALLBACK. Duplicated
# rather than imported: ``revit_api_index`` imports THIS module under the flag,
# and the fallback must not create an import cycle. Keep the two lists in sync.
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
    "е", "у", "о",  # various cases
]


def _suffix_strip(token: str) -> str:
    """Legacy normalization (exact mirror of ``_normalize_token``'s strip)."""
    if len(token) <= 3:
        return token
    for suffix in _RU_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)]
    return token


@lru_cache(maxsize=1)
def _get_morph():
    """The pymorphy3 analyzer, or ``None`` if unavailable (graceful fallback).

    Construction loads the RU DAWG dictionaries (~50 ms, once per process).
    A probe parse fails fast HERE — not later on the hot path — so a broken
    dictionary install degrades to the fallback exactly like a missing one.
    """
    try:
        import pymorphy3

        morph = pymorphy3.MorphAnalyzer()
        morph.parse("стена")  # probe: dictionaries actually work
        return morph
    except Exception:
        logger.warning(
            "pymorphy3 unavailable — lemma() falls back to the legacy RU "
            "suffix stripper (declension coverage reduced, nothing breaks)",
            exc_info=True,
        )
        return None


@lru_cache(maxsize=65536)
def lemma(word: str) -> str:
    """Normalize one word to its lemma (normal form).

    * Cyrillic → pymorphy3 normal form (``стеной`` → ``стена``), ``ё``→``е``;
    * non-Cyrillic → lowercased unchanged (legacy-identical for English);
    * pymorphy3 unavailable → legacy suffix strip.

    μs-level amortized: results are lru_cached (vocabulary in real queries and
    the keyword tables is small); a cold pymorphy3 parse is ~20-200 μs.
    """
    token = word.lower().strip()
    if not token or not _CYRILLIC_RE.search(token):
        return token
    morph = _get_morph()
    if morph is None:
        return _suffix_strip(token)
    try:
        parses = morph.parse(token)
        if parses:
            return parses[0].normal_form.replace("ё", "е")
    except Exception:  # noqa: BLE001 — morphology is best-effort, never raises
        logger.debug("pymorphy3 parse failed for %r", token, exc_info=True)
    return _suffix_strip(token)


def lemma_phrase(phrase: str) -> str:
    """Per-word lemma of a (possibly multi-word) phrase.

    Used to derive lemma keys FROM the existing surface-form tables
    (``кабельным лотком`` → ``кабельный лоток``) and to normalize query
    n-grams the same way — both sides always meet at the same key.
    """
    p = phrase.lower().strip()
    if " " not in p:
        return lemma(p)
    return " ".join(lemma(w) for w in p.split())
