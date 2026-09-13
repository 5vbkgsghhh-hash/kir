"""Re-export: the model moved to :mod:`kir.model.identity` (02.09.2026).

The full argument is in the header of `kir/model/__init__.py`; in short: this
decompile does not own the model — it is a reader, just like clash, and the
shared home inside `decompile/` held a package cycle. The old address is kept
NOT temporarily: it is written in dozens of places and in other trees, while
the carrier itself stays one.
"""
from kir.model.identity import *  # noqa: F401,F403
from kir.model import identity as _m
import sys as _sys
_sys.modules[__name__].__dict__.update(
    {k: v for k, v in vars(_m).items() if not k.startswith("__")})
