"""KIR shadow observer — rollout stage (1) of INTEGRATION_PLAN_D5 §2(в).

Observe-only: on every query_model tool-call, attempt to express the same
request as a KIR program and log the outcome. The model never sees KIR; the
main turn is NEVER affected (absolute fail-open, wiki-adapter discipline —
every public entry is wrapped, any exception degrades to a no-op).

Flag: KUKAI_KIR_TOOL (env, read at call time — create_element convention).
  off (default) -> no-op;  shadow -> observe+log.
The serving hook in kukai/llm/client.py stays a 5-line try/except; ALL logic
lives here so the llm-layer diff is minimal.

Output: backend/data/telemetry/kir_shadow.jsonl (override: KIR_SHADOW_PATH).
Side effect by design: unmappable kinds flow through compile_program into
kir_rejections.jsonl (the cube's queue) — shadow traffic starts feeding the
coverage flywheel with REAL production signals before the tool is ever live.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from kukai.ir.install_paths import install_data_path

logger = logging.getLogger(__name__)

_FLAG = "KUKAI_KIR_TOOL"
_PATH_ENV = "KIR_SHADOW_PATH"
# §18.5: отсутствие пути = фид ВЫКЛЮЧЕН, а не запись в чужую ФС.
_PATH_DEFAULT = None
# Фолбэк адресуется установке, из которой импортирован модуль (install_paths).
# Прежний признак — isdir() абсолютного пути — отвечал на вопрос «путь есть НА
# МАШИНЕ», а не «мы из него запущены», и на проде любой worktree резолвился в
# продовый файл (замер 02.08).


def _shadow_path():
    path = os.environ.get(_PATH_ENV)
    if path:
        return path
    if path is None:
        owned = install_data_path("telemetry", "kir_shadow.jsonl")
        if owned is not None:
            return str(owned)
    return _PATH_DEFAULT

# RU/EN category aliases -> KIR kinds (best-effort; a miss passes the RAW
# string into compile_program, whose typed refusal feeds kir_rejections —
# raw invented names ARE the coverage signal, per the queue contract).
_CATEGORY_TO_KIND = {
    "walls": "wall", "wall": "wall", "стены": "wall", "стена": "wall",
    "doors": "door", "door": "door", "двери": "door", "дверь": "door",
    "windows": "window", "window": "window", "окна": "window", "окно": "window",
    "floors": "floor", "floor": "floor", "перекрытия": "floor", "полы": "floor",
    "ceilings": "ceiling", "потолки": "ceiling",
    "roofs": "roof", "крыши": "roof", "кровля": "roof",
    "rooms": "room", "помещения": "room", "комнаты": "room",
    "levels": "level", "уровни": "level", "этажи": "level",
    "grids": "grid", "оси": "grid", "сетки": "grid",
    "columns": "column_architectural", "колонны": "column_architectural",
    "structural columns": "column_structural", "несущие колонны": "column_structural",
    "stairs": "stair", "лестницы": "stair",
    "pipes": "pipe", "трубы": "pipe",
    "ducts": "duct", "воздуховоды": "duct",
    "views": "view", "виды": "view",
    "sheets": "sheet", "листы": "sheet",
    "images": "image", "изображения": "image",
    "pdf": "pdf_underlay", "пдф": "pdf_underlay", "подложки": "pdf_underlay",
    "cad": "cad_import", "dwg": "cad_import",

    # group_by-волна (28.07): 51-видовая таблица (0a16e8f5, "разделы в
    # таблицах") сама по себе ничего не чинит здесь — эта карта отдельная,
    # и без своих ключей mappable=False продолжал бы врать про уже
    # закрытые виды. Формы — ТОЛЬКО из живых строк data/telemetry
    # (kir_rejections.jsonl UNSUPPORTED_KIND, kir_shadow.jsonl kind_raw),
    # не придуманы.
    "каркас несущий": "structural_framing", "structural framing": "structural_framing",
    "балки": "structural_framing", "beam": "structural_framing", "beams": "structural_framing",
    "ограждения": "railing", "railings": "railing", "перила": "railing",
    "обобщённые модели": "generic_model", "generic models": "generic_model",
    "мех. оборудование": "mechanical_equipment", "mechanical equipment": "mechanical_equipment",
    "сантехника": "plumbing_fixture", "plumbing fixtures": "plumbing_fixture",
    "специальное оборудование": "specialty_equipment", "спец. оборудование": "specialty_equipment",
    "specialty equipment": "specialty_equipment",
    "мебель": "furniture",
    "кабельные лотки": "cable_tray", "cable trays": "cable_tray", "cable tray": "cable_tray",
    # «Опоры» НАМЕРЕННО не занесена — живой разбор (query_id
    # 30614d9c185ec17c) не даёт однозначного BuiltInCategory (кандидаты:
    # OST_RailingSupport, OST_BridgeBearings, структурные анкеры); молчащий
    # неверный счёт хуже, чем no_category/RAW-проход дальше в
    # kir_rejections. Решать со следующим живым заходом, не отсюда.
}

# query_model features KIR family B v1 cannot express yet. Their frequency in
# shadow logs = the empirical priority list for the next opcodes.
_UNSUPPORTED_ARGS = ("type_contains", "type_names", "param", "group_by",
                     "aggregate", "action_select")


def _norm_version(raw: str) -> str:
    from kukai.ir import spec
    m = re.search(r"20\d\d", raw or "")
    v = m.group(0) if m else "2026"
    return v if v in spec.REVIT_VERSIONS else "2026"


def _map_to_program(args: dict) -> tuple[Optional[dict], list[str], Optional[str]]:
    """(program, unsupported_features, kind_raw). Conservative: any feature KIR
    can't express -> mappable=False; no lossy translation, no guessing."""
    unsupported = []
    for feat in ("type_contains", "type_names", "param", "group_by", "aggregate"):
        if args.get(feat):
            unsupported.append(feat)
    action = (args.get("action") or "").strip().lower()
    if action in ("select", "isolate", "highlight"):
        unsupported.append("action_select")
    cat_raw = str(args.get("category") or "").strip()
    kind = _CATEGORY_TO_KIND.get(cat_raw.lower(), cat_raw or None)
    if kind is None:
        unsupported.append("no_category")
    if unsupported:
        return None, unsupported, cat_raw or None
    op = "query_count" if action in ("count", "") else "query_list"
    return ({"ir_version": "1.0",
             "intent": f"shadow:query_model action={action or 'count'}",
             "ops": [{"op": op, "id": "shadow", "kind": kind}]},
            [], cat_raw or None)


def observe_query_model(args: Any, revit_version: str = "",
                        user_query: str = "") -> None:
    """Public entry — MUST never raise, MUST be near-zero cost when flag=off."""
    try:
        if os.environ.get(_FLAG, "off") not in ("shadow", "stage2"):
            return  # stage2 is a superset: the tool goes live, telemetry keeps flowing
        if not isinstance(args, dict):
            args = {}
        t0 = time.perf_counter()
        ver = _norm_version(revit_version)
        qid = hashlib.sha1((user_query or "").encode("utf-8", "replace")).hexdigest()[:16]
        program, unsupported, kind_raw = _map_to_program(args)
        rec: dict[str, Any] = {
            "v": 1,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": "kir-shadow",
            "query_id": qid,
            "revit_version": ver,
            "mappable": program is not None,
            "unsupported_features": unsupported,
            "kind_raw": kind_raw,
        }
        if program is not None:
            from kukai.ir.compiler import compile_program
            out = compile_program(program, revit_version=ver, query_id=qid)
            rec["kir_ok"] = out.ok
            rec["op"] = program["ops"][0]["op"]
            rec["kind_mapped"] = program["ops"][0]["kind"]
            if not out.ok:
                rec["diag_codes"] = [d.code for d in out.diagnostics][:5]
                if out.handoff:
                    rec["handoff"] = out.handoff["route"]
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        _write(rec)
    except Exception:  # noqa: BLE001 — absolute fail-open: shadow never touches the turn
        logger.debug("KIR shadow observe failed (fail-open)", exc_info=True)


def _write(rec: dict) -> None:
    path = _shadow_path()
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── Frame-level applicability observer (coordinator directive 2026-07-16) ────
# The query_model hook starves: even count-intents flow through
# execute_revit_code. Real applicability must be measured at the FRAME level,
# once per turn, regardless of which tool the model picks.

def _action_op_map() -> dict:
    from kukai.ir import spec
    m: dict = {}
    for op in spec.OPS.values():
        for action, kind in op.capability:
            m.setdefault(action, {"ops": set(), "kinds": set()})
            m[action]["ops"].add(op.name)
            m[action]["kinds"].add(kind)
    return m


def observe_frame(frame: Any, user_query: str = "", revit_version: str = "") -> None:
    """Once-per-turn applicability probe over the intent frame. Same flag,
    same log, same absolute fail-open as observe_query_model."""
    try:
        if os.environ.get(_FLAG, "off") not in ("shadow", "stage2"):
            return  # stage2 is a superset: the tool goes live, telemetry keeps flowing
        from kukai.ir import spec
        qid = hashlib.sha1((user_query or "").encode("utf-8", "replace")).hexdigest()[:16]
        rec: dict[str, Any] = {
            "v": 1,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": "kir-frame-shadow",
            "query_id": qid,
            "revit_version": _norm_version(revit_version),
        }
        if not isinstance(frame, dict) or not frame.get("action"):
            rec["applicability"] = "no_frame"
            _write(rec)
            return
        action = str(frame.get("action"))
        kinds = [str(k) for k in (frame.get("object_kinds") or [])]
        rec["action"] = action
        rec["object_kinds"] = kinds
        rec["domain"] = frame.get("domain")
        amap = _action_op_map()
        if action in spec.ROUTE_ONLY_ACTIONS:
            rec["applicability"] = "route-only"
        elif action in amap:
            covered_kinds = amap[action]["kinds"]
            overlap = [k for k in kinds if k in covered_kinds]
            rec["matched_ops"] = sorted(amap[action]["ops"])
            rec["applicability"] = (
                "covered" if (not kinds or overlap) else "action-only")
            if kinds:
                rec["kinds_covered"] = overlap
                rec["kinds_uncovered"] = [k for k in kinds if k not in covered_kinds]
        else:
            rec["applicability"] = "uncovered"
        _write(rec)
    except Exception:  # noqa: BLE001 — absolute fail-open
        logger.debug("KIR frame shadow failed (fail-open)", exc_info=True)
