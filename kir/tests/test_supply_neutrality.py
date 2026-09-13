"""§18.5 — the law of shipment neutrality. Falsifying tests (§18.7, item
2).

Written BEFORE the fix, and all of them failed at the time of writing: the
compiler's executable code contained the owner's literal device id
(`serving.ADMIN_DEVICE`), an absolute install path for refusal telemetry
(`coverage_feed._DEFAULT`), and an absolute `/root/...` for decompile
output (`extract.DEFAULT_OUTPUT_ROOT`).

What is asserted, specifically:
  * the list of admitted devices belongs to the INSTALLATION (env
    KUKAI_ADMIN_DEVICES), not to the code's author; env set and empty ⇒
    the live path is off;
  * the gate's refusal NAMES the variable that needs to be configured
    (otherwise a third-party developer can never open the reverse path
    at all);
  * an absent path = the feature is off, not a write into someone else's
    filesystem;
  * the default output root does not point into someone else's
    installation.
"""
# 🔴 THE NAMES WERE UPDATED ON 28.08.2026 TOGETHER WITH THE VARIABLES
# THEMSELVES (`kir/env.py`). The old `KUKAI_*` used to stand here. The
# test did not "break" — it caught exactly what it was built for: the
# refusal must name the variable that the reader will set RIGHT NOW, not
# the one it used to be called. The old names are still read, and that
# is guarded by `test_env_names_belong_to_the_language.py`; HERE the
# subject is different — the TEXT a human will see.

from __future__ import annotations

import asyncio
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from kir import coverage_feed, serving
from kir.decompile import extract
from kir.tests.gate_fixture import enter_kir_mode


def _run(coro):
    return asyncio.run(coro)


class _EnvGuard(unittest.TestCase):
    """Saves/restores the env variables this test touches."""

    _VARS: tuple[str, ...] = ()

    def setUp(self) -> None:
        self._saved = {name: os.environ.get(name) for name in self._VARS}

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class AdminDeviceAllowList(_EnvGuard):
    _VARS = ("KUKAI_ADMIN_DEVICES", "KIR_TOOL", "KIR_DECOMPILE")

    def test_env_list_is_parsed_and_trimmed(self) -> None:
        os.environ["KUKAI_ADMIN_DEVICES"] = " dev-a , dev-b ,,"
        self.assertEqual(serving.admin_devices(), ("dev-a", "dev-b"))
        self.assertTrue(serving.is_admin_device("dev-a"))
        self.assertTrue(serving.is_admin_device("dev-b"))
        self.assertFalse(serving.is_admin_device("dev-c"))
        self.assertFalse(serving.is_admin_device(None))

    def test_env_present_but_empty_disables_the_live_path(self) -> None:
        """THE MODE IS SET HERE ON PURPOSE, AND THIS IS A STRENGTHENING,
        NOT A RELAXATION.

        The test's subject is an EMPTY device list. Since 13.08 the gate
        has a third condition, and without the mode, `revit_ir_enabled()`
        is false for TWO reasons at once — meaning green was obtained
        without an act of discrimination: the test would pass even with
        the device check completely broken. By turning the mode on, we
        leave exactly one possible cause of refusal, the very one the
        test was written for.
        """
        enter_kir_mode(self)
        os.environ["KUKAI_ADMIN_DEVICES"] = "   "
        os.environ["KIR_TOOL"] = "stage2"
        os.environ["KIR_DECOMPILE"] = "stage2"
        self.assertEqual(serving.admin_devices(), ())
        with mock.patch.object(serving, "_turn_device_id",
                               return_value="any-device"):
            self.assertFalse(serving.revit_ir_enabled())
            self.assertFalse(serving.revit_decompile_enabled())

    def test_unset_env_is_the_same_as_empty_and_never_guesses_a_device(self):
        """AN UNSET VARIABLE AND ONE SET TO EMPTY ARE THE SAME THING.

        The previous edition was called "unset keeps this installation
        working" and required that `admin_devices()` return
        `_MIGRATION_ADMIN_DEVICE` — the id of THIS machine, hard-coded as
        a literal in a file that gets published as a separate repository.
        On 15.08.2026 the open-source boundary wave removed the literal,
        and there is no longer a fallback: `admin_devices` documents this
        verbatim ("we are not entitled to guess someone else's device").

        🔴 THE TEST WAS REWRITTEN FOR WHAT HAS BEEN ACHIEVED, NOT BENT TO
        FIT A RED RESULT. The difference is checkable: the old
        expectation required the PRESENCE of the literal, the new one
        requires its ABSENCE, and the neighboring test below enforces
        this. The intent has been preserved and strengthened — "the
        compiler carries nobody's device" — whereas bending it to fit
        would have weakened it to "however it turned out".

        The mode is set explicitly for the same reason as in the test
        above: without it, `revit_ir_enabled()` is false for two reasons
        at once, and green would have arrived without an act of
        discrimination.
        """
        enter_kir_mode(self)
        os.environ.pop("KUKAI_ADMIN_DEVICES", None)
        os.environ["KIR_TOOL"] = "stage2"
        self.assertEqual(serving.admin_devices(), ())
        with mock.patch.object(serving, "_turn_device_id",
                               return_value="any-device"):
            self.assertFalse(serving.revit_ir_enabled())

    def test_gate_refusal_names_the_env_variable(self) -> None:
        os.environ["KUKAI_ADMIN_DEVICES"] = ""
        os.environ["KIR_DECOMPILE"] = "stage2"

        async def _never_bridge(method, params):  # pragma: no cover
            raise AssertionError("gate refusal must not touch the bridge")

        for handler in (serving.handle_revit_decompile,
                        serving.handle_revit_rebuild,
                        serving.handle_revit_idempotence):
            result = _run(handler(
                {"action": "status", "doc_stamp": "docA"}, None, _never_bridge))
            self.assertFalse(result.get("ok", True), msg=result)
            self.assertEqual(result.get("error"), "gate", msg=result)
            self.assertIn("KUKAI_ADMIN_DEVICES", result.get("message_ru", ""),
                          msg=result)

    def test_no_device_literal_survives_in_the_compiler(self) -> None:
        """THE RATCHET IS TURNED TOWARD WHAT HAS BEEN ACHIEVED: ZERO
        LITERALS.

        The previous edition required EXACTLY ONE hex-32 literal and the
        presence of the name `_MIGRATION_ADMIN_DEVICE` — it was guarding
        "a second one has not appeared" while the first was considered
        inevitable. On 15.08.2026 the first one was removed: the device
        list is now set only by `KUKAI_ADMIN_DEVICES`, and there is no
        fallback.

        Leaving the test as it was would mean demanding the RETURN of
        the literal into a file that gets published as a separate
        repository — that is, guarding a state that has been rescinded.
        Zero is the same §18.5 rule at the mark that has now been
        reached: nobody's device is hard-coded into the compiler, and it
        will not travel back in.
        """
        source = Path(serving.__file__).read_text(encoding="utf-8")
        self.assertTrue(source.strip(), "исходник не прочитан — это отказ")
        hits = re.findall(r"[\"'][0-9a-f]{32}[\"']", source)
        self.assertEqual(
            hits, [],
            msg=f"в компилятор вернулся литерал устройства: {hits}")
        # 🔴 WHAT IS FORBIDDEN IS BINDING, NOT MENTIONING. The first
        # edition of this line searched for the name itself and went red
        # on a COMMENT explaining why the fallback was removed
        # (`serving.py:102`). Forbidding a mention would forbid
        # documenting one's own history — and a probe that catches the
        # LABEL instead of the branch has already been paid for here
        # more than once. The subject is the assignment and the module
        # attribute; the second is checked by execution, not by reading.
        self.assertIsNone(
            re.search(r"^_MIGRATION_ADMIN_DEVICE\s*=", source, re.M),
            msg="миграционный фолбэк снова ПРИСВАИВАЕТСЯ в компиляторе")
        self.assertFalse(
            hasattr(serving, "_MIGRATION_ADMIN_DEVICE"),
            msg="фолбэк вернулся атрибутом модуля")


class RejectionFeedPath(_EnvGuard):
    _VARS = ("KIR_REJECTIONS_PATH",)

    @staticmethod
    def _one_diagnostic():
        from kir.diag import Diagnostic
        return Diagnostic(
            code="KIR-G001", message_ru="неизвестный вид", op_index=0,
            field_name="kind", got="ost_nonsense")

    def test_no_env_and_no_local_install_writes_nothing(self) -> None:
        # The intent is unchanged: without the env and without its OWN
        # installation, the feed stays silent instead of creating
        # someone else's directory. What carries the condition has
        # changed — before it was an isdir() on an absolute path inside
        # the module itself, now there is a single authority,
        # install_paths, so "no installation of its own" is expressed
        # through it.
        os.environ.pop("KIR_REJECTIONS_PATH", None)
        import tempfile
        from kir import install_paths
        with tempfile.TemporaryDirectory() as bare:
            # a directory without backend/kukai ⇒ install_root() == None
            with mock.patch.object(install_paths, "_INSTALL_ROOT",
                                   Path(bare)):
                self.assertIsNone(coverage_feed._feed_path())
                with mock.patch.object(coverage_feed.os, "makedirs") as makedirs:
                    coverage_feed.record_rejections(
                        [self._one_diagnostic()], [{"op": "create_wall"}])
                makedirs.assert_not_called()

    def test_env_path_is_written(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "kir_rejections.jsonl")
            os.environ["KIR_REJECTIONS_PATH"] = path
            coverage_feed.record_rejections(
                [self._one_diagnostic()], [{"op": "create_wall"}])
            self.assertTrue(os.path.isfile(path))

    def test_module_default_is_not_a_foreign_absolute_path(self) -> None:
        self.assertIsNone(coverage_feed._DEFAULT)


class DecompileOutputRoot(_EnvGuard):
    _VARS = ("KUKAI_DECOMPILE_OUT",)

    def test_env_wins(self) -> None:
        os.environ["KUKAI_DECOMPILE_OUT"] = "/somewhere/else"
        self.assertEqual(
            extract.default_output_root(), Path("/somewhere/else"))

    def test_default_does_not_point_into_a_foreign_installation(self) -> None:
        os.environ.pop("KUKAI_DECOMPILE_OUT", None)
        root = str(extract.default_output_root())
        self.assertFalse(root.startswith("/root"), msg=root)
        self.assertFalse(root.startswith("/opt"), msg=root)
        self.assertEqual(str(extract.DEFAULT_OUTPUT_ROOT), root)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
