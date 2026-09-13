"""A SECOND RUN ON AN ALREADY-STANDING STAIRCASE — what this file guards.

THE NUMBER THIS WAVE IS FOR (the owner's house `LEN_AR_ME_R24`):

    19 staircases total · expressible before this wave: 2 (10.5%) · runs
    per staircase 1-run:2 · 2-run:4 · 3-run:2 · 4-run:10 · 5-run:1 — MODE
    FOUR RUNS

`create_stairs` builds a staircase with EXACTLY ONE run; a landing sits on
an already-standing staircase; there was no second run at all. Run+landing
is expressible, but run+landing+run is not: a hole in the LANGUAGE that kept
a residential building 89.5% inexpressible.

🔴 NOT A SINGLE LIVE RUN, AND THIS IS NAMED, NOT PASSED OVER IN SILENCE. On
15.08 `create_stairs` on the real house blocked Revit's thread with a modal
dialog that no one was there to click. What is proven here is COMPILATION
(gate 6/6) and the SHAPE of the emission, not the build. The line in
`tool_doc.UNPROVEN` carries the same reason.
"""

from __future__ import annotations

import unittest

from kir import spec
from kir.compiler import compile_program
from kir.tests import fixtures

OP = "create_stairs_run"
STAIRS = {"by": "element_id", "value": 4242}


def _op(**over):
    op = {"op": OP, "id": "RN1", "stairs": STAIRS,
          "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
          "base_elevation_mm": 1800.0}
    op.update(over)
    return op


def _prog(*ops):
    return {"ir_version": "1.0", "ops": list(ops)}


def _emit(ver="2023", **over):
    out = compile_program(_prog(_op(**over)), revit_version=ver)
    assert out.ok, [d.message_ru for d in (out.diagnostics or [])]
    return out.csharp


class ОпСобираетсяНаШестиВерсиях(unittest.TestCase):
    """There is NO version branching for this op — and this is a
    MEASUREMENT, not a hope: `CreateStraightRun(Document, ElementId, Line,
    StairsRunJustification)` has existed on all six since 2013 (compiled
    15.08)."""

    def test_все_шесть_версий(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(ver=ver):
                out = compile_program(_prog(_op()), revit_version=ver)
                self.assertTrue(out.ok, [d.message_ru
                                         for d in (out.diagnostics or [])])

    def test_эмиссия_одинакова_на_всех_версиях(self):
        """There is no version branch — so the text must match too. A
        discrepancy here would mean a branch appeared unnoticed."""
        texts = {ver: _emit(ver) for ver in spec.REVIT_VERSIONS}
        first = texts["2021"]
        for ver, text in texts.items():
            self.assertEqual(text, first, f"{ver}: эмиссия разошлась")


class ФабрикаИПривязка(unittest.TestCase):

    def test_зовётся_именно_CreateStraightRun(self):
        self.assertIn("StairsRun.CreateStraightRun(doc,", _emit())

    def test_привязка_уезжает_ИМЕНЕМ_ЧЛЕНА_а_не_числом(self):
        """The canon requires handing C# the enum member's name: then the
        Revit assemblies become the authority, and a typo simply does not
        compile."""
        for word, member in (("center", "Center"), ("left", "Left"),
                             ("right", "Right")):
            with self.subTest(word=word):
                cs = _emit(justification=word)
                self.assertIn(f"StairsRunJustification.{member}", cs)

    def test_умолчание_это_center(self):
        self.assertIn("StairsRunJustification.Center", _emit())


class ОбластьПравкиОткрываетсяНаСтоящейЛестнице(unittest.TestCase):
    """`CreateStraightRun`'s `InvalidOperationException`, verbatim: "not in
    an active StairsEditScope". So the scope is mandatory, and it is
    opened by the single-argument `Start(ElementId)` on an
    ALREADY-STANDING staircase."""

    def test_scope_открыт_и_закрыт(self):
        cs = _emit()
        self.assertIn("new StairsEditScope(doc,", cs)
        self.assertIn("__ess.Start(", cs)
        self.assertIn("__ess.Commit(new __KirStairsFailures())", cs)

    def test_отказ_снимает_ОБА_эффекта_доказанно(self):
        """A typed refusal after Start is legitimate only if the
        transaction returned RolledBack AND the scope is no longer active
        after Cancel."""
        cs = _emit()
        self.assertIn("__rollbackCancel_", cs)
        # The transaction must return RolledBack, AND the scope must stop
        # being active. Returning a refusal while the teardown is unproven
        # is a silent effect under a green answer, which is why it throws
        # there instead of refusing.
        self.assertIn("__rollbackStatus_RN1 != TransactionStatus.RolledBack", cs)
        self.assertIn("return __cancel_RN1(__scope_RN1);", cs)
        for site in ("CreateStraightRun failed",
                     "CreateStraightRun returned null",
                     "postcondition failed"):
            with self.subTest(site=site):
                self.assertIn(f"{site} and rollback/cancel is unproven", cs)

    def test_предупреждения_снимаются_чтобы_не_всплыли_диалогом(self):
        """A modal dialog freezes Revit's UI thread — the very incident
        because of which live runs of this path have been halted."""
        cs = _emit()
        self.assertIn("SetFailuresPreprocessor(new __KirStairsFailures())", cs)
        self.assertIn("SetForcedModalHandling(false)", cs)


class СвидетельЧитаетРЕЗУЛЬТАТ(unittest.TestCase):
    """A postcondition that confirms only the fact of the call is a named
    defect of this tree. Here the witness rereads the built run from the
    document."""

    def test_владелец_и_членство(self):
        cs = _emit()
        self.assertIn(".GetStairs()", cs)
        self.assertIn("GetStairsRuns()", cs)

    def test_ось_марша_сверяется_по_ОБОИМ_направлениям(self):
        """Revit is free to return the path reversed; demanding our own
        order would mean rejecting a correct build."""
        cs = _emit()
        self.assertIn("GetStairsPath()", cs)
        # The mere presence of the names is not enough: they must stand in
        # ONE disjunction, otherwise only one direction gets checked while
        # the other is declared and never asked about.
        self.assertIn("if (__fwd_RN1 || __rev_RN1) __pathHit_RN1 = true;", cs)
        for end, val in (("__ax_RN1", "0.0"), ("__zx_RN1", "3000.0")):
            with self.subTest(end=end):
                self.assertIn(f"Math.Abs({end} - {val})", cs)   # forward
        self.assertIn("Math.Abs(__ax_RN1 - 3000.0)", cs)        # reverse

    def test_Z_НЕ_сравнивается_и_это_объявлено(self):
        """The Z of the path is assigned by Revit from the staircase's
        base. Signing off on an axis that was never set is exactly what
        test_witness_axis_honesty forbids."""
        cs = _emit()
        self.assertIn("ось марша в плане не совпала", cs)
        self.assertNotIn("GetEndPoint(0).Z", cs)

    def test_свидетель_запускается_ДВАЖДЫ(self):
        """Inside the transaction (a violation rolls everything back) and
        AFTER StairsEditScope.Commit on freshly reread objects — the old
        managed wrapper must not pose as a live result."""
        cs = _emit()
        self.assertEqual(cs.count("__check_RN1("), 2)
        self.assertIn("doc.GetElement(__runId_RN1)", cs)

    def test_допуск_ВЫВОДИТСЯ_из_документа(self):
        """A registry constant here would be a bound introduced by
        reasoning; the tolerance is a property of the live document."""
        cs = _emit()
        self.assertIn("MM(doc.Application.VertexTolerance)", cs)


class ОтметкаОтносительнаяИСеткаЖивая(unittest.TestCase):

    def test_Z_оси_берётся_от_базы_лестницы(self):
        cs = _emit()
        self.assertIn("__sbz_RN1", cs)
        self.assertIn("BaseElevation", cs)

    def test_кратность_подступенку_проверяется_ДО_эффекта(self):
        """A run that starts in the middle of a riser is not a staircase.
        The step is a live one, so the refusal NAMES the two nearest
        candidates rather than pointing to documentation."""
        cs = _emit()
        # The step must be READ from the staircase itself, not named
        # somewhere nearby.
        self.assertIn("double __rh_RN1 = MM(__st_RN1.ActualRiserHeight);", cs)
        self.assertIn("double __elevQ_RN1 = 1800.0 / __rh_RN1;", cs)
        self.assertIn("Math.Abs(1800.0 - __elevNorm_RN1) > __dt_RN1", cs)
        self.assertIn("ближайшие кандидаты", cs)


class ОтказыТипизированы(unittest.TestCase):
    """FAIL CONTROL: every invalid input must give a NAMED code, not a
    silent build and not an internal error."""

    def _codes(self, prog, **kw):
        out = compile_program(prog, revit_version="2023", **kw)
        self.assertFalse(out.ok)
        return {d.code for d in (out.diagnostics or [])}

    def test_сосед_в_программе_KIR_L002(self):
        wall = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
                "p1_mm": [1000, 0], "level": {"by": "name", "value": "L1"},
                "height_mm": 3000}
        self.assertIn("KIR-L002",
                      self._codes(_prog(_op(), wall), bulk=True))

    def test_ref_на_соседа_отказан(self):
        """A solo op has no predecessor BY CONSTRUCTION, so `ref` is
        unresolvable, not merely "risky"."""
        self.assertTrue(
            self._codes(_prog(_op(stairs={"by": "ref", "value": "s1"}))))

    def test_чужая_привязка_KIR_T001(self):
        self.assertIn("KIR-T001",
                      self._codes(_prog(_op(justification="middle"))))

    def test_отметка_вне_границ_KIR_T002(self):
        self.assertIn("KIR-T002",
                      self._codes(_prog(_op(base_elevation_mm=-100.0))))
        self.assertIn("KIR-T002",
                      self._codes(_prog(_op(base_elevation_mm=9_999_999.0))))


class ЗакрытияПоРееструЗаговорили(unittest.TestCase):
    """An op added to the registry and not entered into the closures is a
    silent hole. Here it is checked that every closure KNOWS about it."""

    def test_соло_оп_объявлен(self):
        self.assertIn(OP, spec.SOLO_OPS)

    def test_у_соло_опа_есть_свой_шаблон_программы(self):
        from kir import authoring
        self.assertIn(OP, authoring._SOLO_PROGRAMS)
        # The table's keys must match `spec.SOLO_OPS` — otherwise an op
        # would silently end up in someone else's template and receive
        # someone else's emission instead of a refusal.
        self.assertEqual(set(authoring._SOLO_PROGRAMS), set(spec.SOLO_OPS))

    def test_контракт_понижения_полон(self):
        from kir import op_contract
        self.assertTrue(op_contract.contract_for(OP))

    def test_обратный_контракт_назван(self):
        from kir import reverse_contract
        self.assertIn(OP, reverse_contract.REVERSE_CONTRACTS)

    def test_категория_объявлена_СЛЕПОЙ_а_не_угадана(self):
        """An error of blindness is reversible (an upper bound is lost), an
        error of filling-in is not: it rejects an HONEST build. The run's
        category has not been measured against live Revit, so there is no
        row for it in the table."""
        from kir import acceptance
        self.assertIn(OP, acceptance._OPS_BLIND)
        self.assertIsNone(spec.OP_RESULT_CATEGORIES.get(OP))

    def test_клеш_знает_что_оболочки_нет(self):
        from kir import clash_bundle
        self.assertIn(OP, clash_bundle.OP_NO_BODY)

    def test_живая_недоказанность_НАЗВАНА(self):
        """Silence reads as "verified". An op without live evidence must
        sit in UNPROVEN — together with the reason."""
        from kir import tool_doc
        self.assertIn(OP, tool_doc.UNPROVEN)


class НастоящаяЛестницаВыразима(unittest.TestCase):
    """The wave's gate: L-shaped and U-shaped staircases compile in full.
    U-shaped is the MODE of the real house (10 of 19 staircases are
    four-run)."""

    SNAP = fixtures.GROUND_SNAPSHOT

    def _levels(self):
        return [r.get("name") for r in self.SNAP.get("levels", [])][:2]

    def _stairs(self):
        base, top = self._levels()
        return _prog({"op": "create_stairs", "id": "S1",
                      "base_level": {"by": "name", "value": base},
                      "top_level": {"by": "name", "value": top},
                      "p0_mm": [0, 0], "p1_mm": [3000, 0], "width_mm": 1200})

    def _landing(self, k):
        return _prog({"op": "create_stairs_landing", "id": f"LG{k+1}",
                      "stairs": STAIRS,
                      "contour": {"outer": {"shape": "rect",
                                            "origin": [3000.0, 1300.0 * k],
                                            "size_mm": [1200.0, 1200.0]}},
                      "elevation_mm": 1800.0 * (k + 1)})

    def _run(self, k):
        return _prog(_op(id=f"RN{k+1}",
                         p0_mm=[0.0, 1300.0 * k], p1_mm=[3000.0, 1300.0 * k],
                         base_elevation_mm=1800.0 * (k + 1)))

    def _all_compile(self, pack):
        for prog in pack:
            out = compile_program(prog, revit_version="2023",
                                  snapshot=self.SNAP)
            self.assertTrue(out.ok, [d.message_ru
                                     for d in (out.diagnostics or [])])
        return len(pack)

    def test_Г_образная_марш_площадка_марш(self):
        pack = [self._stairs(), self._landing(0), self._run(0)]
        self.assertEqual(self._all_compile(pack), 3)

    def test_П_образная_четыре_марша_три_площадки(self):
        pack = [self._stairs()]
        for k in range(3):
            pack += [self._landing(k), self._run(k)]
        self.assertEqual(self._all_compile(pack), 7)

    def test_каждое_звено_ОТДЕЛЬНАЯ_программа_и_это_закон_Revit(self):
        """Revit does not open two edit scopes at once, so the adjacency
        of two staircase ops is inexpressible BY REVIT, not by taste."""
        out = compile_program(
            _prog(_op(id="RN1"), _op(id="RN2")),
            revit_version="2023", bulk=True)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", {d.code for d in (out.diagnostics or [])})


if __name__ == "__main__":
    unittest.main()
