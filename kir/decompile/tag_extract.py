"""Side index of TAGS: the reference, view, and head point that L0 does not carry.

WHY. The annotation wave of 30.07 lifted text notes and honestly named what
it did not do: "Tags and dimensions are not captured by this wave — a tag
has a version seam at 2022 (``TaggedLocalElementId`` before 2022 /
``GetTaggedLocalElementIds`` since 2022), and it deserves its own wave, not
a line at the end of this one" (``annotation_extract`` docstring). This is
that wave.

There are 20,448 tags in the measured document — the largest kind of
annotation after dimensions. The ``create_tag`` op has been in the registry
since 28.07 and is dead not out of laziness: its mandatory inputs
(``in_view``, ``target``, ``at``) are ABSENT AS FIELDS from the frozen L0 1.0
row, and the lifter used to refuse with ``source_contract_gap``. The order
is strict and cannot be worked around: CAPTURE first, then the lifter.

THE 2022 VERSION SEAM IS THE MAIN THING HERE. Checked against the trap index
(``tools/api_trap_index.py``), not memory:

    P:IndependentTag.TaggedLocalElementId       2021-2022, REMOVED after 2022
    M:IndependentTag.GetTaggedLocalElements     2022-2026, ABSENT in 2021
    (M:IndependentTag.GetTaggedLocalElementIds  2022-2026, but FORBIDDEN to us:
     returns ``ISet<>`` from ``System.dll``, which the deployed plugin does
     not have — CS0012 live on 04.08; see _TAG_TARGET_2022_CS)

That is, 2022 is the only year where BOTH exist, and there is no single
member living across all six versions for a tag's target. One C# text,
checked against all six targets, would fail to compile on either 2021 or
2023+, so the branching lives IN PYTHON: exactly one call is emitted per
version, never two in one body under try/catch. This is the same law by
which the direct emitter branches (``authoring._emit_tag``), and it is
recorded here a second time deliberately: both sides of the round trip must
tear the surface at the same spot.

TWO KINDS OF TAGS, NOT ONE. ``OST_RoomTags`` (11,585 elements, more than
half of all tags) is NOT an ``IndependentTag``: a room, area, and space tag
are all ``SpatialElementTag``, which has its own surface
(``TagHeadPosition`` / ``HasLeader``, both 6/6). The stage reads both kinds
and marks the row with the ``tag_family`` field; the decision of what to do
with it is made by the LIFT, not the read (see ``lift._lift_tag``: the
direct path only knows ``IndependentTag.Create``, and a room tag gets a
named refusal, not a made-up reconstruction).

THE TARGET OF A SPATIAL TAG IS TAKEN FROM THE SUBCLASS, NOT FROM THE BASE,
and this is a defect fix, not a style choice. This used to say
"``SpatialElementTag.SpatialElement`` — all 6/6, checked against the trap
index." The property is described in ``RevitAPI.xml`` for all six versions
and IS ABSENT from the shipped ``RevitAPI.dll`` for all six: the stage's
body did not compile on A SINGLE version (``CS1061``), meaning tags were
never read, anywhere. The trap index is built from the XML, so "checked
against the index" was confirming Autodesk's documentation, not the
assembly. A member is considered to exist when Roslyn has accepted it (see
``gate_runner``), not when it has been written about.

WHAT EXACTLY IS READ, AND BY WHAT (every member checked against the trap index):

    op field        API member                                  versions
    ─────────────────────────────────────────────────────────────────────
    in_view         Element.OwnerViewId + View.Name             all 6
    at              IndependentTag.TagHeadPosition               all 6
                    SpatialElementTag.TagHeadPosition            all 6
                    (projected onto the view basis ON THE BRIDGE)
    target          IndependentTag.TaggedLocalElementId         2021-2022
                    IndependentTag.GetTaggedLocalElements()     2022-2026
                    RoomTag.Room / AreaTag.Area / SpaceTag.Space   all 6
                    (NOT SpatialElementTag.SpatialElement: see below)
    leader          IndependentTag.HasLeader                     all 6
                    SpatialElementTag.HasLeader                  all 6
    tag_type        Element.GetTypeId + Element.Name             all 6

WHY THE COORDINATE IS COMPUTED ON THE BRIDGE. For exactly the same reason as
with text notes: the direct path materializes a view point into world space
using the basis of the view ITSELF (``docspace.emit_view2d_to_xyz_cs``:
``Origin + u*Right + v*Up``), and the inverse transform must be its EXACT
inverse, not a similar-looking formula written somewhere else:

    rel = P - view.Origin;  u = rel · view.RightDirection;  v = rel · view.UpDirection

WHAT IS NOT HERE, AND WHY.

* ``TagOrientation`` (all 6 versions) IS CAPTURED, even though the op has no
  parameter for it. This is not "just in case": the direct emitter bakes in
  ``TagOrientation.Horizontal`` unconditionally, and without this field a
  vertical tag would be reconstructed as horizontal SILENTLY — a comparison
  by head position does not see this substitution. The field exists for a
  NAMED refusal in the lift, not for a parameter.
* The leader is captured by the ``HasLeader`` flag and only by it — but this
  flag carries MORE than it looks like, and this is the wave's main finding.
  Autodesk's verbatim line about the seventh argument of
  ``IndependentTag.Create`` (RevitAPI.xml, ``param pnt``; identical in 2021
  and in 2026, in both overloads):

      "For tags without leaders, this point is the position of the tag head.
       For tags with leaders, this point is the end point of the leader, and a
       leader of default length will be created from this point to the tag
       head."

  That is, the op's ``at`` is the head ONLY for a tag with no leader. The
  stage reads ``TagHeadPosition``, so a tag WITH a leader is REFUSED BY THE
  LIFT, by name (``lift._lift_tag``): a reconstruction would place the
  leader's end point where the head used to be, and the shift would stay
  invisible — a comparison by head position does not catch it. There is
  nothing to capture the leader's end point with without a new wave:
  ``GetLeaderEnd`` DOES NOT EXIST in 2021 (``NEW IN 2022`` per the trap
  index) and since 2023 is documented to throw when the leader has no free
  end or is not visible.
* A tag on an element of a LINKED file is inexpressible: the op's
  ``target`` addresses an element of THIS document. Such a tag gets the
  ``tag_target_not_local`` receipt — a named refusal, not a binding to a
  similar element of this file.
* A tag on MULTIPLE elements (2022+ can do this) is also inexpressible: the
  op has exactly one ``target``. Receipt ``address_ambiguous``, because any
  single address here would be a guess.
"""
from __future__ import annotations

import json
from kir.emit_utils import cs_string_literal
from kir import spec as _spec
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from kir.decompile.side_contract import (
    ELEMENT_ID_HELPER_CS,
    ELEMENT_ID_OUT_OF_RANGE_REASON,
    optional_failures,
    source_binding_cs,
)

#: Version of the PERSISTENT index (what lands on disk and gets reused by
#: resume). Changes when the record's shape changes.
TAG_INDEX_SCHEMA_VERSION = "kir-decompile-tag-index/1"
#: Version of the bridge's WIRE response. The literal is baked into the C#
#: and checked while parsing: a foreign or stale response must refuse loudly,
#: not get half-parsed.
TAG_EXTRACT_SCHEMA_VERSION = "kir-decompile-tag-extract/1"

_FT_TO_MM = 304.8

#: The tag's kind: what it actually is in the API, not what its category is
#: called. ``independent`` — ``IndependentTag`` (door, wall, floor, beam…);
#: ``spatial`` — ``SpatialElementTag`` (room, area, space). The distinction
#: is carried by the ROW, not by the lift's guess from the category: there
#: are eleven categories, two kinds, and the link between them is a fact of
#: the API that must travel from the read.
TAG_FAMILY_INDEPENDENT = "independent"
TAG_FAMILY_SPATIAL = "spatial"
TAG_FAMILIES = frozenset({TAG_FAMILY_INDEPENDENT, TAG_FAMILY_SPATIAL})

#: The orientation the direct emitter can set. Everything else is an honest
#: refusal by the lift, not a tag silently straightened out.
TAG_ORIENTATION_HORIZONTAL = "Horizontal"

#: L0 categories this stage feeds — EXACTLY the eleven the extractor reads
#: (``extract._CATEGORY_SPECS``, the "TAGS" block plus the 22.08 tail).
#: ``pipeline._STAGE_CATEGORIES["tag"]`` takes THIS set whole, not its own
#: copy, so a new row here reaches the pipeline on its own; the only
#: remaining second carrier is ``spec.OP_RESULT_CATEGORIES["create_tag"]``,
#: and it as a list.
#:
#: 🔴 OST_WindowTags ADDED 22.08.2026. Not because a capability appeared — it
#: did not: a window tag's kind is `IndependentTag`, the same branch as a
#: door or a wall, and the stage's C# branches by the element's CLASS
#: (``__tgInd != null``), not by category. Added because the argument "there
#: are none in the measured document" expired: the measured document was a
#: single `k2_ar_rd_v6`, while MNVNK has 660 window tags, and the corpus has
#: 3,545 across four of eleven documents. What watches for the next such
#: staleness: ``extract.tag_categories_outside_the_law``.
TAG_CATEGORIES = frozenset({
    "OST_RoomTags",
    "OST_DoorTags",
    "OST_WallTags",
    "OST_WindowTags",
    "OST_FloorTags",
    "OST_AreaTags",
    "OST_StairsRailingTags",
    "OST_StructuralFramingTags",
    "OST_MechanicalEquipmentTags",
    "OST_MaterialTags",
    "OST_MultiCategoryTags",
})

#: The versions the direct path compiles for. The seam runs right through
#: the middle.
#:
#: ASKED OF THE REGISTRY, NOT WRITTEN OUT. Before 13.08.2026 the same six
#: years stood here as literals — a second copy of the authority that would
#: silently have stayed six the day `spec.REVIT_VERSIONS` grows, and the tag
#: tests would keep "checking all versions" while checking the old ones.
TAG_SUPPORTED_VERSIONS = tuple(_spec.REVIT_VERSIONS)
#: The first version where a tag can hold MULTIPLE targets (and where the
#: plural read member appeared in place of the ``TaggedLocalElementId``
#: property).
TAG_MULTI_REFERENCE_SINCE = 2022


class TagPayloadError(ValueError):
    """The wire response has the wrong shape — a typed refusal, not a guess."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TagPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise TagPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TagPayloadError(f"{field_name} must be an array")
    return value


def _exact_fields(value: Any, allowed: set[str], field_name: str, *,
                  optional: set[str] | None = None) -> dict[str, Any]:
    """Not one extra key and not one missing mandatory one.

    A silently ignored extra key is exactly how the two sides of a wire
    drift apart: one already writes a new field, the other does not see it,
    and both believe they agree.
    """
    root = _mapping(value, field_name)
    optional = optional or set()
    missing = allowed - optional - set(root)
    if missing:
        raise TagPayloadError(f"{field_name} is missing {sorted(missing)}")
    extra = set(root) - allowed
    if extra:
        raise TagPayloadError(f"{field_name} has unexpected {sorted(extra)}")
    return root


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TagPayloadError(f"{field_name} must be a non-empty string")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TagPayloadError(f"{field_name} must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise TagPayloadError(f"{field_name} must be finite")
    return number


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TagPayloadError(f"{field_name} must be a boolean")
    return value


def _family(value: Any, field_name: str) -> str:
    family = _string(value, field_name)
    if family not in TAG_FAMILIES:
        raise TagPayloadError(
            f"{field_name} must be one of {sorted(TAG_FAMILIES)}")
    return family


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    """Order by NUMERIC id; non-numeric ones go to the end, but always deterministically."""
    try:
        return (0, int(value), value)
    except (TypeError, ValueError):
        return (1, value, value)


@dataclass(frozen=True, slots=True)
class TagRecord:
    """One tag: what it points at, which view it lives in, and where its head is."""

    element_id: str
    owner_view_id: str
    #: The view's name. Not decoration: the frozen L1 reference dialect knows
    #: EXACTLY one named shape — {"by": "name", "value": <name>, "_id": <id>}.
    #: A reference "by element_id" does not exist in L1, so without the
    #: view's name the tag cannot be expressed at all.
    owner_view_name: str
    #: [u, v] mm in the view's plane — the tag's head, already projected onto
    #: the view basis on the bridge, by the same formula the direct path
    #: uses to place it back.
    at_view_mm: tuple[float, float]
    #: The TAGGED element — exactly one, and exactly of this document. A tag
    #: on a link and a tag on multiple elements do not make it here: they
    #: stay a receipt, because the op has one ``target`` and it addresses its
    #: own file.
    tagged_element_id: str
    #: The tag's kind in API terms (see TAG_FAMILY_*).
    tag_family: str
    leader: bool
    #: ``TagOrientation``/``SpatialElementTagOrientation`` as a string. The op
    #: has no parameter for it — the field exists so the lift can REFUSE by
    #: name, rather than silently straighten the tag out.
    orientation: str
    type_id: str | None = None
    type_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "owner_view_id": self.owner_view_id,
            "owner_view_name": self.owner_view_name,
            "at_view_mm": [self.at_view_mm[0], self.at_view_mm[1]],
            "tagged_element_id": self.tagged_element_id,
            "tag_family": self.tag_family,
            "leader": self.leader,
            "orientation": self.orientation,
            "type_id": self.type_id,
            "type_name": self.type_name,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TagRecord":
        root = _exact_fields(
            value,
            {"element_id", "owner_view_id", "owner_view_name", "at_view_mm",
             "tagged_element_id", "tag_family", "leader", "orientation",
             "type_id", "type_name"},
            "tag record", optional={"type_id", "type_name"})
        at = _array(root["at_view_mm"], "tag record.at_view_mm")
        if len(at) != 2:
            raise TagPayloadError(
                "tag record.at_view_mm must be [u, v] — точка вида ДВУМЕРНА, "
                "третья координата означала бы модельную точку в поле вида")
        type_id = root.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise TagPayloadError("tag record.type_id must be a string")
        type_name = root.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise TagPayloadError("tag record.type_name must be a string")
        return cls(
            element_id=_string(root["element_id"], "tag record.element_id"),
            owner_view_id=_string(
                root["owner_view_id"], "tag record.owner_view_id"),
            owner_view_name=_string(
                root["owner_view_name"], "tag record.owner_view_name"),
            at_view_mm=(_number(at[0], "at_view_mm[0]"),
                        _number(at[1], "at_view_mm[1]")),
            tagged_element_id=_string(
                root["tagged_element_id"], "tag record.tagged_element_id"),
            tag_family=_family(root["tag_family"], "tag record.tag_family"),
            leader=_boolean(root["leader"], "tag record.leader"),
            orientation=_string(root["orientation"], "tag record.orientation"),
            type_id=type_id or None,
            type_name=type_name or None,
        )


@dataclass(frozen=True, slots=True)
class TagFailure:
    """A §18.2 receipt: an element the stage requested and did not read."""

    element_id: str
    reason: str
    typed_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "reason": self.reason,
            "typed_reason": self.typed_reason,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TagFailure":
        root = _exact_fields(
            value, {"element_id", "reason", "typed_reason"}, "tag failure")
        return cls(
            element_id=_string(root["element_id"], "tag failure.element_id"),
            reason=_string(root["reason"], "tag failure.reason"),
            typed_reason=_string(
                root["typed_reason"], "tag failure.typed_reason"),
        )


@dataclass(frozen=True, slots=True)
class TagExtraction:
    """A validated side index of tags, independent of the frozen L0."""

    tags: tuple[TagRecord, ...] = ()
    failures: tuple[TagFailure, ...] = ()

    def __post_init__(self) -> None:
        ids = [record.element_id for record in self.tags]
        if len(ids) != len(set(ids)):
            raise TagPayloadError("tag index contains duplicate element_id")

    def __iter__(self) -> Iterator[TagRecord]:
        return iter(self.tags)

    def __len__(self) -> int:
        return len(self.tags)

    @property
    def records(self) -> tuple[TagRecord, ...]:
        """The CONTRACT name the §18.2 reconciler asks by.

        The annotation wave stumbled on exactly this: the field was named
        for its meaning (``text_notes``), the reconciler asked by contract
        (``records``), and a live Snowdon run died on 26 elements with
        FLAWLESS C# — ``side_stage_count_mismatch``. The property is set in
        place right away, and its presence on every registered stage is held
        by the test ``test_side_stage_contract``.
        """
        return self.tags

    @property
    def tag_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.tags, key=lambda r: _element_id_key(r.element_id))
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TAG_INDEX_SCHEMA_VERSION,
            "tag_index": self.tag_index,
            "failures": [
                failure.to_dict()
                for failure in sorted(
                    self.failures,
                    key=lambda f: (_element_id_key(f.element_id), f.reason))
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Any) -> "TagExtraction":
        root = _exact_fields(
            value, {"schema_version", "tag_index", "failures"},
            "tag index", optional={"failures"})
        if root["schema_version"] != TAG_INDEX_SCHEMA_VERSION:
            raise TagPayloadError("tag index schema_version mismatch")
        index = _mapping(root["tag_index"], "tag index.tag_index")
        records = []
        for key, row in index.items():
            record = TagRecord.from_dict(row)
            if record.element_id != key:
                raise TagPayloadError(
                    "tag index key does not match record.element_id")
            records.append(record)
        failures = tuple(
            TagFailure.from_dict(row)
            for row in optional_failures(root.get("failures"),
                                         "tag index.failures",
                                         TagPayloadError))
        return cls(tags=tuple(records), failures=failures)

    @classmethod
    def from_json(cls, text: str) -> "TagExtraction":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TagPayloadError(
                f"tag index is not valid JSON: {exc}") from exc
        return cls.from_dict(value)


def _unwrap_bridge_payload(payload: Any) -> Any:
    """The bridge wraps the response in ``{"payload": ...}`` — unwrap it ONCE."""
    if isinstance(payload, Mapping) and "payload" in payload \
            and "schema_version" not in payload:
        return payload["payload"]
    return payload


def extract_tags(payload: Any) -> TagExtraction:
    """Validate one bridge response and assemble the index.

    A broken wire shape is a typed exception. An honest refusal for a
    SPECIFIC element is a receipt row, not an exception: the stage must keep
    reading the rest and name what it missed.
    """
    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "elements", "failures"},
        "Tag extraction", optional={"failures"})
    if root["schema_version"] != TAG_EXTRACT_SCHEMA_VERSION:
        raise TagPayloadError("Tag extraction schema_version mismatch")

    records: list[TagRecord] = []
    for index, row in enumerate(_array(root["elements"],
                                       "Tag extraction.elements")):
        item = _exact_fields(
            row,
            {"element_id", "owner_view_id", "owner_view_name", "at_view_ft",
             "tagged_element_id", "tag_family", "leader", "orientation",
             "type_id", "type_name"},
            f"Tag extraction.elements[{index}]",
            optional={"type_id", "type_name"})
        at = _array(item["at_view_ft"], f"elements[{index}].at_view_ft")
        if len(at) != 2:
            raise TagPayloadError(
                f"elements[{index}].at_view_ft must be [u, v]")
        type_id = item.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise TagPayloadError(f"elements[{index}].type_id must be a string")
        type_name = item.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise TagPayloadError(
                f"elements[{index}].type_name must be a string")
        records.append(TagRecord(
            element_id=_string(item["element_id"],
                               f"elements[{index}].element_id"),
            owner_view_id=_string(item["owner_view_id"],
                                  f"elements[{index}].owner_view_id"),
            owner_view_name=_string(item["owner_view_name"],
                                    f"elements[{index}].owner_view_name"),
            # THE CONVERSION LIVES HERE AND ONLY HERE: the wire carries raw feet.
            at_view_mm=(
                _number(at[0], f"elements[{index}].at_view_ft[0]") * _FT_TO_MM,
                _number(at[1], f"elements[{index}].at_view_ft[1]") * _FT_TO_MM),
            tagged_element_id=_string(
                item["tagged_element_id"],
                f"elements[{index}].tagged_element_id"),
            tag_family=_family(item["tag_family"],
                               f"elements[{index}].tag_family"),
            leader=_boolean(item["leader"], f"elements[{index}].leader"),
            orientation=_string(item["orientation"],
                                f"elements[{index}].orientation"),
            type_id=type_id or None,
            type_name=type_name or None,
        ))

    failures = tuple(
        TagFailure.from_dict(row)
        for row in optional_failures(
            root.get("failures"), "Tag extraction.failures",
            TagPayloadError))
    return TagExtraction(tags=tuple(records), failures=failures)


def merge_tags(parts: list[TagExtraction]) -> TagExtraction:
    """Merge the pages of one stage without losing a single record or receipt."""
    records: list[TagRecord] = []
    failures: list[TagFailure] = []
    seen: set[str] = set()
    for part in parts:
        for record in part.tags:
            # The FIRST one read wins, not the last: "last wins" would make
            # the result depend on the order of the pages, i.e. on the
            # network.
            if record.element_id in seen:
                continue
            seen.add(record.element_id)
            records.append(record)
        failures.extend(part.failures)
    return TagExtraction(tags=tuple(records), failures=tuple(failures))


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


TAG_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE — read-only tag helpers. Никаких транзакций.
// Точка головы считается ТОЙ ЖЕ формулой, что и прямой эмиттер:
//   rel = P - view.Origin;  u = rel·view.RightDirection;  v = rel·view.UpDirection
// Провод несёт СЫРЫЕ футы; пересчёт в мм принадлежит офлайн-разборщику.
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
Func<object, string> __tgClassName = (__tgcnObj) =>
{
    if (__tgcnObj == null) return "";
    string __tgcn = __tgcnObj.ToString();
    if (__tgcn == null) return "";
    int __tgcnCut = __tgcn.IndexOf((char)10);
    if (__tgcnCut >= 0) __tgcn = __tgcn.Substring(0, __tgcnCut);
    __tgcnCut = __tgcn.IndexOf(':');
    if (__tgcnCut >= 0) __tgcn = __tgcn.Substring(0, __tgcnCut);
    __tgcn = __tgcn.Trim();
    __tgcnCut = __tgcn.LastIndexOf('.');
    return __tgcnCut >= 0 && __tgcnCut + 1 < __tgcn.Length
        ? __tgcn.Substring(__tgcnCut + 1) : __tgcn;
};
Func<ElementId, string> __tgValidIdString = (__id) =>
    (__id == null || __id == ElementId.InvalidElementId)
        ? null : __id.ToString();
Func<double, bool> __tgFinite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
""" + ELEMENT_ID_HELPER_CS + "\n"


#: The target of a SPATIAL tag. One text for BOTH version branches: it does
#: not depend on the version, and two copies of it (one per branch) would
#: drift apart silently — and would drift apart exactly the way the first
#: version of this block did.
#:
#: THE MEASUREMENT of 30.07: the first version read
#: ``SpatialElementTag.SpatialElement``, and this DID NOT COMPILE ON A
#: SINGLE one of the six versions:
#:
#:     CS1061: 'SpatialElementTag' does not contain a definition for
#:     'SpatialElement'
#:
#: The property is described in ``RevitAPI.xml`` for all six versions — and
#: is absent from the shipped ``RevitAPI.dll`` for all six. The stage's
#: docstring claimed "``SpatialElementTag.SpatialElement`` — all 6/6,
#: checked against the trap index"; the index is built FROM the XML, meaning
#: the check was confirming Autodesk's documentation, not the assembly we
#: compile against. Hence the rule: a member is considered to exist when
#: Roslyn has accepted it, not when it has been written about.
#:
#: The target is taken from the SPECIFIC subclass — there are exactly three
#: across the whole hierarchy (``RoomTag`` / ``AreaTag`` / ``SpaceTag``), and
#: all three members live across all six versions. A fourth subclass, should
#: Autodesk introduce one, will get a NAMED refusal
#: ``element_kind_mismatch``, not a silent ``tag_target_not_local``: "we
#: cannot handle this kind of tag" and "the tag has no local target" are
#: different facts, and conflating them means hiding the first behind the
#: second.
_TAG_TARGET_SPATIAL_CS = r"""
            __tgStep = "RoomTag.Room / AreaTag.Area / SpaceTag.Space";
            Element __tgSpatial = null;
            bool __tgSpatialKnown = false;
            Autodesk.Revit.DB.Architecture.RoomTag __tgRoomTag =
                __tgSpa as Autodesk.Revit.DB.Architecture.RoomTag;
            Autodesk.Revit.DB.AreaTag __tgAreaTag =
                __tgSpa as Autodesk.Revit.DB.AreaTag;
            Autodesk.Revit.DB.Mechanical.SpaceTag __tgSpaceTag =
                __tgSpa as Autodesk.Revit.DB.Mechanical.SpaceTag;
            if (__tgRoomTag != null)
            {
                __tgSpatialKnown = true;
                __tgSpatial = __tgRoomTag.Room;
            }
            else if (__tgAreaTag != null)
            {
                __tgSpatialKnown = true;
                __tgSpatial = __tgAreaTag.Area;
            }
            else if (__tgSpaceTag != null)
            {
                __tgSpatialKnown = true;
                __tgSpatial = __tgSpaceTag.Space;
            }
            if (!__tgSpatialKnown)
            {
                __tgFail(__tgRaw,
                         "unknown SpatialElementTag subclass: "
                             + __tgClassName(__tgSpa),
                         "element_kind_mismatch");
                continue;
            }
            if (__tgSpatial == null)
            {
                __tgFail(__tgRaw,
                         "spatial tag marks no spatial element of this document",
                         "tag_target_not_local");
                continue;
            }
            __tgTargetId = __tgSpatial.Id;
"""


#: A tag's target on 2021: ``TaggedLocalElementId`` is a PROPERTY, and there
#: are no multiple references there by the API's construction.
#: ``GetTaggedLocalElementIds`` does not exist in 2021 (trap index: NEW IN
#: 2022), so this text is the only one possible on 2021, and it would not
#: compile on 2023+.
_TAG_TARGET_2021_CS = r"""
        if (__tgInd != null)
        {
            __tgStep = "IndependentTag.TaggedLocalElementId (<=2021)";
            __tgTargetId = __tgInd.TaggedLocalElementId;
            if (__tgTargetId == null
                || __tgTargetId == ElementId.InvalidElementId)
            {
                __tgFail(__tgRaw,
                         "tag marks no element of this document (linked host or orphaned tag)",
                         "tag_target_not_local");
                continue;
            }
        }
        else
        {
__TAG_TARGET_SPATIAL__
        }
"""


#: A tag's target on 2022+: a set, not one element. Since 2022 a single tag
#: can mark several elements, and this is not a rarity but a documented API
#: capability. The op has exactly one ``target``, so a multi-target tag gets
#: the ``address_ambiguous`` receipt, not "take the first one": the first of
#: the set would depend on Revit's enumeration order.
#:
#: WE ASK FOR ELEMENTS, NOT THEIR IDS, AND THIS IS NOT STYLE.
#: ``GetTaggedLocalElementIds`` returns ``ISet<ElementId>``, and ``ISet<>``
#: on net48 is declared in ``System.dll``, which the deployed plugin's
#: reference closure does NOT have: a live extraction of 13A-RD-AR-K2_v33
#: (Revit 2023) died on 04.08 at 17:22:39 on the VERY FIRST batch of the tag
#: stage — ``CS0012: The type 'ISet<>' is defined in an assembly that is not
#: referenced``, text fingerprint ``5f48cd823928``.
#:
#: THIS CANNOT BE WORKED AROUND WITH A CAST: any use of an expression
#: requires the compiler to load its type — neither ``object`` nor a
#: non-generic ``IEnumerable`` removes this requirement (the same analysis
#: in ``group_extract.py`` about
#: ``GetAvailableAttachedDetailGroupTypeIds``). But here, unlike with
#: groups, the field is mandatory: without a target a tag is not an op. So
#: the NEIGHBORING member of the same class was taken, living across the
#: same 2022-2026 and returning a type from ``mscorlib``:
#:
#:     M:IndependentTag.GetTaggedLocalElementIds  -> ISet<ElementId>          ❌
#:     M:IndependentTag.GetTaggedLocalElements    -> ICollection<Element>     ✅
#:
#: The return types are measured by the Roslyn oracle
#: (``tests/emitted_csharp_signature_closure`` — a deliberate CS0029 error
#: forces the compiler to NAME the type), not taken from documentation. The
#: set is the same thing — the same tagged elements of this document — only
#: the response's shape changes: ``Element.Id`` instead of ``ElementId``
#: directly.
_TAG_TARGET_2022_CS = r"""
        if (__tgInd != null)
        {
            __tgStep = "IndependentTag.GetTaggedLocalElements (>=2022)";
            var __tgTargets = __tgInd.GetTaggedLocalElements();
            int __tgTargetCount = (__tgTargets == null) ? 0 : __tgTargets.Count;
            if (__tgTargetCount == 0)
            {
                __tgFail(__tgRaw,
                         "tag marks no element of this document (linked host or orphaned tag)",
                         "tag_target_not_local");
                continue;
            }
            if (__tgTargetCount > 1)
            {
                __tgFail(__tgRaw,
                         "tag marks " + __tgTargetCount.ToString()
                             + " elements; create_tag holds exactly one target",
                         "address_ambiguous");
                continue;
            }
            foreach (Element __tgOne in __tgTargets)
            {
                if (__tgOne == null) continue;
                __tgTargetId = __tgOne.Id;
                break;
            }
        }
        else
        {
__TAG_TARGET_SPATIAL__
        }
"""


_TAG_EXTRACT_BODY_CS = r"""
long __tgCallBudgetMs = __TG_CALL_BUDGET_MS__L;
long __tgCallWatchT0 = DateTime.UtcNow.Ticks;

var __tgFailures = new List<object>();
Action<string, string, string> __tgFail =
    (__failedId, __reason, __typed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __tgFailures.Add(__failure);
};

var __tgIds = new List<string> { __TAG_IDS__ };
var __tgRows = new List<object>();
bool __tgBudgetOut = false;
foreach (string __tgRaw in __tgIds)
{
    if (__tgBudgetOut
        || ((DateTime.UtcNow.Ticks - __tgCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __tgCallBudgetMs)
    {
        __tgBudgetOut = true;
        __tgFail(__tgRaw, "call_budget_exhausted", "call_budget_exhausted");
        continue;
    }
    // ИМЯ ШАГА, КОТОРЫЙ СЕЙЧАС ИДЁТ. Урок 2846 групп: тип исключения без
    // имени вызова — одно ведро на всё, и по нему нельзя сказать ни ЧТО
    // читали, ни ЧТО ответил Revit.
    string __tgStep = "ElementId.Parse";
    try
    {
        long __tgNum = 0L;
        if (!Int64.TryParse(__tgRaw, out __tgNum))
        {
            __tgFail(__tgRaw, "element id is not numeric", "element_unresolved");
            continue;
        }
        __tgStep = "Document.GetElement";
        ElementId __tgId = __sideElementId(__tgNum);
        if (__tgId == null)
        {
            __tgFail(__tgRaw, "__ELEMENT_ID_OUT_OF_RANGE__", "element_unresolved");
            continue;
        }
        Element __tgEl = __src.GetElement(__tgId);
        if (__tgEl == null)
        {
            __tgFail(__tgRaw, "element not found in document", "element_unresolved");
            continue;
        }
        // ДВА РОДА МАРОК. Марка помещения/площади/пространства — НЕ
        // IndependentTag: у неё своя иерархия (SpatialElementTag), и попытка
        // читать её как IndependentTag дала бы null на 11 585 элементах
        // замеренного документа.
        __tgStep = "cast to IndependentTag / SpatialElementTag";
        Autodesk.Revit.DB.IndependentTag __tgInd =
            __tgEl as Autodesk.Revit.DB.IndependentTag;
        Autodesk.Revit.DB.SpatialElementTag __tgSpa =
            __tgEl as Autodesk.Revit.DB.SpatialElementTag;
        if (__tgInd == null && __tgSpa == null)
        {
            __tgFail(__tgRaw,
                     "not a tag element: " + __tgClassName(__tgEl),
                     "element_kind_mismatch");
            continue;
        }
        string __tgFamily = (__tgInd != null) ? "independent" : "spatial";

        __tgStep = "Element.OwnerViewId";
        ElementId __tgViewId = __tgEl.OwnerViewId;
        string __tgViewIdStr = __tgValidIdString(__tgViewId);
        if (__tgViewIdStr == null)
        {
            // ЗАКОН ПРИВЯЗКИ К ВИДУ: аннотация живёт в конкретном виде, и
            // точка вида существует ТОЛЬКО в его плоскости.
            __tgFail(__tgRaw, "tag has no owner view", "aspect_not_present");
            continue;
        }
        __tgStep = "GetElement(OwnerViewId) as View";
        Autodesk.Revit.DB.View __tgView =
            __src.GetElement(__tgViewId) as Autodesk.Revit.DB.View;
        if (__tgView == null)
        {
            __tgFail(__tgRaw, "owner view is not a View element", "element_unresolved");
            continue;
        }
        __tgStep = "View basis (Origin/RightDirection/UpDirection)";
        XYZ __tgOrigin = __tgView.Origin;
        XYZ __tgRight = __tgView.RightDirection;
        XYZ __tgUp = __tgView.UpDirection;
        if (__tgOrigin == null || __tgRight == null || __tgUp == null)
        {
            __tgFail(__tgRaw, "view basis is unavailable", "aspect_not_present");
            continue;
        }
        __tgStep = "View.Name";
        string __tgViewName = __tgView.Name;
        if (String.IsNullOrEmpty(__tgViewName))
        {
            // Диалект ссылок L1 именованный: вид без имени невыразим.
            __tgFail(__tgRaw, "owner view has no name", "aspect_not_present");
            continue;
        }

        __tgStep = "TagHeadPosition";
        XYZ __tgHead = (__tgInd != null)
            ? __tgInd.TagHeadPosition : __tgSpa.TagHeadPosition;
        if (__tgHead == null)
        {
            __tgFail(__tgRaw, "tag has no head position", "aspect_not_present");
            continue;
        }
        __tgStep = "project onto view basis";
        XYZ __tgRel = __tgHead - __tgOrigin;
        double __tgU = __tgRel.DotProduct(__tgRight);
        double __tgV = __tgRel.DotProduct(__tgUp);
        if (!__tgFinite(__tgU) || !__tgFinite(__tgV))
        {
            __tgFail(__tgRaw, "projected view point is not finite", "aspect_not_present");
            continue;
        }

        // ЦЕЛЬ МАРКИ — ЕДИНСТВЕННОЕ МЕСТО, ГДЕ ПОВЕРХНОСТЬ РВЁТСЯ ПО ВЕРСИИ.
        // Ветвление сделано В PYTHON: ниже стоит РОВНО ОДИН вызов, тот, что
        // существует на целевой версии.
        ElementId __tgTargetId = null;
__TAG_TARGET_BLOCK__
        string __tgTargetIdStr = __tgValidIdString(__tgTargetId);
        if (__tgTargetIdStr == null)
        {
            __tgFail(__tgRaw,
                     "tagged element id is invalid",
                     "tag_target_not_local");
            continue;
        }

        __tgStep = "HasLeader";
        bool __tgLeader = (__tgInd != null)
            ? __tgInd.HasLeader : __tgSpa.HasLeader;

        __tgStep = "TagOrientation";
        string __tgOrient = (__tgInd != null)
            ? __tgInd.TagOrientation.ToString()
            : __tgSpa.TagOrientation.ToString();

        __tgStep = "Element.GetTypeId";
        string __tgTypeId = __tgValidIdString(__tgEl.GetTypeId());
        string __tgTypeName = null;
        if (__tgTypeId != null)
        {
            __tgStep = "type element Name";
            Element __tgTypeEl = __src.GetElement(__tgEl.GetTypeId());
            if (__tgTypeEl != null) __tgTypeName = __tgTypeEl.Name;
        }

        var __tgRow = new Dictionary<string, object>();
        __tgRow["element_id"] = __tgRaw;
        __tgRow["owner_view_id"] = __tgViewIdStr;
        __tgRow["owner_view_name"] = __tgViewName;
        __tgRow["at_view_ft"] = (object)new double[] { __tgU, __tgV };
        __tgRow["tagged_element_id"] = __tgTargetIdStr;
        __tgRow["tag_family"] = __tgFamily;
        __tgRow["leader"] = __tgLeader;
        __tgRow["orientation"] = __tgOrient;
        __tgRow["type_id"] = __tgTypeId;
        __tgRow["type_name"] = __tgTypeName;
        __tgRows.Add(__tgRow);
    }
    catch (Exception __tgEx)
    {
        __tgFail(__tgRaw,
                 "tag read failed at " + __tgStep + ": "
                     + __tgClassName(__tgEx),
                 "read_failed");
    }
}

var __tgPayload = new Dictionary<string, object>();
__tgPayload["schema_version"] = __TG_SCHEMA__;
__tgPayload["elements"] = __tgRows;
__tgPayload["failures"] = __tgFailures;
return __tgPayload;
"""


def tag_target_block_cs(revit_version: Any) -> str:
    """The one and only piece of C# that is DIFFERENT across versions.

    Pulled out into a separate function not for elegance but so the seam can
    be seen and checked by a test separately from the rest of the body: six
    targets are six checks of one spot, not six checks of one text.

    Version unknown/unparsable ⇒ the 2022+ branch is taken: this is NOT a
    guess at "more recent", but a closed refusal in favor of the member that
    exists in FIVE of the six versions. The direct emitter draws the same
    seam at the same boundary (``authoring._emit_tag``: ``if ver >= "2022"``).
    """
    try:
        year = int(str(revit_version))
    except (TypeError, ValueError):
        year = TAG_MULTI_REFERENCE_SINCE
    block = (_TAG_TARGET_2021_CS if year < TAG_MULTI_REFERENCE_SINCE
             else _TAG_TARGET_2022_CS)
    # The spatial branch is ONE for both version branches: substituted here
    # rather than copied into each text (see _TAG_TARGET_SPATIAL_CS on what
    # the first copy cost).
    return block.replace("__TAG_TARGET_SPATIAL__", _TAG_TARGET_SPATIAL_CS)


def build_tag_extract_cs(element_ids: list[str], *,
                         revit_version: Any = None,
                         call_budget_ms: int = 20_000,
                         link_title: str | None = None) -> str:
    """The C# for one page of the tag stage, for a SPECIFIC Revit version.

    ``revit_version`` is not decoration and not an optional hint: a tag's
    target has no single member living across all six versions, and a body
    built with no version must be the one that will compile on the
    majority (see :func:`tag_target_block_cs`).

    An empty id list is NOT a reason to build a body that would walk the
    whole document: the stage is paged, and "no ids" means "nothing to
    read".

    ``link_title`` — read not the HOST, but its link with the given
    ``Document.Title``. The Revit version and the source are DIFFERENT
    questions: the version picks which API member is asked for the tag's
    target, the source picks which document is asked. Both arrive from
    outside, and neither is guessed.
    """
    quoted = ", ".join(_csharp_string(str(item)) for item in element_ids)
    body = _TAG_EXTRACT_BODY_CS
    body = body.replace("__TG_CALL_BUDGET_MS__", str(int(call_budget_ms)))
    body = body.replace("__TAG_IDS__", quoted)
    body = body.replace("__TAG_TARGET_BLOCK__",
                        tag_target_block_cs(revit_version))
    body = body.replace(
        "__ELEMENT_ID_OUT_OF_RANGE__", ELEMENT_ID_OUT_OF_RANGE_REASON)
    body = body.replace(
        "__TG_SCHEMA__", _csharp_string(TAG_EXTRACT_SCHEMA_VERSION))
    return (source_binding_cs(link_title) + "\n"
            + TAG_EXTRACT_HELPER_CS + body)


__all__ = [
    "TAG_CATEGORIES",
    "TAG_EXTRACT_SCHEMA_VERSION",
    "TAG_FAMILIES",
    "TAG_FAMILY_INDEPENDENT",
    "TAG_FAMILY_SPATIAL",
    "TAG_INDEX_SCHEMA_VERSION",
    "TAG_MULTI_REFERENCE_SINCE",
    "TAG_ORIENTATION_HORIZONTAL",
    "TAG_SUPPORTED_VERSIONS",
    "TagExtraction",
    "TagFailure",
    "TagPayloadError",
    "TagRecord",
    "build_tag_extract_cs",
    "extract_tags",
    "merge_tags",
    "tag_target_block_cs",
]
