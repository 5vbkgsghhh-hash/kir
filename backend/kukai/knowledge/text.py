"""Shared RU/EN normalisation for Wiki routing and release generation."""

from __future__ import annotations

import re
import threading
from functools import lru_cache
from importlib import metadata

TOKENIZER_SCHEMA_VERSION = 1
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
_CYRILLIC_RE = re.compile(r"^[а-яё]+$", re.IGNORECASE)

# Routing stop words, deliberately small. Domain words such as "лист",
# "вид", "стена" and "модель" stay searchable; generic instruction glue
# does not dominate IDF evidence.
STOPWORDS = frozenset({
    "и", "в", "во", "на", "по", "с", "со", "для", "как", "что", "это",
    "то", "а", "но", "или", "из", "за", "к", "ко", "у", "до", "от",
    "при", "же", "ли", "бы", "не", "нет", "есть", "все", "всех", "всей",
    "всего", "одну", "эту", "эта", "этот", "эти", "него", "нее", "них",
    "между", "над", "под", "о", "об", "про", "нужно", "надо", "когда",
    "через", "этого", "этой", "который", "которая", "the", "a", "an",
    "of", "to", "in", "on", "for", "and", "or", "revit",
})

_MORPH = None
_MORPH_LOCK = threading.Lock()


def _morph():
    global _MORPH
    if _MORPH is None:
        with _MORPH_LOCK:
            if _MORPH is None:
                import pymorphy3

                _MORPH = pymorphy3.MorphAnalyzer()
    return _MORPH


@lru_cache(maxsize=50_000)
def normalize_token(token: str) -> str:
    token = (token or "").strip().lower()
    if not token:
        return ""
    if _CYRILLIC_RE.fullmatch(token):
        try:
            return str(_morph().parse(token)[0].normal_form)
        except Exception:
            # Cheap deterministic fallback keeps routing alive if dictionaries
            # are damaged; release validation still reports the dependency.
            return token[:6] if len(token) > 7 else token
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def normalized_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if len(raw) <= 1 or raw in STOPWORDS:
            continue
        token = normalize_token(raw)
        if token and token not in STOPWORDS:
            out.add(token)
    return out


def normalizer_metadata() -> dict[str, object]:
    def _version(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "missing"

    return {
        "schema_version": TOKENIZER_SCHEMA_VERSION,
        "pymorphy3": _version("pymorphy3"),
        "pymorphy3_dicts_ru": _version("pymorphy3-dicts-ru"),
    }
