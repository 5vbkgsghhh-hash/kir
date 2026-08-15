"""ops_authoring — v1 core: query + authoring + modify + architectural (wall/floor/roof/stairs/...).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

#: ``create_wall.location_line`` spelled out <-> Revit's ``WallLocationLine``
#: ordinals, which is what ``WALL_KEY_REF_PARAM`` stores.  ONE table, shared by
#: the emitter (word -> ordinal) and the lift (ordinal -> word), so the two
#: directions cannot drift apart.
#:
#: ЧТО ЭТУ ТАБЛИЦУ ПИННИТ, А ЧТО НЕТ — замерено 2026-08-12, потому что строка,
#: стоявшая здесь ("Order is Revit's, and the tests pin it"), обещала шире
#: сделанного.  Тесты пиннят ПОРЯДОК ЗНАЧЕНИЙ (`list(values()) == [0..5]`),
#: длину, членство имён и инъективность — и НИКОГДА ПАРУ имя-ординал.
#: Переставь две пары, оставив значения 0..5 по порядку, и не заметит НИЧТО:
#: полный набор побайтно неподвижен (7 failed / 6140 passed / 7750 subtests
#: до и после), ворота Roslyn 6/6 (1872 compiled), 0 из 57 голденов несут
#: ``WALL_KEY_REF_PARAM``.  Правка, которой это случится на практике, — не
#: диверсия, а АЛФАВИТНАЯ СОРТИРОВКА КЛЮЧЕЙ: обычная уборка, ломает четыре
#: пары из шести, все сторожа зелёные.
#:
#: ПРИЧИНА СТРУКТУРНАЯ, А НЕ «НЕ НАПИСАЛИ ТЕСТ».  Эмиттер пишет
#: ``ORDINALS[name]`` (``authoring.py:557``), свидетель сверяет
#: ``ORDINALS[name]`` (``authoring.py:725``) — оба конца берут число ОТСЮДА,
#: сойтись их заставляет общий источник, и свидетель не может возразить
#: таблице.  Пара имя-ординал — внешний факт о Revit, поэтому пиннить её
#: способен только авторитет ВНЕ этого репозитория: сборки RevitAPI, где
#: дубликат метки ``case`` даёт ``CS0152``, то есть программа обязана НЕ
#: компилироваться ровно тогда, когда пара верна.  Такая стадия ворот
#: написана на ветке ``fix/kir-gate-binding-guard-accounting`` (``3003c388``)
#: и В ЭТОМ ДЕРЕВЕ ЕЁ НЕТ — проверь, что она здесь, прежде чем считать пару
#: защищённой.  Пока её нет, таблица верна (36/36 пар подтверждены Autodesk
#: на шести версиях 12.08), но НЕ ЗАЩИЩЕНА.
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
                    # wave/mep-electrical (2026-08-09): спросить каталог
                    # ДО попытки — единственный способ не нарваться на
                    # KIR-G102 там, где у проекта несколько коробов или
                    # гибких типов с одним именем (в инженерных разделах это
                    # норма, см. три «По умолчанию» у воздуховодов).
                    "conduit_types", "flex_duct_types", "flex_pipe_types",
                    # wave/analysis (2026-08-09): случаи загружения и типы
                    # нагрузок. Здесь предварительный запрос нужнее, чем где
                    # бы то ни было: `load_case` у всех трёх нагрузок
                    # ОБЯЗАТЕЛЕН, а в расчётном проекте случаев загружения
                    # десятки («ДЛ1», «Снег», «Ветер X»...), то есть селектор
                    # по имени вслепую — это отказ ходом позже.
                    "load_cases", "point_load_types", "line_load_types",
                    "area_load_types",
                    # wave/framing (2026-08-09): у фермы документного типа по
                    # умолчанию НЕТ вовсе (ElementTypeGroup.TrussType — CS0117
                    # на всех шести), поэтому спросить каталог заранее для неё
                    # не удобство, а единственный способ назвать тип, не
                    # нарвавшись на KIR-G102/G104 уже внутри программы.
                    "truss_types",
                    # wave/sweep (2026-08-09): карнизы/русты и краевые
                    # профили. Здесь предварительный запрос нужен СИЛЬНЕЕ,
                    # чем где бы то ни было в этой таблице, и причина
                    # документирована Autodesk: у стенного профиля ТИП
                    # ЗАДАЁТ ГЕОМЕТРИЮ ЦЕЛИКОМ («the wall sweep's profile
                    # and type are taken from the wall sweep type
                    # properties»), то есть выбор типа вслепую — это выбор
                    # вслепую того, ЧТО будет построено, а не только как оно
                    # называется в спецификации. `wall_sweep_types` при этом
                    # ОДИН пул на две категории, поэтому имя типа — обычно
                    # единственный способ отличить карниз от руста.
                    "wall_sweep_types", "slab_edge_types",
                    # wave/detail (2026-08-09): типы заливки. Спросить каталог
                    # заранее нужно ровно по той же причине, что у коробов:
                    # у настоящего проекта заливок десятки, имена у них
                    # оформительские («Бетон», «Грунт», «Штриховка 45»), и
                    # промах по имени — это KIR-G102 ходом позже. Документное
                    # умолчание у заливки есть, но выбирать штриховку
                    # умолчанием — то же самое, что выбирать её жребием.
                    "filled_region_types",
                    # ═══ 12.08.2026: ВОСЕМЬ ПУЛОВ, В КОТОРЫЕ КОМПИЛЯТОР УМЕЛ
                    # ПИСАТЬ, НЕ УМЕЯ ЧИТАТЬ. Множество взято у РЕЕСТРА, а не
                    # у списка задач: `OpSpec.grounded` по ВСЕМ опам минус эти
                    # choices. Прежний замер называл ШЕСТЬ — он выводился из
                    # нужд тридцати НЕПРОВЕРЕННЫХ опов, а `create_ceiling` и
                    # `create_railing` давно проверены и потому в тот срез не
                    # попали. Ответ по части множества опять оказался меньше
                    # ответа по всему множеству.
                    #
                    # ЧТО ЭТО СТОИЛО ДАННЫХ: НИЧЕГО. Все восемь пулов снимок
                    # УЖЕ собирает (`open_model.__profile_required_pools`, 36
                    # имён), и коллектор каждого уже написан там же. Разошлась
                    # ровно эта таблица — читающее перечисление вели рукой
                    # против пишущей стороны, которую ведёт реестр.
                    #
                    # РАЗМЕР ОТВЕТА ЗАМЕРЕН ДО РАСШИРЕНИЯ, а не предположен:
                    # 69 сохранённых профилей корпуса, `total_count` каждого
                    # пула. `ceiling_types` максимум 8 (медиана 3),
                    # `railing_types` максимум 22 (медиана 6), усечений по
                    # всему корпусу НИ ОДНОГО. Самый большой пул вообще —
                    # `family_symbols` 741, и он читаем давно: потолок канала
                    # эти восемь не двигают. Проверка не формальная: канал
                    # ОТВЕТА — второй такой же канал, что и печать контракта,
                    # а резак, режущий МНОЖЕСТВО по длине, отдал бы модели
                    # список, читаемый как полный, из которого делается выбор.
                    #
                    # ШЕСТЬ ИЗ ВОСЬМИ ОФЛАЙН НЕ ЗАМЕРИТЬ, И ЭТО НАЗВАНО:
                    # `toposolid_types`, `building_pad_types`,
                    # `wall_foundation_types`, `area_reinforcement_types`,
                    # `rebar_bar_types`, `rebar_hook_types` попали в снимок
                    # 09–10.08 (`cea112cc`, `2a84ede1`, `1f39658a`), а самый
                    # новый профиль корпуса — 04.08. НИ ОДИН сохранённый
                    # профиль не мог их нести; их размер закрывает первое же
                    # живое чтение, а не правка кода. Тот же порядок, что у
                    # `dimension_extract`.
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
            name="create_multi_segment_grid",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                # ОТКРЫТАЯ ломаная, а не контур: `MultiSegmentGrid.Create`
                # документирован дословно как «an open curve loop consisting
                # of lines and arcs», и `IsValidCurveLoop` возвращает false
                # ровно на замкнутом.  Род `path` (2..64 точки, без проверки
                # площади) — тот же, которым пользуется `create_railing`;
                # `pts` потребовал бы >=3 точек и ненулевой площади, то есть
                # по построению замкнул бы цепь, которую API запрещает.
                ParamSpec("path", "path", required=True),
                # Уровень нужен НЕ как привязка оси (у оси её нет), а как
                # ОТМЕТКА горизонтального эскизного плана: четвёртый аргумент
                # Create — id `SketchPlane`, и `IsValidSketchPlaneId` требует
                # ГОРИЗОНТАЛЬНЫЙ.  Отметку надо откуда-то взять, и брать её из
                # воздуха (Z=0) значило бы материализовать умолчание, которого
                # автор не называл.
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
            ),
            capability=(("create", "grid"),),
            # ЧТО НЕ ОБЕЩАНО НАМЕРЕННО: порядок `GetGridIds()`.  Он нигде не
            # документирован, и обещание «i-я ось соответствует i-му звену»
            # было бы догадкой; свидетель поэтому сопоставляет МНОЖЕСТВА (см.
            # эмиттер), а не индексы.  Имя оси тоже не обещано: имена своим
            # осям Revit присваивает сам.
            post=("multi-segment grid exists; it owns exactly one Grid per "
                  "path segment (GetGridIds().Count == len(path)-1); every "
                  "authored segment is matched by a created Grid whose own "
                  "Curve endpoints equal that segment's ends (±5mm), each "
                  "Grid matched at most once — the segment ORDER of "
                  "GetGridIds() is deliberately NOT asserted"),
            writes_model=True,
            grounded=(("level", "levels", True),),
            # То же число и та же величина, что у `create_grid.endpoint_mm`:
            # обратное чтение концов кривой ОСИ.  Не новый допуск — тот же,
            # применённый к тому же прибору.
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
            name="create_extrusion_roof",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # РАБОЧАЯ ПЛОСКОСТЬ, НАЗВАННАЯ ПЛАНОВОЙ ЛИНИЕЙ.  Плоскость
                # выдавленной кровли обязана быть ПАРАЛЛЕЛЬНА оси z (так
                # написано в самой сигнатуре NewExtrusionRoof), то есть
                # вертикальна; вертикальная плоскость однозначно задаётся
                # своим следом на плане.  p0/p1 — этот след.  Пара
                # p0_mm/p1_mm выбрана НЕ по вкусу: `authoring_validation`
                # прогоняет по ней закон «длина ~0» для ЛЮБОГО опа, у
                # которого она есть, и невырожденность направления
                # плоскости достаётся здесь ДАРОМ и той же реализацией,
                # что у стены.
                ParamSpec("p0_mm", "pt_xy", required=True),
                ParamSpec("p1_mm", "pt_xy", required=True),
                # ПРОФИЛЬ — В СОБСТВЕННЫХ КООРДИНАТАХ ПЛОСКОСТИ: [u_mm, z_mm],
                # где u отмеряется от p0 вдоль p0->p1, а z — мировая отметка.
                #
                # ПОЧЕМУ НЕ CONTOUR И НЕ МИРОВЫЕ ТОЧКИ.  CONTOUR замкнут по
                # построению и кладёт каждую точку на Z=0 — это язык ПЛАНА, а
                # профиль выдавливания есть ОТКРЫТАЯ цепь в ВЕРТИКАЛЬНОЙ
                # плоскости; годится оттуда только арифметика дуг.  Мировые
                # [x,y,z] выглядят естественнее, но потребовали бы проверки
                # «все точки лежат в одной вертикальной плоскости», а у неё
                # нет выводимого допуска — пришлось бы ЧИСЛО ВЫДУМАТЬ.  В
                # координатах плоскости компланарность не проверяется, потому
                # что она ТОЖДЕСТВО: каждая точка строится как
                # p0 + u*dir + z*Z.  Незаконное состояние стало
                # непредставимым, а не отловленным.
                ParamSpec("profile_mm", "path", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("type", "sel"),          # omitted -> doc default roof type
                # Границы выдавливания вдоль НОРМАЛИ плоскости, от неё же.
                # Знак нормали Revit выбирает сам, поэтому эмиттер читает
                # `ReferencePlane.Normal` и приводит пару к НАШЕЙ ориентации
                # (dir x Z) прямо в C# — иначе кровля уехала бы на другую
                # сторону здания молча.
                ParamSpec("start_mm", "num", required=True,
                          min_val=-1_000_000, max_val=1_000_000),
                ParamSpec("end_mm", "num", required=True,
                          min_val=-1_000_000, max_val=1_000_000),
            ),
            capability=(("create", "element"),),
            # НИ ОДНОГО «±<число>»: единственный числовой допуск этого опа
            # читается ИЗ ЖИВОГО ДОКУМЕНТА (`Application.VertexTolerance`),
            # а не берётся из реестра — см. эмиттер.  Закон 3 провенанса
            # (`emit_model.py`) требует, чтобы каждое «±N» в post лежало в
            # tolerances; здесь их нет, и tolerances пуст ЧЕСТНО, а не по
            # забывчивости.
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
                # РОВНО ОДНО ИЗ ДВУХ: прямой марш (`p0_mm`/`p1_mm`) ЛИБО
                # винтовой (`spiral`).  Поэтому концы перестали быть
                # required НА УРОВНЕ СХЕМЫ (09.08.2026): обязательность стала
                # ВЗАИМНОЙ, а взаимную схема выразить не может — она живёт в
                # компиляторе типизированным KIR-P007, тем же приёмом и по
                # той же причине, что у create_ceiling (outline против
                # contour) и place_family (xyz против p0_mm/p1_mm).
                #
                # ЗАМЕНЫ НЕ ПРОИЗОШЛО, И ЭТО РЕШЕНИЕ: обратный ход
                # (decompile/lift.py::_lift_stairs) эмитирует именно
                # `p0_mm`/`p1_mm` — концы марша, снятые с элемента, — и если
                # бы прямые концы исчезли, круг разомкнулся бы на каждой
                # лестнице каждого разобранного здания.
                ParamSpec("p0_mm", "pt_xy"),           # run start (base level)
                ParamSpec("p1_mm", "pt_xy"),           # run direction/end
                ParamSpec("base_level", "sel", required=True),
                ParamSpec("top_level", "sel", required=True),
                ParamSpec("width_mm", "mm", min_val=600, max_val=5_000),
                # ВИНТОВОЙ МАРШ (09.08.2026) — StairsRun.CreateSpiralRun,
                # ЕСТЬ и БАЙТ-В-БАЙТ ОДИНАКОВ на всех шести поставляемых
                # версиях (перепроверено по эталонным сборкам:
                # `M:...StairsRun.CreateSpiralRun(Document,ElementId,XYZ,
                # Double,Double,Double,Boolean,StairsRunJustification)` в
                # RevitAPI.xml 2021/2022/2023/2024 (net48) и 2025/2026
                # (net8.0), плюс живой Roslyn на :52412 собрал эмиссию 6/6).
                #
                # Ломаной из двух точек винт невыразим ВООБЩЕ: прямой марш
                # даёт ДРУГУЮ форму, а не приближение, — тот же класс, что
                # «ломаная вместо закруглённого края» у потолка.  Углы — в
                # ГРАДУСАХ, как всё авторское в KIR (`rotation_deg`,
                # `slopes[].angle_deg`); радианы канонической дуги приходят с
                # ОБРАТНОГО хода, а это вход, который пишет человек или
                # модель.  Законы формы и границы — в
                # `authoring_validation._validate_spiral`.
                ParamSpec("spiral", "spiral"),
            ),
            capability=(("create", "element"),),
            post=("stairs exist; base/top level == resolved levels (topology); "
                  ">=1 run created; width_mm held ±5mm when supplied; "
                  "spiral run path contains an Arc when spiral is given "
                  "(geometry — NOT its centre/radius/sweep: the relation "
                  "between the requested centre and what GetStairsPath "
                  "returns is UNMEASURED, so those are recorded in the "
                  "readback for the first live device and gated by nobody); "
                  "MUST be the sole op of its program "
                  "(StairsEditScope owns its transactions — KIR-L002 otherwise)"),
            writes_model=True,
            grounded=(("base_level", "levels", True), ("top_level", "levels", True)),
            # 03.08: обещанные ±5 мм ширины марша.  Число то же, что стояло
            # литералом в emit_stairs_program.
            tolerances={"width_mm": 5.0},
        ),
    OpSpec(
            name="create_stairs_landing",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                # ЛЕСТНИЦА-ХОЗЯИН.  Род `target_w` — тот же, которым
                # `create_railing.host` и `create_multistory_stairs.stairs`
                # уже адресуют лестницу; новой механики ссылки не заводится.
                #
                # `ref_kinds` ПУСТ НАМЕРЕННО, и это НЕ копия соседа, а
                # следствие закона пачки: оп сам лежит в `spec.SOLO_OPS`,
                # значит он ЕДИНСТВЕННЫЙ оп своей программы и предшественника
                # у него нет ни одного.  `by: ref` здесь не «опасен» — он
                # неразрешим по построению, и пустой `ref_kinds` делает его
                # типизированным отказом НА РАЗБОРЕ, а не исключением в
                # эмиссии.  Единственная законная форма — `element_id`
                # лестницы, уже стоящей в модели.
                ParamSpec("stairs", "target_w", required=True, ref_kinds=()),
                # ГРАНИЦА ПЛОЩАДКИ — ЭТО ЭСКИЗ, ЗНАЧИТ CONTOUR.  Второго
                # способа задать профиль в этом компиляторе нет и заводить
                # его нельзя: род `region` даром приносит адреса точек от
                # осей (RELATE), дуги, законы замыкания, нулевые рёбра,
                # самопересечение и вырожденную площадь — ровно тот набор,
                # который `CreateSketchedLanding` требует от `CurveLoop`
                # («closed», «bound Line or bound Arc»).  Дырки ОТКАЗЫВАЮТСЯ
                # (второго кольца в подписи нет ни на одной версии) —
                # `stairs_landing_emit`, KIR-E008.
                ParamSpec("contour", "region", required=True),
                # ОТМЕТКА ПЛОЩАДКИ ОТНОСИТЕЛЬНО БАЗЫ ЛЕСТНИЦЫ — так её
                # называет сам API, дословно: «The base elevation is relative
                # to the base elevation of the stairs» (RevitAPI.xml,
                # `CreateSketchedLanding`, все шесть версий).  Абсолютной
                # отметки у этого аргумента нет вовсе, поэтому и параметр
                # относительный: перевод в абсолютную требовал бы читать
                # `Stairs.BaseElevation` ДО эмиссии, то есть живого Revit.
                #
                # ГРАНИЦЫ ВЫВЕДЕНЫ, А НЕ НАЗНАЧЕНЫ, и обе половины названы:
                #
                #  * ВЕРХ = 9 144 000 мм — это ровно «30000 feet in absolute
                #    value» из текста самого Autodesk (30 000 × 304.8).  Число
                #    внешнее, наше в нём только перевод единиц.
                #  * НИЗ = 0 — СЛАБАЯ граница, и слабость эта намеренная.
                #    Autodesk требует «equal to or greater than half of the
                #    riser height», а высота подступенка = высота лестницы /
                #    число подступенков, то есть величина ЖИВОЙ модели,
                #    которой у компилятора нет.  Ноль не отвергает НИ ОДНОГО
                #    законного значения (любое законное строго больше нуля),
                #    а точную границу ставит РАНТАЙМ-ОТКАЗ, читающий
                #    `Stairs.ActualRiserHeight` у самой лестницы и называющий
                #    измеренное число автору.  Граница, придуманная взамен,
                #    была бы ровно `create_door.sill_mm min_val=0` — 140
                #    отрицательных отметок из 151 в настоящем доме.
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
            # ПУСТО, И ЭТО ЗАМЕР, А НЕ ПРОПУСК.  Оба допуска этого опа зависят
            # от ЖИВОЙ модели и потому не могут быть реестровыми константами
            # по построению: допуск границы = собственный `VertexTolerance`
            # документа плюс квант нашей эмиссии, допуск отметки = высота
            # подступенка ЭТОЙ лестницы.  Считает их эмиссия, из чисел самого
            # Revit — тот же приём и та же причина, что у `create_solid_*`.
            # Высота подступенка здесь задаёт СЕТКУ допустимых отметок, а не
            # широкий допуск свидетеля: ±1 подступенок обязан провалиться.
            tolerances={},
        ),
    OpSpec(
            name="create_multistory_stairs",
            effect=EffectKind.CREATE,
            result=RESULT_UNREFERENCED_ELEMENT,
            family="authoring",
            params=(
                # Лестница-ОРИГИНАЛ.  Род `target_w` — ровно тот, которым
                # `create_railing.host` уже адресует лестницу-владельца, так
                # что новой механики ссылки не заводится.  Ссылка `by: ref`
                # на `create_stairs` ТОЙ ЖЕ программы недостижима по закону
                # пачки (KIR-L002, `spec.SOLO_OPS`) — и это ровно тот шов,
                # ради которого оп существует: марш строится своей
                # программой, а РАЗМНОЖАЕТСЯ по этажам следующей, одним
                # вызовом, рядом с любыми соседями.
                ParamSpec("stairs", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                # ВСЕ уровни, на которых лестница обязана стоять — включая
                # её собственный базовый.  Список селекторов, а не список
                # id: уровни в KIR адресуются именем везде, и заставлять
                # автора знать element_id ради одного опа было бы регрессом
                # языка.  Почему ВКЛЮЧАЯ базовый — см. post.
                #
                # `ref_kinds` ПУСТ НАМЕРЕННО, и это отказ по названной
                # причине, а не недосмотр.  Ссылка `by: ref` внутри СПИСКА
                # прошла бы мимо проверки графа зависимостей: план
                # (`compiler.plan_program`) собирает рёбра только у родов
                # `sel`/`target_w`/`refs_w`, и ссылка на несуществующий или
                # не-уровневый оп доехала бы до эмиссии непроверенной.
                # Научить план новому роду можно, но НЕ НУЖНО: закон пачки
                # уже говорит, что уровень, созданный программой тела, виден
                # лестничной ПО ИМЕНИ (текст отказа KIR-L002 дословно), —
                # значит внутрипрограммная ссылка на уровень здесь не то
                # чтобы опасна, она бессмысленна.  Пустой `ref_kinds` делает
                # `by: ref` типизированным отказом на разборе.
                ParamSpec("levels", "sel_list", required=True),
            ),
            capability=(("create", "element"),),
            # ТОЧНОЕ РАВЕНСТВО МНОЖЕСТВ, БЕЗ ДОПУСКА.  `MultistoryStairs`
            # после `Create` уже занимает базовый уровень оригинала, и
            # request, который его не называет, означал бы «отсоедини» —
            # намерение, которого автор не писал.  Такой запрос ОТКАЗЫВАЕТ
            # (типизированно, с именем недостающего уровня), и ровно поэтому
            # свидетелю доступно РАВЕНСТВО, а не включение: включение прошло
            # бы и тогда, когда ConnectLevels не подключил ничего.
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
                # ROOM_NUMBER is independent from ROOM_NAME.  It is exact
                # model identity, so an empty value and outer whitespace are
                # not normalised into a different authored program.
                ParamSpec("number", "str", exact_string=True),
            ),
            capability=(("create", "room_space"),),
            post=("room exists and has nonzero enclosed area; LevelId == resolved "
                  "level (topology); LocationPoint == xy (±5mm); Name == name "
                  "when given; Number == number when given; placed AFTER "
                  "doc.Regenerate() when walls precede (v0 rule)"),
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
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),        # omitted -> sole snapshot entry
                ParamSpec("rotation_deg", "deg", default=0.0),
                ParamSpec("mirrored", "bool", default=False),
                ParamSpec("hand_flipped", "bool", default=False),
                ParamSpec("facing_flipped", "bool", default=False),
                # ── РОД РАЗМЕЩЕНИЯ (11.08.2026) ──────────────────────────
                #
                # ПОВОД ЗАМЕРЕН, А НЕ ПРИДУМАН. `tools/coverage_matrix.py`
                # по всему корпусу (11 РАЗЛИЧНЫХ документов; 76 каталогов —
                # это каталоги, а не здания) даёт отказ лифтера «place_family
                # ставит только точечные размещения (OneLevelBased/
                # OneLevelBasedHosted)» на двух родах:
                #     WorkPlaneBased    483 эл. на 7 документах из 11
                #     TwoLevelsBased   9392 эл. на 4 документах
                # Семь документов из одиннадцати — самый широкий разброс по
                # зданиям среди всех действенных строк корпуса, а широкий
                # разброс по логике самой карты означает, что неверно НАШЕ
                # правило вообще, а не особенность одного проекта.
                #
                # `ViewBased` и `CurveBasedDetail` (999 и 862 эл. на 3
                # документах) СОЗНАТЕЛЬНО НЕ ВЗЯТЫ: они видозависимы, а
                # `L0Element` не несёт вида-владельца вовсе и ни один оп KIR
                # не создаёт Вид (`authoring._annot_view_res` отказывает
                # `in_view: ref` именно на этой предпосылке). Взять их
                # значило бы упереться в ту же стену, что размер, марка и
                # текст, — и это отдельный, более крупный разговор о ЯЗЫКЕ.
                #
                # У ОБОИХ НОВЫХ РОДОВ НЕТ ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ, и это не
                # забывчивость: отсутствующий ключ обязан остаться
                # отсутствующим, иначе каждая уже написанная программа
                # place_family сменила бы эмитируемый C# (18 700 экземпляров
                # демо заморожены корпусом байт-паритета), а свидетель начал
                # бы требовать величину, которой автор не называл — ровно тот
                # дефект, что стоил отката каждой верной фасадной стене
                # (`height_mm`, замер 29.07).
                #
                # ОБРАТНОГО ХОДА У ОБОИХ РОДОВ НЕТ, и это надо знать здесь,
                # а не узнать следующим замером: `schema.L0Element` несёт
                # РОВНО ОДИН уровень (`level_id`) и НЕ несёт ссылки на
                # рабочую плоскость ни полем, ни боковым индексом. Волна
                # расширяет ПРЯМОЙ ход — то, что инженер может попросить, —
                # а подъём такого экземпляра остаётся невозможным, и лифтер
                # обязан продолжать отказывать.
                #
                # `ref_dir` — НАПРАВЛЕНИЕ отсчёта на рабочей плоскости, а не
                # положение: род `pt_xyz` взят потому, что другого рода для
                # тройки чисел в реестре нет, и ровно по тому же образцу
                # живёт `create_face_wall.face_normal` — включая запись в
                # `relate.ADDRESS_EXCLUDED`, без которой RELATE предложил бы
                # адресовать НАПРАВЛЕНИЕ пересечением осей.
                ParamSpec("ref_dir", "pt_xyz"),
                # Верхний уровень и смещения — те же имена и те же границы,
                # что у create_column, который уже держит род TwoLevelsBased
                # для колонн. Одно имя на одну величину: два словаря для
                # «верха привязки» означали бы двух судей о нём.
                ParamSpec("top_level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("base_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
                ParamSpec("top_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("place", "family"), ("place", "element")),
            post=("instance exists; LocationPoint == xyz (±5mm) OR "
                  "LocationCurve endpoints == p0_mm/p1_mm (±5mm) for the "
                  "curve variant; rotation == rotation_deg (±0.1deg, modulo "
                  "360); Mirrored/HandFlipped/FacingFlipped equal requested "
                  "states; level binding == resolved level (topology, BIP "
                  "chain); reference direction == ref_dir when given, read "
                  "back from HandOrientation up to sense (geometry); "
                  "FAMILY_TOP_LEVEL_PARAM == top_level when given "
                  "(topology); base/top offsets == the requested millimetres "
                  "when given (semantic)"),
            writes_model=True,
            # Уровень перестал быть безусловно обязательным: у кривого
            # варианта его нет ни в источнике (все 79 кожухов ЭОМ имеют
            # LevelId = -1), ни в вызове (перегрузка по ссылке уровня не
            # принимает). Обязательность стала УСЛОВНОЙ и живёт в плане
            # компилятора, где её можно выразить: точечный вариант требует
            # уровень, кривой — хост.
            grounded=(("level", "levels", False),
                      ("top_level", "levels", False),
                      ("symbol", "family_symbols", False)),
            # rotation_deg — та же поправка, что у create_column выше.
            # Смещения — ТЕ ЖЕ ключи и ТЕ ЖЕ числа, что у create_wall и
            # create_column: это одно обещание об одной величине, и
            # другое число здесь означало бы двух судей о том, что
            # такое «то же смещение».
            tolerances={"base_offset_mm": 1.0, "top_offset_mm": 1.0,
                        "location_mm": 5.0, "rotation_deg": 0.1},
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
