"""Drift guard: the canonical exec wrapper copied into the modeling package
(``kukai.modeling.bridge.exec_wrapper``) MUST stay byte-for-byte identical to the
live backend's ``kukai.api.chat_ws._WRAPPER_HEADER`` / ``_WRAPPER_FOOTER`` — that
is the wrapper the live bridge actually applies before compile/execute, so any
divergence silently breaks L3==L4 equivalence.

We extract the backend constants WITHOUT importing chat_ws (which would pull in
FastAPI/websockets) by parsing its source with ``ast`` and literal-eval'ing the
implicitly-concatenated string literals.
"""
from __future__ import annotations
import ast
import importlib.util

import pytest

from kukai.modeling.bridge.exec_wrapper import WRAPPER_FOOTER, WRAPPER_HEADER


def _backend_constant(name: str) -> str:
    spec = importlib.util.find_spec("kukai.api.chat_ws")
    if spec is None or not spec.origin:
        pytest.skip("kukai.api.chat_ws not present in this tree")
    with open(spec.origin, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
    pytest.skip(f"{name} not found in chat_ws source")


def test_wrapper_header_matches_backend():
    assert WRAPPER_HEADER == _backend_constant("_WRAPPER_HEADER")


def test_wrapper_footer_matches_backend():
    assert WRAPPER_FOOTER == _backend_constant("_WRAPPER_FOOTER")
