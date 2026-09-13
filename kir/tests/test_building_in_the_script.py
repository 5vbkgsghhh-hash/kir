"""THE BUILDING IN THE SCRIPT'S HANDS: three outcomes, and none of them stays
silent.

This file's instrument is a REAL sandbox and a REAL index, not a
hand-assembled form. A test that constructs its own input guards the
fixture, not the path: this is exactly how the build-digest test used to stay
green today, while prod put it one level deeper and lost it. That is why
everything here uses `sandbox.execute_author_script` and
`building_index.build_index`.
"""
from __future__ import annotations

import unittest

from kir import building_index as bi
from kir import sandbox


class _El:
    """A minimal double of `L0Element` — exactly the fields the index reads."""

    def __init__(self, eid, cat="OST_Walls", lvl="L1", tname="Кирпич 200мм",
                 p0=(0, 0, 0), p1=(1000, 0, 0), params=None, host=None):
        self.element_id = eid
        self.category = cat
        self.level_name = lvl
        self.type_name = tname
        self.p0_mm = p0
        self.p1_mm = p1
        self.bbox_min_mm = p0
        self.bbox_max_mm = p1
        self.host_id = host
        self.params = params or {}


def _run(source: str, building=None):
    return sandbox.execute_author_script(source, building=building)


class ТриИсходаРазличимы(unittest.TestCase):
    """Empty · not looked at · not supplied — three DIFFERENT answers to one
    question."""

    def test_полный_индекс_отдаёт_пустоту_как_факт_о_здании(self):
        idx = bi.build_index([_El("1"), _El("2")])
        self.assertEqual(idx["tier"], bi.TIER_FULL)
        out = _run("print('НАЙДЕНО', building.found(cat='Doors'))\n"
                   "create_wall(p0_mm=[0,0], p1_mm=[1,0], level='L1')", idx)
        self.assertTrue(out.ok, out.refusal and out.refusal.render())
        self.assertIn("НАЙДЕНО 0", out.stdout)

    def test_перепись_ОТКАЗЫВАЕТ_а_не_отдаёт_пустоту(self):
        """FORM CONTROL 18: an empty response here would be green without
        differentiation."""
        idx = bi.build_index([_El(str(i)) for i in range(50)], ceiling_bytes=200)
        self.assertEqual(idx["tier"], bi.TIER_CENSUS)
        out = _run("building.find(cat='Walls')", idx)
        self.assertFalse(out.ok)
        text = out.refusal.render()
        self.assertIn("не поместилось", text)
        self.assertIn("50", text, "отказ обязан называть ЧИСЛО элементов")

    def test_перепись_всё_равно_отвечает_чем_богато_здание(self):
        """Not fitting does not mean "nothing is known about the building"."""
        idx = bi.build_index([_El(str(i)) for i in range(50)], ceiling_bytes=200)
        out = _run("print('ВСЕГО', building.total())\n"
                   "print('ТОП', building.top(1))\n"
                   "create_wall(p0_mm=[0,0], p1_mm=[1,0], level='L1')", idx)
        self.assertTrue(out.ok, out.refusal and out.refusal.render())
        self.assertIn("ВСЕГО 50", out.stdout)
        self.assertIn("OST_Walls", out.stdout)

    def test_индекса_нет_вовсе_это_факт_о_НАС(self):
        out = _run("building.find(cat='Walls')")
        self.assertFalse(out.ok)
        self.assertIn("не подан", out.refusal.render())


class ПоискНеЛжётОбУсечении(unittest.TestCase):

    def test_счёт_не_ограничен_потолком_ответа(self):
        """A truncated list without a full count would read as the entire
        result."""
        idx = bi.build_index([_El(str(i)) for i in range(40)])
        out = _run("print('СПИСОК', len(building.find(cat='Walls', limit=5)))\n"
                   "print('СЧЁТ', building.found(cat='Walls'))\n"
                   "create_wall(p0_mm=[0,0], p1_mm=[1,0], level='L1')", idx)
        self.assertTrue(out.ok, out.refusal and out.refusal.render())
        self.assertIn("СПИСОК 5", out.stdout)
        self.assertIn("СЧЁТ 40", out.stdout)

    def test_неизвестный_адрес_ОТКАЗ_а_не_None(self):
        idx = bi.build_index([_El("7")])
        out = _run("building.get('НЕТ-ТАКОГО')", idx)
        self.assertFalse(out.ok)
        self.assertIn("НЕТ-ТАКОГО", out.refusal.render())


class ПорядокРешаетсяТамГдеЧитается(unittest.TestCase):
    """CONTROL for a defect found during construction: the frame is
    serialized with `sort_keys=True`, and any ordering declared in the index
    is lost."""

    def test_топ_идёт_по_величине_а_не_по_алфавиту(self):
        els = ([_El(str(i), cat="OST_Walls") for i in range(9)]
               + [_El("a1", cat="OST_CableTray")])
        idx = bi.build_index(els)
        out = _run("print('ТОП', building.top(1))\n"
                   "create_wall(p0_mm=[0,0], p1_mm=[1,0], level='L1')", idx)
        self.assertTrue(out.ok, out.refusal and out.refusal.render())
        self.assertIn("OST_Walls", out.stdout)
        self.assertNotIn("CableTray", out.stdout,
                         "порядок съехал на алфавитный — дефект вернулся")


class ОднаВеличинаОдноПредставление(unittest.TestCase):
    """CONTROL for the second defect found during construction: the row
    carried `None`, the census `"?"`, and `levels()` returned a level that
    `find` could not find."""

    def test_уровень_из_переписи_находится_поиском(self):
        idx = bi.build_index([_El("1", lvl=None)])
        out = _run("L = building.levels()[0]\n"
                   "print('УРОВЕНЬ', L, 'НАЙДЕНО', building.found(lvl=L))\n"
                   "create_wall(p0_mm=[0,0], p1_mm=[1,0], level='L1')", idx)
        self.assertTrue(out.ok, out.refusal and out.refusal.render())
        self.assertIn("НАЙДЕНО 1", out.stdout)


class ПодписьИндексаЕдетНаружу(unittest.TestCase):

    def test_разные_здания_разные_подписи(self):
        a = sandbox.building_catalog_digest(bi.build_index([_El("1")]))
        b = sandbox.building_catalog_digest(bi.build_index([_El("2")]))
        self.assertTrue(a and b)
        self.assertNotEqual(a, b)

    def test_нет_индекса_нет_подписи(self):
        self.assertEqual(sandbox.building_catalog_digest({}), "")


class КадрНеСломанДляТехКтоБезЗдания(unittest.TestCase):
    """REVERSE CONTROL: the frame's second section has no right to break the
    old path."""

    def test_скрипт_без_индекса_работает_как_прежде(self):
        out = _run("create_wall(p0_mm=[0,0], p1_mm=[3000,0], level='L1')")
        self.assertTrue(out.ok, out.refusal and out.refusal.render())
        self.assertEqual(len(out.ops), 1)

    def test_каталог_и_индекс_живут_вместе(self):
        idx = bi.build_index([_El("1")])
        out = sandbox.execute_author_script(
            "print('ПУЛОВ', len(model.pools()), 'ЭЛЕМЕНТОВ', building.total())\n"
            "create_wall(p0_mm=[0,0], p1_mm=[1,0], level='L1')",
            model={"levels": [{"id": "9", "name": "L1"}]}, building=idx)
        self.assertTrue(out.ok, out.refusal and out.refusal.render())
        self.assertIn("ПУЛОВ 1", out.stdout)
        self.assertIn("ЭЛЕМЕНТОВ 1", out.stdout)


class ПотолокЭтоОтказАНеУсечение(unittest.TestCase):

    def test_усечения_не_бывает(self):
        """A truncated index looks complete, and searching it lies "not
        found"."""
        idx = bi.build_index([_El(str(i)) for i in range(500)], ceiling_bytes=1000)
        self.assertEqual(idx["tier"], bi.TIER_CENSUS)
        self.assertEqual(idx["elements"], [])
        self.assertEqual(idx["census"]["total"], 500)


if __name__ == "__main__":
    unittest.main()
