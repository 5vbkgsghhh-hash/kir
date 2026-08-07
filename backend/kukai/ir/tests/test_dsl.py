"""Исходный язык обязан быть ТЕМ ЖЕ языком, а не похожим на него.

Опасность питон-фронта ровно одна и она не в удобстве: он выглядит как язык,
но им не является. Стоит ему завести СВОЁ имя, СВОЁ умолчание или СВОЮ
проверку — и программа, собранная питоном, перестаёт быть той программой,
которую написали бы руками. Снаружи это неотличимо от успеха: компилируется,
исполняется, свидетель зелёный — а доказательство уже про другое.

Поэтому файл начинается с ОПРОВЕРГАЮЩИХ тестов, и первый из них — самый
сильный: программа, собранная DSL, обязана совпасть с УЖЕ ЗАКОММИЧЕННОЙ
золотой программой побайтово и совпасть с ней по `plan_digest`. Не «похожа»,
не «компилируется в тот же C#» — ТА ЖЕ.

Замер, который этот файл поймал (03.08.2026): питон-фронт, вписывающий
умолчание реестра в программу, меняет `plan_digest` (2df7a3bc… против
eb267955…) и подменяет `FieldOrigin.REGISTRY_DEFAULT` на `EXPLICIT`, то есть
стирает провенанс. См. `test_an_omitted_registry_default_keeps_its_provenance`.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import tempfile

import pytest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import dsl, sdk, spec  # noqa: E402
from kukai.ir.compiler import (  # noqa: E402
    BUDGET_INTERNAL_BULK, MAX_BULK_OPS, MAX_OPS_PER_PROGRAM, plan_program,
)
from kukai.ir.diag import KirRefusal  # noqa: E402
from kukai.ir.midend import FieldOrigin  # noqa: E402
from kukai.ir.tests.test_golden import PROGRAMS as GOLDEN  # noqa: E402
#: Образцы по ВИДУ параметра живут в `test_sdk` и там же под стражем («новый вид
#: параметра без образца» валит сборку). Второй такой таблицы заводить нельзя —
#: она разъедется ровно на новом виде. Здесь только ДОБАВКИ: общая таблица
#: намеренно даёт вырожденную геометрию (p0 == p1), а этому файлу нужна
#: программа, которая доходит до конца плана.
from kukai.ir.tests.test_sdk import _SAMPLES  # noqa: E402

ALL_OPS = sorted(spec.OPS)
REFERENCEABLE = sorted(n for n, o in spec.OPS.items() if o.result.referenceable)
UNREFERENCEABLE = sorted(n for n, o in spec.OPS.items()
                         if not o.result.referenceable)

#: Невырожденные значения там, где общая таблица даёт вырожденные.
_BY_PARAM: dict[str, object] = {
    "p1_mm": None,          # заполняется по виду ниже (2D/3D)
    "delta_mm": [100.0, 0.0, 0.0],
    "outline": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]],
}

#: Поля сверх обязательных, без которых оп не имеет смысла как программа.
#: Каждая строка — НАЗВАННАЯ причина, а не «чтобы тест позеленел».
_EXTRA: dict[str, dict] = {
    # place_family: положение задаётся ЛИБО точкой, ЛИБО кривой, и «ни того ни
    # другого» — типизированный отказ KIR-P007, а не форма JSON.
    "place_family": {"xyz": [0.0, 0.0, 0.0], "level": "Этаж 1"},
}


def _args_for(ospec: spec.OpSpec) -> dict:
    args = {}
    for p in ospec.params:
        if not p.required:
            continue
        if p.name == "p1_mm":
            args[p.name] = ([6000.0, 0.0] if p.kind == "pt_xy"
                            else [6000.0, 0.0, 0.0])
        elif p.name in _BY_PARAM and _BY_PARAM[p.name] is not None:
            args[p.name] = _BY_PARAM[p.name]
        elif p.kind == "enum":
            args[p.name] = (p.choices or ("x",))[0]
        else:
            args[p.name] = _SAMPLES[p.kind]
    args.update(_EXTRA.get(ospec.name, {}))
    return args


@pytest.fixture(autouse=True)
def _fresh_program():
    """Накопление НЕЯВНОЕ, значит утечка между тестами — реальный риск, и
    закрывать её обязан сам набор, а не порядок запуска."""
    dsl.reset()
    yield
    dsl.reset()


# ════════════════════════════════════════════════ ОПРОВЕРГАЮЩИЕ

def _canon(program: dict) -> str:
    return json.dumps(program, sort_keys=True, ensure_ascii=False)


def test_a_dsl_program_is_the_committed_golden_byte_for_byte():
    """САМЫЙ СИЛЬНЫЙ ТЕСТ ФАЙЛА.

    `full_house_v1` — не выдумка этого теста: это золотая программа из
    `test_golden.PROGRAMS`, у которой лежит отревьюенный снимок C#. Восемь
    опов, три вида селектора, ссылки на уровень и на стену. DSL обязан выдать
    ЕЁ ЖЕ — тот же JSON и ту же личность доказательства.
    """
    hand = GOLDEN["full_house_v1"]

    p = dsl.program(intent="полный дом v1")
    L1 = dsl.create_level(elev_mm=0, name="КИР-1", id="L1")
    W1 = dsl.create_wall(p0_mm=[0, 0], p1_mm=[8000, 0], level=L1, id="W1")
    dsl.create_window(host=W1, offset_mm=2000, sill_mm=900, id="Win1")
    dsl.create_door(host=W1, offset_mm=5000, id="D1")
    dsl.create_floor(outline=[[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
                     level=L1, id="F1")
    dsl.create_column(xy=[4000, 3000], level=L1, id="C1")
    dsl.create_room(xy=[4000, 3000], level=L1, name="Зал", id="R1")
    dsl.place_family(xyz=[2000, 2000, 0], level=L1, id="T1")
    got = p.build()

    assert _canon(got) == _canon(hand), "DSL собрал НЕ ту программу"
    assert (plan_program(got).plan_digest
            == plan_program(hand).plan_digest), "личность доказательства разная"


def test_a_handle_of_an_unreferenceable_op_cannot_pass_as_a_reference():
    """Ручка есть у каждого опа, ССЫЛКА — не у каждого.

    `ResultSpec` разделяет два факта намеренно: у группы и у удалённого
    элемента свидетельство идентичности есть, а корректной ссылки вперёд нет.
    Питон обязан отказать НА МЕСТЕ вызова и назвать причину из реестра — иначе
    автор узнаёт об этом слоями ниже, из KIR-L003, где уже не видно, какая
    строка скрипта виновата.
    """
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    line = dsl.create_curtain_grid_line(host=wall, direction="u",
                                        position_mm=[3000, 0, 0])
    assert isinstance(line, dsl.Handle)
    assert line.referenceable is False

    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_window(host=line, offset_mm=1000)
    message = got.value.diagnostics[0].message_ru
    assert "create_curtain_grid_line" in message
    assert "reference_kind" in message


@pytest.mark.parametrize("name", UNREFERENCEABLE)
def test_every_unreferenceable_op_says_so_and_says_why(name):
    """Параметризация по РЕЕСТРУ: новый оп без `reference_kind` приносит свой
    тест сам, и «забыли про ещё один» перестаёт быть возможным состоянием."""
    handle = dsl.Handle("x1", name, spec.OPS[name])
    assert handle.referenceable is False
    with pytest.raises(dsl.DslRefusal) as got:
        handle.as_selector()
    assert name in got.value.diagnostics[0].message_ru


def test_a_handle_refuses_indexing_and_names_the_two_honest_forms():
    """ЗАМЕР 04.08, второй по частоте класс (6 из 27). Оба прогона слабой
    модели НАЧАЛИСЬ с `query_types(...)[0]['id']` и потеряли по два хода.

    Индексировать нечего ПО ПОСТРОЕНИЮ: у читающего опа результата на момент
    письма программы не существует — он появится в Revit. Поэтому «сделать
    рабочим» значило бы вернуть «первый попавшийся» тип, то есть молча выбрать
    за автора. Остаётся второй путь: назвать правильную форму ДОСЛОВНО.
    """
    handle = dsl.query_types(pool="wall_types")
    for attempt in (lambda: handle[0], lambda: list(handle), lambda: len(handle)):
        with pytest.raises(dsl.DslRefusal) as got:
            attempt()
        text = got.value.diagnostics[0].message_ru
        assert "query_types" in text
        assert "СЛЕДУЮЩИЙ ХОД" in text
        assert "DEFAULT" in text and "КВИТАНЦИИ" in text, \
            "названа должна быть КАЖДАЯ честная форма, иначе совет — половина"


def test_a_handle_stays_truthy_so_the_fix_does_not_become_a_new_trap():
    """`if wall_types else None` слабая модель написала на ПЕРВОМ ходу (wB t01).

    Истинность без `__bool__` считалась бы через `__len__`, то есть отказом:
    починка одного класса завела бы новый. Ручка существует всегда — она
    адрес, а не результат.
    """
    assert bool(dsl.query_types(pool="wall_types")) is True
    assert bool(dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                                level="Этаж 1")) is True


def test_a_writing_handle_says_it_is_ONE_handle_not_a_list():
    """У пишущего опа причина другая, и отказ обязан говорить ЕГО причину, а не
    общую: ручка одна, список автор собирает питоном сам."""
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    with pytest.raises(dsl.DslRefusal) as got:
        wall[0]
    text = got.value.diagnostics[0].message_ru
    assert "ОДНУ ручку" in text
    assert "СЛЕДУЮЩИЙ ХОД" in text


def test_a_handle_in_a_nonref_slot_names_the_by_name_form_that_actually_works():
    """ЗАМЕР 04.08 (wB t05/t11): KIR-G002 был КОРРЕКТЕН, а совет вёл в яму —
    «слот принимает name», но имени в снимке ещё нет, его создаёт эта же пачка.

    Совет проверен планом, а не выведен: create_type(new_name=…) +
    create_wall(type=<то же имя>) компилируется (`plan_program` принял 3 опа).
    """
    made = dsl.create_type(category="architectural", new_name="Наружная 300",
                           source_type="Обобщённая - 200 мм", width_mm=300)
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1", type=made)
    text = got.value.diagnostics[0].message_ru
    assert "СЛЕДУЮЩИЙ ХОД" in text
    assert "create_type" in text and "new_name" in text, \
        "совет обязан назвать ОП и ПОЛЕ имени, а не жанр совета"


def test_a_handle_in_a_solo_ops_slot_names_the_BUNDLE_not_just_the_name():
    """У `create_stairs` ответ «сошлись по имени» неполон: оп СОЛО (KIR-L002),
    значит уровень физически не может лежать в этой же программе. Отказ обязан
    назвать ФОРМУ ПАЧКИ — иначе совет опять ведёт в яму, на ход позже."""
    level = dsl.create_level(elev_mm=0, name="Этаж 1")
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_stairs(p0_mm=[0, 0], p1_mm=[0, 4000], base_level=level,
                          top_level="Этаж 2")
    text = got.value.diagnostics[0].message_ru
    assert "ПАЧКА" in text
    assert "KIR-L002" in text
    assert "design_check" in text, "вердикт у пачки — часть следующего хода"


def test_the_early_refusal_matches_the_compilers_law_not_our_own():
    """Ранний отказ обязан ПОВТОРЯТЬ закон компилятора, а не заводить свой:
    та же программа, написанная руками со ссылкой на непереставляемый оп,
    обязана получить KIR-L003."""
    by_hand = {
        "ir_version": "1.0",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_curtain_grid_line", "id": "GL1",
             "host": {"by": "ref", "value": "W1"}, "direction": "u",
             "position_mm": [3000, 0, 0]},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "GL1"}, "offset_mm": 1000},
        ],
    }
    with pytest.raises(KirRefusal) as got:
        plan_program(by_hand)
    assert any(d.code == "KIR-L003" for d in got.value.diagnostics)


def test_an_unknown_parameter_fails_at_the_call_site_and_names_it():
    """Отказ приходит из СИГНАТУРЫ, то есть из реестра, и называет поле.

    ТИП ОТКАЗА СМЕНИЛСЯ ОСОЗНАННО (04.08): был голый питоновский `TypeError`
    от `Signature.bind`, стал типизированный `DslRefusal` с кодом KIR-P003.
    Причина — замер: 13 из 27 отказов слабой модели на живом задании были
    этим самым `TypeError`, и он называл ОДИН слот из шести, не говоря ни
    слова об остальных. Модель узнавала сигнатуру по одному биту за ход.
    """
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1",
                        heigth_mm=3000)                    # опечатка автора
    diagnostic = got.value.diagnostics[0]
    assert diagnostic.code == "KIR-P003"
    assert diagnostic.field_name == "heigth_mm"
    assert "heigth_mm" in str(got.value)
    assert dsl.ops() == [], "отказавший вызов не должен ничего оставить"


def test_a_missing_required_parameter_fails_at_the_call_site():
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0])
    diagnostic = got.value.diagnostics[0]
    assert diagnostic.code == "KIR-P005"
    assert diagnostic.field_name == "level"
    assert "level" in str(got.value)


def test_the_arity_refusal_names_the_WHOLE_call_form_not_one_slot():
    """ЗАМЕР 04.08, самый частый класс отказа поверхности (13 из 27).

    Слабая модель писала `create_stairs(..., width=, tread=, riser=)` и
    получала «unexpected keyword argument 'width'» — ОДНО имя за ход. Три
    лишних поля стоили бы трёх ходов. Отказ обязан закрывать их разом, поэтому
    тест требует: названы ВСЕ лишние слоты, перечислены ВСЕ слоты опа
    (обязательные и нет), и назван СЛЕДУЮЩИЙ ХОД — закон эталона KIR-L001.
    """
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_stairs(p0_mm=[0, 0], p1_mm=[0, 4000], base_level="Э1",
                          top_level="Э2", width=1200, tread=280, riser=170)
    text = str(got.value)
    for wrong in ("width", "tread", "riser"):
        assert wrong in text, f"{wrong} не назван — модель узнает о нём ходом позже"
    for slot in ("p0_mm", "p1_mm", "base_level", "top_level", "width_mm"):
        assert slot in text, f"{slot} не перечислен — форма вызова неполная"
    assert "СЛЕДУЮЩИЙ ХОД" in text
    assert dsl.ops() == []


@pytest.mark.parametrize("name", sorted(spec.OPS))
def test_every_op_refuses_a_bogus_slot_typed_and_with_a_next_move(name):
    """ПАРАМЕТРИЗАЦИЯ ПО РЕЕСТРУ: новый оп приносит свой тест сам.

    Прибор, покрывающий ЧАСТЬ диапазона, опаснее отсутствующего — этот пакет
    платил за это 03.08 (матрица спрашивала 3 версии Revit из 6). Поэтому закон
    «отказ типизирован и называет следующий ход» проверяется не на трёх опах, с
    которых начался замер, а на ВСЕХ, и форма вызова печатается для каждого:
    падение `_call_form` на редком опе означало бы отказ хуже исходного.
    """
    dsl.reset()
    with pytest.raises(dsl.DslRefusal) as got:
        getattr(dsl, name)(__nonexistent_slot__=1)
    text = str(got.value)
    assert got.value.diagnostics[0].code == "KIR-P003"
    assert name in text, "отказ обязан назвать ОП, иначе ремонт уйдёт не туда"
    assert "СЛЕДУЮЩИЙ ХОД" in text
    assert dsl.ops() == []


def test_the_missing_arity_refusal_shows_enum_choices_it_could_not_guess():
    """`create_railing(path=…, level=…)` -> «missing 'variety'». Само по себе
    это тупик: `variety` — enum, и его значений из отказа было не узнать.
    Теперь отказ печатает их вместе с формой."""
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_railing(path=[[0, 0, 0], [1000, 0, 0]], level="Э1")
    text = str(got.value)
    assert "variety" in text
    assert "path" in text and "hosted" in text, "значения enum не названы"
    assert "СЛЕДУЮЩИЙ ХОД" in text


def test_the_order_of_ops_is_preserved():
    """Порядок — часть программы: ссылка обязана указывать НАЗАД, и DAG
    компилятора считает именно по порядку."""
    for i in range(6):
        dsl.create_level(elev_mm=i * 3000, name=f"Э{i}")
    assert [o["name"] for o in dsl.ops()] == [f"Э{i}" for i in range(6)]
    assert [o["id"] for o in dsl.ops()] == [f"level{i}" for i in range(1, 7)]


def test_a_fresh_import_carries_no_state_of_the_previous_program():
    """ИЗОЛЯЦИЯ. Накопление модульное, поэтому «прошлый скрипт дописал мне
    стену» — не теория, а ровно то, чем модульное состояние опасно."""
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    assert len(dsl.ops()) == 1
    reloaded = importlib.reload(dsl)
    try:
        assert reloaded.ops() == []
        assert reloaded.current().intent is None
    finally:
        importlib.reload(dsl)


def test_the_bulk_budget_refuses_typed_and_names_the_next_work():
    """ПРЕДЕЛ v1 — внутренний bulk-бюджет. Отказ обязан назвать ИМЕННО его
    (иначе ремонт уходит не туда — замер 30.07) и сказать прямо, что
    чанкование прямого хода ещё не написано."""
    for _ in range(MAX_BULK_OPS):
        dsl.create_level(elev_mm=0)
    assert len(dsl.ops()) == MAX_BULK_OPS

    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_level(elev_mm=0)
    diag = got.value.diagnostics[0]
    assert diag.code == "KIR-L001"
    assert diag.got == MAX_BULK_OPS + 1
    assert BUDGET_INTERNAL_BULK in diag.message_ru
    assert "чанкование" in diag.message_ru
    assert "materialize" in diag.message_ru
    assert len(dsl.ops()) == MAX_BULK_OPS, "отказ не должен ничего дописать"


def test_the_budget_is_the_internal_one_and_the_authored_one_still_exists():
    """Два бюджета не сливаются в один. Программа из 21 опа проходит
    внутренним и отказывает авторским — и отказ называет, какой исчерпан."""
    for _ in range(MAX_OPS_PER_PROGRAM + 1):
        dsl.create_level(elev_mm=0)
    assert plan_program(dsl.build(), bulk=True) is not None
    with pytest.raises(KirRefusal) as got:
        plan_program(dsl.build(), bulk=False)
    assert any(d.code == "KIR-L001" for d in got.value.diagnostics)


# ════════════════════════════════════════ ПОВЕРХНОСТЬ РОЖДЕНА ИЗ РЕЕСТРА

@pytest.mark.parametrize("name", ALL_OPS)
def test_every_op_of_the_registry_has_a_function(name):
    fn = getattr(dsl, name, None)
    assert callable(fn), f"нет функции для {name}"
    assert fn.op_spec is spec.OPS[name], "функция держит ЧУЖУЮ спецификацию"


def test_there_are_exactly_as_many_functions_as_ops():
    assert set(dsl.OP_FUNCTIONS) == set(spec.OPS)
    assert dsl.op_names(writes=True) == sorted(
        n for n, o in spec.OPS.items() if o.writes_model)


@pytest.mark.parametrize("name", ALL_OPS)
def test_the_signature_never_drifts_from_the_paramspec(name):
    """Имена и обязательность — из `ParamSpec`, и только оттуда. Реестр
    перемежает обязательные и необязательные, а питон не разрешает параметру
    без умолчания стоять после параметра с умолчанием, поэтому сравнивается
    порядок ВНУТРИ каждой группы."""
    ospec = spec.OPS[name]
    sig = inspect.signature(getattr(dsl, name))
    got = [p for p in sig.parameters if p != "id"]
    want = ([p.name for p in ospec.params if p.required]
            + [p.name for p in ospec.params if not p.required])
    assert got == want
    assert "id" in sig.parameters, "у опа обязан быть адрес"


@pytest.mark.parametrize("name", ALL_OPS)
def test_registry_defaults_are_shown_in_the_signature(name):
    """Умолчание видно в `help`, хотя в JSON оно не вписывается: автор обязан
    ЗНАТЬ, что получит, не заглядывая в реестр."""
    sig = inspect.signature(getattr(dsl, name))
    for p in spec.OPS[name].params:
        if p.required or p.default is None:
            continue
        assert sig.parameters[p.name].default == p.default, p.name


def test_the_dsl_cannot_name_an_op_the_registry_does_not_have():
    assert not hasattr(dsl, "create_teleporter")


# ═══════════════════════════════════════════════════ ИНТРОСПЕКЦИЯ

def test_the_signature_carries_the_real_bounds_of_the_registry():
    """«Как модель узнаёт о том, чего не видит» — родным для питона способом.
    Границы берутся из `ParamSpec`, а не переписаны в текст."""
    text = str(inspect.signature(dsl.create_wall))
    assert "height_mm: mm 1..100000" in text
    assert "p0_mm: pt_xy" in text
    assert "level: sel: name|element_id|default|ref(level)" in text
    assert "enum{wall_centerline|" in text

    p = next(x for x in spec.OPS["create_wall"].params if x.name == "height_mm")
    assert f"{p.min_val:g}..{p.max_val:g}" in text


def test_a_write_target_slot_advertises_that_it_has_no_name_form():
    """`target_w` — пришпиленный id либо ссылка. Сигнатура обязана это
    ПОКАЗЫВАТЬ, иначе автор узнаёт о законе только из отказа."""
    text = str(inspect.signature(dsl.create_door))
    assert "host: target_w: element_id|ref(wall)" in text
    assert "name" not in text.split("host: target_w:")[1].split(",")[0]


@pytest.mark.parametrize("name", ALL_OPS)
def test_the_docstring_carries_the_post_of_the_op(name):
    """Постусловие — контракт опа. Оно обязано быть В ДОКСТРОКЕ дословно, а не
    пересказом: пересказ живёт до первой правки реестра."""
    doc = getattr(dsl, name).__doc__
    assert spec.OPS[name].post in doc


@pytest.mark.parametrize("name", ALL_OPS)
def test_the_return_annotation_states_referenceability_truthfully(name):
    ospec = spec.OPS[name]
    ret = str(inspect.signature(getattr(dsl, name)).return_annotation)
    if ospec.result.referenceable:
        assert f"ссылка «{ospec.result.reference_kind.value}»" in ret
    else:
        assert "НЕ ссылка" in ret


def test_the_docstring_carries_tolerances_and_grounding_pools():
    doc = dsl.create_wall.__doc__
    assert "endpoint_mm = 5" in doc            # из OpSpec.tolerances
    assert "пулу «levels»" in doc              # из OpSpec.grounded
    assert "wall_types" in doc


# ═══════════════════════════════════════════ РУЧКИ И ГРАФ ЗАВИСИМОСТЕЙ

def test_a_handle_wires_the_dag_by_construction():
    """Ссылка строится ПЕРЕДАЧЕЙ ручки, а не строкой id: граф корректен по
    построению, потому что передать можно только уже созданный оп."""
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    door = dsl.create_door(host=wall, offset_mm=3000)
    assert dsl.ops()[1]["host"] == {"by": "ref", "value": wall.id}
    assert door.reference_kind is spec.ReferenceKind.ELEMENT
    assert plan_program(dsl.build()) is not None


def test_auto_ids_are_deterministic_and_match_the_sdk_scheme():
    """Две питон-поверхности обязаны раздавать ОДНИ адреса, иначе «та же
    программа» перестаёт быть проверяемым сравнением."""
    for _ in range(3):
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[1000, 0], level="Этаж 1")
    assert [o["id"] for o in dsl.ops()] == ["wall1", "wall2", "wall3"]

    p = sdk.program()
    for _ in range(3):
        p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1"))
    assert [o["id"] for o in p.ops] == [o["id"] for o in dsl.ops()]


def test_an_explicit_id_is_never_overwritten_and_a_duplicate_is_refused():
    dsl.create_level(elev_mm=0, id="мой")
    assert dsl.ops()[0]["id"] == "мой"
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_level(elev_mm=3000, id="мой")
    assert got.value.diagnostics[0].code == "KIR-P006"


def test_the_id_is_the_second_key_so_the_program_reads_by_eye():
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    assert list(dsl.ops()[0])[:2] == ["op", "id"]


def test_the_fields_follow_the_registry_order_not_the_signature_order():
    """Сигнатура обязана ставить обязательные вперёд (питон), а JSON — нет.
    Программу читают глазами, и порядок полей в ней принадлежит реестру."""
    dsl.create_floor(outline=[[0, 0], [6000, 0], [6000, 4000]], level="Этаж 1",
                     holes=[[[1000, 1000], [2000, 1000], [2000, 2000]]],
                     structural=True)
    got = [k for k in dsl.ops()[0] if k not in ("op", "id")]
    want = [p.name for p in spec.OPS["create_floor"].params if p.name in got]
    assert got == want


# ══════════════════════════════════════════ ПРИВЕДЕНИЕ СЕЛЕКТОРОВ

def test_the_sugar_is_exactly_the_four_rules_and_nothing_more():
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=42)
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=dsl.DEFAULT)
    dsl.create_door(host=wall, offset_mm=1000)
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                    level={"by": "name", "value": "Этаж 1"})
    got = dsl.ops()
    assert got[0]["level"] == {"by": "name", "value": "Этаж 1"}
    assert got[1]["level"] == {"by": "element_id", "value": 42}
    assert got[2]["level"] == {"by": "default"}
    assert got[3]["host"] == {"by": "ref", "value": wall.id}
    assert got[4]["level"] == {"by": "name", "value": "Этаж 1"}


def test_an_omitted_selector_is_simply_absent():
    """«Пропуск -> правило опа по умолчанию» означает ОТСУТСТВИЕ ключа: лестницу
    разрешения ведёт `ground.py`, и вписанный `{"by":"default"}` — уже другое
    утверждение автора."""
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    assert "type" not in dsl.ops()[0]


def test_a_string_in_a_write_target_is_refused_and_the_forms_are_named():
    """У `target_w` формы `by=name` НЕ СУЩЕСТВУЕТ (`_target_w_ok`). Сахар,
    который не может быть однозначным, лучше не делать вовсе — но отказать он
    обязан ЗДЕСЬ и назвать, что слот принимает."""
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_door(host="Стена 1", offset_mm=1000)
    diag = got.value.diagnostics[0]
    assert diag.expected == ["element_id", "ref"]
    assert "by=name" in diag.message_ru
    assert any("element_id" in c for c in diag.candidates)


def test_a_bool_is_never_an_address():
    with pytest.raises(dsl.DslRefusal):
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=True)


def test_a_list_slot_is_coerced_element_by_element():
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    dsl.move_elements(targets=[42, wall], delta_mm=[100, 0, 0])
    assert dsl.ops()[1]["targets"] == [{"by": "element_id", "value": 42},
                                       {"by": "ref", "value": wall.id}]
    with pytest.raises(dsl.DslRefusal):
        dsl.move_elements(targets=42, delta_mm=[100, 0, 0])


def test_the_explicit_forms_stay_available_and_carry_disambiguate_by():
    """`disambiguate_by` — сужение, которое `ground.py` проверяет ДАЖЕ при
    единственном кандидате. До этого модуля из питона его нельзя было написать
    иначе как словарём руками."""
    dsl.create_pipe(p0_mm=[0, 0, 0], p1_mm=[3000, 0, 0], level="Этаж 1",
                    pipe_type=dsl.by_name(
                        "Стандарт",
                        disambiguate_by=dsl.disambiguate("Диаметр", 100)))
    assert dsl.ops()[0]["pipe_type"] == {
        "by": "name", "value": "Стандарт",
        "disambiguate_by": {"param": "Диаметр", "value": 100}}
    assert plan_program(dsl.build()) is not None

    assert dsl.by_element_id(7) == {"by": "element_id", "value": 7}
    assert dsl.by_default() == {"by": "default"}
    assert dsl.by_default(disambiguate_by=dsl.disambiguate("Ø", None)) == {
        "by": "default", "disambiguate_by": {"param": "Ø", "value": None}}


def test_family_type_is_available_and_its_legality_belongs_to_the_compiler():
    """Форма строится всегда; ГДЕ она законна — знает компилятор, и знает он
    один. DSL, отказавший бы здесь по-своему, стал бы вторым диалектом."""
    catalog = dsl.family_type("OST_Furniture", "Стол офисный", "Стол 1200")
    dsl.place_family(xyz=[0, 0, 0], level="Этаж 1", symbol=catalog)
    assert plan_program(dsl.build()) is not None

    dsl.reset()
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1",
                    type=catalog)
    with pytest.raises(KirRefusal) as got:
        plan_program(dsl.build())
    assert "family_type" in got.value.diagnostics[0].message_ru


@pytest.mark.parametrize("name", ALL_OPS)
def test_every_selector_slot_of_the_registry_has_named_forms(name):
    """Новый вид параметра-селектора обязан быть осознанно разложен по формам,
    а не проехать молча. Классификация «селектор или нет» берётся у `sdk` —
    она там уже под стражем."""
    ospec = spec.OPS[name]
    for p in ospec.params:
        if p.kind not in (sdk.SELECTOR_KINDS | sdk.SELECTOR_LIST_KINDS):
            continue
        forms = dsl.selector_forms(name, p.name)
        assert forms, f"{name}.{p.name}: формы не названы"
        assert ("ref" in forms) == bool(p.ref_kinds)


# ═══════════════════════════════ НИКАКОЙ СВОЕЙ СЕМАНТИКИ

@pytest.mark.parametrize("name", ALL_OPS)
def test_every_op_builds_json_the_planner_accepts(name):
    """39 опов, 39 программ, ни одной оговорки: всё, что DSL порождает,
    проходит `plan_program` — ЕДИНСТВЕННЫЙ семантический вход вниз."""
    dsl.reset(allow_destructive=True)          # delete требует явного согласия
    getattr(dsl, name)(**_args_for(spec.OPS[name]))
    planned = plan_program(dsl.build(), bulk=True)
    assert planned.ops[0].op_name == name


def test_a_knowingly_bad_program_reaches_the_compiler_untouched():
    """DSL не отказывает раньше и по-своему: заведомо неверное значение обязано
    дойти ДО компилятора и получить ЕГО диагностику."""
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1",
                    height_mm=-5)
    assert dsl.ops()[0]["height_mm"] == -5
    with pytest.raises(KirRefusal) as got:
        plan_program(dsl.build())
    assert got.value.diagnostics[0].code == "KIR-T002"


def test_an_unknown_envelope_default_is_the_compilers_refusal_not_ours():
    dsl.envelope(defaults={"nonsense": "x"})
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    with pytest.raises(KirRefusal) as got:
        plan_program(dsl.build())
    assert any(d.field_name == "defaults" for d in got.value.diagnostics)


# ═══════════════════════════════════════════════════════ ПРОВЕНАНС

def test_an_omitted_registry_default_keeps_its_provenance():
    """ЗАМЕР 03.08, из-за которого умолчание реестра НЕ вписывается в JSON.

    Вписанное умолчание и опущенное — разные программы для компилятора:
    у первой поле помечено EXPLICIT, у второй REGISTRY_DEFAULT, и `plan_digest`
    у них РАЗНЫЙ. Питон-фронт, вписывающий умолчания, тем самым стирает
    механизм провенанса (`midend.FieldOrigin`) и меняет личность
    доказательства, не изменив в здании ничего.
    """
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1", id="W1")
    assert "height_mm" not in dsl.ops()[0]
    omitted = plan_program(dsl.build())
    assert dict(omitted.ops[0].provenance.field_origins)["height_mm"] \
        is FieldOrigin.REGISTRY_DEFAULT

    dsl.reset()
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1", id="W1",
                    height_mm=spec.DEFAULTS["wall"]["height_mm"])
    explicit = plan_program(dsl.build())
    assert dict(explicit.ops[0].provenance.field_origins)["height_mm"] \
        is FieldOrigin.EXPLICIT
    assert omitted.plan_digest != explicit.plan_digest


# ══════════════════════════ ДВЕ ПИТОН-ПОВЕРХНОСТИ НЕ РАЗЪЕЗЖАЮТСЯ

def test_the_two_python_surfaces_name_the_same_registry():
    """`sdk.py` и `dsl.py` оба рождены из `spec.OPS`. Пока они оба живы, их
    расхождение — реальный риск, и он обязан валить сборку, а не всплывать у
    пользователя."""
    assert set(dsl.OP_FUNCTIONS) == set(sdk.builders())
    for name in ALL_OPS:
        a = [p for p in inspect.signature(getattr(dsl, name)).parameters]
        b = [p for p in inspect.signature(getattr(sdk, name)).parameters]
        assert a == b, f"{name}: питон-поверхности разъехались"


def test_the_shared_facts_are_shared_by_reference_not_by_copy():
    assert dsl.OMIT is sdk.OMIT
    assert dsl.DEFAULT is sdk.DEFAULT
    assert dsl._plain is sdk._plain
    assert dsl._SELECTOR_KINDS == sdk.SELECTOR_KINDS
    assert dsl._SELECTOR_LIST_KINDS == sdk.SELECTOR_LIST_KINDS
    assert sdk.unclassified_kinds() == [], "вид параметра без классификации"


def test_a_ref_made_by_the_sdk_is_understood_here():
    """Скрипт, смешавший два модуля, не должен ловить разные ссылки."""
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1", id="W1")
    dsl.create_door(host=sdk.Ref("W1"), offset_mm=3000)
    assert dsl.ops()[1]["host"] == {"by": "ref", "value": "W1"}


# ══════════════════════════════════════════════ КОНВЕРТ И ПРОГРАММА

def test_the_envelope_is_the_compilers_envelope_and_nothing_else():
    dsl.envelope(intent="проба", allow_destructive=True,
                 defaults={"level": "Этаж 1", "type": 100})
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    got = dsl.build()
    assert set(got) <= {"ir_version", "intent", "allow_destructive",
                        "defaults", "ops"}
    assert got["ir_version"] == spec.IR_VERSION
    assert got["defaults"] == {"level": {"by": "name", "value": "Этаж 1"},
                               "type": {"by": "element_id", "value": 100}}
    assert plan_program(got) is not None


def test_the_context_manager_isolates_and_restores():
    """Менеджер контекста доступен, но не обязателен: скрипт читается как
    скрипт, и всё же вложенную программу можно отделить явно."""
    dsl.create_level(elev_mm=0, name="снаружи")
    outer = dsl.current()
    with dsl.program(intent="внутри") as inner:
        dsl.create_level(elev_mm=3000, name="внутри")
        assert dsl.current() is inner
        assert len(inner.ops) == 1
    assert dsl.current() is outer
    assert len(outer.ops) == 1
    assert inner.build()["intent"] == "внутри"


def test_a_program_without_the_context_manager_is_the_default_path():
    """Пять строк питона и ничего больше — форма, ради которой всё затевалось."""
    dsl.envelope(intent="каре 6×4")
    corners = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
    walls = [dsl.create_wall(p0_mm=a, p1_mm=b, level="Этаж 1")
             for a, b in zip(corners, corners[1:] + corners[:1])]
    dsl.create_door(host=walls[0], offset_mm=3000, symbol="Дверь 900x2100")
    got = dsl.build()
    assert len(got["ops"]) == 5
    assert got["ops"][4]["host"] == {"by": "ref", "value": "wall1"}
    assert plan_program(got) is not None


def test_the_plan_helper_is_the_single_semantic_door_downwards():
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    planned = dsl.plan()
    assert planned.plan_digest == plan_program(dsl.build(), bulk=True).plan_digest
    assert planned.bulk is True


# ══════════════════════════════════════════ ДОГОВОР С ПЕСОЧНИЦЕЙ

def test_the_drain_hands_the_whole_envelope_and_leaves_nothing_behind():
    """Песочница опрашивает язык `take_ops()` ПЕРВЫМ и умеет конверт. Отдать
    один список опов значило бы молча потерять `intent`, выставленный
    скриптом; обнуление после выдачи — изоляция следующего скрипта."""
    dsl.envelope(intent="каре", allow_destructive=True)
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    got = dsl.take_ops()
    assert got["intent"] == "каре"
    assert got["allow_destructive"] is True
    assert len(got["ops"]) == 1
    assert dsl.ops() == [], "drain обязан обнулить"


def test_an_empty_drain_is_falsy_so_the_scripts_own_variable_still_wins():
    """У песочницы ДВА пути сбора: drain языка и переменная `ops` скрипта.
    Истинный ответ при нуле накопленного забрал бы второй путь себе."""
    assert dsl.take_ops() is None


def test_the_drain_is_not_injected_into_the_authors_namespace():
    """Песочница кладёт в пространство скрипта имена из `__all__`. Сливать
    свою же программу автору незачем — её забирает она."""
    assert "take_ops" not in dsl.__all__
    assert callable(dsl.take_ops)


def test_every_exported_name_is_injectable_into_a_script_namespace():
    """Песочница НИКОГДА не инжектирует модули (иначе `import os` в языке стал
    бы чёрным ходом). Экспортировать модуль здесь — значит молча потерять имя."""
    import types
    for name in dsl.__all__:
        assert hasattr(dsl, name), f"__all__ обещает несуществующее имя {name}"
        assert not isinstance(getattr(dsl, name), types.ModuleType), name
