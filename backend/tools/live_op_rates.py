"""Живая частота по ОПЕРАЦИЯМ — с честным ответом «кто именно отказал».

ЗАЧЕМ ЭТО ОТДЕЛЬНЫЙ ИНСТРУМЕНТ
-------------------------------
Число «оп X работает в N% случаев» — первое, что спросят снаружи, и первое,
чем сами меряем готовность. До 31.07 оно считалось приписыванием провала ВСЕЙ
программе: если в программе были `create_wall` и `create_door`, а отказала
дверь, провал записывался обоим. Замер по корпусу дал `create_wall` 64.2% —
при том, что стена в тех прогонах построилась, и это видно в самой строке
корпуса, в поле `witness.geometry_ok`.

ЧТО ЭТОТ ФАЙЛ ГОВОРИЛ О СЕБЕ И ЧТО ДЕЛАЛ (замер 09.08.2026)
------------------------------------------------------------
Докстрока обещала четыре корзины и точное приписывание по идентификаторам —
и `tally()` их действительно считал. Ложь была не в арифметике, а в ОХВАТЕ, и
её не видно, пока не сложишь два числа из отчёта:

  * точная таблица брала **201 живую строку из 1215**, потому что `classify`
    отказывался от строки, если хоть одна операция без `id`. Но у ЗЕЛЁНОЙ
    строки идентификатор не нужен вовсе: программа закоммичена ⇒ построились
    ВСЕ её операции, нарушений нет и приписывать нечего. Так из точной
    таблицы выпали **862 зелёные живые строки** — весь построенный объём,
    оставив `create_wall` 16 построенных там, где их 135;
  * оставшиеся 152 красные строки без идентификаторов — единственные, которые
    приписать действительно нечем. Ровно столько же («152 из 204») не смог
    разобрать и человек, разбиравший корпус вручную. Совпадение не случайно:
    это одна и та же граница знания, и теперь у неё есть своя корзина;
  * `committed = bool(row["ok"])` растаптывал закрытый контракт v2. У пяти
    строк `outcome.execution == "committed"`, `witness == "satisfied"`, а
    `ok == false` — потому что независимая ПРИЁМКА оказалась `inconclusive`
    (`partial_blind_scope`). Программа построилась; инструмент записывал её
    операции в «программа упала». Обратный случай там же: 40 строк
    `execution == "unconfirmed"` — про них не известно НИЧЕГО, а `bool(ok)`
    делал вид, что известно;
  * «одна операция в программе» означало одно уникальное ИМЯ, а не один
    экземпляр: из 744 таких строк одноопных 628. Хуже того, счёт шёл по
    СТРОКАМ, а не по экземплярам, так что программа из шести балок давала
    одну единицу свидетельства;
  * 52 строки усечены (`ops_truncated`), и в них спрятано **11 022
    операции** — все зелёные, все 30–31.07, все по опам `place_family`,
    `create_pipe`, `create_duct`, `create_text`. `tally()` не смотрел на
    признак усечения вовсе (на него смотрел только `tally_solo`).

ЛЕСТНИЦА ПРИПИСЫВАНИЯ — ТРИ СТУПЕНИ, И НИ ОДНОЙ ДОГАДКИ
--------------------------------------------------------
Приписывание идёт по самой сильной ступени, которую позволяет строка. Ступень
называется в отчёте, чтобы число нельзя было прочитать сильнее, чем оно есть.

  A. ИДЕНТИФИКАТОРЫ — у всех операций строки есть `id`, нарушения адресованы
     `id`. Приписывание поэкземплярное и точное;
  B. ОДНО ИМЯ — идентификаторов нет, но ВСЕ операции программы носят одно имя.
     Тогда какой бы экземпляр ни отказал, отказало это ИМЯ. Экземпляр не
     известен, имя известно точно: `k` обвинённых (по числу разных `id` в
     нарушениях), остальные — попутно откачены;
  C. НИ ТОГО НИ ДРУГОГО — приписать нечем. Строка целиком уходит в
     НЕПРИПИСЫВАЕМОЕ, поимённо, и НИЧЕГО не размазывается по операциям.

Ступень C — не дырка в инструменте, а факт о корпусе, и он обязан быть виден.
Затолкать эти 152 строки в корзину «обвинена» значит обменять правду на
красивое число: именно так `create_wall` и получал 30 отказов при четырёх
своих.

КОРЗИНЫ
--------
  ПОСТРОЕНО      — программа закоммичена, операция не названа в нарушениях;
  ОБВИНЕНА       — операция названа в нарушении (её собственное постусловие
                   не сошлось). Единственная корзина, которая является
                   провалом ОПЕРАЦИИ;
  ЛОЖНЫЙ СВИДЕТЕЛЬ — операция названа в нарушении, но НАРУШЕНИЕ БЫЛО НАШЕ:
                   постусловие требовало того, чего Revit не обещает, и его
                   сняли коммитом. Не провал операции и не успех — отдельный
                   факт, с датой починки (см. `WITNESS_DEFECTS`);
  ПОПУТНО ОТКАЧЕНА — программа откатилась из-за ЧУЖОГО нарушения. Операция
                   не виновата и не построена;
  ОТКАЗ REVIT    — типизированный рантайм-отказ самого Revit (X001/X002/
                   X005/X006 и, с 09.08, X009 — отказ guard'а эмиттера в
                   рантайме), приписан только когда программа одноимённая;
  ДРЕЙФ МОДЕЛИ   — X003: элемент/тип исчез между grounding и исполнением. Не
                   провал операции: цели не стало под руками. Корзина
                   появилась вместе с разделением X003 (см. ниже) и НЕ
                   применяется к строкам, записанным до него;
  ДЕФЕКТ КОМПИЛЯТОРА — наш собственный закон нарушен нами (X008 — квитанция
                   пишущего опа без идентичности; C001 — эмитированный C# не
                   собрался);
  НЕПРИПИСЫВАЕМО — строка не поддалась ни одной ступени, ИЛИ код отказа по
                   построению не называет виновного (см. ниже).

Частота операции = ПОСТРОЕНО / (ПОСТРОЕНО + ОБВИНЕНА). Ни одна другая корзина
в знаменатель не входит, и каждая печатается рядом — их размер сам по себе
факт о системе.

ТРИ КОДА, КОТОРЫЕ НЕ НАЗЫВАЛИ ВИНОВНОГО ПО ПОСТРОЕНИЮ — И ЧТО С НИМИ СТАЛО
--------------------------------------------------------------------------
  KIR-X999 — «неклассифицированный рантайм-отказ»; причина живёт в `detail`.
             133 строки корпуса;
  KIR-X003 — `stale_or_failed` НАМЕРЕННО покрывал два разных мира: «элемент
             исчез между grounding и исполнением» и «оп отказан в рантайме
             Revit» (`serving._translate_runtime`). Различала их только
             подпись внутри `detail`. 43 строки корпуса;
  KIR-X007 — исполнение не подтверждено за таймаут. Про модель не известно
             ничего, и это ЕДИНСТВЕННЫЙ честный ответ — код остаётся
             неприписываемым НАВСЕГДА, и это не дефект.

Первые два чинятся не здесь, а у источника, и оба конца уже сделаны:
  * `witness_feed` пишет `diag_op_id` (кто), а с 09.08 ещё и `diag_code` /
    `diag_field` / `diag_message` / `diag_detail` (что) — всё это диагностика
    несла всегда, а телеметрия выбрасывала;
  * X003 РАЗДЕЛЁН: дрейф остался X003, типизированный отказ рантайма получил
    собственный KIR-X009. Один код перестал быть двумя мирами.

СТАРЫЕ СТРОКИ ОТ ЭТОГО НЕ ПРОЗРЕВАЮТ, И ПРИТВОРЯТЬСЯ НЕЛЬЗЯ. Строка, записанная
до 09.08, несёт X003 в СТАРОМ, двусмысленном значении: разложить её по новым
корзинам значило бы задним числом угадать, каким из двух миров она была.
Признак новизны — поле `refusal_cause`, которое новая запись ставит на КАЖДОЙ
не-зелёной строке; по нему `_cause_bucket` и различает «строка называет свою
причину» и «строка молчит, и это факт о корпусе, а не о коде».

ПОЧЕМУ НИЖНЯЯ ГРАНИЦА, А НЕ ПРОЦЕНТ
------------------------------------
`create_grid` в корпусе — один прогон, один успех. Написать «100%» значит
соврать интонацией: одно наблюдение не отличает оп с частотой 99% от опа с
частотой 40%. Поэтому рядом с долей печатается нижняя граница Вильсона (95%
доверия) — то число, ниже которого частота почти наверняка НЕ лежит. Для
одного успеха из одного она равна 20.7%, и это честный ответ «мы не знаем».
Заявление «оп выше 95%» имеет право звучать только когда 95% перешагнула
ГРАНИЦА, а не доля.

Отсюда цена заявления, и её полезно знать заранее: граница переходит 95% на
**73 успехах подряд** (замерено `wilson_lower(n, n)`, не выведено из памяти).
Шестьдесят дают 94.0%, сто — 96.3%.

КОРПУС ДЕРЖИТ ПРОШЛОЕ, А НЕ НАСТОЯЩЕЕ — ГЛАВНАЯ ЛОВУШКА ЭТОГО ЧИСЛА
------------------------------------------------------------------
Журнал дописывается и никогда не переписывается. Значит частота, посчитанная
по всему корпусу, смешивает поведение ДО починки и ПОСЛЕ неё — и тем ниже,
чем усерднее чинили. `--since` режет корпус по дате; отчёт всегда печатает
границы времени, чтобы «за месяц» нельзя было прочитать как «сейчас».

Корзина ЛОЖНЫЙ СВИДЕТЕЛЬ — это та же ловушка, но названная поимённо вместо
отсечки по дате: у каждой записи `WITNESS_DEFECTS` стоит коммит, снявший
свидетеля, и строки ПОСЛЕ этого коммита в корзину уже не попадают.

ОГОВОРКА, КОТОРУЮ ГРАНИЦА НЕ УЧИТЫВАЕТ. Вильсон считает испытания
независимыми. Двести пятьдесят стен одного чанка независимы не полностью:
одна модель, один тип, одна транзакция. Они РАЗНЫЕ вызовы API с раздельными
постусловиями — поэтому считаются раздельно, — но разнообразия в них меньше,
чем в двухстах пятидесяти стенах из разных зданий.

ОТКАЗЫ ДО ИСПОЛНЕНИЯ — ВТОРОЙ КОРПУС, ВТОРОЙ ЗНАМЕНАТЕЛЬ
---------------------------------------------------------
Программа, отказанная компилятором, до Revit не доехала и в частоту
построения не входит ни числителем, ни знаменателем. Но на вопрос «почему оп
не построился» она отвечает чаще, чем рантайм. Эти события живут в
`kir_rejections.jsonl` и печатаются ОТДЕЛЬНОЙ таблицей:

  ВЕРНЫЙ ОТКАЗ  — компилятор отказался выбирать за автора и назвал кандидатов
                  (KIR-G102 неоднозначность, KIR-G101 «не найден» с
                  ближайшими, KIR-G104 пустой пул). Это РАБОТА, а не поломка;
  ОШИБКА АВТОРА — программа не прошла разбор/типы/бюджет (P/T/L/E).

До 09.08 различить их было нельзя: `coverage_feed` схлопывал ЛЮБУЮ
диагностику в `VALIDATION_FAILED` и выбрасывал `candidates`. Поэтому у старых
1364 событий кода нет, и класс восстанавливается ПО ТЕКСТУ `detail` —
столбцы помечены «(по тексту)». Новые события несут `diag_code` и
`candidates` и считаются по коду.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys

DEFAULT_CORPUS = pathlib.Path(__file__).resolve().parents[1] / "data" / "telemetry" / "kir_witness.jsonl"
DEFAULT_REJECTIONS = DEFAULT_CORPUS.with_name("kir_rejections.jsonl")

BUILT = "built"
BLAMED = "blamed"
COLLATERAL = "collateral"
WITNESS_DEFECT = "witness_defect"
REVIT_REFUSAL = "revit_refusal"
COMPILER_DEFECT = "compiler_defect"
DRIFT = "drift"
UNATTRIBUTABLE = "unattributable"

#: Корзины отказного корпуса (до исполнения). Отдельный знаменатель.
CORRECT_REFUSAL = "correct_refusal"
AUTHOR_ERROR = "author_error"

BUCKETS = (BUILT, BLAMED, COLLATERAL, WITNESS_DEFECT, REVIT_REFUSAL,
           COMPILER_DEFECT, DRIFT, UNATTRIBUTABLE)

_RU = {
    BUILT: "построено",
    BLAMED: "обвинена",
    COLLATERAL: "попутно откачено",
    WITNESS_DEFECT: "ложный свидетель",
    REVIT_REFUSAL: "отказ Revit",
    COMPILER_DEFECT: "дефект компилятора",
    DRIFT: "дрейф модели",
    UNATTRIBUTABLE: "неприписываемо",
    CORRECT_REFUSAL: "верный отказ",
    AUTHOR_ERROR: "ошибка автора",
}

# ── Причины программного уровня ──────────────────────────────────────────────
#
# Приписываются ОПЕРАЦИИ только на ступени A или B; на ступени C программа
# целиком уходит в неприписываемое. Классификация — по типизированному коду,
# никогда по свободному тексту.
_REVIT_REFUSAL_CODES = {
    "KIR-X001",  # ShortCurveTolerance / нулевое ребро — отказал Revit
    "KIR-X002",  # контуры пересекаются в рантайме
    "KIR-X005",  # транзакция не стартовала/не закоммитилась
    "KIR-X006",  # имя уже занято в документе
    "KIR-X009",  # guard эмиттера отказал в рантайме (не дрейф; текст в строке)
}
_COMPILER_DEFECT_CODES = {
    "KIR-C001",  # наш C# не собрался — территория дефекта компилятора
    "KIR-X008",  # закон переписи: квитанция пишущего опа без идентичности
}
#: Коды, которые НЕ НАЗЫВАЮТ виновного по построению. Догадка здесь была бы
#: ровно тем обманом, против которого весь файл.
#:
#: X003 из этого списка УШЁЛ: он больше не два мира сразу (см. докстроку), и у
#: строки, которая называет свою причину, есть собственная корзина. Но только у
#: НЕЁ — старая строка с тем же кодом остаётся здесь, см. `_LEGACY_X003`.
_OPAQUE_CODES = {
    "KIR-X999": "KIR-X999 — рантайм-отказ неклассифицирован (класс не типизирован; текст причины теперь в самой строке)",
    "KIR-X007": "KIR-X007 — исполнение не подтверждено за таймаут",
}
#: Строка с X003, записанная ДО разделения кода: тогда он значил и дрейф, и
#: любой отказ рантайма. Задним числом выбрать один из миров нечем.
_LEGACY_X003 = ("KIR-X003 до разделения кода — покрывал и дрейф модели, и отказ "
                "рантайма; строка записана без `refusal_cause`, различить нечем")

# ── Ложные свидетели: наши постусловия, требовавшие невозможного ─────────────
#
# КАЖДАЯ ЗАПИСЬ НЕСЁТ КОММИТ, СНЯВШИЙ СВИДЕТЕЛЯ. Без коммита запись не имеет
# права здесь стоять: «это был ложный красный» без артефакта — то самое
# сужение знаменателя, которое инструмент обязан запрещать себе.
#
# `until` — время коммита-починки (UTC). Строка ПОЗЖЕ него в корзину не идёт:
# тот же текст нарушения после починки означает уже настоящий отказ.
WITNESS_DEFECTS = (
    {"pattern": "level binding mismatch",
     "op": "create_beam",
     "until": "2026-07-27T13:23:40",
     "fix": "158fadc9 «свидетель балки требовал того, чего Revit не обещает»",
     "why": "постусловие требовало INSTANCE_REFERENCE_LEVEL_PARAM; Revit выводит "
            "опорный уровень из отметки кривой и такой связи не обещает. "
            "Последний живой отказ 27.07 13:22:47, коммит 13:23:40 — через 53 с"},
    {"pattern": "height mismatch",
     "op": "create_wall",
     "until": "2026-07-31T07:53:31",
     "fix": "11b3c389 «два постусловия, требовавших невозможного»",
     "why": "`height_mm` несёт registry-default 3000мм, `validate()` кладёт его в оп "
            "ДО эмиттера — и свидетель требовал высоту, которую автор не называл, "
            "а под attached top constraint назначает сам Revit"},
    {"pattern": "name mismatch",
     "op": "create_room",
     "until": "2026-08-04T15:27:17",
     "fix": "f570aee2 «приёмка ломалась на кириллице»",
     "why": "`Room.Name` отдаёт «имя + НОМЕР», сравнение с запрошенным именем не "
            "сходилось никогда — верно построенное помещение откатывалось месяцами"},
)


def wilson_lower(successes: int, total: int, z: float = 1.96) -> float:
    """Нижняя граница доли при 95% доверия. Ноль наблюдений → 0.0."""
    if total <= 0:
        return 0.0
    p = successes / total
    denom = 1.0 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, (centre - margin) / denom)


def blamed_map(row: dict) -> dict:
    """`id` → список текстов нарушений. Форма нарушения — `«<id>: текст»`
    (см. `authoring.py`, `__post.Add(oid + ": …")`). Всё, что не разбирается,
    в обвинение НЕ попадает: клевета дороже пропуска."""
    out: dict = collections.defaultdict(list)
    for v in row.get("violations") or []:
        head, sep, tail = str(v).partition(":")
        head = head.strip()
        if head and sep:
            out[head].append(tail.strip())
    return dict(out)


def false_witness(op_name: str, texts, ts: str):
    """Запись `WITNESS_DEFECTS`, покрывающая ВСЕ тексты нарушения, или None.

    «Все», а не «любой»: операция с двумя нарушениями, из которых снят один,
    отказала по второму и остаётся обвинённой."""
    if not texts:
        return None
    hit = None
    for text in texts:
        entry = next((d for d in WITNESS_DEFECTS
                      if d["pattern"] in text and d["op"] == op_name
                      and str(ts)[:19] < d["until"]), None)
        if entry is None:
            return None
        hit = entry
    return hit


def program_state(row: dict) -> tuple[str, str]:
    """→ (состояние программы, чем доказано).

    Закрытый контракт v2 (`outcome`) СИЛЬНЕЕ флага `ok`, и это не стилистика:
    `ok=false` при `execution=committed` — законное состояние (свидетель
    сошёлся, независимая приёмка оказалась `inconclusive`), а `ok=false` при
    `execution=unconfirmed` — незнание, а не провал. Схлопывание в `bool(ok)`
    путало оба с откатом."""
    outcome = row.get("outcome")
    if isinstance(outcome, dict) and outcome.get("execution"):
        execution = str(outcome["execution"])
        if execution in ("committed", "read_completed"):
            return "committed", f"outcome.execution={execution}"
        if execution == "unconfirmed":
            return "unconfirmed", "outcome.execution=unconfirmed"
        return "rolled_back", f"outcome.execution={execution}"
    if row.get("diag_code") == "KIR-X007":
        return "unconfirmed", "diag KIR-X007 (таймаут)"
    if row.get("ok"):
        return "committed", "ok=true"
    witness = row.get("witness")
    if isinstance(witness, dict) and witness.get("committed") is True:
        return "committed", "witness.committed=true"
    return "rolled_back", "ok=false"


def names_its_refusal(row: dict) -> bool:
    """Строка записана уже УМЕЮЩЕЙ называть причину?

    Признак — `refusal_cause`, а не наличие текста: новая запись ставит это
    поле на КАЖДОЙ не-зелёной строке, в том числе когда причина ей не известна
    (`unknown`). Поэтому «поля нет» означает ровно «строка старая», и ни одна
    старая строка не будет разложена по корзинам, появившимся после неё.
    """
    return bool(row.get("refusal_cause"))


def _cause_bucket(row: dict) -> tuple[str, str]:
    """Корзина для операции программы, упавшей БЕЗ пооперационных нарушений."""
    code = str(row.get("diag_code") or "")
    named = names_its_refusal(row)
    if code == "KIR-X003":
        # Дрейф — НЕ провал операции: цель исчезла из модели между grounding и
        # исполнением. Отдельная корзина, а не «обвинена» и не «отказ Revit».
        return (DRIFT, code) if named else (UNATTRIBUTABLE, _LEGACY_X003)
    if code in _REVIT_REFUSAL_CODES:
        return REVIT_REFUSAL, code
    if code in _COMPILER_DEFECT_CODES:
        return COMPILER_DEFECT, code
    if code in _OPAQUE_CODES:
        return UNATTRIBUTABLE, _OPAQUE_CODES[code]
    if code:
        return UNATTRIBUTABLE, f"откат без нарушений, код {code} не разобран"
    if row.get("refusal_cause") == "unknown":
        # НАЗВАННОЕ НЕЗНАНИЕ. Отличается от строки ниже тем, что запись СКАЗАЛА
        # «причина мне не была известна», а не промолчала о ней.
        return UNATTRIBUTABLE, ("причина не была известна в момент записи "
                                "(`refusal_cause: unknown`) — названа, а не пропущена")
    return UNATTRIBUTABLE, "откат без нарушений и без кода (строка молчит о причине)"


def attribute(row: dict) -> tuple[list, str, str | None]:
    """→ (пары «оп, корзина», ступень лестницы, причина неприписываемости).

    Ступень называется всегда — она и есть паспорт числа."""
    ops = [o for o in (row.get("ops") or []) if isinstance(o, dict) and o.get("op")]
    if not ops:
        return [], "—", "нет операций в строке"

    names = {o["op"] for o in ops}
    ids_complete = all(o.get("id") for o in ops)
    step = "A:идентификаторы" if ids_complete else (
        "B:одно имя" if len(names) == 1 else "C:нечем")
    state, _evidence = program_state(row)

    if state == "unconfirmed":
        # Единственный честный ответ: про модель не известно ничего.
        return ([(o["op"], UNATTRIBUTABLE) for o in ops], step,
                "исполнение не подтверждено (unconfirmed/таймаут)")

    blamed = blamed_map(row)
    committed = state == "committed"
    # НЕВИНОВНЫЙ СОСЕД СТОИТ В РАЗНЫХ КОРЗИНАХ, СМОТРЯ ЧТО СТАЛО С ТРАНЗАКЦИЕЙ.
    # Закоммиченная программа (режим `report`, KIR-W004) оставила соседа В
    # МОДЕЛИ — он ПОСТРОЕН. Откаченная не оставила ничего — он ПОПУТНО ОТКАЧЕН.
    # Одна корзина на оба случая была бы либо клеветой, либо ложью.
    innocent = BUILT if committed else COLLATERAL
    # Диагностика рантайма НАЗЫВАЕТ операцию, когда рантайм её сообщил
    # (`serving._translate_runtime` кладёт `op_id`). До 09.08 телеметрия это
    # поле выбрасывала, поэтому в старых строках его нет и быть не может.
    culprit = row.get("diag_op_id")
    outcomes = row.get("op_outcomes") if isinstance(row.get("op_outcomes"), dict) else {}
    refused = {oid for oid, v in outcomes.items() if v == "refused"}

    def _named(op_name: str, texts) -> str:
        return (WITNESS_DEFECT
                if false_witness(op_name, texts, row.get("ts") or "") else BLAMED)

    # Причина программного уровня считается ОДИН раз и едет наверх: строка,
    # хоть один экземпляр которой ушёл в неприписываемое, обязана попасть в
    # поимённый реестр отчёта. Без этого 24 строки ступени C были видны, а
    # сотня строк ступени A с кодом X003/X999 растворялась в колонке.
    cause, cause_why = _cause_bucket(row)
    note = cause_why if cause == UNATTRIBUTABLE else None

    if ids_complete:
        pairs = []
        used_cause = False
        for o in ops:
            texts = blamed.get(o["id"])
            if texts:
                pairs.append((o["op"], _named(o["op"], texts)))
            elif o["id"] in refused:
                pairs.append((o["op"], BLAMED))
            elif blamed or committed:
                pairs.append((o["op"], innocent))
            elif culprit:
                if o["id"] == culprit:
                    pairs.append((o["op"], cause))
                    used_cause = True
                else:
                    pairs.append((o["op"], COLLATERAL))
            else:
                pairs.append((o["op"], cause))
                used_cause = True
        return pairs, step, (note if used_cause else None)

    if len(names) == 1:
        # Экземпляр не известен, ИМЯ известно точно: какой бы `id` ни стоял в
        # нарушении, он принадлежит этому имени.
        name = next(iter(names))
        if blamed:
            texts = [t for ts_ in blamed.values() for t in ts_]
            bucket = _named(name, texts)
            n_blamed = min(len(blamed), len(ops))
            pairs = [(name, bucket)] * n_blamed
            pairs += [(name, innocent)] * (len(ops) - n_blamed)
            return pairs, step, None
        if committed:
            return [(name, BUILT) for _ in ops], step, None
        if culprit:
            # Виновный назван диагностикой: один экземпляр этого имени, а не
            # все. Остальные — попутно откачены.
            return ([(name, cause)] + [(name, COLLATERAL)] * (len(ops) - 1),
                    step, note)
        return [(name, cause) for _ in ops], step, note

    # ── ступень C ────────────────────────────────────────────────────────────
    if committed and not blamed and not refused:
        # Закоммиченная программа БЕЗ единого нарушения построила все свои
        # операции — идентификатор для этого не нужен, и требовать его значило
        # выбросить 862 зелёные живые строки корпуса, то есть весь
        # построенный объём.
        return [(o["op"], BUILT) for o in ops], "B:коммит без нарушений", None
    why = ("строка без идентификаторов, имён больше одного — какое из них "
           "названо в нарушении, не восстановить"
           if (blamed or refused) else cause_why)
    return [(o["op"], UNATTRIBUTABLE) for o in ops], step, why


def span(rows) -> tuple[str | None, str | None]:
    """Границы времени корпуса. Печатаются ВСЕГДА: «за месяц» не должно
    читаться как «сейчас»."""
    stamps = sorted(str(r.get("ts")) for r in rows if r.get("ts"))
    return (stamps[0][:19], stamps[-1][:19]) if stamps else (None, None)


def tally(rows, *, live_only: bool = True) -> dict:
    per = collections.defaultdict(collections.Counter)
    skipped = collections.Counter()
    steps = collections.Counter()
    unattributed_rows = collections.Counter()
    truncated_rows = truncated_ops = 0
    seen = considered = 0
    for row in rows:
        seen += 1
        if live_only and not (row.get("duration_ms") or 0) > 0:
            skipped["не доехало до Revit (duration_ms = 0)"] += 1
            continue
        pairs, step, why = attribute(row)
        if not pairs:
            skipped[why or "нечего приписывать"] += 1
            continue
        considered += 1
        steps[step] += 1
        if row.get("ops_truncated"):
            truncated_rows += 1
            truncated_ops += int(row["ops_truncated"])
        if why:
            unattributed_rows[why] += 1
        for name, bucket in pairs:
            per[name][bucket] += 1
    return {"per_op": per, "skipped": skipped, "steps": steps,
            "unattributed_rows": unattributed_rows,
            "truncated_rows": truncated_rows, "truncated_ops": truncated_ops,
            "rows_seen": seen, "rows_considered": considered}


def tally_causes(rows, *, live_only: bool = True) -> dict:
    """ПОЧЕМУ, посчитанное ЗАПРОСОМ к корпусу, а не чтением текста рядом с ним.

    Это и есть цена дефекта, ради которого поля заведены: 04.08 двенадцать
    отказов `create_door` были поделены «компилятор 5 / Revit 11» разбором
    сообщений, живших ВНЕ корпуса, — а сам корпус причин не нёс, и потому тот
    раздел не являлся замером вовсе. Здесь считается только то, что лежит в
    строке; молчащие строки считаются отдельно и НЕ растворяются.
    """
    named: dict = collections.defaultdict(collections.Counter)
    details: dict = collections.defaultdict(collections.Counter)
    silent = collections.Counter()
    for row in rows:
        if live_only and not (row.get("duration_ms") or 0) > 0:
            continue
        if row.get("ok") is True:
            continue
        code = str(row.get("diag_code") or "(кода нет)")
        message = str(row.get("diag_message") or "")
        if not message:
            silent[code] += 1
            continue
        named[(code, str(row.get("diag_field") or ""))][message] += 1
        detail = str(row.get("diag_detail") or "")
        if detail:
            details[(code, str(row.get("diag_field") or ""))][detail] += 1
    return {"named": named, "details": details, "silent": silent}


def render_causes(res: dict) -> str:
    out = ["Причина берётся ИЗ СТРОКИ (`diag_code`/`diag_field`/`diag_message`/",
           "`diag_detail`). Строки без этих полей считаются отдельно — они не",
           "«без причины», они записаны до того, как корпус научился её нести.", ""]
    total_named = sum(sum(c.values()) for c in res["named"].values())
    total_silent = sum(res["silent"].values())
    if not total_named:
        out.append("Строк, называющих свою причину: 0.")
    for (code, field), messages in sorted(
            res["named"].items(), key=lambda kv: -sum(kv[1].values())):
        head = f"{code}" + (f"  поле `{field}`" if field else "")
        out.append(f"  {sum(messages.values()):5}  {head}")
        for message, n in messages.most_common(3):
            out.append(f"         {n:5}  {message}")
        for detail, n in res["details"].get((code, field), collections.Counter()).most_common(2):
            out.append(f"           пример рантайма ({n}): {detail[:120]}")
    out.append("")
    out.append(f"Называют причину: {total_named} строк; молчат: {total_silent}.")
    for code, n in res["silent"].most_common():
        out.append(f"  {n:5}  {code} — поля причины в строке нет")
    return "\n".join(out)


def tally_program_level(rows, *, live_only: bool = True) -> dict:
    """СЫРОЕ приписывание: провал программы записан КАЖДОМУ уникальному ИМЕНИ.

    Оставлено НАМЕРЕННО и печатается рядом — чтобы разницу с честной таблицей
    можно было увидеть, а не поверить на слово. Частотой операции НЕ является
    ни при каких условиях: `create_wall` читается здесь 62.0% при четырёх
    собственных отказах."""
    per = collections.defaultdict(collections.Counter)
    considered = 0
    for row in rows:
        if live_only and not (row.get("duration_ms") or 0) > 0:
            continue
        names = {o.get("op") for o in (row.get("ops") or [])
                 if isinstance(o, dict) and o.get("op")}
        if not names:
            continue
        considered += 1
        for name in names:
            per[name][BUILT if row.get("ok") else BLAMED] += 1
    return {"per_op": per, "rows_considered": considered}


# ── Отказной корпус ──────────────────────────────────────────────────────────

#: Коды grounding, каждый из которых по построению является ВЕРНЫМ отказом:
#: компилятор не стал выбирать за автора и назвал кандидатов.
_CORRECT_REFUSAL_CODES = {"KIR-G101", "KIR-G102", "KIR-G104"}
#: То же по ТЕКСТУ — для событий до 09.08, у которых `coverage_feed` съел код.
#: Формулировки взяты из `ground.py` дословно, не на слух.
_TEXT_AMBIGUOUS = ("неоднозначен",
                   "несколько вариантов — default невозможен",
                   "после disambiguate_by осталось",
                   "снапшот-пул обрезан коллектором")
_TEXT_NOT_FOUND = ("не найден",)
_TEXT_EMPTY_POOL = ("пусто в модели",)


def classify_rejection(event: dict) -> tuple[str, str]:
    """→ (корзина, чем доказано). Код сильнее текста; текст — только фолбэк."""
    code = str(event.get("diag_code") or "")
    if code:
        if code in _CORRECT_REFUSAL_CODES:
            return CORRECT_REFUSAL, f"код {code}"
        return AUTHOR_ERROR, f"код {code}"
    detail = str(event.get("detail") or "")
    if any(p in detail for p in _TEXT_AMBIGUOUS):
        return CORRECT_REFUSAL, "по тексту: неоднозначность"
    if any(p in detail for p in _TEXT_EMPTY_POOL):
        return CORRECT_REFUSAL, "по тексту: пустой пул"
    if any(p in detail for p in _TEXT_NOT_FOUND):
        return CORRECT_REFUSAL, "по тексту: имя не найдено"
    return AUTHOR_ERROR, "по тексту: разбор/типы/бюджет"


def tally_rejections(events) -> dict:
    per = collections.defaultdict(collections.Counter)
    proof = collections.Counter()
    by_code = collections.Counter()
    for e in events:
        bucket, how = classify_rejection(e)
        per[e.get("op_requested") or "(оп не назван)"][bucket] += 1
        proof[how] += 1
        by_code[str(e.get("diag_code") or "(кода нет — до 09.08)")] += 1
    return {"per_op": per, "proof": proof, "by_code": by_code,
            "events": sum(proof.values())}


# A rejection journal has three different units.  Lines measure diagnostic
# volume, attempts measure compiler/serving invocations, and turns measure
# user-visible requests.  They must remain separate: query_fingerprint groups
# equal text only and is deliberately not an identity.
CLASS_SELECTOR = "селектор (пул/имя/пустота)"
CLASS_BUDGET = "бюджет программы (L001)"
CLASS_COVERAGE = "вне покрытия (kind/op)"
CLASS_REF = "ссылка ref"
CLASS_CERTIFICATE = "сертификат перевода"
CLASS_ACCEPTANCE = "независимая приёмка"
CLASS_OTHER = "форма/типы/прочее"

_BUDGET_TEXT = "слишком много опов"
_REF_TEXT = "не указывает на более ранний оп"
_COVERAGE_TEXT = ("неизвестный kind", "неизвестный op")


def classify_rejection_class(event: dict) -> str:
    """Coarse repair class; typed code wins over legacy message text."""
    stage = str(event.get("stage") or "")
    code = str(event.get("diag_code") or "")
    detail = str(event.get("detail") or "")
    if stage == "translation_certificate" or code.startswith("KIR-R"):
        return CLASS_CERTIFICATE
    if stage.startswith("acceptance_") or code.startswith("KIR-A"):
        return CLASS_ACCEPTANCE
    if code in _CORRECT_REFUSAL_CODES or any(
            part in detail
            for part in _TEXT_AMBIGUOUS + _TEXT_NOT_FOUND + _TEXT_EMPTY_POOL):
        return CLASS_SELECTOR
    if code == "KIR-L001" or _BUDGET_TEXT in detail:
        return CLASS_BUDGET
    if code == "KIR-G001" or detail.startswith(_COVERAGE_TEXT):
        return CLASS_COVERAGE
    if _REF_TEXT in detail:
        return CLASS_REF
    return CLASS_OTHER


def _identity_state(event: dict) -> str:
    if event.get("attempt_id"):
        return "explicit"
    if event.get("query_id"):
        # Old query_id values have several incompatible meanings (including a
        # prompt hash).  They are useful as legacy groups, never as attempts.
        return "legacy_no_attempt"
    return "legacy_unknown"


def tally_rejection_units(events) -> dict:
    """Count lines, explicit attempts and explicit turns without inference."""
    lines = collections.Counter()
    attempts = collections.defaultdict(set)
    turns = collections.defaultdict(set)
    actions = collections.defaultdict(set)
    query_fingerprints = collections.defaultdict(set)
    legacy_query_groups = collections.defaultdict(set)
    identity_states = collections.Counter()
    source_lines = collections.Counter()
    source_attempt_sets = collections.defaultdict(set)
    stage_lines = collections.Counter()
    stage_attempt_sets = collections.defaultdict(set)

    all_attempts: set[str] = set()
    all_turns: set[str] = set()
    all_actions: set[str] = set()
    all_fingerprints: set[str] = set()
    all_legacy_groups: set[str] = set()

    for event in events:
        cls = classify_rejection_class(event)
        lines[cls] += 1
        state = _identity_state(event)
        identity_states[state] += 1

        source = str(event.get("source_kind") or (
            "legacy_unknown" if "source_kind" not in event else "unknown"))
        source_lines[source] += 1
        stage = str(event.get("stage") or (
            "legacy_unknown" if "stage" not in event else "unknown"))
        stage_lines[stage] += 1

        attempt_id = str(event.get("attempt_id") or "")
        if attempt_id:
            attempts[cls].add(attempt_id)
            all_attempts.add(attempt_id)
            source_attempt_sets[source].add(attempt_id)
            stage_attempt_sets[stage].add(attempt_id)

        turn_id = str(event.get("turn_id") or "")
        if turn_id:
            turns[cls].add(turn_id)
            all_turns.add(turn_id)

        action_id = str(event.get("action_id") or "")
        if action_id:
            actions[cls].add(action_id)
            all_actions.add(action_id)

        fingerprint = str(event.get("query_fingerprint") or "")
        if fingerprint:
            query_fingerprints[cls].add(fingerprint)
            all_fingerprints.add(fingerprint)

        if state == "legacy_no_attempt":
            legacy = str(event.get("query_id"))
            legacy_query_groups[cls].add(legacy)
            all_legacy_groups.add(legacy)

    return {
        "lines": lines,
        "attempts": attempts,
        "turns": turns,
        "actions": actions,
        "query_fingerprints": query_fingerprints,
        "legacy_query_groups": legacy_query_groups,
        "identity_states": identity_states,
        "source_lines": source_lines,
        "source_attempts": collections.Counter({
            key: len(value) for key, value in source_attempt_sets.items()}),
        "stage_lines": stage_lines,
        "stage_attempts": collections.Counter({
            key: len(value) for key, value in stage_attempt_sets.items()}),
        "lines_total": sum(lines.values()),
        "attempts_total": len(all_attempts),
        "turns_total": len(all_turns),
        "actions_total": len(all_actions),
        "query_fingerprints_total": len(all_fingerprints),
        "legacy_query_groups_total": len(all_legacy_groups),
    }


def render_rejection_units(units: dict) -> str:
    """Render every denominator beside its name; never promote legacy IDs."""
    out = [
        "Единицы: строки = объём диагностик; попытки = отдельные вызовы; "
        "ходы = реальные turn_id.",
        "query_fingerprint группирует одинаковый текст и не является "
        "личностью попытки.",
        "",
        f"{'класс причины':31} {'строк':>7} {'попыток':>9} {'ходов':>7}",
        "-" * 60,
    ]
    classes = sorted(
        units["lines"],
        key=lambda cls: (-len(units["attempts"][cls]),
                         -units["lines"][cls], cls),
    )
    for cls in classes:
        out.append(
            f"{cls:31} {units['lines'][cls]:7} "
            f"{len(units['attempts'][cls]):9} {len(units['turns'][cls]):7}")
    out.extend([
        "",
        f"ВСЕГО: {units['lines_total']} строк, "
        f"{units['attempts_total']} явных попыток, "
        f"{units['turns_total']} явных ходов, "
        f"{units['actions_total']} явных действий.",
        f"Старых query_id-групп без attempt_id: "
        f"{units['legacy_query_groups_total']} — это legacy-группы, не попытки.",
        "Идентичность строк: " + ", ".join(
            f"{key}={value}" for key, value in
            sorted(units["identity_states"].items())),
        "Источники (строки/явные попытки): " + ", ".join(
            f"{key}={value}/{units['source_attempts'][key]}"
            for key, value in sorted(units["source_lines"].items())),
        "Стадии (строки/явные попытки): " + ", ".join(
            f"{key}={value}/{units['stage_attempts'][key]}"
            for key, value in sorted(units["stage_lines"].items())),
    ])
    return "\n".join(out)


def window_rows(rows: list[dict], *, since: str | None = None,
                until: str | None = None) -> list[dict]:
    """Apply a half-open timestamp window [since, until)."""
    return [
        row for row in rows
        if (not since or str(row.get("ts", "")) >= since)
        and (not until or str(row.get("ts", "")) < until)
    ]


# ── Отчёт ────────────────────────────────────────────────────────────────────

def report(res: dict, *, min_runs: int) -> dict:
    rows = []
    for name, c in res["per_op"].items():
        built, blamed = c[BUILT], c[BLAMED]
        judged = built + blamed
        row = {"op": name, "judged": judged,
               "rate": (built / judged) if judged else None,
               "lower95": wilson_lower(built, judged) if judged else None,
               "enough": judged >= min_runs}
        row.update({b: c[b] for b in BUCKETS})
        rows.append(row)
    rows.sort(key=lambda r: (r["lower95"] if r["lower95"] is not None else -1.0,
                             r["judged"]))
    out = {"ops": rows, "min_runs": min_runs,
           "rows_considered": res["rows_considered"]}
    for key in ("rows_seen", "steps", "unattributed_rows",
                "truncated_rows", "truncated_ops"):
        if key in res:
            out[key] = dict(res[key]) if isinstance(res[key], collections.Counter) else res[key]
    out["skipped"] = dict(res.get("skipped") or {})
    return out


_WIDE_HEAD = (f"{'операция':26} {'постр':>6} {'обвин':>6} {'доля':>7} {'ниж.95':>7}"
              f"  {'попут':>6} {'лж.свид':>7} {'Revit':>6} {'компил':>6}"
              f" {'дрейф':>6} {'неприп':>7}")


def render(rep: dict, *, wide: bool = True) -> str:
    out = []
    out.append(f"Причислено строк: {rep['rows_considered']}"
               + (f" из {rep['rows_seen']}" if rep.get("rows_seen") else ""))
    for why, n in sorted(rep.get("skipped", {}).items(), key=lambda kv: -kv[1]):
        out.append(f"  не причислено {n:5}  — {why}")
    if rep.get("steps"):
        out.append("  ступень приписывания: "
                   + ", ".join(f"{k} — {v}" for k, v in
                               sorted(rep["steps"].items(), key=lambda kv: -kv[1])))
    if rep.get("truncated_rows"):
        out.append(f"  ВЫБОРКА: {rep['truncated_rows']} строк усечены "
                   f"(`ops_truncated`) и скрывают {rep['truncated_ops']} операций — "
                   f"по ним считаются только записанные; это недобор свидетельств, "
                   f"не перекос доли")
    for why, n in sorted(rep.get("unattributed_rows", {}).items(), key=lambda kv: -kv[1]):
        out.append(f"  неприписываемо {n:5} строк — {why}")
    out.append("")
    out.append(_WIDE_HEAD if wide else
               f"{'операция':26} {'постр':>6} {'обвин':>6} {'доля':>7} {'ниж.95':>7}")
    out.append("-" * (len(_WIDE_HEAD) if wide else 62))
    for r in rep["ops"]:
        if r["judged"]:
            rate = f"{100*r['rate']:6.1f}%"
            low = f"{100*r['lower95']:6.1f}%"
            mark = "" if r["enough"] else "  ← мало прогонов"
        else:
            rate = low = "      —"
            mark = "  ← ни одного вердикта"
        line = f"{r['op']:26} {r[BUILT]:6} {r[BLAMED]:6} {rate} {low}"
        if wide:
            line += (f"  {r[COLLATERAL]:6} {r[WITNESS_DEFECT]:7} "
                     f"{r[REVIT_REFUSAL]:6} {r[COMPILER_DEFECT]:6} "
                     f"{r[DRIFT]:6} {r[UNATTRIBUTABLE]:7}")
        out.append(line + mark)
    out.append("")
    solid = [r for r in rep["ops"]
             if r["enough"] and r["lower95"] is not None and r["lower95"] >= 0.95]
    out.append(f"Опов с НИЖНЕЙ границей выше 95% при ≥{rep['min_runs']} "
               f"вердиктах: {len(solid)}")
    for r in solid:
        # ДОЛЯ НЕПРИПИСАННОГО ЕДЕТ РЯДОМ С ЗАЯВЛЕНИЕМ, а не в отдельной
        # колонке выше: «create_wall выше 95%» при 192 неприписанных
        # экземплярах из 333 — заявление о 42% экземпляров, и читатель обязан
        # видеть это в той же строке, где берёт число.
        unattr = r[UNATTRIBUTABLE]
        total = r["judged"] + unattr + r[COLLATERAL] + r[WITNESS_DEFECT] \
            + r[REVIT_REFUSAL] + r[COMPILER_DEFECT] + r[DRIFT]
        share = (100.0 * r["judged"] / total) if total else 0.0
        out.append(f"    {r['op']:26} судимо {r['judged']:6} из {total:6} "
                   f"экземпляров ({share:4.1f}%), неприписано {unattr}")
    if solid:
        out.append("    Доля считается ТОЛЬКО по судимым экземплярам "
                   "(построено + обвинена). Неприписанные не входят ни в "
                   "числитель, ни в знаменатель — и не считаются успехом.")
    return "\n".join(out)


def render_rejections(rej: dict) -> str:
    out = [f"Событий отказа: {rej['events']}"]
    for how, n in sorted(rej["proof"].items(), key=lambda kv: -kv[1]):
        out.append(f"  {n:5}  — {how}")
    out.append("")
    out.append(f"{'операция':26} {'верный отказ':>13} {'ошибка автора':>14}")
    out.append("-" * 56)
    rows = sorted(rej["per_op"].items(),
                  key=lambda kv: -(kv[1][CORRECT_REFUSAL] + kv[1][AUTHOR_ERROR]))
    for name, c in rows:
        out.append(f"{name:26} {c[CORRECT_REFUSAL]:13} {c[AUTHOR_ERROR]:14}")
    total_ok = sum(c[CORRECT_REFUSAL] for c in rej["per_op"].values())
    total_err = sum(c[AUTHOR_ERROR] for c in rej["per_op"].values())
    out.append("")
    out.append(f"ВСЕГО: верных отказов {total_ok}, ошибок автора {total_err}. "
               f"Верный отказ — это РАБОТА компилятора, а не его провал.")
    return "\n".join(out)


def render_witness_defects(rep: dict) -> str:
    out = ["Снятые свидетели, из-за которых операция обвинялась зря.",
           "Каждая запись стоит на коммите; строки ПОСЛЕ коммита в корзину не идут.", ""]
    hits = sum(r[WITNESS_DEFECT] for r in rep["ops"])
    for d in WITNESS_DEFECTS:
        out.append(f"  {d['op']:20} «{d['pattern']}»  до {d['until']}")
        out.append(f"    {d['fix']}")
        out.append(f"    {d['why']}")
    out.append("")
    out.append(f"Снято с обвинения экземпляров операций: {hits}")
    return "\n".join(out)


def _read_jsonl(path: pathlib.Path) -> list:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--rejections", default=str(DEFAULT_REJECTIONS),
                    help="корпус отказов ДО исполнения (kir_rejections.jsonl); "
                         "отдельный знаменатель, в частоту построения не входит")
    ap.add_argument("--min-runs", type=int, default=20,
                    help="сколько вердиктов нужно, чтобы доля вообще о чём-то "
                         "говорила (по умолчанию 20)")
    ap.add_argument("--since", default=None,
                    help="отбросить строки старше этой отметки (префикс ISO, "
                         "напр. 2026-07-31). Заголовочное число берётся с "
                         "ОДНОГО свежего прогона, а не со всей истории — "
                         "корпус дописывается и помнит поведение до починок")
    ap.add_argument("--until", default=None,
                    help="отбросить строки на этой ISO-отметке и новее; "
                         "окно полуоткрытое [since, until)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    path = pathlib.Path(args.corpus)
    if not path.exists():
        print(f"корпус не найден: {path}", file=sys.stderr)
        return 2
    rows = _read_jsonl(path)
    total_before = len(rows)
    rows = window_rows(rows, since=args.since, until=args.until)
    lo, hi = span(rows)

    rej_path = pathlib.Path(args.rejections)
    rej_rows = _read_jsonl(rej_path) if rej_path.exists() else []
    rej_before = len(rej_rows)
    rej_rows = window_rows(rej_rows, since=args.since, until=args.until)
    rej_lo, rej_hi = span(rej_rows)

    honest = report(tally(rows), min_runs=args.min_runs)
    raw = report(tally_program_level(rows), min_runs=args.min_runs)
    rej = tally_rejections(rej_rows)
    rejection_units = tally_rejection_units(rej_rows)
    causes = tally_causes(rows)

    if args.json:
        print(json.dumps({
            "корпус": {"строк": len(rows), "всего_в_файле": total_before,
                       "от": lo, "до": hi, "since": args.since,
                       "until": args.until},
            "корпус_отказов": {"событий": len(rej_rows),
                               "всего_в_файле": rej_before,
                               "от": rej_lo, "до": rej_hi,
                               "since": args.since,
                               "until": args.until},
            "по_причинам": honest,
            "почему_из_строк": {
                "названо": {f"{code}|{field}": dict(messages)
                            for (code, field), messages in causes["named"].items()},
                "молчат": dict(causes["silent"])},
            "снятые_свидетели": list(WITNESS_DEFECTS),
            "отказы_до_исполнения": {
                "по_операциям": {k: dict(v) for k, v in rej["per_op"].items()},
                "чем_доказано": dict(rej["proof"]),
                "по_кодам": dict(rej["by_code"])},
            "единицы_отказов": {
                "строк": rejection_units["lines_total"],
                "попыток": rejection_units["attempts_total"],
                "ходов": rejection_units["turns_total"],
                "действий": rejection_units["actions_total"],
                "отпечатков_текста": rejection_units[
                    "query_fingerprints_total"],
                "legacy_query_groups": rejection_units[
                    "legacy_query_groups_total"],
                "identity_states": dict(rejection_units["identity_states"]),
                "source_lines": dict(rejection_units["source_lines"]),
                "source_attempts": dict(rejection_units["source_attempts"]),
                "stage_lines": dict(rejection_units["stage_lines"]),
                "stage_attempts": dict(rejection_units["stage_attempts"]),
                "классы": {
                    cls: {
                        "строк": rejection_units["lines"][cls],
                        "попыток": len(rejection_units["attempts"][cls]),
                        "ходов": len(rejection_units["turns"][cls]),
                    }
                    for cls in rejection_units["lines"]
                },
            },
            "сырое_программного_уровня_НЕ_частота": raw,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"Корпус исполнений: {len(rows)} строк из {total_before}"
          + (f", отсечка --since {args.since}" if args.since else "")
          + (f", отсечка --until {args.until}" if args.until else "")
          + f"\nВремя:             {lo} … {hi}")
    if rej_rows:
        print(f"Корпус отказов:    {len(rej_rows)} событий из {rej_before}"
              f"\nВремя:             {rej_lo} … {rej_hi}")
    if lo and hi and lo[:10] != hi[:10]:
        print("        ВНИМАНИЕ: промежуток охватывает больше одного дня — "
              "значит и правки кода. Частота по такому корпусу смешивает\n"
              "        поведение до починок и после; заголовочное число "
              "берут с одного свежего прогона (--since).")
    print()
    print("=" * len(_WIDE_HEAD))
    print("ПО ПРИЧИНАМ — приписывание по лестнице A/B/C, ни одной догадки")
    print("=" * len(_WIDE_HEAD))
    print(render(honest))
    print()
    print("=" * len(_WIDE_HEAD))
    print("ПОЧЕМУ — причина отказа, взятая ЗАПРОСОМ из строки, а не разбором текста")
    print("=" * len(_WIDE_HEAD))
    print(render_causes(causes))
    print()
    print("=" * len(_WIDE_HEAD))
    print("СНЯТЫЕ СВИДЕТЕЛИ — почему часть обвинений не является отказом операции")
    print("=" * len(_WIDE_HEAD))
    print(render_witness_defects(honest))
    if rej_rows:
        print()
        print("=" * len(_WIDE_HEAD))
        print("ОТКАЗЫ ДО ИСПОЛНЕНИЯ — ДРУГОЙ знаменатель, в частоту построения не входит")
        print("=" * len(_WIDE_HEAD))
        print(render_rejections(rej))
        print()
        print("=" * len(_WIDE_HEAD))
        print("ЕДИНИЦЫ ОТКАЗОВ — строки, попытки и ходы не смешиваются")
        print("=" * len(_WIDE_HEAD))
        print(render_rejection_units(rejection_units))
    print()
    print("=" * len(_WIDE_HEAD))
    print("СЫРОЕ, ПРОГРАММНОГО УРОВНЯ — провал записан каждому имени. НЕ ЧАСТОТА ОПЕРАЦИИ")
    print("=" * len(_WIDE_HEAD))
    print(render(raw, wide=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
