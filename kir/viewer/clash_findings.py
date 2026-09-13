"""The findings of the clash analysis as a DISPLAY RECORD — and nothing more
than that.

🔴 WHAT IS BEING CLOSED HERE, BY THE NUMBERS. Reconnaissance on 06.09.2026:
in the frontend the word `clash` appears 5 times, and ALL FIVE are negations
(`clash_eligibility: 'none'`, the caption «Заявленная clash-оболочка, не
поверхность BIM»); `kir/viewer/scene.py`, in `BLIND_SPOTS`, states outright
«клеши: пересечения тел здесь не ищутся и не показываются». A carrier — two
entities plus a number plus a status — exists in the tree:
`kir/viewer/advice.py`, schema `kir-viewer-advice/1` — but it has NO
consumer: the declared `/api/viewer/advice` does not exist in the tree, the
client lives in KUKAI. This module takes the content FROM THERE and places
it into the existing standalone-display capability mechanism, without
starting a second dictionary.

🔴 WHAT THIS RECORD DOES NOT CLAIM. It is not BIM coverage, not permission
to edit the model, and not completeness of the search: `analysis_limits`
travels ALONGSIDE the findings in the same record, because a list of
findings without a list of limits reads as "there's nothing else," and
that would be untrue. Display without limits is worse than no display at
all: it looks complete.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

#: The consumer's third capability. Like the previous two — a name with a
#: version cutoff, not a flag: a consumer that hasn't declared it gets no
#: findings at all, rather than getting them "silently unshown."
CLASH_CAPABILITY = "display_clash_findings/1"
CLASH_FINDING_SCHEMA = "kir-clash-finding/1"

#: What the finding record claims and what it does not. It is checked for
#: EXACT equality both here and in the JS mirror — same as with surfaces
#: and proxies.
CLASH_CLAIMS = MappingProxyType({
    "scope": "authored_body_pair_analysis",
    "source": "kir_clash_exact_or_hull_phase",
    "bim_coverage": "not_claimed",
    "search_completeness": "declared_in_analysis_limits",
    "repair_authority": "not_granted",
    "native_execution": "not_run",
    "units": "mm",
})

#: The finding's axes. Both are closed: `status` — provenness, `relation`
#: — the relation between bodies. `refuted` exists only since 06.09.2026
#: (the exact phase) and means "the shells intersected, the BODIES did
#: not."
#: `clearance_violated` was introduced on 07.09.2026 from an owner
#: finding: a pair may NOT intersect and still VIOLATE the clearance
#: requirement. Without this kind, such a finding would arrive on screen
#: as `refuted` — that is, as CLEARED.
#: `clearance_unverified` was introduced on 07.09.2026 from finding
#: review6 В-1: the requirement is DECLARED, but the exact phase did not
#: judge it (no body, no kernel, budget ran out). Showing such a pair as
#: `possible` would mean staying silent about the requirement, and as
#: `refuted` would mean declaring an unverified thing cleared. Both are
#: worse than a separate kind.
FINDING_STATUSES = ("confirmed", "possible", "refuted", "clearance_violated",
                    "clearance_unverified")
FINDING_RELATIONS = ("intersect", "contained", "clear")
#: What the side's shell is grounded in. `brep` is the only kind for
#: which the exact phase is possible at all.
HULL_SOURCES = ("brep", "preview", "bbox", "none")

_FINDING_FIELDS = ("finding_id", "display_id_a", "display_id_b", "status",
                   "relation", "depth_mm", "overlap_volume_mm3", "gap_mm",
                   "hull_source_a", "hull_source_b", "refusal_ru",
                   "required_clearance_mm", "deficit_mm", "clearance_source")


class ClashDisplayRefusal(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _number(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ClashDisplayRefusal("invalid_finding", f"{name}: ожидалось число или null")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ClashDisplayRefusal("invalid_finding", f"{name}: неконечное число")
    return round(result, 6)


def _text(value, name, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ClashDisplayRefusal("invalid_finding", f"{name}: ожидалась непустая строка")
    return value


def display_clash_findings(report: Mapping, known_display_ids: Sequence[str], *,
                           address_map: Mapping[str, str] | None = None) -> dict:
    """Translate the analysis report into display records addressed to
    THIS scene.

    🔴 TWO ADDRESS SPACES, AND THIS IS A MEASUREMENT, NOT A GUESS
    (06.09.2026, acceptance of record 6). The analysis addresses bodies by
    the project's `output_id`, the display addresses them by the scene's
    display-id; without the translation, `clash_findings` came out at
    **0 of 5** with five real findings present. `address_map` is built by
    the CALLER from materialization (which knows the "project output ↔
    scene record" pair), not by string concatenation: concatenation would
    match today and would drift silently on the very first day the scene
    address stops being derivable from `output_id`.

    A finding whose side cannot be translated is not silently dropped: it
    goes into `analysis_limits` by name. A silent drop here would mean "we
    looked and found nothing" in a case where we simply couldn't show it.
    """
    if not isinstance(report, Mapping):
        raise ClashDisplayRefusal("invalid_report", "ожидался отчёт анализа как отображение")
    known = set(known_display_ids)
    addresses = dict(address_map or {})
    hull_sources = report.get("hull_source") or report.get("hull_sources") or {}
    if not isinstance(hull_sources, Mapping):
        raise ClashDisplayRefusal("invalid_report", "hull_source: ожидалось отображение")

    def address(value, name):
        """`output_id` -> display-id. An address already translated
        passes through as is."""
        if not isinstance(value, str) or not value.strip():
            raise ClashDisplayRefusal("invalid_finding", f"{name}: ожидалась непустая строка")
        return addresses.get(value, value)

    def hull_of(output_id):
        """The shell kind is taken from the REPORT and reduced to a
        closed list.

        The analysis writes the reason into the value itself
        (`none:brep_unreadable:X`); the display needs a kind, and the
        reason has already gone into `analysis_limits`.
        """
        raw = hull_sources.get(output_id)
        if raw is None:
            return "none"
        head = str(raw).split(":", 1)[0]
        return head if head in HULL_SOURCES else "none"
    findings, limits, unaddressed = [], [], []
    raw_limits = report.get("analysis_limits") or ()
    if not isinstance(raw_limits, Sequence) or isinstance(raw_limits, (str, bytes)):
        raise ClashDisplayRefusal("invalid_report", "analysis_limits: ожидался список строк")
    for item in raw_limits:
        limits.append(_text(item, "analysis_limits[]"))
    rows = report.get("findings") or ()
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ClashDisplayRefusal("invalid_report", "findings: ожидался список")
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ClashDisplayRefusal("invalid_finding", "находка должна быть отображением")
        # Both the analysis names (`a_output_id`) and the display names
        # (`display_id_a`) are accepted: there is one translator, and it
        # has two kinds of input — from the report and from an
        # already-built record (built by tests and by external consumers).
        raw_a = row.get("display_id_a", row.get("a_output_id", row.get("a")))
        raw_b = row.get("display_id_b", row.get("b_output_id", row.get("b")))
        source_a = row.get("a_output_id", row.get("a", raw_a))
        source_b = row.get("b_output_id", row.get("b", raw_b))
        record = {
            "finding_id": _text(row.get("finding_id"), "finding_id"),
            "display_id_a": address(raw_a, "display_id_a"),
            "display_id_b": address(raw_b, "display_id_b"),
            "status": _text(row.get("status"), "status"),
            "relation": _text(row.get("relation"), "relation", optional=True),
            "depth_mm": _number(row.get("depth_mm"), "depth_mm"),
            "overlap_volume_mm3": _number(row.get("overlap_volume_mm3"), "overlap_volume_mm3"),
            "gap_mm": _number(row.get("gap_mm"), "gap_mm"),
            "hull_source_a": _text(row.get("hull_source_a") or hull_of(source_a), "hull_source_a"),
            "hull_source_b": _text(row.get("hull_source_b") or hull_of(source_b), "hull_source_b"),
            "refusal_ru": _text(row.get("refusal_ru"), "refusal_ru", optional=True),
            # The clearance requirement travels ALONGSIDE the number:
            # `gap_mm` without it does not distinguish "met" from "we
            # didn't ask."
            "required_clearance_mm": _number(row.get("required_clearance_mm"),
                                             "required_clearance_mm"),
            "deficit_mm": _number(row.get("deficit_mm"), "deficit_mm"),
            "clearance_source": _text(row.get("clearance_source"), "clearance_source",
                                      optional=True),
        }
        if record["status"] in ("clearance_violated", "clearance_unverified"):
            if record["required_clearance_mm"] is None or record["clearance_source"] is None:
                raise ClashDisplayRefusal("invalid_finding", "зазор обязан назвать требование и его носитель")
            if (record["status"] == "clearance_unverified" and record["gap_mm"] is None
                    and record["deficit_mm"] is None):
                # Unknown is not a zero measurement. Reuse the existing
                # per-finding refusal field and the analysis's addressed limit.
                if record["refusal_ru"] is None:
                    prefix = record["finding_id"] + ":"
                    record["refusal_ru"] = next((item for item in limits if item.startswith(prefix)), None)
                if record["refusal_ru"] is None:
                    raise ClashDisplayRefusal("invalid_finding", "неизмеренный зазор обязан назвать причину")
            elif record["gap_mm"] is None or record["deficit_mm"] is None:
                raise ClashDisplayRefusal(
                    "invalid_finding", "измеренный зазор обязан назвать и расстояние, и дефицит")
        if record["status"] not in FINDING_STATUSES:
            raise ClashDisplayRefusal("invalid_finding", f"status вне закрытого списка: {record['status']}")
        if record["relation"] is not None and record["relation"] not in FINDING_RELATIONS:
            raise ClashDisplayRefusal("invalid_finding", f"relation вне закрытого списка: {record['relation']}")
        for side in ("hull_source_a", "hull_source_b"):
            if record[side] not in HULL_SOURCES:
                raise ClashDisplayRefusal("invalid_finding", f"{side} вне закрытого списка: {record[side]}")
        if record["finding_id"] in seen:
            raise ClashDisplayRefusal("invalid_finding", f"повтор finding_id: {record['finding_id']}")
        seen.add(record["finding_id"])
        missing = [record[key] for key in ("display_id_a", "display_id_b")
                   if record[key] not in known]
        if missing:
            unaddressed.append(record["finding_id"])
            continue
        findings.append(record)
    if unaddressed:
        limits.append("не показаны находки, чьи стороны не адресуются этой сценой: "
                      + ", ".join(sorted(unaddressed)))
    return {"findings": findings, "analysis_limits": limits}


__all__ = ["CLASH_CAPABILITY", "CLASH_FINDING_SCHEMA", "CLASH_CLAIMS",
           "FINDING_STATUSES", "FINDING_RELATIONS", "HULL_SOURCES",
           "ClashDisplayRefusal", "display_clash_findings"]
