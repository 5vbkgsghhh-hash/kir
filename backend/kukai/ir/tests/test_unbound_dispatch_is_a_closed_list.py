"""Каждая отправка в Revit либо связана артефактом, либо НАЗВАНА поимённо.

Связывание доказывает, что в Revit уехали ровно те байты, которые прошли
приёмку. Охрана у моста умеет заметить ПОДМЕНУ связывания и не умеет спросить
«а должна ли была эта отправка быть связанной вообще»: без обоих ключей она
пропускала что угодно. Тот, кто способен переписать `code`, способен и снять
ключи — то есть дыра была под того самого противника, которого называет
докстринг охраны.

Закрыть список — второе из двух наших лекарств. Этот тест и есть замок: он
ОБХОДИТ ПАКЕТ и требует, чтобы всякая литеральная пара (tool, op) на вызовах
`run_declarative` была либо связанной полосой записи, либо названа в
`UNBOUND_DISPATCH_OPS` с причиной. Новый маршрут не проедет молча.

ЧЕГО ОБХОД НЕ ВИДИТ, названо здесь, а не подразумевается: три вызова передают
`op` ПЕРЕМЕННОЙ (`serving.py` — форвардер, `family`, и фаза приёмочного
чтения). Их значения дочитаны в коде замером 11.08.2026 — `query`/`write` у
семьи и `acceptance_before`/`acceptance_after` у читателя — и стоят в списке
как литералы. Появится четвёртый динамический вызов — обход о нём НЕ скажет,
скажет отказ в рантайме, и это осознанный размен: список сторожит то, что
статически видно, а рантайм — остальное.
"""
from __future__ import annotations

import ast
import os
import unittest

from kukai.ir.acceptance_evidence import REGULAR_WRITE_EXECUTION_LANE
from kukai.llm.revit_execution_pipeline import UNBOUND_DISPATCH_OPS

DISPATCH_CALLS = {"run_declarative", "_run_declarative"}

#: Связанная полоса: единственная пара, которой в списке быть НЕ должно.
BOUND_LANE = ("revit_ir", "write")


def _package_root() -> str:
    from kukai import ir
    return os.path.dirname(os.path.dirname(os.path.abspath(ir.__file__)))


def _literal_dispatch_pairs() -> tuple[set[tuple[str, str]], list[str]]:
    """(литеральные пары, вызовы с динамическим op) по всему пакету."""
    pairs: set[tuple[str, str]] = set()
    dynamic: list[str] = []
    root = _package_root()
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        if os.path.sep + "tests" in folder:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(folder, fname)
            try:
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), path)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None))
                if name not in DISPATCH_CALLS:
                    continue
                keywords = {kw.arg: kw.value for kw in node.keywords}

                def literal(value: ast.AST | None) -> str | None:
                    return (value.value
                            if isinstance(value, ast.Constant)
                            and isinstance(value.value, str) else None)

                if name == "_run_declarative":
                    op = (literal(node.args[3]) if len(node.args) > 3
                          else literal(keywords.get("op")))
                    tool = "revit_ir"
                else:
                    op = literal(keywords.get("op"))
                    tool = literal(keywords.get("tool"))
                where = f"{os.path.relpath(path, root)}:{node.lineno}"
                if op is None or tool is None:
                    dynamic.append(where)
                else:
                    pairs.add((tool, op))
    return pairs, dynamic


class UnboundDispatchIsAClosedList(unittest.TestCase):

    def test_every_literal_dispatch_is_bound_or_named(self):
        pairs, _dynamic = _literal_dispatch_pairs()
        self.assertTrue(pairs, "обход не нашёл ни одной отправки — он сломан")
        unaccounted = sorted(
            pair for pair in pairs
            if pair != BOUND_LANE and pair not in UNBOUND_DISPATCH_OPS)
        self.assertEqual(
            unaccounted, [],
            "отправка не связана артефактом и не названа в "
            "UNBOUND_DISPATCH_OPS — назовите её с причиной либо свяжите")

    def test_the_bound_lane_is_not_on_the_unbound_list(self):
        """Иначе список молча разрешил бы то, ради чего он написан."""
        self.assertNotIn(BOUND_LANE, UNBOUND_DISPATCH_OPS)
        self.assertEqual(REGULAR_WRITE_EXECUTION_LANE, "kir_regular_write")

    def test_the_list_holds_no_entry_the_code_stopped_making(self):
        """Список — ЗАМОК, а не архив: снятый маршрут обязан уйти из него.

        Иначе разрешение переживёт свой маршрут, и следующая пара с тем же
        именем проедет по чужому основанию. Динамические вызовы из списка
        исключены: обход их не видит по построению, и требовать от них
        литерального совпадения значило бы удалять верные строки.
        """
        pairs, _dynamic = _literal_dispatch_pairs()
        dynamic_ops = {
            ("revit_ir", "query"),            # family
            ("revit_ir", "acceptance_before"),  # фаза приёмочного чтения
            ("revit_ir", "acceptance_after"),
        }
        stale = sorted(
            pair for pair in UNBOUND_DISPATCH_OPS
            if pair not in pairs and pair not in dynamic_ops)
        self.assertEqual(
            stale, [],
            "в списке остался маршрут, которого в коде больше нет")


if __name__ == "__main__":
    unittest.main()
