"""Wave A2 location geometry extraction.

This module deliberately implements the Wave A brief's narrow geometry
contract: ``LocationCurve`` / ``LocationPoint`` plus an always-attempted
model-space bounding box.  Full B-Rep/mesh storage and reconstruction tiers
remain a later, separately proven wave.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .schema import GeometryKind, L0SchemaError, LocationCurveKind, Vec3


# This snippet is composed into the read-only category extractor after its
# ``__MM`` unit-conversion delegate has been declared.  It is an Execute-body
# fragment, not a standalone class.
GEOMETRY_HELPER_CS = r"""
Func<XYZ, double[]> __VecMM = (__p) => new double[] {
    __MM(__p.X), __MM(__p.Y), __MM(__p.Z)
};
// КВИТАНЦИЯ ЧТЕНИЯ (§18.2): у каждой независимой попытки прочитать поле есть
// свой исход, и «бросило» обязано отличаться от «нет такого у элемента».
//
// ЗАЧЕМ, И ЭТО НЕ ПРО ЗАПАС. Три попытки ниже независимы (принадлежность
// линии, габарит, положение), и до этой правки две из трёх были немы: у
// законного элемента, чей `get_BoundingBox` или `Location.Curve` бросает,
// строка уезжала `bbox_only` с null-полями — ПОБАЙТОВО той же, что у
// элемента, у которого положения и габарита действительно нет. Ниже по
// потоку это читается как факт о МОДЕЛИ, и элемент понижается или
// выбрасывается без пометки о неполноте захвата.
//
// ТРИ СОСТОЯНИЯ КЛЮЧА, тот же закон, что у `worksets_closed` и `census`:
//     ключа НЕТ   строка снята до этой волны — не мерили
//     []          мерили, ни одно чтение не бросило
//     [имена]     эти чтения бросили; их null — НАШ, а не модели
Action<Dictionary<string, object>, string> __GeomReadFailed = (__row, __field) =>
{
    object __slot = null;
    __row.TryGetValue("geom_read_failed", out __slot);
    var __failed = __slot as List<object>;
    if (__failed == null)
    {
        __failed = new List<object>();
        __row["geom_read_failed"] = __failed;
    }
    if (!__failed.Contains(__field)) __failed.Add(__field);
};
Action<Element, Dictionary<string, object>> __PutGeometry = (__e, __row) =>
{
    __row["geom_kind"] = "bbox_only";
    __row["geom_read_failed"] = new List<object>();
    __row["curve_kind"] = null;
    __row["p0_mm"] = null;
    __row["p1_mm"] = null;
    __row["rotation_deg"] = null;
    __row["bbox_min_mm"] = null;
    __row["bbox_max_mm"] = null;

    // ПРИНАДЛЕЖНОСТЬ ЛИНИИ: вид против плоскости построения.
    //
    // ЗАЧЕМ. Замерено 13.08.2026 на `k2_ar_rd_v7`: 9 407 элементов категории
    // `OST_Lines`, у ВСЕХ до единого пустой `type_name` и отсутствует
    // `level_name`; геометрия ЕСТЬ — 9 256 несут кривую с концами, 151
    // остались габаритом. То есть недостаёт РОВНО принадлежности, а не
    // формы: у линии есть где, но неизвестно ЧЬЯ. Модельная линия живёт на
    // плоскости построения, чертёжная — на виде; L0 не доносил НИ ТОГО, НИ
    // ДРУГОГО, и различить их было нечем НИ В КАКУЮ сторону. Из-за этого
    // главное число проекта публикуется полосой 72.70…89.24 вместо точки:
    // отнести 9 407 линий к модели или к отложенной документации нельзя.
    //
    // ТРИ СОСТОЯНИЯ, И ОНИ РАЗЛИЧИМЫ ПО ПОСТРОЕНИЮ — в этом весь смысл поля:
    //     ключа НЕТ          не снималось (не `CurveElement`, старый прогон)
    //     "view"/"sketch_plane"  снято и определено
    //     "none"             снято и НЕ определено: ни вида, ни плоскости
    //     "read_failed"      попытка была и бросила
    // «Не определено» обязано отличаться от «не спрашивали»: иначе пустое
    // поле читалось бы как факт о линии, а оно факт о нашем чтении.
    //
    // ПЕРЕСМОТР: если "none" окажется заметной долей, значит различитель не
    // тот — тогда искать у `CurveElementType`/`LineStyle`, а не расширять
    // молчание. Условие названо здесь, чтобы не выводить его заново.
    //
    // `OwnerViewId` объявлен у `Element`, `SketchPlane` — у `CurveElement`;
    // оба на 2021-2026, ловушек ни у того, ни у другого (индекс, 13.08).
    // Идентификатор берётся `ToString()` — единственная идиома, безопасная на
    // всех шести.
    try
    {
        var __ce = __e as CurveElement;
        if (__ce != null)
        {
            __row["line_owner_kind"] = "none";
            __row["line_owner_id"] = null;
            var __ov = __e.OwnerViewId;
            if (__ov != null && __ov != ElementId.InvalidElementId)
            {
                __row["line_owner_kind"] = "view";
                __row["line_owner_id"] = __ov.ToString();
            }
            else
            {
                SketchPlane __sp = null;
                try { __sp = __ce.SketchPlane; }
                catch
                {
                    __row["line_owner_kind"] = "read_failed";
                    __GeomReadFailed(__row, "sketch_plane");
                }
                if (__sp != null)
                {
                    __row["line_owner_kind"] = "sketch_plane";
                    __row["line_owner_id"] = __sp.Id.ToString();
                }
            }
        }
    }
    catch
    {
        __row["line_owner_kind"] = "read_failed";
        __GeomReadFailed(__row, "line_owner");
    }

    // The bbox attempt is independent of location extraction: a malformed
    // Location object must not suppress a valid bounding box.
    try
    {
        var __bb = __e.get_BoundingBox(null);
        if (__bb != null)
        {
            var __bboxMin = __VecMM(__bb.Min);
            var __bboxMax = __VecMM(__bb.Max);
            __row["bbox_min_mm"] = __bboxMin;
            __row["bbox_max_mm"] = __bboxMax;
        }
    }
    catch { __GeomReadFailed(__row, "bbox"); }

    try
    {
        var __lc = __e.Location as LocationCurve;
        if (__lc != null && __lc.Curve != null)
        {
            var __curveP0 = __VecMM(__lc.Curve.GetEndPoint(0));
            var __curveP1 = __VecMM(__lc.Curve.GetEndPoint(1));
            __row["geom_kind"] = "curve";
            // §18.1-следствие: сами КОНЦЫ ничего не говорят о том, что между
            // ними. Пока L0 писал только "curve", дуга и прямая были
            // неразличимы, и лифт спрямлял дугу хордой молча. Вид кривой
            // снимается здесь и стоит один каст на элемент.
            __row["curve_kind"] = ((__lc.Curve as Line) != null)
                ? "line"
                : (((__lc.Curve as Arc) != null) ? "arc" : "other");
            __row["p0_mm"] = __curveP0;
            __row["p1_mm"] = __curveP1;
            return;
        }
        var __lp = __e.Location as LocationPoint;
        if (__lp != null && __lp.Point != null)
        {
            // ТОЧКА ЗАПИСЫВАЕТСЯ ДО ПОПЫТКИ ПРОЧИТАТЬ ПОВОРОТ, и поворот стоит
            // под своим стражем. Порядок здесь — не стиль, а цена, замеренная
            // 29.07: `LocationPoint.Rotation` документирован Autodesk как
            // неподдерживаемый у части элементов (RevitAPI.xml, все шесть
            // версий, P:Autodesk.Revit.DB.LocationPoint.Rotation): "This
            // property is not supported for some elements supporting
            // LocationPoints, such as AssemblyInstances, Groups, ModelText,
            // Room, and SpotDimensions" — и бросает InvalidOperationException.
            //
            // Пока чтение стояло ПЕРЕД тремя присваиваниями внутри общего
            // catch, у таких элементов молча терялся не только поворот, но и
            // САМА ТОЧКА. Замер по 55 сохранённым прогонам четырёх зданий:
            // 12 369 помещений и 566 зон, у ВСЕХ до единого geom_kind
            // bbox_only и p0_mm null. Ни одно помещение ни в одной модели
            // никогда не получило свою точку.
            //
            // Правило то же, что и у групп (коммит 3f54267f): удостоверение
            // элемента — это то, что прочиталось; добавка, которая не
            // прочиталась, вправе стоить своего поля и ничего сверх него.
            var __point = __VecMM(__lp.Point);
            __row["geom_kind"] = "point";
            __row["p0_mm"] = __point;
            try
            {
                __row["rotation_deg"] = __lp.Rotation * 180.0 / Math.PI;
            }
            catch (Exception) { __GeomReadFailed(__row, "rotation"); }
        }
    }
    catch { __GeomReadFailed(__row, "location"); }
};
""".strip()


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise L0SchemaError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise L0SchemaError(f"{field_name} must be a finite number")
    return result


def _vec3(value: Any, field_name: str) -> Vec3:
    if (not isinstance(value, Sequence) or isinstance(value, (str, bytes))
            or len(value) != 3):
        raise L0SchemaError(f"{field_name} must contain exactly three numbers")
    return (
        _number(value[0], f"{field_name}[0]"),
        _number(value[1], f"{field_name}[1]"),
        _number(value[2], f"{field_name}[2]"),
    )


def _optional_vec3(value: Any, field_name: str) -> Vec3 | None:
    return None if value is None else _vec3(value, field_name)


@dataclass(frozen=True, slots=True)
class ExtractedGeometry:
    """Strict Python representation of the bridge geometry fragment."""

    geom_kind: GeometryKind
    p0_mm: Vec3 | None
    p1_mm: Vec3 | None
    rotation_deg: float | None
    bbox_min_mm: Vec3 | None
    bbox_max_mm: Vec3 | None
    # None = the bridge did not report the curve kind (row captured before
    # §18.1). A state distinct from "line": the guess "not stated means it
    # must be straight" was exactly that silent chord.
    curve_kind: LocationCurveKind | None = None
    # A READ RECEIPT, appended AT THE TAIL under the same law as `curve_kind`
    # above: the field order above it is a positional contract of code
    # already written. Three states, and the middle one is exactly why the
    # field exists:
    #     None      row captured before this wave: NOT MEASURED
    #     ()        measured, no read threw
    #     names     these reads threw — their null is OURS, not a fact about
    #               the model
    # The guess "empty means everything was read" was exactly that same
    # silence: an element with an unread `Location.Curve` used to leave
    # byte-for-byte as the same `bbox_only` as an element that truly has no
    # position.
    read_failed: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.read_failed is not None:
            if (not isinstance(self.read_failed, tuple)
                    or not all(isinstance(name, str) and name
                               for name in self.read_failed)):
                raise L0SchemaError(
                    "ExtractedGeometry.read_failed must be a tuple of "
                    "non-empty field names or None")
        if (self.bbox_min_mm is None) != (self.bbox_max_mm is None):
            raise L0SchemaError(
                "bbox_min_mm and bbox_max_mm must both be present or absent")
        if self.bbox_min_mm is not None and any(
                low > high
                for low, high in zip(self.bbox_min_mm, self.bbox_max_mm or ())):
            raise L0SchemaError("bbox min must not exceed bbox max")
        if self.curve_kind is not None and self.geom_kind is not \
                GeometryKind.CURVE:
            raise L0SchemaError(
                "curve_kind cannot accompany non-curve geometry")
        if self.geom_kind is GeometryKind.CURVE:
            if self.p0_mm is None or self.p1_mm is None:
                raise L0SchemaError("curve geometry requires p0_mm and p1_mm")
            if self.rotation_deg is not None:
                raise L0SchemaError("curve geometry cannot carry rotation_deg")
        elif self.geom_kind is GeometryKind.POINT:
            if self.p0_mm is None or self.p1_mm is not None:
                raise L0SchemaError("point geometry requires only p0_mm")
            # ROTATION ON A POINT IS OPTIONAL, and this is not a relaxation
            # but the correction of a false premise. The invariant "a point
            # must carry a rotation" was written in the confidence that
            # rotation is always available. Autodesk writes the opposite
            # (RevitAPI.xml, six versions): rooms, zones, groups, and model
            # text HAVE NO rotation, the read throws. Requiring the pair
            # forced emission to lose the point as well — measured 29.07:
            # 12 369 rooms and 566 zones across four buildings with not a
            # single point. The absence of rotation on such an element is a
            # FACT about the model; the lifter already knows how to refuse
            # typed when it needs a rotation (lift.py: "rotation is absent
            # from frozen L0"), and that is more honest than having no point
            # at all.
        elif any(value is not None for value in (
                self.p0_mm, self.p1_mm, self.rotation_deg)):
            raise L0SchemaError(
                "bbox_only geometry cannot carry point/curve fields")

    @property
    def capture_is_complete(self) -> bool:
        """Whether EVERYTHING that was attempted was read.

        A separate name rather than a comparison with emptiness:
        `read_failed is None` ("not measured") and `read_failed == ()`
        ("measured, clean") answer DIFFERENT questions, and the caller is
        not required to derive this every time. The unmeasured is NOT
        declared complete.
        """
        return self.read_failed == ()

    def to_element_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "geom_kind": self.geom_kind.value,
            "curve_kind": (
                self.curve_kind.value if self.curve_kind is not None else None),
            "p0_mm": list(self.p0_mm) if self.p0_mm is not None else None,
            "p1_mm": list(self.p1_mm) if self.p1_mm is not None else None,
            "rotation_deg": self.rotation_deg,
            "bbox_min_mm": (
                list(self.bbox_min_mm)
                if self.bbox_min_mm is not None else None),
            "bbox_max_mm": (
                list(self.bbox_max_mm)
                if self.bbox_max_mm is not None else None),
        }
        # 🔴 NOT MEASURED MEANS THE KEY IS ABSENT. Writing `[]` would erase
        # the third state on the very first write-read round trip, exactly
        # as is already done for `worksharing`/`worksets_closed` in the L0
        # header.
        if self.read_failed is not None:
            fields["geom_read_failed"] = list(self.read_failed)
        return fields


def parse_geometry(value: Mapping[str, Any]) -> ExtractedGeometry:
    """Validate a bridge row's geometry without coercing malformed shapes."""

    if not isinstance(value, Mapping):
        raise L0SchemaError("geometry row must be an object")
    try:
        kind = GeometryKind(value.get("geom_kind"))
    except (TypeError, ValueError) as exc:
        raise L0SchemaError(
            f"geom_kind is invalid: {value.get('geom_kind')!r}") from exc
    rotation = value.get("rotation_deg")
    raw_curve_kind = value.get("curve_kind")
    if raw_curve_kind is None:
        curve_kind = None
    else:
        try:
            curve_kind = LocationCurveKind(raw_curve_kind)
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"curve_kind is invalid: {raw_curve_kind!r}") from exc
    raw_read_failed = value.get("geom_read_failed")
    if raw_read_failed is None:
        read_failed: tuple[str, ...] | None = None
    else:
        if (not isinstance(raw_read_failed, Sequence)
                or isinstance(raw_read_failed, (str, bytes))):
            raise L0SchemaError(
                "geom_read_failed must be an array of field names")
        names: list[str] = []
        for item in raw_read_failed:
            if not isinstance(item, str) or not item:
                raise L0SchemaError(
                    "geom_read_failed entries must be non-empty strings")
            names.append(item)
        read_failed = tuple(names)
    return ExtractedGeometry(
        geom_kind=kind,
        read_failed=read_failed,
        curve_kind=curve_kind,
        p0_mm=_optional_vec3(value.get("p0_mm"), "p0_mm"),
        p1_mm=_optional_vec3(value.get("p1_mm"), "p1_mm"),
        rotation_deg=(
            None if rotation is None else _number(rotation, "rotation_deg")),
        bbox_min_mm=_optional_vec3(value.get("bbox_min_mm"), "bbox_min_mm"),
        bbox_max_mm=_optional_vec3(value.get("bbox_max_mm"), "bbox_max_mm"),
    )
