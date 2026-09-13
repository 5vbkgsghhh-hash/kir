# -*- coding: utf-8 -*-
"""`query_level_plan` — фон для листа, пачкой за один вызов.

🔴 ЗАЧЕМ ОП. Слово владельца: «остальное здание становится полупрозрачным».
Гасить было нечего, и не по забывчивости: чтения геометрии ПАЧКОЙ в дереве не
было ни одного. `open_model.prune_ground_snapshot` держит отметки и сечения
типов; `spec.LIST_FIELDS` не несёт ни одной координаты; геометрию давал только
`query_inspect` — по ОДНОМУ элементу за оп, то есть этаж в 200 стен стоил бы 200
опов. Форма согласована с W файлом
`.work/prod-20260913/W-preview/GROUND_CONTRACT.md` (раздел «Ответы W»), а не
правкой его файлов.

Это ОФЛАЙН-ЭТАЛОН: фиксированный вход → фиксированные свойства эмиссии, без
Ревита. Компиляция против настоящих сборок 2021/2023/2024/2026 — отдельным
пином ниже.
"""
import pytest

from kir import compile_program, spec
from kir.tests.fixtures import GROUND_SNAPSHOT

LEVEL = {"by": "name", "value": "Уровень 1"}


def emitted(**extra):
    result = compile_program({"ops": [{"op": "query_level_plan", "id": "g1",
                                       "level": LEVEL, **extra}]},
                             revit_version="2023", snapshot=GROUND_SNAPSHOT)
    assert result.ok, [d.message_ru for d in result.diagnostics]
    return result.csharp


def refused(**extra):
    op = {"op": "query_level_plan", "id": "g1", "level": LEVEL, **extra}
    result = compile_program({"ops": [op]}, revit_version="2023",
                             snapshot=GROUND_SNAPSHOT)
    assert not result.ok, "ожидался отказ"
    return " | ".join(d.message_ru for d in result.diagnostics)


# ── реестр знает оп ──────────────────────────────────────────────────────────

def test_the_registry_owns_the_op_and_it_reads_nothing_but_reads():
    op = spec.OPS["query_level_plan"]
    assert op.effect is spec.EffectKind.READ
    assert op.family == "query"
    assert {p.name for p in op.params} == {"level", "include", "detail", "limit"}
    assert [p.name for p in op.params if p.required] == ["level"]


def test_the_generated_schema_offers_the_ops_OWN_vocabulary():
    """🔴 Ветка `fields` прибита к LIST_FIELDS; `enum_list` — нет, и это причина
    его существования. Схема, предлагающая чужой словарь, — верная проверка при
    ложной подсказке."""
    from kir import schema_gen
    schema = schema_gen._op_schema(spec.OPS["query_level_plan"])
    assert schema["properties"]["include"]["items"]["enum"] == list(spec.LEVEL_PLAN_INCLUDE)
    assert schema["properties"]["detail"]["enum"] == list(spec.LEVEL_PLAN_DETAIL)
    assert "level_name" not in schema["properties"]["include"]["items"]["enum"], (
        "словарь LIST_FIELDS здесь был бы чужим")


# ── 🔴 счёт ДО геометрии ─────────────────────────────────────────────────────

def test_the_count_is_taken_before_a_single_coordinate_is_read():
    """ГЛАВНОЕ СВОЙСТВО. Отказ после того, как геометрия этажа уже в памяти
    Ревита владельца, — это не предел, а отчёт о превышении. Правило оплачено
    живьём 13.09.2026 в шаге §4 окна: круг последствий называется ДО эффекта."""
    cs = emitted()
    предел = cs.index("level_plan_too_many_elements")
    first_geometry = min(cs.index(needle) for needle in
                         ("LocationCurve", "get_BoundingBox", "LocationPoint"))
    assert предел < first_geometry, (
        "проверка предела обязана стоять РАНЬШЕ первого чтения геометрии")
    # И счёт — по коллекторам, а не по уже собранным строкам.
    assert cs.index("ToList();") < предел


def test_the_element_limit_refusal_names_both_levers_and_the_numbers():
    cs = emitted(limit=7)
    assert "предел limit = 7" in cs
    assert "сузь include" in cs and "подними limit" in cs
    assert str(spec.LEVEL_PLAN_LIMIT_MAX) in cs


def test_the_byte_ceiling_is_the_sandboxes_own():
    """8 MiB — не круглое число из головы, а потолок песочницы: перешагнув его,
    ответ всё равно был бы усечён ниже по тракту, но БЕЗ имени."""
    from kir import sandbox
    cs = emitted()
    assert str(sandbox.MAX_RESULT_BYTES) in cs
    assert "level_plan_too_large" in cs


# ── 🔴 отсутствие ≠ пустота ≠ усечение ───────────────────────────────────────

def test_three_states_are_three_different_values_not_one_silence():
    """Правило не моё: так уже записано в докстроке `prune_ground_snapshot`."""
    cs = emitted()
    assert '"rows"' in cs and '"truncated"' in cs and '"limit_hit"' in cs
    # «уровень не найден» — это НЕ пустой уровень, и так и сказано словами.
    assert "уровень не найден" in cs and "НЕ пустой уровень" in cs
    # Усечение всегда называет, ЧЕМ оно вызвано.
    assert '"elements"' in cs and '"bytes"' in cs


# ── строки: личность, порядок, единицы ───────────────────────────────────────

def test_every_row_carries_both_names_of_the_element():
    cs = emitted()
    assert cs.count('__row["element_id"]') == 4, "по одному на каждый включённый род"
    assert cs.count('__row["unique_id"]') == 4


def test_the_id_form_is_the_only_one_that_works_on_all_six_versions():
    """🔴 `.Value` не существует до 2024, `.IntegerValue` мёртв на 2026.
    Реестр уже выбрал `Id.ToString()` (`_emit_row`), и это же строка — ровно тот
    тип, который держит кадр: `preview.DrawnElement.element_id: str`."""
    cs = emitted()
    assert ".Id.Value" not in cs and ".IntegerValue" not in cs
    assert '__row["element_id"] = __e.Id.ToString();' in cs


def test_the_order_is_stable_and_numeric_and_it_is_sorted_HERE():
    """Ответ W 2: лист перерисовывается каждым кадром, выделение работает по
    `data-el`, и при плавающем порядке узлы тасуются — клик слетает, а кадр
    читается как изменение здания. Сортировать у W значило бы завести второй
    источник правды о порядке."""
    cs = emitted()
    assert "OrderBy" in cs and "long.TryParse" in cs, (
        "порядок числовой: иначе «1000» встало бы раньше «999»")


def test_millimetres_everywhere_and_no_feet_leak():
    cs = emitted()
    assert "ConvertFromInternalUnits" in cs
    assert "UnitTypeId.Millimeters" in cs
    assert "ConvertToInternalUnits" not in cs.split("query_level_plan")[1], (
        "читающий оп ничего не переводит В футы"
    )


# ── рода следов ──────────────────────────────────────────────────────────────

def test_a_curved_wall_is_NAMED_not_straightened():
    """Врать прямым отрезком нельзя: на листе это другое здание."""
    cs = emitted(include=["walls"])
    assert '"arc"' in cs and '"line"' in cs and '"unsupported"' in cs
    assert "Tessellate()" in cs
    from kir.geom import MAX_RING_POINTS
    assert str(MAX_RING_POINTS) in cs, "предел точек НАЗВАН, а не бесконечен"
    assert '__row["tessellated"]' in cs
    assert "WALL_ATTR_WIDTH_PARAM" in cs, "толщина — это половина стены на плане"


def test_detail_travels_in_EVERY_floor_row_because_the_frame_draws_them_differently():
    """Условие W 1: без `detail` в строке кадр залил бы прямоугольник там, где у
    Г-образной плиты крыла нет."""
    box = emitted(include=["floors"], detail="box")
    assert '__row["detail"] = "box";' in box
    assert "EdgeLoops" not in box, "box не платит за контур"

    sketch = emitted(include=["floors"], detail="sketch")
    assert '__row["detail"] = "sketch";' in sketch
    assert "EdgeLoops" in sketch and "PlanarFace" in sketch
    assert '__row["holes_mm"]' in sketch, "дыры — не то же, что внешнее кольцо"
    # Контур мог не сняться — тогда строка честно падает в box и ГОВОРИТ об этом.
    assert '__row["sketch_unavailable"]' in sketch


def test_an_opening_names_its_host_by_identity_not_only_by_number():
    """Номер живёт внутри одного документа и переиспользуется после удаления —
    связать фон с публикацией по нему одному нельзя."""
    cs = emitted(include=["openings"])
    assert '__row["host_unique_id"]' in cs and '__row["host_element_id"]' in cs
    assert '"door"' in cs and '"window"' in cs


def test_include_narrows_the_emission_which_is_what_makes_the_lever_real():
    """Отказ по `limit` первым рычагом называет `include` — значит `include`
    обязан РЕАЛЬНО удешевлять вызов, а не только фильтровать ответ."""
    one = emitted(include=["walls"])
    all_four = emitted()
    assert len(one) < len(all_four)
    assert "OST_Floors" not in one and "OST_Floors" in all_four


# ── отказы ───────────────────────────────────────────────────────────────────

def test_control_a_foreign_include_value_is_printed_by_name():
    text = refused(include=["walls", "мебель"])
    assert "мебель" in text and "walls" in text


def test_control_include_must_not_repeat_itself():
    assert "дубликаты" in refused(include=["walls", "walls"])


def test_control_a_ref_level_is_refused_with_the_reason():
    """Оп читает фон СУЩЕСТВУЮЩЕГО документа: ref называет то, чего в модели
    ещё нет."""
    op = {"op": "query_level_plan", "id": "g1", "level": {"by": "ref", "value": "L1"}}
    result = compile_program({"ops": [op]}, revit_version="2023", snapshot=GROUND_SNAPSHOT)
    assert not result.ok
    text = " | ".join(d.message_ru for d in result.diagnostics)
    assert "ref" in text and "element_id" in text


def test_control_limit_beyond_the_ceiling_is_refused_with_the_ceiling_named():
    text = refused(limit=spec.LEVEL_PLAN_LIMIT_MAX + 1)
    assert str(spec.LEVEL_PLAN_LIMIT_MAX) in text


def test_control_an_unknown_detail_names_the_cost_of_each_choice():
    text = refused(detail="solid")
    assert "box" in text and "sketch" in text and "дорого" in text


def test_control_a_missing_level_is_refused_not_defaulted():
    op = {"op": "query_level_plan", "id": "g1"}
    result = compile_program({"ops": [op]}, revit_version="2023", snapshot=GROUND_SNAPSHOT)
    assert not result.ok
    assert "level" in " | ".join(d.field_name or "" for d in result.diagnostics)


# ── ЭТАЛОН: байты эмиссии не гуляют от порядка, в котором автор набрал include ──

def test_the_emission_does_not_depend_on_the_order_include_was_typed_in():
    """Иначе одна и та же программа давала бы разные байты, и паритет стал бы шумом."""
    assert emitted(include=["floors", "walls"]) == emitted(include=["walls", "floors"])


@pytest.mark.parametrize("version", ["2021", "2023", "2024", "2026"])
def test_the_body_compiles_against_the_real_revit_assemblies(version):
    """Пин компиляции. Сам компилятор .NET здесь не запускается — это делает
    `.work/prod-20260913/N-native/offline_compile_check.py`, замер 13.09.2026:
    2021/2023/2024 — 4/4 ok (12 288 · 13 824 · 9 216 · 10 752 Б),
    2026 — 4/4 ok (12 288 · 13 312 · 9 216 · 10 240 Б).
    Здесь проверяется то, что от .NET не зависит: эмиссия для каждой версии
    состоялась и не несёт ни одной формы, мёртвой на другой версии."""
    for extra in ({}, {"detail": "sketch"}, {"include": ["walls"]},
                  {"include": ["openings", "columns"]}):
        result = compile_program(
            {"ops": [{"op": "query_level_plan", "id": "g1", "level": LEVEL, **extra}]},
            revit_version=version, snapshot=GROUND_SNAPSHOT)
        assert result.ok, [d.message_ru for d in result.diagnostics]
        assert ".Id.Value" not in result.csharp, "мертво до 2024"
        assert ".IntegerValue" not in result.csharp, "мертво на 2026"
