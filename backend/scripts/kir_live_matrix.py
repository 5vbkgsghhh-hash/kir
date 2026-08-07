"""Живая матрица: какой пишущий оп РЕАЛЬНО строит, а какой только компилируется.

Гейт Roslyn (`kukai.ir.gate_runner`) доказывает, что все 32 опа компилируются на
шести версиях Revit. Он ничего не говорит о том, строит ли Revit то, что они
описывают: на 27.07 живого Revit касались 8 пишущих опов из 28.

Скрипт гонит по одной программе на оп через ТОТ ЖЕ прод-путь, что и чат
(`POST /admin/kir/run` -> `serving.handle_revit_ir`: ground-снапшот ->
compile_program -> run_declarative), и раскладывает исход на четыре честных
вердикта:

  СТРОИТ            ok:true И все три свидетеля зелёные
  СЛОМАН            типизированный отказ / нарушенное постусловие (с текстом)
  НЕ НА ЧЕМ         ground отказал: нужного пула типов в этой модели нет
  ПРОПУЩЕН          предшественник не дал id / выбор из пула не назван

`ok:true` с `postconditions_violated` — это НЕ успех, а найденный дефект: элемент
закоммичен, но постусловие не выполнено.

Каждый прогон сам ложится в корпус свидетелей (`data/telemetry/kir_witness.jsonl`),
поэтому доказательство переживает сессию и позже цитируется замером, а не памятью.

ДВА НАБОРА СТРОК, И ЭТО РАЗНЫЕ ЖАНРЫ
------------------------------------
`build_programs()`     — базовые 21 строки, снятые 27.07 на SOB6.2. Селекторы
                         ПРИБИТЫ к element_id того документа (L01/WALL_TYPE/…):
                         на другой модели они законно отказывают. Не трогаются —
                         это уже добытое доказательство.
`build_gap_programs()` — 19 строк на 16 пишущих опов, которых живой Revit не
                         касался НИ РАЗУ (замер 04.08: в реестре 37 пишущих
                         опов, базовый набор гоняет 21). Эти САМОДОСТАТОЧНЫ:
                         свой уровень, свой носитель, ни одного id чужой модели.
                         Единственное допущение — открытый документ Revit.

ЧТО ЗНАЧИТ «САМОДОСТАТОЧНА», ЕСЛИ ОПУ НУЖЕН ТИПОРАЗМЕР
------------------------------------------------------
Уровень и носитель программа строит сама (`create_level` + `{"by":"ref"}` —
ground.py разрешает ref внутри программы, минуя снапшот). А вот дверь без
семейства двери построить нельзя НИКАКИМ API: типоразмер обязан уже лежать в
документе, и `load_family` его туда положит, но сослаться на него из ТОЙ ЖЕ
программы нечем (`_symbol_res` читает `__grounded__["id"]`, ветки `via:"ref"`
у него нет). Поэтому такие места помечены `pick(...)` и разрешаются так:

  1. `--pin <ключ>=<element_id>` — слово оператора, сильнее всего;
  2. каталог фазы 0 (`--discover`: тот же прод-путь, оп `query_types`) —
     выбор ПЕЧАТАЕТСЯ, потому что невидимый выбор неотличим от
     `.FirstOrDefault()`;
  3. без каталога — `{"by": "default"}`, то есть «единственный в пуле».
     На свежем документе это работает, на реальном честно отказывает KIR-G102
     со списком кандидатов, и матрица подставляет кандидата САМА (`--autopin`,
     включён по умолчанию) — печатая, кого взяла.

ГРАНИЦА ОХВАТА, ОБЪЯВЛЕННАЯ СЛОВАМИ
-----------------------------------
* `query_types` знает 16 пулов из 18 грунтуемых: `ceiling_types` и
  `railing_types` (волна arch, 29.07) в его enum НЕ ВОШЛИ. Для потолка и
  ограждения фаза 0 бессильна — там работают только `--pin` и автоподбор по
  KIR-G102. Это пробел реестра, а не матрицы.
* `wall_types` в каталоге — это `{id, name}`: витражный тип от базового
  отличить нечем, кроме имени. Отсюда `prefer=` с явным списком образцов и
  `--pin curtain_wall_type=<id>`, если имена в документе нестандартные.
* Матрица НЕ судит идемпотентность и НЕ чистит за собой: инвентарь созданного
  лежит в артефакте (`result` каждой строки), снос — `/admin/kir/cleanup_stamps`.
* Вердикт выносится по ОДНОМУ прогону. «СТРОИТ» здесь значит «построил в этом
  документе на этой версии», а не «строит всегда».

ПОРЯДОК ПРОГОНА
---------------
    # 0. переснять L0 (разблокирует балки/лестницы/метку core) — см. --plan
    # 1. разведка (ЧТЕНИЕ, ничего не пишет)
    PYTHONPATH=. venv/bin/python3.12 scripts/kir_live_matrix.py --doc sob6 --discover
    # 2. план прогона на экран — что за чем и что считать успехом
    PYTHONPATH=. venv/bin/python3.12 scripts/kir_live_matrix.py --plan
    # 3. сам прогон (--set gap | base | all)
    PYTHONPATH=. venv/bin/python3.12 scripts/kir_live_matrix.py --doc sob6 --set gap
    PYTHONPATH=. venv/bin/python3.12 scripts/kir_live_matrix.py --doc sob6 --only create_door
    PYTHONPATH=. venv/bin/python3.12 scripts/kir_live_matrix.py --dry --set gap  # печать программ

Офлайн-доказательство тех же программ (Roslyn ×6, без устройства):
    PYTHONPATH=. venv/bin/python3.12 scripts/kir_gap_compile_matrix.py
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE = "http://127.0.0.1:52411"
BACKEND = pathlib.Path(__file__).resolve().parent.parent
ARTIFACTS = pathlib.Path("/home/claude/kir-night/artifacts")

# Записи только со сдвигом: разрешение оператора — писать в рабочую модель
# ТОЛЬКО на +200 м от оригинала (тот же Δ, что в прогоне идемпотентности A5).
DX = 200_000.0

# Каталог SOB6.2, снятый фазой 0 (`query_types` по 16 закрытым пулам).
# Селекторы — ПО element_id, а не по имени: в duct_types три типа с
# одинаковым именем «По умолчанию», и by=name там законно отказал бы KIR-G102.
L01 = 172458          # уровень L_01_+0.000
L02 = 975727          # уровень L_02_+7.500
WALL_TYPE = 1552125   # ВН_Газобетон D600_200мм
FLOOR_TYPE = 4309863  # АП_Пол первого этажа_100 мм
SLAB_TYPE = 86313     # Плита 300 мм
WINDOW_SYM = 19313138
BEAM_SYM = 20642161   # 100х100х8
PIPE_TYPE = 604023
PIPE_SYS = 246260     # Канализация
# ЗАМЕРЕНО: три типа воздуховода носят ОДНО имя «По умолчанию» и отличаются
# только формой — 604018 Rectangular, 604019 Round, 604020 Oval. Берём КРУГЛЫЙ:
# create_duct/route_duct_system умеют выразить только diameter_mm, и на
# прямоугольном типе свидетель честно ловит «diameter mismatch» и откатывает
# (оп не сломан — он не умеет сказать ширина×высота; это пробел реестра).
DUCT_TYPE = 604019    # Round
DUCT_SYS = 246254     # Приточный воздух
TRAY_TYPE = 604025
VIEW_PLAN = 20905960  # план L_01_+0.000, CropBoxActive == false (проверено)
COLUMN_RFA = (r"C:\ProgramData\Autodesk\RVT 2023\Libraries\Russian\Belarus"
              r"\Несущие конструкции\Колонны\Сталь\Специально для Беларуси"
              r"\Прямоугольные и квадратные пустотелые сечения-Колонна.rfa")


def eid(value: int) -> dict:
    return {"by": "element_id", "value": value}


def ref(op_id: str) -> dict:
    return {"by": "ref", "value": op_id}


def grounded(value: int, name: str = "") -> dict:
    """Член группы обязан быть PRE-GROUNDED: эмиттер зовётся напрямую, минуя
    ground-стадию, и читает ``param["__grounded__"]["id"]``."""
    return {"__grounded__": {"id": value, "name": name or None,
                             "via": "element_id"}}


def prog(intent: str, *ops: dict, destructive: bool = False) -> dict:
    p = {"ir_version": "1.0", "intent": intent, "ops": list(ops)}
    if destructive:
        p["allow_destructive"] = True
    return p


def x(v: float) -> float:
    """Сдвиг по X: всё пишется на +200 м от здания оператора."""
    return v + DX


# ── программы: один оп на программу, кроме связок, где оп ФИЗИЧЕСКИ требует
# предшественника (окно на стене, марка на элементе). Связка нужна не для
# удобства, а чтобы НИКОГДА не целиться в элемент оператора: хост создаётся
# своей же программой и адресуется через ref.
def build_programs() -> list[tuple[str, dict, str]]:
    out: list[tuple[str, dict, str]] = []

    out.append(("create_level", prog(
        "живая проверка create_level",
        {"op": "create_level", "id": "LV", "elev_mm": 120_000.0,
         "name": "KIR_TEST_L120"}), "пулов не требует"))

    out.append(("create_grid", prog(
        "живая проверка create_grid",
        {"op": "create_grid", "id": "GR", "p0_mm": [x(0), -8_000.0],
         "p1_mm": [x(0), 8_000.0], "name": "KIR_T1"}), "пулов не требует"))

    out.append(("create_window", prog(
        "живая проверка create_window (хост — своя же стена)",
        {"op": "create_wall", "id": "W", "p0_mm": [x(0), 0.0],
         "p1_mm": [x(6_000), 0.0], "level": eid(L01), "type": eid(WALL_TYPE),
         "height_mm": 3_000.0},
        {"op": "create_window", "id": "WIN", "host": ref("W"),
         "offset_mm": 3_000.0, "sill_mm": 900.0, "symbol": eid(WINDOW_SYM)}),
        "связка: окно по ref на свою стену"))

    out.append(("create_stairs", prog(
        "живая проверка create_stairs (единственный оп своей программы)",
        {"op": "create_stairs", "id": "ST", "p0_mm": [x(0), 12_000.0],
         "p1_mm": [x(4_000), 12_000.0], "base_level": eid(L01),
         "top_level": eid(L02), "width_mm": 1_200.0}),
        "StairsEditScope владеет транзакциями -> KIR-L002 при любом соседе"))

    out.append(("create_floor_by_contour", prog(
        "живая проверка create_floor_by_contour (подъязык CONTOUR)",
        {"op": "create_floor_by_contour", "id": "FC",
         "contour": {"outer": {"shape": "rect", "origin": [x(0), 20_000.0],
                               "size_mm": [5_000.0, 4_000.0]}},
         "level": eid(L01), "type": eid(FLOOR_TYPE)}),
        "единственный оп CONTOUR; обратный ход его не порождает"))

    out.append(("create_group", prog(
        "живая проверка create_group (нативная группа Revit)",
        {"op": "create_group", "id": "GRP",
         "members": [
             {"op": "create_wall", "id": "m1", "p0_mm": [x(0), 30_000.0],
              "p1_mm": [x(3_000), 30_000.0], "level": grounded(L01, "L_01_+0.000"),
              "type": grounded(WALL_TYPE, "ВН_Газобетон D600_200мм"),
              "height_mm": 2_800.0},
             {"op": "create_wall", "id": "m2", "p0_mm": [x(3_000), 30_000.0],
              "p1_mm": [x(3_000), 33_000.0], "level": grounded(L01, "L_01_+0.000"),
              "type": grounded(WALL_TYPE, "ВН_Газобетон D600_200мм"),
              "height_mm": 2_800.0},
         ],
         "placements": [[6_000.0, 0.0, 0.0]],
         "name": "KIR_TEST_GROUP"}),
        "члены PRE-GROUNDED; 1 определение + 1 размещение"))

    out.append(("set_param", prog(
        "живая проверка set_param (цель — своя же стена, не элемент оператора)",
        {"op": "create_wall", "id": "W2", "p0_mm": [x(0), 40_000.0],
         "p1_mm": [x(4_000), 40_000.0], "level": eid(L01),
         "type": eid(WALL_TYPE), "height_mm": 3_000.0},
        {"op": "set_param", "id": "SP", "target": ref("W2"),
         "param": "Марка", "value": "KIR-LIVE-TEST"}),
        "«Марка» проверена как строковый записываемый параметр стены"))

    out.append(("create_beam", prog(
        "живая проверка create_beam",
        {"op": "create_beam", "id": "BM", "p0_mm": [x(0), 50_000.0, 3_000.0],
         "p1_mm": [x(6_000), 50_000.0, 3_000.0], "level": eid(L01),
         "symbol": eid(BEAM_SYM)}), "beam_types: 36 типов в модели"))

    out.append(("create_foundation:slab", prog(
        "живая проверка create_foundation variety=slab",
        {"op": "create_foundation", "id": "FS", "variety": "slab",
         "outline": [[x(0), 60_000.0], [x(5_000), 60_000.0],
                     [x(5_000), 64_000.0], [x(0), 64_000.0]],
         "level": eid(L01), "type": eid(SLAB_TYPE)}),
        "путь create_floor со structural=true"))

    out.append(("create_foundation:isolated", prog(
        "живая проверка create_foundation variety=isolated",
        {"op": "create_foundation", "id": "FI", "variety": "isolated",
         "xy": [x(8_000), 60_000.0], "level": eid(L01)}),
        "foundation_symbols ПУСТ -> ожидается «не на чем»"))

    out.append(("create_pipe", prog(
        "живая проверка create_pipe",
        {"op": "create_pipe", "id": "PI", "p0_mm": [x(0), 70_000.0, 2_700.0],
         "p1_mm": [x(5_000), 70_000.0, 2_700.0], "level": eid(L01),
         "system_type": eid(PIPE_SYS), "pipe_type": eid(PIPE_TYPE),
         "diameter_mm": 100.0}), "типы есть, экземпляров MEP в модели нет"))

    out.append(("create_duct", prog(
        "живая проверка create_duct",
        {"op": "create_duct", "id": "DU", "p0_mm": [x(0), 74_000.0, 2_700.0],
         "p1_mm": [x(5_000), 74_000.0, 2_700.0], "level": eid(L01),
         "system_type": eid(DUCT_SYS), "duct_type": eid(DUCT_TYPE),
         "diameter_mm": 200.0}), "duct_types: три типа с ОДНИМ именем -> by id"))

    out.append(("create_cable_tray", prog(
        "живая проверка create_cable_tray",
        {"op": "create_cable_tray", "id": "CT",
         "p0_mm": [x(0), 78_000.0, 2_700.0],
         "p1_mm": [x(5_000), 78_000.0, 2_700.0], "level": eid(L01),
         "tray_type": eid(TRAY_TYPE)}), "cable_tray_types: 2"))

    # КОЛЛИНЕАРНАЯ цепочка: у типа трубы «По умолчанию» в этой модели нет
    # семейства отвода, поэтому любой поворот честно отказывает
    # «NewElbowFitting: failed to insert elbow (angle=90.0deg, 100.0/100.0mm)».
    # Это ограничение МОДЕЛИ, не опа: прямая цепочка проверяет сам оп.
    net_nodes = [
        {"id": "n0", "xyz_mm": [x(0), 82_000.0, 2_700.0]},
        {"id": "n1", "xyz_mm": [x(4_000), 82_000.0, 2_700.0]},
        {"id": "n2", "xyz_mm": [x(8_000), 82_000.0, 2_700.0]},
    ]
    net_segs = [{"from": "n0", "to": "n1"}, {"from": "n1", "to": "n2"}]

    out.append(("create_pipe_system", prog(
        "живая проверка create_pipe_system (граф ВК)",
        {"op": "create_pipe_system", "id": "PS", "nodes": net_nodes,
         "segments": net_segs, "level": eid(L01),
         "system_type": eid(PIPE_SYS), "pipe_type": eid(PIPE_TYPE),
         "diameter_mm": 100.0}), "связность по построению, фитинги по степени"))

    out.append(("route_pipe_system", prog(
        "живая проверка route_pipe_system",
        {"op": "route_pipe_system", "id": "RP",
         "nodes": [{"id": "a", "xyz_mm": [x(0), 90_000.0, 2_700.0]},
                   {"id": "b", "xyz_mm": [x(4_000), 90_000.0, 2_600.0]},
                   {"id": "c", "xyz_mm": [x(8_000), 90_000.0, 2_500.0]}],
         "segments": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
         "level": eid(L01),
         "system_type": eid(PIPE_SYS), "pipe_type": eid(PIPE_TYPE),
         "diameter_mm": 100.0}), "уклон — ПРОВЕРЯЕМОЕ постусловие, не генератор"))

    out.append(("route_duct_system", prog(
        "живая проверка route_duct_system",
        {"op": "route_duct_system", "id": "RD",
         "nodes": [{"id": "a", "xyz_mm": [x(0), 94_000.0, 2_700.0]},
                   {"id": "b", "xyz_mm": [x(4_000), 94_000.0, 2_700.0]},
                   {"id": "c", "xyz_mm": [x(8_000), 94_000.0, 2_700.0]}],
         "segments": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
         "level": eid(L01),
         "system_type": eid(DUCT_SYS), "duct_type": eid(DUCT_TYPE),
         "diameter_mm": 200.0}), "ОВ-зеркало route_pipe_system"))

    # ЗАМЕРЕНО 27.07: у вида 20905960 Origin == (0,0,0), Right == +X, Up == +Y,
    # а стены этого здания лежат по Y в 82 693 … 110 160 мм от начала вида.
    # `docspace._SHEET_LIMIT_MM` = 10 000 мм, и точка вида — это смещение ОТ
    # НАЧАЛА ВИДА в мм модели (`emit_view2d_to_xyz_cs`: Origin + u*Right +
    # v*Up, через U() = мм->футы). Значит НИ ОДИН элемент настоящего здания
    # аннотировать нельзя: цель заведомо дальше границы.
    # Поэтому точки ниже нарочно взяты ВНУТРИ границы — так проверяется
    # механика опа отдельно от границы. Сами цели остаются на +200 м.
    out.append(("create_text", prog(
        "живая проверка create_text (точка внутри границы ±10 м)",
        {"op": "create_text", "id": "TX", "in_view": eid(VIEW_PLAN),
         "at": [5_000.0, 5_000.0], "content": "KIR live test",
         "width_mm": 60.0}), "вид без подрезки; граница ±10м проверяется отдельно"))

    out.append(("create_tag", prog(
        "живая проверка create_tag (цель — своя же стена)",
        {"op": "create_wall", "id": "W3", "p0_mm": [x(0), 104_000.0],
         "p1_mm": [x(4_000), 104_000.0], "level": eid(L01),
         "type": eid(WALL_TYPE), "height_mm": 3_000.0},
        {"op": "create_tag", "id": "TG", "in_view": eid(VIEW_PLAN),
         "target": ref("W3"), "at": [6_000.0, 6_000.0], "leader": False}),
        "связка: марка на своей стене"))

    out.append(("create_dimension", prog(
        "живая проверка create_dimension (обе цели — свои же стены)",
        {"op": "create_wall", "id": "W4", "p0_mm": [x(0), 110_000.0],
         "p1_mm": [x(4_000), 110_000.0], "level": eid(L01),
         "type": eid(WALL_TYPE), "height_mm": 3_000.0},
        {"op": "create_wall", "id": "W5", "p0_mm": [x(0), 114_000.0],
         "p1_mm": [x(4_000), 114_000.0], "level": eid(L01),
         "type": eid(WALL_TYPE), "height_mm": 3_000.0},
        {"op": "create_dimension", "id": "DM", "in_view": eid(VIEW_PLAN),
         "refs": [ref("W4"), ref("W5")], "line_at": [7_000.0, 7_000.0]}),
        "связка: размер между двумя своими стенами"))

    out.append(("load_family", prog(
        "живая проверка load_family",
        {"op": "load_family", "id": "LF", "path": COLUMN_RFA}),
        "путь НАЙДЕН пробой ФС, не угадан"))

    out.append(("create_type", prog(
        "живая проверка create_type (после load_family)",
        {"op": "create_type", "id": "CT2",
         "source_type": {"by": "default"}, "category": "structural",
         "new_name": "KIR_TEST_TYPE_400x400", "width_mm": 400.0,
         "depth_mm": 400.0}),
        "column_symbols_structural ПУСТ, пока load_family не отработал"))

    return out


# ═══════════════════════════════════════════════════════════════════════════
# ПРОБЕЛ: 16 пишущих опов, которых живой Revit не касался ни разу
# ═══════════════════════════════════════════════════════════════════════════
# Замер (`gap_report()` ниже, прибором по реестру, а не по списку):
#   пишущих опов в реестре            37
#   гоняет базовый набор              21
#   не гоняет НИКТО                   16
# Базовый набор адресуется по element_id документа SOB6.2. Эти строки —
# наоборот: НИ ОДНОГО id чужой модели. Уровень строит `create_level` той же
# программы, носитель — `create_wall`/`create_floor` той же программы, ссылка
# идёт через `{"by":"ref"}` (ground.py, ветка `sel["by"] == "ref"`).
#
# ГЕОМЕТРИЯ ЖИВЁТ В СВОЁЙ ПОЛОСЕ. Базовые строки занимают Y 0…114 000 на
# уровне L01 оператора; эти — Y от GAP_Y0 и выше, каждая на СВОЁМ уровне из
# полосы GAP_ELEV0+. Так две матрицы не встречаются ни в плане, ни в разрезе.

GAP_Y0 = 150_000.0        # начало полосы Y для строк пробела
GAP_ELEV0 = 130_000.0     # начало полосы отметок для их собственных уровней
GAP_ELEV_STEP = 500.0


@dataclass(frozen=True)
class Row:
    """Одна строка матрицы: программа + чем доказывается её успех живьём."""

    name: str
    program: dict
    note: str
    #: Что ОБЯЗАНО сойтись, чтобы вердикт «СТРОИТ» что-то значил. Оператор
    #: читает это на устройстве вместо кода.
    success: str = "свидетель зелёный по всем трём осям"
    #: Имена строк, чьи созданные элементы нужны этой (через `dep(...)`).
    needs: tuple[str, ...] = ()
    #: Пулы, которые строка расходует — вход для фазы 0 (`--discover`).
    pools: tuple[str, ...] = ()
    #: Пометки об ограничениях (печатаются в плане).
    caveat: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


def dep(row_name: str, op_id: str) -> dict:
    """Селектор на элемент, созданный ДРУГОЙ программой матрицы.

    Нужен ровно там, где оп не может создать свою жертву сам:

    * `create_railing(variety=hosted)` требует лестницу, а `create_stairs`
      обязан быть ЕДИНСТВЕННЫМ опом своей программы (`spec.SOLO_OPS` /
      KIR-L002) — значит хост физически приходит из другой программы. Ветка
      `by:"ref"` в `_emit_railing_hosted` по этой же причине НЕДОСТИЖИМА:
      ссылаться внутри программы не на что.
    * `delete` / `move_elements` — здесь причина тоньше и была найдена
      эмиссией, а не рассуждением. Создать жертву в ТОЙ ЖЕ программе можно
      (`{"by":"ref"}` компилируется), но постусловия всех опов программы
      исполняются ПОСЛЕ всех создателей, одним блоком: свидетель стены
      прочитал бы `__el_W.Location` у элемента, который `delete` уже удалил,
      а после `move_elements` сверял бы концы с ДОПЕРЕНОСНЫМИ координатами и
      честно нашёл бы расхождение. То есть программа сама себе назначила бы
      провал. `change_type` этим не страдает (тип не двигает геометрию), но
      идёт тем же путём — жертва общая, и порядок один для всей семьи modify.
    """
    return {"__dep__": [row_name, op_id]}


def pick(key: str, pool: str, *, prefer: tuple[str, ...] = (),
         require: tuple[str, str] | None = None,
         exclude_categories: tuple[str, ...] = (), nth: int = 0) -> dict:
    """Выбор из пула документа: `--pin` -> каталог фазы 0 -> `{"by":"default"}`.

    `prefer` — образцы имени по убыванию предпочтения (регистронезависимая
    подстрока). `nth` — какой по счёту из отфильтрованных (по возрастанию id);
    нужен там, где программе нужны ДВА РАЗНЫХ элемента одного пула
    (`change_type`: тип «до» и тип «после» обязаны отличаться, иначе смена
    типа проходит как no-op и свидетель подтверждает пустоту).

    `require=(поле, значение)` — отбор по ПОЛЮ каталога, а не по имени.
    Ради `place_family`: держит ли типоразмер точку, не говорит ни имя, ни
    категория — только `FamilyPlacementType` (замер 04.08: `MullionType` id
    407 назывался «50 x 150 мм», категория OST_CurtainWallMullions, и точку
    проигнорировал). Отсутствие поля в каталоге — ОТКАЗ, а не «значит,
    подходит»: молча выбрать из пула, который не умеешь отфильтровать, —
    ровно тот слепой №0, из-за которого строка и падала.

    `exclude_categories` — категории `OST_*`, которые вычёркиваются.
    """
    return {"__pick__": {"key": key, "pool": pool, "prefer": list(prefer),
                         "require": list(require) if require else None,
                         "exclude_categories": list(exclude_categories),
                         "nth": nth}}


def gy(k: float) -> float:
    """Y в полосе строк пробела."""
    return GAP_Y0 + k


def build_gap_programs() -> list[Row]:
    """19 строк на 16 непокрытых опов. Одна программа доказывает ОДИН оп.

    Z — АБСОЛЮТНЫЙ, И ЭТО НЕ МЕЛОЧЬ. `position_mm` линии разрезки — «точка, через
    которую линия проходит, в МИРОВЫХ мм» (ops_authoring); углы `wall_rect` —
    тоже мировые («плоская точка молча уехала бы на отметку 0», ops_opening);
    `place_family.xyz` — мировой, эмиттер САМ вычитает `__lv.Elevation`.
    Базовая матрица этого не замечала, потому что её L01 стоит на отметке 0 и
    абсолютный Z там совпадает с относительным. У этих строк уровень СВОЙ и
    заведомо не нулевой — значит каждый Z обязан быть `elev + h`, иначе проём
    оказался бы на 130 м ниже своей стены. Отсюда `lvl()` возвращает ОТМЕТКУ,
    а не только оп: число, от которого считается высота, всегда под рукой.
    """
    out: list[Row] = []
    lv_n = 0

    def lvl(name: str) -> tuple[dict, float]:
        """Собственный уровень программы: (оп, его отметка в мм)."""
        nonlocal lv_n
        elev = GAP_ELEV0 + GAP_ELEV_STEP * lv_n
        lv_n += 1
        return ({"op": "create_level", "id": "LV", "elev_mm": elev,
                 "name": f"KIR_GAP_{name}"}, elev)

    def wall(oid: str, y: float, x0: float, x1: float,
             type_sel: dict | None = None, h: float = 3_000.0) -> dict:
        op = {"op": "create_wall", "id": oid, "p0_mm": [x(x0), y],
              "p1_mm": [x(x1), y], "level": ref("LV"), "height_mm": h}
        if type_sel is not None:
            op["type"] = type_sel
        return op

    # ── 1. Перекрытие ────────────────────────────────────────────────────
    lv, elev = lvl("FLOOR")
    out.append(Row(
        "create_floor",
        prog("create_floor на СВОЁМ уровне, тип — умолчание документа", lv,
             {"op": "create_floor", "id": "FL",
              "outline": [[x(0), gy(0)], [x(5_000), gy(0)],
                          [x(5_000), gy(4_000)], [x(0), gy(4_000)]],
              "level": ref("LV")}),
        note="тип опущен -> ground отдаёт doc_default (ветка "
             "create_wall/floor/roof/floor_by_contour) — пул не нужен",
        success="FL: bbox XY == контур ±50мм; привязка к СВОЕМУ уровню "
                "(topology); structural=false"))

    # ── 2. Кровля ────────────────────────────────────────────────────────
    lv, elev = lvl("ROOF")
    out.append(Row(
        "create_roof",
        prog("create_roof на СВОЁМ уровне", lv,
             {"op": "create_roof", "id": "RF",
              "outline": [[x(0), gy(6_000)], [x(5_000), gy(6_000)],
                          [x(5_000), gy(10_000)], [x(0), gy(10_000)]],
              "level": ref("LV")}),
        note="footprint-кровля; тип опущен -> doc_default",
        success="RF: базовый уровень == свой (topology); bbox XY == контур "
                "±50мм"))

    # ── 3. Потолок ───────────────────────────────────────────────────────
    lv, elev = lvl("CEIL")
    out.append(Row(
        "create_ceiling",
        prog("create_ceiling на СВОЁМ уровне", lv,
             {"op": "create_ceiling", "id": "CL",
              "outline": [[x(0), gy(12_000)], [x(4_000), gy(12_000)],
                          [x(4_000), gy(15_000)], [x(0), gy(15_000)]],
              "level": ref("LV"), "height_offset_mm": 2_700.0,
              "type": pick("ceiling_type", "ceiling_types")}),
        note="Ceiling.Create есть только с 2022; на 2021 оп ОТКАЗЫВАЕТ "
             "типизированно (KIR-E003) — это исправность, а не провал. "
             "height_offset_mm — смещение ОТ УРОВНЯ, а не мировой Z",
        success="CL: bbox XY ±50мм; уровень (topology); смещение 2700 ±1мм",
        pools=("ceiling_types",),
        caveat="`ceiling_types` НЕТ в enum пула query_types — фаза 0 его не "
               "видит. Только --pin ceiling_type=<id> или автоподбор KIR-G102"))

    # ── 4. Колонна ───────────────────────────────────────────────────────
    lv, elev = lvl("COL")
    out.append(Row(
        "create_column",
        prog("create_column на СВОЁМ уровне", lv,
             {"op": "create_column", "id": "CO", "xy": [x(0), gy(18_000)],
              "level": ref("LV"), "category": "structural",
              "symbol": pick("column_symbol", "column_symbols_structural")}),
        note="типоразмер колонны создать нечем — он обязан лежать в документе; "
             "top_level опущен намеренно: это значит «не привязывать верх», а "
             "не «взять единственный уровень»",
        success="CO: LocationPoint == xy ±5мм; StructuralType соответствует "
                "category (semantic); базовый уровень == свой (topology)",
        pools=("column_symbols_structural",)))

    # ── 5. Дверь ─────────────────────────────────────────────────────────
    lv, elev = lvl("DOOR")
    out.append(Row(
        "create_door",
        prog("create_door в СВОЮ ЖЕ стену", lv,
             wall("W", gy(22_000), 0, 6_000),
             {"op": "create_door", "id": "DR", "host": ref("W"),
              "offset_mm": 3_000.0, "sill_mm": 0.0,
              "symbol": pick("door_symbol", "door_symbols")}),
        note="связка: носитель — своя стена по ref, чтобы НИКОГДА не целить в "
             "стену оператора. sill_mm отсчитывается ОТ УРОВНЯ носителя",
        success="DR: Host.Id == id своей стены (topology); точка == "
                "p0+dir*3000 на уровне+порог ±10мм (geometry)",
        pools=("door_symbols",)))

    # ── 6. Помещение ─────────────────────────────────────────────────────
    # Помещению нужен ЗАМКНУТЫЙ контур: иначе Revit создаёт помещение с
    # нулевой площадью, и свидетель «room is not enclosed» это честно ловит.
    # Четыре стены — минимум, который даёт ему сойтись.
    lv, elev = lvl("ROOM")
    out.append(Row(
        "create_room",
        prog("create_room внутри СВОИХ ЖЕ четырёх стен", lv,
             {"op": "create_wall", "id": "W1", "p0_mm": [x(0), gy(26_000)],
              "p1_mm": [x(4_000), gy(26_000)], "level": ref("LV"),
              "height_mm": 3_000.0},
             {"op": "create_wall", "id": "W2", "p0_mm": [x(4_000), gy(26_000)],
              "p1_mm": [x(4_000), gy(29_000)], "level": ref("LV"),
              "height_mm": 3_000.0},
             {"op": "create_wall", "id": "W3", "p0_mm": [x(4_000), gy(29_000)],
              "p1_mm": [x(0), gy(29_000)], "level": ref("LV"),
              "height_mm": 3_000.0},
             {"op": "create_wall", "id": "W4", "p0_mm": [x(0), gy(29_000)],
              "p1_mm": [x(0), gy(26_000)], "level": ref("LV"),
              "height_mm": 3_000.0},
             {"op": "create_room", "id": "RM", "xy": [x(2_000), gy(27_500)],
              "level": ref("LV"), "name": "KIR_GAP_ROOM_1"}),
        note="6 опов при бюджете 20; эмиттер сам зовёт doc.Regenerate() перед "
             "NewRoom — «v0 rule» в его же коде",
        success="RM: площадь ненулевая (свидетель «room is not enclosed» НЕ "
                "сработал); LevelId == свой; точка ±5мм; имя == "
                "KIR_GAP_ROOM_1"))

    # ── 7. Разделитель помещений ─────────────────────────────────────────
    lv, elev = lvl("SEP")
    out.append(Row(
        "create_room_separator",
        prog("create_room_separator на СВОЁМ уровне", lv,
             {"op": "create_room_separator", "id": "RS",
              "path": [[x(0), gy(32_000)], [x(4_000), gy(32_000)],
                       [x(4_000), gy(35_000)]],
              "level": ref("LV")}),
        note="три точки -> ДВА сегмента: счёт сегментов сам по себе "
             "постусловие (identity), поэтому ломаная, а не отрезок. Путь "
             "плоский, отметку берёт эмиттер из MM(__lv.Elevation) в рантайме",
        success="RS: сегментов ровно 2 (identity); каждый в категории "
                "OST_RoomSeparationLines, а не в модельных линиях (topology); "
                "уровень у каждого; концы == соседние точки пути ±5мм",
        caveat="ГРАНИЦА, ЗАМЕРЕНА ЖИВЬЁМ 04.08, И ОП ЗДЕСЬ ПРАВ. На своём "
               "свежем уровне строка отказывает: «у разрешённого уровня нет "
               "ни одного плана этажа (не шаблона), а NewRoomBoundaryLines "
               "требует вид». Причина — `Level.Create` НЕ создаёт плана: "
               "перепись «Проект1» показала планов=0 у ВСЕХ одиннадцати "
               "KIR_GAP_* уровней и планов>=1 у всех собственных уровней "
               "документа. Та же программа на уровне 355 «Уровень 1» (3 "
               "плана) построилась: ok:true, три оси зелёные, сегментов 2, "
               "вид 356. Подставить чужой план значило бы нарисовать границу "
               "не на том этаже — оп отказывает правильно. Закрыть это может "
               "только оп создания вида: в реестре его НЕТ ни одного (замер "
               "04.08: 37 пишущих опов, ни одного view/plan)"))

    # ── 8/9. Проём — две взятые разновидности из четырёх ─────────────────
    lv, elev = lvl("OPW")
    out.append(Row(
        "create_opening:wall_rect",
        prog("create_opening variety=wall_rect в СВОЕЙ ЖЕ стене", lv,
             wall("W", gy(38_000), 0, 6_000),
             {"op": "create_opening", "id": "OP", "variety": "wall_rect",
              "host": ref("W"),
              "p0_mm": [x(1_500), gy(38_000), elev + 900.0],
              "p1_mm": [x(3_500), gy(38_000), elev + 2_400.0]}),
        note="углы проёма — МИРОВЫЕ мм, поэтому Z считается от отметки своего "
             "уровня. shaft и framing НЕ взяты осознанно (ops_opening."
             "VARIETIES_NOT_TAKEN) — их отказ KIR-E007 тоже исправность",
        success="OP: Opening.Host == своя стена (topology); граница "
                "прямоугольная; Z-полоса (уровень+900 … уровень+2400) и "
                "ширина 2000 вдоль стены ±50мм (сдвиг вдоль стены НЕ "
                "закреплён намеренно)"))

    lv, elev = lvl("OPF")
    out.append(Row(
        "create_opening:host_face",
        prog("create_opening variety=host_face в СВОЁМ ЖЕ перекрытии", lv,
             {"op": "create_floor", "id": "FL",
              "outline": [[x(0), gy(42_000)], [x(6_000), gy(42_000)],
                          [x(6_000), gy(46_000)], [x(0), gy(46_000)]],
              "level": ref("LV")},
             {"op": "create_opening", "id": "OP", "variety": "host_face",
              "host": ref("FL"), "cut": "vertical",
              "outline": [[x(2_000), gy(43_000)], [x(4_000), gy(43_000)],
                          [x(4_000), gy(45_000)], [x(2_000), gy(45_000)]]}),
        note="носитель — своё перекрытие; контур плоский (эмиттер сам берёт "
             "середину габарита носителя по Z), рез вертикальный, поэтому "
             "габарит границы сверяется НА РАВЕНСТВО, а не на вложение",
        success="OP: Opening.Host == своё перекрытие (topology); габарит "
                "BoundaryCurves == контур ±50мм"))

    # ── 10/11. Ограждение — обе разновидности ────────────────────────────
    lv, elev = lvl("RAIL")
    out.append(Row(
        "create_railing:path",
        prog("create_railing variety=path на СВОЁМ уровне", lv,
             {"op": "create_railing", "id": "RL", "variety": "path",
              "path": [[x(0), gy(50_000)], [x(4_000), gy(50_000)],
                       [x(4_000), gy(52_000)]],
              "level": ref("LV"),
              "type": pick("railing_type", "railing_types")}),
        note="путь ОТКРЫТЫЙ — замыкающего сегмента оп не добавляет, и "
             "свидетель габарита это проверяет",
        success="RL: STAIRS_RAILING_BASE_LEVEL_PARAM == свой уровень "
                "(topology); bbox == габарит пути ±50мм",
        pools=("railing_types",),
        caveat="ДВЕ оговорки. (1) `railing_types` НЕТ в enum query_types — "
               "только --pin railing_type=<id> или автоподбор KIR-G102. "
               "(2) ГЛАЗАМИ ПРОВЕРИТЬ ОТМЕТКУ: эмиттер строит CurveLoop с "
               "Z=0 жёстко (arch_emit._path_pts, умолчание z=\"0\"), а "
               "свидетель сверяет ТОЛЬКО габарит XY. Сторона чтения "
               "утверждает, что Revit кладёт путь НА УРОВЕНЬ (lift.py, замер "
               "K2: у всех 28 ограждений plane_z == отметке уровня) — это "
               "первая проверка утверждения на уровне ВЫШЕ нуля. Ограждение "
               "на отметке 0 вместо KIR_GAP_RAIL прошло бы свидетеля молча"))

    # ── 10b/11b. Лестница: САМОДОСТАТОЧНАЯ пара строк ────────────────────
    #
    # ЗАЧЕМ ВТОРАЯ СТРОКА ЛЕСТНИЦЫ. Базовая (`build_programs`) адресует уровни
    # SOB6.2 по element_id (L01=172458 / L02=975727). На «Проект1» их нет, и
    # прогон 04.08 честно вернул `KIR-X003: base_level: уровень не найден` —
    # ЭТО БЫЛ ДЕФЕКТ МАТРИЦЫ, А НЕ ОПА. Проверено живьём в тот же день:
    # уровни своей программой -> лестница СОЛО на них -> ok:true, свидетель
    # зелёный по трём осям, 1 марш, 17 подступенков, ширина марша 1200.00 мм
    # при запрошенных 1200 (элемент 287095 в «Проект1»).
    #
    # Уровни ОБЯЗАНЫ приходить из другой программы: `create_stairs` —
    # единственный оп своей (KIR-L002, StairsEditScope владеет транзакциями),
    # поэтому `create_level` рядом с ним незаконен. Отсюда пара «фикстура +
    # соло», а не одна программа.
    ST_BASE_ELEV = 145_000.0
    ST_TOP_ELEV = 148_000.0
    out.append(Row(
        "stairs_fixture",
        prog("предшественник лестницы: два уровня отдельной программой",
             {"op": "create_level", "id": "L1", "elev_mm": ST_BASE_ELEV,
              "name": "KIR_GAP_ST_BASE"},
             {"op": "create_level", "id": "L2", "elev_mm": ST_TOP_ELEV,
              "name": "KIR_GAP_ST_TOP"}),
        note="лестнице нужны ДВА уровня, а сама она их создать не может: оп "
             "СОЛО (KIR-L002). Отметки вынесены выше полосы GAP_ELEV0, чтобы "
             "не столкнуться ни с одним уровнем других строк",
        success="L1/L2: отметки 145000/148000 ±1мм, имена KIR_GAP_ST_*",
        tags=("fixture",)))

    out.append(Row(
        "create_stairs:standalone",
        prog("create_stairs СОЛО на уровнях строки stairs_fixture",
             {"op": "create_stairs", "id": "ST",
              "p0_mm": [x(0), gy(54_000)], "p1_mm": [x(4_000), gy(54_000)],
              "base_level": dep("stairs_fixture", "L1"),
              "top_level": dep("stairs_fixture", "L2"),
              "width_mm": 1_200.0}),
        note="САМОДОСТАТОЧНАЯ лестница: ни одного id чужой модели. Базовая "
             "строка create_stairs остаётся как есть — она доказательство, "
             "снятое на SOB6.2, и на другом документе законно отказывает",
        success="ST: base/top level == уровни фикстуры (topology); маршей "
                ">=1; ширина марша == 1200 ±5мм",
        needs=("stairs_fixture",)))

    out.append(Row(
        "create_railing:hosted",
        prog("create_railing variety=hosted на лестнице строки "
             "create_stairs:standalone",
             {"op": "create_railing", "id": "RH", "variety": "hosted",
              "host": dep("create_stairs:standalone", "ST"),
              "position": "treads",
              "type": pick("railing_type", "railing_types")}),
        note="ЕДИНСТВЕННАЯ строка, которой предшественник нужен ПО ЗАКОНУ: "
             "хост-лестница обязана быть в отдельной программе (KIR-L002), "
             "поэтому ref внутри программы физически невозможен — и ветка "
             "by:\"ref\" в _emit_railing_hosted по той же причине недостижима",
        success="RH: КАЖДОЕ созданное ограждение имеет HasHost и HostId == "
                "id лестницы (topology). Перегрузка возвращает КОЛЛЕКЦИЮ — "
                "у марша ограждение может встать с двух сторон",
        needs=("create_stairs:standalone",),
        pools=("railing_types",),
        caveat="ГРАНИЦА REVIT, ЗАМЕРЕНА ЖИВЬЁМ 04.08. На свежепостроенной "
               "лестнице ограждения УЖЕ ЕСТЬ: StairsEditScope создаёт их сам "
               "(на 287095 их оказалось два, тип «Труба 900 мм», HostId == "
               "лестница). Railing.Create после этого отказывает дословно: "
               "«The stairsOrRampId already has associated railings or is in "
               "editing mode so association of railings is not permitted». "
               "Значит вариант hosted проверяем ТОЛЬКО на лестнице без "
               "ограждений — своей у матрицы такой нет, и это надо назвать, "
               "а не чинить. Отказ приезжает как KIR-X999 "
               "(неклассифицированный) — типизировать его отдельной работой"))

    # ── 12. Произвольная геометрия ───────────────────────────────────────
    out.append(Row(
        "create_directshape",
        prog("create_directshape — тетраэдр; из документа не нужно НИЧЕГО",
             {"op": "create_directshape", "id": "DS",
              "mesh": {"vertices_mm": [
                  [x(0), gy(56_000), 0.0],
                  [x(2_000), gy(56_000), 0.0],
                  [x(1_000), gy(58_000), 0.0],
                  [x(1_000), gy(57_000), 2_000.0]],
                  "triangles": [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]},
              "category": "generic_model", "name": "KIR_GAP_DS"}),
        note="единственная строка без уровня и без типа вовсе: настоящая "
             "проверка «пустой документ — единственное допущение». Уровня у "
             "DirectShape нет, поэтому Z остаётся мировым и нулевым",
        success="DS: bbox == габарит вершин ±5мм; построено ровно 4 "
                "треугольника (geometry)"))

    # ── 13/14. Витраж: линия разрезки и панель ───────────────────────────
    # Носитель обязан быть ВИТРАЖНОЙ стеной: у обычной CurtainGrid == null.
    # Отличить её в каталоге можно только по имени — отсюда `prefer`.
    curtain = pick("curtain_wall_type", "wall_types",
                   prefer=("витраж", "curtain", "навесн"))
    lv, elev = lvl("CGL")
    out.append(Row(
        "create_curtain_grid_line",
        prog("create_curtain_grid_line на СВОЕЙ ЖЕ витражной стене", lv,
             wall("W", gy(62_000), 0, 6_000, type_sel=curtain),
             {"op": "create_curtain_grid_line", "id": "GL", "host": ref("W"),
              "direction": "u",
              "position_mm": [x(3_000), gy(62_000), elev + 1_500.0]}),
        note="position_mm — точка в МИРОВЫХ мм, через которую проходит линия, "
             "поэтому Z берётся от отметки своего уровня, а не от нуля. "
             "Направление у AddGridLine булево, и перепутанная ветка не видна "
             "ничем, кроме живой модели",
        success="GL: линия состоит в GetUGridLineIds носителя — ЧТЕНИЕ "
                "МОДЕЛИ, не эхо вызова (topology); IsUGridLine == u "
                "(semantic); запрошенная точка лежит на FullCurve ±25мм",
        pools=("wall_types",),
        caveat="нужен ВИТРАЖНЫЙ тип стены; имена ищутся по образцам "
               "витраж/curtain/навесн — иначе --pin curtain_wall_type=<id>"))

    lv, elev = lvl("CP")
    out.append(Row(
        "set_curtain_panel",
        prog("set_curtain_panel в ячейку (0,0) СВОЕЙ ЖЕ витражной стены", lv,
             wall("W", gy(66_000), 0, 6_000, type_sel=curtain),
             {"op": "set_curtain_panel", "id": "CP", "host": ref("W"),
              "u": 0, "v": 0,
              "panel_type": pick("panel_type", "wall_types")}),
        note="адрес (0,0) — не «пустой», а сетка 1×1: тот самый частный "
             "случай, который дизайн запретил считать оправданием отсутствия "
             "адреса. Тип панели ищется эмиттером по ДВУМ пространствам типов "
             "(панели + стены), поэтому обычный тип стены годится",
        success="CP: тип в ячейке (0,0) == запрошенный, перечитанный ПО "
                "АДРЕСУ ЯЧЕЙКИ, а не по эху вызова (semantic); хозяин ячейки "
                "== носитель (topology)",
        pools=("wall_types",),
        caveat="тот же витражный тип стены, что и у create_curtain_grid_line"))

    # ── 15. Размещение семейства ─────────────────────────────────────────
    lv, elev = lvl("PF")
    out.append(Row(
        "place_family",
        prog("place_family на СВОЁМ уровне", lv,
             {"op": "place_family", "id": "PF",
              "xyz": [x(0), gy(70_000), elev], "level": ref("LV"),
              "symbol": pick("family_symbol", "family_symbols",
                             require=("placement", "OneLevelBased"),
                             exclude_categories=("OST_CurtainWallMullions",
                                                 "OST_CurtainWallPanels"))}),
        note="xyz МИРОВОЙ: эмиттер сам вычитает __lv.Elevation из Z, поэтому "
             "z == отметке уровня ставит экземпляр НА свой уровень, а не на "
             "130 м ниже него. Точечный вариант; кривой (p0_mm/p1_mm) уровня "
             "не имеет вовсе — у 79 кожухов ЭОМ LevelId = -1, это замер",
        success="PF: LocationPoint == xyz ±5мм; привязка к уровню по "
                "BIP-цепочке == свой уровень (topology)",
        pools=("family_symbols",),
        caveat="ПОЧЕМУ ВЫЧЁРКИВАНИЕ ПО КАТЕГОРИИ, А НЕ ВЫБОР №0. Прогон "
               "04.08 дал `KIR-X004: PF: location mismatch (geometry)` — и "
               "это был ВЕРНЫЙ КРАСНЫЙ: каталог отдал №0 = id 407 «50 x 150 "
               "мм», а живьём это `MullionType` категории "
               "OST_CurtainWallMullions. Проба на устройстве (транзакция "
               "откачена), одна и та же точка (200000,290000,0): 407 -> "
               "LocationPoint (0,0,0), точка ПРОИГНОРИРОВАНА; 4275 "
               "«Строительный прицеп», 132630 «Опора», 1214 «Балясина» -> "
               "ровно запрошенная точка; 5290 «Системная панель» -> "
               "LocationPoint == null. Подкомпоненты витражной сетки "
               "объявляют FamilyPlacementType.OneLevelBased, но точку не "
               "держат: они живут ЯЧЕЙКОЙ, а не координатой. Отбор идёт по "
               "`FamilyPlacementType` — по имени нельзя (407 назывался «50 x "
               "150 мм»), по категории мало (следующим №0 оказался "
               "OST_CalloutHeads, а это ViewBased-аннотация). Поле "
               "`placement` добавлено в `query_types` 04.08; фаза 0 матрицы "
               "до того выбрасывала и category — это был наш дефект в ДВУХ "
               "местах, а не пробел реестра"))

    # ── 16. Предшественник для семьи modify ──────────────────────────────
    type_a = pick("wall_type_a", "wall_types", nth=0)
    lv, elev = lvl("FIX")
    out.append(Row(
        "modify_fixture",
        prog("предшественник: три стены-жертвы для delete/move/change_type", lv,
             wall("WD", gy(74_000), 0, 4_000),
             wall("WM", gy(76_000), 0, 4_000),
             wall("WC", gy(78_000), 0, 4_000, type_sel=type_a)),
        note="ОДНА программа на три зависимые, и у каждой СВОЯ жертва: "
             "delete -> WD, move_elements -> WM, change_type -> WC",
        success="WD/WM/WC: концы ±5мм, высота ±1мм, привязка к своему уровню. "
                "Дальше их id уходят в delete/move_elements/change_type",
        pools=("wall_types",),
        tags=("fixture",)))

    out.append(Row(
        "delete",
        prog("delete стены, созданной программой modify_fixture",
             {"op": "delete", "id": "DL", "target": dep("modify_fixture", "WD")},
             destructive=True),
        note="конверт allow_destructive=true обязателен (SPEC 12.2); цель — "
             "наша же стена, не элемент оператора",
        success="DL: doc.GetElement(id) == null после Delete. Повторный "
                "прогон обязан дать типизированный отказ «элемент не найден», "
                "а не исключение",
        needs=("modify_fixture",)))

    out.append(Row(
        "move_elements",
        prog("move_elements: перенос стены из modify_fixture на +1000 по X",
             {"op": "move_elements", "id": "MV",
              "targets": [dep("modify_fixture", "WM")],
              "delta_mm": [1_000.0, 0.0, 0.0]}),
        note="снимок «до» берётся ВНУТРИ программы, поэтому сдвиг проверяем "
             "без знания исходных координат",
        success="MV: у цели с LocationCurve оба конца сдвинуты ровно на "
                "delta ±1мм (geometry); суммарное число ПОДКЛЮЧЁННЫХ "
                "коннекторов не изменилось (topology); наклон не изменился "
                "(semantic, перечитан, а не принят на веру)",
        needs=("modify_fixture",)))

    out.append(Row(
        "change_type",
        prog("change_type стены из modify_fixture на ДРУГОЙ тип",
             {"op": "change_type", "id": "CT",
              "target": dep("modify_fixture", "WC"),
              "type": pick("wall_type_b", "wall_types", nth=1)}),
        note="тип «после» обязан отличаться от типа «до» (nth=0 против "
             "nth=1): смена типа на тот же — no-op, и свидетель подтвердил бы "
             "пустоту. Нужно >=2 типа стен в документе",
        success="CT: GetTypeId() == запрошенный ПОСЛЕ Regenerate, перечитанный "
                "с ВОЗВРАЩЁННОГО id (обычный случай — InvalidElementId и тот "
                "же элемент; новый элемент Revit создаёт лишь при переходе "
                "стена<->витражная панель)",
        needs=("modify_fixture",),
        pools=("wall_types",)))

    return out



# ═══════════════════════════════════════════════════════════════════════════
# Замер пробела: прибором по реестру, а не по памяти
# ═══════════════════════════════════════════════════════════════════════════

def _ops_in(node, acc: set) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("op"), str):
            acc.add(node["op"])
        for v in node.values():
            _ops_in(v, acc)
    elif isinstance(node, list):
        for v in node:
            _ops_in(v, acc)


def gap_report() -> dict:
    """Какие пишущие опы реестра НЕ гоняет ни одна строка матрицы.

    Считает по ОПАМ ВНУТРИ ПРОГРАММ, а не по именам строк: `create_wall`
    нигде не заголовок, но живёт носителем в четырёх базовых строках — по
    именам он выглядел бы непокрытым, и это ровно та ошибка, которой стоит
    остерегаться («не упомянут» ≠ «не покрыт»).
    """
    from kukai.ir import spec

    writes = {n for n, o in spec.OPS.items() if o.writes_model}
    base, gap = set(), set()
    for _, program, _ in build_programs():
        _ops_in(program, base)
    for row in build_gap_programs():
        _ops_in(row.program, gap)
    return {
        "write_ops": sorted(writes),
        "base": sorted(writes & base),
        "gap_rows": sorted(writes & gap),
        "still_uncovered": sorted(writes - base - gap),
        "non_write_seen": sorted((base | gap) - writes),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Разрешение плейсхолдеров: pick(...) из каталога, dep(...) из прошлых строк
# ═══════════════════════════════════════════════════════════════════════════

class Unresolved(Exception):
    """Строка не может быть собрана: нечем назвать выбор или нет жертвы."""


def _walk(node, fn):
    """Скопировать дерево, отдав fn каждый dict; None от fn = «не мой»."""
    if isinstance(node, dict):
        got = fn(node)
        if got is not None:
            return got
        return {k: _walk(v, fn) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, fn) for v in node]
    return node


def resolve_picks(program: dict, catalogue: dict | None, pins: dict,
                  chosen: dict) -> dict:
    """Заменить `pick(...)` конкретным селектором. Выбор пишется в `chosen`."""

    def one(node):
        spec_ = node.get("__pick__")
        if spec_ is None:
            return None
        key, pool = spec_["key"], spec_["pool"]
        if key in pins:
            chosen[key] = {"via": "--pin", "pool": pool, "id": pins[key]}
            return {"by": "element_id", "value": pins[key]}
        drop_cats = spec_.get("exclude_categories") or []
        need = spec_.get("require")
        rows = (catalogue or {}).get(pool)
        if not rows:
            if spec_["prefer"] or drop_cats or need or spec_["nth"]:
                raise Unresolved(
                    f"{key}: нужен каталог пула {pool} "
                    f"(--discover) или --pin {key}=<element_id>")
            chosen[key] = {"via": "by:default", "pool": pool}
            return {"by": "default"}
        pool_rows = sorted(rows, key=lambda r: int(r["id"]))

        def by_field(field: str, keep) -> None:
            # Каталог БЕЗ поля — не «значит, всё подходит», а ОТКАЗ: молча
            # выбрать из пула, который не умеешь отфильтровать, значит
            # вернуть тот самый слепой №0.
            nonlocal pool_rows
            blind = [r for r in pool_rows if field not in r]
            if blind:
                raise Unresolved(
                    f"{key}: в каталоге пула {pool} нет поля `{field}` "
                    f"({len(blind)} из {len(pool_rows)} строк) — пересними "
                    f"фазу 0 (--discover) или назови выбор: "
                    f"--pin {key}=<element_id>")
            kept = [r for r in pool_rows if keep(r)]
            if not kept:
                raise Unresolved(
                    f"{key}: в пуле {pool} ({len(pool_rows)} шт.) после "
                    f"отбора по `{field}` не осталось ничего — назови явно: "
                    f"--pin {key}=<element_id>")
            pool_rows = kept

        if need:
            by_field(need[0], lambda r, n=need: r.get(n[0]) == n[1])
        if drop_cats:
            by_field("category",
                     lambda r, d=drop_cats: r.get("category") not in d)
        picked = pool_rows
        for pat in spec_["prefer"]:
            hit = [r for r in pool_rows
                   if pat.lower() in str(r.get("name", "")).lower()]
            if hit:
                picked = hit
                break
        else:
            if spec_["prefer"]:
                raise Unresolved(
                    f"{key}: в пуле {pool} ({len(pool_rows)} шт.) ни одно имя "
                    f"не похоже на {spec_['prefer']} — назови явно: "
                    f"--pin {key}=<element_id>")
        if spec_["nth"] >= len(picked):
            raise Unresolved(
                f"{key}: в пуле {pool} после отбора {len(picked)} записей, "
                f"а нужна №{spec_['nth'] + 1} — назови явно: --pin {key}=<id>")
        row = picked[spec_["nth"]]
        via = f"каталог {pool}#{spec_['nth']}"
        if need:
            via += f" ({need[0]}=={need[1]})"
        if drop_cats:
            via += f" (вычеркнуты категории {drop_cats})"
        chosen[key] = {"via": via, "pool": pool, "id": int(row["id"]),
                       "name": row.get("name"),
                       "category": row.get("category"),
                       "family_name": row.get("family_name"),
                       "placement": row.get("placement")}
        return {"by": "element_id", "value": int(row["id"])}

    return _walk(program, one)


def resolve_deps(program: dict, produced: dict) -> dict:
    """Заменить `dep(...)` id элемента, созданного прошлой строкой."""

    def one(node):
        spec_ = node.get("__dep__")
        if spec_ is None:
            return None
        row_name, op_id = spec_
        got = (produced.get(row_name) or {}).get(op_id)
        if got is None:
            raise Unresolved(
                f"нужен элемент {op_id!r} строки {row_name!r}, а она не дала "
                f"id (не запускалась, отказала или её результат пуст)")
        return {"by": "element_id", "value": int(got)}

    return _walk(program, one)


def exec_payload(reply: dict) -> dict:
    """`__results` программы из ответа.

    Разворачивается ДО ТРЁХ уровней `"result"`: serving кладёт в
    `out_result["result"]` СЫРОЙ `exec_res` моста, а тот сам бывает обёрнут
    (`serving._payload = exec_res.get("result", exec_res)` — тот же приём).
    Разворачивать ровно один уровень значит угадывать глубину; здесь она
    ищется, и поиск останавливается на первом словаре, который уже не
    матрёшка.
    """
    kir = reply.get("kir") if isinstance(reply.get("kir"), dict) else {}
    payload = kir.get("result")
    for _ in range(3):
        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            payload = payload["result"]
        else:
            break
    return payload if isinstance(payload, dict) else {}


def created_ids(reply: dict) -> dict:
    """id, созданные программой: `__results[op_id]["id"]` из квитанции."""
    payload = exec_payload(reply)
    if not payload:
        return {}
    out = {}
    for op_id, rec in payload.items():
        if isinstance(rec, dict):
            raw = rec.get("id") or rec.get("deleted_id")
            if raw is not None:
                try:
                    out[op_id] = int(str(raw))
                except ValueError:
                    pass
            ids = rec.get("ids")
            if isinstance(ids, list) and ids:
                try:
                    out[op_id] = int(str(ids[0]))
                except ValueError:
                    pass
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Фаза 0: разведка каталога тем же прод-путём (оп query_types)
# ═══════════════════════════════════════════════════════════════════════════

#: Пулы, которые `query_types` УМЕЕТ (замерено по его enum, не по памяти).
QUERY_TYPES_POOLS = frozenset({
    "levels", "wall_types", "floor_types", "roof_types", "pipe_types",
    "piping_system_types", "duct_types", "duct_system_types",
    "cable_tray_types", "column_symbols_structural",
    "column_symbols_architectural", "window_symbols", "door_symbols",
    "family_symbols", "beam_types", "foundation_symbols"})


def needed_pools(rows: list[Row]) -> list[str]:
    return sorted({p for r in rows for p in r.pools})


def discover(token: str, doc: str, pools: list[str],
             timeout_ms: int) -> tuple[dict, list[str]]:
    """Прочитать пулы живого документа. Возвращает (каталог, недоступные)."""
    catalogue: dict[str, list] = {}
    blind: list[str] = []
    for pool in pools:
        if pool not in QUERY_TYPES_POOLS:
            blind.append(pool)
            continue
        reply = run_one(token, doc, {
            "ir_version": "1.0", "intent": f"разведка пула {pool}",
            "ops": [{"op": "query_types", "id": "Q", "pool": pool}]},
            timeout_ms)
        # Форма ответа замерена по эмиссии, а не угадана:
        # `__results["Q"] = {pool, total, rows:[{id, name}]}`, и `id` там —
        # СТРОКА (`__e.Id.ToString()`, единственная идиома, живая на всех
        # шести версиях).
        payload = exec_payload(reply)
        rows = None
        if isinstance(payload.get("Q"), dict):
            rows = payload["Q"].get("rows")
        if rows is None:
            rows = payload.get("rows")
        if isinstance(rows, list) and rows:
            # ВСЕ поля строки, а не {id, name}. `query_types` для пула
            # `family_symbols` отдаёт ещё `category`/`family_name`/`type_name`
            # (compiler._emit_op, ветка family_fields) — и именно КАТЕГОРИЯ
            # отличает точечное семейство от подкомпонента витражной сетки.
            # Раньше каталог их выбрасывал, и выбор №0 был слеп НЕ по вине
            # реестра, а по вине этой строки: замер 04.08 привёл матрицу к
            # `MullionType` id 407 «50 x 150 мм», чьё ИМЯ о категории не
            # говорит ничего.
            catalogue[pool] = [
                dict(r, id=int(str(r["id"])), name=r.get("name"))
                for r in rows
                if isinstance(r, dict) and r.get("id") is not None]
            print(f"  {pool:32s} {len(catalogue[pool]):4d}")
        else:
            print(f"  {pool:32s}    — пусто/не прочитан: "
                  f"{str(reply)[:120]}")
    return catalogue, blind


def run_one(token: str, doc: str, program: dict, timeout_ms: int) -> dict:
    body = json.dumps({"program": program, "doc_contains": doc,
                       "timeout_ms": timeout_ms}).encode()
    req = urllib.request.Request(
        f"{BASE}/admin/kir/run", data=body,
        headers={"Content-Type": "application/json", "X-Admin-Token": token})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout_ms / 1000 + 60))
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code, "detail": exc.read().decode()[:600]}


_GROUND_CODES = ("KIR-G101", "KIR-G102", "KIR-G103", "KIR-G104", "KIR-G106")


def classify(reply: dict) -> tuple[str, str]:
    """Честные вердикты. Отказ ground-стадии — не дефект опа: он значит,
    что в ЭТОЙ модели нет типов, на которых оп можно проверить.

    `СЛЕПАЯ ПРИЁМКА` (KIR-A007) отделена от `СЛОМАН` замером 04.08: два
    витражных опа объявлены слепыми для переписи В РЕЕСТРЕ, а построили они
    ровно то, что обещали. Смешивать «не построилось» и «построилось, но
    перепись не судья» — терять единственное различие, ради которого
    независимая приёмка вообще заведена."""
    if "http_error" in reply:
        return "СЛОМАН", f"HTTP {reply['http_error']}: {reply['detail'][:200]}"
    kir = reply.get("kir")
    if not isinstance(kir, dict):
        return "СЛОМАН", f"неожиданный ответ: {str(reply)[:200]}"
    diags = kir.get("diagnostics") or []
    codes = [d.get("code") for d in diags if isinstance(d, dict)]
    if kir.get("ok") is True:
        if kir.get("postconditions_violated"):
            viol = (diags[0].get("violations") if diags else None) or []
            return "СЛОМАН", "постусловия нарушены: " + "; ".join(map(str, viol[:3]))
        w = kir.get("witness") or {}
        checks = [w.get("geometry_ok"), w.get("topology_ok"), w.get("semantic_ok")]
        if all(c is True for c in checks):
            return "СТРОИТ", "свидетель: геометрия+топология+семантика"
        return "СЛОМАН", f"свидетель неполон: {json.dumps(w, ensure_ascii=False)}"
    if any(c in _GROUND_CODES for c in codes):
        msg = next((d.get("message_ru") for d in diags
                    if d.get("code") in _GROUND_CODES), "")
        return "НЕ НА ЧЕМ", f"{codes[0]}: {msg}"
    # KIR-A007 — НЕ «сломан». Запись ЗАКОММИЧЕНА, три оси свидетеля зелёные, а
    # незавершённой осталась НЕЗАВИСИМАЯ ПЕРЕПИСЬ — отдельный судья, который
    # для части опов слеп ПО ОБЪЯВЛЕНИЮ (`acceptance._OPS_BLIND`: у линии
    # разрезки и у смены панели число панелей и импостов после операции
    # определяет Revit, поэтому дельту категорий не вывести из программы).
    # Сваливать это в «сломан» — терять разницу между «не построилось» и
    # «построилось, но перепись не судья». Проверено живьём 04.08: линия
    # 287072 ЕСТЬ в GetUGridLineIds своего носителя, IsUGridLine=True, сетка
    # 2 панели / 1 импост.
    if "KIR-A007" in codes:
        w = kir.get("witness") or {}
        checks = [w.get("geometry_ok"), w.get("topology_ok"), w.get("semantic_ok")]
        reason = next((d.get("acceptance_reason") for d in diags
                       if isinstance(d, dict) and d.get("code") == "KIR-A007"),
                      "?")
        if all(c is True for c in checks):
            return "СЛЕПАЯ ПРИЁМКА", (
                f"свидетель зелёный, независимая перепись не судья: {reason}")
        return "СЛОМАН", (
            f"KIR-A007 ({reason}) при неполном свидетеле: "
            f"{json.dumps(w, ensure_ascii=False)}")
    msg = kir.get("message_ru") or ""
    detail = "; ".join(
        f"{d.get('code')}: {d.get('message_ru') or d.get('detail') or ''}"
        for d in diags[:2] if isinstance(d, dict))
    return "СЛОМАН", (detail or msg)[:400]


def ambiguous_candidates(reply: dict) -> tuple[str, list] | None:
    """Отказ KIR-G102 несёт СПИСОК КАНДИДАТОВ с их id — компилятор прямым
    текстом предлагает переспросить через `{"by":"element_id"}`. Это
    единственный канал разведки для пулов, которых нет в enum `query_types`
    (`ceiling_types`, `railing_types`), поэтому матрица им пользуется."""
    kir = reply.get("kir") if isinstance(reply.get("kir"), dict) else {}
    for d in kir.get("diagnostics") or []:
        if isinstance(d, dict) and d.get("code") == "KIR-G102" \
                and isinstance(d.get("candidates"), list) and d["candidates"]:
            return str(d.get("field_name") or "?"), d["candidates"]
    return None


def pin_default(program: dict, field_name: str, element_id: int) -> dict:
    """Заменить `{"by":"default"}` ТОЛЬКО у названного параметра.

    Именно у названного: программа может нести два умолчания сразу (витражная
    стена + тип панели), и подстановка одного id в оба места была бы тихой
    подменой — тем самым `.FirstOrDefault()`, от которого весь сыр-бор.
    """
    out = json.loads(json.dumps(program))
    for op in out.get("ops", []):
        sel = op.get(field_name)
        if isinstance(sel, dict) and sel.get("by") == "default":
            op[field_name] = {"by": "element_id", "value": int(element_id)}
    return out


# ── порядок прогона ─────────────────────────────────────────────────────────

def base_rows() -> list[Row]:
    """Базовые 21 строки в общей оболочке. Успех у них один и тот же —
    три оси свидетеля; отдельного текста не выдумываем."""
    return [Row(name, program, note, tags=("base",))
            for name, program, note in build_programs()]


def order_rows(rows: list[Row]) -> list[list[Row]]:
    """Разложить строки по ступеням: ступень N зависит только от N-1 и ниже.

    Внутри ступени порядок не важен — эти программы независимы и могут идти
    в любой последовательности (в том числе параллельно, если оператору
    удобно; общий Revit один, поэтому по факту всё равно по очереди).
    """
    by_name = {r.name: r for r in rows}
    depth: dict[str, int] = {}

    def d(name: str, seen: frozenset = frozenset()) -> int:
        if name in depth:
            return depth[name]
        row = by_name.get(name)
        if row is None or name in seen:
            return 0
        got = 0
        for need in row.needs:
            got = max(got, d(need, seen | {name}) + 1)
        depth[name] = got
        return got

    for r in rows:
        d(r.name)
    tiers: dict[int, list[Row]] = {}
    for r in rows:
        tiers.setdefault(depth.get(r.name, 0), []).append(r)
    return [tiers[k] for k in sorted(tiers)]


L0_REEXTRACT = """\
ЭТАП 0 — ПЕРЕСНЯТЬ L0. Делается ПЕРВЫМ, до любой записи.

Цепочка чтения уровня починена коммитом 0f4111be (звено принимается только с
настоящим ElementId, в хвост дописаны INSTANCE_REFERENCE / STAIRS_BASE /
STAIRS_RAILING_BASE), и таблица категорий выросла 73 -> 77 (проёмы отдельными
элементами). НА СТАРЫХ СЛЕПКАХ НЕ ИЗМЕНИТСЯ НИЧЕГО, и вот замер 04.08 по ВСЕМ
слепкам на диске, а не по одному: лестниц 556, у 556 из 556 `level_id=null`
(100%, ни одного исключения); балок OST_StructuralFraming 14 090; категорий
проёмов — НОЛЬ в каждом слепке. Всё это ждёт именно переснятия.

Готовой команды-скрипта нет — есть эндпойнт:

  curl -sS -X POST http://127.0.0.1:52411/admin/kir/decompile \\
    -H "X-Admin-Token: $KUKAI_ADMIN_TOKEN" -H 'Content-Type: application/json' \\
    -d '{"action":"start","doc_contains":"<подстрока имени документа>",
         "doc_stamp":"<новое имя слепка, напр. sob62_r23_v6>"}'

  # ход и завершение:
  curl -sS -X POST http://127.0.0.1:52411/admin/kir/decompile \\
    -H "X-Admin-Token: $KUKAI_ADMIN_TOKEN" -H 'Content-Type: application/json' \\
    -d '{"action":"status","doc_stamp":"<то же имя>"}'

Флаг уже стоит (`KUKAI_KIR_DECOMPILE=stage2` в .env), устройство — из списка
допуска; отдельного включения не нужно. doc_stamp обязан быть НОВЫМ: слепок
поверх старого лишает сравнения, а именно сравнение здесь и есть замер.

ЧТО СЧИТАТЬ УСПЕХОМ — три проверки, все офлайн, устройство уже не нужно:

 1. КАТЕГОРИЙ 77, А НЕ 73. В `L0.checkpoint.json` нового слепка обязаны быть
    OST_SWallRectOpening / OST_FloorOpening / OST_RoofOpening /
    OST_ShaftOpening. Замерено: у sob62_r23_v5 их НЕТ ни одной.
 2. У OST_Stairs level_id НЕ null (до правки был null у всех 12).
 3. Подъём меняется в числах:
      PYTHONPATH=. venv/bin/python3.12 tools/relift_offline.py \\
          backend/data/decompile/<новый doc_stamp>
    БАЗА ДЛЯ СРАВНЕНИЯ, снятая 04.08 на sob62_r23_v5 тем же прибором:
    элементов 1510, поднято 1103 (73.05%), честное покрытие 86.65%,
    create_railing 0, среди причин «frozen L0 has no railing path and no host
    id» 27 и «a named level id and name are both required» 86. Именно эти три
    строки правка обязана сдвинуть; если после переснятия они не сдвинулись —
    переснялось не то или не тем.
"""


def print_plan(rows: list[Row], catalogue: dict | None) -> None:
    print(L0_REEXTRACT)
    pools = needed_pools(rows)
    blind = [p for p in pools if p not in QUERY_TYPES_POOLS]
    print("ЭТАП 1 — РАЗВЕДКА (только чтение, в модель не пишет)")
    print("  kir_live_matrix.py --doc <док> --discover")
    print(f"  нужные пулы: {', '.join(pools) or '—'}")
    if blind:
        print(f"  НЕ ЧИТАЮТСЯ фазой 0 (нет в enum query_types): "
              f"{', '.join(blind)}")
        print(f"  -> либо --pin <ключ>=<element_id>, либо автоподбор по "
              f"KIR-G102 (включён)")
    print()
    for i, tier in enumerate(order_rows(rows), start=2):
        head = ("ЭТАП %d — %s" % (
            i, "НЕЗАВИСИМЫЕ (порядок любой)" if i == 2
            else "ЗАВИСИМЫЕ ОТ ПРЕДЫДУЩЕЙ СТУПЕНИ"))
        print(head)
        for r in tier:
            need = f"  <- {', '.join(r.needs)}" if r.needs else ""
            print(f"  {r.name:26s}{need}")
            print(f"      успех: {r.success}")
            if r.caveat:
                print(f"      оговорка: {r.caveat}")
        print()
    print("ПОСЛЕ ПРОГОНА — инвентарь созданного лежит в артефакте (поле "
          "`created` каждой строки).\nСнос: POST /admin/kir/cleanup_stamps "
          "(preview по умолчанию; delete требует повтора префикса).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--doc", default="sob6", help="подстрока имени документа")
    ap.add_argument("--only", action="append", help="прогнать только эти строки")
    ap.add_argument("--set", dest="which", default="all",
                    choices=("all", "base", "gap"),
                    help="какой набор строк: базовый 27.07, пробел или оба")
    ap.add_argument("--timeout", type=int, default=120_000)
    ap.add_argument("--dry", action="store_true",
                    help="напечатать программы, не отправлять")
    ap.add_argument("--plan", action="store_true",
                    help="порядок прогона и критерии успеха — на экран")
    ap.add_argument("--gap", action="store_true",
                    help="замер пробела по реестру и выход")
    ap.add_argument("--discover", action="store_true",
                    help="фаза 0: прочитать пулы документа и сохранить каталог")
    ap.add_argument("--catalogue", help="файл каталога фазы 0")
    ap.add_argument("--pin", action="append", default=[],
                    metavar="КЛЮЧ=ID", help="назвать выбор из пула явно")
    ap.add_argument("--no-autopin", action="store_true",
                    help="не переспрашивать по кандидатам KIR-G102")
    ap.add_argument("--out", help="куда положить артефакт прогона")
    args = ap.parse_args()

    if args.gap:
        rep = gap_report()
        print(f"пишущих опов в реестре : {len(rep['write_ops'])}")
        print(f"гоняет базовый набор   : {len(rep['base'])}")
        print(f"гоняют строки пробела  : {len(rep['gap_rows'])}")
        print(f"НЕ ГОНЯЕТ НИКТО        : {len(rep['still_uncovered'])}")
        for n in rep["still_uncovered"]:
            print("   ", n)
        return 0

    # Вселенная строк — всегда обе половины: предшественник зависимой строки
    # может лежать в ДРУГОМ наборе (`create_railing:hosted` живёт в пробеле,
    # а его лестница — в базовом). Выборка сужает, а потом ЗАМЫКАЕТСЯ по
    # `needs`: строка без своего предшественника — не экономия, а пропуск.
    universe = base_rows() + build_gap_programs()
    by_name = {r.name: r for r in universe}
    if args.which == "base":
        keep = {r.name for r in universe if "base" in r.tags}
    elif args.which == "gap":
        keep = {r.name for r in universe if "base" not in r.tags}
    else:
        keep = set(by_name)
    if args.only:
        wanted = set(args.only)
        unknown = wanted - set(by_name)
        if unknown:
            print(f"нет таких строк: {sorted(unknown)}", file=sys.stderr)
            return 2
        keep = wanted
    for _ in range(4):   # замыкание по предшественникам (глубина цепочек = 1)
        keep |= {n for name in keep for n in by_name[name].needs
                 if n in by_name}
    rows = [r for r in universe if r.name in keep]

    pins = {}
    for raw in args.pin:
        key, _, val = raw.partition("=")
        pins[key.strip()] = int(val)

    cat_path = pathlib.Path(
        args.catalogue or (ARTIFACTS / f"kir_catalogue_{args.doc}.json"))
    catalogue = None
    if cat_path.exists() and not args.discover:
        catalogue = json.loads(cat_path.read_text(encoding="utf-8"))
        print(f"каталог фазы 0: {cat_path} "
              f"({sum(len(v) for v in catalogue.values())} строк)")

    if args.plan:
        print_plan(rows, catalogue)
        return 0

    if args.dry:
        for row in rows:
            chosen: dict = {}
            try:
                program = resolve_picks(row.program, catalogue, pins, chosen)
            except Unresolved as exc:
                print(f"### {row.name} — НЕ СОБРАНА: {exc}")
                continue
            print(f"### {row.name} — {row.note}")
            print(f"### успех: {row.success}")
            if chosen:
                print(f"### выбор: {json.dumps(chosen, ensure_ascii=False)}")
            print(json.dumps(program, ensure_ascii=False, indent=1))
        return 0

    env = (BACKEND / ".env").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^KUKAI_ADMIN_TOKEN=(.+)$", env, re.M)
    if not m:
        print("KUKAI_ADMIN_TOKEN не найден в .env", file=sys.stderr)
        return 2
    token = m.group(1).strip()

    if args.discover:
        pools = needed_pools(rows)
        print(f"фаза 0: разведка пулов документа «{args.doc}»")
        catalogue, blind = discover(token, args.doc, pools, args.timeout)
        cat_path.parent.mkdir(parents=True, exist_ok=True)
        cat_path.write_text(json.dumps(catalogue, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"каталог -> {cat_path}")
        if blind:
            print(f"НЕ ПРОЧИТАНЫ (нет в enum query_types): {', '.join(blind)} "
                  f"— эти строки пойдут через {{by:default}} + автоподбор")
        return 0

    out_rows: list[dict] = []
    produced: dict[str, dict] = {}
    for tier in order_rows(rows):
        for row in tier:
            chosen: dict = {}
            try:
                program = resolve_picks(row.program, catalogue, pins, chosen)
                program = resolve_deps(program, produced)
            except Unresolved as exc:
                out_rows.append({"op": row.name, "verdict": "ПРОПУЩЕН",
                                 "detail": str(exc), "note": row.note,
                                 "success": row.success})
                print(f"? {row.name:26s} {'ПРОПУЩЕН':10s}         {exc}")
                continue

            t0 = time.perf_counter()
            reply = run_one(token, args.doc, program, args.timeout)
            dur = (time.perf_counter() - t0) * 1000
            verdict, detail = classify(reply)

            # Переспрос по кандидатам KIR-G102 — ровно тот ход, который
            # диагностика предлагает текстом. Один раз, и выбор печатается.
            if verdict == "НЕ НА ЧЕМ" and not args.no_autopin:
                cands = ambiguous_candidates(reply)
                if cands is not None:
                    field_name, rows_c = cands
                    got = sorted(rows_c, key=lambda r: int(r.get("id", 0)))[0]
                    print(f"  автоподбор {field_name}: "
                          f"{got.get('id')} «{got.get('name')}» "
                          f"из {len(rows_c)} кандидатов")
                    program = pin_default(program, field_name, int(got["id"]))
                    chosen[f"autopin:{field_name}"] = {
                        "via": "KIR-G102 candidates", "id": int(got["id"]),
                        "name": got.get("name")}
                    t0 = time.perf_counter()
                    reply = run_one(token, args.doc, program, args.timeout)
                    dur = (time.perf_counter() - t0) * 1000
                    verdict, detail = classify(reply)

            kir = reply.get("kir") if isinstance(reply.get("kir"), dict) else {}
            made = created_ids(reply)
            if made:
                produced[row.name] = made
            out_rows.append({
                "op": row.name, "verdict": verdict, "detail": detail,
                "note": row.note, "success": row.success,
                "needs": list(row.needs), "chosen": chosen,
                "duration_ms": round(dur, 1),
                "witness": kir.get("witness"),
                "grounding_report": kir.get("grounding_report"),
                "defaults_note_ru": kir.get("defaults_note_ru"),
                "created": made,
                "result": kir.get("result"),
                "diagnostics": kir.get("diagnostics"),
            })
            mark = {"СТРОИТ": "+", "СЛОМАН": "!", "СЛЕПАЯ ПРИЁМКА": "~",
                    "НЕ НА ЧЕМ": ".", "ПРОПУЩЕН": "?"}[verdict]
            print(f"{mark} {row.name:26s} {verdict:15s} {dur:7.0f}ms  "
                  f"{detail[:96]}")
            if kir.get("defaults_note_ru"):
                print(f"    умолчание: {kir['defaults_note_ru'][:150]}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = pathlib.Path(args.out) if args.out else (
        ARTIFACTS / f"live_op_matrix_{args.which}.json")
    out.write_text(json.dumps(out_rows, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    counts = {v: sum(1 for r in out_rows if r["verdict"] == v)
              for v in ("СТРОИТ", "СЛОМАН", "СЛЕПАЯ ПРИЁМКА",
                        "НЕ НА ЧЕМ", "ПРОПУЩЕН")}
    print(f"\nитог: строит {counts['СТРОИТ']} · сломан {counts['СЛОМАН']} "
          f"· слепая приёмка {counts['СЛЕПАЯ ПРИЁМКА']} "
          f"· не на чем {counts['НЕ НА ЧЕМ']} · пропущен {counts['ПРОПУЩЕН']}"
          f"   ->  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
