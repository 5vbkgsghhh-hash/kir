"""Test-only attribution of the «identity capture for every create op» migration.

ONE thing changed on 2026-09-13 (audit E1, the producer half): the shared
receipt seam `_readback_block` is now called with `identity_version` from EVERY
emitter that stands on it — 24 call sites of 24 — instead of three. Nothing else
moved: no predicate, no tolerance, no message, no obligation key, no stage, no
refusal. Each affected emission gains the same three rows the three original
emitters already produced — `element_identity`, `element_identity_status`,
`element_identity_reason` — written AFTER the op's commit, by the one reader
`kir/emit_core.py::element_identity_readback_cs`.

WHY IT HAD TO HAPPEN. Measured on the owner's live Revit 2023 on 13.09.2026:
republishing the same section, one number changed, gave walls 4 → 8 → 12 and
floors 1 → 2 → 3 with `ok: true`
(`/root/kir-live-20260909/live-20260913-slice-opening-receipt.json`). A program
cannot say «this output is the element I made last time» unless the element's
identity comes back in the receipt, and 63 of 71 create ops returned none.

THE REVERSAL IS EXACT AND SELECTIVE, which is the whole difficulty. Three call
sites carried `identity_version` BEFORE this migration — `_emit_wall`,
`_emit_floor` and `_emit_floor_contour`, all in `kir.authoring`. Dropping the
argument everywhere would over-reverse and reconstruct a manifest that never
existed. So the wrapper reads the CALLER's name (`sys._getframe(1)`) and keeps
the argument for exactly those three. The context manager refuses to be vacuous:
it asserts that it both dropped and kept at least one, so a corpus that exercises
neither cannot pass as a reconstructed baseline.
"""
from contextlib import contextmanager
import sys

from kir import arch_emit, authoring, mep_emit, opening_emit, site_emit, struct_emit

#: The three emitters that already captured identity before 2026-09-13.
IDENTITY_BEFORE = frozenset({"_emit_wall", "_emit_floor", "_emit_floor_contour"})

#: Every module that holds its own reference to the shared seam.
SEAM_MODULES = (authoring, struct_emit, arch_emit, mep_emit, opening_emit, site_emit)


@contextmanager
def without_universal_identity_capture(*, require_effect: bool = True):
    """Emit the pre-2026-09-13 bytes without touching the emitter registry.

    ``require_effect`` — assert on exit that the reversal actually fired. It
    belongs where a reconstruction is CLAIMED (a contract that re-emits the
    corpus and compares it to a retained manifest). A contract that merely needs
    the historical emitters in scope, and emits nothing, must pass False: an
    assertion that a no-op did nothing is noise, not a guard.
    """

    originals = {module: module._readback_block for module in SEAM_MODULES}
    seen = {"dropped": 0, "kept": 0}

    def wrap(original):
        def readback(*args, **kwargs):
            if "identity_version" in kwargs:
                caller = sys._getframe(1).f_code.co_name
                if caller in IDENTITY_BEFORE:
                    seen["kept"] += 1
                else:
                    kwargs = dict(kwargs)
                    kwargs.pop("identity_version")
                    seen["dropped"] += 1
            return original(*args, **kwargs)

        return readback

    try:
        for module, original in originals.items():
            module._readback_block = wrap(original)
        yield seen
    finally:
        for module, original in originals.items():
            module._readback_block = original
    if not require_effect:
        return
    assert seen["dropped"], (
        "counterfactual «capture for every create»: НИ У ОДНОГО вызова не был "
        "снят identity_version — делта, которую приписывает эта запись, в "
        "корпусе отсутствует, и «восстановленная» база совпала бы с текущей "
        "вхолостую")
    assert seen["kept"], (
        "counterfactual «capture for every create»: ни один из трёх прежних "
        "эмиттеров (_emit_wall/_emit_floor/_emit_floor_contour) не сработал — "
        "значит обратный ход не проверил, что он ИЗБИРАТЕЛЕН, и мог бы "
        "переоткатить то, что было захвачено и до миграции")
