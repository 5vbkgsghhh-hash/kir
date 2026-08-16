"""СБОРКА, УВИДЕННАЯ ОДНИМ ОБЪЕКТОМ: наблюдения с адресом, без прозы.

ЗАЧЕМ. Аппарат проверяемости работает на арности 1 — один оп, одно
постусловие. Замысел живёт на арности N: «четыре стены замкнули контур», «дверь
попала в стену», «колонна ни на чём не стоит». Такие факты в дереве СЧИТАЮТСЯ —
и разъезжаются по четырём каналам в четырёх формах: HAB-правила прозой в
`building` (потолок 2600 символов, fail-open, только чат-дверь), клеш в
`result["clash"]` только на bulk-двери и при выключенном флаге отсутствует,
граф здания заметкой в заголовке сцены вьюера, `coherence` — русскими строками
для промпта.

Этот модуль их не пересчитывает. Он их СОБИРАЕТ в одну форму, пригодную для
чтения МОДЕЛЬЮ, а не человеком.

ТРИ ЗАКОНА, И КАЖДЫЙ КУПЛЕН ЗАМЕРОМ.

1. **У наблюдения ОБЯЗАТЕЛЕН АДРЕС.** Наблюдение без адреса не даёт модели
   ничего, что можно поправить: «контур не замкнут» без имён стен — это
   интонация. Адрес берётся ТОТ, КОТОРЫМ ЧИТАТЕЛЬ МОЖЕТ ДЕЙСТВОВАТЬ: на
   стадии программы это id операции (`w1`), а не ElementId, которого ещё нет.

2. **Список кодов ЗАКРЫТ.** Новый вид наблюдения обязан быть вписан сюда, иначе
   он уедет в отчёт безымянным. Это тот же приём, что `BLIND_CLASSES` без
   умолчания.

3. **МОЛЧАНИЕ ИСТОЧНИКА — ЭТО ЗАПИСЬ, А НЕ ПУСТОТА.** Если судья отказал или
   упал, его отказ едет в `silent_sources` С ПРИЧИНОЙ. Без этого отсутствие
   наблюдений читается как «всё хорошо», а это ровно тот молчаливо-неверный
   результат, против которого построен весь компилятор.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ, И ЭТО РЕШЕНИЕ ВЛАДЕЛЬЦА, А НЕ УПУЩЕНИЕ.
Он НЕ ОТКАЗЫВАЕТ. Ни одно наблюдение не делает запись красной и не трогает
приёмку. Диагноз — «модель строит вслепую», а не «модель пишет мусор»; лечим
слепоту, а не свободу. Неверный инвариант в воротах отверг бы законное здание
и выглядел бы поломкой продукта; неверный инвариант у рассказчика — неточной
подсказкой.

ГРАНИЦА ИСТОЧНИКА, НАЗВАННАЯ ЗДЕСЬ. Дверей теперь ДВЕ, и они судят РАЗНОЕ:
`observe_program` — ЗАЯВЛЕННОЕ программой (`ModelSource.PROGRAM`),
`observe_l0` — ПОСТРОЕННОЕ, перечитанное в L0 (`ModelSource.PARSE`), теми же
правилами и тем же `check_design`. Поэтому поле `source` едет в ответе всегда:
читатель обязан знать, судят его замысел или его здание.

ЧЕСТНАЯ ГРАНИЦА ЭТОЙ ВТОРОЙ ДВЕРИ, чтобы её не прочли как замкнутую петлю.
Она судит УЖЕ прочитанный L0 и сама Ревит не перечитывает; в живом потоке
записи её пока никто не зовёт. То есть ветка `PARSE` перестала быть
недостижимой из этого модуля и НЕ стала участником хода — это две разные
вещи, и вторая стоит рейса к мосту.

И АДРЕСА У ДВУХ ДВЕРЕЙ ЛЕЖАТ В РАЗНЫХ ПРОСТРАНСТВАХ — см. `address_space`.

🔴 ГРАНИЦА, УНАСЛЕДОВАННАЯ ОТ СУДЬИ, И ЕЁ НАДО ЗНАТЬ ЧИТАТЕЛЮ СВОДКИ
(замерено разведкой 15.08). Наблюдения `hab:*` приезжают из вердикта, а
`design_check` СНИМАЕТ ШЕСТЬ ПРАВИЛ БЕЗУСЛОВНО: `HAB002/003/004/042`
(`_APARTMENT_ORACLE_RULES`, снимаются в `design_stage_profile` — точность
вывода квартиры замерена 03.08 и разгромна, 0 % по составу жилища) плюс
`HAB031` (нет площади проёма в снимке) и `HAB050` (у `create_wall` нет
параметра несущей стены).

Значит: **эвакуация, состав квартиры и замкнутость оболочки квартиры в этой
сводке не появятся НИКОГДА** — не потому, что здание их проходит, а потому,
что правила не судили. Их отсутствие в наблюдениях НЕ ЕСТЬ свидетельство.
Сводка это не скрывает: снятое правило не попадает и в `silent_sources`, так
что читателю остаётся ЭТА строка — и она здесь именно поэтому.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

#: КОДЫ НАБЛЮДЕНИЙ. Список ЗАКРЫТ и ПОЛОН ПО ПОСТРОЕНИЮ для тех источников,
#: которые уже подключены; источник, дающий код не отсюда, роняет сборку, а не
#: печатает его молча.
#:
#: `hab:*` — коды правил пригодности, приезжают КАК ЕСТЬ (`rule_id`), потому
#: что у них уже есть закрытый реестр в `checker/engine.RULE_REGISTRY`, и
#: заводить второе имя тому же правилу значило бы развести два списка.
OBSERVATION_CODES: tuple[str, ...] = (
    "enclosure_ok",          # стены замкнули область; число — площадь, м²
    "enclosure_none",        # стены объявлены, не замкнули НИЧЕГО
    "no_walls",              # стен в программе нет вовсе — судить нечего
    # --- связность конструктива (`design/coherence`). Имена НАШИ, потому что
    # у того модуля нет реестра кодов: он отдаёт русские ключи отчёта. Здесь
    # они получают имя один раз и в закрытом списке.
    "column_off_slab",       # колонна не стоит ни на одной плите
    "wall_off_slab",         # стена не стоит ни на одной плите
    "beam_unsupported",      # у балки есть конец, не достающий до колонны
    # --- ЕДИНИЦА ЗАМЫСЛА (`course.unit(reads_as=...)`). Арность N: факт не об
    # элементе, а о ТОМ, КАК НАБОР ЭЛЕМЕНТОВ ЧИТАЕТСЯ. Постусловие такого
    # сказать не может по построению — оно стоит на одном опе.
    "unit_not_continuous",   # члены единицы не читаются как одна непрерывная вещь
)

#: Приставка кодов, приезжающих из чужого закрытого реестра. Такой код
#: пропускается без проверки по `OBSERVATION_CODES`, и это НАЗВАНО: его
#: полнота держится ТАМ, а дублировать реестр правил здесь значит развести
#: два списка, которые обязаны совпадать и ничем не связаны.
#: `preview:*` — коды аномалий плана (`preview.AnomalyReason`), тоже свой
#: закрытый реестр, тоже приезжают КАК ЕСТЬ, по той же причине.
FOREIGN_CODE_PREFIXES: tuple[str, ...] = ("hab:", "preview:")


# ══════════════════════════════════════════════════════════════════════════
# ПРЕДИКАТЫ ЧТЕНИЯ ЕДИНИЦЫ — ОТКРЫТЫЙ РЕЕСТР
# ══════════════════════════════════════════════════════════════════════════
#
# 🔴 РОД ЭТОГО СПИСКА: **ОТКРЫТЫЙ НА ДОПОЛНЕНИЕ.** Это не «закрытый, но не
# полный» и не «полный по построению» — третий род, и он объявляется здесь
# явно, потому что от рода зависит, что означает ОТСУТСТВИЕ записи.
# Отсутствие предиката здесь означает: ТАКОГО СПОСОБА ЧТЕНИЯ МЫ ПОКА НЕ
# УМЕЕМ ПРОВЕРЯТЬ. Не «набор так не читается» и не «мы решили, что не надо».
#
# ПОЧЕМУ ОТКРЫТЫЙ, И ПОЧЕМУ ЭТО НЕ СЛАБОСТЬ. Владелец отверг словарь
# КОМПОЗИТОВ в реестре, и отверг верно: зданий неограниченно много, и
# закрытый список существительных над открытой областью ломается на первом
# же объекте, который в него не лёг. Но здесь перечисляются НЕ ЗДАНИЯ.
# Здесь перечисляются СПОСОБЫ, КОТОРЫМИ НАБОР ЭЛЕМЕНТОВ МОЖЕТ ЧИТАТЬСЯ, а их
# единицы: непрерывная · соосная · компланарная · этажированная ·
# замыкающая. Композит остаётся функцией, которую модель пишет САМА; сюда
# она приносит только ответ на вопрос «как это читать».
#
# ТРЕБОВАНИЕ К КАЖДОМУ ЖИЛЬЦУ, БЕЗ КОТОРОГО ОН НЕ ЖИЛЕЦ: свой КОНТРОЛЬ-FAIL.
# Предикат, который не умеет сказать «нет», не предикат, а украшение — он
# зелен по построению и не измеряет ничего (форма 18: зелёное без акта
# различения). Ратчет `test_unit_reads.py` требует у каждого имени пару
# «нарушающий вход -> находка» И «здоровый вход -> пусто», и падает на
# добавлении имени без этой пары.

#: Допуск стыка, ММ. Выше измеренного шума `anchor_mm` (0.5 мм, замер fold) и
#: ниже любого зазора, который автор написал бы намеренно.
UNIT_JOIN_TOL_MM = 1.0

#: Допуск соосности — ПЕРПЕНДИКУЛЯРНОЕ ОТКЛОНЕНИЕ В ММ, а не векторное
#: произведение. Канон называет сравнение допуска в мм с произведением в мм²
#: своим именным дефектом (`_on_segment`, `_point_in_prism`); здесь величина
#: и допуск в одних единицах по построению.
UNIT_COLLINEAR_TOL_MM = 1.0

#: Поля, чьё расхождение делает соседние отрезки РАЗНЫМИ вещами, даже когда
#: они сошлись концами и лежат на одной оси. Это и есть «полосатая стена»:
#: геометрически лента, по прочтению — полосы.
_READS_SAME_FIELDS: tuple[str, ...] = ("type", "height_mm")


def _seg(op: Mapping[str, Any]) -> tuple[tuple[float, float],
                                         tuple[float, float]] | None:
    """Отрезок опа в плане, ММ. `None` — оп отрезка не несёт."""
    p0, p1 = op.get("p0_mm"), op.get("p1_mm")
    try:
        return ((float(p0[0]), float(p0[1])), (float(p1[0]), float(p1[1])))
    except (TypeError, IndexError, ValueError):
        return None


def _dist_mm(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _off_line_mm(a: tuple[float, float], b: tuple[float, float],
                 p: tuple[float, float]) -> float:
    """Расстояние от точки `p` до ПРЯМОЙ через `a`,`b` — в миллиметрах."""
    length = _dist_mm(a, b)
    if length <= 0.0:
        return _dist_mm(a, p)
    # Векторное произведение делится на длину -> мм² / мм = мм. Деление здесь
    # и есть то, что делает величину сравнимой с допуском в мм.
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    return abs(cross) / length


def reads_continuous(members: Sequence[Mapping[str, Any]]
                     ) -> list[tuple[str, tuple[str, ...]]]:
    """«Эти элементы читаются как ОДНА непрерывная вещь» — лента, ось, нитка.

    Возвращает список разрывов: (причина, адреса участников). Пусто — читается.

    ЧТО ЗНАЧИТ «НЕПРЕРЫВНО» И ПОЧЕМУ ИМЕННО ТАК. Три стены встык — не дефект
    сами по себе: настоящая лента часто набрана из отрезков (разные оси,
    деформационный шов, смена этажа). Дефект — когда набор ОБЪЯВЛЕН одной
    вещью, а прочитаться одной не может. Проверяются ровно три вещи, и все
    три — про ЧТЕНИЕ, а не про вкус:

      `gap`          соседние отрезки не сошлись концами: между ними дыра
                     либо нахлёст. Читатель увидит два объекта, автор
                     объявил один;
      `kink`         сошлись, но следующий уходит с оси предыдущего: это
                     излом, то есть два направления, а не одна нитка;
      `type_differs` / `height_differs` — сошлись и соосны, но объявлены
                     разными. ЭТО И ЕСТЬ ПОЛОСАТАЯ СТЕНА: геометрия
                     непрерывна, прочтение — полосы.

    ЧЕГО ЭТОТ ПРЕДИКАТ НЕ ДЕЛАЕТ, И ЭТО НАЗВАНО. Он не судит ЗАМЫСЕЛ: если
    автор объявил лентой то, что лентой быть не должно, предикат промолчит —
    он проверяет заявленное прочтение, а не выбор прочтения. И он не смотрит
    на этаж: две стены одного плана на разных уровнях сошлись бы концами в
    плане, поэтому уровень входит в сравнение как обычное поле (см. вызов).

    ОДИН ЧЛЕН НЕ МОЖЕТ ПРОВАЛИТЬСЯ, и это сказано вслух: сравнивать не с чем.
    Контроль такого предиката на выборке из одного зелен ПО ПОСТРОЕНИЮ —
    ровно «вырожденный контроль» канона, — поэтому ратчет требует у пары
    контролей мощность >= 2.
    """
    breaks: list[tuple[str, tuple[str, ...]]] = []
    prev: tuple[str, tuple, tuple] | None = None
    for member in members:
        oid = str(member.get("id") or "")
        seg = _seg(member)
        if seg is None:
            continue
        if prev is not None:
            prev_id, prev_a, prev_b = prev
            pair = (prev_id, oid)
            if _dist_mm(prev_b, seg[0]) > UNIT_JOIN_TOL_MM:
                breaks.append(("gap", pair))
            elif _off_line_mm(prev_a, prev_b, seg[1]) > UNIT_COLLINEAR_TOL_MM:
                breaks.append(("kink", pair))
        prev = (oid, seg[0], seg[1])

    # РАСХОЖДЕНИЕ ПОЛЕЙ СЧИТАЕТСЯ ПО ВСЕМУ НАБОРУ, а не по соседям: полоса
    # посреди ленты — расхождение с обоими соседями, и назвать его дважды
    # значило бы посчитать один дефект за два.
    for field_name in _READS_SAME_FIELDS:
        seen: dict[str, list[str]] = {}
        for member in members:
            if _seg(member) is None or field_name not in member:
                continue
            key = _canonical_json_key(member.get(field_name))
            seen.setdefault(key, []).append(str(member.get("id") or ""))
        if len(seen) > 1:
            odd = sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            # Адресуются МЕНЬШИНСТВА: править надо их, а не большинство.
            addresses = tuple(oid for _key, ids in odd[1:] for oid in ids)
            breaks.append(("%s_differs" % field_name.replace("_mm", ""),
                           addresses))
    return breaks


def _canonical_json_key(value: Any) -> str:
    """Сравнимый ключ значения поля. Словарь-селектор сравнивается ЦЕЛИКОМ:
    `{"by":"name","value":"Витраж 200"}` и `{"by":"name","value":"Кирпич"}` —
    разные типы, и различие обязано быть видно."""
    import json as _json
    try:
        return _json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


#: ИМЯ ПРОЧТЕНИЯ -> ПРЕДИКАТ. Открыт на дополнение; каждый жилец обязан иметь
#: пару контролей в `test_unit_reads.py` (нарушение -> находка, здоровое ->
#: пусто), иначе ратчет краснеет.
UNIT_READS: dict[str, Any] = {
    "continuous": reads_continuous,
}

#: Человеческое объяснение каждого прочтения — едет автору в ОТКАЗ, когда он
#: назвал несуществующее имя. Ключи обязаны совпадать с `UNIT_READS` символ в
#: символ, и это держит тест, а не соглашение.
UNIT_READS_RU: dict[str, str] = {
    "continuous": "одна непрерывная вещь: лента, ось, нитка — концы сходятся, "
                  "направление не ломается, тип и высота едины",
}


#: Имя, которым ЭТОТ модуль представляется судье. Для СРАВНЕНИЯ не годится:
#: у каждого вызывающего оно своё (`live.verdict` зовёт судью с «здание этой
#: сессии (пачка программ)»), и константа здесь дала бы ровно тот дефект, ради
#: которого модуль написан, — утверждать в одном месте и читать в другом.
#: Имя здания для сравнения СПРАШИВАЕТСЯ У ВЕРДИКТА (`verdict.building_id`).
BUILDING_ID = "(сборка)"


class AssemblyViewError(ValueError):
    """Нарушен закон формы: код вне списка либо наблюдение без адреса."""


#: Сколько адресов несёт ОДНО наблюдение. Четырёхстенная коробка — самый частый
#: предмет разговора, и она обязана уместиться целиком; перечитанное здание даёт
#: 690 стен (замер `sob62_r23_v5`, 15.08), и такой список адресом уже не
#: является — им нельзя действовать, его можно только пролистать.
#:
#: 🔴 ОБРЕЗАТЬ МОЛЧА НЕЛЬЗЯ: усечённый список, не сказавший об усечении, читается
#: как полный, и решение по нему принимают как по полному. Поэтому наблюдение
#: несёт `address_total` — сколько адресов было НА САМОМ ДЕЛЕ.
ADDRESS_CAP = 12


@dataclass(frozen=True)
class Observation:
    """Одно наблюдение о СБОРКЕ: что, о ком, сколько."""

    code: str
    #: адреса, которыми читатель может действовать. НЕПУСТОЙ по построению.
    address: tuple[str, ...]
    #: мера наблюдения; `None` — мера не определена для этого кода, а не «ноль».
    number: float | None = None
    #: 🔴 ЭТО ЕДИНИЦА ИЗМЕРЕНИЯ («м²»), А НЕ ЕДИНИЦА ЗАМЫСЛА. Имя занято
    #: раньше и не переименовывается: его читает `to_dict` и всё, что смотрит
    #: в квитанцию. Единица замысла — соседнее поле `of_unit`, и они НЕ
    #: синонимы. Омоним под одним словом — тот самый род ошибки, из-за
    #: которого 13.08 едва не сделали вывод «изоляция уже записывается».
    unit: str = ""
    #: АДРЕС ЕДИНИЦЫ ЗАМЫСЛА, в которой написаны эти элементы (`unit_id` из
    #: таблицы `units` конверта). Пусто — наблюдение не о единице.
    #: Стоит РЯДОМ с `address`, а не вместо: адреса элементов говорят, что
    #: править, адрес единицы — в каком замысле это написано, и терять второе
    #: значит возвращать модель к поэлементному чтению собственной программы.
    of_unit: str = ""
    #: сколько адресов у наблюдения ВСЕГО. 0 — «столько же, сколько показано».
    #: Больше `len(address)` — список усечён, и ответ обязан это сказать.
    address_total: int = 0

    def __post_init__(self) -> None:
        if not self.address:
            raise AssemblyViewError(
                "наблюдение %r без адреса: читателю нечего править" % self.code)
        if self.address_total and self.address_total < len(self.address):
            raise AssemblyViewError(
                "наблюдение %r: показано %d адресов при заявленных %d — "
                "усечение не может быть отрицательным"
                % (self.code, len(self.address), self.address_total))
        known = (self.code in OBSERVATION_CODES
                 or self.code.startswith(FOREIGN_CODE_PREFIXES))
        if not known:
            raise AssemblyViewError(
                "код %r вне закрытого списка наблюдений" % self.code)

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"code": self.code, "at": list(self.address)}
        if self.of_unit:
            row["of_unit"] = self.of_unit
        if self.address_total > len(self.address):
            # Полное число едет ВСЕГДА, когда список неполон: без него читатель
            # не отличит «эти четыре стены» от «четыре из шестисот девяноста».
            row["at_of"] = self.address_total
        if self.number is not None:
            row["n"] = self.number
            if self.unit:
                row["unit"] = self.unit
        return row


@dataclass(frozen=True)
class AssemblyView:
    """Что видно о сборке — и чего НЕ видно, с названной причиной."""

    observations: tuple[Observation, ...] = ()
    #: источник -> почему он ничего не сказал. Пустой словарь = все ответили.
    silent_sources: dict[str, str] = field(default_factory=dict)
    #: у кого спрашивали. Без этого «ноль наблюдений» неотличим от «не спросили».
    sources_asked: tuple[str, ...] = ()
    #: судили ЗАЯВЛЕННОЕ или ПОСТРОЕННОЕ
    source: str = "program"
    #: 🔴 В КАКОМ ПРОСТРАНСТВЕ ЛЕЖАТ АДРЕСА. Две сводки об одном здании могут
    #: адресовать его РАЗНО: замысел знает только id операции (`w1`) — ElementId
    #: на стадии программы ещё не существует, — а перечитанное здание знает
    #: только `element_id` Ревита (`4001`). Замер 15.08 подтвердил общий адрес у
    #: ЧЕТЫРЁХ МИРОВ РАЗБОРА (`tools/address_spine.py`: fold, building_graph,
    #: SpatialModel — ноль адресов вне L0 на двух зданиях). Он НИЧЕГО не сказал
    #: про программу, и не мог: её адресов в L0 нет по построению.
    #:
    #: Мост между двумя пространствами существует ровно один — квитанция записи
    #: (`result["w1"]["id"] == "9001"`). Пока сводки не сшиты через неё, поле
    #: обязано ехать в ответе: сравнивать наблюдения из разных пространств,
    #: не заметив этого, — ровно наш именной дефект.
    address_space: str = "op_id"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "assembly-view/1",
            "source": self.source,
            "address_space": self.address_space,
            "asked": list(self.sources_asked),
            "silent": dict(self.silent_sources),
            "observations": [o.to_dict() for o in self.observations],
        }


def _wall_op_ids(ops: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(op.get("id")) for op in ops
            if op.get("op") == "create_wall" and op.get("id") is not None]


def _ops_of(program: Any) -> list[Mapping[str, Any]]:
    if isinstance(program, Mapping):
        raw = program.get("ops")
        if isinstance(raw, Sequence):
            return [op for op in raw if isinstance(op, Mapping)]
    return []


def observe_program(program: Any) -> AssemblyView:
    """Наблюдения о сборке ОДНОЙ программы KIR — из того, что уже считается.

    Здесь не появляется ни одной новой геометрии: замкнутость считает
    `design_check` планарным разбиением с допуском, выбранным замером на
    настоящем здании (100 мм; 0→11.3 %, 100→37.8 % измеримых помещений).
    """
    ops = _ops_of(program)
    walls = _wall_op_ids(ops)
    asked: list[str] = ["design_check", "preview", "coherence"]
    silent: dict[str, str] = {}
    out: list[Observation] = []

    if not walls:
        # НЕ МОЛЧИМ. «Стен нет» и «стены есть, но ничего не замкнули» — разные
        # факты, и читатель обязан их различать; иначе пустой список наблюдений
        # читается как «всё хорошо».
        # `preview` спрашивается И ЗДЕСЬ: «стен нет» не означает «смотреть не на
        # что» — проём без хозяина и незамкнутое помещение живут без единой
        # стены в программе. Пропустить источник, оставив его в `asked`, значило
        # бы соврать о том, у кого спрашивали.
        anomalies, preview_silence = observe_plan_anomalies([program])
        silent.update(preview_silence)
        loose, coherence_silence = observe_coherence([program])
        silent.update(coherence_silence)
        return AssemblyView(
            observations=((Observation("no_walls", address=("(программа)",)),)
                          + tuple(anomalies) + tuple(loose)),
            silent_sources=silent, sources_asked=tuple(asked))

    try:
        from kukai.ir import design_check as _dc
        verdict = _dc.check_bundle([program], building_id=BUILDING_ID)
    except Exception as exc:  # noqa: BLE001 — отказ судьи ЭТО ДАННЫЕ
        silent["design_check"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        anomalies, preview_silence = observe_plan_anomalies([program])
        silent.update(preview_silence)
        loose, coherence_silence = observe_coherence([program])
        silent.update(coherence_silence)
        return AssemblyView(observations=tuple(anomalies) + tuple(loose),
                            silent_sources=silent, sources_asked=tuple(asked))

    return observe_verdict(verdict, walls, programs=[program])


def observe_plan_anomalies(
        programs: Sequence[Any]) -> tuple[list[Observation], dict[str, str]]:
    """Аномалии ПЛАНА — второй источник сводки, и он видит то, чего не видит судья.

    🔴 ЗАЧЕМ ВТОРОЙ ИСТОЧНИК, ЕСЛИ ЕСТЬ ПЕРВЫЙ. Замер 15.08 на трёх программах:
    одна стена 0→6000, три стены встык и ДВЕ СТЕНЫ В ОДНОМ МЕСТЕ дали у
    `design_check` ОДИН И ТОТ ЖЕ ответ `enclosure_none`. Различался только
    список адресов, а он говорит, сколько стен написали, — не о сборке. Сводка,
    отвечающая одинаково на здоровое и на дублированное, не измеряет ничего.
    `preview` различает дубли по одним лишь концам осей, за 0.1 мс, включая
    случай, когда вторая стена нарисована в обратную сторону.

    ЧТО ЭТОТ ИСТОЧНИК НЕ ВИДИТ, названо им самим (`preview.BLIND_SPOTS`): план
    это срез XY, в нём нет высот, замкнутости оболочки и трёхмерных пересечений.
    Поэтому он ДОПОЛНЯЕТ судью, а не заменяет.

    ПОЧЕМУ КОДЫ ЕДУТ С ПРИСТАВКОЙ, А НЕ ПЕРЕИМЕНОВЫВАЮТСЯ. У `AnomalyReason`
    свой закрытый реестр; завести здесь второе имя тем же явлениям значило бы
    развести два списка, обязанных совпадать, — тот самый дефект, против
    которого написан модуль.
    """
    out: list[Observation] = []
    silent: dict[str, str] = {}
    try:
        from kukai.ir import preview as _pv
    except Exception as exc:  # noqa: BLE001
        return out, {"preview": "%s: %s" % (type(exc).__name__, str(exc)[:120])}

    for index, program in enumerate(programs):
        try:
            plan = _pv.build_program_preview(program)
        except Exception as exc:  # noqa: BLE001 — отказ источника ЭТО ДАННЫЕ
            silent.setdefault(
                "preview" if len(programs) == 1 else "preview[%d]" % index,
                "%s: %s" % (type(exc).__name__, str(exc)[:140]))
            continue
        # Аномалии одного рода собираются в ОДНО наблюдение: десять дублей —
        # это один вид дефекта в десяти местах, а не десять разных новостей.
        by_reason: dict[str, list[str]] = {}
        for sheet in getattr(plan, "plans", ()) or ():
            for element in getattr(sheet, "elements", ()) or ():
                address = str(getattr(element, "element_id", "") or "")
                if not address:
                    continue
                for reason in getattr(element, "anomalies", ()) or ():
                    code = str(getattr(reason, "value", reason))
                    seen = by_reason.setdefault(code, [])
                    if address not in seen:
                        seen.append(address)
        for code, addresses in by_reason.items():
            out.append(Observation(
                "preview:" + code, address=tuple(addresses[:ADDRESS_CAP]),
                address_total=len(addresses)))
    return out, silent


#: Ключ отчёта `coherence` -> наш код наблюдения. Список ЗАКРЫТ: новый род
#: несвязности обязан получить имя здесь, иначе уедет в отчёт безымянным.
_COHERENCE_CODES: tuple[tuple[str, str], ...] = (
    ("колонн_вне_плиты_адреса", "column_off_slab"),
    ("стен_вне_плиты_адреса", "wall_off_slab"),
    ("балок_без_опоры_адреса", "beam_unsupported"),
)


def observe_units(
        programs: Sequence[Any]) -> tuple[list[Observation], dict[str, str]]:
    """ЕДИНИЦЫ ЗАМЫСЛА — источник, работающий на АРНОСТИ N.

    🔴 ЗАЧЕМ ЭТО ВООБЩЕ, ОДНОЙ ФРАЗОЙ. Весь остальной аппарат проверяет
    арность 1: оп -> элемент -> постусловие. Замысел живёт на арности N —
    «три соседних стены ДОЛЖНЫ читаться как одна лента», — и постусловие
    сказать этого не может по построению: оно стоит на одном опе и про соседа
    не знает. Полосатая стена проходит все три оси свидетеля, потому что
    каждая стена в отдельности безупречна. Здесь читается НАБОР.

    ОТКУДА БЕРЁТСЯ НАБОР. Из таблицы `units` конверта, которую пишет
    `course.unit(...)` СРЕЗОМ — по образцу `phase()`. Опы при этом остаются
    побайтово теми же: их дайджест подписывает программу, и номер единицы,
    вписанный в каждый оп, сдвинул бы подпись у здания, которое не менялось.

    ПОЧЕМУ ЧЛЕНЫ ИЩУТСЯ ДВУМЯ СПОСОБАМИ. Единица может быть записана группой
    Ревита (`as_group=True`, сегодняшнее умолчание) — тогда её члены лежат
    ВНУТРИ опа `create_group`; либо срезом (`as_group=False`) — тогда они
    лежат в программе верхним уровнем. Прочтение от этого не зависит, и
    предикат обязан отвечать одинаково: способ ЗАПИСИ не меняет того, как
    набор ЧИТАЕТСЯ.

    МОЛЧАНИЕ НАЗЫВАЕТСЯ. Единица без `reads_as` не судится — автор не сказал,
    как её читать, и выдумать за него значило бы кричать на всё подряд
    (`silent_sources`). Имя вне реестра сюда не доедет: его отвергает
    `course.unit()` в момент записи, с перечнем известных имён.
    """
    out: list[Observation] = []
    silent: dict[str, str] = {}
    seen_any = False

    for index, program in enumerate(programs):
        if not isinstance(program, Mapping):
            continue
        units = program.get("units")
        if not units:
            continue
        ops_by_id: dict[str, Mapping[str, Any]] = {}
        for op in (program.get("ops") or ()):
            if isinstance(op, Mapping) and op.get("id") is not None:
                ops_by_id[str(op["id"])] = op
                # члены группы — тоже адресуемые опы
                for member in (op.get("members") or ()):
                    if isinstance(member, Mapping) and member.get("id") is not None:
                        ops_by_id[str(member["id"])] = member
        for row in units:
            if not isinstance(row, Mapping):
                continue
            unit_id = str(row.get("unit_id") or "")
            reads_as = row.get("reads_as")
            if not reads_as:
                continue
            seen_any = True
            predicate = UNIT_READS.get(str(reads_as))
            if predicate is None:
                # Дожило имя, которого реестр не знает: реестр ОТКРЫТ, значит
                # это «не умеем проверять», а не «нарушение». Молчим с причиной.
                silent["unit:%s" % unit_id] = (
                    "прочтение %r не в реестре предикатов — проверить нечем"
                    % reads_as)
                continue
            members = [ops_by_id[str(mid)]
                       for mid in (row.get("member_ids") or ())
                       if str(mid) in ops_by_id]
            if len(members) < 2:
                # ВЫРОЖДЕННЫЙ ВХОД НАЗЫВАЕТСЯ, А НЕ ПРОХОДИТ МОЛЧА: на одном
                # члене всякий предикат непрерывности зелен по построению, и
                # зелёное здесь означало бы «проверено», хотя сравнивать не с
                # чем. Это форма 18 канона, пойманная на входе.
                silent["unit:%s" % unit_id] = (
                    "членов %d — предикату %r нечего сравнивать (нужно >= 2)"
                    % (len(members), reads_as))
                continue
            try:
                breaks = predicate(members)
            except Exception as exc:  # noqa: BLE001 — отказ источника ЭТО ДАННЫЕ
                silent["unit:%s" % unit_id] = (
                    "%s: %s" % (type(exc).__name__, str(exc)[:140]))
                continue
            if not breaks:
                continue
            addresses: list[str] = []
            reasons: list[str] = []
            for reason, ids in breaks:
                reasons.append(reason)
                for oid in ids:
                    if oid and oid not in addresses:
                        addresses.append(oid)
            if not addresses:
                continue
            # КОД ВЫВОДИТСЯ ИЗ ИМЕНИ ПРОЧТЕНИЯ, А НЕ ПИШЕТСЯ ЛИТЕРАЛОМ.
            # Реестр предикатов ОТКРЫТ, список кодов ЗАКРЫТ — и это не
            # противоречие, а шов, который обязан заскрипеть: новый предикат
            # без своего кода уезжает в молчание С ПРИЧИНОЙ, то есть требует
            # решения, вместо того чтобы прислониться к чужому коду и стать
            # неотличимым от него в квитанции.
            code = "unit_not_%s" % reads_as
            if code not in OBSERVATION_CODES:
                silent["unit:%s" % unit_id] = (
                    "предикат %r есть, а кода %r в закрытом списке наблюдений "
                    "нет: назови код, иначе находка неотличима от чужой"
                    % (reads_as, code))
                continue
            shown = tuple(addresses[:ADDRESS_CAP])
            out.append(Observation(
                code=code,
                address=shown,
                of_unit=unit_id or "(без адреса)",
                number=float(len(breaks)),
                unit="разрыв",
                address_total=len(addresses)))
    if not seen_any and not out:
        return out, silent
    return out, silent


def observe_coherence(
        programs: Sequence[Any]) -> tuple[list[Observation], dict[str, str]]:
    """Связность конструктива — третий источник: что НИ НА ЧЁМ НЕ СТОИТ.

    🔴 ПОЧЕМУ ЕГО НЕ БЫЛО ДО 15.08, ХОТЯ ОН СЧИТАЕТСЯ ДАВНО. `coherence.check`
    отдавал СЧЁТЧИКИ без адресов («колонн_вне_плиты: 404»), а первый закон
    сводки требует адреса, которым можно действовать: «404 колонны в воздухе»
    модель починить не может. Причина счётчиков лежала на одну функцию выше —
    `flatten` держал `id` операции в руках и не переносил его в `Elem`.
    Источник не отсутствовал; он был отрезан ОДНИМ ПОЛЕМ. Это наш способ
    отказа по умолчанию: работа сделана и не соединена.

    ЧТО ЭТОТ ИСТОЧНИК ВИДИТ, ЧЕГО НЕ ВИДЯТ ДВА ДРУГИХ. Судья говорит о
    помещениях и оболочке, план — о совпадениях в срезе XY. Ни один из них не
    отвечает на «стоит ли эта колонна на чём-нибудь»: это отношение МЕЖДУ
    этажами, то есть арность N по вертикали.

    ГРАНИЦА, НАЗВАННАЯ ЧИСЛОМ: допуск края плиты 300 мм и досягаемость балки
    1500 мм живут в `coherence` и выбраны там; здесь они не переспрашиваются и
    не дублируются. Программа без плит даёт «вне плиты» ВСЕМ — это верно и
    бесполезно, поэтому при нуле плит источник молчит С ПРИЧИНОЙ, а не заливает
    сводку.
    """
    out: list[Observation] = []
    try:
        from kukai.design import coherence as _co
    except Exception as exc:  # noqa: BLE001
        return out, {"coherence": "%s: %s" % (type(exc).__name__, str(exc)[:120])}

    try:
        elements = _co.flatten(list(programs))
        report = _co.check(elements)
    except Exception as exc:  # noqa: BLE001 — отказ источника ЭТО ДАННЫЕ
        return out, {"coherence": "%s: %s" % (type(exc).__name__, str(exc)[:140])}

    if not int(report.get("плит") or 0):
        # ВЫРОЖДЕННЫЙ ВХОД, НАЗВАННЫЙ ВСЛУХ. Без плит «ни на чём не стоит»
        # верно для КАЖДОГО элемента и не отличает здоровое от битого —
        # зелёный (здесь красный) без акта различения.
        return out, {"coherence": "плит в программе нет: «вне плиты» было бы "
                                  "верно для всех и не различало бы ничего"}

    for key, code in _COHERENCE_CODES:
        addresses = [str(a) for a in (report.get(key) or ()) if a]
        if addresses:
            out.append(Observation(code, address=tuple(addresses[:ADDRESS_CAP]),
                                   address_total=len(addresses)))
    return out, {}


def _source_name(witness: Any, verdict: Any) -> str:
    """«program» или «parse» — СО СЛОВ СВИДЕТЕЛЯ, а не по имени двери.

    Спрашивается свидетель, а не вызывающий: `observe_verdict` — открытая
    дверь, и вердикт с пути PARSE могут подать в неё напрямую. Решать по тому,
    какая функция была позвана, значило бы утверждать источник в одном месте и
    читать в другом.
    """
    for holder in (witness, verdict):
        raw = getattr(holder, "source", None)
        if raw is not None:
            return str(getattr(raw, "value", raw) or "program")
    return "program"


def observe_l0(document: Any, *, building_id: str | None = None) -> AssemblyView:
    """Наблюдения о ПОСТРОЕННОМ здании — ТЕМИ ЖЕ правилами.

    🔴 ВТОРАЯ ПОЛОВИНА ЦЕЛОСТНОСТИ. Один вход правил объявлен ТИПОМ
    (`ModelSource`), но жила только ветка `PROGRAM`: продукт судил ЗАМЫСЕЛ и
    называл это проверкой РЕЗУЛЬТАТА. Здесь зовётся `spatial_model_from_l0`
    (`ModelSource.PARSE`) и тот же `check_design` — ни одного нового правила, ни
    одной новой геометрии. Отличается ровно источник модели, и `source` в ответе
    это говорит.

    ФОРМА ВЫЗОВА — ЧАСТЬ КОНТРАКТА, И ОНА СТОИЛА ЛОЖНОГО ВЫВОДА.
    `L0JSONLReader.metadata()` отдаёт ШАПКУ: уровни, оси, помещения; `elements`
    в ней пуст по построению. Скормив шапку, получаешь «стен 0» на здании, где
    их 695, — и это читается как неспособность ветки читать стены. Сюда
    передаётся ДОКУМЕНТ ЦЕЛИКОМ (шапка плюс `iter_elements()`); проверить
    здание целиком можно прибором `tools/address_spine.py`.

    ЧЕГО ЭТА ДВЕРЬ НЕ ДЕЛАЕТ. Она не перечитывает Ревит — она судит УЖЕ
    прочитанный L0. Замкнуть петлю «записал → перечитал → судил» может только
    живой мост, и это отдельная работа с отдельной ценой хода.
    """
    asked = ("design_check",)
    try:
        from kukai.ir import design_check as _dc
        model, witness = _dc.spatial_model_from_l0(
            document, building_id=building_id)
        verdict = _dc.check_design(model, witness)
    except Exception as exc:  # noqa: BLE001 — отказ судьи ЭТО ДАННЫЕ
        return AssemblyView(
            observations=(),
            silent_sources={"design_check": "%s: %s"
                            % (type(exc).__name__, str(exc)[:160])},
            sources_asked=asked, source="parse", address_space="element_id")

    walls = [str(getattr(wall, "id", "")) for wall in (model.walls or ())]
    view = observe_verdict(verdict, [w for w in walls if w])
    # Адреса здесь — `element_id` Ревита, а не id операций: судится построенное.
    return AssemblyView(
        observations=view.observations, silent_sources=view.silent_sources,
        sources_asked=view.sources_asked, source=view.source,
        address_space="element_id")


def observe_verdict(verdict: Any, wall_ids: Sequence[str], *,
                    programs: Sequence[Any] = ()) -> AssemblyView:
    """То же самое, но по УЖЕ ПОСЧИТАННОМУ вердикту.

    🔴 ЗАЧЕМ ОТДЕЛЬНАЯ ДВЕРЬ. `live.verdict.judge` вызывает того же судью на
    каждом ходе и выбрасывает объект вердикта в прозу. Позвать `check_bundle`
    ещё раз ради сводки значило бы завести ВТОРОЕ СУЖДЕНИЕ ОБ ОДНОМ И ТОМ ЖЕ —
    и оплатить его дважды (замер шапки `serving`: ~0.4 мс на операцию), и
    получить два ответа, которым нечем совпадать. Здесь читается готовое.
    """
    silent: dict[str, str] = {}
    out: list[Observation] = []
    walls = [str(w) for w in wall_ids]
    # ИМЯ ЗДАНИЯ — У ВЕРДИКТА, А НЕ У НАС. Сравнение с нашей константой было
    # верно ровно на нашем пути вызова и протекло `HAB000` в наблюдения, едва
    # сводку позвал `live.verdict` со своим именем здания (живой замер 15.08).
    building_id = str(getattr(verdict, "building_id", "") or BUILDING_ID)

    witness = getattr(verdict, "witness", None)
    # Полное число адресов едет вместе с показанными: на программе из четырёх
    # стен это одно и то же, на перечитанном здании из 690 — нет.
    shown, total = tuple(walls[:ADDRESS_CAP]), len(walls)

    # 🔴 СПРОСИТЬ СВИДЕТЕЛЯ, ОТВЕЧАЛ ЛИ ОН НА ЭТОТ ВОПРОС, А НЕ ЧИТАТЬ ЧИСЛО.
    # `partition_faces` считает ТОЛЬКО `spatial_model_from_program`: на пути
    # PARSE разбиение не строится намеренно — контуры помещений берутся такими,
    # какими их вернул Revit, и пересчитывать их худшей копией нельзя. Значит на
    # разборе поле равно нулю ПО ПОСТРОЕНИЮ.
    #
    # Первая редакция читала ноль как ответ и выдавала `enclosure_none` на
    # здании, где 107 помещений из 120 несут измеренный контур (живой замер
    # `sob62_r23_v5`, 15.08). Это молчаливо-неверное наблюдение — ровно тот
    # исход, против которого написан весь компилятор, и поймано оно не выводом,
    # а вопросом «а считает ли прибор эту величину на этом входе».
    source_name = _source_name(witness, verdict)
    if source_name == "program":
        faces = int(getattr(witness, "partition_faces", 0) or 0)
        if faces > 0:
            out.append(Observation("enclosure_ok", address=shown,
                                   address_total=total,
                                   number=float(faces), unit="граней"))
        else:
            out.append(Observation("enclosure_none", address=shown,
                                   address_total=total))
    else:
        silent["design_check:enclosure"] = (
            "разбиение на этом пути не строится: контуры помещений взяты у "
            "Revit, и замкнутость отвечается ими, а не нашим разбиением")

    # HAB-нарушения приезжают СВОИМИ кодами и СВОИМИ адресами (`refs`), потому
    # что и то и другое у них уже есть. Наше дело — не переименовывать.
    report = getattr(verdict, "report", None)
    for bucket in ("blocking", "warnings"):
        for violation in list(getattr(report, bucket, ()) or ()):
            rule = str(getattr(violation, "rule_id", "?"))
            refs = tuple(str(r) for r in (getattr(violation, "refs", ()) or ()))
            if not refs or refs == (building_id,):
                # 🔴 ПРАВИЛО, АДРЕСОВАННОЕ ЗДАНИЮ ЦЕЛИКОМ, — ЭТО МОЛЧАНИЕ С
                # ПРИЧИНОЙ, А НЕ НАБЛЮДЕНИЕ. Живой случай: `HAB000` («в модели
                # нет помещений») на программе из одних стен. Оно верно и
                # ничего не говорит о СБОРКЕ — оно говорит, что судить было
                # нечем. Положить его в наблюдения значило бы отдать модели
                # адрес `(сборка)`, которым нельзя действовать, — против
                # собственного закона адреса этого модуля.
                silent.setdefault(
                    "design_check:" + rule,
                    str(getattr(violation, "msg", ""))[:140] or "без сообщения")
                continue
            out.append(Observation("hab:" + rule, address=refs))

    asked = ["design_check"]
    if programs:
        # ВТОРОЙ ИСТОЧНИК СПРАШИВАЕТСЯ ТОЛЬКО ТАМ, ГДЕ ЕСТЬ ЧТО СПРОСИТЬ.
        # `preview` читает ПРОГРАММУ; на пути PARSE её нет, и молча подставить
        # туда пустоту значило бы сказать «аномалий нет» вместо «не спрашивали».
        asked.extend(("preview", "coherence", "units"))
        anomalies, preview_silence = observe_plan_anomalies(programs)
        out.extend(anomalies)
        silent.update(preview_silence)
        loose, coherence_silence = observe_coherence(programs)
        out.extend(loose)
        silent.update(coherence_silence)
        # ЧЕТВЁРТЫЙ ИСТОЧНИК — ЕДИНИЦЫ ЗАМЫСЛА, и он единственный, кто читает
        # НАБОР. Три предыдущих судят элемент (замкнутость по стенам, аномалия
        # плана, опора конструктива); этот отвечает на вопрос, который на
        # арности 1 не ставится вовсе: «читается ли написанное так, как автор
        # объявил». Стоит здесь, а не отдельной дверью, потому что живой путь
        # уже зовёт `observe_verdict` с `programs` (`live.verdict._with_assembly`)
        # — новая дверь потребовала бы врезки в чужой файл ради того же вызова.
        unit_obs, unit_silence = observe_units(programs)
        out.extend(unit_obs)
        silent.update(unit_silence)

    return AssemblyView(observations=tuple(out), silent_sources=silent,
                        sources_asked=tuple(asked), source=source_name)


#: Потолок дайджеста. Замерен по читателю, а не выбран: историю сворачивает
#: `chat_helpers._summarize_tool_result`, и он оставляет строку верхнего уровня
#: ЦЕЛИКОМ ровно до 120 символов, а длиннее — режет с многоточием. Списки и
#: словари заменяются на «<N элем. — свёрнуто>» без остатка.
DIGEST_LIMIT = 120

#: Сколько адресов показываем у одного наблюдения. Четыре — потому что
#: четырёхстенная коробка это самый частый предмет разговора, и обрезать её на
#: третьей стене значит потерять именно ту, которой не хватило.
DIGEST_ADDRESSES = 4


def digest(view: "AssemblyView", limit: int = DIGEST_LIMIT) -> str:
    """Плоская строка, ПЕРЕЖИВАЮЩАЯ сворачивание истории.

    🔴 ЗАЧЕМ ОТДЕЛЬНАЯ ФОРМА, ЕСЛИ СТРУКТУРА УЖЕ ЕСТЬ. Восприятие, которое
    модель не может ВСПОМНИТЬ, — не петля. Структурная сводка доезжает до
    модели в пределах хода (потолок 50 000), но в историю сохраняется 5 000, а
    дальше тридцати сообщений `_summarize_tool_result` заменяет КАЖДЫЙ словарь
    и список на «свёрнуто». От квитанции остаются только скаляры верхнего
    уровня — и дайджест написан так, чтобы быть одним из них.

    НИКОГДА НЕ ВЫГЛЯДИТ ПОЛНЫМ, БУДУЧИ УСЕЧЁННЫМ. Непоказанные наблюдения
    считаются в хвосте `+N`, молчащие источники — в `?K`. Строка, которая
    молча обрывается, хуже отсутствующей: по ней принимают решение как по
    полной (тот же довод, по которому история не отдаёт обрезанный JSON).
    """
    if not view.observations and not view.silent_sources:
        return "сборка: не измерена"

    head = "сборка: "
    parts: list[str] = []
    shown = 0
    for obs in view.observations:
        addrs = list(obs.address[:DIGEST_ADDRESSES])
        tail = "+%d" % (len(obs.address) - len(addrs)) if len(obs.address) > len(addrs) else ""
        piece = "%s@%s%s" % (obs.code, ",".join(addrs), tail)
        if obs.of_unit:
            # АДРЕС ЕДИНИЦЫ ЕДЕТ И В ПЛОСКУЮ СТРОКУ. Дайджест — единственное,
            # что переживает сворачивание истории; наблюдение об арности N,
            # потерявшее там свою единицу, возвращает модель к чтению
            # собственной программы поэлементно, то есть ровно к тому, от
            # чего единица и заводилась.
            piece += "/%s" % obs.of_unit
        if obs.number is not None:
            piece += "=%g" % obs.number
        candidate = head + "; ".join(parts + [piece])
        # хвост считаем ЗАРАНЕЕ: строка обязана уместиться ВМЕСТЕ с ним
        reserve = len(" +%d" % (len(view.observations) - shown - 1)) + \
            (len(" ?%d" % len(view.silent_sources)) if view.silent_sources else 0)
        if len(candidate) + reserve > limit:
            break
        parts.append(piece)
        shown += 1

    out = head + "; ".join(parts) if parts else head.strip()
    hidden = len(view.observations) - shown
    if hidden > 0:
        out += " +%d" % hidden
    if view.silent_sources:
        out += " ?%d" % len(view.silent_sources)
    return out
