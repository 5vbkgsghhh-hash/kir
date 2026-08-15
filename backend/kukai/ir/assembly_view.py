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
)

#: Приставка кодов, приезжающих из чужого закрытого реестра. Такой код
#: пропускается без проверки по `OBSERVATION_CODES`, и это НАЗВАНО: его
#: полнота держится ТАМ, а дублировать реестр правил здесь значит развести
#: два списка, которые обязаны совпадать и ничем не связаны.
#: `preview:*` — коды аномалий плана (`preview.AnomalyReason`), тоже свой
#: закрытый реестр, тоже приезжают КАК ЕСТЬ, по той же причине.
FOREIGN_CODE_PREFIXES: tuple[str, ...] = ("hab:", "preview:")


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
    unit: str = ""
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
        asked.extend(("preview", "coherence"))
        anomalies, preview_silence = observe_plan_anomalies(programs)
        out.extend(anomalies)
        silent.update(preview_silence)
        loose, coherence_silence = observe_coherence(programs)
        out.extend(loose)
        silent.update(coherence_silence)

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
