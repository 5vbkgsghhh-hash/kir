"""НЕЯВНЫЙ КОНТРАКТ БОКОВОЙ СТАДИИ — теперь явный и проверяемый.

ЖИВОЙ СЛУЧАЙ 30.07, из-за которого файл существует. Новая стадия оформления
прошла все свои 30 тестов, её C# отработал на мосту идеально (два примечания,
378 мс, текст/вид/имя вида/координаты/тип — всё на месте), а полный прогон по
образцу Snowdon Towers упал через полторы минуты с
``side_stage_count_mismatch: annotation: запрошено 26, без строки и без
квитанции 26``.

Причина — ОДНО ИМЯ ПОЛЯ. Сверщик §18.2 спрашивает у результата пачки
``records`` и ``failures``; новая стадия называла своё поле ``text_notes``,
сверщик увидел ноль отчётов и честно уронил прогон. Закон переписи сработал
ровно как задумано, но вывод из его сообщения («стадия потеряла элементы»)
указывал не туда, где был дефект.

Контракт был НЕЯВНЫМ: нигде не написано, что результат стадии обязан отвечать
на ``records``. Тесты ниже делают его явным для КАЖДОЙ зарегистрированной
стадии, чтобы следующая новая стадия падала здесь, а не на живой модели через
сорок минут чтения.
"""
from __future__ import annotations

import dataclasses
import unittest

from kukai.ir.decompile import pipeline as pipe
from kukai.ir.decompile.annotation_extract import (
    AnnotationExtraction,
    AnnotationFailure,
    TextNoteRecord,
)
from kukai.ir.decompile.curtain_extract import CurtainExtraction
from kukai.ir.decompile.curve_extract import CurveExtraction
from kukai.ir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
)
from kukai.ir.decompile.group_extract import GroupExtraction
from kukai.ir.decompile.geom_extract import GeometryExtraction
from kukai.ir.decompile.mep_system_extract import MepSystemExtraction
from kukai.ir.decompile.sketch_extract import ProfileExtraction
from kukai.ir.decompile.tag_extract import (
    TagExtraction,
    TagFailure,
    TagRecord,
)


#: Стадия -> тип её результата. Строка добавляется ВМЕСТЕ со стадией: стадия
#: без строки здесь — это стадия, чей контракт никто не проверил.
STAGE_RESULT_TYPES = {
    "curve": CurveExtraction,
    "sketch": ProfileExtraction,
    "curtain": CurtainExtraction,
    "family_placement": FamilyPlacementExtraction,
    "group": GroupExtraction,
    "annotation": AnnotationExtraction,
    "mep_system": MepSystemExtraction,
    "tag": TagExtraction,
    "geometry": GeometryExtraction,
}


class SideStageContractTests(unittest.TestCase):

    def test_every_registered_stage_has_a_declared_result_type(self) -> None:
        """Новая стадия обязана появиться в этом файле, иначе она непроверена."""
        registered = set(pipe._default_cs_builders())
        declared = set(STAGE_RESULT_TYPES)
        self.assertEqual(
            registered, declared,
            "стадии зарегистрированы, но их контракт не объявлен: "
            f"{sorted(registered - declared)}; объявлен, но не зарегистрирован: "
            f"{sorted(declared - registered)}")

    def test_every_stage_result_answers_to_the_reconciler(self) -> None:
        """``records`` и ``failures`` — имена, которыми спрашивает §18.2.

        Проверяется КЛАСС, а не экземпляр: у разных стадий разные обязательные
        аргументы конструктора, и тест про контракт не должен знать их формы.
        Имя считается доступным, если оно есть среди полей датакласса ИЛИ среди
        свойств класса — сверщику безразлично, чем оно реализовано.
        """
        for stage, result_type in STAGE_RESULT_TYPES.items():
            with self.subTest(stage=stage):
                names = {f.name for f in dataclasses.fields(result_type)}
                names |= {
                    name for name in dir(result_type)
                    if isinstance(getattr(result_type, name, None), property)}
                for attribute in ("records", "failures"):
                    self.assertIn(
                        attribute, names,
                        f"{stage}: результат стадии не отвечает на "
                        f"{attribute!r} — сверщик посчитает, что стадия не "
                        f"отчиталась НИ ЗА ОДИН запрошенный id")

    def test_every_stage_has_a_category_row_or_is_whole_model(self) -> None:
        """Стадия без категорий и не полномодельная не получит ни одного id."""
        whole_model = {"group"}
        for stage in pipe._default_cs_builders():
            with self.subTest(stage=stage):
                if stage in whole_model or stage in pipe._DYNAMIC_STAGE_IDS:
                    continue
                self.assertTrue(
                    pipe._STAGE_CATEGORIES.get(stage),
                    f"{stage}: нет строки в _STAGE_CATEGORIES — конвейер "
                    f"никогда не запросит для неё ни один id")


class AnnotationReconcilerTests(unittest.TestCase):
    """Тот самый случай, воспроизведённый наименьшим образом."""

    def test_a_read_note_counts_as_accounted(self) -> None:
        extraction = AnnotationExtraction(
            text_notes=(TextNoteRecord("26", "900", "вид", (1.0, 2.0), "т"),))
        self.assertEqual(list(pipe._accounted_ids(extraction)), ["26"])

    def test_a_refused_note_also_counts_as_accounted(self) -> None:
        """Квитанция — тоже отчёт: «не прочитали и вот почему» это не молчание."""
        extraction = AnnotationExtraction(
            failures=(AnnotationFailure("26", "нет вида", "aspect_not_present"),))
        self.assertEqual(list(pipe._accounted_ids(extraction)), ["26"])

    def test_silence_stays_silence(self) -> None:
        """Пустой результат на запрошенный id обязан остаться неотчитанным."""
        self.assertEqual(list(pipe._accounted_ids(AnnotationExtraction())), [])


class TagReconcilerTests(unittest.TestCase):
    """Та же проверка для стадии марок — ПЕРЕД живым прогоном, а не после.

    Волна оформления узнала про имя ``records`` через сорок минут чтения
    Snowdon. Стадия марок узнаёт про него здесь, и это единственная разница,
    ради которой файл существует.
    """

    def _record(self) -> TagRecord:
        return TagRecord(
            element_id="4300", owner_view_id="900", owner_view_name="вид",
            at_view_mm=(1.0, 2.0), tagged_element_id="512",
            tag_family="independent", leader=False, orientation="Horizontal")

    def test_a_read_tag_counts_as_accounted(self) -> None:
        extraction = TagExtraction(tags=(self._record(),))
        self.assertEqual(list(pipe._accounted_ids(extraction)), ["4300"])

    def test_a_refused_tag_also_counts_as_accounted(self) -> None:
        """Марка на элементе связи — квитанция, а не молчание и не догадка."""
        extraction = TagExtraction(
            failures=(TagFailure("4300", "linked host", "tag_target_not_local"),))
        self.assertEqual(list(pipe._accounted_ids(extraction)), ["4300"])

    def test_silence_stays_silence(self) -> None:
        self.assertEqual(list(pipe._accounted_ids(TagExtraction())), [])

    def test_the_stage_is_paged_not_whole_model(self) -> None:
        """У стадии есть строка категорий, значит id ей приедут."""
        self.assertEqual(pipe._STAGE_CATEGORIES["tag"],
                         __import__(
                             "kukai.ir.decompile.tag_extract",
                             fromlist=["TAG_CATEGORIES"]).TAG_CATEGORIES)

    def test_the_builder_is_bound_to_a_revit_version(self) -> None:
        """Стадия марок — единственная, чей C# зависит от версии.

        Без версии строитель обязан собраться (иначе перечисление стадий,
        которым проверяется контракт, упало бы), но версия обязана МЕНЯТЬ
        текст — иначе шов 2022 существует только на словах.
        """
        default = pipe._default_cs_builders()["tag"](["1"])
        old = pipe._default_cs_builders("2021")["tag"](["1"])
        new = pipe._default_cs_builders("2024")["tag"](["1"])
        self.assertNotEqual(old, new)
        self.assertEqual(default, new)


class SideStageGateCoverageTests(unittest.TestCase):
    """ВТОРОЙ неявный контракт стадии: её C# обязан собираться на ШЕСТИ версиях.

    ЖИВОЙ СЛУЧАЙ 30.07, из-за которого класс существует. Разбор 59-этажной
    башни на **Revit 2023** встал намертво и повторял по кругу, каждые 5-20
    секунд, один и тот же отказ:

        EXEC_PIPELINE declarative revit_ir/decompile_read TEMPLATE COMPILE
        FAILED (server bug): CS1503: Argument 1: cannot convert from 'long'
        to 'Autodesk.Revit.DB.BuiltInParameter'   bridge_roundtrips=0

    До Revit не доехало НИЧЕГО. Шестиверсионные ворота
    (``kukai.ir.gate_runner``) компилировали ЧЕТЫРЕ боковые стадии из девяти:
    ``family_placement`` / ``group`` / ``curtain`` / ``sketch``. Три стадии,
    заведённые 30-31.07 (аннотации, системы MEP, марки), не проходили ворота
    НИ РАЗУ и доказывались живьём на публичном образце Snowdon — а он R2026.
    Конструкция, законная в 2026 и незаконная в 2023, уехала незамеченной.

    Сестринский тест выше требует, чтобы у стадии был ОБЪЯВЛЕН контракт
    результата. Этот требует, чтобы у неё был ОБЪЯВЛЕН вход в ворота: реестр
    конвейера и реестр ворот сверяются по множеству имён, и разойтись молча
    они больше не могут ни в одну сторону.
    """

    def _gate_names(self, version: str = "2026") -> set[str]:
        from kukai.ir import gate_runner
        return set(gate_runner.side_stage_gate_bodies(version))

    def test_every_registered_stage_is_compiled_by_the_six_version_gate(
        self,
    ) -> None:
        from kukai.ir import gate_runner
        registered = set(pipe._default_cs_builders())
        expected = registered | set(gate_runner.UNREGISTERED_GATE_STAGES)
        self.assertEqual(
            self._gate_names(), expected,
            "стадия зарегистрирована, но ворота её не компилируют: "
            f"{sorted(registered - self._gate_names())}; "
            "ворота компилируют незарегистрированную стадию, не объявленную "
            "в UNREGISTERED_GATE_STAGES: "
            f"{sorted(self._gate_names() - expected)}")

    def test_the_gate_emits_per_version_not_once(self) -> None:
        """Ворота обязаны эмитировать ПОД ВЕРСИЮ, а не слать один текст шесть раз.

        У марок C# зависит от версии по построению (шов ``TaggedLocalElementId``
        / ``GetTaggedLocalElementIds`` на 2022). Ворота, эмитирующие один раз,
        проверяли бы одну поверхность шесть раз — ровно тот дефект, который
        ``tools/compile_gate_offline.py`` уже описал в своём докстринге.
        """
        from kukai.ir import gate_runner
        self.assertNotEqual(
            gate_runner.side_stage_gate_bodies("2021")["tag"],
            gate_runner.side_stage_gate_bodies("2024")["tag"])

    def test_the_gate_body_is_the_body_the_pipeline_ships(self) -> None:
        """Ворота компилируют ТОТ ЖЕ текст, который поедет в модель.

        Не «похожий»: реестр конвейера — единственный источник строителей, и
        ворота обязаны звать его, а не собственный список импортов, который
        разошёлся бы с ним при первой же правке.
        """
        from kukai.ir import gate_runner
        for stage, builder in pipe._default_cs_builders("2023").items():
            with self.subTest(stage=stage):
                self.assertEqual(
                    gate_runner.side_stage_gate_bodies("2023")[stage],
                    builder(gate_runner.GATE_SIDE_STAGE_IDS))


if __name__ == "__main__":
    unittest.main()
