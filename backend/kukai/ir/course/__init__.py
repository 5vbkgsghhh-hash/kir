"""КУРС ПО `program_py` — ИНТРОСПЕКЦИЯ В ПЕСОЧНИЦЕ, А НЕ ТЕКСТ В ПРОМПТЕ.

ЗАЧЕМ ЭТОТ МОДУЛЬ СУЩЕСТВУЕТ. Замер, который всё объясняет: `create_group`
вызван НОЛЬ раз на 51 574 поднятых операции и не встречается ни разу среди
25 опов в 1 453 живых отказах. Инструмент сеньорский, а пользуются им
по-джуниорски — потому что никто не показал как. Разрыв не в инструментах, а
в методе, и переносится метод не документацией, а разобранными рабочими
примерами.

ПОЧЕМУ НЕ В ПРОМПТ. Описание инструмента — 29 391 символ при пороге 30 000
(`test_tool_doc.test_description_stays_small_next_to_the_schema`), и это
оплачивается КАЖДЫМ запросом. Курс туда не влезет и не должен: три четверти
его текста не нужны трём четвертям задач. Здесь он лежит В ПЕСОЧНИЦЕ, модель
зовёт нужный кусок ИЗ СВОЕГО ЖЕ СКРИПТА, и ответ приходит в `stdout` квитанции
ТОГО ЖЕ ХОДА — без отдельного раунда и без постоянной платы. Постоянно висит
только указатель имён (`POINTER`, 4 строки).

    course()               оглавление
    course("витраж")       урок целиком
    recipe()               список рабочих скриптов с замеренными числами
    recipe("витраж")       сам скрипт
    unit(name, placements) контекст: написанное внутрь становится ОДНОЙ группой
    score()                три числа твоей программы против базовой линии
    preview()              ПЛАН программы текстом: что нарисовалось и что нет
    design_check()         ВЕРДИКТ о пригодности замысла — без Revit

ДВЕ ПОСЛЕДНИЕ — НЕ ПРО ЯЗЫК, А ПРО ЗДАНИЕ, и добавлены они по замеру 03.08:
круг «модель пишет питон -> программа -> план -> вердикт -> правка» не замыкался
ни разу. План строился и уходил по вебсокету на панель ЧЕЛОВЕКА («поток отсюда
УХОДИТ И НЕ ВОЗВРАЩАЕТСЯ», `serving.py`), а у вердикта (`design_check.py`,
112 КБ) не было НИ ОДНОГО импортёра во всём дереве, кроме собственного теста.
Модель писала следующую версию здания вслепую — не потому, что зрение не
построено, а потому, что от него не было двери в её язык.

ЧЕТЫРЕ ПРАВИЛА, КОТОРЫЕ ДЕРЖАТ КУРС ЧЕСТНЫМ (проверяются `test_course.py`):

1. КАЖДОЕ ЧИСЛО ПЕРЕСЧИТЫВАЕТСЯ. Все замеры лежат в `corpus.py` рядом с
   функцией, которая берёт их заново с диска; тест сверяет запись с
   пересчётом. Устаревший замер в курсе неотличим от выдумки.
2. КАЖДЫЙ ПРИМЕР ИСПОЛНЯЕТСЯ. Скрипты `recipes.py` гоняются НАСТОЯЩЕЙ
   песочницей и компилируются на шести версиях Revit. Числа `ops`/`elements`
   — замер прогона, а не оценка автора.
3. НИ ОДНОГО ПЕРЕСЕЧЕНИЯ С `skill.py`. Тот курс — про поле `program` и
   макросы, этот — про `program_py`. Разделение механическое, его держит
   `test_course.test_the_two_courses_do_not_overlap`.
4. УКАЗАТЕЛЬ И ДОСТИЖИМОСТЬ — ОДНО ЦЕЛОЕ. Указатель в описании инструмента
   обещает имена; тест требует, чтобы обещанное было ДОСТИЖИМО из песочницы,
   и падает на половине шва. Реклама недостижимого стоит модели раунда.

ШОВ ПРОВЕДЁН — и эти строки правятся 04.08 именно потому, что утверждали
обратное. Песочница кладёт в пространство скрипта имена ОДНОГО модуля
(`policy.dsl_module`), и его УМОЛЧАНИЕ — уже `kukai.ir.course.language`
(`sandbox.SandboxPolicy`), то есть второй способ из `SEAM` сделан, а не описан.
`SEAM` оставлен как запись того, какими двумя способами это можно было
провести; выбранный — второй.

ЧЕГО СТОИЛА ЭТА УСТАРЕВШАЯ ФРАЗА: прочитав «ни один не сделан», следующий
читатель начинает проектировать уже написанное — ровно то, что в этом
репозитории уже случалось четырежды. Проза про недостижимость опаснее её
отсутствия по той же причине, по которой прибор на часть диапазона опаснее
отсутствующего.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from kukai.ir.course import corpus, lessons, recipes

# ПРОГРЕВ, А НЕ УДОБСТВО. Всё, что курс зовёт ВНУТРИ песочницы, обязано быть
# в `sys.modules` ДО того, как ребёнок установит стража импортов: страж
# (`sandbox._MetaGuard`) поднимает `_ForbiddenImport` на любой корень вне
# белого списка, а спрашивают его только при промахе кэша. Ленивый импорт
# внутри функции курса поэтому падает КИР-B004 «импорт запрещён» с номером
# строки МОДЕЛИ — замерено на первом же прогоне рецептов.
#
# `dsl` в этот список не входит НАМЕРЕННО: его импорт остаётся ленивым, иначе
# шов «две строки в конец dsl.py» стал бы циклом. К моменту исполнения скрипта
# он загружен всегда — он и есть модуль языка, который песочница импортирует
# первым.
from kukai.ir import spec as _spec                             # noqa: E402
from kukai.ir.acceptance import _OPS_WITHOUT_ELEMENTS          # noqa: E402

#: Потолок канала — у песочницы, а не литералом здесь: число, набранное
#: руками, расходится с источником при первой же правке политики.
from kukai.ir.sandbox import MAX_STDOUT_CHARS                  # noqa: E402

# ─────────────────────────────────────────────────────────────── указатель

#: ТО, ЧТО ВИСИТ В ПРОМПТЕ ПОСТОЯННО. Всё остальное — по запросу.
#:
#: Цена подсчитана в отчёте. Заменять он должен строку про
#: `tools/design/examples/*`: она указывает на скрипты с numpy и shapely,
#: которых в песочнице нет — модель не может ни запустить их, ни прочитать.
#: Указатель на недостижимое хуже отсутствия указателя.
POINTER: tuple[str, ...] = (
    "  КУРС ПО `program_py` ЛЕЖИТ В ПЕСОЧНИЦЕ, а не здесь: зови его ИЗ СВОЕГО "
    "ЖЕ СКРИПТА, ответ придёт в `stdout` квитанции ЭТОГО ЖЕ хода — отдельный "
    "раунд не нужен.",
    "    course() — оглавление; course(\"витраж\") — урок; recipe(\"витраж\") "
    "— рабочий скрипт целиком; score() — три числа твоей программы против "
    "базовой линии семи разобранных зданий.",
    "    unit(name, placements) — контекст: всё, написанное внутрь, становится "
    "ОДНОЙ группой Revit (`create_group`), а не россыпью элементов.",
    # Строка платится КАЖДЫМ запросом, поэтому здесь только имя и род
    # утверждения: что именно печатает каждая — видно из её же вывода, и
    # пересказывать это постоянным текстом значило бы платить дважды.
    "    preview() — план твоей программы текстом; design_check() — вердикт о "
    "пригодности замысла без Revit. Обе — САМОПРОВЕРКА; зови ДО отправки.",
    # Число — из константы песочницы, а не из памяти: цифра, набранная руками,
    # разойдётся с политикой при первой же её правке и будет врать уверенно.
    f"  Один урок за скрипт: печать обрезается на {MAX_STDOUT_CHARS} символах.",
)

#: ДВА СПОСОБА ПРОВЕСТИ ШОВ. Ровно одна правка каждый; выбор за лидом.
SEAM: tuple[tuple[str, str], ...] = (
    ("kukai/ir/dsl.py, две строки в конец файла",
     "from kukai.ir.course import SANDBOX_NAMES  # noqa: E402\n"
     "globals().update(SANDBOX_NAMES); __all__ += sorted(SANDBOX_NAMES)"),
    ("kukai/ir/serving.py, `_sandbox_policy()`",
     'SandboxPolicy(..., dsl_module="kukai.ir.course.language")'),
)


# ─────────────────────────────────────────────────────── печать в песочницу

#: ПОТОЛОК УРОКА — не круглое число, а вычет из потолка канала.
#:
#: `stdout` песочницы обрезается на `MAX_STDOUT_CHARS`, и это ЕДИНСТВЕННЫЙ
#: канал обратной связи скрипта. Курс, съевший его целиком, отнимает ровно то,
#: ради чего канал заведён: печать самой модели — расхождение приближения,
#: бюджет, число элементов. Резерв — 700 символов: вывод `score()` замерен в
#: 364, остальное на пару строк печати автора. Тест держит оба конца.
LESSON_RESERVE = 700
LESSON_CAP = MAX_STDOUT_CHARS - LESSON_RESERVE


def _emit(text: str) -> None:
    print(text)


# ───────────────────────────────────────────────────────────────── курс

def course(topic: str | None = None) -> None:
    """Оглавление курса либо один урок целиком.

    ПЕЧАТАЕТ, а не возвращает: канал, по которому текст доезжает до модели, —
    `stdout` квитанции, и возвращённая строка, которую забыли напечатать,
    просто пропала бы.
    """
    _emit(lessons.index() if topic is None else lessons.lesson(topic))


def recipe(name: str | None = None) -> None:
    """Список рабочих скриптов с замеренными числами либо сам скрипт."""
    if name is None:
        _emit(_recipe_index())
        return
    item = recipes.RECIPES[_resolve(name, recipes.RECIPES, "рецепт")]
    head = (f"РЕЦЕПТ «{item.name}» — {item.title}\n"
            f"замер прогона: {item.ops} операций, {item.elements} элементов, "
            f"{item.lines} строк; покрывает {item.covers}.")
    if item.versus:
        head += f"\nсравни с recipe(\"{item.versus}\"): {item.contrast}"
    _emit(head + "\n" + item.source.strip())


def _recipe_index() -> str:
    rows = ["РАБОЧИЕ СКРИПТЫ (числа — ЗАМЕР ПРОГОНА, не оценка автора):"]
    for name in recipes.ORDER:
        item = recipes.RECIPES[name]
        rows.append(f"  {name:<17} опов {item.ops:>3} -> элементов "
                    f"{item.elements:>3}, строк {item.lines:>3} — "
                    f"{item.title} ({item.covers})")
    rows.append("Пары «джуниор — сеньор» дают ОДИН результат разной формой; "
                "расходятся они ценой правки, а не числом элементов.")
    return "\n".join(rows)


def _resolve(name: str, table: dict, noun: str) -> str:
    """Имя темы/рецепта или отказ СО СПИСКОМ имён.

    Отказ без списка — это второй раунд: модель не угадает написание, она
    попробует синоним.
    """
    key = (name or "").strip().lower().replace("ё", "е")
    for candidate in table:
        if candidate.lower().replace("ё", "е") == key:
            return candidate
    raise KeyError(f"{noun} «{name}» не существует. Есть: "
                   + ", ".join(sorted(table)))


# ─────────────────────────────────────────── ЕДИНИЦА: сборка одной группой

class Unit:
    """Что осталось от `with unit(...)`: члены и ручка получившейся группы."""

    __slots__ = ("name", "placements", "members", "handle")

    def __init__(self, name: str | None, placements: list) -> None:
        self.name = name
        self.placements = placements
        self.members: list[dict] = []
        self.handle: Any = None

    def __repr__(self) -> str:
        return (f"Unit({self.name!r}, членов {len(self.members)}, "
                f"вхождений {len(self.placements) + 1})")


class _UnitContext:
    """Контекст, собирающий написанное внутрь в ОДИН `create_group`.

    ЧТО ЭТО НЕ ДЕЛАЕТ. Не проверяет семантику: правда о корректности членов
    принадлежит компилятору, и он уже говорит её точно — `ground.
    _ground_members` перевешивает отказ члена на сам оп группы и называет
    члена ЕГО id, а `authoring_validation` отказывает `by:ref` внутри члена
    отдельным диагнозом. Второй набор правил здесь разошёлся бы с первым на
    первой же правке реестра.

    ЧТО ЭТО ДЕЛАЕТ. Открывает временную программу (`dsl.program()` —
    публичный контекст языка), забирает накопленное и кладёт ОДИН оп
    `create_group` во внешнюю программу. Ни одного своего поля:
    `members`/`placements`/`name` — имена реестра.
    """

    __slots__ = ("_unit", "_inner")

    def __init__(self, name: str | None, placements: Iterable) -> None:
        self._unit = Unit(name, [list(p) for p in (placements or ())])
        self._inner = None

    def __enter__(self) -> Unit:
        from kukai.ir import dsl
        self._inner = dsl.program()
        return self._unit

    def __exit__(self, exc_type, exc, tb) -> bool:
        from kukai.ir import dsl
        inner, self._inner = self._inner, None
        collected = [dict(op) for op in inner.ops]
        inner.__exit__(exc_type, exc, tb)     # текущая программа на место
        if exc_type is not None:
            return False                      # исключение автора идёт наружу
        self._unit.members = collected
        if not collected:
            raise dsl.DslRefusal([dsl.Diagnostic(
                code=dsl.TYPE_BAD_TYPE, field_name="members",
                expected="1..200 опов", got=0,
                message_ru=("unit() не собрал ни одной операции: группа без "
                            "членов ничего не повторяет. Пиши опы ВНУТРИ "
                            "блока with"))])
        kwargs: dict[str, Any] = {"members": collected,
                                  "placements": self._unit.placements}
        if self._unit.name is not None:
            kwargs["name"] = self._unit.name
        self._unit.handle = dsl.OP_FUNCTIONS["create_group"](**kwargs)
        return False


def unit(name: str | None = None, *, placements: Iterable = ()) -> _UnitContext:
    """Повторяющаяся единица одной группой Revit.

        with unit("Кабинка су", placements=[(1600, 0), (3200, 0)]):
            create_wall(...)
            create_wall(...)

    Вхождение 0 — это САМИ члены, написанные в абсолютных координатах;
    `placements` — смещения [dx, dy(, dz)] остальных вхождений. Пустой список
    законен: группа, поставленная один раз, всё равно правится как одно целое.

    ВНУТРИ БЛОКА НЕЛЬЗЯ ССЫЛАТЬСЯ НА СОСЕДА: член группы не видит соседних
    опов, и `{"by": "ref"}` там — типизированный отказ (`members[<id>]`).
    Уровень, тип и символ адресуются именем или element_id.
    """
    return _UnitContext(name, placements)


# ───────────────────────────────────────────────── МЕТРИКА ПЕРЕНЯТИЯ

#: БАЗОВАЯ ЛИНИЯ — то, как выглядит НАСТОЯЩЕЕ здание. Не цель и не порог:
#: цель по числу закрывается одной операцией (`skill.GOOD_VS_BAD`). Это ответ
#: на вопрос «похоже ли построенное на дом» — и здание с 12 000 одиночных
#: колонн и нулём групп не похоже ни на одно из семи разобранных.
BASELINE: dict[str, tuple[float, str]] = {
    "элементов на тип": (
        round(corpus.value("k2.elements") / corpus.value("k2.types"), 1),
        "K2: 115 880 элементов на 638 типов; демо-дом 550, ЭОМ Сколково 411"),
    "копий на определение группы": (
        round(corpus.value("k2.group_places") / corpus.value("k2.group_defs"), 1),
        "K2: 2 846 постановок на 367 определений; ВК Snowdon 110 на 14 — два "
        "независимых здания сошлись на 7.8"),
    "элементов внутри групп, %": (
        corpus.value("k2.grouped_share"),
        "K2, НИЖНЯЯ граница: члены из неснятых категорий в знаменатель не "
        "попали"),
}


def _element_count(op: dict) -> int:
    """Сколько элементов ОБЪЯВЛЯЕТ операция.

    Производные (импосты, панели, фитинги, марши) НЕ считаются: сколько их
    родит Revit, из программы не видно, и догадка здесь была бы ровно тем
    молчаливым числом, ради запрета которого построена приёмка. Перечень
    «опов без элементов» берётся у приёмки, а не заводится второй.
    """
    name = op.get("op")
    ospec = _spec.OPS.get(name)
    if ospec is None or not ospec.writes_model:
        return 0
    if name in _OPS_WITHOUT_ELEMENTS or name == "delete":
        return 0
    if name == "create_group":
        members = op.get("members") or []
        return len(members) * (1 + len(op.get("placements") or []))
    return 1


def measure(ops: list[dict] | None = None) -> dict:
    """Три числа программы. Чистая функция — её зовут и тесты, и стенд."""
    if ops is None:
        from kukai.ir import dsl
        ops = [dict(op) for op in dsl.current().ops]
    written = len(ops)
    elements = sum(_element_count(op) for op in ops)
    groups = [op for op in ops if op.get("op") == "create_group"]
    in_groups = sum(_element_count(op) for op in groups)
    places = sum(1 + len(op.get("placements") or []) for op in groups)
    return {
        "операций написано": written,
        "элементов объявлено": elements,
        "элементов на операцию": round(elements / written, 2) if written else 0.0,
        "определений групп": len(groups),
        "постановок групп": places,
        "копий на определение": (round(places / len(groups), 2)
                                 if groups else 0.0),
        "элементов внутри групп, %": (round(100.0 * in_groups / elements, 1)
                                      if elements else 0.0),
    }


def _current_program() -> dict:
    """Программа, накопившаяся в языке к этой строке. НЕ ЗАБИРАЕТ её.

    Именно НЕ забирает, и это единственное решение в этой функции. `take_ops()`
    — ДВЕРЬ ПЕСОЧНИЦЫ (`sandbox._DRAIN_CANDIDATES`): вызванная отсюда, она
    оставила бы скрипт без программы, а ход — без результата, и заметить это
    было бы нечем, потому что и план, и вердикт при этом напечатались бы
    исправно. `build()` отдаёт КОПИЮ вместе с конвертом.
    """
    from kukai.ir import dsl
    return dsl.current().build()


def _program_for(ops: list[dict] | None) -> dict | None:
    """Что смотреть: переданное или накопленное. `None` — смотреть нечего."""
    program = {"ops": [dict(op) for op in ops]} if ops is not None \
        else _current_program()
    return program if program.get("ops") else None


def _ids(examples) -> str:
    return ", ".join(str(x) for x in examples[:4]) if examples else "—"


def preview(ops: list[dict] | None = None, *, level: str | None = None) -> None:
    """ПЛАН программы, которую ты пишешь, — ТЕКСТОМ, в этом же ходу.

    ДО 03.08 ПЛАН ДО МОДЕЛИ НЕ ДОХОДИЛ ВОВСЕ. Он строился (`plan_stream.py`) и
    уходил по вебсокету на панель человека: «поток отсюда УХОДИТ И НЕ
    ВОЗВРАЩАЕТСЯ» (`serving.py`). В квитанцию не попадало ничего, и модель
    писала следующую версию здания вслепую.

    ПОРЯДОК ПАРАМЕТРОВ ИСПРАВЛЕН 04.08, И ЭТО БЫЛ ДЕФЕКТ, А НЕ ВКУС. Сигнатура
    была `preview(level=None, *, ops=None)` — при том что у близнеца
    `design_check(ops=None)` первым идёт ПРОГРАММА. Замер: `preview(ops_list)`
    отдавал список в `level`, `ops` оставался `None`, и функция печатала
    «программа пуста — ни одной операции. Рисовать нечего» при трёх операциях
    на руках. Отказа не было. Модель читала «пусто» и шла добавлять уже
    написанное. Две функции, которые модель зовёт подряд одной и той же рукой,
    обязаны звать себя одинаково; фильтр по уровню остаётся, но по ИМЕНИ
    параметра: `preview(level="Этаж 1")`.

    ПРИНИМАЕТ И ПАЧКУ, как `design_check`. Разница между ними в том, что судья
    судит звенья ПОРОЗНЬ и по закону (`create_stairs` не имеет права стоять
    рядом со стенами), а рисовальщик СКЛЕИВАЕТ: лист один. Это уже закон
    потока — `plan_stream._slice_for` склеивает пачку ровно за этим. Отказать
    здесь значило бы ослепить модель на той единице, которой здание является.

    Сила утверждения — САМОПРОВЕРКА: рисуется ЗАЯВЛЕННОЕ. Ни один селектор не
    разрешён по настоящему документу, поэтому толщины стен, ширины проёмов и
    границы помещений здесь НЕИЗВЕСТНЫ — и каждое такое незнание стоит в
    переписи третьей колонкой, а не заменяется правдоподобным числом.
    """
    head: list[str] = []
    if ops is not None and not isinstance(ops, (list, tuple)):
        # ФОРМА ВХОДА НАЗЫВАЕТСЯ, А НЕ УГАДЫВАЕТСЯ. Принять строку как имя
        # уровня было бы догадкой в пользу вчерашней сигнатуры; починка — одно
        # слово, и она стоит прямо в отказе.
        _emit(f"ПЛАН ОТКАЗ: первым аргументом идёт ПРОГРАММА — список операций "
              f"(как у design_check), а пришло {type(ops).__name__}. Фильтр по "
              f"этажу задаётся именем параметра: preview(level=…).")
        return
    if _is_bundle(ops):
        merged: list[dict] = []
        for program in ops:
            merged.extend(dict(op) for op in program.get("ops") or ())
        head.append(f"ПАЧКА из {len(ops)} программ склеена в ОДИН лист "
                    f"(так же, как её склеивает живой поток): вердикт судит "
                    f"звенья порознь, план — вместе")
        shared = _shared_ids(ops)
        if shared:
            # НАЗВАНО, а не разрешено молча: `id` уникален ВНУТРИ программы, и
            # между программами совпадение ЗАКОННО. Вердикт разводит их в
            # `p1/wall1`/`p2/wall1`; план — НЕТ, и на листе они сольются.
            head.append(f"  ВНИМАНИЕ: {len(shared)} идентификаторов заняты "
                        f"более чем одной программой ({_ids(shared)}) — на "
                        f"ЛИСТЕ они сольются (вердикт их различает, план нет)")
        ops = merged
    try:
        program = _program_for(ops)
    except Exception as exc:  # noqa: BLE001 — форма входа, а не программа
        _emit(f"ПЛАН ОТКАЗ: программа не читается как список операций "
              f"({type(exc).__name__}: {exc}).")
        return
    if program is None:
        _emit("ПЛАН: программа пуста — ни одной операции. Рисовать нечего.")
        return
    from kukai.ir.preview import BLIND_SPOTS, build_program_preview, census_lines

    building = build_program_preview(program)
    census = building.census
    rows = [f"ПЛАН ПРОГРАММЫ — САМОПРОВЕРКА: нарисовано ЗАЯВЛЕННОЕ, "
            f"ни один селектор не разрешён по документу", *head,
            f"листов {len(building.plans)} из {building.levels_total} уровней; "
            f"операций рассмотрено {census.considered}, нарисовано "
            f"{census.drawn} ({census.coverage_pct:.0f}%)"]
    if census.considered and not census.drawn:
        # ЗАМЕР 04.08: на конверте программы и на узле L1 план печатал
        # «рассмотрено 1, нарисовано 0 (0%)» и НИ СЛОВА о причине — при том что
        # причина у него на руках. Ноль без причины неотличим от «здесь нечего
        # рисовать», а это разные починки: одну чинят чертежом, другую вызовом.
        rows.append(f"НЕ НАРИСОВАНО НИЧЕГО: ни одна из {census.considered} "
                    f"операций не попала на лист. Причины:")
        for line in census_lines(census):
            if line["kind"] != "omitted":
                continue
            rows.append(f"      {line['count']}: {line['ru']}"
                        + (f" ({line['category']})" if line["category"] else "")
                        + (f" — {_ids(line['examples'])}"
                           if line["examples"] else ""))
        rows.append("      Проверь ФОРМУ входа: план рисует ОПЕРАЦИИ KIR "
                    "(`{\"op\": …}`) или ПАЧКУ программ (`[{\"ops\": […]}, …]`).")
        _emit("\n".join(rows + ["план НЕ показывает: " + "; ".join(BLIND_SPOTS)]))
        return
    plans = building.plans
    if level is not None:
        plans = tuple(p for p in plans if p.level_name == level)
        if not plans:
            _emit("ПЛАН: уровня «%s» в программе нет. Есть: %s" % (
                level, ", ".join(f"«{p.level_name}»" for p in building.plans)))
            return
    for plan in plans:
        frame = plan.extents_mm()
        size = (f"поле {(frame[2] - frame[0]) / 1000:.1f} x "
                f"{(frame[3] - frame[1]) / 1000:.1f} м" if frame else "поля нет")
        rows.append(f"  «{plan.level_name}» отм. {plan.level_elevation_mm} мм, "
                    f"{size} — нарисовано {plan.census.drawn} из "
                    f"{plan.census.considered}")
        for group in plan.census.omitted:
            rows.append(f"      не нарисовано {group.count}: "
                        f"{group.reason.value} ({group.category}) — "
                        f"{_ids(group.examples)}")
        for group in plan.census.approx:
            rows.append(f"      приближено {group.count}: {group.reason.value}")
        for group in plan.census.anomalies:
            # ТО, РАДИ ЧЕГО ЭКРАН. Не вердикт и не приёмка: «посмотри сюда».
            rows.append(f"      ПОСМОТРИ СЮДА {group.count}: "
                        f"{group.reason.value} — {_ids(group.examples)}")
    # СПИСОК СЛЕПОТЫ ПЕЧАТАЕТСЯ ЦЕЛИКОМ И КАЖДЫЙ РАЗ. Молчание превью читается
    # как «всё в порядке», а обрезанный список слепоты — как «слепых мест мало».
    rows.append("план НЕ показывает: " + "; ".join(BLIND_SPOTS))
    _emit("\n".join(rows))


def _shared_ids(bundle) -> list[str]:
    """Идентификаторы, занятые более чем одной программой пачки."""
    seen: dict[str, int] = {}
    for program in bundle:
        for oid in {str(op.get("id", "")) for op in program.get("ops") or ()
                    if isinstance(op, Mapping) and op.get("id")}:
            seen[oid] = seen.get(oid, 0) + 1
    return sorted(oid for oid, count in seen.items() if count > 1)


def _is_bundle(value: Any) -> bool:
    """Пачка ли это — по КЛЮЧАМ элементов, а не по длине и не по надежде.

    Пачка — непустой список, КАЖДЫЙ элемент которого несёт свой `ops`. Список
    операций так выглядеть не может: у операции есть `op`, а `ops` нет. Правило
    «каждый», а не «первый»: смесь программы с операцией — это ошибка автора, и
    она обязана дойти до двери вердикта, которая назовёт её (KIR-V001), а не
    быть угаданной здесь в чью-то пользу.
    """
    return (isinstance(value, (list, tuple)) and bool(value)
            and all(isinstance(item, Mapping)
                    and isinstance(item.get("ops"), (list, tuple))
                    for item in value))


def design_check(ops: list[dict] | None = None) -> None:
    """ВЕРДИКТ о пригодности замысла — без Revit, в этом же ходу.

    Читает ЧИСЛА, которые программа уже содержит (концы стен, контуры, отступы
    проёмов), и прогоняет по ним правила пригодности жилья: связность, второй
    выход, площади, высоты, наличие окна. Ничего не симулирует: всё, что Revit
    добавил бы от себя, объявлено вне области поимённо и не моделируется даже
    приблизительно.

    ПРИНИМАЕТ И ПАЧКУ: `design_check([тело, лестница])`, где каждый элемент —
    программа (`{"ops": [...]}`). Это не удобство, а единственный способ
    получить здесь ПРАВДУ о многоэтажном здании: `create_stairs` по закону
    Revit — единственный оп своей программы (KIR-L002), поэтому здание, которое
    судят одной программой, обязано быть без лестницы, а значит `HAB010`
    заблокирует каждый занятый этаж выше земли. Судить надо ту единицу, которой
    здание является, — ПАЧКУ.

    ЭТО САМОПРОВЕРКА. Судится ЗАЯВЛЕННОЕ программой, а не построенное; вердикт
    по программе не является свидетельством о здании.
    """
    bundle = _is_bundle(ops)
    program = ops if bundle else _program_for(ops)
    if program is None:
        _emit("ВЕРДИКТ: программа пуста — ни одной операции. Судить нечего.")
        return
    try:
        from kukai.ir import design_check as _verdict
    except ImportError as exc:                    # pragma: no cover — см. warm_for_source
        _emit(f"ВЕРДИКТ НЕДОСТУПЕН: модуль вердикта не прогрет в этом запуске "
              f"({exc}). Напиши имя `design_check` в скрипте прямо — по нему "
              f"песочница и решает, что грузить.")
        return
    try:
        verdict = (_verdict.check_bundle(program, building_id="пачка этого хода")
                   if bundle else
                   _verdict.check_ops(program, building_id="программа этого хода"))
    except _verdict.VerdictInputError as exc:
        # Корень, а не `ProgramShapeError`: у двери вердикта родов отказа стало
        # два (KIR-V001 форма, KIR-V002 контракт пачки), и перехват по потомку
        # выпустил бы второй наружу трассой вместо названной причины.
        _emit(exc.render())
        return
    except _verdict.DesignCheckUnavailable as exc:
        # Отказ, а не тихий откат на v1: у пути v1 нет ни трёхзначного вердикта,
        # ни покрытия, и отличить его от настоящего было бы нечем.
        _emit(f"ВЕРДИКТ НЕДОСТУПЕН: {exc}")
        return
    _emit(_verdict.render_verdict_brief(verdict))


def score(ops: list[dict] | None = None) -> None:
    """Напечатать числа текущей программы рядом с базовой линией корпуса."""
    got = measure(ops)
    rows = [
        f"ПРОГРАММА: {got['операций написано']} операций -> "
        f"{got['элементов объявлено']} элементов "
        f"({got['элементов на операцию']} на операцию)",
        f"  групп: {got['определений групп']} определений, "
        f"{got['постановок групп']} постановок, "
        f"{got['копий на определение']} копий на определение; "
        f"{got['элементов внутри групп, %']}% элементов внутри групп",
        f"  базовая линия настоящих зданий: "
        f"{BASELINE['копий на определение группы'][0]} копий на определение, "
        f"{BASELINE['элементов внутри групп, %'][0]:.0f}% элементов в группах "
        f"(K2, нижняя граница)",
        "  производные элементы (импосты, панели, фитинги) НЕ посчитаны: "
        "сколько их родит Revit, из программы не видно",
    ]
    _emit("\n".join(rows))


# ─────────────────────────────────────────────────── что уходит в песочницу

#: РОВНО ТО, что шов кладёт в пространство скрипта. Ни одного модуля: песочница
#: их не инжектирует намеренно, и имя-модуль здесь молча пропало бы.
SANDBOX_NAMES: dict[str, Any] = {
    "course": course,
    "recipe": recipe,
    "unit": unit,
    "score": score,
    # ОБРАТНАЯ СВЯЗЬ О САМОМ ЗДАНИИ, а не о языке. Замер 03.08 на живом круге:
    # ни план, ни вердикт не доходили до модели НИ РАЗУ — план уходил по
    # вебсокету человеку, вердикт не имел ни одного импортёра во всём дереве.
    # Обе — УЗКИЕ ФУНКЦИИ, а не модули: песочница модулей не инжектирует
    # (`_child_main`: `isinstance(value, types.ModuleType) -> continue`), и
    # имя-модуль здесь молча пропало бы, а заодно открыло бы скрипту чужое
    # пространство имён целиком.
    "preview": preview,
    "design_check": design_check,
}


__all__ = [
    "BASELINE", "LESSON_CAP", "LESSON_RESERVE", "POINTER", "SANDBOX_NAMES",
    "SEAM", "Unit", "corpus", "course", "design_check", "lessons", "measure",
    "preview", "recipe", "recipes", "score", "unit",
]
