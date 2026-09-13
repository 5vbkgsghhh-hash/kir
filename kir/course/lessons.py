"""LESSONS — what gets printed by the model on request.

GENRE. Neither prose nor a reference manual: code with decompiles and
numbers. Every statement rests either on a measurement from `corpus.py`
(the number is SUBSTITUTED, not typed by hand) or on a fact of the code
with its location given. Folklore in the course is worse than no course at
all — it sounds authoritative and is not checked.

WHY THE TEXT REFLOWS (`_reflow`). Numbers are substituted into ready-made
paragraphs and have different widths: "115 880" and "7" break manual
layout differently, and the lesson arrives with ragged lines. Reflow is
not decoration: ragged text gets read diagonally, and a course read
diagonally does not carry the method across. Tables, code, and lists
(anything starting with indentation) are not touched at all.

WHAT IS NOT INCLUDED HERE. Everything already said in `skill.py` (the form
of repetition via macros, the refusal playbook, the pipeline's structure)
and in `tool_doc.NOTES` (API traps). That course is about the `program`
field, this one is about `program_py`. The overlap is checked mechanically.

THE CEILING. A lesson must fit within `LESSON_CAP` characters and leave
room for the model's own printing: the sandbox's `stdout` is truncated at
4000. The test measures each one.
"""
from __future__ import annotations

import textwrap

from kir.course import corpus
from kir.course.corpus import n, percent, ratio

# 🔴 IMPORTS WERE HOISTED TO MODULE LEVEL (28.08.2026), AND THIS WAS FORCED.
# Lessons execute INSIDE the sandbox, and its import guard deliberately
# refuses the `kir` root — authoring code has access to the language
# without an import. After the `kukai.ir` -> `kir` rename during the 27.08
# split, our own lazy imports inside lessons also fell under this rule:
# four lessons answered with `KIR-B004: импорт 'kir.ground' запрещён`
# instead of the lesson itself.
# At module level they execute when the course loads — before the guard is
# installed.
from kir.ground import MOST_USED_MIN_RATIO, MOST_USED_POOLS  # noqa: E402
from kir.preview import build_program_preview, census_lines  # noqa: E402

WIDTH = 78


def _reflow(text: str) -> str:
    """Reflow of prose paragraphs. Anything indented — code and tables —
    stays as is."""
    out: list[str] = []
    for block in text.strip("\n").split("\n\n"):
        lines = block.split("\n")
        if any(line.startswith((" ", "\t")) for line in lines):
            out.append(block)
            continue
        out.append(textwrap.fill(" ".join(ln.strip() for ln in lines),
                                 width=WIDTH, break_long_words=False,
                                 break_on_hyphens=False))
    return "\n\n".join(out)


# ─────────────────────────────────────────────────────────── 1. UNIT

def _unit() -> str:
    # 🔴 THE GROUP-MEMBER CEILING IS TAKEN FROM THE REGISTRY, NOT FROM
    # MEMORY (F-192, 29.08.2026). "1..200" used to stand here while
    # `spec.GROUP_MEMBERS_MAX = 1000`: the lesson is the last place the
    # model goes SPECIFICALLY for the `create_group` boundary, and it was
    # teaching it to cut a legitimate group down to a fifth. The second
    # carrier of the same number — the JSON schema (`F-190`) — is fixed in
    # the same pass. The import form is the same as `_limits()` below:
    # lazy, in place.
    from kir import spec
    return _reflow(f"""
УРОК «ЕДИНИЦА» — что повторить и на каком уровне.

ЗАМЕР МАСШТАБА. K2, жилая башня 59 этажей: {n('k2.elements')} элементов и
всего {n('k2.types')} различных (категория, тип) —
{ratio('k2.elements', 'k2.types')} элемента на тип. Здание не
{n('k2.elements')} решений, а {n('k2.types')}, размноженных. Демо-дом:
{ratio('demo.elements', 'demo.types')} элемента на тип, ЭОМ Сколково —
{ratio('sklnk.elements', 'sklnk.types')}.

ТРИ УРОВНЯ ПОВТОРА. Выбор делается ОДНИМ вопросом: что станет с правкой.

  1. ТИП — повторяется форма, но не расположение. `create_type` один раз,
     N элементов ссылаются селектором. Правка типа меняет все N в самой
     модели. Самый дешёвый уровень, работает всегда.
  2. ФУНКЦИЯ ПИТОНА — повторяется КОМПОЗИЦИЯ, и повтор нужен только пока ты
     пишешь. Правка = переписать скрипт и построить заново.
  3. `create_group`, он же `unit(...)` — композиция должна ПЕРЕЖИТЬ скрипт.
     Члены пишутся один раз, `placements` — смещения остальных вхождений.
     Человек правит одно вхождение, меняются все.

ПРИЗНАК ВЫБОРА между 2 и 3 ровно один: ПЕРЕЖИВЁТ ЛИ ЕДИНИЦА ТВОЙ СКРИПТ.
Функция — нет, группа — да. Больше ничем они не отличаются.

ЗАМЕР ТИРАЖА. K2: {n('k2.group_defs')} определений групп,
{n('k2.group_places')} постановок верхнего уровня,
{n('k2.group_reused')} из них ({percent('k2.group_reused', 'k2.group_defs')}%)
поставлены больше одного раза — {ratio('k2.group_places', 'k2.group_defs')}
копии на определение. ВК Snowdon, другое здание и другой раздел:
{n('plumb.group_defs')} определений, {n('plumb.group_places')} постановок,
{ratio('plumb.group_places', 'plumb.group_defs')}. Два независимых замера
сошлись. {n('k2.grouped_share')}% элементов K2 лежат ВНУТРИ группы — нижняя
граница, члены из неснятых категорий в знаменатель не попали.

РАЗМЕР ТИРАЖИРУЕМОЙ ЕДИНИЦЫ: медиана {n('k2.group_members')} членов в K2 и
{n('plumb.group_members')} в ВК Snowdon. Это КОМНАТНАЯ сборка — «Пилястра
16 этаж» 48 раз, «Поручень типовой этаж» 41 раз, «Live_Work Core - Studio»
7 раз по 67 членов. Одиночный элемент тиражируют ТИПОМ, целый этаж не
тиражируют вовсе.

ГДЕ ГРУПП НЕТ ВОВСЕ, И ЭТО НОРМА: ЭОМ Snowdon и ЭОМ Сколково —
{n('elec.group_defs')} определений на два здания. В инженерных разделах
повтор выражают система и трасса, а фитинги Revit выводит из степени узла.

НАШ СЛЕД. `create_group` вызван {corpus.GROUP_USES_IN_LIFTED_OPS} раз на
{corpus.fmt(corpus.LIFTED_OPS_MEASURED)} поднятых операции. В живых отказах он
с 18.08 ЕСТЬ: {corpus.GROUP_IN_LIVE_REJECTIONS} из
{corpus.fmt(corpus.LIVE_REJECTIONS_MEASURED)}, и падает на ТИПАХ и ЗАЗЕМЛЕНИИ,
а не на отсутствии попыток. Прежняя причина была нашей и починена; эта — в
форме вызова.

ЧТО НАДО ЗНАТЬ ПРО `create_group` СВЕРХ ЕГО ДОКСТРОКИ (её печатает
`print(create_group.__doc__)`, и это дешевле урока):

  • members — 1..{spec.GROUP_MEMBERS_MAX} авторинг-опов, вложенность запрещена;
  • {{"by": "ref"}} в члене: НАРУЖУ — отказ, ВПЕРЁД — отказ, на соседа
    ВЫШЕ — законно (порядок членов = порядок создания);
  • placements — смещения ДОПОЛНИТЕЛЬНЫХ вхождений; вхождение 0 это сами
    члены, и пустой список законен;
  • отказ ЛЮБОГО члена откатывает группу целиком (fail-closed): вызывающий
    падает обратно на N отдельных элементов, геометрия не теряется молча.

ЧЛЕН ГРУППЫ СТОИТ ТОЛЬКО НА ТОМ, ЧТО В МОДЕЛИ УЖЕ ЕСТЬ. Замерено обеими
ветками: `level=<ручка create_level>` даёт KIR-T001 «член группы не может
содержать ref-селекторы», а `level` ПО ИМЕНИ уровня, созданного этой же
программой, даёт KIR-G101 «не найден» — снимок про него ещё не знает.
Значит новый этаж и группа на нём это ДВЕ ПРОГРАММЫ: первая заводит уровень
и отдаёт его id в квитанции, вторая ставит группу с
`level={{"by": "element_id", "value": <id>}}`. Не костыль: группа — вещь
МОДЕЛИ, и собрать её можно только из того, что в модели есть.

Рабочие скрипты: recipe("санузел"), он же перечислением —
recipe("санузел-джуниор").
""")


# ────────────────────────────────────────────────────────────── 2. FLOOR

def _storey() -> str:
    return _reflow(f"""
УРОК «ЭТАЖ» — на каком масштабе повторяется ИМЕННО ЭТО здание.

МАСШТАБ ПОВТОРА — СВОЙСТВО ЗДАНИЯ, А НЕ ПРИВЫЧКА. Замер по подписи уровня
(множество (категория, тип) элементов уровня; совпали подписи — этаж
повторён):

  демо-дом       уровней {n('demo.levels'):>4}  ->  подписей {n('demo.level_sigs'):>3}
  ЭОМ Сколково   уровней {n('sklnk.levels'):>4}  ->  подписей {n('sklnk.level_sigs'):>3}
  K2, башня      уровней {n('k2.levels'):>4}  ->  подписей {n('k2.level_sigs'):>3}
  детский сад    уровней {n('kinder.levels'):>4}  ->  подписей {n('kinder.level_sigs'):>3}

В демо-доме и в ЭОМ этаж — ГОТОВАЯ повторяющаяся единица:
пиши функцию этажа и зови её в цикле. В K2 этажи ПОХОЖИ, но не равны
({n('k2.level_sigs')} подписи на {n('k2.levels')} уровней): копия одного этажа
{n('k2.levels')} раз — это не K2, а карикатура; повторяются там ЧАСТИ этажа,
их тираж — в course("единица"). В детском саду повтора по этажам НЕТ
ВОВСЕ, {n('kinder.levels')} уровней дают {n('kinder.level_sigs')} подписей;
зато есть {n('kinder.group_defs')} определение группы «Кабинка су_ДОО» и 638
её вхождений. Малое здание повторяется по КОМНАТНОЙ единице.

ПОРЯДОК В СКРИПТЕ.

    # 1. уровни — циклом, отметка арифметикой
    levels = [create_level(elev_mm=i * H, name="Этаж %d" % (i + 1))
              for i in range(N)]

    # 2. этаж — ФУНКЦИЕЙ, принимающей ручку уровня и возвращающей ручки
    def storey(level, tag):
        walls = [create_wall(p0_mm=p, p1_mm=q, level=level, type=WT,
                             height_mm=HH) for p, q in edges]
        create_room(xy=centre, level=level, name="Квартира %s" % tag)
        return walls

    # 3. здание — цикл по уровням
    for i, lvl in enumerate(levels):
        storey(lvl, i + 1)

ЧТО ЛОМАЕТСЯ, ЕСЛИ СДЕЛАТЬ ИНАЧЕ.

  • `level` — ОБЯЗАТЕЛЬНЫЙ аргумент, и `defaults` конверта его НЕ заполнит:
    конверт идёт только в ОПУЩЕННОЕ поле, а питон опустить обязательный
    аргумент не даст (TypeError: missing a required argument). Держи ручку
    уровня в переменной и передавай явно: «селектор один на программу — его
    место в defaults» верно для поля `program`, в скрипте стоит раунда.
  • Ссылки вперёд не существует: ручку получают ДО того, как на неё
    ссылаются. Уровень — потом стена, стена — потом окно.
  • Резать программу САМОМУ НЕ НАДО: не влезающая в кадр идёт срезами в
    твоём порядке. Цена в квитанции: атомарность `per_chunk` — отказ на
    срезе k оставляет срезы до него В МОДЕЛИ, повтор целиком запрещён.
  • ЛЕСТНИЦА — ВСЕГДА ОТДЕЛЬНАЯ программа: `create_stairs` владеет своими
    транзакциями и соседей не терпит (KIR-L002). Уровень, созданный телом,
    виден ей ПО ИМЕНИ: `base_level="Этаж 1"`; ссылка (`ref`) границу
    программы не переживает. И ВЕРДИКТ ТОГДА СПРАШИВАЮТ У ПАЧКИ —
    `design_check([тело, лестница])`. У одного тела HAB010 не блокирует, а
    МОЛЧИТ, назвав причину («лестниц нет ни одной»): без лестницы «этаж
    висит» неотличимо от «спускаться нечему»; как читать молчание —
    course("вердикт"). Лестница, слепленная из плит
    `create_floor`, вердикт не обманет — он читает `create_stairs`.

БЮДЖЕТ СЧИТАЮТ, А НЕ ВСПОМИНАЮТ, и он защита от рунавэя, а не размер
здания. Опы на этаж берут из самой программы, иначе число разъедется с
первой же правкой функции (литералов здесь нет намеренно — протухают):

    per_storey = len(kir.current()) // FLOORS
    print("влезает этажей:", kir.MAX_BULK_OPS // per_storey)

`score()` печатает числа программы рядом с базовой линией корпуса. Рабочие
скрипты: recipe("этаж") и recipe("этаж-джуниор").
""")


# ──────────────────────────────────────────────────────────── 3. CURTAIN WALL

def _curtain() -> str:
    written = corpus.value("k2.curtain_hosts") + corpus.value("k2.curtain_lines")
    born = corpus.value("k2.curtain_mullions") + corpus.value("k2.curtain_panels")
    return _reflow(f"""
УРОК «ВИТРАЖ» — три слоя, из которых пишутся два.

ЗАМЕР. K2: {n('k2.curtain_hosts')} стен-носителей витража;
{n('k2.curtain_lines')} линий разрезки, которые тип не режет сам;
{n('k2.curtain_mullions')} импостов, из них {n('k2.curtain_driven')}% РОДИЛ
ТИП НОСИТЕЛЯ; {n('k2.curtain_panels')} панелей. Фасад СОБ6.2:
{n('fas.curtain_hosts')} носителей, {n('fas.curtain_lines')} линий,
{n('fas.curtain_mullions')} импостов ({n('fas.curtain_driven')}% от типа),
{n('fas.curtain_panels')} панелей — и производные категории составляют
{n('fas.derived')}% ВСЕЙ модели фасада.

СЛОЙ 1 — НОСИТЕЛЬ. `create_wall` с ВИТРАЖНЫМ типом. Тип решает почти всё:
он несёт раскладку сетки, тип импоста по каждому направлению и панель по
умолчанию. У 999 из 1000 носителей K2 панель берётся у типа. Значит выбор
типа и есть главное решение задачи, а принимается оно ЧТЕНИЕМ:
query_types(pool='wall_types').

СЛОЙ 2 — ЛИНИИ РАЗРЕЗКИ. `create_curtain_grid_line(host, direction,
position_mm)`. `host` — слот ЦЕЛИ ЗАПИСИ: принимает element_id или РУЧКУ
соседнего опа, формы by=name у него нет вовсе. `direction` — 'u' либо 'v'.

СЛОЙ 3 — ЯЧЕЙКА, И ТОЛЬКО ГДЕ ОТЛИЧАЕТСЯ. `set_curtain_panel(host, u, v,
panel_type)`. У `panel_type` НЕТ правила по умолчанию вовсе — ни
doc-default, ни единственной записи пула, — поэтому {{"by": "default"}} там
типизированный отказ на разборе. Пиши ОТЛИЧИЯ: на фасаде 5 типов панели на
{n('fas.curtain_panels')} панелей, на K2 — 14 на {n('k2.curtain_panels')}.

ЧЕГО ПИСАТЬ НЕЛЬЗЯ.

  • ИМПОСТ. Опа нет и не будет: единственный его конструктор в Revit API —
    CurtainGridLine.AddMullions, и такого опа в реестре нет
    (decompile/curtain_extract.MullionState объясняет, почему). Настоящая
    башня получает {n('k2.curtain_driven')}% импостов от ТИПА носителя;
    искать оп импоста — потерянный раунд.
  • ПАНЕЛЬ В КАЖДОЙ ЯЧЕЙКЕ: её рождает тип носителя. Назначить вручную то,
    что и так придёт умолчанием, — не лишняя работа, а лишний элемент.

ЛОВУШКА, ЗАМЕРЕННАЯ ЖИВЬЁМ 28.07: `set_curtain_panel` со СТЕНОВЫМ типом
строит СТЕНУ вместо панели. Тип ячейки — это тип ПАНЕЛИ.

НЕ ГРУППИРУЙ ВИТРАЖ. Соблазн «собрать панель с импостами в группу»
разбивается о два факта разом. Первый: член группы не может ссылаться на
соседа, а линия разрезки адресует носитель именно ссылкой — программа
откажет. Второй: работу группы здесь УЖЕ делает тип. В K2
{n('k2.curtain_hosts')} носителей витража и ни одной группы про витраж:
группы там про пилястры, поручни и потолки МОП.

АРИФМЕТИКА. Витраж K2 = {n('k2.curtain_hosts')} + {n('k2.curtain_lines')} =
{corpus.fmt(written)} написанных операций против {corpus.fmt(born)}
элементов импостов и панелей: {corpus.fmt(round(born / written, 1))}
элемента на операцию, и {n('k2.curtain_mullions')} импостов поштучно
невыразимы в принципе.

Рабочие скрипты: recipe("витраж") и recipe("витраж-джуниор").
""")


# ───────────────────────────────────────────────────────────── 4. FOR FREE

def _free() -> str:
    rows = "\n".join(
        textwrap.fill(f"{category:<32} <- {', '.join(ops)}", WIDTH,
                      initial_indent="  ", subsequent_indent=" " * 38)
        for category, ops in corpus.derived_categories().items())
    from kir import spec
    writing = sum(1 for op in spec.OPS.values() if op.writes_model)
    return _reflow(f"""
УРОК «ДАРОМ» — что Revit делает сам, и чего поэтому НЕ надо писать.

ЗАМЕР. Производные категории — {n('k2.derived')}% модели K2 и
{n('fas.derived')}% модели фасада СОБ6.2. Почти половина фасада это
элементы, которых никто не писал.

СПИСОК НЕ СОЧИНЁН. Он взят из цепи приёмки (`acceptance._OP_DERIVED`), где
несёт вес: производную категорию перепись НЕ сверяет и не показывает как
«неожиданное». Читается «категория <- оп, вслед за которым она появляется»:

{rows}

ПРАВИЛО. Если элемент — СЛЕДСТВИЕ другого, его не пишут. Проверка одна и
дешёвая: есть ли у него оп? `print(kir.op_names(writes=True))` — {writing}
имён, целиком. Имени нет — это не пробел языка, это производная.

ЧТО ЕЩЁ ДЕЛАЕТСЯ САМО, НО НЕ ОТДЕЛЬНОЙ КАТЕГОРИЕЙ.

  • ГРАНИЦЫ ПОМЕЩЕНИЯ. `create_room(xy, level)` ставит ТОЧКУ; границы Revit
    находит сам по окружающим стенам. Контур помещению не задают — поля
    нет, и это не пробел.
  • ФИТИНГИ СЕТИ. Один оп `create_pipe_system` / `route_*` описывает ВСЮ
    трассу узлами и рёбрами: связность выходит по построению, фитинги Revit
    выводит из степени узла.
  • ЛЕСТНИЦА. `create_stairs` рождает марши, площадки и ограждение; он
    единственный оп своей программы (сосед => KIR-L002). ЭТАЖИ ей добавляет
    `create_multistory_stairs` — обычный оп, соседи разрешены.
  • ТОЛЩИНА. Своего поля толщины у `create_floor`/`create_wall` нет:
    толщина принадлежит ТИПУ. «Перекрытие 200 мм» =
    `create_type(width_mm=200)`, затем `create_floor(type=<он>)`.

ЦЕНА ОШИБКИ В ЭТУ СТОРОНУ. Элемент, написанный руками там, где Revit сделал
бы его сам, — это ДВОЙНОЙ элемент: свой поверх рождённого. Спецификация
посчитает оба, и расхождение найдут не сразу.
""")


# ─────────────────────────────────────────────────────────── 5. BOUNDARIES

def _limits() -> str:
    from kir import spec
    # 🔴 THE OP BUDGET IS TAKEN FROM THE COMPILER (F-193, 29.08.2026).
    # "300 operations" used to stand here while
    # `MAX_OPS_PER_PROGRAM = 100 000` — an understatement by a factor of
    # 333 PLUS a direct instruction to "cut it yourself", meaning the
    # lesson was forcing the model to split up a building that is built as
    # one program. A neighboring carrier of the same number
    # (`skill.build_skill_text`) was fixed earlier and is protected by
    # `test_skill.test_no_stale_literal_for_the_op_budget`; THIS one stayed
    # outside that guard's reach — the permanent text was guarded, text
    # generated on request was not.
    from kir.compiler import MAX_BULK_OPS, MAX_OPS_PER_PROGRAM
    # 26.08: POOL NUMBERS ARE TAKEN FROM THE REGISTRY AND FROM GROUNDING.
    # Writing "doors have seven variants" would mean writing a number from
    # SOMEONE ELSE'S document into the course — exactly the defect this
    # paragraph teaches not to commit.
    _pools = [pp for pp in spec.OPS["query_types"].params
              if pp.name == "pool"][0].choices
    _no_rule = len(set(_pools) - set(MOST_USED_POOLS))
    # 19.08: the list of IMPORTS IS TAKEN LIVE, rather than rewritten in
    # prose. The earlier text named three modules and separately denied
    # numpy/shapely, whereas the `KUKAI_IR_AUTHOR_GEOMETRY_LIBS` flag opens
    # them up: the course was teaching the model to avoid a capability it
    # actually had.
    from kir.sandbox import allowed_imports_for_env
    allowed = ", ".join(allowed_imports_for_env())
    unref = sorted(name for name, op in spec.OPS.items()
                   if op.writes_model and op.result.reference_kind is None)
    unref_block = textwrap.fill(", ".join(unref), WIDTH,
                                initial_indent="  ", subsequent_indent="  ")
    return _reflow(f"""
УРОК «ГРАНИЦЫ» — чего в языке нет, и что с этим делать.

МАКРОСОВ В СКРИПТЕ НЕТ. `stack`, `series`, `grid_array` разворачиваются ДО
валидации и не входят в реестр опов вовсе — таких имён в пространстве
скрипта нет. Их работу делает питон: цикл, арифметика, список. Макросы
остаются формой поля `program`; это не пробел, а разделение — питон
выразительнее трека.

СУЩЕСТВУЮЩЕЕ АДРЕСУЕТСЯ ТОЛЬКО ID ИЛИ ИМЕНЕМ. Описания («южная стена»,
«верхний этаж») в языке нет. Сначала `query_list`/`query_types`, потом
работа по id. Адресации ОТ ОСЕЙ нет вовсе: `ReferenceKind` — четыре члена
(element, wall, level, family_symbol), GRID среди них отсутствует,
координаты едут числами.

СВОЁ СОЗДАННОЕ ДЕРЖИТСЯ В ПЕРЕМЕННЫХ. Вызов возвращает РУЧКУ, она же
ссылка: `w = create_wall(...)`, потом `create_door(host=w)`. Не сохранил
ручку — оп потерян для ссылок, второго способа адресовать его внутри
программы нет.

НЕ НА ВСЁ МОЖНО СОСЛАТЬСЯ. У {len(unref)} пишущих опов `reference_kind` не
объявлен:

{unref_block}

Ручка у них есть (по ней читают id), `by=ref` — нет, и отказ приходит НА
МЕСТЕ, с причиной из контракта, а не через два слоя компилятора.

ИМЯ ТИПА НЕ УГАДЫВАЕТСЯ — ОНО ЧИТАЕТСЯ: каталог у каждого проекта СВОЙ.
Замер 26.08 — шесть имён из ШАБЛОНА REVIT («0915 x 2134», «Типовой - 200мм»)
в чужом документе, шесть отказов.

🔴 И ЧИТАЕТСЯ ОН ПО-РАЗНОМУ НА ДВУХ ПУТЯХ. В `program_py` каталог УЖЕ В
РУКАХ: read-only рейс идёт ДО песочницы, поэтому `model.types(...)` и
`model.levels()` КРУГА НЕ СТОЯТ. На пути JSON рейса нет вовсе — там имя берут
из ОТКАЗА, который пул уже показал.

{{"by": "default"}} спасает не всегда: у {_no_rule} пулов из {len(_pools)}
правила «самый употребимый» НЕТ ВОВСЕ — отказ, как только записей больше
одной; у остальных {len(MOST_USED_POOLS)} оно есть, но лидеру нужен отрыв в
{MOST_USED_MIN_RATIO:g} раза, иначе выбор был бы жребием.

`defaults` НЕ ЗАПОЛНИТ ОБЯЗАТЕЛЬНЫЙ АРГУМЕНТ — см. course("этаж").

УМОЛЧАНИЯ РЕЕСТРА НЕ ВПИСЫВАЮТСЯ. Сигнатура их ПОКАЗЫВАЕТ, JSON — нет.
Вписанное явно умолчание меняет `plan_digest` программы и стирает провенанс
поля: опущенное — REGISTRY_DEFAULT, вписанное — EXPLICIT. Здание одно,
подпись разная. Не вписывай то, что и так умолчание.

ИМПОРТ — РОВНО {allowed}. random/time/os
нет: недетерминизм ломает `author_digest`, а скрипт прогоняется ДВАЖДЫ со
сверкой дайджестов. Нужен разброс — впиши числа. `open`, `eval`, `exec`,
`id` закрыты и объясняют себя при вызове.

БЮДЖЕТ — {MAX_OPS_PER_PROGRAM} опов ДО макросов, {MAX_BULK_OPS} после. Режь,
только когда упрёшься.

ИНТРОСПЕКЦИЯ УЖЕ РАБОТАЕТ И НИЧЕГО НЕ СТОИТ:

    print(create_wall.__doc__)      параметры реестра, их границы,
                                    ПОСТУСЛОВИЕ и допуски свидетеля — то,
                                    что проверят на живой модели
    kir.op_names(writes=True)       все пишущие опы
    kir.selector_forms(op, param)   какие by= принимает ИМЕННО этот слот

Если вопрос узкий, докстрока опа дешевле любого урока.
""")


# ──────────────────────────────────────────────────────────── 6. SHAPE

def _shape() -> str:
    from kir.course import recipes as _r
    pairs = (("санузел", "санузел-джуниор"), ("витраж", "витраж-джуниор"),
             ("этаж", "этаж-джуниор"))
    rows = []
    for senior, junior in pairs:
        s, j = _r.RECIPES[senior], _r.RECIPES[junior]
        rows.append(
            f"  ЗАДАЧА: {s.title}\n"
            f"    сеньор  опов {s.ops:>3}, строк {s.lines:>3} -> элементов "
            f"{s.elements:>3}  ({s.covers})\n"
            f"{textwrap.fill(s.contrast, WIDTH, initial_indent=' ' * 12, subsequent_indent=' ' * 12)}\n"
            f"    джуниор опов {j.ops:>3}, строк {j.lines:>3} -> элементов "
            f"{j.elements:>3}  ({j.covers})\n"
            f"{textwrap.fill(j.contrast, WIDTH, initial_indent=' ' * 12, subsequent_indent=' ' * 12)}")
    return _reflow("""
УРОК «ФОРМА» — джуниор против сеньора, в числах.

ОБЕ ФОРМЫ КОМПИЛИРУЮТСЯ И ОБЕ СТРОЯТ. Разница не в синтаксисе и почти
никогда не в числе элементов — она в ЦЕНЕ ПРАВКИ и в том, что осталось в
модели.

""" + "\n\n".join(rows) + """

ЧИТАЕТСЯ ЭТО ТАК.

  • «Скрипт короче» ничего не значит: джуниорская кабинка КОРОЧЕ
    сеньорской на строку и при этом оставляет в модели 18 несвязанных стен
    вместо одного определения с шестью вхождениями.
  • «Опов меньше» тоже не самоцель: у витража сеньорская форма пишет 14
    операций вместо 26 не ради экономии, а потому что 12 назначений
    повторяли умолчание типа — то есть были лишними элементами.
  • Единственная величина, в которой формы расходятся всегда, — СКОЛЬКО
    МЕСТ НАДО ТРОНУТЬ, ЧТОБЫ ПОМЕНЯТЬ ОДНО РЕШЕНИЕ. Сеньорская форма
    отвечает «одно» на каждом уровне: тип, функция, группа.

ПРИЗНАК, ЧТО ФОРМА ВЫБРАНА НЕВЕРНО, ВИДЕН РАНО: ты пишешь третью почти
одинаковую операцию, меняя в ней число. Останавливайся здесь, а не на
двадцатой.

ПРОВЕРКА СЕБЯ ОДНОЙ СТРОКОЙ: `score()` в конце скрипта. Здание с 12 000
одиночных колонн и нулём групп статистически не похоже ни на одно из семи
разобранных — и это проверяемый сигнал, а не вкусовщина.
""")


#: THE PROGRAM ON WHICH THE LESSON SHOWS THE PLAN. It lives HERE, not in
#: the text and not in the test: the lesson's numbers are the output of a
#: real run over IT, and a second copy of the same program would silently
#: diverge from the first.
#:
#: Chosen so as to show ALL THREE kinds of census record at once: a level
#: does not make it onto the plan at all, walls and the room make it in
#: APPROXIMATED form (the wall as an axis, not a body, because the type
#: selector is not resolved; the room as a point, because the boundary is
#: computed by Revit), a door carries two approximations at once.
#:
#: 🔴 THE ROOM SLOT WAS CALLED `point_mm`, AND THIS PROGRAM DID NOT COMPILE
#: (measured 04.09.2026, `compile_program({"ops": list(PLAN_DEMO_OPS)},
#: revit_version="2026", snapshot=None)`):
#:
#:     BEFORE  ok=False, 2 diagnostics: KIR-P003 «неизвестное поле
#:             'point_mm' у create_room» and KIR-T001 «xy — точка [x,y] мм»
#:     AFTER   ok=True, 0 diagnostics, C# for all six Revit versions
#:
#: The registry calls the slot `xy`; the lesson wrote `point_mm` and did
#: not notice, because it walked the program ONLY through `preview` — the
#: plan reads what is DECLARED and tolerates an extra field (it drops the
#: room anyway: `no_geometry`). The program never reached the compiler,
#: NOT ONCE, and the course — the first thing an outside person reads —
#: carried a house that cannot be built.
#:
#: What holds this in place is not a convention but a run:
#: `kir/tests/test_the_course_ships_a_house_that_can_be_built.py` compiles
#: EVERY program in the course, found by walking the package, on all six
#: Revit versions — a handwritten list would fall behind on the very first
#: new program.
#:
#: 🔴 WHAT THIS SLOT WAS ALSO HIDING FROM THE LESSON ITSELF. The census
#: SHIFTED: it used to be «рассмотрено 5, нарисовано 3, не нарисовано 2»,
#: now it is «5 / 4 / 1». The room was being dropped as `no_geometry` not
#: by rule, but because its point was called by the wrong name — and the
#: lesson was explaining this omission as a RULE («у помещения до
#: постройки геометрии нет»). With the `xy` slot, the room makes it onto
#: the sheet as a point with the approximation `room_boundary_not_computed`
#: («границу считает Revit»), and only ONE legitimate omission remains —
#: the level. The lesson's text was rewritten to match the measurement: it
#: was already counting the numbers, just not the prose.
PLAN_DEMO_OPS: tuple[dict, ...] = (
    {"op": "create_level", "id": "lvl", "name": "Этаж 1", "elev_mm": 0},
    {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
     "height_mm": 3000, "level": {"by": "ref", "value": "lvl"}},
    {"op": "create_wall", "id": "w2", "p0_mm": [6000, 0], "p1_mm": [6000, 4000],
     "height_mm": 3000, "level": {"by": "ref", "value": "lvl"}},
    # 🔴 THE DOOR SYMBOL IS ADDRESSED BY `element_id`, NOT BY `default`, AND
    # THIS FORM WAS NAMED BY THE FAILURE ITSELF. With `{"by": "default"}`
    # the program failed with KIR-G103 («резолв по имени/default требует
    # снапшот модели; без снимка эти слоты адресуются только формой {"by":
    # "element_id", "value": <id>}») — legitimately: a snapshot exists only
    # for a live Revit, and a lesson about a PLAN must compile without one.
    # The census DID NOT SHIFT by a single line from this change (measured
    # 04.09: 5/4, the same door_swing_unknown and opening_width_unknown),
    # meaning the lesson lost nothing, while the program became ok=True.
    {"op": "create_door", "id": "d1", "host": {"by": "ref", "value": "w1"},
     "offset_mm": 3000, "symbol": {"by": "element_id", "value": 355}},
    {"op": "create_room", "id": "r1", "xy": [3000, 2000],
     "name": "Гостиная", "level": {"by": "ref", "value": "lvl"}},
)


def _plan_block() -> str:
    """Half of the lesson about `preview()`. NUMBERS ARE COMPUTED, not
    written by hand.

    🔴 WHAT THIS HALF WAS BOUGHT WITH, 26.08.2026. Corpus
    `kir_course_uptake.jsonl`, window 23.08 -> 26.08, the CHAT door (model
    turns, 61 authoring-script runs): `preview` was called in ZERO runs,
    `design_check` in three, `spec` in nine. The single call to `preview`
    in the whole corpus came from the ADMIN door, i.e. from the author by
    hand. The model writes enough scripts and reaches the course — the
    difference between the twins is exactly what the course TEACHES the
    judge (four spots in this file), while the plan is named in a single
    line of the index.

    The sample is small (3 against 0 out of 61) and proves nothing by
    itself; the lesson is not written "because it's zero", but because a
    capability that cannot be learned about IN DETAIL is dark by
    construction — the same way `sdk.py` lay excellent and unreachable for
    five weeks.

    WHY A CENSUS, NOT A PICTURE. What needs teaching is what the model will
    not see for itself: a coverage percentage reads as a grade ("4 out of
    5 — bad"), while in fact the single omission is LEGITIMATE, and the
    lesson's whole job is to separate a legitimate omission, an honest
    approximation, and an unresolved selector.

    🔴 "TWO OMISSIONS ARE LEGITIMATE" STOOD HERE UNTIL 04.09.2026 AND WAS
    UNTRUE. The second omission (the room, `no_geometry`) was held up by a
    TYPO in the `create_room` slot of the same program, and the lesson
    explained it as a rule. The shape of the defect is worse than the typo
    itself: the observation was fitted to the prose, because the program
    was never once run past `preview`.
    """
    c = build_program_preview(list(PLAN_DEMO_OPS)).census
    строки = census_lines(c)
    # One line per reason: merging them into one eats the line break and
    # runs past the width, and the census is read WITH THE EYES on the
    # next turn.
    пропуск = "\n".join(f"      {r['category']} — {r['ru']}"
                        for r in строки if r["kind"] == "omitted")
    # Approximations are given ONLY AS CODES: the model will read the full
    # text in its own output, and the lesson is paid for on every call and
    # must be shorter than the output.
    приближ = ", ".join(f"{r['reason']}x{r['count']}"
                        for r in строки if r["kind"] == "approx")
    приближ = textwrap.fill(приближ, WIDTH - 6,
                            initial_indent="      ", subsequent_indent="      ")
    return f"""
БЛИЗНЕЦ СУДЬИ — `preview()`. Судья говорит «годно ли», план — «что вообще
получилось»: тоже текстом, тоже до транзакции, тоже без Revit.

СИЛА ПЛАНА В ПЕРЕПИСИ, А НЕ В КАРТИНКЕ. Перепись ЗАМЫКАЕТСЯ — рассмотрено =
нарисовано + пропущенное, — поэтому молча пропасть не может ничто. Живой
прогон {len(PLAN_DEMO_OPS)} операций (уровень, две стены, дверь, помещение):

    рассмотрено {c.considered}, нарисовано {c.drawn}
    не нарисовано {c.omitted_total}:
{пропуск}
    приближено {c.approx_total}:
{приближ}

«{c.drawn} из {c.considered}» — НЕ ПОЛОМКА и не оценка: уровень в плане не виден
по построению, и это ЕДИНСТВЕННЫЙ пропуск — он законен. Остальное приехало
третьей колонкой, и её надо читать отдельно. «Границу помещения считает Revit»
— граница будет, но не здесь: в программе помещение это ТОЧКА. А «толщина
неизвестна» говорит совсем другое — СЕЛЕКТОР ТИПА НЕ РАЗРЕШЁН, и стена
нарисована ОСЬЮ, а не телом: план рисует ЗАЯВЛЕННОЕ и документ не читает.
Читай эти строки, а не процент."""


# ──────────────────────────────────────────────────────────── 7. VERDICT

# 🔴 WHY A SEPARATE LESSON, RATHER THAN A PARAGRAPH IN "FLOOR" (22.08.2026).
# The course used to have ONE line about the judge — "the verdict is asked
# of the batch" inside the item about the staircase. A live run that same
# day cost two round trips over exactly what that line does not say: the
# PROGRAM path resolves a level ONLY as declared by the program itself, and
# a reference to the model's level throws out the entire construction —
# the verdict prints "model has no rooms" with rooms declared (live run —
# four, reproduced in the test — two).
# Adding this to "floor" was not possible: only 13 free characters
# remained there against the `LESSON_CAP` ceiling, and the addition would
# have cut into the floor's budget, i.e. someone else's fact.
# The lesson's numbers are the OUTPUT of a real run, reproduced by
# `test_course.VerdictLessonIsTheVerdictItself`, not a retelling.
def _verdict() -> str:
    return _reflow("""
УРОК «ВЕРДИКТ» — что судья судит, о чём молчит и чего требует от программы.

`design_check()` судит ЗАЯВЛЕННОЕ программой, без Revit, в этом же ходу.
Замер 22.08 на квартире из двух помещений без окон: он нашёл настоящее и
назвал виновных по именам.

    БЛОКИРУЮЩИЕ 1: HAB030x1
      HAB030: Помещение 'Гостиная' (жилая) не имеет наружного окна
    ПРЕДУПРЕЖДЕНИЯ 1: HAB030x1
      HAB030: Помещение 'Кухня' (кухня) не имеет наружного окна

🔴 УРОВЕНЬ СУДЬЯ БЕРЁТ ТОЛЬКО ИЗ САМОЙ ПРОГРАММЫ. Отметки он собирает из её
же `create_level`; ссылка на уровень МОДЕЛИ — и по id, и по имени — у него
не разрешается ничем. Та же квартира, где level заменён на
{"by": "element_id", "value": 355}: пять стен и два помещения выброшены со
словами «уровень не разрешается по программе», а вердикт — HAB000 «model
has no rooms» при объявленных помещениях, ОЦЕНЕНО 0 ПРАВИЛ ИЗ 20. Лечится
одной операцией `create_level` в той же программе. Стройке чужой уровень
по-прежнему годен: расходятся судья и стройка, а не верное с неверным.

МОЛЧАНИЕ ПРАВИЛА ВЫГЛЯДИТ ЧИСТО — ЭТО ГЛАВНАЯ ЛОВУШКА ЧТЕНИЯ. На том же
прогоне сработало 9 правил из 20, а строкой ниже стоит «НЕ ОЦЕНЕНО правил
11 из 20», и каждое названо со своей причиной:

  HAB001 HAB002  нет входа «вход с улицы»: ни одна дверь не признана
                 наружной
  HAB010         нет входа «уровень земли»
  HAB012         нечего сравнивать: планов марша нет, лестниц нет вовсе
  HAB022         высота не известна ни у одного помещения
  шесть правил   сняты профилем стадии: HAB003 HAB004 HAB011 HAB031
                 HAB042 HAB050

Правило заговорит, когда получит СВОЙ ВХОД, — причина каждого напечатана
рядом и говорит, чего программе не хватает. Повтор прогона не добавляет
входов и вердикта не меняет.

ЗАГОЛОВОК НЕ СИЛЬНЕЕ ТЕЛА, и это видно, когда блокирующих нет: пишется не
«ПРИГОДЕН», а «ПРИГОДЕН ПО 9 ПРАВИЛАМ ИЗ 20, ОСТАЛЬНОЕ НЕ ОЦЕНЕНО».

Здание с лестницей судят ПАЧКОЙ, а не одной программой — course("этаж").
Про правку уже построенного и про то, чего не обещает свидетель мутации, —
course("правка").
""" + _plan_block())


# ───────────────────────────────────────────────────────────── 8. EDIT

# 🔴 WHY THIS DID NOT FIT INTO ITS NEIGHBOR (22.08.2026). The word
# `move_elements` was NOT ONCE present in the course: all fourteen lessons
# taught how to BUILD, and not one taught how to change what was built.
# The closest technique in meaning ("GREEN IS READ FROM THE REHEARSAL",
# the "place" lesson) answers the question "what will not be checked" and
# is built around the rehearsal; here the opposite case holds — the
# rehearsal and three axes are HONESTLY GREEN, yet the circle of
# consequences still goes unchecked, because the op's obligations are
# declared about TARGETS. One text for two different outcomes would be one
# code for two cases — exactly what `unwitnessed_axes` itself was set up
# against.
def _edit() -> str:
    return _reflow("""
УРОК «ПРАВКА» — менять уже построенное и знать, о чём квитанция молчит.

ПЛАНИРОВКА ПРАВИТСЯ, И ВОТ ЧЕМ. `move_elements` двигает существующие
элементы по id из квитанции прошлого хода либо из `query_list`:

    walls = [{"by": "element_id", "value": 294076},
             {"by": "element_id", "value": 294077}]
    move_elements(targets=walls, delta_mm=[500, 0, 0])

ЖИВОЙ ПРОГОН 22.08: две перегородки сдвинуты одной операцией, и Revit
пересчитал за нас — дверь поехала за своим ХОЗЯИНОМ, площади помещений
сошлись с новой геометрией, хозяева целы, соединений не потеряно.

🔴 НО ЗЕЛЁНЫЙ У МУТАЦИИ — УТВЕРЖДЕНИЕ РОВНО О ТОМ, ЧТО ОБЪЯВИЛО ПОСТУСЛОВИЕ.
Список клауз печатает `spec("move_elements")`, и читать надо ЕГО, а не
помнить: он растёт. Говорит он про ЦЕЛИ и про то, что от целей зависит;
ПЕРЕСЧИТАННЫХ ПЛОЩАДЕЙ ПОМЕЩЕНИЙ и вердикта планировки там нет ни строки.

И `unwitnessed_axes` при этом ПУСТ. Пустой словарь значит «оп объявил
обязательства по всем трём осям» — это ответ на вопрос «бралась ли ось
проверять», а не «целы ли соседи». ЧТО именно взято на проверку, знает
только сам список клауз, и пустой словарь про него не говорит ничего.

ЗНАЧИТ КРУГ ПОСЛЕДСТВИЙ ПЕРЕЧИТЫВАЮТ САМИ, и это один дешёвый ход:
`query_inspect` по хозяину и по проёму, `query_count` по помещениям,
`design_check()` по новой планировке. Что сдвинулось — сказал свидетель;
что от этого стало с планом, не сказал никто.
""")


LESSONS: dict[str, tuple[str, object]] = {
    "единица": ("что повторить и на каком уровне; когда группа Revit", _unit),
    "этаж": ("масштаб повтора этого здания; функция, цикл, бюджет", _storey),
    "витраж": ("носитель, линии разрезки, ячейка — разобранный случай",
               _curtain),
    "даром": ("что Revit делает сам и чего не надо писать", _free),
    "границы": ("чего в языке нет и что с этим делать", _limits),
    "форма": ("джуниор против сеньора, в числах", _shape),
    "вердикт": ("что судит design_check, чего требует от программы и о чём "
                "молчит", _verdict),
    "правка": ("менять построенное: move_elements и чего не обещает "
               "свидетель", _edit),
    # HOME FOR DISPLACED LITERALS (09.08). The one lesson that is not
    # written here but is ASSEMBLED from `skill.py` objects: the decompiles
    # live there together with their own chain of reasoning and their own
    # tests (working ones compile, refused ones refuse), and a second copy
    # of the same programs would silently diverge from the first. The
    # import is lazy: `skill` pulls in `macros` and `compiler`, and this
    # module is called from the sandbox.
    # SECOND HOME FOR THE DISPLACED (15.08). §4 of the course — the
    # situational reference — moved here when the description broke the
    # 30 000 ceiling: it is needed AFTER the shape is chosen, i.e. exactly
    # when it can be asked for. It is assembled from `skill.TECHNIQUES`,
    # not rewritten: two copies of the techniques would have diverged
    # silently.
    # THIRD HOME FOR THE DISPLACED (16.08). The "дом" lesson is not about
    # the language but about the BUILDING, and it lives as a separate
    # module because its numbers are TAKEN FROM the decompile corpus
    # (heights, thicknesses, grid spacing, areas), rather than written
    # alongside. The measurement the lesson grew out of: in the course
    # "create_wall" had 9 occurrences and "floor height" had 0 — we taught
    # the model to talk and did not tell it what about.
    "дом": ("из чего состоит настоящее здание: высоты, толщины, шаг, порядок",
            lambda: __import__(
                "kir.course.building", fromlist=["building"]
            ).lesson()),
    "квартира": ("что внутри жилья и какого размера: замер 11 484 помещений",
                 lambda: __import__(
                     "kir.course.building", fromlist=["building"]
                 ).lesson_flat()),
    "геометрия": ("чем сказать кривое, наклонное и вычтенное",
                  lambda: __import__(
                      "kir.skill", fromlist=["skill"]
                  ).build_shape_vocabulary_text()),
    "приёмы": ("чем считать и что строить, когда упёрся: форма, макросы, тип",
               lambda: __import__(
                   "kir.skill", fromlist=["skill"]
               ).build_techniques_text()),
    # 🔴 THE SECOND HALF OF THE CATALOG (22.08.2026). "techniques" grew to
    # 4,882 characters against a 3,300 ceiling, and the sandbox channel
    # truncates at 4,000 — the model was not getting the last three
    # techniques (level, host, coordinates) AT ALL. The argument for the
    # split, and the cost measured on itself, are at `_TECHNIQUES_PLACEMENT`.
    "место": ("куда ставить: уровень, хост, координаты; и порядок большой "
              "программы",
              lambda: __import__(
                  "kir.skill", fromlist=["skill"]
              ).build_placement_techniques_text()),
    "разборы": ("четыре разбора целиком — рассуждение и программы",
                lambda: __import__(
                    "kir.skill", fromlist=["skill"]
                ).build_walkthrough_programs_text()),
    # DISPLACED 19.08.2026 FROM THE PERMANENT TEXT. The argument is at §7
    # in `skill.py`: a refusal carries its own next move WITHIN ITSELF, so
    # retelling it is paid for on every turn, while it is needed at the
    # moment of the refusal.
    "случаи": ("рассуждение трёх разборов: трек, отказ селектора, хост",
               lambda: __import__(
                   "kir.skill", fromlist=["skill"]
               ).build_walkthrough_cases_text()),
    "отказы": ("что делать, когда пришёл KIR-*: селектор, бюджет, retry",
               lambda: __import__(
                   "kir.skill", fromlist=["skill"]
               ).build_refusal_playbook_text()),
}

ORDER: tuple[str, ...] = ("дом", "квартира", "единица", "этаж", "витраж",
                          "даром", "границы", "форма", "геометрия", "разборы",
                          "случаи", "приёмы", "место", "правка", "вердикт",
                          "отказы")


def index() -> str:
    rows = ["КУРС ПО `program_py`: питон считает, KIR доказывает.",
            'Зови course("<тема>") — урок печатается в квитанцию ЭТОГО хода.']
    rows += [f"  {name:<10} {LESSONS[name][0]}" for name in ORDER]
    rows.append("  recipe()   рабочие скрипты с замеренными числами")
    rows.append("  score()    твоя программа против базовой линии корпуса")
    return "\n".join(rows)


def lesson(topic: str) -> str:
    key = (topic or "").strip().lower().replace("ё", "е")
    for name in LESSONS:
        if name.lower().replace("ё", "е") == key:
            return LESSONS[name][1]()
    raise KeyError(f"урока «{topic}» нет. Есть: " + ", ".join(ORDER))


__all__ = ["LESSONS", "ORDER", "index", "lesson"]
