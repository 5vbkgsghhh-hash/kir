"""A short training course: how the people who know how to work with KIR do
it.

GENRE. Not a reference and not a cheat sheet, but a course: after it, you sit
down and work. First the mental model of the system (without it, advice has
nothing to hang on), then how a pro starts, then end-to-end walkthroughs of
real tasks from intent to acceptance, a catalog of techniques, a playbook of
refusals, and a comparison of a good program against a bad one on ONE task.

DIVISION OF DUTIES — why there are no listings here:

* `schema_gen.program_schema()` — WHAT can be written: every operation, every
  field, the bounds, the enums, the macro syntax. Measured 30.07: 22,927
  o200k tokens, and it is exhaustive. Listing the same thing in prose would
  mean paying twice and drifting from the schema on the very first edit.
* `tool_doc.NOTES` — TRAPS: facts about the API that cannot be derived from
  the schema.
* THIS module — SKILL: how to think, where to start, what the work looks
  like as a whole. Not one listing of operations, not one field description.

FOUR RULES THAT KEEP THE COURSE HONEST.

1. EXAMPLES ARE ONLY REAL ONES. The decompile programs live here as LIVE
   objects and are rendered into text from those same objects, and
   `test_skill.py` compiles exactly those objects: what is shown and what is
   checked cannot drift apart by construction. Refusals in the walkthroughs
   are verbatim from live runs (`data/reasoning_traces.jsonl`,
   `data/telemetry/kir_rejections.jsonl`). An invented example in the course
   is a lie that the model will learn and confidently repeat.
2. NOT ONE NUMBER WITHOUT A BASIS. Constant numbers are interpolated from
   constants; measured numbers stand as a literal next to their provenance.
3. WHAT WE TEACH COMPILES; WHAT WE CALL A BOUNDARY REFUSES. The first is held
   by positive tests, the second by negative controls. Advice that runs ahead
   of the compiler produces CONFIDENT failures instead of unconfident ones,
   and that is a worse outcome than having no course at all.
4. NOT ONE OVERLAP WITH `NOTES` — checked mechanically.

THE PLAYBOOK RESTS ON THE CONTRACT, not on a line count in the journal. One
attempt can spawn many diagnostics; without an explicit `attempt_id` their
frequency is unknown.

COST. The instrument arrives in full with every request, so the course is
paid for every time, and a saved round costs a whole batch plus the thinking
time (85% of a turn's time is the model thinking, measured 28.07). The
payback arithmetic is in
`test_tool_doc.test_description_stays_small_next_to_the_schema`.
"""
from __future__ import annotations

import json
import textwrap

from kir import compiler, macros
from kir.compiler import MAX_OPS_PER_PROGRAM

# ─────────────────────────────────────────────────────────────── 1. The setup

#: The mental model a newcomer lacks. Sources: kir/CLAUDE.md (Mission, The two
#: directions, Invariants, "Compiles is not builds"), ground.py (silent-
#: fallback ban), authoring.py (ONE Transaction per program, in-txn commit-
#: gate), contracts.py (the law of the census).
SYSTEM_MODEL: tuple[str, ...] = (
    "РАЗДЕЛЕНИЕ ТРУДА. Ты планируешь — компилятор отвечает за правильность. "
    "Единицы, версии Revit API и транзакции принадлежат ему, замысел — тебе. "
    "Поэтому в языке нет перевода миллиметров в футы, ветвления по версиям и "
    "открытия транзакций: это не пробелы, это граница ответственности.",

    "ПРОГРАММА — ДАННЫЕ, А НЕ КОД, и отсюда всё остальное. Её проверяют "
    "ЦЕЛИКОМ до того, как Revit тронут; отказ приходит на КОНКРЕТНОЕ поле "
    "конкретной операции; «почти сработало» невыразимо. Ты не отлаживаешь "
    "выполнение — ты правишь значение и отправляешь снова.",

    "ПЯТЬ СТАДИЙ ПУТИ, отказ возможен на каждой: разбор формы JSON → "
    "ЗАЗЕМЛЕНИЕ (символьный селектор «стена типа X» превращается в конкретный "
    "ElementId по снимку открытой модели) → проверка типов и пределов → "
    "эмиссия C# под КОНКРЕТНУЮ версию Revit (2021-2026, эмиттер ветвится) → "
    "исполнение. Буква в коде отказа называет стадию, а стадия говорит, что "
    "чинить.",

    "ЗАЗЕМЛЕНИЕ ИДЁТ ПО СНИМКУ, А НЕ ПО ДОГАДКЕ: тихая подстановка запрещена "
    "правилом. Нет снимка — отказ, а не выбор наугад; кандидатов несколько — "
    "отказ со списком, а не первый попавшийся. Поэтому «поставь на втором "
    "этаже» само по себе неисполнимо: «второй этаж» становится адресом только "
    "через снимок.",

    "ИСПОЛНЕНИЕ — ОДНА ТРАНЗАКЦИЯ НА ПРОГРАММУ. После создания идёт "
    "`Regenerate`, затем постусловия ПЕРЕЧИТЫВАЮТ созданное и сравнивают с "
    "заявленным; любое нарушение откатывает транзакцию целиком. Частично "
    "неверная программа невыразима как принятый результат: либо построено и "
    "подтверждено, либо в модели не осталось ничего.",

    "СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ, А НЕ ВЫЗОВ. Каждая пишущая операция объявляет "
    "постусловие, которое эмиттер превращает в C#, читающий созданный элемент "
    "ОБРАТНО из модели и сверяющий с допуском. Проверка, подтверждающая лишь "
    "то, что сеттер отработал, считается здесь дефектом. Поэтому «команда "
    "прошла» и «получилось заказанное» — разные утверждения.",

    "КВИТАНЦИЯ ГОВОРИТ, ЧТО ПОЛУЧИЛОСЬ, А ПРОГРАММА — ЧТО ПРОСИЛИ. Квитанция "
    "обязана сходиться: создано + отказано + закрывшихся-без-элемента == "
    "всего операций. Расхождение — это класс «молча не создано», а не мелочь "
    "отчёта.",

    "ГЛАВНЫЙ ИНВАРИАНТ: НОЛЬ МОЛЧАЛИВО-НЕВЕРНЫХ ИСХОДОВ. Любой вызов либо "
    "построен со свидетелем, либо типизированно отказан; «ok» с ошибкой внутри "
    "— запрещённое состояние. Отказ здесь НОРМА и работает на тебя: система "
    "предпочтёт громко отказать, чем тихо сделать не то.",

    "«КОМПИЛИРУЕТСЯ» НЕ ЗНАЧИТ «ПОСТРОЕНО». Что программа собралась в C# — "
    "одно утверждение; что Revit построил описанное — другое, и доказывает "
    "его только свидетель на живой модели. Не выдавай первое за второе, "
    "докладывая о работе.",
)

# ─────────────────────────────────────────────────── 2. Where a pro starts

# Illustrative opaque ID: replace it with an identity read from the chosen document.
ELEMENT_STATE_READ = {"ops": [{"op": "query_element_state", "id": "state",
    "unique_id": "00112233-4455-6677-8899-aabbccddeeff-00000123"}]}
ELEMENT_STATE_READ_LIMITS = (
    "`query_element_state` перечитывает UniqueId из ТОГО ЖЕ документа. Замени учебный "
    "id реальным: компиляция не доказывает существование элемента. `not_found` и "
    "`unavailable` — не успех. `include_type_definition` по умолчанию False; True "
    "читает ограниченное описание поддержанного WallType/FloorType по UID самого типа. "
    "Запрос не выбирает документ, не доказывает владение и не является BIM-приёмкой.")

HOW_A_PRO_STARTS: tuple[str, ...] = (
    "СНАЧАЛА ЧИТАЮТ МОДЕЛЬ. `query_types` даёт закрытый пул типов {id, name}; "
    "`query_list` — id по фильтру; `query_inspect` — поля и габарит одного элемента; "
    "`query_count` — количество и `group_by`. `query_surface` читает определение грани "
    "и запрошенную сетку точек/нормалей, совместимые с языком создания. "
    "`query_element_state` перечитывает известный UniqueId в том же документе: identity, "
    "параметры уровня и явные not_found/unavailable. Это не BIM-приёмка. "
    "`query_level_plan` — след уровня ПАЧКОЙ (прочие чтения — по элементу). "
    "Пределы и пример: course(\"разборы\").",

    "ЧТЕНИЕ ОКУПАЕТСЯ НЕМЕДЛЕННО. Если задаче нужен тип или уровень, "
    "начни с `query_types`, а не с угадывания. Если KIR-G101/G102 уже несёт "
    "в `candidates` строки с `id`, точный кандидат можно выбрать без второго "
    "чтения, пока снимок модели не изменился. KIR-G104 означает пустой модельный "
    "пул: это факт о снимке, а не разрешение выдумать `element_id`.",

    "ПРЕДИКАТ ПРИЁМКИ ОБЪЯВЛЯЮТ ДО ПОСТРОЙКИ. Критерий, придуманный после "
    "того, как результат виден, всегда описывает полученное — это и есть "
    "«выглядит правильно». Предикат обязан УМЕТЬ ПРОВАЛИТЬСЯ: цель, которую "
    "нельзя не выполнить, закрывает прогон, не построивший ничего.",

    "ПРОБА ПЕРЕД ПАЧКОЙ. Незнакомую форму отправляют одной операцией и читают "
    "квитанцию; форма доказана — идёт пачка. Полная пачка незнакомой формы "
    "отказывает ВСЯ разом: замер 28.07 — 20 балок с пропущенным `level` дали "
    "KIR-G102 x40 и стоили раунда целиком.",

    # EDIT OF 09.08 (the same move and the same reason as the 04.08 merge into
    # `tool_doc.AUTHORING_IDIOMS`): the measurement "210 out of 586" and the
    # recipe "repeating — a macro, heterogeneous — per program" stood TWICE in
    # one request — here and in the refusal playbook below, where they are
    # actually needed, because there they are read by a model that has
    # already gotten a KIR-L001. What stays here is what the playbook lacks: a
    # rule of FORM that must be known BEFORE the first program.
    "КРУПНОЕ ЗДАНИЕ — ПАЧКА ПРОГРАММ, А НЕ ОДНА БОЛЬШАЯ. Бюджет одной "
    f"программы — {MAX_OPS_PER_PROGRAM} операций ДО раскрытия макросов, и он "
    "мал намеренно; что делать при его нарушении — в плейбуке отказов "
    "(KIR-L001).",
)

# ──────────────────────────────────────────────────────────── 3. The form of a repeat

#: Measurements: artifacts 04-tower-comparison.txt and
#: 00-refute-before-code.txt, live run 28.07 (118 beams = 7 rounds; the C#
#: shoulder — 343 beams from one program made of a three-line function).
SHAPE_OF_REPETITION: tuple[str, ...] = (
    "Первый вопрос задачи: что повторяется и МЕНЯЕТСЯ ЛИ ЧТО-ТО ОТ ПОВТОРА К "
    "ПОВТОРУ. Ответ выбирает форму программы, и цена ошибки здесь — раунды.",

    "Меняющееся ВЫЧИСЛЯЕТСЯ (синус, offset контура, интерполяция, сумма) — "
    "тогда форма это `program_py`: питон считает, KIR строит. Трек `series` "
    "кусочно-линеен, `stack.transform` линеен целиком; кривую, которую не "
    "выразить узлами, считают арифметикой — и расхождение приближения "
    "печатают числом, иначе оно молчаливое.",

    "Повторяется с МЕНЯЮЩИМСЯ числом — `series` с `track`. Сужение башни, скат "
    "кровли, переменный шаг осей — одна операция, а не список координат. "
    "Замер: тот же силуэт — 160 операций и 8 раундов перечислением против 1 и "
    "1 треком, при побайтово одинаковом C#.",

    "Не подменяй трек линейным `stack.transform`: у него ОДНА прямая от низа "
    "до верха. На силуэте с тремя изломами лучшая возможная такая прямая "
    "промахивается на 20.62 м — 69% полуширины. Излом => узел трека.",

    "Повторяется ТОЖДЕСТВЕННО по этажам — `stack` (он заводит уровни сам). "
    "Сетка осей — `grid_array`. Фрагмент в N мест без изменений — "
    "`create_group`: панель на 19 операций в 40 местах даёт 760 элементов "
    "одной программой. `series` уровней НЕ создаёт — уровень объявляется "
    "отдельным опом и берётся по `ref`.",

    "Ничего не повторяется — пиши прямо. Макрос ради макроса дороже: трек, у "
    "которого узлов столько же, сколько повторов, — то же перечисление в "
    "другом костюме.",
)

#: The demand-channel topic for the form dictionary.
SHAPE_VOCABULARY_TOPIC = "геометрия"

#: 🔴 THE STANDING TEXT CARRIES ONLY WHAT'S NEEDED TO AVOID PICKING THE WRONG
#: FORM.
#:
#: The rule is not mine: it was bought on 15.08, when the description broke
#: through the 30,000 ceiling and the author's first move was to raise the
#: ceiling — "and that was the wrong move: the ceiling is paid for by EVERY
#: request". Back then six situational techniques moved out to on-demand, and
#: the three that decide the form stayed.
#:
#: Here it's the same case and the same arithmetic. Baseline measured 21.08:
#: the task "a slab with a splined edge" did NOT CONVERGE in 8 turns, because
#: the author did not know a spline existed — checked by grepping the course:
#: neither "spline" nor "plane" nor "boolean" was mentioned EVEN ONCE. Eight
#: turns at ~21,700 schema tokens each is 174,000 tokens wasted against 110
#: characters of a pointer that get paid for on every turn.
#:
#: So what rides permanently is KNOWLEDGE THAT SOMETHING EXISTS, and the "how
#: exactly" rides on demand: not knowing a spline exists, no one will ever
#: reach for it; knowing it, they'll ask in one line.
SHAPE_VOCABULARY_POINTER = (
    "СЛОВАРЬ ФОРМЫ. Ребро контура трёх родов: отрезок · дуга "
    "(`arcs`) · СПЛАЙН (`splines`); окружность — ДВЕ полудуги. Эскиз — "
    "на любую плоскость (`plane`), не "
    # 🔴 `offset`/`thicken` ARE NAMED HERE AT A COST OF EXACTLY ZERO
    # CHARACTERS (F-293, 29.08.2026). The reachability guard reads the
    # RENDERED doc, and a name sitting in the sandbox and named nowhere is
    # dark by OVERSIGHT, not by decision. But the standing text stood 20
    # characters from the 30,000 ceiling, and the first draft of this line ate
    # up 18 of them. So this is not an "addition" but a REWRITE: two names
    # were added in, and room for them was squeezed out of neighboring phrases
    # of the same line ("comes in three kinds" -> "of three kinds", "is
    # placed on" -> "—", "part of the boolean" -> a parenthetical). Pointer
    # length 326 characters BEFORE and 326 AFTER — verified by execution, the
    # ceiling untouched.
    # 🔴 AND A THIRD EDIT OF THIS LINE AT A COST OF ZERO CHARACTERS
    # (01.09.2026). A free-form dictionary was set up (`course/rhino.py`), and
    # by the same law that split spline and plane apart on 21.08, only
    # knowledge that its three names EXIST rides PERMANENTLY: not knowing
    # `loft` exists, no one will ever reach for it. Room was squeezed out of
    # neighboring phrases of the SAME line ("for extrusion/blend" -> the
    # parenthetical `plane`, "with an arbitrary profile" -> "with a profile",
    # "The body is thin starting at 1 mm" -> "The body starts at 1 mm").
    # Length 326 BEFORE and 326 AFTER — verified by execution, the ceiling
    # untouched.
    "только в план. Вычитать — профилем (булева `prism`). "
    "Контур: `offset`/`thicken`. Тело от 1 мм. "
    "Свобода: `loft`/`section`/`faces`/`promote`. "
    f"Подробности — course(\"{SHAPE_VOCABULARY_TOPIC}\").")


SHAPE_VOCABULARY: tuple[str, ...] = (
    # 🔴 THE CHAPTER WAS SET UP BY A MEASUREMENT, NOT A WISH FOR
    # COMPLETENESS (21.08.2026). The author's baseline loop: out of eleven
    # tasks, three did not converge, and one of them was "a slab with a
    # splined edge". The capability was built on 20.08 and works; the course
    # was SILENT about it, and the schema has a field but no "when to reach
    # for this". Checked by grepping the course: neither "spline" nor "plane"
    # nor "boolean" was mentioned EVEN ONCE.
    #
    # So the chapter is short and entirely about CHOICE, not syntax: the
    # reference already rides in the same request as the schema, and
    # retelling it here would mean paying twice for one idea.
    "СЛОВАРЬ ФОРМЫ: чем сказать кривое, наклонное и вычтенное. Справочник в "
    "схеме; здесь — за чем тянуться и когда.",

    "РЕБРО КОНТУРА БЫВАЕТ ТРЁХ РОДОВ, и это решает автор, а не компилятор: "
    "отрезок по умолчанию · дуга через `arcs: [{edge, bulge|radius_mm}]` · "
    "СПЛАЙН через `splines: [{edge, via_mm}]`. Волнистый край плиты, обвод "
    "пятна застройки, лекальная стена — это сплайн, а не сто отрезков. "
    "🔴 ОКРУЖНОСТЬ — ЭТО ДВЕ ПОЛУДУГИ: кольцо из ДВУХ точек законно, если "
    "оба ребра кривые (так её отдаёт и сам Revit из семейств). Круглая "
    "колонна, дымоход, воронка пишутся двумя точками и двумя `bulge: 1.0`.",

    "ЭСКИЗ ЛЕЖИТ НЕ ТОЛЬКО В ПЛАНЕ. `plane: {origin_mm, normal, x_dir}` у "
    "`create_solid_extrusion` и `create_solid_blend` кладёт профиль на любую "
    "плоскость: окно на грани стены (`normal: [0,-1,0]`), лоскут оболочки "
    "двоякой кривизны, наклонная ламель фасада. Поле опущено — плоскость "
    "горизонтальна, поведение прежнее. Направление выдавливания — НОРМАЛЬ "
    "плоскости, а не мировая Z.",

    "ВЫЧТЕННОЕ ГОВОРИТСЯ БУЛЕВОЙ, И ОПЕРАНД БЫВАЕТ НЕ ТОЛЬКО ПРИМИТИВОМ. "
    "`create_solid_boolean.parts` принимает `box` · `sphere` · `cylinder` · "
    "`prism` (профиль контуром плюс `height_mm`). Ниша произвольного "
    "очертания, подрезка под пилон, проём с отверстием — это `prism`, а не "
    "набор коробок. Операнды рождаются и умирают ВНУТРИ опа: сослаться на "
    "чужой оп нельзя, профиль задаётся значением.",

    # 🔴 THE SUBSTANCE IS HERE, ON DEMAND, NOT IN THE STANDING TEXT (F-293,
    # 29.08.2026). The standing cost of this chapter is ZERO: it rides on
    # `course("geometry")`. Only KNOWLEDGE THAT IT EXISTS went into the
    # pointer — by the same rule that split spline and plane apart on 21.08.
    "ПЛОСКИЕ ОПЕРАЦИИ НАД КОНТУРОМ СЧИТАЕТ ЯЗЫК, А НЕ ТЫ РУКАМИ. "
    "`offset(контур, d)` — смещённый контур: НАРУЖУ при положительном, ВНУТРЬ "
    "при отрицательном, и «наружу» берётся из обхода самого контура, а не из "
    "порядка, в котором набраны точки. `thicken(путь, ширина)` — полоса "
    "ПОСТОЯННОЙ ширины вокруг открытой ломаной: из линии контур. Отмостка, "
    "стяжка по краю плиты, переплёт, раскладка, рамка — это они. "
    "🔴 РУКАМИ ОНИ СЧИТАЮТСЯ НЕВЕРНО РОВНО ТАМ, ГДЕ ВАЖНО: на изломе "
    "смещённые рёбра надо ПЕРЕСЕКАТЬ, а сдвиг вершины по нормали даёт полосу "
    "уже заказанной (у прямого угла 70.7 вместо 100). Вырожденный вход — "
    "черта вместо кольца, самопересечение — НАЗВАННЫЙ отказ со следующим "
    "ходом, а не молча другая фигура. Результат — форма `poly`, её берёт "
    "любой контурный оп.",

    # 🔴 THE CHAPTER WAS SET UP BY A LOOP MEASUREMENT, NOT A WISH FOR
    # COMPLETENESS (01.09.2026). The owner's word: "an LLM does far better in
    # three.js than in Revit." The measured reason: of 82 operations, 47
    # require a catalog from a snapshot, 32 need a level, 12 need a host; in
    # the live corpus 121 turns went into RECONNAISSANCE instead of building.
    # Every such slot is a question of "what do you call this here", and the
    # author answers every one of them with caution. Caution is the booth.
    # The chapter is paid for at ZERO: it rides on `course("geometry")`, and
    # exactly three names went into the standing text at a cost of minus seven
    # characters.
    "СВОБОДНАЯ ФОРМА — И ОНА ОСТАЁТСЯ БИМОМ. `loft([(низ,0),(верх,30000)])` "
    "даёт тело: ручки опов И меш, у которого спрашивают: `faces(тело)` — грани "
    "с нормалью, площадью, кольцом, готовым `plane` под эскиз и ТОЛЩИНОЙ "
    "(когда встречная грань той же площади ровно одна); `section(тело, z)` — "
    "срез родом `region`, тем же, что берут пол и потолок. Одной операцией: "
    "`blend` — переход, `revolve` — вращение профиля. Плюс `move`/`rotate`/"
    "`mirror`/`scale`/`array`: род сохраняется. Тип — СВОЙСТВОМ: "
    "`by_property(\"Width\", 380)`: толщину автор знает, имя чужого типа нет. "
    "🔴 ЛОФТ КУСОЧНЫЙ: между сечениями поверхность ПРЯМАЯ, кривизна — ЧИСЛОМ "
    "СЕЧЕНИЙ. Где посчитать нельзя — НАЗВАННЫЙ отказ, а не "
    "правдоподобное число: сечение надвое, меш у сечений с разным числом "
    "точек, `tol_mm` у сужения (заземление равняет ТОЧНО).",

    "ТОНКОЕ — ЗАКОННО. Высота тела от 1 мм: стекло, полка, столешница, "
    "накладка выражаются напрямую. Замер живым Revit: 1 · 3 · 10 · 20 · 50 · "
    "76 мм — построены все, объём точный. Сторона ПРОФИЛЯ по-прежнему от "
    "100 мм, и это другая величина: вырожденно узкая полоса в плане почти "
    "всегда описка.",
)


# ────────────────────────────────────────────────────── 4. Techniques by situation

TECHNIQUES: tuple[tuple[str, str], ...] = (
    # THE LAST SENTENCE MOVED HERE ON 09.08 from `tool_doc.AUTHORING_IDIOMS`,
    # where it sat inside a paragraph that LISTED slots with the `ref` form.
    # The listing was removed: it retold `ParamSpec.ref_kinds`, and the
    # registry now answers this question itself, and PER-SLOT — `spec(<op>)`
    # prints the forms of every selector. The 27.07 correction ("for
    # type/symbol ref doesn't work"), though, cannot be read off the registry
    # at a glance and costs a whole round, so it is kept verbatim — and it is
    # held by `test_ref_rule_matches_the_compiler`.
    # ── THE CHAPTER ON BUILDING DESIGN, 20.08.2026. Everything below is from
    # LIVE runs of that day (Revit 2026), not from general considerations.
    # Numbers stand either interpolated from constants, or as a literal with
    # provenance.
    ("ФОРМА И СМЫСЛ — ДВЕ РАЗНЫЕ ОСИ, И ПУТАТЬ ИХ ДОРОГО",
     "Спроси про каждую вещь: даёт ли Revit ей СМЫСЛ. Стена, перекрытие, "
     "потолок, кровля, колонна несут тип, слои, параметры и попадают в "
     "спецификацию — это элементы. DirectShape, NURBS-поверхность, бленд, "
     "результат булевой несут ТОЛЬКО геометрию: ни типа, ни слоёв, ни строки "
     "в спецификации, и человек их не отредактирует. Квитанция говорит это "
     "сама полями bim_semantics, has_type, schedulable_as_building_element — "
     "читай их, а не смотри на картинку: объём совпадает, смысла нет. "
     "Практический вывод: несущее и ограждающее строй элементами, а свободную "
     "пластику — геометрией, и не подменяй одно другим. Смысл И форму разом "
     "даёт лишь то, у чего контур свой: перекрытие и потолок по контуру "
     "принимают кривой край, оставаясь настоящими элементами."),

    ("ПИТОН СЧИТАЕТ — KIR СТРОИТ",
     "Скрипт автора — настоящий питон: циклы, функции, рекурсия, свои "
     "структуры данных; math, itertools, functools, collections, dataclasses "
     "всегда, а numpy и shapely — когда оператор открыл калитку. Считай "
     "геометрию ТАМ: периметр циклом по рёбрам, панели вложенным циклом, "
     "оболочку синусоидой, отверстия списковым включением. Операции несут "
     "только ЭФФЕКТ. Это и есть разница с узловым редактором, где нет ни "
     "цикла, ни функции: четыре стены по периметру — это цикл по четырём "
     "рёбрам, а не четыре скопированных блока, и правится он в одном месте."),

    ("ПОРЯДОК ДЛЯ БОЛЬШОЙ ПРОГРАММЫ",
     f"Сперва ЧИТАЙ: query_types по нужным пулам (уровни, типы стен, типы "
     f"потолков) и бери element_id — угаданный id не переживёт другой "
     f"документ. Потом уровни, потом несущее, потом ограждающее, потом "
     f"свободная форма. Предел одной программы — {compiler.MAX_OPS_PER_PROGRAM} "
     f"операций до макросов; упёрся — это две программы, а не спор с "
     f"пределом. И помни про транзакцию: программа атомарна, отказ ОДНОЙ "
     f"операции откатывает ВСЁ. Поэтому большой фасад режут на пачки: "
     f"замер 20.08 — из 48 независимых NURBS-панелей одной программы две "
     f"упали в BRepBuilder и унесли с собой 46 построенных."),

    ("ЗЕЛЁНЫЙ ЧИТАЕТСЯ С РЕПЕТИЦИИ, А НЕ СО СВИДЕТЕЛЯ",
     "В квитанции сперва смотри rehearsal_note_ru и will_not_be_checked: там "
     "написано, что проверено НЕ БУДЕТ, и написано ДО исполнения. Ось, "
     "которую никто не смотрел, и ось, которая прошла, выглядят одинаково "
     "зелёно. Только потом — тройка geometry_ok / semantic_ok / topology_ok и "
     "named_absences. Отдельно: execution=unconfirmed значит «эффект "
     "возможен, подтверждения нет» — повтор ЗАПРЕЩЁН до сверки счётчиком, "
     "иначе в модели появятся дубли."),

    ("КОГДА REVIT ЧЕГО-ТО НЕ УМЕЕТ — ЧИТАЙ ОБРАТНО И СТРОЙ ЗАНОВО",
     "Смещения поверхности вдоль собственных нормалей в Revit нет вовсе. "
     "Приём, проверенный живьём 20.08: прочитать построенную грань "
     "(точки и нормали меряет сам Revit), сдвинуть их питоном и построить "
     "новую оболочку. Тот же приём закрывает скругление, оболочку, деление, "
     "морфинг — всё, что чистая математика: считает автор, строит KIR. "
     "Круг двухходовой по устройству: результат чтения приходит ПОСЛЕ "
     "исполнения, значит это две программы, а не одна."),

    ("АДРЕСАЦИЯ ВНУТРИ ПРОГРАММЫ",
     "То, что программа создаёт сама, адресуется {\"by\":\"ref\","
     "\"value\":\"<id опа выше>\"} — уровень, хост, цель. Ссылки вперёд нет: "
     "`ref` разрешается только по операциям ВЫШЕ. Через границу программы "
     "`ref` не проходит вовсе — хост из прошлой программы берут по "
     "`element_id` из квитанции. Для `type`/`symbol` ref НЕ работает вовсе: "
     "типоразмер адресуется каталогом, по element_id или name."),

    ("ВЫБОР ТИПА И СЕМЕЙСТВА",
     "Надёжный порядок один: `query_types`, затем выбор по `element_id`. "
     "Имена в реальных проектах повторяются, поэтому выбор по имени — ставка. "
     "Повторяющийся селектор задают ОДИН раз в `defaults` конверта "
     "(`level`, `symbol`, `type`, `top_level`); опустить поле в надежде на "
     "умолчание — не то же самое. И УМОЛЧАНИЕ ЕСТЬ СВОЙСТВО ДОКУМЕНТА, А НЕ "
     "ОПА: замер 22.08 в «Проект1» — `create_door` умолчание нашёл, "
     "`create_window` рядом отказал и назвал девять типов окон с их id. "
     "Значит «называй тип явно» — не общее правило, а следствие пула: "
     "пул из одного даёт умолчание, пул из девяти даёт отказ со списком."),

    ("ПРЕДЕЛЫ МАКРОСОВ — ЧТО ДЕЛАТЬ, КОГДА УПЁРСЯ",
     f"Трек ОБЯЗАН покрывать каждый читаемый индекс: экстраполяции нет, "
     f"зажима к крайнему узлу нет — есть отказ. До {macros.MAX_TRACK_PARAMS} "
     f"имён и {macros.MAX_TRACK_NODES} узлов в треке; объявленный, но "
     f"неиспользованный параметр — тоже отказ. Один `series` разворачивается "
     f"максимум в {macros.MAX_SERIES_OPS} опов (count x len(items)): макрос не "
     f"вправе забрать весь бюджет программы, иначе не останется места на "
     f"уровни и типы, с которых она обязана начаться. Нужно больше — это два "
     f"`series`, а не спор с пределом. Макрос внутри макроса не "
     f"разворачивается."),

    ("УРОВНИ И ОТМЕТКИ",
     "Уровень — обязательный контекст почти всего. Своя программа создаёт его "
     "`create_level` и берёт по `ref`; чужой — по имени или id из "
     "`query_types(pool='levels')`. ВАЖНО: смещение от уровня "
     "(`height_offset_mm` и родня) ограничено по модулю, потому что это "
     "СМЕЩЕНИЕ, а не отметка. Нужен ярус на +57 м — заводят уровень, а не "
     "растягивают смещение. СУДЬЯ ЖЕ ЧИТАЕТ ТОЛЬКО ПРОГРАММУ и чужой уровень "
     "не разрешает вовсе: чем это кончается — course(\"вердикт\")."),

    ("ХОСТ: ОКНА, ДВЕРИ, МАРКИ",
     "Проём ставится НЕ в координату модели, а вдоль своего хоста: `host` "
     "плюс `offset_mm` — расстояние по стене от её начала, плюс `sill_mm` — "
     "отметка низа. Попытка задать окну [x,y,z] отказывается как неизвестное "
     "поле: своей координаты у проёма нет, так он устроен в Revit."),

    # RELATE, 04.08. The lesson was EXPANDED, not supplemented with something
    # new: an address from grid lines is a second form of a POINT, i.e. the
    # same idea, and keeping it as a separate paragraph would mean paying for
    # one idea twice on every request. The prose budget sits at the ceiling
    # the operator declared (10,000 tokens, measured 04.08: 9,954 before this
    # edit), so the text must displace itself — which is what was done here:
    # the wording about millimeters and dimensionality was tightened, the
    # facts kept verbatim. What an address CANNOT do (an axis created by this
    # same program) sits not here but in the KIR-G108 refusal itself — that's
    # where it's needed, and there it's free.
    ("КООРДИНАТЫ И ЕДИНИЦЫ",
     "Всё в МИЛЛИМЕТРАХ: переводить во внутренние единицы не нужно. "
     "Размерность точки названа в схеме; плоская точка там, где ждут "
     "пространственную, — отказ. Точку можно задать ОТ ОСЕЙ: отступ — "
     "число по перпендикуляру к оси, сторону называет параллельная "
     "соседка (`toward`), знака нет."),

    ("ТОЛЩИНЫ И СЕЧЕНИЯ",
     "Толщина конструкции — это ТИП, а не поле операции: «перекрытие 200 мм» "
     "= `create_type(...)`, затем `create_floor(type=<он>)`. Своего поля "
     "толщины у `create_floor`/`create_wall` нет, и это не значит, что задача "
     "невыполнима."),

    # BOTH HANDS FOLDED TOGETHER, NOT ONE CHOSEN OVER THE OTHER (merge of
    # 09.08).
    # * this file became the ONE AND ONLY copy of the idea: `tool_doc.NOTES`
    #   carried it in its own words (620 characters), i.e. it was paid for
    #   twice on every request. Both halves the text lacked were moved here
    #   verbatim — the ceilings in the listing and the impossibility of a
    #   human edit;
    # * the solids wave EXPANDED the fact from one op to three: the honest
    #   label and the ban on impersonation are THE SAME for the mesh and for
    #   both parametric solids, because all three put the result into a
    #   DirectShape and take their categories from one closed table. They
    #   therefore don't get a second block of the course.
    # Not a single fact was lost in the merge: the closed list of categories
    # is printed by `spec("create_directshape")` straight from the registry
    # itself.
    ("СВОБОДНАЯ ФОРМА",
     "Чего не выразить контуром — `create_directshape` мешем, а выдавливание и "
     "вращение контура — `create_solid_extrusion`/`create_solid_revolve`. "
     "Плата названа честно: геометрия БЕЗ BIM-смысла, ни типа, ни параметров, "
     "ни строки в спецификации, и человек не отредактирует её как стену — "
     "только удалить и построить заново. Стены, перекрытия, кровли, потолки, "
     "колонны, балки и лестницы делают своими операциями всегда, когда задача "
     "ими выражается; категорий walls/floors/roofs/columns у них нет вовсе, "
     "чтобы форма не могла выдать себя за них."),

    ("ОДИНОЧКИ И ОПАСНЫЕ",
     "Часть операций живёт по особым правилам: одна требует собственной "
     "программы, другая — явного разрешения в конверте, сетевые описывают "
     "всю трассу целиком одним опом. Все три случая названы в ловушках выше; "
     "приём здесь один — прочитать про операцию ДО того, как ставить её в "
     "пачку из двадцати."),
)

# ────────────────────────────────────────────────────────────── 5. Three walkthroughs

#: Walkthrough 1 — a fragment of a real artifact,
#: kir-night/artifacts/02-tower-series-program.json (8 track elements there:
#: 4 legs + 4 ties, count=20 => 160 operations after expansion).
TOWER_TRACK: dict = {
    "ir_version": "1.0",
    "intent": "башня с сужающимся силуэтом",
    "defaults": {"symbol": {"by": "element_id", "value": 1100}},
    "ops": [
        {"op": "create_level", "id": "L0", "elev_mm": 0, "name": "Отм. 0.000"},
        {"op": "series", "id": "tower", "count": 20,
         "track": {"hw": [[0, 62500], [5, 30000], [10, 24000], [20, 5000]],
                   "z": [[0, 0], [5, 57000], [10, 115000], [20, 276000]]},
         "items": [
             {"op": "create_beam", "id": "leg_sw",
              "p0_mm": ["-$hw", "-$hw", "$z"],
              "p1_mm": ["-$hw@next", "-$hw@next", "$z@next"],
              "level": {"by": "ref", "value": "L0"}},
             {"op": "create_beam", "id": "ring_s",
              "p0_mm": ["-$hw", "-$hw", "$z"],
              "p1_mm": ["$hw", "-$hw", "$z"],
              "level": {"by": "ref", "value": "L0"}}]}]}

#: Walkthrough 2, "refusal" step: three beams with no `symbol` where there is
#: more than one beam type. The smallest reproduction of the case measured
#: 28.07 (20 beams, 4 types, KIR-G102 x40): the refusal arrives ON EVERY
#: operation.
BEAMS_NO_SYMBOL: dict = {
    "ir_version": "1.0",
    "intent": "балки перекрытия",
    "ops": [{"op": "create_beam", "id": f"b{i}",
             "p0_mm": [i * 6000, 0, 0], "p1_mm": [i * 6000, 12000, 0],
             "level": {"by": "name", "value": "Этаж 1"}} for i in range(3)]}

#: Walkthrough 2, "fix" step: the same program plus ONE line in the envelope.
BEAMS_FIXED: dict = {
    **BEAMS_NO_SYMBOL,
    "defaults": {"symbol": {"by": "element_id", "value": 1101}}}

#: Walkthrough 3, a live case from a production trace
#: (data/reasoning_traces.jsonl): the model placed the tower pad with a +57 m
#: offset. The refusal is reproduced by this object verbatim — KIR-T002,
#: got=57000, suggested_replacement=15000, applicability=maybe-incorrect.
_DECK_OUTLINE = [[0, 0], [6000, 0], [6000, 6000], [0, 6000]]

DECK_BAD_OFFSET: dict = {
    "ir_version": "1.0",
    "intent": "площадка башни на отметке +57 м",
    "ops": [{"op": "create_floor", "id": "deck57", "outline": _DECK_OUTLINE,
             "level": {"by": "name", "value": "Этаж 1"},
             "height_offset_mm": 57000}]}

#: Walkthrough 3, the correct fix: the elevation is carried by the LEVEL, not
#: the offset.
DECK_OWN_LEVEL: dict = {
    "ir_version": "1.0",
    "intent": "площадка башни на своём уровне",
    "ops": [
        {"op": "create_level", "id": "L57", "elev_mm": 57000,
         "name": "Ярус +57.000"},
        {"op": "create_floor", "id": "deck57", "outline": _DECK_OUTLINE,
         "level": {"by": "ref", "value": "L57"}}]}

#: Walkthrough 4 — windows along a host created by this same program.
WALL_WITH_WINDOWS: dict = {
    "ir_version": "1.0",
    "intent": "наружная стена с окнами",
    "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [12000, 0],
         "height_mm": 3300, "level": {"by": "name", "value": "Этаж 1"}},
        {"op": "create_window", "id": "win1",
         "host": {"by": "ref", "value": "w"}, "offset_mm": 3000,
         "sill_mm": 900},
        {"op": "create_window", "id": "win2",
         "host": {"by": "ref", "value": "w"}, "offset_mm": 9000,
         "sill_mm": 900}]}

WALKTHROUGHS: tuple[tuple[str, tuple[str, ...], tuple[tuple[str, dict], ...]], ...] = (
    ("РАЗБОР 1 — «башня с сужающимся силуэтом»: выбор формы решает всё", (
        "ЧИТАЕМ ЗАДАЧУ. Повторяется ли что-то? Да, ярус за ярусом. Меняется "
        "ли что-то от яруса к ярусу? Да, полуширина. Значит `series` с треком "
        "— решение принято ДО первой строки программы.",
        "СМОТРИМ НА СИЛУЭТ. Полуширина падает тремя разными шагами (до первой "
        "площадки -6500 мм/станцию, дальше -1200, затем -1900). Три шага — три "
        "звена трека; одно линейное сужение промахнулось бы на 20.62 м.",
        "ЧИТАЕМ МОДЕЛЬ. Нужен типоразмер балки — `query_types(pool="
        "'beam_types')`; полученный id уходит в `defaults`, потому что он один "
        "на все балки.",
        "ПИШЕМ. Уровень отдельным опом (его `series` не создаёт), трек — "
        "узлами «индекс → значение», элементы — ссылками на трек. Ниже "
        "фрагмент настоящей программы замера: два элемента трека из восьми; в "
        "полном виде 8, что при count=20 даёт 160 операций после раскрытия.",
        "ПРИЁМКА. Квитанция обязана сойтись по закону переписи, а число балок "
        "— совпасть с count x len(items). Силуэт проверяют перечитыванием "
        "габаритов, а не взглядом на скриншот."),
     (("программа", TOWER_TRACK),)),

    ("РАЗБОР 2 — «балки перекрытия»: отказ и прицельная починка", (
        "ПИШЕМ НАИВНО. Три балки, уровень задан, типоразмер — нет: кажется, "
        "что «балка» в проекте одна.",
        "ПОЛУЧАЕМ ОТКАЗ НА КАЖДУЮ ОПЕРАЦИЮ. KIR-G102, field_name=`symbol`, и "
        "в диагностике `candidates` со списком {id, name} всех типов балки. "
        "Дословно из живого прогона: «несколько вариантов — default "
        "невозможен, уточните через {\"by\": \"element_id\", \"value\": <id из "
        "candidates>}». Ровно так замеренные 28.07 двадцать балок дали "
        "KIR-G102 x40 разом.",
        "ЧИТАЕМ ОТКАЗ, А НЕ ПЕРЕПИСЫВАЕМ ПРОГРАММУ. Причина названа полем: "
        "кандидатов несколько, умолчание невозможно. Список уже в руках — "
        "второй `query_types` не нужен.",
        "ЧИНИМ ОДНОЙ СТРОКОЙ. Селектор один на всю программу, значит его "
        "место — `defaults` конверта, а не три правки в трёх опах. В "
        "замеренном случае модель вместо этого повторила один и тот же "
        "селектор 256 раз — это и есть цена непрочитанного отказа."),
     (("наивная программа — отказ", BEAMS_NO_SYMBOL),
      ("починка: одна строка конверта", BEAMS_FIXED))),

    ("РАЗБОР 3 — «ярус на +57 м»: когда подсказку компилятора брать НЕЛЬЗЯ", (
        "СЛУЧАЙ ЖИВОЙ, из production-трейса. Модель строила башню и поставила "
        "площадку операцией с `height_offset_mm: 57000`.",
        "ОТКАЗ ДОСЛОВНО: KIR-T002, «height_offset_mm вне границ "
        "-15000..15000 мм», op_id=`deck57`, got=57000, "
        "suggested_replacement=15000, applicability=`maybe-incorrect`.",
        "ЧТО СДЕЛАЛ БЫ НОВИЧОК. Взял бы подсказку: 15000 проходит границы, "
        "компилятор доволен, программа собирается. И площадка встала бы на "
        "+15 м вместо +57 м — здание было бы построено НЕВЕРНО, молча.",
        "ПОЧЕМУ ПОДСКАЗКА НЕ ГОДИТСЯ. `applicability` сказала прямо: "
        "`maybe-incorrect`. Машинально применяют только "
        "`machine-applicable`; всё прочее проверяют по смыслу. Здесь смысл "
        "такой: смещение — это СМЕЩЕНИЕ ОТ УРОВНЯ, а не отметка, и его "
        "границы отражают физику, а не каприз.",
        "ПРАВИЛЬНАЯ ПОЧИНКА. Ярусу на +57 м нужен СВОЙ уровень: `create_level"
        "(elev_mm=57000)`, и элементы привязывают к нему по `ref`, оставив "
        "смещение маленьким. Именно так устроен разбор 1 — там отметки несёт "
        "трек `z`, а не смещения."),
     (("как было — отказ KIR-T002", DECK_BAD_OFFSET),
      ("как надо — отметку несёт уровень", DECK_OWN_LEVEL))),

    ("РАЗБОР 4 — «окна в наружной стене»: хост и адресация", (
        "ЧИТАЕМ ЗАДАЧУ. Окно не стоит в координате — оно живёт В СТЕНЕ. "
        "Значит нужен хост, и порядок предрешён: сначала стена, потом окна.",
        "АДРЕСУЕМ. Стена создаётся этой же программой, поэтому окна берут её "
        "по `ref` — id ОПЕРАЦИИ, а не id элемента: элемента ещё нет.",
        "ПОЗИЦИОНИРУЕМ ПО ХОСТУ. `offset_mm` — расстояние ВДОЛЬ стены от её "
        "начала, `sill_mm` — отметка низа. Попытка задать окну [x,y,z] "
        "отказывается как неизвестное поле.",
        "ПРИЁМКА. Перечитать стену и убедиться, что проёмов ровно два и они "
        "там, где заявлено. Квитанция скажет, что ПОПРОСИЛИ; что в модели "
        "ЕСТЬ — только повторное чтение."),
     (("программа", WALL_WITH_WINDOWS),)),
)

# ─────────────────────────────────────────── 6. A good program versus a bad one

#: The "bad" one reproduces the case measured in tools/design/kir_dojo.py: on
#: the task ">=10,000 elements" the model produced 12,185 elements, 12,020 of
#: them columns — one grid of 20 columns, placed 601 times, with no rooms,
#: doors, windows, or partitions.
BAD_ONE_OP_BUILDING: dict = {
    "ir_version": "1.0",
    "intent": "здание не менее 10 000 элементов",
    "ops": [{"op": "grid_array", "id": "ax", "nx": 20, "ny": 20,
             "dx_mm": 6000, "dy_mm": 6000}]}

GOOD_COMPOSED_STOREY: dict = {
    "ir_version": "1.0",
    "intent": "типовой этаж: ограждение, проёмы, помещение",
    "defaults": {"level": {"by": "name", "value": "Этаж 1"}},
    "ops": [
        {"op": "create_wall", "id": "w_s", "p0_mm": [0, 0],
         "p1_mm": [12000, 0], "height_mm": 3300},
        {"op": "create_wall", "id": "w_e", "p0_mm": [12000, 0],
         "p1_mm": [12000, 9000], "height_mm": 3300},
        {"op": "create_door", "id": "d1", "host": {"by": "ref", "value": "w_s"},
         "offset_mm": 1500},
        {"op": "create_window", "id": "win1",
         "host": {"by": "ref", "value": "w_s"}, "offset_mm": 6000,
         "sill_mm": 900},
        {"op": "create_room", "id": "r1", "xy": [4000, 3000],
         "name": "Офис 101"}]}

#: A REPEAT SHOWN, NOT DESCRIBED (14.08.2026).
#:
#: THE MEASUREMENT THAT FORCED THIS BLOCK. In the standing description
#: (28,218 characters) the word `track` appeared ONCE — in prose, and NEVER
#: as JSON; there were two full programs, and neither showed a repeat. The
#: section on repeats, meanwhile, is strong, with numbers ("160 operations
#: against one track"). For an LLM a worked example is denser than a
#: paragraph, and the ratio was inverted: we tell — and don't show — exactly
#: the thing that costs the most on a real building.
#:
#: THE PROGRAM IS VERIFIED BY THE COMPILER, NOT WRITTEN FROM MEMORY:
#: `plan_program` accepts it and expands it into 6 ops. An example that does
#: not compile teaches the wrong thing with the same density that a correct
#: one teaches the right thing.
REPEAT_BY_TRACK: dict = {
    "ir_version": "1.0",
    "intent": "фасад ломаной линией: шесть стен одной операцией",
    "defaults": {"level": {"by": "name", "value": "Этаж 1"}},
    "ops": [{
        "op": "series", "id": "fac", "count": 6,
        "track": {"x": [[0, 0], [3, 9000], [6, 12000]],
                  "h": [[0, 3300], [6, 2400]]},
        "items": [{"op": "create_wall", "p0_mm": ["$x", 0],
                   "p1_mm": ["$x@next", 0], "height_mm": "$h"}]}]}

#: THE REFUSAL OF THIS SAME PROGRAM, TAKEN FROM A RUN, NOT MADE UP. Obtained
#: from the same program with track `x` going to node 5 instead of 6. A pair
#: "op + its typical refusal" is worth more than two separate examples: the
#: model will meet this refusal sooner than any other one from `series`, and
#: it names BOTH the subject AND the boundary.
REPEAT_REFUSAL_RU: tuple[str, ...] = (
    "KIR-M001 | поле x | series.track['x'] покрывает индексы 0..5, а читается "
    "на 0..6 (count=6, используется @next). Трек обязан покрывать каждый "
    "индекс: экстраполяция запрещена, а зажим к крайнему узлу дал бы "
    "одинаковые повторы молча",
    "ПОЧИНКА — ОДИН УЗЕЛ: последний индекс трека равен count, если хоть где-то "
    "стоит `@next`. Отказ назвал диапазон — прочти его, не угадывай.",
)

#: A REASON TO ASK THE CONTRACT, NOT JUST A MENTION THAT SUCH A FUNCTION
#: EXISTS. Measured 14.08: the description names `spec(` five times, and
#: BOTH subjects of the arena called it ZERO times. The channel is built,
#: there is material in it (op traps, measured live), the meeting never
#: happens — because not one line says WHEN to call it.
SPEC_TRIGGER_RU: str = (
    "ПЕРЕД ПЕРВЫМ ИСПОЛЬЗОВАНИЕМ ОПА СПРОСИ ЕГО КОНТРАКТ: `spec(\"<оп>\")` "
    "печатает слоты, границы, допуски свидетеля И ЛОВУШКУ ЭТОГО ОПА, "
    "замеренную живьём. Ловушек в этом описании нет — они там. Оп, "
    "использованный без такого чтения, — догадка о его форме."
)

GOOD_VS_BAD: tuple[str, ...] = (
    "ОДНО ЗАДАНИЕ, ДВА ОТВЕТА: «здание не менее 10 000 элементов». Обе "
    "программы ниже КОМПИЛИРУЮТСЯ — разница не в синтаксисе.",

    "ПЛОХАЯ БЕРЁТ ЧИСЛОМ. Одна операция размножает самый дешёвый элемент, и "
    "цель по счётчику закрыта. Замер: на этом задании модель выдала 12 185 "
    "элементов, из них 12 020 колонн — сетка на 20 колонн, поставленная 601 "
    "раз, и ни одного помещения, двери, окна или перегородки. Формально "
    "«готово», по сути — ничего.",

    "ХОРОШАЯ БЕРЁТ СОСТАВОМ. Раздел представлен каждый, ни одна операция не "
    "несёт здание в одиночку, каждый элемент отвечает за свой смысл: стены "
    "ограждают, проёмы сидят в хостах, помещение делает объём считаемым. "
    "Элементов меньше — здания больше.",

    "ПРАВИЛО ОТСЮДА. Цель формулируют ПО СОСТАВУ, а не по числу: каждый "
    "раздел присутствует, и доля одной операции не превышает порога (в стенде "
    "0.55 — выше этого одна операция И ЕСТЬ модель). Счётчик элементов — "
    "побочный эффект, а не достижение.",

    "И ГЛАВНОЕ: СУДЬЯ НЕ МОЖЕТ БЫТЬ СТРОИТЕЛЕМ. Замер 29.07 — две модели "
    "построили башню, обе посмотрели на свой снимок и написали «соответствует "
    "задаче»; оператор на те же модели: «мусорная геометрия». Твои роли — "
    "объявить предикат ДО постройки и починить программу по названной "
    "причине. ГОЛОСА В ПРИЁМКЕ У ТЕБЯ НЕТ. Скриншот — гештальт для человека и "
    "НИКОГДА не доказательство.",
)

# ───────────────────────────────────────────────────────── 7. The refusal playbook

#: Order — per the contract: diagnosis → targeted fix → safety → receipt.
REFUSAL_PLAYBOOK: tuple[tuple[str, str], ...] = (
    ("1. СНАЧАЛА КОНТРАКТ ОТКАЗА",
     "Если есть `diagnostics`, прочитай их все; `diagnostics[0]` — лишь ведущая "
     "диагностика для `err`. Используй `stage` и `err.fix`, только если они есть; "
     "иначе ориентируйся на KIR-код. Применяй подсказку автоматически только при "
     "`machine-applicable`; `maybe-incorrect` требует смысловой проверки. Право на повтор "
     "определяют `err.retryable` и `outcome.retry`; при расхождении действует более "
     "строгий запрет."),

    ("2. SELECTOR: ВЫБЕРИ ТОЧНЫЙ КАНДИДАТ",
     "Для KIR-G101/G102 выбери соответствующий запросу `id` только из тех "
     "строк `candidates`, где `id` явно есть, и повтори исправленную операцию с "
     "`by=element_id`. Для других кодов `candidates` может означать варианты поля, "
     "формы или операции: следуй `field_name` и `expected`, а не подставляй id. KIR-G104 "
     "доказывает пустой модельный пул; не выдумывай id, тип или имя. Повторяющийся "
     "селектор выноси в `defaults` только когда это допускает схема. "
     "У `by=element_id` значение ЦЕЛОЕ: строка `\"294076\"` негодна, и ожидаемый "
     "вид в отказе совпадает с присланным посимвольно — решает ТИП, а не форма. "
     "Замер 22.08: два живых захода подряд; теперь KIR-T001 говорит «сними "
     "кавычки: 294076», и это готовая правка, а не догадка."),

    ("3. KIR-L001: УМЕНЬШИ ПРОГРАММУ",
     f"Бюджет — {MAX_OPS_PER_PROGRAM} операций до раскрытия макросов. Раздели программу на "
     "независимые части, используй поддерживаемый макрос либо перенеси ограниченное "
     "вычисление в `program_py`. У `program_py` свой конечный бюджет: это не безлимитный обход."),

    ("4. EXECUTION И RETRY",
     "`outcome.retry=safe` означает только, что эффекта не было; перед повтором всё равно "
     "исправь названную причину. `verify_first` требует сначала read-only reconciliation, "
     "`forbidden` запрещает повтор. KIR-X004 доказывает rollback внутри транзакции; "
     "KIR-W004 означает, что commit уже произошёл, но постусловие нарушено; такой ход нельзя "
     "повторять вслепую."),

    ("5. HANDOFF — ТОЛЬКО ЯВНЫЙ АЛЬТЕРНАТИВНЫЙ МАРШРУТ",
     "`handoff` не доказывает, что задача вне KIR, и не переопределяет `err.retryable` или "
     "`outcome.retry`. Используй только явно названный, доступный и разрешённый маршрут; иначе "
     "сообщи ограничение без выдуманного обхода."),

    ("6. RECEIPT И ОБЛАСТЬ ИСПРАВЛЕНИЯ",
     "Если receipt несёт `ops_total`, `element_ids`, `op_refusals` и `ops_no_element`, проверь закон "
     "переписи: создано + отказано + без элемента == всего операций. Именованная "
     "диагностика доказывает только наблюдённый дефект, а не правильность остальных операций. "
     "Сохрани незатронутый текст, исправь названный дефект и заново проверь весь контракт. "
     "Любой ход, чей `outcome.retry` не `safe`, запрещено повторять вслепую."),
)

# ────────────────────────────────────────────────────────── 8. Expensive mistakes

COSTLY_MISTAKES: tuple[str, ...] = (
    "ПОДСТАВИТЬ УМОЛЧАНИЕ ВМЕСТО ОТСУТСТВУЮЩЕГО ЗНАЧЕНИЯ — самая дорогая "
    "привычка здесь. Цена замерена на СТОРОНЕ ЧТЕНИЯ, где наш собственный "
    "разборщик подставил «0 вместо отсутствующего»: 2846 групп из 2941 "
    "(96.77%) не попали в индекс реального здания. Правило общее для обеих "
    "сторон: отсутствие значения ОБЪЯСНЯЮТ, а не устраняют.",

    "ИЗОБРЕСТИ ССЫЛКУ, ЧТОБЫ ЗАКРЫТЬ ПОЛЕ. Угаданный id, путь к .rfa или имя "
    "типа либо отказывают, либо — хуже — попадают в чужой элемент.",

    "ВЗЯТЬ ПОДСКАЗКУ, НЕ ПОСМОТРЕВ НА СМЫСЛ (разбор 3).",

    "ГНАТЬСЯ ЗА ЧИСЛОМ ЭЛЕМЕНТОВ (раздел 6).",

    "ПРИНЯТЬ СВОЮ ЖЕ РАБОТУ НА ГЛАЗ. Квитанция говорит, что ПОПРОСИЛИ; что в "
    "модели ЕСТЬ — говорит только повторное чтение.",
)

SECTION_TITLES: tuple[str, ...] = (
    "1. КАК УСТРОЕН KIR",
    "2. С ЧЕГО НАЧИНАЕТ ПРОФИ",
    "3. ФОРМА ПОВТОРА — ПЕРВОЕ РЕШЕНИЕ ЗАДАЧИ",
    "4. ПРИЁМЫ ПО СИТУАЦИЯМ",
    "5. РАЗБОРЫ: ОТ ЗАМЫСЛА ДО ПРИЁМКИ",
    "6. ХОРОШАЯ ПРОГРАММА ПРОТИВ ПЛОХОЙ",
    "7. ПЛЕЙБУК ОТКАЗОВ",
    "8. ПЯТЬ ДОРОГИХ ОШИБОК",
)

#: Everything the course shows as WORKING — is compiled by a test.
ALL_PROGRAMS: tuple[tuple[str, dict], ...] = (
    ("ELEMENT_STATE_READ", ELEMENT_STATE_READ),
    ("TOWER_TRACK", TOWER_TRACK),
    ("BEAMS_FIXED", BEAMS_FIXED),
    ("DECK_OWN_LEVEL", DECK_OWN_LEVEL),
    ("WALL_WITH_WINDOWS", WALL_WITH_WINDOWS),
    ("BAD_ONE_OP_BUILDING", BAD_ONE_OP_BUILDING),
    ("GOOD_COMPOSED_STOREY", GOOD_COMPOSED_STOREY),
)

#: Everything the course shows as a REFUSAL — is required to refuse (negative
#: controls in test_skill.py). A shown refusal that in fact passes teaches
#: the model to fear a technique that actually works.
REFUSING_PROGRAMS: tuple[tuple[str, dict, str], ...] = (
    ("BEAMS_NO_SYMBOL", BEAMS_NO_SYMBOL, "KIR-G102"),
    ("DECK_BAD_OFFSET", DECK_BAD_OFFSET, "KIR-T002"),
)


def _render_program(program: dict) -> str:
    """JSON is paid for in tokens here — hence compact."""

    return json.dumps(program, ensure_ascii=False, separators=(",", ":"))


#: THE DOOR TO THE DISPLACED LITERALS. Sits in §5 as one line; without it the
#: decompile programs would go dark in exactly the way `sdk.py` sat
#: unreachable for five weeks.
#: WALKTHROUGHS STAYING IN THE STANDING TEXT. The kind of list is CLOSED, BUT
#: NOT COMPLETE: empty here would mean "we haven't decided", not "nothing to
#: leave in". Adding a line requires the same justification as removing one:
#: how this walkthrough changes the CHOICE OF FORM, not just understanding.
PERMANENT_WALKTHROUGHS: frozenset = frozenset({
    "РАЗБОР 3 — «ярус на +57 м»: когда подсказку компилятора брать НЕЛЬЗЯ",
})

WALKTHROUGH_PROGRAMS_TOPIC = "разборы"
WALKTHROUGH_CASES_TOPIC = "случаи"
_PROGRAMS_POINTER = (
    f"    ЕЩЁ ТРИ РАЗБОРА — силуэт башни треком, отказ KIR-G102 и его прицельная "
    f"починка, окна в хосте: рассуждение course(\"{WALKTHROUGH_CASES_TOPIC}\"), "
    f"программы всех четырёх course(\"{WALKTHROUGH_PROGRAMS_TOPIC}\") — из "
    f"своего же скрипта, ответ придёт в квитанцию ЭТОГО ЖЕ хода.")


#: TECHNIQUES STAYING IN THE STANDING TEXT. The kind of list is CLOSED, BUT
#: NOT COMPLETE: what lands here is what decides the FORM of the statement,
#: and adding a line requires the same justification as removing one.
#:
#: Why these three, and not the other six. "Free form" decides which OP to
#: write with at all (mesh vs. solid vs. contour); "loners and hazards"
#: decides which ops must ride their own program, i.e. the form of the
#: BATCH; "thicknesses and sections" decides whether to read the catalog
#: before writing. A mistake here costs a rewrite of the whole program. The
#: other six answer "I've hit a specific wall" — they get asked AFTER the
#: form is chosen, and so belong in the demand channel.
#: 🔴 "ADDRESSING WITHIN A PROGRAM" CAME BACK HERE AFTER A RED, and this is
#: the right order: first the rule placed it in the demand channel, then
#: `test_tool_doc.test_ref_rule_matches_the_compiler` went red, because the
#: `ref` rule (what can be addressed by reference, and that `type`/`symbol`
#: cannot) decides HOW the program is written, not "what to do once you've
#: hit a wall". The ratchet turned out more precise than my split — that is
#: exactly what it's there for.
_TECHNIQUES_IN_PERMANENT_TEXT: frozenset[str] = frozenset({
    "АДРЕСАЦИЯ ВНУТРИ ПРОГРАММЫ",
    "ТОЛЩИНЫ И СЕЧЕНИЯ", "СВОБОДНАЯ ФОРМА", "ОДИНОЧКИ И ОПАСНЫЕ",
})


#: 🔴 THE SECOND HALF OF THE TECHNIQUES — AS A SEPARATE LESSON, AND THIS WAS
#: BOUGHT BY A MEASUREMENT ON 22.08.2026, not by taste.
#:
#: The "techniques" lesson grew to 4,882 characters against a `LESSON_CAP` of
#: 3,300, and the sandbox channel truncates `stdout` at 4,000. That is, THE
#: MODEL WAS NOT GETTING THE LAST THREE TECHNIQUES AT ALL — the transport cut
#: them off:
#:
#:     LEVELS AND ELEVATIONS · HOST: WINDOWS, DOORS, MARKS · COORDINATES AND
#:     UNITS
#:
#: The cost was measured on myself that same day: assembling an apartment, I
#: set a level by referencing someone else's `element_id` — and the judge said
#: "model has no rooms" with four rooms declared, because the PROGRAM path
#: only resolves a level declared by the program ITSELF. That is exactly what
#: the truncated "LEVELS AND ELEVATIONS" technique says.
#:
#: There was nothing to cut: the techniques are a catalog, and a truncated
#: catalog is worse than a short one. Hence SPLITTING, not shortening, and
#: the line is drawn by the question the technique answers: "what and with
#: what to build" versus "WHERE to place things and how to run a large
#: program". Completeness is held by a test, not by attention: the union of
#: the three sets must EQUAL `TECHNIQUES`, and the intersections must be
#: empty.
_TECHNIQUES_PLACEMENT: frozenset[str] = frozenset({
    "УРОВНИ И ОТМЕТКИ",
    "ХОСТ: ОКНА, ДВЕРИ, МАРКИ",
    "КООРДИНАТЫ И ЕДИНИЦЫ",
    "ПОРЯДОК ДЛЯ БОЛЬШОЙ ПРОГРАММЫ",
    "ЗЕЛЁНЫЙ ЧИТАЕТСЯ С РЕПЕТИЦИИ, А НЕ СО СВИДЕТЕЛЯ",
})


def _techniques_lesson(chosen: frozenset[str], *, title: str,
                       elsewhere: str) -> str:
    """One half of the technique catalog. ONE builder for both — not two.

    THE FORMAT IS ONE LINE PER ENTRY — the same format the block was printed
    in inside the description. The first draft split the situation and the
    advice across lines with a blank one between them and went over the
    lesson ceiling (3,561 against 3,300), derived from the sandbox channel and
    therefore not raisable. Beauty of layout that doesn't fit the channel is a
    truncation, and truncated advice is worse than no advice.
    """
    rows = [(s, a) for s, a in TECHNIQUES if s in chosen]
    # 🔴 THE HEADER WRAPS, THE ENTRIES DO NOT, and this is the course's own
    # rule (`lessons._reflow`): width is measured against PROSE, and an
    # indented line — a table or a list — is left untouched, because
    # reflowing inside it would make it uncopyable. The header as prose was
    # 114 and 149 characters against an 88 threshold, and this wasn't caught:
    # the sub-test failed EARLIER, on the lesson's length, and the width guard
    # never got to run at all. A red for a known reason was hiding the next
    # one — the recorded form, bought here once more.
    head = textwrap.fill(f"{title} — {len(rows)} из {len(TECHNIQUES)}. "
                         f"{elsewhere}", width=78,
                         break_long_words=False, break_on_hyphens=False)
    out = [head]
    for situation, advice in rows:
        out.append(f"  • {situation} — {advice}")
    return "\n".join(out)


def build_techniques_text() -> str:
    """INTENT techniques — what to build with, what to build, what to do on a
    refusal.

    Home of the displaced §4 (15.08.2026). Assembled from `TECHNIQUES`, i.e.
    from the same object that used to be printed into the description: a
    second copy would have silently drifted from the first, and there would
    have been plenty of chances to drift — the techniques change more often
    than any other block of the course.
    """
    chosen = frozenset(
        s for s, _ in TECHNIQUES
        if s not in _TECHNIQUES_IN_PERMANENT_TEXT
        and s not in _TECHNIQUES_PLACEMENT)
    return _techniques_lesson(
        chosen, title=SECTION_TITLES[3],
        elsewhere=("Решающие ФОРМУ стоят в постоянном тексте; про МЕСТО и "
                   "порядок — course(\"место\")."))


def build_placement_techniques_text() -> str:
    """PLACEMENT techniques: where to put things and how to run a large
    program."""
    return _techniques_lesson(
        _TECHNIQUES_PLACEMENT,
        title="ПРИЁМЫ: КУДА СТАВИТЬ И КАК ВЕСТИ БОЛЬШУЮ ПРОГРАММУ",
        elsewhere=("Чем считать и что строить — course(\"приёмы\"); "
                   "решающие ФОРМУ стоят в постоянном тексте."))


def build_walkthrough_cases_text() -> str:
    """The reasoning chain of the three displaced walkthroughs — ON DEMAND.

    Walkthrough 3 stays in the standing text: it is the only one that teaches
    NOT TAKING the compiler's hint, and that decision is made BEFORE the form
    is chosen and costs a silently wrong building. The other three teach
    reasoning — that is the course.
    """
    out = ["РАЗБОРЫ: ЦЕПОЧКА РАССУЖДЕНИЯ.",
           "Программы этих же разборов целиком — course(\"разборы\").", ""]
    for title, steps, _programs in WALKTHROUGHS:
        if title in PERMANENT_WALKTHROUGHS:
            continue
        out.append(f"  {title}")
        out.extend(f"    - {step}" for step in steps)
        out.append("")
    return "\n".join(out)


REFUSAL_PLAYBOOK_TOPIC = "отказы"


def build_refusal_playbook_text() -> str:
    """The refusal playbook — ON DEMAND. Displaced 19.08.2026, see the
    argument at §7."""
    out = [
        "ПЛЕЙБУК ОТКАЗОВ: что делать, когда пришёл KIR-*.",
        "  Нужен В МОМЕНТ отказа, а не в каждом ходу — потому и здесь.",
        "",
    ]
    for what, meaning in REFUSAL_PLAYBOOK:
        out.append(f"  • {what} — {meaning}")
    return "\n".join(out)


def build_walkthrough_programs_text() -> str:
    """Literals of the decompile-walkthrough programs — ON DEMAND, not on
    every turn.

    THE MEASUREMENT THAT FORCED THE MOVE (09.08.2026). The six literals of §5
    weighed 2,496 characters of permanently loaded text against a description
    ceiling of 30,000 — i.e. 8% of the whole budget went on JSON, of which the
    two programs of walkthrough 2 differ by EXACTLY ONE key, `defaults`, and
    were printed at 400 characters each. The value of a walkthrough is its
    reasoning chain; the JSON illustrates it, and an illustration doesn't have
    to ride on every request.

    A MOVE, NOT A DELETION, AND A TEST HOLDS THIS. The objects stayed the same
    (`ALL_PROGRAMS`/`REFUSING_PROGRAMS` compile and refuse in
    `test_skill.py`), the "shown = checked" ratchet was rewired to this
    address, and §5 carries a line naming the door. This package still cannot
    show a program that nobody has ever run.
    """
    # 🔴 THE PHRASE IS COMPUTED FROM THE SAME SETS THAT DECIDE THE ROUTE
    # (F-113, 29.08.2026). This used to be an unconditional "The walkthroughs
    # themselves stand in the instrument's description" with ONE walkthrough
    # out of FOUR in the standing text: the model got the programs and DID NOT
    # KNOW it had no reasoning for three of them. The cost is not lost text
    # but a lost REASONING CHAIN, and the phrase was flatly saying there was
    # no need to go fetch it. The statement is true exactly when the sets are
    # equal in size — now this is written down, not implied. The topic's name
    # is taken from `WALKTHROUGH_CASES_TOPIC`, not typed in here: typing it in
    # would have made it yet another carrier of the same fact.
    if len(PERMANENT_WALKTHROUGHS) == len(WALKTHROUGHS):
        where = "Сами разборы (зачем каждый шаг) стоят в описании инструмента."
    else:
        where = (f"Рассуждение {len(PERMANENT_WALKTHROUGHS)} из "
                 f"{len(WALKTHROUGHS)} разборов — в описании инструмента; "
                 f"остальные — course(\"{WALKTHROUGH_CASES_TOPIC}\").")
    out = [
        "ПРОГРАММЫ РАЗБОРОВ — то, что в §5 описано словами, здесь целиком.",
        where,
    ]
    # 🔴 THE REASONING DOES NOT RIDE HERE, AND THIS IS A MEASUREMENT, NOT A
    # TASTE. The first draft of the 19.08 cut placed the walkthrough steps
    # next to the programs — the lesson became 5,351 against a `LESSON_CAP` of
    # 3,300, i.e. it WOULD NOT HAVE FIT in the sandbox's stdout, and the
    # capability would have become unreachable in exactly the way this whole
    # cut is written against. Caught by
    # `test_every_lesson_fits_the_sandbox_stdout`. The reasoning moved out to
    # its own topic, `course("cases")`, which does fit the ceiling.
    for title, _steps, programs in WALKTHROUGHS:
        out.append("")
        out.append(f"  {title.split(' — ')[0]}")
        for label, program in programs:
            out.append(f"    {label}:")
            out.append(f"      {_render_program(program)}")
    out.extend(["", "АДРЕСНОЕ ЧТЕНИЕ ПО UNIQUEID:", textwrap.fill(ELEMENT_STATE_READ_LIMITS, width=88),
                f"    {_render_program(ELEMENT_STATE_READ)}"])
    return "\n".join(out)


def build_shape_vocabulary_text() -> str:
    """The whole "geometry" lesson — on demand, not on every turn."""
    out = ["УРОК «ГЕОМЕТРИЯ» — чем сказать кривое, наклонное и вычтенное.", ""]
    out.extend(f"  • {item}" for item in SHAPE_VOCABULARY)
    return "\n".join(out)


def build_skill_text() -> str:
    """The course as one block — for pasting into the `revit_ir` instrument's
    description."""

    out: list[str] = [
        "КРАТКИЙ КУРС: КАК РАБОТАЮТ НА KIR ТЕ, КТО УМЕЕТ.",
        "(Справочник — в схеме инструмента; здесь только то, чего в ней нет.)",
    ]

    def block(title: str, items: tuple[str, ...]) -> None:
        out.append("")
        out.append(f"{title}:")
        out.extend(f"  • {item}" for item in items)

    block(SECTION_TITLES[0], SYSTEM_MODEL)
    block(SECTION_TITLES[1], HOW_A_PRO_STARTS)
    block(SECTION_TITLES[2], SHAPE_OF_REPETITION)
    out.append("")
    out.append(f"  • {SHAPE_VOCABULARY_POINTER}")

    # 🔴 §4 WAS DISPLACED INTO THE DEMAND CHANNEL ON 15.08.2026 — for the same
    # reason and by the same move as the §5 literals six days earlier.
    #
    # MEASUREMENT BEFORE THE EDIT: the instrument description was 30,427
    # characters against a ceiling of 30,000 — the ceiling had been BROKEN
    # THROUGH, not by one edit but by accumulation: eight capabilities landed
    # in the standing text in a single day. Raising the ceiling would mean
    # shifting our own sloppiness onto the model's thinking budget, which is
    # paid for on EVERY turn.
    #
    # WHY THIS BLOCK SPECIFICALLY, AND NOT A NEIGHBORING ONE. There is one
    # placement rule: the standing text carries what the model needs to avoid
    # picking the WRONG FORM. §1 (the setup), §2 (where a pro starts), §3 (the
    # form of a repeat) decide exactly the form, and they stay. §4 is a
    # situational reference, "hit X — do Y": it's needed AFTER the form has
    # been chosen and the author has hit something specific, i.e. exactly
    # when it can be asked for. This is not a shortening of the course: the
    # full text is available in one line, `course("приёмы")`, and the pointer
    # below names it in the very spot where the block itself used to stand.
    out.append("")
    out.append(f"{SECTION_TITLES[3]}:")
    kept = [(s, a) for s, a in TECHNIQUES
            if s in _TECHNIQUES_IN_PERMANENT_TEXT]
    for situation, advice in kept:
        out.append(f"  • {situation} — {advice}")
    # 🔴 THE LIST OF NAMES WAS REMOVED, NOT CORRECTED (F-112, 29.08.2026).
    # This used to hand-name "levels, host, coordinates" as the contents of
    # course("приёмы") — all three actually live in course("место"), moved
    # there by `_TECHNIQUES_PLACEMENT`. As long as the subjects are named by
    # hand, they will drift from the route on every move of a technique, and
    # such a move has already happened once.
    #
    # 🔴 AND THE NUMBER WAS ALSO WRONG, contrary to the bundle. `len(TECHNIQUES)
    # - len(kept)` = 10 added up BOTH topics, while `course("приёмы")` holds
    # FIVE (verified by execution: 14 total − 4 standing − 5 about place).
    # I.e. the computed number was lying in exactly the same way as the
    # hand-typed list — just more quietly.
    in_techniques = len(TECHNIQUES) - len(kept) - len(_TECHNIQUES_PLACEMENT)
    out.append(f"  • ОСТАЛЬНЫЕ {in_techniques} ПРИЁМОВ — course(\"приёмы\"), "
               f"печатает в квитанцию этого хода.")
    # Three subject words are the ONLY names left, and they now sit right next
    # to the topic where the subjects actually live. Without a single subject
    # word the model won't understand why it should call the second topic at
    # all, and the cost of that is the same extra turn this edit is meant to
    # save.
    out.append(f"  • ЕЩЁ {len(_TECHNIQUES_PLACEMENT)} О МЕСТЕ: уровень, хост, "
               f"координаты, порядок — course(\"место\").")
    # 🔴 WHERE `course` LIVES — NOT HERE, AND THIS IS A DECISION (29.08.2026).
    #
    # A stranger's review gate (Phase 6) caught the first step of onboarding:
    # a reader outside the sandbox types `course("дом")` literally and gets
    # `TypeError: 'module' object is not callable`, because
    # `from kir import course` gives a PACKAGE. The correct form,
    # `from kir.course import course`, was written nowhere in the whole tree.
    #
    # The first draft of the fix put the hint HERE — and broke through the
    # description ceiling: 30,067 against 30,000, with only 44 characters of
    # margin to spare. The ceiling is paid for on EVERY turn of the model, and
    # the model works INSIDE the sandbox, where the name is already injected:
    # it NEVER needs the import. The one who needs it is the HUMAN reading the
    # canon — and this file's placement rule says exactly the same thing:
    # "the standing text carries only what's needed to avoid picking the
    # WRONG FORM".
    #
    # The line lives in `kir/CLAUDE.md`; that it's there is held by the
    # ratchet `test_a_taught_command_actually_runs`, and the same ratchet also
    # holds the converse — that the standing text does NOT pay for it.

    out.append("")
    out.append(SECTION_TITLES[4])
    # LITERALS WERE DISPLACED ON 09.08 (see `build_walkthrough_programs_text`):
    # what stays here is the reasoning chain — the reason the walkthrough
    # exists at all — while the JSON arrives on demand. The standing cost of
    # 2,496 characters was replaced with one pointer line.
    # 🔴 THREE WALKTHROUGHS OUT OF FOUR WERE DISPLACED ON 19.08.2026, AND THIS
    # IS THE SAME MOVE AS 09.08: the ceiling was broken through by
    # accumulation (31,736 against 30,000), and raising it would mean shifting
    # our own sloppiness onto the model's thinking budget. The rule of the cut,
    # verbatim: the standing text carries only what's needed to avoid picking
    # the WRONG FORM. §3 chooses the form; walkthroughs 1, 2, and 4 teach
    # REASONING — that is the course, and it is paid for on demand.
    #
    # WALKTHROUGH 3 STAYS, and it is the only one: it teaches NOT TAKING the
    # compiler's hint (`applicability: maybe-incorrect`). This decision is
    # made BEFORE the form is chosen, and the cost of getting it wrong is a
    # silently wrong building: the tier would land at +15 m instead of +57 m,
    # showing green.
    for title, steps, _programs in WALKTHROUGHS:
        if title not in PERMANENT_WALKTHROUGHS:
            continue
        out.append("")
        out.append(f"  {title}")
        out.extend(f"    - {step}" for step in steps)
    out.append(_PROGRAMS_POINTER)

    out.append("")
    out.append(f"{SECTION_TITLES[5]}:")
    out.extend(f"  • {item}" for item in GOOD_VS_BAD)
    # THIS PAIR STAYS IN THE STANDING TEXT, AND THIS IS NOT AN INCONSISTENCY.
    # The §5 literals illustrate a REASONING CHAIN and are meaningless without
    # it — so they moved to join it in `course("разборы")`. Here the programs
    # ARE THE SUBJECT: the claim "composition, not a counter" can only be
    # checked by comparing two texts, and taking one of them out would mean
    # taking out the comparison itself.
    out.append("  ПЛОХАЯ (компилируется, цель по числу закрыта, здания нет):")
    out.append(f"    {_render_program(BAD_ONE_OP_BUILDING)}")
    out.append("  ХОРОШАЯ (состав, а не счётчик):")
    out.append(f"    {_render_program(GOOD_COMPOSED_STOREY)}")
    # THE REPEAT IS SHOWN, NOT JUST DESCRIBED. It stays here, not in `course`,
    # for the same reason as the pair above: the subject is THE PROGRAM TEXT
    # ITSELF, and moving it to the demand channel would mean moving out the
    # very thing this block was written for. The cost was measured AFTER
    # writing, not estimated: the description went 28,218 -> 29,565 characters
    # (+1,347, +4.8% of the description; +1.8% of a turn against a schema of
    # 45,216, i.e. ~422 tokens at the vendor's 3.19 chars/token). The ceiling
    # declared before writing was 3,000 characters — came in at half that.
    out.append("  ПОВТОР ПИШУТ ТРЕКОМ, А НЕ ПЕРЕЧИСЛЕНИЕМ (шесть стен одним опом):")
    out.append(f"    {_render_program(REPEAT_BY_TRACK)}")
    out.append("    `track` — узлы «индекс → значение», между узлами линейная "
               "интерполяция, поэтому ОДИН узел-излом (здесь 3) описывает "
               "ломаный силуэт. `$x` — значение на шаге k, `$x@next` — на шаге "
               "k+1: так N повторов сшивают N СМЕЖНЫХ отрезков, а не рассыпают "
               "их. Разворачивается в 6 операций.")
    out.append("    ЕЁ ТИПИЧНЫЙ ОТКАЗ, ДОСЛОВНО:")
    out.extend(f"      {line}" for line in REPEAT_REFUSAL_RU)
    out.append(f"  {SPEC_TRIGGER_RU}")

    out.append("")
    # 🔴 THE PLAYBOOK WAS DISPLACED IN FULL ON 19.08.2026. The argument is not
    # about size: EVERY KIR refusal carries `err.fix`, `applicability`,
    # `retryable`, and the next move IN ITSELF — that is an invariant of the
    # compiler, not a hope. Standing text that retells what arrives anyway AT
    # THE MOMENT OF NEED is paid for on every turn, while it's needed only
    # rarely. What stays is a line naming the door, and the ONE rule that must
    # be known BEFORE a refusal — about the hint.
    out.append(f"{SECTION_TITLES[6]}:")
    out.append(
        "  • Каждый отказ несёт причину, поле и следующий ход В СЕБЕ: читай "
        "`diagnostics` целиком, а не только `err`. Подсказку применяй "
        "автоматически ТОЛЬКО при `applicability: machine-applicable`; "
        "`maybe-incorrect` проверяй по смыслу (разбор 3 выше). Право на повтор "
        "решают `err.retryable` и `outcome.retry`, и при расхождении действует "
        "более строгий запрет. KIR-X004 доказывает откат ВНУТРИ транзакции, а "
        "KIR-W004 значит, что commit уже произошёл при нарушенном постусловии — "
        "такой ход вслепую не повторяют.")
    # 🔴 THE FLOOR OF THIS SECTION WAS SET NOT BY ME BUT BY `test_skill.py`: it
    # lists by name what must remain PERMANENTLY VISIBLE (selector codes, the
    # law of the receipt census, the three values of `outcome.retry`). So §7
    # is NOT displaced in full — the test is the authority on what's needed to
    # avoid picking the wrong form. The first draft of the 19.08 cut moved
    # everything out and went red on it; that is the right order, not an
    # obstacle.
    out.append(
        "  • СЕЛЕКТОР: KIR-G101/G102 несут `candidates` — возьми оттуда `id` "
        "и повтори операцию с `by=element_id`. Для других кодов `candidates` "
        "может значить варианты поля или формы: следуй `field_name`, а не "
        "подставляй id. KIR-G104 доказывает ПУСТОЙ пул — не выдумывай id.")
    out.append(
        "  • КВИТАНЦИЯ СХОДИТСЯ ПО ЗАКОНУ ПЕРЕПИСИ: `ops_total` == создано + "
        "`op_refusals` + `ops_no_element`. Расхождение — класс «молча не "
        "создано». Именованная диагностика доказывает ОДИН дефект, а не "
        "правильность остальных операций.")
    out.append(
        "  • ПОВТОР РЕШАЕТ `outcome.retry`: `safe` — эффекта не было (причину "
        "всё равно почини), `verify_first` — сперва перечитай модель, "
        "`forbidden` — не повторять.")
    out.append(
        f"  • ОСТАЛЬНОЕ ({len(REFUSAL_PLAYBOOK)} правил целиком: бюджет "
        f"KIR-L001, handoff, область исправления) — "
        f"course(\"{REFUSAL_PLAYBOOK_TOPIC}\") из своего же скрипта.")

    block(SECTION_TITLES[7], COSTLY_MISTAKES)
    return "\n".join(out)


__all__ = [
    "ALL_PROGRAMS",
    "BAD_ONE_OP_BUILDING",
    "BEAMS_FIXED",
    "BEAMS_NO_SYMBOL",
    "COSTLY_MISTAKES",
    "GOOD_COMPOSED_STOREY",
    "GOOD_VS_BAD",
    "HOW_A_PRO_STARTS",
    "REFUSAL_PLAYBOOK",
    "REFUSAL_PLAYBOOK_TOPIC",
    "WALKTHROUGH_CASES_TOPIC",
    "build_walkthrough_cases_text",
    "PERMANENT_WALKTHROUGHS",
    "build_refusal_playbook_text",
    "SECTION_TITLES",
    "SHAPE_OF_REPETITION",
    "SHAPE_VOCABULARY",
    "SHAPE_VOCABULARY_POINTER",
    "SHAPE_VOCABULARY_TOPIC",
    "build_shape_vocabulary_text",
    "SYSTEM_MODEL",
    "TECHNIQUES",
    "TOWER_TRACK",
    "WALKTHROUGHS",
    "WALL_WITH_WINDOWS",
    "build_skill_text",
]
