"""``set_curtain_panel`` — прямая сторона (дизайн 2026-07-28).

Панель витража нельзя создать отдельно: она существует только как ЯЧЕЙКА
сетки носителя. Поэтому оп назначает ячейке тип, а не «строит панель», и
проверять у него надо ровно то, что у такого опа может сломаться молча:

* адрес ячейки обязателен и целочислен — 1×1 это (0,0), а не «можно без»;
* свидетель читает РЕЗУЛЬТАТ по адресу, а не элемент, который вернул вызов
  (``ChangePanelType`` возвращает подменённый элемент — сверка с ним
  доказывала бы лишь то, что вызов состоялся);
* каждый охранник create-блока написан ТОЙ САМОЙ фразой, которую переписывает
  per-op изоляция: иначе отказ одной ячейки утащил бы за собой всю программу,
  и тест на компиляцию этого не заметил бы.
"""

# 04.08.2026: класс объекта читается помощником ``__ClassName`` из преамбулы, а
# не обращением к среде выполнения за типом — прежняя идиома целиком
# отвергается валидатором безопасности моста версий до 06.07.2026 (живой отказ
# на Revit 2023, «Заблокировано: GetType() (runtime type resolution)»). Все
# проверки ниже сохранили СВОЙ контракт (тип исключения назван, внутреннее
# исключение донесено, улика несёт классы операндов) — сменилась только запись.
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir import spec  # noqa: E402
from kukai.ir.authoring import (  # noqa: E402
    _EMITTERS, curtain_cell_address_cs, emit_program)
from kukai.ir.compiler import _parse_and_check, compile_program  # noqa: E402
from kukai.ir.diag import KirRefusal  # noqa: E402
from kukai.ir.emit_model import post_to_string  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")


def _program(ops: list[dict], **envelope) -> dict:
    return {"ir_version": "1.0", "intent": "витраж", "ops": ops, **envelope}


def _cell_op(**overrides) -> dict:
    op = {
        "op": "set_curtain_panel", "id": "CP1",
        "host": {"by": "element_id", "value": 8145901},
        "u": 0, "v": 0,
        "panel_type": {"by": "name", "value": "Стеклопакет 30мм"},
    }
    op.update(overrides)
    return op


def _emit(op: dict, version: str = "2023"):
    grounded = ground_mod.ground(
        _parse_and_check(_program([op])), GROUND_SNAPSHOT)
    return _EMITTERS["set_curtain_panel"](grounded[0], version, "kir:test")


class TheAddressIsRequiredAndExact(unittest.TestCase):
    def test_a_one_by_one_grid_is_cell_zero_zero_not_an_absent_address(
            self) -> None:
        decl, create, post, readback = _emit(_cell_op(u=0, v=0))
        self.assertIn("__ccPanelAt", create)
        self.assertIn(", 0, 0)", create)

    def test_a_missing_address_is_a_typed_refusal(self) -> None:
        for field in ("u", "v"):
            with self.subTest(field=field):
                op = _cell_op()
                del op[field]
                with self.assertRaises(KirRefusal) as caught:
                    _parse_and_check(_program([op]))
                self.assertTrue(
                    any(d.field_name == field
                        for d in caught.exception.diagnostics))

    def test_a_fractional_cell_index_is_refused_not_truncated(self) -> None:
        with self.assertRaises(KirRefusal) as caught:
            _parse_and_check(_program([_cell_op(u=1.5)]))
        self.assertTrue(
            any(d.field_name == "u" for d in caught.exception.diagnostics))

    def test_a_boolean_is_not_a_cell_index(self) -> None:
        with self.assertRaises(KirRefusal):
            _parse_and_check(_program([_cell_op(v=True)]))

    def test_a_negative_index_is_refused(self) -> None:
        with self.assertRaises(KirRefusal):
            _parse_and_check(_program([_cell_op(u=-1)]))

    def test_the_address_definition_is_shared_with_the_capture(self) -> None:
        """ОДНО определение адреса: эмиттер и захват считают его одним кодом."""

        decl, _create, _post, _readback = _emit(_cell_op())
        self.assertIn(curtain_cell_address_cs("CP1").strip(), decl)

    def test_two_cells_in_one_program_do_not_collide(self) -> None:
        """Хелперы адреса именуются по опу: две ячейки — две копии, не CS0128."""

        program = _program([
            _cell_op(),
            _cell_op(id="CP2", u=2, v=1),
        ])
        out = compile_program(program, revit_version="2026",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertIn("__ccOrderCP1", out.csharp)
        self.assertIn("__ccOrderCP2", out.csharp)


class TheWitnessReadsTheResult(unittest.TestCase):
    def test_the_post_re_reads_the_cell_by_address(self) -> None:
        _decl, _create, post, _readback = _emit(_cell_op(u=2, v=1))
        rendered = post_to_string("CP1", post)
        self.assertIn("__ccPanelAtCP1", rendered)
        self.assertIn("__ccOrderCP1", rendered)
        self.assertIn("__ccEffTypeCP1", rendered)
        self.assertIn(", 2, 1)", rendered)

    def test_the_post_never_certifies_the_calls_own_echo(self) -> None:
        """Элемент, который вернул ChangePanelType, свидетелем быть не может."""

        _decl, create, post, _readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        self.assertIn("ChangePanelType", create)
        self.assertNotIn("ChangePanelType", rendered)

    def test_both_obligations_carry_a_verdict(self) -> None:
        _decl, _create, post, _readback = _emit(_cell_op())
        keys = {check.obligation_key for check in post}
        self.assertEqual(keys, {"panel_type", "cell_host"})
        for check in post:
            with self.subTest(key=check.obligation_key):
                self.assertIn("__post.Add", check.verdict_cs)


class TheGuardsSurvivePerOpIsolation(unittest.TestCase):
    def test_every_create_guard_uses_the_one_owned_refusal(self) -> None:
        """В атомарной эмиссии КАЖДЫЙ отказ ячейки откатывает транзакцию.

        До 28.07.2026 это было требование к ФРАЗЕ: per_op переписывал её
        текстом, и охранник, написанный иначе, тихо сохранял семантику всей
        программы внутри SubTransaction.  Фразой больше никто не владеет
        (emit_utils.refuse_stmt), но само правило осталось предметным: отказ
        ячейки в одной транзакции обязан быть откатом, а не голым return —
        `refuses == rewritable` ловит ровно это.  Общий контракт изоляции —
        в test_emission_guard_contract.
        """

        _decl, create, _post, _readback = _emit(_cell_op())
        refuses = create.count("return __Refuse(")
        rewritable = create.count("__t.RollBack(); return __Refuse(")
        self.assertGreater(refuses, 0)
        self.assertEqual(refuses, rewritable)

    def test_per_op_program_leaves_no_whole_program_return(self) -> None:
        grounded = ground_mod.ground(
            _parse_and_check(_program([_cell_op()])), GROUND_SNAPSHOT)
        body = emit_program(grounded, "2026", isolation="per_op")
        self.assertIn("throw __OpRefuse(", body)
        # Единственный `return __Refuse` целой программы — общий пролог
        # транзакции, а не охранник ячейки.
        self.assertNotIn("__t.RollBack(); return __Refuse(\"CP1\"", body)


class TheGridIsRegeneratedBeforeItIsRead(unittest.TestCase):
    """Сетка витража рождается регенерацией, а не вызовом Wall.Create.

    ЗАМЕР 28.07 (живые пробы на фасаде SOB6.2, Revit 2023):
      * П1 — витражная стена ОДНА, точные координаты упавшего чанка: ok,
        свидетель 3/3. Значит сама стена не виновата;
      * П4 — та же стена + наш оп в ОДНОЙ транзакции: KIR-X003,
        «ChangePanelType: » и пустое сообщение Revit.

    Разница между пробами — только соседство в одной транзакции, поэтому
    перед всякой работой с сеткой ставится ``doc.Regenerate()``. Прецедент
    тот же, что у ``_symbol_res`` (Activate + Regenerate) и у CONNECT
    (коннекторы читаются только после регена).
    """

    def test_the_create_block_regenerates_before_touching_the_grid(
            self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("doc.Regenerate();", create)
        self.assertLess(
            create.index("doc.Regenerate();"),
            create.index("__ccGrids"),
            "реген обязан стоять ДО чтения сетки, а не между чтением и записью")

    def test_regeneration_failure_is_not_swallowed(self) -> None:
        """Провал регена — испорченный документ (документация сборок).

        Глушить его значило бы продолжать работу в документе, про который
        Revit уже сказал, что он непригоден даже для чтения.
        """

        _decl, create, _post, _readback = _emit(_cell_op())
        head = create[:create.index("__ccGrids")]
        self.assertNotIn("try", head)
        self.assertNotIn("catch", head)


class TheTypeDrivenPanelIsUnlockedFirst(unittest.TestCase):
    """Панель, порождённую типом носителя, Revit держит запертой.

    ЗАМЕР 28.07, живые пробы на фасаде SOB6.2 (Revit 2023) — обе вернули
    ОДНУ И ТУ ЖЕ причину, чем и закрыли развилку:

        П6 (носитель УЖЕ существует, WallType 273445):
          «ChangePanelType: InvalidOperationException: (пустое сообщение
           Revit) | ячейка (0,0) панель 11401342 (Panel),
           РАЗБЛОКИРОВАНА=НЕТ, новый тип 273445 (WallType), носитель
           11401341»
        П7 (одна транзакция, PanelType 273243): то же, разблокирована=нет.

    П6 сняла транзакцию (носитель был готов и отрегенерирован), П7 сняла вид
    типа. Осталось одно — ЗАМОК. Словарь отказов сборок называет этот класс
    прямо: ``BuiltInFailures.CurtainWallFailures.
    TypePanelsFronNonRectCellsUnlocked`` — «Type-driven panels … were
    UNLOCKED and left unchanged».

    Отпирание здесь — воспроизведение авторского действия: все 53 поднятые
    ячейки фасада ЗАМЕНЁННЫЕ, то есть в оригинале их отперли руками. Обратно
    панель не запирается — запертой она в исходнике и не была.
    """

    def test_the_cell_is_unlocked_before_the_type_is_changed(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("__cp_CP1.Pinned = false;", create)
        self.assertLess(
            create.index("__cp_CP1.Pinned = false;"),
            create.index("ChangePanelType"),
            "отпирать надо ДО смены типа, иначе Revit бросает пустое "
            "исключение (замер П6/П7)")

    def test_the_lock_state_is_read_not_assumed(self) -> None:
        """Отпираем ТОЛЬКО запертую: состояние читается, а не предполагается."""

        _decl, create, _post, _readback = _emit(_cell_op())
        head = create[:create.index("__cp_CP1.Pinned = false;")]
        self.assertIn("GetUnlockedPanelIds", head)
        self.assertIn("__cpn_CP1 = __cp_CP1.Pinned;", head)
        self.assertIn("if (__clk_CP1 || __cpn_CP1)", head)

    def test_an_unlock_that_fails_is_a_typed_refusal_not_a_silence(
            self) -> None:
        """У класса ячейки может не быть отпирания — тогда так и сказать.

        ``Element.Pinned`` по документации сборок бросает
        InvalidOperationException «Element cannot be pinned or unpinned»;
        проглотить его значило бы пойти на ChangePanelType с заведомо
        запертой панелью и получить обратно пустое исключение.
        """

        _decl, create, _post, _readback = _emit(_cell_op())
        block = create[create.index("__cp_CP1.Pinned = false;"):]
        block = block[:block.index("ChangePanelType")]
        self.assertIn("catch (Exception __cux_CP1)", block)
        self.assertIn("замок ячейки не снимается для", block)
        self.assertIn("__ClassName(__cp_CP1)", block)
        self.assertIn("__t.RollBack(); return __Refuse(", block)

    def test_the_panel_is_never_locked_back(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertNotIn("Pinned = true", create)

    def test_the_diagnosis_carries_the_lock_state_before_unlocking(
            self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        tail = create[create.index("catch (Exception __cex_CP1)"):]
        self.assertIn("до отпирания: заперта=", tail)

    def test_the_witness_reads_the_lock_state_back(self) -> None:
        _decl, _create, _post, readback = _emit(_cell_op())
        self.assertIn('__rb["panel_lock"]', readback)
        self.assertIn("GetUnlockedPanelIds", readback)
        # состояние читается у ЗАНЯВШЕГО ячейку (__co_), а не у операнда до
        # смены: после смены на тип стены это разные элементы (см.
        # ChangingTheTypeReplacesTheElement)
        self.assertIn("__co_CP1.Pinned", readback)

    def test_unlocking_works_for_a_wall_filled_cell_too(self) -> None:
        """``GetPanelIds`` отдаёт и ``Panel``, и ``Wall`` (документация
        сборок), поэтому глагол отпирания взят с ``Element``: у ``Panel``
        сеттера замка нет вовсе (``Lockable`` только читается), а ``Lock``
        живёт у ``Mullion``. Один код на оба класса ячейки."""

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertNotIn(".Lockable", create)
        self.assertNotIn(".Lock =", create)
        self.assertIn("__cp_CP1.Pinned = false;", create)


class TheFailureNamesItself(unittest.TestCase):
    """Пустая улика — тоже дефект.

    Живая проба П4 вернула ровно «ChangePanelType: » — Revit бросил с
    ПУСТЫМ Message, и отказ не назвал ни класса исключения, ни панели, ни
    типа. Час догадок вместо секунды чтения; в отказе теперь всё, что
    различает случаи.
    """

    def test_the_exception_type_is_named(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("__ClassName(__cex_CP1)", create)

    def test_an_empty_revit_message_is_called_empty(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("String.IsNullOrEmpty(__cex_CP1.Message)", create)
        self.assertIn("(пустое сообщение Revit)", create)

    def test_the_inner_exception_is_carried(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("__cex_CP1.InnerException", create)
        self.assertIn("__ClassName(__cex_CP1.InnerException)", create)

    def test_the_evidence_carries_the_operands_and_the_lock_state(
            self) -> None:
        """Классы панели и типа + замок: GetPanelIds по документации сборок
        отдаёт и ``Panel``, и ``Wall``, а ``GetUnlockedPanelIds`` существует
        ровно потому, что запертую панель менять нельзя."""

        _decl, create, _post, _readback = _emit(_cell_op())
        tail = create[create.index("catch (Exception __cex_CP1)"):]
        for token in ("__ClassName(__cp_CP1)", "__ClassName(__ct_CP1)",
                      "GetUnlockedPanelIds", "разблокирована=",
                      "__ch_CP1.Id.ToString()"):
            with self.subTest(token=token):
                self.assertIn(token, tail)

    def test_the_witness_readback_names_the_panel_class(self) -> None:
        _decl, _create, _post, readback = _emit(_cell_op())
        self.assertIn('__rb["panel_class"]', readback)

    def test_the_guard_phrase_survives_the_richer_message(self) -> None:
        """Улика не имеет права сломать переписывание per_op."""

        _decl, create, _post, _readback = _emit(_cell_op())
        refuses = create.count("return __Refuse(")
        rewritable = create.count("__t.RollBack(); return __Refuse(")
        self.assertGreater(refuses, 0)
        self.assertEqual(refuses, rewritable)


class ChangingTheTypeReplacesTheElement(unittest.TestCase):
    """Смена типа ячейки — ЗАМЕНА элемента, а не правка на месте.

    ЗАМЕР 28.07, живая проба П8 (после отпирания замка): исключение
    ИСЧЕЗЛО, ChangePanelType исполнился, geometry/topology зелёные — и
    свидетель поймал семантику: «P8C: тип панели в ячейке не равен
    запрошенному». Читалась старая ячейка, которой после смены на тип СТЕНЫ
    в сетке уже нет.

    Документация сборок: «If operation succeeds, **the modified panel element
    is returned**». Возврат — это id нового занявшего, а не утверждение о
    состоянии: состояние всё равно перечитывается из модели после
    Regenerate. Близнец урока ChangeTypeId («реальный id = замена элемента»).
    """

    def test_the_returned_element_is_captured(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("__cn_CP1 = __cg_CP1.ChangePanelType(", create)

    def test_the_witness_does_not_read_the_old_reference(self) -> None:
        """__cp_ — операнд ДО смены; после неё он может быть не в сетке."""

        _decl, _create, post, readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        self.assertNotIn("__ccEffTypeCP1(__cp_CP1)", rendered)
        self.assertNotIn("__ClassName(__cp_CP1)", readback)
        self.assertIn("__ccEffTypeCP1(__co_CP1)", rendered)

    def test_the_returned_element_is_accepted_only_inside_this_grid(
            self) -> None:
        """Ссылку от вызова принимаем, лишь убедившись, что она в СЕТКЕ —
        иначе это было бы эхо вызова вместо чтения модели."""

        _decl, _create, post, _readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        head = rendered[:rendered.index("if (__co_CP1 == null)")]
        self.assertIn("__cg_CP1.GetPanelIds()", head)
        self.assertIn("if (__cnm_CP1) __co_CP1 = __cn_CP1;", head)

    def test_the_address_re_read_survives_as_the_fallback(self) -> None:
        _decl, _create, post, _readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        self.assertIn("__ccPanelAtCP1(", rendered)
        self.assertIn("if (__co_CP1 == null) __co_CP1 = __cq_CP1;", rendered)

    def test_a_wall_occupant_proves_its_host_by_grid_membership(self) -> None:
        """У ячейки-СТЕНЫ нет свойства Host — принадлежность доказывает
        список панелей самой сетки. Для FamilyInstance сильная проверка
        ссылки Host остаётся."""

        _decl, _create, post, _readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        self.assertIn("__cfi_CP1.Host.Id.ToString()", rendered)
        self.assertIn("__chm_CP1", rendered)
        self.assertIn("(topology)", rendered)

    def test_the_replacement_is_a_fact_in_the_readback(self) -> None:
        _decl, _create, _post, readback = _emit(_cell_op())
        for key in ("old_panel_id", "returned_panel_id",
                    "addressed_panel_id", "panel_replaced"):
            with self.subTest(key=key):
                self.assertIn(f'__rb["{key}"]', readback)

    def test_the_old_id_is_captured_before_the_change(self) -> None:
        """После замены читать Id у мёртвой ссылки поздно."""

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("__cpi_CP1 = __cp_CP1.Id.ToString();", create)
        self.assertLess(create.index("__cpi_CP1 = __cp_CP1.Id.ToString();"),
                        create.index("ChangePanelType"))


class TheRequestedTypeIsChasedNotAssumed(unittest.TestCase):
    """ChangePanelType строит стену НЕ ТОГО типа — молча.

    ЗАМЕР 28.07, прямые эксперименты на живом носителе 11401341:

      E1  ChangePanelType(панель, WallType 273445) вернул id=11401344,
          класс Wall, тип **7469627** — тип разрезки носителя, а не
          запрошенный 273445. Ни исключения, ни отказа. Повторный вызов
          идемпотентно возвращает ту же чужую стену.
      E3  `ret.ChangeTypeId(273445)` вернул **-1** (InvalidElementId),
          тип стал 273445 и пережил Regenerate.

    Документация сборок описывает ровно наш случай (Element.ChangeTypeId):
    «In rare cases, applying a change in type will result in a new element
    being created. The ONLY active examples of this are when applying a
    normal wall type to a curtain panel, or converting such a wall back to a
    curtain panel. In this situation the new element id is returned.» И про
    возврат: «The new element id if new element is created, or
    **InvalidElementId if the element's type changed without creating a new
    element**» — то есть -1 это ОБЫЧНЫЙ УСПЕХ, наш близнец-урок.
    """

    def test_the_type_is_verified_after_the_call_not_assumed(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        chase = create[create.index("catch (Exception __cex_CP1)"):]
        self.assertIn("__cnt_CP1 = __cn_CP1.GetTypeId();", chase)
        self.assertIn("__cnt_CP1.ToString() != __ct_CP1.Id.ToString()", chase)

    def test_the_chase_calls_change_type_id(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("__cn_CP1.ChangeTypeId(__ct_CP1.Id)", create)
        self.assertLess(create.index("ChangePanelType"),
                        create.index("ChangeTypeId"),
                        "догон идёт ПОСЛЕ смены панели, а не вместо неё")

    def test_an_invalid_element_id_return_is_success_not_failure(self) -> None:
        """Близнец-урок: -1 значит «тип сменился без замены элемента»."""

        _decl, create, _post, _readback = _emit(_cell_op())
        chase = create[create.index("ChangeTypeId"):]
        self.assertIn("ElementId.InvalidElementId.ToString()", chase)
        # новый id читается ТОЛЬКО когда он не -1
        self.assertIn("__cnw_CP1 = doc.GetElement(__cnr_CP1);", chase)
        self.assertIn("if (__cnw_CP1 != null) __cn_CP1 = __cnw_CP1;", chase)

    def test_a_failed_chase_is_a_typed_refusal(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("догон типа ячейки не прошёл", create)
        self.assertIn("__ClassName(__ctx_CP1)", create)
        self.assertIn("__t.RollBack(); return __Refuse(", create)

    def test_the_receipt_says_whether_the_chase_was_needed(self) -> None:
        _decl, _create, _post, readback = _emit(_cell_op())
        self.assertIn('__rb["type_chased"]', readback)


class AWallOccupantIsBoundBySpaceNotByTheGridList(unittest.TestCase):
    """Стена-занявший НИКОГДА не появляется в списке панелей сетки.

    ЗАМЕР 28.07 (E2, транзакция ЗАКОММИЧЕНА): после смены ячейки на тип
    стены `GetPanelIds()` держит прежнюю авто-панель 11401342 (класс Panel,
    тип 1715), стена 11401344 жива, но в списке её нет — ни после
    Regenerate, ни после Commit. Это запись Revit для возврата ячейки к
    type-driven, живущая параллельно занявшему.

    Значит проверка «занявший состоит в списке панелей» для стены
    ЛОЖНО-ОТРИЦАТЕЛЬНА ВСЕГДА — и П8 падала ровно на ней: фолбэк возвращал
    адресную старую панель, у неё старый тип, свидетель честно ругался.

    Привязка измерена: середина оси стены-занявшего проецируется на ось
    носителя с расстоянием 0.0 мм (E2). Допуск 50 мм — на дуговые носители.
    """

    def test_the_axis_binding_helper_is_declared_once(self) -> None:
        decl, _create, _post, _readback = _emit(_cell_op())
        self.assertIn("Func<Element, bool> __ccAxisCP1", decl)
        self.assertIn("Curve.Project(", decl)
        self.assertIn("MM(__cap_CP1.Distance) <= 50.0", decl)

    def test_a_non_family_occupant_is_accepted_by_the_axis(self) -> None:
        _decl, _create, post, _readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        head = rendered[:rendered.index("if (__co_CP1 == null) __co_CP1")]
        self.assertIn("if (__cn_CP1 is FamilyInstance)", head)
        self.assertIn("else __cnm_CP1 = __ccAxisCP1(__cn_CP1);", head)

    def test_a_family_occupant_is_still_accepted_by_membership(self) -> None:
        _decl, _create, post, _readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        head = rendered[:rendered.index("if (__co_CP1 == null) __co_CP1")]
        self.assertIn("__cg_CP1.GetPanelIds()", head)

    def test_the_topology_verdict_no_longer_asks_the_grid_list_for_a_wall(
            self) -> None:
        """ПРЕД-СОСТОЯНИЕ: на прежней эмиссии эта ветка спрашивала
        GetPanelIds и была ложно-отрицательной для каждой ячейки-стены."""

        _decl, _create, post, _readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        tail = rendered[rendered.index("FamilyInstance __cfi_CP1"):]
        else_branch = tail[tail.index("else"):]
        self.assertIn("__ccAxisCP1(__co_CP1)", else_branch)
        self.assertNotIn("GetPanelIds", else_branch,
                         "членство в списке панелей для стены — всегда ложь")


class OnlyWhatWeCreatedIsStampedAndCounted(unittest.TestCase):
    """Штамп — на созданное; `id` — идентичность; `created` — рождение.

    ЗАМЕР 28.07, пересборка №5 (артефакт v10): цикл чистый, фаза REBUILT
    наступила, и упал следующий слой — RECONCILED: «run-prefix
    reconciliation disagrees with commit receipts». Перепись штампа видит
    ровно ШТАМПОВАННОЕ, а ячейку занимал НОВЫЙ элемент (`ChangePanelType` с
    типом стены рождает стену), который в created_ids ехал, но штампа не
    имел. В плане 54 таких опа.

    Обратная сторона — почему условие «только созданное»: A5 УДАЛЯЕТ по
    штампу. Пометить ячейку, существовавшую до нас (тип сменён на месте, тот
    же элемент), значило бы объявить чужой элемент своим и снести его на
    уборке.
    """

    def test_the_new_occupant_is_stamped(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        stamp = create[create.index("ChangeTypeId"):]
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", stamp)
        self.assertIn("__cn_CP1", stamp)

    def test_an_in_place_type_change_is_not_stamped(self) -> None:
        """Условие штампа — «id занявшего отличается от прежнего»."""

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn(
            'if (__cn_CP1 != null && __cn_CP1.Id.ToString() != __cpi_CP1)',
            create)

    def test_the_stamp_comes_after_the_type_is_final(self) -> None:
        """Штамповать до догона типа значило бы штамповать промежуточный
        элемент, который догон может заменить ещё раз."""

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertLess(create.index("ChangeTypeId"),
                        create.index("ALL_MODEL_INSTANCE_COMMENTS"))

    def test_the_receipt_separates_identity_from_creation(self) -> None:
        _decl, _create, _post, readback = _emit(_cell_op())
        self.assertIn('__rb["id"]', readback)
        self.assertIn('__rb["created"]', readback)
        self.assertIn('(__co_CP1.Id.ToString() != __cpi_CP1)', readback)


class TheTypeSelectorIsResolvedNeverGuessed(unittest.TestCase):
    def test_by_default_is_refused_because_a_cell_has_no_default_type(
            self) -> None:
        with self.assertRaises(KirRefusal) as caught:
            _parse_and_check(_program([_cell_op(
                panel_type={"by": "default"})]))
        self.assertTrue(
            any(d.field_name == "panel_type"
                for d in caught.exception.diagnostics))

    def test_a_named_type_is_searched_in_both_type_spaces(self) -> None:
        """Тип ячейки живёт и среди типоразмеров семейств, и среди типов стен.

        Ячейка, заполненная стеной, — норма фасада (259 из 361 на модели
        замера), и её тип это WallType, который не является FamilySymbol.
        """

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("OfClass(typeof(FamilySymbol))", create)
        self.assertIn("OfClass(typeof(WallType))", create)

    def test_zero_and_several_matches_are_both_typed_refusals(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("Count == 0", create)
        self.assertIn("Count > 1", create)

    def test_host_accepts_both_a_ref_and_a_pinned_id(self) -> None:
        """Дизайн пишет `host: ref|element_id` — обе формы обязаны жить."""

        by_id = _program([_cell_op()])
        self.assertTrue(compile_program(
            by_id, revit_version="2026", snapshot=GROUND_SNAPSHOT).ok)
        by_ref = _program([
            {"op": "create_wall", "id": "WC", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42}},
            _cell_op(host={"by": "ref", "value": "WC"}),
        ])
        out = compile_program(by_ref, revit_version="2026",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_a_host_ref_must_point_at_a_wall_op(self) -> None:
        bad = _program([
            {"op": "create_level", "id": "L1", "elev_mm": 0},
            _cell_op(host={"by": "ref", "value": "L1"}),
        ])
        out = compile_program(bad, revit_version="2026",
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L004", [d.code for d in out.diagnostics])


class TheRegistryEntryIsWellFormed(unittest.TestCase):
    def test_the_op_writes_and_declares_its_witness(self) -> None:
        op_spec = spec.OPS["set_curtain_panel"]
        self.assertTrue(op_spec.writes_model)
        self.assertIn(op_spec.family, spec.WRITE_FAMILIES)
        self.assertIn("panel_type", op_spec.post)
        self.assertIn("(topology)", op_spec.post)

    def test_no_model_specific_name_leaked_into_the_op(self) -> None:
        """INVARIANT #1: ни одного имени из модели замера в реестре/эмиттере.

        Правило распознавания структурное (тип против типа по умолчанию), и
        компилятор опенсорсится — список знакомых имён сделал бы его
        компилятором ОДНОГО здания.
        """

        from pathlib import Path
        emitter = Path(__file__).resolve().parents[1] / "authoring.py"
        source = emitter.read_text(encoding="utf-8")
        start = source.index("CURTAIN_CELL_ADDRESS_CS = ")
        end = source.index("_EMITTERS = {", start)
        # Проверяется ИСПОЛНЯЕМЫЙ текст, а не происхождение фактов.
        # Комментарий обязан называть модель и дату замера — этим и живёт
        # «measure, don't recall»; запрещено имя модели в ПРАВИЛЕ, потому что
        # правило со списком знакомых имён — компилятор одного здания.
        # Первая редакция теста резала и комментарии, то есть требовала
        # анонимных замеров: провенанс и хардкод — разные вещи.
        code_lines = [
            line for line in source[start:end].splitlines()
            if not line.lstrip().startswith("#")
            and not line.lstrip().startswith("//")
        ]
        section = "\n".join(code_lines)
        for token in ("НР_ВТ", "ПН_ВТ", "ATR_", "SOB6", "Стеклопакет"):
            with self.subTest(token=token):
                self.assertNotIn(token, section)


if __name__ == "__main__":
    unittest.main()
