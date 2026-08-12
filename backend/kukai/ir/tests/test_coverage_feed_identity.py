"""Отказ обязан сохранить свою личность.

`coverage_feed` схлопывал ЛЮБУЮ диагностику, кроме G001/G002, в контрактный
`VALIDATION_FAILED` и выбрасывал `candidates`. Последствие замерено 09.08.2026
по `kir_rejections.jsonl` (1469 событий, 16.07–04.08): 1364 события лежат под
одним кодом, и внутри — два разных мира. 662 из них ВЕРНЫЕ отказы: компилятор
не стал выбирать за автора и назвал кандидатов (604 неоднозначности, 49 «имя
не найдено» с ближайшими, 9 честно пустых пулов). Остальное — ошибки автора.
Считались они одинаково, и работа компилятора уходила в статистику как дефект.

Тесты держат обе стороны: код и кандидаты доезжают до события, а контрактный
`reject_code` при этом НЕ меняется — консьюмер ранжирует дыры по нему.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from kukai.ir import coverage_feed
from kukai.ir.diag import Diagnostic


def _events(diags, ops=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rej.jsonl")
        old = os.environ.get(coverage_feed._ENV)
        os.environ[coverage_feed._ENV] = path
        try:
            coverage_feed.record_rejections(diags, ops or [], query_id="q1")
        finally:
            if old is None:
                os.environ.pop(coverage_feed._ENV, None)
            else:
                os.environ[coverage_feed._ENV] = old
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


AMBIGUOUS = Diagnostic(
    code="KIR-G102",
    message_ru="door_symbols: «ДПГ» неоднозначен — 3 совпадений; уточни через "
               "{\"by\": \"element_id\", \"value\": <id из candidates>}",
    op_index=0, field_name="symbol",
    candidates=[{"id": 111, "name": "ДПГ 21-9"},
                {"id": 222, "name": "ДПГ 21-10"},
                {"id": 333, "name": "ДПГ 21-12"}])

BUDGET = Diagnostic(code="KIR-L001", op_index=0,
                    message_ru="слишком много опов в программе")


class RefusalKeepsItsIdentity(unittest.TestCase):
    def test_the_original_code_survives(self):
        [event] = _events([AMBIGUOUS], [{"op": "create_door"}])
        self.assertEqual(event["diag_code"], "KIR-G102")

    def test_candidates_survive(self):
        [event] = _events([AMBIGUOUS], [{"op": "create_door"}])
        self.assertEqual([c["id"] for c in event["candidates"]],
                         [111, 222, 333])
        self.assertIn("ДПГ 21-9", [c["name"] for c in event["candidates"]])

    def test_the_contract_enum_is_not_widened(self):
        """`reject_code` — ЗАКРЫТЫЙ enum контракта: консьюмер
        (`coverage_queue.py`) ранжирует дыры покрытия по нему, и новое значение
        сломало бы ранжирование. Личность едет РЯДОМ, а не вместо."""
        [event] = _events([AMBIGUOUS], [{"op": "create_door"}])
        self.assertEqual(event["reject_code"], "VALIDATION_FAILED")
        self.assertIn(event["reject_code"],
                      {"UNSUPPORTED_KIND", "UNSUPPORTED_ACTION",
                       "UNSUPPORTED_PAIR", "SLOT_RESOLUTION_FAILED",
                       "VALIDATION_FAILED"})

    def test_a_correct_refusal_is_now_distinguishable_from_an_author_error(self):
        """Ровно то, ради чего всё: два события с одним контрактным кодом
        различаются по `diag_code`."""
        events = _events([AMBIGUOUS, BUDGET], [{"op": "create_door"}])
        codes = [e["diag_code"] for e in events]
        self.assertEqual(codes, ["KIR-G102", "KIR-L001"])
        self.assertEqual({e["reject_code"] for e in events},
                         {"VALIDATION_FAILED"})

    def test_absent_candidates_stay_absent(self):
        """Пустой список кандидатов не пишется: «их не было» и «поле забыли» —
        разные факты."""
        [event] = _events([BUDGET], [{"op": "create_door"}])
        self.assertNotIn("candidates", event)

    def test_candidates_are_capped_and_reduced_to_id_and_name(self):
        big = Diagnostic(
            code="KIR-G102", message_ru="pool: неоднозначен",
            op_index=0,
            candidates=[{"id": i, "name": f"t{i}", "family": "f",
                         "instances": i} for i in range(30)])
        [event] = _events([big], [{"op": "create_wall"}])
        self.assertEqual(len(event["candidates"]),
                         coverage_feed._MAX_CANDIDATES)
        self.assertEqual(set(event["candidates"][0]), {"id", "name"})

    def test_nearest_names_are_a_bare_string_list_and_survive(self):
        """У «имя не найдено» кандидаты приходят из `_nearest` ПЛОСКИМ списком
        строк, а не строками пула (`difflib.get_close_matches`). Две разные
        формы в одном поле — ровно тот шов, на котором этот проект ломается."""
        d = Diagnostic(code="KIR-G101", op_index=0, field_name="level",
                       got="Этаж 1", message_ru="levels: «Этаж 1» не найден",
                       candidates=["Этаж 01", "Этаж 1 (тех)", "Уровень 1"])
        [event] = _events([d], [{"op": "create_wall"}])
        self.assertEqual(event["diag_code"], "KIR-G101")
        self.assertEqual([c["name"] for c in event["candidates"]],
                         ["Этаж 01", "Этаж 1 (тех)", "Уровень 1"])

    def test_known_contract_codes_still_map(self):
        d = Diagnostic(code="KIR-G001", message_ru="неизвестный kind 'furniture'",
                       op_index=0, field_name="kind", got="furniture")
        [event] = _events([d], [{"op": "query_count"}])
        self.assertEqual(event["reject_code"], "UNSUPPORTED_KIND")
        self.assertEqual(event["diag_code"], "KIR-G001")


if __name__ == "__main__":
    unittest.main()
