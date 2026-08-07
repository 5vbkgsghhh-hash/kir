"""Tamper laws for emitted-artifact -> compile-unit provenance."""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import unittest
from unittest.mock import patch

from kukai.compiler_unit import wrap_execute_body
from kukai.ir.compiler import compile_program
from kukai.ir.compile_receipt import (
    ArtifactBinding,
    CompileReceipt,
    CompileReceiptError,
    CompileUnitBinding,
    HistoricalCompileReceiptEvidence,
    validate_compile_receipt_wire,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


PROGRAM = {
    "ir_version": "1.0",
    "intent": "compile receipt contract",
    "ops": [{
        "op": "create_wall",
        "id": "W1",
        "p0_mm": [0, 0],
        "p1_mm": [6000, 0],
        "level": {"by": "name", "value": "Этаж 1"},
    }],
}


def _canonical_digest(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rehash_receipt(receipt):
    receipt["receipt_digest"] = _canonical_digest({
        key: value
        for key, value in receipt.items()
        if key != "receipt_digest"
    })


class TestCompileReceipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        output = compile_program(
            PROGRAM,
            revit_version="2026",
            snapshot=GROUND_SNAPSHOT,
        )
        if not output.ok or output.emitted is None:
            raise AssertionError(
                [item.as_dict() for item in output.diagnostics])
        cls.artifact = output.emitted
        cls.receipt = CompileReceipt.expected_for(output.emitted)

    def test_receipt_round_trip_is_deterministic_and_source_free(self):
        payload = self.receipt.to_dict()
        parsed = CompileReceipt.from_dict(copy.deepcopy(payload))

        self.assertEqual(parsed, self.receipt)
        self.assertEqual(parsed.to_dict(), payload)
        self.assertNotIn(self.artifact.source, str(payload))
        self.assertRegex(parsed.receipt_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(
            parsed.artifact.artifact_digest,
            self.artifact.artifact_digest,
        )

    def test_verified_unit_is_exact_canonical_wrapper(self):
        wrapped = self.receipt.verified_compile_unit(self.artifact)

        self.assertEqual(wrapped, wrap_execute_body(self.artifact.source))
        self.assertEqual(
            len(wrapped.encode("utf-8")),
            self.receipt.compile_unit.source_bytes,
        )
        self.assertEqual(
            self.receipt.verified_wrapped_source(wrapped),
            self.artifact.source,
        )

    def test_noncanonical_wrapper_and_body_tampering_are_rejected(self):
        wrapped = self.receipt.verified_compile_unit(self.artifact)
        cases = (
            wrapped.replace("namespace Kukai", "namespace Other", 1),
            wrapped.replace("            ", "           ", 1),
            wrapped.replace("KIR", "K1R", 1),
            wrapped + " ",
        )
        for forged in cases:
            with self.subTest(forged=forged[:40]):
                with self.assertRaises(CompileReceiptError):
                    self.receipt.verified_wrapped_source(forged)

    def test_parser_rejects_field_shape_and_scalar_tampering(self):
        cases = (
            (("receipt_digest",), "0" * 64),
            (("schema",), "kir-compile-receipt/999"),
            (("compiler_contract",), "parse-only/1"),
            (("artifact", "source_sha256"), "0" * 64),
            (("artifact", "source_bytes"), True),
            (("artifact", "artifact_digest"), "0" * 64),
            (("compile_unit", "wrapper_contract"), "other-wrapper/1"),
            (("compile_unit", "source_sha256"), "0" * 64),
            (("compile_unit", "source_bytes"), True),
            (("target", "profile_id"), "private-profile"),
            (("target", "revit_year"), "2025"),
            (("target", "profile_digest"), "0" * 64),
            (("target", "manifest_digest"), "0" * 64),
        )
        for path, replacement in cases:
            with self.subTest(path=path):
                payload = copy.deepcopy(self.receipt.to_dict())
                cursor = payload
                for key in path[:-1]:
                    cursor = cursor[key]
                cursor[path[-1]] = replacement
                with self.assertRaises(CompileReceiptError):
                    CompileReceipt.from_dict(payload)

        extra = copy.deepcopy(self.receipt.to_dict())
        extra["service_says_ok"] = True
        with self.assertRaisesRegex(CompileReceiptError, "fields mismatch"):
            CompileReceipt.from_dict(extra)

    def test_content_corruption_is_rejected_before_either_manifest_loader(self):
        corrupt = []

        artifact = copy.deepcopy(self.receipt.to_dict())
        artifact["artifact"]["artifact_digest"] = "f" * 64
        _rehash_receipt(artifact)
        corrupt.append(artifact)

        compile_unit = copy.deepcopy(self.receipt.to_dict())
        compile_unit["compile_unit"]["wrapper_contract"] = "other-wrapper/1"
        _rehash_receipt(compile_unit)
        corrupt.append(compile_unit)

        target_link = copy.deepcopy(self.receipt.to_dict())
        target_link["target"]["profile_digest"] = "f" * 64
        _rehash_receipt(target_link)
        corrupt.append(target_link)

        root = copy.deepcopy(self.receipt.to_dict())
        root["receipt_digest"] = "f" * 64
        corrupt.append(root)

        with (
            patch(
                "kukai.ir.compile_receipt.load_target_profile_manifest",
                side_effect=AssertionError("current manifest loader was called"),
            ),
            patch(
                "kukai.ir.compile_receipt.load_archived_target_profile_manifest",
                side_effect=AssertionError("archive manifest loader was called"),
            ),
        ):
            for parser in (
                CompileReceipt.from_dict,
                HistoricalCompileReceiptEvidence.from_dict,
            ):
                for payload in corrupt:
                    with self.subTest(parser=parser.__qualname__, payload=payload):
                        with self.assertRaises(CompileReceiptError):
                            parser(copy.deepcopy(payload))

    def test_manifest_neutral_validation_has_no_executable_authority(self):
        with (
            patch(
                "kukai.ir.compile_receipt.load_target_profile_manifest",
                side_effect=AssertionError("current manifest loader was called"),
            ),
            patch(
                "kukai.ir.compile_receipt.load_archived_target_profile_manifest",
                side_effect=AssertionError("archive manifest loader was called"),
            ),
        ):
            validated = validate_compile_receipt_wire(self.receipt.to_dict())

        self.assertEqual(validated.to_dict(), self.receipt.to_dict())
        self.assertFalse(hasattr(validated, "verified_compile_unit"))
        self.assertFalse(hasattr(validated, "verified_wrapped_source"))

    def test_self_consistent_alternate_source_cannot_bind_to_artifact(self):
        forged_artifact = dataclasses.replace(
            self.receipt.artifact,
            source_sha256="0" * 64,
            artifact_digest="",
        )
        forged = dataclasses.replace(
            self.receipt,
            artifact=forged_artifact,
            receipt_digest="",
        )

        with self.assertRaisesRegex(
            CompileReceiptError, "not bound to this emitted artifact"
        ):
            forged.verified_compile_unit(self.artifact)

    def test_self_consistent_alternate_compile_unit_cannot_execute(self):
        forged_unit = dataclasses.replace(
            self.receipt.compile_unit,
            source_sha256="0" * 64,
        )
        forged = dataclasses.replace(
            self.receipt,
            compile_unit=forged_unit,
            receipt_digest="",
        )

        with self.assertRaisesRegex(
            CompileReceiptError, "not bound to this emitted artifact"
        ):
            forged.verified_compile_unit(self.artifact)

    def test_untyped_and_empty_inputs_fail_closed(self):
        with self.assertRaises(TypeError):
            CompileReceipt.expected_for(object())  # type: ignore[arg-type]
        with self.assertRaises(CompileReceiptError):
            CompileUnitBinding.from_source("")
        with self.assertRaises(TypeError):
            ArtifactBinding.from_emitted(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
