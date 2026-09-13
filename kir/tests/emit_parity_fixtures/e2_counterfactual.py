"""Test-only attribution of the E-2 «the last legal writer's outcome» migration.

ONE thing changed on 2026-09-07 under F1/C01 (link E-2, the second half of
«the last legal writer»), and it changes bytes in exactly one way:
the FINAL endpoint witness of a `create_wall` whose result a LATER
`move_elements` of the same program legally shifts now expects the place the
wall ENDS UP — authored p0/p1 plus `geom.program_shift_after` — instead of the
authored intent of the first writer.

Neither predicate, tolerance, message, obligation key NOR STAGE was touched:
E-1 moved a witness between stages, E-2 moves NUMBERS inside one witness that
stays exactly where it was. Both are the same law («the last legal writer
determines the outcome»), applied by the two different means the two cases
allow — and the difference is load-bearing, because the operation stage runs
BEFORE `doc.Regenerate()` and this witness could not have moved there.

The reversal is a single typed field: the synthetic `spec.SYNTHETIC_FINAL_SHIFT`
is stripped from the op the emitter sees, so `endpoint_witness` falls back to
its `shift=(0,0,0)` default and emits the pre-E-2 literals. No regex over C#,
no rewritten fragment. An op that does NOT carry the field is left alone; a
corpus where the field never appears at all is an assertion failure, not a
silently smaller delta.
"""
from contextlib import contextmanager

from kir import authoring, spec

#: Ops whose final witness E-2 taught to compute the outcome.
E2_STAGED_OPS = ("create_wall",)


def strip_e2_shift(op: dict) -> dict:
    """Op without the synthetic outcome — exactly what the emitter saw before E-2."""

    if spec.SYNTHETIC_FINAL_SHIFT not in op:
        return op
    stripped = dict(op)
    stripped.pop(spec.SYNTHETIC_FINAL_SHIFT)
    return stripped


@contextmanager
def without_e2_final_shift():
    """Emit the pre-E-2 bytes without changing the emitter registry shape."""

    originals = {name: authoring._EMITTERS[name] for name in E2_STAGED_OPS}
    seen = {"stripped": 0}

    def wrap(original):
        def emitter(op, version, stamp, isolation="atomic"):
            if spec.SYNTHETIC_FINAL_SHIFT in op:
                seen["stripped"] += 1
            return original(strip_e2_shift(op), version, stamp, isolation)
        return emitter

    try:
        for name, original in originals.items():
            authoring._EMITTERS[name] = wrap(original)
        yield seen
    finally:
        authoring._EMITTERS.update(originals)
    assert seen["stripped"], (
        "E-2 counterfactual: НИ ОДИН оп не нёс "
        f"{spec.SYNTHETIC_FINAL_SHIFT!r} — делта, которую приписывает эта "
        "запись, в корпусе отсутствует, и «восстановленная» база совпала бы "
        "с текущей вхолостую")
