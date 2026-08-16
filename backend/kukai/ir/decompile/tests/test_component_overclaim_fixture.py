"""Избыточная заявка компонентного слоя — сторож, вынутый ИЗ НАСТОЯЩЕГО СЛУЧАЯ.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ, а не строка в `test_component.py`. Разделение труда между
двумя приборами названо, потому что иначе один подменяет другой:

    КОРПУС ОТКРЫВАЕТ   `test_component_corpus_reality.py` ходит по стоящим на
                       диске прогонам и находит то, чего никто не закладывал;
                       он же единственный видит масштаб.
    ФИКСТУРА СТОРОЖИТ  этот файл держит ОДИН вынутый случай в 34 листа: он
                       живёт в дереве, не требует корпуса и краснеет за
                       секунды.

Свойство C-RT (развёртка библиотеки = мультимножество листьев источника)
проверялось в `test_component.py` с 2026-08-09 и держалось — на сеяных сетках в
1–4 этажа. Ложным оно стало на башне: 99 ключей заявлены дважды при кратности
источника 1. Это форма 10 канона дословно — стоимость (здесь: вероятность
пересечения двух вхождений) растёт с n, а прибор с n=3 её не видит. Поэтому
фикстура вынута из настоящего дефекта, а не придумана.

ПРОИСХОЖДЕНИЕ, ПОИМЁННО. Четыре поддерева скопированы дословно из башни
`13A-RD-AR-K2_v33`; узлы присутствуют в ДВУХ прогонах, `k2_ar_rd_v7` и
`k2_ar_rd_v8` (`grep` по `tree.json`, 2026-08-13):

    cffd24b849…  room          «Жилая комната 4»       12 листьев
    285cc1ba9b…  room          «Жилая комната 4»
    ac915268fd…  atom_cluster  5 × OST_RoomSeparationLines
    710caf800b…  atom_cluster  5 × OST_RoomSeparationLines

Пара комнат даёт один повтор, пара кластеров — второй; спорные листья —
разделительные линии помещений, ровно та категория, на которую пришлось 100%
избытка башни. Корень несёт `facts` исходного дерева без правки.

МОЩНОСТЬ, ПРИ КОТОРОЙ КОНТРОЛЬ СПОСОБЕН УПАСТЬ — сказана числом, потому что
контроль на вырожденном входе зелен по построению:

    повторов в фикстуре                       2   (нужно >= 2: с одним
                                                  компонентом делить не с кем)
    вхождений у них                        4 и 2  (нужно >= 2 у каждого, иначе
                                                  `min_occurrences` отвергнет
                                                  их до всякой заявки)
    ключей, делимых двумя экземплярами       12   (нужно >= 1, иначе спора нет)
    из них С ПРЕВЫШЕНИЕМ источника           10   (по +1 каждый = избыток 10)
    кратности источника у превышенных      1 и 2  (нужна хотя бы 1: там, где
                                                  источник несёт столько же,
                                                  заявка ЗАКОННА и правило
                                                  молчит правильно)
    делимых БЕЗ превышения                    2   (нужно >= 1, иначе фикстура
                                                  не отличит «не превышай» от
                                                  «не дели»)

Ниже эти четыре числа проверяются исполняемо: если фикстура выродится — от
правки канона, от смены хеша, от чего угодно — упадёт `TheFixtureIsSharpEnough`,
а не «C-RT держится» вакуумно.
"""
from __future__ import annotations

import json
import pathlib
import unittest
from collections import Counter
from unittest import mock

from kukai.ir.decompile import component
from kukai.ir.decompile.component import (
    _abs_multiset, build_library, expand_library, instantiate)
from kukai.ir.decompile.fold import iter_l1_leaves
from kukai.ir.decompile.merkle import build_index, dedup_report

FIXTURE = (pathlib.Path(__file__).parent / "fixtures"
           / "component_overclaim_tower.json")

#: Избыток неправленого кода на ЭТОЙ фикстуре, измерен 2026-08-13 прогоном
#: `build_library` в локальном рабочем дереве (без
#: правки): 2 компонента, 6 экземпляров, избыток 10, недостача 0.
#: Число держит ОБА конца: контроль-FAIL обязан воспроизвести именно его, иначе
#: заглушка сняла не то, что снимает отсутствие правки.
UNFIXED_EXCESS = 10


def _tree():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _claimed_multiset(lib):
    """Сколько раз каждый абсолютный оп заявлен РАЗМЕЩЕНИЯМИ (без одиночек)."""
    counts: Counter[str] = Counter()
    for op in lib.place_ops:
        for inst in op.instances:
            for leaf in instantiate(
                    op.definition, inst.offset_mm,
                    instance_index=inst.instance_index, regenerate_ids=False):
                key, = _abs_multiset([leaf])
                counts[key] += 1
    return counts


def _holders(lib):
    """{абсолютный оп: {(компонент, номер экземпляра), …}} — КТО его заявил."""
    out: dict[str, set] = {}
    for op in lib.place_ops:
        for inst in op.instances:
            for leaf in instantiate(
                    op.definition, inst.offset_mm,
                    instance_index=inst.instance_index, regenerate_ids=False):
                key, = _abs_multiset([leaf])
                out.setdefault(key, set()).add(
                    (op.def_hash, inst.instance_index))
    return out


def _overflow(lib, source_abs):
    """(избыток, недостача) развёртки против мультимножества источника."""
    back = _abs_multiset(expand_library(lib))
    over = sum(back[k] - source_abs.get(k, 0)
               for k in back if back[k] > source_abs.get(k, 0))
    under = sum(source_abs[k] - back.get(k, 0)
                for k in source_abs if source_abs[k] > back.get(k, 0))
    return over, under


class TheLibraryPartitionsTheSource(unittest.TestCase):

    def test_expansion_is_a_partition_not_a_cover(self):
        """C-RT на настоящем случае: ни избытка, ни недостачи.

        НОЛЬ ЗДЕСЬ ДВУСТОРОННИЙ, и вторая половина не менее важна первой.
        Избыток 0 говорит «мы не заявили лишнего»; недостача 0 говорит «чиня
        избыток, мы не выбросили законное». Правило запрещает не ДЕЛЕНИЕ ключа
        между экземплярами, а ПРЕВЫШЕНИЕ кратности источника: на корпусе
        измерено 322 законных деления, вплоть до кратностей 438 и 1507, и все
        они обязаны выжить.
        """
        tree = _tree()
        index = build_index(tree, label="overclaim")
        lib = build_library(index)
        source_abs = _abs_multiset(iter_l1_leaves(index.root.tree_node))
        over, under = _overflow(lib, source_abs)
        self.assertEqual(
            (over, under), (0, 0),
            f"развёртка не есть разбиение источника: избыток {over}, "
            f"недостача {under}")


class TheFixtureIsSharpEnough(unittest.TestCase):
    """Контроль-PASS: у входа есть чем упасть.

    Не «фикстура корректна», а «фикстура НЕ ВЫРОЖДЕНА». Зелёный выше и зелёный
    на дереве без единого повтора печатаются одинаково, и различает их только
    этот класс.
    """

    def test_the_fixture_carries_two_repeats_of_power_two_and_four(self):
        tree = _tree()
        index = build_index(tree, label="overclaim")
        reps = dedup_report([index], min_occurrences=2, min_leaves=2)
        powers = sorted(len(index.occurrences_of(e.hash)) for e in reps)
        self.assertEqual(
            powers, [2, 4],
            f"мощности повторов {powers}: нужны ДВА повтора со вхождениями "
            f">= 2 каждый — иначе делить нечего и C-RT зелен по построению")

    def test_the_fixture_carries_both_classes_not_only_the_easy_one(self):
        """Спор есть, и рядом с ним есть ЗАКОННОЕ деление — оба обязаны быть.

        ПЕРВАЯ РЕДАКЦИЯ ЭТОГО КЛАССА УТВЕРЖДАЛА «5 спорных ключей, кратность
        источника у всех 1», и была неверна дважды. Пятёрка измерена на
        ПРАВЛЕНОЙ библиотеке, где спор уже снят, — то есть числом ПОСЛЕ лечения
        описывалась болезнь; а «кратность всегда 1» оказалось моим упрощением:
        среди превышенных ключей есть и кратность 2, заявленная трижды.
        Поймал это сам контроль-PASS на первом же прогоне, и это ровно то, зачем
        он написан.

        Измерено на фикстуре 2026-08-13, заглушив предикат:

            делимых двумя и более экземплярами   12
            из них С ПРЕВЫШЕНИЕМ источника       10   (по +1 каждый = избыток 10)
            кратности источника у превышенных    1 и 2
            делимых БЕЗ превышения                2   (кратность 2, заявлены 2)

        Последняя строка — это и есть вторая сторона: правило запрещает не
        деление, а превышение, и фикстура СПОСОБНА поймать правило, которое
        запретило бы слишком много.
        """
        tree = _tree()
        index = build_index(tree, label="overclaim")
        source_abs = _abs_multiset(iter_l1_leaves(index.root.tree_node))
        with mock.patch.object(component, "_multiset_fits",
                               lambda *_a, **_k: True):
            unguarded = build_library(index)
        claimed = _claimed_multiset(unguarded)
        holders = _holders(unguarded)
        shared = {k for k, v in holders.items() if len(v) > 1}
        exceeding = {k for k in claimed if claimed[k] > source_abs.get(k, 0)}
        self.assertEqual(
            (len(shared), len(exceeding)), (12, 10),
            f"делимых {len(shared)}, превышающих {len(exceeding)} — фикстура "
            f"изменилась, пересними и объясни")
        self.assertEqual(
            sorted({source_abs.get(k, 0) for k in exceeding}), [1, 2],
            "превышение осталось только на кратности 1 — фикстура упростилась "
            "до самого лёгкого случая")
        self.assertTrue(
            shared - exceeding,
            "в фикстуре не осталось ЗАКОННОГО деления: она перестала различать "
            "правило «не превышай» от правила «не дели», а это разные правила")

    def test_the_legitimate_split_survives_the_guard(self):
        """Вторая сторона нуля: правило не выбросило законное вместе с лишним.

        После правки деление между экземплярами ПРОДОЛЖАЕТСЯ — 5 ключей, и у
        каждого заявка не превышает кратность источника. Без этого утверждения
        «избыток 0» неотличим от правила, запретившего делить вообще, а на
        корпусе таких законных делений 322, вплоть до кратностей 438 и 1507.
        """
        tree = _tree()
        index = build_index(tree, label="overclaim")
        source_abs = _abs_multiset(iter_l1_leaves(index.root.tree_node))
        lib = build_library(index)
        holders = _holders(lib)
        claimed = _claimed_multiset(lib)
        shared = {k for k, v in holders.items() if len(v) > 1}
        self.assertEqual(
            len(shared), 5,
            f"делимых ключей после правки {len(shared)}, было 5")
        self.assertTrue(
            all(claimed[k] <= source_abs.get(k, 0) for k in shared),
            "деление после правки превышает источник — правило не сработало")

    def test_the_fixture_is_small_enough_to_read(self):
        """34 листа: сторож обязан быть читаемым глазом, иначе его не чинят."""
        tree = _tree()
        index = build_index(tree, label="overclaim")
        leaves = list(iter_l1_leaves(index.root.tree_node))
        self.assertEqual(len(leaves), 34)
        self.assertEqual(len(tree["children"]), 4)


class TheGuardCanBeDisabled(unittest.TestCase):
    """Контроль-FAIL: опыт МОГ кончиться иначе, и это показано на этом входе.

    Глушится НАСТОЯЩИЙ предикат в настоящем `build_library`, а не переписанный
    в тесте цикл: «прибор врёт своему автору» ловится только тогда, когда
    контроль идёт тем же путём, что и проверяемое.
    """

    def test_without_the_predicate_the_defect_returns_at_its_measured_size(self):
        tree = _tree()
        index = build_index(tree, label="overclaim")
        source_abs = _abs_multiset(iter_l1_leaves(index.root.tree_node))
        with mock.patch.object(component, "_multiset_fits",
                               lambda *_a, **_k: True):
            lib = build_library(index)
        over, under = _overflow(lib, source_abs)
        self.assertEqual(
            (over, under), (UNFIXED_EXCESS, 0),
            f"с заглушённым правилом избыток {over} (недостача {under}), а "
            f"неправленый код даёт {UNFIXED_EXCESS}: заглушка сняла не то, что "
            f"снимает отсутствие правки — контроль ничего не доказывает")

    def test_the_price_of_the_guard_is_stated(self):
        """Цена названа числом: правило стоит компонента и двух размещений.

        Отвергается ЭКЗЕМПЛЯР, но если после отказа их остаётся меньше
        `min_occurrences`, компонент уходит целиком — здесь именно так. Это не
        дефект правила, а его цена, и она обязана стоять в тесте: молчаливое
        исчезновение компонента читалось бы как «повтора не было».
        """
        tree = _tree()
        index = build_index(tree, label="overclaim")
        guarded = build_library(index)
        with mock.patch.object(component, "_multiset_fits",
                               lambda *_a, **_k: True):
            unguarded = build_library(index)
        self.assertEqual(
            (len(unguarded.definitions),
             sum(len(o.instances) for o in unguarded.place_ops)),
            (2, 6))
        self.assertEqual(
            (len(guarded.definitions),
             sum(len(o.instances) for o in guarded.place_ops)),
            (1, 4),
            "цена правила изменилась: пересними число и объясни, почему")
        self.assertEqual(len(guarded.singletons_leaves), 14)


if __name__ == "__main__":
    unittest.main()
