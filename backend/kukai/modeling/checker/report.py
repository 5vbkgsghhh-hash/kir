"""Render a CheckReport to human text and to machine JSON (design §11.5).

Both functions are PURE — they return strings; the caller prints or writes them. The
JSON view delegates to pydantic so it can never drift from the Violation/CheckReport
contract; the text view is the terminal-friendly, severity-grouped rendering that a
human (or a fix-loop log) reads."""
from __future__ import annotations

from kukai.modeling.checker.spatial_model import (
    CheckReport,
    Severity,
    Violation,
)

# Fixed render order: most severe first.
_GROUP_ORDER: list[tuple[str, Severity]] = [
    ("BLOCKING", Severity.BLOCKING),
    ("WARNING", Severity.WARNING),
    ("INFO", Severity.INFO),
]


def _bucket(report: CheckReport, severity: Severity) -> list[Violation]:
    if severity is Severity.BLOCKING:
        return report.blocking
    if severity is Severity.WARNING:
        return report.warnings
    return report.info


def _format_violation(v: Violation) -> str:
    """One violation as a two-line block: header + (optional) refs/fix-hint detail."""
    head = f"  [{v.severity.value.upper()}] {v.rule_id}: {v.msg}"
    detail_bits: list[str] = []
    if v.refs:
        detail_bits.append(f"refs={', '.join(v.refs)}")
    if v.fix_hint:
        detail_bits.append(f"fix: {v.fix_hint}")
    if detail_bits:
        return head + "\n      " + "  ".join(detail_bits)
    return head


def format_text(report: CheckReport) -> str:
    """Human-readable, severity-grouped rendering of a CheckReport (BLOCKING → WARNING → INFO).

    v2 reports (verdict set) render the three-valued verdict and a COVERAGE section —
    which rules actually evaluated real subjects, and why the rest could not — so a
    vacuous check can never be mistaken for a clean pass."""
    if report.verdict is not None:
        verdict = report.verdict.value.upper().replace("_", "-")
    else:
        verdict = "PASS" if report.passed else "FAIL"
    n_block = len(report.blocking)
    n_warn = len(report.warnings)
    n_info = len(report.info)

    lines: list[str] = [
        f"=== Building correctness check: {verdict} ===",
        f"{n_block} blocking, {n_warn} warning, {n_info} info",
    ]
    for label, severity in _GROUP_ORDER:
        bucket = _bucket(report, severity)
        if not bucket:
            continue
        lines.append("")
        lines.append(f"{label} ({len(bucket)}):")
        for v in bucket:
            lines.append(_format_violation(v))

    cov = report.coverage
    if cov is not None:
        lines.append("")
        if cov.profile_name:
            # The stage stands ABOVE the counts, never beside them: "18 of 20 rules"
            # means nothing until the reader knows which stage dropped the other two.
            lines.append(f"PROFILE: {cov.profile_name}")
        lines.append(f"COVERAGE: {cov.rules_evaluated} rules evaluated, "
                      f"{cov.rules_not_evaluated} not evaluated; "
                      f"classification {cov.classification_coverage:.0%}, "
                      f"measured rooms {cov.measured_room_ratio:.0%}")
        if cov.mandatory_not_evaluated:
            lines.append("  MANDATORY NOT EVALUATED: "
                          + ", ".join(cov.mandatory_not_evaluated))
        for o in cov.outcomes:
            if o.status.value == "not_evaluated":
                lines.append(f"  [not-evaluated] {o.rule_id}: {o.reason}")
            elif o.excluded_subjects:
                # EVALUATED with subjects withheld is a NARROWER claim than EVALUATED,
                # and a reader who cannot see the difference will quote the wider one.
                lines.append(f"  [partial] {o.rule_id}: examined {o.n_subjects}, "
                              f"withheld {o.excluded_subjects} ({o.excluded_reason})")
        for note in cov.notes:
            lines.append(f"  note: {note}")
    return "\n".join(lines)


def to_json(report: CheckReport) -> str:
    """Stable machine-readable JSON of a CheckReport (delegates to the pydantic contract).

    Round-trips: CheckReport.model_validate_json(to_json(report)) == report. The enum
    severities serialize to their lowercase string values ('blocking'/'warning'/'info')."""
    return report.model_dump_json(indent=2)
