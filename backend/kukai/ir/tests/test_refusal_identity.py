"""ОТКАЗ ОБЯЗАН БЫТЬ ОПОЗНАВАЕМ ИЗ ОДНОГО КОРПУСА.

ЧТО ИЗМЕРЕНО (09.08.2026, перечислением ВСЕХ ключей ВСЕХ 1306 строк
`backend/data/telemetry/kir_witness.jsonl`): ни одна строка не несёт поля с
сообщением отказа — никакого. Следствие, замеренное там же: из 204 красных
строк 165 неприписываемы ПО ПОСТРОЕНИЮ — 79 `KIR-X999`, 41 `unconfirmed`,
38 `KIR-X003`, 7 разноимённых без идентификаторов.

Цена этого была заплачена в тот же день: разбор 12 отказов `create_door` дал
«компилятор 5 / Revit 11» — деление, полученное чтением сообщений, которые
жили ВНЕ корпуса. Более точный замер показал, что таким делением нельзя было
заниматься вовсе: корпус причин не нёс, значит это не измерение, а пересказ.

Здесь стоят опровергающие тесты на обе половины починки:

  * ПРОИЗВОДИТЕЛЬ — `witness_feed` перестал выбрасывать то, что диагностика уже
    несла (код, адрес, поле, сообщение, слова рантайма), а неизвестная причина
    называется вслух, а не оставляется пробелом;
  * ТАКСОНОМИЯ — `KIR-X003` перестал быть двумя мирами сразу; отказ рантайма
    получил собственный `KIR-X009`, и разделение НЕ ослабило знание об откате;
  * ЗАКОН «ОТСУТСТВУЮЩЕЕ ОСТАЁТСЯ ОТСУТСТВУЮЩИМ» — успешная программа обязана
    писать ПОБАЙТНО ту же строку с тем же дайджестом, что и до правки.

Приписывание на стороне потребителя проверяется в `tests/test_live_op_rates.py`
(там же — отрицательный контроль на отсутствие обратной засыпки старых строк).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

from kukai.ir import coverage_feed, serving, witness_feed
from kukai.ir.diag import Diagnostic

_PROGRAM = {"ir_version": "1.0", "ops": [
    {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [4000, 0],
     "height_mm": 3000},
    {"op": "create_door", "id": "D1", "host": {"by": "ref", "value": "W1"},
     "offset_mm": 2000}]}


def _record(**kwargs) -> dict:
    """Одна запись через ПРОДОВЫЙ путь, прочитанная обратно."""
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "kir_witness.jsonl")
        previous = os.environ.get(witness_feed._ENV)
        os.environ[witness_feed._ENV] = path
        try:
            witness_feed.record_witness(**kwargs)
            with open(path, encoding="utf-8") as handle:
                return json.loads(handle.read().strip())
        finally:
            if previous is None:
                os.environ.pop(witness_feed._ENV, None)
            else:
                os.environ[witness_feed._ENV] = previous


def _runtime_diag(message: str, marker: str = "stale_or_failed") -> dict:
    return serving._translate_runtime(
        {"error": marker,
         "layer": {"error": marker, "op_id": "D1", "message": message}})


class GreenRowStaysByteIdentical(unittest.TestCase):
    """ЗАКОН: отсутствующее остаётся отсутствующим.

    Успешная программа не отказывала, поэтому у неё нет ни личности отказа, ни
    названного незнания. Обе цифры ниже сняты сравнением с `witness_feed` на
    `c3e019f6` (версия ДО этой правки) на одной и той же программе: канонические
    байты записи и её контрольная сумма от одного и того же предыдущего звена
    совпали. Пин стоит здесь, чтобы следующее поле «заодно» щёлкнуло храповиком.

    ГРАНИЦА СПИСКА НИЖЕ, названная 13.08.2026, чтобы его не прочли шире, чем
    он есть: фикстура НЕ называет `txn_isolation`, поэтому поля в строке нет
    (не назвали — не записано). **Живая строка записи его несёт**, и перечень
    из десяти имён здесь — утверждение о ЗАКОНЕ «нет отказа — нет личности
    отказа», а не описание живой строки. Форма живой строки пинится отдельно,
    в `test_witness_readback_facts.py`; дайджесты ниже трогать нельзя — они
    сняты сравнением с `c3e019f6` и перепин уничтожил бы сам замер.
    """

    def setUp(self) -> None:
        self.row = _record(
            program=_PROGRAM, family="write", revit_version="2026", ok=True,
            witness={"geometry_ok": True, "semantic_ok": True,
                     "topology_ok": True},
            duration_ms=250.0,
            outcome={"execution": "committed", "witness": "satisfied",
                     "acceptance": "accepted"},
            result_payload={"W1": {"id": "1001"}, "D1": {"id": "1002"}})
        self.body = {k: v for k, v in self.row.items()
                     if k not in ("ts", "prev_checksum", "checksum")}

    def test_no_refusal_field_appears_on_a_successful_program(self):
        self.assertEqual(
            sorted(self.body),
            ["duration_ms", "family", "ok", "op_outcomes", "ops", "outcome",
             "revit_version", "source", "v", "witness"])

    def test_the_canonical_bytes_are_the_ones_measured_before_the_change(self):
        blob = witness_feed._canonical(self.body)
        self.assertEqual(
            hashlib.sha256(blob).hexdigest(),
            "74d9518637e04a23b7c22d5f9823af71c52897172a7e103ef513b33196eef6d1")

    def test_the_row_digest_is_unmoved(self):
        self.assertEqual(
            witness_feed._row_checksum("0" * 64, self.body),
            "337f019286bfe9e0eea78ba04aa5b88eb72f9f9bbb6e542851fabf19ed0672ba")


class TheRowCarriesTheRefusalsIdentity(unittest.TestCase):
    """То, что диагностика УЖЕ несла и что телеметрия выбрасывала."""

    def setUp(self) -> None:
        self.diag = _runtime_diag("NewFamilyInstance (дверь) вернул null")
        self.row = _record(
            program=_PROGRAM, family="write", revit_version="2026", ok=False,
            witness=serving._derive_witness(False, "write", self.diag),
            duration_ms=412.5,
            diag_code=self.diag["code"], diag_op_id=self.diag.get("op_id"),
            diag_field=self.diag.get("field_name"),
            diag_message=self.diag.get("message_ru"),
            diag_detail=self.diag.get("detail"),
            outcome={"execution": "rolled_back", "witness": "incomplete",
                     "acceptance": "not_applicable"})

    def test_the_code_and_the_address_travel_together(self):
        self.assertEqual(self.row["diag_code"], "KIR-X009")
        self.assertEqual(self.row["diag_op_id"], "D1")

    def test_our_own_words_are_persisted(self):
        self.assertIn("отказан в рантайме", self.row["diag_message"])

    def test_the_runtimes_own_words_are_persisted(self):
        """Единственный различающий признак X999/X003 — и ровно его корпус не
        нёс. Без него причина 117 живых строк невосстановима навсегда."""
        self.assertIn("NewFamilyInstance", self.row["diag_detail"])

    def test_the_cause_says_where_it_lives(self):
        self.assertEqual(self.row["refusal_cause"], "diagnostic")

    def test_free_text_obeys_the_existing_size_discipline(self):
        """Потолок не новый: столько же корпус хранит у каждого нарушения."""
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=1.0,
                      diag_code="KIR-X999", diag_detail="ы" * 5000,
                      diag_message="я" * 5000)
        self.assertEqual(len(row["diag_detail"]), witness_feed._MAX_TEXT)
        self.assertEqual(len(row["diag_message"]), witness_feed._MAX_TEXT)

    def test_an_empty_message_is_absence_not_an_empty_field(self):
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=1.0,
                      diag_code="KIR-X999", diag_message="   ", diag_field=None)
        self.assertNotIn("diag_message", row)
        self.assertNotIn("diag_field", row)


class AnUnknownCauseIsNamedNotOmitted(unittest.TestCase):
    """«Причины не знаю» и «причину не записали» обязаны выглядеть по-разному.

    Это та же граница, что и «стадия отказала» против «стадия не заговорила»
    (§18.2): отсутствующий индекс и пустой индекс — разные факты.
    """

    def test_a_red_row_without_a_diagnostic_says_so(self):
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=88.0)
        self.assertEqual(row["refusal_cause"], "unknown")

    def test_violations_are_named_as_the_place_of_the_cause(self):
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=88.0,
                      violations=["D1: mirrored state mismatch (semantic)"])
        self.assertEqual(row["refusal_cause"], "violations")

    def test_a_committed_program_refused_by_acceptance_says_acceptance(self):
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=88.0,
                      outcome={"execution": "committed", "witness": "satisfied",
                               "acceptance": "inconclusive"})
        self.assertEqual(row["refusal_cause"], "acceptance")

    def test_a_green_row_has_no_such_field_at_all(self):
        row = _record(program=_PROGRAM, family="query", revit_version="2026",
                      ok=True, witness={"read_only": True}, duration_ms=12.0)
        self.assertNotIn("refusal_cause", row)


class OneCodeIsOneWorld(unittest.TestCase):
    """`KIR-X003` покрывал ДВА мира, и различал их только текст.

    `__Refuse` помечает всякий типизированный отказ эмиттера одним транспортным
    маркером `stale_or_failed`, поэтому «элемент исчез между grounding и
    исполнением» и «Revit отказался это делать» ехали под одним кодом. Читатель
    корпуса видит КОД, а не прозу, — значит починка текста (27.07) вылечила
    сообщение и не вылечила таксономию.
    """

    def test_genuine_drift_keeps_its_own_code(self):
        diag = _runtime_diag(
            "base_level: уровень не найден (модель изменилась после grounding)")
        self.assertEqual(diag["code"], "KIR-X003")
        self.assertIn("исчез", diag["message_ru"])

    def test_a_runtime_refusal_is_no_longer_called_drift(self):
        diag = _runtime_diag("NewElbowFitting: failed to insert elbow")
        self.assertEqual(diag["code"], "KIR-X009")
        self.assertNotIn("исчез", diag["message_ru"])

    def test_the_wrong_type_guard_is_not_drift_either(self):
        """Ветка `_level_expr`, которая САМА говорит, что причину не определила:
        она не имеет права ехать под кодом «модель дрейфанула»."""
        diag = _runtime_diag(
            "id уровня резолвится не в Level, а в Wall — причина (дрейф модели "
            "или неверный id) не определена рантаймом")
        self.assertEqual(diag["code"], "KIR-X009")

    def test_both_worlds_still_carry_the_runtime_text(self):
        for message in ("уровень не найден (модель изменилась после grounding)",
                        "NewFamilyInstance (дверь) вернул null"):
            self.assertIn("detail", _runtime_diag(message))

    def test_splitting_the_code_did_not_weaken_the_rollback_proof(self):
        """ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ НА САМУ ПРАВКУ. Обе формы приходят из
        `refuse_stmt`, а он рендерит RollBack/throw ДО коммита — значит откат
        они доказывают поровну. Выпади X009 из списка, разделение кода
        превратило бы доказанный откат в `unconfirmed`, то есть УХУДШИЛО бы
        знание об эффекте ради красоты таксономии."""
        self.assertIn("KIR-X003", serving._ROLLBACK_PROVEN_CODES)
        self.assertIn("KIR-X009", serving._ROLLBACK_PROVEN_CODES)
        self.assertIn("KIR-X004", serving._ROLLBACK_PROVEN_CODES)


class PreEffectRefusalKeepsItsAddress(unittest.TestCase):
    """Отказ ДО исполнения живёт в своём корпусе (`kir_rejections.jsonl`), и
    там та же дыра была уже: `op_requested` называет ИМЯ операции, а `op_id` и
    `field_name` диагностика несла и фид их выбрасывал."""

    def _events(self, diag: Diagnostic) -> list:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "kir_rejections.jsonl")
            previous = os.environ.get(coverage_feed._ENV)
            os.environ[coverage_feed._ENV] = path
            try:
                coverage_feed.record_rejections(
                    [diag], [{"op": "create_door", "id": "D1"}])
                with open(path, encoding="utf-8") as handle:
                    return [json.loads(line) for line in handle if line.strip()]
            finally:
                if previous is None:
                    os.environ.pop(coverage_feed._ENV, None)
                else:
                    os.environ[coverage_feed._ENV] = previous

    def test_the_instance_and_the_field_survive(self):
        event, = self._events(Diagnostic(
            code="KIR-G102", message_ru="тип двери неоднозначен",
            op_index=0, op_id="D1", field_name="symbol"))
        self.assertEqual(event["op_id"], "D1")
        self.assertEqual(event["field_name"], "symbol")
        self.assertEqual(event["diag_code"], "KIR-G102")

    def test_absence_stays_absence(self):
        event, = self._events(Diagnostic(
            code="KIR-P004", message_ru="ir_version не поддержан"))
        self.assertNotIn("op_id", event)
        self.assertNotIn("field_name", event)


if __name__ == "__main__":
    unittest.main()
