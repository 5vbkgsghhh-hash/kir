"""Test-only attribution of the D-1 type create/reuse migration.

Two things changed on 2026-09-06 under D-1, and only ONE of them moves a frozen
byte:

  * the ADDRESS in the ownership marker became the authored program's stable
    lineage — but only when the envelope carries one. No program in the frozen
    corpus does, so this half changed exactly **0** keys, and there is nothing
    here to reverse;
  * `create_wall_type` gained a reuse-composition guard, emitted on every
    `create_wall_type`. That is the whole delta: **12** keys, one fixture,
    six versions, both isolations.

The reversal is therefore a single exact fragment removal, and it refuses
instead of guessing: a fragment that is missing, or present more than once, is
an assertion failure, not a silently smaller delta.
"""
from contextlib import contextmanager
import re

from kir import authoring

#: Exactly the block that the D-1 patch added. Parentheses taken as-is.
D1_REUSE_GUARD = re.compile(
    r"    var __reuseCs_(?P<s>\w+) = __twin_(?P=s)\.GetCompoundStructure\(\);\n"
    r"    var __reuseL_(?P=s) = __reuseCs_(?P=s) == null \? null : __reuseCs_(?P=s)\.GetLayers\(\);\n"
    r"    bool __reuseSame_(?P=s) = __reuseL_(?P=s) != null && __reuseL_(?P=s)\.Count == __lay_(?P=s)\.Count;\n"
    r"    if \(__reuseSame_(?P=s)\) \{\n"
    r"        for \(int __ri_(?P=s) = 0; __ri_(?P=s) < __lay_(?P=s)\.Count; __ri_(?P=s)\+\+\) \{\n"
    r"            if \(Math\.Abs\(__reuseL_(?P=s)\[__ri_(?P=s)\]\.Width - __lay_(?P=s)\[__ri_(?P=s)\]\.Width\) > U\([^)]*\)\n"
    r"                \|\| __reuseL_(?P=s)\[__ri_(?P=s)\]\.Function != __lay_(?P=s)\[__ri_(?P=s)\]\.Function\n"
    r"                \|\| !__reuseL_(?P=s)\[__ri_(?P=s)\]\.MaterialId\.Equals\(__lay_(?P=s)\[__ri_(?P=s)\]\.MaterialId\)\)\n"
    r"            \{ __reuseSame_(?P=s) = false; break; \}\n"
    r"        \}\n"
    r"    \}\n"
    r"    if \(!__reuseSame_(?P=s)\) \{ [^\n]*\n")


def reverse_d1_reuse_guard(create: str) -> str:
    """Restore the pre-D-1 `create_wall_type` create block."""
    restored, count = D1_REUSE_GUARD.subn("", create)
    assert count == 1, "D-1 counterfactual: expected exactly one reuse guard"
    return restored


@contextmanager
def without_d1_reuse_guard():
    """Emit the pre-D-1 bytes without changing the emitter registry shape."""
    original = authoring._EMITTERS["create_wall_type"]

    def emitter(op, version, stamp, isolation="atomic"):
        decl, create, post, readback = original(op, version, stamp, isolation)
        return decl, reverse_d1_reuse_guard(create), post, readback

    try:
        authoring._EMITTERS["create_wall_type"] = emitter
        yield
    finally:
        authoring._EMITTERS["create_wall_type"] = original
