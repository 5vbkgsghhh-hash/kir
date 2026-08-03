"""RU gold loader for the plan-009 honest RAG benchmark.

Source: ``backend/scripts/research/control_audit500.jsonl`` — 500 rows, of which
the 200 with a non-empty ``expected_apis`` are the gold set. Each row carries a
Russian input (``ru``), a curated English reading (``en``) used to *replay* the
translation leg offline, and the expected Revit API names a competent retrieval
should surface.

Matching convention (mirrors ``gold_set.GoldQuery.matches_id``,
``gold_set.py:52-62``): a retrieved key ``entry_type:namespace.Name`` is a hit
for an expected API when the retrieved class ``Name`` matches the expected
API's class token. Expected APIs come in three shapes, all handled:

  - plain class     : ``Wall``                  -> compare ``Wall``
  - class.member    : ``Wall.Create``           -> compare ``Wall`` (head)
  - enum.member     : ``BuiltInCategory.OST_*`` -> compare ``BuiltInCategory``
  - ns-qualified    : ``Autodesk.Revit.DB.Wall``-> compare ``Wall`` (tail)

We therefore compare the retrieved tail ``Name`` against {head, tail, whole} of
the expected token. ``strict`` mode first drops the two ubiquitous APIs that
inflated the old 98.2% headline (every "find elements" query trivially matches
``FilteredElementCollector``/``Transaction``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# The two APIs that appear in nearly every Revit task and so trivially inflate
# Hit@K. ``strict`` aggregates exclude them (and exclude queries whose expected
# list becomes empty as a result).
UBIQUITOUS: frozenset[str] = frozenset({"FilteredElementCollector", "Transaction"})


def _default_gold_path() -> Path:
    # backend/kukai/rag/benchmark/gold_ru.py -> backend/
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "scripts" / "research" / "control_audit500.jsonl"


def _retrieved_name(key: str) -> str:
    """Tail ``.Name`` of a retrieved key ``entry_type:namespace.Name``."""
    after_colon = key.split(":", 1)[-1]
    return after_colon.rsplit(".", 1)[-1] if "." in after_colon else after_colon


def _expected_tokens(api: str) -> set[str]:
    """Comparable name tokens for an expected API: {head, tail, whole}."""
    tokens = {api}
    if "." in api:
        tokens.add(api.split(".", 1)[0])   # class head: Wall.Create -> Wall
        tokens.add(api.rsplit(".", 1)[-1])  # tail: Autodesk.Revit.DB.Wall -> Wall
    return tokens


@dataclass
class RuGoldQuery:
    """One RU gold query with curated EN reading and expected APIs."""

    id: str
    ru: str
    en: str
    expected_apis: list[str]
    domain: str = ""
    intent: str = ""
    complexity: str = ""

    def expected_for(self, strict: bool) -> list[str]:
        """Expected API list under the chosen flavour."""
        if not strict:
            return list(self.expected_apis)
        return [a for a in self.expected_apis if a not in UBIQUITOUS]

    def strict_excluded(self) -> bool:
        """True when the strict-expected list is empty (counted, not scored)."""
        return len(self.expected_for(strict=True)) == 0

    def matches_key(self, key: str, strict: bool) -> bool:
        """Does retrieved ``key`` satisfy any expected API (chosen flavour)?"""
        name = _retrieved_name(key)
        for api in self.expected_for(strict=strict):
            if name in _expected_tokens(api):
                return True
        return False

    def hit_at_k(self, keys: list[str], k: int, strict: bool) -> bool:
        """True if any of the top-``k`` retrieved keys matches an expected API."""
        expected = self.expected_for(strict=strict)
        if not expected:
            return False  # strict-excluded — caller filters these out of aggregates
        for key in keys[:k]:
            if self.matches_key(key, strict=strict):
                return True
        return False


def load_control_audit500(path: Optional[Path] = None) -> list[RuGoldQuery]:
    """Load the gold set (rows with non-empty ``expected_apis`` only).

    Returns exactly 200 rows for the shipped control_audit500.jsonl. Raises
    ``FileNotFoundError`` if the gold source is missing (a STOP condition for
    the benchmark — never silently substitute a different set).
    """
    p = Path(path) if path is not None else _default_gold_path()
    if not p.exists():
        raise FileNotFoundError(f"gold source not found: {p}")
    out: list[RuGoldQuery] = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            apis = row.get("expected_apis") or []
            if not apis:
                continue
            out.append(
                RuGoldQuery(
                    id=str(row.get("id", "")),
                    ru=str(row.get("ru", "")),
                    en=str(row.get("en", "")),
                    expected_apis=list(apis),
                    domain=str(row.get("domain", "")),
                    intent=str(row.get("intent", "")),
                    complexity=str(row.get("complexity", "")),
                )
            )
    return out
