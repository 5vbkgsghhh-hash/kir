"""G1 — `kir_build`'s schema is a source string, and it is <= 700 B.

The number is not hygiene. Measured 13.09.2026: the schema of the product's
building tool was 64 841 B and the MCP door's `kir_compile` 65 969 B, while
the tool DeepSeek actually builds with (`execute_revit_code`) costs 1 713 B
of schema. An agent that has never seen our JSON cannot be taught it by
shipping more of it.
"""
from __future__ import annotations

import json

from kir.door import registry as R

#: Gate G1. Measured on this tree: 492 B. The ceiling leaves room for one
#: more field and stands far below any return of the program envelope
#: (3 229 B measured).
BUILD_SCHEMA_MAX_BYTES = 700

#: What the envelope would bring back. Kept as a number so the control below
#: is a fact and not a gesture.
PROGRAM_ENVELOPE_BYTES = 3_229


def _schema() -> dict:
    return R.tool("kir_build").schema("expert")


def _bytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode())


def test_the_input_schema_stays_under_the_ratchet():
    size = _bytes(_schema())
    assert size <= BUILD_SCHEMA_MAX_BYTES, (
        f"схема `kir_build` {size} Б превысила храповик "
        f"{BUILD_SCHEMA_MAX_BYTES} Б — проверь, не вернулась ли оболочка "
        f"программы на провод")


def test_the_schema_carries_no_program_envelope():
    schema = _schema()
    props = schema["properties"]
    assert set(schema["required"]) == {"source"}
    for dead in ("program", "program_py", "ops", "defaults", "ir_version",
                 "lineage", "versions", "rehearse", "created", "example"):
        assert dead not in props, (
            f"поле `{dead}` вернулось в схему: агент пишет питон, а не JSON")
    assert props["source"]["type"] == "string"


def test_the_schema_refuses_anything_it_did_not_declare():
    assert _schema()["additionalProperties"] is False


def test_control_putting_the_program_schema_back_goes_red():
    """The control is a FORM, not a function name: whatever brings a
    multi-kilobyte object into `properties` must break the ratchet, no matter
    which generator produced it."""
    fat = dict(_schema())
    fat["properties"] = dict(fat["properties"])
    fat["properties"]["program"] = {"type": "object",
                                    "description": "x" * PROGRAM_ENVELOPE_BYTES}
    assert _bytes(fat) > BUILD_SCHEMA_MAX_BYTES
