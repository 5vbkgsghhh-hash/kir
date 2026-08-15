"""Манифест обязан говорить, из ЧЕГО состоит его ``failures``.

ЗАМЕР 13.08, ``len_ar_me_r24_v1`` (настоящее здание, 57 809 элементов, живое
чтение, 53 686 строк боковых индексов). Директор прочитал манифест и заказал
работу по колонке ``failures``:

    всего «отказов»              12 073   22.5% строк — заголовок манифеста
    ├─ аспекта нет               10 267   ПРАВИЛЬНЫЙ отрицательный ответ
    │    curtain not_curtain      9 715 — стена НЕ витражная, читатель прав
    ├─ не тот род на входе        1 710   фильтр ВЫЗЫВАЮЩЕГО, не читатель
    └─ настоящий срез                96   0.18% — только это наша работа

``curtain`` возглавляет манифест с 99.5% «отказа» и здоров на все сто.

И ЭТО СЛУЧИЛОСЬ ВТОРОЙ РАЗ. Первый — 29.07 на башне: ``curtain`` 14 343 при 19
настоящих срезах. Тогда завели ``SideFailureKind`` и полный словарь
``SIDE_FAILURE_KINDS``, провели их в ``run.json``, написали тест на то, что
неклассифицированных причин не бывает. Починили ПРИБОР — и не починили один из
его ВЫХОДОВ. Манифест остался с единственным словом, по нему и заказали работу
две недели спустя.

    Форма: класс дефекта закрывают у ИСТОЧНИКА и оставляют открытым у каждого
    ПОТРЕБИТЕЛЯ, который несёт ту же величину под тем же именем.

ЧЕГО ЭТИ ТЕСТЫ НЕ ПОКРЫВАЮТ, словами: правильность самой классификации (её
стережёт ``test_every_reason_is_classified`` у словаря) и то, что стадия
вообще отработала. Здесь проверяется ровно одно — что разбивка ДОЕХАЛА до
манифеста, замкнулась в сумму и не влезла в ключ сверки resume.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kukai.ir.decompile import pipeline as pipe
from kukai.ir.decompile.side_contract import SideFailure, SideFailureReason
from kukai.ir.decompile.tests.test_pipeline import FakePipelineBridge

#: Ровно две причины — «факты о модели». Список продублирован здесь НАМЕРЕННО,
#: а не импортирован: если кто-то переклассифицирует причину, этот тест обязан
#: об этом сказать, а импорт согласился бы молча.
DETERMINATIONS = (
    SideFailureReason.ASPECT_NOT_PRESENT,
    SideFailureReason.ELEMENT_KIND_MISMATCH,
)


class _Extraction:
    """Минимум, который читают ``_side_counts`` и ``_side_breakdown``."""

    def __init__(self, records: tuple, failures: tuple) -> None:
        self.records = records
        self.failures = failures


class ManifestSplitsRefusalFromAnswer(unittest.TestCase):

    def test_a_stage_that_only_answered_shows_zero_cuts(self) -> None:
        """КОНТРОЛЬ-PASS. Здоровая стадия: отказов много, срезов ноль.

        Это curtain с настоящего здания в миниатюре: 9 715 строк «стена не
        витражная». По ``failures`` стадия худшая в прогоне; по ``cuts`` —
        безупречная. Тест утверждает, что это РАЗНЫЕ числа в манифесте, а не
        одно.
        """
        extraction = _Extraction(
            records=(),
            failures=tuple(
                SideFailure(element_id=str(n), reason=reason.value,
                            typed_reason=reason)
                for n, reason in enumerate(DETERMINATIONS * 4)),
        )
        breakdown = pipe._side_breakdown(extraction, "curtain")
        self.assertEqual(8, breakdown["determinations"])
        self.assertEqual(0, breakdown["cuts"])
        self.assertEqual(0, breakdown["failures_untyped"])
        self.assertEqual(
            8, pipe._side_counts(extraction)["failures"],
            "заголовочное число обязано остаться прежним — меняется не оно, "
            "а то, что стоит рядом")

    def test_a_stage_that_gave_up_shows_cuts(self) -> None:
        """КОНТРОЛЬ-FAIL прибора: срез обязан быть ОТЛИЧИМ от ответа.

        Прибор, который на срезах печатает то же, что на ответах, не
        измеряет ни одного из них. Здесь ровно те 96 строк с настоящего
        здания: у ограждения не задан базовый уровень, профиль с разрывным
        контуром, зависимых эскизов ровно два.
        """
        extraction = _Extraction(
            records=(),
            failures=(
                SideFailure(
                    element_id="1", reason="railing base level unavailable",
                    typed_reason=SideFailureReason.READ_FAILED),
                SideFailure(
                    element_id="2", reason="disjoint/nested exterior",
                    typed_reason=(
                        SideFailureReason.PROFILE_TOPOLOGY_UNSUPPORTED)),
                SideFailure(
                    element_id="3", reason="not_curtain",
                    typed_reason=SideFailureReason.ASPECT_NOT_PRESENT),
            ),
        )
        breakdown = pipe._side_breakdown(extraction, "sketch")
        self.assertEqual(2, breakdown["cuts"])
        self.assertEqual(1, breakdown["determinations"])

    def test_the_breakdown_closes_on_a_real_run(self) -> None:
        """Сумма разбивки равна заголовку — на КАЖДОЙ стадии прогона.

        Незамкнутая сумма — это причина, молча выпавшая из обеих корзин;
        ровно так ``not_curtain`` и жил до 29.07.
        """
        with TemporaryDirectory() as tmp:
            result = asyncio.run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="manifest-breakdown-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            manifest = json.loads(
                (Path(tmp) / pipe._SIDE_MANIFEST_NAME).read_text("utf-8"))
            stages = manifest["stages"]
            self.assertTrue(stages, "прогон не записал ни одной стадии")
            for stage, row in stages.items():
                for field in ("cuts", "determinations", "failures_untyped"):
                    self.assertIn(
                        field, row, f"стадия {stage} без поля {field}")
                self.assertEqual(
                    row["failures"],
                    row["cuts"] + row["determinations"]
                    + row["failures_untyped"],
                    f"разбивка стадии {stage} не сходится с её заголовком")

    def test_the_breakdown_is_not_part_of_the_resume_key(self) -> None:
        """Разбивка НЕ участвует в сверке — иначе архив стал бы негодным.

        ``_side_counts`` — ключ, по которому resume решает, можно ли взять
        уже лежащий индекс. Любое новое поле в нём объявляет НЕПРИГОДНЫМ
        каждый разбор, снятый раньше: их манифесты этого поля не несут, и
        4.1 ГБ архива пришлось бы перечитывать ради формы записи.

        Этот тест — единственное, что стоит между удобной правкой
        («положу разбивку прямо в ``_side_counts``, там же логичнее») и
        молчаливым обесцениванием всех прошлых прогонов.
        """
        extraction = _Extraction(
            records=("a", "b"),
            failures=(SideFailure(
                element_id="1", reason="not_curtain",
                typed_reason=SideFailureReason.ASPECT_NOT_PRESENT),))
        self.assertEqual(
            {"rows", "failures"}, set(pipe._side_counts(extraction)),
            "ключ сверки resume расширен — старые манифесты перестанут "
            "совпадать, и архив разборов придётся перечитывать")

        # И вторая половина того же утверждения: манифест БЕЗ разбивки
        # (снятый до этой волны) обязан по-прежнему приниматься.
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / pipe._SIDE_MANIFEST_NAME).write_text(json.dumps({
                "schema_version": pipe._SIDE_MANIFEST_VERSION,
                "stages": {"curtain": {
                    "rows": 2, "failures": 1, "source": None}},
            }), encoding="utf-8")
            self.assertTrue(
                pipe._side_counts_agree(directory, "curtain", extraction),
                "манифест, снятый до разбивки, перестал переиспользоваться")


if __name__ == "__main__":
    unittest.main()
