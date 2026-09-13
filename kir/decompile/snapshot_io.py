"""Re-export: the model moved to :mod:`kir.model.snapshot_io` (02.09.2026).

The full argument is in the header of `kir/model/__init__.py`; in short:
decompile does not own this model, it is a reader just like the clash
checker, and the shared home inside `decompile/` was holding a package
cycle. The old address is kept NOT temporarily: it is written in dozens of
places and in foreign trees, while the carrier itself is one.
"""
from kir.model.snapshot_io import *  # noqa: F401,F403
from kir.model import snapshot_io as _m
import sys as _sys
_sys.modules[__name__].__dict__.update(
    {k: v for k, v in vars(_m).items() if not k.startswith("__")})
