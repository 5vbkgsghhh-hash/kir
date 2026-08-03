"""Живой доклад с хода — чтобы экран не был мёртвым, пока модель работает.

ЗАЧЕМ. Замер 29.07 на настоящей работе оператора («смоделируй Эйфелеву башню»):
за десять минут ход сделал 8 вызовов инструментов, 5 записей в модель и 176
чтений — и отдал на экран **ноль** событий прогресса и **ноль** символов текста.
Модель на каждом раунде вызывала инструмент молча. Человек несколько минут
смотрел в пустоту и написал «она ушла в глухое молчание, куда-то прям исчезла».

Полоска прогресса в интерфейсе есть и работает, но питается сообщением
`bridge_progress` от C#-моста во время пакетных операций — KIR его не шлёт.

ПОЧЕМУ ДОКЛАДЫВАЕТ СЕРВЕР, А НЕ МОДЕЛЬ. Просить модель комментировать свои
действия — уговор: забудет, сократит, или как в том прогоне не напишет ни слова.
Сервер же ЗНАЕТ точно: сколько элементов создано, за сколько миллисекунд, что
сказали свидетели. Доклад из этого места не зависит от того, в настроении ли
модель разговаривать.

ПОБОЧНАЯ ПОЛЬЗА, которая может оказаться главной. Строка доклада попадает не
только на экран, но и в переписку. Сегодня история хода состоит из вызовов и
результатов инструментов при пустых ответах ассистента — если ход оборвать
между отправкой программы в Revit и возвратом квитанции, элементы в модели
появятся, а в истории следа не останется, и следующий ход может построить их
заново.

ГРАНИЦА. Модуль знает только про «отправить словарь в чат». Кто именно шлёт —
задаёт вызывающий (`bind`), поэтому ни `kukai.ir`, ни пайплайн не тянут за
собой веб-слой. Всё fail-open: доклад не может уронить ход.
"""
from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

#: Куда слать. Ставится один раз за ход там, где есть сокет клиента.
_sink: ContextVar[Optional[Callable[[dict], Awaitable[None]]]] = ContextVar(
    "kukai_turn_progress_sink", default=None)

#: Счётчик кругов в пределах хода. Мутабельный словарь на тот же случай, что и
#: в codex_route: исполнение инструмента может идти в копии контекста, и
#: обычный ContextVar.set() оттуда не вернётся к родителю.
_counter: ContextVar[Optional[dict]] = ContextVar(
    "kukai_turn_progress_counter", default=None)


def enabled() -> bool:
    """Выключатель на весь механизм. Выключенный = поведение до 29.07."""
    return os.environ.get("KUKAI_TURN_PROGRESS", "1") != "0"


def bind(sink: Optional[Callable[[dict], Awaitable[None]]]) -> None:
    """Привязать канал к экрану на этот ход. Вызывается в run_turn."""
    _sink.set(sink)
    _counter.set({"writes": 0, "reads": 0, "elements": 0})


def stats() -> dict:
    """Что уже сделано за ход. Пустой словарь вне хода."""
    c = _counter.get()
    return dict(c) if isinstance(c, dict) else {}


def _plural_elements(n: int) -> str:
    """«1 элемент» / «2 элемента» / «5 элементов» — строка идёт человеку."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "элемент"
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return "элемента"
    return "элементов"


async def report_write(created: int, ms: int, note: str = "") -> None:
    """Доложить об исполненной программе записи."""
    c = _counter.get()
    if isinstance(c, dict):
        c["writes"] = int(c.get("writes", 0)) + 1
        c["elements"] = int(c.get("elements", 0)) + max(0, int(created or 0))
    if created > 0:
        text = f"построено {created:,} {_plural_elements(created)}".replace(",", " ")
    else:
        text = "программа выполнена"
    if note:
        text += f" — {note}"
    await _emit({"kind": "write", "message": text,
                 "current": (c or {}).get("writes", 0), "total": 0,
                 "elapsed_ms": int(ms or 0)})


async def report_failure(reason: str = "") -> None:
    """Доложить, что программа НЕ прошла.

    Первая версия рапортовала только об успехе, и живой ход 29.07 поймал это в
    тот же час: запись упала (`state: failed`), а на экран не ушло ничего — та
    самая тишина, от которой всё затевалось. Неудача — момент, когда человеку
    важнее всего видеть «не получилось, пробую иначе»: иначе пауза на ремонт
    неотличима от зависания.

    Причину показываем короткой: длинный диагностический текст на экране
    пугает и не помогает, а полный разбор всё равно уходит в ответ модели."""
    c = _counter.get()
    if isinstance(c, dict):
        c["failures"] = int(c.get("failures", 0)) + 1
    short = (reason or "").strip().split("\n")[0][:90]
    await _emit({"kind": "failure",
                 "message": "не получилось" + (f": {short}" if short else "") + " — пробую иначе",
                 "current": (c or {}).get("failures", 0), "total": 0})


async def report_read(note: str = "") -> None:
    """Доложить о круге проверки. Счётчик здесь важнее текста: именно он делает
    ВИДИМЫМ бесконечное самопроверяние — 29.07 ход сделал 176 чтений на 5
    записей, и заметить это можно было только по журналу."""
    c = _counter.get()
    if isinstance(c, dict):
        c["reads"] = int(c.get("reads", 0)) + 1
        n = c["reads"]
    else:
        n = 0
    # Первые круги показываем каждый, дальше — реже: сто одинаковых строк
    # «проверяю» это тот же пустой экран, только шумный.
    if n > 5 and n % 10:
        return
    await _emit({"kind": "read",
                 "message": f"проверяю построенное ({n})" + (f" — {note}" if note else ""),
                 "current": n, "total": 0})


async def _emit(payload: dict[str, Any]) -> None:
    if not enabled():
        return
    sink = _sink.get()
    if sink is None:
        return
    try:
        await sink({"type": "tool_progress", **payload})
    except Exception:  # noqa: BLE001 — экран не может ломать ход
        logger.debug("turn progress emit failed", exc_info=True)
