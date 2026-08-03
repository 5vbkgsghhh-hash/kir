"""Живая матрица: какой пишущий оп РЕАЛЬНО строит, а какой только компилируется.

Гейт Roslyn (`kukai.ir.gate_runner`) доказывает, что все 32 опа компилируются на
шести версиях Revit. Он ничего не говорит о том, строит ли Revit то, что они
описывают: на 27.07 живого Revit касались 8 пишущих опов из 28.

Скрипт гонит по одной программе на оп через ТОТ ЖЕ прод-путь, что и чат
(`POST /admin/kir/run` -> `serving.handle_revit_ir`: ground-снапшот ->
compile_program -> run_declarative), и раскладывает исход на три честных вердикта:

  СТРОИТ            ok:true И все три свидетеля зелёные
  СЛОМАН            типизированный отказ / нарушенное постусловие (с текстом)
  НЕ НА ЧЕМ         ground отказал: нужного пула типов в этой модели нет

`ok:true` с `postconditions_violated` — это НЕ успех, а найденный дефект: элемент
закоммичен, но постусловие не выполнено.

Каждый прогон сам ложится в корпус свидетелей (`data/telemetry/kir_witness.jsonl`),
поэтому доказательство переживает сессию и позже цитируется замером, а не памятью.

    PYTHONPATH=. venv/bin/python scripts/kir_live_matrix.py --doc sob6
    PYTHONPATH=. venv/bin/python scripts/kir_live_matrix.py --doc sob6 --only create_beam
    PYTHONPATH=. venv/bin/python scripts/kir_live_matrix.py --doc sob6 --dry   # печать программ
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
    """Три честных вердикта. Отказ ground-стадии — не дефект опа: он значит,
    что в ЭТОЙ модели нет типов, на которых оп можно проверить."""
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
    msg = kir.get("message_ru") or ""
    detail = "; ".join(
        f"{d.get('code')}: {d.get('message_ru') or d.get('detail') or ''}"
        for d in diags[:2] if isinstance(d, dict))
    return "СЛОМАН", (detail or msg)[:400]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--doc", default="sob6", help="подстрока имени документа")
    ap.add_argument("--only", action="append", help="прогнать только эти опы")
    ap.add_argument("--timeout", type=int, default=120_000)
    ap.add_argument("--dry", action="store_true", help="напечатать программы, не отправлять")
    args = ap.parse_args()

    programs = build_programs()
    if args.only:
        wanted = set(args.only)
        programs = [p for p in programs if p[0] in wanted]
        if not programs:
            print(f"нет таких опов: {sorted(wanted)}", file=sys.stderr)
            return 2

    if args.dry:
        for name, program, note in programs:
            print(f"### {name} — {note}")
            print(json.dumps(program, ensure_ascii=False, indent=1))
        return 0

    env = (BACKEND / ".env").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^KUKAI_ADMIN_TOKEN=(.+)$", env, re.M)
    if not m:
        print("KUKAI_ADMIN_TOKEN не найден в .env", file=sys.stderr)
        return 2
    token = m.group(1).strip()

    rows = []
    for name, program, note in programs:
        t0 = time.perf_counter()
        reply = run_one(token, args.doc, program, args.timeout)
        dur = (time.perf_counter() - t0) * 1000
        verdict, detail = classify(reply)
        kir = reply.get("kir") if isinstance(reply.get("kir"), dict) else {}
        rows.append({
            "op": name, "verdict": verdict, "detail": detail, "note": note,
            "duration_ms": round(dur, 1),
            "witness": kir.get("witness"),
            "result": kir.get("result"),
            "diagnostics": kir.get("diagnostics"),
        })
        mark = {"СТРОИТ": "+", "СЛОМАН": "!", "НЕ НА ЧЕМ": "."}[verdict]
        print(f"{mark} {name:26s} {verdict:10s} {dur:7.0f}ms  {detail[:96]}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "live_op_matrix_20260727.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in ("СТРОИТ", "СЛОМАН", "НЕ НА ЧЕМ")}
    print(f"\nитог: строит {counts['СТРОИТ']} · сломан {counts['СЛОМАН']} "
          f"· не на чем {counts['НЕ НА ЧЕМ']}   ->  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
