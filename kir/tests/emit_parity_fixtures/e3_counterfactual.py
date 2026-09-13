"""Test-only attribution of the E-3 «the last legal writer's outcome, all eight»
migration.

ONE thing changed on 2026-09-07 under F1/C01 (link E-3, the third part of
«the last legal writer»), and it changes bytes in exactly one way:
the FINAL endpoint witness of EVERY REMAINING create-op whose result a later
`move_elements` of the same program legally shifts now expects the place the
element ENDS UP — authored p0/p1 plus `geom.program_shift_after` — instead of
the authored intent of the first writer. E-2 taught this to `create_wall`
alone and NAMED the other seven places as its own limit; E-3 closes the list.

Neither predicate, tolerance, message, obligation key NOR STAGE was touched —
same as E-2, and for the same reason: the operation stage runs BEFORE
`doc.Regenerate()`, so this witness could not have moved there.

The reversal is the SAME typed field and the SAME strip as E-2
(`e2_counterfactual.strip_e2_shift` is imported, not re-written: two copies of
one reversal would part company on the first edit). What differs is the SET
OF OPS: `without_e3_final_shift` touches the eight ops E-3 added and LEAVES
`create_wall` alone, so reversing E-3 lands exactly on the E-2 manifest and
not one step further. An empty strip count is an assertion failure, not a
silently smaller delta.
"""
from contextlib import contextmanager

from kir import authoring, spec
from kir.tests.emit_parity_fixtures.e2_counterfactual import strip_e2_shift

#: Ops whose final witness learned to compute the outcome specifically in E-3.
#: `create_wall` IS NOT INCLUDED HERE — it belongs to E-2, and stripping it
#: here would attribute someone else's delta to this record.
E3_STAGED_OPS = (
    "create_pipe", "create_duct", "create_cable_tray", "create_conduit",
    "create_pipe_placeholder", "create_duct_placeholder",
    "create_beam", "create_truss",
)


@contextmanager
def without_e3_final_shift():
    """Emit the pre-E-3 bytes without changing the emitter registry shape."""

    originals = {name: authoring._EMITTERS[name] for name in E3_STAGED_OPS}
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
        "E-3 counterfactual: НИ ОДИН из восьми опов не нёс "
        f"{spec.SYNTHETIC_FINAL_SHIFT!r} — делта, которую приписывает эта "
        "запись, в корпусе отсутствует, и «восстановленная» база совпала бы "
        "с текущей вхолостую")
