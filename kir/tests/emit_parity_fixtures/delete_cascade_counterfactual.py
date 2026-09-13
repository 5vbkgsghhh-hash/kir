"""Test-only attribution of the «cascade named before the effect» migration.

ONE thing changed the bytes on 2026-09-13: `delete` now READS the circle of
consequences before it acts. `Element.GetDependentElements(null)` is a read; its
result goes into the receipt as `dependents_predicted(_count)`, next to the
`dependents_actual_count` the return of `doc.Delete` already gave, and the
disagreement between the two is named in its own field instead of being left for
the reader to derive.

WHY IT HAD TO HAPPEN. Measured on the owner's live Revit 2023 on 13.09.2026: one
`doc.Delete` took 38 elements with it (10 + 13 + 12 in another pass) —
`/root/kir-live-20260909/live-20260913-slice-cleanup-receipt.json`. The return
value answers «what went» AFTER it is too late to decide; the author who sees the
number BEFORE can change their mind.

WHAT IS **NOT** IN THIS DELTA, and the manifest proves it: the program-level
identity guard changed its words in the same wave
(`open model binding changed` → `identity_changed_since_read` with a next move),
and moved NOTHING — the corpus does not use `expected_identities`. The new op
fields `expected_identity` / `expected_current` emit only for programs that carry
them, and the corpus carries none. So the whole parity delta of that wave — 36
keys, all in the `*setparam_delete` fixtures — belongs to this one function.

THE REVERSAL IS THE FUNCTION ITSELF, not surgery on emitted C#: the exact
pre-change source of `_emit_delete` is retained beside this file and re-executed
into the module, the way the native-readback counterfactual retains its emitters.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
SOURCE_PATH = HERE / "delete_cascade_legacy_sources.json"
LEGACY_MANIFEST = HERE / "corpus_hashes_pre_delete_cascade.json"
LEGACY_GOLDENS = HERE / "golden_hashes_pre_delete_cascade.json"


@contextmanager
def before_the_cascade_was_named(*, require_effect: bool = True):
    """Emit the pre-2026-09-13 `delete` bytes, then put the module back."""
    import importlib

    record = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    assert record["schema"] == "kir-delete-cascade-legacy-sources/1"
    restored = []
    try:
        for row in record["sources"]:
            assert hashlib.sha256(row["source"].encode()).hexdigest() == row["sha256"], row["name"]
            module = importlib.import_module(row["module"])
            current = getattr(module, row["name"])
            exec(compile(row["source"], f"<retained:{row['module']}.{row['name']}>", "exec"),
                 vars(module))
            replacement = getattr(module, row["name"])
            restored.append((module, row["name"], current, replacement))
            # The registry holds the SAME function object, so it must be
            # re-pointed too — otherwise the emitter is replaced and the
            # dispatch still calls today's one, and the "reconstruction" is a
            # no-op that silently matches the current manifest.
            table = getattr(module, "_EMITTERS", None)
            if isinstance(table, dict):
                for key, value in list(table.items()):
                    if value is current:
                        table[key] = replacement
        yield
    finally:
        for module, name, current, replacement in reversed(restored):
            setattr(module, name, current)
            table = getattr(module, "_EMITTERS", None)
            if isinstance(table, dict):
                for key, value in list(table.items()):
                    if value is replacement:
                        table[key] = current
    if require_effect:
        assert restored, ("counterfactual «cascade before the effect»: ни одна функция не "
                          "была подменена — восстановленная база совпала бы с текущей вхолостую")
