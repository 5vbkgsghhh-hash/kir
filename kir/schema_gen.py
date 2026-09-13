"""JSON Schema generator — derived from the registry, never hand-written (SPEC §3).

Numeric bounds appear in the schema as DOCUMENTATION; enforcement lives in the
compiler's typecheck stage only (SPEC 12.9 — decoders don't enforce min/max).
The kind enum includes the escape value "other" (SPEC 12.8) so constrained
decoding can always terminate; the compiler answers it with a typed handoff.
"""
from __future__ import annotations

from kir import contour as _contour
from kir import geom as _geom
from kir import faceref, macros as _macros, relate, spec
from kir.authoring_validation import (
    _FACE_SEL_SITES,
    _TEXT_CONTENT_MAX_CHARS,
    _refs_w_contract,
)
from kir.emit_utils import ELEMENT_ID_MAX
from kir.registry_base import (
    WALL_LAYER_FUNCTIONS, WALL_LAYER_MAX_MM, WALL_LAYER_MIN_MM,
    WALL_LAYERS_MAX,
)

#: RELATE, SCHEMA: the address is spelled out VERBATIM EVERYWHERE, and
#: `$defs`/`$ref` is done by the `schema_dedup.hoist` post-pass.
#:
#: Spec §10 proposed the opposite — "`$defs` for the address + `$ref` in 22
#: places" by hand. The code is against it, for two reasons at once:
#:   1) `schema_dedup.hoist` REFUSES a schema that already has `$defs`
#:      ("repeat hoist forbidden") — a hand-written `$defs` would not save
#:      anything, it would break the one working deduplication mechanism;
#:   2) `schema_dedup` itself explains why: a hand-written `$defs` is a
#:      second source of truth about the shape, and it falls behind the
#:      generator at the very first edit.
#: Both paths are measured in the wave report; the gain from hoisting the
#: address is the same one the spec expected from a hand-written `$ref`.


def _node_id_schema() -> dict:
    """The shape of a graph node's name. ONE for the whole file.

    🔴 THERE USED TO BE TWO, AND THEY DIVERGED (F-117, 29.08.2026):
    `graph_nodes.id` had a length and a pattern, `graph_segments.from/to`
    had a bare string. The schema accepted as an EDGE END what it rejected
    as a NODE NAME, even though an edge must point at a node
    (`connect.graph_validate`, KIR-L003) — that is, the model spent a round
    on a program that the schema allowed and the compiler rejected.

    Returns a NEW dict on every call, deliberately: the schema is assembled
    and serialized, and a shared mutable object would one day get patched in
    place in one of the two branches.
    """
    return {"type": "string", "minLength": 1, "maxLength": 64,
            "pattern": r"^\S(?:[\s\S]*\S)?$"}


def _grid_name_schema() -> dict:
    return {"type": "string", "minLength": 1,
            "maxLength": relate.MAX_GRID_NAME_LEN}


def _grid_line_schema() -> dict:
    """The <line> node: a grid name as a string, OR an object with an optional offset.

    The PAIRING of `offset_mm`+`toward` is deliberately NOT expressed by the
    schema. JSON Schema cannot express "one of two" without `oneOf`, and
    `oneOf` here would double the subtree for the sake of a law that the
    compiler checks anyway — the same argument behind `KIR-P007` existing in
    this house (place_family: a point OR a curve) instead of a schema
    construct. The schema stays fail-closed on FIELDS
    (`additionalProperties: false`), while "offset without toward" is a
    KIR-T001 refusal that names the next turn.
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


#: A SHORT string, and this is a measured decision, not brevity for its own
#: sake.
#:
#: A description in the schema is paid for AS MANY TIMES as there are
#: point-address parameters in the registry (25 as of 04.08). The full
#: wording of the idiom (~130 tokens) would cost +3 250 schema tokens; here
#: it exists once per package — in `tool_doc.TRAPS`, where it is paid for
#: ONCE. Both layouts are measured in the wave report.
_ADDRESS_DOC = "точка от ОСЕЙ модели: {\"at_grid\": [\"Б\", \"3\"]}"


def _address_schema(dims: int) -> dict:
    """An address from grids for a parameter of dimensionality ``dims``.

    The shape is CLOSED and matches the `relate.ADDRESS_FORMS` registry —
    the schema describes exactly what the compiler will accept, and not one
    field more.
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


#: The same saving as with :data:`_ADDRESS_DOC`, and for the same reason: the
#: description is paid for as many times as there are point-address
#: parameters in the registry. The full idiom lives ONCE in `tool_doc.TRAPS`,
#: here — a short string.
_ELEMENT_ADDRESS_DOC = (
    'точка от ЭЛЕМЕНТА этой же программы: '
    '{"at_element": {"by": "ref", "value": "<id опа выше>"}, "point": "center"}')


def _element_address_schema(dims: int) -> dict:
    """An address from an element for a parameter of dimensionality ``dims``.

    The shape is CLOSED and matches the `relate.ELEMENT_ADDRESS_FORMS`
    registry. The three-dimensional case is spelled out via `oneOf` of TWO
    objects, rather than one with two optional keys: the elevation is
    mandatory, and it can be named in exactly one of two ways — "both at
    once" and "neither" are equally ambiguous, and the schema must say so
    itself rather than leave it to the compiler (which will say so anyway,
    but at a higher cost all around).
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
    """The second stage of the selector: the FACE of an element (`kir/faceref.py`).

    `of` takes the SAME variants as the parameter itself — not a list of its
    own. A second list of stage-1 shapes would drift from the first at the
    very first edit, and a schema that disagrees with the check means a
    shape that decoding produces and the compiler rejects.

    `minProperties: 1` on the predicate is the same law as in
    `faceref.validate_face_sel`: a description that every face answers to
    addresses none of them."""
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


def _region_schema() -> dict:
    """The schema for a value of kind `region`. ONE CARRIER FOR TWO CONSUMERS.

    Hoisted out of the `p.kind == "region"` branch on 21.08.2026, when the
    contour became a field of a boolean PART (`prism`) alongside the op's
    field. A copy of this block inside `solid_parts` would drift from the
    original at the very first edit of the contour's shape — and such pairs
    drift silently, and the cost of that drift is measured here: on
    16.08.2026 three programs out of three were VALID by the schema and
    REJECTED by the compiler, meaning the model was judged by something
    other than what it was shown.
    """
    anchor = {"oneOf": [
        {"type": "array", "minItems": 2, "maxItems": 2,
         "items": {"type": "number"}},
        _address_schema(2),
        # A LEGACY FORM, alive only here: a world-frame pair [dx,dy]. It is
        # exactly spec's D1 (the world offset frame), and it is absent from
        # the new point-address parameters. Kept for the sake of the
        # `region` goldens; a node offset works here too.
        {"type": "object", "properties": {
            "at_grid": {"type": "array", "minItems": 2, "maxItems": 2,
                        "items": _grid_line_schema()},
            "offset_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                          "items": {"type": "number"}}},
         "required": ["at_grid", "offset_mm"],
         "additionalProperties": False}]}
    # 🔴 BOUNDS ARE TAKEN FROM THE VALIDATOR, NOT WRITTEN HERE A SECOND
    # TIME. Measured 16.08.2026 by execution: three programs out of three
    # checked were VALID by this schema and REJECTED by the compiler
    # (`size_mm=[50,50]`, `rotation_deg=720`, `cut_mm=[10,10]`) — the model
    # was judged by something other than what it was shown.
    _side = {"type": "number", "minimum": _contour.SHAPE_SIDE_MIN_MM,
             "maximum": _contour.SHAPE_SIDE_MAX_MM}
    shape = {"oneOf": [
        {"type": "object", "properties": {
            "shape": {"const": "rect"}, "origin": anchor,
            "size_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                        "items": _side},
            "rotation_deg": {
                "type": "number",
                "minimum": -_contour.SHAPE_ROTATION_ABS_MAX_DEG,
                "maximum": _contour.SHAPE_ROTATION_ABS_MAX_DEG}},
         "required": ["shape", "origin", "size_mm"],
         "additionalProperties": False},
        {"type": "object", "properties": {
            "shape": {"const": "l"}, "origin": anchor,
            "size_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                        "items": _side},
            # The cutout's upper bound DEPENDS on the side and is
            # inexpressible in flat JSON Schema; the lower bound is
            # expressible and catches the measured case `cut_mm=[10,10]`.
            # The rest is the compiler's refusal, and it now SHOWS the
            # shape in full.
            "cut_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                       "items": {"type": "number",
                                 "minimum": _contour.SHAPE_SIDE_MIN_MM}},
            "corner": {"type": "string", "enum": ["ne", "nw", "se", "sw"]}},
         "required": ["shape", "origin", "size_mm", "cut_mm"],
         "additionalProperties": False},
        {"type": "object", "properties": {
            "shape": {"const": "poly"},
            "points_mm": {"type": "array",
                          "minItems": _contour.MIN_RING_POINTS,
                          "maxItems": _contour.MAX_RING_POINTS,
                          "items": anchor},
            "arcs": {"type": "array", "items": {"type": "object",
                     "properties": {"edge": {"type": "integer"},
                                    "bulge": {"type": "number"},
                                    "radius_mm": {"type": "number"},
                                    "dir": {"type": "string",
                                            "enum": ["ccw", "cw"]}},
                     "required": ["edge"],
                     "additionalProperties": False}},
            # 🔴 THE THIRD KIND OF EDGE — A SPLINE. Declared HERE, because
            # the schema the model receives has `additionalProperties:
            # False`: a field known to the validator and unknown to the
            # schema gives the model a refusal on a VALID program. The
            # reverse case of this same mismatch was paid for on
            # 16.08.2026 — three programs out of three were valid by the
            # schema and rejected by the compiler. The via_mm bounds come
            # from `contour`, not as a literal: two numbers that must
            # match drift apart silently.
            "splines": {"type": "array", "items": {"type": "object",
                        "properties": {
                            "edge": {"type": "integer"},
                            "via_mm": {
                                "type": "array",
                                "minItems": _contour.SPLINE_VIA_MIN,
                                "maxItems": _contour.SPLINE_VIA_MAX,
                                "items": {"type": "array",
                                          "minItems": 2, "maxItems": 2,
                                          "items": {"type": "number"}}}},
                        "required": ["edge", "via_mm"],
                        "additionalProperties": False}}},
         "required": ["shape", "points_mm"],
         "additionalProperties": False}]}
    return {"type": "object", "properties": {
        "outer": shape,
        "holes": {"type": "array", "maxItems": 8, "items": shape}},
        "required": ["outer"], "additionalProperties": False}


def _plane_schema() -> dict:
    """The schema for a value of kind `plane`. ONE CARRIER FOR TWO CONSUMERS.

    Hoisted out on 21.08.2026 for the same reason as `_region_schema`: the
    plane became a field of a boolean PART (`prism`) alongside the op's
    field.
    """
    # wave/plane (2026-08-21). Fields and bounds are taken FROM `plane.py`,
    # not as literals: a schema that allows something OTHER than the
    # validator gives the model a refusal on a VALID program — paid for on
    # 16.08.2026 on the contour's shapes (three programs out of three were
    # valid by the schema and rejected by the compiler).
    from kir.plane import (PLANE_FIELDS, PLANE_ORIGIN_ABS_MAX_MM,
                                ORTHOGONALITY_COS_TOL)
    _vec = {"type": "array", "minItems": 3, "maxItems": 3,
            "items": {"type": "number"}}
    return {
        "type": "object",
        "properties": {
            "origin_mm": dict(
                _vec, items={"type": "number",
                             "minimum": -PLANE_ORIGIN_ABS_MAX_MM,
                             "maximum": PLANE_ORIGIN_ABS_MAX_MM},
                description="начало плоскости [x, y, z] в мм: сюда "
                            "садится точка (0, 0) профиля"),
            "normal": dict(_vec, description=(
                "нормаль плоскости [nx, ny, nz]; выдавливание идёт "
                "ВДОЛЬ неё. Длина не важна — вектор нормируется")),
            "x_dir": dict(_vec, description=(
                "направление оси +u профиля, ЛЕЖАЩЕЕ в плоскости "
                "(|cos| с нормалью не больше %g). Обязательно: без "
                "него оси в плоскости выбрал бы Revit, и профиль "
                "приехал бы повёрнутым на неизвестный угол"
                % ORTHOGONALITY_COS_TOL)),
        },
        "required": list(PLANE_FIELDS),
        "additionalProperties": False,
        "description": ("плоскость эскиза. НЕОБЯЗАТЕЛЬНА: без неё "
                        "профиль лежит в мировой XY и выдавливается "
                        "по +Z. ВМЕСТЕ с base_z_mm не принимается — "
                        "base_z_mm и есть горизонтальная плоскость"),
    }


def _op_id_schema() -> dict:
    return {"type": "string", "minLength": 1, "maxLength": 64,
            "not": {"enum": sorted(spec.PROGRAM_RESULT_METADATA_KEYS)}}


def _op_schema(op: spec.OpSpec) -> dict:
    props: dict = {
        "op": {"const": op.name},
        "id": _op_id_schema(),
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
        elif p.kind == "enum_list":
            # 🔴 СЛОВАРЬ ИЗ САМОГО ПАРАМЕТРА, А НЕ ИЗ МОДУЛЯ. Ветка `fields`
            # прямо над этой прибита к `LIST_FIELDS`, и второй оп той же формы с
            # другим словарём получил бы верную проверку и ЛОЖНУЮ схему. Здесь
            # `choices` — единственный источник, как у `enum`.
            props[p.name] = {"type": "array", "minItems": 1, "uniqueItems": True,
                             "items": {"type": "string", "enum": list(p.choices)}}
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
        elif p.kind == "dir_xyz":
            # 🔴 A DIRECTION IS DESCRIBED BY THE SAME SHAPE AND A DIFFERENT
            # WORD, AND THE WORD DOES WORK HERE. The schema is read by the
            # MODEL, and "a point [x,y,z] mm" versus "a direction,
            # dimensionless" is the difference between writing [0,0,1] and
            # writing [0,0,3000]. Both have the same shape (three numbers),
            # so nothing but the description can tell them apart in the
            # schema; a direction has no grid address by construction —
            # `addressable_params` knows only point-address kinds.
            props[p.name] = {
                "type": "array", "minItems": 3, "maxItems": 3,
                "items": {"type": "number"},
                "description": ("НАПРАВЛЕНИЕ [x,y,z] — безразмерный луч, не "
                                "точка и не миллиметры. Длина не важна, ноль "
                                "запрещён"),
            }
        elif p.kind in ("pt_xy", "pt_xyz"):
            lo = 3 if p.kind == "pt_xyz" else 2
            literal = {"type": "array", "minItems": lo, "maxItems": lo,
                       "items": {"type": "number"}}
            # RELATE: an address from grids — A SECOND form of the same
            # value, and it is spelled out verbatim, like everything else
            # in this generator. Compression is `schema_dedup.hoist`'s job
            # (see the note at `_ADDRESS_DEF` above): here there is one
            # source of truth about the shape.
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
            # A spiral flight (09.08): the arguments of
            # StairsRun.CreateSpiralRun are in KIR's authoring units —
            # millimeters and DEGREES (radians occur in the language only
            # for the canonical arc that the reverse pass writes). Optional
            # on create_stairs: its absence means a straight flight
            # p0_mm/p1_mm, and mutual mandatoriness is held by the compiler
            # (KIR-P007) — the schema cannot express it.
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
            # A list of selectors of the SAME kind as `sel` — not a new
            # addressing language, just its plural (exactly as `refs_w`
            # relates to `target_w`). Introduced for the sake of
            # `create_multistory_stairs.levels`: `MultistoryStairs.ConnectLevels`
            # accepts A SET of levels in one call, and a list of element_ids
            # instead of names would be a regression — levels in KIR are
            # addressed by name everywhere.
            #
            # The lower bound is 1, not 2: a staircase on ONE level is a
            # valid (if degenerate) request, and this is the same argument
            # behind `path`'s minimum of 2, not 3. The upper bound of 64 is
            # the same as the number of points in `path`/`pts`; no single
            # program addresses more than 64 floors anyway.
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
        elif p.kind == "identity":
            # 🔴 THE BASE A WRITE WAS PLANNED AGAINST. Both fields come from one
            # place — `element_identity` of a creation receipt, or
            # `query_element_state` — so the schema names that place: a model
            # that has to GUESS where a UniqueId comes from will invent one.
            # The schema is no narrower than the validator
            # (`authoring_validation`, kind `identity`): both fields required,
            # nothing else allowed.
            props[p.name] = {
                "type": "object",
                "properties": {
                    "unique_id": {"type": "string", "minLength": 1,
                                  "description": "UniqueId элемента: 8-4-4-4-12 и суффикс"},
                    "version_guid": {"type": "string", "minLength": 32, "maxLength": 32,
                                     "description": "VersionGuid, 32 шестнадцатеричных знака"},
                },
                "required": ["unique_id", "version_guid"],
                "additionalProperties": False,
                "description": (
                    "личность элемента, КАКОЙ ОНА БЫЛА ПРОЧИТАНА: оба поля берутся "
                    "из element_identity квитанции создания либо из "
                    "query_element_state. Если элемент с тех пор изменился, "
                    "операция отказывает по имени identity_changed_since_read, а не "
                    "переписывает чужую правку"),
            }
        elif p.kind == "value":
            props[p.name] = {"oneOf": [
                {"type": "string", "maxLength": 1000},
                {"type": "boolean"},
                {"type": "object",
                 "properties": {"value": {"type": "number"},
                                "unit": {"type": "string", "enum": ["mm", "raw"]}},
                 "required": ["value", "unit"], "additionalProperties": False},
                # A REFERENCE: `{"material": "<name>"}`. The schema must be
                # NO NARROWER than the validator — otherwise a program
                # valid for the compiler would be rejected at the door, and
                # the blame would come from the wrong place.
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
            # wave/site: a surface point cloud. The limits are read from
            # mesh.py, so the number lives in ONE place (where the
            # measurement backing it also lives) — the same technique as
            # for the `mesh` kind below.
            from kir.mesh import MAX_VERTICES
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
            # An empty list is the canonical, explicit "no openings": it is
            # printed by the reverse materializer and accepted by the
            # compiler. The remaining bounds are read from the same
            # geometry law as the runtime.
            props[p.name] = {"type": "array", "minItems": 0,
                             "maxItems": _geom.MAX_HOLES,
                             "items": {"type": "array",
                                        "minItems": _geom.MIN_RING_POINTS,
                                        "maxItems": _geom.MAX_HOLE_RING_POINTS,
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
                                 "id": _node_id_schema(),
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
                # 🔴 AN EDGE END IS A NODE NAME, AND THEY SHARE ONE SHAPE
                # (F-117). It used to be a bare string: the schema ACCEPTED
                # as an edge end ('', '   ', a name longer than 64) exactly
                # what it REJECTED as a node name, even though an edge must
                # point at a node (`connect.graph_validate`, KIR-L003).
                "from": _node_id_schema(), "to": _node_id_schema(),
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
            props[p.name] = _region_schema()
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
            # The cardinality depends on the operation and belongs to the
            # runtime validator. The same contract here keeps constrained
            # decoding from rejecting a valid translation, or from
            # promising an angular dimension that the compiler is bound to
            # reject.
            lo, hi, reject_dupes = _refs_w_contract(op.name)
            variants = [_element_id_selector()]
            if p.ref_kinds:
                variants.append(_string_selector("ref"))
            # THE SECOND STAGE (`{"by": "face", ...}`, `kir/faceref.py`) —
            # ONLY behind the operator's flag, and only for the named
            # carrier. The schema is fail-closed: as long as the variant is
            # absent here, constrained decoding physically cannot produce a
            # face selector, and that is exactly what the law of the
            # disabled flag requires — with the flag off, the schema must
            # be byte-for-byte the same as before.
            if (faceref.face_ref_enabled()
                    and (op.name, p.name) in _FACE_SEL_SITES):
                variants.append(_face_selector(variants))
            props[p.name] = {"type": "array", "minItems": lo, "maxItems": hi,
                             "items": {"oneOf": variants}}
            if reject_dupes:
                # Exact JSON repeats are a subset of the runtime's law of
                # repeats: the runtime also normalizes whitespace in a ref.
                # What is expressed here is the provable part, without
                # narrowing the language the compiler accepts.
                props[p.name]["uniqueItems"] = True
        elif p.kind == "str_long":
            # Documentation `content` (create_text): longer bound than "str"
            # (KIR_DOC_SPEC.md: "непустой, <= разумной длины").
            props[p.name] = {"type": "string", "minLength": 1,
                             "maxLength": _TEXT_CONTENT_MAX_CHARS}
        elif p.kind == "member_ops":
            # feat/native-groups: the group DEFINITION — 1..GROUP_MEMBERS_MAX
            # PRE-GROUNDED
            # member authoring ops.  Members carry the {"__grounded__": ...}
            # selector shape (built by the component-library bridge, not by a
            # raw LLM decode), so the schema stays permissive on the member's
            # own params (additionalProperties true) and requires only op+id;
            # authoring.validate does the structural member check, and the
            # geometric fidelity is proven offline (native_group.py).  This op
            # is a REBUILD op emitted by the bridge, not part of the raw
            # decode surface, so it never constrains free LLM generation.
            props[p.name] = {
                # 🔴 THE CEILING IS TAKEN FROM THE REGISTRY, NOT DIALED IN
                # HERE (F-190, 29.08.2026). It used to be 200 while
                # `spec.GROUP_MEMBERS_MAX = 1000`: a program with 201
                # members passed `authoring_validation`, but was rejected by
                # the schema the MODEL reads. Measured at `spec.py:132-141`:
                # live K6/K3 groups reach 302-318 members — the mismatch hit
                # an existing scenario.
                "type": "array", "minItems": 1,
                "maxItems": spec.GROUP_MEMBERS_MAX,
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string"},
                        "id": _op_id_schema(),
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
            # wave/shape: the triangulated surface of create_directshape. ONE
            # object, not two parallel arrays — triangle indices are only
            # checkable together with their vertex array, and a schema that
            # allows one without the other invites exactly the class of bugs
            # where an absence turns into a zero. The limits are taken from
            # mesh.py, so the number lives in ONE place (where the
            # measurement backing it also lives).
            from kir.mesh import MAX_TRIANGLES, MAX_VERTICES
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
        elif p.kind == "surface":
            # wave/surface (2026-08-20): a SMOOTH NURBS surface. Alongside
            # the mesh, and NOT instead of it: a mesh is facets, a surface is
            # smooth, they have different laws, different witnesses, and a
            # different price.
            #
            # The input is CONTROL points, not interpolation points, and
            # this is decided by the REVERSE PASS:
            # `geom_extract.__gxNurbsSurface` reads exactly those. Had the
            # language taken interpolation, the round trip would not close
            # by construction, and OUR OWN approximation would stand between
            # the author and Revit. (For the contour edge the choice is the
            # OPPOSITE, and equally justified: there `sketch_extract` does
            # not read a spline at all, the shape is free, and its profile
            # is chosen by the LLM. See the block in `contour.py`.)
            #
            # Fields and limits are taken FROM `surface.py`, not as
            # literals: two numbers that must match drift apart silently,
            # and a schema that allows something OTHER than the validator
            # gives the model a refusal on a VALID program — paid for on
            # 16.08.2026 on the contour's shapes.
            from kir.surface import (
                MAX_CONTROL_POINTS, MAX_DEGREE, _FIELDS_OPTIONAL,
                _FIELDS_REQUIRED,
            )
            _num_list = {"type": "array", "items": {"type": "number"}}
            _surface_props = {
                "degree_u": {"type": "integer", "minimum": 1,
                             "maximum": MAX_DEGREE},
                "degree_v": {"type": "integer", "minimum": 1,
                             "maximum": MAX_DEGREE},
                "count_u": {"type": "integer", "minimum": 2},
                "count_v": {"type": "integer", "minimum": 2},
                "knots_u": _num_list,
                "knots_v": _num_list,
                "control_points_mm": {
                    "type": "array", "minItems": 4,
                    "maxItems": MAX_CONTROL_POINTS,
                    "items": {"type": "array", "minItems": 3, "maxItems": 3,
                              "items": {"type": "number"}},
                    "description": ("КОНТРОЛЬНЫЕ точки [x,y,z] в мм, порядком "
                                    "u-major (count_u рядов по count_v); "
                                    "поверхность через них НЕ проходит"),
                },
                "weights": {"type": "array",
                            "items": {"type": "number", "exclusiveMinimum": 0},
                            "description": ("веса рациональной поверхности; "
                                            "без них она нерациональная")},
            }
            _known = set(_FIELDS_REQUIRED) | set(_FIELDS_OPTIONAL)
            props[p.name] = {
                "type": "object",
                "properties": {k: v for k, v in _surface_props.items()
                               if k in _known},
                "required": list(_FIELDS_REQUIRED),
                "additionalProperties": False,
                "description": ("гладкая NURBS-поверхность. Строит DirectShape "
                                "— геометрию БЕЗ BIM-смысла: без типа, вне "
                                "спецификаций, вручную не редактируется"),
            }
        elif p.kind == "plane":
            props[p.name] = _plane_schema()
        elif p.kind == "solid_parts":
            # wave/boolean (2026-08-20): the OPERANDS of a boolean. The list
            # of shapes and the set of fields are taken FROM `ops_boolean`,
            # not as literals: a schema that allows something OTHER than the
            # validator gives the model a refusal on a VALID program, and
            # this was paid for on 16.08.2026 on the contour's shapes.
            #
            # `oneOf` on `shape` is not decoration: a box has a `size_mm`
            # field, a sphere has `radius_mm`, and a merged schema with all
            # fields at once would allow "a box with a radius." The
            # validator rejects that (an extra field is an error), so the
            # schema must reject it too.
            from kir.ops_boolean import (BOOLEAN_PARTS_MAX,
                                              BOOLEAN_PARTS_MIN, PART_FIELDS,
                                              PART_OPTIONAL_FIELDS, PART_SHAPES,
                                              part_extent_bounds)
            _lo, _hi = part_extent_bounds()
            _pt = {"type": "array", "minItems": 3, "maxItems": 3,
                   "items": {"type": "number"},
                   "description": "центр [x, y, z] в мм"}
            # 🔴 A PART'S CONTOUR AND PLANE ARE TAKEN FROM THE SAME BUILDERS
            # AS THE OP'S FIELD (`_region_schema`, `_plane_schema`), NOT
            # WRITTEN HERE A SECOND TIME. A prism part and
            # `create_solid_extrusion` are the same geometry; two schemas
            # for one geometry drift apart silently, and the cost is
            # measured on 16.08.2026: three programs out of three were valid
            # by the schema and rejected by the compiler.
            _field_schema = {
                "center_mm": _pt,
                "size_mm": {"type": "array", "minItems": 3, "maxItems": 3,
                            "items": {"type": "number", "minimum": _lo,
                                      "maximum": _hi},
                            "description": "размеры [dx, dy, dz] в мм"},
                "radius_mm": {"type": "number", "minimum": _lo / 2.0,
                              "maximum": _hi / 2.0},
                "height_mm": {"type": "number", "minimum": _lo,
                              "maximum": _hi},
                "profile": _region_schema(),
                "plane": _plane_schema(),
                "base_z_mm": {"type": "number", "minimum": -_hi,
                              "maximum": _hi,
                              "description": ("отметка плоскости профиля "
                                              "призмы; ВМЕСТЕ с plane не "
                                              "принимается")},
            }
            props[p.name] = {
                "type": "array",
                "minItems": BOOLEAN_PARTS_MIN - 1,
                "maxItems": BOOLEAN_PARTS_MAX - 1,
                "items": {"oneOf": [
                    {"type": "object",
                     "properties": dict(
                         {"shape": {"const": shape}},
                         **{f: _field_schema[f]
                            for f in (*PART_FIELDS[shape],
                                      *PART_OPTIONAL_FIELDS[shape])}),
                     "required": ["shape", *PART_FIELDS[shape]],
                     "additionalProperties": False}
                    for shape in PART_SHAPES]},
                "description": (
                    "операнды булевой. Три примитива (box/sphere/cylinder) "
                    "выровнены по осям мира — поворота у них нет, и это "
                    "отсутствие степени свободы, а не умолчание. Четвёртый род "
                    "prism — призма над КОНТУРОМ с явными точками, с "
                    "необязательной плоскостью эскиза: те же поля, что у "
                    "create_solid_extrusion, потому что это та же геометрия. "
                    "База берётся из profile+height_mm, части применяются к "
                    "ней слева направо. Каждая часть рождается и умирает "
                    "внутри опа: Solid в Revit не элемент, сослаться на него "
                    "соседним опом нельзя"),
            }
        elif p.kind == "wall_layers":
            # THE WALL'S LAYER STACK, OUTSIDE TO INSIDE — the same order in
            # which `CompoundStructure.GetLayers()` returns it.
            #
            # 🔴 THIS BRANCH WAS LATE BY ONE COMMIT, AND THE COST WAS SILENT.
            # `41b4bbc5` introduced the kind into `spec.PARAM_KINDS` (the
            # first lock let it through honestly) and did NOT write the
            # branch here — the third lock fired exactly as intended. But the
            # schema's consumer swallows the exception (`llm/tools.py`,
            # "schema injection must never break the tool list"), and
            # instead of crashing, the `revit_ir` tool DISAPPEARED from the
            # set: the KIR window could not write to Revit at all, and there
            # was not a single line about it in the journal — there was
            # nobody left to mention it. A neighboring session found it after
            # 45 minutes of silence, not a test.
            #
            # The limits are taken from the registry, not as literals: one
            # rule for both the validator and the schema, otherwise they
            # would drift apart at the very first edit — the named shape of
            # this tree's defect.
            props[p.name] = {
                "type": "array",
                "minItems": 1,
                "maxItems": WALL_LAYERS_MAX,
                "items": {
                    "type": "object",
                    "properties": {
                        "width_mm": {"type": "number",
                                     "minimum": WALL_LAYER_MIN_MM,
                                     "maximum": WALL_LAYER_MAX_MM},
                        "function": {"enum": list(WALL_LAYER_FUNCTIONS)},
                        "material": {"type": "string", "minLength": 1,
                                     "maxLength": 128},
                    },
                    "required": ["width_mm", "function"],
                    "additionalProperties": False,
                },
                "description": (
                    "пирог стены СНАРУЖИ ВНУТРЬ. Слой: толщина в мм, функция "
                    "и НЕОБЯЗАТЕЛЬНОЕ имя материала. Отсутствие ключа "
                    "`material` — законный слой без материала "
                    "(`InvalidElementId` в Revit); пустая строка им НЕ "
                    "является. Толщина 0 законна и означает мембрану"),
            }
        else:  # pragma: no cover — the second of three locks, see below
            # AN HONEST DESCRIPTION OF THE LOCK. This used to say "registry
            # lint keeps kinds closed" — a reference to a guarantee that DID
            # NOT EXIST: `spec._lint_registry` checked the capability cells,
            # effects, results, and snapshot pools, and knew nothing about
            # `ParamSpec.kind`. The comment claimed a dict was closed when it
            # was actually open — exactly the kind of defect that the
            # `raise` itself guards against.
            #
            # Since 07.08.2026 the dict IS ACTUALLY closed
            # (`spec.PARAM_KINDS`, checked when the registry is imported),
            # and now there is something to refer to. But this lock remains
            # INDEPENDENT and therefore not redundant: it catches a kind for
            # which no schema branch is written, even if the kind is
            # honestly named in the dict. The three passes — importing the
            # registry, assembling the schema, parsing a program — fail for
            # three different reasons.
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
    from kir.compiler import DEFAULTABLE
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
            "lineage": {
                "type": "string", "minLength": 1, "maxLength": 64,
                # ECMAScript-compatible absolute end; `$` alone admits a final newline.
                "pattern": r"^[A-Za-z0-9._:-]+(?![\s\S])",
                "description": "Stable program identity for native type ownership; not permission to overwrite.",
            },
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
            # 🔴 MACRO-SCHEMA NUMBERS ARE TAKEN FROM THE EXPANDER (F-117).
            # Here they used to be typed in by hand; on `dx_mm`/`dy_mm` the
            # pair had ALREADY DRIFTED (a schema with no bounds against
            # `100..100000` in `macros`), the rest matched by coincidence and
            # were held together by nothing.
            "levels": {"type": "integer", "minimum": 1,
                       "maximum": _macros.MAX_STACK_LEVELS},
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
            "nx": {"type": "integer", "minimum": 0,
                   "maximum": _macros.MAX_GRID_AXIS},
            "ny": {"type": "integer", "minimum": 0,
                   "maximum": _macros.MAX_GRID_AXIS},
            "dx_mm": {"type": "number",
                      "minimum": _macros.GRID_SPACING_MIN_MM,
                      "maximum": _macros.GRID_SPACING_MAX_MM},
            "dy_mm": {"type": "number",
                      "minimum": _macros.GRID_SPACING_MIN_MM,
                      "maximum": _macros.GRID_SPACING_MAX_MM},
            "origin_mm": {"type": "array", "minItems": 2, "maxItems": 2,
                           "items": {"type": "number"}},
            "margin_mm": {"type": "number"},
            "prefix_x": {"type": "string", "maxLength": 8},
            "prefix_y": {"type": "string", "maxLength": 8},
        }, "required": ["op"], "additionalProperties": False},
        {"type": "object", "properties": {
            "op": {"const": "series"},
            "id": {"type": "string", "minLength": 1, "maxLength": 64},
            "count": {"type": "integer", "minimum": 1,
                      "maximum": _macros.MAX_SERIES_COUNT},
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
                "type": "array", "minItems": 1,
                "maxItems": _macros.MAX_SERIES_OPS,
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
