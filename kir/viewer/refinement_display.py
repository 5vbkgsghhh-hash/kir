"""The remainder of the translation and the decisions taken, as a RECORD OF
DISPLAY — and nothing beyond that.

🔴 WHAT IS CLOSED HERE. The owner's word: "explicitly show untranslated
remainders and the decisions taken." The numbers for this have existed since
07.09.2026 (`kir/refine/deviation.py`,
`kir/project_refinement.refine_after_source_change`), but there is no display
for them: the standalone-display artifact `/3` carries surfaces, proxies, and
clash findings — and not a single line about what the translation DID NOT
TRANSLATE.

🔴 THE THREE SETS ARE COUNTED BEFORE ADDRESS TRANSLATION, AND THIS IS NOT A
DETAIL. Their sum equals ALL the outputs of the detailed instance — that is
exactly the property they were set up for. But part of the outputs live in a
FOREIGN instance (types sit in the type library) and have no address in the
scene. If counted after translation, the sum would silently stop converging,
and "the output disappeared" would be indistinguishable from "the output is
not shown". That is why `counts` is taken from the SOURCE report, while
untranslated addresses are named by the number `unaddressed` and a line in
`analysis_limits`.

🔴 WHAT THIS RECORD DOES NOT ASSERT. Role and losses remain AUTHORED
assertions (`kir/project_refinement.py` prints them under
`roles_and_losses: authored_assertions`); the deviation is a number exactly
where a measure is named, and an absence where none is named. The choice on
the question is made by the HUMAN: the display prints the options and the
argument, but does not choose and does not hint.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

#: The consumer's fourth capability. Like the three before it — a name with
#: a date in the version: a consumer that did not declare it gets no records
#: at all, rather than getting them "silently unshown".
REFINEMENT_CAPABILITY = "display_refinement/1"
REFINEMENT_RECORD_SCHEMA = "kir-refinement-display/1"

#: What the record asserts and what it does not assert. Checked for EXACT
#: equality both here and in the JS mirror — like surfaces, proxies, and
#: findings.
REFINEMENT_CLAIMS = MappingProxyType({
    "scope": "authored_section_after_a_source_change",
    "source": "kir_project_refinement_report",
    "sets": "disjoint_and_cover_every_output_of_the_detailed_instance",
    "roles_and_losses": "authored_assertions",
    "residue_inventory": "not_proven_exhaustive",
    "deviation": "number_only_where_the_measure_is_named",
    "decision_authority": "human_answers_the_questions",
    "native_execution": "not_run",
    "units": "mm",
})

_REFINEMENT_FIELDS = ("schema", "source_display_id", "revision_before", "revision_after",
                      "recomputed", "preserved", "needs_decision", "counts",
                      "residue", "deviation", "decisions_digest")
_COUNT_FIELDS = ("recomputed", "preserved", "needs_decision", "total", "unaddressed")
_RESIDUE_FIELDS = ("address", "what", "count", "volume_mm3")
_DEVIATION_FIELDS = ("measure", "value", "unit", "method")
_QUESTION_FIELDS = ("question_id", "address", "choices", "why")

#: Three sets — a closed list of names, not "whichever came in".
SET_NAMES = ("recomputed", "preserved", "needs_decision")


class RefinementDisplayRefusal(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _text(value, name, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RefinementDisplayRefusal("invalid_refinement", f"{name}: ожидалась непустая строка")
    return value


def _count(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RefinementDisplayRefusal("invalid_refinement", f"{name}: ожидалось целое ≥ 0")
    return value


def _number(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RefinementDisplayRefusal("invalid_refinement", f"{name}: ожидалось число или null")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise RefinementDisplayRefusal("invalid_refinement", f"{name}: неконечное число")
    return round(result, 6)


def _value(raw, name):
    """The deviation value: a number, a list of numbers, or `null`. Nothing
    else is possible."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [_number(item, f"{name}[]") for item in raw]
    return _number(raw, name)


def _strings(raw, name):
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise RefinementDisplayRefusal("invalid_refinement", f"{name}: ожидался список строк")
    return [_text(item, f"{name}[]") for item in raw]


def display_refinement(report, known_display_ids: Sequence[str], *,
                       address_map: Mapping[str, str] | None = None) -> dict:
    """The `refine_after_source_change` report -> display records for THIS
    scene.

    Accepts both a typed `RefinementReport` and its `to_dict()`: the
    translator has one subject but two legitimate inputs — from the product
    and from an already-saved artifact.

    Address translation uses the same `address_map` from materialization as
    the clash findings do: the analysis addresses outputs by `output_id`,
    the display by the scene's display-id. An address with nothing to
    translate it into is NOT SILENTLY DROPPED: it goes out to
    `analysis_limits` by name and is counted in `counts.unaddressed`.
    """
    data = report.to_dict() if hasattr(report, "to_dict") else report
    if not isinstance(data, Mapping):
        raise RefinementDisplayRefusal("invalid_refinement",
                                       "ожидался RefinementReport или его отображение")
    known = set(known_display_ids)
    addresses = dict(address_map or {})
    limits = _strings(data.get("analysis_limits") or (), "analysis_limits")
    unaddressed: list[str] = []

    def shown(output_id, name):
        """`output_id` -> display-id; what is not in the scene is named, not
        forgotten."""
        value = _text(output_id, name)
        display = addresses.get(value, value)
        if display not in known:
            unaddressed.append(value)
            return None
        return display

    sets: dict[str, list[str]] = {}
    counts = {"total": 0, "unaddressed": 0}
    for name in SET_NAMES:
        raw = data.get(name)
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise RefinementDisplayRefusal("invalid_refinement",
                                           f"{name}: ожидался список адресов")
        # 🔴 THE COUNT IS TAKEN BEFORE TRANSLATION (see the module header):
        # the property "the sum of the three sets = all outputs" belongs to
        # the REPORT, not to the scene.
        counts[name] = len(raw)
        counts["total"] += len(raw)
        sets[name] = [row for row in (shown(item, f"{name}[]") for item in raw)
                      if row is not None]
    overlap = (set(sets["recomputed"]) & set(sets["preserved"])) | \
              (set(sets["recomputed"]) & set(sets["needs_decision"])) | \
              (set(sets["preserved"]) & set(sets["needs_decision"]))
    if overlap:
        raise RefinementDisplayRefusal(
            "invalid_refinement",
            "три множества обязаны не пересекаться; общие адреса: "
            + ", ".join(sorted(overlap)))

    residue = []
    raw_residue = data.get("residue") or ()
    if not isinstance(raw_residue, Sequence) or isinstance(raw_residue, (str, bytes)):
        raise RefinementDisplayRefusal("invalid_refinement", "residue: ожидался список")
    for row in raw_residue:
        if not isinstance(row, Mapping):
            raise RefinementDisplayRefusal("invalid_refinement", "строка остатка: ожидалось отображение")
        raw_address = _text(row.get("address"), "residue.address")
        residue.append({"address": addresses.get(raw_address, raw_address),
                        "what": _text(row.get("what"), "residue.what"),
                        "count": _count(row.get("count"), "residue.count"),
                        "volume_mm3": _number(row.get("volume_mm3"), "residue.volume_mm3")})
    # 🔴 THE REMAINDER IS ADDRESSED BY THE SOURCE, NOT BY THE SCENE, AND SO
    # IT IS NOT FILTERED. The address of an untranslated piece is the
    # address of the SOURCE part (the concept volume), which may not exist
    # at all in the detail scene. Dropping a line because its source is not
    # drawn would mean hiding exactly what the record was set up for.

    raw_deviation = data.get("deviation")
    if raw_deviation is not None and not isinstance(raw_deviation, Mapping):
        raise RefinementDisplayRefusal("invalid_refinement", "deviation: ожидалось отображение")
    raw_deviation = raw_deviation or {}
    deviation = {"measure": _text(raw_deviation.get("measure"), "deviation.measure", optional=True),
                 "value": _value(raw_deviation.get("value"), "deviation.value"),
                 "unit": _text(raw_deviation.get("unit"), "deviation.unit", optional=True),
                 "method": _text(raw_deviation.get("method"), "deviation.method", optional=True)}
    if deviation["value"] is not None and deviation["measure"] is None:
        raise RefinementDisplayRefusal("invalid_refinement",
                                       "отклонение с числом обязано назвать меру")
    # 🔴 A NUMBER WITHOUT A NAMED METHOD IS NOT A DEFECT, BUT IT IS NOT
    # SILENCE EITHER. Today the report names the measure
    # (`plan_area_delta_mm2`) and the unit, but not the method of obtaining
    # it. The reader must see this distinction: otherwise tomorrow's
    # replacement of the area with a mesh estimate (which converges FROM
    # BELOW) will travel to them in the same field and be read as "equal".
    if deviation["value"] is not None and deviation["method"] is None:
        limits.append(f"метод меры {deviation['measure']} не назван отчётом: "
                      "число читать как «мера», а не как «способ»")

    questions = []
    raw_questions = data.get("questions") or ()
    if not isinstance(raw_questions, Sequence) or isinstance(raw_questions, (str, bytes)):
        raise RefinementDisplayRefusal("invalid_refinement", "questions: ожидался список")
    seen = set()
    for row in raw_questions:
        item = row.to_dict() if hasattr(row, "to_dict") else row
        if not isinstance(item, Mapping):
            raise RefinementDisplayRefusal("invalid_refinement", "вопрос: ожидалось отображение")
        question_id = _text(item.get("question_id"), "question.question_id")
        if question_id in seen:
            raise RefinementDisplayRefusal("invalid_refinement", f"повтор question_id: {question_id}")
        seen.add(question_id)
        raw_address = _text(item.get("address"), "question.address")
        choices = _strings(item.get("choices") or (), "question.choices")
        if not choices:
            raise RefinementDisplayRefusal("invalid_refinement",
                                           "вопрос без вариантов — не вопрос, а сообщение")
        questions.append({"question_id": question_id,
                          "address": addresses.get(raw_address, raw_address),
                          "choices": choices,
                          "why": _text(item.get("why"), "question.why")})

    counts["unaddressed"] = len(unaddressed)
    if unaddressed:
        limits.append("не показаны выходы, не адресуемые этой сценой ("
                      + str(len(unaddressed)) + "): " + ", ".join(sorted(set(unaddressed))))

    raw_source = _text(data.get("source_output_id"), "source_output_id")
    source_display_id = addresses.get(raw_source, raw_source)
    # 🔴 THE SOURCE ADDRESS IS, MORE OFTEN THAN NOT, NOT AN ADDRESS OF THIS
    # SCENE, and this cannot be left unsaid: the source part lives in the
    # CONCEPT revision, while the scene shows the detail. A reader who takes
    # it for a display-id will go looking in the scene for something that is
    # not there.
    if source_display_id not in known:
        limits.append("адрес исходной части не показан этой сценой: " + source_display_id)

    record = {"schema": REFINEMENT_RECORD_SCHEMA,
              "source_display_id": source_display_id,
              "revision_before": _text(data.get("revision_before"), "revision_before"),
              "revision_after": _text(data.get("revision_after"), "revision_after", optional=True),
              "recomputed": sets["recomputed"], "preserved": sets["preserved"],
              "needs_decision": sets["needs_decision"],
              "counts": {name: _count(counts[name], f"counts.{name}") for name in _COUNT_FIELDS},
              "residue": residue, "deviation": deviation,
              "decisions_digest": _text(data.get("decisions_digest"), "decisions_digest")}
    if sorted(record) != sorted(_REFINEMENT_FIELDS):
        raise RefinementDisplayRefusal("invalid_refinement", "состав полей записи изменился")
    return {"refinement": record, "questions": questions, "analysis_limits": limits}


__all__ = ["REFINEMENT_CAPABILITY", "REFINEMENT_RECORD_SCHEMA", "REFINEMENT_CLAIMS",
           "SET_NAMES", "RefinementDisplayRefusal", "display_refinement"]
