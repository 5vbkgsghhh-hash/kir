"""Emitter scope contract (wave/decompile-p4b, per-op isolation guard).

THE CONTRACT: everything an emitter's post (p) and readback (r) blocks
reference is declared in its decl (d) block — or is a program-wide global
(__t/__post/__results/__Refuse/__OpRefuse) or a local declared inside the
p/r block itself. NOTHING p/r reads may be declared only inside create (c):
per_op isolation wraps every create block in its own ``try``/SubTransaction
scope, so a create-scoped declaration becomes CS0103 in the post block —
exactly the ``__hl_<s>`` hosted-op blocker this wave's gate caught (and the
same class the tag emitter had already hit once before: "a witness var never
hoisted to decl", _emit_tag docstring).

Static (pure string) check — no compile gate needed — so it protects every
FUTURE emitter on every version fork at unit-test speed. Fixture programs
deliberately exercise the optional branches that declare extra vars the post
re-reads (dim_type / tag_type+leader / text width_mm+leader_to / create_type
depth+material / floor holes / place_family flips): a branch the fixture
misses is a branch this contract cannot see.
"""
import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.compiler import _parse_and_check  # noqa: E402
from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir import spec  # noqa: E402
from kukai.ir.authoring import _EMITTERS  # noqa: E402
from kukai.ir.emit_model import post_to_string  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
LVL = {"by": "name", "value": "Этаж 1"}
LVL_ID = {"by": "element_id", "value": 42}
IN_VIEW = {"by": "element_id", "value": 900}

# One fixture program per family corner; "__min_ver__" gates programs whose
# ops are typed version refusals below it (tag_type<2022, floor holes<2022).
PROGRAMS = {
    "full_house": {
        "ir_version": "1.0", "intent": "дом", "ops": [
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
             "level": {"by": "ref", "value": "L1"}, "rotation_deg": 15},
            {"op": "create_room", "id": "R1", "xy": [4000, 3000],
             "level": {"by": "ref", "value": "L1"}, "name": "Зал"},
            {"op": "place_family", "id": "T1", "xyz": [2000, 2000, 0],
             "level": {"by": "ref", "value": "L1"}, "rotation_deg": 90,
             "mirrored": False, "hand_flipped": True, "facing_flipped": True},
        ]},
    # 28.07: place_family НА ХОСТЕ — обе перегрузки. Хост объявлялся `var`
    # внутри create, а свидетель хоста читает его из post; в атомарной обёртке
    # шов невидим, в per_op — это CS0103. Живой A5 на ЭОМ упал ровно так и не
    # создал ни одного элемента, потому что ни одна фикстура этой ветки не
    # покрывала. Тот самый урок из докстринга этого файла, повторённый.
    "place_family_hosted": {
        "ir_version": "1.0", "intent": "оборудование на хосте", "ops": [
            {"op": "create_level", "id": "LH", "elev_mm": 0, "name": "КИР-Х"},
            {"op": "create_wall", "id": "WH", "p0_mm": [0, 0], "p1_mm": [8000, 0],
             "level": {"by": "ref", "value": "LH"}},
            {"op": "place_family", "id": "PH", "xyz": [4000, 0, 1200],
             "level": {"by": "ref", "value": "LH"},
             "host": {"by": "ref", "value": "WH"}},
            {"op": "place_family", "id": "PC",
             "p0_mm": [6000, 0, 0], "p1_mm": [6000, 0, 3000],
             "host": {"by": "ref", "value": "WH"}},
        ]},
    # audit F5/F6 (wave hosted-flips-wall-vertical): the flip branches of
    # create_door/create_window and the vertical-attribute branches of
    # create_wall declare extra vars the post re-reads — a branch the fixture
    # misses is a branch this contract cannot see (this file's own lesson).
    "hosted_flips_wall_vertical": {
        "ir_version": "1.0", "intent": "створки и вертикаль", "ops": [
            {"op": "create_level", "id": "LT", "elev_mm": 3000, "name": "КИР-Т"},
            {"op": "create_wall", "id": "WV", "p0_mm": [0, 0], "p1_mm": [8000, 0],
             "level": LVL, "height_mm": 3000, "base_offset_mm": -300,
             "top_level": {"by": "ref", "value": "LT"}},
            {"op": "create_door", "id": "DF",
             "host": {"by": "ref", "value": "WV"}, "offset_mm": 2000,
             "mirrored": True, "hand_flipped": True, "facing_flipped": False},
            {"op": "create_window", "id": "WF",
             "host": {"by": "ref", "value": "WV"}, "offset_mm": 5000,
             "sill_mm": 900, "mirrored": True, "hand_flipped": False,
             "facing_flipped": True},
        ]},
    # 28.07: host: element_id — «поставь окно в МОЮ стену» (audit's most
    # frequent external scenario). The new branch declares its OWN extra
    # decl-scope vars (__hw_<s>/__pt_<s>) that create/post both touch — same
    # lesson this file's docstring names for the ref path's __hl_<s>. Both
    # ops here so the corpus proves the runtime-frame branch for door AND
    # window, and so translation_cert's C1 (every op every version proven)
    # certifies this branch too, not just ref.
    "hosted_element_id": {
        "ir_version": "1.0", "intent": "дверь и окно на чужой стене", "ops": [
            {"op": "create_door", "id": "DE",
             "host": {"by": "element_id", "value": 8145901},
             "offset_mm": 1500, "sill_mm": -100},
            {"op": "create_window", "id": "WE",
             "host": {"by": "element_id", "value": 8145901},
             "offset_mm": 3000, "sill_mm": 900},
        ]},
    # CLASH-починка (28.07): move_elements/change_type declare their OWN
    # decl-scope Lists/vars (__mtIds_<s>/__mtEls_<s>/__mtBefore*_<s>/
    # __tg_<s>/__ty_<s>/__chid_<s>/__el_<s>) that create/post both touch —
    # same scope-contract lesson this file names. targets mix ref (a
    # same-program wall+pipe, so MoveElements is proven on both a
    # LocationCurve AND a wired-but-connectorless pair) with element_id (an
    # existing element, no wall op in-program).
    "move_and_change_type": {
        "ir_version": "1.0", "intent": "перенос связки + смена типа", "ops": [
            {"op": "create_wall", "id": "MW", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": LVL_ID},
            {"op": "create_pipe", "id": "MP", "p0_mm": [0, 0, 2700],
             "p1_mm": [3000, 0, 2900], "level": LVL_ID, "diameter_mm": 50},
            {"op": "move_elements", "id": "ME1",
             "targets": [{"by": "ref", "value": "MW"},
                         {"by": "ref", "value": "MP"},
                         {"by": "element_id", "value": 8145901}],
             "delta_mm": [1000.0, 0.0, 500.0]},
            {"op": "change_type", "id": "CT1",
             "target": {"by": "ref", "value": "MW"},
             "type": {"by": "element_id", "value": 5001}},
        ]},
    # 28.07: ветка location_line эмитится, но в корпусе её не было ни в одной
    # фикстуре — ни здесь, ни в голденах. Значит её байты не держал никто, и
    # правка внутри неё (в этот раз — ось свидетеля) проходила мимо паритета.
    "wall_location_line": {
        "ir_version": "1.0", "intent": "линия привязки стены", "ops": [
            {"op": "create_wall", "id": "WLL", "p0_mm": [0, 0],
             "p1_mm": [7000, 0], "level": LVL, "height_mm": 3300,
             "location_line": "finish_face_exterior"},
        ]},
    "pipe_grid": {
        "ir_version": "1.0", "intent": "труба и ось", "ops": [
            {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
             "p1_mm": [3000, 0, 2700], "level": LVL_ID, "diameter_mm": 50},
            {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000],
             "p1_mm": [0, 9000], "name": "А"},
        ]},
    "mep_runs": {
        "ir_version": "1.0", "intent": "воздуховод и лоток", "ops": [
            {"op": "create_duct", "id": "D1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "level": LVL_ID},
            {"op": "create_cable_tray", "id": "CT1", "p0_mm": [0, 500, 3000],
             "p1_mm": [6000, 500, 3000], "level": LVL_ID},
        ]},
    "pipe_system": {
        "ir_version": "1.0", "intent": "система", "ops": [
            {"op": "create_pipe_system", "id": "SYS1", "level": LVL,
             "nodes": [{"id": "N1", "xyz_mm": [0, 0, 0]},
                       {"id": "N2", "xyz_mm": [0, 0, 15000]},
                       {"id": "N3", "xyz_mm": [3000, 0, 15000]}],
             "segments": [{"from": "N1", "to": "N2", "diameter_mm": 100},
                          {"from": "N2", "to": "N3", "diameter_mm": 50}]},
        ]},
    "route_pipe": {
        "ir_version": "1.0", "intent": "ВК", "ops": [
            {"op": "route_pipe_system", "id": "SYS1", "level": LVL_ID,
             "nodes": [{"id": "N1", "xyz_mm": [0, 0, 15000]},
                       {"id": "N2", "xyz_mm": [0, 0, 0]},
                       {"id": "N3", "xyz_mm": [3000, 0, 0]}],
             "segments": [{"from": "N1", "to": "N2", "diameter_mm": 100},
                          {"from": "N2", "to": "N3", "diameter_mm": 50}]},
        ]},
    "route_duct": {
        "ir_version": "1.0", "intent": "ОВ", "ops": [
            {"op": "route_duct_system", "id": "SYS1", "level": LVL_ID,
             "diameter_mm": 250,
             "nodes": [{"id": "T", "xyz_mm": [0, 0, 3000]},
                       {"id": "A", "xyz_mm": [3000, 0, 3000]},
                       {"id": "B", "xyz_mm": [-3000, 0, 3000]},
                       {"id": "C", "xyz_mm": [0, 3000, 3000]}],
             "segments": [{"from": "T", "to": "A"}, {"from": "T", "to": "B"},
                          {"from": "T", "to": "C"}]},
        ]},
    "struct": {
        "ir_version": "1.0", "intent": "каркас", "ops": [
            {"op": "create_beam", "id": "B1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "level": LVL_ID,
             "symbol": {"by": "name", "value": "Балка 200x400"}},
            {"op": "create_foundation", "id": "F1", "variety": "isolated",
             "xy": [4000, 3000], "level": LVL_ID,
             "symbol": {"by": "name", "value": "Фундамент 1500x1500"}},
            {"op": "create_foundation", "id": "F2", "variety": "slab",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": LVL_ID},
        ]},
    "annotation": {
        "ir_version": "1.0", "intent": "аннотации", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "create_dimension", "id": "DIM1", "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "line_at": [3000, 500]},
            {"op": "create_tag", "id": "TAG1", "in_view": IN_VIEW,
             "target": {"by": "ref", "value": "W1"}, "at": [3000, 800]},
            {"op": "create_text", "id": "TXT1", "in_view": IN_VIEW,
             "at": [1000, 1000], "content": "Проверка"},
        ]},
    "annotation_explicit": {
        "__min_ver__": "2022",  # tag_type = symId overload, >=2022 only
        "ir_version": "1.0", "intent": "аннотации с типами", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "create_dimension", "id": "DIM1", "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "line_at": [3000, 500],
             "dim_type": {"by": "element_id", "value": 6001}},
            {"op": "create_tag", "id": "TAG1", "in_view": IN_VIEW,
             "target": {"by": "ref", "value": "W1"}, "at": [3000, 800],
             "leader": True, "tag_type": {"by": "element_id", "value": 5555}},
            {"op": "create_text", "id": "TXT1", "in_view": IN_VIEW,
             "at": [1000, 1000], "content": "См. примечание",
             "text_type": {"by": "element_id", "value": 7000},
             "width_mm": 80.0, "leader_to": {"by": "ref", "value": "W1"}},
        ]},
    "families": {
        "ir_version": "1.0", "intent": "типы", "ops": [
            {"op": "create_type", "id": "CT1",
             "source_type": {"by": "element_id", "value": 500},
             "category": "structural", "new_name": "ЖБ 400x400",
             "width_mm": 400.0},
            {"op": "create_type", "id": "CT2",
             "source_type": {"by": "element_id", "value": 500},
             "category": "structural", "new_name": "ЖБ 500x600",
             "width_mm": 500.0, "depth_mm": 600.0, "material": "Бетон B30"},
            {"op": "load_family", "id": "LF1", "path": r"C:\Lib\Columns\RC.rfa"},
            {"op": "load_family", "id": "LF2", "path": r"C:\Lib\Columns\RC.rfa",
             "type_name": "RC 400"},
        ]},
    "floor_holes": {
        "__min_ver__": "2022",  # holes = Floor.Create loops, >=2022 only
        "ir_version": "1.0", "intent": "плита с отверстием", "ops": [
            {"op": "create_floor", "id": "FH1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "holes": [[[2000, 2000], [3000, 2000], [3000, 3000], [2000, 3000]]],
             "level": LVL, "structural": True},
        ]},
    # wave/arch (2026-07-29): потолок и оба рода ограждения. Потолок
    # ограничен 2022+ по той же причине, что и floor_holes выше, только
    # жёстче: у перекрытия ниже 2022 есть legacy-путь (NewFloor), у потолка
    # нет НИКАКОГО — doc.Create.NewCeiling не существует ни на одной из
    # шести версий (замерено компиляцией), и на 2021 оп обязан дать
    # типизированный KIR-E003.
    "arch_ceiling": {
        "__min_ver__": "2022",   # Ceiling.Create появился в 2022
        "ir_version": "1.0", "intent": "подвесной потолок", "ops": [
            {"op": "create_ceiling", "id": "CE1",
             "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "holes": [[[2000, 1500], [3000, 1500],
                        [3000, 2500], [2000, 2500]]],
             "level": LVL, "height_offset_mm": 2700},
        ]},
    "arch_railing_path": {
        "ir_version": "1.0", "intent": "ограждение балкона", "ops": [
            {"op": "create_railing", "id": "RP1", "variety": "path",
             "path": [[0, 0], [4000, 0], [4000, 2500]], "level": LVL},
        ]},
    "arch_railing_hosted": {
        "ir_version": "1.0", "intent": "ограждение по лестнице", "ops": [
            {"op": "create_railing", "id": "RH1", "variety": "hosted",
             "host": {"by": "element_id", "value": 8888},
             "position": "treads"},
        ]},
    # wave/shape (2026-07-29): произвольная геометрия мешем. Оси версий у опа
    # нет — всё, что он называет, замерено 6/6, — поэтому и __min_ver__ нет.
    # Форма фикстуры важна: у DirectShape НЕТ уровня, НЕТ типа и НЕТ хоста, и
    # это единственная пишущая операция реестра, которая ничего не грунтует.
    # Октаэдр взят потому, что он замкнут, связен и не имеет ни вырожденных
    # граней, ни висячих вершин, то есть проходит все законы mesh.py целиком.
    "shape_directshape": {
        "ir_version": "1.0", "intent": "произвольная форма мешем", "ops": [
            {"op": "create_directshape", "id": "DS1",
             "mesh": {
                 "vertices_mm": [[2000, 0, 0], [0, 2000, 0], [-2000, 0, 0],
                                 [0, -2000, 0], [0, 0, 2600], [0, 0, -2600]],
                 "triangles": [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4],
                               [1, 0, 5], [2, 1, 5], [3, 2, 5], [0, 3, 5]]},
             "category": "generic_model", "name": "октаэдр"},
        ]},
    "modify": {
        "ir_version": "1.0", "intent": "правка", "allow_destructive": True,
        "ops": [
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 7777},
             "param": "Комментарии", "value": "обработано KIR"},
            {"op": "delete", "id": "DEL1",
             "target": {"by": "element_id", "value": 8888}},
        ]},
    "roof": {
        "ir_version": "1.0", "intent": "кровля", "ops": [
            {"op": "create_roof", "id": "RF1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": LVL},
        ]},
    "contour": {
        "ir_version": "1.0", "intent": "плита по контуру", "ops": [
            {"op": "create_floor_by_contour", "id": "FC1",
             "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [8000, 6000]}},
             "level": LVL},
        ]},
    # Curve-IR (P4-B): the arc branch of create_wall declares an extra
    # __lca/__arc pair inside its post block — this fixture exercises that
    # branch so the scope contract sees it (a straight wall never touches it).
    "arc_wall": {
        "ir_version": "1.0", "intent": "дуговая стена", "ops": [
            {"op": "create_wall", "id": "WA", "p0_mm": [325, 0],
             "p1_mm": [0, 325], "level": LVL,
             "arc": {"curve_type": "Arc", "center_mm": [0.0, 0.0, 0.0],
                     "radius_mm": 325.0, "x_axis": [1.0, 0.0, 0.0],
                     "y_axis": [0.0, 1.0, 0.0], "start_angle_rad": 0.0,
                     "end_angle_rad": 1.5707963267948966}},
        ]},
    # feat/native-groups: create_group carries PRE-GROUNDED member ops (they
    # come from the component-library bridge, not a raw decode), so its members
    # use the {"__grounded__": ...} selector shape ground.py passes through
    # unchanged (the group op itself has grounded=()).  With name -> the post's
    # optional .Name witness branch is exercised.
    "native_group": {
        "ir_version": "1.0", "intent": "типовой этаж как группа", "ops": [
            {"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
             "members": [
                 {"op": "create_wall", "id": "W1", "p0_mm": [30000, 23000],
                  "p1_mm": [36000, 23000],
                  "level": {"__grounded__": {"id": 42, "name": None,
                                             "via": "element_id"}},
                  "height_mm": 3000.0,
                  "type": {"__grounded__": {"id": None, "name": None,
                                            "via": "doc_default",
                                            "in_emit": "__doc_default__"}}},
                 {"op": "place_family", "id": "F1", "xyz": [31000, 24000, 0],
                  "rotation_deg": 90.0, "mirrored": True,
                  "level": {"__grounded__": {"id": 42, "name": None,
                                             "via": "element_id"}},
                  "symbol": {"__grounded__": {"id": 555, "name": "Стул",
                                              "via": "element_id"}}},
             ],
             "placements": [[0, 0, 6600], [0, 0, 13200]]},
        ]},
    # Витражная ячейка (дизайн 2026-07-28): пост-блок ПЕРЕЧИТЫВАЕТ ячейку по
    # адресу, то есть пользуется хелперами адреса и хостом — всё это обязано
    # жить в decl, иначе per_op-изоляция даст CS0103. Обе формы host'а
    # (ref на стену этой же программы и пинованный element_id) и обе формы
    # селектора типа (имя и element_id) — разные ветки эмиссии.
    "curtain_cell": {
        "ir_version": "1.0", "intent": "панели витража", "ops": [
            {"op": "create_wall", "id": "WC", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "set_curtain_panel", "id": "CP1",
             "host": {"by": "ref", "value": "WC"}, "u": 0, "v": 0,
             "panel_type": {"by": "name", "value": "Стеклопакет"}},
            {"op": "set_curtain_panel", "id": "CP2",
             "host": {"by": "element_id", "value": 8145901}, "u": 2, "v": 1,
             "panel_type": {"by": "element_id", "value": 273445}},
        ]},
    # Линия разрезки витража (волна 29.07): свидетель ПЕРЕЧИТЫВАЕТ линию по
    # её id и пользуется хелперами расстояния и членства — всё это обязано
    # жить в decl, иначе per_op-изоляция даст CS0103. Оба направления и обе
    # формы host'а — разные ветки эмиссии.
    "curtain_grid_line": {
        "ir_version": "1.0", "intent": "раскладка сетки витража", "ops": [
            {"op": "create_wall", "id": "WG", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "create_curtain_grid_line", "id": "GL1",
             "host": {"by": "ref", "value": "WG"}, "direction": "u",
             "position_mm": [2000.0, 0.0, 1500.0]},
            {"op": "create_curtain_grid_line", "id": "GL2",
             "host": {"by": "element_id", "value": 8145901},
             "direction": "v", "position_mm": [3000.0, 120.0, 2100.0]},
        ]},
}

_STR = re.compile(r'"(?:[^"\\]|\\.)*"')
_CMT = re.compile(r"//[^\n]*")
_IDENT = re.compile(r"__\w+")
# A declaration: type token (var / dotted identifier / generic) then __name,
# terminated by '=' / ';' / 'in ' (foreach). 'return __Refuse(' / 'throw
# __OpRefuse(' never match: '(' is not a declaration terminator.
_DECL = re.compile(
    r"(?:\b(?:var|[A-Za-z_][\w.]*(?:<[^<>=]*(?:<[^<>=]*>)?[^<>=]*>)?(?:\[\])?)\s+)"
    r"(__\w+)\s*(?:=|;|\bin\b)")
# Обобщённый тип ЛЮБОЙ глубины вложенности: `Func<CurtainGrid,
# List<ElementId>, List<ElementId>, int, int, Element> __x = ...`.  Прежний
# _DECL знал ровно один уровень вложенности и объявление такого хелпера
# читал как «нигде не объявлено» — контракт молча слабел там, где эмиттер
# как раз усложнялся.  Внутренность генерика ограничена (без ';', '=' и
# лишних '<'/'>'), поэтому `if (a > b) __x = ...` сюда не попадает.
_DECL_GENERIC = re.compile(
    r"\b[A-Za-z_][\w.]*<[^<>;=]*(?:<[^<>;=]*>[^<>;=]*)*>(?:\[\])?\s+"
    r"(__\w+)\s*(?:=|;|\bin\b)")
# Lambda parameters declare too: `__x => ...` / `(__m) => ...`.
_LAMBDA = re.compile(r"[(,]?\s*(__\w+)\s*(?:,\s*__\w+\s*)*\)?\s*=>")

# Program-wide names emit_program's own template owns.
GLOBALS = frozenset({"__t", "__post", "__results", "__Refuse", "__OpRefuse"})


def _code(text: str) -> str:
    return _CMT.sub("", _STR.sub('""', text))


def _used(text: str) -> set:
    return set(_IDENT.findall(_code(text)))


def _declared(text: str) -> set:
    code = _code(text)
    return ({m.group(1) for m in _DECL.finditer(code)}
            | {m.group(1) for m in _DECL_GENERIC.finditer(code)}
            | {m.group(1) for m in _LAMBDA.finditer(code)})


class EmitterScopeContract(unittest.TestCase):
    """post/readback identifiers ⊆ decls ∪ own-block locals ∪ globals."""

    def test_every_write_emitter_on_every_version(self):
        covered = set()
        for pname, prog in PROGRAMS.items():
            min_ver = prog.get("__min_ver__", "2021")
            prog = {k: v for k, v in prog.items() if k != "__min_ver__"}
            normed = _parse_and_check(prog)
            grounded = ground_mod.ground(normed, GROUND_SNAPSHOT)
            for ver in [v for v in VERSIONS if v >= min_ver]:
                parts = []
                for op in grounded:
                    d, c, p, r = _EMITTERS[op["op"]](op, ver, "kir:test")
                    # Wave A2: migrated emitters return the post as a list of
                    # WitnessCheck objects; the contract checks the RENDERED
                    # C# (the same bytes emit_program produces).
                    p = post_to_string(op["id"], p)
                    parts.append((op["op"], op["id"], d, c, p, r))
                    covered.add(op["op"])
                # cross-op refs (__el_<host> etc.) resolve against the union
                # of every op's decls — the same visibility the emitted
                # program actually has (all decls precede the transaction).
                all_decls = set()
                for _, _, d, _, _, _ in parts:
                    all_decls |= _declared(d)
                for opname, oid, d, c, p, r in parts:
                    for label, block in (("post", p), ("readback", r)):
                        with self.subTest(program=pname, ver=ver, op=opname,
                                          op_id=oid, block=label):
                            leak = (_used(block) - _declared(block)
                                    - all_decls - GLOBALS)
                            c_decls = _declared(c)
                            self.assertFalse(
                                leak,
                                f"{opname}[{oid}].{label} reads identifiers "
                                f"outside decl scope (per_op isolation would "
                                f"CS0103): "
                                + ", ".join(
                                    f"{i} ({'declared only in create — hoist '
                                            'it to decl' if i in c_decls
                                       else 'undeclared anywhere'})"
                                    for i in sorted(leak)))

    def test_fixture_covers_every_write_emitter(self):
        """A write op absent from the fixtures is a hole in the contract —
        fail loudly so the NEXT emitter wave extends PROGRAMS."""
        write_ops = {name for name, op_spec in spec.OPS.items()
                     if op_spec.family in spec.WRITE_FAMILIES}
        write_ops -= {"create_stairs"}  # sole-op StairsEditScope program,
        #                                 not an _EMITTERS-table emitter
        covered = set()
        for prog in PROGRAMS.values():
            prog = {k: v for k, v in prog.items() if k != "__min_ver__"}
            for op in _parse_and_check(prog):
                covered.add(op["op"])
        self.assertEqual(
            write_ops - covered, set(),
            "write emitters missing from the scope-contract fixtures")


if __name__ == "__main__":
    unittest.main()
