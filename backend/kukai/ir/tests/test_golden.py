"""Gate (b): golden corpus, chibicc discipline (SPEC 12.6a) — snapshots update
ONLY via KIR_UPDATE_GOLDEN=1 plus human/coordinator diff review. CI treats a
mismatch as red; auto-regeneration is forbidden."""
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.compiler import compile_program  # noqa: E402

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"

PROGRAMS = {
    # The canonical regression program: the 2026-07-16 incident query.
    "pdf_underlay_count": {
        "ir_version": "1.0",
        "intent": "посчитай PDF подложки",
        "ops": [{"op": "query_count", "id": "pdf", "kind": "pdf_underlay"}],
    },
    "list_walls_level1": {
        "ir_version": "1.0",
        "intent": "стены на уровне Этаж 1 с типами",
        "ops": [{"op": "query_list", "id": "walls", "kind": "wall",
                 "where": {"level_name": "Этаж 1"},
                 "fields": ["id", "name", "type_name", "level_name"], "limit": 50}],
    },
    "mixed_program": {
        "ir_version": "1.0",
        "intent": "сводка: связи CAD, виды, инспекция по имени",
        "ops": [
            {"op": "query_count", "id": "links", "kind": "cad_link"},
            {"op": "query_count", "id": "imports", "kind": "cad_import"},
            {"op": "query_list", "id": "views", "kind": "view", "limit": 20,
             "fields": ["id", "name"]},
            {"op": "query_inspect", "id": "probe",
             "target": {"by": "name", "value": "Стена-Тест", "kind": "wall"}},
        ],
    },
    # Authoring golden: exercises stamp, stale-guards, in-txn commit-gate,
    # topology postconditions and witness readback in one snapshot-reviewed file.
    "authoring_wall_pipe_grid": {
        "ir_version": "1.0",
        "intent": "стена 6м + труба ХВС + ось А",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "Кирпич 250"}, "height_mm": 3000},
            {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
             "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
             "diameter_mm": 50},
            {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000],
             "p1_mm": [0, 9000], "name": "А"},
        ],
    },
    # Curve-IR (P4-B) golden: a curved (Arc) wall — Arc.Create instead of
    # Line.CreateBound plus the arc center/radius postcondition — in one
    # reviewed file, so a future diff isolates any drift in the arc branch. A
    # 90° fillet (r=325) matching LOT31's rounded corners; endpoints are the
    # arc's plan endpoints (325,0)->(0,325).
    "authoring_wall_arc": {
        "ir_version": "1.0",
        "intent": "дуговая стена (скруглённый угол r325)",
        "ops": [
            {"op": "create_wall", "id": "WA", "p0_mm": [325, 0],
             "p1_mm": [0, 325], "level": {"by": "name", "value": "Этаж 1"},
             "arc": {"curve_type": "Arc", "center_mm": [0.0, 0.0, 0.0],
                     "radius_mm": 325.0, "x_axis": [1.0, 0.0, 0.0],
                     "y_axis": [0.0, 1.0, 0.0], "start_angle_rad": 0.0,
                     "end_angle_rad": 1.5707963267948966}},
        ],
    },
    # Macro golden: stack expansion -> create_level DAG + per-storey walls,
    # single txn, ref-based topology checks.
    "stack_two_storeys": {
        "ir_version": "1.0",
        "intent": "две типовых этажа со стеной",
        "ops": [{"op": "stack", "id": "sec", "levels": 2, "h_mm": 3000,
                 "name_prefix": "Этаж",
                 "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                            "p1_mm": [6000, 0], "height_mm": 2800}]}],
    },
    # Modify golden: set_param (str + mm) and delete under allow_destructive.
    "modify_setparam_delete": {
        "ir_version": "1.0",
        "intent": "правка параметра и удаление",
        "allow_destructive": True,
        "ops": [
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 7777},
             "param": "Комментарии", "value": "обработано KIR"},
            {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 8888}},
        ],
    },
    # Family-A completion golden: every authoring op in one reviewed file.
    "full_house_v1": {
        "ir_version": "1.0",
        "intent": "полный дом v1",
        "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 0, "name": "КИР-1"},
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [8000, 0],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000, "sill_mm": 900},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 5000},
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_column", "id": "C1", "xy": [4000, 3000],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_room", "id": "R1", "xy": [4000, 3000],
             "level": {"by": "ref", "value": "L1"}, "name": "Зал"},
            {"op": "place_family", "id": "T1", "xyz": [2000, 2000, 0],
             "level": {"by": "ref", "value": "L1"}},
        ],
    },
    # wave/mep golden (2026-07-17): route_pipe_system (ВК stack+branch with a
    # checked slope) and route_duct_system (ОВ tee) — same reviewed-snapshot
    # discipline as create_pipe_system's own golden, one file per op so a
    # future diff isolates which op's emit drifted.
    "route_pipe_system_riser_branch": {
        "ir_version": "1.0",
        "intent": "стояк ВК с отводом и уклоном",
        "ops": [{"op": "route_pipe_system", "id": "SYS1",
                 "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "N1", "xyz_mm": [0, 0, 15000]},
                           {"id": "N2", "xyz_mm": [0, 0, 0]},
                           {"id": "N3", "xyz_mm": [3000, 0, 0]}],
                 "segments": [{"from": "N1", "to": "N2", "diameter_mm": 100},
                              {"from": "N2", "to": "N3", "diameter_mm": 50,
                               "slope_min_pct": 2.0}]}],
    },
    "route_duct_system_tee": {
        "ir_version": "1.0",
        "intent": "тройник ОВ приточной сети",
        "ops": [{"op": "route_duct_system", "id": "SYS1",
                 "level": {"by": "element_id", "value": 42}, "diameter_mm": 250,
                 "nodes": [{"id": "T", "xyz_mm": [0, 0, 3000]},
                           {"id": "A", "xyz_mm": [3000, 0, 3000]},
                           {"id": "B", "xyz_mm": [-3000, 0, 3000]},
                           {"id": "C", "xyz_mm": [0, 3000, 3000]}],
                 "segments": [{"from": "T", "to": "A"}, {"from": "T", "to": "B"},
                              {"from": "T", "to": "C"}]}],
    },
    # wave/struct golden (2026-07-17): create_beam (gold-verified overload
    # against CreateBeamsColumnsBraces.cs) + create_foundation (both
    # varieties: isolated footing + slab, one file per variety so a future
    # diff isolates which branch drifted — same one-file-per-op discipline
    # as wave/mep's route_pipe_system/route_duct_system goldens).
    "struct_beam": {
        "ir_version": "1.0",
        "intent": "балка между колоннами на уровне",
        "ops": [{"op": "create_beam", "id": "B1",
                 "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
                 "level": {"by": "element_id", "value": 42},
                 "symbol": {"by": "name", "value": "Балка 200x400"}}],
    },
    "struct_foundation_isolated": {
        "ir_version": "1.0",
        "intent": "столбчатый фундамент под колонну",
        "ops": [{"op": "create_foundation", "id": "F1", "variety": "isolated",
                 "xy": [4000, 3000],
                 "level": {"by": "element_id", "value": 42},
                 "symbol": {"by": "name", "value": "Фундамент 1500x1500"}}],
    },
    "struct_foundation_slab": {
        "ir_version": "1.0",
        "intent": "плитный фундамент с проёмом",
        "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                 "outline": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]],
                 "holes": [[[5000, 3000], [7000, 3000], [7000, 5000], [5000, 5000]]],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Монолит 200"}}],
    },
    # wave/wall-foundation (2026-08-09): ленточный фундамент. ОДИН файл на ОБЕ
    # ветви носителя намеренно: ref и element_id — это разный C# в одной
    # программе, и диф обязан показывать их рядом (ветвь ref не заводит
    # переменной стены вовсе, ветвь element_id заводит __hw_<s> и перечитывает
    # стену из документа). WF2 к тому же идёт по ДОКУМЕНТНОМУ типу по
    # умолчанию, так что в эталон попадает и GetDefaultElementTypeId.
    "struct_wall_foundation": {
        "ir_version": "1.0",
        "intent": "лента под новой стеной и под существующей",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [9000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_wall_foundation", "id": "WF1",
             "wall": {"by": "ref", "value": "W1"},
             "type": {"by": "name", "value": "Ленточный 600x300"}},
            {"op": "create_wall_foundation", "id": "WF2",
             "wall": {"by": "element_id", "value": 8145901}},
        ],
    },
    # wave/arch (2026-07-29): потолок и оба рода ограждения — по файлу на
    # ветку, чтобы будущий диф показывал, какая именно поехала (та же
    # дисциплина «один файл на ветку», что у фундамента isolated/slab).
    # ВНИМАНИЕ ПРИ ЧТЕНИИ ДИФА: у потолка ось версий — ОТКАЗ, а не развилка
    # эмиссии. Этот эталон снят на версии по умолчанию (2022+); на 2021
    # программы не существует вовсе, и ворота обязаны видеть там KIR-E003, а
    # не другой C# (gate_runner.py, список ожидаемых отказов).
    "arch_ceiling": {
        "ir_version": "1.0",
        "intent": "подвесной потолок в помещении с проёмом под шахту",
        "ops": [{"op": "create_ceiling", "id": "C1",
                 "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                 "holes": [[[2000, 1500], [3000, 1500],
                            [3000, 2500], [2000, 2500]]],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Потолок подвесной 600x600"},
                 "height_offset_mm": 2700}],
    },
    # 09.08.2026: ВТОРОЙ вход формы того же опа — эскиз CONTOUR. Отдельный
    # файл, а не расширение arch_ceiling, по той же дисциплине «один файл на
    # ветку»: диф обязан показывать, какая именно ветка поехала. Взято ровно
    # то, чего ломаная сказать не может, — дуговое ребро (Arc.Create с тремя
    # литеральными точками, вся тригонометрия посчитана в питоне) и
    # отверстие ЭСКИЗОМ (region.holes, не плоский `holes`: держать оба
    # описания проёмов сразу запрещено, KIR-P007). Ось версий та же, что у
    # arch_ceiling, и по той же причине: на 2021 у потолка нет НИКАКОГО
    # пути создания, поэтому эталон снят на версии по умолчанию, а ворота
    # обязаны видеть там KIR-E003.
    "arch_ceiling_contour": {
        "ir_version": "1.0",
        "intent": "подвесной потолок с закруглённым краем и проёмом под шахту",
        "ops": [{"op": "create_ceiling", "id": "C1",
                 "contour": {
                     "outer": {"shape": "poly",
                               "points_mm": [[0, 0], [6000, 0],
                                             [6000, 4000], [0, 4000]],
                               "arcs": [{"edge": 1, "bulge": 0.4}]},
                     "holes": [{"shape": "rect", "origin": [2000, 1500],
                                "size_mm": [1000, 1000]}]},
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Потолок подвесной 600x600"},
                 "height_offset_mm": 2700}],
    },
    # 09.08.2026: ДВЕ формы марша одного опа, ДВА файла, и первый из них —
    # ХРАПОВИК. `authoring_stairs_straight.golden.cs` снят ЭМИТТЕРОМ ДО
    # правки (`git stash` на 15d5b206, тот же снапшот, та же программа): пока
    # он совпадает, «отсутствующий параметр ничего не двигает» — не обещание,
    # а сверка байтов. Уровни адресуются ПО ИМЕНИ намеренно: лестница обязана
    # быть отдельной программой (KIR-L002), и через границу пачки имя —
    # единственная доступная ей форма адреса.
    "authoring_stairs_straight": {
        "ir_version": "1.0",
        "intent": "прямой марш между этажами",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "p0_mm": [0, 0], "p1_mm": [5000, 0],
                 "base_level": {"by": "name", "value": "Этаж 1"},
                 "top_level": {"by": "name", "value": "Этаж 2"},
                 "width_mm": 1200}],
    },
    # ВТОРАЯ форма того же опа — винтовой марш. Отдельный файл по той же
    # дисциплине «один файл на ветку»: диф обязан показывать, какая именно
    # ветка поехала. Взято ровно то, чего отрезок сказать не может: 270° по
    # дуге радиуса 1500 мм. Ось версий у винта ТА ЖЕ, что у прямого марша, и
    # это перепроверено по эталонным сборкам и живым Roslyn'ом на всех шести:
    # `StairsRun.CreateSpiralRun` присутствует и одинаков в 2021-2026.
    "authoring_stairs_spiral": {
        "ir_version": "1.0",
        "intent": "винтовая лестница вокруг шахты",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "spiral": {"center_mm": [3000.0, 3000.0],
                            "radius_mm": 1500.0,
                            "start_angle_deg": 0.0,
                            "included_angle_deg": 270.0,
                            "clockwise": False},
                 "base_level": {"by": "name", "value": "Этаж 1"},
                 "top_level": {"by": "name", "value": "Этаж 2"},
                 "width_mm": 1200}],
    },
    "arch_railing_path": {
        "ir_version": "1.0",
        "intent": "ограждение по краю балкона",
        "ops": [{"op": "create_railing", "id": "R1", "variety": "path",
                 "path": [[0, 0], [4000, 0], [4000, 2500]],
                 "level": {"by": "element_id", "value": 42},
                 "type": {"by": "name", "value": "Ограждение 900"}}],
    },
    "arch_railing_hosted": {
        "ir_version": "1.0",
        "intent": "ограждение по существующей лестнице",
        "ops": [{"op": "create_railing", "id": "R1", "variety": "hosted",
                 "host": {"by": "element_id", "value": 8888},
                 "position": "treads",
                 "type": {"by": "name", "value": "Ограждение 900"}}],
    },
    # wave/room (2026-08-03): разделитель помещений. Ломаная буквой П — три
    # звена, — чтобы диф показывал СРАЗУ и посегментную сборку CurveArray, и
    # свидетеля концов по каждому звену. Оси версий у операции нет (6/6), так
    # что эталон снят на версии по умолчанию и обязан совпадать на всех.
    "room_separator": {
        "ir_version": "1.0",
        "intent": "отделить кухню-нишу от гостиной без стены",
        "ops": [{"op": "create_room_separator", "id": "RS1",
                 "path": [[0, 0], [3200, 0], [3200, 2400], [0, 2400]],
                 "level": {"by": "name", "value": "Этаж 1"}}],
    },
    # wave/space (2026-08-10): пространство ОВК. Программа держит СТЕНУ и ДВА
    # пространства намеренно: стена вводит v0-правило `doc.Regenerate()`
    # перед пространством (NewSpace разрешает объемлющую область В МОМЕНТ
    # СОЗДАНИЯ), а два опа показывают в дифе суффиксацию временных
    # свидетеля — единственное место, где имя без суффикса дало бы CS0128.
    # Оси версий у операции нет (три перегрузки 6/6, эмиссия побайтно
    # одинакова на 2021-2026), поэтому эталон снят на версии по умолчанию.
    # wave/placement (2026-08-11): оба новых рода размещения рядом,
    # чтобы будущий дифф сразу показал, какая из двух веток сдвинулась.
    # Оси версий у обеих нет (перегрузки 6/6, эмиссия побайтно одинакова
    # на 2021-2026), поэтому эталон снят на версии по умолчанию.
    # 11.08.2026: ПОСЛЕДНЕЕ «НЕ ДОСТИГНУТО» ОРАКУЛА L6.
    #
    # `create_stairs_landing` не строила НИ ОДНА программа обоих корпусов, и
    # трёхсостоянийный оракул честно читал это как `not-reached` — то есть
    # «свидетельства нет», а не «здоров». Проба, которая объявила оп
    # труднодостижимым, пользовалась ВЫДУМАННЫМИ именами полей (`pts`,
    # `elev_mm`) и получала KIR-P003 на них же; имена, взятые из реестра
    # (`stairs`, `contour`, `elevation_mm`), компилируются сразу. Урок тот
    # же, что весь марафон: спрашивать реестр, а не память.
    #
    # ОП СОЛЬНЫЙ (`spec.SOLO_OPS`), поэтому программа из одного опа — это не
    # упрощение фикстуры, а единственная допустимая форма.
    #
    # КОНТУР ОДНОПЕТЛЕВОЙ, И ЭТО ЗАМЕР, А НЕ ВЫБОР: `contour` с `holes`
    # отвергается типизированным KIR-E008 —
    # `StairsLanding.CreateSketchedLanding` принимает ОДНУ петлю. Эталон
    # держит ту форму, которую API исполняет.
    # 11.08.2026: ПРОГРАММА, КОТОРАЯ ЛОВИТ ДЫРУ ПРАВИЛА РЕГЕНЕРАЦИИ.
    #
    # Ни один эталон корпуса её не строил, и потому правка правила прошла
    # БЕЗ сдвига байтов у всех 52 эталонов — то есть корпус дыру не
    # покрывал вовсе. Эта программа — единственное место, где разница
    # видна: комната ставится в контур, образованный РАЗДЕЛИТЕЛЕМ, а не
    # стеной, и до правки регенерации между ними не было (замер по
    # эмиссии: разделитель на 2645, комната на 5534, регенерации нет).
    #
    # Дифф этого эталона обязан показывать `doc.Regenerate()` МЕЖДУ двумя
    # опами. Если он однажды исчезнет — правило снова сломано.
    "room_separator_then_room": {
        "ir_version": "1.0",
        "intent": "комната в контуре из разделителей, без единой стены",
        "ops": [
            {"op": "create_room_separator", "id": "RS1",
             "path": [[0, 0], [4000, 0], [4000, 3000], [0, 3000], [0, 0]],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_room", "id": "R1", "xy": [2000, 1500],
             "level": {"by": "name", "value": "Этаж 1"},
             "name": "Кухня-ниша"},
        ],
    },
    "authoring_stairs_landing": {
        "ir_version": "1.0",
        "intent": "промежуточная площадка на существующей лестнице",
        "ops": [{"op": "create_stairs_landing", "id": "LD1",
                 "stairs": {"by": "element_id", "value": 8888},
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[0, 0], [2400, 0],
                                   [2400, 1600], [0, 1600]]}},
                 "elevation_mm": 1800}],
    },
    "place_family_placement_kinds": {
        "ir_version": "1.0",
        "intent": "прибор на рабочей плоскости и стойка между уровнями",
        "ops": [
            {"op": "create_wall", "id": "PW", "p0_mm": [0, 0],
             "p1_mm": [8000, 0],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_level", "id": "PL", "elev_mm": 6000,
             "name": "КИР-Р"},
            {"op": "place_family", "id": "PP", "xyz": [4000, 0, 1200],
             "level": {"by": "name", "value": "Этаж 1"},
             "host": {"by": "ref", "value": "PW"},
             "ref_dir": [1, 0, 0]},
            {"op": "place_family", "id": "PT", "xyz": [2000, 2000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "top_level": {"by": "ref", "value": "PL"},
             "base_offset_mm": 100, "top_offset_mm": -250},
        ],
    },
    "space_mep": {
        "ir_version": "1.0",
        "intent": "два пространства ОВК в венткамере",
        "ops": [
            {"op": "create_wall", "id": "SW1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_space", "id": "SPA", "xy": [2000, 2000],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_space", "id": "SPB", "xy": [6000, 2000],
             "level": {"by": "name", "value": "Этаж 1"}},
        ],
    },
    # wave hosted-flips-wall-vertical (audit F5): door with the full enforced
    # swing/mirror state + window with a facing flip — the MirrorElements
    # plane (normal along the host wall's direction), CanFlip* guards and the
    # three per-flag state witnesses in one reviewed file.
    # place_family по КРИВОЙ (27.07). Повод замерен на тренировочной модели
    # ЭОМ (SKLNK R2026): 79 экземпляров — весь остаток дыры этой модели —
    # имеют FamilyPlacementType.CurveBased и живой LocationCurve, а
    # LocationPoint у них не существует. Оп общий: тот же CurveBased есть в
    # КР (связи), ОВ (опоры воздуховодов), АР (карнизы, поручни).
    #
    # Программа держит ОБА варианта рядом намеренно: будущий дифф сразу
    # покажет, какая из двух ветвей сдвинулась, а точечная заморожена
    # корпусом паритета и сдвигаться не должна вовсе.
    "place_family_point_and_curve": {
        "ir_version": "1.0",
        "intent": "семейство в точку и семейство по кривой на хосте",
        "ops": [
            {"op": "place_family", "id": "P1", "xyz": [1000, 2000, 0],
             "level": {"by": "name", "value": "Этаж 1"}},
            # Хост у кривого варианта обязателен, и это ЗАМЕР: перегрузка с
            # уровнем проецирует кривую на плоскость уровня и схлопывает
            # вертикальный отрезок в точку. Порядок «сначала хост, потом то,
            # что на нём» — та же топология, что стена → дверь.
            {"op": "create_cable_tray", "id": "T1",
             "p0_mm": [155643, -5766, 565], "p1_mm": [155643, -5766, 4910],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "place_family", "id": "C1",
             "p0_mm": [155643, -5766, 565], "p1_mm": [155643, -5766, 4910],
             "host": {"by": "ref", "value": "T1"}},
        ],
    },
    "hosted_door_flips": {
        "ir_version": "1.0",
        "intent": "дверь с зеркалом и створкой",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": {"by": "name", "value": "Этаж 1"},
             "height_mm": 3000},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000,
             "mirrored": True, "hand_flipped": True, "facing_flipped": False},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 5000,
             "sill_mm": 900, "facing_flipped": True},
        ],
    },
    # wave hosted-flips-wall-vertical (audit F6): parapet wall with a base
    # offset (WALL_BASE_OFFSET.Set + ±1mm witness) and a wall attached to a
    # top level (WALL_HEIGHT_TYPE + WALL_TOP_OFFSET=0 + topology witness) —
    # one file per attribute so a future diff isolates which branch drifted.
    "wall_base_offset": {
        "ir_version": "1.0",
        "intent": "парапетная стена с офсетом основания",
        "ops": [{"op": "create_wall", "id": "WB", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 1200, "base_offset_mm": 900}],
    },
    # Wave A2: create_group WITH member-POSTs (the wave's one deliberate
    # emission change, pinned here) — each member's braced post block is
    # nested inside the group post (own C# scope per member).
    "native_group": {
        "ir_version": "1.0",
        "intent": "типовой этаж как нативная группа",
        "ops": [{"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
                 "members": [
                     {"op": "create_wall", "id": "W1",
                      "p0_mm": [30000, 23000], "p1_mm": [36000, 23000],
                      "level": {"__grounded__": {"id": 42, "name": None,
                                                 "via": "element_id"}},
                      "height_mm": 3000.0,
                      "type": {"__grounded__": {"id": None, "name": None,
                                                "via": "doc_default",
                                                "in_emit": "__doc_default__"}}},
                     {"op": "create_wall", "id": "W2",
                      "p0_mm": [36000, 23000], "p1_mm": [36000, 27000],
                      "level": {"__grounded__": {"id": 42, "name": None,
                                                 "via": "element_id"}},
                      "height_mm": 3000.0,
                      "type": {"__grounded__": {"id": None, "name": None,
                                                "via": "doc_default",
                                                "in_emit": "__doc_default__"}}},
                 ],
                 "placements": [[0, 0, 6600], [0, 0, 13200]]}],
    },
    "wall_top_attached": {
        "ir_version": "1.0",
        "intent": "стена, приаттаченная к верхнему уровню",
        "ops": [{"op": "create_wall", "id": "WT", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000,
                 "top_level": {"by": "name", "value": "Этаж 2"}}],
    },
    # wave/opening (2026-08-03): проём КАК ОТДЕЛЬНЫЙ ЭЛЕМЕНТ — по файлу на
    # ветку, та же дисциплина, что у фундамента isolated/slab и ограждения
    # path/hosted. Оси версий у операции НЕТ (все четыре перегрузки
    # NewOpening живут 6/6), поэтому ожидаемых отказов в gate_runner для них
    # заводить не нужно — в отличие от потолка.
    #
    # Оба значения `cut` стоят отдельными эталонами намеренно: у
    # вертикального реза свидетель сверяет РАВЕНСТВО габаритов, у
    # перпендикулярного — ВКЛЮЧЕНИЕ (на скате план проёма законно шире
    # контура), то есть это две разные эмиссии, и будущий диф обязан
    # показывать, какая именно поехала.
    "opening_wall_rect": {
        "ir_version": "1.0",
        "intent": "прямоугольный проём в существующей стене",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "wall_rect",
                 "host": {"by": "element_id", "value": 8145901},
                 "p0_mm": [1000.0, 0.0, 900.0],
                 "p1_mm": [2500.0, 0.0, 2400.0]}],
    },
    # ── wave/site (2026-08-09): площадка и рельеф ───────────────────────────
    # ПО ФАЙЛУ НА ВЕТКУ, по той же дисциплине, что у волны архитектуры: диф
    # обязан показывать, какая именно ветка поехала.
    "site_topography_surface": {
        "ir_version": "1.0",
        "intent": "рельеф участка по съёмочным точкам",
        "ops": [{"op": "create_topography", "id": "T1", "variety": "surface",
                 "points_mm": [[0, 0, 0], [24000, 0, 800],
                               [24000, 18000, 1500], [0, 18000, 400],
                               [12000, 9000, 1100]]}],
    },
    # Эталон снят на версии по умолчанию (2026), потому что класса Toposolid
    # до 2024 не существует: на 2021-2023 это типизированный отказ KIR-E003,
    # то есть эмиссии там нет вовсе, а не другая эмиссия.
    "site_topography_toposolid": {
        "ir_version": "1.0",
        "intent": "толща рельефа с привязкой к уровню",
        "ops": [{"op": "create_topography", "id": "T1", "variety": "toposolid",
                 "points_mm": [[0, 0, 0], [24000, 0, 800],
                               [24000, 18000, 1500], [0, 18000, 400],
                               [12000, 9000, 1100]],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Толща рельефа 300"}}],
    },
    # Тип НЕ задан намеренно: это ветка умолчания документа
    # (ElementTypeGroup.BuildingPadType, 6/6 — замерено вопреки нашей же базе
    # API), и эталон обязан её показывать.
    "site_building_pad": {
        "ir_version": "1.0",
        "intent": "площадка под здание с проёмом под приямок",
        "ops": [{"op": "create_building_pad", "id": "P1",
                 "contour": {"outer": {"shape": "rect", "origin": [2000, 2000],
                                       "size_mm": [12000, 9000]},
                             "holes": [{"shape": "rect",
                                        "origin": [5000, 4000],
                                        "size_mm": [1500, 1500]}]},
                 "level": {"by": "name", "value": "Этаж 1"}}],
    },
    # Подобласть с НАЗВАННЫМ хозяином и дуговым ребром: габарит сверяется по
    # lowered-edges (кардинальные экстремумы дуги), и прямая ломаная эту
    # ветку не открывает.
    "site_subregion_hosted": {
        "ir_version": "1.0",
        "intent": "подобласть площадки под газон, с закруглённым краем",
        "ops": [{"op": "create_site_subregion", "id": "R1",
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[1000, 1000], [9000, 1000],
                                   [9000, 7000], [1000, 7000]],
                     "arcs": [{"edge": 1, "bulge": 0.35}]}},
                 "host": {"by": "element_id", "value": 7777}}],
    },
    # wave/sweep (2026-08-09). ПО ФАЙЛУ НА ВЕТКУ, и веток здесь ровно четыре,
    # потому что расходится эмиссия, а не оформление: у стенного профиля —
    # ориентация (единственный аргумент, влияющий на конструктор
    # `WallSweepInfo`) и форма селектора носителя (`element_id` против `ref`,
    # то есть `doc.GetElement` против переменной соседнего опа); у краевого —
    # сторона (`GetTopFaces` против `GetBottomFaces`, разные вызовы) и та же
    # развилка носителя.
    "sweep_wall_horizontal": {
        "ir_version": "1.0",
        "intent": "карниз по существующей стене",
        "ops": [{"op": "create_wall_sweep", "id": "S1",
                 "host": {"by": "element_id", "value": 7777},
                 "orientation": "horizontal",
                 "type": {"by": "name", "value": "Карниз 200x100"}}],
    },
    # Носитель — стена ЭТОЙ ЖЕ программы, плюс вертикальная ориентация: обе
    # ветки сразу, потому что они независимы и вторая пара эталонов ничего бы
    # не добавила.
    "sweep_wall_vertical_ref": {
        "ir_version": "1.0",
        "intent": "руст по только что построенной стене",
        "ops": [
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [8000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_wall_sweep", "id": "S1",
             "host": {"by": "ref", "value": "W1"},
             "orientation": "vertical",
             "type": {"by": "name", "value": "Карниз 200x100"}},
        ],
    },
    # Тип НЕ задан намеренно: ветка «единственный в пуле» у `ground`. Ветки
    # умолчания ДОКУМЕНТА здесь нет и быть не должно —
    # `ElementTypeGroup.EdgeSlabType` существует 6/6, но не используется по
    # тому же доводу, что у потолка и площадки (см. sweep_emit).
    "sweep_slab_edge_top": {
        "ir_version": "1.0",
        "intent": "капельник по верхнему краю плиты",
        "ops": [{"op": "create_slab_edge", "id": "E1",
                 "host": {"by": "element_id", "value": 7777},
                 "side": "top"}],
    },
    "sweep_slab_edge_bottom_ref": {
        "ir_version": "1.0",
        "intent": "капельник по нижнему краю только что построенного перекрытия",
        "ops": [
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "Монолит 200"}},
            {"op": "create_slab_edge", "id": "E1",
             "host": {"by": "ref", "value": "F1"},
             "side": "bottom",
             "type": {"by": "name", "value": "Капельник 100x50"}},
        ],
    },
    "opening_host_face_vertical": {
        "ir_version": "1.0",
        "intent": "проём в существующем перекрытии, вертикальный рез",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "host_face",
                 "host": {"by": "element_id", "value": 8145901},
                 "outline": [[1000, 1000], [3000, 1000],
                             [3000, 3000], [1000, 3000]],
                 "cut": "vertical"}],
    },
    "opening_host_face_perpendicular": {
        "ir_version": "1.0",
        "intent": "проём в скатной кровле, рез перпендикулярно грани",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "host_face",
                 "host": {"by": "element_id", "value": 8145901},
                 "outline": [[5000, 1000], [7000, 1000],
                             [7000, 3000], [5000, 3000]],
                 "cut": "perpendicular"}],
    },
    # 09.08.2026: ВТОРОЙ вход формы того же рода — эскиз CONTOUR. Снова ДВА
    # файла на два значения `cut`, по той же дисциплине, что у прямой ветки
    # выше: у вертикального реза свидетель сверяет ПОЛОСУ (вершины снизу,
    # габарит с дугами сверху), у перпендикулярного — только нижнюю границу,
    # и это две разные эмиссии. Оси версий у эскиза НЕТ, и это переснято по
    # эталонным сборкам: NewOpening(Element, CurveArray, bool), Arc.Create,
    # Line.CreateBound, CurveArray.Append, Curve.Evaluate, Curve.GetEndPoint,
    # Curve.IsBound — все 6/6, поэтому ожидаемых отказов в gate_runner тут
    # заводить не нужно (в отличие от потолка).
    #
    # Взято ровно то, чего ломаная сказать не может: дуговое ребро (Arc.Create
    # с ТРЕМЯ литеральными точками — вся тригонометрия посчитана в питоне) и
    # повёрнутый прямоугольник. В дуговом файле дополнительно видна ВЫБОРКА
    # по границе (`Curve.Evaluate`), которой у прямых профилей нет вовсе.
    "opening_contour_vertical": {
        "ir_version": "1.0",
        "intent": "проём с закруглённой стороной в перекрытии, "
                  "вертикальный рез",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "host_face",
                 "host": {"by": "element_id", "value": 8145901},
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[1000, 1000], [3000, 1000],
                                   [3000, 3000], [1000, 3000]],
                     "arcs": [{"edge": 1, "bulge": 0.4}]}},
                 "cut": "vertical"}],
    },
    "opening_contour_perpendicular": {
        "ir_version": "1.0",
        "intent": "повёрнутый прямоугольный проём в скатной кровле, "
                  "рез перпендикулярно грани",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "host_face",
                 "host": {"by": "element_id", "value": 8145901},
                 "contour": {"outer": {"shape": "rect",
                                       "origin": [5000, 1000],
                                       "size_mm": [2000, 2000],
                                       "rotation_deg": 30.0}},
                 "cut": "perpendicular"}],
    },
    # wave/mep-electrical (2026-08-09). ДВА эталона, а не один: у короба с
    # заготовками свидетель читает ось `LocationCurve` (плюс бит заготовки), у
    # гибких — массив `Points` целиком. Это две разные эмиссии, и будущий диф
    # обязан показывать, какая именно поехала — тот же довод, по которому у
    # проёма два файла на два значения `cut`.
    "mep_conduit_and_placeholders": {
        "ir_version": "1.0",
        "intent": "короб ЭОМ и две заготовки трассы",
        "ops": [
            {"op": "create_conduit", "id": "CD1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000],
             "level": {"by": "name", "value": "Этаж 1"},
             "conduit_type": {"by": "name",
                              "value": "Короб жёсткий металлический"}},
            {"op": "create_pipe_placeholder", "id": "PP1",
             "p0_mm": [0, 1000, 2800], "p1_mm": [6000, 1000, 2800],
             "level": {"by": "element_id", "value": 42},
             "system_type": {"by": "name", "value": "ХВС"},
             "pipe_type": {"by": "name", "value": "Стандарт"}},
            {"op": "create_duct_placeholder", "id": "DP1",
             "p0_mm": [0, 2000, 3200], "p1_mm": [6000, 2000, 3200],
             "level": {"by": "element_id", "value": 42}},
        ],
    },
    "mep_flex_runs": {
        "ir_version": "1.0",
        "intent": "гибкая подводка воздуховода и гибкая труба",
        # Трёхточечная и двухточечная рядом: у первой свидетель обходит
        # середину, у второй — только концы, и разница видна в файле.
        "ops": [
            {"op": "create_flex_duct", "id": "FD1",
             "path": [[0, 3000, 3000], [1500, 3000, 2800],
                      [3000, 3200, 2600]],
             "level": {"by": "element_id", "value": 42},
             "flex_duct_type": {"by": "name",
                                "value": "Гибкий воздуховод круглый"}},
            {"op": "create_flex_pipe", "id": "FP1",
             "path": [[0, 4000, 3000], [1500, 4000, 2700]],
             "level": {"by": "name", "value": "Этаж 1"}},
        ],
    },
    # wave/analysis (2026-08-09). ДВА файла, а не один, и версия у них
    # РАЗНАЯ — это и есть главный факт волны, зафиксированный в эталоне:
    # свободная нагрузка живёт только на 2021-2023, а путь эвакуации — на
    # всех шести. Один файл на обе эмиссии скрыл бы ровно эту границу.
    #
    # Внутри программы нагрузок намеренно стоят обе формы селектора случая
    # загружения (по имени и по id), нагрузка с явным типом рядом с
    # нагрузкой без него и наклонная линейная рядом с горизонтальной: у
    # наклонной рабочая плоскость ВЕРТИКАЛЬНАЯ, и её нормаль считается в
    # питоне — будущий диф обязан показывать, какая из двух веток поехала.
    "analysis_loads": {
        "__ver__": "2023",
        "ir_version": "1.0",
        "intent": "точечная, две линейных и площадная нагрузка",
        "ops": [
            {"op": "create_point_load", "id": "PL1", "xyz": [1000, 2000, 3000],
             "fz_n": -10000.0, "mx_nm": 250.0,
             "load_case": {"by": "name", "value": "ДЛ1 Собственный вес"}},
            {"op": "create_line_load", "id": "LL1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "fz_n_per_m": -5000.0,
             "fx_n_per_m": 120.0,
             "load_case": {"by": "element_id", "value": 1500},
             "load_type": {"by": "name", "value": "Линейная нагрузка 1"}},
            {"op": "create_line_load", "id": "LL2", "p0_mm": [0, 500, 3000],
             "p1_mm": [6000, 2500, 4200], "fz_n_per_m": -2500.0,
             "load_case": {"by": "element_id", "value": 1501}},
            {"op": "create_area_load", "id": "AL1",
             "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "elev_mm": 3000, "fz_n_per_m2": -3000.0,
             "load_case": {"by": "name", "value": "СН1 Снег"}},
        ],
    },
    "analysis_path_of_travel": {
        "ir_version": "1.0",
        "intent": "путь эвакуации от точки до выхода",
        "ops": [
            {"op": "create_path_of_travel", "id": "PT1",
             "in_view": {"by": "element_id", "value": 900},
             "p0_mm": [0, 0], "p1_mm": [12000, 5000]},
        ],
    },
    # wave/datums (09.08.2026). ТРИ отдельные золотые программы, а не одна:
    # каждая закрывает ветку, которую соседние не освещают, и слив их в один
    # файл спрятал бы ровно то, ради чего golden существует, — байтовую
    # разницу веток.
    "datums_multi_segment_grid": {
        "ir_version": "1.0",
        "intent": "цепь осей ломаной",
        "ops": [
            {"op": "create_multi_segment_grid", "id": "MG1",
             "path": [[0, 0], [8000, 0], [8000, 6000], [14000, 6000]],
             "level": {"by": "name", "value": "Этаж 1"}},
        ],
    },
    # Две кровли рядом: у первой тип берётся у ДОКУМЕНТА (поле опущено), у
    # второй пришпилен id, и ход выдавливания уходит в МИНУС с одной стороны —
    # знак единственное, что решается в рантайме по нормали Revit.
    "datums_extrusion_roof": {
        "ir_version": "1.0",
        "intent": "выдавленные кровли: щипец и плоский навес",
        "ops": [
            {"op": "create_extrusion_roof", "id": "XR1",
             "p0_mm": [0, 0], "p1_mm": [0, 8000],
             "profile_mm": [[0, 3000], [4000, 5000], [8000, 3000]],
             "level": {"by": "name", "value": "Этаж 1"},
             "start_mm": 0, "end_mm": 12000},
            {"op": "create_extrusion_roof", "id": "XR2",
             "p0_mm": [1000, 2000], "p1_mm": [9000, 2000],
             "profile_mm": [[0, 4000], [8000, 4000]],
             "level": {"by": "element_id", "value": 43},
             "start_mm": -3000, "end_mm": 9000},
        ],
    },
    "datums_multistory_stairs": {
        "ir_version": "1.0",
        "intent": "марш, размноженный на два этажа",
        # Уровни названы РАЗНЫМИ формами селектора намеренно: список обязан
        # резолвиться поэлементно тем же правилом, что одиночный.
        "ops": [
            {"op": "create_multistory_stairs", "id": "MS1",
             "stairs": {"by": "element_id", "value": 8145901},
             "levels": [{"by": "name", "value": "Этаж 1"},
                        {"by": "element_id", "value": 43}]},
        ],
    },
    # wave/solid: параметрическое тело. ОБА опа в ОДНОМ файле и с РАЗНЫМИ
    # ветками намеренно — так рецензент видит рядом то, что иначе пришлось бы
    # сличать по двум снимкам:
    #   * выдавливание НЕСЁТ проём, дугу и отметку основания, то есть все три
    #     необязательных ветки эмиссии сразу (преобразование контура печатается
    #     только здесь — у голого тела его нет вовсе);
    #   * вращение идёт НЕПОЛНЫМ оборотом, поэтому у него есть торцы, и рядом
    #     видно, чем свидетель торцов отличается от габаритного.
    # Ни один селектор не грунтуется (у DirectShape нет типа), поэтому файл
    # компилируется БЕЗ снапшота — единственный авторский голден с таким
    # свойством, и это факт о DirectShape, а не о фикстуре.
    "solid_extrusion_and_revolve": {
        "ir_version": "1.0",
        "intent": "параметрическое тело: выдавливание с проёмом и вращение",
        "ops": [
            {"op": "create_solid_extrusion", "id": "SE1",
             "profile": {
                 "outer": {"shape": "poly",
                           "points_mm": [[0, 0], [6000, 0], [6000, 4000],
                                         [0, 4000]],
                           "arcs": [{"edge": 1, "bulge": 0.4}]},
                 "holes": [{"shape": "rect", "origin": [1000, 1000],
                            "size_mm": [1200, 1200]}]},
             "height_mm": 1800, "base_z_mm": 3300,
             "category": "mass", "name": "плита с проёмом"},
            {"op": "create_solid_revolve", "id": "SR1",
             "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                   "size_mm": [800, 2400]}},
             "axis_xy_mm": [12000, 4000], "sweep_deg": 270,
             "category": "generic_model", "name": "сектор кольца"},
        ],
    },
    # ── wave/detail (2026-08-09): заливка на виде ───────────────────────────
    # ДВА ФАЙЛА НА ДВЕ ВЕТКИ ТИПА, по той же дисциплине, что у площадки и
    # проёма: диф обязан показывать, какая именно ветка поехала.
    #
    # Первый — тип НАЗВАН, контур с дыркой и дугой. Дуга здесь не украшение:
    # она открывает единственную ветку, где свидетель обязан сверять СЕРЕДИНУ
    # ребра (по концам дуга и её хорда неотличимы), а дырка — ветку, где
    # петель больше одной.
    "detail_filled_region_named_type": {
        "ir_version": "1.0",
        "intent": "заливка бетона на разрезе, с проёмом и скруглённым краем",
        "ops": [{"op": "create_filled_region", "id": "F1",
                 "in_view": {"by": "element_id", "value": 900},
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[0, 0], [4000, 0], [4000, 2500], [0, 2500]],
                     "arcs": [{"edge": 1, "bulge": 0.4}]},
                     "holes": [{"shape": "rect", "origin": [1000, 800],
                                "size_mm": [800, 600]}]},
                 "type": {"by": "name", "value": "Бетон"}}],
    },
    # Второй — тип НЕ задан: ветка документного умолчания
    # (ElementTypeGroup.FilledRegionType, 6/6 — замерено компиляцией), и
    # эталон обязан её показывать отдельно от именованной.
    "detail_filled_region_doc_default": {
        "ir_version": "1.0",
        "intent": "прямоугольная заливка типом документа по умолчанию",
        "ops": [{"op": "create_filled_region", "id": "F1",
                 "in_view": {"by": "element_id", "value": 900},
                 "contour": {"outer": {"shape": "rect", "origin": [500, 500],
                                       "size_mm": [3000, 1200]}}}],
    },
}

from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


class Golden(unittest.TestCase):
    def test_golden(self):
        update = os.environ.get("KIR_UPDATE_GOLDEN") == "1"
        for name, prog in PROGRAMS.items():
            with self.subTest(name=name):
                # Версия эмиссии — свойство ПРОГРАММЫ, а не всего корпуса
                # (09.08). До волны нагрузок все эталоны собирались на 2026 по
                # умолчанию, потому что каждая прежняя операция там есть.
                # Свободная нагрузка на 2026 честно ОТКАЗЫВАЕТ, и эталон её
                # эмиссии может существовать только на версии, где эмиссия
                # есть.
                ver = prog.get("__ver__", "2026")
                prog = {k: v for k, v in prog.items() if k != "__ver__"}
                snap = GROUND_SNAPSHOT if name in (
                    "authoring_wall_pipe_grid", "authoring_wall_arc",
                    "full_house_v1",
                    "route_pipe_system_riser_branch", "route_duct_system_tee",
                    "struct_beam", "struct_foundation_isolated", "struct_foundation_slab",
                    "struct_wall_foundation",
                    "hosted_door_flips", "wall_base_offset", "wall_top_attached",
                    "native_group", "place_family_point_and_curve",
                    "arch_ceiling", "arch_ceiling_contour",
                    "authoring_stairs_straight", "authoring_stairs_spiral",
                    "arch_railing_path", "arch_railing_hosted",
                    "room_separator",
                    "space_mep",
                    "place_family_placement_kinds",
                    "authoring_stairs_landing",
                    "room_separator_then_room",
                    "mep_conduit_and_placeholders", "mep_flex_runs",
                    "analysis_loads", "analysis_path_of_travel",
                    # wave/site: уровень и типы рельефа/площадки грунтуются по
                    # общей фикстуре — своей копии снапшота у волны нет
                    # (урок 16.07: приватная копия делает прогон
                    # невоспроизводимым из HEAD).
                    "site_topography_surface", "site_topography_toposolid",
                    "site_building_pad", "site_subregion_hosted",
                    # wave/sweep: те же соображения — носитель, уровень и типы
                    # профилей грунтуются по ОБЩЕЙ фикстуре.
                    "sweep_wall_horizontal", "sweep_wall_vertical_ref",
                    "sweep_slab_edge_top", "sweep_slab_edge_bottom_ref",
                    "datums_multi_segment_grid", "datums_extrusion_roof",
                    "datums_multistory_stairs",
                    # wave/detail: тип заливки грунтуется общей фикстурой;
                    # ветка умолчания документа снапшот тоже читает (пустой
                    # `type` проходит через ground как doc_default).
                    "detail_filled_region_named_type",
                    "detail_filled_region_doc_default",
                ) else None
                out = compile_program(prog, revit_version=ver, snapshot=snap)
                self.assertTrue(out.ok, name)
                path = GOLDEN_DIR / f"{name}.golden.cs"
                if update:
                    path.write_text(out.csharp, encoding="utf-8")
                    continue
                self.assertTrue(path.exists(),
                                f"{path} missing — run once with KIR_UPDATE_GOLDEN=1 and review")
                self.assertEqual(path.read_text(encoding="utf-8"), out.csharp,
                                 f"{name}: emit drifted from reviewed golden "
                                 f"(intentional? update via KIR_UPDATE_GOLDEN=1 + review)")


if __name__ == "__main__":
    unittest.main()
