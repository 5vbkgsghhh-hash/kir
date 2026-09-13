"""A COMPILER refusal names a line of the author's script — or honestly
stays silent.

WHY THIS FILE. The first two touches of the lineage (`bc55252`) carried the
provenance to the edge of the sandbox: `SandboxResult.lineage` carries
`{op id: [lines, outside in]}`. Beyond that the lineage broke off. A
COMPILER refusal arrives when Python has already run successfully — the
program is assembled, and operation forty-one out of sixty fails — and the
model was getting an `op_id` with no indication whatsoever of which line of
ITS OWN code produced that op.

WHAT IS PINNED HERE, AND WHY EXACTLY THIS:

* the address IS SUPPLIED when the key is found EXACTLY;
* the address DISAPPEARS when there is no key — rather than being filled in
  from a neighbor. Form 44 of this tree: a plausible value is more
  dangerous than an absence, because no one argues with it. A refusal that
  names the WRONG line costs the author an entire round of searching in the
  wrong place;
* the format is THE SAME ONE `SandboxRefusal.render()` prints. A second
  format would be a third carrier of the same knowledge: at the very first
  edit to the output, the two texts would drift apart, and the reader would
  get two different meanings under one name;
* the enrichment IS REACHABLE from a live door. A capability that is built
  and not wired in is a named defect of this tree, and one unit test on a
  pure function is not enough for it.
"""
from __future__ import annotations

import asyncio
import unittest

from kir.diag import Diagnostic


class ЧистаяФункцияПодставляетТолькоТочноеСовпадение(unittest.TestCase):
    """The core of the rule: an exact key -> an address; a foreign key ->
    NOTHING."""

    def setUp(self) -> None:
        from kir import serving
        self.name_lines = serving._name_the_author_line

    def test_the_exact_key_gets_its_line(self) -> None:
        diags = [Diagnostic(code="KIR-T002", message_ru="height_mm вне границ",
                            op_id="wall41")]
        out = self.name_lines(diags, {"wall41": [7, 4]}, source={})
        self.assertIn("строка 4", out[0]["message_ru"])

    def test_the_chain_reads_inner_called_from_outer(self) -> None:
        """The arrow reads «строка 4, вызвана из строки 7».

        The direction is NOT chosen here: it is printed by
        `SandboxRefusal.render()` (`reversed(script_frames)`), and a second
        direction under the same name would hand the reader two different
        meanings. The sidecar stores outside-in, printing reverses it — as
        it was before this wave."""
        diags = [Diagnostic(code="KIR-T002", message_ru="x", op_id="wall41")]
        out = self.name_lines(diags, {"wall41": [7, 4]}, source={})
        self.assertIn("цепочка строк скрипта: 4 ← 7", out[0]["message_ru"])

    def test_a_single_frame_prints_no_chain(self) -> None:
        """A chain of one link is not a chain; printing it is just noise."""
        diags = [Diagnostic(code="KIR-T002", message_ru="x", op_id="wall41")]
        out = self.name_lines(diags, {"wall41": [4]}, source={})
        self.assertIn("строка 4", out[0]["message_ru"])
        self.assertNotIn("цепочка", out[0]["message_ru"])

    def test_the_source_text_of_the_line_rides_when_known(self) -> None:
        diags = [Diagnostic(code="KIR-T002", message_ru="x", op_id="wall41")]
        out = self.name_lines(
            diags, {"wall41": [4]},
            source={4: "    create_wall(p0_mm=[0, 0], p1_mm=[6000, 0])"})
        self.assertIn("create_wall(p0_mm=[0, 0]", out[0]["message_ru"])


class КонтрольFAIL(unittest.TestCase):
    """The other side of it: without a key, the address must DISAPPEAR, not
    be filled in."""

    def setUp(self) -> None:
        from kir import serving
        self.name_lines = serving._name_the_author_line

    def test_a_foreign_key_yields_no_address_at_all(self) -> None:
        """The sidecar is full, but for the WRONG op — there must be no
        address.

        This is exactly the outcome a macro produces: one author `stack`
        expands into six operations with foreign keys (`S1_L2_W` versus
        `S1`), and a substitution "by prefix similarity" would name a line
        the author never wrote.
        """
        diags = [Diagnostic(code="KIR-T002", message_ru="height_mm вне границ",
                            op_id="S1_L2_W")]
        out = self.name_lines(diags, {"S1": [7, 4]}, source={})
        self.assertNotIn("строка", out[0]["message_ru"])
        self.assertNotIn("цепочка", out[0]["message_ru"])
        self.assertEqual(out[0]["message_ru"], "height_mm вне границ")

    def test_an_empty_sidecar_changes_nothing(self) -> None:
        """A program written in JSON has no sidecar — and should not."""
        diags = [Diagnostic(code="KIR-T002", message_ru="height_mm вне границ",
                            op_id="W40")]
        out = self.name_lines(diags, {}, source={})
        self.assertEqual(out[0]["message_ru"], "height_mm вне границ")

    def test_a_diagnostic_without_op_id_is_untouched(self) -> None:
        """An envelope refusal is not addressed to an op — there is nothing
        to attribute a line to it with."""
        diags = [Diagnostic(code="KIR-P003",
                            message_ru="неизвестное поле конверта")]
        out = self.name_lines(diags, {"wall1": [4]}, source={})
        self.assertEqual(out[0]["message_ru"], "неизвестное поле конверта")

    def test_a_malformed_sidecar_is_ignored_not_guessed(self) -> None:
        """Garbage in the sidecar means silence, not an attempt to read
        meaning out of it."""
        diags = [Diagnostic(code="KIR-T002", message_ru="x", op_id="w")]
        for junk in ({"w": []}, {"w": None}, {"w": "4"}, {"w": [None]}):
            with self.subTest(junk=junk):
                out = self.name_lines(diags, junk, source={})
                self.assertEqual(out[0]["message_ru"], "x")


class ЖивойСайдкарСовпадаетСКлючамиДиагностик(unittest.TestCase):
    """The sidecar's keys and the refusal's keys are THE SAME on the script
    door.

    This is checked with a REAL sandbox and a REAL compiler, not a
    fixture: the key match is the premise of the entire substitution, and a
    hand-written pair would prove only that the fixture agrees with itself
    (form 48).
    """

    def test_ids_from_the_sandbox_are_the_ids_the_compiler_refuses(self) -> None:
        from kir.sandbox import execute_author_script
        from kir import compile_program

        src = ("def row(n):\n"
               "    for i in range(n):\n"
               "        create_wall(p0_mm=[0, i*100], p1_mm=[6000, i*100],\n"
               "                    level=by_name('L01'),\n"
               "                    height_mm=3000 if i != 2 else 999999999)\n"
               "\n"
               "row(4)\n")
        result = execute_author_script(src)
        self.assertTrue(result.ok, msg=getattr(result.refusal, "code", None))
        self.assertEqual(len(result.lineage), len(result.ops))

        out = compile_program({"ops": result.ops}, revit_version="2023",
                              snapshot={"levels": [{"id": 311, "name": "L01"}]},
                              bulk=True)
        self.assertFalse(out.ok)
        blamed = [d.op_id for d in out.diagnostics if d.op_id]
        self.assertTrue(blamed, "у отказа нет op_id — подставлять не к чему")
        for op_id in blamed:
            self.assertIn(op_id, result.lineage,
                          "ключ отказа не найден в сайдкаре: подстановка "
                          "промолчала бы там, где обязана назвать строку")


class ОбогащениеДостижимоСЖивойДвери(unittest.TestCase):
    """A capability that nobody calls is not built (NAKAZ, item 1).

    A host is not needed here and is not faked "in general": EXACTLY ONE
    port is set (`llm.turn_context`), which the language is missing for
    the gate's third condition, and it is set by the mechanism that
    `ports.register` declares for the test suite itself («the test suite
    may substitute the host»). A skip instead would be honest and useless:
    it does not distinguish "not wired in" from "nowhere to check".
    """

    def setUp(self) -> None:
        import os
        from unittest import mock
        from kir import ports, serving

        class _Turn:
            def kir_mode_active(self) -> bool: return True
            def kir_hold_active(self) -> bool: return False
            def turn_document_title(self) -> str: return "K3_АР.rvt"

        ports.register("llm.turn_context", _Turn)
        self.addCleanup(ports.unregister, "llm.turn_context")

        for key, value in (("KUKAI_KIR_TOOL", "stage2"),
                           ("KUKAI_ADMIN_DEVICES", "dev-under-test")):
            before = os.environ.get(key)
            os.environ[key] = value
            self.addCleanup(
                (lambda k=key, b=before: os.environ.__setitem__(k, b))
                if before is not None
                else (lambda k=key: os.environ.pop(k, None)))

        # A sample from `test_building_verdict_in_the_receipt`: the move's
        # apparatus is substituted, not conjured by the environment.
        patcher = mock.patch.object(serving, "_turn_device_id",
                                    return_value="dev-under-test")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.serving = serving

    def test_the_door_puts_the_author_line_into_a_compiler_refusal(self) -> None:
        program = {"ops": [
            {"op": "create_wall", "id": "wall1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "L01"},
             "height_mm": 999999999},
        ]}

        async def _never(*_a, **_k):            # there must be no bridge here:
            raise AssertionError(              # the compiler's refusal arrives BEFORE
                "мост позван на отказе компилятора")   # any dispatch at all

        res = asyncio.run(self.serving._handle_revit_ir_inner(
            {"program": program}, None, _never,
            query_id="q", bulk=True, authored_in_python=True,
            lineage={"wall1": [7, 4]},
            source_lines={4: "        create_wall(p0_mm=[0, 0])"}))

        self.assertFalse(res.get("ok"))
        text = str(res.get("message_ru") or "") + "".join(
            str(d.get("message_ru") or "") for d in (res.get("diagnostics") or []))
        self.assertIn("строка 4", text)
        self.assertIn("цепочка строк скрипта: 4 ← 7", text)

    def test_without_the_sidecar_the_same_door_names_no_line(self) -> None:
        """FAIL CONTROL at the live door: no sidecar — no address.

        A second run of THE SAME call without `lineage`: if the address
        were coming from somewhere else, it would show up here too."""
        program = {"ops": [
            {"op": "create_wall", "id": "wall1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "L01"},
             "height_mm": 999999999},
        ]}

        async def _never(*_a, **_k):
            raise AssertionError("мост позван на отказе компилятора")

        res = asyncio.run(self.serving._handle_revit_ir_inner(
            {"program": program}, None, _never,
            query_id="q", bulk=True, authored_in_python=True))
        text = str(res.get("message_ru") or "") + "".join(
            str(d.get("message_ru") or "") for d in (res.get("diagnostics") or []))
        self.assertFalse(res.get("ok"))
        self.assertNotIn("строка 4", text)
        self.assertNotIn("цепочка строк скрипта", text)


class ПодписьЗданияДоезжаетДоАвторскогоВхода(unittest.TestCase):
    """`building_digest` is the fifth signature, and it was being lost
    before this fix.

    Its four siblings (`author_digest`, `env_digest`, `model_digest`,
    `params_digest`) reach `_AuthoredInput`; the fifth was computed by the
    sandbox and read by NOBODY. Fixing `as_dict` does not save it:
    `SandboxResult.as_dict()` is never called in production, and
    `_AuthoredInput` is assembled FROM THE OBJECT.
    """

    def test_the_authored_input_carries_it(self) -> None:
        from kir.serving import _AuthoredInput
        self.assertIn("building_digest", _AuthoredInput.__dataclass_fields__,
                      "подпись каталога здания не доезжает до входа автора")

    def test_the_authored_input_carries_the_lineage(self) -> None:
        from kir.serving import _AuthoredInput
        self.assertIn("lineage", _AuthoredInput.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
