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
# ops are typed version refusals below it (tag_type<2022, floor holes<2022),
# and "__max_ver__" gates programs whose ops are typed version refusals ABOVE
# it. Симметричная граница появилась 09.08 вместе с нагрузками: у них ось
# версий смотрит В ДРУГУЮ СТОРОНУ (свободная нагрузка есть на 2021-2023 и
# убрана из API в 2024), и без верхней границы корпус требовал бы от эмиттера
# выдать C# там, где честный ответ — KIR-E003.
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
            # Both emission branches belong in the structural corpus: CT1
            # leaves section absent, CT2 sets and independently reads it.
            {"op": "create_cable_tray", "id": "CT2", "p0_mm": [0, 900, 3000],
             "p1_mm": [6000, 900, 3000], "level": LVL_ID,
             "width_mm": 300, "height_mm": 100},
        ]},
    # wave/mep-electrical (2026-08-09): короб, обе заготовки и оба гибких
    # участка. Корпус этого файла — ещё и корпус ПРОВЕНАНСА ДОПУСКОВ
    # (test_tolerance_provenance.L5): ветка допуска, которой здесь нет,
    # сертифицирована только в отрицании, и захардкоженное число внутри неё
    # никому не видно. Поэтому программы держат ОБЕ формы селектора (по имени
    # и по id) и трёхточечную ломаную рядом с двухточечной.
    "mep_electrical": {
        "ir_version": "1.0", "intent": "короб и заготовки", "ops": [
            {"op": "create_conduit", "id": "CD1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "level": LVL_ID},
            {"op": "create_pipe_placeholder", "id": "PP1",
             "p0_mm": [0, 1000, 2800], "p1_mm": [6000, 1000, 2800],
             "level": LVL},
            {"op": "create_duct_placeholder", "id": "DP1",
             "p0_mm": [0, 2000, 3200], "p1_mm": [6000, 2000, 3200],
             "level": LVL_ID},
        ]},
    "mep_flex": {
        "ir_version": "1.0", "intent": "гибкие участки", "ops": [
            {"op": "create_flex_duct", "id": "FD1",
             "path": [[0, 3000, 3000], [1500, 3000, 2800], [3000, 3200, 2600]],
             "level": LVL_ID},
            {"op": "create_flex_pipe", "id": "FP1",
             "path": [[0, 4000, 3000], [1500, 4000, 2700]], "level": LVL},
        ]},
    # wave/analysis (2026-08-09): три нагрузки и путь эвакуации. Корпус этого
    # файла — ещё и корпус ПРОВЕНАНСА ДОПУСКОВ (test_tolerance_provenance.L5),
    # поэтому здесь стоят ОБЕ формы селектора случая загружения (по имени и по
    # id), нагрузка С ЯВНЫМ типом рядом с нагрузкой без него, и наклонная
    # линейная нагрузка рядом с горизонтальной: ветка рабочей плоскости у них
    # разная (вертикальная плоскость через отрезок против горизонтальной), и
    # непокрытая ветка — это ветка, которой контракт областей не видит.
    #
    # Ось версий здесь смотрит В ДРУГУЮ СТОРОНУ, чем у потолка и отверстий
    # перекрытия: свободная нагрузка ЕСТЬ на 2021-2023 и убрана из API в 2024,
    # поэтому у программы `__max_ver__`, а не `__min_ver__`.
    "analysis_loads": {
        "__max_ver__": "2023",
        "ir_version": "1.0", "intent": "нагрузки", "ops": [
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
        ]},
    "analysis_path_of_travel": {
        "ir_version": "1.0", "intent": "путь эвакуации", "ops": [
            {"op": "create_path_of_travel", "id": "PT1", "in_view": IN_VIEW,
             "p0_mm": [0, 0], "p1_mm": [12000, 5000]},
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
    # ОБЕ ВЕТВИ ССЫЛКИ В ОДНОЙ ПРОГРАММЕ, потому что они объявляют РАЗНЫЕ
    # переменные: ветвь ref не заводит своей стены вовсе (берёт __el_ соседа),
    # ветвь element_id заводит __hw_<s>, и именно её свидетель читает в блоке
    # post. Фикстура, покрывающая только одну, оставила бы вторую вне этого
    # контракта — а это ровно тот CS0103, которым падало ограждение на живых
    # воротах. WF2 к тому же идёт по ДОКУМЕНТНОМУ типу по умолчанию (`type`
    # опущен), то есть и эта ветвь эмиссии здесь видна.
    "wall_foundation": {
        "ir_version": "1.0", "intent": "лента под стеной", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "create_wall_foundation", "id": "WF1",
             "wall": {"by": "ref", "value": "W1"},
             "type": {"by": "name", "value": "Ленточный 600x300"}},
            {"op": "create_wall_foundation", "id": "WF2",
             "wall": {"by": "element_id", "value": 8145901}},
        ]},
    # ВОЛНА КАРКАСА. Обе операции держат во ВНЕШНЕЙ области ровно то, что
    # перечитывает свидетель, и обе фикстуры это и проверяют:
    #   * балочная система — `__syid_<s>` (id запрошенного символа: сам
    #     `__sy_<s>` объявляет `_symbol_res` ВНУТРИ блока создания, то есть
    #     при per_op он свидетелю невидим — ровно тот CS0103, которым падало
    #     ограждение);
    #   * ферма — `__z_<s>` (отметка плоскости уровня, посчитанная в рантайме)
    #     и `__tyid_<s>`.
    # BS2 берёт ДУГОВОЙ профиль с явным ребром направления: у эмиттера
    # питоновская развилка по bulge, и фикстура, знающая только прямые рёбра,
    # оставила бы дуговую ветку вне контракта. TR2 идёт по ССЫЛКЕ на уровень,
    # созданный этой же программой, — вторая ветвь `_level_expr`.
    "framing": {
        "ir_version": "1.0", "intent": "балочная система и фермы", "ops": [
            {"op": "create_beam_system", "id": "BS1",
             "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [8000, 6000]}},
             "level": LVL_ID},
            {"op": "create_beam_system", "id": "BS2",
             "profile": {"outer": {"shape": "poly",
                                   "points_mm": [[0, 8000], [9000, 8000],
                                                 [9000, 13000], [0, 13000]],
                                   "arcs": [{"edge": 1, "bulge": 0.3}]}},
             "direction_edge": 0, "level": LVL_ID,
             "symbol": {"by": "name", "value": "Балка 200x400"}},
            {"op": "create_level", "id": "LF", "elev_mm": 6000, "name": "КИР-Ф"},
            {"op": "create_truss", "id": "TR1", "p0_mm": [0, 0],
             "p1_mm": [12000, 0], "level": LVL_ID,
             "type": {"by": "name", "value": "Ферма стропильная 12м"}},
            {"op": "create_truss", "id": "TR2", "p0_mm": [0, 2000],
             "p1_mm": [12000, 2000], "level": {"by": "ref", "value": "LF"}},
        ]},
    # ВОЛНА АРМИРОВАНИЯ. У этой операции во ВНЕШНЕЙ области живут ЧЕТЫРЕ
    # переменные, и каждую перечитывает свидетель: `__hh_<s>` (носитель —
    # его id сверяет проверка топологии), `__tyid_<s>` и `__btid_<s>` (типы —
    # обе проверки семантики), `__hkid_<s>` (крюк, без которого не собрался бы
    # сам вызов). Объявить любую из них внутри блока создания значило бы
    # получить CS0103 ровно при per_op — тот же отказ, которым падало
    # ограждение на живых воротах.
    # AR1 идёт по ССЫЛКЕ на плиту этой же программы и БЕЗ крюка (документный
    # тип по умолчанию + `InvalidElementId`), AR2 — по element_id уже стоящей
    # плиты, с явным типом и явным крюком: это ЧЕТЫРЕ разные ветви эмиссии, и
    # фикстура, знающая одну, оставила бы три вне контракта.
    "area_reinforcement": {
        "ir_version": "1.0", "intent": "армирование плит", "ops": [
            {"op": "create_floor", "id": "SL1",
             "outline": [[0, 0], [9000, 0], [9000, 6000], [0, 6000]],
             "level": LVL, "structural": True},
            {"op": "create_area_reinforcement", "id": "AR1",
             "host": {"by": "ref", "value": "SL1"},
             "direction_deg": 0.0,
             "bar_type": {"by": "name", "value": "Ø12 A500C"}},
            {"op": "create_area_reinforcement", "id": "AR2",
             "host": {"by": "element_id", "value": 8145901},
             "direction_deg": 90.0,
             "type": {"by": "name", "value": "Армирование по области 2"},
             "bar_type": {"by": "element_id", "value": 1902},
             "hook_type": {"by": "name", "value": "Крюк 90"}},
        ]},
    "annotation": {
        "ir_version": "1.0", "intent": "аннотации", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "create_dimension", "id": "DIM1", "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "line_at": [3000, 500]},
            {"op": "create_angular_dimension", "id": "ANG1",
             "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "at": [1500, 1500]},
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
            {"op": "create_angular_dimension", "id": "ANG1",
             "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "at": [1500, 1500],
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
    # 09.08.2026: ВТОРАЯ ветка формы того же опа — эскиз CONTOUR. Ветка,
    # которой корпус не строит, этому контракту не видна вовсе (см. шапку
    # файла), а различие у неё ровно в тех именах, из-за которых контракт и
    # заведён: __ol_/__hl_ здесь объявляются строками contour.emit_loop_cs, а
    # не _loop_pts. Отверстие ЭСКИЗОМ (region.holes), потому что плоский
    # `holes` рядом с `contour` — типизированный отказ KIR-P007.
    "arch_ceiling_contour": {
        "__min_ver__": "2022",   # ось версий та же: у потолка на 2021 пути нет
        "ir_version": "1.0", "intent": "потолок по эскизу", "ops": [
            {"op": "create_ceiling", "id": "CE2",
             "contour": {
                 "outer": {"shape": "poly",
                           "points_mm": [[0, 0], [6000, 0],
                                         [6000, 4000], [0, 4000]],
                           "arcs": [{"edge": 1, "bulge": 0.4}]},
                 "holes": [{"shape": "rect", "origin": [2000, 1500],
                            "size_mm": [1000, 1000]}]},
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
    # wave/room (2026-08-03): разделитель помещений. Ломаная из ТРЁХ звеньев,
    # а не из одного: у этого опа блок постусловий читает `__segs_`, `__rsv_`
    # и `__rsvn_`, объявленные во внешней области, и корпус обязан ловить
    # именно ту форму, где сегментов больше одного (CS0103 волны ограждений
    # проявился ровно на многоэлементной ветке).
    "room_separator": {
        "ir_version": "1.0", "intent": "разделитель помещений", "ops": [
            {"op": "create_room_separator", "id": "RS1",
             "path": [[0, 0], [3200, 0], [3200, 2400], [0, 2400]],
             "level": LVL},
        ]},
    # wave/space (2026-08-10): пространство ОВК. ДВА опа, а не один, и не
    # для красоты: блок постусловий объявляет свои временные (`__sloc_`,
    # `__bl_`, `__bread_`, `__bopt_`, `__bsegs_`), и корпус обязан ловить
    # именно ту форму, где их ДВА комплекта в одной программе — ровно там,
    # где имя без суффикса опа дало бы CS0128 «a local variable is already
    # defined». Стена впереди — второй шов: она включает v0-правило
    # `doc.Regenerate()` перед пространством, и без неё эта ветка эмиттера
    # корпусом не строится вовсе.
    # wave/placement (2026-08-11): оба новых рода размещения. Ветка,
    # которой корпус не строит, этому контракту не видна вовсе — ровно
    # тот CS0103, на котором волна ограждений получила шесть отказов
    # живых ворот. У рабочей плоскости своя внешняя переменная
    # (`__pfh_`), у двух уровней — свидетели, читающие параметры
    # ПОСЛЕ закрытия per_op-блока.
    "place_family_work_plane": {
        "ir_version": "1.0", "intent": "прибор на рабочей плоскости",
        "ops": [
            {"op": "create_wall", "id": "PW", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": LVL},
            {"op": "place_family", "id": "PP", "xyz": [4000, 0, 1200],
             "level": LVL, "host": {"by": "ref", "value": "PW"},
             "ref_dir": [1, 0, 0]},
        ]},
    "place_family_two_levels": {
        "ir_version": "1.0", "intent": "семейство между уровнями",
        "ops": [
            {"op": "create_level", "id": "PL", "elev_mm": 6000,
             "name": "КИР-Р"},
            {"op": "place_family", "id": "PT", "xyz": [2000, 2000, 0],
             "level": LVL, "top_level": {"by": "ref", "value": "PL"},
             "base_offset_mm": 100, "top_offset_mm": -250},
        ]},
    "space_mep": {
        "ir_version": "1.0", "intent": "пространства ОВК", "ops": [
            {"op": "create_wall", "id": "SW1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": LVL},
            {"op": "create_space", "id": "SPA", "xy": [2000, 2000],
             "level": LVL},
            {"op": "create_space", "id": "SPB", "xy": [6000, 2000],
             "level": LVL},
        ]},
    # ── wave/site (2026-08-09): площадка и рельеф ───────────────────────────
    # ПО ПРОГРАММЕ НА ВЕТКУ, а не одна на всё семейство: контракт областей
    # видимости видит ровно то, что корпус строит, и у каждой из этих ветвей
    # своя внешняя переменная, которую читает блок постусловий
    # (__pts_ у обеих разновидностей рельефа, __loops_ и __hst_ у площадки и
    # подобласти). Ветка, которой корпус не строит, этому контракту не видна
    # вовсе — ровно тот CS0103, на котором волна ограждений получила шесть
    # отказов живых ворот.
    "site_topography_surface": {
        "ir_version": "1.0", "intent": "рельеф участка", "ops": [
            {"op": "create_topography", "id": "TS1", "variety": "surface",
             "points_mm": [[0, 0, 0], [24000, 0, 800], [24000, 18000, 1500],
                           [0, 18000, 400], [12000, 9000, 1100]]},
        ]},
    # Ось версий: класса Toposolid нет до 2024 (замерено), поэтому ниже вся
    # операция — типизированный отказ KIR-E003, а не другая эмиссия.
    "site_topography_toposolid": {
        "__min_ver__": "2024",
        "ir_version": "1.0", "intent": "толща рельефа", "ops": [
            {"op": "create_topography", "id": "TT1", "variety": "toposolid",
             "points_mm": [[0, 0, 0], [24000, 0, 800], [24000, 18000, 1500],
                           [0, 18000, 400], [12000, 9000, 1100]],
             "level": LVL},
        ]},
    "site_building_pad": {
        "ir_version": "1.0", "intent": "площадка под здание", "ops": [
            {"op": "create_building_pad", "id": "BP1",
             "contour": {"outer": {"shape": "rect", "origin": [2000, 2000],
                                   "size_mm": [12000, 9000]},
                         "holes": [{"shape": "rect", "origin": [5000, 4000],
                                    "size_mm": [1500, 1500]}]},
             "level": LVL,
             "type": {"by": "name", "value": "Площадка 200"}},
        ]},
    # ОБЕ перегрузки подобласти в одной программе: с названным хозяином
    # (ссылкой на рельеф ЭТОЙ ЖЕ программы — тогда хозяин это переменная
    # соседнего опа) и без него (тогда поверхность ищет Revit). Плюс дуговое
    # ребро: габарит сверяется по lowered-edges, знающим кардинальные
    # экстремумы дуг, и прямая ломаная эту ветку не открывает.
    "site_subregion": {
        "ir_version": "1.0", "intent": "подобласти площадки", "ops": [
            {"op": "create_topography", "id": "TS2", "variety": "surface",
             "points_mm": [[0, 0, 0], [30000, 0, 0], [30000, 20000, 900],
                           [0, 20000, 300]]},
            {"op": "create_site_subregion", "id": "SR1",
             "contour": {"outer": {"shape": "poly",
                                   "points_mm": [[1000, 1000], [9000, 1000],
                                                 [9000, 7000], [1000, 7000]],
                                   "arcs": [{"edge": 1, "bulge": 0.35}]}},
             "host": {"by": "ref", "value": "TS2"}},
            {"op": "create_site_subregion", "id": "SR2",
             "contour": {"outer": {"shape": "rect", "origin": [12000, 1000],
                                   "size_mm": [6000, 5000]}}},
            {"op": "create_site_subregion", "id": "SR3",
             "contour": {"outer": {"shape": "rect", "origin": [20000, 1000],
                                   "size_mm": [6000, 5000]}},
             "host": {"by": "element_id", "value": 7777}},
        ]},
    # wave/sweep (2026-08-09): навесные профили. Оси версий у обоих опов НЕТ —
    # всё, что они называют, замерено 6/6, — поэтому и `__min_ver__` нет.
    #
    # ЭТА ФИКСТУРА ПОЙМАЛА НАСТОЯЩИЙ ДЕФЕКТ, и он был ровно тем, ради которого
    # контракт областей видимости существует: `__hs_`/`__named_`/`__bound_`
    # объявлялись в ЧИТАТЕЛЕ свидетеля, а читались КВИТАНЦИЕЙ — то есть в
    # следующей области. 48 живых ячеек Roslyn, 48 отказов CS0103 на всех
    # шести версиях в обеих изоляциях; после переноса объявлений в `decl` —
    # 48 из 48 зелёных. Обе формы носителя (`element_id` и `ref`) стоят здесь
    # намеренно: у `ref` носитель — переменная СОСЕДНЕГО опа, и она живёт в
    # другой области, чем `doc.GetElement`.
    "sweep_wall": {
        "ir_version": "1.0", "intent": "карниз и руст", "ops": [
            {"op": "create_wall", "id": "SW0", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": LVL},
            {"op": "create_wall_sweep", "id": "SW1",
             "host": {"by": "ref", "value": "SW0"},
             "orientation": "horizontal",
             "type": {"by": "name", "value": "Карниз 200x100"}},
            {"op": "create_wall_sweep", "id": "SW2",
             "host": {"by": "element_id", "value": 7777},
             "orientation": "vertical"},
        ]},
    "sweep_slab_edge": {
        "ir_version": "1.0", "intent": "капельники по краям плиты", "ops": [
            {"op": "create_floor", "id": "SE0",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": LVL},
            {"op": "create_slab_edge", "id": "SE1",
             "host": {"by": "ref", "value": "SE0"}, "side": "top",
             "type": {"by": "name", "value": "Капельник 100x50"}},
            {"op": "create_slab_edge", "id": "SE2",
             "host": {"by": "element_id", "value": 7777}, "side": "bottom"},
        ]},
    # ── wave/mass (2026-08-10): стена по наклонной грани массы ─────────────
    # ОБЕ ВЕТКИ РАЗРЕШЕНИЯ НОСИТЕЛЯ В ОДНОЙ ПРОГРАММЕ, и это не роскошь:
    # контракт областей видимости видит ровно то, что корпус строит, а ветки
    # объявляют РАЗНЫЕ имена (`ref` берёт переменную соседнего опа, `element_id`
    # идёт через doc.GetElement). Тип назван в ОБЕИХ: пул `wall_types` в снимке
    # содержит два элемента, поэтому пропущенный тип — законный отказ ground,
    # а не покрытие ветки.
    "mass_face_wall": {
        "ir_version": "1.0", "intent": "стены по скатам массы", "ops": [
            {"op": "place_family", "id": "MS0",
             "symbol": {"by": "family_type", "category": "OST_Furniture",
                        "family_name": "Стол офисный",
                        "type_name": "Стол 1200"},
             "xyz": [1000, 2000, 0], "level": LVL},
            {"op": "create_face_wall", "id": "MF1",
             "host": {"by": "ref", "value": "MS0"},
             "face_normal": [0.6, 0.0, 0.8],
             "location_line": "core_exterior",
             "type": {"by": "name", "value": "Кирпич 250"}},
            {"op": "create_face_wall", "id": "MF2",
             "host": {"by": "element_id", "value": 7777},
             "face_normal": [0.0, -0.5, 0.5],
             "location_line": "wall_centerline",
             "type": {"by": "name", "value": "ЖБ 200"}},
        ]},
    # ── wave/detail (2026-08-09): заливка на виде ───────────────────────────
    # ОБЕ ВЕТКИ ТИПА В ОДНОЙ ПРОГРАММЕ, потому что контракт областей видимости
    # видит ровно то, что корпус строит, а внешних переменных у этого опа
    # больше, чем у любого другого в семействе: кроме `__el_`/`__vw_` блок
    # постусловий читает `__frt_` (тип), ШЕСТЬ авторских массивов и локальную
    # функцию `__vp_` — то есть ровно тот CS0103, на котором волна ограждений
    # получила шесть отказов живых ворот, если хоть одно из них уедет в create.
    # Дуга и дырка здесь по той же причине, что в эталонах: без них ветка
    # «петель больше одной» и ветка «сверяем середину» не строятся вовсе.
    "detail_filled_region": {
        "ir_version": "1.0", "intent": "заливки на виде", "ops": [
            {"op": "create_filled_region", "id": "FR1",
             "in_view": {"by": "element_id", "value": 900},
             "contour": {"outer": {"shape": "poly",
                                   "points_mm": [[0, 0], [4000, 0],
                                                 [4000, 2500], [0, 2500]],
                                   "arcs": [{"edge": 1, "bulge": 0.4}]},
                         "holes": [{"shape": "rect", "origin": [1000, 800],
                                    "size_mm": [800, 600]}]},
             "type": {"by": "name", "value": "Бетон"}},
            {"op": "create_filled_region", "id": "FR2",
             "in_view": {"by": "element_id", "value": 900},
             "contour": {"outer": {"shape": "rect", "origin": [6000, 500],
                                   "size_mm": [3000, 1200]}}},
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
    # wave/solid (2026-08-09): параметрические тела. Оси версий у опов нет —
    # вся GeometryCreationUtilities побайтово одинакова на шести версиях. Как
    # и у меша, здесь НЕТ уровня, НЕТ типа и НЕТ хоста.
    #
    # ЧЕТЫРЕ ПРОГРАММЫ, А НЕ ДВЕ, потому что у обоих опов свидетели ветвятся
    # по ФОРМЕ ВХОДА, а не по параметру: отметка основания решает, печатается
    # ли преобразование вообще; дуга в профиле решает, работает ли замкнутая
    # форма площади на кривом ребре; полный оборот решает, ЕСТЬ ЛИ у тела
    # торцы (у 360° их нет, и свидетеля площади торцов тоже нет — отсутствие
    # названо в квитанции). Корпус, не заходящий в ветку, заверяет её только
    # в отрицании.
    "solid_extrusion": {
        "ir_version": "1.0", "intent": "выдавленное тело", "ops": [
            {"op": "create_solid_extrusion", "id": "SE1",
             "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [4000, 3000]}},
             "height_mm": 2500,
             "category": "generic_model", "name": "призма"},
        ]},
    "solid_extrusion_arc_holes": {
        "ir_version": "1.0", "intent": "выдавливание с дугой и проёмами",
        "ops": [
            {"op": "create_solid_extrusion", "id": "SE2",
             "profile": {
                 "outer": {"shape": "poly",
                           "points_mm": [[0, 0], [6000, 0], [6000, 4000],
                                         [0, 4000]],
                           "arcs": [{"edge": 1, "bulge": 0.4}]},
                 "holes": [{"shape": "rect", "origin": [1000, 1000],
                            "size_mm": [1200, 1200]},
                           {"shape": "rect", "origin": [3000, 1500],
                            "size_mm": [900, 900]}]},
             "height_mm": 1800, "base_z_mm": 3300,
             "category": "mass", "name": "плита с проёмами"},
        ]},
    "solid_revolve": {
        "ir_version": "1.0", "intent": "тело вращения, сектор", "ops": [
            {"op": "create_solid_revolve", "id": "SR1",
             "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                   "size_mm": [800, 2400]}},
             "axis_xy_mm": [5000, 4000], "sweep_deg": 270,
             "category": "generic_model", "name": "сектор кольца"},
        ]},
    "solid_revolve_full_turn": {
        "ir_version": "1.0", "intent": "тело вращения, полный оборот",
        "ops": [
            {"op": "create_solid_revolve", "id": "SR2",
             "profile": {
                 "outer": {"shape": "poly",
                           "points_mm": [[600, 0], [2000, 0], [2000, 500],
                                         [1200, 500], [1200, 3000],
                                         [600, 3000]]},
                 "holes": [{"shape": "rect", "origin": [800, 1000],
                            "size_mm": [300, 800]}]},
             "axis_xy_mm": [0, 0], "sweep_deg": 360, "base_z_mm": -1500,
             "category": "site", "name": "колонна вращения"},
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
    # ── ВЕТКИ ДОПУСКОВ, КОТОРЫЕ КОРПУС НЕ СТРОИЛ (03.08) ─────────────────
    # Сертификат доказывает ровно то, что корпус собирает. Ветка допуска, в
    # которую корпус не заходит, заверена только в ОТРИЦАНИИ («свидетель
    # правильно отсутствует»), и захардкоженное число внутри неё невидимо
    # ни сертификату, ни возмущающему оракулу. Замер 03.08: восемь ключей
    # реестра не достигались НИ ОДНОЙ программой корпуса — шесть условных
    # смещений/диаметров и обе числовые ветки set_param (корпус ставил
    # только строковое значение). Здесь они закрыты; проверяет это
    # tests/test_tolerance_provenance.py (закон «корпус — часть
    # доказательства»).
    "offsets_and_diameters": {
        "ir_version": "1.0", "intent": "смещения и диаметры", "ops": [
            {"op": "create_level", "id": "LOB", "elev_mm": 0, "name": "КИР-Н"},
            {"op": "create_level", "id": "LOT", "elev_mm": 3300,
             "name": "КИР-В"},
            {"op": "create_wall", "id": "WO", "p0_mm": [0, 0],
             "p1_mm": [5000, 0], "level": {"by": "ref", "value": "LOB"},
             "top_level": {"by": "ref", "value": "LOT"},
             "base_offset_mm": -150, "top_offset_mm": -250},
            {"op": "create_column", "id": "CO", "xy": [1000, 1000],
             "level": {"by": "ref", "value": "LOB"},
             "top_level": {"by": "ref", "value": "LOT"},
             "base_offset_mm": 150, "top_offset_mm": -250},
            {"op": "create_floor", "id": "FO",
             "outline": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]],
             "level": {"by": "ref", "value": "LOB"},
             "height_offset_mm": -50},
            {"op": "create_floor_by_contour", "id": "FCO",
             "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [5000, 4000]}},
             "level": {"by": "ref", "value": "LOB"},
             "height_offset_mm": 120},
            {"op": "create_duct", "id": "DO", "p0_mm": [0, 0, 3000],
             "p1_mm": [4000, 0, 3000],
             "level": {"by": "ref", "value": "LOB"}, "diameter_mm": 200},
        ]},
    # НАКЛОННАЯ колонна (`top_xy`) — отдельная ветвь эмиттера, и до 10.08.2026
    # ни одна фикстура её не ставила. Контракт эту ветвь НЕ ВИДЕЛ, а она
    # нарушает его дважды: свидетель наклонной колонны читает отметки
    # `__lv_<s>.Elevation` и `__ctl_<s>.Elevation`, оба объявлены внутри
    # `create`. При per_op обёртке это CS0103.
    #
    # Найдено не рассуждением: сухой гейт по НАСТОЯЩЕМУ разбору `night_b13`
    # дал 6 отказов Roslyn из 6 проверок — «The name '__lv_e287178' does not
    # exist in the current context» на всех шести версиях. Это второй случай
    # в ЭТОМ ЖЕ эмиттере (первый — висячий `else` у поворота, комментарий в
    # `_emit_column` рядом), и оба раза причина одна: фикстура ставила только
    # вертикальную колонну.
    "slanted_column": {
        "ir_version": "1.0", "intent": "наклонная колонна", "ops": [
            {"op": "create_level", "id": "LSB", "elev_mm": 0, "name": "КИР-НН"},
            {"op": "create_level", "id": "LST", "elev_mm": 3300,
             "name": "КИР-ВВ"},
            {"op": "create_column", "id": "CS", "xy": [1000, 1000],
             "level": {"by": "ref", "value": "LSB"},
             "top_level": {"by": "ref", "value": "LST"},
             "top_xy": [2500, 2500], "rotation_deg": 15.0,
             "base_offset_mm": 150, "top_offset_mm": -250},
        ]},
    "set_param_numeric": {
        "ir_version": "1.0", "intent": "числовые параметры", "ops": [
            {"op": "set_param", "id": "SPM",
             "target": {"by": "element_id", "value": 7777},
             "param": "Смещение сверху",
             "value": {"value": 2500, "unit": "mm"}},
            {"op": "set_param", "id": "SPD",
             "target": {"by": "element_id", "value": 7777},
             "param": "Коэффициент", "value": {"value": 1.25, "unit": "raw"}},
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
    # wave/opening (03.08.2026): проём как ОТДЕЛЬНЫЙ элемент. Обе ветви и обе
    # формы host'а стоят здесь по прямому требованию этого файла и
    # test_tolerance_provenance (L5): ветка, в которую корпус не заходит,
    # заверена только в ОТРИЦАНИИ, и захардкоженное в ней число невидимо ни
    # сертификату, ни возмущающему оракулу. Свидетели ОБЕИХ ветвей читают
    # переменные хоста (`__hw_*`/`__hst_*`) из post-блока — то есть это ровно
    # тот шов, ради которого файл и написан: объяви их внутри create, и
    # per_op-изоляция даст CS0103.
    #
    # Оба значения `cut` присутствуют намеренно: у вертикального реза
    # свидетель сверяет РАВЕНСТВО габаритов, у перпендикулярного — ВКЛЮЧЕНИЕ
    # (на скате план проёма шире контура), и это две разные эмиссии.
    "opening_wall_rect_and_host_face": {
        "ir_version": "1.0", "intent": "проёмы отдельными элементами", "ops": [
            {"op": "create_wall", "id": "WO", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL, "height_mm": 3000},
            {"op": "create_opening", "id": "OW", "variety": "wall_rect",
             "host": {"by": "ref", "value": "WO"},
             "p0_mm": [1000.0, 0.0, 900.0], "p1_mm": [2500.0, 0.0, 2400.0]},
            {"op": "create_opening", "id": "OWE", "variety": "wall_rect",
             "host": {"by": "element_id", "value": 8145901},
             "p0_mm": [3000.0, 0.0, 0.0], "p1_mm": [4200.0, 0.0, 2100.0]},
            {"op": "create_opening", "id": "OFV", "variety": "host_face",
             "host": {"by": "element_id", "value": 8145901},
             "outline": [[1000, 1000], [3000, 1000], [3000, 3000],
                         [1000, 3000]],
             "cut": "vertical"},
            {"op": "create_opening", "id": "OFP", "variety": "host_face",
             "host": {"by": "element_id", "value": 8145901},
             "outline": [[5000, 1000], [7000, 1000], [7000, 3000],
                         [5000, 3000]],
             "cut": "perpendicular"},
        ]},
    # 09.08.2026: ВТОРОЙ вход формы того же рода — эскиз CONTOUR. Ветка,
    # которой корпус не строит, ни этому контракту, ни возмущающему оракулу
    # L5/L6 не видна вовсе, а различий у неё ровно два и оба по именам:
    # `__ca_*` собирается строками `contour.emit_curvearray_cs`, а читатель
    # границы объявляет `__c_*`/`__k_*`/`__pt_*` внутри ВЫБОРКИ по
    # `Curve.Evaluate`, а не обхода концов. Оба значения `cut` снова стоят
    # рядом: у вертикального реза свидетель сверяет ПОЛОСУ (вершины снизу,
    # габарит с дугами сверху), у перпендикулярного — только нижнюю границу.
    "opening_host_face_contour": {
        "ir_version": "1.0", "intent": "проёмы по эскизу", "ops": [
            {"op": "create_opening", "id": "OCV", "variety": "host_face",
             "host": {"by": "element_id", "value": 8145901},
             "contour": {"outer": {
                 "shape": "poly",
                 "points_mm": [[1000, 1000], [3000, 1000],
                               [3000, 3000], [1000, 3000]],
                 "arcs": [{"edge": 1, "bulge": 0.4}]}},
             "cut": "vertical"},
            {"op": "create_opening", "id": "OCP", "variety": "host_face",
             "host": {"by": "element_id", "value": 8145901},
             "contour": {"outer": {"shape": "rect", "origin": [5000, 1000],
                                   "size_mm": [2000, 2000],
                                   "rotation_deg": 30.0}},
             "cut": "perpendicular"},
        ]},
    # СКОБКИ ВЫШЕ ВОССТАНОВЛЕНЫ 09.08 — ФАЙЛ НЕ РАЗБИРАЛСЯ ВОВСЕ.
    # Прежнее слияние прошло ВНУТРИ этого литерала и унесло с собой закрытие
    # `ops` и самой программы (`]},`), из-за чего весь модуль падал с
    # SyntaxError «closing parenthesis '}' does not match opening '['», то
    # есть контракт областей видимости НЕ ПРОВЕРЯЛСЯ НИ ОДНИМ прогоном — а
    # ошибка при этом читалась как поломка соседней волны датумов, чей блок
    # оказался первым за разрезом. Ровно тот класс, ради которого написан
    # `tools/merge_dup_keys.py`, и ровно та причина, по которой `ast.parse`
    # гоняют по КАЖДОМУ сведённому файлу сразу, а не тестами потом.
    # wave/datums (09.08.2026). Три опа волны в ОДНОЙ программе, потому что
    # проверяемый здесь шов — именно соседство: у всех трёх свидетель читает
    # переменные, которые создающий блок присваивает (`__nrm_*`/`__org_*` у
    # кровли, `__want_*` у лестницы, `__ze_*` у цепи осей). Объяви их внутри
    # create — и per_op-изоляция даст CS0103 ровно так же, как когда-то у
    # хоста семейства.
    #
    # ОБЕ ВЕТВИ ТИПА КРОВЛИ ПРИСУТСТВУЮТ НАМЕРЕННО: документное умолчание
    # (`XR1`, тип опущен) и пришпиленный id (`XR2`) — это две разные эмиссии,
    # и фикстура, знающая одну, оставила бы вторую непроверенной.
    #
    # У `XR2` ход выдавливания ОТРИЦАТЕЛЬНЫЙ с одной стороны (-3000..9000):
    # знак — единственное, что решается в рантайме по нормали Revit, и
    # программа, где обе границы положительны, эту ветку не осветила бы.
    "datums_grid_chain_roof_and_multistory": {
        "ir_version": "1.0", "intent": "датумы: цепь осей, выдавленная кровля, "
                                       "многоэтажная лестница", "ops": [
            {"op": "create_multi_segment_grid", "id": "MG1",
             "path": [[0, 0], [8000, 0], [8000, 6000]], "level": LVL},
            {"op": "create_extrusion_roof", "id": "XR1",
             "p0_mm": [0, 0], "p1_mm": [0, 8000],
             "profile_mm": [[0, 3000], [4000, 5000], [8000, 3000]],
             "level": LVL, "start_mm": 0, "end_mm": 12000},
            {"op": "create_extrusion_roof", "id": "XR2",
             "p0_mm": [1000, 2000], "p1_mm": [9000, 2000],
             "profile_mm": [[0, 4000], [8000, 4000]],
             "level": LVL_ID, "type": {"by": "element_id", "value": 771},
             "start_mm": -3000, "end_mm": 9000},
            {"op": "create_multistory_stairs", "id": "MS1",
             "stairs": {"by": "element_id", "value": 8145901},
             "levels": [LVL, {"by": "element_id", "value": 43}]},
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
# Lambda parameters declare too: `__x => ...` / `(__m) => ...` /
# `(__a, __b) => ...`.  Capture the complete parameter list: consuming the
# tail outside group(1) made every parameter after the first invisible.
_LAMBDA = re.compile(r"[(,]?\s*(__\w+(?:\s*,\s*__\w+)*)\s*\)?\s*=>")

# A C# declaration may introduce several names in one statement.  This is a
# deliberately small parser for generated code, not a general C# grammar:
# commas inside (), [] or {} are ignored and only a top-level `, __name`
# followed by `=`, `,` or `;` is accepted as another declarator.
_ID_ONLY = re.compile(r"__\w+")
_DECL_COMMA = re.compile(
    r"\b(var|[A-Za-z_][\w.]*(?:<[^<>=;]*(?:<[^<>=;]*>)?[^<>=;]*>)?(?:\[\])?)\s+"
    r"(__\w+)\s*,")
_NOT_A_TYPE = frozenset({
    "out", "ref", "in", "return", "throw", "yield", "case", "else", "new",
    "is", "as", "await", "params", "this", "base", "default", "goto",
    "typeof", "sizeof", "nameof", "checked", "unchecked", "when",
})
_NEXT_DECLARATOR = re.compile(r"\s*(__\w+)\s*(?==|,|;)")


def _tail_declarators(code: str, start: int) -> set[str]:
    """Return sibling declarators after the first name in one statement."""
    names: set[str] = set()
    depth = 0
    i, end = start, len(code)
    while i < end:
        char = code[i]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth < 0:
                break
        elif depth == 0:
            if char == ";":
                break
            if char == ",":
                nxt = _NEXT_DECLARATOR.match(code, i + 1)
                if nxt:
                    names.add(nxt.group(1))
                    i = nxt.end(1)
                    continue
        i += 1
    return names

# Program-wide names emit_program's own template owns.
# Имена, которые объявляет ПРЕАМБУЛА программы (_AUTH_PREAMBLE), а не
# блок операции. `__ClassName` добавлен 04.08.2026 вместе с уходом от
# обращения к среде выполнения за типом; он лежит в преамбуле рядом с
# `__Refuse` и виден так же. ПРОВЕРЕНО ЖИВЫМ КОМПИЛЯТОРОМ, а не
# рассуждением: curtain_cell собирается на 2021 и 2026 в обоих режимах
# изоляции (atomic и per_op), и в обоих emit объявляет __ClassName.
#
# `__KirCanonUnit`/`__KirCanonCmp`/`__KirCanonPayload` добавлены 09.08.2026
# вместе со свидетелем поверхности `create_directshape`. Тот же шов и тот же
# якорь, что у `__ClassName` (`_with_mesh_canon_helper` вставляет объявление
# перед `var __results`, то есть до любого кода операций), и та же проверка:
# живой компайл-сервис :52412 собрал меш-программу 6/6 в ОБЕИХ изоляциях —
# ровно тот случай, где эта проверка ловит CS0103 (первый прогон свидетеля
# упал на 2021-2026 на столкновении имени `__st_` с SubTransaction обёртки
# per_op, и упал он ЗДЕСЬ-и-в-воротах, а не на машине пользователя).
GLOBALS = frozenset({"__t", "__post", "__results", "__Refuse", "__OpRefuse",
                     "__ClassName",
                     "__KirCanonUnit", "__KirCanonCmp", "__KirCanonPayload"})


def _code(text: str) -> str:
    return _CMT.sub("", _STR.sub('""', text))


def _used(text: str) -> set:
    return set(_IDENT.findall(_code(text)))


def _declared(text: str) -> set:
    code = _code(text)
    names: set[str] = set()
    for pattern in (_DECL, _DECL_GENERIC):
        for match in pattern.finditer(code):
            names.add(match.group(1))
            names |= _tail_declarators(code, match.end())
    for match in _DECL_COMMA.finditer(code):
        head = match.group(1).split("<")[0].split("[")[0]
        if head in _NOT_A_TYPE:
            continue
        names.add(match.group(2))
        names |= _tail_declarators(code, match.end(2))
    for match in _LAMBDA.finditer(code):
        names |= set(_ID_ONLY.findall(match.group(1)))
    return names


class TheDeclarationParserItself(unittest.TestCase):
    """The structural guard must see every declaration without inventing one."""

    def test_a_compact_declaration_declares_every_name(self):
        self.assertEqual(_declared("double __a = 1.0, __b = 2.0;"),
                         {"__a", "__b"})
        self.assertEqual(_declared("int __i, __j;"), {"__i", "__j"})
        self.assertEqual(
            _declared("ElementId __x = null, __y = null, __z = null;"),
            {"__x", "__y", "__z"})

    def test_a_compact_declaration_survives_a_call_in_its_initialiser(self):
        self.assertEqual(
            _declared("double __a = Math.Max(__p, __q), __b = 0.0;"),
            {"__a", "__b"})

    def test_a_for_header_declares_both_counters(self):
        self.assertEqual(_declared("for (int __i = 0, __n = 10; __i < __n;)"),
                         {"__i", "__n"})

    def test_every_lambda_parameter_is_declared_not_only_the_first(self):
        self.assertEqual(_declared("__m => __m.Id"), {"__m"})
        self.assertEqual(_declared("(__a, __b) => __a.Id == __b.Id"),
                         {"__a", "__b"})

    def test_the_parser_does_not_invent_declarations(self):
        for code in ("__Groups(doc, __g, ref __gr, ref __gp, ref __gn);",
                     "__post.Add(__a, __b);",
                     "var __ok = __t.Commit(); return __Refuse(__oid, __msg);",
                     "__results[__oid] = new Dictionary<string, object>();"):
            with self.subTest(code=code):
                self.assertEqual(_declared(code) - {"__ok"}, set())

    def test_a_compact_create_declaration_is_visible_to_the_diagnostic(self):
        create = "double __w_x = 1.0, __h_x = 2.0;"
        post = "__post.Add(__h_x);"
        leak = _used(post) - _declared(post) - GLOBALS
        self.assertEqual(leak, {"__h_x"})
        self.assertIn("__h_x", _declared(create))


class EmitterScopeContract(unittest.TestCase):
    """post/readback identifiers ⊆ decls ∪ own-block locals ∪ globals."""

    def test_every_write_emitter_on_every_version(self):
        covered = set()
        for pname, prog in PROGRAMS.items():
            min_ver = prog.get("__min_ver__", "2021")
            max_ver = prog.get("__max_ver__", VERSIONS[-1])
            prog = {k: v for k, v in prog.items()
                    if k not in ("__min_ver__", "__max_ver__")}
            normed = _parse_and_check(prog)
            grounded = ground_mod.ground(normed, GROUND_SNAPSHOT)
            for ver in [v for v in VERSIONS if min_ver <= v <= max_ver]:
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
        # Соло-опы не проходят `_EMITTERS`: каждый владеет шаблоном
        # целой программы. Список берётся из того же реестра,
        # что и plan/emit, а не из литерала первого такого опа.
        write_ops -= set(spec.SOLO_OPS)
        covered = set()
        for prog in PROGRAMS.values():
            prog = {k: v for k, v in prog.items()
                    if k not in ("__min_ver__", "__max_ver__")}
            for op in _parse_and_check(prog):
                covered.add(op["op"])
        self.assertEqual(
            write_ops - covered, set(),
            "write emitters missing from the scope-contract fixtures")


if __name__ == "__main__":
    unittest.main()
