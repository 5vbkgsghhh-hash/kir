"""Доезжает ли содержимое `members` до эмиссии — поэлементно или сводкой.

ЗАЧЕМ. Решение директора: разворот замысла целится в L1. Тогда всё, что
`fold.iter_l1_leaves` отдаёт из `members`, обязано доехать до опов — иначе
кластер, который для читателя один узел, теряет содержимое по дороге к зданию.
Зона КОРПУС назвала цену: 23 855 записей из 55 293 на башне, 43% содержимого.

ОТВЕТ: **`members` — НЕ сводка.** Это `list[L1Node]`, тот же тип, что `payload`,
полные записи со своими `_id`/`source_element_id`; сводка лежит РЯДОМ, в
`macro`. `iter_l1_leaves` отдаёт члена в одном ранге с `payload`, а
`fold.assert_preservation` — закон, стоящий на КАЖДОМ `fold_document` — требует
точного совпадения мультимножества листьев И побайтового равенства полезной
нагрузки. Потерять члена нельзя не тихо, а вообще.

**НО 43% — НЕ ТО ЧИСЛО, КОТОРОЕ ЗДЕСЬ РЕШАЕТ, И РАЗБИВКА ПО РОДУ ЭТО МЕНЯЕТ.**
Замер 12.08.2026 на ТРЁХ прогонах башни. Обход с происхождением, его итог сверен
с авторитетом на каждом (55 293 = 55 293, 115 880 = 115 880, 115 880 = 115 880),
иначе разбивка недействительна:

    прогон        листьев   members            АТОМЫ    ОПЫ   доехало  контроль
                                               в members       опов     payload
    v6 ОТОЗВАН     55 293   23 855 (43.14%)   23 582    273   273/273  29 575/29 575
    v7            115 880   80 547 (69.51%)   80 268    279   279/279  29 650/29 650
    v8            115 880   77 262 (66.67%)   76 983    279   279/279  32 555/33 198

Разложение членов устойчиво: `atom_cluster→atom` держит 96–99% членов,
`row→оп` даёт 265/271/271, `grid_array→оп` — 8 на всех трёх.

Атом — типизированная невыразимость с кодом причины, а не оп: разворот его не
порождает и не обязан. **Обязаны доехать опы-члены, и на всех трёх прогонах
доезжают ВСЕ, пропущено 0.** Пропуски materialize — ровно атомы (`atom:*`), плюс
на `v8` ещё 643 `host_unmaterialized` — и это ВАЖНО: на `v8` контроль перестал
быть стопроцентным (payload 32 555 из 33 198 = 98.06%), то есть матчер УМЕЕТ
показать потерю. Опы-члены при этом идут лучше payload'а: 100% против 98.06%.

**ОТЗЫВ, И ОН МОЙ СОБСТВЕННЫЙ.** Головное число «честный знаменатель авторства =
53.98%» было снято с `v6` и НЕДЕЙСТВИТЕЛЬНО: зона КОРПУС нашла в этом прогоне
2 846 отказов группового индекса из 2 941 (потеряно 96.77% групп), а сверх того
`v6` — частичное чтение (20 категорий из таблицы вернулись пустыми). Законная
полоса по двум чистым прогонам:

    v7   29 929 листьев-опов из 115 880 = 25.83%
    v8   33 477 листьев-опов из 115 880 = 28.89%

**Почему это стоит больше самой поправки.** Опов между `v6` и `v7` почти не
прибавилось (29 848 → 29 929, +0.27%), а атомов стало втрое больше
(25 445 → 85 951). Значит 53.98% не мерили КОМПИЛЯТОР — они мерили, СКОЛЬКО
ЗДАНИЯ ПРОЧЁЛ ТОТ ПРОГОН. Ровно тот дефект, из-за которого фасад давал 63.80 и
91.23 без единой строки правки. Знаменатель авторства обязан публиковаться с
условиями чтения, иначе он неинтерпретируем. Разница `v7`→`v8` (25.83 → 28.89
при одинаковом чтении 115 880) — уже настоящая: это лифтер, а не чтение.

КОНТРОЛЬ ПОЙМАЛ СЕБЯ, и это стоит записать: первый прогон сопоставлял адрес
эмиссии с голым `source_element_id` и дал **0 из 273** — что читалось бы как
«члены теряются». Спасло то, что рядом печатался знаменатель контроля: payload
дал **0 из 29 575**, то есть слепым был МАТЧЕР. Адрес эмиссии — `_op_id` =
``"e" + source_element_id``; спрошено у `materialize._op_id`, не угадано.

РОД ЭТОГО ТЕСТА. Числа выше — ДАТИРОВАННЫЙ ЗАМЕР на машинно-локальном корпусе
(`backend/backend/data/decompile/`, вне всякого чекаута; `k2_ar_rd_v15` числа не
даёт вообще — у него нет `tree.json`, и это молчание прибора, а не ноль). Тест
их НЕ гоняет:
страж без своего прибора обязан отказывать в категории, которую не спутать с
«находок нет». Здесь пиньтся СТРУКТУРНЫЙ факт, который от корпуса не зависит и
который только и нужен разворотовому контракту: член идёт в одном ранге с
`payload` и доезжает до опа. Повторить замер:
``scratchpad/member_ops_reach_programs.py`` (обход + `leaves_to_program`).
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.fold import iter_l1_leaves
from kukai.ir.decompile.l1_schema import stable_l1_id
from kukai.ir.decompile.materialize import leaves_to_program

LEVEL_SRC = "SYNTH-LEVEL-1"
PAYLOAD_SRC = "SYNTH-COL-PAYLOAD"
MEMBER_SRC = "SYNTH-COL-MEMBER"
LEVEL_ID = stable_l1_id("op", LEVEL_SRC)


def _op(op_name, source_id, params, level_name=None):
    return {
        "kind": "op",
        "_id": stable_l1_id("op", source_id),
        "source_element_id": source_id,
        "level_name": level_name,
        "anchor_mm": None,
        "type_name": "—",
        "op_name": op_name,
        "params": params,
    }


def _level():
    return _op("create_level", LEVEL_SRC, {"name": "Этаж 1", "elev_mm": 0})


def _wall(source_id, x):
    return _op("create_wall", source_id, {
        "p0_mm": [x, 0], "p1_mm": [x + 4000, 0], "height_mm": 3000,
        "level": {"ref": LEVEL_ID},
        "type": {"by": "name", "value": "Стена 200", "_id": "12345"},
    }, level_name="Этаж 1")


def _node(kind, *, payload=None, members=(), children=()):
    """Литерал узла ровно в той части, которую читает `iter_l1_leaves`.

    Обход трогает три ключа и никакие другие; строить полный `TreeNode` с
    `facts`/`node_id` здесь значило бы утверждать больше, чем проверяется.
    """
    return {"kind": kind, "payload": payload,
            "members": list(members), "children": list(children)}


def _tree(members):
    """Дерево: уровень листом, а стена — ЧЛЕНОМ сводки `row`."""
    return _node("floor", children=[
        _node("op", payload=_level()),
        _node("row", members=members),
    ])


class AMemberTravelsAtTheSameRankAsAPayload(unittest.TestCase):

    def test_the_authority_yields_members_beside_payloads(self):
        """`iter_l1_leaves` не различает члена и полезную нагрузку."""
        seen = [leaf["source_element_id"]
                for leaf in iter_l1_leaves(_tree([_wall(MEMBER_SRC, 8000)]))]
        self.assertEqual(sorted(seen), sorted([LEVEL_SRC, MEMBER_SRC]))

    def test_a_member_op_reaches_the_emitted_program(self):
        """Член доезжает до опа под адресом `_op_id` = "e" + source id."""
        leaves = list(iter_l1_leaves(_tree([_wall(MEMBER_SRC, 8000)])))
        result = leaves_to_program(leaves, include_datums=True)
        emitted = {op["id"] for program in result.programs
                   for op in program["ops"]}
        self.assertIn("e" + MEMBER_SRC, emitted)
        self.assertEqual(
            [record.source_id for record in result.skipped], [],
            "член пропущен materialize — содержимое сводки теряется")

    def test_the_probe_can_say_no(self):
        """Контроль-FAIL: без члена тот же адрес обязан ИСЧЕЗНУТЬ.

        Иначе «доехал» неотличимо от матчера, отвечающего да на что угодно —
        ровно та ошибка, которую живой замер поймал у себя: сопоставление по
        голому `source_element_id` дало 0 из 273 ПРИ 0 из 29 575 на контроле.
        """
        leaves = list(iter_l1_leaves(_tree([])))
        result = leaves_to_program(leaves, include_datums=True)
        emitted = {op["id"] for program in result.programs
                   for op in program["ops"]}
        self.assertNotIn("e" + MEMBER_SRC, emitted)

    def test_a_payload_and_a_member_are_indistinguishable_downstream(self):
        """Тот же оп payload'ом и членом даёт ту же эмиссию, кроме адреса.

        Это и есть «не сводка»: ранг узла не меняет НИЧЕГО в том, что доедет.
        """
        as_member = leaves_to_program(
            list(iter_l1_leaves(_tree([_wall(MEMBER_SRC, 8000)]))),
            include_datums=True)
        as_payload = leaves_to_program(
            list(iter_l1_leaves(_node("floor", children=[
                _node("op", payload=_level()),
                _node("op", payload=_wall(PAYLOAD_SRC, 8000)),
            ]))),
            include_datums=True)

        def shape(result, source_id):
            for program in result.programs:
                for op in program["ops"]:
                    if op["id"] == "e" + source_id:
                        return {key: value for key, value in op.items()
                                if key != "id"}
            return None

        self.assertIsNotNone(shape(as_member, MEMBER_SRC))
        self.assertEqual(shape(as_member, MEMBER_SRC),
                         shape(as_payload, PAYLOAD_SRC))


if __name__ == "__main__":
    unittest.main()
