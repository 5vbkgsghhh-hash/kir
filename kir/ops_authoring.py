"""ops_authoring — v1 core: query + authoring + modify + architectural (wall/floor/roof/stairs/...).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

#: ``create_wall.location_line`` spelled out <-> Revit's ``WallLocationLine``
#: ordinals, which is what ``WALL_KEY_REF_PARAM`` stores.  ONE table, shared by
#: the emitter (word -> ordinal) and the lift (ordinal -> word), so the two
#: directions cannot drift apart.
#:
#: WHAT PINS THIS TABLE, AND WHAT DOES NOT — measured 2026-08-12, because the
#: line that stood here ("Order is Revit's, and the tests pin it") promised
#: more than was actually done.  The tests pin the ORDER OF THE VALUES
#: (`list(values()) == [0..5]`), the length, membership of the names, and
#: injectivity — and NEVER the name-ordinal PAIR.  Swap two pairs while
#: keeping the values 0..5 in order, and NOTHING notices: the full suite is
#: byte-for-byte unmoved (7 failed / 6140 passed / 7750 subtests before and
#: after), the Roslyn gate is 6/6 (1872 compiled), 0 of 57 goldens carry
#: ``WALL_KEY_REF_PARAM``.  The edit that would trigger this in practice is
#: not sabotage but ALPHABETICAL SORTING OF THE KEYS: routine cleanup, and it
#: breaks four pairs out of six while every guard stays green.
#:
#: THE CAUSE IS STRUCTURAL, NOT "NO TEST WAS WRITTEN."  The emitter writes
#: ``ORDINALS[name]`` (``authoring.py:557``), the witness checks
#: ``ORDINALS[name]`` (``authoring.py:725``) — both ends take the number FROM
#: HERE, a shared source is what forces them to agree, and the witness
#: cannot object to the table.  The name-ordinal pair is an external fact
#: about Revit, so pinning it can only be done by an authority OUTSIDE this
#: repository: the RevitAPI assemblies, where a duplicate ``case`` label
#: gives ``CS0152``, meaning the program is obligated NOT to compile exactly
#: when the pair is correct.  That gate stage is written on the branch
#: ``fix/kir-gate-binding-guard-accounting`` (``3003c388``) and IT IS NOT IN
#: THIS TREE — check that it is present here before considering the pair
#: protected.  Until it is, the table is correct (36/36 pairs confirmed by
#: Autodesk on six versions on 12.08), but NOT PROTECTED.
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
            # 🔴 ФОН ДЛЯ ЛИСТА, ПАЧКОЙ ЗА ОДИН ВЫЗОВ (13.09.2026). Слово
            # владельца: «остальное здание становится полупрозрачным». Гасить
            # было нечего: геометрию до этого опа давал только `query_inspect`
            # по ОДНОМУ элементу за оп, то есть этаж в 200 стен стоил 200 опов.
            # Форма согласована с W файлом `W-preview/GROUND_CONTRACT.md`.
            name="query_level_plan",
            effect=EffectKind.READ,
            result=RESULT_QUERY,
            family="query",
            params=(
                # ОДИН уровень за вызов: один вызов — один лист, и предел объёма
                # тогда считается на то, что человек реально увидит.
                ParamSpec("level", "sel", required=True),
                ParamSpec("include", "enum_list", default=list(LEVEL_PLAN_INCLUDE),
                          choices=LEVEL_PLAN_INCLUDE),
                ParamSpec("detail", "enum", default="box", choices=LEVEL_PLAN_DETAIL),
                ParamSpec("limit", "int", default=LEVEL_PLAN_LIMIT_DEFAULT,
                          min_val=1, max_val=LEVEL_PLAN_LIMIT_MAX),
            ),
            capability=(("plan", "level"),),
            post=("result.rows = плановый след каждого элемента уровня, "
                  "координаты в мм (geometry); у каждой строки element_id и "
                  "unique_id, порядок СТАБИЛЬНЫЙ по element_id (identity); "
                  "у каждой строки свой detail — box или sketch, потому что "
                  "габарит и контур суть разные утверждения о плите "
                  "(semantic); result.truncated и result.limit_hit отличают "
                  "усечение от пустоты, а отсутствие result — от них обоих "
                  "(topology)"),
        ),
    OpSpec(
            name="query_element_state",
            effect=EffectKind.READ,
            result=RESULT_QUERY,
            family="query",
            params=(ParamSpec("unique_id", "str", required=True, max_val=512),
                    ParamSpec("include_type_definition", "bool", default=False)),
            capability=(("inspect", "element"),),
            post=("same-document UniqueId lookup with explicit not_found/unavailable (identity); "
                  "separate Level project elevation/basis/parameter observation status, "
                  "not a successful BIM assertion (geometry)"),
        ),
    OpSpec(
            name="query_types",
            effect=EffectKind.READ,
            result=RESULT_QUERY,
            family="query",
            params=(
                # Closed enum, NOT a free string: exactly the snapshot pools
                # serving.py's _SNAPSHOT_CS actually collects live — "levels"
                # plus every type/family-symbol pool; "grids" is a
                # geometry-bearing CONTOUR grounding pool, not a type pool.
                #
                # 🔴 THE NUMBER HERE WAS "16" AND WAS STALE BY A FACTOR OF
                # THREE (measured 17.08.2026). The queried pools number
                # **35**, the registry declares **36**
                # (`open_model.required_grounding_pools()`), and the entire
                # difference is `grids`, excluded ON PURPOSE for the reason
                # stated a line above. A live snapshot of the tower returns
                # **40** lists: beyond the registry there are `worksets`,
                # `materials`, `phases`, `__profile_required_pools`. Three
                # authorities, three numbers — reconciling them requires a
                # run, not this comment. The list is closed, but NOT
                # complete relative to the snapshot, and that is its nature.
                #
                # THE COST OF THE POOLS WAS MEASURED IN THE SAME PLACE, the
                # live `13A-RD-AR-K2`: the 35 queried pools = 895 lines,
                # **288,137 B ≈ 96k tokens**, and **70% of this weight is
                # one `family_symbols`** (596 lines, 200,878 B). Without it
                # the remaining 34 pools weigh **87,259 B ≈ 29k tokens**.
                # Anyone planning to hand over the whole catalog must keep
                # this split in mind: it is not the catalog that is
                # expensive, it is one pool.
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
                    # wave/mep-electrical (2026-08-09): querying the
                    # catalog BEFORE attempting is the only way not to run
                    # into KIR-G102 where a project has several cable trays
                    # or flexible-conduit types sharing one name (this is
                    # normal in MEP disciplines, see the three "Default"
                    # entries for air ducts).
                    "conduit_types", "flex_duct_types", "flex_pipe_types",
                    # wave/analysis (2026-08-09): load cases and load
                    # types. Here a preliminary query is more necessary than
                    # anywhere else: `load_case` is REQUIRED for all three
                    # loads, and an analytical project has dozens of load
                    # cases ("DL1", "Snow", "Wind X"...), meaning a blind
                    # name selector is a refusal one turn later.
                    "load_cases", "point_load_types", "line_load_types",
                    "area_load_types",
                    # wave/framing (2026-08-09): a truss has NO document
                    # default type at all (ElementTypeGroup.TrussType —
                    # CS0117 on all six), so querying the catalog ahead of
                    # time for it is not a convenience but the only way to
                    # name a type without running into KIR-G102/G104 already
                    # inside the program.
                    "truss_types",
                    # wave/sweep (2026-08-09): cornices/reveals and edge
                    # profiles. Here a preliminary query is needed MORE
                    # STRONGLY than anywhere else in this table, and the
                    # reason is documented by Autodesk: for a wall sweep
                    # profile the TYPE SETS THE ENTIRE GEOMETRY ("the wall
                    # sweep's profile and type are taken from the wall sweep
                    # type properties"), meaning a blind type choice is a
                    # blind choice of WHAT will be built, not just of how it
                    # is named in the schedule. `wall_sweep_types` is at the
                    # same time ONE pool for two categories, so the type
                    # name is usually the only way to tell a cornice from a
                    # reveal.
                    "wall_sweep_types", "slab_edge_types",
                    # wave/detail (2026-08-09): fill region types. Querying
                    # the catalog ahead of time is needed for exactly the
                    # same reason as with the trays: a real project has
                    # dozens of fill regions, their names are decorative
                    # ("Concrete", "Ground", "Hatch 45"), and a miss on the
                    # name is a KIR-G102 one turn later. The fill region does
                    # have a document default, but choosing the hatch by
                    # default is the same as choosing it by lottery.
                    "filled_region_types",
                    # ═══ 12.08.2026: EIGHT POOLS THE COMPILER COULD WRITE
                    # TO WITHOUT BEING ABLE TO READ. The set is taken from
                    # the REGISTRY, not from a task list: `OpSpec.grounded`
                    # across ALL ops minus these choices. The previous
                    # measurement named SIX — it was derived from the needs
                    # of thirty UNVERIFIED ops, and `create_ceiling` and
                    # `create_railing` have long been verified and so did
                    # not fall into that slice. Once again, the answer for
                    # part of the set turned out to be smaller than the
                    # answer for the whole set.
                    #
                    # WHAT THIS COST IN DATA: NOTHING. The snapshot ALREADY
                    # collects all eight pools (`open_model.__profile_required_pools`,
                    # 36 names), and the collector for each is already
                    # written right there. What diverged was exactly this
                    # table — the reading enumeration was maintained by hand
                    # against the writing side, which the registry drives.
                    #
                    # THE SIZE OF THE ANSWER WAS MEASURED BEFORE THE
                    # EXPANSION, not assumed: 69 saved corpus profiles, each
                    # pool's `total_count`. `ceiling_types` maxes at 8
                    # (median 3), `railing_types` maxes at 22 (median 6),
                    # zero truncations across the whole corpus. The single
                    # largest pool overall is `family_symbols` at 741, and it
                    # has long been readable: these eight do not move the
                    # ceiling of the channel. The check is not a formality:
                    # the ANSWER channel is the same kind of channel as
                    # printing the contract, and a cutter that trims the SET
                    # by length would hand the model a list that reads as
                    # complete, and the choice is made from it.
                    #
                    # SIX OF THE EIGHT CANNOT BE MEASURED OFFLINE, AND THIS
                    # IS NAMED: `toposolid_types`, `building_pad_types`,
                    # `wall_foundation_types`, `area_reinforcement_types`,
                    # `rebar_bar_types`, `rebar_hook_types` landed in the
                    # snapshot on 09–10.08 (`cea112cc`, `2a84ede1`,
                    # `1f39658a`), while the newest corpus profile is from
                    # 04.08. NOT ONE saved profile could carry them; their
                    # size is closed by the very first live read, not by a
                    # code edit. The same order as with `dimension_extract`.
                    "ceiling_types", "railing_types", "toposolid_types",
                    "building_pad_types", "wall_foundation_types",
                    "area_reinforcement_types", "rebar_bar_types",
                    "rebar_hook_types",
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
                # 🔴 `ref_kinds` WAS ADDED 23.08.2026, AND THIS IS A FIX
                # FOR A MEASURED DEFECT, NOT A CONVENIENCE. Grounding
                # resolves catalog names against a snapshot taken BEFORE the
                # run; a type created within this same program is not there
                # BY CONSTRUCTION. While an empty tuple stood here,
                # `type={"by":"ref"}` got a typed refusal — "intra-program
                # ref is not permitted by the parameter's contract" — and a
                # `create_wall_type` at the head of the program did not help
                # at all — exactly what already happened with levels
                # (`create_level` at the head + addressing BY NAME = "levels:
                # … not found").
                #
                # The kind is NARROW: `WALL_TYPE` only. `ELEMENT` would let
                # in the result of any create operation, and a wall would
                # accept a reference to a door.
                ParamSpec("type", "sel",           # omitted -> doc default wall type (echoed)
                          ref_kinds=(ReferenceKind.WALL_TYPE,)),
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
                # 19.08: omitting this field does NOT disable a decoration,
                # it CHANGES THE MECHANISM — the wall's top stops following
                # the level and becomes the number `height_mm`. The
                # benchmark's control hand on free-standing C# did this 288
                # times in a row and got geometry that is correct today and
                # dead tomorrow: "move the level — the wall will not know."
                ParamSpec("top_level", "sel",
                          omission_transfers=(
                              "верх задаётся ЧИСЛОМ height_mm и перестаёт "
                              "следовать уровню: сдвиг уровня стену не двигает"),
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
            post=("wall exists (materialize); LocationCurve endpoints == p0/p1 (±5mm) (geometry); "
                  "assigned type == resolved requested type at operation end, before later edits (identity); "
                  "arc curve == arc dict when supplied (center/radius ±1mm) (geometry); "
                  "base constraint == resolved level (topology) (day-1); "
                  "height param == height_mm (±1mm) when top_level is not "
                  "given (measured 29.07.2026: WALL_USER_HEIGHT_PARAM is not "
                  "the source of truth once a top constraint is attached, "
                  "and an omitted height_mm silently carries the registry "
                  "default — the attached case is instead pinned by the top "
                  "constraint check below plus the pre-commit base<top "
                  "guard) (parameter); "
                  "base offset param == base_offset_mm when given (±1mm) (geometry); "
                  "location line rule == location_line when given "
                  "(semantic) (правило записывается в WALL_KEY_REF_PARAM и НЕ "
                  "смещает тело стены — тело стоит симметрично оси p0/p1 при "
                  "любом ординале, а правило решает лишь, какая плоскость "
                  "останется на месте при последующей смене толщины); "
                  "top constraint == resolved top_level when given (topology); "
                  "top offset param == top_offset_mm when given (±1mm) (geometry); "
                  # E3.1 19.08: a promise about GEOMETRY, not about a reference.
                  "built wall spans at least base..top elevation when "
                  "top_level is given (geometry) (-300mm floor)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "wall_types", False),
                      ("top_level", "levels", False)),
            # A2: exact historical emitter literals (byte-parity).
            # `vertical_span_mm` (19.08) — THE SAME NUMBER AND THE SAME
            # CAVEAT as for the column: CHOSEN, not measured; a one-sided
            # guard, because `__post` rolls back the program. To be refined
            # by the first live run.
            tolerances={"endpoint_mm": 5.0, "height_mm": 1.0,
                        "vertical_span_mm": 300.0,
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
                # 19.08: OMITTING IT HANDS IDENTITY OVER TO REVIT'S
                # AUTO-NUMBERING, and this is not a decoration: contours
                # address grid lines BY NAME (`relate.py`: `{"at_grid":
                # [<line>, <line>]}`), so a grid line without a chosen name
                # breaks every anchor downstream of it. Kin case —
                # `KIR-A006`: 35 columns went to "Level 1" instead of
                # "Floor 1" because both stood at elevation 0 and were
                # indistinguishable.
                ParamSpec("name", "str",
                          omission_transfers=(
                              "имя выбирает автонумерация Ревита, и якоря "
                              "`at_grid` после этого адресуют не то, что "
                              "назвала программа")),          # duplicate grid name -> typed rollback
            ),
            capability=(("create", "grid"),),
            post=("grid exists (materialize); curve endpoints == p0/p1 (±5mm) (geometry); "
                  "Name == name when given (identity)"),
            writes_model=True,
            grounded=(),
            tolerances={"endpoint_mm": 5.0},
        ),
    OpSpec(
            name="create_multi_segment_grid",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                # An OPEN polyline, not a contour: `MultiSegmentGrid.Create`
                # is documented verbatim as "an open curve loop consisting
                # of lines and arcs," and `IsValidCurveLoop` returns false
                # precisely on a closed one.  The `path` kind (2..64 points,
                # no area check) is the same one `create_railing` uses;
                # `pts` would require >=3 points and non-zero area, i.e. it
                # would close by construction a chain that the API
                # forbids.
                ParamSpec("path", "path", required=True),
                # The level is needed NOT as the grid's own constraint (the
                # grid has none), but as the ELEVATION of the horizontal
                # sketch plane: the fourth argument of Create is a
                # `SketchPlane` id, and `IsValidSketchPlaneId` requires it to
                # be HORIZONTAL. The elevation has to come from somewhere,
                # and pulling it out of thin air (Z=0) would mean
                # materializing a default the author never named.
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
            ),
            capability=(("create", "grid"),),
            # WHAT IS DELIBERATELY NOT PROMISED: the order of
            # `GetGridIds()`. It is documented nowhere, and the promise "the
            # i-th grid line corresponds to the i-th segment" would be a
            # guess; the witness therefore matches SETS (see the emitter),
            # not indices. The grid's name is also not promised: Revit
            # assigns names to its own grid lines itself.
            post=("multi-segment grid exists; it owns exactly one Grid per "
                  "path segment (GetGridIds().Count == len(path)-1); every "
                  "authored segment is matched by a created Grid whose own "
                  "Curve endpoints equal that segment's ends (±5mm), each "
                  "Grid matched at most once — the segment ORDER of "
                  "GetGridIds() is deliberately NOT asserted"),
            writes_model=True,
            grounded=(("level", "levels", True),),
            # The same number and the same quantity as
            # `create_grid.endpoint_mm`: reading back the ends of the GRID
            # curve. Not a new tolerance — the same one, applied to the same
            # instrument.
            tolerances={"endpoint_mm": 5.0},
        ),
    OpSpec(
            name="create_level",
            effect=EffectKind.CREATE,
            result=RESULT_LEVEL,
            family="authoring",
            params=(
                ParamSpec("elev_mm", "num", required=True, min_val=-1_000_000, max_val=1_000_000),
                # 19.08: THE SAME HANDOVER OF IDENTITY, and for a level it
                # costs more than for a grid. The vertical in KIR is
                # expressed as a REFERENCE, and a reference resolves BY
                # NAME: a level with an auto-name is indistinguishable from
                # a neighbor at the same elevation. Measured — `KIR-A006`,
                # 35 columns on "Level 1" instead of "Floor 1".
                ParamSpec("name", "str",
                          omission_transfers=(
                              "имя выбирает автонумерация Ревита, и селектор "
                              "`by:name` после этого может разрешиться в "
                              "уровень-сосед на той же отметке")),          # duplicate level name -> typed rollback
            ),
            capability=(("create", "level"),),
            post=("level exists (materialize); "
                  "Elevation == elev_mm (±1mm) (geometry); "
                  "Name == name when given (identity)"),
            writes_model=True,
            grounded=(),
            tolerances={"elevation_mm": 1.0},
        ),
    OpSpec(
            # THE FLOOR PLAN IS THE FOURTH CATALOG HOLE, AFTER LEVELS,
            # TYPES, AND FAMILIES, AND IT WAS FOUND BY A LIVE RUN ON
            # 23.08.2026.
            #
            # Building K3 (55 programs, 12,127 operations) into a clean
            # "Проект1": programs were failing with the textbook refusal
            # from the room separator — "the resolved level has not a single
            # floor plan (non-template), and NewRoomBoundaryLines requires a
            # view." `create_level` does NOT create a plan, and the building
            # has 917 separators, and there is ONE transaction PER PROGRAM:
            # each failure dropped 250 neighboring operations.
            #
            # 🔴 WHY A SEPARATE OP, NOT A `create_level` BRANCH. The 23.08
            # rule: an op is created only if it has its OWN Revit semantics.
            # Here everything is its own: the constructor (`ViewPlan.Create`,
            # not `Level.Create`), the result (a view, not a level), the
            # witness (whose `GenLevel` it is and whether it is a template —
            # versus the level's elevation and name), the refusals (no view
            # type, discipline turned off).
            #
            # And the argument that settles it: a plan is sometimes needed
            # for a level that ALREADY EXISTS in the target document and was
            # not created by us. A `create_level` branch cannot ask for it
            # without creating a duplicate level — meaning the need is
            # ORTHOGONAL to creating a level, not a consequence of it.
            #
            # THE VIEW TYPE IS NOT A PARAMETER, AND THIS IS A NAMED GAP.
            # There is no snapshot pool for views (`ops_annotation.py`
            # recorded this about dim_type/tag_type/text_type in the same
            # wave), so there is nothing here for `sel` to ground against.
            # The document's OWN answer is taken —
            # `GetDefaultElementTypeId(ElementTypeGroup.ViewTypeFloorPlan)` —
            # the same device by which `create_wall` takes its default type.
            # This is the DOCUMENT's default, not our guess; once the pool
            # exists, the parameter will be added and the default will
            # remain named.
            name="create_floor_plan",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("name", "str",
                          omission_transfers=(
                              "имя выбирает автонумерация Ревита; вид с "
                              "автоименем не отличить от соседнего плана "
                              "того же этажа")),
            ),
            capability=(("create", "view"), ("create", "element")),
            post=("floor plan for the level exists — created or already "
                  "present (materialize); its GenLevel is EXACTLY the "
                  "resolved level (identity); it is not a template "
                  "(semantic); its ViewType is FloorPlan (semantic) — "
                  "именно эту тройку спрашивает выбор вида у "
                  "create_room_separator, и свидетель перечитывает её У "
                  "МОДЕЛИ по Id, а не из эха вызова; Name == name when given "
                  "(identity)"),
            writes_model=True,
            # The level is grounded against the `levels` pool — the same
            # way `create_wall` and `create_room_separator` take it. An
            # empty `grounded` here would cost a KeyError on `__grounded__`
            # in the emitter: the parameter is declared, but nobody asked to
            # resolve it.
            grounded=(("level", "levels", True),),
        ),
    OpSpec(
            name="set_param",
            effect=EffectKind.MUTATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="modify",
            params=(
                # 🔴 THE TYPE IS NAMED EXPLICITLY (25.08.2026). As of this
                # date `ELEMENT` means "any INSTANCE" and does NOT accept
                # type kinds: a type has neither position nor geometry, and
                # `move_elements` on one died in Revit despite a GREEN
                # compile.
                # Here a type is legitimate, and this is a fact of the API,
                # not a relaxation: a Revit type has its OWN parameters
                # (type parameters), and a type can also be deleted. A slot
                # that needs a type is obligated to say so OUT LOUD — silence
                # no longer means "yes."
                # `change_type.target` is deliberately NOT among them: there
                # the target is the instance whose type is being changed,
                # and a type has no type of its own.
                ParamSpec("target", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,
                                     ReferenceKind.WALL_TYPE,
                                     ReferenceKind.FLOOR_TYPE,
                                     ReferenceKind.ROOF_TYPE,
                                     ReferenceKind.CEILING_TYPE)),
                ParamSpec("param", "str", required=True),
                ParamSpec("value", "value", required=True),
                ParamSpec("expected_identity", "identity", required=False),
                # 🔴 COMPARE-AND-SET ON THE VALUE, and it is the half that
                # works where identity cannot. Measured 13.09.2026: on an
                # UNSAVED document `VersionGuid` returns the DOCUMENT's episode,
                # identical for every element, so it cannot tell an edited wall
                # from an untouched one (registry ОТК-26). The parameter's own
                # value can: the emission re-reads it before writing and refuses
                # if it is no longer what the author read.
                ParamSpec("expected_current", "value", required=False),
            ),
            capability=(("set_param", "parameter"), ("set_param", "element")),
            post=("parameter holds the requested value post-commit (re-read, "
                  "±tol for lengths); unknown/read-only param == typed rollback"),
            writes_model=True,
            grounded=(),
            # 03.08: "±tol" got an address. `length_mm` is the value(mm)
            # branch, `double_abs` is the epsilon for comparing a raw
            # double. Both numbers are the SAME ones that stood as literals
            # in _emit_setparam.
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
                # 🔴 REFERENCE KIND NARROWED 24.08.2026, AND THIS IS A FIX
                # FOR A MEASURED ZERO. The `floor_types` pool is captured
                # from the target document BEFORE the run; a type created by
                # this same program is not there BY CONSTRUCTION. While an
                # empty tuple stood here, `type={"by": "ref"}` got a typed
                # refusal, and in a clean "Проект1" NOT A SINGLE ONE was
                # built: 0 of 82 floors across 46 operations in the
                # programs. Exactly the same defect and the same cure as
                # `create_wall.type` on 23.08.
                ParamSpec("type", "sel",           # omitted -> doc default floor type (echoed)
                          ref_kinds=(ReferenceKind.FLOOR_TYPE,)),
                ParamSpec("structural", "bool", default=False),       # foundation slab = structural floor
                # P1 DOF-completeness: the floor's offset from the level
                # (FLOOR_HEIGHTABOVELEVEL_PARAM) — on "demo" 51% of floors
                # are offset.  NO default: absent = the historical
                # emission.
                ParamSpec("height_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"),),
            post=("floor exists (materialize); level binding == resolved level (topology); "
                  "assigned type == resolved requested type at operation end, before later edits (identity); "
                  "bbox XY extents == outline extents (±50mm) (geometry); "
                  # 🔴 SHAPE, NOT JUST THE BOUNDING BOX (19.08.2026). The
                  # bounding box pins down FOUR numbers; an L-contour of six
                  # vertices has TWELVE coordinates, and eight remained
                  # free — a shifted interior corner, a lost notch, and a
                  # filled-in hole all passed green, signing off on
                  # (geometry). A multiset of vertices on a ±1mm grid is
                  # robust to the loop's rotation and to a change of
                  # traversal direction: both of those belong to Revit, not
                  # to the author.
                  "sketch loop count and per-loop vertex multiset == outline "
                  "plus holes on the ±1mm canon grid (geometry); "
                  "structural flag == requested (semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "floor_types", False)),
            tolerances={"bbox_mm": 50.0, "height_offset_mm": 1.0,
                        "sketch_mm": 1.0},
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
                # 🔴 REFERENCE KIND NARROWED 24.08.2026, AND THIS IS A FIX
                # FOR A MEASURED ZERO. The `roof_types` pool is captured
                # from the target document BEFORE the run; a type created by
                # this same program is not there BY CONSTRUCTION. While an
                # empty tuple stood here, `type={"by": "ref"}` got a typed
                # refusal, and in a clean "Проект1" NOT A SINGLE ONE was
                # built: 0 of 36 roofs across 27 operations in the
                # programs. Exactly the same defect and the same cure as
                # `create_wall.type` on 23.08.
                ParamSpec("type", "sel",           # omitted -> doc default roof type (echoed)
                          ref_kinds=(ReferenceKind.ROOF_TYPE,)),
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
            post=("footprint roof exists (materialize); base level == resolved level (topology); "
                  "bbox XY extents == outline extents (±50mm) (geometry); "
                  "sketch loop vertex multiset == outline on the ±1mm "
                  "canon grid (geometry)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "roof_types", False)),
            tolerances={"bbox_mm": 50.0, "sketch_mm": 1.0},
        ),
    OpSpec(
            name="create_extrusion_roof",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # A WORK PLANE, NAMED BY A PLAN LINE. The plane of an
                # extruded roof must be PARALLEL TO the z axis (so states
                # the very signature of NewExtrusionRoof), i.e. vertical; a
                # vertical plane is uniquely given by its trace on the plan.
                # p0/p1 is that trace. The p0_mm/p1_mm pair was NOT chosen by
                # taste: `authoring_validation` runs the "length ~0" law
                # against it for ANY op that has it, and the
                # non-degeneracy of the plane's direction is obtained here
                # FOR FREE, by the same implementation as for the wall.
                ParamSpec("p0_mm", "pt_xy", required=True),
                ParamSpec("p1_mm", "pt_xy", required=True),
                # THE PROFILE IS IN THE PLANE'S OWN COORDINATES: [u_mm,
                # z_mm], where u is measured from p0 along p0->p1, and z is
                # the world elevation.
                #
                # WHY NOT CONTOUR AND NOT WORLD POINTS. CONTOUR is closed by
                # construction and puts every point at Z=0 — it is the
                # language of the PLAN, while an extrusion profile is an
                # OPEN chain in a VERTICAL plane; only the arc arithmetic
                # from it is usable. World [x,y,z] looks more natural, but
                # would require checking "all points lie in one vertical
                # plane," and that check has no derivable tolerance — a
                # number would have to be MADE UP. In the plane's
                # coordinates coplanarity is not checked, because it is an
                # IDENTITY: every point is constructed as p0 + u*dir + z*Z.
                # The illegal state became unrepresentable, rather than
                # caught.
                ParamSpec("profile_mm", "path", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # 🔴 REFERENCE KIND NARROWED 24.08.2026, AND THIS IS A FIX
                # FOR A MEASURED ZERO. The `roof_types` pool is captured
                # from the target document BEFORE the run; a type created by
                # this same program is not there BY CONSTRUCTION. While an
                # empty tuple stood here, `type={"by": "ref"}` got a typed
                # refusal, and in a clean "Проект1" NOT A SINGLE ONE was
                # built: 0 of 36 roofs. Exactly the same defect and the same
                # cure as `create_wall.type` on 23.08.
                ParamSpec("type", "sel",           # omitted -> doc default roof type
                          ref_kinds=(ReferenceKind.ROOF_TYPE,)),
                # The extrusion bounds run along the plane's NORMAL,
                # measured from that same plane. Revit picks the normal's
                # sign itself, so the emitter reads `ReferencePlane.Normal`
                # and brings the pair back to OUR orientation (dir x Z)
                # right there in C# — otherwise the roof would silently end
                # up on the wrong side of the building.
                ParamSpec("start_mm", "num", required=True,
                          min_val=-1_000_000, max_val=1_000_000),
                ParamSpec("end_mm", "num", required=True,
                          min_val=-1_000_000, max_val=1_000_000),
            ),
            capability=(("create", "element"),),
            # NOT A SINGLE "±<number>": this op's only numeric tolerance is
            # read FROM THE LIVE DOCUMENT (`Application.VertexTolerance`),
            # not taken from the registry — see the emitter. Provenance law
            # 3 (`emit_model.py`) requires that every "±N" in post live in
            # tolerances; there are none here, and tolerances is empty
            # HONESTLY, not out of forgetfulness.
            post=("extrusion roof exists as an ExtrusionRoof; "
                  "ROOF_BASE_LEVEL_PARAM == resolved level (topology); "
                  "the built solid's extent along the work plane's own normal "
                  "spans exactly [start_mm, end_mm] measured from the plane "
                  "(geometry) — bound: TWICE the live document's own "
                  "Application.VertexTolerance, which is Revit's statement of "
                  "vertex precision and not a number we chose; "
                  "the profile SHAPE inside the plane is NOT gated (no "
                  "derivable bound for a swept sketch — named, not omitted)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "roof_types", False)),
            tolerances={},
        ),
    OpSpec(
            name="create_stairs",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                # EXACTLY ONE OF TWO: a straight flight (`p0_mm`/`p1_mm`)
                # OR a spiral one (`spiral`). That is why the ends stopped
                # being required AT THE SCHEMA LEVEL (09.08.2026): the
                # requirement became MUTUAL, and a schema cannot express a
                # mutual one — it lives in the compiler as a typed
                # KIR-P007, the same device and for the same reason as with
                # create_ceiling (outline versus contour) and place_family
                # (xyz versus p0_mm/p1_mm).
                #
                # NO REPLACEMENT TOOK PLACE, AND THIS IS A DECISION: the
                # reverse path (decompile/lift.py::_lift_stairs) emits
                # exactly `p0_mm`/`p1_mm` — the flight's ends, read off the
                # element — and if the straight ends had disappeared, the
                # loop would break on every stair of every decompiled
                # building.
                ParamSpec("p0_mm", "pt_xy"),           # run start (base level)
                ParamSpec("p1_mm", "pt_xy"),           # run direction/end
                ParamSpec("base_level", "sel", required=True),
                ParamSpec("top_level", "sel", required=True),
                ParamSpec("width_mm", "mm", min_val=600, max_val=5_000),
                # SPIRAL FLIGHT (09.08.2026) — StairsRun.CreateSpiralRun,
                # EXISTS and is BYTE-FOR-BYTE IDENTICAL across all six
                # shipped versions (re-verified against the reference
                # assemblies: `M:...StairsRun.CreateSpiralRun(Document,ElementId,XYZ,
                # Double,Double,Double,Boolean,StairsRunJustification)` in
                # RevitAPI.xml 2021/2022/2023/2024 (net48) and 2025/2026
                # (net8.0), plus a live Roslyn run on :52412 compiled the
                # emission 6/6).
                #
                # A spiral is ENTIRELY inexpressible with a two-point
                # polyline: a straight flight gives a DIFFERENT shape, not
                # an approximation — the same class as "a polyline instead
                # of a rounded edge" for the ceiling. Angles are in DEGREES,
                # like everything authored in KIR (`rotation_deg`,
                # `slopes[].angle_deg`); the canonical arc's radians come
                # from the REVERSE path, and that is an input written by a
                # human or a model. Shape laws and bounds are in
                # `authoring_validation._validate_spiral`.
                ParamSpec("spiral", "spiral"),
            ),
            capability=(("create", "element"),),
            post=("stairs exist; base/top level == resolved levels (topology); "
                  ">=1 run created; width_mm held ±5mm when supplied; "
                  "марш ДОХОДИТ до top_level и не перелетает его: "
                  "ActualRisersNumber <= DesiredRisersNumber (geometry) — "
                  "число подступенков задаёт ДЛИНА МАРША, делённая на проступь "
                  "ТИПА, а не подъём, и автор длину назвать обоснованно не "
                  "может (тип у этого опа не выбирается, пула stairs_types в "
                  "каталоге скрипта нет), поэтому отказ ВОЗВРАЩАЕТ потребную "
                  "длину (Desired-1)*ActualTreadDepth, а расписка везёт её "
                  "всегда — вместе с risers_desired/tread_depth_mm/"
                  "riser_height_mm; "
                  "spiral run path contains an Arc when spiral is given "
                  "(geometry — NOT its centre/radius/sweep: the relation "
                  "between the requested centre and what GetStairsPath "
                  "returns is UNMEASURED, so those are recorded in the "
                  "readback for the first live device and gated by nobody); "
                  "MUST be the sole op of its program "
                  "(StairsEditScope owns its transactions — KIR-L002 otherwise)"),
            writes_model=True,
            grounded=(("base_level", "levels", True), ("top_level", "levels", True)),
            # 03.08: the promised ±5 mm on the flight's width. The number
            # is the same one that stood as a literal in
            # emit_stairs_program.
            tolerances={"width_mm": 5.0},
        ),
    OpSpec(
            name="create_stairs_landing",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                # THE OWNING STAIR. The `target_w` kind is the same one
                # `create_railing.host` and `create_multistory_stairs.stairs`
                # already use to address a stair; no new reference machinery
                # is introduced.
                #
                # `ref_kinds` IS DELIBERATELY EMPTY, and this is NOT a copy
                # of its neighbor but a consequence of the batch's law: the
                # op itself sits in `spec.SOLO_OPS`, meaning it is the ONLY
                # op of its own program and has no predecessor at all.
                # `by: ref` here is not "dangerous" — it is unresolvable by
                # construction, and an empty `ref_kinds` turns it into a
                # typed refusal AT PARSE TIME, not an exception during
                # emission. The only legitimate form is the `element_id` of
                # a stair already standing in the model.
                ParamSpec("stairs", "target_w", required=True, ref_kinds=()),
                # THE LANDING'S BOUNDARY IS A SKETCH, HENCE CONTOUR. There
                # is no second way to give a profile in this compiler, and
                # none must be introduced: the `region` kind brings, for
                # free, point addresses from grid lines (RELATE), arcs,
                # closure laws, zero-length edges, self-intersection, and
                # degenerate area — exactly the set that
                # `CreateSketchedLanding` requires of a `CurveLoop`
                # ("closed", "bound Line or bound Arc"). Holes are REFUSED
                # (there is no second ring in the signature on any
                # version) — `stairs_landing_emit`, KIR-E008.
                ParamSpec("contour", "region", required=True),
                # THE LANDING'S ELEVATION RELATIVE TO THE STAIR'S BASE —
                # that is what the API itself calls it, verbatim: "The base
                # elevation is relative to the base elevation of the
                # stairs" (RevitAPI.xml, `CreateSketchedLanding`, all six
                # versions). This argument has no absolute elevation at
                # all, which is why the parameter is relative: converting
                # to absolute would require reading `Stairs.BaseElevation`
                # BEFORE emission, i.e. a live Revit.
                #
                # THE BOUNDS ARE DERIVED, NOT ASSIGNED, and both halves are
                # named:
                #
                #  * TOP = 9,144,000 mm — this is exactly "30000 feet in
                #    absolute value" from Autodesk's own text (30,000 ×
                #    304.8). The number is external; ours is only the unit
                #    conversion.
                #  * BOTTOM = 0 — a WEAK bound, and the weakness is
                #    deliberate. Autodesk requires "equal to or greater
                #    than half of the riser height," and the riser height =
                #    the stair's height / number of risers, i.e. a quantity
                #    of the LIVE model, which the compiler does not have.
                #    Zero rejects NOT A SINGLE legitimate value (any
                #    legitimate one is strictly greater than zero), and the
                #    exact bound is enforced by a RUNTIME REFUSAL that reads
                #    `Stairs.ActualRiserHeight` off the stair itself and
                #    tells the author the measured number. A bound invented
                #    in its place would be exactly `create_door.sill_mm
                #    min_val=0` — 140 negative elevations out of 151 in the
                #    real house.
                ParamSpec("elevation_mm", "mm", required=True,
                          min_val=0.0, max_val=9_144_000.0),
            ),
            capability=(("create", "element"),),
            post=("a sketched StairsLanding exists on the given stairs; "
                  "GetStairs() == the requested stairs (topology); the landing "
                  "id appears in Stairs.GetStairsLandings() (topology); "
                  "IsAutomaticLanding == false — the sketched factory was "
                  "asked for and an automatic landing would be a different "
                  "element (semantic); GetFootprintBoundary re-read in PLAN "
                  "reproduces the authored contour — curve count and every "
                  "authored edge matched exactly once by its endpoints and its "
                  "mid-point (geometry), tolerance DERIVED at run time as "
                  "MM(Application.VertexTolerance) + the contour emission "
                  "quantum, never a registry constant; the Z of those curves "
                  "is NOT compared (Revit projects the boundary onto the "
                  "stairs base level itself, so its Z is Revit's number, not "
                  "ours); elevation_mm must already equal an integer multiple "
                  "of the live ActualRiserHeight within the derived geometry "
                  "tolerance, otherwise the op refuses and names the adjacent "
                  "multiples; CreateSketchedLanding receives that normalized "
                  "multiple and a fresh post-scope BaseElevation read must "
                  "equal it within the same small tolerance (geometry); an "
                  "elevation below half the live riser "
                  "height is a typed refusal naming the measured number, never "
                  "an exception; MUST be the sole op of its program "
                  "(StairsEditScope owns its transactions — KIR-L002 otherwise)"),
            writes_model=True,
            grounded=(),
            # EMPTY, AND THIS IS A MEASUREMENT, NOT AN OMISSION. Both
            # tolerances of this op depend on the LIVE model and therefore
            # cannot be registry constants by construction: the boundary
            # tolerance = the document's own `VertexTolerance` plus our
            # emission's quantum, the elevation tolerance = the riser
            # height of THIS stair. They are computed by the emission, from
            # Revit's own numbers — the same device and the same reason as
            # with `create_solid_*`. The riser height here sets the GRID of
            # permitted elevations, not a wide witness tolerance: ±1 riser
            # must fail.
            tolerances={},
        ),
    OpSpec(
            name="create_stairs_run",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                # THE OWNING STAIR — verbatim the same kind and the same
                # argument as for the landing: `ref_kinds` IS EMPTY, because
                # the op sits in `spec.SOLO_OPS` and has no predecessor at
                # all. The only legitimate form is the `element_id` of a
                # stair already standing.
                ParamSpec("stairs", "target_w", required=True, ref_kinds=()),
                # THE FLIGHT'S AXIS IN PLAN. `CreateStraightRun` accepts a
                # `locationPath` of type `Line` and requires a "bound line";
                # the author gives the XY, the emission computes the Z from
                # the stair's own elevation (see `base_elevation_mm`). The
                # shape is the same as for the first flight in
                # `create_stairs`, and this is not symmetry but one and the
                # same argument of one and the same call.
                ParamSpec("p0_mm", "pt_xy", required=True),
                ParamSpec("p1_mm", "pt_xy", required=True),
                # THE FLIGHT'S BOTTOM ELEVATION RELATIVE TO THE STAIR'S
                # BASE.
                #
                # WHY RELATIVE, NOT ABSOLUTE — the same reason the landing's
                # elevation is relative, and here it is even stricter:
                # `CreateStraightRun` has NO elevation argument at all, it
                # is carried by the Z of the `locationPath` points. An
                # absolute Z would require knowing `Stairs.BaseElevation`
                # BEFORE emission, i.e. a live Revit at compile time. So the
                # author says "how much above the base," and `BaseElevation`
                # (6/6, measured by compilation) is read by C# at runtime.
                #
                # THE BOUNDS are the same and on the same basis as for the
                # landing: the top, 9,144,000 mm, is "30000 feet" from
                # Autodesk's text (`ArgumentOutOfRangeException` from
                # `CreateSketchedRun`, verbatim), the bottom, 0, is a WEAK
                # bound, because the exact one ("bottom of run should not be
                # lower than bottom of stairs") is a quantity of the live
                # model. Inventing it in its place would mean repeating
                # `create_door.sill_mm min_val=0`.
                ParamSpec("base_elevation_mm", "mm", required=True,
                          min_val=0.0, max_val=9_144_000.0),
                # THE FLIGHT'S JUSTIFICATION IS A CLOSED REVIT ENUM.
                # `StairsRunJustification` carries exactly three members,
                # and all three are verified by COMPILATION against real
                # assemblies for 2021-2026 (6/6 each), not read from XML.
                # What goes into the C# is the MEMBER'S NAME, so the Revit
                # assemblies remain the authority: a typo fails to compile
                # rather than silently building the wrong thing. The
                # `center` default is the same one hard-coded for the first
                # flight in `create_stairs`
                # (`StairsRunJustification.Center`), meaning the op does not
                # change the behavior the author is already used to.
                ParamSpec("justification", "enum", required=False,
                          choices=("center", "left", "right"),
                          default="center"),
            ),
            capability=(("create", "element"),),
            post=("a StairsRun exists on the given stairs; GetStairs() == the "
                  "requested stairs (topology); the run id appears in "
                  "Stairs.GetStairsRuns() (topology); the run's re-read "
                  "location path reproduces the authored axis endpoints in "
                  "PLAN within the derived tolerance (geometry) — Z is NOT "
                  "compared, it is Revit's own number derived from the stairs "
                  "base; the run's base elevation re-read after "
                  "StairsEditScope.Commit equals BaseElevation + the authored "
                  "base_elevation_mm within the same tolerance (geometry); "
                  "base_elevation_mm must already be an integer multiple of "
                  "the live ActualRiserHeight, otherwise the op refuses and "
                  "names the adjacent multiples — a run starting mid-riser is "
                  "not a stair; MUST be the sole op of its program "
                  "(StairsEditScope owns its transactions — KIR-L002 "
                  "otherwise)"),
            writes_model=True,
            grounded=(),
            # EMPTY FOR THE SAME REASON AS THE LANDING: both tolerances of
            # this op are quantities of the LIVE model (the document's
            # `VertexTolerance` and this stair's riser height), and they
            # cannot be registry constants by construction.
            tolerances={},
        ),
    OpSpec(
            name="create_multistory_stairs",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                # THE ORIGINAL stair. The `target_w` kind is exactly the
                # one `create_railing.host` already uses to address an
                # owning stair, so no new reference machinery is
                # introduced. A `by: ref` reference to a `create_stairs` in
                # THE SAME program is unreachable by the batch's law
                # (KIR-L002, `spec.SOLO_OPS`) — and this is exactly the
                # seam for which the op exists: the flight is built by its
                # own program, and it is MULTIPLIED across floors by the
                # next one, with a single call, next to any neighbors.
                ParamSpec("stairs", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                # ALL levels on which the stair must stand — including its
                # own base one. A list of selectors, not a list of ids:
                # levels in KIR are addressed by name everywhere, and
                # forcing the author to know an element_id for the sake of
                # one op would be a regression of the language. Why
                # INCLUDING the base one — see post.
                #
                # `ref_kinds` IS DELIBERATELY EMPTY, and this is a refusal
                # for a named reason, not an oversight. A `by: ref`
                # reference inside the LIST would slip past the dependency
                # graph check: the plan (`compiler.plan_program`) collects
                # edges only for the `sel`/`target_w`/`refs_w` kinds, and a
                # reference to a non-existent or non-level op would reach
                # emission unchecked. The plan could be taught the new
                # kind, but it is NOT NEEDED: the batch's law already states
                # that a level created by the body's program is visible to
                # the stairs program BY NAME (the KIR-L002 refusal text,
                # verbatim) — meaning an intra-program reference to a level
                # here is not so much dangerous as it is pointless. An
                # empty `ref_kinds` turns `by: ref` into a typed refusal at
                # parse time.
                ParamSpec("levels", "sel_list", required=True),
            ),
            capability=(("create", "element"),),
            # EXACT SET EQUALITY, WITHOUT TOLERANCE. After `Create`,
            # `MultistoryStairs` already occupies the original's base
            # level, and a request that does not name it would mean
            # "detach" — an intent the author did not write. Such a request
            # REFUSES (typed, naming the missing level), and that is
            # exactly why the witness can use EQUALITY rather than
            # inclusion: inclusion would pass even when ConnectLevels
            # connected nothing at all.
            post=("a MultistoryStairs element exists over the given stairs; "
                  "GetAllConnectedLevels() re-read after commit EQUALS the "
                  "resolved `levels` set exactly (ElementId set equality — no "
                  "tolerance, no subset); a level the stairs already occupies "
                  "but `levels` omits is a typed refusal, never a silent "
                  "disconnect; a level Revit reports as unconnectable "
                  "(CanConnectLevel==false) is a typed refusal naming it"),
            writes_model=True,
            grounded=(("levels", "levels", True),),
            tolerances={},
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
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),        # omitted -> sole snapshot entry, else AMBIGUOUS
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
                # P1 DOF-completeness (fidelity audit 2026-07-21): the
                # column's vertical — on "demo" 100% of columns are
                # top-attached, 99% have a base-offset.  NO default: absent
                # = the historical emission, byte-for-byte (as-placed
                # symbol height).
                ParamSpec("base_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
                # 19.08: omitting it lifts the CONDITIONAL obligation "top
                # constraint == resolved top_level," and the height is
                # silently taken from the type default. Measurement from
                # the live benchmark: 420 columns came out at 2500 mm
                # instead of 3600–4500, not a single refusal, three audits
                # missed it.
                ParamSpec("top_level", "sel",
                          omission_transfers=(
                              "высота берётся из умолчания типа, а не из "
                              "программы, и обязательство верхней привязки "
                              "не проверяется вовсе"),
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("top_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"), ("create", "category")),
            post=("column exists (materialize); LocationPoint == xy (±5mm) (geometry); "
                  "rotation == rotation_deg (±0.1deg, modulo 360) (geometry); "
                  "StructuralType matches category (semantic); base level "
                  "== resolved level (topology) (BIP chain); "
                  # 🔴 E3.1 19.08: a promise about vertical GEOMETRY, not
                  # about a reference. One-sided and deliberate: `__post`
                  # rolls back the program, the observed defect produces an
                  # UNDERSHOOT (2500 versus 3600), while a family that
                  # protrudes past the attachment produces an overshoot and
                  # must be tolerated.
                  "built solid spans at least base..top elevation when "
                  "top_level is given (geometry) (-300mm floor)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("symbol", "column_symbols_{category}", False),
                      ("top_level", "levels", False)),
            # rotation_deg (03.08): `post` promised ±0.1deg, and the
            # registry could not name that number. In C# the tolerance
            # stands as the EXPRESSION `Math.PI / 1800.0` — the divisor is
            # computed from that same 0.1 (Tolerance.deg_rad_divisor), so
            # the bytes are unchanged.
            # 🔴 `vertical_span_mm` (19.08) — THE NUMBER WAS CHOSEN, NOT
            # MEASURED, and this is stated here so the next reader does not
            # mistake it for a measured one. What WAS measured is the miss:
            # 1100 mm of undershoot across 420 columns of the live
            # benchmark. A 300 mm margin gives a 3.6x difference from that
            # and tolerates a family whose geometry falls tens of mm short
            # of the attachment. To be refined by the FIRST live run on a
            # real column family: if the guard produces a false positive,
            # the number grows while the one-sidedness stays.
            tolerances={"location_mm": 5.0, "rotation_deg": 0.1,
                        "base_offset_mm": 1.0, "top_offset_mm": 1.0,
                        "vertical_span_mm": 300.0},
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
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),
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
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),
                # audit F5: дверь без створки — не та дверь.  Same optional
                # bools as create_window/place_family; absent stays implicit
                # (byte-stable pre-existing programs), the emitter enforces the
                # requested swing/mirror state with CanFlip* guards.
                ParamSpec("mirrored", "bool", default=False),
                ParamSpec("hand_flipped", "bool", default=False),
                ParamSpec("facing_flipped", "bool", default=False),
            ),
            capability=(("create", "element"),),
            post=("door exists (materialize); Host.Id == host wall id (topology); "
                  "LocationPoint == p0+dir*offset at host level+sill (±10mm) (geometry); "
                  "Mirrored/HandFlipped/FacingFlipped equal requested states "
                  "when given (semantic)"),
            writes_model=True,
            grounded=(("symbol", "door_symbols", False),),
            tolerances={"location_mm": 10.0},
        ),
    OpSpec(
            name="create_room",
            caveat=(
                "Помещение замыкается СТЕНАМИ, и Revit видит их только "
                "после `doc.Regenerate()`. В одной программе стены обязаны "
                "стоять ВЫШЕ помещения; если контур строится соседним "
                "ходом — помещение кладётся СЛЕДУЮЩЕЙ программой, иначе "
                "Revit вернёт площадь 0 и постусловие откатит транзакцию. "
                "И высота: `NewRoom` ставит верхний предел из умолчания "
                "документа (8 футов = 2438 мм), что НИЖЕ жилой нормы 2500 — "
                "назови `upper_offset_mm`, иначе правило HAB022 справедливо "
                "объявит помещение непригодным. "
                "И НАЗОВИ `function`: без неё род помещения УГАДЫВАЕТСЯ из "
                "`name` словарём, который знает 23 имени из 81 на восьми "
                "языках и по-немецки не знает ни одного, — а неугаданное "
                "помещение уходит в `прочее`, и все правила пригодности "
                "(площадь, ширина, высота, инсоляция) к нему НЕ ПРИМЕНЯЮТСЯ. "
                "Ты знаешь, что строишь; назвав род, ты не оставляешь это "
                "догадке."),
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("xy", "pt_xy", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("name", "str"),
                # 🔴 ROOM FUNCTION, NAMED BY THE AUTHOR, NOT GUESSED FROM
                # THE NAME (28.08.2026). Before this date the room's kind
                # was inferred by a lexicon from the free-form `name`
                # string — EVEN when the program is written by an LLM that
                # perfectly well knows it is building a bedroom.
                # Measurement from the same day: 81 names across eight
                # languages, the lexicon recognizes 23; and the owner's
                # decision is NOT to grow the dictionary toward completeness
                # (see the header of `checker/classify.py`). An author who
                # already knows the answer has no need for guessing at all.
                #
                # 🔴 THIS FIELD DOES NOT GO INTO REVIT, AND THIS IS A
                # DECISION, NOT AN UNFINISHED PART. Revit has NO typed slot
                # for a room's function: `ROOM_OCCUPANCY` does not appear at
                # all in the captured API signatures, and `ROOM_DEPARTMENT`
                # is a free-form string ALREADY TAKEN for a different
                # subject: `apartment_id` is read from it
                # (`checker/extractor.cs`), and a live measurement gives it
                # ONE group per 1102 rooms. Writing the function there
                # would mean colliding two subjects in one parameter and
                # breaking apartment inference. So the kind lives in the
                # KIR model: the emission does not change, and an old
                # program compiles BYTE FOR BYTE on all six versions — this
                # is verified, not assumed (`test_emit_model_byte_parity`).
                #
                # The values are exactly `checker.spatial_model.RoomFunction`,
                # and what guards the two lists from drifting apart is
                # `tests/test_authored_room_function_is_not_a_guess.py`: two
                # neighboring decisions about ONE subject is our named
                # class of defect.
                ParamSpec("function", "enum",
                          choices=("жилая", "кухня", "санузел", "коридор",
                                   "лестница", "лифт_холл", "прихожая",
                                   "входная_группа", "тех", "прочее")),
                # ROOM_NUMBER is independent from ROOM_NAME.  It is exact
                # model identity, so an empty value and outer whitespace are
                # not normalised into a different authored program.
                ParamSpec("number", "str", exact_string=True),
                # upper_offset_mm — ROOM_UPPER_OFFSET (measured from a live
                # apartment 25.08.2026: 1102 of 1102 rooms carry it, always
                # — not sometimes). Named `upper_offset_mm`, not
                # `top_offset_mm` or `height_offset_mm`, ON PURPOSE:
                # `create_wall.top_offset_mm` and
                # `create_column.top_offset_mm` are half of a PAIR, meaningful
                # ONLY together with `top_level` (the emitter ignores them
                # separately, see the comment at
                # `create_wall.top_offset_mm`), while a room in v1 has no
                # `upper_level` — Revit itself sets the upper bound at the
                # room's own level on `NewRoom`, leaving nothing to pair a
                # slot with. `height_offset_mm` (floor/ceiling) names the
                # offset of the element's OWN plane from its level — a
                # different quantity. Here the name copies exactly the tail
                # of the BuiltInParameter (the same discipline that gave
                # base_offset_mm / top_offset_mm / height_offset_mm), not
                # its neighbor's pose.
                #
                # Without this slot the ceiling height IS NOT EXPRESSIBLE
                # IN THE LANGUAGE AT ALL: `NewRoom` sets it from the
                # document's type default (8 feet = 2438 mm — a live HAB022
                # refusal, 25.08: the habitability norm is 2500 mm), and
                # fixing it required a SECOND op (`set_param` by the
                # Revit parameter's Russian name "Смещение сверху"), which
                # the model could not have guessed and about which the
                # HAB022 refusal is silent.
                #
                # 🔴 THE BOUNDS ARE DERIVED FROM MEASUREMENT, NOT FROM
                # THE HEAD. The same measurement (1102 of 1102 live rooms)
                # gives the values 3000×1054, 3300×23, 0×21, 3700×3, and one
                # non-round 3493.74 (Revit itself accumulates foot-rounding
                # error; the author does not write it). Hence: `min_val=0`,
                # NOT HIGHER — 21 rooms out of 1102 declare exactly zero,
                # and this is a legitimate author value (the upper bound
                # coincides with the room's level), not an omission.
                # `max_val=100_000` is the same ceiling as
                # `create_wall.height_mm`, not a new number out of thin
                # air. NO default: as with base_offset_mm/top_offset_mm/
                # height_offset_mm — absence stays absence, and every
                # existing program with a room is emitted byte-for-byte as
                # before.
                ParamSpec("upper_offset_mm", "mm", min_val=0, max_val=100_000,
                          omission_transfers=(
                              "верхний предел остаётся на умолчании типа "
                              "документа (обычно 8 футов = 2438 мм), которое "
                              "ниже нормы пригодности жилья HAB022 "
                              "(min_ceiling_height_mm = 2500) почти всегда")),
            ),
            capability=(("create", "room_space"),),
            post=("room exists and has nonzero enclosed area; LevelId == resolved "
                  "level (topology); LocationPoint == xy (±5mm) (geometry); Name == name "
                  "when given (identity); Number == number when given (semantic); "
                  "upper offset param == upper_offset_mm when given (±1mm) (geometry); "
                  "placed AFTER doc.Regenerate() when walls precede (v0 rule)"),
            writes_model=True,
            grounded=(("level", "levels", True),),
            tolerances={"location_mm": 5.0, "upper_offset_mm": 1.0},
        ),
    OpSpec(
            # A family is placed EITHER at a point OR along a curve —
            # Revit gives two different NewFamilyInstance overloads for
            # this, and the choice between them is determined by what kind
            # of family is placed: a CurveBased instance has no
            # LocationPoint at all.
            #
            # Hence `xyz` stopped being required at the SCHEMA level, and
            # the mutual exclusion moved into the compiler as a typed
            # refusal (KIR-P007): "one of the two" cannot be expressed by a
            # schema, and silently guessing on the author's behalf is
            # exactly what this compiler forbids.
            #
            # A curve is recorded as the pair p0_mm/p1_mm — the same way as
            # in create_beam / create_pipe / create_cable_tray. There must
            # not be a second way to record a segment in this registry.
            #
            # The case was measured (ЭОМ SKLNK R2026): 79 instances, the
            # entire remainder of this model's hole, all CurveBased, all
            # with a live LocationCurve.
            name="place_family",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("xyz", "pt_xyz"),
                ParamSpec("p0_mm", "pt_xyz"),
                ParamSpec("p1_mm", "pt_xyz"),
                # The host on the curve variant is not decoration, it is a
                # Revit requirement. MEASURED 27.07 on a live ЭОМ model
                # with two trials:
                #   * NewFamilyInstance(Curve, symbol, LEVEL, …) lays the
                #     curve onto the level's plane. The source segment of
                #     the tray cover was vertical ([...,565]→[...,4910]) and
                #     collapsed into a point ([...,0]→[...,0]). Revit also
                #     ignored the passed level: LevelId stayed -1;
                #   * NewFamilyInstance(REFERENCE, Line, symbol) is the
                #     correct overload, and it checks the real relation:
                #     "Family cannot be placed on this line as it does not
                #     coincide with the input face" when the segment does
                #     not lie on the host's face.
                # From this follows the reassembly order as well: host
                # first, then whatever hangs on it — exactly as with a door
                # and a window.
                ParamSpec("host", "target_w",
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                ParamSpec("level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),        # omitted -> sole snapshot entry
                ParamSpec("rotation_deg", "deg", default=0.0),
                ParamSpec("mirrored", "bool", default=False),
                ParamSpec("hand_flipped", "bool", default=False),
                ParamSpec("facing_flipped", "bool", default=False),
                # ── PLACEMENT KIND (11.08.2026) ──────────────────────────
                #
                # THE CASE WAS MEASURED, NOT MADE UP. `tools/coverage_matrix.py`
                # across the whole corpus (11 DISTINCT documents; 76
                # catalogs — catalogs, not buildings) gives the lifter
                # refusal "place_family places only point placements
                # (OneLevelBased/OneLevelBasedHosted)" on two kinds:
                #     WorkPlaneBased    483 elements on 7 of 11 documents
                #     TwoLevelsBased   9392 elements on 4 documents
                # Seven documents out of eleven is the widest spread across
                # buildings of any actionable line in the corpus, and a wide
                # spread by the map's own logic means it is OUR rule that is
                # wrong altogether, not a quirk of one project.
                #
                # `ViewBased` and `CurveBasedDetail` (999 and 862 elements
                # across 3 documents) are DELIBERATELY NOT TAKEN: they are
                # view-dependent, and `L0Element` carries no owning view at
                # all, and no KIR op creates a View
                # (`authoring._annot_view_res` refuses `in_view: ref`
                # precisely on this premise). Taking them would mean
                # running into the same wall as dimensions, tags, and text —
                # and that is a separate, larger conversation about the
                # LANGUAGE.
                #
                # NEITHER OF THE TWO NEW KINDS HAS A DEFAULT VALUE, and
                # this is not forgetfulness: a missing key must stay
                # missing, otherwise every already-written place_family
                # program would change its emitted C# (18,700 demo
                # instances are frozen by the byte-parity corpus), and the
                # witness would start requiring a value the author never
                # named — exactly the defect that cost a rollback for every
                # correct facade wall (`height_mm`, measured 29.07).
                #
                # NEITHER OF THE TWO KINDS HAS A REVERSE PATH, and this must
                # be known here, not discovered by the next measurement:
                # `schema.L0Element` carries EXACTLY ONE level (`level_id`)
                # and carries NO reference to a work plane, neither as a
                # field nor as a side index. This wave extends the FORWARD
                # path — what an engineer can ask for — while lifting such
                # an instance remains impossible, and the lifter must
                # continue to refuse.
                #
                # `ref_dir` is the DIRECTION of reference on the work
                # plane, not a position: the `pt_xyz` kind is used because
                # the registry has no other kind for a triple of numbers,
                # and `create_face_wall.face_normal` lives by exactly the
                # same pattern — including the entry in
                # `relate.ADDRESS_EXCLUDED`, without which RELATE would
                # offer to address the DIRECTION by a grid intersection.
                ParamSpec("ref_dir", "dir_xyz"),
                # The top level and the offsets are the same names and the
                # same bounds as in create_column, which already holds the
                # TwoLevelsBased kind for columns. One name for one
                # quantity: two dictionaries for "the top of the
                # attachment" would mean two judges of it.
                #
                # 19.08: and the same HANDOVER OF AUTHORITY on omission as
                # with the column — one name for one quantity also means
                # one declaration for it. For an instance of the
                # TwoLevelsBased kind with no top attachment, the height
                # comes from the family's default, and the obligation
                # `FAMILY_TOP_LEVEL_PARAM == top_level` is not checked at
                # all. The cost was measured on the column: 420 units at
                # 2500 mm instead of 3600–4500, not a single refusal, three
                # audits missed it.
                ParamSpec("top_level", "sel",
                          omission_transfers=(
                              "высота приходит из умолчания семейства, а не "
                              "из программы, и обязательство верхней привязки "
                              "не проверяется вовсе"),
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("base_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
                ParamSpec("top_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("place", "family"), ("place", "element")),
            post=("instance exists (materialize); LocationPoint == xyz (±5mm) OR "
                  "LocationCurve endpoints == p0_mm/p1_mm (±5mm) for the "
                  "curve variant (geometry); rotation == rotation_deg (±0.1deg, modulo "
                  "360) (geometry); Mirrored/HandFlipped/FacingFlipped equal requested "
                  "states (semantic); level binding == resolved level (topology) (BIP "
                  "chain); reference direction == ref_dir when given, read "
                  "back from HandOrientation up to sense (geometry); "
                  "FAMILY_TOP_LEVEL_PARAM == top_level when given "
                  "(topology); base/top offsets == the requested millimetres "
                  "when given (semantic)"),
            writes_model=True,
            # The level stopped being unconditionally required: on the
            # curve variant it is present neither in the source (all 79 ЭОМ
            # tray covers have LevelId = -1) nor in the call (the overload
            # by reference does not accept a level). The requirement became
            # CONDITIONAL and lives in the compiler's plan, where it can be
            # expressed: the point variant requires a level, the curve one
            # requires a host.
            grounded=(("level", "levels", False),
                      ("top_level", "levels", False),
                      ("symbol", "family_symbols", False)),
            # rotation_deg — the same correction as for create_column
            # above. The offsets are the SAME keys and the SAME numbers as
            # for create_wall and create_column: this is one promise about
            # one quantity, and a different number here would mean two
            # judges of what "the same offset" is.
            tolerances={"base_offset_mm": 1.0, "top_offset_mm": 1.0,
                        "location_mm": 5.0, "rotation_deg": 0.1},
        ),
    OpSpec(
            name="delete",
            effect=EffectKind.DELETE,
            result=RESULT_DELETED_ELEMENT,
            family="modify",
            params=(
                # 🔴 THE TYPE IS NAMED EXPLICITLY (25.08.2026). As of this
                # date `ELEMENT` means "any INSTANCE" and does NOT accept
                # type kinds: a type has neither position nor geometry, and
                # `move_elements` on one died in Revit despite a GREEN
                # compile.
                # Here a type is legitimate, and this is a fact of the API,
                # not a relaxation: a Revit type has its OWN parameters
                # (type parameters), and a type can also be deleted. A slot
                # that needs a type is obligated to say so OUT LOUD — silence
                # no longer means "yes."
                # `change_type.target` is deliberately NOT among them: there
                # the target is the instance whose type is being changed,
                # and a type has no type of its own.
                ParamSpec("target", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,
                                     ReferenceKind.WALL_TYPE,
                                     ReferenceKind.FLOOR_TYPE,
                                     ReferenceKind.ROOF_TYPE,
                                     ReferenceKind.CEILING_TYPE)),
                ParamSpec("expected_identity", "identity", required=False),
            ),
            capability=(("delete", "element"),),
            # 🔴 THE BLAST RADIUS OF A DELETE IS HANDED OVER BY REVIT
            # ITSELF (22.08.2026), and the emission was DISCARDING it.
            # `Document.Delete` returns `ICollection<ElementId>` — everything
            # that went away along with the target — while the receipt
            # named ONE id, the very one that was asked for. So this is a
            # FACT here, not an obligation: a guard for "zero deleted
            # incidentally" would flag every deletion of a wall with a door
            # as red. There is no bound on incidental deletion, and it is
            # named as an absence, not signed off in green — see the
            # `_emit_delete` docstring.
            # WHY THIS IS NOT IN `post`. `post` is the registry of
            # PROMISES, and every one of its clauses must name a kind and
            # get an obligation in `translation_cert.REFINEMENT`. Incidental
            # deletion is NOT a promise: it is evidence that Revit hands
            # over for free. Writing it in as a clause would mean creating
            # a promise with no guard standing behind it — exactly the
            # defect the ratchet `spec._lint_post_clause_kinds` guards
            # against.
            post=("element no longer resolvable post-commit; requires envelope "
                  "allow_destructive=true (policy-gate on the plan, SPEC 12.2)"),
            writes_model=True,
            grounded=(),
        ),
    OpSpec(
            # CLASH fix, op 1/2 (28.07, operator's strategy: an early
            # honest release). Moving the WHOLE CONNECTED SUBGRAPH at
            # once — ElementTransformUtils.MoveElements(doc,
            # ICollection<ElementId>, XYZ) moves the set with ONE call, and
            # Revit drags along fittings and PRESERVES connections (unlike
            # moving element by element, where links break and get
            # re-established). The signature was verified by reflection
            # against RevitAPI.dll for all six versions — identical
            # 2021..2026.
            #
            # targets is the same id-pinned/ref-only pattern as host on a
            # door and a window (28.07) and refs on create_dimension: there
            # is no snapshot pool for elements of an arbitrary category. The
            # upper bound of 500 is a practical ceiling for one program
            # (its own MAX_OPS does not apply to elements INSIDE one op),
            # not a measured Revit API limit.
            name="move_elements",
            caveat=(
                "НЕ КЛАДИ В ОДНУ ПРОГРАММУ с созданием того, что двигаешь. "
                "Свидетель создающего опа проверяет положение В КОНЦЕ "
                "программы, а сдвиг его меняет — постусловие создателя "
                "нарушится и откатит ВСЮ программу. Замер 26.08.2026 живьём: "
                "80 стен со сдвигом в одной программе — отказ; те же 80 "
                "сдвигов ОТДЕЛЬНОЙ программой по `element_id` — 80 из 80."),
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
                ParamSpec("expected_identity", "identity", required=False),
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
                  # 🔴 THE BLAST RADIUS (22.08.2026). The three clauses
                  # above speak about the TARGET ITSELF, while the move's
                  # effect lives in its NEIGHBORS. The two added below are
                  # about the neighbors, and both cost one call per target;
                  # what they cost and what remains named as an absence —
                  # in the `_emit_move_elements` docstring.
                  "every door/window insert a moved HostObject carried before "
                  "the move is still hosted by it after (topology) — "
                  "HostObject.FindInserts(doors, windows) re-read, "
                  "shared/embedded deliberately excluded because an embedded "
                  "wall legitimately stops being embedded when moved away; "
                  "every LOCKED single-segment Dimension that depended on a "
                  "target before the move still resolves and is still locked "
                  "(topology) — Element.GetDependentElements + "
                  "Dimension.IsLocked re-read, multi-segment dimensions "
                  "counted but NOT judged because IsLocked is per-segment "
                  "there; "
                  "pinned element or stale id is a typed refusal, never a "
                  "live exception"),
            writes_model=True,
            grounded=(),
            tolerances={"location_mm": 1.0},
        ),
    OpSpec(
            # CLASH fix, op 2/2. Element.ChangeTypeId(ElementId) — the
            # signature and the return semantics are confirmed by the XML
            # documentation shipped INSIDE the assembly's NuGet package
            # (RevitAPI.xml, not the wiki): the return is InvalidElementId
            # in the ORDINARY case (the type changed IN PLACE, same
            # element), and a REAL ElementId only in the rare case where
            # Revit creates a NEW element instead (wall <-> curtain panel is
            # the only documented example). A type incompatibility is a
            # THROWN ArgumentException, not a return of InvalidElementId (a
            # naive "Invalid = failure" would confuse an ordinary success
            # with a failure). Identical on all six versions (since="2011"
            # in the documentation itself).
            #
            # type — element_id is required in v1: there is no type pool
            # across ALL categories (the same gap that panel_type on
            # set_curtain_panel closed with a bounded collector — here a
            # collector is impossible in principle, because the target's
            # category is unknown to the compiler ahead of time). Honestly
            # declared as a limitation, not a silent shortfall.
            name="change_type",
            effect=EffectKind.MUTATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="modify",
            params=(
                ParamSpec("target", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                ParamSpec("type", "target_w", required=True),
                ParamSpec("expected_identity", "identity", required=False),
            ),
            capability=(("set_type", "element"),),
            post=("GetTypeId() == requested type after this operation's Regenerate, "
                  "before subsequent operations (semantic, "
                  "re-read — the rare new-element case re-reads the "
                  "RETURNED id, never the stale original); incompatible "
                  "type or an internal/grouped element is a typed refusal "
                  "(caught ArgumentException/InvalidOperationException/"
                  "ModificationForbiddenException), never a live exception"),
            writes_model=True,
            grounded=(),
        ),
    OpSpec(
            # GEOMETRY JOIN — A DIRECT REQUEST FROM THE OWNER, 17.08.2026:
            # "so that the fact that this is joined is not lost but
            # preserved."
            #
            # WHY A SEPARATE OP, NOT A FIELD ON `create_wall`. A join is a
            # RELATION BETWEEN TWO elements, not a property of one. As a
            # field it can only be expressed for pairs created by the same
            # program, and it is silent about the pair "a new wall + an
            # already-standing slab" — i.e. about the main reassembly case.
            # The relation gets its own op exactly because it has two
            # operands.
            #
            # WHY NOT `Document.AutoJoinElements`. It exists (trap index:
            # 6/6 versions, throws AutoJoinFailedException), but it is
            # WHOLE-DOCUMENT and has no address: it cannot say "these two,"
            # and it cannot check pairwise either. An op with two operands
            # and a pairwise postcondition is strictly stronger.
            #
            # VERSION MEASUREMENT, 18.08.2026, BY THE LIVE COMPILE SERVICE
            # against the reference assemblies 2021-2026: the body of
            # `AreElementsJoined` + `JoinGeometry` + `GetJoinedElements`
            # compiles on ALL SIX, zero errors. There is NO version
            # fragility here, and that is why the op is not in
            # `VERSION_FRAGILE` — this is a measurement, not forgetfulness.
            #
            # THE `AreElementsJoined` PRECHECK IS MANDATORY, AND THIS IS NOT
            # CAUTION. Autodesk's documentation (trap index, 6/6):
            # `JoinGeometry` throws ArgumentException, "The elements are
            # already joined. -or- The elements cannot be joined." Without
            # a precheck, a REPEAT run of the same program — and
            # reassembly is exactly in the business of that — would fail on
            # an already-joined pair, meaning idempotency would break on
            # the previous run's own success.
            #
            # THE POSTCONDITION HERE IS A RARE CASE OF FULL COINCIDENCE
            # WITH THE PROMISE: the op promises "joined," and the witness
            # asks exactly `AreElementsJoined(doc, a, b)` post-commit. Not a
            # proxy, not a bounding box, not "looks like" — the very same
            # relation, re-read.
            name="join_elements",
            effect=EffectKind.MUTATE,
            # NOT A SINGLE NEW ELEMENT: the op changes a RELATION. The key
            # is named `joined_ids`, rather than reusing someone else's:
            # `moved_ids` would lie about a move, `id` would lie about a
            # creation. Of 66 writing ops, not one has ZERO identity
            # (measured by `len(spec.OPS)`), and this pair of ids is the
            # honest address of what the op touched.
            result=ResultSpec(IdentityCardinality.MANY, "joined_ids"),
            family="modify",
            params=(
                ParamSpec("first", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                ParamSpec("second", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
            ),
            capability=(("join", "element"),),
            post=("AreElementsJoined(doc, first, second) == true post-commit "
                  "(semantic, re-read by the SAME relation the op promises, "
                  "never a proxy); an already-joined pair is a no-op that "
                  "still satisfies the postcondition (idempotence: a rebuild "
                  "re-run must not fail on its own previous success); "
                  "elements that cannot be joined, a curtain-panel pair, or "
                  "a stale id are typed refusals (caught ArgumentException/"
                  "InvalidOperationException), never a live exception"),
            writes_model=True,
            grounded=(),
        ),
    OpSpec(
            # A curtain panel is NOT created separately — it exists only
            # as a CELL of the host's grid (design 2026-07-28). So the op is
            # not "create a panel" but "assign a type to a cell": Revit does
            # this with exactly one call — CurtainGrid.ChangePanelType(panel,
            # type), present on all six versions (measured against the
            # reference assemblies 2021-2026, 28.07).
            #
            # u/v ARE REQUIRED. A 1×1 grid is a special case (0,0), not an
            # excuse for having no address: without an address the question
            # "which exact cell to change" has no answer, and this compiler
            # has no right to guess. The address is the RANK of the
            # reference grid line, given by Panel.GetRefGridLines: 0 = the
            # cell before the first line, k = the cell after the k-th line
            # in order. The line order is built FROM GEOMETRY
            # (CURTAIN_CELL_ADDRESS_CS in authoring.py) and is therefore the
            # same for the extractor and for the emitter — otherwise the
            # address would not survive reassembly, where the line ids
            # differ.
            #
            # panel_type is NOT grounded against a pool: a cell's type
            # lives in TWO type spaces AT ONCE — PanelType/FamilySymbol
            # (glazing unit, curtain door) and WallType (a cell filled with
            # a wall; in the measured facade model 259 of 361 are such).
            # No snapshot pool covers the union, and a new pool is a
            # Fable-level change (REGISTRY_MODULES.md), not something this
            # wave can do on its own. So the selector is resolved IN
            # EMISSION by a bounded collector over both spaces, exactly as
            # load_family resolves a family by path: zero matches and more
            # than one are typed refusals, never "the first one found."
            # THE GRID LINE is the missing link of the curtain wall
            # generator.
            #
            # MEASUREMENT FROM THE NIGHT OF 28.07 (child_closure_20260728.json):
            # child closure is 417/1556 = 27%, and ALL reassembled hosts
            # have ZERO internal U/V lines despite BYTE-IDENTICAL types.
            # That is the diagnosis: the grid layout is a state that
            # create_wall does not carry, and without it a host has no
            # cells, no mullions, no panels — meaning its entire family of
            # children is not reproduced.
            #
            # There is exactly one constructor:
            # CurtainGrid.AddGridLine(isUGridLine, position,
            # oneSegmentOnly) -> CurtainGridLine (RevitAPI.xml and the CHM
            # of the reference package; present on all six versions,
            # measured 29.07). The parameters follow from this: direction
            # is the boolean isUGridLine, so the op has a closed u|v
            # enumeration rather than a free string; position is the POINT
            # the line passes through, in world mm.
            #
            # oneSegmentOnly=false is hard-coded: the line's segments are
            # edited by separate calls (AddSegment/RemoveSegment), and an
            # op that silently placed a single segment would not be "a grid
            # line," it would be a guess at one.
            #
            # 🔴 ONE LINE PER PROGRAM. THIS IS A PROPERTY OF REVIT, AND IT
            # COST A MODEL TEN MINUTES (measured 26.08.2026, a live turn).
            #
            # A real model, through chat, was building a 10×4 curtain wall
            # with cells: 22 tool calls, 630 seconds, the turn limit was
            # exhausted BEFORE the task closed. Of the ~16 cells requested,
            # 4 got built.
            #
            # The share-based instrument shows this from two sides, and
            # both are true:
            #   by final state       4 built / 0 accused = 100%
            #   by each attempt      0 built / 17 accused = 0%
            # The truth is in the GAP: laying out the grid costs 4–5
            # attempts per live line. The "100%" figure here is honest and
            # useless: it is about what survived, not about what it cost.
            #
            # 🔴 THE FIRST OF TWO "PROPERTIES" WAS REFUTED ON THE EVENING
            # OF 26.08.2026, AND WITH IT — THE "WORKING SCHEME" THAT HAD
            # BEEN DERIVED FROM IT.
            #
            # It used to say here: "Revit does not regenerate the grid
            # between calls." Checked BY EXECUTION — a program of TWO lines
            # was compiled and the emitted C# was read. The sequence:
            #     Regenerate · AddGridLine×3 · Regenerate · Regenerate ·
            #     AddGridLine×3 · Regenerate · Regenerate
            # There are TWO `doc.Regenerate()` calls between the lines. The
            # postcondition of this same op says the very same thing five
            # lines below ("re-read BY ITS OWN ID after Regenerate") — the
            # advice contradicted the contract within a single render, and
            # the model was reading both.
            #
            # WHAT WAS AN ACTUAL MEASUREMENT AND WHAT WAS A GUESS. The
            # numbers (17 attempts, 630 s) describe the SYMPTOM and are
            # correct. The mechanism behind them was inferred by the model
            # itself; in the trace it is recorded as a hypothesis ("the
            # emitter does not regenerate"), but it landed here as an
            # assertion. A canon shape: a guess presented as a fact — and
            # here it rode out to the MODEL as advice.
            #
            # THE COST IS GIVEN AS A NUMBER. On the evening of 26.08 the
            # model read this advice, built its work around it ("the
            # contract explained the cause, I'll take one line per call"),
            # and spent 15 calls and 529 seconds without laying down a
            # single one of the four lines. In other words, the false cause
            # pushed it into the MOST EXPENSIVE strategy: every round trip
            # costs ~14 s of fixed overhead.
            #
            # 🔴 THE CAUSE WAS FOUND ON THE EVENING OF 26.08.2026, AND
            # "UNKNOWN" IS LIFTED.
            #
            # Live Revit 2026, curtain wall 2140306 (0,-60000)->(8000,
            # -60000), level "01 Floor" at elevation 0, height 4000. Nine
            # trials, and ONE model explains all nine:
            #
            #   u (2000,-60000,2000)  SUCCESS  panels 3->4
            #   u (4000,-60000,2000)  null          <- same z=2000
            #   u (6000,-60000,2000)  null          <- same z=2000
            #   v (4000,-60000,2000)  SUCCESS  4->6
            #   u (2100,-60000,2000)  null          <- same z=2000
            #   u (4000,-60000,3000)  SUCCESS  6->8   <- z NEW
            #   u (5000,-60000,2000)  null          <- same z=2000
            #   u (5000,-60000,1000)  SUCCESS  8->10  <- z NEW
            #   u (1000,-60000,3500)  SUCCESS 10->12  <- z NEW
            #
            # `direction="u"` gives a line at a CONSTANT Z, `"v"` at a
            # constant position along the host. The marathon model was
            # moving X while holding Z, and each time it was asking for THE
            # SAME horizontal line.
            #
            # THREE PREDICTIONS, MADE BEFORE THE RUN, ALL THREE LANDED:
            #   u (7000,-60000,1000) predicted null (z taken)   -> null   ✓
            #   v (4000,-60000,3900) predicted null (x taken)   -> null   ✓
            #   v (7000,-60000,100)  predicted SUCCESS (x free) -> SUCCESS ✓
            # Agreement across nine trials could still be explained by
            # curve-fitting; three predictions made in advance can no
            # longer be.
            #
            # 🔴 THE BOUNDARY OF THIS KNOWLEDGE, AND IT IS NARROW. One
            # document, one host type, one STRAIGHT wall, one version.
            # Therefore the axis in the refusal is NOT ASSERTED from this
            # record, but is READ off the `FullCurve` of an already-existing
            # line (see `_emit_create_curtain_grid_line`): the reading holds
            # true on a curved host too, and even if u/v turn out reversed
            # for a different grid kind. Here — advice to the author; there
            # — an instrument.
            #
            # A THIRD OUTCOME, distinct from null: a point EXACTLY on the
            # host's boundary (z equal to the wall's bottom elevation) gives
            # an `ArgumentException` with an EMPTY message from Revit.
            # Measured in the same place.
            #
            # WHY THIS WAS NOT TURNED INTO A REFUSAL AT PARSE TIME. Only
            # the document knows which coordinates are taken, and it knows
            # this at the moment of EXECUTION, not of parsing: a human can
            # also add lines between programs. A list inferred on the
            # Python side would drift from the model — this tree's named
            # class of defect. So the check lives in emission and reads the
            # document, while the contract only tells the author what to
            # move.
            name="create_curtain_grid_line",
            caveat=(
                "ОСЬ РЕШАЕТ, КАКАЯ КООРДИНАТА ТОЧКИ ЗНАЧИМА, и это НЕ та, "
                "что подсказывает имя. Замерено живьём 26.08.2026 (Revit "
                "2026, прямая витражная стена, 9 заходов + 3 сбывшихся "
                "предсказания): direction='u' ставит линию ГОРИЗОНТАЛЬНО — "
                "значима ВЫСОТА, третья координата; direction='v' ставит "
                "ВЕРТИКАЛЬНО — значимо положение ВДОЛЬ носителя, первые две. "
                "Линия на УЖЕ ЗАНЯТОЙ координате этой оси не создаётся: "
                "AddGridLine возвращает null БЕЗ СООБЩЕНИЯ. Поэтому "
                "раскладка задаётся ПЕРЕЧНЕМ РАЗНЫХ координат по каждой оси, "
                "а не сдвигом точки вдоль линии: подвинуть X у 'u' — значит "
                "запросить ту же самую линию ещё раз. Точка РОВНО на границе "
                "носителя (z равен отметке низа стены) даёт ArgumentException "
                "с пустым сообщением — ставь точку ВНУТРЬ. Отказ теперь "
                "перечисляет линии этой оси, что уже стоят, и расстояние до "
                "каждой: расстояние 0 мм и есть причина. "
                "ЧЕМ КУПЛЕНО: марафон 26.08 — 17 попыток пачкой за 630 с и 15 "
                "вызовов по одной за 529 с, четыре линии так и не легли, "
                "потому что модель двигала X, держа Z."),
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
            # The witness has one tolerance: the line must PASS through
            # the requested point. The radius within which a mullion counts
            # as "on this line" is deliberately not included here — it is
            # evidence for the receipt (whether the host type itself places
            # mullions), not an obligation, and the registry of witness
            # tolerances must not pretend that it is.
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
            # absolute coords). CORRECTED 2026-08-15 — the old parenthetical
            # "no name/ref resolution inside the group" is FALSE since
            # 2026-08-12: `authoring_validation` refuses a ref pointing OUTSIDE
            # the member set and a ref pointing FORWARD (to a member declared
            # below), and allows a ref to an EARLIER member, because the member
            # order is the creation order;
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
                  "delta); GroupType Name == name when given; КАЖДЫЙ ЧЛЕН "
                  "размещения стоит там же, где член определения, плюс "
                  "смещение этого размещения (geometry) — величина, которую "
                  "Revit ВЫВОДИТ сам, а не получает аргументом"),
            writes_model=True,
            # 🔴 `group_placement_mm` (19.08) — THE NUMBER WAS CHOSEN, NOT
            # MEASURED, and this is stated here so the next reader does not
            # mistake it for a measured one.
            #
            # Why the tolerance is COARSE, not "equality to the mm." The
            # signal is taken from a member's bounding box, and the bbox
            # LEGITIMATELY differs between instances if members are joined
            # to their neighbors differently: a join shifts the solid by
            # half its thickness (measured 18.08, `get_ElementsAtJoin`).
            # Requiring equality would roll back CORRECTLY built buildings —
            # a mistake already paid for on `create_beam` 27.07 and one
            # that would be repeated here verbatim.
            #
            # Separating the classes: half a wall's thickness is hundreds
            # of mm; the miss we are catching is a member that ended up on
            # the wrong grid node (a 6000 mm step) or the wrong floor
            # (3600 mm). A threshold of 1000 mm gives a 3.6x difference
            # from the observed class of miss and is deliberately larger
            # than any joint. The exact maximum discrepancy goes into the
            # receipt AS A NUMBER — refine the threshold with the first
            # live run on a real group.
            tolerances={"group_placement_mm": 1000.0},
            grounded=(),
        ),
]
