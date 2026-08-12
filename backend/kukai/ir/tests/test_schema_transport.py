"""ЧТО ИМЕННО ПОЛУЧАЕТ МОДЕЛЬ — и доказательство, что это ТОТ ЖЕ ЯЗЫК.

Схема KIR на 41 опе стоит 42 390 токенов поставщицкого счёта за КАЖДЫЙ ход
(замер 09.08.2026, живой openrouter/deepseek-v4-flash, `usage.prompt_tokens`).
Свёрнутая в `$defs` — 11 751. Экономия не бесплатна ровно в одном месте: схема
со ссылками ОБЯЗАНА принимать и отвергать в точности те же программы, что
плоская. Если это не так, мы сэкономили токены и поменяли язык, а это худшая
сделка в этом доме.

Здесь три доказательства, и они разные по природе:

  1. ТОЖДЕСТВО ФОРМЫ   — `expand(hoist(s))` побайтово равно `s`;
  2. ТОЖДЕСТВО ПОВЕДЕНИЯ — корпус реальных программ (собран из самого набора
     тестов) плюс заведомо неверные: у каждой ОДИН И ТОТ ЖЕ вердикт у обеих
     схем, и совпадать обязаны не только «да/нет», но и ПУТИ ошибок;
  3. СВОЙСТВО НА ПОРОЖДЁННЫХ — образцы каждой ветки каждого опа, верные и
     испорченные, тем же сравнением.

Первое ловит потерю данных, второе — потерю смысла на том, что люди правда
писали, третье — потерю ограничения в ветке, куда корпус не заглянул.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import random
import tempfile
from typing import Any

import pytest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import schema_dedup, schema_transport, spec  # noqa: E402
from kukai.ir.schema_gen import program_schema  # noqa: E402

jsonschema = pytest.importorskip("jsonschema")


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@pytest.fixture(scope="module")
def flat() -> dict:
    return program_schema()


@pytest.fixture(scope="module")
def packed(flat: dict) -> dict:
    return schema_dedup.hoist(flat)


@pytest.fixture(scope="module")
def validators(flat: dict, packed: dict):
    return (jsonschema.Draft202012Validator(flat),
            jsonschema.Draft202012Validator(packed))


def _verdict(validator, program) -> tuple[bool, list[str]]:
    """Вердикт вместе с ПУТЯМИ — «отверг» мало, важно ГДЕ и ЧЕМ."""
    errors = sorted("/".join(str(p) for p in e.absolute_path) + "|" + e.validator
                    for e in validator.iter_errors(program))
    return (not errors, errors)


def _same(validators, program, label: str) -> bool:
    flat_v, packed_v = validators
    a, ea = _verdict(flat_v, program)
    b, eb = _verdict(packed_v, program)
    assert a == b, (f"{label}: плоская схема сказала {a}, свёрнутая {b} — "
                    f"это РАЗНЫЕ языки, экономия не имеет значения")
    assert ea == eb, (f"{label}: вердикт совпал, а причины разошлись\n"
                      f"  плоская:  {ea[:3]}\n  свёрнутая: {eb[:3]}")
    return a


# ─── ДОКАЗАТЕЛЬСТВО 1: тождество формы ──────────────────────────────────────

def test_proof_1_round_trip_is_byte_exact(flat: dict, packed: dict) -> None:
    """`expand(hoist(s)) == s` — и как объекты, и побайтово в каноне."""
    back = schema_dedup.expand(packed)
    assert back == flat, "разворот вернул не ту схему"
    assert _canon(back) == _canon(flat), "разворот совпал по смыслу, но не по байтам"


# ─── ДОКАЗАТЕЛЬСТВО 2: тождество поведения на реальном корпусе ──────────────

_TEST_TREE = pathlib.Path(__file__).resolve().parents[3]


def _harvest_programs() -> list[tuple[str, Any]]:
    """Все литеральные программы KIR из дерева тестов — БЕЗ импорта модулей.

    Корпус собирается разбором исходников, а не рукописным списком: рукописный
    отстаёт от набора тестов при первой же новой волне, и «прогнали корпус»
    начинает значить «прогнали то, что кто-то однажды выписал».
    """
    out: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for root in ("kukai/ir", "tools/design", "tests"):
        base = _TEST_TREE / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Dict, ast.List)):
                    continue
                try:
                    value = ast.literal_eval(node)
                except (ValueError, TypeError, SyntaxError, MemoryError,
                        RecursionError):
                    continue
                program: Any = None
                if (isinstance(value, dict) and isinstance(value.get("ops"), list)
                        and value["ops"]
                        and all(isinstance(o, dict) for o in value["ops"])):
                    program = value
                elif (isinstance(value, list) and value
                      and all(isinstance(o, dict) and isinstance(o.get("op"), str)
                              for o in value)):
                    program = {"ir_version": spec.IR_VERSION, "ops": value}
                if program is None:
                    continue
                key = _canon(program)
                if key not in seen:
                    seen.add(key)
                    out.append((path.name, program))
    return out


#: Заведомо НЕВЕРНЫЕ программы, нацеленные ровно туда, где ссылка могла бы
#: потерять ограничение: селекторы, границы чисел, арность точек, адрес от осей
#: и — отдельно — данные, которые сами ВЫГЛЯДЯТ как ссылка.
INVALID: list[tuple[str, Any]] = [
    ("нет ir_version", {"ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
    ("чужой ir_version", {"ir_version": "9.9",
                          "ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
    ("пустой ops", {"ir_version": spec.IR_VERSION, "ops": []}),
    ("несуществующий оп", {"ir_version": spec.IR_VERSION,
                           "ops": [{"op": "make_coffee"}]}),
    ("лишний ключ конверта", {"ir_version": spec.IR_VERSION, "junk": 1,
                              "ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
    ("селектор неизвестного рода", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "level": {"by": "vibe", "value": "x"}, "height_mm": 3000}]}),
    ("селектор без value", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "level": {"by": "name"}, "height_mm": 3000}]}),
    ("селектор с лишним ключом", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "level": {"by": "name", "value": "Этаж 1", "colour": "red"},
         "height_mm": 3000}]}),
    ("element_id вне границ", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "query_inspect", "id": "q",
         "target": {"by": "element_id", "value": -5}}]}),
    ("element_id ноль", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "query_inspect", "id": "q",
         "target": {"by": "element_id", "value": 0}}]}),
    ("точка не той арности", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0, 0, 0], "p1_mm": [1000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000}]}),
    ("точка не того типа", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": ["a", "b"], "p1_mm": [1000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000}]}),
    ("адрес от осей сломан", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": {"at_grid": ["1"]},
         "p1_mm": [1000, 0], "level": {"by": "name", "value": "Этаж 1"},
         "height_mm": 3000}]}),
    ("род не из словаря", {"ir_version": spec.IR_VERSION,
                           "ops": [{"op": "query_count", "id": "a", "kind": "🦄"}]}),
    ("число ниже минимума", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": -1}]}),
    ("intent длиннее предела", {"ir_version": spec.IR_VERSION, "intent": "ы" * 5000,
                                "ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
    ("оп — это $ref", {"ir_version": spec.IR_VERSION,
                       "ops": [{"$ref": "#/$defs/sel_by_name"}]}),
    ("не объект вовсе", None),
    ("строка вместо программы", "wall"),
    ("список вместо программы", [{"op": "query_count"}]),
    ("пустой объект", {}),
]


#: ВЕРНЫЕ программы, в которых ДАННЫЕ выглядят как ссылка. Разворот, идущий
#: шире выноса, принял бы такое поле за `$ref` и подменил бы его телом формы —
#: и это была бы не отвергнутая программа, а МОЛЧА ДРУГАЯ. Поэтому они
#: проверяются отдельным списком, где ожидается «принято обеими».
REF_LOOKALIKE: list[tuple[str, Any]] = [
    ("имя выглядит как ссылка", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "query_inspect", "id": "q", "target": {
            "by": "name", "value": "#/$defs/sel_by_name", "kind": "wall"}}]}),
    ("замысел выглядит как ссылка", {
        "ir_version": spec.IR_VERSION, "intent": "{\"$ref\": \"#/$defs/pt_xy\"}",
        "ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
]


def test_proof_2_the_corpus_gets_identical_verdicts(validators) -> None:
    """Корпус набора тестов + заведомо неверные: вердикт обязан совпасть."""
    harvested = _harvest_programs()
    assert len(harvested) >= 100, (
        f"корпус усох до {len(harvested)} программ — сбор сломался, "
        f"а не тесты похудели")
    accepted = rejected = 0
    for name, program in harvested:
        accepted += _same(validators, program, f"корпус {name}")
    for label, program in INVALID:
        rejected += not _same(validators, program, f"неверная «{label}»")
    assert accepted, "корпус не содержит ни одной ПРИНЯТОЙ программы"
    assert rejected == len(INVALID), (
        "часть заведомо неверных программ прошла ОБЕ схемы — тогда они не "
        "проверяют то, ради чего написаны")
    for label, program in REF_LOOKALIKE:
        assert _same(validators, program, f"похожая на ссылку «{label}»"), (
            f"«{label}» обязана быть ПРИНЯТА: это данные, а не ссылка")


# ─── ДОКАЗАТЕЛЬСТВО 3: свойство на порождённых сочетаниях ───────────────────

def _sample(schema: dict, rng: random.Random, valid: bool, depth: int = 0) -> Any:
    """Образец по схеме. Каждая ветка `oneOf` равновероятна, поэтому вынесенное
    поддерево получает и верные значения, и нарушающие ровно его ограничение."""
    if depth > 10:
        return None
    if "const" in schema:
        return schema["const"] if valid else "___не_та_константа___"
    if "enum" in schema:
        return rng.choice(schema["enum"]) if valid else "___не_из_словаря___"
    for key in ("oneOf", "anyOf"):
        if key in schema:
            return _sample(rng.choice(schema[key]), rng, valid, depth + 1)
    kind = schema.get("type")
    if kind == "object":
        props = schema.get("properties") or {}
        required = set(schema.get("required") or ())
        out: dict = {}
        for name, sub in props.items():
            if name in required or rng.random() < 0.55:
                out[name] = _sample(sub, rng, valid, depth + 1)
        if not valid and rng.random() < 0.35:
            out["___сюрприз___"] = 1
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            for i in range(schema.get("minProperties") or 1):
                out[f"k{i}"] = _sample(extra, rng, valid, depth + 1)
        return out
    if kind == "array":
        lo = schema.get("minItems", 1)
        hi = schema.get("maxItems", max(lo, 3))
        n = rng.randint(lo, min(hi, lo + 2))
        if not valid and rng.random() < 0.5:
            n = hi + 1
        items = schema.get("items")
        return [_sample(items, rng, valid, depth + 1) if isinstance(items, dict)
                else 0 for _ in range(n)]
    if kind in ("number", "integer"):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        if not valid:
            return lo - 1 if lo is not None else (hi + 1 if hi is not None
                                                  else "не число")
        if lo is not None and hi is not None:
            value = rng.choice([lo, hi, (lo + hi) / 2])
        elif lo is not None:
            value = rng.choice([lo, lo + 1000])
        elif hi is not None:
            value = rng.choice([hi, hi - 1000])
        else:
            value = rng.choice([0, 1, -1, 1234.5])
        if kind == "integer":
            value = int(value)
        floor = schema.get("exclusiveMinimum")
        if floor is not None and value <= floor:
            value = floor + 1
        return value
    if kind == "string":
        hi = schema.get("maxLength", 24)
        if not valid:
            return "ы" * (hi + 1)
        body = rng.choice(["Этаж 1", "Кирпич 250", "А", "w1", "x"])
        low = schema.get("minLength", 0)
        if len(body) < low:
            body += "y" * (low - len(body))
        return body[:hi] if hi else body
    if kind == "boolean":
        return rng.choice([True, False]) if valid else "да"
    return rng.choice([1, "x", True, None, [], {}])


def test_proof_3_generated_op_combinations_agree(flat: dict, validators) -> None:
    """Каждая ветка каждого опа — образцами, верными и испорченными.

    Корпус показывает, что мы не сломали написанное; здесь проверяется то, чего
    никто ещё не писал. Ветки перебираются ЯВНО, а не выпадают случайно: иначе
    редкий оп остался бы непроверенным, и тест сообщал бы об этом молчанием.
    """
    branches = flat["properties"]["ops"]["items"]["oneOf"]
    assert len(branches) >= len(spec.OPS), "ветки опов пропали из схемы"
    accepted = rejected = 0
    for index, branch in enumerate(branches):
        for shot in range(6):
            rng = random.Random(index * 1000 + shot)
            valid = shot < 3
            program = {"ir_version": spec.IR_VERSION,
                       "ops": [_sample(branch, rng, valid)]}
            if shot % 2:
                program["intent"] = "проба"
            hit = _same(validators, program, f"ветка {index} образец {shot}")
            accepted += hit
            rejected += not hit
    # Сочетания: одна ветка может быть законна в одиночку и нет в компании.
    for seed in range(120):
        rng = random.Random(90_000 + seed)
        ops = [_sample(rng.choice(branches), rng, rng.random() < 0.6)
               for _ in range(rng.randint(2, 4))]
        program = {"ir_version": spec.IR_VERSION, "ops": ops}
        if rng.random() < 0.2:
            program["defaults"] = _sample(flat["properties"]["defaults"], rng,
                                          rng.random() < 0.6)
        hit = _same(validators, program, f"сочетание {seed}")
        accepted += hit
        rejected += not hit
    assert accepted and rejected, (
        f"порождение вырождено: принято {accepted}, отвергнуто {rejected} — "
        f"тест, который всё принимает или всё отвергает, ничего не проверяет")


# ─── ХРАПОВИК: выигрыш обязан пережить следующие волны ──────────────────────

#: Байт свёрнутой схемы НА ОДИН ОП — единственное число, которое переживает
#: рост реестра, и потому единственное, по которому можно ставить границу.
#:
#: ВЫВЕДЕНО, А НЕ НАЗНАЧЕНО. Замер 09.08.2026 на 41 опе: плоская схема — 118 543
#: байта, свёрнутая — 30 626, то есть 747 байт на оп. Реестр растёт к ~120 опам,
#: и граница выбрана из требования, которое можно произнести: **при ЛЮБОМ
#: размере реестра до 120 опов свёрнутая схема не должна стоить дороже, чем
#: стоит СЕГОДНЯШНЯЯ плоская на 41 опе** — 118 543 / 120 = 988 байт на оп.
#: Сегодняшние 747 дают 24% запаса; выход за 988 означает, что утроение реестра
#: вернуло нас к тому счёту, ради ухода от которого вынос и подключён.
MAX_SHIPPED_BYTES_PER_OP = 988

#: Слабейшее СОБЛЮДЁННОЕ сжатие из всех, что мы видели: 3.871x по байтам,
#: 3.61x по токенам поставщика на openrouter, 5.68x на openai/gpt-5.6-sol
#: (замеры 09.08). Порог поставлен ПОД слабейшим замером, а не под сегодняшним
#: числом: тест обязан ловить регресс, а не фиксировать рекорд.
MIN_RATIO = 3.5


def test_the_saving_does_not_rot_back(flat: dict, packed: dict) -> None:
    stats = schema_dedup.measure(flat)
    assert stats["ratio"] >= MIN_RATIO, (
        f"сжатие упало до {stats['ratio']}x при пороге {MIN_RATIO}x — {stats}")
    per_op = len(_canon(packed)) / max(len(spec.OPS), 1)
    assert per_op <= MAX_SHIPPED_BYTES_PER_OP, (
        f"свёрнутая схема стоит {per_op:.0f} байт на оп при потолке "
        f"{MAX_SHIPPED_BYTES_PER_OP}; на 120 опах это "
        f"{per_op * 120:,.0f} байт — дороже сегодняшней ПЛОСКОЙ схемы, то есть "
        f"вынос перестал решать задачу, ради которой подключён")


def test_the_live_tool_actually_ships_the_deduped_schema(monkeypatch) -> None:
    """ГЛАВНЫЙ ХРАПОВИК: ссылки обязаны доехать до ПАНЕЛИ ХОДА, не до модуля.

    Число в тесте выше правится одной строкой; а вот эта проверка красная
    ровно тогда, когда вынос отвязали от живого пути — а именно так дорогая
    работа в этом доме и умирает: код есть, тесты зелёные, прод платит старую
    цену.
    """
    from kukai.ir import serving

    monkeypatch.setenv("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    monkeypatch.delenv("KUKAI_KIR_SCHEMA_DEDUP", raising=False)
    for name in schema_transport._LEG_ENV + schema_transport._OPENAI_PREFIXED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KUKAI_FALLBACK_TIERS", raising=False)

    tools: list = []
    serving.inject_revit_ir_schema(tools)
    program = tools[0]["function"]["parameters"]["properties"]["program"]
    assert "$defs" in program, (
        "инструмент уехал бы с плоской схемой — вынос отключился от живого пути")
    # И это ТА ЖЕ схема: разворот на панели, а не в модуле.
    assert _canon(schema_dedup.expand(program)) == _canon(program_schema())
    # Ни один оп не исчез из виду — этим вынос и отличается от ярусной подачи.
    text = _canon(program)
    missing = sorted(name for name in spec.OPS if f'"{name}"' not in text)
    assert not missing, f"опы пропали из схемы инструмента: {missing}"


def test_an_unverified_transport_keeps_todays_schema_and_says_so(monkeypatch) -> None:
    """Закон «ничего молча»: где не свернули — там названа причина."""
    monkeypatch.setenv("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    monkeypatch.setenv("KUKAI_LLM_THINKING_MODEL", "мой-личный-прокси/model-x")
    for name in schema_transport._OPENAI_PREFIXED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KUKAI_FALLBACK_TIERS", raising=False)
    monkeypatch.delenv("KUKAI_KIR_SCHEMA_DEDUP", raising=False)

    hoist_it, why = schema_transport.transport_verdict()
    assert hoist_it is False
    assert "мой-личный-прокси/model-x" in why, (
        "причина обязана НАЗЫВАТЬ виновника, иначе её нельзя проверить")
    schema, note = schema_transport.program_schema_for_tool()
    assert "$defs" not in schema, "неизвестный транспорт получил ссылки"
    assert _canon(schema) == _canon(program_schema()), (
        "отсутствующее осталось отсутствующим не полностью — схема изменилась")
    assert why in note


def test_gemini_is_refused_for_a_named_reason_not_silence(monkeypatch) -> None:
    """На vertex/gemini litellm сам разворачивает `$defs` — экономии нет.

    Это ВТОРОЙ род отказа, и он обязан отличаться от «мы не проверяли»: сказать
    «неизвестно» там, где известно ровно обратное, — та же ложь, только вежливая.
    """
    monkeypatch.setenv("KUKAI_LLM_MODEL", "vertex_ai/gemini-3-flash-preview")
    for name in (schema_transport._LEG_ENV
                 + schema_transport._OPENAI_PREFIXED_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KUKAI_FALLBACK_TIERS", raising=False)
    monkeypatch.delenv("KUKAI_KIR_SCHEMA_DEDUP", raising=False)

    hoist_it, why = schema_transport.transport_verdict()
    assert hoist_it is False
    assert "разворачивает" in why and "vertex_ai/gemini-3-flash-preview" in why


def test_the_kill_switch_is_honoured_in_both_directions(monkeypatch) -> None:
    monkeypatch.setenv("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    for name in (schema_transport._LEG_ENV
                 + schema_transport._OPENAI_PREFIXED_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KUKAI_FALLBACK_TIERS", raising=False)

    monkeypatch.setenv("KUKAI_KIR_SCHEMA_DEDUP", "0")
    assert schema_transport.transport_verdict()[0] is False
    monkeypatch.setenv("KUKAI_KIR_SCHEMA_DEDUP", "1")
    monkeypatch.setenv("KUKAI_LLM_MODEL", "какой-то/невиданный-транспорт")
    assert schema_transport.transport_verdict()[0] is True


def test_a_missing_model_is_unknown_not_assumed(monkeypatch) -> None:
    monkeypatch.delenv("KUKAI_LLM_MODEL", raising=False)
    monkeypatch.delenv("KUKAI_KIR_SCHEMA_DEDUP", raising=False)
    hoist_it, why = schema_transport.transport_verdict()
    assert hoist_it is False and "KUKAI_LLM_MODEL" in why


def test_every_leg_of_the_turn_is_weighed_not_only_the_primary(monkeypatch) -> None:
    """Пачка инструментов строится ОДИН раз и переживает всю цепочку запасных.

    Значит безопасным обязан быть каждый ярус, а не только основной ход: иначе
    первый же переход на запасную модель увозит ей схему, которой она не ждала.
    """
    monkeypatch.setenv("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    for name in (schema_transport._LEG_ENV
                 + schema_transport._OPENAI_PREFIXED_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KUKAI_FALLBACK_TIERS",
                       json.dumps([{"model": "неизвестный/ярус-2"}]))
    hoist_it, why = schema_transport.transport_verdict()
    assert hoist_it is False and "неизвестный/ярус-2" in why
    assert "неизвестный/ярус-2" in schema_transport.configured_models()
