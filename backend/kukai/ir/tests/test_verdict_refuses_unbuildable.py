"""Вердикт не смеет судить пригодность того, что компилятор не возьмёт.

ДЕФЕКТ, РАДИ КОТОРОГО ЭТОТ ФАЙЛ (замер 04.08.2026, живой A/B). `check_ops`
судил пригодность программы, где `create_stairs` стоял рядом с соседями, и
печатал вердикт — тогда как `plan_program` ту же программу отвергал
`KIR-L002`. Модель получала ДВА зелёных света и стену: `preview()` рисовал
её, `design_check()` выносил вердикт, а компилятор отказывал. Это ровно те
«две подписи у одного здания», против которых типизирован весь компилятор,
и одной из подписей был наш собственный вердикт.

ПОЧЕМУ ЭТО НЕ НАХОДКА, А ОТКАЗ ДВЕРИ. Находка вердикта говорит «здание
плохое» — её чинят, меняя здание. Здесь здание может быть безупречным:
непостроима ПРОГРАММА как единица, и чинится это разбиением на пачку.
Смешать одно с другим значило бы отправить автора искать несуществующий
изъян в замысле.

ГРАНИЦА ЭТОГО ФАЙЛА. Он проверяет ровно закон формы (`spec.SOLO_OPS`), а не
то, что дверь вердикта стала фронтендом компилятора: `plan_program` отказывает
и по причинам, к пригодности отношения не имеющим (неизвестное поле, бюджет),
и тащить их в вердикт значило бы подменить вопрос «дом ли это» вопросом
«компилируется ли».
"""
from __future__ import annotations

import os

# Ставится ДО импорта вердикта: флаг читается на сборке, и `skipif` уровня
# модуля здесь уже наступал на грабли — в общем прогоне тесты молча скипались.
os.environ.setdefault("KUKAI_CHECKER_V2", "1")

import pytest  # noqa: E402

from kukai.ir import compiler, spec  # noqa: E402
from kukai.ir.design_check import (
    PROGRAM_NOT_BUILDABLE,
    ProgramNotBuildableError,
    VerdictInputError,
    check_bundle,
    check_ops,
)




_LEVELS = [
    {"op": "create_level", "id": "L1", "name": "Этаж 1", "elev_mm": 0},
    {"op": "create_level", "id": "L2", "name": "Этаж 2", "elev_mm": 4200},
]
_WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [8000, 0],
         "height_mm": 4200, "level": {"by": "ref", "value": "L1"}}
_STAIRS = {"op": "create_stairs", "id": "S1",
           "p0_mm": [1000, 1000], "p1_mm": [1000, 7000],
           "base_level": {"by": "name", "value": "Этаж 1"},
           "top_level": {"by": "name", "value": "Этаж 2"},
           "width_mm": 1200}


def _illegal() -> dict:
    return {"ir_version": "1.0", "ops": [*_LEVELS, _WALL, _STAIRS]}


def test_the_compiler_really_refuses_this_program():
    """Опора теста. Если компилятор однажды перестанет отказывать, вердикту
    незачем отказывать тоже — и этот файл обязан упасть первым, а не молча
    сторожить снятое правило."""
    with pytest.raises(Exception) as excinfo:
        compiler.plan_program(_illegal(), bulk=True)
    assert "KIR-L002" in str(excinfo.value)


def test_verdict_refuses_what_the_compiler_will_not_take():
    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_ops(_illegal(), building_id="непостроимая")
    assert ProgramNotBuildableError.code == PROGRAM_NOT_BUILDABLE


def test_the_refusal_names_the_next_move_not_only_the_diagnosis():
    """Планка жанра — `KIR-L001`: назван закон, назван виновник, назван ход.

    Отказ, называющий только диагноз, оставляет модель на том же месте: она
    уже знает, что что-то не так, — ей нужно знать, что делать дальше.
    """
    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_ops(_illegal(), building_id="непостроимая")
    text = str(excinfo.value)
    assert "KIR-L002" in text                 # закон назван
    assert "create_stairs" in text            # виновник назван
    assert "ПАЧКУ" in text
    # ХОД НАЗВАН ИМЕНЕМ, КОТОРОЕ ЕСТЬ У МОДЕЛИ. Первая редакция отправляла в
    # `check_bundle` — имя двери СНАРУЖИ; изнутри песочницы его нет вовсе
    # (`NameError`). Отказ, называющий несуществующий ход, тратит ход модели
    # на проверку нашей опечатки.
    assert "design_check([" in text
    assert "check_bundle" not in text


def test_the_named_next_move_exists_in_the_model_language():
    """Сторож против повторения той же опечатки: имя из отказа обязано быть
    в пространстве имён песочницы, а не только в нашем модуле."""
    from kukai.ir.course import SANDBOX_NAMES

    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_ops(_illegal(), building_id="непостроимая")
    named = [n for n in SANDBOX_NAMES if f"{n}(" in str(excinfo.value)]
    assert named, ("отказ не назвал НИ ОДНОГО имени, доступного модели: "
                   f"{sorted(SANDBOX_NAMES)}")


def test_one_catch_point_for_the_whole_door():
    """Родовой перехват обязан ловить и этот отказ — иначе новый род тихо
    пролетает мимо старого `except`, и наружу вместо причины уходит трасса."""
    with pytest.raises(VerdictInputError):
        check_ops(_illegal(), building_id="непостроимая")


def test_the_same_ops_are_legal_as_a_bundle():
    """Смысл пачки: тот же набор, разложенный по звеньям, ЗАКОНЕН.

    Без этого утверждения ворота были бы не законом, а запретом на лестницу.
    """
    verdict = check_bundle(
        [{"ir_version": "1.0", "ops": [*_LEVELS, _WALL]},
         {"ir_version": "1.0", "ops": [_STAIRS]}],
        building_id="пачка")
    assert verdict is not None


def test_a_lone_solo_op_is_not_refused():
    """Один `create_stairs` — законная программа, и дверь обязана её принять.

    Порог именно «есть соседи», а не «есть solo-оп»: перепутать их значило бы
    запретить единственную форму, в которой лестница вообще выразима.
    """
    assert check_ops({"ir_version": "1.0", "ops": [_STAIRS]},
                     building_id="одна лестница") is not None


def test_the_gate_reads_the_registry_not_its_own_list(monkeypatch):
    """Судья один. Свой список solo-опов здесь стал бы ЧЕТВЁРТЫМ (после плана,
    эмиттера и реестра) и разошёлся бы с остальными на первом же новом опе.

    ПЕРВАЯ РЕДАКЦИЯ ЭТОГО ТЕСТА БЫЛА ВАКУУМНОЙ и поймана ревизией: она
    утверждала `"create_stairs" in spec.SOLO_OPS` — факт О РЕЕСТРЕ, ворот не
    касающийся. Мутация «ворота держат свой список» оставляла все семь тестов
    зелёными. Проверять надо не что в реестре лежит, а что ворота ЕГО ЧИТАЮТ:
    добавляем в реестр оп, которого в любом захардкоженном списке быть не
    может, и требуем, чтобы ворота его увидели.
    """
    monkeypatch.setattr(
        spec, "SOLO_OPS", frozenset({*spec.SOLO_OPS, "create_wall"}))
    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_ops({"ir_version": "1.0", "ops": [*_LEVELS, _WALL]},
                  building_id="реестр расширен")
    assert "create_wall" in str(excinfo.value)


def test_a_bundle_whose_own_link_is_unbuildable_is_refused(monkeypatch):
    """Закон проверяется ПО ЗВЕНЬЯМ — и это утверждение до сих пор не было
    защищено ничем.

    Ревизия показала: выброси проверку звеньев из `spatial_model_from_bundle`
    целиком — и все семь тестов остаются зелёными, потому что ни один не подаёт
    пачку, ОДНО ЗВЕНО КОТОРОЙ само непостроимо. Самый длинный комментарий той
    правки объяснял именно эту проверку, а держало её только честное слово.
    """
    seen: list[str] = []
    monkeypatch.setattr(spec, "SOLO_OPS",
                        frozenset({*spec.SOLO_OPS, "create_wall"}))
    bundle = [
        {"ir_version": "1.0", "ops": [*_LEVELS, _WALL]},   # звено НЕЗАКОННО
        {"ir_version": "1.0", "ops": [_STAIRS]},
    ]
    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_bundle(bundle, building_id="пачка с больным звеном")
    text = str(excinfo.value)
    seen.append(text)
    # Названо ИМЕННО ЗВЕНО, а не «пачка плохая»: автор чинит одну программу,
    # и без номера ему пришлось бы искать её перебором.
    assert "звено пачки p1" in text, text


def test_a_healthy_bundle_survives_the_per_link_check():
    """Обратная сторона: проверка по звеньям не смеет запрещать саму пачку.

    Без этого утверждения предыдущий тест можно было бы «починить» отказом на
    любую пачку с solo-опом — то есть запретом единственной формы, ради
    которой пачка и заведена.
    """
    verdict = check_bundle(
        [{"ir_version": "1.0", "ops": [*_LEVELS, _WALL]},
         {"ir_version": "1.0", "ops": [_STAIRS]}],
        building_id="здоровая пачка")
    assert verdict is not None
