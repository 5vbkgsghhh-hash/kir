"""ПОТЕРЯ СВЯЗИ — НЕ «ВНУТРЕННЯЯ ОШИБКА». Отказ обязан называть причину.

ПОВОД ЗАМЕРЕН ЖИВЬЁМ (03.08.2026): мост рвался **4571 раз за 2 часа 45 минут**
(`close_code=1006`), и обработчики KIR отвечали на это плоским отказом
`"internal"`, который таблица `_FLAT_ERROR_TO_ERRCODE` переводит в
`internal.unhandled`. А у этого кода в `ERR_PROPS` стоит
`(retryable=False, transient=False)`.

ЧТО ЭТО ЗНАЧИТ НА ПРАКТИКЕ. Модели сообщают: «наша внутренняя поломка, повторять
бессмысленно» — ровно в тот момент, когда правда противоположна: связь пропала,
и повтор через пару секунд сработает. Модель бросает задачу, оператор видит
«КУКАИ сломался», а сломан был провод. Причём НУЖНЫЙ код в таксономии есть с
самого начала — `transport.bridge_disconnected`, помеченный
`(retryable=True, transient=True)`, — но до него никто не доводил исключение.

ПОЧЕМУ ЭТО ЛОВИТСЯ ТОЛЬКО ТАК. `classify_bridge_error` разбирает ПРОЗУ моста и
работает, когда мост ОТВЕТИЛ. Оборванный сокет прозы не приносит: он приходит
ИСКЛЮЧЕНИЕМ, минует классификатор целиком и падает в общий `except Exception`.
Поэтому проверять надо не текст, а тип исключения.

ГРАНИЦА, КОТОРУЮ ТЕСТ ТОЖЕ СТЕРЕЖЁТ: пере-классификация обязана быть
УЗКОЙ. Настоящая внутренняя ошибка (`KeyError`, `TypeError`, `ValueError`),
названная транспортной, отправила бы модель повторять программу, которая
сломана детерминированно, — то есть заменила бы одну ложь другой. Отказ по
умолчанию остаётся `internal`.
"""
from __future__ import annotations

import asyncio

import pytest

from kukai.ir.serving import (
    _FLAT_ERROR_TO_ERRCODE, _failure_stage, _transport_stage)
from kukai.llm.envelope import ERR_PROPS, ErrCode


class _FakeConnectionClosed(Exception):
    """Двойник `websockets.exceptions.ConnectionClosed`.

    Настоящий класс живёт в стороннем пакете, и завязывать ядро KIR на его
    импорт значило бы получить `ImportError` в окружении без websockets. Опознание
    идёт по ИМЕНИ класса — тем же приёмом, которым `_transport_stage` работает в
    проде, поэтому двойник проверяет ровно тот путь, что и живой обрыв.
    """

    __name__ = "ConnectionClosed"


_FakeConnectionClosed.__name__ = "ConnectionClosed"


class _FakeConnectionClosedError(Exception):
    pass


_FakeConnectionClosedError.__name__ = "ConnectionClosedError"


DISCONNECTS = [
    ConnectionResetError("[Errno 104] Connection reset by peer"),
    BrokenPipeError("[Errno 32] Broken pipe"),
    ConnectionAbortedError("software caused connection abort"),
    ConnectionError("bridge socket is gone"),
    _FakeConnectionClosed("received 1006 (abnormal closure)"),
    _FakeConnectionClosedError("no close frame received or sent"),
]

TIMEOUTS = [
    asyncio.TimeoutError(),
    TimeoutError("bridge did not answer in time"),
]

GENUINELY_INTERNAL = [
    KeyError("op_id"),
    TypeError("unsupported operand"),
    ValueError("bad literal"),
    AttributeError("'NoneType' object has no attribute 'id'"),
    ZeroDivisionError("division by zero"),
]


@pytest.mark.parametrize("exc", DISCONNECTS, ids=lambda e: type(e).__name__)
def test_a_dead_socket_is_named_a_dead_socket(exc: Exception) -> None:
    """Обрыв связи опознаётся по типу исключения, а не по тексту."""
    assert _transport_stage(exc) == "bridge_disconnected", (
        f"{type(exc).__name__} — это потеря связи, а не внутренняя ошибка; "
        "модели скажут «не повторяй» там, где повтор и есть лекарство")


@pytest.mark.parametrize("exc", TIMEOUTS, ids=lambda e: type(e).__name__)
def test_a_silent_bridge_is_named_a_timeout(exc: Exception) -> None:
    assert _transport_stage(exc) == "bridge_timeout"


@pytest.mark.parametrize("exc", GENUINELY_INTERNAL, ids=lambda e: type(e).__name__)
def test_a_real_bug_stays_internal(exc: Exception) -> None:
    """Узость границы — половина ценности правила.

    Назвать `KeyError` транспортом значит отправить модель повторять
    детерминированно сломанную программу. Одна ложь заменилась бы другой.
    """
    assert _transport_stage(exc) is None, (
        f"{type(exc).__name__} — настоящий дефект, и он обязан остаться "
        "internal: повтор его не вылечит")


def test_the_named_stages_reach_the_right_taxonomy_codes() -> None:
    """Имя стадии бесполезно, если таблица не доводит его до кода."""
    assert _FLAT_ERROR_TO_ERRCODE["bridge_disconnected"] is (
        ErrCode.TRANSPORT_BRIDGE_DISCONNECTED)
    assert _FLAT_ERROR_TO_ERRCODE["bridge_timeout"] is (
        ErrCode.TRANSPORT_BRIDGE_TIMEOUT)


def test_the_whole_point_is_the_retry_flag() -> None:
    """РАДИ ЧЕГО ВСЁ: у транспортных кодов повтор РАЗРЕШЁН, у internal — нет.

    Этот тест не про имена, а про поведение, которое имена включают. Если
    когда-нибудь `transport.*` перестанет быть retryable, правило потеряет
    смысл, и упасть обязано здесь, а не на живом мосту.
    """
    for code in (ErrCode.TRANSPORT_BRIDGE_DISCONNECTED,
                 ErrCode.TRANSPORT_BRIDGE_TIMEOUT):
        retryable, transient = ERR_PROPS[code]
        assert retryable and transient, (
            f"{code.value} обязан быть retryable+transient — иначе "
            "переименование ничего не меняет для модели")
    assert ERR_PROPS[ErrCode.INTERNAL_UNHANDLED] == (False, False)


def test_a_chained_cause_is_still_seen() -> None:
    """Обрыв, завёрнутый в чужое исключение, обязан быть найден.

    Живой путь этого требует: `run_decompile` оборачивает сбой транспорта своим
    RuntimeError, и без обхода цепочки `__cause__` правило сработало бы только
    на голом исключении, то есть почти никогда.
    """
    inner = ConnectionResetError("[Errno 104] Connection reset by peer")
    outer = RuntimeError("decompile stage failed")
    outer.__cause__ = inner
    assert _transport_stage(outer) == "bridge_disconnected"


def test_a_real_bug_keeps_its_exact_old_message() -> None:
    """Побайтовая устойчивость честного пути.

    Правило добавляет ветку, а не переписывает поведение: настоящая внутренняя
    ошибка обязана отвечать ДОСЛОВНО тем же, чем отвечала до правки, иначе
    «мы ничего не сломали» — обещание, а не факт.
    """
    for what in ("декомпайла", "rebuild", "идемпотентности"):
        assert _failure_stage(KeyError("op"), what) == (
            "internal", f"внутренняя ошибка {what}")


def test_the_user_is_told_what_to_do_not_just_what_broke() -> None:
    """Отказ обязан нести действие, иначе он бесполезен читателю."""
    stage, message = _failure_stage(ConnectionResetError(104), "rebuild")
    assert stage == "bridge_disconnected"
    assert "повтори" in message
    # Главное для доверия: сказать, что модель НЕ пострадала.
    assert "не изменялась" in message


def test_the_search_through_causes_is_bounded() -> None:
    """Цепочка причин не должна становиться бесконечным циклом.

    Самоссылающееся исключение — не выдумка: оно получается при повторном
    `raise ... from ...` в цикле восстановления. Обход обязан завершиться.
    """
    loop_exc = RuntimeError("boom")
    loop_exc.__cause__ = loop_exc
    assert _transport_stage(loop_exc) is None
