"""A control for the HELPER, and it cannot be derived from the green of the
95 tests the helper is given to.

WHY A SEPARATE FILE. `gate_fixture.enter_kir_mode` opens the gate's third
condition for ninety-five tests. **A dummy helper would turn them all
green** — wrong key, wrong context, wrong scope — and would turn them green
FOR NOTHING: the gate would still be refusing, only nobody would notice.

    ninety-five greens with no act of distinguishing
    are WORSE than ninety-five reds: reds are visible, these are not

So the helper has its own control, and it is two-sided. One side is not
enough: "open with the helper" is also true of a helper that does nothing,
if the path was already open without it. Only the second line tells them
apart.

    control-PASS   helper called      -> revit_ir_enabled() is True
    control-FAIL   helper NOT called  -> revit_ir_enabled() is False

Both conditions, aside from the third, are set here BY HAND — otherwise the
control would be checking someone else's fixture instead of the helper.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from kir import serving
from kir.tests.gate_fixture import enter_kir_mode


class TheHelperOpensTheThirdConditionAndOnlyIt(unittest.TestCase):

    def setUp(self) -> None:
        # We restore what was OBSERVED, not a remembered constant.
        self._env = {k: os.environ.get(k)
                     for k in ("KUKAI_KIR_TOOL", "KUKAI_ADMIN_DEVICES")}
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._dev = mock.patch.object(serving, "_turn_device_id",
                                      return_value=serving.ADMIN_DEVICE)
        self._dev.start()

    def tearDown(self) -> None:
        self._dev.stop()
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_without_the_helper_the_gate_is_shut(self):
        """FAIL control, and it is the main one here.

        The flag is set, the device is an admin one — only the MODE can
        refuse. If this assertion ever turns green without the helper, it
        means the path is open by something else, and all ninety-five
        "fixed" tests pass not thanks to the fixture but around it.
        """
        self.assertFalse(
            serving.revit_ir_enabled(),
            "гейт открыт БЕЗ третьего условия — либо режим утёк из соседнего "
            "теста, либо гейт перестал его требовать; в обоих случаях помощник "
            "ничего не доказывает")

    def test_with_the_helper_the_gate_opens(self):
        """PASS control: the helper actually sets the flag."""
        enter_kir_mode(self)
        self.assertTrue(
            serving.revit_ir_enabled(),
            "помощник вызван, а гейт закрыт — фикстура пустышка")

    def test_the_helper_restores_what_it_observed(self):
        """The flag lives in a `ContextVar`; not restoring it turns neighbors green.

        What is checked is PRECISELY the restore, not the setting: a test
        that leaves the mode turned on fixes global state on behalf of
        others — the very crutch we pulled out of `test_any_query`, and it
        masks someone else's defect.
        """
        from kir.tests.gate_fixture import _ХОД as _тк
        if _тк is None:
            self.skipTest('порт llm.turn_context не поставлен')
        kir_mode_active = _тк.kir_mode_active

        before = kir_mode_active()
        case = unittest.TestCase()
        case.setUp()
        enter_kir_mode(case)
        self.assertTrue(kir_mode_active(), "помощник не поставил признак")
        case.doCleanups()
        self.assertEqual(kir_mode_active(), before,
                         "помощник не вернул наблюдённое значение")


if __name__ == "__main__":
    unittest.main()
