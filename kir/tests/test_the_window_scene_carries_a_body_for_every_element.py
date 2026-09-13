"""СЦЕНА ОКНА НЕСЁТ ТЕЛО КАЖДОМУ ЭЛЕМЕНТУ ПРОГРАММЫ, А НЕ ОСЬ.

🔴 ЧЕМ КУПЛЕНО (13.09.2026, слово владельца о выкаченном окне): «не понимаю
зачем мне план этажа который нельзя посмотреть и повертеть в 3д». Окно
показывало лист, а сцена — даже если бы её показали — была БЕЗ ТЕЛ: замер
`W-preview/tools/bodies_probe.py` дал НОЛЬ тел из шести на программе
«коробка», и все причины названы поимённо в `W-preview/BODIES_CONTRACT.md`.

ЧТО ЗДЕСЬ СТЕРЕЖЁТСЯ. Не правила тела (они в `clash_bundle`, надел N), а ШОВ
ОКНА: что сцена, собранная тем же вызовом, что зовёт прод
(`live_scene.scene_from_programs`), доносит до рамки ТЕЛО каждого элемента —
и что число тел равно числу строящих операций. Один недостающий род тела
превращает здание в набор осей молча: сцена приходит, элементы в ней есть, а
крыши нет.

ЧТО ЭТОТ ПИН НЕ ДОКАЗЫВАЕТ. Он не доказывает, что `create_door` умеет тело —
НЕ УМЕЕТ (`create_door_geometry_not_expressed`, §1.4 заявки). Дверь здесь
выражена `create_directshape`, и это сказано вслух, а не спрятано: пин мерит
окно, а не притворяется, что чужая работа сделана.
"""
from __future__ import annotations

import json
import struct

from kir.viewer.codec import SCENE_MAGIC
from kir.viewer.live_scene import scene_from_programs

Ш, Г, В, Т = 4000.0, 3000.0, 3000.0, 200.0
УГЛЫ = [[0.0, 0.0], [Ш, 0.0], [Ш, Г], [0.0, Г]]

СНИМОК = {
    "levels": [{"id": 101, "name": "Уровень 1", "elevation_mm": 0.0}],
    "wall_types": [{"id": 201, "name": "Стена 200",
                    "section": {"kind": "plate", "thickness_mm": Т,
                                "uniform": True, "source": "снимок"}}],
    "floor_types": [{"id": 202, "name": "Перекрытие 200",
                     "section": {"kind": "plate", "thickness_mm": Т,
                                 "uniform": True, "source": "снимок"}}],
    "roof_types": [{"id": 203, "name": "Кровля 100",
                    "section": {"kind": "plate", "thickness_mm": 100.0,
                                "uniform": True, "source": "снимок"}}],
}


def коробка() -> list[dict]:
    ops: list[dict] = [
        {"op": "create_level", "id": "L1", "name": "Уровень 1", "elev_mm": 0}]
    for i in range(4):
        ops.append({"op": "create_wall", "id": f"w{i}",
                    "p0_mm": УГЛЫ[i], "p1_mm": УГЛЫ[(i + 1) % 4],
                    "height_mm": В,
                    "level": {"by": "name", "value": "Уровень 1"},
                    "type": {"by": "name", "value": "Стена 200"}})
    ops.append({"op": "create_floor_by_contour", "id": "f0",
                "level": {"by": "name", "value": "Уровень 1"},
                "type": {"by": "name", "value": "Перекрытие 200"},
                "contour": {"outer": {"shape": "poly", "points_mm": УГЛЫ}}})
    ops.append({"op": "create_extrusion_roof", "id": "r0",
                "level": {"by": "name", "value": "Уровень 1"},
                "type": {"by": "name", "value": "Кровля 100"},
                "p0_mm": [0.0, 0.0], "p1_mm": [Ш, 0.0],
                "profile_mm": [[0.0, В], [Ш / 2, В + 900.0], [Ш, В]],
                "start_mm": 0.0, "end_mm": Г})
    ops.append({"op": "create_directshape", "id": "d0",
                "category": "generic_model",
                "level": {"by": "name", "value": "Уровень 1"},
                "mesh": {"vertices_mm": [[1500.0, -Т / 2, 0.0], [2400.0, -Т / 2, 0.0],
                                         [2400.0, Т / 2, 0.0], [1500.0, Т / 2, 0.0],
                                         [1500.0, -Т / 2, 2100.0], [2400.0, -Т / 2, 2100.0],
                                         [2400.0, Т / 2, 2100.0], [1500.0, Т / 2, 2100.0]],
                         "triangles": [[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
                                       [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
                                       [1, 2, 6], [1, 6, 5], [3, 0, 4], [3, 4, 7]]}})
    return ops


def _header(blob: bytes) -> dict:
    n = len(SCENE_MAGIC)
    assert blob[:n] == SCENE_MAGIC, "это не сцена KIR"
    length = struct.unpack("<I", blob[n:n + 4])[0]
    return json.loads(blob[n + 4:n + 4 + length].decode("utf-8"))


def test_every_building_op_of_the_box_arrives_as_a_body():
    ops = коробка()
    строящих = [op for op in ops if op["op"] != "create_level"]
    assert len(строящих) == 7, "контроль негоден: в коробке не семь предметов"

    blob, _ = scene_from_programs([{"ops": ops}], doc_key="коробка",
                                  snapshot=СНИМОК)
    header = _header(blob)

    assert header["elements"] == 7, (
        f"сцена несёт {header['elements']} тел вместо семи — часть здания "
        f"придёт осью: {header.get('counts')}")
    counts = header["counts"]
    тел = counts["box"] + counts["capsule"] + counts["prism"] + counts["mesh"]
    assert тел == 7, f"родов тел меньше, чем элементов: {counts}"
    # Роды здания названы: стена, перекрытие и кровля обязаны доехать
    # каждая своим родом, иначе «семь тел» могли бы оказаться семью стенами.
    assert set(header["categories"]) >= {"OST_Walls", "OST_Floors", "OST_Roofs"}, (
        f"в сцене нет одного из родов коробки: {header['categories']}")


def test_without_a_type_snapshot_the_same_box_loses_its_bodies():
    """КОНТРОЛЬ: без снимка типов тел нет — значит пин выше меряет снимок,
    а не сам факт существования сцены.

    Это же и есть §1.1 заявки: сечение типа обязано быть разрешено ДО кадра.
    """
    blob, _ = scene_from_programs([{"ops": коробка()}], doc_key="коробка",
                                  snapshot=None)
    header = _header(blob)
    assert header["elements"] < 7, (
        "без снимка типов сцена всё равно полна — тогда пин выше ничего не "
        f"доказывает: {header['elements']}")
