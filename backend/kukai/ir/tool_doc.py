"""The prose half of the `revit_ir` tool: what the JSON Schema cannot say.

The schema (`schema_gen.program_schema`) is generated from the registry and is
complete — every op, parameter, bound and enum, ~23k tokens of it. What it
cannot express is the knowledge that only came from running programs against a
real Revit: which ops are PROVEN to build, which are known broken, in what
ORDER a selector has to be resolved, and the traps that cost a live round-trip
each.

Two rules govern this module, both learned the hard way in this package:

1. **The op inventory is GENERATED from `spec.OPS`.** A hand-written list is a
   promise to drift, and the drift is invisible: the tool description shipped
   until 2026-07-27 named 7 of the 28 writing ops, so a model reading it could
   not know KIR authors beams, ducts, groups, family types or annotations at
   all. `test_tool_doc.py` fails if any writing op is missing from the text.

2. **Every trap below is a MEASUREMENT, with its provenance.** This package has
   repeatedly asserted the opposite of the truth in confident prose (the CONNECT
   emitter's own docstring claimed pipe connectors were free — a live document
   said otherwise, and four ops were unbuildable because of it). Nothing goes in
   here that was reasoned rather than observed.

`UNPROVEN` is deliberately part of the contract: telling the model an op is not
yet proven costs a line and saves a round-trip, and it is a debt counter — the
list is meant to shrink to empty.
"""
from __future__ import annotations

from kukai.ir import sandbox, spec
from kukai.ir.skill import build_skill_text

#: Ops whose live behaviour is NOT established, with the reason. Verified
#: 2026-07-27 against SOB6.2 (Revit 2023) via scripts/kir_live_matrix.py; 26 of
#: the 28 writing ops built with a green witness. Shrink this list as they are
#: proven or fixed — never grow it by assumption.
UNPROVEN: dict[str, str] = {
    "create_dimension":
        "не работает: NewDimension требует ГЕОМЕТРИЧЕСКИХ ссылок (грань/ребро), "
        "эмиттер подаёт ссылку на элемент — используй обычный инструмент",
    # wave/shape, 29.07. Ворота Roslyn зелёные 6/6 в обеих изоляциях, но живой
    # Revit этот оп ещё не видел ни разу, и два его свойства офлайн
    # непроверяемы в принципе: сколько Revit собирает тысячи граней внутри
    # транзакции (мост режет execute на 200 с) и сохраняет ли он нашу
    # триангуляцию один-в-один. Свидетель числа граней написан так, чтобы
    # расхождение было ГРОМКИМ, — то есть первый живой прогон это и покажет.
    "create_directshape":
        "ворота 6/6 пройдены, живьём НЕ проверялся ни разу: время построения "
        "большого меша и сохранение числа граней Revit'ом офлайн неизмеримы. "
        "Начинай с сотен треугольников, не с тысяч",
}

#: Ограничения, которые НЕ мешают опу работать, но о которых лучше знать до
#: вызова: каждое замерено живьём.
CONSTRAINTS: tuple[str, ...] = (
    "`create_beam` строит только на КРИВООРИЕНТИРОВАННОМ семействе каркаса. "
    "Пул `beam_types` их и отдаёт (фильтр по FamilyPlacementType), но во многих "
    "проектах каркас смоделирован точечными семействами — тогда пул окажется "
    "пуст, и это честное «не на чем», а не поломка.",
    "Опорный уровень балки Revit выводит из отметки кривой, а не из аргумента "
    "`level`: он контекст размещения. Полученный уровень возвращается в "
    "свидетеле (`reference_level`).",
)

#: Idioms measured 2026-07-27 by giving the MODEL seven building tasks: from
#: the generated schema alone it authored a valid Eiffel Tower (57 ops), so the
#: ops themselves are legible. Every remaining failure was a rule that exists
#: only inside a diagnostic — unknowable up front — and two of them made the
#: model REFUSE tasks KIR can actually do. Authored in a parallel session and
#: preserved verbatim here except for the `ref` line, corrected below.
AUTHORING_IDIOMS: tuple[str, ...] = (
    "Толщина/ширина конструкции — это ТИП, а не параметр операции. Перекрытие "
    "200 мм = create_type(category='architectural', width_mm=200, "
    "source_type=…) и затем create_floor(type=<этот тип>). У "
    "create_floor/create_wall своего поля толщины НЕТ — это не значит, что "
    "задача невыполнима.",
    # Corrected against the live matrix 2026-07-27: `ref` is NOT level-only.
    # Проверено живьём — окно по ref на свою стену, set_param и create_tag по
    # ref на свой элемент. Ограничение касается именно каталожных селекторов.
    # СЛИЯНИЕ 04.08: отдельная ловушка «Хост и цель адресуются через ref —
    # окно на только что созданной стене, марка на только что созданном
    # элементе» стояла ниже ЧЕТЫРНАДЦАТЬЮ строками и не несла ни одного факта
    # сверх этой: `host`/`target` тут уже названы, и названы вместе с
    # ограничением, которого там не было вовсе. Два абзаца об одной мысли
    # оплачивались КАЖДЫМ запросом; пример из второго перенесён сюда целиком,
    # так что потеряно ровно ничего.
    "`{\"by\": \"ref\", \"value\": \"<id опа выше>\"}` работает для level/"
    "base_level/top_level, host, target и refs — то есть для того, что ты "
    "создаёшь в ЭТОЙ ЖЕ программе (окно на только что созданной стене, марка "
    "на только что созданном элементе); за границу программы ref не идёт — "
    "только по имени. Для `type`/`symbol` ref НЕ работает: типоразмер "
    "выбирается по element_id или по name, не знаешь id — сначала query_types.",
    "Существующий элемент нельзя выбрать описанием («южная стена»). Сначала "
    "query_list с фильтрами, потом работай по его id.",
    # ВЫБОР макроса под форму задачи переехал в `skill.SHAPE_OF_REPETITION`
    # (30.07): это суждение, а не ловушка, и держать его в двух местах значит
    # платить за него дважды. Здесь остаётся только то, чего из схемы не
    # вывести, — какие ФОРМЫ приняты под `transform` и чем задаётся кривизна.
    "Под `stack.transform` криволинейный план — это "
    "`contour.outer.shape='poly'` с точками по эллипсу: rect и l там не "
    "принимаются, потому что не переносят поворот без потери смысла. Гнутые "
    "стены — поле `arc`, наклонные колонны — `top_xy` вместе с `top_level`.",
    # `defaults` против ставки на умолчание и ВЫБОР `series` под меняющийся
    # параметр переехали в `skill.BEFORE_YOU_SEND` / `skill.SHAPE_OF_REPETITION`
    # (30.07) — оба суждения, а не ловушки. Синтаксис трека («$hw», «$hw@next»,
    # «-$hw») здесь тоже не нужен: проверено 30.07 — `track`, `items` и суффикс
    # `@next` схема описывает сама, а проза, дублирующая схему, стоит токенов
    # в каждом запросе и расходится с ней при первой же правке.
    "Точки: у стен/колонн/помещений — [x,y] в мм, у балок, труб и place_family "
    "— [x,y,z]. Наклонные элементы делаются балкой.",
    # 20, not 300: MAX_BULK_OPS=300 is the INTERNAL decompile/rebuild budget,
    # never the serving path. Told 300, the model sent a 24-op program and got
    # KIR-L001 (expected <=20, got 24) — the wrong number cost it a round and a
    # rewrite (measured 2026-07-27, Eiffel-tower run).
    # ПРАВКА 04.08: «не более 20 операций (MAX_OPS_PER_PROGRAM). Это мало
    # намеренно» отсюда УБРАНО — не потому, что неверно, а потому, что стоит
    # уже дважды в том же самом запросе: `_two_input_forms` печатает потолок
    # ИНТЕРПОЛЯЦИЕЙ из `compiler.MAX_OPS_PER_PROGRAM`, а `skill.CRAFT` — вместе
    # с замером «210 отказов из 586». Здесь число было ЛИТЕРАЛОМ, то есть ровно
    # тем, чем этот модуль запрещает писать числа: разойдись оно с компилятором
    # — и врало бы уверенно. Уникальная часть ловушки (арифметика группы)
    # осталась целиком.
    "Повторяющееся собирается не перечислением, а через "
    "create_group(members, placements) — панель на 19 операций, поставленная в "
    # «Крупное здание — это ПАЧКА программ» переехало отсюда в ловушку про
    # `create_stairs` (04.08). Там оно стоит рядом с ПРАВИЛОМ, которое эту пачку
    # ВЫНУЖДАЕТ, и вместе с ответом на «а как тогда проверить целое» — здесь же
    # это был лозунг без адреса: модель читала его, соглашалась и всё равно
    # писала здание одной программой, потому что не знала ни что делить, ни где
    # спрашивать вердикт. Замер 03-04.08: 4 прогона A/B, 0 зданий без
    # блокирующих; сильная модель нашла стену сама и слепила лестницу из 15
    # `create_floor`. Строка перенесена, а не удвоена: платить дважды за одну
    # мысль дороже, чем перенести её к причине.
    "40 мест, даёт 760 элементов одной программой.",
)

#: Traps observed while proving the ops against a live Revit (the live matrix,
#: scripts/kir_live_matrix.py). Each cost a round-trip to find.
NOTES: tuple[str, ...] = AUTHORING_IDIOMS + (
    "Сначала спроси `query_types` по нужному пулу, потом ставь селектор. "
    "Имена типов в реальных проектах повторяются: в одном здании три типа "
    "воздуховода назывались «По умолчанию» и различались только формой "
    "(круглый/прямоугольный/овальный). by=name там законно отказывает KIR-G102.",
    # Что делать с KIR-G102 (в диагностике уже лежат `candidates`) — в
    # `skill.REFUSAL_PLAYBOOK`: это тактика следующего хода, а не ловушка опа.
    # Здесь остаётся только то, чего курс не говорит: второй, более узкий путь
    # уточнения, применимый когда id брать неоткуда.
    "У неоднозначного селектора есть и второй путь уточнения — "
    "disambiguate_by={param, value}: принимается, только если после фильтра "
    "остаётся ровно один кандидат.",
    # ПОЧЕМУ ЗДЕСЬ ЖЕ, А НЕ ОТДЕЛЬНОЙ СТРОКОЙ. Запрет без выхода — это тупик, и
    # замер это показал: модель прочитала «сосед => KIR-L002», согласилась,
    # написала в скрипте «create_stairs обязан быть единственным» — и слепила
    # лестницу из 15 `create_floor`, потому что не знала, КУДА её деть. Правило,
    # способ и место проверки — одна мысль, и цену за неё платят один раз.
    # ВТОРАЯ ПОЛОВИНА ТОЙ ЖЕ ДЫРЫ, ЗАКРЫТАЯ 04.08. Канал был построен и молчал:
    # программы сессии копились в журнал, пачка уезжала витрине и исполнителю, а
    # МОДЕЛИ о том, что она строит здание по частям и что это здание кто-то
    # судит целиком, не говорилось нигде. В замере 03-04.08 модель освоила пачку
    # РОВНО потому, что ей об этом сказал стенд; в проде такой строки не было, и
    # модель писала здание одной программой. Строка стоит здесь, а не отдельной
    # ловушкой, по той же причине, по которой сюда переехало «здание = ПАЧКА»:
    # правило, способ, место проверки и обратная связь — одна мысль, и цену за
    # неё платят один раз.
    "`create_stairs` — единственный оп своей программы (StairsEditScope владеет "
    "собственными транзакциями; сосед => KIR-L002). Здание = ПАЧКА: тело "
    "отдельно, лестницы отдельно; уровень тела виден лестнице ПО ИМЕНИ "
    "(base_level=\"Этаж 1\", не ref). Программы сессии НАКАПЛИВАЮТСЯ в одно "
    "здание: вердикт о ПАЧКЕ сам приезжает в КВИТАНЦИИ пишущего хода "
    "(блок `building`); в скрипте — design_check([тело, лестница]).",
    "У аннотаций (`create_dimension`/`create_tag`/`create_text`) точка — это "
    "ПРОСТРАНСТВО ВИДА: [u,v] мм от начала вида вдоль его осей, не координата "
    "модели. Трёхкомпонентная точка там — типизированный отказ.",
    "`create_duct`/`route_duct_system` выражают только `diameter_mm`, то есть "
    "КРУГЛОЕ сечение. На прямоугольном типе постусловие честно поймает "
    "несовпадение диаметра и откатит транзакцию — выбери круглый тип.",
    "Сеть (`create_pipe_system`/`route_*`) — один оп на всю трассу: узлы плюс "
    "рёбра, связность по построению, фитинги выводятся из степени узла. "
    "Поворот требует, чтобы у типа было семейство отвода, иначе отказ назовёт "
    "угол и диаметры.",
    "`load_family` берёт ЯВНЫЙ путь к .rfa и сам проверяет наличие файла; путь "
    "угадывать нельзя. После загрузки пул типов наполняется — `create_type` "
    "дублирует типоразмер от загруженного символа.",
    # Until 2026-07-27 this idiom described something no caller could actually
    # do: `ground()` never recursed into `members`, so the emitter met a raw
    # selector and raised KeyError, reported as "члены должны быть pre-grounded
    # (element_id/…)" — advice that failed identically when followed. 0 uses in
    # 51 574 lifted ops. Members now ground like any other op.
    "`create_group` собирает нативную группу Revit: члены задаются один раз в "
    "абсолютных координатах, `placements` — смещения остальных вхождений. "
    "Селекторы у членов обычные (by name / element_id), как в любом опе; "
    "`by: ref` внутри группы не работает — член не видит соседние опы.",
    # wave/shape. Стоит здесь, а не в описании параметра, потому что выбор
    # операции модель делает ДО того, как прочитает её схему: если сказать про
    # меш только в схеме, «сделай оболочку» превратится в create_directshape
    # там, где надо было create_wall, и наоборот.
    "`create_directshape` строит ПРОИЗВОЛЬНУЮ ФОРМУ треугольным мешем — "
    "оболочку, решётку, скульптурный объём, то, чего не выразить контуром. "
    "Плата названа честно: это ГЕОМЕТРИЯ БЕЗ BIM-СМЫСЛА. У элемента нет типа "
    "и параметров, он не попадёт в спецификации как строительный элемент, и "
    "человек не отредактирует его как стену — только удалить и построить "
    "заново. Поэтому: стены, перекрытия, кровли, потолки, колонны, балки и "
    "лестницы делаются СВОИМИ операциями всегда, когда задача выражается ими; "
    "категории walls/floors/roofs/columns у этого опа нет вовсе, чтобы меш не "
    "мог выдать себя за них. Меш — для того, чего иначе не сказать, а не "
    "быстрый способ сказать что угодно.",
    "`delete` требует `allow_destructive: true` в конверте программы.",
    # Как ЧИТАТЬ отказ (в т.ч. `handoff`) — в `skill.READING_A_REFUSAL`: это
    # тактика следующего хода, а не ловушка конкретного опа.
)


#: ВЫБОР ФОРМЫ ВХОДА — первое решение задачи, и оно принимается ДО того, как
#: модель откроет схему операции. Поэтому текст стоит в начале описания, а не
#: в поле параметра: поле читают, когда форма уже выбрана.
#:
#: Числа НЕ литералами: `ALLOWED_IMPORTS`, `MAX_BULK_OPS` и авторский бюджет
#: интерполируются из своих источников — прозу, разошедшуюся с компилятором,
#: этот пакет уже оплачивал раундом (сказали «300», компилятор держал 20).
def _two_input_forms() -> list[str]:
    from kukai.ir.compiler import MAX_BULK_OPS, MAX_OPS_PER_PROGRAM
    allowed = ", ".join(sandbox.ALLOWED_IMPORTS)
    return [
        "ДВЕ ФОРМЫ ВХОДА, РОВНО ОДНА ЗА ВЫЗОВ: `program` (операции) ЛИБО "
        "`program_py` (питон, который их порождает). Оба сразу или ни одного "
        "— типизированный отказ.",
        f"  • ПЕРЕЧИСЛЕНИЕ разнородного — `program`: пять стен, дверь, "
        f"помещение. Потолок {MAX_OPS_PER_PROGRAM} операций.",
        f"  • ПОВТОР, РАСЧЁТ, СИЛУЭТ, МНОГО ЭТАЖЕЙ — `program_py`. Авторская "
        f"вещь тут скрипт, а не его выход, поэтому выход меряется другим "
        f"бюджетом: до {MAX_BULK_OPS} операций. Признак выбора один — если "
        f"пишешь третью почти одинаковую операцию, меняя в ней число, это "
        f"скрипт.",
        "КАК УСТРОЕН `program_py`. Каждая операция реестра уже лежит в "
        "пространстве скрипта ФУНКЦИЕЙ с теми же именами и полями (язык "
        "импортировать не надо и нельзя). Вызов кладёт оп в программу и "
        "возвращает РУЧКУ — её передают как level/host/target, и ссылки "
        "сходятся по построению. Конверт — "
        "`envelope(intent=..., defaults=..., allow_destructive=...)`, но "
        "`defaults` заполняет только ОПУЩЕННОЕ поле, а обязательный аргумент "
        "(`level` и родня) питон опустить не даст — держи его в переменной и "
        "передавай каждому вызову. Программу забирают сами: ни `return`, ни "
        "печати JSON не нужно.",
        f"  Импорт разрешён РОВНО: {allowed}. numpy/shapely/random/time/os "
        f"нет: недетерминизм запрещён жёстко, потому что исходник "
        f"подписывается в квитанции (`author_digest`), а подпись случайного "
        f"скрипта не удостоверяет ничего. Скрипт исполняется дважды и "
        f"дайджесты сверяются — разошлись, это отказ.",
        "  Макросов (`stack`/`series`/`grid_array`) в скрипте НЕТ: их работу "
        "делает сам питон — цикл, арифметика, список. Они остаются формой "
        "поля `program`.",
        "  `print(...)` возвращается тебе в квитанции. Печатай ЧИСЛОМ то, что "
        "приблизил (расхождение ломаной с кривой): названное приближение "
        "честно, неназванное — молчаливо неверный ответ.",
        "  Ошибка скрипта — типизированный отказ KIR-B* с НОМЕРОМ СТРОКИ "
        "твоего скрипта и самой строкой. Revit при этом не трогали вовсе: "
        "песочница стоит до компилятора и до транзакции.",
        # Строка про `tools/design/examples/*` УДАЛЕНА осознанно: она
        # рекламировала скрипты, которые в песочнице НЕ ЗАПУСТЯТСЯ (там numpy
        # и shapely, а белый список импортов — ровно math/itertools/functools).
        # Указатель на курс занимает её место и ведёт туда, куда дойти можно.
        *_course_pointer(),
    ]


def _course_pointer() -> tuple[str, ...]:
    """Указатель на курс — и он ОБЯЗАН быть парой к достижимости имён.

    Закон достижимости (`tests/capability_reachability`): способность, до
    которой нет пути от настоящей точки входа, не существует. У указателя эта
    же монета есть и с обратной стороны: описание, обещающее имена, которых в
    песочнице нет, дарит модели потерянный раунд. Поэтому пара «указатель ⟺
    имена» держится тестом `test_the_pointer_and_reachability_are_one_thing`, и
    половина шва красная.

    Импорт ленивый: `tool_doc` зовут на каждом ходу, а пакет курса тянет за
    собой замеры корпуса. Пусто вернуть нельзя — тогда шов разъедется молча.
    """

    from kukai.ir.course import POINTER

    return tuple(POINTER)


def program_py_schema() -> dict:
    """Схема поля `program_py`.

    НАМЕРЕННО ОДНА СТРОКА. Всё, чему тут можно было бы научить, уже стоит в
    описании инструмента (`_two_input_forms`), а описание поля оплачивается
    тем же токеном в том же запросе: пересказ здесь — это ровно вторая плата
    за одну мысль, и он ещё и разойдётся с оригиналом при первой правке.
    Порог `test_description_stays_small_next_to_the_schema` меряет ТОЛЬКО
    описание инструмента, поэтому дубль в поле не виден тесту, но виден счёту.
    """
    return {
        "type": "string",
        "description": (
            "Питон, который ПОРОЖДАЕТ программу IR (см. «ДВЕ ФОРМЫ ВХОДА» в "
            "описании инструмента). Взаимоисключающее с `program`."),
    }


def _writing_ops_by_kind() -> list[tuple[str, list[str]]]:
    """Writing ops grouped by the object kinds they cover, from the registry."""

    groups: dict[str, list[str]] = {}
    for name, op in sorted(spec.OPS.items()):
        if not op.writes_model:
            continue
        key = "/".join(sorted({kind for _action, kind in op.capability}))
        groups.setdefault(key, []).append(name)
    return sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))


def build_tool_description() -> str:
    """The `revit_ir` description string, generated so it cannot go stale."""

    reading = sorted(n for n, op in spec.OPS.items() if not op.writes_model)
    lines = [
        "Типизированная IR-программа для Revit: компилятор владеет единицами, "
        "версиями API и транзакциями, а любое постусловие проверяется на живой "
        "модели ПОСЛЕ создания — молчаливо-неверный результат невыразим.",
        "",
    ]
    lines.extend(_two_input_forms())
    lines += [
        "",
        f"ЧИТАЮЩИЕ ({len(reading)}): " + ", ".join(reading) + ". "
        "`query_list` возвращает id элементов — для выделения передай их в "
        "show_elements. `query_types` перечисляет {id, name} закрытого пула типов.",
        "",
        "ПИШУЩИЕ (" + str(sum(1 for op in spec.OPS.values() if op.writes_model)) + "):",
    ]
    for kind, names in _writing_ops_by_kind():
        lines.append(f"  {kind}: " + ", ".join(names))
    if UNPROVEN:
        lines.append("")
        lines.append("НЕ ОПИРАЙСЯ БЕЗ ПРОВЕРКИ:")
        lines.extend(f"  {name} — {why}" for name, why in sorted(UNPROVEN.items()))
    lines.append("")
    lines.append("ЛОВУШКИ (замерены живьём, из схемы не выводятся):")
    lines.extend(f"  • {note}" for note in NOTES)
    lines.extend(f"  • {item}" for item in CONSTRAINTS)
    # Суждения — отдельным модулем и отдельным блоком: NOTES отвечает на «что
    # тут неочевидно», skill — на «как думать». Разделение механическое, его
    # держит test_skill.test_skill_and_notes_do_not_overlap.
    lines.append("")
    lines.append(build_skill_text())
    return "\n".join(lines)


__all__ = ["CONSTRAINTS", "NOTES", "UNPROVEN", "build_tool_description",
           "program_py_schema"]
