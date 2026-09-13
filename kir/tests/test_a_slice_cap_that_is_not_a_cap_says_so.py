"""A slice cap that is not a cap is obligated to NAME the overage (F-203).

`_slice_for` deliberately leaves the freshest record WHOLE, even when it
alone outweighs the cap, and datums are added AFTER the count. Both
omissions are legitimate by design; what is illegitimate is staying silent
about the fact that the declared "hard limit on rendering" is not actually a
limit.

🔴 WHY THREE CHECKS HERE, NOT ONE.

A check for "the field exists on overage" would miss a fix of "always set
the field": that fix would produce the field too. So next to it stands the
reverse — **for a slice that fits within the cap, the overage field must NOT
exist**. And a third check holds `slice_ops_cap` present always: without it,
`slice_ops` has nothing to compare against, and the reader is again left
with no anchor.

What is checked is the PATH (`_slice_for` -> frame fields), not the helper:
the numbers come from the real `_slice_ops_cap()`, not written into the test.
"""
import unittest

from kir.live import plan_stream


class _Запись:
    def __init__(self, ops):
        self.ops = list(ops)
        self.op_count = len(self.ops)


class _Вход:
    """The smallest input that the real `_slice_for` accepts without a showroom."""

    def __init__(self, записи, датумы=()):
        self._r = list(записи)
        self.datums = list(датумы)
        self.level_index = {"L1": tuple(range(len(self._r)))}

    def by_seqs(self, seqs):
        return [self._r[i] for i in seqs]


def _оп(i):
    return {"op": "create_wall", "_id": f"w{i}"}


class ПотолокСрезаНазываетПревышение(unittest.TestCase):

    def setUp(self):
        self.cap = plan_stream._slice_ops_cap()

    def test_свежайшая_запись_перевешивает_потолок_и_срез_БОЛЬШЕ_него(self):
        """A case that matches the subject: without an overage, the check is green by construction."""
        крупная = _Запись(_оп(i) for i in range(self.cap + 40))
        ops, dropped, _pack = plan_stream._slice_for(
            _Вход([крупная]), "L1")
        self.assertGreater(
            len(ops), self.cap,
            "случай подобран не по предмету: срез не превысил потолок, "
            "и проверять нечего")
        self.assertEqual(dropped, 0,
                         "единственная запись не выброшена — она и есть "
                         "свежайшая, которую правило хранит целиком")

    def test_датумы_добавляются_СВЕРХ_учёта(self):
        """The second omission, named separately in the finding."""
        точная = _Запись(_оп(i) for i in range(self.cap))
        датумы = [_оп(9000 + i) for i in range(5)]
        ops, _dropped, _pack = plan_stream._slice_for(
            _Вход([точная], датумы), "L1")
        self.assertEqual(
            len(ops), self.cap + len(датумы),
            "датумы прибавляются к уже исчерпанному потолку, и это надо "
            "видеть числом, а не выводить из кода")

    def test_кадр_НАЗЫВАЕТ_превышение_числом_и_причиной(self):
        """What is checked is WHAT THE HUMAN READS, not just the internal count.

        The first edition of this guard reached only as far as `_slice_for`
        — and would have stayed green if someone cut the frame fields
        entirely. So the naming was moved out into `cap_notice`, and that is
        what gets checked.
        """
        крупная = _Запись(_оп(i) for i in range(self.cap + 40))
        ops, _dropped, _pack = plan_stream._slice_for(_Вход([крупная]), "L1")
        поля = plan_stream.cap_notice(len(ops), self.cap)
        self.assertEqual(поля["slice_ops_cap"], self.cap)
        self.assertEqual(поля["slice_cap_exceeded"], len(ops) - self.cap)
        self.assertIn(str(len(ops)), поля["slice_cap_exceeded_ru"],
                      "строка для человека обязана нести САМО ЧИСЛО, а не "
                      "только слово «превышено»")
        self.assertIn("датумы", поля["slice_cap_exceeded_ru"],
                      "названа обязана быть и ПРИЧИНА: почему потолок не "
                      "потолок")

    def test_срез_В_потолке_превышения_НЕ_объявляет(self):
        """The reverse side: "always set the field" is obligated to go red."""
        малая = _Запись(_оп(i) for i in range(10))
        ops, _dropped, _pack = plan_stream._slice_for(_Вход([малая]), "L1")
        self.assertLessEqual(len(ops), self.cap)
        поля = plan_stream.cap_notice(len(ops), self.cap)
        self.assertEqual(поля["slice_ops_cap"], self.cap,
                         "потолок едет ВСЕГДА: без него slice_ops не с чем "
                         "сравнить")
        self.assertNotIn("slice_cap_exceeded", поля,
                         "срез влез в потолок; объявлять превышение здесь "
                         "значило бы пугать читателя тем, чего нет")


if __name__ == "__main__":
    unittest.main()
