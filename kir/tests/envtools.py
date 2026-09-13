"""AN ENVIRONMENT FIX WITH A RESTORE THAT SURVIVES A `setUp` FAILURE.

🔴 WHY, BY MEASUREMENT ON 27.08.2026. Eight suite classes were setting
environment variables in `setUp` and restoring them in `tearDown` — and this
worked right up until the day `setUp` learned to FAIL. After the split, its
last line (`enter_kir_mode`) SKIPS the test on an environment with no host,
and `tearDown` is NOT CALLED AT ALL when `setUp` fails. The variables stayed
set, the leak guard in `conftest` correctly turned red on the NEXT tests, and
one skip produced 34 errors in a single file (`test_program_py_door`), 114
across the suite.

The shape of the defect is general and predates the split: **a restore
deferred to `tearDown` is a promise, while `addCleanup` is an obligation.**
The difference only shows when something fails in between.

    from kir.tests.envtools import подменить_env
    подменить_env(self, "KIR_WITNESS_PATH", путь)

The restore is registered BEFORE the assignment: if the assignment itself
fails, there is nothing to restore; if something after it fails, the value
is restored.
"""

from __future__ import annotations

import os
import unittest


def _вернуть(ключ: str, было: str | None) -> None:
    if было is None:
        os.environ.pop(ключ, None)
    else:
        os.environ[ключ] = было


def подменить_env(case: unittest.TestCase, ключ: str, значение: str) -> None:
    """Set the variable and IMMEDIATELY commit to restoring the previous one."""
    case.addCleanup(_вернуть, ключ, os.environ.get(ключ))
    os.environ[ключ] = значение
