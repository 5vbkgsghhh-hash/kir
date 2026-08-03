"""НАЗВАННОЕ УМОЛЧАНИЕ — правило выбора, а не первый попавшийся.

Опровергающий тест написан ПЕРВЫМ и воспроизводит живой случай 02.08.2026
дословно (`kir-bench`, задание T1, документ Snowdon):

* плечо C# взяло `.FirstOrDefault()` по коллектору — **1 тип двери из 62** и
  1 окна из 34 — и построило МОЛЧА. Пользователь получил дверь, которую не
  выбирал, и не узнает об этом;
* плечо KIR отказало `KIR-G102` со списком кандидатов, `execution:
  not_started`; перепись подтвердила НУЛЕВОЙ след.

Оба исхода плохи по-своему, и развилка между ними ЛОЖНАЯ. Правильный ответ
третий, и он тот же, что в HTML: **у кнопки есть вид по умолчанию, и он
НАЗВАН, а не случаен.** От `.FirstOrDefault()` названное умолчание отличается
ровно одним, но решающим: правило объявлено заранее, а сделанный по нему выбор
попал в квитанцию.

ПОЧЕМУ ПРАВИЛО ИМЕННО «САМЫЙ УПОТРЕБИМЫЙ В МОДЕЛИ», а не «дефолт документа»:
`ElementTypeGroup` НЕ содержит ни `DoorType`, ни `WindowType` — замерено
прибором по RevitAPI.xml всех шести версий (2021 и 2026 сверены поимённо,
94 члена; есть WallType/FloorType/RoofType/CeilingType/TextNoteType, дверей и
окон нет ни в одной). Поэтому у `create_wall.type` документный дефолт есть
(`ground.IN_EMIT_DEFAULT`), а спросить у Revit «твоя дверь по умолчанию»
НЕВОЗМОЖНО ПО ПОСТРОЕНИЮ. Правило обязано опираться на сам документ, и
единственное объяснимое — то, что сделал бы человек: «ставь такую же, как
уже стоит по всему проекту».

ГРАНИЦЫ ПРАВИЛА (строгость не сдаётся там, где она дёшева):
* ничья на максимуме -> отказ остаётся. Равенство значит, что в проекте НЕТ
  сложившейся практики, и выбор действительно произволен;
* ни одного размещённого экземпляра -> правило неприменимо, прежнее поведение;
* снапшот без счётчиков (старый мост) -> прежнее поведение, побайтово.
"""
from __future__ import annotations

import copy

from kukai.ir.compiler import compile_program
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

# Живая форма: 62 типа дверей в одном документе (Snowdon). Один из них
# поставлен по всему проекту, остальные — единично или ни разу. Ровно та
# ситуация, где `.FirstOrDefault()` молча берёт не то.
def _door_pool() -> list[dict]:
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}",
             "instances": 1 if i % 3 == 0 else 0}
            for i in range(62)]
    # сложившаяся практика проекта — 47 размещённых экземпляров
    pool[31] = {"id": 7031, "name": "Дверь однопольная 900x2100",
                "instances": 47}
    return pool


def _snapshot(**pools) -> dict:
    snap = copy.deepcopy(GROUND_SNAPSHOT)
    snap.update(pools)
    return snap


def _door_program() -> dict:
    """Дверь без `symbol` — модель не назвала тип, потому что ей всё равно."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000,
         "type": {"by": "name", "value": "Кирпич 250"}},
        {"op": "create_door", "id": "d1", "host": {"by": "ref", "value": "w1"},
         "offset_mm": 3000},
    ]}


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


def _ground_one(program: dict, snapshot: dict, op_name: str, param: str):
    """Заземление — отдельная стадия: `ground()` возвращает СВОЙ список опов с
    `{param: {"__grounded__": {...}}}`, и он НЕ попадает в PlannedProgram
    (замерено: `compiler.py:1077` держит его локальной переменной и отдаёт
    прямо в эмиттер). Поэтому правило проверяется на своей стадии, а его
    видимость пользователю — отдельным тестом про квитанцию ниже."""
    from kukai.ir import ground as ground_mod
    from kukai.ir.compiler import plan_program
    normed = plan_program(program, bulk=False).to_ops()
    grounded = ground_mod.ground(normed, snapshot)
    op = next(o for o in grounded if o["op"] == op_name)
    sel = op.get(param)
    return sel.get("__grounded__") if isinstance(sel, dict) else None


def _compile(program, snapshot):
    return compile_program(program, revit_version="2026", snapshot=snapshot,
                           bulk=False)


def test_the_live_refusal_we_are_here_to_remove():
    """СЕЙЧАС: 62 кандидата -> KIR-G102, ноль построенного. Это и чиним."""
    out = _compile(_door_program(), _snapshot(door_symbols=_door_pool()))
    assert out.ok, (
        "названное умолчание обязано построить дверь: правило «самый "
        f"употребимый» имеет однозначный максимум. Диагностики: {_codes(out)}")


def test_the_choice_is_named_in_the_receipt_not_merely_made():
    """Выбор без названного правила — это `.FirstOrDefault()` в костюме.

    Проверяем НЕ факт постройки, а отчётность: какое правило сработало, что
    именно выбрано и из скольких кандидатов. Без этого мы воспроизвели бы
    ровно тот дефект, ради которого тест написан.
    """
    snap = _snapshot(door_symbols=_door_pool())
    grounding = _ground_one(_door_program(), snap, "create_door", "symbol")
    assert grounding is not None, "заземление symbol обязано состояться"
    assert grounding.get("via") == "most_used", (
        f"правило обязано быть НАЗВАНО, получено via={grounding.get('via')!r}")
    assert grounding["id"] == 7031, "выбран не самый употребимый тип"
    assert grounding.get("rule_detail", {}).get("instances") == 47
    assert grounding.get("rule_detail", {}).get("candidates") == 62


def test_the_receipt_carries_the_choice_to_the_user():
    """Выбор, которого пользователь не видит, неотличим от `.FirstOrDefault()`.

    Это ВТОРАЯ половина работы и отдельный дефект: сегодня ни один сделанный
    компилятором выбор — даже давно существующий `sole_entry` — не доезжает до
    вызывающего. `ground()` отдаёт результат прямо в эмиттер, и `CompileOutput`
    о нём молчит.
    """
    out = _compile(_door_program(), _snapshot(door_symbols=_door_pool()))
    assert out.ok, _codes(out)
    report = out.as_dict().get("grounding_report")
    assert report, "квитанция обязана нести сделанные выборы"
    choice = next((r for r in report
                   if r["op_id"] == "d1" and r["param"] == "symbol"), None)
    assert choice is not None, f"выбор двери отсутствует в квитанции: {report}"
    assert choice["rule"] == "most_used"
    assert choice["chosen"]["id"] == 7031
    assert choice["chosen"]["name"] == "Дверь однопольная 900x2100"
    assert choice["rule_detail"]["candidates"] == 62


def test_a_tie_on_the_maximum_still_refuses():
    """Равенство = в проекте нет практики, и выбор действительно произволен."""
    pool = _door_pool()
    pool[7] = {"id": 7007, "name": "Дверь двупольная 1500x2100", "instances": 47}
    out = _compile(_door_program(), _snapshot(door_symbols=pool))
    assert not out.ok, "ничья на максимуме не должна разрешаться молча"
    assert "KIR-G102" in _codes(out), _codes(out)


def test_a_weak_lead_is_not_a_practice_measured_on_snowdon():
    """25 против 21 — это жребий, а не стандарт проекта.

    Числа взяты из живого замера 03.08.2026 по разобранным зданиям на диске
    (`snowdon_plumb`, двери: лидер 25, следующий 21, отрыв 1.2x, доля 17%).
    Без порога правило подписалось бы под утверждением «самый употребимый в
    модели» там, где разница составляет четыре двери.
    """
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}", "instances": 0}
            for i in range(26)]
    pool[3] = {"id": 7003, "name": "36\" x 84\" (60 MIN)", "instances": 25}
    pool[9] = {"id": 7009, "name": "36\" x 84\"", "instances": 21}
    out = _compile(_door_program(), _snapshot(door_symbols=pool))
    assert not out.ok, "отрыв 1.2x не может называться сложившейся практикой"
    assert "KIR-G102" in _codes(out), _codes(out)


def test_a_real_buildings_lead_still_builds():
    """Порог не должен убить смысл правила на НАСТОЯЩЕМ доме.

    `k2_ar_rd`, живой жилой дом с диска: 2096 дверей, 35 типов, лидер
    «ДГ 21-8 П» 500 против 272 — отрыв 1.8x. Это сложившийся стандарт
    проекта, и отказать здесь значило бы потерять результат ради круглого
    числа. Именно этот случай задал порог 1.5, а не 2.0.
    """
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}", "instances": 0}
            for i in range(35)]
    pool[2] = {"id": 7002, "name": "ДГ 21-8 П", "instances": 500}
    pool[5] = {"id": 7005, "name": "ДГ 21-9 Л", "instances": 272}
    grounding = _ground_one(_door_program(),
                            _snapshot(door_symbols=pool),
                            "create_door", "symbol")
    assert grounding["via"] == "most_used"
    assert grounding["id"] == 7002
    assert grounding["rule_detail"]["runner_up"] == 272


def test_a_clear_lead_still_builds():
    """2698 против 1219 — практика вне всяких сомнений."""
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}", "instances": 0}
            for i in range(21)]
    pool[2] = {"id": 7002, "name": "00_ДВ 21-13Л_балкон", "instances": 2698}
    pool[5] = {"id": 7005, "name": "00_ДВ 21-9Л", "instances": 1219}
    grounding = _ground_one(_door_program(),
                            _snapshot(door_symbols=pool),
                            "create_door", "symbol")
    assert grounding["via"] == "most_used"
    assert grounding["id"] == 7002
    assert grounding["rule_detail"]["runner_up"] == 1219


def test_the_receipt_shows_the_runner_up_so_the_user_can_judge():
    """Порог НАЗНАЧЕН, а не измерен — значит силу сигнала показываем всегда."""
    from kukai.ir.ground import describe_choices_ru
    note = describe_choices_ru([
        {"op_id": "d1", "param": "symbol", "rule": "most_used",
         "chosen": {"id": 7031, "name": "ДГ 21-8 П"},
         "rule_detail": {"instances": 500, "candidates": 35,
                         "runner_up": 272}}])
    assert "500" in note and "272" in note, note


def test_no_placed_instances_keeps_the_old_behaviour():
    """Ни одного размещённого — правилу не на что опереться."""
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}", "instances": 0}
            for i in range(62)]
    out = _compile(_door_program(), _snapshot(door_symbols=pool))
    assert not out.ok
    assert "KIR-G102" in _codes(out), _codes(out)


def test_a_snapshot_without_counters_is_byte_stable():
    """Старый мост не шлёт счётчиков — поведение обязано остаться прежним."""
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}"} for i in range(62)]
    out = _compile(_door_program(), _snapshot(door_symbols=pool))
    assert not out.ok
    assert "KIR-G102" in _codes(out), _codes(out)


def test_an_explicit_selector_still_wins_over_the_rule():
    """Умолчание заполняет молчание, оно НИКОГДА не переопределяет сказанное."""
    program = _door_program()
    program["ops"][1]["symbol"] = {"by": "element_id", "value": 7005}
    snap = _snapshot(door_symbols=_door_pool())
    grounding = _ground_one(program, snap, "create_door", "symbol")
    assert grounding["id"] == 7005
    assert grounding["via"] == "element_id"


def test_the_note_speaks_human_not_machine():
    """`via=most_used` в ответе — машинный код, выданный за объяснение."""
    from kukai.ir.ground import describe_choices_ru
    note = describe_choices_ru([
        {"op_id": "d1", "param": "symbol", "rule": "most_used",
         "chosen": {"id": 7031, "name": "Дверь однопольная 900x2100"},
         "rule_detail": {"instances": 47, "candidates": 62}}])
    assert "Дверь однопольная 900x2100" in note
    assert "самый употребимый" in note
    assert "47" in note and "62" in note
    assert "most_used" not in note


def test_the_note_is_silent_when_there_was_nothing_to_choose():
    """Примечание «ничего не произошло» — шум, а шум учит не читать примечания."""
    from kukai.ir.ground import describe_choices_ru
    assert describe_choices_ru([]) == ""
    # единственный в модели — выбора не было, защищать нечего
    assert describe_choices_ru([
        {"op_id": "w1", "param": "type", "rule": "sole_entry",
         "chosen": {"id": 100, "name": "Кирпич 250"}}]) == ""


def test_an_uncategorised_pool_must_not_get_a_named_default():
    """ПУЛ БЕЗ КАТЕГОРИИ СРАВНИВАЕТ НЕСРАВНИМОЕ — и правило там обязано молчать.

    ОПРОВЕРГАЮЩИЙ ТЕСТ, НАПИСАННЫЙ ПЕРВЫМ. Он падал на первой редакции правила,
    и падал по делу: `family_symbols` стоял в списке пулов, а он ЕДИНСТВЕННЫЙ
    собирается без фильтра категории —

        __AddPool("door_symbols",   ...OfClass(FamilySymbol).OfCategory(OST_Doors)...)
        __AddPool("family_symbols", ...OfClass(FamilySymbol)...)   ← фильтра НЕТ

    (`open_model.GROUND_SNAPSHOT_CS`; у остальных шести пулов правила фильтр
    категории есть, у beam_types ещё и по типу размещения).

    ЗАМЕР, КОТОРЫЙ ЭТО ВСКРЫЛ (офлайн-репетиция по 63 сохранённым разборам,
    03.08.2026, до живого Revit). Что правило выбирало в `family_symbols`:

        R_0_200Lx50W_-50   10 190 экз., отрыв 1.73x  — ТИП ИМПОСТА ВИТРАЖА
        Standard            8 070 экз., отрыв 4.51x
        170x60x5              151 экз., отрыв 2.29x
        305x305x97UC            2 экз., отрыв «нет второго» — стальной профиль

    Импост витража не размещается `place_family` в принципе: его порождает сетка
    носителя. То есть `place_family` без `symbol` получал бы молча объект, который
    этой операцией не ставится, — и это ХУЖЕ прежнего отказа, а не лучше.

    ПОРОГ ЗДЕСЬ НЕ ЗАЩИЩАЕТ, и это главное. Отрывы 2.29x, 3.65x, 4.51x —
    уверенные; беда не в силе сигнала, а в том, что «самый употребимый» среди
    ВСЕХ семейств документа сравнивает импост с мебелью и с маркой помещения.
    Утверждение «в этом проекте так принято» осмысленно только ВНУТРИ рода вещи.

    Поэтому граница правила структурная, а не числовая: пул без сужения по
    категории названного умолчания не получает никогда.
    """
    mullion_heavy = [
        # Живая форма k2_ar_rd: импостов витража в разы больше, чем всего
        # остального, потому что их порождает сетка, а не человек.
        {"id": 9001, "name": "R_0_200Lx50W_-50", "instances": 10190},
        {"id": 9002, "name": "Стул офисный", "instances": 5876},
        {"id": 9003, "name": "Стол рабочий", "instances": 120},
    ]
    program = {"ir_version": "1.0", "ops": [
        {"op": "place_family", "id": "f1", "xyz": [1000, 1000, 0],
         "level": {"by": "name", "value": "Этаж 1"}},
    ]}
    out = compile_program(
        program, "2026", snapshot=_snapshot(family_symbols=mullion_heavy))
    assert not out.ok, (
        "place_family без symbol МОЛЧА получил тип из пула без категории; "
        "на живых данных это оказывался импост витража")
    assert any(d.code == "KIR-G102" for d in out.diagnostics), (
        "отказ обязан остаться типизированным KIR-G102 с кандидатами — "
        f"получено {[d.code for d in out.diagnostics]}")


def test_every_named_pool_is_narrowed_by_category():
    """Замок на СТРУКТУРНУЮ границу, а не на список имён.

    Список пулов держит соседний тест, но список — это перечень, и он не
    объясняет, ПОЧЕМУ пула в нём нет. Здесь проверяется само правило членства:
    каждый пул названного умолчания обязан быть сужен категорией в самом
    коллекторе снапшота. Автор, который захочет добавить пул, обязан сначала
    сузить его коллектор — и тогда добавление станет безопасным по построению,
    а не по внимательности ревьюера.
    """
    from kukai.ir.ground import MOST_USED_POOLS
    from kukai.ir.open_model import GROUND_SNAPSHOT_CS

    unnarrowed = []
    for pool in sorted(MOST_USED_POOLS):
        marker = f'__AddPool("{pool}"'
        start = GROUND_SNAPSHOT_CS.find(marker)
        assert start != -1, f"пул {pool} не собирается снапшотом вовсе"
        line = GROUND_SNAPSHOT_CS[start:GROUND_SNAPSHOT_CS.find("\n", start)]
        if ".OfCategory(" not in line:
            unnarrowed.append(pool)
    assert not unnarrowed, (
        "пул названного умолчания обязан быть сужен категорией — иначе "
        "«самый употребимый» сравнивает несравнимое (замер 03.08: импост "
        f"витража против мебели): {unnarrowed}")


def test_the_pool_list_is_closed_and_this_test_is_the_lock():
    """Список пулов правила ЗАКРЫТ, и комментарий в ground.py это обещает.

    Обещание без замка — та самая документация, которая утверждает
    противоположное правде (класс дефекта, названный в каноне пакета). Пул,
    попавший в правило без замера, превращает честный отказ в тихую подмену —
    ровно в тот дефект, ради которого правило написано. Расширение списка
    обязано быть отдельным решением, которое ломает этот тест и заставляет
    автора объяснить, чем он это померил.
    """
    from kukai.ir.ground import MOST_USED_POOLS
    assert MOST_USED_POOLS == frozenset({
        "door_symbols", "window_symbols",
        "column_symbols_structural", "column_symbols_architectural",
        "foundation_symbols", "beam_types",
    }), ("список пулов названного умолчания изменён — это осознанное решение "
         "с замером, а не побочный эффект правки")


def test_every_named_pool_actually_exists_in_the_registry():
    """Правило, объявленное на несуществующий пул, — мёртвая буква."""
    from kukai.ir.ground import MOST_USED_POOLS
    from kukai.ir import spec
    declared = {pool.format(category=category)
                for op in spec.OPS.values()
                for _param, pool, _req in op.grounded
                for category in ("structural", "architectural")}
    unknown = MOST_USED_POOLS - declared
    assert not unknown, f"пулы правила отсутствуют в реестре: {sorted(unknown)}"


def test_the_sole_entry_path_is_untouched():
    """Единственный в пуле разрешался и раньше — правило не меняет этот путь."""
    grounding = _ground_one(_door_program(), GROUND_SNAPSHOT,
                            "create_door", "symbol")
    assert grounding["via"] == "sole_entry"
