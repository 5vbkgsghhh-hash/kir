"""ИНДЕКС СУЩЕСТВУЮЩЕГО ЗДАНИЯ — то, по чему автор ищет, как по репозиторию.

ЗАЧЕМ. Каталог (`sandbox.ModelCatalog`) отвечает на вопрос «чем я могу
строить»: уровни, оси, пулы ТИПОВ. На вопрос «что тут уже стоит» не отвечал
никто: четыре опа-запроса (`query_count`/`query_list`/`query_inspect`/
`query_types`) — это ОПЕРАЦИИ внутри программы, то есть рейс к Ревиту, и ответ
приходит в КВИТАНЦИЮ, а не в руки скрипту. Ветвиться по найденному нельзя.

Из-за этого цикл «сделал → посмотрел → проанализировал → поправил» распадался
на ходы: найти элемент — ход, посмотреть — ход, поправить — ход. Здесь он
собирается в один: индекс приезжает тем же кадром stdin, что и каталог, и
автор ищет в нём локально.

═══════════════════════════════════════════════════════════════════════════
ПОТОЛОК НАЗНАЧЕН ЗАМЕРОМ, А НЕ ВКУСОМ (15.08.2026)
═══════════════════════════════════════════════════════════════════════════

Ребёнок песочницы живёт под `DEFAULT_MEMORY_MB = 256` и `DEFAULT_CPU_SECONDS =
5.0`. Замер на трёх настоящих зданиях корпуса, строка округлена до целых
миллиметров:

    здание               элементов   индекс     Б/эл   разбор   RSS процесса
    sob62_r23_v5             1 510    0.29 МБ    193   0.01 с      36 МБ
    snowdon_plumb_v3         6 556    0.99 МБ    150   0.03 с      47 МБ
    k2_ar_rd_v15           115 889   16.68 МБ    143   0.39 с     268 МБ  ← ПЕРЕБОР

Связывает ПАМЯТЬ, а не время: разбор башни стоит 0.39 с из пяти, но процесс
упирается в 268 МБ при потолке 256. Отсюда `CEILING_BYTES = 8 МБ` — та же
величина, что уже стоит транспортным потолком результата
(`sandbox.MAX_RESULT_BYTES`), а не новое число из головы.

**59 разборов корпуса из 71 помещаются целиком** при этом потолке (замер по
размеру `L0.jsonl`, соотношение индекс/L0 держится 0.19–0.21 на всех трёх).

ОКРУГЛЕНИЕ ДО МИЛЛИМЕТРА — тоже замер: без него строка весит 320–427 Б, с ним
143–193 Б. Здание проектируют в миллиметрах; семнадцать значащих цифр в индексе
поиска описывают не здание, а формат double.

═══════════════════════════════════════════════════════════════════════════
ТРИ ИСХОДА, И НИ ОДИН НЕ МОЛЧИТ
═══════════════════════════════════════════════════════════════════════════

Тот же закон, что у каталога (`sandbox.ModelCatalog._rows`), и заведён он здесь
не по симметрии, а потому что цена ошибки та же:

* **`tier="full"`** — приехали все элементы. Пустой ответ на поиск есть факт О
  ЗДАНИИ: такого в нём нет, автор ветвится;
* **`tier="census"`** — здание не поместилось, приехала только перепись. Поиск
  ОТКАЗЫВАЕТ и называет число, потолок и способ сузить. Пустой ответ здесь был
  бы ложью: мы не смотрели;
* **индекса нет вовсе** — отказ третьего рода: «не подан».

Молчаливый пустой список на все три случая — ровно тот дефект, который
`ModelCatalog` уже стоил один раз («пула нет. Пришли: (каталог не подан)» —
оба утверждения ложны).

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ. Он не читает Ревит. Он проецирует УЖЕ прочитанный
L0 — свежий снимок хода либо сохранённый разбор. Живое перечитывание документа
под индекс — отдельная работа с отдельной ценой рейса, и она НАЗВАНА, а не
подразумевается.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Iterator, Mapping

#: Транспортный потолок индекса. Обоснование — в шапке модуля: связывает память
#: ребёнка (256 МБ), а не время разбора. Величина взята у уже существующего
#: потолка результата, чтобы не заводить второго числа того же рода.
CEILING_BYTES: int = 8 * 1024 * 1024

#: Сколько элементов отдаёт один поиск, если автор не назвал своего предела.
#: Это ПОТОЛОК ОТВЕТА, а не индекса: усечение обязано быть объявлено, поэтому
#: `find` всегда возвращает и число найденного целиком (`total`).
DEFAULT_FIND_LIMIT: int = 200

#: Род индекса. Закрытый список: третьего значения нет, и добавить его молча
#: нельзя — `BuildingIndexError` разбирает ровно эти два плюс отсутствие.
TIER_FULL = "full"
TIER_CENSUS = "census"


class BuildingIndexError(RuntimeError):
    """Индекса нет либо он не отвечает на этот вопрос — С ПРИЧИНОЙ.

    Отдельный тип, а не `ValueError`: «здание не поместилось» и «в здании
    такого нет» обязаны быть различимы вызывающим, а не читаться по тексту.
    """


def _mm(triple: Any) -> list[int] | None:
    """Точка в целых миллиметрах. См. довод про округление в шапке модуля."""
    if not triple:
        return None
    try:
        return [int(round(float(v))) for v in triple]
    except (TypeError, ValueError):
        return None


def _row(element: Any) -> dict[str, Any]:
    """Одна строка индекса — «файл» этого репозитория.

    Поля выбраны тем, ЧТО РЕШАЕТ поиск: адрес, категория, уровень, тип,
    геометрия, хозяин. Параметры сюда НЕ входят: замерено, их 2.4–3.6 на
    элемент, но именно они дают разброс веса 320→143 Б. Один элемент со всеми
    параметрами отдаёт `get()`, и это ровно `read file:line` против `grep`.
    """
    # 🔴 ОДНА ВЕЛИЧИНА — ОДНО ПРЕДСТАВЛЕНИЕ. Первая редакция клала в строку
    # `None`, а в перепись `"?"` (ключ JSON обязан быть строкой), и `levels()`
    # отдавал уровень, которого `find(lvl=…)` не мог найти никогда. Тот же
    # именной дефект: величина объявлена в одном месте и прочитана в другом.
    # `"?"` значит «элемент не несёт уровня» — это факт о ЗДАНИИ, а не пробел.
    row: dict[str, Any] = {
        "id": element.element_id,
        "cat": element.category or "?",
        "lvl": element.level_name or "?",
        "type": element.type_name or "?",
    }
    for key, value in (("p0", _mm(element.p0_mm)), ("p1", _mm(element.p1_mm)),
                       ("b0", _mm(element.bbox_min_mm)),
                       ("b1", _mm(element.bbox_max_mm))):
        if value is not None:
            row[key] = value
    if element.host_id:
        row["host"] = element.host_id
    return row


def _params(element: Any) -> dict[str, Any]:
    """Параметры элемента как есть — только для `get()`, поштучно."""
    raw = getattr(element, "params", None)
    return dict(raw) if isinstance(raw, Mapping) else {}


def build_index(elements: Iterable[Any],
                *,
                ceiling_bytes: int = CEILING_BYTES) -> dict[str, Any]:
    """Ограниченный индекс здания из потока элементов L0.

    🔴 ФОРМА ВЫЗОВА — ЧАСТЬ КОНТРАКТА. Сюда идёт поток ЭЛЕМЕНТОВ
    (`L0JSONLReader.iter_elements()`), а не документ и не `metadata()`: шапка
    несёт уровни и оси, а `elements` в ней пуст ПО ПОСТРОЕНИЮ, и скормивший её
    получит «элементов 0» на здании, где их 115 889. Эта ловушка в дереве уже
    названа поимённо и стоила ложного вывода — не повторяем.

    Возвращает словарь, пригодный для кадра stdin. Перепись строится ВСЕГДА:
    она весит килобайты и отвечает на «что тут вообще есть» даже тогда, когда
    поэлементный слой не поместился.
    """
    rows: list[dict[str, Any]] = []
    params: dict[str, dict[str, Any]] = {}
    by_category: dict[str, int] = {}
    by_level: dict[str, int] = {}
    total = 0

    for element in elements:
        total += 1
        row = _row(element)
        rows.append(row)
        detail = _params(element)
        if detail:
            params[row["id"]] = detail
        by_category[row["cat"]] = by_category.get(row["cat"], 0) + 1
        by_level[row["lvl"]] = by_level.get(row["lvl"], 0) + 1

    # 🔴 ПОРЯДОК ЗДЕСЬ НЕ ОБЪЯВЛЯЕТСЯ, И ЭТО ЗАМЕР, А НЕ ЛЕНЬ (15.08.2026).
    # Первая редакция сортировала перепись по убыванию количества — и порядок
    # МОЛЧА терялся: кадр stdin сериализуется с `sort_keys=True` (иначе подпись
    # индекса не воспроизводима), и словарь приезжал к автору по алфавиту.
    # «Топ категорий» отдавал `OST_CableTray: 1` первой строкой на здании, где
    # 695 стен. Величина объявлена в одном месте и переписана в другом — наш
    # именной дефект, совершённый внутри правки против него.
    # Порядок теперь решается ТАМ, ГДЕ ЧИТАЕТСЯ: `BuildingView.top()`.
    census = {
        "total": total,
        "by_category": by_category,
        "by_level": by_level,
    }

    payload: dict[str, Any] = {"tier": TIER_FULL, "census": census,
                               "elements": rows, "params": params}
    size = len(json.dumps(payload, ensure_ascii=False,
                          separators=(",", ":"), default=str).encode("utf-8"))
    if size <= ceiling_bytes:
        payload["bytes"] = size
        return payload

    # ПЕРЕБОР. Усечь список молча нельзя: усечённый индекс выглядит полным, и
    # поиск по нему вернёт «не найдено» там, где элемент есть. Отдаём перепись
    # и НАЗЫВАЕМ, почему поэлементного слоя нет.
    census_only: dict[str, Any] = {
        "tier": TIER_CENSUS,
        "census": census,
        "elements": [],
        "params": {},
        "refused": (
            "здание не поместилось в индекс: %d элементов, %.1f МБ при потолке "
            "%.1f МБ. Приехала перепись — по ней видно, что и на каких уровнях "
            "есть. Поэлементный поиск по этому зданию недоступен, пока область "
            "не сужена."
            % (total, size / 1e6, ceiling_bytes / 1e6)),
    }
    census_only["bytes"] = len(
        json.dumps(census_only, ensure_ascii=False,
                   separators=(",", ":"), default=str).encode("utf-8"))
    return census_only


def observations_of(document: Any, *, building_id: str | None = None
                    ) -> tuple[list[dict], str]:
    """Наблюдения о ПОСТРОЕННОМ здании — готовыми, для кадра.

    Считает их РОДИТЕЛЬ и кладёт в индекс. Довод не в удобстве: у ребёнка
    песочницы `DEFAULT_CPU_SECONDS = 5.0`, а судья здания в пять секунд не
    обязан помещаться, и скрипт, у которого судья съел бюджет, не допишет
    программу. Среда считает — автор читает и ветвится.

    Отказ судьи — ЭТО ДАННЫЕ: он возвращается второй половиной пары, а не
    исключением, иначе «правила молчат» стало бы неотличимо от «правила не
    запускались».
    """
    try:
        from kukai.ir.assembly_view import observe_l0
        view = observe_l0(document, building_id=building_id)
    except Exception as exc:  # noqa: BLE001 — отказ судьи это данные
        return [], "%s: %s" % (type(exc).__name__, exc)
    out: list[dict] = []
    for obs in getattr(view, "observations", ()) or ():
        try:
            out.append(obs.to_dict())
        except Exception:  # noqa: BLE001 — форма наблюдения чужая
            out.append({"code": str(getattr(obs, "code", "?"))})
    silent = getattr(view, "silent_sources", None)
    return out, ("; ".join(f"{k}: {v}" for k, v in silent.items())
                 if isinstance(silent, dict) and silent else "")


def index_from_run(run_dir: str,
                   *,
                   ceiling_bytes: int = CEILING_BYTES,
                   with_observations: bool = False) -> dict[str, Any]:
    """Индекс по СОХРАНЁННОМУ разбору — офлайновый вход, без моста и Ревита.

    Живой вход (перечитать открытый документ под индекс) — ОТДЕЛЬНАЯ работа с
    отдельной ценой рейса; она названа здесь, а не подразумевается.

    🔴 `with_observations` строит ДОКУМЕНТ ЦЕЛИКОМ — шапку плюс элементы.
    `metadata()` в одиночку отдаёт только шапку, и `elements` в ней пуст ПО
    ПОСТРОЕНИЮ: скормивший её судье получит «стен 0» на здании с 695 стенами.
    Ловушка названа в дереве поимённо и стоила ложного вывода.
    """
    import dataclasses
    import os

    from kukai.ir.decompile.extract import L0JSONLReader

    path = os.path.join(run_dir, "L0.jsonl")
    if not os.path.exists(path):
        raise BuildingIndexError(
            "разбор %r не несёт L0.jsonl — индекс строить не из чего. Это факт "
            "о ПРОГОНЕ, а не о здании" % run_dir)
    payload = build_index(L0JSONLReader(path).iter_elements(),
                          ceiling_bytes=ceiling_bytes)
    if with_observations:
        reader = L0JSONLReader(path)
        document = dataclasses.replace(
            reader.metadata(), elements=tuple(reader.iter_elements()))
        observations, silent = observations_of(document)
        payload["observations"] = observations
        if silent:
            payload["observations_silent"] = silent
    return payload


def matches(row: Mapping[str, Any], criteria: Mapping[str, Any]) -> bool:
    """Совпадает ли строка с признаками поиска.

    Правило одно и оно закрытое: строковые признаки (`cat`, `lvl`, `type`)
    сравниваются ПОДСТРОКОЙ без учёта регистра — автор ищет «Стены», не помня
    точного `OST_Walls`; всё остальное сравнивается точно. Регистр снят
    намеренно: `ground.by=name` в этом дереве уже принимает имя без учёта
    регистра, и поиск, строже заземления, отправлял бы автора чинить то, что
    построится.
    """
    for key, want in criteria.items():
        if want is None:
            continue
        got = row.get(key)
        if key in ("cat", "lvl", "type"):
            if got is None:
                return False
            if str(want).casefold() not in str(got).casefold():
                return False
        elif got != want:
            return False
    return True


def iter_matching(rows: Iterable[Mapping[str, Any]],
                  criteria: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    for row in rows:
        if matches(row, criteria):
            yield row


__all__ = [
    "CEILING_BYTES", "DEFAULT_FIND_LIMIT", "TIER_FULL", "TIER_CENSUS",
    "BuildingIndexError", "build_index", "index_from_run", "matches",
    "iter_matching",
]
