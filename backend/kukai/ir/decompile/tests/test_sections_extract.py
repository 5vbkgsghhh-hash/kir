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


@pytest.mark.parametrize("param", SECTION_PARAMS)
def test_the_emission_asks_for_every_section_parameter(param):
    cs = build_category_batch_cs("OST_Walls")
    assert f"BuiltInParameter.{param}" in cs, param
    assert f'"{param}"' in cs, f"{param}: имя в params не совпадает с BIP"


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
