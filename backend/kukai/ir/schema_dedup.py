"""Дедупликация JSON Schema через `$defs`/`$ref` — БЕЗ потери выразительности.

ПОВОД ЗАМЕРЕН (03.08.2026). Схема KIR — 22 631 токен, и это 70.7% всего, что
уходит модели на первом ходу (44 615). При этом **66% схемы — дословный
повтор**: селектор `{by: name|element_id|default|family_type}` выписан заново
27–102 раза, потому что `schema_gen._catalog_selector` разворачивает полный
`oneOf` на КАЖДЫЙ селекторный параметр КАЖДОГО опа.

ПОЧЕМУ ЭТО ПЕРВЕЕ ЯРУСОВ. Замер трёх вариантов:

    сегодня                      22 631 токен    1.00x
    все 39 опов + $ref            7 719 токен    2.93x   ← ничего не скрыто
    ярус 1 (21 оп), без $ref     11 669 токен    1.94x
    ярус 1 + $ref                 4 488 токен    5.04x

Дедупликация ОДНА обгоняет ярусы и стоит **ноль честности**: ни один оп не
исчезает из контекста. А ярусы платят видимостью, и цена уже измерена — из
журнала отказов 4.8% компиляций это ВЫДУМАННЫЕ опы (`create_rebar`,
`create_elevator`, `create_vent_shaft`): чего модель не видит, то она сочиняет.

ПОЧЕМУ ПОСТ-ПРОХОД, А НЕ ПРАВКА ГЕНЕРАТОРА. Написать `$defs` руками означало бы
завести второй источник правды о форме селектора: генератор поменяли — таблица
отстала, и схема начала описывать не тот язык. Здесь же общие поддеревья
НАХОДЯТСЯ в готовой схеме, поэтому разойтись с генератором нечему по
построению. И главное — преобразование ОБРАТИМО, а значит тождество не
обещание, а проверяемый факт: `expand(hoist(s)) == s` побайтово (тест
`test_schema_dedup.py`).

ЧТО НЕ ДЕЛАЕТСЯ ЗДЕСЬ. Схема не сокращается «по смыслу»: ни одно ограничение не
ослабляется, ни один `description` не выбрасывается. Экономия берётся
исключительно из повтора. Если однажды понадобится резать смысл — это другое
решение, с другой ценой, и принимать его надо отдельно.

ОТКРЫТЫЙ РИСК, НАЗВАННЫЙ ЧЕСТНО: держит ли рабочая модель `$defs`/`$ref` так же
хорошо, как плоскую схему. Constrained decoding в проде ВЫКЛЮЧЕН — схема едет
модели текстом, — поэтому речь про понимание, а не про грамматику декодера.
Это A/B на `tools/design/mission_bench.py`, а не допущение, и до его прохождения
`program_schema()` остаётся плоской.
"""
from __future__ import annotations

import json
from typing import Any

from kukai.ir.emit_utils import ELEMENT_ID_MAX

#: Порог: поддерево попадает в `$defs`, только если это ВЫГОДНО. Условие
#: считается, а не назначается — см. `_net_saving`.
_REF_OVERHEAD = len('{"$ref":"#/$defs/"}')

#: Минимальная длина канонического представления. Ниже неё ссылка почти всегда
#: дороже тела (`{"type":"string"}` — 19 байт против 26 у ссылки), и хойст
#: сделал бы схему БОЛЬШЕ, оставаясь формально «дедупликацией».
_MIN_BODY = 40


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


#: Ключевые слова, ЗНАЧЕНИЕ которых само является схемой.
_SCHEMA_VALUE = frozenset({
    "items", "additionalProperties", "propertyNames", "contains", "not",
    "if", "then", "else", "additionalItems", "unevaluatedItems",
    "unevaluatedProperties",
})

#: Ключевые слова, значение которых — СПИСОК схем.
_SCHEMA_LIST = frozenset({"oneOf", "anyOf", "allOf", "prefixItems"})

#: Ключевые слова, значение которых — КАРТА «имя → схема». Сама карта схемой
#: НЕ является, схемы — только её значения.
_SCHEMA_MAP = frozenset({
    "properties", "$defs", "definitions", "patternProperties",
    "dependentSchemas",
})


def _walk(node: Any):
    """Поддеревья, стоящие в ПОЗИЦИИ СХЕМЫ, кроме корня.

    ПОЗИЦИЯ РЕШАЕТ ВСЁ, и это не педантизм — это корректность. Первая редакция
    обходила словарь без разбора и выносила, среди прочего, карту `properties`
    целиком. Получалось `{"type":"object","properties":{"$ref":"#/$defs/..."}}`,
    и такая схема ОБРАТИМА (тест тождества её пропускал), но НЕВАЛИДНА: внутри
    `properties` ключ `$ref` читается как имя свойства с именем «$ref», а не
    как ссылка. То есть модель получила бы объект, у которого «есть свойство
    $ref», вместо описания операции.

    Поймано тестом читаемости имён 03.08 — он ругался на 44 безымянные формы, и
    за этой косметикой лежал настоящий дефект. Урок ровно тот же, что уже
    записан в этом пакете: тождества НЕДОСТАТОЧНО, надо ещё, чтобы промежуточная
    форма была законной сама по себе.
    """
    if isinstance(node, dict):
        yield from _walk_children(node)


def _walk_children(node: dict):
    for key, value in node.items():
        if key in _SCHEMA_VALUE:
            yield from _walk_schema(value)
        elif key in _SCHEMA_LIST and isinstance(value, list):
            for item in value:
                yield from _walk_schema(item)
        elif key in _SCHEMA_MAP and isinstance(value, dict):
            for item in value.values():
                yield from _walk_schema(item)


def _walk_schema(node: Any):
    """Узел В ПОЗИЦИИ СХЕМЫ: он сам кандидат, и его дети тоже."""
    if isinstance(node, dict):
        yield node
        yield from _walk_children(node)


def _net_saving(body_len: int, occurrences: int, name_len: int) -> int:
    """Сколько байт экономит вынос: было `n * body`, стало `body + n * ref`."""
    ref_len = _REF_OVERHEAD + name_len
    return occurrences * body_len - (body_len + occurrences * ref_len)


def _num(value: Any) -> str:
    """Число в имени: без хвостов и без точки, минус читается словом."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).replace(".", "p")
    return text.replace("-", "neg")


def _ref_tail(node: Any) -> str | None:
    """Короткое имя вложенного узла: хвост ссылки либо имя его собственной формы.

    Имена присваиваются ДО подстановки ссылок, поэтому вложенный узел здесь
    почти всегда ещё развёрнут. Ветка с `$ref` оставлена для повторного вызова
    на уже свёрнутом дереве — иначе имя зависело бы от порядка обработки, а оно
    обязано зависеть только от содержимого.
    """
    if not isinstance(node, dict):
        return None
    ref = node.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    return _semantic_name(node)


def _semantic_name(body: dict) -> str | None:
    """Читаемое имя, когда форму удаётся УЗНАТЬ.

    Имя видит МОДЕЛЬ, и `#/$defs/pt_xy` объясняет ей форму, а `#/$defs/shape_30`
    — нет. Правило одно: называем только то, что распознаётся структурно.
    Выдумать «осмысленное» имя там, где смысл не выведен, хуже честного
    порядкового номера — это ровно та подмена, за которую в этом пакете платят.
    """
    keys = set(body)

    # Селектор: объект с `by: {"const": ...}`.
    props = body.get("properties")
    if isinstance(props, dict):
        by = props.get("by")
        if isinstance(by, dict) and isinstance(by.get("const"), str):
            return f"sel_by_{by['const']}"
        # Контур/область: объект с `shape: {"const": ...}`.
        shape = props.get("shape")
        if isinstance(shape, dict) and isinstance(shape.get("const"), str):
            return f"region_{shape['const']}"

    # Объединение селекторов — перечисляем роды, это и есть его смысл.
    if keys == {"oneOf"} and isinstance(body["oneOf"], list):
        tails = [_ref_tail(v) for v in body["oneOf"]]
        if all(t and t.startswith("sel_by_") for t in tails):
            return "sel_" + "_or_".join(t[len("sel_by_"):] for t in tails)
        if all(isinstance(v, dict) and set(v) == {"type"} for v in body["oneOf"]):
            return "scalar_" + "_or_".join(v["type"] for v in body["oneOf"])

    # Массивы.
    if body.get("type") == "array":
        items = body.get("items")
        lo, hi = body.get("minItems"), body.get("maxItems")
        if isinstance(items, dict) and set(items) == {"type"} and lo == hi:
            if items["type"] == "number":
                return {2: "pt_xy", 3: "pt_xyz"}.get(lo) or f"nums_{lo}"
            return f"{items['type']}s_{lo}"
        tail = _ref_tail(items)
        if tail:
            span = (f"_{_num(lo)}_{_num(hi)}" if lo is not None and hi is not None
                    else "")
            return f"list_{tail}{span}"

    # Числа и строки с границами — граница И ЕСТЬ их смысл.
    if keys <= {"type", "minimum", "maximum"} and body.get("type") in (
            "number", "integer"):
        lo, hi = body.get("minimum"), body.get("maximum")
        if body["type"] == "integer" and lo == 1 and hi == ELEMENT_ID_MAX:
            return "element_id"
        if lo is not None and hi is not None:
            return f"{body['type']}_{_num(lo)}_{_num(hi)}"
    if keys <= {"type", "minLength", "maxLength", "pattern"} and body.get(
            "type") == "string" and body.get("maxLength") is not None:
        trimmed = "_trimmed" if "pattern" in body else ""
        return f"str_{_num(body['maxLength'])}{trimmed}"

    # Перечисления: словарь родов узнаём по составу, прочие — по началу списка.
    if keys <= {"type", "enum"} and isinstance(body.get("enum"), list):
        values = body["enum"]
        if set(values) == set(_kind_enum_values()):
            return "kind_enum"
        if all(isinstance(v, str) for v in values) and len(values) <= 4:
            return "enum_" + "_".join(values)
        return f"enum_{len(values)}"
    return None


def _kind_enum_values() -> list[str]:
    """Словарь родов объектов — читается из реестра, а не переписывается."""
    from kukai.ir import spec
    return sorted(spec.KINDS) + [spec.KIND_ESCAPE]


def hoist(schema: dict) -> dict:
    """Схема с `$defs`: повторяющиеся поддеревья вынесены, остальное как было.

    Детерминированно: имена и порядок зависят только от СОДЕРЖИМОГО схемы, не
    от порядка обхода и не от версии Python. Иначе один и тот же реестр давал бы
    разные схемы между запусками, и любой хеш поверх неё стал бы бессмысленным.
    """
    if not isinstance(schema, dict):
        raise TypeError("hoist ожидает объект схемы")
    if "$defs" in schema:
        raise ValueError("схема уже содержит $defs — повторный хойст запрещён")

    counts: dict[str, int] = {}
    bodies: dict[str, dict] = {}
    for node in _walk(schema):
        key = _canon(node)
        counts[key] = counts.get(key, 0) + 1
        bodies.setdefault(key, node)

    # Кандидаты: встречаются больше раза И вынос ВЫГОДЕН. Сортировка по
    # (убывание длины, канон) — длинные вперёд, чтобы вложенные общие куски
    # тоже подхватились; канон вторым ключом даёт полную детерминированность.
    candidates = sorted(
        (key for key, count in counts.items()
         if count > 1 and len(key) >= _MIN_BODY),
        key=lambda key: (-len(key), key))

    names: dict[str, str] = {}
    used: set[str] = set()
    for index, key in enumerate(candidates):
        body = bodies[key]
        name = _semantic_name(body) or f"shape_{index}"
        if name in used:
            name = f"{name}_{index}"
        if _net_saving(len(key), counts[key], len(name)) <= 0:
            continue
        names[key] = name
        used.add(name)

    if not names:
        return json.loads(_canon(schema))

    def in_schema_position(node: Any, *, skip: str | None) -> Any:
        """Замена допустима ЗДЕСЬ: узел стоит там, где ожидается схема."""
        if isinstance(node, dict):
            key = _canon(node)
            if key in names and key != skip:
                return {"$ref": f"#/$defs/{names[key]}"}
            return descend(node, skip=skip)
        return node

    def descend(node: dict, *, skip: str | None) -> dict:
        """Спуск по ключам: подставлять ссылку можно только в схемных позициях,
        а данные (`const`, `enum`, `required`, `description`) идут как есть."""
        out: dict = {}
        for key, value in node.items():
            if key in _SCHEMA_VALUE:
                out[key] = in_schema_position(value, skip=skip)
            elif key in _SCHEMA_LIST and isinstance(value, list):
                out[key] = [in_schema_position(item, skip=skip)
                            for item in value]
            elif key in _SCHEMA_MAP and isinstance(value, dict):
                out[key] = {name: in_schema_position(item, skip=skip)
                            for name, item in value.items()}
            else:
                out[key] = value
        return out

    defs = {names[key]: descend(bodies[key], skip=key)
            for key in sorted(names, key=lambda k: names[k])}
    out = descend(schema, skip=None)
    # `$defs` кладётся ПОСЛЕ остальных ключей: заголовок схемы должен читаться
    # первым и человеком, и моделью.
    out["$defs"] = defs
    return out


def expand(schema: dict) -> dict:
    """Обратная функция: вернуть плоскую схему, развернув все `$ref`.

    Существует не ради удобства, а ради доказательства. Пока `expand(hoist(s))`
    побайтово равно `s`, утверждение «мы ничего не потеряли» — факт, который
    проверяет машина. Без неё это было бы обещание, а обещания в этом доме уже
    подводили.
    """
    defs = schema.get("$defs") or {}
    if not isinstance(defs, dict):
        raise ValueError("$defs должен быть объектом")

    def resolve(node: Any, depth: int = 0) -> Any:
        """Разворот идёт по ТЕМ ЖЕ позициям, по которым шёл вынос.

        Симметрия обязательна: развернуть шире, чем свернули, значит принять за
        ссылку данные, у которых просто оказался ключ `$ref` (а такое поле в
        принципе может встретиться в `const` или `enum`).
        """
        if depth > 32:
            raise ValueError("циклическая ссылка $ref")
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and len(node) == 1:
            prefix = "#/$defs/"
            if not ref.startswith(prefix):
                raise ValueError(f"неподдерживаемая ссылка {ref!r}")
            name = ref[len(prefix):]
            if name not in defs:
                raise ValueError(f"висячая ссылка {ref!r}")
            return resolve(defs[name], depth + 1)
        out: dict = {}
        for key, value in node.items():
            if key in _SCHEMA_VALUE:
                out[key] = resolve(value, depth)
            elif key in _SCHEMA_LIST and isinstance(value, list):
                out[key] = [resolve(item, depth) for item in value]
            elif key in _SCHEMA_MAP and isinstance(value, dict):
                out[key] = {name: resolve(item, depth)
                            for name, item in value.items()}
            else:
                out[key] = value
        return out

    # Корень — САМ схема, и разворачивать его надо целиком, а не поключевно.
    # Поключевой обход звал `resolve` на ЗНАЧЕНИИ ключа `properties`, то есть на
    # карте «имя → схема», а не на схеме; внутри карты имена свойств не
    # являются ключевыми словами, и ссылки под ними оставались неразвёрнутыми.
    # Ловится только сверкой на тождество — глазами такое не видно.
    return resolve({key: value for key, value in schema.items()
                    if key != "$defs"})


def measure(schema: dict) -> dict:
    """Что дал вынос — числами, а не ощущением."""
    flat = _canon(schema if "$defs" not in schema else expand(schema))
    packed = _canon(hoist(schema) if "$defs" not in schema else schema)
    return {
        "flat_bytes": len(flat),
        "packed_bytes": len(packed),
        "ratio": round(len(flat) / len(packed), 3) if packed else 0.0,
        "defs": len((hoist(schema) if "$defs" not in schema
                     else schema).get("$defs", {})),
    }


__all__ = ["expand", "hoist", "measure"]
