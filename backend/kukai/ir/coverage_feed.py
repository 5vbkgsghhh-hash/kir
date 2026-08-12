"""KIR rejection telemetry — producer side of the coverage flywheel
(SPEC §14.1; contract: /root/kukai-cube/KIR_QUEUE_CONTRACT.md, schema v1).

Every refusal is a growth signal. Events are appended (JSONL, fail-open —
a write failure never blocks compilation) to the contract path; the cube's
coverage_queue consumer joins them by query_id and ranks the holes.

Contract essentials honoured here:
  * kind_requested is the RAW string the model emitted — never normalized;
    invented names ARE the signal (the OST_ImportInstances lesson);
  * reject_code is the closed enum from the contract;
  * query texts live in rag_retrieval.jsonl — we only carry query_id;
  * diag_code and candidates ride BESIDE the enum (added 2026-08-09, additive
    to schema v1): without them a CORRECT grounding refusal — the compiler
    declining to choose for the author and naming candidates instead — was
    indistinguishable from an author error in every later count. Measured
    damage: 662 of 1469 stored events were correct refusals filed as generic
    VALIDATION_FAILED. See the block above _MAX_CANDIDATES.
  * op_id and field_name ride beside them (added 2026-08-09, same additivity):
    a refusal must be identifiable from the corpus alone, and «op_requested»
    names the OP KIND while the diagnostic already knew the instance and the
    field. Both were being discarded at this exact line.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
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

# ─── ОТКАЗ ОБЯЗАН СОХРАНИТЬ СВОЮ ЛИЧНОСТЬ ────────────────────────────────────
#
# `reject_code` — ЗАКРЫТЫЙ enum контракта (KIR_QUEUE_CONTRACT.md, v1), и
# расширять его нельзя: консьюмер `coverage_queue.py` ранжирует дыры покрытия
# именно по нему. Но схлопывание ВСЕГО, что не G001/G002, в `VALIDATION_FAILED`
# стоило ровно того, ради чего фид заводили.
#
# Замер 09.08.2026 по `kir_rejections.jsonl` (1469 событий, 16.07–04.08):
# 1364 из них — `VALIDATION_FAILED`, и внутри этой кучи лежат ДВА РАЗНЫХ МИРА:
#
#   662 события — ВЕРНЫЙ ОТКАЗ. Компилятор отказался выбирать за автора и
#       назвал кандидатов: 604 неоднозначности (`KIR-G102` — «несколько
#       вариантов, default невозможен»), 49 «имя не найдено» с ближайшими
#       (`KIR-G101`), 9 честно пустых пулов (`KIR-G104`). Это РАБОТА
#       компилятора — то самое поведение, из-за которого живая пара 02.08
#       показала, что C#-плечо молча взяло 1 тип двери из 62, а KIR отказал;
#   остальные — ошибка автора (разбор, типы, бюджет программы).
#
# Обе кучи считались одинаково — «отказ», — и верный отказ уходил в статистику
# как дефект. Теперь рядом с контрактным `reject_code` едут ДВА поля:
#
#   `diag_code`  — исходный типизированный код (`KIR-G102`, `KIR-T002`, …);
#   `candidates` — то, что компилятор ПРЕДЛОЖИЛ вместо выбора за автора.
#                  Пустой список отказа с кандидатами не бывает; его наличие
#                  и есть доказательство, что отказ верный.
#
# Оба поля АДДИТИВНЫ к схеме v1: консьюмер читает по ключам и старые события
# без них остаются читаемыми (их класс восстанавливается по тексту `detail` —
# см. `tools/live_op_rates.py`, столбцы «по тексту»).
_MAX_CANDIDATES = 8


def _candidates(diag) -> list:
    """Кандидаты отказа, обрезанные и обезличенные до {id, name}.

    Координат тут нет и не было; берём ровно те поля, которыми автор сможет
    переписать селектор (`{"by": "element_id", "value": <id>}`)."""
    raw = getattr(diag, "candidates", None)
    if not isinstance(raw, list) or not raw:
        return []
    out = []
    for item in raw[:_MAX_CANDIDATES]:
        if isinstance(item, dict):
            row = {k: item[k] for k in ("id", "name") if k in item}
            out.append(row or {k: str(v)[:64] for k, v in list(item.items())[:2]})
        else:
            out.append({"name": str(item)[:64]})
    return out

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


def record_rejections(
    diagnostics: list,
    ops: list,
    query_id: str = "",
    revit_version: str = "2026",
    stage: str = "compile",
    *,
    turn_id: str = "",
    action_id: str = "",
    query_fingerprint: str = "",
    source_kind: str = "unknown",
) -> None:
    """diagnostics: list[kukai.ir.diag.Diagnostic]; ops: raw program ops (may be junk)."""
    path = _feed_path()
    if not path:
        return
    try:
        # One call is one compiler/serving attempt.  This identity is never
        # derived from query_id: chat historically stored a hash of the text
        # there, so two real turns with the same prompt share that value.
        attempt_id = uuid.uuid4().hex
        all_diagnostics = list(diagnostics or [])
        attempt_diagnostics = len(all_diagnostics)
        normalized_source = str(source_kind or "unknown").strip().lower()
        if not normalized_source:
            normalized_source = "unknown"
        events = []
        for d in all_diagnostics[:_MAX_EVENTS_PER_COMPILE]:
            op_name = None
            if d.op_index is not None and isinstance(ops, list) and d.op_index < len(ops):
                raw_op = ops[d.op_index]
                if isinstance(raw_op, dict):
                    op_name = raw_op.get("op")
            action = _ACTION_BY_OP.get(op_name) or (op_name if isinstance(op_name, str) else None)
            kind_raw = str(d.got) if (d.field_name or "").endswith("kind") and d.got is not None else None
            event = {
                "v": 1,
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "source": "kir",
                "reject_code": _REJECT_BY_DIAG.get(d.code, _FALLBACK_REJECT),
                # Личность отказа. `reject_code` остаётся контрактным enum'ом,
                # а `diag_code` называет, ЧТО именно отказало: без него верный
                # отказ по неоднозначности неотличим от ошибки автора.
                "diag_code": d.code,
                "op_requested": action,
                "kind_requested": kind_raw,        # RAW, no normalization (contract)
                # АДРЕС ОТКАЗА, А НЕ ТОЛЬКО ЕГО ИМЯ. `op_requested` берётся из
                # `op_index` и называет ИМЯ операции; в программе из двадцати
                # стен это адрес всех двадцати сразу. `Diagnostic` при этом
                # НЕСЁТ `op_id` — тот самый идентификатор, которым адресованы
                # `op_outcomes` и `violations` в корпусе свидетелей, — и фид
                # его выбрасывал, так что событие отказа нечем было соединить
                # ни с экземпляром операции, ни со строкой исполнения.
                # Оба поля пишутся ТОЛЬКО когда они есть: пустой ключ читался
                # бы как «адреса не было», а это другой факт (см. `candidates`).
                **({"op_id": str(d.op_id)[:64]} if d.op_id else {}),
                # `field_name` — ЧТО именно отказало внутри операции. Сейчас он
                # лежит только внутри прозы `detail`, и любой счёт «по какому
                # параметру нас отказывают чаще всего» был разбором текста.
                **({"field_name": str(d.field_name)[:64]} if d.field_name else {}),
                "cell": _cell(action, kind_raw),
                "query_id": query_id or None,
                # Orthogonal identity axes.  Missing caller identity stays
                # explicit None; only the attempt is compiler-owned and can
                # therefore always be minted truthfully here.
                "turn_id": str(turn_id)[:128] if turn_id else None,
                "action_id": str(action_id)[:128] if action_id else None,
                "attempt_id": attempt_id,
                "attempt_diagnostics": attempt_diagnostics,
                "query_fingerprint": (
                    str(query_fingerprint)[:128]
                    if query_fingerprint else None
                ),
                "source_kind": normalized_source[:32],
                "stage": str(stage or "compile")[:64],
                "revit_version": revit_version,
                "detail": (d.message_ru or "")[:300],
            }
            candidates = _candidates(d)
            if candidates:
                # Кандидаты — доказательство того, что компилятор не выбрал за
                # автора, а предложил. Отсутствие поля тоже факт: их не было.
                event["candidates"] = candidates
            events.append(event)
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
