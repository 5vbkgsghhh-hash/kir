"""THE JUDGE SPEAKS WHEN THE ENVIRONMENT IS SILENT — AND THIS IS A PROPERTY, NOT A SETTING.

🔴 WHY THIS RATCHET WAS SET UP (01.09.2026).

Before this day, the default for `checker_v2_enabled()` was OFF, and the
cost of that is measured, not assumed: an outside person who installed the
package from PyPI got "VERDICT UNAVAILABLE" on the path to construction,
instead of "FIT BY 13 OF 20 RULES". The refusal was honest and named its
cause — and precisely for that reason nobody counted it as a defect: a
named refusal looks like soundness.

The default is ONE character in one line. Reverting it can be done with an
edit that no instrument today would notice: the gates run 6/6 under a host
whose lever is set in `.env`, and the chosen suite never asks about the
judge at all. Hence this file.

WHAT EXACTLY IS GUARDED, AND WHY THREE CLAIMS RATHER THAN ONE

1. A SILENT ENVIRONMENT GIVES v2. This is exactly the property "the judge
   speaks on its own."
2. IT CAN STILL BE TURNED OFF. A default that cannot be reverted is not a
   default, it is baked-in behavior; rollback must remain one word of
   environment.
3. THE OLD NAME IS STILL HEARD. In the owner's live service the lever is
   set under the old name; if changing the default also silenced the
   alias, the service would lose the ability to roll back, and lose it
   SILENTLY.

🔴 WHAT THIS RATCHET DOES NOT CLAIM. It does not say that v2 is BETTER —
that is the measurement in plan §10 (two deliberately bad buildings that
v1 let through; no regression the other way). Here there is only that the
default choice is exactly this, and that both rollbacks are alive.
"""
from __future__ import annotations

import os
import unittest
from contextlib import contextmanager

from kir.checker.flags import checker_v2_enabled

_NEW = "KIR_CHECKER_V2"
_OLD = "KUKAI_CHECKER_V2"


@contextmanager
def _env(**pairs: str | None):
    """Environment for the duration of the block. Release in `finally` is LOAD-BEARING.

    The lever is read LIVE on every call, so a leaked value would make the
    neighboring assertion unverifiable — and unnoticeably so: the test
    would pass while asking something other than what its name says.
    """
    saved = {k: os.environ.get(k) for k in pairs}
    try:
        for k, v in pairs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class СудьяГоворитКогдаСредаМолчит(unittest.TestCase):

    def test_молчащая_среда_даёт_v2(self):
        with _env(**{_NEW: None, _OLD: None}):
            self.assertTrue(
                checker_v2_enabled(),
                "среда молчит, а судья взял ветку v1. Она не умеет сказать "
                "«не определено» (verdict=None, coverage=None), и потому у "
                "читателя пакета вердикта не будет вовсе. Умолчание «1» "
                "куплено замером KIR_PLAN.md §10 и словом владельца 01.09.2026")

    def test_выключить_по_прежнему_можно(self):
        with _env(**{_NEW: "0", _OLD: None}):
            self.assertFalse(
                checker_v2_enabled(),
                "KIR_CHECKER_V2=0 обязан вернуть v1 целиком. Умолчание, "
                "которое нельзя отменить, — зашитое поведение, а не умолчание")

    def test_прежнее_имя_по_прежнему_слышно(self):
        with _env(**{_NEW: None, _OLD: "0"}):
            self.assertFalse(
                checker_v2_enabled(),
                "прежнее имя перестало отключать судью. В живой службе "
                "хозяина рычаг стоит именно под ним, и потеря псевдонима "
                "отняла бы у неё откат — молча")

    def test_новое_имя_побеждает_прежнее(self):
        """Order from `kir/env.py`: a NEW name set explicitly outranks the old one.

        Checked here, not only at `env`, because it is exactly for this
        lever that a mismatch between the two names would cost the
        verdict.
        """
        with _env(**{_NEW: "1", _OLD: "0"}):
            self.assertTrue(checker_v2_enabled())
        with _env(**{_NEW: "0", _OLD: "1"}):
            self.assertFalse(checker_v2_enabled())


class КонтрольСторожаНеВакуумен(unittest.TestCase):
    """🔴 A GUARD THAT CANNOT TURN RED IS WORSE THAN NO GUARD AT ALL.

    The four claims above rest on one function, and if it ever starts
    returning a constant, all four would diverge from the subject
    silently — except one: a constant cannot be both true and false at
    once.
    """

    def test_рычаг_различает_свои_положения(self):
        with _env(**{_NEW: "1", _OLD: None}):
            включено = checker_v2_enabled()
        with _env(**{_NEW: "0", _OLD: None}):
            выключено = checker_v2_enabled()
        self.assertNotEqual(
            включено, выключено,
            "рычаг отвечает ОДИНАКОВО в обоих положениях — значит он больше "
            "ничего не решает, и все утверждения этого файла вакуумны")


if __name__ == "__main__":
    unittest.main()
