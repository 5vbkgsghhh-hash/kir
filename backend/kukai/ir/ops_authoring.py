"""ops_authoring — v1 core: query + authoring + modify + architectural (wall/floor/roof/stairs/...).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

#: ``create_wall.location_line`` spelled out <-> Revit's ``WallLocationLine``
#: ordinals, which is what ``WALL_KEY_REF_PARAM`` stores.  ONE table, shared by
#: the emitter (word -> ordinal) and the lift (ordinal -> word), so the two
#: directions cannot drift apart.  Order is Revit's, and the tests pin it.
WALL_LOCATION_LINE_ORDINALS = {
    "wall_centerline": 0,
    "core_centerline": 1,
    "finish_face_exterior": 2,
    "finish_face_interior": 3,
    "core_exterior": 4,
    "core_interior": 5,
}

WALL_LOCATION_LINE_NAMES = {
    ordinal: name for name, ordinal in WALL_LOCATION_LINE_ORDINALS.items()
}

OPS = [
    OpSpec(
            name="query_count",
            effect=EffectKind.READ,
            result=RESULT_QUERY,
            family="query",
            params=(
                ParamSpec("kind", "kind_enum", required=True),
                ParamSpec("where", "filters"),
                # group_by (DRAFT, unapplied to prod tree — compiler.py is
                # foreign-dirty this wave): closed set, reuses the exact
                # field vocabulary query_list.fields/_emit_row already know
                # (minus "id", degenerate for grouping — always unique).
                ParamSpec("group_by", "enum",
                          choices=("name", "category", "type_name", "level_name")),
            ),
            capability=(("count", "category"), ("count", "element"), ("count", "link")),
            post=("result.count == number of model elements matching kind+where "
                  "at execution time; when group_by is given, result.groups = "
                  "[{key, count}, ...] partitions the SAME elements by that "
                  "field (result.count stays the ungrouped total)"),
        ),
    OpSpec(
            name="query_list",
            effect=EffectKind.READ,
            result=RESULT_QUERY,
            family="query",
            params=(
                ParamSpec("kind", "kind_enum", required=True),
                ParamSpec("where", "filters"),
                ParamSpec("fields", "fields", default=list(LIST_FIELDS)),
                ParamSpec("limit", "int", default=LIST_LIMIT_DEFAULT, min_val=1, max_val=LIST_LIMIT_MAX),
            ),
            capability=(("list", "category"), ("list", "element"), ("list", "link"),
                        ("list", "level"), ("list", "view"), ("list", "sheet")),
            post="result.rows = requested fields per matching element; result.total independent of limit",
        ),
    OpSpec(
            name="query_inspect",
            effect=EffectKind.READ,
            result=RESULT_QUERY,
            family="query",
            params=(
                ParamSpec("target", "target", required=True),
            ),
            capability=(("inspect", "element"),),
            post="result = fields+bbox_mm of exactly one element, or a typed not_found/ambiguous result",
        ),
    OpSpec(
            name="query_types",
            effect=EffectKind.READ,
            result=RESULT_QUERY,
            family="query",
            params=(
                # Closed enum, NOT a free string: exactly the snapshot pools
                # serving.py's _SNAPSHOT_CS actually collects live (16 —
                # "levels" plus every type/family-symbol pool; "grids" is a
                # geometry-bearing CONTOUR grounding pool, not a type pool).
                # Reusing the generic "enum" ParamSpec kind (schema_gen.py already
                # lowers it to {"type":"string","enum":[...]}) rather than adding
                # a new kind string — no new schema_gen/compiler branch needed
                # beyond this op's own validate/emit.
                ParamSpec("pool", "enum", required=True, choices=(
                    "levels", "wall_types", "floor_types", "roof_types",
                    "pipe_types", "piping_system_types",
                    "duct_types", "duct_system_types", "cable_tray_types",
                    "column_symbols_structural", "column_symbols_architectural",
                    "window_symbols", "door_symbols", "family_symbols",
                    "beam_types", "foundation_symbols",
                )),
            ),
            capability=(("list", "category"), ("list", "element")),
            # fix/g102-disambiguate (2026-07-17): the G102-AMBIGUOUS enumeration
            # companion (REGISTRY_MODULES.md / ground.py Sel<K> resolution). When
            # a by=name selector refuses KIR-G102 (several types/families share
            # one name — routine in real MEP projects: several duct/cable-tray
            # types both called "По умолчанию"), the caller now gets {id, name}
            # candidates on the refusal itself (ground.py fix, same commit) —
            # this op is the STANDALONE, ask-first counterpart: "what types of
            # X exist in this project" BEFORE attempting a name selector at
            # all, so the model can pick the right element_id up front instead
            # of round-tripping through a refusal. Reads the SAME closed pool
            # namespace authoring ops already ground selectors against
            # (known_pools, spec.py); no new snapshot pool, no document write.
            post=("result.rows = [{id, name}, ...] for every element in the "
                  "requested type/family-symbol pool (same identity space "
                  "authoring ops' Sel<K> by=name/by=element_id resolve "
                  "against); result.total == len(rows)"),
        ),
    OpSpec(
            name="create_wall",
            effect=EffectKind.CREATE,
            result=RESULT_WALL,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xy", required=True),
                ParamSpec("p1_mm", "pt_xy", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("height_mm", "mm", default=DEFAULTS["wall"]["height_mm"],
                          min_val=1, max_val=100_000),
                ParamSpec("type", "sel"),          # omitted -> doc default wall type (echoed)
                # Curve-IR (P4-B): optional canonical Arc dict. Absent -> a
                # straight Line.CreateBound wall exactly as before (byte-stable).
                # Present -> Arc.Create; p0_mm/p1_mm must equal the arc endpoints
                # and stay the grounding/hosting anchor.
                ParamSpec("arc", "arc"),
                # audit F6: vertical attributes.  base_offset_mm — the wall
                # base's offset from its level (WALL_BASE_OFFSET; parapets /
                # retaining walls).  NO default: absent stays absent, every
                # pre-existing wall program/hash/emitted C# is byte-stable.
                ParamSpec("base_offset_mm", "mm", min_val=-15_000, max_val=15_000),
                # location_line — the wall's location-line RULE, carried so
                # the round trip stops dropping it.  Measured on live Revit
                # 2023 (docs/2026-07-28-location-line-measurement.md), because
                # the obvious reading of this field is wrong: p0/p1 are ALWAYS
                # the wall's centre plane — the LocationCurve Revit's API
                # returns sits at the middle of the body under every ordinal,
                # on all 724 non-centreline walls of the operator's facade
                # model.  The rule decides which plane stays put when the
                # thickness LATER changes (measured: retyping 200mm -> 400mm
                # under finish_face_exterior holds that face and slides the
                # curve 100mm), so it is deferred state, not a placement.
                # Names are language-neutral (INVARIANT #1): a Russian Revit
                # reports the same ordinal.  NO default — absent stays absent,
                # so every pre-existing wall program stays byte-stable.
                # The core planes stay out of `choices` for now: the same
                # measurement voided the old reason (no offset is involved for
                # ANY ordinal, so nothing needs the type's compound structure),
                # but adding them CHANGES THE LIFT — 147 ordinal-5 walls in
                # that one model stop being atoms — and that deserves its own
                # coverage measurement rather than a ride on this fix.
                ParamSpec("location_line", "enum",
                          choices=("wall_centerline",
                                   "finish_face_exterior",
                                   "finish_face_interior")),
                # top_level — top constraint: given => the wall top is ATTACHED
                # to that level (WALL_HEIGHT_TYPE = level id, WALL_TOP_OFFSET
                # 0); absent => the exact pre-existing unconnected-height
                # emission.  height_mm stays required either way (its in-txn
                # ±1mm witness then doubles as a consistency check: a height
                # that contradicts the attached constraint is a typed
                # rollback, never a silently different wall).
                ParamSpec("top_level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # Wall-fidelity (live A5 evidence 2026-07-21): top_offset_mm —
                # the attached top's offset from top_level (WALL_TOP_OFFSET), a
                # DEFINING DOF of the attach.  Meaningful only WITH top_level
                # (emitter ignores it otherwise); NO default — absent keeps the
                # historical «attach at offset 0» emission byte-stable.
                ParamSpec("top_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"), ("create", "category")),
            post=("wall exists; LocationCurve endpoints == p0/p1 (±5mm); "
                  "arc curve == arc dict when supplied (center/radius ±1mm); "
                  "base constraint == resolved level (topology, day-1); "
                  "height param == height_mm (±1mm) when top_level is not "
                  "given (measured 29.07.2026: WALL_USER_HEIGHT_PARAM is not "
                  "the source of truth once a top constraint is attached, "
                  "and an omitted height_mm silently carries the registry "
                  "default — the attached case is instead pinned by the top "
                  "constraint check below plus the pre-commit base<top "
                  "guard); "
                  "base offset param == base_offset_mm when given (±1mm); "
                  "location line rule == location_line when given "
                  "(semantic: правило записывается в WALL_KEY_REF_PARAM и НЕ "
                  "смещает тело стены — тело стоит симметрично оси p0/p1 при "
                  "любом ординале, а правило решает лишь, какая плоскость "
                  "останется на месте при последующей смене толщины); "
                  "top constraint == resolved top_level when given (topology); "
                  "top offset param == top_offset_mm when given (±1mm)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "wall_types", False),
                      ("top_level", "levels", False)),
            # A2: exact historical emitter literals (byte-parity).
            tolerances={"endpoint_mm": 5.0, "height_mm": 1.0,
                        "arc_mm": 1.0, "base_offset_mm": 1.0,
                        "top_offset_mm": 1.0},
        ),
    OpSpec(
            name="create_pipe",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),   # omitted -> sole snapshot entry, else AMBIGUOUS
                ParamSpec("pipe_type", "sel"),     # same rule
                ParamSpec("diameter_mm", "mm", min_val=5, max_val=2_000),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("pipe exists; LocationCurve endpoints == p0/p1 (±5mm, 3D); "
                  "reference level == resolved level (topology); "
                  "diameter param == diameter_mm (±0.5mm) when given"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "piping_system_types", False),
                      ("pipe_type", "pipe_types", False)),
            tolerances={"endpoint_mm": 5.0, "diameter_mm": 0.5},
        ),
    OpSpec(
            name="create_grid",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xy", required=True),
                ParamSpec("p1_mm", "pt_xy", required=True),
                ParamSpec("name", "str"),          # duplicate grid name -> typed rollback
            ),
            capability=(("create", "grid"),),
            post=("grid exists; curve endpoints == p0/p1 (±5mm); "
                  "Name == name when given"),
            writes_model=True,
            grounded=(),
            tolerances={"endpoint_mm": 5.0},
        ),
    OpSpec(
            name="create_level",
            effect=EffectKind.CREATE,
            result=RESULT_LEVEL,
            family="authoring",
            params=(
                ParamSpec("elev_mm", "num", required=True, min_val=-1_000_000, max_val=1_000_000),
                ParamSpec("name", "str"),          # duplicate level name -> typed rollback
            ),
            capability=(("create", "level"),),
            post="level exists; Elevation == elev_mm (±1mm); Name == name when given",
            writes_model=True,
            grounded=(),
            tolerances={"elevation_mm": 1.0},
        ),
    OpSpec(
            name="set_param",
            effect=EffectKind.MUTATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="modify",
            params=(
                ParamSpec("target", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                ParamSpec("param", "str", required=True),
                ParamSpec("value", "value", required=True),
            ),
            capability=(("set_param", "parameter"), ("set_param", "element")),
            post=("parameter holds the requested value post-commit (re-read, "
                  "±tol for lengths); unknown/read-only param == typed rollback"),
            writes_model=True,
            grounded=(),
            # 03.08: у «±tol» появился адрес.  `length_mm` — ветка value(mm),
            # `double_abs` — эпсилон сравнения сырого double.  Оба числа ТЕ
            # ЖЕ, что стояли литералами в _emit_setparam.
            tolerances={"length_mm": 0.5, "double_abs": 1e-06},
        ),
    OpSpec(
            name="create_floor",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("outline", "pts", required=True),          # >=3 [x,y] mm, closed ring implied
                ParamSpec("holes", "pts_list"),                       # 2022+ only (KIR-E003 on 2021)
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("type", "sel"),          # omitted -> doc default floor type (echoed)
                ParamSpec("structural", "bool", default=False),       # foundation slab = structural floor
                # P1 DOF-completeness: смещение пола от уровня
                # (FLOOR_HEIGHTABOVELEVEL_PARAM) — на «демо» 51% полов
                # смещены.  NO default: absent = историческая эмиссия.
                ParamSpec("height_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"),),
            post=("floor exists; level binding == resolved level (topology); "
                  "bbox XY extents == outline extents (±50mm); "
                  "structural flag == requested (semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "floor_types", False)),
            tolerances={"bbox_mm": 50.0, "height_offset_mm": 1.0},
        ),
    OpSpec(
            name="create_roof",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("outline", "pts", required=True),           # footprint, ring implied
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("type", "sel"),          # omitted -> doc default roof type (echoed)
                # slopes — per-EDGE pitch, parallel to `outline`: entry i
                # applies to the edge from outline[i] to outline[i+1], null
                # meaning that edge stays level.  This is exactly how Revit
                # models a footprint roof (DefinesSlope + SlopeAngle per
                # boundary curve), and it is the only shape that can express
                # both a gable (two sloped edges) and a hip (all of them).
                # Absent => the historical flat roof, byte-for-byte.
                ParamSpec("slopes", "slopes"),
            ),
            capability=(("create", "element"),),
            post=("footprint roof exists; base level == resolved level (topology); "
                  "bbox XY extents == outline extents (±50mm)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "roof_types", False)),
            tolerances={"bbox_mm": 50.0},
        ),
    OpSpec(
            name="create_stairs",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xy", required=True),           # run start (base level)
                ParamSpec("p1_mm", "pt_xy", required=True),           # run direction/end
                ParamSpec("base_level", "sel", required=True),
                ParamSpec("top_level", "sel", required=True),
                ParamSpec("width_mm", "mm", min_val=600, max_val=5_000),
            ),
            capability=(("create", "element"),),
            post=("stairs exist; base/top level == resolved levels (topology); "
                  ">=1 run created; width_mm held ±5mm when supplied; MUST be the sole op of its program "
                  "(StairsEditScope owns its transactions — KIR-L002 otherwise)"),
            writes_model=True,
            grounded=(("base_level", "levels", True), ("top_level", "levels", True)),
            # 03.08: обещанные ±5 мм ширины марша.  Число то же, что стояло
            # литералом в emit_stairs_program.
            tolerances={"width_mm": 5.0},
        ),
    OpSpec(
            name="create_column",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("xy", "pt_xy", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("category", "enum", default="structural",
                          choices=("structural", "architectural")),
                ParamSpec("symbol", "sel"),        # omitted -> sole snapshot entry, else AMBIGUOUS
                ParamSpec("rotation_deg", "deg", default=0.0),
                # top_xy — the column's TOP plan position.  Present and the
                # column is SLANTED: Revit models that as a location CURVE
                # from base to top, not a point, so the emitter switches to
                # the Line overload of NewFamilyInstance.  A slanted column
                # needs a defined top, so top_xy requires top_level; the
                # compiler enforces that rather than inventing an elevation.
                # NO default: absent stays absent and every existing column
                # program emits byte-identical C#.
                ParamSpec("top_xy", "pt_xy"),
                # P1 DOF-completeness (fidelity audit 2026-07-21): столбовая
                # вертикаль — на «демо» 100% колонн top-attached, 99% с
                # base-offset.  NO default: absent = историческая эмиссия
                # байт-в-байт (as-placed высота символа).
                ParamSpec("base_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
                ParamSpec("top_level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("top_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"), ("create", "category")),
            post=("column exists; LocationPoint == xy (±5mm); "
                  "rotation == rotation_deg (±0.1deg, modulo 360); "
                  "StructuralType matches category (semantic); base level "
                  "== resolved level (topology, BIP chain)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("symbol", "column_symbols_{category}", False),
                      ("top_level", "levels", False)),
            # rotation_deg (03.08): `post` обещал ±0.1deg, а реестр назвать
            # это число не мог.  В C# допуск стоит ВЫРАЖЕНИЕМ
            # `Math.PI / 1800.0` — делитель считается из этих 0.1
            # (Tolerance.deg_rad_divisor), поэтому байты прежние.
            tolerances={"location_mm": 5.0, "rotation_deg": 0.1,
                        "base_offset_mm": 1.0, "top_offset_mm": 1.0},
        ),
    OpSpec(
            name="create_window",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("host", "target_w", required=True,
                          ref_kinds=(ReferenceKind.WALL,)),
                ParamSpec("offset_mm", "mm", required=True, min_val=0, max_val=100_000),
                # max widened 3_000 -> 100_000 (audit F1): on a multi-storey/
                # facade host wall the sill is measured from the WALL's base
                # level, so an upper-storey window legitimately carries a
                # multi-metre sill.
                ParamSpec("sill_mm", "mm", default=900.0, min_val=0, max_val=100_000),
                ParamSpec("symbol", "sel"),
                # audit F5: swing/mirror state.  Optional bools; an absent flag
                # stays implicit (validate's bool rule: "default stays
                # implicit"), so every pre-existing window program, hash and
                # emitted C# is byte-stable.  The emitter clones place_family's
                # enforced-state pattern (CanFlip* guards, MirrorElements).
                ParamSpec("mirrored", "bool", default=False),
                ParamSpec("hand_flipped", "bool", default=False),
                ParamSpec("facing_flipped", "bool", default=False),
            ),
            capability=(("create", "element"),),
            post=("window exists; Host.Id == host wall id (topology); "
                  "LocationPoint == p0+dir*offset at level+sill (±10mm); "
                  "Mirrored/HandFlipped/FacingFlipped equal requested states "
                  "when given (semantic)"),
            writes_model=True,
            grounded=(("symbol", "window_symbols", False),),
            tolerances={"location_mm": 10.0},
        ),
    OpSpec(
            name="create_door",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("host", "target_w", required=True,
                          ref_kinds=(ReferenceKind.WALL,)),
                ParamSpec("offset_mm", "mm", required=True, min_val=0, max_val=100_000),
                # Optional vertical anchor from the HOST wall's level (audit
                # F1: a door on a multi-storey wall sits above the wall's base
                # level).  NO default: an absent sill stays absent, so every
                # pre-existing door program/hash/emitted C# is byte-stable.
                # min widened 0 -> -100_000 (layer-3 audit on SOB6.2 R23): the
                # sill is measured from the host wall's LEVEL, and a wall whose
                # WALL_BASE_OFFSET is negative begins below that level, so a
                # door set at the finished floor sits below the level while
                # staying wholly inside the wall.  140 of that building's 151
                # doors are negative (131 at -100mm); the old bound turned
                # 92.7% of them into atoms.  Sign is not a defect signal — the
                # witness checks the resulting LocationPoint (±10mm).
                ParamSpec("sill_mm", "mm", min_val=-100_000, max_val=100_000),
                ParamSpec("symbol", "sel"),
                # audit F5: дверь без створки — не та дверь.  Same optional
                # bools as create_window/place_family; absent stays implicit
                # (byte-stable pre-existing programs), the emitter enforces the
                # requested swing/mirror state with CanFlip* guards.
                ParamSpec("mirrored", "bool", default=False),
                ParamSpec("hand_flipped", "bool", default=False),
                ParamSpec("facing_flipped", "bool", default=False),
            ),
            capability=(("create", "element"),),
            post=("door exists; Host.Id == host wall id (topology); "
                  "LocationPoint == p0+dir*offset at host level+sill (±10mm); "
                  "Mirrored/HandFlipped/FacingFlipped equal requested states "
                  "when given (semantic)"),
            writes_model=True,
            grounded=(("symbol", "door_symbols", False),),
            tolerances={"location_mm": 10.0},
        ),
    OpSpec(
            name="create_room",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("xy", "pt_xy", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("name", "str"),
            ),
            capability=(("create", "room_space"),),
            post=("room exists and has nonzero enclosed area; LevelId == resolved "
                  "level (topology); LocationPoint == xy (±5mm); Name == name "
                  "when given; placed AFTER doc.Regenerate() when walls precede (v0 rule)"),
            writes_model=True,
            grounded=(("level", "levels", True),),
            tolerances={"location_mm": 5.0},
        ),
    OpSpec(
            # Семейство ставится ЛИБО в точку, ЛИБО по кривой — Revit даёт
            # для этого две разные перегрузки NewFamilyInstance, и выбор
            # между ними определяется тем, что за семейство поставлено:
            # у CurveBased-экземпляра нет LocationPoint вообще.
            #
            # Отсюда `xyz` перестал быть обязательным на уровне СХЕМЫ, а
            # взаимное исключение переехало в компилятор типизированным
            # отказом (KIR-P007): «одно из двух» схемой не выражается, а
            # молча угадывать за автора — ровно то, что этот компилятор
            # запрещает.
            #
            # Кривая записывается парой p0_mm/p1_mm — тем же способом, что у
            # create_beam / create_pipe / create_cable_tray. Второго способа
            # записать отрезок в этом реестре быть не должно.
            #
            # Повод замерен (ЭОМ SKLNK R2026): 79 экземпляров, весь остаток
            # дыры этой модели, все CurveBased, у всех живой LocationCurve.
            name="place_family",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("xyz", "pt_xyz"),
                ParamSpec("p0_mm", "pt_xyz"),
                ParamSpec("p1_mm", "pt_xyz"),
                # Хост у кривого варианта — не украшение, а требование Revit.
                # ЗАМЕРЕНО 27.07 на живой модели ЭОМ двумя пробами:
                #   * NewFamilyInstance(Curve, symbol, LEVEL, …) кладёт кривую
                #     на плоскость уровня. Исходный отрезок кожуха лотка
                #     вертикальный ([...,565]→[...,4910]) и схлопнулся в точку
                #     ([...,0]→[...,0]). Переданный уровень Revit к тому же
                #     проигнорировал: LevelId остался -1;
                #   * NewFamilyInstance(REFERENCE, Line, symbol) — верная
                #     перегрузка, и она проверяет настоящее отношение:
                #     «Family cannot be placed on this line as it does not
                #     coincide with the input face», когда отрезок не лежит
                #     на грани хоста.
                # Отсюда же следует порядок пересборки: сначала хост, потом
                # то, что на нём висит — ровно как у двери и окна.
                ParamSpec("host", "target_w",
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                ParamSpec("level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("symbol", "sel"),        # omitted -> sole snapshot entry
                ParamSpec("rotation_deg", "deg", default=0.0),
                ParamSpec("mirrored", "bool", default=False),
                ParamSpec("hand_flipped", "bool", default=False),
                ParamSpec("facing_flipped", "bool", default=False),
            ),
            capability=(("place", "family"), ("place", "element")),
            post=("instance exists; LocationPoint == xyz (±5mm) OR "
                  "LocationCurve endpoints == p0_mm/p1_mm (±5mm) for the "
                  "curve variant; rotation == rotation_deg (±0.1deg, modulo "
                  "360); Mirrored/HandFlipped/FacingFlipped equal requested "
                  "states; level binding == resolved level (topology, BIP "
                  "chain)"),
            writes_model=True,
            # Уровень перестал быть безусловно обязательным: у кривого
            # варианта его нет ни в источнике (все 79 кожухов ЭОМ имеют
            # LevelId = -1), ни в вызове (перегрузка по ссылке уровня не
            # принимает). Обязательность стала УСЛОВНОЙ и живёт в плане
            # компилятора, где её можно выразить: точечный вариант требует
            # уровень, кривой — хост.
            grounded=(("level", "levels", False),
                      ("symbol", "family_symbols", False)),
            # rotation_deg — та же поправка, что у create_column выше.
            tolerances={"location_mm": 5.0, "rotation_deg": 0.1},
        ),
    OpSpec(
            name="delete",
            effect=EffectKind.DELETE,
            result=RESULT_DELETED_ELEMENT,
            family="modify",
            params=(
                ParamSpec("target", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
            ),
            capability=(("delete", "element"),),
            post=("element no longer resolvable post-commit; requires envelope "
                  "allow_destructive=true (policy-gate on the plan, SPEC 12.2)"),
            writes_model=True,
            grounded=(),
        ),
    OpSpec(
            # CLASH-починка, оп 1/2 (28.07, стратегия оператора: ранний
            # честный релиз). Перенос СВЯЗНОГО ПОДГРАФА целиком —
            # ElementTransformUtils.MoveElements(doc, ICollection<ElementId>,
            # XYZ) двигает набор ОДНИМ вызовом, и Revit тянет фитинги и
            # СОХРАНЯЕТ соединения (в отличие от перемещения по одному
            # элементу, где связи рвутся и перевосстанавливаются). Сигнатура
            # проверена рефлексией по RevitAPI.dll всех шести версий —
            # идентична 2021..2026.
            #
            # targets — тот же id-pinned/ref-only узор, что host у двери и
            # окна (28.07) и refs у create_dimension: снапшот-пула элементов
            # произвольной категории не существует. Верхняя граница 500 —
            # практический потолок одной программы (её же MAX_OPS не
            # относится к элементам ВНУТРИ одного опа), не измеренный лимит
            # Revit API.
            name="move_elements",
            effect=EffectKind.MUTATE,
            result=RESULT_MOVED_ELEMENTS,
            family="modify",
            params=(
                # 28.07 SRC PIN (live schema_gen collision): reuses the
                # EXISTING recognized kinds (refs_w/pt_xyz), never a new
                # kind — schema_gen.py's kind-switch is exhaustive and
                # foreign-dirty (cannot be edited to learn a new one).
                # refs_w's shared bounds (2..16, no-duplicate) stay
                # UNCHANGED for create_dimension; move_elements gets its
                # own 1..500/duplicates-allowed rule by OP NAME inside
                # validate()'s refs_w branch — see authoring.py.
                ParamSpec("targets", "refs_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                # pt_xyz: schema-recognized 3-number shape; the tighter
                # |component|<=100_000 + nonzero rule is a move_elements-
                # only post-check in validate() (same by-name-override
                # discipline, not a change to pt_xyz's own bound).
                ParamSpec("delta_mm", "pt_xyz", required=True),
            ),
            capability=(("move", "element"),),
            post=("every target with a LocationPoint/LocationCurve shifted "
                  "by delta_mm exactly (±1mm, geometry, snapshotted before "
                  "the move — scope contract); total CONNECTED connector "
                  "count summed over targets unchanged (topology, "
                  "ConnectorManager — MEPCurve.ConnectorManager or "
                  "FamilyInstance.MEPModel.ConnectorManager, elements "
                  "without either honestly skip this obligation); slope "
                  "(end1.Z-end0.Z) of every LocationCurve target unchanged "
                  "(semantic, re-read — a uniform translation cannot change "
                  "it, but the witness confirms rather than assumes); "
                  "pinned element or stale id is a typed refusal, never a "
                  "live exception"),
            writes_model=True,
            grounded=(),
            tolerances={"location_mm": 1.0},
        ),
    OpSpec(
            # CLASH-починка, оп 2/2. Element.ChangeTypeId(ElementId) —
            # сигнатура и семантика возврата подтверждены XML-документацией,
            # отгруженной ВНУТРИ NuGet-пакета сборки (RevitAPI.xml, не вики):
            # возврат — InvalidElementId в ОБЫЧНОМ случае (тип сменился НА
            # МЕСТЕ, тот же элемент), и НАСТОЯЩИЙ ElementId только в редком
            # случае, когда Revit создаёт НОВЫЙ элемент взамен (стена <->
            # витражная панель — единственный документированный пример).
            # Несовместимость типа — это БРОШЕННОЕ ArgumentException, не
            # возврат InvalidElementId (наивное «Invalid = отказ» перепутало
            # бы обычный успех с провалом). Идентична на всех шести версиях
            # (since="2011" в самой документации).
            #
            # type — element_id обязателен в v1: пула типов по ВСЕМ
            # категориям не существует (тот же пробел, что закрыл
            # panel_type у set_curtain_panel ограниченным коллектором —
            # здесь коллектор невозможен в принципе, потому что категория
            # цели заранее неизвестна компилятору). Честно объявлено
            # ограничением, а не тихой недостачей.
            name="change_type",
            effect=EffectKind.MUTATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="modify",
            params=(
                ParamSpec("target", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                ParamSpec("type", "target_w", required=True),
            ),
            capability=(("set_type", "element"),),
            post=("GetTypeId() == requested type after Regenerate (semantic, "
                  "re-read — the rare new-element case re-reads the "
                  "RETURNED id, never the stale original); incompatible "
                  "type or an internal/grouped element is a typed refusal "
                  "(caught ArgumentException/InvalidOperationException/"
                  "ModificationForbiddenException), never a live exception"),
            writes_model=True,
            grounded=(),
        ),
    OpSpec(
            # Витражная панель НЕ создаётся отдельно — она существует только
            # как ЯЧЕЙКА сетки носителя (дизайн 2026-07-28). Поэтому оп не
            # «создать панель», а «назначить тип ячейке»: Revit делает это
            # ровно одним вызовом — CurtainGrid.ChangePanelType(panel, type),
            # присутствующим на всех шести версиях (замер по эталонным
            # сборкам 2021-2026, 28.07).
            #
            # u/v ОБЯЗАТЕЛЬНЫ. Сетка 1×1 — частный случай (0,0), а не
            # оправдание отсутствия адреса: без адреса вопрос «какую именно
            # ячейку менять» неответим, а угадывать этот компилятор права не
            # имеет. Адрес — РАНГ опорной линии разрезки, который отдаёт
            # Panel.GetRefGridLines: 0 = ячейка до первой линии, k = ячейка
            # за k-й линией по порядку. Порядок линий строится ИЗ ГЕОМЕТРИИ
            # (CURTAIN_CELL_ADDRESS_CS в authoring.py) и потому одинаков у
            # экстрактора и у эмиттера — иначе адрес не пережил бы
            # пересборку, где id линий другие.
            #
            # panel_type НЕ заземляется в пул: тип ячейки живёт СРАЗУ В ДВУХ
            # пространствах типов — PanelType/FamilySymbol (стеклопакет,
            # витражная дверь) и WallType (ячейка, заполненная стеной; в
            # фасадной модели замера таких 259 из 361). Ни один снапшот-пул
            # не покрывает объединение, а новый пул — изменение уровня Fable
            # (REGISTRY_MODULES.md), не самодеятельность этой волны. Поэтому
            # селектор разрешается В ЭМИССИИ ограниченным коллектором по
            # обоим пространствам, ровно как load_family разрешает семейство
            # по пути: ноль совпадений и больше одного — типизированные
            # отказы, никогда «первый попавшийся».
            # ЛИНИЯ РАЗРЕЗКИ — недостающее звено генератора витража.
            #
            # ЗАМЕР НОЧИ 28.07 (child_closure_20260728.json): замыкание
            # детей 417/1556 = 27%, и у ВСЕХ пересобранных носителей НОЛЬ
            # внутренних U/V линий при БАЙТ-ИДЕНТИЧНЫХ типах. Это и есть
            # диагноз: раскладка сетки — состояние, которое create_wall не
            # несёт, и без него у носителя нет ни ячеек, ни импостов, ни
            # панелей — то есть вся его семья детей не воспроизводится.
            #
            # Конструктор ровно один: CurtainGrid.AddGridLine(isUGridLine,
            # position, oneSegmentOnly) -> CurtainGridLine (RevitAPI.xml и
            # CHM эталонного пакета; присутствует на всех шести версиях,
            # замер 29.07). Отсюда и параметры: направление — булев
            # isUGridLine, поэтому у опа закрытое перечисление u|v, а не
            # свободная строка; позиция — ТОЧКА, через которую линия
            # проходит, в мировых мм.
            #
            # oneSegmentOnly=false зашит: сегментами линия правится
            # отдельными вызовами (AddSegment/RemoveSegment), и оп, который
            # молча ставил бы один сегмент, был бы не «линией разрезки», а
            # догадкой о ней.
            name="create_curtain_grid_line",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("host", "target_w", required=True,
                          ref_kinds=(ReferenceKind.WALL,)),
                ParamSpec("direction", "enum", required=True,
                          choices=("u", "v")),
                ParamSpec("position_mm", "pt_xyz", required=True),
            ),
            capability=(("create", "curtain_grid_line"),),
            post=("grid line created on the host curtain grid or typed "
                  "refusal; the line is re-read BY ITS OWN ID after "
                  "Regenerate: it belongs to this grid (membership in "
                  "GetU/VGridLineIds — model read, not the call's echo), its "
                  "direction == requested (IsUGridLine), and the requested "
                  "position lies on its FullCurve within position_mm "
                  "tolerance"),
            writes_model=True,
            grounded=(),
            # Допуск свидетеля один: линия обязана ПРОЙТИ через
            # запрошенную точку. Радиус, в котором импост считается «на этой
            # линии», сюда не входит осознанно — это улика для квитанции
            # (сам ли тип носителя ставит импосты), а не обязательство, и
            # реестр допусков свидетелей не должен делать вид, что она им.
            tolerances={"position_mm": 25.0},
        ),
    OpSpec(
            name="set_curtain_panel",
            effect=EffectKind.MUTATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="modify",
            params=(
                ParamSpec("host", "target_w", required=True,
                          ref_kinds=(ReferenceKind.WALL,)),
                ParamSpec("u", "int", required=True, min_val=0, max_val=4_096),
                ParamSpec("v", "int", required=True, min_val=0, max_val=4_096),
                ParamSpec("panel_type", "sel", required=True),
            ),
            capability=(("set_type", "element"),),
            post=("cell (u,v) of the host curtain grid resolves or typed "
                  "refusal; effective panel type in cell (u,v) == panel_type "
                  "post-commit (semantic, re-read by cell address, never the "
                  "call's echo); cell host == host (topology)"),
            writes_model=True,
            grounded=(),
        ),
    OpSpec(
            # Native Revit group of a repeated component (feat/native-groups):
            # author the member ops ONCE (the definition, at occurrence 0's
            # absolute coords), doc.Create.NewGroup them, then PlaceGroup at each
            # further occurrence's offset. The rebuild edits like a live
            # modeller's (edit one instance, all update) instead of N loose
            # elements. members are PRE-GROUNDED authoring ops (element_id /
            # absolute coords — no name/ref resolution inside the group);
            # placements are per-additional-occurrence [dx,dy,dz] deltas
            # (occ_origin_k - occ_origin_0, ABSOLUTE origins subtracted — the
            # only origin-independent form; occurrence 0 IS the members). Emit
            # reads the group's live origin O0 and places at O0+delta. FAIL-
            # CLOSED: any member/NewGroup/PlaceGroup null refuses the whole
            # group op (its SubTransaction rolls back) so the caller falls back
            # to N loose elements — geometry never silently lost.
            name="create_group",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("members", "member_ops", required=True),
                ParamSpec("placements", "placements", required=True),
                ParamSpec("name", "str"),          # optional GroupType name
            ),
            capability=(("create", "group"), ("create", "element")),
            post=("group definition materialized from the member elements "
                  "(GroupType exists) or typed refusal; one placed group "
                  "instance per placement offset (PlaceGroup at group origin + "
                  "delta); GroupType Name == name when given"),
            writes_model=True,
            grounded=(),
        ),
]
