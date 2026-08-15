"""JSON Schema generator — derived from the registry, never hand-written (SPEC §3).

Numeric bounds appear in the schema as DOCUMENTATION; enforcement lives in the
compiler's typecheck stage only (SPEC 12.9 — decoders don't enforce min/max).
The kind enum includes the escape value "other" (SPEC 12.8) so constrained
decoding can always terminate; the compiler answers it with a typed handoff.
"""
from __future__ import annotations

from kukai.ir import faceref, relate, spec
from kukai.ir.authoring_validation import _FACE_SEL_SITES
from kukai.ir.emit_utils import ELEMENT_ID_MAX

#: RELATE, СХЕМА: адрес выписывается ВСЮДУ ДОСЛОВНО, а `$defs`/`$ref` делает
#: пост-проход `schema_dedup.hoist`.
#:
#: Спека §10 предлагала обратное — «`$defs` для адреса + `$ref` в 22 местах»
#: руками. Код против, и по двум причинам сразу:
#:   1) `schema_dedup.hoist` ОТКАЗЫВАЕТ схеме, у которой уже есть `$defs`
#:      («повторный хойст запрещён») — рукописный `$defs` не сэкономил бы, а
#:      сломал бы единственный работающий механизм дедупликации;
#:   2) сам `schema_dedup` объясняет почему: рукописный `$defs` — это второй
#:      источник правды о форме, и он отстаёт от генератора при первой правке.
#: Замер обоих путей — в отчёте волны; выигрыш хойста на адресе тот же, что
#: спека ждала от рукописного `$ref`.


def _grid_name_schema() -> dict:
    return {"type": "string", "minLength": 1,
            "maxLength": relate.MAX_GRID_NAME_LEN}


def _grid_line_schema() -> dict:
    """Узел <линия>: имя оси строкой ЛИБО объект с необязательным отступом.

    ПАРНОСТЬ `offset_mm`+`toward` схемой НЕ выражена намеренно. «Одно из двух»
    JSON Schema не выражает без `oneOf`, а `oneOf` здесь удвоил бы поддерево
    ради закона, который всё равно проверяет компилятор — тот же довод, по
    которому в этом доме существует `KIR-P007` (place_family: точка ЛИБО
    кривая) вместо схемной конструкции. Схема остаётся fail-closed по ПОЛЯМ
    (`additionalProperties: false`), а «offset без toward» — отказ KIR-T001,
    называющий следующий ход.
    """
    return {"oneOf": [
        _grid_name_schema(),
        {"type": "object", "properties": {
            "grid": _grid_name_schema(),
            "offset_mm": {"type": "number",
                          "minimum": -relate.MAX_OFFSET_MM,
                          "maximum": relate.MAX_OFFSET_MM},
            "toward": _grid_name_schema()},
         "required": ["grid"], "additionalProperties": False},
    ]}


#: КОРОТКАЯ строка, и это решение по замеру, а не лаконичность ради неё.
#:
#: Описание в схеме платится СТОЛЬКО РАЗ, сколько точечных параметров в
#: реестре (25 на 04.08). Полная формулировка идиомы (~130 токенов) стоила бы
#: +3 250 токенов схемы; здесь она одна на пакет — в `tool_doc.TRAPS`, где за
#: неё платят ОДИН раз. Замер обеих вёрсток — в отчёте волны.
_ADDRESS_DOC = "точка от ОСЕЙ модели: {\"at_grid\": [\"Б\", \"3\"]}"


def _address_schema(dims: int) -> dict:
    """Адрес от осей для параметра размерности ``dims``.

    Форма ЗАКРЫТА и совпадает с реестром `relate.ADDRESS_FORMS` — схема
    описывает ровно то, что примет компилятор, и ни поля больше.
    """
    at_grid = {"type": "array", "minItems": 2, "maxItems": 2,
               "items": _grid_line_schema()}
    if dims == 2:
        return {"type": "object", "description": _ADDRESS_DOC,
                "properties": {"at_grid": at_grid},
                "required": ["at_grid"], "additionalProperties": False}
    return {"type": "object",
            "description": _ADDRESS_DOC + " + z_mm (у сетки осей нет Z)",
            "properties": {"at_grid": at_grid, "z_mm": {"type": "number"}},
            "required": ["at_grid", "z_mm"], "additionalProperties": False}


#: Та же экономия, что у :data:`_ADDRESS_DOC`, и по той же причине: описание
#: платится столько раз, сколько точечных параметров в реестре. Полная идиома
#: живёт ОДИН раз в `tool_doc.TRAPS`, здесь — короткая строка.
_ELEMENT_ADDRESS_DOC = (
    'точка от ЭЛЕМЕНТА этой же программы: '
    '{"at_element": {"by": "ref", "value": "<id опа выше>"}, "point": "center"}')


def _element_address_schema(dims: int) -> dict:
    """Адрес от элемента для параметра размерности ``dims``.

    Форма ЗАКРЫТА и совпадает с реестром `relate.ELEMENT_ADDRESS_FORMS`.
    Трёхмерный случай выписан через `oneOf` из ДВУХ объектов, а не одним с
    двумя необязательными ключами: отметка обязательна, и назвать её можно
    ровно одним способом из двух — «оба сразу» и «ни одного» одинаково
    неоднозначны, и схема обязана говорить это сама, а не оставлять
    компилятору (тот всё равно скажет, но кругом дороже).
    """
    sel = {"type": "object",
           "properties": {"by": {"const": "ref"},
                          "value": {"type": "string", "minLength": 1}},
           "required": ["by", "value"], "additionalProperties": False}
    point = {"type": "string", "enum": list(relate.PLAN_POINTS)}
    if dims == 2:
        return {"type": "object", "description": _ELEMENT_ADDRESS_DOC,
                "properties": {"at_element": sel, "point": point},
                "required": ["at_element", "point"],
                "additionalProperties": False}
    return {"oneOf": [
        {"type": "object",
         "description": _ELEMENT_ADDRESS_DOC + ' + z: "base"|"top"|"axis"',
         "properties": {"at_element": sel, "point": point,
                        "z": {"type": "string",
                              "enum": list(relate.ELEVATIONS)}},
         "required": ["at_element", "point", "z"],
         "additionalProperties": False},
        {"type": "object",
         "description": _ELEMENT_ADDRESS_DOC + " + z_mm (отметка числом)",
         "properties": {"at_element": sel, "point": point,
                        "z_mm": {"type": "number"}},
         "required": ["at_element", "point", "z_mm"],
         "additionalProperties": False},
    ]}


def _kind_enum() -> list:
    return sorted(spec.KINDS) + [spec.KIND_ESCAPE]


def _filters_schema() -> dict:
    return {
        "type": "object",
        "properties": {k: ({"type": "boolean"} if fs["type"] is bool
                           else {"type": "string"})
                       for k, fs in spec.FILTERS.items()},
        "additionalProperties": False,
    }


def _element_id_selector(by: str = "element_id") -> dict:
    return {
        "type": "object",
        "properties": {
            "by": {"const": by},
            "value": {"type": "integer", "minimum": 1,
                      "maximum": ELEMENT_ID_MAX},
        },
        "required": ["by", "value"],
        "additionalProperties": False,
    }


def _disambiguate_by_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "param": {"type": "string", "minLength": 1},
            "value": {"oneOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "null"},
            ]},
        },
        "required": ["param", "value"],
        "additionalProperties": False,
    }


def _face_selector(inner_variants: list) -> dict:
    """Вторая ступень селектора: ГРАНЬ элемента (`kukai/ir/faceref.py`).

    `of` берёт ТЕ ЖЕ варианты, что и сам параметр, — не свой список. Второй
    список форм ступени 1 разъехался бы с первым на первой же правке, а
    расхождение схемы с проверкой означает форму, которую декод выдаёт, а
    компилятор отвергает.

    `minProperties: 1` у предиката — это тот же закон, что и в
    `faceref.validate_face_sel`: описание, которому отвечает КАЖДАЯ грань, не
    адресует ни одной."""
    return {
        "type": "object",
        "properties": {
            "by": {"const": faceref.BY_FACE},
            "of": {"oneOf": list(inner_variants)},
            "predicate": {
                "type": "object",
                "properties": {
                    "side": {"enum": list(faceref.SIDES)},
                    "normal": {"type": "array", "minItems": 3, "maxItems": 3,
                               "items": {"type": "number"}},
                },
                "minProperties": 1,
                "additionalProperties": False,
            },
        },
        "required": ["by", "of", "predicate"],
        "additionalProperties": False,
    }


def _string_selector(by: str, *, allow_disambiguation: bool = False) -> dict:
    properties = {
        "by": {"const": by},
        "value": {"type": "string", "minLength": 1},
    }
    if allow_disambiguation:
        properties["disambiguate_by"] = _disambiguate_by_schema()
    return {
        "type": "object",
        "properties": properties,
        "required": ["by", "value"],
        "additionalProperties": False,
    }


def _catalog_selector(kinds: list[str]) -> dict:
    variants = []
    for kind in kinds:
        if kind == "element_id":
            variants.append(_element_id_selector())
        elif kind == "family_type":
            variants.append({
                "type": "object",
                "properties": {
                    "by": {"const": "family_type"},
                    "category": {"type": "string", "minLength": 1},
                    "family_name": {"type": "string", "minLength": 1},
                    "type_name": {"type": "string", "minLength": 1},
                },
                "required": [
                    "by", "category", "family_name", "type_name"],
                "additionalProperties": False,
            })
        elif kind == "default":
            variants.append({
                "type": "object",
                "properties": {
                    "by": {"const": "default"},
                    "disambiguate_by": _disambiguate_by_schema(),
                },
                "required": ["by"],
                "additionalProperties": False,
            })
        else:
            variants.append(_string_selector(
                kind, allow_disambiguation=(kind == "name")))
    return {"oneOf": variants}


def _op_schema(op: spec.OpSpec) -> dict:
    props: dict = {
        "op": {"const": op.name},
        "id": {"type": "string", "minLength": 1, "maxLength": 64},
    }
    required = ["op"]
    for p in op.params:
        if p.kind == "kind_enum":
            props[p.name] = {"type": "string", "enum": _kind_enum()}
        elif p.kind == "filters":
            props[p.name] = _filters_schema()
        elif p.kind == "fields":
            props[p.name] = {"type": "array", "minItems": 1, "uniqueItems": True,
                             "items": {"type": "string", "enum": list(spec.LIST_FIELDS)}}
        elif p.kind == "int":
            s: dict = {"type": "integer"}
            if p.min_val is not None:
                s["minimum"] = p.min_val   # documentation; compiler enforces
            if p.max_val is not None:
                s["maximum"] = p.max_val
            props[p.name] = s
        elif p.kind == "target":
            props[p.name] = {"oneOf": [
                _element_id_selector(),
                {
                    "type": "object",
                    "properties": {
                        "by": {"const": "name"},
                        "value": {"type": "string", "minLength": 1},
                        "kind": {"type": "string", "enum": _kind_enum()},
                    },
                    "required": ["by", "value", "kind"],
                    "additionalProperties": False,
                },
            ]}
        elif p.kind in ("pt_xy", "pt_xyz"):
            lo = 3 if p.kind == "pt_xyz" else 2
            literal = {"type": "array", "minItems": lo, "maxItems": lo,
                       "items": {"type": "number"}}
            # RELATE: адрес от осей — ВТОРАЯ форма того же значения, и она
            # выписывается дословно, как всё остальное в этом генераторе.
            # Сжатие — работа `schema_dedup.hoist` (см. заметку у
            # `_ADDRESS_DEF` выше): здесь один источник правды о форме.
            if p.name in relate.addressable_params(op.name):
                props[p.name] = {"oneOf": [literal, _address_schema(lo),
                                           _element_address_schema(lo)]}
            else:
                props[p.name] = literal
        elif p.kind == "mm":
            s = {"type": "number"}
            if p.min_val is not None:
                s["minimum"] = p.min_val   # documentation; compiler enforces (12.9)
            if p.max_val is not None:
                s["maximum"] = p.max_val
            props[p.name] = s
        elif p.kind == "arc":
            # Curve-IR (P4-B): the canonical Arc dict (same shape as
            # decompile.recompile.ArcCurve / geom_extract.__gxCurve), so a
            # curved wall round-trips through the audited recompile machinery.
            # Optional on create_wall — absence means a straight Line wall.
            props[p.name] = {
                "type": "object",
                "properties": {
                    "curve_type": {"const": "Arc"},
                    "center_mm": {"type": "array", "minItems": 3,
                                  "maxItems": 3, "items": {"type": "number"}},
                    "radius_mm": {"type": "number", "exclusiveMinimum": 0},
                    "x_axis": {"type": "array", "minItems": 3, "maxItems": 3,
                               "items": {"type": "number"}},
                    "y_axis": {"type": "array", "minItems": 3, "maxItems": 3,
                               "items": {"type": "number"}},
                    "start_angle_rad": {"type": "number"},
                    "end_angle_rad": {"type": "number"}},
                "required": ["curve_type", "center_mm", "radius_mm",
                             "x_axis", "y_axis", "start_angle_rad",
                             "end_angle_rad"],
                "additionalProperties": False}
        elif p.kind == "spiral":
            # Винтовой марш (09.08): аргументы StairsRun.CreateSpiralRun в
            # авторских единицах KIR — миллиметры и ГРАДУСЫ (радианы в языке
            # бывают только у канонической дуги, которую пишет обратный ход).
            # Необязателен на create_stairs: отсутствие означает прямой марш
            # p0_mm/p1_mm, а взаимную обязательность держит компилятор
            # (KIR-P007) — схема выразить её не может.
            props[p.name] = {
                "type": "object",
                "properties": {
                    "center_mm": {"type": "array", "minItems": 2,
                                  "maxItems": 2, "items": {"type": "number"}},
                    "radius_mm": {"type": "number", "exclusiveMinimum": 0},
                    "start_angle_deg": {"type": "number"},
                    "included_angle_deg": {"type": "number",
                                           "exclusiveMinimum": 0,
                                           "maximum": 360},
                    "clockwise": {"type": "boolean"}},
                "required": ["center_mm", "radius_mm", "start_angle_deg",
                             "included_angle_deg", "clockwise"],
                "additionalProperties": False}
        elif p.kind == "deg":
            # Angle in degrees.  Any finite JSON number is meaningful here;
            # the emitter compares rotations modulo 2*pi instead of imposing
            # an arbitrary 0..360 input convention.
            props[p.name] = {"type": "number"}
            if p.default is not None:
                props[p.name]["default"] = p.default
        elif p.kind == "sel":
            selector_kinds = ["name", "element_id", "default"]
            if op.name == "place_family" and p.name == "symbol":
                selector_kinds.append("family_type")
            if p.ref_kinds:
                selector_kinds.append("ref")
            props[p.name] = _catalog_selector(selector_kinds)
        elif p.kind == "sel_list":
            # Список селекторов ТОГО ЖЕ рода, что и `sel` — не новый язык
            # адресации, а его множественное число (ровно как `refs_w`
            # относится к `target_w`).  Заводится ради
            # `create_multistory_stairs.levels`: `MultistoryStairs.
            # ConnectLevels` принимает МНОЖЕСТВО уровней одним вызовом, и
            # список element_id вместо имён был бы регрессом — уровни в KIR
            # адресуются именем везде.
            #
            # Нижняя граница 1, а не 2: лестница на ОДНОМ уровне — законный
            # (пусть и вырожденный) запрос, и это тот же довод, по которому
            # у `path` минимум 2, а не 3.  Верхняя 64 — столько же, сколько
            # точек у `path`/`pts`; этажей больше 64 одной программой всё
            # равно не адресуют.
            selector_kinds = ["name", "element_id", "default"]
            if p.ref_kinds:
                selector_kinds.append("ref")
            props[p.name] = {
                "type": "array", "minItems": 1, "maxItems": 64,
                "items": _catalog_selector(selector_kinds),
            }
        elif p.kind == "target_w":
            variants = [_element_id_selector()]
            if p.ref_kinds:
                variants.append(_string_selector("ref"))
            props[p.name] = {"oneOf": variants}
        elif p.kind == "num":
            sn: dict = {"type": "number"}
            if p.min_val is not None:
                sn["minimum"] = p.min_val   # documentation; compiler enforces (12.9)
            if p.max_val is not None:
                sn["maximum"] = p.max_val
            props[p.name] = sn
        elif p.kind == "value":
            props[p.name] = {"oneOf": [
                {"type": "string", "maxLength": 1000},
                {"type": "boolean"},
                {"type": "object",
                 "properties": {"value": {"type": "number"},
                                "unit": {"type": "string", "enum": ["mm", "raw"]}},
                 "required": ["value", "unit"], "additionalProperties": False},
                # ССЫЛКА: `{"material": "<имя>"}`. Схема обязана НЕ УЖЕ
                # валидатора — иначе программа, законная для компилятора,
                # отвергалась бы на входе, и причина приходила бы не оттуда.
                {"type": "object",
                 "properties": {"material": {"type": "string", "minLength": 1,
                                             "maxLength": 1000}},
                 "required": ["material"], "additionalProperties": False},
                {"type": "object",
                 "properties": {"phase": {"type": "string", "minLength": 1,
                                          "maxLength": 1000}},
                 "required": ["phase"], "additionalProperties": False},
                {"type": "object",
                 "properties": {"workset": {"type": "string", "minLength": 1,
                                            "maxLength": 1000}},
                 "required": ["workset"], "additionalProperties": False},
            ]}
        elif p.kind == "str":
            # cap defaults to 64 (every pre-existing str param leaves max_val
            # unset); documentation only (SPEC 12.9 — the compiler enforces
            # the real cap in authoring.validate(), kept in lockstep here so
            # the schema never UNDER-states what a caller may send).
            props[p.name] = {"type": "string",
                             "minLength": 0 if p.exact_string else 1,
                             "maxLength": p.max_val if p.max_val is not None else 64}
        elif p.kind == "pts":
            props[p.name] = {"type": "array", "minItems": 3, "maxItems": 64,
                             "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                        "items": {"type": "number"}}}
        elif p.kind == "pts_xyz":
            # wave/site: облако точек поверхности. Пределы читаются из
            # mesh.py, чтобы число жило в ОДНОМ месте (там же и замер, которым
            # оно обосновано) — тот же приём, что у рода `mesh` ниже.
            from kukai.ir.mesh import MAX_VERTICES
            props[p.name] = {
                "type": "array", "minItems": 3, "maxItems": MAX_VERTICES,
                "items": {"type": "array", "minItems": 3, "maxItems": 3,
                          "items": {"type": "number"}},
                "description": ("точки поверхности [[x,y,z], ...] в мм; Z — "
                                "отметка земли В САМОЙ ТОЧКЕ, а не смещение "
                                "от уровня. Две точки с одинаковым планом — "
                                "типизированный отказ"),
            }
        elif p.kind == "path":
            props[p.name] = {
                "type": "array", "minItems": 2, "maxItems": 64,
                "items": {"type": "array", "minItems": 2, "maxItems": 2,
                          "items": {"type": "number"}},
                "description": ("открытая ломаная [[x,y], ...] в мм; "
                                "замыкающий сегмент НЕ подразумевается"),
            }
        elif p.kind == "path3":
            props[p.name] = {
                "type": "array", "minItems": 2, "maxItems": 64,
                "items": {"type": "array", "minItems": 3, "maxItems": 3,
                          "items": {"type": "number"}},
                "description": ("открытая ТРЁХМЕРНАЯ ломаная [[x,y,z], ...] "
                                "в мм; замыкающий сегмент НЕ подразумевается, "
                                "совпадающие соседние точки — отказ"),
            }
        elif p.kind == "pts_list":
            props[p.name] = {"type": "array", "minItems": 1, "maxItems": 8,
                             "items": {"type": "array", "minItems": 3, "maxItems": 32,
                                        "items": {"type": "array", "minItems": 2,
                                                   "maxItems": 2,
                                                   "items": {"type": "number"}}}}
        elif p.kind == "slopes":
            # One entry per outline EDGE, null where that edge stays level.
            # The length tie to `outline` is a cross-field rule the compiler
            # checks; JSON Schema cannot express it, so it is stated in words
            # for the model that reads this.
            props[p.name] = {
                "type": "array", "minItems": 3, "maxItems": 64,
                "items": {"type": ["number", "null"],
                          "exclusiveMinimum": 0, "exclusiveMaximum": 90},
                "description": ("pitch in degrees per outline edge, same "
                                "length and order as outline; null = that "
                                "edge stays level"),
            }
        elif p.kind == "enum":
            props[p.name] = {"type": "string", "enum": list(p.choices)}
        elif p.kind == "graph_nodes":
            props[p.name] = {"type": "array", "minItems": 2, "maxItems": 64,
                             "items": {"type": "object", "properties": {
                                 "id": {"type": "string", "minLength": 1,
                                        "maxLength": 64,
                                        "pattern": r"^\S(?:[\s\S]*\S)?$"},
                                 "xyz_mm": {"type": "array", "minItems": 3, "maxItems": 3,
                                            "items": {"type": "number"}}},
                                 "required": ["id", "xyz_mm"],
                                 "additionalProperties": False}}
        elif p.kind == "graph_segments":
            diameter_param = next(
                (candidate for candidate in op.params
                 if candidate.name == "diameter_mm"), None)
            diameter_schema = {"type": "number"}
            if diameter_param is not None:
                if diameter_param.min_val is not None:
                    diameter_schema["minimum"] = diameter_param.min_val
                if diameter_param.max_val is not None:
                    diameter_schema["maximum"] = diameter_param.max_val
            segment_props = {
                "from": {"type": "string"}, "to": {"type": "string"},
                "diameter_mm": diameter_schema,
            }
            if op.name in ("route_pipe_system", "route_duct_system"):
                segment_props["slope_min_pct"] = {
                    "type": "number", "minimum": 0.0, "maximum": 100.0,
                }
            props[p.name] = {"type": "array", "minItems": 1, "maxItems": 128,
                             "items": {"type": "object", "properties": segment_props,
                                 "required": ["from", "to"],
                                 "additionalProperties": False}}
        elif p.kind == "region":
            anchor = {"oneOf": [
                {"type": "array", "minItems": 2, "maxItems": 2,
                 "items": {"type": "number"}},
                _address_schema(2),
                # ЛЕГАСИ-ФОРМА, живая только здесь: мировая пара [dx,dy].
                # Она и есть Д1 спеки (мировая рамка отступа), и в новых
                # точечных параметрах её нет. Остаётся ради голденов
                # `region`; узловой отступ работает и тут.
                {"type": "object", "properties": {
                    "at_grid": {"type": "array", "minItems": 2, "maxItems": 2,
                                "items": _grid_line_schema()},
                    "offset_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                                  "items": {"type": "number"}}},
                 "required": ["at_grid", "offset_mm"],
                 "additionalProperties": False}]}
            shape = {"oneOf": [
                {"type": "object", "properties": {
                    "shape": {"const": "rect"}, "origin": anchor,
                    "size_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                                "items": {"type": "number"}},
                    "rotation_deg": {"type": "number"}},
                 "required": ["shape", "origin", "size_mm"],
                 "additionalProperties": False},
                {"type": "object", "properties": {
                    "shape": {"const": "l"}, "origin": anchor,
                    "size_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                                "items": {"type": "number"}},
                    "cut_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                               "items": {"type": "number"}},
                    "corner": {"type": "string", "enum": ["ne", "nw", "se", "sw"]}},
                 "required": ["shape", "origin", "size_mm", "cut_mm"],
                 "additionalProperties": False},
                {"type": "object", "properties": {
                    "shape": {"const": "poly"},
                    "points_mm": {"type": "array", "minItems": 3, "maxItems": 64,
                                  "items": anchor},
                    "arcs": {"type": "array", "items": {"type": "object",
                             "properties": {"edge": {"type": "integer"},
                                            "bulge": {"type": "number"},
                                            "radius_mm": {"type": "number"},
                                            "dir": {"type": "string",
                                                    "enum": ["ccw", "cw"]}},
                             "required": ["edge"],
                             "additionalProperties": False}}},
                 "required": ["shape", "points_mm"],
                 "additionalProperties": False}]}
            props[p.name] = {"type": "object", "properties": {
                "outer": shape,
                "holes": {"type": "array", "maxItems": 8, "items": shape}},
                "required": ["outer"], "additionalProperties": False}
        elif p.kind == "bool":
            props[p.name] = ({"type": "boolean", "default": p.default}
                             if p.default is not None else {"type": "boolean"})
        elif p.kind == "pt_view2d":
            # Documentation VIEW-SPACE type (KIR_DOC_SPEC.md): EXACTLY [u, v]
            # mm — the schema shape mirrors docspace.is_pt_view2d (2 items,
            # never 3; a 3D point is a compiler-stage KIR-T001, not a schema
            # violation, so the schema stays permissive on numeric range and
            # the compiler enforces the sheet-bounds guard, same 12.9 split
            # as every other numeric field).
            props[p.name] = {"type": "array", "minItems": 2, "maxItems": 2,
                             "items": {"type": "number"}}
        elif p.kind == "refs_w":
            # Documentation `refs` (create_dimension): >=2 target_w selectors.
            variants = [_element_id_selector()]
            if p.ref_kinds:
                variants.append(_string_selector("ref"))
            # ВТОРАЯ СТУПЕНЬ (`{"by": "face", ...}`, `kukai/ir/faceref.py`) —
            # ТОЛЬКО за флагом оператора и только у названного носителя.
            # Схема fail-closed: пока варианта здесь нет, ограниченный декод
            # физически не может выдать селектор грани, и это ровно то, чего
            # закон выключенного флага требует — при выключенном флаге схема
            # обязана быть побайтово прежней.
            if (faceref.face_ref_enabled()
                    and (op.name, p.name) in _FACE_SEL_SITES):
                variants.append(_face_selector(variants))
            props[p.name] = {"type": "array", "minItems": 2, "maxItems": 16,
                             "items": {"oneOf": variants}}
        elif p.kind == "str_long":
            # Documentation `content` (create_text): longer bound than "str"
            # (KIR_DOC_SPEC.md: "непустой, <= разумной длины").
            props[p.name] = {"type": "string", "minLength": 1, "maxLength": 2000}
        elif p.kind == "member_ops":
            # feat/native-groups: the group DEFINITION — 1..200 PRE-GROUNDED
            # member authoring ops.  Members carry the {"__grounded__": ...}
            # selector shape (built by the component-library bridge, not by a
            # raw LLM decode), so the schema stays permissive on the member's
            # own params (additionalProperties true) and requires only op+id;
            # authoring.validate does the structural member check, and the
            # geometric fidelity is proven offline (native_group.py).  This op
            # is a REBUILD op emitted by the bridge, not part of the raw
            # decode surface, so it never constrains free LLM generation.
            props[p.name] = {
                "type": "array", "minItems": 1, "maxItems": 200,
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string"},
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                    },
                    "required": ["op", "id"],
                    "additionalProperties": True,
                }}
        elif p.kind == "placements":
            # feat/native-groups: per-additional-occurrence [dx,dy(,dz)] mm
            # offset deltas (occurrence 0 is the members, so an empty list is
            # legal).
            props[p.name] = {
                "type": "array", "minItems": 0, "maxItems": 4096,
                "items": {"type": "array", "minItems": 2, "maxItems": 3,
                          "items": {"type": "number"}}}
        elif p.kind == "mesh":
            # wave/shape: треугольная поверхность create_directshape. ОДИН
            # объект, а не два параллельных массива — индексы треугольников
            # проверяемы только вместе со своим вершинным массивом, и схема,
            # допускающая одно без другого, приглашает ровно тот класс ошибок,
            # где отсутствие превращается в ноль. Пределы берутся из mesh.py,
            # чтобы число жило в ОДНОМ месте (там же и замер, которым оно
            # обосновано).
            from kukai.ir.mesh import MAX_TRIANGLES, MAX_VERTICES
            props[p.name] = {
                "type": "object",
                "properties": {
                    "vertices_mm": {
                        "type": "array", "minItems": 3,
                        "maxItems": MAX_VERTICES,
                        "items": {"type": "array", "minItems": 3,
                                  "maxItems": 3,
                                  "items": {"type": "number"}},
                        "description": "вершины [x,y,z] в мм",
                    },
                    "triangles": {
                        "type": "array", "minItems": 1,
                        "maxItems": MAX_TRIANGLES,
                        "items": {"type": "array", "minItems": 3,
                                  "maxItems": 3,
                                  "items": {"type": "integer", "minimum": 0}},
                        "description": ("грани тройками НОМЕРОВ вершин "
                                        "(0-based) из vertices_mm"),
                    },
                },
                "required": ["vertices_mm", "triangles"],
                "additionalProperties": False,
                "description": (
                    "связный треугольный меш. Строит DirectShape — геометрию "
                    "БЕЗ BIM-смысла: без типа, без параметров, вне "
                    "спецификаций, не редактируется вручную. Для стен, "
                    "перекрытий, кровель, колонн и балок есть настоящие "
                    "операции — меш их не заменяет и не изображает"),
            }
        else:  # pragma: no cover — второй из трёх замков, см. ниже
            # ЧЕСТНОЕ ОПИСАНИЕ ЗАМКА. Здесь стояло «registry lint keeps kinds
            # closed» — ссылка на гарантию, которой НЕ СУЩЕСТВОВАЛО:
            # `spec._lint_registry` проверял клетки способности, эффекты,
            # результаты и пулы снапшота, а про `ParamSpec.kind` не знал
            # ничего. Комментарий утверждал закрытость словаря, который был
            # открыт, — ровно тот род дефекта, против которого стоит сам
            # `raise`.
            #
            # С 07.08.2026 словарь ДЕЙСТВИТЕЛЬНО закрыт (`spec.PARAM_KINDS`,
            # проверяется на импорте реестра), и ссылаться теперь есть на что.
            # Но этот замок остаётся НЕЗАВИСИМЫМ и потому не лишним: он ловит
            # вид, для которого ветвь схемы не написана, даже если вид честно
            # назван в словаре. Три прохода — импорт реестра, сборка схемы,
            # разбор программы — падают по трём разным причинам.
            raise AssertionError(f"unknown param kind {p.kind}")
        if p.required:
            required.append(p.name)
    return {"type": "object", "properties": props,
            "required": required, "additionalProperties": False}


def _defaults_schema() -> dict:
    """Envelope-level selectors, inherited by every op that accepts them.

    Kept in step with compiler.DEFAULTABLE — the compiler refuses any other key,
    so advertising a wider schema would invite a program it then rejects.
    """
    from kukai.ir.compiler import DEFAULTABLE
    kinds = ["name", "element_id", "default", "family_type", "ref"]
    return {
        "type": "object",
        "description": ("Селекторы на всю программу: любой оп, который "
                        "принимает такое поле и не задал его сам, получит это "
                        "значение. 128 балок одного типа — один раз здесь, а "
                        "не 128 раз в опах."),
        "properties": {name: _catalog_selector(kinds) for name in DEFAULTABLE},
        "additionalProperties": False,
    }


def program_schema() -> dict:
    """The constrained-decoding artifact for a KIR program."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"KIR program v{spec.IR_VERSION}",
        "type": "object",
        "properties": {
            "ir_version": {"const": spec.IR_VERSION},
            "intent": {"type": "string", "maxLength": 2000},
            "allow_destructive": {"type": "boolean", "default": False},
            "defaults": _defaults_schema(),
            "ops": {
                "type": "array", "minItems": 1,
                "items": {"oneOf": [_op_schema(op) for op in OPS_SORTED]
                          + _macro_schemas()},
            },
        },
        "required": ["ir_version", "ops"],
        "additionalProperties": False,
    }


OPS_SORTED = [spec.OPS[k] for k in sorted(spec.OPS)]


def _macro_schemas() -> list:
    """Macro envelopes for constrained decoding. `floor` items stay loose in
    the schema — the compiler re-validates every expanded op fail-closed, so
    looseness here cannot admit an invalid final program (SPEC 12.9 analog)."""
    return [
        {"type": "object", "properties": {
            "op": {"const": "stack"},
            "id": {"type": "string", "minLength": 1, "maxLength": 64},
            "levels": {"type": "integer", "minimum": 1, "maximum": 40},
            "h_mm": {"type": "number"},
            "base_elev_mm": {"type": "number"},
            "name_prefix": {"type": "string", "maxLength": 32},
            "floor": {"type": "array", "minItems": 1, "maxItems": 299,
                      "items": {"type": "object"}},
            "transform": {
                "type": "object",
                "description": (
                    "Как план этажа меняется от низа к верху. Без него все "
                    "этажи одинаковые — то есть коробка. С ним получается "
                    "сужение, закрутка и смещение: этаж k интерполируется "
                    "между низом и этими значениями."),
                "properties": {
                    "scale_xy_top": {
                        "type": "array", "minItems": 2, "maxItems": 2,
                        "items": {"type": "number", "minimum": 0.05,
                                  "maximum": 20},
                        "description": "во сколько раз план верхнего этажа "
                                       "отличается от нижнего, [sx, sy]"},
                    "twist_deg_total": {
                        "type": "number", "minimum": -3600, "maximum": 3600,
                        "description": "суммарный поворот от низа к верху"},
                    "offset_mm_top": {
                        "type": "array", "minItems": 2, "maxItems": 2,
                        "items": {"type": "number"},
                        "description": "смещение верха относительно низа, мм"},
                    "pivot_mm": {
                        "type": "array", "minItems": 2, "maxItems": 2,
                        "items": {"type": "number"},
                        "description": "центр сужения и поворота"},
                },
                "additionalProperties": False},
        }, "required": ["op", "levels", "floor"], "additionalProperties": False},
        {"type": "object", "properties": {
            "op": {"const": "grid_array"},
            "id": {"type": "string", "minLength": 1, "maxLength": 64},
            "nx": {"type": "integer", "minimum": 0, "maximum": 50},
            "ny": {"type": "integer", "minimum": 0, "maximum": 50},
            "dx_mm": {"type": "number"}, "dy_mm": {"type": "number"},
            "origin_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                           "items": {"type": "number"}},
            "margin_mm": {"type": "number"},
            "prefix_x": {"type": "string", "maxLength": 8},
            "prefix_y": {"type": "string", "maxLength": 8},
        }, "required": ["op"], "additionalProperties": False},
        {"type": "object", "properties": {
            "op": {"const": "series"},
            "id": {"type": "string", "minLength": 1, "maxLength": 64},
            "count": {"type": "integer", "minimum": 1, "maximum": 200},
            "track": {
                "type": "object",
                "description": (
                    "Именованные числовые параметры, каждый — КУСОЧНО-ЛИНЕЙНЫЙ "
                    "трек из узлов [индекс, значение]. Между узлами линейная "
                    "интерполяция, поэтому одна тройка узлов описывает силуэт с "
                    "изломом. Трек обязан покрывать все индексы, на которых его "
                    "читают (0..count-1, а с @next — 0..count)."),
                "minProperties": 1, "maxProperties": 8,
                "additionalProperties": {
                    "type": "array", "minItems": 2, "maxItems": 32,
                    "items": {"type": "array", "minItems": 2, "maxItems": 2,
                              "items": {"type": "number"}}}},
            "items": {
                "type": "array", "minItems": 1, "maxItems": 200,
                "description": (
                    "Шаблоны опов. В любом ЧИСЛОВОМ поле вместо числа можно "
                    "поставить ссылку на параметр трека: \"$имя\" — значение на "
                    "шаге k, \"$имя@next\" — на шаге k+1 (так N повторов сшивают "
                    "N сегментов), минусом впереди берётся зеркальное значение: "
                    "\"-$имя\", \"-$имя@next\". Других форм нет — арифметики в "
                    "программе не бывает."),
                "items": {"type": "object"}},
        }, "required": ["op", "count", "track", "items"],
           "additionalProperties": False},
    ]
