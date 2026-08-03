"""Молчащий Revit — не ошибка инструмента, и повторять в него нельзя.

Замерено вживую 29.07 на устройстве пользователя: шесть `execute_revit_code`
подряд, каждый ждал полный таймаут моста (~40 с) и не получил ответа вовсе.
Пользователь просидел 10.5 минут в тишине и написал «завис».

Существовавшая защита не могла помочь дважды. Во-первых, она считает ошибки
ПО ИНСТРУМЕНТУ и срабатывает на третьей — то есть после двух минут молчания.
Во-вторых, её подсказка советует «попробовать другой подход», а когда до Revit
не доходит ничего, другого подхода не существует.

Порог здесь 2, а не 3, ровно по цене: третья попытка не приносит информации,
только ещё 40 секунд тишины. Одного повтора хватает на честно случайный сбой.
"""
from __future__ import annotations

import inspect

import pytest

from kukai.llm.client import (
    _BRIDGE_SILENT_HINT,
    _MAX_BRIDGE_SILENCE,
    _looks_like_a_silent_bridge,
)

SILENT = [
    '{"tool": "execute_revit_code", "state": "timeout_unconfirmed"}',
    "Revit не подтвердил завершение за 40с. Операция не будет повторена вслепую.",
    '{"err": {"code": "transport.bridge_timeout", "retryable": true}}',
    '{"err_code": "TRANSPORT_BRIDGE_TIMEOUT"}',
]

ANSWERED = [
    '{"error": true, "message": "CS0103: имя doc не найдено"}',
    '{"ok": true, "created_id": "1290279"}',
    '{"error": "Element not found"}',
    "",
]


@pytest.mark.parametrize("blob", SILENT)
def test_a_bridge_that_never_answered_is_recognised(blob):
    assert _looks_like_a_silent_bridge(blob) is True


@pytest.mark.parametrize("blob", ANSWERED)
def test_an_answer_that_happens_to_be_an_error_is_not(blob):
    """Ошибка компиляции — это ОТВЕТ: Revit жив, код плохой, повторять осмысленно.
    Спутать их значит прекращать ход там, где надо чинить код."""
    assert _looks_like_a_silent_bridge(blob) is False


def test_two_strikes_not_three():
    assert _MAX_BRIDGE_SILENCE == 2


def test_the_hint_tells_the_user_what_to_do_not_the_model_what_to_try():
    """Подсказка адресована человеку у экрана: причина почти всегда — открытый
    в Revit диалог, и её не обойти никаким кодом."""
    assert "диалог" in _BRIDGE_SILENT_HINT
    assert "ПРЕКРАТИ" in _BRIDGE_SILENT_HINT
    assert "Не пытайся обойти" in _BRIDGE_SILENT_HINT


def test_the_guard_is_actually_wired_into_the_round_loop():
    """Правило достижимости: гейт, до которого никто не доходит, — это тот же
    revit_ir, невидимый неделями."""
    from kukai.llm import client

    src = inspect.getsource(client)
    assert "_looks_like_a_silent_bridge(result_str)" in src
    assert "_bridge_silent >= _MAX_BRIDGE_SILENCE" in src
    assert "_bridge_silent = 0" in src, "счётчик должен сбрасываться на успехе"


def test_the_counter_resets_on_a_successful_call():
    """Иначе два разнесённых по ходу сбоя сложатся в ложное «Revit молчит»."""
    from kukai.llm import client

    src = inspect.getsource(client)
    success_reset = src.index("_reset_tool_error(state.consecutive_errors, tool_name)")
    counter_reset = src.index("_bridge_silent = 0", success_reset)
    assert counter_reset - success_reset < 200, (
        "сброс счётчика должен стоять в ветке успеха, рядом с _reset_tool_error")
