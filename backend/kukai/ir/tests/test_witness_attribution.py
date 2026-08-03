"""Измеритель обязан уметь назвать ОПЕРАЦИЮ, которая отказала.

31.07: разбор корпуса свидетелей упёрся в собственный инструмент. Корпус
пишет три вещи по отдельности — список опов (`ops`), пооперационные исходы
(`op_outcomes`) и нарушения постусловий (`violations`), — но `ops` держит
только ИМЯ операции, а исходы и нарушения адресуются её ИДЕНТИФИКАТОРОМ.
Связать одно с другим нечем.

Следствие замерено, а не предположено: у программы `create_wall` +
`create_door`, где отказала дверь, единственный доступный способ посчитать
частоту — приписать провал ОБЕИМ операциям. Так и считалось: `create_wall`
выходил 64.2%, хотя стена в тех прогонах строилась. Число, полученное таким
измерителем, нельзя ни публиковать, ни использовать как цель.

Это не про красоту записи. Это про то, что четыре из пяти живых провалов
базовых опов — X004 с поимённым списком нарушений, и вся эта улика лежит в
файле НЕПРИВЯЗАННОЙ.

Второе: усечение. `_MAX_VIOLATIONS` режет список молча — двадцатибалочная
программа с двадцатью нарушениями оставит в корпусе десять и ни следа о том,
что были ещё. Молчаливое усечение читается как «столько и было» — ровно тот
род тишины, против которого построена вся система.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from kukai.ir import witness_feed


def _read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


class ViolationIsAttributableToAnOp(unittest.TestCase):
    """Живой образец 21.07: стена построилась, дверь отказала."""

    PROGRAM = {"ops": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "height_mm": 3000},
        {"op": "create_door", "id": "PD", "host": {"by": "ref", "value": "W1"},
         "offset_mm": 3000},
    ]}
    VIOLATIONS = ["PD: mirrored state mismatch (semantic)",
                  "PD: facing flip state mismatch (semantic)"]

    def _record(self, path, **over):
        kw = dict(program=self.PROGRAM, family="write", revit_version="2026",
                  ok=False, witness={"geometry_ok": True, "semantic_ok": False,
                                     "topology_ok": True, "committed": False},
                  duration_ms=812.0, diag_code="KIR-X004",
                  violations=list(self.VIOLATIONS))
        kw.update(over)
        with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
            witness_feed.record_witness(**kw)

    def test_ops_carry_the_id_the_violation_names(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            self._record(path)
            row = _read(path)[0]
            by_id = {o.get("id"): o.get("op") for o in row["ops"]}
            self.assertEqual(by_id.get("W1"), "create_wall")
            self.assertEqual(by_id.get("PD"), "create_door")

    def test_failing_op_is_nameable_from_the_row_alone(self):
        """Ради этого всё и делается: по одной строке корпуса сказать, что
        отказала ИМЕННО дверь, а стена — нет."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            self._record(path)
            row = _read(path)[0]
            by_id = {o.get("id"): o.get("op") for o in row["ops"]}
            blamed = {by_id[v.split(":", 1)[0].strip()]
                      for v in row["violations"]
                      if v.split(":", 1)[0].strip() in by_id}
            self.assertEqual(blamed, {"create_door"})
            self.assertNotIn("create_wall", blamed)

    def test_id_does_not_change_the_skeleton_hash(self):
        """Скелет остаётся стабильным к переименованию — id живёт РЯДОМ с
        ним, а не внутри."""
        a = dict(self.PROGRAM["ops"][0])
        b = dict(a, id="совсем-другое-имя")
        self.assertEqual(witness_feed.op_skeleton_hash(a),
                         witness_feed.op_skeleton_hash(b))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            self._record(path)
            row = _read(path)[0]
            self.assertNotIn("6000", json.dumps(row["ops"], ensure_ascii=False))

    def test_missing_id_is_recorded_as_absent_not_invented(self):
        prog = {"ops": [{"op": "create_wall", "p0_mm": [0, 0]}]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            self._record(path, program=prog, violations=None)
            row = _read(path)[0]
            self.assertEqual(row["ops"][0]["op"], "create_wall")
            self.assertIsNone(row["ops"][0].get("id"))


class TruncationIsNamed(unittest.TestCase):
    """Двадцатибалочная программа 27.07: двадцать нарушений, десять в файле."""

    def test_violation_overflow_is_counted(self):
        n = witness_feed._MAX_VIOLATIONS + 7
        prog = {"ops": [{"op": "create_beam", "id": f"b{i}"} for i in range(n)]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=prog, family="write", revit_version="2023",
                    ok=False, witness=None, duration_ms=5.0,
                    diag_code="KIR-X004",
                    violations=[f"b{i}: level binding mismatch (topology)"
                                for i in range(n)])
            row = _read(path)[0]
            self.assertEqual(len(row["violations"]),
                             witness_feed._MAX_VIOLATIONS)
            self.assertEqual(row.get("violations_truncated"), 7)

    def test_no_overflow_no_counter(self):
        prog = {"ops": [{"op": "create_beam", "id": "b0"}]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=prog, family="write", revit_version="2023",
                    ok=False, witness=None, duration_ms=5.0,
                    diag_code="KIR-X004",
                    violations=["b0: level binding mismatch (topology)"])
            row = _read(path)[0]
            self.assertNotIn("violations_truncated", row)

    def test_a_whole_materialiser_chunk_fits_in_one_record(self):
        """Потолок записи обязан покрывать САМУЮ БОЛЬШУЮ программу, какую
        система умеет исполнить, — иначе корпус меряет треть работы.

        Замерено 31.07 живым кругом по образцу Snowdon: 26 чанков, 6344
        исполнения операций, в журнал попало 833. Остальные 5511 честно
        отмечены усечением — и ровно поэтому `create_duct` не добрал
        свидетельств (34 записанных вместо 181 исполненного) и не перешагнул
        95%, хотя не отказал НИ РАЗУ. Компилятор отработал безупречно;
        недобрал измеритель.

        Планка взята не на глаз: `MAX_VALIDATED_OPS` — потолок программы
        после раскрытия макросов, то есть по построению ничто исполнимое
        больше не бывает. Цена замерена: строка на 250 операций весит ~25 КБ,
        весь круг ~640 КБ при корпусе в мегабайт."""
        from kukai.ir.compiler import MAX_VALIDATED_OPS
        self.assertGreaterEqual(witness_feed._MAX_OPS_PER_RECORD,
                                MAX_VALIDATED_OPS)
        n = 250          # chunk_target материализатора
        prog = {"ops": [{"op": "create_pipe", "id": f"p{i}"} for i in range(n)]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=prog, family="write", revit_version="2026",
                    ok=True, witness={"geometry_ok": True}, duration_ms=14200.0,
                    result_payload={f"p{i}": {"id": str(i)} for i in range(n)})
            row = _read(path)[0]
            self.assertEqual(len(row["ops"]), n)
            self.assertNotIn("ops_truncated", row)
            self.assertEqual(len(row["op_outcomes"]), n)
            self.assertNotIn("op_outcomes_truncated", row)

    def test_outcome_overflow_is_counted(self):
        n = witness_feed._MAX_OPS_PER_RECORD + 3
        prog = {"ops": [{"op": "create_pipe", "id": f"p{i}"} for i in range(n)]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=prog, family="write", revit_version="2026",
                    ok=True, witness={"geometry_ok": True}, duration_ms=5.0,
                    result_payload={f"p{i}": {"id": str(i)} for i in range(n)})
            row = _read(path)[0]
            self.assertEqual(len(row["op_outcomes"]),
                             witness_feed._MAX_OPS_PER_RECORD)
            self.assertEqual(row.get("op_outcomes_truncated"), 3)


if __name__ == "__main__":
    unittest.main()
