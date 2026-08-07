"""ЖИВОЙ ПЛАН — читатель журнала программ, который рисует и отправляет.

Оператор хочет ВИДЕТЬ, как здание собирается, пока модель его проектирует.
Ценность не в красоте: человек, видящий сборку, верит больше, чем любому
отчёту. Поэтому кадр обязан доезжать ВО ВРЕМЯ работы, а не после неё.

Модуль — ЧИТАТЕЛЬ, и только. Он не компилирует, не заземляет, не пишет в
Revit и не решает ничего о ходе. Его можно выключить, сломать или удалить
целиком, и стройка этого не заметит — это проверяется разрушительными
воротами, а не обещается (`kukai/ir/tests/test_live_plan_stream.py`).

ЧЕТЫРЕ ИНВАРИАНТА И ГДЕ ОНИ ЖИВУТ В КОДЕ
-----------------------------------------

1. ОДНОСТОРОННОСТЬ. Отсюда в компилятор пути нет. Единственное ребро внутрь
   `kukai.ir` — ленивый импорт `preview` в `_render_frame`, а `preview.py` на
   уровне модуля не импортирует из `kukai.ir` ничего. Проверяется обходом
   импортов (`ast`), а не чтением глазами.

2. КРАН БЕЗ ОЖИДАНИЯ. `publish()` — СИНХРОННАЯ функция без единой точки
   ожидания. Не «мы стараемся не блокировать», а «заблокировать нечем»:
   в теле нет `await`, поэтому вызывающий не может быть задержан рисованием
   даже теоретически. «Задача на событие» (`create_task` на каждый кадр)
   отвергнута: это неограниченное число задач и удержание ссылок на программы,
   то есть утечка, замаскированная под асинхронность. Вместо неё — ОДИН
   ограниченный работник с очередью.

3. ОГРАНИЧЕННОСТЬ. Очередь с потолком; переполнилась — кадр ВЫБРАСЫВАЕТСЯ и
   считается. Частота ограничена (WebView2 уже кусался троттлингом, морозившим
   JS-пинг). Панель не подключена — рисование не запускается вовсе: `publish`
   выходит сразу после записи в журнал.

   ПОЧЕМУ ВЫБРАСЫВАТЬ КАДР БЕЗОПАСНО. В очереди едет не кадр, а БУДИЛЬНИК:
   сама программа уже в журнале, и работник догоняет по курсору. Потерянный
   будильник стоит одной картинки, а не одной программы. И последнее состояние
   не теряется тоже: очередь полна ⇒ работник занят ⇒ дойдя до конца цикла он
   заново сверяет курсор с головой журнала.

4. ЧЕСТНОСТЬ ИСТОЧНИКА. `preview` штампует лист `Assertion.SELF_REPORTED`,
   кадр несёт `stage="planned"`, сводка называется «ЗАЯВЛЕНО». Три метки,
   ни одна не выводится из другой. Иначе через месяц кто-нибудь скажет «я же
   видел, всё было нормально», и мы получим приёмку через глаз.

ЧЕМ ПОТОК ВСЁ-ТАКИ СПОСОБЕН ПОМЕШАТЬ — названо в отчёте волны и здесь:
рисование считает питоном, то есть держит GIL. Оно вынесено в поток
(`asyncio.to_thread`), поэтому цикл событий не замирает на всю отрисовку, но
конкуренция за GIL остаётся и на тяжёлом этаже отнимает у хода проценты
времени. Это цена, а не дефект; её величина измерена длинным прогоном.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Awaitable, Callable, Mapping, Optional

from kukai.live import journal as _journal
from kukai.live import showroom as _showroom

logger = logging.getLogger(__name__)

__all__ = (
    "FRAME_SCHEMA",
    "attach",
    "attached",
    "bind_transport",
    "detach",
    "drain",
    "enabled",
    "publish",
    "reset",
    "stats",
)

FRAME_SCHEMA = "kir-plan-frame/1"

_FLAG = "KUKAI_KIR_LIVE_PLAN"


def enabled() -> bool:
    """Выключатель на весь поток. Выключенный = поведение до этой волны."""
    return os.environ.get(_FLAG, "1") != "0"


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _queue_max() -> int:
    return _int_env("KUKAI_KIR_LIVE_PLAN_QUEUE", 8, low=1, high=1024)


def _interval_s() -> float:
    """Минимальный промежуток между отправками. Не украшение: WebView2 душит
    таймеры фонового окна, и лента кадров чаще ~2/с морозила JS-пинг."""
    return _int_env(
        "KUKAI_KIR_LIVE_PLAN_INTERVAL_MS", 400, low=0, high=60_000) / 1000.0


def _levels_per_frame() -> int:
    """Сколько этажей рисуется за один проход. Программа, задевшая двадцать
    этажей, не имеет права превратить один кадр в двадцать отрисовок."""
    return _int_env("KUKAI_KIR_LIVE_PLAN_LEVELS", 3, low=1, high=64)


def _index_batch() -> int:
    """Сколько программ размечается за один проход работника. Догоняние на
    четыреста программ обязано разложиться на ограниченные куски."""
    return _int_env("KUKAI_KIR_LIVE_PLAN_INDEX_BATCH", 64, low=1, high=4096)


def _slice_ops_cap() -> int:
    """Потолок операций, отдаваемых в ОДНУ отрисовку. Замер: 2 800 операций
    одного этажа = 543 мс на кадр."""
    return _int_env("KUKAI_KIR_LIVE_PLAN_SLICE_OPS", 1_500, low=50, high=100_000)


def _send_timeout_s() -> float:
    return _int_env(
        "KUKAI_KIR_LIVE_PLAN_SEND_MS", 5_000, low=100, high=120_000) / 1000.0


# ── канал наружу ────────────────────────────────────────────────────────────
# Модуль знает только «как отправить словарь», сам канал задаёт веб-слой
# (`bind_transport`). Ровно та же граница, что у `llm/turn_progress.py`: ни
# `kukai.live`, ни `kukai.ir` не тянут за собой FastAPI.
#
# ПОЧЕМУ КАНАЛ АДРЕСУЕТСЯ УСТРОЙСТВОМ, А НЕ ХОДОМ. `turn_progress` привязан
# ContextVar'ом внутри `run_turn`, поэтому вне хода он молчит — а длинный
# офлайн-прогон идёт час без единой реплики в чате, и кадры обязаны доезжать
# и тогда. Реестр `ws_registry._device_websockets` живёт независимо от ходов
# и уже используется фоновыми задачами (прогресс VOR) — берём его.
_Transport = Callable[[str, dict], Awaitable[Any]]
_transport: Optional[_Transport] = None

_STATE_LOCK = threading.Lock()
#: device_id -> сколько панелей этого устройства подключено (человек открывает
#: KUKI в двух окнах Revit — обе панели ждут кадры).
_attached: dict[str, int] = {}

_COUNTERS = {
    "published": 0,          # сколько раз позвали publish
    "journaled": 0,          # сколько программ легло в журнал
    "queued": 0,             # сколько будильников поставлено
    "dropped_frames": 0,     # сколько будильников выброшено (очередь полна)
    "skipped_no_panel": 0,   # панели нет — не рисуем вовсе
    "skipped_disabled": 0,
    "renders": 0,
    "render_errors": 0,
    "index_errors": 0,
    "frames_sent": 0,
    "send_errors": 0,
    "worker_errors": 0,
    "showroom_errors": 0,    # кадр нарисован, но подписать программу не вышло
    "render_ms_total": 0.0,
}


def bind_transport(transport: Optional[_Transport]) -> None:
    """Задать канал доставки. Вызывается веб-слоем один раз."""
    global _transport
    _transport = transport


def attach(device_id: str) -> None:
    """Панель этого устройства подключилась."""
    if not device_id:
        return
    with _STATE_LOCK:
        _attached[device_id] = _attached.get(device_id, 0) + 1


def detach(device_id: str) -> None:
    """Панель отключилась. Ноль панелей — рисование для устройства встаёт."""
    if not device_id:
        return
    with _STATE_LOCK:
        left = _attached.get(device_id, 0) - 1
        if left > 0:
            _attached[device_id] = left
        else:
            _attached.pop(device_id, None)


def attached(device_id: str) -> bool:
    with _STATE_LOCK:
        return bool(device_id) and _attached.get(device_id, 0) > 0


# ── работник ────────────────────────────────────────────────────────────────
# Ровно один на цикл событий. Привязка к циклу, а не к процессу: в тестах цикл
# на тест, а очередь, созданная в чужом цикле, тихо перестаёт будиться.

_worker_lock = threading.Lock()
_worker_task: Optional[asyncio.Task] = None
_worker_loop: Optional[asyncio.AbstractEventLoop] = None
_queue: Optional[asyncio.Queue] = None
_idle: Optional[asyncio.Event] = None


def _ensure_worker() -> Optional[asyncio.Queue]:
    """Поднять работника в ТЕКУЩЕМ цикле. Нет цикла — потока нет, и это не
    ошибка: журнал уже записан, а рисовать некому и незачем."""
    global _worker_task, _worker_loop, _queue, _idle
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    with _worker_lock:
        if (_worker_loop is not loop or _queue is None
                or _worker_task is None or _worker_task.done()):
            _worker_loop = loop
            _queue = asyncio.Queue(maxsize=_queue_max())
            _idle = asyncio.Event()
            _idle.set()
            _worker_task = loop.create_task(_worker(_queue, _idle))
        return _queue


async def _worker(queue: asyncio.Queue, idle: asyncio.Event) -> None:
    """ЕДИНСТВЕННЫЙ работник. Отдельная задача — значит его беды остаются его.

    Тело целиком под `except`: исключение в рисовальщике не имеет права ни
    уронить работника, ни тем более дойти до пути записи (до него ему и так
    не дотянуться — он в другой задаче). Счётчик `render_errors` делает поломку
    ВИДИМОЙ числом; молчаливо переживать её было бы тем же обманом, только
    вежливым.
    """
    while True:
        try:
            key = await queue.get()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _COUNTERS["worker_errors"] += 1
            continue
        idle.clear()
        try:
            pending = {key}
            # Схлопывание: пока работник рисовал, могло прийти десять
            # будильников по одной сессии. Рисуем ОДИН раз по текущему
            # состоянию журнала — отставший кадр никому не нужен.
            while True:
                try:
                    pending.add(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            for session_key in pending:
                try:
                    await _serve(session_key)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    _COUNTERS["worker_errors"] += 1
                    logger.debug("live plan worker cycle failed", exc_info=True)
            # Ограничение частоты. Стоит ПОСЛЕ отправки, поэтому первый кадр
            # уходит без задержки, а лента — не чаще интервала.
            interval = _interval_s()
            if interval > 0:
                await asyncio.sleep(interval)
        finally:
            if queue.empty():
                idle.set()


async def _serve(session_key: tuple[str, str]) -> None:
    """Догнать журнал по курсору, нарисовать изменившиеся этажи, отправить.

    Один проход ОГРАНИЧЕН по обеим осям: сколько программ индексируем и
    сколько операций отдаём в отрисовку. Догоняние на сотню программ не имеет
    права превратиться в одну неразрывную секунду счёта — не потому, что это
    медленно, а потому, что этот счёт идёт питоном и держит GIL, то есть
    отнимает время у самого хода.
    """
    entry = _journal.get(session_key)
    if entry is None:
        return
    device_id = session_key[0]
    if not attached(device_id):
        return
    pending = entry.pending()
    if not pending:
        return

    # ИНДЕКСАЦИЯ. Какие этажи затронула каждая новая программа — спрашиваем у
    # `preview`, а не у собственной копии правила: «какому этажу принадлежит
    # операция» уже решено в `preview._op_level_key`, и второй экземпляр этого
    # решения разъехался бы с первым за месяц.
    #
    # В индексацию едут ТОЛЬКО `create_level`-датумы, а не все: имя этажу даёт
    # `create_level`, оси на метку не влияют. Без датумов ключ `$L1` в одной
    # программе и «Отметка 0.000» в другой раскололи бы один этаж на два.
    naming = [op for op in entry.datums if op.get("op") == "create_level"]
    batch = _index_batch()
    behind = len(pending) > batch
    pending = pending[:batch]
    # ОДИН заход в поток на всю пачку, а не по заходу на программу. Замер до
    # правки: 400 программ = 400 переключений и 1.4 с на прогон, из которых
    # сама индексация — малая часть.
    try:
        indexed = await asyncio.to_thread(_index_batch_ops, naming, pending)
    except Exception:  # noqa: BLE001
        _COUNTERS["index_errors"] += 1
        logger.debug("live plan index failed", exc_info=True)
        indexed = [(record, ()) for record in pending]

    touched: list[str] = []
    for record, labels in indexed:
        for label, considered in labels:
            entry.level_index.setdefault(label, [])
            if record.seq not in entry.level_index[label]:
                entry.level_index[label].append(record.seq)
            entry.level_tally[label] = (
                entry.level_tally.get(label, 0) + considered)
            if label not in touched:
                touched.append(label)
        # Сводка инкрементальная: O(операций новой программы), а не O(здания).
        for op in record.ops:
            name = str(op.get("op", "?"))
            entry.op_tally[name] = entry.op_tally.get(name, 0) + 1
        entry.indexed_upto = record.seq + 1

    limit = _levels_per_frame()
    drawn = touched[-limit:] if len(touched) > limit else touched
    not_drawn = len(touched) - len(drawn)

    for label in drawn:
        ops, dropped_programs, pack = _slice_for(entry, label)
        if not ops:
            continue
        started = time.perf_counter()
        try:
            frame = await asyncio.to_thread(_render_frame, ops, label)
        except Exception:  # noqa: BLE001 — рисовальщик падает В ОДИНОЧКУ
            _COUNTERS["render_errors"] += 1
            logger.debug("live plan render failed", exc_info=True)
            continue
        finally:
            _COUNTERS["render_ms_total"] += (
                time.perf_counter() - started) * 1000.0
        _COUNTERS["renders"] += 1
        frame["slice_ops"] = len(ops)
        # УСЕЧЁННЫЙ СРЕЗ ОБЯЗАН БЫТЬ НАЗВАН. Лист, на котором нет двадцати
        # первых программ этажа, и лист, на котором их не было, выглядят
        # одинаково — и это ровно тот класс молчания, ради запрета которого
        # написана перепись `preview`.
        frame["slice_truncated_programs"] = dropped_programs
        if dropped_programs:
            frame["slice_truncated_ru"] = (
                f"на листе НЕ ПОКАЗАНЫ самые ранние программы этажа: "
                f"{dropped_programs} — срез ограничен")
        frame.update({
            "type": "kir_plan",
            "schema": FRAME_SCHEMA,
            "stage": "planned",
            "seq": entry.indexed_upto,
            "summary": entry.summary(),
            "journal": entry.stats(),
            "levels_not_drawn": not_drawn,
            "dropped_frames": _COUNTERS["dropped_frames"],
        })
        # ВИТРИНА. Кадр уходит человеку не только картинкой, но и ПОДПИСЬЮ
        # своей программы; тело остаётся здесь. Это и есть закон «что видел, то
        # и построится»: панель называет подпись, а операции исполнителю
        # выдаёт витрина — назвать программу, которой не показывали, нечем.
        #
        # Единица — ПАЧКА (`pack`), а не склеенный список: границы программ на
        # листе не видно, а компилятор судит именно программу (бюджет,
        # solo-опы, транзакция).
        #
        # Промах витрины НЕ отменяет кадр: картинка полезна и без кнопки.
        # Поэтому `transferable` — отдельное поле, а не молчаливое «ну как-то
        # же оно перенесётся».
        try:
            shown = _showroom.show(
                session_key, level=frame.get("level", label),
                programs=pack, context=list(entry.datums),
                census=frame.get("census") or {}, seq=entry.indexed_upto,
                ts=time.time())
        except Exception:  # noqa: BLE001 — витрина не имеет права ронять кадр
            shown = None
            _COUNTERS["showroom_errors"] += 1
        if shown is not None:
            frame["program_digest"] = shown.digest
            frame["program_ops"] = shown.op_count
            frame["program_count"] = len(shown.programs_json)
            frame["transferable"] = True
        else:
            frame["transferable"] = False
            frame["transfer_blocked_ru"] = (
                "перенос недоступен для этого кадра: программу не удалось "
                "подписать (см. showroom_errors)")
        await _send(device_id, frame)

    if behind:
        # Пачка кончилась, журнал — нет. Ставим будильник себе, чтобы курсор
        # догнал голову за несколько ОГРАНИЧЕННЫХ проходов, а не за один
        # неразрывный. Очередь полна — не беда: работник и так вернётся сюда.
        queue = _queue
        if queue is not None:
            try:
                queue.put_nowait(session_key)
            except asyncio.QueueFull:
                _COUNTERS["dropped_frames"] += 1


def _index_batch_ops(naming: list[Mapping[str, Any]], records: list
                     ) -> list[tuple[Any, tuple[tuple[str, int], ...]]]:
    """Разметить пачку программ по этажам — ОДИН заход в рабочий поток."""
    out = []
    for record in records:
        try:
            out.append((record, _levels_of(naming + list(record.ops))))
        except Exception:  # noqa: BLE001 — одна кривая программа не роняет пачку
            _COUNTERS["index_errors"] += 1
            out.append((record, ()))
    return out


def _slice_for(entry: Any, label: str) -> tuple[list, int, list]:
    """СРЕЗ ПО ЭТАЖУ, а не всё здание.
    -> (операции, сколько программ НЕ вошло, ПАЧКА программ).

    Третьим значением едет пачка — те же программы, но НЕ склеенные. Склейка
    нужна рисовальщику (лист один), пачка — витрине и переносу: компилятор
    судит программу целиком (бюджет, solo-опы, одна транзакция), и склеенный
    список из десяти программ он справедливо отверг бы как одну гигантскую.

    Наивный союз всех программ сессии даёт квадратичную работу: каждый новый
    кадр перерисовывал бы всё накопленное (замер K2 — 9.3 с на три этажа). Сюда
    попадают только программы, ЗАТРОНУВШИЕ этот этаж, плюс датумы; программа по
    соседнему этажу в работу кадра не входит вовсе.

    Гранулярность — ПРОГРАММА, а не операция: программа, задевшая два этажа,
    целиком попадает в оба среза, а лишние операции честно уходят в перепись
    как `LEVEL_NOT_IN_RUN`. Резать по операциям значило бы завести ВТОРОЙ
    экземпляр правила «какому этажу принадлежит операция» — первый живёт в
    `preview._op_level_key`, и два источника правды об одном дороже, чем
    немного лишней работы на редкой двухэтажной программе.

    ПОЧЕМУ СВЕРХУ ЕЩЁ И ПОТОЛОК. Отрисовка линейна по размеру среза, а срез
    растёт всю сессию: замер 03.08 — 543 мс на кадр при 2 800 операциях одного
    этажа, то есть на потолке журнала кадр стоил бы секунды. Считается это
    питоном, под GIL, и хотя работа вынесена в поток, длинный кадр всё равно
    отнимает такты у хода. Потолок бьёт по САМЫМ РАННИМ программам (свежее
    важнее) и НАЗЫВАЕТ, сколько выброшено.
    """
    cap = _slice_ops_cap()
    seqs = entry.level_index.get(label, ())
    records = entry.by_seqs(seqs)
    kept: list = []
    total = 0
    for record in reversed(records):
        if total + record.op_count > cap and kept:
            break
        kept.append(record)
        total += record.op_count
    kept.reverse()
    ops = list(entry.datums)
    pack: list[list] = []
    for record in kept:
        ops.extend(record.ops)
        pack.append(list(record.ops))
    return ops, len(records) - len(kept), pack


def _levels_of(ops: list[Mapping[str, Any]]) -> tuple[tuple[str, int], ...]:
    """(метка этажа, сколько операций ему предъявлено) — целиком из `preview`.

    ШОВ, КОТОРЫЙ НУЖЕН В `preview.py` (правку проводит лид отдельно). Здесь
    строится ПОЛНЫЙ `BuildingPreview` ради двух полей — меток этажей и
    `census.considered`; формы всех элементов при этом считаются и тут же
    выбрасываются. Нужен публичный дешёвый `preview.program_level_index(ops)
    -> tuple[tuple[str, int], ...]`, который проходит операции, раскладывает по
    `_op_level_key`/`_selector_key` и НЕ строит `DrawnElement`. Замер стоимости
    этого шва — в отчёте волны; переписывать правило принадлежности здесь
    нельзя, это был бы второй источник правды.
    """
    from kukai.ir.preview import build_program_preview
    building = build_program_preview(ops)
    return tuple((plan.level_name, plan.census.considered)
                 for plan in building.plans)


def _render_frame(ops: list[Mapping[str, Any]], label: str) -> dict:
    """Один лист плана. Тяжёлая часть, поэтому исполняется в потоке."""
    from kukai.ir.preview import build_program_preview, census_lines, render_svg
    building = build_program_preview(ops, levels=[label])
    try:
        plan = building.plan(label)
    except KeyError:
        raise ValueError(f"этаж {label!r} не собрался в лист") from None
    return {
        "level": plan.level_name,
        # ЧЕСТНОСТЬ ИСТОЧНИКА едет с кадром, а не подразумевается: `assertion`
        # приходит из `preview.PreviewSource.PROGRAM`, а не выставляется здесь.
        "assertion": plan.assertion.value,
        "assertion_ru": ("ЗАЯВЛЕНО программой — модель не читалась"
                         if plan.assertion.value == "self_reported"
                         else "независимое чтение модели"),
        "source": plan.source.value,
        "content_digest": plan.content_digest,
        "svg": render_svg(plan),
        "census": plan.census.to_dict(),
        # ПЕРЕПИСЬ ЕДЕТ РЯДОМ С КАРТИНКОЙ, А НЕ ТОЛЬКО ВНУТРИ НЕЁ. Подвал листа
        # печатает столько строк, сколько влезает (и называет остаток), а лист
        # в панели сжат до ширины карточки — читать подвал 11.5 px там нечем.
        # Панели строки нужны текстом, целиком и по-русски: красивая картинка
        # без переписи это красивая неправда.
        "census_lines": list(census_lines(plan.census)),
        "meta": plan.to_dict(),
    }


async def _send(device_id: str, payload: dict) -> None:
    transport = _transport
    if transport is None:
        return
    try:
        await asyncio.wait_for(
            transport(device_id, payload), timeout=_send_timeout_s())
        _COUNTERS["frames_sent"] += 1
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — отвалившийся сокет это не наша беда
        _COUNTERS["send_errors"] += 1
        logger.debug("live plan frame send failed", exc_info=True)


# ── кран ────────────────────────────────────────────────────────────────────

def publish(*, device_id: Optional[str], doc_key: str = "",
            program: Any = None, plan_digest: str = "",
            author_digest: str = "", source: str = "") -> None:
    """ЕДИНСТВЕННЫЙ вход потока. Синхронный, без ожиданий, никогда не бросает.

    Порядок в теле — не стиль, а договор:
      1) программа ложится в ЖУРНАЛ (первичный артефакт, не выбрасывается);
      2) и только потом решается, будить ли рисовальщика.
    Обратный порядок означал бы, что при переполнении очереди теряется не
    картинка, а исходный код здания.
    """
    try:
        if not enabled():
            _COUNTERS["skipped_disabled"] += 1
            return
        _COUNTERS["published"] += 1
        key = _journal.key_for(device_id, doc_key)
        record = _journal.append(
            key, program, plan_digest=plan_digest,
            author_digest=author_digest, source=source)
        if record is None:
            return
        _COUNTERS["journaled"] += 1
        if not attached(key[0]):
            # Панель не подключена — рисование не запускается ВОВСЕ.
            _COUNTERS["skipped_no_panel"] += 1
            return
        queue = _ensure_worker()
        if queue is None:
            return
        try:
            queue.put_nowait(key)
            _COUNTERS["queued"] += 1
        except asyncio.QueueFull:
            # Копить нельзя: очередь без потолка — это утечка, отложенная во
            # времени. Выброшенный будильник стоит одной картинки (см. шапку).
            _COUNTERS["dropped_frames"] += 1
    except Exception:  # noqa: BLE001 — АБСОЛЮТНЫЙ fail-open
        logger.debug("live plan publish failed (fail-open)", exc_info=True)


# ── приборы ─────────────────────────────────────────────────────────────────

async def drain(timeout: float = 10.0) -> bool:
    """Дождаться, пока работник разгребёт очередь. Только для замеров/тестов."""
    if _idle is None:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (_queue is None or _queue.empty()) and _idle.is_set():
            return True
        await asyncio.sleep(0.01)
    return False


def stats() -> dict[str, Any]:
    out = dict(_COUNTERS)
    out["attached_devices"] = len(_attached)
    out["queue_depth"] = _queue.qsize() if _queue is not None else 0
    out["queue_max"] = _queue_max()
    out["transport_bound"] = _transport is not None
    out["journal"] = _journal.stats()
    out["showroom"] = _showroom.stats()
    return out


def reset() -> None:
    """Сбросить счётчики, канал, подключения и работника. Для замеров/тестов."""
    global _worker_task, _worker_loop, _queue, _idle, _transport
    with _worker_lock:
        if _worker_task is not None and not _worker_task.done():
            _worker_task.cancel()
        _worker_task = None
        _worker_loop = None
        _queue = None
        _idle = None
    with _STATE_LOCK:
        _attached.clear()
    _transport = None
    for name in _COUNTERS:
        _COUNTERS[name] = 0.0 if name.endswith("_total") else 0
    _journal.reset()
    _showroom.reset()
