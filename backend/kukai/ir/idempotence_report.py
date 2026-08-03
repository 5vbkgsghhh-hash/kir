"""Immutable report and metric value objects for KIR idempotence evidence.

This is the serialization boundary for an A5 verdict.  It owns accounting
invariants only; rebuild orchestration, bridge IO, and durable recovery are
outside its authority.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from kukai.ir.decompile.fold import FIDELITY_CANON_VERSION
from kukai.ir.decompile.geometry_acceptance import FormAcceptanceState
from kukai.ir.idempotence_contract import Vec3

# ── per-op-kind comparison ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class KindComparison:
    """Symmetric match tally for one op-kind.

    ``expected``/``actual`` are the two multiset denominators.  Excluded counts
    make the adjusted metric leaf-specific (not a blanket op-name carve-out).
    """

    op_name: str
    expected: int
    actual: int
    matched: int
    excluded_expected: int = 0
    excluded_actual: int = 0
    excluded_matched: int = 0
    outside_universe: int = 0

    @property
    def missing(self) -> int:
        return self.expected - self.matched

    @property
    def extra(self) -> int:
        return self.actual - self.matched

    @property
    def expected_class(self) -> bool:
        """Backward-compatible flag: every expected leaf is excluded."""

        return self.expected > 0 and self.excluded_expected == self.expected

    @property
    def recall_pct(self) -> Optional[float]:
        return _ratio_pct(self.matched, self.expected)

    @property
    def precision_pct(self) -> Optional[float]:
        return _ratio_pct(self.matched, self.actual)

    @property
    def exact_pct(self) -> Optional[float]:
        """Legacy name retained as a recall alias."""

        return self.recall_pct

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_name": self.op_name,
            "expected": self.expected,
            "actual": self.actual,
            "matched": self.matched,
            "missing": self.missing,
            "extra": self.extra,
            "exact_pct": _round_pct(self.exact_pct),
            "recall_pct": _round_pct(self.recall_pct),
            "precision_pct": _round_pct(self.precision_pct),
            "excluded_expected": self.excluded_expected,
            "excluded_actual": self.excluded_actual,
            "expected_discrepancy_class": self.expected_class,
            # Ожидания, вынесенные из вселенной сравнения: НЕ входят ни в
            # `expected`, ни в `missing`, ни в один процент — публикуются
            # числом, чтобы вынос был виден, а не молчалив.
            "outside_universe": self.outside_universe,
        }


@dataclass(frozen=True, slots=True)
class MetricTotals:
    """Aggregate symmetric A5 metrics; a zero denominator is represented by N/A."""

    total_expected: int
    total_actual: int
    total_matched: int
    total_extra: int
    adjusted_expected: int
    adjusted_actual: int
    adjusted_matched: int
    raw_precision_pct: Optional[float]
    raw_recall_pct: Optional[float]
    adjusted_precision_pct: Optional[float]
    adjusted_recall_pct: Optional[float]


def _ratio_pct(numerator: int, denominator: int) -> Optional[float]:
    return None if denominator == 0 else numerator / denominator * 100.0


def _round_pct(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 3)


@dataclass(frozen=True, slots=True)
class IdempotenceReport:
    """The full A5 verdict.  ``to_dict`` is the serialization boundary."""

    doc_stamp: str
    delta_mm: Vec3
    # None means no rebuild/re-extract comparison was performed (dry-run or an
    # earlier typed failure).  Compile-gate success is not a geometry match.
    multiset_match: Optional[bool]
    expected_hash: str
    actual_hash: str
    total_expected: int
    total_matched: int
    raw_exact_pct: Optional[float]
    adjusted_exact_pct: Optional[float]
    per_kind: tuple[KindComparison, ...]
    discrepancies: tuple[dict[str, Any], ...]
    datums_skipped: int
    created_ids: tuple[str, ...]
    cleanup_ok: bool
    cleanup_detail: str
    total_actual: int = 0
    total_extra: int = 0
    raw_precision_pct: Optional[float] = None
    raw_recall_pct: Optional[float] = None
    adjusted_precision_pct: Optional[float] = None
    adjusted_recall_pct: Optional[float] = None
    atoms_excluded: int = 0
    #: Atom leaves which produced a typed DirectShape expectation.  They are
    #: not matches until the independent post-commit geometry read accepts.
    atoms_escrowed: int = 0
    atoms_form_accepted: int = 0
    atoms_form_rejected: int = 0
    atoms_form_inconclusive: int = 0
    form_expectations: tuple[dict[str, Any], ...] = ()
    form_acceptance: tuple[dict[str, Any], ...] = ()
    form_read_error: str = ""
    non_datum_total: int = 0
    #: Ожидания, вынесенные из вселенной сравнения ПО СТРОЕНИЮ: эффект опа
    #: семейства ``modify``, не породивший элемента в ``created_ids``.
    modify_outside_universe: int = 0
    modify_outside_universe_by_op: tuple[dict[str, Any], ...] = ()
    comparable_coverage_pct: Optional[float] = None
    canon_version: str = FIDELITY_CANON_VERSION
    dry_run: bool = True
    error: Optional[dict[str, Any]] = None
    #: Квитанции по ИЗОЛИРОВАННЫМ программам, которые Revit отверг. Каждая —
    #: одна хост-группа (радиус доказан построением), поэтому её отказ не
    #: фатален для прогона. Пустой кортеж = ни одна не отказала.
    isolated_failures: tuple[dict[str, Any], ...] = ()
    #: Отказы ОТДЕЛЬНЫХ опов внутри ЗАКОММИЧЕННЫХ чанков (29.07, задача
    #: №25). Класс, который был невидим: прогон №11 отчитался «Committed», а
    #: 113 линий разрезки витража из 122 отказали внутри успешных транзакций
    #: и попали в missing без единого слова о причине. Опы остаются в
    #: знаменателе — они были обещаны и не построены.
    op_refusals: tuple[dict[str, Any], ...] = ()
    #: Квитанции по ОБЫЧНЫМ чанкам, которые Revit отверг с ИЗВЕСТНЫМ исходом
    #: (`refused_without_commit`). Их опы остаются в знаменателе — они были
    #: обещаны и не построены. Неизвестный исход сюда не попадает: он валит
    #: прогон, а не пополняет этот список.
    chunk_failures: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        """Reject internally contradictory form accounting at construction.

        Dry runs and typed failures may legitimately leave pre-registered
        expectations pending.  A completed live comparison may not: every
        escrow candidate must have exactly one closed independent verdict.
        """

        form_counts = {
            "atoms_excluded": self.atoms_excluded,
            "atoms_escrowed": self.atoms_escrowed,
            "atoms_form_accepted": self.atoms_form_accepted,
            "atoms_form_rejected": self.atoms_form_rejected,
            "atoms_form_inconclusive": self.atoms_form_inconclusive,
        }
        for field_name, value in form_counts.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"IdempotenceReport.{field_name} must be non-negative int")
        verdict_total = (
            self.atoms_form_accepted
            + self.atoms_form_rejected
            + self.atoms_form_inconclusive
        )
        if verdict_total > self.atoms_escrowed:
            raise ValueError("form verdict count exceeds escrow candidates")
        if not isinstance(self.form_read_error, str):
            raise ValueError("IdempotenceReport.form_read_error must be string")
        if len(self.form_acceptance) != verdict_total:
            raise ValueError("form verdict rows disagree with form counters")
        if self.form_expectations and (
                len(self.form_expectations) != self.atoms_escrowed):
            raise ValueError(
                "form expectation rows disagree with escrow candidates")
        if self.error is None and (
                len(self.form_expectations) != self.atoms_escrowed):
            raise ValueError(
                "successful report lacks a form expectation per escrow atom")
        if self.form_read_error and (
                self.atoms_form_accepted or self.atoms_form_rejected):
            raise ValueError(
                "failed independent form read cannot yield a conclusive verdict")
        if self.form_acceptance:
            state_counts = Counter(
                row.get("state") if isinstance(row, Mapping) else None
                for row in self.form_acceptance
            )
            expected_counts = {
                FormAcceptanceState.ACCEPTED.value:
                    self.atoms_form_accepted,
                FormAcceptanceState.REJECTED.value:
                    self.atoms_form_rejected,
                FormAcceptanceState.INCONCLUSIVE.value:
                    self.atoms_form_inconclusive,
            }
            if any(key not in expected_counts for key in state_counts):
                raise ValueError("form verdict row has an unknown state")
            if any(state_counts[state] != count
                   for state, count in expected_counts.items()):
                raise ValueError("form verdict states disagree with form counters")
            for row in self.form_acceptance:
                digest = row.get("evidence_digest")
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(char not in "0123456789abcdef"
                               for char in digest)):
                    raise ValueError(
                        "form verdict evidence_digest must be SHA-256")
        if (not self.dry_run and self.error is None
                and self.multiset_match is not None
                and verdict_total != self.atoms_escrowed):
            raise ValueError(
                "completed live report has pending form expectations")

    def to_dict(self) -> dict[str, Any]:
        coverage_pct = _round_pct(self.comparable_coverage_pct)
        matched_end_to_end = self.total_matched + self.atoms_form_accepted
        form_pending = max(
            self.atoms_escrowed
            - self.atoms_form_accepted
            - self.atoms_form_rejected
            - self.atoms_form_inconclusive,
            0,
        )
        atom_summary = (
            f"{self.atoms_excluded} atoms skipped; "
            f"{self.atoms_escrowed} escrow candidates "
            f"({self.atoms_form_accepted} form accepted, "
            f"{self.atoms_form_rejected} rejected, "
            f"{self.atoms_form_inconclusive} inconclusive, "
            f"{form_pending} pending)"
        )
        if coverage_pct is None:
            coverage_summary = f"N/A (not measured); {atom_summary}"
        else:
            coverage_summary = (
                f"{matched_end_to_end}/{self.non_datum_total} "
                f"({coverage_pct}%); {atom_summary}")
        isolated_ops = sum(
            int(item.get("ops") or 0) for item in self.isolated_failures)
        chunk_ops = sum(
            int(item.get("ops") or 0) for item in self.chunk_failures)
        op_refused = len(self.op_refusals)
        if self.modify_outside_universe:
            named = ", ".join(f"{r['op_name']}×{r['count']}"
                              for r in self.modify_outside_universe_by_op)
            coverage_summary += (
                f"; {self.modify_outside_universe} modify-эффектов вне "
                f"вселенной created-ids ({named}) — не проверяемы по "
                f"построению, из знаменателя вынесены")
        if self.isolated_failures:
            coverage_summary += (
                f"; {len(self.isolated_failures)} изолированных программ "
                f"отвергнуты Revit ({isolated_ops} опов не построено)")
        if self.op_refusals:
            by_name = Counter(
                str(row.get("op_name") or "?") for row in self.op_refusals)
            named = ", ".join(f"{name}×{count}"
                              for name, count in sorted(by_name.items()))
            coverage_summary += (
                f"; {op_refused} опов отвергнуты ВНУТРИ закоммиченных чанков "
                f"({named}) — опы остались в знаменателе")
        if self.chunk_failures:
            coverage_summary += (
                f"; {len(self.chunk_failures)} чанков отвергнуты Revit "
                f"({chunk_ops} опов не построено) — доля посчитана ПРИ них, "
                f"опы остались в знаменателе")
        d: dict[str, Any] = {
            "doc_stamp": self.doc_stamp,
            "delta_mm": list(self.delta_mm),
            "multiset_match": self.multiset_match,
            "comparison_performed": self.multiset_match is not None,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "total_expected": self.total_expected,
            "total_actual": self.total_actual,
            "total_matched": self.total_matched,
            "total_extra": self.total_extra,
            # Backward-compatible exact fields are recall aliases.
            "raw_exact_pct": _round_pct(self.raw_exact_pct),
            "adjusted_exact_pct": _round_pct(self.adjusted_exact_pct),
            "raw_precision_pct": _round_pct(self.raw_precision_pct),
            "raw_recall_pct": _round_pct(self.raw_recall_pct),
            "adjusted_precision_pct": _round_pct(self.adjusted_precision_pct),
            "adjusted_recall_pct": _round_pct(self.adjusted_recall_pct),
            "canon_version": self.canon_version,
            "per_kind": [k.to_dict() for k in self.per_kind],
            # Срез изолированных идёт В ТОТ ЖЕ список расхождений: читатель
            # отчёта не обязан помнить про второе место, где живёт правда о
            # непостроенном.
            "discrepancies": list(self.discrepancies)
            + list(self.isolated_failures)
            + list(self.chunk_failures)
            + list(self.op_refusals),
            "datums_skipped": self.datums_skipped,
            "atoms_excluded": self.atoms_excluded,
            "atoms_escrowed": self.atoms_escrowed,
            "atoms_form_accepted": self.atoms_form_accepted,
            "atoms_form_rejected": self.atoms_form_rejected,
            "atoms_form_inconclusive": self.atoms_form_inconclusive,
            "atoms_form_pending": form_pending,
            "form_expectations": list(self.form_expectations),
            "form_acceptance": list(self.form_acceptance),
            "form_read_error": self.form_read_error or None,
            "non_datum_total": self.non_datum_total,
            "modify_outside_universe": self.modify_outside_universe,
            "modify_outside_universe_by_op": [
                dict(row) for row in self.modify_outside_universe_by_op],
            "comparable_coverage_pct": coverage_pct,
            "comparable_coverage": {
                "matched_end_to_end": (
                    matched_end_to_end if coverage_pct is not None else None),
                "all_non_datum": self.non_datum_total,
                "pct": coverage_pct,
                # Legacy name: before Tier-G materialization every atom was
                # held in not-reproduced escrow.  Keep it as a skip alias.
                "atoms_escrow": self.atoms_excluded,
                "atoms_skipped": self.atoms_excluded,
                "atoms_escrowed_candidates": self.atoms_escrowed,
                "atoms_form_accepted": self.atoms_form_accepted,
                "atoms_form_rejected": self.atoms_form_rejected,
                "atoms_form_inconclusive": self.atoms_form_inconclusive,
                "atoms_form_pending": form_pending,
                # Опы отвергнутых изолированных программ ОСТАЮТСЯ в
                # знаменателе: они были обещаны и не построены. Вынести их
                # значило бы поднять процент за счёт того, чего нет.
                "isolated_refused_ops": isolated_ops,
                # То же правило для обычных чанков: опы отвергнутого чанка
                # были обещаны и не построены, поэтому остаются в
                # знаменателе. Вынести их значило бы поднять процент ровно
                # на том, чего в модели нет.
                "chunk_refused_ops": chunk_ops,
                # То же правило: оп отвергнут внутри УСПЕШНОГО чанка, но он
                # был обещан и не построен — из знаменателя не выносится.
                "op_refused_ops": op_refused,
            },
            "isolated_failed": len(self.isolated_failures),
            "isolated_failed_ops": isolated_ops,
            "isolated_failures": list(self.isolated_failures),
            "op_refused": op_refused,
            "op_refusals": list(self.op_refusals),
            "chunk_failed": len(self.chunk_failures),
            "chunk_failed_ops": chunk_ops,
            "chunk_failures": list(self.chunk_failures),
            "comparable_coverage_summary": coverage_summary,
            "created_ids_count": len(self.created_ids),
            "cleanup_ok": self.cleanup_ok,
            "cleanup_detail": self.cleanup_detail,
            "dry_run": self.dry_run,
        }
        if self.error is not None:
            d["error"] = self.error
        return d
