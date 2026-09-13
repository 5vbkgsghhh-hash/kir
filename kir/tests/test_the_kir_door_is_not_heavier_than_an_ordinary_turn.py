"""РЕЖИМ КИР НЕ ИМЕЕТ ПРАВА БЫТЬ ТЯЖЕЛЕЕ ОБЫЧНОГО ХОДА ТОЙ ЖЕ МОДЕЛИ.

🔴 СЛОВО ВЛАДЕЛЬЦА 13.09.2026: «дипсик можем в ревите строить. значит он должен
это делать в КИР и делать это еще успешнее». Мозг остаётся DeepSeek — значит
менять надо не мозг, а то, что мы кладём ему на вход.

ЗАМЕР ТОГО ЖЕ ДНЯ, обе стороны:
    обычный ход: `execute_revit_code` — описание 931 знак + схема 1 701 = 2 632
    ход КИР:     `revit_ir`          — описание 29 874 + схема 61 591 (после
                                        свёртки в `$defs`) ≈ 91 465

И живой исход этой разницы — ход владельца `530f4ed7` (18:11:36→18:14:30Z,
«построй сарай»): **174 291 мс, 0 знаков текста, 0 вызовов инструментов**,
остановлен рукой. В кассете рассуждения (55 434 знака, сохранена в
`.work/prod-20260913/K-panel/shots/loop_reasoning.txt`) четыре блока правил
повторены по **77 раз**: модель пересказывала справочник сама себе.

Здесь прибит ПОТОЛОК краткой справки чат-двери и то, что она не потеряла
несущего: две формы входа, предел программы (числом ИЗ КОМПИЛЯТОРА, а не
литералом), идиому типа и готовые примеры программ.
"""
from __future__ import annotations

import re

from kir.compiler import MAX_OPS_PER_PROGRAM
from kir.tool_doc import (BRIEF_DESCRIPTION_LIMIT_CHARS,
                          build_tool_description,
                          build_tool_description_brief)


def test_the_brief_fits_the_ceiling():
    краткая = build_tool_description_brief()
    assert len(краткая) <= BRIEF_DESCRIPTION_LIMIT_CHARS, len(краткая)
    # КОНТРОЛЬ-ПАРА: полная справка НЕ обрезана — она на месте для MCP-двери.
    # Прибор, зелёный оттого, что исчезли ОБЕ, сторожил бы потерю.
    assert len(build_tool_description()) > 10 * len(краткая)


def test_the_brief_is_lighter_than_the_full_by_an_order():
    краткая, полная = build_tool_description_brief(), build_tool_description()
    assert len(краткая) * 10 <= len(полная), (len(краткая), len(полная))


def test_the_cap_agrees_with_the_compiler_and_is_not_a_literal():
    """Число предела — из компилятора. Сказать модели 20 там, где компилятор
    держит другое, уже стоило отказанной программы (KIR-L001, 27.07.2026)."""
    caps = re.findall(r"(?:Потолок|Бюджет[^.\n]{0,40}?)\s*[—–-]?\s*(\d+)\s+операц",
                      build_tool_description_brief())
    assert caps, "предел программы не назван ни одной формулировкой"
    assert all(int(c) == MAX_OPS_PER_PROGRAM for c in caps), (caps, MAX_OPS_PER_PROGRAM)


def test_the_brief_keeps_what_the_model_cannot_infer():
    краткая = build_tool_description_brief()
    assert "это ТИП, а не параметр" in краткая, "идиома типа потеряна"
    assert "`program`" in краткая and "`program_py`" in краткая, "две формы входа"
    for адрес in ("spec(", "example", "rehearse", "created"):
        assert адрес in краткая, f"адрес {адрес!r} не назван — знание стало недоступным"


def test_the_brief_carries_the_envelope_contract_not_examples():
    """🔴 СЛОВО ВЛАДЕЛЬЦА 13.09.2026: «примеры программ это плохо. нужно только
    КИР сдк ему знать». Первая редакция этой справки несла пять готовых
    программ; они сняты. Остаётся КОНТРАКТ: как выглядит конверт входа.

    Мой довод «модель с образцом подражает, без образца пересказывает правила»
    остаётся ГИПОТЕЗОЙ и проверяется замером раздела S, а не этим пином.
    """
    from kir import spec as _spec

    краткая = build_tool_description_brief()
    assert '"ir_version"' in краткая, "конверт входа не назван"
    assert f'"{_spec.IR_VERSION}"' in краткая, "версия конверта не из схемы"
    assert '"ops"' in краткая and '"op"' in краткая, "форма операций не названа"
    assert '"by":"ref"' in краткая, "адресация своего не названа"
    # Ни одной ГОТОВОЙ программы: имён операций в справке быть не должно вовсе —
    # список имён живёт за `spec()`, а не в подсказке.
    примеры = re.findall(r'"op"\s*:\s*"(create_[a-z_]+|query_[a-z_]+)"', краткая)
    assert not примеры, f"в справку вернулись готовые программы: {примеры}"


def test_the_brief_names_no_operation_by_name():
    """Список имён — по запросу (`spec()` без аргумента), а не в подсказке: имя
    в прозе стареет молча, а `spec()` порождается из реестра."""
    from kir import spec as _spec

    краткая = build_tool_description_brief()
    названные = sorted(set(re.findall(r"\b(create_[a-z_]+|query_[a-z_]+)\b", краткая)))
    assert not названные, f"справка перечисляет операции вместо адреса: {названные}"
    assert "spec()" in краткая, "не назван адрес списка имён"
    assert 'spec("' in краткая, "не назван адрес контракта одной операции"
    # КОНТРОЛЬ: реестр не пуст — иначе «имён нет» зеленело бы на пустом реестре.
    assert len(_spec.OPS) > 50, "контроль негоден: реестр операций пуст"


def test_the_counts_come_from_the_registry_not_from_prose():
    from kir import spec as _spec

    краткая = build_tool_description_brief()
    пишущие = sum(1 for op in _spec.OPS.values() if op.writes_model)
    читающие = sum(1 for op in _spec.OPS.values() if not op.writes_model)
    assert f"Пишущих операций {пишущие}" in краткая, краткая[:200]
    assert f"читающих {читающие}" in краткая
