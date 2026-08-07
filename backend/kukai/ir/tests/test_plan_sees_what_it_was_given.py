"""ПЛАН — ГЛАЗА МОДЕЛИ, И НА НЕВЕРНОМ ВХОДЕ ОНИ ВРАЛИ.

Три замера 04.08, каждый воспроизведён здесь ДО починки:

1. `preview(ops_list)` ПОЗИЦИОННО уходил в параметр `level`, `ops` оставался
   `None`, и функция печатала «ПЛАН: программа пуста — ни одной операции.
   Рисовать нечего» — при трёх операциях на руках. Отказа не было: модель
   читала «пусто», шла добавлять уже написанное. При этом `design_check(ops)`
   позиционно РАБОТАЕТ: сигнатуры `preview(level=None, *, ops=None)` и
   `design_check(ops=None)` разошлись на одном шве, и разошлись молча.

2. `preview(ops=<пачка>)` печатал «операций рассмотрено 2, нарисовано 0 (0%)»
   и НИ СЛОВА о причине. Пачка — форма, которую мы модели ПРЕДПИСЫВАЕМ
   (`design_check([тело, лестница])`, `tool_doc.NOTES`); плану она не была
   известна вовсе.

3. Отметка уровня резолвилась ТОЛЬКО по `$id`: по имени печаталось
   «отм. None мм». А адресация ПО ИМЕНИ — ровно то, что предписывает закон
   пачки (`create_stairs.base_level` не принимает `ref`). Глаза слепли именно
   на той форме, которую мы велели использовать.

ЧЕГО ЗДЕСЬ НАМЕРЕННО НЕТ: отказа на узлах L1. Модель в песочнице их произвести
не может (у неё есть только реестр опов), а «отказ на входе, которого у двери
нет» стоит дороже отсутствующего. Вместо отказа проверяется, что НУЛЕВОЕ
покрытие называет СЕБЯ и свою причину — одним правилом на любой мусор.

Прогон: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kukai/ir/tests/test_plan_sees_what_it_was_given.py -q
"""
from __future__ import annotations

import contextlib
import io
import os

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kukai.ir import course  # noqa: E402
from kukai.ir import preview as P  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════
# Материал
# ═════════════════════════════════════════════════════════════════════════

def body_ops(*, by_name: bool) -> list[dict]:
    """Две стены на объявленном уровне. Уровень адресован ref либо ИМЕНЕМ."""
    level = ({"by": "name", "value": "Этаж 1"} if by_name
             else {"by": "ref", "value": "L1"})
    return [
        {"op": "create_level", "id": "L1", "name": "Этаж 1", "elev_mm": 3300.0},
        {"op": "create_wall", "id": "w1", "level": level, "height_mm": 3000,
         "p0_mm": [0, 0], "p1_mm": [6000, 0]},
        {"op": "create_wall", "id": "w2", "level": level, "height_mm": 3000,
         "p0_mm": [6000, 0], "p1_mm": [6000, 5000]},
    ]


def stairs_ops() -> list[dict]:
    return [{"op": "create_stairs", "id": "s1", "width_mm": 1200,
             "p0_mm": [1000, 1000], "p1_mm": [1000, 4000],
             "base_level": {"by": "name", "value": "Этаж 1"},
             "top_level": {"by": "name", "value": "Этаж 2"}}]


def say(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════
# 1. ШОВ СИГНАТУР: план и вердикт зовутся ОДИНАКОВО
# ═════════════════════════════════════════════════════════════════════════

def test_the_plan_takes_its_program_positionally_like_the_verdict() -> None:
    """ГЛАВНОЕ УТВЕРЖДЕНИЕ ФАЙЛА. `preview(ops)` и `design_check(ops)` — пара,
    и модель зовёт их одинаково. До 04.08 первый молча терял программу."""
    ops = body_ops(by_name=False)
    text = say(course.preview, ops)
    assert "программа пуста" not in text, text
    assert "нарисовано 2 из 2" in text, text


def test_a_string_first_argument_is_named_not_guessed() -> None:
    """Обратная сторона перестановки: `preview("Этаж 1")` больше не значит
    «фильтр по уровню». Молча принять строку как уровень было бы догадкой;
    отказ обязан назвать увиденное И починку одной строкой."""
    text = say(course.preview, "Этаж 1")
    assert "ПЛАН ОТКАЗ" in text, text
    assert "level=" in text, text
    assert "str" in text or "строка" in text, text


def test_the_level_filter_still_works_by_name_of_the_parameter() -> None:
    ops = body_ops(by_name=False)
    text = say(course.preview, ops, level="Этаж 1")
    assert "«Этаж 1»" in text and "нарисовано 2 из 2" in text, text
    missing = say(course.preview, ops, level="Этаж 7")
    assert "уровня «Этаж 7» в программе нет" in missing, missing


# ═════════════════════════════════════════════════════════════════════════
# 2. ПАЧКА — ФОРМА, КОТОРУЮ МЫ САМИ ПРЕДПИСАЛИ
# ═════════════════════════════════════════════════════════════════════════

def test_the_plan_draws_a_bundle_and_says_it_was_one() -> None:
    """Пачку рисовальщик СКЛЕИВАЕТ — лист один, и это уже закон потока
    (`plan_stream._slice_for`: «склейка нужна рисовальщику»). Отказать на ней
    значило бы ослепить модель ровно на той единице, которой здание является.
    """
    pack = [{"ops": body_ops(by_name=False)}, {"ops": stairs_ops()}]
    text = say(course.preview, pack)
    assert "нарисовано 0 (0%)" not in text, text
    assert "пачка" in text.lower(), text
    assert "2 программ" in text, text
    # И это не пустой лист: тело и лестница нарисовались НА ОДНОМ этаже.
    assert "нарисовано 3 из 3" in text, text


def test_one_storey_addressed_two_ways_is_one_sheet() -> None:
    """ОДИН ЭТАЖ — ОДИН ЛИСТ, чем бы его ни адресовали.

    Тело адресует уровень ссылкой (`$L1`), лестница обязана адресовать ЕГО ЖЕ
    по имени — `create_stairs.base_level` ссылку не принимает вовсе. Значит в
    пачке обе формы стоят рядом ВСЕГДА, и до 04.08 один этаж выходил ДВУМЯ
    листами с ОДИНАКОВЫМ названием: тот же раскол, о котором предупреждает
    шапка `live/journal.py`.
    """
    pack = [{"ops": body_ops(by_name=False)}, {"ops": stairs_ops()}]
    text = say(course.preview, pack)
    assert text.count("«Этаж 1»") == 1, text
    assert "нарисовано 3 из 3" in text, text


def test_zero_drawn_names_itself_and_its_reason() -> None:
    """ЛЮБОЙ вход, из которого не нарисовалось НИЧЕГО, обязан сказать это
    словом и назвать причину. До 04.08 «рассмотрено 1, нарисовано 0 (0%)» было
    всем, что получала модель: ни одной строки о том, ПОЧЕМУ ноль."""
    junk = [{"kind": "op", "op_name": "create_wall", "params": {}}]
    text = say(course.preview, junk)
    assert "НЕ НАРИСОВАНО НИЧЕГО" in text, text
    assert "не операция KIR" in text, text


def test_the_reason_for_a_non_op_is_not_blamed_on_a_selector() -> None:
    """Причина адресная: «у этого элемента нет ключа `op`» и «селектор уровня
    не сведён к плану» — разные починки, и вторая посылает чинить не туда."""
    census = P.build_program_preview(
        [{"kind": "op", "op_name": "create_wall", "params": {}}]).census
    reasons = {group.reason for group in census.omitted}
    assert P.OmitReason.NOT_AN_OP in reasons, reasons
    assert P.OmitReason.SELECTOR_UNRESOLVED not in reasons, reasons


# ═════════════════════════════════════════════════════════════════════════
# 3. ОТМЕТКА ПО ИМЕНИ
# ═════════════════════════════════════════════════════════════════════════

def test_the_elevation_resolves_for_a_level_addressed_by_name() -> None:
    """Замер 04.08: по ref — 3300.0, по имени — None. Программа объявляет
    `create_level(name="Этаж 1", elev_mm=3300)` в обоих случаях; отметка есть
    в программе, и не отдавать её — потеря, а не неизвестность."""
    by_ref = say(course.preview, body_ops(by_name=False))
    by_name = say(course.preview, body_ops(by_name=True))
    assert "отм. 3300.0 мм" in by_ref, by_ref
    assert "отм. None мм" not in by_name, by_name
    assert "отм. 3300.0 мм" in by_name, by_name


def test_an_ambiguous_name_stays_unknown_rather_than_guessing() -> None:
    """Обратная сторона: два `create_level` с одним именем и РАЗНЫМИ отметками
    — это неизвестность, а не «возьми первую». Правдоподобное число здесь
    дороже честного пробела.

    ЭТО ЖЕ И ЕДИНСТВЕННЫЙ СЛУЧАЙ, ГДЕ ИМЕННАЯ ВЕТКА РЕШАЕТ ДЕЛО, и мутационный
    прогон это показал: при ОДНОЗНАЧНОМ имени ключ этажа сводится к `$id`
    раньше (`build_program_preview`, alias), поэтому «отм. по имени» держится
    сведением, а не резолвом. Остаётся ровно эта развилка — имя занято дважды,
    сведение честно отказано, и отметка известна лишь тогда, когда ОБА
    объявления говорят одно и то же.
    """
    ops = body_ops(by_name=True)
    ops.insert(1, {"op": "create_level", "id": "L1b", "name": "Этаж 1",
                   "elev_mm": 9999.0})
    assert P._program_level_elevation(ops, "Этаж 1") is None
    # А совпадающие отметки неоднозначности не создают.
    ops[1]["elev_mm"] = 3300.0
    assert P._program_level_elevation(ops, "Этаж 1") == 3300.0
    # И это ровно то, что видит модель: лист печатает число, а не «None».
    assert "отм. 3300.0 мм" in say(course.preview, ops)
