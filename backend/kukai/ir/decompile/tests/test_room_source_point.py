"""Захват точки помещения приехал — подъём его не забрал.

За всю историю проекта (55 сохранённых разборов, 4 здания) у КАЖДОГО
помещения `p0_mm` был null: тот же член API, что убил чтение групп, стоил
точки и всем помещениям. 30.07 это починили, и башня впервые дала помещения
с точкой.

Подъём этого не заметил. `_lift_room` передавал `source_location_mm=None`
явно, с комментарием «L0 1.0 хранит только границы, не Room.Location» —
верным на момент написания и устаревшим в тот день, когда захват поехал. Шов
между захватом и подъёмом держался на КОММЕНТАРИИ, а не на контракте, и
поэтому разошёлся молча.

Цена не косметическая. Для невыпуклого помещения — Г-образного, коридора,
помещения с вырезом — центр, вычисленный по контуру, может лежать ВНЕ самого
помещения. Пересобранное помещение тогда попадает в соседнюю комнату или не
создаётся вовсе. На башне это дало 2153 расхождения из 2153 поднятых
помещений, с отклонениями до 5339 мм.

Тесты держат ОБЕ стороны правила, потому что «просто доверять захвату» —
тоже дефект: захваченная точка может оказаться вне контура (помещение
переобмерили, границы поехали), и тогда единственный честный ответ —
детерминированный запасной вариант, а не сломанная программа.
"""
from __future__ import annotations

import math
import unittest

from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
    RoomInfo,
)

_LEVEL = LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0)
_PROJ = ProjectInfo(name="Проект", address="адрес", building_type_hint=None)

#: Г-образное помещение. Центр габарита (5000, 5000) лежит В ВЫРЕЗЕ, то есть
#: снаружи; любой «центр», выведенный из габарита, указывает не туда.
_L_SHAPE = (
    (0.0, 0.0), (10000.0, 0.0), (10000.0, 3000.0),
    (3000.0, 3000.0), (3000.0, 10000.0), (0.0, 10000.0),
)

#: Точка, которую Revit реально держит у этого помещения: внутри нижней
#: полки, далеко от любого выведенного центра.
_CAPTURED = [8000.0, 1500.0, 0.0]


def _room(**kw) -> RoomInfo:
    base = dict(
        id="8001", name="Комн 101", level_id="100", level_name="Этаж 1",
        area_m2=51.0, boundary_mm=_L_SHAPE, boundary_loops_mm=(_L_SHAPE,),
        bounding_element_ids=())
    base.update(kw)
    return RoomInfo(**base)


def _room_element(p0: list[float] | None) -> L0Element:
    return L0Element(
        element_id="8001", category="OST_Rooms", category_ru="Помещения",
        type_id="7001", type_name="Помещение", level_id="100", level_name="Этаж 1",
        geom_kind=GeometryKind.POINT if p0 else GeometryKind.BBOX_ONLY,
        p0_mm=p0, p1_mm=None, rotation_deg=None,
        bbox_min_mm=[0.0, 0.0, 0.0], bbox_max_mm=[10000.0, 10000.0, 3000.0],
        host_id=None, params={})


def _document(p0: list[float] | None) -> L0Document:
    return L0Document(
        doc_name="проба", revit_version="2023", units="mm",
        change_stamp="room-point-test", levels=(_LEVEL,), grids=(),
        rooms=(_room(),), project_info=_PROJ,
        elements=(_room_element(p0),))


def _lift_xy(p0: list[float] | None) -> tuple[float, float]:
    ops = [n for n in lift_document(_document(p0))
           if n["kind"] == "op" and n["op_name"] == "create_room"]
    assert len(ops) == 1, f"ожидался ровно один create_room, получено {ops!r}"
    xy = ops[0]["params"]["xy"]
    return (float(xy[0]), float(xy[1]))


class RoomSourcePointTests(unittest.TestCase):

    def test_a_captured_room_point_is_used_verbatim(self) -> None:
        """ОПРОВЕРГАЮЩИЙ ТЕСТ: точка из модели обязана доехать до операции.

        До починки подъём вычислял свою точку и захваченную не смотрел вовсе,
        поэтому здесь стояло расхождение в тысячи миллиметров — ровно то, что
        верификатор доложил 2153 раза подряд и что никто не прочитал, потому
        что смотрели на покрытие.
        """
        xy = _lift_xy(_CAPTURED)
        self.assertAlmostEqual(xy[0], _CAPTURED[0], delta=0.5)
        self.assertAlmostEqual(xy[1], _CAPTURED[1], delta=0.5)

    def test_without_a_captured_point_the_fallback_stays_inside(self) -> None:
        """Старое поведение остаётся ЗАКОННЫМ там, где точки нет.

        Слепки, снятые до 30.07, точки не несут, и их подъём обязан работать
        по-прежнему — но выведенная точка обязана лежать ВНУТРИ помещения, а
        не в вырезе Г-образного контура.
        """
        x, y = _lift_xy(None)
        self.assertFalse(
            3000.0 < x and 3000.0 < y,
            f"выведенная точка ({x}, {y}) попала в вырез, то есть вне помещения")

    def test_a_captured_point_outside_the_room_is_not_trusted(self) -> None:
        """Обратная сторона: захват тоже может врать.

        Если точка вне контура (границы переобмерили, слепок постарел),
        честный ответ — детерминированный запасной вариант, а не программа,
        которая создаст помещение в соседней комнате.
        """
        x, y = _lift_xy([9000.0, 9000.0, 0.0])      # в вырезе, снаружи
        self.assertFalse(
            math.isclose(x, 9000.0, abs_tol=1.0)
            and math.isclose(y, 9000.0, abs_tol=1.0),
            "точка вне помещения принята как есть — подъём доверяет захвату "
            "слепо, и пересобранное помещение уедет в чужое пространство")

    def test_the_point_that_lands_in_the_op_also_lands_in_the_anchor(self) -> None:
        """Якорь и параметр обязаны говорить одно и то же.

        Верификатор сравнивает предсказанные точки с прочитанными, а
        предсказание берёт из `xy`, если оно есть, и из `anchor_mm`, если нет.
        Разъедься эти двое — и вердикт начнёт зависеть от того, какую ветку
        выбрал читатель, а не от того, что построено.
        """
        node = [n for n in lift_document(_document(_CAPTURED))
                if n["kind"] == "op" and n["op_name"] == "create_room"][0]
        xy = node["params"]["xy"]
        anchor = node["anchor_mm"]
        self.assertAlmostEqual(float(anchor[0]), float(xy[0]), delta=0.5)
        self.assertAlmostEqual(float(anchor[1]), float(xy[1]), delta=0.5)


if __name__ == "__main__":
    unittest.main()
