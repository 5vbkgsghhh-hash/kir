"""ОДОБРЕНИЕ СЛИВАЕТСЯ В ЗДАНИЕ, А НЕ КЛАДЁТСЯ ПОВЕРХ НЕГО.

🔴 ЧЕМ КУПЛЕНО (13.09.2026, слово владельца дословно): «когда мы тыкаем во
вьюере одобрить, то оно грамотно мержится в основное здание». «Грамотно» —
это одно проверяемое свойство, и вот его цена, замеренная на живом Ревите
2023 в тот же день (квитанции S): повторная публикация либо отказывает
целиком (`live-20260913-slice-receipt.json`), либо ДУБЛИРУЕТ целиком —
стены 4→8→12, перекрытия 1→2→3, экземпляры 3913→3938→3968
(`live-20260913-slice-opening-receipt.json`). Вторая стена поверх первой —
не гипотеза, она измерена.

ЧТО ЗДЕСЬ СТЕРЕЖЁТСЯ. НЕ решение keep/update/create — его принимает
`project_republish.plan_republish` (надел S) и стерегут его собственные
тесты. Здесь стережётся КЛЕЙ: что дверь переноса ЗОВЁТ это решение, что
исполняется ПРОИЗВОДНАЯ программа, а не сырая, и что повтор не доходит до
исполнителя ни одним вызовом.

КОНТРОЛЬ ВНУТРИ КАЖДОГО АКТА. «Дублей нет» зеленеет на пустой программе,
поэтому каждый акт сперва доказывает, что мерить есть что: без прошлой
публикации та же программа даёт СЕМЬ операций создания. Разница между
семью и нулём — и есть предмет.
"""
from __future__ import annotations

import asyncio

import pytest

from kir.serving import handle_revit_ir, republish_for_transfer

LEVEL, WALL_TYPE, FLOOR = "1" * 64, "3" * 64, "8" * 64
WALLS = [str(index) * 64 for index in (4, 5, 6, 7)]


def section(*, height_mm: int = 3000) -> dict:
    corners = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 6000.0], [0.0, 6000.0]]
    ops: list[dict] = [
        {"op": "create_level", "id": LEVEL, "elev_mm": 0, "name": "Уровень 1"},
        {"op": "create_wall_type", "id": WALL_TYPE, "host_kind": "wall",
         "new_name": "секция", "source_type": {"by": "name", "value": "Типовой"},
         "layers": [{"width_mm": 230, "function": "Structure",
                     "material": "Бетон"}]}]
    for index in range(4):
        ops.append({"op": "create_wall", "id": WALLS[index],
                    "p0_mm": corners[index], "p1_mm": corners[(index + 1) % 4],
                    "height_mm": height_mm,
                    "level": {"by": "ref", "value": LEVEL},
                    "type": {"by": "ref", "value": WALL_TYPE}})
    ops.append({"op": "create_floor_by_contour", "id": FLOOR,
                "level": {"by": "ref", "value": LEVEL},
                "contour": {"outer": {"shape": "poly", "points_mm": corners}}})
    return {"ir_version": "1.0", "intent": "секция", "lineage": "sec", "ops": ops}


def published(program: dict) -> dict:
    """Прошлая публикация ЭТОЙ программы — в той же форме, что кладёт
    `republish_archive.previous_from_stored_publication`. Личности —
    настоящей формы живого документа (`8-4-4-4-12-суффикс`): выдуманная
    строка проходила бы здесь и отказывала бы у эмиттера, то есть тест
    мерил бы не то."""
    return {"program": program, "identity": {
        "schema": "kir-create-identity-assessment/1",
        "receipt_digest": "d" * 64,
        "outputs": [{"output_id": op["id"], "source_op": op["op"],
                     "state": "created_here",
                     "element_identity": {
                         "schema_version": "revit-element-identity/1",
                         "unique_id": f"7ff4b512-b299-4d75-8107-62effd492f45-{42980 + index:08x}",
                         "element_id": 274500 + index,
                         "version_guid": "7ff4b512b2994d75810762effd492f45"}}
                    for index, op in enumerate(program["ops"])]}}


# ── КОНТРОЛЬ: без прошлой публикации это СЕМЬ созданий ──────────────────────

def test_without_a_previous_publication_the_same_program_is_seven_creates():
    """Контроль к главному числу. Без него «ноль операций» — правда о пустоте.

    И это же — честный рассказ о сегодняшнем тракте: у переноса нет адреса
    прошлой публикации (перенос пишет в Ревит, а не в `ProjectStore`), значит
    повторное одобрение СТРОИТ ВТОРУЮ КОПИЮ. Дверь обязана сказать это
    словами, а не промолчать.
    """
    program = section()
    итог = republish_for_transfer(program, None)
    assert итог["action"] == "no_previous_publication"
    assert итог["program"] is program, "сырую программу подменили без плана"
    assert len(итог["program"]["ops"]) == 7
    assert "вторую копию" in итог["message_ru"], итог["message_ru"]
    assert итог["next_ru"].strip(), "отказ назвал причину и не назвал ход"


# ── ПИН (в): выходы уже в документе ⇒ план keep, а не create ────────────────

def test_an_approval_of_what_already_stands_plans_keep_not_create():
    program = section()
    итог = republish_for_transfer(program, published(program))

    assert итог["action"] == "nothing_to_send", итог
    assert итог["counts"]["keep"] == 7, итог["counts"]
    assert итог["counts"]["create"] == 0, итог["counts"]
    assert итог["program"]["ops"] == [], "повтор собрал операции — это дубль"
    assert "уже стоит" in итог["message_ru"], итог["message_ru"]
    assert "НИЧЕГО НЕ ЗАПИСАНО" in итог["message_ru"], (
        "исход «переносить нечего» обязан сказать, что в Revit не записано "
        "ничего: человек нажал кнопку и должен знать, что случилось")


def test_a_changed_program_merges_without_creating_over_a_known_element():
    """Изменение — это слияние, а не пересоздание. Ни одного create поверх
    известной личности: свойство, ради которого модуль S и написан."""
    program = section(height_mm=3300)
    итог = republish_for_transfer(program, published(section()))

    assert итог["action"] == "merged", итог
    assert итог["counts"]["create"] == 0, (
        f"слияние создаёт поверх стоящего: {итог['counts']}")
    assert итог["program"]["ops"], "контроль негоден: слияние ничего не шлёт"
    assert sum(итог["counts"].get(k, 0) for k in ("update", "replace")) >= 1, (
        f"высота изменилась, а план ничего не меняет: {итог['counts']}")
    assert "поверх стоящего ничего не создаётся" in итог["message_ru"]


def test_a_refusal_of_the_plan_comes_back_by_name_with_a_next_move():
    """Отказ звена — по имени и со следующим ходом, а не исключением наружу.

    Одобрение, упавшее молча, человек читает как «кнопка не работает».
    """
    program = section()
    прошлое = published(program)
    # Личность есть, ЗНАЧЕНИЙ нет: `plan_republish` обязан отказать
    # `previous_payload_unavailable` — назвать нечем.
    прошлое["program"] = {"ir_version": "1.0", "ops": []}
    итог = republish_for_transfer(program, прошлое)

    assert итог["action"] == "refused", итог
    assert итог["refusal_code"], "отказ без имени — это молчание"
    assert итог["refusal"]["ok"] is False
    assert итог["next_ru"].strip(), "отказ не назвал следующий ход"


# ── ДВЕРЬ: повтор не доходит до исполнителя НИ ОДНИМ вызовом ────────────────

def test_the_transfer_door_never_reaches_the_executor_on_a_repeat(monkeypatch):
    """Самое дорогое число: СКОЛЬКО РАЗ дверь позвала исполнителя. Ноль.

    Проверяется не обещание «мы решили не строить», а факт: тело двери
    (`_handle_revit_ir_inner`) подменено счётчиком, и он остаётся на нуле.
    """
    from kir import serving

    вызовы = []

    async def _recorder(*args, **kwargs):
        вызовы.append(kwargs.get("source_kind"))
        return {"ok": True, "kir": True}

    monkeypatch.setattr(serving, "_handle_revit_ir_inner", _recorder)
    program = section()

    async def _bridge(method, params):
        raise AssertionError("повтор поехал в Ревит — это и есть дубль")

    итог = asyncio.run(handle_revit_ir(
        {"program": program}, None, _bridge, "q",
        source_kind="transfer", previous_publication=published(program)))

    assert вызовы == [], f"исполнителя позвали {len(вызовы)} раз(а)"
    assert итог.get("wrote_nothing") is True, итог
    assert "уже стоит" in str(итог.get("message_ru") or ""), итог

    # КОНТРОЛЬ ТОЙ ЖЕ ДВЕРЬЮ: без прошлой публикации исполнителя ЗОВУТ.
    # Без этого «ноль вызовов» мог бы означать, что дверь не работает вовсе.
    вызовы.clear()
    asyncio.run(handle_revit_ir(
        {"program": section()}, None, _bridge, "q", source_kind="transfer"))
    assert вызовы == ["transfer"], (
        "контроль негоден: дверь не зовёт исполнителя и без повтора — "
        f"значит ноль выше ничего не доказывает ({вызовы})")


def test_a_model_turn_is_not_touched_by_the_merge(monkeypatch):
    """Ход МОДЕЛИ идёт прежним путём байт в байт.

    Слияние — свойство ОДОБРЕНИЯ человека. Дать его обычному ходу значило бы
    позволить модели молча решать, что «это уже стоит».
    """
    from kir import serving

    вызовы = []

    async def _recorder(*args, **kwargs):
        вызовы.append(kwargs.get("source_kind"))
        return {"ok": True, "kir": True}

    monkeypatch.setattr(serving, "_handle_revit_ir_inner", _recorder)
    program = section()

    async def _bridge(method, params):
        raise AssertionError("моста быть не должно")

    итог = asyncio.run(handle_revit_ir(
        {"program": program}, None, _bridge, "q",
        source_kind="chat", previous_publication=published(program)))

    assert вызовы == ["chat"], (
        "ход модели не дошёл до исполнителя — слияние тронуло чужой путь")
    assert "republish" not in итог, (
        "квитанция хода модели несёт следы слияния: путь изменился")
