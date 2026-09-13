"""Test-only attribution of the C-1 per_op refusal-range migration.

This is not an emitter compatibility mode and it is not a way to keep the old
behaviour reachable. It reverses ONE exact emitted fragment in memory — the
``per_op`` operation-stage gate guard — so the frozen manifest of the previous
reviewed record can be reconstructed from the current emitter, and it restores
the function on exit.

The reversal is deliberately narrow and refuses instead of guessing:

* ``atomic`` emissions are returned untouched, because C-1 did not move a
  single atomic byte (measured: 0 of 1419 atomic keys, 309 of 921 per_op);
* a ``per_op`` gate whose guard does not match the current form EXACTLY, or
  matches it more than once, raises — a changed emission must be reviewed and
  recorded, never silently absorbed here.

No native execution, no fixture writes, no historical source reconstruction.
"""
from contextlib import contextmanager
import re
from unittest.mock import patch

from kir import authoring

#: The guard C-1 introduced. Groups: (1) the marker variable suffix,
#: (2) the C# string literal of the op id carried into ``__OpRefuse``.
C1_GUARD = re.compile(
    r'if \(__post\.Count > __operationPostStart_(?P<s>\w+)\) \{ '
    r'var __opRefusal_(?P=s) = String\.Join\(" ; ", __post\.Skip\(__operationPostStart_(?P=s)\)\); '
    r'__post\.RemoveRange\(__operationPostStart_(?P=s), __post\.Count - __operationPostStart_(?P=s)\); '
    r'throw __OpRefuse\((?P<oid>"(?:[^"\\]|\\.)*"), __opRefusal_(?P=s)\); \}')


def _legacy_guard(match: "re.Match") -> str:
    s, oid = match.group("s"), match.group("oid")
    return (f'if (__post.Count > __operationPostStart_{s}) {{ '
            f'throw __OpRefuse({oid}, String.Join(" ; ", '
            f'__post.Skip(__operationPostStart_{s}))); }}')


def reverse_c1_gate(operation_gate: str) -> str:
    """Restore the pre-C-1 per_op guard of ONE rendered operation gate."""
    restored, count = C1_GUARD.subn(_legacy_guard, operation_gate)
    assert count == 1, "C-1 counterfactual: expected exactly one per_op gate guard"
    return restored


def reverse_c1_gates(fragment: str) -> tuple[str, int]:
    """Restore every per_op gate guard in an arbitrary emitted fragment.

    Used where an emitter renders SEVERAL gates itself (create_group renders
    one per member), so ``exactly one`` would be the wrong law. Returns the
    restored text and how many guards were reversed; zero is legal — an op
    without operation-stage checks has no guard at all.
    """
    return C1_GUARD.subn(_legacy_guard, fragment)


@contextmanager
def without_c1_range_cleanup():
    """Emit the pre-C-1 bytes without changing the emitter registry."""
    current = authoring.operation_check_gate

    def gate(oid, operation_cs, isolation):
        rendered = current(oid, operation_cs, isolation)
        if not rendered or isolation != "per_op":
            return rendered
        return reverse_c1_gate(rendered)

    with patch.object(authoring, "operation_check_gate", gate):
        yield
