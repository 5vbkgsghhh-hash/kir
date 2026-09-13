"""The gate's refusal names THE reason that actually refused.

WHY. On 13.08.2026 the `revit_ir_enabled` gate got a third condition — an
explicit sign of KIR mode on the turn (the operator's decision: KIR is a
separate mode, not an ordinary chat tool). The refusal text stayed the
same, one text for all reasons, and it pointed at the DEVICE LIST:

    what refused     the third condition, `kir_mode_active()`
    what was named    the second one, `KUKAI_ADMIN_DEVICES`

Found by THE GATE while sorting through 110 red items on the merged line:
the first thing they did was go check `admin_devices()`, because the
message points there, and they spent a separate pass on an innocent
module. **Anyone who reads this message will add a device id, and nothing
will change.**

This is our named class in the diagnostics channel: the value that named
the reason is not the one that decided. And this is also the flip side of
the law "an error carries its own remedy": an error naming an
UNACTIONABLE step is worse than one that names none at all.

WHAT IS PINNED HERE. Not the wording, but DISTINGUISHABILITY: three reasons
must produce three DIFFERENT texts, and each must point to its own. The
test will survive any rewording as long as the distinction is preserved.
"""
# 🔴 THE NAMES WERE UPDATED ON 28.08.2026 ALONG WITH THE VARIABLES
# THEMSELVES (`kir/env.py`). The old `KUKAI_*` used to stand here. The test
# did not "break" — it caught exactly what it was set up for: a refusal
# must name the variable that the reader will set RIGHT NOW, not the one it
# used to be called. The old names are still read, and that is guarded by
# `test_env_names_belong_to_the_language.py`; HERE the subject is
# different — the TEXT a human will see.


from __future__ import annotations

import os
import unittest

from kir import serving
from kir.serving import admin_gate_message_ru

ADMIN = "test-device-id-0000000000000000"


class TheRefusalNamesTheConditionThatFailed(unittest.TestCase):

    def setUp(self) -> None:
        self._env = {k: os.environ.get(k)
                     for k in ("KIR_TOOL", "KUKAI_ADMIN_DEVICES")}
        os.environ["KIR_TOOL"] = "stage2"
        os.environ["KUKAI_ADMIN_DEVICES"] = ADMIN

    def tearDown(self) -> None:
        # We restore what was OBSERVED, not a remembered constant.
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            from kir import ports as _п; publish_kir_mode = _п.need(_п.TURN_CONTEXT).publish_kir_mode
            publish_kir_mode(False)
        except Exception:  # noqa: BLE001
            pass

    def _mode(self, on: bool) -> None:
        """Either set KIR mode — or SKIP the test with a named reason.

        🔴 MODE IS A HOST CONCEPT, NOT A LANGUAGE ONE (28.08.2026). The flag
        lives in the product's `ContextVar` and arrives through the
        `llm.turn_context` port. In standalone KIR there is no such
        supplier, and `need` was throwing `PortMissing` in the middle of
        the test — a refusal ABOUT US, in the voice of an assertion about
        whether the gate names the right reason. The cleanup below has
        been catching this exception since 24.08; here it was not being
        caught, and three checks were failing instead of being skipped.
        """
        from kir import ports as _п

        try:
            publish_kir_mode = _п.need(_п.TURN_CONTEXT).publish_kir_mode
        except _п.PortMissing as exc:                    # pragma: no cover
            self.skipTest("режим КИР — понятие ХОСТА: " + str(exc))
        publish_kir_mode(on)

    def test_no_flag_names_the_flag(self) -> None:
        os.environ["KIR_TOOL"] = "off"
        msg = admin_gate_message_ru("revit_ir")
        self.assertIn("KIR_TOOL", msg)
        self.assertNotIn("KUKAI_ADMIN_DEVICES", msg,
                         "отказ по флагу отправляет настраивать устройства")

    def test_no_mode_names_the_mode_and_never_the_device_list(self) -> None:
        """THE MAIN ASSERTION this test was written for.

        The flag is on, devices are set — only the mode can refuse. The
        message must speak about the mode and is NOT REQUIRED to send the
        reader to the device list: it was exactly this false route that
        cost THE GATE a separate pass.
        """
        self._mode(False)
        msg = admin_gate_message_ru("revit_ir")
        self.assertIn("РЕЖИМ", msg)
        self.assertNotIn("KUKAI_ADMIN_DEVICES", msg,
                         "отказ по режиму снова отправляет в список устройств")

    def test_empty_device_list_names_the_list(self) -> None:
        self._mode(True)
        os.environ["KUKAI_ADMIN_DEVICES"] = ""
        msg = admin_gate_message_ru("revit_ir")
        self.assertIn("KUKAI_ADMIN_DEVICES", msg)
        self.assertIn("пуст", msg)

    def test_the_three_texts_are_pairwise_DIFFERENT(self) -> None:
        """Distinguishability, not wording: what is pinned is that three
        reasons give three DIFFERENT answers. Rewording does not break
        this test."""
        texts = []
        os.environ["KIR_TOOL"] = "off"
        texts.append(admin_gate_message_ru("revit_ir"))
        os.environ["KIR_TOOL"] = "stage2"
        self._mode(False)
        texts.append(admin_gate_message_ru("revit_ir"))
        self._mode(True)
        os.environ["KUKAI_ADMIN_DEVICES"] = ""
        texts.append(admin_gate_message_ru("revit_ir"))
        self.assertEqual(len(set(texts)), 3,
                         f"причин три, различных текстов {len(set(texts))}")

    def test_the_order_here_matches_the_gate(self) -> None:
        """The order of checks in the message and in the gate is one and
        the same.

        Should they diverge, the message would again start naming the
        wrong condition: the gate would refuse on the first, while the
        text would report on the second. What is pinned is the SOURCE, not
        a memorized copy.
        """
        import ast
        import inspect
        import textwrap

        def body_text(fn) -> str:
            """The function BODY without its docstring.

            The first edition of this test indexed the raw `getsource` —
            and landed inside the DOCSTRING, where `kir_mode_active` is
            mentioned before `_FLAG`. A match by appearance instead of a
            match by subject, in a test written against exactly this class
            of defect.
            """
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            fn_node = tree.body[0]
            stmts = fn_node.body
            if (stmts and isinstance(stmts[0], ast.Expr)
                    and isinstance(stmts[0].value, ast.Constant)
                    and isinstance(stmts[0].value.value, str)):
                stmts = stmts[1:]
            return "\n".join(ast.unparse(s) for s in stmts)

        gate = body_text(serving.revit_ir_enabled)
        msg = body_text(serving.admin_gate_message_ru)
        for token in ("_FLAG", "kir_mode_active", "admin_device"):
            self.assertIn(token, gate, f"{token} исчез из ТЕЛА гейта")
        # In the message, the flag is the PARAMETER `flag`, not a
        # constant: there are two gates, and only the caller knows which
        # one refused.
        self.assertLess(msg.index("os.environ.get(flag"),
                        msg.index("kir_mode_active"),
                        "в сообщении режим проверяется раньше флага")
        self.assertLess(msg.index("kir_mode_active"),
                        msg.index("admin_devices"),
                        "в сообщении устройства проверяются раньше режима")


class TheMessageAsksTheGateThatActuallyRefused(unittest.TestCase):
    """THERE ARE TWO GATES, AND ONE MESSAGE FOR BOTH.

    `revit_ir` stands behind `revit_ir_enabled` (flag `KIR_TOOL` + mode +
    device). `revit_decompile` / `revit_rebuild` / `revit_idempotence`
    stand behind `revit_decompile_enabled` (flag `KIR_DECOMPILE`, NO mode).

    The first edition of the fix baked the FIRST gate's conditions into
    the shared message, and the decompile refusal started naming a
    foreign flag and a condition it does not even have. **The fix
    committed the exact defect it was fixing, one floor up.** Caught by
    THE GATE, not by the author.

    THE SECOND EDITION OF THIS SAME FILE COMMITTED IT A THIRD TIME, and
    here is how. `test_the_decompile_message_names_its_own_flag` asserted
    the "flag not set" branch WITHOUT CONTROLLING the flag: the value came
    from the environment. Run alone, the file is green (no flag); run
    alongside any test under `tests/`, it is red — `tests/conftest.py`
    pulls in the prod `.env`, where `KIR_DECOMPILE=stage2` (measured on
    13.08 with a probe on every test: the flag is already `stage2` BEFORE
    the run's first test, meaning it is set on import, not by a neighbor).
    The test was passing BY CONSTRUCTION OF THE ENVIRONMENT, not by a
    property of the code — the value deciding the outcome was set
    somewhere other than where it was being asserted.

    So here the flag is set EXPLICITLY, both ways, and both ways are
    checked: off ⇒ the message names ITS OWN flag; on ⇒ it does not name
    it at all, because it was not the one that refused. The "off/on" pair
    is itself the act of distinction: without it, a green cannot be told
    apart from a green-by-default.
    """

    def setUp(self) -> None:
        self._env = {k: os.environ.get(k)
                     for k in (serving._DECOMPILE_FLAG, "KUKAI_ADMIN_DEVICES")}
        # We pin the devices so the "flag is fine" branch stays the same
        # regardless of what the prod `.env` left in the environment.
        os.environ["KUKAI_ADMIN_DEVICES"] = ADMIN

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _flag(self, on: bool) -> None:
        if on:
            os.environ[serving._DECOMPILE_FLAG] = "stage2"
        else:
            os.environ.pop(serving._DECOMPILE_FLAG, None)

    def _msg(self) -> str:
        return serving.admin_gate_message_ru(
            "revit_decompile", flag=serving._DECOMPILE_FLAG, needs_mode=False)

    def test_the_decompile_message_names_its_own_flag(self) -> None:
        self._flag(False)
        msg = self._msg()
        self.assertIn("KIR_DECOMPILE", msg)
        self.assertNotIn("KIR_TOOL", msg, "назван чужой флаг")

    def test_with_the_flag_on_the_message_stops_naming_it(self) -> None:
        """A CONTROL IN THE OTHER DIRECTION: the one that REFUSED is
        named.

        Without this test, the first one is green even for a message that
        ALWAYS names its own flag — that is, even after reverting to
        exactly the defect the function was rewritten to fix.
        """
        self._flag(True)
        msg = self._msg()
        self.assertNotIn("KIR_DECOMPILE", msg,
                         "назван флаг, который не отказывал")

    def test_the_decompile_message_never_speaks_of_a_mode(self) -> None:
        """This gate has NO mode — mentioning it means sending the reader
        to turn on something that does not exist."""
        self._flag(True)
        self.assertNotIn("РЕЖИМ", self._msg())

    def test_every_call_site_names_the_gate_it_stands_behind(self) -> None:
        """THE LIST OF SITES IS COMPLETE BY CONSTRUCTION: an AST walk over
        `serving.py`.

        A site added tomorrow will fall under the check on its own. The
        rule: decompile tools must name their flag explicitly; `revit_ir`
        sites are entitled to rely on the default that describes THEIR
        gate.
        """
        import ast
        import pathlib
        src = pathlib.Path(serving.__file__).read_text(encoding="utf-8")
        decompile = {"revit_decompile", "revit_rebuild", "revit_idempotence"}
        seen = set()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else getattr(fn, "id", ""))
            if name != "admin_gate_message_ru" or not node.args:
                continue
            arg = node.args[0]
            if not isinstance(arg, ast.Constant):
                continue
            inst = str(arg.value).split(" ")[0]
            kw = {k.arg for k in node.keywords}
            seen.add(inst)
            if inst in decompile:
                self.assertIn("flag", kw, f"{inst} не назвал свой флаг")
                self.assertIn("needs_mode", kw,
                              f"{inst} не снял условие режима")
        self.assertEqual(seen & decompile, decompile,
                         f"обход не нашёл все площадки декомпиляции: {seen}")


if __name__ == "__main__":
    unittest.main()
