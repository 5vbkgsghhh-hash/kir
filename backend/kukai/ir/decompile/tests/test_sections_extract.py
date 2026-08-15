"""Сечения в извлечении: без них клеш-детектор строит только габаритные боксы.

Замер D1 на фасаде SOB6.2 (v10): 2754 оболочки, из них exact — НОЛЬ, потому что
ни толщины стены, ни диаметра трубы в артефактах декомпайла не было. Труба и
воздуховод собирались уже давно; не хватало толщины стены — и она живёт не на
стене, а на её ТИПЕ.

Имена сверены по RevitAPI.xml (`/root/27B/sdk/nuget_extracted/ref/net8.0/`), а
не по памяти: перечисление несёт `WALL_ATTR_WIDTH_PARAM`, а члена
`WALL_ATTR_WIDTH` (как его называют по привычке) в API НЕТ ВООБЩЕ — эмиссия с
ним не собралась бы ни на одной версии.

Живьём НЕ ПРОВЕРЕНО: замер ждёт пересборки v12.
"""
from __future__ import annotations

import re

import pytest

from kukai.ir.decompile.extract import build_category_batch_cs

#: Сечения, которые обязаны собираться. Ключ — имя в `params` строки L0.
SECTION_PARAMS = (
    "WALL_ATTR_WIDTH_PARAM",
    "RBS_PIPE_DIAMETER_PARAM",
    "RBS_CURVE_DIAMETER_PARAM",
    "RBS_CURVE_WIDTH_PARAM",
    "RBS_CURVE_HEIGHT_PARAM",
    "RBS_CABLETRAY_WIDTH_PARAM",
    "RBS_CABLETRAY_HEIGHT_PARAM",
    "RBS_CONDUIT_DIAMETER_PARAM",
    "STRUCTURAL_SECTION_COMMON_WIDTH",
    "STRUCTURAL_SECTION_COMMON_HEIGHT",
    "STRUCTURAL_SECTION_COMMON_DIAMETER",
)


#: Один вызов сечения: член перечисления и ЯРЛЫК, под которым число ляжет
#: в `params`. Оба захватываются отдельно — именно их равенство и есть
#: предмет проверки.
_SECTION_CALL = re.compile(
    r"__PutSectionParam\(\s*__e,\s*BuiltInParameter\.(\w+)\s*,\s*"
    r"nameof\(BuiltInParameter\.(\w+)\)\s*,\s*__params\s*\)\s*;")


def section_calls(cs: str) -> list[tuple[str, str]]:
    """Пары (член, ярлык) по всем вызовам сечений в эмиссии."""
    return [(m.group(1), m.group(2)) for m in _SECTION_CALL.finditer(cs)]


@pytest.mark.parametrize("param", SECTION_PARAMS)
def test_the_emission_asks_for_every_section_parameter(param):
    cs = build_category_batch_cs("OST_Walls")
    assert f"BuiltInParameter.{param}" in cs, param
    assert (param, param) in section_calls(cs), (
        f"{param}: нет вызова, где член и ярлык — ОДИН И ТОТ ЖЕ")


def test_no_section_call_labels_a_member_with_another_members_name():
    """ЧТО ЗДЕСЬ ТЕПЕРЬ ПРОВЕРЯЕТСЯ, И ЧТО СТАЛО НЕВОЗМОЖНЫМ (12.08.2026).

    До правки `nameof` ярлык был ЛИТЕРАЛОМ в кавычках, и тест искал
    написание: `assert f'"{param}"' in cs`. Литерал мог разойтись с членом
    молча — 38 таких пар и были предметом проверки.

    `nameof(BuiltInParameter.X)` берёт имя У КОМПИЛЯТОРА C#: опечатка в
    ярлыке больше не компилируется, а переименование члена едет вместе с
    ним. **Расхождение «ярлык написан не так» стало НЕВОЗМОЖНЫМ.** Прежний
    тест доложил это усиление как пропажу — прибор был привязан к
    НАПИСАНИЮ и не отличает усиление от ослабления.

    Но одна дыра `nameof` НЕ закрывает, и держится она здесь: ничто в
    языке не мешает написать `__PutSectionParam(__e, BuiltInParameter.A,
    nameof(BuiltInParameter.B), ...)` — оба аргумента законны, C#
    соберётся, а число ляжет в `params` под ЧУЖИМ именем. Проверка
    закрыта по ВСЕМ вызовам эмиссии, а не только по одиннадцати из
    SECTION_PARAMS: у остальных (например RBS_PIPE_OUTER_DIAMETER) та же
    возможность.

    НЕ «упрощать» обратно на литерал: литерал снимет гарантию `nameof`,
    выглядя починкой теста.
    """
    calls = section_calls(build_category_batch_cs("OST_Walls"))
    assert calls, "вызовов сечений не найдено — регулярка разошлась с эмиссией"
    mismatched = [(bip, label) for bip, label in calls if bip != label]
    assert not mismatched, (
        f"член и ярлык названы РАЗНЫМИ параметрами: {mismatched}")


def test_the_mismatch_check_is_a_check_and_not_an_ornament():
    """Контроль-FAIL и контроль-PASS у проверки выше.

    Без этой пары `section_calls`, разучившийся разбирать вызов, вернул бы
    пустой список — и проверка «расхождений нет» стала бы вакуумно-зелёной,
    выглядя ровно как обычная работа.
    """
    good = ("__PutSectionParam(__e, BuiltInParameter.WALL_ATTR_WIDTH_PARAM,\n"
            "                 nameof(BuiltInParameter.WALL_ATTR_WIDTH_PARAM), __params);")
    bad = ("__PutSectionParam(__e, BuiltInParameter.WALL_ATTR_WIDTH_PARAM,\n"
           "                 nameof(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM), __params);")
    # control-PASS: одинаковые имена читаются как пара и признаются равными
    assert section_calls(good) == [
        ("WALL_ATTR_WIDTH_PARAM", "WALL_ATTR_WIDTH_PARAM")]
    # control-FAIL: член и ярлык от РАЗНЫХ параметров обязаны быть видны
    parsed = section_calls(bad)
    assert parsed == [("WALL_ATTR_WIDTH_PARAM", "RBS_PIPE_DIAMETER_PARAM")]
    assert [p for p in parsed if p[0] != p[1]], (
        "подменённый ярлык не отличён от верного — проверка стала украшением")


def test_the_wall_width_parameter_is_the_one_that_exists_in_the_api():
    """`WALL_ATTR_WIDTH` — имя, которого в перечислении нет. Тест держит
    границу между привычкой и API: с неверным членом C# не собрался бы."""
    cs = build_category_batch_cs("OST_Walls")
    assert "BuiltInParameter.WALL_ATTR_WIDTH_PARAM" in cs
    assert "BuiltInParameter.WALL_ATTR_WIDTH," not in cs


def test_sections_are_read_through_the_type_falling_back_helper():
    """Толщина живёт на WallType, диаметр — на типе трубы. Читать их прямо с
    экземпляра значит не прочитать вовсе, поэтому все сечения идут через
    помощник, который сам падает на тип.

    Волна D2-A перевела сечения с молчаливого `__PutLengthParam` на
    `__PutSectionParam` (ревью кодекса №12): падение на тип осталось, но теперь
    у каждого исхода есть квитанция. Проверка нового помощника —
    `test_sections_receipts.py`; здесь держится только падение на тип.
    """
    cs = build_category_batch_cs("OST_Walls")
    assert "var __type = doc.GetElement(__e.GetTypeId());" in cs
    for param in SECTION_PARAMS:
        assert f"__PutSectionParam(__e, BuiltInParameter.{param}" in cs


def test_a_missing_parameter_is_absence_not_failure():
    """Fail-open: `__PutLengthParam` кладёт число, только если параметр есть.
    Элемент без сечения обязан дать запись БЕЗ числа, а не уронить извлечение —
    иначе первая же семейная стена без параметра остановит декомпайл."""
    cs = build_category_batch_cs("OST_Walls")
    assert "try" in cs and "catch { }" in cs
    assert "if (__p != null && __p.HasValue) return __p;" in cs


@pytest.mark.parametrize("category", ["OST_Walls", "OST_PipeCurves",
                                      "OST_DuctCurves", "OST_CableTray",
                                      "OST_StructuralColumns"])
def test_every_section_bearing_category_gets_the_same_block(category):
    """Блок общий для всех категорий: сечение спрашивается у каждой, а
    отсутствие — это факт о конкретном элементе, а не о категории."""
    cs = build_category_batch_cs(category)
    assert "BuiltInParameter.WALL_ATTR_WIDTH_PARAM" in cs
    assert "BuiltInParameter.RBS_PIPE_DIAMETER_PARAM" in cs
