"""КАКУЮ форму схемы получает модель — и ПОЧЕМУ именно её.

`schema_gen.program_schema()` выписывает каждый селектор дословно, поэтому две
трети схемы — повтор. `schema_dedup.hoist` этот повтор выносит в `$defs`, ничего
не убирая из виду. Здесь решается ОДИН вопрос: доезжает ли `$ref` до модели
целым на ЭТОЙ установке. Ответ обязан быть измерен, а не предположен, поэтому
список безопасных транспортов — таблица замеров, а не список надежд.

ЗАМЕРЕНО ЖИВЬЁМ 09.08.2026, оба плеча одним и тем же запросом (max_tokens=1,
tool_choice=auto), число берётся из `usage.prompt_tokens` ПОСТАВЩИКА, а не из
нашего токенизатора:

    транспорт                       плоская   свёрнутая   раз
    openrouter/deepseek-v4-flash     42 390     11 751    3.61x   HTTP 200 обе
    openai/gpt-5.6-sol (CLIProxy)    20 628      3 633    5.68x   HTTP 200 обе

Тот же замер на ПОЛНОМ инструменте `revit_ir` (описание + program + program_py),
поставщик закреплён одинаковый: 53 914 → 23 275 токенов, экономия 30 639 за
КАЖДЫЙ ход.

ПОЧЕМУ УСЛОВНО, А НЕ ВСЕГДА. Цена ошибки несимметрична и уже названа в
`serving.inject_revit_ir_schema`: поставщик, отвергший пачку инструментов
целиком, ломает ХОД — то есть все способности сразу, а не одну. Поэтому
преобразование применяется только там, где приём `$ref` ЗАМЕРЕН, а всюду ещё
схема остаётся ровно такой, какой была, и причина НАЗЫВАЕТСЯ (закон «ничего
молча»).

ДВА РОДА «НЕЛЬЗЯ», И ИХ НАДО РАЗЛИЧАТЬ:
  * НЕИЗВЕСТНО — транспорт не замерен. Молчим и не трогаем схему.
  * БЕССМЫСЛЕННО — litellm сам разворачивает `$defs` обратно перед отправкой
    (`llms/vertex_ai/common_utils.py::_build_vertex_schema` → `unpack_defs`,
    вызывается на `parameters` КАЖДОГО объявления функции, строка 584 в
    установленной версии). На gemini/vertex вынос не экономит ни токена —
    значит делать его там не «безопасно», а незачем.

ЧЕГО ЗДЕСЬ НЕТ И ЧТО ЧЕСТНО ОСТАЁТСЯ ОТКРЫТЫМ. Замерено, что `$ref` ДОЕЗЖАЕТ и
что он ДЕШЕВЛЕ. НЕ замерено, читает ли рабочая модель схему со ссылками так же
хорошо, как плоскую: это A/B на `tools/design/mission_bench.py`, и его никто ещё
не гонял. Поэтому у выноса есть именованный рубильник
`KUKAI_KIR_SCHEMA_DEDUP=0`, который возвращает прежнюю схему целиком, и решение
записано здесь словами, а не растворено в коде.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from kukai.ir import schema_dedup
from kukai.ir.schema_gen import program_schema

logger = logging.getLogger(__name__)

#: Рубильник. `0` — прежняя плоская схема; `1` — вынос независимо от транспорта
#: (для стенда); не задан — решает замер транспорта.
_FLAG = "KUKAI_KIR_SCHEMA_DEDUP"

#: Префиксы litellm, на которых приём `$ref` ЗАМЕРЕН живьём (таблица в шапке).
#: `openai/` покрывает и прокси-плечи: `codex_route` шлёт `model=f"openai/{...}"`,
#: agy/antigravity — тоже, и именно этот эндпоинт и был опрошен.
_REF_MEASURED = ("openrouter/", "openai/")

#: Префиксы, где litellm разворачивает `$defs` обратно ⇒ экономии не будет.
_REF_POINTLESS = ("vertex_ai/", "gemini/")

#: Основной ход. Если модель не названа — транспорт неизвестен, и это ОТКАЗ
#: от преобразования, а не повод угадать.
_PRIMARY_ENV = "KUKAI_LLM_MODEL"

#: Прочие плечи ОДНОГО хода: пачка инструментов строится один раз и переживает
#: всю цепочку запасных, поэтому безопасным обязан быть КАЖДЫЙ.
_LEG_ENV = (
    "KUKAI_LLM_THINKING_MODEL",
    "KUKAI_LLM_FALLBACK_MODEL",
    "KUKAI_LLM_LAST_RESORT_MODEL",
    "KUKAI_MODELING_LLM_MODEL",
)

#: Плечи, которые litellm видит как `openai/<имя>` (префикс ставит наш код, а не
#: окружение) — `codex_route.py:406`, `client.py` для agy.
_OPENAI_PREFIXED_ENV = (
    "KUKAI_CODEXPROXY_MODEL",
    "KUKAI_CODEXPROXY_MODEL_FALLBACK",
    "KUKAI_AGY_MODEL",
    "KUKAI_ANTIGRAVITY_MODEL",
)

#: Ярусы запасных моделей едут одним JSON — `transport._parse_fallback_tiers`.
_TIERS_ENV = "KUKAI_FALLBACK_TIERS"


def _tier_models() -> list[str]:
    raw = (os.environ.get(_TIERS_ENV) or "").strip()
    if not raw:
        return []
    try:
        tiers = json.loads(raw)
    except Exception:  # noqa: BLE001 — разбор ярусов не наша забота, но и не повод врать
        return ["<нечитаемый KUKAI_FALLBACK_TIERS>"]
    out: list[str] = []
    if isinstance(tiers, list):
        for tier in tiers:
            if isinstance(tier, dict) and isinstance(tier.get("model"), str):
                out.append(tier["model"].strip())
    return [m for m in out if m]


def configured_models() -> list[str]:
    """Все модели, которые МОГУТ увезти эту пачку инструментов за один ход."""
    models: list[str] = []
    primary = (os.environ.get(_PRIMARY_ENV) or "").strip()
    if primary:
        models.append(primary)
    for name in _LEG_ENV:
        value = (os.environ.get(name) or "").strip()
        if value:
            models.append(value)
    for name in _OPENAI_PREFIXED_ENV:
        value = (os.environ.get(name) or "").strip()
        if value:
            models.append(value if "/" in value else f"openai/{value}")
    models.extend(_tier_models())
    seen: set[str] = set()
    return [m for m in models if not (m in seen or seen.add(m))]


def transport_verdict() -> tuple[bool, str]:
    """(выносить ли, ПОЧЕМУ) — причина по-русски и всегда называет виновника."""
    flag = (os.environ.get(_FLAG) or "").strip()
    if flag == "0":
        return False, f"выключено рубильником {_FLAG}=0"
    if flag == "1":
        return True, f"включено рубильником {_FLAG}=1 (транспорт не проверялся)"

    primary = (os.environ.get(_PRIMARY_ENV) or "").strip()
    if not primary:
        return False, (f"транспорт неизвестен: {_PRIMARY_ENV} не задан — схема "
                       f"остаётся плоской, пока приём $ref не замерен")

    models = configured_models()
    pointless = [m for m in models if m.startswith(_REF_POINTLESS)]
    unknown = [m for m in models
               if not m.startswith(_REF_MEASURED) and m not in pointless]
    if pointless:
        return False, (f"litellm разворачивает $defs обратно перед отправкой на "
                       f"{', '.join(sorted(pointless))} — вынос не сэкономил бы "
                       f"ни токена")
    if unknown:
        return False, (f"приём $ref не замерен на {', '.join(sorted(unknown))} — "
                       f"схема остаётся плоской (замерь и внеси в _REF_MEASURED)")
    return True, (f"$ref замерен живьём на {_plural_legs(len(models))} хода "
                  f"({', '.join(models[:3])}{'…' if len(models) > 3 else ''})")


def _plural_legs(n: int) -> str:
    return f"{n} плече" if n % 10 == 1 and n % 100 != 11 else f"{n} плечах"


#: Вынос стоит 45 мс на схему (замер 09.08), а `_resolve_tools` зовётся каждый
#: запрос. Ключ — канонические байты ПЛОСКОЙ схемы, поэтому правка реестра
#: инвалидирует кэш сама, без ручного сброса.
_CACHE: dict[str, dict] = {}
_CACHE_MAX = 2
_announced: set[str] = set()


def _hoist_cached(flat: dict) -> dict:
    key = json.dumps(flat, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    packed = schema_dedup.hoist(flat)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = packed
    return packed


def program_schema_for_tool() -> tuple[dict, str]:
    """Схема поля `program` для инструмента + НАЗВАННАЯ причина её формы.

    Ничего молча: путь, на котором вынос не применён, обязан сказать об этом, а
    не тихо отдать прежнее — иначе «сэкономили» и «не сэкономили» выглядят
    одинаково, и регресс живёт незамеченным ровно до следующего счёта.
    """
    flat = program_schema()
    hoist_it, why = transport_verdict()
    if not hoist_it:
        note = f"схема KIR плоская: {why}"
        if why not in _announced:
            _announced.add(why)
            logger.info("KIR schema dedup OFF — %s", why)
        return flat, note

    packed = _hoist_cached(flat)
    stats = _measure(flat, packed)
    note = (f"схема KIR свёрнута в $defs ({stats['ratio']}x, "
            f"{stats['flat_bytes']}→{stats['packed_bytes']} байт, "
            f"{stats['defs']} форм): {why}")
    if why not in _announced:
        _announced.add(why)
        logger.info("KIR schema dedup ON — %s", note)
    return packed, note


def _measure(flat: dict, packed: dict) -> dict[str, Any]:
    def canon(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    a, b = len(canon(flat)), len(canon(packed))
    return {"flat_bytes": a, "packed_bytes": b,
            "ratio": round(a / b, 3) if b else 0.0,
            "defs": len(packed.get("$defs", {}))}


def describe_ru() -> str:
    """Одна строка для человека: что именно увидит модель и почему."""
    return program_schema_for_tool()[1]


__all__ = ["configured_models", "describe_ru", "program_schema_for_tool",
           "transport_verdict"]
