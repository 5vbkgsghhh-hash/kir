"""ФИКСТУРА-МОДЕЛЬ ОБЯЗАНА НЕСТИ КАЖДЫЙ ПУЛ, К КОТОРОМУ ЗАЗЕМЛЯЕТСЯ ХОТЬ ОДИН ОП.

РОД СПИСКА: **ПОЛНЫЙ ПО ПОСТРОЕНИЮ** — потребители перечисляются у авторитета
(`spec.OPS`), а не набираются руками.

ЗАЧЕМ. `GROUND_SNAPSHOT` — единственная модель, на которой считается почти весь
набор. Пул, которого в ней нет, делает НЕДОСТИЖИМЫМ по умолчанию каждый оп,
заземляющийся на этот пул: он отказывает `KIR-G104: <пул>: пусто в модели`, и
отказ выглядит дефектом ОПА, хотя это дефект МОДЕЛИ, на которой его меряют.

ЦЕНА, УПЛАЧЕННАЯ 12.08.2026. `roof_types` отсутствовал. Из-за этого
`create_roof` и `create_extrusion_roof` не заземлялись по умолчанию нигде, а
единственный корпусный вход, где кровля стоит рядом с другими опами
(`group_mixed_members`), был красным — и читался как красный ГРУППОВОГО пути,
который в тот день как раз стал несущим.

И ГЛАВНОЕ, ПОЧЕМУ ЭТО НЕ ЗАМЕЧАЛИ. Пулов у производителя было 35 и у фикстуры
35. **Счёт совпадал; расходились ИМЕНА.** Любая проверка «сколько пулов»
подтвердила бы полноту. Поэтому здесь сверяются МНОЖЕСТВА, а число не
проверяется вовсе — оно ничего не различает.
"""
from __future__ import annotations

import unittest

from kukai.ir.spec import OPS
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

#: Пулы, чьё имя — ШАБЛОН: `{category}` подставляется на заземлении. Проверять
#: надо развёртки, иначе шаблон вечно «отсутствует», и пин станет шумом.
_TEMPLATE_EXPANSIONS = {"structural", "architectural"}


def pools_ops_ground_against() -> dict[str, set[str]]:
    """Пул → опы, которым он нужен. Спрашивается у `spec.OPS`, не у списка."""
    out: dict[str, set[str]] = {}
    for op_name, op_spec in OPS.items():
        for entry in (getattr(op_spec, "grounded", ()) or ()):
            pool = entry[1]
            names = ({pool.format(category=c) for c in _TEMPLATE_EXPANSIONS}
                     if "{category}" in pool else {pool})
            for name in names:
                out.setdefault(name, set()).add(op_name)
    return out


class TheTestModelCarriesEveryPoolItsOpsNeed(unittest.TestCase):

    def test_no_op_grounds_against_a_pool_the_fixture_lacks(self):
        needed = pools_ops_ground_against()
        missing = {p: sorted(ops) for p, ops in needed.items()
                   if p not in GROUND_SNAPSHOT}
        self.assertEqual(
            missing, {},
            "фикстура-модель не несёт пул, к которому заземляется оп: эти опы "
            "недостижимы по умолчанию во всём наборе, а их отказ выглядит "
            "дефектом опа, а не модели")

    def test_the_check_would_notice_a_pool_going_missing(self):
        """Контроль-FAIL: без него зелёный выше не отличим от пустой проверки."""
        needed = pools_ops_ground_against()
        self.assertIn("roof_types", needed, "кровли перестали заземляться — "
                                            "пин смотрит не туда")
        crippled = {k: v for k, v in GROUND_SNAPSHOT.items() if k != "roof_types"}
        missing = [p for p in needed if p not in crippled]
        self.assertEqual(missing, ["roof_types"])

    def test_the_count_alone_never_would_have_noticed(self):
        """Почему сверяются множества, а не число.

        До починки у производителя было 35 пулов и у фикстуры 35 — счёт сходился
        при расходящихся именах. Тест держит это утверждение живым: он падает,
        если кто-нибудь заменит сверку множеств на сверку длин.
        """
        needed = set(pools_ops_ground_against())
        carried = {k for k in GROUND_SNAPSHOT if not k.startswith("__")}
        self.assertTrue(needed <= carried)
        self.assertNotEqual(len(needed), len(carried),
                            "числа совпали — значит сверка по длине выглядела "
                            "бы достаточной; именно так пропустили roof_types")


if __name__ == "__main__":
    unittest.main()
