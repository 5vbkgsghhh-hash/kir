"""KIR ground stage — selector resolution against a model snapshot (SPEC §5, R4).

The create_element GROUND discipline, generalized: *no ungrounded C# is ever
emitted*. Every Sel<K> resolves to a pinned ElementId here, in ONE pass over a
snapshot (census-style dict; at serving time built from one batched bridge
round-trip — this module never talks to the bridge itself, which keeps it
fully testable with fixtures).

Resolution rules (silent-fallback ban, SPEC §2):
  by=element_id  -> pinned as-is (existence re-checked by the emitted
                    null-guard: model may drift between ground and execute).
  by=name        -> exact match after trim; if none, ONE case-insensitive
                    match is accepted; zero -> NOT_FOUND with the 5 nearest
                    names as candidates; several -> AMBIGUOUS with candidates.
  by=default     -> only where the op declares a deterministic rule:
                      * wall.type: doc default wall type, resolved IN-EMIT via
                        GetDefaultElementTypeId (echoed in the witness readback);
                      * pipe.system_type / pipe.pipe_type: the SOLE snapshot
                        entry; more than one -> AMBIGUOUS (never "first").
                    Every default resolution is echoed in the grounding record.

Snapshot shape: {"levels": [{"id": int, "name": str}, ...],
                 "wall_types": [...], "pipe_types": [...],
                 "piping_system_types": [...]}
"""
from __future__ import annotations

import difflib
import math
from typing import Any, Optional

from kukai.ir import relate, spec
from kukai.ir.diag import Diagnostic, KirRefusal, GROUND_BAD_SELECTOR
from kukai.ir.emit_utils import ELEMENT_ID_MAX

GROUND_NOT_FOUND = "KIR-G101"
GROUND_AMBIGUOUS = "KIR-G102"
GROUND_NO_SNAPSHOT = "KIR-G103"
GROUND_EMPTY_POOL = "KIR-G104"

#: Слово рода ссылки для человекочитаемого отказа.
#: Род ссылки -> (слово, причастие). Причастие отдельно, потому что
#: «фаза не найден» — не опечатка, а сообщение, написанное для
#: английской грамматики в русском продукте.
_REF_WORD = {"materials": ("материал", "найден"),
             "phases": ("фаза", "найдена"),
             "worksets": ("рабочий набор", "найден")}
GROUND_BAD_SNAPSHOT = "KIR-G106"

# Sentinel a grounded op carries when the default is resolved in-emit
# (wall type via GetDefaultElementTypeId) rather than from the snapshot.
IN_EMIT_DEFAULT = "__doc_default__"
_MISSING = object()

#: НАЗВАННОЕ УМОЛЧАНИЕ — пулы, где «тип по умолчанию» берётся из САМОГО
#: документа по объявленному правилу «самый употребимый».
#:
#: Замер 02.08.2026 (kir-bench, T1, Snowdon): плечо C# взяло `.FirstOrDefault()`
#: и построило дверь 1 из 62 МОЛЧА — пользователь получил тип, которого не
#: выбирал, и не узнал об этом. Наше плечо отказало KIR-G102 и оставило
#: НУЛЕВОЙ след. Развилка между этими двумя исходами ложная: у кнопки должен
#: быть вид по умолчанию, и он обязан быть НАЗВАН, а не случаен.
#:
#: Почему правило опирается на документ, а не на Revit: `ElementTypeGroup` НЕ
#: содержит ни `DoorType`, ни `WindowType` — сверено поимённо по RevitAPI.xml
#: 2021 и 2026 (94 члена; WallType/FloorType/RoofType/CeilingType/TextNoteType
#: есть, дверей и окон нет ни в одной версии). Поэтому `create_wall.type`
#: имеет документный дефолт (`IN_EMIT_DEFAULT`), а спросить у Revit «твоя
#: дверь по умолчанию» НЕВОЗМОЖНО ПО ПОСТРОЕНИЮ. Единственное объяснимое
#: правило — то, что сделал бы человек: «ставь такую же, как уже стоит».
#:
#: ГРАНИЦА ЧЛЕНСТВА СТРУКТУРНАЯ, А НЕ ВКУСОВАЯ: пул обязан быть СУЖЕН
#: КАТЕГОРИЕЙ в самом коллекторе снапшота. «В этом проекте так принято»
#: осмысленно только ВНУТРИ рода вещи: у двери есть сложившийся тип двери, у
#: колонны — сложившееся сечение. Пул без сужения сравнивает несравнимое.
#:
#: `family_symbols` СТОЯЛ ЗДЕСЬ И БЫЛ УБРАН 03.08.2026 — это моя же ошибка,
#: пойманная офлайн-репетицией по 63 сохранённым разборам ДО живого Revit
#: (`scratchpad/rehearse_named_default.py`). Он единственный собирается
#: `OfClass(FamilySymbol)` БЕЗ `OfCategory` (см. `open_model.GROUND_SNAPSHOT_CS`),
#: и правило выбирало в нём:
#:
#:   R_0_200Lx50W_-50   10 190 экз., отрыв 1.73x   ← ТИП ИМПОСТА ВИТРАЖА
#:   Standard            8 070 экз., отрыв 4.51x
#:   170x60x5              151 экз., отрыв 2.29x
#:   305x305x97UC            2 экз., второго нет   ← стальной профиль
#:
#: Импост порождается сеткой носителя и `place_family` не ставится вовсе.
#: То есть `place_family` без `symbol` молча получал бы объект, который этой
#: операцией не создаётся, — ХУЖЕ прежнего честного отказа, а не лучше.
#:
#: ПОРОГ ЗДЕСЬ НЕ СПАСАЛ, и это главный вывод: отрывы 2.29x / 3.65x / 4.51x
#: уверенные. Беда не в силе сигнала, а в несопоставимости кандидатов, и лечится
#: она границей пула, а не числом.
#:
#: Список ЗАКРЫТ и держится ДВУМЯ замками (`test_named_default.py`): перечнем
#: имён и проверкой самого правила членства по коллектору. Расширять — осознанное
#: решение с замером, а не побочный эффект: пул, попавший сюда без смысла,
#: превращает отказ в тихую подмену, то есть ровно в тот дефект, ради которого
#: правило написано.
MOST_USED_POOLS = frozenset({
    "door_symbols", "window_symbols",
    "column_symbols_structural", "column_symbols_architectural",
    "foundation_symbols", "beam_types",
})

#: Ключ в строке пула, несущий число РАЗМЕЩЁННЫХ экземпляров этого типа.
INSTANCE_COUNT_KEY = "instances"

#: Во сколько раз лидер обязан опережать следующего, чтобы его можно было
#: НАЗВАТЬ сложившейся практикой проекта.
#:
#: Порог появился из замера по 5 реальным зданиям (03.08.2026, 64 разбора на
#: диске, дедуплицировано по зданию). Без него правило подписывалось бы под
#: утверждениями, которых не выдерживают данные:
#:
#:   здание          род     1-й   2-й  отрыв  доля
#:   snowdon_plumb   двери    25    21   1.2x   17%   ← «практика» из 4 дверей
#:   snowdon_plumb   окна     38    32   1.2x   33%
#:   k2_ar_rd        двери   500   272   1.8x   24%
#:   демо-v3         двери  2698  1219   2.2x   45%
#:   sob62_r23       окна     22     7   3.1x   71%
#:   k2_ar_rd        окна     48     1  48.0x   98%
#:
#: 25 против 21 — это не стандарт проекта, это жребий, и назвать его «самым
#: употребимым» значит продать пользователю уверенность, которой нет.
#:
#: ЧЕСТНО О ПРОИСХОЖДЕНИИ ЧИСЛА. Наблюдения разбиваются на две группы с
#: широким зазором посередине: {1.0, 1.0, 1.2, 1.2} и {1.8, 2.2, 3.1, 48, ∞}.
#: Граница проведена ПО НАИБОЛЬШЕМУ ЗАЗОРУ между наблюдениями (1.2 → 1.8), а
#: не по красивому круглому числу: «вдвое» звучало бы убедительнее, но
#: отсекало бы 500 против 272 в реальном жилом доме, где ДГ 21-8 П —
#: очевидный стандарт проекта. Терять результат ради круглого числа нельзя:
#: пользователю нужен дом, а не отказ.
#:
#: Это всё равно `assigned`-граница в терминах bounds_audit, а не `measured`:
#: девять точек не выводят порог, они лишь показывают, где данные рвутся.
#: Поэтому отрыв ВСЕГДА едет в квитанции — пользователь видит силу сигнала
#: сам и не обязан верить нашему числу. Пересматривать при первом же здании,
#: чей отрыв попадёт в зазор 1.2–1.8.
MOST_USED_MIN_RATIO = 1.5


def _validate_snapshot_pool(snapshot: dict, pool_name: str,
                            diags: list[Diagnostic]) -> list[dict]:
    """Return structurally safe rows for one externally supplied pool.

    The census is a bridge result, not trusted compiler state.  A malformed
    row must become a typed grounding refusal rather than an AttributeError,
    ValueError, or an out-of-range ElementId literal during emission.
    Category-specific extra fields (grid endpoints) are deliberately kept;
    their consumers validate those fields when needed.
    """
    raw = snapshot.get(pool_name)
    if raw is None:
        return []
    if not isinstance(raw, list):
        diags.append(Diagnostic(
            code=GROUND_BAD_SNAPSHOT, field_name=pool_name,
            expected="список строк {id, name}", got=type(raw).__name__,
            message_ru=f"снапшот: пул {pool_name} должен быть списком"))
        return []
    rows: list[dict] = []
    seen_ids: set[int] = set()
    for index, row in enumerate(raw):
        field = f"{pool_name}[{index}]"
        if not isinstance(row, dict):
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=field,
                expected="{id, name}", got=type(row).__name__,
                message_ru=f"снапшот: {field} должен быть объектом"))
            continue
        element_id, name = row.get("id"), row.get("name")
        if (isinstance(element_id, bool) or not isinstance(element_id, int)
                or not (1 <= element_id <= ELEMENT_ID_MAX)):
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=f"{field}.id",
                expected=f"целое 1..{ELEMENT_ID_MAX}", got=element_id,
                message_ru=f"снапшот: {field}.id — положительный 64-битный ElementId"))
            continue
        if not isinstance(name, str):
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=f"{field}.name",
                expected="строка", got=type(name).__name__,
                message_ru=f"снапшот: {field}.name должен быть строкой"))
            continue
        if pool_name == "family_symbols":
            family_fields = ("category", "family_name", "type_name")
            # Legacy name/element-id selectors remain valid against old
            # snapshots. Once any v1.1 identity field is present, however,
            # the triple is inseparable and must be fully well-formed.
            bad_family_field = next((
                key for key in family_fields
                if any(candidate in row for candidate in family_fields)
                and (not isinstance(row.get(key), str)
                     or not row[key].strip())
            ), None)
            if bad_family_field is not None:
                diags.append(Diagnostic(
                    code=GROUND_BAD_SNAPSHOT,
                    field_name=f"{field}.{bad_family_field}",
                    expected="непустая строка",
                    got=row.get(bad_family_field),
                    message_ru=(f"снапшот: {field}.{bad_family_field} "
                                "обязателен для family selector")))
                continue
        params = row.get("params")
        if params is not None and (
                not isinstance(params, dict)
                or not all(isinstance(key, str) for key in params)):
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=f"{field}.params",
                expected="объект {имя параметра: значение}",
                got=type(params).__name__,
                message_ru=(f"снапшот: {field}.params должен быть объектом "
                            "со строковыми именами параметров")))
            continue
        if element_id in seen_ids:
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=f"{field}.id", got=element_id,
                message_ru=f"снапшот: ElementId {element_id} повторяется в пуле {pool_name}"))
            continue
        seen_ids.add(element_id)
        rows.append(row)
    return rows


def _nearest(name: str, pool: list[dict]) -> list[str]:
    names = [str(p.get("name", "")) for p in pool]
    return difflib.get_close_matches(name, names, n=5, cutoff=0.0)


def _disambiguator(sel: dict, op_index: int, op_id: str, param: str,
                   diags: list[Diagnostic]) -> Optional[dict]:
    """Return a normalized disambiguator, or None.

    ``None`` means either "not requested" or "malformed and diagnosed".  The
    latter is safe because the caller sees the appended typed diagnostic and
    the ground stage refuses the complete program.
    """
    raw = sel.get("disambiguate_by")
    if raw is None:
        return None
    if sel.get("by") not in ("name", "default"):
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
            field_name=f"{param}.disambiguate_by", got=raw,
            message_ru="disambiguate_by допустим только для name/default"))
        return None
    if not isinstance(raw, dict) or set(raw) != {"param", "value"}:
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
            field_name=f"{param}.disambiguate_by",
            expected={"param": "непустое имя", "value": "скаляр"}, got=raw,
            message_ru="disambiguate_by — объект {param, value}"))
        return None
    pname, value = raw.get("param"), raw.get("value")
    scalar = (value is None or isinstance(value, (str, bool, int, float)))
    if (not isinstance(pname, str) or not pname.strip() or not scalar
            or (isinstance(value, float) and not math.isfinite(value))):
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
            field_name=f"{param}.disambiguate_by",
            expected={"param": "непустое имя", "value": "JSON-скаляр"}, got=raw,
            message_ru="disambiguate_by требует имя параметра и конечное скалярное значение"))
        return None
    return {"param": pname.strip(), "value": value}


def _parameter_equals(actual: Any, expected: Any) -> bool:
    """Exact, non-coercive equality for externally supplied parameter data."""
    if isinstance(actual, dict):
        # The bridge may preserve both a typed/raw value and Revit's display
        # string for unit-bearing parameters.  Either representation must
        # still match exactly; no locale parsing or unit guessing happens here.
        return any(_parameter_equals(actual[key], expected)
                   for key in ("value", "raw", "display") if key in actual)
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if (isinstance(actual, (int, float))
            and isinstance(expected, (int, float))):
        return (not isinstance(actual, bool) and not isinstance(expected, bool)
                and math.isfinite(float(actual))
                and math.isfinite(float(expected))
                and actual == expected)
    return type(actual) is type(expected) and actual == expected


def _narrow_by_parameter(pool: list[dict], disambiguate_by: Optional[dict]) -> list[dict]:
    # An explicit predicate is a constraint, not merely a tie-breaker.  It
    # must therefore be checked even when the name/default stage happened to
    # leave one row; otherwise a caller asking for Diameter=100 could silently
    # receive the sole Diameter=200 type.
    if disambiguate_by is None:
        return pool
    pname, expected = disambiguate_by["param"], disambiguate_by["value"]
    narrowed = []
    for row in pool:
        params = row.get("params")
        actual = params.get(pname, _MISSING) if isinstance(params, dict) else _MISSING
        if actual is not _MISSING and _parameter_equals(actual, expected):
            narrowed.append(row)
    return narrowed


def _instance_count(row: dict) -> Optional[int]:
    """Число размещённых экземпляров, или None если строка его не несёт.

    `bool` отсекается намеренно: в Python `True == 1`, и счётчик, пришедший
    булевым, означает поломанный сборщик, а не «один экземпляр»."""
    value = row.get(INSTANCE_COUNT_KEY)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _most_used(pool: list[dict], pool_name: str,
               disambiguate_by: Optional[dict]) -> Optional[dict]:
    """Названное умолчание: самый употребимый тип в ЭТОМ документе.

    Возвращает None (правило неприменимо — вызывающий продолжает прежним
    путём, вплоть до отказа) в каждом из случаев, где выбор перестал бы быть
    объяснимым:

    * пул не объявлен в `MOST_USED_POOLS`;
    * хотя бы одна строка пула без счётчика — максимум по неполным данным
      это утверждение, которого мы не можем доказать (старый мост, не
      присылающий счётчиков, обязан сохранить прежнее поведение побайтово);
    * ни одного размещённого экземпляра — правилу не на что опереться;
    * НИЧЬЯ на максимуме — равенство значит, что в проекте нет сложившейся
      практики, и выбор действительно произволен. Строгость тут дёшева, и мы
      её не сдаём: отказ с кандидатами честнее монетки;
    * СЛАБЫЙ ОТРЫВ от следующего (< ``MOST_USED_MIN_RATIO``) — «самый
      употребимый» при 25 против 21 продаёт уверенность, которой нет.
    """
    if pool_name not in MOST_USED_POOLS or not pool:
        return None
    counts = [_instance_count(row) for row in pool]
    if any(count is None for count in counts):
        return None
    top = max(counts)
    if top <= 0:
        return None
    winners = [row for row, count in zip(pool, counts) if count == top]
    if len(winners) != 1:
        return None
    # Отрыв считается от ЛУЧШЕГО ИЗ ОСТАЛЬНЫХ, а не от второй строки пула:
    # порядок строк — дело коллектора, и опираться на него значило бы вернуть
    # `.FirstOrDefault()` через заднюю дверь.
    runner_up = max((count for count in counts if count != top), default=0)
    if runner_up and top < runner_up * MOST_USED_MIN_RATIO:
        return None
    row = winners[0]
    return {
        "id": int(row["id"]),
        "name": str(row.get("name")),
        "via": ("most_used+disambiguate_by"
                if disambiguate_by is not None else "most_used"),
        # Правило обязано быть не только применено, но и ПРЕДЪЯВЛЕНО: без
        # этих чисел выбор неотличим от `.FirstOrDefault()` в костюме.
        # `runner_up` едет всегда — порог назначенный, и пользователь должен
        # видеть силу сигнала, а не верить нашей двойке на слово.
        "rule_detail": {"instances": top, "candidates": len(pool),
                        "runner_up": runner_up},
        **({"disambiguate_by": disambiguate_by}
           if disambiguate_by is not None else {}),
    }


#: Сколько кандидатов едет в отказе. Пять — сознательный размер: отказ
#: платится токенами каждого хода, а список, который нельзя прочесть глазом,
#: не помогает выбрать.
_CANDIDATES_SHOWN = 5


def _candidate_rows(pool: list[dict]) -> list[dict]:
    rows = []
    for item in pool[:_CANDIDATES_SHOWN]:
        row = {"id": int(item["id"]), "name": str(item.get("name"))}
        for key in ("category", "family_name", "type_name"):
            if isinstance(item.get(key), str):
                row[key] = item[key]
        rows.append(row)
    return rows


def _shown_of(pool: list[dict], pool_name: str) -> str:
    """«Показаны 5 из 185, весь список — query_types(...)» либо ПУСТО.

    ЗАЧЕМ ЭТО СУЩЕСТВУЕТ (замер 12.08.2026). Отказ везёт пять кандидатов и
    предлагает «уточни через element_id из candidates». Пул при этом бывает
    сильно больше пяти: по 69 сохранённым профилям корпуса **43.6% всех
    наблюдений пула — больше пяти**, а `family_symbols` и `levels` превышают
    пятёрку в 69 профилях из 69 (максимумы 741 и 122; `wall_types` — 185 при
    59 профилях из 69). До этой строки модель не могла отличить «пять из
    пяти» от «пять из семисот сорока одного» и выбирала тип из усечённого
    множества, считая его полным.

    СРЕЗ ИДЁТ ПО ПОРЯДКУ ПРИБЫТИЯ (пул отсортирован по ElementId, то есть по
    порядку создания в документе) — по величине, не связанной с вопросом. Там,
    где имя ЕСТЬ, рядом в этом же файле уже стоит правильная идиома —
    `_nearest()` режет по РЕЛЕВАНТНОСТИ (`difflib`). Здесь имени нет по
    построению (ветка `by=default`), поэтому релевантность взять неоткуда, и
    честный ход один: НАЗВАТЬ ОСТАТОК И ДАТЬ СПОСОБ ЕГО ПРОЧЕСТЬ. Число
    говорит, сколько ты не видишь; следующий ход говорит, что делать.

    Пул, помещающийся целиком, не платит ни символа: приписка появляется
    только когда есть чему не влезть.
    """
    total = len(pool)
    if total <= _CANDIDATES_SHOWN:
        return ""
    return (f" ПОКАЗАНЫ {_CANDIDATES_SHOWN} ИЗ {total} — остальные не видны; "
            f"весь список: query_types(pool=\"{pool_name}\")")


def _producers_of(kind_value: str) -> list[str]:
    """Опы, ПОРОЖДАЮЩИЕ ссылку этого рода. Спрашиваем реестр, не список."""
    return sorted(
        name for name, op in spec.OPS.items()
        if op.result.reference_kind is not None
        and op.result.reference_kind.value == kind_value)


def _empty_pool_next_move(op_name: str, param: str) -> str:
    """Следующий ход при ПУСТОМ пуле — и только ВЫПОЛНИМЫЙ.

    ПОЧЕМУ ЭТО НЕ ОДНА ФРАЗА НА ВСЕХ. Отказ, называющий невыполнимый ход, хуже
    отказа, не называющего никакого: он выглядит помощью и стоит раунда,
    который не мог удаться. Замер 13.08 на настоящем здании: из 22 пустых пулов
    ход выполним у **двух** (`create_column.symbol`, `create_foundation.symbol`
    — оба принимают `family_symbol`, который язык умеет породить), и НЕ выполним
    у двадцати: их параметры не принимают ссылку вовсе, а язык порождает всего
    четыре рода (`element`, `family_symbol`, `level`, `wall`).

    Различает не мой список, а РЕЕСТР: пересекается ли `ref_kinds` параметра с
    родами, у которых есть производитель. Заведут производителя завтра — фраза
    сменится сама.
    """
    op = spec.OPS.get(op_name)
    pspec = next((p for p in op.params if p.name == param), None) if op else None
    for kind in (pspec.ref_kinds if pspec else ()):
        producers = _producers_of(kind.value)
        if producers:
            how = " или ".join(f"`{name}`" for name in producers)
            return (f"Создай его В ЭТОЙ ЖЕ программе: поставь {how} выше, затем "
                    f"{param}: {{\"by\": \"ref\", \"value\": \"<id того опа>\"}}. "
                    f"Снимок переснимать не нужно — ссылка разрешается внутри "
                    f"программы")
    return ("Ни одна операция KIR не создаёт этот род, поэтому в программе "
            "сделать нечего: тип обязан появиться в документе иначе (шаблон "
            "проекта или загрузка семейства пользователем), и только после "
            "этого — НОВОЕ чтение модели")


def _resolve_one(sel: Any, pool_name: str, pool: list[dict], op_index: int,
                 op_id: str, param: str, op_name: str,
                 diags: list, truncated: bool = False) -> Optional[dict]:
    """Returns {"id": int, "name": str, "via": ...} or None (diag appended).

    ``truncated`` (audit F7): the snapshot pool was capped by the collector and
    the model holds MORE rows than were sent.  A by=name/exact match inside the
    slice is still accepted (id-ordered slice; the residual same-name-twin risk
    is documented), but a not-found says so, and default/sole-entry resolution
    is refused outright — "the sole visible entry" proves nothing about an
    invisible remainder.
    """
    if not isinstance(sel, dict) or sel.get("by") not in (
            "name", "element_id", "default", "family_type"):
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id, field_name=param,
            expected={"by": "name|element_id|default|family_type"}, got=sel,
            message_ru=f"{param} — селектор {{by, value}}"))
        return None
    by = sel["by"]
    if by == "family_type":
        expected_fields = {"by", "category", "family_name", "type_name"}
        if set(sel) != expected_fields or any(
                not isinstance(sel.get(key), str) or not sel[key].strip()
                for key in ("category", "family_name", "type_name")):
            diags.append(Diagnostic(
                code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
                field_name=param,
                expected={
                    "by": "family_type", "category": "OST_...",
                    "family_name": "...", "type_name": "...",
                },
                got=sel,
                message_ru=(f"{param}: family_type требует category+family_name+"
                            "type_name")))
            return None
        want = {
            key: sel[key].strip()
            for key in ("category", "family_name", "type_name")
        }
        exact = [
            row for row in pool
            if all(row.get(key) == value for key, value in want.items())
        ]
        if len(exact) == 1:
            return {
                "id": int(exact[0]["id"]),
                "name": str(exact[0]["name"]),
                "via": "family_type",
                **want,
            }
        diags.append(Diagnostic(
            code=(GROUND_NOT_FOUND if not exact else GROUND_AMBIGUOUS),
            op_index=op_index,
            op_id=op_id,
            field_name=param,
            got=want,
            candidates=_candidate_rows(exact if exact else pool),
            message_ru=(
                f"{pool_name}: family selector не найден"
                if not exact else
                f"{pool_name}: family selector неоднозначен — "
                f"{len(exact)} совпадений"),
        ))
        return None
    disambiguate_by = _disambiguator(sel, op_index, op_id, param, diags)
    if "disambiguate_by" in sel and disambiguate_by is None:
        return None
    if by == "element_id":
        val = sel.get("value")
        if (isinstance(val, bool) or not isinstance(val, int)
                or not (1 <= val <= ELEMENT_ID_MAX)):
            diags.append(Diagnostic(
                code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
                field_name=f"{param}.value",
                expected=f"целое 1..{ELEMENT_ID_MAX}", got=val,
                message_ru="element_id — положительное 64-битное целое"))
            return None
        return {"id": val, "name": None, "via": "element_id"}
    if by == "name":
        val = sel.get("value")
        if not isinstance(val, str) or not val.strip():
            diags.append(Diagnostic(
                code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
                field_name=f"{param}.value", expected="непустая строка", got=val,
                message_ru="имя — непустая строка"))
            return None
        want = val.strip()
        exact = [p for p in pool if str(p.get("name", "")).strip() == want]
        if not exact:
            ci = [p for p in pool
                  if str(p.get("name", "")).strip().lower() == want.lower()]
            # One case-insensitive match may resolve, several are AMBIGUOUS.
            # Keeping ``exact=[]`` for the latter used to misreport a real
            # ambiguity as NOT_FOUND (F31).
            exact = ci
        initial_matches = exact
        exact = _narrow_by_parameter(exact, disambiguate_by)
        if len(exact) == 1:
            return {"id": int(exact[0]["id"]), "name": str(exact[0]["name"]),
                    "via": ("name+disambiguate_by"
                            if disambiguate_by is not None else "name"),
                    **({"disambiguate_by": disambiguate_by}
                       if disambiguate_by is not None else {})}
        if not initial_matches:
            trunc_note = ("; снапшот-пул обрезан коллектором — тип может "
                          "существовать за пределами среза, используйте "
                          "element_id" if truncated else "")
            diags.append(Diagnostic(
                code=GROUND_NOT_FOUND, op_index=op_index, op_id=op_id,
                field_name=param, got=want, candidates=_nearest(want, pool),
                message_ru=f"{pool_name}: «{want}» не найден" + trunc_note))
        else:
            # KIR-G102 disambiguation path (2026-07-17): several pool entries
            # share `want` verbatim (e.g. several duct/cable-tray types named
            # "По умолчанию" — routine in real projects, see fix report).
            # Surface each candidate's element_id alongside its name so the
            # caller's NEXT program can re-select deterministically via
            # {"by": "element_id", "value": <id>} instead of retrying the
            # same ambiguous name. The ids were already sitting in `pool`
            # (same dicts _resolve_one reads `id`/`name` off of two branches
            # above) — only the AMBIGUOUS diagnostic used to throw them away.
            diags.append(Diagnostic(
                code=GROUND_AMBIGUOUS, op_index=op_index, op_id=op_id,
                field_name=param,
                got=({"name": want, "disambiguate_by": disambiguate_by}
                     if disambiguate_by is not None else want),
                candidates=_candidate_rows(
                    exact if exact or disambiguate_by is None
                    else initial_matches),
                message_ru=(
                    f"{pool_name}: «{want}» неоднозначен — после "
                    f"disambiguate_by осталось {len(exact)} совпадений"
                    if disambiguate_by is not None else
                    f"{pool_name}: «{want}» неоднозначен — "
                    f"{len(exact)} совпадений; уточни через "
                    f"{{\"by\": \"element_id\", \"value\": <id из candidates>}}"
                    + _shown_of(exact, pool_name))))
        return None
    # by == "default"
    if (op_name == "create_wall" and param == "type"
            and disambiguate_by is None):
        return {"id": None, "name": None, "via": "doc_default",
                "in_emit": IN_EMIT_DEFAULT}
    initial_pool = pool
    if truncated and initial_pool:
        # A truncated pool cannot prove sole-entry-ness (audit F7): the sole
        # VISIBLE row may have invisible siblings beyond the cap.
        diags.append(Diagnostic(
            code=GROUND_AMBIGUOUS, op_index=op_index, op_id=op_id,
            field_name=param, candidates=_candidate_rows(initial_pool),
            message_ru=(f"{pool_name}: снапшот-пул обрезан коллектором — "
                        "default/sole-entry невозможен, укажите element_id"
                        + _shown_of(initial_pool, pool_name))))
        return None
    pool = _narrow_by_parameter(pool, disambiguate_by)
    if len(pool) == 1:
        return {"id": int(pool[0]["id"]), "name": str(pool[0].get("name")),
                "via": ("sole_entry+disambiguate_by"
                        if disambiguate_by is not None else "sole_entry"),
                **({"disambiguate_by": disambiguate_by}
                   if disambiguate_by is not None else {})}
    # НАЗВАННОЕ УМОЛЧАНИЕ — строго между «единственный в пуле» и отказом.
    # Порядок неслучаен: sole_entry сильнее (один кандидат не нуждается в
    # правиле выбора), а отказ обязан остаться там, где правило промолчало.
    named = _most_used(pool, pool_name, disambiguate_by)
    if named is not None:
        return named
    code = GROUND_EMPTY_POOL if not initial_pool else GROUND_AMBIGUOUS
    # Same id-surfacing fix as the by=name AMBIGUOUS branch above, for the
    # by=default path (omitted param, several pool entries -> AMBIGUOUS never
    # "first"): EMPTY_POOL has no candidates by construction (pool is empty),
    # AMBIGUOUS gets {id, name} pairs so the caller can re-issue with an
    # explicit element_id selector instead of retrying default.
    diags.append(Diagnostic(
        code=code, op_index=op_index, op_id=op_id, field_name=param,
        got=({"disambiguate_by": disambiguate_by}
             if disambiguate_by is not None else None),
        candidates=_candidate_rows(
            pool if pool or disambiguate_by is None else initial_pool),
        message_ru=(
            f"{pool_name}: пусто в модели. {_empty_pool_next_move(op_name, param)}"
            if not initial_pool else
            f"{pool_name}: после disambiguate_by осталось {len(pool)} вариантов"
            + _shown_of(pool, pool_name)
            if disambiguate_by is not None else
            # ЧИСЛА ЗДЕСЬ НЕ БЫЛО ВОВСЕ — ветка говорила «несколько вариантов»
            # и предлагала выбрать из candidates, не назвав ни сколько их, ни
            # что показаны не все. Это худший из трёх случаев в этом файле:
            # усечение без величины и без имени остатка.
            f"{pool_name}: {len(pool)} вариантов — default невозможен, "
            f"уточните через "
            f"{{\"by\": \"element_id\", \"value\": <id из candidates>}}"
            + _shown_of(pool, pool_name))))
    return None


#: Правила, где выбор сделал КОМПИЛЯТОР, а не автор программы. Всё остальное
#: (`name`, `element_id`, `family_type`, `ref`) — эхо сказанного, и отчитываться
#: там не о чем. Пара «+disambiguate_by» остаётся выбором компилятора: сужение
#: ограничивает пул, но последний шаг всё равно делает правило.
_COMPILER_CHOICE_RULES = frozenset({
    "most_used", "most_used+disambiguate_by",
    "sole_entry", "sole_entry+disambiguate_by",
    "doc_default",
})

#: Кто отвечает на вопрос «какой тип», когда компилятор передал его документу.
#: Это НЕ «мы не знаем», а «знает Revit, и знает он это только в момент
#: постройки»: `doc.GetDefaultElementTypeId(ElementTypeGroup.*)` спрашивают у
#: открытого документа внутри транзакции (см. `IN_EMIT_DEFAULT` и, например,
#: `authoring._emit_wall`).
DEFERRED_TO_REVIT = "revit"

#: Ключ, под которым эмиссия кладёт ИМЯ ТИПА построенного элемента в квитанцию
#: исполнения. Один на все опы с документным умолчанием — замер 10.08.2026 по
#: эмиссии всех восьми таких опов; замок держит `test_choice_showcase.
#: test_every_document_default_op_reads_its_type_name_back`, потому что
#: указатель на несуществующее поле хуже отсутствия указателя.
RUNTIME_TYPE_NAME_KEY = "type_name"


#: Единственный параметр, чьё отложенное имя эмиссия читает обратно. Сегодня
#: `IN_EMIT_DEFAULT` ставится ТОЛЬКО на `type` (обе площадки в `ground()`), и
#: указатель верен ровно поэтому. Если документное умолчание когда-нибудь
#: заведут на другом параметре, строка честно останется без адреса, а не
#: пошлёт читателя в поле `type_name`, которое к нему не относится.
_DEFERRED_PARAM_WITH_READBACK = "type"


def _deferred_chosen(op_id: Any, param: Any) -> dict:
    """Строка выбора, который компилятор ОТЛОЖИЛ документу.

    ПОЧЕМУ ЭТО НЕ «ЗАПОЛНИТЬ ПУСТОЕ ПОЛЕ». Живой ход 10.08.2026 (модель
    оператора, Revit 2023, стена без `type`) прошёл зелёным насквозь и вернул
    `chosen: {"id": null, "name": null}`, тогда как построенная стена получила
    вполне конкретный «111_Кирпич 380». Имени на стадии заземления НЕ
    СУЩЕСТВУЕТ — и это не наш недосмотр, а устройство правила: тип выбирает сам
    документ уже внутри эмиссии. Придумать имя было бы худшим из ответов
    (выдуманное имя типа хуже пустого), убрать строку — вторым худшим (молчание
    о сделанном выборе и есть исходный дефект).

    Поэтому строка меняет не содержимое, а СМЫСЛ: пустая пара «id/name»
    читается как «выбор не сделан», а `resolved_at` + `read_from` говорят
    ровно то, что верно, — выбор сделан, сделал его документ, имя появится в
    квитанции исполнения вот по этому адресу. После исполнения имя туда и
    доезжает (`attach_runtime_choices`), так что указатель живёт недолго и
    нужен там, где исполнения ещё (или уже) не было: сухая компиляция, отказ
    до эффекта, разбор программы без Revit.
    """
    chosen = {"id": None, "name": None, "resolved_at": DEFERRED_TO_REVIT}
    if param == _DEFERRED_PARAM_WITH_READBACK:
        chosen["read_from"] = f"result.{op_id}.{RUNTIME_TYPE_NAME_KEY}"
    return chosen


def attach_runtime_choices(report: list[dict], payload: Any) -> list[dict]:
    """Дописать в квитанцию имена, которые знал только Revit.

    Из двух честных ответов на отложенный выбор — «скажи, где прочесть» и
    «прочти и скажи» — взяты ОБА, и порядок неслучаен. Указатель обязателен:
    он верен всегда, в том числе когда исполнения не было. Но останавливаться
    на нём нельзя, и причина не в удобстве: ответ УЖЕ ЛЕЖИТ В ТОМ ЖЕ JSON, а
    эмиттер, который тип применил, он же его и прочитал обратно с
    `GetTypeId()` построенного элемента. Оставить соединение читателю значило
    бы отдать модели работу, которую мы можем сделать один раз и точно, — и
    оставить её в состоянии «правило названо, результат неизвестен», то есть
    ровно там, откуда механизм начинался.

    Это ЗАМЕР, а не заполнение правдоподобным: имя берётся из построенного
    элемента и ниоткуда больше. Нет строки в квитанции, нет поля, пустая
    строка — выбор остаётся неразрешённым, а указатель на месте. Провенанс
    называется (`source: readback`), потому что имя из снапшота и имя из
    построенного элемента — разные факты, и склеивать их молча нельзя.

    Возвращает НОВЫЙ список: `CompileOutput` живёт дольше хода и попадает в
    кэш компиляции, а квитанция — не черновик.
    """
    if not report:
        return report
    filled: list[dict] = []
    for row in report:
        chosen = row.get("chosen") if isinstance(row, dict) else None
        if (not isinstance(chosen, dict)
                or chosen.get("resolved_at") != DEFERRED_TO_REVIT
                or chosen.get("name") is not None
                # Без адреса читать неоткуда: строка без `read_from` — это
                # честное «мы не знаем, где это лежит», и угадывать поле здесь
                # значило бы вернуть догадку под видом замера.
                or not chosen.get("read_from")):
            filled.append(row)
            continue
        readback = (payload.get(row.get("op_id"))
                    if isinstance(payload, dict) else None)
        name = (readback.get(RUNTIME_TYPE_NAME_KEY)
                if isinstance(readback, dict) else None)
        if not isinstance(name, str) or not name.strip():
            filled.append(row)
            continue
        filled.append({**row, "chosen": {**chosen, "name": name.strip(),
                                         "source": "readback"}})
    return filled


def compiler_choices(grounded_ops: list[dict]) -> list[dict]:
    """Квитанция: что выбрал компилятор там, где автор промолчал.

    Отдельная функция, а не побочный продукт заземления, по той же причине,
    по которой существует сам отчёт: выбор, который некому предъявить, — это
    `.FirstOrDefault()` с лучшей репутацией. Порядок сохраняется программным,
    чтобы квитанция читалась сверху вниз как сама программа.
    """
    report: list[dict] = []
    for op in grounded_ops:
        if not isinstance(op, dict):
            continue
        # RELATE: адрес — это НЕ умолчание (автор сказал «А/3» вслух), но
        # ВЫВОД компилятора из сказанного, и предъявлять его надо по той же
        # причине. Отдельные правила `at_grid`/`at_element`, а не подмешивание
        # в `_COMPILER_CHOICE_RULES`: смешать «я выбрал за тебя» и «я вывел из
        # твоих слов» значило бы соврать про происхождение обоих.
        for row in op.get("__address__") or ():
            report.append({
                "op_id": op.get("id"), "op": op.get("op"),
                "param": row.get("param"),
                "rule": "at_element" if row.get("element") else "at_grid",
                "chosen": {"point_mm": row.get("point_mm")},
                "rule_detail": {"lines": row.get("lines"),
                                "angle_deg": row.get("angle_deg"),
                                "element": row.get("element")},
            })
        for param, sel in op.items():
            if not isinstance(sel, dict):
                continue
            res = sel.get("__grounded__")
            if not isinstance(res, dict):
                continue
            via = res.get("via")
            if via not in _COMPILER_CHOICE_RULES:
                continue
            # Форма строки решается МЕТКОЙ ЭМИССИИ, а не именем правила:
            # `in_emit` — то самое, что заставляет эмиттер спросить документ,
            # и привязка к нему не даёт витрине разъехаться с эмиссией, если
            # правило когда-нибудь переименуют или заведут второе такое же.
            chosen = (_deferred_chosen(op.get("id"), param)
                      if res.get("in_emit") == IN_EMIT_DEFAULT
                      else {"id": res.get("id"), "name": res.get("name")})
            row = {
                "op_id": op.get("id"),
                "op": op.get("op"),
                "param": param,
                "rule": via,
                "chosen": chosen,
            }
            if isinstance(res.get("rule_detail"), dict):
                row["rule_detail"] = res["rule_detail"]
            report.append(row)
    return report


#: Как правило называется по-русски, когда его предъявляют пользователю.
#: Пользователь не читает `via`, и «most_used» в ответе — это машинный код,
#: выданный за объяснение.
_RULE_NAMES_RU = {
    "most_used": "самый употребимый в модели",
    "most_used+disambiguate_by": "самый употребимый после сужения",
    "sole_entry": "единственный в модели",
    "sole_entry+disambiguate_by": "единственный после сужения",
    "doc_default": "тип по умолчанию документа",
}


def describe_choices_ru(report: list[dict]) -> str:
    """Одна строка на человеческом: что выбрал компилятор и по какому правилу.

    Пустая строка, если выбирать было не из чего, — примечание, сообщающее
    «ничего не произошло», это шум, а шум учит не читать примечания.
    """
    parts: list[str] = []
    addresses: list[str] = []
    for row in report:
        if row.get("rule") in ("at_grid", "at_element"):
            # Квитанция адреса печатается ВСЕГДА: она отвечает на вопрос
            # «что компилятор вывел из «А/3»», а не «чем он заполнил
            # молчание». Без неё выбор оси неотличим от угадывания.
            detail = row.get("rule_detail") or {}
            addresses.extend(relate.describe_receipt_ru([{
                "op_id": row.get("op_id"), "param": row.get("param"),
                "point_mm": (row.get("chosen") or {}).get("point_mm"),
                "lines": detail.get("lines") or (),
                "element": detail.get("element"),
            }]))
            continue
        rule = _RULE_NAMES_RU.get(row.get("rule", ""), row.get("rule", ""))
        chosen = row.get("chosen") or {}
        name = chosen.get("name")
        detail = row.get("rule_detail") or {}
        if chosen.get("resolved_at") == DEFERRED_TO_REVIT:
            # ОТЛОЖЕННЫЙ ВЫБОР ПЕЧАТАЕТСЯ ВСЕГДА, И ЭТО ПОПРАВКА 10.08.2026.
            # Раньше строка выпадала здесь же, где `sole_entry`, по одному и
            # тому же условию «нет кандидатов», — и живой ход вернул пустое
            # примечание при построенной стене «111_Кирпич 380». Условие было
            # верным для `sole_entry` (кандидат один, выбирать не из чего) и
            # неверным для документного умолчания: типов стен у настоящего
            # проекта десятки, выбор среди них СДЕЛАН — просто не нами, и
            # именно поэтому его надо назвать вслух.
            parts.append(
                f"{row.get('param')}: «{name}» ({rule}, прочитано в "
                f"построенном элементе)"
                if name else
                f"{row.get('param')}: выбирает документ ({rule}); имя типа "
                f"известно только после постройки"
                + (f" — {chosen['read_from']}" if chosen.get("read_from")
                   else ""))
            continue
        # «Единственный в модели» не нуждается в защите: выбора там не было.
        # Предъявлять надо там, где кандидатов много — именно этот случай
        # неотличим от `.FirstOrDefault()` без объяснения.
        if not detail.get("candidates"):
            continue
        runner_up = detail.get("runner_up")
        # Отрыв показывается всегда, когда есть с чем сравнивать: порог у нас
        # назначенный, и пользователь должен мерить силу сигнала сам.
        gap = (f", следующий {runner_up}" if runner_up else "")
        parts.append(
            f"{row.get('param')}: «{name}» "
            f"({rule}: {detail.get('instances')} экз. "
            f"из {detail.get('candidates')} кандидатов{gap})")
    lines: list[str] = []
    if addresses:
        lines.append("адрес — " + "; ".join(addresses))
    if parts:
        lines.append("выбрано по умолчанию — " + "; ".join(parts))
    return "\n".join(lines)


def _ground_members(members: list, snapshot: Any, gid: str,
                    diags: list[Diagnostic], *, group_index: int) -> list:
    """Plan, then ground every group member through the ordinary pipeline.

    A legacy pre-grounded marker is decoded by the member planner into an
    explicit selector and validated; it is never accepted as executable shape
    merely because a component bridge supplied it.  The repeat validation here
    is an intentional defence at the legacy ``ground(list[dict])`` boundary:
    production ``ground_program`` already owns a typed parent, while direct
    callers must not regain the historical member bypass.
    """
    from kukai.ir.compiler import _plan_group_members

    try:
        member_plans = _plan_group_members(
            members, group_id=gid, group_index=group_index)
    except KirRefusal as refusal:
        diags.extend(refusal.diagnostics)
        return members
    raw = [item.to_dict() for item in member_plans]
    try:
        return ground(raw, snapshot)
    except KirRefusal as refusal:
        for d in refusal.diagnostics:
            member_id = d.op_id
            d.op_id = gid
            d.op_index = group_index
            d.field_name = (f"members[{member_id or '?'}]"
                            f"{'.' + d.field_name if d.field_name else ''}")
        diags.extend(refusal.diagnostics)
        return members


def ground(normed_ops: list[dict], snapshot: Any) -> list[dict]:
    """Grounded copy of ops: every grounded param becomes
    {"__grounded__": {"id": ..., "name": ..., "via": ...}}. Raises KirRefusal
    with ALL resolution failures at once (one round of typed feedback beats
    a drip of single errors — SPEC 12.7 economy)."""
    if not any(spec.OPS[op["op"]].family in spec.WRITE_FAMILIES for op in normed_ops):
        return normed_ops
    # snapshot is needed only when something must resolve FROM it: by-name /
    # by-default selectors or omitted-with-pool-default params. Pure
    # element_id/ref programs ground without one.
    def _needs_pool(op, ospec):
        for param, _pool, required in ospec.grounded:
            sel = op.get(param)
            if sel is None:
                # wave/struct: mirrors the same variety-discriminated skip as
                # the main resolution loop below — an irrelevant omitted
                # param (symbol when variety!=isolated, type when
                # variety!=slab) must not force a snapshot requirement either.
                if ospec.name == "create_foundation" and (
                        (param == "symbol" and op.get("variety") != "isolated") or
                        (param == "type" and op.get("variety") != "slab")):
                    continue
                if (ospec.name == "create_railing" and param == "level"
                        and op.get("variety") != "path"):
                    # wave/arch: тот же зеркальный пропуск, что и в основном
                    # цикле разрешения ниже — нерелевантный пропущенный
                    # параметр не должен ТРЕБОВАТЬ снапшот.
                    continue
                if (ospec.name == "create_area_reinforcement"
                        and param == "hook_type"):
                    # wave/reinforcement: зеркало пропуска из основного цикла
                    # разрешения ниже. Пропущенный крюк — это НАЗВАННОЕ «без
                    # крюков», а не «разреши из пула», поэтому и снапшота он
                    # требовать не должен.
                    continue
                if param == "top_level":
                    # audit F6 (generalized, P1 2026-07-21): omitted top_level
                    # = no top attach for ANY op (wall unconnected height,
                    # column as-placed height).  A top constraint is opt-in by
                    # construction — default-resolving one from the pool is
                    # never meaningful.  No pool read.
                    continue
                if not required and not (op["op"] in ("create_wall", "create_floor", "create_roof", "create_floor_by_contour") and param == "type"):
                    return True            # default rule reads the pool
                continue
            if isinstance(sel, dict) and sel.get("by") in (
                    "name", "default", "family_type"):
                return True
        # Адрес от осей читает пул `grids`.
        #
        # До 04.08 здесь стоял ОДИН оп и СТРОКОВЫЙ поиск:
        # `op["op"] == "create_floor_by_contour" and "at_grid" in repr(...)`.
        # Теперь адрес живёт в любом точечном параметре, и спрашивать про пул
        # надо по РЕАЛЬНЫМ значениям реальных параметров, а не по `repr`:
        # подстрока «at_grid» в имени типа больше не может ни включить чтение
        # пула, ни (что хуже) остаться незамеченной там, где адрес есть.
        #
        # 09.08.2026 — ОСТАТОК ТОЙ ЖЕ ПОЧИНКИ, ДОБИТЫЙ ВОЛНОЙ ТЕЛ. Строка
        # выше переехала на роды, а ЭТА осталась с зашитым ИМЕНЕМ параметра
        # `contour` — и работала ровно потому, что оба тогдашних региона так и
        # звались. Профиль тела зовётся `profile`, и с зашитым именем адрес от
        # осей внутри него не потребовал бы снапшота: пул `grids` пришёл бы
        # пустым, а отказ назвал бы «оси не найдены» вместо «снапшота нет» —
        # ремонт не туда. Правило адресуется РОДОМ, как и соседнее.
        if any("at_grid" in repr(op.get(p.name))
               for p in ospec.params if p.kind == "region"):
            return True
        if relate.program_uses_address(op):
            return True
        return False
    needs_snapshot = any(_needs_pool(op, spec.OPS[op["op"]]) for op in normed_ops)
    if needs_snapshot and not isinstance(snapshot, dict):
        raise KirRefusal([Diagnostic(
            code=GROUND_NO_SNAPSHOT,
            message_ru="программа требует снапшот модели (census) для ground-стадии (резолв по имени/default)")])
    if not isinstance(snapshot, dict):
        snapshot = {}
    diags: list[Diagnostic] = []
    pool_cache: dict[str, list[dict]] = {}

    def snapshot_pool(pool_name: str) -> list[dict]:
        if pool_name not in pool_cache:
            pool_cache[pool_name] = _validate_snapshot_pool(
                snapshot, pool_name, diags)
        return pool_cache[pool_name]

    def pool_truncated(pool_name: str) -> bool:
        return snapshot.get(pool_name + "__truncated") is True

    out = []
    address_receipt: list[dict] = []
    #: Заземлённые опы, СТОЯЩИЕ ВЫШЕ текущего, по id — единственный источник
    #: чисел для адреса от элемента. Наполняется в конце итерации, поэтому
    #: ссылка вперёд не находится ПО ПОСТРОЕНИЮ, а не по проверке, которую
    #: можно забыть добавить (тот же приём, что у `created` в `plan_program`).
    by_id_so_far: dict[str, dict] = {}
    for i, op in enumerate(normed_ops):
        ospec = spec.OPS[op["op"]]
        g = dict(op)
        # RELATE: адрес от осей -> литеральная точка, ЗДЕСЬ и до всего
        # остального. Пересечение двух прямых есть чистая функция от
        # снапшота: отказ до транзакции дешевле отказа внутри неё, а в
        # эмиттер, как и у CONTOUR, уходят только числа.
        op_receipt: list[dict] = []
        for param, dims in relate.addressable_params(ospec.name).items():
            value = op.get(param)
            if not relate.is_address(value):
                continue
            if relate.is_element_address(value):
                # АДРЕС ОТ ЭЛЕМЕНТА читает не снапшот, а САМУ ПРОГРАММУ —
                # уже заземлённые опы, стоящие ВЫШЕ (`by_id_so_far`). Отсюда
                # же и ответ на «а если элемент создаётся этой же программой»:
                # это ЕДИНСТВЕННЫЙ случай, который здесь и выражается, ровно
                # обратной стороной того, чем `at_grid` отказывает на оси из
                # той же программы. Пул `levels` нужен только отметке.
                point = relate.resolve_element_address(
                    value, by_id_so_far, snapshot_pool("levels"),
                    op["id"], param, diags, dims=dims, receipt=op_receipt)
            else:
                point = relate.resolve_address(
                    value, snapshot_pool("grids"), op["id"], param, diags,
                    dims=dims, truncated=pool_truncated("grids"),
                    receipt=op_receipt)
            if point is not None:
                g[param] = point
        if op_receipt:
            # КВИТАНЦИЯ. Автор написал «А/3» — он обязан увидеть, ЧТО из
            # этого вывел компилятор (id и имя каждой оси, отступ, сторона,
            # итоговая точка). Выбор, который некому предъявить, неотличим
            # от `.FirstOrDefault()` в костюме — тот же закон, что у
            # НАЗВАННОГО УМОЛЧАНИЯ.
            g["__address__"] = op_receipt
            address_receipt.extend(op_receipt)
        diameter_spec = next((p for p in ospec.params if p.name == "diameter_mm"), None)
        diameter_bounds = ((diameter_spec.min_val, diameter_spec.max_val)
                           if diameter_spec is not None else None)
        # CONTOUR: регион опускается в канонические рёбра ЗДЕСЬ, потому что
        # его точки могут быть адресами осей, а оси живут в снапшоте.
        #
        # Правило адресуется РОДОМ ПАРАМЕТРА, а не именем опа (09.08.2026).
        # До этого дня здесь стояло `if ospec.name == "create_floor_by_contour"`,
        # и второй оп с эскизом (create_ceiling) молча получил бы `contour`
        # без единого закона: анкеры неразрешёнными, дуги неопущенными, а
        # эмиттер — KeyError вместо формы. Род `region` в реестре ровно один
        # и означает ровно это, поэтому связывать надо с ним.
        for region_spec in [p for p in ospec.params if p.kind == "region"]:
            raw_region = op.get(region_spec.name)
            if raw_region is None:
                # Необязательный эскиз (у create_ceiling он альтернатива
                # `outline`). Обязательный отсутствующий уже назван раньше:
                # authoring_validation отказывает по роду, а взаимную
                # обязательность держит план (KIR-P007).
                continue
            from kukai.ir import contour as contour_mod
            grids = (snapshot_pool("grids")
                     if "at_grid" in repr(raw_region) else [])
            region = contour_mod.validate_region(
                raw_region, grids, op["id"], region_spec.name, diags)
            if region is not None:
                g["__region__"] = region
        if ospec.name == "create_group" and isinstance(op.get("members"), list):
            g["members"] = _ground_members(
                op["members"], snapshot, op["id"], diags, group_index=i)
        if ospec.name == "create_pipe_system":
            from kukai.ir import connect as connect_mod
            graph = connect_mod.graph_validate(
                op, op["id"], diags, op.get("diameter_mm"), diameter_bounds)
            if graph is not None:
                g["__graph__"] = graph
        if ospec.name in ("route_pipe_system", "route_duct_system"):
            # wave/mep: same connect.graph_validate reuse as create_pipe_system,
            # plus the checked (not generative) slope_min_pct extraction —
            # see ops_connect.py's module docstring and route_mep.py.
            from kukai.ir import connect as connect_mod
            from kukai.ir import route_mep as route_mep_mod
            slope_reqs = route_mep_mod.extract_slope_requirements(op, op["id"], diags)
            if slope_reqs is not None:
                stripped = route_mep_mod.strip_slope_keys(op)
                graph = connect_mod.graph_validate(
                    stripped, op["id"], diags, op.get("diameter_mm"), diameter_bounds)
                if graph is not None:
                    g["__graph__"] = graph
                    g["__slope_reqs__"] = slope_reqs
        # ССЫЛОЧНОЕ ЗНАЧЕНИЕ `set_param` СВЕРЯЕТСЯ С ПУЛОМ ЗДЕСЬ, А НЕ В
        # РАНТАЙМЕ. Оно не селектор и потому не проходит по `ospec.grounded`
        # ниже, но проверка ему нужна ровно та же — и РАНЬШЕ, чем эмиссия.
        #
        # Образец (`create_type.material`) разрешает имя коллектором ВНУТРИ
        # транзакции: отказ честный и типизированный, но приходит там, где
        # круг стоит дороже всего. Пул переносит ту же проверку на АВТОРСТВО —
        # неверное имя материала отказывается офлайн, до всякого Ревита.
        # Живая проверка при этом ОСТАЁТСЯ: пул — снимок, между снятием и
        # исполнением документ мог измениться, и снимать живого свидетеля
        # ради офлайнового было бы обменом доказательства на удобство.
        val = op.get("value")
        if (op.get("op") == "set_param" and isinstance(val, dict)
                and val.get("type") in ("ref", "int_ref")):
            pool_name = val.get("pool") or "materials"
            if pool_name == "worksets":
                # НАБОРЫ ЧИТАЮТСЯ НЕ КАК ПУЛ ЭЛЕМЕНТОВ, И ЭТО НЕ ОБХОД
                # ПРОВЕРКИ, А ЕЁ ПРИЗНАНИЕ. `snapshot_pool` требует
                # `1 <= id <= ELEMENT_ID_MAX`, потому что «пул» в этом
                # компиляторе означает ПУЛ ЭЛЕМЕНТОВ. У рабочего набора id —
                # `WorksetId.IntegerValue`, целое, начинающееся с НУЛЯ, и
                # `Workset` не наследует `Element`. Проверка была права, а
                # неверна была моя попытка объявить набор пулом: тот же урок,
                # что этажом ниже — «работа та же по форме, механизм другой».
                raw = snapshot.get("worksets")
                pool = []
                if raw is None:
                    pass
                elif not isinstance(raw, list):
                    diags.append(Diagnostic(
                        code=GROUND_BAD_SNAPSHOT, op_index=i, op_id=op["id"],
                        field_name="worksets", expected="список {id, name}",
                        got=type(raw).__name__,
                        message_ru="снапшот: worksets должен быть списком"))
                else:
                    for n, row in enumerate(raw):
                        wid = row.get("id") if isinstance(row, dict) else None
                        nm = row.get("name") if isinstance(row, dict) else None
                        if (isinstance(wid, bool) or not isinstance(wid, int)
                                or wid < 0 or not isinstance(nm, str)):
                            diags.append(Diagnostic(
                                code=GROUND_BAD_SNAPSHOT, op_index=i,
                                op_id=op["id"], field_name=f"worksets[{n}]",
                                expected="{id: целое >= 0, name: строка}",
                                got=row,
                                message_ru=(f"снапшот: worksets[{n}].id — "
                                            f"неотрицательное целое "
                                            f"(WorksetId.IntegerValue)")))
                        else:
                            pool.append(row)
            else:
                pool = snapshot_pool(pool_name)
            wanted = val.get("v")
            if pool_name == "worksets" and not snapshot.get(
                    "worksets__workshared", False):
                # НЕ «наборов нет», А «ДОКУМЕНТ НЕ РАЗДЕЛЁН». Один пустой пул
                # на два разных исхода — форма 11; здесь их различает
                # отдельный факт, который производитель снимает рядом с пулом.
                diags.append(Diagnostic(
                    code=GROUND_EMPTY_POOL, op_index=i, op_id=op["id"],
                    field_name="value", expected=pool_name,
                    message_ru=("документ не разделён на рабочие наборы — "
                                "набор задать некуда")))
            elif not pool:
                diags.append(Diagnostic(
                    code=GROUND_EMPTY_POOL, op_index=i, op_id=op["id"],
                    field_name="value", expected=pool_name,
                    message_ru=f"{pool_name}: пусто в модели"))
            else:
                _w = _REF_WORD.get(pool_name, (pool_name, "найден"))
                hit = [r for r in pool if r.get("name") == wanted]
                if not hit:
                    diags.append(Diagnostic(
                        code=GROUND_NOT_FOUND, op_index=i, op_id=op["id"],
                        field_name="value", expected=pool_name, got=wanted,
                        candidates=sorted(r.get("name") for r in pool)[:8],
                        message_ru=(f"{_w[0]} «{wanted}» не {_w[1]} в модели; "
                                    f"известно {len(pool)}")))
                elif len(hit) > 1:
                    diags.append(Diagnostic(
                        code=GROUND_AMBIGUOUS, op_index=i, op_id=op["id"],
                        field_name="value", expected=pool_name, got=wanted,
                        message_ru=(f"{_w[0]} «{wanted}» неоднозначен: "
                                    f"совпадений {len(hit)}")))
                # Найдено — и БОЛЬШЕ НИЧЕГО не делаем. Заземление здесь
                # только ОТКАЗЫВАЕТ; подставлять найденный id в программу
                # значило бы завести второй источник истины о материале
                # рядом с живым разрешением в эмиссии, и они разошлись бы на
                # первом же документе, изменившемся после снятия снимка.
        for param, pool_name, required in ospec.grounded:
            sel = op.get(param)
            pspec = next((pp for pp in ospec.params if pp.name == param), None)
            if pspec is not None and pspec.kind == "sel_list":
                # МНОЖЕСТВЕННОЕ ЧИСЛО РОДА `sel` (wave/datums).  Каждый
                # селектор списка резолвится ТЕМ ЖЕ `_resolve_one` и против
                # ТОГО ЖЕ пула, что одиночный: правило отбора, написанное
                # здесь второй раз, разошлось бы с одиночным на первом же
                # `disambiguate_by`.  Результат — СПИСОК `{"__grounded__":
                # ...}`, то есть та же форма, что у одиночного, поэлементно;
                # читает его только эмиттер своего опа.
                #
                # ВЕТКИ `by: ref` ЗДЕСЬ НЕТ, И ЭТО НЕ ПРОПУСК.  Сегодня ни
                # один параметр рода `sel_list` не объявляет `ref_kinds`
                # (см. `create_multistory_stairs.levels`: причина записана
                # там), поэтому validate отклоняет такую ссылку раньше — а
                # ветка, до которой нельзя дойти, это мёртвый код, который
                # со временем начинает выглядеть как работающая функция.
                # День, когда `ref_kinds` у списка появится, начинается с
                # обучения графа зависимостей в `compiler.plan_program`, и
                # ветка пишется ТОГДА, вместе с ним.
                if sel is None:
                    if required:
                        diags.append(Diagnostic(
                            code=GROUND_BAD_SELECTOR, op_index=i,
                            op_id=op["id"], field_name=param,
                            message_ru=(f"{param}: обязательный список "
                                        "селекторов отсутствует")))
                    continue
                resolved: list = []
                for one in sel:
                    res = _resolve_one(
                        one, pool_name, snapshot_pool(pool_name),
                        i, op["id"], param, ospec.name, diags,
                        truncated=pool_truncated(pool_name))
                    if res:
                        resolved.append({"__grounded__": res})
                if len(resolved) == len(sel):
                    # ОДНО И ТО ЖЕ ИМЯ ДВАЖДЫ — И РАЗНЫЕ ИМЕНА, ВЕДУЩИЕ К
                    # ОДНОМУ id, — ОДИН И ТОТ ЖЕ ДЕФЕКТ.  validate ловит
                    # только текстовый повтор; повтор ПО РЕЗУЛЬТАТУ виден
                    # лишь здесь, и пропустить его значило бы отдать
                    # ConnectLevels множество меньшей мощности, чем просили,
                    # — при равенстве множеств свидетель этого НЕ заметит.
                    ids = [r["__grounded__"].get("id") for r in resolved
                           if r["__grounded__"].get("id") is not None]
                    dup = next((x for k, x in enumerate(ids)
                                if x in ids[:k]), None)
                    if dup is not None:
                        diags.append(Diagnostic(
                            code=GROUND_BAD_SELECTOR, op_index=i,
                            op_id=op["id"], field_name=param, got=dup,
                            message_ru=(f"{param}: два селектора разрешились "
                                        f"в ОДИН элемент (id {dup}) — "
                                        "множество вышло меньше, чем "
                                        "названо")))
                    else:
                        g[param] = resolved
                continue
            if isinstance(sel, dict) and sel.get("by") == "ref":
                # intra-program DAG reference: resolved by the plan stage, not
                # against the snapshot (validity checked by the DAG walk).
                g[param] = {"__grounded__": {"ref": str(sel.get("value")), "via": "ref"}}
                continue
            if sel is None:
                # wave/struct (2026-07-17): create_foundation is the first op
                # whose grounded params are VARIETY-DISCRIMINATED — "symbol"
                # (FamilySymbol for the isolated footing) is irrelevant when
                # variety="slab", and "type" (FloorType for the slab) is
                # irrelevant when variety="isolated". The generic omitted-
                # optional rule below has no per-branch concept and would
                # otherwise speculatively resolve BOTH against their pools on
                # every create_foundation op regardless of variety — refusing
                # a perfectly well-formed program because the OTHER branch's
                # pool happens to be empty/ambiguous (a real bug caught live:
                # variety=isolated failed on empty floor_types, variety=slab
                # failed on empty foundation_symbols, neither pool being
                # relevant to the branch actually used). Skip silently (no
                # diagnostic, no __grounded__ entry) exactly when the branch
                # doesn't use the param — struct_emit.py's emit_foundation
                # dispatch never reads that key on the branch where it's
                # skipped, so this is
                # a true no-op for the irrelevant param, not a silent
                # substitute for a real resolution.
                if required:
                    diags.append(Diagnostic(
                        code=GROUND_BAD_SELECTOR, op_index=i, op_id=op["id"],
                        field_name=param, message_ru=f"{param} обязателен"))
                elif ospec.name == "create_foundation" and (
                        (param == "symbol" and op.get("variety") != "isolated") or
                        (param == "type" and op.get("variety") != "slab")):
                    pass
                elif (ospec.name == "create_topography"
                        and op.get("variety") != "toposolid"):
                    # wave/site: тот же шов, что у create_foundation и
                    # create_railing выше, и та же причина в её самой резкой
                    # форме. У ПОВЕРХНОСТИ рельефа уровня НЕ СУЩЕСТВУЕТ в
                    # API вовсе — TopographySurface.Create его не принимает,
                    # отметка живёт в Z каждой точки. Типа у неё тоже нет.
                    # Без этой ветки общее правило «единственный в пуле»
                    # подставило бы поверхности привязку к этажу, которой у
                    # неё быть не может, и свидетель начал бы проверять
                    # выдуманное; в проекте с двумя уровнями (то есть в
                    # любом настоящем) оно просто отказало бы KIR-G102,
                    # потеряв рельеф ни за что. Ветка накрывает ОБА
                    # необязательных селектора этого опа — и `level`, и
                    # `type`, — потому что оба принадлежат толще.
                    pass
                elif (ospec.name == "create_area_reinforcement"
                        and param == "hook_type"):
                    # wave/reinforcement (10.08): ПРОПУЩЕННЫЙ КРЮК ЗНАЧИТ «БЕЗ
                    # КРЮКОВ», и это значение САМОГО API, а не наша подстановка:
                    # «If this parameter is InvalidElementId, it means to create
                    # a rebar with no hooks» (RevitAPI.xml, AreaReinforcement.
                    # Create). Общее правило «единственный в пуле» здесь
                    # ВРАЛО БЫ дважды: в документе с одним типом крюка оно
                    # молча заанкерило бы арматуру, которую автор просил без
                    # анкеровки, а в документе с несколькими просто отказало бы
                    # KIR-G102 — потеряв армирование ни за что. Тот же шов и та
                    # же причина, что у create_topography.level ниже.
                    pass
                elif (ospec.name == "create_railing" and param == "level"
                        and op.get("variety") != "path"):
                    # wave/arch: ровно тот же шов, что у create_foundation
                    # строкой выше. Базовый уровень нужен ТОЛЬКО свободному
                    # ограждению (Railing.Create по пути его требует);
                    # ограждение на лестнице берёт уровень у хозяина, и
                    # перегрузка Railing.Create(doc, hostId, typeId, position)
                    # уровня не принимает вовсе. Без этой ветки общее правило
                    # «единственный в пуле» подставило бы уровень проекта в
                    # операцию, которая его не использует, а в проекте с двумя
                    # уровнями (то есть в любом настоящем) просто отказало бы
                    # KIR-G102 — потеряв ограждение ни за что.
                    pass
                elif (ospec.name == "place_family" and param == "level"
                        and "p0_mm" in op):
                    # Кривой вариант place_family уровня НЕ ИМЕЕТ, и это
                    # замер, а не упрощение: у всех 79 кожухов модели ЭОМ
                    # LevelId = -1, а перегрузка NewFamilyInstance по ссылке
                    # на грань хоста уровня не принимает вовсе. Общее
                    # правило ниже подставило бы «единственный уровень
                    # проекта», то есть привязку, которой у оригинала нет, —
                    # и свидетель начал бы проверять выдуманное. В проекте с
                    # двумя уровнями оно к тому же просто отказывает
                    # (KIR-G102), теряя элемент ни за что.
                    pass
                elif param == "top_level":
                    # audit F6 (generalized, P1 2026-07-21): omitted top_level
                    # MEANS «no top attach» for ANY op — wall keeps its
                    # unconnected height, column its as-placed height.  It must
                    # not speculatively resolve a "default level" from the pool
                    # (a sole-level model would silently attach every top).
                    # Skip: no diagnostic, no __grounded__ key; the emitter's
                    # absent-branch is the byte-stable historical emission.
                    pass
                elif ospec.name in ("create_wall", "create_floor", "create_roof",
                                    "create_floor_by_contour",
                                    # wave/wall-foundation (09.08): у
                                    # ленточного фундамента документный тип по
                                    # умолчанию СУЩЕСТВУЕТ —
                                    # ElementTypeGroup.WallFoundationType
                                    # компилируется на всех шести версиях
                                    # (замер), в отличие от двери, окна и
                                    # ограждения, где спросить документ нельзя
                                    # по построению. Подмена не молчалива:
                                    # свидетель semantic сверяет построенный
                                    # тип с тем самым id, который сюда попал.
                                    "create_wall_foundation",
                                    # wave/datums (09.08): выдавленная кровля
                                    # берёт тип у документа ровно как
                                    # контурная — `ElementTypeGroup.RoofType`
                                    # собирается на всех шести (замер :52412).
                                    # Без этой строки опущенный `type` уходил
                                    # бы в общее правило и отказывал
                                    # KIR-G104 на модели без пула, где
                                    # контурная кровля строится.
                                    "create_extrusion_roof",
                                    # wave/detail (09.08): у заливки
                                    # документный тип по умолчанию
                                    # СУЩЕСТВУЕТ — ElementTypeGroup.
                                    # FilledRegionType компилируется на всех
                                    # шести (замер). Общее правило
                                    # «единственный в пуле» здесь было бы
                                    # ХУЖЕ ВСЕГО: типов заливки у настоящего
                                    # проекта десятки, то есть опущенный
                                    # `type` отказывал бы KIR-G102 всегда, а
                                    # на пустом проекте — молча брал
                                    # единственный. Подмена не молчалива:
                                    # свидетель semantic сверяет
                                    # GetTypeId() с тем самым id.
                                    # wave/reinforcement (10.08): у армирования
                                    # по области документный тип по умолчанию
                                    # СУЩЕСТВУЕТ — ElementTypeGroup.
                                    # AreaReinforcementType компилируется на
                                    # всех шести (замер). Общее правило
                                    # «единственный в пуле» здесь было бы
                                    # ХУЖЕ ВСЕГО, как у заливки: типов
                                    # армирования у настоящего проекта КР
                                    # несколько, то есть опущенный `type`
                                    # отказывал бы KIR-G102 всегда. Подмена не
                                    # молчалива: свидетель semantic сверяет
                                    # GetTypeId() с тем самым id.
                                    "create_area_reinforcement",
                                    "create_filled_region") and param == "type":
                    g[param] = {"__grounded__": {"id": None, "name": None,
                                                 "via": "doc_default",
                                                 "in_emit": IN_EMIT_DEFAULT}}
                else:
                    # generic omitted-optional rule: the SOLE snapshot entry,
                    # several -> AMBIGUOUS (never first), none -> EMPTY_POOL
                    real_pool = (pool_name.format(category=op.get("category", "structural"))
                                 if "{category}" in pool_name else pool_name)
                    res = _resolve_one({"by": "default"}, real_pool,
                                       snapshot_pool(real_pool),
                                       i, op["id"], param, ospec.name, diags,
                                       truncated=pool_truncated(real_pool))
                    if res:
                        g[param] = {"__grounded__": res}
                continue
            real_pool = (pool_name.format(category=op.get("category", "structural"))
                         if "{category}" in pool_name else pool_name)
            selected_pool = (snapshot_pool(real_pool)
                             if sel.get("by") in (
                                 "name", "default", "family_type") else [])
            res = _resolve_one(sel, real_pool, selected_pool,
                               i, op["id"], param, ospec.name, diags,
                               truncated=pool_truncated(real_pool))
            if res:
                g[param] = {"__grounded__": res}
        by_id_so_far[op["id"]] = g
        out.append(g)
    if address_receipt:
        _recheck_geometry_after_addresses(out, diags)
    if diags:
        raise KirRefusal(diags)
    return out


def resolution_report(
    grounded_ops: list[dict],
) -> tuple["GroundingResolution", ...]:
    """Return every explicit selector resolution in deterministic order.

    ``compiler_choices`` is intentionally a concise user-facing report and
    omits ordinary by-name/by-id resolutions.  Digest evidence cannot make
    that trade-off: every nested ``__grounded__`` marker must be accounted,
    including selectors inside lists and grouped member operations.
    """
    from kukai.ir.midend import GroundingResolution

    report: list[GroundingResolution] = []
    for op in grounded_ops:
        op_id = op.get("id") if isinstance(op, dict) else None
        if not isinstance(op_id, str) or not op_id:
            raise ValueError("grounded operation needs an id")
        report.extend(GroundingResolution.collect(op_id=op_id, payload=op))
    return tuple(report)


def ground_program(
    planned: "PlannedProgram",
    snapshot: Any,
    *,
    context: "GroundingContext | None" = None,
) -> "GroundedProgram":
    """Freeze output and bind it to the exact snapshot that produced it.

    Direct compiler callers get a content-addressed, explicitly untrusted
    ``compiler_argument`` context.  The live serving boundary supplies its
    own trusted context after the bridge read.  Neither path invents revision
    evidence when the collector did not provide it.
    """
    from kukai.ir.midend import (
        GroundedProgram,
        GroundingContext,
        PlannedProgram,
    )

    if not isinstance(planned, PlannedProgram):
        raise TypeError("ground_program requires PlannedProgram")
    if context is None:
        context = GroundingContext.from_snapshot(
            snapshot,
            source="compiler_argument",
            trusted_source=False,
        )
    elif not isinstance(context, GroundingContext):
        raise TypeError("context must be GroundingContext or None")
    else:
        observed = GroundingContext.from_snapshot(
            snapshot,
            source="context_recheck",
            trusted_source=False,
        )
        if context.snapshot_digest != observed.snapshot_digest:
            raise ValueError(
                "grounding context is bound to another snapshot payload")
        if context.document_digest != observed.document_digest:
            raise ValueError(
                "grounding context is bound to another document identity")
    grounded_ops = ground(planned.to_ops(), snapshot)
    return GroundedProgram.from_ops(
        planned,
        grounded_ops,
        resolution_report(grounded_ops),
        context=context,
        snapshot=snapshot,
    )


def _recheck_geometry_after_addresses(grounded: list[dict],
                                      diags: list[Diagnostic]) -> None:
    """Законы, которым нужны ЧИСЛА, — второй площадкой вызова, не копией.

    Два закона плана читают координаты концов: «длина ~0» и «дверь за краем
    стены». Пока концы были литералами, оба доказывались до снапшота. Адрес от
    осей даёт числа только здесь — и закон обязан ДОЕХАТЬ сюда, а не замолчать
    на этой части диапазона (прибор на часть диапазона опаснее отсутствующего).

    Обе функции ИМПОРТИРУЮТСЯ, а не переписываются: `authoring_validation.
    reject_zero_length` и `compiler.hosted_offset_check` остаются
    единственными владельцами своих правил.

    ЗАКОН ЧИТАЕТ ТОЛЬКО РАЗРЕШЁННЫЕ ЧИСЛА, и это ОПРОВЕРГАЮЩИЙ ЗАМЕР, а не
    предосторожность (найдено 09.08.2026 на базе `2bfbec0a`, до всякой правки).
    Программа `create_wall` с адресом на НЕСУЩЕСТВУЮЩУЮ ось в `p0_mm` и
    верным адресом в `p1_mm` доходила сюда с квитанцией (второй адрес
    разрешился, значит `__address__` есть) и НЕразрешённым первым — то есть с
    объектом-адресом там, где закон ждёт список. `reject_zero_length` брал
    `p0_mm[0]` и получал `KeyError`, а вся программа отвечала
    «KIR-P000 внутренняя ошибка компилятора» ВМЕСТО честного KIR-G108
    «оси нет в модели», который в этот момент уже лежал в `diags`. Худший из
    возможных обменов: типизированный отказ с названным следующим ходом
    подменялся сообщением, которое посылает автора чинить компилятор.
    """
    from kukai.ir.authoring_validation import reject_zero_length
    from kukai.ir.compiler import hosted_offset_check

    def _resolved(op: dict) -> bool:
        return all(isinstance(op.get(key), list)
                   for key in ("p0_mm", "p1_mm"))

    addressed = {op["id"] for op in grounded if "__address__" in op}
    by_id = {op["id"]: op for op in grounded}
    for index, op in enumerate(grounded):
        if op["id"] in addressed and _resolved(op):
            reject_zero_length(op["p0_mm"], op["p1_mm"], op["op"], index,
                               op["id"], diags)
        if op["op"] not in ("create_window", "create_door"):
            continue
        host = op.get("host") or {}
        wall = by_id.get(host.get("value"))
        if (wall is None or wall.get("op") != "create_wall"
                or wall["id"] not in addressed or not _resolved(wall)):
            continue
        hosted_offset_check(op, wall, str(host.get("value")), index, diags)
