"""Typed validation boundary for KIR authoring operations.

This module owns normalization and static refusal of authoring input.  It has
no emitter or live-execution authority: accepted values are handed to
``kukai.ir.authoring`` for deterministic C# emission.
"""
from __future__ import annotations

import math
from typing import Any

from kukai.ir import docspace, spec
from kukai.ir.diag import (
    Diagnostic,
    PARSE_MISSING_FIELD,
    TYPE_BAD_TYPE,
    TYPE_BOUNDS,
)
from kukai.ir.emit_utils import ELEMENT_ID_MAX, is_finite_number


def _num(x) -> bool:
    return is_finite_number(x)


# Static coordinate sanity bound (audit F12): Revit's own workable model
# extent is ~16 km from origin; a coordinate beyond that is a unit/garbage
# error that previously sailed to a late Revit runtime refusal.  Refused
# statically here instead — same enforcement point as every numeric bound.
_COORD_LIMIT_MM = 16_000_000.0

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
    for key in (("p0_mm", "p1_mm") if has_pts else ()):
        v = op.get(key)
        if v is None and not _pt_required.get(key, True):
            continue
        if not _pt_ok(v, dims=dims):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=key,
                expected=f"[x,y{',z' if dims == (3,) else ''}] мм (числа)", got=v,
                message_ru=f"{key} — точка в мм"))
        else:
            norm[key] = v
    if "p0_mm" in norm and "p1_mm" in norm and _dist(norm["p0_mm"], norm["p1_mm"]) < 1.0:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="p1_mm",
            message_ru=f"{name}: длина ~0 (p0==p1)"))
    for p in ospec.params:
        if p.kind in ("pt_xy", "pt_xyz") and p.name not in ("p0_mm", "p1_mm"):
            v = op.get(p.name)
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
            elif not (p.min_val <= v <= p.max_val):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"{p.min_val}..{p.max_val}", got=v,
                    suggested_replacement=min(max(v, p.min_val), p.max_val),
                    applicability="maybe-incorrect",
                    message_ru=f"{p.name} вне границ {p.min_val}..{p.max_val} мм"))
            else:
                norm[p.name] = float(v)
        elif p.kind == "deg":
            # Additive angle kind: keep an omitted default implicit so old
            # normalized programs, program hashes and emitted C# do not move.
            # Explicit values remain in degrees and are compared modulo 2*pi
            # by the live postcondition.
            if p.name not in op:
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
                continue                      # ground handles required/defaults
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
            if p.name == "host" \
                    and name not in ("set_curtain_panel",
                                     "create_curtain_grid_line",
                                     "create_railing") \
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
            if not (isinstance(v, list) and 3 <= len(v) <= 64
                    and all(_pt_ok(pt, dims=(2,)) for pt in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=">=3 точек [x,y] мм", got=v,
                    message_ru=f"{p.name} — контур из 3..64 точек"))
            else:
                area = abs(sum(v[k][0] * v[(k + 1) % len(v)][1]
                               - v[(k + 1) % len(v)][0] * v[k][1]
                               for k in range(len(v)))) / 2.0
                if area < 1e4:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        message_ru=f"{p.name}: вырожденный контур (площадь < 0.01 м²)"))
                else:
                    from kukai.ir.geom import ring_normalize
                    ring = ring_normalize(v, oid, p.name, diags)
                    if ring is not None:
                        norm[p.name] = ring
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
            if not (isinstance(v, list) and 2 <= len(v) <= 64
                    and all(_pt_ok(pt, dims=(2,)) for pt in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=">=2 точек [x,y] мм", got=v,
                    message_ru=f"{p.name} — ломаная из 2..64 точек"))
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
        elif p.kind == "pts_list":
            v = op.get(p.name)
            if v is None or (isinstance(v, list) and not v):
                # Absent OR empty list ⇒ "no holes" (semantically identical).
                # The materializer emits holes=[] for hole-free floors/roofs; a
                # bare `is None` check refused every such op KIR-T001.  Do not
                # use truthiness here: False/0/""/{} are malformed payloads,
                # not an alternative spelling of an empty hole list (F29).
                continue
            if not (isinstance(v, list) and 1 <= len(v) <= 8
                    and all(isinstance(h, list) and 3 <= len(h) <= 32
                            and all(_pt_ok(pt, dims=(2,)) for pt in h) for h in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    message_ru=f"{p.name} — список контуров (каждый 3..32 точек)"))
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
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=list(p.choices), got=v,
                    message_ru=f"{p.name} — одно из {list(p.choices)}"))
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
            if not isinstance(v, str) or not v.strip() or len(v) > cap:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"непустая строка <={cap}", got=v,
                    message_ru=f"{p.name} — непустая строка"))
            else:
                norm[p.name] = v.strip()
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
            _refs_w_bounds = {
                "move_elements": (1, 500, False),
            }
            lo, hi, reject_dupes = _refs_w_bounds.get(name, (2, 16, True))
            v = op.get(p.name)
            if not (isinstance(v, list) and lo <= len(v) <= hi
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
            arc_norm = _validate_arc(v, i, oid, norm.get("p0_mm"),
                                     norm.get("p1_mm"), diags)
            if arc_norm is not None:
                norm[p.name] = arc_norm
        elif p.kind == "member_ops":
            # feat/native-groups: the group DEFINITION — 1..N PRE-GROUNDED
            # member authoring ops authored at occurrence 0's absolute coords.
            # Structural check only (each member is a dict with a real,
            # non-group authoring op name and its own id); the members' own
            # params were already validated + grounded when the op was built by
            # the component-library bridge, and the GEOMETRIC fidelity of the
            # whole group is proven offline (native_group.assert_group_matches_
            # place_op) — never re-derived here.
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
                    if mospec is None or mospec.family not in spec.WRITE_FAMILIES \
                            or mop == "create_group":
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}].op", got=mop,
                            message_ru=("член группы — авторинг-оп (не query, не "
                                        "вложенная create_group)")))
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
                    # Лид-ревью №3: интра-программные ref-селекторы внутри
                    # члена указывают на переменные ВНЕ неймспейса группы —
                    # эмиссия дала бы несуществующий __el_* (падение на
                    # компайл-гейте). Отказываем типизированно здесь.
                    def _has_ref(node) -> bool:
                        if isinstance(node, dict):
                            if node.get("by") == "ref":
                                return True
                            g = node.get("__grounded__")
                            if isinstance(g, dict) and g.get("via") == "ref":
                                return True
                            return any(_has_ref(x) for x in node.values())
                        if isinstance(node, list):
                            return any(_has_ref(x) for x in node)
                        return False
                    if _has_ref({k: v2 for k, v2 in m.items() if k != "id"}):
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}]", got=mid,
                            message_ru=("член группы не может содержать "
                                        "ref-селекторы — только element_id/"
                                        "абсолютные координаты")))
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
