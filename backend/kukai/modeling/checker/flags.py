"""Feature flag for the geometry-first checker rebuild (checker v2).

Read DIRECTLY from the environment on every call (no import-time caching, no
kukai.config coupling): the operator flips `KUKAI_CHECKER_V2=1` on the service and the
very next check runs the v2 path — derivation pre-pass, three-valued verdict, coverage
section, declaration-consistency rules. Default OFF: the legacy (v1) checker behaviour
is bit-for-bit preserved so this can land in prod dark.

Kept in its own module so every checker/generator module gates on ONE reviewable
switch instead of scattering os.environ reads.
"""
from __future__ import annotations

import os


def checker_v2_enabled() -> bool:
    """True iff the geometry-first checker v2 path is switched on (env, read live)."""
    return os.environ.get("KUKAI_CHECKER_V2", "0") == "1"
