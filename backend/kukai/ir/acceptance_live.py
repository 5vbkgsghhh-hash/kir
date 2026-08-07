"""Strict live adapter for KIR's independent L2 acceptance census.

The pure judge lives in :mod:`kukai.ir.acceptance`.  This module owns only the
independent Revit read needed to feed that judge:

* the requested category universe is derived from the immutable expectation;
* the read is bound to one exact document and one random execution id;
* the C# walks the model again and returns category x level counts only;
* the parser rejects missing, duplicated, widened, or mis-bound evidence.

No builder receipt is accepted here.  The same registered predicate and run id
are executed in two distinct ``before``/``after`` phases; only the fresh
returned census becomes source truth.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from kukai.ir.acceptance import (
    Expectation,
    ScopeCensus,
    expectation_categories,
    expectation_digest,
)
from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.document_guard import bind_read_to_document
from kukai.ir.emit_utils import cs_string_literal
from kukai.ir.revit_read_helpers import ELEMENT_LEVEL_HELPERS_CS


SCOPE_CENSUS_SCHEMA_VERSION = "kir-scope-census/1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_CATEGORY_RE = re.compile(r"(?:OST_[A-Za-z0-9_]+|DirectShape)\Z")
_PHASES = frozenset({"before", "after"})
_MAX_COUNT = 0x7FFFFFFFFFFFFFFF
_MAX_LEVEL_NAME = 512


class ScopeCensusError(ValueError):
    """A live acceptance request or response violates its closed contract."""


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ScopeCensusError(f"{field_name} must be lowercase SHA-256")
    return value


def _run_id(value: Any) -> str:
    if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
        raise ScopeCensusError("run_id must be 32 lowercase hex chars")
    return value


def _phase(value: Any) -> str:
    if value not in _PHASES:
        raise ScopeCensusError(
            f"scope census phase must be one of {sorted(_PHASES)}")
    return str(value)


def _category(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _CATEGORY_RE.fullmatch(value) is None:
        raise ScopeCensusError(
            f"{field_name} must be an OST_* key or DirectShape")
    return value


def _count(value: Any, field_name: str, *, positive: bool = False) -> int:
    lower = 1 if positive else 0
    if (isinstance(value, bool) or not isinstance(value, int)
            or not lower <= value <= _MAX_COUNT):
        qualifier = "positive" if positive else "non-negative"
        raise ScopeCensusError(f"{field_name} must be a {qualifier} int64")
    return value


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ScopeCensusError(
            f"scope census is not canonical JSON: {exc}") from exc


@dataclass(frozen=True, slots=True, order=True)
class ScopeCensusRow:
    """One non-zero canonical category x level cell."""

    category: str
    level_name: str
    count: int

    def __post_init__(self) -> None:
        _category(self.category, "scope row category")
        if (not isinstance(self.level_name, str)
                or len(self.level_name) > _MAX_LEVEL_NAME
                or self.level_name != self.level_name.strip()):
            raise ScopeCensusError(
                "scope row level_name must be a trimmed bounded string")
        _count(self.count, "scope row count", positive=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "level_name": self.level_name,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class ScopeCensusObservation:
    """A content-addressed result of one independent live model read."""

    run_id: str
    phase: str
    expectation_digest: str
    document_digest: str
    categories: tuple[str, ...]
    rows: tuple[ScopeCensusRow, ...]
    total: int

    def __post_init__(self) -> None:
        _run_id(self.run_id)
        _phase(self.phase)
        _sha256(self.expectation_digest, "expectation_digest")
        _sha256(self.document_digest, "document_digest")
        if not isinstance(self.categories, tuple) or not self.categories:
            raise ScopeCensusError(
                "scope census categories must be a non-empty tuple")
        for index, category in enumerate(self.categories):
            _category(category, f"categories[{index}]")
        if self.categories != tuple(sorted(set(self.categories))):
            raise ScopeCensusError(
                "scope census categories must be unique and sorted")
        if (not isinstance(self.rows, tuple)
                or any(not isinstance(row, ScopeCensusRow)
                       for row in self.rows)):
            raise ScopeCensusError(
                "scope census rows must be typed immutable rows")
        if self.rows != tuple(sorted(set(self.rows))):
            raise ScopeCensusError(
                "scope census rows must be unique and sorted")
        cell_keys = tuple((row.category, row.level_name) for row in self.rows)
        if len(cell_keys) != len(set(cell_keys)):
            raise ScopeCensusError(
                "scope census contains duplicate category x level cells")
        wanted = set(self.categories)
        if any(row.category not in wanted for row in self.rows):
            raise ScopeCensusError(
                "scope census returned a category outside registered scope")
        declared = _count(self.total, "scope census total")
        if sum(row.count for row in self.rows) != declared:
            raise ScopeCensusError(
                "scope census total disagrees with row counts")

    @property
    def census(self) -> dict[tuple[str, str], int]:
        return {
            (row.category, row.level_name): row.count
            for row in self.rows
        }

    @property
    def observation_digest(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCOPE_CENSUS_SCHEMA_VERSION,
            "run_id": self.run_id,
            "phase": self.phase,
            "expectation_digest": self.expectation_digest,
            "document_digest": self.document_digest,
            "categories": list(self.categories),
            "rows": [row.to_dict() for row in self.rows],
            "total": self.total,
        }


def _registered_categories(expectation: Expectation) -> tuple[str, ...]:
    categories = expectation_categories(expectation)
    for index, category in enumerate(categories):
        _category(category, f"expectation category[{index}]")
    return categories


def scope_census_fragment(
    expectation: Expectation,
    document: DocumentFingerprint,
    *,
    run_id: str,
    phase: str,
    result_var: str = "__kirScopeCensusObservation",
) -> str:
    """Emit a bounded census fragment assigning one observation map."""

    if not isinstance(expectation, Expectation):
        raise TypeError("live acceptance requires a typed Expectation")
    if not isinstance(document, DocumentFingerprint):
        raise TypeError("live acceptance requires DocumentFingerprint")
    accepted_run_id = _run_id(run_id)
    accepted_phase = _phase(phase)
    if re.fullmatch(r"__[A-Za-z0-9_]+", result_var) is None:
        raise ScopeCensusError("scope census result variable is unsafe")
    categories = _registered_categories(expectation)
    if not categories:
        raise ScopeCensusError(
            "vacuous expectation has no live census scope")
    category_literals = ", ".join(
        cs_string_literal(category) for category in categories)
    exp_digest = expectation_digest(expectation)
    body = f"""
{ELEMENT_LEVEL_HELPERS_CS}
var __kirAcceptanceWanted = new HashSet<string>(
    new string[] {{ {category_literals} }}, StringComparer.Ordinal);
var __kirAcceptanceCounts = new Dictionary<string, Dictionary<string, long>>(
    StringComparer.Ordinal);
long __kirAcceptanceTotal = 0L;
foreach (Element __kirAcceptanceElement in new FilteredElementCollector(doc)
         .WhereElementIsNotElementType())
{{
    string __kirAcceptanceCategory = null;
    if (__kirAcceptanceElement is DirectShape
        && __kirAcceptanceWanted.Contains("DirectShape"))
    {{
        __kirAcceptanceCategory = "DirectShape";
    }}
    else
    {{
        Category __kirAcceptanceRawCategory = null;
        try {{ __kirAcceptanceRawCategory = __kirAcceptanceElement.Category; }} catch {{ }}
        if (__kirAcceptanceRawCategory != null)
        {{
            long __kirAcceptanceNumeric;
            if (Int64.TryParse(__kirAcceptanceRawCategory.Id.ToString(),
                               out __kirAcceptanceNumeric))
            {{
                try
                {{
                    __kirAcceptanceCategory = Enum.GetName(
                        typeof(BuiltInCategory),
                        (BuiltInCategory)__kirAcceptanceNumeric);
                }}
                catch {{ __kirAcceptanceCategory = null; }}
            }}
        }}
    }}
    if (String.IsNullOrEmpty(__kirAcceptanceCategory)
        || !__kirAcceptanceWanted.Contains(__kirAcceptanceCategory))
        continue;

    string __kirAcceptanceLevel = "";
    var __kirAcceptanceResolvedLevel = __ElementLevel(__kirAcceptanceElement);
    if (__kirAcceptanceResolvedLevel != null)
    {{
        try
        {{
            __kirAcceptanceLevel =
                (__kirAcceptanceResolvedLevel.Name ?? "").Trim();
        }}
        catch {{ __kirAcceptanceLevel = ""; }}
    }}
    Dictionary<string, long> __kirAcceptanceByLevel;
    if (!__kirAcceptanceCounts.TryGetValue(
            __kirAcceptanceCategory, out __kirAcceptanceByLevel))
    {{
        __kirAcceptanceByLevel = new Dictionary<string, long>(
            StringComparer.Ordinal);
        __kirAcceptanceCounts[__kirAcceptanceCategory] =
            __kirAcceptanceByLevel;
    }}
    __kirAcceptanceByLevel[__kirAcceptanceLevel] =
        __kirAcceptanceByLevel.ContainsKey(__kirAcceptanceLevel)
        ? __kirAcceptanceByLevel[__kirAcceptanceLevel] + 1L : 1L;
    __kirAcceptanceTotal++;
}}
// ПОРЯДОК ЗДЕСЬ — ЧАСТЬ КОНТРАКТА, И ОН ПОРЯДКОВЫЙ, А НЕ КУЛЬТУРНЫЙ.
// `ScopeCensusObservation` принимает строки только в питоновском
// `sorted()`, то есть по кодовым точкам. `OrderBy` без компаратора берёт
// `Comparer<string>.Default` — сравнение ПО КУЛЬТУРЕ машины.
//
// Замер живьём 04.08 (устройство оператора, CurrentCulture=ru-RU, имена
// уровней «Проект1»): культурный и порядковый порядок не совпали НИ В ОДНОЙ
// позиции — «Основание B.O.» шло первым, а порядковый ждёт там
// «KIR_GAP_CEIL»; у категорий разошлись `OST_Rooms` и
// `OST_RoomSeparationLines`. Приёмка падала fail-closed: `KIR-A002` до
// записи («scope census rows must be unique and sorted») и
// `post_read_invalid` после неё — на программе, которая построилась верно.
var __kirAcceptanceRows = new List<object>();
foreach (var __kirAcceptanceCategoryPair in
         __kirAcceptanceCounts.OrderBy(__x => __x.Key, StringComparer.Ordinal))
{{
    foreach (var __kirAcceptanceLevelPair in
             __kirAcceptanceCategoryPair.Value.OrderBy(
                 __x => __x.Key, StringComparer.Ordinal))
    {{
        __kirAcceptanceRows.Add(new Dictionary<string, object> {{
            {{"category", __kirAcceptanceCategoryPair.Key}},
            {{"level_name", __kirAcceptanceLevelPair.Key}},
            {{"count", __kirAcceptanceLevelPair.Value}}
        }});
    }}
}}
var {result_var} = new Dictionary<string, object> {{
    {{"schema_version", "{SCOPE_CENSUS_SCHEMA_VERSION}"}},
    {{"run_id", "{accepted_run_id}"}},
    {{"phase", "{accepted_phase}"}},
    {{"expectation_digest", "{exp_digest}"}},
    {{"document_digest", "{document.digest}"}},
    {{"categories", __kirAcceptanceWanted.OrderBy(
        __x => __x, StringComparer.Ordinal).ToList()}},
    {{"rows", __kirAcceptanceRows}},
    {{"total", __kirAcceptanceTotal}}
}};
""".strip()
    return body


def build_scope_census_cs(
    expectation: Expectation,
    document: DocumentFingerprint,
    *,
    run_id: str,
    phase: str,
) -> str:
    """Build one document-bound, read-only category x level census program."""

    fragment = scope_census_fragment(
        expectation,
        document,
        run_id=run_id,
        phase=phase,
    )
    return bind_read_to_document(
        fragment + "\nreturn __kirScopeCensusObservation;", document)


def observation_from_census(
    expectation: Expectation,
    document: DocumentFingerprint,
    census: ScopeCensus,
    *,
    run_id: str,
    phase: str,
) -> ScopeCensusObservation:
    """Build the exact wire observation from trusted in-process counters.

    This is useful to adapters and deterministic tests.  Live serving still
    obtains the counters only from :func:`build_scope_census_cs` and parses
    them with :func:`parse_scope_census`.
    """

    categories = _registered_categories(expectation)
    wanted = set(categories)
    rows: list[ScopeCensusRow] = []
    for key, value in census.items():
        if (not isinstance(key, tuple) or len(key) != 2
                or not isinstance(key[0], str)
                or not isinstance(key[1], str)):
            raise ScopeCensusError(
                "in-process scope census keys must be (category, level) strings")
        if key[0] not in wanted or not value:
            continue
        rows.append(ScopeCensusRow(key[0], key[1], value))
    rows.sort()
    return ScopeCensusObservation(
        run_id=_run_id(run_id),
        phase=_phase(phase),
        expectation_digest=expectation_digest(expectation),
        document_digest=document.digest,
        categories=categories,
        rows=tuple(rows),
        total=sum(row.count for row in rows),
    )


def parse_scope_census(
    value: Any,
    expectation: Expectation,
    document: DocumentFingerprint,
    *,
    run_id: str,
    phase: str,
) -> ScopeCensusObservation:
    """Strictly parse and bind one bridge census response."""

    if not isinstance(value, Mapping):
        raise ScopeCensusError("scope census response must be an object")
    row = dict(value)
    required = {
        "schema_version", "run_id", "phase", "expectation_digest", "document_digest",
        "categories", "rows", "total",
    }
    if set(row) != required:
        missing = sorted(required - set(row))
        extra = sorted(set(row) - required)
        raise ScopeCensusError(
            f"scope census fields differ; missing={missing}, extra={extra}")
    if row["schema_version"] != SCOPE_CENSUS_SCHEMA_VERSION:
        raise ScopeCensusError("unsupported scope census schema_version")
    expected_run = _run_id(run_id)
    if row["run_id"] != expected_run:
        raise ScopeCensusError("scope census belongs to another execution")
    expected_phase = _phase(phase)
    if row["phase"] != expected_phase:
        raise ScopeCensusError("scope census belongs to another read phase")
    expected_expectation = expectation_digest(expectation)
    if row["expectation_digest"] != expected_expectation:
        raise ScopeCensusError("scope census belongs to another expectation")
    if row["document_digest"] != document.digest:
        raise ScopeCensusError("scope census belongs to another document")

    raw_categories = row["categories"]
    if (not isinstance(raw_categories, Sequence)
            or isinstance(raw_categories, (str, bytes, bytearray))):
        raise ScopeCensusError("scope census categories must be an array")
    categories = tuple(
        _category(item, f"categories[{index}]")
        for index, item in enumerate(raw_categories)
    )
    if categories != _registered_categories(expectation):
        raise ScopeCensusError("scope census category universe was widened")

    raw_rows = row["rows"]
    if (not isinstance(raw_rows, Sequence)
            or isinstance(raw_rows, (str, bytes, bytearray))):
        raise ScopeCensusError("scope census rows must be an array")
    parsed: list[ScopeCensusRow] = []
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise ScopeCensusError(f"scope census rows[{index}] must be object")
        item = dict(raw)
        if set(item) != {"category", "level_name", "count"}:
            raise ScopeCensusError(
                f"scope census rows[{index}] has an open wire shape")
        level = item["level_name"]
        if not isinstance(level, str):
            raise ScopeCensusError(
                f"scope census rows[{index}].level_name must be string")
        parsed.append(ScopeCensusRow(
            _category(item["category"], f"rows[{index}].category"),
            level,
            _count(item["count"], f"rows[{index}].count", positive=True),
        ))
    return ScopeCensusObservation(
        run_id=expected_run,
        phase=expected_phase,
        expectation_digest=expected_expectation,
        document_digest=document.digest,
        categories=categories,
        rows=tuple(parsed),
        total=_count(row["total"], "scope census total"),
    )


__all__ = [
    "SCOPE_CENSUS_SCHEMA_VERSION",
    "ScopeCensusError",
    "ScopeCensusObservation",
    "ScopeCensusRow",
    "build_scope_census_cs",
    "observation_from_census",
    "parse_scope_census",
    "scope_census_fragment",
]
