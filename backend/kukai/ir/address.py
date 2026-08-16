"""АДРЕС С ОБЪЯВЛЕННЫМ ПРОСТРАНСТВОМ — и карта между двумя пространствами.

ЗАЧЕМ. У здания в этом дереве не один адрес, а три, и все три — голый `str`:

    op_id        `w1`, `p0/wall1`  — идентификатор ОПЕРАЦИИ, который написала
                                     модель; путь ПРОГРАММЫ адресует им всё
                                     (`design_check._program_nodes`: «`source_
                                     element_id` — это `id` самой операции»)
    element_id   `9001`            — то, чем адресует Ревит; путь РАЗБОРА,
                                     `SpatialModel` из `checker/extractor`,
                                     `building_graph`, дерево `fold`
    synthetic    `apt_0_0_hall`    — то, что выдумал генератор
                                     (`modeling/generator/*`), не адрес ничего
                                     существующего в документе

Тип у всех трёх один и тот же, и ничто их не различает. Замерено 15.08:
`SpatialModel.id` — `str` в шести классах, `design/coherence.Elem.oid` — `str`,
и в нём лежит id ОПЕРАЦИИ, у `generator/*` — синтетика.

ЧТО ЭТО СТОИЛО, ЧИСЛОМ. `design_check.compare_geometry` пересекает множества
`id` двух моделей. На ПЕРЕСБОРКЕ обе стороны несут `element_id` и пересечение
осмысленно. На АВТОРСКОЙ программе одна сторона несёт `w1`, другая `9001`,
**пересечение ПУСТО — и компаратор молча возвращает пустой список расхождений,
что читается как «всё совпало»**. Это наш именной класс в чистом виде: величина
названа в одном месте, прочитана в другом, и ничто не заставляет их совпасть.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ. Он НЕ переписывает четыре мира на новый тип: это
была бы правка на тысячи строк ради типа, который нужен ровно на границах.
Он объявляет пространство ТАМ, ГДЕ ДВА МИРА ВСТРЕЧАЮТСЯ, и отказывает, когда
их сводят молча.

## ПОЧЕМУ `__eq__` НЕ ОТКАЗЫВАЕТ, А `same_as` ОТКАЗЫВАЕТ

Требование «сравнение адресов из разных пространств обязано ОТКАЗАТЬ» верно по
существу и невыполнимо в `__eq__`: `Address` кладут в `set`/`dict`, а там
`__eq__` зовётся при КОЛЛИЗИИ ХЕША между произвольными элементами, и
исключение оттуда уронило бы обычный поиск по словарю на ровном месте. Поэтому:

* `__eq__` — структурное (пространство входит в равенство, разные пространства
  просто не равны). Контейнеры работают;
* `same_as()` — ЯВНОЕ сравнение с отказом `AddressSpaceError`, и именно оно
  стоит на границах, где ошибка стоит дорого;
* `assert_one_space()` — то же для множеств: сводить два множества адресов
  можно, только назвав их пространство.

Разделение названо здесь, а не в чьей-то памяти, потому что «почему тут не
отказывает» — первый вопрос читателя.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

from kukai.ir.registry_base import EffectKind, IdentityCardinality

__all__ = [
    "Address",
    "AddressSpace",
    "AddressSpaceError",
    "IdentityMissingError",
    "assert_one_space",
    "created_identity_fields",
    "element_addresses",
    "identity_field_reasons",
    "receipt_map",
]


class AddressSpace(str, Enum):
    """Пространства адресов, встречающиеся в этом дереве. ПОЛНЫЙ ПО ПОСТРОЕНИЮ.

    Полнота держится не обещанием: четвёртого пространства в дереве нет,
    потому что адрес рождается ровно в трёх местах — его пишет автор
    (`op_id`), его возвращает Ревит (`element_id`), его выдумывает генератор
    (`synthetic`). Появится четвёртое — оно обязано появиться ЗДЕСЬ, иначе
    `Address` его не выразит и код не соберётся.
    """

    OP_ID = "op_id"
    ELEMENT_ID = "element_id"
    SYNTHETIC = "synthetic"


class AddressSpaceError(TypeError):
    """Два адреса сведены молча. Это ОТКАЗ, а не «не совпало»."""


class IdentityMissingError(ValueError):
    """Пишущий оп не принёс идентичности. Пустая карта была бы враньём."""


@dataclass(frozen=True)
class Address:
    """Адрес элемента ВМЕСТЕ со своим пространством.

    `value` всегда строка: `element_id` приходит из Ревита то числом, то
    строкой цифр (см. `registry_base._result_element_id`), и хранить две формы
    одного адреса значит завести два ключа для одной вещи.
    """

    space: AddressSpace
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.space, AddressSpace):
            raise AddressSpaceError(
                "пространство адреса обязано быть типизированным, "
                f"получено {type(self.space).__name__}")
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("адрес не бывает пустым")

    def same_as(self, other: "Address") -> bool:
        """Сравнить ЯВНО. Разные пространства — отказ, а не `False`.

        `w1` и `9001` не «разные элементы» — они утверждения РАЗНОГО РОДА, и
        ответ `False` на такой вопрос неотличим от честного несовпадения.
        """

        if not isinstance(other, Address):
            raise AddressSpaceError("сравнивать адрес можно только с адресом")
        if self.space is not other.space:
            raise AddressSpaceError(
                f"адреса из РАЗНЫХ пространств: {self.space.value} против "
                f"{other.space.value}. Их нельзя сравнивать — их надо "
                f"ПЕРЕВЕСТИ (`receipt_map`)")
        return self.value == other.value

    def __str__(self) -> str:
        return f"{self.space.value}:{self.value}"


def assert_one_space(addresses: Iterable[Address],
                     expected: AddressSpace | None = None) -> AddressSpace:
    """Пространство множества адресов, либо ОТКАЗ. Пустое множество — отказ.

    Пустое отказывает намеренно: «пространство пустого множества» — это ноль
    величины, которую здесь никто не считал, и принимать его за согласие
    значит повторять ровно тот дефект, ради которого модуль написан.
    """

    seen = {a.space for a in addresses}
    if not seen:
        raise AddressSpaceError(
            "пространство пустого множества адресов не определено")
    if len(seen) > 1:
        raise AddressSpaceError(
            "множество смешивает пространства: "
            + ", ".join(sorted(s.value for s in seen)))
    only = seen.pop()
    if expected is not None and only is not expected:
        raise AddressSpaceError(
            f"ожидалось пространство {expected.value}, получено {only.value}")
    return only


# ─── КАРТА `op_id → element_id`, ВЫВЕДЕННАЯ ИЗ РЕЕСТРА ───────────────────────
#
# Поле идентичности РАЗНОЕ у разных опов, и рукописный список этих имён —
# вторая таблица, обязанная совпасть с реестром. Замерено 15.08 на 65 пишущих:
# `id` у 59, `segment_ids` у 4, `deleted_id` у 1, `moved_ids` у 1. Всякий, кто
# пишет эти имена рукой, промахивается ровно на редких — и промах тихий.


@lru_cache(maxsize=1)
def created_identity_fields() -> tuple[str, ...]:
    """Поля, несущие идентичность СОЗДАННОГО. ПОЛНЫЙ ПО ПОСТРОЕНИЮ.

    Авторитет — реестр: берутся `ResultSpec.identity_field` всех опов с
    `EffectKind.CREATE`. Новый созидающий оп попадает сюда САМ; забыть его
    нельзя, потому что списка, который можно забыть, больше нет.

    КЭШ — НЕ УКРАШЕНИЕ. `witness_feed.outcome_label` зовёт эту функцию на
    КАЖДОЙ строке результата, а строк до `_MAX_OPS_PER_RECORD` за запись:
    без кэша это перебор 69 опов реестра на строку, то есть стоимость,
    растущая с n, в теле, которое крутится. Реестр за время процесса не
    меняется, поэтому ответ считается один раз.

    Кто подменяет `spec.OPS` (тесты реестра), обязан звать
    `created_identity_fields.cache_clear()` — иначе получит ответ о прежнем
    реестре и примет его за свойство подменённого.
    """

    from kukai.ir import spec

    return tuple(sorted({
        op.result.identity_field
        for op in spec.OPS.values()
        if op.effect is EffectKind.CREATE and op.result.identity_field}))


def identity_field_reasons() -> dict[str, str]:
    """Поля, которые НИ У ОДНОГО опа не несут созданного, — каждое с причиной.

    Пара к `created_identity_fields`: вместе они покрывают все поля
    идентичности реестра БЕЗ ОСТАТКА и БЕЗ ПЕРЕСЕЧЕНИЯ, и это держит тест.

    🔴 УСЛОВИЕ «БЕЗ ПЕРЕСЕЧЕНИЯ» — НЕ ПЕДАНТИЗМ, ОНО ПОЙМАЛО ОШИБКУ АВТОРА
    ЭТОЙ ФУНКЦИИ. Первая редакция брала «поля не-CREATE опов» и вернула `id`
    среди не-созидающих: `change_type` — `MUTATE` и несёт `id`, тот самый `id`,
    которым 59 созидающих опов называют созданное. Поле принадлежит ОБОИМ
    множествам, и пара перестала покрывать реестр разбиением. Поэтому здесь
    вычитается: не-созидающее — это поле, которое не несёт созданного НИ РАЗУ.
    """

    from kukai.ir import spec

    created = set(created_identity_fields())
    reasons: dict[str, str] = {}
    for op in spec.OPS.values():
        field = op.result.identity_field
        if not field or field in created:
            continue
        if op.effect is EffectKind.DELETE:
            reasons[field] = (
                "удалённого элемента в модели уже нет — следить не за чем")
        elif op.effect is EffectKind.MUTATE:
            reasons[field] = (
                "элемент существовал до хода: правка не оставляет НОВОГО "
                "следа, а реестр отвечает на «что я оставил»")
        else:
            reasons[field] = f"эффект {op.effect.value}: созданного нет"
    return reasons


def element_addresses(ops: Sequence[Mapping[str, Any]],
                      payload: Mapping[str, Any],
                      *, strict: bool = True) -> dict[str, tuple[Address, ...]]:
    """Карта «id операции → адреса созданных ею элементов Ревита».

    Единственный производитель этой карты в дереве. Поле идентичности берётся
    У РЕЕСТРА пооперационно (`OpSpec.result.identity_field`), а не угадывается
    по имени: у `create_wall` это `id`, у `route_pipe_system` — `segment_ids`,
    у `delete` — `deleted_id`. Читатель, знающий только `"id"`, теряет шесть
    операций из 65 и не узнаёт об этом.

    `ops` — программа КАК НАПИСАНА (`{"op": ..., "id": ...}`); `payload` —
    `result` квитанции, словарь по id операции.

    `strict=True` (умолчание): пишущий оп без идентичности — `IdentityMissing
    Error` с именами. Пустая карта на успешной программе была бы враньём того
    же рода, что и молчаливое пересечение пустых множеств. `strict=False`
    существует для читателей уже сохранённых квитанций, где часть строк
    записана до появления контракта; такой читатель обязан назвать, что он
    смягчил.
    """

    from kukai.ir import spec

    out: dict[str, tuple[Address, ...]] = {}
    missing: list[str] = []
    for index, op in enumerate(ops):
        name = str(op.get("op", ""))
        ospec = spec.OPS.get(name)
        if ospec is None:
            continue
        result = ospec.result
        if result.identity_cardinality is IdentityCardinality.NONE:
            continue                      # query: идентичности нет по контракту
        raw_id = op.get("id")
        oid = str(raw_id) if raw_id not in (None, "") else f"#{index}"
        row = payload.get(oid)
        if not isinstance(row, Mapping) or not result.identity_present(row):
            missing.append(f"{oid} ({name}, ждали `{result.identity_field}`)")
            continue
        value = row[result.identity_field]
        values = ([value] if result.identity_cardinality is IdentityCardinality.ONE
                  else list(value))
        out[oid] = tuple(Address(AddressSpace.ELEMENT_ID, str(v)) for v in values)
    if missing and strict:
        raise IdentityMissingError(
            "идентичности нет у операций: " + "; ".join(missing)
            + ". Успешная пишущая программа обязана нести её у КАЖДОЙ "
              "(`serving._result_contract_diagnostic`, KIR-X008)")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 ЗДЕСЬ БЫЛА ВТОРАЯ ФОРМА КАРТЫ — `op_to_element_ids`, И ОНА УДАЛЕНА 15.08.
#
# Две функции одной работы, рождённые В ОДИН ДЕНЬ двумя параллельными волнами:
# плоская `dict[str, str]` (ранняя) и списочная `dict[str, list[str]]`
# (поздняя). Живой путь звал списочную; у плоской не было НИ ОДНОГО
# продуктового потребителя — только собственные тесты и две строки прозы в
# `design_check`.
#
# ПОЧЕМУ УДАЛЕНА, А НЕ ОСТАВЛЕНА ОБЁРТКОЙ. Плоский словарь физически не несёт
# множественную идентичность, поэтому его перевод МОЛЧА терял операции —
# замерено на реестре 15.08: **5 пишущих опов из 66 имеют арность МНОГО**
# (`create_pipe_system`, `create_room_separator`, `move_elements`,
# `route_duct_system`, `route_pipe_system`), и все пять исчезали из карты без
# единой диагностики. Оставить такую функцию обёрткой с честной докстрокой
# значило бы сохранить ровно тот молчаливый исход, против которого построен
# весь компилятор, — только с документацией. Документированная потеря данных
# остаётся потерей данных: докстроку читает автор функции, а не тот, кто через
# месяц напишет `for oid, eid in map.items()`.
#
# ЧЕМ ЗАМЕНЯЕТСЯ. Ничем: `receipt_map` отдаёт СПИСОК на любой арности, и
# вызывающий, которому нужен ровно один элемент, обязан сказать это явно —
# `addrs, = receipt_map(...)[oid]` откажет там, где их оказалось два.
#
# Этот блок стоит здесь, а не в истории git, потому что «почему тут нет
# плоской формы» — первый вопрос того, кто придёт её дописывать.
# ─────────────────────────────────────────────────────────────────────────────


def receipt_map(ops: Sequence[Mapping[str, Any]],
                payload: Mapping[str, Any],
                *, strict: bool = False) -> dict[str, list[str]]:
    """Карта для КВИТАНЦИИ, которую читает модель: `op_id → [element_id, …]`.

    СПИСОК ВСЕГДА, ДАЖЕ КОГДА ЭЛЕМЕНТ ОДИН, и это не оформление. Соблазн отдать
    скаляр у арности ОДИН и список у МНОГИХ — ровно тот дефект, который этот
    модуль и закрыл этажом ниже: читатель напишет `map[oid]` в расчёте на
    строку, и на шести операциях из 65 (`create_pipe_system`,
    `create_room_separator`, `route_duct_system`, `route_pipe_system`,
    `move_elements`, `delete`… — точный список у `created_identity_fields`)
    получит не то, чего ждал, БЕЗ ЕДИНОЙ ОШИБКИ. Одна форма на все арности
    заставляет решение о множественности приниматься явно.

    ЕДИНСТВЕННАЯ форма карты в дереве: плоская `op_to_element_ids` удалена
    15.08 вместе со своими утверждениями (довод — в блоке над этой функцией).
    Кому нужен ровно один элемент, пишет это ЯВНО и получает отказ, если их
    оказалось два: `element_id, = receipt_map(ops, payload)[oid]`.

    `strict=False` по умолчанию: квитанция строится ПОСЛЕ того, как
    `serving._result_contract_diagnostic` уже отказал бы (KIR-X008) на любой
    недостающей идентичности, поэтому второй отказ здесь ничего не добавил бы
    к защите и мог бы обрушить УЖЕ СОСТОЯВШУЮСЯ запись.
    """

    return {oid: [a.value for a in addrs]
            for oid, addrs in element_addresses(
                ops, payload, strict=strict).items()}
