"""ВЕРДИКТ ОБЯЗАН ЕСТЬ ТО, ЧТО ПРОИЗВОДИТ ПЕСОЧНИЦА.

Замер 03.08, живой круг на девяти витках: модель пишет питон -> песочница
отдаёт ОПЕРАЦИИ KIR (`{"op": …, "id": …}`, поля плоско, ссылки
`{"by": "ref", …}`), а `spatial_model_from_program` принимает УЗЛЫ L1
(`{"kind": "op", "op_name": …, "params": {…}}`). Переходника в дереве не было,
и круг не замыкался ни разу.

Хуже самого разрыва — то, ЧЕМ он отвечал. Скормленные напрямую операции KIR
дают `ops = []` (ни у одного узла нет ключа `kind`), пустая модель попадает в
вырожденные ворота `_run_v2`, и вердикт печатает:

    HAB000 — model has no rooms

при 27 `create_room` в самой программе. Утверждение НЕПРАВДА, и врёт оно ровно
в ту сторону, в которую модель побежит чинить: добавлять помещения туда, где их
уже двадцать семь.

ЗАКОН, КОТОРЫЙ ДЕРЖАТ ЭТИ ТЕСТЫ. «Вход не той формы» и «в здании нет
помещений» — РАЗНЫЕ утверждения, и второе врёт. Дверь, получившая не свою
форму, обязана назвать это прямо, назвать увиденную форму и назвать дверь, в
которую надо было идти.

Прогон: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kukai/ir/tests/test_verdict_takes_kir_ops.py -q
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kukai.ir import design_check as dc  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════
# Материал: маленькое, но НАСТОЯЩЕЕ здание в форме песочницы
# ═════════════════════════════════════════════════════════════════════════

def kir_ops() -> list[dict]:
    """Две комнаты, замкнутые стенами, дверь и окно — операции KIR как есть.

    Форма ровно та, что выходит из `sandbox.execute_author_script(...).ops`:
    плоские поля, `id` строкой, ссылки селекторами `{"by": "ref"}`.
    """
    ops: list[dict] = [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"},
        {"op": "create_level", "id": "lvl2", "elev_mm": 3000, "name": "Этаж 2"},
    ]
    lvl = {"by": "ref", "value": "lvl"}
    # прямоугольник 8000 x 5000 с перегородкой посередине
    box = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
           ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
           ((4000, 0), (4000, 5000))]
    for i, (p0, p1) in enumerate(box, start=1):
        ops.append({"op": "create_wall", "id": f"w{i}", "p0_mm": list(p0),
                    "p1_mm": list(p1), "level": lvl, "height_mm": 3000})
    ops.append({"op": "create_room", "id": "r1", "xy": [2000, 2500],
                "level": lvl, "name": "Жилая комната"})
    ops.append({"op": "create_room", "id": "r2", "xy": [6000, 2500],
                "level": lvl, "name": "Кухня"})
    ops.append({"op": "create_door", "id": "d1",
                "host": {"by": "ref", "value": "w5"}, "offset_mm": 2500})
    ops.append({"op": "create_window", "id": "win1",
                "host": {"by": "ref", "value": "w1"}, "offset_mm": 2000})
    ops.append({"op": "create_window", "id": "win2",
                "host": {"by": "ref", "value": "w3"}, "offset_mm": 2000})
    return ops


def l1_nodes() -> list[dict]:
    """Те же две комнаты, но в форме УЗЛОВ L1 — внутреннее дело декомпилятора."""
    return [
        {"kind": "op", "op_name": "create_level", "_id": "n1",
         "source_element_id": "1", "params": {"elev_mm": 0, "name": "Этаж 1"}},
        {"kind": "op", "op_name": "create_room", "_id": "n2",
         "source_element_id": "2",
         "params": {"xy": [1000, 1000], "name": "Жилая",
                    "level": {"by": "name", "value": "Этаж 1", "_id": "1"}}},
    ]


# ═════════════════════════════════════════════════════════════════════════
# 1. ВЕРДИКТ ЕСТ ОПЕРАЦИИ KIR
# ═════════════════════════════════════════════════════════════════════════

def test_kir_ops_reach_the_verdict_with_their_rooms_intact() -> None:
    """Главное утверждение: то, что отдаёт песочница, доезжает до вердикта.

    Меряется не «функция не упала», а ЧИСЛО: помещений в вердикте столько же,
    сколько `create_room` в программе. Тождество формы без этого числа ничего
    не доказывает — пустая модель тоже «преобразуется успешно».
    """
    ops = kir_ops()
    declared = sum(1 for op in ops if op["op"] == "create_room")
    model, witness = dc.spatial_model_from_ops(ops, building_id="проба")
    assert witness.rooms_total == declared == 2
    assert witness.counts["walls"] == 5
    assert witness.counts["doors"] == 1
    assert witness.counts["windows"] == 2

    verdict = dc.check_ops(ops, building_id="проба")
    blocking = [v.rule_id for v in verdict.report.blocking]
    assert "HAB000" not in blocking, (
        "вердикт по 15 операциям с двумя помещениями всё ещё говорит "
        "«в модели нет помещений»")
    # И это не пустой прогон: полигоны сложились, значит правила о площадях
    # и свете действительно высказались.
    assert witness.rooms_measured == 2, witness.unmeasured_reasons


def test_the_ops_door_is_not_a_tautology() -> None:
    """Обратимость мало что доказывает: результат обязан быть ЗАКОННЫМ.

    Проверяем, что полигоны настоящие (площади сошлись с чертежом: 4x5 и 4x5
    метра), а не что «преобразование прошло».
    """
    model, _ = dc.spatial_model_from_ops(kir_ops(), building_id="проба")
    areas = sorted(round(room.area_m2) for room in model.rooms)
    assert areas == [20, 20], areas
    assert {room.name for room in model.rooms} == {"Жилая комната", "Кухня"}


# ═════════════════════════════════════════════════════════════════════════
# 2. НЕ ТА ФОРМА — НАЗВАНА ПРЯМО, А НЕ ПЕРЕСКАЗАНА КАК «НЕТ ПОМЕЩЕНИЙ»
# ═════════════════════════════════════════════════════════════════════════

def test_the_l1_door_refuses_kir_ops_instead_of_reporting_an_empty_building() -> None:
    """ДЕФЕКТ, ради которого написан файл.

    До починки: `spatial_model_from_program(kir_ops())` возвращает модель без
    единого помещения, и вердикт по ней печатает HAB000 «model has no rooms».
    После: типизированный отказ, который называет увиденную форму.
    """
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.spatial_model_from_program(kir_ops(), building_id="проба")
    text = caught.value.render()
    assert "KIR-V001" in text
    assert "create_level" in text or "ops[0]" in text
    # Отказ обязан назвать ДВЕРЬ, в которую надо было идти.
    assert "spatial_model_from_ops" in text or "check_ops" in text
    # И не имеет права выглядеть как утверждение о здании.
    assert "no rooms" not in text and "нет помещений" not in text


def test_the_ops_door_refuses_l1_nodes_and_says_whose_form_that_is() -> None:
    """Симметрия: форма L1 — внутреннее дело декомпилятора, и наружная дверь
    обязана сказать это, а не молча прочитать ноль операций."""
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.spatial_model_from_ops(l1_nodes(), building_id="проба")
    text = caught.value.render()
    assert "KIR-V001" in text
    assert "L1" in text


@pytest.mark.parametrize("bad, needle", [
    ([], "пуст"),
    ("create_wall", "строка"),
    ([{"op": "create_wall"}, 42], "ops[1]"),
    ([{"id": "w1", "p0_mm": [0, 0]}], "op"),
])
def test_every_wrong_input_names_itself(bad, needle) -> None:
    """Отказ без имени увиденного — это второй раунд ремонта."""
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.spatial_model_from_ops(bad, building_id="проба")
    assert needle in caught.value.render(), caught.value.render()


def test_a_program_envelope_is_accepted_as_well_as_a_bare_list() -> None:
    """Песочница отдаёт список, конвейер — `{"ops": [...]}`. Обе формы —
    операции KIR, и требовать распаковки от вызывающего значило бы завести
    третью форму там, где их и так две."""
    envelope = {"ir_version": "1.0", "ops": kir_ops()}
    model, witness = dc.spatial_model_from_ops(envelope, building_id="проба")
    assert witness.rooms_total == 2


# ═════════════════════════════════════════════════════════════════════════
# 3. ЗАГОЛОВОК НЕ СИЛЬНЕЕ ТЕЛА
# ═════════════════════════════════════════════════════════════════════════

def test_a_not_evaluated_verdict_never_hides_rule_coverage() -> None:
    """Интеграционный носитель: на реальной KIR-программе часть правил
    оценена, а обязательные предусловия для других не доказаны. Итог
    честно `NOT_EVALUATED`, но он не имеет права скрыть знаменатель покрытия.
    """
    verdict = dc.check_ops(kir_ops(), building_id="проба")
    coverage = verdict.report.coverage
    evaluated = coverage.rules_evaluated
    total = len(coverage.outcomes)
    assert evaluated < total, (
        "материал перестал быть материалом: на этой программе оценены ВСЕ "
        "правила, и заголовку нечего скрывать — тест потерял предмет")
    # Обязательные предусловия отказывают fail-closed: этот носитель честно
    # NOT_EVALUATED и всё равно обязан назвать покрытие в первой строке.
    assert verdict.verdict is dc.Verdict.NOT_EVALUATED

    head = dc.render_verdict(verdict).splitlines()[0]
    assert str(evaluated) in head and str(total) in head, head
    assert "НЕ ОЦЕНЕН" in head.upper(), head
    # Исторически здесь был голый «ПРИГОДЕН»; ни этот старый
    # исход, ни голый «НЕ ОЦЕНЕНО» не имеют права скрыть покрытие.
    assert head.strip() != "═══ ВЕРДИКТ О ЗАМЫСЛЕ: ПРИГОДЕН ═══"


@pytest.mark.parametrize(("evaluated", "total"), [
    (0, 20),
    (10, 20),
    (20, 20),
])
def test_a_not_evaluated_headline_names_its_rule_coverage(
    evaluated: int, total: int,
) -> None:
    assert dc.verdict_headline_text(
        dc.Verdict.NOT_EVALUATED, evaluated=evaluated, total=total,
    ) == f"ИТОГ НЕ ОЦЕНЕН; ОЦЕНЕНО {evaluated} ПРАВИЛ ИЗ {total}"


def test_a_partial_pass_headline_names_its_rule_coverage() -> None:
    assert dc.verdict_headline_text(
        dc.Verdict.PASS, evaluated=10, total=20,
    ) == "ПРИГОДЕН ПО 10 ПРАВИЛАМ ИЗ 20, ОСТАЛЬНОЕ НЕ ОЦЕНЕНО"


def test_the_headline_of_a_full_pass_stays_short() -> None:
    """Оговорка не имеет права стоять там, где оговаривать нечего: если
    оценены все правила, заголовок обязан остаться простым."""
    verdict = dc.check_ops(kir_ops(), building_id="проба")
    coverage = verdict.report.coverage
    n = len(coverage.outcomes)
    assert dc.verdict_headline_text(
        dc.Verdict.PASS, evaluated=n, total=n) == "ПРИГОДЕН"


# ═════════════════════════════════════════════════════════════════════════
# 4. КРАТКИЙ ВЕРДИКТ ВЛЕЗАЕТ В КАНАЛ ПЕСОЧНИЦЫ
# ═════════════════════════════════════════════════════════════════════════

def separator_ops() -> list[dict]:
    """Комната, замкнутая ТРЕМЯ стенами и ОДНИМ разделителем помещений.

    Именно так замыкается всё, что открыто в коридор: четвёртой стены там нет
    и быть не должно. `create_room_separator` в языке ЕСТЬ (`spec.OPS`, замер
    мой, 03.08: параметры `path` + `level`), и программа его пишет.
    """
    lvl = {"by": "ref", "value": "lvl"}
    return [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"},
        # Уровень выше нужен по существу: высота помещения считается, только
        # если ограждение ДОХОДИТ до следующего уровня («ограждение — не
        # потолок»). Без него высота честно неизвестна, и тест про разбавление
        # голосования разделителями не имел бы предмета.
        {"op": "create_level", "id": "lvl2", "elev_mm": 3000, "name": "Этаж 2"},
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [4000, 0],
         "level": lvl, "height_mm": 3000},
        {"op": "create_wall", "id": "w2", "p0_mm": [4000, 0],
         "p1_mm": [4000, 5000], "level": lvl, "height_mm": 3000},
        {"op": "create_wall", "id": "w3", "p0_mm": [4000, 5000],
         "p1_mm": [0, 5000], "level": lvl, "height_mm": 3000},
        # ЧЕТВЁРТАЯ СТОРОНА — РАЗДЕЛИТЕЛЬ, а не стена.
        {"op": "create_room_separator", "id": "sep1",
         "path": [[0, 5000], [0, 0]], "level": lvl},
        {"op": "create_room", "id": "r1", "xy": [2000, 2500], "level": lvl,
         "name": "Жилая комната"},
    ]


def test_a_room_closed_by_a_separator_gets_its_polygon() -> None:
    """ДЕФЕКТ: планарное разбиение строилось ТОЛЬКО по `create_wall`.

    Разделитель помещений — полноправная граница помещения в Revit, и в языке
    KIR он есть. Пока он не доезжал до разбиения, комната, открытая в коридор,
    не замыкалась: площади нет, значит HAB020 говорит «площадь 0», HAB030 —
    «нет окна», HAB040/HAB060 молчат. Инструмент есть, данные есть, провода
    не было.
    """
    ops = separator_ops()
    model, witness = dc.spatial_model_from_ops(ops, building_id="проба")
    assert witness.rooms_total == 1
    assert witness.rooms_measured == 1, (
        f"комната не замкнулась: {dict(witness.unmeasured_reasons)}")
    assert round(model.rooms[0].area_m2) == 20, model.rooms[0].area_m2
    # Разделитель — НЕ стена: правила о стенах не имеют права его считать.
    assert witness.counts["walls"] == 3
    assert len(model.walls) == 3
    # И высоту он не выдумывает: у разделителя её нет вовсе.
    assert model.rooms[0].height_mm == 3000, model.rooms[0].height_mm


def test_a_separator_alone_does_not_invent_a_room() -> None:
    """Обратная сторона: разделитель, который ничего не замыкает, не имеет
    права дать помещению полигон."""
    ops = [op for op in separator_ops() if op["op"] != "create_wall"]
    _model, witness = dc.spatial_model_from_ops(ops, building_id="проба")
    assert witness.rooms_measured == 0
    assert witness.rooms_total == 1


def test_a_building_without_stairs_is_never_told_its_stairs_lack_geometry() -> None:
    """Д-4. `engine.RULE_SPECS_V2` несёт у HAB011 захардкоженную строку
    «stairs present but none has measured geometry» — и печатает её при НУЛЕ
    лестниц в модели. Строка утверждает наличие того, чего нет, и утверждает
    уверенно: модель читает её как «лестницы есть, но кривые».
    """
    verdict = dc.check_ops(kir_ops(), building_id="проба")
    assert verdict.witness.counts["stairs"] == 0, "материал потерял предмет"
    reasons = {o.rule_id: o.reason for o in verdict.report.coverage.outcomes}
    assert "stairs present" not in reasons["HAB011"], reasons["HAB011"]
    assert "лестниц" in reasons["HAB011"].lower(), reasons["HAB011"]


def test_a_building_with_stairs_still_gets_the_stair_rule() -> None:
    """Обратная сторона: снятие обязано быть УСЛОВНЫМ. Правило, снятое всегда,
    — это правило, которого нет.

    ПОЧЕМУ ЗДЕСЬ ПАЧКА, А НЕ ОДНА ПРОГРАММА (правка 04.08). Первая редакция
    дописывала `create_stairs` к телу и звала `check_ops` — то есть проверяла
    верное утверждение на программе, которую КОМПИЛЯТОР НЕ ВОЗЬМЁТ
    (`KIR-L002`: лестница владеет своими транзакциями и обязана быть
    единственным опом). Тест закреплял ровно тот дефект, ради которого потом
    завели `KIR-V003`: вердикт судил пригодность непостроимого. Утверждение
    осталось прежним, изменился носитель — лестница переехала в своё звено,
    как ей и положено в настоящем здании.
    """
    stairs = {"op": "create_stairs", "id": "s1",
              "p0_mm": [1000, 1000], "p1_mm": [1000, 4000],
              "base_level": {"by": "name", "value": "Этаж 1"},
              "top_level": {"by": "name", "value": "Этаж 2"},
              "width_mm": 1200}
    verdict = dc.check_bundle(
        [{"ir_version": "1.0", "ops": kir_ops()},
         {"ir_version": "1.0", "ops": [stairs]}],
        building_id="проба")
    assert verdict.witness.counts["stairs"] == 1
    assert "HAB011" not in verdict.rules_suspended, verdict.rules_suspended


def test_the_brief_verdict_fits_the_sandbox_stdout() -> None:
    """`stdout` песочницы обрезается на `MAX_STDOUT_CHARS`, и вердикт, съевший
    канал целиком, отнимает у модели её собственную печать. Полный вердикт для
    этого канала слишком велик — краткий обязан влезать с запасом."""
    from kukai.ir.sandbox import MAX_STDOUT_CHARS

    verdict = dc.check_ops(kir_ops(), building_id="проба")
    brief = dc.render_verdict_brief(verdict)
    assert len(brief) < MAX_STDOUT_CHARS // 2, len(brief)
    # Краткость не имеет права стоить честности: заголовок тот же.
    assert brief.splitlines()[0] == dc.render_verdict(verdict).splitlines()[0]
    # И он обязан назвать, что именно НЕ оценивалось.
    assert "не оценено" in brief.lower()


# ═════════════════════════════════════════════════════════════════════════
# 4. ЕДИНИЦА ЗДАНИЯ — ПАЧКА ПРОГРАММ, А НЕ ПРОГРАММА
#
# ДЕФЕКТ, ради которого написан этот раздел. Два правила по отдельности верны:
#   * `create_stairs` — единственный оп своей программы (KIR-L002): его
#     `StairsEditScope` владеет собственными транзакциями — факт Revit API;
#   * `HAB010` блокирует занятый уровень выше земли без лестничной связи.
# Вместе они давали третье, неверное: многоэтажное здание, выраженное ОДНОЙ
# программой, непригодно ПО ПОСТРОЕНИЮ — лестницу в него положить нельзя, а без
# неё вердикт обязан блокировать. Замер 03-04.08 (4 прогона A/B, 2 модели, по 20
# ходов): НИ ОДНОГО здания без блокирующих, у всех четырёх `лест 0`. Сильная
# модель нашла стену сама и слепила лестницу из 15 `create_floor`.
#
# Чинится ЕДИНИЦА СУЖДЕНИЯ, а не эмиттер: запрет — факт Revit, а вот судить
# программу там, где здание есть ПАЧКА программ, было нашей ошибкой.
# ═════════════════════════════════════════════════════════════════════════

def two_storey_body() -> dict:
    """Тело двухэтажного здания: БЕЗ лестницы — её туда класть запрещено.

    Лестничная клетка (помещение) здесь ЕСТЬ: она обычное помещение и закону
    KIR-L002 не противоречит. Нет только самой `create_stairs`.
    """
    ops: list[dict] = [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"},
        {"op": "create_level", "id": "lvl2", "elev_mm": 3000, "name": "Этаж 2"},
    ]
    box = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
           ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
           ((4000, 0), (4000, 5000))]
    for storey, lid in ((1, "lvl"), (2, "lvl2")):
        lvl = {"by": "ref", "value": lid}
        for i, (p0, p1) in enumerate(box, start=1):
            ops.append({"op": "create_wall", "id": f"w{storey}_{i}",
                        "p0_mm": list(p0), "p1_mm": list(p1),
                        "level": lvl, "height_mm": 3000})
        ops.append({"op": "create_room", "id": f"r{storey}", "xy": [6000, 2500],
                    "level": lvl, "name": "Жилая комната"})
        ops.append({"op": "create_room", "id": f"st{storey}", "xy": [2000, 2500],
                    "level": lvl, "name": "Лестничная клетка"})
        # дверь между жилой комнатой и лестничной клеткой
        ops.append({"op": "create_door", "id": f"d{storey}",
                    "host": {"by": "ref", "value": f"w{storey}_5"},
                    "offset_mm": 2500})
        ops.append({"op": "create_window", "id": f"win{storey}",
                    "host": {"by": "ref", "value": f"w{storey}_2"},
                    "offset_mm": 2500})
    # наружный вход — в лестничную клетку первого этажа
    ops.append({"op": "create_door", "id": "entrance",
                "host": {"by": "ref", "value": "w1_1"}, "offset_mm": 2000})
    return {"ir_version": "1.0", "ops": ops}


def stairs_program() -> dict:
    """Лестница ОТДЕЛЬНОЙ программой, уровни — ПО ИМЕНИ.

    По имени, а не ссылкой, и это не стиль: `create_stairs.base_level` не
    принимает `ref` (`ref_kinds` пуст — KIR-G002), а уровень к тому же живёт в
    ДРУГОЙ программе пачки, где его `id` уже не существует.
    """
    return {"ir_version": "1.0", "ops": [{
        "op": "create_stairs", "id": "s1",
        "p0_mm": [2000, 1000], "p1_mm": [2000, 4000],
        "base_level": {"by": "name", "value": "Этаж 1"},
        "top_level": {"by": "name", "value": "Этаж 2"},
        "width_mm": 1200}]}


def test_one_program_alone_cannot_express_a_habitable_two_storey_building() -> None:
    """ПОЛ, КАК ОН БЫЛ. Тело без лестницы обязано блокироваться по HAB010 —
    и это ЧЕСТНО: связи между этажами в нём действительно нет."""
    verdict = dc.check_ops(two_storey_body(), building_id="тело")
    blocking = [v.rule_id for v in verdict.report.blocking]
    assert "HAB010" in blocking, blocking


def test_the_same_building_as_a_bundle_clears_the_stair_rules() -> None:
    """ПОЛ СНЯТ. То же тело + лестница ОТДЕЛЬНОЙ программой -> HAB010 уходит.

    Проверяется не «блокирующих ноль» (это спутало бы ПРОЙДЕНО с НЕ
    ОЦЕНИВАЛОСЬ — правило, снятое профилем, тоже не попадает в блокирующие), а
    ДВА утверждения сразу: правило ОЦЕНЕНО и не нарушено.
    """
    verdict = dc.check_bundle([two_storey_body(), stairs_program()],
                              building_id="пачка")
    blocking = [v.rule_id for v in verdict.report.blocking]
    assert "HAB010" not in blocking, blocking
    assert "HAB001" not in blocking, blocking
    # И правило действительно ВЫСКАЗАЛОСЬ, а не было снято за отсутствием входа.
    assert "HAB010" not in verdict.rules_suspended, verdict.rules_suspended
    assert verdict.witness.counts["stairs"] == 1


def test_the_bundle_keeps_the_order_it_was_given() -> None:
    """Порядок пачки значим: программы исполняются последовательно, и уровень,
    созданный первой, существует для второй. Слияние — конкатенация."""
    model, _ = dc.spatial_model_from_bundle(
        [two_storey_body(), stairs_program()], building_id="пачка")
    # Лестница адресовала уровни ПО ИМЕНИ через границу программы — и нашла их.
    stair = model.stairs[0]
    elevations = {lvl.id: lvl.elevation_mm for lvl in model.levels}
    assert elevations[stair.base_level_id] == 0
    assert elevations[stair.top_level_id] == 3000


def test_colliding_ids_across_programs_are_named_not_silently_merged() -> None:
    """`id` уникален ВНУТРИ программы; между программами совпадение ЗАКОННО.

    Молча разрешить его в пользу последней программы значило бы потерять
    элемент И увести ссылку в чужую операцию. Обе выживают, адрес у каждой
    свой, а само столкновение НАЗВАНО в свидетеле.
    """
    one = {"ops": [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Э1"},
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "level": {"by": "ref", "value": "lvl"}, "height_mm": 3000}]}
    two = {"ops": [
        {"op": "create_level", "id": "lvl", "elev_mm": 3000, "name": "Э2"},
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "level": {"by": "ref", "value": "lvl"}, "height_mm": 3000}]}
    model, witness = dc.spatial_model_from_bundle([one, two], building_id="х")
    assert len(model.walls) == 2, "стена второй программы затёрла первую"
    assert {w.id for w in model.walls} == {"p1/w1", "p2/w1"}
    # Ссылка каждой стены разрешилась в СВОЙ уровень, а не в последний.
    by_id = {w.id: w.level_id for w in model.walls}
    assert by_id["p1/w1"] == "p1/lvl" and by_id["p2/w1"] == "p2/lvl"
    collision = [n for n in witness.notes if n.code == "bundle_id_collision"]
    assert collision and "lvl" in collision[0].detail, witness.notes


def test_a_ref_across_a_program_boundary_is_refused_by_name() -> None:
    """Ссылка живёт ВНУТРИ программы. Соседняя — отдельная транзакция, где id
    первой уже не существует; тихо проигнорировать такую ссылку значило бы
    судить не то здание, которое построится."""
    stairs = {"ops": [{
        "op": "create_stairs", "id": "s1", "p0_mm": [2000, 1000],
        "p1_mm": [2000, 4000],
        "base_level": {"by": "ref", "value": "lvl"},      # ЧУЖАЯ программа
        "top_level": {"by": "name", "value": "Этаж 2"}, "width_mm": 1200}]}
    with pytest.raises(dc.BundleContractError) as caught:
        dc.check_bundle([two_storey_body(), stairs], building_id="пачка")
    text = caught.value.render()
    assert "KIR-V002" in text
    assert "lvl" in text and "s1" in text        # что и где именно
    assert "имени" in text.lower()               # и куда идти вместо этого


@pytest.mark.parametrize("bad, needle", [
    ([], "пуст"),
    ("тело", "строка"),
])
def test_a_malformed_bundle_names_itself(bad, needle) -> None:
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.check_bundle(bad, building_id="проба")
    assert needle in caught.value.render(), caught.value.render()


def test_one_program_in_the_bundle_door_is_told_which_door_it_wanted() -> None:
    """Симметрия KIR-V001: дверь обязана назвать не только увиденное, но и ту
    дверь, в которую надо было идти."""
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.check_bundle(two_storey_body(), building_id="проба")
    text = caught.value.render()
    assert "KIR-V001" in text and "check_ops" in text


def test_a_list_of_programs_in_the_ops_door_is_told_about_the_bundle() -> None:
    """И обратно: пачка, поданная в дверь программы, обязана услышать про пачку,
    а не «по ключам не видно, что это»."""
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.check_ops([two_storey_body(), stairs_program()], building_id="проба")
    text = caught.value.render()
    assert "KIR-V001" in text and "check_bundle" in text


def test_a_query_op_is_not_mistaken_for_an_l1_node() -> None:
    """ДЕФЕКТ ФОРМЫ, найденный 04.08 при работе над пачкой.

    `_shape_of` спрашивал `kind` РАНЬШЕ `op`, а у `query_count`/`query_list`
    СВОЙ параметр называется `kind` и лежит плоско. Законная операция KIR
    объявлялась узлом L1, и `check_ops` отказывал KIR-V001, посылая В ЧУЖУЮ
    ДВЕРЬ — ровно та ложь о входе, против которой написан весь этот файл.
    """
    assert dc._shape_of({"op": "query_count", "id": "q", "kind": "wall"}) == "ops"
    ops = kir_ops() + [{"op": "query_count", "id": "q", "kind": "wall"}]
    model, _ = dc.spatial_model_from_ops(ops, building_id="проба")
    assert len(model.rooms) == 2
