"""§18.1 — the census law: a document's accounting must reconcile.

    |elements in the document| = lifted_into_ops
                                + atoms (each with a typed reason)
                                + unscanned (each row with a typed
                                  reason)

Before this wave, the denominator of any coverage percentage was a SAMPLE:
extract reads a closed table of 47 categories, and anything not in the table
yielded neither an element, nor a status row, nor a refusal (audit finding
M3, 2026-07-28). There is no topography, site, parking, planting, mass,
rebar, insulation — yet "93% coverage" was computed from what was seen, and
said nothing about what was never looked at.

The census (``L0Document.census``) is one cheap, whole-model pass —
``FilteredElementCollector(doc).WhereElementIsNotElementType()`` — keyed by
BuiltInCategory (§18.5: the localized name is a reference column only).
This module reconciles it against what was actually extracted, and sorts
the difference into typed reasons.

The direction of a discrepancy is not symmetric, and this is the module's
central decision:

* A SHORTFALL (census > extracted) is NOT an error — it is exactly
  ``unscanned``; every such row gets a typed reason;
* AN OVERAGE (extracted > census) is the claim "more elements were read
  than exist in the document". Refutable, and always a defect: a typed run
  error, not a warning (§18.1).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .schema import CategoryState, L0Document


# The census key for an element without a category. Not "other" and not an
# empty string: the absence of a category is a fact about the document
# (views, sheets, service elements), and it must be countable, not dissolve.
NO_CATEGORY_KEY = "no_category"

# The call to ``Element.Category`` THREW. Before 12.08.2026 such an element
# fell into ``no_category`` along with genuinely categoryless ones: a
# `catch { }` in the census (`extract.py`) turned an INSTRUMENT's refusal
# into a MEASUREMENT — canon form 3. The cost is measured: on the
# `k2_ar_rd_v7` tower the `no_category` key carries 53,896 elements = 17.35%
# of the document, and there was NO WAY to learn from the artifacts how many
# of them were of which kind: it was one key.
#
# The keys are split, and these are different subjects with different fixes:
#   no_category          — a fact about the MODEL: the element has no
#                          category in Revit. Not fixed by the extraction
#                          table at all, because the table is keyed by
#                          CATEGORY (an architectural boundary).
#   category_read_failed — a fact about OUR reading: asking failed.
#
# Old artifacts do not carry the new key — 77 stored runs were captured
# before the split, and their `no_category` remains the sum of both kinds.
# The distinction holds by construction, with no schema version: a key that
# is not there cannot be confused with one that is.
CATEGORY_READ_FAILED_KEY = "category_read_failed"

# How many "unscanned" rows are printed by name; the rest is folded into a
# remainder that keeps BOTH numbers (how many categories and how many
# elements) — a truncated tail whose size goes unstated would be exactly the
# same omission this law was written to forbid.
TOP_N = 8


class UnscannedReason(str, Enum):
    """A closed dictionary of reasons an element was not read."""

    # The category is not in the extraction table at all: the element is
    # invisible to reading.
    CATEGORY_OUTSIDE_TABLE = "category_outside_table"
    # The category is in the table, but its page/probe failed (CategoryState.PARTIAL).
    PAGE_REFUSED = "page_refused"
    # The category is in the table, status complete, but fewer elements
    # arrived than the census counted. The reason is not always known
    # (closed worksets, a subclass the collector does not pick up, a
    # DirectShape filter), so it is named by its own name — "read fewer" —
    # rather than substituted with a guess from the §18.1 dictionary. A guess
    # here would be the same defect as a budget that silently drops
    # elements.
    CATEGORY_SHORT_READ = "category_short_read"


class CensusBalanceError(str, Enum):
    """Typed identity errors (§18.1: a run error, not a warning)."""

    EXTRACTED_EXCEEDS_CENSUS = "extracted_exceeds_census"
    CENSUS_TOTAL_MISMATCH = "census_total_mismatch"


@dataclass(frozen=True, slots=True)
class UnscannedRow:
    """One "unscanned" row with a typed reason."""

    category: str
    census_count: int
    extracted_count: int
    unscanned: int
    reason: UnscannedReason
    category_ru: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "category_ru": self.category_ru,
            "census_count": self.census_count,
            "extracted_count": self.extracted_count,
            "unscanned": self.unscanned,
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class CensusBalance:
    """The reconciled accounting for one run.

    ``present=False`` means the census was NOT TAKEN (a frozen L0 captured
    before this wave, or a bridge that did not return one). This is honest
    degradation: the numbers are absent rather than replaced with zeros, and
    any percentage must be printed with the caveat "there is no document
    denominator".
    """

    present: bool
    census_total: int
    extracted: int
    unscanned: int
    categories_in_model: int
    categories_scanned: int
    rows: tuple[UnscannedRow, ...] = ()
    errors: tuple[dict[str, Any], ...] = ()

    @property
    def balanced(self) -> bool:
        return not self.errors

    def document_pct(self, lifted: int) -> float | None:
        """Percent of the WHOLE document (denominator is the census), or None."""
        if not self.present or self.census_total <= 0:
            return None
        return round(100.0 * lifted / self.census_total, 2)

    def extracted_pct(self, lifted: int) -> float | None:
        """Percent of what was READ — a historical base, kept explicit."""
        if self.extracted <= 0:
            return None
        return round(100.0 * lifted / self.extracted, 2)

    def top_rows(self, top_n: int = TOP_N) -> tuple[UnscannedRow, ...]:
        return self.rows[:top_n]

    def by_category_dict(self, top_n: int = TOP_N) -> dict[str, Any]:
        top = self.top_rows(top_n)
        rest = self.rows[top_n:]
        return {
            "top": [row.to_dict() for row in top],
            "other_categories": len(rest),
            "other_elements": sum(row.unscanned for row in rest),
        }

    def to_dict(self, top_n: int = TOP_N) -> dict[str, Any]:
        return {
            "census_present": self.present,
            "census_total": self.census_total,
            "extracted": self.extracted,
            "unscanned_elements": self.unscanned,
            "categories_in_model": self.categories_in_model,
            "categories_scanned": self.categories_scanned,
            "unscanned_by_category": self.by_category_dict(top_n),
            "census_balanced": self.balanced,
            "census_balance_errors": [dict(error) for error in self.errors],
        }

    def summary_ru(self, top_n: int = 3) -> str:
        """A §18.1 human-readable string (in Russian, by design) — printed BEFORE percentages."""
        if not self.present:
            return ("переписи нет в этом L0 (снят до §18.1) — знаменателя "
                    "документа не существует, проценты ниже считаны от "
                    "ПРОЧИТАННОГО")
        head = (f"категорий в модели {self.categories_in_model}, "
                f"читается {self.categories_scanned}; "
                f"не читалось {self.unscanned} элементов "
                f"из {self.census_total}")
        top = [row for row in self.top_rows(top_n) if row.unscanned]
        if not top:
            return head
        listed = ", ".join(
            f"{row.category} {row.unscanned}" for row in top)
        rest = self.rows[top_n:]
        tail = sum(row.unscanned for row in rest)
        if tail:
            listed += f", прочие {len(rest)} категорий {tail}"
        return f"{head} (топ: {listed})"


def _extract_table() -> frozenset[str]:
    # Import inside the function: extract.py is the package's heaviest
    # module, and this one is also used by offline tools that need no bridge.
    from .extract import EXTRACT_CATEGORIES

    return frozenset(EXTRACT_CATEGORIES)


def _table_of_this_document(document: L0Document) -> frozenset[str]:
    """The reading table of THAT generation which captured this document.

    Taken from the snapshot itself: ``category_status`` writes exactly one
    row per table category, so the list of statuses IS the run's table —
    with no call to ``extract.py`` and no guessing at a generation.

    WHY, rather than "today's table". The "unscanned" reason must describe
    THAT run. On 29.07 the table grew 54 -> 73; with today's table, all 19
    new categories of an old snapshot would get
    ``category_short_read`` — "extraction read and under-read" — that is,
    the snapshot would be charged with a failure it did not commit, and
    instead of table growth the report would show a reading regression. The
    correct answer is exactly one: these categories were not in the table
    THEN.

    An empty status list is not "the table is empty": that is what a
    document assembled bypassing the snapshot looks like (fixtures,
    materialize without statuses). Then we have no information about the
    table at all, and today's is used instead — but this is an EXPLICIT
    fallback, not a silent substitution.
    """
    visited = frozenset(status.category for status in document.category_status)
    return visited or _extract_table()


def reconcile_census(
    document: L0Document,
    *,
    table: frozenset[str] | None = None,
) -> CensusBalance:
    """Reconcile the document's census against what was actually extracted.

    ``table`` is the set of categories extraction knew how to read AT THE
    MOMENT this document was captured. By default it is taken from the
    snapshot itself (see :func:`_table_of_this_document`), not from today's
    ``EXTRACT_CATEGORIES``: the rule must measure a snapshot against its own
    table, otherwise table growth would retroactively rewrite the reasons
    for failures in already-captured snapshots. An explicit argument still
    takes priority — it exists for tests and for a foreign build with a
    different table.
    """

    known = _table_of_this_document(document) if table is None else table
    extracted_by_category: dict[str, int] = {}
    for element in document.elements:
        extracted_by_category[element.category] = (
            extracted_by_category.get(element.category, 0) + 1)
    extracted_total = len(document.elements)

    if not document.census:
        # Honest degradation: without a census there is neither a
        # denominator nor "unscanned" rows. A zero here would mean "nothing
        # was unscanned", that is, exactly the silent 100% lie that §18.1
        # forbids.
        return CensusBalance(
            present=False,
            census_total=0,
            extracted=extracted_total,
            unscanned=0,
            categories_in_model=0,
            categories_scanned=0,
        )

    status_by_category: dict[str, CategoryState] = {
        status.category: status.state for status in document.category_status}

    census_by_key = {entry.key: entry for entry in document.census}
    census_total = sum(entry.count for entry in document.census)

    rows: list[UnscannedRow] = []
    errors: list[dict[str, Any]] = []
    for key, entry in census_by_key.items():
        seen = extracted_by_category.get(key, 0)
        if seen > entry.count:
            errors.append({
                "code": CensusBalanceError.EXTRACTED_EXCEEDS_CENSUS.value,
                "category": key,
                "census_count": entry.count,
                "extracted_count": seen,
                "detail": (
                    f"извлечено {seen} элементов категории {key}, "
                    f"а перепись документа насчитала {entry.count}"),
            })
            continue
        missing = entry.count - seen
        if not missing:
            continue
        if key not in known:
            reason = UnscannedReason.CATEGORY_OUTSIDE_TABLE
        elif status_by_category.get(key) is CategoryState.PARTIAL:
            reason = UnscannedReason.PAGE_REFUSED
        else:
            reason = UnscannedReason.CATEGORY_SHORT_READ
        rows.append(UnscannedRow(
            category=key,
            census_count=entry.count,
            extracted_count=seen,
            unscanned=missing,
            reason=reason,
            category_ru=entry.name,
        ))

    # A category extraction returned that the census does not know at all
    # is the SAME overage: by the census, that category has zero elements
    # in the document.
    for category, seen in extracted_by_category.items():
        if category not in census_by_key and seen:
            errors.append({
                "code": CensusBalanceError.EXTRACTED_EXCEEDS_CENSUS.value,
                "category": category,
                "census_count": 0,
                "extracted_count": seen,
                "detail": (
                    f"извлечено {seen} элементов категории {category}, "
                    "которой нет в переписи документа"),
            })

    unscanned = sum(row.unscanned for row in rows)
    if not errors and census_total != extracted_total + unscanned:
        # The only remaining path here is an arithmetic mismatch in the
        # summary itself; it must be loud, not fudged.
        errors.append({
            "code": CensusBalanceError.CENSUS_TOTAL_MISMATCH.value,
            "category": "",
            "census_count": census_total,
            "extracted_count": extracted_total,
            "detail": (
                f"перепись {census_total} != извлечено {extracted_total} + "
                f"не читалось {unscanned}"),
        })

    rows.sort(key=lambda row: (-row.unscanned, row.category))
    return CensusBalance(
        present=True,
        census_total=census_total,
        extracted=extracted_total,
        unscanned=unscanned,
        categories_in_model=len(census_by_key),
        categories_scanned=len(set(census_by_key) & known),
        rows=tuple(rows),
        errors=tuple(errors),
    )


def census_from_mapping(counts: Mapping[str, int]) -> tuple[dict[str, Any], ...]:
    """Assemble a census payload from a counter (for fixtures/tests)."""
    return tuple(
        {"key": key, "name": "", "count": int(count)}
        for key, count in sorted(counts.items()))


__all__ = [
    "NO_CATEGORY_KEY",
    "TOP_N",
    "CensusBalance",
    "CensusBalanceError",
    "UnscannedReason",
    "UnscannedRow",
    "census_from_mapping",
    "reconcile_census",
]
