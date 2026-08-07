"""Test-only immutable registry variants for mutation oracles."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from types import MappingProxyType
from unittest.mock import patch

from kukai.ir import spec


@contextmanager
def perturbed_tolerance(op_name: str, key: str, value: float):
    """Temporarily install a copied registry with one changed tolerance.

    Production registry objects stay immutable. The oracle still perturbs the
    authority observed by emitters, so a hard-coded emitter value remains
    detectable.
    """
    original = spec.OPS[op_name]
    replacement = replace(
        original,
        tolerances={**original.tolerances, key: value},
    )
    variant = MappingProxyType({
        **spec.OPS,
        op_name: replacement,
    })
    with patch.object(spec, "OPS", variant):
        yield
