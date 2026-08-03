"""Wave A2 byte-guarantee: the witness-model render reproduces the OLD bytes.

The fixture `emit_parity_fixtures/corpus_hashes.json` froze SHA-256 hashes of
607 emissions (golden + scope-contract + gate-authoring + pbt/query corpus,
6 versions, atomic + per_op) BEFORE the refactor.  This test recomputes every
emission and compares.  Any divergence fails the wave — updating the fixture
is forbidden ("обновим голден" is not an option here); the ONLY sanctioned
exemptions are listed in _INTENDED_CHANGES with their rationale and their own
replacement pin (a new golden / dedicated test).
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_parity_queue.jsonl"))

from kukai.ir.tests.emit_parity_fixtures.generate_fixtures import (  # noqa: E402
    FIXTURE_PATH,
    INTENDED_CHANGES,
    emit_corpus,
)

# An exempted key must be covered by its OWN pin elsewhere (никогда просто
# вычеркнут) — see INTENDED_CHANGES rationales in the generator (one source).


def _exempt(key: str) -> bool:
    return any(key.startswith(prefix) for prefix in INTENDED_CHANGES)


class ByteParity(unittest.TestCase):
    def test_emit_model_byte_parity(self) -> None:
        frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        current = emit_corpus()
        mismatched = sorted(
            key for key in frozen
            if not _exempt(key) and current.get(key) != frozen[key])
        missing = sorted(
            key for key in frozen
            if not _exempt(key) and key not in current)
        self.assertEqual(
            mismatched, [],
            f"{len(mismatched)} emissions diverged from the frozen bytes; "
            "первые: " + ", ".join(mismatched[:10]))
        self.assertEqual(missing, [], "frozen emissions disappeared")


class WitnessModelContract(unittest.TestCase):
    """The by-construction guarantees of the model itself (wave A2 core)."""

    def test_verdictless_check_unconstructible(self) -> None:
        from kukai.ir.emit_model import EmitModelError, WitnessCheck
        with self.assertRaises(EmitModelError):
            WitnessCheck(obligation_key="x", reader_cs="var __a = 1;\n",
                         verdict_cs="// no verdict\n", message="m")

    def test_empty_post_refused(self) -> None:
        from kukai.ir.emit_model import EmitModelError, render_post
        with self.assertRaises(EmitModelError):
            render_post("OP", [])

    def test_duplicate_keys_refused(self) -> None:
        from kukai.ir.emit_model import (
            EmitModelError, WitnessCheck, render_post,
        )
        check = WitnessCheck(
            obligation_key="k", reader_cs="",
            verdict_cs="    __post.Add(\"m\");\n", message="m")
        with self.assertRaises(EmitModelError):
            render_post("OP", [check, check])

    def test_bare_post_same_validation(self) -> None:
        from kukai.ir.emit_model import BarePost, EmitModelError, WitnessCheck
        with self.assertRaises(EmitModelError):
            BarePost(())
        check = WitnessCheck(
            obligation_key="k", reader_cs="",
            verdict_cs="__post.Add(\"m\");\n", message="m")
        with self.assertRaises(EmitModelError):
            BarePost((check, check))

    def test_render_frame_matches_legacy_shape(self) -> None:
        from kukai.ir.emit_model import WitnessCheck, render_post
        check = WitnessCheck(
            obligation_key="k", reader_cs="    var __x = 1;\n",
            verdict_cs="    if (__x != 1) __post.Add(\"m\");\n",
            message="m")
        self.assertEqual(
            render_post("OP", [check]),
            "// post OP\n{\n    var __x = 1;\n"
            "    if (__x != 1) __post.Add(\"m\");\n}")


if __name__ == "__main__":
    unittest.main()
