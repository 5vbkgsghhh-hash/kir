"""Каждый пишущий оп ОБЯЗАН быть назван ровно одним механизмом.

ПОВОД — НЕ ГИПОТЕЗА, А ПЕРЕМЕР 11.08.2026. Абзац в `spec.py` над
`OP_RESULT_CATEGORIES` объяснял «незаполненные» опы тремя механизмами и
суммой 43 + 10 + 4 + 7 = 64. На день перемера в реестре было 65 пишущих
опов, 44 строки таблицы, а разрешатель отвечал за 6 — и главное, механизмов
оказалось ПЯТЬ: `create_group` не назван ни таблицей, ни разрешателем, ни
одним из двух журналов приёмки. Он назван ПЯТЫМ способом, которого абзац не
упоминал вовсе: обёртку группы Revit ведёт как собственную бухгалтерию
(`acceptance._OP_DERIVED`), а ожидание строится по ЧЛЕНАМ группы.

Прежняя сумма сходилась не потому, что была верна, а потому, что слагаемые и
итог сняли в один день. Такую арифметику обязан держать ТЕСТ: абзац
объясняет ПОЧЕМУ, тест отвечает СКОЛЬКО.

ЧЕГО ЭТОТ ТЕСТ НЕ ДЕЛАЕТ И ПОЧЕМУ. Он НЕ требует, чтобы у каждого опа была
строка в таблице. Заполнить категорию, которой перепись не наблюдает, —
ошибка НЕОБРАТИМАЯ: приёмка ждёт прибавки в клетке, куда никто не смотрит,
и ЧЕСТНАЯ постройка получает `category_shortfall`. Слепота обратима: теряется
только верхняя граница. Поэтому тест требует ИМЕНОВАННОСТИ, а не полноты.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_accounting_queue.jsonl"))

from kukai.ir import acceptance, spec  # noqa: E402

#: Пробы разновидностей: у шести опов категорию решает СОБСТВЕННОЕ закрытое
#: перечисление, и разрешатель отвечает только по заполненному полю.
_VARIETY_PROBES = (
    {}, {"variety": "wall_rect"}, {"variety": "host_face"},
    {"variety": "isolated"}, {"variety": "slab"},
    {"variety": "surface"}, {"variety": "toposolid"},
    {"category": "structural"}, {"category": "generic_model"},
)


def _writing_ops():
    return {name for name, op in spec.OPS.items()
            if op.family in spec.WRITE_FAMILIES}


def _resolver_answers(name):
    """Отвечает ли разрешатель на оп, у которого строки в таблице нет."""
    for probe in _VARIETY_PROBES:
        op = dict(probe)
        op["op"] = name
        try:
            if spec.op_result_categories(op):
                return True
        except Exception:
            continue
    return False


def _buckets():
    writing = _writing_ops()
    table = set(spec.OP_RESULT_CATEGORIES) & writing
    blind = set(acceptance._OPS_BLIND) & writing
    no_elements = set(acceptance._OPS_WITHOUT_ELEMENTS) & writing
    resolver = {n for n in writing - table if _resolver_answers(n)}
    derived_only = {
        n for n in writing - table - blind - no_elements - resolver
        if acceptance._OP_DERIVED.get(n)}
    return writing, table, resolver, blind, no_elements, derived_only


class EveryWritingOpIsNamed(unittest.TestCase):

    def test_no_writing_op_is_unaccounted(self):
        """Оп, которого не назвал НИ ОДИН механизм, — молчаливая слепота:
        приёмка не строит по нему ни строки ожидания, ни записи о том, что
        смотреть нечего. Снаружи это неотличимо от «проверили и сошлось»."""
        writing, table, resolver, blind, no_elements, derived = _buckets()
        unaccounted = writing - table - resolver - blind - no_elements - derived
        self.assertEqual(
            unaccounted, set(),
            "пишущие опы, которых не назвал ни один механизм: %s — добавь "
            "строку в spec.OP_RESULT_CATEGORIES ТОЛЬКО если категория "
            "ЗАМЕРЕНА, иначе назови слепым в acceptance._OPS_BLIND с "
            "причиной словами" % sorted(unaccounted))

    def test_the_table_never_contradicts_the_blind_ledger(self):
        """Оп не может одновременно иметь клетку переписи и быть объявлен
        невидимым для переписи — это два ответа на один вопрос."""
        _w, table, _r, blind, _n, _d = _buckets()
        self.assertEqual(
            table & blind, set(),
            "оп и в таблице категорий, и в журнале слепых: %s"
            % sorted(table & blind))

    def test_the_table_holds_only_writing_ops(self):
        """Строка про читающий оп обещала бы прибавку от операции, которая
        ничего не создаёт."""
        extra = set(spec.OP_RESULT_CATEGORIES) - _writing_ops()
        self.assertEqual(extra, set(),
                         "не-пишущие опы в таблице категорий: %s"
                         % sorted(extra))

    def test_the_arithmetic_in_the_spec_comment_still_holds(self):
        """ЧИСЛА ИЗ АБЗАЦА НАД ТАБЛИЦЕЙ. Тест намеренно падает при добавлении
        опа: прежняя редакция абзаца разъехалась с деревом молча, и цена
        этого — читатель, который верит сумме, не сходящейся уже месяц.
        Падение здесь означает «обнови абзац в spec.py», а не «почини код»."""
        writing, table, resolver, blind, no_elements, derived = _buckets()
        measured = {
            "writing": len(writing), "table": len(table),
            "resolver": len(resolver), "blind": len(blind),
            "no_elements": len(no_elements), "derived_only": len(derived),
        }
        self.assertEqual(
            measured,
            {"writing": 66, "table": 44, "resolver": 6, "blind": 11,
             "no_elements": 4, "derived_only": 1},
            "арифметика категорий сдвинулась — обнови абзац над "
            "OP_RESULT_CATEGORIES в spec.py и это число здесь")
        self.assertEqual(
            len(table) + len(resolver) + len(blind) + len(no_elements)
            + len(derived), len(writing))

    def test_the_two_named_gaps_stay_named_and_stay_out_of_the_table(self):
        """`create_curtain_grid_line` и `create_wall_foundation` — НЕ пробел,
        а названная слепота, и заполнять их запрещено: ошибка заполнения
        отклоняет честную постройку, ошибка слепоты теряет верхнюю границу."""
        for name in ("create_curtain_grid_line", "create_wall_foundation"):
            with self.subTest(op=name):
                self.assertNotIn(name, spec.OP_RESULT_CATEGORIES)
                self.assertIn(name, acceptance._OPS_BLIND)
                self.assertTrue(acceptance._OPS_BLIND.reason(name).strip())

    def test_create_group_is_named_by_the_fifth_mechanism(self):
        """Пятый механизм, которого прежний абзац не называл вовсе: обёртку
        группы ведёт Revit (`_OP_DERIVED`), а ожидание строится по ЧЛЕНАМ."""
        self.assertNotIn("create_group", spec.OP_RESULT_CATEGORIES)
        self.assertIsNone(spec.op_result_categories({"op": "create_group"}))
        self.assertNotIn("create_group", acceptance._OPS_BLIND)
        self.assertTrue(acceptance._OP_DERIVED.get("create_group"))


if __name__ == "__main__":
    unittest.main()