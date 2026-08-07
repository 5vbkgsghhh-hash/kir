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
}

from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


class Golden(unittest.TestCase):
    def test_golden(self):
        update = os.environ.get("KIR_UPDATE_GOLDEN") == "1"
        for name, prog in PROGRAMS.items():
            with self.subTest(name=name):
                snap = GROUND_SNAPSHOT if name in (
                    "authoring_wall_pipe_grid", "authoring_wall_arc",
                    "full_house_v1",
                    "route_pipe_system_riser_branch", "route_duct_system_tee",
                    "struct_beam", "struct_foundation_isolated", "struct_foundation_slab",
                    "hosted_door_flips", "wall_base_offset", "wall_top_attached",
                    "native_group", "place_family_point_and_curve",
                    "arch_ceiling", "arch_railing_path", "arch_railing_hosted",
                    "room_separator",
                ) else None
                out = compile_program(prog, snapshot=snap)
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
