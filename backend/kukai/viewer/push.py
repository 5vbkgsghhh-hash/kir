"""PUSH — толчок вместо опроса. БУДИЛЬНИК, а не данные.

ЗАМЕР ПЕРЕД ПОСТРОЙКОЙ (11.08.2026), и он отменил половину задуманного:

* `seq` растёт РОВНО В ОДНОМ месте — `plan_stream.publish()` вызывает
  `journal.append()` и получает `record.seq`. Второго источника курсора нет и
  заводить его не надо;
* транспорт `/ws/chat` уже поднят и подписан, но он принадлежит ЧАТ-ПАНЕЛИ:
  `plan_stream.bind_transport` привязывает его из `chat_ws`. **Страница вьюера
  сокета не имеет вовсе** — она только опрашивает. Значит толкать её через
  чужой канал нечем, и канал заводится свой (`/ws/viewer`);
* дельта уже O(нового) (2.0 мс на 300 программах) и уже несёт `base_digest` с
  честным отказом. Толкать БАЙТЫ незачем.

════════════════════════════════════════════════════════════════════════════
ТОЛЧОК НЕСЁТ НОМЕР, А НЕ СЦЕНУ — И ЭТО ТА ЖЕ ДОКТРИНА, ЧТО У `plan_stream`
════════════════════════════════════════════════════════════════════════════
«В очереди едет не кадр, а БУДИЛЬНИК» — правило, которым `plan_stream`
обосновывает право ВЫБРАСЫВАТЬ кадры. Здесь оно применено этажом выше:
по сокету едет `{"type": "kir_scene", "seq": N}`, а сцену клиент забирает
СВОИМ обычным запросом дельты — от СВОЕГО курсора и со СВОЕЙ подписью базы.

Три следствия, и все три — требования, выполненные по построению:

1. **ОПРОС НЕ ВЫБРОШЕН.** Толчок только будит; путь получения не менялся ни
   на строку. Клиент с упавшим сокетом догоняет курсором и получает то же
   самое, просто позже. Push — ускорение, а не единственный путь.
2. **`base_digest` РАБОТАЕТ ТАК ЖЕ.** Толчок не несёт данных, поэтому ослабить
   договор дельты ему нечем: расхождение базы по-прежнему даёт 409 и
   перезапрос целого. Тихой склейки не появляется, потому что склеивать
   толчку нечего.
3. **ПРОПУСК ВИДЕН.** Клиент всегда запрашивает от СВОЕГО курсора, поэтому
   потерянный толчок не может потерять программу — он теряет только
   свежесть. А чтобы потеря была ЗАМЕТНА, а не молчалива, толчок несёт
   `seq`, и клиент сверяет его с тем, что получил: опрос, нашедший работу, о
   которой не будили, считается пропущенным толчком и НАЗЫВАЕТСЯ.

════════════════════════════════════════════════════════════════════════════
ОГРАНИЧЕННОСТЬ — ПО ТОМУ ЖЕ ЗАКОНУ, ЧТО У РИСОВАЛЬЩИКА
════════════════════════════════════════════════════════════════════════════
Очередь с потолком; переполнилась — толчок ВЫБРАСЫВАЕТСЯ и считается.
Выброшенный толчок стоит задержки до следующего опроса, а не программы:
программа уже в журнале, и курсор клиента её заберёт. Задача на событие
(`create_task` на каждую публикацию) отвергнута здесь по той же причине, по
которой отвергнута там: неограниченное число задач есть утечка,
замаскированная под асинхронность.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ("PUSH_SCHEMA", "connect", "disconnect", "enabled", "notify",
           "reset", "stats", "subscribers")

PUSH_SCHEMA = "kir-scene-push/1"

_FLAG = "KUKAI_KIR_SCENE_PUSH"

#: Ключ подписки — тот же `(device_id, doc_key)`, что у журнала и витрины.
#: Своего ключа здесь нет намеренно: третий способ назвать одну сессию
#: разъехался бы с первыми двумя молча.
_SUBS: dict[tuple[str, str], set] = {}
_QUEUE: Optional[asyncio.Queue] = None
_TASK = None
_LOOP = None

_COUNTERS = {
    "notified": 0, "sent": 0, "dropped": 0, "send_errors": 0,
    "no_subscriber": 0, "disabled": 0,
}


def enabled() -> bool:
    """Выключатель на весь push. Выключенный = поведение до этой волны:
    клиент опрашивает и ничего не теряет, только ждёт дольше."""
    return os.environ.get(_FLAG, "1") != "0"


def _queue_max() -> int:
    try:
        return max(1, min(1024, int(os.environ.get("KUKAI_KIR_PUSH_QUEUE", "")
                                    or 64)))
    except (TypeError, ValueError):
        return 64


def connect(key: tuple[str, str], socket: Any) -> None:
    _SUBS.setdefault(key, set()).add(socket)


def disconnect(key: tuple[str, str], socket: Any) -> None:
    bucket = _SUBS.get(key)
    if bucket is not None:
        bucket.discard(socket)
        if not bucket:
            _SUBS.pop(key, None)


def subscribers(key: tuple[str, str]) -> int:
    return len(_SUBS.get(key) or ())


def _ensure_worker() -> Optional[asyncio.Queue]:
    """ОДИН ограниченный работник, как у рисовальщика. Пересоздаётся, если
    цикл событий сменился (перезапуск сервиса в том же процессе)."""
    global _QUEUE, _TASK, _LOOP
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    if _LOOP is not loop or _QUEUE is None or _TASK is None or _TASK.done():
        _LOOP = loop
        _QUEUE = asyncio.Queue(maxsize=_queue_max())
        _TASK = loop.create_task(_worker(_QUEUE))
    return _QUEUE


async def _worker(queue: asyncio.Queue) -> None:
    while True:
        key, seq = await queue.get()
        # СХЛОПЫВАНИЕ: если в очереди уже лежат толчки той же сессии, берём
        # ПОСЛЕДНИЙ номер. Клиенту незачем просыпаться трижды, чтобы забрать
        # один и тот же хвост, а номер всё равно только будильник.
        while not queue.empty():
            try:
                nkey, nseq = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if nkey == key:
                seq = max(seq, nseq)
            else:
                await _fanout(nkey, nseq)
        await _fanout(key, seq)


async def _fanout(key: tuple[str, str], seq: int) -> None:
    sockets = list(_SUBS.get(key) or ())
    if not sockets:
        _COUNTERS["no_subscriber"] += 1
        return
    payload = {"type": "kir_scene", "schema": PUSH_SCHEMA, "seq": int(seq),
               "device_id": key[0], "doc_key": key[1],
               # ТОЛЧОК НЕ НЕСЁТ СЦЕНЫ, и это сказано в нём самом: читатель,
               # решивший, что здесь данные, обязан споткнуться о слово.
               "wake_only": True,
               "ru": ("журнал вырос до seq=%d — заберите дельту своим "
                      "курсором и своей подписью базы" % int(seq))}
    for socket in sockets:
        try:
            await socket.send_json(payload)
            _COUNTERS["sent"] += 1
        except Exception:  # noqa: BLE001 — отвалившийся сокет это не наша беда
            _COUNTERS["send_errors"] += 1
            disconnect(key, socket)


def notify(device_id: Optional[str], doc_key: str, seq: int) -> None:
    """ЕДИНСТВЕННЫЙ вход. Синхронный, без ожиданий, НИКОГДА не бросает.

    Зовётся из `plan_stream.publish` сразу после журнала — то есть из того же
    и единственного места, где растёт `seq`. Второго источника курсора не
    появляется: здесь номер только ПЕРЕДАЁТСЯ, а принадлежит он журналу.
    """
    try:
        if not enabled():
            _COUNTERS["disabled"] += 1
            return
        key = (str(device_id or ""), str(doc_key or ""))
        if not _SUBS.get(key):
            _COUNTERS["no_subscriber"] += 1
            return
        queue = _ensure_worker()
        if queue is None:
            return
        _COUNTERS["notified"] += 1
        try:
            queue.put_nowait((key, int(seq)))
        except asyncio.QueueFull:
            # Выброшенный толчок стоит ЗАДЕРЖКИ, а не программы: программа уже
            # в журнале, и курсор клиента её заберёт следующим опросом.
            _COUNTERS["dropped"] += 1
    except Exception:  # noqa: BLE001 — АБСОЛЮТНЫЙ fail-open, как у publish
        logger.debug("scene push failed (fail-open)", exc_info=True)


def stats() -> dict[str, Any]:
    out = dict(_COUNTERS)
    out["schema"] = PUSH_SCHEMA
    out["enabled"] = enabled()
    out["sessions"] = len(_SUBS)
    out["sockets"] = sum(len(v) for v in _SUBS.values())
    out["queue_depth"] = _QUEUE.qsize() if _QUEUE is not None else 0
    out["queue_max"] = _queue_max()
    return out


def reset() -> None:
    global _QUEUE, _TASK, _LOOP
    _SUBS.clear()
    if _TASK is not None:
        _TASK.cancel()
    _QUEUE = None
    _TASK = None
    _LOOP = None
    for name in _COUNTERS:
        _COUNTERS[name] = 0
