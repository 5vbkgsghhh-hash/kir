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

from kukai.ir import spec
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
    "`{\"by\": \"ref\", \"value\": \"<id опа выше>\"}` работает для level/"
    "base_level/top_level, host, target и refs — то есть для того, что ты "
    "создаёшь в этой же программе. Для `type`/`symbol` ref НЕ работает: "
    "типоразмер выбирается по element_id или по name, не знаешь id — "
    "сначала query_types.",
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
    "Одна программа — не более 20 операций (MAX_OPS_PER_PROGRAM). Это мало "
    "намеренно: повторяющееся собирается не перечислением, а через "
    "create_group(members, placements) — панель на 19 операций, поставленная в "
    "40 мест, даёт 760 элементов одной программой. Крупное здание — это ПАЧКА "
    "программ, а не одна большая.",
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
    "`create_stairs` — единственный оп своей программы: StairsEditScope владеет "
    "собственными транзакциями (любой сосед => KIR-L002).",
    "Хост и цель адресуются через {\"by\": \"ref\", \"value\": \"<id опа выше>\"} — "
    "окно на только что созданной стене, марка на только что созданном элементе.",
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


__all__ = ["CONSTRAINTS", "NOTES", "UNPROVEN", "build_tool_description"]
