"""ДЕДУПЛИКАЦИЯ СХЕМЫ — экономия обязана быть ДОКАЗАННОЙ, а не обещанной.

Схема KIR — 70.7% всего, что уходит модели на первом ходу (замер 03.08:
22 631 токен из 44 615). Две трети её — дословный повтор селекторов. Вынос
повторов в `$defs` даёт втрое, НЕ убирая из контекста ни одной операции, — и
это принципиально отличает его от ярусной подачи, которая платит видимостью
(из журнала отказов: 4.8% компиляций — опы, которых модель не видела и потому
ВЫДУМАЛА).

Здесь проверяется ровно то, чем это отличие держится: преобразование
ОБРАТИМО. Пока `expand(hoist(s))` побайтово равно `s`, «мы ничего не потеряли»
— факт, проверяемый машиной. Как только перестанет — тест красный, и никакая
экономия этого не перевешивает.
"""
from __future__ import annotations

import json

import pytest

from kukai.ir import spec
from kukai.ir.schema_dedup import expand, hoist, measure
from kukai.ir.schema_gen import program_schema


def _canon(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@pytest.fixture(scope="module")
def flat() -> dict:
    return program_schema()


@pytest.fixture(scope="module")
def packed(flat: dict) -> dict:
    return hoist(flat)


def test_the_transform_is_exactly_reversible(flat: dict, packed: dict) -> None:
    """ГЛАВНЫЙ ТЕСТ ФАЙЛА: развёрнутая обратно схема ТОЖДЕСТВЕННА исходной."""
    assert _canon(expand(packed)) == _canon(flat), (
        "дедупликация изменила смысл схемы — экономия не имеет значения, "
        "если язык стал другим")


def test_no_operation_disappears(flat: dict, packed: dict) -> None:
    """Ни один оп не исчезает — это и есть отличие от ярусов.

    Ярусная подача убирает опы из виду и платит за это выдуманными вызовами.
    Дедупликация не убирает ничего, и здесь это проверяется поимённо, а не
    доверием к предыдущему тесту.
    """
    text = _canon(packed)
    missing = sorted(name for name in spec.OPS if f'"{name}"' not in text)
    assert not missing, f"опы пропали из схемы после выноса: {missing}"


def test_every_reference_resolves(packed: dict) -> None:
    """Висячая ссылка — схема, которую нельзя прочитать. Ловим до модели."""
    defs = set(packed.get("$defs", {}))
    dangling: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in defs:
                    dangling.append(ref)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(packed)
    assert not dangling, f"висячие ссылки: {sorted(set(dangling))}"


def test_the_saving_is_real_and_large(flat: dict) -> None:
    """Экономия обязана быть КРУПНОЙ, иначе она не стоит новой сущности.

    Порог 2.5x назначен НИЖЕ замеренного (3.04x на 03.08; 3.871x на 41 опе
    09.08) — тест сторожит регресс, а не фиксирует сегодняшнее число. Если
    вынос перестанет окупаться, честнее выбросить его целиком, чем возить
    `$defs` ради приличия.

    Острый храповик — в `test_schema_transport.py` (порог 3.5x, поставленный
    под слабейший ЖИВОЙ замер, плюс потолок байт на оп). Здесь остаётся грубая
    нижняя граница самого преобразования, независимая от того, куда его
    подключили.
    """
    stats = measure(flat)
    assert stats["ratio"] >= 2.5, (
        f"вынос перестал окупаться: {stats}")
    assert stats["packed_bytes"] < stats["flat_bytes"]


def test_the_result_is_deterministic(flat: dict) -> None:
    """Дважды одна схема — дважды один байт.

    Без этого любой хеш поверх схемы (а он рано или поздно понадобится:
    так работает вся пред-регистрация в этом пакете) стал бы случайным числом.
    """
    assert _canon(hoist(flat)) == _canon(hoist(program_schema()))


def test_names_explain_themselves_where_they_can(packed: dict) -> None:
    """Имя в `$defs` читает МОДЕЛЬ, а не только компилятор.

    `#/$defs/sel_by_name` объясняет форму; `#/$defs/shape_7` — нет. Мы не
    требуем осмысленности от всех имён (выдумывать смысл там, где его не
    распознали, хуже честного порядкового номера), но селекторы — 90%
    вынесенного, и они обязаны читаться.
    """
    names = set(packed.get("$defs", {}))
    assert names, "вынос ничего не дал"
    # Безымянная форма — та, что получила порядковый номер, потому что её не
    # УЗНАЛИ. Все прочие имена выведены структурно: `pt_xy`, `element_id`,
    # `kind_enum`, `region_rect`, `number_5_2000`.
    anonymous = {name for name in names if name.startswith("shape_")}
    speaking = names - anonymous
    assert len(speaking) * 3 >= len(names) * 2, (
        f"узнано только {len(speaking)} форм из {len(names)}; "
        f"безымянные: {sorted(anonymous)}")


def test_both_forms_are_legal_json_schema(flat: dict, packed: dict) -> None:
    """СВЁРНУТАЯ ФОРМА ОБЯЗАНА БЫТЬ ЗАКОННОЙ САМА ПО СЕБЕ — тождества мало.

    Первая редакция выноса была обратимой и при этом НЕВАЛИДНОЙ: `$ref`
    подставлялся внутрь карты `properties`, где он читается как имя свойства
    «$ref», а не как ссылка. Тест тождества это пропускал, потому что разворот
    механически возвращал всё назад. Модель же получила бы схему, описывающую
    объект со свойством `$ref` вместо описания операции.

    Здесь судит ПОСТОРОННИЙ валидатор по метасхеме, а не наши рассуждения о
    том, где ссылка уместна.
    """
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator
    validator.check_schema(flat)
    validator.check_schema(packed)


def test_both_forms_accept_the_same_program(flat: dict, packed: dict) -> None:
    """Последнее слово — за поведением: обе формы принимают одну программу.

    Валидность метасхеме говорит «это законная схема», но не «это ТА ЖЕ схема».
    Настоящая программа, прогнанная через обе, отвечает на второй вопрос.
    """
    jsonschema = pytest.importorskip("jsonschema")
    program = {
        "ir_version": spec.IR_VERSION,
        "intent": "проверка тождества форм схемы",
        "ops": [
            {"op": "create_wall", "id": "w1",
             "p0_mm": [0, 0], "p1_mm": [5000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "height_mm": 3000},
            {"op": "create_door", "id": "d1",
             "host": {"by": "ref", "value": "w1"}, "offset_mm": 2500},
        ],
    }
    flat_errors = [e.message for e
                   in jsonschema.Draft202012Validator(flat).iter_errors(program)]
    packed_errors = [e.message for e
                     in jsonschema.Draft202012Validator(packed).iter_errors(program)]
    assert not flat_errors, f"плоская схема отвергла верную программу: {flat_errors}"
    assert not packed_errors, (
        f"свёрнутая схема отвергла программу, которую приняла плоская: "
        f"{packed_errors}")


def test_hoisting_twice_is_refused(packed: dict) -> None:
    """Повторный вынос — признак спутанного конвейера, а не безобидность."""
    with pytest.raises(ValueError):
        hoist(packed)


def test_flat_schema_is_untouched_by_this_module(flat: dict) -> None:
    """ГЕНЕРАТОР ОСТАЁТСЯ ПЛОСКИМ — и это уже не отсрочка, а разделение ролей.

    С 09.08.2026 вынос ПОДКЛЮЧЁН, но не здесь: его делает
    `schema_transport.program_schema_for_tool()` на границе инструмента
    (`serving.inject_revit_ir_schema`), по ЗАМЕРЕННОМУ условию транспорта.
    Генератор при этом обязан остаться единственным источником правды о ЯЗЫКЕ,
    а `schema_dedup` — чистым пост-проходом над его результатом: как только
    `program_schema()` сам начнёт отдавать `$defs`, повторный хойст станет
    невозможен («повторный хойст запрещён»), а форма языка перестанет
    описываться одним местом.

    Что видит модель — проверяется там, где это решается:
    `test_schema_transport.py::test_the_live_tool_actually_ships_the_deduped_schema`.
    """
    assert "$defs" not in flat, (
        "program_schema() начал отдавать схему со ссылками — тогда хойст на "
        "границе инструмента откажет, и единственный работающий механизм "
        "дедупликации сломается о рукописный `$defs`")
