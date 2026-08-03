# -*- coding: utf-8 -*-
"""ОПРОВЕРГАЮЩИЙ ТЕСТ: дуговая стена не переживает раунд-трип канона.

Повод — пересборка №11 (v18): create_wall expected 2346 / missing 244.
239 из 244 объясняются отказными чанками (238 — чанк 9, 1 — solo-чанк 12).
Оставшиеся ПЯТЬ построены живьём и не сошлись в каноне; они же числятся
`extra_rebuilt`. Все пять — ДУГОВЫЕ, из четырёх разных committed-чанков,
четырёх типов и четырёх уровней, то есть это не свойство одного элемента.

Дефектов ровно два, оба воспроизводятся на синтетике без Revit:

  A. ВЕТВЬ 2π. `_FIDELITY_RADIAN_FIELDS` квантуются на сетке 1e-6, но не
     приводятся по модулю 2π. У `rotation_deg` такое приведение есть
     (`_canonical_rotation`, «360°≡0°»), у радиан — нет. Живьём: ожидалось
     start=3.4732052114687098, получено -2.8099800957108703; разница ровно
     1.0×2π. Та же дуга — другой хеш. Затронуто 4 из 5.

  B. ХРАНИМЫЙ КОНЕЦ ПРОТИВ СВОЕЙ ЖЕ ДУГИ. В исходном листе `p0_mm`/`p1_mm`
     расходятся с точкой, вычисленной из `arc` того же листа, на 0.37-0.94 мм.
     Пересобранная стена строится ИЗ дуги, и её концы совпадают с дугой в
     0.0000 мм — измерено по всем пяти. Канон сравнивает избыточную
     несогласованную копию и ловит переход через сетку CANON_MM=1.
     Затронуто 2 из 5.

Фикс принят лидом 29.07 (fidelity-canon/4): оба дефектных теста переведены
из `expectedFailure` в обычные — теперь они охраняют закрытую дыру.
"""
from __future__ import annotations

import copy
import math
import unittest

from kukai.ir.decompile.fold import FidelityCanon

ORIGIN = (0.0, 0.0, 0.0)

# Дуга живой стены 8146232 (v18), ДОСЛОВНО из idempotence_debug.json,
# сокращённая до полей, участвующих в каноне.
ARC_WALL = {
    "kind": "op",
    "_id": "arcwall",
    "op_name": "create_wall",
    "level_name": "L_02.1Кровля ДОО_+10.460",
    "params": {
        "arc": {
            "center_mm": [1503010.0, 24214.0, 9700.0],
            "curve_type": "Arc",
            "radius_mm": 3819.999999999997,
            "start_angle_rad": 3.4732052114687098,
            "end_angle_rad": 4.712388980384677,
            "x_axis": [0.9455185755993463, 0.3255681544570712, 0.0],
            "y_axis": [0.3255681544570712, -0.9455185755993463, 0.0],
        },
        "p0_mm": [1499190.0, 24214.0],
        "p1_mm": [1501766.0, 27825.0],
        "height_mm": 550.0000000000006,
        "base_offset_mm": 520.0,
        "level": {"by": "name", "value": "L_02.1Кровля ДОО_+10.460",
                  "_id": "7476592"},
        "type": {"by": "name", "value": "НР_НВФ", "_id": "8146075"},
    },
}
TWO_PI = 2.0 * math.pi


def arc_point(arc: dict, angle: float) -> list[float]:
    """Точка дуги по её собственным параметрам."""
    c, xa, ya, r = (arc["center_mm"], arc["x_axis"],
                    arc["y_axis"], arc["radius_mm"])
    return [c[0] + r * (math.cos(angle) * xa[0] + math.sin(angle) * ya[0]),
            c[1] + r * (math.cos(angle) * xa[1] + math.sin(angle) * ya[1])]


def shifted_branch(leaf: dict, turns: int = -1) -> dict:
    """Тот же лист, чьи углы записаны в другой ветви 2π.

    Развёртка (end-start) сохраняется бит-в-бит: сдвигаются ОБА угла на одно
    и то же кратное. Геометрически это ТА ЖЕ дуга — так её и возвращает
    atan2 при обратном чтении из Revit.
    """
    out = copy.deepcopy(leaf)
    arc = out["params"]["arc"]
    arc["start_angle_rad"] += turns * TWO_PI
    arc["end_angle_rad"] += turns * TWO_PI
    return out


def endpoints_from_arc(leaf: dict) -> dict:
    """Тот же лист, чьи p0/p1 согласованы с его же дугой (как строит Revit)."""
    out = copy.deepcopy(leaf)
    arc = out["params"]["arc"]
    out["params"]["p0_mm"] = arc_point(arc, arc["start_angle_rad"])
    out["params"]["p1_mm"] = arc_point(arc, arc["end_angle_rad"])
    return out


class ArcCanonRoundTrip(unittest.TestCase):

    def test_shifted_branch_is_the_same_arc(self):
        """Предпосылка: сдвиг на 2π не меняет ни развёртку, ни точки."""
        moved = shifted_branch(ARC_WALL)
        a, b = ARC_WALL["params"]["arc"], moved["params"]["arc"]
        self.assertAlmostEqual(b["end_angle_rad"] - b["start_angle_rad"],
                               a["end_angle_rad"] - a["start_angle_rad"],
                               places=12)
        for angle_key in ("start_angle_rad", "end_angle_rad"):
            self.assertLess(
                math.dist(arc_point(a, a[angle_key]),
                          arc_point(b, b[angle_key])), 1e-6)

    def test_stored_endpoints_disagree_with_their_own_arc(self):
        """Предпосылка дефекта B: расхождение реально и субмиллиметровое.

        Это НЕ придирка канона — это противоречие внутри самого листа.
        """
        arc = ARC_WALL["params"]["arc"]
        drift = max(
            math.dist(arc_point(arc, arc["start_angle_rad"]),
                      ARC_WALL["params"]["p0_mm"]),
            math.dist(arc_point(arc, arc["end_angle_rad"]),
                      ARC_WALL["params"]["p1_mm"]))
        self.assertGreater(drift, 0.3)
        self.assertLess(drift, 1.0)

    def test_A_canon_collapses_the_2pi_branch(self):
        """ДЕФЕКТ A. Одна дуга в двух ветвях 2π обязана дать ОДИН канон."""
        self.assertEqual(
            FidelityCanon.hash(ARC_WALL, ORIGIN),
            FidelityCanon.hash(shifted_branch(ARC_WALL), ORIGIN))

    def test_B_canon_reads_endpoints_from_the_arc(self):
        """ДЕФЕКТ B. Лист и его же дуга-источник обязаны дать ОДИН канон.

        Слева — как хранит декомпиляция, справа — как построит Revit.
        Расхождение 0.37-0.94 мм переходит сетку CANON_MM=1 и разводит хеши.
        """
        self.assertEqual(
            FidelityCanon.hash(ARC_WALL, ORIGIN),
            FidelityCanon.hash(endpoints_from_arc(ARC_WALL), ORIGIN))


if __name__ == "__main__":
    unittest.main()
