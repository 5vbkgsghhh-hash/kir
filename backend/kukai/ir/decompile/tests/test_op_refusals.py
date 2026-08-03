# -*- coding: utf-8 -*-
"""Задача №25: пооперационный отказ внутри ЗАКОММИЧЕННОГО чанка.

Повод — пересборка №11 (v18): 122 линии разрезки витража ожидались, создано
НОЛЬ, и 113 из них сидели в чанках со статусом ``Committed``. Прогон
отчитался успехом, линии ушли в missing, причина не сохранилась нигде:
квитанция несла только ``element_ids``.

При этом причина приходила наружу с самого начала. В ``isolation="per_op"``
эмиссия кладёт её в тот же ``result``, откуда берутся id::

    __rf["refused"] = <текст>;  __rf["refused_op_id"] = <op_id>;
    __results[oid] = __rf;

Поэтому здесь не проверяется «умеет ли Revit сказать» — проверяется, что мы
перестали выбрасывать сказанное, и что закон переписи ловит оп без исхода.

VERBATIM: полезная нагрузка чанка 6 ниже — настоящая форма выдачи (198 стен
создано, 37 линий отказало, 15 ячеек сменили тип на месте), 250 опов.
"""
from __future__ import annotations

import unittest

from kukai.ir.contracts import CommitReceipt, ContractSchemaError, RunId
from kukai.ir.serving import collect_op_refusals, count_ops_without_element

RUN_ID = RunId("d51b64480a14a8b4")
PROGRAM_ID = "01745acbe44a476787c20eed37266dc55772085fa1c0b080d7ae1b4f5ecf4d5c"
# Дословный текст отказа, который эмиссия строит для линии разрезки, когда
# строгий блок штампа прогона (только путь A5) бросает на отсутствующем
# параметре Comments.
LINE_REFUSAL = (
    "линия разрезки не принимает штамп прогона (A5 stamp write failed: "
    "A5 stamp parameter missing) — созданный, но непомеченный элемент "
    "сломал бы сверку пересборки")


def chunk6_payload(walls=198, lines=37, panels=15):
    """Форма выдачи чанка 6 прогона №11: стены + отказавшие линии + ячейки."""
    result = {}
    for index in range(walls):
        result[f"w{index}"] = {"id": str(11472000 + index), "created": True}
    for index in range(lines):
        result[f"g{index}"] = {"refused": LINE_REFUSAL,
                               "refused_op_id": f"g{index}"}
    for index in range(panels):
        result[f"p{index}"] = {"id": str(9000000 + index), "created": False}
    return {"ok": True, "result": result}


def chunk6_program(walls=198, lines=37, panels=15):
    ops = [{"op": "create_wall", "id": f"w{i}"} for i in range(walls)]
    ops += [{"op": "create_curtain_grid_line", "id": f"g{i}",
             "host": {"by": "ref", "value": f"w{i}"}} for i in range(lines)]
    ops += [{"op": "set_curtain_panel", "id": f"p{i}",
             "host": {"by": "ref", "value": f"w{i}"}} for i in range(panels)]
    return {"ir_version": "1.0", "ops": ops}


def receipt(**over):
    base = dict(
        run_id=RUN_ID, operation="rebuild", element_ids=(),
        bridge_error=False, commit_confirmed=True, commit_status="Committed",
        program_id=PROGRAM_ID, document_revision="1:a:b")
    base.update(over)
    return CommitReceipt(**base)


class HarvestingRefusals(unittest.TestCase):

    def test_01_refusals_are_read_from_the_same_result_map(self):
        """Отказы поднимаются оттуда же, откуда id — на живой форме чанка 6."""
        rows = collect_op_refusals(chunk6_payload(), chunk6_program())
        self.assertEqual(len(rows), 37)
        first = rows[0]
        self.assertEqual(first["op_name"], "create_curtain_grid_line")
        self.assertEqual(first["intent"], {"by": "ref", "value": "w0"})
        # Причина ДОСЛОВНО: именно текст назвал виновника в разборе чанка 9.
        self.assertEqual(first["reason"], LINE_REFUSAL)
        self.assertIn("штамп прогона", first["reason"])
        # Порядок детерминирован — квитанция идёт в журнал.
        self.assertEqual([r["op_id"] for r in rows],
                         sorted(r["op_id"] for r in rows))

    def test_02_no_element_counts_only_explicit_created_false(self):
        """`created:false` — семантика; строка без id и без отказа — НЕ она."""
        self.assertEqual(count_ops_without_element(chunk6_payload()), 15)
        silent = {"ok": True, "result": {"x": {"op": "create_wall"}}}
        self.assertEqual(count_ops_without_element(silent), 0)

    def test_03_the_chunk_balances_end_to_end(self):
        """198 создано + 37 отказало + 15 без элемента == 250 опов."""
        payload, program = chunk6_payload(), chunk6_program()
        rows = collect_op_refusals(payload, program)
        created = [v["id"] for v in payload["result"].values()
                   if v.get("id") and v.get("created") is True]
        built = receipt(element_ids=tuple(created), op_refusals=rows,
                        ops_total=len(program["ops"]),
                        ops_no_element=count_ops_without_element(payload))
        self.assertEqual(len(built.element_ids), 198)
        self.assertEqual(len(built.op_refusals), 37)
        self.assertEqual(built.ops_no_element, 15)
        self.assertEqual(built.ops_total, 250)
        out = built.to_dict()
        self.assertEqual(out["schema_version"], "a5-commit-receipt/3")
        self.assertEqual(out["ops_refused"], 37)
        self.assertEqual(
            CommitReceipt.from_dict(out).op_refusals, built.op_refusals)


class CensusLaw(unittest.TestCase):

    def test_04_an_op_without_an_outcome_is_refused(self):
        """ОПРОВЕРГАЮЩИЙ: квитанция с расхождением обязана НЕ построиться.

        Это и есть класс «молча не создано»: 250 опов в плане, 249 исходов.
        """
        with self.assertRaises(ContractSchemaError) as caught:
            receipt(element_ids=("1", "2"), ops_total=250, ops_no_element=0)
        self.assertIn("не сходятся", str(caught.exception))

    def test_05_legacy_receipts_stay_readable(self):
        """ops_total=0 выключает закон: журналы №9-№11 обязаны реплеиться."""
        legacy = receipt(element_ids=("1", "2")).to_dict()
        self.assertNotIn("ops_total", legacy)
        self.assertEqual(len(CommitReceipt.from_dict(legacy).element_ids), 2)
        old = dict(legacy, schema_version="a5-commit-receipt/2")
        self.assertEqual(len(CommitReceipt.from_dict(old).element_ids), 2)

    def test_06_law_assumes_one_element_per_op(self):
        """ДОПУЩЕНИЕ, ЗАФИКСИРОВАННОЕ НАМЕРЕННО: один оп — не более одного id.

        Закон приравнивает ЧИСЛО СОЗДАННЫХ ID к числу успешных опов. Сегодня
        в пересборке это так (ретро-баланс v18 сошёлся на всех закоммиченных
        чанках), но это свойство нынешнего набора опов, а не закон природы:
        многоэлементный оп (move_elements с набором целей уже рядом) даст
        БОЛЬШЕ id, чем опов, и квитанция перестанет строиться.

        Тест существует, чтобы этот день был ОСОЗНАННЫМ КРАСНЫМ с понятным
        именем, а не загадкой в живом прогоне. Автору многоэлементного опа:
        считать закон по ОПАМ (нести ops_created в квитанции), а НЕ ослаблять
        сравнение — иначе вместе с допущением уедет и весь класс «молча не
        создано», ради которого закон и заведён.
        """
        # Один оп, два созданных элемента — сегодня это уже не сходится.
        with self.assertRaises(ContractSchemaError):
            receipt(element_ids=("1", "2"), ops_total=1, ops_no_element=0)
        # И ровно так же не сойдётся честный однооповый случай.
        ok = receipt(element_ids=("1",), ops_total=1, ops_no_element=0)
        self.assertEqual(ok.ops_total, 1)


if __name__ == "__main__":
    unittest.main()
