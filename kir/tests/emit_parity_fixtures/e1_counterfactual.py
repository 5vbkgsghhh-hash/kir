"""Test-only attribution of the E-1 «last legal writer» stage migration.

ONE thing changed on 2026-09-07 under F1/C01, and it changes bytes in exactly
one way: two already-existing witness checks moved from the FINAL stage to the
OPERATION stage.

  * `set_param` obligation `value_held`;
  * `move_elements` obligation `location`.

Neither predicate, tolerance, message nor obligation key was touched — only
`WitnessCheck.stage`. The whole frozen delta is therefore the SAME fragment
text leaving the `// post <oid>` block and entering an `// operation <oid>`
block behind `int __operationPostStart_<oid> = __post.Count;` with the
existing refusal gate that `authoring.operation_check_gate` already emits for
`change_type`.

The reversal is a single typed field flip on the emitted witness objects: no
regex over C#, no rewritten fragment. A missing check, or a check already on
the final stage, is an assertion failure — not a silently smaller delta.
"""
from contextlib import contextmanager
from dataclasses import replace

from kir import authoring

#: Op -> obligation key whose stage the E-1 patch moved.
E1_STAGED_CHECKS = {"set_param": "value_held", "move_elements": "location"}


def reverse_e1_stage(op_name: str, post):
    """Move the E-1 witness back to the `final` stage, touching nothing else."""

    key = E1_STAGED_CHECKS[op_name]
    seen = 0
    restored = []
    for check in post:
        if check.obligation_key == key:
            assert check.stage == "operation", (
                f"E-1 counterfactual: {op_name}.{key} is not on the operation "
                "stage — the delta this record attributes is not there")
            seen += 1
            check = replace(check, stage="final")
        restored.append(check)
    assert seen == 1, (
        f"E-1 counterfactual: expected exactly one {op_name}.{key} witness, "
        f"got {seen}")
    return restored


@contextmanager
def without_e1_operation_stage():
    """Emit the pre-E-1 bytes without changing the emitter registry shape."""

    originals = {name: authoring._EMITTERS[name] for name in E1_STAGED_CHECKS}

    def wrap(op_name, original):
        def emitter(op, version, stamp, isolation="atomic"):
            decl, create, post, readback = original(op, version, stamp, isolation)
            return decl, create, reverse_e1_stage(op_name, post), readback
        return emitter

    try:
        for name, original in originals.items():
            authoring._EMITTERS[name] = wrap(name, original)
        yield
    finally:
        authoring._EMITTERS.update(originals)
