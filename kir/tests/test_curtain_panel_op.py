"""``set_curtain_panel`` — the straightforward side (designed 2026-07-28).

A curtain wall panel cannot be created on its own: it exists only as a
CELL of the host's grid. So the op assigns a type to the cell rather than
"building a panel," and what needs checking is exactly what can silently
break for an op like this:

* the cell address is mandatory and integer — 1×1 is (0,0), not "can be
  omitted";
* the witness reads the RESULT at the address, not the element the call
  returned (``ChangePanelType`` returns the replaced element — checking
  against it would only prove the call happened);
* every create-block guard is written with THE EXACT SAME phrase that
  per-op isolation rewrites: otherwise one cell's refusal would drag the
  whole program down with it, and a compile test would never notice.
"""

# 04.08.2026: the object's class is read by the ``__ClassName`` helper
# from the preamble, rather than by asking the runtime for the type — the
# old idiom is rejected outright by the version-bridge safety validator as
# of 06.07.2026 (a live refusal on Revit 2023, «Заблокировано: GetType()
# (runtime type resolution)»). All the checks below kept THEIR OWN
# contract (the exception type is named, the inner exception is carried
# through, the evidence carries the operands' classes) — only the way it
# is written down changed.
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import ground as ground_mod  # noqa: E402
from kir import spec  # noqa: E402
from kir.authoring import (  # noqa: E402
    _EMITTERS, curtain_cell_address_cs, emit_program)
from kir.compiler import _parse_and_check, compile_program  # noqa: E402
from kir.diag import KirRefusal  # noqa: E402
from kir.emit_model import post_to_string  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

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
        """ONE definition of the address: the emitter and the capture
        compute it with the same code."""

        decl, _create, _post, _readback = _emit(_cell_op())
        self.assertIn(curtain_cell_address_cs("CP1").strip(), decl)

    def test_two_cells_in_one_program_do_not_collide(self) -> None:
        """Address helpers are named after the op: two cells mean two
        copies, not a CS0128."""

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
        """The element that `ChangePanelType` returned cannot serve as the witness."""

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
        """In atomic emission EVERY cell refusal rolls back the
        transaction.

        Before 28.07.2026 this was a requirement on the PHRASE: per_op
        rewrote it as text, and a guard written differently would silently
        preserve the semantics of the entire program inside the
        SubTransaction.  Nobody owns the phrase anymore
        (emit_utils.refuse_stmt), but the rule itself stayed substantive: a
        cell's refusal inside one transaction must be a rollback, not a
        bare return — `refuses == rewritable` catches exactly this.  The
        shared isolation contract lives in test_emission_guard_contract.
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
        # The one and only `return __Refuse` in the whole program is the
        # transaction's shared prologue, not a cell guard.
        self.assertNotIn("__t.RollBack(); return __Refuse(\"CP1\"", body)


class TheGridIsRegeneratedBeforeItIsRead(unittest.TestCase):
    """A curtain wall's grid is born from a regeneration, not from a call
    to Wall.Create.

    MEASURED 28.07 (live trials on façade SOB6.2, Revit 2023):
      * P1 — a SINGLE curtain wall, the exact coordinates of the failed
        chunk: ok, witness 3/3. So the wall itself is not at fault;
      * P4 — the same wall + our op in ONE transaction: KIR-X003,
        «ChangePanelType: » and an empty Revit message.

    The only difference between the trials is being neighbors inside one
    transaction, so a ``doc.Regenerate()`` is placed before any work with
    the grid. The precedent is the same one set by ``_symbol_res``
    (Activate + Regenerate) and by CONNECT (connectors are only read after
    a regen).
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
        """A failed regen means a corrupted document (per the SDK
        documentation).

        Swallowing it would mean continuing to work in a document that
        Revit has already declared unfit even to read.
        """

        _decl, create, _post, _readback = _emit(_cell_op())
        head = create[:create.index("__ccGrids")]
        self.assertNotIn("try", head)
        self.assertNotIn("catch", head)


class TheTypeDrivenPanelIsUnlockedFirst(unittest.TestCase):
    """Revit keeps a panel spawned by the host's type LOCKED.

    MEASURED 28.07, live trials on façade SOB6.2 (Revit 2023) — both
    returned THE SAME cause, which closed the fork:

        P6 (the host ALREADY exists, WallType 273445):
          «ChangePanelType: InvalidOperationException: (пустое сообщение
           Revit) | ячейка (0,0) панель 11401342 (Panel),
           РАЗБЛОКИРОВАНА=НЕТ, новый тип 273445 (WallType), носитель
           11401341»
        P7 (one transaction, PanelType 273243): the same, unlocked=no.

    P6 removed the transaction (the host was ready and regenerated), P7
    removed the type view. One thing was left — the LOCK. The SDK's
    failure dictionary names this class outright: ``BuiltInFailures.
    CurtainWallFailures.TypePanelsFronNonRectCellsUnlocked`` — «Type-driven
    panels … were UNLOCKED and left unchanged».

    The unlocking here reproduces the author's own action: all 53 lifted
    cells of the façade are REPLACED, meaning in the original they were
    unlocked by hand. The panel is not locked back afterward — it was
    never locked in the source either.
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
        """We unlock ONLY what is locked: the state is read, not assumed."""

        _decl, create, _post, _readback = _emit(_cell_op())
        head = create[:create.index("__cp_CP1.Pinned = false;")]
        self.assertIn("GetUnlockedPanelIds", head)
        self.assertIn("__cpn_CP1 = __cp_CP1.Pinned;", head)
        self.assertIn("if (__clk_CP1 || __cpn_CP1)", head)

    def test_an_unlock_that_fails_is_a_typed_refusal_not_a_silence(
            self) -> None:
        """A cell class may have no unlocking at all — then say so
        outright.

        Per the SDK documentation, ``Element.Pinned`` throws an
        InvalidOperationException «Element cannot be pinned or unpinned»;
        swallowing it would mean going into ChangePanelType with a panel
        already known to be locked and getting back an empty exception.
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
        # the state is read from WHATEVER NOW OCCUPIES the cell (__co_),
        # not from the operand before the change: after switching to a
        # wall type these are different elements (see
        # ChangingTheTypeReplacesTheElement)
        self.assertIn("__co_CP1.Pinned", readback)

    def test_unlocking_works_for_a_wall_filled_cell_too(self) -> None:
        """``GetPanelIds`` returns both ``Panel`` and ``Wall`` (per the SDK
        documentation), so the unlocking verb is taken from ``Element``:
        ``Panel`` has no lock setter at all (``Lockable`` is read-only),
        while ``Lock`` lives on ``Mullion``. One code path for both cell
        classes."""

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertNotIn(".Lockable", create)
        self.assertNotIn(".Lock =", create)
        self.assertIn("__cp_CP1.Pinned = false;", create)


class TheFailureNamesItself(unittest.TestCase):
    """An empty piece of evidence is also a defect.

    The live trial P4 returned exactly «ChangePanelType: » — Revit threw
    with an EMPTY Message, and the refusal named neither the exception
    class, nor the panel, nor the type. An hour of guessing instead of a
    second of reading; the refusal now carries everything that tells the
    cases apart.
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
        """The panel's class and the type's class + the lock: GetPanelIds,
        per the SDK documentation, returns both ``Panel`` and ``Wall``, and
        ``GetUnlockedPanelIds`` exists precisely because a locked panel
        cannot be changed."""

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
        """The evidence has no right to break the per_op rewrite."""

        _decl, create, _post, _readback = _emit(_cell_op())
        refuses = create.count("return __Refuse(")
        rewritable = create.count("__t.RollBack(); return __Refuse(")
        self.assertGreater(refuses, 0)
        self.assertEqual(refuses, rewritable)


class ChangingTheTypeReplacesTheElement(unittest.TestCase):
    """Changing a cell's type is a REPLACEMENT of the element, not an
    in-place edit.

    MEASURED 28.07, live trial P8 (after unlocking): the exception
    DISAPPEARED, ChangePanelType executed, geometry/topology came back
    green — and the witness caught the semantics: «P8C: the panel type at
    the cell does not equal the requested one». The old cell was being
    read, and after switching to a WALL type it is no longer in the grid.

    The SDK documentation: «If operation succeeds, **the modified panel
    element is returned**». The return value is the id of whatever now
    occupies the cell, not a claim about state: the state is re-read from
    the model after a Regenerate regardless. A twin of the ChangeTypeId
    lesson ("the real id = the element was replaced").
    """

    def test_the_returned_element_is_captured(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("__cn_CP1 = __cg_CP1.ChangePanelType(", create)

    def test_the_witness_does_not_read_the_old_reference(self) -> None:
        """__cp_ is the operand BEFORE the change; afterward it may not be
        in the grid at all."""

        _decl, _create, post, readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        self.assertNotIn("__ccEffTypeCP1(__cp_CP1)", rendered)
        self.assertNotIn("__ClassName(__cp_CP1)", readback)
        self.assertIn("__ccEffTypeCP1(__co_CP1)", rendered)

    def test_the_returned_element_is_accepted_only_inside_this_grid(
            self) -> None:
        """We accept the reference from the call only after confirming it
        is IN THE GRID — otherwise it would be an echo of the call instead
        of a read of the model."""

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
        """A WALL cell has no Host property — membership is proven by the
        grid's own panel list. For a FamilyInstance the strong Host
        reference check still stands."""

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
        """After a replacement it is too late to read the Id off a dead reference."""

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("__cpi_CP1 = __cp_CP1.Id.ToString();", create)
        self.assertLess(create.index("__cpi_CP1 = __cp_CP1.Id.ToString();"),
                        create.index("ChangePanelType"))


class TheRequestedTypeIsChasedNotAssumed(unittest.TestCase):
    """ChangePanelType builds a wall of the WRONG type — silently.

    MEASURED 28.07, direct experiments on live host 11401341:

      E1  ChangePanelType(panel, WallType 273445) returned id=11401344,
          class Wall, type **7469627** — the host's split type, not the
          requested 273445. No exception, no refusal. A repeat call
          idempotently returns that same foreign wall.
      E3  `ret.ChangeTypeId(273445)` returned **-1** (InvalidElementId),
          the type became 273445 and survived a Regenerate.

    The SDK documentation describes exactly our case (Element.ChangeTypeId):
    «In rare cases, applying a change in type will result in a new element
    being created. The ONLY active examples of this are when applying a
    normal wall type to a curtain panel, or converting such a wall back to a
    curtain panel. In this situation the new element id is returned.» And
    about the return value: «The new element id if new element is created,
    or **InvalidElementId if the element's type changed without creating a
    new element**» — meaning -1 is an ORDINARY SUCCESS, our twin lesson.
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
        """The twin lesson: -1 means "the type changed without replacing the element"."""

        _decl, create, _post, _readback = _emit(_cell_op())
        chase = create[create.index("ChangeTypeId"):]
        self.assertIn("ElementId.InvalidElementId.ToString()", chase)
        # the new id is read ONLY when it is not -1
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
    """A wall occupant NEVER appears in the grid's panel list.

    MEASURED 28.07 (E2, transaction COMMITTED): after switching a cell to
    a wall type, `GetPanelIds()` still holds the old auto-panel 11401342
    (class Panel, type 1715); the wall 11401344 is alive, but it is not in
    the list — not after a Regenerate, not after a Commit. This is Revit's
    own record for returning the cell to type-driven, living in parallel
    with the occupant.

    Which means the check "the occupant is a member of the panel list" is
    ALWAYS A FALSE NEGATIVE for a wall — and P8 failed on exactly this: the
    fallback returned the addressed old panel, it had the old type, and the
    witness honestly complained.

    The binding was measured: the midpoint of the occupant wall's axis
    projects onto the host's axis at a distance of 0.0 mm (E2). A 50 mm
    tolerance is for curved hosts.
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
        """THE PRE-STATE: on the previous emission this branch asked
        GetPanelIds and was a false negative for every wall cell."""

        _decl, _create, post, _readback = _emit(_cell_op())
        rendered = post_to_string("CP1", post)
        tail = rendered[rendered.index("FamilyInstance __cfi_CP1"):]
        else_branch = tail[tail.index("else"):]
        self.assertIn("__ccAxisCP1(__co_CP1)", else_branch)
        self.assertNotIn("GetPanelIds", else_branch,
                         "членство в списке панелей для стены — всегда ложь")


class OnlyWhatWeCreatedIsStampedAndCounted(unittest.TestCase):
    """The stamp is for what was created; `id` is identity; `created` is
    birth.

    MEASURED 28.07, rebuild #5 (artifact v10): a clean cycle, the REBUILT
    phase arrived, and the next layer failed — RECONCILED: «run-prefix
    reconciliation disagrees with commit receipts». The stamp census sees
    exactly what was STAMPED, while the cell was occupied by a NEW element
    (`ChangePanelType` with a wall type gives birth to a wall), which
    traveled in created_ids but carried no stamp. 54 such ops in the plan.

    The other side, and why the condition is "only what was created": A5
    DELETES by stamp. Tagging a cell that existed before us (the type
    changed in place, the same element) would mean declaring someone
    else's element our own and tearing it down during cleanup.
    """

    def test_the_new_occupant_is_stamped(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        stamp = create[create.index("ChangeTypeId"):]
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", stamp)
        self.assertIn("__cn_CP1", stamp)

    def test_an_in_place_type_change_is_not_stamped(self) -> None:
        """The stamp's condition is "the occupant's id differs from the previous one"."""

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn(
            'if (__cn_CP1 != null && __cn_CP1.Id.ToString() != __cpi_CP1)',
            create)

    def test_the_stamp_comes_after_the_type_is_final(self) -> None:
        """Stamping before the type catch-up would mean stamping an
        intermediate element that the catch-up might replace yet again."""

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
        """A cell's type lives both among family type-sizes and among wall
        types.

        A cell filled by a wall is the façade's norm (259 out of 361 on
        the measurement model), and its type is a WallType, which is not a
        FamilySymbol.
        """

        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("OfClass(typeof(FamilySymbol))", create)
        self.assertIn("OfClass(typeof(WallType))", create)

    def test_zero_and_several_matches_are_both_typed_refusals(self) -> None:
        _decl, create, _post, _readback = _emit(_cell_op())
        self.assertIn("Count == 0", create)
        self.assertIn("Count > 1", create)

    def test_host_accepts_both_a_ref_and_a_pinned_id(self) -> None:
        """The design writes `host: ref|element_id` — both forms must be supported."""

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
        """INVARIANT #1: not one name from the measurement model appears
        in the registry/emitter.

        The recognition rule is structural (type against the default
        type), and the compiler is going open source — a list of familiar
        names would turn it into a compiler for ONE building.
        """

        from pathlib import Path
        emitter = Path(__file__).resolve().parents[1] / "authoring.py"
        source = emitter.read_text(encoding="utf-8")
        start = source.index("CURTAIN_CELL_ADDRESS_CS = ")
        end = source.index("_EMITTERS = {", start)
        # What is checked is the EXECUTABLE text, not the provenance of
        # facts. A comment must name the model and the measurement date —
        # that is exactly what "measure, don't recall" lives on; a model
        # name is forbidden IN THE RULE, because a rule with a list of
        # familiar names is a compiler for one building. The first edition
        # of the test also cut comments, meaning it demanded anonymous
        # measurements: provenance and hardcoding are different things.
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
