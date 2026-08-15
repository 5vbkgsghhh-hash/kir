"""Typed validation boundary for KIR authoring operations.

This module owns normalization and static refusal of authoring input.  It has
no emitter or live-execution authority: accepted values are handed to
``kukai.ir.authoring`` for deterministic C# emission.
"""
from __future__ import annotations

import json
import math
from typing import Any

from kukai.ir import docspace, faceref, relate, spec
from kukai.ir.diag import (
    Diagnostic,
    GROUND_BAD_SELECTOR,
    PARSE_EXCLUSIVE_FIELDS,
    PARSE_MISSING_FIELD,
    TYPE_BAD_TYPE,
    TYPE_BOUNDS,
)
from kukai.ir.emit_utils import ELEMENT_ID_MAX, is_finite_number
# Закон многоугольного профиля объявлен ОДИН РАЗ в geom (там же его
# происхождение и замер вреда). Здесь он ЧИТАЕТСЯ: прямой ход обязан
# отвергать ровно то, что обратный превращает в атом.
from kukai.ir.geom import (
    MAX_HOLE_RING_POINTS,
    MAX_HOLES,
    MAX_PATH_POINTS,
    MAX_RING_POINTS,
    MIN_PATH_POINTS,
    MIN_RING_AREA_MM2,
    MIN_RING_POINTS,
)


def _num(x) -> bool:
    return is_finite_number(x)


# Static coordinate sanity bound (audit F12): Revit's own workable model
# extent is ~16 km from origin; a coordinate beyond that is a unit/garbage
# error that previously sailed to a late Revit runtime refusal.  Refused
# statically here instead — same enforcement point as every numeric bound.
_COORD_LIMIT_MM = 16_000_000.0

# ``ref_dir`` selects Revit's WorkPlaneBased placement overload.  The
# operands below belong to the point/TwoLevelsBased lowering: today there is
# no measured Revit contract which composes them with that overload.  Keep
# the list at the validation/emission boundary so an explicit neutral value
# (``rotation_deg=0``/``mirrored=false``) cannot disappear merely because it
# happens to match a default.
PLACE_FAMILY_WORK_PLANE_UNSUPPORTED = (
    "rotation_deg",
    "mirrored",
    "hand_flipped",
    "facing_flipped",
    "top_level",
    "base_offset_mm",
    "top_offset_mm",
)

#: Потолок длины `create_text.content`.
#:
#: ЧТО ЗАМЕРЕНО (02.08.2026, `k2_ar_rd_v8`, 59-этажная башня): 2 697 текстовых
#: примечаний, максимум **4 763 символа**, девять штук длиннее прежнего потолка
#: 2 000. Прежнее число пришло из `KIR_DOC_SPEC.md` — «content: непустой,
#: <= разумной длины» — то есть было написано РАССУЖДЕНИЕМ, и живое здание его
#: опровергло. Ровно тот класс дефекта, что `create_door.sill_mm min_val=0`
#: против 140 отрицательных отметок.
#:
#: ЧТО НЕ ЗАМЕРЕНО: собственный предел Revit на `TextNote.Text`. Он не
#: документирован, живым зондом не проверялся, и этот потолок его НЕ моделирует.
#: Здесь он защищает ЭМИССИЮ: одна операция не должна раздувать программу.
#: Поэтому запас взят с четырёхкратным перекрытием измеренного максимума —
#: и как только предел Revit будет измерен, ЭТО ЧИСЛО ОБЯЗАНО быть заменено
#: измеренным, а не подвинуто ещё раз рассуждением.
_TEXT_CONTENT_MAX_CHARS = 20_000


def _pt_ok(v, dims=(2, 3)) -> bool:
    return (isinstance(v, list) and len(v) in dims
            and all(_num(c) and abs(c) <= _COORD_LIMIT_MM for c in v))


def _dist(a, b) -> float:
    dz = (a[2] if len(a) > 2 else 0) - (b[2] if len(b) > 2 else 0)
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + dz ** 2)


#: Минимальная длина отрезка (мм). Ниже — Revit сам откажет ShortCurveTolerance,
#: и отказ придёт из транзакции вместо компиляции.
_MIN_SEGMENT_MM = 1.0


def reject_zero_length(p0, p1, op_name: str, i, oid, diags: list) -> bool:
    """«длина ~0 (p0==p1)» — ОДНА реализация на две стадии.

    Литеральные концы проверяются здесь, на validate. Концы, приехавшие
    адресом от осей, известны только после ground — и тот же закон вызывается
    оттуда (`ground.ground`), а не переписывается заново. Правило, написанное
    дважды, расходится в одном из двух мест; вызванное дважды — нет.
    """
    if _dist(p0, p1) >= _MIN_SEGMENT_MM:
        return True
    diags.append(Diagnostic(
        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="p1_mm",
        message_ru=f"{op_name}: длина ~0 (p0==p1)"))
    return False


# Endpoint agreement tolerance between the arc dict and p0_mm/p1_mm (mm). The
# endpoints stay the wall's grounding/hosting anchor; the arc supplies the
# bulge. Kept loose enough for round-tripped float noise (LOT31 capture drifts
# <1e-6 mm) yet far below any real modelling tolerance.
_ARC_ENDPOINT_TOL_MM = 1.0


def _arc_endpoints_mm(arc: dict) -> tuple[tuple[float, float, float],
                                          tuple[float, float, float]]:
    """The two world-mm endpoints implied by a canonical Arc dict, evaluated
    the same way Revit's Arc.Create parameterises: P(t)=C + r(cos t·X + sin t·Y)
    at the start and end angle. Used only to cross-check p0_mm/p1_mm."""
    c = arc["center_mm"]
    r = float(arc["radius_mm"])
    xa = arc["x_axis"]
    ya = arc["y_axis"]
    out = []
    for ang in (float(arc["start_angle_rad"]), float(arc["end_angle_rad"])):
        ca, sa = math.cos(ang), math.sin(ang)
        out.append((
            c[0] + r * (ca * xa[0] + sa * ya[0]),
            c[1] + r * (ca * xa[1] + sa * ya[1]),
            c[2] + r * (ca * xa[2] + sa * ya[2]),
        ))
    return out[0], out[1]


def _validate_arc(v: dict, i: int, oid: str, p0, p1, diags: list):
    """Validate a canonical Arc dict via recompile's audited ArcCurve, then
    cross-check that its endpoints match p0_mm/p1_mm (either orientation).

    recompile owns every geometric invariant (unit axes, positive radius,
    (0,2*pi] span) — we never re-derive them here, keeping the arc law in ONE
    place. Returns the deduplicated canonical dict, or None on a diagnostic."""
    from kukai.ir.decompile import recompile
    required = {"curve_type", "center_mm", "radius_mm", "x_axis", "y_axis",
                "start_angle_rad", "end_angle_rad"}
    if set(v) != required or v.get("curve_type") != "Arc":
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="arc",
            expected=sorted(required), got=v,
            message_ru="arc — canonical Arc {center_mm, radius_mm, x_axis, "
                       "y_axis, start_angle_rad, end_angle_rad}"))
        return None
    try:
        curve = recompile.curve_from_dict(v, "arc")
    except recompile.GeometrySchemaError as exc:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="arc",
            got=v, message_ru=f"arc — недопустимая дуга: {exc}"))
        return None
    canonical = curve.to_dict()
    if p0 is not None and p1 is not None:
        a0, a1 = _arc_endpoints_mm(canonical)
        # Compare in the level PLAN plane (x/y) only: p0_mm/p1_mm carry no z
        # (the base level supplies it), while the arc's absolute z is its
        # capture elevation. Wall.Create projects the curve onto the base level,
        # so plan agreement is the correct, universal check — mirroring
        # _endpoint_check's three_d=False for the straight wall.
        def _xy(pt):
            return (pt[0], pt[1])
        # accept either endpoint orientation (Revit may store p0->p1 either way)
        forward = max(_dist(_xy(a0), _xy(p0)), _dist(_xy(a1), _xy(p1)))
        reverse = max(_dist(_xy(a0), _xy(p1)), _dist(_xy(a1), _xy(p0)))
        if min(forward, reverse) > _ARC_ENDPOINT_TOL_MM:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="arc",
                got=v, message_ru="arc: концы дуги не совпадают с p0_mm/p1_mm "
                                  f"(> {_ARC_ENDPOINT_TOL_MM} мм) — дуга и "
                                  "точки должны описывать одну кривую"))
            return None
    return canonical


#: Потолок радиуса винтового марша, мм. НЕ придуман и НЕ выведен рассуждением:
#: это ДОКУМЕНТИРОВАННАЯ граница самого API, дословно —
#: «The given value for radius must be greater than 0 and no more than 30000
#: feet» (ArgumentOutOfRangeException у `StairsRun.CreateSpiralRun`,
#: RevitAPI.xml, одинаково во всех шести поставляемых версиях). 30000 фут ×
#: 304.8 мм/фут = 9 144 000 мм РОВНО. Отказать здесь дешевле, чем узнать то же
#: самое исключением внутри StairsEditScope на устройстве пользователя.
_SPIRAL_RADIUS_MAX_MM = 30_000 * 304.8

#: Потолок охватываемого угла, градусы. ЧИСЛО НАЗНАЧЕНО, и вот чем именно оно
#: обосновано: путь марша — ОДНА дуга, а ограниченная дуга Revit по построению
#: не бывает длиннее полного оборота, поэтому «больше 360°» не является
#: винтовым маршем в смысле этого вызова. API верхней границы НЕ называет
#: (сказано лишь «includedAngle must be positive»), и низ он тоже не называет
#: числом: «The includedAngle doesn't satisfy riser restriction to generate
#: spiral run (probably it's too small)» — эта граница зависит от высоты
#: подступенка ТИПА лестницы и от перепада base→top, то есть офлайн неизвестна
#: ни нам, ни автору программы. Мы её НЕ моделируем и не выдумываем: снизу
#: стоит только документированное «строго положительный», а настоящий отказ
#: приходит от Revit и приходит громко.
_SPIRAL_MAX_INCLUDED_DEG = 360.0


def _validate_spiral(v: dict, i: int, oid: str, width_mm, diags: list):
    """Канонический словарь винтового марша -> нормализованный словарь|None.

    Форма ровно та, что принимает `StairsRun.CreateSpiralRun` (одинаковая на
    2021-2026), но в АВТОРСКИХ единицах KIR: миллиметры и ГРАДУСЫ. Радианы
    канонической дуги (`arc`) приезжают с обратного хода — их пишет прибор;
    сюда же пишет человек или модель, а весь остальной авторский угол в языке
    измеряется в градусах (`rotation_deg`, `slopes[].angle_deg`). Перевод в
    радианы делает эмиттер на КОМПИЛЯЦИИ, в C# тригонометрии не остаётся.

    Ключ `clockwise` обязателен и БЕЗ УМОЛЧАНИЯ намеренно: направление закрутки
    видно в модели с первого взгляда, и молча выбранное за автора «против
    часовой» — это ровно тот «тихо другой результат», ради запрета которого
    существует весь этот компилятор.
    """
    required = {"center_mm", "radius_mm", "start_angle_deg",
                "included_angle_deg", "clockwise"}
    if set(v) != required:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="spiral",
            expected=sorted(required), got=sorted(v),
            message_ru="spiral — {center_mm: [x,y], radius_mm, "
                       "start_angle_deg, included_angle_deg, clockwise}"))
        return None
    if not _pt_ok(v["center_mm"], dims=(2,)):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
            field_name="spiral.center_mm", got=v["center_mm"],
            message_ru="spiral.center_mm — точка [x,y] мм (отметку центра "
                       "даёт base_level, а не автор: у CreateSpiralRun Z "
                       "центра И ЕСТЬ базовая отметка марша)"))
        return None
    if not isinstance(v["clockwise"], bool):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
            field_name="spiral.clockwise", got=v["clockwise"],
            message_ru="spiral.clockwise — true (по часовой) или false"))
        return None
    for key in ("radius_mm", "start_angle_deg", "included_angle_deg"):
        if not _num(v[key]):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                field_name=f"spiral.{key}", got=v[key],
                message_ru=f"spiral.{key} — конечное число"))
            return None
    radius = float(v["radius_mm"])
    if not 0.0 < radius <= _SPIRAL_RADIUS_MAX_MM:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid,
            field_name="spiral.radius_mm", got=radius,
            expected=f"0 < radius_mm <= {_SPIRAL_RADIUS_MAX_MM}",
            message_ru=(f"spiral.radius_mm вне границ самого API: радиус "
                        f"обязан быть больше 0 и не больше "
                        f"{_SPIRAL_RADIUS_MAX_MM:.0f} мм (30000 футов)")))
        return None
    included = float(v["included_angle_deg"])
    if not 0.0 < included <= _SPIRAL_MAX_INCLUDED_DEG:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid,
            field_name="spiral.included_angle_deg", got=included,
            expected=f"0 < included_angle_deg <= {_SPIRAL_MAX_INCLUDED_DEG}",
            message_ru=(f"spiral.included_angle_deg — строго положительный "
                        f"угол не больше {_SPIRAL_MAX_INCLUDED_DEG:.0f}° "
                        f"(путь марша — ОДНА дуга, а дуга длиннее полного "
                        f"оборота не бывает; направление задаёт clockwise, а "
                        f"не знак угла)")))
        return None
    # ВЫВЕДЕННАЯ, А НЕ НАЗНАЧЕННАЯ ПРОВЕРКА. Марш создаётся с
    # `StairsRunJustification.Center` — той же, что и прямой, — а значит
    # дуга-путь идёт по СЕРЕДИНЕ марша и внутренняя кромка лежит на радиусе
    # `radius - width/2`. При `radius <= width/2` внутреннего края не
    # существует вовсе: это не узкая лестница, это не лестница. Ровно этот
    # случай API называет своим отказом «The radius is too small to generate
    # a spiral run at the given justification», и здесь он ловится ДО
    # StairsEditScope, из тех же двух чисел, которые уже есть у компилятора.
    if width_mm is not None and radius <= float(width_mm) / 2.0:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid,
            field_name="spiral.radius_mm", got=radius,
            expected=f"radius_mm > {float(width_mm) / 2.0}",
            message_ru=(f"spiral.radius_mm={radius:g} не больше половины "
                        f"width_mm={float(width_mm):g}: марш строится по "
                        f"середине (justification=Center), поэтому внутренняя "
                        f"кромка легла бы на радиус "
                        f"{radius - float(width_mm) / 2.0:g} мм — внутреннего "
                        f"края у такого марша нет")))
        return None
    return {"center_mm": [float(v["center_mm"][0]), float(v["center_mm"][1])],
            "radius_mm": radius,
            "start_angle_deg": float(v["start_angle_deg"]),
            "included_angle_deg": included,
            "clockwise": bool(v["clockwise"])}


def _impersonation_route(pspec, value) -> str | None:
    """Честная операция вместо запрещённой категории DirectShape, или None.

    Срабатывает ТОЛЬКО на перечислении, чей набор вариантов В ТОЧНОСТИ равен
    закрытой таблице категорий DirectShape: это и есть машинный признак «здесь
    действует запрет самозванства», и он не зависит ни от имени опа, ни от
    имени параметра. Оп, объявивший другой набор, никакого маршрута не
    получает — молчание тут дешевле, чем совет невпопад.
    """
    from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES, IMPERSONATION_ROUTES

    if not isinstance(value, str):
        return None
    if set(pspec.choices) != set(DIRECTSHAPE_CATEGORIES):
        return None
    return IMPERSONATION_ROUTES.get(value)


def _sel_shape_ok(sel) -> bool:
    if not isinstance(sel, dict):
        return False
    by = sel.get("by")
    if by == "family_type":
        if set(sel) != {"by", "category", "family_name", "type_name"}:
            return False
        return all(
            isinstance(sel.get(key), str) and bool(sel[key].strip())
            for key in ("category", "family_name", "type_name")
        )
    disambiguate_by = sel.get("disambiguate_by")
    if disambiguate_by is not None:
        if by not in ("name", "default"):
            return False
        if (not isinstance(disambiguate_by, dict)
                or set(disambiguate_by) != {"param", "value"}):
            return False
        pname, pvalue = (disambiguate_by.get("param"),
                         disambiguate_by.get("value"))
        if not isinstance(pname, str) or not pname.strip():
            return False
        if not (pvalue is None or isinstance(pvalue, (str, bool))
                or _num(pvalue)):
            return False
    if by == "default":
        allowed = {"by", "disambiguate_by"} if disambiguate_by is not None else {"by"}
        return set(sel) == allowed
    allowed = ({"by", "value", "disambiguate_by"}
               if disambiguate_by is not None else {"by", "value"})
    if set(sel) != allowed:
        return False
    value = sel.get("value")
    if by in ("name", "ref"):
        return isinstance(value, str) and bool(value.strip())
    if by == "element_id":
        return (not isinstance(value, bool) and isinstance(value, int)
                and 1 <= value <= ELEMENT_ID_MAX)
    return False


def _target_w_ok(sel) -> bool:
    """Write-target selector: pinned id or intra-program ref (SPEC DAG)."""
    if not isinstance(sel, dict) or set(sel) != {"by", "value"}:
        return False
    if sel.get("by") == "element_id":
        v = sel.get("value")
        return (not isinstance(v, bool) and isinstance(v, int)
                and 1 <= v <= ELEMENT_ID_MAX)
    if sel.get("by") == "ref":
        v = sel.get("value")
        return isinstance(v, str) and bool(v.strip())
    return False


#: ГДЕ вторая ступень селектора вообще законна — ИМЕНОВАННЫМ списком, а не
#: «везде, где `refs_w`». Грань — часть тела элемента; `move_elements.targets`
#: тоже `refs_w`, но «подвинуть грань» не значит ничего, и разрешить форму по
#: РОДУ параметра значило бы отгрузить бессмысленную операцию как побочный
#: эффект. Новый носитель добавляется сюда явно, вместе со своим эмиттером.
_FACE_SEL_SITES: frozenset = frozenset({("create_dimension", "refs")})


def _face_sel_key(sel: dict) -> tuple:
    """Ключ ТОЖДЕСТВА селектора грани — для той же проверки на повтор.

    Повтор запрещён по той же причине, что и у ступени 1: размер между гранью
    и ей же — нулевой размер. Две РАЗНЫЕ грани одного элемента при этом
    законны и обязаны различаться ключом, поэтому в ключ входит предикат."""
    inner = sel["of"]
    pred = sel["predicate"]
    return (faceref.BY_FACE, inner["by"],
            inner["value"].strip() if inner["by"] == "ref" else inner["value"],
            pred.get("side"),
            tuple(pred["normal"]) if "normal" in pred else None)


def _validate_refs_w_with_faces(v: list, *, name: str, param, oid: str, i: int,
                                lo: int, hi: int, reject_dupes: bool,
                                diags: list) -> list | None:
    """`refs_w`, в котором есть хотя бы один селектор ГРАНИ (ступень 2).

    Возвращает нормализованный список или None (отказы уже в `diags`).

    Порядок проверок выбран так, чтобы отказ называл СВОЮ причину: сперва
    «формы вообще нет» (флаг/носитель), потом форма каждого элемента, и лишь
    затем длина и повторы. Обратный порядок отвечал бы «список из 2..16
    селекторов element_id/ref» на верно написанную грань — то есть посылал бы
    ремонт не туда."""
    where = param.name
    if (name, param.name) not in _FACE_SEL_SITES:
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=i, op_id=oid, field_name=where,
            expected="element_id|ref", got=faceref.BY_FACE,
            message_ru=(
                f"{where}: селектор грани у операции «{name}» не принят — "
                f"грань адресует ЧАСТЬ ТЕЛА элемента, и смысл у этого есть "
                f"только там, где операция действительно связывается с "
                f"гранью. Носители названы поимённо: "
                f"{sorted(f'{o}.{p}' for o, p in _FACE_SEL_SITES)}")))
        return None
    if not faceref.face_ref_enabled():
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=i, op_id=oid, field_name=where,
            expected="element_id|ref", got=faceref.BY_FACE,
            message_ru=(
                f"{where}: селектор грани выключен флагом оператора "
                f"{faceref.FACE_REF_FLAG} (по умолчанию ВЫКЛ). Пока он "
                f"выключен, грань назвать нельзя: адресуй элемент целиком "
                f"({{\"by\": \"element_id\"|\"ref\"}}) — компилятор возьмёт "
                f"геометрическую ссылку сам, но КАКУЮ именно, программа не "
                f"назовёт")))
        return None
    if not (isinstance(v, list) and lo <= len(v) <= hi):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=where,
            expected=f"{lo}..{hi} селекторов", got=v,
            message_ru=f"{where} — список из {lo}..{hi} селекторов"))
        return None
    out: list[dict] = []
    keys: list[tuple] = []
    for j, x in enumerate(v):
        if faceref.is_face_sel(x):
            face = faceref.validate_face_sel(
                x, oid=oid, field=param.name, i=j,
                inner_ok=_target_w_ok, diags=diags)
            if face is None:
                return None
            if not param.ref_kinds and face["of"]["by"] == "ref":
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=f"{where}[{j}].of", expected="element_id", got=x,
                    message_ru=(f"{where}[{j}].of: intra-program ref не "
                                "разрешён типизированным контрактом "
                                "параметра")))
                return None
            # ВНУТРЕННИЙ СЕЛЕКТОР НОРМАЛИЗУЕТСЯ ТАК ЖЕ, КАК ВНЕШНИЙ, и это не
            # аккуратность. Обход графа компилятора идёт по НОРМАЛИЗОВАННЫМ
            # опам и сверяет `value` с id опов; ступень 1 обрезает пробелы
            # (ниже), а необрезанная ступень 2 дала бы KIR-L003 «ref не
            # указывает на более ранний оп» на ссылке, которая указывает —
            # диагноз, посылающий ремонт не туда.
            inner_sel = face["of"]
            face = dict(face, of={
                "by": inner_sel["by"],
                "value": (inner_sel["value"].strip()
                          if inner_sel["by"] == "ref" else inner_sel["value"])})
            out.append(face)
            keys.append(_face_sel_key(face))
        elif _target_w_ok(x):
            if not param.ref_kinds and x.get("by") == "ref":
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=where, expected="только element_id-селекторы",
                    got=v,
                    message_ru=(f"{where}: intra-program ref не разрешён "
                                "типизированным контрактом параметра")))
                return None
            val = x["value"].strip() if x["by"] == "ref" else x["value"]
            out.append({"by": x["by"], "value": val})
            keys.append((x["by"], val))
        else:
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                field_name=f"{where}[{j}]",
                expected='{by: element_id|ref} либо {by: face, of, predicate}',
                got=x,
                message_ru=(f"{where}[{j}] — селектор элемента "
                            "(element_id/ref) либо селектор грани")))
            return None
    if reject_dupes and len(set(keys)) != len(keys):
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=where, got=v,
            message_ru=(f"{where}: повторяющийся селектор — нулевой размер "
                        "размера недопустим")))
        return None
    return out


#: КИНДЫ, КОТОРЫЕ РАЗБИРАЕТ НЕ ЭТОТ ФАЙЛ — С АДРЕСОМ ТОГО, КТО РАЗБИРАЕТ.
#:
#: Список заведён ПРОТИВ ОПЕЧАТОК, поэтому он не «прочее», а перепись: каждый
#: ключ назван вместе с местом, где кинд действительно проверяется, и новый
#: ключ сюда нельзя дописать, не назвав такого места. Иначе список стал бы
#: ровно той дырой, которую замок ниже закрывает.
#:
#: Все четыре стоят ТОЛЬКО на опах семейства query, а `compiler._validate_op`
#: уходит в `validate()` лишь для `spec.WRITE_FAMILIES` — то есть сегодня они
#: до цикла ниже не доезжают вовсе. Записаны они потому, что это факт о
#: РАСКЛАДКЕ (кто чей судья), а не о сегодняшнем маршруте: перенос опа между
#: семействами не должен превращаться в молчание.
_KINDS_VALIDATED_ELSEWHERE: dict[str, str] = {
    "kind_enum": "compiler._validate_op -> _check_kind (query_count/query_list)",
    "filters": "compiler._validate_op -> _check_filters (query_count/query_list)",
    "fields": "compiler._validate_op, ветка `name == \"query_list\"`",
    "target": "compiler._validate_op, ветка `name == \"query_inspect\"`",
}


def _assert_kind_dispatched(p, op_name: str) -> None:
    """ЗАМОК ОТ ОПЕЧАТКИ В `ParamSpec.kind`.

    `kind` — ОТКРЫТАЯ строка: закрытого перечня у неё нет, `spec._lint_registry`
    её не проверяет (он про капабилити-клетки), и опечатка в новом кинде не
    падает нигде. Цепочка ниже — `if/elif` без хвоста, поэтому параметр с
    неузнанным киндом не просто «не проверен»: он не попадает и в `norm`, то
    есть уезжает дальше так, как будто автор его не писал. Отказ бы это
    заметил, тишина — нет.

    Исключение — ошибка ПРОГРАММИСТА, а не автора программы, поэтому здесь
    `AssertionError`, а не `Diagnostic`: диагностика сказала бы пользователю,
    что виноват он, и отказала бы в верной программе. Тот же приём и по той же
    причине уже стоит в `schema_gen` (`unknown param kind`) и в `dsl` — этот
    третий замок нужен потому, что первые два защищают ЧУЖИЕ проходы: до
    07.08 опечатка ловилась только если кто-то сгенерирует схему.
    """
    if p.kind in _KINDS_VALIDATED_ELSEWHERE:
        return
    if p.kind in ("pt_xy", "pt_xyz") and p.name in ("p0_mm", "p1_mm"):
        # Концы отрезка НАМЕРЕННО выведены из первой ветви цикла: пара
        # проверяется и нормализуется ЦЕЛИКОМ до цикла (там же живёт закон
        # «длина ~0», которому нужны обе точки сразу). Ветвь по одной точке
        # разрезала бы этот закон пополам.
        return
    raise AssertionError(
        f"{op_name}.{p.name}: вид {p.kind!r} не разбирает ни одна ветвь "
        f"`authoring_validation.validate`, и в `norm` параметр не попадёт — "
        f"опечатка в `ParamSpec.kind` либо новый вид без ветви. Если вид "
        f"разбирается в другом файле, назовите его в "
        f"`_KINDS_VALIDATED_ELSEWHERE` вместе с адресом разбора")


def validate(op: dict, name: str, i: int, oid: str, diags: list) -> dict:
    """Structural typecheck for authoring ops; deep resolution is ground.py's."""
    norm: dict[str, Any] = {"op": name, "id": oid}
    ospec = spec.OPS[name]
    has_pts = any(pp.name == "p0_mm" for pp in ospec.params)
    endpoint_spec = next((p for p in ospec.params if p.name == "p0_mm"), None)
    dims = (3,) if endpoint_spec and endpoint_spec.kind == "pt_xyz" else (2,)
    # Концы отрезка могут быть НЕОБЯЗАТЕЛЬНЫМИ (place_family: либо точка,
    # либо кривая). До 27.07 каждый p0_mm/p1_mm в реестре был required=True,
    # поэтому отсутствие значения не отличали от значения неверной формы — и
    # необязательная пара давала «p0_mm — точка в мм» на программе, где
    # кривой нет и не должно быть. Пропуск повторяет ту же оговорку
    # `if v is None and not p.required`, что несколькими строками ниже:
    # обязательная пара по-прежнему проверяется дословно.
    _pt_required = {
        pp.name: pp.required for pp in ospec.params
        if pp.name in ("p0_mm", "p1_mm")}
    # RELATE (04.08): адресуемость параметра — вопрос к РЕЕСТРУ, а не к списку
    # здесь. `relate.addressable_params` выводит её из рода pt_xy/pt_xyz с
    # одним НАЗВАННЫМ исключением (`move_elements.delta_mm` — смещение, а не
    # положение). Свой список стал бы четвёртым судьёй и разошёлся бы на
    # первом же новом опе.
    _addressable = relate.addressable_params(name)
    for key in (("p0_mm", "p1_mm") if has_pts else ()):
        v = op.get(key)
        if v is None and not _pt_required.get(key, True):
            continue
        if relate.is_address(v) and key in _addressable:
            if relate.validate_address(v, oid, key, diags,
                                       dims=_addressable[key]):
                norm[key] = v
            continue
        if not _pt_ok(v, dims=dims):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=key,
                expected=f"[x,y{',z' if dims == (3,) else ''}] мм (числа)", got=v,
                message_ru=f"{key} — точка в мм"))
        else:
            norm[key] = v
    # Закон «длина ~0» — чистая функция от ЧИСЕЛ, и когда числа приезжают из
    # снапшота, он обязан переехать за ту же черту, а не потеряться. Второй
    # вызов той же функции стоит в `ground` (одна реализация, две площадки);
    # прибор, который молчит на части диапазона, опаснее отсутствующего.
    if ("p0_mm" in norm and "p1_mm" in norm
            and not relate.is_address(norm["p0_mm"])
            and not relate.is_address(norm["p1_mm"])):
        reject_zero_length(norm["p0_mm"], norm["p1_mm"], name, i, oid, diags)
    for p in ospec.params:
        if p.kind in ("pt_xy", "pt_xyz") and p.name not in ("p0_mm", "p1_mm"):
            v = op.get(p.name)
            if relate.is_address(v) and p.name in _addressable:
                if relate.validate_address(v, oid, p.name, diags,
                                           dims=_addressable[p.name]):
                    norm[p.name] = v
                continue
            # wave/struct (2026-07-17): OPTIONAL pt_xy/pt_xyz — needed for
            # create_foundation's kind-discriminated xy (isolated-only;
            # absent for kind=slab). Every PRE-EXISTING pt_xy/pt_xyz param
            # across the registry is required=True, so an omitted value was
            # never legitimately None before this — this None-skip mirrors
            # the mm/sel/str kinds' own "if v is None: continue" convention
            # a few lines below and changes nothing for any required param
            # (still validated exactly as before when present or missing-
            # but-required, since required-ness is enforced at ground.py for
            # sel and implicitly by this same _pt_ok check for a REQUIRED
            # pt_xy/pt_xyz — None only reaches here for an optional one).
            if v is None and not p.required:
                continue
            d2 = (3,) if p.kind == "pt_xyz" else (2,)
            if not _pt_ok(v, dims=d2):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="точка в мм", got=v,
                    message_ru=f"{p.name} — точка [x,y{',z' if d2 == (3,) else ''}] мм"))
            # move_elements.delta_mm (28.07 SRC PIN, live schema_gen
            # collision): reuses pt_xyz's SCHEMA-recognized shape (schema_gen
            # is exhaustive/foreign-dirty — no new kind), but it is a
            # DISPLACEMENT, not an absolute position, so the generic
            # _COORD_LIMIT_MM (16 000 000mm workable-extent bound) is the
            # wrong ceiling — the design's own 100_000mm (100m) per-
            # component bound is tighter, and only applies to this op/param.
            elif name == "move_elements" and p.name == "delta_mm" \
                    and not all(_num(c) and abs(c) <= 100_000 for c in v):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="[dx,dy,dz] мм, |компонент| <= 100000", got=v,
                    message_ru=f"{p.name} — вектор [dx,dy,dz] мм, "
                               "|компонент| не более 100000"))
            elif name == "move_elements" and p.name == "delta_mm" \
                    and all(float(c) == 0.0 for c in v):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru=f"{p.name}: нулевой перенос — переносить нечего"))
            # wave/mass (2026-08-10): create_face_wall.face_normal — тот же
            # приём, что у `delta_mm` строкой выше, и по той же причине
            # (`schema_gen` исчерпывающий, форма [x,y,z] уже распознаётся, а
            # новый род ради значения той же формы стоил бы правки в каждом
            # потребителе схемы). Отличие от переноса — в ЕДИНИЦАХ: это
            # НАПРАВЛЕНИЕ, а не миллиметры, поэтому потолок координат
            # (_COORD_LIMIT_MM, рабочая протяжённость модели) к нему не
            # применяется вовсе — у направления нет длины, значимой для
            # операции, оно нормируется в Revit.
            #
            # ОТВЕРГАЕТСЯ РОВНО ОДНО: ТОЧНЫЙ НОЛЬ. Это не порог и не допуск,
            # а вырожденность по определению — направления в [0,0,0] нет ни
            # в какой системе. «Почти нулевой» вектор здесь НЕ трогается
            # намеренно: где проходит эта граница, знает только Revit, и он
            # отвечает на неё своим `XYZ.IsZeroLength()` уже в рантайме
            # (эмиссия `faceref.resolve_cs` ставит там типизированный отказ).
            # Назначить порог здесь значило бы завести число, которого никто
            # не мерил, рядом с числом, которое Revit сообщает сам.
            elif name == "create_face_wall" and p.name == "face_normal" \
                    and all(_num(c) and float(c) == 0.0 for c in v):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected="ненулевой вектор [x,y,z]", got=v,
                    message_ru=(f"{p.name}: нулевой вектор — направления в "
                                f"[0,0,0] нет, называть грань нечем")))
            else:
                norm[p.name] = v
        elif p.kind == "mm":
            v = op.get(p.name, p.default)
            if v is None:
                # Same PRE-EXISTING GAP class as the str-kind branch above:
                # a MISSING required mm param (create_window/door.offset_mm
                # are already required=True — same latent bug, just never
                # exercised by an existing negative test; create_type.width_mm
                # is the one that surfaced it) used to `continue` silently and
                # panic emit-side with a raw KeyError instead of a typed
                # refusal. Fixed for every required mm param, additive.
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            if not _num(v):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="число (мм)", got=v, message_ru=f"{p.name} — число в мм"))
            elif ((p.min_val is not None and v < p.min_val)
                  or (p.max_val is not None and v > p.max_val)):
                if p.min_val is None:
                    expected = f"<= {p.max_val}"
                    replacement = p.max_val
                elif p.max_val is None:
                    expected = f">= {p.min_val}"
                    replacement = p.min_val
                else:
                    expected = f"{p.min_val}..{p.max_val}"
                    replacement = min(max(v, p.min_val), p.max_val)
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=expected, got=v,
                    suggested_replacement=replacement,
                    applicability="maybe-incorrect",
                    message_ru=f"{p.name} вне границ {expected} мм"))
            else:
                norm[p.name] = float(v)
        elif p.kind == "deg":
            # Additive angle kind: keep an omitted default implicit so old
            # normalized programs, program hashes and emitted C# do not move.
            # Explicit values remain in degrees and are compared modulo 2*pi
            # by the live postcondition.
            #
            # ОБЯЗАТЕЛЬНОСТЬ РОДА `deg` ДО 10.08.2026 БЫЛА НЕИСПОЛНИМА. Эта
            # ветка выходила по `not in op` РАНЬШЕ, чем кто-либо спрашивал
            # `p.required`, то есть `required=True` у угла был обещанием,
            # которого валидатор не держал: программа без обязательного угла
            # доезжала до эмиттера и падала там KeyError'ом (KIR-P000
            # «внутренняя ошибка») вместо названного отказа. Пока все углы
            # реестра были необязательными (`rotation_deg`, default=0.0),
            # дыра не наблюдалась — ровно «прибор на часть диапазона».
            # Волна армирования принесла первый обязательный угол
            # (`create_area_reinforcement.direction_deg`: главное направление
            # рабочей арматуры, умолчания у него нет и быть не должно), и
            # дыра стала достижимой. Правка АДДИТИВНА: у необязательных углов
            # ничего не меняется ни на байт.
            if p.name not in op:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, expected="конечное число (градусы)",
                        message_ru=f"{p.name} обязателен — угол в градусах"))
                continue
            v = op.get(p.name)
            if not _num(v):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name, expected="конечное число (градусы)",
                    got=v, message_ru=f"{p.name} — угол в градусах"))
            else:
                norm[p.name] = float(v)
        elif p.kind == "sel":
            sel = op.get(p.name)
            if sel is None:
                # Requiredness is a property of the authored program, not of
                # the model snapshot.  Program-envelope defaults have already
                # been applied before this validator runs, so an absent value
                # here cannot become valid during grounding.  Deferring the
                # refusal used to let PlannedProgram represent an impossible
                # program and made the same input fail at a different stage
                # depending on whether a caller happened to invoke ground().
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected="обязательный селектор",
                        message_ru=f"{p.name} обязателен"))
                continue
            if not _sel_shape_ok(sel):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"by": "name|element_id|default", "value": "..."}, got=sel,
                    message_ru=f"{p.name} — селектор"))
            elif (sel.get("by") == "family_type"
                  and not (name == "place_family" and p.name == "symbol")):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected={"by": "name|element_id|default"}, got=sel,
                    message_ru=("family_type поддержан только для "
                                "place_family.symbol")))
            elif sel.get("by") == "ref" and not p.ref_kinds:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"by": "name|element_id|default"}, got=sel,
                    message_ru=(f"{p.name}: intra-program ref не разрешён "
                                "типизированным контрактом параметра; "
                                "используйте element_id/каталожный селектор")))
            else:
                norm[p.name] = dict(sel)
                if sel.get("by") == "family_type":
                    for key in ("category", "family_name", "type_name"):
                        norm[p.name][key] = sel[key].strip()
                if sel.get("by") in ("name", "ref"):
                    norm[p.name]["value"] = sel["value"].strip()
                if "disambiguate_by" in sel:
                    norm[p.name]["disambiguate_by"] = dict(sel["disambiguate_by"])
                    norm[p.name]["disambiguate_by"]["param"] = \
                        sel["disambiguate_by"]["param"].strip()
        elif p.kind == "sel_list":
            # Множественное число рода `sel` (wave/datums): список селекторов
            # ОДНОГО пула.  Форма каждого элемента проверяется тем же
            # `_sel_shape_ok`, что и одиночный селектор, — одна реализация,
            # две площадки; свой разбор разошёлся бы с `sel` на первом же
            # новом виде селектора.
            v = op.get(p.name)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected="список селекторов (1..64)", got=v,
                        message_ru=f"{p.name} — список селекторов"))
                continue
            if not (isinstance(v, list) and 1 <= len(v) <= 64
                    and all(_sel_shape_ok(s) for s in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected="список из 1..64 селекторов", got=v,
                    message_ru=f"{p.name} — список из 1..64 селекторов"))
                continue
            bad_ref = next((s for s in v
                            if s.get("by") == "ref" and not p.ref_kinds), None)
            bad_ft = next((s for s in v if s.get("by") == "family_type"), None)
            if bad_ref is not None or bad_ft is not None:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected={"by": "name|element_id|default"},
                    got=bad_ref if bad_ref is not None else bad_ft,
                    message_ru=(f"{p.name}: селектор такого вида здесь не "
                                "разрешён — имя, element_id или default")))
                continue
            out_sels = []
            for s in v:
                one = dict(s)
                if s.get("by") in ("name", "ref"):
                    one["value"] = s["value"].strip()
                if "disambiguate_by" in s:
                    one["disambiguate_by"] = dict(s["disambiguate_by"])
                    one["disambiguate_by"]["param"] = \
                        s["disambiguate_by"]["param"].strip()
                out_sels.append(one)
            # ПОВТОР — ОТКАЗ, А НЕ ТИХАЯ СКЛЕЙКА.  Множество, в которое один
            # уровень попал дважды, неотличимо от множества, где его назвали
            # один раз; но программа, написавшая его дважды, почти наверняка
            # имела в виду ДВА разных уровня и ошиблась в имени.  Молча
            # схлопнув, мы построили бы лестницу не на том числе этажей, чем
            # просили, и свидетель равенства множеств это бы ПРОПУСТИЛ.
            seen: list = []
            for one in out_sels:
                key = json.dumps(one, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid,
                        field_name=p.name,
                        message_ru=(f"{p.name}: селектор повторён "
                                    f"({one.get('value', one.get('by'))}) — "
                                    "повтор в множестве неотличим от "
                                    "опечатки в имени соседа")))
                    break
                seen.append(key)
            else:
                norm[p.name] = out_sels
        elif p.kind == "num":
            v = op.get(p.name)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            if not _num(v):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="число", got=v, message_ru=f"{p.name} — число"))
            elif not (p.min_val <= v <= p.max_val):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"{p.min_val}..{p.max_val}", got=v,
                    message_ru=f"{p.name} вне границ"))
            else:
                norm[p.name] = float(v)
        elif p.kind == "target_w":
            sel = op.get(p.name)
            if sel is None and not p.required:
                # Optional target_w (Documentation family: dim_type/tag_type/
                # text_type/leader_to) — absence is a legal "use doc default"
                # signal, handled in-emit (IN_EMIT_DEFAULT pattern), NOT a
                # missing-selector diagnostic (that would wrongly reject every
                # program that omits an optional catalog type).
                continue
            # «host — только ref» родом от двери и окна: их хост обязан
            # строиться этой же программой. У ячейки витража это не так —
            # дизайн 2026-07-28 пишет `host: ref|element_id` прямо в
            # сигнатуре: «поменяй панель вот в этом витраже» относится к
            # УЖЕ СУЩЕСТВУЮЩЕЙ стене, которую программа не создавала.
            # Правило сужено до опов, для которых оно было законом, а не
            # снято: у остальных ничего не изменилось.
            #
            # host: element_id (28.07, аудит — самый частый внешний сценарий:
            # «поставь окно в МОЮ стену»). Ref-путь НЕ трогается ни байтом —
            # ref остаётся единственно законным для ВСЕХ прочих target_w
            # host-полей (place_family по кривой и т.д.); сужено ДО
            # create_door/create_window, а не снято вообще. compiler.py (план-
            # стадия) ищет host.value в byid — таблице по id ОПОВ-СТРОК;
            # element_id — int, там его нет по построению, __host_wall__ не
            # прикрепляется, и compile-time проверка «offset за краем стены»
            # для этой ветки НЕ срабатывает. Закон не снят — он переехал в
            # рантайм (_emit_hosted: живое чтение LocationCurve хоста).
            # create_curtain_grid_line: тот же случай, что у ячейки —
            # раскладку правят и на СУЩЕСТВУЮЩЕМ витраже («добавь стойку в
            # эту стену»), а не только на созданном этой же программой.
            # create_railing: тот же случай, что у витражной ячейки и линии
            # разрезки — ограждение вешают и на СУЩЕСТВУЮЩУЮ лестницу («сделай
            # ограждение по этой лестнице»), а не только на созданную этой же
            # программой. Для обратного хода это вообще единственный
            # возможный вид ссылки: у поднятого из модели ограждения хозяин —
            # лестница с настоящим element_id, а опа-строки, которая её
            # создала, в программе нет и быть не может.
            # create_opening: тот же случай, что у ячейки витража, линии
            # разрезки и ограждения — и БОЛЕЕ ТОГО, основной. Проём режут в
            # том, что УЖЕ СТОИТ («сделай проём в этой плите»), а носитель,
            # построенный этой же программой, — частный случай. Требовать ref
            # значило бы запретить главный сценарий операции.
            # create_face_wall: тот же случай, и тоже ОСНОВНОЙ. Стену по
            # грани строят по массе, которая УЖЕ СТОИТ в модели («сделай
            # стену по этому скату»); масса, размещённая этой же программой
            # через place_family, — частный случай. Требовать ref значило бы
            # запретить главный сценарий операции.
            # create_wall_sweep / create_slab_edge: тот же случай, что у
            # проёма, и тоже ОСНОВНОЙ. Карниз вешают на стену, которая УЖЕ
            # СТОИТ («сделай поясок по этой стене»), капельник — по краю уже
            # построенной плиты. Носитель, созданный этой же программой, —
            # частный случай; требовать ref значило бы запретить главный
            # сценарий обеих операций.
            # create_area_reinforcement: тот же случай, что у проёма и
            # карниза, и тоже ОСНОВНОЙ. Армируют плиту, которая УЖЕ СТОИТ
            # («заармируй эту плиту»); плита, построенная этой же программой,
            # — частный случай. Требовать ref значило бы запретить главный
            # сценарий раздела КР.
            if p.name == "host" \
                    and name not in ("set_curtain_panel",
                                     "create_curtain_grid_line",
                                     "create_railing",
                                     "create_opening",
                                     "create_wall_sweep",
                                     "create_slab_edge",
                                     "create_area_reinforcement",
                                     "create_face_wall") \
                    and name not in ("create_door", "create_window") \
                    and isinstance(sel, dict) and sel.get("by") != "ref":
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=sel, message_ru="host в v1 — только ref на create_wall этой же программы"))
            # change_type.type: element_id ОБЯЗАТЕЛЕН в v1 (28.07, CLASH) —
            # НЕ ref (нет опа, создающего типы, кроме create_type — ref на
            # него годился бы, но это следующая волна, не самодеятельность
            # этой) и не имя (нет снапшот-пула по ВСЕМ категориям — тот же
            # честно объявленный пробел, что у panel_type, только там
            # компилятор может поискать ограниченным коллектором по ДВУМ
            # известным пространствам типов, а здесь категория цели заранее
            # не известна вообще ни одному пространству).
            elif p.name == "type" and name == "change_type" \
                    and isinstance(sel, dict) and sel.get("by") != "element_id":
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"by": "element_id"}, got=sel,
                    message_ru="type в v1 — только element_id (нет снапшот-пула "
                               "типов по всем категориям)"))
            elif not _target_w_ok(sel):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"by": "element_id|ref", "value": "..."}, got=sel,
                    message_ru=f"{p.name} — селектор element_id или ref"))
            elif sel.get("by") == "ref" and not p.ref_kinds:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected={"by": "element_id"}, got=sel,
                    message_ru=(f"{p.name}: intra-program ref не разрешён "
                                "типизированным контрактом параметра")))
            else:
                value = sel["value"].strip() if sel["by"] == "ref" else sel["value"]
                norm[p.name] = {"by": sel["by"], "value": value}
        elif p.kind == "value":
            v = op.get(p.name)
            if isinstance(v, bool):
                norm[p.name] = {"type": "int", "v": 1 if v else 0}
            elif isinstance(v, str):
                if len(v) > 1000:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        message_ru="строка значения <=1000"))
                else:
                    norm[p.name] = {"type": "str", "v": v}
            elif isinstance(v, dict) and set(v) == {"workset"}:
                # РАБОЧИЙ НАБОР — НЕ ССЫЛКА, хотя выглядит как она. `Workset`
                # не наследует `Element`, `Parameter.Set(WorksetId)` не
                # существует (CS1503 на всех шести), и набор пишется ЦЕЛЫМ.
                # Свой род значения заведён намеренно: сложить его к `ref`
                # значило бы получить одну запись, живущую по другим правилам,
                # чем остальные, — и способность, которая ВЫГЛЯДИТ доказанной.
                name = v.get("workset")
                if not isinstance(name, str) or not name.strip():
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected={"workset": "имя рабочего набора"}, got=v,
                        message_ru="значение набора — {workset: <имя>}"))
                else:
                    norm[p.name] = {"type": "int_ref", "pool": "worksets",
                                    "by": "name", "v": name.strip()}
            elif isinstance(v, dict) and set(v) == {"phase"}:
                # ВТОРОЙ РОД ССЫЛКИ. Приём тот же, что у материала, и это
                # НАМЕРЕННО один приём, а не второй способ делать то же:
                # разошлись бы они на первом же роде, который придёт третьим.
                name = v.get("phase")
                if not isinstance(name, str) or not name.strip():
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected={"phase": "имя фазы"}, got=v,
                        message_ru="ссылочное значение — {phase: <имя>}"))
                else:
                    norm[p.name] = {"type": "ref", "pool": "phases",
                                    "by": "name", "v": name.strip()}
            elif isinstance(v, dict) and set(v) == {"material"}:
                # ССЫЛОЧНОЕ ЗНАЧЕНИЕ. Множество значений `set_param` было
                # закрыто на str|bool|число, и потому НЕДОСТИЖИМ был каждый
                # параметр со значением-ссылкой: материал, фаза, помещение,
                # уровень. Ветка открыта на материале — одном, а не на всех
                # четырёх: четыре сразу дали бы четыре недоказанных вместо
                # одного доказанного.
                #
                # ССЫЛКА АВТОРИТСЯ ЯВНО И НЕ ИМЕЕТ УМОЛЧАНИЯ. Опускаемое
                # значение разрешалось бы правилом `sole_entry`, которое не
                # ВЫБИРАЕТ, а констатирует безальтернативность: замерено
                # 12.08.2026 — на фикстуре так разрешаются 46 пар из 47, а на
                # настоящих зданиях 42 из 91 умолчания перестают работать.
                # Здесь этот выбор не создаётся ПО ПОСТРОЕНИЮ, а не по памяти
                # исполнителя.
                name = v.get("material")
                if not isinstance(name, str) or not name.strip():
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected={"material": "имя материала"}, got=v,
                        message_ru="ссылочное значение — {material: <имя>}"))
                else:
                    norm[p.name] = {"type": "ref", "pool": "materials",
                                    "by": "name", "v": name.strip()}
            elif isinstance(v, dict) and set(v) <= {"value", "unit"}:
                num, unit = v.get("value"), v.get("unit")
                if not _num(num) or unit not in ("mm", "raw"):
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                        expected={"value": "число", "unit": "mm|raw"}, got=v,
                        message_ru="числовое значение — {value, unit: mm|raw}"))
                elif unit == "mm" and not (-1_000_000 <= num <= 1_000_000):
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        got=num, message_ru="value(mm) вне границ ±1e6"))
                elif unit == "raw" and isinstance(num, int) \
                        and not (-0x80000000 <= num <= 0x7FFFFFFF):
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid,
                        field_name=p.name, got=num,
                        expected="32-битное целое -2147483648..2147483647",
                        message_ru=("raw integer не помещается в Revit Parameter.Set(int); "
                                    "для double передайте число с десятичной точкой")))
                elif unit == "raw" and isinstance(num, int):
                    norm[p.name] = {"type": "int", "v": num}
                else:
                    norm[p.name] = {"type": unit, "v": float(num)}
            elif _num(v):
                # bare numbers are BANNED: unit ambiguity is the R6 bug class
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, suggested_replacement={"value": v, "unit": "mm"},
                    applicability="maybe-incorrect",
                    message_ru="число без единиц запрещено — укажите {value, unit: mm|raw}"))
            else:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru="value — строка, bool или {value, unit}"))
        elif p.kind == "pts":
            v = op.get(p.name)
            # wave/struct: same optional-geometry None-skip as pt_xy/pt_xyz
            # above — create_foundation's outline (slab-only) is the first
            # non-required "pts" param in the registry (create_floor's own
            # outline is required=True).
            if v is None and not p.required:
                continue
            if not (isinstance(v, list)
                    and MIN_RING_POINTS <= len(v) <= MAX_RING_POINTS
                    and all(_pt_ok(pt, dims=(2,)) for pt in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f">={MIN_RING_POINTS} точек [x,y] мм", got=v,
                    message_ru=(f"{p.name} — контур из {MIN_RING_POINTS}.."
                                f"{MAX_RING_POINTS} точек")))
            else:
                area = abs(sum(v[k][0] * v[(k + 1) % len(v)][1]
                               - v[(k + 1) % len(v)][0] * v[k][1]
                               for k in range(len(v)))) / 2.0
                if area < MIN_RING_AREA_MM2:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        message_ru=f"{p.name}: вырожденный контур (площадь < 0.01 м²)"))
                else:
                    from kukai.ir.geom import ring_normalize
                    ring = ring_normalize(v, oid, p.name, diags)
                    if ring is not None:
                        norm[p.name] = ring
        elif p.kind == "pts_xyz":
            # ОБЛАКО ТОЧЕК ПОВЕРХНОСТИ (wave/site, 09.08.2026). Законы
            # ПОЛНОСТЬЮ статические (ни один не смотрит на модель), поэтому
            # выполняются здесь, а не на стадии ground, — как у `mesh` и в
            # отличие от `region`, которому нужны оси из снапшота. Владелец
            # законов один — geom.validate_points_xyz; здесь только вызов, и
            # это намеренно: второй набор правил о том же самом разъехался бы.
            v = op.get(p.name)
            if v is None and not p.required:
                continue
            if v is None:
                diags.append(Diagnostic(
                    code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                    field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            from kukai.ir.geom import validate_points_xyz
            pts = validate_points_xyz(v, oid, p.name, diags)
            if pts is not None:
                norm[p.name] = pts
        elif p.kind == "path":
            # ОТКРЫТАЯ ломаная (wave/arch): 2..64 точки, БЕЗ проверки площади
            # и БЕЗ ring_normalize. Две точки — законное прямое ограждение;
            # площадь у него ноль, и требовать её значило бы запретить самый
            # частый случай. Не required -> None пропускается: `path` нужен
            # только варианту variety="path" (условная обязательность
            # проверяется в arch_emit.emit_railing типизированным KIR-P005).
            v = op.get(p.name)
            if v is None and not p.required:
                continue
            if not (isinstance(v, list)
                    and MIN_PATH_POINTS <= len(v) <= MAX_PATH_POINTS
                    and all(_pt_ok(pt, dims=(2,)) for pt in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f">={MIN_PATH_POINTS} точек [x,y] мм", got=v,
                    message_ru=(f"{p.name} — ломаная из {MIN_PATH_POINTS}.."
                                f"{MAX_PATH_POINTS} точек")))
            else:
                # Вырожденное ЗВЕНО — отказ, а не тихая склейка. Порог 1 мм:
                # короткая кривая в Revit (~0.8 мм) не строится вовсе, и
                # выбросить такое звено молча значило бы вернуть в модель
                # ограждение другой формы, чем просили.
                bad = next((k for k in range(len(v) - 1)
                            if _dist(v[k], v[k + 1]) < 1.0), None)
                if bad is not None:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid,
                        field_name=p.name,
                        message_ru=(f"{p.name}: звено {bad}-{bad + 1} короче "
                                    f"1 мм (Revit такую кривую не строит)")))
                else:
                    norm[p.name] = [[float(pt[0]), float(pt[1])] for pt in v]
        elif p.kind == "path3":
            # ТРЁХМЕРНАЯ открытая ломаная (wave/mep-electrical): 2..64 точки
            # [x,y,z] мм. Отдельный род от `path`, а не его расширение: у
            # ограждения путь лежит НА уровне и третья координата была бы
            # ложной степенью свободы, а у гибкой подводки весь смысл как раз
            # в подъёме к потолку. Тот же довод, по которому create_beam
            # потребовал `pt_xyz` вместо `pt_xy`+уровень.
            v = op.get(p.name)
            if v is None and not p.required:
                continue
            if not (isinstance(v, list)
                    and MIN_PATH_POINTS <= len(v) <= MAX_PATH_POINTS
                    and all(_pt_ok(pt, dims=(3,)) for pt in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f">={MIN_PATH_POINTS} точек [x,y,z] мм", got=v,
                    message_ru=(f"{p.name} — трёхмерная ломаная из "
                                f"{MIN_PATH_POINTS}..{MAX_PATH_POINTS} точек")))
            else:
                # Совпадающие точки — ОТКАЗ, а не мелочь округления.
                # Autodesk пишет про Flex*.Create дословно: «Note the
                # duplicate points don't take into account» — то есть Revit
                # их ВЫБРАСЫВАЕТ и строит трассу с ДРУГИМ числом точек, чем
                # просили. Свидетель пути после этого честно упал бы, но
                # диагноз «геометрия не сошлась» назвал бы следствие вместо
                # причины, а причина видна уже здесь.
                bad = next((k for k in range(len(v) - 1)
                            if _dist(v[k], v[k + 1]) < _MIN_SEGMENT_MM), None)
                if bad is not None:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid,
                        field_name=p.name,
                        message_ru=(f"{p.name}: звено {bad}-{bad + 1} короче "
                                    f"{_MIN_SEGMENT_MM:g} мм — Revit считает "
                                    "такие точки совпадающими и выбрасывает "
                                    "их, то есть построил бы другую трассу")))
                else:
                    norm[p.name] = [[float(pt[0]), float(pt[1]), float(pt[2])]
                                    for pt in v]
        elif p.kind == "pts_list":
            v = op.get(p.name)
            if v is None or (isinstance(v, list) and not v):
                # Absent OR empty list ⇒ "no holes" (semantically identical).
                # The materializer emits holes=[] for hole-free floors/roofs; a
                # bare `is None` check refused every such op KIR-T001.  Do not
                # use truthiness here: False/0/""/{} are malformed payloads,
                # not an alternative spelling of an empty hole list (F29).
                continue
            if not (isinstance(v, list) and 1 <= len(v) <= MAX_HOLES
                    and all(isinstance(h, list)
                            and MIN_RING_POINTS <= len(h) <= MAX_HOLE_RING_POINTS
                            and all(_pt_ok(pt, dims=(2,)) for pt in h) for h in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    message_ru=(f"{p.name} — список контуров (каждый "
                                f"{MIN_RING_POINTS}..{MAX_HOLE_RING_POINTS} "
                                f"точек)")))
            else:
                from kukai.ir.geom import ring_normalize
                rings, bad = [], False
                for hi, h in enumerate(v):
                    r = ring_normalize(h, oid, f"{p.name}[{hi}]", diags)
                    if r is None:
                        bad = True
                        break
                    rings.append(r)
                if not bad:
                    norm[p.name] = rings
        elif p.kind == "enum":
            if p.name not in op and p.default is None and not p.required:
                continue          # an OPTIONAL enum with no default: absent
                                  # stays absent, exactly as the bool branch
                                  # below.  Without this the framework could
                                  # not express such a param at all —
                                  # ``op.get(name, None)`` is not in choices,
                                  # so every program omitting the field was
                                  # refused with a type error.
            v = op.get(p.name, p.default)
            if v not in p.choices:
                # МАРШРУТ ВМЕСТО «НЕЛЬЗЯ» (09.08). `ops_shape.IMPERSONATION_ROUTES`
                # описывает, ЧЕМ честно делается то, ради чего человек тянется к
                # запрещённой категории DirectShape (стена, перекрытие, кровля…).
                # Таблица существовала с 29.07 и имела НОЛЬ импортёров: закон был
                # записан и не произносился ни в одном отказе, а пользователь
                # получал сухое «одно из [generic_model, mass, …]» и не узнавал,
                # что нужная ему операция в KIR ЕСТЬ.
                #
                # Условие адресовано ТАБЛИЦЕ ВЫБОРА, а не имени опа: правило про
                # DirectShape-категории, и любой оп, объявивший ровно этот набор,
                # обязан отказывать одинаково. Имя опа здесь снова развело бы
                # закон и его носителей (ровно та починка, что уже была сделана
                # для рода `region` в ground.py).
                route = _impersonation_route(p, v)
                message = f"{p.name} — одно из {list(p.choices)}"
                if route is not None:
                    message += (f". Категория {v!r} тут запрещена намеренно: "
                                f"геометрия без BIM-смысла читалась бы «{v}» в "
                                f"каждом фильтре и каждой спецификации, не "
                                f"будучи ничем, чем этот элемент является. "
                                f"Это делается операцией {route}")
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=list(p.choices), got=v, message_ru=message))
            else:
                norm[p.name] = v
        elif p.kind == "slopes":
            # Parallel to `outline`, so the two are validated together: a
            # slope list of a different length silently pitches the wrong
            # edges, which is the kind of plausible-wrong this compiler exists
            # to refuse.
            if p.name not in op:
                continue
            v = op.get(p.name)
            ring = norm.get("outline") or op.get("outline") or []
            def _pitch_ok(x):
                return x is None or (
                    isinstance(x, (int, float)) and not isinstance(x, bool)
                    and 0.0 < float(x) < 90.0)
            if not (isinstance(v, list) and len(v) == len(ring)
                    and all(_pitch_ok(x) for x in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name, got=v,
                    expected=f"list of {len(ring)} entries, each null or 0<deg<90",
                    message_ru=f"{p.name} — по одному значению на ребро outline "
                               f"({len(ring)}), каждое null или угол 0..90 градусов"))
            elif not any(x is not None for x in v):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid,
                    field_name=p.name, got=v,
                    message_ru=f"{p.name} без единого угла — это плоская крыша, "
                               "просто не задавай поле"))
            else:
                norm[p.name] = [None if x is None else float(x) for x in v]
        elif p.kind == "bool":
            if p.name not in op:
                continue          # default stays implicit: program_hash/stamps
                                  # of pre-v1.1 programs must not shift
            v = op.get(p.name)
            if not isinstance(v, bool):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="true|false", got=v,
                    message_ru=f"{p.name} — булево"))
            else:
                norm[p.name] = v
        elif p.kind == "region":
            v = op.get(p.name)
            # Тот же None-пропуск для НЕобязательного, что у pt_xy/pts/path
            # выше. Он понадобился 09.08, когда `region` перестал быть только
            # обязательным полем create_floor_by_contour: у create_ceiling
            # эскиз — АЛЬТЕРНАТИВА прямому outline, и без этой строки
            # молчаливое отсутствие второго входа читалось как битый тип
            # (KIR-T001 на поле, которого автор не писал), а взаимная
            # обязательность (KIR-P007) до плана вообще не доживала.
            if v is None and not p.required:
                continue
            if not isinstance(v, dict):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru=f"{p.name} — объект {{outer, holes?}}"))
            else:
                norm[p.name] = v      # full laws run at ground (anchors need world)
        elif p.kind in ("graph_nodes", "graph_segments"):
            v = op.get(p.name)
            if not isinstance(v, list):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru=f"{p.name} — список"))
            else:
                norm[p.name] = v      # graph laws run once, cross-field, at ground
        elif p.kind == "mesh":
            # wave/shape. Законы формы меша ПОЛНОСТЬЮ статические (ни один из
            # них не смотрит на модель), поэтому они выполняются здесь, а не
            # на стадии ground, — в отличие от `region`, которому нужны оси из
            # снапшота. Валидатор либо возвращает нормализованный меш, либо
            # кладёт названный отказ; тихой правки входа у него нет.
            from kukai.ir.mesh import validate_mesh
            v = validate_mesh(op.get(p.name), oid, p.name, diags)
            if v is not None:
                norm[p.name] = v
        elif p.kind == "str":
            v = op.get(p.name)
            if v is None:
                # PRE-EXISTING GAP fixed here (found while gating load_family/
                # create_type's required str params): this branch used to
                # `continue` unconditionally, so a MISSING required str param
                # (e.g. set_param.param, also required=True) produced no
                # diagnostic at all and later panicked emit-side with a raw
                # KeyError (KIR-P000) instead of a typed refusal — the exact
                # class of bug the compiler-must-never-panic invariant bans.
                # Every pre-existing str param without this check was either
                # optional (name) or always supplied in every existing test
                # (set_param.param) — this closes the gap for both, additive.
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            # cap defaults to 64 (unchanged for every pre-existing str param,
            # all of which leave max_val unset); an op can opt into a wider
            # cap for genuinely long strings (load_family.path — Windows
            # MAX_PATH-class .rfa paths) via ParamSpec(..., max_val=N).
            cap = p.max_val if p.max_val is not None else 64
            if not isinstance(v, str):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=(f"строка <={cap}" if p.exact_string
                              else f"непустая строка <={cap}"),
                    got=v, message_ru=f"{p.name} — строка"))
            elif not p.exact_string and not v.strip():
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"непустая строка <={cap}", got=v,
                    message_ru=f"{p.name} — непустая строка"))
            elif len(v) > cap:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"строка <={cap}", got=v,
                    message_ru=f"{p.name} длиннее {cap} символов"))
            else:
                norm[p.name] = v if p.exact_string else v.strip()
        elif p.kind == "int":
            # ЦЕЛОЕ, а не «число, которое мы потом обрежем». Первый
            # авторский оп с этим видом — set_curtain_panel.u/v: адрес
            # ячейки. 1.5 не адрес; принять его и усечь значило бы выбрать
            # за автора соседнюю ячейку — ровно тот молчаливый выбор,
            # который этот компилятор запрещает. bool отсекается отдельно:
            # в Python True — это 1, а «истина» адресом не является.
            v = op.get(p.name, p.default)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            if isinstance(v, bool) or not isinstance(v, int):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="целое число", got=v,
                    message_ru=f"{p.name} — целое число"))
            elif (p.min_val is not None and v < p.min_val) \
                    or (p.max_val is not None and v > p.max_val):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"{p.min_val}..{p.max_val}", got=v,
                    message_ru=f"{p.name} вне границ {p.min_val}..{p.max_val}"))
            else:
                norm[p.name] = int(v)
        elif p.kind == "str_long":
            # Documentation family (create_text.content): a longer bound than
            # "str" (KIR_DOC_SPEC.md: "content: непустой, <= разумной длины"),
            # same json.dumps-escaping law as v1 (no separate rule needed here
            # — _cs() at emit time is the single escaping point).
            v = op.get(p.name)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid, field_name=p.name,
                        message_ru=f"{p.name} обязателен"))
                continue
            # Три РАЗНЫХ отказа, три разных сообщения. Склеенные в одно, они
            # врут: замер 02.08 на 59-этажной башне дал девять заметок длиннее
            # предела (максимум 4763 символа) — и все девять сообщили «content —
            # непустая строка», то есть отправили искать пустоту там, где её
            # не было. Диагностика, называющая не тот отказ, дороже отсутствия
            # диагностики: по ней чинят не то.
            if not isinstance(v, str):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="строка", got=v,
                    message_ru=f"{p.name} — строка (текст заметки)"))
            elif not v.strip():
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="непустая строка", got=v,
                    message_ru=(f"{p.name} пуст — текст примечания обязателен, "
                                "подставлять пустую строку значило бы выдумать "
                                "источник")))
            elif len(v) > _TEXT_CONTENT_MAX_CHARS:
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"<={_TEXT_CONTENT_MAX_CHARS} символов",
                    got=len(v),
                    message_ru=(f"{p.name} длиннее {_TEXT_CONTENT_MAX_CHARS} "
                                f"символов ({len(v)})")))
            else:
                norm[p.name] = v
        elif p.kind == "pt_view2d":
            # Documentation VIEW-SPACE law (KIR_DOC_SPEC.md): reuse docspace's
            # core, never reinvent it. A 3D point here is KIR-T001 by
            # construction (docspace.check_pt_view2d), not a truncation.
            v = op.get(p.name)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid, field_name=p.name,
                        message_ru=f"{p.name} обязателен — точка вида [u,v] мм"))
                continue
            # `docspace` импортирован на уровне модуля (строка 12); повторный
            # локальный импорт делал имя локальным на всю `validate`.
            pt = docspace.check_pt_view2d(v, oid, p.name, diags)
            if pt is not None:
                norm[p.name] = pt
        elif p.kind == "refs_w":
            # Documentation `refs` (create_dimension): >=2 write-target
            # selectors (element_id | intra-program ref), no two identical
            # (a dimension between an element and itself is a zero-size
            # refusal, same law as p0==p1 for walls/pipes/grids).
            #
            # move_elements.targets (28.07 SRC PIN, live schema_gen
            # collision): reuses this SAME kind — it is exactly "a list of
            # target_w selectors", and schema_gen.py's kind-switch is
            # exhaustive and foreign-dirty (cannot learn a new kind).  The
            # bound/dedup rule is looked up BY OP NAME, same discipline as
            # the beam/foundation dims-by-name branch above: create_dimension
            # keeps its ORIGINAL 2..16 + no-duplicates law untouched;
            # move_elements gets its own 1..500, duplicates ALLOWED (moving
            # the same element twice is harmless — Revit's ElementId
            # collection de-duplicates — not a zero-size-dimension hazard).
            # create_angular_dimension: EXACTLY two, and the bound is derived
            # from the API rather than picked — RevitAPI.xml requires the
            # references to be "rays of the arc passed", and the arc's vertex
            # is the intersection of the two referenced planes, a construction
            # a third plane has no place in (09.08).
            _refs_w_bounds = {
                "move_elements": (1, 500, False),
                "create_angular_dimension": (2, 2, True),
            }
            lo, hi, reject_dupes = _refs_w_bounds.get(name, (2, 16, True))
            v = op.get(p.name)
            # ВТОРАЯ СТУПЕНЬ СЕЛЕКТОРА (`{"by": "face", ...}`, `faceref.py`).
            #
            # ОТДЕЛЬНОЙ ВЕТКОЙ, А НЕ ВПЛЕТЕНИЕМ В ПРОВЕРКУ НИЖЕ, И ЭТО НЕ
            # СТИЛЬ. Закон флага: выключенным он обязан быть НЕОТЛИЧИМ от
            # отсутствия формы вовсе. Пока в списке нет ни одного селектора
            # грани, ниже исполняется ТОТ ЖЕ код, что и до этой правки, —
            # значит побайтовое совпадение эмиссии доказуемо структурой, а не
            # прогонкой (`test_faceref.py::FlagOffIsAbsentTests` проверяет обе
            # стороны). Вплетённое условие пришлось бы доказывать перебором.
            if isinstance(v, list) and any(faceref.is_face_sel(x) for x in v):
                norm_faces = _validate_refs_w_with_faces(
                    v, name=name, param=p, oid=oid, i=i,
                    lo=lo, hi=hi, reject_dupes=reject_dupes, diags=diags)
                if norm_faces is not None:
                    norm[p.name] = norm_faces
            elif not (isinstance(v, list) and lo <= len(v) <= hi
                    and all(_target_w_ok(x) for x in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"{lo}..{hi} селекторов {{by: element_id|ref, value: ...}}",
                    got=v, message_ru=f"{p.name} — список из {lo}..{hi} селекторов "
                                     "element_id/ref"))
            elif (not p.ref_kinds
                  and any(x.get("by") == "ref" for x in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected="только element_id-селекторы", got=v,
                    message_ru=(f"{p.name}: intra-program ref не разрешён "
                                "типизированным контрактом параметра")))
            else:
                keys = [(x["by"],
                         x["value"].strip() if x["by"] == "ref" else x["value"])
                        for x in v]
                if reject_dupes and len(set(keys)) != len(keys):
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        got=v, message_ru=f"{p.name}: повторяющийся ref — нулевой размер размера недопустим"))
                else:
                    norm[p.name] = [
                        {"by": x["by"],
                         "value": x["value"].strip() if x["by"] == "ref" else x["value"]}
                        for x in v]
        elif p.kind == "arc":
            # Curve-IR (P4-B): optional canonical Arc dict on create_wall.
            # Absent -> unchanged straight Line wall (program_hash/emitted C#
            # byte-stable). Present -> validated through the audited
            # recompile.ArcCurve invariants (single source of truth for
            # frame/radius/span), AND cross-checked so the arc endpoints match
            # p0_mm/p1_mm (which stay the grounding/hosting anchor).
            if p.name not in op:
                continue
            v = op.get(p.name)
            if not isinstance(v, dict):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru=f"{p.name} — объект дуги (canonical Arc)"))
                continue
            # RELATE + дуга — НЕ смешиваются, и это решение, а не пропуск.
            # Дуга задаётся центром, радиусом и углами; её концы обязаны
            # СОВПАСТЬ с p0_mm/p1_mm, и это сверяется прямо ниже. Если концы
            # приезжают из снапшота, сверять на validate нечего, а перенести
            # сверку в ground значило бы, что дуга при промахе по осям едет
            # мимо своих же концов. `arc` спекой прямо вынесен за v1 (§9.4).
            if any(relate.is_address(norm.get(k)) for k in ("p0_mm", "p1_mm")):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=sorted(k for k in ("p0_mm", "p1_mm")
                               if relate.is_address(norm.get(k))),
                    message_ru=(
                        f"{name}: дуга и адрес от осей вместе не выражаются — "
                        "концы дуги заданы её центром/радиусом/углами и обязаны "
                        "совпасть с p0_mm/p1_mm. Задайте концы дуговой стены "
                        "литералами [x, y]")))
                continue
            arc_norm = _validate_arc(v, i, oid, norm.get("p0_mm"),
                                     norm.get("p1_mm"), diags)
            if arc_norm is not None:
                norm[p.name] = arc_norm
        elif p.kind == "spiral":
            # Винтовой марш (09.08): АЛЬТЕРНАТИВА прямому p0_mm/p1_mm, не
            # добавка к нему. Отсутствие — исторический прямой марш байт в
            # байт; «оба сразу» и «ни одного» — типизированный KIR-P007 в
            # плане (взаимную обязательность схема выразить не может).
            # None-пропуск тот же, что у pt_xy/region выше.
            if p.name not in op or op.get(p.name) is None:
                continue
            v = op.get(p.name)
            if not isinstance(v, dict):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name, got=v,
                    message_ru=f"{p.name} — объект винтового марша "
                               "{center_mm, radius_mm, start_angle_deg, "
                               "included_angle_deg, clockwise}"))
                continue
            # width_mm уже нормализован: род `mm` стоит в реестре ВЫШЕ, а
            # проверка «радиус больше полуширины» читает оба числа сразу.
            spiral_norm = _validate_spiral(v, i, oid, norm.get("width_mm"),
                                           diags)
            if spiral_norm is not None:
                norm[p.name] = spiral_norm
        elif p.kind == "member_ops":
            # feat/native-groups: the group definition is 1..N create-authoring
            # ops at occurrence 0's absolute coordinates.  This first pass owns
            # container shape, identity and obvious capability exclusions.  The
            # compiler immediately runs every accepted member through the SAME
            # single-op planner as a top-level operation and binds its OpContract
            # into the parent plan; no component bridge is a validation trust
            # boundary.
            v = op.get(p.name)
            if not (isinstance(v, list) and 1 <= len(v) <= 200
                    and all(isinstance(m, dict) for m in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="список из 1..200 опов-членов", got=v,
                    message_ru=f"{p.name} — список опов-членов группы (1..200)"))
            else:
                ok = True
                seen_ids: set = set()
                for mi, m in enumerate(v):
                    mop = m.get("op")
                    mospec = spec.OPS.get(mop) if isinstance(mop, str) else None
                    if (mospec is None
                            or mospec.family != "authoring"
                            or mospec.effect.value != "create"
                            or mospec.result.identity_cardinality.value != "one"
                            or mop == "create_group"
                            or mop in spec.SOLO_OPS):
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}].op", got=mop,
                            message_ru=("член группы — одиночный create-authoring "
                                        "op с одним Element-результатом (не "
                                        "query/modify/delete/solo/create_group)")))
                        ok = False
                        continue
                    mid = m.get("id")
                    if not isinstance(mid, str) or not (1 <= len(mid) <= 64):
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}].id", got=mid,
                            message_ru="у члена группы должен быть строковый id"))
                        ok = False
                        continue
                    if mid in seen_ids:
                        diags.append(Diagnostic(
                            code=TYPE_BOUNDS, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}].id", got=mid,
                            message_ru=f"дублирующийся id члена группы {mid!r}"))
                        ok = False
                        continue
                    seen_ids.add(mid)
                    # Ссылка ВНУТРЬ группы законна; ссылка НАРУЖУ — нет.
                    #
                    # Лид-ревью №3 отказывало всякому `ref` внутри члена, и
                    # причина была верной ровно наполовину: ref на переменную
                    # ВНЕ неймспейса группы дал бы несуществующий `__el_*` и
                    # падение на компайл-гейте. Но ref на СОСЕДА ПО ТОЙ ЖЕ
                    # ГРУППЕ — не ссылка наружу: эмиттер именует членов
                    # `{oid}__m__{id}`, и достаточно переписать значение ссылки
                    # тем же именем (`authoring._emit_group`).
                    #
                    # **ЦЕНА СТАРОГО ОТКАЗА, ЗАМЕРЕНА 12.08.2026.** Дверь
                    # адресует свою стену ТОЛЬКО через `ref`, поэтому этаж со
                    # стенами И дверьми был негруппируем ПО ПОСТРОЕНИЮ — а
                    # именно так человек и собирает 59-этажный дом: **41.1%
                    # элементов настоящей башни живут внутри групп** (стены
                    # 94.9%, несущие колонны 100%, панели витража 99.3%, двери
                    # 91.4%; 2 941 экземпляр из 367 определений). Оставшейся
                    # формой было перечисление, и оно упиралось в потолок 300
                    # при медиане настоящего этажа 796 опов.
                    #
                    # Порядок членов проверяется здесь же и БЕСПЛАТНО:
                    # `seen_ids` — это ровно «члены, объявленные ВЫШЕ», поэтому
                    # ссылка назад проходит, ссылка вперёд отказывается с
                    # названной причиной. Автор естественно пишет стену раньше
                    # двери.
                    def _refs(node) -> list:
                        out: list = []
                        if isinstance(node, dict):
                            if node.get("by") == "ref":
                                out.append(node.get("value"))
                            g = node.get("__grounded__")
                            if isinstance(g, dict) and g.get("via") == "ref":
                                out.append(g.get("value"))
                            for x in node.values():
                                out.extend(_refs(x))
                        elif isinstance(node, list):
                            for x in node:
                                out.extend(_refs(x))
                        return out
                    body = {k: v2 for k, v2 in m.items() if k != "id"}
                    member_ids = {
                        str(other.get("id")) for other in v
                        if isinstance(other, dict) and other.get("id") is not None}
                    outside = [r for r in _refs(body)
                               if str(r) not in member_ids]
                    forward = [r for r in _refs(body)
                               if str(r) in member_ids and str(r) not in seen_ids]
                    if outside:
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}]", got=sorted(outside),
                            expected=sorted(member_ids),
                            message_ru=(
                                f"член группы ссылается НАРУЖУ группы: "
                                f"{sorted(outside)!r}. Внутри группы ссылаться "
                                f"можно только на её же членов "
                                f"({sorted(member_ids)!r}); на элементы вне "
                                f"группы — по element_id. СЛЕДУЮЩИЙ ХОД: либо "
                                f"внеси адресуемый элемент в members, либо "
                                f"замени ref на element_id")))
                        ok = False
                        continue
                    if forward:
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}]", got=sorted(forward),
                            message_ru=(
                                f"член группы ссылается на члена, объявленного "
                                f"НИЖЕ: {sorted(forward)!r}. Внутри группы "
                                f"порядок членов — это порядок создания. "
                                f"СЛЕДУЮЩИЙ ХОД: переставь адресуемого члена "
                                f"выше ссылающегося (стену раньше двери)")))
                        ok = False
                        continue
                if ok:
                    # Deep-copy so the emitter can safely namespace member ids
                    # under the group op id without mutating the caller's ops.
                    import copy as _copy
                    norm[p.name] = _copy.deepcopy(v)
        elif p.kind == "placements":
            # feat/native-groups: per-ADDITIONAL-occurrence offset deltas
            # [dx,dy,dz] (mm), each == occ_origin_k - occ_origin_0 (occurrence 0
            # is the members themselves, so an EMPTY list is legal — a group
            # placed once, or the definition-only degenerate the bridge refuses
            # upstream). Deltas may be [x,y] (z=0 implied) or [x,y,z].
            v = op.get(p.name)
            if not (isinstance(v, list) and len(v) <= 4096
                    and all(_pt_ok(d, dims=(2, 3)) for d in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="список смещений [dx,dy(,dz)] мм (0..4096)", got=v,
                    message_ru=f"{p.name} — список смещений [dx,dy,dz] в мм"))
            else:
                norm[p.name] = [
                    [float(d[0]), float(d[1]), float(d[2] if len(d) > 2 else 0.0)]
                    for d in v
                ]
        else:
            # ХВОСТ ЦЕПОЧКИ. Без него `if/elif` молча пропускает параметр
            # мимо всех проверок И мимо `norm` — см. `_assert_kind_dispatched`.
            _assert_kind_dispatched(p, name)
    if name == "create_extrusion_roof":
        # ХОД ВЫДАВЛИВАНИЯ — ОТРЕЗОК, А НЕ ПАРА ЧИСЕЛ. `start_mm >= end_mm`
        # это либо пустой ход (кровли не будет вовсе), либо перевёрнутый — и
        # второй случай опаснее: Revit, скорее всего, построит тот же объём,
        # а свидетель сравнивает МИНИМУМ проекции со `start_mm` и МАКСИМУМ с
        # `end_mm` и честно упадёт. Диагноз «выдавливание не то» назвал бы
        # СЛЕДСТВИЕ, а причина видна уже здесь, до всякой эмиссии.
        #
        # Порог НЕ НОВЫЙ: `_MIN_SEGMENT_MM` — тот же 1 мм, которым этот файл
        # уже отвергает вырожденное звено ломаной, с той же обоснованием
        # («короткая кривая в Revit ~0.8 мм не строится»). Заводить второе
        # число для той же физической величины значило бы завести второго
        # судью.
        a, b = norm.get("start_mm"), norm.get("end_mm")
        if (isinstance(a, (int, float)) and isinstance(b, (int, float))
                and float(b) - float(a) < _MIN_SEGMENT_MM):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="end_mm",
                expected=f"end_mm - start_mm >= {_MIN_SEGMENT_MM:g} мм",
                got=float(b) - float(a),
                message_ru=(
                    f"end_mm ({b}) не больше start_mm ({a}) хотя бы на "
                    f"{_MIN_SEGMENT_MM:g} мм — ход выдавливания пуст или "
                    "перевёрнут; это отрезок ВДОЛЬ нормали плоскости, и "
                    "начало обязано быть меньше конца")))
    if name == "set_curtain_panel":
        # У типа ячейки витража нет детерминированного правила «по
        # умолчанию»: ни doc-default (его в API нет), ни «единственная
        # запись пула» (пула нет — тип ячейки живёт в двух пространствах
        # типов). Отказ типизированный и НА РАЗБОРЕ, а не на эмиссии.
        selector = norm.get("panel_type")
        if isinstance(selector, dict) and selector.get("by") == "default":
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                field_name="panel_type",
                expected={"by": "name|element_id"}, got=selector,
                message_ru=("panel_type: у типа ячейки витража нет правила по "
                            "умолчанию — назовите тип или его element_id")))
    if name == "place_family" and "ref_dir" in op:
        # ``_emit_place`` routes to the WorkPlaneBased overload as soon as it
        # sees ref_dir.  Before this guard every explicit operand below was
        # accepted by the registry and then lost at that early return.  A
        # typed refusal is deliberately stricter than interpreting a neutral
        # explicit value as omission: source intent must never disappear.
        for field in PLACE_FAMILY_WORK_PLANE_UNSUPPORTED:
            if field not in op:
                continue
            diags.append(Diagnostic(
                code=PARSE_EXCLUSIVE_FIELDS,
                op_index=i,
                op_id=oid,
                field_name=field,
                expected=(f"{field} без ref_dir или ref_dir без "
                          f"{field}"),
                got=op[field],
                message_ru=(
                    f"place_family на рабочей плоскости: {field} "
                    "не имеет доказанного совместного lowering с "
                    "ref_dir; уберите один из операндов — компилятор не "
                    "будет молча игнорировать авторское поле")))
    if name in ("create_door", "create_window", "place_family"):
        raw_states = {
            key: op.get(key, False)
            for key in ("mirrored", "hand_flipped", "facing_flipped")
        }
        if ("mirrored" in op
                and all(isinstance(value, bool)
                        for value in raw_states.values())
                and raw_states["mirrored"] != (
                    raw_states["hand_flipped"]
                    != raw_states["facing_flipped"])):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_index=i, op_id=oid,
                field_name="mirrored",
                expected="hand_flipped XOR facing_flipped",
                got=raw_states["mirrored"],
                message_ru=("mirrored — производное состояние: должно быть "
                            "равно hand_flipped XOR facing_flipped")))
    if (name == "create_floor"
            or (name == "create_foundation" and norm.get("variety") == "slab")) \
            and "outline" in norm and norm.get("holes"):
        from kukai.ir.geom import check_holes_relation
        check_holes_relation(norm["outline"], norm["holes"], oid, diags)
    return norm
