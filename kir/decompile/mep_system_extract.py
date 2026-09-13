"""Side index of the SYSTEM TYPE: without it an engineering building cannot
be reassembled.

THE TRIGGER IS A DRY REASSEMBLY RUN, not a guess. The Snowdon Towers Sample
Plumbing model was fully decompiled: 3 051 pipes were lifted into
``create_pipe``, with "expressible from what was read" coverage of 98.4%. But
a dry reassembly gave **0 of 26 chunks**, for one reason:
``KIR-G102 piping_system_types: multiple variants — no default possible``.

The decompile lifted a pipe with no system type. The document has twelve of
them, and the grounding gate honestly refused to guess. The forward pass
treats ``system_type`` as OPTIONAL, because with a single variant in the
pool it can be inferred; any real engineering building has variants, and the
optional field becomes mandatory. As long as that is so, coverage measures
EXPRESSIBILITY, not EXECUTABILITY, and the difference between the two is the
difference between "we can write this down" and "we can build this".

WHERE IT COMES FROM. ``MEPCurve.MEPSystem`` is a property that lives across
all six versions (checked with the trap index, not from memory; ``Pipe`` and
``Duct`` inherit it from ``MEPCurve``). Then ``Element.GetTypeId`` and
``Element.Name``, also 6/6. Not one guessed name: a typo in a member name
would have cost a CS0117 across six versions for the sake of one line.

WHAT IS NOT HERE. Cable tray (``OST_CableTray``) has no system at all —
``create_cable_tray`` has no such parameter either. Flex pipes and flex
ducts are not captured by this wave: another path lifts them, and adding the
category to the table without checking the lifter first would open a gap
out of nowhere.
"""
from __future__ import annotations

import json
from kir.emit_utils import cs_string_literal
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from kir.decompile.side_contract import (
    ELEMENT_ID_HELPER_CS,
    ELEMENT_ID_OUT_OF_RANGE_REASON,
    optional_failures,
    source_binding_cs,
)

MEP_SYSTEM_INDEX_SCHEMA_VERSION = "kir-decompile-mep-system-index/1"
MEP_SYSTEM_EXTRACT_SCHEMA_VERSION = "kir-decompile-mep-system-extract/1"

#: Categories this stage feeds. Moves TOGETHER with the row in
#: ``pipeline._STAGE_CATEGORIES``: a category here with no row there means
#: ids are never requested; a row there with no category here means every
#: id will leave as a receipt.
MEP_SYSTEM_CATEGORIES = frozenset({"OST_PipeCurves", "OST_DuctCurves"})


class MepSystemPayloadError(ValueError):
    """A wire response of the wrong shape — a typed refusal, not a guess."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MepSystemPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise MepSystemPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise MepSystemPayloadError(f"{field_name} must be an array")
    return value


def _exact_fields(value: Any, allowed: set[str], field_name: str, *,
                  optional: set[str] | None = None) -> dict[str, Any]:
    root = _mapping(value, field_name)
    optional = optional or set()
    missing = allowed - optional - set(root)
    if missing:
        raise MepSystemPayloadError(f"{field_name} is missing {sorted(missing)}")
    extra = set(root) - allowed
    if extra:
        raise MepSystemPayloadError(f"{field_name} has unexpected {sorted(extra)}")
    return root


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise MepSystemPayloadError(f"{field_name} must be a non-empty string")
    return value


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return (0, int(value), value)
    except (TypeError, ValueError):
        return (1, value, value)


@dataclass(frozen=True, slots=True)
class MepSystemRecord:
    """Which system a pipe or duct belongs to."""

    element_id: str
    #: The system TYPE (Sanitary / Supply Air / …). The TYPE specifically,
    #: not the system instance: reassembly needs the type, Revit will infer
    #: the instance itself.
    system_type_id: str
    #: The type name. The L1 reference dialect knows exactly one named form
    #: {"by": "name", "value": <name>, "_id": <id>} — a reference cannot be
    #: assembled without a name. A lesson from the styling wave, applied
    #: here in advance.
    system_type_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "system_type_id": self.system_type_id,
            "system_type_name": self.system_type_name,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "MepSystemRecord":
        root = _exact_fields(
            value, {"element_id", "system_type_id", "system_type_name"},
            "mep system record")
        return cls(
            element_id=_string(root["element_id"], "mep system record.element_id"),
            system_type_id=_string(
                root["system_type_id"], "mep system record.system_type_id"),
            system_type_name=_string(
                root["system_type_name"], "mep system record.system_type_name"),
        )


@dataclass(frozen=True, slots=True)
class MepSystemFailure:
    """Receipt §18.2: an element the stage requested and did not read."""

    element_id: str
    reason: str
    typed_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"element_id": self.element_id, "reason": self.reason,
                "typed_reason": self.typed_reason}

    @classmethod
    def from_dict(cls, value: Any) -> "MepSystemFailure":
        root = _exact_fields(
            value, {"element_id", "reason", "typed_reason"}, "mep system failure")
        return cls(
            element_id=_string(root["element_id"], "mep system failure.element_id"),
            reason=_string(root["reason"], "mep system failure.reason"),
            typed_reason=_string(
                root["typed_reason"], "mep system failure.typed_reason"))


@dataclass(frozen=True, slots=True)
class MepSystemExtraction:
    """A validated side index of system membership."""

    systems: tuple[MepSystemRecord, ...] = ()
    failures: tuple[MepSystemFailure, ...] = ()

    def __post_init__(self) -> None:
        ids = [record.element_id for record in self.systems]
        if len(ids) != len(set(ids)):
            raise MepSystemPayloadError(
                "mep system index contains duplicate element_id")

    def __iter__(self) -> Iterator[MepSystemRecord]:
        return iter(self.systems)

    def __len__(self) -> int:
        return len(self.systems)

    @property
    def records(self) -> tuple[MepSystemRecord, ...]:
        """The CONTRACT name that the §18.2 checker asks for.

        The styling wave stumbled on exactly this: the field was named for
        its meaning, the checker asked by contract, and a live run died on
        26 elements with correct C#. The property is put in place RIGHT
        AWAY, not after a second lesson.
        """
        return self.systems

    @property
    def system_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.systems, key=lambda r: _element_id_key(r.element_id))
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MEP_SYSTEM_INDEX_SCHEMA_VERSION,
            "system_index": self.system_index,
            "failures": [
                failure.to_dict()
                for failure in sorted(
                    self.failures,
                    key=lambda f: (_element_id_key(f.element_id), f.reason))],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Any) -> "MepSystemExtraction":
        root = _exact_fields(
            value, {"schema_version", "system_index", "failures"},
            "mep system index", optional={"failures"})
        if root["schema_version"] != MEP_SYSTEM_INDEX_SCHEMA_VERSION:
            raise MepSystemPayloadError("mep system index schema_version mismatch")
        index = _mapping(root["system_index"], "mep system index.system_index")
        records = []
        for key, row in index.items():
            record = MepSystemRecord.from_dict(row)
            if record.element_id != key:
                raise MepSystemPayloadError(
                    "mep system index key does not match record.element_id")
            records.append(record)
        failures = tuple(
            MepSystemFailure.from_dict(row)
            for row in optional_failures(
                root.get("failures"), "mep system index.failures",
                MepSystemPayloadError))
        return cls(systems=tuple(records), failures=failures)

    @classmethod
    def from_json(cls, text: str) -> "MepSystemExtraction":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MepSystemPayloadError(
                f"mep system index is not valid JSON: {exc}") from exc
        return cls.from_dict(value)


def _unwrap_bridge_payload(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "payload" in payload \
            and "schema_version" not in payload:
        return payload["payload"]
    return payload


def extract_mep_systems(payload: Any) -> MepSystemExtraction:
    """Validate one bridge response and assemble the index."""
    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "elements", "failures"},
        "MEP system extraction", optional={"failures"})
    if root["schema_version"] != MEP_SYSTEM_EXTRACT_SCHEMA_VERSION:
        raise MepSystemPayloadError("MEP system extraction schema_version mismatch")
    records = []
    for index, row in enumerate(_array(root["elements"],
                                       "MEP system extraction.elements")):
        item = _exact_fields(
            row, {"element_id", "system_type_id", "system_type_name"},
            f"MEP system extraction.elements[{index}]")
        records.append(MepSystemRecord(
            element_id=_string(item["element_id"], f"elements[{index}].element_id"),
            system_type_id=_string(
                item["system_type_id"], f"elements[{index}].system_type_id"),
            system_type_name=_string(
                item["system_type_name"], f"elements[{index}].system_type_name"),
        ))
    failures = tuple(
        MepSystemFailure.from_dict(row)
        for row in optional_failures(
            root.get("failures"), "MEP system extraction.failures",
            MepSystemPayloadError))
    return MepSystemExtraction(systems=tuple(records), failures=failures)


def merge_mep_systems(parts: list[MepSystemExtraction]) -> MepSystemExtraction:
    """Merge pages without losing a single record or receipt."""
    records: list[MepSystemRecord] = []
    failures: list[MepSystemFailure] = []
    seen: set[str] = set()
    for part in parts:
        for record in part.systems:
            # The FIRST one read wins: "last one wins" would make the result
            # depend on page order, i.e. on the network.
            if record.element_id in seen:
                continue
            seen.add(record.element_id)
            records.append(record)
        failures.extend(part.failures)
    return MepSystemExtraction(systems=tuple(records), failures=tuple(failures))


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


MEP_SYSTEM_HELPER_CS = r"""
// KIR DECOMPILE — read-only MEP system helpers. Никаких транзакций.
// Имя класса БЕЗ обращения к среде выполнения за типом: та форма записи
// целиком отвергается валидатором безопасности моста версий до 06.07.2026,
// который всё ещё стоит на части флота, — тело браковалось бы на машине
// пользователя ДО компиляции, и сервер об этом не узнавал бы.
// Object.ToString() у Element/Curve/Surface и у исключений — это полное имя
// типа CLR: из Autodesk.Revit.DB его перекрывают только ElementId, UV, XYZ,
// WorksetId, ScheduleFieldId и PolymeshFacet (замер по индексу ловушек), и
// ни один из них сюда не передаётся. Исключение дописывает ": сообщение" и
// стек, поэтому срез идёт по первому переводу строки и первому двоеточию.
// Результат побайтно равен прежнему .Name.
Func<object, string> __msClassName = (__mscnObj) =>
{
    if (__mscnObj == null) return "";
    string __mscn = __mscnObj.ToString();
    if (__mscn == null) return "";
    int __mscnCut = __mscn.IndexOf((char)10);
    if (__mscnCut >= 0) __mscn = __mscn.Substring(0, __mscnCut);
    __mscnCut = __mscn.IndexOf(':');
    if (__mscnCut >= 0) __mscn = __mscn.Substring(0, __mscnCut);
    __mscn = __mscn.Trim();
    __mscnCut = __mscn.LastIndexOf('.');
    return __mscnCut >= 0 && __mscnCut + 1 < __mscn.Length
        ? __mscn.Substring(__mscnCut + 1) : __mscn;
};
Func<ElementId, string> __msValidIdString = (__id) =>
    (__id == null || __id == ElementId.InvalidElementId)
        ? null : __id.ToString();
""" + ELEMENT_ID_HELPER_CS + "\n"


_MEP_SYSTEM_BODY_CS = r"""
long __msCallBudgetMs = __MS_CALL_BUDGET_MS__L;
long __msCallWatchT0 = DateTime.UtcNow.Ticks;

var __msFailures = new List<object>();
Action<string, string, string> __msFail =
    (__failedId, __reason, __typed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __msFailures.Add(__failure);
};

var __msIds = new List<string> { __MEP_SYSTEM_IDS__ };
var __msRows = new List<object>();
bool __msBudgetOut = false;
foreach (string __msRaw in __msIds)
{
    if (__msBudgetOut
        || ((DateTime.UtcNow.Ticks - __msCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __msCallBudgetMs)
    {
        __msBudgetOut = true;
        __msFail(__msRaw, "call_budget_exhausted", "call_budget_exhausted");
        continue;
    }
    // Имя ШАГА, который сейчас идёт: тип исключения без имени вызова — одно
    // ведро на всё, и по нему нельзя сказать ни ЧТО читали, ни ЧТО ответил Revit.
    string __msStep = "ElementId.Parse";
    try
    {
        long __msNum = 0L;
        if (!Int64.TryParse(__msRaw, out __msNum))
        {
            __msFail(__msRaw, "element id is not numeric", "element_unresolved");
            continue;
        }
        __msStep = "Document.GetElement";
        ElementId __msId = __sideElementId(__msNum);
        if (__msId == null)
        {
            __msFail(__msRaw, "__ELEMENT_ID_OUT_OF_RANGE__", "element_unresolved");
            continue;
        }
        Element __msEl = __src.GetElement(__msId);
        if (__msEl == null)
        {
            __msFail(__msRaw, "element not found in document", "element_unresolved");
            continue;
        }
        __msStep = "cast to MEPCurve";
        Autodesk.Revit.DB.MEPCurve __msCurve = __msEl as Autodesk.Revit.DB.MEPCurve;
        if (__msCurve == null)
        {
            __msFail(__msRaw, "not an MEPCurve: " + __msClassName(__msEl),
                     "element_kind_mismatch");
            continue;
        }
        __msStep = "MEPCurve.MEPSystem";
        Autodesk.Revit.DB.MEPSystem __msSystem = __msCurve.MEPSystem;
        if (__msSystem == null)
        {
            // Труба, не приписанная ни к какой системе, — законное состояние
            // модели, а не сбой чтения: она так и лежит «ничьей».
            __msFail(__msRaw, "element belongs to no MEP system",
                     "aspect_not_present");
            continue;
        }
        __msStep = "MEPSystem.GetTypeId";
        ElementId __msTypeId = __msSystem.GetTypeId();
        string __msTypeIdStr = __msValidIdString(__msTypeId);
        if (__msTypeIdStr == null)
        {
            __msFail(__msRaw, "MEP system has no type", "aspect_not_present");
            continue;
        }
        __msStep = "system type Name";
        Element __msTypeEl = __src.GetElement(__msTypeId);
        string __msTypeName = (__msTypeEl == null) ? null : __msTypeEl.Name;
        if (String.IsNullOrEmpty(__msTypeName))
        {
            // Диалект ссылок L1 именованный: тип без имени не адресовать.
            __msFail(__msRaw, "MEP system type has no name", "aspect_not_present");
            continue;
        }

        var __msRow = new Dictionary<string, object>();
        __msRow["element_id"] = __msRaw;
        __msRow["system_type_id"] = __msTypeIdStr;
        __msRow["system_type_name"] = __msTypeName;
        __msRows.Add(__msRow);
    }
    catch (Exception __msEx)
    {
        __msFail(__msRaw,
                 "MEP system read failed at " + __msStep + ": "
                     + __msClassName(__msEx),
                 "read_failed");
    }
}

var __msPayload = new Dictionary<string, object>();
__msPayload["schema_version"] = __MS_SCHEMA__;
__msPayload["elements"] = __msRows;
__msPayload["failures"] = __msFailures;
return __msPayload;
"""


def build_mep_system_extract_cs(element_ids: list[str], *,
                                call_budget_ms: int = 20_000,
                                link_title: str | None = None) -> str:
    """C# for one page of the system-membership stage.

    ``link_title`` — read not the HOST, but its link to that
    ``Document.Title``. There must be one source for the whole body:
    ``__src.GetElement`` on the link id in the host document would return
    either null (a receipt out of nowhere), or a FOREIGN element with the
    same number — silently, and indistinguishable from the truth.
    """
    quoted = ", ".join(_csharp_string(str(item)) for item in element_ids)
    body = _MEP_SYSTEM_BODY_CS
    body = body.replace("__MS_CALL_BUDGET_MS__", str(int(call_budget_ms)))
    body = body.replace("__MEP_SYSTEM_IDS__", quoted)
    body = body.replace(
        "__ELEMENT_ID_OUT_OF_RANGE__", ELEMENT_ID_OUT_OF_RANGE_REASON)
    body = body.replace(
        "__MS_SCHEMA__", _csharp_string(MEP_SYSTEM_EXTRACT_SCHEMA_VERSION))
    return (source_binding_cs(link_title) + "\n"
            + MEP_SYSTEM_HELPER_CS + body)
