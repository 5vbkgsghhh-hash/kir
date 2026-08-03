"""Три опровергающих теста: то, что ВЕШАЕТ, и то, что ВРЁТ.

Отказ — нормальный и безопасный исход: он типизирован и несёт маршрут. Эти три
дефекта — другого класса, каждый нарушает единственный инвариант системы «ноль
молчаливо-неверных исходов»:

* `create_stairs` оставлял Revit с модальным окном и мост умирал на КАЖДОМ
  следующем вызове (наблюдалось живьём 27.07: лестница построилась, дальше
  шесть подряд «Execution was cancelled before Revit started it»);
* `KIR-X003` утверждал «элемент/тип исчез между grounding и исполнением» на
  ЛЮБОМ рантайм-отказе — включая «NewFamilyInstance вернул null» и
  «NewElbowFitting: failed to insert elbow», где ничего не исчезало;
* пул `beam_types` отдавал точечные семейства, которыми `create_beam`
  воспользоваться не может — факт, известный на ground, всплывал в рантайме.
"""
from __future__ import annotations

import unittest

from kukai.ir import serving
from kukai.ir.compiler import compile_program
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


def _stairs_program() -> dict:
    return {"ir_version": "1.0", "intent": "лестница",
            "ops": [{"op": "create_stairs", "id": "S",
                     "p0_mm": [0, 0], "p1_mm": [4000, 0],
                     "base_level": {"by": "element_id", "value": 42},
                     "top_level": {"by": "element_id", "value": 43},
                     "width_mm": 1200}]}


class StairsMustNotLeaveAModalDialog(unittest.TestCase):
    """`create_stairs` — единственный оп со своим шаблоном программы, и в нём
    не было НИЧЕГО из того, что есть у каждой обычной программы: ни
    SetFailuresPreprocessor, ни SetForcedModalHandling(false), ни удаления
    предупреждений. Его собственный обработчик на StairsEditScope.Commit
    возвращал Continue, не удаляя их, — в отличие от основного."""

    def setUp(self) -> None:
        out = compile_program(_stairs_program(), revit_version="2023")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.cs = out.csharp

    def test_transaction_installs_a_failure_preprocessor(self):
        self.assertIn("SetFailuresPreprocessor", self.cs)

    def test_modal_handling_is_disabled(self):
        self.assertIn("SetForcedModalHandling(false)", self.cs)

    def test_warnings_are_swallowed_not_shown(self):
        self.assertIn("DeleteWarning", self.cs)

    def test_scope_commit_preprocessor_also_deletes_warnings(self):
        """StairsEditScope.Commit берёт СВОЙ обработчик — предупреждение может
        подняться и там, уже вне транзакции."""
        scope = self.cs[self.cs.index("__KirStairsFailures : IFailuresPreprocessor"):]
        self.assertIn("DeleteWarning", scope)


class RefusalMessageMustNotInventACause(unittest.TestCase):
    """`__Refuse` помечает ВСЕ рантайм-отказы одним маркером stale_or_failed,
    и serving переводил его в «элемент/тип исчез между grounding и
    исполнением». На отказе «NewFamilyInstance (балка) вернул null» это ложь:
    ничего не исчезало, и пользователя отправляли искать дрейф модели."""

    def _translate(self, message: str) -> dict:
        return serving._translate_runtime(
            {"error": "stale_or_failed",
             "layer": {"error": "stale_or_failed", "op_id": "X",
                       "message": message}})

    def test_api_null_is_not_reported_as_a_vanished_element(self):
        diag = self._translate("NewFamilyInstance (балка) вернул null")
        self.assertEqual(diag["code"], "KIR-X003")
        self.assertNotIn("исчез", diag["message_ru"])
        self.assertIn("null", diag["detail"])

    def test_fitting_failure_is_not_reported_as_a_vanished_element(self):
        diag = self._translate(
            "NewElbowFitting: failed to insert elbow. (angle=90.0deg, 100.0/100.0mm)")
        self.assertNotIn("исчез", diag["message_ru"])

    def test_a_real_grounding_drift_still_says_so(self):
        """Сообщение не выхолащивается: настоящий случай сохраняет прежний
        текст, иначе мы бы просто сделали диагностику бесполезной."""
        diag = self._translate(
            "level: уровень не найден (модель изменилась после grounding)")
        self.assertEqual(diag["code"], "KIR-X003")
        self.assertIn("исчез", diag["message_ru"])


class LevelGuardMustNotClaimDriftForAWrongType(unittest.TestCase):
    """Замерено живьём 27.07 дважды (`create_beam` x16, два прогона ~74 мин
    друг от друга, один редактор, один локальный файл, journalctl
    kukai-backend): X003 сказал «уровень не найден (модель изменилась после
    grounding)» через 130-460мс ПОСЛЕ того, как `ground_snapshot` этот же
    каталог уровней только что вернул — физически мало времени, чтобы кто-то
    руками удалил уровень между двумя вызовами одного bridge-моста.

    Причина: `_level_expr` эмитит ОДНО статическое C#-сообщение на
    `doc.GetElement(id) as Level == null`, а этот null бывает от ДВУХ разных
    причин — id действительно пропал из документа (согласуется с дрейфом)
    ИЛИ id существует, но указывает не на Level. Вторая причина САМА ПО СЕБЕ
    не доказывает баг заземления: `ground.py` документирует `by: element_id`
    как ПРЕДНАМЕРЕННЫЙ pass-through (существование/тип перепроверяются
    ТОЛЬКО здесь, в рантайме — см. докстринг модуля `ground.py`), так что
    неверный id мог прийти и со стороны вызывающего. Починка поэтому не
    придумывает причину: сообщение называет НАБЛЮДАЕМЫЙ факт (не тот тип) и
    честно говорит, что причина рантаймом не определена — та же дисциплина,
    что `RefusalMessageMustNotInventACause` уже применила к «NewFamilyInstance
    вернул null» / «NewElbowFitting: failed to insert elbow», но на слой
    глубже: там `_translate_runtime` угадывала причину по СЫРОМУ тексту
    Revit, здесь сам C#-guard заранее решал за Revit, что случилось, и
    всегда называл это дрейфом — ЛЮБОЙ null-каст, включая «никогда не был
    уровнем»."""

    def _beam_cs(self) -> str:
        out = compile_program({"ir_version": "1.0", "intent": "балка", "ops": [{
            "op": "create_beam", "id": "B",
            "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
            "level": {"by": "element_id", "value": 42},
            "symbol": {"by": "element_id", "value": 1000}}]},
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        return out.csharp

    def test_guard_distinguishes_absent_from_wrong_type(self):
        """До фикса `as Level == null` ведёт в ЕДИНСТВЕННОЕ статическое
        сообщение независимо от причины: C# никогда не смотрит на реальный
        тип того, что лежит по id. Эта проверка требует вторую ветку —
        иначе `_translate_runtime` не может честно отличить «исчез» от «не
        тот класс», сколько бы подписей в Python ни придумывай: информации
        просто нет в сообщении, которое эмитировал компилятор."""
        cs = self._beam_cs()
        self.assertIn(".GetType().Name", cs)

    def test_wrong_type_message_does_not_claim_drift(self):
        """Сообщение о «не тот тип» не должно содержать подпись «после
        grounding» — иначе `_translate_runtime` снова назовёт это дрейфом,
        та же тавтология под новым текстом."""
        diag = serving._translate_runtime(
            {"error": "stale_or_failed",
             "layer": {"error": "stale_or_failed", "op_id": "B",
                       "message": ("id уровня резолвится не в Level, а в Wall "
                                   "— причина (дрейф модели или неверный id) "
                                   "не определена рантаймом")}})
        self.assertNotIn("исчез", diag["message_ru"])

    def test_wrong_type_message_does_not_blame_grounding(self):
        """`ground.py` документирует `by: element_id` как pass-through без
        проверки типа (существование/тип перепроверяются только рантаймом) —
        значит неверный id мог прийти со стороны вызывающего, а не из бага
        заземления. Сообщение обязано называть НАБЛЮДАЕМЫЙ факт, а не
        придумывать, чей это баг."""
        cs = self._beam_cs()
        seg = cs[cs.index("id уровня резолвится не в Level"):]
        clause = seg[:seg.index(";")]
        self.assertNotIn("grounding привязал", clause)
        self.assertIn("не определена", clause)

    def test_genuine_absence_still_claims_drift(self):
        """И наоборот: когда элемента ДЕЙСТВИТЕЛЬНО нет (raw == null), фикс
        обязан сохранить прежний честный текст — не выхолостить диагностику
        в обратную сторону (симметрично `test_a_real_grounding_drift_still_says_so`)."""
        diag = serving._translate_runtime(
            {"error": "stale_or_failed",
             "layer": {"error": "stale_or_failed", "op_id": "B",
                       "message": "уровень не найден (модель изменилась после grounding)"}})
        self.assertIn("исчез", diag["message_ru"])


class BeamPoolMustNotOfferPointPlacedFamilies(unittest.TestCase):
    """Замерено 27.07: все 36 семейств каркаса в реальном здании —
    FamilyPlacementType.OneLevelBased (точечные). NewFamilyInstance(Line, …,
    Beam) на таком возвращает null, а пул отдавал их как ни в чём не бывало.
    Ground обязан отказать KIR-G104 «пусто в модели» — честное «не на чем»
    вместо рантайм-null."""

    def test_snapshot_pool_filters_by_placement_type(self):
        from kukai.ir.open_model import GROUND_SNAPSHOT_CS
        line = next(ln for ln in GROUND_SNAPSHOT_CS.splitlines()
                    if '__AddPool("beam_types"' in ln)
        self.assertIn("FamilyPlacementType", line)

    def test_query_types_pool_filters_by_placement_type(self):
        from kukai.ir.compiler import _TYPE_POOL_COLLECTOR_CS
        self.assertIn("FamilyPlacementType", _TYPE_POOL_COLLECTOR_CS["beam_types"])

    def test_other_symbol_pools_are_untouched(self):
        """Точечное размещение — норма для окон/дверей/колонн; фильтр касается
        ТОЛЬКО балок, где эмиттер требует кривой."""
        from kukai.ir.compiler import _TYPE_POOL_COLLECTOR_CS
        for pool in ("window_symbols", "door_symbols",
                     "column_symbols_structural", "foundation_symbols"):
            self.assertNotIn("FamilyPlacementType", _TYPE_POOL_COLLECTOR_CS[pool], pool)


class BeamLevelWitnessMustReadTheParameterABeamActuallyHas(unittest.TestCase):
    """Замерено 27.07 прямой пробой: у балки, созданной
    NewFamilyInstance(Line, symbol, level, StructuralType.Beam), уровень лежит
    ТОЛЬКО в INSTANCE_REFERENCE_LEVEL_PARAM. Всё остальное пусто:

        INSTANCE_REFERENCE_LEVEL_PARAM = 172458 («L_01_+0.000»)
        FAMILY_LEVEL_PARAM   = -1
        SCHEDULE_LEVEL_PARAM = -1
        LEVEL_PARAM          = нет такого параметра
        fi.LevelId           = -1

    Общая цепочка свидетеля этого параметра не знала, поэтому балка
    откатывалась с «level binding mismatch (topology)» ДАЖЕ когда уровень был
    ровно тот, что просили — то есть свидетель обвинял правильную постройку.
    Цепочка короткозамкнутая, поэтому добавление в хвост ничего не меняет для
    опов, у которых заполнен более ранний параметр."""

    def _beam_cs(self) -> str:
        out = compile_program({"ir_version": "1.0", "intent": "балка", "ops": [{
            "op": "create_beam", "id": "B",
            "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
            "level": {"by": "element_id", "value": 42},
            "symbol": {"by": "element_id", "value": 1000}}]},
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        return out.csharp

    def test_beam_witness_consults_the_reference_level_parameter(self):
        self.assertIn("INSTANCE_REFERENCE_LEVEL_PARAM", self._beam_cs())

    def test_beam_does_not_assert_a_level_the_api_never_promised(self):
        """Второй замер той же пробы: Revit привязал балку НЕ к переданному
        уровню — передан L_01 @ 0 мм, кривая на Z=3000, привязка ушла к
        L_01ДОО1_+2.500 (ближайший снизу). Значит `level` у
        NewFamilyInstance(Line, …, Beam) — контекст размещения, а не обещание,
        и требовать равенства значило откатывать правильную балку. Свидетель
        проверяет НАЛИЧИЕ уровня, а какой именно — читает в результат;
        положение при этом пришпилено обоими концами в 3D с допуском 5 мм."""
        cs = self._beam_cs()
        self.assertIn("нет опорного уровня (topology)", cs)
        self.assertNotIn("level binding mismatch", cs)
        self.assertIn('"reference_level_id"', cs)

    def test_level_chain_skips_a_link_that_holds_no_element(self):
        """`HasValue` истинен и для InvalidElementId — замерено на балке:
        `FAMILY_LEVEL_PARAM: HasValue=True, AsElementId=-1`. Цепочка обрывалась
        на пустом звене и сравнивала «-1» с ожидаемым id. Переход должен
        требовать НАСТОЯЩИЙ id, а не просто заполненность."""
        # place_family — оп, который цепочку действительно эмитит (стена
        # читает WALL_BASE_CONSTRAINT напрямую и до цепочки не доходит).
        out = compile_program({"ir_version": "1.0", "intent": "семейство", "ops": [{
            "op": "place_family", "id": "P", "xyz": [0, 0, 0],
            "level": {"by": "element_id", "value": 42},
            "symbol": {"by": "element_id", "value": 1000}}]},
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("ElementId.InvalidElementId) __lp =", out.csharp)


class RollbackMustNameItsCause(unittest.TestCase):
    """Сборка здания целиком умерла на «transaction commit status: RolledBack»
    и больше не сказала ничего. Revit откатывает так, встретив отказ уровня
    ERROR: наш обработчик снимал предупреждения и НАМЕРЕННО не гасил ошибку —
    но и не запоминал её, поэтому причина терялась безвозвратно.

    Живая проба 27.07 показала, что текст доступен: перехваченное через
    FailuresAccessor сообщение читается (`GetSeverity()` + `GetDescriptionText()`).
    Молчащий откат — тот самый немой исход, который этот компилятор запрещает."""

    def _cs(self) -> str:
        out = compile_program({"ir_version": "1.0", "intent": "стена", "ops": [{
            "op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [6000, 0],
            "level": {"by": "element_id", "value": 42}}]},
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        return out.csharp

    def test_errors_are_collected_not_only_warnings_deleted(self):
        cs = self._cs()
        self.assertIn("GetDescriptionText()", cs)
        self.assertIn("public static List<string> Seen", cs)

    def test_warnings_are_still_swallowed(self):
        """Предупреждения по-прежнему снимаются: иначе диалог заморозит Revit."""
        self.assertIn("DeleteWarning", self._cs())

    def test_failure_names_the_failing_elements_not_only_the_type(self):
        """Отказ «Экземпляры ДВг_21х10.5_П_900 в свету ничего не вырезают»
        называет ТИП, а таких дверей в здании семь. Найти виноватый экземпляр
        по типу нельзя — а FailureMessageAccessor.GetFailingElementIds() есть
        во всех шести версиях и отдаёт ровно те id, на которые Revit ругается.
        Без них каждая следующая проверка бьёт по площади вместо цели."""
        cs = self._cs()
        self.assertIn("GetFailingElementIds()", cs)

    def test_rollback_refusal_carries_the_revit_text(self):
        cs = self._cs()
        self.assertIn("transaction commit status: ", cs)
        self.assertIn("| Revit: ", cs)

    def test_the_log_is_cleared_before_each_run(self):
        """Список статический и переживает прогон — иначе следующая программа
        получит чужую причину."""
        cs = self._cs()
        self.assertIn("__KirMainFailures.Seen.Clear()", cs)
        # Важен не порядок относительно Start, а то, что чистка предшествует
        # ЛЮБОЙ операции: только тогда собранное относится к этому прогону.
        self.assertLess(cs.index("Seen.Clear()"), cs.index("Wall.Create"))


if __name__ == "__main__":
    unittest.main()
