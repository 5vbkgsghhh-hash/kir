"""KIR rejection telemetry — producer side of the coverage flywheel
(SPEC §14.1; contract: /root/kukai-cube/KIR_QUEUE_CONTRACT.md, schema v1).

Every refusal is a growth signal. Events are appended (JSONL, fail-open —
a write failure never blocks compilation) to the contract path; the cube's
coverage_queue consumer joins them by query_id and ranks the holes.

Contract essentials honoured here:
  * kind_requested is the RAW string the model emitted — never normalized;
    invented names ARE the signal (the OST_ImportInstances lesson);
  * reject_code is the closed enum from the contract;
  * query texts live in rag_retrieval.jsonl — we only carry query_id.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from kukai.ir.install_paths import install_data_path

logger = logging.getLogger(__name__)

_ENV = "KIR_REJECTIONS_PATH"
# §18.5: отсутствие пути = функция ВЫКЛЮЧЕНА, а не запись в чужую ФС. Раньше
# здесь стоял абсолютный путь этой установки, и на чужой машине первый же отказ
# компилятора пытался создать /opt/kukai-rebuild1/... .
_DEFAULT = None
# Фолбэк оставлен ровно потому, что KIR_REJECTIONS_PATH нет в прод-.env
# (проверено 28.07), а .env этой волне трогать нельзя: без него телеметрия
# отказов на проде замолчала бы молча. Признаком служил isdir() абсолютного
# пути — то есть «путь есть НА МАШИНЕ», а не «мы из него запущены»; замер 02.08
# показал, что процесс из worktree резолвился в ПРОДОВЫЙ файл. Теперь адрес
# принадлежит установке, из которой импортирован модуль (install_paths).
_MAX_EVENTS_PER_COMPILE = 10

# diag code -> contract reject_code
_REJECT_BY_DIAG = {
    "KIR-G001": "UNSUPPORTED_KIND",
    "KIR-G002": "SLOT_RESOLUTION_FAILED",
}
_FALLBACK_REJECT = "VALIDATION_FAILED"

# op name -> action (op_requested field)
_ACTION_BY_OP = {"query_count": "count", "query_list": "list", "query_inspect": "inspect"}

# best-effort kind -> cube object_kind axis (cell is nullable by contract)
_OBJECT_KIND_HINTS = {
    "cad_link": "link", "rvt_link": "link", "level": "level",
    "view": "view", "sheet": "sheet", "grid": "grid", "room": "room_space",
}


def _cell(action: Optional[str], kind: Optional[str]) -> Optional[str]:
    if not action:
        return None
    ok = _OBJECT_KIND_HINTS.get(kind or "", "element")
    return f"{action}×{ok}"


def _feed_path() -> Optional[str]:
    """Куда писать телеметрию отказов, или None — «фид выключен».

    Порядок: env ⇒ каталог данных ЭТОЙ установки ⇒ None. Вне исходного дерева
    последний шаг — тишина, а не попытка создать чужой каталог.
    """
    path = os.environ.get(_ENV)
    if path:
        return path
    if path is None:
        owned = install_data_path("telemetry", "kir_rejections.jsonl")
        if owned is not None:
            return str(owned)
    return _DEFAULT


def record_rejections(diagnostics: list, ops: list, query_id: str = "",
                      revit_version: str = "2026") -> None:
    """diagnostics: list[kukai.ir.diag.Diagnostic]; ops: raw program ops (may be junk)."""
    path = _feed_path()
    if not path:
        return
    try:
        events = []
        for d in diagnostics[:_MAX_EVENTS_PER_COMPILE]:
            op_name = None
            if d.op_index is not None and isinstance(ops, list) and d.op_index < len(ops):
                raw_op = ops[d.op_index]
                if isinstance(raw_op, dict):
                    op_name = raw_op.get("op")
            action = _ACTION_BY_OP.get(op_name) or (op_name if isinstance(op_name, str) else None)
            kind_raw = str(d.got) if (d.field_name or "").endswith("kind") and d.got is not None else None
            events.append({
                "v": 1,
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "source": "kir",
                "reject_code": _REJECT_BY_DIAG.get(d.code, _FALLBACK_REJECT),
                "op_requested": action,
                "kind_requested": kind_raw,        # RAW, no normalization (contract)
                "cell": _cell(action, kind_raw),
                "query_id": query_id or None,
                "revit_version": revit_version,
                "detail": (d.message_ru or "")[:300],
            })
        if not events:
            return
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — fail-open by contract
        logger.debug("kir rejection telemetry write failed (fail-open)", exc_info=True)
